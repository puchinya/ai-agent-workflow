from __future__ import annotations

import os
import signal
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.admin_auth import (  # noqa: E402
    ADMIN_AUTH_MODES,
    AdminAuthError,
    _secure_private_config,
    temporary_admin_client,
)
from p_ases.github import GitHub


class AdminAuthenticationTests(unittest.TestCase):
    def local_environment(self):
        return patch.dict(os.environ, {
            "CODEX_ENVIRONMENT_ID": "", "CODEX_EXEC_SERVER_REMOTE_BASE_URL": "",
            "CODEX_CLOUD": "", "CODESPACE_NAME": "",
        })

    @staticmethod
    def fake_process(*, wait_side_effect=None, returncode=0):
        process = Mock()
        process.poll.return_value = None
        if wait_side_effect is None:
            process.wait.return_value = returncode
        else:
            process.wait.side_effect = wait_side_effect
        return process

    @staticmethod
    def secure_test_config(path):
        if os.name == "posix":
            os.chmod(path, stat.S_IRWXU)

    def test_device_config_requires_a_verifiable_private_mode(self):
        with tempfile.TemporaryDirectory() as parent:
            path = Path(parent) / "private-config"
            path.mkdir()
            if os.name == "posix":
                _secure_private_config(path)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            else:
                with self.assertRaisesRegex(AdminAuthError, "ADMIN_DEVICE_LOGIN_UNAVAILABLE"):
                    _secure_private_config(path)

    def test_device_mode_blocks_without_secure_config_permissions(self):
        with tempfile.TemporaryDirectory() as parent, self.local_environment():
            config_dir = Path(parent) / "private-config"
            config_dir.mkdir()
            login = Mock(side_effect=AssertionError("login must not start without private config"))
            with patch("p_ases.admin_auth.tempfile.mkdtemp", return_value=str(config_dir)), \
                 patch("p_ases.admin_auth._secure_private_config", side_effect=AdminAuthError(
                     "ADMIN_DEVICE_LOGIN_UNAVAILABLE: private config permissions unavailable")), \
                 patch("p_ases.admin_auth.subprocess.Popen", login), \
                 patch("p_ases.admin_auth.sys.stdout", Mock(isatty=lambda: True)):
                with self.assertRaisesRegex(AdminAuthError, "ADMIN_DEVICE_LOGIN_UNAVAILABLE"):
                    with temporary_admin_client(
                        "puchinya/ai-agent-workflow", auth_mode="isolated-gh-device",
                        stdin=Mock(isatty=lambda: True), github_factory=GitHub,
                    ):
                        self.fail("device mode must block without private config")
            self.assertFalse(config_dir.exists())
            login.assert_not_called()

    def test_non_tty_blocks_before_getpass_or_api_call(self):
        prompt = Mock(side_effect=AssertionError("credential prompt must not run"))
        factory = Mock(side_effect=AssertionError("API client must not be created"))
        with self.local_environment(), self.assertRaises(AdminAuthError):
            with temporary_admin_client(
                "puchinya/ai-agent-workflow", stdin=Mock(isatty=lambda: False),
                getpass_fn=prompt, github_factory=factory,
            ):
                self.fail("non-TTY admin session must not yield")
        prompt.assert_not_called()
        factory.assert_not_called()

    def test_temporary_credential_reaches_only_active_gh_api_child(self):
        token = "marker-admin-token"
        child_environments: list[dict[str, str]] = []

        def fake_run(argv, **kwargs):
            child_environments.append(dict(kwargs["env"]))
            stdout = '{"data":{}}' if "graphql" in argv else "{}"
            return Mock(returncode=0, stdout=stdout, stderr="")

        parent_auth = {
            "GH_TOKEN": "ambient-gh", "GITHUB_TOKEN": "ambient-github",
            "GH_ENTERPRISE_TOKEN": "ambient-enterprise-gh",
            "GITHUB_ENTERPRISE_TOKEN": "ambient-enterprise-github",
        }
        with self.local_environment(), patch.dict(os.environ, parent_auth), \
             patch("p_ases.github.subprocess.run", side_effect=fake_run):
            parent_before = {key: os.environ.get(key) for key in parent_auth}
            with temporary_admin_client(
                "puchinya/ai-agent-workflow", auth_mode="pat", stdin=Mock(isatty=lambda: True),
                getpass_fn=lambda _prompt: token, github_factory=GitHub,
            ) as github:
                github.request("GET", "user")
                github._graphql("query { viewer { login } }", {})
                self.assertEqual({key: os.environ.get(key) for key in parent_auth}, parent_before)

            GitHub("puchinya/ai-agent-workflow").request("GET", "user")

        self.assertEqual(child_environments[0].get("GH_TOKEN"), token)
        self.assertNotIn("GITHUB_TOKEN", child_environments[0])
        self.assertNotIn("GH_ENTERPRISE_TOKEN", child_environments[0])
        self.assertNotIn("GITHUB_ENTERPRISE_TOKEN", child_environments[0])
        self.assertEqual(child_environments[1].get("GH_TOKEN"), token)
        self.assertNotIn("GITHUB_TOKEN", child_environments[1])
        self.assertNotIn("GH_ENTERPRISE_TOKEN", child_environments[1])
        self.assertNotIn("GITHUB_ENTERPRISE_TOKEN", child_environments[1])
        self.assertNotIn(token, child_environments[2].values())
        self.assertNotIn(token, repr(github))

    def test_device_mode_uses_one_private_config_for_gh_children(self):
        self.assertEqual(ADMIN_AUTH_MODES, ("pat", "isolated-gh-device"))
        token_env = {
            "GH_TOKEN": "ambient-gh", "GITHUB_TOKEN": "ambient-github",
            "GH_ENTERPRISE_TOKEN": "ambient-enterprise-gh",
            "GITHUB_ENTERPRISE_TOKEN": "ambient-enterprise-github",
            "GH_CONFIG_DIR": "/existing/normal-gh-config",
        }
        calls = []

        def fake_popen(argv, **kwargs):
            calls.append((list(argv), dict(kwargs["env"]), kwargs.get("stdin")))
            return self.fake_process()

        def fake_api_run(argv, **kwargs):
            calls.append((list(argv), dict(kwargs["env"]), kwargs.get("stdin")))
            stdout = '{"data":{}}' if "graphql" in argv else "{}"
            return Mock(returncode=0, stdout=stdout, stderr="")

        with self.local_environment(), patch.dict(os.environ, token_env), \
             patch("p_ases.admin_auth._secure_private_config", side_effect=self.secure_test_config), \
             patch("p_ases.admin_auth.subprocess.Popen", side_effect=fake_popen), \
             patch("p_ases.github.subprocess.run", side_effect=fake_api_run), \
             patch("p_ases.admin_auth.sys.stdout", Mock(isatty=lambda: True)):
            parent_before = {key: os.environ.get(key) for key in token_env}
            with temporary_admin_client(
                "puchinya/ai-agent-workflow",
                stdin=Mock(isatty=lambda: True), github_factory=GitHub,
            ) as github:
                config_dir = Path(calls[0][1]["GH_CONFIG_DIR"])
                self.assertTrue(config_dir.is_dir())
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(config_dir.stat().st_mode), 0o700)
                self.assertEqual(github._admin_config_dir, str(config_dir))
                github.request("GET", "user")
                github._graphql("query { viewer { login } }", {})
                self.assertEqual(calls[1][0], ["gh", "api", "--method", "GET", "user"])
                self.assertEqual(calls[1][1]["GH_CONFIG_DIR"], str(config_dir))
                self.assertEqual(calls[2][0], ["gh", "api", "graphql", "--input", "-"])
                self.assertEqual(calls[2][1]["GH_CONFIG_DIR"], str(config_dir))
                self.assertEqual({key: os.environ.get(key) for key in token_env}, parent_before)
                for _name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
                    self.assertNotIn(_name, calls[0][1])
                    self.assertNotIn(_name, calls[1][1])
                    self.assertNotIn(_name, calls[2][1])
                self.assertNotIn("--token", calls[0][0])
                self.assertEqual(calls[0][0], [
                    "gh", "auth", "login", "--hostname", "github.com", "--web",
                    "--git-protocol", "https", "--insecure-storage",
                ])
                self.assertIsNotNone(calls[0][2])
            self.assertFalse(config_dir.exists())
            self.assertIsNone(github._admin_config_dir)
            self.assertEqual({key: os.environ.get(key) for key in token_env}, parent_before)

    def test_cloud_device_flow_blocks_before_tty_or_login(self):
        prompt = Mock(side_effect=AssertionError("device mode must not request PAT"))
        factory = Mock(side_effect=AssertionError("Cloud device mode must not create a client"))
        run = Mock(side_effect=AssertionError("Cloud device mode must not launch gh"))
        with patch.dict(os.environ, {"CODEX_CLOUD": "1"}), \
             patch("p_ases.admin_auth.subprocess.Popen", run):
            with self.assertRaisesRegex(AdminAuthError, "ADMIN_DEVICE_LOGIN_UNAVAILABLE"):
                with temporary_admin_client(
                    "puchinya/ai-agent-workflow", auth_mode="isolated-gh-device",
                    stdin=Mock(isatty=lambda: False), getpass_fn=prompt, github_factory=factory,
                ):
                    self.fail("Cloud device flow must not yield")
        prompt.assert_not_called()
        factory.assert_not_called()
        run.assert_not_called()

    def test_cloud_device_auth_uses_private_child_for_read_only_identity_when_tty_exists(self):
        calls = []

        def fake_popen(argv, **kwargs):
            calls.append((list(argv), dict(kwargs["env"])))
            return self.fake_process()

        def fake_api_run(argv, **kwargs):
            calls.append((list(argv), dict(kwargs["env"])))
            return Mock(returncode=0, stdout='{"id":3744776,"type":"User"}', stderr="")

        with patch.dict(os.environ, {
            "CODEX_CLOUD": "1", "GH_TOKEN": "ambient-gh", "GITHUB_TOKEN": "ambient-github",
        }), patch("p_ases.admin_auth._secure_private_config", side_effect=self.secure_test_config), \
             patch("p_ases.admin_auth.subprocess.Popen", side_effect=fake_popen), \
             patch("p_ases.github.subprocess.run", side_effect=fake_api_run), \
             patch("p_ases.admin_auth.sys.stdout", Mock(isatty=lambda: True)):
            with temporary_admin_client(
                "puchinya/ai-agent-workflow", auth_mode="isolated-gh-device",
                stdin=Mock(isatty=lambda: True), github_factory=GitHub,
            ) as github:
                self.assertEqual(github.request("GET", "user"), {"id": 3744776, "type": "User"})
                config_dir = Path(github._admin_config_dir)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1][0], ["gh", "api", "--method", "GET", "user"])
                self.assertEqual(calls[1][1]["GH_CONFIG_DIR"], str(config_dir))
                self.assertNotIn("GH_TOKEN", calls[1][1])
                self.assertNotIn("GITHUB_TOKEN", calls[1][1])
            self.assertFalse(config_dir.exists())

    def test_device_login_failure_and_interruptions_remove_private_config(self):
        def keyboard_process(_calls):
            process = self.fake_process(wait_side_effect=[KeyboardInterrupt(), -15])
            return process

        def sigterm_process(_calls):
            wait_count = [0]

            def wait(**_kwargs):
                if wait_count[0] == 0:
                    wait_count[0] += 1
                    self._raise_sigterm()
                return -15

            process = self.fake_process()
            process.wait.side_effect = wait
            return process

        scenarios = (
            ("nonzero", lambda _calls: self.fake_process(returncode=1)),
            ("keyboard", keyboard_process),
            ("sigterm", sigterm_process),
        )
        for name, behavior in scenarios:
            with self.subTest(name=name), self.local_environment():
                config_dirs = []
                processes = []

                def fake_popen(_argv, **kwargs):
                    config_dirs.append(Path(kwargs["env"]["GH_CONFIG_DIR"]))
                    process = behavior(config_dirs)
                    processes.append(process)
                    return process

                with patch("p_ases.admin_auth._secure_private_config", side_effect=self.secure_test_config), \
                     patch("p_ases.admin_auth.subprocess.Popen", side_effect=fake_popen), \
                     patch("p_ases.admin_auth.sys.stdout", Mock(isatty=lambda: True)):
                    with self.assertRaisesRegex(AdminAuthError, "ADMIN_DEVICE_LOGIN_UNAVAILABLE"):
                        with temporary_admin_client(
                            "puchinya/ai-agent-workflow", auth_mode="isolated-gh-device",
                            stdin=Mock(isatty=lambda: True), github_factory=GitHub,
                        ):
                            self.fail("failed device login must not yield")
                self.assertEqual(len(config_dirs), 1)
                self.assertFalse(config_dirs[0].exists())
                if name != "nonzero":
                    processes[0].terminate.assert_called_once_with()

    @staticmethod
    def _raise_sigterm():
        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)

    def test_device_client_exception_cleans_config_and_restores_normal_auth(self):
        calls = []

        def fake_popen(argv, **kwargs):
            calls.append((list(argv), dict(kwargs["env"])))
            return self.fake_process()

        with self.local_environment(), patch.dict(os.environ, {"GH_TOKEN": "ambient-gh"}), \
             patch("p_ases.admin_auth._secure_private_config", side_effect=self.secure_test_config), \
             patch("p_ases.admin_auth.subprocess.Popen", side_effect=fake_popen), \
             patch("p_ases.github.subprocess.run", return_value=Mock(
                 returncode=1, stdout="", stderr="HTTP 403")), \
             patch("p_ases.admin_auth.sys.stdout", Mock(isatty=lambda: True)):
            with temporary_admin_client(
                "puchinya/ai-agent-workflow", auth_mode="isolated-gh-device",
                stdin=Mock(isatty=lambda: True), github_factory=GitHub,
            ) as github:
                config_dir = Path(github._admin_config_dir)
                with self.assertRaises(Exception):
                    github.request("GET", "user")
            self.assertFalse(config_dir.exists())
            self.assertEqual(os.environ["GH_TOKEN"], "ambient-gh")


if __name__ == "__main__":
    unittest.main()
