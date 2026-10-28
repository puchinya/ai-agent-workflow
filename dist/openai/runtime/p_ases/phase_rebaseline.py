"""One-time Issue #63 phase bootstrap based on its approved ADC successor.

The phase change is an ordinary workflow execution step after the successor ADC
has been approved and published. Intent and Applied comments are append-only
technical evidence; they are not owner decisions.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .adc import (
    ADCError, ADCPointer, VerifiedADC, verify_adc, verify_adc_forward_generations,
    verify_adc_generation,
)
from .github import GitHubError
from .owner_consent import OwnerDecisionError, SCHEMA_V3, read_verified_owner_decision

REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
ISSUE_NUMBER = 63
OWNER_ID = 3744776
BASELINE_ADC_COMMENT_ID = 6228771805
BASELINE_ADC_SHA256 = "ad13d005126693bb4e1cbe1e7eaa815e43f0a1ef3b88ef9f1670450a42bc9622"
INTENT_SCHEMA = "PASES_PHASE_REBASE_INTENT_V1"
APPLIED_SCHEMA = "PASES_PHASE_REBASE_APPLIED_V1"
INTENT_V2_SCHEMA = "PASES_PHASE_REBASE_INTENT_V2"
APPLIED_V2_SCHEMA = "PASES_PHASE_REBASE_APPLIED_V2"
INTENT_V3_SCHEMA = "PASES_PHASE_REBASE_INTENT_V3"
APPLIED_V3_SCHEMA = "PASES_PHASE_REBASE_APPLIED_V3"
INTENT_START = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_START = f"<!-- {APPLIED_SCHEMA}\n"
INTENT_V2_START = f"<!-- {INTENT_V2_SCHEMA}\n"
APPLIED_V2_START = f"<!-- {APPLIED_V2_SCHEMA}\n"
INTENT_V3_START = f"<!-- {INTENT_V3_SCHEMA}\n"
APPLIED_V3_START = f"<!-- {APPLIED_V3_SCHEMA}\n"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")

PHASE_SCHEMAS = {
    INTENT_SCHEMA: INTENT_START,
    APPLIED_SCHEMA: APPLIED_START,
    INTENT_V2_SCHEMA: INTENT_V2_START,
    APPLIED_V2_SCHEMA: APPLIED_V2_START,
    INTENT_V3_SCHEMA: INTENT_V3_START,
    APPLIED_V3_SCHEMA: APPLIED_V3_START,
}

# Exact approved Issue #63 generations whose previous Phase operation was
# blocked after publication. V3 may recover only these two ordered pairs.
V3_RECOVERY_GENERATIONS = (
    (6271832228, "221e62a86a5b682237948abec1ee287d24d3808a9ad4fa22960be2c869fdcd05",
     6468215907, "6b2ab1c83aead86efe602b700bdfd33807d1675a56089a6a3ffc29175e2b601a"),
    (6468215907, "6b2ab1c83aead86efe602b700bdfd33807d1675a56089a6a3ffc29175e2b601a",
     6469056354, "f03465611fda6df485b323beab212f132cb9df2145827d46d0f0525445584efe"),
)


class PhaseRebaselineError(ValueError):
    """The approved ADC or append-only phase bootstrap evidence is invalid."""


@dataclass(frozen=True)
class PhaseRecord:
    comment_id: int
    schema: str
    payload: dict[str, Any]
    body: str
    created_at: str
    actor_id: int

    @property
    def payload_sha256(self) -> str:
        canonical = json.dumps(self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _body(schema: str, payload: dict[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(payload)}\n-->"


def _strict_utc(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PhaseRebaselineError("phase evidence timestamp must be UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PhaseRebaselineError("phase evidence timestamp is malformed") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PhaseRebaselineError("phase evidence timestamp must be UTC")
    return value


def _record_from_row(row: Any, schema: str) -> PhaseRecord:
    if not isinstance(row, dict):
        raise PhaseRebaselineError("phase evidence carrier is not an object")
    comment_id = row.get("id")
    user = row.get("user")
    if (type(comment_id) is not int or comment_id < 1 or not isinstance(user, dict)
            or type(user.get("id")) is not int or user["id"] < 1
            or not isinstance(user.get("login"), str) or not user["login"]
            or user.get("type") != "User"):
        raise PhaseRebaselineError("phase evidence carrier author or ID is invalid")
    body = row.get("body")
    start = PHASE_SCHEMAS.get(schema)
    if start is None:
        raise PhaseRebaselineError("phase evidence schema is unsupported")
    if not isinstance(body, str) or not body.startswith(start) or not body.endswith("\n-->"):
        raise PhaseRebaselineError("phase evidence carrier is malformed")
    raw = body[len(start):-len("\n-->")]
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise PhaseRebaselineError("phase evidence JSON is invalid") from exc
    if not isinstance(payload, dict) or _canonical(payload) != raw or payload.get("schema") != schema:
        raise PhaseRebaselineError("phase evidence is noncanonical or has the wrong schema")
    created_at = _strict_utc(row.get("created_at"))
    if row.get("updated_at") != created_at:
        raise PhaseRebaselineError("phase evidence carrier was edited")
    return PhaseRecord(comment_id, schema, payload, body, created_at, user["id"])


def _expected_urls(repository: str, issue_number: int, comment_id: int) -> tuple[str, str, str]:
    return (
        f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}",
        f"https://api.github.com/repos/{repository}/issues/{issue_number}",
        f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}",
    )


def _fingerprint(row: Any, schema: str, repository: str, issue_number: int) -> tuple[Any, ...]:
    record = _record_from_row(row, schema)
    expected = _expected_urls(repository, issue_number, record.comment_id)
    actual = (row.get("url"), row.get("issue_url"), row.get("html_url"))
    if actual != expected:
        raise PhaseRebaselineError("phase evidence carrier belongs to a different repository or Issue")
    user = row["user"]
    return (record.comment_id, record.body, record.created_at, user["id"], user["login"].casefold(),
            user["type"], *actual)


def _read_history(github: Any) -> tuple[PhaseRecord, ...]:
    """Read every phase marker direct/list/direct and reject ambiguous history."""
    try:
        first = github.issue_comments(ISSUE_NUMBER)
        first_rows: list[tuple[dict[str, Any], str]] = []
        for row in first:
            body = row.get("body") if isinstance(row, dict) else None
            if not isinstance(body, str) or not body.startswith("<!-- PASES_PHASE_REBASE_"):
                continue
            schema = next((name for name, marker in PHASE_SCHEMAS.items() if body.startswith(marker)), None)
            if schema is None:
                raise PhaseRebaselineError("unknown or malformed phase rebaseline marker")
            first_rows.append((row, schema))
        ids = [row.get("id") for row, _schema in first_rows]
        if any(type(comment_id) is not int or comment_id < 1 for comment_id in ids):
            raise PhaseRebaselineError("phase evidence history contains an invalid comment ID")
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise PhaseRebaselineError("phase evidence history is duplicated or not append-only")
        def direct_readback() -> dict[int, dict[str, Any]]:
            comment_ids = [row["id"] for row, _schema in first_rows]
            if not comment_ids:
                return {}
            with ThreadPoolExecutor(max_workers=min(4, len(comment_ids))) as executor:
                rows = list(executor.map(lambda comment_id: github.issue_comment(ISSUE_NUMBER, comment_id),
                                         comment_ids))
            return dict(zip(comment_ids, rows, strict=True))

        direct_before = direct_readback()
        second = github.issue_comments(ISSUE_NUMBER)
        second_rows = []
        for row in second:
            body = row.get("body") if isinstance(row, dict) else None
            if isinstance(body, str) and body.startswith("<!-- PASES_PHASE_REBASE_"):
                second_rows.append(row)
        second_ids = [row.get("id") if isinstance(row, dict) else None for row in second_rows]
        if second_ids != ids:
            raise PhaseRebaselineError("phase evidence history changed during direct/list/direct readback")
        direct_after = direct_readback()
    except GitHubError as exc:
        raise PhaseRebaselineError(str(exc)) from exc

    records: list[PhaseRecord] = []
    for listed, schema in first_rows:
        comment_id = listed["id"]
        direct = direct_before[comment_id]
        listed_again = next(row for row in second_rows if row.get("id") == comment_id)
        direct_after_row = direct_after[comment_id]
        triples = tuple(_fingerprint(row, schema, github.repo, ISSUE_NUMBER)
                        for row in (direct, listed_again, direct_after_row))
        if triples[0] != triples[1] or triples[1] != triples[2]:
            raise PhaseRebaselineError("phase evidence carrier changed during direct/list/direct readback")
        record = _record_from_row(direct, schema)
        if record.comment_id <= 0:
            raise PhaseRebaselineError("phase evidence comment ID is invalid")
        records.append(record)
    return tuple(records)


def _issue_state(github: Any) -> tuple[dict[str, Any], list[str]]:
    try:
        issue = github.issue(ISSUE_NUMBER)
    except GitHubError as exc:
        raise PhaseRebaselineError(str(exc)) from exc
    expected_url = f"https://api.github.com/repos/{REPOSITORY}"
    rows = issue.get("labels") if isinstance(issue, dict) else None
    if (not isinstance(issue, dict) or issue.get("number") != ISSUE_NUMBER or issue.get("state") != "open"
            or issue.get("repository_url") != expected_url or issue.get("pull_request") is not None
            or not isinstance(issue.get("body"), str) or not isinstance(rows, list)
            or any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in rows)):
        raise PhaseRebaselineError("Issue #63 identity or readback is incomplete")
    labels = [row["name"] for row in rows]
    if len(labels) != len(set(labels)):
        raise PhaseRebaselineError("Issue #63 has duplicate labels")
    return issue, labels


def _require_adc_supersede_decision(github: Any, adc: VerifiedADC) -> None:
    """Require the exact typed chat-confirmed approval for this ADC generation."""
    try:
        read_verified_owner_decision(
            github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID,
            operation="ADC_SUPERSEDE", subject_sha256=adc.pointer.sha256,
            repository_id=REPOSITORY_ID, expected_schema=SCHEMA_V3,
        )
    except OwnerDecisionError as exc:
        raise PhaseRebaselineError(
            "ADC phase evidence requires its exact chat-confirmed ADC_SUPERSEDE decision"
        ) from exc


def _approved_generations(github: Any) -> tuple[VerifiedADC, ...]:
    try:
        if getattr(github, "repo", None) != REPOSITORY:
            raise PhaseRebaselineError("phase rebaseline is restricted to puchinya/ai-agent-workflow#63")
        metadata = github.repository_metadata()
        owner = metadata.get("owner") if isinstance(metadata, dict) else None
        if (not isinstance(metadata, dict) or metadata.get("id") != REPOSITORY_ID
                or metadata.get("full_name") != REPOSITORY or not isinstance(owner, dict)
                or owner.get("type") != "User" or owner.get("id") != OWNER_ID):
            raise PhaseRebaselineError("configured repository identity changed")
        issue, _labels = _issue_state(github)
        if not isinstance(issue.get("body"), str):
            raise PhaseRebaselineError("Issue body is not text")
        current = verify_adc(github, ISSUE_NUMBER)
        if current.pointer.state != "approved":
            raise PhaseRebaselineError("current ADC pointer is not approved")
        _require_adc_supersede_decision(github, current)
        baseline = verify_adc_generation(
            github, ISSUE_NUMBER, BASELINE_ADC_COMMENT_ID, BASELINE_ADC_SHA256, state="approved",
        )
        chain = verify_adc_forward_generations(
            github, ISSUE_NUMBER,
            prior_comment_id=baseline.pointer.comment_id,
            prior_sha256=baseline.pointer.sha256,
            current_comment_id=current.pointer.comment_id,
            current_sha256=current.pointer.sha256,
        )
        if (len(chain) < 2 or chain[0].pointer != baseline.pointer
                or chain[-1].pointer != current.pointer):
            raise PhaseRebaselineError("current approved ADC is not a forward successor of the configured baseline")
        return chain
    except ADCError as exc:
        raise PhaseRebaselineError(str(exc)) from exc


def _intent_v1_payload(predecessor: VerifiedADC, successor: VerifiedADC, body: str,
                       labels_before: list[str], labels_after: list[str], executor_user_id: int) -> dict[str, Any]:
    return {
        "schema": INTENT_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "predecessor_adc_comment_id": predecessor.pointer.comment_id,
        "predecessor_adc_sha256": predecessor.pointer.sha256,
        "successor_adc_comment_id": successor.pointer.comment_id,
        "successor_adc_sha256": successor.pointer.sha256,
        "from_phase": "ready",
        "to_phase": "requirements",
        "labels_before": sorted(labels_before),
        "labels_after": sorted(labels_after),
        "issue_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "executor_user_id": executor_user_id,
    }


def _intent_v2_payload(predecessor: VerifiedADC, successor: VerifiedADC, previous_applied: PhaseRecord,
                       body: str, labels: list[str], executor_user_id: int) -> dict[str, Any]:
    stable_labels = sorted(labels)
    return {
        "schema": INTENT_V2_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "predecessor_adc_comment_id": predecessor.pointer.comment_id,
        "predecessor_adc_sha256": predecessor.pointer.sha256,
        "successor_adc_comment_id": successor.pointer.comment_id,
        "successor_adc_sha256": successor.pointer.sha256,
        "previous_applied_comment_id": previous_applied.comment_id,
        "previous_applied_payload_sha256": previous_applied.payload_sha256,
        "operation": "adopt_existing_requirements",
        "from_phase": "requirements",
        "to_phase": "requirements",
        "labels_before": stable_labels,
        "labels_after": stable_labels,
        "issue_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "executor_user_id": executor_user_id,
    }


def _intent_v3_payload(predecessor: VerifiedADC, successor: VerifiedADC, previous_applied: PhaseRecord,
                       body: str, labels: list[str], executor_user_id: int) -> dict[str, Any]:
    stable_labels = sorted(labels)
    edge = (predecessor.pointer.comment_id, predecessor.pointer.sha256,
            successor.pointer.comment_id, successor.pointer.sha256)
    if edge == V3_RECOVERY_GENERATIONS[0]:
        from_phase, operation = "execution", "rebaseline_execution_to_requirements"
        after = sorted([label for label in stable_labels if label != "phase:execution"]
                       + ["phase:requirements"])
    elif edge == V3_RECOVERY_GENERATIONS[1]:
        from_phase, operation, after = "requirements", "adopt_existing_requirements", stable_labels
    else:
        raise PhaseRebaselineError("V3 Intent is outside the exact approved ADC recovery generations")
    return {
        "schema": INTENT_V3_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "predecessor_adc_comment_id": predecessor.pointer.comment_id,
        "predecessor_adc_sha256": predecessor.pointer.sha256,
        "successor_adc_comment_id": successor.pointer.comment_id,
        "successor_adc_sha256": successor.pointer.sha256,
        "previous_applied_comment_id": previous_applied.comment_id,
        "previous_applied_payload_sha256": previous_applied.payload_sha256,
        "operation": operation,
        "from_phase": from_phase,
        "to_phase": "requirements",
        "labels_before": stable_labels,
        "labels_after": after,
        "issue_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "executor_user_id": executor_user_id,
    }


def _validated_labels(payload: dict[str, Any], before_phase: str, after_phase: str) -> None:
    before, after = payload.get("labels_before"), payload.get("labels_after")
    if (not isinstance(before, list) or not isinstance(after, list)
            or any(not isinstance(label, str) for label in before + after)
            or before != sorted(set(before)) or after != sorted(set(after))):
        raise PhaseRebaselineError("phase evidence labels are malformed")
    before_phases = [label for label in before if label.startswith("phase:")]
    after_phases = [label for label in after if label.startswith("phase:")]
    before_kinds = [label for label in before if label.startswith("kind:")]
    after_kinds = [label for label in after if label.startswith("kind:")]
    if (before_phases != [before_phase] or after_phases != [after_phase]
            or before_kinds != ["kind:single"] or after_kinds != ["kind:single"]):
        raise PhaseRebaselineError("phase evidence does not bind the exact #63 kind and phase labels")


def _validate_v1_pair(intent: PhaseRecord | None, applied: PhaseRecord | None,
                      adc_chain: tuple[VerifiedADC, ...]) -> None:
    if intent is None:
        if applied is not None:
            raise PhaseRebaselineError("V1 Applied evidence has no matching Intent")
        return
    if len(adc_chain) < 2:
        raise PhaseRebaselineError("V1 phase evidence has no historical approved ADC pair")
    predecessor, successor = adc_chain[:2]
    payload = intent.payload
    required = {
        "schema", "repository", "issue_number", "predecessor_adc_comment_id", "predecessor_adc_sha256",
        "successor_adc_comment_id", "successor_adc_sha256", "from_phase", "to_phase",
        "labels_before", "labels_after", "issue_body_sha256",
    }
    if (frozenset(payload) not in {frozenset(required), frozenset(required | {"executor_user_id"})}
            or payload.get("schema") != INTENT_SCHEMA
            or payload.get("repository") != REPOSITORY or payload.get("issue_number") != ISSUE_NUMBER
            or payload.get("predecessor_adc_comment_id") != predecessor.pointer.comment_id
            or payload.get("predecessor_adc_sha256") != predecessor.pointer.sha256
            or payload.get("successor_adc_comment_id") != successor.pointer.comment_id
            or payload.get("successor_adc_sha256") != successor.pointer.sha256
            or payload.get("from_phase") != "ready" or payload.get("to_phase") != "requirements"
            or any(not isinstance(payload.get(key), str) or SHA256.fullmatch(payload[key]) is None
                   for key in ("predecessor_adc_sha256", "successor_adc_sha256", "issue_body_sha256"))
            or any(type(payload.get(key)) is not int or payload[key] < 1
                   for key in ("predecessor_adc_comment_id", "successor_adc_comment_id"))
            or ("executor_user_id" in payload
                and (type(payload["executor_user_id"]) is not int or payload["executor_user_id"] < 1))
            or payload["successor_adc_comment_id"] <= payload["predecessor_adc_comment_id"]
            or intent.comment_id <= payload["successor_adc_comment_id"]):
        raise PhaseRebaselineError("V1 Intent evidence fields do not match its historical ADC generation")
    _validated_labels(payload, "phase:ready", "phase:requirements")
    before, after = payload["labels_before"], payload["labels_after"]
    expected_after = sorted([label for label in before if label != "phase:ready"] + ["phase:requirements"])
    if after != expected_after:
        raise PhaseRebaselineError("V1 Intent does not describe the exact historical label replacement")
    if "executor_user_id" in payload and intent.actor_id != payload["executor_user_id"]:
        raise PhaseRebaselineError("V1 Intent author does not match its authenticated executor identity")
    if applied is None:
        return
    expected = {
        "schema": APPLIED_SCHEMA, "repository": REPOSITORY, "issue_number": ISSUE_NUMBER,
        "intent_comment_id": intent.comment_id, "intent_sha256": intent.payload_sha256,
        "predecessor_adc_comment_id": predecessor.pointer.comment_id,
        "predecessor_adc_sha256": predecessor.pointer.sha256,
        "successor_adc_comment_id": successor.pointer.comment_id,
        "successor_adc_sha256": successor.pointer.sha256,
        "from_phase": "ready", "to_phase": "requirements",
        "labels_after": payload["labels_after"],
    }
    if "executor_user_id" in payload:
        expected["executor_user_id"] = payload["executor_user_id"]
    if (applied.payload != expected or applied.comment_id <= intent.comment_id
            or applied.actor_id != intent.actor_id):
        raise PhaseRebaselineError("V1 Applied evidence does not exactly match its Intent")


def _validate_v2_pair(intent: PhaseRecord, applied: PhaseRecord | None,
                      adc_chain: tuple[VerifiedADC, ...], generation_index: int,
                      previous_applied: PhaseRecord) -> None:
    predecessor, successor = adc_chain[generation_index - 1:generation_index + 1]
    payload = intent.payload
    required = {
        "schema", "repository", "issue_number", "predecessor_adc_comment_id", "predecessor_adc_sha256",
        "successor_adc_comment_id", "successor_adc_sha256", "previous_applied_comment_id",
        "previous_applied_payload_sha256", "operation", "from_phase", "to_phase",
        "labels_before", "labels_after", "issue_body_sha256", "executor_user_id",
    }
    if (set(payload) != required or payload.get("schema") != INTENT_V2_SCHEMA
            or payload.get("repository") != REPOSITORY or payload.get("issue_number") != ISSUE_NUMBER
            or payload.get("predecessor_adc_comment_id") != predecessor.pointer.comment_id
            or payload.get("predecessor_adc_sha256") != predecessor.pointer.sha256
            or payload.get("successor_adc_comment_id") != successor.pointer.comment_id
            or payload.get("successor_adc_sha256") != successor.pointer.sha256
            or payload.get("previous_applied_comment_id") != previous_applied.comment_id
            or payload.get("previous_applied_payload_sha256") != previous_applied.payload_sha256
            or payload.get("operation") != "adopt_existing_requirements"
            or payload.get("from_phase") != "requirements" or payload.get("to_phase") != "requirements"
            or any(not isinstance(payload.get(key), str) or SHA256.fullmatch(payload[key]) is None
                   for key in ("predecessor_adc_sha256", "successor_adc_sha256",
                               "previous_applied_payload_sha256", "issue_body_sha256"))
            or any(type(payload.get(key)) is not int or payload[key] < 1
                   for key in ("predecessor_adc_comment_id", "successor_adc_comment_id",
                               "previous_applied_comment_id", "executor_user_id"))
            or intent.comment_id <= successor.pointer.comment_id
            or intent.comment_id <= previous_applied.comment_id):
        raise PhaseRebaselineError("V2 Intent evidence fields do not match its ADC/history generation")
    _validated_labels(payload, "phase:requirements", "phase:requirements")
    if payload["labels_before"] != payload["labels_after"]:
        raise PhaseRebaselineError("V2 adoption Intent must preserve the complete Issue label set")
    if intent.actor_id != payload["executor_user_id"]:
        raise PhaseRebaselineError("V2 Intent author does not match its authenticated executor identity")
    if applied is None:
        return
    expected = {
        "schema": APPLIED_V2_SCHEMA, "repository": REPOSITORY, "issue_number": ISSUE_NUMBER,
        "intent_comment_id": intent.comment_id, "intent_sha256": intent.payload_sha256,
        "predecessor_adc_comment_id": predecessor.pointer.comment_id,
        "predecessor_adc_sha256": predecessor.pointer.sha256,
        "successor_adc_comment_id": successor.pointer.comment_id,
        "successor_adc_sha256": successor.pointer.sha256,
        "previous_applied_comment_id": previous_applied.comment_id,
        "previous_applied_payload_sha256": previous_applied.payload_sha256,
        "operation": "adopt_existing_requirements", "from_phase": "requirements",
        "to_phase": "requirements", "labels_after": payload["labels_after"],
        "issue_body_sha256": payload["issue_body_sha256"],
        "executor_user_id": payload["executor_user_id"],
    }
    if (set(applied.payload) != {
            "schema", "repository", "issue_number", "intent_comment_id", "intent_sha256",
            "predecessor_adc_comment_id", "predecessor_adc_sha256", "successor_adc_comment_id",
            "successor_adc_sha256", "previous_applied_comment_id", "previous_applied_payload_sha256",
            "operation", "from_phase", "to_phase", "labels_after", "issue_body_sha256", "executor_user_id",
    } or applied.payload != expected or applied.comment_id <= intent.comment_id
            or applied.actor_id != intent.actor_id):
        raise PhaseRebaselineError("V2 Applied evidence does not exactly match its Intent")


def _recovery_generation_indexes(adc_chain: tuple[VerifiedADC, ...]) -> dict[int, tuple[VerifiedADC, VerifiedADC]]:
    """Return only the two exact ADC edges authorized for V3 recovery."""
    recovered: dict[int, tuple[VerifiedADC, VerifiedADC]] = {}
    for predecessor_id, predecessor_sha, successor_id, successor_sha in V3_RECOVERY_GENERATIONS:
        matches = [index for index in range(1, len(adc_chain))
                   if adc_chain[index - 1].pointer.comment_id == predecessor_id
                   and adc_chain[index - 1].pointer.sha256 == predecessor_sha
                   and adc_chain[index].pointer.comment_id == successor_id
                   and adc_chain[index].pointer.sha256 == successor_sha]
        if len(matches) > 1:
            raise PhaseRebaselineError("V3 recovery ADC generation is duplicated")
        if matches:
            index = matches[0]
            recovered[index] = (adc_chain[index - 1], adc_chain[index])
    return recovered


def _validate_v3_pair(intent: PhaseRecord, applied: PhaseRecord | None,
                      predecessor: VerifiedADC, successor: VerifiedADC,
                      previous_applied: PhaseRecord) -> None:
    payload = intent.payload
    first_recovery = successor.pointer.comment_id == V3_RECOVERY_GENERATIONS[0][2]
    expected_from = "execution" if first_recovery else "requirements"
    expected_operation = ("rebaseline_execution_to_requirements" if first_recovery
                          else "adopt_existing_requirements")
    required = {
        "schema", "repository", "issue_number", "predecessor_adc_comment_id", "predecessor_adc_sha256",
        "successor_adc_comment_id", "successor_adc_sha256", "previous_applied_comment_id",
        "previous_applied_payload_sha256", "operation", "from_phase", "to_phase",
        "labels_before", "labels_after", "issue_body_sha256", "executor_user_id",
    }
    if (set(payload) != required or payload.get("schema") != INTENT_V3_SCHEMA
            or payload.get("repository") != REPOSITORY or payload.get("issue_number") != ISSUE_NUMBER
            or payload.get("predecessor_adc_comment_id") != predecessor.pointer.comment_id
            or payload.get("predecessor_adc_sha256") != predecessor.pointer.sha256
            or payload.get("successor_adc_comment_id") != successor.pointer.comment_id
            or payload.get("successor_adc_sha256") != successor.pointer.sha256
            or payload.get("previous_applied_comment_id") != previous_applied.comment_id
            or payload.get("previous_applied_payload_sha256") != previous_applied.payload_sha256
            or payload.get("operation") != expected_operation
            or payload.get("from_phase") != expected_from or payload.get("to_phase") != "requirements"
            or any(not isinstance(payload.get(key), str) or SHA256.fullmatch(payload[key]) is None
                   for key in ("predecessor_adc_sha256", "successor_adc_sha256",
                               "previous_applied_payload_sha256", "issue_body_sha256"))
            or any(type(payload.get(key)) is not int or payload[key] < 1
                   for key in ("predecessor_adc_comment_id", "successor_adc_comment_id",
                               "previous_applied_comment_id", "executor_user_id"))
            or intent.comment_id <= successor.pointer.comment_id
            or intent.comment_id <= previous_applied.comment_id):
        raise PhaseRebaselineError("V3 Intent evidence fields do not match its authorized recovery generation")
    _validated_labels(payload, f"phase:{expected_from}", "phase:requirements")
    expected_after = (sorted([label for label in payload["labels_before"]
                              if label != "phase:execution"] + ["phase:requirements"])
                      if first_recovery else payload["labels_before"])
    if payload["labels_after"] != expected_after:
        raise PhaseRebaselineError("V3 recovery Intent does not describe its exact authorized label operation")
    if intent.actor_id != payload["executor_user_id"]:
        raise PhaseRebaselineError("V3 Intent author does not match its authenticated executor identity")
    if applied is None:
        return
    expected = {
        "schema": APPLIED_V3_SCHEMA, "repository": REPOSITORY, "issue_number": ISSUE_NUMBER,
        "intent_comment_id": intent.comment_id, "intent_sha256": intent.payload_sha256,
        "predecessor_adc_comment_id": predecessor.pointer.comment_id,
        "predecessor_adc_sha256": predecessor.pointer.sha256,
        "successor_adc_comment_id": successor.pointer.comment_id,
        "successor_adc_sha256": successor.pointer.sha256,
        "previous_applied_comment_id": previous_applied.comment_id,
        "previous_applied_payload_sha256": previous_applied.payload_sha256,
        "operation": expected_operation, "from_phase": expected_from,
        "to_phase": "requirements", "labels_after": payload["labels_after"],
        "issue_body_sha256": payload["issue_body_sha256"],
        "executor_user_id": payload["executor_user_id"],
    }
    if (applied.payload != expected or applied.comment_id <= intent.comment_id
            or applied.actor_id != intent.actor_id):
        raise PhaseRebaselineError("V3 Applied evidence does not exactly match its Intent")


def _validate_generation_history(
    records: tuple[PhaseRecord, ...], adc_chain: tuple[VerifiedADC, ...],
) -> tuple[PhaseRecord | None, PhaseRecord | None, dict[int, tuple[PhaseRecord, PhaseRecord | None]]]:
    """Validate immutable V1 and contiguous V2 plus exact, forward-only V3 recovery receipts."""
    v1_intents = [record for record in records if record.schema == INTENT_SCHEMA]
    v1_applied = [record for record in records if record.schema == APPLIED_SCHEMA]
    if len(v1_intents) > 1 or len(v1_applied) > 1:
        raise PhaseRebaselineError("duplicate V1 phase rebaseline evidence")
    v1_intent = v1_intents[0] if v1_intents else None
    v1_result = v1_applied[0] if v1_applied else None
    _validate_v1_pair(v1_intent, v1_result, adc_chain)

    v2_intents: dict[int, PhaseRecord] = {}
    v2_applied: dict[int, PhaseRecord] = {}
    v3_intents: dict[int, PhaseRecord] = {}
    v3_applied: dict[int, PhaseRecord] = {}
    v2_schemas = {INTENT_V2_SCHEMA, APPLIED_V2_SCHEMA}
    v3_schemas = {INTENT_V3_SCHEMA, APPLIED_V3_SCHEMA}
    if len(adc_chain) <= 2 and any(record.schema in v2_schemas | v3_schemas for record in records):
        raise PhaseRebaselineError("V2 phase evidence has no successor ADC generation")
    latest_index = len(adc_chain) - 1
    recovery_generations = _recovery_generation_indexes(adc_chain)
    for record in records:
        if record.schema not in v2_schemas | v3_schemas:
            continue
        pointer_id, digest = record.payload.get("successor_adc_comment_id"), record.payload.get("successor_adc_sha256")
        if (type(pointer_id) is not int or pointer_id < 1 or not isinstance(digest, str)
                or SHA256.fullmatch(digest) is None):
            raise PhaseRebaselineError("V2 phase evidence has a malformed ADC generation key")
        indexes = [index for index, generation in enumerate(adc_chain)
                   if generation.pointer.comment_id == pointer_id and generation.pointer.sha256 == digest]
        if len(indexes) != 1 or indexes[0] < 2 or indexes[0] > latest_index:
            raise PhaseRebaselineError("phase evidence references an unknown or skipped ADC generation")
        index = indexes[0]
        if record.schema in v3_schemas and index not in recovery_generations:
            raise PhaseRebaselineError("V3 phase evidence references a generation outside the approved recovery scope")
        if record.schema in v2_schemas and index in recovery_generations:
            # The two explicitly recovered generations must use their scoped V3
            # receipt pair. V2 remains the normal format for later generations.
            raise PhaseRebaselineError("V2 phase evidence conflicts with an authorized V3 recovery generation")
        if record.schema in {INTENT_V2_SCHEMA, INTENT_V3_SCHEMA}:
            target = v2_intents if record.schema == INTENT_V2_SCHEMA else v3_intents
        else:
            target = v2_applied if record.schema == APPLIED_V2_SCHEMA else v3_applied
        if index in target:
            raise PhaseRebaselineError("duplicate phase evidence for one ADC generation")
        target[index] = record

    if (v1_intent is None or v1_result is None) and len(adc_chain) > 2:
        raise PhaseRebaselineError("new ADC generation cannot skip the incomplete historical V1 phase pair")
    if set(v2_applied) - set(v2_intents) or set(v3_applied) - set(v3_intents):
        raise PhaseRebaselineError("phase Applied evidence has no matching Intent")
    if set(v2_intents) & set(v3_intents) or set(v2_applied) & set(v3_applied):
        raise PhaseRebaselineError("conflicting V2 and V3 phase evidence exists for one ADC generation")

    previous_applied = v1_result
    validated: dict[int, tuple[PhaseRecord, PhaseRecord | None]] = {}
    incomplete_index: int | None = None
    for index in range(2, latest_index + 1):
        is_recovery = index in recovery_generations
        intent = (v3_intents if is_recovery else v2_intents).get(index)
        applied = (v3_applied if is_recovery else v2_applied).get(index)
        if intent is None:
            if applied is not None:
                raise PhaseRebaselineError("phase Applied evidence has no matching Intent")
            if is_recovery:
                # An absent V3 pair is permitted only as a pending exact recovery
                # edge. Later receipts are rejected below until it is filled.
                if incomplete_index is None:
                    incomplete_index = index
                continue
            if index < latest_index:
                raise PhaseRebaselineError("current ADC generation skips one or more completed Phase receipts")
            continue
        if previous_applied is None:
            raise PhaseRebaselineError("phase generation has no completed predecessor Applied record")
        if incomplete_index is not None and index > incomplete_index:
            raise PhaseRebaselineError("phase evidence skips an incomplete authorized recovery generation")
        if is_recovery:
            predecessor, successor = recovery_generations[index]
            _validate_v3_pair(intent, applied, predecessor, successor, previous_applied)
        else:
            _validate_v2_pair(intent, applied, adc_chain, index, previous_applied)
        validated[index] = (intent, applied)
        if applied is not None:
            previous_applied = applied
        else:
            if incomplete_index is not None and incomplete_index != index:
                raise PhaseRebaselineError("multiple incomplete Phase generations exist")
            incomplete_index = index
    if incomplete_index is not None:
        later_records = [index for index in (set(v2_intents) | set(v2_applied) | set(v3_intents) | set(v3_applied))
                         if index > incomplete_index]
        if later_records:
            raise PhaseRebaselineError("phase evidence exists after an incomplete earlier generation")
    if len(adc_chain) > 2 and v1_result is None:
        raise PhaseRebaselineError("V2 phase history has no completed V1 predecessor")
    return v1_intent, v1_result, validated


def _create_and_verify(github: Any, schema: str, payload: dict[str, Any]) -> PhaseRecord:
    body = _body(schema, payload)
    records = _read_history(github)
    matching = [record for record in records if record.schema == schema and record.body == body]
    if schema in {INTENT_V2_SCHEMA, APPLIED_V2_SCHEMA, INTENT_V3_SCHEMA, APPLIED_V3_SCHEMA}:
        generation_key = (payload.get("successor_adc_comment_id"), payload.get("successor_adc_sha256"))
        conflicting = [record for record in records
                       if record.schema == schema and record.body != body
                       and (record.payload.get("successor_adc_comment_id"),
                            record.payload.get("successor_adc_sha256")) == generation_key]
    else:
        conflicting = [record for record in records if record.schema == schema and record.body != body]
    if conflicting or len(matching) > 1:
        raise PhaseRebaselineError(f"conflicting or duplicate {schema} records exist")
    if matching:
        return matching[0]
    try:
        github.create_issue_comment(ISSUE_NUMBER, body)
    except GitHubError as exc:
        if exc.status_code == 403:
            raise PhaseRebaselineError(f"BLOCKED_PERMISSION: cannot append {schema} evidence") from exc
        # A lost response is resolved by exact history readback before any retry.
    after = _read_history(github)
    matching = [record for record in after if record.schema == schema and record.body == body]
    if len(matching) != 1:
        raise PhaseRebaselineError(f"{schema} evidence was not confirmed by direct/list/direct readback")
    return matching[0]


def _verify_current_successor(github: Any, intent: PhaseRecord) -> tuple[VerifiedADC, VerifiedADC]:
    chain = _approved_generations(github)
    payload = intent.payload
    if intent.schema == INTENT_SCHEMA:
        if len(chain) != 2:
            raise PhaseRebaselineError("the incomplete V1 phase bootstrap cannot resume after a newer ADC generation")
        predecessor, successor = chain
    elif intent.schema == INTENT_V2_SCHEMA:
        predecessor, successor = chain[-2:]
    elif intent.schema == INTENT_V3_SCHEMA:
        predecessor_id = payload.get("predecessor_adc_comment_id")
        predecessor_sha = payload.get("predecessor_adc_sha256")
        successor_id = payload.get("successor_adc_comment_id")
        successor_sha = payload.get("successor_adc_sha256")
        matches = [(chain[index - 1], chain[index]) for index in range(1, len(chain))
                   if chain[index - 1].pointer.comment_id == predecessor_id
                   and chain[index - 1].pointer.sha256 == predecessor_sha
                   and chain[index].pointer.comment_id == successor_id
                   and chain[index].pointer.sha256 == successor_sha]
        authorized = any((predecessor_id, predecessor_sha, successor_id, successor_sha) == edge
                         for edge in V3_RECOVERY_GENERATIONS)
        if not authorized or len(matches) != 1:
            raise PhaseRebaselineError("V3 Intent does not match an exact approved recovery ADC generation")
        predecessor, successor = matches[0]
    else:
        raise PhaseRebaselineError("phase Intent schema is unsupported")
    if (predecessor.pointer.comment_id != payload["predecessor_adc_comment_id"]
            or predecessor.pointer.sha256 != payload["predecessor_adc_sha256"]
            or successor.pointer.comment_id != payload["successor_adc_comment_id"]
            or successor.pointer.sha256 != payload["successor_adc_sha256"]):
        raise PhaseRebaselineError("approved ADC pointer changed after the phase Intent")
    return predecessor, successor


def _append_applied(github: Any, intent: PhaseRecord) -> PhaseRecord:
    payload = intent.payload
    if intent.schema == INTENT_SCHEMA:
        schema = APPLIED_SCHEMA
        applied_payload = {
            "schema": schema, "repository": REPOSITORY, "issue_number": ISSUE_NUMBER,
            "intent_comment_id": intent.comment_id, "intent_sha256": intent.payload_sha256,
            "predecessor_adc_comment_id": payload["predecessor_adc_comment_id"],
            "predecessor_adc_sha256": payload["predecessor_adc_sha256"],
            "successor_adc_comment_id": payload["successor_adc_comment_id"],
            "successor_adc_sha256": payload["successor_adc_sha256"],
            "from_phase": "ready", "to_phase": "requirements",
            "labels_after": payload["labels_after"],
        }
        # Historical V1 carriers exist with and without executor_user_id.
        # Preserve the accepted Intent's exact schema during interrupted recovery.
        if "executor_user_id" in payload:
            applied_payload["executor_user_id"] = payload["executor_user_id"]
    elif intent.schema == INTENT_V2_SCHEMA:
        schema = APPLIED_V2_SCHEMA
        applied_payload = {
            "schema": schema, "repository": REPOSITORY, "issue_number": ISSUE_NUMBER,
            "intent_comment_id": intent.comment_id, "intent_sha256": intent.payload_sha256,
            "predecessor_adc_comment_id": payload["predecessor_adc_comment_id"],
            "predecessor_adc_sha256": payload["predecessor_adc_sha256"],
            "successor_adc_comment_id": payload["successor_adc_comment_id"],
            "successor_adc_sha256": payload["successor_adc_sha256"],
            "previous_applied_comment_id": payload["previous_applied_comment_id"],
            "previous_applied_payload_sha256": payload["previous_applied_payload_sha256"],
            "operation": payload["operation"], "from_phase": payload["from_phase"],
            "to_phase": payload["to_phase"], "labels_after": payload["labels_after"],
            "issue_body_sha256": payload["issue_body_sha256"],
            "executor_user_id": payload["executor_user_id"],
        }
    elif intent.schema == INTENT_V3_SCHEMA:
        schema = APPLIED_V3_SCHEMA
        applied_payload = {
            "schema": schema, "repository": REPOSITORY, "issue_number": ISSUE_NUMBER,
            "intent_comment_id": intent.comment_id, "intent_sha256": intent.payload_sha256,
            "predecessor_adc_comment_id": payload["predecessor_adc_comment_id"],
            "predecessor_adc_sha256": payload["predecessor_adc_sha256"],
            "successor_adc_comment_id": payload["successor_adc_comment_id"],
            "successor_adc_sha256": payload["successor_adc_sha256"],
            "previous_applied_comment_id": payload["previous_applied_comment_id"],
            "previous_applied_payload_sha256": payload["previous_applied_payload_sha256"],
            "operation": payload["operation"], "from_phase": payload["from_phase"],
            "to_phase": payload["to_phase"], "labels_after": payload["labels_after"],
            "issue_body_sha256": payload["issue_body_sha256"],
            "executor_user_id": payload["executor_user_id"],
        }
    else:
        raise PhaseRebaselineError("phase Intent schema is unsupported")
    current_chain = _approved_generations(github)
    history_before_apply = _read_history(github)
    _validate_generation_history(history_before_apply, current_chain)
    if not any(record.comment_id == intent.comment_id and record.body == intent.body
               for record in history_before_apply):
        raise PhaseRebaselineError("matching phase Intent disappeared before Applied append")
    _verify_post_write(github, intent)
    record = _create_and_verify(github, schema, applied_payload)
    _validate_generation_history(_read_history(github), _approved_generations(github))
    return record


def _labels_exact(labels: list[str], expected: list[str]) -> bool:
    return len(labels) == len(expected) and set(labels) == set(expected)


def _verify_post_write(github: Any, intent: PhaseRecord) -> None:
    expected_labels = intent.payload["labels_after"]
    body_digest = intent.payload["issue_body_sha256"]
    first_issue, first_labels = _issue_state(github)
    _verify_current_successor(github, intent)
    second_issue, second_labels = _issue_state(github)
    _verify_current_successor(github, intent)
    if (first_issue.get("body") != second_issue.get("body")
            or hashlib.sha256(first_issue["body"].encode("utf-8")).hexdigest() != body_digest
            or not _labels_exact(first_labels, expected_labels)
            or not _labels_exact(second_labels, expected_labels)
            or first_issue.get("state") != second_issue.get("state")
            or first_issue.get("repository_url") != second_issue.get("repository_url")):
        raise PhaseRebaselineError("Issue or approved ADC changed during double post-write readback")


def rebaseline_issue_phase(github: Any, issue_number: int = ISSUE_NUMBER) -> dict[str, Any]:
    """Record append-only phase evidence for each approved #63 ADC generation.

    The first ADC successor keeps the historical V1 ready→requirements label
    transition. Later successors adopt the already-current requirements phase
    with V2 receipts and never write Issue labels.
    """
    if type(issue_number) is not int or issue_number != ISSUE_NUMBER:
        raise PhaseRebaselineError("phase rebaseline is restricted to Issue #63")
    try:
        identity = github.authenticated_user()
        if (not isinstance(identity, dict) or type(identity.get("id")) is not int or identity["id"] < 1
                or not isinstance(identity.get("login"), str) or identity.get("type") != "User"):
            raise PhaseRebaselineError("authenticated GitHub workflow executor identity is invalid")
        adc_chain = _approved_generations(github)
        successor = adc_chain[-1]
        initial_issue, initial_labels = _issue_state(github)
        records = _read_history(github)
        v1_intent, v1_applied, v2_pairs = _validate_generation_history(records, adc_chain)

        if len(adc_chain) == 2:
            if v1_applied is not None and v1_intent is not None:
                if (hashlib.sha256(initial_issue["body"].encode("utf-8")).hexdigest()
                        != v1_intent.payload["issue_body_sha256"]
                        or not _labels_exact(initial_labels, v1_intent.payload["labels_after"])):
                    raise PhaseRebaselineError("completed V1 phase evidence does not match the current Issue")
                _verify_post_write(github, v1_intent)
                return {"status": "NOOP", "intent_comment_id": v1_intent.comment_id,
                        "applied_comment_id": v1_applied.comment_id,
                        "adc_comment_id": successor.pointer.comment_id,
                        "adc_sha256": successor.pointer.sha256, "labels": sorted(initial_labels)}

            if v1_intent is not None:
                _verify_current_successor(github, v1_intent)
                before_labels = v1_intent.payload["labels_before"]
                after_labels = v1_intent.payload["labels_after"]
                body_digest = hashlib.sha256(initial_issue["body"].encode("utf-8")).hexdigest()
                if body_digest != v1_intent.payload["issue_body_sha256"]:
                    raise PhaseRebaselineError("Issue body changed after the V1 phase Intent")
                if _labels_exact(initial_labels, after_labels):
                    _verify_post_write(github, v1_intent)
                    applied_record = _append_applied(github, v1_intent)
                    return {"status": "RECOVERED", "intent_comment_id": v1_intent.comment_id,
                            "applied_comment_id": applied_record.comment_id,
                            "adc_comment_id": successor.pointer.comment_id,
                            "adc_sha256": successor.pointer.sha256, "labels": after_labels}
                if _labels_exact(initial_labels, before_labels):
                    raise PhaseRebaselineError(
                        "V1 phase Intent already exists but target labels are absent; refusing a second PUT")
                raise PhaseRebaselineError("Issue labels drifted after the V1 phase Intent")

            phase_labels = [label for label in initial_labels if label.startswith("phase:")]
            kind_labels = [label for label in initial_labels if label.startswith("kind:")]
            if phase_labels != ["phase:ready"] or kind_labels != ["kind:single"]:
                raise PhaseRebaselineError("Issue #63 is not in the exact phase:ready / kind:single bootstrap state")
            predecessor = adc_chain[0]
            before_labels = sorted(initial_labels)
            after_labels = sorted([label for label in initial_labels if label != "phase:ready"]
                                  + ["phase:requirements"])
            payload = _intent_v1_payload(predecessor, successor, initial_issue["body"],
                                         before_labels, after_labels, identity["id"])
            intent = _create_and_verify(github, INTENT_SCHEMA, payload)
            _validate_generation_history(_read_history(github), adc_chain)

            latest_issue, latest_labels = _issue_state(github)
            _verify_current_successor(github, intent)
            if (latest_issue.get("body") != initial_issue.get("body")
                    or not _labels_exact(latest_labels, before_labels)):
                raise PhaseRebaselineError("Issue or ADC changed before the one permitted label PUT")
            try:
                github.replace_issue_labels(ISSUE_NUMBER, after_labels)
            except GitHubError as exc:
                if exc.status_code == 403:
                    raise PhaseRebaselineError(
                        "BLOCKED_PERMISSION: authenticated executor cannot update Issue labels") from exc
                current_issue, current_labels = _issue_state(github)
                if (not _labels_exact(current_labels, after_labels)
                        or current_issue.get("body") != initial_issue.get("body")):
                    raise PhaseRebaselineError(
                        "label PUT outcome is uncertain; refusing another write") from exc
            _verify_post_write(github, intent)
            applied_record = _append_applied(github, intent)
            return {"status": "APPLIED", "intent_comment_id": intent.comment_id,
                    "applied_comment_id": applied_record.comment_id,
                    "adc_comment_id": successor.pointer.comment_id,
                    "adc_sha256": successor.pointer.sha256, "labels": after_labels}

        if v1_intent is None or v1_applied is None:
            raise PhaseRebaselineError("new ADC generation requires the completed immutable V1 predecessor pair")
        recovery_generations = _recovery_generation_indexes(adc_chain)
        incomplete_recoveries = [
            recovery_index for recovery_index in recovery_generations
            if (v2_pairs.get(recovery_index) is None or v2_pairs[recovery_index][1] is None)
        ]
        for recovery_index in incomplete_recoveries:
            recovery_successor = recovery_generations[recovery_index][1]
            _require_adc_supersede_decision(github, recovery_successor)
        for recovery_index, (predecessor, recovery_successor) in sorted(recovery_generations.items()):
            recovery_pair = v2_pairs.get(recovery_index)
            if recovery_pair is not None:
                intent, applied = recovery_pair
                body_digest = hashlib.sha256(initial_issue["body"].encode("utf-8")).hexdigest()
                if body_digest != intent.payload["issue_body_sha256"]:
                    raise PhaseRebaselineError("Issue body changed after the V3 recovery Intent")
                _verify_current_successor(github, intent)
                before_labels = intent.payload["labels_before"]
                after_labels = intent.payload["labels_after"]
                if applied is not None:
                    if not _labels_exact(initial_labels, after_labels):
                        raise PhaseRebaselineError("completed V3 recovery evidence does not match current Issue labels")
                    _verify_post_write(github, intent)
                    continue
                if recovery_index == min(recovery_generations):
                    if _labels_exact(initial_labels, before_labels):
                        raise PhaseRebaselineError(
                            "V3 Intent exists but target labels are absent; refusing a second label PUT")
                    if not _labels_exact(initial_labels, after_labels):
                        raise PhaseRebaselineError("Issue labels drifted after the V3 recovery Intent")
                elif not _labels_exact(initial_labels, after_labels):
                    raise PhaseRebaselineError("V3 requirements adoption does not match current Issue labels")
                _verify_post_write(github, intent)
                applied_record = _append_applied(github, intent)
                return {"status": "RECOVERED_V3", "phase_action": "RECOVER_MISSING_GENERATION",
                        "label_writes": 0, "intent_comment_id": intent.comment_id,
                        "applied_comment_id": applied_record.comment_id,
                        "adc_comment_id": successor.pointer.comment_id,
                        "adc_sha256": successor.pointer.sha256, "labels": sorted(initial_labels)}

            previous_applied = (v1_applied if recovery_index - 1 == 1
                                else v2_pairs.get(recovery_index - 1, (None, None))[1])
            if previous_applied is None:
                raise PhaseRebaselineError("V3 recovery requires the immediately preceding Applied receipt")
            first_recovery = recovery_successor.pointer.comment_id == V3_RECOVERY_GENERATIONS[0][2]
            expected_phase = "execution" if first_recovery else "requirements"
            phase_labels = [label for label in initial_labels if label.startswith("phase:")]
            kind_labels = [label for label in initial_labels if label.startswith("kind:")]
            if phase_labels != [f"phase:{expected_phase}"] or kind_labels != ["kind:single"]:
                raise PhaseRebaselineError(
                    f"V3 recovery requires the exact phase:{expected_phase} / kind:single state")
            labels_before = sorted(initial_labels)
            payload = _intent_v3_payload(predecessor, recovery_successor, previous_applied,
                                         initial_issue["body"], labels_before, identity["id"])
            intent = _create_and_verify(github, INTENT_V3_SCHEMA, payload)
            _validate_generation_history(_read_history(github), adc_chain)
            latest_issue, latest_labels = _issue_state(github)
            _verify_current_successor(github, intent)
            if (latest_issue.get("body") != initial_issue.get("body")
                    or not _labels_exact(latest_labels, payload["labels_before"])):
                raise PhaseRebaselineError("Issue or ADC changed before the V3 recovery operation")
            if first_recovery:
                try:
                    github.replace_issue_labels(ISSUE_NUMBER, payload["labels_after"])
                except GitHubError as exc:
                    if exc.status_code == 403:
                        raise PhaseRebaselineError(
                            "BLOCKED_PERMISSION: authenticated executor cannot update Issue labels") from exc
                    current_issue, current_labels = _issue_state(github)
                    if (not _labels_exact(current_labels, payload["labels_after"])
                            or current_issue.get("body") != initial_issue.get("body")):
                        raise PhaseRebaselineError(
                            "V3 label PUT outcome is uncertain; refusing another write") from exc
            _verify_post_write(github, intent)
            applied_record = _append_applied(github, intent)
            return {"status": "APPLIED_V3", "phase_action": "RECOVER_MISSING_GENERATION",
                    "label_writes": 1 if first_recovery else 0,
                    "intent_comment_id": intent.comment_id,
                    "applied_comment_id": applied_record.comment_id,
                    "adc_comment_id": successor.pointer.comment_id,
                    "adc_sha256": successor.pointer.sha256,
                    "labels": payload["labels_after"]}

        generation_index = len(adc_chain) - 1
        current_pair = v2_pairs.get(generation_index)
        if current_pair is not None:
            intent, applied = current_pair
            if (hashlib.sha256(initial_issue["body"].encode("utf-8")).hexdigest()
                    != intent.payload["issue_body_sha256"]
                    or not _labels_exact(initial_labels, intent.payload["labels_after"])):
                raise PhaseRebaselineError("completed V2 phase evidence does not match the current Issue")
            if applied is not None:
                _verify_post_write(github, intent)
                return {"status": "NOOP", "phase_action": "ADOPT_EXISTING_REQUIREMENTS",
                        "label_writes": 0, "intent_comment_id": intent.comment_id,
                        "applied_comment_id": applied.comment_id,
                        "adc_comment_id": successor.pointer.comment_id,
                        "adc_sha256": successor.pointer.sha256, "labels": sorted(initial_labels)}
            _verify_current_successor(github, intent)
            _verify_post_write(github, intent)
            applied_record = _append_applied(github, intent)
            return {"status": "RECOVERED", "phase_action": "ADOPT_EXISTING_REQUIREMENTS",
                    "label_writes": 0, "intent_comment_id": intent.comment_id,
                    "applied_comment_id": applied_record.comment_id,
                    "adc_comment_id": successor.pointer.comment_id,
                    "adc_sha256": successor.pointer.sha256, "labels": sorted(initial_labels)}

        phase_labels = [label for label in initial_labels if label.startswith("phase:")]
        kind_labels = [label for label in initial_labels if label.startswith("kind:")]
        if phase_labels != ["phase:requirements"] or kind_labels != ["kind:single"]:
            raise PhaseRebaselineError("V2 adoption requires the exact phase:requirements / kind:single state")
        previous_applied = (v1_applied if generation_index == 2
                            else v2_pairs[generation_index - 1][1])
        if previous_applied is None:
            raise PhaseRebaselineError("V2 adoption requires the previous ADC generation's Applied record")
        labels = sorted(initial_labels)
        payload = _intent_v2_payload(adc_chain[-2], successor, previous_applied,
                                     initial_issue["body"], labels, identity["id"])
        intent = _create_and_verify(github, INTENT_V2_SCHEMA, payload)
        _validate_generation_history(_read_history(github), adc_chain)
        _verify_post_write(github, intent)
        applied_record = _append_applied(github, intent)
        return {"status": "RECORDED", "phase_action": "ADOPT_EXISTING_REQUIREMENTS",
                "label_writes": 0, "intent_comment_id": intent.comment_id,
                "applied_comment_id": applied_record.comment_id,
                "adc_comment_id": successor.pointer.comment_id,
                "adc_sha256": successor.pointer.sha256, "labels": labels}
    except PhaseRebaselineError:
        raise
    except (ADCError, GitHubError) as exc:
        if isinstance(exc, GitHubError) and exc.status_code == 403:
            raise PhaseRebaselineError("BLOCKED_PERMISSION: authenticated executor lacks required GitHub write permission") from exc
        raise PhaseRebaselineError(str(exc)) from exc
