from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

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
    def test_api_metrics_count_requests_and_measure_client_latency(self):
        github = GitHub("octo/repo")
        completed = __import__("subprocess").CompletedProcess(
            ["gh", "api"], 0, "{}", "")
        with patch("p_ases.github.subprocess.run", return_value=completed):
            github.request("GET", "repos/octo/repo/issues/26")
            metrics = github.api_metrics
        self.assertEqual(metrics["api_calls"], 1)
        self.assertGreaterEqual(metrics["elapsed_ms"], 0)

    def test_pull_request_readback_uses_exact_numbered_api_resource(self):
        row = {"number": 54, "state": "open", "draft": False}
        github = FakeGitHub((row,))
        self.assertEqual(github.pull_request(54), row)
        self.assertEqual(github.calls, [("GET", "repos/octo/repo/pulls/54", None)])

    def test_pull_request_readback_rejects_bad_number_and_non_object(self):
        with self.assertRaises(GitHubError):
            FakeGitHub(()).pull_request(0)
        with self.assertRaises(GitHubError):
            FakeGitHub(([],)).pull_request(54)
        with self.assertRaises(GitHubError):
            FakeGitHub(({"number": 53},)).pull_request(54)

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

    def test_historical_check_run_reads_exact_id_and_rejects_mismatched_response(self):
        row = check_run(701, "trusted-ci")
        github = FakeGitHub((row,))
        self.assertEqual(github.check_run(701), row)
        self.assertEqual(github.calls, [("GET", "repos/octo/repo/check-runs/701", None)])
        with self.assertRaises(GitHubError):
            FakeGitHub((row,)).check_run(0)
        with self.assertRaises(GitHubError):
            FakeGitHub((check_run(702, "trusted-ci"),)).check_run(701)

    def test_actions_job_supplies_creation_time_only_for_its_exact_check_run(self):
        check = check_run(701, "trusted-ci")
        check.update({"status": "completed", "conclusion": "success",
                      "started_at": "2026-10-14T11:59:01Z",
                      "completed_at": "2026-10-14T11:59:02Z"})
        job = {"id": 701, "run_id": 30, "run_attempt": 1, "name": "trusted-ci",
               "head_sha": HEAD, "status": "completed", "conclusion": "success",
               "check_run_url": "https://api.github.com/repos/octo/repo/check-runs/701",
               "created_at": "2026-10-14T11:59:00Z",
               "started_at": check["started_at"], "completed_at": check["completed_at"]}
        github = FakeGitHub((job,))

        resolved = github.workflow_job_for_check_run(check)

        self.assertEqual(resolved["created_at"], job["created_at"])
        self.assertEqual(github.calls, [("GET", "repos/octo/repo/actions/jobs/701", None)])

        for field, value in (("name", "other-job"), ("head_sha", "b" * 40),
                             ("status", "in_progress"), ("conclusion", "failure"),
                             ("started_at", "2026-10-14T11:58:00Z"),
                             ("completed_at", "2026-10-14T11:58:00Z")):
            with self.subTest(field=field):
                mismatched = {**job, field: value}
                with self.assertRaisesRegex(GitHubError, "does not match"):
                    FakeGitHub((mismatched,)).workflow_job_for_check_run(check)

        wrong_link = {**job, "check_run_url": "https://api.github.com/repos/octo/repo/check-runs/702"}
        with self.assertRaisesRegex(GitHubError, "incomplete or mismatched"):
            FakeGitHub((wrong_link,)).workflow_job_for_check_run(check)

    def test_workflow_runs_support_main_push_and_dispatch_with_exact_event_path(self):
        run = {"id": 30, "run_number": 8, "run_attempt": 1,
               "path": ".github/workflows/ci.yml", "event": "push",
               "head_sha": HEAD, "head_branch": "main", "status": "completed",
               "conclusion": "success", "head_repository": {"full_name": "octo/repo"}}
        github = FakeGitHub(({"total_count": 1, "workflow_runs": [run]},))
        self.assertEqual(github.workflow_runs_for_ref(HEAD, event="push"), [run])
        self.assertIn("event=push", github.calls[0][1])
        with self.assertRaises(GitHubError):
            FakeGitHub(()).workflow_runs_for_ref(HEAD, event="delete")
        with self.assertRaises(GitHubError):
            FakeGitHub(({"total_count": 1, "workflow_runs": [{**run, "event": "workflow_dispatch"}]},)).workflow_runs_for_ref(
                HEAD, event="push")

    def test_workflow_run_jobs_paginates_and_validates_step_provenance(self):
        def job(identifier, run_id=30):
            return {"id": identifier, "run_id": run_id, "head_sha": HEAD,
                    "name": f"job-{identifier}", "status": "completed", "conclusion": "success",
                    "check_run_url": f"https://api.github.com/repos/octo/repo/check-runs/{identifier}",
                    "steps": [{"number": 1, "name": "Unit tests", "status": "completed", "conclusion": "success"}]}
        first = [job(i) for i in range(1, 101)]
        github = FakeGitHub(({"total_count": 101, "jobs": first},
                             {"total_count": 101, "jobs": [job(101)]}))
        rows = github.workflow_run_jobs(30)
        self.assertEqual(len(rows), 101)
        self.assertIn("/actions/runs/30/jobs?page=1&per_page=100", github.calls[0][1])
        self.assertIn("/actions/runs/30/jobs?page=2&per_page=100", github.calls[1][1])

        wrong_run = FakeGitHub(({"total_count": 1, "jobs": [job(1, 31)]},))
        with self.assertRaisesRegex(GitHubError, "incomplete identity"):
            wrong_run.workflow_run_jobs(30)
        truncated = FakeGitHub(({"total_count": 2, "jobs": [job(1)]},))
        with self.assertRaisesRegex(GitHubError, "pagination count"):
            truncated.workflow_run_jobs(30)

    def test_historical_workflow_attempt_and_jobs_use_attempt_specific_endpoints(self):
        run = {"id": 30, "run_number": 8, "run_attempt": 1,
               "path": ".github/workflows/ci.yml", "event": "push",
               "head_sha": HEAD, "head_branch": "main", "status": "completed",
               "conclusion": "success", "head_repository": {"full_name": "octo/repo"}}
        job = {"id": 500, "run_id": 30, "head_sha": HEAD, "name": "test (ubuntu-latest, 3.10)",
               "status": "completed", "conclusion": "success",
               "check_run_url": "https://api.github.com/repos/octo/repo/check-runs/700",
               "steps": [{"number": 1, "name": "Unit tests", "status": "completed",
                          "conclusion": "success"}]}
        github = FakeGitHub((run, {"total_count": 1, "jobs": [job]}))
        self.assertEqual(github.workflow_run_attempt(30, 1), run)
        self.assertEqual(github.workflow_run_jobs(30, 1), [job])
        self.assertEqual(github.calls, [
            ("GET", "repos/octo/repo/actions/runs/30/attempts/1", None),
            ("GET", "repos/octo/repo/actions/runs/30/attempts/1/jobs?page=1&per_page=100", None),
        ])

    def test_historical_workflow_attempt_rejects_missing_or_mismatched_records(self):
        run = {"id": 30, "run_number": 8, "run_attempt": 2,
               "path": ".github/workflows/ci.yml", "event": "push",
               "head_sha": HEAD, "head_branch": "main", "status": "completed",
               "conclusion": "success", "head_repository": {"full_name": "octo/repo"}}
        with self.assertRaisesRegex(GitHubError, "attempt response"):
            FakeGitHub((run,)).workflow_run_attempt(30, 1)
        with self.assertRaises(GitHubError):
            FakeGitHub((GitHubError("HTTP 404"),)).workflow_run_attempt(30, 1)
        with self.assertRaises(GitHubError):
            FakeGitHub(()).workflow_run_jobs(30, 0)


if __name__ == "__main__":
    unittest.main()
