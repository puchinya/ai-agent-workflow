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


@dataclass(frozen=True)
class AdoptedExecutionEpoch:
    """Prospective Issue #63 epoch; deliberately not an ExecutionBinding V1.

    The observed PR start and selected base are separate facts. This record
    never claims that the current PR head was the original execution start.
    """

    repository: str
    issue_number: int
    adc_comment_id: int
    adc_sha256: str
    pr_number: int
    pr_author_user_id: int
    selected_base_ref: str
    selected_base_sha40: str
    branch_ref: str
    observed_start_head_sha40: str
    adoption_id: str
    plan_sha256: str
    owner_decision_comment_id: int
    owner_authorization_plan_sha256: str
    approval_scope_sha256: str
    intent_comment_id: int
    applied_comment_id: int
    intent_body_sha256: str
    applied_body_sha256: str
    attachment_id: str
    historical_binding_provenance: str = "UNVERIFIED"
    schema: str = "PASES_EXECUTION_ADOPTION_V1"

    def validate(self) -> "AdoptedExecutionEpoch":
        if self.schema != "PASES_EXECUTION_ADOPTION_V1":
            raise ExecutionError("adopted execution epoch schema is unsupported")
        if (self.repository != "puchinya/ai-agent-workflow" or self.issue_number != 63
                or self.pr_number != 64 or type(self.pr_author_user_id) is not int
                or self.pr_author_user_id < 1):
            raise ExecutionError("adopted execution epoch is restricted to repository #63 / PR #64")
        if type(self.adc_comment_id) is not int or self.adc_comment_id < 1:
            raise ExecutionError("adopted epoch ADC comment ID is invalid")
        if type(self.owner_decision_comment_id) is not int or self.owner_decision_comment_id < 1:
            raise ExecutionError("adopted epoch owner decision comment ID is invalid")
        if any(type(value) is not int or value < 1 for value in (self.intent_comment_id, self.applied_comment_id)):
            raise ExecutionError("adopted epoch journal comment ID is invalid")
        if not isinstance(self.adc_sha256, str) or not SHA256.fullmatch(self.adc_sha256):
            raise ExecutionError("adopted epoch ADC digest is invalid")
        if not isinstance(self.plan_sha256, str) or not SHA256.fullmatch(self.plan_sha256):
            raise ExecutionError("adopted epoch plan digest is invalid")
        if (not isinstance(self.owner_authorization_plan_sha256, str)
                or not SHA256.fullmatch(self.owner_authorization_plan_sha256)):
            raise ExecutionError("adopted epoch owner authorization plan digest is invalid")
        if not isinstance(self.approval_scope_sha256, str) or not SHA256.fullmatch(self.approval_scope_sha256):
            raise ExecutionError("adopted epoch owner approval scope digest is invalid")
        if (not isinstance(self.intent_body_sha256, str) or not SHA256.fullmatch(self.intent_body_sha256)
                or not isinstance(self.applied_body_sha256, str) or not SHA256.fullmatch(self.applied_body_sha256)):
            raise ExecutionError("adopted epoch journal digest is invalid")
        if (not isinstance(self.adoption_id, str) or not SHA256.fullmatch(self.adoption_id)
                or not isinstance(self.attachment_id, str) or not SHA256.fullmatch(self.attachment_id)):
            raise ExecutionError("adopted epoch identity digest is invalid")
        if (not isinstance(self.selected_base_sha40, str) or not SHA40.fullmatch(self.selected_base_sha40)
                or not isinstance(self.observed_start_head_sha40, str)
                or not SHA40.fullmatch(self.observed_start_head_sha40)):
            raise ExecutionError("adopted epoch observed Git commit is invalid")
        if self.historical_binding_provenance != "UNVERIFIED":
            raise ExecutionError("adopted epoch must preserve unverified historical provenance")
        invalid_ref_chars = ("\x00", "\r", "\n", " ", "~", "^", ":", "?", "*", "[", "\\")
        for name, value in (("base", self.selected_base_ref), ("branch", self.branch_ref)):
            if (not isinstance(value, str) or not value or len(value) > 255
                    or value.startswith(("-", "/")) or value.endswith(("/", ".")) or "//" in value
                    or ".." in value or "@{" in value or any(char in value for char in invalid_ref_chars)
                    or any(part.startswith(".") or part.endswith(".lock") for part in value.split("/"))):
                raise ExecutionError(f"adopted epoch {name} ref is invalid")
        if self.branch_ref.casefold() in {"main", "master"} or self.branch_ref == self.selected_base_ref:
            raise ExecutionError("adopted epoch branch must be distinct from its selected base")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "adc_comment_id": self.adc_comment_id,
            "adc_sha256": self.adc_sha256,
            "adoption_id": self.adoption_id,
            "applied_body_sha256": self.applied_body_sha256,
            "applied_comment_id": self.applied_comment_id,
            "attachment_id": self.attachment_id,
            "branch_ref": self.branch_ref,
            "historical_binding_provenance": self.historical_binding_provenance,
            "intent_body_sha256": self.intent_body_sha256,
            "intent_comment_id": self.intent_comment_id,
            "issue_number": self.issue_number,
            "observed_start_head_sha40": self.observed_start_head_sha40,
            "owner_decision_comment_id": self.owner_decision_comment_id,
            "owner_authorization_plan_sha256": self.owner_authorization_plan_sha256,
            "approval_scope_sha256": self.approval_scope_sha256,
            "plan_sha256": self.plan_sha256,
            "pr_number": self.pr_number,
            "pr_author_user_id": self.pr_author_user_id,
            "repository": self.repository,
            "schema": self.schema,
            "selected_base_ref": self.selected_base_ref,
            "selected_base_sha40": self.selected_base_sha40,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.payload(), sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False).encode("utf-8")).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["epoch_sha256"] = self.sha256
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False) + "\n").encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "AdoptedExecutionEpoch":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutionError("adopted execution epoch is not valid UTF-8 JSON") from exc
        if not isinstance(value, dict) or set(value) != {
                "adc_comment_id", "adc_sha256", "adoption_id", "applied_body_sha256", "applied_comment_id",
                "attachment_id", "branch_ref", "epoch_sha256", "historical_binding_provenance",
                "intent_body_sha256", "intent_comment_id", "issue_number", "observed_start_head_sha40",
                "owner_decision_comment_id", "owner_authorization_plan_sha256", "approval_scope_sha256", "plan_sha256",
                "pr_number", "pr_author_user_id", "repository", "schema",
                "selected_base_ref", "selected_base_sha40"}:
            raise ExecutionError("adopted execution epoch has unknown or missing fields")
        supplied = value.pop("epoch_sha256")
        epoch = cls(**value).validate()
        if supplied != epoch.sha256 or epoch.to_bytes() != raw:
            raise ExecutionError("adopted execution epoch digest or canonical bytes do not match")
        return epoch


@dataclass(frozen=True)
class WorkspaceAttachment:
    """Local-only attachment of a logical adopted epoch to this physical checkout."""

    repository: str
    issue_number: int
    adoption_id: str
    attachment_id: str
    branch_ref: str
    work_directory: str
    schema: str = "PASES_WORKSPACE_ATTACH_V1"

    def validate(self) -> "WorkspaceAttachment":
        if (self.schema != "PASES_WORKSPACE_ATTACH_V1" or self.repository != "puchinya/ai-agent-workflow"
                or self.issue_number != 63 or not SHA256.fullmatch(self.adoption_id)
                or not SHA256.fullmatch(self.attachment_id)):
            raise ExecutionError("workspace attachment identity is invalid")
        if not isinstance(self.work_directory, str) or not Path(self.work_directory).is_absolute():
            raise ExecutionError("workspace attachment path must be absolute and local")
        if not isinstance(self.branch_ref, str) or not self.branch_ref:
            raise ExecutionError("workspace attachment branch is invalid")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "adoption_id": self.adoption_id, "attachment_id": self.attachment_id,
            "branch_ref": self.branch_ref, "issue_number": self.issue_number,
            "repository": self.repository, "schema": self.schema,
            "work_directory": self.work_directory,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.payload(), sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False).encode("utf-8")).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["attachment_sha256"] = self.sha256
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False) + "\n").encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "WorkspaceAttachment":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutionError("workspace attachment is not valid UTF-8 JSON") from exc
        if not isinstance(value, dict) or set(value) != {
                "adoption_id", "attachment_id", "attachment_sha256", "branch_ref", "issue_number",
                "repository", "schema", "work_directory"}:
            raise ExecutionError("workspace attachment has unknown or missing fields")
        supplied = value.pop("attachment_sha256")
        attachment = cls(**value).validate()
        if supplied != attachment.sha256 or attachment.to_bytes() != raw:
            raise ExecutionError("workspace attachment digest or canonical bytes do not match")
        return attachment


ExecutionIdentity = ExecutionBinding | AdoptedExecutionEpoch


def execution_identity_base(identity: ExecutionIdentity) -> tuple[str, str]:
    if isinstance(identity, ExecutionBinding):
        return identity.base_ref, identity.base_sha
    if isinstance(identity, AdoptedExecutionEpoch):
        identity.validate()
        return identity.selected_base_ref, identity.selected_base_sha40
    raise ExecutionError("execution identity type is unsupported")


def execution_identity_context_id(identity: ExecutionIdentity) -> str:
    if isinstance(identity, ExecutionBinding):
        return f"execution-binding:{binding_digest(identity)}"
    if isinstance(identity, AdoptedExecutionEpoch):
        return f"execution-adoption:{identity.sha256}"
    raise ExecutionError("execution identity type is unsupported")


def binding_digest(binding: ExecutionBinding) -> str:
    binding.validate()
    return hashlib.sha256(json.dumps(binding.__dict__, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def execution_identity_digest(identity: ExecutionIdentity) -> str:
    if isinstance(identity, ExecutionBinding):
        return binding_digest(identity)
    if isinstance(identity, AdoptedExecutionEpoch):
        return identity.sha256
    raise ExecutionError("execution identity type is unsupported")


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
