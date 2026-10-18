from __future__ import annotations

import hashlib
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import ADCPointer, parse_adc  # noqa: E402
from p_ases.github import GitHubError  # noqa: E402
from p_ases import phase_rebaseline as phase_module  # noqa: E402
from p_ases.phase_rebaseline import (  # noqa: E402
    APPLIED_SCHEMA,
    BASELINE_ADC_COMMENT_ID,
    BASELINE_ADC_SHA256,
    INTENT_SCHEMA,
    INTENT_V2_SCHEMA,
    APPLIED_V2_SCHEMA,
    OWNER_ID,
    REPOSITORY,
    PhaseRebaselineError,
    rebaseline_issue_phase,
)


OLD_SHA = BASELINE_ADC_SHA256
NEW_SHA = "a" * 64
ACTOR_ID = 9001
PREVIOUS_ADC_COMMENT_ID = 6236636013
PREVIOUS_ADC_SHA256 = "59714ca55da1a524f0874a9bcfc57c62493cb03af5a2fcc8382901e7abce3135"
CURRENT_ADC_COMMENT_ID = 6244160653
CURRENT_ADC_SHA256 = "f1cab9b9edca34d4e80c486642059881b62abd5d95b993999a52494494bafac8"


def verified(comment_id: int, sha256: str, state: str = "approved") -> SimpleNamespace:
    pointer = ADCPointer(comment_id, sha256, 100, state)
    authority = ("REQ-F01-015 automatic phase rebaseline automatic #63 Phase Intent/Applied path "
                 "`PHASE_REBASE` decisionは要求せず、必須のIntent/Applied技術記録を残す")
    return SimpleNamespace(pointer=pointer, contract=SimpleNamespace(
        sha256=sha256, content=authority.encode("utf-8"), requirement_ids=("REQ-F01-015",)))


def canonical_body(schema: str, payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"<!-- {schema}\n{data}\n-->"


class FakeGitHub:
    repo = REPOSITORY

    def __init__(self, labels: list[str] | None = None):
        self.labels = list(labels or ["enhancement", "phase:ready", "kind:single"])
        self.issue_body = "unchanged Issue body"
        self.comments: list[dict] = []
        self.calls: list[tuple[str, object]] = []
        self.next_comment_id = 6228771900
        self.lose_label_response = False
        self.deny_label_permission = False
        self.fail_applied_comment_once = False
        self.bad_direct: dict[int, dict] = {}

    def authenticated_user(self) -> dict:
        return {"id": ACTOR_ID, "login": "workflow-executor", "type": "User"}

    def repository_metadata(self) -> dict:
        return {"id": 1401910271, "full_name": REPOSITORY,
                "default_branch": "main",
                "owner": {"id": OWNER_ID, "login": "puchinya", "type": "User"}}

    def issue(self, number: int) -> dict:
        self.calls.append(("issue", number))
        return {"number": number, "state": "open",
                "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
                "pull_request": None, "body": self.issue_body,
                "labels": [{"name": name} for name in self.labels]}

    def issue_comments(self, number: int) -> list[dict]:
        self.calls.append(("issue_comments", number))
        return list(self.comments)

    def issue_comment(self, number: int, comment_id: int) -> dict:
        self.calls.append(("issue_comment", (number, comment_id)))
        if comment_id in self.bad_direct:
            return self.bad_direct[comment_id]
        return next(row for row in self.comments if row["id"] == comment_id)

    def create_issue_comment(self, number: int, body: str) -> dict:
        schema = body.split("\n", 1)[0][5:]
        is_applied = schema in {APPLIED_SCHEMA, APPLIED_V2_SCHEMA}
        if is_applied and self.fail_applied_comment_once:
            self.fail_applied_comment_once = False
            raise GitHubError("simulated response interruption")
        comment_id = self.next_comment_id
        self.next_comment_id += 1
        row = {
            "id": comment_id, "body": body,
            "created_at": f"2026-10-17T09:{comment_id % 60:02d}:00Z",
            "updated_at": f"2026-10-17T09:{comment_id % 60:02d}:00Z",
            "user": {"id": ACTOR_ID, "login": "workflow-executor", "type": "User"},
            "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/63",
            "html_url": f"https://github.com/{REPOSITORY}/issues/63#issuecomment-{comment_id}",
        }
        self.comments.append(row)
        return row

    def add_record(self, comment_id: int, schema: str, payload: dict) -> dict:
        row = {
            "id": comment_id, "body": canonical_body(schema, payload),
            "created_at": "2026-10-17T09:00:00Z", "updated_at": "2026-10-17T09:00:00Z",
            "user": {"id": ACTOR_ID, "login": "workflow-executor", "type": "User"},
            "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/63",
            "html_url": f"https://github.com/{REPOSITORY}/issues/63#issuecomment-{comment_id}",
        }
        self.comments.append(row)
        return row

    def replace_issue_labels(self, number: int, labels: list[str]) -> list[dict]:
        self.calls.append(("replace_issue_labels", list(labels)))
        if self.deny_label_permission:
            raise GitHubError("simulated missing label permission", status_code=403)
        self.labels = list(labels)
        if self.lose_label_response:
            self.lose_label_response = False
            raise GitHubError("simulated lost PUT response")
        return [{"name": name} for name in labels]


class PhaseRebaselineTests(unittest.TestCase):
    def call(self, github: FakeGitHub):
        current = verified(6228771810, NEW_SHA)
        predecessor = verified(BASELINE_ADC_COMMENT_ID, OLD_SHA)
        with ExitStack() as stack:
            stack.enter_context(patch.object(phase_module, "verify_adc", return_value=current))
            stack.enter_context(patch.object(phase_module, "verify_adc_generation", return_value=predecessor))
            stack.enter_context(patch.object(
                phase_module, "verify_adc_forward_generations", return_value=(predecessor, current)))
            return rebaseline_issue_phase(github, 63)

    def add_historical_v1_pair(self, github: FakeGitHub) -> tuple[dict, dict]:
        chain = (verified(BASELINE_ADC_COMMENT_ID, BASELINE_ADC_SHA256),
                 verified(PREVIOUS_ADC_COMMENT_ID, PREVIOUS_ADC_SHA256))
        before = sorted(["enhancement", "phase:ready", "kind:single"])
        after = sorted(["enhancement", "phase:requirements", "kind:single"])
        intent_payload = phase_module._intent_v1_payload(
            chain[0], chain[1], github.issue_body, before, after, ACTOR_ID,
        )
        intent = github.add_record(6236687874, INTENT_SCHEMA, intent_payload)
        applied_payload = {
            "schema": phase_module.APPLIED_SCHEMA, "repository": REPOSITORY, "issue_number": 63,
            "intent_comment_id": intent["id"],
            "intent_sha256": hashlib.sha256(json.dumps(
                intent_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            ).encode()).hexdigest(),
            "predecessor_adc_comment_id": chain[0].pointer.comment_id,
            "predecessor_adc_sha256": chain[0].pointer.sha256,
            "successor_adc_comment_id": chain[1].pointer.comment_id,
            "successor_adc_sha256": chain[1].pointer.sha256,
            "from_phase": "ready", "to_phase": "requirements", "labels_after": after,
            "executor_user_id": ACTOR_ID,
        }
        applied = github.add_record(6236700004, phase_module.APPLIED_SCHEMA, applied_payload)
        github.next_comment_id = CURRENT_ADC_COMMENT_ID + 10
        return intent, applied

    def call_successor(self, github: FakeGitHub, *generations: SimpleNamespace):
        chain = generations or (
            verified(BASELINE_ADC_COMMENT_ID, BASELINE_ADC_SHA256),
            verified(PREVIOUS_ADC_COMMENT_ID, PREVIOUS_ADC_SHA256),
            verified(CURRENT_ADC_COMMENT_ID, CURRENT_ADC_SHA256),
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(phase_module, "verify_adc", return_value=chain[-1]))
            stack.enter_context(patch.object(phase_module, "verify_adc_generation", return_value=chain[0]))
            stack.enter_context(patch.object(
                phase_module, "verify_adc_forward_generations", return_value=chain))
            return rebaseline_issue_phase(github, 63)

    def test_approved_adc_bootstraps_without_phase_decision_and_preserves_all_other_labels(self):
        github = FakeGitHub(["enhancement", "phase:ready", "kind:single", "attention:review"])

        result = self.call(github)

        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(github.labels, sorted(["enhancement", "phase:requirements", "kind:single", "attention:review"]))
        self.assertEqual(sum(call[0] == "replace_issue_labels" for call in github.calls), 1)
        schemas = [row["body"].split("\n", 1)[0][5:] for row in github.comments]
        self.assertEqual(schemas, [INTENT_SCHEMA, APPLIED_SCHEMA])
        self.assertGreaterEqual(sum(call[0] == "issue_comments" for call in github.calls), 4)

    def test_published_successor_adc_authority_matches_phase_executor(self):
        github = FakeGitHub()
        github.next_comment_id = 6228771900
        raw = (ROOT / "docs/contracts/issue-63-successor-adc-draft.md").read_bytes()
        successor = SimpleNamespace(
            pointer=ADCPointer(6228771810, hashlib.sha256(raw).hexdigest(), len(raw), "approved"),
            contract=parse_adc(raw, REPOSITORY, 63),
        )
        predecessor = verified(BASELINE_ADC_COMMENT_ID, OLD_SHA)
        with patch.object(phase_module, "verify_adc", return_value=successor), \
                patch.object(phase_module, "verify_adc_generation", return_value=predecessor), \
                patch.object(phase_module, "verify_adc_forward_generations",
                             return_value=(predecessor, successor)):
            result = rebaseline_issue_phase(github, 63)

        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(github.labels, ["enhancement", "kind:single", "phase:requirements"])
        self.assertEqual([row["body"].split("\n", 1)[0][5:] for row in github.comments],
                         [INTENT_SCHEMA, APPLIED_SCHEMA])

    def test_completed_bootstrap_is_noop(self):
        github = FakeGitHub()
        self.call(github)
        calls_before = len(github.calls)

        result = self.call(github)

        self.assertEqual(result["status"], "NOOP")
        self.assertEqual(sum(call[0] == "replace_issue_labels" for call in github.calls), 1)
        self.assertGreater(len(github.calls), calls_before)

    def test_lost_put_response_finishes_without_second_put(self):
        github = FakeGitHub()
        github.lose_label_response = True

        result = self.call(github)

        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(sum(call[0] == "replace_issue_labels" for call in github.calls), 1)
        self.assertEqual(github.labels, sorted(["enhancement", "phase:requirements", "kind:single"]))

    def test_process_interruption_after_put_recovers_applied_record_without_second_put(self):
        github = FakeGitHub()
        github.fail_applied_comment_once = True
        with self.assertRaises(PhaseRebaselineError):
            self.call(github)
        self.assertEqual(sum(call[0] == "replace_issue_labels" for call in github.calls), 1)
        self.assertEqual(len(github.comments), 1)

        result = self.call(github)

        self.assertEqual(result["status"], "RECOVERED")
        self.assertEqual(sum(call[0] == "replace_issue_labels" for call in github.calls), 1)
        self.assertEqual(len(github.comments), 2)

    def test_successor_adc_adds_v2_receipts_without_rewriting_requirements_labels(self):
        github = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        _old_intent, old_applied = self.add_historical_v1_pair(github)

        result = self.call_successor(github)

        self.assertEqual(result["status"], "RECORDED")
        self.assertEqual(result["phase_action"], "ADOPT_EXISTING_REQUIREMENTS")
        self.assertEqual(result["label_writes"], 0)
        self.assertEqual(github.labels, ["enhancement", "phase:requirements", "kind:single"])
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))
        intent, applied = github.comments[-2:]
        intent_payload = json.loads(intent["body"].split("\n", 1)[1][:-3])
        applied_payload = json.loads(applied["body"].split("\n", 1)[1][:-3])
        self.assertTrue(intent["body"].startswith(f"<!-- {INTENT_V2_SCHEMA}\n"))
        self.assertTrue(applied["body"].startswith(f"<!-- {APPLIED_V2_SCHEMA}\n"))
        self.assertEqual(intent_payload["predecessor_adc_comment_id"], PREVIOUS_ADC_COMMENT_ID)
        self.assertEqual(intent_payload["successor_adc_comment_id"], CURRENT_ADC_COMMENT_ID)
        self.assertEqual(intent_payload["previous_applied_comment_id"], old_applied["id"])
        self.assertEqual(intent_payload["previous_applied_payload_sha256"],
                         hashlib.sha256(json.dumps(
                             json.loads(old_applied["body"].split("\n", 1)[1][:-3]),
                             sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                         ).encode()).hexdigest())
        self.assertEqual(intent_payload["operation"], "adopt_existing_requirements")
        self.assertEqual(intent_payload["from_phase"], "requirements")
        self.assertEqual(intent_payload["to_phase"], "requirements")
        self.assertEqual(intent_payload["labels_before"], intent_payload["labels_after"])
        self.assertEqual(applied_payload["intent_comment_id"], intent["id"])
        self.assertEqual(applied_payload["previous_applied_comment_id"], old_applied["id"])

        first_comment_count = len(github.comments)
        noop = self.call_successor(github)
        self.assertEqual(noop["status"], "NOOP")
        self.assertEqual(len(github.comments), first_comment_count)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

    def test_successive_v2_adc_generations_link_previous_applied_and_preserve_v1_bytes(self):
        github = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        old_intent, old_applied = self.add_historical_v1_pair(github)
        v1_bytes = (old_intent["body"], old_applied["body"])
        first_chain = (
            verified(BASELINE_ADC_COMMENT_ID, BASELINE_ADC_SHA256),
            verified(PREVIOUS_ADC_COMMENT_ID, PREVIOUS_ADC_SHA256),
            verified(CURRENT_ADC_COMMENT_ID, CURRENT_ADC_SHA256),
        )
        first = self.call_successor(github, *first_chain)
        first_applied = github.comments[-1]
        first_v2_bytes = tuple(row["body"] for row in github.comments[-2:])

        next_adc = verified(6250000000, "b" * 64)
        github.next_comment_id = next_adc.pointer.comment_id + 10
        second = self.call_successor(github, *first_chain, next_adc)

        self.assertEqual(first["status"], "RECORDED")
        self.assertEqual(second["status"], "RECORDED")
        second_intent = json.loads(github.comments[-2]["body"].split("\n", 1)[1][:-3])
        self.assertEqual(second_intent["predecessor_adc_comment_id"], CURRENT_ADC_COMMENT_ID)
        self.assertEqual(second_intent["successor_adc_comment_id"], next_adc.pointer.comment_id)
        self.assertEqual(second_intent["previous_applied_comment_id"], first_applied["id"])
        self.assertEqual(second_intent["previous_applied_payload_sha256"], hashlib.sha256(
            json.dumps(json.loads(first_applied["body"].split("\n", 1)[1][:-3]),
                       sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest())
        self.assertEqual(tuple(row["body"] for row in github.comments[:2]), v1_bytes)
        self.assertEqual(tuple(row["body"] for row in github.comments[2:4]), first_v2_bytes)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

    def test_v2_generation_skip_or_wrong_previous_applied_digest_blocks_without_writes(self):
        skipped = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        self.add_historical_v1_pair(skipped)
        chain4 = (
            verified(BASELINE_ADC_COMMENT_ID, BASELINE_ADC_SHA256),
            verified(PREVIOUS_ADC_COMMENT_ID, PREVIOUS_ADC_SHA256),
            verified(CURRENT_ADC_COMMENT_ID, CURRENT_ADC_SHA256),
            verified(6250000000, "b" * 64),
        )
        with self.assertRaisesRegex(PhaseRebaselineError, "skips one or more completed Phase receipts"):
            self.call_successor(skipped, *chain4)
        self.assertEqual(len(skipped.comments), 2)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in skipped.calls))

        tampered = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        _intent, previous_applied = self.add_historical_v1_pair(tampered)
        payload = phase_module._intent_v2_payload(
            verified(PREVIOUS_ADC_COMMENT_ID, PREVIOUS_ADC_SHA256),
            verified(CURRENT_ADC_COMMENT_ID, CURRENT_ADC_SHA256),
            phase_module._record_from_row(previous_applied, phase_module.APPLIED_SCHEMA),
            tampered.issue_body, tampered.labels, ACTOR_ID,
        )
        payload["previous_applied_payload_sha256"] = "0" * 64
        tampered.add_record(CURRENT_ADC_COMMENT_ID + 1, INTENT_V2_SCHEMA, payload)
        tampered.next_comment_id = CURRENT_ADC_COMMENT_ID + 10
        with self.assertRaisesRegex(PhaseRebaselineError, "ADC/history generation"):
            self.call_successor(tampered)
        self.assertEqual(len(tampered.comments), 3)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in tampered.calls))

    def test_interrupted_v2_application_recovers_with_readback_only_and_zero_label_writes(self):
        github = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        self.add_historical_v1_pair(github)
        github.fail_applied_comment_once = True

        with self.assertRaises(PhaseRebaselineError):
            self.call_successor(github)
        self.assertEqual(len(github.comments), 3)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

        recovered = self.call_successor(github)

        self.assertEqual(recovered["status"], "RECOVERED")
        self.assertEqual(len(github.comments), 4)
        self.assertTrue(github.comments[-1]["body"].startswith(f"<!-- {APPLIED_V2_SCHEMA}\n"))
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

    def test_v2_issue_body_or_label_drift_blocks_recovery_without_appending_or_writing_labels(self):
        github = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        self.add_historical_v1_pair(github)
        github.fail_applied_comment_once = True
        with self.assertRaises(PhaseRebaselineError):
            self.call_successor(github)
        before = len(github.comments)
        github.issue_body += " changed"

        with self.assertRaisesRegex(PhaseRebaselineError, "current Issue|labels"):
            self.call_successor(github)
        self.assertEqual(len(github.comments), before)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

        labels_changed = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        self.add_historical_v1_pair(labels_changed)
        labels_changed.fail_applied_comment_once = True
        with self.assertRaises(PhaseRebaselineError):
            self.call_successor(labels_changed)
        before = len(labels_changed.comments)
        labels_changed.labels.append("attention:review")
        with self.assertRaisesRegex(PhaseRebaselineError, "current Issue|labels"):
            self.call_successor(labels_changed)
        self.assertEqual(len(labels_changed.comments), before)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in labels_changed.calls))

    def test_duplicate_or_wrong_issue_v2_carriers_fail_direct_list_direct_readback(self):
        duplicated = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        self.add_historical_v1_pair(duplicated)
        self.call_successor(duplicated)
        intent = duplicated.comments[-2]
        duplicate_id = duplicated.comments[-1]["id"] + 1
        duplicated.add_record(duplicate_id, INTENT_V2_SCHEMA,
                              json.loads(intent["body"].split("\n", 1)[1][:-3]))
        duplicated.next_comment_id = duplicate_id + 1
        with self.assertRaisesRegex(PhaseRebaselineError, "duplicate"):
            self.call_successor(duplicated)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in duplicated.calls))

        wrong_issue = FakeGitHub(["enhancement", "phase:requirements", "kind:single"])
        self.add_historical_v1_pair(wrong_issue)
        self.call_successor(wrong_issue)
        intent_id = wrong_issue.comments[-2]["id"]
        wrong_issue.bad_direct[intent_id] = {
            **wrong_issue.comments[-2],
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/62",
        }
        before = len(wrong_issue.comments)
        with self.assertRaisesRegex(PhaseRebaselineError, "different repository or Issue|changed during"):
            self.call_successor(wrong_issue)
        self.assertEqual(len(wrong_issue.comments), before)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in wrong_issue.calls))

    def test_existing_intent_with_old_labels_blocks_without_second_put(self):
        github = FakeGitHub()
        before = sorted(github.labels)
        after = sorted([name for name in before if name != "phase:ready"] + ["phase:requirements"])
        predecessor, successor = verified(BASELINE_ADC_COMMENT_ID, OLD_SHA), verified(6228771810, NEW_SHA)
        body_digest = __import__("hashlib").sha256(github.issue_body.encode()).hexdigest()
        payload = {
            "schema": INTENT_SCHEMA, "repository": REPOSITORY, "issue_number": 63,
            "predecessor_adc_comment_id": predecessor.pointer.comment_id,
            "predecessor_adc_sha256": predecessor.pointer.sha256,
            "successor_adc_comment_id": successor.pointer.comment_id,
            "successor_adc_sha256": successor.pointer.sha256,
            "from_phase": "ready", "to_phase": "requirements",
            "labels_before": before, "labels_after": after,
            "issue_body_sha256": body_digest,
            "executor_user_id": ACTOR_ID,
        }
        github.create_issue_comment(63, canonical_body(INTENT_SCHEMA, payload))

        with self.assertRaisesRegex(PhaseRebaselineError, "refusing a second PUT"):
            self.call(github)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

    def test_unapproved_or_stale_successor_blocks_before_intent_and_put(self):
        github = FakeGitHub()
        stale = verified(6228771810, NEW_SHA, state="draft")
        with patch.object(phase_module, "verify_adc", return_value=stale), \
                patch.object(phase_module, "verify_adc_generation", return_value=verified(BASELINE_ADC_COMMENT_ID, OLD_SHA)), \
                patch.object(phase_module, "verify_adc_forward_generations", return_value=()):
            with self.assertRaisesRegex(PhaseRebaselineError, "not approved"):
                rebaseline_issue_phase(github, 63)
        self.assertFalse(github.comments)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

    def test_approved_pointer_without_phase_authority_in_successor_adc_blocks(self):
        github = FakeGitHub()
        current = SimpleNamespace(
            pointer=ADCPointer(6228771810, NEW_SHA, 100, "approved"),
            contract=SimpleNamespace(content=b"REQ-F01-015 but no phase-bootstrap authority",
                                     requirement_ids=("REQ-F01-015",)),
        )
        predecessor = verified(BASELINE_ADC_COMMENT_ID, OLD_SHA)
        with patch.object(phase_module, "verify_adc", return_value=current), \
                patch.object(phase_module, "verify_adc_generation", return_value=predecessor), \
                patch.object(phase_module, "verify_adc_forward_generations", return_value=(predecessor, current)):
            with self.assertRaisesRegex(PhaseRebaselineError, "does not contain the exact phase-bootstrap authority"):
                rebaseline_issue_phase(github, 63)
        self.assertFalse(github.comments)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

    def test_missing_github_write_permission_is_reported_without_requesting_phase_approval(self):
        github = FakeGitHub()
        github.deny_label_permission = True

        with self.assertRaisesRegex(PhaseRebaselineError, "BLOCKED_PERMISSION"):
            self.call(github)

        self.assertEqual(sum(call[0] == "replace_issue_labels" for call in github.calls), 1)
        self.assertEqual(len(github.comments), 1)
        self.assertEqual(github.labels, ["enhancement", "phase:ready", "kind:single"])

    def test_duplicate_records_and_wrong_issue_source_url_block(self):
        github = FakeGitHub()
        self.call(github)
        duplicate_id = github.comments[0]["id"] + 2
        github.comments.append({**github.comments[0], "id": duplicate_id,
                                "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{duplicate_id}",
                                "html_url": f"https://github.com/{REPOSITORY}/issues/63#issuecomment-{duplicate_id}"})
        with self.assertRaisesRegex(PhaseRebaselineError, "duplicate"):
            self.call(github)

        duplicated_applied = FakeGitHub()
        self.call(duplicated_applied)
        applied = duplicated_applied.comments[1]
        applied_id = duplicated_applied.next_comment_id
        duplicated_applied.comments.append({
            **applied, "id": applied_id,
            "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{applied_id}",
            "html_url": f"https://github.com/{REPOSITORY}/issues/63#issuecomment-{applied_id}",
        })
        with self.assertRaisesRegex(PhaseRebaselineError, "duplicate"):
            self.call(duplicated_applied)

        other = FakeGitHub()
        self.call(other)
        comment_id = other.comments[0]["id"]
        other.bad_direct[comment_id] = {**other.comments[0],
                                        "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/62"}
        with self.assertRaisesRegex(PhaseRebaselineError, "different repository or Issue|changed during"):
            self.call(other)

        wrong_repo = FakeGitHub()
        self.call(wrong_repo)
        comment_id = wrong_repo.comments[0]["id"]
        wrong_repo.bad_direct[comment_id] = {**wrong_repo.comments[0],
                                             "url": f"https://api.github.com/repos/other/repo/issues/comments/{comment_id}"}
        with self.assertRaisesRegex(PhaseRebaselineError, "different repository or Issue|changed during"):
            self.call(wrong_repo)

        wrong_actor = FakeGitHub()
        self.call(wrong_actor)
        comment_id = wrong_actor.comments[0]["id"]
        wrong_actor.bad_direct[comment_id] = {**wrong_actor.comments[0],
                                              "user": {"id": ACTOR_ID + 1, "login": "other", "type": "User"}}
        with self.assertRaisesRegex(PhaseRebaselineError, "changed during"):
            self.call(wrong_actor)

    def test_wrong_repository_owner_and_non_bootstrap_labels_block(self):
        github = FakeGitHub()
        with patch.object(github, "repository_metadata", return_value={
            "id": 999, "full_name": "somewhere/else", "owner": {"id": 1, "type": "User"}}):
            with self.assertRaisesRegex(PhaseRebaselineError, "identity changed"):
                self.call(github)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

        wrong = FakeGitHub(["phase:design", "kind:single"])
        with self.assertRaisesRegex(PhaseRebaselineError, "exact phase:ready"):
            self.call(wrong)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in wrong.calls))

        wrong_kind = FakeGitHub(["phase:ready", "kind:single", "kind:child"])
        with self.assertRaisesRegex(PhaseRebaselineError, "exact phase:ready"):
            self.call(wrong_kind)
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in wrong_kind.calls))


if __name__ == "__main__":
    unittest.main()
