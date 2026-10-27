from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.branch_policy import assess_branch_policy  # noqa: E402
from p_ases.verification import RequiredCheckPolicy  # noqa: E402


POLICY = RequiredCheckPolicy((("ci", 15368),)).validate()


def solo_ruleset(*, branch="main", approvals=0, enforcement="active", bypass=(),
                 check_rows=(("ci", 15368),), include=None, force_push=True):
    rules = [
        {"type": "pull_request", "parameters": {"required_approving_review_count": approvals}},
        {"type": "required_status_checks", "parameters": {
            "required_status_checks": [
                {"context": name, "integration_id": app_id} for name, app_id in check_rows
            ],
        }},
    ]
    if force_push:
        rules.append({"type": "non_fast_forward", "parameters": {}})
    details = {
        "id": 17, "source": "octo/repo", "source_type": "Repository",
        "target": "branch", "enforcement": enforcement,
        "conditions": {"ref_name": {"include": include or [f"refs/heads/{branch}"], "exclude": []}},
        "bypass_actors": list(bypass), "rules": rules,
    }
    effective = [
        {"ruleset_id": 17, "ruleset_source_type": "Repository", "ruleset_source": "octo/repo",
         "type": row["type"], "parameters": row["parameters"]}
        for row in rules
    ]
    return effective, [details]


def assess(*, mode="solo_owner", branch_info=None, legacy=None, effective=None,
           rulesets=None, errors=None, required=POLICY):
    return assess_branch_policy(
        repository="octo/repo", branch="main", review_mode=mode,
        required_check_policy=required,
        branch_info={"protected": True} if branch_info is None else branch_info,
        legacy_protection=legacy,
        effective_rules=[] if effective is None else effective,
        ruleset_details=[] if rulesets is None else rulesets,
        source_errors={} if errors is None else errors,
    )


class BranchPolicyTests(unittest.TestCase):
    def test_solo_owner_requires_one_exact_active_ruleset_and_is_digest_stable(self):
        rules, details = solo_ruleset()
        first = assess(effective=rules, rulesets=details)
        second = assess(effective=rules, rulesets=details)
        self.assertEqual(first.status, "VERIFIED")
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.review_mode, "solo_owner")

    def test_403_404_not_configured_and_mismatch_remain_distinct(self):
        unavailable = assess(errors={"legacy_protection": 403})
        unverified = assess(branch_info=None, errors={"legacy_protection": 404})
        not_configured = assess(branch_info={"protected": False}, effective=[], rulesets=[],
                                errors={"legacy_protection": 404})
        rules, details = solo_ruleset(approvals=1)
        mismatch = assess(effective=rules, rulesets=details)
        self.assertEqual(unavailable.status, "UNAVAILABLE")
        self.assertEqual(unverified.status, "UNVERIFIED")
        self.assertEqual(not_configured.status, "NOT_CONFIGURED")
        self.assertEqual(mismatch.status, "MISMATCH")

    def test_solo_owner_rejects_wrong_check_app_scope_enforcement_and_bypass(self):
        cases = (
            solo_ruleset(check_rows=(("ci", 999),)),
            solo_ruleset(branch="other"),
            solo_ruleset(enforcement="evaluate"),
            solo_ruleset(bypass=({"actor_id": 1, "actor_type": "RepositoryRole", "bypass_mode": "always"},)),
        )
        for effective, details in cases:
            with self.subTest(details=details):
                self.assertEqual(assess(effective=effective, rulesets=details).status, "MISMATCH")

    def test_solo_owner_requires_ruleset_even_when_legacy_protection_is_present(self):
        legacy = {
            "required_status_checks": {"checks": [{"context": "ci", "app_id": 15368}]},
            "required_pull_request_reviews": {"required_approving_review_count": 0},
        }
        self.assertEqual(assess(legacy=legacy, effective=[], rulesets=[]).status, "MISMATCH")

    def test_solo_owner_preserves_conflicting_legacy_approval_requirement(self):
        legacy = {
            "required_status_checks": {"checks": [{"context": "ci", "app_id": 15368}]},
            "required_pull_request_reviews": {"required_approving_review_count": 1},
        }
        rules, details = solo_ruleset(approvals=0)
        result = assess(legacy=legacy, effective=rules, rulesets=details)
        self.assertEqual(result.status, "MISMATCH")
        self.assertIn("SOLO_OWNER_LEGACY_APPROVAL_POLICY_CONFLICT", result.reason_codes)
        self.assertEqual(result.minimum_approvals, 1)

    def test_external_reviewer_accepts_exact_legacy_policy(self):
        legacy = {
            "required_status_checks": {"checks": [{"context": "ci", "app_id": 15368}]},
            "required_pull_request_reviews": {"required_approving_review_count": 1},
        }
        result = assess(mode="external_reviewer", legacy=legacy, effective=[], rulesets=[])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.review_mode, "external_reviewer")

    def test_external_reviewer_accepts_stronger_ruleset_approval_and_records_actual_count(self):
        rules, details = solo_ruleset(approvals=2, force_push=False,
                                     bypass=({"actor_id": 1, "actor_type": "RepositoryRole",
                                              "bypass_mode": "always"},))
        result = assess(mode="external_reviewer", effective=rules, rulesets=details)
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.minimum_approvals, 2)
        self.assertEqual(result.bypass_actor_count, 1)
        self.assertFalse(result.force_push_disabled)

    def test_status_diagnostics_keep_source_errors_and_admin_actions(self):
        unavailable = assess(errors={"legacy_protection": 403})
        self.assertEqual(unavailable.source_errors, (("legacy_protection", 403),))
        self.assertIn("branch", unavailable.source)
        self.assertTrue(unavailable.required_actions)
        not_configured = assess(branch_info={"protected": False}, effective=[], rulesets=[],
                                errors={"legacy_protection": 404})
        self.assertEqual(not_configured.status, "NOT_CONFIGURED")
        self.assertIn("effective-rules", not_configured.source)
        self.assertIn("ruleset-details", not_configured.source)

    def test_ruleset_source_mismatch_is_not_verified(self):
        rules, details = solo_ruleset()
        details[0]["source"] = "other/repo"
        self.assertEqual(assess(effective=rules, rulesets=details).status, "MISMATCH")

    def test_duplicate_effective_rule_type_is_rejected(self):
        rules, details = solo_ruleset()
        rules.append(dict(rules[0]))
        result = assess(effective=rules, rulesets=details)
        self.assertEqual(result.status, "MISMATCH")
        self.assertIn("DUPLICATE_EFFECTIVE_RULE", result.reason_codes)

    def test_check_policy_names_are_not_repository_constants(self):
        custom = RequiredCheckPolicy((("consumer-build", 9876),)).validate()
        effective, details = solo_ruleset(check_rows=(("consumer-build", 9876),))
        self.assertEqual(assess(effective=effective, rulesets=details, required=custom).status,
                         "VERIFIED")


if __name__ == "__main__":
    unittest.main()
