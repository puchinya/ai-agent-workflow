from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.branch_policy import assess_branch_policy
from p_ases.delivery import ReadinessResult, evaluate_final_delivery
from p_ases.evidence_store import VerificationSubject
from p_ases.user_review import UserReviewResult, UserReviewSubject
from p_ases.verification import RequiredCheckPolicy, VerificationResult


HEAD = "a" * 40
SUBJECT = VerificationSubject("octo/repo", 31, 37, 123, "b" * 64, "c" * 64, HEAD).validate()
READINESS = ReadinessResult("PASS", SUBJECT, (), ("d" * 64,), "e" * 64).validate()
USER_SUBJECT = UserReviewSubject(SUBJECT, READINESS.sha256).validate()
USER_REVIEW = UserReviewResult("APPROVED", USER_SUBJECT, "f" * 64, (), "user-review",
                               "pr-review:5").validate()
SOLO_USER_REVIEW = UserReviewResult("APPROVED", USER_SUBJECT, "f" * 64, (), "user-review",
                                   "issue-comment:77").validate()
CHECK_POLICY = RequiredCheckPolicy((("ci", 15368),)).validate()
VERIFICATION = VerificationResult(
    "PASS", SUBJECT, (), CHECK_POLICY.sha256, "2" * 64, ("3" * 64,), (),
).validate()


def active_policy(mode="external_reviewer", approvals=1):
    if mode == "external_reviewer":
        return assess_branch_policy(
            repository="octo/repo", branch="main", review_mode=mode,
            required_check_policy=CHECK_POLICY, branch_info={"protected": True},
            legacy_protection={
                "required_status_checks": {"checks": [{"context": "ci", "app_id": 15368}]},
                "required_pull_request_reviews": {"required_approving_review_count": approvals},
            }, effective_rules=[], ruleset_details=[], source_errors={},
        )
    rules = [
        {"type": "pull_request", "parameters": {"required_approving_review_count": approvals}},
        {"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": "ci", "integration_id": 15368}],
        }},
        {"type": "non_fast_forward", "parameters": {}},
    ]
    details = {"id": 17, "source": "octo/repo", "source_type": "Repository",
               "target": "branch", "enforcement": "active",
               "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
               "bypass_actors": [], "rules": rules}
    effective = [{"ruleset_id": 17, "ruleset_source_type": "Repository",
                  "ruleset_source": "octo/repo", "type": row["type"], "parameters": row["parameters"]}
                 for row in rules]
    return assess_branch_policy(
        repository="octo/repo", branch="main", review_mode=mode,
        required_check_policy=CHECK_POLICY, branch_info={"protected": True},
        legacy_protection=None, effective_rules=effective, ruleset_details=[details], source_errors={},
    )


def formal_review(*, reviewer=7, author_type="User", state="APPROVED", commit=HEAD,
                  submitted="2026-10-12T00:00:00Z", updated="2026-10-12T00:00:00Z"):
    return {"id": 8, "state": state, "commit_id": commit,
            "submitted_at": submitted, "updated_at": updated,
            "user": {"id": reviewer, "type": author_type}}


def evaluate(**overrides):
    inputs = dict(
        subject=SUBJECT, user_review=USER_REVIEW, verification=VERIFICATION,
        current_pr_head_sha40=HEAD, current_pr_state="open", current_pr_draft=False,
        github_review_decision="APPROVED", github_review_head_sha40=HEAD,
        github_reviews=(formal_review(),), branch_policy=active_policy(),
        required_check_policy=CHECK_POLICY, review_mode="external_reviewer",
        repository_owner_type="User", repository_owner_id=42,
        authenticated_user_id=42, pr_author_id=99, mergeable=True,
    )
    inputs.update(overrides)
    return evaluate_final_delivery(**inputs)


class FinalDeliveryTests(unittest.TestCase):
    def test_external_mode_passes_only_to_explicit_merge_authorization(self):
        result = evaluate()
        self.assertEqual(result.status, "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION")
        value = result.as_dict()
        self.assertFalse(value["merge_authorized"])
        self.assertEqual(value["schema"], "PASES_FINAL_DELIVERY_V2")
        self.assertEqual(value["review_mode"], "external_reviewer")
        self.assertEqual(value["branch_policy_status"], "VERIFIED")
        self.assertEqual(value["branch_policy_sha256"], active_policy().sha256)
        self.assertEqual(value["branch_policy_branch"], "main")
        self.assertIn("effective-rules", value["branch_policy_sources"])
        self.assertEqual(value["branch_policy_required_actions"], [])
        self.assertEqual(len(result.sha256), 64)

    def test_formal_review_effective_policy_or_exact_head_failure_blocks(self):
        cases = (
            {"github_review_decision": "REVIEW_REQUIRED"},
            {"github_review_head_sha40": "f" * 40},
            {"branch_policy": None},
            {"branch_policy": active_policy(approvals=0)},
            {"github_reviews": (formal_review(reviewer=99),)},
            {"github_reviews": (formal_review(state="DISMISSED"),)},
            {"current_pr_head_sha40": "f" * 40},
            {"mergeable": False},
        )
        for values in cases:
            with self.subTest(values=values):
                self.assertEqual(evaluate(**values).status, "BLOCKED")

    def test_stale_readiness_or_user_review_for_another_subject_blocks(self):
        stale = UserReviewResult("APPROVED", UserReviewSubject(
            VerificationSubject("octo/repo", 31, 37, 123, "b" * 64, "c" * 64, "f" * 40),
            READINESS.sha256), "f" * 64, (), "user-review", "pr-review:5").validate()
        self.assertEqual(evaluate(user_review=stale).status, "BLOCKED")
        self.assertEqual(evaluate(verification=None).status, "BLOCKED")

    def test_solo_owner_requires_personal_owner_author_identity_and_exact_ruleset(self):
        base = dict(
            user_review=SOLO_USER_REVIEW, review_mode="solo_owner",
            branch_policy=active_policy("solo_owner", approvals=0),
            github_review_decision="REVIEW_REQUIRED", github_reviews=(),
            repository_owner_type="User", repository_owner_id=42,
            authenticated_user_id=42, pr_author_id=42,
        )
        self.assertEqual(evaluate(**base).status, "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION")
        for key, value in (("repository_owner_type", "Organization"),
                           ("repository_owner_id", 41), ("authenticated_user_id", 41),
                           ("pr_author_id", 41)):
            with self.subTest(key=key):
                changed = dict(base)
                changed[key] = value
                self.assertEqual(evaluate(**changed).status, "BLOCKED")

    def test_solo_owner_does_not_accept_formal_self_approval_or_wrong_review_carrier(self):
        base = dict(review_mode="solo_owner", branch_policy=active_policy("solo_owner", approvals=0),
                    github_review_decision="APPROVED", github_reviews=(formal_review(reviewer=42),),
                    repository_owner_type="User", repository_owner_id=42,
                    authenticated_user_id=42, pr_author_id=42)
        self.assertEqual(evaluate(**(base | {"user_review": USER_REVIEW})).status, "BLOCKED")
        self.assertEqual(evaluate(**(base | {"user_review": SOLO_USER_REVIEW})).status,
                         "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION")

    def test_solo_owner_does_not_ignore_another_users_current_head_review(self):
        inputs = dict(
            user_review=SOLO_USER_REVIEW, review_mode="solo_owner",
            branch_policy=active_policy("solo_owner", approvals=0),
            github_review_decision="REVIEW_REQUIRED", github_reviews=(formal_review(reviewer=99),),
            repository_owner_type="User", repository_owner_id=42,
            authenticated_user_id=42, pr_author_id=42,
        )
        result = evaluate(**inputs)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("OTHER_FORMAL_REVIEW_PRESENT", result.reason_codes)

    def test_policy_change_blocks_and_v2_merge_authorization_remains_false(self):
        blocked = evaluate(branch_policy=active_policy(approvals=0))
        self.assertEqual(blocked.status, "BLOCKED")
        self.assertFalse(blocked.as_dict()["merge_authorized"])


if __name__ == "__main__":
    unittest.main()
