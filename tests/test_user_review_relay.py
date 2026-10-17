"""Contract tests for the dedicated self-authored User Review relay evidence.

The relay runtime remains gated on Issue #63's successor ADC and phase evidence.
These tests define the verifier, evaluator, and persistence contract in advance.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.delivery import ReadinessResult
from p_ases.evidence_store import VerificationSubject
from p_ases.cli import _read_review_record
from p_ases.user_review import (
    FeedbackEvent,
    FeedbackSnapshot,
    UserReviewError,
    UserReviewResult,
    UserReviewSession,
    UserReviewSubject,
    evaluate_user_review,
    feedback_digest,
)
from p_ases.user_review_relay import (
    USER_REVIEW_DECISION_SCHEMA,
    USER_REVIEW_DECISION_SCHEMA_V2,
    UserReviewDecisionHistory,
    UserReviewRelayError,
    parse_user_review_decision,
    publish_owner_local_user_review_decision,
    verify_user_review_decision_history,
)


REPOSITORY = "puchinya/ai-agent-workflow"
ISSUE_NUMBER = 63
PR_NUMBER = 64
OWNER_ID = 3744776
READ_ONLY_VERIFIER_ID = 91827364
ADC_SHA256 = "c" * 64
PLAN_SHA256 = "e" * 64
PR_HEAD_SHA40 = "d" * 40
SESSION_STARTED_AT = "2026-10-17T09:00:00Z"
COMMENT_CREATED_AT = "2026-10-17T09:01:00Z"

VERIFICATION_SUBJECT = VerificationSubject(
    REPOSITORY, ISSUE_NUMBER, PR_NUMBER, 9001, ADC_SHA256, PLAN_SHA256, PR_HEAD_SHA40
).validate()
READINESS = ReadinessResult("PASS", VERIFICATION_SUBJECT, (), ("f" * 64,), "a" * 64).validate()
REVIEW_SUBJECT = UserReviewSubject(VERIFICATION_SUBJECT, READINESS.sha256).validate()
SESSION = UserReviewSession(REVIEW_SUBJECT, SESSION_STARTED_AT).validate()


def decision_body(**overrides: object) -> str:
    payload: dict[str, object] = {
        "schema": USER_REVIEW_DECISION_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "pr_number": PR_NUMBER,
        "decision": "APPROVED",
        "owner_id": OWNER_ID,
        "review_session_id": SESSION.sha256,
        "readiness_sha256": READINESS.sha256,
        "adc_sha256": ADC_SHA256,
        "pr_head_sha40": PR_HEAD_SHA40,
        "evidence_channel": "delegated_github_relay",
        "predecessor_comment_id": None,
    }
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def owner_local_decision_body(*, feedback_sha256: str, plan_sha256: str,
                              **overrides: object) -> str:
    payload = json.loads(decision_body())
    payload.update({
        "schema": USER_REVIEW_DECISION_SCHEMA_V2,
        "evidence_channel": "owner_local_tty_v1",
        "feedback_sha256": feedback_sha256,
        "plan_sha256": plan_sha256,
    })
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def github_comment(
    body: str,
    *,
    comment_id: int = 101,
    actor_id: int = OWNER_ID,
    created_at: str = COMMENT_CREATED_AT,
    updated_at: str | None = None,
    comment_url_repo: str = REPOSITORY,
    comment_url_id: int | None = None,
    source_repo: str = REPOSITORY,
    source_issue: int = ISSUE_NUMBER,
    html_url_repo: str = REPOSITORY,
    html_url_issue: int = ISSUE_NUMBER,
    html_url_comment_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=comment_id,
        body=body,
        user={"id": actor_id, "type": "User", "login": "puchinya"},
        created_at=created_at,
        updated_at=updated_at or created_at,
        url=(f"https://api.github.com/repos/{comment_url_repo}/issues/comments/"
             f"{comment_url_id if comment_url_id is not None else comment_id}"),
        issue_url=f"https://api.github.com/repos/{source_repo}/issues/{source_issue}",
        html_url=(f"https://github.com/{html_url_repo}/issues/{html_url_issue}"
                  f"#issuecomment-{html_url_comment_id if html_url_comment_id is not None else comment_id}"),
    )


def decision_history(*comments: SimpleNamespace, complete: bool = True,
                     direct_before: dict[int, object] | None = None,
                     direct_after: dict[int, object] | None = None) -> UserReviewDecisionHistory:
    before = direct_before if direct_before is not None else {row.id: row for row in comments}
    after = direct_after if direct_after is not None else {row.id: row for row in comments}
    return UserReviewDecisionHistory(
        listed_comments=tuple(comments),
        direct_before=before,
        direct_after=after,
        pagination_complete=complete,
    )


def verify(history: UserReviewDecisionHistory, session: UserReviewSession = SESSION):
    return verify_user_review_decision_history(
        history,
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        pr_number=PR_NUMBER,
        repository_owner_user_id=OWNER_ID,
        authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
        session=session,
        readiness_sha256=READINESS.sha256,
        adc_sha256=ADC_SHA256,
        pr_head_sha40=PR_HEAD_SHA40,
    )


def feedback_snapshot(*events: FeedbackEvent, unresolved: tuple[str, ...] = ()) -> FeedbackSnapshot:
    return FeedbackSnapshot(
        REVIEW_SUBJECT,
        tuple(sorted(events, key=lambda row: (row.channel, row.event_id))),
        tuple(sorted(set(unresolved))),
        "2026-10-17T09:02:00Z",
    ).validate()


def carrier_feedback_event(comment: SimpleNamespace) -> FeedbackEvent:
    return FeedbackEvent(
        channel="issue-comment",
        event_id=str(comment.id),
        actor_id=comment.user["id"],
        actor_login=comment.user["login"],
        actor_type=comment.user["type"],
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        kind="questions",
        head_sha40=None,
        body_sha256=hashlib.sha256(comment.body.encode("utf-8")).hexdigest(),
        source_url=comment.html_url,
    ).validate()


class UserReviewRelayTests(unittest.TestCase):
    def test_parses_only_canonical_dedicated_schema(self) -> None:
        body = decision_body()
        self.assertEqual(parse_user_review_decision(body)["schema"], USER_REVIEW_DECISION_SCHEMA)

        for invalid in (
            decision_body(schema="PASES_OWNER_DECISION_V1"),
            decision_body(unexpected="field"),
            decision_body(decision="CHANGES_REQUESTED"),
            json.dumps(json.loads(body), indent=2),
        ):
            with self.subTest(body=invalid), self.assertRaises(UserReviewRelayError):
                parse_user_review_decision(invalid)

    def test_verifies_genesis_for_the_actual_session_and_returns_typed_evidence(self) -> None:
        comment = github_comment(decision_body())
        approval = verify(decision_history(comment))

        self.assertEqual(approval.comment_id, 101)
        self.assertEqual(approval.review_session_sha256, SESSION.sha256)
        self.assertEqual(approval.owner_id, OWNER_ID)
        self.assertEqual(approval.predecessor_comment_id, None)
        self.assertEqual(approval.evidence_channel, "delegated_github_relay")

    def test_owner_local_v2_binds_prior_feedback_and_keeps_verifier_identity_separate(self) -> None:
        prior = FeedbackEvent(
            channel="issue-comment", event_id="42", actor_id=OWNER_ID,
            actor_login="puchinya", actor_type="User",
            created_at="2026-10-17T08:30:00Z", updated_at="2026-10-17T08:30:00Z",
            kind="questions", head_sha40=None, body_sha256="1" * 64,
            source_url=f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-42",
        ).validate()
        baseline = feedback_digest((prior,))
        plan_sha = "f" * 64
        comment = github_comment(owner_local_decision_body(
            feedback_sha256=baseline, plan_sha256=plan_sha,
        ))
        approval = verify(
            decision_history(comment),
        )
        self.assertEqual(approval.evidence_type, USER_REVIEW_DECISION_SCHEMA_V2)
        self.assertEqual(approval.evidence_channel, "owner_local_tty_v1")
        self.assertEqual(approval.feedback_sha256, baseline)
        self.assertEqual(approval.plan_sha256, plan_sha)
        self.assertNotEqual(READ_ONLY_VERIFIER_ID, OWNER_ID)

        snapshot = feedback_snapshot(prior, carrier_feedback_event(comment))
        result = evaluate_user_review(
            SESSION, READINESS, PR_HEAD_SHA40, snapshot,
            review_mode="solo_owner", pr_author_user_id=OWNER_ID,
            repository_owner_user_id=OWNER_ID,
            authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
            allowed_human_user_ids=(OWNER_ID,), relay_approval=approval,
        )
        self.assertEqual(result.status, "APPROVED")
        self.assertEqual(result.selected_approval_evidence["evidence_type"], USER_REVIEW_DECISION_SCHEMA_V2)

        wrong = replace(approval, feedback_sha256="e" * 64)
        blocked = evaluate_user_review(
            SESSION, READINESS, PR_HEAD_SHA40, snapshot,
            review_mode="solo_owner", pr_author_user_id=OWNER_ID,
            repository_owner_user_id=OWNER_ID,
            authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
            allowed_human_user_ids=(OWNER_ID,), relay_approval=wrong,
        )
        self.assertNotEqual(blocked.status, "APPROVED")

    def test_owner_local_publisher_posts_v2_once_and_reads_it_back(self) -> None:
        class FakeGitHub:
            repo = REPOSITORY

            def __init__(self):
                self.comments: list[dict[str, object]] = []
                self.writes = 0

            def issue_comments(self, number):
                if number != ISSUE_NUMBER:
                    raise AssertionError("unexpected Issue")
                return list(self.comments)

            def issue_comment(self, number, comment_id):
                return next((row for row in self.comments if row["id"] == comment_id), None)

            def create_issue_comment(self, number, body):
                self.writes += 1
                row = {
                    "id": 101, "body": body,
                    "created_at": COMMENT_CREATED_AT, "updated_at": COMMENT_CREATED_AT,
                    "user": {"id": OWNER_ID, "type": "User", "login": "puchinya"},
                    "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/101",
                    "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
                    "html_url": f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-101",
                }
                self.comments.append(row)
                return row

        github = FakeGitHub()
        approval = publish_owner_local_user_review_decision(
            github, repository=REPOSITORY, issue_number=ISSUE_NUMBER, pr_number=PR_NUMBER,
            repository_owner_user_id=OWNER_ID, session=SESSION,
            readiness_sha256=READINESS.sha256, adc_sha256=ADC_SHA256,
            pr_head_sha40=PR_HEAD_SHA40, feedback_sha256="e" * 64,
            plan_sha256="f" * 64,
        )
        self.assertEqual(approval.evidence_type, USER_REVIEW_DECISION_SCHEMA_V2)
        self.assertEqual(approval.evidence_channel, "owner_local_tty_v1")
        self.assertEqual(github.writes, 1)
        self.assertEqual(len(github.comments), 1)
        with self.assertRaises(UserReviewRelayError):
            publish_owner_local_user_review_decision(
                github, repository=REPOSITORY, issue_number=ISSUE_NUMBER, pr_number=PR_NUMBER,
                repository_owner_user_id=OWNER_ID, session=SESSION,
                readiness_sha256=READINESS.sha256, adc_sha256=ADC_SHA256,
                pr_head_sha40=PR_HEAD_SHA40, feedback_sha256="e" * 64,
                plan_sha256="f" * 64,
            )
        self.assertEqual(github.writes, 1)

    def test_chain_requires_null_genesis_and_immediate_predecessors(self) -> None:
        previous = github_comment(
            decision_body(review_session_id="e" * 64), comment_id=100,
            created_at="2026-10-17T08:00:00Z",
        )
        current = github_comment(decision_body(predecessor_comment_id=100), comment_id=101)
        self.assertEqual(verify(decision_history(previous, current)).comment_id, 101)

        invalid_histories = (
            decision_history(github_comment(decision_body(predecessor_comment_id=100))),
            decision_history(
                previous,
                github_comment(decision_body(predecessor_comment_id=99), comment_id=101),
            ),
            decision_history(
                github_comment(decision_body(review_session_id="e" * 64), comment_id=100,
                               actor_id=OWNER_ID + 1, created_at="2026-10-17T08:00:00Z"),
                github_comment(decision_body(predecessor_comment_id=100), comment_id=101),
            ),
            decision_history(
                github_comment(decision_body(review_session_id="e" * 64, pr_number=99),
                               comment_id=100, created_at="2026-10-17T08:00:00Z"),
                github_comment(decision_body(predecessor_comment_id=100), comment_id=101),
            ),
            decision_history(
                github_comment(decision_body(review_session_id="e" * 64), comment_id=102,
                               created_at="2026-10-17T08:00:00Z"),
                github_comment(decision_body(predecessor_comment_id=102), comment_id=101),
            ),
        )
        for history in invalid_histories:
            with self.subTest(history=history), self.assertRaises(UserReviewRelayError):
                verify(history)

    def test_rejects_pre_session_equal_time_edits_wrong_actor_and_stale_subject(self) -> None:
        current_body = decision_body()
        invalid_comments = (
            github_comment(current_body, created_at="2026-10-17T08:59:59Z"),
            github_comment(current_body, created_at=SESSION_STARTED_AT),
            github_comment(current_body, updated_at="2026-10-17T09:02:00Z"),
            github_comment(current_body, actor_id=OWNER_ID + 1),
            github_comment(current_body, actor_id=READ_ONLY_VERIFIER_ID),
            github_comment(decision_body(review_session_id="e" * 64)),
            github_comment(decision_body(readiness_sha256="e" * 64)),
            github_comment(decision_body(adc_sha256="e" * 64)),
            github_comment(decision_body(pr_head_sha40="e" * 40)),
        )
        for comment in invalid_comments:
            with self.subTest(comment=comment), self.assertRaises(UserReviewRelayError):
                verify(decision_history(comment))

        next_session = UserReviewSession(REVIEW_SUBJECT, "2026-10-17T09:02:00Z").validate()
        with self.assertRaises(UserReviewRelayError):
            verify(decision_history(github_comment(current_body)), session=next_session)

    def test_rejects_incomplete_pagination_and_direct_list_direct_disagreement(self) -> None:
        comment = github_comment(decision_body())
        with self.assertRaises(UserReviewRelayError):
            verify(decision_history(comment, complete=False))

        with self.assertRaises(UserReviewRelayError):
            verify(decision_history())

        edited = github_comment(decision_body(decision="APPROVED"), updated_at="2026-10-17T09:02:00Z")
        cases = (
            decision_history(comment, direct_before={101: None}),
            decision_history(comment, direct_after={101: None}),
            decision_history(comment, direct_after={101: edited}),
            decision_history(comment, direct_after={101: github_comment(
                decision_body(), source_issue=62)}),
        )
        for history in cases:
            with self.subTest(history=history), self.assertRaises(UserReviewRelayError):
                verify(history)

        for wrong_source in (
            github_comment(decision_body(), source_issue=62),
            github_comment(decision_body(), source_repo="someone/else"),
            github_comment(decision_body(), comment_url_repo="someone/else"),
            github_comment(decision_body(), comment_url_id=102),
            github_comment(decision_body(), html_url_repo="someone/else"),
            github_comment(decision_body(), html_url_issue=62),
            github_comment(decision_body(), html_url_comment_id=102),
        ):
            with self.subTest(wrong_source=wrong_source), self.assertRaises(UserReviewRelayError):
                verify(decision_history(wrong_source))

    def test_rejects_duplicate_or_replayed_current_session_decisions(self) -> None:
        first = github_comment(decision_body(), comment_id=101)
        repeated = github_comment(decision_body(predecessor_comment_id=101), comment_id=102)
        with self.assertRaises(UserReviewRelayError):
            verify(decision_history(first, repeated))

    def test_exact_typed_carrier_flows_through_full_snapshot_evaluator(self) -> None:
        comment = github_comment(decision_body())
        approval = verify(decision_history(comment))
        snapshot = feedback_snapshot(carrier_feedback_event(comment))

        result = evaluate_user_review(
            SESSION,
            READINESS,
            PR_HEAD_SHA40,
            snapshot,
            review_mode="solo_owner",
            pr_author_user_id=OWNER_ID,
            repository_owner_user_id=OWNER_ID,
            authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
            allowed_human_user_ids=(OWNER_ID,),
            relay_approval=approval,
        )

        self.assertEqual(result.status, "APPROVED")
        self.assertNotEqual(READ_ONLY_VERIFIER_ID, OWNER_ID)
        self.assertEqual(result.selected_approval_event, "user-review-relay:101")
        self.assertEqual(result.selected_approval_evidence, approval.as_selected_evidence())

    def test_wrong_mode_subject_feedback_and_unresolved_threads_never_approve(self) -> None:
        comment = github_comment(decision_body())
        approval = verify(decision_history(comment))
        carrier = carrier_feedback_event(comment)

        for mode, author, allowed, snapshot in (
            ("external_reviewer", OWNER_ID, (OWNER_ID,), feedback_snapshot(carrier)),
            ("solo_owner", OWNER_ID + 1, (OWNER_ID,), feedback_snapshot(carrier)),
            ("solo_owner", OWNER_ID, (OWNER_ID + 1,), feedback_snapshot(carrier)),
            ("solo_owner", OWNER_ID, (OWNER_ID,), feedback_snapshot(
                carrier, replace(carrier, event_id="999"))),
            ("solo_owner", OWNER_ID, (OWNER_ID,), feedback_snapshot(
                carrier, replace(carrier, event_id="202", kind="questions",
                                 created_at="2026-10-17T09:02:00Z",
                                 updated_at="2026-10-17T09:02:00Z"))),
            ("solo_owner", OWNER_ID, (OWNER_ID,), feedback_snapshot(
                carrier, unresolved=("thread-1",))),
        ):
            with self.subTest(mode=mode, author=author, allowed=allowed):
                result = evaluate_user_review(
                    SESSION, READINESS, PR_HEAD_SHA40, snapshot,
                    review_mode=mode, pr_author_user_id=author,
                    repository_owner_user_id=OWNER_ID,
                    authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
                    allowed_human_user_ids=allowed, relay_approval=approval,
                )
                self.assertNotEqual(result.status, "APPROVED")

        with self.assertRaises(UserReviewError):
            evaluate_user_review(
                SESSION, READINESS, PR_HEAD_SHA40, feedback_snapshot(carrier),
                review_mode="independent", pr_author_user_id=OWNER_ID,
                repository_owner_user_id=OWNER_ID,
                authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
                allowed_human_user_ids=(OWNER_ID,), relay_approval=approval,
            )

        wrong_owner = evaluate_user_review(
            SESSION, READINESS, PR_HEAD_SHA40, feedback_snapshot(carrier),
            review_mode="solo_owner", pr_author_user_id=OWNER_ID,
            repository_owner_user_id=OWNER_ID + 1,
            authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
            allowed_human_user_ids=(OWNER_ID,), relay_approval=approval,
        )
        self.assertNotEqual(wrong_owner.status, "APPROVED")

        formal_self_approval = FeedbackEvent(
            channel="pr-review",
            event_id="self-approval-1",
            actor_id=OWNER_ID,
            actor_login="puchinya",
            actor_type="User",
            created_at="2026-10-17T09:01:00Z",
            updated_at="2026-10-17T09:01:00Z",
            kind="approved",
            head_sha40=PR_HEAD_SHA40,
            body_sha256="a" * 64,
            source_url=f"https://github.com/{REPOSITORY}/pull/{PR_NUMBER}#pullrequestreview-1",
        ).validate()
        executor_self_approval = evaluate_user_review(
            SESSION, READINESS, PR_HEAD_SHA40,
            feedback_snapshot(formal_self_approval),
            review_mode="solo_owner", pr_author_user_id=OWNER_ID,
            repository_owner_user_id=OWNER_ID,
            authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
            allowed_human_user_ids=(OWNER_ID,), relay_approval=None,
        )
        self.assertNotEqual(executor_self_approval.status, "APPROVED")

        incomplete = evaluate_user_review(
            SESSION, READINESS, PR_HEAD_SHA40, feedback_snapshot(carrier),
            review_mode="solo_owner", pr_author_user_id=OWNER_ID,
            repository_owner_user_id=OWNER_ID,
            authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
            allowed_human_user_ids=(OWNER_ID,), relay_approval=approval,
            all_feedback_surfaces_read=False,
        )
        self.assertNotEqual(incomplete.status, "APPROVED")

    def test_result_persists_selected_carrier_and_complete_snapshot_digest(self) -> None:
        comment = github_comment(decision_body())
        approval = verify(decision_history(comment))
        snapshot = feedback_snapshot(carrier_feedback_event(comment))
        result = evaluate_user_review(
            SESSION, READINESS, PR_HEAD_SHA40, snapshot,
            review_mode="solo_owner", pr_author_user_id=OWNER_ID,
            repository_owner_user_id=OWNER_ID,
            authenticated_verifier_user_id=READ_ONLY_VERIFIER_ID,
            allowed_human_user_ids=(OWNER_ID,), relay_approval=approval,
        )

        stored = {
            "schema": "PASES_USER_REVIEW_RESULT_V2",
            "subject": REVIEW_SUBJECT.as_dict(),
            "result": result.as_dict(),
            "result_sha256": result.sha256,
            "snapshot_sha256": snapshot.sha256,
        }
        restored = json.loads(json.dumps(stored, sort_keys=True))
        self.assertEqual(restored["schema"], "PASES_USER_REVIEW_RESULT_V2")
        self.assertEqual(restored["result"]["selected_approval_evidence"], approval.as_selected_evidence())
        self.assertEqual(restored["snapshot_sha256"], snapshot.sha256)
        self.assertEqual(UserReviewResult.from_dict(restored["result"]), result)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "relay-backed.result.json"
            path.write_text(json.dumps(stored, sort_keys=True, separators=(",", ":")) + "\n")
            saved_subject, saved_result, saved_snapshot_sha256 = _read_review_record(path)
        self.assertEqual(saved_subject, REVIEW_SUBJECT)
        self.assertEqual(saved_result, result)
        self.assertEqual(saved_snapshot_sha256, snapshot.sha256)


if __name__ == "__main__":
    unittest.main()
