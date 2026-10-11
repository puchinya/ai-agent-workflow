from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHub, GitHubError


HEAD = "a" * 40


def workflow_run(identifier: int, run_number: int) -> dict[str, object]:
    return {
        "id": identifier,
        "run_number": run_number,
        "run_attempt": 1,
        "path": ".github/workflows/ci.yml",
        "head_sha": HEAD,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "pases/adc-core",
        "head_repository": {"full_name": "octo/repo"},
        "pull_requests": [{"number": 33}],
    }


class FakeGitHub(GitHub):
    def __init__(self, responses):
        super().__init__("octo/repo")
        self.responses = list(responses)
        self.calls = []

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class GitHubWorkflowRunTests(unittest.TestCase):
    def test_reads_exact_workflow_path_sha_and_pull_request_event(self):
        github = FakeGitHub(({"total_count": 1, "workflow_runs": [workflow_run(10, 2)]},))
        rows = github.workflow_runs_for_ref(HEAD)
        self.assertEqual(rows[0]["id"], 10)
        method, endpoint, payload = github.calls[0]
        self.assertEqual((method, payload), ("GET", None))
        self.assertIn("actions/workflows/ci.yml/runs?", endpoint)
        self.assertIn(f"head_sha={HEAD}", endpoint)
        self.assertIn("event=pull_request", endpoint)

    def test_paginates_and_fails_on_count_drift_or_incomplete_identity(self):
        first = [workflow_run(i, i) for i in range(1, 101)]
        second = workflow_run(101, 101)
        github = FakeGitHub(({"total_count": 101, "workflow_runs": first},
                             {"total_count": 101, "workflow_runs": [second]}))
        self.assertEqual(len(github.workflow_runs_for_ref(HEAD)), 101)
        drift = FakeGitHub(({"total_count": 101, "workflow_runs": first},
                            {"total_count": 102, "workflow_runs": [second]}))
        with self.assertRaises(GitHubError):
            drift.workflow_runs_for_ref(HEAD)
        malformed = workflow_run(1, 1)
        malformed.pop("head_repository")
        bad = FakeGitHub(({"total_count": 1, "workflow_runs": [malformed]},))
        with self.assertRaises(GitHubError):
            bad.workflow_runs_for_ref(HEAD)

    def test_rejects_invalid_sha_path_and_api_failure(self):
        with self.assertRaises(GitHubError):
            FakeGitHub(()).workflow_runs_for_ref("a" * 39)
        with self.assertRaises(GitHubError):
            FakeGitHub(()).workflow_runs_for_ref(HEAD, workflow_path="../ci.yml")
        with self.assertRaisesRegex(GitHubError, "503"):
            FakeGitHub((GitHubError("HTTP 503"),)).workflow_runs_for_ref(HEAD)


if __name__ == "__main__":
    unittest.main()
