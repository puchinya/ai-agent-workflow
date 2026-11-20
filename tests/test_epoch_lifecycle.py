from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import epoch_lifecycle as module
from p_ases.github import GitHubError


class FakeGitHub:
    repo = "owner/repo"

    def __init__(self, issue_number=128):
        self.issue_number = issue_number
        self.owner_id = 440
        self.issue_row = {
            "id": 9876, "number": issue_number,
            "state": "open", "pull_request": None, "body": "Immutable Issue body",
            "repository_url": f"https://api.github.com/repos/{self.repo}",
            "labels": [{"name": "kind:single"}, {"name": "phase:ready"}],
        }
        self.records = {900: {"id": 900, "body": "current approved ADC pointer"}}
        self.pages_read = 0
        self.label_writes = 0
        self.post_count = 0
        self.fail_label = False
        self.branch_ref = "pases/epoch"
        self.head = "b" * 40

    def repository_metadata(self):
        return {"id": 556, "full_name": self.repo,
                "owner": {"id": self.owner_id, "type": "User"}}

    def authenticated_user(self):
        return {"id": self.owner_id, "type": "User"}

    def issue(self, issue_number):
        assert issue_number == self.issue_number
        row = copy.deepcopy(self.issue_row)
        row["comments"] = len(self.records)
        return row

    def branch(self, branch_ref):
        assert branch_ref == self.branch_ref
        return {"commit": {"sha": self.head}}

    def create_issue_comment(self, issue_number, body):
        assert issue_number == self.issue_number
        self.post_count += 1
        record_id = 1000 + self.post_count
        record = {
            "id": record_id, "body": body,
            "issue_url": f"https://api.github.com/repos/{self.repo}/issues/{issue_number}",
            "created_at": "2026-11-18T00:00:00Z", "updated_at": "2026-11-18T00:00:00Z",
            "user": {"id": self.owner_id, "type": "User"},
        }
        self.records[record_id] = record
        return record

    def issue_comments(self, issue_number):
        raise AssertionError("full Issue history must not be materialized")

    def issue_comment_pages_newest(self, issue_number, total_comments):
        assert issue_number == self.issue_number
        assert total_comments == len(self.records)
        records = sorted(self.records.values(), key=lambda row: row["id"])
        for end in range(len(records), 0, -100):
            self.pages_read += 1
            yield copy.deepcopy(records[max(0, end - 100):end])

    def issue_comment(self, issue_number, comment_id):
        assert issue_number == self.issue_number
        return copy.deepcopy(self.records[comment_id])

    def replace_issue_labels(self, issue_number, labels):
        assert issue_number == self.issue_number
        self.label_writes += 1
        if self.fail_label:
            raise GitHubError("simulated ambiguous PUT")
        self.issue_row["labels"] = [{"name": label} for label in labels]


def authorization(issue_number=128):
    return {
        "schema": module.AUTH_SCHEMA, "repository": "owner/repo",
        "issue_number": issue_number, "issue_id": 9876, "owner_id": 440,
        "base_ref": "main", "base_sha40": "a" * 40, "branch_ref": "pases/epoch",
        "from_phase": "ready", "to_phase": "requirements",
        "labels_before": ["kind:single", "phase:ready"],
        "labels_after": ["kind:single", "phase:requirements"],
        "historical_binding_provenance": "UNVERIFIED",
        "historical_binding_sha256": None, "predecessor_epoch_id": None,
        "predecessor_epoch_sha256": None, "max_applications": 1,
    }


def verified_adc(auth):
    raw = f"Current authorized contract\n{module._record(module.AUTH_SCHEMA, auth)}\n".encode()
    return SimpleNamespace(
        pointer=SimpleNamespace(state="approved", comment_id=900, sha256="d" * 64),
        contract=SimpleNamespace(content=raw, sha256="d" * 64),
    )


class EpochLifecycleTests(unittest.TestCase):
    @staticmethod
    def _run(root, github, adc):
        def active(_github, _root, issue, _verified=None):
            origin_path, attachment_path = module.epoch_paths(root, issue)
            if not attachment_path.is_file():
                raise module.CurrentEpochError("missing epoch attachment")
            origin = json.loads(origin_path.read_bytes())
            return SimpleNamespace(epoch_id=origin["epoch_id"],
                                   applied_comment_id=origin["applied_comment_id"])
        with patch.object(module, "verify_adc", return_value=adc), \
                patch.object(module, "read_current_epoch", side_effect=active), \
                patch.object(module, "current_branch", return_value="pases/epoch"), \
                patch.object(module, "head_sha40", return_value="b" * 40), \
                patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "worktree_clean", return_value=True):
            return module.reset_execution_epoch(github, root, github.issue_number)

    def test_new_epoch_is_generic_append_only_and_exact_retry_is_noop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub(128)
            adc = verified_adc(authorization(128))
            first = self._run(root, github, adc)
            self.assertEqual(first["status"], "APPLIED")
            self.assertEqual(first["writes_performed"], 3)
            self.assertEqual((github.post_count, github.label_writes), (2, 1))
            origin_path, attachment_path = module.epoch_paths(root, 128)
            origin_bytes, attachment_bytes = origin_path.read_bytes(), attachment_path.read_bytes()
            origin = json.loads(origin_bytes)
            self.assertEqual(origin["issue_number"], 128)
            self.assertEqual(origin["historical_binding_provenance"], "UNVERIFIED")
            self.assertEqual(json.loads(attachment_bytes)["epoch_sha256"], origin["sha256"])
            second = self._run(root, github, adc)
            self.assertEqual(second["status"], "NOOP")
            self.assertEqual(second["writes_performed"], 0)
            self.assertEqual((github.post_count, github.label_writes), (2, 1))
            self.assertEqual(origin_path.read_bytes(), origin_bytes)
            self.assertEqual(attachment_path.read_bytes(), attachment_bytes)

    def test_no_marker_or_wrong_issue_prevents_all_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            for adc in (
                verified_adc(authorization(129)),
                SimpleNamespace(pointer=SimpleNamespace(state="approved",
                                    comment_id=1, sha256="d" * 64),
                                contract=SimpleNamespace(content=b"No typed authorization",
                                                         sha256="d" * 64)),
            ):
                with self.assertRaises(module.EpochLifecycleError):
                    self._run(root, github, adc)
            self.assertEqual((github.post_count, github.label_writes), (0, 0))
            self.assertFalse(module.epoch_paths(root, 128)[0].exists())

    def test_multi_kind_or_attention_authorization_blocks_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            invalid_labels = (
                (["kind:parent", "kind:single", "phase:ready"],
                 ["kind:parent", "kind:single", "phase:requirements"]),
                (["attention:blocked", "kind:single", "phase:ready"],
                 ["attention:blocked", "kind:single", "phase:requirements"]),
            )
            for before, after in invalid_labels:
                with self.subTest(before=before):
                    auth = authorization(128)
                    auth["labels_before"] = before
                    auth["labels_after"] = after
                    with self.assertRaisesRegex(
                            module.EpochLifecycleError, "invalid exact label sets"):
                        self._run(root, github, verified_adc(auth))
            self.assertEqual((github.post_count, github.label_writes), (0, 0))

    def test_partial_label_failure_is_one_shot_and_never_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            github.fail_label = True
            adc = verified_adc(authorization(128))
            with self.assertRaisesRegex(module.EpochLifecycleError, "ambiguous"):
                self._run(root, github, adc)
            self.assertEqual((github.post_count, github.label_writes), (1, 1))
            github.fail_label = False
            with self.assertRaisesRegex(module.EpochLifecycleError, "remote epoch reset journal already exists"):
                self._run(root, github, adc)
            self.assertEqual((github.post_count, github.label_writes), (1, 1))

    def test_issue_body_drift_before_intent_blocks_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            original_issue = github.issue
            reads = 0

            def changed_issue(number):
                nonlocal reads
                reads += 1
                result = original_issue(number)
                if reads >= 2:
                    result["body"] = "Changed after first subject read"
                return result

            github.issue = changed_issue
            with self.assertRaisesRegex(module.EpochLifecycleError, "Issue body changed before Intent"):
                self._run(root, github, verified_adc(authorization(128)))
            self.assertEqual((github.post_count, github.label_writes), (0, 0))

    def test_issue_body_drift_during_remote_journal_scan_blocks_intent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            original = github.issue_comment_pages_newest

            def changed_history(number, total_comments):
                for page in original(number, total_comments):
                    github.issue_row["body"] = "Changed during remote journal scan"
                    yield page

            github.issue_comment_pages_newest = changed_history
            with self.assertRaisesRegex(module.EpochLifecycleError, "Issue body changed before Intent"):
                self._run(root, github, verified_adc(authorization(128)))
            self.assertEqual((github.post_count, github.label_writes), (0, 0))

    def test_epoch_reset_streams_every_page_without_materializing_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            for ident in range(100, 335):
                github.records[ident] = {"id": ident, "body": "historical ADC or Issue comment"}
            result = self._run(root, github, verified_adc(authorization(128)))
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(github.pages_read, 3)
            self.assertEqual((github.post_count, github.label_writes), (2, 1))

    def test_epoch_reset_detects_old_pending_intent_across_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            for ident in range(100, 335):
                github.records[ident] = {"id": ident, "body": "historical unrelated comment"}
            github.records[105]["body"] = f"<!-- {module.INTENT_SCHEMA}\npending"
            with self.assertRaisesRegex(module.EpochLifecycleError,
                                        "remote epoch reset journal already exists"):
                self._run(root, github, verified_adc(authorization(128)))
            self.assertEqual(github.pages_read, 3)
            self.assertEqual((github.post_count, github.label_writes), (0, 0))

    def test_epoch_reset_concurrent_comment_change_blocks_before_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            original = github.issue_comment_pages_newest

            def changed_history(number, total_comments):
                for page in original(number, total_comments):
                    yield page
                github.records[950] = {"id": 950, "body": "concurrent comment"}

            github.issue_comment_pages_newest = changed_history
            with self.assertRaisesRegex(module.EpochLifecycleError,
                                        "Issue comments changed during journal preflight"):
                self._run(root, github, verified_adc(authorization(128)))
            self.assertEqual((github.post_count, github.label_writes), (0, 0))

    def test_owner_and_issue_drift_block_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            adc = verified_adc(authorization(128))
            github.owner_id = 999
            with self.assertRaisesRegex(module.EpochLifecycleError, "live ADC"):
                self._run(root, github, adc)
            self.assertEqual((github.post_count, github.label_writes), (0, 0))

    def test_existing_epoch_with_missing_attachment_blocks_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, github = Path(temporary), FakeGitHub(128)
            path, _ = module.epoch_paths(root, 128)
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            with self.assertRaisesRegex(module.EpochLifecycleError, "existing epoch"):
                self._run(root, github, verified_adc(authorization(128)))
            self.assertEqual((github.post_count, github.label_writes), (0, 0))


if __name__ == "__main__":
    unittest.main()
