"""Evidence-backed self-audit and independent-review record schemas."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .evidence_store import VerificationSubject
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
        if "BLOCKED" in statuses:
            return "BLOCKED"
        if "CONCERNS" in statuses:
            return "CONCERNS"
        return "PASS"

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
