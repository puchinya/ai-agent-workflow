"""Create-only work checkpoints and PR binding snapshots for resumable work."""

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


class CheckpointError(ValueError):
    pass


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REF_INVALID = set("\x00\r\n ~^:?*[\\")
STAGES = {"base", "branch", "bind", "recover", "pr", "verification", "audit", "readiness"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CheckpointError(f"{label} must be non-empty text")
    return value.strip()


def _digest(value: Any, label: str, pattern: re.Pattern[str] = SHA256) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise CheckpointError(f"{label} has an invalid digest")
    return value


def _reject_symlink_path(path: Path, label: str) -> None:
    if path_has_symlink(path):
        raise CheckpointError(f"{label} must not traverse a symbolic link")


def validate_ref(value: Any) -> str:
    ref = _text(value, "Git branch ref")
    if (len(ref) > 255 or ref.startswith(("-", "/")) or ref.endswith(("/", ".")) or "//" in ref
            or ".." in ref or "@{" in ref or any(char in REF_INVALID for char in ref)
            or any(part.startswith(".") or part.endswith(".lock") for part in ref.split("/"))):
        raise CheckpointError("Git branch ref is invalid")
    return ref


@dataclass(frozen=True)
class PRBinding:
    repository: str
    issue_number: int
    adc_comment_id: int
    adc_sha256: str
    base_sha40: str
    branch_ref: str
    pr_number: int
    pr_head_sha40: str

    def validate(self) -> "PRBinding":
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository):
            raise CheckpointError("PRBinding repository must be owner/name")
        for value, label in (
            (self.issue_number, "PRBinding Issue number"),
            (self.adc_comment_id, "PRBinding ADC Comment ID"),
            (self.pr_number, "PRBinding PR number"),
        ):
            if type(value) is not int or value < 1:
                raise CheckpointError(f"{label} must be positive")
        _digest(self.adc_sha256, "PRBinding ADC SHA-256")
        _digest(self.base_sha40, "PRBinding base SHA", SHA40)
        _digest(self.pr_head_sha40, "PRBinding PR HEAD", SHA40)
        validate_ref(self.branch_ref)
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "adc_comment_id": self.adc_comment_id,
            "adc_sha256": self.adc_sha256,
            "base_sha40": self.base_sha40,
            "branch_ref": self.branch_ref,
            "issue_number": self.issue_number,
            "pr_head_sha40": self.pr_head_sha40,
            "pr_number": self.pr_number,
            "repository": self.repository,
            "schema": "PASES_PR_BINDING_V1",
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["pr_binding_sha256"] = self.sha256
        return _canonical(value) + b"\n"


@dataclass(frozen=True)
class WorkCheckpoint:
    execution_binding_sha256: str
    current_head_sha40: str
    worktree_clean: bool
    completed_stage: str
    artifact_digests: tuple[tuple[str, str], ...]
    step: int

    def validate(self) -> "WorkCheckpoint":
        _digest(self.execution_binding_sha256, "Checkpoint ExecutionBinding digest")
        _digest(self.current_head_sha40, "Checkpoint current HEAD", SHA40)
        if type(self.worktree_clean) is not bool:
            raise CheckpointError("Checkpoint worktree_clean must be boolean")
        if not isinstance(self.completed_stage, str) or self.completed_stage not in STAGES:
            raise CheckpointError("Checkpoint completed_stage is unknown")
        if type(self.step) is not int or self.step < 1:
            raise CheckpointError("Checkpoint step must be positive")
        if type(self.artifact_digests) is not tuple:
            raise CheckpointError("Checkpoint artifact_digests must be a tuple")
        names: list[str] = []
        for item in self.artifact_digests:
            if type(item) is not tuple or len(item) != 2:
                raise CheckpointError("Checkpoint artifact digest entries must be (name, sha256)")
            name, digest = item
            names.append(_text(name, "Checkpoint artifact name"))
            _digest(digest, f"Checkpoint artifact digest for {name}")
        if names != sorted(names) or len(names) != len(set(names)):
            raise CheckpointError("Checkpoint artifact digests must have sorted unique names")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "artifact_digests": [{"name": name, "sha256": digest} for name, digest in self.artifact_digests],
            "completed_stage": self.completed_stage,
            "current_head_sha40": self.current_head_sha40,
            "execution_binding_sha256": self.execution_binding_sha256,
            "schema": "PASES_WORK_CHECKPOINT_V1",
            "step": self.step,
            "worktree_clean": self.worktree_clean,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["checkpoint_sha256"] = self.sha256
        return _canonical(value) + b"\n"


def checkpoint_path(work_directory: Path, issue_number: int, step: int) -> Path:
    if type(issue_number) is not int or issue_number < 1 or type(step) is not int or step < 1:
        raise CheckpointError("Checkpoint Issue and step must be positive integers")
    root = Path(work_directory)
    if not root.is_absolute():
        raise CheckpointError("Checkpoint work directory must be absolute")
    return root / ".p_ases" / "state" / str(issue_number) / f"checkpoint-{step:06d}.json"


def read_pr_binding(path: Path) -> PRBinding:
    location = Path(path)
    _reject_symlink_path(location, "PRBinding path")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointError("PRBinding is missing or invalid JSON") from exc
    expected = {
        "adc_comment_id", "adc_sha256", "base_sha40", "branch_ref", "issue_number",
        "pr_binding_sha256", "pr_head_sha40", "pr_number", "repository", "schema",
    }
    if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_PR_BINDING_V1":
        raise CheckpointError("PRBinding has unknown/missing fields or schema")
    binding = PRBinding(
        repository=value["repository"], issue_number=value["issue_number"],
        adc_comment_id=value["adc_comment_id"], adc_sha256=value["adc_sha256"],
        base_sha40=value["base_sha40"], branch_ref=value["branch_ref"],
        pr_number=value["pr_number"], pr_head_sha40=value["pr_head_sha40"],
    ).validate()
    if value["pr_binding_sha256"] != binding.sha256 or binding.to_bytes() != raw:
        raise CheckpointError("PRBinding digest or canonical byte representation does not match")
    return binding


def write_pr_binding(path: Path, binding: PRBinding) -> str:
    """Create the PRBinding once; conflicting retries never replace it."""
    binding.validate()
    destination = Path(path)
    _reject_symlink_path(destination, "PRBinding path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(destination, "PRBinding path")
    data = binding.to_bytes()
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != data:
                raise CheckpointError("PRBinding already exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise CheckpointError("Could not atomically store PRBinding") from exc
    if read_pr_binding(destination) != binding:
        raise CheckpointError("PRBinding readback changed")
    return binding.sha256


def read_checkpoint(path: Path) -> WorkCheckpoint:
    location = Path(path)
    _reject_symlink_path(location, "Checkpoint path")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointError("Checkpoint is missing or invalid JSON") from exc
    expected = {
        "artifact_digests", "checkpoint_sha256", "completed_stage", "current_head_sha40",
        "execution_binding_sha256", "schema", "step", "worktree_clean",
    }
    if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_WORK_CHECKPOINT_V1":
        raise CheckpointError("Checkpoint has unknown/missing fields or schema")
    if not isinstance(value["artifact_digests"], list):
        raise CheckpointError("Checkpoint artifact_digests must be an array")
    artifacts = []
    for item in value["artifact_digests"]:
        if not isinstance(item, dict) or set(item) != {"name", "sha256"}:
            raise CheckpointError("Checkpoint artifact digest has unknown/missing fields")
        artifacts.append((item["name"], item["sha256"]))
    checkpoint = WorkCheckpoint(
        execution_binding_sha256=value["execution_binding_sha256"],
        current_head_sha40=value["current_head_sha40"], worktree_clean=value["worktree_clean"],
        completed_stage=value["completed_stage"], artifact_digests=tuple(artifacts), step=value["step"],
    ).validate()
    if value["checkpoint_sha256"] != checkpoint.sha256 or checkpoint.to_bytes() != raw:
        raise CheckpointError("Checkpoint digest or canonical bytes do not match")
    return checkpoint


def write_checkpoint(path: Path, checkpoint: WorkCheckpoint) -> str:
    """Persist one immutable step; identical retries reuse it, changed bytes conflict."""
    checkpoint.validate()
    destination = Path(path)
    _reject_symlink_path(destination, "Checkpoint path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(destination, "Checkpoint path")
    data = checkpoint.to_bytes()
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != data:
                raise CheckpointError("Checkpoint step already exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise CheckpointError("Could not atomically store Checkpoint") from exc
    if read_checkpoint(destination) != checkpoint:
        raise CheckpointError("Checkpoint readback changed")
    return checkpoint.sha256
