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

from p_ases.current_epoch import (
    ATTACHMENT_SCHEMA, ORIGIN_APPLIED, ORIGIN_SCHEMA, REWORK_APPLIED,
    CurrentEpochError, epoch_paths, read_current_epoch,
)


def canonical(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def carrier(schema, fields, number, comment_id, owner=77):
    payload = {"schema": schema, **fields}
    body = f"<!-- {schema}\n" + canonical(payload).decode().strip() + "\n-->"
    return {
        "id": comment_id, "body": body,
        "issue_url": f"https://api.github.com/repos/demo/project/issues/{number}",
        "created_at": "2026-11-18T12:00:00Z",
        "updated_at": "2026-11-18T12:00:00Z",
        "user": {"id": owner, "type": "User", "login": "owner"},
    }


class FakeGitHub:
    repo = "demo/project"

    def __init__(self, origin, latest=None):
        self.origin, self.latest = origin, latest
        self.direct_calls = []
        self.pages = 0

    def repository_metadata(self):
        return {"id": 8, "full_name": self.repo,
                "owner": {"id": 77, "login": "owner", "type": "User"}}

    def issue(self, number):
        return {
            "number": number, "id": 2000 + number, "state": "open",
            "pull_request": None, "comments": 1000000,
            "repository_url": f"https://api.github.com/repos/{self.repo}",
            "labels": [{"name": "kind:single"}, {"name": "phase:requirements"}],
        }

    def branch(self, branch):
        return {"name": branch, "commit": {"sha": "c" * 40}}

    def issue_comment(self, number, comment_id):
        self.direct_calls.append(comment_id)
        candidates = [self.origin, self.latest]
        for item in candidates:
            if item is not None and item["id"] == comment_id:
                return item
        raise AssertionError("unexpected historical carrier request")

    def issue_comment_pages_newest(self, number, total_comments):
        self.pages += 1
        yield [self.latest] if self.latest else []

    def issue_comments(self, number):
        raise AssertionError("full Issue history must not be read")


class CurrentEpochTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.issue = 24
        self.epoch = {
            "schema": ORIGIN_SCHEMA, "repository": "demo/project",
            "issue_number": self.issue, "issue_id": 2000 + self.issue,
            "adc_comment_id": 21, "adc_sha256": "a" * 64,
            "base_ref": "main", "base_sha40": "b" * 40,
            "branch_ref": "feature/issue-24", "epoch_id": "d" * 64,
            "intent_comment_id": 40, "intent_body_sha256": "e" * 64,
            "applied_comment_id": 41, "applied_body_sha256": "",
            "predecessor_epoch_id": "f" * 64,
            "predecessor_epoch_sha256": "1" * 64,
            "historical_binding_provenance": "UNVERIFIED",
            "historical_binding_sha256": "2" * 64,
        }
        self.origin = carrier(ORIGIN_APPLIED, {
            "repository": "demo/project", "issue_number": self.issue,
            "epoch_id": self.epoch["epoch_id"], "adc_comment_id": 21,
            "adc_sha256": "a" * 64,
        }, self.issue, 41)
        self.epoch["applied_body_sha256"] = hashlib.sha256(self.origin["body"].encode()).hexdigest()
        self.epoch["sha256"] = hashlib.sha256(canonical(self.epoch).rstrip(b"\n")).hexdigest()
        self.attachment = {
            "schema": ATTACHMENT_SCHEMA, "repository": "demo/project",
            "issue_number": self.issue, "adc_comment_id": 21, "adc_sha256": "a" * 64,
            "base_ref": "main", "base_sha40": "b" * 40,
            "branch_ref": "feature/issue-24", "epoch_id": self.epoch["epoch_id"],
            "epoch_sha256": self.epoch["sha256"],
            "intent_comment_id": 40, "intent_body_sha256": "e" * 64,
            "applied_comment_id": 41,
            "applied_body_sha256": self.epoch["applied_body_sha256"],
            "work_directory": str(self.root.resolve()),
        }
        self.save()
        self.current_adc = SimpleNamespace(pointer=SimpleNamespace(
            comment_id=77, sha256="8" * 64, state="approved",
        ))

    def save(self):
        epoch, attachment = epoch_paths(self.root, self.issue)
        epoch.parent.mkdir(parents=True, exist_ok=True)
        epoch.write_bytes(canonical(self.epoch))
        attachment.write_bytes(canonical(self.attachment))

    def read(self, github):
        with patch("p_ases.current_epoch.current_branch", return_value="feature/issue-24"), \
                patch("p_ases.current_epoch.head_sha40", return_value="c" * 40), \
                patch("p_ases.current_epoch.is_ancestor", return_value=True):
            return read_current_epoch(github, self.root, self.issue, self.current_adc)

    def test_no_historical_adc_or_full_issue_history_lookup(self):
        github = FakeGitHub(self.origin)
        active = self.read(github)
        self.assertEqual(active.repository, "demo/project")
        self.assertEqual(active.issue_number, 24)
        self.assertEqual(active.adc_comment_id, 77)
        self.assertEqual(active.applied_comment_id, 41)
        self.assertEqual(github.direct_calls, [41])
        self.assertEqual(github.pages, 1)

    def test_newer_phase_applied_is_selected_without_prior_adc_reads(self):
        latest = carrier(REWORK_APPLIED, {
            "repository": "demo/project", "issue_number": 24,
            "active_epoch_id": self.epoch["epoch_id"],
            "active_epoch_sha256": self.epoch["sha256"],
            "branch_ref": self.epoch["branch_ref"],
        }, 24, 68)
        github = FakeGitHub(self.origin, latest)
        active = self.read(github)
        self.assertEqual(active.applied_comment_id, 68)
        self.assertEqual(active.applied_body_sha256,
                         hashlib.sha256(latest["body"].encode()).hexdigest())
        self.assertEqual(github.direct_calls, [41, 68])

    def test_tampered_origin_and_attachment_fail_closed(self):
        github = FakeGitHub(self.origin)
        self.attachment["epoch_sha256"] = "f" * 64
        self.save()
        with self.assertRaisesRegex(CurrentEpochError, "attachment"):
            self.read(github)
        self.attachment["epoch_sha256"] = self.epoch["sha256"]
        self.save()
        github.origin["user"]["id"] = 90
        with self.assertRaisesRegex(CurrentEpochError, "author"):
            self.read(github)

    def test_wrong_issue_or_adc_state_is_rejected(self):
        github = FakeGitHub(self.origin)
        with patch("p_ases.current_epoch.current_branch", return_value="feature/issue-24"):
            with self.assertRaises(CurrentEpochError):
                read_current_epoch(github, self.root, 25, self.current_adc)
        self.current_adc.pointer.state = "draft"
        with self.assertRaisesRegex(CurrentEpochError, "approved"):
            self.read(github)


if __name__ == "__main__":
    unittest.main()
