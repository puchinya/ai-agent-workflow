from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import ADCPointer, VerifiedADC, parse_adc, publish_adc
from p_ases.execution import ExecutionBinding, ExecutionError, binding_digest, read_binding, write_binding
from p_ases.github import GitHubError
from p_ases.gate_policy import ActivationRecord, GateSelection, PASES_POLICY
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
from p_ases.phase_evidence import (
    PhaseDecision, PhaseEvidenceError, _check_activation, _collect_payload, _readback,
    _validate_ready_traceability,
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
        self.lose_create_issue_response = False
        self.sub_issue_calls = 0
        self.fail_sub_issue_call: int | None = None
        self.label_definitions: dict[str, dict[str, str]] = {}

    def issue(self, number: int) -> dict[str, object]:
        return copy.deepcopy(self.records[number])

    def issues(self) -> list[dict[str, object]]:
        return [copy.deepcopy(issue) for issue in self.records.values()]

    def repository_labels(self) -> list[dict[str, str]]:
        return [copy.deepcopy(row) for row in self.label_definitions.values()]

    def create_repository_label(self, name: str, color: str, description: str) -> dict[str, str]:
        if name in self.label_definitions:
            raise GitHubError("label already exists")
        row = {"name": name, "color": color, "description": description}
        self.label_definitions[name] = row
        return copy.deepcopy(row)

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
            "labels": [{"name": label} for label in (labels or [])],
        }
        self.records[number] = issue
        self.blocker_ids[number] = set()
        if self.lose_create_issue_response:
            self.lose_create_issue_response = False
            raise GitHubError("simulated lost child Issue create response")
        return copy.deepcopy(issue)

    def create_issue_comment(self, number: int, body: str) -> dict[str, object]:
        comment_id = self.next_comment
        self.next_comment += 1
        comment = {
            "id": comment_id,
            "body": body,
            "issue_url": f"https://api.github.com/repos/octo/repo/issues/{number}",
            "user": {"id": 101, "login": "octo"},
            "author_association": "OWNER",
        }
        self.comments[comment_id] = comment
        return copy.deepcopy(comment)

    def issue_comment(self, number: int, comment_id: int) -> dict[str, object]:
        return copy.deepcopy(self.comments[comment_id])

    def issue_comments(self, number: int) -> list[dict[str, object]]:
        suffix = f"/issues/{number}"
        return [copy.deepcopy(comment) for comment in self.comments.values()
                if comment.get("issue_url", "").endswith(suffix)]

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
        github.records[first[0].number]["labels"] = [
            {"name": "enhancement"}, {"name": "kind:child"}, {"name": "phase:execution"},
        ]
        second = split_issue(github, 1, parent_sha, ("REQ-01", "REQ-02"), children)
        self.assertEqual(first, second)
        self.assertEqual(github.create_issue_calls, 2)
        self.assertIn("phase:execution", [row["name"] for row in github.records[first[0].number]["labels"]])
        for record in github.records.values():
            if record.get("number") != 1:
                names = [row["name"] for row in record["labels"]]
                self.assertIn("kind:child", names)
                self.assertIn("phase:execution" if record.get("number") == first[0].number else "phase:requirements", names)
                self.assertIn("enhancement", names)
        self.assertEqual(github.label_definitions["kind:child"]["color"], "c5def5")

    def test_split_recovers_a_lost_issue_create_response_by_exact_marker_readback(self):
        github = FakeGitHub()
        parent_pointer = publish_adc(github, 1, adc_bytes(issue=1), state="approved", explicitly_approved=True)
        github.lose_create_issue_response = True
        result = split_issue(github, 1, parent_pointer.sha256, ("REQ-01",),
                             (child_plan("core", ("REQ-01",)),))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].number, 2)
        self.assertEqual(github.create_issue_calls, 1)
        names = [row["name"] for row in github.records[2]["labels"]]
        self.assertEqual(set(names), {"enhancement", "kind:child", "phase:requirements"})

    def test_split_fails_before_child_creation_when_owned_label_definition_conflicts(self):
        github = FakeGitHub()
        parent_pointer = publish_adc(github, 1, adc_bytes(issue=1), state="approved", explicitly_approved=True)
        github.label_definitions["kind:child"] = {
            "name": "kind:child", "color": "ffffff", "description": "local override",
        }
        with self.assertRaisesRegex(IssueGraphError, "conflicts"):
            split_issue(github, 1, parent_pointer.sha256, ("REQ-01",),
                        (child_plan("core", ("REQ-01",)),))
        self.assertEqual(github.create_issue_calls, 0)

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
        self.assertEqual(len(github.comments), 9)
        retry = split_issue(github, 1, parent_pointer.sha256, ("REQ-01", "REQ-02"), children)
        self.assertEqual([item.key for item in retry], ["core", "docs"])
        self.assertEqual(github.create_issue_calls, 2)
        self.assertEqual(len(github.comments), 9)

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
        self.assertEqual(len(github.comments), 3)

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
        with self.assertRaisesRegex(PhaseError, "match exactly"):
            advance(state, Phase.DESIGN, skip_reasons={
                "specification": "unchanged", "design": "also unchanged",
            })
        with self.assertRaisesRegex(PhaseError, "match exactly"):
            advance(PhaseState(1, IssueKind.CHILD, Phase.EXECUTION), Phase.VERIFICATION,
                    skip_reasons={"specification": "irrelevant"})

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

    def test_new_scope_returns_user_review_to_requirements_explicitly(self):
        state = PhaseState(1, IssueKind.CHILD, Phase.USER_REVIEW)
        with self.assertRaisesRegex(PhaseError, "new-scope decision"):
            advance(state, Phase.REQUIREMENTS)
        state = advance(state, Phase.REQUIREMENTS, new_requirements=True)
        self.assertIs(state.phase, Phase.REQUIREMENTS)

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


class PhaseEvidenceSchemaTests(unittest.TestCase):
    def payload(self):
        return {
            "schema": "PASES_PHASE_DECISION_V1",
            "repository": "octo/repo",
            "issue_number": 12,
            "issue_kind": "child",
            "from_phase": "requirements",
            "to_phase": "design",
            "adc_comment_id": 44,
            "adc_sha256": "a" * 64,
            "branch_ref": "issues/12",
            "commit_sha40": "b" * 40,
            "documents": [{"role": "design", "path": "docs/design/workflow-design.md",
                           "sha256": "c" * 64}],
            "skip_reasons": {"specification": "product behavior is unchanged"},
        }

    def test_phase_decision_uses_canonical_json_and_exact_schema(self):
        decision = PhaseDecision(self.payload())
        self.assertEqual(PhaseDecision.from_body(decision.body()), decision)
        with self.assertRaisesRegex(PhaseEvidenceError, "format|canonical"):
            PhaseDecision.from_body("PASES_PHASE_DECISION_V1\n" + json.dumps(self.payload(), indent=2) + "\n")
        unknown = self.payload() | {"approved": True}
        with self.assertRaisesRegex(PhaseEvidenceError, "unknown or missing"):
            PhaseDecision(unknown).body()  # Serialization never bypasses model validation below.

    def test_phase_decision_rejects_boolean_numbers_unsafe_paths_and_wrong_skip_edges(self):
        for change in (
            {"issue_number": True},
            {"documents": [{"role": "design", "path": "docs/design/../secret.md", "sha256": "c" * 64}]},
            {"documents": [{"role": "specification", "path": "docs/design/workflow-design.md", "sha256": "c" * 64}]},
            {"skip_reasons": {}},
        ):
            payload = self.payload() | change
            with self.subTest(change=change), self.assertRaises(PhaseEvidenceError):
                PhaseDecision(payload).body()


class PhaseEvidenceReadbackTests(unittest.TestCase):
    def setUp(self):
        self.decision = PhaseDecision(PhaseEvidenceSchemaTests().payload())
        self.base = {
            "id": 88,
            "body": self.decision.body(),
            "created_at": "2026-10-12T10:00:00Z",
            "updated_at": "2026-10-12T10:00:00Z",
            "issue_url": "https://api.github.com/repos/octo/repo/issues/12",
            "html_url": "https://github.com/octo/repo/issues/12#issuecomment-88",
            "url": "https://api.github.com/repos/octo/repo/issues/comments/88",
            "user": {"id": 101, "login": "octo", "type": "User", "avatar_url": "https://a"},
        }

    def test_readback_ignores_volatile_profile_urls_and_login_case(self):
        class Fake:
            repo = "octo/repo"

            def __init__(self, base):
                self.rows = []
                self.base = base
                self.direct_count = 0
                self.list_count = 0

            def authenticated_user(self):
                return {"id": 101, "login": "Octo", "type": "User"}

            def issue_comment(self, _number, _comment_id):
                self.direct_count += 1
                row = copy.deepcopy(self.base)
                row["user"]["avatar_url"] = f"https://profile/{self.direct_count}"
                if self.direct_count == 2:
                    row["user"]["login"] = "OCTO"
                return row

            def issue_comments(self, _number):
                self.list_count += 1
                row = copy.deepcopy(self.base)
                row["user"]["avatar_url"] = "https://profile/list"
                row["user"]["login"] = "oCtO"
                return [row]

        parsed = _readback(Fake(self.base), 12, 88, self.decision.body())
        self.assertEqual(parsed, self.decision)

    def test_readback_rejects_comment_edit_and_duplicate_transition_subject(self):
        class Fake:
            repo = "octo/repo"

            def __init__(self, base, *, edit=False, duplicate=False):
                self.base, self.edit, self.duplicate = base, edit, duplicate
                self.direct_count = 0

            def authenticated_user(self):
                return {"id": 101, "login": "octo", "type": "User"}

            def issue_comment(self, _number, _comment_id):
                self.direct_count += 1
                row = copy.deepcopy(self.base)
                if self.edit and self.direct_count == 2:
                    row["updated_at"] = "2026-10-12T10:01:00Z"
                return row

            def issue_comments(self, _number):
                rows = [copy.deepcopy(self.base)]
                if self.duplicate:
                    duplicate = copy.deepcopy(self.base)
                    duplicate["id"] = 89
                    rows.append(duplicate)
                return rows

        with self.assertRaisesRegex(PhaseEvidenceError, "edited"):
            _readback(Fake(self.base, edit=True), 12, 88, self.decision.body())
        with self.assertRaisesRegex(PhaseEvidenceError, "duplicated or stale"):
            _readback(Fake(self.base, duplicate=True), 12, 88, self.decision.body())

    def test_readback_requires_authenticated_positive_user_identity(self):
        class Fake:
            repo = "octo/repo"

            def __init__(self, user):
                self.user = user

            def authenticated_user(self):
                return {"id": 101, "login": "octo", "type": "User"}

            def issue_comment(self, _number, _comment_id):
                row = copy.deepcopy(self_row)
                row["user"] = copy.deepcopy(self.user)
                return row

            def issue_comments(self, _number):
                row = self.issue_comment(_number, 88)
                return [row]

        self_row = self.base
        for user in (
            {"id": 102, "login": "octo", "type": "User"},
            {"id": True, "login": "octo", "type": "User"},
            {"id": 101, "login": "octo", "type": "Bot"},
        ):
            with self.subTest(user=user), self.assertRaisesRegex(
                    PhaseEvidenceError, "authenticated GitHub user"):
                _readback(Fake(user), 12, 88, self.decision.body())


class PhaseEvidenceActivationTests(unittest.TestCase):
    def setUp(self):
        self.repo = "puchinya/ai-agent-workflow"
        child_prs = tuple((issue, issue + 6, f"{issue:040x}") for issue in range(27, 33))
        self.activation = ActivationRecord(
            self.repo, tuple(range(27, 33)), child_prs, tuple(range(27, 33)), "a" * 64,
            300, PASES_POLICY, "b" * 40, 301, "2026-10-11T01:30:00Z",
        )
        self.gate = GateSelection(
            self.repo, 40, PASES_POLICY, "2026-10-11T02:00:00Z", 999, self.activation.sha256,
        )

        class Fake:
            repo = self.repo

            def issue(_self, _number):
                return {"number": 40, "pull_request": None, "created_at": "2026-10-11T01:45:00Z"}

        self.github = Fake()

    def test_requires_gate_selection_bound_to_exact_activation_and_post_activation_issue(self):
        with patch("p_ases.phase_evidence.read_activation_record", return_value=(self.activation, 999)), \
                patch("p_ases.phase_evidence.read_gate_selection", return_value=(302, self.gate, "body")):
            _check_activation(self.github, 40)

        stale_gate = GateSelection(
            self.repo, 40, PASES_POLICY, "2026-10-11T02:00:00Z", 998, self.activation.sha256,
        )
        with patch("p_ases.phase_evidence.read_activation_record", return_value=(self.activation, 999)), \
                patch("p_ases.phase_evidence.read_gate_selection", return_value=(302, stale_gate, "body")):
            with self.assertRaisesRegex(PhaseEvidenceError, "exact P-ASES Gate Selection"):
                _check_activation(self.github, 40)

    def test_rejects_issue_created_before_activation(self):
        self.github.issue = lambda _number: {
            "number": 40, "pull_request": None, "created_at": "2026-10-11T01:00:00Z",
        }
        with patch("p_ases.phase_evidence.read_activation_record", return_value=(self.activation, 999)), \
                patch("p_ases.phase_evidence.read_gate_selection", return_value=(302, self.gate, "body")):
            with self.assertRaisesRegex(PhaseEvidenceError, "exact P-ASES Gate Selection"):
                _check_activation(self.github, 40)


class ReadyTraceabilityTests(unittest.TestCase):
    def test_ready_requires_linked_design_oracle_test_and_existing_source(self):
        matrix = (ROOT / "docs/testing/traceability.md").read_bytes()

        class Fake:
            def regular_content_at_ref(self, path, _commit):
                if path != "tests/test_issue_phases.py":
                    raise PhaseEvidenceError("unexpected source")
                return (ROOT / path).read_bytes()

        _validate_ready_traceability(ROOT, "docs/testing/traceability.md", matrix, Fake(),
                                     "b" * 40, ("REQ-WF-001",))
        with self.assertRaisesRegex(PhaseEvidenceError, "does not cover"):
            _validate_ready_traceability(ROOT, "docs/testing/traceability.md", matrix, Fake(),
                                         "b" * 40, ("REQ-UNKNOWN-999",))

    def test_ready_requires_actual_local_links_for_each_traceability_identity(self):
        matrix = (ROOT / "docs/testing/traceability.md").read_bytes().replace(
            b"[DES-WF-001](../design/workflow-design.md#des-wf-001)", b"[DES-WF-001]",
        )

        class Fake:
            def regular_content_at_ref(self, path, _commit):
                return (ROOT / path).read_bytes()

        with self.assertRaisesRegex(PhaseEvidenceError, "missing linked REQ/DES/Oracle/Test anchors"):
            _validate_ready_traceability(ROOT, "docs/testing/traceability.md", matrix, Fake(),
                                         "b" * 40, ("REQ-WF-001",))


class PhaseEvidenceCollectionTests(unittest.TestCase):
    def make_repository(self, root: Path) -> tuple[str, VerifiedADC]:
        repository = "puchinya/ai-agent-workflow"
        files = {
            "docs/specs/product.md": b"# Product specification\n",
            "docs/design/system.md": b"# Technical design\n",
            "docs/testing/oracle.md": b"# Independent Oracle\n",
            "docs/testing/traceability.md": b"# Traceability\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        for command in (
            ["git", "init", "-b", "issues/40"],
            ["git", "add", "docs"],
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
             "commit", "-m", "phase evidence fixtures"],
        ):
            subprocess.run(command, cwd=root, check=True, capture_output=True)
        adc = adc_bytes(repository, issue=40).replace(
            b"Runtime and tests are created; product behavior is unchanged.",
            b"- Specification: docs/specs/product.md\n"
            b"- Design: docs/design/system.md\n"
            b"- Testing: docs/testing/oracle.md, docs/testing/traceability.md",
        )
        contract = parse_adc(adc, repository, 40)
        verified = VerifiedADC(contract, ADCPointer(88, contract.sha256, len(adc), "approved"))
        return repository, verified

    def test_collection_binds_approved_adc_and_artifacts_to_regular_branch_blobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, verified = self.make_repository(root)

            class FakeGitHub:
                repo = repository

                def issue(_self, number):
                    return {
                        "number": number, "state": "open", "pull_request": None,
                        "repository_url": f"https://api.github.com/repos/{repository}",
                        "labels": [{"name": "kind:single"}, {"name": "phase:requirements"}],
                    }

                def branch(_self, branch):
                    return {"name": branch, "commit": {"sha": commit_sha}}

                def regular_content_at_ref(_self, path, ref):
                    if ref != commit_sha:
                        raise GitHubError("wrong commit")
                    return subprocess.run(
                        ["git", "show", f"{ref}:{path}"], cwd=root, check=True,
                        capture_output=True,
                    ).stdout

            commit_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
            ).stdout.strip()
            with patch("p_ases.phase_evidence._check_activation"), \
                    patch("p_ases.phase_evidence.verify_adc", return_value=verified):
                decision, _issue, _adc, branch, commit = _collect_payload(
                    FakeGitHub(), root, 40, Phase.REQUIREMENTS, Phase.SPECIFICATION, {},
                )
            self.assertEqual((branch, commit), ("issues/40", commit_sha))
            self.assertEqual(decision.payload["adc_sha256"], verified.contract.sha256)
            self.assertEqual([row["path"] for row in decision.payload["documents"]], [
                "docs/design/system.md", "docs/specs/product.md", "docs/testing/oracle.md",
                "docs/testing/traceability.md",
            ])

    def test_uncommitted_document_change_blocks_phase_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, verified = self.make_repository(root)
            (root / "docs/specs/product.md").write_bytes(b"uncommitted change\n")
            commit_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
            ).stdout.strip()

            class FakeGitHub:
                repo = repository

                def issue(_self, number):
                    return {
                        "number": number, "state": "open", "pull_request": None,
                        "repository_url": f"https://api.github.com/repos/{repository}",
                        "labels": [{"name": "kind:single"}, {"name": "phase:requirements"}],
                    }

                def branch(_self, branch):
                    return {"name": branch, "commit": {"sha": commit_sha}}

                def regular_content_at_ref(_self, path, ref):
                    return subprocess.run(
                        ["git", "show", f"{ref}:{path}"], cwd=root, check=True,
                        capture_output=True,
                    ).stdout

            with patch("p_ases.phase_evidence._check_activation"), \
                    patch("p_ases.phase_evidence.verify_adc", return_value=verified):
                with self.assertRaisesRegex(PhaseEvidenceError, "working-tree bytes differ"):
                    _collect_payload(FakeGitHub(), root, 40, Phase.REQUIREMENTS,
                                     Phase.SPECIFICATION, {})


class ReadmeWorkflowGraphTests(unittest.TestCase):
    EDGE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)(?:\[[^]]+\])?\s*(-->|-\.->)\s*(?:\|[^|]+\|\s*)?([A-Za-z_][A-Za-z0-9_]*)(?:\[[^]]+\])?\s*$")

    def read_graph(self, name: str):
        text = (ROOT / name).read_text(encoding="utf-8")
        blocks = re.findall(r"```mermaid\s*\n(.*?)\n```", text, re.DOTALL)
        self.assertEqual(len(blocks), 1, name)
        self.assertTrue(blocks[0].startswith("flowchart TD"))
        edges = []
        for line in blocks[0].splitlines():
            match = self.EDGE.fullmatch(line)
            if match:
                edges.append((match.group(1), match.group(3), match.group(2)))
            elif "-->" in line or "-.->" in line:
                self.fail(f"unsupported Mermaid edge in {name}: {line}")
        return edges, blocks[0]

    def test_bilingual_readme_graphs_have_identical_child_topology(self):
        en, en_text = self.read_graph("README.md")
        ja, ja_text = self.read_graph("README.ja.md")
        self.assertEqual({(a, b) for a, b, _ in en}, {(a, b) for a, b, _ in ja})
        self.assertEqual(sum(kind == "-.->" for _, _, kind in en), 3)
        self.assertEqual(sum(kind == "-.->" for _, _, kind in ja), 3)
        edges = {(a, b) for a, b, _ in en}
        self.assertTrue({("req", "spec"), ("spec", "design"), ("design", "ready"),
                         ("ready", "exec"), ("exec", "verify"), ("verify", "review"),
                         ("review", "merge"), ("merge", "closed"), ("req", "design"),
                         ("spec", "ready"), ("req", "ready"), ("review", "exec"),
                         ("review", "req")} <= edges)
        self.assertNotIn("parent_issue", en_text)
        self.assertNotIn("parent_issue", ja_text)
        self.assertIn("separate specification and design reasons", en_text)
        self.assertIn("仕様と設計それぞれの理由", ja_text)


class ExecutionBindingTests(unittest.TestCase):
    def test_binding_is_exact_and_round_trips(self):
        with tempfile.TemporaryDirectory() as temporary:
            binding = ExecutionBinding(
                repository="octo/repo", issue_number=12, adc_comment_id=123,
                adc_sha256="a" * 64, base_ref="main", base_sha="b" * 40,
                work_directory=str(Path(temporary) / "repo"), initial_head_sha="b" * 40,
            )
            path = Path(temporary) / ".p-ases" / "binding.json"
            write_binding(path, binding)
            self.assertEqual(read_binding(path), binding)
            self.assertEqual(binding_digest(read_binding(path)), binding_digest(binding))
            write_binding(path, binding)
            changed = ExecutionBinding(
                repository="octo/repo", issue_number=12, adc_comment_id=123,
                adc_sha256="a" * 64, base_ref="release", base_sha="c" * 40,
                work_directory=str(Path(temporary) / "repo"), initial_head_sha="c" * 40,
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
