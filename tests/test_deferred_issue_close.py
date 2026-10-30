from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.cli import _delivery_finalize


REPOSITORY = "puchinya/ai-agent-workflow"
MERGE_SHA = "e" * 40
MAIN_SHA = "f" * 40


class FakeGitHub:
    repo = REPOSITORY

    def __init__(self):
        self.close_calls = 0
        self.issue_row = {
            "number": 63, "state": "open", "closed_at": None,
            "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
        }
        self.pr = {
            "number": 64, "state": "closed", "merged": True,
            "merged_at": "2026-10-16T10:00:00Z", "merge_commit_sha": MERGE_SHA,
            "title": "Issue #63 implementation", "body": "Implementation delivered.\n\nRefs #63",
            "head": {"sha": "d" * 40},
        }

    def pull_request(self, number):
        if number != 64:
            raise AssertionError("wrong PR")
        return self.pr

    def issue(self, number):
        if number != 63:
            raise AssertionError("wrong Issue")
        return dict(self.issue_row)

    def issues_all(self):
        return [dict(self.issue_row)]

    def repository_metadata(self):
        return {"default_branch": "main"}

    def branch(self, branch):
        if branch != "main":
            raise AssertionError("wrong branch")
        return {"commit": {"sha": MAIN_SHA}}

    def compare_commits(self, base, head):
        self.assert_sha(base, MERGE_SHA)
        self.assert_sha(head, MAIN_SHA)
        return {"status": "identical"}

    @staticmethod
    def assert_sha(actual, expected):
        if actual != expected:
            raise AssertionError("wrong commit SHA")

    def pull_request_commits(self, number):
        if number != 64:
            raise AssertionError("wrong PR")
        return [{"sha": "a" * 40, "commit": {"message": "Implement Issue #63 changes"}}]

    def pull_request_closing_issues(self, number):
        if number != 64:
            raise AssertionError("wrong PR")
        return []

    def issue_pull_request_cross_references(self, number):
        if number != 63:
            raise AssertionError("wrong Issue")
        return [{"pr_number": 64, "repository": REPOSITORY, "will_close_target": False}]

    def commit_details(self, sha):
        self.assert_sha(sha, MERGE_SHA)
        return {"message": "Merge PR #64 at dddddddddddd\n\nImplementation delivered."}

    def close_issue(self, number):
        if number != 63:
            raise AssertionError("wrong Issue")
        self.close_calls += 1
        self.issue_row.update({"state": "closed", "closed_at": "2026-10-17T12:00:00Z"})
        return dict(self.issue_row)


def activation_proof():
    return {
        "status": "ACTIVE", "activation_record_id": 500,
        "activation_record_sha256": "a" * 64,
        "activated_at": "2026-10-17T11:00:00Z",
        "activation_adc_sha256": "b" * 64,
        "activation_profile_sha256": "c" * 64,
        "ruleset_id": 7, "ruleset_applied_record_id": 499,
        "effective_policy_sha256": "d" * 64,
        "default_branch": "main", "default_branch_sha40": MAIN_SHA,
        "required_check_policy_sha256": "e" * 64,
    }


def run_finalize(root: Path, github: FakeGitHub) -> dict:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        status = _delivery_finalize(SimpleNamespace(issue=63, pr=64), REPOSITORY, root, github)
    value = json.loads(output.getvalue())
    value["exit_code"] = status
    return value


class NormalAutoCloseGitHub:
    repo = REPOSITORY

    def __init__(self):
        self.close_calls = 0

    def pull_request(self, number):
        if number != 42:
            raise AssertionError("wrong PR")
        return {
            "number": 42, "state": "closed", "merged": True,
            "merged_at": "2026-10-17T10:00:00Z", "merge_commit_sha": MERGE_SHA,
            "body": "Routine change.\n\nCloses #41",
        }

    def issue(self, number):
        if number != 41:
            raise AssertionError("wrong Issue")
        return {"number": 41, "state": "closed", "closed_at": "2026-10-17T10:01:00Z"}

    def repository_metadata(self):
        return {"default_branch": "main"}

    def branch(self, branch):
        if branch != "main":
            raise AssertionError("wrong branch")
        return {"commit": {"sha": MAIN_SHA}}

    def compare_commits(self, base, head):
        if (base, head) != (MERGE_SHA, MAIN_SHA):
            raise AssertionError("wrong merge/main comparison")
        return {"status": "identical"}


class DeferredIssueCloseTests(unittest.TestCase):
    def test_normal_closes_association_still_finalizes_from_github_auto_close(self):
        output = io.StringIO()
        github = NormalAutoCloseGitHub()
        with contextlib.redirect_stdout(output):
            status = _delivery_finalize(SimpleNamespace(issue=41, pr=42), REPOSITORY,
                                        Path("."), github)
        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "FINALIZED")
        self.assertEqual(result["issue_state"], "closed")
        self.assertEqual(github.close_calls, 0)

    def test_merge_waits_for_activation_and_does_not_close_issue_early(self):
        with tempfile.TemporaryDirectory() as temporary:
            github = FakeGitHub()
            with patch("p_ases.cli.read_consumer_activation_history", return_value=[]):
                result = run_finalize(Path(temporary), github)
            self.assertEqual(result["status"], "MERGED_AWAITING_ISSUE_COMPLETION")
            self.assertEqual(result["issue_state"], "open")
            self.assertEqual(github.close_calls, 0)

    def test_issue_closes_once_only_after_active_v2_and_recovers_by_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            active_history = [(SimpleNamespace(schema_version=2), 500)]
            with patch("p_ases.cli.read_consumer_activation_history", return_value=active_history), \
                    patch("p_ases.cli._activation_v2_issue63_proof", return_value=activation_proof()):
                first = run_finalize(root, github)
                second = run_finalize(root, github)
            self.assertEqual(first["status"], "FINALIZED")
            self.assertEqual(second["status"], "FINALIZED")
            self.assertEqual(first["issue_state"], "closed")
            self.assertEqual(github.close_calls, 1)

    def test_closed_issue_without_activation_or_durable_intent_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            github.issue_row.update({"state": "closed", "closed_at": "2026-10-17T12:00:00Z"})
            with patch("p_ases.cli.read_consumer_activation_history", return_value=[]):
                result = run_finalize(root, github)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(github.close_calls, 0)


if __name__ == "__main__":
    unittest.main()
