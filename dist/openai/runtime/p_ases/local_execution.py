"""Operational locality guard for live Activation V2 operations.

This confirms an owner-controlled interactive host by explicit operator
attestation. It is intentionally an operational trust check, not host
attestation or cryptographic proof.
"""
from __future__ import annotations

import contextvars
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping


class LocalExecutionError(ValueError):
    """Live Activation must stop because local operator control is unverified."""


_CONFIRMATION = "I CONTROL THIS LOCAL HOST"
_AUTHORIZED = contextvars.ContextVar("pases_local_activation_authorized", default=False)
_ACTIVE_ADMIN_CLIENT = contextvars.ContextVar("pases_active_admin_client", default=None)
_REMOTE_MARKERS = (
    "CODEX_ENVIRONMENT_ID", "CODEX_EXEC_SERVER_REMOTE_BASE_URL", "CODEX_CLOUD",
    "CODESPACE_NAME", "CODESPACES", "CLAUDE_CODE_REMOTE", "CLAUDE_CODE_REMOTE_CONTROL",
    "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "CIRCLECI", "JENKINS_URL",
    "TF_BUILD", "TEAMCITY_VERSION", "CI", "SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY",
    "REMOTEHOST", "GITPOD_WORKSPACE_ID", "REMOTE_CONTAINERS",
)


def _set(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().casefold() not in {
        "0", "false", "no", "off", "none",
    }


def locality_blockers(env: Mapping[str, str], *, stdin_tty: bool, stdout_tty: bool,
                      stderr_tty: bool) -> tuple[str, ...]:
    """Return stable blockers for the host facts, without consulting agent identity."""
    blockers = [f"REMOTE_OR_HOSTED_CONTEXT:{name}" for name in _REMOTE_MARKERS if _set(env.get(name))]
    if not stdin_tty or not (stdout_tty or stderr_tty):
        blockers.append("LOCAL_INTERACTIVE_TERMINAL_REQUIRED")
    return tuple(blockers)


def require_local_activation_execution() -> None:
    """Require a clean locality check and an explicit same-terminal confirmation."""
    try:
        input_tty = bool(sys.stdin.isatty())
        output_tty = bool(sys.stdout.isatty())
        error_tty = bool(sys.stderr.isatty())
    except (AttributeError, OSError, ValueError):
        input_tty = output_tty = error_tty = False
    blockers = locality_blockers(os.environ, stdin_tty=input_tty,
                                 stdout_tty=output_tty, stderr_tty=error_tty)
    if blockers:
        raise LocalExecutionError("LOCAL_ACTIVATION_CONTEXT_BLOCKED: " + ", ".join(blockers))
    if _AUTHORIZED.get():
        return
    try:
        answer = input(
            "Live Activation requires an owner-controlled local terminal. "
            f"Type '{_CONFIRMATION}' to confirm: "
        )
    except (EOFError, KeyboardInterrupt, OSError) as exc:
        raise LocalExecutionError("LOCAL_ACTIVATION_OPERATOR_CONFIRMATION_UNAVAILABLE") from exc
    if answer.strip() != _CONFIRMATION:
        raise LocalExecutionError("LOCAL_ACTIVATION_OPERATOR_CONFIRMATION_REQUIRED")
    _AUTHORIZED.set(True)


def _require_private_device_config(github: Any) -> None:
    config = getattr(github, "_admin_config_dir", None)
    if not isinstance(config, str) or not config:
        raise LocalExecutionError("ADMIN_DEVICE_AUTH_REQUIRED: Admin reads need isolated-gh-device")
    path = Path(config)
    try:
        mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        if path.is_symlink() or not path.is_dir() or mode != stat.S_IRWXU:
            raise LocalExecutionError("ADMIN_DEVICE_AUTH_REQUIRED: GH_CONFIG_DIR must be private mode 0700")
    except OSError as exc:
        raise LocalExecutionError("ADMIN_DEVICE_AUTH_REQUIRED: private GH_CONFIG_DIR is unavailable") from exc


@contextmanager
def verified_device_admin_session(github: Any) -> Iterator[None]:
    """Mark only a device-authenticated, owner-verified Admin client as active."""
    if getattr(github, "repo", None) != "puchinya/ai-agent-workflow":
        raise LocalExecutionError("ADMIN_DEVICE_AUTH_REQUIRED: Admin session targets another repository")
    if getattr(github, "_admin_token_override", None) is not None:
        raise LocalExecutionError("ADMIN_DEVICE_AUTH_REQUIRED: token fallback is disabled")
    _require_private_device_config(github)
    try:
        actor = github.authenticated_user()
    except Exception as exc:
        raise LocalExecutionError("ADMIN_DEVICE_AUTH_REQUIRED: authenticated owner readback failed") from exc
    if (not isinstance(actor, dict) or actor.get("id") != 3744776 or actor.get("type") != "User"):
        raise LocalExecutionError("ADMIN_DEVICE_AUTH_REQUIRED: authenticated identity is not the repository owner")
    token = _ACTIVE_ADMIN_CLIENT.set(id(github))
    try:
        yield
    finally:
        _ACTIVE_ADMIN_CLIENT.reset(token)


def require_isolated_device_admin_client(github: Any) -> None:
    """Require an active session created after isolated device login and owner readback."""
    if _ACTIVE_ADMIN_CLIENT.get() != id(github):
        raise LocalExecutionError("ADMIN_DEVICE_AUTH_REQUIRED: client is outside its verified device session")
    _require_private_device_config(github)
