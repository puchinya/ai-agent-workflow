from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import publish_adc
from p_ases.cli import CLI_ADVANCE_TARGETS, _parser, main
from test_adc_intake import FakeGitHub, adc_bytes


class PasesCLITests(unittest.TestCase):
    def test_advance_cli_excludes_readiness_approval_and_close_targets(self):
        self.assertNotIn("user-review", CLI_ADVANCE_TARGETS)
        self.assertNotIn("closed", CLI_ADVANCE_TARGETS)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            _parser().parse_args([
                "issue", "advance", "1", "closed", "--kind", "child", "--repo", "octo/repo",
            ])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_advance_help_documents_later_evidence_and_github_readback(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            _parser().parse_args(["issue", "advance", "--help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("Review Readiness", help_text)
        self.assertIn("Issues #30 and #31", help_text)
        self.assertNotIn("closed", help_text)

    def test_explicit_repository_lets_github_commands_run_without_local_checkout(self):
        github = FakeGitHub()
        publish_adc(github, 1, adc_bytes(), state="approved", explicitly_approved=True)
        output = io.StringIO()
        with patch("p_ases.cli._repo_root", side_effect=AssertionError("checkout lookup was attempted")), \
                patch("p_ases.cli.GitHub", return_value=github), \
                contextlib.redirect_stdout(output):
            status = main(["adc", "verify", "1", "--repo", "octo/repo"])
        self.assertEqual(status, 0)
        self.assertIn('"status": "VERIFIED"', output.getvalue())

    def test_issue_31_cli_namespaces_are_present_and_chat_file_fails_closed(self):
        args = _parser().parse_args([
            "user-review", "start", "31", "37", "a" * 40, "plan.json", "readiness.json",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((args.namespace, args.verb), ("user-review", "start"))
        args = _parser().parse_args([
            "issue", "integration-check", "26", "--verification-comment-id", "100",
            "--acceptance-comment-id", "101",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((args.namespace, args.verb), ("issue", "integration-check"))
        self.assertEqual((args.verification_comment_id, args.acceptance_comment_id), (100, 101))
        migration = _parser().parse_args([
            "delivery", "parent-migrate-labels", "26", "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertFalse(migration.apply)
        evidence = _parser().parse_args([
            "delivery", "parent-evidence", "26", "verification", "result.json",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((evidence.verb, evidence.kind), ("parent-evidence", "verification"))
        stdout = io.StringIO()
        with patch("p_ases.cli._repo_root", return_value=ROOT), contextlib.redirect_stdout(stdout):
            status = main(["user-review", "record", "31", "37", "untrusted.json",
                           "--repo", "octo/repo", "--root", str(ROOT)])
        self.assertEqual(status, 2)
        self.assertIn("UNVERIFIABLE_CHAT_IDENTITY", stdout.getvalue())

    def test_final_delivery_cli_exposes_all_distinct_gates(self):
        args = _parser().parse_args([
            "delivery", "final", "31", "37", "a" * 40, "plan.json", "verification.json",
            "acceptance.json", "self.json", "independent.json", "readiness.json", "review.json",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((args.namespace, args.verb), ("delivery", "final"))


if __name__ == "__main__":
    unittest.main()
