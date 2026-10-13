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
    branch_ref: str
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
        if (not isinstance(self.branch_ref, str) or not self.branch_ref or len(self.branch_ref) > 255
                or self.branch_ref.startswith(("-", "/")) or self.branch_ref.endswith(("/", "."))
                or "//" in self.branch_ref or ".." in self.branch_ref or "@{" in self.branch_ref
                or any(char in self.branch_ref for char in invalid_ref_chars)
                or any(part.startswith(".") or part.endswith(".lock") for part in self.branch_ref.split("/"))):
            raise ExecutionError("execution branch ref is invalid")
        if self.branch_ref.casefold() in {"main", "master"} or self.branch_ref == self.base_ref:
            raise ExecutionError("execution branch must be a dedicated Issue branch, not its base")
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


def _binding_rows(path: Path, *, legacy_branch_ref: str | None = None) -> list[ExecutionBinding]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"execution binding is missing or invalid: {exc}") from exc
    if isinstance(data, dict) and set(data) == {"schema", "bindings"}:
        if data.get("schema") != "PASES_EXECUTION_BINDING_HISTORY_V1" or not isinstance(data.get("bindings"), list):
            raise ExecutionError("execution binding history schema is invalid")
        rows = data["bindings"]
    else:
        rows = [data]
    if not rows:
        raise ExecutionError("execution binding history cannot be empty")
    expected = {
        "repository", "issue_number", "adc_comment_id", "adc_sha256", "base_ref", "base_sha",
        "branch_ref", "work_directory", "initial_head_sha",
    }
    legacy_expected = expected - {"branch_ref"}
    bindings: list[ExecutionBinding] = []
    for row in rows:
        if (isinstance(row, dict) and set(row) == legacy_expected
                and isinstance(legacy_branch_ref, str) and legacy_branch_ref):
            row = {**row, "branch_ref": legacy_branch_ref}
        if not isinstance(row, dict) or set(row) != expected:
            raise ExecutionError("execution binding must contain exactly the current Schema 1 fields")
        bindings.append(ExecutionBinding(**row).validate())
    if len(bindings) > 1 or (isinstance(data, dict) and set(data) == {"schema", "bindings"}):
        frozen_fields = (
            "repository", "issue_number", "base_ref", "base_sha", "branch_ref",
            "work_directory", "initial_head_sha",
        )
        first = bindings[0]
        if any(any(getattr(binding, field) != getattr(first, field) for field in frozen_fields)
               for binding in bindings[1:]):
            raise ExecutionError("execution binding history conflicts with its frozen work identity")
        generation_ids = [binding.adc_comment_id for binding in bindings]
        if len(generation_ids) != len(set(generation_ids)):
            raise ExecutionError("execution binding history contains a duplicate ADC generation")
    return bindings


def write_binding(path: Path, binding: ExecutionBinding) -> None:
    binding.validate()
    destination = Path(path)
    _reject_symlink_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(destination)
    lock = destination.with_name(destination.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ExecutionError("execution binding is being updated concurrently") from exc
    try:
        _reject_symlink_path(lock)
        wrapper = False
        if destination.exists():
            try:
                existing = json.loads(destination.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ExecutionError(f"execution binding is missing or invalid: {exc}") from exc
            wrapper = (isinstance(existing, dict)
                       and set(existing) == {"schema", "bindings"}
                       and existing.get("schema") == "PASES_EXECUTION_BINDING_HISTORY_V1")
        current = _binding_rows(destination, legacy_branch_ref=binding.branch_ref) if destination.exists() else []
        if current and current[-1] == binding and wrapper:
            return
        migrating_exact = bool(current and current[-1] == binding)
        if current and not migrating_exact:
            latest = current[-1]
            frozen = ("repository", "issue_number", "base_ref", "base_sha", "branch_ref",
                      "work_directory", "initial_head_sha")
            if any(getattr(latest, key) != getattr(binding, key) for key in frozen):
                raise ExecutionError("execution binding is frozen and cannot be replaced")
            if any(row.adc_comment_id == binding.adc_comment_id for row in current):
                raise ExecutionError("execution binding generation is duplicated or conflicts")
        rows = [row.__dict__ for row in (current if migrating_exact else [*current, binding])]
        data = (json.dumps({"schema": "PASES_EXECUTION_BINDING_HISTORY_V1", "bindings": rows},
                           sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        temporary = Path(name)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        os.close(lock_fd)
        lock.unlink(missing_ok=True)


def read_binding(path: Path, *, legacy_branch_ref: str | None = None) -> ExecutionBinding:
    location = Path(path)
    _reject_symlink_path(location)
    return _binding_rows(location, legacy_branch_ref=legacy_branch_ref)[-1]


def read_binding_history(path: Path) -> tuple[ExecutionBinding, ...]:
    location = Path(path)
    _reject_symlink_path(location)
    return tuple(_binding_rows(location))
