"""Issue-scoped implementation execution bindings for host-selected workspaces."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import ContractError, parse_comment, parse_pointer
from .git import (
    GitLifecycleError,
    fetch_base_ref,
    feature_slug,
    is_configured_issue_branch,
    origin_repository,
    require_clean_worktree,
    validate_branch_ref,
    workspace_identity,
)
from .github import GitHub, GitHubError
from .profile import ProfileError, load_profile


class ExecutionError(ValueError):
    pass


FIELDS = {
    "schema_version", "issue", "repository", "contract_comment_id", "contract_sha256",
    "workspace_root", "mode", "base_ref", "base_sha", "initial_head", "canonical_branch",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def execution_path(repo: Path, issue: int) -> Path:
    return repo / ".agent-state" / "issues" / str(issue) / "execution.json"


def _positive_issue(issue: int) -> None:
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        raise ExecutionError("Issue number must be a positive integer")


def _approved_contract(issue: int, gh: GitHub) -> tuple[int, str]:
    """Verify the approved pointer and its named comment bytes through the GitHub boundary."""
    try:
        issue_obj = gh.issue(issue)
        expected_repo = f"https://api.github.com/repos/{gh.repo}"
        if (not isinstance(issue_obj, dict) or type(issue_obj.get("number")) is not int
                or issue_obj.get("number") != issue
                or issue_obj.get("repository_url") != expected_repo or issue_obj.get("pull_request")):
            raise ExecutionError("Issue identity does not match the configured repository")
        if issue_obj.get("state") != "open":
            raise ExecutionError("Issue must be open before implementation execution")
        issue_body = issue_obj.get("body") or ""
        if not isinstance(issue_body, str):
            raise ExecutionError("Issue body is malformed")
        comment_id, pointer_sha = parse_pointer(issue_body)
        comment = gh.issue_comment(issue, comment_id)
        expected_issue_url = f"{expected_repo}/issues/{issue}"
        if (not isinstance(comment, dict) or comment.get("issue_url") != expected_issue_url
                or type(comment.get("id")) is not int or comment.get("id") != comment_id):
            raise ExecutionError("approved Contract comment is not associated with the requested Issue")
        comment_body = comment.get("body") or ""
        if not isinstance(comment_body, str):
            raise ExecutionError("approved Contract comment body is malformed")
        _payload, actual_sha = parse_comment(comment_body, issue)
        if actual_sha != pointer_sha:
            raise ExecutionError("approved Contract pointer SHA does not match its named comment bytes")
        return comment_id, actual_sha
    except (GitHubError, ContractError) as exc:
        raise ExecutionError(str(exc)) from exc


def _validate_record(record: Any, repo: Path, issue: int, repository: str,
                     root: Path, profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ExecutionError("execution binding must contain exactly the Schema 1 fields")
    if record.get("schema_version") != 1:
        raise ExecutionError("unsupported execution binding schema version")
    if record.get("issue") != issue or isinstance(record.get("issue"), bool):
        raise ExecutionError("execution binding belongs to a different Issue")
    if record.get("repository") != repository:
        raise ExecutionError("execution binding belongs to a different repository")
    if not isinstance(record.get("contract_comment_id"), int) or isinstance(record.get("contract_comment_id"), bool) or record["contract_comment_id"] < 1:
        raise ExecutionError("execution binding Contract comment ID is invalid")
    if not isinstance(record.get("contract_sha256"), str) or not SHA256.fullmatch(record["contract_sha256"]):
        raise ExecutionError("execution binding Contract SHA-256 is invalid")
    workspace_root = record.get("workspace_root")
    if not isinstance(workspace_root, str) or not Path(workspace_root).is_absolute():
        raise ExecutionError("execution binding workspace root must be an absolute path")
    if Path(workspace_root).resolve() != root.resolve():
        raise ExecutionError("execution binding belongs to a different workspace")
    if record.get("mode") not in {"isolated", "current"}:
        raise ExecutionError("execution binding mode is invalid")
    if (not isinstance(record.get("base_ref"), str) or not record["base_ref"].strip()
            or len(record["base_ref"]) > 255 or any(c in record["base_ref"] for c in "\x00\r\n")):
        raise ExecutionError("execution binding base ref is invalid")
    if not isinstance(record.get("base_sha"), str) or not SHA40.fullmatch(record["base_sha"]):
        raise ExecutionError("execution binding base SHA is invalid")
    if not isinstance(record.get("initial_head"), str) or not SHA40.fullmatch(record["initial_head"]):
        raise ExecutionError("execution binding initial HEAD is invalid")
    if record["initial_head"] != record["base_sha"]:
        raise ExecutionError("execution binding initial HEAD does not match its frozen base SHA")
    try:
        validate_branch_ref(repo, record["base_ref"], "execution binding base ref")
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    canonical = record.get("canonical_branch")
    if not isinstance(canonical, str) or not is_configured_issue_branch(profile, issue, canonical):
        raise ExecutionError("execution binding canonical branch is not configured for this Issue")
    return record


def _read_record(repo: Path, issue: int) -> dict[str, Any] | None:
    path = execution_path(repo, issue)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"execution binding is missing or invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise ExecutionError("execution binding must be a JSON object")
    return value


def _atomic_write(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        temp.unlink(missing_ok=True)
        raise


def _load_profile(repo: Path) -> dict[str, Any]:
    try:
        profile = load_profile(repo)
    except ProfileError as exc:
        raise ExecutionError(str(exc)) from exc
    if profile.get("schema_version") != 2:
        raise ExecutionError("prepare-implementation requires a Schema 2 project profile")
    return profile


def _execution_status(record: dict[str, Any], current: bool) -> dict[str, Any]:
    return {
        "mode": record["mode"],
        "canonical_branch": record["canonical_branch"],
        "base_ref": record["base_ref"],
        "base_sha": record["base_sha"],
        "contract_comment_id": record["contract_comment_id"],
        "contract_sha256": record["contract_sha256"],
        "current": current,
    }


def execution_status(repo: Path, issue: int, gh: GitHub) -> dict[str, Any] | None:
    """Return only bounded binding status; malformed or foreign state is not exposed."""
    _positive_issue(issue)
    try:
        record = _read_record(repo, issue)
        if record is None:
            return None
        profile = _load_profile(repo)
        identity = workspace_identity(repo)
        record = _validate_record(record, repo, issue, gh.repo, identity.root, profile)
        if record["mode"] == "isolated" and not identity.linked_worktree:
            return None
        if record["mode"] == "current" and identity.branch != record["canonical_branch"]:
            return None
        if origin_repository(repo).casefold() != gh.repo.casefold():
            return None
    except (ExecutionError, GitLifecycleError):
        return None
    try:
        comment_id, digest = _approved_contract(issue, gh)
        current = comment_id == record["contract_comment_id"] and digest == record["contract_sha256"]
    except ExecutionError:
        current = False
    return _execution_status(record, current)


def load_execution(repo: Path, issue: int, gh: GitHub) -> dict[str, Any] | None:
    """Load a current binding for review publication or fail closed when stale."""
    _positive_issue(issue)
    profile = _load_profile(repo)
    record = _read_record(repo, issue)
    if record is None:
        return None
    identity = workspace_identity(repo)
    record = _validate_record(record, repo, issue, gh.repo, identity.root, profile)
    if record["mode"] == "isolated" and not identity.linked_worktree:
        raise ExecutionError("isolated execution binding is not in a linked worktree")
    if record["mode"] == "current" and identity.branch != record["canonical_branch"]:
        raise ExecutionError("current execution binding is no longer on its canonical Issue branch")
    try:
        if origin_repository(repo).casefold() != gh.repo.casefold():
            raise ExecutionError("origin fetch repository does not match the owning Issue")
        comment_id, digest = _approved_contract(issue, gh)
    except (GitLifecycleError, GitHubError) as exc:
        raise ExecutionError(str(exc)) from exc
    if comment_id != record["contract_comment_id"] or digest != record["contract_sha256"]:
        raise ExecutionError("approved Contract changed; run prepare-implementation with --supersede")
    return record


def prepare_implementation(repo: Path, issue: int, gh: GitHub, *, mode: str,
                           base_ref: str | None = None, expected_base_sha: str | None = None,
                           supersede: bool = False) -> dict[str, Any]:
    """Verify initial execution preconditions and atomically create/reuse the binding."""
    _positive_issue(issue)
    if mode not in {"isolated", "current"}:
        raise ExecutionError("--mode must be isolated or current")
    if expected_base_sha is not None and (not isinstance(expected_base_sha, str) or not SHA40.fullmatch(expected_base_sha)):
        raise ExecutionError("--expected-base-sha must be exactly 40 lowercase hexadecimal characters")
    profile = _load_profile(repo)
    isolation = profile["workspace"]["isolation"]
    if isolation == "required" and mode != "isolated":
        raise ExecutionError("workspace.isolation=required requires host-managed isolated mode")
    if isolation == "disabled" and mode != "current":
        raise ExecutionError("workspace.isolation=disabled requires current mode")

    try:
        if origin_repository(repo).casefold() != gh.repo.casefold():
            raise ExecutionError("origin fetch repository does not match the owning Issue")
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    contract_comment_id, contract_sha = _approved_contract(issue, gh)
    identity = workspace_identity(repo)
    existing = _read_record(repo, issue)
    if existing is not None:
        record = _validate_record(existing, repo, issue, gh.repo, identity.root, profile)
        if record["mode"] == "isolated" and not identity.linked_worktree:
            raise ExecutionError("isolated execution binding is not in a linked worktree")
        if record["mode"] == "current" and identity.branch != record["canonical_branch"]:
            raise ExecutionError("current execution binding is no longer on its canonical Issue branch")
        if record["mode"] != mode:
            raise ExecutionError("execution binding already uses a different workspace mode")
        changed_contract = (
            record["contract_comment_id"] != contract_comment_id
            or record["contract_sha256"] != contract_sha
        )
        if changed_contract:
            if not supersede:
                raise ExecutionError("approved Contract changed; explicit --supersede is required")
            record = {**record, "contract_comment_id": contract_comment_id, "contract_sha256": contract_sha}
            _atomic_write(execution_path(repo, issue), record)
        elif supersede:
            # An explicit retry against the same approved Contract is an idempotent reuse.
            pass
        return {**record, "reused": True, "superseded": changed_contract}
    if supersede:
        raise ExecutionError("--supersede requires an existing execution binding")

    if mode == "isolated" and not identity.linked_worktree:
        raise ExecutionError("isolated mode requires a linked Git worktree")
    try:
        require_clean_worktree(repo)
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    selected_base = base_ref
    if selected_base is None:
        try:
            selected_base = gh.repository().get("default_branch")
        except GitHubError as exc:
            raise ExecutionError(str(exc)) from exc
    if not isinstance(selected_base, str) or not selected_base.strip():
        raise ExecutionError("selected base branch is missing")
    try:
        base_sha = fetch_base_ref(repo, selected_base)
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    if expected_base_sha is not None and expected_base_sha != base_sha:
        raise ExecutionError("expected base SHA does not match the selected remote branch")
    if identity.head_sha != base_sha:
        raise ExecutionError("local HEAD does not match the selected base SHA")

    issue_obj = gh.issue(issue)
    if (not isinstance(issue_obj, dict) or type(issue_obj.get("number")) is not int
            or issue_obj.get("number") != issue
            or issue_obj.get("repository_url") != f"https://api.github.com/repos/{gh.repo}"
            or issue_obj.get("pull_request") or issue_obj.get("state") != "open"):
        raise ExecutionError("Issue identity or state changed while preparing the execution binding")
    title = issue_obj.get("title") if isinstance(issue_obj, dict) else None
    if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
        raise ExecutionError("Issue title is missing or malformed")
    if mode == "current":
        if not is_configured_issue_branch(profile, issue, identity.branch):
            raise ExecutionError("current mode requires the configured Issue feature branch")
        canonical_branch = identity.branch
    else:
        branch_policy = profile["branch"]
        try:
            slug = feature_slug(title, branch_policy["max_slug_length"])
        except GitLifecycleError as exc:
            raise ExecutionError(str(exc)) from exc
        canonical_branch = f"{branch_policy['prefix']}/{issue}-{slug}"
    latest_identity = workspace_identity(repo)
    if (latest_identity.root != identity.root or latest_identity.head_sha != base_sha
            or latest_identity.branch != identity.branch
            or latest_identity.linked_worktree != identity.linked_worktree):
        raise ExecutionError("workspace identity changed while preparing the execution binding")
    try:
        require_clean_worktree(repo)
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    latest_contract_id, latest_contract_sha = _approved_contract(issue, gh)
    if latest_contract_id != contract_comment_id or latest_contract_sha != contract_sha:
        raise ExecutionError("approved Contract changed while preparing the execution binding")
    record = {
        "schema_version": 1,
        "issue": issue,
        "repository": gh.repo,
        "contract_comment_id": contract_comment_id,
        "contract_sha256": contract_sha,
        "workspace_root": str(identity.root.resolve()),
        "mode": mode,
        "base_ref": selected_base,
        "base_sha": base_sha,
        "initial_head": identity.head_sha,
        "canonical_branch": canonical_branch,
    }
    _validate_record(record, repo, issue, gh.repo, identity.root, profile)
    _atomic_write(execution_path(repo, issue), record)
    return {**record, "reused": False, "superseded": False}
