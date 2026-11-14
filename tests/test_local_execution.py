from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import local_execution  # noqa: E402
from p_ases.consumer_activation import ConsumerActivationError, setup_consumer_activation  # noqa: E402
from p_ases.ruleset_management import RulesetManagementError, build_ruleset_plan  # noqa: E402


REPOSITORY = "puchinya/ai-agent-workflow"


class LocalExecutionTests(unittest.TestCase):
    def tearDown(self):
        local_execution._AUTHORIZED.set(False)
        local_execution._ACTIVE_ADMIN_CLIENT.set(None)

    @staticmethod
    def local_env():
        return patch.dict(os.environ, {name: "" for name in local_execution._REMOTE_MARKERS})

    @staticmethod
    def tty_streams():
        return (
            patch("p_ases.local_execution.sys.stdin", Mock(isatty=lambda: True)),
            patch("p_ases.local_execution.sys.stdout", Mock(isatty=lambda: True)),
            patch("p_ases.local_execution.sys.stderr", Mock(isatty=lambda: True)),
        )

    def test_local_codex_claude_and_owner_vm_have_identical_eligibility(self):
        streams = dict(stdin_tty=True, stdout_tty=True, stderr_tty=True)
        codex = local_execution.locality_blockers({"CODEX_CLI": "1"}, **streams)
        claude = local_execution.locality_blockers({"CLAUDE_CODE": "1"}, **streams)
        vm = local_execution.locality_blockers({"PASES_OWNER_CONTROLLED_LOCAL_VM": "1"}, **streams)
        self.assertEqual(codex, ())
        self.assertEqual(claude, codex)
        self.assertEqual(vm, codex)

    def test_hosted_remote_ci_and_noninteractive_contexts_are_rejected(self):
        streams = dict(stdin_tty=True, stdout_tty=True, stderr_tty=True)
        for marker in ("CODEX_CLOUD", "CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "SSH_CONNECTION"):
            with self.subTest(marker=marker):
                blockers = local_execution.locality_blockers({marker: "1"}, **streams)
                self.assertIn(f"REMOTE_OR_HOSTED_CONTEXT:{marker}", blockers)
        self.assertIn(
            "LOCAL_INTERACTIVE_TERMINAL_REQUIRED",
            local_execution.locality_blockers({}, stdin_tty=False, stdout_tty=False, stderr_tty=False),
        )

    def test_local_guard_requires_typed_operator_confirmation(self):
        token = local_execution._AUTHORIZED.set(False)
        with self.local_env(), self.tty_streams()[0], self.tty_streams()[1], self.tty_streams()[2], \
             patch("builtins.input", return_value="wrong"):
            with self.assertRaisesRegex(local_execution.LocalExecutionError, "CONFIRMATION_REQUIRED"):
                local_execution.require_local_activation_execution()
        local_execution._AUTHORIZED.reset(token)

        token = local_execution._AUTHORIZED.set(False)
        with self.local_env(), self.tty_streams()[0], self.tty_streams()[1], self.tty_streams()[2], \
             patch("builtins.input", return_value="I CONTROL THIS LOCAL HOST"):
            local_execution.require_local_activation_execution()
            self.assertTrue(local_execution._AUTHORIZED.get())
        local_execution._AUTHORIZED.reset(token)

    def test_local_authorization_rechecks_host_context_on_every_call(self):
        token = local_execution._AUTHORIZED.set(False)
        with self.local_env(), self.tty_streams()[0], self.tty_streams()[1], self.tty_streams()[2], \
             patch("builtins.input", return_value="I CONTROL THIS LOCAL HOST") as prompt:
            local_execution.require_local_activation_execution()
            with patch.dict(os.environ, {"CODEX_CLOUD": "1"}):
                with self.assertRaisesRegex(local_execution.LocalExecutionError, "REMOTE_OR_HOSTED_CONTEXT"):
                    local_execution.require_local_activation_execution()
            prompt.assert_called_once_with(
                "Live Activation requires an owner-controlled local terminal. "
                "Type 'I CONTROL THIS LOCAL HOST' to confirm: "
            )
        local_execution._AUTHORIZED.reset(token)

    def test_cloud_marker_blocks_before_prompt(self):
        token = local_execution._AUTHORIZED.set(False)
        with patch.dict(os.environ, {"CODEX_CLOUD": "1"}), \
             self.tty_streams()[0], self.tty_streams()[1], self.tty_streams()[2], \
             patch("builtins.input", side_effect=AssertionError("must not prompt in Cloud")):
            with self.assertRaisesRegex(local_execution.LocalExecutionError, "REMOTE_OR_HOSTED_CONTEXT"):
                local_execution.require_local_activation_execution()
        local_execution._AUTHORIZED.reset(token)

    def test_isolated_device_client_requires_active_owner_verified_session(self):
        with tempfile.TemporaryDirectory() as parent:
            config = Path(parent) / "gh-config"
            config.mkdir(mode=0o700)
            if os.name == "posix":
                os.chmod(config, stat.S_IRWXU)
            client = SimpleNamespace(
                repo=REPOSITORY, _admin_config_dir=str(config),
                authenticated_user=Mock(return_value={"id": 3744776, "type": "User"}),
            )
            with self.assertRaisesRegex(local_execution.LocalExecutionError, "outside its verified device session"):
                local_execution.require_isolated_device_admin_client(client)
            with patch("p_ases.local_execution._require_private_device_config"):
                with local_execution.verified_device_admin_session(client):
                    local_execution.require_isolated_device_admin_client(client)
            with self.assertRaisesRegex(local_execution.LocalExecutionError, "outside its verified device session"):
                local_execution.require_isolated_device_admin_client(client)
            client.authenticated_user.assert_called_once_with()

    def test_wrong_authenticated_owner_never_enters_device_session(self):
        with tempfile.TemporaryDirectory() as parent:
            config = Path(parent) / "gh-config"
            config.mkdir(mode=0o700)
            if os.name == "posix":
                os.chmod(config, stat.S_IRWXU)
            client = SimpleNamespace(
                repo=REPOSITORY, _admin_config_dir=str(config),
                authenticated_user=Mock(return_value={"id": 42, "type": "User"}),
            )
            with patch("p_ases.local_execution._require_private_device_config"):
                with self.assertRaisesRegex(local_execution.LocalExecutionError, "not the repository owner"):
                    with local_execution.verified_device_admin_session(client):
                        self.fail("wrong owner must not enter")

    def test_device_session_rejects_nonprivate_config_before_owner_read(self):
        with tempfile.TemporaryDirectory() as parent:
            config = Path(parent) / "gh-config"
            config.mkdir(mode=0o700)
            client = SimpleNamespace(
                repo=REPOSITORY, _admin_config_dir=str(config),
                authenticated_user=Mock(return_value={"id": 3744776, "type": "User"}),
            )
            with patch("p_ases.local_execution.stat.S_IMODE", return_value=0o755):
                with self.assertRaisesRegex(local_execution.LocalExecutionError, "GH_CONFIG_DIR must be private mode 0700"):
                    with local_execution.verified_device_admin_session(client):
                        self.fail("nonprivate device config must not enter")
            client.authenticated_user.assert_not_called()

    def test_direct_runtime_guards_block_before_any_github_read_or_write(self):
        class TrapGitHub:
            repo = REPOSITORY

            def __init__(self):
                self.calls = []

            def __getattr__(self, name):
                def trap(*_args, **_kwargs):
                    self.calls.append(name)
                    raise AssertionError(f"GitHub access before locality gate: {name}")
                return trap

        github = TrapGitHub()
        token = local_execution._AUTHORIZED.set(False)
        with patch.dict(os.environ, {name: "" for name in local_execution._REMOTE_MARKERS}), \
             self.tty_streams()[0], self.tty_streams()[1], self.tty_streams()[2], \
             patch("builtins.input", return_value="I CONTROL THIS LOCAL HOST"):
            with self.assertRaisesRegex(RulesetManagementError, "ADMIN_DEVICE_AUTH_REQUIRED"):
                build_ruleset_plan(Path("/unused"), github)
            with self.assertRaisesRegex(ConsumerActivationError, "ADMIN_DEVICE_AUTH_REQUIRED"):
                setup_consumer_activation(Path("/unused"), github, policy_github=github)
        local_execution._AUTHORIZED.reset(token)
        self.assertEqual(github.calls, [])

    def test_live_runtime_entrypoints_reject_cloud_before_api_calls(self):
        class TrapGitHub:
            repo = REPOSITORY

            def __init__(self):
                self.calls = []

            def __getattr__(self, name):
                def trap(*_args, **_kwargs):
                    self.calls.append(name)
                    raise AssertionError(f"GitHub access before Cloud rejection: {name}")
                return trap

        github = TrapGitHub()
        token = local_execution._AUTHORIZED.set(False)
        with patch.dict(os.environ, {"CODEX_CLOUD": "1"}), \
             self.tty_streams()[0], self.tty_streams()[1], self.tty_streams()[2], \
             patch("builtins.input", side_effect=AssertionError("must not prompt in Cloud")):
            with self.assertRaisesRegex(RulesetManagementError, "REMOTE_OR_HOSTED_CONTEXT"):
                build_ruleset_plan(Path("/unused"), github)
            with self.assertRaisesRegex(ConsumerActivationError, "REMOTE_OR_HOSTED_CONTEXT"):
                setup_consumer_activation(Path("/unused"), github, policy_github=github)
        local_execution._AUTHORIZED.reset(token)
        self.assertEqual(github.calls, [])


if __name__ == "__main__":
    unittest.main()
