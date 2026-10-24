from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.acceptance import AcceptanceObservation, AcceptanceResult, evaluate_acceptance
from p_ases.audits import AuditItem, IndependentReview, ReviewFinding, SelfAudit
from p_ases.checkpoint import PRBinding
from p_ases.context import WorkContext
from p_ases.delivery import PRReadback, ReadinessResult, evaluate_readiness, read_readiness, readiness_path, write_readiness
from p_ases.evidence_store import VerificationSubject
from p_ases.execution import ExecutionBinding, binding_digest
from p_ases.review_assurance import attest_native_review
from p_ases.verification import (
    GateResult, RequiredCheckPolicy, VerificationResult, evaluate_required_checks,
)


BASE = "a" * 40
HEAD = "b" * 40
ADC_SHA = "c" * 64
PLAN_SHA = "d" * 64


def setup(*, draft=False, fork=False, stale=False, unresolved=False):
    subject = VerificationSubject("octo/repo", 30, 55, 123, ADC_SHA, PLAN_SHA, "e" * 40)
    binding = ExecutionBinding(
        repository="octo/repo", issue_number=30, adc_comment_id=123, adc_sha256=ADC_SHA,
        base_ref="main", base_sha=BASE, work_directory=str(Path(tempfile.gettempdir()) / "pases-30"),
        branch_ref="pases/work-readiness", initial_head_sha=BASE,
    ).validate()
    context = WorkContext(binding, subject.pr_head_sha40, "pases/work-readiness", True,
                          binding_digest(binding)).validate()
    pr_binding = PRBinding("octo/repo", 30, 123, ADC_SHA, BASE, "pases/work-readiness", 55,
                           "f" * 40 if stale else subject.pr_head_sha40).validate()
    pr = PRReadback(
        repository="octo/repo", issue_number=30, pr_number=55, state="open", draft=draft,
        base_ref="main", base_sha40=BASE, head_ref="pases/work-readiness",
        head_sha40=subject.pr_head_sha40, head_repository="other/repo" if fork else "octo/repo",
        closing_issue_number=30,
    )
    policy = RequiredCheckPolicy((("required-ci", 789),))
    repository = {"url": "https://api.github.com/repos/octo/repo"}
    check = evaluate_required_checks(
        policy, ({
            "id": 1, "name": "required-ci", "head_sha": subject.pr_head_sha40,
            "status": "completed", "conclusion": "success", "app": {"id": 789},
            "pull_requests": [{
                "number": subject.pr_number,
                "base": {"repo": repository, "sha": BASE},
                "head": {"repo": repository, "sha": subject.pr_head_sha40},
            }],
        },), subject=subject, expected_repository="octo/repo", response_repository="octo/repo",
        head_sha40=subject.pr_head_sha40, is_fork=False,
    )
    pass_result = VerificationResult(
        "PASS", subject, (), policy.sha256, check.sha256, ("1" * 64,), (),
    ).validate()
    acceptance = evaluate_acceptance(
        artifact_type="feature_manual", subject=subject,
        required_req_ids=("REQ-08", "REQ-09"), mapped_req_ids=("REQ-08", "REQ-09"),
        verification=GateResult("PASS", (), subject), oracle_trace=GateResult("PASS", (), subject),
        observations=(AcceptanceObservation("manual_verification", subject, subject.pr_head_sha40,
                                            "PASS", "2" * 64, "manual.json"),),
        verification_result_sha256=pass_result.sha256,
    )
    audit = SelfAudit(subject, tuple(sorted((
        AuditItem("REQ-08", "PASS", ("checkpoint.json#sha256",)),
        AuditItem("REQ-09", "PASS", ("readiness.json#sha256",)),
        AuditItem("checklist:exact-head", "PASS", ("pr-readback.json#sha256",)),
    ), key=lambda row: row.item_id))).validate(("REQ-08", "REQ-09", "checklist:exact-head"))
    findings = (ReviewFinding("A-01", "A", False, "Blocking example", "review.md#A-01"),) if unresolved else ()
    review = IndependentReview(
        subject, "fresh-review-session", "implementation-session", "review-context.json",
        "2" * 64, findings, "CONCERNS" if unresolved else "PASS",
    ).validate()
    execution = "execution-binding:" + "e" * 64
    child_output = json.dumps({
        "findings": [{"description": row.description, "evidence_ref": row.evidence_ref,
                      "finding_id": row.finding_id, "resolved": row.resolved, "severity": row.severity}
                     for row in findings],
        "reviewer_context_id": "fresh-review-session", "schema": "PASES_CHILD_REVIEW_OUTPUT_V1",
        "subject": subject.as_dict(), "verdict": "CONCERNS" if unresolved else "PASS",
    }, sort_keys=True, separators=(",", ":")).encode()
    request = json.dumps({
        "execution_identity_context_id": execution, "operation": "spawn_independent_review_child",
        "reviewer_context_id": "fresh-review-session", "schema": "PASES_NATIVE_REVIEW_REQUEST_V1",
        "subject": subject.as_dict(),
    }, sort_keys=True, separators=(",", ":")).encode()
    terminal = json.dumps({
        "child_output_sha256": hashlib.sha256(child_output).hexdigest(), "completed": True,
        "request_sha256": hashlib.sha256(request).hexdigest(),
        "schema": "PASES_NATIVE_REVIEW_TERMINAL_V1", "status": "success",
    }, sort_keys=True, separators=(",", ":")).encode()
    review_v2 = attest_native_review(
        subject=subject, execution_identity_context_id=execution, profile_sha256="f" * 64,
        request=request, terminal_return=terminal, child_output=child_output,
    )
    return subject, context, pr_binding, pr, pass_result, check, acceptance, audit, review, review_v2


class WorkReadinessSchemaTests(unittest.TestCase):
    def test_operator_supplied_capture_cannot_make_readiness_pass(self):
        subject, context, pr_binding, pr, passed, check, acceptance, audit, review, review_v2 = setup()
        result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=review_v2.as_v1_readiness_projection(),
            independent_review_v2=review_v2,
            review_minimum_assurance="independent_attested", current_profile_sha256="f" * 64,
            execution_identity_context_id="execution-binding:" + "e" * 64,
            required_checks_sha256=check.sha256,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertFalse(result.ready_for_user_review)
        self.assertTrue(any("capture boundary" in reason for reason in result.reasons))
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(ReadinessResult.from_bytes(result.to_bytes()), result)
        with tempfile.TemporaryDirectory() as temporary:
            path = readiness_path(Path(temporary), result)
            self.assertEqual(write_readiness(path, result), result.sha256)
            self.assertEqual(read_readiness(path), result)

    def test_missing_stale_draft_fork_and_unresolved_review_block_readiness(self):
        subject, context, pr_binding, pr, passed, check, acceptance, audit, review, review_v2 = setup()
        args = dict(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=review_v2.as_v1_readiness_projection(),
            independent_review_v2=review_v2,
            review_minimum_assurance="independent_attested", current_profile_sha256="f" * 64,
            execution_identity_context_id="execution-binding:" + "e" * 64,
            required_checks_sha256=check.sha256,
        )
        self.assertEqual(evaluate_readiness(**{**args, "verification": None}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "pr": setup(draft=True)[3]}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "pr": setup(fork=True)[3]}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "pr_binding": setup(stale=True)[2]}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "independent_review": None,
                                               "independent_review_v2": None}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "independent_review_v2": setup(unresolved=True)[9]}).status, "CONCERNS")
        self.assertEqual(evaluate_readiness(**{**args, "independent_review_v2": None,
                                               "independent_review": review}).status, "BLOCKED")

    def test_unaccepted_dependency_is_an_explicit_readiness_blocker(self):
        subject, context, pr_binding, pr, passed, check, acceptance, audit, review, review_v2 = setup()
        result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=review_v2.as_v1_readiness_projection(),
            independent_review_v2=review_v2,
            review_minimum_assurance="independent_attested", current_profile_sha256="f" * 64,
            execution_identity_context_id="execution-binding:" + "e" * 64,
            required_checks_sha256=check.sha256,
            blocker_reasons=("WAITING_DEPENDENCY #28: formal Oracle has not been accepted",),
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("WAITING_DEPENDENCY #28", result.reasons[0])

    def test_independent_review_requires_a_distinct_context_and_no_unresolved_ab(self):
        subject, *_ = setup()
        same_context = IndependentReview(
            subject, "same", "same", "review.json", "3" * 64, (), "PASS",
        )
        with self.assertRaises(ValueError):
            same_context.validate()
        blocking = IndependentReview(
            subject, "review", "implementation", "review.json", "3" * 64,
            (ReviewFinding("B-1", "B", False, "Unresolved blocker", "review.json#B-1"),), "PASS",
        )
        with self.assertRaises(ValueError):
            blocking.validate()


if __name__ == "__main__":
    unittest.main()
