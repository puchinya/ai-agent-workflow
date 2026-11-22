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

from p_ases.current_epoch import (
    ATTACHMENT_SCHEMA, ORIGIN_APPLIED, ORIGIN_INTENT, ORIGIN_SCHEMA, REWORK_APPLIED, REWORK_INTENT,
    CurrentEpochError, REWORK_TIMESTAMP_MARKER, epoch_paths, read_current_epoch,
    validate_rework_publication_window, _validate_pinned_rework_timestamps,
)


def canonical(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def carrier(schema, fields, number, comment_id, owner=77,
            created_at="2026-11-18T12:00:00Z", updated_at=None):
    payload = {"schema": schema, **fields}
    body = f"<!-- {schema}\n" + canonical(payload).decode().strip() + "\n-->"
    return {
        "id": comment_id, "body": body,
        "issue_url": f"https://api.github.com/repos/demo/project/issues/{number}",
        "created_at": created_at,
        "updated_at": created_at if updated_at is None else updated_at,
        "user": {"id": owner, "type": "User", "login": "owner"},
    }


class FakeGitHub:
    repo = "demo/project"

    def __init__(self, origin, intent, latest=None, phase_intent=None):
        self.origin, self.intent = origin, intent
        self.latest, self.phase_intent = latest, phase_intent
        self.direct_calls = []
        self.pages = 0
        self.comment_pages = None
        self.extra_comments = {}
        self.write_calls = 0

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
        candidates = [self.origin, self.intent, self.latest, self.phase_intent,
                      *self.extra_comments.values()]
        for item in candidates:
            if item is not None and item["id"] == comment_id:
                return item
        raise AssertionError("unexpected historical carrier request")

    def issue_comment_pages_newest(self, number, total_comments):
        assert number == 24 and total_comments == 1000000
        rows = self.comment_pages
        if rows is None:
            comments = [item for item in (self.origin, self.phase_intent, self.latest)
                        if item is not None]
            rows = [sorted(comments, key=lambda item: item["id"])]
        for page in rows:
            self.pages += 1
            yield page

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
            "intent_comment_id": 40, "intent_body_sha256": "",
            "applied_comment_id": 41, "applied_body_sha256": "",
            "predecessor_epoch_id": "f" * 64,
            "predecessor_epoch_sha256": "1" * 64,
            "historical_binding_provenance": "UNVERIFIED",
            "historical_binding_sha256": "2" * 64,
        }
        self.intent = carrier(ORIGIN_INTENT, {
            "repository": "demo/project", "issue_number": self.issue,
            "epoch_id": self.epoch["epoch_id"], "adc_comment_id": 21,
            "adc_sha256": "a" * 64, "base_ref": "main", "base_sha40": "b" * 40,
            "branch_ref": "feature/issue-24",
        }, self.issue, 40)
        self.epoch["intent_body_sha256"] = hashlib.sha256(self.intent["body"].encode()).hexdigest()
        self.origin = carrier(ORIGIN_APPLIED, {
            "repository": "demo/project", "issue_number": self.issue,
            "epoch_id": self.epoch["epoch_id"], "adc_comment_id": 21,
            "adc_sha256": "a" * 64, "base_ref": "main", "base_sha40": "b" * 40,
            "branch_ref": "feature/issue-24",
            "intent_comment_id": 40, "intent_body_sha256": self.epoch["intent_body_sha256"],
        }, self.issue, 41)
        self.epoch["applied_body_sha256"] = hashlib.sha256(self.origin["body"].encode()).hexdigest()
        self.epoch["sha256"] = hashlib.sha256(canonical(self.epoch).rstrip(b"\n")).hexdigest()
        self.attachment = {
            "schema": ATTACHMENT_SCHEMA, "repository": "demo/project",
            "issue_number": self.issue, "adc_comment_id": 21, "adc_sha256": "a" * 64,
            "base_ref": "main", "base_sha40": "b" * 40,
            "branch_ref": "feature/issue-24", "epoch_id": self.epoch["epoch_id"],
            "epoch_sha256": self.epoch["sha256"],
            "intent_comment_id": 40, "intent_body_sha256": self.epoch["intent_body_sha256"],
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
        with patch("p_ases.current_epoch.current_branch", return_value=self.epoch["branch_ref"]), \
                patch("p_ases.current_epoch.head_sha40", return_value="c" * 40), \
                patch("p_ases.current_epoch.is_ancestor", return_value=True):
            return read_current_epoch(github, self.root, self.issue, self.current_adc)

    def _reseal_local_epoch(self):
        payload = dict(self.epoch)
        payload.pop("sha256", None)
        self.epoch["sha256"] = hashlib.sha256(canonical(payload).rstrip(b"\n")).hexdigest()
        self.attachment.update({
            "base_ref": self.epoch["base_ref"],
            "base_sha40": self.epoch["base_sha40"],
            "branch_ref": self.epoch["branch_ref"],
            "epoch_sha256": self.epoch["sha256"],
            "intent_body_sha256": self.epoch["intent_body_sha256"],
            "applied_body_sha256": self.epoch["applied_body_sha256"],
        })
        self.save()

    def test_immutable_applied_pins_each_base_and_branch_identity_field(self):
        original_epoch = copy.deepcopy(self.epoch)
        original_attachment = copy.deepcopy(self.attachment)
        expected_fields = {
            "base_ref": "main", "base_sha40": "b" * 40,
            "branch_ref": "feature/issue-24",
        }
        invalid_values = {"base_ref": 7, "base_sha40": 7, "branch_ref": ["feature/other"]}
        for field in expected_fields:
            for mutation in ("mismatch", "missing"):
                with self.subTest(field=field, mutation=mutation):
                    self.epoch = copy.deepcopy(original_epoch)
                    self.attachment = copy.deepcopy(original_attachment)
                    payload = {
                        "repository": "demo/project", "issue_number": self.issue,
                        "epoch_id": self.epoch["epoch_id"], "adc_comment_id": 21,
                        "adc_sha256": "a" * 64, **expected_fields,
                        "intent_comment_id": self.epoch["intent_comment_id"],
                        "intent_body_sha256": self.epoch["intent_body_sha256"],
                    }
                    if mutation == "mismatch":
                        payload[field] = invalid_values[field]
                    else:
                        payload.pop(field)
                    mismatched_applied = carrier(ORIGIN_APPLIED, payload, self.issue, 41)
                    self.epoch["applied_body_sha256"] = hashlib.sha256(
                        mismatched_applied["body"].encode(),
                    ).hexdigest()
                    self._reseal_local_epoch()
                    github = FakeGitHub(mismatched_applied, self.intent)
                    with self.assertRaisesRegex(CurrentEpochError, "origin Applied does not match"):
                        self.read(github)

    def test_immutable_intent_pins_each_base_and_branch_identity_field(self):
        original_epoch = copy.deepcopy(self.epoch)
        original_attachment = copy.deepcopy(self.attachment)
        local_fields = {
            "base_ref": "main", "base_sha40": "b" * 40,
            "branch_ref": "feature/issue-24",
        }
        invalid_values = {"base_ref": 7, "base_sha40": 7, "branch_ref": ["feature/other"]}
        for field in local_fields:
            for mutation in ("mismatch", "missing"):
                with self.subTest(field=field, mutation=mutation):
                    self.epoch = copy.deepcopy(original_epoch)
                    self.attachment = copy.deepcopy(original_attachment)
                    intent_payload = {
                        "repository": "demo/project", "issue_number": self.issue,
                        "epoch_id": self.epoch["epoch_id"], "adc_comment_id": 21,
                        "adc_sha256": "a" * 64, **local_fields,
                    }
                    if mutation == "mismatch":
                        intent_payload[field] = invalid_values[field]
                    else:
                        intent_payload.pop(field)
                    mismatched_intent = carrier(ORIGIN_INTENT, intent_payload, self.issue, 40)
                    intent_sha = hashlib.sha256(mismatched_intent["body"].encode()).hexdigest()
                    applied_payload = {
                        "repository": "demo/project", "issue_number": self.issue,
                        "epoch_id": self.epoch["epoch_id"], "adc_comment_id": 21,
                        "adc_sha256": "a" * 64, **local_fields,
                        "intent_comment_id": 40, "intent_body_sha256": intent_sha,
                    }
                    matching_applied = carrier(ORIGIN_APPLIED, applied_payload, self.issue, 41)
                    self.epoch["intent_body_sha256"] = intent_sha
                    self.epoch["applied_body_sha256"] = hashlib.sha256(
                        matching_applied["body"].encode(),
                    ).hexdigest()
                    self._reseal_local_epoch()
                    github = FakeGitHub(matching_applied, mismatched_intent)
                    with self.assertRaisesRegex(CurrentEpochError, "origin Intent does not match"):
                        self.read(github)

    def test_no_historical_adc_or_full_issue_history_lookup(self):
        github = FakeGitHub(self.origin, self.intent)
        active = self.read(github)
        self.assertEqual(active.repository, "demo/project")
        self.assertEqual(active.issue_number, 24)
        self.assertEqual(active.adc_comment_id, 77)
        self.assertEqual(active.applied_comment_id, 41)
        self.assertEqual(github.direct_calls, [41, 40])
        self.assertEqual(github.pages, 1)

    def test_stops_at_epoch_origin_without_scanning_historical_phase_records(self):
        old_applied = carrier(REWORK_APPLIED, {
            "repository": "demo/project", "issue_number": 24,
            "active_epoch_id": "f" * 64,
            "active_epoch_sha256": "a" * 64,
        }, self.issue, 35)
        github = FakeGitHub(self.origin, self.intent)
        github.comment_pages = [
            [{"id": 90, "body": "Newer unrelated comment"}],
            [old_applied, self.origin],
            [{"id": 20, "body": "Historical ADC, must not be read"}],
        ]
        active = self.read(github)
        self.assertEqual(active.applied_comment_id, 41)
        self.assertEqual(github.direct_calls, [41, 40])
        self.assertEqual(github.pages, 2)

    def test_missing_epoch_origin_in_newest_pages_fails_closed(self):
        github = FakeGitHub(self.origin, self.intent)
        github.comment_pages = [[{"id": 90, "body": "Unrelated comment"}]]
        with self.assertRaisesRegex(CurrentEpochError, "origin was not found"):
            self.read(github)
        self.assertEqual(github.direct_calls, [41, 40])

    def test_changed_comment_count_blocks_stale_generation(self):
        github = FakeGitHub(self.origin, self.intent)
        original_issue = github.issue
        calls = 0

        def changing_issue(number):
            nonlocal calls
            calls += 1
            row = original_issue(number)
            if calls > 1:
                row["comments"] += 1
            return row

        github.issue = changing_issue
        with self.assertRaisesRegex(CurrentEpochError, "comment count changed"):
            self.read(github)
        self.assertEqual(github.direct_calls, [41, 40])
        self.assertEqual(github.pages, 1)

    def test_newer_phase_applied_is_selected_without_prior_adc_reads(self):
        phase_intent = carrier(REWORK_INTENT, {
            "repository": "demo/project", "issue_number": 24,
            "active_epoch_id": self.epoch["epoch_id"],
            "active_epoch_sha256": self.epoch["sha256"],
            "branch_ref": self.epoch["branch_ref"],
            "adc_comment_id": 77, "adc_sha256": "8" * 64,
            "created_at": "2026-11-18T12:00:00Z",
        }, 24, 67)
        phase_sha = hashlib.sha256(phase_intent["body"].encode()).hexdigest()
        latest = carrier(REWORK_APPLIED, {
            "repository": "demo/project", "issue_number": 24,
            "active_epoch_id": self.epoch["epoch_id"],
            "active_epoch_sha256": self.epoch["sha256"],
            "branch_ref": self.epoch["branch_ref"],
            "adc_comment_id": 77, "adc_sha256": "8" * 64,
            "intent_comment_id": 67, "intent_body_sha256": phase_sha,
            "applied_at": "2026-11-18T12:00:00Z",
        }, 24, 68)
        github = FakeGitHub(self.origin, self.intent, latest, phase_intent)
        active = self.read(github)
        self.assertEqual(active.applied_comment_id, 68)
        self.assertEqual(active.applied_body_sha256,
                         hashlib.sha256(latest["body"].encode()).hexdigest())
        self.assertEqual(github.direct_calls, [41, 40, 68, 67])

    def _phase_pair(self, intent_id=67, applied_id=68, *, intent_fields=None, applied_fields=None,
                    intent_owner=77, applied_owner=77):
        intent_payload = {
            "repository": "demo/project", "issue_number": self.issue,
            "active_epoch_id": self.epoch["epoch_id"],
            "active_epoch_sha256": self.epoch["sha256"],
            "branch_ref": self.epoch["branch_ref"],
            "adc_comment_id": 77, "adc_sha256": "8" * 64,
            "created_at": "2026-11-18T12:00:00Z",
        }
        intent_payload.update(intent_fields or {})
        intent = carrier(REWORK_INTENT, intent_payload, self.issue, intent_id, owner=intent_owner)
        intent_sha = hashlib.sha256(intent["body"].encode()).hexdigest()
        applied_payload = {
            "repository": "demo/project", "issue_number": self.issue,
            "active_epoch_id": self.epoch["epoch_id"],
            "active_epoch_sha256": self.epoch["sha256"],
            "branch_ref": self.epoch["branch_ref"],
            "adc_comment_id": 77, "adc_sha256": "8" * 64,
            "intent_comment_id": intent_id, "intent_body_sha256": intent_sha,
            "applied_at": "2026-11-18T12:00:00Z",
        }
        applied_payload.update(applied_fields or {})
        applied = carrier(REWORK_APPLIED, applied_payload, self.issue, applied_id, owner=applied_owner)
        return intent, applied

    def test_unmatched_and_duplicate_post_origin_rework_blocks(self):
        intent, applied = self._phase_pair()
        newer_intent, _ = self._phase_pair(intent_id=69, applied_id=70)
        duplicate_applied = carrier(REWORK_APPLIED, {
            "repository": "demo/project", "issue_number": self.issue,
            "active_epoch_id": self.epoch["epoch_id"],
            "active_epoch_sha256": self.epoch["sha256"],
            "branch_ref": self.epoch["branch_ref"],
            "adc_comment_id": 77, "adc_sha256": "8" * 64,
            "intent_comment_id": 67,
            "intent_body_sha256": hashlib.sha256(intent["body"].encode()).hexdigest(),
            "applied_at": "2026-11-18T12:00:00Z",
        }, self.issue, 71)
        malformed_intent = copy.deepcopy(intent)
        malformed_intent["id"] = 72
        malformed_intent["body"] = malformed_intent["body"].replace(
            f"<!-- {REWORK_INTENT}\n", "<!-- PASES-ISSUE-VERIFICATION-REWORK-INTENT-V3\n", 1,
        )
        for comments in (
            [self.origin, intent],
            [self.origin, intent, applied, newer_intent],
            [self.origin, intent, applied, duplicate_applied],
            [self.origin, malformed_intent],
        ):
            with self.subTest(ids=[row["id"] for row in comments]):
                github = FakeGitHub(self.origin, self.intent)
                github.extra_comments = {row["id"]: row for row in comments if row is not self.origin}
                github.comment_pages = [comments]
                with self.assertRaises(CurrentEpochError):
                    self.read(github)
                self.assertEqual(github.write_calls, 0)

    def test_wrong_epoch_branch_owner_and_order_block_rework(self):
        cases = []
        cases.append(self._phase_pair(intent_fields={"active_epoch_id": "f" * 64}))
        cases.append(self._phase_pair(intent_fields={"branch_ref": "other"}))
        cases.append(self._phase_pair(intent_owner=78))
        intent, applied = self._phase_pair(intent_id=69, applied_id=68)
        cases.append((intent, applied))
        for intent, applied in cases:
            comments = sorted([self.origin, intent, applied], key=lambda row: row["id"])
            github = FakeGitHub(self.origin, self.intent)
            github.extra_comments = {intent["id"]: intent, applied["id"]: applied}
            github.comment_pages = [comments]
            with self.subTest(ids=(intent["id"], applied["id"])):
                with self.assertRaises(CurrentEpochError):
                    self.read(github)
                self.assertEqual(github.write_calls, 0)

    def test_publication_window_boundaries_for_v2_v3_event_fields(self):
        for event_field in ("created_at", "applied_at"):
            for delta, accepted in ((0, True), (300, True), (-1, False), (301, False)):
                event = "2026-11-18T12:00:00Z"
                # Use datetime arithmetic for values crossing the minute boundary.
                from datetime import datetime, timedelta, timezone
                event_dt = datetime.strptime(event, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                server = (event_dt + timedelta(seconds=delta)).strftime("%Y-%m-%dT%H:%M:%SZ")
                payload = {event_field: event}
                row = {"created_at": server, "updated_at": server}
                for schema in ("V2", "V3"):
                    with self.subTest(schema=schema, field=event_field, delta=delta):
                        if accepted:
                            validate_rework_publication_window(payload, row, event_field)
                        else:
                            with self.assertRaises(CurrentEpochError):
                                validate_rework_publication_window(payload, row, event_field)
            for event in (None, "2026-11-18T12:00:00+00:00", "2026-11-18 12:00:00Z"):
                with self.subTest(field=event_field, event=event):
                    row = {"created_at": "2026-11-18T12:00:00Z", "updated_at": "2026-11-18T12:00:00Z"}
                    with self.assertRaises(CurrentEpochError):
                        validate_rework_publication_window({event_field: event}, row, event_field)

    def test_current_adc_timestamp_marker_reads_only_direct_v2_v3_comments(self):
        from datetime import datetime, timedelta
        schemas = (
            ("PASES_ISSUE_VERIFICATION_REWORK_INTENT_V2", "created_at", 101, 0, False),
            ("PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V2", "applied_at", 102, 300, False),
            (REWORK_INTENT, "created_at", 103, 0, True),
            (REWORK_APPLIED, "applied_at", 104, 300, True),
        )
        base = datetime.strptime("2026-11-18T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ")
        references = []
        rows = {}
        for schema, event_field, ident, delta, detailed in schemas:
            event = base.strftime("%Y-%m-%dT%H:%M:%SZ")
            published = (base + timedelta(seconds=delta)).strftime("%Y-%m-%dT%H:%M:%SZ")
            row = carrier(schema, {
                "repository": "demo/project", "issue_number": self.issue,
                event_field: event,
            }, self.issue, ident, created_at=published)
            rows[ident] = row
            reference = {"comment_id": ident,
                         "body_sha256": hashlib.sha256(row["body"].encode()).hexdigest()}
            if detailed:
                reference.update({
                    "schema": schema, "body_byte_length": len(row["body"].encode()),
                    "comment_created_at": published, "event_time": event,
                    "event_to_publication_delta_seconds": delta,
                })
            references.append(reference)
        marker = {
            "schema": REWORK_TIMESTAMP_MARKER,
            "timestamp_policy": {
                "schema": "PASES_ISSUE_PHASE_EVENT_PUBLICATION_WINDOW_V1",
                "applies_to": [row[0] for row in schemas],
                "intent_event_field": "created_at", "applied_event_field": "applied_at",
                "minimum_skew_seconds": 0, "max_skew_seconds": 300,
            },
            "phase_rework_origin": {
                "prior_v2_intent": references[0], "prior_v2_applied": references[1],
                "intent": references[2], "applied": references[3],
            },
        }
        content = (f"<!-- {REWORK_TIMESTAMP_MARKER}\n".encode()
                   + canonical(marker).rstrip(b"\n") + b"\n-->")
        verified = SimpleNamespace(contract=SimpleNamespace(content=content))
        github = FakeGitHub(self.origin, self.intent)
        github.extra_comments = rows
        self.assertEqual(_validate_pinned_rework_timestamps(github, self.issue, verified, 77),
                         ({101, 102, 103, 104}, {103, 104}))
        self.assertEqual(github.direct_calls, [101, 102, 103, 104])

    def test_phase_evidence_and_restart_wrappers_block_invalid_epoch(self):
        from p_ases.phase_evidence import PhaseEvidenceError, _active_phase_generation_subject
        from p_ases.phase_restart import PhaseRestartError, current_phase_generation
        github = FakeGitHub(self.origin, self.intent)
        with patch("p_ases.current_epoch.read_current_epoch",
                   side_effect=CurrentEpochError("unmatched post-origin Intent")):
            with self.assertRaisesRegex(PhaseRestartError, "unmatched post-origin Intent"):
                current_phase_generation(github, self.root, self.issue, self.current_adc)
            with self.assertRaisesRegex(PhaseEvidenceError, "active Phase generation is invalid"):
                _active_phase_generation_subject(github, self.root, self.issue, self.current_adc)
        self.assertEqual(github.write_calls, 0)

    def test_ordinary_issue_advance_blocks_before_label_write_on_invalid_epoch(self):
        from p_ases.cli import CLIError, _advance_issue_with_adc_session
        from types import SimpleNamespace

        class CountingGitHub:
            def __init__(self):
                self.label_writes = 0
            def issue(self, number):
                return {"number": number, "state": "open", "pull_request": None,
                        "body": "Issue body", "repository_url": "https://api.github.com/repos/demo/project",
                        "labels": [{"name": "kind:single"}, {"name": "phase:requirements"}]}
            def replace_issue_labels(self, number, labels):
                self.label_writes += 1

        github = CountingGitHub()
        args = SimpleNamespace(issue=24, kind="single", target="specification", root="/tmp/repo",
                               skip_phase=[], phase_evidence_comment_id=None)
        with patch("p_ases.cli._repo_root", return_value=self.root),                 patch("p_ases.cli.verify_ordinary_issue_context",
                      side_effect=CLIError("active epoch has an unmatched Intent")):
            with self.assertRaisesRegex(CLIError, "unmatched Intent"):
                _advance_issue_with_adc_session(args, "demo/project", github)
        self.assertEqual(github.label_writes, 0)

    def test_modified_origin_intent_is_detected_by_direct_digest(self):
        github = FakeGitHub(self.origin, self.intent)
        github.intent["body"] += "modified"
        with self.assertRaisesRegex(CurrentEpochError, "digest|schema"):
            self.read(github)
        self.assertEqual(github.direct_calls, [41, 40])
        self.assertEqual(github.pages, 0)

    def test_modified_current_phase_intent_is_detected(self):
        phase_intent = carrier(REWORK_INTENT, {
            "repository": "demo/project", "issue_number": self.issue,
            "active_epoch_id": self.epoch["epoch_id"],
            "active_epoch_sha256": self.epoch["sha256"],
            "branch_ref": self.epoch["branch_ref"],
            "adc_comment_id": 77, "adc_sha256": "8" * 64,
            "created_at": "2026-11-18T12:00:00Z",
        }, self.issue, 67)
        latest = carrier(REWORK_APPLIED, {
            "repository": "demo/project", "issue_number": self.issue,
            "active_epoch_id": self.epoch["epoch_id"],
            "active_epoch_sha256": self.epoch["sha256"],
            "branch_ref": self.epoch["branch_ref"],
            "adc_comment_id": 77, "adc_sha256": "8" * 64,
            "intent_comment_id": 67, "intent_body_sha256": "f" * 64,
            "applied_at": "2026-11-18T12:00:00Z",
        }, self.issue, 68)
        phase_payload = json.loads(phase_intent["body"].split("\n", 1)[1].removesuffix("\n-->"))
        phase_payload["edited"] = True
        phase_intent["body"] = (f"<!-- {REWORK_INTENT}\n" + canonical(phase_payload).decode().strip()
                                 + "\n-->")
        github = FakeGitHub(self.origin, self.intent, latest, phase_intent)
        with self.assertRaisesRegex(CurrentEpochError, "digest"):
            self.read(github)
        self.assertEqual(github.direct_calls, [41, 40, 68, 67])

    def test_tampered_origin_and_attachment_fail_closed(self):
        github = FakeGitHub(self.origin, self.intent)
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
        github = FakeGitHub(self.origin, self.intent)
        with patch("p_ases.current_epoch.current_branch", return_value="feature/issue-24"):
            with self.assertRaises(CurrentEpochError):
                read_current_epoch(github, self.root, 25, self.current_adc)
        self.current_adc.pointer.state = "draft"
        with self.assertRaisesRegex(CurrentEpochError, "approved"):
            self.read(github)


if __name__ == "__main__":
    unittest.main()
