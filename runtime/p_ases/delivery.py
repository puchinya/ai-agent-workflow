"""Pure Review Readiness aggregation. This module never starts User Review."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .acceptance import AcceptanceResult
from .audits import AuditError, IndependentReview, SelfAudit
from .checkpoint import CheckpointError, PRBinding
from .context import WorkContext, WorkContextError
from .evidence_store import VerificationSubject
from .verification import GateResult, VERDICTS


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
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {
            "evidence_sha256s": list(self.evidence_sha256s),
            "reasons": list(self.reasons),
            "schema": "PASES_REVIEW_READINESS_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()

    @property
    def ready_for_user_review(self) -> bool:
        return self.status == "PASS"


def evaluate_readiness(
    *,
    subject: VerificationSubject,
    pr: PRReadback,
    pr_binding: PRBinding,
    work_context: WorkContext,
    verification: GateResult | None,
    acceptance: AcceptanceResult | None,
    self_audit: SelfAudit | None,
    required_item_ids: Iterable[str],
    independent_review: IndependentReview | None,
    required_checks: GateResult | None,
) -> ReadinessResult:
    """Pass only when every exact-subject proof and the open PR read back agree."""
    if not isinstance(subject, VerificationSubject):
        raise ReadinessError("Readiness requires an exact Verification subject")
    subject.validate()
    reasons: list[str] = []
    digest_refs: set[str] = set()

    pr_readback_valid = False
    if not isinstance(pr, PRReadback):
        reasons.append("GitHub PR readback is missing")
    else:
        try:
            pr.validate()
            pr_readback_valid = True
            if (pr.repository != subject.repository or pr.issue_number != subject.issue_number
                    or pr.pr_number != subject.pr_number or pr.state != "open" or pr.draft
                    or pr.head_sha40 != subject.pr_head_sha40 or pr.head_repository != subject.repository
                    or pr.closing_issue_number != subject.issue_number):
                reasons.append("GitHub PR readback is not the same open, non-draft, non-fork exact subject")
        except ReadinessError as exc:
            reasons.append(f"PR readback is invalid: {exc}")

    try:
        pr_binding.validate()
        if (pr_binding.repository != subject.repository or pr_binding.issue_number != subject.issue_number
                or pr_binding.pr_number != subject.pr_number or pr_binding.adc_comment_id != subject.adc_comment_id
                or pr_binding.adc_sha256 != subject.adc_sha256 or pr_binding.pr_head_sha40 != subject.pr_head_sha40
                or (pr_readback_valid and (pr_binding.base_sha40 != pr.base_sha40
                                            or pr_binding.branch_ref != pr.head_ref))):
            reasons.append("PRBinding does not match the exact Verification subject")
        digest_refs.add(pr_binding.sha256)
    except CheckpointError as exc:
        reasons.append(f"PRBinding is invalid: {exc}")

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
    except WorkContextError as exc:
        reasons.append(f"work context is invalid: {exc}")

    for label, result in (("Verification", verification), ("Required Checks", required_checks)):
        if not isinstance(result, GateResult):
            reasons.append(f"{label} result is missing")
            continue
        try:
            result.validate()
        except ValueError as exc:
            reasons.append(f"{label} result is invalid: {exc}")
            continue
        if result.subject != subject:
            reasons.append(f"{label} result is stale or belongs to a different exact subject")
        if result.status != "PASS":
            reasons.append(f"{label} status is {result.status}")

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
    return ReadinessResult(status, subject, normalized_reasons, tuple(sorted(digest_refs))).validate()
