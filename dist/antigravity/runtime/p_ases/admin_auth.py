"""Explicit, short-lived owner-operated GitHub administration session.

The credential is obtained only from a local interactive terminal and is given
only to this GitHub client's gh-api child process. It is never an approval.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from getpass import getpass
from typing import Any, Callable, Iterator

from .github import GitHub


class AdminAuthError(ValueError):
    """Temporary administrator identity or terminal is unavailable."""


@contextmanager
def temporary_admin_client(
    repo: str, *, stdin: Any = None,
    getpass_fn: Callable[[str], str] = getpass,
    github_factory: Callable[[str], GitHub] = GitHub,
) -> Iterator[GitHub]:
    """Yield an isolated GitHub client only while a genuine local TTY is active.

    The caller still must check repository owner/admin permission and an exact
    approved plan independently. The function never saves a token.
    """
    terminal = sys.stdin if stdin is None else stdin
    try:
        interactive = bool(terminal.isatty())
    except (AttributeError, OSError, ValueError) as exc:
        raise AdminAuthError("ADMIN_AUTH_INTERACTIVE_REQUIRED") from exc
    if not interactive:
        raise AdminAuthError("ADMIN_AUTH_INTERACTIVE_REQUIRED")
    if repo != "puchinya/ai-agent-workflow":
        raise AdminAuthError("temporary Admin is limited to the configured repository")
    try:
        token = getpass_fn("Repository-scoped temporary Admin PAT: ")
    except (EOFError, KeyboardInterrupt, OSError) as exc:
        raise AdminAuthError("ADMIN_AUTH_CANCELLED") from exc
    if (not isinstance(token, str) or not token or
            any(c in token for c in "\r\n\x00")):
        raise AdminAuthError("ADMIN_AUTH_INVALID")
    github: GitHub | None = None
    try:
        github = github_factory(repo)
        if not isinstance(github, GitHub):
            raise AdminAuthError("Admin GitHub factory returned an invalid client")
        github._admin_token_override = token
        yield github
    finally:
        if github is not None:
            github._admin_token_override = None
        token = ""
