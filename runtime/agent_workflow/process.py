"""Sequential execution of trusted, explicitly configured local hook commands."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_DIAGNOSTIC_BYTES = 16 * 1024
_SENSITIVE_NAME = re.compile(r"(?i)(?:TOKEN|SECRET|PASS(?:WORD)?|CREDENTIAL|API[_-]?KEY|AUTHORIZATION|PRIVATE[_-]?KEY)")
_SENSITIVE_PAIR = re.compile(
    r"(?i)(\b(?:access[_-]?token|api[_-]?key|authorization|client[_-]?secret|credential|password|secret|token)\s*[:=]\s*)"
    r"(?:\"([^\"]*)\"|'([^']*)'|([^\s,;]+))"
)
_TOKEN_PATTERNS = (
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class ProcessError(RuntimeError):
    def __init__(self, message: str, returncode: int = 1, diagnostic: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class ProcessResult:
    command: str
    returncode: int


def _command_label(command: str) -> str:
    """Name the executable without echoing user-supplied arguments or paths."""
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return "shell command"
    for part in parts:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", part):
            continue
        label = Path(part).name
        return label if re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", label) else "configured executable"
    return "shell command"


def _secret_values(command: str) -> list[str]:
    values: set[str] = set()
    for name, value in os.environ.items():
        if _SENSITIVE_NAME.search(name) and value:
            values.add(value)
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        parts = []
    for index, part in enumerate(parts):
        name, separator, value = part.partition("=")
        if separator and _SENSITIVE_NAME.search(name) and value:
            values.add(value)
            continue
        if re.fullmatch(r"(?i)--?(?:access[-_]?token|api[-_]?key|authorization|client[-_]?secret|credential|password|secret|token)", part):
            if index + 1 < len(parts) and parts[index + 1]:
                values.add(parts[index + 1])
            continue
        match = re.fullmatch(r"(?i)--?(?:access[-_]?token|api[-_]?key|authorization|client[-_]?secret|credential|password|secret|token)=(.+)", part)
        if match and match.group(1):
            values.add(match.group(1))
    return sorted(values, key=len, reverse=True)


def _redact(text: str, secrets: list[str]) -> str:
    for value in secrets:
        text = text.replace(value, "[REDACTED]")
    text = re.sub(r"(?i)(\bAuthorization\s*[:=]\s*)(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+",
                  r"\1[REDACTED]", text)
    text = _SENSITIVE_PAIR.sub(lambda match: match.group(1) + "[REDACTED]", text)
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}", r"\1 [REDACTED]", text)
    text = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                  "[REDACTED PRIVATE KEY]", text, flags=re.S)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return _ANSI.sub("", text)


def _read_tail(stream: Any, limit: int, was_truncated: bool) -> str:
    stream.flush()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(max(0, size - limit), os.SEEK_SET)
    data = stream.read(limit)
    text = data.decode("utf-8", errors="replace")
    if was_truncated and size > limit:
        newline = text.find("\n")
        if newline < 0:
            return "[diagnostic omitted: long unterminated line]\n"
        text = text[newline + 1:]
    return text


def _diagnostic_tail(stdout_file: Any, stderr_file: Any, secrets: list[str]) -> str:
    largest_secret = max((len(value.encode("utf-8", errors="ignore")) for value in secrets), default=0)
    if largest_secret > 65536:
        return "[diagnostic output omitted: oversized credential value]"
    read_limit = MAX_DIAGNOSTIC_BYTES + largest_secret + 1024
    output = _read_tail(stdout_file, read_limit, True)
    error = _read_tail(stderr_file, read_limit, True)
    parts = []
    if output:
        parts.append("stdout:\n" + output)
    if error:
        parts.append("stderr:\n" + error)
    text = _redact("\n".join(parts), secrets)
    text = "".join(char for char in text if char in "\n\r\t" or ord(char) >= 32)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > MAX_DIAGNOSTIC_BYTES:
        text = encoded[-MAX_DIAGNOSTIC_BYTES:].decode("utf-8", errors="ignore")
    return text


def _failure(command: str, returncode: int, diagnostic: str = "") -> ProcessError:
    message = f"hook command {_command_label(command)!r} exited with status {returncode}"
    if diagnostic:
        message += "\n" + diagnostic
    return ProcessError(message, returncode, diagnostic)


def run_command(command: str, cwd: Path, diagnostic: bool = False) -> ProcessResult:
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise ProcessError("configured hook command must be a non-empty string")
    actual = command
    interpreter = re.match(r"^(\s*)(python3?)(?=\s|$)", actual)
    if interpreter and shutil.which(interpreter.group(2)) is None:
        alternate = "python3" if interpreter.group(2) == "python" else "python"
        if shutil.which(alternate):
            start, end = interpreter.span(2)
            actual = actual[:start] + alternate + actual[end:]
    if not diagnostic:
        try:
            completed = subprocess.run(actual, cwd=cwd, shell=True, check=False,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise ProcessError(f"hook command {_command_label(actual)!r} could not start") from exc
        if completed.returncode:
            raise _failure(actual, completed.returncode)
        return ProcessResult(actual, completed.returncode)

    captures: list[tuple[str, Any]] = []
    try:
        stdout_file = tempfile.NamedTemporaryFile(mode="w+b", prefix="agent-workflow-hook-stdout-",
                                                  suffix=".tmp", delete=False)
        captures.append((stdout_file.name, stdout_file))
        stderr_file = tempfile.NamedTemporaryFile(mode="w+b", prefix="agent-workflow-hook-stderr-",
                                                  suffix=".tmp", delete=False)
        captures.append((stderr_file.name, stderr_file))
        completed = subprocess.run(actual, cwd=cwd, shell=True, check=False,
                                   stdout=stdout_file, stderr=stderr_file)
        if completed.returncode:
            tail = _diagnostic_tail(stdout_file, stderr_file, _secret_values(actual))
            raise _failure(actual, completed.returncode, tail)
        return ProcessResult(actual, completed.returncode)
    except ProcessError:
        raise
    except OSError as exc:
        raise ProcessError(f"hook command {_command_label(actual)!r} could not start") from exc
    finally:
        for name, stream in captures:
            try:
                stream.close()
            finally:
                try:
                    os.unlink(name)
                except FileNotFoundError:
                    pass
