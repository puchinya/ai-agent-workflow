from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.admin_auth import (  # noqa: E402
    AdminAuthError,
    temporary_admin_client,
)
from p_ases.github import GitHub


class AdminAuthenticationTests(unittest.TestCase):
    def test_non_tty_blocks_before_getpass_or_api_call(self):
        prompt = Mock(side_effect=AssertionError("credential prompt must not run"))
        factory = Mock(side_effect=AssertionError("API client must not be created"))
        with self.assertRaises(AdminAuthError):
            with temporary_admin_client(
                "puchinya/ai-agent-workflow",
                stdin=Mock(isatty=lambda: False),
                getpass_fn=prompt,
                github_factory=factory,
            ):
                self.fail("non-TTY admin session must not yield")
        prompt.assert_not_called()
        factory.assert_not_called()

    def test_temporary_credential_reaches_only_active_gh_api_child(self):
        token = "marker-admin-token"
        child_environments: list[dict[str, str]] = []

        def fake_run(argv, **kwargs):
            child_environments.append(dict(kwargs["env"]))
            return Mock(returncode=0, stdout="{}", stderr="")

        with patch.dict(os.environ, {"GH_TOKEN": "ambient-gh", "GITHUB_TOKEN": "ambient-github"}), \
             patch("p_ases.github.subprocess.run", side_effect=fake_run):
            with temporary_admin_client(
                "puchinya/ai-agent-workflow",
                stdin=Mock(isatty=lambda: True),
                getpass_fn=lambda _prompt: token,
                github_factory=GitHub,
            ) as github:
                github.request("GET", "user")
                self.assertEqual(os.environ["GH_TOKEN"], "ambient-gh")
                self.assertEqual(os.environ["GITHUB_TOKEN"], "ambient-github")

            GitHub("puchinya/ai-agent-workflow").request("GET", "user")

        self.assertEqual(child_environments[0].get("GH_TOKEN"), token)
        self.assertNotIn("GITHUB_TOKEN", child_environments[0])
        self.assertNotIn(token, child_environments[1].values())
        self.assertNotIn(token, repr(github))


if __name__ == "__main__":
    unittest.main()
