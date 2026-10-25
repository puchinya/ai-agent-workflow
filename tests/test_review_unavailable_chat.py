from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.review_unavailable_chat import (
    ChatExceptionError, ChatReviewUnavailableException, ChatReviewUnavailablePlan,
    RECORD_SCHEMA, RISK,
)


class ChatReviewUnavailableTests(unittest.TestCase):
    def snapshot(self):
        return {
            "adc_comment_id": 6399596796, "adc_sha256": "a" * 64,
            "base_ref": "main", "base_sha40": "b" * 40,
            "branch_ref": "codex/issue-46-multi-host-independent-review",
            "capability_observation_sha256s": ["c" * 64],
            "execution_binding_sha256": "d" * 64, "head_sha40": "e" * 40,
            "host_surface": "codex_cloud", "independent_review_sha256": "f" * 64,
            "review_occurrence_sha256": "9" * 64,
            "issue_id": 5846549384, "issue_number": 46, "owner_user_id": 3744776,
            "pr_binding_sha256": "1" * 64, "pr_number": 67,
            "profile_sha256": "2" * 64, "reason": "HOST_NATIVE_CAPTURE_UNAVAILABLE",
            "repository": "puchinya/ai-agent-workflow", "repository_id": 1401910271,
            "risk": RISK, "verification_plan_sha256": "3" * 64,
        }

    def test_plan_binds_the_actual_review_and_exact_chat_scope(self):
        plan = ChatReviewUnavailablePlan.create(self.snapshot(), generated_at="2026-10-25T00:00:00Z")
        restored = ChatReviewUnavailablePlan.from_bytes(plan.to_bytes())
        self.assertEqual(restored, plan)
        self.assertEqual(restored.approval_scope["review_sha256"], "f" * 64)
        self.assertEqual(restored.approval_scope["review_occurrence_sha256"], "9" * 64)
        self.assertEqual(restored.approval_scope["plan_sha256"], restored.sha256)
        self.assertEqual(len(restored.approval_scope_sha256), 64)

    def test_old_not_performed_risk_is_not_reinterpreted(self):
        snapshot = self.snapshot()
        snapshot["risk"] = "INDEPENDENT_REVIEW_NOT_PERFORMED"
        with self.assertRaisesRegex(ChatExceptionError, "outside the approved"):
            ChatReviewUnavailablePlan.create(snapshot)

    def test_chat_receipt_round_trips_separate_decision_and_recorder_metadata(self):
        plan = ChatReviewUnavailablePlan.create(self.snapshot(), generated_at="2026-10-25T00:00:00Z")
        record = ChatReviewUnavailableException({
            "chat_decision_comment_id": 6400000001,
            "chat_decision_sha256": "4" * 64,
            "exception_comment_id": 6400000002,
            "exception_comment_sha256": "5" * 64,
            "plan": plan.value, "plan_sha256": plan.sha256,
            "publisher_user_id": 3744776, "schema": RECORD_SCHEMA,
        }).validate()
        self.assertEqual(ChatReviewUnavailableException.from_bytes(record.to_bytes()), record)


if __name__ == "__main__":
    unittest.main()
