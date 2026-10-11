"""Immutable exact-subject verification evidence records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EvidenceError(ValueError):
    pass


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OUTCOMES = {"PASS", "FAIL", "SKIPPED", "FLAKY", "BLOCKED"}
RUNNERS = {"local", "github-actions", "manual"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _positive(value: Any, label: str) -> None:
    if type(value) is not int or value < 1:
        raise EvidenceError(f"{label} must be positive")


def _sha(value: Any, label: str, pattern: re.Pattern[str] = SHA256) -> None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise EvidenceError(f"{label} has an invalid digest")


@dataclass(frozen=True)
class VerificationSubject:
    repository: str
    issue_number: int
    pr_number: int
    adc_comment_id: int
    adc_sha256: str
    plan_sha256: str
    pr_head_sha40: str

    def validate(self) -> "VerificationSubject":
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository):
            raise EvidenceError("Verification subject repository must be owner/name")
        _positive(self.issue_number, "Verification subject Issue number")
        _positive(self.pr_number, "Verification subject PR number")
        _positive(self.adc_comment_id, "Verification subject ADC Comment ID")
        _sha(self.adc_sha256, "Verification subject ADC SHA-256")
        _sha(self.plan_sha256, "Verification subject Plan SHA-256")
        _sha(self.pr_head_sha40, "Verification subject PR HEAD", SHA40)
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "adc_comment_id": self.adc_comment_id,
            "adc_sha256": self.adc_sha256,
            "issue_number": self.issue_number,
            "plan_sha256": self.plan_sha256,
            "pr_head_sha40": self.pr_head_sha40,
            "pr_number": self.pr_number,
            "repository": self.repository,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()

    @classmethod
    def from_dict(cls, value: Any) -> "VerificationSubject":
        expected = {
            "adc_comment_id", "adc_sha256", "issue_number", "plan_sha256",
            "pr_head_sha40", "pr_number", "repository",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise EvidenceError("Verification subject has unknown or missing fields")
        return cls(**value).validate()


@dataclass(frozen=True)
class EvidenceRecord:
    subject: VerificationSubject
    entry_key: str
    evidence_type: str
    command: tuple[str, ...]
    manual_procedure: str
    environment: str
    runner_source: str
    observed_at: str
    outcome: str
    exit_status: int | None
    output_sha256: str

    def validate(self) -> "EvidenceRecord":
        if not isinstance(self.subject, VerificationSubject):
            raise EvidenceError("Evidence subject must be a VerificationSubject")
        self.subject.validate()
        for value, label in (
            (self.entry_key, "Evidence Plan entry key"),
            (self.evidence_type, "Evidence type"),
            (self.environment, "Evidence environment"),
            (self.observed_at, "Evidence timestamp"),
        ):
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise EvidenceError(f"{label} must be non-empty text")
        if type(self.command) is not tuple or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in self.command):
            raise EvidenceError("Evidence command must be a tuple of argv strings")
        if not isinstance(self.manual_procedure, str):
            raise EvidenceError("Evidence manual_procedure must be text")
        manual = self.manual_procedure.strip()
        if bool(self.command) == bool(manual):
            raise EvidenceError("Evidence must identify exactly one command or manual procedure")
        if not isinstance(self.runner_source, str) or self.runner_source not in RUNNERS:
            raise EvidenceError("Evidence runner_source is unknown")
        if not isinstance(self.outcome, str) or self.outcome not in OUTCOMES:
            raise EvidenceError("Evidence outcome is unknown")
        try:
            observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceError("Evidence timestamp must be ISO-8601 UTC") from exc
        if observed.tzinfo is None or observed.utcoffset() != timezone.utc.utcoffset(observed):
            raise EvidenceError("Evidence timestamp must be timezone-aware UTC")
        if not (self.observed_at.endswith("Z") or self.observed_at.endswith("+00:00")):
            raise EvidenceError("Evidence timestamp must be encoded as UTC")
        if self.exit_status is not None and type(self.exit_status) is not int:
            raise EvidenceError("Evidence exit_status must be an integer or null")
        _sha(self.output_sha256, "Evidence output SHA-256")
        if self.runner_source == "manual" and self.command:
            raise EvidenceError("Manual evidence cannot claim a spawned command")
        if self.runner_source != "manual" and self.manual_procedure:
            raise EvidenceError("Command evidence cannot claim a manual procedure")
        if self.runner_source == "manual" and self.exit_status is not None:
            raise EvidenceError("Manual evidence cannot claim a process exit status")
        if self.runner_source != "manual" and self.exit_status is None:
            raise EvidenceError("Command Evidence must record its exit status")
        if self.outcome == "PASS" and self.exit_status not in {0, None}:
            raise EvidenceError("Passing command Evidence must record exit status zero")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "command": list(self.command),
            "entry_key": self.entry_key,
            "evidence_type": self.evidence_type.strip(),
            "environment": self.environment,
            "manual_procedure": self.manual_procedure.strip(),
            "observed_at": self.observed_at,
            "outcome": self.outcome,
            "output_sha256": self.output_sha256,
            "runner_source": self.runner_source,
            "schema": "PASES_VERIFICATION_EVIDENCE_V1",
            "subject": self.subject.as_dict(),
            "exit_status": self.exit_status,
        }

    @property
    def evidence_sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["evidence_sha256"] = self.evidence_sha256
        return _canonical(value) + b"\n"


def read_evidence(path: Path) -> EvidenceRecord:
    location = Path(path)
    if location.is_symlink():
        raise EvidenceError("Evidence path must not be a symbolic link")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("Evidence record is missing or invalid JSON") from exc
    expected = {
        "command", "entry_key", "environment", "evidence_sha256", "evidence_type", "exit_status", "manual_procedure",
        "observed_at", "outcome", "output_sha256", "runner_source", "schema", "subject",
    }
    if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_VERIFICATION_EVIDENCE_V1":
        raise EvidenceError("Evidence record has unknown/missing fields or schema")
    if not isinstance(value["command"], list):
        raise EvidenceError("Evidence command must be an array")
    record = EvidenceRecord(
        subject=VerificationSubject.from_dict(value["subject"]), entry_key=value["entry_key"],
        evidence_type=value["evidence_type"],
        command=tuple(value["command"]), manual_procedure=value["manual_procedure"],
        environment=value["environment"], runner_source=value["runner_source"],
        observed_at=value["observed_at"], outcome=value["outcome"], exit_status=value["exit_status"],
        output_sha256=value["output_sha256"],
    ).validate()
    if value["evidence_sha256"] != record.evidence_sha256 or record.to_bytes() != raw:
        raise EvidenceError("Evidence digest or canonical byte representation does not match")
    return record


def write_evidence(path: Path, record: EvidenceRecord) -> str:
    """Create an immutable record; identical retries are idempotent, collisions fail."""
    record.validate()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise EvidenceError("Evidence path must not be a symbolic link")
    # A symlinked parent could redirect a durable record outside the workspace.
    parent = destination.parent
    while parent != parent.parent:
        if parent.is_symlink():
            raise EvidenceError("Evidence directory path must not contain a symbolic link")
        parent = parent.parent
    data = record.to_bytes()
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
                raise EvidenceError("Evidence identity already exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise EvidenceError("Could not atomically store Evidence record") from exc
    readback = read_evidence(destination)
    if readback != record:
        raise EvidenceError("Evidence record readback changed")
    return record.evidence_sha256
