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
    OWNER_ID,
    REPOSITORY,
    PhaseRebaselineError,
    rebaseline_issue_phase,
)


OLD_SHA = BASELINE_ADC_SHA256
NEW_SHA = "a" * 64
ACTOR_ID = 9001


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
        schema = INTENT_SCHEMA if body.startswith(f"<!-- {INTENT_SCHEMA}\n") else APPLIED_SCHEMA
        if schema == APPLIED_SCHEMA and self.fail_applied_comment_once:
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
