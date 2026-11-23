"""Issue #79: regression tests for nonblocking optional independent-review findings."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.audits import AuditError, IndependentReviewV3, ReviewFinding, ReviewFindingV3


class OptionalReviewFindingTests(unittest.TestCase):
    def test_v3_d_is_valid_and_never_blocks(self):
        optional = ReviewFindingV3(
            "F-1", "D", False, "Unreachable optional cleanup",
            "diff:path.py:20 (not used by the approved ADC)", False,
        ).validate()
        self.assertEqual(optional.severity, "D")
        # Blocking classification is computed from the same raw findings.
        review = IndependentReviewV3(
            None, "child", "writer", "context", "a" * 64,
            (), (optional,), "PASS", "LIMITED", None, None, None,
        )
        self.assertEqual(review.blocking_findings, ())

    def test_v3_d_cannot_claim_readiness_blocker(self):
        with self.assertRaisesRegex(AuditError, "Only a reviewer-designated C"):
            ReviewFindingV3(
                "F-2", "D", False, "Optional refactor", "diff:path.py:30", True
            ).validate()

    def test_historical_v2_review_finding_still_rejects_d(self):
        with self.assertRaisesRegex(AuditError, "A, B, or C"):
            ReviewFinding("F-3", "D", False, "historical optional", "diff:path.py:40").validate()

    def test_v3_a_and_b_still_block(self):
        findings = (
            ReviewFindingV3("F-1", "A", False, "ADC violation", "REQ-F79-004", False),
            ReviewFindingV3("F-2", "B", False, "Material ambiguity", "ADC architecture", False),
            ReviewFindingV3("F-3", "C", False, "Follow-up", "test:unknown", False),
            ReviewFindingV3("F-4", "D", False, "Optional cleanup", "diff:dead.py", False),
        )
        review = IndependentReviewV3(
            None, "child", "writer", "context", "a" * 64,
            (), findings, "FAIL", "LIMITED", None, None, None,
        )
        self.assertEqual(tuple(f.finding_id for f in review.blocking_findings), ("F-1", "F-2"))


if __name__ == "__main__":
    unittest.main()
