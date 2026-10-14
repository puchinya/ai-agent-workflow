"""Shared trusted GitHub Actions evidence reconstruction for parent #26."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .adc import verify_adc
from .github import GitHub, GitHubError
from .integration import IntegrationError, IntegrationGateEvidence, ParentGateEvidenceComment


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


PARENT_ISSUE_CONTRACT_SOURCE = "planning/p-ases/08-migration-contract.md"
PARENT_ISSUE_CONTRACT_COMMIT = "f34f166f11bbbe6c45b1555827f37f9467b1e49b"
def _parent_contract_declaration(content: bytes) -> tuple[str, str, str]:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise IntegrationError("approved child ADC parent-contract reference is not UTF-8") from exc
    source_rows = re.findall(r"(?m)^Parent contract: `([^`]+)` at `([0-9a-f]{40})`$", text)
    digest_rows = re.findall(r"(?m)^Parent ADC SHA-256: `([0-9a-f]{64})`$", text)
    if (len(source_rows) != 1 or source_rows[0] !=
            (PARENT_ISSUE_CONTRACT_SOURCE, PARENT_ISSUE_CONTRACT_COMMIT) or len(digest_rows) != 1):
        raise IntegrationError("current approved child ADC does not declare the pinned parent contract and digest")
    return source_rows[0][0], source_rows[0][1], digest_rows[0]


def _parent_adc_authority(github: GitHub) -> tuple[str, Any]:
    """Read the pinned legacy parent ADC digest from approved child #31's immutable ADC."""
    child_adc = verify_adc(github, 31)
    if child_adc.pointer.state != "approved":
        raise IntegrationError("parent Integration needs the approved child #31 ADC authority")
    source_path, source_commit, parent_adc_sha256 = _parent_contract_declaration(child_adc.contract.content)
    # Parent #26 predates the append-only ADC pointer journal. Its approved digest
    # is declared by child #31's current immutable ADC and pinned to this source commit.
    if not github.content_at_ref(source_path, source_commit):
        raise IntegrationError("pinned parent contract source is empty or unavailable")
    return parent_adc_sha256, child_adc.pointer


def _parent_current_main_sha(github: GitHub) -> str:
    metadata = github.repository_metadata()
    main_ref = metadata.get("default_branch")
    if not isinstance(main_ref, str) or not main_ref:
        raise GitHubError("repository default branch is unavailable")
    row = github.branch(main_ref)
    commit = row.get("commit") if isinstance(row, dict) else None
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GitHubError("current main branch SHA is invalid")
    return sha



PARENT_TRUSTED_ACTIONS_APP_ID = 15368
PARENT_CI_WORKFLOW = ".github/workflows/ci.yml"
PARENT_ACCEPTANCE_WORKFLOW = ".github/workflows/parent-integration.yml"
PARENT_REQUIRED_CI_JOBS = (
    "test (ubuntu-latest, 3.10)", "test (ubuntu-latest, 3.14)",
    "test (windows-latest, 3.14)", "test (macos-latest, 3.14)",
)
PARENT_VERIFICATION_STEPS = {
    "compileall": "Compile runtime, tools, and tests",
    "committed-distributions": "Check committed distributions before mutation",
    "unit-tests": "Unit tests",
    "docs-validation": "Validate repository documentation",
    "distribution-build": "Generate distributions",
    "generated-distributions": "Check generated distributions",
    "distribution-validation": "Validate distributions",
    "generated-paths": "Confirm generated paths remain unchanged",
    "format-check": "Check committed diff whitespace",
}
PARENT_ACCEPTANCE_STEPS = {
    "specification-traceability": "Specification traceability",
    "design-traceability": "Design traceability",
    "test-oracle-traceability": "Test-oracle traceability",
    "16-skills-package": "Check canonical 16-Skill package",
    "generated-distributions": "Check generated distributions",
    "distribution-validation": "Validate distributions",
}



def _repository_file_reference(value: Path | str) -> str:
    """Validate a repository-relative file reference carried by parent evidence."""
    if not isinstance(value, (Path, str)):
        raise IntegrationError("parent Integration evidence reference must be text")
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise IntegrationError("parent Integration evidence reference must be repository-relative")
    reference = path.as_posix()
    if "\\" in reference or any(char in reference for char in "\x00\r\n?#:"):
        raise IntegrationError("parent Integration evidence reference is invalid")
    return reference


def _parent_gate_comment_security_fingerprint(row: dict[str, Any]) -> tuple[Any, ...]:
    """Canonical stable security identity for a GitHub parent evidence comment."""
    if not isinstance(row, dict):
        raise IntegrationError("parent evidence comment API readback is malformed")
    comment_id = row.get("id")
    body = row.get("body")
    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    issue_url = row.get("issue_url")
    html_url = row.get("html_url")
    api_url = row.get("url")
    if (type(comment_id) is not int or comment_id < 1 or not isinstance(body, str)
            or not all(isinstance(value, str) for value in
                       (created_at, updated_at, issue_url, html_url, api_url))):
        raise IntegrationError("parent evidence comment stable identity fields are malformed")
    try:
        created_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        updated_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrationError("parent evidence comment timestamps are invalid") from exc
    if (created_time.tzinfo is None or created_time.utcoffset() is None
            or updated_time.tzinfo is None or updated_time.utcoffset() is None):
        raise IntegrationError("parent evidence comment timestamps require a timezone")
    if updated_at != created_at:
        raise IntegrationError("parent evidence comment was edited")
    user = row.get("user")
    if (not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] < 1
            or not isinstance(user.get("login"), str) or not user["login"]
            or user.get("type") != "User"):
        raise IntegrationError("parent evidence comment stable author identity is malformed")
    # Profile URLs and avatar_url vary between otherwise identical GitHub API responses.
    # Only fields that identify the comment, its contents, and its authenticated author
    # participate in equality checks.
    return (comment_id, body, created_at, updated_at, issue_url, html_url, api_url,
            (user["id"], user["login"].casefold(), user["type"]))


def _load_parent_gate_evidence_from_github(
    github: GitHub, comment_id: int, main_sha40: str, kind: str,
    repository: str, parent_adc_sha256: str, *, require_authenticated_author: bool = True,
) -> IntegrationGateEvidence:
    """Read the exact comment and independently reconstruct its Actions provenance twice.

    Parent Integration publication/readback requires the current authenticated user
    to be the comment author. Historical Activation validation instead checks the
    repository owner identity from each stable comment snapshot.
    """
    if not isinstance(main_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", main_sha40):
        raise IntegrationError("parent Integration evidence requires an exact main SHA-40")
    if type(comment_id) is not int or comment_id < 1:
        raise IntegrationError("parent Integration evidence requires a positive Issue comment ID")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise IntegrationError("parent Integration evidence repository is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", parent_adc_sha256):
        raise IntegrationError("parent Integration evidence parent ADC digest is invalid")

    def read_comment() -> tuple[dict[str, Any], ParentGateEvidenceComment, bytes, tuple[Any, ...]]:
        direct = github.issue_comment(26, comment_id)
        listed = github.issue_comments(26)
        if not isinstance(direct, dict) or not isinstance(listed, list):
            raise IntegrationError("parent evidence comment API readback is malformed")
        if any(not isinstance(item, dict) for item in listed):
            raise IntegrationError("parent evidence Issue comment list contains a malformed row")
        matches = [row for row in listed if row.get("id") == comment_id]
        if len(matches) != 1:
            raise IntegrationError("pinned parent evidence comment is missing or duplicated on Issue #26")
        row = matches[0]
        direct_fingerprint = _parent_gate_comment_security_fingerprint(direct)
        listed_fingerprint = _parent_gate_comment_security_fingerprint(row)
        bundle = ParentGateEvidenceComment.from_body(row.get("body"))
        subject_comment_ids: list[int] = []
        for candidate in listed:
            candidate_body = candidate.get("body")
            if not isinstance(candidate_body, str) or not candidate_body.startswith("P-ASES-PARENT-EVIDENCE-V2\n"):
                continue
            candidate_bundle = ParentGateEvidenceComment.from_body(candidate_body)
            if (candidate_bundle.kind == kind
                    and candidate_bundle.repository.casefold() == repository.casefold()
                    and candidate_bundle.parent_issue_number == 26
                    and candidate_bundle.parent_adc_sha256 == parent_adc_sha256
                    and candidate_bundle.main_sha40 == main_sha40
                    and candidate_bundle.workflow_run_id == bundle.workflow_run_id
                    and candidate_bundle.workflow_run_attempt == bundle.workflow_run_attempt):
                if candidate.get("updated_at") != candidate.get("created_at"):
                    raise IntegrationError("a parent evidence comment for this subject was edited")
                candidate_id = candidate.get("id")
                if type(candidate_id) is not int or candidate_id < 1:
                    raise IntegrationError("parent evidence comment subject has a malformed ID")
                subject_comment_ids.append(candidate_id)
        if subject_comment_ids and subject_comment_ids != [comment_id]:
            raise IntegrationError("parent evidence subject has duplicate or mismatched comment IDs")
        after = github.issue_comment(26, comment_id)
        if not isinstance(after, dict):
            raise IntegrationError("parent evidence comment second API readback is malformed")
        after_fingerprint = _parent_gate_comment_security_fingerprint(after)
        if (direct_fingerprint != listed_fingerprint or listed_fingerprint != after_fingerprint
                or listed_fingerprint[0] != comment_id):
            raise IntegrationError("parent evidence comment was edited or changed during double-read")
        expected_issue_url = f"https://api.github.com/repos/{repository}/issues/26"
        expected_html = f"https://github.com/{repository}/issues/26#issuecomment-{comment_id}"
        expected_api = f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}"
        if (not all(isinstance(row.get(field), str) for field in ("issue_url", "html_url", "url"))
                or row["issue_url"].casefold() != expected_issue_url.casefold()
                or row["html_url"].casefold() != expected_html.casefold()
                or row["url"].casefold() != expected_api.casefold()):
            raise IntegrationError("parent evidence comment repository or Issue identity does not match")
        if require_authenticated_author:
            identity = github.authenticated_user()
            if (not isinstance(identity, dict) or type(identity.get("id")) is not int
                    or identity["id"] < 1
                    or not isinstance(identity.get("login"), str) or not identity["login"]
                    or identity.get("type") != "User"
                    or listed_fingerprint[-1] !=
                    (identity["id"], identity["login"].casefold(), identity["type"])):
                raise IntegrationError("parent evidence comment author is not the authenticated GitHub user")
        if (bundle.kind != kind or bundle.repository.casefold() != repository.casefold()
                or bundle.parent_issue_number != 26 or bundle.parent_adc_sha256 != parent_adc_sha256
                or bundle.main_sha40 != main_sha40):
            raise IntegrationError("parent evidence comment does not match the exact current main/ADC subject")
        return row, bundle, row["body"].encode("utf-8"), listed_fingerprint

    _first_row, first_bundle, first_body, first_fingerprint = read_comment()
    _second_row, second_bundle, second_body, second_fingerprint = read_comment()
    if (first_fingerprint != second_fingerprint
            or first_bundle != second_bundle or first_body != second_body):
        raise IntegrationError("parent evidence comment changed during double-read")
    _validate_parent_gate_bundle(first_bundle, kind, repository, parent_adc_sha256, main_sha40)
    expected_first = _parent_gate_bundle_from_actions(
        github, first_bundle.workflow_run_id, kind, repository, parent_adc_sha256, main_sha40)
    expected_second = _parent_gate_bundle_from_actions(
        github, first_bundle.workflow_run_id, kind, repository, parent_adc_sha256, main_sha40)
    _third_row, third_bundle, third_body, third_fingerprint = read_comment()
    if (expected_first != expected_second or expected_first != first_bundle
            or second_fingerprint != third_fingerprint or second_bundle != third_bundle
            or second_body != third_body):
        raise IntegrationError("parent evidence is not the current trusted Actions run result")
    raw_source = first_bundle.result_bytes
    source_sha256 = hashlib.sha256(raw_source).hexdigest()
    evidence = IntegrationGateEvidence(kind, repository, 26, parent_adc_sha256, main_sha40,
                                       "PASS", source_sha256, f"issue-comment:{comment_id}").validate()
    return evidence


def _check_run_id(job: dict[str, Any], repository: str) -> int:
    url = job.get("check_run_url")
    match = re.fullmatch(r"https://api\.github\.com/repos/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/check-runs/([1-9][0-9]*)", url or "")
    if (not match or f"{match.group(1)}/{match.group(2)}".casefold() != repository.casefold()):
        raise IntegrationError("GitHub Actions job has an invalid or foreign-repository Check Run URL")
    return int(match.group(3))


def _parent_gate_bundle_from_actions(
    github: GitHub, run_id: int, kind: str, repository: str,
    parent_adc_sha256: str, main_sha40: str,
) -> ParentGateEvidenceComment:
    """Build parent PASS evidence only from exact-main trusted GitHub Actions records."""
    if kind not in {"verification", "acceptance"}:
        raise IntegrationError("parent Actions evidence kind is invalid")
    workflow_path = PARENT_CI_WORKFLOW if kind == "verification" else PARENT_ACCEPTANCE_WORKFLOW
    event = "push" if kind == "verification" else "workflow_dispatch"
    runs = github.workflow_runs_for_ref(main_sha40, workflow_path=workflow_path, event=event)
    if not isinstance(runs, list) or any(not isinstance(row, dict) for row in runs):
        raise IntegrationError("GitHub Actions workflow run list is malformed")
    if not runs:
        raise IntegrationError(f"no {kind} GitHub Actions run exists on the exact main SHA")
    latest_key = max((row.get("run_number", 0), row.get("run_attempt", 0)) for row in runs)
    latest = [row for row in runs if (row.get("run_number"), row.get("run_attempt")) == latest_key]
    if len(latest) != 1 or latest[0].get("id") != run_id:
        raise IntegrationError("parent evidence references a stale or ambiguous Actions run")
    run = latest[0]
    if (run.get("id") != run_id or run.get("path") != workflow_path or run.get("event") != event
            or run.get("head_sha") != main_sha40 or run.get("head_branch") != "main"
            or run.get("status") != "completed" or run.get("conclusion") != "success"
            or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1
            or not isinstance(run.get("head_repository"), dict)
            or str(run["head_repository"].get("full_name", "")).casefold() != repository.casefold()):
        raise IntegrationError("parent evidence Actions run is incomplete, unsuccessful, forked, or stale")

    jobs = github.workflow_run_jobs(run_id)
    if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
        raise IntegrationError("GitHub Actions job response is malformed")
    required_job_names = set(PARENT_REQUIRED_CI_JOBS) | {"pull-request-metadata"} if kind == "verification" else {"parent-acceptance"}
    by_name: dict[str, dict[str, Any]] = {}
    for job in jobs:
        name = job.get("name")
        if not isinstance(name, str) or name in by_name or name not in required_job_names:
            raise IntegrationError("parent Actions run has duplicate or unexpected jobs")
        by_name[name] = job
    if set(by_name) != required_job_names:
        raise IntegrationError("parent Actions run does not contain the complete fixed job set")
    if kind == "verification" and (by_name["pull-request-metadata"].get("conclusion") != "skipped"
                                    or by_name["pull-request-metadata"].get("status") != "completed"):
        raise IntegrationError("push-triggered Verification must have a skipped PR metadata job")

    check_runs = github.check_runs_for_ref(main_sha40)
    if not isinstance(check_runs, list) or any(not isinstance(row, dict) for row in check_runs):
        raise IntegrationError("exact-main Check Runs response is malformed")
    checks_by_id: dict[int, dict[str, Any]] = {}
    for check in check_runs:
        app = check.get("app")
        if (type(check.get("id")) is not int or check["id"] < 1
                or check.get("head_sha") != main_sha40 or not isinstance(app, dict)
                or type(app.get("id")) is not int or app["id"] < 1):
            raise IntegrationError("exact-main Check Run response has incomplete SHA/App provenance")
        checks_by_id[check["id"]] = check

    job_observations: dict[str, dict[str, Any]] = {}
    required_action_checks: list[dict[str, Any]] = []
    for job_name, job in by_name.items():
        if job.get("status") != "completed":
            if kind == "verification" and job_name == "pull-request-metadata":
                continue
            raise IntegrationError(f"parent Actions job is not completed: {job_name}")
        if kind == "verification" and job_name == "pull-request-metadata":
            continue
        if job.get("conclusion") != "success" or job.get("head_sha") != main_sha40:
            raise IntegrationError(f"parent Actions job failed or has a stale SHA: {job_name}")
        check_id = _check_run_id(job, repository)
        check = checks_by_id.get(check_id)
        if (check is None or check.get("name") != job_name or check.get("status") != "completed"
                or check.get("conclusion") != "success"
                or check.get("app", {}).get("id") != PARENT_TRUSTED_ACTIONS_APP_ID):
            raise IntegrationError(f"parent Actions job Check Run provenance does not match: {job_name}")
        required_action_checks.append({
            "app_id": PARENT_TRUSTED_ACTIONS_APP_ID,
            "check_run_id": check_id,
            "conclusion": "success",
            "head_sha40": main_sha40,
            "name": job_name,
            "status": "completed",
        })
        steps = job.get("steps")
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise IntegrationError(f"parent Actions job steps are malformed: {job_name}")
        step_names = [step.get("name") for step in steps]
        if any(not isinstance(name, str) for name in step_names) or len(step_names) != len(set(step_names)):
            raise IntegrationError(f"parent Actions job has ambiguous step names: {job_name}")
        job_observations[job_name] = {
            "app_id": PARENT_TRUSTED_ACTIONS_APP_ID,
            "check_run_id": check_id,
            "head_sha40": main_sha40,
            "job_id": job["id"],
            "name": job_name,
            "status": job["status"],
            "conclusion": job["conclusion"],
            "steps": steps,
        }
    if kind == "verification":
        if set(job_observations) != set(PARENT_REQUIRED_CI_JOBS):
            raise IntegrationError("parent Verification does not have all four successful matrix jobs")
        action_check_by_name = {row["name"]: row for row in required_action_checks}
        if set(action_check_by_name) != set(PARENT_REQUIRED_CI_JOBS):
            raise IntegrationError("parent Verification Required Check provenance is incomplete")
        checks: list[dict[str, Any]] = []
        artifacts: dict[str, bytes] = {}
        for check_id, step_name in PARENT_VERIFICATION_STEPS.items():
            selected_steps: list[dict[str, Any]] = []
            for job_name in PARENT_REQUIRED_CI_JOBS:
                matches = [step for step in job_observations[job_name]["steps"] if step.get("name") == step_name]
                if (len(matches) != 1 or matches[0].get("status") != "completed"
                        or matches[0].get("conclusion") != "success"):
                    raise IntegrationError(f"exact-main CI step did not pass: {step_name} ({job_name})")
                selected_steps.append({"job": job_name, "step": matches[0]})
            reference = f"actions/{check_id}.json"
            artifact = _canonical({"check_id": check_id, "jobs": selected_steps,
                                   "main_sha40": main_sha40, "run_id": run_id}) + b"\n"
            artifacts[reference] = artifact
            checks.append({"check_id": check_id, "status": "PASS",
                           "evidence_sha256": hashlib.sha256(artifact).hexdigest(),
                           "evidence_reference": reference})
        required_reference = "actions/required-ci.json"
        required_bytes = _canonical({"check_id": "required-ci", "checks": sorted(required_action_checks, key=lambda row: row["name"]),
                                     "main_sha40": main_sha40, "run_id": run_id}) + b"\n"
        artifacts[required_reference] = required_bytes
        checks.append({"check_id": "required-ci", "status": "PASS",
                       "evidence_sha256": hashlib.sha256(required_bytes).hexdigest(),
                       "evidence_reference": required_reference})
    else:
        job = job_observations.get("parent-acceptance")
        if job is None:
            raise IntegrationError("parent Acceptance job provenance is missing")
        checks = []
        artifacts = {}
        for check_id, step_name in PARENT_ACCEPTANCE_STEPS.items():
            matches = [step for step in job["steps"] if step.get("name") == step_name]
            if (len(matches) != 1 or matches[0].get("status") != "completed"
                    or matches[0].get("conclusion") != "success"):
                raise IntegrationError(f"exact-main acceptance step did not pass: {step_name}")
            reference = f"actions/{check_id}.json"
            artifact = _canonical({"check_id": check_id, "job": job["name"],
                                   "main_sha40": main_sha40, "run_id": run_id,
                                   "step": matches[0]}) + b"\n"
            artifacts[reference] = artifact
            checks.append({"check_id": check_id, "status": "PASS",
                           "evidence_sha256": hashlib.sha256(artifact).hexdigest(),
                           "evidence_reference": reference})

    source = {
        "schema": "PASES_PARENT_INTEGRATION_CHECKS_V2",
        "kind": kind,
        "status": "PASS",
        "repository": repository,
        "parent_issue_number": 26,
        "parent_adc_sha256": parent_adc_sha256,
        "main_sha40": main_sha40,
        "workflow_run": {"id": run_id, "attempt": run["run_attempt"], "path": workflow_path,
                          "event": event, "head_branch": "main", "head_sha40": main_sha40,
                          "status": "completed", "conclusion": "success"},
        "checks": sorted(checks, key=lambda row: row["check_id"]),
    }
    result_bytes = _canonical(source) + b"\n"
    bundle = ParentGateEvidenceComment(
        kind, repository, 26, parent_adc_sha256, main_sha40, run_id,
        run["run_attempt"], workflow_path, result_bytes,
        tuple((name, artifacts[name]) for name in sorted(artifacts)),
    ).validate()
    _validate_parent_gate_bundle(bundle, kind, repository, parent_adc_sha256, main_sha40)
    return bundle


def _validate_parent_gate_bundle(
    bundle: ParentGateEvidenceComment, kind: str, repository: str,
    parent_adc_sha256: str, main_sha40: str,
) -> dict[str, Any]:
    """Check canonical PASS result bytes and exact cited artifact bytes inside a comment."""
    bundle.validate()
    try:
        source_value = json.loads(bundle.result_bytes.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"parent Integration {kind} result bytes are invalid JSON") from exc
    required_source = {"schema", "kind", "status", "repository", "parent_issue_number",
                       "parent_adc_sha256", "main_sha40", "workflow_run", "checks"}
    source_repository = source_value.get("repository") if isinstance(source_value, dict) else None
    if (not isinstance(source_value, dict) or set(source_value) != required_source
            or source_value.get("schema") != "PASES_PARENT_INTEGRATION_CHECKS_V2"
            or source_value.get("kind") != kind or source_value.get("status") != "PASS"
            or not isinstance(source_repository, str)
            or source_repository.casefold() != repository.casefold()
            or type(source_value.get("parent_issue_number")) is not int
            or source_value.get("parent_issue_number") != 26
            or source_value.get("parent_adc_sha256") != parent_adc_sha256
            or source_value.get("main_sha40") != main_sha40
            or source_value.get("workflow_run") != {
                "id": bundle.workflow_run_id, "attempt": bundle.workflow_run_attempt,
                "path": bundle.workflow_path,
                "event": "push" if kind == "verification" else "workflow_dispatch",
                "head_branch": "main", "head_sha40": main_sha40,
                "status": "completed", "conclusion": "success",
            }
            or bundle.kind != kind or bundle.parent_issue_number != 26
            or bundle.parent_adc_sha256 != parent_adc_sha256 or bundle.main_sha40 != main_sha40
            or bundle.repository.casefold() != repository.casefold()
            or bundle.result_bytes != _canonical(source_value) + b"\n"):
        raise IntegrationError(f"parent Integration {kind} source has no matching typed PASS subject")
    checks = source_value["checks"]
    if not isinstance(checks, list) or any(not isinstance(row, dict) or set(row) != {
            "check_id", "status", "evidence_sha256", "evidence_reference"} for row in checks):
        raise IntegrationError(f"parent Integration {kind} source check list is malformed")
    artifacts = dict(bundle.artifacts)
    by_id: dict[str, dict[str, Any]] = {}
    expected_artifacts: set[str] = set()
    for row in checks:
        check_id = row["check_id"]
        if (not isinstance(check_id, str) or not check_id or check_id in by_id
                or row["status"] != "PASS" or not isinstance(row["evidence_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["evidence_sha256"])):
            raise IntegrationError(f"parent Integration {kind} source contains a failing or duplicate check")
        try:
            evidence_reference = _repository_file_reference(row["evidence_reference"])
            evidence_bytes = artifacts[evidence_reference]
        except (IntegrationError, KeyError) as exc:
            raise IntegrationError(f"parent Integration {kind} check artifact bytes are missing from its comment") from exc
        if hashlib.sha256(evidence_bytes).hexdigest() != row["evidence_sha256"]:
            raise IntegrationError(f"parent Integration {kind} check evidence digest does not match comment bytes")
        expected_artifacts.add(evidence_reference)
        by_id[check_id] = row
    if set(artifacts) != expected_artifacts:
        raise IntegrationError(f"parent Integration {kind} comment has missing or unreferenced artifact bytes")
    required = ({"compileall", "committed-distributions", "unit-tests", "docs-validation",
                 "distribution-build", "generated-distributions", "distribution-validation",
                 "generated-paths", "format-check", "required-ci"}
                if kind == "verification" else
                {"specification-traceability", "design-traceability", "test-oracle-traceability",
                 "16-skills-package", "generated-distributions", "distribution-validation"})
    if set(by_id) != required:
        raise IntegrationError(f"parent Integration {kind} evidence does not cover the fixed required check set")
    return source_value


