"""One-time, exact-scope adopted execution epoch for Issue #63 / PR #64.

This is a prospective recovery origin. It never creates or rewrites an old
ExecutionBinding V1 and all adoption writes are guarded by a separate V3 owner
decision bound to the final candidate HEAD.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adc import ADCError, verify_adc
from .checkpoint import (
    CheckpointError, PRBinding, WorkCheckpoint, checkpoint_path, read_checkpoint,
    read_pr_binding, write_checkpoint, write_pr_binding,
)
from .current_base import CurrentBaseError
from .execution import (
    AdoptedExecutionEpoch, ExecutionError, WorkspaceAttachment, read_binding,
)
from .execution import execution_identity_digest
from .git import (
    GitError, current_branch, discover_repository, head_sha40, is_ancestor,
    remote_branch_sha, verify_remote_repository, worktree_clean,
)
from .github import GitHubError
from .issue_association import IssueAssociationError, parse_issue_association
from .owner_consent import OWNER_ID, REPOSITORY_ID, SCHEMA_V3, OwnerDecisionError, read_verified_owner_decision
from .owner_authorization import (
    OwnerAuthorizationError,
    _validate_plan as _validate_owner_authorization_plan,
    create_authorization_plan,
)
from .path_safety import path_has_symlink
from .phase_rebaseline import (
    APPLIED_V2_SCHEMA, INTENT_V2_SCHEMA, PhaseRebaselineError,
    _approved_generations, _read_history, _validate_generation_history,
)
from .profile import ProfileError, load_profile
from .work import (
    WorkError, _checkpoint_files, execution_binding_path, latest_checkpoint, read_pr_binding_history,
    _pr_binding_version_path,
)

REPOSITORY = "puchinya/ai-agent-workflow"
ISSUE_NUMBER = 63
PR_NUMBER = 64
PLAN_SCHEMA = "PASES_EXECUTION_ADOPTION_PLAN_V1"
INTENT_SCHEMA = "PASES_EXECUTION_ADOPTION_INTENT_V1"
APPLIED_SCHEMA = "PASES_EXECUTION_ADOPTION_APPLIED_V1"
INTENT_MARKER = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_MARKER = f"<!-- {APPLIED_SCHEMA}\n"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class ExecutionAdoptionError(ValueError):
    """Invalid, stale, ambiguous or unauthenticated one-time adoption."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def adoption_path(root: Path, issue_number: int = ISSUE_NUMBER) -> Path:
    if issue_number != ISSUE_NUMBER:
        raise ExecutionAdoptionError("adoption is restricted to Issue #63")
    return Path(root) / ".p_ases" / "state" / str(issue_number) / "execution-adoption.json"


def attachment_path(root: Path, issue_number: int = ISSUE_NUMBER) -> Path:
    if issue_number != ISSUE_NUMBER:
        raise ExecutionAdoptionError("workspace adoption is restricted to Issue #63")
    return Path(root) / ".p_ases" / "state" / str(issue_number) / "workspace-attachment.json"


def adoption_plan_path(root: Path, issue_number: int = ISSUE_NUMBER) -> Path:
    if issue_number != ISSUE_NUMBER:
        raise ExecutionAdoptionError("adoption plan storage is restricted to Issue #63")
    return Path(root) / ".p_ases" / "state" / str(issue_number) / "execution-adoption-plan.json"


def _attachment_id(root: Path, branch_ref: str) -> str:
    stat = root.stat()
    material = {
        "branch_ref": branch_ref, "device": stat.st_dev, "inode": stat.st_ino,
        "issue_number": ISSUE_NUMBER, "repository": REPOSITORY,
        "work_directory": str(root.resolve()),
    }
    return hashlib.sha256(b"PASES_WORKSPACE_ATTACH_V1\x00" + _canonical(material)).hexdigest()


def _read_issue_phase(issue: dict[str, Any]) -> tuple[list[str], str, str]:
    labels = issue.get("labels")
    if (not isinstance(labels, list) or any(not isinstance(row, dict) or not isinstance(row.get("name"), str)
                                            for row in labels)):
        raise ExecutionAdoptionError("Issue #63 labels are incomplete")
    names = [row["name"] for row in labels]
    if len(names) != len(set(names)):
        raise ExecutionAdoptionError("Issue #63 labels are duplicated")
    kinds = [name.removeprefix("kind:") for name in names if name.startswith("kind:")]
    phases = [name.removeprefix("phase:") for name in names if name.startswith("phase:")]
    if kinds != ["single"] or phases != ["requirements"]:
        raise ExecutionAdoptionError("adoption requires Issue #63 kind:single / phase:requirements")
    if any(name.startswith("attention:") for name in names):
        raise ExecutionAdoptionError("adoption is blocked while Issue #63 has an attention state")
    return sorted(names), kinds[0], phases[0]


def _phase_receipt_snapshot(github: Any, adc_comment_id: int, adc_sha256: str) -> dict[str, Any]:
    try:
        chain = _approved_generations(github)
        records = _read_history(github)
        _v1_intent, _v1_applied, v2_pairs = _validate_generation_history(records, chain)
    except (PhaseRebaselineError, ADCError) as exc:
        raise ExecutionAdoptionError(f"Phase V2 history is invalid: {exc}") from exc
    if not chain or chain[-1].pointer.comment_id != adc_comment_id or chain[-1].pointer.sha256 != adc_sha256:
        raise ExecutionAdoptionError("Phase V2 history is not bound to the current approved ADC")
    generation_index = len(chain) - 1
    pair = v2_pairs.get(generation_index)
    if pair is None or pair[1] is None:
        raise ExecutionAdoptionError("current ADC generation has no completed Phase V2 rebaseline")
    intent, applied = pair
    if (intent.schema != INTENT_V2_SCHEMA or applied.schema != APPLIED_V2_SCHEMA
            or intent.payload.get("operation") != "adopt_existing_requirements"
            or intent.payload.get("to_phase") != "requirements"
            or applied.payload.get("intent_comment_id") != intent.comment_id):
        raise ExecutionAdoptionError("current Phase V2 receipts do not represent the completed requirements adoption")
    return {
        "phase_intent_comment_id": intent.comment_id,
        "phase_applied_comment_id": applied.comment_id,
        "phase_applied_payload_sha256": hashlib.sha256(_canonical(applied.payload)).hexdigest(),
    }


def _required_ci_snapshot(github: Any, root: Path, head: str) -> tuple[list[dict[str, Any]], str]:
    try:
        profile = load_profile(root)
        checks = github.check_runs_for_ref(head)
    except (ProfileError, GitHubError) as exc:
        raise ExecutionAdoptionError(f"final exact-HEAD Required Checks are unavailable: {exc}") from exc
    expected = dict(profile.required_checks)
    if len(expected) != 4 or any(app_id != 15368 for app_id in expected.values()):
        raise ExecutionAdoptionError("PR #64 adoption requires the configured four trusted App ID 15368 checks")
    expected["pull-request-metadata"] = 15368
    result: list[dict[str, Any]] = []
    for name, app_id in sorted(expected.items()):
        matches = [row for row in checks if row.get("name") == name and row.get("app", {}).get("id") == app_id]
        if len(matches) != 1:
            raise ExecutionAdoptionError(f"exact-HEAD CI check {name!r} is missing or duplicated")
        row = matches[0]
        if row.get("status") != "completed" or row.get("conclusion") != "success" or row.get("head_sha") != head:
            raise ExecutionAdoptionError(f"exact-HEAD CI check {name!r} has not succeeded")
        result.append({
            "app_id": app_id, "check_run_id": row["id"], "conclusion": row["conclusion"],
            "head_sha40": head, "name": name,
        })
    return result, hashlib.sha256(_canonical(result)).hexdigest()


def _pull_identity(github: Any) -> tuple[dict[str, Any], str, str, str, str, int]:
    try:
        pull = github.pull_request(PR_NUMBER)
    except GitHubError as exc:
        raise ExecutionAdoptionError(f"PR #64 readback failed: {exc}") from exc
    base, head = pull.get("base"), pull.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_ref = base.get("ref") if isinstance(base, dict) else None
    base_sha = base.get("sha") if isinstance(base, dict) else None
    branch_ref = head.get("ref") if isinstance(head, dict) else None
    head_sha = head.get("sha") if isinstance(head, dict) else None
    author = pull.get("user") if isinstance(pull, dict) else None
    author_id = author.get("id") if isinstance(author, dict) else None
    try:
        association = parse_issue_association(pull.get("body"), ISSUE_NUMBER)
    except IssueAssociationError as exc:
        raise ExecutionAdoptionError(f"PR #64 Issue association is invalid: {exc}") from exc
    if (pull.get("number") != PR_NUMBER or not _positive(pull.get("id"))
            or pull.get("state") != "open" or pull.get("draft") is not False
            or pull.get("merged") is True or association != "deferred_close"
            or not isinstance(base_repo, dict) or not isinstance(base_repo.get("full_name"), str)
            or base_repo["full_name"].casefold() != REPOSITORY.casefold()
            or base_repo.get("id") != REPOSITORY_ID
            or not isinstance(head_repo, dict) or not isinstance(head_repo.get("full_name"), str)
            or head_repo["full_name"].casefold() != REPOSITORY.casefold()
            or head_repo.get("id") != REPOSITORY_ID
            or not isinstance(base_ref, str) or not isinstance(base_sha, str) or not SHA40.fullmatch(base_sha)
            or not isinstance(branch_ref, str) or not isinstance(head_sha, str) or not SHA40.fullmatch(head_sha)
            or not isinstance(author, dict) or author.get("type") != "User" or not _positive(author_id)
            or not isinstance(pull.get("title"), str) or not pull["title"].strip()):
        raise ExecutionAdoptionError("PR #64 is not the exact open, same-repository Refs #63 pull request")
    return pull, base_ref, base_sha, branch_ref, head_sha, author_id


def _candidate(github: Any, root: Path) -> dict[str, Any]:
    location = Path(root)
    if location.is_symlink() or path_has_symlink(location):
        raise ExecutionAdoptionError("adoption requires a non-symlink repository worktree")
    root = location.resolve()
    if getattr(github, "repo", None) != REPOSITORY:
        raise ExecutionAdoptionError("adoption is restricted to puchinya/ai-agent-workflow")
    try:
        repository = discover_repository(root)
        verify_remote_repository(root, REPOSITORY)
        metadata = github.repository_metadata()
        issue = github.issue(ISSUE_NUMBER)
    except (GitError, GitHubError) as exc:
        raise ExecutionAdoptionError(f"adoption preflight read failed: {exc}") from exc
    owner = metadata.get("owner") if isinstance(metadata, dict) else None
    expected_issue_url = f"https://api.github.com/repos/{REPOSITORY}"
    if (repository.casefold() != REPOSITORY.casefold() or not isinstance(metadata, dict)
            or metadata.get("id") != REPOSITORY_ID or metadata.get("full_name") != REPOSITORY
            or not isinstance(owner, dict) or owner.get("id") != OWNER_ID or owner.get("type") != "User"
            or issue.get("number") != ISSUE_NUMBER or issue.get("state") != "open"
            or issue.get("pull_request") is not None or issue.get("repository_url") != expected_issue_url):
        raise ExecutionAdoptionError("pinned repository/owner or open Issue #63 identity did not verify")
    labels, kind, phase = _read_issue_phase(issue)
    try:
        adc = verify_adc(github, ISSUE_NUMBER)
    except ADCError as exc:
        raise ExecutionAdoptionError(f"current approved ADC readback failed: {exc}") from exc
    if (adc.pointer.state != "approved" or adc.contract.repository != REPOSITORY
            or adc.pointer.comment_id != 6248703643
            or adc.pointer.sha256 != "b83620dc5d977c3f96c7ad792fded202b70a78f0c97d637bfcc64d8ef8e89306"):
        raise ExecutionAdoptionError("current ADC differs from the approved Issue #63 successor in this contract")
    phase_receipts = _phase_receipt_snapshot(github, adc.pointer.comment_id, adc.pointer.sha256)
    pull, base_ref, base_sha, branch_ref, pull_head, pr_author_user_id = _pull_identity(github)
    try:
        local_branch = current_branch(root)
        local_head = head_sha40(root)
        if not worktree_clean(root):
            raise ExecutionAdoptionError("adoption preflight requires a clean worktree")
        if local_branch != branch_ref or local_head != pull_head:
            raise ExecutionAdoptionError("local branch/HEAD differs from the exact current PR #64 head")
        if remote_branch_sha(root, branch_ref) != pull_head:
            raise ExecutionAdoptionError("origin PR branch differs from the exact current PR #64 head")
        if remote_branch_sha(root, base_ref) != base_sha:
            raise ExecutionAdoptionError("origin selected base ref differs from PR #64's exact base SHA")
        if not is_ancestor(root, base_sha, pull_head):
            raise ExecutionAdoptionError("PR #64 HEAD does not descend from the prospective selected base")
    except GitError as exc:
        raise ExecutionAdoptionError(f"exact Git preflight failed: {exc}") from exc
    binding_file = root / ".p_ases" / "state" / str(ISSUE_NUMBER) / "execution-binding.json"
    if binding_file.exists() or binding_file.is_symlink():
        raise ExecutionAdoptionError("an ExecutionBinding exists; adoption cannot overwrite or reinterpret it")
    ci_rows, ci_digest = _required_ci_snapshot(github, root, pull_head)
    attachment_id = _attachment_id(root, branch_ref)
    plan_without_id: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "owner_id": OWNER_ID,
        "issue_number": ISSUE_NUMBER,
        "issue_kind": kind,
        "issue_phase": phase,
        "issue_labels": labels,
        "adc_comment_id": adc.pointer.comment_id,
        "adc_sha256": adc.pointer.sha256,
        **phase_receipts,
        "pr_number": PR_NUMBER,
        "pr_id": pull["id"],
        "pr_url": pull.get("html_url"),
        "pr_title_sha256": hashlib.sha256(pull["title"].encode("utf-8")).hexdigest(),
        "pr_body_sha256": hashlib.sha256(pull["body"].encode("utf-8")).hexdigest(),
        "pr_author_user_id": pr_author_user_id,
        "selected_base_ref": base_ref,
        "selected_base_sha40": base_sha,
        "branch_ref": branch_ref,
        "observed_start_head_sha40": pull_head,
        "attachment_id": attachment_id,
        "historical_binding_provenance": "UNVERIFIED",
        "ci_check_runs": ci_rows,
        "ci_evidence_sha256": ci_digest,
    }
    adoption_id = hashlib.sha256(b"PASES_EXECUTION_ADOPTION_V1\x00" + _canonical(plan_without_id)).hexdigest()
    plan_without_id["adoption_id"] = adoption_id
    plan_without_id["plan_sha256"] = hashlib.sha256(_canonical(plan_without_id)).hexdigest()
    return validate_adoption_plan(plan_without_id)


def _validate_local_adoption_artifacts(root: Path, plan: dict[str, Any], *, allow_recovery: bool) -> None:
    """Allow only exact partial artifacts from this adoption during recovery."""
    root = Path(root).resolve()
    state_dir = root / ".p_ases" / "state" / str(ISSUE_NUMBER)
    expected_names = {"execution-adoption-plan.json", "execution-adoption.json", "workspace-attachment.json",
                      "pr-binding-000001.json", "checkpoint-000001.json"}
    if path_has_symlink(state_dir):
        raise ExecutionAdoptionError("adoption state path traverses a symbolic link")
    if state_dir.exists():
        if state_dir.is_symlink() or not state_dir.is_dir() or path_has_symlink(state_dir):
            raise ExecutionAdoptionError("adoption state directory is invalid or traverses a symbolic link")
        names = {path.name for path in state_dir.iterdir()}
        epoch_exists = adoption_path(root).is_file() and not adoption_path(root).is_symlink()
        later_history = {
            name for name in names
            if re.fullmatch(r"(?:pr-binding|checkpoint)-[0-9]{6}\.json", name)
        }
        unexpected = names - expected_names - (later_history if allow_recovery and epoch_exists else set())
        if unexpected:
            raise ExecutionAdoptionError("unverified or unrelated local binding/checkpoint artifacts exist")
    present = [path for path in (adoption_plan_path(root), adoption_path(root), attachment_path(root),
                                 _pr_binding_version_path(root, ISSUE_NUMBER, 1),
                                 checkpoint_path(root, ISSUE_NUMBER, 1))
               if path.exists() or path.is_symlink()]
    if present and not allow_recovery:
        raise ExecutionAdoptionError("local adoption artifacts already exist; use read-only status/recovery")
    for path in present:
        if path.is_symlink() or path_has_symlink(path):
            raise ExecutionAdoptionError("local adoption recovery artifact traverses a symbolic link")
    present_names = {path.name for path in present}
    if (("execution-adoption.json" in present_names and "execution-adoption-plan.json" not in present_names)
            or ("workspace-attachment.json" in present_names
                and not {"execution-adoption-plan.json", "execution-adoption.json"}.issubset(present_names))
            or ("pr-binding-000001.json" in present_names
                and not {"execution-adoption-plan.json", "execution-adoption.json",
                         "workspace-attachment.json"}.issubset(present_names))
            or ("checkpoint-000001.json" in present_names
                and not {"execution-adoption-plan.json", "execution-adoption.json",
                         "workspace-attachment.json", "pr-binding-000001.json"}
                    .issubset(present_names))):
        raise ExecutionAdoptionError("local adoption artifacts violate their atomic persistence order")
    if adoption_plan_path(root).exists():
        try:
            stored_plan = read_adoption_plan(adoption_plan_path(root))
        except ExecutionAdoptionError as exc:
            raise ExecutionAdoptionError("existing local adoption plan is invalid") from exc
        if stored_plan != validate_adoption_plan(plan):
            raise ExecutionAdoptionError("existing local adoption plan differs from the exact approved plan")
    epoch: AdoptedExecutionEpoch | None = None
    if adoption_path(root).exists():
        try:
            epoch = AdoptedExecutionEpoch.from_bytes(adoption_path(root).read_bytes())
        except (OSError, ExecutionError) as exc:
            raise ExecutionAdoptionError("existing local adopted epoch is invalid") from exc
        if epoch.adoption_id != plan["adoption_id"] or epoch.plan_sha256 != plan["plan_sha256"]:
            raise ExecutionAdoptionError("existing local adopted epoch belongs to a different approved plan")
        try:
            pr_history = read_pr_binding_history(root, ISSUE_NUMBER)
            checkpoint = latest_checkpoint(root, ISSUE_NUMBER)
        except WorkError as exc:
            raise ExecutionAdoptionError("existing adopted PRBinding/checkpoint history is invalid") from exc
        for _path, binding in pr_history:
            if (binding.adoption_id != epoch.adoption_id or binding.repository != REPOSITORY
                    or binding.issue_number != ISSUE_NUMBER or binding.pr_number != PR_NUMBER
                    or binding.adc_comment_id != plan["adc_comment_id"]
                    or binding.adc_sha256 != plan["adc_sha256"]
                    or binding.base_sha40 != plan["selected_base_sha40"]
                    or binding.branch_ref != plan["branch_ref"]):
                raise ExecutionAdoptionError("existing adopted PRBinding history changes its immutable epoch")
        for checkpoint_pathname in _checkpoint_files(root, ISSUE_NUMBER):
            checkpoint_row = read_checkpoint(checkpoint_pathname)
            if (checkpoint_row.execution_adoption_sha256 != epoch.sha256
                    or checkpoint_row.execution_binding_sha256 is not None):
                raise ExecutionAdoptionError("existing checkpoint history changes its adopted epoch identity")
    if attachment_path(root).exists():
        try:
            attachment = WorkspaceAttachment.from_bytes(attachment_path(root).read_bytes())
        except (OSError, ExecutionError) as exc:
            raise ExecutionAdoptionError("existing local workspace attachment is invalid") from exc
        if (attachment.adoption_id != plan["adoption_id"]
                or attachment.attachment_id != plan["attachment_id"]
                or attachment.branch_ref != plan["branch_ref"]
                or Path(attachment.work_directory).resolve() != root):
            raise ExecutionAdoptionError("existing workspace attachment differs from the approved plan")
    pr_path = _pr_binding_version_path(root, ISSUE_NUMBER, 1)
    if pr_path.exists():
        try:
            binding = read_pr_binding(pr_path)
        except CheckpointError as exc:
            raise ExecutionAdoptionError("existing adopted PRBinding is invalid") from exc
        if (binding.adoption_id != plan["adoption_id"] or binding.repository != REPOSITORY
                or binding.issue_number != ISSUE_NUMBER or binding.pr_number != PR_NUMBER
                or binding.adc_comment_id != plan["adc_comment_id"]
                or binding.adc_sha256 != plan["adc_sha256"]
                or binding.base_sha40 != plan["selected_base_sha40"]
                or binding.branch_ref != plan["branch_ref"]
                or binding.pr_head_sha40 != plan["observed_start_head_sha40"]):
            raise ExecutionAdoptionError("existing adopted PRBinding differs from the approved plan")
    checkpoint_file = checkpoint_path(root, ISSUE_NUMBER, 1)
    if checkpoint_file.exists():
        try:
            checkpoint = read_checkpoint(checkpoint_file)
        except CheckpointError as exc:
            raise ExecutionAdoptionError("existing adoption checkpoint is invalid") from exc
        if (checkpoint.execution_adoption_sha256 is None or checkpoint.execution_binding_sha256 is not None
                or checkpoint.completed_stage != "adoption" or checkpoint.step != 1
                or checkpoint.current_head_sha40 != plan["observed_start_head_sha40"]
                or epoch is None or checkpoint.execution_adoption_sha256 != epoch.sha256):
            raise ExecutionAdoptionError("existing checkpoint differs from the approved adopted epoch")


def build_adoption_plan(github: Any, root: Path) -> dict[str, Any]:
    """Build a read-only exact-scope plan bound to current clean PR HEAD and CI."""
    plan = _candidate(github, root)
    _validate_local_adoption_artifacts(root, plan, allow_recovery=False)
    history = _read_adoption_history(github)
    if history:
        raise ExecutionAdoptionError("an adoption journal already exists; no second adoption plan is permitted")
    return plan


def validate_adoption_plan(value: Any) -> dict[str, Any]:
    fields = {
        "schema", "repository", "repository_id", "owner_id", "issue_number", "issue_kind", "issue_phase",
        "issue_labels",
        "adc_comment_id", "adc_sha256", "phase_intent_comment_id", "phase_applied_comment_id",
        "phase_applied_payload_sha256", "pr_number", "pr_id", "pr_url", "pr_title_sha256", "pr_body_sha256",
        "pr_author_user_id",
        "selected_base_ref", "selected_base_sha40",
        "branch_ref", "observed_start_head_sha40", "attachment_id", "historical_binding_provenance",
        "ci_check_runs", "ci_evidence_sha256", "adoption_id", "plan_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ExecutionAdoptionError("adoption plan has unknown or missing fields")
    plan = dict(value)
    supplied = plan.pop("plan_sha256")
    issue_labels = plan.get("issue_labels")
    if (not isinstance(issue_labels, list) or any(not isinstance(label, str) for label in issue_labels)
            or issue_labels != sorted(set(issue_labels))):
        raise ExecutionAdoptionError("adoption plan Issue label snapshot is invalid")
    if (plan.get("schema") != PLAN_SCHEMA or plan.get("repository") != REPOSITORY
            or plan.get("repository_id") != REPOSITORY_ID or plan.get("owner_id") != OWNER_ID
            or plan.get("issue_number") != ISSUE_NUMBER or plan.get("pr_number") != PR_NUMBER
            or plan.get("issue_kind") != "single" or plan.get("issue_phase") != "requirements"
            or not {"kind:single", "phase:requirements"}.issubset(issue_labels)
            or any(label.startswith("attention:") for label in issue_labels)
            or not _positive(plan.get("pr_author_user_id"))
            or not _positive(plan.get("pr_id"))
            or plan.get("historical_binding_provenance") != "UNVERIFIED"
            or plan.get("adc_comment_id") != 6248703643
            or plan.get("adc_sha256") != "b83620dc5d977c3f96c7ad792fded202b70a78f0c97d637bfcc64d8ef8e89306"
            or not _positive(plan.get("phase_intent_comment_id"))
            or not _positive(plan.get("phase_applied_comment_id"))
            or plan.get("phase_applied_comment_id") <= plan.get("phase_intent_comment_id")
            or not isinstance(plan.get("phase_applied_payload_sha256"), str)
            or not SHA256.fullmatch(plan["phase_applied_payload_sha256"])
            or not isinstance(plan.get("pr_url"), str) or not plan["pr_url"].startswith("https://github.com/")
            or not isinstance(plan.get("pr_title_sha256"), str) or not SHA256.fullmatch(plan["pr_title_sha256"])
            or not isinstance(plan.get("pr_body_sha256"), str) or not SHA256.fullmatch(plan["pr_body_sha256"])
            or not isinstance(plan.get("selected_base_ref"), str) or not plan["selected_base_ref"]
            or not isinstance(plan.get("branch_ref"), str) or not plan["branch_ref"]
            or not isinstance(plan.get("selected_base_sha40"), str) or not SHA40.fullmatch(plan["selected_base_sha40"])
            or not isinstance(plan.get("observed_start_head_sha40"), str)
            or not SHA40.fullmatch(plan["observed_start_head_sha40"])
            or not isinstance(plan.get("attachment_id"), str) or not SHA256.fullmatch(plan["attachment_id"])
            or not isinstance(plan.get("adoption_id"), str) or not SHA256.fullmatch(plan["adoption_id"])
            or not isinstance(plan.get("ci_evidence_sha256"), str) or not SHA256.fullmatch(plan["ci_evidence_sha256"])
            or not isinstance(plan.get("ci_check_runs"), list)
            or not isinstance(supplied, str) or not SHA256.fullmatch(supplied)
            or hashlib.sha256(_canonical(plan)).hexdigest() != supplied):
        raise ExecutionAdoptionError("adoption plan subject or digest is invalid")
    if plan["ci_evidence_sha256"] != hashlib.sha256(_canonical(plan["ci_check_runs"])).hexdigest():
        raise ExecutionAdoptionError("adoption plan CI evidence digest does not match its check list")
    checks = plan["ci_check_runs"]
    if (len(checks) != 5 or any(not isinstance(row, dict)
                               or set(row) != {"app_id", "check_run_id", "conclusion", "head_sha40", "name"}
                               or row.get("app_id") != 15368 or not _positive(row.get("check_run_id"))
                               or row.get("conclusion") != "success"
                               or row.get("head_sha40") != plan["observed_start_head_sha40"]
                               or not isinstance(row.get("name"), str) or not row["name"]
                               for row in checks)
            or [row["name"] for row in checks] != sorted(row["name"] for row in checks)
            or len({row["name"] for row in checks}) != 5
            or len({row["check_run_id"] for row in checks}) != 5):
        raise ExecutionAdoptionError("adoption plan must bind five unique successful trusted exact-HEAD checks")
    adoption_id_material = {key: value for key, value in plan.items()
                            if key not in {"adoption_id", "plan_sha256"}}
    expected_adoption_id = hashlib.sha256(
        b"PASES_EXECUTION_ADOPTION_V1\x00" + _canonical(adoption_id_material)).hexdigest()
    if plan["adoption_id"] != expected_adoption_id:
        raise ExecutionAdoptionError("adoption operation ID does not match the complete prospective snapshot")
    if (plan["pr_url"] != f"https://github.com/{REPOSITORY}/pull/{PR_NUMBER}"
            or plan["selected_base_ref"] == plan["branch_ref"]
            or plan["branch_ref"].casefold() in {"main", "master"}):
        raise ExecutionAdoptionError("adoption plan PR URL or base/branch identity is invalid")
    try:
        from .checkpoint import validate_ref
        validate_ref(plan["selected_base_ref"])
        validate_ref(plan["branch_ref"])
    except CheckpointError as exc:
        raise ExecutionAdoptionError(f"adoption plan Git ref is invalid: {exc}") from exc
    return {**plan, "plan_sha256": supplied}


def adoption_plan_bytes(plan: dict[str, Any]) -> bytes:
    checked = validate_adoption_plan(plan)
    return _canonical(checked) + b"\n"


def write_adoption_plan(path: Path, plan: dict[str, Any]) -> None:
    destination = Path(path)
    if destination.exists() or destination.is_symlink() or path_has_symlink(destination):
        raise ExecutionAdoptionError("adoption plan output must be a new, non-symlink file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = adoption_plan_bytes(plan)
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise ExecutionAdoptionError("could not create immutable adoption plan") from exc
    if destination.read_bytes() != data:
        raise ExecutionAdoptionError("adoption plan readback changed")


def read_adoption_plan(path: Path) -> dict[str, Any]:
    location = Path(path)
    if path_has_symlink(location) or not location.is_file():
        raise ExecutionAdoptionError("adoption plan must be a regular non-symlink file")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionAdoptionError("adoption plan is unreadable or invalid JSON") from exc
    checked = validate_adoption_plan(value)
    if raw != adoption_plan_bytes(checked):
        raise ExecutionAdoptionError("adoption plan is not in canonical byte form")
    return checked


def _owner_details(plan: dict[str, Any]) -> dict[str, Any]:
    checked = validate_adoption_plan(plan)
    return {"adoption_plan": checked}


def _body(schema: str, payload: dict[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(payload).decode('utf-8')}\n-->"


def _parse_marker(body: Any, schema: str) -> dict[str, Any]:
    marker = f"<!-- {schema}\n"
    if not isinstance(body, str) or not body.startswith(marker) or not body.endswith("\n-->"):
        raise ExecutionAdoptionError("adoption journal marker is malformed")
    raw = body[len(marker):-len("\n-->")]
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ExecutionAdoptionError("adoption journal JSON is invalid") from exc
    if not isinstance(value, dict) or _canonical(value).decode("utf-8") != raw or value.get("schema") != schema:
        raise ExecutionAdoptionError("adoption journal payload is noncanonical")
    return value


def _comment_fingerprint(row: Any) -> tuple[Any, ...]:
    if not isinstance(row, dict) or not _positive(row.get("id")):
        raise ExecutionAdoptionError("adoption journal comment identity is incomplete")
    user = row.get("user")
    if (not isinstance(user, dict) or not _positive(user.get("id")) or user.get("type") != "User"
            or not isinstance(user.get("login"), str) or not user["login"]):
        raise ExecutionAdoptionError("adoption journal actor is not a stable GitHub User")
    body, created, updated = row.get("body"), row.get("created_at"), row.get("updated_at")
    if not isinstance(body, str) or not isinstance(created, str) or created != updated or not created.endswith("Z"):
        raise ExecutionAdoptionError("adoption journal comment is edited or lacks an exact UTC timestamp")
    try:
        parsed = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ExecutionAdoptionError("adoption journal comment timestamp is malformed") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ExecutionAdoptionError("adoption journal comment timestamp is not UTC")
    expected = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{row['id']}",
        f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{row['id']}",
    )
    actual = (row.get("url"), row.get("issue_url"), row.get("html_url"))
    if actual != expected:
        raise ExecutionAdoptionError("adoption journal carrier belongs to another Issue or repository")
    return (row["id"], body, created, updated, user["id"], user["login"].casefold(), user["type"], *actual)


def _read_adoption_history(github: Any) -> tuple[tuple[int, str, dict[str, Any], tuple[Any, ...]], ...]:
    try:
        first = github.issue_comments(ISSUE_NUMBER)
        rows: list[tuple[dict[str, Any], str]] = []
        for row in first:
            body = row.get("body") if isinstance(row, dict) else None
            if isinstance(body, str) and body.startswith("<!-- PASES_EXECUTION_ADOPTION_"):
                schema = INTENT_SCHEMA if body.startswith(INTENT_MARKER) else APPLIED_SCHEMA if body.startswith(APPLIED_MARKER) else None
                if schema is None:
                    raise ExecutionAdoptionError("unknown or malformed execution adoption journal marker")
                rows.append((row, schema))
        ids = [row.get("id") for row, _schema in rows]
        if any(not _positive(value) for value in ids) or ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ExecutionAdoptionError("adoption journal IDs are invalid, duplicated, or not append-only")
        direct_before = {comment_id: github.issue_comment(ISSUE_NUMBER, comment_id) for comment_id in ids}
        second = github.issue_comments(ISSUE_NUMBER)
        second_rows = [row for row in second if isinstance(row, dict)
                       and isinstance(row.get("body"), str)
                       and row["body"].startswith("<!-- PASES_EXECUTION_ADOPTION_")]
        if [row.get("id") for row in second_rows] != ids:
            raise ExecutionAdoptionError("adoption history changed during direct/list/direct readback")
        direct_after = {comment_id: github.issue_comment(ISSUE_NUMBER, comment_id) for comment_id in ids}
    except GitHubError as exc:
        raise ExecutionAdoptionError(f"adoption journal readback failed: {exc}") from exc
    records: list[tuple[int, str, dict[str, Any], tuple[Any, ...]]] = []
    for listed, schema in rows:
        comment_id = listed["id"]
        listed_again = next(row for row in second_rows if row.get("id") == comment_id)
        fingerprints = tuple(_comment_fingerprint(row) for row in (
            direct_before[comment_id], listed_again, direct_after[comment_id]))
        if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
            raise ExecutionAdoptionError("adoption carrier changed during direct/list/direct readback")
        payload = _parse_marker(direct_before[comment_id].get("body"), schema)
        if payload.get("repository") != REPOSITORY or payload.get("issue_number") != ISSUE_NUMBER:
            raise ExecutionAdoptionError("adoption journal declares a different repository or Issue")
        _validate_journal_shape(payload, schema)
        if fingerprints[0][4] != payload["executor_user_id"]:
            raise ExecutionAdoptionError("adoption journal executor ID differs from the GitHub comment actor")
        records.append((comment_id, schema, payload, fingerprints[0]))
    return tuple(records)


_JOURNAL_COMMON_FIELDS = frozenset({
    "schema", "repository", "repository_id", "owner_id", "executor_user_id", "issue_number", "pr_number",
    "adc_comment_id", "adc_sha256", "plan_sha256", "owner_authorization_plan_sha256",
    "approval_scope_sha256", "owner_decision_comment_id", "adoption_id", "operation_id",
    "selected_base_ref", "selected_base_sha40", "branch_ref", "observed_start_head_sha40",
    "historical_binding_provenance", "attachment_id", "created_at",
})


def _validate_journal_shape(payload: dict[str, Any], schema: str) -> None:
    expected = (_JOURNAL_COMMON_FIELDS if schema == INTENT_SCHEMA else
                _JOURNAL_COMMON_FIELDS | {"intent_comment_id", "intent_body_sha256"}
                if schema == APPLIED_SCHEMA else frozenset())
    if set(payload) != expected or payload.get("schema") != schema:
        raise ExecutionAdoptionError("adoption journal has unknown or missing fields")
    if (payload.get("repository") != REPOSITORY or payload.get("repository_id") != REPOSITORY_ID
            or payload.get("owner_id") != OWNER_ID or payload.get("issue_number") != ISSUE_NUMBER
            or payload.get("pr_number") != PR_NUMBER or payload.get("historical_binding_provenance") != "UNVERIFIED"
            or not _positive(payload.get("executor_user_id"))
            or not _positive(payload.get("adc_comment_id"))
            or not _positive(payload.get("owner_decision_comment_id"))
            or not all(isinstance(payload.get(key), str) and SHA256.fullmatch(payload[key])
                       for key in ("adc_sha256", "plan_sha256", "owner_authorization_plan_sha256",
                                   "approval_scope_sha256", "adoption_id", "attachment_id"))
            or payload.get("operation_id") != payload.get("adoption_id")
            or not isinstance(payload.get("selected_base_ref"), str) or not payload["selected_base_ref"]
            or not isinstance(payload.get("branch_ref"), str) or not payload["branch_ref"]
            or not isinstance(payload.get("selected_base_sha40"), str)
            or not SHA40.fullmatch(payload["selected_base_sha40"])
            or not isinstance(payload.get("observed_start_head_sha40"), str)
            or not SHA40.fullmatch(payload["observed_start_head_sha40"])):
        raise ExecutionAdoptionError("adoption journal scope fields are invalid")
    try:
        datetime.strptime(payload.get("created_at", ""), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as exc:
        raise ExecutionAdoptionError("adoption journal timestamp must be canonical UTC seconds") from exc
    if schema == APPLIED_SCHEMA and (
            not _positive(payload.get("intent_comment_id"))
            or not isinstance(payload.get("intent_body_sha256"), str)
            or SHA256.fullmatch(payload["intent_body_sha256"]) is None):
        raise ExecutionAdoptionError("adoption Applied journal linkage is invalid")


def _live_owner_decision(github: Any, plan: dict[str, Any], owner_plan: dict[str, Any]):
    try:
        return read_verified_owner_decision(
            github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID, operation="EXECUTION_ADOPTION",
            subject_sha256=plan["plan_sha256"], expected_pr_number=PR_NUMBER,
            expected_pr_head_sha40=plan["observed_start_head_sha40"],
            expected_plan_sha256=owner_plan["plan_sha256"], repository_id=REPOSITORY_ID,
            expected_approval_scope_sha256=owner_plan["approval_scope_sha256"], expected_schema=SCHEMA_V3,
        )
    except OwnerDecisionError as exc:
        raise ExecutionAdoptionError(f"exact post-CI Owner adoption decision is missing or invalid: {exc}") from exc


def _current_plan_matches(github: Any, root: Path, approved: dict[str, Any]) -> dict[str, Any]:
    current = _candidate(github, root)
    if current != validate_adoption_plan(approved):
        raise ExecutionAdoptionError("Issue/ADC/Phase/PR/base/head/branch/CI/workspace drifted; replan and reapprove")
    _validate_local_adoption_artifacts(root, current, allow_recovery=True)
    return current


def _revalidate_before_adoption_write(github: Any, root: Path, plan: dict[str, Any],
                                      owner_plan: dict[str, Any], decision_comment_id: int) -> None:
    _current_plan_matches(github, root, plan)
    try:
        current_owner_plan = create_authorization_plan(
            github, root, operation="EXECUTION_ADOPTION", subject_sha256=plan["plan_sha256"],
            issue_number=ISSUE_NUMBER, target_issue_number=ISSUE_NUMBER, pr_number=PR_NUMBER,
            pr_head_sha40=plan["observed_start_head_sha40"], details=_owner_details(plan),
        )
    except OwnerAuthorizationError as exc:
        raise ExecutionAdoptionError(f"exact Owner plan could not be revalidated before adoption write: {exc}") from exc
    if current_owner_plan != owner_plan:
        raise ExecutionAdoptionError("Owner authorization scope changed before adoption write")
    decision = _live_owner_decision(github, plan, owner_plan)
    if decision.comment_id != decision_comment_id:
        raise ExecutionAdoptionError("exact Owner decision changed before adoption write")


def _journal_payload(plan: dict[str, Any], owner_plan: dict[str, Any], decision_comment_id: int,
                     executor_user_id: int, *, phase: str, intent_comment_id: int | None = None,
                     intent_body_sha256: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": INTENT_SCHEMA if phase == "intent" else APPLIED_SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "owner_id": OWNER_ID,
        "executor_user_id": executor_user_id,
        "issue_number": ISSUE_NUMBER,
        "pr_number": PR_NUMBER,
        "adc_comment_id": plan["adc_comment_id"],
        "adc_sha256": plan["adc_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "owner_authorization_plan_sha256": owner_plan["plan_sha256"],
        "approval_scope_sha256": owner_plan["approval_scope_sha256"],
        "owner_decision_comment_id": decision_comment_id,
        "adoption_id": plan["adoption_id"],
        "operation_id": plan["adoption_id"],
        "selected_base_ref": plan["selected_base_ref"],
        "selected_base_sha40": plan["selected_base_sha40"],
        "branch_ref": plan["branch_ref"],
        "observed_start_head_sha40": plan["observed_start_head_sha40"],
        "historical_binding_provenance": "UNVERIFIED",
        "attachment_id": plan["attachment_id"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if phase == "applied":
        value["intent_comment_id"] = intent_comment_id
        value["intent_body_sha256"] = intent_body_sha256
    return value


def _validate_journal_record(record: tuple[int, str, dict[str, Any], tuple[Any, ...]], *,
                             schema: str, plan: dict[str, Any], owner_plan: dict[str, Any],
                             decision_comment_id: int, executor_user_id: int,
                             intent_record: tuple[int, str, dict[str, Any], tuple[Any, ...]] | None = None) -> None:
    comment_id, actual_schema, payload, fingerprint = record
    expected = _journal_payload(
        plan, owner_plan, decision_comment_id, executor_user_id,
        phase="intent" if schema == INTENT_SCHEMA else "applied",
        intent_comment_id=None if intent_record is None else intent_record[0],
        intent_body_sha256=None if intent_record is None else hashlib.sha256(
            _body(INTENT_SCHEMA, intent_record[2]).encode("utf-8")).hexdigest(),
    )
    actual_static = {key: value for key, value in payload.items() if key != "created_at"}
    expected_static = {key: value for key, value in expected.items() if key != "created_at"}
    if (actual_schema != schema or actual_static != expected_static
            or payload.get("created_at") != fingerprint[2]
            or fingerprint[3] != fingerprint[2]
            or fingerprint[4] != executor_user_id or comment_id <= 0):
        raise ExecutionAdoptionError("adoption journal record differs from the exact approved snapshot")
    if schema == INTENT_SCHEMA and comment_id <= decision_comment_id:
        raise ExecutionAdoptionError("adoption Intent must follow the exact Owner decision")
    if schema == APPLIED_SCHEMA and (
            intent_record is None or intent_record[0] <= decision_comment_id or comment_id <= intent_record[0]):
        raise ExecutionAdoptionError("adoption Applied must follow its exact Intent and Owner decision")
    _validate_journal_shape(payload, schema)
    if intent_record is not None and payload["intent_comment_id"] != intent_record[0]:
        raise ExecutionAdoptionError("adoption Applied record does not reference the exact Intent")


def _append_marker_once(github: Any, schema: str, payload: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
    expected_body = _body(schema, payload)
    history = _read_adoption_history(github)
    same_operation = [record for record in history if record[2].get("adoption_id") == payload.get("adoption_id")]
    same_schema = [record for record in same_operation if record[1] == schema]
    if len(same_schema) > 1:
        raise ExecutionAdoptionError("adoption journal record is duplicated")
    matches = [record for record in same_schema
               if {key: value for key, value in record[2].items() if key != "created_at"}
               == {key: value for key, value in payload.items() if key != "created_at"}]
    if same_schema and not matches:
        raise ExecutionAdoptionError("adoption operation ID already has conflicting journal bytes")
    if len(matches) > 1:
        raise ExecutionAdoptionError("adoption journal record is duplicated")
    if matches:
        comment_id, _schema, _payload, _fingerprint = matches[0]
        body_sha = hashlib.sha256(_fingerprint[1].encode("utf-8")).hexdigest()
        return comment_id, body_sha, matches[0][2]
    if schema == INTENT_SCHEMA and history:
        raise ExecutionAdoptionError("a different adoption journal already exists; refusing a second adoption")
    if schema == APPLIED_SCHEMA:
        intents = [record for record in history if record[1] == INTENT_SCHEMA]
        if len(intents) != 1 or payload.get("intent_comment_id") != intents[0][0]:
            raise ExecutionAdoptionError("Applied record requires the exact previously read Intent")
    try:
        github.create_issue_comment(ISSUE_NUMBER, expected_body)
    except GitHubError as exc:
        # Resolve ambiguous responses through exact operation-ID reads only.
        recovered = _read_adoption_history(github)
        matches = [record for record in recovered if record[1] == schema and record[2] == payload]
        if len(matches) != 1:
            raise ExecutionAdoptionError("adoption comment POST is ambiguous; no retry was attempted") from exc
        comment_id = matches[0][0]
    else:
        recovered = _read_adoption_history(github)
        matches = [record for record in recovered if record[1] == schema and record[2] == payload]
        if len(matches) != 1:
            raise ExecutionAdoptionError("adoption comment did not read back exactly once")
        comment_id = matches[0][0]
    matched = next(record for record in recovered if record[0] == comment_id and record[1] == schema)
    return comment_id, hashlib.sha256(matched[3][1].encode("utf-8")).hexdigest(), matched[2]


def read_adopted_epoch(root: Path, issue_number: int = ISSUE_NUMBER) -> AdoptedExecutionEpoch:
    path = adoption_path(root, issue_number)
    if path_has_symlink(path):
        raise ExecutionAdoptionError("adopted epoch path traverses a symbolic link")
    try:
        return AdoptedExecutionEpoch.from_bytes(path.read_bytes())
    except (OSError, ExecutionError) as exc:
        raise ExecutionAdoptionError(f"adopted epoch is missing or invalid: {exc}") from exc


def read_workspace_attachment(root: Path, issue_number: int = ISSUE_NUMBER) -> WorkspaceAttachment:
    path = attachment_path(root, issue_number)
    if path_has_symlink(path):
        raise ExecutionAdoptionError("workspace attachment path traverses a symbolic link")
    try:
        return WorkspaceAttachment.from_bytes(path.read_bytes())
    except (OSError, ExecutionError) as exc:
        raise ExecutionAdoptionError(f"workspace attachment is missing or invalid: {exc}") from exc


def read_execution_identity(github: Any, root: Path, *, adc_comment_id: int,
                            adc_sha256: str) -> Any:
    """Read a normal V1 binding or verify the explicit one-time adopted epoch."""
    path = execution_binding_path(Path(root), ISSUE_NUMBER)
    if path.exists() or path.is_symlink():
        if (adoption_path(root).exists() or adoption_path(root).is_symlink()
                or attachment_path(root).exists() or attachment_path(root).is_symlink()):
            raise ExecutionAdoptionError("normal ExecutionBinding and adopted epoch artifacts conflict")
        try:
            binding = read_binding(path)
        except ExecutionError as exc:
            raise ExecutionAdoptionError(f"normal ExecutionBinding exists but is invalid: {exc}") from exc
        if (binding.repository != REPOSITORY or binding.issue_number != ISSUE_NUMBER
                or binding.adc_comment_id != adc_comment_id or binding.adc_sha256 != adc_sha256
                or Path(binding.work_directory).resolve() != Path(root).resolve()):
            raise ExecutionAdoptionError("normal ExecutionBinding does not match the current Issue/ADC/worktree")
        return binding
    verified = verify_adopted_execution(
        github, root, expected_adc_comment_id=adc_comment_id, expected_adc_sha256=adc_sha256,
    )
    return verified["epoch"]


def _create_local(path: Path, data: bytes, label: str) -> None:
    if path.exists() or path.is_symlink() or path_has_symlink(path):
        if path.is_symlink() or path.read_bytes() != data:
            raise ExecutionAdoptionError(f"{label} already exists with conflicting bytes")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise ExecutionAdoptionError(f"{label} raced with conflicting bytes")
    except OSError as exc:
        raise ExecutionAdoptionError(f"could not persist {label}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    if path.read_bytes() != data:
        raise ExecutionAdoptionError(f"{label} readback changed")


def apply_adoption(github: Any, root: Path, adoption_plan: dict[str, Any], owner_plan: dict[str, Any]) -> dict[str, Any]:
    """Append or recover the exact authorized adoption, then persist local typed evidence."""
    plan = validate_adoption_plan(adoption_plan)
    root = Path(root).resolve()
    try:
        owner_plan = _validate_owner_authorization_plan(owner_plan)
    except OwnerAuthorizationError as exc:
        raise ExecutionAdoptionError(f"Owner authorization plan is invalid: {exc}") from exc
    if (owner_plan.get("operation") != "EXECUTION_ADOPTION"
            or owner_plan.get("subject_sha256") != plan["plan_sha256"]
            or owner_plan.get("target_issue_number") != ISSUE_NUMBER
            or owner_plan.get("pr_number") != PR_NUMBER
            or owner_plan.get("pr_head_sha40") != plan["observed_start_head_sha40"]
            or owner_plan.get("details") != _owner_details(plan)):
        raise ExecutionAdoptionError("Owner authorization plan does not bind the complete adoption plan")
    complete_local_adoption = all(path.is_file() and not path.is_symlink() for path in (
        adoption_plan_path(root), adoption_path(root), attachment_path(root),
        _pr_binding_version_path(root, ISSUE_NUMBER, 1), checkpoint_path(root, ISSUE_NUMBER, 1),
    ))
    if complete_local_adoption:
        _validate_local_adoption_artifacts(root, plan, allow_recovery=True)
        verified = verify_adopted_execution(
            github, root, expected_adc_comment_id=plan["adc_comment_id"],
            expected_adc_sha256=plan["adc_sha256"],
        )
        epoch = verified["epoch"]
        if (epoch.plan_sha256 != plan["plan_sha256"]
                or epoch.owner_authorization_plan_sha256 != owner_plan["plan_sha256"]
                or epoch.approval_scope_sha256 != owner_plan["approval_scope_sha256"]):
            raise ExecutionAdoptionError("existing adopted epoch belongs to a different exact authorization")
        return {
            "status": "ADOPTED", "repository": REPOSITORY, "issue": ISSUE_NUMBER, "pr": PR_NUMBER,
            "adoption_id": epoch.adoption_id, "adoption_plan_sha256": epoch.plan_sha256,
            "owner_authorization_plan_sha256": epoch.owner_authorization_plan_sha256,
            "owner_decision_comment_id": epoch.owner_decision_comment_id,
            "intent_comment_id": epoch.intent_comment_id, "applied_comment_id": epoch.applied_comment_id,
            "epoch_sha256": epoch.sha256, "current_head_sha40": verified["current_head_sha40"],
            "historical_binding_provenance": "UNVERIFIED", "writes_performed": 0,
            "evidence_refs": [str(adoption_plan_path(root)), str(adoption_path(root)),
                              str(attachment_path(root)),
                              str(_pr_binding_version_path(root, ISSUE_NUMBER, 1)),
                              str(checkpoint_path(root, ISSUE_NUMBER, 1))],
        }
    _current_plan_matches(github, root, plan)
    try:
        refreshed_owner_plan = create_authorization_plan(
            github, root, operation="EXECUTION_ADOPTION", subject_sha256=plan["plan_sha256"],
            issue_number=ISSUE_NUMBER, target_issue_number=ISSUE_NUMBER, pr_number=PR_NUMBER,
            pr_head_sha40=plan["observed_start_head_sha40"], details=_owner_details(plan),
        )
    except OwnerAuthorizationError as exc:
        raise ExecutionAdoptionError(f"exact Owner plan could not be refreshed: {exc}") from exc
    if refreshed_owner_plan != owner_plan:
        raise ExecutionAdoptionError("Owner authorization plan or source HEAD changed; regenerate and reapprove")
    decision = _live_owner_decision(github, plan, owner_plan)
    actor = github.authenticated_user()
    if (not isinstance(actor, dict) or actor.get("type") != "User" or not _positive(actor.get("id"))):
        raise ExecutionAdoptionError("adoption executor lacks an authenticated GitHub User identity")
    history = _read_adoption_history(github)
    if len(history) > 2:
        raise ExecutionAdoptionError("adoption journal contains extra or duplicate records")
    intent_rows = [row for row in history if row[1] == INTENT_SCHEMA]
    applied_rows = [row for row in history if row[1] == APPLIED_SCHEMA]
    if len(intent_rows) > 1 or len(applied_rows) > 1:
        raise ExecutionAdoptionError("adoption journal contains duplicate Intent or Applied records")
    if any(row[2].get("adoption_id") != plan["adoption_id"] for row in history):
        raise ExecutionAdoptionError("a different adoption operation already exists")
    if applied_rows and not intent_rows:
        raise ExecutionAdoptionError("adoption Applied record has no Intent predecessor")
    local_complete = all(path.is_file() and not path.is_symlink() for path in (
        adoption_plan_path(root), adoption_path(root), attachment_path(root),
        _pr_binding_version_path(root, ISSUE_NUMBER, 1), checkpoint_path(root, ISSUE_NUMBER, 1),
    ))
    if len(intent_rows) == 1 and len(applied_rows) == 1 and local_complete:
        verified = verify_adopted_execution(
            github, root, expected_adc_comment_id=plan["adc_comment_id"],
            expected_adc_sha256=plan["adc_sha256"],
        )
        epoch = verified["epoch"]
        return {
            "status": "ADOPTED", "repository": REPOSITORY, "issue": ISSUE_NUMBER, "pr": PR_NUMBER,
            "adoption_id": epoch.adoption_id, "adoption_plan_sha256": epoch.plan_sha256,
            "owner_authorization_plan_sha256": epoch.owner_authorization_plan_sha256,
            "owner_decision_comment_id": epoch.owner_decision_comment_id,
            "intent_comment_id": epoch.intent_comment_id, "applied_comment_id": epoch.applied_comment_id,
            "epoch_sha256": epoch.sha256, "current_head_sha40": verified["current_head_sha40"],
            "historical_binding_provenance": "UNVERIFIED", "writes_performed": 0,
            "evidence_refs": [str(adoption_plan_path(root)), str(adoption_path(root)),
                              str(attachment_path(root)),
                              str(_pr_binding_version_path(root, ISSUE_NUMBER, 1)),
                              str(checkpoint_path(root, ISSUE_NUMBER, 1))],
        }
    intent_id: int | None = None
    intent_sha: str | None = None
    if intent_rows:
        intent_id, _schema, existing_intent, _fingerprint = intent_rows[0]
        intent_record = intent_rows[0]
        _validate_journal_record(intent_record, schema=INTENT_SCHEMA, plan=plan, owner_plan=owner_plan,
                                 decision_comment_id=decision.comment_id, executor_user_id=actor["id"])
        intent_sha = hashlib.sha256(_body(INTENT_SCHEMA, existing_intent).encode("utf-8")).hexdigest()
    else:
        _revalidate_before_adoption_write(github, root, plan, owner_plan, decision.comment_id)
        payload = _journal_payload(plan, owner_plan, decision.comment_id, actor["id"], phase="intent")
        intent_id, intent_sha, existing_intent = _append_marker_once(github, INTENT_SCHEMA, payload)
        intent_record = next(row for row in _read_adoption_history(github) if row[0] == intent_id)
    _current_plan_matches(github, root, plan)
    if applied_rows:
        applied_id, _schema, applied_payload, _fingerprint = applied_rows[0]
        applied_record = applied_rows[0]
        _validate_journal_record(applied_record, schema=APPLIED_SCHEMA, plan=plan, owner_plan=owner_plan,
                                 decision_comment_id=decision.comment_id, executor_user_id=actor["id"],
                                 intent_record=intent_record)
    else:
        _revalidate_before_adoption_write(github, root, plan, owner_plan, decision.comment_id)
        payload = _journal_payload(plan, owner_plan, decision.comment_id, actor["id"], phase="applied",
                                   intent_comment_id=intent_id, intent_body_sha256=intent_sha)
        applied_id, applied_sha, applied_payload = _append_marker_once(github, APPLIED_SCHEMA, payload)
        applied_record = next(row for row in _read_adoption_history(github) if row[0] == applied_id)
        _validate_journal_record(applied_record, schema=APPLIED_SCHEMA, plan=plan, owner_plan=owner_plan,
                                 decision_comment_id=decision.comment_id, executor_user_id=actor["id"],
                                 intent_record=intent_record)
    # Verify the complete remote journal again after the last append.
    final_history = _read_adoption_history(github)
    if len(final_history) != 2 or [row[1] for row in final_history] != [INTENT_SCHEMA, APPLIED_SCHEMA]:
        raise ExecutionAdoptionError("adoption journal final readback is incomplete or out of order")
    intent_record, applied_record = final_history
    _validate_journal_record(intent_record, schema=INTENT_SCHEMA, plan=plan, owner_plan=owner_plan,
                             decision_comment_id=decision.comment_id, executor_user_id=actor["id"])
    _validate_journal_record(applied_record, schema=APPLIED_SCHEMA, plan=plan, owner_plan=owner_plan,
                             decision_comment_id=decision.comment_id, executor_user_id=actor["id"],
                             intent_record=intent_record)
    epoch = AdoptedExecutionEpoch(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, adc_comment_id=plan["adc_comment_id"],
        adc_sha256=plan["adc_sha256"], pr_number=PR_NUMBER,
        pr_author_user_id=plan["pr_author_user_id"],
        selected_base_ref=plan["selected_base_ref"], selected_base_sha40=plan["selected_base_sha40"],
        branch_ref=plan["branch_ref"], observed_start_head_sha40=plan["observed_start_head_sha40"],
        adoption_id=plan["adoption_id"], plan_sha256=plan["plan_sha256"],
        owner_decision_comment_id=decision.comment_id,
        owner_authorization_plan_sha256=owner_plan["plan_sha256"],
        approval_scope_sha256=owner_plan["approval_scope_sha256"],
        intent_comment_id=intent_record[0], applied_comment_id=applied_record[0],
        intent_body_sha256=hashlib.sha256(_body(INTENT_SCHEMA, intent_record[2]).encode("utf-8")).hexdigest(),
        applied_body_sha256=hashlib.sha256(_body(APPLIED_SCHEMA, applied_record[2]).encode("utf-8")).hexdigest(),
        attachment_id=plan["attachment_id"],
    ).validate()
    root_path = root
    attachment = WorkspaceAttachment(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, adoption_id=epoch.adoption_id,
        attachment_id=epoch.attachment_id, branch_ref=epoch.branch_ref,
        work_directory=str(root_path),
    ).validate()
    _create_local(adoption_plan_path(root_path), adoption_plan_bytes(plan), "adoption plan snapshot")
    _create_local(adoption_path(root_path), epoch.to_bytes(), "adopted epoch")
    _create_local(attachment_path(root_path), attachment.to_bytes(), "workspace attachment")
    current_head = head_sha40(root_path)
    pr_binding = PRBinding(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER,
        adc_comment_id=epoch.adc_comment_id, adc_sha256=epoch.adc_sha256,
        base_sha40=epoch.selected_base_sha40, branch_ref=epoch.branch_ref,
        pr_number=epoch.pr_number, pr_head_sha40=current_head,
        adoption_id=epoch.adoption_id,
    ).validate()
    binding_file = _pr_binding_version_path(root_path, ISSUE_NUMBER, 1)
    write_pr_binding(binding_file, pr_binding)
    checkpoint = WorkCheckpoint(
        execution_binding_sha256=None, current_head_sha40=current_head,
        worktree_clean=worktree_clean(root_path), completed_stage="adoption",
        artifact_digests=tuple(sorted((
            ("adopted-epoch", epoch.sha256), ("owner-decision", decision.body_sha256),
            ("pr-binding", pr_binding.sha256), ("workspace-attachment", attachment.sha256),
        ))), step=1, execution_adoption_sha256=epoch.sha256,
    ).validate()
    checkpoint_file = checkpoint_path(root_path, ISSUE_NUMBER, checkpoint.step)
    write_checkpoint(checkpoint_file, checkpoint)
    verified = verify_adopted_execution(github, root_path, expected_adc_comment_id=epoch.adc_comment_id,
                                        expected_adc_sha256=epoch.adc_sha256)
    return {
        "status": "ADOPTED", "repository": REPOSITORY, "issue": ISSUE_NUMBER, "pr": PR_NUMBER,
        "adoption_id": epoch.adoption_id, "adoption_plan_sha256": epoch.plan_sha256,
        "owner_authorization_plan_sha256": epoch.owner_authorization_plan_sha256,
        "owner_decision_comment_id": epoch.owner_decision_comment_id,
        "intent_comment_id": epoch.intent_comment_id, "applied_comment_id": epoch.applied_comment_id,
        "epoch_sha256": epoch.sha256, "attachment_sha256": attachment.sha256,
        "pr_binding_sha256": pr_binding.sha256, "checkpoint_sha256": checkpoint.sha256,
        "observed_start_head_sha40": epoch.observed_start_head_sha40,
        "current_head_sha40": verified["current_head_sha40"],
        "selected_base_ref": epoch.selected_base_ref, "selected_base_sha40": epoch.selected_base_sha40,
        "historical_binding_provenance": "UNVERIFIED",
        "evidence_refs": [str(adoption_plan_path(root_path)), str(adoption_path(root_path)), str(attachment_path(root_path)),
                          str(binding_file), str(checkpoint_file),
                          f"issue-comment:{epoch.intent_comment_id}", f"issue-comment:{epoch.applied_comment_id}"]
    }


def append_adopted_pr_binding(github: Any, root: Path, *,
                              expected_adc_comment_id: int, expected_adc_sha256: str) -> dict[str, Any]:
    """Append a fresh PRBinding after a legitimate forward-only post-adoption commit."""
    root = Path(root).resolve()
    epoch = read_adopted_epoch(root)
    try:
        stored_plan = read_adoption_plan(adoption_plan_path(root))
    except ExecutionAdoptionError as exc:
        raise ExecutionAdoptionError("complete immutable adoption plan snapshot is missing or invalid") from exc
    if (stored_plan["plan_sha256"] != epoch.plan_sha256
            or stored_plan["adoption_id"] != epoch.adoption_id
            or stored_plan["adc_comment_id"] != epoch.adc_comment_id
            or stored_plan["adc_sha256"] != epoch.adc_sha256
            or stored_plan["pr_number"] != epoch.pr_number
            or stored_plan["pr_author_user_id"] != epoch.pr_author_user_id
            or stored_plan["selected_base_ref"] != epoch.selected_base_ref
            or stored_plan["selected_base_sha40"] != epoch.selected_base_sha40
            or stored_plan["branch_ref"] != epoch.branch_ref
            or stored_plan["observed_start_head_sha40"] != epoch.observed_start_head_sha40
            or stored_plan["attachment_id"] != epoch.attachment_id):
        raise ExecutionAdoptionError("immutable adoption plan differs from the typed adopted epoch")
    attachment = read_workspace_attachment(root)
    if (attachment.adoption_id != epoch.adoption_id or attachment.attachment_id != epoch.attachment_id
            or Path(attachment.work_directory).resolve() != root
            or _attachment_id(root, epoch.branch_ref) != epoch.attachment_id):
        raise ExecutionAdoptionError("current worktree is not the original adopted workspace attachment")
    if (epoch.adc_comment_id != expected_adc_comment_id or epoch.adc_sha256 != expected_adc_sha256):
        raise ExecutionAdoptionError("adopted epoch is stale for the current approved ADC")
    try:
        current_adc = verify_adc(github, ISSUE_NUMBER)
        if current_adc.pointer.comment_id != epoch.adc_comment_id or current_adc.pointer.sha256 != epoch.adc_sha256:
            raise ExecutionAdoptionError("approved ADC changed after adoption")
        decision = read_verified_owner_decision(
            github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID, operation="EXECUTION_ADOPTION",
            subject_sha256=epoch.plan_sha256, expected_pr_number=PR_NUMBER,
            expected_pr_head_sha40=epoch.observed_start_head_sha40,
            expected_plan_sha256=epoch.owner_authorization_plan_sha256,
            repository_id=REPOSITORY_ID, expected_approval_scope_sha256=epoch.approval_scope_sha256,
            expected_schema=SCHEMA_V3,
        )
        history = _read_adoption_history(github)
    except (ADCError, OwnerDecisionError) as exc:
        raise ExecutionAdoptionError(f"adopted epoch authority could not be revalidated: {exc}") from exc
    if decision.comment_id != epoch.owner_decision_comment_id or len(history) != 2:
        raise ExecutionAdoptionError("adopted epoch owner decision or append-only journal differs")
    executor_id = history[0][2].get("executor_user_id")
    journal_plan = {
        "adc_comment_id": epoch.adc_comment_id, "adc_sha256": epoch.adc_sha256,
        "plan_sha256": epoch.plan_sha256, "adoption_id": epoch.adoption_id,
        "selected_base_ref": epoch.selected_base_ref, "selected_base_sha40": epoch.selected_base_sha40,
        "branch_ref": epoch.branch_ref, "observed_start_head_sha40": epoch.observed_start_head_sha40,
        "attachment_id": epoch.attachment_id,
    }
    journal_owner = {"plan_sha256": epoch.owner_authorization_plan_sha256,
                     "approval_scope_sha256": epoch.approval_scope_sha256}
    if (history[0][0] != epoch.intent_comment_id or history[1][0] != epoch.applied_comment_id
            or hashlib.sha256(_body(INTENT_SCHEMA, history[0][2]).encode("utf-8")).hexdigest()
               != epoch.intent_body_sha256
            or hashlib.sha256(_body(APPLIED_SCHEMA, history[1][2]).encode("utf-8")).hexdigest()
               != epoch.applied_body_sha256):
        raise ExecutionAdoptionError("adoption history differs from its immutable local epoch")
    _validate_journal_record(history[0], schema=INTENT_SCHEMA, plan=journal_plan, owner_plan=journal_owner,
                             decision_comment_id=decision.comment_id, executor_user_id=executor_id)
    _validate_journal_record(history[1], schema=APPLIED_SCHEMA, plan=journal_plan, owner_plan=journal_owner,
                             decision_comment_id=decision.comment_id, executor_user_id=executor_id,
                             intent_record=history[0])
    try:
        issue = github.issue(ISSUE_NUMBER)
        if (issue.get("number") != ISSUE_NUMBER or issue.get("state") != "open"
                or issue.get("repository_url") != f"https://api.github.com/repos/{REPOSITORY}"):
            raise ExecutionAdoptionError("Issue #63 is not the exact open adopted Issue")
        branch = current_branch(root)
        current_head = head_sha40(root)
        if (not worktree_clean(root) or branch != epoch.branch_ref
                or remote_branch_sha(root, branch) != current_head
                or not is_ancestor(root, epoch.observed_start_head_sha40, current_head)
                or not is_ancestor(root, epoch.selected_base_sha40, current_head)):
            raise ExecutionAdoptionError("post-adoption worktree is dirty or is not a forward-only PR continuation")
        pull, base_ref, current_base, head_ref, pr_head, author_id = _pull_identity(github)
        if (pull.get("id") != stored_plan["pr_id"] or pull.get("number") != PR_NUMBER
                or base_ref != epoch.selected_base_ref
                or head_ref != epoch.branch_ref or pr_head != current_head
                or author_id != epoch.pr_author_user_id):
            raise ExecutionAdoptionError("live PR #64 does not match the exact adopted worktree")
        bindings = read_pr_binding_history(root, ISSUE_NUMBER, github=github)
        if not bindings:
            raise WorkError("adopted PRBinding history is missing")
        previous = bindings[-1][1]
        if (previous.adoption_id != epoch.adoption_id or previous.repository != REPOSITORY
                or previous.issue_number != ISSUE_NUMBER or previous.pr_number != PR_NUMBER
                or previous.adc_comment_id != epoch.adc_comment_id or previous.adc_sha256 != epoch.adc_sha256
                or previous.base_sha40 != epoch.selected_base_sha40 or previous.branch_ref != epoch.branch_ref
                or not is_ancestor(root, previous.pr_head_sha40, current_head)):
            raise ExecutionAdoptionError("latest immutable PRBinding does not precede the current adopted PR HEAD")
        evidence = None
        if current_base != epoch.selected_base_sha40:
            profile = load_profile(root)
            if profile.activation_issue_number is None:
                raise ExecutionAdoptionError("forward PR base requires the configured Activation proof")
            try:
                from .current_base import verify_current_base_advance
                evidence = verify_current_base_advance(
                    root, github, repository=REPOSITORY, issue_number=ISSUE_NUMBER,
                    execution_binding=epoch, prior_pr_binding=previous, current_pr=pull,
                    activation_issue_number=profile.activation_issue_number,
                )
            except (CurrentBaseError, ProfileError, GitHubError, GitError) as exc:
                raise ExecutionAdoptionError(f"PR base drift is not the exact Activation transition: {exc}") from exc
        elif previous.current_base_sha40 is not None:
            raise ExecutionAdoptionError("PR base reverted after an Activation transition")
    except (GitError, GitHubError, WorkError, ProfileError) as exc:
        raise ExecutionAdoptionError(f"adopted PR continuation readback failed: {exc}") from exc
    new_binding = PRBinding(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER,
        adc_comment_id=epoch.adc_comment_id, adc_sha256=epoch.adc_sha256,
        base_sha40=epoch.selected_base_sha40, branch_ref=epoch.branch_ref,
        pr_number=PR_NUMBER, pr_head_sha40=current_head,
        current_base_sha40=None if evidence is None else evidence.current_base_sha40,
        current_base_advance_sha256=None if evidence is None else evidence.sha256,
        adoption_id=epoch.adoption_id,
    ).validate()
    if previous != new_binding:
        try:
            from .work import _verify_pr_binding_successor
            _verify_pr_binding_successor(github, ISSUE_NUMBER, previous, new_binding,
                                         current_base_evidence=evidence)
        except WorkError as exc:
            raise ExecutionAdoptionError(f"adopted PRBinding successor is invalid: {exc}") from exc
        version = len(bindings) + 1
        write_pr_binding(_pr_binding_version_path(root, ISSUE_NUMBER, version), new_binding)
        checkpoint_row = latest_checkpoint(root, ISSUE_NUMBER)
        step = 1 if checkpoint_row is None else checkpoint_row[1].step + 1
        artifacts = (("adopted-epoch", epoch.sha256), ("pr-binding", new_binding.sha256))
        checkpoint = WorkCheckpoint(
            execution_binding_sha256=None, execution_adoption_sha256=epoch.sha256,
            current_head_sha40=current_head, worktree_clean=True, completed_stage="pr",
            artifact_digests=tuple(sorted(artifacts)), step=step,
        ).validate()
        write_checkpoint(checkpoint_path(root, ISSUE_NUMBER, step), checkpoint)
    return verify_adopted_execution(
        github, root, expected_adc_comment_id=epoch.adc_comment_id,
        expected_adc_sha256=epoch.adc_sha256,
    ) | {"status": "PR_BINDING_CURRENT" if previous == new_binding else "PR_BINDING_ADVANCED"}


def verify_adopted_execution(
    github: Any, root: Path, *, expected_adc_comment_id: int, expected_adc_sha256: str,
) -> dict[str, Any]:
    """Revalidate local epoch/attachment, exact remote journal and owner decision."""
    root = Path(root).resolve()
    epoch = read_adopted_epoch(root)
    try:
        stored_plan = read_adoption_plan(adoption_plan_path(root))
    except ExecutionAdoptionError as exc:
        raise ExecutionAdoptionError("complete immutable adoption plan snapshot is missing or invalid") from exc
    if (stored_plan["plan_sha256"] != epoch.plan_sha256
            or stored_plan["adoption_id"] != epoch.adoption_id
            or stored_plan["adc_comment_id"] != epoch.adc_comment_id
            or stored_plan["adc_sha256"] != epoch.adc_sha256
            or stored_plan["pr_number"] != epoch.pr_number
            or stored_plan["pr_author_user_id"] != epoch.pr_author_user_id
            or stored_plan["selected_base_ref"] != epoch.selected_base_ref
            or stored_plan["selected_base_sha40"] != epoch.selected_base_sha40
            or stored_plan["branch_ref"] != epoch.branch_ref
            or stored_plan["observed_start_head_sha40"] != epoch.observed_start_head_sha40
            or stored_plan["attachment_id"] != epoch.attachment_id):
        raise ExecutionAdoptionError("immutable adoption plan differs from the typed adopted epoch")
    attachment = read_workspace_attachment(root)
    if (attachment.repository != epoch.repository or attachment.issue_number != epoch.issue_number
            or attachment.adoption_id != epoch.adoption_id or attachment.attachment_id != epoch.attachment_id
            or attachment.branch_ref != epoch.branch_ref or Path(attachment.work_directory).resolve() != root
            or _attachment_id(root, epoch.branch_ref) != epoch.attachment_id):
        raise ExecutionAdoptionError("current workspace is not the authenticated adopted-epoch attachment")
    if (epoch.adc_comment_id != expected_adc_comment_id or epoch.adc_sha256 != expected_adc_sha256):
        raise ExecutionAdoptionError("adopted epoch is stale for the current approved ADC")
    binding_path = root / ".p_ases" / "state" / str(ISSUE_NUMBER) / "execution-binding.json"
    if (adoption_path(root).is_symlink() or attachment_path(root).is_symlink()
            or adoption_plan_path(root).is_symlink()
            or binding_path.exists() or binding_path.is_symlink()):
        raise ExecutionAdoptionError("normal and adopted execution identities conflict")
    history = _read_adoption_history(github)
    if (len(history) != 2 or history[0][1] != INTENT_SCHEMA or history[1][1] != APPLIED_SCHEMA
            or history[0][0] != epoch.intent_comment_id or history[1][0] != epoch.applied_comment_id
            or hashlib.sha256(_body(INTENT_SCHEMA, history[0][2]).encode("utf-8")).hexdigest()
               != epoch.intent_body_sha256
            or hashlib.sha256(_body(APPLIED_SCHEMA, history[1][2]).encode("utf-8")).hexdigest()
               != epoch.applied_body_sha256):
        raise ExecutionAdoptionError("remote adopted-epoch journal does not match the local immutable epoch")
    executor_id = history[0][2].get("executor_user_id")
    journal_plan = {
        "adc_comment_id": epoch.adc_comment_id, "adc_sha256": epoch.adc_sha256,
        "plan_sha256": epoch.plan_sha256, "adoption_id": epoch.adoption_id,
        "selected_base_ref": epoch.selected_base_ref, "selected_base_sha40": epoch.selected_base_sha40,
        "branch_ref": epoch.branch_ref, "observed_start_head_sha40": epoch.observed_start_head_sha40,
        "attachment_id": epoch.attachment_id,
    }
    journal_owner_plan = {
        "plan_sha256": epoch.owner_authorization_plan_sha256,
        "approval_scope_sha256": epoch.approval_scope_sha256,
    }
    _validate_journal_record(history[0], schema=INTENT_SCHEMA, plan=journal_plan,
                             owner_plan=journal_owner_plan,
                             decision_comment_id=epoch.owner_decision_comment_id,
                             executor_user_id=executor_id)
    _validate_journal_record(history[1], schema=APPLIED_SCHEMA, plan=journal_plan,
                             owner_plan=journal_owner_plan,
                             decision_comment_id=epoch.owner_decision_comment_id,
                             executor_user_id=executor_id, intent_record=history[0])
    try:
        decision = read_verified_owner_decision(
            github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID, operation="EXECUTION_ADOPTION",
            subject_sha256=epoch.plan_sha256, expected_pr_number=PR_NUMBER,
            expected_pr_head_sha40=epoch.observed_start_head_sha40,
            expected_plan_sha256=epoch.owner_authorization_plan_sha256,
            repository_id=REPOSITORY_ID, expected_approval_scope_sha256=epoch.approval_scope_sha256,
            expected_schema=SCHEMA_V3,
        )
    except OwnerDecisionError as exc:
        raise ExecutionAdoptionError(f"adopted epoch Owner decision is invalid: {exc}") from exc
    if decision.comment_id != epoch.owner_decision_comment_id:
        raise ExecutionAdoptionError("local adopted epoch owner-decision ID differs from live history")
    issue = github.issue(ISSUE_NUMBER)
    metadata = github.repository_metadata()
    if (issue.get("number") != ISSUE_NUMBER or issue.get("state") != "open"
            or issue.get("repository_url") != f"https://api.github.com/repos/{REPOSITORY}"
            or metadata.get("id") != REPOSITORY_ID
            or not isinstance(metadata.get("owner"), dict)
            or metadata["owner"].get("id") != OWNER_ID):
        raise ExecutionAdoptionError("Issue #63 is no longer the open adopted execution Issue")
    try:
        branch = current_branch(root)
        current_head = head_sha40(root)
        remote_head = remote_branch_sha(root, epoch.branch_ref)
        if (not worktree_clean(root) or branch != epoch.branch_ref or remote_head != current_head
                or not is_ancestor(root, epoch.observed_start_head_sha40, current_head)):
            raise ExecutionAdoptionError("current worktree is not a forward continuation of the adopted HEAD")
        if not is_ancestor(root, epoch.selected_base_sha40, epoch.observed_start_head_sha40):
            raise ExecutionAdoptionError("adopted PR HEAD no longer proves ancestry from the selected base")
    except GitError as exc:
        raise ExecutionAdoptionError(f"adopted execution Git lineage is unavailable: {exc}") from exc
    pull, current_base_ref, current_base_sha, current_branch_ref, current_pr_head, author_id = _pull_identity(github)
    if (pull.get("id") != stored_plan["pr_id"] or current_base_ref != epoch.selected_base_ref
            or current_branch_ref != epoch.branch_ref):
        raise ExecutionAdoptionError("current PR base/head branch differs from the adopted epoch")
    if author_id != epoch.pr_author_user_id:
        raise ExecutionAdoptionError("current PR author differs from the exact approved adoption snapshot")
    if current_pr_head != current_head:
        raise ExecutionAdoptionError("current PR HEAD differs from the attached worktree")
    try:
        pr_history = read_pr_binding_history(root, ISSUE_NUMBER, github=github)
    except WorkError as exc:
        raise ExecutionAdoptionError(f"adopted PRBinding history is invalid: {exc}") from exc
    if not pr_history:
        raise ExecutionAdoptionError("adopted PRBinding is missing")
    latest_pr_binding = pr_history[-1][1]
    if (latest_pr_binding.adoption_id != epoch.adoption_id
            or latest_pr_binding.repository != REPOSITORY or latest_pr_binding.issue_number != ISSUE_NUMBER
            or latest_pr_binding.pr_number != PR_NUMBER or latest_pr_binding.adc_comment_id != epoch.adc_comment_id
            or latest_pr_binding.adc_sha256 != epoch.adc_sha256
            or latest_pr_binding.base_sha40 != epoch.selected_base_sha40
            or latest_pr_binding.branch_ref != epoch.branch_ref
            or latest_pr_binding.pr_head_sha40 != current_head):
        raise ExecutionAdoptionError("latest PRBinding does not authenticate this adopted epoch and exact PR HEAD")
    if current_base_sha != epoch.selected_base_sha40:
        try:
            if not is_ancestor(root, epoch.selected_base_sha40, current_base_sha):
                raise ExecutionAdoptionError("current PR base is not a forward successor of the adopted base")
            profile = load_profile(root)
            if profile.activation_issue_number is None:
                raise ExecutionAdoptionError("current PR base advanced without configured Activation evidence")
            from .current_base import (
                current_base_advance_path, read_current_base_advance, verify_current_base_advance,
            )
            evidence_path = current_base_advance_path(root, ISSUE_NUMBER)
            if not evidence_path.is_file():
                raise ExecutionAdoptionError("current PR base advanced without persisted Activation evidence")
            evidence = verify_current_base_advance(
                root, github, repository=REPOSITORY, issue_number=ISSUE_NUMBER,
                execution_binding=epoch, prior_pr_binding=latest_pr_binding, current_pr=pull,
                activation_issue_number=profile.activation_issue_number,
            )
            if (read_current_base_advance(evidence_path) != evidence
                    or evidence.current_base_sha40 != current_base_sha
                    or latest_pr_binding.current_base_sha40 != current_base_sha
                    or latest_pr_binding.current_base_advance_sha256 != evidence.sha256):
                raise ExecutionAdoptionError("current PR base does not match its exact Activation proof")
        except (CurrentBaseError, ProfileError, GitHubError, GitError) as exc:
            raise ExecutionAdoptionError(f"current PR base advance is not authenticated: {exc}") from exc
    elif latest_pr_binding.current_base_sha40 is not None:
        raise ExecutionAdoptionError("PRBinding carries a current-base proof although the PR base returned to its frozen SHA")
    return {"epoch": epoch, "attachment": attachment, "pr_binding": latest_pr_binding,
            "current_head_sha40": current_head, "current_base_sha40": current_base_sha,
            "pr": pull, "owner_decision": decision}
