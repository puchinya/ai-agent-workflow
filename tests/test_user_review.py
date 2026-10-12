from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.delivery import ReadinessResult
from p_ases.evidence_store import VerificationSubject
from p_ases.user_review import (
    FeedbackSnapshot, ParentFeedbackSnapshot, ParentReviewSubject, ParentUserReviewSession,
    UserReviewError, UserReviewSession, UserReviewSubject, add_authenticated_chat_event,
    capture_authenticated_chat_event,
    evaluate_parent_user_review, evaluate_user_review, feedback_digest, merge_feedback_history,
    merge_parent_feedback_history, normalize_github_feedback,
    parent_feedback_snapshot_path, parent_review_session_path, read_parent_feedback_snapshot,
    read_parent_review_session, read_review_session, reject_unattested_chat_event,
    review_session_path, write_parent_feedback_snapshot, write_parent_review_session,
    write_review_session,
)

HEAD = "a" * 40
SUBJECT = VerificationSubject("octo/repo", 31, 37, 123, "b" * 64, "c" * 64, HEAD).validate()
READINESS = ReadinessResult("PASS", SUBJECT, (), ("d" * 64,), "e" * 64).validate()
USER_SUBJECT = UserReviewSubject(SUBJECT, READINESS.sha256)
CREATED = "2026-10-12T00:00:00Z"
PARENT_SUBJECT = ParentReviewSubject(
    "octo/repo", 26, "b" * 64,
    tuple((number, f"{number:040x}") for number in range(27, 33)), "c" * 64,
).validate()
PARENT_SESSION = ParentUserReviewSession(PARENT_SUBJECT, "2026-10-11T23:59:00Z").validate()


def github_review(identifier=4, *, state="APPROVED", head=HEAD, actor=42, login="puchinya",
                  actor_type="User", updated_at=CREATED):
    return {
        "id": identifier, "state": state, "commit_id": head, "body": "",
        "user": {"id": actor, "login": login, "type": actor_type},
        "submitted_at": CREATED, "updated_at": updated_at,
        "html_url": f"https://github.com/octo/repo/pull/37#pullrequestreview-{identifier}",
    }


def comment(identifier=6, *, user_id=42, actor_type="User", body="Please clarify", channel="pr-comment",
            commit_id=None):
    return {
        "id": identifier, "created_at": CREATED, "updated_at": CREATED, "body": body,
        "user": {"id": user_id, "login": "someone", "type": actor_type},
        "html_url": f"https://github.com/octo/repo/pull/37#issuecomment-{identifier}",
        "commit_id": commit_id or (HEAD if channel == "diff-comment" else None),
    }


def rows(*, reviews=(), issue=(), pr=(), diff=()):
    return normalize_github_feedback(
        issue_comments=issue, pr_comments=pr, pr_reviews=reviews, diff_comments=diff)


def evaluate(events, **kwargs):
    return evaluate_user_review(
        USER_SUBJECT, READINESS, HEAD, events, allowed_human_user_ids=(42,), **kwargs)


def parent_issue_comment(identifier=90, *, user_id=42, actor_type="User", decision="APPROVED",
                         subject_sha256=None, updated_at=CREATED):
    subject = subject_sha256 or PARENT_SUBJECT.sha256
    body = f"P-ASES-DECISION: {decision}\nP-ASES-SUBJECT: {subject}"
    return {
        "id": identifier, "created_at": CREATED, "updated_at": updated_at, "body": body,
        "user": {"id": user_id, "login": "puchinya", "type": actor_type},
        "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{identifier}",
    }


def parent_events(*, comments=()):
    return normalize_github_feedback(issue_comments=comments, pr_comments=(), pr_reviews=(), diff_comments=())


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

    def test_edited_formal_approval_requires_a_fresh_review_event(self):
        edited = rows(reviews=(github_review(updated_at="2026-10-12T00:01:00Z"),))
        self.assertEqual(evaluate(edited).status, "BLOCKED")

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

    def test_explicit_pr_conversation_and_inline_change_commands_return_to_same_execution_loop(self):
        directive = f"P-ASES-DECISION: CHANGES_REQUESTED\nP-ASES-HEAD: {HEAD}"
        for channel in ("pr-comment", "diff-comment"):
            with self.subTest(channel=channel):
                event_rows = rows(**{ "pr" if channel == "pr-comment" else "diff": (
                    comment(body=directive, channel=channel),
                )})
                event = event_rows[0]
                self.assertEqual(event.kind, "changes_requested")
                self.assertEqual(event.head_sha40, HEAD)
                result = evaluate(event_rows)
                self.assertEqual(result.status, "CHANGES_REQUESTED")
                self.assertEqual(result.next_phase, "execution")
                self.assertEqual(result.subject, USER_SUBJECT)

    def test_ordinary_quoted_malformed_and_unauthorized_comments_never_request_changes(self):
        invalid_bodies = (
            "Please fix this defect",
            f"> P-ASES-DECISION: CHANGES_REQUESTED\n> P-ASES-HEAD: {HEAD}",
            f"P-ASES-DECISION: CHANGES_REQUESTED\nP-ASES-HEAD: {HEAD}\nPlease fix this",
            f"P-ASES-DECISION: CHANGES_REQUESTED\nP-ASES-HEAD: {'z' * 40}",
        )
        for body in invalid_bodies:
            with self.subTest(body=body):
                event_rows = rows(pr=(comment(body=body),))
                self.assertEqual(event_rows[0].kind, "questions")
                self.assertNotEqual(evaluate(event_rows).next_phase, "execution")

        directive = f"P-ASES-DECISION: CHANGES_REQUESTED\nP-ASES-HEAD: {HEAD}"
        unauthorized = rows(pr=(comment(body=directive, user_id=99),))
        bot = rows(pr=(comment(body=directive, actor_type="Bot"),))
        self.assertEqual(unauthorized[0].kind, "changes_requested")
        self.assertNotEqual(evaluate(unauthorized).next_phase, "execution")
        self.assertNotEqual(evaluate(bot).next_phase, "execution")

    def test_inline_change_command_must_match_github_diff_commit_and_current_head(self):
        directive = f"P-ASES-DECISION: CHANGES_REQUESTED\nP-ASES-HEAD: {HEAD}"
        mismatched_diff = rows(diff=(comment(body=directive, channel="diff-comment", commit_id="f" * 40),))
        self.assertEqual(mismatched_diff[0].kind, "questions")
        stale = rows(pr=(comment(body=f"P-ASES-DECISION: CHANGES_REQUESTED\nP-ASES-HEAD: {'f' * 40}"),))
        stale_result = evaluate(stale)
        self.assertEqual(stale_result.status, "BLOCKED")
        self.assertNotEqual(stale_result.next_phase, "execution")
        edited_row = comment(body=directive)
        edited_row["updated_at"] = "2026-10-12T00:01:00Z"
        edited = rows(pr=(edited_row,))
        self.assertTrue(edited[0].edited)
        self.assertNotEqual(evaluate(edited).next_phase, "execution")

    def test_parent_review_requires_explicit_exact_subject_human_issue_decision(self):
        approved = parent_events(comments=(parent_issue_comment(),))
        self.assertEqual(approved[0].kind, "approved")
        self.assertEqual(approved[0].subject_sha256, PARENT_SUBJECT.sha256)
        result = evaluate_parent_user_review(
            PARENT_SUBJECT, PARENT_SESSION, approved, allowed_human_user_ids=(42,))
        self.assertEqual(result.status, "APPROVED")
        self.assertEqual(result.selected_decision_event, "issue-comment:90")

        quoted_row = parent_issue_comment(identifier=91)
        quoted_row["body"] = "> " + quoted_row["body"].replace("\n", "\n> ")
        ordinary_row = parent_issue_comment(identifier=92)
        ordinary_row["body"] = "Looks good to me"
        self.assertEqual(parent_events(comments=(quoted_row,))[0].kind, "questions")
        self.assertEqual(parent_events(comments=(ordinary_row,))[0].kind, "questions")
        for rows in (parent_events(comments=(quoted_row,)), parent_events(comments=(ordinary_row,)),
                     parent_events(comments=(parent_issue_comment(user_id=99),)),
                     parent_events(comments=(parent_issue_comment(actor_type="Bot"),)),
                     parent_events(comments=(parent_issue_comment(subject_sha256="d" * 64),))):
            self.assertEqual(evaluate_parent_user_review(
                PARENT_SUBJECT, PARENT_SESSION, rows, allowed_human_user_ids=(42,)).status, "PENDING")

    def test_parent_review_changes_stale_and_incomplete_decisions_fail_closed(self):
        requested = parent_events(comments=(parent_issue_comment(decision="CHANGES_REQUESTED"),))
        self.assertEqual(evaluate_parent_user_review(
            PARENT_SUBJECT, PARENT_SESSION, requested, allowed_human_user_ids=(42,)).status,
            "CHANGES_REQUESTED")
        edited = parent_events(comments=(parent_issue_comment(updated_at="2026-10-12T00:01:00Z"),))
        self.assertEqual(evaluate_parent_user_review(
            PARENT_SUBJECT, PARENT_SESSION, edited, allowed_human_user_ids=(42,)).status, "BLOCKED")
        approved_before_session = ParentUserReviewSession(PARENT_SUBJECT, "2026-10-12T00:01:00Z")
        self.assertEqual(evaluate_parent_user_review(
            PARENT_SUBJECT, approved_before_session, parent_events(comments=(parent_issue_comment(),)),
            allowed_human_user_ids=(42,)).status, "PENDING")
        simultaneous_session = ParentUserReviewSession(PARENT_SUBJECT, CREATED)
        self.assertEqual(evaluate_parent_user_review(
            PARENT_SUBJECT, simultaneous_session, parent_events(comments=(parent_issue_comment(),)),
            allowed_human_user_ids=(42,)).status,
            "PENDING")
        self.assertEqual(evaluate_parent_user_review(
            PARENT_SUBJECT, PARENT_SESSION, parent_events(comments=(parent_issue_comment(),)),
            allowed_human_user_ids=(42,), all_feedback_read=False).status, "BLOCKED")
        changed_subject = replace(PARENT_SUBJECT, integration_evidence_digest="f" * 64)
        with self.assertRaisesRegex(UserReviewError, "stale Integration subject"):
            evaluate_parent_user_review(
                changed_subject, PARENT_SESSION, parent_events(comments=(parent_issue_comment(),)),
                allowed_human_user_ids=(42,))

    def test_parent_review_deletion_tombstones_invalidate_approval_and_artifacts_are_immutable(self):
        first = ParentFeedbackSnapshot(PARENT_SUBJECT, parent_events(comments=(parent_issue_comment(),)), CREATED)
        current = ParentFeedbackSnapshot(PARENT_SUBJECT, (), "2026-10-12T00:02:00Z")
        merged = merge_parent_feedback_history(first, current)
        self.assertTrue(merged.events[0].deleted)
        result = evaluate_parent_user_review(
            PARENT_SUBJECT, PARENT_SESSION, merged.events, allowed_human_user_ids=(42,))
        self.assertEqual(result.status, "BLOCKED")

        edited_row = parent_issue_comment()
        edited_row["body"] = "Edited comment retaining the old API timestamp"
        edited_snapshot = ParentFeedbackSnapshot(
            PARENT_SUBJECT, parent_events(comments=(edited_row,)), "2026-10-12T00:03:00Z")
        edit_readback = merge_parent_feedback_history(first, edited_snapshot)
        self.assertTrue(edit_readback.events[0].edited)
        self.assertNotEqual(evaluate_parent_user_review(
            PARENT_SUBJECT, PARENT_SESSION, edit_readback.events,
            allowed_human_user_ids=(42,)).status, "APPROVED")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = parent_review_session_path(root, PARENT_SUBJECT)
            saved = write_parent_review_session(path, PARENT_SESSION)
            retry = write_parent_review_session(path, ParentUserReviewSession(
                PARENT_SUBJECT, "2026-10-12T00:05:00Z"))
            self.assertEqual(saved, PARENT_SESSION)
            self.assertEqual(retry, PARENT_SESSION)
            self.assertEqual(read_parent_review_session(path), PARENT_SESSION)
            snapshot_path = parent_feedback_snapshot_path(root, first)
            write_parent_feedback_snapshot(snapshot_path, first)
            self.assertEqual(read_parent_feedback_snapshot(snapshot_path), first)

    def test_latest_question_after_approval_requires_a_new_formal_decision(self):
        events = rows(reviews=(github_review(),), pr=(comment(body="Can we clarify this?"),))
        self.assertEqual(evaluate(events).status, "PENDING")

    def test_unresolved_thread_blocks_approval(self):
        result = evaluate(rows(reviews=(github_review(),)), unresolved_thread_ids=("thread-1",))
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.unresolved_thread_ids, ("thread-1",))

    def test_feedback_snapshot_is_canonical_and_deletions_become_tombstones(self):
        first = FeedbackSnapshot(USER_SUBJECT, rows(reviews=(github_review(),)), (), CREATED).validate()
        self.assertEqual(FeedbackSnapshot.from_bytes(first.to_bytes()), first)
        current = FeedbackSnapshot(USER_SUBJECT, (), (), "2026-10-12T00:01:00Z").validate()
        merged = merge_feedback_history(first, current)
        self.assertTrue(merged.events[0].deleted)
        self.assertEqual(evaluate(merged.events).status, "BLOCKED")

    def test_host_chat_adapter_must_attest_direct_unquoted_current_user(self):
        assertion = {
            "event_id": "chat:42", "actor_id": 42, "actor_login": "puchinya", "actor_type": "User",
            "created_at": CREATED, "updated_at": CREATED, "decision": "approved",
            "conversation_ref": "https://chat.example/conversation/123", "body_sha256": "f" * 64,
            "attestation_sha256": "e" * 64, "is_direct": True, "is_quoted": False,
            "has_attachments": False, "author_is_current_user": True, "head_sha40": HEAD,
            "subject_sha256": USER_SUBJECT.sha256,
        }
        event = capture_authenticated_chat_event("opaque host payload", lambda _payload: assertion)
        self.assertEqual(event.channel, "chat")
        self.assertEqual(evaluate((event,)).status, "APPROVED")
        stale_event = capture_authenticated_chat_event("stale host payload",
                                                      lambda _payload: {**assertion, "subject_sha256": "0" * 64})
        self.assertNotEqual(evaluate((stale_event,)).status, "APPROVED")
        with self.assertRaisesRegex(UserReviewError, "not a direct unquoted"):
            capture_authenticated_chat_event("quoted", lambda _payload: {**assertion, "is_quoted": True})

        session = UserReviewSession(USER_SUBJECT, "2026-10-11T23:59:00Z").validate()
        current = FeedbackSnapshot(USER_SUBJECT, (), (), CREATED).validate()
        with_chat = add_authenticated_chat_event(
            current, session, "opaque host payload", lambda _payload: assertion)
        github_repoll = FeedbackSnapshot(USER_SUBJECT, (), (), "2026-10-12T00:01:00Z").validate()
        retained = merge_feedback_history(with_chat, github_repoll)
        self.assertEqual(len(retained.events), 1)
        self.assertFalse(retained.events[0].deleted)
        self.assertEqual(evaluate(retained.events).status, "APPROVED")
        with self.assertRaisesRegex(UserReviewError, "predates"):
            add_authenticated_chat_event(
                current, UserReviewSession(USER_SUBJECT, "2026-10-12T00:01:00Z"),
                "stale host payload", lambda _payload: assertion)

    def test_review_session_is_immutable_and_retries_reuse_original_start(self):
        with tempfile.TemporaryDirectory() as temp:
            session = UserReviewSession(USER_SUBJECT, CREATED).validate()
            path = review_session_path(Path(temp), session)
            self.assertEqual(write_review_session(path, session), session)
            retry = UserReviewSession(USER_SUBJECT, "2026-10-12T00:02:00Z").validate()
            self.assertEqual(write_review_session(path, retry), session)
            self.assertEqual(read_review_session(path), session)
            self.assertEqual(UserReviewSession.from_bytes(session.to_bytes()), session)

    def test_old_approval_cannot_cross_adc_or_readiness_subject_change(self):
        approval = rows(reviews=(github_review(),))
        new_adc_subject = VerificationSubject(
            "octo/repo", 31, 37, 124, "f" * 64, "c" * 64, HEAD).validate()
        new_adc_readiness = ReadinessResult("PASS", new_adc_subject, (), ("d" * 64,), "e" * 64).validate()
        new_adc_user_subject = UserReviewSubject(new_adc_subject, new_adc_readiness.sha256).validate()
        for readiness, user_subject in (
            (new_adc_readiness, new_adc_user_subject),
            (ReadinessResult("PASS", SUBJECT, (), ("f" * 64,), "e" * 64).validate(), None),
        ):
            if user_subject is None:
                user_subject = UserReviewSubject(SUBJECT, readiness.sha256).validate()
            result = evaluate_user_review(
                user_subject, readiness, HEAD, approval, allowed_human_user_ids=(42,),
                required_after="2026-10-12T00:01:00Z",
            )
            self.assertEqual(result.status, "BLOCKED")
            self.assertTrue(any("predates" in reason for reason in result.reasons))

        simultaneous = evaluate(approval, required_after=CREATED)
        self.assertEqual(simultaneous.status, "BLOCKED")
        self.assertTrue(any("simultaneous" in reason for reason in simultaneous.reasons))

    def test_stale_or_pre_session_change_request_does_not_reopen_execution(self):
        before_session = rows(reviews=(github_review(state="CHANGES_REQUESTED"),))
        result = evaluate(before_session, required_after="2026-10-12T00:01:00Z")
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.next_phase, "user-review")
        stale_head = rows(reviews=(github_review(state="CHANGES_REQUESTED", head="f" * 40,
                                                 updated_at="2026-10-12T00:02:00Z"),))
        result = evaluate(stale_head, required_after="2026-10-12T00:01:00Z")
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.next_phase, "user-review")
        current_request = rows(reviews=(github_review(state="CHANGES_REQUESTED",
                                                      updated_at="2026-10-12T00:02:00Z"),))
        result = evaluate(current_request, required_after="2026-10-12T00:01:00Z")
        self.assertEqual(result.status, "CHANGES_REQUESTED")
        self.assertEqual(result.next_phase, "execution")

    def test_dismissed_formal_review_never_approves(self):
        result = evaluate(rows(reviews=(github_review(state="DISMISSED"),)))
        self.assertNotEqual(result.status, "APPROVED")


if __name__ == "__main__":
    unittest.main()
