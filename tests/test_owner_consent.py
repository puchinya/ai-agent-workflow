from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.owner_consent import (  # noqa: E402
    OwnerDecisionError,
    parse_owner_decision,
    verify_owner_decision_history,
)


REPOSITORY = "puchinya/ai-agent-workflow"
OWNER_ID = 3744776
SUBJECT_SHA = "a" * 64


def decision_body(**overrides: object) -> str:
    payload = {
        "evidence_channel": "delegated_github_relay",
        "issue_number": 63,
        "operation": "ADC_SUPERSEDE",
        "owner_id": OWNER_ID,
        "pr_head_sha40": None,
        "pr_number": None,
        "predecessor_comment_id": None,
        "repository": REPOSITORY,
        "schema": "PASES_OWNER_DECISION_V1",
        "subject_sha256": SUBJECT_SHA,
    }
    payload.update(overrides)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"<!-- PASES_OWNER_DECISION_V1\n{canonical}\n-->"


class OwnerDecisionRecordTests(unittest.TestCase):
    def test_canonical_record_binds_exact_operation_and_subject(self):
        body = decision_body()
        record = parse_owner_decision(body)
        self.assertEqual(record.operation, "ADC_SUPERSEDE")
        self.assertEqual(record.repository, REPOSITORY)
        self.assertEqual(record.issue_number, 63)
        self.assertEqual(record.subject_sha256, SUBJECT_SHA)
        self.assertEqual(record.evidence_channel, "delegated_github_relay")
        self.assertNotIn("host_attestation", body)

    def test_rejects_noncanonical_json_unknown_fields_and_wrong_channel(self):
        with self.assertRaises(OwnerDecisionError):
            parse_owner_decision(decision_body(extra="not allowed"))
        with self.assertRaises(OwnerDecisionError):
            parse_owner_decision(decision_body(evidence_channel="host_attested"))
        with self.assertRaises(OwnerDecisionError):
            parse_owner_decision(decision_body().replace('"issue_number":63', '"issue_number": 63'))
        with self.assertRaises(OwnerDecisionError):
            parse_owner_decision(decision_body(operation="USER_REVIEW"))

    def test_history_rejects_wrong_owner_operation_subject_and_replay(self):
        comments = [
            {"id": 101, "body": decision_body(), "user": {"id": OWNER_ID, "type": "User"}},
        ]
        scope = {
            "repository": REPOSITORY,
            "issue_number": 63,
            "owner_id": OWNER_ID,
            "operation": "ADC_SUPERSEDE",
            "subject_sha256": SUBJECT_SHA,
        }
        verify_owner_decision_history(comments, **scope)
        with self.assertRaises(OwnerDecisionError):
            verify_owner_decision_history(comments, **{**scope, "owner_id": OWNER_ID + 1})
        with self.assertRaises(OwnerDecisionError):
            verify_owner_decision_history(comments, **{**scope, "operation": "PHASE_REBASE"})
        with self.assertRaises(OwnerDecisionError):
            verify_owner_decision_history(comments, **{**scope, "subject_sha256": "b" * 64})
        duplicate = comments + [{**comments[0], "id": 102}]
        with self.assertRaises(OwnerDecisionError):
            verify_owner_decision_history(duplicate, **scope)


if __name__ == "__main__":
    unittest.main()
