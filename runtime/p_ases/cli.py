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
from .git import GitError, discover_repository
from .github import GitHub, GitHubError
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
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
    except (ADCError, AcceptanceError, EvidenceError, GitError, GitHubError, IssueGraphError,
            OracleTraceError, PhaseError, PlanError, VerificationError, CLIError, OSError, UnicodeError) as exc:
        if args.namespace in {"verification", "acceptance"}:
            return _blocked_result((str(exc),))
        print(f"p-ases: {exc}", file=sys.stderr)
        return 2
