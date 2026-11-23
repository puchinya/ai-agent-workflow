"""Issue #79 regression tests for ordinary exact-HEAD merge authorization."""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.cli import _merge_readback, _owner_merge_gate, _perform_authorized_merge
from p_ases.owner_authorization import (
    OwnerAuthorizationError, authorize_chat_confirmed_plan,
    capture_direct_chat_confirmation, create_authorization_plan,
    ordinary_merge_details, read_authorization_plan, write_authorization_plan,
)

REPO = "puchinya/ai-agent-workflow"
HEAD = "b" * 40
GATE_SHA = "e" * 64
SUBJECT_SHA = "f" * 64


class OrdinaryGitHub:
    repo = REPO

    def __init__(self):
        self.body = "Implement a bounded rework path.\n\nCloses #79"
        self.title = "Issue 79 review/rework"
        self.head = HEAD
        self.base_ref = "main"
        self.base_sha = "a" * 40
        self.comments = []
        self.posts = 0

    def repository_metadata(self):
        return {"full_name": REPO, "id": 1401910271,
                "owner": {"id": 3744776, "type": "User", "login": "puchinya"}}

    def issue(self, number):
        return {"number": number, "state": "open", "pull_request": None,
                "repository_url": f"https://api.github.com/repos/{REPO}"}

    def authenticated_user(self):
        return {"id": 3744776, "login": "puchinya", "type": "User"}

    def pull_request(self, number):
        return {"number": number, "state": "open", "merged": False, "draft": False,
                "head": {"sha": self.head, "repo": {"full_name": REPO}},
                "base": {"ref": self.base_ref, "sha": self.base_sha,
                         "repo": {"full_name": REPO}},
                "title": self.title, "body": self.body}

    def issue_comments(self, number):
        if number != 79:
            raise AssertionError("ordinary decisions must stay on Issue #79")
        return list(self.comments)

    def issue_comment(self, number, comment_id):
        if number != 79:
            raise AssertionError("cross-Issue decision read")
        return next(row for row in self.comments if row["id"] == comment_id)

    def create_issue_comment(self, number, body):
        if number != 79:
            raise AssertionError("cross-Issue decision write")
        self.posts += 1
        ident = 500 + len(self.comments)
        row = {
            "id": ident, "body": body,
            "created_at": "2026-11-23T12:00:00Z",
            "updated_at": "2026-11-23T12:00:00Z",
            "user": {"id": 3744776, "login": "puchinya", "type": "User"},
            "url": f"https://api.github.com/repos/{REPO}/issues/comments/{ident}",
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/79",
            "html_url": f"https://github.com/{REPO}/issues/79#issuecomment-{ident}",
        }
        self.comments.append(row)
        return row


class OrdinaryMergeAuthorizationTests(unittest.TestCase):
    def plan(self, github, root):
        details = ordinary_merge_details(
            github, issue_number=79, pr_number=80, pr_head_sha40=HEAD,
            final_delivery_sha256=GATE_SHA,
            final_delivery_subject_sha256=SUBJECT_SHA,
        )
        subject = hashlib.sha256(b"issue79 exact PR80 merge").hexdigest()
        with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                patch("p_ases.owner_authorization.head_sha40", return_value=HEAD):
            plan = create_authorization_plan(
                github, root, operation="PR_MERGE", subject_sha256=subject,
                issue_number=79, target_issue_number=79,
                pr_number=80, pr_head_sha40=HEAD, details=details,
            )
        return plan

    def test_generic_plan_is_issue_local_and_round_trips(self):
        github = OrdinaryGitHub()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan(github, root)
            self.assertEqual((plan["issue_number"], plan["target_issue_number"]), (79, 79))
            self.assertEqual(plan["details"]["association_mode"], "auto_close")
            path = root / "plan.json"
            write_authorization_plan(path, plan)
            self.assertEqual(read_authorization_plan(path), plan)
            self.assertEqual(github.posts, 0)

    def test_stale_head_or_missing_auto_close_never_creates_a_plan(self):
        github = OrdinaryGitHub()
        with tempfile.TemporaryDirectory() as directory:
            github.body = "Refs #79"
            with self.assertRaisesRegex(OwnerAuthorizationError, "Closes"):
                self.plan(github, Path(directory))
            github.body = "Closes #79"
            github.head = "c" * 40
            with self.assertRaisesRegex(OwnerAuthorizationError, "exact open"):
                self.plan(github, Path(directory))
            self.assertEqual(github.posts, 0)

    def test_owner_plan_fixes_target_base_and_merge_method(self):
        github = OrdinaryGitHub()
        with tempfile.TemporaryDirectory() as directory:
            plan = self.plan(github, Path(directory))
            self.assertEqual(plan["details"]["pr_base_ref"], "main")
            self.assertEqual(plan["details"]["pr_base_sha40"], "a" * 40)
            self.assertEqual(plan["details"]["merge_method"], "merge")
            self.assertEqual(plan["details"]["final_delivery_sha256"], GATE_SHA)
            github.base_ref = "release"
            with (patch("p_ases.owner_authorization.worktree_clean", return_value=True),
                    patch("p_ases.owner_authorization.head_sha40", return_value=HEAD)):
                with self.assertRaisesRegex(OwnerAuthorizationError, "plan no longer matches"):
                    create_authorization_plan(
                        github, Path(directory), operation="PR_MERGE",
                        subject_sha256=plan["subject_sha256"], issue_number=79,
                        target_issue_number=79, pr_number=80, pr_head_sha40=HEAD,
                        details=plan["details"],
                    )

    def test_merge_rejects_changed_base_or_final_delivery_before_merge(self):
        for drift in ("base", "final_delivery"):
            github = OrdinaryGitHub()
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self.plan(github, root)
                decision = {
                    "status": "AUTHORIZED", "operation": "PR_MERGE",
                    "evidence_type": "PASES_OWNER_DECISION_V3",
                    "evidence_channel": "chat_confirmed_gh_v1", "chat_signature": False,
                    "owner_decision_comment_id": 501,
                }
                subject = {"repository": REPO, "issue_number": 79,
                           "pr_number": 80, "pr_head_sha40": HEAD}
                gate = {"final_delivery_sha256": GATE_SHA, "subject": subject}
                # The approved plan binds the exact serialized Final Delivery subject.
                import json
                subject_digest = hashlib.sha256(
                    json.dumps(subject, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                plan["details"]["final_delivery_subject_sha256"] = subject_digest
                if drift == "base":
                    github.base_ref = "release"
                else:
                    gate["final_delivery_sha256"] = "d" * 64
                with patch("p_ases.cli._owner_merge_gate", return_value=gate):
                    with self.subTest(drift=drift), self.assertRaises(OwnerAuthorizationError):
                        _perform_authorized_merge(argparse.Namespace(), root, github, plan, decision)
                self.assertFalse((root / ".p_ases" / "delivery").exists(),
                                 "failure must occur before the merge attempt record")

    def test_merge_gate_readback_binds_the_exact_final_delivery_subject(self):
        import json
        github = OrdinaryGitHub()
        with tempfile.TemporaryDirectory() as directory:
            plan = self.plan(github, Path(directory))
            final = {
                "schema": "PASES_FINAL_DELIVERY_V3",
                "status": "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION",
                "review_mode": "solo_owner",
                "branch_protection_sha256": None,
                "user_review_sha256": "3" * 64,
                "required_check_result_sha256": "4" * 64,
                "merge_authorized": False,
                "final_delivery_sha256": GATE_SHA,
                "subject": {"repository": REPO, "issue_number": 79,
                            "pr_number": 80, "pr_head_sha40": HEAD},
                "blockers": [],
            }
            def evaluate(_args, _repository, _root, _github):
                print(json.dumps(final))
                return 0
            args = argparse.Namespace(
                readiness="readiness", delivery_plan="plan",
                verification="verification", acceptance="acceptance",
                self_audit="self-audit", independent_review="independent-review",
                user_review_record="user-review",
            )
            with patch("p_ases.cli._delivery_final", side_effect=evaluate):
                result = _owner_merge_gate(args, Path(directory), github, plan)
            self.assertEqual(result["final_delivery_sha256"], GATE_SHA)
            self.assertEqual(result["subject"], final["subject"])
            final["status"] = "BLOCKED"
            with patch("p_ases.cli._delivery_final", side_effect=evaluate):
                with self.assertRaisesRegex(OwnerAuthorizationError, "not PASS"):
                    _owner_merge_gate(args, Path(directory), github, plan)

    def test_merged_readback_rejects_target_branch_change(self):
        class MergedGitHub(OrdinaryGitHub):
            def pull_request(self, number):
                row = super().pull_request(number)
                row.update(state="closed", merged=True, merge_commit_sha="c" * 40,
                           merged_by={"id": 3744776, "login": "puchinya", "type": "User"})
                return row
        github = MergedGitHub()
        with tempfile.TemporaryDirectory() as directory:
            # The plan is created from the open PR before its merge.
            open_github = OrdinaryGitHub()
            plan = self.plan(open_github, Path(directory))
            self.assertEqual(_merge_readback(github, plan)["pr_number"], 80)
            github.base_ref = "release"
            with self.assertRaisesRegex(OwnerAuthorizationError, "different base branch"):
                _merge_readback(github, plan)

    def test_explicit_chat_grant_is_exact_subject_and_single_use(self):
        github = OrdinaryGitHub()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan(github, root)
            grant = capture_direct_chat_confirmation(
                plan, response="承認する", user_role="user", same_conversation=True,
            )
            with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=HEAD):
                result = authorize_chat_confirmed_plan(github, root, plan, grant)
            self.assertEqual(result["status"], "AUTHORIZED")
            self.assertEqual(github.posts, 1)
            self.assertIn('"issue_number":79', github.comments[0]["body"])
            with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=HEAD):
                with self.assertRaisesRegex(OwnerAuthorizationError, "already has an owner decision"):
                    authorize_chat_confirmed_plan(github, root, plan, grant)
            self.assertEqual(github.posts, 1)


if __name__ == "__main__":
    unittest.main()
