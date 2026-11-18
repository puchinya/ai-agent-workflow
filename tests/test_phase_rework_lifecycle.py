from __future__ import annotations

import copy
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

from p_ases import phase_rework_lifecycle as phase
from p_ases import epoch_lifecycle as epoch
from p_ases.github import GitHubError


class FakeGitHub:
    repo = "owner/repo"

    def __init__(self):
        self.issue_number = 128
        self.owner_id = 440
        self.issue_row = {
            "id": 9876, "number": 128, "state": "open", "pull_request": None,
            "body": "Immutable Issue body",
            "repository_url": f"https://api.github.com/repos/{self.repo}",
            "labels": [{"name": "kind:single"}, {"name": "phase:verification"}],
        }
        self.records = {}
        self.post_count = 0
        self.label_writes = 0
        self.fail_label = False

    def repository_metadata(self):
        return {"id": 556, "full_name": self.repo,
                "owner": {"id": self.owner_id, "type": "User"}}

    def authenticated_user(self):
        return {"id": self.owner_id, "type": "User"}

    def issue(self, number):
        assert number == self.issue_number
        return copy.deepcopy(self.issue_row)

    def branch(self, name):
        assert name == "pases/epoch"
        return {"commit": {"sha": "b" * 40}}

    def pull_request(self, number):
        assert number == 202
        return {
            "number": number, "state": "open", "draft": False,
            "merged": False, "merged_at": None,
            "body": "Review.\n\nCloses #128\n",
            "head": {"ref": "pases/epoch", "sha": "b" * 40,
                     "repo": {"full_name": self.repo}},
            "base": {"ref": "main", "repo": {"full_name": self.repo}},
            "user": {"id": self.owner_id, "type": "User"},
        }

    def create_issue_comment(self, number, body):
        assert number == 128
        self.post_count += 1
        ident = 3000 + self.post_count
        row = {
            "id": ident, "body": body,
            "issue_url": f"https://api.github.com/repos/{self.repo}/issues/128",
            "created_at": "2026-11-18T00:00:00Z",
            "updated_at": "2026-11-18T00:00:00Z",
            "user": {"id": self.owner_id, "type": "User"},
        }
        self.records[ident] = row
        return row

    def issue_comment(self, number, ident):
        assert number == 128
        return copy.deepcopy(self.records[ident])

    def replace_issue_labels(self, number, labels):
        assert number == 128
        self.label_writes += 1
        if self.fail_label:
            raise GitHubError("ambiguous PUT response")
        self.issue_row["labels"] = [{"name": label} for label in labels]


def auth():
    return {
        "schema": phase.AUTH_SCHEMA, "repository": "owner/repo",
        "issue_number": 128, "issue_id": 9876, "owner_id": 440,
        "base_ref": "main", "base_sha40": "a" * 40, "branch_ref": "pases/epoch",
        "pr_number": 202, "pr_head_sha40": "b" * 40,
        "active_epoch_id": "c" * 64, "active_epoch_sha256": "d" * 64,
        "from_phase": "verification", "to_phase": "requirements",
        "labels_before": ["kind:single", "phase:verification"],
        "labels_after": ["kind:single", "phase:requirements"],
        "max_applications": 1,
    }


def verified(authorization=None):
    content = b"No new Phase rework authorized"
    if authorization is not None:
        content = f"Current ADC\n{epoch._record(phase.AUTH_SCHEMA, authorization)}\n".encode()
    return SimpleNamespace(
        pointer=SimpleNamespace(state="approved", comment_id=2300, sha256="e" * 64),
        contract=SimpleNamespace(sha256="e" * 64, content=content),
    )


def readiness():
    subject = SimpleNamespace(
        repository="owner/repo", issue_number=128, pr_number=202,
        pr_head_sha40="b" * 40, adc_comment_id=2300,
        adc_sha256="e" * 64, sha256="3" * 64,
    )
    return SimpleNamespace(status="PASS", subject=subject, sha256="f" * 64)


class GenericPhaseReworkTests(unittest.TestCase):
    @staticmethod
    def _run(root, github, adc, factory=readiness):
        def current(_gh, _root, _issue, _verified=None):
            applies = [
                row for row in github.records.values()
                if row["body"].startswith(f"<!-- {phase.APPLIED_SCHEMA}\n")
            ]
            latest = applies[-1] if applies else None
            return SimpleNamespace(
                origin={"applied_comment_id": 500},
                epoch_id="c" * 64, sha256="d" * 64,
                branch_ref="pases/epoch", base_sha40="a" * 40,
                applied_comment_id=latest["id"] if latest else 500,
                applied_body_sha256=hashlib.sha256(latest["body"].encode()).hexdigest()
                                    if latest else "0" * 64,
            )
        with patch.object(phase, "verify_adc", return_value=adc), \
                patch.object(phase, "read_current_epoch", side_effect=current), \
                patch.object(epoch, "verify_adc", return_value=adc), \
                patch.object(epoch, "current_branch", return_value="pases/epoch"), \
                patch.object(epoch, "head_sha40", return_value="b" * 40), \
                patch.object(epoch, "is_ancestor", return_value=True), \
                patch.object(epoch, "worktree_clean", return_value=True):
            return phase.apply_phase_rework(github, root, 128, readiness_factory=factory)

    def test_generic_one_shot_rework_and_noop_after_new_adc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub()
            adc = verified(auth())
            result = self._run(root, github, adc)
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual((github.post_count, github.label_writes), (2, 1))
            # The current successor ADC need not repeat a retired phase rework marker.
            result = self._run(root, github, verified())
            self.assertEqual(result["status"], "NOOP")
            self.assertEqual(result["writes_performed"], 0)
            self.assertEqual((github.post_count, github.label_writes), (2, 1))

    def test_missing_typed_marker_blocks_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub()
            with self.assertRaisesRegex(phase.PhaseReworkLifecycleError, "typed Phase"):
                self._run(root, github, verified())
            self.assertEqual((github.post_count, github.label_writes), (0, 0))

    def test_readiness_drift_blocks_before_intent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub()
            count = 0
            def changes():
                nonlocal count
                count += 1
                record = readiness()
                if count == 2:
                    record.sha256 = "9" * 64
                return record
            with self.assertRaisesRegex(phase.PhaseReworkLifecycleError, "Readiness changed"):
                self._run(root, github, verified(auth()), changes)
            self.assertEqual((github.post_count, github.label_writes), (0, 0))

    def test_ambiguous_label_update_never_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub()
            github.fail_label = True
            adc = verified(auth())
            with self.assertRaisesRegex(phase.PhaseReworkLifecycleError, "ambiguous"):
                self._run(root, github, adc)
            self.assertEqual((github.post_count, github.label_writes), (1, 1))
            github.fail_label = False
            with self.assertRaisesRegex(phase.PhaseReworkLifecycleError, "already attempted"):
                self._run(root, github, adc)
            self.assertEqual((github.post_count, github.label_writes), (1, 1))

    def test_issue_owner_or_pr_drift_blocks_prior_to_intent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub()
            adc = verified(auth())
            github.owner_id = 999
            with self.assertRaises(phase.PhaseReworkLifecycleError):
                self._run(root, github, adc)
            self.assertEqual((github.post_count, github.label_writes), (0, 0))


if __name__ == "__main__":
    unittest.main()
