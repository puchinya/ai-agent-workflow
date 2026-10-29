"""Namespace-based command-line interface for P-ASES."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from .adc import (
    ADCError, adc_forward_generation_session, parse_adc, publish_adc,
    refresh_adc_forward_generation_session, restore_adc, validate_approval_ready_adc,
    verify_adc, verify_adc_generation,
)
from .admin_auth import AdminAuthError, temporary_admin_client
from .owner_authorization import (
    OwnerAuthorizationError, authorize_chat_confirmed_plan, authorize_plan, create_authorization_plan,
    issue63_deferred_merge_details, read_authorization_plan, resume_authorization, write_authorization_plan,
)
from .owner_authorization import capture_direct_chat_confirmation
from .consumer_activation import (
    ConsumerActivationError, activation_checkpoint_path, activation_setting_inventory, read_activation_checkpoint,
    read_consumer_activation_history, verify_setup_pr_ready_to_merge, write_activation_checkpoint,
    setup_consumer_activation, verify_and_record_activation,
)
from .ruleset_management import (
    RulesetManagementError, apply_ruleset_plan, build_ruleset_plan, preflight as ruleset_preflight,
    read_plan as read_ruleset_plan, read_verified_managed_policy, write_plan as write_ruleset_plan,
)
from .git import GitError, current_branch, discover_repository, head_sha40, remote_branch_sha, worktree_clean
from .document_format import DocumentFormatError, format_tree
from .documents import DocumentError, validate_documents
from .github import GitHub, GitHubError, ReadOnlyGitHub
from .execution import (
    AdoptedExecutionEpoch, ExecutionError, ExecutionIdentity, binding_digest,
    execution_identity_base, execution_identity_context_id, execution_identity_digest, read_binding,
)
from .execution_adoption import (
    ExecutionAdoptionError, adoption_path, append_adopted_pr_binding, apply_adoption, build_adoption_plan,
    read_execution_identity, refresh_adopted_pr_binding, verify_adopted_execution,
    read_adoption_plan, write_adoption_plan,
)
from .checkpoint import CheckpointError, PRBinding, read_pr_binding
from .current_base import (
    CurrentBaseAdvanceEvidence, CurrentBaseError, current_base_advance_path,
    verify_current_base_advance,
)
from .context import WorkContext
from .profile import ProfileError, load_profile
from .gate_policy import (
    BOOTSTRAP_COHORT, BOOTSTRAP_ISSUES, BOOTSTRAP_POLICY, BOOTSTRAP_REPOSITORY,
    BootstrapResult, BootstrapSubject, GateSelection,
    GatePolicyError, bootstrap_policy_digest, choose_gate_for_new_issue, current_checkout_subject,
    evaluate_bootstrap,
    pin_gate_selection, publish_immutable_record, read_bootstrap_adc, read_bootstrap_evidence,
    read_gate_selection, read_latest_bootstrap_evidence,
    run_local_bootstrap_checks_bound,
    validate_bootstrap_pr_identity,
)
from .work import (
    WorkError, bind_work, ensure_branch, ensure_pull_request, execution_binding_path,
    closing_issue_references, parse_issue_association,
    pr_binding_path, recover_work,
)
from .audits import (
    AuditError, AuditItem, IndependentReview, IndependentReviewV2, ReviewFinding, SelfAudit,
    read_independent_review, read_self_audit, write_independent_review, write_self_audit,
)
from .delivery import (
    FinalDeliveryResult, PRReadback, ReadinessError, evaluate_final_delivery,
    evaluate_readiness, read_readiness, readiness_path, write_readiness,
)
from .acceptance import (
    ACCEPTANCE_POLICY_VERSION, ARTIFACT_TYPES, OBSERVATION_KINDS, AcceptanceError,
    AcceptanceObservation, AcceptanceResult, acceptance_result_path, evaluate_acceptance,
    read_acceptance_result, write_acceptance_result,
)
from .evidence_store import (
    EvidenceError, EvidenceRecord, VerificationSubject, evidence_path,
    read_evidence, read_evidence_set, write_evidence,
)
from .issue_graph import (
    IssueGraphError,
    load_split_plan,
    split_issue,
    validate_native_issue_graph,
    validate_split,
)
from .phase_evidence import (
    BOOTSTRAP_ISSUES as PHASE_EVIDENCE_BOOTSTRAP_ISSUES,
    PhaseEvidenceError,
    publish_phase_evidence,
    refresh_ready_phase_evidence,
    verify_ordinary_issue_context,
    verify_ready_preparation,
    verify_phase_evidence,
)
from .oracle_trace import (
    OracleDefinition, OracleTraceError, TestDefinition, validate_plan_oracles,
    validate_plan_tests,
)
from .phases import Attention, IssueKind, Phase, PhaseError, PhaseState, advance, parse_attention_labels, parse_phase_labels
from .verification import (
    GateResult, RequiredCheckPolicy, VerificationError, VerificationResult,
    build_verification_result, evaluate_required_checks, read_verification_result,
    required_check_fork_status, verification_result_path, write_verification_result,
)


def _validate_issue_advance_readback(issue: Any, *, original_issue: dict[str, Any],
                                    repository: str, issue_number: int,
                                    expected_labels: list[str], kind: IssueKind,
                                    target: Phase, attention: set[Any], ordinary: bool) -> None:
    """Require the post-write Issue to retain its identity and exact intended labels."""
    if not isinstance(issue, dict):
        raise CLIError("post-write Issue readback is not an object")
    expected_repository_url = f"https://api.github.com/repos/{repository}"
    repository_url = issue.get("repository_url")
    if (issue.get("number") != issue_number or issue.get("state") != "open"
            or issue.get("pull_request") is not None
            or not isinstance(repository_url, str)
            or repository_url.casefold() != expected_repository_url.casefold()
            or repository_url != original_issue.get("repository_url")
            or issue.get("body") != original_issue.get("body")):
        raise CLIError("Issue number, repository, PR identity, open state, or body changed after the label write")

    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CLIError("post-write Issue labels are malformed")
    names = [row.get("name") for row in rows]
    if (any(not isinstance(name, str) for name in names)
            or len(names) != len(set(names)) or set(names) != set(expected_labels)):
        raise CLIError("post-write Issue labels differ from the complete intended label set")
    if names.count(f"phase:{target.value}") != 1 or any(
            name.startswith("phase:") and name != f"phase:{target.value}" for name in names):
        raise CLIError("post-write Issue phase label does not match the requested transition")
    actual_kinds = [name for name in names if name.startswith("kind:")]
    if ordinary and actual_kinds != [f"kind:{kind.value}"]:
        raise CLIError("post-write Issue kind label changed during the phase transition")
    actual_attention = {name for name in names if name.startswith("attention:")}
    expected_attention = {f"attention:{item.value}" for item in attention}
    if actual_attention != expected_attention:
        raise CLIError("post-write Issue attention labels differ from the intended state")
from .verification_plan import (
    REQ_ID_PATTERN, PlanEntry, PlanError, VerificationPlan, create_plan, read_plan,
    verify_plan_sources,
)
from .path_safety import path_has_symlink
from .user_review import (
    FeedbackSnapshot, ParentFeedbackSnapshot, ParentReviewSubject,
    ParentUserReviewSession, UserReviewError, UserReviewResult, UserReviewSession, UserReviewSubject,
    capture_authenticated_chat_event, evaluate_parent_user_review, feedback_digest,
    feedback_snapshot_path, merge_feedback_history, merge_parent_feedback_history,
    normalize_github_feedback, parent_feedback_snapshot_path, parent_review_session_path,
    read_feedback_snapshot, read_parent_feedback_snapshot, read_parent_review_session,
    read_review_session, reject_unattested_chat_event, evaluate_user_review,
    review_session_path, write_feedback_snapshot, write_parent_feedback_snapshot,
    write_parent_review_session, write_review_session,
)
from .owner_consent import OwnerDecisionError, read_verified_owner_decision
from .phase_rebaseline import PhaseRebaselineError, rebaseline_issue_phase
from .user_review_relay import (
    UserReviewDecisionHistory, UserReviewRelayApproval, UserReviewRelayError,
    has_user_review_decision_marker, verify_user_review_decision_history,
)
from .integration import (
    IntegrationError, IntegrationGateEvidence, ParentGateEvidenceComment, evaluate_parent_integration,
)
from .parent_gate import (
    PARENT_ACCEPTANCE_STEPS, PARENT_ACCEPTANCE_WORKFLOW, PARENT_CI_WORKFLOW,
    PARENT_ISSUE_CONTRACT_COMMIT, PARENT_ISSUE_CONTRACT_SOURCE, PARENT_REQUIRED_CI_JOBS,
    PARENT_TRUSTED_ACTIONS_APP_ID, PARENT_VERIFICATION_STEPS,
    _check_run_id, _load_parent_gate_evidence_from_github, _parent_adc_authority,
    _parent_contract_declaration, _parent_current_main_sha, _parent_gate_bundle_from_actions,
    _parent_gate_comment_security_fingerprint, _repository_file_reference, _validate_parent_gate_bundle,
)


class CLIError(RuntimeError):
    pass


CLI_ADVANCE_TARGETS = tuple(
    phase.value for phase in Phase if phase not in {Phase.USER_REVIEW, Phase.CLOSED}
)

# The approved stacked-PR contract for this repository's Verification issue.
ISSUE_PR_REFS = {
    29: ("pases/adc-core", "pases/verification"),
    31: ("main", "pases/user-review-integration"),
}
def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _repo_root(value: str | None) -> Path:
    start = Path(value or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise CLIError("could not find repository root (.git)")


def _gh(root: Path) -> GitHub:
    return GitHub(discover_repository(root))


def _read_only_github(github: GitHub | ReadOnlyGitHub) -> ReadOnlyGitHub:
    """Create or verify the GET-only transport used by independent User Review reads."""
    if type(github) is ReadOnlyGitHub:
        github.verify_read_only_scope()
        return github
    if type(github) is not GitHub:
        raise CLIError("read-only GitHub verifier route cannot be positively verified")
    reader = ReadOnlyGitHub(github.repo)
    reader.verify_read_only_scope()
    if reader is github:
        raise CLIError("read-only GitHub verifier must be a separate client instance")
    return reader


def _positive_number(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("Issue number must be a positive integer")
    return int(value)


def _phase_skip_reasons(values: list[str]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for raw in values:
        name, separator, reason = raw.partition("=")
        if not separator or not reason.strip() or name in reasons or name not in {"specification", "design"}:
            raise CLIError("--skip-phase must be a unique specification=reason or design=reason")
        reasons[name] = reason.strip()
    return reasons


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CLIError(f"JSON contains duplicate object key: {key}")
        result[key] = value
    return result


def _path_components_without_symlinks(path: Path, root: Path | None = None) -> bool:
    location = Path(os.path.abspath(path))
    if root is not None:
        anchor = Path(os.path.abspath(root))
        if anchor.is_symlink():
            return False
        try:
            relative = location.relative_to(anchor)
        except ValueError:
            return not location.is_symlink() and not location.parent.is_symlink()
        candidates = [anchor]
        current = anchor
        for part in relative.parts:
            current = current / part
            candidates.append(current)
        return not any(candidate.is_symlink() for candidate in candidates)
    return not location.is_symlink() and not location.parent.is_symlink()


def _read_json(path: Path, label: str, *, root: Path | None = None) -> Any:
    location = Path(path)
    if not _path_components_without_symlinks(location, root) or not location.is_file():
        raise CLIError(f"{label} must be a regular non-symlink file")
    try:
        raw = location.read_bytes()
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CLIError(f"{label} is not readable UTF-8 JSON") from exc


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_immutable(path: Path, data: bytes, *, root: Path | None = None) -> str:
    destination = Path(path)
    if not _path_components_without_symlinks(destination, root):
        raise CLIError("immutable artifact path must not traverse a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _path_components_without_symlinks(destination, root):
        raise CLIError("immutable artifact path must not traverse a symbolic link")
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != data:
                raise CLIError("immutable artifact identity exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise CLIError("could not atomically store immutable artifact") from exc
    if destination.read_bytes() != data:
        raise CLIError("immutable artifact readback changed")
    return hashlib.sha256(data).hexdigest()


def _source_path(root: Path, name: Any) -> Path:
    if not isinstance(name, str) or not name or "\\" in name:
        raise PlanError("source name must be a canonical repository-relative path")
    windows = PureWindowsPath(name)
    if windows.is_absolute() or Path(name).is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        raise PlanError("source name must be a canonical repository-relative path")
    path = root
    for part in name.split("/"):
        path = path / part
        if path.is_symlink():
            raise PlanError(f"source path must not traverse a symbolic link: {name}")
    if not path.is_file():
        raise PlanError(f"frozen source file is missing: {name}")
    return path


_DECLARED_REQ = re.compile(
    rf"^\s*(?:\|\s*)?(?:#{{1,6}}\s+)?(?:[0-9]+(?:\.[0-9]+)*\s+)?"
    rf"(?:[-*+]\s*)?\[?({REQ_ID_PATTERN})\]?(?=\s|:|\||\(|$)",
    re.MULTILINE,
)
_ISSUE_REF = re.compile(r"(?:#|issues/)([1-9][0-9]*)\b", re.IGNORECASE)


def _normative_req_ids(contract: Any, source_digests: tuple[tuple[str, str, str], ...], root: Path) -> tuple[str, ...]:
    found: set[str] = set(contract.requirement_ids)
    test_spec_ids: set[str] = set()
    for kind, name, _digest in source_digests:
        if kind not in {"specification", "test_specification"}:
            continue
        try:
            text = _source_path(root, name).read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            raise PlanError(f"normative source is unreadable: {name}") from exc
        declared = set(_DECLARED_REQ.findall(text))
        found.update(declared)
        if kind == "test_specification":
            test_spec_ids.update(declared)
    if not test_spec_ids:
        raise PlanError("frozen test specifications declare no normative REQ-ID")
    return tuple(sorted(found))


def _plans_root(root: Path, issue_number: int) -> Path:
    return root / ".p_ases" / "plans" / str(issue_number)


def _trace_path(root: Path, plan: VerificationPlan) -> Path:
    return _plans_root(root, plan.issue_number) / f"{plan.sha256}.trace.json"


def _trace_payload(plan: VerificationPlan, oracles: tuple[OracleDefinition, ...],
                   tests: tuple[TestDefinition, ...]) -> bytes:
    value = {
        "oracles": [item.as_dict() for item in sorted(oracles, key=lambda item: item.oracle_id)],
        "plan_sha256": plan.sha256,
        "schema": "PASES_VERIFICATION_TRACE_V1",
        "trace_sha256": plan.oracle_test_trace_sha256,
        "tests": [item.as_dict() for item in sorted(tests, key=lambda item: (item.req_id, item.test_id, item.target))],
    }
    return _canonical(value) + b"\n"


def _trace_digest(oracles: tuple[OracleDefinition, ...], tests: tuple[TestDefinition, ...]) -> str:
    value = {
        "oracles": [item.as_dict() for item in sorted(oracles, key=lambda item: item.oracle_id)],
        "schema": "PASES_VERIFICATION_TRACE_V1",
        "tests": [item.as_dict() for item in sorted(tests, key=lambda item: (item.req_id, item.test_id, item.target))],
    }
    return hashlib.sha256(_canonical(value)).hexdigest()


def _load_plan(root: Path, repository: str, issue_number: int, plan_path: Path, verified_adc: Any
               ) -> tuple[VerificationPlan, tuple[str, ...], tuple[OracleDefinition, ...], tuple[TestDefinition, ...]]:
    try:
        plan = read_plan(_safe_file_bytes(Path(plan_path), "frozen Verification Plan", root=root))
    except (OSError, PlanError) as exc:
        raise PlanError(f"frozen Verification Plan is missing or invalid: {exc}") from exc
    pointer = verified_adc.pointer
    if (plan.repository != repository or plan.issue_number != issue_number
            or plan.adc_comment_id != pointer.comment_id or plan.adc_sha256 != pointer.sha256):
        raise PlanError("frozen Plan belongs to a different repository, Issue, or current approved ADC")
    source_digests = verify_plan_sources(root, plan)
    trace_path = _trace_path(root, plan)
    trace_bytes = _safe_file_bytes(trace_path, "frozen Oracle/Test trace", root=root)
    raw = _read_json(trace_path, "frozen Oracle/Test trace", root=root)
    if (not isinstance(raw, dict) or set(raw) != {"oracles", "plan_sha256", "schema", "tests", "trace_sha256"}
            or raw.get("schema") != "PASES_VERIFICATION_TRACE_V1" or raw.get("plan_sha256") != plan.sha256
            or raw.get("trace_sha256") != plan.oracle_test_trace_sha256
            or not isinstance(raw.get("oracles"), list) or not isinstance(raw.get("tests"), list)):
        raise PlanError("frozen Oracle/Test trace does not match the Verification Plan")
    if _canonical(raw) + b"\n" != trace_bytes:
        raise PlanError("frozen Oracle/Test trace bytes changed or became noncanonical after Plan creation")
    oracles = tuple(OracleDefinition.from_dict(item) for item in raw["oracles"])
    tests = tuple(TestDefinition.from_dict(item) for item in raw["tests"])
    if _trace_digest(oracles, tests) != plan.oracle_test_trace_sha256:
        raise PlanError("frozen Oracle/Test definitions changed after Plan creation")
    required = _normative_req_ids(verified_adc.contract, source_digests, root)
    validate_plan_oracles(plan, required, {item.oracle_id: item for item in oracles})
    validate_plan_tests(plan, tests, source_digests)
    return plan, required, oracles, tests


def _safe_file_bytes(path: Path, label: str, *, root: Path | None = None) -> bytes:
    if not _path_components_without_symlinks(path, root) or not path.is_file():
        raise CLIError(f"{label} must be a regular non-symlink file")
    return path.read_bytes()


def _subject(repository: str, issue_number: int, pr_number: int, head_sha40: str,
             verified_adc: Any, plan: VerificationPlan) -> VerificationSubject:
    pointer = verified_adc.pointer
    if plan.repository != repository or plan.issue_number != issue_number:
        raise PlanError("Plan and requested Verification subject identify different repository/Issue")
    return VerificationSubject(repository, issue_number, pr_number, pointer.comment_id,
                                pointer.sha256, plan.sha256, head_sha40).validate()


def _readback_current_pr(github: GitHub, subject: VerificationSubject) -> dict[str, Any]:
    """Fail closed unless GitHub's current PR is the exact open same-repository subject."""
    try:
        row = github.pull_request(subject.pr_number)
    except GitHubError as exc:
        raise CLIError(f"current GitHub PR readback failed: {exc}") from exc
    base = row.get("base") if isinstance(row, dict) else None
    head = row.get("head") if isinstance(row, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    head_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    base_ref = base.get("ref") if isinstance(base, dict) else None
    head_ref = head.get("ref") if isinstance(head, dict) else None
    base_sha = base.get("sha") if isinstance(base, dict) else None
    head_sha = head.get("sha") if isinstance(head, dict) else None
    body = row.get("body") if isinstance(row, dict) else None
    if (not isinstance(row, dict) or row.get("number") != subject.pr_number
            or row.get("state") != "open" or row.get("draft") is not False
            or not isinstance(base_ref, str) or not base_ref.strip()
            or not isinstance(head_ref, str) or not head_ref.strip()
            or not isinstance(base_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", base_sha)
            or not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
            or not isinstance(base_name, str) or base_name.casefold() != subject.repository.casefold()
            or not isinstance(head_name, str) or head_name.casefold() != subject.repository.casefold()):
        raise CLIError("current PR is closed, draft, forked, cross-repository, or has incomplete base/head identity")
    if head_sha != subject.pr_head_sha40:
        raise CLIError("Verification subject HEAD differs from the current GitHub PR HEAD")
    expected_refs = ISSUE_PR_REFS.get(subject.issue_number)
    if expected_refs is not None and (base_ref, head_ref) != expected_refs:
        raise CLIError("current PR base/head branches do not match the approved Issue branch contract")
    if not isinstance(body, str):
        raise CLIError("current PR body is missing; Issue closing association cannot be verified")
    try:
        association_mode = parse_issue_association(body, subject.issue_number)
    except WorkError as exc:
        raise CLIError(f"current PR Issue association is invalid: {exc}") from exc
    if subject.issue_number == 63 and (subject.pr_number != 64 or association_mode != "deferred_close"):
        raise CLIError("Issue #63 deferred delivery requires existing PR #64 with standalone Refs #63")
    return {
        "number": subject.pr_number,
        "state": "open",
        "draft": False,
        "repository": subject.repository.casefold(),
        "base_ref": base_ref,
        "base_sha": base_sha,
        "head_ref": head_ref,
        "head_sha": head_sha,
        "body": body,
        "association_mode": association_mode,
        "close_on_merge": association_mode == "auto_close",
    }


def _require_same_pr_readback(github: GitHub, subject: VerificationSubject,
                              initial: dict[str, Any]) -> None:
    current = _readback_current_pr(github, subject)
    if current != initial:
        raise CLIError("GitHub PR identity/base/head changed during Verification; result is stale")


def _result_comment(kind: str, value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    marker = "PASES_VERIFICATION_RESULT_V1" if kind == "verification" else "PASES_ACCEPTANCE_RESULT_V1"
    return f"<!-- {marker} -->\n\n```json\n{payload}\n```"


def _publish_once(github: GitHub, issue_number: int, body: str) -> int:
    def find() -> list[dict[str, Any]]:
        rows = [item for item in github.issue_comments(issue_number) if item.get("body") == body]
        if len(rows) > 1:
            raise CLIError("identical immutable evidence comments are duplicated")
        return rows

    existing = find()
    if existing:
        comment_id = existing[0].get("id")
    else:
        try:
            created = github.create_issue_comment(issue_number, body)
            comment_id = created["id"]
        except GitHubError:
            recovered = find()
            if len(recovered) != 1:
                raise
            comment_id = recovered[0].get("id")
    if type(comment_id) is not int or comment_id < 1:
        raise CLIError("GitHub comment readback has an invalid Comment ID")
    readback = github.issue_comment(issue_number, comment_id)
    expected_issue_url = f"https://api.github.com/repos/{github.repo}/issues/{issue_number}"
    if readback.get("body") != body or readback.get("issue_url") != expected_issue_url:
        raise CLIError("published evidence comment did not match exact issue/body readback")
    return comment_id


def _exact_published(github: GitHub, issue_number: int, body: str) -> int | None:
    matches = [item for item in github.issue_comments(issue_number) if item.get("body") == body]
    if len(matches) > 1:
        raise CLIError("identical immutable evidence comments are duplicated")
    if not matches:
        return None
    comment_id = matches[0].get("id")
    if type(comment_id) is not int or comment_id < 1:
        raise CLIError("published evidence Comment ID is invalid")
    readback = github.issue_comment(issue_number, comment_id)
    if readback.get("body") != body:
        raise CLIError("published evidence comment changed during readback")
    return comment_id


def _blocked_result(reasons: list[str] | tuple[str, ...], subject: VerificationSubject | None = None) -> int:
    _json({"status": "BLOCKED", "subject": None if subject is None else subject.as_dict(),
           "subject_sha256": None if subject is None else subject.sha256,
           "reasons": list(reasons) or ["required evidence is unavailable"], "evidence_refs": []})
    return 2


def _verification_plan(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    verified_adc = verify_adc(github, args.issue)
    if verified_adc.pointer.state != "approved":
        raise CLIError("Verification Plan requires the current approved ADC")
    value = _read_json(args.input, "Verification Plan input", root=root)
    if not isinstance(value, dict) or set(value) != {"entries", "oracles", "sources", "tests"}:
        raise CLIError("Plan input must contain exactly sources, entries, oracles, and tests")
    if any(not isinstance(value[key], list) for key in ("sources", "entries", "oracles", "tests")):
        raise CLIError("Plan input sources, entries, oracles, and tests must be arrays")
    sources: list[tuple[str, str, str]] = []
    for item in value["sources"]:
        if not isinstance(item, dict) or set(item) != {"kind", "name"}:
            raise CLIError("Plan source entries must contain exactly kind and name")
        kind, name = item["kind"], item["name"]
        path = _source_path(root, name)
        sources.append((kind, name, hashlib.sha256(path.read_bytes()).hexdigest()))
    source_rows = tuple(sorted(sources))
    entries = tuple(PlanEntry.from_dict(item) for item in value["entries"])
    oracles = tuple(OracleDefinition.from_dict(item) for item in value["oracles"])
    tests = tuple(TestDefinition.from_dict(item) for item in value["tests"])
    trace_sha256 = _trace_digest(oracles, tests)
    required = _normative_req_ids(verified_adc.contract, source_rows, root)
    plan = create_plan(
        repository=repository, issue_number=args.issue, adc_comment_id=verified_adc.pointer.comment_id,
        adc_sha256=verified_adc.pointer.sha256, source_digests=source_rows, entries=entries,
        required_req_ids=required, oracle_test_trace_sha256=trace_sha256,
    )
    validate_plan_oracles(plan, required, {item.oracle_id: item for item in oracles})
    validate_plan_tests(plan, tests, source_rows)
    plan_path = _plans_root(root, args.issue) / f"{plan.sha256}.json"
    trace_path = _trace_path(root, plan)
    _write_immutable(plan_path, plan.to_bytes(), root=root)
    _write_immutable(trace_path, _trace_payload(plan, oracles, tests), root=root)
    _json({"status": "READY_FOR_EVIDENCE", "issue": args.issue, "adc_comment_id": plan.adc_comment_id,
           "adc_sha256": plan.adc_sha256, "plan_sha256": plan.sha256,
           "plan_path": str(plan_path), "required_req_ids": list(required),
           "source_digests": [{"kind": k, "name": n, "sha256": d} for k, n, d in plan.source_digests],
           "evidence_refs": [str(plan_path), str(trace_path)], "reasons": []})
    return 0


def _verification_collect(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    verified_adc = verify_adc(github, args.issue)
    _require_current_adopted_generation(github, root, repository, args.issue, verified_adc)
    plan, _required, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
    subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
    pr_readback = _readback_current_pr(github, subject)
    value = _read_json(args.observation, "external execution observation", root=root)
    expected = {
        "command", "entry_key", "environment", "evidence_type", "exit_status", "manual_procedure",
        "observed_at", "outcome", "output_sha256", "runner_source",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise CLIError("external execution observation has unknown or missing fields")
    record = EvidenceRecord(
        subject=subject, entry_key=value["entry_key"], evidence_type=value["evidence_type"],
        command=tuple(value["command"]) if isinstance(value["command"], list) else value["command"],
        manual_procedure=value["manual_procedure"], environment=value["environment"],
        runner_source=value["runner_source"], observed_at=value["observed_at"], outcome=value["outcome"],
        exit_status=value["exit_status"], output_sha256=value["output_sha256"],
    ).validate()
    entry = next((item for item in plan.entries if "|".join((item.req_id, item.oracle_id, item.test_id, item.target)) == record.entry_key), None)
    if (entry is None or record.environment != entry.environment or record.command != entry.command
            or record.manual_procedure != entry.manual_procedure or record.evidence_type not in entry.evidence_required):
        raise CLIError("external observation identity does not match the frozen Plan entry")
    path = evidence_path(root / ".p_ases" / "evidence", record)
    digest = write_evidence(path, record)
    readback = read_evidence(path)
    if readback != record:
        raise CLIError("Evidence readback changed")
    _require_same_pr_readback(github, subject, pr_readback)
    _json({"status": "EVIDENCE_RECORDED", "subject": subject.as_dict(), "subject_sha256": subject.sha256,
           "outcome": record.outcome, "evidence_sha256": digest, "evidence_refs": [str(path)], "reasons": []})
    return 0 if record.outcome == "PASS" else 2


def _calculate_verification(args: argparse.Namespace, repository: str, root: Path, github: GitHub
                             ) -> tuple[VerificationResult, list[str]]:
    verified_adc = verify_adc(github, args.issue)
    _require_current_adopted_generation(github, root, repository, args.issue, verified_adc)
    plan, _required, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
    subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
    pr_readback = _readback_current_pr(github, subject)
    records = read_evidence_set(root / ".p_ases" / "evidence", subject)
    try:
        config_value = _read_json(root / ".agent" / "project.json", "project Required Check configuration", root=root)
        policy = RequiredCheckPolicy.from_project_config(config_value)
        check_runs = github.check_runs_for_ref(args.head)
        forked = required_check_fork_status(policy, check_runs, subject=subject, expected_repository=repository)
        if forked is None:
            check_result = GateResult("BLOCKED", ("exact PR/fork provenance is missing from Check Run readback",), subject).validate()
        else:
            check_result = evaluate_required_checks(
                policy, check_runs, subject=subject, expected_repository=repository,
                response_repository=repository, head_sha40=args.head, is_fork=forked,
            )
    except (CLIError, VerificationError, GitHubError) as exc:
        policy = None
        check_result = GateResult("BLOCKED", (f"Required Checks could not be verified: {exc}",), subject).validate()
    # Detect source edits that raced the GitHub read before freezing the result.
    verify_plan_sources(root, plan)
    result = build_verification_result(plan, subject, records, check_result, policy)
    _require_same_pr_readback(github, subject, pr_readback)
    evidence_root = root / ".p_ases" / "evidence"
    evidence_refs = [str(evidence_path(evidence_root, record)) for record in records]
    return result, evidence_refs


def _verification_gate(args: argparse.Namespace, repository: str, root: Path, github: GitHub,
                       *, persist: bool) -> int:
    result, evidence_refs = _calculate_verification(args, repository, root, github)
    subject = result.subject
    result_path = verification_result_path(root / ".p_ases" / "verification", result)
    if persist:
        _readback_current_pr(github, subject)
        write_verification_result(result_path, result)
        body = _result_comment("verification", result.as_json())
        pr_before_publish = _readback_current_pr(github, subject)
        comment_id = _publish_once(github, args.issue, body)
        _require_same_pr_readback(github, subject, pr_before_publish)
        evidence_refs.extend((str(result_path), f"issue-comment:{comment_id}"))
    output = result.as_json()
    output["evidence_refs"] = evidence_refs
    output["reasons"] = list(result.reasons)
    _json(output)
    return 0 if result.status == "PASS" else 2


def _verification_published(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    result = read_verification_result(args.result)
    if result.subject.repository != repository or result.subject.issue_number != args.issue:
        raise CLIError("Verification result belongs to a different repository or Issue")
    plan_path = _plans_root(root, args.issue) / f"{result.subject.plan_sha256}.json"
    current_args = argparse.Namespace(issue=args.issue, pr=result.subject.pr_number,
                                      head=result.subject.pr_head_sha40, plan=plan_path)
    current, _ = _calculate_verification(current_args, repository, root, github)
    if current != result:
        raise CLIError("Verification result is stale relative to current ADC, Plan, Evidence, Check policy, or Check Runs")
    body = _result_comment("verification", result.as_json())
    pr_before_readback = _readback_current_pr(github, result.subject)
    comment_id = _exact_published(github, args.issue, body)
    if comment_id is None:
        return _blocked_result(("exact Verification result comment is not present on the Issue",), result.subject)
    _require_same_pr_readback(github, result.subject, pr_before_readback)
    _json({"status": "PUBLISHED", "subject": result.subject.as_dict(), "subject_sha256": result.subject.sha256,
           "result_sha256": result.sha256, "comment_id": comment_id,
           "evidence_refs": [str(args.result), f"issue-comment:{comment_id}"], "reasons": []})
    return 0


def _acceptance_template(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    verified_adc = verify_adc(github, args.issue)
    _require_current_adopted_generation(github, root, repository, args.issue, verified_adc)
    plan, _required, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
    subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
    pr_readback = _readback_current_pr(github, subject)
    required_kinds = {
        "spec_change": ("acceptance_criteria",),
        "design_change": ("acceptance_criteria",),
        "bug_fix": ("red_before", "green_after"),
        "documentation_only": ("link_validation", "acceptance_criteria"),
        "formatting_only": ("link_validation", "semantic_unchanged"),
        "test_improvement": ("oracle_validation",),
        "feature_gui": ("gui_verification",),
        "feature_e2e": ("e2e_verification",),
        "feature_manual": ("manual_verification",),
    }[args.artifact_type]
    template = {
        "artifact_type": args.artifact_type,
        "baseline_sha40": None,
        "observations": [],
        "policy_version": ACCEPTANCE_POLICY_VERSION,
        "required_observation_kinds": list(required_kinds),
        "schema": "PASES_ACCEPTANCE_INPUT_V1",
        "subject": subject.as_dict(),
    }
    data = _canonical(template) + b"\n"
    _write_immutable(args.output, data, root=root)
    _require_same_pr_readback(github, subject, pr_readback)
    _json({"status": "PREPARED", "subject": subject.as_dict(), "subject_sha256": subject.sha256,
           "artifact_type": args.artifact_type, "policy_version": ACCEPTANCE_POLICY_VERSION,
           "evidence_refs": [str(args.output)], "reasons": []})
    return 0


def _acceptance_kinds(artifact_type: str) -> list[str]:
    return {
        "spec_change": ["acceptance_criteria"],
        "design_change": ["acceptance_criteria"],
        "bug_fix": ["red_before", "green_after"],
        "documentation_only": ["link_validation", "acceptance_criteria"],
        "formatting_only": ["link_validation", "semantic_unchanged"],
        "test_improvement": ["oracle_validation"],
        "feature_gui": ["gui_verification"],
        "feature_e2e": ["e2e_verification"],
        "feature_manual": ["manual_verification"],
    }[artifact_type]


def _acceptance_template_value(artifact_type: str, subject: VerificationSubject,
                               observations: list[dict[str, Any]], baseline_sha40: str | None) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "baseline_sha40": baseline_sha40,
        "observations": observations,
        "policy_version": ACCEPTANCE_POLICY_VERSION,
        "required_observation_kinds": _acceptance_kinds(artifact_type),
        "schema": "PASES_ACCEPTANCE_INPUT_V1",
        "subject": subject.as_dict(),
    }


def _unaccepted_dependencies(github: GitHub, contract: Any) -> tuple[str, ...]:
    section = getattr(contract, "section", None)
    if not callable(section):
        return ()
    try:
        text = section("Dependencies")
    except (KeyError, ValueError):
        text = ""
    numbers = sorted({int(value) for value in _ISSUE_REF.findall(text)})
    if not numbers and getattr(contract, "issue_number", None) == 29:
        # The approved #29 ADC fixes #27/#28 as its upstream dependencies.
        numbers = [27, 28]
    elif not numbers and getattr(contract, "issue_number", None) == 30:
        # The approved #30 ADC fixes #27/#29 as its upstream dependencies.
        numbers = [27, 29]
    if getattr(contract, "issue_number", None) == 30:
        # #28 is an explicit transitive blocker through #29 until formal Oracle acceptance.
        numbers = sorted(set(numbers) | {28})
    pending: list[str] = []
    for number in numbers:
        try:
            issue = github.issue(number)
        except GitHubError as exc:
            pending.append(f"WAITING_DEPENDENCY #{number}: GitHub readback failed ({exc})")
            continue
        if not isinstance(issue, dict) or issue.get("number") != number or issue.get("state") != "closed":
            pending.append(f"WAITING_DEPENDENCY #{number}: dependency Issue is not accepted/closed")
    return tuple(pending)


def _calculate_acceptance(args: argparse.Namespace, repository: str, root: Path, github: GitHub,
                          template: dict[str, Any]) -> tuple[AcceptanceResult, list[str]]:
    verified_adc = verify_adc(github, args.issue)
    plan, required, oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
    subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
    pr_readback = _readback_current_pr(github, subject)
    expected = {"artifact_type", "baseline_sha40", "observations", "policy_version", "required_observation_kinds", "schema", "subject"}
    if not isinstance(template, dict) or set(template) != expected or template.get("schema") != "PASES_ACCEPTANCE_INPUT_V1":
        raise CLIError("Acceptance input has unknown/missing fields or schema")
    if (template["artifact_type"] != args.artifact_type or template["policy_version"] != ACCEPTANCE_POLICY_VERSION
            or template["required_observation_kinds"] != _acceptance_kinds(args.artifact_type)
            or VerificationSubject.from_dict(template["subject"]) != subject
            or not isinstance(template["observations"], list)):
        raise CLIError("Acceptance input is stale or does not match the selected artifact/subject")
    observations = tuple(AcceptanceObservation.from_dict(item) for item in template["observations"])
    evidence_root = (root / ".p_ases" / "evidence").absolute()
    verification_records = read_evidence_set(evidence_root, subject)
    evidence_paths = {evidence_path(evidence_root, record).absolute() for record in verification_records}
    evidence_by_digest = {record.evidence_sha256: record for record in verification_records}
    for observation in observations:
        reference = Path(observation.reference)
        if not reference.is_absolute():
            reference = root / reference
        absolute_reference = Path(os.path.abspath(reference))
        try:
            if os.path.commonpath((str(evidence_root), str(absolute_reference))) != str(evidence_root):
                raise CLIError("Acceptance Evidence reference must stay inside the exact-subject Evidence store")
        except ValueError as exc:
            raise CLIError("Acceptance Evidence reference is outside the exact-subject Evidence store") from exc
        record = read_evidence(absolute_reference)
        if (record.subject != subject or record.evidence_sha256 != observation.evidence_sha256
                or record.evidence_type != observation.kind or record.outcome != observation.outcome
                or record.evidence_sha256 not in evidence_by_digest or absolute_reference not in evidence_paths):
            raise CLIError("Acceptance observation does not match read-back exact-subject Evidence")
    verification = read_verification_result(args.verification)
    current_verification, _ = _calculate_verification(args, repository, root, github)
    if verification != current_verification:
        raise CLIError("Verification result is stale relative to current source, Evidence, Check policy, or Check Runs")
    verification_gate = GateResult(verification.status, verification.reasons, verification.subject).validate()
    try:
        validate_plan_oracles(plan, required, {item.oracle_id: item for item in oracles})
        dependency_reasons = _unaccepted_dependencies(github, verified_adc.contract)
        if dependency_reasons:
            oracle_gate = GateResult("BLOCKED", dependency_reasons, subject).validate()
        else:
            oracle_gate = GateResult("PASS", (), subject).validate()
    except OracleTraceError as exc:
        oracle_gate = GateResult("BLOCKED", (str(exc),), subject).validate()
    result = evaluate_acceptance(
        artifact_type=args.artifact_type, subject=subject, required_req_ids=required,
        mapped_req_ids=tuple(sorted({entry.req_id for entry in plan.entries})),
        verification=verification_gate, oracle_trace=oracle_gate, observations=observations,
        baseline_sha40=template["baseline_sha40"],
        verification_result_sha256=current_verification.sha256,
    )
    _require_same_pr_readback(github, subject, pr_readback)
    refs = [str(evidence_path(evidence_root, evidence_by_digest[row.evidence_sha256])) for row in observations]
    return result, refs


def _acceptance_validate(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    template = _read_json(args.observations, "Acceptance input", root=root)
    result, evidence_refs = _calculate_acceptance(args, repository, root, github, template)
    _readback_current_pr(github, result.subject)
    path = acceptance_result_path(root / ".p_ases" / "acceptance", result)
    write_acceptance_result(path, result)
    _readback_current_pr(github, result.subject)
    output = result.as_json()
    output["evidence_refs"] = [str(path), str(args.observations), str(args.verification), *evidence_refs]
    output["reasons"] = list(result.reasons)
    _json(output)
    return 0 if result.status == "PASS" else 2


def _acceptance_recompute_saved(args: argparse.Namespace, repository: str, root: Path, github: GitHub,
                                result: AcceptanceResult, *,
                                verification_result: VerificationResult | None = None) -> AcceptanceResult:
    if result.subject.repository != repository or result.subject.issue_number != args.issue:
        raise CLIError("Acceptance result belongs to a different repository or Issue")
    _readback_current_pr(github, result.subject)
    plan_path = _plans_root(root, args.issue) / f"{result.subject.plan_sha256}.json"
    recompute_args = argparse.Namespace(
        issue=result.subject.issue_number, pr=result.subject.pr_number, head=result.subject.pr_head_sha40,
        plan=plan_path, artifact_type=result.artifact_type,
        verification=Path("__p_ases_recompute_current_verification__"),
    )
    verified_adc = verify_adc(github, args.issue)
    plan, _required, _oracles, _tests = _load_plan(root, repository, args.issue, plan_path, verified_adc)
    current_subject = _subject(repository, args.issue, result.subject.pr_number,
                               result.subject.pr_head_sha40, verified_adc, plan)
    template = _acceptance_template_value(
        result.artifact_type, current_subject, [row.as_dict() for row in result.observations], result.baseline_sha40,
    )
    # Recompute current Verification and use its immutable local readback as the input gate.
    if verification_result is None:
        current_verification, _ = _calculate_verification(recompute_args, repository, root, github)
    else:
        current_verification = verification_result
        if current_verification.subject != current_subject:
            raise CLIError("precomputed Verification does not match the current Acceptance subject")
    verification_path = verification_result_path(root / ".p_ases" / "verification", current_verification)
    write_verification_result(verification_path, current_verification)
    recompute_args.verification = verification_path
    fresh, _refs = _calculate_acceptance(recompute_args, repository, root, github, template)
    if fresh != result:
        raise CLIError("Acceptance result is stale relative to current Verification, Evidence, Oracle, or policy")
    return fresh


def _acceptance_publish(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    result = read_acceptance_result(args.result)
    _acceptance_recompute_saved(args, repository, root, github, result)
    body = _result_comment("acceptance", result.as_json())
    pr_before_publish = _readback_current_pr(github, result.subject)
    comment_id = _publish_once(github, args.issue, body)
    _require_same_pr_readback(github, result.subject, pr_before_publish)
    _json({"status": "PUBLISHED", "subject": result.subject.as_dict(), "subject_sha256": result.subject.sha256,
           "result_sha256": result.sha256, "comment_id": comment_id,
           "evidence_refs": [str(args.result), f"issue-comment:{comment_id}"], "reasons": []})
    return 0


def _acceptance_verify(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    result = read_acceptance_result(args.result)
    _acceptance_recompute_saved(args, repository, root, github, result)
    body = _result_comment("acceptance", result.as_json())
    pr_before_readback = _readback_current_pr(github, result.subject)
    comment_id = _exact_published(github, args.issue, body)
    if comment_id is None:
        return _blocked_result(("exact Acceptance result comment is not present on the Issue",), result.subject)
    _require_same_pr_readback(github, result.subject, pr_before_readback)
    _json({"status": "PUBLISHED", "subject": result.subject.as_dict(), "subject_sha256": result.subject.sha256,
           "result_sha256": result.sha256, "comment_id": comment_id,
           "evidence_refs": [str(args.result), f"issue-comment:{comment_id}"], "reasons": []})
    return 0


CHECKLIST_LINE = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s+(.+?)\s*$")
FILE_EVIDENCE_REF = re.compile(r"^(.+)#sha256=([0-9a-f]{64})$")
STANDALONE_CLOSE = re.compile(r"(?im)^Closes #([1-9][0-9]*)\s*$")
ANY_CLOSE = re.compile(r"(?i)\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s+#([1-9][0-9]*)\b")


def _runtime_root(args: argparse.Namespace) -> Path:
    root_arg = getattr(args, "root", None)
    root = _repo_root(None) if root_arg is None else Path(root_arg)
    if root.is_symlink() or not root.is_dir():
        raise CLIError("repository root must be a regular directory")
    return root.resolve()


def _project_status(root: Path) -> int:
    """Read the project profile without creating or changing repository state."""
    try:
        profile = load_profile(root)
    except ProfileError as exc:
        _json({"status": "UNAVAILABLE", "root": str(root), "reason": str(exc)})
        return 2
    _json({
        "status": "READY",
        "root": str(profile.root),
        "project_name": profile.project_name,
        "branch_prefix": profile.branch_prefix,
        "activation_issue_number": profile.activation_issue_number,
        "required_checks": [
            {"name": name, "trusted_app_id": app_id}
            for name, app_id in profile.required_checks
        ],
    })
    return 0


def _context_show(issue_number: int, repository: str, root: Path, github: GitHub) -> int:
    """Read Issue, approved ADC, and an existing frozen binding without resolving a base."""
    try:
        issue = github.issue(issue_number)
    except GitHubError as exc:
        _json({"status": "ISSUE_UNAVAILABLE", "issue": issue_number,
               "repository": repository, "binding_status": "NOT_EVALUATED", "reason": str(exc)})
        return 2
    if issue.get("number") != issue_number or issue.get("pull_request") is not None:
        _json({"status": "ISSUE_INVALID", "issue": issue_number, "repository": repository,
               "binding_status": "NOT_EVALUATED", "reason": "GitHub readback is not the requested Issue"})
        return 2
    if issue.get("state") != "open":
        _json({"status": "ISSUE_CLOSED", "issue": issue_number, "repository": repository,
               "issue_state": issue.get("state"), "binding_status": "NOT_EVALUATED",
               "reason": "context is available only for an open Issue"})
        return 2
    try:
        verified = verify_adc(github, issue_number)
    except ADCError as exc:
        _json({"status": "ADC_UNAVAILABLE", "issue": issue_number, "repository": repository,
               "issue_state": "open", "binding_status": "NOT_EVALUATED", "reason": str(exc)})
        return 2
    if (verified.pointer.state != "approved"
            or verified.contract.repository.casefold() != repository.casefold()):
        _json({"status": "ADC_NOT_APPROVED", "issue": issue_number, "repository": repository,
               "issue_state": "open", "adc_status": verified.pointer.state.upper(),
               "adc_comment_id": verified.pointer.comment_id,
               "adc_sha256": verified.pointer.sha256,
               "binding_status": "NOT_EVALUATED",
               "reason": "current ADC is not approved for this repository"})
        return 2

    binding_path = execution_binding_path(root, issue_number)
    if path_has_symlink(binding_path):
        _json({"status": "BINDING_INVALID", "issue": issue_number, "repository": repository,
               "issue_state": "open", "adc_status": "APPROVED", "binding_status": "INVALID",
               "reason": "ExecutionBinding path traverses a symbolic link"})
        return 2
    if not binding_path.is_file() and issue_number == 63 and repository.casefold() == "puchinya/ai-agent-workflow":
        adoption_path = root / ".p_ases" / "state" / "63" / "execution-adoption.json"
        attachment_path = root / ".p_ases" / "state" / "63" / "workspace-attachment.json"
        if adoption_path.exists() or adoption_path.is_symlink() or attachment_path.exists() or attachment_path.is_symlink():
            try:
                identity = read_execution_identity(
                    github, root, adc_comment_id=verified.pointer.comment_id,
                    adc_sha256=verified.pointer.sha256,
                )
                if not isinstance(identity, AdoptedExecutionEpoch):
                    raise ExecutionAdoptionError("adoption artifacts resolved to a non-adopted identity")
            except (ExecutionAdoptionError, ExecutionError, OSError, ValueError) as exc:
                _json({"status": "ADOPTION_INVALID", "issue": issue_number, "repository": repository,
                       "issue_state": "open", "adc_status": "APPROVED", "binding_status": "INVALID",
                       "reason": str(exc)})
                return 2
            attachment = root / ".p_ases" / "state" / "63" / "workspace-attachment.json"
            _json({"status": "ADOPTED", "issue": issue_number, "repository": repository,
                   "issue_state": "open", "adc_status": "APPROVED",
                   "adc_comment_id": verified.pointer.comment_id, "adc_sha256": verified.pointer.sha256,
                   "binding_status": "ADOPTED_EPOCH", "execution_identity_sha256": identity.sha256,
                   "adoption_id": identity.adoption_id, "historical_binding_provenance": "UNVERIFIED",
                   "frozen_context": {"base_ref": identity.selected_base_ref,
                                      "base_sha": identity.selected_base_sha40,
                                      "branch_ref": identity.branch_ref,
                                      "observed_start_head_sha40": identity.observed_start_head_sha40,
                                      "workspace_attachment": str(attachment)}})
            return 0
    if not binding_path.is_file():
        _json({"status": "NOT_BOUND", "issue": issue_number, "repository": repository,
               "issue_state": "open", "adc_status": "APPROVED",
               "adc_comment_id": verified.pointer.comment_id,
               "adc_sha256": verified.pointer.sha256,
               "binding_status": "NOT_BOUND"})
        return 2
    try:
        binding = read_binding(binding_path)
    except (ExecutionError, OSError, ValueError) as exc:
        _json({"status": "BINDING_INVALID", "issue": issue_number, "repository": repository,
               "issue_state": "open", "adc_status": "APPROVED", "binding_status": "INVALID",
               "reason": str(exc)})
        return 2
    if (binding.repository.casefold() != repository.casefold() or binding.issue_number != issue_number
            or binding.adc_comment_id != verified.pointer.comment_id
            or binding.adc_sha256 != verified.pointer.sha256):
        _json({"status": "STALE_BINDING", "issue": issue_number, "repository": repository,
               "issue_state": "open", "adc_status": "APPROVED",
               "adc_comment_id": verified.pointer.comment_id,
               "adc_sha256": verified.pointer.sha256, "binding_status": "STALE_ADC",
               "binding_adc_comment_id": binding.adc_comment_id,
               "binding_adc_sha256": binding.adc_sha256,
               "frozen_context": {"base_ref": binding.base_ref, "base_sha": binding.base_sha,
                                  "branch_ref": binding.branch_ref,
                                  "work_directory": binding.work_directory,
                                  "initial_head_sha": binding.initial_head_sha}})
        return 2
    if Path(binding.work_directory) != root:
        _json({"status": "NOT_BOUND_HERE", "issue": issue_number, "repository": repository,
               "issue_state": "open", "adc_status": "APPROVED",
               "adc_comment_id": verified.pointer.comment_id,
               "adc_sha256": verified.pointer.sha256, "binding_status": "BOUND_ELSEWHERE"})
        return 2
    _json({"status": "BOUND", "issue": issue_number, "repository": repository,
           "issue_state": "open", "adc_status": "APPROVED",
           "adc_comment_id": verified.pointer.comment_id,
           "adc_sha256": verified.pointer.sha256, "binding_status": "BOUND",
           "frozen_context": {"base_ref": binding.base_ref, "base_sha": binding.base_sha,
                              "branch_ref": binding.branch_ref, "work_directory": binding.work_directory,
                              "initial_head_sha": binding.initial_head_sha}})
    return 0


def _approved_issue_adc(github: GitHub, issue_number: int, repository: str) -> tuple[dict[str, Any], Any]:
    issue = github.issue(issue_number)
    if (issue.get("number") != issue_number or issue.get("state") != "open"
            or issue.get("pull_request") is not None):
        raise CLIError("work management requires the exact Issue to remain open")
    verified = verify_adc(github, issue_number)
    if verified.contract.repository != repository or verified.pointer.state != "approved":
        raise CLIError("work management requires the current approved ADC for this repository")
    return issue, verified


def _read_execution_identity(github: GitHub, root: Path, repository: str,
                             issue_number: int, verified_adc: Any) -> ExecutionIdentity:
    """Read the ordinary V1 binding or the explicitly discriminated #63 epoch."""
    if (issue_number == 63 and repository.casefold() == "puchinya/ai-agent-workflow"):
        try:
            return read_execution_identity(
                github, root, adc_comment_id=verified_adc.pointer.comment_id,
                adc_sha256=verified_adc.pointer.sha256,
            )
        except ExecutionAdoptionError as exc:
            raise CLIError(str(exc)) from exc
    try:
        return read_binding(execution_binding_path(root, issue_number))
    except ExecutionError as exc:
        raise CLIError(f"immutable ExecutionBinding readback failed: {exc}") from exc


def _require_current_adopted_generation(github: GitHub, root: Path, repository: str,
                                        issue_number: int, verified_adc: Any) -> None:
    """Prevent #63 exact-subject evidence until the adopted epoch has its current ADC bridge."""
    if (issue_number != 63 or repository.casefold() != "puchinya/ai-agent-workflow"
            or not (adoption_path(root).exists() or adoption_path(root).is_symlink())):
        return
    identity = _read_execution_identity(github, root, repository, issue_number, verified_adc)
    if not isinstance(identity, AdoptedExecutionEpoch):
        raise CLIError("Issue #63 adopted execution did not resolve to its immutable epoch")
    try:
        current_binding = read_pr_binding(pr_binding_path(root, issue_number, github=github))
    except (CheckpointError, WorkError, OSError) as exc:
        raise CLIError(f"current adopted PRBinding readback failed: {exc}") from exc
    if (current_binding.adoption_id != identity.adoption_id
            or current_binding.adc_comment_id != verified_adc.pointer.comment_id
            or current_binding.adc_sha256 != verified_adc.pointer.sha256
            or current_binding.pr_number != identity.pr_number
            or current_binding.pr_head_sha40 != head_sha40(root)):
        raise CLIError("current adopted PRBinding does not bridge the approved ADC and exact PR HEAD")


def _work_json(result: Any, issue_number: int, repository: str, *, extra: dict[str, Any] | None = None) -> int:
    binding = result.binding
    context = result.context
    value = {
        "status": result.status,
        "repository": repository,
        "issue": issue_number,
        "binding": None if binding is None else binding.__dict__,
        "binding_sha256": None if binding is None else binding_digest(binding),
        "context": None if context is None else {
            "branch_ref": context.branch_ref,
            "current_head_sha40": context.current_head_sha40,
            "worktree_clean": context.worktree_clean,
        },
        "remote_base_sha40": result.remote_base_sha40,
        "checkpoint_path": None if result.checkpoint_path is None else str(result.checkpoint_path),
        "checkpoint_sha256": result.checkpoint_sha256,
        "reasons": list(result.reasons),
        "evidence_refs": [] if result.checkpoint_path is None else [str(result.checkpoint_path)],
    }
    if extra:
        value.update(extra)
    _json(value)
    return 0 if result.status not in {"BLOCKED", "FAIL", "CONCERNS"} else 2


def _work_command(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    if args.verb == "adoption-refresh" and (
            args.issue != 63 or repository.casefold() != "puchinya/ai-agent-workflow"):
        raise CLIError("adoption refresh is restricted to puchinya/ai-agent-workflow Issue #63")
    _issue, verified = _approved_issue_adc(github, args.issue, repository)
    if args.verb == "adoption-refresh":
        result = refresh_adopted_pr_binding(
            github, root, expected_adc_comment_id=verified.pointer.comment_id,
            expected_adc_sha256=verified.pointer.sha256,
        )
        binding = result["pr_binding"]
        _json({"status": result["status"], "repository": repository, "issue": 63,
               "adoption_id": result["epoch"].adoption_id, "epoch_sha256": result["epoch"].sha256,
               "adc_comment_id": binding.adc_comment_id, "adc_sha256": binding.adc_sha256,
               "pr": binding.pr_number, "pr_head_sha40": binding.pr_head_sha40,
               "pr_binding_sha256": binding.sha256,
               "writes_performed": result["writes_performed"],
               "evidence_refs": [str(adoption_path(root)), str(pr_binding_path(root, 63, github=github))]})
        return 0 if result["status"] in {"REFRESHED", "RECOVERED", "NOOP"} else 2
    if args.verb == "adoption-plan":
        if args.issue != 63 or repository.casefold() != "puchinya/ai-agent-workflow":
            raise CLIError("execution adoption is restricted to puchinya/ai-agent-workflow Issue #63 / PR #64")
        plan = build_adoption_plan(github, root)
        write_adoption_plan(args.output, plan)
        _json({"status": "PLAN_READY", "output": str(args.output), "plan_sha256": plan["plan_sha256"],
               "adoption_id": plan["adoption_id"], "adoption_plan": plan,
               "approval_required": "EXECUTION_ADOPTION", "writes_performed": 0})
        return 0
    if args.verb == "adoption-apply":
        if args.issue != 63 or repository.casefold() != "puchinya/ai-agent-workflow":
            raise CLIError("execution adoption is restricted to puchinya/ai-agent-workflow Issue #63 / PR #64")
        plan = read_adoption_plan(args.plan)
        owner_plan = read_authorization_plan(args.authorization_plan)
        result = apply_adoption(github, root, plan, owner_plan)
        _json(result)
        return 0 if result.get("status") == "ADOPTED" else 2
    if (args.issue == 63 and repository.casefold() == "puchinya/ai-agent-workflow"
            and not execution_binding_path(root, args.issue).exists()
            and (adoption_path(root).exists() or adoption_path(root).is_symlink()
                 or (root / ".p_ases" / "state" / "63" / "workspace-attachment.json").exists()
                 or (root / ".p_ases" / "state" / "63" / "workspace-attachment.json").is_symlink())):
        if args.verb in {"branch", "bind"}:
            raise CLIError("Issue #63 already uses an adopted epoch; do not create a normal branch or V1 binding")
        if args.verb == "recover":
            verified_epoch = verify_adopted_execution(
                github, root, expected_adc_comment_id=verified.pointer.comment_id,
                expected_adc_sha256=verified.pointer.sha256,
            )
            epoch = verified_epoch["epoch"]
            _json({"status": "ADOPTED_EPOCH_VERIFIED", "repository": repository,
                   "issue": 63, "adoption_id": epoch.adoption_id,
                   "execution_identity_sha256": epoch.sha256,
                   "historical_binding_provenance": "UNVERIFIED",
                   "observed_start_head_sha40": epoch.observed_start_head_sha40,
                   "current_head_sha40": verified_epoch["current_head_sha40"],
                   "writes_performed": 0,
                   "evidence_refs": [str(adoption_path(root)),
                                     str(root / ".p_ases" / "state" / "63" / "workspace-attachment.json")]})
            return 0
    if (args.verb == "branch" and args.issue == 63
            and repository.casefold() == "puchinya/ai-agent-workflow"
            and not execution_binding_path(root, args.issue).exists()):
        raise CLIError("Issue #63 is already an open-PR continuation; work branch cannot replace its exact PR branch")
    if (args.verb == "bind" and args.issue == 63
            and repository.casefold() == "puchinya/ai-agent-workflow"
            and not execution_binding_path(root, args.issue).exists()):
        raise CLIError(
            "Issue #63 has no authenticated original ExecutionBinding; normal work bind cannot reconstruct it. "
            "Use the post-CI exact EXECUTION_ADOPTION plan and separate Owner approval."
        )
    if args.verb == "base":
        binding_path = execution_binding_path(root, args.issue)
        if binding_path.exists():
            binding = read_binding(binding_path)
            if (binding.repository != repository or binding.adc_comment_id != verified.pointer.comment_id
                    or binding.adc_sha256 != verified.pointer.sha256 or Path(binding.work_directory) != root):
                raise CLIError("existing ExecutionBinding conflicts with the current Issue/ADC/worktree")
            current_remote = remote_branch_sha(root, binding.base_ref)
            status = "BLOCKED" if current_remote != binding.base_sha else "FROZEN"
            _json({"status": status, "repository": repository, "issue": args.issue,
                   "base_ref": binding.base_ref, "base_sha40": binding.base_sha,
                   "remote_base_sha40": current_remote, "binding_sha256": binding_digest(binding),
                   "reasons": [] if current_remote == binding.base_sha else [
                       "remote base advanced; the immutable base remains frozen and must not be re-resolved"],
                   "evidence_refs": [str(binding_path)]})
            return 0 if status == "FROZEN" else 2
        if args.issue == 63 and (root / ".p_ases" / "state" / "63" / "execution-adoption.json").exists():
            identity = read_execution_identity(
                github, root, adc_comment_id=verified.pointer.comment_id,
                adc_sha256=verified.pointer.sha256,
            )
            if not isinstance(identity, AdoptedExecutionEpoch):
                raise CLIError("adoption state did not resolve to its typed adopted epoch")
            remote = remote_branch_sha(root, identity.selected_base_ref)
            status = "ADOPTED" if remote == identity.selected_base_sha40 else "FORWARD_BASE_ADVANCE_PENDING_EVIDENCE"
            _json({"status": status, "repository": repository, "issue": args.issue,
                   "base_ref": identity.selected_base_ref, "base_sha40": identity.selected_base_sha40,
                   "remote_base_sha40": remote, "execution_identity_sha256": identity.sha256,
                   "adoption_id": identity.adoption_id, "reasons": [],
                   "evidence_refs": [str(root / ".p_ases" / "state" / "63" / "execution-adoption.json")]})
            return 0 if status == "ADOPTED" else 2
        if not worktree_clean(root):
            raise CLIError("base selection requires a clean worktree")
        base_ref = args.base_ref or github.repository_metadata().get("default_branch")
        if not isinstance(base_ref, str) or not base_ref:
            raise CLIError("GitHub repository default branch is invalid")
        selected = remote_branch_sha(root, base_ref)
        _json({"status": "BASE_SELECTED", "repository": repository, "issue": args.issue,
               "adc_comment_id": verified.pointer.comment_id, "adc_sha256": verified.pointer.sha256,
               "base_ref": base_ref, "base_sha40": selected, "reasons": [], "evidence_refs": []})
        return 0
    if args.verb == "branch":
        result = ensure_branch(root, args.base_ref, args.base_sha, args.branch_ref)
        return _work_json(result, args.issue, repository)
    if args.verb == "bind":
        result = bind_work(root, repository=repository, issue_number=args.issue,
                           adc_comment_id=verified.pointer.comment_id, adc_sha256=verified.pointer.sha256,
                           base_ref=args.base_ref, branch_ref=args.branch_ref,
                           expected_base_sha40=args.base_sha)
        return _work_json(result, args.issue, repository)
    result = recover_work(root, repository=repository, issue_number=args.issue,
                          adc_comment_id=verified.pointer.comment_id, adc_sha256=verified.pointer.sha256,
                          expected_branch_ref=args.branch_ref)
    return _work_json(result, args.issue, repository)


def _pr_ensure(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    _issue, verified = _approved_issue_adc(github, args.issue, repository)
    binding_path = execution_binding_path(root, args.issue)
    if (args.issue == 63 and repository.casefold() == "puchinya/ai-agent-workflow"
            and not binding_path.exists()
            and (adoption_path(root).exists() or adoption_path(root).is_symlink())):
        adopted_readback = verify_adopted_execution(
            github, root, expected_adc_comment_id=verified.pointer.comment_id,
            expected_adc_sha256=verified.pointer.sha256, allow_pr_head_advance=True,
        )
        identity = adopted_readback["epoch"]
        if not isinstance(identity, AdoptedExecutionEpoch):
            raise CLIError("Issue #63 adoption artifacts did not resolve to an adopted execution epoch")
        if args.branch_ref != identity.branch_ref or args.base_ref != identity.selected_base_ref:
            raise CLIError("PR ensure refs differ from the immutable adopted PR identity")
        body = _safe_file_bytes(args.body_file, "PR body file", root=root).decode("utf-8", errors="strict")
        pull = github.pull_request(identity.pr_number)
        if pull.get("title") != args.title or pull.get("body") != body:
            raise CLIError("adopted PR ensure is readback-only and cannot alter PR title or body")
        result = append_adopted_pr_binding(
            github, root, expected_adc_comment_id=verified.pointer.comment_id,
            expected_adc_sha256=verified.pointer.sha256,
        )
        current = result["pr"]
        pr_binding = result["pr_binding"]
        _json({"status": result["status"], "repository": repository, "issue": 63,
               "pr": identity.pr_number, "url": current.get("html_url"), "state": current.get("state"),
               "draft": current.get("draft"), "base_ref": identity.selected_base_ref,
               "base_sha40": result["current_base_sha40"],
               "frozen_base_sha40": identity.selected_base_sha40,
               "head_ref": identity.branch_ref, "head_sha40": result["current_head_sha40"],
               "adoption_id": identity.adoption_id, "pr_binding_sha256": pr_binding.sha256,
               "reasons": [], "evidence_refs": [str(adoption_path(root)), str(binding_path.with_name(
                   "pr-binding-000001.json")), str(pr_binding_path(root, 63, github=github))]})
        return 0
    binding = read_binding(binding_path)
    body = _safe_file_bytes(args.body_file, "PR body file", root=root).decode("utf-8", errors="strict")
    result = ensure_pull_request(
        root, github, repository=repository, issue_number=args.issue, binding=binding,
        branch_ref=args.branch_ref, base_ref=args.base_ref, title=args.title, body=body,
    )
    _issue, current_verified = _approved_issue_adc(github, args.issue, repository)
    if current_verified.pointer != verified.pointer:
        raise CLIError("ADC pointer changed during PR ensure; the PR remains open but no newer binding was written")
    if (not worktree_clean(root) or current_branch(root) != args.branch_ref
            or head_sha40(root) != result.binding.pr_head_sha40
            or remote_branch_sha(root, args.branch_ref) != result.binding.pr_head_sha40):
        raise CLIError("worktree or remote branch changed during final PR/ADC readback")
    pull = result.pull_request
    _json({"status": "PR_READY", "repository": repository, "issue": args.issue,
           "pr": pull.get("number"), "url": pull.get("html_url"), "state": pull.get("state"),
           "draft": pull.get("draft"), "base_ref": args.base_ref,
           "base_sha40": result.pull_request.get("base", {}).get("sha"),
           "frozen_base_sha40": result.binding.base_sha40,
           "current_base_advance_sha256": result.binding.current_base_advance_sha256,
           "head_ref": args.branch_ref,
           "head_sha40": result.binding.pr_head_sha40, "reused": result.reused,
           "pr_binding_sha256": result.binding.sha256,
           "checkpoint_path": str(result.checkpoint_path),
           "checkpoint_sha256": result.checkpoint_sha256,
           "reasons": [], "evidence_refs": [str(binding_path), str(pr_binding_path(root, args.issue, github=github)),
                                            str(result.checkpoint_path)]})
    return 0


def _audit_subject(args: argparse.Namespace, repository: str, root: Path,
                   github: GitHub) -> tuple[Any, VerificationSubject, tuple[str, ...], dict[str, str]]:
    _issue, verified = _approved_issue_adc(github, args.issue, repository)
    _require_current_adopted_generation(github, root, repository, args.issue, verified)
    plan, _required, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified)
    subject = _subject(repository, args.issue, args.pr, args.head, verified, plan)
    try:
        checklist_text = verified.contract.section("reviewer_checklist")
    except (KeyError, ValueError) as exc:
        raise CLIError("ADC reviewer checklist is missing") from exc
    checklist_rows = [match.group(1) for line in checklist_text.splitlines()
                      if line.strip() and (match := CHECKLIST_LINE.fullmatch(line))]
    if not checklist_rows:
        raise CLIError("ADC reviewer checklist has no valid checklist entries")
    checklist_labels = {f"checklist:{index:02d}": label
                        for index, label in enumerate(checklist_rows, start=1)}
    required = tuple(sorted((*verified.contract.requirement_ids, *checklist_labels)))
    if len(set(required)) != len(required):
        raise CLIError("ADC requirement and checklist identifiers are not unique")
    return verified, subject, required, checklist_labels


def _verified_file_evidence(root: Path, reference: Any) -> tuple[str, str]:
    if not isinstance(reference, str):
        raise CLIError("evidence reference must be text")
    match = FILE_EVIDENCE_REF.fullmatch(reference)
    if match is None:
        raise CLIError("evidence reference must use path#sha256=<64 lowercase hex>")
    name, expected = match.groups()
    if Path(name).is_absolute() or "\\" in name or any(part in {"", ".", ".."} for part in name.split("/")):
        raise CLIError("evidence reference path must be a canonical repository-relative path")
    path = root
    for part in name.split("/"):
        path = path / part
        if path.is_symlink():
            raise CLIError("evidence reference must not traverse a symbolic link")
    if not path.is_file():
        raise CLIError(f"evidence reference file is missing: {name}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise CLIError(f"evidence reference digest changed: {name}")
    return f"{name}#sha256={actual}", actual


def _audit_self(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    verified, subject, required, checklist_labels = _audit_subject(args, repository, root, github)
    value = _read_json(args.input, "self-audit input", root=root)
    if (not isinstance(value, dict) or set(value) != {"items", "schema", "subject"}
            or value.get("schema") != "PASES_SELF_AUDIT_INPUT_V1"
            or VerificationSubject.from_dict(value.get("subject")) != subject
            or not isinstance(value.get("items"), list)):
        raise CLIError("self-audit input is stale or has unknown/missing fields")
    rows: list[AuditItem] = []
    for row in value["items"]:
        if not isinstance(row, dict) or set(row) != {"evidence_refs", "item_id", "status"}:
            raise CLIError("self-audit item has unknown/missing fields")
        if not isinstance(row["evidence_refs"], list):
            raise CLIError("self-audit evidence_refs must be an array")
        refs = tuple(_verified_file_evidence(root, ref)[0] for ref in row["evidence_refs"])
        rows.append(AuditItem(row["item_id"], row["status"], refs).validate())
    audit = SelfAudit(subject, tuple(sorted(rows, key=lambda row: row.item_id))).validate(required)
    path = root / ".p_ases" / "audits" / str(args.issue) / subject.sha256 / f"self-{audit.sha256}.json"
    write_self_audit(path, audit, required)
    _json({"status": audit.status, "subject": subject.as_dict(), "subject_sha256": subject.sha256,
           "audit_sha256": audit.sha256, "path": str(path), "required_items": list(required),
           "checklist_labels": checklist_labels, "adc_comment_id": verified.pointer.comment_id,
           "reasons": [] if audit.status == "PASS" else ["self-audit contains non-PASS items"],
           "evidence_refs": [str(path), *[ref for row in audit.items for ref in row.evidence_refs]]})
    return 0 if audit.status == "PASS" else 2


def _audit_independent(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    _verified, subject, _required, _checklist_labels = _audit_subject(args, repository, root, github)
    value = _read_json(args.input, "independent-review context artifact", root=root)
    expected = {"context_id", "findings", "provenance", "reviewed_head_sha40", "schema",
                "session_description", "subject", "verdict"}
    if (not isinstance(value, dict) or set(value) != expected
            or value.get("schema") != "PASES_INDEPENDENT_REVIEW_CONTEXT_V1"
            or VerificationSubject.from_dict(value.get("subject")) != subject
            or value.get("reviewed_head_sha40") != subject.pr_head_sha40
            or not isinstance(value.get("findings"), list)):
        raise CLIError("independent-review artifact is stale or has unknown/missing fields")
    if any(not isinstance(value.get(field), str) or not value[field].strip()
           for field in ("context_id", "session_description", "verdict")):
        raise CLIError("independent-review child result is incomplete")
    binding = _read_execution_identity(github, root, repository, args.issue, _verified)
    implementation_context = execution_identity_context_id(binding)
    provenance_text = value.get("provenance")
    if not isinstance(provenance_text, str):
        raise CLIError("independent-review provenance must be text")
    provenance: dict[str, Any] = {}
    if provenance_text.strip():
        try:
            decoded_provenance = json.loads(provenance_text, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise CLIError("independent-review provenance is not valid JSON") from exc
        if (not isinstance(decoded_provenance, dict)
                or set(decoded_provenance) - {"spawn_session_id", "reviewer_id", "implementation_binding_id"}
                or _canonical(decoded_provenance).decode("utf-8") != provenance_text):
            raise CLIError("independent-review provenance is not a canonical host-identity object")
        provenance = decoded_provenance
    host_ids: dict[str, str | int | None] = {
        name: provenance.get(name)
        for name in ("spawn_session_id", "reviewer_id", "implementation_binding_id")
    }
    for name, identity in host_ids.items():
        if identity is None:
            continue
        if (isinstance(identity, bool) or not isinstance(identity, (str, int))
                or isinstance(identity, str) and (not identity.strip() or identity != identity.strip())
                or isinstance(identity, int) and identity < 1):
            raise CLIError(f"independent-review {name} is malformed")
    reported_binding_id = host_ids["implementation_binding_id"]
    if reported_binding_id is not None and reported_binding_id != implementation_context:
        raise CLIError("independent-review host binding identity does not match the current execution")
    if any(str(host_ids[name]) == implementation_context
           for name in ("spawn_session_id", "reviewer_id") if host_ids[name] is not None):
        raise CLIError("independent-review provenance identifies the implementation context")
    findings: list[ReviewFinding] = []
    for row in value["findings"]:
        if not isinstance(row, dict) or set(row) != {"description", "evidence_ref", "finding_id", "resolved", "severity"}:
            raise CLIError("independent-review finding has unknown/missing fields")
        evidence_ref, _digest = _verified_file_evidence(root, row["evidence_ref"])
        findings.append(ReviewFinding(row["finding_id"], row["severity"], row["resolved"],
                                      row["description"], evidence_ref).validate())
    findings.sort(key=lambda item: item.finding_id)
    raw = _safe_file_bytes(args.input, "independent-review context artifact", root=root)
    context_dir = root / ".p_ases" / "audits" / str(args.issue) / subject.sha256
    context_path = context_dir / f"review-context-{hashlib.sha256(raw).hexdigest()}.json"
    _write_immutable(context_path, raw, root=root)
    context_ref = str(context_path.relative_to(root))
    confidence = "HIGH" if all(identity is not None for identity in host_ids.values()) else "LIMITED"
    review = IndependentReviewV2(
        subject=subject, reviewer_context_id=value["context_id"],
        implementation_context_id=implementation_context, context_artifact_ref=context_ref,
        context_artifact_sha256=hashlib.sha256(raw).hexdigest(), findings=tuple(findings), verdict=value["verdict"],
        provenance_confidence=confidence, spawn_session_id=host_ids["spawn_session_id"],
        reviewer_id=host_ids["reviewer_id"], implementation_binding_id=host_ids["implementation_binding_id"],
    ).validate()
    path = root / ".p_ases" / "audits" / str(args.issue) / subject.sha256 / f"independent-{review.sha256}.json"
    write_independent_review(path, review)
    _json({"status": review.verdict, "subject": subject.as_dict(), "subject_sha256": subject.sha256,
           "review_sha256": review.sha256, "review_schema": "PASES_INDEPENDENT_REVIEW_V2",
           "reviewer_context_id": review.reviewer_context_id,
           "implementation_context_id": review.implementation_context_id,
           "provenance_confidence": review.provenance_confidence,
           "spawn_session_id": review.spawn_session_id, "reviewer_id": review.reviewer_id,
           "implementation_binding_id": review.implementation_binding_id,
           "path": str(path), "context_artifact": str(context_path),
           "reasons": [] if review.verdict == "PASS" else ["independent review did not PASS"],
           "evidence_refs": [str(path), str(args.input), str(context_path), *[row.evidence_ref for row in findings]]})
    return 0 if review.verdict == "PASS" and not review.blocking_findings else 2


def _readback_readiness_pr(github: GitHub, repository: str, issue_number: int,
                           pr_number: int) -> PRReadback:
    row = github.pull_request(pr_number)
    base, head = row.get("base"), row.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    body = row.get("body")
    try:
        association_mode = parse_issue_association(body, issue_number)
    except WorkError as exc:
        raise CLIError(f"PR Issue association is invalid: {exc}") from exc
    if issue_number == 63 and (pr_number != 64 or association_mode != "deferred_close"):
        raise CLIError("Issue #63 deferred delivery requires existing PR #64 with standalone Refs #63")
    if (not isinstance(base, dict) or not isinstance(head, dict)
            or not isinstance(base_repo, dict) or not isinstance(head_repo, dict)
            or not isinstance(base_repo.get("full_name"), str)
            or base_repo["full_name"].lower() != repository.lower()
            or not isinstance(head_repo.get("full_name"), str)
            or not isinstance(body, str)):
        raise CLIError("PR readback lacks exact same-repository identity or a valid Issue association")
    return PRReadback(
        repository=repository, issue_number=issue_number, pr_number=pr_number,
        state=row.get("state"), draft=row.get("draft"),
        base_ref=base.get("ref"), base_sha40=base.get("sha"),
        head_ref=head.get("ref"), head_sha40=head.get("sha"),
        head_repository=head_repo["full_name"], closing_issue_number=issue_number,
        close_on_merge=association_mode == "auto_close",
    ).validate()


def _current_base_evidence_for_pr(root: Path, github: GitHub, repository: str,
                                  issue_number: int, execution_binding: Any,
                                  pr_binding: PRBinding, raw_pr: dict[str, Any]
                                  ) -> CurrentBaseAdvanceEvidence | None:
    _base_ref, frozen_base_sha = execution_identity_base(execution_binding)
    base = raw_pr.get("base") if isinstance(raw_pr, dict) else None
    current_base = base.get("sha") if isinstance(base, dict) else None
    if (current_base == frozen_base_sha and pr_binding.current_base_sha40 is None
            and pr_binding.current_base_advance_sha256 is None):
        return None
    profile = load_profile(root)
    if profile.activation_issue_number is None:
        raise CLIError("Activation-owned base advance has no configured Activation Issue")
    try:
        return verify_current_base_advance(
            root, github, repository=repository, issue_number=issue_number,
            execution_binding=execution_binding, prior_pr_binding=pr_binding,
            current_pr=raw_pr, activation_issue_number=profile.activation_issue_number,
        )
    except CurrentBaseError as exc:
        raise CLIError(f"current base is not the exact verified Activation transition: {exc}") from exc


def _read_audit_references(root: Path, audit: SelfAudit | IndependentReview | IndependentReviewV2) -> tuple[str, ...]:
    references: list[str] = []
    if isinstance(audit, SelfAudit):
        refs = [ref for item in audit.items for ref in item.evidence_refs]
    else:
        refs = [audit.context_artifact_ref, *(item.evidence_ref for item in audit.findings)]
    for ref in refs:
        if isinstance(audit, (IndependentReview, IndependentReviewV2)) and ref == audit.context_artifact_ref:
            if (not isinstance(ref, str) or Path(ref).is_absolute() or "\\" in ref
                    or any(part in {"", ".", ".."} for part in ref.split("/"))):
                raise CLIError("independent-review context reference is not a canonical workspace-relative path")
            path = root / ref
            try:
                raw = _safe_file_bytes(path, "independent-review context artifact", root=root)
            except (CLIError, OSError) as exc:
                raise CLIError(f"independent-review context artifact cannot be read back: {exc}") from exc
            if hashlib.sha256(raw).hexdigest() != audit.context_artifact_sha256:
                raise CLIError("independent-review context artifact digest changed")
            references.append(str(path))
            continue
        _canonical_ref, _digest = _verified_file_evidence(root, ref)
        references.append(ref)
    return tuple(references)


def _delivery_gate_policy(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    selected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        fixed_migration = (repository.casefold() == BOOTSTRAP_REPOSITORY.casefold()
                           and args.issue in BOOTSTRAP_COHORT)
        activation_issue_number = None
        if not fixed_migration:
            try:
                profile = load_profile(root)
            except ProfileError as exc:
                raise GatePolicyError(f"consumer gate selection requires a valid project.json: {exc}") from exc
            try:
                if discover_repository(root).casefold() != repository.casefold():
                    raise GatePolicyError("GitHub repository does not match the active workspace origin")
            except GitError as exc:
                raise GatePolicyError(f"could not resolve the active repository from this workspace: {exc}") from exc
            activation_issue_number = profile.activation_issue_number
        issue = github.issue(args.issue)
        if issue.get("state") != "open" or issue.get("pull_request") is not None:
            raise GatePolicyError("gate policy selection requires an open Issue")
        selection = choose_gate_for_new_issue(
            github, repository, args.issue, selected_at,
            activation_issue_number=activation_issue_number,
        )
        if selection is None:
            _json({"status": "UNDETERMINED", "repository": repository, "issue": args.issue,
                   "policy": None, "reasons": ["no valid post-activation gate selection is available; activation may be absent/invalid or this Issue may predate activation"]})
            return 2
        comment_id, _body = pin_gate_selection(github, selection)
        if selection.policy_version == BOOTSTRAP_POLICY:
            status = "BOOTSTRAP_BLOCKED"
            reason = "Bootstrap quality checks have not been evaluated for this exact PR subject"
        else:
            status = "PASES_GATE_REQUIRED"
            reason = "normal P-ASES Review Readiness is required for work started after activation"
        _json({"status": status, "repository": repository, "issue": args.issue,
               "policy": selection.policy_version, "gate_selection_comment_id": comment_id,
               "reasons": [reason]})
        return 2 if status == "BOOTSTRAP_BLOCKED" else 0
    except (GatePolicyError, GitHubError) as exc:
        _json({"status": "UNDETERMINED", "repository": repository, "issue": args.issue,
               "policy": None, "reasons": [str(exc)]})
        return 2


def _bootstrap_pr_identity(pr: dict[str, Any]) -> tuple[Any, ...]:
    """Return all PR fields that identify the Bootstrap subject and Issue association."""
    def repo_identity(value: Any) -> tuple[Any, Any]:
        if not isinstance(value, dict):
            return None, None
        full_name = value.get("full_name")
        return (full_name.casefold() if isinstance(full_name, str) else None,
                value.get("id") if type(value.get("id")) is int else None)

    base, head = pr.get("base"), pr.get("head")
    base = base if isinstance(base, dict) else {}
    head = head if isinstance(head, dict) else {}
    return (pr.get("number"), pr.get("state"), pr.get("draft"),
            repo_identity(base.get("repo")), base.get("ref"), base.get("sha"),
            repo_identity(head.get("repo")), head.get("ref"), head.get("sha"),
            pr.get("body"))


def _verify_live_bootstrap_subject(github: GitHub, issue_number: int, pr_number: int,
                                   repository: str, root: Path, subject: BootstrapSubject,
                                   initial_adc: Any, initial_pr: dict[str, Any],
                                   gate_comment_id: int, gate_selection: GateSelection,
                                   gate_selection_body: str) -> None:
    """Re-read the complete PR/ADC/gate identity and require it to match the initial snapshot."""
    current_checkout_subject(root, subject)
    current_adc = read_bootstrap_adc(github, issue_number)
    if current_adc.pointer != initial_adc.pointer:
        raise GatePolicyError("current ADC pointer changed during Bootstrap verification")
    current_pr = github.pull_request(pr_number)
    validate_bootstrap_pr_identity(subject, current_pr, repository)
    if _bootstrap_pr_identity(current_pr) != _bootstrap_pr_identity(initial_pr):
        raise GatePolicyError("current PR identity or Issue-closing body changed during Bootstrap verification")
    current_selection = choose_gate_for_new_issue(
        github, repository, issue_number, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if (current_selection is None or current_selection.issue_number != issue_number
            or current_selection.repository.casefold() != repository.casefold()
            or current_selection.policy_version != gate_selection.policy_version):
        raise GatePolicyError("current fixed gate selection changed during Bootstrap verification")
    current_gate_id, pinned_selection, current_gate_body = read_gate_selection(github, issue_number)
    if (current_gate_id != gate_comment_id or pinned_selection.payload() != gate_selection.payload()
            or current_gate_body != gate_selection_body):
        raise GatePolicyError("pinned gate selection identity changed during Bootstrap verification")


def _publish_bootstrap_observation(github: GitHub, issue_number: int,
                                   result: BootstrapResult) -> int:
    """Publish and verify that this exact append-only observation is the latest one."""
    expected = result.payload()
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            comment_id, _body = publish_immutable_record(
                github, issue_number, "PASES_BOOTSTRAP_REVIEW_V1", expected)
            if read_bootstrap_evidence(github, issue_number, comment_id) != expected:
                raise GatePolicyError("Bootstrap evidence payload readback does not match the current result")
        except (GatePolicyError, GitHubError) as exc:
            last_error = exc
        else:
            last_error = None
        try:
            latest = read_latest_bootstrap_evidence(github, issue_number)
            if latest is not None and latest[1] == expected:
                return latest[0]
            last_error = GatePolicyError("published Bootstrap result is not the latest append-only observation")
        except (GatePolicyError, GitHubError) as exc:
            last_error = exc
    detail = f": {last_error}" if last_error is not None else ""
    raise GatePolicyError(f"Bootstrap evidence publish/readback did not become current{detail}")


def _append_blocked_bootstrap_observation(github: GitHub, issue_number: int,
                                          result: BootstrapResult,
                                          reasons: tuple[str, ...]) -> tuple[BootstrapResult, int]:
    blocked = replace(result, status="BOOTSTRAP_BLOCKED",
                      reasons=tuple(dict.fromkeys(result.reasons + reasons))).validate()
    return blocked, _publish_bootstrap_observation(github, issue_number, blocked)


def _delivery_bootstrap_check(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    reasons: list[str] = []
    try:
        bootstrap_adc = read_bootstrap_adc(github, args.issue)
        pr = github.pull_request(args.pr)
        base, head = pr.get("base"), pr.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            raise GatePolicyError("current PR base/head readback is incomplete")
        base_sha, head_sha = base.get("sha"), head.get("sha")
        if not isinstance(base.get("ref"), str) or not isinstance(base_sha, str):
            raise GatePolicyError("current PR base ref/SHA readback is incomplete")
        if not isinstance(head.get("ref"), str) or not isinstance(head_sha, str):
            raise GatePolicyError("current PR head ref/SHA readback is incomplete")
        subject = BootstrapSubject(repository, args.issue, args.pr, bootstrap_adc.pointer.comment_id,
                                  bootstrap_adc.pointer.sha256, base["ref"], base_sha,
                                  head["ref"], head_sha).validate()
        selection = choose_gate_for_new_issue(
            github, repository, args.issue, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if selection is None or selection.policy_version != BOOTSTRAP_POLICY:
            raise GatePolicyError("Issue does not resolve to the fixed Bootstrap policy")
        gate_comment_id, gate_selection_body = pin_gate_selection(github, selection)
        read_gate_id, gate_selection, read_gate_body = read_gate_selection(github, args.issue)
        if (read_gate_id != gate_comment_id or read_gate_body != gate_selection_body
                or gate_selection.issue_number != args.issue
                or gate_selection.repository.casefold() != repository.casefold()
                or gate_selection.policy_version != BOOTSTRAP_POLICY):
            raise GatePolicyError("pinned gate selection does not match the current Bootstrap subject")
    except (ADCError, GatePolicyError, GitHubError, KeyError, TypeError) as exc:
        _json({"status": "BOOTSTRAP_BLOCKED", "subject": None,
               "reasons": [f"current ADC/PR/gate selection readback failed: {exc}"],
               "evidence_refs": []})
        return 2

    if bootstrap_adc.pointer.state != "approved":
        reasons.append(f"current child ADC approval state is {bootstrap_adc.pointer.state}; explicit approved state is required")

    try:
        local_checks = run_local_bootstrap_checks_bound(root, subject)
    except (GatePolicyError, OSError) as exc:
        local_checks = ()
        reasons.append(f"local exact-head verification failed: {exc}")

    try:
        profile = load_profile(root)
        check_runs = github.check_runs_for_ref(subject.head_sha40)
        workflow_runs = github.workflow_runs_for_ref(subject.head_sha40)
        response_repository = repository
    except (ProfileError, GitHubError) as exc:
        reasons.append(f"current-head CI/profile readback failed: {exc}")
        check_runs, workflow_runs = [], []
        try:
            profile = load_profile(root)
        except ProfileError:
            profile = None

    # Recheck after local and GitHub verification; a checkout change invalidates every result.
    try:
        current_checkout_subject(root, subject)
    except GatePolicyError as exc:
        reasons.append(f"local checkout changed during Bootstrap verification: {exc}")
    required_names = tuple(name for name, _app_id in profile.required_checks) if profile else ()
    unverified_hosts = tuple(args.unverified_host)
    try:
        policy_sha256 = bootstrap_policy_digest()
    except GatePolicyError as exc:
        policy_sha256 = None
        reasons.append(f"Bootstrap policy fingerprint failed: {exc}")
    result = evaluate_bootstrap(
        subject, pr=pr, response_repository=repository, workflow_runs=workflow_runs, check_runs=check_runs,
        required_check_names=required_names, local_checks=local_checks,
        adc_requirement_ids=(), adc_checklist_ids=(),
        self_review=None, independent_review=None, unverified_hosts=unverified_hosts,
        bootstrap_policy_sha256=policy_sha256)
    if reasons:
        result = replace(result, status="BOOTSTRAP_BLOCKED",
                         reasons=tuple(dict.fromkeys(result.reasons + tuple(reasons)))).validate()

    # Re-read the complete immutable ADC, PR, and fixed gate selection before publishing.
    snapshot_stable = True
    try:
        _verify_live_bootstrap_subject(
            github, args.issue, args.pr, repository, root, subject, bootstrap_adc, pr,
            gate_comment_id, gate_selection, gate_selection_body)
    except (ADCError, GatePolicyError, GitHubError, AttributeError) as exc:
        snapshot_stable = False
        result = replace(result, status="BOOTSTRAP_BLOCKED",
                         reasons=tuple(dict.fromkeys(result.reasons + (str(exc),)))).validate()

    evidence_comment_id = None
    if snapshot_stable:
        try:
            # This final clean-checkout read is immediately before publication.
            current_checkout_subject(root, subject)
            evidence_comment_id = _publish_bootstrap_observation(github, args.issue, result)
            post_publish_failures: list[str] = []
            try:
                _verify_live_bootstrap_subject(
                    github, args.issue, args.pr, repository, root, subject, bootstrap_adc, pr,
                    gate_comment_id, gate_selection, gate_selection_body)
            except (ADCError, GatePolicyError, GitHubError, AttributeError) as exc:
                post_publish_failures.append(f"PR/ADC/gate selection changed during evidence publication: {exc}")
            try:
                current_checkout_subject(root, subject)
            except GatePolicyError as exc:
                post_publish_failures.append(f"local checkout changed during evidence publication: {exc}")
            if post_publish_failures:
                # A published READY must not remain the latest observation after any subject drift.
                result, evidence_comment_id = _append_blocked_bootstrap_observation(
                    github, args.issue, result, tuple(post_publish_failures))
        except (ADCError, GatePolicyError, GitHubError, AttributeError) as exc:
            reasons = tuple(dict.fromkeys(result.reasons + (str(exc),)))
            _json({"status": "BOOTSTRAP_BLOCKED", "subject": subject.as_dict(), "reasons": list(reasons),
                   "gate_selection_comment_id": gate_comment_id, "evidence_comment_id": evidence_comment_id,
                   "evidence_refs": ([f"Issue #{args.issue} comment {evidence_comment_id}"]
                                     if evidence_comment_id else [])})
            return 2
    _json({"status": result.status, "subject": subject.as_dict(), "reasons": list(result.reasons),
           "gate_selection_comment_id": gate_comment_id, "evidence_comment_id": evidence_comment_id,
           "evidence_sha256": result.sha256 if evidence_comment_id else None,
           "evidence_refs": ([f"Issue #{args.issue} comment {evidence_comment_id}"] if evidence_comment_id else [])})
    return 0 if result.status == "BOOTSTRAP_TECHNICAL_READY" else 2


def _issue_kind_phase(issue: Any, issue_number: int) -> tuple[IssueKind, Phase, frozenset[Attention]]:
    """Read the unique kind, phase, and attention state for lifecycle gates."""
    if (not isinstance(issue, dict) or issue.get("number") != issue_number
            or issue.get("state") != "open" or issue.get("pull_request") is not None):
        raise CLIError("workflow phase check requires the same open non-PR Issue")
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CLIError("Issue workflow labels are invalid")
    labels = [row.get("name") for row in rows]
    if any(not isinstance(label, str) for label in labels):
        raise CLIError("Issue workflow labels contain a malformed name")
    kind_values = [label.removeprefix("kind:") for label in labels if label.startswith("kind:")]
    if len(kind_values) != 1:
        raise CLIError("an open Issue must have exactly one kind:* label")
    try:
        kind = IssueKind(kind_values[0])
        phase = parse_phase_labels(labels)
        attention = parse_attention_labels(labels)
    except PhaseError as exc:
        raise CLIError(str(exc)) from exc
    return kind, phase, attention


def _readiness_phase_blocker(kind: IssueKind, phase: Phase, attention: frozenset[Attention], subject: Any,
                             result: Any, root: Path) -> str | None:
    """Allow new readiness only during verification or an exact active review session."""
    if attention:
        return ("Review Readiness cannot pass while Issue has an attention:* state; "
                "clear attention through the existing attention workflow before continuing")
    if kind not in {IssueKind.SINGLE, IssueKind.CHILD}:
        return None
    if phase is Phase.VERIFICATION:
        return None
    if phase is not Phase.USER_REVIEW:
        return (f"Review Readiness cannot pass while Issue phase is {phase.value}; "
                "single/child readiness is permitted only in verification or an exact active User Review")
    if getattr(result, "status", None) != "PASS":
        return "phase:user-review readiness may only be recomputed for the immutable active User Review session"
    try:
        review_subject = UserReviewSubject(subject, result.sha256).validate()
        session = read_review_session(review_session_path(root, review_subject))
    except (UserReviewError, OSError, AttributeError, ValueError) as exc:
        return ("phase:user-review cannot create a new Readiness PASS; an immutable session for the exact "
                f"subject and Readiness SHA is required ({exc})")
    if session.subject != review_subject:
        return "phase:user-review User Review session differs from the exact subject and Readiness SHA"
    return None


def _delivery_readiness(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    blockers: list[str] = []
    published_refs: list[str] = []
    verified_adc = None
    issue_kind: IssueKind | None = None
    issue_phase: Phase | None = None
    issue_attention: frozenset[Attention] = frozenset()
    try:
        issue_row, verified_adc = _approved_issue_adc(github, args.issue, repository)
        issue_kind, issue_phase, issue_attention = _issue_kind_phase(issue_row, args.issue)
        if issue_attention:
            blockers.append(
                "Review Readiness cannot pass while Issue has an attention:* state; "
                "clear attention through the existing attention workflow before continuing"
            )
        if (issue_kind in {IssueKind.SINGLE, IssueKind.CHILD}
                and issue_phase not in {Phase.VERIFICATION, Phase.USER_REVIEW}):
            blockers.append(
                f"Review Readiness cannot pass while Issue phase is {issue_phase.value}; "
                "single/child readiness is permitted only in verification or an exact active User Review"
            )
    except (ADCError, CLIError, GitHubError) as exc:
        blockers.append(f"current open Issue/approved ADC readback failed: {exc}")

    plan = None
    required_item_ids: tuple[str, ...] = ()
    if verified_adc is not None:
        try:
            plan, _reqs, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
        except (PlanError, OracleTraceError, CLIError, OSError) as exc:
            blockers.append(f"current Verification Plan readback failed: {exc}")

    subject = None
    if verified_adc is not None and plan is not None:
        try:
            subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
        except (CLIError, EvidenceError) as exc:
            blockers.append(f"exact readiness subject is invalid: {exc}")

    pr_readback = None
    try:
        pr_readback = _readback_readiness_pr(github, repository, args.issue, args.pr)
    except (GitHubError, CLIError, ReadinessError) as exc:
        blockers.append(f"current GitHub PR readback failed: {exc}")

    pr_binding = None
    binding: ExecutionIdentity | None = None
    binding_path = execution_binding_path(root, args.issue)
    try:
        binding = _read_execution_identity(github, root, repository, args.issue, verified_adc)
        pr_binding = read_pr_binding(pr_binding_path(root, args.issue, github=github))
        if binding.repository != repository or binding.issue_number != args.issue:
            raise CLIError("execution identity repository/Issue does not match")
        if isinstance(binding, AdoptedExecutionEpoch):
            if (pr_binding.adoption_id != binding.adoption_id
                    or pr_binding.adc_comment_id != (None if verified_adc is None else verified_adc.pointer.comment_id)
                    or pr_binding.adc_sha256 != (None if verified_adc is None else verified_adc.pointer.sha256)):
                blockers.append("adopted epoch lacks a current-generation PRBinding bridge")
        elif (binding.adc_comment_id != (None if verified_adc is None else verified_adc.pointer.comment_id)
              or binding.adc_sha256 != (None if verified_adc is None else verified_adc.pointer.sha256)):
            blockers.append("ExecutionBinding belongs to a stale ADC pointer")
    except (ExecutionError, CheckpointError, CLIError, OSError) as exc:
        blockers.append(f"current immutable work/PR binding readback failed: {exc}")

    current_base_evidence = None
    if binding is not None and pr_binding is not None and pr_readback is not None:
        try:
            current_base_evidence = _current_base_evidence_for_pr(
                root, github, repository, args.issue, binding, pr_binding, github.pull_request(args.pr),
            )
        except (CLIError, CurrentBaseError, ProfileError, GitHubError, OSError, ValueError) as exc:
            blockers.append(f"current Activation base transition readback failed: {exc}")

    work_context = None
    if binding is not None:
        try:
            work_context = WorkContext(
                binding, head_sha40(root), current_branch(root), worktree_clean(root),
                execution_identity_digest(binding),
            ).validate()
        except (GitError, ValueError) as exc:
            blockers.append(f"current local work context readback failed: {exc}")

    verification = None
    verification_args = argparse.Namespace(issue=args.issue, pr=args.pr, head=args.head, plan=args.plan)
    try:
        saved_verification = read_verification_result(args.verification)
        current_verification, _evidence_refs = _calculate_verification(
            verification_args, repository, root, github,
        )
        if saved_verification != current_verification:
            blockers.append("saved #29 Verification is stale relative to current ADC/Plan/Evidence/Checks")
        elif subject is None or saved_verification.subject != subject:
            blockers.append("saved #29 Verification does not match the current exact subject")
        else:
            verification = current_verification
            comment_id = _exact_published(github, args.issue,
                                          _result_comment("verification", current_verification.as_json()))
            if comment_id is None:
                blockers.append("exact current #29 Verification result comment is not published on the Issue")
            else:
                published_refs.append(f"issue-comment:{comment_id}")
    except (VerificationError, ADCError, PlanError, OracleTraceError, EvidenceError,
            GitHubError, CLIError, OSError) as exc:
        blockers.append(f"#29 Verification readback/recomputation failed: {exc}")

    acceptance = None
    try:
        saved_acceptance = read_acceptance_result(args.acceptance)
        current_acceptance = _acceptance_recompute_saved(
            argparse.Namespace(issue=args.issue), repository, root, github, saved_acceptance,
            verification_result=verification,
        )
        if subject is None or saved_acceptance.subject != subject or current_acceptance != saved_acceptance:
            blockers.append("saved #29 Acceptance is stale or does not match the current exact subject")
        else:
            acceptance = current_acceptance
            comment_id = _exact_published(github, args.issue,
                                          _result_comment("acceptance", current_acceptance.as_json()))
            if comment_id is None:
                blockers.append("exact current #29 Acceptance result comment is not published on the Issue")
            else:
                published_refs.append(f"issue-comment:{comment_id}")
    except (AcceptanceError, ADCError, PlanError, OracleTraceError, EvidenceError,
            VerificationError, GitHubError, CLIError, OSError) as exc:
        blockers.append(f"#29 Acceptance readback/recomputation failed: {exc}")

    self_audit = None
    independent_review = None
    if verified_adc is not None:
        try:
            checklist_text = verified_adc.contract.section("reviewer_checklist")
            checklist_rows = [match.group(1) for line in checklist_text.splitlines()
                              if line.strip() and (match := CHECKLIST_LINE.fullmatch(line))]
            required_item_ids = tuple(sorted((*verified_adc.contract.requirement_ids,
                                              *(f"checklist:{index:02d}" for index in range(1, len(checklist_rows) + 1)))))
        except (KeyError, ValueError) as exc:
            blockers.append(f"ADC self-audit checklist cannot be reconstructed: {exc}")
        try:
            self_audit = read_self_audit(args.self_audit)
            self_audit.validate(required_item_ids)
            if subject is None or self_audit.subject != subject:
                blockers.append("self-audit is stale or does not match the current exact subject")
            _read_audit_references(root, self_audit)
        except (AuditError, CLIError, OSError) as exc:
            blockers.append(f"self-audit readback/evidence validation failed: {exc}")
            self_audit = None
        try:
            independent_review = read_independent_review(args.independent_review)
            independent_review.validate()
            if subject is None or independent_review.subject != subject:
                blockers.append("independent review is stale or does not match the current exact subject")
            if (binding is not None and independent_review.implementation_context_id
                    != execution_identity_context_id(binding)):
                blockers.append("independent-review implementation context does not match the current work binding")
            _read_audit_references(root, independent_review)
        except (AuditError, CLIError, OSError) as exc:
            blockers.append(f"independent-review readback/evidence validation failed: {exc}")
            independent_review = None

    dependency_reasons: tuple[str, ...] = ()
    if verified_adc is not None:
        dependency_reasons = _unaccepted_dependencies(github, verified_adc.contract)
        blockers.extend(dependency_reasons)

    check_sha = None if verification is None else verification.check_result_sha256
    try:
        profile = load_profile(root)
        policy = profile.required_check_policy()
        if verification is None or verification.required_check_policy_sha256 != policy.sha256:
            blockers.append("current Required Check policy has no matching trusted #29 Verification")
    except (ProfileError, VerificationError) as exc:
        blockers.append(f"Required Check policy cannot be trusted: {exc}")

    if subject is not None and verified_adc is not None:
        # Earlier read-only checks may share immutable ADC history within this
        # command. Start the final gate with a fresh journal read before using
        # any cached generation evidence for persistence.
        refresh_adc_forward_generation_session(github, args.issue)
        try:
            final_issue = github.issue(args.issue)
            if final_issue.get("number") != args.issue or final_issue.get("state") != "open":
                blockers.append("Issue changed from open before Review Readiness persistence")
            elif issue_kind is not None and issue_phase is not None:
                final_kind, final_phase, final_attention = _issue_kind_phase(final_issue, args.issue)
                if (final_kind, final_phase, final_attention) != (issue_kind, issue_phase, issue_attention):
                    blockers.append("Issue kind/phase/attention changed before Review Readiness persistence")
        except (GitHubError, CLIError) as exc:
            blockers.append(f"Issue final readback failed before Readiness persistence: {exc}")
        try:
            last_adc = verify_adc(github, args.issue)
            if last_adc.pointer != verified_adc.pointer:
                blockers.append("ADC pointer changed before Review Readiness persistence")
        except (ADCError, GitHubError) as exc:
            blockers.append(f"ADC final readback failed before Readiness persistence: {exc}")
        try:
            last_pr = _readback_readiness_pr(github, repository, args.issue, args.pr)
            if last_pr != pr_readback:
                blockers.append("PR identity/base/head changed before Review Readiness persistence")
        except (GitHubError, CLIError, ReadinessError) as exc:
            blockers.append(f"PR final readback failed before Readiness persistence: {exc}")
        if current_base_evidence is not None and binding is not None and pr_binding is not None:
            try:
                final_pr_binding = read_pr_binding(pr_binding_path(root, args.issue, github=github))
                final_base_evidence = _current_base_evidence_for_pr(
                    root, github, repository, args.issue, binding, final_pr_binding, github.pull_request(args.pr),
                )
                if final_base_evidence != current_base_evidence:
                    blockers.append("Activation current-base evidence changed before Readiness persistence")
            except (CheckpointError, CLIError, CurrentBaseError, ProfileError,
                    GitHubError, OSError, ValueError) as exc:
                blockers.append(f"Activation current-base final readback failed before Readiness persistence: {exc}")
        try:
            if (current_branch(root) != (None if pr_readback is None else pr_readback.head_ref)
                    or head_sha40(root) != subject.pr_head_sha40 or not worktree_clean(root)
                    or (pr_readback is not None
                        and remote_branch_sha(root, pr_readback.head_ref) != subject.pr_head_sha40)):
                blockers.append("local worktree or remote branch changed before Readiness persistence")
        except GitError as exc:
            blockers.append(f"local/remote branch final readback failed before Readiness persistence: {exc}")
        last_verification = None
        if verification is not None:
            try:
                last_verification, _last_refs = _calculate_verification(
                    verification_args, repository, root, github,
                )
                if last_verification != verification:
                    blockers.append("#29 Verification/Required Checks changed before Readiness persistence")
            except (VerificationError, ADCError, PlanError, OracleTraceError, EvidenceError,
                    GitHubError, CLIError, OSError) as exc:
                blockers.append(f"#29 final Verification/Check Runs readback failed: {exc}")
        if acceptance is not None:
            try:
                last_acceptance = _acceptance_recompute_saved(
                    argparse.Namespace(issue=args.issue), repository, root, github, acceptance,
                    verification_result=last_verification,
                )
                if last_acceptance != acceptance:
                    blockers.append("#29 Acceptance changed before Readiness persistence")
            except (AcceptanceError, ADCError, PlanError, OracleTraceError, EvidenceError,
                    VerificationError, GitHubError, CLIError, OSError) as exc:
                blockers.append(f"#29 final Acceptance readback failed: {exc}")
        if binding is not None:
            try:
                final_binding = _read_execution_identity(github, root, repository, args.issue, verified_adc)
                final_pr_binding = read_pr_binding(pr_binding_path(root, args.issue, github=github))
                if final_binding != binding or final_pr_binding != pr_binding:
                    blockers.append("immutable execution identity or PRBinding changed before Readiness persistence")
            except (ExecutionError, CheckpointError, OSError) as exc:
                blockers.append(f"work binding final readback failed before Readiness persistence: {exc}")
        if self_audit is not None:
            try:
                final_audit = read_self_audit(args.self_audit)
                final_audit.validate(required_item_ids)
                if final_audit != self_audit:
                    blockers.append("self-audit changed before Readiness persistence")
                _read_audit_references(root, final_audit)
            except (AuditError, CLIError, OSError) as exc:
                blockers.append(f"self-audit final readback failed before Readiness persistence: {exc}")
        if independent_review is not None:
            try:
                final_review = read_independent_review(args.independent_review)
                if final_review != independent_review:
                    blockers.append("independent review changed before Readiness persistence")
                _read_audit_references(root, final_review)
            except (AuditError, CLIError, OSError) as exc:
                blockers.append(f"independent-review final readback failed before Readiness persistence: {exc}")

    # Re-read the lifecycle labels immediately before evaluating/persisting Readiness.
    # In particular, attention must not change between the earlier gate checks and a new PASS.
    if subject is not None and issue_kind is not None and issue_phase is not None:
        try:
            latest_issue = github.issue(args.issue)
            latest_kind, latest_phase, latest_attention = _issue_kind_phase(latest_issue, args.issue)
            if (latest_kind, latest_phase, latest_attention) != (issue_kind, issue_phase, issue_attention):
                blockers.append("Issue kind/phase/attention changed immediately before Readiness evaluation")
            if latest_attention:
                blocker = (
                    "Review Readiness cannot pass while Issue has an attention:* state; "
                    "clear attention through the existing attention workflow before continuing"
                )
                if blocker not in blockers:
                    blockers.append(blocker)
        except (GitHubError, CLIError) as exc:
            blockers.append(f"Issue phase/attention final readback failed before Readiness evaluation: {exc}")

    if subject is None:
        _json({"status": "BLOCKED", "subject": None, "subject_sha256": None,
               "reasons": blockers or ["exact readiness subject is unavailable"], "evidence_refs": []})
        return 2

    # A complete evaluator result is still emitted when external inputs are missing.
    result = evaluate_readiness(
        subject=subject, pr=pr_readback, pr_binding=pr_binding, work_context=work_context,
        verification=verification, acceptance=acceptance, self_audit=self_audit,
        required_item_ids=required_item_ids, independent_review=independent_review,
        required_checks_sha256=check_sha, blocker_reasons=blockers,
        current_base_advance=current_base_evidence,
    )
    if issue_kind is not None and issue_phase is not None:
        phase_blocker = _readiness_phase_blocker(
            issue_kind, issue_phase, issue_attention, subject, result, root,
        )
        if phase_blocker is not None and phase_blocker not in blockers:
            blockers.append(phase_blocker)
            result = evaluate_readiness(
                subject=subject, pr=pr_readback, pr_binding=pr_binding, work_context=work_context,
                verification=verification, acceptance=acceptance, self_audit=self_audit,
                required_item_ids=required_item_ids, independent_review=independent_review,
                required_checks_sha256=check_sha, blocker_reasons=blockers,
                current_base_advance=current_base_evidence,
            )
    path = readiness_path(root, result)
    write_readiness(path, result)
    review_schema = ("PASES_INDEPENDENT_REVIEW_V2" if isinstance(independent_review, IndependentReviewV2)
                     else "PASES_INDEPENDENT_REVIEW_V1" if isinstance(independent_review, IndependentReview)
                     else None)
    review_confidence = (independent_review.provenance_confidence
                         if isinstance(independent_review, IndependentReviewV2)
                         else "LEGACY_UNSPECIFIED" if isinstance(independent_review, IndependentReview)
                         else None)
    missing_host_ids = ([name for name in ("spawn_session_id", "reviewer_id", "implementation_binding_id")
                         if getattr(independent_review, name) is None]
                        if isinstance(independent_review, IndependentReviewV2) else [])
    _json({"status": result.status, "subject": result.subject.as_dict(),
           "subject_sha256": result.subject.sha256, "readiness_sha256": result.sha256,
           "independent_review_schema": review_schema,
           "independent_review_provenance_confidence": review_confidence,
           "independent_review_missing_host_ids": missing_host_ids,
           "ready_for_user_review": result.ready_for_user_review, "path": str(path),
           "reasons": list(result.reasons),
           "evidence_refs": [str(path), str(args.plan), str(args.verification), str(args.acceptance),
                             str(args.self_audit), str(args.independent_review),
                             str(execution_binding_path(root, args.issue)),
                             str(pr_binding_path(root, args.issue, github=github)),
                             *([str(current_base_advance_path(root, args.issue))]
                               if current_base_evidence is not None else []), *published_refs]})
    return 0 if result.status == "PASS" else 2


def _review_payload_from_github(github: GitHub, subject: UserReviewSubject,
                                *, observed_at: str) -> FeedbackSnapshot:
    verification_subject = subject.verification_subject
    issue_comments = github.issue_comments(verification_subject.issue_number)
    pr_comments = github.pull_conversation_comments(verification_subject.pr_number)
    pr_reviews = github.pull_reviews(verification_subject.pr_number)
    diff_comments = github.pull_diff_comments(verification_subject.pr_number)
    threads = github.pull_review_threads(verification_subject.pr_number)
    if any(not isinstance(thread, dict) for thread in threads):
        raise GitHubError("GitHub review thread readback is malformed")
    unresolved = tuple(sorted(thread["id"] for thread in threads
                              if thread.get("isResolved") is False and thread.get("isOutdated") is False))
    events = normalize_github_feedback(issue_comments=issue_comments, pr_comments=pr_comments,
                                       pr_reviews=pr_reviews, diff_comments=diff_comments)
    ordered = tuple(sorted(events, key=lambda row: (row.channel, row.event_id)))
    return FeedbackSnapshot(subject, ordered, unresolved, observed_at).validate()


def _latest_review_snapshot(root: Path, subject: UserReviewSubject) -> FeedbackSnapshot | None:
    folder = Path(root).absolute() / ".p_ases" / "user-review" / str(subject.verification_subject.issue_number) / subject.sha256
    if path_has_symlink(folder):
        raise UserReviewError("User Review history path must not traverse a symbolic link")
    if not folder.exists():
        return None
    if not folder.is_dir():
        raise UserReviewError("User Review history path is not a directory")
    snapshots: list[FeedbackSnapshot] = []
    for path in folder.iterdir():
        if path.name == "session.json":
            continue
        if re.fullmatch(r"[0-9a-f]{64}-[0-9a-f]{64}\.result\.json", path.name):
            continue
        match = re.fullmatch(r"([0-9a-f]{64})\.json", path.name)
        if match is None:
            raise UserReviewError(f"unexpected file in User Review history: {path.name}")
        item = read_feedback_snapshot(path)
        if item.sha256 != match.group(1):
            raise UserReviewError("User Review snapshot filename does not match its content digest")
        if item.subject == subject:
            snapshots.append(item)
    return max(snapshots, key=lambda item: item.observed_at) if snapshots else None


def _review_record_path(root: Path, issue_number: int, subject: UserReviewSubject,
                        result: UserReviewResult, snapshot_sha256: str) -> Path:
    return (Path(root).absolute() / ".p_ases" / "user-review" / str(issue_number)
            / subject.sha256 / f"{result.sha256}-{snapshot_sha256}.result.json")


def _read_review_record(path: Path) -> tuple[UserReviewSubject, UserReviewResult, str]:
    value = _read_json(path, "User Review result")
    expected = {"result", "result_sha256", "schema", "snapshot_sha256", "subject"}
    if (not isinstance(value, dict) or set(value) != expected
            or value.get("schema") not in {"PASES_USER_REVIEW_RESULT_V1", "PASES_USER_REVIEW_RESULT_V2"}):
        raise UserReviewError("User Review result record has unknown or missing fields")
    result = UserReviewResult.from_dict(value["result"])
    if ((value["schema"] == "PASES_USER_REVIEW_RESULT_V2") !=
            (result.selected_approval_evidence is not None)):
        raise UserReviewError("dedicated carrier requires V2 User Review result schema")
    if value["subject"] != result.subject.as_dict() or value["result_sha256"] != result.sha256:
        raise UserReviewError("User Review result record subject/digest does not match")
    if not isinstance(value["snapshot_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["snapshot_sha256"]):
        raise UserReviewError("User Review snapshot digest is invalid")
    return result.subject, result, value["snapshot_sha256"]


_ISSUE63_REPOSITORY_ID = 1401910271
_ISSUE63_OWNER_ID = 3744776


def _ruleset_operation_plan(github: GitHub, plan_path: Path) -> tuple[dict[str, Any], int | None]:
    """Require the separate exact-plan owner decision before any Ruleset write path."""
    plan = read_ruleset_plan(plan_path)
    if (github.repo.casefold() != "puchinya/ai-agent-workflow"
            or plan["repository_id"] != _ISSUE63_REPOSITORY_ID
            or plan["owner_id"] != _ISSUE63_OWNER_ID or plan["activation_issue_number"] != 57):
        raise CLIError("Ruleset owner relay is configured only for the approved #63 repository/Activation Issue")
    if plan["diff"]["operation"] == "noop":
        return plan, None
    verified = read_verified_owner_decision(
        github, issue_number=63, owner_id=_ISSUE63_OWNER_ID,
        operation="RULESET_PLAN_APPLY", subject_sha256=plan["plan_sha256"],
        repository_id=_ISSUE63_REPOSITORY_ID,
    )
    if (verified.decision.schema in {"PASES_OWNER_DECISION_V2", "PASES_OWNER_DECISION_V3"}
            and verified.decision.operation_plan_sha256 != plan["plan_sha256"]):
        raise OwnerDecisionError("owner-local RULESET_PLAN_APPLY decision is bound to another plan")
    return plan, verified.comment_id


def _user_review_owner_context(args: argparse.Namespace, repository: str,
                               github: GitHub) -> dict[str, Any]:
    github = _read_only_github(github)
    if args.session is None or args.readiness is None or args.feedback_snapshot is None:
        raise OwnerAuthorizationError(
            "USER_REVIEW requires --session, --readiness, and --feedback-snapshot"
        )
    session = read_review_session(args.session)
    readiness = read_readiness(args.readiness)
    snapshot = read_feedback_snapshot(args.feedback_snapshot)
    subject = session.subject
    verification_subject = subject.verification_subject
    if (verification_subject.repository != repository
            or verification_subject.issue_number != 63 or snapshot.subject != subject
            or readiness.status != "PASS" or readiness.subject != verification_subject
            or readiness.sha256 != subject.readiness_sha256
            or snapshot.unresolved_thread_ids):
        raise OwnerAuthorizationError("User Review session, Readiness, feedback snapshot, or Issue identity is stale")
    _solo_owner_identity(github, repository, 63, verification_subject.pr_number,
                         verification_subject.pr_head_sha40)
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    current = _review_payload_from_github(github, subject, observed_at=observed_at)
    if (current.events != snapshot.events
            or current.unresolved_thread_ids != snapshot.unresolved_thread_ids):
        raise OwnerAuthorizationError("current complete GitHub feedback differs from the User Review snapshot")
    details = {
        "review_session_sha256": session.sha256,
        "readiness_sha256": readiness.sha256,
        "adc_sha256": verification_subject.adc_sha256,
        "pr_head_sha40": verification_subject.pr_head_sha40,
        "feedback_sha256": feedback_digest(current.events),
    }
    subject_sha256 = hashlib.sha256(_canonical({
        "repository": repository, "issue_number": 63,
        "pr_number": verification_subject.pr_number, **details,
    })).hexdigest()
    return {"session": session, "readiness": readiness, "snapshot": snapshot,
            "details": details, "subject_sha256": subject_sha256,
            "pr_number": verification_subject.pr_number,
            "pr_head_sha40": verification_subject.pr_head_sha40}


def _owner_authorization_plan_command(args: argparse.Namespace, repository: str,
                                     root: Path, github: GitHub) -> int:
    operation = args.operation
    details: dict[str, Any] = {}
    target_issue: int | None = None
    pr_number: int | None = None
    pr_head: str | None = None
    if operation == "ADC_SUPERSEDE":
        if args.subject_file is None or args.ruleset_plan is not None:
            raise OwnerAuthorizationError("ADC_SUPERSEDE plan requires --subject-file")
        path = args.subject_file
        if path.is_symlink() or not path.is_file():
            raise OwnerAuthorizationError("ADC successor source must be a regular file")
        raw = path.read_bytes()
        adc = parse_adc(raw, repository, 63)
        subject_sha256 = hashlib.sha256(raw).hexdigest()
        if adc.issue_number != 63:
            raise OwnerAuthorizationError("ADC successor source is not for Issue #63")
        try:
            predecessor = verify_adc(github, 63).pointer
        except ADCError as exc:
            raise OwnerAuthorizationError("ADC_SUPERSEDE requires the current approved predecessor") from exc
        if predecessor.state != "approved":
            raise OwnerAuthorizationError("ADC_SUPERSEDE requires the current approved predecessor")
        try:
            validate_approval_ready_adc(
                raw, repository, 63, current_pointer=predecessor, check_current_pointer=True,
            )
        except ADCError as exc:
            raise OwnerAuthorizationError(f"ADC_SUPERSEDE candidate is not approval-ready: {exc}") from exc
        details = {
            "predecessor_comment_id": predecessor.comment_id,
            "predecessor_sha256": predecessor.sha256,
            "predecessor_byte_length": predecessor.byte_length,
            "predecessor_state": predecessor.state,
        }
    elif operation == "RULESET_PLAN_APPLY":
        if args.ruleset_plan is None or args.subject_file is not None:
            raise OwnerAuthorizationError("RULESET_PLAN_APPLY plan requires --ruleset-plan")
        ruleset = read_ruleset_plan(args.ruleset_plan)
        if (ruleset.get("blockers") or ruleset.get("diff", {}).get("operation") == "noop"
                or ruleset.get("activation_issue_number") != 57):
            raise OwnerAuthorizationError("Ruleset approval is only for a blocker-free write plan bound to Activation #57")
        subject_sha256 = ruleset.get("plan_sha256")
        if not isinstance(subject_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", subject_sha256):
            raise OwnerAuthorizationError("Ruleset plan digest is invalid")
        target_issue = 57
        details = {"activation_issue_number": 57}
    elif operation == "USER_REVIEW":
        if args.subject_file is not None or args.ruleset_plan is not None:
            raise OwnerAuthorizationError("USER_REVIEW plan does not accept ADC or Ruleset source files")
        context = _user_review_owner_context(args, repository, github)
        subject_sha256 = context["subject_sha256"]
        pr_number, pr_head = context["pr_number"], context["pr_head_sha40"]
        details = context["details"]
    elif operation == "PR_MERGE":
        if (args.subject_file is not None or args.ruleset_plan is not None
                or args.pr is None or args.head is None or args.target_issue is None):
            raise OwnerAuthorizationError("PR_MERGE plan requires --pr, --head, and --target-issue")
        pr_number, pr_head, target_issue = args.pr, args.head, args.target_issue
        details = (issue63_deferred_merge_details(github, pr_number=pr_number, pr_head_sha40=pr_head)
                   if target_issue == 63 else {"target_issue_number": target_issue})
        subject_value = {"repository": repository, "target_issue_number": target_issue,
                         "pr_number": pr_number, "pr_head_sha40": pr_head}
        if target_issue == 63:
            subject_value["details"] = details
        subject_sha256 = hashlib.sha256(_canonical(subject_value)).hexdigest()
    elif operation == "EXECUTION_ADOPTION":
        if (args.adoption_plan is None or args.subject_file is not None or args.ruleset_plan is not None
                or args.session is not None or args.feedback_snapshot is not None):
            raise OwnerAuthorizationError("EXECUTION_ADOPTION plan requires only --adoption-plan")
        if repository.casefold() != "puchinya/ai-agent-workflow":
            raise OwnerAuthorizationError("EXECUTION_ADOPTION is restricted to puchinya/ai-agent-workflow")
        adoption = read_adoption_plan(args.adoption_plan)
        live = build_adoption_plan(github, root)
        if adoption != live:
            raise OwnerAuthorizationError("adoption plan is stale or differs from current exact-HEAD preflight")
        subject_sha256 = adoption["plan_sha256"]
        target_issue, pr_number, pr_head = 63, 64, adoption["observed_start_head_sha40"]
        details = {"adoption_plan": adoption}
    else:
        raise OwnerAuthorizationError("unsupported owner authorization operation")
    plan = create_authorization_plan(
        github, root, operation=operation, subject_sha256=subject_sha256,
        issue_number=63, target_issue_number=target_issue,
        pr_number=pr_number, pr_head_sha40=pr_head, details=details,
    )
    write_authorization_plan(args.output, plan)
    _json({"status": "PLANNED", "operation": operation, "output": str(args.output),
           "subject_sha256": subject_sha256, "plan_sha256": plan["plan_sha256"],
           "repository": repository, "issue": 63, "target_issue": target_issue,
           "pr": pr_number, "head": pr_head, "chat_signature": False})
    return 0


def _validate_owner_authorization_source(args: argparse.Namespace, plan: dict[str, Any],
                                         repository: str, github: GitHub) -> dict[str, Any] | None:
    if plan["operation"] == "ADC_SUPERSEDE":
        path = args.subject_file
        if path is None or path.is_symlink() or not path.is_file():
            raise OwnerAuthorizationError("ADC_SUPERSEDE commit requires the same regular --subject-file")
        raw = path.read_bytes()
        parsed = parse_adc(raw, repository, 63)
        if parsed.issue_number != 63 or hashlib.sha256(raw).hexdigest() != plan["subject_sha256"]:
            raise OwnerAuthorizationError("ADC source bytes differ from the exact authorization plan")
        try:
            predecessor = verify_adc(github, 63).pointer
        except ADCError as exc:
            raise OwnerAuthorizationError("current approved ADC predecessor is unavailable") from exc
        expected_predecessor = plan["details"]
        if (predecessor.comment_id != expected_predecessor.get("predecessor_comment_id")
                or predecessor.sha256 != expected_predecessor.get("predecessor_sha256")
                or predecessor.byte_length != expected_predecessor.get("predecessor_byte_length")
                or predecessor.state != expected_predecessor.get("predecessor_state")):
            raise OwnerAuthorizationError("current approved ADC predecessor changed after plan creation")
        try:
            validate_approval_ready_adc(
                raw, repository, 63, current_pointer=predecessor, check_current_pointer=True,
            )
        except ADCError as exc:
            raise OwnerAuthorizationError(f"ADC_SUPERSEDE candidate is not approval-ready: {exc}") from exc
    elif plan["operation"] == "RULESET_PLAN_APPLY":
        if args.ruleset_plan is None or args.ruleset_plan.is_symlink() or not args.ruleset_plan.is_file():
            raise OwnerAuthorizationError("RULESET_PLAN_APPLY commit requires the same regular --ruleset-plan")
        ruleset = read_ruleset_plan(args.ruleset_plan)
        if (ruleset.get("plan_sha256") != plan["subject_sha256"]
                or ruleset.get("activation_issue_number") != plan["target_issue_number"]
                or ruleset.get("blockers") or ruleset.get("diff", {}).get("operation") == "noop"):
            raise OwnerAuthorizationError("Ruleset plan changed or no longer requires an approved write")
    elif plan["operation"] == "PR_MERGE":
        target = plan["target_issue_number"]
        details = (issue63_deferred_merge_details(
            github, pr_number=plan["pr_number"], pr_head_sha40=plan["pr_head_sha40"],
        ) if target == 63 else {"target_issue_number": target})
        expected_value = {"repository": repository, "target_issue_number": target,
                          "pr_number": plan["pr_number"], "pr_head_sha40": plan["pr_head_sha40"]}
        if target == 63:
            expected_value["details"] = details
        expected = hashlib.sha256(_canonical(expected_value)).hexdigest()
        if expected != plan["subject_sha256"] or details != plan["details"]:
            raise OwnerAuthorizationError("PR merge subject digest differs from the exact target PR")
    elif plan["operation"] == "USER_REVIEW":
        context = _user_review_owner_context(args, repository, github)
        if (context["subject_sha256"] != plan["subject_sha256"]
                or context["details"] != plan["details"]
                or context["pr_number"] != plan["pr_number"]
                or context["pr_head_sha40"] != plan["pr_head_sha40"]):
            raise OwnerAuthorizationError("live User Review session, Readiness, feedback, or PR differs from its plan")
        return {"session": context["session"], "subject_sha256": context["subject_sha256"]}
    elif plan["operation"] == "EXECUTION_ADOPTION":
        path = getattr(args, "adoption_plan", None)
        if path is None:
            raise OwnerAuthorizationError("EXECUTION_ADOPTION requires the same immutable --adoption-plan")
        adoption = read_adoption_plan(path)
        if (adoption != plan["details"].get("adoption_plan")
                or adoption["plan_sha256"] != plan["subject_sha256"]
                or adoption["observed_start_head_sha40"] != plan["pr_head_sha40"]):
            raise OwnerAuthorizationError("adoption bytes differ from the exact Owner authorization plan")
        live = build_adoption_plan(github, args.root or _runtime_root(args))
        if live != adoption:
            raise OwnerAuthorizationError("live adoption preflight differs from the exact approved plan")
        return live
    return None


def _owner_authorization_commit_command(args: argparse.Namespace, repository: str,
                                        root: Path, github: GitHub) -> int:
    # A CLI process has no trustworthy ChatGPT user-role event. It must not
    # accept consent through stdin, flags, or a JSON file. The V3 in-process
    # orchestrator API is the only route that can bind a live chat response.
    raise OwnerAuthorizationError(
        "CHAT_CONFIRMATION_REQUIRED: obtain approval for the exact displayed scope in this chat, "
        "then use the in-process chat authorization integration; CLI approval is disabled"
    )


def execute_chat_confirmed_authorization(
    args: argparse.Namespace, repository: str, root: Path, github: GitHub, grant: Any,
) -> dict[str, Any]:
    """In-process chat host hook for an exact current user-role confirmation.

    The command line intentionally cannot call this path. The chat integration
    must construct ``grant`` from a direct approval event in this conversation;
    the resulting V3 evidence remains operator-reported, not host-signed.
    """
    plan = read_authorization_plan(args.plan)
    user_review_context = _validate_owner_authorization_source(args, plan, repository, github)
    result = authorize_chat_confirmed_plan(
        github, root, plan, grant, user_review_context=user_review_context,
        subject_bytes=(args.subject_file.read_bytes()
                       if plan["operation"] == "ADC_SUPERSEDE" and args.subject_file is not None else None),
        source_validator=lambda: _validate_owner_authorization_source(args, plan, repository, github),
    )
    if plan["operation"] == "ADC_SUPERSEDE":
        result = _publish_owner_approved_adc(args, repository, github, plan, result)
    elif plan["operation"] == "PR_MERGE":
        result = _perform_authorized_merge(args, root, github, plan, result)
    elif plan["operation"] == "EXECUTION_ADOPTION":
        adoption = read_adoption_plan(args.adoption_plan)
        result = apply_adoption(github, root, adoption, plan)
    return result


def execute_current_chat_confirmed_adoption(
    args: argparse.Namespace, repository: str, root: Path, github: GitHub, *,
    response: str, user_role: str, same_conversation: bool,
) -> dict[str, Any]:
    """Host adapter for the direct user-role approval of one exact adoption plan.

    This callable is not a CLI route. The chat host must provide the actual
    user-role event from this same conversation; it records no chat signature.
    """
    plan = read_authorization_plan(args.plan)
    grant = capture_direct_chat_confirmation(
        plan, response=response, user_role=user_role, same_conversation=same_conversation,
    )
    return execute_chat_confirmed_authorization(args, repository, root, github, grant)


def _publish_owner_approved_adc(args: argparse.Namespace, repository: str, github: GitHub,
                                plan: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Dispatch exact local ADC approval through the existing ADC and phase writers."""
    if args.subject_file is None or args.subject_file.is_symlink() or not args.subject_file.is_file():
        raise OwnerAuthorizationError("ADC_SUPERSEDE commit requires the same regular --subject-file")
    if repository.casefold() != "puchinya/ai-agent-workflow":
        raise OwnerAuthorizationError("ADC_SUPERSEDE dispatch is fixed to the approved Issue #63 repository")
    data = args.subject_file.read_bytes()
    contract = parse_adc(data, repository, 63)
    if contract.sha256 != plan["subject_sha256"]:
        raise OwnerAuthorizationError("successor ADC bytes changed after owner authorization")
    try:
        verified_decision = read_verified_owner_decision(
            github, issue_number=63, owner_id=_ISSUE63_OWNER_ID,
            operation="ADC_SUPERSEDE", subject_sha256=contract.sha256,
            expected_plan_sha256=plan["plan_sha256"], repository_id=_ISSUE63_REPOSITORY_ID,
            expected_approval_scope_sha256=plan["approval_scope_sha256"],
            expected_schema="PASES_OWNER_DECISION_V3",
        )
    except OwnerDecisionError as exc:
        raise OwnerAuthorizationError("exact ADC_SUPERSEDE V3 decision did not pass readback") from exc
    if (verified_decision.comment_id != decision.get("owner_decision_comment_id")
            or verified_decision.decision.schema != "PASES_OWNER_DECISION_V3"
            or verified_decision.decision.evidence_channel != "chat_confirmed_gh_v1"):
        raise OwnerAuthorizationError("ADC publication requires this exact chat-confirmed V3 decision")
    try:
        current = verify_adc(github, 63)
        if current.pointer.state != "approved":
            raise ADCError("ADC supersession requires the exact current approved predecessor")
        predecessor = plan["details"]
        if (current.pointer.comment_id != predecessor.get("predecessor_comment_id")
                or current.pointer.sha256 != predecessor.get("predecessor_sha256")
                or current.pointer.byte_length != predecessor.get("predecessor_byte_length")
                or current.pointer.state != predecessor.get("predecessor_state")):
            raise ADCError("current approved predecessor differs from the scope approved in chat")
        validate_approval_ready_adc(
            data, repository, 63, current_pointer=current.pointer, check_current_pointer=True,
        )
        pointer = publish_adc(
            github, 63, data, state="approved", explicitly_approved=True,
            supersede=True, expected_current=current.pointer,
        )
        published = verify_adc(github, 63)
        if (published.pointer != pointer or published.pointer.sha256 != contract.sha256
                or published.pointer.state != "approved" or published.contract.content != data):
            raise ADCError("approved successor ADC did not pass exact pointer and byte readback")
    except ADCError as exc:
        raise OwnerAuthorizationError(f"approved successor ADC publication failed: {exc}") from exc
    try:
        phase_result = rebaseline_issue_phase(github, 63)
    except PhaseRebaselineError as exc:
        status = ("BLOCKED_PERMISSION" if str(exc).startswith("BLOCKED_PERMISSION:")
                  else "ADC_PUBLISHED_PHASE_BLOCKED")
        return {"status": status, "operation": "ADC_SUPERSEDE",
                "owner_decision_comment_id": verified_decision.comment_id,
                "adc_comment_id": published.pointer.comment_id,
                "adc_sha256": published.pointer.sha256,
                "reasons": [str(exc)]}
    return {"status": "PUBLISHED", "operation": "ADC_SUPERSEDE",
            "owner_decision_comment_id": verified_decision.comment_id,
            "adc_comment_id": published.pointer.comment_id,
            "adc_sha256": published.pointer.sha256,
            "state": published.pointer.state, "phase_rebaseline": phase_result}


def _merge_attempt_path(root: Path, plan_sha256: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", plan_sha256):
        raise OwnerAuthorizationError("merge plan digest is invalid")
    return root / ".p_ases" / "owner-authorization" / "merge-attempts" / f"{plan_sha256}.json"


def _create_merge_attempt(path: Path, payload: dict[str, Any], *, root: Path) -> None:
    """Exclusively persist the attempt marker so concurrent callers cannot both merge."""
    destination = Path(path)
    data = _canonical(payload) + b"\n"
    if not _path_components_without_symlinks(destination, root):
        raise OwnerAuthorizationError("merge attempt path traverses a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _path_components_without_symlinks(destination, root):
        raise OwnerAuthorizationError("merge attempt path traverses a symbolic link")
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise OwnerAuthorizationError(
            "another invocation already claimed this merge attempt; only read-only recovery is allowed"
        ) from exc
    except OSError as exc:
        raise OwnerAuthorizationError("could not create the exclusive merge attempt record") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise OwnerAuthorizationError("merge attempt record write was interrupted; no retry is permitted") from exc
    try:
        if destination.is_symlink() or destination.read_bytes() != data:
            raise OwnerAuthorizationError("merge attempt record failed exact readback; no retry is permitted")
    except OSError as exc:
        raise OwnerAuthorizationError("merge attempt record readback failed; no retry is permitted") from exc


def _merge_readback(github: GitHub, plan: dict[str, Any]) -> dict[str, Any]:
    pr = github.pull_request(plan["pr_number"])
    head = pr.get("head") if isinstance(pr, dict) else None
    base = pr.get("base") if isinstance(pr, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    merger = pr.get("merged_by") if isinstance(pr, dict) else None
    if (pr.get("number") != plan["pr_number"] or pr.get("merged") is not True
            or pr.get("state") != "closed" or not isinstance(head, dict)
            or head.get("sha") != plan["pr_head_sha40"]
            or not isinstance(head_repo, dict) or head_repo.get("full_name") != "puchinya/ai-agent-workflow"
            or not isinstance(base_repo, dict) or base_repo.get("full_name") != "puchinya/ai-agent-workflow"
            or not isinstance(pr.get("merge_commit_sha"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", pr["merge_commit_sha"])
            or not isinstance(merger, dict) or merger.get("id") != _ISSUE63_OWNER_ID
            or merger.get("type") != "User"):
        raise OwnerAuthorizationError("PR merge readback does not prove the exact owner-merged HEAD")
    body = pr.get("body")
    if plan["target_issue_number"] == 63:
        try:
            details = issue63_deferred_merge_details(
                github, pr_number=plan["pr_number"], pr_head_sha40=plan["pr_head_sha40"],
                allow_merged=True,
            )
        except OwnerAuthorizationError:
            raise
        if details != plan["details"]:
            raise OwnerAuthorizationError("merged implementation PR association or merge plan differs from approval")
        issue = github.issue(63)
        if (issue.get("number") != 63 or issue.get("state") != "open"
                or issue.get("repository_url") != "https://api.github.com/repos/puchinya/ai-agent-workflow"):
            raise OwnerAuthorizationError("Issue #63 did not remain open after deferred-close PR merge")
        merge_commit = github.commit_details(pr["merge_commit_sha"])
        merge_message = merge_commit.get("message")
        if not isinstance(merge_message, str) or closing_issue_references(merge_message):
            raise OwnerAuthorizationError("merged PR commit message contains an auto-close reference or is unreadable")
    else:
        from .consumer_activation import SETUP_MARKER_V2, _decode
        try:
            payload = _decode(body, SETUP_MARKER_V2, "Activation Setup PR", allow_trailer=True)
        except ConsumerActivationError as exc:
            raise OwnerAuthorizationError("merged PR is not the exact Activation Setup PR") from exc
        if payload.get("activation_issue_number") != 57:
            raise OwnerAuthorizationError("merged Activation Setup PR does not bind Issue #57")
    return {"pr_number": plan["pr_number"], "head_sha40": plan["pr_head_sha40"],
            "merge_commit_sha40": pr["merge_commit_sha"], "merged_by_id": merger["id"],
            "issue_state": "open" if plan["target_issue_number"] == 63 else None}


def _owner_merge_gate(args: argparse.Namespace, root: Path, github: GitHub,
                      plan: dict[str, Any]) -> dict[str, Any]:
    if plan["target_issue_number"] == 57:
        return verify_setup_pr_ready_to_merge(github, plan["pr_number"])
    required = ("readiness", "delivery_plan", "verification", "acceptance", "self_audit",
                "independent_review", "user_review_record")
    missing = [f"--{name.replace('_', '-')}" for name in required if getattr(args, name, None) is None]
    if missing:
        raise OwnerAuthorizationError("PR #64 merge requires fresh Final Delivery evidence: " + ", ".join(missing))
    final_args = argparse.Namespace(
        issue=63, pr=plan["pr_number"], head=plan["pr_head_sha40"],
        plan=args.delivery_plan, readiness=args.readiness, verification=args.verification,
        acceptance=args.acceptance, self_audit=args.self_audit,
        independent_review=args.independent_review, user_review_record=args.user_review_record,
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = _delivery_final(final_args, "puchinya/ai-agent-workflow", root, github)
    try:
        final = json.loads(output.getvalue())
    except json.JSONDecodeError as exc:
        raise OwnerAuthorizationError("Final Delivery did not return a readable gate result") from exc
    final_schema = final.get("schema") if isinstance(final, dict) else None
    final_policy_shape_ok = False
    if isinstance(final, dict):
        if final_schema == "PASES_FINAL_DELIVERY_V3":
            final_policy_shape_ok = (
                final.get("review_mode") == "solo_owner"
                and final.get("branch_protection_sha256") is None
                and re.fullmatch(r"[0-9a-f]{64}", str(final.get("user_review_sha256", ""))) is not None
                and re.fullmatch(r"[0-9a-f]{64}", str(final.get("required_check_result_sha256", ""))) is not None
            )
        elif final_schema in {"PASES_FINAL_DELIVERY_V1", "PASES_FINAL_DELIVERY_V2"}:
            protection_sha = final.get("branch_protection_sha256")
            final_policy_shape_ok = (
                isinstance(protection_sha, str)
                and re.fullmatch(r"[0-9a-f]{64}", protection_sha) is not None
                and "review_mode" not in final
                and (final_schema == "PASES_FINAL_DELIVERY_V1"
                     and "current_base_advance_sha256" not in final
                     or final_schema == "PASES_FINAL_DELIVERY_V2"
                     and re.fullmatch(r"[0-9a-f]{64}", str(final.get("current_base_advance_sha256", ""))) is not None)
            )
    if (exit_code != 0 or not isinstance(final, dict)
            or final.get("status") != "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION"
            or final.get("merge_authorized") is not False
            or not final_policy_shape_ok
            or not isinstance(final.get("subject"), dict)
            or final["subject"].get("repository") != "puchinya/ai-agent-workflow"
            or final["subject"].get("issue_number") != 63
            or final["subject"].get("pr_number") != plan["pr_number"]
            or final["subject"].get("pr_head_sha40") != plan["pr_head_sha40"]
            or final.get("blockers")):
        raise OwnerAuthorizationError("PR #64 Final Delivery gates are not PASS for this exact merge plan")
    return {"status": final["status"], "final_delivery_sha256": final.get("final_delivery_sha256"),
            "final_delivery_schema": final_schema,
            "subject": final["subject"]}


def _perform_authorized_merge(args: argparse.Namespace, root: Path, github: GitHub,
                              plan: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Revalidate target gates and make at most one exact-HEAD merge request."""
    if (decision.get("status") != "AUTHORIZED" or decision.get("operation") != "PR_MERGE"
            or decision.get("evidence_type") != "PASES_OWNER_DECISION_V3"
            or decision.get("evidence_channel") != "chat_confirmed_gh_v1"
            or decision.get("chat_signature") is not False
            or type(decision.get("owner_decision_comment_id")) is not int
            or decision["owner_decision_comment_id"] < 1):
        raise OwnerAuthorizationError("PR merge requires the exact owner-local V2 decision readback")
    path = _merge_attempt_path(root, plan["plan_sha256"])
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise OwnerAuthorizationError("merge attempt record is not a regular file")
        try:
            intent = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OwnerAuthorizationError("merge attempt record is unreadable; no retry is permitted") from exc
        if (not isinstance(intent, dict) or intent.get("plan_sha256") != plan["plan_sha256"]
                or intent.get("pr_number") != plan["pr_number"]
                or intent.get("head_sha40") != plan["pr_head_sha40"]):
            raise OwnerAuthorizationError("merge attempt record conflicts with the exact authorization plan")
        try:
            merged = _merge_readback(github, plan)
        except OwnerAuthorizationError:
            current = github.pull_request(plan["pr_number"])
            if current.get("merged") is not True:
                raise OwnerAuthorizationError(
                    "merge attempt already has durable intent and remains unresolved; read-only recovery only"
                )
            raise
        return {**decision, "status": ("MERGED_AWAITING_ISSUE_COMPLETION"
                                         if plan["target_issue_number"] == 63 else "MERGED_READBACK"), **merged,
                "merge_request_repeated": False, "recovered_from_intent": True}

    gates = _owner_merge_gate(args, root, github, plan)
    if plan["target_issue_number"] == 63:
        live_details = issue63_deferred_merge_details(
            github, pr_number=plan["pr_number"], pr_head_sha40=plan["pr_head_sha40"],
        )
        if live_details != plan["details"]:
            raise OwnerAuthorizationError("Issue #63 close association, commits, or planned message changed before merge")
    current = github.pull_request(plan["pr_number"])
    head = current.get("head") if isinstance(current, dict) else None
    if (current.get("state") != "open" or current.get("merged") is True
            or not isinstance(head, dict) or head.get("sha") != plan["pr_head_sha40"]):
        raise OwnerAuthorizationError("PR changed or merged before the one permitted merge request")
    intent = {
        "schema": "PASES_PR_MERGE_ATTEMPT_V1", "plan_sha256": plan["plan_sha256"],
        "owner_decision_comment_id": decision.get("owner_decision_comment_id"),
        "target_issue_number": plan["target_issue_number"], "pr_number": plan["pr_number"],
        "head_sha40": plan["pr_head_sha40"], "merge_method": "merge",
        "source_head_sha40": plan["source_head_sha40"],
    }
    _create_merge_attempt(path, intent, root=root)
    response_error: GitHubError | None = None
    try:
        if plan["target_issue_number"] == 63:
            github.merge_pull_request(
                plan["pr_number"], plan["pr_head_sha40"],
                commit_title=plan["details"]["merge_commit_title"],
                commit_message=plan["details"]["merge_commit_message"],
            )
        else:
            github.merge_pull_request(plan["pr_number"], plan["pr_head_sha40"])
    except GitHubError as exc:
        response_error = exc
    try:
        merged = _merge_readback(github, plan)
    except (GitHubError, OwnerAuthorizationError) as exc:
        if response_error is not None:
            raise OwnerAuthorizationError(
                "merge response was ambiguous and readback did not prove completion; no retry was attempted"
            ) from response_error
        raise OwnerAuthorizationError(
            "merge endpoint response was not confirmed by exact PR readback; no retry was attempted"
        ) from exc
    return {**decision, "status": ("MERGED_AWAITING_ISSUE_COMPLETION"
                                    if plan["target_issue_number"] == 63 else "MERGED"), **merged,
            "merge_request_repeated": False, "merge_gate": gates,
            "response_recovered": response_error is not None}


def _owner_authorization_resume_command(args: argparse.Namespace, repository: str,
                                       root: Path, github: GitHub) -> int:
    plan = read_authorization_plan(args.plan)
    if plan["operation"] != "USER_REVIEW":
        result = resume_authorization(github, args.plan)
        if plan["operation"] == "PR_MERGE" and result.get("status") == "AUTHORIZED":
            path = _merge_attempt_path(root, plan["plan_sha256"])
            if path.exists() or path.is_symlink():
                if path.is_symlink() or not path.is_file():
                    raise OwnerAuthorizationError("merge attempt record is not a regular file")
                try:
                    intent = json.loads(path.read_text(encoding="utf-8"))
                    if (not isinstance(intent, dict) or intent.get("plan_sha256") != plan["plan_sha256"]
                            or intent.get("pr_number") != plan["pr_number"]
                            or intent.get("head_sha40") != plan["pr_head_sha40"]):
                        raise OwnerAuthorizationError("merge attempt record conflicts with the exact plan")
                    result = {**result, "merge_attempt_intent": True,
                              "merge_readback": _merge_readback(github, plan)}
                    result["merge_status"] = ("MERGED_AWAITING_ISSUE_COMPLETION"
                                               if plan["target_issue_number"] == 63 else "MERGED_READBACK")
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise OwnerAuthorizationError("merge attempt record is unreadable; no retry is permitted") from exc
                except OwnerAuthorizationError:
                    current = github.pull_request(plan["pr_number"])
                    result["merge_attempt_intent"] = True
                    result["merge_status"] = ("MERGE_OUTCOME_UNKNOWN_NO_RETRY"
                                               if current.get("merged") is not True else "MERGE_READBACK_INVALID")
                    result["merge_readback_error"] = "attempt intent exists; merge endpoint will not be retried"
        _json(result)
        return 0 if (result.get("status") == "AUTHORIZED"
                     and result.get("merge_status") not in {"MERGE_OUTCOME_UNKNOWN_NO_RETRY",
                                                             "MERGE_READBACK_INVALID"}) else 2
    if args.session is None or args.readiness is None:
        raise OwnerAuthorizationError("USER_REVIEW resume requires --session and --readiness")
    session = read_review_session(args.session)
    readiness = read_readiness(args.readiness)
    details = plan["details"]
    verification_subject = session.subject.verification_subject
    if (session.sha256 != details["review_session_sha256"]
            or session.subject.readiness_sha256 != details["readiness_sha256"]
            or readiness.status != "PASS" or readiness.sha256 != details["readiness_sha256"]
            or verification_subject.repository != repository
            or verification_subject.issue_number != 63
            or verification_subject.pr_number != plan["pr_number"]
            or verification_subject.pr_head_sha40 != details["pr_head_sha40"]
            or verification_subject.adc_sha256 != details["adc_sha256"]):
        raise OwnerAuthorizationError("User Review recovery session or Readiness differs from the plan")
    owner_id, pr_author_id, verifier_id = _solo_owner_identity(
        github, repository, 63, plan["pr_number"], details["pr_head_sha40"],
    )
    approval = _read_user_review_relay_approval(
        github, session=session, readiness=readiness, owner_id=owner_id, verifier_id=verifier_id,
        feedback_sha256=details["feedback_sha256"], plan_sha256=plan["plan_sha256"],
        approval_scope_sha256=plan["approval_scope_sha256"],
    )
    if (approval is None or approval.evidence_type not in {
            "PASES_USER_REVIEW_DECISION_V2", "PASES_USER_REVIEW_DECISION_V3"}
            or approval.plan_sha256 != plan["plan_sha256"]):
        _json({"status": "NOT_FOUND_OR_BLOCKED", "plan_sha256": plan["plan_sha256"],
               "reasons": ["exact owner User Review carrier is missing or stale"]})
        return 2
    if (approval.evidence_type == "PASES_USER_REVIEW_DECISION_V3"
            and approval.approval_scope_sha256 != plan["approval_scope_sha256"]):
        _json({"status": "NOT_FOUND_OR_BLOCKED", "plan_sha256": plan["plan_sha256"],
               "reasons": ["exact chat-confirmed User Review scope is missing or stale"]})
        return 2
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    fresh = _review_payload_from_github(github, session.subject, observed_at=observed_at)
    prior_events = [event for event in fresh.events
                    if not (event.channel == "issue-comment" and event.event_id == str(approval.comment_id))]
    if (fresh.unresolved_thread_ids
            or feedback_digest(prior_events) != details["feedback_sha256"]
            or approval.feedback_sha256 != details["feedback_sha256"]
            or pr_author_id != owner_id):
        _json({"status": "NOT_FOUND_OR_BLOCKED", "plan_sha256": plan["plan_sha256"],
               "reasons": ["current feedback, threads, PR author, or carrier subject differs from the plan"]})
        return 2
    _json({"status": "AUTHORIZED", "operation": "USER_REVIEW",
           "plan_sha256": plan["plan_sha256"], "subject_sha256": plan["subject_sha256"],
           "owner_decision_comment_id": approval.comment_id,
           "evidence_type": approval.evidence_type,
           "evidence_channel": approval.evidence_channel,
           "approval_scope_sha256": approval.approval_scope_sha256,
           "chat_signature": False})
    return 0


def _verify_activation_plan_checkpoint(root: Path, repository: str, plan: dict[str, Any]) -> None:
    binding = plan.get("activation_binding")
    if binding is None:
        return
    issue_number = plan.get("activation_issue_number")
    checkpoint = read_activation_checkpoint(activation_checkpoint_path(root, issue_number))
    checks = tuple(sorted((row.get("context"), row.get("integration_id"))
                          for row in plan.get("required_checks", []) if isinstance(row, dict)))
    if (checkpoint.repository.casefold() != repository.casefold()
            or checkpoint.repository_id != plan.get("repository_id")
            or checkpoint.owner_id != plan.get("owner_id")
            or checkpoint.activation_issue_number != issue_number
            or checkpoint.adc_comment_id != binding.get("adc_comment_id")
            or checkpoint.adc_sha256 != binding.get("adc_sha256")
            or checkpoint.default_branch_sha40 != binding.get("base_sha40")
            or checkpoint.predecessor_record_id != binding.get("predecessor_record_id")
            or checkpoint.setup_branch != binding.get("setup_branch")
            or checkpoint.setup_commit_sha40 != binding.get("setup_commit_sha40")
            or checkpoint.profile_sha256 != plan.get("profile_sha256")
            or checkpoint.plan_sha256 != plan.get("plan_sha256")
            or tuple(sorted(checkpoint.required_checks)) != checks
            or checkpoint.stage not in {"POLICY_PLAN", "AWAIT_OWNER_POLICY_DECISION", "APPLY_AND_READBACK"}):
        raise CLIError("Activation Ruleset plan is stale or does not match the current resumable checkpoint")


def _verify_ruleset_noop(github: GitHub, plan: dict[str, Any]) -> dict[str, Any]:
    checks = tuple((row["context"], row["integration_id"]) for row in plan["required_checks"])
    first = read_verified_managed_policy(
        github, plan["default_branch"], checks, plan["profile_review_mode"], plan["activation_issue_number"],
    )
    second = read_verified_managed_policy(
        github, plan["default_branch"], checks, plan["profile_review_mode"], plan["activation_issue_number"],
    )
    if (first != second or first["ruleset_id"] != plan["existing_ruleset_id"]
            or first["applied_record_id"] != plan["predecessor_comment_id"]
            or first["ruleset_body_sha256"] != plan["existing_ruleset_sha256"]
            or not isinstance(plan.get("policy_proof"), dict)
            or first["policy"].as_dict() != plan["policy_proof"]):
        raise CLIError("no-op Ruleset plan changed or lacks matching ownership/effective-policy evidence")
    return first


def _solo_owner_identity(github: ReadOnlyGitHub, repository: str, issue_number: int,
                         pr_number: int, expected_head_sha40: str) -> tuple[int, int, int]:
    """Read configured owner, fresh PR author and independent read-only principal."""
    if type(github) is not ReadOnlyGitHub:
        raise CLIError("User Review verifier must use the dedicated read-only GitHub client")
    try:
        github.verify_read_only_scope()
    except GitHubError as exc:
        raise CLIError("User Review read-only verifier route is not positively verified") from exc
    if repository.casefold() != "puchinya/ai-agent-workflow" or issue_number != 63:
        raise CLIError("solo_owner identity is only configured for puchinya/ai-agent-workflow Issue #63")
    metadata = github.repository_metadata()
    owner = metadata.get("owner") if isinstance(metadata, dict) else None
    full_name = metadata.get("full_name") if isinstance(metadata, dict) else None
    owner_login = owner.get("login") if isinstance(owner, dict) else None
    if (not isinstance(metadata, dict) or metadata.get("id") != _ISSUE63_REPOSITORY_ID
            or not isinstance(full_name, str) or full_name.casefold() != repository.casefold()
            or not isinstance(owner, dict) or owner.get("type") != "User"
            or owner.get("id") != _ISSUE63_OWNER_ID or not isinstance(owner_login, str)
            or owner_login.casefold() != "puchinya"):
        raise CLIError("fresh repository metadata differs from the configured Issue #63 owner identity")
    pr = github.pull_request(pr_number)
    head = pr.get("head") if isinstance(pr, dict) else None
    author = pr.get("user") if isinstance(pr, dict) else None
    if (not isinstance(head, dict) or head.get("sha") != expected_head_sha40
            or not isinstance(author, dict) or author.get("type") != "User"
            or author.get("id") != _ISSUE63_OWNER_ID):
        raise CLIError("fresh PR author or HEAD differs from the configured solo_owner identity")
    verifier = github.authenticated_user()
    verifier_id = verifier.get("id")
    if type(verifier_id) is not int or verifier_id < 1:
        raise CLIError("read-only GitHub verifier principal is unavailable")
    return _ISSUE63_OWNER_ID, author["id"], verifier_id


def _read_user_review_relay_approval(
    github: ReadOnlyGitHub, *, session: UserReviewSession, readiness: Any,
    owner_id: int, verifier_id: int, feedback_sha256: str | None = None,
    plan_sha256: str | None = None, approval_scope_sha256: str | None = None,
) -> UserReviewRelayApproval | None:
    """Read all dedicated carriers as complete direct/list/direct evidence."""
    if type(github) is not ReadOnlyGitHub:
        raise UserReviewRelayError("User Review carrier verification requires the dedicated read-only GitHub client")
    try:
        github.verify_read_only_scope()
    except GitHubError as exc:
        raise UserReviewRelayError("User Review carrier reads lack a verified read-only GitHub route") from exc
    subject = session.subject.verification_subject

    def carrier_ids(rows: list[dict[str, Any]]) -> tuple[int, ...]:
        selected: list[int] = []
        for row in rows:
            body = row.get("body") if isinstance(row, dict) else None
            if not has_user_review_decision_marker(body):
                continue
            comment_id = row.get("id") if isinstance(row, dict) else None
            if type(comment_id) is not int or comment_id < 1:
                raise UserReviewRelayError("dedicated review carrier has no valid comment ID")
            selected.append(comment_id)
        if len(selected) != len(set(selected)):
            raise UserReviewRelayError("dedicated review carrier ID is duplicated")
        return tuple(selected)

    initial = github.issue_comments(subject.issue_number)
    initial_ids = carrier_ids(initial)
    direct_before = {comment_id: github.issue_comment(subject.issue_number, comment_id)
                     for comment_id in initial_ids}
    listed = github.issue_comments(subject.issue_number)
    listed_ids = carrier_ids(listed)
    if listed_ids != initial_ids:
        raise UserReviewRelayError("complete dedicated review history changed during readback")
    direct_after = {comment_id: github.issue_comment(subject.issue_number, comment_id)
                    for comment_id in listed_ids}
    if not listed_ids:
        return None
    approval = verify_user_review_decision_history(
        UserReviewDecisionHistory(tuple(listed), direct_before, direct_after, True),
        repository=subject.repository, issue_number=subject.issue_number,
        pr_number=subject.pr_number, repository_owner_user_id=owner_id,
        authenticated_verifier_user_id=verifier_id, session=session,
        readiness_sha256=session.subject.readiness_sha256,
        adc_sha256=subject.adc_sha256, pr_head_sha40=subject.pr_head_sha40,
        feedback_sha256=feedback_sha256, plan_sha256=plan_sha256,
        approval_scope_sha256=approval_scope_sha256,
    )
    if readiness.status != "PASS" or readiness.sha256 != session.subject.readiness_sha256:
        raise UserReviewRelayError("typed carrier was read for stale Review Readiness")
    return approval


def _same_snapshot_payload(left: FeedbackSnapshot, right: FeedbackSnapshot) -> bool:
    """Compare the complete persisted payload while retaining its observation time."""
    if left.subject != right.subject or left.events != right.events or left.unresolved_thread_ids != right.unresolved_thread_ids:
        return False
    normalized = replace(right, observed_at=left.observed_at).validate()
    return normalized.sha256 == left.sha256


def _review_phase_transition(github: GitHub, issue_number: int, kind: IssueKind,
                             result: UserReviewResult, operation: str) -> None:
    issue = github.issue(issue_number)
    actual_kind, phase, attention = _issue_kind_phase(issue, issue_number)
    if actual_kind is not kind:
        raise CLIError("User Review phase update Issue kind differs from the requested kind")
    label_rows = issue.get("labels")
    labels = [row["name"] for row in label_rows]
    attention = parse_attention_labels(labels)
    if result.next_phase == "execution" and phase is Phase.USER_REVIEW:
        next_state = advance(PhaseState(issue_number, kind, phase, attention), Phase.EXECUTION,
                             changes_requested=True)
    elif result.next_phase == "requirements" and phase is Phase.USER_REVIEW:
        next_state = advance(PhaseState(issue_number, kind, phase, attention), Phase.REQUIREMENTS,
                             new_requirements=True)
    elif operation in {"start", "sync"} and phase is Phase.VERIFICATION:
        next_state = advance(PhaseState(issue_number, kind, phase, attention), Phase.USER_REVIEW,
                             readiness_passed=True)
    elif operation in {"start", "sync"} and phase is Phase.USER_REVIEW and not attention:
        return
    else:
        if operation in {"start", "sync"}:
            raise CLIError(f"User Review cannot enter from Issue phase {phase.value}")
        return
    current = github.issue(issue_number)
    current_labels = current.get("labels") if isinstance(current, dict) else None
    try:
        current_kind, current_phase, current_attention = _issue_kind_phase(current, issue_number)
    except CLIError as exc:
        raise CLIError("Issue kind/phase/attention changed during User Review; refusing a stale update") from exc
    if (current.get("state") != "open" or current.get("number") != issue_number
            or not isinstance(current_labels, list)
            or [row.get("name") for row in current_labels if isinstance(row, dict)] != labels
            or (current_kind, current_phase, current_attention) != (kind, phase, attention)):
        raise CLIError("Issue kind/phase/attention labels changed during User Review; refusing a stale update")
    kept = [label for label in labels if not label.startswith(("phase:", "attention:"))]
    kept.append(f"phase:{next_state.phase.value}")
    kept.extend(f"attention:{item.value}" for item in sorted(next_state.attention, key=lambda x: x.value))

    def verify_phase_readback(readback: Any) -> bool:
        if not isinstance(readback, dict) or readback.get("state") != "open":
            return False
        rows = readback.get("labels")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return False
        names = [row.get("name") for row in rows]
        if any(not isinstance(name, str) for name in names):
            return False
        try:
            readback_kind, readback_phase, readback_attention = _issue_kind_phase(readback, issue_number)
        except CLIError:
            return False
        return ((readback_kind, readback_phase, readback_attention)
                == (kind, next_state.phase, next_state.attention)
                and set(names) == set(kept))

    try:
        github.replace_issue_labels(issue_number, kept)
    except GitHubError as write_error:
        try:
            readback = github.issue(issue_number)
        except GitHubError as read_error:
            raise CLIError("User Review phase label write response was lost and exact label readback failed") from read_error
        if verify_phase_readback(readback):
            return
        raise CLIError("User Review phase label write response was lost; exact intended labels were not confirmed") from write_error
    readback = github.issue(issue_number)
    if not verify_phase_readback(readback):
        raise CLIError("GitHub did not confirm the exact requested User Review phase and attention labels")


def _user_review_run(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    blockers: list[str] = []
    result: UserReviewResult | None = None
    snapshot: FeedbackSnapshot | None = None
    try:
        broker = github
        github = _read_only_github(github)
        issue_row, verified_adc = _approved_issue_adc(github, args.issue, repository)
        issue_kind, issue_phase, issue_attention = _issue_kind_phase(issue_row, args.issue)
        requested_kind = getattr(args, "kind", None)
        if requested_kind is not None and issue_kind is not IssueKind(requested_kind):
            raise CLIError("User Review --kind differs from the Issue's unique kind:* label")
        if issue_kind not in {IssueKind.SINGLE, IssueKind.CHILD}:
            raise CLIError("ordinary User Review requires a single or child Issue")
        if issue_attention:
            raise CLIError(
                "User Review cannot start while Issue has an attention:* state; "
                "clear attention through the existing attention workflow before continuing"
            )
        if issue_phase not in {Phase.VERIFICATION, Phase.USER_REVIEW}:
            raise CLIError(f"User Review cannot start while Issue phase is {issue_phase.value}")
        plan, _reqs, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
        pr = github.pull_request(args.pr)
        head = pr.get("head") if isinstance(pr, dict) else None
        head_sha = head.get("sha") if isinstance(head, dict) else None
        if head_sha != args.head:
            raise CLIError("requested HEAD differs from the current GitHub PR HEAD")
        subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
        pr_identity = _readback_current_pr(github, subject)
        readiness = read_readiness(args.readiness)
        if (readiness.status != "PASS" or readiness.subject != subject):
            raise CLIError("User Review cannot start without current exact-subject Review Readiness PASS")
        user_review_subject = UserReviewSubject(subject, readiness.sha256).validate()
        profile = load_profile(root)
        review_mode = profile.final_delivery_review_mode
        if review_mode == "solo_owner":
            owner_id, pr_author_id, verifier_id = _solo_owner_identity(
                github, repository, args.issue, args.pr, args.head,
            )
            allowed_user_ids = (owner_id,)
        else:
            identity = github.authenticated_user()
            owner_id = pr_author_id = verifier_id = None
            allowed_user_ids = (identity["id"],)
        pre_session_issue = github.issue(args.issue)
        pre_session_kind, pre_session_phase, pre_session_attention = _issue_kind_phase(
            pre_session_issue, args.issue,
        )
        if (pre_session_kind, pre_session_phase, pre_session_attention) != (
                issue_kind, issue_phase, issue_attention):
            raise CLIError("Issue kind/phase/attention changed before User Review session access")
        if pre_session_attention:
            raise CLIError(
                "User Review cannot start while Issue has an attention:* state; "
                "clear attention through the existing attention workflow before continuing"
            )
        if pre_session_phase is Phase.VERIFICATION:
            advance(
                PhaseState(args.issue, pre_session_kind, pre_session_phase, pre_session_attention),
                Phase.USER_REVIEW, readiness_passed=True,
            )
        session_path = review_session_path(root, user_review_subject)
        if session_path.exists():
            session = read_review_session(session_path)
            if session.subject != user_review_subject:
                raise UserReviewError("User Review session belongs to a stale or different exact subject")
        else:
            if issue_phase is Phase.USER_REVIEW:
                raise UserReviewError(
                    "phase:user-review has no immutable session for this exact subject; refusing to create one"
                )
            if args.verb != "start":
                raise UserReviewError("User Review sync/status requires an existing immutable exact-subject session")
            session_started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            session = write_review_session(
                session_path, UserReviewSession(user_review_subject, session_started_at),
            )
        if session.subject != user_review_subject:
            raise UserReviewError("User Review session belongs to a stale or different exact subject")
        observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        current = _review_payload_from_github(github, user_review_subject, observed_at=observed_at)
        previous = _latest_review_snapshot(root, user_review_subject)
        snapshot = merge_feedback_history(previous, current)
        if review_mode == "solo_owner":
            relay_approval = _read_user_review_relay_approval(
                github, session=session, readiness=readiness,
                owner_id=owner_id, verifier_id=verifier_id,
            )
            result = evaluate_user_review(
                session, readiness, pr_identity["head_sha"], snapshot,
                review_mode=review_mode, pr_author_user_id=pr_author_id,
                repository_owner_user_id=owner_id, authenticated_verifier_user_id=verifier_id,
                allowed_human_user_ids=allowed_user_ids, relay_approval=relay_approval,
                all_feedback_surfaces_read=True,
                new_scope_requested=bool(getattr(args, "new_scope", False)),
            )
        else:
            result = evaluate_user_review(
                user_review_subject, readiness, pr_identity["head_sha"], snapshot.events,
                allowed_human_user_ids=allowed_user_ids, all_feedback_surfaces_read=True,
                required_after=session.started_at,
                new_scope_requested=bool(getattr(args, "new_scope", False)),
                unresolved_thread_ids=snapshot.unresolved_thread_ids,
            )
        current_issue = github.issue(args.issue)
        current_kind, current_phase, current_attention = _issue_kind_phase(current_issue, args.issue)
        if (current_kind, current_phase, current_attention) != (issue_kind, issue_phase, issue_attention):
            raise CLIError("Issue kind/phase/attention changed during User Review; refusing stale session processing")
        if current_attention:
            raise CLIError("Issue attention changed during User Review; refusing to persist review evidence")
        current_adc = verify_adc(github, args.issue)
        current_pr_identity = _readback_current_pr(github, subject)
        current_readiness = read_readiness(args.readiness)
        if review_mode == "solo_owner":
            current_owner_id, current_author_id, current_verifier_id = _solo_owner_identity(
                github, repository, args.issue, args.pr, args.head,
            )
            second_relay_approval = _read_user_review_relay_approval(
                github, session=session, readiness=current_readiness,
                owner_id=current_owner_id, verifier_id=current_verifier_id,
            )
            identity_unchanged = ((current_owner_id, current_author_id, current_verifier_id)
                                  == (owner_id, pr_author_id, verifier_id)
                                  and second_relay_approval == relay_approval)
        else:
            current_identity = github.authenticated_user()
            identity_unchanged = current_identity.get("id") == identity.get("id")
        second_observed = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        second = _review_payload_from_github(github, user_review_subject, observed_at=second_observed)
        second = merge_feedback_history(previous, second)
        if (current_issue.get("state") != "open" or current_adc.pointer != verified_adc.pointer
                or current_pr_identity != pr_identity or current_readiness != readiness
                or not identity_unchanged or not _same_snapshot_payload(snapshot, second)):
            raise CLIError("Issue, ADC, PR, Readiness, identity, or feedback changed during User Review readback")
        if args.verb != "status":
            persistence_issue = github.issue(args.issue)
            persistence_kind, persistence_phase, persistence_attention = _issue_kind_phase(
                persistence_issue, args.issue,
            )
            if (persistence_issue.get("state") != "open"
                    or (persistence_kind, persistence_phase, persistence_attention)
                    != (issue_kind, issue_phase, issue_attention)):
                raise CLIError("Issue kind/phase/attention changed immediately before User Review evidence persistence")
            if persistence_attention:
                raise CLIError("Issue attention is present immediately before User Review evidence persistence")
        if args.verb != "status":
            snapshot_path = feedback_snapshot_path(root, snapshot)
            write_feedback_snapshot(snapshot_path, snapshot)
            saved_snapshot = read_feedback_snapshot(snapshot_path)
            if saved_snapshot != snapshot or saved_snapshot.sha256 != snapshot.sha256:
                raise UserReviewError("persisted full User Review feedback snapshot changed on readback")
            result_schema = ("PASES_USER_REVIEW_RESULT_V2" if result.selected_approval_evidence is not None
                             else "PASES_USER_REVIEW_RESULT_V1")
            record = {"result": result.as_dict(), "result_sha256": result.sha256,
                      "schema": result_schema, "snapshot_sha256": snapshot.sha256,
                      "subject": user_review_subject.as_dict()}
            record_path = _review_record_path(root, args.issue, user_review_subject, result, snapshot.sha256)
            _write_immutable(record_path, _canonical(record) + b"\n", root=root)
            saved_subject, saved_result, saved_snapshot_sha256 = _read_review_record(record_path)
            if (saved_subject != user_review_subject or saved_result != result
                    or saved_snapshot_sha256 != snapshot.sha256):
                raise UserReviewError("persisted User Review result differs from its typed evaluation")
            if args.verb in {"start", "sync"}:
                _review_phase_transition(broker, args.issue, issue_kind, result, args.verb)
        else:
            snapshot_path = feedback_snapshot_path(root, snapshot)
            record_path = _review_record_path(root, args.issue, user_review_subject, result, snapshot.sha256)
        _json({"status": result.status, "subject": user_review_subject.as_dict(),
               "subject_sha256": user_review_subject.sha256, "result_sha256": result.sha256,
               "feedback_sha256": result.feedback_sha256, "next_phase": result.next_phase,
               "selected_approval_event": result.selected_approval_event,
               "selected_approval_evidence": result.selected_approval_evidence,
               "unresolved_thread_ids": list(result.unresolved_thread_ids),
               "reasons": list(result.reasons),
               "evidence_refs": [str(session_path), str(snapshot_path), str(record_path),
                                 f"pull/{args.pr}", f"issue/{args.issue}"]})
        return 0 if result.status in {"APPROVED", "CHANGES_REQUESTED"} else 2
    except (ADCError, PlanError, OracleTraceError, EvidenceError, ReadinessError, UserReviewError,
            UserReviewRelayError, OwnerDecisionError, ProfileError,
            PhaseError, GitHubError, CLIError, OSError, ValueError) as exc:
        blockers.append(str(exc))
        return _blocked_result(blockers)


def _user_review_record(args: argparse.Namespace) -> int:
    # A JSON file cannot authenticate a chat author. This command is reserved for a host adapter.
    try:
        reject_unattested_chat_event(args.event_file)
    except UserReviewError as exc:
        return _blocked_result((str(exc),))
    return 2


def _delivery_final(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    blockers: list[str] = []
    try:
        github = _read_only_github(github)
        _issue, verified_adc = _approved_issue_adc(github, args.issue, repository)
        plan, _reqs, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
        subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
        pr = _readback_current_pr(github, subject)
        profile = load_profile(root)
        delivery_binding = _read_execution_identity(github, root, repository, args.issue, verified_adc)
        delivery_pr_binding = read_pr_binding(pr_binding_path(root, args.issue, github=github))
        _frozen_base_ref, frozen_base_sha = execution_identity_base(delivery_binding)
        raw_pr = github.pull_request(args.pr)
        current_base_evidence = _current_base_evidence_for_pr(
            root, github, repository, args.issue, delivery_binding, delivery_pr_binding, raw_pr,
        )
        review_mode = profile.final_delivery_review_mode
        if review_mode == "solo_owner":
            identity = _solo_owner_identity(github, repository, args.issue, args.pr, args.head)
            owner_id, pr_author_id, verifier_id = identity
            allowed_user_ids = (owner_id,)
        else:
            verifier = github.authenticated_user()
            owner_id = pr_author_id = verifier_id = None
            identity = (verifier.get("id"),)
            allowed_user_ids = identity
        saved_readiness = read_readiness(args.readiness)
        readiness_args = argparse.Namespace(
            issue=args.issue, pr=args.pr, head=args.head, plan=args.plan,
            verification=args.verification, acceptance=args.acceptance,
            self_audit=args.self_audit, independent_review=args.independent_review,
        )
        readiness_output = io.StringIO()
        with contextlib.redirect_stdout(readiness_output):
            _readiness_exit = _delivery_readiness(readiness_args, repository, root, github)
        readiness_record = json.loads(readiness_output.getvalue())
        readiness_path_value = readiness_record.get("path") if isinstance(readiness_record, dict) else None
        if not isinstance(readiness_path_value, str):
            raise CLIError("current Review Readiness could not be recomputed")
        readiness = read_readiness(Path(readiness_path_value))
        if readiness != saved_readiness:
            blockers.append("saved Review Readiness differs from the current full-gate re-evaluation")
        if readiness.subject != subject or readiness.status != "PASS":
            blockers.append("Review Readiness is not PASS for the exact current subject")
        user_subject, saved_review, snapshot_sha = _read_review_record(args.user_review_record)
        if (user_subject.verification_subject != subject or readiness.status != "PASS"
                or user_subject.readiness_sha256 != readiness.sha256):
            blockers.append("saved User Review record belongs to a stale or different exact subject")
        session_path = review_session_path(root, user_subject)
        session = read_review_session(session_path)
        if session.subject != user_subject:
            blockers.append("User Review session belongs to a stale or different exact subject")
        saved_snapshot_path = (root / ".p_ases" / "user-review" / str(args.issue)
                               / user_subject.sha256 / f"{snapshot_sha}.json")
        saved_snapshot = read_feedback_snapshot(saved_snapshot_path)
        if (saved_snapshot.sha256 != snapshot_sha or saved_snapshot.subject != user_subject
                or feedback_digest(saved_snapshot.events) != saved_review.feedback_sha256):
            blockers.append("saved User Review snapshot is missing or inconsistent")
        if (review_mode == "solo_owner" and saved_review.status == "APPROVED"
                and (not isinstance(saved_review.selected_approval_evidence, dict)
                     or saved_review.selected_approval_evidence.get("evidence_type")
                     not in {"PASES_USER_REVIEW_DECISION_V1", "PASES_USER_REVIEW_DECISION_V2",
                             "PASES_USER_REVIEW_DECISION_V3"})):
            blockers.append("solo_owner approved record is not backed by its dedicated carrier")
        fresh_subject = UserReviewSubject(subject, readiness.sha256).validate()
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        fresh = _review_payload_from_github(github, fresh_subject, observed_at=observed_at)
        previous = _latest_review_snapshot(root, fresh_subject)
        fresh = merge_feedback_history(previous, fresh)
        if review_mode == "solo_owner":
            relay_approval = _read_user_review_relay_approval(
                github, session=session, readiness=readiness,
                owner_id=owner_id, verifier_id=verifier_id,
            )
            current_review = evaluate_user_review(
                session, readiness, pr["head_sha"], fresh,
                review_mode=review_mode, pr_author_user_id=pr_author_id,
                repository_owner_user_id=owner_id, authenticated_verifier_user_id=verifier_id,
                allowed_human_user_ids=allowed_user_ids, relay_approval=relay_approval,
                all_feedback_surfaces_read=True,
            )
        else:
            relay_approval = None
            current_review = evaluate_user_review(
                fresh_subject, readiness, pr["head_sha"], fresh.events,
                allowed_human_user_ids=allowed_user_ids, required_after=session.started_at,
                unresolved_thread_ids=fresh.unresolved_thread_ids,
            )
        if (saved_review.status != "APPROVED" or current_review != saved_review
                or feedback_digest(fresh.events) != saved_review.feedback_sha256
                or not _same_snapshot_payload(saved_snapshot, fresh)):
            blockers.append("current GitHub feedback no longer matches the saved approved User Review")
        verification = read_verification_result(args.verification)
        calculated_verification, _refs = _calculate_verification(
            argparse.Namespace(issue=args.issue, pr=args.pr, head=args.head, plan=args.plan),
            repository, root, github)
        if verification != calculated_verification or verification.subject != subject or verification.status != "PASS":
            blockers.append("#29 Verification is stale or is not PASS for the exact subject")
        raw_pr = github.pull_request(args.pr)
        aggregate = github.pull_review_decision(args.pr)
        protection = github.branch_protection(pr["base_ref"]) if review_mode == "external_reviewer" else None
        required_names = tuple(name for name, _app_id in profile.required_checks)
        result = evaluate_final_delivery(
            subject=subject, user_review=current_review, verification=verification,
            current_pr_head_sha40=aggregate.get("headRefOid"), current_pr_state=pr["state"],
            current_pr_draft=raw_pr.get("draft"), github_review_decision=aggregate.get("reviewDecision"),
            github_review_head_sha40=aggregate.get("headRefOid"), branch_protection=protection,
            required_check_names=required_names, mergeable=raw_pr.get("mergeable"),
            review_mode=review_mode,
            current_base_advance=current_base_evidence,
            current_pr_base_sha40=pr["base_sha"],
            frozen_base_sha40=frozen_base_sha,
        )
        if verify_adc(github, args.issue).pointer != verified_adc.pointer:
            blockers.append("approved ADC pointer changed during Final Delivery")
        if _readback_current_pr(github, subject) != pr:
            blockers.append("PR identity/base/head changed during Final Delivery")
        final_pr_binding = read_pr_binding(pr_binding_path(root, args.issue, github=github))
        final_execution_identity = _read_execution_identity(github, root, repository, args.issue, verified_adc)
        if final_execution_identity != delivery_binding:
            blockers.append("immutable execution identity changed during Final Delivery")
        final_base_evidence = _current_base_evidence_for_pr(
            root, github, repository, args.issue, final_execution_identity, final_pr_binding,
            github.pull_request(args.pr),
        )
        if final_base_evidence != current_base_evidence:
            blockers.append("Activation current-base evidence changed during Final Delivery")
        if github.pull_review_decision(args.pr) != aggregate:
            blockers.append("GitHub formal review decision or PR HEAD changed during Final Delivery")
        if review_mode == "external_reviewer" and github.branch_protection(pr["base_ref"]) != protection:
            blockers.append("branch protection changed during Final Delivery")
        final_readiness = read_readiness(args.readiness)
        final_session = read_review_session(session_path)
        final_observed = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        final_feedback = _review_payload_from_github(github, fresh_subject, observed_at=final_observed)
        final_feedback = merge_feedback_history(previous, final_feedback)
        if review_mode == "solo_owner":
            final_identity = _solo_owner_identity(github, repository, args.issue, args.pr, args.head)
            final_relay_approval = _read_user_review_relay_approval(
                github, session=final_session, readiness=final_readiness,
                owner_id=final_identity[0], verifier_id=final_identity[2],
            )
            final_review = evaluate_user_review(
                final_session, final_readiness, pr["head_sha"], final_feedback,
                review_mode=review_mode, pr_author_user_id=final_identity[1],
                repository_owner_user_id=final_identity[0], authenticated_verifier_user_id=final_identity[2],
                allowed_human_user_ids=(final_identity[0],), relay_approval=final_relay_approval,
                all_feedback_surfaces_read=True,
            )
            identity_unchanged = (final_identity == identity and final_relay_approval == relay_approval)
        else:
            final_identity_raw = github.authenticated_user()
            final_review = evaluate_user_review(
                fresh_subject, final_readiness, pr["head_sha"], final_feedback.events,
                allowed_human_user_ids=(final_identity_raw["id"],), required_after=final_session.started_at,
                unresolved_thread_ids=final_feedback.unresolved_thread_ids,
            )
            identity_unchanged = (final_identity_raw.get("id"),) == identity
        persisted_subject, persisted_review, persisted_snapshot_sha = _read_review_record(args.user_review_record)
        if (final_readiness != readiness or not identity_unchanged or final_session != session
                or persisted_subject != user_subject or persisted_review != saved_review
                or persisted_snapshot_sha != snapshot_sha or final_review != saved_review
                or feedback_digest(final_feedback.events) != feedback_digest(fresh.events)
                or not _same_snapshot_payload(saved_snapshot, final_feedback)):
            blockers.append("Readiness, identity, relay history, session, result, or full feedback snapshot changed during Final Delivery")
        final_verification, _final_refs = _calculate_verification(
            argparse.Namespace(issue=args.issue, pr=args.pr, head=args.head, plan=args.plan),
            repository, root, github)
        if final_verification != verification:
            blockers.append("#29 Verification/Required Check Runs changed during Final Delivery")
        if blockers:
            result = FinalDeliveryResult("BLOCKED", subject, result.user_review_sha256,
                                         result.required_check_result_sha256,
                                         result.branch_protection_sha256,
                                         tuple((*result.reasons, *blockers)),
                                         result.current_base_advance_sha256,
                                         result.review_mode).validate()
        path = root / ".p_ases" / "final-delivery" / str(args.issue) / f"{result.sha256}.json"
        _write_immutable(path, _canonical(result.as_dict()) + b"\n", root=root)
        _json({**result.as_dict(), "subject_sha256": subject.sha256, "path": str(path),
               "merge_authorized": False,
               "independent_review_schema": readiness_record.get("independent_review_schema"),
               "independent_review_provenance_confidence": readiness_record.get(
                   "independent_review_provenance_confidence"),
               "independent_review_missing_host_ids": readiness_record.get(
                   "independent_review_missing_host_ids", []),
               "evidence_refs": [str(session_path), str(args.readiness), str(args.user_review_record), str(args.verification),
                                 str(args.acceptance), str(args.self_audit), str(args.independent_review),
                                 *([str(current_base_advance_path(root, args.issue))]
                                   if current_base_evidence is not None else []), str(path)]})
        return 0 if result.status == "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION" else 2
    except (ADCError, PlanError, OracleTraceError, EvidenceError, ReadinessError, VerificationError,
            UserReviewError, UserReviewRelayError, OwnerDecisionError, ProfileError,
            RulesetManagementError, GitHubError, CLIError, OSError, ValueError) as exc:
        return _blocked_result((str(exc),))


def _issue_state_triplet(github: GitHub, issue_number: int, repository: str) -> tuple[dict[str, Any], ...]:
    """Bind Issue state and identity to direct/list/direct GitHub reads."""
    before = github.issue(issue_number)
    rows = github.issues_all()
    listed = [row for row in rows if row.get("number") == issue_number]
    after = github.issue(issue_number)
    if len(listed) != 1:
        raise CLIError("Issue is missing or duplicated in the complete GitHub Issue list")
    expected_repo = f"https://api.github.com/repos/{repository}"

    def identity(row: dict[str, Any]) -> tuple[Any, ...]:
        if (row.get("number") != issue_number or row.get("pull_request") is not None
                or row.get("repository_url") != expected_repo
                or row.get("state") not in {"open", "closed"}
                or not isinstance(row.get("closed_at"), (str, type(None)))):
            raise CLIError("Issue direct/list/direct identity readback is incomplete or mismatched")
        return row.get("number"), row.get("state"), row.get("repository_url"), row.get("closed_at")

    fingerprints = (identity(before), identity(listed[0]), identity(after))
    if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
        raise CLIError("Issue state or identity changed during direct/list/direct readback")
    return before, listed[0], after


def _issue_close_intent_path(root: Path, issue_number: int, merge_sha40: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", merge_sha40):
        raise CLIError("deferred Issue close requires the exact PR merge SHA")
    return root / ".p_ases" / "delivery" / "deferred-close" / str(issue_number) / f"{merge_sha40}.json"


def _create_issue_close_intent(path: Path, payload: dict[str, Any], *, root: Path) -> None:
    destination = Path(path)
    if not _path_components_without_symlinks(destination, root):
        raise CLIError("Issue close intent path traverses a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _path_components_without_symlinks(destination, root):
        raise CLIError("Issue close intent path traverses a symbolic link")
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CLIError("Issue close already has durable intent; only read-only recovery is allowed") from exc
    except OSError as exc:
        raise CLIError("could not create exclusive Issue close intent") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical(payload) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise CLIError("Issue close intent write was interrupted; no close retry is permitted") from exc
    actual = _read_json(destination, "Issue close intent", root=root)
    if actual != payload:
        raise CLIError("Issue close intent failed exact readback; no close retry is permitted")


def _activation_v2_issue63_proof(root: Path, github: GitHub, repository: str) -> dict[str, Any] | None:
    """Return fresh ACTIVE V2 and policy proof, or None while Activation is not active."""
    history = read_consumer_activation_history(github, repository, 57)
    if not history or history[-1][0].schema_version != 2:
        return None
    record, record_id = history[-1]
    profile = load_profile(root)
    if (repository.casefold() != "puchinya/ai-agent-workflow" or profile.activation_issue_number != 57
            or profile.final_delivery_review_mode != "solo_owner"
            or record.activation_issue_number != 57 or record.repository.casefold() != repository.casefold()
            or record.review_mode != "solo_owner" or record.ruleset_id is None
            or record.branch_policy_sha256 is None or record.ruleset_applied_record_id is None):
        raise CLIError("latest Activation record is not the configured Consumer Activation V2")
    required_checks = profile.required_check_policy()
    checks = tuple((name, app_id) for name, app_id in profile.required_checks if app_id is not None)
    if len(checks) != len(profile.required_checks):
        raise CLIError("Activation V2 policy lacks trusted Required Check App IDs")
    metadata = github.repository_metadata()
    default_branch = metadata.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise CLIError("Activation V2 default branch is unavailable")
    branch_row = github.branch(default_branch)
    main_sha = branch_row.get("commit", {}).get("sha") if isinstance(branch_row.get("commit"), dict) else None
    if not isinstance(main_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", main_sha):
        raise CLIError("Activation V2 current default branch SHA is invalid")
    if current_branch(root) != default_branch or not worktree_clean(root) or head_sha40(root) != main_sha:
        raise CLIError("post-merge Activation verification requires a clean local default worktree at current main")
    profile_bytes = github.regular_content_at_ref(".agent/project.json", main_sha)
    if hashlib.sha256(profile_bytes).hexdigest() != record.activation_profile_sha256:
        raise CLIError("current main profile differs from the ACTIVE V2 Activation record")
    current_adc = verify_adc(github, 57)
    if (current_adc.pointer.state != "approved" or current_adc.pointer.sha256 != record.adc_sha256
            or current_adc.pointer.comment_id != record.adc_comment_id):
        raise CLIError("current approved Activation ADC differs from the ACTIVE V2 record")
    first = read_verified_managed_policy(github, default_branch, checks, "solo_owner", 57)
    second = read_verified_managed_policy(github, default_branch, checks, "solo_owner", 57)
    if (first != second or first.get("ruleset_id") != record.ruleset_id
            or first.get("effective_policy_sha256") != record.branch_policy_sha256
            or first.get("applied_record_id") != record.ruleset_applied_record_id):
        raise CLIError("current Ruleset/effective branch policy does not match ACTIVE V2 evidence")
    return {
        "status": "ACTIVE", "activation_record_id": record_id,
        "activation_record_sha256": hashlib.sha256(_canonical(record.payload())).hexdigest(),
        "activated_at": record.activated_at, "activation_adc_sha256": record.adc_sha256,
        "activation_profile_sha256": record.activation_profile_sha256,
        "ruleset_id": record.ruleset_id, "ruleset_applied_record_id": record.ruleset_applied_record_id,
        "effective_policy_sha256": first["effective_policy_sha256"],
        "default_branch": default_branch, "default_branch_sha40": main_sha,
        "required_check_policy_sha256": required_checks.sha256,
    }


def _delivery_finalize(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    try:
        pr = github.pull_request(args.pr)
        issue = github.issue(args.issue)
        merge_sha = pr.get("merge_commit_sha") if isinstance(pr, dict) else None
        main = github.repository_metadata().get("default_branch")
        main_row = github.branch(main)
        main_sha = main_row["commit"]["sha"]
        reasons = []
        if pr.get("state") != "closed" or pr.get("merged_at") is None:
            reasons.append("PR has not been merged")
        try:
            association_mode = parse_issue_association(pr.get("body"), args.issue)
        except WorkError as exc:
            association_mode = None
            reasons.append(f"PR Issue association is invalid: {exc}")
        if args.issue == 63 and (args.pr != 64 or association_mode != "deferred_close"):
            reasons.append("Issue #63 requires PR #64 with one standalone Refs #63 association")
        if association_mode == "deferred_close" and args.issue == 63 and pr.get("merged") is True:
            raw_head = pr.get("head")
            current_pr_head = raw_head.get("sha") if isinstance(raw_head, dict) else None
            if not isinstance(current_pr_head, str):
                raise CLIError("merged deferred-close PR HEAD is unavailable")
            planned = issue63_deferred_merge_details(
                github, pr_number=args.pr, pr_head_sha40=current_pr_head,
                allow_merged=True,
            )
            if planned.get("association_mode") != "deferred_close":
                reasons.append("GitHub does not confirm deferred-close association metadata")
            if isinstance(merge_sha, str) and re.fullmatch(r"[0-9a-f]{40}", merge_sha):
                merge_message = github.commit_details(merge_sha).get("message")
                if not isinstance(merge_message, str) or closing_issue_references(merge_message):
                    reasons.append("merged PR commit message is unreadable or contains an auto-close reference")
        if not isinstance(merge_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", merge_sha):
            reasons.append("merged PR has no full merge commit SHA")
        else:
            comparison = github.compare_commits(merge_sha, main_sha)
            if comparison.get("status") not in {"ahead", "identical"}:
                reasons.append("merged PR commit is not contained in current main")
        activation_proof = None
        close_status = None
        if association_mode == "auto_close":
            if issue.get("state") != "closed":
                reasons.append("GitHub has not auto-closed the Issue after merge")
            close_status = "FINALIZED" if not reasons else "BLOCKED"
        elif association_mode == "deferred_close":
            if args.issue != 63 or args.pr != 64:
                reasons.append("deferred-close finalization is configured only for Issue #63 and PR #64")
            if not reasons:
                history = read_consumer_activation_history(github, repository, 57)
                if not history or history[-1][0].schema_version != 2:
                    close_intent_path = _issue_close_intent_path(root, 63, merge_sha)
                    if issue.get("state") == "closed" or close_intent_path.exists() or close_intent_path.is_symlink():
                        close_status = "BLOCKED"
                        reasons.append("Issue #63 closure exists without a current verified Activation V2 proof")
                    else:
                        close_status = "MERGED_AWAITING_ISSUE_COMPLETION"
                else:
                    activation_proof = _activation_v2_issue63_proof(root, github, repository)
                    if activation_proof is None:
                        close_status = "MERGED_AWAITING_ISSUE_COMPLETION"
                    else:
                        try:
                            merged_at = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
                            activated_at = datetime.fromisoformat(activation_proof["activated_at"].replace("Z", "+00:00"))
                        except (KeyError, TypeError, ValueError) as exc:
                            raise CLIError("PR merge or Activation V2 effective timestamp is invalid") from exc
                        if merged_at.tzinfo is None or activated_at.tzinfo is None or activated_at <= merged_at:
                            reasons.append("Activation V2 must become ACTIVE after PR #64 merge")
                            close_status = "BLOCKED"
                        else:
                            intent = {
                                "schema": "PASES_DEFERRED_ISSUE_CLOSE_INTENT_V1",
                                "repository": repository, "issue_number": 63, "pr_number": 64,
                                "pr_merge_sha40": merge_sha,
                                "activation_record_id": activation_proof["activation_record_id"],
                                "activation_record_sha256": activation_proof["activation_record_sha256"],
                                "activated_at": activation_proof["activated_at"],
                                "ruleset_id": activation_proof["ruleset_id"],
                                "effective_policy_sha256": activation_proof["effective_policy_sha256"],
                                "default_branch": activation_proof["default_branch"],
                                "default_branch_sha40": activation_proof["default_branch_sha40"],
                            }
                            intent_path = _issue_close_intent_path(root, 63, merge_sha)
                            issue_before = _issue_state_triplet(github, 63, repository)[0]
                            if intent_path.exists() or intent_path.is_symlink():
                                existing = _read_json(intent_path, "Issue close intent", root=root)
                                if existing != intent:
                                    raise CLIError("existing Issue close intent does not match current Activation proof")
                                if issue_before.get("state") == "closed" and isinstance(issue_before.get("closed_at"), str):
                                    close_status = "FINALIZED"
                                else:
                                    close_status = "BLOCKED"
                                    reasons.append("Issue close intent exists but Issue remains open; recovery is read-only and no retry is permitted")
                            else:
                                if issue_before.get("state") == "closed":
                                    raise CLIError("Issue #63 closed before this verified P-ASES completion path")
                                if issue_before.get("state") != "open":
                                    raise CLIError("Issue #63 was not open immediately before deferred close")
                                _create_issue_close_intent(intent_path, intent, root=root)
                                close_error: GitHubError | None = None
                                try:
                                    github.close_issue(63)
                                except GitHubError as exc:
                                    close_error = exc
                                issue_after = _issue_state_triplet(github, 63, repository)[0]
                                if issue_after.get("state") == "closed" and isinstance(issue_after.get("closed_at"), str):
                                    close_status = "FINALIZED"
                                else:
                                    close_status = "BLOCKED"
                                    reasons.append(
                                        "Issue close did not read back as closed; durable intent prevents another PATCH"
                                        + (f" ({close_error})" if close_error else "")
                                    )
        if association_mode is None:
            close_status = "BLOCKED"
        status = close_status or ("BLOCKED" if reasons else "FINALIZED")
        value = {"status": status, "issue": args.issue, "pr": args.pr,
                 "merge_sha40": merge_sha, "main_sha40": main_sha,
                 "reasons": reasons, "issue_state": github.issue(args.issue).get("state"),
                 "association_mode": association_mode,
                 "activation_v2": activation_proof,
                 "note": ("Issue #63 remains open until post-merge Activation V2 and effective policy verify"
                          if status == "MERGED_AWAITING_ISSUE_COMPLETION" else
                          "deferred Issue closure uses one durable close intent and read-only recovery")}
        _json(value)
        return 0 if status == "FINALIZED" and not reasons else 2
    except (ADCError, ConsumerActivationError, RulesetManagementError,
            GitHubError, CLIError, OSError, ValueError) as exc:
        return _blocked_result((str(exc),))


PARENT_CHILD_ISSUES = (27, 28, 29, 30, 31, 32)
PARENT_CHILD_DAG = {
    27: (), 28: (27,), 29: (27, 28), 30: (27, 29),
    31: (29, 30), 32: (27, 28, 29, 30, 31),
}
def _publish_parent_gate_evidence(args: argparse.Namespace, repository: str, root: Path,
                                  github: GitHub) -> int:
    try:
        if args.issue != 26:
            raise CLIError("parent evidence publication is fixed to Issue #26")
        parent_issue = github.issue(26)
        expected_issue_url = f"https://api.github.com/repos/{repository}"
        if (not isinstance(parent_issue, dict) or parent_issue.get("number") != 26
                or parent_issue.get("state") != "open"
                or parent_issue.get("pull_request") is not None
                or not isinstance(parent_issue.get("repository_url"), str)
                or parent_issue["repository_url"].casefold() != expected_issue_url.casefold()):
            raise CLIError("parent evidence publication needs the same open Issue #26")
        parent_body = parent_issue.get("body")
        if not isinstance(parent_body, str):
            raise CLIError("parent evidence publication requires Issue #26 body readback")
        parent_body_sha = hashlib.sha256(parent_body.encode("utf-8")).hexdigest()
        adc_sha256, adc_pointer = _parent_adc_authority(github)
        main_sha40 = _parent_current_main_sha(github)
        bundle = _parent_gate_bundle_from_actions(
            github, args.run_id, args.kind, repository, adc_sha256, main_sha40)
        expected_body = bundle.to_body()
        identity = github.authenticated_user()
        if not isinstance(identity, dict) or identity.get("type") != "User" or type(identity.get("id")) is not int:
            raise CLIError("parent evidence publication requires a readback of the authenticated GitHub user")

        matching_ids: list[int] = []
        existing_comments = github.issue_comments(26)
        if (not isinstance(existing_comments, list)
                or any(not isinstance(row, dict) for row in existing_comments)):
            raise IntegrationError("parent Issue comment list is malformed")
        for row in existing_comments:
            body = row.get("body")
            if not isinstance(body, str) or not body.startswith("P-ASES-PARENT-EVIDENCE-V2\n"):
                continue
            if row.get("updated_at") != row.get("created_at"):
                raise IntegrationError("an existing parent evidence comment was edited")
            existing = ParentGateEvidenceComment.from_body(body)
            if (existing.kind == args.kind and existing.repository.casefold() == repository.casefold()
                    and existing.parent_issue_number == 26 and existing.parent_adc_sha256 == adc_sha256
                    and existing.main_sha40 == main_sha40
                    and existing.workflow_run_id == bundle.workflow_run_id
                    and existing.workflow_run_attempt == bundle.workflow_run_attempt):
                author = row.get("user")
                if (not isinstance(author, dict) or author.get("id") != identity["id"]
                        or author.get("type") != "User"):
                    raise IntegrationError("existing parent evidence comment author is not the authenticated user")
                matching_ids.append(row.get("id"))
                if body != expected_body:
                    raise IntegrationError("a different parent evidence comment already claims this exact subject")
        if len(matching_ids) > 1 or any(type(value) is not int or value < 1 for value in matching_ids):
            raise IntegrationError("parent evidence subject has duplicate or malformed Issue comments")
        if matching_ids:
            comment_id = matching_ids[0]
            evidence = _load_parent_gate_evidence_from_github(
                github, comment_id, main_sha40, args.kind, repository, adc_sha256)
            status = "REUSED"
        else:
            created = github.create_issue_comment(26, expected_body)
            comment_id = created.get("id")
            if type(comment_id) is not int or comment_id < 1:
                raise GitHubError("created parent evidence comment has no valid ID")
            evidence = _load_parent_gate_evidence_from_github(
                github, comment_id, main_sha40, args.kind, repository, adc_sha256)
            status = "PUBLISHED"
        if (_parent_current_main_sha(github) != main_sha40
                or _parent_adc_authority(github) != (adc_sha256, adc_pointer)):
            raise IntegrationError("main or parent ADC changed during evidence publication")
        final_issue = github.issue(26)
        if (not isinstance(final_issue, dict) or final_issue.get("number") != 26
                or final_issue.get("state") != "open"
                or final_issue.get("pull_request") is not None
                or final_issue.get("repository_url") != parent_issue.get("repository_url")
                or final_issue.get("body") != parent_body
                or hashlib.sha256(final_issue.get("body", "").encode("utf-8")).hexdigest() != parent_body_sha):
            raise IntegrationError("parent Issue changed during evidence publication")
        _json({"status": status, "kind": args.kind, "parent_issue": 26,
               "main_sha40": main_sha40, "comment_id": comment_id,
               "evidence_sha256": evidence.sha256,
               "comment_sha256": hashlib.sha256(expected_body.encode("utf-8")).hexdigest(),
               "evidence_refs": [f"issue-comment:{comment_id}"], "reasons": []})
        return 0
    except (ADCError, GitHubError, IntegrationError, CLIError, OSError, ValueError) as exc:
        return _blocked_result((str(exc),))


def _read_parent_integration(args: argparse.Namespace, repository: str, root: Path,
                             github: GitHub) -> tuple[Any, Path, Any, Any]:
    parent_number = getattr(args, "parent", getattr(args, "issue", None))
    if parent_number != 26:
        raise CLIError("native parent integration is fixed to Issue #26 for this migration")
    def snapshot() -> tuple[Any, str, Any, str, Any, Any, Any]:
        parent_issue = github.issue(parent_number)
        if (parent_issue.get("number") != parent_number or parent_issue.get("state") != "open"
                or parent_issue.get("pull_request") is not None
                or parent_issue.get("repository_url", "").casefold()
                != f"https://api.github.com/repos/{repository}".casefold()):
            raise CLIError("parent Integration requires the same open parent Issue")
        parent_body = parent_issue.get("body")
        if not isinstance(parent_body, str):
            raise CLIError("parent Integration requires the current parent Issue body readback")
        parent_body_sha256 = hashlib.sha256(parent_body.encode("utf-8")).hexdigest()
        parent_adc_sha256, child_adc_pointer = _parent_adc_authority(github)
        metadata = github.repository_metadata()
        main_ref = metadata.get("default_branch")
        if not isinstance(main_ref, str) or not main_ref:
            raise GitHubError("repository default branch is unavailable")
        main_row = github.branch(main_ref)
        main_commit = main_row.get("commit") if isinstance(main_row, dict) else None
        main_sha = main_commit.get("sha") if isinstance(main_commit, dict) else None
        if not isinstance(main_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", main_sha):
            raise GitHubError("current main branch SHA is invalid")
        verification_comment_id = getattr(args, "verification_comment_id", None)
        acceptance_comment_id = getattr(args, "acceptance_comment_id", None)
        verification_evidence = (None if verification_comment_id is None else
                                 _load_parent_gate_evidence_from_github(
                                     github, verification_comment_id, main_sha, "verification",
                                     repository, parent_adc_sha256))
        acceptance_evidence = (None if acceptance_comment_id is None else
                               _load_parent_gate_evidence_from_github(
                                   github, acceptance_comment_id, main_sha, "acceptance",
                                   repository, parent_adc_sha256))
        subs = github.sub_issues(parent_number)
        child_rows = [github.issue(number) for number in PARENT_CHILD_ISSUES]
        blockers: dict[int, tuple[int, ...]] = {}
        for number in PARENT_CHILD_ISSUES:
            rows = github.blocked_by(number)
            blockers[number] = tuple(sorted(row["id"] for row in rows
                                             if isinstance(row, dict) and type(row.get("id")) is int))
        prs = github.pull_requests_all()
        ancestry: dict[str, bool] = {}
        for pr in prs:
            body = pr.get("body") if isinstance(pr, dict) else None
            if not isinstance(body, str):
                continue
            own_closes = [int(value) for value in STANDALONE_CLOSE.findall(body)]
            if len(own_closes) != 1 or own_closes[0] not in PARENT_CHILD_ISSUES:
                continue
            merge_sha = pr.get("merge_commit_sha")
            if not isinstance(merge_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", merge_sha):
                continue
            try:
                comparison = github.compare_commits(merge_sha, main_sha)
                ancestry[merge_sha] = comparison.get("status") in {"ahead", "identical"}
            except GitHubError:
                ancestry[merge_sha] = False
        result = evaluate_parent_integration(
            repository=repository, parent_issue_number=parent_number,
            parent_adc_sha256=parent_adc_sha256, main_sha40=main_sha,
            expected_child_issue_numbers=PARENT_CHILD_ISSUES,
            native_sub_issues=subs, child_issue_rows=child_rows,
            actual_blockers_by_issue=blockers, declared_dependencies=PARENT_CHILD_DAG,
            merged_pr_rows=prs, merge_sha_ancestry=ancestry,
            integration_verification=verification_evidence,
            integration_acceptance=acceptance_evidence,
        )
        return (result, parent_adc_sha256, child_adc_pointer, parent_body_sha256,
                main_ref, verification_evidence, acceptance_evidence)

    first, first_adc_sha, first_source_pointer, first_body_sha, first_main_ref, verification_evidence, acceptance_evidence = snapshot()
    second, second_adc_sha, second_source_pointer, second_body_sha, second_main_ref, second_verification, second_acceptance = snapshot()
    if (first.sha256 != second.sha256 or first_adc_sha != second_adc_sha
            or first_source_pointer != second_source_pointer or first_body_sha != second_body_sha
            or first_main_ref != second_main_ref
            or verification_evidence != second_verification
            or acceptance_evidence != second_acceptance):
        raise CLIError("parent children, dependency graph, main SHA, or ADC changed during Integration readback")
    result_path = root / ".p_ases" / "integration" / str(parent_number) / f"{first.sha256}.json"
    value = {"integration_sha256": first.sha256, "reasons": list(first.reasons),
             "schema": "PASES_PARENT_INTEGRATION_RESULT_V1", "status": first.status,
             "subject": first.subject.as_dict()}
    _write_immutable(result_path, _canonical(value) + b"\n", root=root)
    return first, result_path, verification_evidence, acceptance_evidence


def _issue_integration_check(args: argparse.Namespace, repository: str, root: Path,
                             github: GitHub) -> int:
    try:
        result, path, verification, acceptance = _read_parent_integration(args, repository, root, github)
        _json({"status": result.status, "parent_issue": 26,
               "integration_sha256": result.sha256, "subject": result.subject.as_dict(),
               "reasons": list(result.reasons),
               "evidence_refs": [str(path), *(row.source_reference for row in (verification, acceptance)
                                   if row is not None)]})
        return 0 if result.status == "PASS" else 2
    except (ADCError, GitHubError, IntegrationError, CLIError, OSError, ValueError) as exc:
        return _blocked_result((str(exc),))


def _parent_review_subject_from_integration(result: Any) -> ParentReviewSubject:
    if getattr(result, "status", None) != "PASS":
        raise CLIError("parent User Review can start only after complete parent Integration PASS")
    integration_subject = result.subject
    subject = ParentReviewSubject(
        integration_subject.repository,
        integration_subject.parent_issue_number,
        integration_subject.parent_adc_sha256,
        tuple((row.issue_number, row.merge_sha40) for row in integration_subject.children),
        result.sha256,
    )
    return subject.validate()


def _latest_parent_feedback_snapshot(root: Path, subject: ParentReviewSubject) -> ParentFeedbackSnapshot | None:
    folder = (Path(root).absolute() / ".p_ases" / "user-review" / str(subject.parent_issue_number)
              / subject.sha256)
    if path_has_symlink(folder):
        raise UserReviewError("parent User Review history path must not traverse a symbolic link")
    if not folder.exists():
        return None
    if not folder.is_dir():
        raise UserReviewError("parent User Review history path is not a directory")
    snapshots: list[ParentFeedbackSnapshot] = []
    for path in folder.glob("*.json"):
        if path.name == "parent-session.json" or path.name.endswith(".result.json"):
            continue
        snapshot = read_parent_feedback_snapshot(path)
        if snapshot.subject == subject:
            snapshots.append(snapshot)
    return max(snapshots, key=lambda item: item.observed_at) if snapshots else None


PARENT_MIGRATION_LABEL_DEFINITIONS = {
    "kind:parent": ("c5def5", "P-ASES Issue kind: parent"),
    "phase:integration": ("0e8a16", "Workflow phase: integration"),
    "phase:user-review": ("d93f0b", "Workflow phase: user review"),
}


def _parent_label_migration_plan(github: GitHub, repository: str, issue_number: int
                                 ) -> tuple[dict[str, Any], list[str], list[str], list[dict[str, str]]]:
    if issue_number != 26:
        raise CLIError("legacy parent label migration is fixed to Issue #26")
    issue = github.issue(issue_number)
    expected_repo = f"https://api.github.com/repos/{repository}"
    if (not isinstance(issue, dict) or issue.get("number") != issue_number or issue.get("state") != "open"
            or issue.get("pull_request") is not None
            or not isinstance(issue.get("repository_url"), str)
            or issue["repository_url"].casefold() != expected_repo.casefold()):
        raise CLIError("parent label migration requires the same open Issue #26")
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CLIError("parent label migration cannot read the current label set")
    current = [row.get("name") for row in rows]
    if (any(not isinstance(label, str) or not label for label in current)
            or len(current) != len(set(current))):
        raise CLIError("parent label migration found malformed or duplicate labels")
    kinds = [label for label in current if label.startswith("kind:")]
    phases = [label for label in current if label.startswith("phase:")]
    if kinds and kinds != ["kind:parent"]:
        raise CLIError("parent label migration conflicts with an existing Issue kind label")
    if phases and phases != ["phase:integration"]:
        raise CLIError("parent label migration conflicts with an existing phase label")
    repo_labels = github.repository_labels()
    if not isinstance(repo_labels, list):
        raise CLIError("repository label definition list is malformed")
    definitions: dict[str, dict[str, Any]] = {}
    for row in repo_labels:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
            raise CLIError("repository label definitions are malformed")
        if row["name"] in definitions:
            raise CLIError("repository label definitions are duplicated")
        definitions[row["name"]] = row
    missing: list[dict[str, str]] = []
    for name, (color, description) in PARENT_MIGRATION_LABEL_DEFINITIONS.items():
        existing = definitions.get(name)
        if existing is None:
            missing.append({"name": name, "color": color, "description": description})
            continue
        if (not isinstance(existing.get("color"), str) or existing["color"].casefold() != color
                or existing.get("description") != description):
            raise CLIError(f"repository label definition {name} has conflicting metadata")
    if any(not isinstance(name, str) for name in definitions):
        raise CLIError("repository label definitions are malformed or duplicated")
    target = list(current)
    for name in ("kind:parent", "phase:integration"):
        if name not in target:
            target.append(name)
    return issue, current, target, missing


def _delivery_parent_label_migration(args: argparse.Namespace, repository: str,
                                     github: GitHub) -> int:
    try:
        issue, current, target, definitions_to_create = _parent_label_migration_plan(
            github, repository, args.issue)
        expected_repo = f"https://api.github.com/repos/{repository}".casefold()
        if current == target and not definitions_to_create:
            _json({"status": "ALREADY_MIGRATED", "parent_issue": 26,
                   "labels_before": current, "labels_after": target,
                   "label_definitions_created": [], "changed": False, "reasons": []})
            return 0
        if not args.apply:
            _json({"status": "PREFLIGHT_READY", "parent_issue": 26,
                   "labels_before": current, "labels_after": target,
                   "label_definitions_to_create": definitions_to_create,
                   "changed": False, "requires_apply": True,
                   "note": "no GitHub state was changed; rerun with --apply to apply this exact migration",
                   "reasons": []})
            return 0
        latest, latest_labels, latest_target, latest_definitions = _parent_label_migration_plan(
            github, repository, 26)
        if latest_labels != current or latest_target != target or latest_definitions != definitions_to_create:
            raise CLIError("parent labels or Issue identity changed after migration preflight")
        for definition in definitions_to_create:
            try:
                github.create_repository_label(
                    definition["name"], definition["color"], definition["description"])
            except GitHubError:
                # A lost response is safe to retry only when the exact named definition now exists.
                reread = {row.get("name"): row for row in github.repository_labels()
                          if isinstance(row, dict)}
                current_definition = reread.get(definition["name"])
                if (not isinstance(current_definition, dict)
                        or not isinstance(current_definition.get("color"), str)
                        or current_definition["color"].casefold() != definition["color"]
                        or current_definition.get("description") != definition["description"]):
                    raise
        verified_definitions = {row.get("name"): row for row in github.repository_labels()
                                if isinstance(row, dict)}
        if any((name not in verified_definitions
                or not isinstance(verified_definitions[name].get("color"), str)
                or verified_definitions[name]["color"].casefold() != color
                or verified_definitions[name].get("description") != description)
               for name, (color, description) in PARENT_MIGRATION_LABEL_DEFINITIONS.items()):
            raise CLIError("GitHub did not confirm all exact P-ASES label definitions")
        latest_issue = github.issue(26)
        latest_rows = latest_issue.get("labels") if isinstance(latest_issue, dict) else None
        latest_issue_labels = ([row.get("name") for row in latest_rows if isinstance(row, dict)]
                               if isinstance(latest_rows, list) else None)
        if (not isinstance(latest_issue, dict) or latest_issue.get("number") != 26 or latest_issue.get("state") != "open"
                or latest_issue.get("pull_request") is not None
                or not isinstance(latest_issue.get("repository_url"), str)
                or latest_issue["repository_url"].casefold() != expected_repo
                or latest_issue_labels != current):
            raise CLIError("parent labels changed during label-definition creation")
        if current != target:
            github.replace_issue_labels(26, target)
        readback = github.issue(26)
        readback_rows = readback.get("labels") if isinstance(readback, dict) else None
        readback_labels = ([row.get("name") for row in readback_rows if isinstance(row, dict)]
                           if isinstance(readback_rows, list) else None)
        if (not isinstance(readback, dict) or readback.get("number") != 26 or readback.get("state") != "open"
                or readback.get("pull_request") is not None
                or not isinstance(readback.get("repository_url"), str)
                or readback["repository_url"].casefold() != expected_repo
                or readback_labels is None or set(readback_labels) != set(target)
                or len(readback_labels) != len(target)):
            raise CLIError("GitHub did not confirm the complete parent label migration")
        _json({"status": "MIGRATED", "parent_issue": 26,
               "labels_before": current, "labels_after": target,
               "label_definitions_created": [row["name"] for row in definitions_to_create],
               "changed": current != target or bool(definitions_to_create), "reasons": []})
        return 0
    except (GitHubError, CLIError, OSError, ValueError) as exc:
        return _blocked_result((str(exc),))


def _require_parent_user_review_phase(issue: dict[str, Any], issue_number: int) -> None:
    if issue.get("number") != issue_number or issue.get("state") != "open":
        raise CLIError("parent User Review requires the same open parent Issue")
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CLIError("parent Issue phase labels are malformed")
    labels = [row.get("name") for row in rows]
    if any(not isinstance(label, str) for label in labels):
        raise CLIError("parent Issue phase label is malformed")
    if "kind:parent" not in labels:
        raise CLIError("parent Issue kind changed during User Review")
    if parse_phase_labels(labels) is not Phase.USER_REVIEW or parse_attention_labels(labels):
        raise CLIError("parent Issue is no longer in unblocked User Review")


def _advance_parent_to_user_review(github: GitHub, issue_number: int) -> None:
    issue = github.issue(issue_number)
    if issue.get("number") != issue_number or issue.get("state") != "open":
        raise CLIError("parent User Review phase transition needs the same open parent Issue")
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CLIError("parent Issue phase labels are malformed")
    labels = [row.get("name") for row in rows]
    if any(not isinstance(label, str) for label in labels):
        raise CLIError("parent Issue phase label is malformed")
    if "kind:parent" not in labels:
        raise CLIError("parent Issue kind is not parent")
    phase, attention = parse_phase_labels(labels), parse_attention_labels(labels)
    if attention:
        raise CLIError("clear parent waiting/blocked attention before starting User Review")
    if phase is Phase.USER_REVIEW:
        return
    if phase is not Phase.INTEGRATION:
        raise CLIError("parent User Review can start only from the Integration phase")
    next_state = advance(PhaseState(issue_number, IssueKind.PARENT, phase, attention),
                         Phase.USER_REVIEW, integration_passed=True)
    current = github.issue(issue_number)
    current_rows = current.get("labels") if isinstance(current, dict) else None
    current_labels = ([row.get("name") for row in current_rows if isinstance(row, dict)]
                      if isinstance(current_rows, list) else None)
    if (current.get("state") != "open" or current.get("number") != issue_number
            or current_labels != labels):
        raise CLIError("parent Issue phase changed during Integration readback")
    kept = [label for label in labels if not label.startswith(("phase:", "attention:"))]
    kept.append(f"phase:{next_state.phase.value}")
    github.replace_issue_labels(issue_number, kept)
    readback = github.issue(issue_number)
    _require_parent_user_review_phase(readback, issue_number)


def _delivery_parent(args: argparse.Namespace, repository: str, root: Path,
                     github: GitHub) -> int:
    try:
        result, path, verification, acceptance = _read_parent_integration(args, repository, root, github)
        evidence_refs = [str(path), *(row.source_reference for row in (verification, acceptance)
                                      if row is not None)]
        if result.status != "PASS":
            _json({"status": "BLOCKED", "parent_issue": 26,
                   "integration_status": result.status, "integration_sha256": result.sha256,
                   "parent_user_review": "NOT_EVALUATED", "merge_authorized": False,
                   "activation_issued": False, "reasons": list(result.reasons),
                   "remaining_gates": ["parent Integration must PASS before Parent User Review"],
                   "evidence_refs": evidence_refs})
            return 2

        subject = _parent_review_subject_from_integration(result)
        expected_repo_url = f"https://api.github.com/repos/{repository}".casefold()
        issue = github.issue(subject.parent_issue_number)
        if (not isinstance(issue, dict) or issue.get("number") != subject.parent_issue_number or issue.get("state") != "open"
                or issue.get("pull_request") is not None
                or not isinstance(issue.get("repository_url"), str)
                or issue["repository_url"].casefold() != expected_repo_url
                or not isinstance(issue.get("body"), str)):
            raise CLIError("Parent User Review requires the same open parent Issue body readback")
        _advance_parent_to_user_review(github, subject.parent_issue_number)
        issue = github.issue(subject.parent_issue_number)
        if (not isinstance(issue, dict) or issue.get("number") != subject.parent_issue_number or issue.get("state") != "open"
                or issue.get("pull_request") is not None
                or not isinstance(issue.get("repository_url"), str)
                or issue["repository_url"].casefold() != expected_repo_url
                or not isinstance(issue.get("body"), str)):
            raise CLIError("parent Issue changed during User Review phase transition")
        _require_parent_user_review_phase(issue, subject.parent_issue_number)
        parent_body_sha256 = hashlib.sha256(issue["body"].encode("utf-8")).hexdigest()
        parent_adc_sha256, parent_adc_pointer = _parent_adc_authority(github)
        if parent_adc_sha256 != subject.parent_adc_sha256:
            raise CLIError("parent ADC changed after Integration PASS")

        session_path = parent_review_session_path(root, subject)
        candidate = ParentUserReviewSession(
            subject, datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))
        session = (write_parent_review_session(session_path, candidate) if not session_path.exists()
                   else read_parent_review_session(session_path))
        if session.subject != subject:
            raise UserReviewError("Parent User Review session belongs to stale child merges or Integration")

        def read_snapshot(observed_at: str) -> ParentFeedbackSnapshot:
            comments = github.issue_comments(subject.parent_issue_number)
            events = normalize_github_feedback(issue_comments=comments, pr_comments=(),
                                                pr_reviews=(), diff_comments=())
            ordered = tuple(sorted((row for row in events if row.channel == "issue-comment"),
                                   key=lambda row: (row.channel, row.event_id)))
            return ParentFeedbackSnapshot(subject, ordered, observed_at).validate()

        previous = _latest_parent_feedback_snapshot(root, subject)
        observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        current = merge_parent_feedback_history(previous, read_snapshot(observed_at))
        identity = github.authenticated_user()
        review = evaluate_parent_user_review(
            subject, session, current.events, allowed_human_user_ids=(identity["id"],))

        second_result, second_path, _second_verification, _second_acceptance = _read_parent_integration(
            args, repository, root, github)
        second_issue = github.issue(subject.parent_issue_number)
        second_adc_sha256, second_adc_pointer = _parent_adc_authority(github)
        second_identity = github.authenticated_user()
        second_observed = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        second_current = merge_parent_feedback_history(previous, read_snapshot(second_observed))
        if (second_result.status != "PASS" or second_result.sha256 != result.sha256
                or second_path != path or second_adc_sha256 != parent_adc_sha256
                or second_adc_pointer != parent_adc_pointer
                or not isinstance(second_issue, dict)
                or second_issue.get("number") != subject.parent_issue_number
                or second_issue.get("state") != "open"
                or second_issue.get("pull_request") is not None
                or not isinstance(second_issue.get("repository_url"), str)
                or second_issue["repository_url"].casefold() != expected_repo_url
                or not isinstance(second_issue.get("body"), str)
                or second_issue.get("labels") != issue.get("labels")
                or hashlib.sha256(second_issue["body"].encode("utf-8")).hexdigest()
                != parent_body_sha256
                or second_identity.get("id") != identity.get("id")
                or feedback_digest(second_current.events) != feedback_digest(current.events)
                or session != read_parent_review_session(session_path)):
            raise CLIError("Parent Issue, ADC, Integration, identity, or feedback changed during User Review")
        _require_parent_user_review_phase(second_issue, subject.parent_issue_number)

        snapshot_path = parent_feedback_snapshot_path(root, current)
        write_parent_feedback_snapshot(snapshot_path, current)
        review_record = {"schema": "PASES_PARENT_USER_REVIEW_RESULT_V1",
                         "subject": subject.as_dict(), "subject_sha256": subject.sha256,
                         "session_sha256": session.sha256, "snapshot_sha256": current.sha256,
                         "result": review.as_dict(), "result_sha256": review.sha256}
        review_path = (Path(root).absolute() / ".p_ases" / "user-review"
                       / str(subject.parent_issue_number) / subject.sha256
                       / f"{review.sha256}-{current.sha256}.result.json")
        _write_immutable(review_path, _canonical(review_record) + b"\n", root=root)
        result_status = ("READY_FOR_EXPLICIT_ACTIVATION_APPROVAL" if review.status == "APPROVED"
                         else "PARENT_USER_REVIEW_" + review.status)
        _json({"status": result_status, "parent_issue": subject.parent_issue_number,
               "integration_status": result.status, "integration_sha256": result.sha256,
               "parent_user_review": review.status, "parent_review_subject": subject.as_dict(),
               "parent_review_subject_sha256": subject.sha256,
               "parent_review_session_sha256": session.sha256,
               "parent_review_result_sha256": review.sha256,
               "merge_authorized": False, "activation_issued": False,
               "reasons": list(review.reasons),
               "remaining_gates": ["activation, merge, and release require separate explicit user authorization"],
               "evidence_refs": [*evidence_refs, str(session_path), str(snapshot_path), str(review_path)]})
        return 0 if review.status == "APPROVED" else 2
    except (ADCError, GitHubError, IntegrationError, UserReviewError, CLIError, OSError, ValueError) as exc:
        return _blocked_result((str(exc),))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m p_ases")
    namespaces = parser.add_subparsers(dest="namespace", required=True)

    project = namespaces.add_parser("project", help="read the local project profile")
    project_commands = project.add_subparsers(dest="verb", required=True)
    project_status = project_commands.add_parser("status", help="read profile status without mutation")
    project_status.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    context = namespaces.add_parser("context", help="read Issue and frozen work-binding context")
    context_commands = context.add_subparsers(dest="verb", required=True)
    context_show = context_commands.add_parser("show", help="read current Issue, approved ADC, and binding")
    context_show.add_argument("issue", type=_positive_number)
    context_show.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    context_show.add_argument("--repo", help="repository owner/name; defaults to origin")

    adc = namespaces.add_parser("adc", help="validate and manage Agent Development Contracts")
    adc_commands = adc.add_subparsers(dest="verb", required=True)
    validate = adc_commands.add_parser("validate")
    validate.add_argument("issue", type=_positive_number)
    validate.add_argument("source", type=Path)
    validate.add_argument("--repo", help="repository owner/name; defaults to origin")
    publish = adc_commands.add_parser("publish")
    publish.add_argument("issue", type=_positive_number)
    publish.add_argument("source", type=Path)
    publish.add_argument("--repo", help="repository owner/name; defaults to origin")
    publish.add_argument("--state", choices=("draft", "approved"), default="draft")
    publish.add_argument("--supersede", action="store_true")
    publish.add_argument("--approval-comment-id", type=_positive_number,
                         help="exact PASES_OWNER_DECISION_V1 ADC_SUPERSEDE comment ID for Issue #63")
    verify = adc_commands.add_parser("verify")
    verify.add_argument("issue", type=_positive_number)
    verify.add_argument("--repo", help="repository owner/name; defaults to origin")
    restore = adc_commands.add_parser("restore")
    restore.add_argument("issue", type=_positive_number)
    restore.add_argument("destination", type=Path)
    restore.add_argument("--repo", help="repository owner/name; defaults to origin")

    issue = namespaces.add_parser(
        "issue", help="validate Issue graphs and apply foundational phase labels"
    )
    issue_commands = issue.add_subparsers(dest="verb", required=True)
    phase_rebaseline = issue_commands.add_parser(
        "phase-rebaseline", help="apply/recover the approved-ADC-backed Issue #63 phase bootstrap"
    )
    phase_rebaseline.add_argument("issue", type=_positive_number)
    phase_rebaseline.add_argument("--repo", help="repository owner/name; defaults to origin")
    validate_plan = issue_commands.add_parser("validate-split")
    validate_plan.add_argument("plan", type=Path)
    validate_plan.add_argument("--repo", help="repository owner/name; defaults to origin")
    split = issue_commands.add_parser("split")
    split.add_argument("plan", type=Path)
    split.add_argument("--repo", help="repository owner/name; defaults to origin")
    split.add_argument("--dry-run", action="store_true")
    advance_issue = issue_commands.add_parser(
        "advance",
        description=(
            "Apply foundational phase-label transitions through integration. This command cannot "
            "certify Review Readiness, User Review, merge, or GitHub Issue closure. Those evidence "
            "and readback steps are delivered by Issues #30 and #31; do not replace them with "
            "caller-supplied pass flags."
        ),
    )
    advance_issue.add_argument("issue", type=_positive_number)
    advance_issue.add_argument("target", choices=CLI_ADVANCE_TARGETS)
    advance_issue.add_argument("--repo", help="repository owner/name; defaults to origin")
    advance_issue.add_argument("--kind", choices=tuple(kind.value for kind in IssueKind), required=True)
    advance_issue.add_argument("--skip-phase", action="append", default=[], metavar="PHASE=REASON")
    advance_issue.add_argument("--root", type=Path,
                               help="repository root; required for ordinary Issue phase transitions")
    advance_issue.add_argument("--phase-evidence-comment-id", type=_positive_number,
                               help="exact PASES_PHASE_DECISION_V1 comment ID for specification/design/ready")
    phase_evidence = issue_commands.add_parser(
        "phase-evidence", help="publish an ADC- and commit-bound specification/design/ready receipt"
    )
    phase_evidence.add_argument("issue", type=_positive_number)
    phase_evidence.add_argument("from_phase", choices=tuple(phase.value for phase in Phase))
    phase_evidence.add_argument("to_phase", choices=(Phase.SPECIFICATION.value, Phase.DESIGN.value, Phase.READY.value))
    phase_evidence.add_argument("--repo", help="repository owner/name; defaults to origin")
    phase_evidence.add_argument("--root", type=Path, required=True,
                                help="repository root containing the committed documents")
    phase_evidence.add_argument("--skip-phase", action="append", default=[], metavar="PHASE=REASON")
    phase_refresh_ready = issue_commands.add_parser(
        "phase-refresh-ready",
        help="append an exact current-HEAD READY receipt refresh without changing Issue labels",
    )
    phase_refresh_ready.add_argument("issue", type=_positive_number)
    phase_refresh_ready.add_argument("--repo", help="repository owner/name; defaults to origin")
    phase_refresh_ready.add_argument("--root", type=Path, required=True,
                                     help="repository root containing the committed documents")
    integration_check = issue_commands.add_parser("integration-check", help="read back all child merges and parent evidence")
    integration_check.add_argument("parent", type=_positive_number)
    integration_check.add_argument("--verification-comment-id", type=_positive_number,
                                   help="exact Issue #26 comment ID containing Verification evidence")
    integration_check.add_argument("--acceptance-comment-id", type=_positive_number,
                                   help="exact Issue #26 comment ID containing Acceptance evidence")
    integration_check.add_argument("--repo", help="repository owner/name; defaults to origin")
    integration_check.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    verification = namespaces.add_parser("verification", help="freeze Plans and collect exact-subject verification")
    verification_commands = verification.add_subparsers(dest="verb", required=True)
    plan = verification_commands.add_parser("plan", help="validate source inputs and create an immutable Plan")
    plan.add_argument("issue", type=_positive_number)
    plan.add_argument("input", type=Path, help="JSON object with sources, entries, oracles, and tests")
    plan.add_argument("--repo", help="repository owner/name; defaults to origin")
    plan.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    collect = verification_commands.add_parser("collect", help="import a typed external execution observation")
    collect.add_argument("issue", type=_positive_number)
    collect.add_argument("pr", type=_positive_number)
    collect.add_argument("head", help="exact PR HEAD SHA-40")
    collect.add_argument("plan", type=Path)
    collect.add_argument("observation", type=Path)
    collect.add_argument("--repo", help="repository owner/name; defaults to origin")
    collect.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    for verb in ("validate", "final"):
        command = verification_commands.add_parser(verb, help=f"re-evaluate exact-subject Verification ({verb})")
        command.add_argument("issue", type=_positive_number)
        command.add_argument("pr", type=_positive_number)
        command.add_argument("head", help="exact PR HEAD SHA-40")
        command.add_argument("plan", type=Path)
        command.add_argument("--repo", help="repository owner/name; defaults to origin")
        command.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    published = verification_commands.add_parser("published", help="read back an exact final-result comment")
    published.add_argument("issue", type=_positive_number)
    published.add_argument("result", type=Path)
    published.add_argument("--repo", help="repository owner/name; defaults to origin")
    published.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    acceptance = namespaces.add_parser("acceptance", help="prepare, validate, publish, and verify artifact Acceptance")
    acceptance_commands = acceptance.add_subparsers(dest="verb", required=True)
    prepare = acceptance_commands.add_parser("prepare", help="create a subject-bound Acceptance observation template")
    prepare.add_argument("issue", type=_positive_number)
    prepare.add_argument("pr", type=_positive_number)
    prepare.add_argument("head")
    prepare.add_argument("plan", type=Path)
    prepare.add_argument("artifact_type", choices=sorted(ARTIFACT_TYPES))
    prepare.add_argument("output", type=Path)
    prepare.add_argument("--repo", help="repository owner/name; defaults to origin")
    prepare.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    validate_acceptance = acceptance_commands.add_parser("validate", help="evaluate artifact-specific Acceptance evidence")
    validate_acceptance.add_argument("issue", type=_positive_number)
    validate_acceptance.add_argument("pr", type=_positive_number)
    validate_acceptance.add_argument("head")
    validate_acceptance.add_argument("plan", type=Path)
    validate_acceptance.add_argument("artifact_type", choices=sorted(ARTIFACT_TYPES))
    validate_acceptance.add_argument("observations", type=Path)
    validate_acceptance.add_argument("verification", type=Path)
    validate_acceptance.add_argument("--repo", help="repository owner/name; defaults to origin")
    validate_acceptance.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    for verb in ("publish", "verify"):
        command = acceptance_commands.add_parser(verb, help=f"{verb} the exact Acceptance result comment")
        command.add_argument("issue", type=_positive_number)
        command.add_argument("result", type=Path)
        command.add_argument("--repo", help="repository owner/name; defaults to origin")
        command.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    work = namespaces.add_parser("work", help="freeze and recover exact-base work contexts")
    work_commands = work.add_subparsers(dest="verb", required=True)
    base = work_commands.add_parser("base", help="resolve a clean worktree's exact remote base")
    base.add_argument("issue", type=_positive_number)
    base.add_argument("--base-ref", help="explicit base ref; defaults to GitHub repository default branch")
    branch = work_commands.add_parser("branch", help="create or reuse a branch from an exact base SHA")
    branch.add_argument("issue", type=_positive_number)
    branch.add_argument("--base-ref", required=True)
    branch.add_argument("--base-sha", required=True)
    branch.add_argument("--branch-ref", required=True)
    bind = work_commands.add_parser("bind", help="freeze the current clean worktree in ExecutionBinding")
    bind.add_argument("issue", type=_positive_number)
    bind.add_argument("--base-ref", required=True)
    bind.add_argument("--base-sha", required=True)
    bind.add_argument("--branch-ref", required=True)
    recover = work_commands.add_parser("recover", help="resume the same immutable work binding")
    recover.add_argument("issue", type=_positive_number)
    recover.add_argument("--branch-ref", required=True)
    adoption_plan = work_commands.add_parser(
        "adoption-plan", help="read-only exact-head plan for the one-time Issue #63 / PR #64 epoch adoption")
    adoption_plan.add_argument("issue", type=_positive_number)
    adoption_plan.add_argument("--output", required=True, type=Path,
                               help="create-only canonical prospective adoption plan")
    adoption_apply = work_commands.add_parser(
        "adoption-apply", help="apply/recover only the separately owner-approved exact adoption plan")
    adoption_apply.add_argument("issue", type=_positive_number)
    adoption_apply.add_argument("--plan", required=True, type=Path)
    adoption_apply.add_argument("--authorization-plan", required=True, type=Path)
    adoption_refresh = work_commands.add_parser(
        "adoption-refresh", help="append the exact approved ADC successor bridge for the existing #63 epoch")
    adoption_refresh.add_argument("issue", type=_positive_number)
    for command in (base, branch, bind, recover, adoption_plan, adoption_apply, adoption_refresh):
        command.add_argument("--repo", help="repository owner/name; defaults to origin")
        command.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    pr = namespaces.add_parser("pr", help="ensure an exact open PR and immutable PRBinding")
    pr_commands = pr.add_subparsers(dest="verb", required=True)
    ensure = pr_commands.add_parser("ensure", help="reuse or create one exact Issue PR")
    ensure.add_argument("issue", type=_positive_number)
    ensure.add_argument("--branch-ref", required=True)
    ensure.add_argument("--base-ref", required=True)
    ensure.add_argument("--title", required=True)
    ensure.add_argument("--body-file", type=Path, required=True,
                        help="UTF-8 PR body with one standalone Closes #N or deferred Refs #N line")
    ensure.add_argument("--repo", help="repository owner/name; defaults to origin")
    ensure.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    audit = namespaces.add_parser("audit", help="record subject-bound self-audit and separate review evidence")
    audit_commands = audit.add_subparsers(dest="verb", required=True)
    for verb, label in (("self", "evidence-backed requirement/checklist self-audit"),
                        ("independent", "ingest a separately supplied review-context artifact")):
        command = audit_commands.add_parser(verb, help=label)
        command.add_argument("issue", type=_positive_number)
        command.add_argument("pr", type=_positive_number)
        command.add_argument("head", help="exact PR HEAD SHA-40")
        command.add_argument("plan", type=Path)
        command.add_argument("input", type=Path)
        command.add_argument("--repo", help="repository owner/name; defaults to origin")
        command.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    delivery = namespaces.add_parser("delivery", help="aggregate exact-subject Review Readiness")
    delivery_commands = delivery.add_subparsers(dest="verb", required=True)
    readiness = delivery_commands.add_parser("readiness", help="re-read every delivery gate and persist its result")
    readiness.add_argument("issue", type=_positive_number)
    readiness.add_argument("pr", type=_positive_number)
    readiness.add_argument("head", help="exact PR HEAD SHA-40")
    readiness.add_argument("plan", type=Path)
    readiness.add_argument("verification", type=Path)
    readiness.add_argument("acceptance", type=Path)
    readiness.add_argument("self_audit", type=Path)
    readiness.add_argument("independent_review", type=Path)
    readiness.add_argument("--repo", help="repository owner/name; defaults to origin")
    readiness.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    gate_policy = delivery_commands.add_parser("gate-policy", help="pin or read the versioned gate for an Issue")
    gate_policy.add_argument("issue", type=_positive_number)
    gate_policy.add_argument("--repo", help="repository owner/name; defaults to origin")
    gate_policy.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    activation_setup = delivery_commands.add_parser(
        "consumer-activation-setup", help="create the consumer Activation Issue and setup PR")
    activation_setup.add_argument("--repo", help="repository owner/name; defaults to origin")
    activation_setup.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    activation_verify = delivery_commands.add_parser(
        "consumer-activation-verify", help="verify an admin-merged setup PR and record Activation")
    activation_verify.add_argument("pr", type=_positive_number)
    activation_verify.add_argument("--repo", help="repository owner/name; defaults to origin")
    activation_verify.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    activation_preflight = delivery_commands.add_parser(
        "consumer-activation-preflight", help="read-only Consumer Activation and Ruleset preflight")
    activation_preflight.add_argument("--repo", help="repository owner/name; defaults to origin")
    activation_preflight.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    ruleset_plan = delivery_commands.add_parser(
        "consumer-activation-ruleset-plan", help="write a canonical, read-only Ruleset plan")
    ruleset_plan.add_argument("--output", required=True, type=Path, help="path for the canonical plan JSON")
    ruleset_plan.add_argument("--repo", help="repository owner/name; defaults to origin")
    ruleset_plan.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    ruleset_apply = delivery_commands.add_parser(
        "consumer-activation-ruleset-apply", help="apply one exact owner-approved Ruleset plan")
    ruleset_apply.add_argument("--plan", required=True, type=Path, help="canonical Ruleset plan JSON")
    ruleset_apply.add_argument("--approval-comment-id", type=_positive_number)
    ruleset_apply.add_argument("--repo", help="repository owner/name; defaults to origin")
    ruleset_apply.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    owner_plan = delivery_commands.add_parser(
        "owner-authorize-plan", help="read live GitHub subjects and write an immutable owner authorization plan")
    owner_plan.add_argument("operation", choices=(
        "ADC_SUPERSEDE", "RULESET_PLAN_APPLY", "USER_REVIEW", "PR_MERGE", "EXECUTION_ADOPTION"))
    owner_plan.add_argument("--subject-file", type=Path, help="exact successor ADC bytes for ADC_SUPERSEDE")
    owner_plan.add_argument("--ruleset-plan", type=Path, help="canonical Ruleset plan for RULESET_PLAN_APPLY")
    owner_plan.add_argument("--adoption-plan", type=Path,
                            help="complete exact-HEAD Issue #63 / PR #64 adoption plan")
    owner_plan.add_argument("--session", type=Path, help="exact User Review session for USER_REVIEW")
    owner_plan.add_argument("--readiness", type=Path, help="exact PASS Readiness result for USER_REVIEW")
    owner_plan.add_argument("--feedback-snapshot", type=Path,
                            help="pre-decision feedback snapshot for USER_REVIEW")
    owner_plan.add_argument("--pr", type=_positive_number, help="exact PR number for PR_MERGE")
    owner_plan.add_argument("--head", help="exact current PR HEAD SHA-40 for PR_MERGE")
    owner_plan.add_argument("--target-issue", type=_positive_number,
                            help="Issue closed by the exact PR (57 for Activation or 63 for implementation)")
    owner_plan.add_argument("--output", required=True, type=Path, help="create-only canonical plan path")
    owner_plan.add_argument("--repo", help="repository owner/name; defaults to origin")
    owner_plan.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    owner_commit = delivery_commands.add_parser(
        "owner-authorize-commit", help="deprecated; chat approvals are accepted only by the in-process integration")
    owner_commit.add_argument("--plan", required=True, type=Path, help="exact canonical owner authorization plan")
    owner_commit.add_argument("--subject-file", type=Path, help="same ADC source used by ADC_SUPERSEDE plan")
    owner_commit.add_argument("--ruleset-plan", type=Path, help="same canonical Ruleset plan used for approval")
    owner_commit.add_argument("--adoption-plan", type=Path,
                              help="same immutable exact-HEAD adoption plan")
    owner_commit.add_argument("--session", type=Path, help="same immutable User Review session")
    owner_commit.add_argument("--readiness", type=Path,
                              help="same User Review or fresh PR #64 Final Delivery Readiness")
    owner_commit.add_argument("--feedback-snapshot", type=Path,
                              help="same pre-decision complete feedback snapshot")
    owner_commit.add_argument("--delivery-plan", type=Path, help="frozen Verification Plan for PR #64 merge")
    owner_commit.add_argument("--verification", type=Path, help="PASS Verification result for PR #64 merge")
    owner_commit.add_argument("--acceptance", type=Path, help="completed Acceptance record for PR #64 merge")
    owner_commit.add_argument("--self-audit", type=Path, help="completed self-audit for PR #64 merge")
    owner_commit.add_argument("--independent-review", type=Path,
                              help="independent review evidence for PR #64 merge")
    owner_commit.add_argument("--user-review-record", type=Path,
                              help="approved User Review record for PR #64 merge")
    owner_commit.add_argument("--repo", help="repository owner/name; defaults to origin")
    owner_commit.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    owner_resume = delivery_commands.add_parser(
        "owner-authorize-resume", help="read-only direct/list/direct reconciliation of an owner decision")
    owner_resume.add_argument("--plan", required=True, type=Path)
    owner_resume.add_argument("--session", type=Path, help="exact User Review session for USER_REVIEW recovery")
    owner_resume.add_argument("--readiness", type=Path, help="current PASS Readiness for USER_REVIEW recovery")
    owner_resume.add_argument("--repo", help="repository owner/name; defaults to origin")
    owner_resume.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    admin_plan = delivery_commands.add_parser(
        "consumer-activation-admin-plan", help="create a Ruleset plan with isolated browser device auth")
    admin_plan.add_argument("--output", required=True, type=Path)
    admin_plan.add_argument("--auth-mode", choices=("pat", "isolated-gh-device"), default="isolated-gh-device",
                             help="isolated browser device auth; pat is a nonstandard owner-local fallback")
    admin_plan.add_argument("--repo", help="repository owner/name; defaults to origin")
    admin_plan.add_argument("--root", type=Path, help="repository root; defaults to current checkout")
    admin_apply = delivery_commands.add_parser(
        "consumer-activation-admin-apply", help="apply an exact-approved Ruleset plan with isolated browser device auth")
    admin_apply.add_argument("--plan", required=True, type=Path)
    admin_apply.add_argument("--approval-comment-id", type=_positive_number)
    admin_apply.add_argument("--auth-mode", choices=("pat", "isolated-gh-device"), default="isolated-gh-device",
                             help="isolated browser device auth; pat is a nonstandard owner-local fallback")
    admin_apply.add_argument("--repo", help="repository owner/name; defaults to origin")
    admin_apply.add_argument("--root", type=Path, help="repository root; defaults to current checkout")
    bootstrap = delivery_commands.add_parser("bootstrap-check", help="evaluate the separate migration Bootstrap gate")
    bootstrap.add_argument("issue", type=_positive_number)
    bootstrap.add_argument("pr", type=_positive_number)
    bootstrap.add_argument("--self-review-comment", type=_positive_number,
                           help="legacy option, accepted and ignored by the Bootstrap technical gate")
    bootstrap.add_argument("--independent-review-comment", type=_positive_number,
                           help="legacy option, accepted and ignored by the Bootstrap technical gate")
    bootstrap.add_argument("--unverified-host", action="append", default=[],
                           help="host/environment not verified; use 'none' when no host remains unverified")
    bootstrap.add_argument("--repo", help="repository owner/name; defaults to origin")
    bootstrap.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    final = delivery_commands.add_parser("final", help="re-read User Review, GitHub review, checks, and branch protection")
    final.add_argument("issue", type=_positive_number)
    final.add_argument("pr", type=_positive_number)
    final.add_argument("head", help="exact current PR HEAD SHA-40")
    final.add_argument("plan", type=Path)
    final.add_argument("verification", type=Path)
    final.add_argument("acceptance", type=Path)
    final.add_argument("self_audit", type=Path)
    final.add_argument("independent_review", type=Path)
    final.add_argument("readiness", type=Path)
    final.add_argument("user_review_record", type=Path)
    final.add_argument("--repo", help="repository owner/name; defaults to origin")
    final.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    finalize = delivery_commands.add_parser("finalize", help="verify ordinary closure or complete a deferred Issue close")
    finalize.add_argument("issue", type=_positive_number)
    finalize.add_argument("pr", type=_positive_number)
    finalize.add_argument("--repo", help="repository owner/name; defaults to origin")
    finalize.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    parent_final = delivery_commands.add_parser("parent", help="evaluate parent integration and its User Review gates")
    parent_final.add_argument("issue", type=_positive_number)
    parent_final.add_argument("--verification-comment-id", type=_positive_number,
                              help="exact Issue #26 comment ID containing external typed Verification evidence")
    parent_final.add_argument("--acceptance-comment-id", type=_positive_number,
                              help="exact Issue #26 comment ID containing external typed Acceptance evidence")
    parent_final.add_argument("--repo", help="repository owner/name; defaults to origin")
    parent_final.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    parent_evidence = delivery_commands.add_parser(
        "parent-evidence", help="publish exact-main GitHub Actions provenance to Issue #26")
    parent_evidence.add_argument("issue", type=_positive_number)
    parent_evidence.add_argument("kind", choices=("verification", "acceptance"))
    parent_evidence.add_argument("run_id", type=_positive_number,
                                 help="completed trusted GitHub Actions run ID for the current main SHA")
    parent_evidence.add_argument("--repo", help="repository owner/name; defaults to origin")
    parent_evidence.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    parent_labels = delivery_commands.add_parser(
        "parent-migrate-labels", help="preflight the legacy parent #26 P-ASES labels")
    parent_labels.add_argument("issue", type=_positive_number)
    parent_labels.add_argument("--apply", action="store_true",
                               help="apply the exact preflighted labels after Issue and label readback")
    parent_labels.add_argument("--repo", help="repository owner/name; defaults to origin")
    parent_labels.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    user_review = namespaces.add_parser("user-review", help="start, synchronize, or inspect exact-subject human review")
    user_review_commands = user_review.add_subparsers(dest="verb", required=True)
    for verb in ("start", "sync", "status"):
        command = user_review_commands.add_parser(verb)
        command.add_argument("issue", type=_positive_number)
        command.add_argument("pr", type=_positive_number)
        command.add_argument("head", help="exact current PR HEAD SHA-40")
        command.add_argument("plan", type=Path)
        command.add_argument("readiness", type=Path)
        command.add_argument(
            "--kind", choices=tuple(kind.value for kind in IssueKind), default=None,
            help="assert the Issue kind; when omitted, use its unique verified kind:* label",
        )
        if verb == "sync":
            command.add_argument("--new-scope", action="store_true",
                                 help="route explicitly triaged new scope back to requirements")
        command.add_argument("--repo", help="repository owner/name; defaults to origin")
        command.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    record_chat = user_review_commands.add_parser("record", help="record a host-attested direct chat decision")
    record_chat.add_argument("issue", type=_positive_number)
    record_chat.add_argument("pr", type=_positive_number)
    record_chat.add_argument("event_file", type=Path,
                             help="host payload is not trusted by the CLI; use a verified host adapter")
    record_chat.add_argument("--repo", help="repository owner/name; defaults to origin")
    record_chat.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")

    docs = namespaces.add_parser("docs", help="validate and deterministically format canonical Markdown docs")
    docs_commands = docs.add_subparsers(dest="verb", required=True)
    docs_validate = docs_commands.add_parser("validate", help="validate document structure, links, and traceability")
    docs_validate.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    docs_format = docs_commands.add_parser("format", help="number headings and refresh contents maps")
    mode = docs_format.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="atomically write deterministic formatting")
    mode.add_argument("--check", action="store_true", help="report formatting drift without writing")
    docs_format.add_argument("--root", type=Path, help="repository root; defaults to the current checkout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.namespace == "project":
            return _project_status(_runtime_root(args))
        if args.namespace == "context":
            root = _runtime_root(args)
            repository = args.repo or discover_repository(root)
            return _context_show(args.issue, repository, root, GitHub(repository))

        if args.namespace in {"work", "pr", "audit", "delivery", "user-review"}:
            root = _runtime_root(args)
            repository = args.repo or discover_repository(root)
            github = GitHub(repository)
            if args.namespace == "work":
                return _work_command(args, repository, root, github)
            if args.namespace == "pr":
                if args.verb != "ensure":
                    raise CLIError("unknown PR command")
                return _pr_ensure(args, repository, root, github)
            if args.namespace == "audit":
                if args.verb == "self":
                    return _audit_self(args, repository, root, github)
                return _audit_independent(args, repository, root, github)
            if args.namespace == "delivery" and args.verb == "owner-authorize-plan":
                return _owner_authorization_plan_command(args, repository, root, github)
            if args.namespace == "delivery" and args.verb == "owner-authorize-commit":
                return _owner_authorization_commit_command(args, repository, root, github)
            if args.namespace == "delivery" and args.verb == "owner-authorize-resume":
                return _owner_authorization_resume_command(args, repository, root, github)
            if args.namespace == "user-review":
                if args.verb == "record":
                    return _user_review_record(args)
                return _user_review_run(args, repository, root, github)
            if args.verb == "gate-policy":
                return _delivery_gate_policy(args, repository, root, github)
            if args.verb == "consumer-activation-setup":
                try:
                    result = setup_consumer_activation(root, github)
                    _json(result)
                    return 0 if result.get("status") == "ACTIVE" else 2
                except ConsumerActivationError as exc:
                    review_mode = "unknown"
                    checks_verified = False
                    try:
                        profile = load_profile(root)
                        review_mode = profile.final_delivery_review_mode
                        checks_verified = bool(profile.required_checks) and all(
                            app_id is not None for _name, app_id in profile.required_checks)
                    except ProfileError:
                        pass
                    _json({"status": "BLOCKED", "stage": "DISCOVER_AND_PREFLIGHT",
                           "repository": repository, "issue": getattr(args, "issue", None),
                           "required_setting_inventory": activation_setting_inventory(
                               review_mode, required_checks_verified=checks_verified, blocked=True),
                           "reasons": [str(exc)]})
                    return 2
            if args.verb == "consumer-activation-verify":
                try:
                    if discover_repository(root).casefold() != repository.casefold():
                        raise ConsumerActivationError("GitHub repository does not match the active workspace origin")
                    record, comment_id = verify_and_record_activation(github, args.pr, root=root)
                    _json({"status": "ACTIVATED", "repository": repository,
                           "issue": record.activation_issue_number, "pr": args.pr,
                           "activation_comment_id": comment_id, "activated_at": record.activated_at,
                           "activation_sha256": record.sha256,
                           "required_setting_inventory": activation_setting_inventory(
                               record.review_mode or "external_reviewer",
                               required_checks_verified=bool(record.required_check_runs),
                               policy_verified=record.schema_version == 2)})
                    return 0
                except ConsumerActivationError as exc:
                    return _blocked_result((str(exc),))
            if args.verb in {"consumer-activation-admin-plan", "consumer-activation-admin-apply"}:
                try:
                    authorized_plan_sha: str | None = None
                    if args.verb == "consumer-activation-admin-apply":
                        try:
                            plan, _decision_id = _ruleset_operation_plan(github, args.plan)
                        except OwnerDecisionError as exc:
                            if "missing exact owner operation/subject" in str(exc):
                                _json({"status": "PENDING_APPROVAL", "stage": "AWAIT_OWNER_POLICY_DECISION",
                                       "plan_path": str(args.plan), "reasons": [str(exc)]})
                                return 2
                            raise
                        _verify_activation_plan_checkpoint(root, repository, plan)
                        authorized_plan_sha = plan["plan_sha256"]
                        if plan["diff"]["operation"] != "noop" and args.approval_comment_id is None:
                            _json({"status": "PENDING_APPROVAL", "stage": "AWAIT_OWNER_POLICY_DECISION",
                                   "plan_path": str(args.plan), "plan_sha256": authorized_plan_sha,
                                   "reasons": ["the isolated owner relay must return the exact Issue #57 approval comment ID"]})
                            return 2
                    with temporary_admin_client(repository, auth_mode=args.auth_mode) as admin:
                        profile = load_profile(root)
                        if profile.activation_issue_number != 57:
                            raise CLIError("temporary Admin target must match configured Activation #57")
                        identity = admin.authenticated_user()
                        metadata = admin.repository_metadata()
                        owner = metadata.get("owner") if isinstance(metadata, dict) else None
                        owner_id = owner.get("id") if isinstance(owner, dict) else None
                        login = owner.get("login") if isinstance(owner, dict) else None
                        if (metadata.get("id") != 1401910271
                                or metadata.get("full_name") != repository
                                or not isinstance(owner, dict) or owner.get("type") != "User"
                                or owner_id != 3744776 or identity.get("id") != owner_id
                                or identity.get("type") != "User"
                                or identity.get("login", "").casefold() != login.casefold()
                                or metadata.get("permissions", {}).get("admin") is not True
                                or admin.collaborator_permission(login).get("permission") != "admin"):
                            raise CLIError("temporary administrator identity/permission mismatch")
                        branch = metadata.get("default_branch")
                        if not isinstance(branch, str):
                            raise CLIError("default branch is unavailable")
                        # Policy reads are centralized in build_ruleset_plan and
                        # apply_ruleset_plan via _read_policy -> assess_branch_policy.
                        # That path may accept a legacy-protection 404 only when
                        # branch, Ruleset inventory, effective rules and details
                        # independently prove NOT_CONFIGURED; 403/incomplete reads
                        # stay fail-closed. Do not make this probe successful-only.
                        if (args.verb == "consumer-activation-admin-apply"
                                and plan["diff"]["operation"] == "noop"):
                            current = build_ruleset_plan(
                                root, admin, profile_ref=plan.get("profile_ref"),
                                activation_binding=plan.get("activation_binding"),
                            )
                            if current["plan_sha256"] != authorized_plan_sha:
                                raise RulesetManagementError("Ruleset NOOP plan changed before verified readback")
                            if plan.get("activation_binding") is not None:
                                activation = setup_consumer_activation(root, github, policy_github=admin)
                                _json({"status": activation.get("status"), "operation": "NOOP",
                                       "plan_sha256": authorized_plan_sha, "activation": activation})
                                return 0 if activation.get("status") == "ACTIVE" else 2
                            policy = _verify_ruleset_noop(admin, plan)
                            _json({"status": "VERIFIED", "operation": "NOOP",
                                   "plan_sha256": authorized_plan_sha, "ruleset_id": policy["ruleset_id"],
                                   "applied_record_id": policy["applied_record_id"],
                                   "effective_policy_sha256": policy["effective_policy_sha256"]})
                            return 0
                        if args.verb == "consumer-activation-admin-plan":
                            activation_binding = None
                            profile_ref = None
                            checkpoint_path = activation_checkpoint_path(root, 57)
                            checkpoint = None
                            if checkpoint_path.exists():
                                checkpoint = read_activation_checkpoint(checkpoint_path)
                                if (checkpoint.repository.casefold() != repository.casefold()
                                        or checkpoint.repository_id != metadata.get("id")
                                        or checkpoint.owner_id != owner_id
                                        or checkpoint.stage not in {"POLICY_PLAN", "AWAIT_OWNER_POLICY_DECISION",
                                                                    "APPLY_AND_READBACK"}
                                        or checkpoint.setup_branch is None
                                        or checkpoint.setup_commit_sha40 is None):
                                    raise CLIError("Activation checkpoint is stale or not resumable at POLICY_PLAN")
                                current_base = admin.branch(checkpoint.default_branch).get("commit", {}).get("sha")
                                if current_base != checkpoint.default_branch_sha40:
                                    raise CLIError("Activation checkpoint base is stale; rerun setup to rebuild the exact branch and plan")
                                activation_binding = {
                                    "activation_issue_number": checkpoint.activation_issue_number,
                                    "adc_comment_id": checkpoint.adc_comment_id,
                                    "adc_sha256": checkpoint.adc_sha256,
                                    "base_sha40": checkpoint.default_branch_sha40,
                                    "predecessor_record_id": checkpoint.predecessor_record_id,
                                    "schema": "PASES_ACTIVATION_RULESET_BINDING_V1",
                                    "setup_branch": checkpoint.setup_branch,
                                    "setup_commit_sha40": checkpoint.setup_commit_sha40,
                                }
                                profile_ref = checkpoint.setup_commit_sha40
                            plan = build_ruleset_plan(
                                root, admin, profile_ref=profile_ref, activation_binding=activation_binding,
                            )
                            if plan["blockers"]:
                                return _blocked_result(tuple(plan["blockers"]))
                            write_ruleset_plan(args.output, plan)
                            if checkpoint is not None:
                                next_stage = ("APPLY_AND_READBACK" if plan["diff"]["operation"] == "noop"
                                              else "AWAIT_OWNER_POLICY_DECISION")
                                next_status = ("ADMIN_AUTH_REQUIRED" if next_stage == "APPLY_AND_READBACK"
                                               else "PENDING_APPROVAL")
                                checkpoint = replace(
                                    checkpoint, stage=next_stage, status=next_status,
                                    plan_sha256=plan["plan_sha256"],
                                    policy_status=(plan.get("policy_proof", {}).get("status")
                                                   if isinstance(plan.get("policy_proof"), dict) else None),
                                )
                                write_activation_checkpoint(checkpoint_path, checkpoint, root=root)
                            _json({"status": "PLANNED", "plan_sha256": plan["plan_sha256"],
                                   "output": str(args.output), "operation": plan["diff"]["operation"],
                                   "activation_stage": (checkpoint.stage if checkpoint is not None else None)})
                            return 0
                        result = apply_ruleset_plan(
                            root, admin, args.plan, args.approval_comment_id,
                            expected_plan_sha256=authorized_plan_sha,
                        )
                        if plan.get("activation_binding") is not None:
                            activation = setup_consumer_activation(root, github, policy_github=admin)
                            _json({"status": activation.get("status"), "ruleset": result,
                                   "activation": activation})
                            return 0 if activation.get("status") == "ACTIVE" else 2
                        _json(result)
                        return 0
                except (AdminAuthError, RulesetManagementError, ProfileError, GitHubError, CLIError,
                        OwnerDecisionError) as exc:
                    return _blocked_result((str(exc),))
            if args.verb == "consumer-activation-preflight":
                try:
                    result = ruleset_preflight(root, github)
                    _json(result)
                    return 0 if not result["blockers"] else 2
                except RulesetManagementError as exc:
                    return _blocked_result((str(exc),))
            if args.verb == "consumer-activation-ruleset-plan":
                try:
                    plan = build_ruleset_plan(root, github)
                    if plan["blockers"]:
                        _json({"status": "BLOCKED", "blockers": plan["blockers"],
                               "plan_sha256": plan["plan_sha256"], "plan": plan})
                        return 2
                    write_ruleset_plan(args.output, plan)
                    _json({"status": "PLANNED", "output": str(args.output),
                           "plan_sha256": plan["plan_sha256"], "operation": plan["diff"]["operation"]})
                    return 0
                except RulesetManagementError as exc:
                    return _blocked_result((str(exc),))
            if args.verb == "consumer-activation-ruleset-apply":
                try:
                    plan, _decision_id = _ruleset_operation_plan(github, args.plan)
                    if plan["diff"]["operation"] == "noop":
                        policy = _verify_ruleset_noop(github, plan)
                        _json({"status": "VERIFIED", "operation": "NOOP", "plan_sha256": plan["plan_sha256"],
                               "ruleset_id": policy["ruleset_id"],
                               "applied_record_id": policy["applied_record_id"],
                               "effective_policy_sha256": policy["effective_policy_sha256"]})
                        return 0
                    _json({"status": "ADMIN_AUTH_REQUIRED", "stage": "APPLY_AND_READBACK",
                           "plan_sha256": plan["plan_sha256"],
                           "next_permitted_step": "Run consumer-activation-admin-apply with isolated browser device authentication; a runner-managed PTY must display the challenge."})
                    return 2
                except OwnerDecisionError as exc:
                    if "missing exact owner operation/subject" in str(exc):
                        _json({"status": "PENDING_APPROVAL", "stage": "AWAIT_OWNER_POLICY_DECISION",
                               "plan_path": str(args.plan), "reasons": [str(exc)]})
                        return 2
                    return _blocked_result((str(exc),))
                except (RulesetManagementError, CLIError) as exc:
                    return _blocked_result((str(exc),))
            if args.verb == "bootstrap-check":
                return _delivery_bootstrap_check(args, repository, root, github)
            if args.verb == "readiness":
                with adc_forward_generation_session(github, args.issue):
                    return _delivery_readiness(args, repository, root, github)
            if args.verb == "final":
                return _delivery_final(args, repository, root, github)
            if args.verb == "finalize":
                return _delivery_finalize(args, repository, root, github)
            if args.verb == "parent":
                return _delivery_parent(args, repository, root, github)
            if args.verb == "parent-evidence":
                return _publish_parent_gate_evidence(args, repository, root, github)
            if args.verb == "parent-migrate-labels":
                return _delivery_parent_label_migration(args, repository, github)
            raise CLIError("unknown Delivery command")

        if args.namespace in {"verification", "acceptance"}:
            root: Path | None = None
            if hasattr(args, "root"):
                root_arg = args.root
                root = _repo_root(None) if root_arg is None else Path(root_arg)
                if root.is_symlink() or not root.is_dir():
                    raise CLIError("repository root must be a regular directory")
                root = root.resolve()
            repository = args.repo or discover_repository(root or _repo_root(None))
            github = GitHub(repository)
            if args.namespace == "verification":
                if args.verb == "plan":
                    return _verification_plan(args, repository, root, github)
                if args.verb == "collect":
                    return _verification_collect(args, repository, root, github)
                if args.verb in {"validate", "final"}:
                    return _verification_gate(args, repository, root, github, persist=args.verb == "final")
                return _verification_published(args, repository, root or _repo_root(None), github)
            if args.verb == "prepare":
                return _acceptance_template(args, repository, root, github)
            if args.verb == "validate":
                return _acceptance_validate(args, repository, root, github)
            if args.verb == "publish":
                return _acceptance_publish(args, repository, root or _repo_root(None), github)
            return _acceptance_verify(args, repository, root or _repo_root(None), github)

        if args.namespace == "docs":
            root = (args.root or _repo_root(None)).resolve()
            if args.verb == "validate":
                errors = validate_documents(root)
                _json({"status": "VALID" if not errors else "INVALID", "root": str(root),
                       "errors": errors})
                return 0 if not errors else 2
            changed = format_tree(root, write=args.write)
            status = "FORMATTED" if args.write else ("CLEAN" if not changed else "DRIFT")
            _json({"status": status, "root": str(root), "changed_paths": list(changed)})
            return 0 if args.write or not changed else 2

        if args.repo:
            repository = args.repo
        else:
            repository = discover_repository(_repo_root(None))
        if args.namespace == "adc":
            if args.verb == "validate":
                contract = parse_adc(args.source.read_bytes(), repository, args.issue)
                _json({"status": "VALID", "issue": args.issue, "repository": repository,
                       "adc_sha256": contract.sha256, "byte_length": contract.byte_length,
                       "requirement_ids": contract.requirement_ids, "child_key": contract.child_key})
                return 0
            github = GitHub(repository)
            if args.verb == "publish":
                data = args.source.read_bytes()
                expected_current = None
                issue63_target = (args.issue == 63
                                  and repository.casefold() == "puchinya/ai-agent-workflow")
                if issue63_target and args.state == "approved":
                    if args.approval_comment_id is None:
                        _json({"status": "PENDING_APPROVAL", "issue": args.issue,
                               "operation": "ADC_SUPERSEDE",
                               "reasons": ["an exact ADC_SUPERSEDE decision comment ID is required"]})
                        return 2
                    contract = parse_adc(data, repository, args.issue)
                    try:
                        decision = read_verified_owner_decision(
                            github, issue_number=args.issue, owner_id=3744776,
                            operation="ADC_SUPERSEDE", subject_sha256=contract.sha256,
                            repository_id=_ISSUE63_REPOSITORY_ID,
                        )
                    except OwnerDecisionError as exc:
                        if "missing exact owner operation/subject" in str(exc):
                            _json({"status": "PENDING_APPROVAL", "issue": args.issue,
                                   "operation": "ADC_SUPERSEDE", "adc_sha256": contract.sha256,
                                   "reasons": [str(exc)]})
                            return 2
                        raise CLIError(str(exc)) from exc
                    if decision.comment_id != args.approval_comment_id:
                        raise CLIError("ADC_SUPERSEDE comment ID differs from the exact verified decision")
                    expected_current = verify_adc(github, args.issue).pointer
                    if expected_current.state != "approved":
                        raise CLIError("ADC supersession requires the exact current approved predecessor")
                    if not args.supersede:
                        raise CLIError("ADC_SUPERSEDE requires --supersede")
                pointer = publish_adc(github, args.issue, data,
                                      state=args.state,
                                      explicitly_approved=(args.state == "approved"),
                                      supersede=args.supersede,
                                      expected_current=expected_current)
                phase_result = None
                if issue63_target and pointer.state == "approved":
                    try:
                        phase_result = rebaseline_issue_phase(github, args.issue)
                    except PhaseRebaselineError as exc:
                        status = ("BLOCKED_PERMISSION" if str(exc).startswith("BLOCKED_PERMISSION:")
                                  else "ADC_PUBLISHED_PHASE_BLOCKED")
                        _json({"status": status, "issue": args.issue,
                               "comment_id": pointer.comment_id, "adc_sha256": pointer.sha256,
                               "byte_length": pointer.byte_length, "state": pointer.state,
                               "reasons": [str(exc)]})
                        return 2
                _json({"status": "PUBLISHED", "issue": args.issue, "comment_id": pointer.comment_id,
                       "adc_sha256": pointer.sha256, "byte_length": pointer.byte_length,
                       "state": pointer.state, "phase_rebaseline": phase_result})
                return 0
            if args.verb == "verify":
                verified = verify_adc(github, args.issue)
                _json({"status": "VERIFIED", "issue": args.issue,
                       "comment_id": verified.pointer.comment_id,
                       "adc_sha256": verified.pointer.sha256,
                       "byte_length": verified.pointer.byte_length,
                       "state": verified.pointer.state,
                       "requirement_ids": verified.contract.requirement_ids})
                return 0
            verified = restore_adc(github, args.issue, args.destination)
            _json({"status": "RESTORED", "issue": args.issue, "destination": str(args.destination),
                   "comment_id": verified.pointer.comment_id, "adc_sha256": verified.pointer.sha256,
                   "byte_length": verified.pointer.byte_length})
            return 0

        if args.verb == "phase-rebaseline":
            github = GitHub(repository)
            try:
                result = rebaseline_issue_phase(github, args.issue)
                _json(result)
                return 0
            except PhaseRebaselineError as exc:
                if str(exc).startswith("BLOCKED_PERMISSION:"):
                    _json({"status": "BLOCKED_PERMISSION", "issue": args.issue,
                           "reasons": [str(exc)]})
                    return 2
                return _blocked_result((str(exc),))

        if args.verb == "phase-evidence":
            root = _repo_root(str(args.root)).resolve()
            github = GitHub(repository)
            source, target = Phase(args.from_phase), Phase(args.to_phase)
            skips = _phase_skip_reasons(args.skip_phase)
            comment_id, decision = publish_phase_evidence(
                github, root, args.issue, source, target, skips)
            _json({"status": "PUBLISHED", "issue": args.issue, "comment_id": comment_id,
                   "schema": decision.payload["schema"], "from": source.value, "to": target.value,
                   "adc_comment_id": decision.payload["adc_comment_id"],
                   "adc_sha256": decision.payload["adc_sha256"],
                   "branch_ref": decision.payload["branch_ref"],
                   "commit_sha40": decision.payload["commit_sha40"],
                   "documents": decision.payload["documents"]})
            return 0

        if args.verb == "phase-refresh-ready":
            root = _repo_root(str(args.root)).resolve()
            github = GitHub(repository)
            comment_id, receipt, result = refresh_ready_phase_evidence(github, root, args.issue)
            _json({
                "status": result,
                "issue": args.issue,
                "comment_id": comment_id,
                "schema": receipt.payload["schema"],
                "phase": receipt.payload.get("phase", receipt.payload.get("to_phase")),
                "commit_sha40": receipt.payload["commit_sha40"],
                "ready_decision_comment_id": receipt.payload.get("ready_decision_comment_id", comment_id),
                "predecessor_comment_id": receipt.payload.get("predecessor_comment_id"),
            })
            return 0

        if args.verb == "advance":
            github = GitHub(repository)
            issue = github.issue(args.issue)
            if issue.get("state") != "open" or issue.get("pull_request") is not None:
                raise CLIError("Issue advance requires an open Issue, not a pull request")
            label_rows = issue.get("labels")
            if not isinstance(label_rows, list) or any(not isinstance(item, dict) for item in label_rows):
                raise CLIError("Issue label readback is invalid")
            labels = [item.get("name") for item in label_rows]
            if any(not isinstance(label, str) for label in labels):
                raise CLIError("Issue label readback contains an invalid name")
            phase = parse_phase_labels(labels)
            attention = parse_attention_labels(labels)
            skip_reasons = _phase_skip_reasons(args.skip_phase)
            kind = IssueKind(args.kind)
            bootstrap = (repository.casefold() == BOOTSTRAP_REPOSITORY.casefold()
                         and args.issue in PHASE_EVIDENCE_BOOTSTRAP_ISSUES)
            kind_labels = [label.removeprefix("kind:") for label in labels if label.startswith("kind:")]
            if not bootstrap and (len(kind_labels) != 1 or kind_labels[0] != kind.value):
                raise CLIError("--kind must match the Issue's unique verified kind:* label")
            if bootstrap and kind_labels and (len(kind_labels) != 1 or kind_labels[0] != kind.value):
                raise CLIError("Bootstrap Issue kind label conflicts with --kind")
            target = Phase(args.target)
            evidence_required = (not bootstrap and kind in {IssueKind.SINGLE, IssueKind.CHILD}
                                 and target in {Phase.SPECIFICATION, Phase.DESIGN, Phase.READY})
            ordinary_issue = (not bootstrap and kind in {IssueKind.SINGLE, IssueKind.CHILD})
            root: Path | None = None
            approved_adc = None
            ordinary_context = None
            if ordinary_issue:
                if args.root is None:
                    raise CLIError("ordinary Issue phase transitions require --root for Activation and ADC verification")
                root = _repo_root(str(args.root)).resolve()
                ordinary_context = verify_ordinary_issue_context(
                    github, root, args.issue, kind,
                    require_binding=target in {Phase.EXECUTION, Phase.VERIFICATION},
                )
                approved_adc = ordinary_context.verified_adc
                if target is Phase.EXECUTION:
                    verify_ready_preparation(
                        github, root, args.issue, kind, verified_context=ordinary_context,
                    )
            if evidence_required:
                if args.phase_evidence_comment_id is None:
                    raise CLIError("specification, design, and ready transitions require --phase-evidence-comment-id")
                verify_phase_evidence(github, root, args.issue, args.phase_evidence_comment_id,
                                      phase, target, skip_reasons)
            graph_validated = False
            if kind is IssueKind.PARENT and phase is Phase.REQUIREMENTS and target is Phase.READY:
                validate_native_issue_graph(github, args.issue)
                graph_validated = True
            next_state = advance(PhaseState(args.issue, kind, phase, attention), target,
                                 skip_reasons=skip_reasons, issue_graph_validated=graph_validated)
            kept = [label for label in labels if not label.startswith(("phase:", "attention:"))]
            kept.append(f"phase:{next_state.phase.value}")
            kept.extend(f"attention:{item.value}" for item in sorted(next_state.attention, key=lambda x: x.value))
            if ordinary_issue and root is not None:
                latest_context = verify_ordinary_issue_context(
                    github, root, args.issue, kind,
                    require_binding=target in {Phase.EXECUTION, Phase.VERIFICATION},
                )
                latest_adc = latest_context.verified_adc
                if (approved_adc is None or latest_adc.pointer != approved_adc.pointer
                        or latest_adc.contract.sha256 != approved_adc.contract.sha256):
                    raise CLIError("approved ADC pointer or generation changed before the phase label write")
                if target is Phase.EXECUTION:
                    verify_ready_preparation(
                        github, root, args.issue, kind, verified_context=latest_context,
                    )
            if evidence_required and root is not None:
                verify_phase_evidence(github, root, args.issue, args.phase_evidence_comment_id,
                                      phase, target, skip_reasons)
            latest = github.issue(args.issue)
            if (latest.get("number") != args.issue or latest.get("state") != "open"
                    or latest.get("pull_request") is not None or latest.get("labels") != label_rows
                    or latest.get("body") != issue.get("body")
                    or latest.get("repository_url") != issue.get("repository_url")):
                raise CLIError("Issue state changed before the phase label write")
            write_error: GitHubError | None = None
            try:
                github.replace_issue_labels(args.issue, kept)
            except GitHubError as exc:
                # The same complete readback is required after both a normal response
                # and a lost/failed response; the exception alone cannot establish whether
                # GitHub applied the PUT.
                write_error = exc
            try:
                final_issue = github.issue(args.issue)
                _validate_issue_advance_readback(
                    final_issue, original_issue=issue, repository=repository,
                    issue_number=args.issue, expected_labels=kept, kind=kind,
                    target=next_state.phase, attention=next_state.attention,
                    ordinary=ordinary_issue,
                )
                if ordinary_issue and root is not None:
                    final_context = verify_ordinary_issue_context(
                        github, root, args.issue, kind,
                        require_binding=target in {Phase.EXECUTION, Phase.VERIFICATION},
                    )
                    final_adc = final_context.verified_adc
                    _validate_issue_advance_readback(
                        final_context.issue, original_issue=issue, repository=repository,
                        issue_number=args.issue, expected_labels=kept, kind=kind,
                        target=next_state.phase, attention=next_state.attention,
                        ordinary=True,
                    )
                    if (approved_adc is None or final_adc.pointer != approved_adc.pointer
                            or final_adc.contract.sha256 != approved_adc.contract.sha256):
                        raise CLIError("approved ADC pointer or generation changed after the phase label write")
            except (ADCError, GitHubError, PhaseEvidenceError, CLIError, OSError, UnicodeError, ValueError) as exc:
                raise CLIError(
                    f"BLOCKED after phase label write: {exc}; the label PUT may already have applied; "
                    "no automatic rollback or retry was attempted"
                ) from (write_error or exc)
            _json({"status": "ADVANCED", "issue": args.issue, "from": phase.value,
                   "to": next_state.phase.value, "attention": sorted(x.value for x in next_state.attention)})
            return 0

        if args.verb == "integration-check":
            root = _runtime_root(args)
            return _issue_integration_check(args, repository, root, GitHub(repository))

        parent_issue, parent_sha, requirement_ids, children = load_split_plan(args.plan, repository)
        order = validate_split(parent_issue, parent_sha, requirement_ids, children)
        if args.verb == "validate-split" or getattr(args, "dry_run", False):
            _json({"status": "VALID", "parent_issue": parent_issue, "parent_adc_sha256": parent_sha,
                   "requirement_ids": requirement_ids, "child_order": order,
                   "children": [{"key": child.key, "adc_sha256": child.adc_sha256,
                                 "assigned_requirement_ids": child.assigned_requirement_ids,
                                 "dependencies": child.dependencies} for child in children]})
            return 0
        created = split_issue(GitHub(repository), parent_issue, parent_sha, requirement_ids, children)
        _json({"status": "SPLIT", "parent_issue": parent_issue,
               "children": [{"key": child.key, "issue": child.number,
                             "issue_id": child.issue_id, "adc_sha256": child.adc_sha256}
                            for child in created]})
        return 0
    except (ADCError, AcceptanceError, AuditError, CheckpointError, ExecutionError,
            DocumentError, DocumentFormatError, EvidenceError, GitError, GitHubError,
            IntegrationError, IssueGraphError, OracleTraceError, PhaseError, PlanError, ProfileError,
            PhaseEvidenceError, ReadinessError, UserReviewError, VerificationError,
            WorkError, CLIError, OSError, UnicodeError, ValueError) as exc:
        if args.namespace in {"verification", "acceptance", "work", "pr", "audit", "delivery", "user-review"}:
            return _blocked_result((str(exc),))
        print(f"p-ases: {exc}", file=sys.stderr)
        return 2
