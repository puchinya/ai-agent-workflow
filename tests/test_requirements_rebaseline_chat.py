import copy
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from p_ases.chat_decisions import (
    ADC_REBASELINE_SCOPE, ADC_SCOPE_FIELDS, REPOSITORY, REPOSITORY_ID,
    SCHEMA_V1, SCHEMA_V2, ISSUE_ID, ISSUE_NUMBER, PR_NUMBER, ChatDecisionError,
    find_adc_rebaseline_decision, read_chat_decision,
)
from p_ases.requirements_rebaseline import RequirementsRebaselineError, _digest
from p_ases.requirements_rebaseline_chat import (
    APPLIED_SCHEMA, INTENT_SCHEMA, PLAN_SCHEMA, ChatRequirementsRebaselinePlan,
    apply_plan, read_plan, write_plan,
)


ADC_SHA = "f27107b42c30ea91267e1ea05912fbfb44c29987f0c6010b984f46a625278877"
DECISION_COMMENT_ID = 6399593074
QUESTION_ITEM_ID = '["request_user_input_async","call_374e4037765b44d0894bdbce339579d0",0]'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def decision_payload():
    scope = {
        "adc_sha256": ADC_SHA,
        "append_execution_binding": True,
        "excluded": ["USER_REVIEW", "PR_MERGE", "ISSUE_CLOSE"],
        "issue_number": ISSUE_NUMBER,
        "phase_rebaseline": ADC_REBASELINE_SCOPE,
        "pr_head_sha40": "4" * 40,
        "pr_number": PR_NUMBER,
        "predecessor_adc_comment_id": 6399289386,
        "predecessor_adc_sha256": "8465cfa151186b3a59a015f9f0c6f674f9e7bedce587747b72e080197e480ab3",
        "publish_adc_as_approved": True,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
    }
    assert set(scope) == ADC_SCOPE_FIELDS
    return {
        "answer": "承認する", "evidence_channel": "operator_reported_chat",
        "github_recorder": {"login": "puchinya", "user_id": 3744776},
        "issue_id": ISSUE_ID, "issue_number": ISSUE_NUMBER,
        "pr_head_sha40": "4" * 40, "pr_number": PR_NUMBER,
        "question_item_id": QUESTION_ITEM_ID,
        "recorded_at": "2026-10-25T00:00:00Z", "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID, "schema": SCHEMA_V1, "scope": scope,
        "scope_sha256": hashlib.sha256(canonical(scope)).hexdigest(),
        "subject_sha256": ADC_SHA,
    }


def comment_row(comment_id, body):
    return {
        "id": comment_id, "body": body,
        "created_at": "2026-10-25T00:00:01Z", "updated_at": "2026-10-25T00:00:01Z",
        "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
        "html_url": f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}",
        "user": {"id": 3744776, "login": "puchinya", "type": "User"},
    }


def plan_value():
    snapshot = {
        "adc_comment_id": 6399596796, "adc_sha256": ADC_SHA,
        "binding_sha256": "b" * 64,
        "branch_ref": "codex/issue-46-multi-host-independent-review",
        "head_sha40": "4" * 40, "issue_created_at": "2026-10-14T10:57:28Z",
        "issue_id": ISSUE_ID, "issue_kind": "single",
        "issue_labels": ["enhancement", "kind:single", "phase:user-review"],
        "issue_number": ISSUE_NUMBER, "owner_id": 3744776,
        "pr": {"base_ref": "main", "base_sha40": "d" * 40,
               "head_ref": "codex/issue-46-multi-host-independent-review",
               "head_sha40": "4" * 40, "id": 3022241991, "number": PR_NUMBER},
        "prior_legacy_reset": {
            "approval_comment_id": 6391206933, "applied_body_sha256": "e" * 64,
            "applied_comment_id": 6391259435, "intent_body_sha256": "f" * 64,
            "intent_comment_id": 6391248414, "plan_sha256": "1" * 64,
        },
        "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "target_labels": ["enhancement", "kind:single", "phase:requirements"],
    }
    decision = {"comment_id": DECISION_COMMENT_ID, "body_sha256": "a" * 64,
                "scope_sha256": hashlib.sha256(canonical(decision_payload()["scope"])).hexdigest()}
    unsigned = {"chat_decision": decision, "generated_at": "2026-10-25T00:00:00Z",
                "schema": PLAN_SCHEMA, "snapshot": snapshot}
    return {**unsigned, "plan_sha256": _digest(unsigned)}


class ChatDecisionTests(unittest.TestCase):
    def test_exact_adc_chat_decision_is_read_back_and_bound_to_the_successor(self):
        payload = decision_payload()
        body = f"<!-- {SCHEMA_V1}\n{canonical(payload).decode()}\n-->"
        row = comment_row(DECISION_COMMENT_ID, body)

        class FakeGitHub:
            repo = REPOSITORY

            def issue_comments(self, issue_number):
                self.assert_issue(issue_number)
                return [copy.deepcopy(row)]

            def issue_comment(self, issue_number, comment_id):
                self.assert_issue(issue_number)
                if comment_id != DECISION_COMMENT_ID:
                    raise AssertionError("unexpected comment")
                return copy.deepcopy(row)

            @staticmethod
            def assert_issue(issue_number):
                if issue_number != ISSUE_NUMBER:
                    raise AssertionError("wrong issue")

        decision = find_adc_rebaseline_decision(FakeGitHub(), ADC_SHA)
        self.assertEqual(decision.comment_id, DECISION_COMMENT_ID)
        self.assertEqual(decision.subject_sha256, ADC_SHA)
        self.assertEqual(decision.payload["scope"]["phase_rebaseline"], ADC_REBASELINE_SCOPE)
        with self.assertRaises(ChatDecisionError):
            find_adc_rebaseline_decision(FakeGitHub(), "0" * 64)

    def test_v2_chat_decision_requires_the_immediately_preceding_decision(self):
        first_payload = decision_payload()
        first_body = f"<!-- {SCHEMA_V1}\n{canonical(first_payload).decode()}\n-->"
        scope = {"head_sha40": "4" * 40, "review_sha256": "5" * 64}
        payload = {
            "answer": "承認する", "evidence_channel": "operator_reported_chat",
            "github_recorder": {"login": "puchinya", "user_id": 3744776},
            "issue_id": ISSUE_ID, "issue_number": ISSUE_NUMBER,
            "operation": "USER_REVIEW", "predecessor_decision_comment_id": DECISION_COMMENT_ID,
            "pr_number": PR_NUMBER, "question_item_id": QUESTION_ITEM_ID,
            "recorded_at": "2026-10-25T00:01:00Z", "repository": REPOSITORY,
            "repository_id": REPOSITORY_ID, "schema": SCHEMA_V2, "scope": scope,
            "scope_sha256": hashlib.sha256(canonical(scope)).hexdigest(),
            "subject_sha256": "6" * 64,
        }
        second_id = DECISION_COMMENT_ID + 10
        second_body = f"<!-- {SCHEMA_V2}\n{canonical(payload).decode()}\n-->"
        rows = [comment_row(DECISION_COMMENT_ID, first_body), comment_row(second_id, second_body)]

        class FakeGitHub:
            repo = REPOSITORY

            def issue_comments(self, _issue_number):
                return copy.deepcopy(rows)

            def issue_comment(self, _issue_number, comment_id):
                return copy.deepcopy(next(row for row in rows if row["id"] == comment_id))

        decision = read_chat_decision(FakeGitHub(), second_id, operation="USER_REVIEW",
                                      subject_sha256="6" * 64,
                                      scope_sha256=payload["scope_sha256"])
        self.assertEqual(decision.payload["predecessor_decision_comment_id"], DECISION_COMMENT_ID)
        payload["predecessor_decision_comment_id"] = 6399289386
        rows[1] = comment_row(second_id, f"<!-- {SCHEMA_V2}\n{canonical(payload).decode()}\n-->")
        with self.assertRaisesRegex(ChatDecisionError, "predecessor"):
            read_chat_decision(FakeGitHub(), second_id, operation="USER_REVIEW",
                               subject_sha256="6" * 64,
                               scope_sha256=payload["scope_sha256"])


class ChatRequirementsRebaselinePlanTests(unittest.TestCase):
    def test_plan_is_canonical_and_bound_to_chat_decision(self):
        value = plan_value()
        plan = ChatRequirementsRebaselinePlan.from_payload(value)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            write_plan(path, plan)
            self.assertEqual(read_plan(path), plan)
        changed = copy.deepcopy(value)
        changed["chat_decision"]["comment_id"] += 1
        with self.assertRaisesRegex(RequirementsRebaselineError, "digest"):
            ChatRequirementsRebaselinePlan.from_payload(changed)

    def test_stale_subject_blocks_before_any_phase_or_comment_write(self):
        plan = ChatRequirementsRebaselinePlan.from_payload(plan_value())

        class FakeGitHub:
            repo = REPOSITORY

            def replace_issue_labels(self, *_args):
                raise AssertionError("stale plan must not write phase labels")

        changed = copy.deepcopy(plan.value["snapshot"])
        changed["head_sha40"] = "9" * 40
        with patch("p_ases.requirements_rebaseline_chat._legacy_v1_must_be_empty"), \
                patch("p_ases.requirements_rebaseline_chat._find_chat_history", return_value={
                    "applied_id": None, "applied_payload": None,
                    "intent_id": None, "intent_payload": None,
                }), \
                patch("p_ases.requirements_rebaseline_chat._verify_adc_chat_decision"), \
                patch("p_ases.requirements_rebaseline_chat._current_snapshot", return_value=changed), \
                patch("p_ases.requirements_rebaseline_chat._append_record",
                      side_effect=AssertionError("stale plan must not append Intent")):
            with self.assertRaisesRegex(RequirementsRebaselineError, "stale"):
                apply_plan(FakeGitHub(), Path("/tmp/unused"), plan)

    def test_schema_versions_are_forward_only(self):
        self.assertEqual(INTENT_SCHEMA, "PASES_REQUIREMENTS_REBASELINE_INTENT_V2")
        self.assertEqual(APPLIED_SCHEMA, "PASES_REQUIREMENTS_REBASELINE_APPLIED_V2")


if __name__ == "__main__":
    unittest.main()
