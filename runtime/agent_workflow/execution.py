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
    is_commit_ancestor,
    is_configured_issue_branch,
    local_head_sha,
    origin_repository,
    require_clean_worktree,
    validate_branch_ref,
    workspace_identity,
)
from .github import GitHub, GitHubError
from .profile import ProfileError, load_profile


class ExecutionError(ValueError):
    pass


SCHEMA_1_FIELDS = {
    "schema_version", "issue", "repository", "contract_comment_id", "contract_sha256",
    "workspace_root", "mode", "base_ref", "base_sha", "initial_head", "canonical_branch",
}
SCHEMA_2_FIELDS = SCHEMA_1_FIELDS | {"recovery"}
FIELDS = SCHEMA_1_FIELDS
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
    if not isinstance(record, dict):
        raise ExecutionError("execution binding must be a JSON object")
    version = record.get("schema_version")
    expected_fields = SCHEMA_1_FIELDS if version == 1 and type(version) is int else (
        SCHEMA_2_FIELDS if version == 2 and type(version) is int else None
    )
    if expected_fields is None:
        raise ExecutionError("unsupported execution binding schema version")
    if set(record) != expected_fields:
        raise ExecutionError(f"execution binding must contain exactly the Schema {version} fields")
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
    if version == 2:
        recovery = record.get("recovery")
        if (record.get("mode") != "current" or not isinstance(recovery, dict)
                or set(recovery) != {"kind", "pr", "head_sha"}
                or recovery.get("kind") != "verified-open-pr-continuation"
                or type(recovery.get("pr")) is not int or recovery["pr"] < 1
                or not isinstance(recovery.get("head_sha"), str)
                or not SHA40.fullmatch(recovery["head_sha"])):
            raise ExecutionError("execution binding Schema 2 recovery metadata is invalid")
        try:
            checkpoint_is_ancestor = is_commit_ancestor(
                repo, recovery["head_sha"], local_head_sha(repo)
            )
        except GitLifecycleError as exc:
            raise ExecutionError(str(exc)) from exc
        if not checkpoint_is_ancestor:
            raise ExecutionError("current HEAD is not a descendant of the recovered PR checkpoint")
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


def _atomic_create(path: Path, record: dict[str, Any]) -> None:
    """Atomically create a new binding without replacing a concurrent record."""
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
        os.link(temp, path)
        temp.unlink()
    except OSError as exc:
        try:
            os.close(fd)
        except OSError:
            pass
        temp.unlink(missing_ok=True)
        if isinstance(exc, FileExistsError):
            raise ExecutionError("an execution binding appeared during continuation recovery") from exc
        raise ExecutionError("could not atomically create the execution binding") from exc


def _load_profile(repo: Path) -> dict[str, Any]:
    try:
        profile = load_profile(repo)
    except ProfileError as exc:
        raise ExecutionError(str(exc)) from exc
    if profile.get("schema_version") != 2:
        raise ExecutionError("prepare-implementation requires a Schema 2 project profile")
    return profile


def resolve_implementation_base(repo: Path, issue: int, gh: GitHub, *,
                                base_ref: str | None = None,
                                expected_base_sha: str | None = None) -> dict[str, Any]:
    """Resolve the approved execution's selected same-origin base without changing workspace state."""
    _positive_issue(issue)
    if expected_base_sha is not None and (
            not isinstance(expected_base_sha, str) or not SHA40.fullmatch(expected_base_sha)):
        raise ExecutionError("--expected-base-sha must be exactly 40 lowercase hexadecimal characters")

    profile = _load_profile(repo)
    try:
        if origin_repository(repo).casefold() != gh.repo.casefold():
            raise ExecutionError("origin fetch repository does not match the owning Issue")
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc

    contract_comment_id, contract_sha = _approved_contract(issue, gh)
    try:
        default_base_ref = gh.repository().get("default_branch")
    except GitHubError as exc:
        raise ExecutionError(str(exc)) from exc
    if not isinstance(default_base_ref, str) or not default_base_ref.strip():
        raise ExecutionError("GitHub repository default branch is missing")
    try:
        validate_branch_ref(repo, default_base_ref, "GitHub repository default branch")
        selected_base = default_base_ref if base_ref is None else base_ref
        validate_branch_ref(repo, selected_base, "selected base branch")
        base_sha = fetch_base_ref(repo, selected_base)
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    if expected_base_sha is not None and expected_base_sha != base_sha:
        raise ExecutionError("expected base SHA does not match the selected remote branch")

    return {
        "issue": issue,
        "repository": gh.repo,
        "contract_comment_id": contract_comment_id,
        "contract_sha256": contract_sha,
        "default_base_ref": default_base_ref,
        "base_ref": selected_base,
        "base_sha": base_sha,
        "stacked": selected_base != default_base_ref,
    }


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


def _verify_recovery_pull(pull: Any, issue: int, pr: int, repository: str,
                          branch: str, base_ref: str, base_sha: str,
                          head_sha: str) -> None:
    if not isinstance(pull, dict) or type(pull.get("number")) is not int or pull.get("number") != pr:
        raise ExecutionError("PR identity does not match the requested continuation PR")
    if pull.get("state") != "open" or pull.get("draft") is not False or pull.get("merged") is True:
        raise ExecutionError("continuation recovery requires an open, non-draft PR")
    head, base = pull.get("head"), pull.get("base")
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    if (not isinstance(head_repo, dict) or not isinstance(base_repo, dict)
            or str(head_repo.get("full_name", "")).casefold() != repository.casefold()
            or str(base_repo.get("full_name", "")).casefold() != repository.casefold()):
        raise ExecutionError("continuation PR head and base must belong to the configured repository")
    body = pull.get("body")
    if not isinstance(body, str) or not re.search(rf"(?im)^\s*closes\s+#{issue}\s*$", body):
        raise ExecutionError(f"continuation PR body must contain a standalone Closes #{issue} line")
    if (head.get("ref") != branch or head.get("sha") != head_sha
            or base.get("ref") != base_ref or base.get("sha") != base_sha):
        raise ExecutionError("continuation PR refs or SHAs do not match the verified checkout and base")


def recover_implementation_binding(repo: Path, issue: int, pr: int, gh: GitHub, *,
                                   base_ref: str, expected_base_sha: str) -> dict[str, Any]:
    """Recover a missing local binding from an exact, open same-repository continuation PR."""
    _positive_issue(issue)
    if not isinstance(pr, int) or isinstance(pr, bool) or pr < 1:
        raise ExecutionError("PR number must be a positive integer")
    if not isinstance(expected_base_sha, str) or not SHA40.fullmatch(expected_base_sha):
        raise ExecutionError("--expected-base-sha must be exactly 40 lowercase hexadecimal characters")

    profile = _load_profile(repo)
    if profile["workspace"]["isolation"] == "required":
        raise ExecutionError("workspace.isolation=required does not allow current-mode binding recovery")
    try:
        if origin_repository(repo).casefold() != gh.repo.casefold():
            raise ExecutionError("origin fetch repository does not match the owning Issue")
        validate_branch_ref(repo, base_ref, "--base-ref")
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc

    contract_comment_id, contract_sha = _approved_contract(issue, gh)
    if _read_record(repo, issue) is not None:
        raise ExecutionError("an execution binding already exists; validate it with prepare-implementation")
    try:
        require_clean_worktree(repo)
        identity = workspace_identity(repo)
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    if not identity.branch:
        raise ExecutionError("continuation recovery requires a current Issue branch workspace")

    issue_obj = gh.issue(issue)
    expected_issue_url = f"https://api.github.com/repos/{gh.repo}"
    if (not isinstance(issue_obj, dict) or type(issue_obj.get("number")) is not int
            or issue_obj.get("number") != issue or issue_obj.get("repository_url") != expected_issue_url
            or issue_obj.get("pull_request") or issue_obj.get("state") != "open"):
        raise ExecutionError("Issue identity or state changed during continuation recovery")
    title = issue_obj.get("title")
    if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
        raise ExecutionError("Issue title is missing or malformed")
    try:
        canonical_branch = f"{profile['branch']['prefix']}/{issue}-{feature_slug(title, profile['branch']['max_slug_length'])}"
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    if identity.branch != canonical_branch:
        raise ExecutionError("continuation recovery requires the configured canonical Issue branch")

    try:
        base_sha = fetch_base_ref(repo, base_ref)
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc
    if base_sha != expected_base_sha:
        raise ExecutionError("expected base SHA does not match the selected remote branch")

    pull = gh.pull(pr)
    _verify_recovery_pull(pull, issue, pr, gh.repo, canonical_branch, base_ref,
                          expected_base_sha, identity.head_sha)
    try:
        if not is_commit_ancestor(repo, expected_base_sha, identity.head_sha):
            raise ExecutionError("selected base is not an ancestor of the continuation PR HEAD")
    except GitLifecycleError as exc:
        raise ExecutionError(str(exc)) from exc

    # Recheck all authority and mutable refs immediately before the atomic local write.
    try:
        latest_base_sha = fetch_base_ref(repo, base_ref)
        latest_contract_id, latest_contract_sha = _approved_contract(issue, gh)
        latest_issue = gh.issue(issue)
        latest_pull = gh.pull(pr)
        latest_identity = workspace_identity(repo)
        require_clean_worktree(repo)
    except (GitLifecycleError, GitHubError) as exc:
        raise ExecutionError(str(exc)) from exc
    if latest_base_sha != expected_base_sha:
        raise ExecutionError("selected base changed during continuation recovery")
    if (latest_contract_id != contract_comment_id or latest_contract_sha != contract_sha
            or not isinstance(latest_issue, dict) or latest_issue.get("title") != title):
        raise ExecutionError("Issue or approved Contract changed during continuation recovery")
    _verify_recovery_pull(latest_pull, issue, pr, gh.repo, canonical_branch, base_ref,
                          expected_base_sha, identity.head_sha)
    if (latest_identity.root != identity.root or latest_identity.head_sha != identity.head_sha
            or latest_identity.branch != identity.branch
            or latest_identity.linked_worktree != identity.linked_worktree):
        raise ExecutionError("workspace identity changed during continuation recovery")
    if _read_record(repo, issue) is not None:
        raise ExecutionError("an execution binding appeared during continuation recovery")

    record = {
        "schema_version": 2,
        "issue": issue,
        "repository": gh.repo,
        "contract_comment_id": contract_comment_id,
        "contract_sha256": contract_sha,
        "workspace_root": str(identity.root.resolve()),
        "mode": "current",
        "base_ref": base_ref,
        "base_sha": expected_base_sha,
        "initial_head": expected_base_sha,
        "canonical_branch": canonical_branch,
        "recovery": {
            "kind": "verified-open-pr-continuation",
            "pr": pr,
            "head_sha": identity.head_sha,
        },
    }
    _validate_record(record, repo, issue, gh.repo, identity.root, profile)
    _atomic_create(execution_path(repo, issue), record)
    return {
        "issue": issue,
        "repository": gh.repo,
        "contract_comment_id": contract_comment_id,
        "contract_sha256": contract_sha,
        "pr": pr,
        "canonical_branch": canonical_branch,
        "mode": "current",
        "base_ref": base_ref,
        "base_sha": expected_base_sha,
        "initial_head": expected_base_sha,
        "recovered_head": identity.head_sha,
        "recovered": True,
    }
