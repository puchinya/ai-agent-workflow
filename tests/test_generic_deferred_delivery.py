from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import cli, owner_authorization as owner
from p_ases.github import GitHubError


class FakeDeferredGitHub:
    repo = "puchinya/ai-agent-workflow"
    issue_number = 91
    pr_number = 120
    head = "b" * 40
    merge_sha = "9" * 40

    def __init__(self):
        self.issue_row = {
            "number": self.issue_number, "state": "open", "closed_at": None,
            "repository_url": f"https://api.github.com/repos/{self.repo}",
            "pull_request": None,
        }
        self.pr_row = {
            "number": self.pr_number, "title": "Implement deferred work",
            "body": "Implementation complete.\n\nRefs #91",
            "state": "closed", "merged": True, "merged_at": "2026-10-14T13:00:00Z",
            "merge_commit_sha": self.merge_sha, "head": {"sha": self.head},
        }
        self.close_writes = 0
        self.ambiguous_close = False

    def pull_request(self, number):
        assert number == self.pr_number
        return copy.deepcopy(self.pr_row)

    def issue(self, number):
        assert number == self.issue_number
        return copy.deepcopy(self.issue_row)

    def issues_all(self):
        return [copy.deepcopy(self.issue_row)]

    def repository_metadata(self):
        return {"default_branch": "main"}

    def branch(self, name):
        assert name == "main"
        return {"commit": {"sha": "f" * 40}}

    def compare_commits(self, before, after):
        assert before == self.merge_sha and after == "f" * 40
        return {"status": "ahead"}

    def commit_details(self, sha):
        assert sha == self.merge_sha
        return {"message": "Merge implementation of deferred work"}

    def pull_request_commits(self, number):
        assert number == self.pr_number
        return [{"sha": self.head, "commit": {"message": "Implement work"}}]

    def pull_request_closing_issues(self, number):
        assert number == self.pr_number
        return []

    def issue_pull_request_cross_references(self, issue_number):
        assert issue_number == self.issue_number
        return []

    def close_issue(self, number):
        assert number == self.issue_number
        self.close_writes += 1
        self.issue_row["state"] = "closed"
        self.issue_row["closed_at"] = "2026-10-14T13:04:00Z"
        if self.ambiguous_close:
            raise GitHubError("ambiguous PATCH; the Issue did close")
        return self.issue(number)


def active_proof():
    return {
        "status": "ACTIVE", "activation_record_id": 900,
        "activation_record_sha256": "a" * 64,
        "activated_at": "2026-10-14T13:02:00Z",
        "ruleset_id": 19, "effective_policy_sha256": "b" * 64,
        "default_branch": "main", "default_branch_sha40": "f" * 40,
    }


class GenericDeferredDeliveryTests(unittest.TestCase):
    @staticmethod
    def run_finalize(root, github, *, history=True, proof=None):
        if proof is None:
            proof = active_proof()
        output = io.StringIO()
        with patch.object(cli, "load_profile",
                          return_value=SimpleNamespace(activation_issue_number=88)), \
                patch.object(cli, "read_consumer_activation_history",
                             return_value=[(SimpleNamespace(schema_version=2), 900)] if history else []) as read, \
                patch.object(cli, "_activation_v2_proof", return_value=proof), \
                redirect_stdout(output):
            code = cli._delivery_finalize(
                SimpleNamespace(issue=github.issue_number, pr=github.pr_number),
                github.repo, root, github, policy_github=SimpleNamespace(repo=github.repo),
            )
        if history:
            read.assert_called_once_with(github, github.repo, 88)
        return code, json.loads(output.getvalue())

    def test_generic_issue_merges_then_closes_exactly_once_after_v2_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root, github = Path(temp), FakeDeferredGitHub()
            code, result = self.run_finalize(root, github)
            self.assertEqual((code, result["status"]), (0, "FINALIZED"))
            self.assertEqual(github.close_writes, 1)
            self.assertEqual((result["issue"], result["pr"]), (91, 120))
            intent = root / ".p_ases" / "delivery" / "deferred-close" / "91" / f"{github.merge_sha}.json"
            data = json.loads(intent.read_text(encoding="utf-8"))
            self.assertEqual((data["issue_number"], data["pr_number"]), (91, 120))
            second, result = self.run_finalize(root, github)
            self.assertEqual((second, result["status"]), (0, "FINALIZED"))
            self.assertEqual(github.close_writes, 1)

    def test_activation_pending_never_creates_close_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            root, github = Path(temp), FakeDeferredGitHub()
            code, result = self.run_finalize(root, github, history=False)
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "MERGED_AWAITING_ISSUE_COMPLETION")
            self.assertEqual(github.close_writes, 0)
            self.assertFalse((root / ".p_ases" / "delivery").exists())

    def test_ambiguous_close_is_read_back_but_never_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            root, github = Path(temp), FakeDeferredGitHub()
            github.ambiguous_close = True
            code, result = self.run_finalize(root, github)
            self.assertEqual((code, result["status"]), (0, "FINALIZED"))
            code, result = self.run_finalize(root, github)
            self.assertEqual((code, result["status"]), (0, "FINALIZED"))
            self.assertEqual(github.close_writes, 1)

    def test_early_closed_issue_without_intent_never_becomes_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root, github = Path(temp), FakeDeferredGitHub()
            github.issue_row["state"] = "closed"
            github.issue_row["closed_at"] = "2026-10-14T13:00:00Z"
            code, result = self.run_finalize(root, github, history=False)
            self.assertEqual((code, result["status"]), (2, "BLOCKED"))
            self.assertEqual(github.close_writes, 0)

    def test_bad_activation_order_cannot_close_issue(self):
        with tempfile.TemporaryDirectory() as temp:
            root, github = Path(temp), FakeDeferredGitHub()
            proof = active_proof()
            proof["activated_at"] = "2026-10-14T12:59:00Z"
            code, result = self.run_finalize(root, github, proof=proof)
            self.assertEqual((code, result["status"]), (2, "BLOCKED"))
            self.assertEqual(github.close_writes, 0)

    def test_premerge_exact_deferred_metadata_blocks_auto_close_tokens(self):
        github = FakeDeferredGitHub()
        github.pr_row["state"] = "open"
        github.pr_row["merged"] = False
        details = owner.deferred_merge_details(
            github, issue_number=91, pr_number=120, pr_head_sha40=github.head,
        )
        self.assertEqual(details["target_issue_number"], 91)
        self.assertEqual(details["merge_commit_message"], owner.merge_commit_message(91))
        github.pr_row["body"] = "Closes #91"
        with self.assertRaises(owner.OwnerAuthorizationError):
            owner.deferred_merge_details(
                github, issue_number=91, pr_number=120, pr_head_sha40=github.head,
            )

    def test_generic_pr_merge_plan_is_exactly_bound_to_issue_and_head(self):
        github = FakeDeferredGitHub()
        github.pr_row.update({"state": "open", "merged": False, "draft": False})
        github.pr_row["head"]["repo"] = {"full_name": github.repo}
        github.pr_row["base"] = {"repo": {"full_name": github.repo}}
        details = owner.deferred_merge_details(
            github, issue_number=91, pr_number=120, pr_head_sha40=github.head,
        )
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(owner, "worktree_clean", return_value=True), \
                patch.object(owner, "head_sha40", return_value="c" * 40), \
                patch.object(owner, "_check_identity") as identity:
            plan = owner.create_authorization_plan(
                github, Path(temp), operation="PR_MERGE",
                subject_sha256="d" * 64, issue_number=91,
                target_issue_number=91, pr_number=120, pr_head_sha40=github.head,
                details=details,
            )
            self.assertEqual(owner._validate_plan(plan), plan)
            self.assertEqual(identity.call_args.args[1:3], (91, 91))
            with self.assertRaisesRegex(owner.OwnerAuthorizationError, "exact target Issue"):
                owner.create_authorization_plan(
                    github, Path(temp), operation="PR_MERGE",
                    subject_sha256="d" * 64, issue_number=63,
                    target_issue_number=91, pr_number=120, pr_head_sha40=github.head,
                    details=details,
                )
            mismatched = copy.deepcopy(plan)
            mismatched["issue_number"] = 63
            mismatched["approval_scope_sha256"] = owner._approval_scope_sha256(mismatched)
            mismatched_without_digest = {key: value for key, value in mismatched.items()
                                         if key != "plan_sha256"}
            mismatched["plan_sha256"] = hashlib.sha256(
                owner._canonical(mismatched_without_digest)).hexdigest()
            with self.assertRaisesRegex(owner.OwnerAuthorizationError, "carrier"):
                owner._validate_plan(mismatched)
            broken = copy.deepcopy(plan)
            broken["details"]["merge_commit_message"] = "Closes #91"
            with self.assertRaises(owner.OwnerAuthorizationError):
                owner._validate_plan(broken)


if __name__ == "__main__":
    unittest.main()
