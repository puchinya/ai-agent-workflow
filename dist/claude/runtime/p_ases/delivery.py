"""Pure Review Readiness aggregation. This module never starts User Review."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .acceptance import AcceptanceResult
from .audits import AuditError, IndependentReview, SelfAudit
from .checkpoint import CheckpointError, PRBinding
from .context import WorkContext, WorkContextError
from .evidence_store import VerificationSubject
from .path_safety import path_has_symlink
from .review_assurance import (
    IndependentReviewV2, ReviewAssuranceError, ReviewCaptureEligibility, evaluate_review_assurance,
)
from .review_unavailable_exception import ReviewUnavailableException
from .verification import VerificationResult, VERDICTS


class ReadinessError(ValueError):
    pass


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class PRReadback:
    repository: str
    issue_number: int
    pr_number: int
    state: str
    draft: bool
    base_ref: str
    base_sha40: str
    head_ref: str
    head_sha40: str
    head_repository: str
    closing_issue_number: int

    def validate(self) -> "PRReadback":
        if not isinstance(self.repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise ReadinessError("PR readback repository is invalid")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise ReadinessError("PR readback Issue number must be positive")
        if type(self.pr_number) is not int or self.pr_number < 1:
            raise ReadinessError("PR readback number must be positive")
        if not isinstance(self.state, str) or self.state not in {"open", "closed"}:
            raise ReadinessError("PR readback state is unknown")
        if type(self.draft) is not bool:
            raise ReadinessError("PR draft readback must be boolean")
        if not isinstance(self.base_ref, str) or not self.base_ref:
            raise ReadinessError("PR base ref readback is missing")
        if not isinstance(self.base_sha40, str) or not SHA40.fullmatch(self.base_sha40):
            raise ReadinessError("PR base SHA readback must be a full SHA-40")
        if not isinstance(self.head_ref, str) or not self.head_ref:
            raise ReadinessError("PR head ref readback is missing")
        if not isinstance(self.head_sha40, str) or not SHA40.fullmatch(self.head_sha40):
            raise ReadinessError("PR readback HEAD must be a full SHA-40")
        if not isinstance(self.head_repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.head_repository):
            raise ReadinessError("PR head repository readback is invalid")
        if type(self.closing_issue_number) is not int or self.closing_issue_number < 1:
            raise ReadinessError("PR closing Issue reference is missing")
        return self


@dataclass(frozen=True)
class ReadinessResult:
    status: str
    subject: VerificationSubject
    reasons: tuple[str, ...]
    evidence_sha256s: tuple[str, ...]
    required_check_policy_sha256: str | None = None

    def validate(self) -> "ReadinessResult":
        if not isinstance(self.status, str) or self.status not in VERDICTS:
            raise ReadinessError("Readiness result status is invalid")
        self.subject.validate()
        if type(self.reasons) is not tuple or any(not isinstance(reason, str) or not reason for reason in self.reasons):
            raise ReadinessError("Readiness result reasons are invalid")
        if (self.status == "PASS" and self.reasons) or (self.status != "PASS" and not self.reasons):
            raise ReadinessError("Readiness status and explanation reasons are inconsistent")
        if (type(self.evidence_sha256s) is not tuple
                or any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in self.evidence_sha256s)):
            raise ReadinessError("Readiness evidence digests are invalid")
        if self.evidence_sha256s != tuple(sorted(set(self.evidence_sha256s))):
            raise ReadinessError("Readiness evidence digests must be sorted and unique")
        if self.required_check_policy_sha256 is not None and not SHA256.fullmatch(self.required_check_policy_sha256):
            raise ReadinessError("Readiness Required Check policy digest is invalid")
        if self.status == "PASS" and self.required_check_policy_sha256 is None:
            raise ReadinessError("Readiness PASS requires an exact Required Check policy digest")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {
            "evidence_sha256s": list(self.evidence_sha256s),
            "policy_version": "PASES_REVIEW_READINESS_V1",
            "reasons": list(self.reasons),
            "required_check_policy_sha256": self.required_check_policy_sha256,
            "schema": "PASES_REVIEW_READINESS_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "evidence_sha256s": list(self.evidence_sha256s),
            "policy_version": "PASES_REVIEW_READINESS_V1",
            "reasons": list(self.reasons),
            "required_check_policy_sha256": self.required_check_policy_sha256,
            "schema": "PASES_REVIEW_READINESS_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
        }

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["readiness_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ReadinessResult":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReadinessError("Readiness result is not valid UTF-8 JSON") from exc
        expected = {
            "evidence_sha256s", "policy_version", "readiness_sha256", "reasons",
            "required_check_policy_sha256", "schema", "status", "subject",
        }
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_REVIEW_READINESS_V1"
                or value.get("policy_version") != "PASES_REVIEW_READINESS_V1"
                or not isinstance(value.get("evidence_sha256s"), list)
                or not isinstance(value.get("reasons"), list)):
            raise ReadinessError("Readiness result has unknown/missing fields or schema")
        result = cls(
            value["status"], VerificationSubject.from_dict(value["subject"]),
            tuple(value["reasons"]), tuple(value["evidence_sha256s"]),
            value["required_check_policy_sha256"],
        ).validate()
        if value["readiness_sha256"] != result.sha256 or result.to_bytes() != raw:
            raise ReadinessError("Readiness digest or canonical bytes do not match")
        return result

    @property
    def ready_for_user_review(self) -> bool:
        return self.status == "PASS"


@dataclass(frozen=True)
class ReadinessResultV2:
    status: str
    subject: VerificationSubject
    review_assurance: str
    profile_sha256: str
    exception_record_sha256: str | None
    exception_comment_id: int | None
    exception_comment_sha256: str | None
    owner_comment_id: int | None
    owner_comment_sha256: str | None
    accepted_risks: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence_sha256s: tuple[str, ...]
    required_check_policy_sha256: str | None

    def validate(self) -> "ReadinessResultV2":
        self.subject.validate()
        if self.status not in {"READY_WITH_EXCEPTION", "BLOCKED"} or self.review_assurance != "UNAVAILABLE":
            raise ReadinessError("Readiness V2 status or review assurance is invalid")
        for name, value in (("profile", self.profile_sha256),):
            if not isinstance(value, str) or not SHA256.fullmatch(value):
                raise ReadinessError(f"Readiness V2 {name} digest is invalid")
        for name, value in (("exception record", self.exception_record_sha256),
                            ("exception comment", self.exception_comment_sha256),
                            ("Owner comment", self.owner_comment_sha256),
                            ("Required Check policy", self.required_check_policy_sha256)):
            if value is not None and (not isinstance(value, str) or not SHA256.fullmatch(value)):
                raise ReadinessError(f"Readiness V2 {name} digest is invalid")
        for name, value in (("exception comment", self.exception_comment_id), ("Owner comment", self.owner_comment_id)):
            if value is not None and (type(value) is not int or value < 1):
                raise ReadinessError(f"Readiness V2 {name} ID is invalid")
        if (type(self.accepted_risks) is not tuple or self.accepted_risks != ("INDEPENDENT_REVIEW_NOT_PERFORMED",)
                or type(self.reasons) is not tuple
                or any(not isinstance(item, str) or not item for item in self.reasons)):
            raise ReadinessError("Readiness V2 risk or reason fields are invalid")
        if ((self.status == "READY_WITH_EXCEPTION") != (not self.reasons)
                or self.status == "READY_WITH_EXCEPTION"
                and (self.exception_record_sha256 is None or self.exception_comment_id is None
                     or self.exception_comment_sha256 is None or self.owner_comment_id is None
                     or self.owner_comment_sha256 is None or self.required_check_policy_sha256 is None)):
            raise ReadinessError("Readiness V2 status and exact exception evidence disagree")
        if (type(self.evidence_sha256s) is not tuple
                or any(not isinstance(item, str) or not SHA256.fullmatch(item) for item in self.evidence_sha256s)
                or self.evidence_sha256s != tuple(sorted(set(self.evidence_sha256s)))):
            raise ReadinessError("Readiness V2 evidence digests are invalid")
        if self.status == "READY_WITH_EXCEPTION":
            required_evidence = {self.profile_sha256, self.exception_record_sha256,
                                 self.exception_comment_sha256, self.owner_comment_sha256,
                                 self.required_check_policy_sha256}
            if not required_evidence.issubset(set(self.evidence_sha256s)):
                raise ReadinessError("Readiness V2 omits a required exact exception or policy digest")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"accepted_risks": list(self.accepted_risks),
                "evidence_sha256s": list(self.evidence_sha256s),
                "exception_comment_id": self.exception_comment_id,
                "exception_comment_sha256": self.exception_comment_sha256,
                "exception_record_sha256": self.exception_record_sha256,
                "disclosure": "No independent review was performed; code defects may go undetected.",
                "owner_comment_id": self.owner_comment_id,
                "owner_comment_sha256": self.owner_comment_sha256,
                "policy_version": "PASES_REVIEW_READINESS_V2",
                "profile_sha256": self.profile_sha256,
                "reasons": list(self.reasons),
                "required_check_policy_sha256": self.required_check_policy_sha256,
                "review_assurance": self.review_assurance,
                "schema": "PASES_REVIEW_READINESS_V2",
                "status": self.status,
                "subject": self.subject.as_dict()}

    def to_bytes(self) -> bytes:
        value = {**self.payload(), "readiness_sha256": self.sha256}
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ReadinessResultV2":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReadinessError("Readiness V2 is not valid UTF-8 JSON") from exc
        expected = {"accepted_risks", "disclosure", "evidence_sha256s", "exception_comment_id", "exception_comment_sha256",
                    "exception_record_sha256", "owner_comment_id", "owner_comment_sha256", "policy_version",
                    "profile_sha256", "reasons", "readiness_sha256", "required_check_policy_sha256",
                    "review_assurance", "schema", "status", "subject"}
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_REVIEW_READINESS_V2"
                or value.get("policy_version") != "PASES_REVIEW_READINESS_V2"
                or not isinstance(value.get("accepted_risks"), list)
                or value.get("disclosure") != "No independent review was performed; code defects may go undetected."
                or not isinstance(value.get("evidence_sha256s"), list)
                or not isinstance(value.get("reasons"), list)):
            raise ReadinessError("Readiness V2 has unknown or missing fields")
        result = cls(
            value["status"], VerificationSubject.from_dict(value["subject"]), value["review_assurance"],
            value["profile_sha256"], value["exception_record_sha256"], value["exception_comment_id"],
            value["exception_comment_sha256"], value["owner_comment_id"], value["owner_comment_sha256"],
            tuple(value["accepted_risks"]), tuple(value["reasons"]), tuple(value["evidence_sha256s"]),
            value["required_check_policy_sha256"],
        ).validate()
        if value["readiness_sha256"] != result.sha256 or result.to_bytes() != raw:
            raise ReadinessError("Readiness V2 digest or canonical bytes do not match")
        return result

    @property
    def ready_for_user_review(self) -> bool:
        return self.status == "READY_WITH_EXCEPTION"


@dataclass(frozen=True)
class FinalDeliveryResult:
    """Final gates after Review Readiness; this result never grants merge authority."""

    status: str
    subject: VerificationSubject
    user_review_sha256: str | None
    required_check_result_sha256: str | None
    branch_protection_sha256: str | None
    reasons: tuple[str, ...]

    def validate(self) -> "FinalDeliveryResult":
        self.subject.validate()
        if self.status not in {"READY_FOR_EXPLICIT_MERGE_AUTHORIZATION", "BLOCKED"}:
            raise ReadinessError("Final Delivery status is invalid")
        if type(self.reasons) is not tuple or any(not isinstance(x, str) or not x for x in self.reasons):
            raise ReadinessError("Final Delivery reasons are invalid")
        digests = (self.user_review_sha256, self.required_check_result_sha256, self.branch_protection_sha256)
        if any(value is not None and (not isinstance(value, str) or not SHA256.fullmatch(value)) for value in digests):
            raise ReadinessError("Final Delivery evidence digest is invalid")
        if ((self.status == "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION") != (not self.reasons)
                or self.status == "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION" and any(x is None for x in digests)):
            raise ReadinessError("Final Delivery status and evidence are inconsistent")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        value = {"branch_protection_sha256": self.branch_protection_sha256,
                 "required_check_result_sha256": self.required_check_result_sha256,
                 "reasons": list(self.reasons), "schema": "PASES_FINAL_DELIVERY_V1",
                 "status": self.status, "subject": self.subject.as_dict(),
                 "user_review_sha256": self.user_review_sha256,
                 "merge_authorized": False}
        return hashlib.sha256(_canonical(value)).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"branch_protection_sha256": self.branch_protection_sha256,
                "final_delivery_sha256": self.sha256,
                "merge_authorized": False,
                "required_check_result_sha256": self.required_check_result_sha256,
                "reasons": list(self.reasons), "schema": "PASES_FINAL_DELIVERY_V1",
                "status": self.status, "subject": self.subject.as_dict(),
                "user_review_sha256": self.user_review_sha256}


@dataclass(frozen=True)
class ReadinessCore:
    """Typed result for gates shared by ordinary and exception Readiness."""

    subject: VerificationSubject
    reasons: tuple[str, ...]
    evidence_sha256s: tuple[str, ...]
    required_check_policy_sha256: str | None
    base_ref: str | None
    base_sha40: str | None
    branch_ref: str | None
    pr_binding_sha256: str | None
    execution_binding_sha256: str | None

    def validate(self) -> "ReadinessCore":
        self.subject.validate()
        if type(self.reasons) is not tuple or any(not isinstance(item, str) or not item for item in self.reasons):
            raise ReadinessError("shared Readiness gate reasons are invalid")
        if (type(self.evidence_sha256s) is not tuple
                or any(not isinstance(item, str) or not SHA256.fullmatch(item)
                       for item in self.evidence_sha256s)
                or self.evidence_sha256s != tuple(sorted(set(self.evidence_sha256s)))):
            raise ReadinessError("shared Readiness evidence digests are invalid")
        if (self.required_check_policy_sha256 is not None
                and not SHA256.fullmatch(self.required_check_policy_sha256)):
            raise ReadinessError("shared Readiness Required Check policy digest is invalid")
        for name, value in (("base SHA", self.base_sha40), ("PRBinding", self.pr_binding_sha256),
                            ("ExecutionBinding", self.execution_binding_sha256)):
            if value is not None:
                pattern = SHA40 if name == "base SHA" else SHA256
                if not pattern.fullmatch(value):
                    raise ReadinessError(f"shared Readiness {name} identity digest is invalid")
        if self.base_ref is not None and (not isinstance(self.base_ref, str) or not self.base_ref):
            raise ReadinessError("shared Readiness base ref is invalid")
        if self.branch_ref is not None and (not isinstance(self.branch_ref, str) or not self.branch_ref):
            raise ReadinessError("shared Readiness branch ref is invalid")
        return self


def evaluate_readiness_core(
    *, subject: VerificationSubject, pr: PRReadback, pr_binding: PRBinding,
    work_context: WorkContext, verification: VerificationResult | None,
    acceptance: AcceptanceResult | None, self_audit: SelfAudit | None,
    required_item_ids: Iterable[str], required_checks_sha256: str | None,
    blocker_reasons: Iterable[str] = (),
) -> ReadinessCore:
    """Evaluate exact PR/work/Verification/Acceptance/Self-Audit gates only."""
    if not isinstance(subject, VerificationSubject):
        raise ReadinessError("Readiness requires an exact Verification subject")
    subject.validate()
    reasons: list[str] = []
    digest_refs: set[str] = set()
    required_check_policy_sha256: str | None = None
    bound_base_ref: str | None = None
    bound_base_sha40: str | None = None
    bound_branch_ref: str | None = None
    bound_pr_binding_sha256: str | None = None
    bound_execution_binding_sha256: str | None = None
    for reason in blocker_reasons:
        if not isinstance(reason, str) or not reason.strip():
            raise ReadinessError("Readiness blocker reasons must be non-empty text")
        reasons.append(reason.strip())
    pr_readback_valid = False
    if not isinstance(pr, PRReadback):
        reasons.append("GitHub PR readback is missing")
    else:
        try:
            pr.validate()
            pr_readback_valid = True
            bound_base_ref, bound_base_sha40 = pr.base_ref, pr.base_sha40
            bound_branch_ref = pr.head_ref
            if (pr.repository != subject.repository or pr.issue_number != subject.issue_number
                    or pr.pr_number != subject.pr_number or pr.state != "open" or pr.draft
                    or pr.head_sha40 != subject.pr_head_sha40 or pr.head_repository != subject.repository
                    or pr.closing_issue_number != subject.issue_number):
                reasons.append("GitHub PR readback is not the same open, non-draft, non-fork exact subject")
        except ReadinessError as exc:
            reasons.append(f"PR readback is invalid: {exc}")
    if not isinstance(pr_binding, PRBinding):
        reasons.append("PRBinding is missing")
    else:
        try:
            pr_binding.validate()
            if (pr_binding.repository != subject.repository or pr_binding.issue_number != subject.issue_number
                    or pr_binding.pr_number != subject.pr_number or pr_binding.adc_comment_id != subject.adc_comment_id
                    or pr_binding.adc_sha256 != subject.adc_sha256 or pr_binding.pr_head_sha40 != subject.pr_head_sha40
                    or (pr_readback_valid and (pr_binding.base_sha40 != pr.base_sha40
                                                or pr_binding.branch_ref != pr.head_ref))):
                reasons.append("PRBinding does not match the exact Verification subject")
            digest_refs.add(pr_binding.sha256)
            bound_pr_binding_sha256 = pr_binding.sha256
        except CheckpointError as exc:
            reasons.append(f"PRBinding is invalid: {exc}")
    if not isinstance(work_context, WorkContext):
        reasons.append("work context is missing")
    else:
        try:
            work_context.validate()
            binding = work_context.execution_binding
            if (binding.repository != subject.repository or binding.issue_number != subject.issue_number
                    or binding.adc_comment_id != subject.adc_comment_id or binding.adc_sha256 != subject.adc_sha256
                    or work_context.current_head_sha40 != subject.pr_head_sha40
                    or not work_context.worktree_clean
                    or (pr_readback_valid and (binding.base_sha != pr.base_sha40
                                               or binding.base_ref != pr.base_ref
                                               or work_context.branch_ref != pr.head_ref))):
                reasons.append("work context is stale, dirty, or bound to a different exact subject")
            digest_refs.add(work_context.execution_binding_sha256)
            bound_execution_binding_sha256 = work_context.execution_binding_sha256
        except WorkContextError as exc:
            reasons.append(f"work context is invalid: {exc}")
    if not isinstance(verification, VerificationResult):
        reasons.append("#29 Verification result is missing")
    else:
        try:
            verification.validate()
        except ValueError as exc:
            reasons.append(f"#29 Verification result is invalid: {exc}")
        else:
            if verification.subject != subject:
                reasons.append("#29 Verification result is stale or belongs to a different exact subject")
            if verification.status != "PASS":
                reasons.append(f"Verification status is {verification.status}")
            required_check_policy_sha256 = verification.required_check_policy_sha256
            if required_check_policy_sha256 is None or verification.check_result_sha256 is None:
                reasons.append("Verification has no trusted Required Check policy/result digest")
            digest_refs.add(verification.sha256)
            if verification.check_result_sha256 is not None:
                digest_refs.add(verification.check_result_sha256)
            if required_check_policy_sha256 is not None:
                digest_refs.add(required_check_policy_sha256)
    if not isinstance(required_checks_sha256, str) or not SHA256.fullmatch(required_checks_sha256):
        reasons.append("Required Checks result digest is missing or invalid")
    elif (verification is not None and verification.check_result_sha256 is not None
          and required_checks_sha256 != verification.check_result_sha256):
        reasons.append("Required Checks result differs from the #29 Verification readback")
    if not isinstance(acceptance, AcceptanceResult):
        reasons.append("Acceptance result is missing")
    else:
        try:
            acceptance.validate()
        except ValueError as exc:
            reasons.append(f"Acceptance result is invalid: {exc}")
        else:
            if acceptance.subject != subject:
                reasons.append("Acceptance result belongs to a different exact subject")
            if acceptance.status != "PASS":
                reasons.append(f"Acceptance status is {acceptance.status}")
            if (isinstance(verification, VerificationResult)
                    and acceptance.verification_result_sha256 != verification.sha256):
                reasons.append("Acceptance result was not evaluated from the current #29 Verification result")
            digest_refs.add(acceptance.sha256)
    if not isinstance(self_audit, SelfAudit):
        reasons.append("self-audit is missing")
    else:
        try:
            self_audit.validate(required_item_ids)
        except AuditError as exc:
            reasons.append(f"self-audit is incomplete or invalid: {exc}")
        else:
            if self_audit.subject != subject:
                reasons.append("self-audit belongs to a different exact subject")
            if self_audit.status != "PASS":
                reasons.append(f"self-audit status is {self_audit.status}")
            digest_refs.add(self_audit.sha256)
    return ReadinessCore(subject, tuple(reasons), tuple(sorted(digest_refs)),
                         required_check_policy_sha256, bound_base_ref, bound_base_sha40,
                         bound_branch_ref, bound_pr_binding_sha256,
                         bound_execution_binding_sha256).validate()


def evaluate_final_delivery(
    *,
    subject: VerificationSubject,
    user_review: Any,
    verification: VerificationResult | None,
    current_pr_head_sha40: str,
    current_pr_state: str,
    current_pr_draft: bool,
    github_review_decision: str | None,
    github_review_head_sha40: str | None,
    branch_protection: dict[str, Any] | None,
    required_check_names: Iterable[str],
    mergeable: bool | None,
) -> FinalDeliveryResult:
    """Require human review, GitHub review, checks, and branch protection separately."""
    subject.validate()
    reasons: list[str] = []
    user_review_sha: str | None = None
    if user_review is None:
        reasons.append("exact-subject final User Review evidence is missing")
    else:
        try:
            user_review.validate()
            review_subject = user_review.subject.verification_subject
            if user_review.status != "APPROVED" or review_subject != subject:
                reasons.append("User Review is not APPROVED for the exact Verification subject")
            else:
                user_review_sha = user_review.sha256
        except (AttributeError, TypeError, ValueError):
            reasons.append("final User Review evidence is malformed")
    check_result_sha: str | None = None
    if not isinstance(verification, VerificationResult):
        reasons.append("current #29 Verification result is missing")
    else:
        try:
            verification.validate()
            if verification.status != "PASS" or verification.subject != subject:
                reasons.append("#29 Verification is not PASS for the exact final subject")
            elif verification.check_result_sha256 is None:
                reasons.append("#29 Required Check Run evidence is missing")
            else:
                check_result_sha = verification.check_result_sha256
        except ValueError:
            reasons.append("#29 Verification result is malformed")
    if current_pr_head_sha40 != subject.pr_head_sha40:
        reasons.append("PR HEAD changed after the final review subject")
    if current_pr_state != "open" or current_pr_draft is not False:
        reasons.append("PR is not open and non-draft")
    if github_review_decision != "APPROVED" or github_review_head_sha40 != subject.pr_head_sha40:
        reasons.append("GitHub formal review decision is not APPROVED for the current HEAD")
    if not isinstance(branch_protection, dict):
        reasons.append("GitHub branch protection could not be read")
    else:
        required = tuple(sorted(set(required_check_names)))
        status_checks = branch_protection.get("required_status_checks")
        contexts = status_checks.get("contexts") if isinstance(status_checks, dict) else None
        review_policy = branch_protection.get("required_pull_request_reviews")
        if not required or not isinstance(contexts, list) or set(contexts) != set(required):
            reasons.append("branch protection does not require the exact configured Check set")
        if (not isinstance(review_policy, dict)
                or type(review_policy.get("required_approving_review_count")) is not int
                or review_policy["required_approving_review_count"] < 1):
            reasons.append("branch protection does not require a formal pull-request review")
    protection_sha = None if not isinstance(branch_protection, dict) else hashlib.sha256(_canonical(branch_protection)).hexdigest()
    if mergeable is not True:
        reasons.append("GitHub has not confirmed the PR as mergeable")
    status = "BLOCKED" if reasons else "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION"
    return FinalDeliveryResult(status, subject, user_review_sha, check_result_sha,
                               protection_sha, tuple(dict.fromkeys(reasons))).validate()


def evaluate_readiness(
    *,
    subject: VerificationSubject,
    pr: PRReadback,
    pr_binding: PRBinding,
    work_context: WorkContext,
    verification: VerificationResult | None,
    acceptance: AcceptanceResult | None,
    self_audit: SelfAudit | None,
    required_item_ids: Iterable[str],
    independent_review: IndependentReview | None,
    required_checks_sha256: str | None,
    blocker_reasons: Iterable[str] = (),
    independent_review_v2: IndependentReviewV2 | None = None,
    review_minimum_assurance: str | None = None,
    current_profile_sha256: str | None = None,
    execution_identity_context_id: str | None = None,
) -> ReadinessResult:
    """Pass only when every exact-subject proof and the open PR read back agree."""
    core = evaluate_readiness_core(
        subject=subject, pr=pr, pr_binding=pr_binding, work_context=work_context,
        verification=verification, acceptance=acceptance, self_audit=self_audit,
        required_item_ids=required_item_ids, required_checks_sha256=required_checks_sha256,
        blocker_reasons=blocker_reasons,
    )
    reasons = list(core.reasons)
    digest_refs = set(core.evidence_sha256s)
    required_check_policy_sha256 = core.required_check_policy_sha256
    if independent_review_v2 is not None:
        try:
            independent_review_v2.validate()
            if (review_minimum_assurance is None or current_profile_sha256 is None
                    or execution_identity_context_id is None):
                raise ReviewAssuranceError("Readiness requires the current profile and execution identity")
            assurance = evaluate_review_assurance(
                independent_review_v2, subject=subject,
                execution_identity_context_id=execution_identity_context_id,
                minimum_assurance=review_minimum_assurance,
                profile_sha256=current_profile_sha256,
            )
            if assurance.status != "PASS":
                reasons.extend(assurance.reasons)
            projection = independent_review_v2.as_v1_readiness_projection()
            if independent_review is not None and independent_review != projection:
                reasons.append("legacy projection differs from Independent Review V2")
            independent_review = projection
            digest_refs.add(independent_review_v2.sha256)
            digest_refs.add(current_profile_sha256)
        except (AuditError, ReviewAssuranceError, ValueError) as exc:
            reasons.append(f"Independent Review V2 assurance is invalid: {exc}")
            independent_review = None
    elif isinstance(independent_review, IndependentReview):
        reasons.append("V1-only Independent Review evidence does not satisfy the V2 assurance policy")

    if not isinstance(independent_review, IndependentReview):
        reasons.append("independent review artifact is missing")
    else:
        try:
            independent_review.validate()
        except AuditError as exc:
            reasons.append(f"independent review artifact is invalid: {exc}")
        else:
            if independent_review.subject != subject:
                reasons.append("independent review belongs to a different exact subject")
            if independent_review.verdict != "PASS":
                reasons.append(f"independent review verdict is {independent_review.verdict}")
            if independent_review.blocking_findings:
                reasons.append("independent review has unresolved A/B findings")
            digest_refs.add(independent_review.sha256)

    normalized_reasons = tuple(reasons)
    if any("status is FAIL" in reason or "verdict is FAIL" in reason for reason in reasons):
        status = "FAIL"
    elif any("CONCERNS" in reason for reason in reasons):
        status = "CONCERNS"
    elif reasons:
        status = "BLOCKED"
    else:
        status = "PASS"
    return ReadinessResult(status, subject, normalized_reasons, tuple(sorted(digest_refs)),
                           required_check_policy_sha256).validate()


def evaluate_readiness_with_exception(*, core: ReadinessCore, profile_sha256: str,
                                      eligibility: ReviewCaptureEligibility,
                                      exception: ReviewUnavailableException | None) -> ReadinessResultV2:
    """Emit a distinct degraded result without changing Independent Review assurance."""
    core.validate()
    eligibility.validate()
    if not isinstance(profile_sha256, str) or not SHA256.fullmatch(profile_sha256):
        raise ReadinessError("Readiness V2 requires the current committed profile digest")
    reasons = list(core.reasons)
    if eligibility.status != "HOST_NATIVE_CAPTURE_UNAVAILABLE":
        reasons.extend(eligibility.reasons or (f"review exception eligibility is {eligibility.status}",))
    record_sha: str | None = None
    exception_comment_id: int | None = None
    exception_comment_sha: str | None = None
    owner_comment_id: int | None = None
    owner_comment_sha: str | None = None
    evidence = set(core.evidence_sha256s)
    evidence.add(profile_sha256)
    if exception is None:
        reasons.append("exact Owner-authorized review exception record is missing")
    else:
        try:
            exception.validate()
            snapshot = exception.snapshot
            expected = {
                "repository": core.subject.repository,
                "issue_number": core.subject.issue_number,
                "pr_number": core.subject.pr_number,
                "adc_comment_id": core.subject.adc_comment_id,
                "adc_sha256": core.subject.adc_sha256,
                "verification_plan_sha256": core.subject.plan_sha256,
                "head_sha40": core.subject.pr_head_sha40,
                "profile_sha256": profile_sha256,
                "base_ref": core.base_ref,
                "base_sha40": core.base_sha40,
                "branch_ref": core.branch_ref,
                "execution_binding_sha256": core.execution_binding_sha256,
                "pr_binding_sha256": core.pr_binding_sha256,
                "host_surface": eligibility.host_surface,
                "capability_observation_sha256s": list(eligibility.observation_sha256s),
            }
            mismatches = [name for name, current in expected.items() if snapshot.get(name) != current]
            if mismatches:
                reasons.append("Owner exception is stale or mismatched: " + ", ".join(sorted(mismatches)))
            record_sha = exception.sha256
            exception_comment_id = exception.value["exception_comment_id"]
            exception_comment_sha = exception.value["exception_comment_sha256"]
            owner_comment_id = exception.value["owner_approval_comment_id"]
            owner_comment_sha = exception.value["owner_approval_sha256"]
            evidence.update((record_sha, exception.plan_sha256, exception_comment_sha, owner_comment_sha))
        except (ValueError, TypeError, AttributeError) as exc:
            reasons.append(f"Owner exception record is invalid: {exc}")
    normalized = tuple(dict.fromkeys(reasons))
    status = "BLOCKED" if normalized else "READY_WITH_EXCEPTION"
    return ReadinessResultV2(
        status=status, subject=core.subject, review_assurance="UNAVAILABLE", profile_sha256=profile_sha256,
        exception_record_sha256=record_sha, exception_comment_id=exception_comment_id,
        exception_comment_sha256=exception_comment_sha, owner_comment_id=owner_comment_id,
        owner_comment_sha256=owner_comment_sha, accepted_risks=("INDEPENDENT_REVIEW_NOT_PERFORMED",),
        reasons=normalized, evidence_sha256s=tuple(sorted(evidence)),
        required_check_policy_sha256=core.required_check_policy_sha256,
    ).validate()


@dataclass(frozen=True)
class FinalDeliveryResultV2:
    status: str
    subject: VerificationSubject
    review_assurance: str
    exception_record_sha256: str | None
    user_review_sha256: str | None
    required_check_result_sha256: str | None
    branch_protection_sha256: str | None
    accepted_risks: tuple[str, ...]
    reasons: tuple[str, ...]
    merge_authorized: bool = False

    def validate(self) -> "FinalDeliveryResultV2":
        self.subject.validate()
        if self.status not in {"READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION", "BLOCKED"}:
            raise ReadinessError("Final Delivery V2 status is invalid")
        if self.review_assurance != "UNAVAILABLE" or self.merge_authorized is not False:
            raise ReadinessError("Final Delivery V2 cannot claim review assurance or merge authority")
        for name, value in (("exception", self.exception_record_sha256),
                            ("User Review", self.user_review_sha256),
                            ("Required Checks", self.required_check_result_sha256),
                            ("branch protection", self.branch_protection_sha256)):
            if value is not None and (not isinstance(value, str) or not SHA256.fullmatch(value)):
                raise ReadinessError(f"Final Delivery V2 {name} digest is invalid")
        if (self.exception_record_sha256 is None and self.status != "BLOCKED"
                or self.exception_record_sha256 is not None
                and not SHA256.fullmatch(self.exception_record_sha256)):
            raise ReadinessError("Final Delivery V2 exception digest is missing or invalid")
        if (self.accepted_risks != ("INDEPENDENT_REVIEW_NOT_PERFORMED",)
                or type(self.reasons) is not tuple
                or any(not isinstance(item, str) or not item for item in self.reasons)):
            raise ReadinessError("Final Delivery V2 risk or reason fields are invalid")
        if ((self.status == "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION") != (not self.reasons)
                or self.status == "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION"
                and any(item is None for item in (self.exception_record_sha256, self.user_review_sha256,
                                                    self.required_check_result_sha256,
                                                    self.branch_protection_sha256))):
            raise ReadinessError("Final Delivery V2 status and evidence are inconsistent")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict(include_digest=False))).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        self.validate()
        value = {"accepted_risks": list(self.accepted_risks),
                 "branch_protection_sha256": self.branch_protection_sha256,
                 "disclosure": "No independent review was performed; code defects may go undetected.",
                 "exception_record_sha256": self.exception_record_sha256,
                 "merge_authorized": False,
                 "reasons": list(self.reasons),
                 "required_check_result_sha256": self.required_check_result_sha256,
                 "review_assurance": self.review_assurance,
                 "schema": "PASES_FINAL_DELIVERY_V2",
                 "status": self.status,
                 "subject": self.subject.as_dict(),
                 "user_review_sha256": self.user_review_sha256}
        if include_digest:
            value["final_delivery_sha256"] = self.sha256
        return value


def evaluate_final_delivery_with_exception(*, ordinary: FinalDeliveryResult,
                                           readiness: ReadinessResultV2) -> FinalDeliveryResultV2:
    ordinary.validate()
    readiness.validate()
    reasons = list(ordinary.reasons)
    if readiness.status != "READY_WITH_EXCEPTION" or readiness.subject != ordinary.subject:
        reasons.append("Readiness V2 is not READY_WITH_EXCEPTION for the exact Final Delivery subject")
    return FinalDeliveryResultV2(
        status="BLOCKED" if reasons else "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION",
        subject=ordinary.subject, review_assurance="UNAVAILABLE",
        exception_record_sha256=readiness.exception_record_sha256,
        user_review_sha256=ordinary.user_review_sha256,
        required_check_result_sha256=ordinary.required_check_result_sha256,
        branch_protection_sha256=ordinary.branch_protection_sha256,
        accepted_risks=("INDEPENDENT_REVIEW_NOT_PERFORMED",),
        reasons=tuple(dict.fromkeys(reasons)),
    ).validate()


def readiness_path(root: Path, result: ReadinessResult | ReadinessResultV2) -> Path:
    result.validate()
    return Path(root).absolute() / ".p_ases" / "readiness" / str(result.subject.issue_number) / result.subject.sha256 / f"{result.sha256}.json"


def read_readiness(path: Path) -> ReadinessResult | ReadinessResultV2:
    location = Path(path)
    if path_has_symlink(location):
        raise ReadinessError("Readiness path must not traverse a symbolic link")
    try:
        raw = location.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReadinessError("Readiness result is not valid UTF-8 JSON") from exc
        if isinstance(value, dict) and value.get("schema") == "PASES_REVIEW_READINESS_V2":
            return ReadinessResultV2.from_bytes(raw)
        return ReadinessResult.from_bytes(raw)
    except OSError as exc:
        raise ReadinessError("Readiness result is missing or unreadable") from exc


def write_readiness(path: Path, result: ReadinessResult | ReadinessResultV2) -> str:
    result.validate()
    destination = Path(path)
    if path_has_symlink(destination):
        raise ReadinessError("Readiness path must not traverse a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(destination):
        raise ReadinessError("Readiness path must not traverse a symbolic link")
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
            if read_readiness(destination) != result:
                raise ReadinessError("Readiness identity exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise ReadinessError("could not atomically store Readiness result") from exc
    if read_readiness(destination) != result:
        raise ReadinessError("Readiness result readback changed")
    return result.sha256
