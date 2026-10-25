from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.review_assurance import capture_unavailability_observation
from p_ases.review_host_adapters.codex_cloud import CodexCloudReviewAdapter
from p_ases.delivery import (
    FinalDeliveryResult, ReadinessCore, ReadinessResultV2,
    evaluate_final_delivery_with_exception, evaluate_readiness_with_exception,
)
from p_ases.evidence_store import VerificationSubject
from p_ases.review_assurance import ReviewCaptureEligibility
from p_ases.review_unavailable_exception import (
    ISSUE_NUMBER, OWNER_USER_ID, RECORD_SCHEMA, REPOSITORY, REPOSITORY_ID,
    ReviewUnavailableError, ReviewUnavailableException, ReviewUnavailablePlan,
    approval_comment, apply_exception, read_exception, read_exception_comment,
    verify_owner_approval,
)
from p_ases import review_unavailable_exception as exception_module
from p_ases.user_review import UserReviewSubject, evaluate_user_review


def snapshot():
    observation, digest = capture_unavailability_observation(
        "codex_cloud", CodexCloudReviewAdapter.capabilities().as_dict())
    return {
        "adc_comment_id": 1001, "adc_sha256": "a" * 64,
        "base_ref": "main", "base_sha40": "1" * 40,
        "branch_ref": "codex/issue-46-multi-host-independent-review",
        "capability_observation_sha256s": [digest],
        "execution_binding_sha256": "2" * 64, "head_sha40": "3" * 40,
        "host_surface": "codex_cloud", "issue_id": 5846549384, "issue_number": ISSUE_NUMBER,
        "owner_user_id": OWNER_USER_ID, "pr_binding_sha256": "4" * 64,
        "pr_number": 67, "profile_sha256": "5" * 64,
        "reason": "HOST_NATIVE_CAPTURE_UNAVAILABLE", "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID, "risk": "INDEPENDENT_REVIEW_NOT_PERFORMED",
        "verification_plan_sha256": "6" * 64,
    }


def comment(comment_id, body, author_id=OWNER_USER_ID, login="puchinya"):
    stamp = "2026-10-25T03:00:00Z"
    return {
        "id": comment_id, "body": body,
        "user": {"id": author_id, "login": login, "type": "User"},
        "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
        "html_url": f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}",
        "created_at": stamp, "updated_at": stamp,
    }


class FakeGitHub:
    repo = REPOSITORY

    def __init__(self, owner_body):
        self.comments = [comment(1201, owner_body)]
        self.posts = 0

    def repository_metadata(self):
        return {"id": REPOSITORY_ID}

    def authenticated_user(self):
        return {"id": OWNER_USER_ID, "login": "puchinya", "type": "User"}

    def issue_comments(self, issue_number):
        assert issue_number == ISSUE_NUMBER
        return list(self.comments)

    def issue_comment(self, issue_number, comment_id):
        assert issue_number == ISSUE_NUMBER
        rows = [row for row in self.comments if row["id"] == comment_id]
        if len(rows) != 1:
            raise ValueError("missing comment")
        return dict(rows[0])

    def create_issue_comment(self, issue_number, body):
        assert issue_number == ISSUE_NUMBER
        self.posts += 1
        row = comment(1202, body)
        self.comments.append(row)
        return dict(row)


class ReviewUnavailableExceptionTests(unittest.TestCase):
    def test_plan_canonical_bytes_and_owner_scope_are_exact(self):
        plan = ReviewUnavailablePlan.create(snapshot(), generated_at="2026-10-25T03:00:00.000000Z")
        self.assertEqual(ReviewUnavailablePlan.from_bytes(plan.to_bytes()), plan)
        self.assertIn(plan.sha256, approval_comment(plan))
        tampered = dict(plan.value)
        tampered["snapshot"] = {**plan.snapshot, "head_sha40": "9" * 40}
        with self.assertRaisesRegex(ReviewUnavailableError, "digest"):
            ReviewUnavailablePlan(tampered).validate()
        wrong_scope = {**plan.snapshot, "pr_number": 68}
        with self.assertRaisesRegex(ReviewUnavailableError, "scope"):
            ReviewUnavailablePlan.create(wrong_scope)

    def test_owner_approval_and_exception_receipt_use_direct_list_direct_and_replay_noop(self):
        plan = ReviewUnavailablePlan.create(snapshot(), generated_at="2026-10-25T03:00:00.000000Z")
        github = FakeGitHub(approval_comment(plan))
        owner_digest, _ = verify_owner_approval(github, plan, 1201)
        self.assertEqual(owner_digest, hashlib.sha256(approval_comment(plan).encode()).hexdigest())
        with tempfile.TemporaryDirectory() as temporary:
            record, path, replayed = apply_exception(github, plan, 1201, local_root=Path(temporary))
            self.assertFalse(replayed)
            self.assertEqual(github.posts, 1)
            self.assertEqual(read_exception(path), record)
            self.assertEqual(read_exception_comment(github, record)["id"], 1202)
            replay, replay_path, replayed = apply_exception(github, plan, 1201, local_root=Path(temporary))
            self.assertTrue(replayed)
            self.assertEqual(replay, record)
            self.assertEqual(replay_path, path)
            self.assertEqual(github.posts, 1)
            self.assertEqual(record.value["schema"], RECORD_SCHEMA)
            self.assertNotEqual(record.value["owner_approval_comment_id"],
                                record.value["exception_comment_id"])

    def test_wrong_owner_edited_approval_and_duplicate_record_fail_closed(self):
        plan = ReviewUnavailablePlan.create(snapshot(), generated_at="2026-10-25T03:00:00.000000Z")
        bad_owner = FakeGitHub(approval_comment(plan))
        bad_owner.comments[0] = comment(1201, approval_comment(plan), author_id=7, login="other")
        with self.assertRaisesRegex(ReviewUnavailableError, "author"):
            verify_owner_approval(bad_owner, plan, 1201)
        edited = FakeGitHub(approval_comment(plan) + "\n")
        with self.assertRaisesRegex(ReviewUnavailableError, "body|missing|conflicting"):
            verify_owner_approval(edited, plan, 1201)
        github = FakeGitHub(approval_comment(plan))
        with tempfile.TemporaryDirectory() as temporary:
            record, _path, _ = apply_exception(github, plan, 1201, local_root=Path(temporary))
            github.comments.append(dict(github.comments[-1], id=1203,
                                        url=f"https://api.github.com/repos/{REPOSITORY}/issues/comments/1203",
                                        html_url=f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-1203"))
            with self.assertRaisesRegex(ReviewUnavailableError, "conflicting|duplicated"):
                apply_exception(github, plan, 1201, local_root=Path(temporary))
            self.assertEqual(github.posts, 1)

    def test_exception_readers_reject_conflicting_or_malformed_same_head_history(self):
        plan_a = ReviewUnavailablePlan.create(snapshot(), generated_at="2026-10-25T03:00:00.000000Z")
        github = FakeGitHub(approval_comment(plan_a))
        with tempfile.TemporaryDirectory() as temporary:
            record_a, _path, _ = apply_exception(github, plan_a, 1201, local_root=Path(temporary))
            plan_b = ReviewUnavailablePlan.create(
                {**snapshot(), "host_surface": "claude_code"},
                generated_at="2026-10-25T03:01:00.000000Z",
            )
            approval_b = approval_comment(plan_b)
            github.comments.append(comment(1203, approval_b))
            approval_b_sha = hashlib.sha256(approval_b.encode("utf-8")).hexdigest()
            body_b = exception_module._record_body(plan_b, 1203, approval_b_sha, OWNER_USER_ID)
            github.comments.append(comment(1204, body_b))
            with self.assertRaisesRegex(ReviewUnavailableError, "duplicate or conflicting"):
                read_exception_comment(github, record_a)

        malformed = FakeGitHub(approval_comment(plan_a))
        with tempfile.TemporaryDirectory() as temporary:
            record, _path, _ = apply_exception(malformed, plan_a, 1201, local_root=Path(temporary))
            malformed.comments.append(comment(1205, f"<!-- {RECORD_SCHEMA}\nnot-json\n-->"))
            with self.assertRaisesRegex(ReviewUnavailableError, "malformed"):
                read_exception_comment(malformed, record)

    def test_wrong_repository_and_forged_receipt_digest_fail_before_reuse(self):
        plan = ReviewUnavailablePlan.create(snapshot(), generated_at="2026-10-25T03:00:00.000000Z")
        github = FakeGitHub(approval_comment(plan))
        github.repo = "someone/else"
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ReviewUnavailableError, "repository"):
                apply_exception(github, plan, 1201, local_root=Path(temporary))
            self.assertEqual(github.posts, 0)

        github = FakeGitHub(approval_comment(plan))
        with tempfile.TemporaryDirectory() as temporary:
            record, _path, _replayed = apply_exception(github, plan, 1201, local_root=Path(temporary))
            forged = ReviewUnavailableException({
                **record.value,
                "exception_comment_sha256": "f" * 64,
            }).validate()
            with self.assertRaisesRegex(ReviewUnavailableError, "body digest|missing|duplicated|conflicts"):
                read_exception_comment(github, forged)

    def test_readiness_v2_user_review_and_final_v2_disclose_exception_without_merge_authority(self):
        current = snapshot()
        plan = ReviewUnavailablePlan.create(current, generated_at="2026-10-25T03:00:00.000000Z")
        body = approval_comment(plan)
        record = ReviewUnavailableException({
            "exception_comment_id": 1202,
            "exception_comment_sha256": hashlib.sha256(b"exception receipt").hexdigest(),
            "owner_approval_comment_id": 1201,
            "owner_approval_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "plan": plan.value,
            "plan_sha256": plan.sha256,
            "publisher_user_id": OWNER_USER_ID,
            "schema": RECORD_SCHEMA,
        }).validate()
        subject = VerificationSubject(
            REPOSITORY, ISSUE_NUMBER, 67, current["adc_comment_id"], current["adc_sha256"],
            current["verification_plan_sha256"], current["head_sha40"],
        ).validate()
        observation, observation_sha = capture_unavailability_observation(
            "codex_cloud", CodexCloudReviewAdapter.capabilities().as_dict())
        eligibility = ReviewCaptureEligibility(
            "HOST_NATIVE_CAPTURE_UNAVAILABLE", "codex_cloud", (observation_sha,), (),
        ).validate()
        core = ReadinessCore(
            subject=subject, reasons=(), evidence_sha256s=tuple(sorted(("7" * 64, "8" * 64, "9" * 64))),
            required_check_policy_sha256="9" * 64, base_ref="main", base_sha40=current["base_sha40"],
            branch_ref=current["branch_ref"], pr_binding_sha256=current["pr_binding_sha256"],
            execution_binding_sha256=current["execution_binding_sha256"],
        ).validate()
        readiness = evaluate_readiness_with_exception(
            core=core, profile_sha256=current["profile_sha256"], eligibility=eligibility, exception=record,
        )
        self.assertEqual(readiness.status, "READY_WITH_EXCEPTION")
        self.assertEqual(readiness.review_assurance, "UNAVAILABLE")
        self.assertEqual(ReadinessResultV2.from_bytes(readiness.to_bytes()), readiness)
        user_subject = UserReviewSubject(subject, readiness.sha256).validate()
        user_review = evaluate_user_review(
            user_subject, readiness, subject.pr_head_sha40, (), allowed_human_user_ids=(OWNER_USER_ID,),
        )
        self.assertFalse(any("Readiness is missing" in reason for reason in user_review.reasons))
        final = evaluate_final_delivery_with_exception(
            ordinary=FinalDeliveryResult(
                "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION", subject, "a" * 64, "b" * 64, "c" * 64, (),
            ).validate(),
            readiness=readiness,
        )
        self.assertEqual(final.status, "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION")
        self.assertFalse(final.merge_authorized)
        self.assertEqual(final.as_dict()["schema"], "PASES_FINAL_DELIVERY_V2")

    def test_readiness_v2_keeps_other_gates_and_stale_exception_blocked(self):
        current = snapshot()
        plan = ReviewUnavailablePlan.create(current, generated_at="2026-10-25T03:00:00.000000Z")
        body = approval_comment(plan)
        record = ReviewUnavailableException({
            "exception_comment_id": 1202, "exception_comment_sha256": "a" * 64,
            "owner_approval_comment_id": 1201,
            "owner_approval_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "plan": plan.value, "plan_sha256": plan.sha256,
            "publisher_user_id": OWNER_USER_ID, "schema": RECORD_SCHEMA,
        }).validate()
        subject = VerificationSubject(
            REPOSITORY, ISSUE_NUMBER, 67, current["adc_comment_id"], current["adc_sha256"],
            current["verification_plan_sha256"], current["head_sha40"],
        ).validate()
        _, observation_sha = capture_unavailability_observation(
            "codex_cloud", CodexCloudReviewAdapter.capabilities().as_dict())
        eligibility = ReviewCaptureEligibility(
            "HOST_NATIVE_CAPTURE_UNAVAILABLE", "codex_cloud", (observation_sha,), (),
        ).validate()
        core = ReadinessCore(
            subject=subject, reasons=("Verification status is FAIL",), evidence_sha256s=(),
            required_check_policy_sha256=None, base_ref="main", base_sha40=current["base_sha40"],
            branch_ref=current["branch_ref"], pr_binding_sha256=current["pr_binding_sha256"],
            execution_binding_sha256=current["execution_binding_sha256"],
        ).validate()
        blocked = evaluate_readiness_with_exception(
            core=core, profile_sha256=current["profile_sha256"], eligibility=eligibility, exception=record,
        )
        self.assertEqual(blocked.status, "BLOCKED")
        changed_subject = VerificationSubject(
            REPOSITORY, ISSUE_NUMBER, 67, current["adc_comment_id"], current["adc_sha256"],
            current["verification_plan_sha256"], "f" * 40,
        ).validate()
        stale_core = ReadinessCore(
            subject=changed_subject, reasons=(), evidence_sha256s=(), required_check_policy_sha256="9" * 64,
            base_ref="main", base_sha40=current["base_sha40"], branch_ref=current["branch_ref"],
            pr_binding_sha256=current["pr_binding_sha256"],
            execution_binding_sha256=current["execution_binding_sha256"],
        ).validate()
        stale = evaluate_readiness_with_exception(
            core=stale_core, profile_sha256=current["profile_sha256"], eligibility=eligibility, exception=record,
        )
        self.assertEqual(stale.status, "BLOCKED")
        self.assertTrue(any("head_sha40" in reason for reason in stale.reasons))


if __name__ == "__main__":
    unittest.main()
