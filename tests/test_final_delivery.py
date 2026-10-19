from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.current_base import CurrentBaseAdvanceEvidence
from p_ases.delivery import FinalDeliveryResult, ReadinessResult, evaluate_final_delivery
from p_ases.evidence_store import VerificationSubject
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
SOLO_SUBJECT = VerificationSubject(
    "puchinya/ai-agent-workflow", 63, 64, 90064, "b" * 64, "c" * 64, HEAD,
).validate()
SOLO_READINESS = ReadinessResult("PASS", SOLO_SUBJECT, (), ("d" * 64,), "e" * 64).validate()
SOLO_USER_SUBJECT = UserReviewSubject(SOLO_SUBJECT, SOLO_READINESS.sha256).validate()
SOLO_USER_REVIEW = UserReviewResult(
    "APPROVED", SOLO_USER_SUBJECT, "f" * 64, (), "user-review", "user-review-relay:55", (),
    {
        "evidence_type": "PASES_USER_REVIEW_DECISION_V3",
        "evidence_channel": "chat_confirmed_gh_v1",
        "comment_id": 55,
        "body_sha256": "1" * 64,
        "owner_id": 3744776,
        "created_at": "2026-10-18T00:00:00Z",
        "review_session_sha256": "2" * 64,
        "predecessor_comment_id": None,
        "feedback_sha256": "3" * 64,
        "plan_sha256": "4" * 64,
        "approval_scope_sha256": "5" * 64,
    },
).validate()
SOLO_VERIFICATION = VerificationResult("PASS", SOLO_SUBJECT, (), "1" * 64, "2" * 64, ("3" * 64,), ()).validate()


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
        self.assertEqual(result.as_dict()["schema"], "PASES_FINAL_DELIVERY_V1")
        self.assertNotIn("review_mode", result.as_dict())

    def test_v1_and_v2_digest_payloads_remain_byte_compatible(self):
        result = evaluate()
        expected_v1 = {
            "branch_protection_sha256": result.branch_protection_sha256,
            "required_check_result_sha256": result.required_check_result_sha256,
            "reasons": [], "schema": "PASES_FINAL_DELIVERY_V1",
            "status": result.status, "subject": SUBJECT.as_dict(),
            "user_review_sha256": result.user_review_sha256, "merge_authorized": False,
        }
        canonical_v1 = json.dumps(expected_v1, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")
        self.assertEqual(result.sha256, hashlib.sha256(canonical_v1).hexdigest())

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

    def test_final_delivery_requires_and_binds_verified_activation_base_advance(self):
        frozen, current = "4" * 40, "5" * 40
        self.assertEqual(evaluate(current_pr_base_sha40=current, frozen_base_sha40=frozen).status, "BLOCKED")
        evidence = CurrentBaseAdvanceEvidence(
            repository=SUBJECT.repository, issue_number=SUBJECT.issue_number,
            pr_number=SUBJECT.pr_number, pr_id=900, branch_ref="pases/work",
            frozen_base_sha40=frozen, current_base_sha40=current,
            activation_issue_number=57, activation_record_id=901, activation_record_sha256="1" * 64,
            setup_pr_number=902, setup_pr_id=903, setup_branch="pases/consumer-activation-57-abc12345",
            setup_head_sha40="1" * 40, setup_merge_sha40="2" * 40,
            original_pr_binding_sha256="3" * 64, original_pr_head_sha40="6" * 40,
            transition_pr_head_sha40=HEAD, activation_profile_sha256="7" * 64,
            original_code_patch_sha256="8" * 64, transition_code_patch_sha256="8" * 64,
        ).validate()
        result = evaluate(
            current_pr_base_sha40=current, frozen_base_sha40=frozen,
            current_base_advance=evidence,
        )
        self.assertEqual(result.status, "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION")
        self.assertEqual(result.current_base_advance_sha256, evidence.sha256)
        self.assertEqual(result.as_dict()["schema"], "PASES_FINAL_DELIVERY_V2")
        expected_v2 = {
            "branch_protection_sha256": result.branch_protection_sha256,
            "required_check_result_sha256": result.required_check_result_sha256,
            "reasons": [], "schema": "PASES_FINAL_DELIVERY_V2",
            "status": result.status, "subject": SUBJECT.as_dict(),
            "user_review_sha256": result.user_review_sha256, "merge_authorized": False,
            "current_base_advance_sha256": evidence.sha256,
        }
        canonical_v2 = json.dumps(expected_v2, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")
        self.assertEqual(result.sha256, hashlib.sha256(canonical_v2).hexdigest())

    def test_solo_owner_uses_v3_without_reading_or_claiming_ruleset_policy(self):
        result = evaluate_final_delivery(
            subject=SOLO_SUBJECT, user_review=SOLO_USER_REVIEW, verification=SOLO_VERIFICATION,
            current_pr_head_sha40=HEAD, current_pr_state="open", current_pr_draft=False,
            github_review_decision=None, github_review_head_sha40=None,
            branch_protection=None, required_check_names=("ci",), mergeable=True,
            review_mode="solo_owner",
        )
        value = result.as_dict()
        self.assertEqual(result.status, "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION")
        self.assertEqual(value["schema"], "PASES_FINAL_DELIVERY_V3")
        self.assertEqual(value["review_mode"], "solo_owner")
        self.assertIsNone(value["branch_protection_sha256"])
        self.assertFalse(value["merge_authorized"])
        expected = {
            "branch_protection_sha256": None,
            "required_check_result_sha256": result.required_check_result_sha256,
            "reasons": [], "schema": "PASES_FINAL_DELIVERY_V3",
            "status": result.status, "subject": SOLO_SUBJECT.as_dict(),
            "user_review_sha256": result.user_review_sha256, "merge_authorized": False,
            "review_mode": "solo_owner",
        }
        canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
        self.assertEqual(result.sha256, hashlib.sha256(canonical).hexdigest())

    def test_solo_owner_still_requires_all_pases_gates_and_exact_current_head(self):
        base = dict(
            subject=SOLO_SUBJECT, user_review=SOLO_USER_REVIEW, verification=SOLO_VERIFICATION,
            current_pr_head_sha40=HEAD, current_pr_state="open", current_pr_draft=False,
            github_review_decision=None, github_review_head_sha40=None,
            branch_protection=None, required_check_names=("ci",), mergeable=True,
            review_mode="solo_owner",
        )
        for overrides in (
            {"verification": None},
            {"user_review": None},
            {"current_pr_head_sha40": "f" * 40},
            {"mergeable": False},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(evaluate_final_delivery(**(base | overrides)).status, "BLOCKED")
        self.assertEqual(evaluate(branch_protection=None).status, "BLOCKED")

    def test_ready_without_branch_policy_cannot_use_legacy_schema(self):
        with self.assertRaisesRegex(ValueError, "status and evidence"):
            FinalDeliveryResult(
                "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION", SOLO_SUBJECT, "f" * 64,
                "1" * 64, None, (),
            ).validate()


if __name__ == "__main__":
    unittest.main()
