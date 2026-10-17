"""Contract tests for the dedicated self-authored User Review relay evidence.

The runtime adapter is intentionally added after Issue #63's successor ADC and
phase gates pass. This source scaffold records the approved design boundary.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from p_ases.user_review_relay import (
    USER_REVIEW_DECISION_SCHEMA,
    UserReviewRelayError,
    parse_user_review_decision,
    verify_user_review_decision_history,
)


REPOSITORY = "puchinya/ai-agent-workflow"
ISSUE_NUMBER = 63
PR_NUMBER = 64
OWNER_ID = 3744776
SESSION_ID = "a" * 64
READINESS_SHA256 = "b" * 64
ADC_SHA256 = "c" * 64
PR_HEAD_SHA40 = "d" * 40


def decision_body(**overrides: object) -> str:
    payload: dict[str, object] = {
        "schema": USER_REVIEW_DECISION_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "pr_number": PR_NUMBER,
        "decision": "APPROVED",
        "owner_id": OWNER_ID,
        "review_session_id": SESSION_ID,
        "readiness_sha256": READINESS_SHA256,
        "adc_sha256": ADC_SHA256,
        "pr_head_sha40": PR_HEAD_SHA40,
        "evidence_channel": "delegated_github_relay",
        "predecessor_comment_id": 100,
    }
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def github_comment(body: str, *, comment_id: int = 101, actor_id: int = OWNER_ID,
                   created_at: str = "2026-10-17T09:00:00Z",
                   updated_at: str = "2026-10-17T09:00:00Z") -> SimpleNamespace:
    return SimpleNamespace(
        id=comment_id,
        body=body,
        user={"id": actor_id, "type": "User"},
        created_at=created_at,
        updated_at=updated_at,
        html_url="https://github.com/puchinya/ai-agent-workflow/issues/63#issuecomment-101",
    )


class UserReviewRelayTests(unittest.TestCase):
    def test_parses_only_canonical_dedicated_schema(self) -> None:
        body = decision_body()
        self.assertEqual(parse_user_review_decision(body)["schema"], USER_REVIEW_DECISION_SCHEMA)

        for invalid in (
            decision_body(schema="PASES_OWNER_DECISION_V1"),
            decision_body(unexpected="field"),
            decision_body(decision="CHANGES_REQUESTED"),
        ):
            with self.subTest(body=invalid), self.assertRaises(UserReviewRelayError):
                parse_user_review_decision(invalid)

    def test_accepts_one_exact_owner_record_for_current_session(self) -> None:
        comments = [github_comment(decision_body())]

        result = verify_user_review_decision_history(
            comments,
            repository=REPOSITORY,
            issue_number=ISSUE_NUMBER,
            pr_number=PR_NUMBER,
            owner_id=OWNER_ID,
            review_session_id=SESSION_ID,
            readiness_sha256=READINESS_SHA256,
            adc_sha256=ADC_SHA256,
            pr_head_sha40=PR_HEAD_SHA40,
        )

        self.assertEqual(result.comment_id, 101)

    def test_rejects_stale_subjects_wrong_actor_edits_and_cross_session_replay(self) -> None:
        for overrides, actor_id, updated_at in (
            ({"review_session_id": "e" * 64}, OWNER_ID, "2026-10-17T09:00:00Z"),
            ({"readiness_sha256": "e" * 64}, OWNER_ID, "2026-10-17T09:00:00Z"),
            ({"adc_sha256": "e" * 64}, OWNER_ID, "2026-10-17T09:00:00Z"),
            ({"pr_head_sha40": "e" * 40}, OWNER_ID, "2026-10-17T09:00:00Z"),
            ({}, OWNER_ID + 1, "2026-10-17T09:00:00Z"),
            ({}, OWNER_ID, "2026-10-17T09:01:00Z"),
        ):
            with self.subTest(overrides=overrides, actor_id=actor_id, updated_at=updated_at):
                comments = [github_comment(decision_body(**overrides), actor_id=actor_id,
                                           updated_at=updated_at)]
                with self.assertRaises(UserReviewRelayError):
                    verify_user_review_decision_history(
                        comments,
                        repository=REPOSITORY,
                        issue_number=ISSUE_NUMBER,
                        pr_number=PR_NUMBER,
                        owner_id=OWNER_ID,
                        review_session_id=SESSION_ID,
                        readiness_sha256=READINESS_SHA256,
                        adc_sha256=ADC_SHA256,
                        pr_head_sha40=PR_HEAD_SHA40,
                    )

    def test_rejects_duplicate_or_replayed_session_decisions(self) -> None:
        comments = [
            github_comment(decision_body(), comment_id=101),
            github_comment(decision_body(predecessor_comment_id=101), comment_id=102),
        ]

        with self.assertRaises(UserReviewRelayError):
            verify_user_review_decision_history(
                comments,
                repository=REPOSITORY,
                issue_number=ISSUE_NUMBER,
                pr_number=PR_NUMBER,
                owner_id=OWNER_ID,
                review_session_id=SESSION_ID,
                readiness_sha256=READINESS_SHA256,
                adc_sha256=ADC_SHA256,
                pr_head_sha40=PR_HEAD_SHA40,
            )


if __name__ == "__main__":
    unittest.main()
