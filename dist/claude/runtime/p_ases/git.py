"""Git identity helpers. Git subprocesses stay behind this module."""

from __future__ import annotations

import re
import subprocess
import hashlib
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


def verify_remote_repository(repo: Path, expected_repository: str, remote: str = "origin") -> None:
    """Require every configured fetch and push URL for one remote to target a GitHub repo.

    Remote URLs are parsed only in memory and are never included in errors. This
    is useful for exact-scope operations where a distinct push URL could send
    Git objects to another repository despite a correct fetch URL.
    """
    if not isinstance(expected_repository, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected_repository):
        raise GitError("expected GitHub repository identity is invalid")
    if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
        raise GitError("Git remote name is invalid")
    try:
        fetch_urls = run_git(repo, "remote", "get-url", "--all", remote).splitlines()
        push_urls = run_git(repo, "remote", "get-url", "--push", "--all", remote).splitlines()
    except GitError as exc:
        raise GitError("could not read all configured Git remote URLs") from exc
    urls = [url.strip() for url in (*fetch_urls, *push_urls) if url.strip()]
    if not urls:
        raise GitError("Git remote has no configured fetch or push URL")
    for url in urls:
        match = re.search(r"(?:github\.com[:/])([^/\s:]+/[^/\s]+?)(?:\.git)?$", url, re.I)
        if not match or match.group(1).casefold() != expected_repository.casefold():
            raise GitError("configured Git remote does not target the pinned GitHub repository")


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


def fetch_remote_branch_exact(repo: Path, branch_ref: str, expected_sha40: str,
                              remote: str = "origin") -> str:
    """Fetch one branch ref and require it to match the preceding remote SHA read."""
    if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
        raise GitError("Git remote name is invalid")
    if (not isinstance(branch_ref, str) or not branch_ref or branch_ref.startswith("-")
            or any(char in branch_ref for char in "\x00\r\n ~^:?*[\\")):
        raise GitError("Git branch ref is invalid")
    if not isinstance(expected_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha40):
        raise GitError("expected remote branch commit must be a full SHA-40")
    run_git(repo, "fetch", "--no-tags", remote, f"refs/heads/{branch_ref}")
    fetched_sha40 = run_git(repo, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", fetched_sha40) or fetched_sha40 != expected_sha40:
        raise GitError("fetched remote branch commit differs from its observed SHA")
    return fetched_sha40


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


def remote_branch_exists(repo: Path, branch_ref: str, remote: str = "origin") -> bool:
    if (not isinstance(branch_ref, str) or not branch_ref or branch_ref.startswith("-")
            or any(char in branch_ref for char in "\x00\r\n ~^:?*[\\")):
        raise GitError("Git branch ref is invalid")
    if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
        raise GitError("Git remote name is invalid")
    output = run_git(repo, "ls-remote", "--heads", remote, f"refs/heads/{branch_ref}")
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if not rows:
        return False
    if (len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != f"refs/heads/{branch_ref}"
            or not re.fullmatch(r"[0-9a-f]{40}", rows[0][0])):
        raise GitError("remote branch readback is ambiguous or malformed")
    return True


def commit_parent_sha40(repo: Path, commit_sha40: str) -> str:
    if not isinstance(commit_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_sha40):
        raise GitError("commit ref must be a full SHA-40")
    row = run_git(repo, "rev-list", "--parents", "-n", "1", commit_sha40).split()
    if len(row) != 2 or row[0] != commit_sha40 or not re.fullmatch(r"[0-9a-f]{40}", row[1]):
        raise GitError("Activation setup commit must have exactly one parent")
    return row[1]


def commit_parents_sha40(repo: Path, commit_sha40: str) -> tuple[str, ...]:
    if not isinstance(commit_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_sha40):
        raise GitError("commit ref must be a full SHA-40")
    row = run_git(repo, "rev-list", "--parents", "-n", "1", commit_sha40).split()
    if (not row or row[0] != commit_sha40
            or any(not re.fullmatch(r"[0-9a-f]{40}", value) for value in row[1:])):
        raise GitError("commit parent readback is malformed")
    return tuple(row[1:])


def changed_paths_between(repo: Path, base_sha40: str, head_sha40: str) -> tuple[str, ...]:
    for value, label in ((base_sha40, "base"), (head_sha40, "head")):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            raise GitError(f"Git {label} ref must be a full SHA-40")
    output = run_git(repo, "diff", "--name-only", "--diff-filter=ACDMRTUXB", base_sha40, head_sha40, "--")
    return tuple(output.splitlines())


def patch_sha256_excluding_activation_profile(repo: Path, base_sha40: str, head_sha40: str) -> str:
    """Hash the exact binary patch outside the one Activation-owned profile path."""
    for value, label in ((base_sha40, "base"), (head_sha40, "head")):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            raise GitError(f"Git {label} ref must be a full SHA-40")
    try:
        result = subprocess.run(
            ["git", "diff", "--binary", base_sha40, head_sha40, "--", ".",
             ":(exclude).agent/project.json"], cwd=repo, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise GitError("could not start git patch readback") from exc
    if result.returncode:
        raise GitError("git patch readback failed")
    return hashlib.sha256(result.stdout).hexdigest()


def activation_profile_bytes_at_commit(repo: Path, commit_sha40: str) -> bytes:
    if not isinstance(commit_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_sha40):
        raise GitError("Activation setup ref must be a full SHA-40")
    try:
        result = subprocess.run(
            ["git", "show", f"{commit_sha40}:.agent/project.json"], cwd=repo, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise GitError("could not read Activation project.json from Git") from exc
    if result.returncode:
        raise GitError("Activation commit does not contain .agent/project.json")
    return result.stdout


def push_branch_exact(repo: Path, branch_ref: str, expected_sha40: str, remote: str = "origin") -> None:
    if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
        raise GitError("Git remote name is invalid")
    if (not isinstance(branch_ref, str) or not branch_ref or branch_ref.startswith("-")
            or any(char in branch_ref for char in "\x00\r\n ~^:?*[\\")):
        raise GitError("Git branch ref is invalid")
    if not isinstance(expected_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha40):
        raise GitError("expected Activation setup commit must be a full SHA-40")
    if current_branch(repo) != branch_ref or head_sha40(repo) != expected_sha40:
        raise GitError("Activation setup branch changed before push")
    run_git(repo, "push", remote, f"HEAD:refs/heads/{branch_ref}")
    actual = remote_branch_sha(repo, branch_ref, remote)
    if actual != expected_sha40:
        raise GitError("pushed Activation setup commit did not pass exact remote readback")


def commit_and_push_one_path(repo: Path, branch_ref: str, path: str, message: str) -> str:
    if path != ".agent/project.json" or not isinstance(message, str) or not message.strip():
        raise GitError("Activation setup may commit only .agent/project.json with a message")
    if current_branch(repo) != branch_ref:
        raise GitError("Activation setup branch changed before commit")
    staged = run_git(repo, "diff", "--cached", "--name-only", "--")
    unstaged = run_git(repo, "diff", "--name-only", "--")
    untracked = run_git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    changed = set(unstaged.splitlines()) | set(untracked)
    target = Path(repo) / path
    if staged or changed != {path} or target.is_symlink() or not target.is_file():
        raise GitError("Activation setup may commit only its intended project.json change")
    run_git(repo, "add", "--", path)
    staged = run_git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB")
    if staged.splitlines() != [path]:
        raise GitError("Activation setup must stage exactly .agent/project.json")
    run_git(repo, "commit", "-m", message)
    sha = head_sha40(repo)
    push_branch_exact(repo, branch_ref, sha)
    if not worktree_clean(repo):
        raise GitError("Activation setup worktree is not clean after commit and push")
    return sha


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
