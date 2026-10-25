"""Strict Independent Review V2 evidence and assurance evaluation.

V1 review records remain readable for historical compatibility, but V1 alone
does not satisfy current Review Readiness. Native capture records bind the
request, terminal return, and child-authored output bytes without claiming that
the host authenticated those bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .audits import AuditError, IndependentReview, ReviewFinding
from .evidence_store import VerificationSubject
from .path_safety import path_has_symlink


class ReviewAssuranceError(ValueError):
    pass


SHA256 = re.compile(r"^[0-9a-f]{64}$")
ASSURANCES = {"HOST_VERIFIED", "INDEPENDENT_ATTESTED", "SELF_REVIEW", "UNAVAILABLE"}
MINIMUMS = {"host_verified", "independent_attested"}
EVIDENCE_ORIGIN = "operator_captured_native_tool_result"
MAX_CAPTURE_BYTES = 2_000_000
# The repository currently contains payload validators, not integrations that
# capture results directly from a host-owned native delegation API.
NATIVE_CAPTURE_BOUNDARY_CONFIGURED = False


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewAssuranceError(f"{label} has duplicate JSON key {key!r}")
            result[key] = value
        return result

    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_CAPTURE_BYTES:
        raise ReviewAssuranceError(f"{label} must be non-empty bytes within the capture size limit")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewAssuranceError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReviewAssuranceError(f"{label} must be a JSON object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ReviewAssuranceError(f"{label} must be non-empty text")
    return value.strip()


@dataclass(frozen=True)
class CapturedBytes:
    bytes_b64: str
    sha256: str

    def validate(self, label: str) -> bytes:
        if not isinstance(self.bytes_b64, str) or not isinstance(self.sha256, str) or not SHA256.fullmatch(self.sha256):
            raise ReviewAssuranceError(f"{label} capture encoding or digest is invalid")
        try:
            raw = base64.b64decode(self.bytes_b64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ReviewAssuranceError(f"{label} capture is not valid base64") from exc
        if (not raw or len(raw) > MAX_CAPTURE_BYTES
                or base64.b64encode(raw).decode("ascii") != self.bytes_b64
                or hashlib.sha256(raw).hexdigest() != self.sha256):
            raise ReviewAssuranceError(f"{label} capture bytes or digest changed")
        return raw

    def as_dict(self) -> dict[str, str]:
        self.validate("captured bytes")
        return {"bytes_b64": self.bytes_b64, "sha256": self.sha256}

    @classmethod
    def capture(cls, raw: bytes) -> "CapturedBytes":
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_CAPTURE_BYTES:
            raise ReviewAssuranceError("native evidence must be non-empty bytes within the capture size limit")
        return cls(base64.b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest())

    @classmethod
    def from_dict(cls, value: Any, label: str) -> "CapturedBytes":
        if not isinstance(value, dict) or set(value) != {"bytes_b64", "sha256"}:
            raise ReviewAssuranceError(f"{label} has unknown or missing fields")
        result = cls(value["bytes_b64"], value["sha256"])
        result.validate(label)
        return result


@dataclass(frozen=True)
class AttestedNativeDelegationEvidenceV1:
    subject: VerificationSubject
    execution_identity_context_id: str
    request: CapturedBytes
    terminal_return: CapturedBytes
    child_output: CapturedBytes
    host_spawn_id: str | None = None
    host_child_id: str | None = None
    host_join_id: str | None = None
    evidence_origin: str = EVIDENCE_ORIGIN

    def validate(self) -> "AttestedNativeDelegationEvidenceV1":
        self.subject.validate()
        execution = _text(self.execution_identity_context_id, "execution identity context ID")
        if self.evidence_origin != EVIDENCE_ORIGIN:
            raise ReviewAssuranceError("native evidence origin must identify operator-captured tool results")
        for item, label in ((self.host_spawn_id, "host spawn ID"), (self.host_child_id, "host child ID"),
                            (self.host_join_id, "host join ID")):
            if item is not None:
                _text(item, label)
        request_raw = self.request.validate("native delegation request")
        return_raw = self.terminal_return.validate("native terminal return")
        output_raw = self.child_output.validate("child review output")
        request = _strict_json(request_raw, "native delegation request")
        expected_request = {"execution_identity_context_id", "operation", "reviewer_context_id", "schema", "subject"}
        if (set(request) != expected_request or request.get("schema") != "PASES_NATIVE_REVIEW_REQUEST_V1"
                or request.get("operation") != "spawn_independent_review_child"
                or request.get("subject") != self.subject.as_dict()
                or request.get("execution_identity_context_id") != execution):
            raise ReviewAssuranceError("native request is not bound to the exact subject and implementation context")
        reviewer = _text(request.get("reviewer_context_id"), "reviewer context ID")
        if reviewer == execution:
            raise ReviewAssuranceError("native review must come from a distinct child context")
        terminal = _strict_json(return_raw, "native terminal return")
        expected_terminal = {"child_output_sha256", "completed", "request_sha256", "schema", "status"}
        if (set(terminal) != expected_terminal or terminal.get("schema") != "PASES_NATIVE_REVIEW_TERMINAL_V1"
                or terminal.get("completed") is not True or terminal.get("status") != "success"
                or terminal.get("request_sha256") != self.request.sha256
                or terminal.get("child_output_sha256") != self.child_output.sha256):
            raise ReviewAssuranceError("native terminal return does not confirm successful completion of these exact bytes")
        child = _strict_json(output_raw, "child-authored review output")
        expected_child = {"findings", "reviewer_context_id", "schema", "subject", "verdict"}
        if (set(child) != expected_child or child.get("schema") != "PASES_CHILD_REVIEW_OUTPUT_V1"
                or child.get("subject") != self.subject.as_dict()
                or child.get("reviewer_context_id") != reviewer):
            raise ReviewAssuranceError("child output is not bound to the native request and exact review subject")
        _validate_review_result(child.get("findings"), child.get("verdict"))
        return self

    @property
    def reviewer_context_id(self) -> str:
        request = _strict_json(self.request.validate("native request"), "native request")
        return request["reviewer_context_id"]

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "child_output": self.child_output.as_dict(),
            "evidence_origin": self.evidence_origin,
            "execution_identity_context_id": self.execution_identity_context_id,
            "host_child_id": self.host_child_id,
            "host_join_id": self.host_join_id,
            "host_spawn_id": self.host_spawn_id,
            "request": self.request.as_dict(),
            "schema": "PASES_ATTESTED_NATIVE_DELEGATION_EVIDENCE_V1",
            "subject": self.subject.as_dict(),
            "terminal_return": self.terminal_return.as_dict(),
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    @classmethod
    def capture(cls, *, subject: VerificationSubject, execution_identity_context_id: str,
                request: bytes, terminal_return: bytes, child_output: bytes,
                host_spawn_id: str | None = None, host_child_id: str | None = None,
                host_join_id: str | None = None) -> "AttestedNativeDelegationEvidenceV1":
        item = cls(subject, execution_identity_context_id, CapturedBytes.capture(request),
                   CapturedBytes.capture(terminal_return), CapturedBytes.capture(child_output),
                   host_spawn_id, host_child_id, host_join_id)
        return item.validate()

    @classmethod
    def from_dict(cls, value: Any) -> "AttestedNativeDelegationEvidenceV1":
        expected = {"child_output", "evidence_origin", "execution_identity_context_id", "host_child_id",
                    "host_join_id", "host_spawn_id", "request", "schema", "subject", "terminal_return"}
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_ATTESTED_NATIVE_DELEGATION_EVIDENCE_V1"):
            raise ReviewAssuranceError("native delegation evidence has unknown or missing fields")
        result = cls(
            VerificationSubject.from_dict(value["subject"]), value["execution_identity_context_id"],
            CapturedBytes.from_dict(value["request"], "native request"),
            CapturedBytes.from_dict(value["terminal_return"], "native terminal return"),
            CapturedBytes.from_dict(value["child_output"], "child output"),
            value["host_spawn_id"], value["host_child_id"], value["host_join_id"], value["evidence_origin"],
        )
        return result.validate()


@dataclass(frozen=True)
class HostProvenanceV1:
    """Host event wrapper. No supported surface currently registers a verifier."""

    source_id: str
    event: CapturedBytes
    native_evidence_sha256: str

    def validate(self) -> "HostProvenanceV1":
        _text(self.source_id, "host provenance source ID")
        self.event.validate("host provenance event")
        if not isinstance(self.native_evidence_sha256, str) or not SHA256.fullmatch(self.native_evidence_sha256):
            raise ReviewAssuranceError("host provenance native evidence digest is invalid")
        event = _strict_json(self.event.validate("host provenance event"), "host provenance event")
        if (set(event) != {"native_evidence_sha256", "schema", "source_id", "subject"}
                or event.get("schema") != "PASES_HOST_PROVENANCE_EVENT_V1"
                or event.get("source_id") != self.source_id
                or event.get("native_evidence_sha256") != self.native_evidence_sha256):
            raise ReviewAssuranceError("host event does not bind the exact native evidence")
        VerificationSubject.from_dict(event.get("subject"))
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"event": self.event.as_dict(), "native_evidence_sha256": self.native_evidence_sha256,
                "schema": "PASES_HOST_PROVENANCE_V1", "source_id": self.source_id}

    @classmethod
    def from_dict(cls, value: Any) -> "HostProvenanceV1":
        if (not isinstance(value, dict) or set(value) != {"event", "native_evidence_sha256", "schema", "source_id"}
                or value.get("schema") != "PASES_HOST_PROVENANCE_V1"):
            raise ReviewAssuranceError("host provenance has unknown or missing fields")
        return cls(value["source_id"], CapturedBytes.from_dict(value["event"], "host provenance event"),
                   value["native_evidence_sha256"]).validate()


def _validate_review_result(rows: Any, verdict: Any) -> tuple[ReviewFinding, ...]:
    if not isinstance(rows, list) or not isinstance(verdict, str) or verdict not in {"PASS", "FAIL", "BLOCKED", "CONCERNS"}:
        raise ReviewAssuranceError("child review verdict or findings are invalid")
    findings: list[ReviewFinding] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"description", "evidence_ref", "finding_id", "resolved", "severity"}:
            raise ReviewAssuranceError("child review finding has unknown or missing fields")
        try:
            findings.append(ReviewFinding(row["finding_id"], row["severity"], row["resolved"],
                                          row["description"], row["evidence_ref"]).validate())
        except AuditError as exc:
            raise ReviewAssuranceError(str(exc)) from exc
    if len({item.finding_id for item in findings}) != len(findings):
        raise ReviewAssuranceError("child review finding IDs must be unique")
    if tuple(row.finding_id for row in findings) != tuple(sorted(row.finding_id for row in findings)):
        raise ReviewAssuranceError("child review findings must be in canonical ID order")
    if any(row.severity in {"A", "B"} and not row.resolved for row in findings) and verdict == "PASS":
        raise ReviewAssuranceError("child review with unresolved A/B findings cannot PASS")
    return tuple(findings)


@dataclass(frozen=True)
class IndependentReviewV2:
    subject: VerificationSubject
    assurance: str
    reviewer_context_id: str
    execution_identity_context_id: str
    verdict: str
    findings: tuple[ReviewFinding, ...]
    native_evidence: AttestedNativeDelegationEvidenceV1 | None = None
    host_provenance: HostProvenanceV1 | None = None
    profile_sha256: str | None = None
    evidence_origin: str | None = None

    def validate(self) -> "IndependentReviewV2":
        self.subject.validate()
        if self.assurance not in ASSURANCES:
            raise ReviewAssuranceError("Independent Review V2 assurance is unknown")
        reviewer = _text(self.reviewer_context_id, "reviewer context ID")
        execution = _text(self.execution_identity_context_id, "execution identity context ID")
        if self.verdict not in {"PASS", "FAIL", "BLOCKED", "CONCERNS"}:
            raise ReviewAssuranceError("Independent Review V2 verdict is invalid")
        if type(self.findings) is not tuple:
            raise ReviewAssuranceError("Independent Review V2 findings must be a tuple")
        if any(not isinstance(row, ReviewFinding) for row in self.findings):
            raise ReviewAssuranceError("Independent Review V2 finding has an invalid type")
        _validate_review_result([{
            "description": row.description, "evidence_ref": row.evidence_ref,
            "finding_id": row.finding_id, "resolved": row.resolved, "severity": row.severity,
        } for row in self.findings], self.verdict)
        if not isinstance(self.profile_sha256, str) or not SHA256.fullmatch(self.profile_sha256):
            raise ReviewAssuranceError("Independent Review V2 must bind a committed profile digest")
        if self.assurance == "INDEPENDENT_ATTESTED":
            if (not isinstance(self.native_evidence, AttestedNativeDelegationEvidenceV1)
                    or self.host_provenance is not None or self.evidence_origin != EVIDENCE_ORIGIN):
                raise ReviewAssuranceError("attested review requires exact native evidence and its explicit origin")
            self.native_evidence.validate()
            if (self.native_evidence.subject != self.subject
                    or self.native_evidence.execution_identity_context_id != execution
                    or self.native_evidence.reviewer_context_id != reviewer or reviewer == execution):
                raise ReviewAssuranceError("attested native evidence does not match review and implementation identities")
            child = _strict_json(self.native_evidence.child_output.validate("child output"), "child output")
            if child.get("verdict") != self.verdict:
                raise ReviewAssuranceError("Independent Review V2 verdict differs from child-authored bytes")
            parsed = _validate_review_result(child.get("findings"), child.get("verdict"))
            if parsed != self.findings:
                raise ReviewAssuranceError("Independent Review V2 findings differ from child-authored bytes")
        elif self.assurance == "HOST_VERIFIED":
            if (not isinstance(self.native_evidence, AttestedNativeDelegationEvidenceV1)
                    or not isinstance(self.host_provenance, HostProvenanceV1)):
                raise ReviewAssuranceError("host-verified review requires host provenance and native child evidence")
            self.native_evidence.validate()
            self.host_provenance.validate()
            if (self.native_evidence.subject != self.subject
                    or self.native_evidence.execution_identity_context_id != execution
                    or self.native_evidence.reviewer_context_id != reviewer
                    or self.host_provenance.native_evidence_sha256 != self.native_evidence.sha256):
                raise ReviewAssuranceError("host provenance is not bound to the exact review result")
            host_event = _strict_json(self.host_provenance.event.validate("host event"), "host event")
            if VerificationSubject.from_dict(host_event.get("subject")) != self.subject:
                raise ReviewAssuranceError("host provenance subject differs from the review subject")
            child = _strict_json(self.native_evidence.child_output.validate("child output"), "child output")
            if (child.get("verdict") != self.verdict
                    or _validate_review_result(child.get("findings"), child.get("verdict")) != self.findings):
                raise ReviewAssuranceError("HOST_VERIFIED result differs from exact child-authored output")
        else:
            if self.native_evidence is not None or self.host_provenance is not None:
                raise ReviewAssuranceError("SELF_REVIEW and UNAVAILABLE cannot carry independent native evidence")
            if self.assurance == "SELF_REVIEW" and reviewer != execution:
                raise ReviewAssuranceError("SELF_REVIEW must identify the implementation context")
            if self.assurance == "UNAVAILABLE" and reviewer == execution:
                raise ReviewAssuranceError("UNAVAILABLE provenance requires a distinct independent reviewer context")
            if self.assurance == "UNAVAILABLE" and self.verdict == "PASS":
                raise ReviewAssuranceError("UNAVAILABLE V2 cannot claim a formal Independent Review PASS")
        return self

    @property
    def blocking_findings(self) -> tuple[ReviewFinding, ...]:
        return tuple(row for row in self.findings if row.severity in {"A", "B"} and not row.resolved)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "assurance": self.assurance,
            "evidence_origin": self.evidence_origin,
            "execution_identity_context_id": self.execution_identity_context_id,
            "findings": [{"description": row.description, "evidence_ref": row.evidence_ref,
                          "finding_id": row.finding_id, "resolved": row.resolved, "severity": row.severity}
                         for row in self.findings],
            "host_provenance": None if self.host_provenance is None else self.host_provenance.as_dict(),
            "native_evidence": None if self.native_evidence is None else self.native_evidence.payload(),
            "profile_sha256": self.profile_sha256,
            "reviewer_context_id": self.reviewer_context_id,
            "schema": "PASES_INDEPENDENT_REVIEW_V2",
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

    def as_v1_readiness_projection(self) -> IndependentReview:
        self.validate()
        return IndependentReview(
            subject=self.subject,
            reviewer_context_id=self.reviewer_context_id,
            implementation_context_id=self.execution_identity_context_id,
            context_artifact_ref=f"independent-review-v2:sha256:{self.sha256}",
            context_artifact_sha256=self.sha256,
            findings=self.findings,
            verdict=self.verdict,
        ).validate()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "IndependentReviewV2":
        value = _strict_json(raw, "Independent Review V2")
        expected = {"assurance", "evidence_origin", "execution_identity_context_id", "findings",
                    "host_provenance", "native_evidence", "profile_sha256", "review_sha256",
                    "reviewer_context_id", "schema", "subject", "verdict"}
        if (set(value) != expected or value.get("schema") != "PASES_INDEPENDENT_REVIEW_V2"
                or not isinstance(value.get("findings"), list)):
            raise ReviewAssuranceError("Independent Review V2 has unknown or missing fields")
        findings = _validate_review_result(value["findings"], value["verdict"])
        native = None if value["native_evidence"] is None else AttestedNativeDelegationEvidenceV1.from_dict(value["native_evidence"])
        host = None if value["host_provenance"] is None else HostProvenanceV1.from_dict(value["host_provenance"])
        result = cls(VerificationSubject.from_dict(value["subject"]), value["assurance"],
                     value["reviewer_context_id"], value["execution_identity_context_id"],
                     value["verdict"], findings, native, host, value["profile_sha256"], value["evidence_origin"])
        result.validate()
        if result.sha256 != value["review_sha256"] or result.to_bytes() != raw:
            raise ReviewAssuranceError("Independent Review V2 digest or canonical bytes do not match")
        return result


@dataclass(frozen=True)
class IndependentReviewOccurrenceV1:
    """Explicit occurrence record retaining the exact reviewer output bytes.

    The record establishes which bytes the operator captured and keeps review
    occurrence, outcome, findings, and provenance assurance as separate data.
    It is not a signature from the host that ran the reviewer.
    """

    subject: VerificationSubject
    reviewer_context_id: str
    execution_identity_context_id: str
    execution_binding_sha256: str
    pr_binding_sha256: str
    profile_sha256: str
    independent_review_v2_sha256: str
    review_outcome: str
    findings: tuple[ReviewFinding, ...]
    reviewer_output: CapturedBytes
    provenance_assurance: str = "UNAVAILABLE"
    review_occurrence: str = "COMPLETED"
    evidence_origin: str = "operator_reported_separate_context_review"

    def validate(self) -> "IndependentReviewOccurrenceV1":
        self.subject.validate()
        reviewer = _text(self.reviewer_context_id, "reviewer context ID")
        execution = _text(self.execution_identity_context_id, "execution identity context ID")
        if reviewer == execution:
            raise ReviewAssuranceError("Independent Review occurrence must come from a separate context")
        for name, value in (("ExecutionBinding", self.execution_binding_sha256),
                            ("PRBinding", self.pr_binding_sha256), ("profile", self.profile_sha256),
                            ("Independent Review V2", self.independent_review_v2_sha256)):
            if not isinstance(value, str) or not SHA256.fullmatch(value):
                raise ReviewAssuranceError(f"review occurrence {name} digest is invalid")
        if (self.review_occurrence != "COMPLETED" or self.provenance_assurance != "UNAVAILABLE"
                or self.evidence_origin != "operator_reported_separate_context_review"):
            raise ReviewAssuranceError("operator-reported occurrence has invalid status or provenance label")
        self.reviewer_output.validate("exact captured reviewer output")
        output = _strict_json(self.reviewer_output.validate("exact captured reviewer output"),
                              "exact captured reviewer output")
        expected = {"findings", "reviewer_context_id", "schema", "subject", "verdict"}
        if (set(output) != expected or output.get("schema") != "PASES_CHILD_REVIEW_OUTPUT_V1"
                or output.get("subject") != self.subject.as_dict()
                or output.get("reviewer_context_id") != reviewer
                or output.get("verdict") != self.review_outcome):
            raise ReviewAssuranceError("captured reviewer output does not match the exact occurrence record")
        parsed = _validate_review_result(output.get("findings"), output.get("verdict"))
        if parsed != self.findings:
            raise ReviewAssuranceError("captured reviewer output findings differ from the occurrence record")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "evidence_origin": self.evidence_origin,
            "execution_binding_sha256": self.execution_binding_sha256,
            "execution_identity_context_id": self.execution_identity_context_id,
            "findings": [{"description": row.description, "evidence_ref": row.evidence_ref,
                          "finding_id": row.finding_id, "resolved": row.resolved,
                          "severity": row.severity} for row in self.findings],
            "pr_binding_sha256": self.pr_binding_sha256,
            "profile_sha256": self.profile_sha256,
            "independent_review_v2_sha256": self.independent_review_v2_sha256,
            "provenance_assurance": self.provenance_assurance,
            "review_occurrence": self.review_occurrence,
            "review_outcome": self.review_outcome,
            "reviewer_context_id": self.reviewer_context_id,
            "reviewer_output": self.reviewer_output.as_dict(),
            "schema": "PASES_INDEPENDENT_REVIEW_OCCURRENCE_V1",
            "subject": self.subject.as_dict(),
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        return _canonical({**self.payload(), "occurrence_sha256": self.sha256}) + b"\n"

    @classmethod
    def from_captured_output(cls, *, subject: VerificationSubject,
                             execution_identity_context_id: str,
                             execution_binding_sha256: str, pr_binding_sha256: str,
                             profile_sha256: str, independent_review_v2_sha256: str,
                             raw_output: bytes) -> "IndependentReviewOccurrenceV1":
        value = _strict_json(raw_output, "exact captured reviewer output")
        findings = _validate_review_result(value.get("findings"), value.get("verdict"))
        result = cls(
            subject=subject, reviewer_context_id=value.get("reviewer_context_id"),
            execution_identity_context_id=execution_identity_context_id,
            execution_binding_sha256=execution_binding_sha256,
            pr_binding_sha256=pr_binding_sha256, profile_sha256=profile_sha256,
            independent_review_v2_sha256=independent_review_v2_sha256,
            review_outcome=value.get("verdict"), findings=findings,
            reviewer_output=CapturedBytes.capture(raw_output),
        )
        return result.validate()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "IndependentReviewOccurrenceV1":
        value = _strict_json(raw, "Independent Review occurrence")
        expected = {"evidence_origin", "execution_binding_sha256", "execution_identity_context_id",
                    "findings", "occurrence_sha256", "pr_binding_sha256", "profile_sha256",
                    "independent_review_v2_sha256", "provenance_assurance", "review_occurrence", "review_outcome",
                    "reviewer_context_id", "reviewer_output", "schema", "subject"}
        if set(value) != expected or value.get("schema") != "PASES_INDEPENDENT_REVIEW_OCCURRENCE_V1":
            raise ReviewAssuranceError("Independent Review occurrence has unknown or missing fields")
        try:
            findings = tuple(ReviewFinding(
                row["finding_id"], row["severity"], row["resolved"], row["description"], row["evidence_ref"],
            ).validate() for row in value["findings"])
            record = cls(
                subject=VerificationSubject.from_dict(value["subject"]),
                reviewer_context_id=value["reviewer_context_id"],
                execution_identity_context_id=value["execution_identity_context_id"],
                execution_binding_sha256=value["execution_binding_sha256"],
                pr_binding_sha256=value["pr_binding_sha256"], profile_sha256=value["profile_sha256"],
                independent_review_v2_sha256=value["independent_review_v2_sha256"],
                review_outcome=value["review_outcome"], findings=findings,
                reviewer_output=CapturedBytes.from_dict(value["reviewer_output"], "reviewer output"),
                provenance_assurance=value["provenance_assurance"],
                review_occurrence=value["review_occurrence"], evidence_origin=value["evidence_origin"],
            ).validate()
        except (KeyError, TypeError) as exc:
            raise ReviewAssuranceError("Independent Review occurrence is malformed") from exc
        if value["occurrence_sha256"] != record.sha256 or record.to_bytes() != raw:
            raise ReviewAssuranceError("Independent Review occurrence digest or canonical bytes do not match")
        return record


def read_independent_review_occurrence_v1(path: Path) -> IndependentReviewOccurrenceV1:
    if path_has_symlink(path) or not path.is_file():
        raise ReviewAssuranceError("Independent Review occurrence must be a regular non-symlink file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReviewAssuranceError("Independent Review occurrence file cannot be read") from exc
    return IndependentReviewOccurrenceV1.from_bytes(raw)


def write_independent_review_occurrence_v1(path: Path,
                                           record: IndependentReviewOccurrenceV1) -> str:
    raw = record.to_bytes()
    if path_has_symlink(path) or path.exists():
        raise ReviewAssuranceError("Independent Review occurrence output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(path):
        raise ReviewAssuranceError("Independent Review occurrence path traverses a symbolic link")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ReviewAssuranceError("Independent Review occurrence output was concurrently created") from exc
    if path.read_bytes() != raw:
        raise ReviewAssuranceError("Independent Review occurrence readback differs from written bytes")
    return record.sha256


def attest_native_review(*, subject: VerificationSubject, execution_identity_context_id: str,
                         request: bytes, terminal_return: bytes, child_output: bytes,
                         profile_sha256: str, host_spawn_id: str | None = None,
                         host_child_id: str | None = None, host_join_id: str | None = None) -> IndependentReviewV2:
    """Issue attested V2 only when a real host capture boundary is connected."""
    if not NATIVE_CAPTURE_BOUNDARY_CONFIGURED:
        raise ReviewAssuranceError(
            "no host-native capture boundary is configured; caller-supplied bytes cannot be attested"
        )
    evidence = AttestedNativeDelegationEvidenceV1.capture(
        subject=subject, execution_identity_context_id=execution_identity_context_id,
        request=request, terminal_return=terminal_return, child_output=child_output,
        host_spawn_id=host_spawn_id, host_child_id=host_child_id, host_join_id=host_join_id,
    )
    child = _strict_json(evidence.child_output.validate("child review output"), "child review output")
    findings = _validate_review_result(child["findings"], child["verdict"])
    return IndependentReviewV2(
        subject=subject,
        assurance="INDEPENDENT_ATTESTED",
        reviewer_context_id=evidence.reviewer_context_id,
        execution_identity_context_id=execution_identity_context_id,
        verdict=child["verdict"], findings=findings,
        native_evidence=evidence, profile_sha256=profile_sha256,
        evidence_origin=EVIDENCE_ORIGIN,
    ).validate()


def report_separate_context_review(*, subject: VerificationSubject,
                                   execution_identity_context_id: str,
                                   reviewer_context_id: str, verdict: str,
                                   findings: tuple[ReviewFinding, ...],
                                   profile_sha256: str) -> IndependentReviewV2:
    """Record unavailable formal assurance for a separately completed review.

    Preserve the V2 meaning: a result with unavailable provenance cannot claim
    a formal review PASS. The linked occurrence V1 carries the actual review
    outcome and findings without changing historical V2 semantics.
    """
    if verdict not in {"PASS", "FAIL", "BLOCKED", "CONCERNS"}:
        raise ReviewAssuranceError("separate-context review outcome is invalid")
    _validate_review_result([{
        "description": row.description, "evidence_ref": row.evidence_ref,
        "finding_id": row.finding_id, "resolved": row.resolved, "severity": row.severity,
    } for row in findings], verdict)
    result = IndependentReviewV2(
        subject=subject, assurance="UNAVAILABLE", reviewer_context_id=reviewer_context_id,
        execution_identity_context_id=execution_identity_context_id, verdict="BLOCKED",
        findings=findings, profile_sha256=profile_sha256,
        evidence_origin="operator_reported_separate_context_review",
    ).validate()
    if reviewer_context_id == execution_identity_context_id:
        raise ReviewAssuranceError("Independent Review must be performed in a separate context")
    return result


@dataclass(frozen=True)
class ReviewAssuranceDecision:
    status: str
    assurance: str
    minimum_assurance: str
    review_sha256: str
    profile_sha256: str
    reasons: tuple[str, ...]

    def validate(self) -> "ReviewAssuranceDecision":
        if self.status not in {"PASS", "BLOCKED"} or self.assurance not in ASSURANCES or self.minimum_assurance not in MINIMUMS:
            raise ReviewAssuranceError("review assurance decision fields are invalid")
        for value, label in ((self.review_sha256, "review digest"), (self.profile_sha256, "profile digest")):
            if not isinstance(value, str) or not SHA256.fullmatch(value):
                raise ReviewAssuranceError(f"{label} is invalid")
        if type(self.reasons) is not tuple or (self.status == "PASS" and self.reasons) or (self.status == "BLOCKED" and not self.reasons):
            raise ReviewAssuranceError("review assurance status and reasons disagree")
        return self


def evaluate_review_assurance(review: IndependentReviewV2, *, subject: VerificationSubject,
                              execution_identity_context_id: str, minimum_assurance: str,
                              profile_sha256: str) -> ReviewAssuranceDecision:
    review.validate()
    subject.validate()
    execution = _text(execution_identity_context_id, "current execution identity")
    if minimum_assurance not in MINIMUMS:
        raise ReviewAssuranceError("project minimum assurance is unsupported")
    if not isinstance(profile_sha256, str) or not SHA256.fullmatch(profile_sha256):
        raise ReviewAssuranceError("current project profile digest is invalid")
    reasons: list[str] = []
    if review.subject != subject:
        reasons.append("Independent Review V2 is stale or belongs to a different exact subject")
    if review.execution_identity_context_id != execution:
        reasons.append("Independent Review V2 is bound to a different implementation identity")
    if review.profile_sha256 != profile_sha256:
        reasons.append("Independent Review V2 was not issued against the current committed profile digest")
    effective_assurance = review.assurance
    if review.assurance == "HOST_VERIFIED":
        # No current adapter provides a trusted, agent-nonwritable event verifier.
        reasons.append("HOST_VERIFIED is unavailable because no trusted host event verifier is configured")
        effective_assurance = "UNAVAILABLE"
    elif review.assurance == "INDEPENDENT_ATTESTED" and not NATIVE_CAPTURE_BOUNDARY_CONFIGURED:
        # Self-consistent JSON can be authored by the implementation process.
        # Byte integrity does not prove that a host actually spawned or joined a
        # separate reviewer, so no policy minimum may consume it as attested.
        reasons.append(
            "operator-supplied native-review bytes have no configured host capture boundary; "
            "effective assurance is UNAVAILABLE"
        )
        effective_assurance = "UNAVAILABLE"
    elif review.assurance == "UNAVAILABLE":
        reasons.append("native review capture is unavailable because no host capture boundary is configured")
    if minimum_assurance == "host_verified" and effective_assurance != "HOST_VERIFIED":
        reasons.append("project requires HOST_VERIFIED Independent Review evidence")
    elif (minimum_assurance == "independent_attested"
          and effective_assurance not in {"HOST_VERIFIED", "INDEPENDENT_ATTESTED"}):
        reasons.append(f"review assurance {review.assurance} does not meet the project minimum")
    if review.verdict != "PASS":
        reasons.append(f"independent review verdict is {review.verdict}")
    if review.blocking_findings:
        reasons.append("independent review has unresolved A/B findings")
    return ReviewAssuranceDecision("BLOCKED" if reasons else "PASS", effective_assurance,
                                   minimum_assurance, review.sha256, profile_sha256,
                                   tuple(dict.fromkeys(reasons))).validate()


@dataclass(frozen=True)
class ReviewCaptureEligibility:
    """Typed distinction between absent host capture, a failed review, and bad evidence."""

    status: str
    host_surface: str
    observation_sha256s: tuple[str, ...]
    reasons: tuple[str, ...]

    def validate(self) -> "ReviewCaptureEligibility":
        if self.status not in {"HOST_NATIVE_CAPTURE_UNAVAILABLE", "REVIEW_FAILED", "INVALID_EVIDENCE"}:
            raise ReviewAssuranceError("review capture eligibility status is invalid")
        if self.host_surface not in {"codex_cloud", "codex_local_cli", "codex_desktop", "claude_code"}:
            raise ReviewAssuranceError("review capture eligibility host surface is invalid")
        if (type(self.observation_sha256s) is not tuple
                or any(not isinstance(item, str) or not SHA256.fullmatch(item)
                       for item in self.observation_sha256s)
                or self.observation_sha256s != tuple(sorted(set(self.observation_sha256s)))):
            raise ReviewAssuranceError("review capability observation digests are invalid")
        if self.status == "HOST_NATIVE_CAPTURE_UNAVAILABLE":
            if not self.observation_sha256s or self.reasons:
                raise ReviewAssuranceError("eligible capture-unavailable evidence is incomplete")
        elif not self.reasons:
            raise ReviewAssuranceError("ineligible review evidence needs an explicit reason")
        return self


def capture_unavailability_observation(host_surface: str, capabilities: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Bind the adapter's actual capability report without asserting host provenance."""
    if host_surface not in {"codex_cloud", "codex_local_cli", "codex_desktop", "claude_code"}:
        raise ReviewAssuranceError("review host surface is unsupported")
    expected_fields = {"host_ids_optional", "native_request_return_capture", "surface",
                       "trusted_host_event_verification"}
    if (not isinstance(capabilities, dict) or set(capabilities) != expected_fields
            or capabilities.get("surface") != host_surface
            or type(capabilities.get("native_request_return_capture")) is not bool
            or type(capabilities.get("trusted_host_event_verification")) is not bool
            or type(capabilities.get("host_ids_optional")) is not bool):
        raise ReviewAssuranceError("native review adapter capability observation is malformed")
    observation = {
        "capabilities": dict(capabilities),
        "configured_capture_boundary": NATIVE_CAPTURE_BOUNDARY_CONFIGURED,
        "host_surface": host_surface,
        "schema": "PASES_REVIEW_CAPTURE_OBSERVATION_V1",
    }
    return observation, hashlib.sha256(_canonical(observation)).hexdigest()


def evaluate_capture_unavailability(*, host_surface: str, observation: dict[str, Any],
                                    observation_sha256: str,
                                    current_reviews: Iterable[IndependentReviewV2] = (),
                                    current_occurrences: Iterable[IndependentReviewOccurrenceV1] = ()
                                    ) -> ReviewCaptureEligibility:
    """Permit a provenance exception only for a completed current independent review."""
    reasons: list[str] = []
    digest_tuple: tuple[str, ...] = ()
    reviews = tuple(current_reviews)
    occurrences = tuple(current_occurrences)
    if not reviews or not occurrences:
        reasons.append("no current independent review occurrence record and outcome were recorded")
    if len(reviews) > 1:
        reasons.append("multiple current Independent Review results are conflicting")
    if len(occurrences) > 1:
        reasons.append("multiple current Independent Review occurrence records are conflicting")
    if host_surface not in {"codex_cloud", "codex_local_cli", "codex_desktop", "claude_code"}:
        reasons.append("host surface is unknown")
    if (not isinstance(observation_sha256, str) or not SHA256.fullmatch(observation_sha256)
            or not isinstance(observation, dict)
            or hashlib.sha256(_canonical(observation)).hexdigest() != observation_sha256):
        reasons.append("native capture capability observation is malformed or changed")
    else:
        digest_tuple = (observation_sha256,)
        capabilities = observation.get("capabilities")
        if (observation.get("schema") != "PASES_REVIEW_CAPTURE_OBSERVATION_V1"
                or observation.get("host_surface") != host_surface
                or observation.get("configured_capture_boundary") is not False
                or NATIVE_CAPTURE_BOUNDARY_CONFIGURED is not False
                or not isinstance(capabilities, dict)
                or capabilities.get("surface") != host_surface
                or capabilities.get("native_request_return_capture") is not False):
            reasons.append("host-to-runtime native request/return capture is not positively observed unavailable")
    for review in reviews:
        if not isinstance(review, IndependentReviewV2):
            reasons.append("current review evidence has an unsupported type")
            continue
        try:
            review.validate()
        except (ReviewAssuranceError, ValueError):
            reasons.append("current review evidence is malformed")
            continue
        has_unresolved_abc = any(f.severity in {"A", "B", "C"} and not f.resolved
                                 for f in review.findings)
        if review.reviewer_context_id == review.execution_identity_context_id:
            reasons.append("current review was not performed in a distinct reviewer context")
            continue
        if review.assurance == "UNAVAILABLE" and review.evidence_origin != "operator_reported_separate_context_review":
            reasons.append("current unavailable review lacks an explicit separate-context occurrence report")
            continue
        if review.assurance == "UNAVAILABLE":
            if review.verdict != "BLOCKED":
                reasons.append("UNAVAILABLE V2 evidence must preserve its historical non-PASS meaning")
                continue
            if len(occurrences) != 1 or not isinstance(occurrences[0], IndependentReviewOccurrenceV1):
                reasons.append("current unavailable V2 result has no unique typed occurrence record")
                continue
            occurrence = occurrences[0]
            try:
                occurrence.validate()
            except (ReviewAssuranceError, ValueError):
                reasons.append("current separate-context occurrence record is malformed")
                continue
            if (occurrence.subject != review.subject
                    or occurrence.independent_review_v2_sha256 != review.sha256
                    or occurrence.reviewer_context_id != review.reviewer_context_id
                    or occurrence.execution_identity_context_id != review.execution_identity_context_id
                    or occurrence.profile_sha256 != review.profile_sha256
                    or occurrence.findings != review.findings):
                reasons.append("current occurrence report does not match its V2 provenance record")
                continue
            occurrence_has_unresolved_abc = any(
                f.severity in {"A", "B", "C"} and not f.resolved for f in occurrence.findings
            )
            if occurrence.review_outcome != "PASS" or occurrence_has_unresolved_abc:
                return ReviewCaptureEligibility(
                    "REVIEW_FAILED", host_surface, digest_tuple,
                    ("current completed separate-context review did not PASS or has unresolved A/B/C findings",),
                ).validate()
            continue
        if review.assurance in {"HOST_VERIFIED", "INDEPENDENT_ATTESTED"}:
            if review.verdict in {"FAIL", "BLOCKED", "CONCERNS"} or has_unresolved_abc:
                return ReviewCaptureEligibility(
                    "REVIEW_FAILED", host_surface, digest_tuple,
                    ("a current completed native review failed or has unresolved A/B/C findings",),
                ).validate()
            reasons.append("a current native review exists; use its ordinary assurance path")
        elif review.assurance == "SELF_REVIEW":
            reasons.append("self-review cannot establish host capture unavailability")
    if reasons:
        return ReviewCaptureEligibility("INVALID_EVIDENCE", host_surface, digest_tuple,
                                        tuple(dict.fromkeys(reasons))).validate()
    return ReviewCaptureEligibility("HOST_NATIVE_CAPTURE_UNAVAILABLE", host_surface,
                                    digest_tuple, ()).validate()


def write_independent_review_v2(path: Any, review: IndependentReviewV2) -> str:
    """Write V2 review once; callers must separately preserve captured native bytes."""
    from .audits import _write_once
    review.validate()
    _write_once(path, review.to_bytes(), "Independent Review V2")
    return review.sha256


def read_independent_review_v2(path: Any) -> IndependentReviewV2:
    from .audits import _safe_read
    return IndependentReviewV2.from_bytes(_safe_read(path, "Independent Review V2"))
