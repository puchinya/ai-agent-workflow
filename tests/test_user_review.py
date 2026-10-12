from __future__ import annotations

import hashlib
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.delivery import ReadinessResult
from p_ases.evidence_store import VerificationSubject
from p_ases.user_review import (
    UserReviewError, UserReviewSubject, evaluate_user_review, feedback_digest,
    normalize_github_feedback, reject_unattested_chat_event,
)

HEAD = "a" * 40
SUBJECT = VerificationSubject("octo/repo", 31, 37, 123, "b" * 64, "c" * 64, HEAD).validate()
READINESS = ReadinessResult("PASS", SUBJECT, (), ("d" * 64,), "e" * 64).validate()
USER_SUBJECT = UserReviewSubject(SUBJECT, READINESS.sha256)
CREATED = "2026-10-12T00:00:00Z"


def github_review(identifier=4, *, state="APPROVED", head=HEAD, actor=42, login="puchinya",
                  actor_type="User", updated_at=CREATED):
    return {
        "id": identifier, "state": state, "commit_id": head, "body": "",
        "user": {"id": actor, "login": login, "type": actor_type},
        "submitted_at": CREATED, "updated_at": updated_at,
        "html_url": f"https://github.com/octo/repo/pull/37#pullrequestreview-{identifier}",
    }


def comment(identifier=6, *, user_id=42, body="Please clarify", channel="pr-comment"):
    return {
        "id": identifier, "created_at": CREATED, "updated_at": CREATED, "body": body,
        "user": {"id": user_id, "login": "someone", "type": "User"},
        "html_url": f"https://github.com/octo/repo/pull/37#issuecomment-{identifier}",
        "commit_id": HEAD if channel == "diff-comment" else None,
    }


def rows(*, reviews=(), issue=(), pr=(), diff=()):
    return normalize_github_feedback(
        issue_comments=issue, pr_comments=pr, pr_reviews=reviews, diff_comments=diff)


def evaluate(events, **kwargs):
    return evaluate_user_review(
        USER_SUBJECT, READINESS, HEAD, events, allowed_human_user_ids=(42,), **kwargs)


class UserReviewTests(unittest.TestCase):
    def test_u01_readiness_missing_or_stale_blocks_even_after_human_approval(self):
        events = rows(reviews=(github_review(),))
        self.assertEqual(evaluate(events).status, "APPROVED")
        stale_readiness = replace(READINESS, status="BLOCKED", reasons=("stale",))
        self.assertEqual(evaluate_user_review(
            USER_SUBJECT, stale_readiness, HEAD, events, allowed_human_user_ids=(42,)
        ).status, "BLOCKED")
        self.assertEqual(evaluate_user_review(
            USER_SUBJECT, READINESS, "f" * 40, events, allowed_human_user_ids=(42,)
        ).status, "BLOCKED")

    def test_u02_changes_requested_returns_to_execution_for_same_subject(self):
        events = rows(reviews=(github_review(state="CHANGES_REQUESTED"),))
        result = evaluate(events)
        self.assertEqual(result.status, "CHANGES_REQUESTED")
        self.assertEqual(result.next_phase, "execution")
        self.assertEqual(result.subject, USER_SUBJECT)
        self.assertEqual(evaluate(events, new_scope_requested=True).next_phase, "requirements")

    def test_u03_unattested_chat_is_not_trusted_user_feedback(self):
        with self.assertRaisesRegex(UserReviewError, "UNVERIFIABLE_CHAT_IDENTITY"):
            reject_unattested_chat_event({"actor_id": 42, "trusted": True, "text": "approved"})

    def test_u04_human_approval_is_not_github_merge_authorization(self):
        result = evaluate(rows(reviews=(github_review(),)))
        self.assertEqual(result.status, "APPROVED")
        self.assertEqual(result.next_phase, "user-review")
        self.assertIn("pr-review:", result.selected_approval_event)
        # The result only carries review evidence; no merge / branch-protection pass flag exists.
        self.assertFalse(hasattr(result, "merge_authorized"))

    def test_u05_bot_stale_head_and_changed_feedback_never_approve(self):
        self.assertNotEqual(evaluate(rows(reviews=(github_review(actor_type="Bot"),))).status,
                            "APPROVED")
        self.assertNotEqual(evaluate(rows(reviews=(github_review(actor=99),))).status,
                            "APPROVED")
        self.assertEqual(evaluate(rows(reviews=(github_review(head="f" * 40),))).status,
                         "BLOCKED")
        complete = rows(reviews=(github_review(),))
        self.assertEqual(evaluate(complete, previous_feedback_sha256=feedback_digest(complete)).status,
                         "APPROVED")
        altered = rows(reviews=(github_review(),), pr=(comment(body="changed"),))
        self.assertEqual(evaluate(altered, previous_feedback_sha256=feedback_digest(complete)).status,
                         "BLOCKED")
        with self.assertRaisesRegex(UserReviewError, "conflicting duplicate"):
            rows(pr=(comment(body="before"), comment(body="after")))

    def test_edits_identity_provenance_and_collection_fail_closed(self):
        with self.assertRaises(UserReviewError):
            rows(reviews=(github_review(updated_at="2026-10-11T23:59:59Z"),))
        with self.assertRaises(UserReviewError):
            rows(reviews=(github_review(actor_type="User", actor=0),))
        approved = rows(reviews=(github_review(),))
        self.assertEqual(evaluate(approved, all_feedback_surfaces_read=False).status, "BLOCKED")

    def test_all_four_github_surfaces_are_ordered_and_deduplicated(self):
        events = rows(reviews=(github_review(), github_review()), issue=(comment(1),),
                      pr=(comment(2),), diff=(comment(3, channel="diff-comment"),))
        self.assertEqual(len(events), 4)
        self.assertEqual(len(feedback_digest(events)), 64)
        self.assertEqual({event.channel for event in events},
                         {"issue-comment", "pr-comment", "pr-review", "diff-comment"})

    def test_no_implicit_approval_from_comment_text_or_quote(self):
        text = "Approved!\n> APPROVED\n"
        events = rows(pr=(comment(body=text),))
        self.assertNotEqual(evaluate(events).status, "APPROVED")


if __name__ == "__main__":
    unittest.main()
