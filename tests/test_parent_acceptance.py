from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_dist import EXPECTED_SKILLS  # noqa: E402
from validate_parent_acceptance import PARENT_CANONICAL_SKILLS, validate_skill_package  # noqa: E402
from validate_pases_traceability import validate  # noqa: E402


class ParentAcceptanceTests(unittest.TestCase):
    def test_repository_spec_design_and_test_oracle_traceability_are_complete(self):
        for scope in ("specification", "design", "test-oracle"):
            with self.subTest(scope=scope):
                self.assertEqual(validate(ROOT, scope), ())

    def test_traceability_blocks_an_unmapped_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("docs/specs", "docs/design", "docs/testing", "tests"):
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / "docs/specs/spec.md").write_text('<a id="req-wf-001"></a>\n', encoding="utf-8")
            (root / "docs/design/design.md").write_text('<a id="des-wf-001"></a>\n', encoding="utf-8")
            (root / "docs/testing/oracle.md").write_text(
                '<a id="ora-wf-001"></a>\n<a id="tst-wf-001"></a>\n', encoding="utf-8")
            (root / "tests/test_oracle.py").write_text("pass\n", encoding="utf-8")
            matrix = root / "docs/testing/traceability.md"
            matrix.write_text(
                "| REQ | DES | Oracle | Test | Evidence |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| [REQ-WF-001](../specs/spec.md#req-wf-001) | "
                "[DES-WF-001](../design/design.md#des-wf-001) | "
                "[ORA-WF-001](oracle.md#ora-wf-001) | "
                "[TST-WF-001](oracle.md#tst-wf-001) | [test source](../../tests/test_oracle.py) |\n",
                encoding="utf-8")
            self.assertEqual(validate(root, "test-oracle"), ())
            matrix.write_text(matrix.read_text(encoding="utf-8").replace(
                "[ORA-WF-001](oracle.md#ora-wf-001) | [TST-WF-001](oracle.md#tst-wf-001)",
                "[ORA-WF-001](oracle.md#ora-wf-001) | [TST-WF-002](oracle.md#tst-wf-001)"), encoding="utf-8")
            self.assertTrue(any("omits TST IDs" in reason for reason in validate(root, "test-oracle")))

    def test_sixteen_skill_gate_matches_the_pinned_canonical_set(self):
        self.assertEqual(tuple(EXPECTED_SKILLS), PARENT_CANONICAL_SKILLS)
        self.assertEqual(validate_skill_package(ROOT), ())


if __name__ == "__main__":
    unittest.main()
