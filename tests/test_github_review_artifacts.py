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


class TreeGitHub(GitHub):
    def __init__(self, *, leaf_mode="100644", leaf_type="blob", blob_sha=BLOB_SHA, truncated=False):
        super().__init__("puchinya/ai-agent-workflow")
        self.leaf_mode, self.leaf_type, self.blob_sha, self.truncated = leaf_mode, leaf_type, blob_sha, truncated

    def request(self, method, endpoint, payload=None):
        self.assertions = (method, payload)
        if endpoint.endswith("/git/commits/" + HEAD):
            return {"tree": {"sha": "b" * 40}}
        if endpoint.endswith("/git/trees/" + "b" * 40):
            return {"tree": [{"path": "runtime", "mode": "040000", "type": "tree", "sha": "c" * 40}],
                    "truncated": self.truncated}
        if endpoint.endswith("/git/trees/" + "c" * 40):
            return {"tree": [{"path": "p_ases", "mode": "040000", "type": "tree", "sha": "d" * 40}],
                    "truncated": False}
        if endpoint.endswith("/git/trees/" + "d" * 40):
            return {"tree": [{"path": "gate_policy.py", "mode": self.leaf_mode,
                               "type": self.leaf_type, "sha": self.blob_sha}], "truncated": False}
        encoded = base64.b64encode(CONTENT).decode("ascii")
        return {"path": PATH, "type": "file", "encoding": "base64", "content": encoded, "sha": BLOB_SHA}


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

    def test_phase_artifact_reader_requires_regular_tree_entry_at_exact_commit(self):
        self.assertEqual(TreeGitHub().regular_content_at_ref(PATH, HEAD), CONTENT)
        with self.assertRaisesRegex(GitHubError, "symlinks"):
            TreeGitHub(leaf_mode="120000", leaf_type="blob").regular_content_at_ref(PATH, HEAD)
        with self.assertRaisesRegex(GitHubError, "truncated"):
            TreeGitHub(truncated=True).regular_content_at_ref(PATH, HEAD)
        with self.assertRaisesRegex(GitHubError, "differs"):
            TreeGitHub(blob_sha="f" * 40).regular_content_at_ref(PATH, HEAD)


if __name__ == "__main__":
    unittest.main()
