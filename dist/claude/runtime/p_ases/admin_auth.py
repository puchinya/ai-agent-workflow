"""Explicit, short-lived isolated GitHub administration sessions.

Admin access is available only through a locally confirmed, interactive
``isolated-gh-device`` login and a private temporary ``GH_CONFIG_DIR``. The
route does not change normal ``gh`` authentication, and authentication is not
an owner decision or a strong OS sandbox.
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from .github import GitHub
from .local_execution import (
    LocalExecutionError, require_local_activation_execution, verified_device_admin_session,
)


class AdminAuthError(ValueError):
    """Temporary administrator identity or terminal is unavailable."""


ADMIN_AUTH_MODES = ("isolated-gh-device",)
ADMIN_REPOSITORY = "puchinya/ai-agent-workflow"
_TOKEN_ENV_VARS = (
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
)


def _interactive_terminal(stdin: Any) -> Any:
    terminal = sys.stdin if stdin is None else stdin
    try:
        interactive = bool(terminal.isatty())
    except (AttributeError, OSError, ValueError):
        interactive = False
    if not interactive:
        raise AdminAuthError("ADMIN_AUTH_INTERACTIVE_REQUIRED")
    return terminal


def _device_terminal(stdin: Any) -> Any:
    try:
        terminal = _interactive_terminal(stdin)
        visible_output = any(
            bool(stream.isatty()) for stream in (sys.stdout, sys.stderr)
            if callable(getattr(stream, "isatty", None))
        )
    except (AdminAuthError, OSError, ValueError):
        visible_output = False
        terminal = None
    if terminal is None or not visible_output:
        raise AdminAuthError("ADMIN_DEVICE_LOGIN_UNAVAILABLE: local interactive device-code terminal is unavailable")
    return terminal


def _without_ambient_tokens() -> dict[str, str]:
    child_env = os.environ.copy()
    for name in _TOKEN_ENV_VARS:
        child_env.pop(name, None)
    return child_env


def _install_sigterm_cleanup_handler() -> Any:
    try:
        previous = signal.getsignal(signal.SIGTERM)

        def terminate(signum: int, _frame: Any) -> None:
            raise AdminAuthError(
                f"ADMIN_DEVICE_LOGIN_UNAVAILABLE: interrupted by signal {signum}; temporary config cleanup attempted"
            )

        signal.signal(signal.SIGTERM, terminate)
        return previous
    except (OSError, ValueError) as exc:
        raise AdminAuthError("ADMIN_DEVICE_LOGIN_UNAVAILABLE: cannot install cleanup handler") from exc


def _remove_private_config(config_dir: Path) -> None:
    try:
        if config_dir.is_symlink():
            config_dir.unlink()
        elif config_dir.exists():
            shutil.rmtree(config_dir)
    except OSError as exc:
        raise AdminAuthError("ADMIN_DEVICE_LOGIN_UNAVAILABLE: temporary config cleanup failed") from exc


def _secure_private_config(config_dir: Path) -> None:
    if os.name != "posix":
        raise AdminAuthError(
            "ADMIN_DEVICE_LOGIN_UNAVAILABLE: this host cannot guarantee mode-0700 GitHub CLI config"
        )
    os.chmod(config_dir, stat.S_IRWXU)
    if stat.S_IMODE(config_dir.stat().st_mode) != stat.S_IRWXU:
        raise AdminAuthError(
            "ADMIN_DEVICE_LOGIN_UNAVAILABLE: this host cannot guarantee mode-0700 GitHub CLI config"
        )


def _run_device_login(argv: list[str], *, env: dict[str, str], terminal: Any) -> int:
    process = subprocess.Popen(argv, env=env, stdin=terminal, stdout=None, stderr=None)
    try:
        return process.wait()
    except BaseException:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise


@contextmanager
def _isolated_device_client(
    repo: str, terminal: Any, *, github_factory: Callable[[str], GitHub],
) -> Iterator[GitHub]:
    """Yield a device-authenticated client whose gh state is private to this command."""
    if repo != ADMIN_REPOSITORY:
        raise AdminAuthError("temporary Admin is limited to the configured repository")

    previous_sigterm = _install_sigterm_cleanup_handler()
    config_dir: Path | None = None
    atexit_cleanup: Callable[[], None] | None = None
    github: GitHub | None = None
    primary_error = False
    try:
        try:
            config_dir = Path(tempfile.mkdtemp(prefix="pases-admin-gh-"))
            _secure_private_config(config_dir)
        except OSError as exc:
            raise AdminAuthError(
                "ADMIN_DEVICE_LOGIN_UNAVAILABLE: could not create private GitHub CLI config"
            ) from exc
        atexit_cleanup = lambda: _remove_private_config(config_dir)  # noqa: E731
        atexit.register(atexit_cleanup)

        child_env = _without_ambient_tokens()
        child_env["GH_CONFIG_DIR"] = str(config_dir)
        argv = [
            "gh", "auth", "login", "--hostname", "github.com", "--web",
            "--git-protocol", "https", "--insecure-storage",
        ]
        try:
            returncode = _run_device_login(argv, env=child_env, terminal=terminal)
        except (OSError, KeyboardInterrupt, AdminAuthError) as exc:
            raise AdminAuthError("ADMIN_DEVICE_LOGIN_UNAVAILABLE: isolated device login did not complete") from exc
        if returncode != 0:
            raise AdminAuthError("ADMIN_DEVICE_LOGIN_UNAVAILABLE: isolated device login did not complete")

        github = github_factory(repo)
        if not isinstance(github, GitHub):
            raise AdminAuthError("Admin GitHub factory returned an invalid client")
        github._admin_config_dir = str(config_dir)
        try:
            with verified_device_admin_session(github):
                yield github
        except LocalExecutionError as exc:
            raise AdminAuthError(str(exc)) from exc
    except BaseException:
        primary_error = True
        raise
    finally:
        if github is not None:
            github._admin_config_dir = None
        cleanup_error: BaseException | None = None
        if config_dir is not None:
            try:
                _remove_private_config(config_dir)
            except BaseException as exc:  # cleanup must still restore the caller's signal state
                cleanup_error = exc
            if atexit_cleanup is not None:
                atexit.unregister(atexit_cleanup)
        try:
            signal.signal(signal.SIGTERM, previous_sigterm)
        except (OSError, ValueError):
            if cleanup_error is None:
                cleanup_error = AdminAuthError("ADMIN_DEVICE_LOGIN_UNAVAILABLE: cannot restore signal handler")
        if cleanup_error is not None and not primary_error:
            raise cleanup_error


@contextmanager
def temporary_admin_client(
    repo: str, *, stdin: Any = None,
    github_factory: Callable[[str], GitHub] = GitHub,
    auth_mode: str = "isolated-gh-device",
) -> Iterator[GitHub]:
    """Yield an isolated client in the selected authentication mode.

    ``isolated-gh-device`` is the only supported route. It uses the local
    interactive terminal and stores GitHub CLI auth only below a new mode-0700
    config directory. Device login failure blocks without a credential fallback.
    """
    if repo != ADMIN_REPOSITORY:
        raise AdminAuthError("temporary Admin is limited to the configured repository")
    if auth_mode not in ADMIN_AUTH_MODES:
        raise AdminAuthError("ADMIN_AUTH_MODE_UNAVAILABLE: only isolated-gh-device is permitted")
    try:
        require_local_activation_execution()
    except LocalExecutionError as exc:
        raise AdminAuthError(str(exc)) from exc
    terminal = _device_terminal(stdin)
    with _isolated_device_client(repo, terminal, github_factory=github_factory) as github:
        yield github
