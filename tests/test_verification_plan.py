from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.acceptance import AcceptanceObservation, evaluate_acceptance
from p_ases.evidence_store import EvidenceError, EvidenceRecord, VerificationSubject, read_evidence, write_evidence
from p_ases.oracle_trace import OracleDefinition, OracleTraceError, trace_requirements, validate_plan_oracles
from p_ases.verification import (
    GateResult, RequiredCheckPolicy, VerificationError, evaluate_evidence,
    evaluate_required_checks, verify_final,
)
from p_ases.verification_plan import (
    PlanEntry, PlanError, VerificationPlan, create_plan, entry_ref, read_plan,
    validate_plan_coverage,
)


ADC_SHA = "a" * 64
HEAD = "b" * 40
PLAN_INPUTS = (
    ("specification", "spec.md", "c" * 64),
    ("test_specification", "test.md", "d" * 64),
    ("oracle", "oracle.md", "e" * 64),
)


def entry(req="REQ-01", *, evidence=("result",), target="linux"):
    return PlanEntry(
        req_id=req, oracle_id="ORACLE-core", test_id="TEST-core", target=target,
        environment="ubuntu-py314", command=("/usr/bin/python", "-m", "unittest"),
        risk="high", acceptance="assert the independently specified invariant",
        evidence_required=evidence,
    )


def plan(entries=None):
    return create_plan(
        repository="octo/repo", issue_number=29, adc_comment_id=123,
        adc_sha256=ADC_SHA, source_digests=PLAN_INPUTS,
        entries=entries if entries is not None else (entry(),), required_req_ids=("REQ-01",),
    )


def oracle(*, derived=False, reqs=("REQ-01",)):
    return OracleDefinition(
        oracle_id="ORACLE-core", source_kind="frozen_specification", source_ref="docs/specs/core.md",
        source_sha256="e" * 64, expected_behavior="preserve the exact pointer predecessor",
        req_ids=reqs, derived_from_implementation=derived,
    )


def subject(p=None, *, head=HEAD):
    current = p or plan()
    return VerificationSubject("octo/repo", 29, 54, 123, ADC_SHA, current.sha256, head).validate()


def evidence(p=None, *, outcome="PASS", evidence_type="result", head=HEAD, observed_at="2026-10-11T00:00:00Z"):
    current = p or plan()
    current_subject = subject(current, head=head)
    row = current.entries[0]
    return EvidenceRecord(
        subject=current_subject, entry_key=entry_ref(row), evidence_type=evidence_type,
        command=row.command, manual_procedure="", environment=row.environment,
        runner_source="local", observed_at=observed_at, outcome=outcome,
        exit_status=0 if outcome == "PASS" else 1, output_sha256="f" * 64,
    ).validate()


class VerificationPlanTests(unittest.TestCase):
    def test_plan_has_stable_digest_and_round_trips_canonical_bytes(self):
        first = plan()
        second = plan(tuple(reversed(first.entries)))
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(read_plan(first.to_bytes()), first)

    def test_plan_rejects_empty_missing_or_unexpected_requirement_coverage(self):
        with self.assertRaises(PlanError):
            create_plan(repository="octo/repo", issue_number=29, adc_comment_id=123,
                        adc_sha256=ADC_SHA, source_digests=PLAN_INPUTS, entries=(),
                        required_req_ids=("REQ-01",))
        with self.assertRaises(PlanError):
            validate_plan_coverage(plan(), ("REQ-01", "REQ-02"))
        extra = entry("REQ-02", target="macos")
        with self.assertRaises(PlanError):
            create_plan(repository="octo/repo", issue_number=29, adc_comment_id=123,
                        adc_sha256=ADC_SHA, source_digests=PLAN_INPUTS,
                        entries=(entry(), extra), required_req_ids=("REQ-01",))

    def test_plan_requires_explicit_absolute_command_or_named_manual_procedure(self):
        with self.assertRaises(PlanError):
            replace(entry(), command=("python", "-m", "unittest")).validate()
        manual = replace(entry(), command=(), manual_procedure="Inspect the rendered artifact and record the observed state.")
        self.assertIs(manual.validate(), manual)
        with self.assertRaises(PlanError):
            replace(manual, manual_procedure="").validate()

    def test_plan_reader_rejects_digest_and_noncanonical_tampering(self):
        encoded = plan().to_bytes()
        with self.assertRaises(PlanError):
            read_plan(encoded.replace(b"REQ-01", b"REQ-02", 1))
        with self.assertRaises(PlanError):
            read_plan(encoded.rstrip(b"\n"))

    def test_oracle_trace_requires_independent_defined_oracles_and_exact_coverage(self):
        self.assertEqual(trace_requirements(("REQ-01",), (entry(),), {"ORACLE-core": oracle()}).status, "PASS")
        with self.assertRaises(OracleTraceError):
            trace_requirements(("REQ-01",), (entry(),), {})
        with self.assertRaises(OracleTraceError):
            trace_requirements(("REQ-01",), (entry(),), {"ORACLE-core": oracle(derived=True)})
        with self.assertRaises(OracleTraceError):
            trace_requirements(("REQ-01", "REQ-02"), (entry(),), {"ORACLE-core": oracle()})
        with self.assertRaises(OracleTraceError):
            validate_plan_oracles(plan(), ("REQ-01",), {"ORACLE-core": replace(oracle(), source_sha256="9" * 64)})

    def test_evidence_is_immutable_idempotent_and_exact_subject_bound(self):
        p = plan()
        item = evidence(p)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            self.assertEqual(write_evidence(path, item), item.evidence_sha256)
            self.assertEqual(write_evidence(path, item), item.evidence_sha256)
            self.assertEqual(read_evidence(path), item)
            with self.assertRaises(EvidenceError):
                write_evidence(path, replace(item, outcome="FAIL", exit_status=1))

    def test_evidence_store_rejects_symlink(self):
        p = plan()
        item = evidence(p)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            target.write_bytes(item.to_bytes())
            link = Path(directory) / "link.json"
            link.symlink_to(target)
            with self.assertRaises(EvidenceError):
                read_evidence(link)

    def test_evidence_evaluation_preserves_fail_skip_flaky_and_stale(self):
        p = plan()
        current_subject = subject(p)
        self.assertEqual(evaluate_evidence(p, current_subject, (evidence(p),)).status, "PASS")
        self.assertEqual(evaluate_evidence(p, current_subject, (evidence(p, outcome="FAIL"),)).status, "FAIL")
        self.assertEqual(evaluate_evidence(p, current_subject, (evidence(p, outcome="SKIPPED"),)).status, "BLOCKED")
        self.assertEqual(evaluate_evidence(p, current_subject, (evidence(p, outcome="FLAKY"),)).status, "CONCERNS")
        stale = evidence(p, head="c" * 40)
        self.assertEqual(evaluate_evidence(p, current_subject, (stale,)).status, "BLOCKED")
        self.assertEqual(evaluate_evidence(p, current_subject, ()).status, "BLOCKED")

    def test_latest_required_check_rerun_wins_and_app_head_are_bound(self):
        p = plan()
        current = subject(p)
        policy = RequiredCheckPolicy((("test (ubuntu, 3.14)", 789),))
        run = {"id": 1, "name": policy.checks[0][0], "head_sha": HEAD, "status": "completed",
               "conclusion": "success", "app": {"id": 789}}
        passed = evaluate_required_checks(policy, (run,), subject=current, expected_repository="octo/repo",
                                          response_repository="octo/repo", head_sha40=HEAD, is_fork=False)
        self.assertEqual(passed.status, "PASS")
        failed_rerun = dict(run, id=2, conclusion="skipped")
        rejected = evaluate_required_checks(policy, (run, failed_rerun), subject=current, expected_repository="octo/repo",
                                           response_repository="octo/repo", head_sha40=HEAD, is_fork=False)
        self.assertEqual(rejected.status, "BLOCKED")
        wrong_app = dict(run, app={"id": 999})
        rejected = evaluate_required_checks(policy, (wrong_app,), subject=current, expected_repository="octo/repo",
                                           response_repository="octo/repo", head_sha40=HEAD, is_fork=False)
        self.assertEqual(rejected.status, "BLOCKED")
        stale = evaluate_required_checks(policy, (run,), subject=current, expected_repository="octo/repo",
                                         response_repository="octo/repo", head_sha40="c" * 40, is_fork=False)
        self.assertEqual(stale.status, "BLOCKED")
        empty = evaluate_required_checks(RequiredCheckPolicy(()), (run,), subject=current, expected_repository="octo/repo",
                                         response_repository="octo/repo", head_sha40=HEAD, is_fork=False)
        self.assertEqual(empty.status, "BLOCKED")

    def test_final_verification_requires_checks_for_same_exact_subject(self):
        p = plan()
        current = subject(p)
        passing = GateResult("PASS", (), current)
        self.assertEqual(verify_final(p, current, (evidence(p),), passing).status, "PASS")
        self.assertEqual(verify_final(p, current, (evidence(p),), GateResult("PASS", ())).status, "BLOCKED")

    def test_artifact_acceptance_requires_its_specific_independent_observations(self):
        p = plan()
        current = subject(p)
        passing = GateResult("PASS", (), current)
        criteria = AcceptanceObservation(
            "acceptance_criteria", current, HEAD, "PASS", "1" * 64, "acceptance.md#REQ-01",
        )
        spec = evaluate_acceptance(
            artifact_type="spec_change", subject=current, required_req_ids=("REQ-01",),
            mapped_req_ids=("REQ-01",), verification=passing, oracle_trace=passing,
            observations=(criteria,),
        )
        self.assertEqual(spec.status, "PASS")
        docs = evaluate_acceptance(
            artifact_type="documentation_only", subject=current, required_req_ids=("REQ-01",),
            mapped_req_ids=("REQ-01",), verification=passing, oracle_trace=passing,
            observations=(criteria,),
        )
        self.assertEqual(docs.status, "BLOCKED")
        red = AcceptanceObservation("red_before", current, "c" * 40, "FAIL", "2" * 64, "before.json")
        green = AcceptanceObservation("green_after", current, HEAD, "PASS", "3" * 64, "after.json")
        bug = evaluate_acceptance(
            artifact_type="bug_fix", subject=current, required_req_ids=("REQ-01",),
            mapped_req_ids=("REQ-01",), verification=passing, oracle_trace=passing,
            observations=(red, green), baseline_sha40="c" * 40,
        )
        self.assertEqual(bug.status, "PASS")
        no_red = evaluate_acceptance(
            artifact_type="bug_fix", subject=current, required_req_ids=("REQ-01",),
            mapped_req_ids=("REQ-01",), verification=passing, oracle_trace=passing,
            observations=(green,), baseline_sha40="c" * 40,
        )
        self.assertEqual(no_red.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
