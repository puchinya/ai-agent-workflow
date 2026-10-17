from __future__ import annotations

import json
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.owner_consent import (  # noqa: E402
    OwnerDecisionError,
    parse_owner_decision,
    read_verified_owner_decision,
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
        with self.assertRaises(OwnerDecisionError):
            parse_owner_decision(decision_body(operation="PHASE_REBASE"))

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

    def test_read_verified_owner_decision_checks_exact_github_origin_and_direct_list_direct(self):
        payload = parse_owner_decision(decision_body(operation="ADC_SUPERSEDE")).as_dict()
        comment = {
            "id": 101, "body": decision_body(operation="ADC_SUPERSEDE"),
            "created_at": "2026-10-17T09:01:00Z", "updated_at": "2026-10-17T09:01:00Z",
            "user": {"id": OWNER_ID, "login": "puchinya", "type": "User"},
            "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/101",
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/63",
            "html_url": f"https://github.com/{REPOSITORY}/issues/63#issuecomment-101",
        }

        class FakeGitHub:
            repo = REPOSITORY

            def __init__(self, listed, *, direct=None, owner_id=OWNER_ID):
                self.listed = list(listed)
                self.direct = (direct if isinstance(direct, dict)
                               else {row["id"]: row for row in (direct or listed)})
                self.owner_id = owner_id
                self.calls = []

            def repository_metadata(self):
                return {"id": 1401910271, "full_name": REPOSITORY,
                        "owner": {"id": self.owner_id, "login": "puchinya", "type": "User"}}

            def issue(self, number):
                self.calls.append(("issue", number))
                return {"number": number, "state": "open", "pull_request": None,
                        "repository_url": f"https://api.github.com/repos/{REPOSITORY}", "body": ""}

            def issue_comments(self, number):
                self.calls.append(("list", number))
                return self.listed

            def issue_comment(self, number, comment_id):
                self.calls.append(("direct", number, comment_id))
                return self.direct.get(comment_id)

        verified = read_verified_owner_decision(
            FakeGitHub([comment]), issue_number=63, owner_id=OWNER_ID,
            operation="ADC_SUPERSEDE", subject_sha256=SUBJECT_SHA,
        )
        self.assertEqual(verified.comment_id, 101)
        self.assertEqual(verified.decision.as_dict(), payload)
        self.assertEqual(verified.body_sha256, hashlib.sha256(comment["body"].encode()).hexdigest())
        self.assertEqual(verified.created_at, comment["created_at"])

        invalid_rows = (
            {**comment, "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/62"},
            {**comment, "url": f"https://api.github.com/repos/other/repo/issues/comments/101"},
            {**comment, "html_url": f"https://github.com/{REPOSITORY}/issues/62#issuecomment-101"},
            {**comment, "user": {**comment["user"], "id": OWNER_ID + 1}},
            {**comment, "updated_at": "2026-10-17T09:02:00Z"},
        )
        for invalid in invalid_rows:
            with self.subTest(invalid=invalid), self.assertRaises(OwnerDecisionError):
                read_verified_owner_decision(
                    FakeGitHub([invalid]), issue_number=63, owner_id=OWNER_ID,
                    operation="ADC_SUPERSEDE", subject_sha256=SUBJECT_SHA,
                )
        with self.assertRaises(OwnerDecisionError):
            read_verified_owner_decision(
                FakeGitHub([comment], direct={101: {**comment, "body": "different"}}),
                issue_number=63, owner_id=OWNER_ID, operation="ADC_SUPERSEDE", subject_sha256=SUBJECT_SHA,
            )
        with self.assertRaises(OwnerDecisionError):
            read_verified_owner_decision(
                FakeGitHub([comment], owner_id=OWNER_ID + 1), issue_number=63, owner_id=OWNER_ID,
                operation="ADC_SUPERSEDE", subject_sha256=SUBJECT_SHA,
            )

    def test_verified_owner_decision_binds_exact_pr_and_rejects_unknown_marker(self):
        body = decision_body(operation="PR_MERGE", pr_number=64, pr_head_sha40="d" * 40)
        row = {
            "id": 201, "body": body,
            "created_at": "2026-10-17T09:01:00Z", "updated_at": "2026-10-17T09:01:00Z",
            "user": {"id": OWNER_ID, "login": "puchinya", "type": "User"},
            "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/201",
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/63",
            "html_url": f"https://github.com/{REPOSITORY}/issues/63#issuecomment-201",
        }

        class FakeGitHub:
            repo = REPOSITORY
            def repository_metadata(self):
                return {"full_name": REPOSITORY, "owner": {"id": OWNER_ID, "type": "User"}}
            def issue(self, number):
                return {"number": number, "state": "open", "repository_url": f"https://api.github.com/repos/{REPOSITORY}"}
            def issue_comments(self, _number):
                return [row]
            def issue_comment(self, _number, _comment_id):
                return row

        with self.assertRaises(OwnerDecisionError):
            read_verified_owner_decision(
                FakeGitHub(), issue_number=63, owner_id=OWNER_ID, operation="PR_MERGE",
                subject_sha256=SUBJECT_SHA, expected_pr_number=64, expected_pr_head_sha40="e" * 40,
            )
        self.assertEqual(read_verified_owner_decision(
            FakeGitHub(), issue_number=63, owner_id=OWNER_ID, operation="PR_MERGE",
            subject_sha256=SUBJECT_SHA, expected_pr_number=64, expected_pr_head_sha40="d" * 40,
        ).comment_id, 201)
        with self.assertRaises(OwnerDecisionError):
            read_verified_owner_decision(
                FakeGitHub(), issue_number=63, owner_id=OWNER_ID, operation="RULESET_PLAN_APPLY",
                subject_sha256=SUBJECT_SHA,
            )
        malformed = {**row, "body": "<!-- PASES_OWNER_DECISION_V2\n{}\n-->"}
        FakeGitHub.issue_comments = lambda self, _number: [malformed]
        FakeGitHub.issue_comment = lambda self, _number, _id: malformed
        with self.assertRaises(OwnerDecisionError):
            read_verified_owner_decision(
                FakeGitHub(), issue_number=63, owner_id=OWNER_ID, operation="PR_MERGE",
                subject_sha256=SUBJECT_SHA, expected_pr_number=64, expected_pr_head_sha40="d" * 40,
            )


if __name__ == "__main__":
    unittest.main()
