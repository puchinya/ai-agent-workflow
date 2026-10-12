"""Bounded argv-only process execution with redacted output and explicit outcomes."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class ProcessError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessResult:
    status: str
    exit_status: int | None
    stdout: str
    stderr: str
    output_truncated: bool
    reason: str | None = None

    def validate(self) -> "ProcessResult":
        if self.status not in {"completed", "timed_out", "cancelled", "start_failed"}:
            raise ProcessError("process result status is unknown")
        if self.status == "completed" and type(self.exit_status) is not int:
            raise ProcessError("completed process result requires an exit status")
        if self.status != "completed" and self.exit_status is not None:
            raise ProcessError("incomplete process result cannot claim an exit status")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise ProcessError("process output must be text")
        if type(self.output_truncated) is not bool:
            raise ProcessError("process output_truncated must be boolean")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason):
            raise ProcessError("process result reason must be non-empty text")
        return self


def run_process(
    argv: Iterable[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    cancel_event: threading.Event | None = None,
    secrets: Iterable[str] = (),
    max_output_bytes: int = 262144,
) -> ProcessResult:
    """Run a bounded command without a shell; output capture is capped and redacted."""
    if isinstance(argv, (str, bytes)):
        raise ProcessError("process command must be an argv sequence, not a shell string")
    command = tuple(argv)
    if not command or any(not isinstance(part, str) or not part or "\x00" in part for part in command):
        raise ProcessError("process argv must contain non-empty NUL-free strings")
    location = Path(os.path.abspath(cwd))
    if not location.is_dir() or location.is_symlink():
        raise ProcessError("process cwd must be an existing non-symlink directory")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not 0.05 <= float(timeout_seconds) <= 600):
        raise ProcessError("process timeout must be between 0.05 and 600 seconds")
    if type(max_output_bytes) is not int or not 0 <= max_output_bytes <= 4 * 1024 * 1024:
        raise ProcessError("process output limit must be between zero and four MiB")
    redactions = tuple(sorted({secret for secret in secrets if isinstance(secret, str) and secret},
                              key=len, reverse=True))
    if cancel_event is not None and not isinstance(cancel_event, threading.Event):
        raise ProcessError("cancel_event must be a threading.Event")
    try:
        launch: dict[str, object] = {}
        if os.name == "posix":
            launch["start_new_session"] = True
        elif os.name == "nt":
            launch["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        child = subprocess.Popen(command, cwd=location, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **launch)
    except OSError:
        return ProcessResult("start_failed", None, "", "", False, "process could not be started").validate()

    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"value": False}
    lock = threading.Lock()

    def drain(name: str, stream) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            with lock:
                room = max_output_bytes - len(buffers[name])
                if room > 0:
                    buffers[name].extend(chunk[:room])
                if len(chunk) > max(room, 0):
                    truncated["value"] = True

    readers = [threading.Thread(target=drain, args=(name, stream), daemon=True)
               for name, stream in (("stdout", child.stdout), ("stderr", child.stderr))]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + float(timeout_seconds)
    status = "completed"
    reason = None

    def terminate_group(*, force: bool) -> None:
        try:
            if os.name == "posix":
                os.killpg(child.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif force:
                child.kill()
            else:
                child.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
        except (OSError, ProcessLookupError):
            pass

    while child.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            status, reason = "cancelled", "process cancelled by caller"
            terminate_group(force=False)
            break
        if time.monotonic() >= deadline:
            status, reason = "timed_out", "process exceeded its time limit"
            terminate_group(force=False)
            break
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    if child.poll() is None:
        try:
            child.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            terminate_group(force=True)
            child.wait()
    for reader in readers:
        reader.join(timeout=1.0)
    if any(reader.is_alive() for reader in readers):
        terminate_group(force=True)
        for stream in (child.stdout, child.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for reader in readers:
            reader.join(timeout=1.0)
    for stream in (child.stdout, child.stderr):
        if stream is not None and not stream.closed:
            stream.close()

    def decode(name: str) -> str:
        value = bytes(buffers[name]).decode("utf-8", errors="replace")
        for secret in redactions:
            value = value.replace(secret, "[REDACTED]")
        return value

    return ProcessResult(
        status=status, exit_status=child.returncode if status == "completed" else None,
        stdout=decode("stdout"), stderr=decode("stderr"),
        output_truncated=truncated["value"], reason=reason,
    ).validate()
