from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.document_format import format_tree
from p_ases.documents import validate_documents


class DocumentValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "evidence.py").write_text("# executable evidence source\n", encoding="utf-8")
        (self.repo / "docs" / "specs").mkdir(parents=True)
        (self.repo / "docs" / "design").mkdir()
        (self.repo / "docs" / "testing").mkdir()
        (self.repo / "docs" / "specs" / "demo.md").write_text(
            """<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Demo specification

## Purpose
## Scope
## Normative requirements
<a id="req-demo-001"></a>
### REQ-DEMO-001 Stable behavior
## Observable behavior
## Error and boundary behavior
## Security and privacy
""",
            encoding="utf-8",
        )
        (self.repo / "docs" / "design" / "demo.md").write_text(
            """<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# Demo design

## Context and goals
## Requirements traceability
<a id="des-demo-001"></a>
### DES-DEMO-001 Ownership decision
## Architecture
## Data flow and ownership
## Failure handling
## Alternatives considered
""",
            encoding="utf-8",
        )
        (self.repo / "docs" / "testing" / "demo.md").write_text(
            """<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# Demo tests

## Test purpose
## Test conditions and oracles
<a id="tst-demo-001"></a>
### TST-DEMO-001 Input boundary
Given an input at the documented boundary, exercise the public command.
<a id="ora-demo-001"></a>
#### ORA-DEMO-001 Independent expected result
The command returns a nonzero result before any external mutation.
""",
            encoding="utf-8",
        )
        (self.repo / "docs" / "testing" / "traceability.md").write_text(
            """<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# Traceability matrix

## Test purpose
## Test conditions and oracles

| REQ | DES | Oracle | Test | Evidence |
|---|---|---|---|---|
| [REQ-DEMO-001](../specs/demo.md#req-demo-001) | [DES-DEMO-001](../design/demo.md#des-demo-001) | [ORA-DEMO-001](demo.md#ora-demo-001) | [TST-DEMO-001](demo.md#tst-demo-001) | [test source](../../tests/evidence.py) |
""",
            encoding="utf-8",
        )
        format_tree(self.repo, write=True)

    def test_complete_req_design_oracle_test_evidence_graph_passes(self):
        self.assertEqual(validate_documents(self.repo), [])

    def test_product_spec_does_not_require_verification_strategy(self):
        text = (self.repo / "docs" / "specs" / "demo.md").read_text(encoding="utf-8")
        self.assertNotIn("Verification Strategy", text)
        self.assertEqual(validate_documents(self.repo), [])

    def test_missing_traceability_edge_is_reported(self):
        matrix = self.repo / "docs" / "testing" / "traceability.md"
        text = matrix.read_text(encoding="utf-8").replace(
            "[DES-DEMO-001](../design/demo.md#des-demo-001)", "DES-DEMO-001", 1
        )
        matrix.write_text(text, encoding="utf-8")
        errors = validate_documents(self.repo)
        self.assertTrue(any("exactly one linked DES ID" in error for error in errors), errors)

    def test_duplicate_stable_id_is_reported(self):
        design = self.repo / "docs" / "design" / "demo.md"
        text = design.read_text(encoding="utf-8") + (
            "\n<a id=\"des-demo-001\"></a>\n### DES-DEMO-001 Duplicate\n"
        )
        design.write_text(text, encoding="utf-8")
        errors = validate_documents(self.repo)
        self.assertTrue(any("duplicate stable ID definition DES-DEMO-001" in error for error in errors), errors)

    def test_missing_local_fragment_is_reported(self):
        matrix = self.repo / "docs" / "testing" / "traceability.md"
        text = matrix.read_text(encoding="utf-8").replace("#req-demo-001", "#missing", 1)
        matrix.write_text(text, encoding="utf-8")
        errors = validate_documents(self.repo)
        self.assertTrue(any("missing link fragment" in error for error in errors), errors)

    def test_stable_anchor_inside_fenced_example_is_not_a_definition(self):
        spec = self.repo / "docs" / "specs" / "demo.md"
        text = spec.read_text(encoding="utf-8").replace(
            '<a id="req-demo-001"></a>',
            '```html\n<a id="req-demo-001"></a>\n```',
            1,
        )
        spec.write_text(text, encoding="utf-8")
        errors = validate_documents(self.repo)
        self.assertTrue(any("stable ID REQ-DEMO-001 needs a manual anchor" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
