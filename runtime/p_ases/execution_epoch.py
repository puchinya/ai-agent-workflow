"""Exact-ADC-authorized Issue #71 V2 execution-epoch bootstrap.

This module never reads or writes ExecutionBinding V1. The incomplete V1 Intent
is verified as retired history; only a complete V2 journal activates this epoch.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .adc import ADCError, VerifiedADC, verify_adc, verify_adc_generation
from .execution import ExecutionError, SHA40, SHA256
from .github import GitHub, GitHubError
from .git import (
    GitError, current_branch, discover_repository, head_sha40,
    is_ancestor, remote_branch_sha, verify_remote_repository,
)
from .path_safety import path_has_symlink


REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
OWNER_ID = 3744776
ISSUE_NUMBER = 71
ISSUE_ID = 6135294757

ADC_COMMENT_ID = 6874553609
ADC_SHA256 = "aa0e69210dec4f2df1b069eafc4f5ce99ca3a71465a7ca59da3a05301fa023a4"
PREDECESSOR_ADC_COMMENT_ID = 6872348866
PREDECESSOR_ADC_SHA256 = "8b89b61d554f3b6e3be890a30e4e8146dabcef2a361aafc7c07528cbae0e9af9"
OLD_ADC_COMMENT_ID = 6825088328
OLD_ADC_SHA256 = "1d17c6d9ee18a946a6aafe8e22c890e15de217a57c36a33c81e4f82f14c6b0b5"
OLD_PHASE_COMMENT_ID = 6809971791
OLD_PHASE_SHA256 = "1e7706b1c172ee284d67d712ac1d2cb92ec5dfdebfb303826eea934813e0bd98"
RETIRED_INTENT_COMMENT_ID = 6872950816
RETIRED_INTENT_SHA256 = "a5772c31a06e26991430759a3568f9c20e7e4e7c77090de716031ce9f84bfb12"
HISTORICAL_BINDING_SHA256 = "b828daa98c9cab2c5243019e71158231e43f8c06826c7c31e6ca48ea3f5ac868"
ISSUE_BODY_SHA256 = "5f910c8de4cbe3ec391edf18b69fabe0f4c42880b59357083647a8b06e7a6a36"
BASE_REF = "main"
BASE_SHA40 = "07481c4b451a81750a6c2e1a6a18bdfd4e3459c2"
BRANCH_REF = "pases/issue-71-local-activation-v2-epoch-2"
RETIRED_BRANCH_REF = "pases/issue-71-local-activation-v2-new-epoch"

REASON = (
    "Continue Issue #71 as the same owning Issue after the first successor ADC migration "
    "stopped with an incomplete Intent. Create a new execution epoch only under this "
    "successor contract. Do not claim that the old Binding, worktree, or epoch was recovered."
)

AUTH_SCHEMA = "PASES_EXECUTION_EPOCH_AUTHORIZATION_V2"
V1_INTENT_SCHEMA = "PASES_EXECUTION_EPOCH_RESTART_INTENT_V1"
V1_APPLIED_SCHEMA = "PASES_EXECUTION_EPOCH_RESTART_APPLIED_V1"
INTENT_SCHEMA = "PASES_EXECUTION_EPOCH_RESTART_INTENT_V2"
APPLIED_SCHEMA = "PASES_EXECUTION_EPOCH_RESTART_APPLIED_V2"
EPOCH_SCHEMA = "PASES_ISSUE_EXECUTION_EPOCH_V2"
ATTACHMENT_SCHEMA = "PASES_EXECUTION_EPOCH_ATTACHMENT_V2"
AUTH_START = f"<!-- {AUTH_SCHEMA}\n"
INTENT_START = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_START = f"<!-- {APPLIED_SCHEMA}\n"
V1_INTENT_START = f"<!-- {V1_INTENT_SCHEMA}\n"
V1_APPLIED_START = f"<!-- {V1_APPLIED_SCHEMA}\n"

AUTHORIZATION = {
    "base_ref": BASE_REF,
    "base_sha40": BASE_SHA40,
    "branch_ref": BRANCH_REF,
    "from_phase": "ready",
    "historical_binding_provenance": "UNVERIFIED",
    "historical_binding_sha256": HISTORICAL_BINDING_SHA256,
    "issue_body_sha256": ISSUE_BODY_SHA256,
    "max_applications": 1,
    "old_phase_generation_comment_id": OLD_PHASE_COMMENT_ID,
    "old_phase_generation_sha256": OLD_PHASE_SHA256,
    "owner_id": OWNER_ID,
    "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
    "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "retired_intent_body_sha256": RETIRED_INTENT_SHA256,
    "retired_intent_comment_id": RETIRED_INTENT_COMMENT_ID,
    "schema": AUTH_SCHEMA,
    "target_issue": ISSUE_NUMBER,
    "to_phase": "requirements",
}
COMMON_FIELDS = {
    "actor_id", "adc_comment_id", "adc_sha256", "authorization_sha256",
    "base_ref", "base_sha40", "branch_ref", "created_at", "epoch_id",
    "historical_binding_provenance", "historical_binding_sha256",
    "issue_body_sha256", "issue_id", "issue_number", "labels_after",
    "labels_before", "old_adc_comment_id", "old_adc_sha256",
    "old_phase_comment_id", "old_phase_sha256", "owner_id", "from_phase", "to_phase",
    "predecessor_adc_comment_id",
    "predecessor_adc_sha256", "reason", "repository", "repository_id",
    "retired_intent_body_sha256", "retired_intent_comment_id", "schema",
}
INTENT_FIELDS = COMMON_FIELDS
APPLIED_FIELDS = COMMON_FIELDS | {"applied_at", "intent_body_sha256", "intent_comment_id"}
PHASES = {
    "requirements", "specification", "design", "ready", "execution",
    "verification", "integration", "user-review",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ExecutionEpochError(ValueError):
    """The approved epoch authorization or its immutable state is invalid."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutionEpochError("execution epoch JSON has duplicate fields")
        result[key] = value
    return result


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def epoch_paths(root: Path) -> tuple[Path, Path]:
    state = Path(root) / ".p_ases" / "state" / str(ISSUE_NUMBER)
    return state / "execution-epoch.json", state / "execution-epoch-attachment.json"


@dataclass(frozen=True)
class IssueExecutionEpoch:
    repository: str
    issue_number: int
    adc_comment_id: int
    adc_sha256: str
    base_ref: str
    base_sha40: str
    branch_ref: str
    epoch_id: str
    intent_comment_id: int
    intent_body_sha256: str
    applied_comment_id: int
    applied_body_sha256: str
    attachment_id: str
    historical_binding_sha256: str
    historical_binding_provenance: str = "UNVERIFIED"
    schema: str = EPOCH_SCHEMA

    @property
    def sha256(self) -> str:
        return _sha(self._payload_bytes())

    def validate(self) -> "IssueExecutionEpoch":
        if (self.schema != EPOCH_SCHEMA or self.repository != REPOSITORY
                or self.issue_number != ISSUE_NUMBER):
            raise ExecutionEpochError("execution epoch identity is for the wrong Issue or schema")
        if (self.adc_comment_id != ADC_COMMENT_ID or self.adc_sha256 != ADC_SHA256
                or self.base_ref != BASE_REF or self.base_sha40 != BASE_SHA40
                or self.branch_ref != BRANCH_REF):
            raise ExecutionEpochError("execution epoch identity differs from the exact successor ADC")
        for name, value in (
            ("epoch ID", self.epoch_id), ("ADC digest", self.adc_sha256),
            ("Intent digest", self.intent_body_sha256), ("Applied digest", self.applied_body_sha256),
            ("attachment ID", self.attachment_id), ("Binding history digest", self.historical_binding_sha256),
        ):
            if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                raise ExecutionEpochError(f"execution epoch {name} is invalid")
        if (type(self.intent_comment_id) is not int or self.intent_comment_id < 1
                or type(self.applied_comment_id) is not int or self.applied_comment_id <= self.intent_comment_id):
            raise ExecutionEpochError("execution epoch journal comment ordering is invalid")
        if self.historical_binding_provenance != "UNVERIFIED":
            raise ExecutionEpochError("historical Binding provenance must remain UNVERIFIED")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "adc_comment_id": self.adc_comment_id,
            "adc_sha256": self.adc_sha256,
            "applied_body_sha256": self.applied_body_sha256,
            "applied_comment_id": self.applied_comment_id,
            "attachment_id": self.attachment_id,
            "base_ref": self.base_ref,
            "base_sha40": self.base_sha40,
            "branch_ref": self.branch_ref,
            "epoch_id": self.epoch_id,
            "historical_binding_provenance": self.historical_binding_provenance,
            "historical_binding_sha256": self.historical_binding_sha256,
            "intent_body_sha256": self.intent_body_sha256,
            "intent_comment_id": self.intent_comment_id,
            "issue_number": self.issue_number,
            "repository": self.repository,
            "schema": self.schema,
        }

    def _payload_bytes(self) -> bytes:
        return _canonical(self.payload()).encode("utf-8")

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["epoch_sha256"] = self.sha256
        return (_canonical(value) + "\n").encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "IssueExecutionEpoch":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutionEpochError("execution epoch record is invalid JSON") from exc
        expected = {
            "adc_comment_id", "adc_sha256", "applied_body_sha256", "applied_comment_id",
            "attachment_id", "base_ref", "base_sha40", "branch_ref", "epoch_id",
            "epoch_sha256", "historical_binding_provenance", "historical_binding_sha256",
            "intent_body_sha256", "intent_comment_id", "issue_number", "repository", "schema",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ExecutionEpochError("execution epoch record has unknown or missing fields")
        supplied = value.pop("epoch_sha256")
        epoch = cls(**value).validate()
        if supplied != epoch.sha256 or epoch.to_bytes() != raw:
            raise ExecutionEpochError("execution epoch record digest or bytes are invalid")
        return epoch


def _comment_fp(row: Any, comment_id: int) -> tuple[Any, ...]:
    if not isinstance(row, dict) or row.get("id") != comment_id:
        raise ExecutionEpochError("epoch journal comment identity is incomplete")
    user = row.get("user")
    if (not isinstance(user, dict) or user.get("id") != OWNER_ID
            or user.get("type") != "User" or not isinstance(user.get("login"), str)
            or not user.get("login")):
        raise ExecutionEpochError("epoch journal comment is not authored by the verified owner")
    body, created_at = row.get("body"), row.get("created_at")
    if not isinstance(body, str) or not isinstance(created_at, str) or not created_at.endswith("Z"):
        raise ExecutionEpochError("epoch journal comment body or timestamp is incomplete")
    expected = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}",
        f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
    )
    actual = (row.get("issue_url"), row.get("html_url"), row.get("url"))
    if tuple(item.casefold() if isinstance(item, str) else None for item in actual) != tuple(
            item.casefold() for item in expected):
        raise ExecutionEpochError("epoch journal comment URLs do not match Issue #71")
    return (body, created_at, user["id"], user["login"].casefold(), user["type"], *actual)


def _read_comment_triplet(github: GitHub, comment_id: int) -> dict[str, Any]:
    try:
        first = github.issue_comment(ISSUE_NUMBER, comment_id)
        rows = github.issue_comments(ISSUE_NUMBER)
        listed = [row for row in rows if isinstance(row, dict) and row.get("id") == comment_id]
        last = github.issue_comment(ISSUE_NUMBER, comment_id)
    except GitHubError as exc:
        raise ExecutionEpochError(f"epoch comment readback failed: {exc}") from exc
    if len(listed) != 1:
        raise ExecutionEpochError("epoch comment is missing or duplicated in the complete list")
    if _comment_fp(first, comment_id) != _comment_fp(listed[0], comment_id) or \
            _comment_fp(listed[0], comment_id) != _comment_fp(last, comment_id):
        raise ExecutionEpochError("epoch comment changed during direct/list/direct readback")
    return last


def _issue_fp(issue: Any) -> tuple[Any, ...]:
    if (not isinstance(issue, dict) or issue.get("number") != ISSUE_NUMBER
            or issue.get("id") != ISSUE_ID or issue.get("state") not in {"open", "closed"}
            or issue.get("pull_request") is not None
            or str(issue.get("repository_url", "")).casefold()
                != f"https://api.github.com/repos/{REPOSITORY}".casefold()):
        raise ExecutionEpochError("Issue #71 identity or state is invalid")
    labels = issue.get("labels")
    if not isinstance(labels, list) or any(not isinstance(row, dict) for row in labels):
        raise ExecutionEpochError("Issue #71 labels are incomplete")
    names = [row.get("name") for row in labels]
    if any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
        raise ExecutionEpochError("Issue #71 labels are malformed or duplicated")
    body = issue.get("body")
    if not isinstance(body, str):
        raise ExecutionEpochError("Issue #71 body is unavailable")
    return (issue["number"], issue["id"], issue["state"], tuple(sorted(names)),
            _sha(body.encode("utf-8")), issue.get("repository_url"))


def _issue_snapshot(github: GitHub) -> tuple[dict[str, Any], tuple[str, ...]]:
    try:
        first = github.issue(ISSUE_NUMBER)
        all_issues = github.issues_all()
        listed = [row for row in all_issues if isinstance(row, dict) and row.get("number") == ISSUE_NUMBER]
        last = github.issue(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ExecutionEpochError(f"Issue #71 readback failed: {exc}") from exc
    if len(listed) != 1 or _issue_fp(first) != _issue_fp(listed[0]) or \
            _issue_fp(listed[0]) != _issue_fp(last):
        raise ExecutionEpochError("Issue #71 changed or is duplicated during direct/list/direct readback")
    return last, _issue_fp(last)[3]


def _verify_repo_actor(github: GitHub) -> None:
    try:
        metadata = github.repository_metadata()
        actor = github.authenticated_user()
    except GitHubError as exc:
        raise ExecutionEpochError(f"repository or actor verification failed: {exc}") from exc
    owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
    if (github.repo.casefold() != REPOSITORY.casefold()
            or metadata.get("id") != REPOSITORY_ID or owner.get("id") != OWNER_ID
            or actor.get("id") != OWNER_ID or actor.get("type") != "User"):
        raise ExecutionEpochError("authenticated owner or repository ID differs from the approved subject")


def _marker(adc: VerifiedADC) -> tuple[dict[str, Any], str]:
    if (adc.pointer.comment_id != ADC_COMMENT_ID or adc.pointer.sha256 != ADC_SHA256
            or adc.pointer.state != "approved" or adc.contract.sha256 != ADC_SHA256):
        raise ExecutionEpochError("current approved ADC pointer is not the exact epoch-2 contract")
    text = adc.contract.content.decode("utf-8", errors="strict")
    if text.count(AUTH_START) != 1:
        raise ExecutionEpochError("approved ADC must contain one exact V2 epoch authorization marker")
    start = text.index(AUTH_START)
    end = text.find("\n-->", start + len(AUTH_START))
    if end < 0:
        raise ExecutionEpochError("V2 epoch authorization marker is not closed")
    raw = text[start + len(AUTH_START):end]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ExecutionEpochError("V2 epoch authorization marker JSON is malformed") from exc
    if not isinstance(value, dict) or set(value) != set(AUTHORIZATION) or value != AUTHORIZATION:
        raise ExecutionEpochError("V2 epoch authorization marker differs from its exact approved values")
    if _canonical(value) != raw:
        raise ExecutionEpochError("V2 epoch authorization marker is not canonical")
    if REASON not in text:
        raise ExecutionEpochError("approved ADC does not bind the exact epoch-2 reason")
    marker_bytes = text[start:end + len("\n-->")].encode("utf-8")
    return value, _sha(marker_bytes)


def _read_v2_payload(body: str, schema: str, fields: set[str]) -> dict[str, Any]:
    start = f"<!-- {schema}\n"
    if not body.startswith(start) or not body.endswith("\n-->"):
        raise ExecutionEpochError("V2 epoch journal comment framing is invalid")
    raw = body[len(start):-len("\n-->")]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ExecutionEpochError("V2 epoch journal JSON is malformed") from exc
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != schema:
        raise ExecutionEpochError("V2 epoch journal has unknown or missing fields")
    if _canonical(value) != raw:
        raise ExecutionEpochError("V2 epoch journal JSON is not canonical")
    _validate_payload(value, schema)
    return value


def _validate_payload(value: dict[str, Any], schema: str) -> None:
    if value.get("repository") != REPOSITORY:
        raise ExecutionEpochError("V2 epoch journal repository is invalid")
    for key, expected in (
        ("repository_id", REPOSITORY_ID), ("issue_number", ISSUE_NUMBER), ("issue_id", ISSUE_ID),
        ("owner_id", OWNER_ID), ("actor_id", OWNER_ID), ("adc_comment_id", ADC_COMMENT_ID),
        ("predecessor_adc_comment_id", PREDECESSOR_ADC_COMMENT_ID),
        ("old_adc_comment_id", OLD_ADC_COMMENT_ID), ("old_phase_comment_id", OLD_PHASE_COMMENT_ID),
        ("retired_intent_comment_id", RETIRED_INTENT_COMMENT_ID),
    ):
        if type(value.get(key)) is not int or value[key] != expected:
            raise ExecutionEpochError(f"V2 epoch journal {key} is invalid")
    for key, expected in (
        ("adc_sha256", ADC_SHA256), ("predecessor_adc_sha256", PREDECESSOR_ADC_SHA256),
        ("old_adc_sha256", OLD_ADC_SHA256), ("old_phase_sha256", OLD_PHASE_SHA256),
        ("retired_intent_body_sha256", RETIRED_INTENT_SHA256),
        ("historical_binding_sha256", HISTORICAL_BINDING_SHA256),
        ("issue_body_sha256", ISSUE_BODY_SHA256),
    ):
        if value.get(key) != expected:
            raise ExecutionEpochError(f"V2 epoch journal {key} differs from authorization")
    if (value.get("historical_binding_provenance") != "UNVERIFIED"
            or value.get("base_ref") != BASE_REF or value.get("base_sha40") != BASE_SHA40
            or value.get("branch_ref") != BRANCH_REF or value.get("from_phase") != "ready"
            or value.get("to_phase") != "requirements" or value.get("reason") != REASON):
        raise ExecutionEpochError("V2 epoch journal subject differs from authorization")
    for key in ("authorization_sha256", "epoch_id"):
        if not isinstance(value.get(key), str) or not SHA256_RE.fullmatch(value[key]):
            raise ExecutionEpochError(f"V2 epoch journal {key} is invalid")
    if not isinstance(value.get("created_at"), str) or not value["created_at"].endswith("Z"):
        raise ExecutionEpochError("V2 epoch journal timestamp is invalid")
    try:
        timestamp = datetime.fromisoformat(value["created_at"][:-1] + "+00:00")
    except ValueError as exc:
        raise ExecutionEpochError("V2 epoch journal timestamp is malformed") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp) or \
            timestamp.isoformat(timespec="seconds").replace("+00:00", "Z") != value["created_at"]:
        raise ExecutionEpochError("V2 epoch journal timestamp is not canonical UTC")
    for key in ("labels_before", "labels_after"):
        labels = value.get(key)
        if (not isinstance(labels, list) or any(not isinstance(label, str) or not label for label in labels)
                or labels != sorted(set(labels))):
            raise ExecutionEpochError(f"V2 epoch {key} must be a complete sorted label set")
    before, after = value["labels_before"], value["labels_after"]
    if (before.count("phase:ready") != 1 or "kind:single" not in before
            or "phase:requirements" in before
            or after != sorted([label for label in before if not label.startswith("phase:")]
                               + ["phase:requirements"])):
        raise ExecutionEpochError("V2 epoch labels do not describe the exact ready-to-requirements transition")
    if schema == APPLIED_SCHEMA:
        if not isinstance(value.get("applied_at"), str) or not value["applied_at"].endswith("Z"):
            raise ExecutionEpochError("V2 Applied timestamp is invalid")
        try:
            applied_at = datetime.fromisoformat(value["applied_at"][:-1] + "+00:00")
        except ValueError as exc:
            raise ExecutionEpochError("V2 Applied timestamp is malformed") from exc
        if (applied_at.tzinfo is None
                or applied_at.utcoffset() != timezone.utc.utcoffset(applied_at)
                or applied_at.isoformat(timespec="seconds").replace("+00:00", "Z") != value["applied_at"]):
            raise ExecutionEpochError("V2 Applied timestamp is not canonical UTC")
        if type(value.get("intent_comment_id")) is not int or value["intent_comment_id"] < 1:
            raise ExecutionEpochError("V2 Applied Intent comment ID is invalid")
        if not isinstance(value.get("intent_body_sha256"), str) or \
                not SHA256_RE.fullmatch(value["intent_body_sha256"]):
            raise ExecutionEpochError("V2 Applied Intent body digest is invalid")


def _record_body(value: Mapping[str, Any], schema: str) -> str:
    return f"<!-- {schema}\n{_canonical(value)}\n-->"


def _read_journal(github: GitHub) -> tuple[dict[str, Any] | None, int | None, str | None,
                                          dict[str, Any] | None, int | None, str | None,
                                          dict[str, Any], int, str]:
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ExecutionEpochError(f"epoch journal history is unavailable: {exc}") from exc
    v1_intents: list[tuple[dict[str, Any], int, str]] = []
    v1_applied: list[int] = []
    intents: list[tuple[dict[str, Any], int, str]] = []
    applied: list[tuple[dict[str, Any], int, str]] = []
    retired: list[tuple[dict[str, Any], int, str]] = []
    for row in comments:
        if not isinstance(row, dict) or not isinstance(row.get("body"), str):
            continue
        body = row["body"]
        schema = next((s for s, start in (
            (V1_INTENT_SCHEMA, V1_INTENT_START), (V1_APPLIED_SCHEMA, V1_APPLIED_START),
            (INTENT_SCHEMA, INTENT_START), (APPLIED_SCHEMA, APPLIED_START),
        ) if body.startswith(start)), None)
        if schema is None:
            continue
        comment_id = row.get("id")
        if type(comment_id) is not int or comment_id < 1:
            raise ExecutionEpochError("epoch journal comment ID is invalid")
        _comment_fp(row, comment_id)
        body_sha = _sha(body.encode("utf-8"))
        if schema == V1_INTENT_SCHEMA:
            value = _read_retired_intent(body)
            if comment_id == RETIRED_INTENT_COMMENT_ID:
                retired.append((value, comment_id, body_sha))
            v1_intents.append((value, comment_id, body_sha))
            continue
        if schema == V1_APPLIED_SCHEMA:
            v1_applied.append(comment_id)
            continue
        fields = INTENT_FIELDS if schema == INTENT_SCHEMA else APPLIED_FIELDS
        value = _read_v2_payload(body, schema, fields)
        direct = _read_comment_triplet(github, comment_id)
        if direct["body"] != body:
            raise ExecutionEpochError("V2 epoch journal list/direct bodies differ")
        (intents if schema == INTENT_SCHEMA else applied).append((value, comment_id, body_sha))
    if len(v1_intents) != 1 or len(retired) != 1 or v1_applied:
        raise ExecutionEpochError("retired V1 epoch history is missing, duplicated, or unexpectedly Applied")
    retired_payload, retired_id, retired_sha = retired[0]
    if retired_id != RETIRED_INTENT_COMMENT_ID or retired_sha != RETIRED_INTENT_SHA256:
        raise ExecutionEpochError("retired V1 Intent identity or body digest differs from the ADC")
    if len(intents) > 1 or len(applied) > 1:
        raise ExecutionEpochError("V2 epoch journal is duplicated")
    if bool(intents) != bool(applied) and applied:
        raise ExecutionEpochError("V2 Applied exists without a V2 Intent")
    intent = intents[0] if intents else (None, None, None)
    applied_row = applied[0] if applied else (None, None, None)
    if intent[0] is not None and applied_row[0] is not None:
        if intent[1] >= applied_row[1]:
            raise ExecutionEpochError("V2 epoch journal order is invalid")
        if (applied_row[0].get("intent_comment_id") != intent[1]
                or applied_row[0].get("intent_body_sha256") != intent[2]):
            raise ExecutionEpochError("V2 Applied does not point to the exact V2 Intent")
        for key in COMMON_FIELDS - {"schema"}:
            if intent[0][key] != applied_row[0][key]:
                raise ExecutionEpochError("V2 Intent and Applied payloads differ")
    retired_tuple = (retired_payload, retired_id, retired_sha)
    return (*intent, *applied_row, *retired_tuple)


def _read_retired_intent(body: str) -> dict[str, Any]:
    if not body.startswith(V1_INTENT_START) or not body.endswith("\n-->"):
        raise ExecutionEpochError("retired V1 Intent body framing is invalid")
    raw = body[len(V1_INTENT_START):-len("\n-->")]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ExecutionEpochError("retired V1 Intent JSON is invalid") from exc
    if (not isinstance(value, dict) or value.get("schema") != V1_INTENT_SCHEMA
            or value.get("repository") != REPOSITORY or value.get("repository_id") != REPOSITORY_ID
            or value.get("issue_number") != ISSUE_NUMBER or value.get("issue_id") != ISSUE_ID
            or value.get("adc_comment_id") != PREDECESSOR_ADC_COMMENT_ID
            or value.get("adc_sha256") != PREDECESSOR_ADC_SHA256
            or value.get("branch_ref") != RETIRED_BRANCH_REF or value.get("base_sha40") != BASE_SHA40
            or value.get("historical_binding_provenance") != "UNVERIFIED"):
        raise ExecutionEpochError("retired V1 Intent subject differs from its immutable reference")
    if _canonical(value) != raw:
        raise ExecutionEpochError("retired V1 Intent JSON is not canonical")
    return value


def _read_v1_retired_triplet(github: GitHub) -> tuple[dict[str, Any], int, str]:
    row = _read_comment_triplet(github, RETIRED_INTENT_COMMENT_ID)
    body = row["body"]
    body_sha = _sha(body.encode("utf-8"))
    if body_sha != RETIRED_INTENT_SHA256:
        raise ExecutionEpochError("retired V1 Intent body digest changed")
    value = _read_retired_intent(body)
    return value, RETIRED_INTENT_COMMENT_ID, body_sha


def _read_journal_full(github: GitHub):
    intent, intent_id, intent_sha, applied, applied_id, applied_sha, retired, retired_id, retired_sha = \
        _read_journal(github)
    return intent, intent_id, intent_sha, applied, applied_id, applied_sha, retired, retired_id, retired_sha


def _verify_predecessors(github: GitHub) -> tuple[dict[str, Any], str]:
    try:
        verify_adc_generation(github, ISSUE_NUMBER, PREDECESSOR_ADC_COMMENT_ID,
                             PREDECESSOR_ADC_SHA256, state="approved")
        verify_adc_generation(github, ISSUE_NUMBER, OLD_ADC_COMMENT_ID, OLD_ADC_SHA256, state="approved")
        row = _read_comment_triplet(github, OLD_PHASE_COMMENT_ID)
    except (ADCError, ExecutionEpochError) as exc:
        raise ExecutionEpochError(f"predecessor ADC or Phase readback failed: {exc}") from exc
    body = row["body"]
    if (_sha(body.encode("utf-8")) != OLD_PHASE_SHA256
            or not body.startswith("<!-- PASES_PHASE_RESTART_APPLIED_V1\n")):
        raise ExecutionEpochError("predecessor active Phase Applied differs from the exact authorization")
    return row, _sha(body.encode("utf-8"))


def _branch_sha(github: GitHub, branch_ref: str) -> str:
    try:
        row = github.branch(branch_ref)
    except GitHubError as exc:
        raise ExecutionEpochError(f"branch {branch_ref} is unavailable: {exc}") from exc
    commit = row.get("commit") if isinstance(row, dict) else None
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if row.get("name") != branch_ref or not isinstance(sha, str) or not SHA40.fullmatch(sha):
        raise ExecutionEpochError(f"branch {branch_ref} readback is incomplete")
    return sha


def _check_local_initial_branch(github: GitHub, root: Path) -> None:
    try:
        if (discover_repository(root).casefold() != REPOSITORY.casefold()
                or current_branch(root) != BRANCH_REF or head_sha40(root) != BASE_SHA40
                or remote_branch_sha(root, BRANCH_REF) != BASE_SHA40
                or _branch_sha(github, BRANCH_REF) != BASE_SHA40
                or _branch_sha(github, BASE_REF) != BASE_SHA40
                or _branch_sha(github, RETIRED_BRANCH_REF) != BASE_SHA40):
            raise ExecutionEpochError("epoch-2 and retired branches must remain at their exact authorized base")
        verify_remote_repository(root, REPOSITORY)
        if not is_ancestor(root, BASE_SHA40, head_sha40(root)):
            raise ExecutionEpochError("epoch-2 branch does not descend from the authorized base")
    except GitError as exc:
        raise ExecutionEpochError(str(exc)) from exc


def _verify_subject(github: GitHub, root: Path, *, phase: str, no_v2_records: bool
                    ) -> tuple[VerifiedADC, dict[str, Any], tuple[str, ...], str, dict[str, Any]]:
    _verify_repo_actor(github)
    try:
        adc = verify_adc(github, ISSUE_NUMBER)
    except ADCError as exc:
        raise ExecutionEpochError(f"current approved ADC is unavailable: {exc}") from exc
    _marker(adc)
    predecessor, old_phase_sha = _verify_predecessors(github)
    issue, labels = _issue_snapshot(github)
    if (issue.get("state") != "open" or _sha(issue["body"].encode("utf-8")) != ISSUE_BODY_SHA256
            or "kind:single" not in labels):
        raise ExecutionEpochError("Issue #71 state, body, or kind differs from the exact approved subject")
    phase_labels = [label for label in labels if label.startswith("phase:")]
    if phase_labels != [f"phase:{phase}"]:
        raise ExecutionEpochError(f"Issue #71 must be in phase:{phase}")
    _read_v1_retired_triplet(github)
    if no_v2_records:
        intent, intent_id, _intent_sha, applied, applied_id, _applied_sha, *_retired = _read_journal_full(github)
        if intent is not None or applied is not None:
            raise ExecutionEpochError("V2 epoch journal already exists; do not replay its one-time application")
        local, attachment = epoch_paths(root)
        if local.exists() or local.is_symlink() or attachment.exists() or attachment.is_symlink():
            raise ExecutionEpochError("local epoch-2 state already exists before its authorized migration")
        binding = root / ".p_ases" / "state" / str(ISSUE_NUMBER) / "execution-binding.json"
        if binding.exists() or binding.is_symlink():
            raise ExecutionEpochError("old ExecutionBinding bytes cannot be overwritten or adopted")
        _check_local_initial_branch(github, root)
    return adc, issue, labels, old_phase_sha, predecessor


def inspect_execution_epoch(github: GitHub, root: Path) -> dict[str, Any]:
    """Read-only exact authorization preflight and recovery status."""
    try:
        intent, intent_id, intent_sha, applied, applied_id, applied_sha, *_ = \
            _read_journal_full(github)
        issue, labels = _issue_snapshot(github)
        if intent is not None and applied is None:
            return {
                "status": "BLOCKED_RECOVERY_REQUIRED",
                "stage": "V2_INTENT_WITHOUT_APPLIED",
                "intent_comment_id": intent_id,
                "labels": list(labels),
                "reasons": ["partial V2 migration is read-only; a new approved ADC is required"],
            }
        if applied is not None:
            epoch = _identity(intent, intent_id, intent_sha, applied, applied_id, applied_sha)
            local, attachment = epoch_paths(Path(root).resolve())
            if not local.exists() or not attachment.exists():
                verify_execution_epoch(github, root, require_attachment=False)
                return {
                    "status": "ACTIVE_ATTACHMENT_REQUIRED",
                    "epoch_sha256": epoch.sha256,
                    "applied_comment_id": applied_id,
                    "labels": list(labels),
                    "reasons": [],
                }
            verify_execution_epoch(github, root)
            return {
                "status": "ACTIVE",
                "epoch_sha256": epoch.sha256,
                "applied_comment_id": applied_id,
                "labels": list(labels),
                "reasons": [],
            }
        adc, issue2, labels2, _phase_sha, _predecessor = \
            _verify_subject(github, root, phase="ready", no_v2_records=True)
        return {
            "status": "READY_TO_APPLY",
            "repository": REPOSITORY,
            "issue": ISSUE_NUMBER,
            "adc_comment_id": adc.pointer.comment_id,
            "adc_sha256": adc.contract.sha256,
            "base_ref": BASE_REF,
            "base_sha40": BASE_SHA40,
            "branch_ref": BRANCH_REF,
            "labels_before": list(labels2),
            "labels_after": sorted([label for label in labels2 if not label.startswith("phase:")]
                                   + ["phase:requirements"]),
            "retired_intent_comment_id": RETIRED_INTENT_COMMENT_ID,
            "historical_binding_provenance": "UNVERIFIED",
            "reasons": [],
        }
    except (ExecutionEpochError, ADCError, GitHubError, GitError, OSError, ValueError) as exc:
        return {"status": "BLOCKED", "reasons": [str(exc)]}


def _validate_applied_state(github: GitHub, root: Path, epoch: IssueExecutionEpoch,
                            common: Mapping[str, Any]) -> None:
    _verify_repo_actor(github)
    adc = verify_adc(github, ISSUE_NUMBER)
    _marker(adc)
    _verify_predecessors(github)
    issue, labels = _issue_snapshot(github)
    if (issue.get("state") != "open" or _sha(issue["body"].encode("utf-8")) != ISSUE_BODY_SHA256
            or tuple(labels) != tuple(common["labels_after"])
            or epoch.epoch_id != common["epoch_id"]):
        raise ExecutionEpochError("V2 Applied labels or Issue body do not match the exact Intent")
    if _branch_sha(github, BRANCH_REF) != BASE_SHA40 or _branch_sha(github, BASE_REF) != BASE_SHA40:
        raise ExecutionEpochError("V2 Applied branch/base differs from the authorized exact HEAD")
    intent, intent_id, intent_sha, applied, applied_id, applied_sha, *_ = _read_journal_full(github)
    if (intent is None or applied is None or intent_id != epoch.intent_comment_id
            or applied_id != epoch.applied_comment_id
            or intent_sha != epoch.intent_body_sha256 or applied_sha != epoch.applied_body_sha256):
        raise ExecutionEpochError("V2 journal readback differs from the new local epoch record")


def _identity(intent: dict[str, Any], intent_id: int, intent_sha: str,
              applied: dict[str, Any], applied_id: int, applied_sha: str) -> IssueExecutionEpoch:
    try:
        return IssueExecutionEpoch(
            repository=applied["repository"], issue_number=applied["issue_number"],
            adc_comment_id=applied["adc_comment_id"], adc_sha256=applied["adc_sha256"],
            base_ref=applied["base_ref"], base_sha40=applied["base_sha40"],
            branch_ref=applied["branch_ref"], epoch_id=applied["epoch_id"],
            intent_comment_id=intent_id, intent_body_sha256=intent_sha,
            applied_comment_id=applied_id, applied_body_sha256=applied_sha,
            attachment_id=_sha(f"{applied['epoch_id']}:attachment".encode("ascii")),
            historical_binding_sha256=applied["historical_binding_sha256"],
            historical_binding_provenance=applied["historical_binding_provenance"],
        ).validate()
    except (ExecutionError, KeyError) as exc:
        raise ExecutionEpochError(f"V2 execution epoch identity is invalid: {exc}") from exc


def _atomic_create(path: Path, raw: bytes) -> None:
    if path_has_symlink(path):
        raise ExecutionEpochError("epoch local state path traverses a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise ExecutionEpochError("epoch local state is immutable and already conflicts")
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ExecutionEpochError("concurrent epoch local state conflicts")
        if path.read_bytes() != raw:
            raise ExecutionEpochError("epoch local state create-only readback failed")
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _attachment_bytes(epoch: IssueExecutionEpoch, root: Path) -> bytes:
    value = {
        "attachment_id": epoch.attachment_id,
        "base_sha40": epoch.base_sha40,
        "branch_ref": epoch.branch_ref,
        "epoch_sha256": epoch.sha256,
        "issue_number": epoch.issue_number,
        "repository": epoch.repository,
        "schema": ATTACHMENT_SCHEMA,
        "work_directory": str(root.resolve()),
    }
    value["attachment_sha256"] = _sha(_canonical(value).encode("utf-8"))
    return (_canonical(value) + "\n").encode("utf-8")


def attach_verified_epoch(github: GitHub, root: Path) -> IssueExecutionEpoch:
    """Recreate only local files from a complete verified V2 GitHub journal."""
    root = Path(root).resolve()
    epoch = verify_execution_epoch(github, root, require_attachment=False)
    local, attachment = epoch_paths(root)
    _atomic_create(local, epoch.to_bytes())
    _atomic_create(attachment, _attachment_bytes(epoch, root))
    return verify_execution_epoch(github, root)


def verify_execution_epoch(github: GitHub, root: Path, *,
                           require_attachment: bool = True) -> IssueExecutionEpoch:
    root = Path(root).resolve()
    _verify_repo_actor(github)
    adc = verify_adc(github, ISSUE_NUMBER)
    _marker(adc)
    _verify_predecessors(github)
    issue, labels = _issue_snapshot(github)
    if (issue.get("state") != "open" or _sha(issue["body"].encode("utf-8")) != ISSUE_BODY_SHA256
            or "kind:single" not in labels):
        raise ExecutionEpochError("active Issue #71 state/body/kind differs from the epoch authorization")
    phase_labels = [label for label in labels if label.startswith("phase:")]
    if len(phase_labels) != 1 or phase_labels[0].removeprefix("phase:") not in PHASES:
        raise ExecutionEpochError("active Issue #71 has an invalid current phase label")
    intent, intent_id, intent_sha, applied, applied_id, applied_sha, *_ = _read_journal_full(github)
    if intent is None or applied is None:
        raise ExecutionEpochError("active Issue #71 lacks a complete V2 Intent/Applied journal")
    if (tuple(label for label in labels if not label.startswith("phase:"))
            != tuple(label for label in applied["labels_after"] if not label.startswith("phase:"))):
        raise ExecutionEpochError("active Issue #71 non-phase labels differ from the V2 Applied snapshot")
    epoch = _identity(intent, intent_id, intent_sha, applied, applied_id, applied_sha)
    local, attachment = epoch_paths(root)
    if not require_attachment:
        if local.exists() and local.read_bytes() != epoch.to_bytes():
            raise ExecutionEpochError("existing local V2 epoch record conflicts with GitHub")
        return epoch
    if not local.is_file() or local.is_symlink() or local.read_bytes() != epoch.to_bytes():
        raise ExecutionEpochError("local V2 epoch record is missing, unsafe, or mismatched")
    if not attachment.is_file() or attachment.is_symlink():
        raise ExecutionEpochError("V2 epoch workspace attachment is missing or unsafe")
    try:
        attachment_value = json.loads(attachment.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionEpochError("V2 epoch workspace attachment is invalid JSON") from exc
    expected_fields = {
        "attachment_id", "attachment_sha256", "base_sha40", "branch_ref",
        "epoch_sha256", "issue_number", "repository", "schema", "work_directory",
    }
    if not isinstance(attachment_value, dict) or set(attachment_value) != expected_fields:
        raise ExecutionEpochError("V2 epoch workspace attachment has unknown or missing fields")
    supplied = attachment_value.pop("attachment_sha256")
    if (_sha(_canonical(attachment_value).encode("utf-8")) != supplied
            or (_canonical({**attachment_value, "attachment_sha256": supplied}) + "\n").encode("utf-8")
                != attachment.read_bytes()
            or attachment_value != {
                "attachment_id": epoch.attachment_id,
                "base_sha40": epoch.base_sha40,
                "branch_ref": epoch.branch_ref,
                "epoch_sha256": epoch.sha256,
                "issue_number": epoch.issue_number,
                "repository": epoch.repository,
                "schema": ATTACHMENT_SCHEMA,
                "work_directory": str(root),
            }):
        raise ExecutionEpochError("V2 epoch workspace attachment differs from its epoch")
    try:
        if (discover_repository(root).casefold() != REPOSITORY.casefold()
                or current_branch(root) != BRANCH_REF or not is_ancestor(root, BASE_SHA40, head_sha40(root))
                or _branch_sha(github, BRANCH_REF) != head_sha40(root)
                or remote_branch_sha(root, BRANCH_REF) != head_sha40(root)):
            raise ExecutionEpochError("active V2 epoch local and remote branch identity differs")
    except GitError as exc:
        raise ExecutionEpochError(str(exc)) from exc
    binding = root / ".p_ases" / "state" / str(ISSUE_NUMBER) / "execution-binding.json"
    if binding.exists() or binding.is_symlink():
        raise ExecutionEpochError("an ExecutionBinding V1 must not be synthesized for the V2 epoch")
    return epoch


def current_execution_epoch_generation(github: GitHub, root: Path,
                                       issue_number: int, verified_adc: VerifiedADC
                                       ) -> tuple[int, str] | None:
    if issue_number != ISSUE_NUMBER or github.repo.casefold() != REPOSITORY.casefold():
        return None
    epoch = verify_execution_epoch(github, root)
    if (verified_adc.pointer.comment_id != epoch.adc_comment_id
            or verified_adc.contract.sha256 != epoch.adc_sha256):
        raise ExecutionEpochError("active V2 epoch differs from the current approved ADC")
    return epoch.applied_comment_id, epoch.applied_body_sha256


def apply_execution_epoch(github: GitHub, root: Path) -> IssueExecutionEpoch:
    """Apply the exact one-time V2 migration; incomplete writes are never retried."""
    root = Path(root).resolve()
    report = inspect_execution_epoch(github, root)
    if report["status"] == "ACTIVE_ATTACHMENT_REQUIRED":
        return attach_verified_epoch(github, root)
    if report["status"] != "READY_TO_APPLY":
        raise ExecutionEpochError(
            f"epoch-2 cannot apply: {report['status']}: {'; '.join(report.get('reasons', []))}"
        )
    adc, issue, labels, old_phase_sha, _predecessor = \
        _verify_subject(github, root, phase="ready", no_v2_records=True)
    marker, authorization_sha = _marker(adc)
    after = sorted([label for label in labels if not label.startswith("phase:")]
                   + ["phase:requirements"])
    common = {
        "actor_id": OWNER_ID,
        "adc_comment_id": ADC_COMMENT_ID,
        "adc_sha256": ADC_SHA256,
        "authorization_sha256": authorization_sha,
        "base_ref": BASE_REF,
        "base_sha40": BASE_SHA40,
        "branch_ref": BRANCH_REF,
        "created_at": _now(),
        "epoch_id": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "historical_binding_provenance": "UNVERIFIED",
        "historical_binding_sha256": HISTORICAL_BINDING_SHA256,
        "issue_body_sha256": ISSUE_BODY_SHA256,
        "issue_id": ISSUE_ID,
        "issue_number": ISSUE_NUMBER,
        "labels_after": after,
        "labels_before": list(labels),
        "from_phase": "ready",
        "to_phase": "requirements",
        "old_adc_comment_id": OLD_ADC_COMMENT_ID,
        "old_adc_sha256": OLD_ADC_SHA256,
        "old_phase_comment_id": OLD_PHASE_COMMENT_ID,
        "old_phase_sha256": old_phase_sha,
        "owner_id": OWNER_ID,
        "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
        "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
        "reason": REASON,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "retired_intent_body_sha256": RETIRED_INTENT_SHA256,
        "retired_intent_comment_id": RETIRED_INTENT_COMMENT_ID,
        "schema": INTENT_SCHEMA,
    }
    intent_body = _record_body(common, INTENT_SCHEMA)
    try:
        created = github.create_issue_comment(ISSUE_NUMBER, intent_body)
        intent_id = created.get("id") if isinstance(created, dict) else None
        if type(intent_id) is not int or intent_id < 1:
            raise ExecutionEpochError("V2 Intent response lacks a valid comment ID")
        named = _read_comment_triplet(github, intent_id)
        if named.get("body") != intent_body:
            raise ExecutionEpochError("V2 Intent readback differs from exact bytes")
    except (GitHubError, ExecutionEpochError) as exc:
        raise ExecutionEpochError(f"V2 Intent outcome is ambiguous; read-only recovery only: {exc}") from exc
    intent_sha = _sha(intent_body.encode("utf-8"))
    # This full read is deliberately before the one label request.
    try:
        _verify_repo_actor(github)
        adc2 = verify_adc(github, ISSUE_NUMBER)
        _marker(adc2)
        _verify_predecessors(github)
        issue2, labels2 = _issue_snapshot(github)
        _read_v1_retired_triplet(github)
        intent2, intent_id2, intent_sha2, applied2, *_ = _read_journal_full(github)
        if (adc2.pointer.comment_id != ADC_COMMENT_ID or adc2.contract.sha256 != ADC_SHA256
                or issue2.get("state") != "open"
                or _sha(issue2["body"].encode("utf-8")) != ISSUE_BODY_SHA256
                or labels2 != labels or intent2 is None or intent_id2 != intent_id
                or intent_sha2 != intent_sha or applied2 is not None
                or _branch_sha(github, BASE_REF) != BASE_SHA40
                or _branch_sha(github, BRANCH_REF) != BASE_SHA40
                or remote_branch_sha(root, BRANCH_REF) != BASE_SHA40
                or current_branch(root) != BRANCH_REF or head_sha40(root) != BASE_SHA40):
            raise ExecutionEpochError("V2 pre-write readback changed after Intent; no label request sent")
    except (ADCError, ExecutionEpochError, GitError, GitHubError) as exc:
        raise ExecutionEpochError(f"V2 pre-write readback failed; no label request sent: {exc}") from exc
    try:
        github.replace_issue_labels(ISSUE_NUMBER, after)
    except GitHubError as exc:
        raise ExecutionEpochError(f"V2 label update outcome is ambiguous; read-only recovery only: {exc}") from exc
    issue3, labels3 = _issue_snapshot(github)
    if (labels3 != tuple(after) or issue3.get("state") != "open"
            or _sha(issue3["body"].encode("utf-8")) != ISSUE_BODY_SHA256):
        raise ExecutionEpochError("V2 label post-write readback differs; read-only recovery only")
    applied_value = {**common, "schema": APPLIED_SCHEMA, "applied_at": _now(),
                     "intent_comment_id": intent_id, "intent_body_sha256": intent_sha}
    applied_body = _record_body(applied_value, APPLIED_SCHEMA)
    try:
        created_applied = github.create_issue_comment(ISSUE_NUMBER, applied_body)
        applied_id = created_applied.get("id") if isinstance(created_applied, dict) else None
        if type(applied_id) is not int or applied_id <= intent_id:
            raise ExecutionEpochError("V2 Applied response has invalid comment ordering")
        named_applied = _read_comment_triplet(github, applied_id)
        if named_applied.get("body") != applied_body:
            raise ExecutionEpochError("V2 Applied readback differs from exact bytes")
    except (GitHubError, ExecutionEpochError) as exc:
        raise ExecutionEpochError(f"V2 Applied outcome is ambiguous; read-only recovery only: {exc}") from exc
    applied_sha = _sha(applied_body.encode("utf-8"))
    intent_value = _read_v2_payload(intent_body, INTENT_SCHEMA, INTENT_FIELDS)
    applied_value = _read_v2_payload(applied_body, APPLIED_SCHEMA, APPLIED_FIELDS)
    epoch = _identity(intent_value, intent_id, intent_sha, applied_value, applied_id, applied_sha)
    local, attachment = epoch_paths(root)
    _atomic_create(local, epoch.to_bytes())
    _atomic_create(attachment, _attachment_bytes(epoch, root))
    return verify_execution_epoch(github, root)


def _ensure_no_extra_v1_candidates(github: GitHub) -> None:
    # Kept separate for focused tests; _read_journal enforces exactly the pinned V1 Intent.
    _read_journal_full(github)
