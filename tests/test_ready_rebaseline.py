import copy
import hashlib
import unittest
from unittest.mock import patch

from p_ases.phase_evidence import PhaseDecision
from p_ases.ready_rebaseline import (
    PLAN_SCHEMA, ReadyRebaselineError, ReadyRebaselinePlan, _allowed_changed_paths,
    _digest, _validate_candidate_documents, _verify_owner_approval, apply_plan, owner_approval_comment,
)


def ready_plan():
    candidate = PhaseDecision({
        "schema": "PASES_PHASE_DECISION_V1",
        "repository": "puchinya/ai-agent-workflow",
        "issue_number": 46,
        "issue_kind": "single",
        "from_phase": "design",
        "to_phase": "ready",
        "adc_comment_id": 6391179626,
        "adc_sha256": "f" * 64,
        "branch_ref": "codex/issue-46-multi-host-independent-review",
        "commit_sha40": "a" * 40,
        "documents": [
            {"role": "design", "path": "docs/design/workflow-design.md", "sha256": "1" * 64},
            {"role": "specification", "path": "docs/specs/workflow-spec.md", "sha256": "2" * 64},
            {"role": "test-oracle", "path": "docs/testing/pases-lifecycle-tests.md", "sha256": "3" * 64},
            {"role": "test-oracle", "path": "docs/testing/runtime-tests.md", "sha256": "4" * 64},
            {"role": "test-oracle", "path": "docs/testing/traceability.md", "sha256": "5" * 64},
        ],
        "skip_reasons": {},
    })
    candidate_body = candidate.body()
    snapshot = {
        "adc_comment_id": 6391179626,
        "adc_sha256": "f" * 64,
        "ancestry_policy": "any_descendant_requires_exact_owner_checkpoint",
        "binding_sha256": "6" * 64,
        "branch_ref": "codex/issue-46-multi-host-independent-review",
        "candidate_ready_decision": candidate.payload,
        "candidate_ready_decision_sha256": hashlib.sha256(candidate_body.encode()).hexdigest(),
        "changed_paths": [
            "adapters/openai/README.md",
            "dist/openai/docs/specs/workflow-spec.md",
            "workflow/skills/independent-review/SKILL.md",
        ],
        "document_validation": "UNCHANGED",
        "head_sha40": "a" * 40,
        "issue_created_at": "2026-10-14T10:57:28Z",
        "issue_id": 5846549384,
        "issue_kind": "single",
        "issue_number": 46,
        "owner_id": 3744776,
        "previous_documents": copy.deepcopy(candidate.payload["documents"]),
        "prior_ready_body_sha256": "7" * 64,
        "prior_ready_comment_id": 6391400880,
        "prior_ready_commit_sha40": "b" * 40,
        "pr": {
            "base_ref": "main",
            "base_sha40": "c" * 40,
            "head_ref": "codex/issue-46-multi-host-independent-review",
            "head_sha40": "a" * 40,
            "id": 222,
            "number": 67,
        },
        "repository": "puchinya/ai-agent-workflow",
        "repository_id": 1401910271,
    }
    unsigned = {
        "generated_at": "2026-10-25T02:00:00Z",
        "schema": PLAN_SCHEMA,
        "snapshot": snapshot,
    }
    return ReadyRebaselinePlan.from_payload({**unsigned, "plan_sha256": _digest(unsigned)})


def comment_row(comment_id, body, *, actor_id=3744776, login="puchinya", actor_type="User"):
    return {
        "id": comment_id,
        "body": body,
        "created_at": "2026-10-25T02:01:00Z",
        "updated_at": "2026-10-25T02:01:00Z",
        "issue_url": "https://api.github.com/repos/puchinya/ai-agent-workflow/issues/46",
        "html_url": f"https://github.com/puchinya/ai-agent-workflow/issues/46#issuecomment-{comment_id}",
        "url": f"https://api.github.com/repos/puchinya/ai-agent-workflow/issues/comments/{comment_id}",
        "user": {"id": actor_id, "login": login, "type": actor_type},
    }


class ReadyRebaselinePlanTests(unittest.TestCase):
    def test_exact_plan_is_canonical_and_digest_bound(self):
        plan = ready_plan()
        self.assertEqual(ReadyRebaselinePlan.from_payload(plan.value), plan)
        changed = copy.deepcopy(plan.value)
        changed["snapshot"]["head_sha40"] = "d" * 40
        with self.assertRaisesRegex(ReadyRebaselineError, "digest"):
            ReadyRebaselinePlan.from_payload(changed)

    def test_plan_must_state_the_strict_descendant_policy(self):
        changed = copy.deepcopy(ready_plan().value)
        changed["snapshot"]["ancestry_policy"] = "artifact_hashes_only"
        unsigned = {key: value for key, value in changed.items() if key != "plan_sha256"}
        changed["plan_sha256"] = _digest(unsigned)
        with self.assertRaisesRegex(ReadyRebaselineError, "fixed identity"):
            ReadyRebaselinePlan.from_payload(changed)

    def test_candidate_decision_must_bind_the_planned_head_and_artifact_digest(self):
        plan = ready_plan()
        changed = copy.deepcopy(plan.value)
        changed["snapshot"]["candidate_ready_decision"]["commit_sha40"] = "d" * 40
        snapshot = changed["snapshot"]
        candidate = PhaseDecision(snapshot["candidate_ready_decision"])
        snapshot["candidate_ready_decision_sha256"] = hashlib.sha256(candidate.body().encode()).hexdigest()
        unsigned = {key: value for key, value in changed.items() if key != "plan_sha256"}
        changed["plan_sha256"] = _digest(unsigned)
        with self.assertRaisesRegex(ReadyRebaselineError, "exact subject"):
            ReadyRebaselinePlan.from_payload(changed)

    def test_candidate_cannot_change_approved_artifact_set_or_roles(self):
        changed = copy.deepcopy(ready_plan().value)
        changed["snapshot"]["previous_documents"] = changed["snapshot"]["previous_documents"][:-1]
        unsigned = {key: value for key, value in changed.items() if key != "plan_sha256"}
        changed["plan_sha256"] = _digest(unsigned)
        with self.assertRaisesRegex(ReadyRebaselineError, "artifact set or roles"):
            ReadyRebaselinePlan.from_payload(changed)

    def test_changed_document_hash_is_new_ready_evidence_bound_to_prior_and_current_bytes(self):
        changed = copy.deepcopy(ready_plan().value)
        snapshot = changed["snapshot"]
        snapshot["candidate_ready_decision"]["documents"][0]["sha256"] = "e" * 64
        snapshot["document_validation"] = "PASS"
        candidate = PhaseDecision(snapshot["candidate_ready_decision"])
        snapshot["candidate_ready_decision_sha256"] = hashlib.sha256(candidate.body().encode()).hexdigest()
        unsigned = {key: value for key, value in changed.items() if key != "plan_sha256"}
        changed["plan_sha256"] = _digest(unsigned)
        plan = ReadyRebaselinePlan.from_payload(changed)
        old_documents = plan.value["snapshot"]["previous_documents"]
        new_documents = plan.value["snapshot"]["candidate_ready_decision"]["documents"]
        self.assertNotEqual(old_documents[0]["sha256"], new_documents[0]["sha256"])
        with patch("p_ases.ready_rebaseline.validate_documents", return_value=[]) as validate:
            _validate_candidate_documents("repo", old_documents, new_documents)
        validate.assert_called_once_with("repo")

    def test_only_adc_artifacts_and_explicit_recovery_sidecars_may_change(self):
        _allowed_changed_paths(("docs/specs/workflow-spec.md", "dist/openai/runtime/p_ases/cli.py",
                                "runtime/p_ases/ready_rebaseline.py"),
                               {"docs/specs/workflow-spec.md"})
        with self.assertRaisesRegex(ReadyRebaselineError, "outside the approved recovery scope"):
            _allowed_changed_paths(("runtime/p_ases/delivery.py",), set())

    def test_unchanged_ready_artifacts_keep_exact_hashes_and_need_no_document_downgrade(self):
        documents = ready_plan().value["snapshot"]["previous_documents"]
        with patch("p_ases.ready_rebaseline.validate_documents",
                   side_effect=AssertionError("unchanged documents need no revalidation")):
            result = _validate_candidate_documents(None, documents, copy.deepcopy(documents))
        self.assertEqual(result, "UNCHANGED")

    def test_changed_ready_artifacts_require_repository_document_validation(self):
        previous = ready_plan().value["snapshot"]["previous_documents"]
        current = copy.deepcopy(previous)
        current[0]["sha256"] = "e" * 64
        with patch("p_ases.ready_rebaseline.validate_documents", return_value=[] ) as validate:
            result = _validate_candidate_documents("repo", previous, current)
        validate.assert_called_once_with("repo")
        self.assertEqual(result, "PASS")
        with patch("p_ases.ready_rebaseline.validate_documents", return_value=["bad traceability"]):
            with self.assertRaisesRegex(ReadyRebaselineError, "bad traceability"):
                _validate_candidate_documents("repo", previous, current)

    def test_plan_validation_marker_must_match_previous_and_current_artifact_hashes(self):
        changed = copy.deepcopy(ready_plan().value)
        changed["snapshot"]["document_validation"] = "PASS"
        unsigned = {key: value for key, value in changed.items() if key != "plan_sha256"}
        changed["plan_sha256"] = _digest(unsigned)
        with self.assertRaisesRegex(ReadyRebaselineError, "validation state"):
            ReadyRebaselinePlan.from_payload(changed)

    def test_owner_approval_uses_exact_body_and_stable_owner_identity(self):
        plan = ready_plan()
        expected = owner_approval_comment(plan)

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

            def __init__(self, row):
                self.row = row

            def issue_comments(self, _issue):
                return [copy.deepcopy(self.row)]

            def issue_comment(self, _issue, _comment_id):
                return copy.deepcopy(self.row)

        row = comment_row(6392085000, expected + "\n")
        self.assertEqual(_verify_owner_approval(FakeGitHub(row), plan, row["id"])["id"], row["id"])
        wrong_owner = comment_row(6392085000, expected, actor_id=101, login="not-owner")
        with self.assertRaisesRegex(ReadyRebaselineError, "fixed repository Owner"):
            _verify_owner_approval(FakeGitHub(wrong_owner), plan, wrong_owner["id"])

    def test_edited_or_double_newline_approval_is_rejected(self):
        plan = ready_plan()
        expected = owner_approval_comment(plan)

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

            def __init__(self, row):
                self.row = row

            def issue_comments(self, _issue):
                return [copy.deepcopy(self.row)]

            def issue_comment(self, _issue, _comment_id):
                return copy.deepcopy(self.row)

        for body in (expected + "\n\n", expected + "\nextra"):
            row = comment_row(6392085000, body)
            with self.subTest(body=body[-12:]), self.assertRaises(ReadyRebaselineError):
                _verify_owner_approval(FakeGitHub(row), plan, row["id"])

    def test_missing_owner_approval_blocks_before_any_issue_write(self):
        plan = ready_plan()

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"
            writes = 0

            def issue_comments(self, _issue):
                return []

            def create_issue_comment(self, _issue, _body):
                self.writes += 1
                raise AssertionError("no Issue write should occur")

        github = FakeGitHub()
        with self.assertRaisesRegex(ReadyRebaselineError, "approval comment is missing"):
            apply_plan(github, ".", plan, 6392085000)
        self.assertEqual(github.writes, 0)

    def test_stale_exact_plan_blocks_before_intent_write(self):
        plan = ready_plan()
        approval = comment_row(6392085000, owner_approval_comment(plan))

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"
            writes = 0

            def issue_comments(self, _issue):
                return [copy.deepcopy(approval)]

            def issue_comment(self, _issue, _comment_id):
                return copy.deepcopy(approval)

            def create_issue_comment(self, _issue, _body):
                self.writes += 1
                raise AssertionError("stale plan must not write")

        github = FakeGitHub()
        stale = copy.deepcopy(plan.value["snapshot"])
        stale["head_sha40"] = "d" * 40
        with patch("p_ases.ready_rebaseline._snapshot", return_value=stale):
            with self.assertRaisesRegex(ReadyRebaselineError, "stale"):
                apply_plan(github, ".", plan, approval["id"])
        self.assertEqual(github.writes, 0)

    def test_exact_owner_checkpoint_appends_once_and_replay_is_read_only_noop(self):
        plan = ready_plan()
        approval = comment_row(6392085000, owner_approval_comment(plan))

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

            def __init__(self):
                self.rows = [copy.deepcopy(approval)]
                self.writes = 0

            def issue_comments(self, _issue):
                return copy.deepcopy(self.rows)

            def issue_comment(self, _issue, comment_id):
                for row in self.rows:
                    if row["id"] == comment_id:
                        return copy.deepcopy(row)
                raise AssertionError("comment not found")

            def create_issue_comment(self, _issue, body):
                self.writes += 1
                row = comment_row(6392085000 + self.writes, body)
                self.rows.append(row)
                return copy.deepcopy(row)

        github = FakeGitHub()
        with patch("p_ases.ready_rebaseline._assert_current"):
            first = apply_plan(github, ".", plan, approval["id"])
            second = apply_plan(github, ".", plan, approval["id"])
        self.assertEqual(first["status"], "APPLIED")
        self.assertEqual(second["status"], "NOOP")
        self.assertEqual(github.writes, 2)
        self.assertNotEqual(first["intent_comment_id"], first["applied_comment_id"])
        self.assertEqual(first["applied_comment_id"], second["applied_comment_id"])


if __name__ == "__main__":
    unittest.main()
