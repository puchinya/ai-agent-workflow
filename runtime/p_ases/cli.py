"""Namespace-based command-line interface for P-ASES."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any

from .adc import ADCError, parse_adc, publish_adc, restore_adc, verify_adc
from .git import GitError, current_branch, discover_repository, head_sha40, remote_branch_sha, worktree_clean
from .github import GitHub, GitHubError
from .execution import ExecutionError, binding_digest, read_binding
from .checkpoint import CheckpointError, PRBinding, read_pr_binding
from .context import WorkContext
from .profile import ProfileError, load_profile
from .work import (
    WorkError, bind_work, ensure_branch, ensure_pull_request, execution_binding_path,
    pr_binding_path, recover_work,
)
from .audits import (
    AuditError, AuditItem, IndependentReview, ReviewFinding, SelfAudit,
    read_independent_review, read_self_audit, write_independent_review, write_self_audit,
)
from .delivery import (
    PRReadback, ReadinessError, evaluate_readiness, readiness_path, write_readiness,
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
from .oracle_trace import (
    OracleDefinition, OracleTraceError, TestDefinition, validate_plan_oracles,
    validate_plan_tests,
)
from .phases import IssueKind, Phase, PhaseError, PhaseState, advance, parse_attention_labels, parse_phase_labels
from .verification import (
    GateResult, RequiredCheckPolicy, VerificationError, VerificationResult,
    build_verification_result, evaluate_required_checks, read_verification_result,
    required_check_fork_status, verification_result_path, write_verification_result,
)
from .verification_plan import (
    PlanEntry, PlanError, VerificationPlan, create_plan, read_plan, verify_plan_sources,
)


class CLIError(RuntimeError):
    pass


CLI_ADVANCE_TARGETS = tuple(
    phase.value for phase in Phase if phase not in {Phase.USER_REVIEW, Phase.CLOSED}
)


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


def _positive_number(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("Issue number must be a positive integer")
    return int(value)


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


_DECLARED_REQ = re.compile(r"^\s*(?:[-*+]\s*)?(REQ-[0-9]+)\s*:", re.MULTILINE)
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
    plan, _required, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
    subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
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
    _json({"status": "EVIDENCE_RECORDED", "subject": subject.as_dict(), "subject_sha256": subject.sha256,
           "outcome": record.outcome, "evidence_sha256": digest, "evidence_refs": [str(path)], "reasons": []})
    return 0 if record.outcome == "PASS" else 2


def _calculate_verification(args: argparse.Namespace, repository: str, root: Path, github: GitHub
                             ) -> tuple[VerificationResult, list[str]]:
    verified_adc = verify_adc(github, args.issue)
    plan, _required, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
    subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
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
    evidence_root = root / ".p_ases" / "evidence"
    evidence_refs = [str(evidence_path(evidence_root, record)) for record in records]
    return result, evidence_refs


def _verification_gate(args: argparse.Namespace, repository: str, root: Path, github: GitHub,
                       *, persist: bool) -> int:
    result, evidence_refs = _calculate_verification(args, repository, root, github)
    subject = result.subject
    result_path = verification_result_path(root / ".p_ases" / "verification", result)
    if persist:
        write_verification_result(result_path, result)
        body = _result_comment("verification", result.as_json())
        comment_id = _publish_once(github, args.issue, body)
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
    comment_id = _exact_published(github, args.issue, body)
    if comment_id is None:
        return _blocked_result(("exact Verification result comment is not present on the Issue",), result.subject)
    _json({"status": "PUBLISHED", "subject": result.subject.as_dict(), "subject_sha256": result.subject.sha256,
           "result_sha256": result.sha256, "comment_id": comment_id,
           "evidence_refs": [str(args.result), f"issue-comment:{comment_id}"], "reasons": []})
    return 0


def _acceptance_template(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    verified_adc = verify_adc(github, args.issue)
    plan, _required, _oracles, _tests = _load_plan(root, repository, args.issue, args.plan, verified_adc)
    subject = _subject(repository, args.issue, args.pr, args.head, verified_adc, plan)
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
    refs = [str(evidence_path(evidence_root, evidence_by_digest[row.evidence_sha256])) for row in observations]
    return result, refs


def _acceptance_validate(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    template = _read_json(args.observations, "Acceptance input", root=root)
    result, evidence_refs = _calculate_acceptance(args, repository, root, github, template)
    path = acceptance_result_path(root / ".p_ases" / "acceptance", result)
    write_acceptance_result(path, result)
    output = result.as_json()
    output["evidence_refs"] = [str(path), str(args.observations), str(args.verification), *evidence_refs]
    output["reasons"] = list(result.reasons)
    _json(output)
    return 0 if result.status == "PASS" else 2


def _acceptance_recompute_saved(args: argparse.Namespace, repository: str, root: Path, github: GitHub,
                                result: AcceptanceResult) -> AcceptanceResult:
    if result.subject.repository != repository or result.subject.issue_number != args.issue:
        raise CLIError("Acceptance result belongs to a different repository or Issue")
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
    current_verification, _ = _calculate_verification(recompute_args, repository, root, github)
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
    comment_id = _publish_once(github, args.issue, body)
    _json({"status": "PUBLISHED", "subject": result.subject.as_dict(), "subject_sha256": result.subject.sha256,
           "result_sha256": result.sha256, "comment_id": comment_id,
           "evidence_refs": [str(args.result), f"issue-comment:{comment_id}"], "reasons": []})
    return 0


def _acceptance_verify(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    result = read_acceptance_result(args.result)
    _acceptance_recompute_saved(args, repository, root, github, result)
    body = _result_comment("acceptance", result.as_json())
    comment_id = _exact_published(github, args.issue, body)
    if comment_id is None:
        return _blocked_result(("exact Acceptance result comment is not present on the Issue",), result.subject)
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


def _approved_issue_adc(github: GitHub, issue_number: int, repository: str) -> tuple[dict[str, Any], Any]:
    issue = github.issue(issue_number)
    if (issue.get("number") != issue_number or issue.get("state") != "open"
            or issue.get("pull_request") is not None):
        raise CLIError("work management requires the exact Issue to remain open")
    verified = verify_adc(github, issue_number)
    if verified.contract.repository != repository or verified.pointer.state != "approved":
        raise CLIError("work management requires the current approved ADC for this repository")
    return issue, verified


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
    _issue, verified = _approved_issue_adc(github, args.issue, repository)
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
    binding = read_binding(binding_path)
    body = _safe_file_bytes(args.body_file, "PR body file").decode("utf-8", errors="strict")
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
           "base_sha40": result.binding.base_sha40, "head_ref": args.branch_ref,
           "head_sha40": result.binding.pr_head_sha40, "reused": result.reused,
           "pr_binding_sha256": result.binding.sha256,
           "checkpoint_path": str(result.checkpoint_path),
           "checkpoint_sha256": result.checkpoint_sha256,
           "reasons": [], "evidence_refs": [str(binding_path), str(pr_binding_path(root, args.issue)),
                                            str(result.checkpoint_path)]})
    return 0


def _audit_subject(args: argparse.Namespace, repository: str, root: Path,
                   github: GitHub) -> tuple[Any, VerificationSubject, tuple[str, ...], dict[str, str]]:
    _issue, verified = _approved_issue_adc(github, args.issue, repository)
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
    value = _read_json(args.input, "self-audit input")
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
    value = _read_json(args.input, "independent-review context artifact")
    expected = {"context_id", "findings", "provenance", "reviewed_head_sha40", "schema",
                "session_description", "subject", "verdict"}
    if (not isinstance(value, dict) or set(value) != expected
            or value.get("schema") != "PASES_INDEPENDENT_REVIEW_CONTEXT_V1"
            or VerificationSubject.from_dict(value.get("subject")) != subject
            or value.get("reviewed_head_sha40") != subject.pr_head_sha40
            or not isinstance(value.get("findings"), list)):
        raise CLIError("independent-review artifact is stale or has unknown/missing fields")
    if any(not isinstance(value.get(field), str) or not value[field].strip()
           for field in ("context_id", "provenance", "session_description", "verdict")):
        raise CLIError("independent-review context description/provenance is incomplete")
    binding = read_binding(execution_binding_path(root, args.issue))
    implementation_context = f"execution-binding:{binding_digest(binding)}"
    findings: list[ReviewFinding] = []
    for row in value["findings"]:
        if not isinstance(row, dict) or set(row) != {"description", "evidence_ref", "finding_id", "resolved", "severity"}:
            raise CLIError("independent-review finding has unknown/missing fields")
        evidence_ref, _digest = _verified_file_evidence(root, row["evidence_ref"])
        findings.append(ReviewFinding(row["finding_id"], row["severity"], row["resolved"],
                                      row["description"], evidence_ref).validate())
    findings.sort(key=lambda item: item.finding_id)
    raw = args.input.read_bytes()
    context_dir = root / ".p_ases" / "audits" / str(args.issue) / subject.sha256
    context_path = context_dir / f"review-context-{hashlib.sha256(raw).hexdigest()}.json"
    _write_immutable(context_path, raw)
    context_ref = str(context_path.relative_to(root))
    review = IndependentReview(
        subject=subject, reviewer_context_id=value["context_id"],
        implementation_context_id=implementation_context, context_artifact_ref=context_ref,
        context_artifact_sha256=hashlib.sha256(raw).hexdigest(), findings=tuple(findings), verdict=value["verdict"],
    ).validate()
    path = root / ".p_ases" / "audits" / str(args.issue) / subject.sha256 / f"independent-{review.sha256}.json"
    write_independent_review(path, review)
    _json({"status": review.verdict, "subject": subject.as_dict(), "subject_sha256": subject.sha256,
           "review_sha256": review.sha256, "reviewer_context_id": review.reviewer_context_id,
           "implementation_context_id": review.implementation_context_id,
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
    close_refs = [int(value) for value in ANY_CLOSE.findall(body)] if isinstance(body, str) else []
    own_lines = [int(value) for value in STANDALONE_CLOSE.findall(body)] if isinstance(body, str) else []
    if (not isinstance(base, dict) or not isinstance(head, dict)
            or not isinstance(base_repo, dict) or not isinstance(head_repo, dict)
            or not isinstance(base_repo.get("full_name"), str)
            or base_repo["full_name"].lower() != repository.lower()
            or not isinstance(head_repo.get("full_name"), str)
            or not isinstance(body, str)
            or close_refs != [issue_number] or own_lines != [issue_number]):
        raise CLIError("PR readback lacks exact same-repository identity or its standalone Closes #N line")
    return PRReadback(
        repository=repository, issue_number=issue_number, pr_number=pr_number,
        state=row.get("state"), draft=row.get("draft"),
        base_ref=base.get("ref"), base_sha40=base.get("sha"),
        head_ref=head.get("ref"), head_sha40=head.get("sha"),
        head_repository=head_repo["full_name"], closing_issue_number=issue_number,
    ).validate()


def _read_audit_references(root: Path, audit: SelfAudit | IndependentReview) -> tuple[str, ...]:
    references: list[str] = []
    if isinstance(audit, SelfAudit):
        refs = [ref for item in audit.items for ref in item.evidence_refs]
    else:
        refs = [audit.context_artifact_ref, *(item.evidence_ref for item in audit.findings)]
    for ref in refs:
        if isinstance(audit, IndependentReview) and ref == audit.context_artifact_ref:
            if (not isinstance(ref, str) or Path(ref).is_absolute() or "\\" in ref
                    or any(part in {"", ".", ".."} for part in ref.split("/"))):
                raise CLIError("independent-review context reference is not a canonical workspace-relative path")
            path = root / ref
            try:
                raw = _safe_file_bytes(path, "independent-review context artifact")
            except (CLIError, OSError) as exc:
                raise CLIError(f"independent-review context artifact cannot be read back: {exc}") from exc
            if hashlib.sha256(raw).hexdigest() != audit.context_artifact_sha256:
                raise CLIError("independent-review context artifact digest changed")
            references.append(str(path))
            continue
        _canonical_ref, _digest = _verified_file_evidence(root, ref)
        references.append(ref)
    return tuple(references)


def _delivery_readiness(args: argparse.Namespace, repository: str, root: Path, github: GitHub) -> int:
    blockers: list[str] = []
    published_refs: list[str] = []
    verified_adc = None
    try:
        _issue, verified_adc = _approved_issue_adc(github, args.issue, repository)
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
    binding = None
    binding_path = execution_binding_path(root, args.issue)
    try:
        binding = read_binding(binding_path)
        pr_binding = read_pr_binding(pr_binding_path(root, args.issue))
        if binding.repository != repository or binding.issue_number != args.issue:
            raise CLIError("ExecutionBinding repository/Issue does not match")
        if (binding.adc_comment_id != (None if verified_adc is None else verified_adc.pointer.comment_id)
                or binding.adc_sha256 != (None if verified_adc is None else verified_adc.pointer.sha256)):
            blockers.append("ExecutionBinding belongs to a stale ADC pointer")
    except (ExecutionError, CheckpointError, CLIError, OSError) as exc:
        blockers.append(f"current immutable work/PR binding readback failed: {exc}")

    work_context = None
    if binding is not None:
        try:
            work_context = WorkContext(
                binding, head_sha40(root), current_branch(root), worktree_clean(root), binding_digest(binding),
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
            if binding is not None and independent_review.implementation_context_id != f"execution-binding:{binding_digest(binding)}":
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
        try:
            if (current_branch(root) != (None if pr_readback is None else pr_readback.head_ref)
                    or head_sha40(root) != subject.pr_head_sha40 or not worktree_clean(root)
                    or (pr_readback is not None
                        and remote_branch_sha(root, pr_readback.head_ref) != subject.pr_head_sha40)):
                blockers.append("local worktree or remote branch changed before Readiness persistence")
        except GitError as exc:
            blockers.append(f"local/remote branch final readback failed before Readiness persistence: {exc}")
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
                )
                if last_acceptance != acceptance:
                    blockers.append("#29 Acceptance changed before Readiness persistence")
            except (AcceptanceError, ADCError, PlanError, OracleTraceError, EvidenceError,
                    VerificationError, GitHubError, CLIError, OSError) as exc:
                blockers.append(f"#29 final Acceptance readback failed: {exc}")

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
    )
    path = readiness_path(root, result)
    write_readiness(path, result)
    _json({"status": result.status, "subject": result.subject.as_dict(),
           "subject_sha256": result.subject.sha256, "readiness_sha256": result.sha256,
           "ready_for_user_review": result.ready_for_user_review, "path": str(path),
           "reasons": list(result.reasons),
           "evidence_refs": [str(path), str(args.plan), str(args.verification), str(args.acceptance),
                             str(args.self_audit), str(args.independent_review),
                             str(execution_binding_path(root, args.issue)),
                             str(pr_binding_path(root, args.issue)), *published_refs]})
    return 0 if result.status == "PASS" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m p_ases")
    namespaces = parser.add_subparsers(dest="namespace", required=True)

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
    for command in (base, branch, bind, recover):
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
                        help="UTF-8 PR body with a standalone Closes #N line")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.namespace in {"work", "pr", "audit", "delivery"}:
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
            if args.verb == "readiness":
                return _delivery_readiness(args, repository, root, github)
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
                pointer = publish_adc(github, args.issue, args.source.read_bytes(),
                                      state=args.state, explicitly_approved=(args.state == "approved"),
                                      supersede=args.supersede)
                _json({"status": "PUBLISHED", "issue": args.issue, "comment_id": pointer.comment_id,
                       "adc_sha256": pointer.sha256, "byte_length": pointer.byte_length,
                       "state": pointer.state})
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
            skip_reasons: dict[str, str] = {}
            for raw in args.skip_phase:
                name, separator, reason = raw.partition("=")
                if not separator or name in skip_reasons or name not in {"specification", "design"}:
                    raise CLIError("--skip-phase must be a unique specification=reason or design=reason")
                skip_reasons[name] = reason
            kind = IssueKind(args.kind)
            target = Phase(args.target)
            graph_validated = False
            if kind is IssueKind.PARENT and phase is Phase.REQUIREMENTS and target is Phase.READY:
                validate_native_issue_graph(github, args.issue)
                graph_validated = True
            next_state = advance(PhaseState(args.issue, kind, phase, attention), target,
                                 skip_reasons=skip_reasons, issue_graph_validated=graph_validated)
            kept = [label for label in labels if not label.startswith(("phase:", "attention:"))]
            kept.append(f"phase:{next_state.phase.value}")
            kept.extend(f"attention:{item.value}" for item in sorted(next_state.attention, key=lambda x: x.value))
            github.replace_issue_labels(args.issue, kept)
            _json({"status": "ADVANCED", "issue": args.issue, "from": phase.value,
                   "to": next_state.phase.value, "attention": sorted(x.value for x in next_state.attention)})
            return 0

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
            EvidenceError, GitError, GitHubError, IssueGraphError, OracleTraceError,
            PhaseError, PlanError, ProfileError, ReadinessError, VerificationError,
            WorkError, CLIError, OSError, UnicodeError, ValueError) as exc:
        if args.namespace in {"verification", "acceptance", "work", "pr", "audit", "delivery"}:
            return _blocked_result((str(exc),))
        print(f"p-ases: {exc}", file=sys.stderr)
        return 2
