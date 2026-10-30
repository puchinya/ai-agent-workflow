"""Evidence-backed self-audit and independent-review record schemas."""

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
from .path_safety import path_has_symlink
from .verification import VERDICTS


class AuditError(ValueError):
    pass


SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEVERITIES = {"A", "B", "C"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise AuditError(f"{label} must be non-empty text")
    return value.strip()


@dataclass(frozen=True)
class AuditItem:
    item_id: str
    status: str
    evidence_refs: tuple[str, ...]

    def validate(self) -> "AuditItem":
        _nonempty(self.item_id, "Audit item ID")
        if not isinstance(self.status, str) or self.status not in VERDICTS:
            raise AuditError("Audit item status is unknown")
        if type(self.evidence_refs) is not tuple or any(not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs):
            raise AuditError("Audit item must carry explicit evidence references")
        if not self.evidence_refs:
            raise AuditError("Audit item requires at least one evidence reference")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"evidence_refs": list(self.evidence_refs), "item_id": self.item_id, "status": self.status}


@dataclass(frozen=True)
class SelfAudit:
    subject: VerificationSubject
    items: tuple[AuditItem, ...]

    def validate(self, required_item_ids: Iterable[str]) -> "SelfAudit":
        self.subject.validate()
        required = tuple(required_item_ids)
        if not required or any(not isinstance(item, str) or not item.strip() for item in required):
            raise AuditError("Self-audit required item set is missing or invalid")
        if len(set(required)) != len(required):
            raise AuditError("Self-audit required item set contains duplicates")
        if type(self.items) is not tuple or not self.items:
            raise AuditError("Self-audit items are required")
        for item in self.items:
            if not isinstance(item, AuditItem):
                raise AuditError("Self-audit item has an invalid type")
            item.validate()
        ids = tuple(item.item_id for item in self.items)
        if ids != tuple(sorted(ids)) or len(set(ids)) != len(ids):
            raise AuditError("Self-audit items must be sorted and unique")
        if set(ids) != set(required):
            raise AuditError("Self-audit must cover every requirement and checklist item exactly")
        return self

    @property
    def status(self) -> str:
        statuses = {item.status for item in self.items}
        if "FAIL" in statuses:
            return "FAIL"
        if statuses & {"BLOCKED", "SKIPPED", "FLAKY"}:
            return "BLOCKED"
        if "CONCERNS" in statuses:
            return "CONCERNS"
        return "PASS" if statuses == {"PASS"} else "BLOCKED"

    @property
    def sha256(self) -> str:
        self.subject.validate()
        payload = {
            "items": [item.as_dict() for item in self.items],
            "schema": "PASES_SELF_AUDIT_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()

    def payload(self) -> dict[str, Any]:
        self.subject.validate()
        for item in self.items:
            item.validate()
        ids = tuple(item.item_id for item in self.items)
        if ids != tuple(sorted(ids)) or len(set(ids)) != len(ids):
            raise AuditError("Self-audit items must be sorted and unique")
        return {
            "items": [item.as_dict() for item in self.items],
            "schema": "PASES_SELF_AUDIT_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
        }

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["audit_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "SelfAudit":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditError("Self-audit is not valid UTF-8 JSON") from exc
        expected = {"audit_sha256", "items", "schema", "status", "subject"}
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_SELF_AUDIT_V1" or not isinstance(value.get("items"), list)):
            raise AuditError("Self-audit has unknown/missing fields or schema")
        rows = []
        for item in value["items"]:
            if not isinstance(item, dict) or set(item) != {"evidence_refs", "item_id", "status"}:
                raise AuditError("Self-audit item has unknown/missing fields")
            if not isinstance(item["evidence_refs"], list):
                raise AuditError("Self-audit evidence_refs must be an array")
            rows.append(AuditItem(item["item_id"], item["status"], tuple(item["evidence_refs"])))
        audit = cls(VerificationSubject.from_dict(value["subject"]), tuple(rows))
        audit.payload()
        if value["status"] != audit.status or value["audit_sha256"] != audit.sha256 or audit.to_bytes() != raw:
            raise AuditError("Self-audit digest or canonical bytes do not match")
        return audit


@dataclass(frozen=True)
class ReviewFinding:
    finding_id: str
    severity: str
    resolved: bool
    description: str
    evidence_ref: str

    def validate(self) -> "ReviewFinding":
        _nonempty(self.finding_id, "Review finding ID")
        if not isinstance(self.severity, str) or self.severity not in SEVERITIES:
            raise AuditError("Review finding severity must be A, B, or C")
        if type(self.resolved) is not bool:
            raise AuditError("Review finding resolved must be boolean")
        _nonempty(self.description, "Review finding description")
        _nonempty(self.evidence_ref, "Review finding evidence reference")
        return self


@dataclass(frozen=True)
class IndependentReview:
    subject: VerificationSubject
    reviewer_context_id: str
    implementation_context_id: str
    context_artifact_ref: str
    context_artifact_sha256: str
    findings: tuple[ReviewFinding, ...]
    verdict: str

    def validate(self) -> "IndependentReview":
        self.subject.validate()
        reviewer = _nonempty(self.reviewer_context_id, "Independent review context ID")
        implementation = _nonempty(self.implementation_context_id, "Implementation context ID")
        if reviewer == implementation:
            raise AuditError("Independent review must come from a separate context")
        _nonempty(self.context_artifact_ref, "Independent review context artifact")
        if not isinstance(self.context_artifact_sha256, str) or not SHA256.fullmatch(self.context_artifact_sha256):
            raise AuditError("Independent review context artifact digest is invalid")
        if type(self.findings) is not tuple:
            raise AuditError("Independent review findings must be a tuple")
        for finding in self.findings:
            if not isinstance(finding, ReviewFinding):
                raise AuditError("Independent review finding has an invalid type")
            finding.validate()
        if len({finding.finding_id for finding in self.findings}) != len(self.findings):
            raise AuditError("Independent review finding IDs must be unique")
        finding_ids = tuple(item.finding_id for item in self.findings)
        if finding_ids != tuple(sorted(finding_ids)):
            raise AuditError("Independent review findings must be in canonical ID order")
        if not isinstance(self.verdict, str) or self.verdict not in VERDICTS:
            raise AuditError("Independent review verdict is unknown")
        if self.blocking_findings and self.verdict == "PASS":
            raise AuditError("Independent review with unresolved A/B findings cannot PASS")
        return self

    @property
    def blocking_findings(self) -> tuple[ReviewFinding, ...]:
        return tuple(item for item in self.findings if item.severity in {"A", "B"} and not item.resolved)

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {
            "context_artifact_ref": self.context_artifact_ref,
            "context_artifact_sha256": self.context_artifact_sha256,
            "findings": [
                {"description": item.description, "evidence_ref": item.evidence_ref,
                 "finding_id": item.finding_id, "resolved": item.resolved, "severity": item.severity}
                for item in self.findings
            ],
            "implementation_context_id": self.implementation_context_id,
            "reviewer_context_id": self.reviewer_context_id,
            "schema": "PASES_INDEPENDENT_REVIEW_V1",
            "subject": self.subject.as_dict(),
            "verdict": self.verdict,
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "context_artifact_ref": self.context_artifact_ref,
            "context_artifact_sha256": self.context_artifact_sha256,
            "findings": [
                {"description": row.description, "evidence_ref": row.evidence_ref,
                 "finding_id": row.finding_id, "resolved": row.resolved, "severity": row.severity}
                for row in self.findings
            ],
            "implementation_context_id": self.implementation_context_id,
            "reviewer_context_id": self.reviewer_context_id,
            "schema": "PASES_INDEPENDENT_REVIEW_V1",
            "subject": self.subject.as_dict(),
            "verdict": self.verdict,
        }

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["review_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "IndependentReview":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditError("Independent review is not valid UTF-8 JSON") from exc
        expected = {
            "context_artifact_ref", "context_artifact_sha256", "findings", "implementation_context_id",
            "review_sha256", "reviewer_context_id", "schema", "subject", "verdict",
        }
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_INDEPENDENT_REVIEW_V1"
                or not isinstance(value.get("findings"), list)):
            raise AuditError("Independent review has unknown/missing fields or schema")
        findings = []
        for row in value["findings"]:
            expected_row = {"description", "evidence_ref", "finding_id", "resolved", "severity"}
            if not isinstance(row, dict) or set(row) != expected_row:
                raise AuditError("Independent review finding has unknown/missing fields")
            findings.append(ReviewFinding(row["finding_id"], row["severity"], row["resolved"],
                                          row["description"], row["evidence_ref"]))
        review = cls(
            subject=VerificationSubject.from_dict(value["subject"]),
            reviewer_context_id=value["reviewer_context_id"],
            implementation_context_id=value["implementation_context_id"],
            context_artifact_ref=value["context_artifact_ref"],
            context_artifact_sha256=value["context_artifact_sha256"],
            findings=tuple(findings), verdict=value["verdict"],
        ).validate()
        if value["review_sha256"] != review.sha256 or review.to_bytes() != raw:
            raise AuditError("Independent review digest or canonical bytes do not match")
        return review


@dataclass(frozen=True)
class IndependentReviewV2:
    """Independent Review evidence with explicit optional host provenance."""

    subject: VerificationSubject
    reviewer_context_id: str
    implementation_context_id: str
    context_artifact_ref: str
    context_artifact_sha256: str
    findings: tuple[ReviewFinding, ...]
    verdict: str
    provenance_confidence: str
    spawn_session_id: str | int | None
    reviewer_id: str | int | None
    implementation_binding_id: str | None

    def validate(self) -> "IndependentReviewV2":
        self.subject.validate()
        reviewer = _nonempty(self.reviewer_context_id, "Independent review context ID")
        implementation = _nonempty(self.implementation_context_id, "Implementation context ID")
        if reviewer == implementation:
            raise AuditError("Independent review must come from a separate context")
        _nonempty(self.context_artifact_ref, "Independent review context artifact")
        if not isinstance(self.context_artifact_sha256, str) or not SHA256.fullmatch(self.context_artifact_sha256):
            raise AuditError("Independent review context artifact digest is invalid")
        optional_ids = (
            ("spawn_session_id", self.spawn_session_id),
            ("reviewer_id", self.reviewer_id),
            ("implementation_binding_id", self.implementation_binding_id),
        )
        for label, value in optional_ids:
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise AuditError(f"Independent review {label} must be a non-empty string, positive integer, or null")
            if isinstance(value, str) and (not value.strip() or value != value.strip() or "\x00" in value):
                raise AuditError(f"Independent review {label} must be a non-empty canonical value")
            if isinstance(value, int) and value < 1:
                raise AuditError(f"Independent review {label} must be positive")
        if (self.implementation_binding_id is not None
                and self.implementation_binding_id != implementation):
            raise AuditError("Independent review implementation binding ID does not match the current context")
        if any(str(value) == implementation for _label, value in optional_ids[:2] if value is not None):
            raise AuditError("Independent review host identity identifies the implementation context")
        complete = all(value is not None for _label, value in optional_ids)
        expected_confidence = "HIGH" if complete else "LIMITED"
        if self.provenance_confidence != expected_confidence:
            raise AuditError("Independent review provenance confidence does not match available host identities")
        if type(self.findings) is not tuple:
            raise AuditError("Independent review findings must be a tuple")
        for finding in self.findings:
            if not isinstance(finding, ReviewFinding):
                raise AuditError("Independent review finding has an invalid type")
            finding.validate()
        if len({finding.finding_id for finding in self.findings}) != len(self.findings):
            raise AuditError("Independent review finding IDs must be unique")
        finding_ids = tuple(item.finding_id for item in self.findings)
        if finding_ids != tuple(sorted(finding_ids)):
            raise AuditError("Independent review findings must be in canonical ID order")
        if not isinstance(self.verdict, str) or self.verdict not in VERDICTS:
            raise AuditError("Independent review verdict is unknown")
        if self.blocking_findings and self.verdict == "PASS":
            raise AuditError("Independent review with unresolved A/B findings cannot PASS")
        return self

    @property
    def blocking_findings(self) -> tuple[ReviewFinding, ...]:
        return tuple(item for item in self.findings if item.severity in {"A", "B"} and not item.resolved)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "context_artifact_ref": self.context_artifact_ref,
            "context_artifact_sha256": self.context_artifact_sha256,
            "findings": [
                {"description": item.description, "evidence_ref": item.evidence_ref,
                 "finding_id": item.finding_id, "resolved": item.resolved, "severity": item.severity}
                for item in self.findings
            ],
            "implementation_binding_id": self.implementation_binding_id,
            "implementation_context_id": self.implementation_context_id,
            "provenance_confidence": self.provenance_confidence,
            "reviewer_context_id": self.reviewer_context_id,
            "reviewer_id": self.reviewer_id,
            "schema": "PASES_INDEPENDENT_REVIEW_V2",
            "spawn_session_id": self.spawn_session_id,
            "subject": self.subject.as_dict(),
            "verdict": self.verdict,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["review_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "IndependentReviewV2":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditError("Independent review is not valid UTF-8 JSON") from exc
        expected = {
            "context_artifact_ref", "context_artifact_sha256", "findings", "implementation_binding_id",
            "implementation_context_id", "provenance_confidence", "review_sha256", "reviewer_context_id",
            "reviewer_id", "schema", "spawn_session_id", "subject", "verdict",
        }
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_INDEPENDENT_REVIEW_V2"
                or not isinstance(value.get("findings"), list)):
            raise AuditError("Independent review V2 has unknown/missing fields or schema")
        findings: list[ReviewFinding] = []
        for row in value["findings"]:
            if (not isinstance(row, dict)
                    or set(row) != {"description", "evidence_ref", "finding_id", "resolved", "severity"}):
                raise AuditError("Independent review finding has unknown/missing fields")
            findings.append(ReviewFinding(row["finding_id"], row["severity"], row["resolved"],
                                           row["description"], row["evidence_ref"]))
        review = cls(
            subject=VerificationSubject.from_dict(value["subject"]),
            reviewer_context_id=value["reviewer_context_id"],
            implementation_context_id=value["implementation_context_id"],
            context_artifact_ref=value["context_artifact_ref"],
            context_artifact_sha256=value["context_artifact_sha256"],
            findings=tuple(findings), verdict=value["verdict"],
            provenance_confidence=value["provenance_confidence"],
            spawn_session_id=value["spawn_session_id"], reviewer_id=value["reviewer_id"],
            implementation_binding_id=value["implementation_binding_id"],
        ).validate()
        if value["review_sha256"] != review.sha256 or review.to_bytes() != raw:
            raise AuditError("Independent review V2 digest or canonical bytes do not match")
        return review


@dataclass(frozen=True)
class ReviewUnitResult:
    """Child-authored evidence that one required review unit was inspected."""

    item_id: str
    status: str
    evidence_refs: tuple[str, ...]

    def validate(self) -> "ReviewUnitResult":
        _nonempty(self.item_id, "Independent review unit ID")
        if not isinstance(self.status, str) or self.status not in {"PASS", "FAIL"}:
            raise AuditError("Independent review unit status must be PASS or FAIL")
        if (type(self.evidence_refs) is not tuple or not self.evidence_refs
                or any(not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs)):
            raise AuditError("Independent review unit requires explicit evidence references")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"evidence_refs": list(self.evidence_refs), "item_id": self.item_id, "status": self.status}


@dataclass(frozen=True)
class ReviewFindingV3:
    finding_id: str
    severity: str
    resolved: bool
    description: str
    evidence_ref: str
    blocks_readiness: bool

    def validate(self) -> "ReviewFindingV3":
        _nonempty(self.finding_id, "Review finding ID")
        if not isinstance(self.severity, str) or self.severity not in SEVERITIES:
            raise AuditError("Review finding severity must be A, B, or C")
        if type(self.resolved) is not bool or type(self.blocks_readiness) is not bool:
            raise AuditError("Review finding flags must be boolean")
        if self.severity != "C" and self.blocks_readiness:
            raise AuditError("Only a reviewer-designated C finding may set blocks_readiness")
        _nonempty(self.description, "Review finding description")
        _nonempty(self.evidence_ref, "Review finding evidence reference")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"blocks_readiness": self.blocks_readiness, "description": self.description,
                "evidence_ref": self.evidence_ref, "finding_id": self.finding_id,
                "resolved": self.resolved, "severity": self.severity}


@dataclass(frozen=True)
class IndependentReviewV3:
    """Exact-subject review with child-authored unit coverage and typed blocking C findings."""

    subject: VerificationSubject
    reviewer_context_id: str
    implementation_context_id: str
    context_artifact_ref: str
    context_artifact_sha256: str
    review_units: tuple[ReviewUnitResult, ...]
    findings: tuple[ReviewFindingV3, ...]
    verdict: str
    provenance_confidence: str
    spawn_session_id: str | int | None
    reviewer_id: str | int | None
    implementation_binding_id: str | None

    def validate(self, required_item_ids: Iterable[str] | None = None) -> "IndependentReviewV3":
        if required_item_ids is None:
            if type(self.review_units) is not tuple:
                raise AuditError("Independent review unit results are required")
            required = tuple(item.item_id for item in self.review_units if isinstance(item, ReviewUnitResult))
        else:
            required = tuple(required_item_ids)
        if (not required or any(not isinstance(item, str) or not item.strip() for item in required)
                or len(set(required)) != len(required)):
            raise AuditError("Independent review required item set is missing, invalid, or duplicated")
        if required != tuple(sorted(required)):
            raise AuditError("Independent review required item set must be in canonical order")

        # Reuse the frozen V2 checks for subject, context, and optional host-identity semantics.
        common = IndependentReviewV2(
            subject=self.subject,
            reviewer_context_id=self.reviewer_context_id,
            implementation_context_id=self.implementation_context_id,
            context_artifact_ref=self.context_artifact_ref,
            context_artifact_sha256=self.context_artifact_sha256,
            findings=(), verdict=self.verdict,
            provenance_confidence=self.provenance_confidence,
            spawn_session_id=self.spawn_session_id, reviewer_id=self.reviewer_id,
            implementation_binding_id=self.implementation_binding_id,
        )
        common.validate()
        if type(self.review_units) is not tuple or not self.review_units:
            raise AuditError("Independent review unit results are required")
        for item in self.review_units:
            if not isinstance(item, ReviewUnitResult):
                raise AuditError("Independent review unit result has an invalid type")
            item.validate()
        unit_ids = tuple(item.item_id for item in self.review_units)
        if unit_ids != tuple(sorted(unit_ids)) or len(set(unit_ids)) != len(unit_ids):
            raise AuditError("Independent review unit results must be sorted and unique")
        if unit_ids != required:
            raise AuditError("Independent review must cover every required review unit exactly")
        if type(self.findings) is not tuple:
            raise AuditError("Independent review findings must be a tuple")
        for finding in self.findings:
            if not isinstance(finding, ReviewFindingV3):
                raise AuditError("Independent review finding has an invalid type")
            finding.validate()
        finding_ids = tuple(item.finding_id for item in self.findings)
        if finding_ids != tuple(sorted(finding_ids)) or len(set(finding_ids)) != len(finding_ids):
            raise AuditError("Independent review findings must be sorted and unique")
        if not isinstance(self.verdict, str) or self.verdict not in VERDICTS:
            raise AuditError("Independent review verdict is unknown")
        if self.blocking_findings and self.verdict == "PASS":
            raise AuditError("Independent review with unresolved blocking findings cannot PASS")
        if any(item.status != "PASS" for item in self.review_units) and self.verdict == "PASS":
            raise AuditError("Independent review with failed review units cannot PASS")
        return self

    @property
    def blocking_findings(self) -> tuple[ReviewFindingV3, ...]:
        return tuple(item for item in self.findings if not item.resolved and (
            item.severity in {"A", "B"} or (item.severity == "C" and item.blocks_readiness)
        ))

    def payload(self) -> dict[str, Any]:
        return {
            "context_artifact_ref": self.context_artifact_ref,
            "context_artifact_sha256": self.context_artifact_sha256,
            "findings": [item.as_dict() for item in self.findings],
            "implementation_binding_id": self.implementation_binding_id,
            "implementation_context_id": self.implementation_context_id,
            "provenance_confidence": self.provenance_confidence,
            "review_units": [item.as_dict() for item in self.review_units],
            "reviewer_context_id": self.reviewer_context_id,
            "reviewer_id": self.reviewer_id,
            "schema": "PASES_INDEPENDENT_REVIEW_V3",
            "spawn_session_id": self.spawn_session_id,
            "subject": self.subject.as_dict(),
            "verdict": self.verdict,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["review_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "IndependentReviewV3":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditError("Independent review V3 is not valid UTF-8 JSON") from exc
        expected = {
            "context_artifact_ref", "context_artifact_sha256", "findings", "implementation_binding_id",
            "implementation_context_id", "provenance_confidence", "review_sha256", "review_units",
            "reviewer_context_id", "reviewer_id", "schema", "spawn_session_id", "subject", "verdict",
        }
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_INDEPENDENT_REVIEW_V3"
                or not isinstance(value.get("findings"), list)
                or not isinstance(value.get("review_units"), list)):
            raise AuditError("Independent review V3 has unknown/missing fields or schema")
        findings: list[ReviewFindingV3] = []
        for row in value["findings"]:
            if not isinstance(row, dict) or set(row) != {
                "blocks_readiness", "description", "evidence_ref", "finding_id", "resolved", "severity",
            }:
                raise AuditError("Independent review V3 finding has unknown/missing fields")
            findings.append(ReviewFindingV3(row["finding_id"], row["severity"], row["resolved"],
                                             row["description"], row["evidence_ref"], row["blocks_readiness"]))
        review_units: list[ReviewUnitResult] = []
        for row in value["review_units"]:
            if not isinstance(row, dict) or set(row) != {"evidence_refs", "item_id", "status"}:
                raise AuditError("Independent review unit has unknown/missing fields")
            if not isinstance(row["evidence_refs"], list):
                raise AuditError("Independent review unit evidence_refs must be an array")
            review_units.append(ReviewUnitResult(row["item_id"], row["status"], tuple(row["evidence_refs"])))
        review = cls(
            subject=VerificationSubject.from_dict(value["subject"]),
            reviewer_context_id=value["reviewer_context_id"],
            implementation_context_id=value["implementation_context_id"],
            context_artifact_ref=value["context_artifact_ref"],
            context_artifact_sha256=value["context_artifact_sha256"],
            review_units=tuple(review_units), findings=tuple(findings), verdict=value["verdict"],
            provenance_confidence=value["provenance_confidence"], spawn_session_id=value["spawn_session_id"],
            reviewer_id=value["reviewer_id"], implementation_binding_id=value["implementation_binding_id"],
        )
        # Required IDs come from the exact approved ADC during readiness. Standalone parsing validates
        # canonical form and the digest; the caller supplies the subject's required set separately.
        review.validate(tuple(item.item_id for item in review.review_units))
        if value["review_sha256"] != review.sha256 or review.to_bytes() != raw:
            raise AuditError("Independent review V3 digest or canonical bytes do not match")
        return review


def _safe_read(path: Path, label: str) -> bytes:
    if path_has_symlink(path) or not path.is_file():
        raise AuditError(f"{label} must be a regular non-symlink file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AuditError(f"{label} is missing or unreadable") from exc


def _write_once(path: Path, raw: bytes, label: str) -> None:
    destination = Path(path)
    if path_has_symlink(destination):
        raise AuditError(f"{label} path must not traverse a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(destination):
        raise AuditError(f"{label} path must not traverse a symbolic link")
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
            if _safe_read(destination, label) != raw:
                raise AuditError(f"{label} identity exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise AuditError(f"could not atomically store {label}") from exc
    if _safe_read(destination, label) != raw:
        raise AuditError(f"{label} readback changed")


def read_self_audit(path: Path) -> SelfAudit:
    return SelfAudit.from_bytes(_safe_read(path, "Self-audit"))


def write_self_audit(path: Path, audit: SelfAudit, required_item_ids: Iterable[str]) -> str:
    audit.validate(required_item_ids)
    _write_once(path, audit.to_bytes(), "Self-audit")
    return audit.sha256


IndependentReviewEvidence = IndependentReview | IndependentReviewV2 | IndependentReviewV3


def read_independent_review(path: Path) -> IndependentReviewEvidence:
    raw = _safe_read(path, "Independent review")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError("Independent review is not valid UTF-8 JSON") from exc
    if isinstance(value, dict) and value.get("schema") == "PASES_INDEPENDENT_REVIEW_V3":
        return IndependentReviewV3.from_bytes(raw)
    if isinstance(value, dict) and value.get("schema") == "PASES_INDEPENDENT_REVIEW_V2":
        return IndependentReviewV2.from_bytes(raw)
    return IndependentReview.from_bytes(raw)


def write_independent_review(path: Path, review: IndependentReviewEvidence) -> str:
    if not isinstance(review, (IndependentReview, IndependentReviewV2, IndependentReviewV3)):
        raise AuditError("Independent review has an unsupported type")
    review.validate()
    _write_once(path, review.to_bytes(), "Independent review")
    return review.sha256
