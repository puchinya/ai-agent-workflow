"""One-time Issue #63 phase bootstrap based on its approved ADC successor.

The phase change is an ordinary workflow execution step after the successor ADC
has been approved and published. Intent and Applied comments are append-only
technical evidence; they are not owner decisions.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .adc import (
    ADCError, ADCPointer, VerifiedADC, verify_adc, verify_adc_forward_generations,
    verify_adc_generation,
)
from .github import GitHubError

REPOSITORY = "puchinya/ai-agent-workflow"
ISSUE_NUMBER = 63
OWNER_ID = 3744776
BASELINE_ADC_COMMENT_ID = 6228771805
BASELINE_ADC_SHA256 = "ad13d005126693bb4e1cbe1e7eaa815e43f0a1ef3b88ef9f1670450a42bc9622"
INTENT_SCHEMA = "PASES_PHASE_REBASE_INTENT_V1"
APPLIED_SCHEMA = "PASES_PHASE_REBASE_APPLIED_V1"
INTENT_START = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_START = f"<!-- {APPLIED_SCHEMA}\n"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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
    start = INTENT_START if schema == INTENT_SCHEMA else APPLIED_START
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
            if not isinstance(body, str) or "PASES_PHASE_REBASE_" not in body:
                continue
            if body.startswith(INTENT_START):
                schema = INTENT_SCHEMA
            elif body.startswith(APPLIED_START):
                schema = APPLIED_SCHEMA
            else:
                raise PhaseRebaselineError("unknown or malformed phase rebaseline marker")
            first_rows.append((row, schema))
        ids = [row.get("id") for row, _schema in first_rows]
        if any(type(comment_id) is not int or comment_id < 1 for comment_id in ids):
            raise PhaseRebaselineError("phase evidence history contains an invalid comment ID")
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise PhaseRebaselineError("phase evidence history is duplicated or not append-only")
        direct_before = {
            row["id"]: github.issue_comment(ISSUE_NUMBER, row["id"])
            for row, _schema in first_rows
        }
        second = github.issue_comments(ISSUE_NUMBER)
        second_rows = []
        for row in second:
            body = row.get("body") if isinstance(row, dict) else None
            if isinstance(body, str) and "PASES_PHASE_REBASE_" in body:
                second_rows.append(row)
        second_ids = [row.get("id") if isinstance(row, dict) else None for row in second_rows]
        if second_ids != ids:
            raise PhaseRebaselineError("phase evidence history changed during direct/list/direct readback")
        direct_after = {
            row["id"]: github.issue_comment(ISSUE_NUMBER, row["id"])
            for row, _schema in first_rows
        }
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


def _approved_generation(github: Any) -> tuple[VerifiedADC, VerifiedADC]:
    try:
        if getattr(github, "repo", None) != REPOSITORY:
            raise PhaseRebaselineError("phase rebaseline is restricted to puchinya/ai-agent-workflow#63")
        metadata = github.repository_metadata()
        owner = metadata.get("owner") if isinstance(metadata, dict) else None
        if (not isinstance(metadata, dict) or metadata.get("id") != 1401910271
                or metadata.get("full_name") != REPOSITORY or not isinstance(owner, dict)
                or owner.get("type") != "User" or owner.get("id") != OWNER_ID):
            raise PhaseRebaselineError("configured repository identity changed")
        issue, _labels = _issue_state(github)
        if not isinstance(issue.get("body"), str):
            raise PhaseRebaselineError("Issue body is not text")
        current = verify_adc(github, ISSUE_NUMBER)
        if current.pointer.state != "approved":
            raise PhaseRebaselineError("current ADC pointer is not approved")
        successor_text = current.contract.content.decode("utf-8", errors="strict")
        required_authority = (
            "REQ-F01-015", INTENT_SCHEMA, APPLIED_SCHEMA,
            "phase:ready", "phase:requirements", "Phase rebaseline is not a decision",
            "without a separate phase approval",
        )
        if ("REQ-F01-015" not in current.contract.requirement_ids
                or any(term not in successor_text for term in required_authority[1:])):
            raise PhaseRebaselineError("approved successor ADC does not contain the exact phase-bootstrap authority")
        predecessor = verify_adc_generation(
            github, ISSUE_NUMBER, BASELINE_ADC_COMMENT_ID, BASELINE_ADC_SHA256, state="approved",
        )
        chain = verify_adc_forward_generations(
            github, ISSUE_NUMBER,
            prior_comment_id=predecessor.pointer.comment_id,
            prior_sha256=predecessor.pointer.sha256,
            current_comment_id=current.pointer.comment_id,
            current_sha256=current.pointer.sha256,
        )
        if len(chain) < 2 or chain[0].pointer != predecessor.pointer or chain[-1].pointer != current.pointer:
            raise PhaseRebaselineError("current approved ADC is not a forward successor of the configured baseline")
        return predecessor, current
    except ADCError as exc:
        raise PhaseRebaselineError(str(exc)) from exc


def _intent_payload(predecessor: VerifiedADC, successor: VerifiedADC, body: str,
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


def _validate_payloads(records: tuple[PhaseRecord, ...]) -> tuple[PhaseRecord | None, PhaseRecord | None]:
    intents = [record for record in records if record.schema == INTENT_SCHEMA]
    applied = [record for record in records if record.schema == APPLIED_SCHEMA]
    if len(intents) > 1 or len(applied) > 1:
        raise PhaseRebaselineError("duplicate phase rebaseline intent or applied evidence")
    if applied and not intents:
        raise PhaseRebaselineError("Applied evidence has no matching Intent")
    intent = intents[0] if intents else None
    result = applied[0] if applied else None
    if intent is not None:
        payload = intent.payload
        required = {
            "schema", "repository", "issue_number", "predecessor_adc_comment_id", "predecessor_adc_sha256",
            "successor_adc_comment_id", "successor_adc_sha256", "from_phase", "to_phase",
            "labels_before", "labels_after", "issue_body_sha256", "executor_user_id",
        }
        if (set(payload) != required or payload.get("repository") != REPOSITORY
                or payload.get("issue_number") != ISSUE_NUMBER
                or payload.get("from_phase") != "ready" or payload.get("to_phase") != "requirements"
                or any(not isinstance(payload.get(key), str) or SHA256.fullmatch(payload[key]) is None
                       for key in ("predecessor_adc_sha256", "successor_adc_sha256", "issue_body_sha256"))
                or any(type(payload.get(key)) is not int or payload[key] < 1
                       for key in ("predecessor_adc_comment_id", "successor_adc_comment_id", "executor_user_id"))
                or not isinstance(payload.get("labels_before"), list)
                or not isinstance(payload.get("labels_after"), list)
                or any(not isinstance(label, str) for label in payload["labels_before"] + payload["labels_after"])
                or payload["labels_before"] != sorted(set(payload["labels_before"]))
                or payload["labels_after"] != sorted(set(payload["labels_after"]))
                or payload["successor_adc_comment_id"] <= payload["predecessor_adc_comment_id"]
                or intent.comment_id <= payload["successor_adc_comment_id"]):
            raise PhaseRebaselineError("Intent evidence fields are invalid")
        if intent.actor_id != payload["executor_user_id"]:
            raise PhaseRebaselineError("Intent author does not match its authenticated executor identity")
        before = payload["labels_before"]
        after = payload["labels_after"]
        before_phase = [label for label in before if label.startswith("phase:")]
        after_phase = [label for label in after if label.startswith("phase:")]
        before_kind = [label for label in before if label.startswith("kind:")]
        after_kind = [label for label in after if label.startswith("kind:")]
        expected_after = sorted([label for label in before if label != "phase:ready"]
                                + ["phase:requirements"])
        if (before_phase != ["phase:ready"] or after_phase != ["phase:requirements"]
                or before_kind != ["kind:single"] or after_kind != ["kind:single"]
                or after != expected_after):
            raise PhaseRebaselineError("Intent does not describe the exact #63 phase-label replacement")
    if result is not None and intent is not None:
        payload = result.payload
        expected = {
            "schema": APPLIED_SCHEMA,
            "repository": REPOSITORY,
            "issue_number": ISSUE_NUMBER,
            "intent_comment_id": intent.comment_id,
            "intent_sha256": intent.payload_sha256,
            "predecessor_adc_comment_id": intent.payload["predecessor_adc_comment_id"],
            "predecessor_adc_sha256": intent.payload["predecessor_adc_sha256"],
            "successor_adc_comment_id": intent.payload["successor_adc_comment_id"],
            "successor_adc_sha256": intent.payload["successor_adc_sha256"],
            "from_phase": "ready",
            "to_phase": "requirements",
            "labels_after": intent.payload["labels_after"],
            "executor_user_id": intent.payload["executor_user_id"],
        }
        if (payload != expected or result.comment_id <= intent.comment_id
                or result.actor_id != intent.actor_id):
            raise PhaseRebaselineError("Applied evidence does not exactly match its Intent")
    return intent, result


def _create_and_verify(github: Any, schema: str, payload: dict[str, Any]) -> PhaseRecord:
    body = _body(schema, payload)
    records = _read_history(github)
    matching = [record for record in records if record.schema == schema and record.body == body]
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
    predecessor, successor = _approved_generation(github)
    payload = intent.payload
    if (predecessor.pointer.comment_id != payload["predecessor_adc_comment_id"]
            or predecessor.pointer.sha256 != payload["predecessor_adc_sha256"]
            or successor.pointer.comment_id != payload["successor_adc_comment_id"]
            or successor.pointer.sha256 != payload["successor_adc_sha256"]):
        raise PhaseRebaselineError("approved ADC pointer changed after the phase Intent")
    return predecessor, successor


def _append_applied(github: Any, intent: PhaseRecord) -> PhaseRecord:
    payload = intent.payload
    applied_payload = {
        "schema": APPLIED_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "intent_comment_id": intent.comment_id,
        "intent_sha256": intent.payload_sha256,
        "predecessor_adc_comment_id": payload["predecessor_adc_comment_id"],
        "predecessor_adc_sha256": payload["predecessor_adc_sha256"],
        "successor_adc_comment_id": payload["successor_adc_comment_id"],
        "successor_adc_sha256": payload["successor_adc_sha256"],
        "from_phase": "ready",
        "to_phase": "requirements",
        "labels_after": payload["labels_after"],
        "executor_user_id": payload["executor_user_id"],
    }
    record = _create_and_verify(github, APPLIED_SCHEMA, applied_payload)
    _validate_payloads(_read_history(github))
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
    """Apply the one-time #63 ready→requirements bootstrap after ADC approval.

    An Intent permits at most one label PUT. If a process stops after writing
    Intent, a retry can finish only when the target labels are already present;
    an old or drifted label set blocks without another PUT.
    """
    if type(issue_number) is not int or issue_number != ISSUE_NUMBER:
        raise PhaseRebaselineError("phase rebaseline is restricted to Issue #63")
    try:
        identity = github.authenticated_user()
        if (not isinstance(identity, dict) or type(identity.get("id")) is not int or identity["id"] < 1
                or not isinstance(identity.get("login"), str) or identity.get("type") != "User"):
            raise PhaseRebaselineError("authenticated GitHub workflow executor identity is invalid")
        _predecessor, successor = _approved_generation(github)
        initial_issue, initial_labels = _issue_state(github)
        records = _read_history(github)
        intent, applied = _validate_payloads(records)

        if applied is not None:
            if intent is None:
                raise PhaseRebaselineError("Applied evidence has no Intent")
            if (hashlib.sha256(initial_issue["body"].encode("utf-8")).hexdigest()
                    != intent.payload["issue_body_sha256"]
                    or not _labels_exact(initial_labels, intent.payload["labels_after"])):
                raise PhaseRebaselineError("completed phase evidence does not match the current Issue")
            _verify_post_write(github, intent)
            return {"status": "NOOP", "intent_comment_id": intent.comment_id,
                    "applied_comment_id": applied.comment_id,
                    "adc_comment_id": successor.pointer.comment_id,
                    "adc_sha256": successor.pointer.sha256, "labels": sorted(initial_labels)}

        if intent is not None:
            _verify_current_successor(github, intent)
            before_labels = intent.payload["labels_before"]
            after_labels = intent.payload["labels_after"]
            body_digest = hashlib.sha256(initial_issue["body"].encode("utf-8")).hexdigest()
            if body_digest != intent.payload["issue_body_sha256"]:
                raise PhaseRebaselineError("Issue body changed after the phase Intent")
            if _labels_exact(initial_labels, after_labels):
                _verify_post_write(github, intent)
                applied_record = _append_applied(github, intent)
                return {"status": "RECOVERED", "intent_comment_id": intent.comment_id,
                        "applied_comment_id": applied_record.comment_id,
                        "adc_comment_id": successor.pointer.comment_id,
                        "adc_sha256": successor.pointer.sha256, "labels": after_labels}
            if _labels_exact(initial_labels, before_labels):
                raise PhaseRebaselineError("phase Intent already exists but target labels are absent; refusing a second PUT")
            raise PhaseRebaselineError("Issue labels drifted after the phase Intent")

        phase_labels = [label for label in initial_labels if label.startswith("phase:")]
        kind_labels = [label for label in initial_labels if label.startswith("kind:")]
        if phase_labels != ["phase:ready"] or kind_labels != ["kind:single"]:
            raise PhaseRebaselineError("Issue #63 is not in the exact phase:ready / kind:single bootstrap state")
        after_labels = sorted([label for label in initial_labels if label != "phase:ready"]
                              + ["phase:requirements"])
        before_labels = sorted(initial_labels)
        payload = _intent_payload(_predecessor, successor, initial_issue["body"],
                                  before_labels, after_labels, identity["id"])
        intent = _create_and_verify(github, INTENT_SCHEMA, payload)
        _validate_payloads(_read_history(github))

        latest_issue, latest_labels = _issue_state(github)
        _verify_current_successor(github, intent)
        if (latest_issue.get("body") != initial_issue.get("body")
                or not _labels_exact(latest_labels, before_labels)):
            raise PhaseRebaselineError("Issue or ADC changed before the one permitted label PUT")
        try:
            github.replace_issue_labels(ISSUE_NUMBER, after_labels)
        except GitHubError as exc:
            if exc.status_code == 403:
                raise PhaseRebaselineError("BLOCKED_PERMISSION: authenticated executor cannot update Issue labels") from exc
            current_issue, current_labels = _issue_state(github)
            if (_labels_exact(current_labels, after_labels)
                    and current_issue.get("body") == initial_issue.get("body")):
                # The PUT may have succeeded even though its response was lost.
                pass
            else:
                raise PhaseRebaselineError("label PUT outcome is uncertain; refusing another write") from exc
        _verify_post_write(github, intent)
        applied_record = _append_applied(github, intent)
        return {"status": "APPLIED", "intent_comment_id": intent.comment_id,
                "applied_comment_id": applied_record.comment_id,
                "adc_comment_id": successor.pointer.comment_id,
                "adc_sha256": successor.pointer.sha256, "labels": after_labels}
    except PhaseRebaselineError:
        raise
    except (ADCError, GitHubError) as exc:
        if isinstance(exc, GitHubError) and exc.status_code == 403:
            raise PhaseRebaselineError("BLOCKED_PERMISSION: authenticated executor lacks required GitHub write permission") from exc
        raise PhaseRebaselineError(str(exc)) from exc
