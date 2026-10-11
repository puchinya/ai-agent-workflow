from __future__ import annotations

import sys
import unittest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHub, GitHubError


HEAD = "a" * 40


def check_run(identifier, name):
    repository = {"url": "https://api.github.com/repos/octo/repo"}
    return {
        "id": identifier,
        "name": name,
        "head_sha": HEAD,
        "app": {"id": 789},
        "status": "completed",
        "conclusion": "success",
        "pull_requests": [{
            "number": 54,
            "base": {"repo": repository, "sha": "c" * 40},
            "head": {"repo": repository, "sha": HEAD},
        }],
    }


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
        first = [check_run(i, f"job-{i}") for i in range(1, 101)]
        second = [check_run(101, "job-last")]
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

    def test_check_runs_rejects_missing_app_or_wrong_head_identity(self):
        incomplete = check_run(1, "job")
        incomplete.pop("app")
        github = FakeGitHub(({"total_count": 1, "check_runs": [incomplete]},))
        with self.assertRaises(GitHubError):
            github.check_runs_for_ref(HEAD)

    def test_check_runs_rejects_duplicate_ids_and_page_count_drift(self):
        duplicate = check_run(1, "job")
        github = FakeGitHub(({"total_count": 2, "check_runs": [duplicate]},
                             {"total_count": 2, "check_runs": [duplicate]}))
        with self.assertRaises(GitHubError):
            github.check_runs_for_ref(HEAD)
        full = [check_run(i, f"job-{i}") for i in range(1, 101)]
        changed = FakeGitHub(({"total_count": 101, "check_runs": full},
                              {"total_count": 102, "check_runs": [check_run(101, "job-last")] }))
        with self.assertRaises(GitHubError):
            changed.check_runs_for_ref(HEAD)

    def test_check_runs_api_errors_fail_closed(self):
        class FailedGitHub(FakeGitHub):
            def request(self, method, endpoint, payload=None):
                raise GitHubError("HTTP 503")

        with self.assertRaisesRegex(GitHubError, "503"):
            FailedGitHub(()).check_runs_for_ref(HEAD)
        wrong_head = check_run(1, "job")
        wrong_head["head_sha"] = "b" * 40
        github = FakeGitHub(({"total_count": 1, "check_runs": [wrong_head]},))
        with self.assertRaises(GitHubError):
            github.check_runs_for_ref(HEAD)


if __name__ == "__main__":
    unittest.main()
