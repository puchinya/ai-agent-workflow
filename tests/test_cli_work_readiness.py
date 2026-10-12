from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.cli import _parser


class WorkReadinessCLITests(unittest.TestCase):
    def _help(self, *argv: str) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                _parser().parse_args(list(argv) + ["--help"])
        self.assertEqual(raised.exception.code, 0)
        return output.getvalue()

    def test_work_pr_audit_and_delivery_namespaces_are_exposed(self):
        self.assertIn("base,branch,bind,recover", self._help("work"))
        self.assertIn("ensure", self._help("pr"))
        self.assertIn("self,independent", self._help("audit"))
        self.assertIn("readiness", self._help("delivery"))

    def test_readiness_requires_evidence_paths_and_has_no_self_asserted_pass_flags(self):
        help_text = self._help("delivery", "readiness")
        for argument in ("verification", "acceptance", "self_audit", "independent_review"):
            self.assertIn(argument, help_text)
        self.assertNotIn("--passed", help_text)
        self.assertNotIn("--approved", help_text)


if __name__ == "__main__":
    unittest.main()
