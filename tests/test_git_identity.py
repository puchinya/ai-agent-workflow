from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.git import GitError, verify_remote_repository


class GitRemoteIdentityTests(unittest.TestCase):
    def test_all_fetch_and_push_urls_must_resolve_to_the_pinned_repository(self):
        def run_git(_root: Path, *args: str) -> str:
            if args == ("remote", "get-url", "--all", "origin"):
                return "git@github.com:puchinya/ai-agent-workflow.git\nhttps://github.com/puchinya/ai-agent-workflow.git"
            if args == ("remote", "get-url", "--push", "--all", "origin"):
                return "https://github.com/puchinya/ai-agent-workflow.git"
            raise AssertionError(args)

        with patch("p_ases.git.run_git", side_effect=run_git):
            verify_remote_repository(Path("/tmp/repo"), "puchinya/ai-agent-workflow")

    def test_foreign_push_url_is_rejected_without_disclosing_remote_url(self):
        def run_git(_root: Path, *args: str) -> str:
            if args == ("remote", "get-url", "--all", "origin"):
                return "https://github.com/puchinya/ai-agent-workflow.git"
            if args == ("remote", "get-url", "--push", "--all", "origin"):
                return "https://user:secret@github.com/attacker/other.git"
            raise AssertionError(args)

        with patch("p_ases.git.run_git", side_effect=run_git):
            with self.assertRaisesRegex(GitError, "pinned GitHub repository") as caught:
                verify_remote_repository(Path("/tmp/repo"), "puchinya/ai-agent-workflow")
        self.assertNotIn("secret", str(caught.exception))

    def test_missing_remote_url_fails_closed(self):
        with patch("p_ases.git.run_git", return_value=""):
            with self.assertRaisesRegex(GitError, "no configured"):
                verify_remote_repository(Path("/tmp/repo"), "puchinya/ai-agent-workflow")


if __name__ == "__main__":
    unittest.main()
