"""Artifact-specific Acceptance decisions over subject-bound observations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .evidence_store import VerificationSubject
from .verification import GateResult, VERDICTS


class AcceptanceError(ValueError):
    pass


ARTIFACT_TYPES = {
    "spec_change", "design_change", "bug_fix", "documentation_only",
    "formatting_only", "test_improvement", "feature_gui", "feature_e2e", "feature_manual",
}
ACCEPTANCE_POLICY_VERSION = "PASES_ARTIFACT_ACCEPTANCE_V1"
OBSERVATION_KINDS = {
    "acceptance_criteria", "red_before", "green_after", "link_validation",
    "semantic_unchanged", "oracle_validation", "gui_verification", "e2e_verification",
    "manual_verification",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _reject_symlink_path(path: Path, label: str, *, parent_count: int = 3) -> None:
    location = Path(os.path.abspath(path))
    candidates = [location]
    parent = location
    for _ in range(parent_count):
        if parent == parent.parent:
            break
        parent = parent.parent
        candidates.append(parent)
    for candidate in candidates:
        if candidate.is_symlink():
            raise AcceptanceError(f"{label} must not traverse a symbolic link")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class AcceptanceObservation:
    kind: str
    subject: VerificationSubject
    observed_revision_sha40: str
    outcome: str
    evidence_sha256: str
    reference: str

    def validate(self) -> "AcceptanceObservation":
        if not isinstance(self.kind, str) or self.kind not in OBSERVATION_KINDS:
            raise AcceptanceError("Acceptance observation kind is unknown")
        if not isinstance(self.subject, VerificationSubject):
            raise AcceptanceError("Acceptance observation requires an exact Verification subject")
        self.subject.validate()
        if not isinstance(self.observed_revision_sha40, str) or not SHA40.fullmatch(self.observed_revision_sha40):
            raise AcceptanceError("Acceptance observation revision must be a full SHA-40")
        if not isinstance(self.outcome, str) or self.outcome not in {"PASS", "FAIL", "BLOCKED", "CONCERNS"}:
            raise AcceptanceError("Acceptance observation outcome is unknown")
        if not isinstance(self.evidence_sha256, str) or not SHA256.fullmatch(self.evidence_sha256):
            raise AcceptanceError("Acceptance observation requires a SHA-256 evidence digest")
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise AcceptanceError("Acceptance observation requires an evidence reference")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "evidence_sha256": self.evidence_sha256,
            "kind": self.kind,
            "observed_revision_sha40": self.observed_revision_sha40,
            "outcome": self.outcome,
            "reference": self.reference,
            "subject": self.subject.as_dict(),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "AcceptanceObservation":
        expected = {"evidence_sha256", "kind", "observed_revision_sha40", "outcome", "reference", "subject"}
        if not isinstance(value, dict) or set(value) != expected:
            raise AcceptanceError("Acceptance observation has unknown or missing fields")
        return cls(
            kind=value["kind"], subject=VerificationSubject.from_dict(value["subject"]),
            observed_revision_sha40=value["observed_revision_sha40"], outcome=value["outcome"],
            evidence_sha256=value["evidence_sha256"], reference=value["reference"],
        ).validate()


@dataclass(frozen=True)
class AcceptanceResult:
    artifact_type: str
    status: str
    subject: VerificationSubject
    evidence_sha256s: tuple[str, ...]
    reasons: tuple[str, ...]
    observations: tuple[AcceptanceObservation, ...] = ()
    baseline_sha40: str | None = None
    verification_result_sha256: str | None = None

    def validate(self) -> "AcceptanceResult":
        if not isinstance(self.artifact_type, str) or self.artifact_type not in ARTIFACT_TYPES:
            raise AcceptanceError("Acceptance result artifact type is unknown")
        if not isinstance(self.status, str) or self.status not in VERDICTS:
            raise AcceptanceError("Acceptance result status is unknown")
        self.subject.validate()
        if (type(self.evidence_sha256s) is not tuple
                or any(not isinstance(item, str) or not SHA256.fullmatch(item) for item in self.evidence_sha256s)):
            raise AcceptanceError("Acceptance result evidence digests are invalid")
        if self.evidence_sha256s != tuple(sorted(set(self.evidence_sha256s))):
            raise AcceptanceError("Acceptance result evidence digests must be sorted and unique")
        if type(self.reasons) is not tuple or any(not isinstance(item, str) or not item for item in self.reasons):
            raise AcceptanceError("Acceptance result reasons are invalid")
        if type(self.observations) is not tuple or any(not isinstance(row, AcceptanceObservation) for row in self.observations):
            raise AcceptanceError("Acceptance result observations are invalid")
        for row in self.observations:
            row.validate()
            if row.subject != self.subject:
                raise AcceptanceError("Acceptance result contains an observation for another exact subject")
        if self.evidence_sha256s != tuple(sorted({row.evidence_sha256 for row in self.observations})):
            raise AcceptanceError("Acceptance result digest set differs from its frozen observations")
        if self.baseline_sha40 is not None and (
            not isinstance(self.baseline_sha40, str) or not SHA40.fullmatch(self.baseline_sha40)
        ):
            raise AcceptanceError("Acceptance result baseline SHA-40 is invalid")
        if self.verification_result_sha256 is not None and (
            not isinstance(self.verification_result_sha256, str)
            or not SHA256.fullmatch(self.verification_result_sha256)
        ):
            raise AcceptanceError("Acceptance result Verification digest is invalid")
        if (self.status == "PASS" and self.reasons) or (self.status != "PASS" and not self.reasons):
            raise AcceptanceError("Acceptance result status and explanation reasons are inconsistent")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {
            "artifact_type": self.artifact_type,
            "baseline_sha40": self.baseline_sha40,
            "policy_version": ACCEPTANCE_POLICY_VERSION,
            "evidence_sha256s": list(self.evidence_sha256s),
            "observations": [row.as_dict() for row in self.observations],
            "reasons": list(self.reasons),
            "schema": "PASES_ACCEPTANCE_RESULT_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
            "verification_result_sha256": self.verification_result_sha256,
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "artifact_type": self.artifact_type,
            "baseline_sha40": self.baseline_sha40,
            "evidence_sha256s": list(self.evidence_sha256s),
            "observations": [row.as_dict() for row in self.observations],
            "policy_version": ACCEPTANCE_POLICY_VERSION,
            "reasons": list(self.reasons),
            "schema": "PASES_ACCEPTANCE_RESULT_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
            "verification_result_sha256": self.verification_result_sha256,
        }

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["result_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    def as_json(self) -> dict[str, Any]:
        value = self.payload()
        value["result_sha256"] = self.sha256
        value["subject_sha256"] = self.subject.sha256
        return value

    @classmethod
    def from_bytes(cls, raw: bytes) -> "AcceptanceResult":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AcceptanceError("Acceptance result is not valid UTF-8 JSON") from exc
        expected = {
            "artifact_type", "baseline_sha40", "evidence_sha256s", "observations", "policy_version",
            "reasons", "result_sha256", "schema", "status", "subject", "verification_result_sha256",
        }
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_ACCEPTANCE_RESULT_V1"
                or value.get("policy_version") != ACCEPTANCE_POLICY_VERSION):
            raise AcceptanceError("Acceptance result has unknown/missing fields or policy version")
        if (not isinstance(value["evidence_sha256s"], list) or not isinstance(value["observations"], list)
                or not isinstance(value["reasons"], list)):
            raise AcceptanceError("Acceptance result arrays have an invalid shape")
        result = cls(
            artifact_type=value["artifact_type"], status=value["status"],
            subject=VerificationSubject.from_dict(value["subject"]),
            evidence_sha256s=tuple(value["evidence_sha256s"]), reasons=tuple(value["reasons"]),
            observations=tuple(AcceptanceObservation.from_dict(row) for row in value["observations"]),
            baseline_sha40=value["baseline_sha40"],
            verification_result_sha256=value["verification_result_sha256"],
        ).validate()
        if value["result_sha256"] != result.sha256 or result.to_bytes() != raw:
            raise AcceptanceError("Acceptance result digest or canonical bytes do not match")
        return result


def _gate(name: str, gate: GateResult | None, subject: VerificationSubject, reasons: list[str]) -> None:
    if not isinstance(gate, GateResult):
        reasons.append(f"required {name} result is missing")
        return
    try:
        gate.validate()
    except (ValueError, TypeError) as exc:
        reasons.append(f"{name} result is invalid: {exc}")
        return
    if gate.subject != subject:
        reasons.append(f"{name} result is missing or belongs to a different exact subject")
    elif gate.status != "PASS":
        reasons.append(f"{name} status is {gate.status}")


def evaluate_acceptance(
    *,
    artifact_type: str,
    subject: VerificationSubject,
    required_req_ids: Iterable[str],
    mapped_req_ids: Iterable[str],
    verification: GateResult | None,
    oracle_trace: GateResult | None,
    observations: Iterable[AcceptanceObservation] = (),
    baseline_sha40: str | None = None,
    verification_result_sha256: str | None = None,
) -> AcceptanceResult:
    """Evaluate the pinned artifact classes without treating missing proof as PASS."""
    if not isinstance(subject, VerificationSubject):
        raise AcceptanceError("Acceptance requires an exact Verification subject")
    subject.validate()
    if not isinstance(artifact_type, str) or artifact_type not in ARTIFACT_TYPES:
        raise AcceptanceError("Acceptance artifact type is unknown")
    required = tuple(required_req_ids)
    mapped = tuple(mapped_req_ids)
    reasons: list[str] = []
    if not required or any(not isinstance(req, str) or not re.fullmatch(r"REQ-[0-9]+", req) for req in required):
        reasons.append("normative requirement set is missing or invalid")
    if len(set(required)) != len(required):
        reasons.append("normative requirement set contains duplicates")
    if len(set(mapped)) != len(mapped) or set(required) != set(mapped):
        missing, extra = sorted(set(required) - set(mapped)), sorted(set(mapped) - set(required))
        if missing:
            reasons.append("missing REQ mappings: " + ", ".join(missing))
        if extra:
            reasons.append("unexpected REQ mappings: " + ", ".join(extra))
    _gate("Verification", verification, subject, reasons)
    _gate("Oracle trace", oracle_trace, subject, reasons)

    rows = tuple(observations)
    if any(not isinstance(row, AcceptanceObservation) for row in rows):
        reasons.append("Acceptance observations contain a malformed record")
        rows = tuple(row for row in rows if isinstance(row, AcceptanceObservation))
    for row in rows:
        try:
            row.validate()
        except AcceptanceError as exc:
            reasons.append(str(exc))
            continue
        if row.subject != subject:
            reasons.append("Acceptance observation belongs to a different exact subject")
    allowed_kinds = {
        "spec_change": {"acceptance_criteria"},
        "design_change": {"acceptance_criteria"},
        "bug_fix": {"red_before", "green_after"},
        "documentation_only": {"link_validation", "acceptance_criteria"},
        "formatting_only": {"link_validation", "semantic_unchanged"},
        "test_improvement": {"oracle_validation"},
        "feature_gui": {"gui_verification"},
        "feature_e2e": {"e2e_verification"},
        "feature_manual": {"manual_verification"},
    }[artifact_type]
    if any(row.kind not in allowed_kinds for row in rows):
        reasons.append("Acceptance input contains evidence outside the artifact-specific table")
    by_kind = {kind: [row for row in rows if row.kind == kind and row.subject == subject] for kind in OBSERVATION_KINDS}

    def require(kind: str, expected: str = "PASS", revision: str | None = None) -> None:
        candidates = by_kind[kind]
        if revision is not None:
            candidates = [row for row in candidates if row.observed_revision_sha40 == revision]
        if not candidates:
            reasons.append(f"required Acceptance evidence is missing: {kind}")
            return
        if len(candidates) != 1:
            reasons.append(f"Acceptance evidence is ambiguous for {kind}")
            return
        observation = candidates[0]
        if observation.outcome != expected:
            reasons.append(f"Acceptance observation {kind} is {observation.outcome}, expected {expected}")
        if expected == "PASS" and observation.observed_revision_sha40 != subject.pr_head_sha40:
            reasons.append(f"Acceptance observation {kind} is not for the current PR HEAD")

    if artifact_type in {"spec_change", "design_change"}:
        require("acceptance_criteria")
    elif artifact_type == "bug_fix":
        if not isinstance(baseline_sha40, str) or not SHA40.fullmatch(baseline_sha40):
            reasons.append("bug-fix Acceptance requires the exact baseline commit SHA")
        elif baseline_sha40 == subject.pr_head_sha40:
            reasons.append("bug-fix baseline and current PR HEAD must differ")
        require("red_before", expected="FAIL", revision=baseline_sha40)
        require("green_after", expected="PASS", revision=subject.pr_head_sha40)
    elif artifact_type == "documentation_only":
        require("link_validation")
        require("acceptance_criteria")
    elif artifact_type == "formatting_only":
        require("link_validation")
        require("semantic_unchanged")
    elif artifact_type == "test_improvement":
        require("oracle_validation")
    elif artifact_type == "feature_gui":
        require("gui_verification")
    elif artifact_type == "feature_e2e":
        require("e2e_verification")
    elif artifact_type == "feature_manual":
        require("manual_verification")

    digests = tuple(sorted({row.evidence_sha256 for row in rows if row.subject == subject}))
    blocking = any("FAIL" in reason for reason in reasons)
    only_concerns = bool(reasons) and all("status is CONCERNS" in reason for reason in reasons)
    status = "FAIL" if blocking else ("CONCERNS" if only_concerns else ("BLOCKED" if reasons else "PASS"))
    return AcceptanceResult(
        artifact_type, status, subject, digests, tuple(reasons), rows,
        baseline_sha40, verification_result_sha256,
    ).validate()


def acceptance_result_path(root: Path, result: AcceptanceResult) -> Path:
    result.validate()
    return Path(root).absolute() / str(result.subject.issue_number) / result.subject.sha256 / f"{result.sha256}.json"


def read_acceptance_result(path: Path) -> AcceptanceResult:
    location = Path(path)
    _reject_symlink_path(location, "Acceptance result path")
    try:
        raw = location.read_bytes()
    except OSError as exc:
        raise AcceptanceError("Acceptance result is missing or unreadable") from exc
    return AcceptanceResult.from_bytes(raw)


def write_acceptance_result(path: Path, result: AcceptanceResult) -> str:
    """Persist a versioned Acceptance result without replacing prior evidence."""
    result.validate()
    destination = Path(path)
    _reject_symlink_path(destination, "Acceptance result path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(destination, "Acceptance result path")
    raw = result.to_bytes()
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != raw:
                raise AcceptanceError("Acceptance result identity exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise AcceptanceError("Could not atomically store Acceptance result") from exc
    if read_acceptance_result(destination) != result:
        raise AcceptanceError("Acceptance result readback changed")
    return result.sha256
