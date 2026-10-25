"""Legacy V1 Issue #46 rebaseline readers and compatibility helpers.

The Issue #46 CLI now uses :mod:`p_ases.requirements_rebaseline_chat` for the
forward V2 path. V1 schemas remain available to validate immutable historical
receipts; new rebaseline plans and writes must use V2's ADC-granted chat route.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution import ExecutionError, binding_digest, read_binding
from .git import GitError, worktree_clean
from .github import GitHub, GitHubError
from .legacy_adoption import (
    LegacyAdoptionError,
    LegacyResetPlan,
    RESET_APPLIED_SCHEMA,
    RESET_INTENT_SCHEMA,
    _body as _legacy_body,
    _exact_issue,
    _issue_labels,
    _read_comment_direct_list_direct,
    _read_reset_state,
    _record_payload,
    _repository_identity,
    _timestamp as _legacy_timestamp,
    verify_owner_approval as verify_legacy_owner_approval,
)
from .phase_evidence import PhaseEvidenceError, verify_ordinary_issue_context
from .phases import IssueKind, Phase, PhaseError, PhaseState, advance
from .path_safety import path_has_symlink
from .work import execution_binding_path


class RequirementsRebaselineError(ValueError):
    """A fail-closed error while planning or applying the one-time recovery."""


PLAN_SCHEMA = "PASES_REQUIREMENTS_REBASELINE_PLAN_V1"
APPROVAL_SCHEMA = "PASES_REQUIREMENTS_REBASELINE_APPROVAL_V1"
INTENT_SCHEMA = "PASES_REQUIREMENTS_REBASELINE_INTENT_V1"
APPLIED_SCHEMA = "PASES_REQUIREMENTS_REBASELINE_APPLIED_V1"
REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
OWNER_ID = 3744776
ISSUE_NUMBER = 46
ISSUE_ID = 5846549384
PR_NUMBER = 67
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
APPROVAL_MARKER = f"<!-- {APPROVAL_SCHEMA}\n"
INTENT_MARKER = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_MARKER = f"<!-- {APPLIED_SCHEMA}\n"

PLAN_FIELDS = {"generated_at", "plan_sha256", "schema", "snapshot"}
SNAPSHOT_FIELDS = {
    "adc_comment_id", "adc_sha256", "binding_sha256", "branch_ref", "head_sha40",
    "issue_created_at", "issue_id", "issue_kind", "issue_labels", "issue_number",
    "owner_id", "pr", "prior_legacy_reset", "repository", "repository_id", "target_labels",
}
PR_FIELDS = {"base_ref", "base_sha40", "head_ref", "head_sha40", "id", "number"}
PRIOR_RESET_FIELDS = {
    "approval_comment_id", "applied_body_sha256", "applied_comment_id",
    "intent_body_sha256", "intent_comment_id", "plan_sha256",
}
APPROVAL_FIELDS = {
    "approved", "issue_id", "issue_number", "plan_sha256", "repository", "repository_id", "schema",
}
INTENT_FIELDS = {"approval_comment_id", "plan", "plan_sha256", "record_sha256", "schema"}
APPLIED_FIELDS = {
    "approval_comment_id", "intent_comment_id", "intent_sha256", "plan_sha256", "record_sha256", "schema",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _body(schema: str, payload: dict[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(payload).decode('utf-8')}\n-->"


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise RequirementsRebaselineError(f"{label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RequirementsRebaselineError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RequirementsRebaselineError(f"{label} timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_time(value: Any, label: str) -> str:
    result = _timestamp(value, label).isoformat(timespec="seconds").replace("+00:00", "Z")
    if value != result:
        raise RequirementsRebaselineError(f"{label} timestamp is not canonical UTC")
    return result


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise RequirementsRebaselineError(f"{label} must be a positive integer")
    return value


def _validate_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_FIELDS:
        raise RequirementsRebaselineError("requirements rebaseline snapshot has unknown or missing fields")
    if (snapshot.get("repository") != REPOSITORY or snapshot.get("repository_id") != REPOSITORY_ID
            or snapshot.get("owner_id") != OWNER_ID or snapshot.get("issue_number") != ISSUE_NUMBER
            or snapshot.get("issue_id") != ISSUE_ID or snapshot.get("issue_kind") != IssueKind.SINGLE.value):
        raise RequirementsRebaselineError("requirements rebaseline is outside the exact Issue #46 identity")
    for field in ("adc_sha256", "binding_sha256"):
        if not isinstance(snapshot.get(field), str) or not SHA256.fullmatch(snapshot[field]):
            raise RequirementsRebaselineError(f"requirements rebaseline {field} is invalid")
    for field in ("adc_comment_id", "issue_number", "issue_id", "owner_id", "repository_id"):
        _positive(snapshot.get(field), f"snapshot {field}")
    if not isinstance(snapshot.get("branch_ref"), str) or not snapshot["branch_ref"]:
        raise RequirementsRebaselineError("requirements rebaseline branch ref is invalid")
    if not isinstance(snapshot.get("head_sha40"), str) or not SHA40.fullmatch(snapshot["head_sha40"]):
        raise RequirementsRebaselineError("requirements rebaseline HEAD is invalid")
    _canonical_time(snapshot.get("issue_created_at"), "Issue creation")
    labels = snapshot.get("issue_labels")
    if (not isinstance(labels, list) or any(not isinstance(item, str) or not item for item in labels)
            or labels != sorted(set(labels))):
        raise RequirementsRebaselineError("requirements rebaseline Issue labels are not canonical")
    try:
        kind = IssueKind(next(item.removeprefix("kind:") for item in labels if item.startswith("kind:")))
        phase = Phase(next(item.removeprefix("phase:") for item in labels if item.startswith("phase:")))
    except (StopIteration, ValueError) as exc:
        raise RequirementsRebaselineError("requirements rebaseline labels do not identify one kind and phase") from exc
    if (sum(item.startswith("kind:") for item in labels) != 1
            or sum(item.startswith("phase:") for item in labels) != 1
            or any(item.startswith("attention:") for item in labels)
            or kind is not IssueKind.SINGLE or phase not in {Phase.USER_REVIEW, Phase.REQUIREMENTS}):
        raise RequirementsRebaselineError("requirements rebaseline phase/label state is invalid")
    target = snapshot.get("target_labels")
    expected_target = sorted([item for item in labels if not item.startswith(("phase:", "attention:"))]
                             + [f"phase:{Phase.REQUIREMENTS.value}"])
    if (not isinstance(target, list) or target != expected_target
            or len(target) != len(set(target))):
        raise RequirementsRebaselineError("requirements rebaseline target labels are invalid")
    pr = snapshot.get("pr")
    if not isinstance(pr, dict) or set(pr) != PR_FIELDS:
        raise RequirementsRebaselineError("requirements rebaseline PR identity is malformed")
    if (pr.get("number") != PR_NUMBER or type(pr.get("id")) is not int or pr["id"] < 1
            or pr.get("base_ref") != "main" or not isinstance(pr.get("base_sha40"), str)
            or not SHA40.fullmatch(pr["base_sha40"]) or pr.get("head_ref") != snapshot["branch_ref"]
            or pr.get("head_sha40") != snapshot["head_sha40"]):
        raise RequirementsRebaselineError("requirements rebaseline PR does not match the exact Issue branch HEAD")
    prior = snapshot.get("prior_legacy_reset")
    if not isinstance(prior, dict) or set(prior) != PRIOR_RESET_FIELDS:
        raise RequirementsRebaselineError("prior Legacy Reset V1 pair snapshot is malformed")
    for field in ("approval_comment_id", "applied_comment_id", "intent_comment_id"):
        _positive(prior.get(field), f"prior Legacy Reset {field}")
    for field in ("applied_body_sha256", "intent_body_sha256", "plan_sha256"):
        if not isinstance(prior.get(field), str) or not SHA256.fullmatch(prior[field]):
            raise RequirementsRebaselineError(f"prior Legacy Reset {field} is invalid")
    if not (prior["approval_comment_id"] < prior["intent_comment_id"] < prior["applied_comment_id"]):
        raise RequirementsRebaselineError("prior Legacy Reset records are not in append-only order")
    return snapshot


def _validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PLAN_FIELDS or value.get("schema") != PLAN_SCHEMA:
        raise RequirementsRebaselineError("requirements rebaseline plan has unknown or missing fields")
    _canonical_time(value.get("generated_at"), "plan generated")
    digest = value.get("plan_sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise RequirementsRebaselineError("requirements rebaseline plan digest is invalid")
    payload = {key: item for key, item in value.items() if key != "plan_sha256"}
    if _digest(payload) != digest:
        raise RequirementsRebaselineError("requirements rebaseline plan digest does not match its content")
    _validate_snapshot(value.get("snapshot"))
    return value


@dataclass(frozen=True)
class RequirementsRebaselinePlan:
    value: dict[str, Any]

    def validate(self) -> "RequirementsRebaselinePlan":
        _validate_plan(self.value)
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        return self.value["plan_sha256"]

    @classmethod
    def from_payload(cls, value: Any) -> "RequirementsRebaselinePlan":
        return cls(value).validate()


def read_plan(path: Path) -> RequirementsRebaselinePlan:
    location = Path(path)
    if path_has_symlink(location, root=location.parent) or not location.is_file():
        raise RequirementsRebaselineError("requirements rebaseline plan must be a regular non-symlink file")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RequirementsRebaselineError("requirements rebaseline plan is unreadable") from exc
    if _canonical(value) + b"\n" != raw:
        raise RequirementsRebaselineError("requirements rebaseline plan is not canonical JSON with one trailing newline")
    return RequirementsRebaselinePlan.from_payload(value)


def write_plan(path: Path, plan: RequirementsRebaselinePlan) -> None:
    plan.validate()
    target = Path(path)
    if path_has_symlink(target, root=target.parent) or target.exists():
        raise RequirementsRebaselineError("requirements rebaseline plan output exists or traverses a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical(plan.value) + b"\n")


def _prior_reset_snapshot(github: GitHub) -> dict[str, Any]:
    try:
        state = _read_reset_state(github, ISSUE_NUMBER)
    except (LegacyAdoptionError, GitHubError) as exc:
        raise RequirementsRebaselineError(f"prior Legacy Reset V1 history is invalid: {exc}") from exc
    if state["intent_comment_id"] is None or state["applied_comment_id"] is None:
        raise RequirementsRebaselineError("a complete previously applied Legacy Reset V1 pair is required")
    plan = state["plan"]
    if not isinstance(plan, LegacyResetPlan):
        raise RequirementsRebaselineError("prior Legacy Reset V1 plan is missing")
    intent_payload = state["intent_payload"]
    applied_payload = state["applied_payload"]
    approval_id = intent_payload.get("approval_comment_id") if isinstance(intent_payload, dict) else None
    if (not isinstance(intent_payload, dict) or not isinstance(applied_payload, dict)
            or intent_payload.get("schema") != RESET_INTENT_SCHEMA
            or applied_payload.get("schema") != RESET_APPLIED_SCHEMA
            or intent_payload.get("plan_sha256") != plan.sha256
            or intent_payload.get("plan") != plan.value
            or intent_payload.get("approval_comment_id") != approval_id
            or applied_payload.get("approval_comment_id") != approval_id
            or applied_payload.get("intent_comment_id") != state["intent_comment_id"]
            or applied_payload.get("plan_sha256") != plan.sha256):
        raise RequirementsRebaselineError("prior Legacy Reset V1 Intent/Applied do not bind the same exact plan")
    try:
        verify_legacy_owner_approval(github, plan, approval_id, operation="RESET_TO_REQUIREMENTS")
        intent = _read_comment_direct_list_direct(
            github, ISSUE_NUMBER, state["intent_comment_id"],
            expected_body=_legacy_body(RESET_INTENT_SCHEMA, state["intent_payload"]),
        )
        applied = _read_comment_direct_list_direct(
            github, ISSUE_NUMBER, state["applied_comment_id"],
            expected_body=_legacy_body(RESET_APPLIED_SCHEMA, state["applied_payload"]),
        )
    except (LegacyAdoptionError, GitHubError) as exc:
        raise RequirementsRebaselineError(f"prior Legacy Reset V1 Owner approval/readback failed: {exc}") from exc
    old = plan.value
    if (old.get("issue_number") != ISSUE_NUMBER or old.get("issue_id") != ISSUE_ID
            or old.get("repository", "").casefold() != REPOSITORY.casefold()
            or old.get("repository_id") != REPOSITORY_ID or old.get("owner_id") != OWNER_ID
            or f"phase:{Phase.REQUIREMENTS.value}" not in old.get("target_labels", [])):
        raise RequirementsRebaselineError("prior Legacy Reset V1 pair is not for this Issue/repository/Owner")
    return {
        "approval_comment_id": approval_id,
        "applied_body_sha256": hashlib.sha256(applied["body"].encode("utf-8")).hexdigest(),
        "applied_comment_id": state["applied_comment_id"],
        "intent_body_sha256": hashlib.sha256(intent["body"].encode("utf-8")).hexdigest(),
        "intent_comment_id": state["intent_comment_id"],
        "plan_sha256": plan.sha256,
    }


def _current_snapshot(github: GitHub, root: Path, *, expected_phase: Phase) -> dict[str, Any]:
    root = Path(root).resolve()
    try:
        issue, verified, kind, branch_ref, local_head_sha = verify_ordinary_issue_context(
            github, root, ISSUE_NUMBER, IssueKind.SINGLE, require_binding=True,
        )
    except (PhaseEvidenceError, GitHubError, OSError, ValueError) as exc:
        raise RequirementsRebaselineError(f"current Issue/ADC/Binding context is invalid: {exc}") from exc
    if github.repo.casefold() != REPOSITORY.casefold():
        raise RequirementsRebaselineError("requirements rebaseline requires the fixed repository and a clean worktree")
    try:
        clean_worktree = worktree_clean(root)
    except GitError as exc:
        raise RequirementsRebaselineError(f"clean worktree status could not be verified: {exc}") from exc
    if not clean_worktree:
        raise RequirementsRebaselineError("requirements rebaseline requires the fixed repository and a clean worktree")
    try:
        labels, actual_kind, phase, attention = _issue_labels(issue)
    except LegacyAdoptionError as exc:
        raise RequirementsRebaselineError(f"Issue labels are invalid: {exc}") from exc
    if (issue.get("id") != ISSUE_ID or kind is not IssueKind.SINGLE or actual_kind is not IssueKind.SINGLE
            or phase is not expected_phase or attention):
        raise RequirementsRebaselineError("Issue #46 must be open kind:single at the exact expected phase with no attention")
    try:
        repository_id, owner_id = _repository_identity(github)
        binding = read_binding(execution_binding_path(root, ISSUE_NUMBER))
        binding_sha = binding_digest(binding)
    except (LegacyAdoptionError, ExecutionError, OSError, ValueError) as exc:
        raise RequirementsRebaselineError(f"repository Owner or ExecutionBinding is invalid: {exc}") from exc
    if (repository_id != REPOSITORY_ID or owner_id != OWNER_ID
            or binding.repository.casefold() != REPOSITORY.casefold()
            or binding.issue_number != ISSUE_NUMBER
            or binding.adc_comment_id != verified.pointer.comment_id
            or binding.adc_sha256 != verified.contract.sha256
            or binding.branch_ref != branch_ref
            or binding.base_ref == branch_ref
            or Path(binding.work_directory).resolve() != root):
        raise RequirementsRebaselineError("repository Owner, approved ADC, or ExecutionBinding identity changed")
    try:
        pull = github.pull_request(PR_NUMBER)
    except GitHubError as exc:
        raise RequirementsRebaselineError(f"PR #67 readback failed: {exc}") from exc
    base, head = pull.get("base"), pull.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_sha = base.get("sha") if isinstance(base, dict) else None
    pr_head_sha = head.get("sha") if isinstance(head, dict) else None
    if (pull.get("number") != PR_NUMBER or type(pull.get("id")) is not int or pull["id"] < 1
            or pull.get("state") != "open" or pull.get("merged") is True
            or pull.get("draft") is not False
            or not isinstance(base, dict) or not isinstance(head, dict)
            or base.get("ref") != "main" or not isinstance(base_sha, str) or not SHA40.fullmatch(base_sha)
            or head.get("ref") != branch_ref or pr_head_sha != local_head_sha
            or not isinstance(base_repo, dict) or base_repo.get("id") != REPOSITORY_ID
            or not isinstance(head_repo, dict) or head_repo.get("id") != REPOSITORY_ID):
        raise RequirementsRebaselineError("PR #67 is not the open, ready PR for the exact bound branch HEAD")
    if binding.base_ref != base["ref"] or binding.base_sha != base_sha:
        raise RequirementsRebaselineError("PR base no longer matches the frozen ExecutionBinding")
    if expected_phase is Phase.USER_REVIEW:
        try:
            transition = advance(
                PhaseState(ISSUE_NUMBER, IssueKind.SINGLE, phase), Phase.REQUIREMENTS, new_requirements=True,
            )
        except PhaseError as exc:
            raise RequirementsRebaselineError(
                f"the existing phase validator rejected the exact transition: {exc}"
            ) from exc
        if transition.phase is not Phase.REQUIREMENTS:
            raise RequirementsRebaselineError("the existing phase validator did not produce requirements")
    prior = _prior_reset_snapshot(github)
    target_labels = sorted([item for item in labels if not item.startswith(("phase:", "attention:"))]
                           + [f"phase:{Phase.REQUIREMENTS.value}"])
    return _validate_snapshot({
        "adc_comment_id": verified.pointer.comment_id,
        "adc_sha256": verified.contract.sha256,
        "binding_sha256": binding_sha,
        "branch_ref": branch_ref,
        "head_sha40": local_head_sha,
        "issue_created_at": _canonical_time(issue.get("created_at"), "Issue creation"),
        "issue_id": issue["id"],
        "issue_kind": kind.value,
        "issue_labels": labels,
        "issue_number": ISSUE_NUMBER,
        "owner_id": owner_id,
        "pr": {
            "base_ref": base["ref"], "base_sha40": base_sha,
            "head_ref": head["ref"], "head_sha40": pr_head_sha,
            "id": pull["id"], "number": PR_NUMBER,
        },
        "prior_legacy_reset": prior,
        "repository": github.repo,
        "repository_id": repository_id,
        "target_labels": target_labels,
    })


def _history(github: GitHub) -> dict[str, Any]:
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise RequirementsRebaselineError(f"Requirements Rebaseline history read failed: {exc}") from exc
    markers = {
        "approval": (APPROVAL_SCHEMA, APPROVAL_MARKER),
        "intent": (INTENT_SCHEMA, INTENT_MARKER),
        "applied": (APPLIED_SCHEMA, APPLIED_MARKER),
    }
    rows: dict[str, list[dict[str, Any]]] = {}
    for name, (_schema, marker) in markers.items():
        rows[name] = [row for row in comments if isinstance(row, dict)
                      and isinstance(row.get("body"), str) and row["body"].startswith(marker)]
        if len(rows[name]) > 1:
            raise RequirementsRebaselineError(f"Requirements Rebaseline {name} history is duplicated")
    if rows["applied"] and not rows["intent"]:
        raise RequirementsRebaselineError("Requirements Rebaseline Applied exists without its Intent")
    intent_payload = applied_payload = None
    intent_id = applied_id = approval_id = None
    if rows["approval"]:
        row = rows["approval"][0]
        approval_id = _positive(row.get("id"), "Owner approval comment ID")
        approval_payload = _record_payload(row.get("body"), APPROVAL_SCHEMA)
        if set(approval_payload) != APPROVAL_FIELDS or approval_payload.get("schema") != APPROVAL_SCHEMA:
            raise RequirementsRebaselineError("Requirements Rebaseline approval fields are invalid")
        if (approval_payload.get("approved") is not True
                or approval_payload.get("issue_number") != ISSUE_NUMBER
                or approval_payload.get("issue_id") != ISSUE_ID
                or approval_payload.get("repository") != REPOSITORY
                or approval_payload.get("repository_id") != REPOSITORY_ID
                or not isinstance(approval_payload.get("plan_sha256"), str)
                or not SHA256.fullmatch(approval_payload["plan_sha256"])):
            raise RequirementsRebaselineError("Requirements Rebaseline approval subject is invalid")
        _read_comment_direct_list_direct(github, ISSUE_NUMBER, approval_id, expected_body=row["body"])
    else:
        approval_payload = None
    if rows["intent"]:
        row = rows["intent"][0]
        intent_id = _positive(row.get("id"), "Requirements Rebaseline Intent ID")
        intent_payload = _record_payload(row.get("body"), INTENT_SCHEMA)
        if (set(intent_payload) != INTENT_FIELDS or intent_payload.get("schema") != INTENT_SCHEMA
                or intent_payload.get("record_sha256") != _digest({
                    key: val for key, val in intent_payload.items() if key != "record_sha256"})):
            raise RequirementsRebaselineError("Requirements Rebaseline Intent fields/digest are invalid")
        plan = RequirementsRebaselinePlan.from_payload(intent_payload["plan"])
        approval_from_intent = _positive(intent_payload.get("approval_comment_id"),
                                         "Requirements Rebaseline approval comment ID")
        if (plan.value["snapshot"]["issue_number"] != ISSUE_NUMBER
                or intent_payload.get("plan_sha256") != plan.sha256
                or intent_id <= approval_from_intent):
            raise RequirementsRebaselineError("Requirements Rebaseline Intent is not bound to its exact plan/approval")
        _read_comment_direct_list_direct(
            github, ISSUE_NUMBER, intent_id, expected_body=_body(INTENT_SCHEMA, intent_payload),
        )
    if rows["applied"]:
        row = rows["applied"][0]
        applied_id = _positive(row.get("id"), "Requirements Rebaseline Applied ID")
        applied_payload = _record_payload(row.get("body"), APPLIED_SCHEMA)
        applied_approval_id = _positive(applied_payload.get("approval_comment_id"),
                                        "Applied approval comment ID")
        applied_intent_id = _positive(applied_payload.get("intent_comment_id"),
                                      "Applied Intent comment ID")
        if (set(applied_payload) != APPLIED_FIELDS or applied_payload.get("schema") != APPLIED_SCHEMA
                or applied_payload.get("record_sha256") != _digest({
                    key: val for key, val in applied_payload.items() if key != "record_sha256"})
                or applied_intent_id != intent_id
                or applied_approval_id != intent_payload["approval_comment_id"]
                or applied_payload.get("plan_sha256") != intent_payload["plan_sha256"]
                or applied_payload.get("intent_sha256") != intent_payload["record_sha256"]
                or applied_id <= intent_id):
            raise RequirementsRebaselineError("Requirements Rebaseline Applied is not linked to its exact Intent")
        _read_comment_direct_list_direct(
            github, ISSUE_NUMBER, applied_id, expected_body=_body(APPLIED_SCHEMA, applied_payload),
        )
    return {"approval_id": approval_id, "approval_payload": approval_payload,
            "applied_id": applied_id, "applied_payload": applied_payload,
            "intent_id": intent_id, "intent_payload": intent_payload}


def build_plan(github: GitHub, root: Path, issue_number: int) -> RequirementsRebaselinePlan:
    if issue_number != ISSUE_NUMBER or github.repo.casefold() != REPOSITORY.casefold():
        raise RequirementsRebaselineError("Requirements Rebaseline is limited to puchinya/ai-agent-workflow Issue #46")
    history = _history(github)
    if any(history[key] is not None for key in ("approval_id", "intent_id", "applied_id")):
        raise RequirementsRebaselineError("Requirements Rebaseline history already exists; refusing a second plan")
    snapshot = _current_snapshot(github, root, expected_phase=Phase.USER_REVIEW)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {"generated_at": generated_at, "schema": PLAN_SCHEMA, "snapshot": snapshot}
    return RequirementsRebaselinePlan.from_payload({**payload, "plan_sha256": _digest(payload)})


def owner_approval_comment(plan: RequirementsRebaselinePlan) -> str:
    plan.validate()
    snapshot = plan.value["snapshot"]
    return _body(APPROVAL_SCHEMA, {
        "approved": True,
        "issue_id": snapshot["issue_id"],
        "issue_number": snapshot["issue_number"],
        "plan_sha256": plan.sha256,
        "repository": snapshot["repository"],
        "repository_id": snapshot["repository_id"],
        "schema": APPROVAL_SCHEMA,
    })


def _verify_owner_approval(github: GitHub, plan: RequirementsRebaselinePlan,
                           comment_id: int) -> dict[str, Any]:
    plan.validate()
    comment_id = _positive(comment_id, "Owner approval comment ID")
    expected = _record_payload(owner_approval_comment(plan), APPROVAL_SCHEMA)
    try:
        repository_id, owner_id = _repository_identity(github)
        comments = github.issue_comments(ISSUE_NUMBER)
    except (LegacyAdoptionError, GitHubError) as exc:
        raise RequirementsRebaselineError(f"Owner approval identity/history read failed: {exc}") from exc
    snapshot = plan.value["snapshot"]
    if (repository_id != snapshot["repository_id"] or owner_id != snapshot["owner_id"]
            or github.repo.casefold() != snapshot["repository"].casefold()):
        raise RequirementsRebaselineError("Owner approval repository identity changed")
    candidates = []
    for row in comments:
        body_value = row.get("body") if isinstance(row, dict) else None
        if not isinstance(body_value, str) or not body_value.startswith(APPROVAL_MARKER):
            continue
        payload = _record_payload(body_value[:-1] if body_value.endswith("\n") else body_value,
                                  APPROVAL_SCHEMA)
        if payload.get("issue_number") != ISSUE_NUMBER:
            raise RequirementsRebaselineError("Requirements Rebaseline approval is attached to another Issue")
        if payload == expected:
            candidates.append(row)
    if len(candidates) != 1 or candidates[0].get("id") != comment_id:
        raise RequirementsRebaselineError("exact Owner approval is missing, duplicated, or has the wrong ID")
    expected_body = owner_approval_comment(plan)
    stored_body = candidates[0].get("body")
    if stored_body not in {expected_body, expected_body + "\n"}:
        raise RequirementsRebaselineError("Owner approval body differs from the exact plan authorization")
    try:
        row = _read_comment_direct_list_direct(github, ISSUE_NUMBER, comment_id, expected_body=stored_body)
    except (LegacyAdoptionError, GitHubError) as exc:
        raise RequirementsRebaselineError(f"Owner approval direct/list/direct readback failed: {exc}") from exc
    actor = row.get("user")
    owner_login = REPOSITORY.split("/", 1)[0]
    if (not isinstance(actor, dict) or actor.get("id") != OWNER_ID or actor.get("type") != "User"
            or not isinstance(actor.get("login"), str) or actor["login"].casefold() != owner_login.casefold()):
        raise RequirementsRebaselineError("approval was not authored by the stable repository Owner User ID")
    if _timestamp(row.get("created_at"), "Owner approval") < _timestamp(
            plan.value["generated_at"], "plan generated"):
        raise RequirementsRebaselineError("Owner approval predates the exact plan")
    return row


def _append_record(github: GitHub, schema: str, payload: dict[str, Any]) -> tuple[int, str]:
    expected = _body(schema, payload)
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise RequirementsRebaselineError(f"{schema} pre-write history read failed: {exc}") from exc
    marker = f"<!-- {schema}\n"
    rows = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
            and row["body"].startswith(marker)]
    if len(rows) > 1 or (rows and rows[0].get("body") != expected):
        raise RequirementsRebaselineError(f"{schema} history is duplicated or conflicts with the exact payload")
    if rows:
        comment_id = _positive(rows[0].get("id"), f"{schema} comment ID")
    else:
        issue = _exact_issue(github, ISSUE_NUMBER)
        if issue.get("state") != "open":
            raise RequirementsRebaselineError(f"{schema} can only be appended to an open Issue")
        try:
            created = github.create_issue_comment(ISSUE_NUMBER, expected)
        except GitHubError as exc:
            try:
                recovered = [row for row in github.issue_comments(ISSUE_NUMBER)
                             if isinstance(row, dict) and row.get("body") == expected]
            except GitHubError as read_exc:
                raise RequirementsRebaselineError(
                    f"{schema} append response and read-only recovery are uncertain"
                ) from read_exc
            if len(recovered) != 1:
                raise RequirementsRebaselineError(f"{schema} append is ambiguous; refusing a blind retry") from exc
            created = recovered[0]
        comment_id = _positive(created.get("id"), f"{schema} comment ID")
    try:
        readback = _read_comment_direct_list_direct(
            github, ISSUE_NUMBER, comment_id, expected_body=expected,
        )
        exact = [row for row in github.issue_comments(ISSUE_NUMBER)
                 if isinstance(row, dict) and row.get("body") == expected]
    except (LegacyAdoptionError, GitHubError) as exc:
        raise RequirementsRebaselineError(f"{schema} direct/list/direct readback failed: {exc}") from exc
    if len(exact) != 1 or exact[0].get("id") != comment_id:
        raise RequirementsRebaselineError(f"{schema} complete history readback is missing or duplicated")
    return comment_id, readback["body"]


def _expected_after_phase(snapshot: dict[str, Any]) -> dict[str, Any]:
    expected = dict(snapshot)
    expected["issue_labels"] = list(snapshot["target_labels"])
    return expected


def apply_plan(github: GitHub, root: Path, plan: RequirementsRebaselinePlan,
               approval_comment_id: int) -> dict[str, Any]:
    """Apply the exact Owner-approved phase change once; recover only by readback."""
    plan.validate()
    if github.repo.casefold() != REPOSITORY.casefold():
        raise RequirementsRebaselineError("Requirements Rebaseline is limited to the fixed repository")
    approval_comment_id = _positive(approval_comment_id, "Owner approval comment ID")
    history = _history(github)
    if history["applied_id"] is not None:
        intent = history["intent_payload"]
        if (intent.get("plan_sha256") != plan.sha256
                or intent.get("approval_comment_id") != approval_comment_id):
            raise RequirementsRebaselineError("existing Applied record belongs to another plan or approval")
        _verify_owner_approval(github, plan, approval_comment_id)
        return {"status": "NOOP", "intent_comment_id": history["intent_id"],
                "applied_comment_id": history["applied_id"], "plan_sha256": plan.sha256,
                "label_write": "ALREADY_APPLIED"}
    if history["intent_id"] is not None:
        intent = history["intent_payload"]
        if (intent.get("plan_sha256") != plan.sha256
                or intent.get("approval_comment_id") != approval_comment_id):
            raise RequirementsRebaselineError("existing incomplete Intent belongs to another plan/approval")
        _verify_owner_approval(github, plan, approval_comment_id)
        snapshot = plan.value["snapshot"]
        current = _current_snapshot(github, root, expected_phase=Phase.REQUIREMENTS)
        if current != _expected_after_phase(snapshot):
            raise RequirementsRebaselineError("existing Intent has no Applied; current Issue is not the exact target")
        applied_payload = {
            "approval_comment_id": approval_comment_id,
            "intent_comment_id": history["intent_id"],
            "intent_sha256": intent["record_sha256"],
            "plan_sha256": plan.sha256,
            "schema": APPLIED_SCHEMA,
        }
        applied_payload["record_sha256"] = _digest(applied_payload)
        applied_id, _ = _append_record(github, APPLIED_SCHEMA, applied_payload)
        complete = _history(github)
        if complete["applied_id"] != applied_id or complete["applied_payload"] != applied_payload:
            raise RequirementsRebaselineError("read-only Applied recovery failed complete direct/list/direct verification")
        return {"status": "APPLIED", "intent_comment_id": history["intent_id"],
                "applied_comment_id": applied_id, "plan_sha256": plan.sha256,
                "label_write": "RECOVERED_BY_READBACK"}
    if history["approval_id"] not in {None, approval_comment_id}:
        raise RequirementsRebaselineError("another Requirements Rebaseline approval is already recorded")
    approval = _verify_owner_approval(github, plan, approval_comment_id)
    current = _current_snapshot(github, root, expected_phase=Phase.USER_REVIEW)
    if current != plan.value["snapshot"]:
        raise RequirementsRebaselineError("plan is stale for the current ADC, Binding, PR, HEAD, labels, or reset history")
    intent_payload = {
        "approval_comment_id": approval_comment_id,
        "plan": plan.value,
        "plan_sha256": plan.sha256,
        "schema": INTENT_SCHEMA,
    }
    intent_payload["record_sha256"] = _digest(intent_payload)
    intent_id, _ = _append_record(github, INTENT_SCHEMA, intent_payload)
    # After Intent, all recovery is exact-subject readback; never issue a second label PUT.
    _verify_owner_approval(github, plan, approval_comment_id)
    latest = _history(github)
    if (latest["intent_id"] != intent_id or latest["intent_payload"] != intent_payload
            or latest["applied_id"] is not None):
        raise RequirementsRebaselineError("Intent history changed before the phase write")
    current = _current_snapshot(github, root, expected_phase=Phase.USER_REVIEW)
    if current != plan.value["snapshot"]:
        raise RequirementsRebaselineError("Issue/ADC/Binding/PR/HEAD changed after Intent; no phase label was written")
    issue = _exact_issue(github, ISSUE_NUMBER)
    labels, kind, phase, attention = _issue_labels(issue)
    next_state = advance(PhaseState(ISSUE_NUMBER, kind, phase), Phase.REQUIREMENTS,
                         new_requirements=True)
    if (issue.get("id") != ISSUE_ID or labels != plan.value["snapshot"]["issue_labels"]
            or next_state.phase is not Phase.REQUIREMENTS or attention):
        raise RequirementsRebaselineError("Issue changed after Intent; no phase label was written")
    write_error: GitHubError | None = None
    try:
        github.replace_issue_labels(ISSUE_NUMBER, plan.value["snapshot"]["target_labels"])
    except GitHubError as exc:
        write_error = exc
    # One direct Issue read only. A failed/ambiguous PUT is never retried.
    final_issue = _exact_issue(github, ISSUE_NUMBER)
    final_labels, final_kind, final_phase, final_attention = _issue_labels(final_issue)
    expected = _expected_after_phase(plan.value["snapshot"])
    if (final_issue.get("id") != ISSUE_ID or final_labels != expected["issue_labels"]
            or final_kind is not IssueKind.SINGLE or final_phase is not Phase.REQUIREMENTS or final_attention):
        detail = "phase label write is unconfirmed; no retry was attempted"
        if write_error is not None:
            detail = f"{detail} ({write_error})"
        raise RequirementsRebaselineError(detail)
    _verify_owner_approval(github, plan, approval_comment_id)
    after = _current_snapshot(github, root, expected_phase=Phase.REQUIREMENTS)
    if after != expected:
        raise RequirementsRebaselineError("post-write Issue/ADC/Binding/PR/HEAD readback differs from the approved target")
    confirmed = _history(github)
    if (confirmed["intent_id"] != intent_id or confirmed["intent_payload"] != intent_payload
            or confirmed["applied_id"] is not None):
        raise RequirementsRebaselineError("Intent changed before the Applied append")
    applied_payload = {
        "approval_comment_id": approval_comment_id,
        "intent_comment_id": intent_id,
        "intent_sha256": intent_payload["record_sha256"],
        "plan_sha256": plan.sha256,
        "schema": APPLIED_SCHEMA,
    }
    applied_payload["record_sha256"] = _digest(applied_payload)
    applied_id, _ = _append_record(github, APPLIED_SCHEMA, applied_payload)
    complete = _history(github)
    if (complete["intent_id"] != intent_id or complete["intent_payload"] != intent_payload
            or complete["applied_id"] != applied_id or complete["applied_payload"] != applied_payload):
        raise RequirementsRebaselineError("Requirements Rebaseline Intent/Applied failed complete readback")
    final_snapshot = _current_snapshot(github, root, expected_phase=Phase.REQUIREMENTS)
    if final_snapshot != expected:
        raise RequirementsRebaselineError("Issue changed after Applied; the complete recovery is not current")
    return {"status": "APPLIED", "intent_comment_id": intent_id,
            "applied_comment_id": applied_id, "plan_sha256": plan.sha256,
            "label_write": "VERIFIED"}
