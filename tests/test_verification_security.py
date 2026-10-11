from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.acceptance import AcceptanceObservation, AcceptanceResult, evaluate_acceptance
from p_ases.evidence_store import (
    EvidenceError, EvidenceRecord, VerificationSubject, evidence_path,
    read_evidence_set, write_evidence,
)
from p_ases.oracle_trace import (
    OracleDefinition, OracleTraceError, TestDefinition, validate_plan_oracles,
    validate_plan_tests,
)
from p_ases.verification import (
    GateResult, RequiredCheckPolicy, evaluate_required_checks,
)
from p_ases.verification_plan import PlanEntry, PlanError, create_plan, entry_ref, verify_plan_sources


ADC = "a" * 64
HEAD = "b" * 40
BASELINE = "c" * 40


def make_plan(root: Path | None = None):
    spec = b"REQ-01: Expected behavior is stable.\n"
    tests = b"REQ-01: Test the frozen external behavior.\n"
    oracle_bytes = b"The independently recorded behavior is stable.\n"
    rows = []
    if root is not None:
        for name, data in (("spec.md", spec), ("tests.md", tests), ("oracle.md", oracle_bytes)):
            (root / name).write_bytes(data)
    for kind, name, data in (("specification", "spec.md", spec),
                             ("test_specification", "tests.md", tests),
                             ("oracle", "oracle.md", oracle_bytes)):
        rows.append((kind, name, hashlib.sha256(data).hexdigest()))
    command = ("/usr/bin/python", "-m", "unittest")
    entry = PlanEntry(
        req_id="REQ-01", oracle_id="ORACLE-01", test_id="TEST-01", target="linux",
        environment="ubuntu-py314", command=command, risk="high",
        acceptance="assert the frozen behavior", evidence_required=("result", "acceptance_criteria"),
    ).validate()
    oracle = OracleDefinition(
        oracle_id="ORACLE-01", source_kind="frozen_specification", source_ref="oracle.md",
        source_sha256=hashlib.sha256(oracle_bytes).hexdigest(),
        expected_behavior="The independently recorded behavior is stable.", req_ids=("REQ-01",),
    ).validate()
    test = TestDefinition(
        test_id="TEST-01", req_id="REQ-01", target="linux", source_ref="tests.md",
        source_sha256=hashlib.sha256(tests).hexdigest(),
    ).validate()
    trace = {
        "oracles": [oracle.as_dict()], "schema": "PASES_VERIFICATION_TRACE_V1",
        "tests": [test.as_dict()],
    }
    trace_digest = hashlib.sha256(json.dumps(trace, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
    plan = create_plan(repository="owner/repo", issue_number=29, adc_comment_id=71,
                       adc_sha256=ADC, source_digests=tuple(rows), entries=(entry,),
                       required_req_ids=("REQ-01",), oracle_test_trace_sha256=trace_digest)
    return plan, entry, oracle, test


def make_subject(plan, *, head=HEAD):
    return VerificationSubject("owner/repo", 29, 83, 71, ADC, plan.sha256, head).validate()


def make_evidence(plan, *, kind="result", outcome="PASS", observed_at="2026-10-11T00:00:00Z"):
    entry = plan.entries[0]
    return EvidenceRecord(
        subject=make_subject(plan), entry_key=entry_ref(entry), evidence_type=kind,
        command=entry.command, manual_procedure="", environment=entry.environment,
        runner_source="local", observed_at=observed_at, outcome=outcome,
        exit_status=0 if outcome == "PASS" else 1, output_sha256="f" * 64,
    ).validate()


def check_run(identifier=1, *, status="completed", conclusion="success", app_id=789, head=HEAD):
    repository = {"url": "https://api.github.com/repos/owner/repo"}
    return {
        "id": identifier, "name": "required-ci", "head_sha": head,
        "status": status, "conclusion": conclusion, "app": {"id": app_id},
        "pull_requests": [{
            "number": 83,
            "base": {"repo": repository, "sha": "d" * 40},
            "head": {"repo": repository, "sha": head},
        }],
    }


class VerificationSecurityTests(unittest.TestCase):
    def test_frozen_sources_and_oracle_test_mappings_are_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, _entry, oracle, test = make_plan(root)
            self.assertEqual(verify_plan_sources(root, plan), plan.source_digests)
            validate_plan_oracles(plan, ("REQ-01",), {oracle.oracle_id: oracle})
            validate_plan_tests(plan, (test,), plan.source_digests)
            with self.assertRaises(OracleTraceError):
                validate_plan_tests(plan, (), plan.source_digests)
            with self.assertRaises(OracleTraceError):
                validate_plan_tests(plan, (test, test), plan.source_digests)
            with self.assertRaises(OracleTraceError):
                validate_plan_oracles(plan, ("REQ-01",), {
                    oracle.oracle_id: replace(oracle, derived_from_implementation=True),
                })
            (root / "spec.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(PlanError, "source changed"):
                verify_plan_sources(root, plan)

    def test_evidence_history_retry_is_idempotent_and_conflicts_fail_closed(self):
        plan, _entry, _oracle, _test = make_plan()
        record = make_evidence(plan)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = evidence_path(root, record)
            self.assertEqual(write_evidence(path, record), record.evidence_sha256)
            self.assertEqual(write_evidence(path, record), record.evidence_sha256)
            self.assertEqual(read_evidence_set(root, record.subject), (record,))
            with self.assertRaises(EvidenceError):
                write_evidence(path, replace(record, outcome="FAIL", exit_status=1))

    def test_evidence_readback_rejects_symlinked_ancestor(self):
        plan, _entry, _oracle, _test = make_plan()
        record = make_evidence(plan)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir()
            path = real / "evidence.json"
            write_evidence(path, record)
            link = root / "linked"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(EvidenceError):
                read_evidence_set(link, record.subject)

    def test_evidence_writer_rejects_a_symlinked_pases_root(self):
        plan, _entry, _oracle, _test = make_plan()
        record = make_evidence(plan)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "target"
            target.mkdir()
            workspace = base / "workspace"
            workspace.mkdir()
            (workspace / ".p_ases").symlink_to(target, target_is_directory=True)
            path = evidence_path(workspace / ".p_ases" / "evidence", record)
            with self.assertRaises(EvidenceError):
                write_evidence(path, record)

    def test_required_check_accepts_only_trusted_current_successful_check_run(self):
        plan, _entry, _oracle, _test = make_plan()
        subject = make_subject(plan)
        policy = RequiredCheckPolicy((("required-ci", 789),))
        for run in (
            check_run(app_id=790),
            check_run(head="e" * 40),
            check_run(status="completed", conclusion="skipped"),
            check_run(status="completed", conclusion="neutral"),
            check_run(status="in_progress", conclusion=None),
        ):
            result = evaluate_required_checks(
                policy, (run,), subject=subject, expected_repository="owner/repo",
                response_repository="owner/repo", head_sha40=HEAD, is_fork=False,
            )
            self.assertEqual(result.status, "BLOCKED")
        latest_failed = evaluate_required_checks(
            policy, (check_run(), check_run(2, conclusion="failure")), subject=subject,
            expected_repository="owner/repo", response_repository="owner/repo",
            head_sha40=HEAD, is_fork=False,
        )
        self.assertEqual(latest_failed.status, "BLOCKED")
        self.assertEqual(evaluate_required_checks(
            RequiredCheckPolicy(()), (check_run(),), subject=subject,
            expected_repository="owner/repo", response_repository="owner/repo",
            head_sha40=HEAD, is_fork=False,
        ).status, "BLOCKED")

    def test_acceptance_bug_fix_requires_independent_red_before_and_green_after(self):
        plan, _entry, _oracle, _test = make_plan()
        subject = make_subject(plan)
        verification = GateResult("PASS", (), subject)
        oracle = GateResult("PASS", (), subject)
        red = AcceptanceObservation("red_before", subject, BASELINE, "FAIL", "1" * 64, "before.json")
        green = AcceptanceObservation("green_after", subject, HEAD, "PASS", "2" * 64, "after.json")
        result = evaluate_acceptance(
            artifact_type="bug_fix", subject=subject, required_req_ids=("REQ-01",),
            mapped_req_ids=("REQ-01",), verification=verification, oracle_trace=oracle,
            observations=(red, green), baseline_sha40=BASELINE,
            verification_result_sha256="9" * 64,
        )
        self.assertEqual(result.status, "PASS")
        self.assertEqual(AcceptanceResult.from_bytes(result.to_bytes()), result)
        self.assertEqual(evaluate_acceptance(
            artifact_type="bug_fix", subject=subject, required_req_ids=("REQ-01",),
            mapped_req_ids=("REQ-01",), verification=verification, oracle_trace=oracle,
            observations=(green,), baseline_sha40=BASELINE,
        ).status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
