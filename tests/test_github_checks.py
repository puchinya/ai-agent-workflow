from __future__ import annotations

import sys
import unittest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHub, GitHubError


HEAD = "a" * 40


class FakeGitHub(GitHub):
    def __init__(self, responses):
        super().__init__("octo/repo")
        self.responses = list(responses)
        self.calls = []

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        return self.responses.pop(0)


class GitHubCheckRunTests(unittest.TestCase):
    def test_check_runs_paginates_all_pages_and_selects_check_runs_array(self):
        first = [{"id": i, "name": f"job-{i}", "head_sha": HEAD} for i in range(1, 101)]
        second = [{"id": 101, "name": "job-last", "head_sha": HEAD}]
        github = FakeGitHub(({"total_count": 101, "check_runs": first},
                             {"total_count": 101, "check_runs": second}))
        runs = github.check_runs_for_ref(HEAD)
        self.assertEqual(len(runs), 101)
        self.assertEqual(runs[-1]["id"], 101)
        self.assertIn("filter=all&page=1&per_page=100", github.calls[0][1])
        self.assertIn("filter=all&page=2&per_page=100", github.calls[1][1])

    def test_check_runs_rejects_invalid_sha_shape_and_truncated_pagination(self):
        github = FakeGitHub(())
        with self.assertRaises(GitHubError):
            github.check_runs_for_ref("not-a-sha")
        truncated = FakeGitHub(({"total_count": 101, "check_runs": [{"id": 1}]},))
        with self.assertRaises(GitHubError):
            truncated.check_runs_for_ref(HEAD)

    def test_check_runs_rejects_legacy_array_response(self):
        github = FakeGitHub(([],))
        with self.assertRaises(GitHubError):
            github.check_runs_for_ref(HEAD)


if __name__ == "__main__":
    unittest.main()
