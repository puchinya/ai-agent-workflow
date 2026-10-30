from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.audits import (
    AuditError, AuditItem, IndependentReview, IndependentReviewV2, IndependentReviewV3,
    ReviewFinding, ReviewFindingV3, ReviewUnitResult, SelfAudit,
    read_independent_review, read_self_audit, write_independent_review, write_self_audit,
)
from p_ases.evidence_store import VerificationSubject
from p_ases.profile import ProfileError, load_profile


SUBJECT = VerificationSubject("owner/repo", 30, 73, 123, "a" * 64, "b" * 64, "c" * 40)


def project_config(required_checks=None):
    return {
        "schema_version": 2, "initialized": True, "project_name": "test-project",
        "components": [], "branch": {
            "prefix": "feature", "max_slug_length": 48, "cleanup_on_switch": [],
            "required_checks": required_checks or [{"name": "ci"}],
        },
        "workspace": {}, "milestones": {}, "hooks": {},
    }


class WorkReadinessTests(unittest.TestCase):
    def test_skipped_or_flaky_self_audit_items_never_count_as_pass(self):
        items = tuple(sorted((
            AuditItem("REQ-08", "PASS", ("one#sha256=" + "1" * 64,)),
            AuditItem("REQ-09", "SKIPPED", ("two#sha256=" + "2" * 64,)),
            AuditItem("checklist:01", "PASS", ("three#sha256=" + "3" * 64,)),
        ), key=lambda item: item.item_id))
        with self.assertRaises(AuditError):
            SelfAudit(SUBJECT, items).validate(("REQ-08", "REQ-09", "checklist:01"))

    def test_self_audit_requires_every_requirement_and_checklist_evidence(self):
        items = tuple(sorted((
            AuditItem("REQ-08", "PASS", ("evidence.json#sha256=" + "1" * 64,)),
            AuditItem("REQ-09", "PASS", ("evidence.json#sha256=" + "1" * 64,)),
            AuditItem("checklist:01", "PASS", ("pr.json#sha256=" + "2" * 64,)),
        ), key=lambda item: item.item_id))
        audit = SelfAudit(SUBJECT, items)
        required = ("REQ-08", "REQ-09", "checklist:01")
        audit.validate(required)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "self-audit.json"
            self.assertEqual(write_self_audit(path, audit, required), audit.sha256)
            self.assertEqual(read_self_audit(path), audit)
            with self.assertRaises(AuditError):
                write_self_audit(path, SelfAudit(SUBJECT, items[:-1]), required)
        with self.assertRaises(AuditError):
            SelfAudit(SUBJECT, items[:-1]).validate(required)

    def test_independent_review_requires_a_separate_context_and_round_trips(self):
        review = IndependentReview(
            subject=SUBJECT, reviewer_context_id="fresh-review-context",
            implementation_context_id="implementation-context", context_artifact_ref="review-context.json",
            context_artifact_sha256="4" * 64,
            findings=(ReviewFinding("A-01", "A", True, "Resolved with code evidence", "evidence.json#sha256=" + "5" * 64),),
            verdict="PASS",
        ).validate()
        expected_v1 = (
            b'{"context_artifact_ref":"review-context.json","context_artifact_sha256":"'
            + b"4" * 64
            + b'","findings":[{"description":"Resolved with code evidence","evidence_ref":"evidence.json#sha256='
            + b"5" * 64
            + b'","finding_id":"A-01","resolved":true,"severity":"A"}],'
            b'"implementation_context_id":"implementation-context","review_sha256":"'
            b'4ebef294128dae743add4ed3a26fe6bf256115c56ba22e5b91ecade1eb2dce3d'
            b'","reviewer_context_id":"fresh-review-context","schema":"PASES_INDEPENDENT_REVIEW_V1",'
            b'"subject":{"adc_comment_id":123,"adc_sha256":"' + b"a" * 64
            + b'","issue_number":30,"plan_sha256":"' + b"b" * 64
            + b'","pr_head_sha40":"' + b"c" * 40
            + b'","pr_number":73,"repository":"owner/repo"},"verdict":"PASS"}\n'
        )
        self.assertEqual(review.to_bytes(), expected_v1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "independent-review.json"
            self.assertEqual(write_independent_review(path, review), review.sha256)
            self.assertEqual(read_independent_review(path), review)
        same_context = IndependentReview(
            SUBJECT, "same", "same", "review.json", "6" * 64, (), "PASS",
        )
        with self.assertRaises(AuditError):
            same_context.validate()

    def test_independent_review_v2_records_limited_provenance_without_blocking_review(self):
        review = IndependentReviewV2(
            subject=SUBJECT, reviewer_context_id="fresh-review-context",
            implementation_context_id="execution-binding:current", context_artifact_ref="review-context.json",
            context_artifact_sha256="7" * 64, findings=(), verdict="PASS",
            provenance_confidence="LIMITED", spawn_session_id=None, reviewer_id=None,
            implementation_binding_id=None,
        ).validate()
        self.assertEqual(review.provenance_confidence, "LIMITED")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "independent-review-v2.json"
            self.assertEqual(write_independent_review(path, review), review.sha256)
            restored = read_independent_review(path)
            self.assertIsInstance(restored, IndependentReviewV2)
            self.assertEqual(restored, review)

    def test_independent_review_v2_accepts_matching_binding_and_rejects_mismatch(self):
        matching = IndependentReviewV2(
            subject=SUBJECT, reviewer_context_id="fresh-review-context",
            implementation_context_id="execution-binding:current", context_artifact_ref="review-context.json",
            context_artifact_sha256="8" * 64, findings=(), verdict="PASS",
            provenance_confidence="HIGH", spawn_session_id="spawn-123", reviewer_id=456,
            implementation_binding_id="execution-binding:current",
        ).validate()
        self.assertEqual(matching.provenance_confidence, "HIGH")
        mismatched = IndependentReviewV2(
            **{**matching.__dict__, "implementation_binding_id": "execution-binding:other"},
        )
        with self.assertRaisesRegex(AuditError, "binding ID"):
            mismatched.validate()

    def test_independent_review_v3_round_trips_child_unit_coverage_and_blocking_c(self):
        required = ("REQ-F01-016", "checklist:01", "checklist:02")
        review = IndependentReviewV3(
            subject=SUBJECT, reviewer_context_id="fresh-review-context",
            implementation_context_id="execution-binding:current", context_artifact_ref="review-context.json",
            context_artifact_sha256="b" * 64,
            review_units=tuple(ReviewUnitResult(item_id, "PASS", (f"evidence/{index}.json#sha256=" + str(index) * 64,))
                               for index, item_id in enumerate(required, start=1)),
            findings=(ReviewFindingV3("C-01", "C", False, "Reviewer-designated blocker",
                                      "evidence/c.json#sha256=" + "d" * 64, True),),
            verdict="CONCERNS", provenance_confidence="LIMITED", spawn_session_id=None,
            reviewer_id=None, implementation_binding_id=None,
        ).validate(required)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "independent-review-v3.json"
            self.assertEqual(write_independent_review(path, review), review.sha256)
            restored = read_independent_review(path)
            self.assertIsInstance(restored, IndependentReviewV3)
            self.assertEqual(restored, review)
            with self.assertRaisesRegex(AuditError, "cover every required review unit exactly"):
                restored.validate(required[:-1])

    def test_independent_review_v2_still_rejects_same_context_and_unresolved_blockers(self):
        same_context = IndependentReviewV2(
            subject=SUBJECT, reviewer_context_id="execution-binding:current",
            implementation_context_id="execution-binding:current", context_artifact_ref="review-context.json",
            context_artifact_sha256="9" * 64, findings=(), verdict="PASS",
            provenance_confidence="LIMITED", spawn_session_id=None, reviewer_id=None,
            implementation_binding_id=None,
        )
        with self.assertRaisesRegex(AuditError, "separate context"):
            same_context.validate()
        blocker = IndependentReviewV2(
            subject=SUBJECT, reviewer_context_id="fresh-review-context",
            implementation_context_id="execution-binding:current", context_artifact_ref="review-context.json",
            context_artifact_sha256="a" * 64,
            findings=(ReviewFinding("A-01", "A", False, "Unresolved", "review.md#A-01"),),
            verdict="PASS", provenance_confidence="LIMITED", spawn_session_id=None,
            reviewer_id=None, implementation_binding_id=None,
        )
        with self.assertRaisesRegex(AuditError, "unresolved A/B"):
            blocker.validate()

    def test_profile_rejects_unknown_settings_and_missing_trusted_app_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".agent").mkdir()
            path = root / ".agent" / "project.json"
            path.write_text(json.dumps(project_config()), encoding="utf-8")
            profile = load_profile(root)
            self.assertEqual(profile.branch_prefix, "feature")
            with self.assertRaises(ProfileError):
                profile.required_check_policy()
            path.write_text(json.dumps(project_config([{"name": "ci", "trusted_app_id": 789}])), encoding="utf-8")
            self.assertEqual(load_profile(root).required_check_policy().checks, (("ci", 789),))
            invalid = project_config()
            invalid["branch"]["surprise"] = "unknown"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ProfileError):
                load_profile(root)


if __name__ == "__main__":
    unittest.main()
