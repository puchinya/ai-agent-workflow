"""Repository-scoped Consumer Activation setup and append-only history."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adc import ADCError, VerifiedADC, publish_adc, verify_adc, verify_adc_generation
from .github import GitHub, GitHubError
from .git import (
    GitError, activation_profile_bytes_at_commit, branch_exists, changed_paths_between,
    commit_and_push_one_path, commit_parent_sha40, create_branch, current_branch, discover_repository,
    fetch_remote_branch_exact, head_sha40, push_branch_exact, remote_branch_exists, remote_branch_sha,
    switch_branch, worktree_clean,
)
from .path_safety import path_has_symlink
from .profile import ProfileError, load_profile


class ConsumerActivationError(ValueError):
    pass


ISSUE_MARKER = "<!-- PASES_CONSUMER_ACTIVATION_ISSUE_V1 -->"
SETUP_MARKER = "<!-- PASES_CONSUMER_ACTIVATION_SETUP_V1\n"
APPROVAL_MARKER = "<!-- PASES_CONSUMER_ACTIVATION_APPROVAL_V1\n"
RECORD_MARKER = "<!-- PASES_CONSUMER_ACTIVATION_V1\n"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ConsumerActivationError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConsumerActivationError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
        raise ConsumerActivationError(f"{label} is not a valid past timestamp")
    return parsed


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ConsumerActivationError(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConsumerActivationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ConsumerActivationError(f"{label} must be a JSON object")
    return value


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ConsumerActivationError(f"{label} must be a positive integer")
    return value


def _body(marker: str, payload: dict[str, Any]) -> str:
    return f"{marker}{_canonical(payload).decode('utf-8')}\n-->"


def _decode(body: Any, marker: str, label: str, *, allow_trailer: bool = False) -> dict[str, Any]:
    if not isinstance(body, str) or not body.startswith(marker):
        raise ConsumerActivationError(f"{label} has an invalid schema marker")
    end = body.find("\n-->", len(marker))
    if end < 0 or (not allow_trailer and end + 4 != len(body)):
        raise ConsumerActivationError(f"{label} has an incomplete or non-canonical envelope")
    value = _json_object(body[len(marker):end].encode("utf-8"), label)
    if _body(marker, value) != body[:end + 4]:
        raise ConsumerActivationError(f"{label} JSON is not canonical")
    return value


def _identity(user: Any, label: str) -> tuple[int, str, str]:
    if (not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] < 1
            or not isinstance(user.get("login"), str) or not user["login"]
            or user.get("type") != "User"):
        raise ConsumerActivationError(f"{label} is not a stable human GitHub identity")
    return user["id"], user["login"].casefold(), "User"


def activation_profile(issue_number: int) -> dict[str, int]:
    return {"issue_number": _positive(issue_number, "Activation Issue number")}


def _has_issue_marker(body: Any) -> bool:
    return isinstance(body, str) and body.splitlines()[:1] == [ISSUE_MARKER]


def _profile_digest(issue_number: int) -> str:
    return hashlib.sha256(_canonical(activation_profile(issue_number))).hexdigest()


def _default_profile(repository: str) -> dict[str, Any]:
    return {
        "schema_version": 2, "initialized": True, "project_name": repository.split("/", 1)[1],
        "components": [],
        "branch": {"prefix": "feature", "max_slug_length": 48,
                   "cleanup_on_switch": [], "required_checks": []},
        "workspace": {"isolation": "auto"},
        "milestones": {"mode": "optional", "version_source": None},
        "hooks": {"branch_switch": [], "verify_quick": [], "verify_final": []},
    }


def _profile_for_setup(root: Path, repository: str, issue_number: int) -> tuple[dict[str, Any], bytes]:
    path = root / ".agent" / "project.json"
    if path_has_symlink(path, root=root):
        raise ConsumerActivationError("project.json path traverses a symbolic link")
    original = path.read_bytes() if path.is_file() else None
    if original is not None:
        try:
            value = _json_object(original, "project.json")
            load_profile(root)
        except (OSError, ProfileError, ConsumerActivationError) as exc:
            raise ConsumerActivationError(f"existing project.json is invalid: {exc}") from exc
    else:
        value = _default_profile(repository)
    current = value.get("activation")
    if current is not None:
        if not isinstance(current, dict) or set(current) != {"issue_number"}:
            raise ConsumerActivationError("project.json activation setting is malformed")
        if _positive(current.get("issue_number"), "Activation Issue number") != issue_number:
            raise ConsumerActivationError("project.json already points to a different Activation Issue")
    value["activation"] = activation_profile(issue_number)
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if original == content:
        # A successor policy still needs a reviewable setup commit. Reordering JSON keys
        # changes only presentation; the parsed profile and canonical Activation object stay exact.
        keys = list(value)
        if len(keys) > 1:
            rotated = keys[1:] + keys[:1]
            content = (json.dumps({key: value[key] for key in rotated}, ensure_ascii=False,
                                  sort_keys=False, indent=2) + "\n").encode("utf-8")
    return value, content


def _write_profile(root: Path, content: bytes) -> None:
    directory = root / ".agent"
    if path_has_symlink(directory, root=root):
        raise ConsumerActivationError(".agent path traverses a symbolic link")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "project.json"
    if path_has_symlink(target, root=root):
        raise ConsumerActivationError("project.json path traverses a symbolic link")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".project.json.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ConsumerActivationError("could not atomically write project.json") from exc


def _default_activation_adc(repository: str, issue_number: int) -> bytes:
    text = f"""# Agent Development Contract — consumer-p-ases-activation
Repository: {repository}
Issue: {issue_number}

## Issue
Define the default P-ASES Activation policy for this consumer repository.

## Scope
Authorize the normal P-ASES gate only for same-repository Issues created after verified Activation. Preserve existing Issue routing and Gate Selections.

## Change Kind
Policy definition for the consumer repository's P-ASES Activation.

## Requirements
- REQ-01: Only a non-pull-request Issue in this repository whose GitHub creation time is later than the verified Activation time may select the normal P-ASES gate.
- REQ-02: Existing or pre-Activation Issues keep their existing gate state and are never silently relabeled or migrated.
- REQ-03: Every Gate Selection stays bound to the exact Activation record that authorized it.

## Architecture Decisions
The approved ADC on this Issue is the policy authority. The project profile stores only this Issue number as a locator; verified Activation history is the evidence of authorization.

## Artifact Impact
Specification: No consumer product specification changes; this ADC defines repository workflow policy.
Design: No consumer product design changes; this ADC defines repository workflow policy.
Testing: Verify Activation timing, immutable Gate Selection, and preservation of existing Issue routing.

## Exact Changes
Use the repository's normal P-ASES gate for eligible Issues after verified Activation.

## Invariants
The repository, Activation Issue, approved ADC generation, human administrator, and Activation history must match exactly. Missing, ambiguous, edited, stale, or unauthorized evidence blocks.

## Non-goals
Do not migrate existing Issues, change their labels, or alter the separate P-ASES migration Bootstrap history.

## Verification Obligations
Check the exact Activation Issue and ADC, human admin permission, setup PR merge, required checks, default-branch ancestry, and immutable per-Issue Gate Selection.

## Reviewer Checklist
- [ ] Only later same-repository non-PR Issues can select the P-ASES gate.
- [ ] Existing Issues and Gate Selections remain unchanged.
- [ ] Activation history is complete, immutable, and authorized.

## Completion Gates
Activate only after the exact setup PR is merged by a verified repository administrator and all Activation evidence passes readback.
"""
    from .adc import parse_adc
    data = text.encode("utf-8")
    parse_adc(data, repository, issue_number)
    return data


def _fingerprint(row: Any, issue_number: int, comment_id: int, marker: str,
                 label: str) -> tuple[Any, ...]:
    if (not isinstance(row, dict) or row.get("id") != comment_id
            or not isinstance(row.get("body"), str) or not row["body"].startswith(marker)):
        raise ConsumerActivationError(f"{label} comment identity or schema is invalid")
    created, updated = row.get("created_at"), row.get("updated_at")
    if not isinstance(created, str) or created != updated:
        raise ConsumerActivationError(f"{label} comment was edited or has invalid timestamps")
    identity = _identity(row.get("user"), f"{label} author")
    return (comment_id, row["body"], created, updated, identity,
            row.get("issue_url"), row.get("html_url"), row.get("url"))


def _read_comment(github: GitHub, issue_number: int, comment_id: int, marker: str,
                  label: str, *, unique_marker: bool = True) -> dict[str, Any]:
    try:
        direct = github.issue_comment(issue_number, comment_id)
        listed = github.issue_comments(issue_number)
        matches = [row for row in listed if isinstance(row, dict) and row.get("id") == comment_id]
        marked = [row for row in listed if isinstance(row, dict) and isinstance(row.get("body"), str)
                  and row["body"].startswith(marker)]
        if (len(matches) != 1 or not any(row.get("id") == comment_id for row in marked)
                or (unique_marker and len(marked) != 1)):
            raise ConsumerActivationError(f"{label} is missing, duplicated, or ambiguous")
        after = github.issue_comment(issue_number, comment_id)
    except GitHubError as exc:
        raise ConsumerActivationError(f"{label} readback failed: {exc}") from exc
    fingerprints = [_fingerprint(row, issue_number, comment_id, marker, label)
                    for row in (direct, matches[0], after)]
    if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
        raise ConsumerActivationError(f"{label} changed during direct/list/direct readback")
    repository = github.repo
    expected_urls = (f"https://api.github.com/repos/{repository}/issues/{issue_number}",
                     f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}",
                     f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}")
    actual_urls = tuple(value.casefold() if isinstance(value, str) else None
                        for value in fingerprints[1][5:])
    if actual_urls != tuple(value.casefold() for value in expected_urls):
        raise ConsumerActivationError(f"{label} URLs do not identify the exact Issue and comment")
    return matches[0]


def _publish_comment(github: GitHub, issue_number: int, marker: str, payload: dict[str, Any],
                     label: str, *, allow_history: bool = False) -> tuple[int, str]:
    body = _body(marker, payload)
    try:
        comments = github.issue_comments(issue_number)
        matches = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                   and row["body"].startswith(marker)]
        exact = [row for row in matches if row.get("body") == body]
        if len(matches) > 1 and not allow_history:
            raise ConsumerActivationError(f"multiple {label} comments exist")
        if len(exact) > 1:
            raise ConsumerActivationError(f"duplicate exact {label} comments exist")
        if exact:
            comment_id = _positive(exact[0].get("id"), f"{label} Comment ID")
        else:
            created = github.create_issue_comment(issue_number, body)
            comment_id = _positive(created.get("id") if isinstance(created, dict) else None,
                                   f"created {label} Comment ID")
        row = _read_comment(github, issue_number, comment_id, marker, label,
                            unique_marker=not allow_history)
    except GitHubError as exc:
        raise ConsumerActivationError(f"{label} publication failed: {exc}") from exc
    if row.get("body") != body:
        raise ConsumerActivationError(f"{label} exact-body readback failed")
    return comment_id, body


def _resolve_issue(github: GitHub, configured: int | None) -> dict[str, Any] | None:
    try:
        issues = github.issues()
    except GitHubError as exc:
        raise ConsumerActivationError(f"Activation Issue lookup failed: {exc}") from exc
    marked = [row for row in issues if isinstance(row, dict) and row.get("pull_request") is None
              and _has_issue_marker(row.get("body"))]
    if any(type(row.get("number")) is not int or row["number"] < 1 for row in marked):
        raise ConsumerActivationError("marked Activation Issue has an invalid number")
    if len(marked) > 1:
        raise ConsumerActivationError("multiple marked Activation Issues exist")
    if configured is not None:
        matches = [row for row in marked if row.get("number") == configured]
        if len(matches) != 1:
            raise ConsumerActivationError("configured Activation Issue does not uniquely match its marker")
        selected = matches[0]
    else:
        selected = marked[0] if marked else None
    def signature(rows: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
        values = [(row.get("number"), row.get("state"), row.get("repository_url"), row.get("body"))
                  for row in rows]
        return tuple(sorted(values, key=lambda row: row[0]))

    if selected is None:
        try:
            after_marked = [row for row in github.issues() if isinstance(row, dict)
                            and row.get("pull_request") is None and _has_issue_marker(row.get("body"))]
        except GitHubError as exc:
            raise ConsumerActivationError(f"Activation Issue lookup readback failed: {exc}") from exc
        if (any(type(row.get("number")) is not int or row["number"] < 1 for row in after_marked)
                or signature(marked) != signature(after_marked)):
            raise ConsumerActivationError("Activation Issue marker set changed during readback")
        return None

    repo_url = selected.get("repository_url")
    if (selected.get("state") != "open" or not isinstance(repo_url, str)
            or repo_url.casefold() != f"https://api.github.com/repos/{github.repo}".casefold()):
        raise ConsumerActivationError("marked Activation Issue has invalid repository, number, or state")
    try:
        direct = github.issue(selected["number"])
        after_marked = [row for row in github.issues() if isinstance(row, dict)
                        and row.get("pull_request") is None and _has_issue_marker(row.get("body"))]
    except GitHubError as exc:
        raise ConsumerActivationError(f"Activation Issue direct readback failed: {exc}") from exc
    if (any(type(row.get("number")) is not int or row["number"] < 1 for row in after_marked)
            or signature(marked) != signature(after_marked)):
        raise ConsumerActivationError("Activation Issue marker set changed during readback")
    if (not isinstance(direct, dict) or direct.get("number") != selected["number"]
            or direct.get("state") != selected.get("state")
            or direct.get("pull_request") is not None
            or direct.get("repository_url") != selected.get("repository_url")
            or direct.get("body") != selected.get("body")
            or not _has_issue_marker(direct.get("body"))):
        raise ConsumerActivationError("Activation Issue changed during list/direct/list readback")
    return direct


def _ensure_adc(github: GitHub, issue_number: int) -> VerifiedADC:
    try:
        return verify_adc(github, issue_number)
    except ADCError as exc:
        if "Issue has no Agent Development Contract pointer" not in str(exc):
            raise ConsumerActivationError(f"Activation Issue ADC is invalid: {exc}") from exc
    data = _default_activation_adc(github.repo, issue_number)
    try:
        pointer = publish_adc(github, issue_number, data, state="draft")
        verified = verify_adc(github, issue_number)
    except ADCError as exc:
        raise ConsumerActivationError(f"proposed default Activation ADC could not be published: {exc}") from exc
    if verified.pointer != pointer or verified.contract.content != data:
        raise ConsumerActivationError("proposed default Activation ADC did not pass exact readback")
    return verified


def _setup_payload(issue_number: int, adc: VerifiedADC, predecessor_record_id: int | None) -> dict[str, Any]:
    if adc.pointer.state not in {"draft", "approved"}:
        raise ConsumerActivationError("Activation ADC pointer state is invalid")
    return {"activation_issue_number": issue_number,
            "activation_profile_sha256": _profile_digest(issue_number),
            "adc_comment_id": adc.pointer.comment_id, "adc_sha256": adc.pointer.sha256,
            "adc_state": adc.pointer.state, "predecessor_record_id": predecessor_record_id,
            "schema": "PASES_CONSUMER_ACTIVATION_SETUP_V1"}


def _setup_branch(issue_number: int, adc_sha256: str, predecessor_record_id: int | None) -> str:
    predecessor = "initial" if predecessor_record_id is None else str(predecessor_record_id)
    return f"pases/consumer-activation-{issue_number}-{adc_sha256[:8]}-{predecessor}"


def _repositories_match(base: Any, head: Any, repository: str, *, expected_id: int | None = None) -> bool:
    if not isinstance(base, dict) or not isinstance(head, dict):
        return False
    base_name, head_name = base.get("full_name"), head.get("full_name")
    base_id, head_id = base.get("id"), head.get("id")
    if (not isinstance(base_name, str) or not isinstance(head_name, str)
            or base_name.casefold() != repository.casefold()
            or head_name.casefold() != repository.casefold()
            or type(base_id) is not int or base_id < 1 or base_id != head_id):
        return False
    return expected_id is None or base_id == expected_id


def _check_setup_pr(github: GitHub, pr: dict[str, Any], expected: dict[str, Any],
                    default_branch: str, repository_id: int) -> dict[str, Any]:
    base, head = pr.get("base"), pr.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    payload = _decode(pr.get("body"), SETUP_MARKER, "setup PR", allow_trailer=True)
    if (pr.get("state") != "open" or pr.get("merged") is True or pr.get("draft") is not False
            or payload != expected or not isinstance(base, dict) or base.get("ref") != default_branch
            or not isinstance(head, dict) or head.get("ref") != _setup_branch(
                expected["activation_issue_number"], expected["adc_sha256"],
                expected["predecessor_record_id"])
            or not _repositories_match(base_repo, head_repo, github.repo, expected_id=repository_id)):
        raise ConsumerActivationError("existing setup PR is closed, forked, draft, or mismatched")
    files = github.pull_request_files(_positive(pr.get("number"), "setup PR number"))
    if len(files) != 1 or files[0].get("filename") != ".agent/project.json":
        raise ConsumerActivationError("setup PR must change exactly .agent/project.json")
    return pr


def _validate_profile_bytes(raw: bytes, issue_number: int) -> tuple[dict[str, Any], tuple[tuple[str, int], ...]]:
    profile = _json_object(raw, "merged project.json")
    try:
        with tempfile.TemporaryDirectory(prefix="pases-profile-check-") as tmp:
            path = Path(tmp) / ".agent" / "project.json"
            path.parent.mkdir()
            path.write_bytes(raw)
            parsed = load_profile(Path(tmp))
    except (OSError, ProfileError) as exc:
        raise ConsumerActivationError(f"merged project.json is invalid: {exc}") from exc
    activation = profile.get("activation")
    if not isinstance(activation, dict) or activation != activation_profile(issue_number):
        raise ConsumerActivationError("merged project.json does not contain the exact Activation Issue locator")
    checks = parsed.required_checks
    if not checks or any(app_id is None for _name, app_id in checks):
        raise ConsumerActivationError("merged project.json must configure trusted Required Checks")
    return profile, tuple((name, app_id) for name, app_id in checks if app_id is not None)


def _check_run_with_creation_time(github: GitHub, row: dict[str, Any]) -> dict[str, Any]:
    """Use the linked Actions Job timestamp when GitHub omits Check Run created_at."""
    if row.get("created_at") is not None:
        return row
    try:
        job = github.workflow_job_for_check_run(row)
    except GitHubError as exc:
        raise ConsumerActivationError("Required Check creation time could not be verified") from exc
    created_at = job.get("created_at") if isinstance(job, dict) else None
    if not isinstance(created_at, str):
        raise ConsumerActivationError("Required Check creation time could not be verified")
    return {**row, "created_at": created_at}


def _required_check_evidence(
    github: GitHub, head_sha40: str, checks: tuple[tuple[str, int], ...],
    expected: tuple[RequiredCheckEvidence, ...] | None, merged_at: str,
) -> tuple[RequiredCheckEvidence, ...]:
    merge_time = _timestamp(merged_at, "setup PR merge time")
    if expected is not None:
        if tuple((item.name, item.app_id) for item in expected) != checks:
            raise ConsumerActivationError("pinned Required Check identities do not match the merged project profile")
        evidence: list[RequiredCheckEvidence] = []
        for pinned in expected:
            current_row = _check_run_with_creation_time(github, github.check_run(pinned.check_run_id))
            current = RequiredCheckEvidence.from_run(current_row)
            if (current != pinned or current.head_sha40 != head_sha40
                    or _timestamp(current.completed_at, f"Required Check {current.name} completion time") > merge_time):
                raise ConsumerActivationError(
                    f"pinned Required Check {pinned.name} no longer matches its successful pre-merge Check Run"
                )
            evidence.append(current)
        return tuple(evidence)

    runs = github.check_runs_for_ref(head_sha40)
    evidence = []
    for name, app_id in checks:
        matching = [row for row in runs if row.get("name") == name and row.get("head_sha") == head_sha40
                    and isinstance(row.get("app"), dict) and row["app"].get("id") == app_id]
        if not matching:
            raise ConsumerActivationError(f"Required Check {name} did not pass: no trusted Check Run on PR HEAD")
        dated: list[tuple[datetime, int, dict[str, Any]]] = []
        seen_ids: set[int] = set()
        for row in matching:
            resolved = _check_run_with_creation_time(github, row)
            created = _timestamp(resolved.get("created_at"), f"Required Check {name} creation time")
            run_id = _positive(row.get("id"), f"Required Check {name} Run ID")
            if run_id in seen_ids:
                raise ConsumerActivationError(f"Required Check {name} has duplicate Check Run IDs")
            seen_ids.add(run_id)
            if created <= merge_time:
                dated.append((created, run_id, resolved))
        if not dated:
            raise ConsumerActivationError(f"Required Check {name} did not exist by setup PR merge")
        # GitHub timestamps can tie across reruns; the numeric Run ID gives a
        # stable order independent of API response ordering.
        _created, _run_id, latest = max(dated, key=lambda item: (item[0], item[1]))
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ConsumerActivationError(f"Required Check {name} latest Check Run at merge did not pass")
        selected = RequiredCheckEvidence.from_run(latest)
        if (_timestamp(selected.completed_at, f"Required Check {name} completion time") > merge_time):
            raise ConsumerActivationError(f"Required Check {name} completed after setup PR merge")
        if selected.head_sha40 != head_sha40:
            raise ConsumerActivationError(f"Required Check {name} belongs to a different PR HEAD")
        evidence.append(selected)
    return tuple(evidence)


def _validate_merged_setup(github: GitHub, pr_number: int, expected: dict[str, Any], *,
                           require_current_adc: bool, require_current_admin: bool,
                           expected_check_runs: tuple[RequiredCheckEvidence, ...] | None = None
                           ) -> tuple[dict[str, Any], dict[str, Any], VerifiedADC,
                                      tuple[RequiredCheckEvidence, ...]]:
    try:
        pr = github.pull_request(pr_number)
        metadata = github.repository_metadata()
        default_branch = metadata.get("default_branch")
        repository_id = metadata.get("id")
        base, head = pr.get("base"), pr.get("head")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        head_repo = head.get("repo") if isinstance(head, dict) else None
        merger = pr.get("merged_by")
        merge_sha, merged_at = pr.get("merge_commit_sha"), pr.get("merged_at")
        if (pr.get("state") != "closed" or pr.get("merged") is not True or pr.get("draft") is not False
                or _decode(pr.get("body"), SETUP_MARKER, "setup PR", allow_trailer=True) != expected
                or not isinstance(default_branch, str) or not isinstance(base, dict)
                or base.get("ref") != default_branch or not isinstance(head, dict)
                or type(repository_id) is not int or repository_id < 1
                or not _repositories_match(base_repo, head_repo, github.repo, expected_id=repository_id)
                or not isinstance(head.get("sha"), str) or not SHA40.fullmatch(head["sha"])
                or not isinstance(merge_sha, str) or not SHA40.fullmatch(merge_sha)
                or not isinstance(merged_at, str)):
            raise ConsumerActivationError("merged setup PR identity is incomplete or mismatched")
        merger_identity = _identity(merger, "setup PR merger")
        if require_current_admin:
            permission = github.collaborator_permission(merger["login"])
            if (permission.get("permission") != "admin"
                    or _identity(permission.get("user"), "setup PR merger") != merger_identity):
                raise ConsumerActivationError("setup PR must be merged by a current repository admin")
        current_default_sha = github.branch(default_branch).get("commit", {}).get("sha")
        if (not isinstance(current_default_sha, str) or not SHA40.fullmatch(current_default_sha)
                or github.compare_commits(merge_sha, current_default_sha).get("status") not in {"ahead", "identical"}):
            raise ConsumerActivationError("setup PR merge commit is not on the current default branch")
        files = github.pull_request_files(pr_number)
        if len(files) != 1 or files[0].get("filename") != ".agent/project.json":
            raise ConsumerActivationError("setup PR must change exactly .agent/project.json")
        raw_profile = github.regular_content_at_ref(".agent/project.json", merge_sha)
        _profile, checks = _validate_profile_bytes(raw_profile, expected["activation_issue_number"])
        if hashlib.sha256(_canonical(activation_profile(expected["activation_issue_number"]))).hexdigest() != expected["activation_profile_sha256"]:
            raise ConsumerActivationError("setup PR Activation profile digest is invalid")
        check_evidence = _required_check_evidence(
            github, head["sha"], checks, expected_check_runs, merged_at,
        )
        issue_number = expected["activation_issue_number"]
        issue = github.issue(issue_number)
        issue_repository_url = issue.get("repository_url")
        if (issue.get("number") != issue_number or issue.get("pull_request") is not None
                or not _has_issue_marker(issue.get("body"))
                or not isinstance(issue_repository_url, str)
                or issue_repository_url.casefold() != f"https://api.github.com/repos/{github.repo}".casefold()):
            raise ConsumerActivationError("Activation Issue marker or repository identity is invalid")
    except GitHubError as exc:
        raise ConsumerActivationError(f"merged setup PR evidence readback failed: {exc}") from exc
    try:
        proposed = verify_adc_generation(
            github, expected["activation_issue_number"], expected["adc_comment_id"],
            expected["adc_sha256"], state=expected["adc_state"],
        )
        if require_current_adc:
            latest = verify_adc(github, expected["activation_issue_number"])
            same_content = (latest.pointer.sha256 == proposed.pointer.sha256
                           and latest.contract.content == proposed.contract.content)
            exact_proposal = latest.pointer == proposed.pointer
            promoted = (expected["adc_state"] == "draft" and latest.pointer.state == "approved"
                        and same_content)
            if not exact_proposal and not promoted:
                raise ConsumerActivationError("setup PR refers to a stale or superseded Activation ADC")
    except ADCError as exc:
        raise ConsumerActivationError(f"Activation ADC is missing, changed, or not journaled: {exc}") from exc
    return pr, issue, proposed, check_evidence


@dataclass(frozen=True)
class RequiredCheckEvidence:
    check_run_id: int
    name: str
    app_id: int
    head_sha40: str
    created_at: str
    started_at: str
    completed_at: str
    status: str
    conclusion: str

    def validate(self) -> "RequiredCheckEvidence":
        _positive(self.check_run_id, "Required Check Run ID")
        _positive(self.app_id, "Required Check App ID")
        if (not isinstance(self.name, str) or not self.name
                or not isinstance(self.head_sha40, str) or not SHA40.fullmatch(self.head_sha40)
                or self.status != "completed" or self.conclusion != "success"):
            raise ConsumerActivationError("Required Check evidence is not a successful trusted Check Run")
        created = _timestamp(self.created_at, "Check Run creation time")
        started = _timestamp(self.started_at, "Check Run start time")
        completed = _timestamp(self.completed_at, "Check Run completion time")
        if not created <= started <= completed:
            raise ConsumerActivationError("Required Check Run timestamps are out of order")
        return self

    @classmethod
    def from_run(cls, value: Any) -> "RequiredCheckEvidence":
        app = value.get("app") if isinstance(value, dict) else None
        if not isinstance(value, dict) or not isinstance(app, dict):
            raise ConsumerActivationError("Required Check API response is malformed")
        return cls(value.get("id"), value.get("name"), app.get("id"), value.get("head_sha"),
                   value.get("created_at"), value.get("started_at"), value.get("completed_at"),
                   value.get("status"), value.get("conclusion")).validate()

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "app_id": self.app_id, "check_run_id": self.check_run_id,
            "completed_at": self.completed_at, "conclusion": self.conclusion,
            "created_at": self.created_at, "head_sha40": self.head_sha40,
            "name": self.name, "started_at": self.started_at, "status": self.status,
        }

    @classmethod
    def from_payload(cls, value: Any) -> "RequiredCheckEvidence":
        expected = {"app_id", "check_run_id", "completed_at", "conclusion", "created_at",
                    "head_sha40", "name", "started_at", "status"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ConsumerActivationError("Required Check evidence has unknown schema or fields")
        return cls(value["check_run_id"], value["name"], value["app_id"], value["head_sha40"],
                   value["created_at"], value["started_at"], value["completed_at"],
                   value["status"], value["conclusion"]).validate()


@dataclass(frozen=True)
class ConsumerActivationRecord:
    repository: str
    activation_issue_number: int
    proposed_adc_comment_id: int
    proposed_adc_sha256: str
    proposed_adc_state: str
    adc_comment_id: int
    adc_sha256: str
    activation_profile_sha256: str
    setup_pr_number: int
    setup_pr_id: int
    merge_commit_sha40: str
    merged_at: str
    merger_id: int
    merger_login: str
    merger_type: str
    approval_comment_id: int
    predecessor_record_id: int | None
    required_check_runs: tuple["RequiredCheckEvidence", ...]
    record_created_at: str | None = None

    def validate(self) -> "ConsumerActivationRecord":
        if not isinstance(self.repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise ConsumerActivationError("Activation repository is invalid")
        for value, label in ((self.activation_issue_number, "Activation Issue"),
                             (self.proposed_adc_comment_id, "proposed ADC comment"),
                             (self.adc_comment_id, "approved ADC comment"),
                             (self.setup_pr_number, "setup PR"), (self.setup_pr_id, "setup PR ID"),
                             (self.merger_id, "PR merger"), (self.approval_comment_id, "approval comment")):
            _positive(value, label)
        for digest, label in ((self.proposed_adc_sha256, "proposed ADC"),
                              (self.adc_sha256, "approved ADC"),
                              (self.activation_profile_sha256, "Activation profile")):
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise ConsumerActivationError(f"{label} digest is invalid")
        if self.proposed_adc_sha256 != self.adc_sha256 or self.proposed_adc_state not in {"draft", "approved"}:
            raise ConsumerActivationError("proposed and approved Activation ADC do not match")
        if not isinstance(self.merge_commit_sha40, str) or not SHA40.fullmatch(self.merge_commit_sha40):
            raise ConsumerActivationError("Activation merge SHA is invalid")
        if (not isinstance(self.merger_login, str) or not re.fullmatch(r"[A-Za-z0-9-]+", self.merger_login)
                or self.merger_type != "User"):
            raise ConsumerActivationError("Activation merger identity is invalid")
        merged = _timestamp(self.merged_at, "setup PR merge time")
        if self.record_created_at is not None:
            if _timestamp(self.record_created_at, "Activation comment creation time") < merged:
                raise ConsumerActivationError("Activation record was created before its setup PR merge")
        if self.predecessor_record_id is not None:
            _positive(self.predecessor_record_id, "predecessor Activation record")
        if (not isinstance(self.required_check_runs, tuple) or not self.required_check_runs
                or any(not isinstance(item, RequiredCheckEvidence) for item in self.required_check_runs)
                or len({item.name for item in self.required_check_runs}) != len(self.required_check_runs)):
            raise ConsumerActivationError("Activation required-check evidence is missing, duplicate, or malformed")
        for item in self.required_check_runs:
            item.validate()
            if _timestamp(item.completed_at, f"Required Check {item.name} completion time") > merged:
                raise ConsumerActivationError(
                    f"Required Check {item.name} completed after the setup PR merge"
                )
        return self

    @property
    def activated_at(self) -> str:
        self.validate()
        return self.merged_at

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "activation_issue_number": self.activation_issue_number,
            "activation_profile_sha256": self.activation_profile_sha256,
            "adc_comment_id": self.adc_comment_id, "adc_sha256": self.adc_sha256,
            "approval_comment_id": self.approval_comment_id,
            "merge_commit_sha40": self.merge_commit_sha40, "merged_at": self.merged_at,
            "merger_id": self.merger_id, "merger_login": self.merger_login,
            "merger_type": self.merger_type,
            "predecessor_record_id": self.predecessor_record_id,
            "proposed_adc_comment_id": self.proposed_adc_comment_id,
            "proposed_adc_sha256": self.proposed_adc_sha256,
            "proposed_adc_state": self.proposed_adc_state,
            "required_check_runs": [item.payload() for item in self.required_check_runs],
            "repository": self.repository, "setup_pr_id": self.setup_pr_id,
            "setup_pr_number": self.setup_pr_number,
            "schema": "PASES_CONSUMER_ACTIVATION_V1",
        }

    @classmethod
    def from_payload(cls, value: Any) -> "ConsumerActivationRecord":
        expected = {"activation_issue_number", "activation_profile_sha256", "adc_comment_id", "adc_sha256",
                    "approval_comment_id", "merge_commit_sha40", "merged_at", "merger_id", "merger_login",
                    "merger_type", "predecessor_record_id", "proposed_adc_comment_id", "proposed_adc_sha256",
                    "proposed_adc_state", "required_check_runs", "repository", "setup_pr_id",
                    "setup_pr_number", "schema"}
        if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_CONSUMER_ACTIVATION_V1":
            raise ConsumerActivationError("Activation record has unknown schema or fields")
        if not isinstance(value["required_check_runs"], list):
            raise ConsumerActivationError("Activation required-check evidence must be a list")
        return cls(
            repository=value["repository"], activation_issue_number=value["activation_issue_number"],
            proposed_adc_comment_id=value["proposed_adc_comment_id"],
            proposed_adc_sha256=value["proposed_adc_sha256"], proposed_adc_state=value["proposed_adc_state"],
            adc_comment_id=value["adc_comment_id"], adc_sha256=value["adc_sha256"],
            activation_profile_sha256=value["activation_profile_sha256"],
            setup_pr_number=value["setup_pr_number"], setup_pr_id=value["setup_pr_id"],
            merge_commit_sha40=value["merge_commit_sha40"], merged_at=value["merged_at"],
            merger_id=value["merger_id"], merger_login=value["merger_login"],
            merger_type=value["merger_type"], approval_comment_id=value["approval_comment_id"],
            predecessor_record_id=value["predecessor_record_id"],
            required_check_runs=tuple(RequiredCheckEvidence.from_payload(row)
                                      for row in value["required_check_runs"]),
        ).validate()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()


def _approval_payload(record_fields: dict[str, Any], *, predecessor: int | None) -> dict[str, Any]:
    return {
        "activation_issue_number": record_fields["activation_issue_number"],
        "activation_profile_sha256": record_fields["activation_profile_sha256"],
        "adc_comment_id": record_fields["adc_comment_id"], "adc_sha256": record_fields["adc_sha256"],
        "approved": True, "merge_commit_sha40": record_fields["merge_commit_sha40"],
        "merged_at": record_fields["merged_at"], "merger_id": record_fields["merger_id"],
        "merger_login": record_fields["merger_login"], "merger_type": record_fields["merger_type"],
        "predecessor_record_id": predecessor,
        "proposed_adc_comment_id": record_fields["proposed_adc_comment_id"],
        "proposed_adc_sha256": record_fields["proposed_adc_sha256"],
        "proposed_adc_state": record_fields["proposed_adc_state"],
        "required_check_runs": record_fields["required_check_runs"],
        "repository": record_fields["repository"], "setup_pr_id": record_fields["setup_pr_id"],
        "setup_pr_number": record_fields["setup_pr_number"],
        "schema": "PASES_CONSUMER_ACTIVATION_APPROVAL_V1",
    }


def _ensure_setup_branch(root: Path, branch_ref: str, base_sha40: str, content: bytes) -> tuple[str, bool]:
    """Create or resume the one-path Activation branch, then pin its exact pushed commit."""
    local_exists = branch_exists(root, branch_ref)
    remote_exists = remote_branch_exists(root, branch_ref)
    resumed = local_exists or remote_exists
    if not resumed:
        create_branch(root, branch_ref, base_sha40)
        _write_profile(root, content)
        commit_sha = commit_and_push_one_path(
            root, branch_ref, ".agent/project.json", "chore: prepare P-ASES consumer activation",
        )
        remote_exists = True
    else:
        remote_sha = remote_branch_sha(root, branch_ref) if remote_exists else None
        if local_exists:
            switch_branch(root, branch_ref)
            commit_sha = head_sha40(root)
            if remote_sha is not None and remote_sha != commit_sha:
                raise ConsumerActivationError("local and remote Activation setup branch commits differ")
            if not remote_exists and commit_sha == base_sha40:
                _write_profile(root, content)
                commit_sha = commit_and_push_one_path(
                    root, branch_ref, ".agent/project.json", "chore: prepare P-ASES consumer activation",
                )
                remote_exists = True
        else:
            if remote_sha is None:
                raise ConsumerActivationError("remote Activation setup branch disappeared during readback")
            fetched_sha = fetch_remote_branch_exact(root, branch_ref, remote_sha)
            create_branch(root, branch_ref, fetched_sha)
            commit_sha = head_sha40(root)
    if (current_branch(root) != branch_ref or head_sha40(root) != commit_sha
            or commit_parent_sha40(root, commit_sha) != base_sha40
            or changed_paths_between(root, base_sha40, commit_sha) != (".agent/project.json",)
            or activation_profile_bytes_at_commit(root, commit_sha) != content
            or not worktree_clean(root)):
        raise ConsumerActivationError(
            "Activation setup branch is not the exact one-file change for the current subject"
        )
    if not remote_exists:
        push_branch_exact(root, branch_ref, commit_sha)
    if remote_branch_sha(root, branch_ref) != commit_sha or not worktree_clean(root):
        raise ConsumerActivationError("Activation setup branch failed exact remote/worktree readback")
    return commit_sha, resumed


def setup_consumer_activation(root: Path, github: GitHub) -> dict[str, Any]:
    """Prepare a marked Activation Issue, proposed ADC, project.json setup PR; never activate pre-merge."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ConsumerActivationError("Activation setup requires an existing non-symlink repository directory")
    root = root.resolve()
    if not worktree_clean(root):
        raise ConsumerActivationError("Activation setup requires a clean repository worktree")
    try:
        local_repository = discover_repository(root)
    except GitError as exc:
        raise ConsumerActivationError(f"could not resolve the active repository from this workspace: {exc}") from exc
    if local_repository.casefold() != github.repo.casefold():
        raise ConsumerActivationError("GitHub repository does not match the active workspace origin")
    profile_path = root / ".agent" / "project.json"
    configured = None
    if profile_path.exists() or profile_path.is_symlink():
        if path_has_symlink(profile_path, root=root):
            raise ConsumerActivationError("project.json path traverses a symbolic link")
        try:
            configured = load_profile(root).activation_issue_number
        except ProfileError as exc:
            raise ConsumerActivationError(f"existing project.json is invalid: {exc}") from exc
    try:
        metadata = github.repository_metadata()
        default_branch = metadata.get("default_branch")
        repository_id = _positive(metadata.get("id"), "repository ID")
        if not isinstance(default_branch, str) or current_branch(root) != default_branch:
            raise ConsumerActivationError("Activation setup must start on the repository default branch")
        head = head_sha40(root)
        if github.branch(default_branch).get("commit", {}).get("sha") != head:
            raise ConsumerActivationError("local default branch must match GitHub default-branch HEAD")
        user = github.authenticated_user()
        _identity(user, "authenticated user")
        issue = _resolve_issue(github, configured)
        if issue is None:
            created = github.create_issue(
                "P-ASES Consumer Activation",
                f"{ISSUE_MARKER}\n\nThis Issue stores the approved Activation ADC and append-only Activation history for `{github.repo}`.\n",
            )
            created_number = _positive(created.get("number"), "created Activation Issue number")
            issue = _resolve_issue(github, created_number)
            if issue is None or issue.get("number") != created_number:
                raise ConsumerActivationError("created Activation Issue did not pass exact readback")
        issue_number = _positive(issue.get("number"), "Activation Issue number")
        adc = _ensure_adc(github, issue_number)
        history = read_consumer_activation_history(github, github.repo, issue_number)
        if (history and configured == issue_number and adc.pointer.state == "approved"
                and history[-1][0].adc_sha256 == adc.pointer.sha256):
            active, record_id = history[-1]
            return {"status": "ACTIVE", "repository": github.repo, "issue": issue_number,
                    "activation_comment_id": record_id, "activated_at": active.activated_at,
                    "adc_comment_id": adc.pointer.comment_id, "adc_sha256": adc.pointer.sha256,
                    "reused": True}
        predecessor = history[-1][1] if history else None
        expected = _setup_payload(issue_number, adc, predecessor)
        branch_ref = _setup_branch(issue_number, adc.pointer.sha256, predecessor)
        candidates = github.pull_requests_for_refs(base_ref=default_branch, head_ref=branch_ref)
        if len(candidates) > 1:
            raise ConsumerActivationError("multiple setup PRs match the exact Activation branch")
        if candidates and candidates[0].get("state") == "open":
            pr = _check_setup_pr(github, candidates[0], expected, default_branch, repository_id)
            return {"status": "SETUP_PENDING", "repository": github.repo, "issue": issue_number,
                    "adc_comment_id": adc.pointer.comment_id, "adc_sha256": adc.pointer.sha256,
                    "pr": pr["number"], "pr_url": pr.get("html_url"), "reused": True}
        if candidates and candidates[0].get("merged") is True:
            record, record_id = verify_and_record_activation(github, candidates[0]["number"])
            return {"status": "ACTIVE", "repository": github.repo, "issue": issue_number,
                    "activation_comment_id": record_id, "activated_at": record.activated_at,
                    "pr": candidates[0]["number"], "reused": True}
        if candidates:
            raise ConsumerActivationError("an ambiguous closed setup PR already exists for this ADC generation")
        value, content = _profile_for_setup(root, github.repo, issue_number)
        before = profile_path.read_bytes() if profile_path.exists() else None
        try:
            commit_sha, resumed_branch = _ensure_setup_branch(root, branch_ref, head, content)
            body = _body(SETUP_MARKER, expected) + "\n\nMerge this PR to approve the Activation ADC and authorize P-ASES for new Issues."
            try:
                created_pr = github.create_pull_request(
                    title="P-ASES: prepare consumer Activation", body=body,
                    head_ref=branch_ref, base_ref=default_branch,
                )
                pr = github.pull_request(created_pr["number"])
            except GitHubError as exc:
                recovered = github.pull_requests_for_refs(base_ref=default_branch, head_ref=branch_ref)
                if len(recovered) != 1:
                    raise ConsumerActivationError("setup PR creation failed and exact recovery was ambiguous") from exc
                pr = recovered[0]
            pr = _check_setup_pr(github, pr, expected, default_branch, repository_id)
            if pr.get("head", {}).get("sha") != commit_sha:
                raise ConsumerActivationError("setup PR HEAD differs from the pushed project.json commit")
        except Exception:
            if current_branch(root) == branch_ref:
                if not worktree_clean(root):
                    if before is None:
                        profile_path.unlink(missing_ok=True)
                    else:
                        _write_profile(root, before)
                if worktree_clean(root):
                    switch_branch(root, default_branch)
            raise
        switch_branch(root, default_branch)
        return {"status": "SETUP_PENDING", "repository": github.repo, "issue": issue_number,
                "adc_comment_id": adc.pointer.comment_id, "adc_sha256": adc.pointer.sha256,
                    "pr": pr["number"], "pr_url": pr.get("html_url"), "setup_branch": branch_ref,
                "required_checks_configured": bool(value.get("branch", {}).get("required_checks")),
                "reasons": ([] if value.get("branch", {}).get("required_checks") else
                            ["Add trusted branch.required_checks in project.json before merging this setup PR."]),
                "reused": resumed_branch}
    except (GitHubError, GitError, OSError, ADCError) as exc:
        raise ConsumerActivationError(f"Activation setup failed closed: {exc}") from exc


def verify_and_record_activation(github: GitHub, pr_number: int) -> tuple[ConsumerActivationRecord, int]:
    """Verify an admin-merged setup PR, approve its exact ADC generation, and append history."""
    try:
        pr = github.pull_request(pr_number)
        setup = _decode(pr.get("body"), SETUP_MARKER, "setup PR", allow_trailer=True)
        issue_number = _positive(setup.get("activation_issue_number"), "Activation Issue number")
        if (not isinstance(setup.get("adc_sha256"), str) or not SHA256.fullmatch(setup["adc_sha256"])
                or not isinstance(setup.get("activation_profile_sha256"), str)
                or not SHA256.fullmatch(setup["activation_profile_sha256"])):
            raise ConsumerActivationError("setup PR ADC or Activation profile digest is invalid")
        history = read_consumer_activation_history(github, github.repo, issue_number,
                                                   allow_pending_approval=True)
        for existing, existing_id in history:
            if existing.setup_pr_number == pr_number:
                if (existing.proposed_adc_comment_id != setup["adc_comment_id"]
                        or existing.proposed_adc_sha256 != setup["adc_sha256"]
                        or existing.merge_commit_sha40 != pr.get("merge_commit_sha")):
                    raise ConsumerActivationError("setup PR already has a conflicting Activation record")
                return existing, existing_id
        checked_pr, _issue, proposed, check_evidence = _validate_merged_setup(
            github, pr_number, setup, require_current_adc=True, require_current_admin=True,
        )
        merger = checked_pr["merged_by"]
        merger_id, merger_login, _kind = _identity(merger, "setup PR merger")
        if _identity(github.authenticated_user(), "authenticated verifier") != (merger_id, merger_login, "User"):
            raise ConsumerActivationError("post-merge verifier must be the authenticated human who merged the setup PR")
        predecessor = history[-1][1] if history else None
        if setup.get("predecessor_record_id") != predecessor:
            raise ConsumerActivationError("setup PR predecessor does not match the latest Activation history")
        try:
            latest_adc = verify_adc(github, issue_number)
            if latest_adc.pointer.state == "approved":
                approved = latest_adc
            elif (latest_adc.pointer == proposed.pointer and proposed.pointer.state == "draft"):
                pointer = publish_adc(github, issue_number, proposed.contract.content,
                                      state="approved", explicitly_approved=True, supersede=True,
                                      expected_current=proposed.pointer)
                approved = verify_adc(github, issue_number)
                if approved.pointer != pointer:
                    raise ConsumerActivationError("approved ADC pointer did not pass exact current readback")
            else:
                raise ConsumerActivationError("Activation ADC changed before its setup PR was verified")
        except ADCError as exc:
            raise ConsumerActivationError(f"could not approve the exact merged Activation ADC: {exc}") from exc
        if (approved.pointer.sha256 != proposed.pointer.sha256
                or approved.contract.content != proposed.contract.content
                or approved.pointer.state != "approved"):
            raise ConsumerActivationError("approved Activation ADC differs from the setup PR proposal")
        fields = {
            "activation_issue_number": issue_number,
            "activation_profile_sha256": setup["activation_profile_sha256"],
            "adc_comment_id": approved.pointer.comment_id, "adc_sha256": approved.pointer.sha256,
            "merge_commit_sha40": checked_pr["merge_commit_sha"], "merged_at": checked_pr["merged_at"],
            "merger_id": merger_id, "merger_login": merger_login, "merger_type": "User",
            "predecessor_record_id": predecessor,
            "proposed_adc_comment_id": proposed.pointer.comment_id,
            "proposed_adc_sha256": proposed.pointer.sha256,
            "proposed_adc_state": proposed.pointer.state,
            "required_check_runs": [item.payload() for item in check_evidence],
            "repository": github.repo,
            "setup_pr_id": _positive(checked_pr.get("id"), "setup PR ID"),
            "setup_pr_number": pr_number,
        }
        approval_payload = _approval_payload(fields, predecessor=predecessor)
        comments = github.issue_comments(issue_number)
        approved_ids = {record.approval_comment_id for record, _ in history}
        orphans = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                   and row["body"].startswith(APPROVAL_MARKER) and row.get("id") not in approved_ids]
        if len(orphans) > 1:
            raise ConsumerActivationError("multiple unpaired Activation approvals exist")
        if orphans:
            approval_id = _positive(orphans[0].get("id"), "pending Activation approval Comment ID")
            readback = _read_comment(github, issue_number, approval_id, APPROVAL_MARKER,
                                     "Activation approval", unique_marker=False)
            if (_decode(readback.get("body"), APPROVAL_MARKER, "Activation approval") != approval_payload
                    or _identity(readback.get("user"), "Activation approval author")
                    != (merger_id, merger_login.casefold(), "User")):
                raise ConsumerActivationError("pending Activation approval does not match this exact merged PR")
        else:
            approval_id, _ = _publish_comment(github, issue_number, APPROVAL_MARKER, approval_payload,
                                              "Activation approval", allow_history=True)
        record = ConsumerActivationRecord(
            repository=github.repo, activation_issue_number=issue_number,
            proposed_adc_comment_id=proposed.pointer.comment_id,
            proposed_adc_sha256=proposed.pointer.sha256, proposed_adc_state=proposed.pointer.state,
            adc_comment_id=approved.pointer.comment_id, adc_sha256=approved.pointer.sha256,
            activation_profile_sha256=setup["activation_profile_sha256"],
            setup_pr_number=pr_number, setup_pr_id=fields["setup_pr_id"],
            merge_commit_sha40=checked_pr["merge_commit_sha"], merged_at=checked_pr["merged_at"],
            merger_id=merger_id, merger_login=merger_login, merger_type="User",
            approval_comment_id=approval_id, predecessor_record_id=predecessor,
            required_check_runs=check_evidence,
        ).validate()
        record_id, _ = _publish_comment(github, issue_number, RECORD_MARKER, record.payload(),
                                        "Activation record", allow_history=True)
        result = read_consumer_activation_record(github, github.repo, issue_number)
        if result is None or result[1] != record_id or result[0].payload() != record.payload():
            raise ConsumerActivationError("Activation record did not pass complete readback")
        return result[0], record_id
    except GitHubError as exc:
        raise ConsumerActivationError(f"post-merge Activation verification failed: {exc}") from exc


def read_consumer_activation_history(
    github: GitHub, repository: str, issue_number: int, *, allow_pending_approval: bool = False,
) -> list[tuple[ConsumerActivationRecord, int]]:
    try:
        if repository.casefold() != github.repo.casefold():
            raise ConsumerActivationError("Activation repository does not match the GitHub client")
        issue = github.issue(issue_number)
        issue_repository_url = issue.get("repository_url")
        if (issue.get("number") != issue_number or issue.get("pull_request") is not None
                or not _has_issue_marker(issue.get("body"))
                or not isinstance(issue_repository_url, str)
                or issue_repository_url.casefold() != f"https://api.github.com/repos/{repository}".casefold()):
            raise ConsumerActivationError("Activation Issue does not match its repository marker")
        comments = github.issue_comments(issue_number)
        records = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                   and row["body"].startswith(RECORD_MARKER)]
        approvals = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                     and row["body"].startswith(APPROVAL_MARKER)]
        if not records:
            if approvals and not allow_pending_approval:
                raise ConsumerActivationError("Activation history contains an orphan approval")
            if len(approvals) > (1 if allow_pending_approval else 0):
                raise ConsumerActivationError("Activation history contains duplicate orphan approvals")
            return []
        records.sort(key=lambda row: row.get("id", 0))
        record_ids = [row.get("id") for row in records]
        approval_ids = [row.get("id") for row in approvals]
        if (any(type(value) is not int or value < 1 for value in record_ids + approval_ids)
                or len(record_ids) != len(set(record_ids)) or len(approval_ids) != len(set(approval_ids))
                or len(approvals) not in ({len(records), len(records) + 1}
                                          if allow_pending_approval else {len(records)})):
            raise ConsumerActivationError("Activation history has missing or duplicate approval/record IDs")
        initial_markers = {
            "records": sorted((_fingerprint(row, issue_number, row["id"], RECORD_MARKER, "Activation record")
                                for row in records), key=lambda row: row[0]),
            "approvals": sorted((_fingerprint(row, issue_number, row["id"], APPROVAL_MARKER, "Activation approval")
                                  for row in approvals), key=lambda row: row[0]),
        }
        result: list[tuple[ConsumerActivationRecord, int]] = []
        used_approvals: set[int] = set()
        used_prs: set[int] = set()
        predecessor: int | None = None
        predecessor_merge: datetime | None = None
        for listed_record in records:
            record_id = _positive(listed_record["id"], "Activation record Comment ID")
            record = ConsumerActivationRecord.from_payload(
                _decode(listed_record.get("body"), RECORD_MARKER, "Activation record"))
            if (record.activation_issue_number != issue_number or record.repository.casefold() != repository.casefold()
                    or record.predecessor_record_id != predecessor or record.setup_pr_number in used_prs
                    or record.activation_profile_sha256 != _profile_digest(issue_number)):
                raise ConsumerActivationError("Activation history is misordered or belongs to another subject")
            used_prs.add(record.setup_pr_number)
            record_row = _read_comment(github, issue_number, record_id, RECORD_MARKER,
                                       "Activation record", unique_marker=False)
            if record_row.get("body") != listed_record.get("body"):
                raise ConsumerActivationError("Activation record changed after its initial list read")
            record = replace(record, record_created_at=record_row.get("created_at")).validate()
            merge_time = _timestamp(record.merged_at, "setup PR merge time")
            if predecessor_merge is not None and merge_time < predecessor_merge:
                raise ConsumerActivationError("successor Activation merge time predates its predecessor")
            predecessor_merge = merge_time
            approval_row = next((row for row in approvals if row.get("id") == record.approval_comment_id), None)
            if approval_row is None or record.approval_comment_id in used_approvals:
                raise ConsumerActivationError("Activation record has a missing or reused approval comment")
            used_approvals.add(record.approval_comment_id)
            approval = _read_comment(github, issue_number, record.approval_comment_id,
                                     APPROVAL_MARKER, "Activation approval", unique_marker=False)
            expected_approval = _approval_payload(record.payload(), predecessor=record.predecessor_record_id)
            if (_decode(approval.get("body"), APPROVAL_MARKER, "Activation approval") != expected_approval
                    or _identity(approval.get("user"), "Activation approval author")
                    != (record.merger_id, record.merger_login.casefold(), record.merger_type)
                    or _identity(record_row.get("user"), "Activation record author")
                    != (record.merger_id, record.merger_login.casefold(), record.merger_type)):
                raise ConsumerActivationError("Activation approval/record author or payload does not match")
            approval_time = _timestamp(approval.get("created_at"), "Activation approval creation time")
            record_time = _timestamp(record_row.get("created_at"), "Activation record creation time")
            if merge_time > approval_time or approval_time > record_time:
                raise ConsumerActivationError("Activation approval and record do not follow the verified PR merge")
            expected_setup = {
                "activation_issue_number": record.activation_issue_number,
                "activation_profile_sha256": record.activation_profile_sha256,
                "adc_comment_id": record.proposed_adc_comment_id,
                "adc_sha256": record.proposed_adc_sha256,
                "adc_state": record.proposed_adc_state,
                "predecessor_record_id": record.predecessor_record_id,
                "schema": "PASES_CONSUMER_ACTIVATION_SETUP_V1",
            }
            pr, _issue, proposed, _pinned_checks = _validate_merged_setup(
                github, record.setup_pr_number, expected_setup,
                require_current_adc=False, require_current_admin=False,
                expected_check_runs=record.required_check_runs,
            )
            approved = verify_adc_generation(github, issue_number, record.adc_comment_id,
                                             record.adc_sha256, state="approved")
            if (proposed.contract.content != approved.contract.content
                    or pr.get("id") != record.setup_pr_id
                    or pr.get("merge_commit_sha") != record.merge_commit_sha40
                    or pr.get("merged_at") != record.merged_at
                    or _identity(pr.get("merged_by"), "setup PR merger")
                    != (record.merger_id, record.merger_login.casefold(), record.merger_type)):
                raise ConsumerActivationError("Activation record no longer matches its merged setup PR and ADC")
            final = _read_comment(github, issue_number, record_id, RECORD_MARKER,
                                  "Activation record", unique_marker=False)
            if (final.get("body") != record_row.get("body")
                    or final.get("created_at") != record_row.get("created_at")
                    or _identity(final.get("user"), "Activation record author")
                    != (record.merger_id, record.merger_login.casefold(), record.merger_type)):
                raise ConsumerActivationError("Activation record changed during PR/evidence validation")
            result.append((record, record_id))
            predecessor = record_id
        orphan_ids = set(approval_ids) - used_approvals
        if orphan_ids:
            if not allow_pending_approval or len(orphan_ids) != 1:
                raise ConsumerActivationError("Activation history contains an orphan approval")
            orphan_row = next(row for row in approvals if row.get("id") in orphan_ids)
            orphan_id = _positive(orphan_row.get("id"), "pending Activation approval Comment ID")
            readback = _read_comment(github, issue_number, orphan_id, APPROVAL_MARKER,
                                     "Activation approval", unique_marker=False)
            payload = _decode(readback.get("body"), APPROVAL_MARKER, "Activation approval")
            if (payload.get("schema") != "PASES_CONSUMER_ACTIVATION_APPROVAL_V1"
                    or payload.get("activation_issue_number") != issue_number
                    or payload.get("repository") != repository
                    or payload.get("predecessor_record_id") != predecessor
                    or type(payload.get("setup_pr_number")) is not int
                    or payload.get("setup_pr_number") in used_prs):
                raise ConsumerActivationError("orphan approval is not a valid pending Activation successor")
        final_comments = github.issue_comments(issue_number)
        final_records = [row for row in final_comments if isinstance(row, dict)
                         and isinstance(row.get("body"), str) and row["body"].startswith(RECORD_MARKER)]
        final_approvals = [row for row in final_comments if isinstance(row, dict)
                           and isinstance(row.get("body"), str) and row["body"].startswith(APPROVAL_MARKER)]
        final_markers = {
            "records": sorted((_fingerprint(row, issue_number, row.get("id"), RECORD_MARKER, "Activation record")
                                for row in final_records), key=lambda row: row[0]),
            "approvals": sorted((_fingerprint(row, issue_number, row.get("id"), APPROVAL_MARKER, "Activation approval")
                                  for row in final_approvals), key=lambda row: row[0]),
        }
        if initial_markers != final_markers:
            raise ConsumerActivationError("Activation history changed during full readback")
        return result
    except (GitHubError, ADCError) as exc:
        raise ConsumerActivationError(f"Activation history readback failed: {exc}") from exc


def read_consumer_activation_record(
    github: GitHub, repository: str, issue_number: int,
) -> tuple[ConsumerActivationRecord, int] | None:
    history = read_consumer_activation_history(github, repository, issue_number)
    return history[-1] if history else None
