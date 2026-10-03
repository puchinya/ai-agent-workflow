"""Safe, one-shot Git lifecycle operations. All Git calls use argv arrays."""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

from .process import ProcessError, run_command
from .profile import build_hook_plan


class GitLifecycleError(RuntimeError):
    pass


def feature_slug(description: str, max_length: int) -> str:
    ascii_text = unicodedata.normalize("NFKD", description).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = re.sub(r"-+", "-", slug)[:max_length].rstrip("-")
    if not slug:
        raise GitLifecycleError("feature description produces an empty branch slug")
    return slug


def _invoke(repo: Path, args: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8", errors="replace",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, shell=False)
    except OSError as exc:
        raise GitLifecycleError(f"could not start Git {args[0]}") from exc
    if result.returncode and not allow_failure:
        raise GitLifecycleError(f"Git {args[0]} failed (exit status {result.returncode})")
    return result


def _validate_ref(repo: Path, ref: str) -> None:
    if not ref or "\x00" in ref or _invoke(repo, ["check-ref-format", "--branch", ref], allow_failure=True).returncode:
        raise GitLifecycleError("GitHub repository metadata contains an invalid default branch")


def _require_clean(repo: Path) -> None:
    result = _invoke(repo, ["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"])
    if result.stdout:
        raise GitLifecycleError("worktree must be clean before starting a feature branch")


def _branch_exists(repo: Path, branch: str) -> bool:
    result = _invoke(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], allow_failure=True)
    if result.returncode not in {0, 1}:
        raise GitLifecycleError(f"Git show-ref failed (exit status {result.returncode})")
    return result.returncode == 0


def _current_branch(repo: Path) -> str | None:
    result = _invoke(repo, ["branch", "--show-current"])
    return result.stdout.strip() or None


def _fetch_refs(repo: Path, default_branch: str, target_branch: str) -> bool:
    _invoke(repo, ["fetch", "origin", f"+refs/heads/{default_branch}:refs/remotes/origin/{default_branch}"])
    remote = _invoke(repo, ["ls-remote", "--heads", "origin", f"refs/heads/{target_branch}"])
    has_remote_target = any(line.split("\t", 1)[-1] == f"refs/heads/{target_branch}"
                            for line in remote.stdout.splitlines() if "\t" in line)
    if has_remote_target:
        _invoke(repo, ["fetch", "origin", f"+refs/heads/{target_branch}:refs/remotes/origin/{target_branch}"])
    return has_remote_target


def _remove_cleanup_path(repo: Path, relative: str) -> bool:
    path = repo.joinpath(*PurePosixPath(relative).parts)
    root = repo.resolve()
    parent = path.parent.resolve()
    if parent != root and root not in parent.parents:
        raise OSError(f"cleanup path escapes repository: {relative}")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode):
        path.unlink()
    elif stat.S_ISDIR(mode):
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def start_feature_branch(repo: Path, profile: dict[str, Any], issue_number: int,
                         description: str, github: Any) -> tuple[dict[str, Any], int]:
    """Switch/create a feature branch, then perform cleanup and global switch hooks."""
    policy = profile["branch"]
    slug = feature_slug(description, policy["max_slug_length"])
    target = f"{policy['prefix']}/{issue_number}-{slug}"

    _require_clean(repo)
    metadata = github.repository()
    default_branch = metadata["default_branch"]
    _validate_ref(repo, default_branch)
    has_remote_target = _fetch_refs(repo, default_branch, target)

    current = _current_branch(repo)
    if current == target:
        return ({"issue": issue_number, "branch": target, "switched": False,
                 "cleanup_paths_removed": 0, "hooks_run": 0}, 0)

    local_target = _branch_exists(repo, target)
    if local_target:
        _invoke(repo, ["switch", "--", target])
    elif has_remote_target:
        _invoke(repo, ["switch", "--track", "--create", target, f"origin/{target}"])
    else:
        _invoke(repo, ["switch", "--no-track", "--create", target, f"origin/{default_branch}"])

    cleanup_removed = 0
    try:
        for path in policy["cleanup_on_switch"]:
            cleanup_removed += int(_remove_cleanup_path(repo, path))
    except (OSError, GitLifecycleError) as exc:
        return ({"issue": issue_number, "branch": _current_branch(repo), "switched": True,
                 "cleanup_paths_removed": cleanup_removed, "hooks_run": 0,
                 "failure": {"stage": "cleanup", "message": str(exc)[:256]}}, 1)

    plan = build_hook_plan(profile, "branch_switch")
    hooks_run = 0
    try:
        for step in plan.steps:
            run_command(step.command, repo)
            hooks_run += 1
    except ProcessError as exc:
        return ({"issue": issue_number, "branch": _current_branch(repo), "switched": True,
                 "cleanup_paths_removed": cleanup_removed, "hooks_run": hooks_run,
                 "failure": {"stage": "branch_switch", "message": str(exc)[:256]}}, 1)

    return ({"issue": issue_number, "branch": target, "switched": True,
             "cleanup_paths_removed": cleanup_removed, "hooks_run": hooks_run}, 0)
