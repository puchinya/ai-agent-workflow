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
import re
from dataclasses import dataclass
from typing import Any

from .audits import AuditError, IndependentReview, ReviewFinding
from .evidence_store import VerificationSubject


class ReviewAssuranceError(ValueError):
    pass


SHA256 = re.compile(r"^[0-9a-f]{64}$")
ASSURANCES = {"HOST_VERIFIED", "INDEPENDENT_ATTESTED", "SELF_REVIEW", "UNAVAILABLE"}
MINIMUMS = {"host_verified", "independent_attested"}
EVIDENCE_ORIGIN = "operator_captured_native_tool_result"
MAX_CAPTURE_BYTES = 2_000_000


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
            if self.assurance == "UNAVAILABLE" and self.verdict == "PASS":
                raise ReviewAssuranceError("UNAVAILABLE review cannot PASS")
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


def attest_native_review(*, subject: VerificationSubject, execution_identity_context_id: str,
                         request: bytes, terminal_return: bytes, child_output: bytes,
                         profile_sha256: str, host_spawn_id: str | None = None,
                         host_child_id: str | None = None, host_join_id: str | None = None) -> IndependentReviewV2:
    """Build V2 from exact bytes returned by a host's native delegation tool."""
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
    if review.assurance == "HOST_VERIFIED":
        # No current adapter provides a trusted, agent-nonwritable event verifier.
        reasons.append("HOST_VERIFIED is unavailable because no trusted host event verifier is configured")
    elif minimum_assurance == "host_verified":
        reasons.append("project requires HOST_VERIFIED Independent Review evidence")
    elif review.assurance != "INDEPENDENT_ATTESTED":
        reasons.append(f"review assurance {review.assurance} does not meet the project minimum")
    if review.verdict != "PASS":
        reasons.append(f"independent review verdict is {review.verdict}")
    if review.blocking_findings:
        reasons.append("independent review has unresolved A/B findings")
    return ReviewAssuranceDecision("BLOCKED" if reasons else "PASS", review.assurance,
                                   minimum_assurance, review.sha256, profile_sha256,
                                   tuple(dict.fromkeys(reasons))).validate()


def write_independent_review_v2(path: Any, review: IndependentReviewV2) -> str:
    """Write V2 review once; callers must separately preserve captured native bytes."""
    from .audits import _write_once
    review.validate()
    _write_once(path, review.to_bytes(), "Independent Review V2")
    return review.sha256


def read_independent_review_v2(path: Any) -> IndependentReviewV2:
    from .audits import _safe_read
    return IndependentReviewV2.from_bytes(_safe_read(path, "Independent Review V2"))
