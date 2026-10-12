from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHub, GitHubError


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
