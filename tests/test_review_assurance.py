from __future__ import annotations

import hashlib
import json
import sys
import unittest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.evidence_store import VerificationSubject
from p_ases.review_assurance import (
    IndependentReviewV2, ReviewAssuranceError, evaluate_review_assurance,
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


def native_capture(*, same_context=False, completed=True):
    reviewer = EXECUTION if same_context else "native-review-child-7"
    request = canonical({
        "execution_identity_context_id": EXECUTION,
        "operation": "spawn_independent_review_child",
        "reviewer_context_id": reviewer,
        "schema": "PASES_NATIVE_REVIEW_REQUEST_V1",
        "subject": SUBJECT.as_dict(),
    })
    child_output = canonical({
        "findings": [], "reviewer_context_id": reviewer,
        "schema": "PASES_CHILD_REVIEW_OUTPUT_V1", "subject": SUBJECT.as_dict(), "verdict": "PASS",
    })
    terminal = canonical({
        "child_output_sha256": hashlib.sha256(child_output).hexdigest(),
        "completed": completed,
        "request_sha256": hashlib.sha256(request).hexdigest(),
        "schema": "PASES_NATIVE_REVIEW_TERMINAL_V1",
        "status": "success" if completed else "running",
    })
    return request, terminal, child_output


class ReviewAssuranceTests(unittest.TestCase):
    def test_locally_synthesized_capture_cannot_satisfy_attested_policy(self):
        request, terminal, output = native_capture()
        review = CodexCloudReviewAdapter.attest(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            profile_sha256=PROFILE_SHA, request=request, terminal_return=terminal,
            child_output=output,
        )
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
        review = CodexCloudReviewAdapter.attest(
            subject=SUBJECT, execution_identity_context_id=EXECUTION,
            profile_sha256=PROFILE_SHA, request=native_capture()[0],
            terminal_return=native_capture()[1], child_output=native_capture()[2],
        )
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
            CodexCloudReviewAdapter.attest(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                profile_sha256=PROFILE_SHA, request=request, terminal_return=terminal, child_output=output,
            )
        request, terminal, output = native_capture(completed=False)
        with self.assertRaisesRegex(ReviewAssuranceError, "successful completion"):
            CodexCloudReviewAdapter.attest(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                profile_sha256=PROFILE_SHA, request=request, terminal_return=terminal, child_output=output,
            )
        request, terminal, output = native_capture()
        tampered = terminal.replace(b"success", b"failed")
        with self.assertRaisesRegex(ReviewAssuranceError, "exact bytes"):
            CodexCloudReviewAdapter.attest(
                subject=SUBJECT, execution_identity_context_id=EXECUTION,
                profile_sha256=PROFILE_SHA, request=request, terminal_return=tampered, child_output=output,
            )

    def test_stale_profile_or_subject_blocks_assurance(self):
        request, terminal, output = native_capture()
        review = CodexCloudReviewAdapter.attest(
            subject=SUBJECT, execution_identity_context_id=EXECUTION, profile_sha256=PROFILE_SHA,
            request=request, terminal_return=terminal, child_output=output,
        )
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


if __name__ == "__main__":
    unittest.main()
