"""Owner-authorized forward checkpoint for one stale Issue #46 Ready receipt."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adc import ADCError
from .documents import validate_documents
from .execution import ExecutionError, binding_digest, read_binding
from .git import GitError, changed_paths_between, is_ancestor, worktree_clean
from .github import GitHub, GitHubError
from .path_safety import path_has_symlink
from .phase_evidence import (
    PhaseDecision, PhaseEvidenceError, Phase, _artifact_impacts, _collect_payload, _find_receipt,
    verify_ordinary_issue_context,
)
from .phases import IssueKind, parse_attention_labels, parse_phase_labels
from .work import execution_binding_path


class ReadyRebaselineError(ValueError):
    pass


PLAN_SCHEMA = "PASES_READY_REBASELINE_PLAN_V1"
APPROVAL_SCHEMA = "PASES_READY_REBASELINE_APPROVAL_V1"
INTENT_SCHEMA = "PASES_READY_REBASELINE_INTENT_V1"
APPLIED_SCHEMA = "PASES_READY_REBASELINE_V1"
OWNER_ID = 3744776
REPOSITORY_ID = 1401910271
ISSUE_ID = 5846549384
ISSUE_NUMBER = 46
PR_NUMBER = 67
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLAN_MARKER = f"<!-- {PLAN_SCHEMA}\n"
APPROVAL_MARKER = f"<!-- {APPROVAL_SCHEMA}\n"
INTENT_MARKER = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_MARKER = f"<!-- {APPLIED_SCHEMA}\n"
PLAN_FIELDS = {"generated_at", "plan_sha256", "schema", "snapshot"}
SNAPSHOT_FIELDS = {
    "adc_comment_id", "adc_sha256", "ancestry_policy", "binding_sha256", "branch_ref", "candidate_ready_decision",
    "candidate_ready_decision_sha256", "changed_paths", "document_validation", "head_sha40", "issue_created_at",
    "issue_id", "issue_kind", "issue_number", "owner_id", "previous_documents", "prior_ready_body_sha256",
    "prior_ready_comment_id", "prior_ready_commit_sha40", "pr", "repository", "repository_id",
}
INTENT_FIELDS = {"approval_body_sha256", "approval_comment_id", "plan", "plan_sha256", "record_sha256", "schema"}
APPLIED_FIELDS = {"intent_comment_id", "intent_sha256", "plan_sha256", "record_sha256", "schema"}

_ALLOWED_EXTRA_PATHS = {
    "adapters/claude/README.md",
    "adapters/openai/README.md",
    "docs/status/issue-46-review-assurance.md",
    "runtime/p_ases/cli.py",
    "runtime/p_ases/phase_evidence.py",
    "runtime/p_ases/ready_rebaseline.py",
    "tests/test_issue_phases.py",
    "tests/test_p_ases_cli.py",
    "tests/test_ready_rebaseline.py",
    "workflow/skills/delivery-control/SKILL.md",
    "workflow/skills/independent-review/SKILL.md",
    "workflow/skills/user-review/SKILL.md",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _body(schema: str, payload: dict[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(payload).decode('utf-8')}\n-->"


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ReadyRebaselineError(f"{label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReadyRebaselineError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReadyRebaselineError(f"{label} timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_time(value: Any, label: str) -> str:
    parsed = _timestamp(value, label)
    result = parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
    if value != result:
        raise ReadyRebaselineError(f"{label} timestamp is not canonical UTC")
    return result


def _decode_record(body: Any, schema: str) -> dict[str, Any]:
    if not isinstance(body, str):
        raise ReadyRebaselineError("GitHub record body is invalid")
    if body.endswith("\n"):
        body = body[:-1]
    prefix = f"<!-- {schema}\n"
    if not body.startswith(prefix) or not body.endswith("\n-->"):
        raise ReadyRebaselineError(f"{schema} comment format is invalid")
    encoded = body[len(prefix):-4]
    try:
        payload = json.loads(encoded)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ReadyRebaselineError(f"{schema} JSON is malformed") from exc
    if not isinstance(payload, dict) or _canonical(payload).decode("utf-8") != encoded:
        raise ReadyRebaselineError(f"{schema} JSON is not canonical")
    if payload.get("schema") != schema:
        raise ReadyRebaselineError(f"{schema} payload schema does not match")
    return payload


def _validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PLAN_FIELDS or value.get("schema") != PLAN_SCHEMA:
        raise ReadyRebaselineError("ready rebaseline plan has unknown or missing fields")
    if _canonical_time(value.get("generated_at"), "plan generated") != value["generated_at"]:
        raise ReadyRebaselineError("ready rebaseline plan timestamp is invalid")
    digest = value.get("plan_sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ReadyRebaselineError("ready rebaseline plan digest is invalid")
    without_digest = {key: item for key, item in value.items() if key != "plan_sha256"}
    if _digest(without_digest) != digest:
        raise ReadyRebaselineError("ready rebaseline plan digest does not match its content")
    snapshot = value.get("snapshot")
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_FIELDS:
        raise ReadyRebaselineError("ready rebaseline snapshot has unknown or missing fields")
    if (snapshot.get("ancestry_policy") != "any_descendant_requires_exact_owner_checkpoint"
            or snapshot.get("repository") != "puchinya/ai-agent-workflow"
            or snapshot.get("repository_id") != REPOSITORY_ID
            or snapshot.get("owner_id") != OWNER_ID
            or snapshot.get("issue_number") != ISSUE_NUMBER
            or snapshot.get("issue_id") != ISSUE_ID
            or snapshot.get("issue_kind") != IssueKind.SINGLE.value):
        raise ReadyRebaselineError("ready rebaseline plan is outside Issue #46's fixed identity")
    for key in ("adc_sha256", "binding_sha256", "candidate_ready_decision_sha256", "prior_ready_body_sha256"):
        if not isinstance(snapshot.get(key), str) or not SHA256.fullmatch(snapshot[key]):
            raise ReadyRebaselineError(f"ready rebaseline {key} is invalid")
    for key in ("head_sha40", "prior_ready_commit_sha40"):
        if not isinstance(snapshot.get(key), str) or not SHA40.fullmatch(snapshot[key]):
            raise ReadyRebaselineError(f"ready rebaseline {key} is invalid")
    for key in ("adc_comment_id", "prior_ready_comment_id"):
        if type(snapshot.get(key)) is not int or snapshot[key] < 1:
            raise ReadyRebaselineError(f"ready rebaseline {key} is invalid")
    _canonical_time(snapshot.get("issue_created_at"), "Issue creation")
    if not isinstance(snapshot.get("branch_ref"), str) or not snapshot["branch_ref"]:
        raise ReadyRebaselineError("ready rebaseline branch ref is invalid")
    paths = snapshot.get("changed_paths")
    if (not isinstance(paths, list) or any(not isinstance(path, str) or not path or path.startswith("/")
            or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")) for path in paths)
            or paths != sorted(set(paths))):
        raise ReadyRebaselineError("ready rebaseline changed paths are not canonical")
    previous_documents = snapshot.get("previous_documents")
    if not isinstance(previous_documents, list):
        raise ReadyRebaselineError("ready rebaseline previous document list is invalid")
    candidate = snapshot.get("candidate_ready_decision")
    try:
        decision = PhaseDecision(candidate)
        decision_body = decision.body()
    except PhaseEvidenceError as exc:
        raise ReadyRebaselineError(f"ready rebaseline candidate decision is invalid: {exc}") from exc
    if (decision.payload["repository"] != snapshot["repository"]
            or decision.payload["issue_number"] != ISSUE_NUMBER
            or decision.payload["issue_kind"] != IssueKind.SINGLE.value
            or decision.payload["from_phase"] not in {Phase.DESIGN.value, Phase.SPECIFICATION.value, Phase.REQUIREMENTS.value}
            or decision.payload["to_phase"] != Phase.READY.value
            or decision.payload["adc_comment_id"] != snapshot["adc_comment_id"]
            or decision.payload["adc_sha256"] != snapshot["adc_sha256"]
            or decision.payload["branch_ref"] != snapshot["branch_ref"]
            or decision.payload["commit_sha40"] != snapshot["head_sha40"]
            or hashlib.sha256(decision_body.encode()).hexdigest() != snapshot["candidate_ready_decision_sha256"]):
        raise ReadyRebaselineError("ready rebaseline candidate decision does not match its exact subject")
    prior_by_path: dict[str, dict[str, str]] = {}
    for row in previous_documents:
        if (not isinstance(row, dict) or set(row) != {"path", "role", "sha256"}
                or not isinstance(row.get("path"), str) or not row["path"]
                or not isinstance(row.get("role"), str)
                or not isinstance(row.get("sha256"), str) or not SHA256.fullmatch(row["sha256"])
                or row["path"] in prior_by_path):
            raise ReadyRebaselineError("ready rebaseline previous document entry is invalid")
        prior_by_path[row["path"]] = row
    current_by_path = {row["path"]: row for row in decision.payload["documents"]}
    if (not prior_by_path or set(prior_by_path) != set(current_by_path)
            or any(prior_by_path[path]["role"] != current_by_path[path]["role"] for path in prior_by_path)):
        raise ReadyRebaselineError("ready rebaseline candidate changed the approved artifact set or roles")
    changed_documents = any(prior_by_path[path]["sha256"] != current_by_path[path]["sha256"]
                            for path in prior_by_path)
    if snapshot.get("document_validation") != ("PASS" if changed_documents else "UNCHANGED"):
        raise ReadyRebaselineError("ready rebaseline document validation state does not match its bound artifact hashes")
    pr = snapshot.get("pr")
    if (not isinstance(pr, dict) or set(pr) != {"base_ref", "base_sha40", "head_ref", "head_sha40", "id", "number"}
            or pr.get("number") != PR_NUMBER or type(pr.get("id")) is not int or pr["id"] < 1
            or not isinstance(pr.get("base_ref"), str) or pr["base_ref"] != "main"
            or not isinstance(pr.get("head_ref"), str) or pr["head_ref"] != snapshot["branch_ref"]
            or pr.get("head_sha40") != snapshot["head_sha40"]
            or not isinstance(pr.get("base_sha40"), str) or not SHA40.fullmatch(pr["base_sha40"])):
        raise ReadyRebaselineError("ready rebaseline PR identity is invalid")
    return value


@dataclass(frozen=True)
class ReadyRebaselinePlan:
    value: dict[str, Any]

    def validate(self) -> "ReadyRebaselinePlan":
        _validate_plan(self.value)
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        return self.value["plan_sha256"]

    @classmethod
    def from_payload(cls, value: Any) -> "ReadyRebaselinePlan":
        return cls(value).validate()


def read_plan(path: Path) -> ReadyRebaselinePlan:
    location = Path(path)
    if path_has_symlink(location, root=location.parent) or not location.is_file():
        raise ReadyRebaselineError("ready rebaseline plan must be a regular non-symlink file")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReadyRebaselineError("ready rebaseline plan is unreadable") from exc
    if _canonical(value) + b"\n" != raw:
        raise ReadyRebaselineError("ready rebaseline plan is not canonical JSON with one trailing newline")
    return ReadyRebaselinePlan.from_payload(value)


def write_plan(path: Path, plan: ReadyRebaselinePlan) -> None:
    plan.validate()
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise ReadyRebaselineError("ready rebaseline plan output already exists; refusing overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical(plan.value) + b"\n")


def _fixed_identity(github: GitHub, issue: dict[str, Any]) -> tuple[int, int]:
    try:
        repository = github.repository_metadata()
    except GitHubError as exc:
        raise ReadyRebaselineError(f"repository identity readback failed: {exc}") from exc
    owner = repository.get("owner") if isinstance(repository, dict) else None
    repository_id = repository.get("id") if isinstance(repository, dict) else None
    owner_id = owner.get("id") if isinstance(owner, dict) else None
    if (type(repository_id) is not int or repository_id != REPOSITORY_ID
            or type(owner_id) is not int or owner_id != OWNER_ID
            or issue.get("number") != ISSUE_NUMBER or issue.get("id") != ISSUE_ID):
        raise ReadyRebaselineError("repository, Owner, or Issue identity differs from the fixed Issue #46 scope")
    return repository_id, owner_id


def _ready_source(verified: Any) -> tuple[Phase, dict[str, str]]:
    declared, reasons = _artifact_impacts(verified)
    if declared.get("specification") and declared.get("design"):
        return Phase.DESIGN, {}
    if declared.get("design"):
        return Phase.DESIGN, {}
    if declared.get("specification"):
        return Phase.SPECIFICATION, {"design": reasons.get("design", "")}
    return Phase.REQUIREMENTS, {key: reasons.get(key, "") for key in ("specification", "design")}


def _allowed_changed_paths(paths: tuple[str, ...], phase_documents: set[str]) -> None:
    for path in paths:
        if (path in phase_documents or path in _ALLOWED_EXTRA_PATHS
                or path.startswith("dist/")):
            continue
        raise ReadyRebaselineError(f"Ready rebaseline path is outside the approved recovery scope: {path}")


def _validate_candidate_documents(root: Path, previous_documents: list[dict[str, str]],
                                 candidate_documents: list[dict[str, str]]) -> str:
    previous = {row["path"]: row for row in previous_documents}
    current = {row["path"]: row for row in candidate_documents}
    if (set(previous) != set(current)
            or any(previous[path]["role"] != current[path]["role"] for path in previous)):
        raise ReadyRebaselineError("current Ready evidence changed the ADC-approved artifact set or roles")
    if any(previous[path]["sha256"] != current[path]["sha256"] for path in previous):
        errors = validate_documents(root)
        if errors:
            raise ReadyRebaselineError(
                "changed Ready documents fail the repository document/traceability validation: "
                + "; ".join(errors[:8]),
            )
        return "PASS"
    return "UNCHANGED"


def _comment_fingerprint(row: Any, comment_id: int) -> tuple[Any, ...]:
    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] != comment_id:
        raise ReadyRebaselineError("Issue comment identity is invalid")
    expected = {
        "issue_url": f"https://api.github.com/repos/puchinya/ai-agent-workflow/issues/{ISSUE_NUMBER}",
        "html_url": f"https://github.com/puchinya/ai-agent-workflow/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}",
        "url": f"https://api.github.com/repos/puchinya/ai-agent-workflow/issues/comments/{comment_id}",
    }
    if any(row.get(key) != value for key, value in expected.items()):
        raise ReadyRebaselineError("Issue comment repository or Issue attribution is invalid")
    created, updated = row.get("created_at"), row.get("updated_at")
    if not isinstance(created, str) or created != updated:
        raise ReadyRebaselineError("Issue comment was edited or has invalid timestamps")
    _timestamp(created, "Issue comment")
    actor = row.get("user")
    if (not isinstance(actor, dict) or type(actor.get("id")) is not int or actor["id"] < 1
            or not isinstance(actor.get("login"), str) or actor.get("type") not in {"User", "Bot"}):
        raise ReadyRebaselineError("Issue comment author identity is incomplete")
    return (comment_id, row.get("body"), created, updated, actor["id"], actor["login"].casefold(),
            actor["type"], *(row.get(key) for key in ("issue_url", "html_url", "url")))


def _read_comment_direct_list_direct(github: GitHub, comment_id: int,
                                     *, expected_body: str | None = None) -> dict[str, Any]:
    try:
        first = github.issue_comment(ISSUE_NUMBER, comment_id)
        rows = [row for row in github.issue_comments(ISSUE_NUMBER)
                if isinstance(row, dict) and row.get("id") == comment_id]
        second = github.issue_comment(ISSUE_NUMBER, comment_id)
    except GitHubError as exc:
        raise ReadyRebaselineError(f"Issue comment direct/list/direct readback failed: {exc}") from exc
    if len(rows) != 1:
        raise ReadyRebaselineError("Issue comment is missing or duplicated in the Issue history")
    fingerprints = [_comment_fingerprint(row, comment_id) for row in (first, rows[0], second)]
    if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
        raise ReadyRebaselineError("Issue comment changed during direct/list/direct readback")
    if expected_body is not None and second.get("body") != expected_body:
        raise ReadyRebaselineError("Issue comment body differs from the expected canonical record")
    return second


def owner_approval_comment(plan: ReadyRebaselinePlan) -> str:
    plan.validate()
    return _body(APPROVAL_SCHEMA, {
        "approved": True,
        "issue_id": ISSUE_ID,
        "issue_number": ISSUE_NUMBER,
        "plan_sha256": plan.sha256,
        "repository": "puchinya/ai-agent-workflow",
        "repository_id": REPOSITORY_ID,
        "schema": APPROVAL_SCHEMA,
    })


def _approval_payload(plan: ReadyRebaselinePlan) -> dict[str, Any]:
    return _decode_record(owner_approval_comment(plan), APPROVAL_SCHEMA)


def _verify_owner_approval(github: GitHub, plan: ReadyRebaselinePlan, comment_id: int) -> dict[str, Any]:
    if type(comment_id) is not int or comment_id < 1:
        raise ReadyRebaselineError("Owner approval comment ID is invalid")
    expected = _approval_payload(plan)
    try:
        rows = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ReadyRebaselineError(f"Owner approval history is unavailable: {exc}") from exc
    exact: list[dict[str, Any]] = []
    for row in rows:
        body = row.get("body") if isinstance(row, dict) else None
        if not isinstance(body, str) or not body.startswith(APPROVAL_MARKER):
            continue
        payload = _decode_record(body, APPROVAL_SCHEMA)
        if payload.get("issue_number") != ISSUE_NUMBER:
            raise ReadyRebaselineError("ready rebaseline approval is attached to another Issue")
        if payload == expected:
            exact.append(row)
    if len(exact) != 1 or exact[0].get("id") != comment_id:
        raise ReadyRebaselineError("exact Owner approval comment is missing, duplicated, or has the wrong ID")
    body = owner_approval_comment(plan)
    stored_body = exact[0].get("body")
    if stored_body not in {body, body + "\n"}:
        raise ReadyRebaselineError("Owner approval body differs from the exact canonical plan authorization")
    row = _read_comment_direct_list_direct(github, comment_id, expected_body=stored_body)
    actor = row.get("user")
    if (actor.get("id") != OWNER_ID or actor.get("type") != "User"
            or actor.get("login", "").casefold() != "puchinya"):
        raise ReadyRebaselineError("ready rebaseline approval was not authored by the fixed repository Owner")
    if _timestamp(row["created_at"], "Owner approval") < _timestamp(plan.value["generated_at"], "plan generated"):
        raise ReadyRebaselineError("Owner approval predates the exact plan")
    return row


def _snapshot(github: GitHub, root: Path, *, allow_execution_phase: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    issue, verified, kind, branch_ref, head_sha = verify_ordinary_issue_context(
        github, root, ISSUE_NUMBER, IssueKind.SINGLE, require_binding=True,
    )
    labels = [row.get("name") for row in issue.get("labels", []) if isinstance(row, dict)]
    phase = parse_phase_labels(labels)
    allowed_phases = {Phase.READY, Phase.EXECUTION} if allow_execution_phase else {Phase.READY}
    if phase not in allowed_phases or parse_attention_labels(labels):
        raise ReadyRebaselineError("ready rebaseline subject is no longer in the permitted Issue phase")
    if kind is not IssueKind.SINGLE:
        raise ReadyRebaselineError("ready rebaseline is limited to Issue #46 kind:single")
    repository_id, owner_id = _fixed_identity(github, issue)
    ready_source, skips = _ready_source(verified)
    prior_id, prior = _find_receipt(
        github, ISSUE_NUMBER, source=ready_source, target=Phase.READY,
        adc_comment_id=verified.pointer.comment_id, adc_sha256=verified.contract.sha256,
    )
    prior_sha = prior.payload["commit_sha40"]
    if not is_ancestor(root, prior_sha, head_sha):
        raise ReadyRebaselineError("current branch HEAD is not a descendant of the immutable Ready receipt")
    if not worktree_clean(root):
        raise ReadyRebaselineError("ready rebaseline requires a clean committed worktree")
    candidate, _current_issue, _current_adc, _branch, _head = _collect_payload(
        github, root, ISSUE_NUMBER, ready_source, Phase.READY, skips,
        check_source_phase=False, allow_predecessor_artifact_drift=True,
    )
    phase_documents = {row["path"] for row in candidate.payload["documents"]}
    try:
        changed_paths = changed_paths_between(root, prior_sha, head_sha)
    except GitError as exc:
        raise ReadyRebaselineError(f"Ready-to-HEAD change set could not be verified: {exc}") from exc
    _allowed_changed_paths(changed_paths, phase_documents)
    binding = read_binding(execution_binding_path(root, ISSUE_NUMBER))
    binding_sha = binding_digest(binding)
    try:
        pull = github.pull_request(PR_NUMBER)
    except GitHubError as exc:
        raise ReadyRebaselineError(f"current PR identity readback failed: {exc}") from exc
    base, head = pull.get("base"), pull.get("head")
    if (pull.get("state") != "open" or pull.get("merged") is True
            or not isinstance(base, dict) or not isinstance(head, dict)
            or base.get("ref") != "main" or head.get("ref") != branch_ref
            or head.get("sha") != head_sha or not isinstance(base.get("sha"), str)
            or not SHA40.fullmatch(base["sha"])):
        raise ReadyRebaselineError("PR #67 is not the exact open PR for the current bound branch HEAD")
    prior_documents = prior.payload["documents"]
    document_validation = _validate_candidate_documents(root, prior_documents, candidate.payload["documents"])
    decision_body = candidate.body()
    snapshot = {
        "adc_comment_id": verified.pointer.comment_id,
        "adc_sha256": verified.contract.sha256,
        "ancestry_policy": "any_descendant_requires_exact_owner_checkpoint",
        "binding_sha256": binding_sha,
        "branch_ref": branch_ref,
        "candidate_ready_decision": candidate.payload,
        "candidate_ready_decision_sha256": hashlib.sha256(decision_body.encode("utf-8")).hexdigest(),
        "changed_paths": list(changed_paths),
        "document_validation": document_validation,
        "head_sha40": head_sha,
        "issue_created_at": _canonical_time(issue.get("created_at"), "Issue creation"),
        "issue_id": issue["id"],
        "issue_kind": kind.value,
        "issue_number": ISSUE_NUMBER,
        "owner_id": owner_id,
        "previous_documents": prior_documents,
        "prior_ready_body_sha256": hashlib.sha256(prior.body().encode("utf-8")).hexdigest(),
        "prior_ready_comment_id": prior_id,
        "prior_ready_commit_sha40": prior_sha,
        "pr": {"base_ref": base["ref"], "base_sha40": base["sha"],
               "head_ref": head["ref"], "head_sha40": head["sha"],
               "id": pull.get("id"), "number": PR_NUMBER},
        "repository": github.repo,
        "repository_id": repository_id,
    }
    return snapshot


def build_plan(github: GitHub, root: Path) -> ReadyRebaselinePlan:
    """Build a read-only exact-subject Ready rebaseline plan for Issue #46."""
    snapshot = _snapshot(github, root)
    if snapshot["head_sha40"] == snapshot["prior_ready_commit_sha40"]:
        raise ReadyRebaselineError("current HEAD already matches the immutable Ready receipt")
    state = _read_state(github)
    if state["intent_id"] is not None:
        raise ReadyRebaselineError("a prior Ready rebaseline Intent exists; refusing a second or ambiguous attempt")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {"generated_at": generated_at, "schema": PLAN_SCHEMA, "snapshot": snapshot}
    plan = {**payload, "plan_sha256": _digest(payload)}
    return ReadyRebaselinePlan.from_payload(plan)


def _read_plan_comment_body(row: dict[str, Any], schema: str) -> dict[str, Any]:
    return _decode_record(row.get("body"), schema)


def _read_state(github: GitHub) -> dict[str, Any]:
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ReadyRebaselineError(f"ready rebaseline history is unavailable: {exc}") from exc
    intents = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
               and row["body"].startswith(INTENT_MARKER)]
    applied = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
               and row["body"].startswith(APPLIED_MARKER)]
    if len(intents) > 1 or len(applied) > 1 or (applied and not intents):
        raise ReadyRebaselineError("ready rebaseline history is duplicated or incomplete")
    if not intents:
        return {"intent_id": None, "intent_payload": None, "applied_id": None, "applied_payload": None}
    intent_row = intents[0]
    intent_id = intent_row.get("id")
    intent_payload = _read_plan_comment_body(intent_row, INTENT_SCHEMA)
    if type(intent_id) is not int or intent_id < 1 or set(intent_payload) != INTENT_FIELDS:
        raise ReadyRebaselineError("ready rebaseline Intent schema is invalid")
    record_digest = intent_payload.get("record_sha256")
    if not isinstance(record_digest, str) or _digest({key: item for key, item in intent_payload.items()
                                                     if key != "record_sha256"}) != record_digest:
        raise ReadyRebaselineError("ready rebaseline Intent digest is invalid")
    plan = ReadyRebaselinePlan.from_payload(intent_payload.get("plan"))
    approval_id = intent_payload.get("approval_comment_id")
    if (type(approval_id) is not int or approval_id < 1 or intent_id <= approval_id
            or intent_payload.get("plan_sha256") != plan.sha256
            or not isinstance(intent_payload.get("approval_body_sha256"), str)
            or not SHA256.fullmatch(intent_payload["approval_body_sha256"])):
        raise ReadyRebaselineError("ready rebaseline Intent does not bind its exact approval and plan")
    _read_comment_direct_list_direct(github, intent_id, expected_body=intent_row["body"])
    approval_row = _verify_owner_approval(github, plan, approval_id)
    if hashlib.sha256(approval_row["body"].encode("utf-8")).hexdigest() != intent_payload["approval_body_sha256"]:
        raise ReadyRebaselineError("ready rebaseline Intent approval digest changed")
    applied_id = None
    applied_payload = None
    if applied:
        applied_row = applied[0]
        applied_id = applied_row.get("id")
        applied_payload = _read_plan_comment_body(applied_row, APPLIED_SCHEMA)
        if (type(applied_id) is not int or applied_id <= intent_id or set(applied_payload) != APPLIED_FIELDS
                or applied_payload.get("schema") != APPLIED_SCHEMA
                or applied_payload.get("intent_comment_id") != intent_id
                or applied_payload.get("intent_sha256") != record_digest
                or applied_payload.get("plan_sha256") != plan.sha256):
            raise ReadyRebaselineError("ready rebaseline Applied record does not match its exact Intent")
        applied_record_digest = applied_payload.get("record_sha256")
        if (not isinstance(applied_record_digest, str)
                or _digest({key: item for key, item in applied_payload.items()
                            if key != "record_sha256"}) != applied_record_digest):
            raise ReadyRebaselineError("ready rebaseline Applied digest is invalid")
        _read_comment_direct_list_direct(github, applied_id, expected_body=applied_row["body"])
    return {"intent_id": intent_id, "intent_payload": intent_payload,
            "applied_id": applied_id, "applied_payload": applied_payload}


def _assert_current(github: GitHub, root: Path, plan: ReadyRebaselinePlan, *, allow_execution: bool = False) -> None:
    try:
        current = _snapshot(github, root, allow_execution_phase=allow_execution)
    except (ReadyRebaselineError, PhaseEvidenceError, ADCError, GitHubError, GitError, ExecutionError) as exc:
        raise ReadyRebaselineError(f"ready rebaseline current-subject validation failed: {exc}") from exc
    if current != plan.value["snapshot"]:
        raise ReadyRebaselineError("ready rebaseline plan is stale for the current Issue, ADC, Binding, PR, HEAD, or documents")


def _check_history_for_write(github: GitHub, plan: ReadyRebaselinePlan) -> None:
    state = _read_state(github)
    if state["intent_id"] is not None:
        if (state["intent_payload"]["plan_sha256"] == plan.sha256 and state["applied_id"] is not None):
            return
        if state["intent_payload"]["plan_sha256"] == plan.sha256:
            raise ReadyRebaselineError("matching Ready rebaseline Intent has no Applied record; refusing replay")
        raise ReadyRebaselineError("a conflicting Ready rebaseline Intent already exists")


def _append_record(github: GitHub, schema: str, payload: dict[str, Any]) -> tuple[int, str]:
    body = _body(schema, payload)
    try:
        response = github.create_issue_comment(ISSUE_NUMBER, body)
    except GitHubError as exc:
        try:
            matches = [row for row in github.issue_comments(ISSUE_NUMBER)
                       if isinstance(row, dict) and row.get("body") in {body, body + "\n"}]
        except GitHubError as read_exc:
            raise ReadyRebaselineError(f"{schema} write response and recovery readback are unknown: {read_exc}") from exc
        if len(matches) != 1:
            raise ReadyRebaselineError(f"{schema} write failed or is ambiguous; refusing blind retry") from exc
        response = matches[0]
    comment_id = response.get("id") if isinstance(response, dict) else None
    if type(comment_id) is not int or comment_id < 1:
        raise ReadyRebaselineError(f"{schema} response has no valid Issue comment ID")
    row = _read_comment_direct_list_direct(github, comment_id)
    if row.get("body") not in {body, body + "\n"}:
        raise ReadyRebaselineError(f"{schema} readback body differs from the canonical record")
    return comment_id, row["body"]


def apply_plan(github: GitHub, root: Path, plan: ReadyRebaselinePlan,
               approval_comment_id: int) -> dict[str, Any]:
    """Append one Intent and one Applied checkpoint after exact Owner approval."""
    plan.validate()
    state = _read_state(github)
    if state["applied_id"] is not None:
        if (state["intent_payload"]["plan_sha256"] != plan.sha256
                or state["intent_payload"]["approval_comment_id"] != approval_comment_id):
            raise ReadyRebaselineError("existing Ready checkpoint belongs to another plan or approval")
        applied_row = _read_comment_direct_list_direct(github, state["applied_id"])
        return {"status": "NOOP", "intent_comment_id": state["intent_id"],
                "applied_comment_id": state["applied_id"], "plan_sha256": plan.sha256,
                "applied_body_sha256": hashlib.sha256(applied_row["body"].encode()).hexdigest()}
    if state["intent_id"] is not None:
        raise ReadyRebaselineError("an incomplete Ready rebaseline Intent exists; refusing blind replay")
    approval = _verify_owner_approval(github, plan, approval_comment_id)
    _assert_current(github, root, plan)
    _check_history_for_write(github, plan)
    intent_payload = {
        "approval_body_sha256": hashlib.sha256(approval["body"].encode("utf-8")).hexdigest(),
        "approval_comment_id": approval_comment_id,
        "plan": plan.value,
        "plan_sha256": plan.sha256,
        "schema": INTENT_SCHEMA,
    }
    intent_payload["record_sha256"] = _digest(intent_payload)
    intent_id, _intent_body = _append_record(github, INTENT_SCHEMA, intent_payload)
    # Any incomplete Intent is deliberately non-replayable. The following recheck either
    # proves the exact approved subject is still current or leaves a visible fail-closed record.
    _assert_current(github, root, plan)
    approval = _verify_owner_approval(github, plan, approval_comment_id)
    current = _read_state(github)
    if (current["intent_id"] != intent_id or current["applied_id"] is not None
            or current["intent_payload"] != intent_payload
            or hashlib.sha256(approval["body"].encode("utf-8")).hexdigest()
               != intent_payload["approval_body_sha256"]):
        raise ReadyRebaselineError("Ready rebaseline history changed after Intent; no checkpoint was written")
    applied_payload = {
        "intent_comment_id": intent_id,
        "intent_sha256": intent_payload["record_sha256"],
        "plan_sha256": plan.sha256,
        "schema": APPLIED_SCHEMA,
    }
    applied_payload["record_sha256"] = _digest(applied_payload)
    applied_id, applied_body = _append_record(github, APPLIED_SCHEMA, applied_payload)
    completed = _read_state(github)
    if (completed["intent_id"] != intent_id or completed["applied_id"] != applied_id
            or completed["intent_payload"] != intent_payload or completed["applied_payload"] != applied_payload):
        raise ReadyRebaselineError("Ready rebaseline checkpoint failed complete history readback")
    return {"status": "APPLIED", "intent_comment_id": intent_id,
            "applied_comment_id": applied_id, "plan_sha256": plan.sha256,
            "applied_body_sha256": hashlib.sha256(applied_body.encode("utf-8")).hexdigest()}


def verify_checkpoint(github: GitHub, root: Path, applied_comment_id: int) -> ReadyRebaselinePlan:
    """Validate the latest Owner-authorized checkpoint against the exact current Ready subject."""
    state = _read_state(github)
    if state["intent_id"] is None or state["applied_id"] != applied_comment_id:
        raise ReadyRebaselineError("requested Ready rebaseline checkpoint is missing, stale, or not latest")
    plan = ReadyRebaselinePlan.from_payload(state["intent_payload"]["plan"])
    approval_id = state["intent_payload"]["approval_comment_id"]
    _verify_owner_approval(github, plan, approval_id)
    if (plan.value["snapshot"]["head_sha40"] != state["intent_payload"]["plan"]["snapshot"]["head_sha40"]
            or state["applied_payload"]["plan_sha256"] != plan.sha256):
        raise ReadyRebaselineError("Ready rebaseline checkpoint identity is inconsistent")
    _assert_current(github, root, plan)
    return plan
