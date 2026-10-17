from __future__ import annotations

import sys
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHub, GitHubError


class FakeGitHub(GitHub):
    def __init__(self, responses):
        super().__init__("owner/repo")
        self.responses = list(responses)
        self.calls = []

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        return self.responses.pop(0)


class GitHubPRAdapterTests(unittest.TestCase):
    def test_pr_search_paginates_exact_refs_and_closed_state(self):
        row = {"number": 42}
        github = FakeGitHub(([row],))
        self.assertEqual(github.pull_requests_for_refs(base_ref="pases/base", head_ref="pases/work"), [row])
        query = parse_qs(urlsplit(github.calls[0][1].replace("?page=1&per_page=100", "")).query)
        self.assertEqual(query["state"], ["all"])
        self.assertEqual(query["base"], ["pases/base"])
        self.assertEqual(query["head"], ["owner:pases/work"])

    def test_create_and_readback_use_structured_pr_api(self):
        created = {"number": 43}
        readback = {"number": 43, "state": "open"}
        github = FakeGitHub((created, readback))
        self.assertEqual(github.create_pull_request(
            title="Issue work", body="Summary\n\nCloses #30", head_ref="pases/work", base_ref="pases/base",
        ), created)
        self.assertEqual(github.pull_request(43), readback)
        self.assertEqual(github.calls[0][0], "POST")
        self.assertEqual(github.calls[0][2]["head"], "owner:pases/work")
        self.assertEqual(github.calls[0][2]["base"], "pases/base")
        self.assertFalse(github.calls[0][2]["draft"])

    def test_api_shape_and_invalid_refs_fail_closed(self):
        with self.assertRaises(GitHubError):
            FakeGitHub(({},)).pull_request(43)
        with self.assertRaises(GitHubError):
            FakeGitHub(([],)).pull_requests_for_refs(base_ref="", head_ref="branch")

    def test_merge_uses_exact_head_precondition_and_validates_response(self):
        response = {"merged": True, "sha": "a" * 40}
        github = FakeGitHub((response,))
        self.assertEqual(github.merge_pull_request(64, "b" * 40), response)
        self.assertEqual(github.calls, [("PUT", "repos/owner/repo/pulls/64/merge",
                                        {"sha": "b" * 40, "merge_method": "merge"})])
        with self.assertRaisesRegex(GitHubError, "expected HEAD SHA"):
            FakeGitHub(()).merge_pull_request(64, "invalid")
        with self.assertRaisesRegex(GitHubError, "does not confirm a merge"):
            FakeGitHub(({"merged": False},)).merge_pull_request(64, "b" * 40)


if __name__ == "__main__":
    unittest.main()
