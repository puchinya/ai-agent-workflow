from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.gate_policy import (
    GatePolicyError, LegacyGateSelection, PASES_POLICY, GateSelection, read_gate_selection,
)
from p_ases.legacy_adoption import (
    ACCEPTED_RISK_IDS, ADOPTION_SCHEMA, LEGACY_GATE_SCHEMA, OWNER_APPROVAL_SCHEMA,
    PLAN_SCHEMA, PLAN_SCHEMA_V1,
    RESET_APPLIED_SCHEMA, RESET_INTENT_SCHEMA, RESET_PLAN_SCHEMA,
    LegacyAdoptionError, LegacyAdoptionPlan, _body, _digest, _validate_plan_payload,
    LegacyResetPlan, _read_reset_state, apply_legacy_adoption, apply_legacy_reset,
    build_legacy_adoption_plan, build_legacy_reset_plan, owner_approval_comment,
    validate_bootstrap_authorization_record,
    validate_bootstrap_changed_paths, read_bootstrap_authorization_record,
    validate_bootstrap_prework_subject, verify_legacy_gate_selection, verify_owner_approval,
)
from p_ases.github import GitHubError
from p_ases.phase_evidence import PhaseEvidenceError, _check_activation


def make_plan(*, phase: str = "requirements", labels: list[str] | None = None) -> LegacyAdoptionPlan:
    repo = "puchinya/ai-agent-workflow"
    labels = labels or ["enhancement", "kind:single", f"phase:{phase}"]
    gate = {
        "issue_number": 46,
        "policy_version": "legacy-issue-adopted-v1",
        "repository": repo,
        "schema": LEGACY_GATE_SCHEMA,
        "selected_at": "2026-10-21T15:00:00Z",
    }
    activation_records = [{"comment_id": 701, "record_sha256": "a" * 64}]
    activation_payload = {
        "activation_issue_number": 57,
        "records": activation_records,
        "schema": "PASES_LEGACY_ACTIVATION_PREFIX_V1",
    }
    payload = {
        "activation_issue_number": 57,
        "activation_prefix": {**activation_payload, "sha256": _digest(activation_payload)},
        "adc_comment_id": 801,
        "adc_sha256": "b" * 64,
        "adc_state": "approved",
        "attention_labels": [],
        "binding": None,
        "generated_at": "2026-10-21T15:00:00Z",
        "issue_created_at": "2026-10-14T10:57:28Z",
        "issue_id": 5846549384,
        "issue_kind": "single",
        "issue_labels": labels,
        "issue_number": 46,
        "owner_id": 3744776,
        "phase": phase,
        "planned_gate_payload": gate,
        "planned_gate_payload_sha256": _digest(gate),
        "proposed_phase_action": ("KEEP_REQUIREMENTS" if phase == "requirements"
                                  else "RESET_TO_REQUIREMENTS_REQUIRED"),
        "remote_head_ref": "main",
        "remote_head_sha": "c" * 40,
        "repository": repo,
        "repository_id": 1401910271,
        "schema": PLAN_SCHEMA,
        "accepted_risks": list(ACCEPTED_RISK_IDS),
        "writer_policy": {
            "max_active_writers": 1,
            "mode": "owner_trusted_single_writer_v1",
            "required_user_id": 3744776,
        },
    }
    return LegacyAdoptionPlan({**payload, "plan_sha256": _digest(payload)}).validate()


def make_reset_plan() -> LegacyResetPlan:
    payload = {
        "adoption_comment_id": 910,
        "adoption_record_sha256": "a" * 64,
        "generated_at": "2026-10-21T15:00:00Z",
        "issue_created_at": "2026-10-14T10:57:28Z",
        "issue_id": 804,
        "issue_kind": "single",
        "issue_labels": ["enhancement", "kind:single", "phase:specification"],
        "issue_number": 40,
        "owner_id": 900,
        "phase": "specification",
        "repository": "octo/repo",
        "repository_id": 901,
        "schema": RESET_PLAN_SCHEMA,
        "target_labels": ["enhancement", "kind:single", "phase:requirements"],
    }
    return LegacyResetPlan({**payload, "plan_sha256": _digest(payload)}).validate()


def comment_row(comment_id: int, body: str, *, user_id: int = 900, login: str = "octo",
                user_type: str = "User", updated_at: str = "2026-10-21T15:01:00Z",
                repository: str = "octo/repo", issue_number: int = 40,
                issue_url: str | None = None,
                html_url: str | None = None, url: str | None = None) -> dict:
    issue_url = issue_url or f"https://api.github.com/repos/{repository}/issues/{issue_number}"
    return {
        "id": comment_id,
        "body": body,
        "created_at": "2026-10-21T15:01:00Z",
        "updated_at": updated_at,
        "issue_url": issue_url,
        "html_url": html_url or f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}",
        "url": url or f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}",
        "user": {"id": user_id, "login": login, "type": user_type},
    }


class FakeGitHub:
    def __init__(self, rows: list[dict] | None = None, *, labels: list[str] | None = None,
                 repository: str = "octo/repo", issue_number: int = 40,
                 owner_id: int = 900, owner_login: str = "octo",
                 repository_id: int = 901, issue_id: int = 804,
                 authenticated_id: int | None = None):
        self.repo = repository
        self.issue_number = issue_number
        self.owner_id = owner_id
        self.owner_login = owner_login
        self.repository_id = repository_id
        self.issue_id = issue_id
        self.authenticated_id = owner_id if authenticated_id is None else authenticated_id
        self.rows = list(rows or [])
        self.labels = labels or ["enhancement", "kind:single", "phase:requirements"]
        self.next_id = max((row["id"] for row in self.rows), default=900) + 1
        self.comment_posts = 0
        self.label_writes = 0
        self.lose_next_comment_response = False
        self.lose_comment_response_at = None
        self.lose_next_label_response = False

    def repository_metadata(self):
        return {"id": self.repository_id,
                "owner": {"id": self.owner_id, "login": self.owner_login, "type": "User"}}

    def authenticated_user(self):
        return {"id": self.authenticated_id, "login": self.owner_login, "type": "User"}

    def issue_comments(self, _issue_number):
        return list(self.rows)

    def issue_comment(self, _issue_number, comment_id):
        found = [row for row in self.rows if row["id"] == comment_id]
        if len(found) != 1:
            raise RuntimeError("missing comment")
        return dict(found[0])

    def issue(self, number):
        return {"number": number, "id": self.issue_id, "state": "open", "pull_request": None,
                "repository_url": f"https://api.github.com/repos/{self.repo}",
                "created_at": "2026-10-14T10:57:28Z",
                "labels": [{"name": x} for x in self.labels]}

    def create_issue_comment(self, issue_number, body):
        self.comment_posts += 1
        comment_id = self.next_id
        self.next_id += 1
        is_adoption_record = body.startswith((f"<!-- {ADOPTION_SCHEMA}\n", f"<!-- {LEGACY_GATE_SCHEMA}\n"))
        row = comment_row(
            comment_id, body,
            user_id=self.owner_id if is_adoption_record else 1000,
            login=self.owner_login if is_adoption_record else "workflow-bot",
            user_type="User" if is_adoption_record else "Bot",
            repository=self.repo, issue_number=issue_number,
            updated_at="2026-10-21T15:02:00Z",
        )
        row["created_at"] = "2026-10-21T15:02:00Z"
        self.rows.append(row)
        if self.lose_next_comment_response or self.comment_posts == self.lose_comment_response_at:
            self.lose_next_comment_response = False
            self.lose_comment_response_at = None
            raise GitHubError("simulated lost response")
        return row

    def replace_issue_labels(self, issue_number, labels):
        self.label_writes += 1
        self.labels = list(labels)
        if self.lose_next_label_response:
            self.lose_next_label_response = False
            raise GitHubError("simulated lost response")
        return self.issue(issue_number)


def adoption_github(rows: list[dict] | None = None, *, authenticated_id: int | None = None,
                    labels: list[str] | None = None) -> FakeGitHub:
    return FakeGitHub(
        rows, labels=labels, repository="puchinya/ai-agent-workflow", issue_number=46,
        owner_id=3744776, owner_login="puchinya", repository_id=1401910271,
        issue_id=5846549384, authenticated_id=authenticated_id,
    )


def adoption_comment(comment_id: int, body: str, *, user_id: int = 3744776,
                     login: str = "puchinya", updated_at: str = "2026-10-21T15:01:00Z",
                     issue_url: str | None = None) -> dict:
    return comment_row(
        comment_id, body, user_id=user_id, login=login, updated_at=updated_at,
        repository="puchinya/ai-agent-workflow", issue_number=46, issue_url=issue_url,
    )


class LegacyAdoptionContractTests(unittest.TestCase):
    def test_legacy_gate_is_typed_and_has_one_way_adoption_link(self):
        selection_core = {
            "issue_number": 40,
            "policy_version": "legacy-issue-adopted-v1",
            "repository": "octo/repo",
            "schema": LEGACY_GATE_SCHEMA,
            "selected_at": "2026-10-21T15:00:00Z",
        }
        gate = LegacyGateSelection(
            repository="octo/repo", issue_number=40, policy_version="legacy-issue-adopted-v1",
            selected_at=selection_core["selected_at"], adoption_comment_id=9011,
            adoption_record_sha256="a" * 64,
            selection_sha256=_digest(selection_core),
        ).validate()
        self.assertEqual(gate.selection_payload(), selection_core)
        self.assertEqual(LegacyGateSelection.from_payload(gate.payload()), gate)
        with self.assertRaises(GatePolicyError):
            LegacyGateSelection.from_payload({**gate.payload(), "selection_sha256": "0" * 64})

    def test_ordinary_gate_payload_remains_the_existing_v1_shape(self):
        selection = GateSelection("octo/repo", 40, PASES_POLICY, "2026-10-21T15:00:00Z", 45, "a" * 64, 57)
        self.assertEqual(selection.payload()["schema"], "PASES_GATE_SELECTION_V1")
        self.assertNotIn("adoption_comment_id", selection.payload())

    def test_read_gate_selection_returns_typed_legacy_v1_and_rejects_conflict(self):
        core = {
            "issue_number": 40, "policy_version": "legacy-issue-adopted-v1",
            "repository": "octo/repo", "schema": LEGACY_GATE_SCHEMA,
            "selected_at": "2026-10-21T15:00:00Z",
        }
        gate = LegacyGateSelection(
            repository="octo/repo", issue_number=40, policy_version="legacy-issue-adopted-v1",
            selected_at=core["selected_at"], adoption_comment_id=901,
            adoption_record_sha256="a" * 64, selection_sha256=_digest(core),
        ).validate()
        body = _body(LEGACY_GATE_SCHEMA, gate.payload())
        row = comment_row(902, body)
        comment_id, parsed, _ = read_gate_selection(FakeGitHub([row]), 40)
        self.assertEqual((comment_id, parsed), (902, gate))
        ordinary = GateSelection("octo/repo", 40, PASES_POLICY, "2026-10-21T15:00:00Z", 903, "b" * 64, 57)
        ordinary_row = comment_row(904, _body("PASES_GATE_SELECTION_V1", ordinary.payload()))
        with self.assertRaisesRegex(GatePolicyError, "missing or duplicated"):
            read_gate_selection(FakeGitHub([row, ordinary_row]), 40)

    def test_bootstrap_authorization_record_is_exact_scope_bound_and_operator_reported(self):
        record_fields = [
            "schema", "scope_sha256", "repository_id", "owner_user_id", "issue_number",
            "issue_stable_id", "adc_comment_id", "adc_sha256", "activation_prefix_sha256",
            "binding_sha256", "branch_ref", "prework_head_sha", "changed_file_budget_sha256",
            "decision", "approval_channel", "decision_observed_at",
        ]
        scope_body = {
            "operation": "ISSUE_46_STAGE_1_LEGACY_ADMISSION_BOOTSTRAP",
            "schema": "PASES_LEGACY_BOOTSTRAP_SCOPE_V1",
            "repository": {"repository_id": 1401910271, "owner_user_id": 3744776},
            "issue": {"number": 46, "stable_id": 5846549384},
            "approved_adc": {"comment_id": 6319520907,
                             "sha256": "d" * 64},
            "activation_prefix": {"prefix_sha256": "e" * 64},
            "execution_binding": {"generations": [{"binding_sha256": "f" * 64}]},
            "prework_subject": {"base_ref": "main", "base_sha": "b" * 40,
                                "branch_ref": "codex/issue-46", "local_head_sha": "a" * 40,
                                "remote_head_sha": "a" * 40, "worktree_clean": True},
            "changed_file_budget": {"max_tracked_files": 1,
                                     "paths": ["runtime/p_ases/legacy_adoption.py"]},
            "authorization_record": {
                "schema": "PASES_LEGACY_BOOTSTRAP_AUTHORIZATION_V1",
                "record_path": ".p_ases/state/46/legacy-bootstrap-authorization-v1.json",
                "record_fields": record_fields,
            },
        }
        scope = {"scope": scope_body, "scope_sha256": _digest(scope_body)}
        record = {
            "activation_prefix_sha256": "e" * 64, "adc_comment_id": 6319520907,
            "adc_sha256": "d" * 64, "approval_channel": "same-conversation direct user-role response",
            "binding_sha256": "f" * 64, "branch_ref": "codex/issue-46",
            "changed_file_budget_sha256": hashlib.sha256(
                json.dumps(scope_body["changed_file_budget"]["paths"], separators=(",", ":")).encode()
            ).hexdigest(),
            "decision": "APPROVED", "decision_observed_at": "2026-10-21T15:28:12Z",
            "issue_number": 46, "issue_stable_id": 5846549384, "owner_user_id": 3744776,
            "prework_head_sha": "a" * 40, "repository_id": 1401910271,
            "schema": "PASES_LEGACY_BOOTSTRAP_AUTHORIZATION_V1", "scope_sha256": scope["scope_sha256"],
        }
        self.assertIs(validate_bootstrap_authorization_record(record, scope), record)
        self.assertEqual(validate_bootstrap_changed_paths(
            ["runtime/p_ases/legacy_adoption.py"], scope), ("runtime/p_ases/legacy_adoption.py",))
        self.assertIs(validate_bootstrap_prework_subject(scope_body["prework_subject"], scope),
                      scope_body["prework_subject"])
        with self.assertRaisesRegex(LegacyAdoptionError, "pre-work subject"):
            validate_bootstrap_prework_subject({**scope_body["prework_subject"], "worktree_clean": False}, scope)
        with self.assertRaisesRegex(LegacyAdoptionError, "exceed"):
            validate_bootstrap_changed_paths(["runtime/p_ases/cli.py"], scope)
        with self.assertRaises(LegacyAdoptionError):
            validate_bootstrap_authorization_record({**record, "binding_sha256": "0" * 64}, scope)
        bad_scope = {**scope, "scope_sha256": "0" * 64}
        with self.assertRaises(LegacyAdoptionError):
            validate_bootstrap_authorization_record(record, bad_scope)
        malformed_body = {**scope_body, "repository": None}
        malformed_scope = {"scope": malformed_body, "scope_sha256": _digest(malformed_body)}
        with self.assertRaisesRegex(LegacyAdoptionError, "field repository is malformed"):
            validate_bootstrap_authorization_record(record, malformed_scope)

    def test_bootstrap_record_reader_requires_canonical_record_and_exact_scoped_changes(self):
        record_fields = [
            "schema", "scope_sha256", "repository_id", "owner_user_id", "issue_number",
            "issue_stable_id", "adc_comment_id", "adc_sha256", "activation_prefix_sha256",
            "binding_sha256", "branch_ref", "prework_head_sha", "changed_file_budget_sha256",
            "decision", "approval_channel", "decision_observed_at",
        ]
        body = {
            "operation": "ISSUE_46_STAGE_1_LEGACY_ADMISSION_BOOTSTRAP",
            "schema": "PASES_LEGACY_BOOTSTRAP_SCOPE_V1",
            "repository": {"repository_id": 1401910271, "owner_user_id": 3744776},
            "issue": {"number": 46, "stable_id": 5846549384},
            "approved_adc": {"comment_id": 6319520907, "sha256": "d" * 64},
            "activation_prefix": {"prefix_sha256": "e" * 64},
            "execution_binding": {"generations": [{"binding_sha256": "f" * 64}]},
            "prework_subject": {"base_ref": "main", "base_sha": "b" * 40,
                                "branch_ref": "codex/issue-46", "local_head_sha": "a" * 40,
                                "remote_head_sha": "a" * 40, "worktree_clean": True},
            "changed_file_budget": {"max_tracked_files": 1,
                                     "paths": ["runtime/p_ases/legacy_adoption.py"]},
            "authorization_record": {
                "schema": "PASES_LEGACY_BOOTSTRAP_AUTHORIZATION_V1",
                "record_path": ".p_ases/state/46/legacy-bootstrap-authorization-v1.json",
                "record_fields": record_fields,
            },
        }
        scope = {"scope": body, "scope_sha256": _digest(body)}
        record = {
            "activation_prefix_sha256": "e" * 64, "adc_comment_id": 6319520907,
            "adc_sha256": "d" * 64, "approval_channel": "same-conversation direct user-role response",
            "binding_sha256": "f" * 64, "branch_ref": "codex/issue-46",
            "changed_file_budget_sha256": hashlib.sha256(
                json.dumps(body["changed_file_budget"]["paths"], separators=(",", ":")).encode()
            ).hexdigest(),
            "decision": "APPROVED", "decision_observed_at": "2026-10-21T15:28:12Z",
            "issue_number": 46, "issue_stable_id": 5846549384, "owner_user_id": 3744776,
            "prework_head_sha": "a" * 40, "repository_id": 1401910271,
            "schema": "PASES_LEGACY_BOOTSTRAP_AUTHORIZATION_V1", "scope_sha256": scope["scope_sha256"],
        }
        with tempfile.TemporaryDirectory() as directory:
            record_path = Path(directory) / "authorization.json"
            scope_path = Path(directory) / "scope.json"
            record_path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            scope_path.write_text(json.dumps(scope))
            loaded = read_bootstrap_authorization_record(
                record_path, scope_path, changed_paths=["runtime/p_ases/legacy_adoption.py"],
                prework_subject=body["prework_subject"],
            )
            self.assertEqual(loaded, record)
            record_path.write_text(json.dumps(record, indent=2) + "\n")
            with self.assertRaisesRegex(LegacyAdoptionError, "canonical JSON"):
                read_bootstrap_authorization_record(record_path, scope_path)

    def test_plan_digest_and_gate_digest_are_both_checked(self):
        plan = make_plan()
        self.assertEqual(_validate_plan_payload(plan.value), plan.value)
        changed = {**plan.value, "remote_head_sha": "0" * 40}
        with self.assertRaises(LegacyAdoptionError):
            _validate_plan_payload(changed)
        changed_gate = {**plan.value, "planned_gate_payload_sha256": "0" * 64}
        with self.assertRaises(LegacyAdoptionError):
            _validate_plan_payload(changed_gate)

    def test_v1_plan_remains_readable_without_reinterpreting_it_as_risk_accepted(self):
        plan = make_plan()
        legacy = {key: value for key, value in plan.value.items()
                  if key not in {"accepted_risks", "writer_policy"}}
        legacy["schema"] = PLAN_SCHEMA_V1
        legacy.pop("plan_sha256")
        legacy["plan_sha256"] = _digest({key: value for key, value in legacy.items()
                                         if key != "plan_sha256"})
        self.assertEqual(_validate_plan_payload(legacy), legacy)
        with self.assertRaisesRegex(LegacyAdoptionError, "V2 risk-bound"):
            apply_legacy_adoption(adoption_github(), Path("."), LegacyAdoptionPlan(legacy), 930)

    def test_v2_plan_binds_both_risks_and_exact_single_owner_writer(self):
        plan = make_plan()
        self.assertEqual(plan.value["accepted_risks"], list(ACCEPTED_RISK_IDS))
        self.assertEqual(plan.value["writer_policy"], {
            "max_active_writers": 1,
            "mode": "owner_trusted_single_writer_v1",
            "required_user_id": 3744776,
        })
        changed = {**plan.value, "accepted_risks": [ACCEPTED_RISK_IDS[0]]}
        changed.pop("plan_sha256")
        changed["plan_sha256"] = _digest(changed)
        with self.assertRaisesRegex(LegacyAdoptionError, "both exact risks"):
            _validate_plan_payload(changed)
        for identity in ({"repository_id": 1}, {"owner_id": 1}):
            changed_identity = {**plan.value, **identity}
            changed_identity.pop("plan_sha256")
            changed_identity["plan_sha256"] = _digest(changed_identity)
            with self.subTest(identity=identity), self.assertRaisesRegex(
                    LegacyAdoptionError, "exact repository, Owner, and Issue #46"):
                _validate_plan_payload(changed_identity)

    def test_risk_accepted_adoption_plan_is_limited_to_issue_46(self):
        with self.assertRaisesRegex(LegacyAdoptionError, "limited to Issue #46"):
            build_legacy_adoption_plan(adoption_github(), Path("."), 47)

    def test_adoption_apply_requires_authenticated_repository_owner_before_writing(self):
        plan = make_plan()
        approval = adoption_comment(930, owner_approval_comment(plan))
        github = adoption_github([approval], authenticated_id=900)
        with patch("p_ases.legacy_adoption._fresh_plan", return_value=plan):
            with self.assertRaisesRegex(LegacyAdoptionError, "authenticated repository Owner"):
                apply_legacy_adoption(github, Path("."), plan, 930)
        self.assertEqual(github.comment_posts, 0)
        self.assertEqual(github.label_writes, 0)

    def test_owner_approval_requires_direct_list_direct_owner_identity_and_exact_urls(self):
        plan = make_plan()
        body = owner_approval_comment(plan)
        github = adoption_github([adoption_comment(930, body)])
        row = verify_owner_approval(github, plan, 930)
        self.assertEqual(row["user"]["id"], 3744776)
        wrong_owner = adoption_github([adoption_comment(930, body, user_id=900, login="other")])
        with self.assertRaisesRegex(LegacyAdoptionError, "repository Owner"):
            verify_owner_approval(wrong_owner, plan, 930)
        edited = adoption_github([adoption_comment(930, body, updated_at="2026-10-21T15:02:00Z")])
        with self.assertRaisesRegex(LegacyAdoptionError, "edited"):
            verify_owner_approval(edited, plan, 930)
        wrong_issue = adoption_github([adoption_comment(
            930, body, issue_url="https://api.github.com/repos/other/repo/issues/46")])
        with self.assertRaisesRegex(LegacyAdoptionError, "attribution"):
            verify_owner_approval(wrong_issue, plan, 930)

    def test_adoption_apply_is_stale_fail_closed_without_a_write(self):
        plan = make_plan()
        github = adoption_github()
        with patch("p_ases.legacy_adoption._fresh_plan", side_effect=LegacyAdoptionError("stale")), \
                patch("p_ases.legacy_adoption._append_record") as append:
            with self.assertRaisesRegex(LegacyAdoptionError, "stale"):
                apply_legacy_adoption(github, Path("."), plan, 930)
        append.assert_not_called()

    def test_adoption_apply_posts_exact_pair_once_and_never_writes_phase_labels(self):
        plan = make_plan()
        approval = adoption_comment(930, owner_approval_comment(plan))
        github = adoption_github([approval])
        with patch("p_ases.legacy_adoption._fresh_plan", return_value=plan):
            result = apply_legacy_adoption(github, Path("."), plan, 930)
        self.assertEqual(result["status"], "ADOPTED")
        self.assertEqual(result["risk_status"], "KNOWN_RISK_ACCEPTED_BY_OWNER")
        self.assertEqual(result["accepted_risks"], list(ACCEPTED_RISK_IDS))
        self.assertNotIn("PASS", result.values())
        self.assertEqual(github.comment_posts, 2)
        self.assertEqual(github.label_writes, 0)
        self.assertEqual(github.labels, ["enhancement", "kind:single", "phase:requirements"])
        markers = [row["body"].splitlines()[0] for row in github.rows if row["id"] > 930]
        self.assertEqual(markers, [f"<!-- {ADOPTION_SCHEMA}", f"<!-- {LEGACY_GATE_SCHEMA}"])

    def test_adoption_lost_post_response_blocks_then_recovers_without_duplicate_post(self):
        plan = make_plan()
        approval = adoption_comment(930, owner_approval_comment(plan))
        github = adoption_github([approval])
        github.lose_next_comment_response = True
        with patch("p_ases.legacy_adoption._fresh_plan", return_value=plan):
            with self.assertRaisesRegex(LegacyAdoptionError, "response is uncertain"):
                apply_legacy_adoption(github, Path("."), plan, 930)
            self.assertEqual(github.comment_posts, 1)
            result = apply_legacy_adoption(github, Path("."), plan, 930)
        self.assertEqual(result["status"], "ADOPTED")
        self.assertEqual(github.comment_posts, 2)
        self.assertEqual(github.label_writes, 0)

    def test_gate_lost_post_response_recovers_as_complete_readonly_noop(self):
        plan = make_plan()
        approval = adoption_comment(930, owner_approval_comment(plan))
        github = adoption_github([approval])
        github.lose_comment_response_at = 2
        with patch("p_ases.legacy_adoption._fresh_plan", return_value=plan):
            with self.assertRaisesRegex(LegacyAdoptionError, "response is uncertain"):
                apply_legacy_adoption(github, Path("."), plan, 930)
            self.assertEqual(github.comment_posts, 2)
            result = apply_legacy_adoption(github, Path("."), plan, 930)
        self.assertEqual(result["status"], "NOOP")
        self.assertEqual(github.comment_posts, 2)
        self.assertEqual(github.label_writes, 0)

    def test_reset_empty_history_has_stable_noop_shape(self):
        state = _read_reset_state(FakeGitHub(), 40)
        self.assertEqual(state, {
            "intent_comment_id": None, "intent_payload": None, "plan": None,
            "applied_comment_id": None, "applied_payload": None,
        })

    def test_reset_apply_writes_one_label_update_then_is_readback_noop(self):
        plan = make_reset_plan()
        approval = comment_row(930, owner_approval_comment(plan, operation="RESET_TO_REQUIREMENTS"))
        github = FakeGitHub([approval], labels=plan.value["issue_labels"])
        with patch("p_ases.legacy_adoption._fresh_reset_plan", return_value=plan), \
                patch("p_ases.legacy_adoption._verify_reset_subject", side_effect=lambda gh, _root, _plan, **_kw: gh.issue(40)):
            result = apply_legacy_reset(github, Path("."), plan, 930)
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(result["label_write"], "VERIFIED")
            self.assertEqual(github.label_writes, 1)
            repeated = apply_legacy_reset(github, Path("."), plan, 930)
        self.assertEqual(repeated["status"], "NOOP")
        self.assertEqual(github.label_writes, 1)
        self.assertEqual(github.labels, plan.value["target_labels"])

    def test_reset_recovers_applied_labels_without_a_second_put(self):
        plan = make_reset_plan()
        approval = comment_row(930, owner_approval_comment(plan, operation="RESET_TO_REQUIREMENTS"))
        github = FakeGitHub([approval], labels=plan.value["target_labels"])
        intent = {"approval_comment_id": 930, "plan": plan.value,
                  "plan_sha256": plan.sha256, "schema": RESET_INTENT_SCHEMA}
        intent_row = github.create_issue_comment(40, _body(RESET_INTENT_SCHEMA, intent))
        github.comment_posts = 0
        with patch("p_ases.legacy_adoption._verify_reset_subject", side_effect=lambda gh, _root, _plan, **_kw: gh.issue(40)):
            result = apply_legacy_reset(github, Path("."), plan, 930)
        self.assertEqual(result["label_write"], "RECOVERED_BY_READBACK")
        self.assertEqual(github.label_writes, 0)
        self.assertEqual(github.comment_posts, 1)
        self.assertGreater(result["applied_comment_id"], intent_row["id"])

    def test_reset_lost_label_response_is_verified_and_not_retried(self):
        plan = make_reset_plan()
        approval = comment_row(930, owner_approval_comment(plan, operation="RESET_TO_REQUIREMENTS"))
        github = FakeGitHub([approval], labels=plan.value["issue_labels"])
        github.lose_next_label_response = True
        with patch("p_ases.legacy_adoption._fresh_reset_plan", return_value=plan), \
                patch("p_ases.legacy_adoption._verify_reset_subject", side_effect=lambda gh, _root, _plan, **_kw: gh.issue(40)):
            result = apply_legacy_reset(github, Path("."), plan, 930)
        self.assertEqual(result["label_write"], "VERIFIED")
        self.assertEqual(github.label_writes, 1)

    def test_reset_intent_with_unchanged_labels_never_retries_the_put(self):
        plan = make_reset_plan()
        approval = comment_row(930, owner_approval_comment(plan, operation="RESET_TO_REQUIREMENTS"))
        github = FakeGitHub([approval], labels=plan.value["issue_labels"])
        intent = {"approval_comment_id": 930, "plan": plan.value,
                  "plan_sha256": plan.sha256, "schema": RESET_INTENT_SCHEMA}
        github.create_issue_comment(40, _body(RESET_INTENT_SCHEMA, intent))
        github.comment_posts = 0
        with self.assertRaisesRegex(LegacyAdoptionError, "refusing a second PUT"):
            apply_legacy_reset(github, Path("."), plan, 930)
        self.assertEqual(github.label_writes, 0)
        self.assertEqual(github.comment_posts, 0)

    def test_requirements_reset_is_a_noop(self):
        github = FakeGitHub()
        self.assertIsNone(build_legacy_reset_plan(github, Path("."), 40))

    def test_reset_plan_blocks_user_review_phase_with_resolved_owner_decision(self):
        github = FakeGitHub(labels=["enhancement", "kind:single", "phase:user-review"])
        with self.assertRaisesRegex(LegacyAdoptionError, "User Review decision"):
            build_legacy_reset_plan(github, Path("."), 40)

    def test_phase_gate_dispatch_requires_bound_worktree_for_legacy(self):
        selection = LegacyGateSelection(
            repository="octo/repo", issue_number=40, policy_version="legacy-issue-adopted-v1",
            selected_at="2026-10-21T15:00:00Z", adoption_comment_id=901,
            adoption_record_sha256="a" * 64, selection_sha256="b" * 64,
        )

        class IssueOnly:
            repo = "octo/repo"

            def issue(self, number):
                return {"number": number, "pull_request": None, "created_at": "2026-10-14T10:57:28Z"}

        with patch("p_ases.phase_evidence.read_gate_selection", return_value=(902, selection, "body")), \
                patch("p_ases.legacy_adoption.verify_legacy_gate_selection") as verify:
            _check_activation(IssueOnly(), 40, Path("."))
        verify.assert_called_once()
        with patch("p_ases.phase_evidence.read_gate_selection", return_value=(902, selection, "body")):
            with self.assertRaisesRegex(PhaseEvidenceError, "bound worktree"):
                _check_activation(IssueOnly(), 40)

    def test_historical_gate_verifier_rechecks_issue_creation_against_activation(self):
        plan = make_plan()
        adoption_payload = {
            "approval_comment_id": 930, "plan": plan.value, "plan_sha256": plan.sha256,
            "planned_gate_payload_sha256": plan.value["planned_gate_payload_sha256"],
            "schema": ADOPTION_SCHEMA,
        }
        selection = LegacyGateSelection(
            repository=plan.value["repository"], issue_number=plan.value["issue_number"],
            policy_version="legacy-issue-adopted-v1",
            selected_at=plan.value["generated_at"], adoption_comment_id=940,
            adoption_record_sha256=_digest(adoption_payload),
            selection_sha256=plan.value["planned_gate_payload_sha256"],
        ).validate()
        state = {"plan": plan, "approval_comment_id": 930, "gate_comment_id": 941,
                 "gate_selection": selection}
        activation = SimpleNamespace(sha256="a" * 64, activated_at="2026-10-15T17:37:00Z")
        adc = SimpleNamespace(pointer=SimpleNamespace(state="approved"),
                              contract=SimpleNamespace(sha256=plan.value["adc_sha256"]))
        github = adoption_github()
        github.branch = lambda ref: {"name": ref, "commit": {"sha": plan.value["remote_head_sha"]}}
        common = (
            patch("p_ases.legacy_adoption._read_adoption_state", return_value=state),
            patch("p_ases.legacy_adoption.verify_owner_approval"),
            patch("p_ases.legacy_adoption._repository_identity",
                  return_value=(plan.value["repository_id"], plan.value["owner_id"])),
            patch("p_ases.legacy_adoption._exact_issue", return_value=github.issue(46)),
            patch("p_ases.legacy_adoption.verify_adc_generation", return_value=adc),
            patch("p_ases.legacy_adoption.read_consumer_activation_history",
                  return_value=[(activation, 701)]),
            patch("p_ases.legacy_adoption.is_ancestor", return_value=True),
        )
        with common[0], common[1], common[2], common[3], common[4], common[5], common[6]:
            verify_legacy_gate_selection(github, Path("."), 46, 941, selection)
        activation.activated_at = "2026-10-14T10:00:00Z"
        with common[0], common[1], common[2], common[3], common[4], common[5], common[6]:
            with self.assertRaisesRegex(LegacyAdoptionError, "before the first Activation"):
                verify_legacy_gate_selection(github, Path("."), 46, 941, selection)


if __name__ == "__main__":
    unittest.main()
