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
from .branch_policy import BranchPolicyError, EffectiveBranchPolicy
from .checkpoint import CheckpointError, PRBinding
from .context import WorkContext, WorkContextError
from .evidence_store import VerificationSubject
from .path_safety import path_has_symlink
from .verification import RequiredCheckPolicy, VerificationResult, VERDICTS


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
class FinalDeliveryResult:
    """Final gates after Review Readiness; this result never grants merge authority."""

    status: str
    subject: VerificationSubject
    review_mode: str
    branch_policy_status: str
    branch_policy_sha256: str | None
    branch_policy_branch: str | None
    branch_policy_sources: tuple[str, ...]
    branch_policy_source_errors: tuple[tuple[str, int | None], ...]
    branch_policy_reason_codes: tuple[str, ...]
    branch_policy_required_actions: tuple[str, ...]
    user_review_sha256: str | None
    required_check_result_sha256: str | None
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]

    def validate(self) -> "FinalDeliveryResult":
        self.subject.validate()
        if self.status not in {"READY_FOR_EXPLICIT_MERGE_AUTHORIZATION", "BLOCKED"}:
            raise ReadinessError("Final Delivery status is invalid")
        if type(self.reasons) is not tuple or any(not isinstance(x, str) or not x for x in self.reasons):
            raise ReadinessError("Final Delivery reasons are invalid")
        if self.review_mode not in {"external_reviewer", "solo_owner"}:
            raise ReadinessError("Final Delivery review mode is invalid")
        if self.branch_policy_status not in {"VERIFIED", "NOT_CONFIGURED", "UNAVAILABLE", "UNVERIFIED", "MISMATCH"}:
            raise ReadinessError("Final Delivery branch-policy status is invalid")
        if self.branch_policy_branch is not None and (
                not isinstance(self.branch_policy_branch, str) or not self.branch_policy_branch):
            raise ReadinessError("Final Delivery branch-policy branch is invalid")
        for name, rows in (("sources", self.branch_policy_sources),
                           ("reason codes", self.branch_policy_reason_codes),
                           ("required actions", self.branch_policy_required_actions)):
            if (type(rows) is not tuple or any(not isinstance(x, str) or not x for x in rows)
                    or rows != tuple(sorted(set(rows)))):
                raise ReadinessError(f"Final Delivery branch-policy {name} are invalid")
        if (type(self.branch_policy_source_errors) is not tuple
                or any(type(row) is not tuple or len(row) != 2 or not isinstance(row[0], str) or not row[0]
                       or row[1] is not None and (type(row[1]) is not int or row[1] < 100 or row[1] > 599)
                       for row in self.branch_policy_source_errors)
                or self.branch_policy_source_errors != tuple(sorted(set(self.branch_policy_source_errors)))):
            raise ReadinessError("Final Delivery branch-policy source errors are invalid")
        if self.branch_policy_status == "VERIFIED" and self.branch_policy_required_actions:
            raise ReadinessError("verified Final Delivery branch policy cannot require administrator action")
        digests = (self.user_review_sha256, self.required_check_result_sha256, self.branch_policy_sha256)
        if any(value is not None and (not isinstance(value, str) or not SHA256.fullmatch(value)) for value in digests):
            raise ReadinessError("Final Delivery evidence digest is invalid")
        if (type(self.reason_codes) is not tuple or any(not isinstance(x, str) or not x for x in self.reason_codes)
                or self.reason_codes != tuple(sorted(set(self.reason_codes)))):
            raise ReadinessError("Final Delivery reason codes are invalid")
        if (type(self.reasons) is not tuple or any(not isinstance(x, str) or not x for x in self.reasons)):
            raise ReadinessError("Final Delivery reasons are invalid")
        if ((self.status == "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION") != (not self.reason_codes and not self.reasons)
                or self.status == "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION"
                and (any(x is None for x in digests) or self.branch_policy_status != "VERIFIED"
                     or self.branch_policy_branch is None or not self.branch_policy_sources)):
            raise ReadinessError("Final Delivery status and evidence are inconsistent")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        value = {"branch_policy_sha256": self.branch_policy_sha256,
                 "branch_policy_branch": self.branch_policy_branch,
                 "branch_policy_reason_codes": list(self.branch_policy_reason_codes),
                 "branch_policy_required_actions": list(self.branch_policy_required_actions),
                 "branch_policy_source_errors": [
                     {"http_status": code, "source": source}
                     for source, code in self.branch_policy_source_errors
                 ],
                 "branch_policy_sources": list(self.branch_policy_sources),
                 "branch_policy_status": self.branch_policy_status,
                 "required_check_result_sha256": self.required_check_result_sha256,
                 "reason_codes": list(self.reason_codes), "reasons": list(self.reasons),
                 "review_mode": self.review_mode, "schema": "PASES_FINAL_DELIVERY_V2",
                 "status": self.status, "subject": self.subject.as_dict(),
                 "user_review_sha256": self.user_review_sha256,
                 "merge_authorized": False}
        return hashlib.sha256(_canonical(value)).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"branch_policy_sha256": self.branch_policy_sha256,
                "branch_policy_branch": self.branch_policy_branch,
                "branch_policy_reason_codes": list(self.branch_policy_reason_codes),
                "branch_policy_required_actions": list(self.branch_policy_required_actions),
                "branch_policy_source_errors": [
                    {"http_status": code, "source": source}
                    for source, code in self.branch_policy_source_errors
                ],
                "branch_policy_sources": list(self.branch_policy_sources),
                "branch_policy_status": self.branch_policy_status,
                "final_delivery_sha256": self.sha256,
                "merge_authorized": False,
                "required_check_result_sha256": self.required_check_result_sha256,
                "reason_codes": list(self.reason_codes), "reasons": list(self.reasons),
                "review_mode": self.review_mode, "schema": "PASES_FINAL_DELIVERY_V2",
                "status": self.status, "subject": self.subject.as_dict(),
                "user_review_sha256": self.user_review_sha256}


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
    github_reviews: Iterable[dict[str, Any]],
    branch_policy: EffectiveBranchPolicy | None,
    required_check_policy: RequiredCheckPolicy,
    review_mode: str,
    repository_owner_type: str | None,
    repository_owner_id: int | None,
    authenticated_user_id: int | None,
    pr_author_id: int | None,
    mergeable: bool | None,
) -> FinalDeliveryResult:
    """Require mode-specific human review, exact checks, and verified effective policy."""
    subject.validate()
    reasons: list[str] = []
    reason_codes: set[str] = set()
    user_review_sha: str | None = None
    if user_review is None:
        reasons.append("exact-subject final User Review evidence is missing")
        reason_codes.add("USER_REVIEW_MISSING")
    else:
        try:
            user_review.validate()
            review_subject = user_review.subject.verification_subject
            if user_review.status != "APPROVED" or review_subject != subject:
                reasons.append("User Review is not APPROVED for the exact Verification subject")
                reason_codes.add("USER_REVIEW_NOT_APPROVED_FOR_SUBJECT")
            elif (review_mode == "solo_owner" and not user_review.selected_approval_event.startswith("issue-comment:")
                  or review_mode == "external_reviewer"
                  and not user_review.selected_approval_event.startswith(("pr-review:", "chat:"))):
                reasons.append("User Review approval carrier does not match the repository mode")
                reason_codes.add("USER_REVIEW_CARRIER_MODE_MISMATCH")
            else:
                user_review_sha = user_review.sha256
        except (AttributeError, TypeError, ValueError):
            reasons.append("final User Review evidence is malformed")
            reason_codes.add("USER_REVIEW_MALFORMED")
    check_result_sha: str | None = None
    if not isinstance(verification, VerificationResult):
        reasons.append("current #29 Verification result is missing")
        reason_codes.add("VERIFICATION_MISSING")
    else:
        try:
            verification.validate()
            if verification.status != "PASS" or verification.subject != subject:
                reasons.append("#29 Verification is not PASS for the exact final subject")
                reason_codes.add("VERIFICATION_SUBJECT_NOT_PASS")
            elif verification.check_result_sha256 is None:
                reasons.append("#29 Required Check Run evidence is missing")
                reason_codes.add("REQUIRED_CHECK_EVIDENCE_MISSING")
            else:
                check_result_sha = verification.check_result_sha256
                try:
                    if not isinstance(required_check_policy, RequiredCheckPolicy):
                        raise ValueError("trusted Required Check policy is missing")
                    required_check_policy.validate()
                    if verification.required_check_policy_sha256 != required_check_policy.sha256:
                        reasons.append("#29 Verification uses a different Required Check policy")
                        reason_codes.add("REQUIRED_CHECK_POLICY_STALE")
                except ValueError:
                    reasons.append("trusted Required Check policy is invalid")
                    reason_codes.add("REQUIRED_CHECK_POLICY_INVALID")
        except (AttributeError, TypeError, ValueError):
            reasons.append("#29 Verification result is malformed")
            reason_codes.add("VERIFICATION_MALFORMED")
    if not isinstance(required_check_policy, RequiredCheckPolicy):
        reasons.append("trusted Required Check policy is missing")
        reason_codes.add("REQUIRED_CHECK_POLICY_MISSING")
    if review_mode not in {"external_reviewer", "solo_owner"}:
        reasons.append("repository Final Delivery review mode is invalid")
        reason_codes.add("REVIEW_MODE_INVALID")
    if current_pr_head_sha40 != subject.pr_head_sha40:
        reasons.append("PR HEAD changed after the final review subject")
        reason_codes.add("PR_HEAD_STALE")
    if current_pr_state != "open" or current_pr_draft is not False:
        reasons.append("PR is not open and non-draft")
        reason_codes.add("PR_NOT_OPEN_NON_DRAFT")
    if github_review_head_sha40 != subject.pr_head_sha40:
        reasons.append("GitHub aggregate review readback belongs to a stale PR HEAD")
        reason_codes.add("FORMAL_REVIEW_HEAD_STALE")
    try:
        reviews = tuple(github_reviews)
    except TypeError:
        reviews = ()
        reasons.append("GitHub formal review collection is unavailable")
        reason_codes.add("FORMAL_REVIEW_COLLECTION_UNAVAILABLE")
    changed_requested = any(isinstance(row, dict) and row.get("state") == "CHANGES_REQUESTED"
                            and row.get("commit_id") == subject.pr_head_sha40 for row in reviews)
    if changed_requested or github_review_decision == "CHANGES_REQUESTED":
        reasons.append("GitHub has a current formal CHANGES_REQUESTED review")
        reason_codes.add("FORMAL_CHANGES_REQUESTED")
    if review_mode == "external_reviewer":
        if github_review_decision != "APPROVED":
            reasons.append("GitHub formal review decision is not APPROVED for the current HEAD")
            reason_codes.add("FORMAL_REVIEW_NOT_APPROVED")
        reviewer_ok = False
        author_id_valid = type(pr_author_id) is int and pr_author_id > 0
        for row in reviews:
            if not isinstance(row, dict):
                continue
            user = row.get("user")
            actor_id = user.get("id") if isinstance(user, dict) else None
            submitted = row.get("submitted_at")
            updated = row.get("updated_at")
            if (row.get("state") == "APPROVED" and row.get("commit_id") == subject.pr_head_sha40
                    and isinstance(user, dict) and user.get("type") == "User"
                    and type(actor_id) is int and actor_id > 0 and author_id_valid
                    and actor_id != pr_author_id and isinstance(submitted, str) and submitted
                    and (updated is None or updated == submitted)):
                reviewer_ok = True
                break
        if not reviewer_ok:
            reasons.append("no active formal approval by a different user on the current HEAD")
            reason_codes.add("INDEPENDENT_FORMAL_REVIEW_MISSING")
        if branch_policy is not None and branch_policy.minimum_approvals is not None \
                and branch_policy.minimum_approvals < 1:
            reasons.append("effective policy does not require external formal approval")
            reason_codes.add("FORMAL_REVIEW_POLICY_MISSING")
    else:
        if github_review_decision not in {None, "REVIEW_REQUIRED", "APPROVED"}:
            reasons.append("GitHub aggregate review state is unknown in solo-owner mode")
            reason_codes.add("FORMAL_REVIEW_STATE_UNKNOWN")
        identity_ids = (repository_owner_id, authenticated_user_id, pr_author_id)
        if (repository_owner_type != "User" or any(type(value) is not int or value < 1 for value in identity_ids)
                or len(set(identity_ids)) != 1):
            reasons.append("repository owner, authenticated user, and PR author are not the same personal User")
            reason_codes.add("SOLO_OWNER_IDENTITY_MISMATCH")
        other_current_reviews = [row for row in reviews if isinstance(row, dict)
                                 and row.get("commit_id") == subject.pr_head_sha40
                                 and row.get("state") in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
                                 and isinstance(row.get("user"), dict)
                                 and row["user"].get("type") == "User"
                                 and type(row["user"].get("id")) is int
                                 and row["user"]["id"] != repository_owner_id]
        if other_current_reviews:
            reasons.append("another user has a formal review on the current PR HEAD")
            reason_codes.add("OTHER_FORMAL_REVIEW_PRESENT")
    policy_sha: str | None = None
    policy_status = "UNVERIFIED"
    policy_branch: str | None = None
    policy_sources: tuple[str, ...] = ()
    policy_source_errors: tuple[tuple[str, int | None], ...] = ()
    policy_reason_codes: tuple[str, ...] = ()
    policy_required_actions: tuple[str, ...] = ()
    if not isinstance(branch_policy, EffectiveBranchPolicy):
        reasons.append("effective GitHub branch policy is unavailable")
        reason_codes.add("BRANCH_POLICY_UNAVAILABLE")
    else:
        try:
            branch_policy.validate()
            policy_status = branch_policy.status
            policy_sha = branch_policy.sha256
            policy_branch = branch_policy.branch
            policy_sources = branch_policy.source
            policy_source_errors = branch_policy.source_errors
            policy_reason_codes = branch_policy.reason_codes
            policy_required_actions = branch_policy.required_actions
            if branch_policy.status != "VERIFIED":
                reasons.append(f"effective GitHub branch policy is {branch_policy.status}")
                reason_codes.add("BRANCH_POLICY_" + branch_policy.status)
                reason_codes.update("POLICY_" + code for code in branch_policy.reason_codes)
            if branch_policy.review_mode != review_mode:
                reasons.append("effective branch policy was evaluated for a different review mode")
                reason_codes.add("BRANCH_POLICY_MODE_MISMATCH")
            if branch_policy.repository.casefold() != subject.repository.casefold():
                reasons.append("effective branch policy belongs to a different repository")
                reason_codes.add("BRANCH_POLICY_REPOSITORY_MISMATCH")
            if isinstance(required_check_policy, RequiredCheckPolicy) and branch_policy.required_checks != tuple(
                    sorted(required_check_policy.checks)):
                reasons.append("effective branch policy requires a different Check/App set")
                reason_codes.add("BRANCH_POLICY_CHECK_SET_MISMATCH")
            if branch_policy.pull_request_required is not True:
                reasons.append("effective branch policy does not require a pull request")
                reason_codes.add("PULL_REQUEST_POLICY_MISSING")
            if review_mode == "solo_owner" and (
                    branch_policy.minimum_approvals != 0 or branch_policy.force_push_disabled is not True
                    or branch_policy.bypass_actor_count != 0):
                reasons.append("solo-owner branch policy lacks approval-count-zero, no-force-push, or no-bypass proof")
                reason_codes.add("SOLO_OWNER_RULESET_REQUIREMENTS_MISMATCH")
        except (BranchPolicyError, ValueError):
            reasons.append("effective GitHub branch policy is malformed")
            reason_codes.add("BRANCH_POLICY_MALFORMED")
    if mergeable is not True:
        reasons.append("GitHub has not confirmed the PR as mergeable")
        reason_codes.add("PR_MERGEABILITY_UNVERIFIED")
    reasons = list(dict.fromkeys(reasons))
    codes = tuple(sorted(reason_codes))
    status = "BLOCKED" if reasons else "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION"
    return FinalDeliveryResult(
        status, subject, review_mode, policy_status, policy_sha,
        policy_branch, policy_sources, policy_source_errors, policy_reason_codes, policy_required_actions,
        user_review_sha, check_result_sha, codes, tuple(reasons),
    ).validate()


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
) -> ReadinessResult:
    """Pass only when every exact-subject proof and the open PR read back agree."""
    if not isinstance(subject, VerificationSubject):
        raise ReadinessError("Readiness requires an exact Verification subject")
    subject.validate()
    reasons: list[str] = []
    digest_refs: set[str] = set()
    required_check_policy_sha256: str | None = None
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


def readiness_path(root: Path, result: ReadinessResult) -> Path:
    result.validate()
    return Path(root).absolute() / ".p_ases" / "readiness" / str(result.subject.issue_number) / result.subject.sha256 / f"{result.sha256}.json"


def read_readiness(path: Path) -> ReadinessResult:
    location = Path(path)
    if path_has_symlink(location):
        raise ReadinessError("Readiness path must not traverse a symbolic link")
    try:
        return ReadinessResult.from_bytes(location.read_bytes())
    except OSError as exc:
        raise ReadinessError("Readiness result is missing or unreadable") from exc


def write_readiness(path: Path, result: ReadinessResult) -> str:
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
