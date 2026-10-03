"""Sequential execution of trusted, explicitly configured local hook commands."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ProcessError(RuntimeError):
    def __init__(self, message: str, returncode: int = 1):
        super().__init__(message)
        self.returncode = returncode


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


def run_command(command: str, cwd: Path) -> ProcessResult:
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise ProcessError("configured hook command must be a non-empty string")
    actual = command
    interpreter = re.match(r"^(\s*)(python3?)(?=\s|$)", actual)
    if interpreter and shutil.which(interpreter.group(2)) is None:
        alternate = "python3" if interpreter.group(2) == "python" else "python"
        if shutil.which(alternate):
            start, end = interpreter.span(2)
            actual = actual[:start] + alternate + actual[end:]
    try:
        completed = subprocess.run(actual, cwd=cwd, shell=True, check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise ProcessError(f"configured hook command could not start: {exc}") from exc
    if completed.returncode:
        # Identify the executable without echoing user-provided arguments or child output.
        raise ProcessError(f"hook command {_command_label(actual)!r} exited with status {completed.returncode}",
                           completed.returncode)
    return ProcessResult(actual, completed.returncode)
