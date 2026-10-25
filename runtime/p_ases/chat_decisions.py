"""Append-only, operator-reported chat decisions for Issue #46 workflows.

These records report that an affirmative answer was received in the active chat.
They do not prove the chat host's identity or provide a cryptographic signature.
The GitHub actor is recorded only as the technical recorder.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .github import GitHub, GitHubError


SCHEMA_V1 = "PASES_OPERATOR_REPORTED_CHAT_DECISION_V1"
SCHEMA_V2 = "PASES_OPERATOR_REPORTED_CHAT_DECISION_V2"
V1_MARKER = f"<!-- {SCHEMA_V1}\n"
V2_MARKER = f"<!-- {SCHEMA_V2}\n"
REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
ISSUE_NUMBER = 46
ISSUE_ID = 5846549384
PR_NUMBER = 67
OWNER_ID = 3744776
SHA256 = re.compile(r"^[0-9a-f]{64}$")
OPERATIONS = {"ADC_SUPERSEDE", "REVIEW_UNAVAILABLE_EXCEPTION", "USER_REVIEW", "PR_MERGE"}
V1_FIELDS = {
    "answer", "evidence_channel", "github_recorder", "issue_id", "issue_number",
    "pr_head_sha40", "pr_number", "question_item_id", "recorded_at", "repository",
    "repository_id", "schema", "scope", "scope_sha256", "subject_sha256",
}
V2_FIELDS = {
    "answer", "evidence_channel", "github_recorder", "issue_id", "issue_number",
    "operation", "predecessor_decision_comment_id", "pr_number", "question_item_id",
    "recorded_at", "repository", "repository_id", "schema", "scope", "scope_sha256",
    "subject_sha256",
}
ADC_SCOPE_FIELDS = {
    "adc_sha256", "append_execution_binding", "excluded", "issue_number", "phase_rebaseline",
    "pr_head_sha40", "pr_number", "predecessor_adc_comment_id", "predecessor_adc_sha256",
    "publish_adc_as_approved", "repository", "repository_id",
}
ADC_REBASELINE_SCOPE = {
    "from": "phase:user-review", "max_label_puts": 1,
    "requires_all_req_f06_015_preconditions": True,
    "separate_plan_approval": False, "to": "phase:requirements",
}


class ChatDecisionError(ValueError):
    """Invalid, stale, duplicated, or mismatched operator-reported chat evidence."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ChatDecisionError("chat decision payload is not canonical JSON data") from exc


def _parse_body(body: Any, schema: str) -> dict[str, Any]:
    marker = f"<!-- {schema}\n"
    if not isinstance(body, str) or not body.startswith(marker) or not body.endswith("\n-->"):
        raise ChatDecisionError("chat decision comment marker/body is invalid")
    encoded = body[len(marker):-len("\n-->")]
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise ChatDecisionError("chat decision body JSON is invalid") from exc
    if not isinstance(value, dict) or _canonical(value).decode("utf-8") != encoded:
        raise ChatDecisionError("chat decision body is not exact canonical JSON")
    return value


def _validate_question_item(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise ChatDecisionError("chat question item ID is invalid")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ChatDecisionError("chat question item ID is not the serialized UI item ID") from exc
    if (not isinstance(decoded, list) or len(decoded) != 3
            or decoded[0] != "request_user_input_async"
            or not isinstance(decoded[1], str) or not decoded[1]
            or type(decoded[2]) is not int or decoded[2] < 0):
        raise ChatDecisionError("chat question item ID does not identify one selection UI request")
    return value


def _validate_base_payload(payload: Any, schema: str, fields: set[str]) -> dict[str, Any]:
    if (not isinstance(payload, dict) or set(payload) != fields
            or payload.get("schema") != schema):
        raise ChatDecisionError("chat decision has unknown or missing fields")
    if (payload.get("answer") != "承認する"
            or payload.get("evidence_channel") != "operator_reported_chat"
            or payload.get("repository") != REPOSITORY
            or payload.get("repository_id") != REPOSITORY_ID
            or payload.get("issue_number") != ISSUE_NUMBER or payload.get("issue_id") != ISSUE_ID
            or payload.get("pr_number") != PR_NUMBER):
        raise ChatDecisionError("chat decision is not an affirmative record for Issue #46 / PR #67")
    for field in ("subject_sha256", "scope_sha256"):
        if not isinstance(payload.get(field), str) or not SHA256.fullmatch(payload[field]):
            raise ChatDecisionError(f"chat decision {field} is invalid")
    scope = payload.get("scope")
    if not isinstance(scope, dict) or hashlib.sha256(_canonical(scope)).hexdigest() != payload["scope_sha256"]:
        raise ChatDecisionError("chat decision scope digest does not match its exact scope")
    _validate_question_item(payload.get("question_item_id"))
    timestamp = payload.get("recorded_at")
    if not isinstance(timestamp, str):
        raise ChatDecisionError("chat decision recorded_at is invalid")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ChatDecisionError("chat decision recorded_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ChatDecisionError("chat decision recorded_at must include a timezone")
    if (parsed.utcoffset().total_seconds() != 0 or parsed.microsecond
            or not timestamp.endswith("Z") or parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != timestamp):
        raise ChatDecisionError("chat decision recorded_at must be canonical UTC seconds")
    recorder = payload.get("github_recorder")
    if (not isinstance(recorder, dict) or set(recorder) != {"login", "user_id"}
            or type(recorder.get("user_id")) is not int or recorder["user_id"] < 1
            or not isinstance(recorder.get("login"), str) or not recorder["login"]):
        raise ChatDecisionError("chat decision GitHub recorder metadata is invalid")
    return payload


def _validate_v1(payload: Any, expected_subject_sha256: str | None = None) -> dict[str, Any]:
    value = _validate_base_payload(payload, SCHEMA_V1, V1_FIELDS)
    scope = value["scope"]
    phase = scope.get("phase_rebaseline") if isinstance(scope, dict) else None
    if (set(scope) != ADC_SCOPE_FIELDS or value["subject_sha256"] != scope.get("adc_sha256")
            or scope.get("publish_adc_as_approved") is not True
            or scope.get("append_execution_binding") is not True
            or phase != ADC_REBASELINE_SCOPE
            or scope.get("repository") != REPOSITORY or scope.get("repository_id") != REPOSITORY_ID
            or scope.get("issue_number") != ISSUE_NUMBER or scope.get("pr_number") != PR_NUMBER
            or scope.get("predecessor_adc_comment_id") != 6399289386
            or scope.get("predecessor_adc_sha256") != "8465cfa151186b3a59a015f9f0c6f674f9e7bedce587747b72e080197e480ab3"
            or scope.get("pr_head_sha40") != value.get("pr_head_sha40")
            or scope.get("excluded") != ["USER_REVIEW", "PR_MERGE", "ISSUE_CLOSE"]):
        raise ChatDecisionError("chat decision does not carry the exact approved ADC/rebaseline scope")
    if (expected_subject_sha256 is not None
            and value["subject_sha256"] != expected_subject_sha256):
        raise ChatDecisionError("chat decision is bound to a different ADC SHA")
    if type(value.get("pr_head_sha40")) is not str or not re.fullmatch(r"[0-9a-f]{40}", value["pr_head_sha40"]):
        raise ChatDecisionError("chat decision PR HEAD is invalid")
    return value


def _validate_v2(payload: Any, *, operation: str | None = None,
                 subject_sha256: str | None = None, scope_sha256: str | None = None) -> dict[str, Any]:
    value = _validate_base_payload(payload, SCHEMA_V2, V2_FIELDS)
    if value.get("operation") not in OPERATIONS:
        raise ChatDecisionError("chat decision operation is unknown")
    predecessor = value.get("predecessor_decision_comment_id")
    if type(predecessor) is not int or predecessor < 1:
        raise ChatDecisionError("chat decision predecessor comment ID is invalid")
    if operation is not None and value["operation"] != operation:
        raise ChatDecisionError("chat decision is for a different operation")
    if subject_sha256 is not None and value["subject_sha256"] != subject_sha256:
        raise ChatDecisionError("chat decision is for a different exact subject")
    if scope_sha256 is not None and value["scope_sha256"] != scope_sha256:
        raise ChatDecisionError("chat decision has a different exact scope")
    return value


def _check_comment_location(github: GitHub, row: Any, comment_id: int,
                            payload: dict[str, Any]) -> dict[str, Any]:
    expected_issue = f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}"
    expected_comment = f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}"
    expected_html = f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}"
    actor = row.get("user") if isinstance(row, dict) else None
    recorder = payload["github_recorder"]
    issue_url = row.get("issue_url") if isinstance(row, dict) else None
    api_url = row.get("url") if isinstance(row, dict) else None
    html_url = row.get("html_url") if isinstance(row, dict) else None
    if (not isinstance(row, dict) or row.get("id") != comment_id
            or not isinstance(issue_url, str) or issue_url.casefold() != expected_issue.casefold()
            or not isinstance(api_url, str) or api_url.casefold() != expected_comment.casefold()
            or not isinstance(html_url, str) or html_url.casefold() != expected_html.casefold()
            or row.get("created_at") != row.get("updated_at")
            or not isinstance(actor, dict) or actor.get("type") != "User"
            or actor.get("id") != recorder["user_id"]
            or actor.get("login", "").casefold() != recorder["login"].casefold()):
        raise ChatDecisionError("chat decision Issue/comment/recorder identity or immutable readback is invalid")
    return row


@dataclass(frozen=True)
class OperatorReportedChatDecision:
    comment_id: int
    schema: str
    payload: dict[str, Any]
    body: str
    body_sha256: str

    @property
    def scope_sha256(self) -> str:
        return self.payload["scope_sha256"]

    @property
    def subject_sha256(self) -> str:
        return self.payload["subject_sha256"]

    @property
    def operation(self) -> str | None:
        return self.payload.get("operation")


def _read_direct_list_direct(github: GitHub, comment_id: int, expected_body: str,
                             payload: dict[str, Any]) -> dict[str, Any]:
    try:
        first = github.issue_comment(ISSUE_NUMBER, comment_id)
        listed = [item for item in github.issue_comments(ISSUE_NUMBER) if item.get("id") == comment_id]
        second = github.issue_comment(ISSUE_NUMBER, comment_id)
    except GitHubError as exc:
        raise ChatDecisionError("chat decision direct/list/direct readback failed") from exc
    if len(listed) != 1:
        raise ChatDecisionError("chat decision is missing or duplicated in the complete Issue comment list")
    for row in (first, listed[0], second):
        if row.get("body") != expected_body:
            raise ChatDecisionError("chat decision body changed during direct/list/direct readback")
        _check_comment_location(github, row, comment_id, payload)
    return second


def _validate_decision_history(github: GitHub, comment_id: int, schema: str,
                               payload: dict[str, Any]) -> None:
    """Require a unique operation record and a valid append-only predecessor reference."""
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ChatDecisionError("chat decision history could not be read completely") from exc
    decisions: list[tuple[int, str, dict[str, Any]]] = []
    seen_ids: set[int] = set()
    seen_subjects: set[tuple[str, str]] = set()
    for row in comments:
        body = row.get("body") if isinstance(row, dict) else None
        if not isinstance(body, str) or not (body.startswith(V1_MARKER) or body.startswith(V2_MARKER)):
            continue
        row_id = row.get("id")
        if type(row_id) is not int or row_id < 1 or row_id in seen_ids:
            raise ChatDecisionError("chat decision history contains a missing or duplicate comment ID")
        seen_ids.add(row_id)
        if body.startswith(V1_MARKER):
            row_schema = SCHEMA_V1
            row_payload = _validate_v1(_parse_body(body, row_schema))
            operation = "ADC_SUPERSEDE"
        else:
            row_schema = SCHEMA_V2
            row_payload = _validate_v2(_parse_body(body, row_schema))
            operation = row_payload["operation"]
        key = (operation, row_payload["subject_sha256"])
        if key in seen_subjects:
            raise ChatDecisionError("chat decision history has duplicate records for one operation/subject")
        seen_subjects.add(key)
        decisions.append((row_id, row_schema, row_payload))
    if not any(row_id == comment_id and row_schema == schema and row_payload == payload
               for row_id, row_schema, row_payload in decisions):
        raise ChatDecisionError("chat decision is missing from the complete Issue history")
    decisions.sort(key=lambda item: item[0])
    for index, (row_id, row_schema, row_payload) in enumerate(decisions):
        if row_schema != SCHEMA_V2:
            continue
        if index == 0 or row_payload["predecessor_decision_comment_id"] != decisions[index - 1][0]:
            raise ChatDecisionError("chat decision history has a broken or skipped predecessor link")
    if schema == SCHEMA_V1:
        if comment_id <= payload["scope"]["predecessor_adc_comment_id"]:
            raise ChatDecisionError("bootstrap ADC chat decision predates its exact predecessor ADC")
        return
    predecessor = payload["predecessor_decision_comment_id"]
    earlier = [row_id for row_id, _schema, _payload in decisions if row_id < comment_id]
    if not earlier or max(earlier) != predecessor or predecessor >= comment_id:
        raise ChatDecisionError("chat decision predecessor is not the immediately preceding decision record")


def read_chat_decision(github: GitHub, comment_id: int, *, operation: str | None = None,
                       subject_sha256: str | None = None, scope_sha256: str | None = None,
                       allow_adc_v1: bool = False) -> OperatorReportedChatDecision:
    if type(comment_id) is not int or comment_id < 1:
        raise ChatDecisionError("chat decision comment ID must be positive")
    try:
        row = github.issue_comment(ISSUE_NUMBER, comment_id)
    except GitHubError as exc:
        raise ChatDecisionError("chat decision comment could not be read") from exc
    body = row.get("body") if isinstance(row, dict) else None
    schema = SCHEMA_V1 if isinstance(body, str) and body.startswith(V1_MARKER) else SCHEMA_V2
    payload = _parse_body(body, schema)
    if schema == SCHEMA_V1:
        if not allow_adc_v1:
            raise ChatDecisionError("bootstrap ADC chat decision schema is not valid for this operation")
        payload = _validate_v1(payload, subject_sha256)
    else:
        payload = _validate_v2(payload, operation=operation, subject_sha256=subject_sha256,
                               scope_sha256=scope_sha256)
    _read_direct_list_direct(github, comment_id, body, payload)
    _validate_decision_history(github, comment_id, schema, payload)
    if schema == SCHEMA_V1 and (operation not in {None, "ADC_SUPERSEDE"}
                                or scope_sha256 not in {None, payload["scope_sha256"]}):
        raise ChatDecisionError("bootstrap ADC chat decision is not valid for the requested operation/scope")
    return OperatorReportedChatDecision(comment_id, schema, payload, body,
                                        hashlib.sha256(body.encode("utf-8")).hexdigest())


def find_adc_rebaseline_decision(github: GitHub, subject_sha256: str) -> OperatorReportedChatDecision:
    if not isinstance(subject_sha256, str) or not SHA256.fullmatch(subject_sha256):
        raise ChatDecisionError("ADC subject SHA-256 is invalid")
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ChatDecisionError("chat decision history could not be read") from exc
    matches: list[dict[str, Any]] = []
    for row in comments:
        body = row.get("body") if isinstance(row, dict) else None
        if not isinstance(body, str) or not body.startswith(V1_MARKER):
            continue
        payload = _validate_v1(_parse_body(body, SCHEMA_V1))
        if payload["subject_sha256"] == subject_sha256:
            matches.append(row)
    if len(matches) != 1:
        raise ChatDecisionError("exact ADC/rebaseline chat decision is missing, duplicated, or conflicting")
    comment_id = matches[0].get("id")
    if type(comment_id) is not int or comment_id < 1:
        raise ChatDecisionError("ADC/rebaseline chat decision has an invalid Comment ID")
    return read_chat_decision(github, comment_id, operation="ADC_SUPERSEDE",
                              subject_sha256=subject_sha256, allow_adc_v1=True)


def _latest_decision_id(github: GitHub) -> int | None:
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ChatDecisionError("chat decision history could not be read before append") from exc
    decisions: list[tuple[int, str, dict[str, Any]]] = []
    for row in comments:
        body = row.get("body") if isinstance(row, dict) else None
        comment_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(body, str) or not (body.startswith(V1_MARKER) or body.startswith(V2_MARKER)):
            continue
        if type(comment_id) is not int or comment_id < 1:
            raise ChatDecisionError("chat decision history contains an invalid Comment ID")
        if body.startswith(V1_MARKER):
            schema = SCHEMA_V1
            payload = _validate_v1(_parse_body(body, schema))
        else:
            schema = SCHEMA_V2
            payload = _validate_v2(_parse_body(body, schema))
        decisions.append((comment_id, schema, payload))
    if not decisions:
        return None
    decisions.sort(key=lambda item: item[0])
    latest_id, latest_schema, latest_payload = decisions[-1]
    read_chat_decision(
        github, latest_id,
        operation="ADC_SUPERSEDE" if latest_schema == SCHEMA_V1 else latest_payload["operation"],
        subject_sha256=latest_payload["subject_sha256"],
        scope_sha256=latest_payload["scope_sha256"], allow_adc_v1=latest_schema == SCHEMA_V1,
    )
    return latest_id


def record_chat_decision(github: GitHub, *, operation: str, subject_sha256: str,
                         scope: dict[str, Any], question_item_id: str, answer: str,
                         pr_number: int = PR_NUMBER) -> OperatorReportedChatDecision | None:
    """Append a V2 technical record after the host orchestrator receives a direct chat answer."""
    if answer != "承認する":
        return None
    if operation not in OPERATIONS or not isinstance(subject_sha256, str) or not SHA256.fullmatch(subject_sha256):
        raise ChatDecisionError("chat decision operation or exact subject is invalid")
    if not isinstance(scope, dict) or not scope or pr_number != PR_NUMBER:
        raise ChatDecisionError("chat decision scope or PR identity is invalid")
    _validate_question_item(question_item_id)
    try:
        issue = github.issue(ISSUE_NUMBER)
        repo = github.repository_metadata()
        actor = github.authenticated_user()
    except GitHubError as exc:
        raise ChatDecisionError("chat decision repository/Issue/recorder readback failed") from exc
    if (issue.get("id") != ISSUE_ID or issue.get("state") != "open"
            or repo.get("id") != REPOSITORY_ID):
        raise ChatDecisionError("chat decision Issue/repository identity changed")
    scope_sha256 = hashlib.sha256(_canonical(scope)).hexdigest()
    existing: list[dict[str, Any]] = []
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ChatDecisionError("chat decision history could not be read before append") from exc
    for row in comments:
        body = row.get("body") if isinstance(row, dict) else None
        if not isinstance(body, str) or not body.startswith(V2_MARKER):
            continue
        payload = _validate_v2(_parse_body(body, SCHEMA_V2))
        if payload["operation"] == operation and payload["subject_sha256"] == subject_sha256:
            existing.append(row)
    if existing:
        if (len(existing) != 1 or existing[0].get("body") is None):
            raise ChatDecisionError("chat decision already has duplicate or conflicting records")
        payload = _parse_body(existing[0]["body"], SCHEMA_V2)
        if payload.get("scope_sha256") != scope_sha256 or payload.get("question_item_id") != question_item_id:
            raise ChatDecisionError("a different chat approval already exists for this exact operation/subject")
        return read_chat_decision(github, existing[0]["id"], operation=operation,
                                  subject_sha256=subject_sha256, scope_sha256=scope_sha256)
    predecessor_id = _latest_decision_id(github)
    if predecessor_id is None:
        raise ChatDecisionError("chat decision predecessor history is missing")
    payload = {
        "answer": "承認する", "evidence_channel": "operator_reported_chat",
        "github_recorder": {"login": actor["login"], "user_id": actor["id"]},
        "issue_id": ISSUE_ID, "issue_number": ISSUE_NUMBER, "operation": operation,
        "predecessor_decision_comment_id": predecessor_id, "pr_number": PR_NUMBER,
        "question_item_id": question_item_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "schema": SCHEMA_V2, "scope": scope, "scope_sha256": scope_sha256,
        "subject_sha256": subject_sha256,
    }
    body = f"<!-- {SCHEMA_V2}\n{_canonical(payload).decode('utf-8')}\n-->"
    try:
        created = github.create_issue_comment(ISSUE_NUMBER, body)
    except GitHubError as exc:
        try:
            recovered = [row for row in github.issue_comments(ISSUE_NUMBER)
                         if isinstance(row.get("body"), str) and row["body"] == body]
        except GitHubError as read_exc:
            raise ChatDecisionError("chat decision append is ambiguous; read-only recovery failed") from read_exc
        if len(recovered) != 1:
            raise ChatDecisionError("chat decision append is ambiguous; refusing a blind retry") from exc
        created = recovered[0]
    comment_id = created.get("id") if isinstance(created, dict) else None
    if type(comment_id) is not int or comment_id <= predecessor_id:
        raise ChatDecisionError("chat decision append has an invalid or out-of-order Comment ID")
    return read_chat_decision(github, comment_id, operation=operation,
                              subject_sha256=subject_sha256, scope_sha256=scope_sha256)
