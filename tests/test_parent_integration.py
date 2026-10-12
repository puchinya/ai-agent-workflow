from __future__ import annotations

from dataclasses import replace
import sys
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.integration import (
    IntegrationError, IntegrationGateEvidence, evaluate_parent_integration,
)
from p_ases.cli import _load_parent_gate_evidence_from_github

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
            "merged_at": f"2026-10-12T00:{number - 27:02d}:00Z",
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
        merged_pr_rows=prs,
        merge_sha_ancestry={f"{number:040x}": True for number in EXPECTED},
        integration_verification=IntegrationGateEvidence(
            "verification", "octo/repo", 26, "b" * 64, MAIN, "PASS", "c" * 64, "parent-verification.json"),
        integration_acceptance=IntegrationGateEvidence(
            "acceptance", "octo/repo", 26, "b" * 64, MAIN, "PASS", "d" * 64, "parent-acceptance.json"),
    )


class ParentIntegrationTests(unittest.TestCase):
    def test_u07_six_closed_merged_children_and_exact_evidence_can_pass(self):
        result = evaluate_parent_integration(**integration_fixture())
        self.assertEqual(result.status, "PASS")
        self.assertEqual(tuple(row.issue_number for row in result.subject.children), EXPECTED)
        self.assertEqual(result.subject.expected_child_issue_numbers, EXPECTED)
        self.assertEqual(tuple(number for number, _dependencies in result.subject.declared_dependency_graph), EXPECTED)
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
            ("integration_verification", None),
            ("integration_acceptance", None),
            ("integration_verification", IntegrationGateEvidence(
                "verification", "octo/repo", 26, "b" * 64, MAIN, "FAIL", "c" * 64, "bad.json")),
            ("integration_acceptance", IntegrationGateEvidence(
                "acceptance", "octo/repo", 26, "b" * 64, "f" * 40, "PASS", "d" * 64, "stale.json")),
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

    def test_child_merge_timestamps_must_follow_the_declared_dependencies(self):
        kwargs = integration_fixture()
        kwargs["merged_pr_rows"][0]["merged_at"] = "2026-10-12T00:05:00Z"
        result = evaluate_parent_integration(**kwargs)
        self.assertEqual(result.status, "BLOCKED")
        self.assertTrue(any("merged before dependency" in reason for reason in result.reasons))

    def test_parent_closing_reference_is_rejected(self):
        kwargs = integration_fixture()
        kwargs["merged_pr_rows"][0]["body"] += "\nCloses #26\n"
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_merge_commit_must_be_confirmed_in_current_main(self):
        kwargs = integration_fixture()
        kwargs["merge_sha_ancestry"].pop(f"{27:040x}")
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")
        kwargs = integration_fixture()
        kwargs["merge_sha_ancestry"][f"{27:040x}"] = False
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_parent_pass_record_cannot_claim_a_stale_child_merge(self):
        result = evaluate_parent_integration(**integration_fixture())
        children = (replace(result.subject.children[0], merge_sha_in_main=False), *result.subject.children[1:])
        invalid = replace(result, subject=replace(result.subject, children=children))
        with self.assertRaisesRegex(IntegrationError, "PASS lacks the exact child"):
            invalid.validate()

    def test_typed_parent_gate_evidence_round_trips_exact_subject(self):
        kwargs = integration_fixture()
        evidence = kwargs["integration_verification"]
        self.assertEqual(IntegrationGateEvidence.from_dict(__import__("json").loads(evidence.to_bytes())), evidence)
        stale = IntegrationGateEvidence.from_dict(__import__("json").loads(evidence.to_bytes()))
        self.assertNotEqual(stale.main_sha40, "f" * 40)

    def test_parent_gate_evidence_is_read_from_exact_main_api_content(self):
        class ContentGitHub:
            def __init__(self, files):
                self.files = files
                self.calls = []

            def content_at_ref(self, path, ref):
                self.calls.append((path, ref))
                if ref != MAIN or path not in self.files:
                    raise RuntimeError("missing exact-main content")
                return self.files[path]

        check_ids = ("compileall", "unit-tests", "docs-validation", "format-check", "required-ci")
        files = {}
        checks = []
        for check_id in check_ids:
            reference = f"evidence/{check_id}.txt"
            content = f"main {check_id}\n".encode()
            files[reference] = content
            checks.append({"check_id": check_id, "status": "PASS",
                           "evidence_sha256": hashlib.sha256(content).hexdigest(),
                           "evidence_reference": reference})
        source = {"schema": "PASES_PARENT_INTEGRATION_CHECKS_V1", "kind": "verification",
                  "status": "PASS", "repository": "octo/repo", "parent_issue_number": 26,
                  "parent_adc_sha256": "b" * 64, "main_sha40": MAIN, "checks": checks}
        source_bytes = json.dumps(source, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        files["reports/verification.json"] = source_bytes
        evidence = IntegrationGateEvidence("verification", "octo/repo", 26, "b" * 64, MAIN,
                                           "PASS", hashlib.sha256(source_bytes).hexdigest(),
                                           "reports/verification.json")
        files["records/verification.json"] = evidence.to_bytes()
        github = ContentGitHub(files)
        self.assertEqual(_load_parent_gate_evidence_from_github(
            github, Path("records/verification.json"), MAIN, "verification"), evidence)
        self.assertTrue(github.calls)
        self.assertEqual({ref for _path, ref in github.calls}, {MAIN})
        self.assertIn(("records/verification.json", MAIN), github.calls)
        files["evidence/required-ci.txt"] = b"different bytes\n"
        with self.assertRaisesRegex(IntegrationError, "exact-main bytes"):
            _load_parent_gate_evidence_from_github(
                github, Path("records/verification.json"), MAIN, "verification")
        with self.assertRaisesRegex(IntegrationError, "repository-relative"):
            _load_parent_gate_evidence_from_github(
                github, Path("../records/verification.json"), MAIN, "verification")
        incomplete_source = {**source, "checks": checks[:-1]}
        incomplete_bytes = json.dumps(incomplete_source, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        files["reports/verification.json"] = incomplete_bytes
        incomplete_evidence = IntegrationGateEvidence(
            "verification", "octo/repo", 26, "b" * 64, MAIN, "PASS",
            hashlib.sha256(incomplete_bytes).hexdigest(), "reports/verification.json")
        files["records/verification.json"] = incomplete_evidence.to_bytes()
        with self.assertRaisesRegex(IntegrationError, "fixed required check set"):
            _load_parent_gate_evidence_from_github(
                github, Path("records/verification.json"), MAIN, "verification")

    def test_frozen_child_set_cannot_be_empty_or_duplicate(self):
        kwargs = integration_fixture()
        kwargs["expected_child_issue_numbers"] = (27, 27)
        with self.assertRaises(IntegrationError):
            evaluate_parent_integration(**kwargs)


if __name__ == "__main__":
    unittest.main()
