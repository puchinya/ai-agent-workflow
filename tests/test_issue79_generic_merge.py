"""Issue #79 regression tests for ordinary exact-HEAD merge authorization."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.owner_authorization import (
    OwnerAuthorizationError, authorize_chat_confirmed_plan,
    capture_direct_chat_confirmation, create_authorization_plan,
    ordinary_merge_details, read_authorization_plan, write_authorization_plan,
)

REPO = "puchinya/ai-agent-workflow"
HEAD = "b" * 40


class OrdinaryGitHub:
    repo = REPO

    def __init__(self):
        self.body = "Implement a bounded rework path.\n\nCloses #79"
        self.title = "Issue 79 review/rework"
        self.head = HEAD
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
                "base": {"sha": "a" * 40, "repo": {"full_name": REPO}},
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
