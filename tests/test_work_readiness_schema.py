from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.acceptance import AcceptanceObservation, AcceptanceResult, evaluate_acceptance
from p_ases.audits import (
    AuditItem, IndependentReview, IndependentReviewV2, IndependentReviewV3, ReviewFinding,
    ReviewFindingV3, ReviewUnitResult, SelfAudit,
)
from p_ases.checkpoint import PRBinding
from p_ases.context import WorkContext
from p_ases.current_base import CurrentBaseAdvanceEvidence
from p_ases.delivery import (
    PRReadback, ReadinessResult, _identity_adc_matches_subject, evaluate_readiness,
    read_readiness, readiness_path, write_readiness,
)
from p_ases.evidence_store import VerificationSubject
from p_ases.execution import AdoptedExecutionEpoch, ExecutionBinding, binding_digest
from p_ases.execution_adoption import adoption_path, attachment_path as adoption_attachment_path
from p_ases.current_epoch import ActiveExecutionEpoch
from p_ases.cli import CLIError, _identity_evidence_paths
from p_ases.work import execution_binding_path
from p_ases.verification import (
    GateResult, RequiredCheckPolicy, VerificationResult, evaluate_required_checks,
)


BASE = "a" * 40
HEAD = "b" * 40
ADC_SHA = "c" * 64
PLAN_SHA = "d" * 64


def epoch3_identity() -> ActiveExecutionEpoch:
    """Fixture for a generic V3 epoch, retaining the historical issue number."""
    origin = {
        "schema": "PASES_ISSUE_EXECUTION_EPOCH_V3",
        "repository": "puchinya/ai-agent-workflow",
        "issue_number": 71,
        "issue_id": 6135294757,
        "adc_comment_id": 6881591677,
        "adc_sha256": "3c6b3ac28270357b57047dc5da0a2c1fbdbada269d55225ea33a656cd3076e17",
        "base_ref": "main",
        "base_sha40": "07481c4b451a81750a6c2e1a6a18bdfd4e3459c2",
        "branch_ref": "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3",
        "epoch_id": "1" * 64,
        "historical_binding_provenance": "UNVERIFIED",
        "sha256": "4" * 64,
    }
    return ActiveExecutionEpoch(
        origin=origin,
        adc_comment_id=origin["adc_comment_id"],
        adc_sha256=origin["adc_sha256"],
        applied_comment_id=6881839877,
        applied_body_sha256="3" * 64,
    ).validate()

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
    required_review_ids = ("REQ-08", "REQ-09", "checklist:exact-head")
    findings = (ReviewFindingV3("A-01", "A", False, "Blocking example", "review.md#A-01", False),) if unresolved else ()
    review = IndependentReviewV3(
        subject, "fresh-review-session", "implementation-session", "review-context.json",
        "2" * 64,
        tuple(ReviewUnitResult(item_id, "PASS", (f"review-evidence.json#{item_id}",))
              for item_id in required_review_ids),
        findings, "CONCERNS" if unresolved else "PASS", "LIMITED", None, None, None,
    ).validate(required_review_ids)
    return subject, context, pr_binding, pr, pass_result, check, acceptance, audit, review


class WorkReadinessSchemaTests(unittest.TestCase):
    def test_issue71_requires_the_active_epoch3_identity_and_v4_prbinding_bridge(self):
        repository = "puchinya/ai-agent-workflow"
        epoch = epoch3_identity()
        subject = VerificationSubject(repository, 71, 81, epoch.adc_comment_id, epoch.adc_sha256,
                                      PLAN_SHA, "e" * 40)
        binding = PRBinding(
            repository, 71, epoch.adc_comment_id, epoch.adc_sha256, epoch.base_sha40,
            epoch.branch_ref, 81, subject.pr_head_sha40, execution_epoch_sha256=epoch.sha256,
        ).validate()
        context = WorkContext(epoch, subject.pr_head_sha40, epoch.branch_ref, True, epoch.sha256).validate()
        self.assertTrue(_identity_adc_matches_subject(epoch, binding, subject))
        self.assertIsNone(context.execution_binding_sha256)
        with self.assertRaisesRegex(ValueError, "not a normal ExecutionBinding"):
            _ = context.execution_binding
        self.assertFalse(_identity_adc_matches_subject(
            epoch, PRBinding(
                repository, 71, epoch.adc_comment_id, epoch.adc_sha256, epoch.base_sha40,
                epoch.branch_ref, 81, subject.pr_head_sha40,
            ).validate(), subject,
        ))

    def test_deferred_close_pr_association_is_not_issue_specific(self):
        for issue_number in (63, 129):
            subject = VerificationSubject("octo/repo", issue_number, 55, 123, ADC_SHA,
                                          PLAN_SHA, "e" * 40)
            pr = PRReadback(
                repository="octo/repo", issue_number=issue_number, pr_number=55,
                state="open", draft=False, base_ref="main", base_sha40=BASE,
                head_ref="pases/work", head_sha40=subject.pr_head_sha40,
                head_repository="octo/repo", closing_issue_number=issue_number,
                close_on_merge=True,
            )
            binding = ExecutionBinding(
                "octo/repo", issue_number, 123, ADC_SHA, "main", BASE,
                "pases/work", str(Path(tempfile.gettempdir()) / "pases"), BASE,
            ).validate()
            context = WorkContext(binding, subject.pr_head_sha40, "pases/work",
                                  True, binding_digest(binding)).validate()
            pr_binding = PRBinding("octo/repo", issue_number, 123, ADC_SHA, BASE,
                                   "pases/work", 55, subject.pr_head_sha40).validate()
            result = evaluate_readiness(
                subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
                verification=None, acceptance=None, self_audit=None, required_item_ids=(),
                independent_review=None, required_checks_sha256=None,
            )
            self.assertFalse(any("Issue #63 requires" in reason for reason in result.reasons))

    def test_v1_binding_is_not_rejected_by_hardcoded_issue_number(self):
        repository = "puchinya/ai-agent-workflow"
        for issue_number in (71, 128):
            subject = VerificationSubject(
                repository, issue_number, 81, 6881591677,
                "3c6b3ac28270357b57047dc5da0a2c1fbdbada269d55225ea33a656cd3076e17",
                PLAN_SHA, "e" * 40,
            )
            binding = ExecutionBinding(
                repository=repository, issue_number=issue_number,
                adc_comment_id=subject.adc_comment_id, adc_sha256=subject.adc_sha256,
                base_ref="main", base_sha="07481c4b451a81750a6c2e1a6a18bdfd4e3459c2",
                work_directory=str(Path(tempfile.gettempdir()) / "pases-work"),
                branch_ref="pases/work", initial_head_sha="07481c4b451a81750a6c2e1a6a18bdfd4e3459c2",
            ).validate()
            context = WorkContext(binding, subject.pr_head_sha40, binding.branch_ref, True,
                                  binding_digest(binding)).validate()
            pr_binding = PRBinding(
                repository, issue_number, subject.adc_comment_id, subject.adc_sha256,
                binding.base_sha, binding.branch_ref, 81, subject.pr_head_sha40,
            ).validate()
            self.assertTrue(_identity_adc_matches_subject(binding, pr_binding, subject))
            result = evaluate_readiness(
                subject=subject, pr=None, pr_binding=pr_binding, work_context=context,
                verification=None, acceptance=None, self_audit=None, required_item_ids=(),
                independent_review=None, required_checks_sha256=None,
            )
            self.assertEqual(result.status, "BLOCKED")
            self.assertFalse(any("Issue #71 requires" in reason for reason in result.reasons))


    def test_readiness_identity_evidence_refs_follow_validated_active_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            epoch = epoch3_identity()
            epoch_paths = (
                root / ".p_ases/state/71/execution-epoch.json",
                root / ".p_ases/state/71/execution-epoch-attachment.json",
            )
            for path in epoch_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("validated epoch evidence", encoding="utf-8")
            self.assertEqual(_identity_evidence_paths(root, 71, epoch), epoch_paths)
            self.assertFalse(execution_binding_path(root, 71).exists())
            epoch_paths[1].unlink()
            with self.assertRaisesRegex(CLIError, "evidence file is missing"):
                _identity_evidence_paths(root, 71, epoch)
            epoch_paths[1].write_text("validated epoch evidence", encoding="utf-8")

            binding = ExecutionBinding(
                repository="octo/repo", issue_number=30, adc_comment_id=123, adc_sha256=ADC_SHA,
                base_ref="main", base_sha=BASE, work_directory=str(root),
                branch_ref="pases/ordinary", initial_head_sha=BASE,
            ).validate()
            ordinary_path = execution_binding_path(root, 30)
            ordinary_path.parent.mkdir(parents=True, exist_ok=True)
            ordinary_path.write_text("validated binding", encoding="utf-8")
            self.assertEqual(_identity_evidence_paths(root, 30, binding), (ordinary_path,))

            adopted = AdoptedExecutionEpoch(
                repository="puchinya/ai-agent-workflow", issue_number=63, adc_comment_id=100,
                adc_sha256="1" * 64, pr_number=64, pr_author_user_id=3744776,
                selected_base_ref="main", selected_base_sha40=BASE,
                branch_ref="codex/issue-63-adoption", observed_start_head_sha40=HEAD,
                adoption_id="2" * 64, plan_sha256="3" * 64, owner_decision_comment_id=1,
                owner_authorization_plan_sha256="4" * 64, approval_scope_sha256="5" * 64,
                intent_comment_id=2, applied_comment_id=3, intent_body_sha256="6" * 64,
                applied_body_sha256="7" * 64, attachment_id="8" * 64,
            ).validate()
            adopted_paths = (adoption_path(root, 63), adoption_attachment_path(root, 63))
            for path in adopted_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("validated adopted epoch", encoding="utf-8")
            self.assertEqual(_identity_evidence_paths(root, 63, adopted), adopted_paths)
            adopted_paths[0].unlink()
            with self.assertRaisesRegex(CLIError, "evidence file is missing"):
                _identity_evidence_paths(root, 63, adopted)

    def test_readiness_does_not_emit_or_accept_reconstructed_v1_binding_for_issue71(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            epoch = epoch3_identity()
            for path in (
                root / ".p_ases/state/71/execution-epoch.json",
                root / ".p_ases/state/71/execution-epoch-attachment.json",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("validated epoch evidence", encoding="utf-8")
            legacy_path = execution_binding_path(root, 71)
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text("reconstructed binding", encoding="utf-8")
            with self.assertRaisesRegex(CLIError, "must not coexist with an ordinary V1 ExecutionBinding"):
                _identity_evidence_paths(root, 71, epoch)

    def test_adopted_epoch_uses_current_prbinding_adc_without_mutating_origin(self):
        repository = "puchinya/ai-agent-workflow"
        origin_adc_sha = "1" * 64
        current_adc_sha = "2" * 64
        adoption_id = "3" * 64
        epoch = AdoptedExecutionEpoch(
            repository=repository, issue_number=63, adc_comment_id=100,
            adc_sha256=origin_adc_sha, pr_number=64, pr_author_user_id=3744776,
            selected_base_ref="main", selected_base_sha40=BASE,
            branch_ref="codex/issue-63-activation-ruleset-management",
            observed_start_head_sha40=HEAD, adoption_id=adoption_id,
            plan_sha256="4" * 64, owner_decision_comment_id=1,
            owner_authorization_plan_sha256="5" * 64, approval_scope_sha256="6" * 64,
            intent_comment_id=2, applied_comment_id=3,
            intent_body_sha256="7" * 64, applied_body_sha256="8" * 64,
            attachment_id="9" * 64,
        ).validate()
        subject = VerificationSubject(
            repository, 63, 64, 200, current_adc_sha, PLAN_SHA, "e" * 40,
        )
        current = PRBinding(
            repository, 63, 200, current_adc_sha, BASE,
            "codex/issue-63-activation-ruleset-management", 64,
            subject.pr_head_sha40, adoption_id=adoption_id,
        ).validate()
        self.assertTrue(_identity_adc_matches_subject(epoch, current, subject))
        self.assertEqual(epoch.adc_comment_id, 100)
        self.assertEqual(epoch.adc_sha256, origin_adc_sha)
        self.assertFalse(_identity_adc_matches_subject(
            epoch, PRBinding(**{**current.__dict__, "adc_comment_id": 201}).validate(), subject,
        ))
        self.assertFalse(_identity_adc_matches_subject(
            epoch, PRBinding(**{**current.__dict__, "adoption_id": "a" * 64}).validate(), subject,
        ))

    def test_readiness_passes_only_for_matching_open_exact_subject_and_all_evidence(self):
        subject, context, pr_binding, pr, passed, check, acceptance, audit, review = setup()
        result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=review, required_checks_sha256=check.sha256,
        )
        self.assertEqual(result.status, "PASS")
        self.assertTrue(result.ready_for_user_review)
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(ReadinessResult.from_bytes(result.to_bytes()), result)
        with tempfile.TemporaryDirectory() as temporary:
            path = readiness_path(Path(temporary), result)
            self.assertEqual(write_readiness(path, result), result.sha256)
            self.assertEqual(read_readiness(path), result)

    def test_missing_stale_draft_fork_and_unresolved_review_block_readiness(self):
        subject, context, pr_binding, pr, passed, check, acceptance, audit, review = setup()
        args = dict(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=review, required_checks_sha256=check.sha256,
        )
        self.assertEqual(evaluate_readiness(**{**args, "verification": None}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "pr": setup(draft=True)[3]}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "pr": setup(fork=True)[3]}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "pr_binding": setup(stale=True)[2]}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "independent_review": None}).status, "BLOCKED")
        self.assertEqual(evaluate_readiness(**{**args, "independent_review": setup(unresolved=True)[8]}).status, "CONCERNS")

    def test_unaccepted_dependency_is_an_explicit_readiness_blocker(self):
        subject, context, pr_binding, pr, passed, check, acceptance, audit, review = setup()
        result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=review, required_checks_sha256=check.sha256,
            blocker_reasons=("WAITING_DEPENDENCY #28: formal Oracle has not been accepted",),
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("WAITING_DEPENDENCY #28", result.reasons[0])

    def test_activation_base_advance_requires_a_typed_evidence_link(self):
        subject, context, source_binding, pr, passed, check, acceptance, audit, review = setup()
        advanced_base = "f" * 40
        advanced_pr = PRReadback(**{**pr.__dict__, "base_sha40": advanced_base})
        args = dict(
            subject=subject, pr=advanced_pr, pr_binding=source_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=review, required_checks_sha256=check.sha256,
        )
        self.assertEqual(evaluate_readiness(**args).status, "BLOCKED")
        proof = CurrentBaseAdvanceEvidence(
            repository=subject.repository, issue_number=subject.issue_number,
            pr_number=subject.pr_number, pr_id=900, branch_ref=source_binding.branch_ref,
            frozen_base_sha40=BASE, current_base_sha40=advanced_base,
            activation_issue_number=57, activation_record_id=901, activation_record_sha256="1" * 64,
            setup_pr_number=902, setup_pr_id=903, setup_branch="pases/consumer-activation-57-abc12345",
            setup_head_sha40="1" * 40, setup_merge_sha40="2" * 40,
            original_pr_binding_sha256=source_binding.sha256,
            original_pr_head_sha40=source_binding.pr_head_sha40,
            transition_pr_head_sha40=subject.pr_head_sha40,
            activation_profile_sha256="3" * 64,
            original_code_patch_sha256="4" * 64, transition_code_patch_sha256="4" * 64,
        ).validate()
        advanced_binding = PRBinding(
            source_binding.repository, source_binding.issue_number, source_binding.adc_comment_id,
            source_binding.adc_sha256, source_binding.base_sha40, source_binding.branch_ref,
            source_binding.pr_number, source_binding.pr_head_sha40,
            advanced_base, proof.sha256,
        ).validate()
        result = evaluate_readiness(
            **{**args, "pr_binding": advanced_binding}, current_base_advance=proof,
        )
        self.assertEqual(result.status, "PASS")
        self.assertIn(proof.sha256, result.evidence_sha256s)

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

    def test_limited_provenance_independent_review_still_passes_readiness(self):
        subject, context, pr_binding, pr, passed, check, acceptance, audit, _review = setup()
        required = ("REQ-08", "REQ-09", "checklist:exact-head")
        review = IndependentReviewV3(
            subject, "fresh-child-context", "implementation-session", "review-context.json",
            "3" * 64,
            tuple(ReviewUnitResult(item_id, "PASS", (f"review-evidence.json#{item_id}",))
                  for item_id in required),
            (), "PASS", "LIMITED", None, None, None,
        ).validate(required)
        result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=required,
            independent_review=review, required_checks_sha256=check.sha256,
        )
        self.assertEqual(result.status, "PASS")
        self.assertTrue(result.ready_for_user_review)

    def test_legacy_review_without_child_authored_unit_coverage_cannot_pass_readiness(self):
        subject, context, pr_binding, pr, passed, check, acceptance, audit, _review = setup()
        review = IndependentReviewV2(
            subject, "fresh-child-context", "implementation-session", "review-context.json",
            "3" * 64, (), "PASS", "LIMITED", None, None, None,
        ).validate()
        result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=review, required_checks_sha256=check.sha256,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("independent review lacks child-authored complete review-unit coverage", result.reasons)

        legacy_v1 = IndependentReview(
            subject, "fresh-child-context", "implementation-session", "review-context.json",
            "4" * 64, (), "PASS",
        ).validate()
        v1_result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=("REQ-08", "REQ-09", "checklist:exact-head"),
            independent_review=legacy_v1, required_checks_sha256=check.sha256,
        )
        self.assertEqual(v1_result.status, "BLOCKED")

    def test_review_v3_requires_exact_unit_coverage_and_typed_blocking_c(self):
        subject, *_ = setup()
        required = ("REQ-08", "REQ-09", "checklist:exact-head")
        units = tuple(ReviewUnitResult(item_id, "PASS", (f"evidence.json#{item_id}",))
                      for item_id in required)
        incomplete = IndependentReviewV3(
            subject, "review", "implementation", "context.json", "4" * 64,
            units[:-1], (), "PASS", "LIMITED", None, None, None,
        )
        with self.assertRaisesRegex(ValueError, "cover every required review unit exactly"):
            incomplete.validate(required)

        nonblocking_c = IndependentReviewV3(
            subject, "review", "implementation", "context.json", "5" * 64, units,
            (ReviewFindingV3("C-01", "C", False, "New optional requirement", "c.json#sha256=x", False),),
            "PASS", "LIMITED", None, None, None,
        ).validate(required)
        self.assertEqual(nonblocking_c.blocking_findings, ())
        subject, context, pr_binding, pr, passed, check, acceptance, audit, _review = setup()
        nonblocking_result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=required, independent_review=nonblocking_c,
            required_checks_sha256=check.sha256,
        )
        self.assertEqual(nonblocking_result.status, "PASS")
        blocking_c = IndependentReviewV3(
            subject, "review", "implementation", "context.json", "6" * 64, units,
            (ReviewFindingV3("C-01", "C", False, "Reviewer-designated blocker", "c.json#sha256=x", True),),
            "PASS", "LIMITED", None, None, None,
        )
        with self.assertRaisesRegex(ValueError, "unresolved blocking findings"):
            blocking_c.validate(required)
        blocking_c_concerns = IndependentReviewV3(
            **{**blocking_c.__dict__, "verdict": "CONCERNS"},
        ).validate(required)
        blocking_result = evaluate_readiness(
            subject=subject, pr=pr, pr_binding=pr_binding, work_context=context,
            verification=passed, acceptance=acceptance, self_audit=audit,
            required_item_ids=required, independent_review=blocking_c_concerns,
            required_checks_sha256=check.sha256,
        )
        self.assertEqual(blocking_result.status, "CONCERNS")
        with self.assertRaisesRegex(ValueError, "Only a reviewer-designated C finding"):
            ReviewFindingV3("B-01", "B", False, "A/B is inherently blocking", "b.json#sha256=x", True).validate()


if __name__ == "__main__":
    unittest.main()
