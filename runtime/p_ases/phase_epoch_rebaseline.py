"""Issue #71 exact-ADC-authorized epoch-3 phase rebaseline.

This bootstrap appends a new execution epoch and phase generation. It never
rewrites or promotes predecessor Binding, epoch, or Phase evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .adc import ADCError, VerifiedADC, verify_adc, verify_adc_generation
from .execution import ExecutionError, SHA40, SHA256
from .github import GitHub, GitHubError
from .git import (
    GitError, current_branch, head_sha40, is_ancestor, remote_branch_sha,
    remote_branch_exists, verify_remote_repository, worktree_clean,
)
from .path_safety import path_has_symlink
from .phases import PhaseError, parse_phase_labels

REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
ISSUE_NUMBER = 71
ISSUE_ID = 6135294757
OWNER_ID = 3744776
CURRENT_ADC_SHA256 = "3c6b3ac28270357b57047dc5da0a2c1fbdbada269d55225ea33a656cd3076e17"
PREDECESSOR_ADC_COMMENT_ID = 6881235235
PREDECESSOR_ADC_SHA256 = "3b86972309acf28df77cee3634dc102545fd79e3aa252034606c0c0250675e7c"
ISSUE_BODY_SHA256 = "5f910c8de4cbe3ec391edf18b69fabe0f4c42880b59357083647a8b06e7a6a36"
BASE_REF = "main"
BASE_SHA40 = "07481c4b451a81750a6c2e1a6a18bdfd4e3459c2"
BRANCH_REF = "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3"
OLD_EPOCH_APPLIED_ID = 6874828409
OLD_EPOCH_APPLIED_SHA256 = "23cd53f6f60f122bda3d3d4d2618b3e8ab05d3b34c20f6f355cab885020eac1a"
OLD_EPOCH_ID = "7230f492e6af06283bb72cbcf2df474c960b1e5a3c0760be1f765c46114a99ef"
OLD_EPOCH_SHA256 = "257958f86debbe128eecc2f00c884c759d5ae4eb76eb402393d67d8e60590caf"
OLD_READY_ID = 6875175855
OLD_READY_SHA256 = "1662908b4ea7bde7946a1a6ceeee6b9732130e5255360384f49a5389be3781ba"
DEVIATION_ID = 6880303687
DEVIATION_SHA256 = "d2c661d9ae0df3eaab867166f094b011b2996090f72681775d9999e741ffd8c9"
BLOCKER_ID = 6880363866
BLOCKER_SHA256 = "d09b7ca8b4a53037f49bc1c1d40767a9d9be1bf1b155012b1cfa294d64432312"
PR_NUMBER = 74
PR_HEAD_SHA40 = "bb76d7a7df01717a16c6834401fe09b1496dbcf3"
AUTH_SCHEMA = "PASES_ISSUE_PHASE_EPOCH_REBASE_AUTHORIZATION_V1"
INTENT_SCHEMA = "PASES_ISSUE_PHASE_EPOCH_REBASE_INTENT_V1"
APPLIED_SCHEMA = "PASES_ISSUE_PHASE_EPOCH_REBASE_APPLIED_V1"
EPOCH_SCHEMA = "PASES_ISSUE_EXECUTION_EPOCH_V3"
ATTACHMENT_SCHEMA = "PASES_EXECUTION_EPOCH_ATTACHMENT_V3"
AUTH_START = f"<!-- {AUTH_SCHEMA}\n"
INTENT_START = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_START = f"<!-- {APPLIED_SCHEMA}\n"
ISSUE_PHASES = {"requirements", "specification", "design", "ready", "execution",
                "verification", "integration", "user-review"}
LABELS_BEFORE = ["enhancement", "kind:single", "phase:ready"]
LABELS_AFTER = ["enhancement", "kind:single", "phase:requirements"]

AUTHORIZATION = {
    "base_ref": BASE_REF,
    "base_sha40": BASE_SHA40,
    "blocker_comment_body_sha256": BLOCKER_SHA256,
    "blocker_comment_id": BLOCKER_ID,
    "branch_ref": BRANCH_REF,
    "deviation_comment_body_sha256": DEVIATION_SHA256,
    "deviation_comment_id": DEVIATION_ID,
    "existing_local_branch_head_sha40": BASE_SHA40,
    "from_phase": "ready",
    "issue_body_sha256": ISSUE_BODY_SHA256,
    "issue_number": ISSUE_NUMBER,
    "labels_after": LABELS_AFTER,
    "labels_before": LABELS_BEFORE,
    "max_applications": 1,
    "old_active_epoch_id": OLD_EPOCH_ID,
    "old_active_epoch_sha256": OLD_EPOCH_SHA256,
    "old_phase_generation_comment_id": OLD_EPOCH_APPLIED_ID,
    "old_phase_generation_sha256": OLD_EPOCH_APPLIED_SHA256,
    "old_ready_receipt_body_sha256": OLD_READY_SHA256,
    "old_ready_receipt_comment_id": OLD_READY_ID,
    "owner_id": OWNER_ID,
    "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
    "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
    "pr_head_sha40": PR_HEAD_SHA40,
    "pr_number": PR_NUMBER,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "schema": AUTH_SCHEMA,
    "target_issue": ISSUE_NUMBER,
    "to_phase": "requirements",
}
AUTH_FIELDS = set(AUTHORIZATION)
INTENT_FIELDS = {
    "schema", "repository", "repository_id", "issue_number", "issue_id",
    "adc_comment_id", "adc_sha256", "authorization_sha256",
    "predecessor_adc_comment_id", "predecessor_adc_sha256",
    "base_ref", "base_sha40", "branch_ref", "existing_local_branch_head_sha40",
    "old_active_epoch_id", "old_active_epoch_sha256",
    "old_phase_generation_comment_id", "old_phase_generation_sha256",
    "old_ready_receipt_comment_id", "old_ready_receipt_body_sha256",
    "deviation_comment_id", "deviation_comment_body_sha256",
    "blocker_comment_id", "blocker_comment_body_sha256",
    "pr_number", "pr_head_sha40", "issue_body_sha256",
    "labels_before", "labels_after", "from_phase", "to_phase",
    "historical_binding_provenance", "historical_binding_sha256",
    "max_applications", "actor_id", "executor_user_id", "epoch_id", "created_at",
}
APPLIED_FIELDS = (INTENT_FIELDS - {"created_at"}) | {
    "applied_at", "intent_comment_id", "intent_body_sha256",
}
EPOCH_FIELDS = {
    "schema", "repository", "issue_number", "issue_id", "adc_comment_id", "adc_sha256",
    "base_ref", "base_sha40", "branch_ref", "epoch_id",
    "intent_comment_id", "intent_body_sha256", "applied_comment_id", "applied_body_sha256",
    "predecessor_epoch_id", "predecessor_epoch_sha256",
    "historical_binding_provenance", "historical_binding_sha256", "sha256",
}
ATTACHMENT_FIELDS = {
    "schema", "repository", "issue_number", "adc_comment_id", "adc_sha256",
    "base_ref", "base_sha40", "branch_ref", "epoch_id", "epoch_sha256",
    "intent_comment_id", "intent_body_sha256", "applied_comment_id", "applied_body_sha256",
    "work_directory",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PhaseEpochRebaselineError(ValueError):
    """The epoch-3 authorization, predecessor history, or Issue state is invalid."""


@dataclass(frozen=True)
class RebaselineRecord:
    comment_id: int
    schema: str
    payload: dict[str, Any]
    body: str
    actor_id: int
    created_at: str

    @property
    def body_sha256(self) -> str:
        return _sha(self.body.encode("utf-8"))


@dataclass(frozen=True)
class Issue71ExecutionEpoch:
    repository: str
    issue_number: int
    issue_id: int
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
    predecessor_epoch_id: str
    predecessor_epoch_sha256: str
    historical_binding_provenance: str
    historical_binding_sha256: str
    sha256: str
    schema: str = EPOCH_SCHEMA

    def validate(self) -> "Issue71ExecutionEpoch":
        if (self.schema != EPOCH_SCHEMA or self.repository != REPOSITORY
                or self.issue_number != ISSUE_NUMBER or self.issue_id != ISSUE_ID
                or self.adc_sha256 != CURRENT_ADC_SHA256 or self.base_ref != BASE_REF
                or self.base_sha40 != BASE_SHA40 or self.branch_ref != BRANCH_REF
                or self.predecessor_epoch_id != OLD_EPOCH_ID
                or self.predecessor_epoch_sha256 != OLD_EPOCH_SHA256
                or self.historical_binding_provenance != "UNVERIFIED"):
            raise PhaseEpochRebaselineError("epoch-3 identity differs from the approved frozen tuple")
        for name, value in (
            ("adc_comment_id", self.adc_comment_id),
            ("intent_comment_id", self.intent_comment_id),
            ("applied_comment_id", self.applied_comment_id),
        ):
            if type(value) is not int or value < 1:
                raise PhaseEpochRebaselineError(f"epoch-3 {name} is invalid")
        if self.historical_binding_sha256 != "b828daa98c9cab2c5243019e71158231e43f8c06826c7c31e6ca48ea3f5ac868":
            raise PhaseEpochRebaselineError("epoch-3 historical Binding provenance digest changed")
        for name, value in (
            ("adc_sha256", self.adc_sha256), ("intent_body_sha256", self.intent_body_sha256),
            ("applied_body_sha256", self.applied_body_sha256),
            ("predecessor_epoch_sha256", self.predecessor_epoch_sha256),
            ("historical_binding_sha256", self.historical_binding_sha256), ("sha256", self.sha256),
        ):
            if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
                raise PhaseEpochRebaselineError(f"epoch-3 {name} is invalid")
        if not isinstance(self.epoch_id, str) or SHA256_RE.fullmatch(self.epoch_id) is None:
            raise PhaseEpochRebaselineError("epoch-3 epoch_id is invalid")
        if not isinstance(self.base_sha40, str) or SHA40.fullmatch(self.base_sha40) is None:
            raise PhaseEpochRebaselineError("epoch-3 base SHA is invalid")
        return self


@dataclass(frozen=True)
class _Preflight:
    issue: dict[str, Any]
    adc: VerifiedADC
    authorization_sha256: str
    actor_id: int


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PhaseEpochRebaselineError("epoch rebaseline JSON contains duplicate fields")
        result[key] = value
    return result


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strict_utc(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PhaseEpochRebaselineError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PhaseEpochRebaselineError(f"{field} is malformed") from exc
    if (parsed.utcoffset() != timezone.utc.utcoffset(parsed)
            or parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != value):
        raise PhaseEpochRebaselineError(f"{field} is not canonical UTC")
    return value


def _parse_marker(verified: VerifiedADC) -> tuple[dict[str, Any], str]:
    text = verified.contract.content.decode("utf-8", errors="strict")
    if text.count(AUTH_START) != 1:
        raise PhaseEpochRebaselineError("approved ADC must contain exactly one epoch-3 authorization marker")
    start = text.index(AUTH_START)
    close = text.find("\n-->", start + len(AUTH_START))
    if close < 0:
        raise PhaseEpochRebaselineError("epoch-3 authorization marker is incomplete")
    end = close + len("\n-->")
    raw = text[start + len(AUTH_START):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseEpochRebaselineError("epoch-3 authorization JSON is malformed") from exc
    if (not isinstance(value, dict) or set(value) != AUTH_FIELDS
            or json.dumps(value, separators=(",", ":"), ensure_ascii=True) != raw):
        raise PhaseEpochRebaselineError("epoch-3 authorization fields or canonical form are invalid")
    if value != AUTHORIZATION:
        raise PhaseEpochRebaselineError("epoch-3 authorization does not match the approved exact tuple")
    marker_bytes = text[start:end].encode("utf-8", errors="strict")
    return value, _sha(marker_bytes)


def _label_names(issue: Mapping[str, Any]) -> list[str]:
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PhaseEpochRebaselineError("Issue labels are incomplete")
    labels = [row.get("name") for row in rows]
    if any(not isinstance(label, str) or not label for label in labels) or len(labels) != len(set(labels)):
        raise PhaseEpochRebaselineError("Issue labels are malformed or duplicated")
    return sorted(labels)


def _check_issue(issue: Any, *, phase: str | None = None) -> dict[str, Any]:
    if (not isinstance(issue, dict) or type(issue.get("number")) is not int
            or issue.get("number") != ISSUE_NUMBER or type(issue.get("id")) is not int
            or issue.get("id") != ISSUE_ID or issue.get("state") != "open"
            or issue.get("pull_request") is not None
            or issue.get("repository_url") != f"https://api.github.com/repos/{REPOSITORY}"
            or not isinstance(issue.get("body"), str)
            or _sha(issue["body"].encode("utf-8")) != ISSUE_BODY_SHA256):
        raise PhaseEpochRebaselineError("Issue #71 identity, body, or state differs from the authorized tuple")
    labels = _label_names(issue)
    expected = LABELS_BEFORE if phase == "ready" else LABELS_AFTER if phase == "requirements" else None
    if expected is not None and labels != expected:
        raise PhaseEpochRebaselineError("Issue #71 complete label set differs from the expected epoch-3 state")
    return issue


def _comment_fingerprint(row: Any, comment_id: int) -> tuple[Any, ...]:
    if (not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] != comment_id
            or not isinstance(row.get("body"), str)):
        raise PhaseEpochRebaselineError("immutable comment readback is malformed")
    user = row.get("user")
    if (not isinstance(user, dict) or user.get("type") != "User"
            or type(user.get("id")) is not int or user["id"] != OWNER_ID):
        raise PhaseEpochRebaselineError("immutable comment actor is not the authorized owner User")
    created, updated = row.get("created_at"), row.get("updated_at")
    if not isinstance(created, str) or updated != created:
        raise PhaseEpochRebaselineError("immutable comment is edited or lacks canonical timestamps")
    _strict_utc(created, "comment created_at")
    expected_issue = f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}"
    expected_html = f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}"
    expected_url = f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}"
    if (row.get("issue_url") != expected_issue or row.get("html_url") != expected_html
            or row.get("url") != expected_url):
        raise PhaseEpochRebaselineError("immutable comment URLs do not match Issue #71")
    return (comment_id, row["body"], created, updated, user["id"], user.get("login"),
            row["issue_url"], row["html_url"], row["url"])


def _comment_triplet(github: GitHub, comment_id: int) -> dict[str, Any]:
    try:
        first = github.issue_comment(ISSUE_NUMBER, comment_id)
        listed_all = github.issue_comments(ISSUE_NUMBER)
        listed = [row for row in listed_all if isinstance(row, dict) and row.get("id") == comment_id]
        second = github.issue_comment(ISSUE_NUMBER, comment_id)
    except GitHubError as exc:
        raise PhaseEpochRebaselineError(f"immutable Issue comment readback failed: {exc}") from exc
    if len(listed) != 1:
        raise PhaseEpochRebaselineError("immutable Issue comment is missing or duplicated in full history")
    fingerprints = [_comment_fingerprint(row, comment_id) for row in (first, listed[0], second)]
    if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
        raise PhaseEpochRebaselineError("immutable Issue comment changed during direct/list/direct readback")
    return first


def _verified_historical_comment(github: GitHub, comment_id: int, sha256: str,
                                prefix: str | None = None) -> dict[str, Any]:
    row = _comment_triplet(github, comment_id)
    body = row["body"]
    if _sha(body.encode("utf-8")) != sha256 or (prefix is not None and not body.startswith(prefix)):
        raise PhaseEpochRebaselineError(f"historical comment #{comment_id} differs from its pinned digest")
    return row


def _validate_old_phase_history(github: GitHub) -> None:
    old = _verified_historical_comment(
        github, OLD_EPOCH_APPLIED_ID, OLD_EPOCH_APPLIED_SHA256,
        "<!-- PASES_EXECUTION_EPOCH_RESTART_APPLIED_V2\n",
    )
    raw = old["body"][len("<!-- PASES_EXECUTION_EPOCH_RESTART_APPLIED_V2\n"):-len("\n-->")]
    try:
        payload = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseEpochRebaselineError("predecessor epoch Applied payload is malformed") from exc
    if (_canonical(payload) != raw or payload.get("epoch_id") != OLD_EPOCH_ID
            or payload.get("base_ref") != "main" or payload.get("base_sha40") != BASE_SHA40
            or payload.get("branch_ref") != "pases/issue-71-local-activation-v2-epoch-2"
            or payload.get("historical_binding_provenance") != "UNVERIFIED"):
        raise PhaseEpochRebaselineError("predecessor epoch Applied record differs from pinned history")
    ready = _verified_historical_comment(github, OLD_READY_ID, OLD_READY_SHA256, "PASES_PHASE_DECISION_V2\n")
    from .phase_evidence import PhaseDecision
    decision = PhaseDecision.from_body(ready["body"])
    p = decision.payload
    if (p.get("issue_number") != ISSUE_NUMBER or p.get("to_phase") != "ready"
            or p.get("adc_comment_id") != 6874553609
            or p.get("adc_sha256") != "aa0e69210dec4f2df1b069eafc4f5ce99ca3a71465a7ca59da3a05301fa023a4"
            or p.get("phase_generation_comment_id") != OLD_EPOCH_APPLIED_ID
            or p.get("phase_generation_sha256") != OLD_EPOCH_APPLIED_SHA256):
        raise PhaseEpochRebaselineError("predecessor READY receipt differs from the pinned epoch-2 history")
    _verified_historical_comment(github, DEVIATION_ID, DEVIATION_SHA256)
    _verified_historical_comment(github, BLOCKER_ID, BLOCKER_SHA256)
    try:
        pull = github.pull_request(PR_NUMBER)
    except GitHubError as exc:
        raise PhaseEpochRebaselineError(f"PR #74 readback failed: {exc}") from exc
    head = pull.get("head")
    if (pull.get("number") != PR_NUMBER or pull.get("state") != "open"
            or pull.get("merged_at") is not None or not isinstance(head, dict)
            or head.get("sha") != PR_HEAD_SHA40):
        raise PhaseEpochRebaselineError("PR #74 state or pinned head has changed")


def _verify_live(github: GitHub, root: Path, *, phase: str,
                 require_current_adc: bool = True) -> _Preflight:
    try:
        metadata = github.repository_metadata()
        if metadata.get("full_name", "").casefold() != REPOSITORY.casefold() or metadata.get("id") != REPOSITORY_ID:
            raise PhaseEpochRebaselineError("repository metadata does not match the authorized repository")
        issue = _check_issue(github.issue(ISSUE_NUMBER), phase=phase)
        verified = verify_adc(github, ISSUE_NUMBER)
        if (verified.contract.repository != REPOSITORY or verified.contract.issue_number != ISSUE_NUMBER
                or verified.pointer.state != "approved"
                or verified.contract.sha256 != CURRENT_ADC_SHA256):
            raise PhaseEpochRebaselineError("current approved ADC differs from the exact epoch-3 authorization")
        marker, authorization_sha = _parse_marker(verified)
        if marker["predecessor_adc_comment_id"] != PREDECESSOR_ADC_COMMENT_ID:
            raise PhaseEpochRebaselineError("successor ADC predecessor differs from the authorized pointer")
        verify_adc_generation(
            github, ISSUE_NUMBER, PREDECESSOR_ADC_COMMENT_ID, PREDECESSOR_ADC_SHA256, state="approved",
        )
        actor = github.authenticated_user()
        if type(actor.get("id")) is not int or actor["id"] != OWNER_ID or actor.get("type") != "User":
            raise PhaseEpochRebaselineError("authenticated executor is not the repository owner User")
        verify_remote_repository(root, REPOSITORY)
        branch = current_branch(root)
        head = head_sha40(root)
        if branch != BRANCH_REF or head != BASE_SHA40 or not worktree_clean(root):
            raise PhaseEpochRebaselineError("epoch-3 branch/worktree is not clean at the exact authorized base")
        if remote_branch_sha(root, BASE_REF) != BASE_SHA40:
            raise PhaseEpochRebaselineError("remote main differs from the frozen base SHA")
        if remote_branch_exists(root, BRANCH_REF):
            raise PhaseEpochRebaselineError("epoch-3 branch already exists on the remote")
        _validate_old_phase_history(github)
        return _Preflight(issue, verified, authorization_sha, actor["id"])
    except (ADCError, GitError, GitHubError) as exc:
        raise PhaseEpochRebaselineError(str(exc)) from exc


def _record_body(schema: str, payload: Mapping[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(payload)}\n-->"


def _parse_record(row: dict[str, Any], schema: str, fields: set[str]) -> RebaselineRecord:
    comment_id = row.get("id")
    if type(comment_id) is not int or comment_id < 1:
        raise PhaseEpochRebaselineError("epoch rebaseline journal has an invalid comment ID")
    checked = _comment_fingerprint(row, comment_id)
    body = checked[1]
    start = f"<!-- {schema}\n"
    if not body.startswith(start) or not body.endswith("\n-->"):
        raise PhaseEpochRebaselineError("epoch rebaseline journal framing is invalid")
    raw = body[len(start):-len("\n-->")]
    try:
        payload = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseEpochRebaselineError("epoch rebaseline journal JSON is malformed") from exc
    if not isinstance(payload, dict) or set(payload) != fields or payload.get("schema") != schema:
        raise PhaseEpochRebaselineError("epoch rebaseline journal has unknown or missing fields")
    if _canonical(payload) != raw:
        raise PhaseEpochRebaselineError("epoch rebaseline journal JSON is not canonical")
    return RebaselineRecord(comment_id, schema, payload, body, checked[4], checked[2])


def _read_rebaseline_history(github: GitHub) -> tuple[RebaselineRecord, ...]:
    try:
        rows = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise PhaseEpochRebaselineError(f"epoch rebaseline history is unavailable: {exc}") from exc
    candidates: list[tuple[int, str]] = []
    for row in rows:
        body = row.get("body") if isinstance(row, dict) else None
        if not isinstance(body, str):
            continue
        header = body.lstrip()
        offset = 0
        while offset < len(header) and header[offset] in "<!-/ >":
            offset += 1
        if not header[offset:].startswith("PASES_ISSUE_PHASE_EPOCH_REBASE_"):
            continue
        if not header.startswith(f"<!-- {INTENT_SCHEMA}") and not header.startswith(f"<!-- {APPLIED_SCHEMA}"):
            raise PhaseEpochRebaselineError("malformed reserved epoch rebaseline history candidate")
        matched_schema = next(
            (schema for schema in (INTENT_SCHEMA, APPLIED_SCHEMA)
             if header.startswith(f"<!-- {schema}\n")),
            None,
        )
        if matched_schema is None:
            raise PhaseEpochRebaselineError("epoch rebaseline history marker framing is malformed")
        rid = row.get("id")
        if type(rid) is not int or rid < 1:
            raise PhaseEpochRebaselineError("epoch rebaseline history has an invalid comment ID")
        candidates.append((rid, matched_schema))
    records: list[RebaselineRecord] = []
    for rid, schema in candidates:
        row = _comment_triplet(github, rid)
        fields = INTENT_FIELDS if schema == INTENT_SCHEMA else APPLIED_FIELDS
        records.append(_parse_record(row, schema, fields))
    records.sort(key=lambda record: record.comment_id)
    return tuple(records)


def _common_payload(preflight: _Preflight, epoch_id: str) -> dict[str, Any]:
    marker, _ = _parse_marker(preflight.adc)
    labels = _label_names(preflight.issue)
    return {
        "schema": INTENT_SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER,
        "issue_id": ISSUE_ID,
        "adc_comment_id": preflight.adc.pointer.comment_id,
        "adc_sha256": preflight.adc.contract.sha256,
        "authorization_sha256": preflight.authorization_sha256,
        "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
        "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
        "base_ref": BASE_REF,
        "base_sha40": BASE_SHA40,
        "branch_ref": BRANCH_REF,
        "existing_local_branch_head_sha40": BASE_SHA40,
        "old_active_epoch_id": OLD_EPOCH_ID,
        "old_active_epoch_sha256": OLD_EPOCH_SHA256,
        "old_phase_generation_comment_id": OLD_EPOCH_APPLIED_ID,
        "old_phase_generation_sha256": OLD_EPOCH_APPLIED_SHA256,
        "old_ready_receipt_comment_id": OLD_READY_ID,
        "old_ready_receipt_body_sha256": OLD_READY_SHA256,
        "deviation_comment_id": DEVIATION_ID,
        "deviation_comment_body_sha256": DEVIATION_SHA256,
        "blocker_comment_id": BLOCKER_ID,
        "blocker_comment_body_sha256": BLOCKER_SHA256,
        "pr_number": PR_NUMBER,
        "pr_head_sha40": PR_HEAD_SHA40,
        "issue_body_sha256": ISSUE_BODY_SHA256,
        "labels_before": labels,
        "labels_after": LABELS_AFTER,
        "from_phase": "ready",
        "to_phase": "requirements",
        "historical_binding_provenance": "UNVERIFIED",
        "historical_binding_sha256": "b828daa98c9cab2c5243019e71158231e43f8c06826c7c31e6ca48ea3f5ac868",
        "max_applications": 1,
        "actor_id": preflight.actor_id,
        "executor_user_id": preflight.actor_id,
        "epoch_id": epoch_id,
        "created_at": _now(),
    }


def _validate_intent(record: RebaselineRecord, preflight: _Preflight) -> None:
    p = record.payload
    marker, auth_sha = _parse_marker(preflight.adc)
    for key, expected in (
        ("repository", REPOSITORY), ("repository_id", REPOSITORY_ID),
        ("issue_number", ISSUE_NUMBER), ("issue_id", ISSUE_ID),
        ("adc_comment_id", preflight.adc.pointer.comment_id), ("adc_sha256", CURRENT_ADC_SHA256),
        ("authorization_sha256", auth_sha),
        ("predecessor_adc_comment_id", PREDECESSOR_ADC_COMMENT_ID),
        ("predecessor_adc_sha256", PREDECESSOR_ADC_SHA256),
        ("base_ref", BASE_REF), ("base_sha40", BASE_SHA40), ("branch_ref", BRANCH_REF),
        ("existing_local_branch_head_sha40", BASE_SHA40),
        ("old_active_epoch_id", OLD_EPOCH_ID), ("old_active_epoch_sha256", OLD_EPOCH_SHA256),
        ("old_phase_generation_comment_id", OLD_EPOCH_APPLIED_ID),
        ("old_phase_generation_sha256", OLD_EPOCH_APPLIED_SHA256),
        ("old_ready_receipt_comment_id", OLD_READY_ID), ("old_ready_receipt_body_sha256", OLD_READY_SHA256),
        ("deviation_comment_id", DEVIATION_ID), ("deviation_comment_body_sha256", DEVIATION_SHA256),
        ("blocker_comment_id", BLOCKER_ID), ("blocker_comment_body_sha256", BLOCKER_SHA256),
        ("pr_number", PR_NUMBER), ("pr_head_sha40", PR_HEAD_SHA40),
        ("issue_body_sha256", ISSUE_BODY_SHA256),
        ("labels_before", LABELS_BEFORE), ("labels_after", LABELS_AFTER),
        ("from_phase", "ready"), ("to_phase", "requirements"),
        ("historical_binding_provenance", "UNVERIFIED"),
        ("historical_binding_sha256", "b828daa98c9cab2c5243019e71158231e43f8c06826c7c31e6ca48ea3f5ac868"),
        ("max_applications", 1), ("actor_id", OWNER_ID), ("executor_user_id", OWNER_ID),
    ):
        if p.get(key) != expected:
            raise PhaseEpochRebaselineError(f"epoch Intent {key} differs from the exact authorization")
    if (type(p.get("epoch_id")) is not str or SHA256_RE.fullmatch(p["epoch_id"]) is None
            or record.actor_id != OWNER_ID):
        raise PhaseEpochRebaselineError("epoch Intent ID or actor is invalid")
    _strict_utc(record.created_at, "Intent created_at")


def _validate_applied(applied: RebaselineRecord, intent: RebaselineRecord,
                      preflight: _Preflight) -> None:
    p = applied.payload
    expected = dict(intent.payload)
    expected["schema"] = APPLIED_SCHEMA
    expected.pop("created_at")
    expected.update({
        "intent_comment_id": intent.comment_id,
        "intent_body_sha256": intent.body_sha256,
        "applied_at": p.get("applied_at"),
    })
    if p != expected or applied.actor_id != OWNER_ID:
        raise PhaseEpochRebaselineError("epoch Applied record does not match its exact Intent")
    _strict_utc(p.get("applied_at"), "Applied applied_at")


def _attempt_path(root: Path, operation: str) -> Path:
    return root / ".p_ases" / "state" / str(ISSUE_NUMBER) / "phase-epoch-rebaseline" / f"{operation}-attempt.json"


def _write_attempt_once(root: Path, operation: str, body_sha256: str) -> None:
    path = _attempt_path(root, operation)
    data = (_canonical({"schema": "PASES_EPOCH_REBASE_LOCAL_ATTEMPT_V1",
                        "operation": operation, "body_sha256": body_sha256}) + "\n").encode("utf-8")
    if path_has_symlink(path, root=root):
        raise PhaseEpochRebaselineError("local epoch rebaseline attempt path traverses a symlink")
    if path.exists():
        try:
            old = path.read_bytes()
        except OSError as exc:
            raise PhaseEpochRebaselineError(f"local attempt marker cannot be read: {exc}") from exc
        if old != data:
            raise PhaseEpochRebaselineError("local epoch rebaseline attempt marker conflicts")
        return
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path_has_symlink(path, root=root):
            raise PhaseEpochRebaselineError("local epoch rebaseline attempt path traverses a symlink")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != data:
            raise PhaseEpochRebaselineError("local attempt marker raced with a conflicting operation")
    except OSError as exc:
        raise PhaseEpochRebaselineError(f"could not persist local no-retry marker: {exc}") from exc


def _post_record_once(github: GitHub, root: Path, schema: str,
                      payload: Mapping[str, Any]) -> RebaselineRecord:
    fields = INTENT_FIELDS if schema == INTENT_SCHEMA else APPLIED_FIELDS
    body = _record_body(schema, payload)
    op = "intent" if schema == INTENT_SCHEMA else "applied"
    existing = [r for r in _read_rebaseline_history(github) if r.schema == schema]
    if existing:
        if len(existing) != 1 or existing[0].body != body:
            raise PhaseEpochRebaselineError(f"{schema} has a conflicting or duplicate existing record")
        return existing[0]
    if _attempt_state(root, op):
        raise PhaseEpochRebaselineError(f"{op} POST was previously attempted; read-only recovery only")
    _write_attempt_once(root, op, _sha(body.encode("utf-8")))
    write_error: GitHubError | None = None
    try:
        created = github.create_issue_comment(ISSUE_NUMBER, body)
        created_id = created.get("id") if isinstance(created, dict) else None
    except GitHubError as exc:
        write_error, created_id = exc, None
    try:
        history = _read_rebaseline_history(github)
    except PhaseEpochRebaselineError as exc:
        if write_error is not None:
            raise PhaseEpochRebaselineError(f"{op} POST failed and immutable readback is unavailable; no retry") from write_error
        raise
    matches = [record for record in history if record.schema == schema and record.body == body]
    if len(matches) != 1:
        reason = "POST outcome is ambiguous" if write_error else "POST has no unique exact readback"
        raise PhaseEpochRebaselineError(f"{reason}; {op} will not be retried")
    record = matches[0]
    if created_id is not None and created_id != record.comment_id:
        raise PhaseEpochRebaselineError(f"{op} POST ID differs from direct/list/direct readback")
    return record


def _read_issue_labels(github: GitHub, expected_labels: list[str]) -> dict[str, Any]:
    try:
        issue = _check_issue(github.issue(ISSUE_NUMBER))
    except GitHubError as exc:
        raise PhaseEpochRebaselineError(f"Issue readback failed: {exc}") from exc
    if _label_names(issue) != expected_labels:
        raise PhaseEpochRebaselineError("Issue complete label set differs from the expected transition state")
    return issue


def _replace_labels_once(github: GitHub, root: Path, intent: RebaselineRecord) -> None:
    body_sha = _sha(_canonical({
        "schema": "PASES_EPOCH_REBASE_LABEL_ATTEMPT_V1",
        "intent_comment_id": intent.comment_id,
        "intent_body_sha256": intent.body_sha256,
        "labels_before": LABELS_BEFORE,
        "labels_after": LABELS_AFTER,
    }).encode("utf-8"))
    marker_path = _attempt_path(root, "labels")
    marker_data = (_canonical({"schema": "PASES_EPOCH_REBASE_LOCAL_ATTEMPT_V1",
                               "operation": "labels", "body_sha256": body_sha}) + "\n").encode("utf-8")
    if path_has_symlink(marker_path, root=root):
        raise PhaseEpochRebaselineError("label attempt path traverses a symlink")
    if marker_path.exists():
        try:
            prior = marker_path.read_bytes()
        except OSError as exc:
            raise PhaseEpochRebaselineError(f"label attempt marker cannot be read: {exc}") from exc
        if prior != marker_data:
            raise PhaseEpochRebaselineError("label attempt marker conflicts")
        raise PhaseEpochRebaselineError("previous label PUT may have been sent; read-only recovery only, no retry")
    _read_issue_labels(github, LABELS_BEFORE)
    _write_attempt_once(root, "labels", body_sha)
    write_error: GitHubError | None = None
    try:
        github.replace_issue_labels(ISSUE_NUMBER, LABELS_AFTER)
    except GitHubError as exc:
        write_error = exc
    try:
        after = _read_issue_labels(github, LABELS_AFTER)
    except PhaseEpochRebaselineError as after_error:
        try:
            before = _read_issue_labels(github, LABELS_BEFORE)
        except PhaseEpochRebaselineError:
            raise PhaseEpochRebaselineError("label PUT outcome is ambiguous; read-only recovery only, no retry") from after_error
        if before and write_error is not None:
            raise PhaseEpochRebaselineError("label PUT failed with before-state unchanged; no retry") from write_error
        raise PhaseEpochRebaselineError("label PUT outcome differs from the exact authorized state") from after_error
    if after.get("state") != "open":
        raise PhaseEpochRebaselineError("Issue closed during the authorized label transition")


def _epoch_payload(intent: RebaselineRecord, applied: RebaselineRecord,
                   work_directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    source = intent.payload
    base = {
        "schema": EPOCH_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "issue_id": ISSUE_ID,
        "adc_comment_id": source["adc_comment_id"],
        "adc_sha256": source["adc_sha256"],
        "base_ref": BASE_REF,
        "base_sha40": BASE_SHA40,
        "branch_ref": BRANCH_REF,
        "epoch_id": source["epoch_id"],
        "intent_comment_id": intent.comment_id,
        "intent_body_sha256": intent.body_sha256,
        "applied_comment_id": applied.comment_id,
        "applied_body_sha256": applied.body_sha256,
        "predecessor_epoch_id": OLD_EPOCH_ID,
        "predecessor_epoch_sha256": OLD_EPOCH_SHA256,
        "historical_binding_provenance": "UNVERIFIED",
        "historical_binding_sha256": "b828daa98c9cab2c5243019e71158231e43f8c06826c7c31e6ca48ea3f5ac868",
    }
    digest = _sha(_canonical(base).encode("utf-8"))
    epoch = {**base, "sha256": digest}
    attachment = {
        "schema": ATTACHMENT_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "adc_comment_id": source["adc_comment_id"],
        "adc_sha256": source["adc_sha256"],
        "base_ref": BASE_REF,
        "base_sha40": BASE_SHA40,
        "branch_ref": BRANCH_REF,
        "epoch_id": source["epoch_id"],
        "epoch_sha256": digest,
        "intent_comment_id": intent.comment_id,
        "intent_body_sha256": intent.body_sha256,
        "applied_comment_id": applied.comment_id,
        "applied_body_sha256": applied.body_sha256,
        "work_directory": str(work_directory.resolve()),
    }
    return epoch, attachment


def _write_exact_private_json(path: Path, value: Mapping[str, Any], root: Path) -> None:
    if path_has_symlink(path, root=root):
        raise PhaseEpochRebaselineError("epoch attachment path traverses a symlink")
    data = (_canonical(value) + "\n").encode("utf-8")
    if path.exists():
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise PhaseEpochRebaselineError(f"epoch identity file cannot be read: {exc}") from exc
        if current != data:
            raise PhaseEpochRebaselineError("existing epoch identity file conflicts with the verified journal")
        return
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path_has_symlink(path, root=root):
            raise PhaseEpochRebaselineError("epoch attachment path traverses a symlink")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != data:
            raise PhaseEpochRebaselineError("epoch identity file raced with conflicting content")
    except OSError as exc:
        raise PhaseEpochRebaselineError(f"epoch identity write failed: {exc}") from exc


def epoch_paths(root: Path) -> tuple[Path, Path]:
    state = Path(root) / ".p_ases" / "state" / str(ISSUE_NUMBER)
    return state / "execution-epoch.json", state / "execution-epoch-attachment.json"


def _materialize_epoch(root: Path, intent: RebaselineRecord,
                       applied: RebaselineRecord) -> Issue71ExecutionEpoch:
    epoch_path, attachment_path = epoch_paths(root)
    epoch_record, attachment = _epoch_payload(intent, applied, root)
    _write_exact_private_json(epoch_path, epoch_record, root)
    _write_exact_private_json(attachment_path, attachment, root)
    return _load_local_epoch(root, expected_adc_comment_id=intent.payload["adc_comment_id"],
                             expected_adc_sha256=intent.payload["adc_sha256"])


def _load_local_epoch(root: Path, *, expected_adc_comment_id: int,
                      expected_adc_sha256: str) -> Issue71ExecutionEpoch:
    epoch_path, attachment_path = epoch_paths(root)
    try:
        if (path_has_symlink(epoch_path, root=root) or path_has_symlink(attachment_path, root=root)
                or not epoch_path.is_file() or not attachment_path.is_file()):
            raise PhaseEpochRebaselineError("epoch-3 identity and attachment must be regular files without symlinks")
        epoch_bytes = epoch_path.read_bytes()
        attachment_bytes = attachment_path.read_bytes()
        data = json.loads(epoch_bytes.decode("utf-8", errors="strict"), object_pairs_hook=_pairs)
        attachment = json.loads(attachment_bytes.decode("utf-8", errors="strict"), object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhaseEpochRebaselineError(f"epoch-3 local identity is missing or malformed: {exc}") from exc
    if not isinstance(data, dict) or set(data) != EPOCH_FIELDS or not isinstance(attachment, dict) or set(attachment) != ATTACHMENT_FIELDS:
        raise PhaseEpochRebaselineError("epoch-3 identity or attachment has unknown/missing fields")
    if (epoch_bytes != (_canonical(data) + "\n").encode("utf-8")
            or attachment_bytes != (_canonical(attachment) + "\n").encode("utf-8")):
        raise PhaseEpochRebaselineError("epoch-3 identity or attachment bytes are not canonical")
    base = {key: data[key] for key in data if key != "sha256"}
    if data["schema"] != EPOCH_SCHEMA:
        raise PhaseEpochRebaselineError("epoch-3 identity JSON is not canonical")
    digest = _sha(_canonical(base).encode("utf-8"))
    if digest != data["sha256"]:
        raise PhaseEpochRebaselineError("epoch-3 identity checksum is invalid")
    expected_attachment = {
        "schema": ATTACHMENT_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "adc_comment_id": expected_adc_comment_id,
        "adc_sha256": expected_adc_sha256,
        "base_ref": BASE_REF,
        "base_sha40": BASE_SHA40,
        "branch_ref": BRANCH_REF,
        "epoch_id": data["epoch_id"],
        "epoch_sha256": digest,
        "intent_comment_id": data["intent_comment_id"],
        "intent_body_sha256": data["intent_body_sha256"],
        "applied_comment_id": data["applied_comment_id"],
        "applied_body_sha256": data["applied_body_sha256"],
        "work_directory": str(Path(root).resolve()),
    }
    if attachment != expected_attachment:
        raise PhaseEpochRebaselineError("epoch-3 workspace attachment differs from the durable identity")
    identity = Issue71ExecutionEpoch(
        repository=data["repository"], issue_number=data["issue_number"], issue_id=data["issue_id"],
        adc_comment_id=data["adc_comment_id"], adc_sha256=data["adc_sha256"],
        base_ref=data["base_ref"], base_sha40=data["base_sha40"], branch_ref=data["branch_ref"],
        epoch_id=data["epoch_id"], intent_comment_id=data["intent_comment_id"],
        intent_body_sha256=data["intent_body_sha256"], applied_comment_id=data["applied_comment_id"],
        applied_body_sha256=data["applied_body_sha256"],
        predecessor_epoch_id=data["predecessor_epoch_id"],
        predecessor_epoch_sha256=data["predecessor_epoch_sha256"],
        historical_binding_provenance=data["historical_binding_provenance"],
        historical_binding_sha256=data["historical_binding_sha256"], sha256=data["sha256"],
    ).validate()
    if identity.adc_comment_id != expected_adc_comment_id or identity.adc_sha256 != expected_adc_sha256:
        raise PhaseEpochRebaselineError("epoch-3 identity is stale for the current ADC")
    return identity


def _records_for_current_adc(github: GitHub, preflight: _Preflight
                             ) -> tuple[RebaselineRecord | None, RebaselineRecord | None]:
    records = _read_rebaseline_history(github)
    if len(records) > 2:
        raise PhaseEpochRebaselineError("epoch-3 journal has duplicate or unrelated rebaseline records")
    intents = [r for r in records if r.schema == INTENT_SCHEMA]
    applied = [r for r in records if r.schema == APPLIED_SCHEMA]
    if len(intents) > 1 or len(applied) > 1:
        raise PhaseEpochRebaselineError("epoch-3 journal contains duplicate Intent or Applied records")
    if any(r.payload.get("adc_comment_id") != preflight.adc.pointer.comment_id
           or r.payload.get("adc_sha256") != preflight.adc.contract.sha256 for r in records):
        raise PhaseEpochRebaselineError("predecessor ADC has a rebaseline record; no current-generation reuse is allowed")
    if applied and not intents:
        raise PhaseEpochRebaselineError("epoch-3 Applied record has no matching Intent")
    if intents and applied:
        _validate_intent(intents[0], preflight)
        _validate_applied(applied[0], intents[0], preflight)
    elif intents:
        _validate_intent(intents[0], preflight)
    return (intents[0] if intents else None, applied[0] if applied else None)


def _prepare_intent(github: GitHub, root: Path, preflight: _Preflight) -> RebaselineRecord:
    epoch_id = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    payload = _common_payload(preflight, epoch_id)
    _validate_payload_shape(payload, INTENT_FIELDS, INTENT_SCHEMA)
    return _post_record_once(github, root, INTENT_SCHEMA, payload)


def _validate_payload_shape(payload: Mapping[str, Any], fields: set[str], schema: str) -> None:
    if set(payload) != fields or payload.get("schema") != schema:
        raise PhaseEpochRebaselineError(f"{schema} payload fields are invalid")
    _strict_utc(payload.get("created_at", payload.get("applied_at")), "journal timestamp")


def _prepare_applied(github: GitHub, root: Path, intent: RebaselineRecord) -> RebaselineRecord:
    payload = dict(intent.payload)
    payload["schema"] = APPLIED_SCHEMA
    payload.pop("created_at")
    payload["intent_comment_id"] = intent.comment_id
    payload["intent_body_sha256"] = intent.body_sha256
    payload["applied_at"] = _now()
    _validate_payload_shape(payload, APPLIED_FIELDS, APPLIED_SCHEMA)
    return _post_record_once(github, root, APPLIED_SCHEMA, payload)


def _attempt_state(root: Path, operation: str) -> bool:
    path = _attempt_path(root, operation)
    if path_has_symlink(path, root=root):
        raise PhaseEpochRebaselineError("local attempt marker path traverses a symlink")
    return path.exists()


def _ensure_label_transition(github: GitHub, root: Path, intent: RebaselineRecord) -> int:
    issue = _check_issue(github.issue(ISSUE_NUMBER))
    labels = _label_names(issue)
    if labels == LABELS_AFTER:
        return 0
    if labels != LABELS_BEFORE:
        raise PhaseEpochRebaselineError("Issue labels match neither the exact before nor after state")
    # A persistent local attempt marker prevents a later process from retrying a
    # potentially sent PUT whose response and remote readback were both lost.
    if _attempt_state(root, "labels"):
        raise PhaseEpochRebaselineError("label PUT was previously attempted; read-only recovery only")
    _replace_labels_once(github, root, intent)
    return 1


def _write_attachment_after_applied(github: GitHub, root: Path,
                                    intent: RebaselineRecord, applied: RebaselineRecord,
                                    preflight: _Preflight) -> Issue71ExecutionEpoch:
    _validate_applied(applied, intent, preflight)
    issue = _read_issue_labels(github, LABELS_AFTER)
    if issue.get("state") != "open":
        raise PhaseEpochRebaselineError("Issue closed before the epoch-3 attachment")
    return _materialize_epoch(root, intent, applied)


def apply_phase_epoch_rebaseline(github: GitHub, root: Path, issue_number: int) -> dict[str, Any]:
    """Apply or read-only recover the one authorized Issue #71 ready-to-requirements rebaseline."""
    if type(issue_number) is not int or issue_number != ISSUE_NUMBER or github.repo.casefold() != REPOSITORY.casefold():
        raise PhaseEpochRebaselineError("epoch-3 rebaseline is fixed to puchinya/ai-agent-workflow Issue #71")
    root = Path(root).resolve()
    phase = "ready"
    try:
        issue = github.issue(ISSUE_NUMBER)
        labels = _label_names(issue)
        phase = "ready" if labels == LABELS_BEFORE else "requirements" if labels == LABELS_AFTER else "invalid"
        preflight = _verify_live(github, root, phase=phase)
        intent, applied = _records_for_current_adc(github, preflight)
        if applied is not None:
            if intent is None:
                raise PhaseEpochRebaselineError("epoch-3 Applied record has no Intent")
            epoch = _write_attachment_after_applied(github, root, intent, applied, preflight)
            return {"status": "NOOP", "issue": ISSUE_NUMBER,
                    "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                    "epoch_id": epoch.epoch_id, "epoch_sha256": epoch.sha256, "label_write_count": 0}
        if intent is not None:
            if labels == LABELS_BEFORE:
                if _attempt_state(root, "labels"):
                    raise PhaseEpochRebaselineError("label PUT was previously attempted; no retry")
                raise PhaseEpochRebaselineError("Intent exists with before-labels unchanged; label PUT will not be retried")
            if labels != LABELS_AFTER:
                raise PhaseEpochRebaselineError("Intent exists but labels match neither exact state")
            latest = _verify_live(github, root, phase="requirements")
            _validate_intent(intent, latest)
            applied = _prepare_applied(github, root, intent)
            epoch = _write_attachment_after_applied(github, root, intent, applied, latest)
            return {"status": "RECOVERED", "issue": ISSUE_NUMBER,
                    "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                    "epoch_id": epoch.epoch_id, "epoch_sha256": epoch.sha256, "label_write_count": 0}
        if labels != LABELS_BEFORE:
            raise PhaseEpochRebaselineError("new epoch-3 authorization applies only from phase:ready")
        if _attempt_state(root, "intent"):
            raise PhaseEpochRebaselineError("Intent POST was previously attempted without exact readback; no retry")
        intent = _prepare_intent(github, root, preflight)
        # Revalidate every mutable GitHub and local precondition after Intent and
        # immediately before the sole authorized complete-label replacement.
        latest = _verify_live(github, root, phase="ready")
        _validate_intent(intent, latest)
        _ensure_label_transition(github, root, intent)
        after = _read_issue_labels(github, LABELS_AFTER)
        if after.get("id") != ISSUE_ID:
            raise PhaseEpochRebaselineError("Issue identity changed after label replacement")
        latest = _verify_live(github, root, phase="requirements")
        _validate_intent(intent, latest)
        applied = _prepare_applied(github, root, intent)
        epoch = _write_attachment_after_applied(github, root, intent, applied, latest)
        return {"status": "APPLIED", "issue": ISSUE_NUMBER,
                "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                "epoch_id": epoch.epoch_id, "epoch_sha256": epoch.sha256, "label_write_count": 1}
    except (ADCError, ExecutionError, GitError, GitHubError) as exc:
        raise PhaseEpochRebaselineError(str(exc)) from exc


def read_active_epoch(github: GitHub, root: Path, verified_adc: VerifiedADC | None = None
                      ) -> Issue71ExecutionEpoch:
    """Read the current epoch-3 journal and verified workspace attachment."""
    root = Path(root).resolve()
    try:
        verified = verify_adc(github, ISSUE_NUMBER) if verified_adc is None else verified_adc
        if (verified.pointer.state != "approved" or verified.contract.sha256 != CURRENT_ADC_SHA256
                or verified.contract.repository != REPOSITORY):
            raise PhaseEpochRebaselineError("current ADC does not authorize the epoch-3 identity")
        marker, _auth_sha = _parse_marker(verified)
        metadata = github.repository_metadata()
        if (not isinstance(metadata, dict)
                or metadata.get("full_name", "").casefold() != REPOSITORY.casefold()
                or type(metadata.get("id")) is not int or metadata.get("id") != REPOSITORY_ID):
            raise PhaseEpochRebaselineError("repository metadata differs from the pinned Issue #71 repository")
        issue = _check_issue(github.issue(ISSUE_NUMBER))
        labels = _label_names(issue)
        kind_labels = [label for label in labels if label.startswith("kind:")]
        if (kind_labels != ["kind:single"] or parse_phase_labels(labels) not in ISSUE_PHASES):
            raise PhaseEpochRebaselineError("Issue #71 must have unique kind:single and phase labels")
        branch = current_branch(root)
        head = head_sha40(root)
        if branch != BRANCH_REF or not is_ancestor(root, BASE_SHA40, head):
            raise PhaseEpochRebaselineError("epoch-3 worktree is not on the authorized branch/base")
        epoch = _load_local_epoch(root, expected_adc_comment_id=verified.pointer.comment_id,
                                  expected_adc_sha256=verified.contract.sha256)
        retired_binding = root / ".p_ases" / "state" / str(ISSUE_NUMBER) / "execution-binding.json"
        if retired_binding.exists() or retired_binding.is_symlink():
            raise PhaseEpochRebaselineError("epoch-3 identity must not coexist with a reconstructed V1 Binding")
        records = _read_rebaseline_history(github)
        intents = [r for r in records if r.schema == INTENT_SCHEMA]
        applied = [r for r in records if r.schema == APPLIED_SCHEMA]
        if len(intents) != 1 or len(applied) != 1:
            raise PhaseEpochRebaselineError("current epoch-3 Intent/Applied history is incomplete or duplicated")
        preflight = _Preflight(issue, verified, _parse_marker(verified)[1], OWNER_ID)
        _validate_intent(intents[0], preflight)
        _validate_applied(applied[0], intents[0], preflight)
        if (epoch.epoch_id != intents[0].payload["epoch_id"]
                or epoch.intent_comment_id != intents[0].comment_id
                or epoch.applied_comment_id != applied[0].comment_id):
            raise PhaseEpochRebaselineError("local epoch-3 identity differs from its durable journal")
        return epoch
    except (ADCError, ExecutionError, GitError, GitHubError, PhaseError) as exc:
        raise PhaseEpochRebaselineError(str(exc)) from exc


def active_phase_generation(github: GitHub, root: Path,
                            verified_adc: VerifiedADC | None = None) -> tuple[int, str]:
    epoch = read_active_epoch(github, root, verified_adc)
    return epoch.applied_comment_id, epoch.applied_body_sha256


def is_issue71_execution_epoch(identity: Any) -> bool:
    return (getattr(identity, "schema", None) == EPOCH_SCHEMA
            and getattr(identity, "repository", None) == REPOSITORY
            and getattr(identity, "issue_number", None) == ISSUE_NUMBER
            and isinstance(getattr(identity, "sha256", None), str))
