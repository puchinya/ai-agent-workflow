from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHub, GitHubError
from p_ases.delivery import ReadinessResult
from p_ases.evidence_store import VerificationSubject
from p_ases.phases import IssueKind
from p_ases.user_review import UserReviewSubject, evaluate_user_review
from p_ases.cli import CLIError, _review_payload_from_github, _review_phase_transition


class FakeGitHub(GitHub):
    def __init__(self, responses):
        super().__init__("octo/repo")
        self.responses = list(responses)
        self.calls = []

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        if not self.responses:
            raise AssertionError("unexpected GitHub API request")
        return self.responses.pop(0)


def records(n, offset=0):
    return [{"id": i + offset} for i in range(n)]


class UserReviewGitHubAdapterTests(unittest.TestCase):
    def test_cli_review_sync_maps_explicit_pr_and_diff_comments_to_same_execution_loop(self):
        head = "a" * 40
        verification_subject = VerificationSubject(
            "octo/repo", 31, 37, 123, "b" * 64, "c" * 64, head).validate()
        readiness = ReadinessResult("PASS", verification_subject, (), ("d" * 64,), "e" * 64).validate()
        subject = UserReviewSubject(verification_subject, readiness.sha256).validate()
        body = f"P-ASES-DECISION: CHANGES_REQUESTED\nP-ASES-HEAD: {head}"
        comment = {"id": 700, "created_at": "2026-10-12T00:00:00Z",
                   "updated_at": "2026-10-12T00:00:00Z", "body": body,
                   "user": {"id": 42, "login": "puchinya", "type": "User"},
                   "html_url": "https://github.com/octo/repo/pull/37#issuecomment-700",
                   "commit_id": None}

        class FeedbackGitHub:
            def __init__(self, *, conversation=(), inline=()):
                self.conversation = list(conversation)
                self.inline = list(inline)

            def issue_comments(self, _issue):
                return []

            def pull_conversation_comments(self, _pr):
                return self.conversation

            def pull_reviews(self, _pr):
                return []

            def pull_diff_comments(self, _pr):
                return self.inline

            def pull_review_threads(self, _pr):
                return []

        for channel, fake in (
            ("pr-comment", FeedbackGitHub(conversation=(comment,))),
            ("diff-comment", FeedbackGitHub(inline=({**comment, "commit_id": head},))),
        ):
            with self.subTest(channel=channel):
                snapshot = _review_payload_from_github(
                    fake, subject, observed_at="2026-10-12T00:01:00Z")
                result = evaluate_user_review(
                    subject, readiness, head, snapshot.events, allowed_human_user_ids=(42,))
                self.assertEqual(result.status, "CHANGES_REQUESTED")
                self.assertEqual(result.next_phase, "execution")
                self.assertEqual(result.subject.verification_subject, verification_subject)

        class LabelGitHub:
            def __init__(self, *, lose_response=False, apply_before_error=True):
                self.labels = ["kind:child", "phase:user-review"]
                self.lose_response = lose_response
                self.apply_before_error = apply_before_error
                self.writes = 0

            def issue(self, _issue):
                return {"number": 31, "state": "open", "pull_request": None,
                        "labels": [{"name": row} for row in self.labels]}

            def replace_issue_labels(self, _issue, labels):
                self.writes += 1
                self.labels = list(labels)
                if self.lose_response:
                    if not self.apply_before_error:
                        self.labels = ["kind:child", "phase:user-review"]
                    raise GitHubError("simulated lost response")

        github = LabelGitHub()
        _review_phase_transition(github, 31, IssueKind.CHILD, result, "sync")
        self.assertIn("phase:execution", github.labels)

        applied_but_response_lost = LabelGitHub(lose_response=True)
        _review_phase_transition(applied_but_response_lost, 31, IssueKind.CHILD, result, "sync")
        self.assertIn("phase:execution", applied_but_response_lost.labels)
        self.assertEqual(applied_but_response_lost.writes, 1)

        not_applied = LabelGitHub(lose_response=True, apply_before_error=False)
        with self.assertRaisesRegex(CLIError, "ambiguous.*no retry"):
            _review_phase_transition(not_applied, 31, IssueKind.CHILD, result, "sync")
        self.assertIn("phase:user-review", not_applied.labels)
        self.assertEqual(not_applied.writes, 1)

    def test_formal_reviews_and_inline_comments_paginate_all_pages(self):
        gh = FakeGitHub((records(100), records(1, 100), records(1)))
        self.assertEqual(len(gh.pull_reviews(37)), 101)
        self.assertEqual(len(gh.pull_diff_comments(37)), 1)
        self.assertEqual(gh.calls, [
            ("GET", "repos/octo/repo/pulls/37/reviews?page=1&per_page=100", None),
            ("GET", "repos/octo/repo/pulls/37/reviews?page=2&per_page=100", None),
            ("GET", "repos/octo/repo/pulls/37/comments?page=1&per_page=100", None),
        ])

    def test_pr_conversation_uses_issues_comment_api_and_integration_reads_all_prs(self):
        gh = FakeGitHub((records(1), records(100), records(0)))
        self.assertEqual(len(gh.pull_conversation_comments(37)), 1)
        self.assertEqual(len(gh.pull_requests_all()), 100)
        self.assertEqual(gh.calls[0][1], "repos/octo/repo/issues/37/comments?page=1&per_page=100")
        self.assertEqual(gh.calls[1][1], "repos/octo/repo/pulls?state=all&page=1&per_page=100")
        self.assertEqual(gh.calls[2][1], "repos/octo/repo/pulls?state=all&page=2&per_page=100")

    def test_malformed_page_or_api_failure_does_not_silently_skip_feedback(self):
        gh = FakeGitHub(([{"id": 1}, None],))
        with self.assertRaises(GitHubError):
            gh.pull_reviews(37)
        gh = FakeGitHub((records(100), "broken"))
        with self.assertRaises(GitHubError):
            gh.pull_diff_comments(37)

    def test_invalid_review_pr_number_fails_before_api(self):
        gh = FakeGitHub(())
        for call in (gh.pull_reviews, gh.pull_diff_comments, gh.pull_conversation_comments):
            with self.assertRaises(GitHubError):
                call(0)
        self.assertEqual(gh.calls, [])

    def test_review_thread_pages_keep_resolution_and_outdated_metadata(self):
        class GraphQLFake(GitHub):
            def __init__(self):
                super().__init__("octo/repo")
                self.responses = [{"repository": {"pullRequest": {"reviewThreads": {
                    "nodes": [{"id": "thread-1", "isResolved": False, "isOutdated": False,
                               "comments": {"nodes": [{"databaseId": 9}],
                                            "pageInfo": {"hasNextPage": False, "endCursor": None}}}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }}}}]

            def _graphql(self, _query, _variables):
                return self.responses.pop(0)

        threads = GraphQLFake().pull_review_threads(37)
        self.assertEqual(threads[0]["id"], "thread-1")
        self.assertFalse(threads[0]["isResolved"])
        self.assertFalse(threads[0]["isOutdated"])
        self.assertEqual(threads[0]["comments"], [{"databaseId": 9}])

    def test_review_threads_and_nested_comments_follow_all_cursors(self):
        class GraphQLFake(GitHub):
            def __init__(self):
                super().__init__("octo/repo")
                self.calls = []
                self.responses = [
                    {"repository": {"pullRequest": {"reviewThreads": {
                        "nodes": [{"id": "thread-1", "isResolved": False, "isOutdated": False,
                                   "comments": {"nodes": [{"databaseId": 1}],
                                                "pageInfo": {"hasNextPage": True, "endCursor": "comment-cursor"}}}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "thread-cursor"},
                    }}}},
                    {"node": {"comments": {"nodes": [{"databaseId": 2}],
                                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}},
                    {"repository": {"pullRequest": {"reviewThreads": {
                        "nodes": [{"id": "thread-2", "isResolved": True, "isOutdated": True,
                                   "comments": {"nodes": [],
                                                "pageInfo": {"hasNextPage": False, "endCursor": None}}}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }}}},
                ]

            def _graphql(self, query, variables):
                self.calls.append((query, variables))
                return self.responses.pop(0)

        fake = GraphQLFake()
        threads = fake.pull_review_threads(37)
        self.assertEqual([row["id"] for row in threads], ["thread-1", "thread-2"])
        self.assertEqual([row["databaseId"] for row in threads[0]["comments"]], [1, 2])
        for query, _variables in fake.calls:
            self.assertIn("author{login __typename ... on User {databaseId} ... on Bot {databaseId}}", query)
            self.assertNotIn("author{databaseId", query)
        self.assertEqual(fake.calls[1][1]["threadId"], "thread-1")
        self.assertEqual(fake.calls[2][1]["cursor"], "thread-cursor")

    def test_authenticated_identity_must_be_a_human_user(self):
        gh = FakeGitHub(({"id": 42, "login": "puchinya", "type": "User"},))
        self.assertEqual(gh.authenticated_user()["id"], 42)
        gh = FakeGitHub(({"id": 42, "login": "runner", "type": "Bot"},))
        with self.assertRaises(GitHubError):
            gh.authenticated_user()


if __name__ == "__main__":
    unittest.main()
