from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.integration import (
    IntegrationError, evaluate_parent_integration,
)

EXPECTED = (27, 28, 29, 30, 31, 32)
DAG = {
    27: (),
    28: (27,),
    29: (27, 28),
    30: (27, 29),
    31: (29, 30),
    32: (27, 28, 29, 30, 31),
}
PR_NUMBER = {27: 33, 28: 36, 29: 34, 30: 35, 31: 37, 32: 38}
MAIN = "a" * 40


def integration_fixture():
    native = [{"id": 100 + number, "number": number} for number in EXPECTED]
    issues = [{"id": 100 + number, "number": number, "state": "closed"} for number in EXPECTED]
    blockers = {number: tuple(100 + dependency for dependency in DAG[number]) for number in EXPECTED}
    prs = []
    for number in EXPECTED:
        repository = {"full_name": "octo/repo"}
        prs.append({
            "number": PR_NUMBER[number], "state": "closed",
            "merged_at": "2026-10-12T00:00:00Z",
            "merge_commit_sha": f"{number:040x}",
            "body": f"Implementation details\n\nCloses #{number}\n",
            "base": {"repo": repository, "ref": "main", "sha": MAIN},
            "head": {"repo": repository, "ref": f"pases/issue-{number}", "sha": f"{number + 100:040x}"},
        })
    return dict(
        repository="octo/repo", parent_issue_number=26,
        parent_adc_sha256="b" * 64, main_sha40=MAIN,
        expected_child_issue_numbers=EXPECTED,
        native_sub_issues=native, child_issue_rows=issues,
        actual_blockers_by_issue=blockers, declared_dependencies=DAG,
        merged_pr_rows=prs, integration_verification_sha256="c" * 64,
        integration_acceptance_sha256="d" * 64,
        integration_verification_pass=True, integration_acceptance_pass=True,
    )


class ParentIntegrationTests(unittest.TestCase):
    def test_u07_six_closed_merged_children_and_exact_evidence_can_pass(self):
        result = evaluate_parent_integration(**integration_fixture())
        self.assertEqual(result.status, "PASS")
        self.assertEqual(tuple(row.issue_number for row in result.subject.children), EXPECTED)
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(len({child.merge_sha40 for child in result.subject.children}), 6)

    def test_u07_unmerged_or_open_child_blocks_without_guessing_provenance(self):
        for target in ("issue", "pr", "merge"):
            with self.subTest(target=target):
                kwargs = integration_fixture()
                if target == "issue":
                    kwargs["child_issue_rows"][-1]["state"] = "open"
                elif target == "pr":
                    kwargs["merged_pr_rows"][-1]["merged_at"] = None
                else:
                    kwargs["merged_pr_rows"][-1]["merge_commit_sha"] = "bad"
                self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_u07_unaccepted_or_missing_integration_evidence_blocks(self):
        for name, value in (
            ("integration_verification_pass", False),
            ("integration_acceptance_pass", False),
            ("integration_verification_sha256", None),
            ("integration_acceptance_sha256", None),
        ):
            kwargs = integration_fixture()
            kwargs[name] = value
            self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_native_children_duplicates_and_missing_records_block(self):
        cases = (
            lambda a: a["native_sub_issues"].pop(),
            lambda a: a["native_sub_issues"].append(dict(a["native_sub_issues"][0])),
            lambda a: a["child_issue_rows"].pop(),
            lambda a: a["merged_pr_rows"].pop(),
            lambda a: a["merged_pr_rows"].append(dict(a["merged_pr_rows"][0])),
        )
        for mutate in cases:
            kwargs = integration_fixture()
            mutate(kwargs)
            self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_dependency_cycle_and_incomplete_graph_block(self):
        kwargs = integration_fixture()
        kwargs["declared_dependencies"] = {**DAG, 27: (32,)}
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")
        kwargs = integration_fixture()
        kwargs["actual_blockers_by_issue"][31] = (999,)
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_parent_closing_reference_is_rejected(self):
        kwargs = integration_fixture()
        kwargs["merged_pr_rows"][0]["body"] += "\nCloses #26\n"
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_frozen_child_set_cannot_be_empty_or_duplicate(self):
        kwargs = integration_fixture()
        kwargs["expected_child_issue_numbers"] = (27, 27)
        with self.assertRaises(IntegrationError):
            evaluate_parent_integration(**kwargs)


if __name__ == "__main__":
    unittest.main()
