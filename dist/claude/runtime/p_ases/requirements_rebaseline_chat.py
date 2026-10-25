"""Forward-only chat-authorized Requirements Rebaseline V2 for Issue #46.

The approved successor ADC grants one exact rebaseline. Its read-only V2 plan
checks the live subject; there is no second plan-approval step. Legacy V1
approval/Intent/Applied records remain readable by the predecessor module and
are never reinterpreted as chat decisions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .chat_decisions import (
    ChatDecisionError, OperatorReportedChatDecision, find_adc_rebaseline_decision,
    read_chat_decision,
)
from .github import GitHub, GitHubError
from .legacy_adoption import _record_payload
from .path_safety import path_has_symlink
from .phases import IssueKind, Phase, PhaseError, PhaseState, advance
from .requirements_rebaseline import (
    RequirementsRebaselineError,
    _append_record,
    _canonical_time,
    _current_snapshot,
    _digest,
    _expected_after_phase as _expected_after_phase_legacy,
    _history as _legacy_history,
    _issue_labels,
    _positive,
    _read_comment_direct_list_direct,
    _validate_snapshot,
)


PLAN_SCHEMA = "PASES_REQUIREMENTS_REBASELINE_PLAN_V2"
INTENT_SCHEMA = "PASES_REQUIREMENTS_REBASELINE_INTENT_V2"
APPLIED_SCHEMA = "PASES_REQUIREMENTS_REBASELINE_APPLIED_V2"
PLAN_FIELDS = {"chat_decision", "generated_at", "plan_sha256", "schema", "snapshot"}
CHAT_DECISION_FIELDS = {"comment_id", "body_sha256", "scope_sha256"}
INTENT_FIELDS = {"chat_decision_comment_id", "plan", "plan_sha256", "record_sha256", "schema"}
APPLIED_FIELDS = {
    "chat_decision_comment_id", "intent_comment_id", "intent_sha256", "plan_sha256",
    "record_sha256", "schema",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _body(schema: str, payload: dict[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(payload).decode('utf-8')}\n-->"


@dataclass(frozen=True)
class ChatRequirementsRebaselinePlan:
    value: dict[str, Any]

    def validate(self) -> "ChatRequirementsRebaselinePlan":
        value = self.value
        if not isinstance(value, dict) or set(value) != PLAN_FIELDS or value.get("schema") != PLAN_SCHEMA:
            raise RequirementsRebaselineError("chat-authorized Requirements Rebaseline plan has unknown or missing fields")
        _canonical_time(value.get("generated_at"), "plan generated")
        digest = value.get("plan_sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise RequirementsRebaselineError("chat-authorized plan digest is invalid")
        unsigned = {key: item for key, item in value.items() if key != "plan_sha256"}
        if _digest(unsigned) != digest:
            raise RequirementsRebaselineError("chat-authorized plan digest does not match its content")
        _validate_snapshot(value.get("snapshot"))
        decision = value.get("chat_decision")
        if not isinstance(decision, dict) or set(decision) != CHAT_DECISION_FIELDS:
            raise RequirementsRebaselineError("plan chat decision reference is malformed")
        _positive(decision.get("comment_id"), "chat decision comment ID")
        for field in ("body_sha256", "scope_sha256"):
            if not isinstance(decision.get(field), str) or not SHA256_RE.fullmatch(decision[field]):
                raise RequirementsRebaselineError(f"plan chat decision {field} is invalid")
        if value["snapshot"].get("issue_number") != 46:
            raise RequirementsRebaselineError("chat-authorized plan is outside Issue #46")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        return self.value["plan_sha256"]

    @classmethod
    def from_payload(cls, value: Any) -> "ChatRequirementsRebaselinePlan":
        return cls(value).validate()


def read_plan(path: Path) -> ChatRequirementsRebaselinePlan:
    location = Path(path)
    if path_has_symlink(location) or not location.is_file():
        raise RequirementsRebaselineError("chat-authorized plan must be a regular non-symlink file")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RequirementsRebaselineError("chat-authorized plan is unreadable") from exc
    if _canonical(value) + b"\n" != raw:
        raise RequirementsRebaselineError("chat-authorized plan is not canonical JSON with one trailing newline")
    return ChatRequirementsRebaselinePlan.from_payload(value)


def write_plan(path: Path, plan: ChatRequirementsRebaselinePlan) -> None:
    plan.validate()
    target = Path(path)
    if path_has_symlink(target) or target.exists():
        raise RequirementsRebaselineError("chat-authorized plan output already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical(plan.value) + b"\n")


def _find_chat_history(github: GitHub) -> dict[str, Any]:
    try:
        comments = github.issue_comments(46)
    except GitHubError as exc:
        raise RequirementsRebaselineError("chat Requirements Rebaseline history could not be read") from exc
    rows: dict[str, list[dict[str, Any]]] = {"intent": [], "applied": []}
    markers = {"intent": f"<!-- {INTENT_SCHEMA}\n", "applied": f"<!-- {APPLIED_SCHEMA}\n"}
    for row in comments:
        body = row.get("body") if isinstance(row, dict) else None
        if not isinstance(body, str):
            continue
        for name, marker in markers.items():
            if body.startswith(marker):
                rows[name].append(row)
    if any(len(rows[name]) > 1 for name in rows):
        raise RequirementsRebaselineError("chat Requirements Rebaseline history is duplicated")
    if rows["applied"] and not rows["intent"]:
        raise RequirementsRebaselineError("chat Rebaseline Applied exists without its Intent")
    intent_id = applied_id = None
    intent_payload = applied_payload = None
    if rows["intent"]:
        row = rows["intent"][0]
        intent_id = _positive(row.get("id"), "chat Rebaseline Intent ID")
        intent_payload = _record_payload(row.get("body"), INTENT_SCHEMA)
        if (set(intent_payload) != INTENT_FIELDS or intent_payload.get("schema") != INTENT_SCHEMA
                or intent_payload.get("record_sha256") != _digest({
                    key: val for key, val in intent_payload.items() if key != "record_sha256"})):
            raise RequirementsRebaselineError("chat Rebaseline Intent fields/digest are invalid")
        plan = ChatRequirementsRebaselinePlan.from_payload(intent_payload.get("plan"))
        decision_id = _positive(intent_payload.get("chat_decision_comment_id"), "chat decision comment ID")
        if (decision_id != plan.value["chat_decision"]["comment_id"]
                or intent_payload.get("plan_sha256") != plan.sha256 or intent_id <= decision_id):
            raise RequirementsRebaselineError("chat Rebaseline Intent is not linked to its exact ADC decision/plan")
        _read_comment_direct_list_direct(github, 46, intent_id, expected_body=_body(INTENT_SCHEMA, intent_payload))
    if rows["applied"]:
        row = rows["applied"][0]
        applied_id = _positive(row.get("id"), "chat Rebaseline Applied ID")
        applied_payload = _record_payload(row.get("body"), APPLIED_SCHEMA)
        if (set(applied_payload) != APPLIED_FIELDS or applied_payload.get("schema") != APPLIED_SCHEMA
                or applied_payload.get("record_sha256") != _digest({
                    key: val for key, val in applied_payload.items() if key != "record_sha256"})
                or applied_payload.get("intent_comment_id") != intent_id
                or applied_payload.get("chat_decision_comment_id") != intent_payload["chat_decision_comment_id"]
                or applied_payload.get("plan_sha256") != intent_payload["plan_sha256"]
                or applied_payload.get("intent_sha256") != intent_payload["record_sha256"]
                or applied_id <= intent_id):
            raise RequirementsRebaselineError("chat Rebaseline Applied is not linked to its exact Intent")
        _read_comment_direct_list_direct(github, 46, applied_id, expected_body=_body(APPLIED_SCHEMA, applied_payload))
    return {"applied_id": applied_id, "applied_payload": applied_payload,
            "intent_id": intent_id, "intent_payload": intent_payload}


def _legacy_v1_must_be_empty(github: GitHub) -> None:
    old = _legacy_history(github)
    if any(old[name] is not None for name in ("approval_id", "intent_id", "applied_id")):
        raise RequirementsRebaselineError(
            "legacy Requirements Rebaseline V1 history exists; V1 records cannot be reinterpreted as chat approval"
        )


def _verify_adc_chat_decision(github: GitHub, plan: ChatRequirementsRebaselinePlan) -> OperatorReportedChatDecision:
    reference = plan.value["chat_decision"]
    try:
        decision = read_chat_decision(
            github, reference["comment_id"], operation="ADC_SUPERSEDE",
            subject_sha256=plan.value["snapshot"]["adc_sha256"],
            scope_sha256=reference["scope_sha256"], allow_adc_v1=True,
        )
    except ChatDecisionError as exc:
        raise RequirementsRebaselineError(f"approved ADC chat decision is invalid or stale: {exc}") from exc
    if decision.body_sha256 != reference["body_sha256"]:
        raise RequirementsRebaselineError("approved ADC chat decision body changed after planning")
    return decision


def build_plan(github: GitHub, root: Path, issue_number: int) -> ChatRequirementsRebaselinePlan:
    if issue_number != 46 or github.repo.casefold() != "puchinya/ai-agent-workflow":
        raise RequirementsRebaselineError("Requirements Rebaseline is limited to puchinya/ai-agent-workflow Issue #46")
    _legacy_v1_must_be_empty(github)
    history = _find_chat_history(github)
    if history["intent_id"] is not None or history["applied_id"] is not None:
        raise RequirementsRebaselineError("chat Requirements Rebaseline history already exists; refusing a second plan")
    snapshot = _current_snapshot(github, root, expected_phase=Phase.USER_REVIEW)
    try:
        decision = find_adc_rebaseline_decision(github, snapshot["adc_sha256"])
    except ChatDecisionError as exc:
        raise RequirementsRebaselineError(f"the approved ADC does not carry a valid chat rebaseline grant: {exc}") from exc
    decision_ref = {"comment_id": decision.comment_id, "body_sha256": decision.body_sha256,
                    "scope_sha256": decision.scope_sha256}
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    unsigned = {"chat_decision": decision_ref, "generated_at": generated_at,
                "schema": PLAN_SCHEMA, "snapshot": snapshot}
    return ChatRequirementsRebaselinePlan.from_payload({**unsigned, "plan_sha256": _digest(unsigned)})


def apply_plan(github: GitHub, root: Path, plan: ChatRequirementsRebaselinePlan) -> dict[str, Any]:
    """Apply the sole Requirements Rebaseline authorized by the current approved ADC."""
    plan.validate()
    if github.repo.casefold() != "puchinya/ai-agent-workflow":
        raise RequirementsRebaselineError("Requirements Rebaseline is limited to the fixed repository")
    _legacy_v1_must_be_empty(github)
    decision = _verify_adc_chat_decision(github, plan)
    history = _find_chat_history(github)
    decision_id = plan.value["chat_decision"]["comment_id"]
    if history["applied_id"] is not None:
        intent = history["intent_payload"]
        if (intent.get("plan_sha256") != plan.sha256
                or intent.get("chat_decision_comment_id") != decision_id):
            raise RequirementsRebaselineError("existing Applied belongs to another plan or ADC chat decision")
        return {"status": "NOOP", "intent_comment_id": history["intent_id"],
                "applied_comment_id": history["applied_id"], "plan_sha256": plan.sha256,
                "chat_decision_comment_id": decision_id, "label_write": "ALREADY_APPLIED"}
    if history["intent_id"] is not None:
        intent = history["intent_payload"]
        if (intent.get("plan_sha256") != plan.sha256
                or intent.get("chat_decision_comment_id") != decision_id):
            raise RequirementsRebaselineError("existing incomplete Intent belongs to another plan/decision")
        current = _current_snapshot(github, root, expected_phase=Phase.REQUIREMENTS)
        if current != _expected_after_phase_legacy(plan.value["snapshot"]):
            raise RequirementsRebaselineError("existing Intent has no Applied; target labels are not present")
        applied_payload = {
            "chat_decision_comment_id": decision_id,
            "intent_comment_id": history["intent_id"],
            "intent_sha256": intent["record_sha256"],
            "plan_sha256": plan.sha256,
            "schema": APPLIED_SCHEMA,
        }
        applied_payload["record_sha256"] = _digest(applied_payload)
        applied_id, _ = _append_record(github, APPLIED_SCHEMA, applied_payload)
        complete = _find_chat_history(github)
        if complete["applied_id"] != applied_id or complete["applied_payload"] != applied_payload:
            raise RequirementsRebaselineError("read-only Applied recovery failed direct/list/direct verification")
        return {"status": "APPLIED", "intent_comment_id": history["intent_id"],
                "applied_comment_id": applied_id, "plan_sha256": plan.sha256,
                "chat_decision_comment_id": decision_id, "label_write": "RECOVERED_BY_READBACK"}

    current = _current_snapshot(github, root, expected_phase=Phase.USER_REVIEW)
    if current != plan.value["snapshot"]:
        raise RequirementsRebaselineError("plan is stale for the current ADC, Binding, PR, HEAD, labels, or reset history")
    decision = _verify_adc_chat_decision(github, plan)
    intent_payload = {
        "chat_decision_comment_id": decision_id,
        "plan": plan.value,
        "plan_sha256": plan.sha256,
        "schema": INTENT_SCHEMA,
    }
    intent_payload["record_sha256"] = _digest(intent_payload)
    intent_id, _ = _append_record(github, INTENT_SCHEMA, intent_payload)
    # After the durable Intent, only exact readback can recover. Never issue a second label PUT.
    _verify_adc_chat_decision(github, plan)
    latest = _find_chat_history(github)
    if (latest["intent_id"] != intent_id or latest["intent_payload"] != intent_payload
            or latest["applied_id"] is not None):
        raise RequirementsRebaselineError("Intent changed before the one-time phase label write")
    current = _current_snapshot(github, root, expected_phase=Phase.USER_REVIEW)
    if current != plan.value["snapshot"]:
        raise RequirementsRebaselineError("Issue/ADC/Binding/PR/HEAD changed after Intent; no phase label was written")
    issue = github.issue(46)
    labels, kind, phase, attention = _issue_labels(issue)
    try:
        next_state = advance(PhaseState(46, kind, phase), Phase.REQUIREMENTS, new_requirements=True)
    except PhaseError as exc:
        raise RequirementsRebaselineError(f"phase validator rejected the ADC-authorized transition: {exc}") from exc
    if (issue.get("id") != 5846549384 or labels != plan.value["snapshot"]["issue_labels"]
            or next_state.phase is not Phase.REQUIREMENTS or attention):
        raise RequirementsRebaselineError("Issue changed after Intent; no phase label was written")
    write_error: GitHubError | None = None
    try:
        github.replace_issue_labels(46, plan.value["snapshot"]["target_labels"])
    except GitHubError as exc:
        write_error = exc
    final_issue = github.issue(46)
    final_labels, final_kind, final_phase, final_attention = _issue_labels(final_issue)
    expected = _expected_after_phase_legacy(plan.value["snapshot"])
    if (final_issue.get("id") != 5846549384 or final_labels != expected["issue_labels"]
            or final_kind is not IssueKind.SINGLE or final_phase is not Phase.REQUIREMENTS or final_attention):
        detail = "phase label write is unconfirmed; no retry was attempted"
        if write_error is not None:
            detail = f"{detail} ({write_error})"
        raise RequirementsRebaselineError(detail)
    _verify_adc_chat_decision(github, plan)
    after = _current_snapshot(github, root, expected_phase=Phase.REQUIREMENTS)
    if after != expected:
        raise RequirementsRebaselineError("post-write Issue/ADC/Binding/PR/HEAD differs from the authorized target")
    confirmed = _find_chat_history(github)
    if (confirmed["intent_id"] != intent_id or confirmed["intent_payload"] != intent_payload
            or confirmed["applied_id"] is not None):
        raise RequirementsRebaselineError("Intent changed before the Applied append")
    applied_payload = {
        "chat_decision_comment_id": decision_id,
        "intent_comment_id": intent_id,
        "intent_sha256": intent_payload["record_sha256"],
        "plan_sha256": plan.sha256,
        "schema": APPLIED_SCHEMA,
    }
    applied_payload["record_sha256"] = _digest(applied_payload)
    applied_id, _ = _append_record(github, APPLIED_SCHEMA, applied_payload)
    complete = _find_chat_history(github)
    if (complete["intent_id"] != intent_id or complete["intent_payload"] != intent_payload
            or complete["applied_id"] != applied_id or complete["applied_payload"] != applied_payload):
        raise RequirementsRebaselineError("chat Rebaseline Intent/Applied failed complete readback")
    if _current_snapshot(github, root, expected_phase=Phase.REQUIREMENTS) != expected:
        raise RequirementsRebaselineError("Issue changed after Applied; the operation is not current")
    return {"status": "APPLIED", "intent_comment_id": intent_id,
            "applied_comment_id": applied_id, "plan_sha256": plan.sha256,
            "chat_decision_comment_id": decision_id, "label_write": "VERIFIED"}
