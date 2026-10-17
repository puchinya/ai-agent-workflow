from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.phase_rebaseline import (  # noqa: E402
    PhaseRebaselineError,
    rebaseline_issue_phase,
)


REPOSITORY = "puchinya/ai-agent-workflow"
OWNER_ID = 3744776
ADC_SHA = "a" * 64


def decision_body(subject_sha256: str) -> str:
    payload = {
        "evidence_channel": "delegated_github_relay",
        "issue_number": 63,
        "operation": "PHASE_REBASE",
        "owner_id": OWNER_ID,
        "pr_head_sha40": None,
        "pr_number": None,
        "predecessor_comment_id": None,
        "repository": REPOSITORY,
        "schema": "PASES_OWNER_DECISION_V1",
        "subject_sha256": subject_sha256,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"<!-- PASES_OWNER_DECISION_V1\n{canonical}\n-->"


def comment_row(comment_id: int, subject_sha256: str) -> dict:
    return {
        "id": comment_id,
        "body": decision_body(subject_sha256),
        "created_at": "2026-10-17T08:00:00Z",
        "updated_at": "2026-10-17T08:00:00Z",
        "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/63",
        "html_url": f"https://github.com/{REPOSITORY}/issues/63#issuecomment-{comment_id}",
        "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
        "user": {"id": OWNER_ID, "login": "puchinya", "type": "User"},
    }


class FakeGitHub:
    repo = REPOSITORY

    def __init__(self, labels: list[str], decision: dict):
        self.labels = list(labels)
        self.decision = decision
        self.calls: list[tuple[str, object]] = []

    def issue(self, number: int) -> dict:
        self.calls.append(("issue", number))
        return {
            "number": number,
            "state": "open",
            "labels": [{"name": name} for name in self.labels],
        }

    def authenticated_user(self) -> dict:
        return {"id": OWNER_ID, "login": "puchinya", "type": "User"}

    def issue_comments(self, number: int) -> list[dict]:
        return [self.decision]

    def issue_comment(self, number: int, comment_id: int) -> dict:
        return self.decision

    def replace_issue_labels(self, number: int, labels: list[str]) -> list[dict]:
        self.calls.append(("replace_issue_labels", list(labels)))
        self.labels = list(labels)
        return [{"name": name} for name in labels]


class PhaseRebaselineTests(unittest.TestCase):
    def test_exact_receipt_changes_only_phase_and_preserves_other_labels(self):
        decision = comment_row(501, ADC_SHA)
        github = FakeGitHub(["enhancement", "phase:ready", "kind:single"], decision)
        rebaseline_issue_phase(
            github,
            issue_number=63,
            decision_comment_id=501,
            successor_adc_sha256=ADC_SHA,
        )
        self.assertEqual(
            github.labels,
            ["enhancement", "phase:requirements", "kind:single"],
        )
        writes = [call for call in github.calls if call[0] == "replace_issue_labels"]
        self.assertEqual(len(writes), 1)

    def test_wrong_subject_or_phase_blocks_before_label_write(self):
        decision = comment_row(501, "b" * 64)
        github = FakeGitHub(["phase:ready", "kind:single"], decision)
        with self.assertRaises(PhaseRebaselineError):
            rebaseline_issue_phase(
                github,
                issue_number=63,
                decision_comment_id=501,
                successor_adc_sha256=ADC_SHA,
            )
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in github.calls))

        already_rebased = FakeGitHub(
            ["phase:requirements", "kind:single"],
            comment_row(501, ADC_SHA),
        )
        rebaseline_issue_phase(
            already_rebased,
            issue_number=63,
            decision_comment_id=501,
            successor_adc_sha256=ADC_SHA,
        )
        self.assertFalse(any(call[0] == "replace_issue_labels" for call in already_rebased.calls))


if __name__ == "__main__":
    unittest.main()
