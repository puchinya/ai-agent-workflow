from __future__ import annotations

import hashlib
import json
import sys
import unittest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.evidence_store import VerificationSubject
from p_ases.review_assurance import (
    AttestedNativeDelegationEvidenceV1, IndependentReviewOccurrenceV1, IndependentReviewV2, ReviewAssuranceError,
    capture_unavailability_observation, evaluate_capture_unavailability,
    evaluate_review_assurance, report_separate_context_review,
)
from p_ases.review_host_adapters import (
    ClaudeCodeReviewAdapter, CodexCloudReviewAdapter, CodexDesktopReviewAdapter,
    CodexLocalCLIReviewAdapter,
)


SUBJECT = VerificationSubject("owner/repo", 46, 91, 123, "a" * 64, "b" * 64, "c" * 40)
EXECUTION = "execution-binding:" + "e" * 64
PROFILE_SHA = "d" * 64


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def native_capture(*, same_context=False, completed=True, child_subject=None,
                   findings=None, verdict="PASS"):
    reviewer = EXECUTION if same_context else "native-review-child-7"
    request = canonical({
        "execution_identity_context_id": EXECUTION,
        "operation": "spawn_independent_review_child",
        "reviewer_context_id": reviewer,
        "schema": "PASES_NATIVE_REVIEW_REQUEST_V1",
        "subject": SUBJECT.as_dict(),
    })
    child_output = canonical({
        "findings": [] if findings is None else findings, "reviewer_context_id": reviewer,
        "schema": "PASES_CHILD_REVIEW_OUTPUT_V1",
        "subject": SUBJECT.as_dict() if child_subject is None else child_subject, "verdict": verdict,
    })
    terminal = canonical({
        "child_output_sha256": hashlib.sha256(child_output).hexdigest(),
        "completed": completed,
        "request_sha256": hashlib.sha256(request).hexdigest(),
        "schema": "PASES_NATIVE_REVIEW_TERMINAL_V1",
        "status": "success" if completed else "running",
    })
    return request, terminal, child_output


def fabricated_review(*, subject=SUBJECT, profile_sha256=PROFILE_SHA):
    request, terminal, output = native_capture()
    evidence = AttestedNativeDelegationEvidenceV1.capture(
        subject=subject, execution_identity_context_id=EXECUTION,
        request=request, terminal_return=terminal, child_output=output,
    )
    return IndependentReviewV2(
        subject=subject, assurance="INDEPENDENT_ATTESTED",
        reviewer_context_id=evidence.reviewer_context_id,
        execution_identity_context_id=EXECUTION, verdict="PASS", findings=(),
        native_evidence=evidence, profile_sha256=profile_sha256,
        evidence_origin="operator_captured_native_tool_result",
    ).validate()


class ReviewAssuranceTests(unittest.TestCase):
    def test_locally_synthesized_capture_cannot_satisfy_attested_policy(self):
        request, terminal, output = native_capture()
        with self.assertRaisesRegex(ReviewAssuranceError, "cannot be attested"):
            CodexCloudReviewAdapter.attest(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                profile_sha256=PROFILE_SHA, request=request, terminal_return=terminal,
                child_output=output,
            )
        review = fabricated_review()
        self.assertEqual(review.assurance, "INDEPENDENT_ATTESTED")
        self.assertIsNone(review.native_evidence.host_spawn_id)
        self.assertEqual(IndependentReviewV2.from_bytes(review.to_bytes()), review)
        decision = evaluate_review_assurance(
            review, subject=SUBJECT, execution_identity_context_id=EXECUTION,
            minimum_assurance="independent_attested", profile_sha256=PROFILE_SHA,
        )
        self.assertEqual(decision.status, "BLOCKED")
        self.assertEqual(decision.assurance, "UNAVAILABLE")
        self.assertTrue(any("capture boundary" in reason for reason in decision.reasons))

    def test_attested_result_does_not_satisfy_default_host_verified_minimum(self):
        review = fabricated_review()
        decision = evaluate_review_assurance(
            review, subject=SUBJECT, execution_identity_context_id=EXECUTION,
            minimum_assurance="host_verified", profile_sha256=PROFILE_SHA,
        )
        self.assertEqual(decision.status, "BLOCKED")
        self.assertEqual(decision.assurance, "UNAVAILABLE")
        self.assertTrue(any("HOST_VERIFIED" in reason for reason in decision.reasons))

    def test_same_context_incomplete_completion_and_changed_terminal_are_rejected(self):
        request, terminal, output = native_capture(same_context=True)
        with self.assertRaisesRegex(ReviewAssuranceError, "distinct child"):
            AttestedNativeDelegationEvidenceV1.capture(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                request=request, terminal_return=terminal, child_output=output,
            )
        request, terminal, output = native_capture(completed=False)
        with self.assertRaisesRegex(ReviewAssuranceError, "successful completion"):
            AttestedNativeDelegationEvidenceV1.capture(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                request=request, terminal_return=terminal, child_output=output,
            )
        request, terminal, output = native_capture()
        tampered = terminal.replace(b"success", b"failed")
        with self.assertRaisesRegex(ReviewAssuranceError, "exact bytes"):
            AttestedNativeDelegationEvidenceV1.capture(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                request=request, terminal_return=tampered, child_output=output,
            )

    def test_child_output_requires_canonical_subject_and_findings(self):
        def finding(finding_id, severity="C"):
            return {
                "description": "Diagnostic finding",
                "evidence_ref": "tests/test_review_assurance.py",
                "finding_id": finding_id,
                "resolved": True,
                "severity": severity,
            }

        invalid_results = (
            (
                "short subject",
                {"repo": "owner/repo", "issue": 46, "pr": 91, "head": "c" * 40},
                [],
                "child output is not bound",
            ),
            ("INFO severity", SUBJECT.as_dict(), [finding("A-01", "INFO")],
             "severity must be A, B, or C"),
            ("unsorted findings", SUBJECT.as_dict(), [finding("B-01"), finding("A-01")],
             "canonical ID order"),
        )
        for label, subject, findings, expected_error in invalid_results:
            with self.subTest(label=label):
                request, terminal, child_output = native_capture(
                    child_subject=subject, findings=findings, verdict="FAIL",
                )
                with self.assertRaisesRegex(ReviewAssuranceError, expected_error):
                    AttestedNativeDelegationEvidenceV1.capture(
                        subject=SUBJECT, execution_identity_context_id=EXECUTION,
                        request=request, terminal_return=terminal, child_output=child_output,
                    )

    def test_stale_profile_or_subject_blocks_assurance(self):
        review = fabricated_review()
        decision = evaluate_review_assurance(
            review, subject=VerificationSubject("owner/repo", 46, 91, 123, "f" * 64, "b" * 64, "c" * 40),
            execution_identity_context_id=EXECUTION, minimum_assurance="independent_attested",
            profile_sha256="9" * 64,
        )
        self.assertEqual(decision.status, "BLOCKED")
        self.assertGreaterEqual(len(decision.reasons), 2)

    def test_all_host_adapters_are_distinct_and_do_not_claim_live_host_verification(self):
        adapters = (CodexCloudReviewAdapter, CodexLocalCLIReviewAdapter,
                    CodexDesktopReviewAdapter, ClaudeCodeReviewAdapter)
        self.assertEqual(len({adapter.surface for adapter in adapters}), 4)
        for adapter in adapters:
            with self.subTest(surface=adapter.surface):
                capabilities = adapter.capabilities()
                self.assertFalse(capabilities.native_request_return_capture)
                self.assertFalse(capabilities.trusted_host_event_verification)

    def test_capture_unavailability_requires_an_independent_occurrence_report_and_does_not_override_failure(self):
        capabilities = CodexCloudReviewAdapter.capabilities().as_dict()
        observation, digest = capture_unavailability_observation("codex_cloud", capabilities)
        missing = evaluate_capture_unavailability(
            host_surface="codex_cloud", observation=observation, observation_sha256=digest,
        )
        self.assertEqual(missing.status, "INVALID_EVIDENCE")
        self.assertTrue(any("occurrence" in reason for reason in missing.reasons))
        with self.assertRaisesRegex(ReviewAssuranceError, "formal Independent Review PASS"):
            IndependentReviewV2(
                subject=SUBJECT, assurance="UNAVAILABLE", reviewer_context_id="separate-reviewer-7",
                execution_identity_context_id=EXECUTION, verdict="PASS", findings=(),
                profile_sha256=PROFILE_SHA, evidence_origin="operator_reported_separate_context_review",
            ).validate()
        reported_review = report_separate_context_review(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            reviewer_context_id="native-review-child-7", verdict="PASS", findings=(),
            profile_sha256=PROFILE_SHA,
        )
        raw_output = native_capture()[2]
        occurrence = IndependentReviewOccurrenceV1.from_captured_output(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            execution_binding_sha256="e" * 64, pr_binding_sha256="f" * 64,
            profile_sha256=PROFILE_SHA, independent_review_v2_sha256=reported_review.sha256,
            raw_output=raw_output,
        )
        eligible = evaluate_capture_unavailability(
            host_surface="codex_cloud", observation=observation, observation_sha256=digest,
            current_reviews=(reported_review,), current_occurrences=(occurrence,),
        )
        self.assertEqual(eligible.status, "HOST_NATIVE_CAPTURE_UNAVAILABLE")
        recorded = report_separate_context_review(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            reviewer_context_id="native-review-child-7", verdict="PASS", findings=(),
            profile_sha256=PROFILE_SHA,
        )
        self.assertEqual(recorded.assurance, "UNAVAILABLE")
        self.assertEqual(recorded.verdict, "BLOCKED")
        self.assertEqual(recorded.evidence_origin, "operator_reported_separate_context_review")
        self.assertEqual(IndependentReviewV2.from_bytes(recorded.to_bytes()), recorded)
        with self.assertRaisesRegex(ReviewAssuranceError, "distinct independent reviewer context"):
            report_separate_context_review(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                reviewer_context_id=EXECUTION, verdict="PASS", findings=(),
                profile_sha256=PROFILE_SHA,
            )

    def test_occurrence_record_preserves_exact_output_and_separates_outcome_from_provenance(self):
        capabilities = CodexCloudReviewAdapter.capabilities().as_dict()
        observation, digest = capture_unavailability_observation("codex_cloud", capabilities)
        _request, _terminal, raw_output = native_capture()
        review = report_separate_context_review(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            reviewer_context_id="native-review-child-7", verdict="PASS", findings=(),
            profile_sha256=PROFILE_SHA,
        )
        occurrence = IndependentReviewOccurrenceV1.from_captured_output(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            execution_binding_sha256="e" * 64, pr_binding_sha256="f" * 64,
            profile_sha256=PROFILE_SHA, independent_review_v2_sha256=review.sha256,
            raw_output=raw_output,
        )
        restored = IndependentReviewOccurrenceV1.from_bytes(occurrence.to_bytes())
        self.assertEqual(restored, occurrence)
        self.assertEqual(restored.review_occurrence, "COMPLETED")
        self.assertEqual(restored.review_outcome, "PASS")
        self.assertEqual(restored.provenance_assurance, "UNAVAILABLE")
        self.assertEqual(restored.reviewer_output.validate("test output"), raw_output)
        with self.assertRaisesRegex(ReviewAssuranceError, "separate context"):
            IndependentReviewOccurrenceV1.from_captured_output(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                execution_binding_sha256="e" * 64, pr_binding_sha256="f" * 64,
                profile_sha256=PROFILE_SHA, independent_review_v2_sha256=review.sha256,
                raw_output=raw_output.replace(b"native-review-child-7", EXECUTION.encode()),
            )
        failed_output = canonical({
            "findings": [], "reviewer_context_id": "native-review-child-7",
            "schema": "PASES_CHILD_REVIEW_OUTPUT_V1", "subject": SUBJECT.as_dict(), "verdict": "FAIL",
        })
        request = canonical({
            "execution_identity_context_id": EXECUTION, "operation": "spawn_independent_review_child",
            "reviewer_context_id": "native-review-child-7", "schema": "PASES_NATIVE_REVIEW_REQUEST_V1",
            "subject": SUBJECT.as_dict(),
        })
        terminal = canonical({
            "child_output_sha256": hashlib.sha256(failed_output).hexdigest(), "completed": True,
            "request_sha256": hashlib.sha256(request).hexdigest(), "schema": "PASES_NATIVE_REVIEW_TERMINAL_V1",
            "status": "success",
        })
        native = AttestedNativeDelegationEvidenceV1.capture(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            request=request, terminal_return=terminal, child_output=failed_output,
        )
        failed_review = IndependentReviewV2(
            subject=SUBJECT, assurance="INDEPENDENT_ATTESTED",
            reviewer_context_id=native.reviewer_context_id, execution_identity_context_id=EXECUTION,
            verdict="FAIL", findings=(), native_evidence=native, profile_sha256=PROFILE_SHA,
            evidence_origin="operator_captured_native_tool_result",
        ).validate()
        failed = evaluate_capture_unavailability(
            host_surface="codex_cloud", observation=observation, observation_sha256=digest,
            current_reviews=(failed_review,),
        )
        self.assertEqual(failed.status, "REVIEW_FAILED")
        unavailable_failed = report_separate_context_review(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            reviewer_context_id="native-review-child-7", verdict="FAIL", findings=(),
            profile_sha256=PROFILE_SHA,
        )
        fail_output = native_capture(verdict="FAIL")[2]
        fail_occurrence = IndependentReviewOccurrenceV1.from_captured_output(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            execution_binding_sha256="e" * 64, pr_binding_sha256="f" * 64,
            profile_sha256=PROFILE_SHA, independent_review_v2_sha256=unavailable_failed.sha256,
            raw_output=fail_output,
        )
        unavailable_result = evaluate_capture_unavailability(
            host_surface="codex_cloud", observation=observation, observation_sha256=digest,
            current_reviews=(unavailable_failed,), current_occurrences=(fail_occurrence,),
        )
        self.assertEqual(unavailable_result.status, "REVIEW_FAILED")
        fabricated_pass = fabricated_review()
        ineligible = evaluate_capture_unavailability(
            host_surface="codex_cloud", observation=observation, observation_sha256=digest,
            current_reviews=(fabricated_pass,),
        )
        self.assertEqual(ineligible.status, "INVALID_EVIDENCE")

    def test_capture_observation_must_match_surface_and_digest(self):
        observation, digest = capture_unavailability_observation(
            "claude_code", ClaudeCodeReviewAdapter.capabilities().as_dict())
        mismatch = evaluate_capture_unavailability(
            host_surface="codex_cloud", observation=observation, observation_sha256=digest,
        )
        self.assertEqual(mismatch.status, "INVALID_EVIDENCE")
        tampered = {**observation, "host_surface": "codex_cloud"}
        invalid = evaluate_capture_unavailability(
            host_surface="claude_code", observation=tampered, observation_sha256=digest,
        )
        self.assertEqual(invalid.status, "INVALID_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
