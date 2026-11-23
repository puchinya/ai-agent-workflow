"""Issue #79: deterministic regression tests for bounded verification rework."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHubError
from p_ases.verification_rework import (
    APPLIED_SCHEMA, INTENT_SCHEMA, VerificationReworkError, MAX_CYCLES,
    read_rework_history, require_rework_progress, verification_rework,
)

REPO = "puchinya/ai-agent-workflow"
HEAD = "a" * 40
ADC_SHA = "b" * 64
BIND_SHA = "c" * 64


class FakeGitHub:
    repo = REPO

    def __init__(self, *, lost_put=None):
        self.labels = ["kind:single", "phase:verification"]
        self.comments = []
        self.comment_posts = 0
        self.label_puts = 0
        self.lost_put = lost_put
        self.head = HEAD

    def issue(self, number):
        return {
            "id": 7900, "number": number, "state": "open",
            "pull_request": None, "body": "Issue 79",
            "repository_url": f"https://api.github.com/repos/{REPO}",
            "labels": [{"name": name} for name in self.labels],
        }

    def pull_request(self, number):
        return {
            "number": number, "state": "open", "draft": False, "merged": False,
            "head": {"ref": "fix/issue79", "sha": self.head,
                     "repo": {"full_name": REPO}},
            "base": {"ref": "main", "sha": "d" * 40,
                     "repo": {"full_name": REPO}},
            "body": "Closes #79",
        }

    def issue_comments(self, number):
        return list(self.comments)

    def issue_comment(self, number, comment_id):
        return next(item for item in self.comments if item["id"] == comment_id)

    def create_issue_comment(self, number, body):
        self.comment_posts += 1
        cid = 7000 + len(self.comments)
        row = {
            "id": cid, "body": body, "created_at": "2026-11-23T12:01:01Z",
            "updated_at": "2026-11-23T12:01:01Z",
            "user": {"id": 3744776, "login": "puchinya", "type": "User"},
            "url": f"https://api.github.com/repos/{REPO}/issues/comments/{cid}",
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/79",
            "html_url": f"https://github.com/{REPO}/issues/79#issuecomment-{cid}",
        }
        self.comments.append(row)
        return row

    def replace_issue_labels(self, number, labels):
        self.label_puts += 1
        if self.lost_put == "before":
            raise GitHubError("lost before apply")
        self.labels = sorted(labels)
        if self.lost_put == "after":
            raise GitHubError("lost after apply")
        return [{"name": label} for label in labels]


class VerificationReworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.github = FakeGitHub()

    def subject(self):
        verified = SimpleNamespace(pointer=SimpleNamespace(comment_id=7099602476),
                                   contract=SimpleNamespace(sha256=ADC_SHA))
        binding = SimpleNamespace(base_ref="main")
        return SimpleNamespace(
            repository=REPO, repository_id=1401910271, issue_number=79, issue_id=7900,
            labels=tuple(sorted(self.github.labels)), verified_adc=verified,
            binding=binding, binding_sha256=BIND_SHA, binding_generation=1,
            head_sha40=self.github.head, branch_ref="fix/issue79", executor_user_id=3744776,
            issue=self.github.issue(79),
        )

    def run_rework(self):
        with patch("p_ases.verification_rework._live_subject", side_effect=lambda *_a, **_k: self.subject()), \
                patch("p_ases.verification_rework._require_review_not_started"), \
                patch("p_ases.verification_rework._evidence",
                      return_value=("independent_review_A", "e" * 64)):
            return verification_rework(
                self.github, self.root, 79, 80,
                self.root / "review.json", "F-01", "Correct a confirmed ADC violation",
            )

    def test_one_intent_one_label_update_one_applied_then_noop(self):
        applied = self.run_rework()
        self.assertEqual(applied["status"], "APPLIED")
        self.assertEqual(applied["rework_cycle"], 1)
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (2, 1))
        self.assertEqual(self.github.labels, ["kind:single", "phase:execution"])
        records = read_rework_history(self.github, 79)
        self.assertEqual([item.schema for item in records], [INTENT_SCHEMA, APPLIED_SCHEMA])
        self.assertEqual(self.run_rework()["status"], "NOOP")
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (2, 1))

    def test_lost_put_after_apply_is_recovered_with_zero_second_put(self):
        self.github.lost_put = "after"
        result = self.run_rework()
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (2, 1))
        self.assertEqual(self.run_rework()["status"], "NOOP")

    def test_lost_put_before_apply_blocks_but_never_retries(self):
        self.github.lost_put = "before"
        with self.assertRaisesRegex(VerificationReworkError, "ambiguous PUT"):
            self.run_rework()
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (1, 1))
        self.github.lost_put = None
        with self.assertRaisesRegex(VerificationReworkError, "no blind retry"):
            self.run_rework()
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (1, 1))

    def test_recovery_after_successful_put_without_applied(self):
        self.github.lost_put = "before"
        with self.assertRaises(VerificationReworkError):
            self.run_rework()
        self.github.labels = ["kind:single", "phase:execution"]
        self.github.lost_put = None
        recovered = self.run_rework()
        self.assertEqual(recovered["status"], "RECOVERED")
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (2, 1))

    def test_malformed_or_edited_journal_blocks(self):
        self.run_rework()
        self.github.comments[0]["updated_at"] = "2026-11-23T12:02:01Z"
        with self.assertRaisesRegex(VerificationReworkError, "edited"):
            read_rework_history(self.github, 79)

    def test_user_review_session_blocks_before_any_write(self):
        with patch("p_ases.verification_rework._live_subject", side_effect=lambda *_a, **_k: self.subject()), \
                patch("p_ases.verification_rework._require_review_not_started",
                      side_effect=VerificationReworkError("User Review started")), \
                patch("p_ases.verification_rework._evidence",
                      return_value=("independent_review_A", "e" * 64)):
            with self.assertRaisesRegex(VerificationReworkError, "User Review started"):
                verification_rework(
                    self.github, self.root, 79, 80,
                    self.root / "review.json", "F-01", "Fix an ADC violation",
                )
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (0, 0))

    def test_no_progress_rejects_same_head_after_applied(self):
        self.run_rework()
        with self.assertRaisesRegex(VerificationReworkError, "NO_PROGRESS"):
            require_rework_progress(
                self.github, self.root, 79,
                current_head=HEAD, adc_comment_id=7099602476,
            )

    def test_new_descendant_head_clears_no_progress_gate(self):
        self.run_rework()
        with patch("p_ases.verification_rework.is_ancestor", return_value=True):
            require_rework_progress(
                self.github, self.root, 79,
                current_head="f" * 40, adc_comment_id=7099602476,
            )

    def test_wrong_phase_blocks_without_writes(self):
        self.github.labels = ["kind:single", "phase:ready"]
        with self.assertRaisesRegex(VerificationReworkError, "phase:verification"):
            self.run_rework()
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (0, 0))


if __name__ == "__main__":
    unittest.main()
