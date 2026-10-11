"""Git identity helpers. Git subprocesses stay behind this module."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run_git(repo: Path, *args: str) -> str:
    if any(not isinstance(arg, str) or "\x00" in arg for arg in args):
        raise GitError("git arguments must be NUL-free strings")
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, check=False, text=True, encoding="utf-8",
            errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise GitError(f"could not start git: {exc}") from exc
    if result.returncode:
        # Git stderr may contain remote URLs with credentials.
        raise GitError(f"git {' '.join(args[:2])} failed (exit status {result.returncode})")
    return result.stdout.strip()


def discover_repository(repo: Path) -> str:
    """Return the GitHub owner/name from origin without exposing the remote URL."""
    try:
        url = run_git(repo, "remote", "get-url", "origin")
    except GitError as exc:
        raise GitError("could not identify the origin repository") from exc
    match = re.search(r"(?:github\.com[:/])([^/\s:]+/[^/\s]+?)(?:\.git)?$", url, re.I)
    if not match:
        raise GitError("origin is not a recognizable GitHub repository")
    return match.group(1)


def current_branch(repo: Path) -> str:
    ref = run_git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not ref:
        raise GitError("worktree is detached")
    return ref


def head_sha40(repo: Path) -> str:
    value = run_git(repo, "rev-parse", "--verify", "HEAD^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise GitError("Git HEAD readback is not a full SHA-40")
    return value


def worktree_clean(repo: Path) -> bool:
    return run_git(repo, "status", "--porcelain", "--untracked-files=all") == ""


def remote_branch_sha(repo: Path, branch_ref: str, remote: str = "origin") -> str:
    if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
        raise GitError("Git remote name is invalid")
    if (not isinstance(branch_ref, str) or not branch_ref or branch_ref.startswith("-")
            or any(char in branch_ref for char in "\x00\r\n ~^:?*[\\")):
        raise GitError("Git branch ref is invalid")
    output = run_git(repo, "ls-remote", "--heads", remote, f"refs/heads/{branch_ref}")
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if (len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != f"refs/heads/{branch_ref}"
            or not re.fullmatch(r"[0-9a-f]{40}", rows[0][0])):
        raise GitError("remote branch readback is missing, ambiguous, or malformed")
    return rows[0][0]


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    for value, label in ((ancestor, "ancestor"), (descendant, "descendant")):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            raise GitError(f"Git {label} must be a full SHA-40")
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=repo,
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise GitError("could not start git ancestry check") from exc
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise GitError("git ancestry check failed")


def branch_exists(repo: Path, branch_ref: str) -> bool:
    if not isinstance(branch_ref, str) or not branch_ref:
        raise GitError("Git branch ref is invalid")
    return bool(run_git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{branch_ref}"))


def switch_branch(repo: Path, branch_ref: str) -> None:
    if not isinstance(branch_ref, str) or not branch_ref or branch_ref.startswith("-"):
        raise GitError("Git branch ref is invalid")
    run_git(repo, "switch", branch_ref)


def create_branch(repo: Path, branch_ref: str, start_sha40: str) -> None:
    if not isinstance(branch_ref, str) or not branch_ref or branch_ref.startswith("-"):
        raise GitError("Git branch ref is invalid")
    if not isinstance(start_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", start_sha40):
        raise GitError("branch start point must be a full SHA-40")
    run_git(repo, "switch", "--create", branch_ref, start_sha40)
