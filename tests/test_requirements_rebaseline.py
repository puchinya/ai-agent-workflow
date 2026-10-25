import copy
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from p_ases.phases import IssueKind, Phase
from p_ases.legacy_adoption import (
    LegacyResetPlan, RESET_APPLIED_SCHEMA, RESET_INTENT_SCHEMA, RESET_PLAN_SCHEMA,
    _body as legacy_body,
)
from p_ases.requirements_rebaseline import (
    APPLIED_SCHEMA, APPROVAL_SCHEMA, INTENT_SCHEMA, PLAN_SCHEMA,
    RequirementsRebaselineError, RequirementsRebaselinePlan, _body, _digest,
    _expected_after_phase, _history, _prior_reset_snapshot, apply_plan,
    owner_approval_comment, read_plan, write_plan,
)


def rebaseline_plan():
    snapshot = {
        "adc_comment_id": 6399289386,
        "adc_sha256": "a" * 64,
        "binding_sha256": "b" * 64,
        "branch_ref": "codex/issue-46-multi-host-independent-review",
        "head_sha40": "c" * 40,
        "issue_created_at": "2026-10-14T10:57:28Z",
        "issue_id": 5846549384,
        "issue_kind": "single",
        "issue_labels": ["enhancement", "kind:single", "phase:user-review"],
        "issue_number": 46,
        "owner_id": 3744776,
        "pr": {
            "base_ref": "main",
            "base_sha40": "d" * 40,
            "head_ref": "codex/issue-46-multi-host-independent-review",
            "head_sha40": "c" * 40,
            "id": 3022241991,
            "number": 67,
        },
        "prior_legacy_reset": {
            "approval_comment_id": 6391206933,
            "applied_body_sha256": "e" * 64,
            "applied_comment_id": 6391259435,
            "intent_body_sha256": "f" * 64,
            "intent_comment_id": 6391248414,
            "plan_sha256": "1" * 64,
        },
        "repository": "puchinya/ai-agent-workflow",
        "repository_id": 1401910271,
        "target_labels": ["enhancement", "kind:single", "phase:requirements"],
    }
    unsigned = {"generated_at": "2026-10-26T00:00:00Z", "schema": PLAN_SCHEMA, "snapshot": snapshot}
    return RequirementsRebaselinePlan.from_payload({**unsigned, "plan_sha256": _digest(unsigned)})


def comment_row(comment_id, body, *, actor_id=3744776, login="puchinya", actor_type="User"):
    return {
        "id": comment_id,
        "body": body,
        "created_at": "2026-10-26T00:01:00Z",
        "updated_at": "2026-10-26T00:01:00Z",
        "issue_url": "https://api.github.com/repos/puchinya/ai-agent-workflow/issues/46",
        "html_url": f"https://github.com/puchinya/ai-agent-workflow/issues/46#issuecomment-{comment_id}",
        "url": f"https://api.github.com/repos/puchinya/ai-agent-workflow/issues/comments/{comment_id}",
        "user": {"id": actor_id, "login": login, "type": actor_type},
    }


def approved_plan_row(plan, comment_id=6399289400):
    return comment_row(comment_id, owner_approval_comment(plan))


class RequirementsRebaselinePlanTests(unittest.TestCase):
    def test_exact_plan_is_canonical_and_digest_bound(self):
        plan = rebaseline_plan()
        self.assertEqual(RequirementsRebaselinePlan.from_payload(plan.value), plan)
        changed = copy.deepcopy(plan.value)
        changed["snapshot"]["head_sha40"] = "2" * 40
        with self.assertRaisesRegex(RequirementsRebaselineError, "digest"):
            RequirementsRebaselinePlan.from_payload(changed)

    def test_plan_rejects_unapproved_issue_or_phase_scope_even_with_new_digest(self):
        for field, value in (("issue_number", 47), ("owner_id", 22)):
            changed = copy.deepcopy(rebaseline_plan().value)
            changed["snapshot"][field] = value
            unsigned = {key: item for key, item in changed.items() if key != "plan_sha256"}
            changed["plan_sha256"] = _digest(unsigned)
            with self.subTest(field=field), self.assertRaises(RequirementsRebaselineError):
                RequirementsRebaselinePlan.from_payload(changed)

        changed = copy.deepcopy(rebaseline_plan().value)
        changed["snapshot"]["issue_labels"] = ["enhancement", "kind:single", "phase:verification"]
        unsigned = {key: item for key, item in changed.items() if key != "plan_sha256"}
        changed["plan_sha256"] = _digest(unsigned)
        with self.assertRaisesRegex(RequirementsRebaselineError, "phase/label"):
            RequirementsRebaselinePlan.from_payload(changed)

    def test_plan_file_is_canonical_and_never_overwritten(self):
        plan = rebaseline_plan()
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "plan.json"
            write_plan(output, plan)
            self.assertEqual(read_plan(output), plan)
            with self.assertRaisesRegex(RequirementsRebaselineError, "exists"):
                write_plan(output, plan)
            output.write_bytes(output.read_bytes() + b" ")
            with self.assertRaisesRegex(RequirementsRebaselineError, "canonical"):
                read_plan(output)

    def test_exact_approval_is_bound_to_the_plan_and_owner_identity(self):
        plan = rebaseline_plan()
        expected = owner_approval_comment(plan)

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

            def __init__(self, row):
                self.row = row

            def repository_metadata(self):
                return {"id": 1401910271,
                        "owner": {"id": 3744776, "type": "User", "login": "puchinya"}}

            def issue_comments(self, _issue):
                return [copy.deepcopy(self.row)]

            def issue_comment(self, _issue, _comment_id):
                return copy.deepcopy(self.row)

        from p_ases.requirements_rebaseline import _verify_owner_approval
        self.assertEqual(_verify_owner_approval(
            FakeGitHub(comment_row(6399289400, expected + "\n")), plan, 6399289400)["id"], 6399289400)
        wrong_owner = comment_row(6399289400, expected, actor_id=17, login="another-user")
        with self.assertRaisesRegex(RequirementsRebaselineError, "stable repository Owner"):
            _verify_owner_approval(FakeGitHub(wrong_owner), plan, 6399289400)


class RequirementsRebaselineHistoryTests(unittest.TestCase):
    def test_duplicate_or_orphan_applied_markers_block(self):
        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

            def __init__(self, rows):
                self.rows = rows

            def issue_comments(self, _issue):
                return self.rows

        intent = comment_row(10, _body(INTENT_SCHEMA, {}))
        with self.assertRaisesRegex(RequirementsRebaselineError, "duplicated"):
            _history(FakeGitHub([intent, intent]))
        orphan = comment_row(11, _body(APPLIED_SCHEMA, {}))
        with self.assertRaisesRegex(RequirementsRebaselineError, "without its Intent"):
            _history(FakeGitHub([orphan]))

    def test_prior_reset_must_be_complete_and_bind_the_fixed_predecessor(self):
        def prior_plan(*, issue_id=5846549384):
            unsigned = {
                "adoption_comment_id": 6391190000,
                "adoption_record_sha256": "2" * 64,
                "generated_at": "2026-10-14T11:00:00Z",
                "issue_created_at": "2026-10-14T10:57:28Z",
                "issue_id": issue_id,
                "issue_kind": "single",
                "issue_labels": ["enhancement", "kind:single", "phase:user-review"],
                "issue_number": 46,
                "owner_id": 3744776,
                "phase": "user-review",
                "repository": "puchinya/ai-agent-workflow",
                "repository_id": 1401910271,
                "schema": RESET_PLAN_SCHEMA,
                "target_labels": ["enhancement", "kind:single", "phase:requirements"],
            }
            return LegacyResetPlan.from_payload({**unsigned, "plan_sha256": _digest(unsigned)})

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

        def state_for(plan, *, applied=True, plan_sha=None):
            intent = {
                "approval_comment_id": 6391206933,
                "plan": plan.value,
                "plan_sha256": plan_sha or plan.sha256,
                "schema": RESET_INTENT_SCHEMA,
            }
            applied_payload = {
                "approval_comment_id": 6391206933,
                "intent_comment_id": 6391248414,
                "plan_sha256": plan.sha256,
                "schema": RESET_APPLIED_SCHEMA,
            }
            return {
                "intent_comment_id": 6391248414, "intent_payload": intent,
                "plan": plan,
                "applied_comment_id": 6391259435 if applied else None,
                "applied_payload": applied_payload if applied else None,
            }

        plan = prior_plan()
        intent = state_for(plan)["intent_payload"]
        applied = state_for(plan)["applied_payload"]
        intent_body = legacy_body(RESET_INTENT_SCHEMA, intent)
        applied_body = legacy_body(RESET_APPLIED_SCHEMA, applied)

        def read_comment(_github, _issue, comment_id, *, expected_body=None):
            return {"body": expected_body}

        with patch("p_ases.requirements_rebaseline._read_reset_state", return_value=state_for(plan)), \
                patch("p_ases.requirements_rebaseline.verify_legacy_owner_approval"), \
                patch("p_ases.requirements_rebaseline._read_comment_direct_list_direct", side_effect=read_comment):
            result = _prior_reset_snapshot(FakeGitHub())
        self.assertEqual(result["intent_comment_id"], 6391248414)
        self.assertEqual(result["applied_comment_id"], 6391259435)
        self.assertEqual(result["plan_sha256"], plan.sha256)
        self.assertEqual(result["intent_body_sha256"], hashlib.sha256(intent_body.encode()).hexdigest())

        with patch("p_ases.requirements_rebaseline._read_reset_state", return_value=state_for(plan, applied=False)):
            with self.assertRaisesRegex(RequirementsRebaselineError, "complete previously applied"):
                _prior_reset_snapshot(FakeGitHub())

        wrong_predecessor = prior_plan(issue_id=5846549385)
        with patch("p_ases.requirements_rebaseline._read_reset_state", return_value=state_for(wrong_predecessor)), \
                patch("p_ases.requirements_rebaseline.verify_legacy_owner_approval"), \
                patch("p_ases.requirements_rebaseline._read_comment_direct_list_direct", side_effect=read_comment):
            with self.assertRaisesRegex(RequirementsRebaselineError, "not for this Issue"):
                _prior_reset_snapshot(FakeGitHub())

        with patch("p_ases.requirements_rebaseline._read_reset_state",
                   return_value=state_for(plan, plan_sha="3" * 64)):
            with self.assertRaisesRegex(RequirementsRebaselineError, "same exact plan"):
                _prior_reset_snapshot(FakeGitHub())


class RequirementsRebaselineSubjectTests(unittest.TestCase):
    def _subject(self, phase="user-review", *, pr_head=None):
        branch = "codex/issue-46-multi-host-independent-review"
        head_sha = "c" * 40
        issue = {
            "id": 5846549384,
            "number": 46,
            "state": "open",
            "pull_request": None,
            "created_at": "2026-10-14T10:57:28Z",
            "labels": [{"name": "enhancement"}, {"name": "kind:single"}, {"name": f"phase:{phase}"}],
        }
        verified = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=6399289386),
            contract=SimpleNamespace(sha256="a" * 64),
        )
        binding = SimpleNamespace(
            repository="puchinya/ai-agent-workflow", issue_number=46,
            adc_comment_id=6399289386, adc_sha256="a" * 64,
            branch_ref=branch, base_ref="main", base_sha="d" * 40,
            work_directory="/tmp/requirements-rebaseline-test",
        )
        pull = {
            "id": 3022241991, "number": 67, "state": "open", "merged": False, "draft": False,
            "base": {"ref": "main", "sha": "d" * 40, "repo": {"id": 1401910271}},
            "head": {"ref": branch, "sha": pr_head or head_sha, "repo": {"id": 1401910271}},
        }

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

            def pull_request(self, _number):
                return pull

        patches = [
            patch("p_ases.requirements_rebaseline.verify_ordinary_issue_context",
                  return_value=(issue, verified, IssueKind.SINGLE, branch, head_sha)),
            patch("p_ases.requirements_rebaseline.worktree_clean", return_value=True),
            patch("p_ases.requirements_rebaseline._repository_identity", return_value=(1401910271, 3744776)),
            patch("p_ases.requirements_rebaseline.read_binding", return_value=binding),
            patch("p_ases.requirements_rebaseline.binding_digest", return_value="b" * 64),
            patch("p_ases.requirements_rebaseline.execution_binding_path",
                  return_value=Path("/tmp/binding.json")),
            patch("p_ases.requirements_rebaseline._prior_reset_snapshot",
                  return_value=rebaseline_plan().value["snapshot"]["prior_legacy_reset"]),
        ]
        entered = []
        for item in patches:
            item.start()
            entered.append(item)
        self.addCleanup(lambda: [item.stop() for item in reversed(entered)])
        return FakeGitHub(), Path("/tmp/requirements-rebaseline-test")

    def test_current_subject_binds_adc_binding_pr_head_and_complete_old_reset(self):
        from p_ases.requirements_rebaseline import _current_snapshot

        github, root = self._subject()
        current = _current_snapshot(github, root, expected_phase=Phase.USER_REVIEW)
        self.assertEqual(current["adc_comment_id"], 6399289386)
        self.assertEqual(current["binding_sha256"], "b" * 64)
        self.assertEqual(current["head_sha40"], "c" * 40)
        self.assertEqual(current["pr"]["head_sha40"], "c" * 40)
        self.assertEqual(current["prior_legacy_reset"]["applied_comment_id"], 6391259435)

    def test_current_subject_rejects_pr_head_mismatch(self):
        from p_ases.requirements_rebaseline import _current_snapshot

        github, root = self._subject(pr_head="2" * 40)
        with self.assertRaisesRegex(RequirementsRebaselineError, "exact bound branch HEAD"):
            _current_snapshot(github, root, expected_phase=Phase.USER_REVIEW)

    def test_post_transition_snapshot_is_read_only_and_does_not_attempt_second_transition(self):
        from p_ases.requirements_rebaseline import _current_snapshot

        github, root = self._subject(phase="requirements")
        current = _current_snapshot(github, root, expected_phase=Phase.REQUIREMENTS)
        self.assertEqual(current["issue_labels"], current["target_labels"])


class RequirementsRebaselineApplyTests(unittest.TestCase):
    def test_missing_owner_approval_blocks_before_any_write(self):
        plan = rebaseline_plan()

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"
            writes = 0

            def issue_comments(self, _issue):
                return []

            def repository_metadata(self):
                return {"id": 1401910271,
                        "owner": {"id": 3744776, "type": "User", "login": "puchinya"}}

            def create_issue_comment(self, *_args):
                self.writes += 1
                raise AssertionError("missing approval must block every write")

        github = FakeGitHub()
        with self.assertRaisesRegex(RequirementsRebaselineError, "approval is missing"):
            apply_plan(github, ".", plan, 6399289400)
        self.assertEqual(github.writes, 0)

    def test_stale_subject_blocks_before_intent_or_label_write(self):
        plan = rebaseline_plan()
        approval = approved_plan_row(plan)

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"
            writes = 0

            def issue_comments(self, _issue):
                return [copy.deepcopy(approval)]

            def issue_comment(self, _issue, _comment_id):
                return copy.deepcopy(approval)

            def repository_metadata(self):
                return {"id": 1401910271,
                        "owner": {"id": 3744776, "type": "User", "login": "puchinya"}}

            def create_issue_comment(self, *_args):
                self.writes += 1
                raise AssertionError("stale plan must not write")

            def replace_issue_labels(self, *_args):
                self.writes += 1
                raise AssertionError("stale plan must not write labels")

        current = copy.deepcopy(plan.value["snapshot"])
        current["head_sha40"] = "2" * 40
        with patch("p_ases.requirements_rebaseline._current_snapshot", return_value=current):
            github = FakeGitHub()
            with patch("p_ases.requirements_rebaseline._verify_owner_approval", return_value=approval):
                with self.assertRaisesRegex(RequirementsRebaselineError, "stale"):
                    apply_plan(github, ".", plan, approval["id"])
        self.assertEqual(github.writes, 0)

    def test_exact_approval_performs_one_label_put_and_appends_linked_records(self):
        plan = rebaseline_plan()
        approval = approved_plan_row(plan)
        initial_issue = {
            "id": 5846549384,
            "number": 46,
            "state": "open",
            "pull_request": None,
            "repository_url": "https://api.github.com/repos/puchinya/ai-agent-workflow",
            "created_at": "2026-10-14T10:57:28Z",
            "body": "Issue contract",
            "labels": [{"name": name} for name in plan.value["snapshot"]["issue_labels"]],
        }

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

            def __init__(self):
                self.rows = [copy.deepcopy(approval)]
                self.issue_data = copy.deepcopy(initial_issue)
                self.next_id = 6399289500
                self.label_puts = 0

            def repository_metadata(self):
                return {"id": 1401910271,
                        "owner": {"id": 3744776, "type": "User", "login": "puchinya"}}

            def issue_comments(self, _issue):
                return copy.deepcopy(self.rows)

            def issue_comment(self, _issue, comment_id):
                for row in self.rows:
                    if row["id"] == comment_id:
                        return copy.deepcopy(row)
                raise AssertionError("comment not found")

            def create_issue_comment(self, _issue, body):
                self.next_id += 1
                row = comment_row(self.next_id, body, actor_id=3744776)
                self.rows.append(row)
                return copy.deepcopy(row)

            def issue(self, _issue):
                return copy.deepcopy(self.issue_data)

            def replace_issue_labels(self, _issue, labels):
                self.label_puts += 1
                self.issue_data["labels"] = [{"name": name} for name in labels]
                return copy.deepcopy(self.issue_data["labels"])

        github = FakeGitHub()
        before = copy.deepcopy(plan.value["snapshot"])
        after = _expected_after_phase(before)
        with patch("p_ases.requirements_rebaseline._current_snapshot", side_effect=[before, before, after, after]):
            with patch("p_ases.requirements_rebaseline._verify_owner_approval", return_value=approval):
                result = apply_plan(github, ".", plan, approval["id"])
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(result["label_write"], "VERIFIED")
        self.assertEqual(github.label_puts, 1)
        history = _history(github)
        self.assertEqual(history["intent_id"], result["intent_comment_id"])
        self.assertEqual(history["applied_id"], result["applied_comment_id"])
        self.assertEqual(history["applied_payload"]["intent_comment_id"], history["intent_id"])


if __name__ == "__main__":
    unittest.main()
