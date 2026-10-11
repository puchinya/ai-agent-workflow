"""Artifact-specific Acceptance decisions over subject-bound observations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable

from .evidence_store import VerificationSubject
from .verification import GateResult, VERDICTS


class AcceptanceError(ValueError):
    pass


ARTIFACT_TYPES = {
    "spec_change", "design_change", "bug_fix", "documentation_only",
    "formatting_only", "test_improvement", "feature_manual",
}
OBSERVATION_KINDS = {
    "acceptance_criteria", "red_before", "green_after", "link_validation",
    "semantic_unchanged", "oracle_validation", "manual_verification",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


@dataclass(frozen=True)
class AcceptanceResult:
    artifact_type: str
    status: str
    subject: VerificationSubject
    evidence_sha256s: tuple[str, ...]
    reasons: tuple[str, ...]

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
        if (self.status == "PASS" and self.reasons) or (self.status != "PASS" and not self.reasons):
            raise AcceptanceError("Acceptance result status and explanation reasons are inconsistent")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {
            "artifact_type": self.artifact_type,
            "evidence_sha256s": list(self.evidence_sha256s),
            "reasons": list(self.reasons),
            "schema": "PASES_ACCEPTANCE_RESULT_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()


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
    elif artifact_type == "feature_manual":
        require("manual_verification")

    digests = tuple(sorted({row.evidence_sha256 for row in rows if row.subject == subject}))
    blocking = any("FAIL" in reason for reason in reasons)
    only_concerns = bool(reasons) and all("status is CONCERNS" in reason for reason in reasons)
    status = "FAIL" if blocking else ("CONCERNS" if only_concerns else ("BLOCKED" if reasons else "PASS"))
    return AcceptanceResult(artifact_type, status, subject, digests, tuple(reasons)).validate()
