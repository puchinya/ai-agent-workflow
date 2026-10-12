from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.cli import _parser, main


class DocsCLITests(unittest.TestCase):
    def test_help_exposes_validate_and_format_modes(self):
        help_text = _parser().format_help()
        self.assertIn("docs", help_text)
        format_parser = _parser()._subparsers._group_actions[0].choices["docs"]._subparsers._group_actions[0].choices["format"]
        self.assertIn("--write", format_parser.format_help())
        self.assertIn("--check", format_parser.format_help())

    def test_check_reports_drift_without_writing_then_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            doc = repo / "docs" / "specs" / "sample.md"
            doc.parent.mkdir(parents=True)
            original = "# Sample\n\n## Heading\n"
            doc.write_text(original, encoding="utf-8")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["docs", "format", "--check", "--root", str(repo)])
            self.assertEqual(status, 2)
            self.assertEqual(doc.read_text(encoding="utf-8"), original)
            self.assertEqual(json.loads(output.getvalue())["status"], "DRIFT")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["docs", "format", "--write", "--root", str(repo)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["changed_paths"], ["docs/specs/sample.md"])
            self.assertIn("## 1 Heading", doc.read_text(encoding="utf-8"))

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["docs", "format", "--check", "--root", str(repo)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "CLEAN")

    def test_validate_returns_machine_readable_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "docs").mkdir()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["docs", "validate", "--root", str(repo)])
            self.assertEqual(status, 2)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "INVALID")
            self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
