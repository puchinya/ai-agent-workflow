from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.audits import (
    AuditError, AuditItem, IndependentReview, ReviewFinding, SelfAudit,
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
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "independent-review.json"
            self.assertEqual(write_independent_review(path, review), review.sha256)
            self.assertEqual(read_independent_review(path), review)
        same_context = IndependentReview(
            SUBJECT, "same", "same", "review.json", "6" * 64, (), "PASS",
        )
        with self.assertRaises(AuditError):
            same_context.validate()

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
