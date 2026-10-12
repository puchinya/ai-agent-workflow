from __future__ import annotations

import base64
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHub, GitHubError


HEAD = "a" * 40
PATH = "runtime/p_ases/gate_policy.py"
CONTENT = b"review evidence at the exact commit\n"
BLOB_SHA = hashlib.sha1(b"blob " + str(len(CONTENT)).encode() + b"\x00" + CONTENT).hexdigest()


class FakeGitHub(GitHub):
    def __init__(self, response):
        super().__init__("puchinya/ai-agent-workflow")
        self.response = response
        self.calls = []

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        return self.response


class GitHubReviewArtifactTests(unittest.TestCase):
    def test_content_at_ref_verifies_file_path_commit_and_git_blob_digest(self):
        encoded = base64.b64encode(CONTENT).decode("ascii")
        github = FakeGitHub({"path": PATH, "type": "file", "encoding": "base64",
                             "content": encoded, "sha": BLOB_SHA})
        self.assertEqual(github.content_at_ref(PATH, HEAD), CONTENT)
        method, endpoint, payload = github.calls[0]
        self.assertEqual((method, payload), ("GET", None))
        self.assertIn(f"contents/{PATH}?ref={HEAD}", endpoint)

    def test_content_at_ref_rejects_tampered_digest_malformed_and_unsafe_refs(self):
        encoded = base64.b64encode(CONTENT).decode("ascii")
        tampered = FakeGitHub({"path": PATH, "type": "file", "encoding": "base64",
                               "content": encoded, "sha": "f" * 40})
        with self.assertRaisesRegex(GitHubError, "does not match"):
            tampered.content_at_ref(PATH, HEAD)
        malformed = FakeGitHub({"path": PATH, "type": "file", "encoding": "base64",
                                "content": "not base64!", "sha": BLOB_SHA})
        with self.assertRaisesRegex(GitHubError, "encoding"):
            malformed.content_at_ref(PATH, HEAD)
        with self.assertRaisesRegex(GitHubError, "path is invalid"):
            FakeGitHub({}).content_at_ref("../secret", HEAD)
        with self.assertRaisesRegex(GitHubError, "full commit SHA"):
            FakeGitHub({}).content_at_ref(PATH, "bad")


if __name__ == "__main__":
    unittest.main()
