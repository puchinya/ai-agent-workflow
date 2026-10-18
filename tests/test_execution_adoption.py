from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.execution import AdoptedExecutionEpoch, ExecutionError, WorkspaceAttachment
from p_ases.checkpoint import CheckpointError, PRBinding
from p_ases.github import GitHubError
from p_ases.execution_adoption import (
    APPLIED_SCHEMA, INTENT_SCHEMA, PLAN_SCHEMA, ExecutionAdoptionError,
    _append_marker_once, _attachment_id, _body, _comment_fingerprint, _owner_details,
    adoption_path, adoption_plan_path, attachment_path,
    _validate_journal_record, apply_adoption,
    _validate_journal_shape, _journal_payload,
    _validate_local_adoption_artifacts, adoption_plan_bytes, append_adopted_pr_binding,
    validate_adoption_plan,
)


REPOSITORY = "puchinya/ai-agent-workflow"
OWNER_ID = 3744776
REPOSITORY_ID = 1401910271


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _adoption_plan():
    checks = [
        {"app_id": 15368, "check_run_id": 700 + index, "conclusion": "success",
         "head_sha40": "b" * 40, "name": name}
        for index, name in enumerate(("Linux Python 3.10", "Linux Python 3.14", "Windows Python 3.14",
                                      "macOS Python 3.14", "pull-request-metadata"), start=1)
    ]
    checks.sort(key=lambda item: item["name"])
    value = {
        "schema": PLAN_SCHEMA, "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "owner_id": OWNER_ID, "issue_number": 63, "issue_kind": "single", "issue_phase": "requirements",
        "issue_labels": ["kind:single", "phase:requirements"],
        "adc_comment_id": 6248703643,
        "adc_sha256": "b83620dc5d977c3f96c7ad792fded202b70a78f0c97d637bfcc64d8ef8e89306",
        "phase_intent_comment_id": 6248707745, "phase_applied_comment_id": 6248721169,
        "phase_applied_payload_sha256": "d" * 64, "pr_number": 64,
        "pr_id": 864, "pr_title_sha256": "5" * 64, "pr_body_sha256": "6" * 64,
        "pr_url": "https://github.com/puchinya/ai-agent-workflow/pull/64",
        "pr_author_user_id": 3744776,
        "selected_base_ref": "main", "selected_base_sha40": "a" * 40,
        "branch_ref": "codex/issue-63-activation-ruleset-management",
        "observed_start_head_sha40": "b" * 40,
        "attachment_id": "e" * 64, "historical_binding_provenance": "UNVERIFIED",
        "ci_check_runs": checks,
        "ci_evidence_sha256": hashlib.sha256(_canonical(checks)).hexdigest(),
    }
    value["adoption_id"] = hashlib.sha256(
        b"PASES_EXECUTION_ADOPTION_V1\x00" + _canonical(value)).hexdigest()
    value["plan_sha256"] = hashlib.sha256(_canonical(value)).hexdigest()
    return value


def _epoch():
    return AdoptedExecutionEpoch(
        repository=REPOSITORY, issue_number=63, adc_comment_id=6248703643,
        adc_sha256="c" * 64, pr_number=64, pr_author_user_id=OWNER_ID,
        selected_base_ref="main", selected_base_sha40="a" * 40,
        branch_ref="codex/issue-63-activation-ruleset-management",
        observed_start_head_sha40="b" * 40, adoption_id="d" * 64, plan_sha256="e" * 64,
        owner_decision_comment_id=7001, owner_authorization_plan_sha256="f" * 64,
        approval_scope_sha256="1" * 64, intent_comment_id=7002, applied_comment_id=7003,
        intent_body_sha256="2" * 64, applied_body_sha256="3" * 64,
        attachment_id="4" * 64,
    ).validate()


class FakeGitHub:
    repo = REPOSITORY

    def __init__(self, rows=None, *, pull=None, issue_data=None, created_at_lag_seconds=0):
        self.rows = list(rows or [])
        self.writes = 0
        self.lose_response = False
        self.pull = pull
        self.created_at_lag_seconds = created_at_lag_seconds
        self.issue_data = issue_data or {
            "number": 63, "state": "open",
            "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
        }

    def issue_comments(self, number):
        if number != 63:
            raise AssertionError("wrong Issue")
        return list(self.rows)

    def issue_comment(self, number, comment_id):
        if number != 63:
            raise AssertionError("wrong Issue")
        return next(row for row in self.rows if row["id"] == comment_id)

    def create_issue_comment(self, number, body):
        self.writes += 1
        comment_id = 9000 + self.writes
        try:
            payload = json.loads(body.split("\n", 1)[1].rsplit("\n-->", 1)[0])
        except (IndexError, json.JSONDecodeError):
            payload = {}
        now = payload.get("created_at", "2026-10-18T12:00:00Z")
        if self.created_at_lag_seconds:
            persisted = (datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                         + timedelta(seconds=self.created_at_lag_seconds))
            now = persisted.strftime("%Y-%m-%dT%H:%M:%SZ")
        row = {
            "id": comment_id, "body": body, "created_at": now, "updated_at": now,
            "user": {"id": 5150, "login": "executor", "type": "User"},
            "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/63",
            "html_url": f"https://github.com/{REPOSITORY}/issues/63#issuecomment-{comment_id}",
        }
        self.rows.append(row)
        if self.lose_response:
            raise GitHubError("simulated response loss")
        return row

    def authenticated_user(self):
        return {"id": 5150, "login": "executor", "type": "User"}

    def issue(self, number):
        if number != 63:
            raise AssertionError("wrong Issue")
        return dict(self.issue_data)

    def repository_metadata(self):
        return {"id": REPOSITORY_ID, "full_name": REPOSITORY,
                "owner": {"id": OWNER_ID, "type": "User"}}

    def pull_request(self, number):
        if number != 64 or self.pull is None:
            raise AssertionError("wrong or unavailable PR")
        return dict(self.pull)


def _git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, text=True, check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def _live_plan_for_temporary_repo(root):
    remote = root.parent / "origin.git"
    _git(root.parent, "init", "--bare", "--initial-branch=main", str(remote))
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Test Owner")
    _git(root, "config", "user.email", "owner@example.invalid")
    (root / ".gitignore").write_text(".p_ases/\n.agent-state/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-m", "configure ignored state")
    base_sha = _git(root, "rev-parse", "HEAD")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "base.txt")
    _git(root, "commit", "-m", "base")
    base_sha = _git(root, "rev-parse", "HEAD")
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-u", "origin", "main")
    branch = "codex/issue-63-adoption-test"
    _git(root, "checkout", "-b", branch)
    (root / "change.txt").write_text("implementation\n", encoding="utf-8")
    _git(root, "add", "change.txt")
    _git(root, "commit", "-m", "bootstrap implementation")
    head_sha = _git(root, "rev-parse", "HEAD")
    _git(root, "push", "-u", "origin", branch)
    plan = _adoption_plan()
    plan["selected_base_sha40"] = base_sha
    plan["branch_ref"] = branch
    plan["observed_start_head_sha40"] = head_sha
    plan["attachment_id"] = _attachment_id(root, branch)
    for row in plan["ci_check_runs"]:
        row["head_sha40"] = head_sha
    plan["ci_evidence_sha256"] = hashlib.sha256(_canonical(plan["ci_check_runs"])).hexdigest()
    plan.pop("adoption_id")
    plan.pop("plan_sha256")
    plan["adoption_id"] = hashlib.sha256(
        b"PASES_EXECUTION_ADOPTION_V1\x00" + _canonical(plan)).hexdigest()
    plan["plan_sha256"] = hashlib.sha256(_canonical(plan)).hexdigest()
    plan = validate_adoption_plan(plan)
    repo_row = {"full_name": REPOSITORY, "id": REPOSITORY_ID}
    pull = {
        "number": 64, "id": 864, "state": "open", "draft": False, "merged": False,
        "title": "Adoption integration test", "body": "Refs #63",
        "html_url": f"https://github.com/{REPOSITORY}/pull/64",
        "base": {"repo": repo_row, "ref": "main", "sha": base_sha},
        "head": {"repo": repo_row, "ref": branch, "sha": head_sha},
        "user": {"id": OWNER_ID, "type": "User"},
    }
    return remote, plan, pull


class ExecutionAdoptionTests(unittest.TestCase):
    def test_adopted_epoch_round_trip_keeps_selected_base_separate_from_observed_pr_head(self):
        epoch = _epoch()
        self.assertNotEqual(epoch.selected_base_sha40, epoch.observed_start_head_sha40)
        self.assertEqual(AdoptedExecutionEpoch.from_bytes(epoch.to_bytes()), epoch)
        altered = json.loads(epoch.to_bytes())
        altered["historical_binding_provenance"] = "VERIFIED"
        raw = (json.dumps(altered, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        with self.assertRaisesRegex(ExecutionError, "unverified historical provenance"):
            AdoptedExecutionEpoch.from_bytes(raw)

    def test_adopted_epoch_rejects_other_issue_pr_and_missing_pr_author(self):
        with self.assertRaisesRegex(ExecutionError, "restricted"):
            _epoch().__class__(**{**_epoch().__dict__, "issue_number": 62}).validate()
        with self.assertRaisesRegex(ExecutionError, "restricted"):
            _epoch().__class__(**{**_epoch().__dict__, "pr_number": 65}).validate()
        with self.assertRaisesRegex(ExecutionError, "restricted"):
            _epoch().__class__(**{**_epoch().__dict__, "pr_author_user_id": 0}).validate()

    def test_workspace_attachment_is_local_and_strict(self):
        with tempfile.TemporaryDirectory() as temporary:
            attachment = WorkspaceAttachment(
                repository=REPOSITORY, issue_number=63, adoption_id="a" * 64,
                attachment_id="b" * 64, branch_ref="codex/issue-63",
                work_directory=str(Path(temporary).resolve()),
            )
            self.assertEqual(WorkspaceAttachment.from_bytes(attachment.to_bytes()), attachment)
            with self.assertRaisesRegex(ExecutionError, "absolute"):
                WorkspaceAttachment(**{**attachment.__dict__, "work_directory": "relative"}).validate()

    def test_adopted_prbinding_v3_is_restricted_to_the_one_time_issue_and_pr(self):
        binding = PRBinding(
            repository=REPOSITORY, issue_number=63, adc_comment_id=6248703643,
            adc_sha256="a" * 64, base_sha40="b" * 40,
            branch_ref="codex/issue-63", pr_number=64, pr_head_sha40="c" * 40,
            adoption_id="d" * 64,
        ).validate()
        self.assertEqual(binding.payload()["schema"], "PASES_PR_BINDING_V3")
        with self.assertRaisesRegex(CheckpointError, "restricted"):
            PRBinding(**{**binding.__dict__, "issue_number": 62}).validate()
        with self.assertRaisesRegex(CheckpointError, "restricted"):
            PRBinding(**{**binding.__dict__, "pr_number": 65}).validate()

    def test_plan_digest_binds_exact_scope_author_ci_and_deterministic_operation_id(self):
        plan = _adoption_plan()
        self.assertEqual(validate_adoption_plan(plan), plan)
        self.assertEqual(adoption_plan_bytes(plan), _canonical(plan) + b"\n")
        changed = dict(plan)
        changed["pr_author_user_id"] += 1
        with self.assertRaisesRegex(ExecutionAdoptionError, "digest"):
            validate_adoption_plan(changed)
        changed = dict(plan)
        changed["adoption_id"] = "0" * 64
        changed.pop("plan_sha256")
        changed["plan_sha256"] = hashlib.sha256(_canonical(changed)).hexdigest()
        with self.assertRaisesRegex(ExecutionAdoptionError, "operation ID"):
            validate_adoption_plan(changed)

    def test_plan_rejects_unknown_or_missing_fields_and_duplicate_ci(self):
        plan = _adoption_plan()
        missing = dict(plan)
        missing.pop("pr_author_user_id")
        with self.assertRaisesRegex(ExecutionAdoptionError, "unknown or missing"):
            validate_adoption_plan(missing)
        duplicate = dict(plan)
        duplicate["ci_check_runs"] = [*plan["ci_check_runs"]]
        duplicate["ci_check_runs"][1] = dict(duplicate["ci_check_runs"][0])
        duplicate["ci_evidence_sha256"] = hashlib.sha256(_canonical(duplicate["ci_check_runs"])).hexdigest()
        duplicate.pop("plan_sha256")
        duplicate["plan_sha256"] = hashlib.sha256(_canonical(duplicate)).hexdigest()
        with self.assertRaisesRegex(ExecutionAdoptionError, "five unique"):
            validate_adoption_plan(duplicate)

    def test_local_preflight_blocks_unverified_artifacts_but_allows_clean_state(self):
        plan = _adoption_plan()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _validate_local_adoption_artifacts(root, plan, allow_recovery=False)
            state = root / ".p_ases/state/63"
            state.mkdir(parents=True)
            (state / "pr-binding.json").write_text("unverified\n", encoding="utf-8")
            with self.assertRaisesRegex(ExecutionAdoptionError, "unverified or unrelated"):
                _validate_local_adoption_artifacts(root, plan, allow_recovery=True)

    def test_local_preflight_rejects_symlinked_parent_before_any_remote_journal_write(self):
        plan = _adoption_plan()
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as target:
            root = Path(temporary)
            (root / ".p_ases").symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ExecutionAdoptionError, "state path traverses"):
                _validate_local_adoption_artifacts(root, plan, allow_recovery=False)

    def test_journal_shape_requires_deterministic_operation_id_and_exact_scope(self):
        payload = {
            "schema": INTENT_SCHEMA, "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
            "owner_id": OWNER_ID, "executor_user_id": 5150, "issue_number": 63, "pr_number": 64,
            "adc_comment_id": 6248703643, "adc_sha256": "a" * 64, "plan_sha256": "b" * 64,
            "owner_authorization_plan_sha256": "c" * 64, "approval_scope_sha256": "d" * 64,
            "owner_decision_comment_id": 7001, "adoption_id": "e" * 64, "operation_id": "e" * 64,
            "selected_base_ref": "main", "selected_base_sha40": "f" * 40, "branch_ref": "feature/63",
            "observed_start_head_sha40": "1" * 40, "historical_binding_provenance": "UNVERIFIED",
            "attachment_id": "2" * 64, "created_at": "2026-10-18T12:00:00Z",
        }
        _validate_journal_shape(payload, INTENT_SCHEMA)
        bad = dict(payload, operation_id="9" * 64)
        with self.assertRaisesRegex(ExecutionAdoptionError, "scope fields"):
            _validate_journal_shape(bad, INTENT_SCHEMA)
        bad = dict(payload, created_at="2026-10-18T12:00:00+00:00")
        with self.assertRaisesRegex(ExecutionAdoptionError, "canonical UTC"):
            _validate_journal_shape(bad, INTENT_SCHEMA)

    def test_journal_link_order_requires_owner_decision_before_intent_and_intent_before_applied(self):
        plan = _adoption_plan()
        owner_plan = {"plan_sha256": "c" * 64, "approval_scope_sha256": "d" * 64}
        intent = _journal_payload(plan, owner_plan, 7001, 5150, phase="intent")
        fingerprint = (7002, _body(INTENT_SCHEMA, intent), intent["created_at"], intent["created_at"],
                       5150, "executor", "User", "url", "issue_url", "html_url")
        _validate_journal_record((7002, INTENT_SCHEMA, intent, fingerprint), schema=INTENT_SCHEMA,
                                 plan=plan, owner_plan=owner_plan, decision_comment_id=7001,
                                 executor_user_id=5150)
        with self.assertRaisesRegex(ExecutionAdoptionError, "must follow"):
            _validate_journal_record((7001, INTENT_SCHEMA, intent, fingerprint), schema=INTENT_SCHEMA,
                                     plan=plan, owner_plan=owner_plan, decision_comment_id=7001,
                                     executor_user_id=5150)
        applied = _journal_payload(plan, owner_plan, 7001, 5150, phase="applied",
                                   intent_comment_id=7002,
                                   intent_body_sha256=hashlib.sha256(_body(INTENT_SCHEMA, intent).encode()).hexdigest())
        applied_fingerprint = (7003, _body(APPLIED_SCHEMA, applied), applied["created_at"],
                               applied["created_at"], 5150, "executor", "User", "url", "issue_url", "html_url")
        with self.assertRaisesRegex(ExecutionAdoptionError, "must follow"):
            _validate_journal_record((7002, APPLIED_SCHEMA, applied, applied_fingerprint),
                                     schema=APPLIED_SCHEMA, plan=plan, owner_plan=owner_plan,
                                     decision_comment_id=7001, executor_user_id=5150,
                                     intent_record=(7002, INTENT_SCHEMA, intent, fingerprint))

    def test_journal_accepts_immutable_github_timestamp_after_pre_post_payload_time(self):
        plan = _adoption_plan()
        owner_plan = {"plan_sha256": "c" * 64, "approval_scope_sha256": "d" * 64}
        intent = _journal_payload(plan, owner_plan, 7001, 5150, phase="intent")
        intent_api_time = (datetime.strptime(intent["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                           .replace(tzinfo=timezone.utc) + timedelta(seconds=1))
        intent_carrier_time = intent_api_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        intent_fingerprint = (7002, _body(INTENT_SCHEMA, intent), intent_carrier_time,
                              intent_carrier_time, 5150, "executor", "User", "url", "issue_url", "html_url")
        intent_record = (7002, INTENT_SCHEMA, intent, intent_fingerprint)
        _validate_journal_record(intent_record, schema=INTENT_SCHEMA, plan=plan, owner_plan=owner_plan,
                                 decision_comment_id=7001, executor_user_id=5150)

        applied = _journal_payload(
            plan, owner_plan, 7001, 5150, phase="applied", intent_comment_id=7002,
            intent_body_sha256=hashlib.sha256(_body(INTENT_SCHEMA, intent).encode()).hexdigest(),
        )
        applied_api_time = (datetime.strptime(applied["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                            .replace(tzinfo=timezone.utc) + timedelta(seconds=1))
        applied_carrier_time = applied_api_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        applied_fingerprint = (7003, _body(APPLIED_SCHEMA, applied), applied_carrier_time,
                               applied_carrier_time, 5150, "executor", "User", "url", "issue_url", "html_url")
        _validate_journal_record((7003, APPLIED_SCHEMA, applied, applied_fingerprint),
                                 schema=APPLIED_SCHEMA, plan=plan, owner_plan=owner_plan,
                                 decision_comment_id=7001, executor_user_id=5150,
                                 intent_record=intent_record)

    def test_comment_fingerprint_requires_issue_urls_and_immutable_utc_time(self):
        github = FakeGitHub()
        github.create_issue_comment(63, "body")
        row = github.rows[0]
        self.assertEqual(_comment_fingerprint(row)[0], row["id"])
        foreign = dict(row, issue_url=f"https://api.github.com/repos/{REPOSITORY}/issues/62")
        with self.assertRaisesRegex(ExecutionAdoptionError, "another Issue"):
            _comment_fingerprint(foreign)
        edited = dict(row, updated_at="2026-10-18T12:00:01Z")
        with self.assertRaisesRegex(ExecutionAdoptionError, "edited"):
            _comment_fingerprint(edited)

    def test_lost_response_retry_reuses_same_operation_without_second_post(self):
        payload = {
            "schema": INTENT_SCHEMA, "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
            "owner_id": OWNER_ID, "executor_user_id": 5150, "issue_number": 63, "pr_number": 64,
            "adc_comment_id": 6248703643, "adc_sha256": "a" * 64, "plan_sha256": "b" * 64,
            "owner_authorization_plan_sha256": "c" * 64, "approval_scope_sha256": "d" * 64,
            "owner_decision_comment_id": 7001, "adoption_id": "e" * 64, "operation_id": "e" * 64,
            "selected_base_ref": "main", "selected_base_sha40": "f" * 40, "branch_ref": "feature/63",
            "observed_start_head_sha40": "1" * 40, "historical_binding_provenance": "UNVERIFIED",
            "attachment_id": "2" * 64, "created_at": "2026-10-18T12:00:00Z",
        }
        github = FakeGitHub()
        github.lose_response = True
        first_id, _first_sha, _ = _append_marker_once(github, INTENT_SCHEMA, payload)
        second_id, body_sha, recovered = _append_marker_once(github, INTENT_SCHEMA, payload)
        self.assertEqual(first_id, second_id)
        self.assertEqual(github.writes, 1)
        self.assertEqual(recovered["created_at"], payload["created_at"])
        self.assertEqual(body_sha, hashlib.sha256(_body(INTENT_SCHEMA, payload).encode()).hexdigest())

    def test_exact_approved_apply_creates_one_epoch_and_exact_retry_is_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / "repo"
            root.mkdir()
            _remote, plan, pull = _live_plan_for_temporary_repo(root)
            # GitHub assigns its carrier timestamp after the runtime has
            # generated the immutable body payload, often in the next second.
            github = FakeGitHub(pull=pull, created_at_lag_seconds=1)
            owner_plan = {
                "operation": "EXECUTION_ADOPTION", "subject_sha256": plan["plan_sha256"],
                "target_issue_number": 63, "pr_number": 64,
                "pr_head_sha40": plan["observed_start_head_sha40"],
                "details": _owner_details(plan), "plan_sha256": "f" * 64,
                "approval_scope_sha256": "a" * 64,
            }
            decision = SimpleNamespace(
                comment_id=7001, body_sha256="d" * 64,
                decision=SimpleNamespace(schema="PASES_OWNER_DECISION_V3",
                                         evidence_channel="chat_confirmed_gh_v1"),
            )
            patches = (
                patch("p_ases.execution_adoption._validate_owner_authorization_plan", side_effect=lambda value: value),
                patch("p_ases.execution_adoption._current_plan_matches",
                      side_effect=lambda _github, _root, approved: approved),
                patch("p_ases.execution_adoption.create_authorization_plan", return_value=owner_plan),
                patch("p_ases.execution_adoption._live_owner_decision", return_value=decision),
                patch("p_ases.execution_adoption.read_verified_owner_decision", return_value=decision),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                first = apply_adoption(github, root, plan, owner_plan)
                self.assertEqual(first["status"], "ADOPTED")
                self.assertEqual(github.writes, 2)
                self.assertTrue(adoption_plan_path(root).is_file())
                self.assertTrue(adoption_path(root).is_file())
                self.assertTrue(attachment_path(root).is_file())
                (root / "later.txt").write_text("forward-only continuation\n", encoding="utf-8")
                _git(root, "add", "later.txt")
                _git(root, "commit", "-m", "later forward-only fix")
                later_head = _git(root, "rev-parse", "HEAD")
                _git(root, "push", "origin", "HEAD:refs/heads/" + plan["branch_ref"])
                github.pull["head"]["sha"] = later_head
                current_adc = SimpleNamespace(pointer=SimpleNamespace(
                    comment_id=plan["adc_comment_id"], sha256=plan["adc_sha256"]))
                with patch("p_ases.execution_adoption.verify_adc", return_value=current_adc):
                    advanced = append_adopted_pr_binding(
                        github, root, expected_adc_comment_id=plan["adc_comment_id"],
                        expected_adc_sha256=plan["adc_sha256"])
                self.assertEqual(advanced["status"], "PR_BINDING_ADVANCED")
                self.assertEqual(advanced["epoch"].observed_start_head_sha40,
                                 plan["observed_start_head_sha40"])
                second = apply_adoption(github, root, plan, owner_plan)
                self.assertEqual(second["status"], "ADOPTED")
                self.assertEqual(second["writes_performed"], 0)
                self.assertEqual(second["current_head_sha40"], later_head)
                self.assertEqual(github.writes, 2)

    def test_exact_final_plan_without_owner_decision_has_zero_adoption_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / "repo"
            root.mkdir()
            _remote, plan, _pull = _live_plan_for_temporary_repo(root)
            github = FakeGitHub()
            owner_plan = {
                "operation": "EXECUTION_ADOPTION", "subject_sha256": plan["plan_sha256"],
                "target_issue_number": 63, "pr_number": 64,
                "pr_head_sha40": plan["observed_start_head_sha40"],
                "details": _owner_details(plan), "plan_sha256": "f" * 64,
                "approval_scope_sha256": "a" * 64,
            }
            with patch("p_ases.execution_adoption._validate_owner_authorization_plan",
                       side_effect=lambda value: value), \
                    patch("p_ases.execution_adoption._current_plan_matches",
                          side_effect=lambda _github, _root, approved: approved), \
                    patch("p_ases.execution_adoption.create_authorization_plan", return_value=owner_plan), \
                    patch("p_ases.execution_adoption._live_owner_decision",
                          side_effect=ExecutionAdoptionError("exact Owner approval missing")):
                with self.assertRaisesRegex(ExecutionAdoptionError, "Owner approval missing"):
                    apply_adoption(github, root, plan, owner_plan)
            self.assertEqual(github.writes, 0)
            self.assertFalse(adoption_path(root).exists())
            self.assertFalse(attachment_path(root).exists())


if __name__ == "__main__":
    unittest.main()
