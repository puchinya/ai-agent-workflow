"""Immutable Issue execution binding used to resume the same work context."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .path_safety import path_has_symlink


class ExecutionError(ValueError):
    pass


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _reject_symlink_path(path: Path) -> None:
    if path_has_symlink(path):
        raise ExecutionError("execution binding path must not traverse a symbolic link")


@dataclass(frozen=True)
class ExecutionBinding:
    repository: str
    issue_number: int
    adc_comment_id: int
    adc_sha256: str
    base_ref: str
    base_sha: str
    work_directory: str
    initial_head_sha: str

    def validate(self) -> "ExecutionBinding":
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository):
            raise ExecutionError("execution repository must be owner/name")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise ExecutionError("execution Issue number must be positive")
        if type(self.adc_comment_id) is not int or self.adc_comment_id < 1:
            raise ExecutionError("execution ADC comment ID must be positive")
        if not isinstance(self.adc_sha256, str) or not SHA256.fullmatch(self.adc_sha256):
            raise ExecutionError("execution ADC SHA-256 is invalid")
        invalid_ref_chars = ("\x00", "\r", "\n", " ", "~", "^", ":", "?", "*", "[", "\\")
        if (not isinstance(self.base_ref, str) or not self.base_ref or len(self.base_ref) > 255
                or self.base_ref.startswith(("-", "/")) or self.base_ref.endswith(("/", "."))
                or "//" in self.base_ref or ".." in self.base_ref or "@{" in self.base_ref
                or any(char in self.base_ref for char in invalid_ref_chars)
                or any(part.startswith(".") or part.endswith(".lock") for part in self.base_ref.split("/"))):
            raise ExecutionError("execution base ref is invalid")
        if not isinstance(self.base_sha, str) or not SHA40.fullmatch(self.base_sha):
            raise ExecutionError("execution base SHA must be a full lowercase commit SHA")
        if not isinstance(self.initial_head_sha, str) or not SHA40.fullmatch(self.initial_head_sha):
            raise ExecutionError("execution initial HEAD must be a full lowercase commit SHA")
        if self.initial_head_sha != self.base_sha:
            raise ExecutionError("execution initial HEAD must equal the frozen base SHA")
        if not isinstance(self.work_directory, str) or not Path(self.work_directory).is_absolute():
            raise ExecutionError("execution work directory must be an absolute path")
        return self


def binding_digest(binding: ExecutionBinding) -> str:
    binding.validate()
    return hashlib.sha256(json.dumps(binding.__dict__, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_binding(path: Path, binding: ExecutionBinding) -> None:
    binding.validate()
    destination = Path(path)
    _reject_symlink_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(destination)
    data = (json.dumps(binding.__dict__, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            try:
                # A hard link publishes the fully written file atomically without
                # replacing an existing Issue binding on retries or concurrent runs.
                os.link(temporary, destination)
            except FileExistsError:
                if destination.is_symlink():
                    raise ExecutionError("execution binding path must not be a symbolic link")
                if read_binding(destination) != binding:
                    raise ExecutionError("execution binding is frozen and cannot be replaced")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def read_binding(path: Path) -> ExecutionBinding:
    location = Path(path)
    _reject_symlink_path(location)
    try:
        data: Any = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"execution binding is missing or invalid: {exc}") from exc
    expected = {
        "repository", "issue_number", "adc_comment_id", "adc_sha256", "base_ref",
        "base_sha", "work_directory", "initial_head_sha",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ExecutionError("execution binding must contain exactly the Schema 1 fields")
    binding = ExecutionBinding(**data)
    return binding.validate()
