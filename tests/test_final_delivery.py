from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.delivery import (
    FinalDeliveryResult, ReadinessCore, ReadinessResult, ReadinessResultV3,
    evaluate_final_delivery, evaluate_readiness_with_provenance_exception,
)
from p_ases.evidence_store import VerificationSubject
from p_ases.review_assurance import (
    IndependentReviewOccurrenceV1, IndependentReviewV2, ReviewCaptureEligibility,
    report_separate_context_review,
)
from p_ases.review_unavailable_chat import ChatReviewUnavailableException, ChatReviewUnavailablePlan, RECORD_SCHEMA
from p_ases.user_review import UserReviewResult, UserReviewSubject
from p_ases.verification import VerificationResult


HEAD = "a" * 40
SUBJECT = VerificationSubject("octo/repo", 31, 37, 123, "b" * 64, "c" * 64, HEAD).validate()
READINESS = ReadinessResult("PASS", SUBJECT, (), ("d" * 64,), "e" * 64).validate()
USER_SUBJECT = UserReviewSubject(SUBJECT, READINESS.sha256).validate()
USER_REVIEW = UserReviewResult("APPROVED", USER_SUBJECT, "f" * 64, (), "user-review",
                               "pr-review:5").validate()
VERIFICATION = VerificationResult("PASS", SUBJECT, (), "1" * 64, "2" * 64, ("3" * 64,), ()).validate()
PROTECTION = {
    "required_status_checks": {"contexts": ["ci"]},
    "required_pull_request_reviews": {"required_approving_review_count": 1},
}


def evaluate(**overrides):
    inputs = dict(
        subject=SUBJECT, user_review=USER_REVIEW, verification=VERIFICATION,
        current_pr_head_sha40=HEAD, current_pr_state="open", current_pr_draft=False,
        github_review_decision="APPROVED", github_review_head_sha40=HEAD,
        branch_protection=PROTECTION, required_check_names=("ci",), mergeable=True,
    )
    inputs.update(overrides)
    return evaluate_final_delivery(**inputs)


class FinalDeliveryTests(unittest.TestCase):
    def test_all_independent_gates_yield_only_merge_authorization_readiness(self):
        result = evaluate()
        self.assertEqual(result.status, "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION")
        self.assertFalse(result.as_dict()["merge_authorized"])
        self.assertEqual(len(result.sha256), 64)

    def test_github_review_branch_protection_or_exact_head_failure_blocks(self):
        cases = (
            {"github_review_decision": "REVIEW_REQUIRED"},
            {"github_review_head_sha40": "f" * 40},
            {"branch_protection": None},
            {"branch_protection": {**PROTECTION,
                                   "required_pull_request_reviews": {"required_approving_review_count": 0}}},
            {"branch_protection": {**PROTECTION,
                                   "required_status_checks": {"contexts": ["other"]}}},
            {"current_pr_head_sha40": "f" * 40},
            {"mergeable": False},
        )
        for values in cases:
            with self.subTest(values=values):
                self.assertEqual(evaluate(**values).status, "BLOCKED")

    def test_readiness_or_user_review_for_another_subject_blocks(self):
        stale = UserReviewResult("APPROVED", UserReviewSubject(
            VerificationSubject("octo/repo", 31, 37, 123, "b" * 64, "c" * 64, "f" * 40),
            READINESS.sha256), "f" * 64, (), "user-review", "pr-review:5").validate()
        self.assertEqual(evaluate(user_review=stale).status, "BLOCKED")
        self.assertEqual(evaluate(verification=None).status, "BLOCKED")

    def test_in_scope_comment_change_request_returns_to_execution_and_blocks_final_delivery(self):
        request = UserReviewResult(
            "CHANGES_REQUESTED", USER_SUBJECT, "f" * 64,
            ("authorized human requested in-scope changes",), "execution").validate()
        self.assertEqual(evaluate(user_review=request).status, "BLOCKED")

    def test_unavailable_provenance_requires_current_separate_context_review_and_round_trips_v3(self):
        subject = VerificationSubject("puchinya/ai-agent-workflow", 46, 67, 6399596796,
                                      "a" * 64, "b" * 64, "c" * 40).validate()
        profile = "d" * 64
        execution_identity = "execution-binding:" + "4" * 64
        review = report_separate_context_review(
            subject=subject, execution_identity_context_id=execution_identity,
            reviewer_context_id="separate-review-context", verdict="PASS", findings=(),
            profile_sha256=profile,
        )
        observation_sha = "f" * 64
        eligibility = ReviewCaptureEligibility(
            "HOST_NATIVE_CAPTURE_UNAVAILABLE", "codex_cloud", (observation_sha,), (),
        ).validate()
        core = ReadinessCore(
            subject=subject, reasons=(), evidence_sha256s=(), required_check_policy_sha256="1" * 64,
            base_ref="main", base_sha40="2" * 40,
            branch_ref="codex/issue-46-multi-host-independent-review",
            pr_binding_sha256="3" * 64, execution_binding_sha256="4" * 64,
        ).validate()
        raw_output = json.dumps({
            "findings": [], "reviewer_context_id": "separate-review-context",
            "schema": "PASES_CHILD_REVIEW_OUTPUT_V1", "subject": subject.as_dict(), "verdict": "PASS",
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        occurrence = IndependentReviewOccurrenceV1.from_captured_output(
            subject=subject, execution_identity_context_id=execution_identity,
            execution_binding_sha256=core.execution_binding_sha256,
            pr_binding_sha256=core.pr_binding_sha256, profile_sha256=profile,
            independent_review_v2_sha256=review.sha256, raw_output=raw_output,
        )
        plan = ChatReviewUnavailablePlan.create({
            "adc_comment_id": subject.adc_comment_id, "adc_sha256": subject.adc_sha256,
            "base_ref": "main", "base_sha40": "2" * 40,
            "branch_ref": core.branch_ref,
            "capability_observation_sha256s": [observation_sha],
            "execution_binding_sha256": core.execution_binding_sha256,
            "head_sha40": subject.pr_head_sha40, "host_surface": "codex_cloud",
            "independent_review_sha256": review.sha256,
            "review_occurrence_sha256": occurrence.sha256,
            "issue_id": 5846549384, "issue_number": 46, "owner_user_id": 3744776,
            "pr_binding_sha256": core.pr_binding_sha256, "pr_number": 67,
            "profile_sha256": profile, "reason": "HOST_NATIVE_CAPTURE_UNAVAILABLE",
            "repository": subject.repository, "repository_id": 1401910271,
            "risk": "INDEPENDENT_REVIEW_PROVENANCE_UNAVAILABLE",
            "verification_plan_sha256": subject.plan_sha256,
        }, generated_at="2026-10-25T00:00:00Z")
        exception = ChatReviewUnavailableException({
            "chat_decision_comment_id": 6400000001, "chat_decision_sha256": "5" * 64,
            "exception_comment_id": 6400000002, "exception_comment_sha256": "6" * 64,
            "plan": plan.value, "plan_sha256": plan.sha256,
            "publisher_user_id": 3744776, "schema": RECORD_SCHEMA,
        }).validate()
        result = evaluate_readiness_with_provenance_exception(
            core=core, profile_sha256=profile, eligibility=eligibility, review=review,
            occurrence=occurrence, exception=exception,
        )
        self.assertEqual(result.status, "READY_WITH_EXCEPTION")
        self.assertEqual(result.review_sha256, review.sha256)
        self.assertEqual(result.review_occurrence, "COMPLETED")
        self.assertEqual(result.review_occurrence_sha256, occurrence.sha256)
        self.assertEqual(result.review_outcome, "PASS")
        self.assertEqual(result.accepted_risks, ("INDEPENDENT_REVIEW_PROVENANCE_UNAVAILABLE",))
        self.assertEqual(ReadinessResultV3.from_bytes(result.to_bytes()), result)


if __name__ == "__main__":
    unittest.main()
