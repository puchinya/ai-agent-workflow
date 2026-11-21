from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import cli, owner_authorization as owner
from p_ases.owner_consent import OwnerDecisionError


def ruleset_plan(activation_issue=91):
    return {
        "repository": "owner/project",
        "repository_id": 12345,
        "owner_id": 7654,
        "activation_issue_number": activation_issue,
        "plan_sha256": "a" * 64,
        "diff": {"operation": "update"},
    }


class FakeGithub:
    repo = "owner/project"

    def __init__(self, *, issue_number=91, comment_id=712):
        self.issue_number = issue_number
        self.comment_id = comment_id
        self.comment_reads = 0

    def repository_metadata(self):
        return {"id": 12345, "full_name": self.repo,
                "owner": {"id": 7654, "type": "User"}}

    def issue_comment(self, _issue, comment_id):
        assert comment_id == self.comment_id
        self.comment_reads += 1
        return {"id": comment_id,
                "issue_url": f"https://api.github.com/repos/{self.repo}/issues/{self.issue_number}"}


class RulesetAuthorityTests(unittest.TestCase):
    def test_exact_carrier_issue_is_derived_from_git_hub_comment(self):
        for carrier_issue in (91, 63):
            with self.subTest(carrier_issue=carrier_issue):
                github = FakeGithub(issue_number=carrier_issue)
                proof = SimpleNamespace(
                    comment_id=github.comment_id,
                    decision=SimpleNamespace(
                        schema="PASES_OWNER_DECISION_V3",
                        operation_plan_sha256="a" * 64,
                    ),
                )
                with patch.object(cli, "read_ruleset_plan", return_value=ruleset_plan()), \
                        patch.object(cli, "read_verified_owner_decision", return_value=proof) as verify:
                    value, comment_id = cli._ruleset_operation_plan(
                        github, Path("approved-plan.json"), github.comment_id,
                    )
                self.assertEqual(comment_id, github.comment_id)
                self.assertEqual(value["plan_sha256"], "a" * 64)
                self.assertEqual(verify.call_args.kwargs["issue_number"], carrier_issue)
                self.assertEqual(verify.call_args.kwargs["repository_id"], 12345)
                self.assertEqual(verify.call_args.kwargs["owner_id"], 7654)
                self.assertEqual(verify.call_args.kwargs["subject_sha256"], "a" * 64)
                self.assertEqual(github.comment_reads, 1)

    def test_missing_explicit_approval_never_searches_unbounded_issues(self):
        github = FakeGithub()
        with patch.object(cli, "read_ruleset_plan", return_value=ruleset_plan()), \
                self.assertRaisesRegex(OwnerDecisionError, "missing exact owner"):
            cli._ruleset_operation_plan(github, Path("plan.json"))
        self.assertEqual(github.comment_reads, 0)

    def test_ruleset_plan_identity_and_comment_url_fail_closed(self):
        github = FakeGithub()
        changed = ruleset_plan()
        changed["owner_id"] = 999
        with patch.object(cli, "read_ruleset_plan", return_value=changed), \
                self.assertRaisesRegex(cli.CLIError, "repository and owner"):
            cli._ruleset_operation_plan(github, Path("plan.json"), 712)
        bad = FakeGithub()
        bad.issue_comment = lambda issue, ident: {
            "id": ident, "issue_url": "https://api.github.com/repos/other/repo/issues/91",
        }
        with patch.object(cli, "read_ruleset_plan", return_value=ruleset_plan()), \
                self.assertRaisesRegex(OwnerDecisionError, "does not belong"):
            cli._ruleset_operation_plan(bad, Path("plan.json"), 712)

    def test_different_approval_id_and_plan_digest_fail_closed(self):
        github = FakeGithub()
        for proof in (
                SimpleNamespace(comment_id=999, decision=SimpleNamespace(
                    schema="PASES_OWNER_DECISION_V3", operation_plan_sha256="a" * 64)),
                SimpleNamespace(comment_id=712, decision=SimpleNamespace(
                    schema="PASES_OWNER_DECISION_V3", operation_plan_sha256="b" * 64))):
            with self.subTest(proof=proof), \
                    patch.object(cli, "read_ruleset_plan", return_value=ruleset_plan()), \
                    patch.object(cli, "read_verified_owner_decision", return_value=proof), \
                    self.assertRaises(OwnerDecisionError):
                cli._ruleset_operation_plan(github, Path("plan.json"), 712)

    def test_noop_uses_exact_plan_and_live_owner_without_decision(self):
        github = FakeGithub()
        plan = ruleset_plan()
        plan["diff"]["operation"] = "noop"
        with patch.object(cli, "read_ruleset_plan", return_value=plan), \
                patch.object(cli, "read_verified_owner_decision") as verify:
            actual, decision = cli._ruleset_operation_plan(github, Path("plan.json"))
        self.assertIs(actual, plan)
        self.assertIsNone(decision)
        verify.assert_not_called()


class RulesetOwnerPlanTests(unittest.TestCase):
    def test_generic_activation_issue_has_exact_plan_bound_owner_decision(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(owner, "worktree_clean", return_value=True), \
                patch.object(owner, "head_sha40", return_value="f" * 40), \
                patch.object(owner, "_check_identity") as identity:
            result = owner.create_authorization_plan(
                FakeGithub(), Path(temporary), operation="RULESET_PLAN_APPLY",
                subject_sha256="a" * 64, issue_number=91,
                target_issue_number=91, details={"activation_issue_number": 91},
            )
            self.assertEqual(result["issue_number"], 91)
            self.assertEqual(result["target_issue_number"], 91)
            self.assertEqual(owner._validate_plan(result), result)
            self.assertEqual(identity.call_args.args[1:3], (91, 91))
            bad = dict(result)
            bad["issue_number"] = 63
            with self.assertRaises(owner.OwnerAuthorizationError):
                owner._validate_plan(bad)


if __name__ == "__main__":
    unittest.main()
