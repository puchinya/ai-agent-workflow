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


if __name__ == "__main__":
    unittest.main()
