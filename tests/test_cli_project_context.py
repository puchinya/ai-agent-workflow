from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import ADCError  # noqa: E402
from p_ases.cli import _parser, main  # noqa: E402
from p_ases.execution import ExecutionBinding, write_binding  # noqa: E402
from p_ases.github import GitHubError  # noqa: E402
from p_ases.work import execution_binding_path  # noqa: E402


class ProjectContextCLITests(unittest.TestCase):
    def profile(self):
        return {
            "schema_version": 2, "initialized": True, "project_name": "p-ases-test",
            "components": [],
            "branch": {"prefix": "pases", "max_slug_length": 48,
                       "cleanup_on_switch": [], "required_checks": [{"name": "ci", "trusted_app_id": 15368}]},
            "workspace": {"isolation": "auto"},
            "milestones": {"mode": "required", "version_source": {
                "type": "python-attr", "path": "runtime/p_ases/__init__.py", "field": "__version__"}},
            "hooks": {"branch_switch": [], "verify_quick": [], "verify_final": []},
        }

    def verified_adc(self, digest="a" * 64, comment_id=99):
        return SimpleNamespace(
            contract=SimpleNamespace(repository="owner/repo"),
            pointer=SimpleNamespace(state="approved", comment_id=comment_id, sha256=digest),
        )

    def run_json(self, argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(argv)
        return result, json.loads(output.getvalue())

    def test_help_lists_exactly_twelve_namespaces_and_legacy_flat_cli_is_not_parsed(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                _parser().parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        for namespace in ("project", "context", "adc", "issue", "docs", "work", "pr",
                          "verification", "acceptance", "audit", "user-review", "delivery"):
            self.assertIn(namespace, help_text)
        self.assertNotIn("agent-context", help_text)
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            _parser().parse_args(["agent-context", "32"])
        self.assertEqual(raised.exception.code, 2)

    def test_project_status_reads_valid_profile_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".agent/project.json"
            config.parent.mkdir()
            config.write_text(json.dumps(self.profile()), encoding="utf-8")
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            status, result = self.run_json(["project", "status", "--root", str(root)])
            after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(status, 0)
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["project_name"], "p-ases-test")
            self.assertEqual(before, after)

    def test_project_status_reports_missing_and_invalid_profile_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, result = self.run_json(["project", "status", "--root", str(root)])
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertEqual(list(root.iterdir()), [])
            config = root / ".agent/project.json"
            config.parent.mkdir()
            config.write_text("{invalid", encoding="utf-8")
            original = config.read_bytes()
            status, result = self.run_json(["project", "status", "--root", str(root)])
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertEqual(config.read_bytes(), original)

    def test_context_show_reports_unbound_and_does_not_create_work_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            github = SimpleNamespace(issue=lambda number: {"number": number, "state": "open"})
            with patch("p_ases.cli.GitHub", return_value=github), \
                 patch("p_ases.cli.verify_adc", return_value=self.verified_adc()):
                status, result = self.run_json(["context", "show", "32", "--root", str(root),
                                                "--repo", "owner/repo"])
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "NOT_BOUND")
            self.assertEqual(result["binding_status"], "NOT_BOUND")
            self.assertFalse((root / ".p_ases").exists())

    def test_context_show_returns_existing_frozen_binding_without_resolving_a_new_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            digest = "a" * 64
            binding = ExecutionBinding("owner/repo", 32, 99, digest, "main", "b" * 40,
                                       str(root), "b" * 40)
            write_binding(execution_binding_path(root, 32), binding)
            github = SimpleNamespace(issue=lambda number: {"number": number, "state": "open"})
            with patch("p_ases.cli.GitHub", return_value=github), \
                 patch("p_ases.cli.verify_adc", return_value=self.verified_adc(digest)), \
                 patch("p_ases.cli.remote_branch_sha", side_effect=AssertionError("must not re-resolve base")):
                status, result = self.run_json(["context", "show", "32", "--root", str(root),
                                                "--repo", "owner/repo"])
            self.assertEqual(status, 0)
            self.assertEqual(result["status"], "BOUND")
            self.assertEqual(result["frozen_context"]["base_sha"], "b" * 40)
            self.assertEqual(result["frozen_context"]["base_ref"], "main")

    def test_context_show_marks_stale_adc_binding_closed_issue_and_missing_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binding = ExecutionBinding("owner/repo", 32, 99, "c" * 64, "main", "b" * 40,
                                       str(root), "b" * 40)
            write_binding(execution_binding_path(root, 32), binding)
            github = SimpleNamespace(issue=lambda number: {"number": number, "state": "open"})
            with patch("p_ases.cli.GitHub", return_value=github), \
                 patch("p_ases.cli.verify_adc", return_value=self.verified_adc("a" * 64)):
                status, result = self.run_json(["context", "show", "32", "--root", str(root),
                                                "--repo", "owner/repo"])
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "STALE_BINDING")

            closed = SimpleNamespace(issue=lambda number: {"number": number, "state": "closed"})
            with patch("p_ases.cli.GitHub", return_value=closed), \
                 patch("p_ases.cli.verify_adc", side_effect=AssertionError("closed Issue needs no ADC read")):
                status, result = self.run_json(["context", "show", "32", "--root", str(root),
                                                "--repo", "owner/repo"])
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "ISSUE_CLOSED")

            missing = SimpleNamespace(issue=lambda number: (_ for _ in ()).throw(GitHubError("not found")))
            with patch("p_ases.cli.GitHub", return_value=missing):
                status, result = self.run_json(["context", "show", "32", "--root", str(root),
                                                "--repo", "owner/repo"])
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "ISSUE_UNAVAILABLE")

    def test_context_show_unverified_adc_is_explicit_and_does_not_claim_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            github = SimpleNamespace(issue=lambda number: {"number": number, "state": "open"})
            with patch("p_ases.cli.GitHub", return_value=github), \
                 patch("p_ases.cli.verify_adc", side_effect=ADCError("pointer mismatch")):
                status, result = self.run_json(["context", "show", "32", "--root", str(root),
                                                "--repo", "owner/repo"])
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "ADC_UNAVAILABLE")
            self.assertEqual(result["binding_status"], "NOT_EVALUATED")
            self.assertFalse((root / ".p_ases").exists())


if __name__ == "__main__":
    unittest.main()
