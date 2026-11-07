from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import ADC, ADCPointer, VerifiedADC
from p_ases.execution import ExecutionBinding, binding_digest, write_binding
from p_ases.github import GitHubError
from p_ases.phase_restart import (
    APPLIED_SCHEMA,
    AUTH_SCHEMA,
    INTENT_SCHEMA,
    _History,
    _active_generation_before,
    PhaseRestartError,
    RestartAuthorization,
    RestartRecord,
    _parse_payload,
    current_phase_generation,
    parse_authorization,
    restart_issue_phase,
)
from p_ases.work import execution_binding_path


def authorization_bytes(*, target: str = "self", from_phase: str = "execution",
                        to_phase: str = "requirements", max_applications: int = 1,
                        reason: str = "Reopen requirements for the approved successor") -> bytes:
    payload = {
        "schema": AUTH_SCHEMA,
        "target_issue": target,
        "from_phase": from_phase,
        "to_phase": to_phase,
        "max_applications": max_applications,
        "reason": reason,
    }
    compact = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return ("# ADC\n\n<!-- " + AUTH_SCHEMA + "\n" + compact + "\n-->\n").encode()


class FakeGitHub:
    def __init__(self, *, issue_number: int, issue_id: int, labels: list[str], branch: str, head: str,
                 repository: str = "puchinya/ai-agent-workflow", repository_id: int = 1401910271):
        self.repo = repository
        self.repository_id = repository_id
        self.branch_name = branch
        self.head = head
        self.issue_row = {
            "number": issue_number,
            "id": issue_id,
            "state": "open",
            "pull_request": None,
            "repository_url": f"https://api.github.com/repos/{repository}",
            "body": "Issue body stays fixed",
            "labels": [{"name": label} for label in labels],
        }
        self.comments: list[dict[str, object]] = []
        self.next_id = 100
        self.label_writes = 0
        self.fail_label_before_apply = False
        self.fail_label_after_apply = False
        self.fail_applied_post_after_apply = False
        self.duplicate_next_intent = False
        self.tamper_direct = False
        self.omit_second_history_snapshot = False
        self.history_reads = 0
        self.issue_reads = 0
        self.race_on_third_issue_read = False

    def repository_metadata(self):
        return {"id": self.repository_id, "full_name": self.repo, "default_branch": "main"}

    def issue(self, number: int):
        self.issue_reads += 1
        if self.race_on_third_issue_read and self.issue_reads == 3:
            self.issue_row["labels"] = [
                {"name": label} for label in ("enhancement", "kind:single", "phase:requirements")
            ]
        return json.loads(json.dumps(self.issue_row))

    def branch(self, branch: str):
        return {"name": branch, "commit": {"sha": self.head}}

    def authenticated_user(self):
        return {"id": 77, "login": "owner", "type": "User"}

    def issue_comments(self, number: int):
        self.history_reads += 1
        rows = json.loads(json.dumps(self.comments))
        if self.omit_second_history_snapshot and self.history_reads == 3:
            return []
        return rows

    def issue_comment(self, number: int, comment_id: int):
        row = next((item for item in self.comments if item["id"] == comment_id), None)
        if row is None:
            raise GitHubError("comment is absent")
        result = json.loads(json.dumps(row))
        if self.tamper_direct:
            result["updated_at"] = "2026-11-07T00:00:01Z"
            self.tamper_direct = False
        return result

    def create_issue_comment(self, number: int, body: str):
        comment_id = self.next_id
        self.next_id += 1
        now = f"2026-11-07T00:00:{comment_id % 60:02d}Z"
        row = {
            "id": comment_id,
            "body": body,
            "created_at": now,
            "updated_at": now,
            "issue_url": f"https://api.github.com/repos/{self.repo}/issues/{number}",
            "html_url": f"https://github.com/{self.repo}/issues/{number}#issuecomment-{comment_id}",
            "url": f"https://api.github.com/repos/{self.repo}/issues/comments/{comment_id}",
            "user": {"id": 77, "login": "owner", "type": "User"},
        }
        self.comments.append(row)
        if self.duplicate_next_intent and body.startswith(f"<!-- {INTENT_SCHEMA}\n"):
            self.duplicate_next_intent = False
            duplicate = json.loads(json.dumps(row))
            duplicate["id"] = self.next_id
            duplicate["url"] = f"https://api.github.com/repos/{self.repo}/issues/comments/{self.next_id}"
            duplicate["html_url"] = f"https://github.com/{self.repo}/issues/{number}#issuecomment-{self.next_id}"
            duplicate["created_at"] = f"2026-11-07T00:00:{self.next_id % 60:02d}Z"
            duplicate["updated_at"] = duplicate["created_at"]
            self.next_id += 1
            self.comments.append(duplicate)
        if self.fail_applied_post_after_apply and body.startswith(f"<!-- {APPLIED_SCHEMA}\n"):
            self.fail_applied_post_after_apply = False
            raise GitHubError("lost Applied POST response")
        return {"id": comment_id}

    def replace_issue_labels(self, number: int, labels: list[str]):
        self.label_writes += 1
        if self.fail_label_before_apply:
            self.fail_label_before_apply = False
            raise GitHubError("lost label PUT response before server apply")
        self.issue_row["labels"] = [{"name": label} for label in labels]
        if self.fail_label_after_apply:
            self.fail_label_after_apply = False
            raise GitHubError("lost label PUT response after server apply")
        return self.issue_row["labels"]


class PhaseRestartTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-b", "main"], cwd=self.root, check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Phase Test"], cwd=self.root, check=True)
        (self.root / "README.md").write_text("phase test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.root, check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-b", "feature/issue-40"], cwd=self.root, check=True,
                       capture_output=True, text=True)
        self.head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, check=True,
                                   capture_output=True, text=True).stdout.strip()
        self.issue_number = 40
        self.adc_content = authorization_bytes()
        self.adc_sha = hashlib.sha256(self.adc_content).hexdigest()
        self.verified = VerifiedADC(
            ADC("puchinya/ai-agent-workflow", self.issue_number, self.adc_content, self.adc_sha,
                len(self.adc_content), (), ("REQ-F01-031",)),
            ADCPointer(50, self.adc_sha, len(self.adc_content), "approved"),
        )
        self.binding = ExecutionBinding(
            "puchinya/ai-agent-workflow", self.issue_number, 50, self.adc_sha,
            "main", self.head, "feature/issue-40", str(self.root.resolve()), self.head,
        )
        write_binding(execution_binding_path(self.root, self.issue_number), self.binding)
        self.github = FakeGitHub(
            issue_number=self.issue_number, issue_id=4040,
            labels=["enhancement", "kind:single", "phase:execution"],
            branch="feature/issue-40", head=self.head,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def run_restart(self):
        with patch("p_ases.phase_restart.verify_adc", return_value=self.verified), \
                patch("p_ases.phase_restart.verify_adc_generation", return_value=self.verified):
            return restart_issue_phase(self.github, self.root, self.issue_number)

    def test_authorization_accepts_one_canonical_unfenced_marker(self):
        parsed = parse_authorization(self.adc_content, self.issue_number)
        self.assertIsInstance(parsed, RestartAuthorization)
        self.assertEqual(parsed.target_issue, "self")
        self.assertEqual(parsed.from_phase, "execution")
        self.assertEqual(parsed.to_phase, "requirements")
        self.assertEqual(parsed.max_applications, 1)
        self.assertEqual(parsed.sha256, hashlib.sha256(
            json.dumps({"schema": AUTH_SCHEMA, "target_issue": "self", "from_phase": "execution",
                        "to_phase": "requirements", "max_applications": 1,
                        "reason": "Reopen requirements for the approved successor"},
                       sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def test_authorization_rejects_missing_fenced_duplicate_noncanonical_and_bad_scope(self):
        with self.assertRaises(PhaseRestartError):
            parse_authorization(b"# ADC\nPASES_PHASE_RESTART_AUTHORIZATION_V1\n", self.issue_number)
        fenced = b"```\n" + self.adc_content + b"```\n"
        with self.assertRaises(PhaseRestartError):
            parse_authorization(fenced, self.issue_number)
        with self.assertRaises(PhaseRestartError):
            parse_authorization(self.adc_content + self.adc_content, self.issue_number)
        indented = self.adc_content.replace(b'{"from_phase"', b'{\n  "from_phase"')
        with self.assertRaises(PhaseRestartError):
            parse_authorization(indented, self.issue_number)
        with self.assertRaises(PhaseRestartError):
            parse_authorization(authorization_bytes(target="40"), self.issue_number)
        with self.assertRaises(PhaseRestartError):
            parse_authorization(authorization_bytes(max_applications=True), self.issue_number)
        with self.assertRaises(PhaseRestartError):
            parse_authorization(authorization_bytes(reason="invalid\nreason"), self.issue_number)
        with self.assertRaises(PhaseRestartError):
            parse_authorization(b"\xff", self.issue_number)

    def test_record_parser_rejects_unknown_fields_and_noncanonical_payload(self):
        with self.assertRaises(PhaseRestartError):
            _parse_payload(f"<!-- {INTENT_SCHEMA}\n{{}}\n-->", INTENT_SCHEMA)
        with self.assertRaises(PhaseRestartError):
            _parse_payload(f"<!-- {APPLIED_SCHEMA}\n{{}}\n-->", APPLIED_SCHEMA)

    def test_latest_phase_decision_supersedes_an_older_restart_applied_record(self):
        applied = RestartRecord(100, APPLIED_SCHEMA, {}, "applied", 77, "2026-11-07T00:00:00Z")
        decision_body = "PASES_PHASE_DECISION_V1\\n{}\\n"
        history = _History((applied,), ((120, object(), decision_body, 77),))
        self.assertEqual(
            _active_generation_before(history),
            (120, hashlib.sha256(decision_body.encode()).hexdigest()),
        )
        self.assertEqual(_active_generation_before(history, 115), (100, applied.body_sha256))

    def test_valid_restart_writes_one_intent_one_label_update_and_one_applied(self):
        result = self.run_restart()
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(result["label_write_count"], 1)
        self.assertEqual(self.github.label_writes, 1)
        self.assertEqual([row["body"].splitlines()[0] for row in self.github.comments], [
            f"<!-- {INTENT_SCHEMA}", f"<!-- {APPLIED_SCHEMA}",
        ])
        self.assertEqual(
            {row["name"] for row in self.github.issue_row["labels"]},
            {"enhancement", "kind:single", "phase:requirements"},
        )
        with patch("p_ases.phase_restart.verify_adc", return_value=self.verified), \
                patch("p_ases.phase_restart.verify_adc_generation", return_value=self.verified):
            generation = current_phase_generation(self.github, self.root, self.issue_number, self.verified)
        self.assertEqual(generation.comment_id, result["applied_comment_id"])
        self.assertEqual(generation.sha256, result["phase_generation_sha256"])

    def test_exact_replay_is_noop_and_does_not_repeat_label_write(self):
        self.run_restart()
        replay = self.run_restart()
        self.assertEqual(replay["status"], "NOOP")
        self.assertEqual(replay["label_write_count"], 0)
        self.assertEqual(self.github.label_writes, 1)
        self.assertEqual(len(self.github.comments), 2)

    def test_competing_intent_publication_blocks_before_label_write(self):
        self.github.duplicate_next_intent = True
        with self.assertRaisesRegex(PhaseRestartError, "unique exact readback"):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 0)
        self.assertEqual(len(self.github.comments), 2)

    def test_lost_label_response_after_apply_recovers_without_second_put(self):
        self.github.fail_label_after_apply = True
        result = self.run_restart()
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(self.github.label_writes, 1)
        self.assertEqual(len(self.github.comments), 2)

    def test_lost_label_response_before_apply_is_never_retried(self):
        self.github.fail_label_before_apply = True
        with self.assertRaisesRegex(PhaseRestartError, "not repeated"):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 1)
        self.assertEqual(len(self.github.comments), 1)
        with self.assertRaisesRegex(PhaseRestartError, "will not be retried"):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 1)

    def test_lost_applied_post_response_recovers_by_exact_readback(self):
        self.github.fail_applied_post_after_apply = True
        result = self.run_restart()
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(self.github.label_writes, 1)
        self.assertEqual(len(self.github.comments), 2)

    def test_pending_intent_from_superseded_adc_blocks_new_generation(self):
        self.github.fail_label_before_apply = True
        with self.assertRaisesRegex(PhaseRestartError, "not repeated"):
            self.run_restart()

        old_verified = self.verified
        content = authorization_bytes(reason="Successor authorization after interrupted attempt")
        digest = hashlib.sha256(content).hexdigest()
        successor = VerifiedADC(
            ADC("puchinya/ai-agent-workflow", self.issue_number, content, digest, len(content), (),
                ("REQ-F01-031",)),
            ADCPointer(51, digest, len(content), "approved"),
        )
        self.verified = successor
        successor_binding = ExecutionBinding(
            self.binding.repository, self.binding.issue_number, 51, digest,
            self.binding.base_ref, self.binding.base_sha, self.binding.branch_ref,
            self.binding.work_directory, self.binding.initial_head_sha,
        )
        write_binding(execution_binding_path(self.root, self.issue_number), successor_binding)
        verify_generation = lambda _github, _issue, comment_id, _sha, state: (
            old_verified if comment_id == 50 else successor
        )
        with patch("p_ases.phase_restart.verify_adc", return_value=successor), \
                patch("p_ases.phase_restart.verify_adc_generation", side_effect=verify_generation):
            with self.assertRaisesRegex(PhaseRestartError, "prior-ADC"):
                restart_issue_phase(self.github, self.root, self.issue_number)
            with self.assertRaisesRegex(PhaseRestartError, "prior-ADC"):
                current_phase_generation(self.github, self.root, self.issue_number, successor)
        self.assertEqual(self.github.label_writes, 1)
        self.assertEqual(len(self.github.comments), 1)

    def test_prior_completed_restart_does_not_require_marker_in_later_adc(self):
        self.run_restart()
        content = b"# Later approved ADC without Phase restart authorization\n"
        digest = hashlib.sha256(content).hexdigest()
        successor = VerifiedADC(
            ADC("puchinya/ai-agent-workflow", self.issue_number, content, digest, len(content), (),
                ("REQ-F01-031",)),
            ADCPointer(51, digest, len(content), "approved"),
        )
        successor_binding = ExecutionBinding(
            self.binding.repository, self.binding.issue_number, 51, digest,
            self.binding.base_ref, self.binding.base_sha, self.binding.branch_ref,
            self.binding.work_directory, self.binding.initial_head_sha,
        )
        write_binding(execution_binding_path(self.root, self.issue_number), successor_binding)
        with patch("p_ases.phase_restart.verify_adc_generation", return_value=self.verified):
            generation = current_phase_generation(self.github, self.root, self.issue_number, successor)
        self.assertIsNone(generation)

    def test_current_adc_without_marker_cannot_restart(self):
        content = b"# ADC without Phase restart authorization\n"
        digest = hashlib.sha256(content).hexdigest()
        successor = VerifiedADC(
            ADC("puchinya/ai-agent-workflow", self.issue_number, content, digest, len(content), (),
                ("REQ-F01-031",)),
            ADCPointer(51, digest, len(content), "approved"),
        )
        successor_binding = ExecutionBinding(
            self.binding.repository, self.binding.issue_number, 51, digest,
            self.binding.base_ref, self.binding.base_sha, self.binding.branch_ref,
            self.binding.work_directory, self.binding.initial_head_sha,
        )
        write_binding(execution_binding_path(self.root, self.issue_number), successor_binding)
        with patch("p_ases.phase_restart.verify_adc", return_value=successor):
            with self.assertRaisesRegex(PhaseRestartError, "exactly one authorization marker"):
                restart_issue_phase(self.github, self.root, self.issue_number)
        self.assertEqual(self.github.label_writes, 0)
        self.assertEqual(self.github.comments, [])

    def test_issue_label_race_after_intent_blocks_before_label_put(self):
        self.github.race_on_third_issue_read = True
        with self.assertRaisesRegex(PhaseRestartError, "changed immediately before"):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 0)
        self.assertEqual(len(self.github.comments), 1)

    def test_comment_tampering_or_partial_history_blocks_before_label_put(self):
        self.github.tamper_direct = True
        with self.assertRaises(PhaseRestartError):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 0)
        self.assertEqual(len(self.github.comments), 1)

    def test_incomplete_pagination_blocks_before_label_put(self):
        self.github.omit_second_history_snapshot = True
        with self.assertRaisesRegex(PhaseRestartError, "changed during direct/list/direct"):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 0)
        self.assertEqual(len(self.github.comments), 1)

    def test_wrong_phase_kind_missing_binding_and_issue63_fail_closed(self):
        self.github.issue_row["labels"] = [{"name": "kind:single"}, {"name": "phase:requirements"}]
        with self.assertRaisesRegex(PhaseRestartError, "phase:execution"):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 0)
        self.github.issue_row["labels"] = [{"name": "kind:parent"}, {"name": "phase:execution"}]
        with self.assertRaisesRegex(PhaseRestartError, "kind:single or kind:child"):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 0)
        self.github.issue_row["labels"] = [{"name": "kind:single"}]
        with self.assertRaisesRegex(PhaseRestartError, "exactly one phase"):
            self.run_restart()
        self.assertEqual(self.github.label_writes, 0)
        with patch("p_ases.phase_restart.verify_adc", return_value=self.verified):
            with self.assertRaisesRegex(PhaseRestartError, "Issue #63"):
                restart_issue_phase(self.github, self.root, 63)
        self.assertEqual(self.github.label_writes, 0)

    def test_binding_digest_and_generation_are_in_both_records(self):
        result = self.run_restart()
        intent, applied = self.github.comments
        intent_payload = json.loads(intent["body"].splitlines()[1])
        applied_payload = json.loads(applied["body"].splitlines()[1])
        self.assertEqual(intent_payload["binding_generation"], 1)
        self.assertEqual(intent_payload["binding_generation_id"], 50)
        self.assertEqual(intent_payload["binding_sha256"], binding_digest(self.binding))
        self.assertEqual(applied_payload["intent_comment_id"], result["intent_comment_id"])
        self.assertEqual(applied_payload["intent_sha256"], hashlib.sha256(intent["body"].encode()).hexdigest())
        self.assertEqual(applied_payload["labels_after"], intent_payload["labels_after"])


if __name__ == "__main__":
    unittest.main()
