from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import cli
from p_ases.github import GitHubError


class FakeGitHub:
    repo = "owner/repo"
    number = 128
    expected_body = "immutable exact-subject evidence"

    def __init__(self, old_comments=0):
        self.records = {}
        for comment_id in range(1, old_comments + 1):
            self.records[comment_id] = self._record(comment_id, f"unrelated-{comment_id}")
        self.page_reads = 0
        self.issue_reads = 0
        self.posts = 0
        self.ambiguous_post = False
        self.fail_post = False
        self.change_on_issue_read = None

    def _record(self, comment_id, body):
        return {
            "id": comment_id, "body": body,
            "issue_url": f"https://api.github.com/repos/{self.repo}/issues/{self.number}",
        }

    def issue(self, number):
        assert number == self.number
        self.issue_reads += 1
        if self.change_on_issue_read == self.issue_reads:
            next_id = max(self.records, default=0) + 1
            self.records[next_id] = self._record(next_id, "concurrent unrelated comment")
        return {"number": number, "comments": len(self.records)}

    def issue_comments(self, number):
        raise AssertionError("must not materialize all Issue comments")

    def issue_comment_pages_newest(self, number, total_comments):
        assert number == self.number
        rows = sorted(self.records.values(), key=lambda item: item["id"])
        if not rows:
            self.page_reads += 1
            yield []
        for end in range(len(rows), 0, -100):
            self.page_reads += 1
            yield copy.deepcopy(rows[max(0, end - 100):end])

    def issue_comment(self, number, comment_id):
        assert number == self.number
        return copy.deepcopy(self.records[comment_id])

    def create_issue_comment(self, number, body):
        assert number == self.number
        self.posts += 1
        if self.fail_post:
            raise GitHubError("ambiguous POST without durable write")
        next_id = max(self.records, default=0) + 1
        record = self._record(next_id, body)
        self.records[next_id] = record
        if self.ambiguous_post:
            raise GitHubError("ambiguous POST with durable write")
        return record


class ImmutableEvidenceScanTests(unittest.TestCase):
    def test_publish_streams_multiple_pages_and_reuses_exact_body(self):
        github = FakeGitHub(235)
        comment_id = cli._publish_once(github, 128, github.expected_body)
        self.assertEqual(comment_id, 236)
        self.assertEqual((github.posts, github.page_reads), (1, 3))
        reused = cli._publish_once(github, 128, github.expected_body)
        self.assertEqual(reused, comment_id)
        self.assertEqual(github.posts, 1)
        self.assertEqual(cli._exact_published(github, 128, github.expected_body), comment_id)

    def test_zero_comment_issue_publishes_once(self):
        github = FakeGitHub()
        self.assertIsNone(cli._exact_published(github, 128, github.expected_body))
        self.assertEqual(cli._publish_once(github, 128, github.expected_body), 1)
        self.assertEqual(github.posts, 1)

    def test_duplicate_matching_body_on_different_pages_fails_without_post(self):
        github = FakeGitHub(235)
        github.records[22]["body"] = github.expected_body
        github.records[227]["body"] = github.expected_body
        with self.assertRaisesRegex(cli.CLIError, "duplicated"):
            cli._publish_once(github, 128, github.expected_body)
        self.assertEqual(github.posts, 0)
        with self.assertRaisesRegex(cli.CLIError, "duplicated"):
            cli._exact_published(github, 128, github.expected_body)

    def test_ambiguous_post_recovers_by_exact_recheck_without_retry(self):
        github = FakeGitHub(110)
        github.ambiguous_post = True
        comment_id = cli._publish_once(github, 128, github.expected_body)
        self.assertEqual(comment_id, 111)
        self.assertEqual(github.posts, 1)
        self.assertEqual(cli._exact_published(github, 128, github.expected_body), 111)

    def test_ambiguous_post_without_published_body_is_not_retried(self):
        github = FakeGitHub(110)
        github.fail_post = True
        with self.assertRaisesRegex(GitHubError, "ambiguous POST"):
            cli._publish_once(github, 128, github.expected_body)
        self.assertEqual(github.posts, 1)

    def test_comment_count_drift_during_or_after_scan_blocks_post(self):
        for issue_read in (2, 3):
            with self.subTest(issue_read=issue_read):
                github = FakeGitHub(125)
                github.change_on_issue_read = issue_read
                with self.assertRaisesRegex(cli.CLIError, "comment count|comments changed"):
                    cli._publish_once(github, 128, github.expected_body)
                self.assertEqual(github.posts, 0)

    def test_malformed_comment_and_incomplete_pagination_fail_closed(self):
        github = FakeGitHub(101)
        github.records[97]["id"] = "bad"
        with self.assertRaisesRegex(cli.CLIError, "malformed"):
            cli._publish_once(github, 128, github.expected_body)
        self.assertEqual(github.posts, 0)
        github = FakeGitHub(101)
        github.records.pop(95)
        original_issue = github.issue

        def stale_count(number):
            result = original_issue(number)
            result["comments"] = 101
            return result

        github.issue = stale_count
        with self.assertRaisesRegex(cli.CLIError, "page count differs"):
            cli._publish_once(github, 128, github.expected_body)
        self.assertEqual(github.posts, 0)


if __name__ == "__main__":
    unittest.main()
