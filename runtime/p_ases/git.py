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
