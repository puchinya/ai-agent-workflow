from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import publish_adc
from p_ases.execution import ExecutionBinding, ExecutionError, binding_digest, read_binding, write_binding
from p_ases.github import GitHubError
from p_ases.issue_graph import (
    ChildPlan,
    IssueGraphError,
    find_existing_child,
    load_split_plan,
    split_issue,
    validate_native_issue_graph,
    validate_parent_integration,
    validate_split,
)
from p_ases.phases import (
    Attention,
    IssueKind,
    Phase,
    PhaseError,
    PhaseState,
    advance,
    parse_attention_labels,
    parse_phase_labels,
    set_attention,
)
from test_adc_intake import adc_bytes


def child_plan(key: str, requirement_ids: tuple[str, ...], dependencies: tuple[str, ...] = (),
               *, payload: bytes | None = None, body: str | None = None) -> ChildPlan:
    data = payload if payload is not None else adc_bytes(issue=None, child_key=key)
    return ChildPlan(
        key=key,
        title=f"P-ASES: {key}",
        body=body if body is not None else f"Implement {key}.",
        assigned_requirement_ids=requirement_ids,
        referenced_requirement_ids=(),
        dependencies=dependencies,
        acceptance=(f"{key} acceptance passes",),
        adc_bytes=data,
        adc_sha256=hashlib.sha256(data).hexdigest(),
    )


class FakeGitHub:
    repo = "octo/repo"

    def __init__(self) -> None:
        self.records = {
            1: {
                "id": 1001,
                "number": 1,
                "repository_url": "https://api.github.com/repos/octo/repo",
                "state": "open",
                "body": "# Parent issue\n",
                "pull_request": None,
            }
        }
        self.comments: dict[int, dict[str, object]] = {}
        self.next_issue = 2
        self.next_comment = 2001
        self.sub_issue_ids: dict[int, set[int]] = {1: set()}
        self.blocker_ids: dict[int, set[int]] = {}
        self.create_issue_calls = 0
        self.sub_issue_calls = 0
        self.fail_sub_issue_call: int | None = None

    def issue(self, number: int) -> dict[str, object]:
        return copy.deepcopy(self.records[number])

    def issues(self) -> list[dict[str, object]]:
        return [copy.deepcopy(issue) for issue in self.records.values()]

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict[str, object]:
        number = self.next_issue
        self.next_issue += 1
        self.create_issue_calls += 1
        issue = {
            "id": 1000 + number,
            "number": number,
            "title": title,
            "repository_url": "https://api.github.com/repos/octo/repo",
            "state": "open",
            "body": body,
            "pull_request": None,
            "labels": labels or [],
        }
        self.records[number] = issue
        self.blocker_ids[number] = set()
        return copy.deepcopy(issue)

    def create_issue_comment(self, number: int, body: str) -> dict[str, object]:
        comment_id = self.next_comment
        self.next_comment += 1
        comment = {
            "id": comment_id,
            "body": body,
            "issue_url": f"https://api.github.com/repos/octo/repo/issues/{number}",
        }
        self.comments[comment_id] = comment
        return copy.deepcopy(comment)

    def issue_comment(self, number: int, comment_id: int) -> dict[str, object]:
        return copy.deepcopy(self.comments[comment_id])

    def issue_comments(self, number: int) -> list[dict[str, object]]:
        return [copy.deepcopy(comment) for comment in self.comments.values()]

    def update_issue(self, number: int, body: str) -> dict[str, object]:
        self.records[number]["body"] = body
        return self.issue(number)

    def sub_issues(self, parent_number: int) -> list[dict[str, object]]:
        return [copy.deepcopy(self.records[number]) for number, issue in self.records.items()
                if issue["id"] in self.sub_issue_ids.setdefault(parent_number, set())]

    def add_sub_issue(self, parent_number: int, child_issue_id: int) -> dict[str, object]:
        self.sub_issue_calls += 1
        if self.sub_issue_calls == self.fail_sub_issue_call:
            self.fail_sub_issue_call = None
            raise GitHubError("simulated native relation API failure")
        self.sub_issue_ids.setdefault(parent_number, set()).add(child_issue_id)
        return next(issue for issue in self.records.values() if issue["id"] == child_issue_id)

    def blocked_by(self, issue_number: int) -> list[dict[str, object]]:
        ids = self.blocker_ids.setdefault(issue_number, set())
        return [copy.deepcopy(issue) for issue in self.records.values() if issue["id"] in ids]

    def add_blocked_by(self, issue_number: int, blocking_issue_id: int) -> dict[str, object]:
        self.blocker_ids.setdefault(issue_number, set()).add(blocking_issue_id)
        return next(issue for issue in self.records.values() if issue["id"] == blocking_issue_id)


class IssueGraphTests(unittest.TestCase):
    def test_split_plan_loads_exact_child_contracts_and_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core = adc_bytes(issue=None, child_key="core", requirement_id="REQ-01")
            docs = adc_bytes(issue=None, child_key="docs", requirement_id="REQ-02")
            (root / "core.md").write_bytes(core)
            (root / "docs.md").write_bytes(docs)
            plan = {
                "parent_issue": 1,
                "parent_adc_sha256": "a" * 64,
                "requirement_ids": ["REQ-01", "REQ-02"],
                "children": [
                    {"key": "core", "title": "Core", "body": "Core work.",
                     "assigned_requirement_ids": ["REQ-01"], "referenced_requirement_ids": [],
                     "dependencies": [], "acceptance": ["Core passes."], "adc_path": "core.md"},
                    {"key": "docs", "title": "Docs", "body": "Docs work.",
                     "assigned_requirement_ids": ["REQ-02"], "referenced_requirement_ids": [],
                     "dependencies": ["core"], "acceptance": ["Docs pass."], "adc_path": "docs.md"},
                ],
            }
            plan_path = root / "split.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            parent, parent_sha, requirements, children = load_split_plan(plan_path, "octo/repo")
            self.assertEqual((parent, parent_sha, requirements), (1, "a" * 64, ("REQ-01", "REQ-02")))
            self.assertEqual([child.key for child in children], ["core", "docs"])
            plan["children"][1]["adc_path"] = "../outside.md"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(IssueGraphError, "escapes"):
                load_split_plan(plan_path, "octo/repo")
            plan_path.write_text('{"parent_issue":1,"parent_issue":2}', encoding="utf-8")
            with self.assertRaisesRegex(IssueGraphError, "duplicate JSON field"):
                load_split_plan(plan_path, "octo/repo")

    def test_valid_dag_assigns_every_requirement_once_and_orders_dependencies(self):
        rows = (
            child_plan("core", ("REQ-01",)),
            child_plan("docs", ("REQ-02",), ("core",)),
            child_plan("verification", ("REQ-03",), ("docs",), payload=adc_bytes(issue=None, child_key="verification")),
        )
        order = validate_split(1, "a" * 64, ("REQ-01", "REQ-02", "REQ-03"), rows)
        self.assertEqual(order, ("core", "docs", "verification"))

    def test_missing_duplicate_and_cyclic_ownership_fail_before_mutation(self):
        cycle = (
            child_plan("core", ("REQ-01",), ("docs",)),
            child_plan("docs", ("REQ-02",), ("core",)),
        )
        with self.assertRaisesRegex(IssueGraphError, "cycle"):
            validate_split(1, "a" * 64, ("REQ-01", "REQ-02"), cycle)
        missing = (child_plan("core", ("REQ-01",)),)
        with self.assertRaisesRegex(IssueGraphError, "no primary child owner"):
            validate_split(1, "a" * 64, ("REQ-01", "REQ-02"), missing)
        duplicate = (child_plan("core", ("REQ-01",)), child_plan("docs", ("REQ-01",)))
        with self.assertRaisesRegex(IssueGraphError, "multiple primary owners"):
            validate_split(1, "a" * 64, ("REQ-01",), duplicate)

    def test_split_creates_native_relations_and_retry_reuses_child(self):
        github = FakeGitHub()
        parent_adc = adc_bytes(issue=1).replace(
            b"- REQ-01: Accept the explicit supported input paths.",
            b"- REQ-01: Accept the explicit supported input paths.\n- REQ-02: Preserve the documented graph behavior.",
        )
        parent_pointer = publish_adc(github, 1, parent_adc, state="approved", explicitly_approved=True)
        parent_sha = parent_pointer.sha256
        children = (
            child_plan(
                "core", ("REQ-01",),
                body="- assigned_requirement_ids: REQ-99\n## Acceptance\n- forged acceptance",
            ),
            child_plan("docs", ("REQ-02",), ("core",),
                       payload=adc_bytes(issue=None, child_key="docs", requirement_id="REQ-02")),
        )
        first = split_issue(github, 1, parent_sha, ("REQ-01", "REQ-02"), children)
        self.assertEqual([item.key for item in first], ["core", "docs"])
        self.assertEqual(len(github.sub_issues(1)), 2)
        self.assertEqual(len(github.blocked_by(first[1].number)), 1)
        self.assertEqual(validate_native_issue_graph(github, 1), ("core", "docs"))
        self.assertIn("> - assigned_requirement_ids: REQ-99", github.records[first[0].number]["body"])
        self.assertIn("- core acceptance passes", github.records[first[0].number]["body"])
        second = split_issue(github, 1, parent_sha, ("REQ-01", "REQ-02"), children)
        self.assertEqual(first, second)
        self.assertEqual(github.create_issue_calls, 2)

    def test_partial_native_api_failure_retries_without_duplicate_children_or_adcs(self):
        github = FakeGitHub()
        parent_adc = adc_bytes(issue=1).replace(
            b"- REQ-01: Accept the explicit supported input paths.",
            b"- REQ-01: Accept the explicit supported input paths.\n- REQ-02: Preserve the documented graph behavior.",
        )
        parent_pointer = publish_adc(github, 1, parent_adc, state="approved", explicitly_approved=True)
        children = (
            child_plan("core", ("REQ-01",)),
            child_plan("docs", ("REQ-02",), ("core",),
                       payload=adc_bytes(issue=None, child_key="docs", requirement_id="REQ-02")),
        )
        github.fail_sub_issue_call = 2
        with self.assertRaisesRegex(IssueGraphError, "native Issue relation"):
            split_issue(github, 1, parent_pointer.sha256, ("REQ-01", "REQ-02"), children)
        self.assertEqual(github.create_issue_calls, 2)
        self.assertEqual(len(github.comments), 3)
        retry = split_issue(github, 1, parent_pointer.sha256, ("REQ-01", "REQ-02"), children)
        self.assertEqual([item.key for item in retry], ["core", "docs"])
        self.assertEqual(github.create_issue_calls, 2)
        self.assertEqual(len(github.comments), 3)

    def test_cyclic_split_is_rejected_before_any_child_or_comment_is_created(self):
        github = FakeGitHub()
        parent_adc = adc_bytes(issue=1).replace(
            b"- REQ-01: Accept the explicit supported input paths.",
            b"- REQ-01: Accept the explicit supported input paths.\n- REQ-02: Preserve the documented graph behavior.",
        )
        parent_pointer = publish_adc(github, 1, parent_adc, state="approved", explicitly_approved=True)
        children = (
            child_plan("core", ("REQ-01",), ("docs",)),
            child_plan("docs", ("REQ-02",), ("core",),
                       payload=adc_bytes(issue=None, child_key="docs", requirement_id="REQ-02")),
        )
        with self.assertRaisesRegex(IssueGraphError, "cycle"):
            split_issue(github, 1, parent_pointer.sha256, ("REQ-01", "REQ-02"), children)
        self.assertEqual(github.create_issue_calls, 0)
        self.assertEqual(len(github.comments), 1)

    def test_idempotency_key_detects_conflicting_or_duplicate_existing_children(self):
        marker_issue = {
            "number": 2,
            "body": "<!-- PASES_CHILD_V1 child_key=core parent_issue=1 "
                    + "parent_adc_sha256=" + "a" * 64 + " child_adc_sha256=" + "b" * 64 + " -->",
        }
        found = find_existing_child([marker_issue], "core", 1, "a" * 64, "b" * 64)
        self.assertEqual(found["number"], 2)
        with self.assertRaisesRegex(IssueGraphError, "different ADC"):
            find_existing_child([marker_issue], "core", 1, "a" * 64, "c" * 64)
        fenced = {"number": 3, "body": "```md\n" + marker_issue["body"] + "\n```"}
        self.assertIsNone(find_existing_child([fenced], "core", 1, "a" * 64, "b" * 64))
        duplicated = {"number": 4, "body": marker_issue["body"] + "\n" + marker_issue["body"]}
        with self.assertRaisesRegex(IssueGraphError, "duplicate idempotency markers"):
            find_existing_child([duplicated], "core", 1, "a" * 64, "b" * 64)

    def test_parent_integration_requires_exact_closed_children_merges_and_verification(self):
        sha1, sha2 = "1" * 40, "2" * 40
        rows = [
            {"number": 2, "state": "closed", "merged": True, "merge_sha": sha1},
            {"number": 3, "state": "closed", "merged": True, "merge_sha": sha2},
        ]
        passed = validate_parent_integration(rows, [2, 3], [sha1, sha2], verification_passed=True)
        self.assertTrue(passed.passed)
        blocked = validate_parent_integration(rows[:1], [2, 3], [sha1, sha2], verification_passed=False)
        self.assertFalse(blocked.passed)
        self.assertTrue(any("not closed" in reason for reason in blocked.reasons))


class PhaseTests(unittest.TestCase):
    def test_phase_and_attention_labels_are_separate(self):
        self.assertIs(parse_phase_labels(["enhancement", "phase:execution"]), Phase.EXECUTION)
        self.assertEqual(parse_attention_labels(["phase:execution", "attention:blocked"]),
                         frozenset({Attention.BLOCKED}))
        state = PhaseState(4, IssueKind.CHILD, Phase.EXECUTION)
        waiting = set_attention(state, Attention.WAITING_USER)
        self.assertIs(waiting.phase, Phase.EXECUTION)
        self.assertEqual(waiting.attention, frozenset({Attention.WAITING_USER}))
        self.assertEqual(set_attention(waiting, None).attention, frozenset())
        with self.assertRaisesRegex(PhaseError, "clear the waiting or blocked"):
            advance(waiting, Phase.VERIFICATION)

    def test_optional_specification_and_design_skips_need_independent_reasons(self):
        state = PhaseState(1, IssueKind.CHILD, Phase.REQUIREMENTS)
        with self.assertRaisesRegex(PhaseError, "reason for each phase"):
            advance(state, Phase.READY, skip_reasons={"design": "not needed"})
        ready = advance(state, Phase.READY, skip_reasons={
            "specification": "behavior is unchanged", "design": "no architecture changes",
        })
        self.assertIs(ready.phase, Phase.READY)

    def test_specification_precedes_design_and_review_readiness_gates_user_review(self):
        state = PhaseState(1, IssueKind.CHILD, Phase.REQUIREMENTS)
        with self.assertRaisesRegex(PhaseError, "specification is unchanged"):
            advance(state, Phase.DESIGN)
        state = advance(state, Phase.DESIGN, skip_reasons={"specification": "behavior is unchanged"})
        state = advance(state, Phase.READY)
        state = advance(state, Phase.EXECUTION)
        state = advance(state, Phase.VERIFICATION)
        with self.assertRaisesRegex(PhaseError, "Review Readiness"):
            advance(state, Phase.USER_REVIEW)
        state = advance(state, Phase.USER_REVIEW, readiness_passed=True)
        with self.assertRaisesRegex(PhaseError, "changes_requested"):
            advance(state, Phase.EXECUTION)
        state = advance(state, Phase.EXECUTION, changes_requested=True)
        self.assertIs(state.phase, Phase.EXECUTION)

    def test_issue_closure_requires_user_approval_and_merge_or_parent_integration(self):
        child = PhaseState(9, IssueKind.CHILD, Phase.USER_REVIEW)
        with self.assertRaisesRegex(PhaseError, "explicit user approval"):
            advance(child, Phase.CLOSED, merged=True)
        with self.assertRaisesRegex(PhaseError, "PR is merged"):
            advance(child, Phase.CLOSED, user_approved=True)
        self.assertIs(advance(child, Phase.CLOSED, user_approved=True, merged=True).phase, Phase.CLOSED)
        parent = PhaseState(8, IssueKind.PARENT, Phase.INTEGRATION)
        with self.assertRaisesRegex(PhaseError, "Integration must pass"):
            advance(parent, Phase.USER_REVIEW)
        parent = advance(parent, Phase.USER_REVIEW, integration_passed=True)
        with self.assertRaisesRegex(PhaseError, "every child"):
            advance(parent, Phase.CLOSED, user_approved=True, all_children_merged=False)
        self.assertIs(advance(parent, Phase.CLOSED, user_approved=True, all_children_merged=True).phase,
                      Phase.CLOSED)

    def test_parent_cannot_enter_ready_before_the_issue_graph_is_validated(self):
        parent = PhaseState(26, IssueKind.PARENT, Phase.REQUIREMENTS)
        with self.assertRaisesRegex(PhaseError, "issue graph"):
            advance(parent, Phase.READY)
        self.assertIs(advance(parent, Phase.READY, issue_graph_validated=True).phase, Phase.READY)

    def test_invalid_phase_or_attention_labels_fail_closed(self):
        with self.assertRaisesRegex(PhaseError, "exactly one"):
            parse_phase_labels(["phase:execution", "phase:user-review"])
        with self.assertRaisesRegex(PhaseError, "unknown phase"):
            parse_phase_labels(["phase:review"])
        with self.assertRaisesRegex(PhaseError, "at most one"):
            parse_attention_labels(["attention:blocked", "attention:waiting-user"])


class ExecutionBindingTests(unittest.TestCase):
    def test_binding_is_exact_and_round_trips(self):
        binding = ExecutionBinding(
            repository="octo/repo", issue_number=12, adc_comment_id=123,
            adc_sha256="a" * 64, base_ref="main", base_sha="b" * 40,
            work_directory="/workspace/repo", initial_head_sha="b" * 40,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".p-ases" / "binding.json"
            write_binding(path, binding)
            self.assertEqual(read_binding(path), binding)
            self.assertEqual(binding_digest(read_binding(path)), binding_digest(binding))
            write_binding(path, binding)
            changed = ExecutionBinding(
                repository="octo/repo", issue_number=12, adc_comment_id=123,
                adc_sha256="a" * 64, base_ref="release", base_sha="c" * 40,
                work_directory="/workspace/repo", initial_head_sha="c" * 40,
            )
            with self.assertRaisesRegex(ExecutionError, "frozen and cannot be replaced"):
                write_binding(path, changed)

    def test_binding_rejects_changed_base_or_malformed_sha(self):
        binding = ExecutionBinding(
            repository="octo/repo", issue_number=12, adc_comment_id=123,
            adc_sha256="a" * 64, base_ref="main", base_sha="b" * 40,
            work_directory="/workspace/repo", initial_head_sha="c" * 40,
        )
        with self.assertRaisesRegex(ExecutionError, "equal the frozen base"):
            binding.validate()
        invalid = ExecutionBinding(
            repository="octo/repo", issue_number=12, adc_comment_id=123,
            adc_sha256="a" * 64, base_ref="main..evil", base_sha="b" * 40,
            work_directory="/workspace/repo", initial_head_sha="b" * 40,
        )
        with self.assertRaisesRegex(ExecutionError, "base ref is invalid"):
            invalid.validate()


if __name__ == "__main__":
    unittest.main()
