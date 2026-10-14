from __future__ import annotations

from dataclasses import replace
import sys
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
import contextlib
import shlex
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.integration import (
    IntegrationError, IntegrationGateEvidence, ParentGateEvidenceComment, evaluate_parent_integration,
)
from p_ases.github import GitHub, GitHubError
from p_ases.cli import (
    PARENT_ACCEPTANCE_STEPS, PARENT_ACCEPTANCE_WORKFLOW, PARENT_CI_WORKFLOW,
    PARENT_REQUIRED_CI_JOBS, PARENT_TRUSTED_ACTIONS_APP_ID, PARENT_VERIFICATION_STEPS,
    PARENT_ISSUE_CONTRACT_COMMIT, PARENT_ISSUE_CONTRACT_SOURCE,
    CLIError, _advance_parent_to_user_review, _delivery_parent, _delivery_parent_label_migration,
    _issue_integration_check, _parser,
    _require_parent_user_review_phase, _load_parent_gate_evidence_from_github, _parent_adc_authority,
    _parent_contract_declaration, _parent_gate_bundle_from_actions, _parent_review_subject_from_integration,
    _publish_parent_gate_evidence,
)

EXPECTED = (27, 28, 29, 30, 31, 32)
DAG = {
    27: (),
    28: (27,),
    29: (27, 28),
    30: (27, 29),
    31: (29, 30),
    32: (27, 28, 29, 30, 31),
}
PR_NUMBER = {27: 33, 28: 36, 29: 34, 30: 35, 31: 37, 32: 38}
MAIN = "a" * 40


def trusted_actions_fixture(main_sha: str, kind: str = "verification", run_id: int = 500):
    workflow_path = PARENT_CI_WORKFLOW if kind == "verification" else PARENT_ACCEPTANCE_WORKFLOW
    event = "push" if kind == "verification" else "workflow_dispatch"
    names = (*PARENT_REQUIRED_CI_JOBS, "pull-request-metadata") if kind == "verification" else ("parent-acceptance",)
    jobs = []
    check_runs = []
    for index, name in enumerate(names, 1):
        job_id = 8000 + index
        check_id = 9000 + index
        steps_by_name = PARENT_VERIFICATION_STEPS if kind == "verification" else PARENT_ACCEPTANCE_STEPS
        if name == "pull-request-metadata":
            status, conclusion, steps = "completed", "skipped", []
        else:
            status, conclusion = "completed", "success"
            required_step_names = (tuple(steps_by_name.values()) if kind == "acceptance"
                                   else tuple(steps_by_name.values()))
            steps = [{"number": step_num, "name": step_name, "status": "completed", "conclusion": "success"}
                     for step_num, step_name in enumerate(required_step_names, 1)]
            if kind == "verification":
                steps.extend([
                    {"number": 20, "name": "Set up job", "status": "completed", "conclusion": "success"},
                    {"number": 21, "name": "Complete job", "status": "completed", "conclusion": "success"},
                ])
        jobs.append({
            "id": job_id, "run_id": run_id, "head_sha": main_sha, "name": name,
            "status": status, "conclusion": conclusion,
            "check_run_url": f"https://api.github.com/repos/octo/repo/check-runs/{check_id}",
            "steps": steps,
        })
        check_runs.append({
            "id": check_id, "name": name, "head_sha": main_sha, "status": status,
            "conclusion": conclusion, "app": {"id": PARENT_TRUSTED_ACTIONS_APP_ID},
        })
    run = {
        "id": run_id, "run_number": run_id, "run_attempt": 1,
        "path": workflow_path, "event": event, "head_branch": "main", "head_sha": main_sha,
        "status": "completed", "conclusion": "success",
        "head_repository": {"full_name": "octo/repo"},
    }

    class ActionsGitHub:
        def __init__(self):
            self.run = run
            self.jobs = jobs
            self.checks = check_runs

        def workflow_runs_for_ref(self, _sha, *, workflow_path, event):
            if workflow_path != self.run["path"] or event != self.run["event"]:
                return []
            return [dict(self.run)]

        def workflow_run_jobs(self, requested_run_id):
            if requested_run_id != self.run["id"]:
                return []
            return [dict(job, steps=[dict(step) for step in job["steps"]]) for job in self.jobs]

        def check_runs_for_ref(self, _sha):
            return [dict(row, app=dict(row["app"])) for row in self.checks]

    return ActionsGitHub()


def integration_fixture():
    native = [{"id": 100 + number, "number": number} for number in EXPECTED]
    issues = [{"id": 100 + number, "number": number, "state": "closed"} for number in EXPECTED]
    blockers = {number: tuple(100 + dependency for dependency in DAG[number]) for number in EXPECTED}
    prs = []
    for number in EXPECTED:
        repository = {"full_name": "octo/repo"}
        prs.append({
            "number": PR_NUMBER[number], "state": "closed",
            "merged_at": f"2026-10-12T00:{number - 27:02d}:00Z",
            "merge_commit_sha": f"{number:040x}",
            "body": f"Implementation details\n\nCloses #{number}\n",
            "base": {"repo": repository, "ref": "main", "sha": MAIN},
            "head": {"repo": repository, "ref": f"pases/issue-{number}", "sha": f"{number + 100:040x}"},
        })
    return dict(
        repository="octo/repo", parent_issue_number=26,
        parent_adc_sha256="b" * 64, main_sha40=MAIN,
        expected_child_issue_numbers=EXPECTED,
        native_sub_issues=native, child_issue_rows=issues,
        actual_blockers_by_issue=blockers, declared_dependencies=DAG,
        merged_pr_rows=prs,
        merge_sha_ancestry={f"{number:040x}": True for number in EXPECTED},
        integration_verification=IntegrationGateEvidence(
            "verification", "octo/repo", 26, "b" * 64, MAIN, "PASS", "c" * 64, "issue-comment:801"),
        integration_acceptance=IntegrationGateEvidence(
            "acceptance", "octo/repo", 26, "b" * 64, MAIN, "PASS", "d" * 64, "issue-comment:802"),
    )


def parent_integration_github_fixture(
    verification_bundle: ParentGateEvidenceComment,
    acceptance_bundle: ParentGateEvidenceComment,
    verification_actions,
    acceptance_actions,
):
    """GitHub I/O fixture used by the public integration-check route, without stubbing its reader."""
    repository = "octo/repo"
    main_sha = MAIN
    base = integration_fixture()
    child_adc = (
        "# Agent Development Contract — parent integration fixture\n"
        f"Repository: {repository}\nIssue: #31\nChild key: integration-validation\n"
        "State: approved\n\n"
        "## Issue\nRead the approved parent contract from the immutable child ADC.\n\n"
        "## Scope and change kind\nScope: parent Integration validation.\nChange kind: regression fixture.\n\n"
        "## Requirements\n- REQ-31: Preserve exact GitHub evidence identity.\n\n"
        "## Architecture decisions\nUse trusted GitHub API records.\n\n"
        "## Artifact impact\nNo generated artifacts are authored by this fixture.\n\n"
        "## Exact changes\nExercise the integration-check command route.\n\n"
        "## Invariants and non-goals\nDo not weaken Integration gates.\n\n"
        "## Verification obligations\nRun the exact parent Integration path.\n"
        f"Parent contract: `{PARENT_ISSUE_CONTRACT_SOURCE}` at `{PARENT_ISSUE_CONTRACT_COMMIT}`\n"
        f"Parent ADC SHA-256: `{'b' * 64}`\n\n"
        "## Reviewer Checklist\n- [ ] Verify exact child ADC bytes.\n\n"
        "## Completion gates\nReturn the exact Integration result.\n"
    ).encode("utf-8")
    child_adc_comment_id = 3100
    child_adc_digest = hashlib.sha256(child_adc).hexdigest()
    child_pointer = (
        "## Agent Development Contract\n"
        f"Comment ID: {child_adc_comment_id}\n"
        f"SHA-256: {child_adc_digest}\n"
        f"Bytes: {len(child_adc)}\n"
        "State: approved\n"
    )
    child_issues = {
        row["number"]: {
            **row, "repository_url": f"https://api.github.com/repos/{repository}",
            "pull_request": None,
        }
        for row in base["child_issue_rows"]
    }
    child_issues[31]["body"] = child_pointer
    child_adc_comment = {
        "id": child_adc_comment_id, "body": child_adc.decode("utf-8"),
        "issue_url": f"https://api.github.com/repos/{repository}/issues/31",
    }

    def make_comment(comment_id, bundle):
        return {
            "id": comment_id, "body": bundle.to_body(),
            "created_at": "2026-10-12T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
            "issue_url": f"https://api.github.com/repos/{repository}/issues/26",
            "html_url": f"https://github.com/{repository}/issues/26#issuecomment-{comment_id}",
            "url": f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}",
            "user": {"id": 42, "login": "octocat", "type": "User"},
        }

    evidence_comments = {
        801: make_comment(801, verification_bundle),
        802: make_comment(802, acceptance_bundle),
    }

    class IntegrationGitHub:
        repo = repository

        def __init__(self):
            self.main_sha40 = main_sha
            self.direct_reads = 0
            self.list_reads = 0
            self.direct_comment_ids = []
            self.blocked_by_calls = []
            self.sub_issue_reads = 0
            self.active_actions = None
            self.actions_by_run = {
                verification_actions.run["id"]: verification_actions,
                acceptance_actions.run["id"]: acceptance_actions,
            }

        def issue(self, number):
            if number == 26:
                return {
                    "number": 26, "state": "open", "pull_request": None,
                    "repository_url": f"https://api.github.com/repos/{repository}",
                    "body": "Parent Integration test contract",
                }
            row = dict(child_issues[number])
            if number == 31:
                row["body"] = child_pointer
            return row

        def issue_comments(self, number):
            if number == 31:
                return []
            if number != 26:
                return []
            rows = []
            login = ("OCTOCAT", "octocat", "OcToCaT", "oCToCaT")[self.list_reads % 4]
            for row in evidence_comments.values():
                item = dict(row)
                item["user"] = {
                    **item["user"], "login": login,
                    "avatar_url": f"https://avatars.example/list?read={self.list_reads}",
                    "html_url": f"https://github.com/{login}/profile",
                }
                rows.append(item)
            self.list_reads += 1
            return rows

        def issue_comment(self, number, comment_id):
            if number == 31 and comment_id == child_adc_comment_id:
                return dict(child_adc_comment)
            if number != 26 or comment_id not in evidence_comments:
                raise GitHubError("fixture comment does not exist")
            self.direct_comment_ids.append(comment_id)
            row = dict(evidence_comments[comment_id])
            login = ("OctoCat", "octocat", "OCTOCAT", "oCToCaT")[self.direct_reads % 4]
            row["user"] = {
                **row["user"], "login": login,
                "avatar_url": f"https://avatars.example/direct?read={self.direct_reads}",
                "html_url": f"https://github.com/{login}/profile",
            }
            self.direct_reads += 1
            return row

        @staticmethod
        def authenticated_user():
            return {"id": 42, "login": "Octocat", "type": "User"}

        @staticmethod
        def repository_metadata():
            return {"default_branch": "main"}

        def branch(self, branch):
            if branch != "main":
                raise GitHubError("fixture only has main")
            return {"commit": {"sha": self.main_sha40}}

        @staticmethod
        def content_at_ref(path, ref):
            if path != PARENT_ISSUE_CONTRACT_SOURCE or ref != PARENT_ISSUE_CONTRACT_COMMIT:
                raise GitHubError("fixture parent contract pin does not match")
            return b"pinned parent contract bytes\n"

        def sub_issues(self, parent_number):
            if parent_number != 26:
                raise GitHubError("fixture parent number does not match")
            self.sub_issue_reads += 1
            return [dict(row) for row in base["native_sub_issues"]]

        def blocked_by(self, issue_number):
            self.blocked_by_calls.append(issue_number)
            child_ids = {row["number"]: row["id"] for row in base["native_sub_issues"]}
            return [{"id": child_ids[blocker], "number": blocker}
                    for blocker in DAG[issue_number]]

        @staticmethod
        def pull_requests_all():
            return [dict(row) for row in base["merged_pr_rows"]]

        @staticmethod
        def compare_commits(base_sha40, head_sha40):
            if head_sha40 != main_sha or base_sha40 not in base["merge_sha_ancestry"]:
                return {"status": "behind"}
            return {"status": "ahead"}

        def workflow_runs_for_ref(self, sha, *, workflow_path, event):
            for actions in (verification_actions, acceptance_actions):
                rows = actions.workflow_runs_for_ref(
                    sha, workflow_path=workflow_path, event=event)
                if rows:
                    return rows
            return []

        def workflow_run_jobs(self, run_id):
            self.active_actions = self.actions_by_run.get(run_id)
            if self.active_actions is None:
                return []
            return self.active_actions.workflow_run_jobs(run_id)

        def check_runs_for_ref(self, sha):
            if self.active_actions is None:
                return []
            return self.active_actions.check_runs_for_ref(sha)

    return IntegrationGitHub()


class ParentIntegrationTests(unittest.TestCase):
    def test_parent_gate_step_contract_matches_committed_workflows(self):
        ci = (ROOT / PARENT_CI_WORKFLOW).read_text(encoding="utf-8")
        acceptance = (ROOT / PARENT_ACCEPTANCE_WORKFLOW).read_text(encoding="utf-8")
        for step_name in PARENT_VERIFICATION_STEPS.values():
            self.assertIn(f"- name: {step_name}", ci)
        for step_name in PARENT_ACCEPTANCE_STEPS.values():
            self.assertIn(f"- name: {step_name}", acceptance)

    def test_parent_review_subject_is_exact_integration_pass_and_phase_transition_is_guarded(self):
        passed = evaluate_parent_integration(**integration_fixture())
        subject = _parent_review_subject_from_integration(passed)
        self.assertEqual(subject.parent_issue_number, 26)
        self.assertEqual(subject.child_merge_set,
                         tuple((row.issue_number, row.merge_sha40) for row in passed.subject.children))
        self.assertEqual(subject.integration_evidence_digest, passed.sha256)

        blocked_inputs = integration_fixture()
        blocked_inputs["child_issue_rows"][-1]["state"] = "open"
        blocked = evaluate_parent_integration(**blocked_inputs)
        with self.assertRaisesRegex(CLIError, "only after complete parent Integration PASS"):
            _parent_review_subject_from_integration(blocked)

        class LabelGitHub:
            def __init__(self, labels):
                self.labels = labels
                self.replacements = []

            def issue(self, _number):
                return {"number": 26, "state": "open",
                        "labels": [{"name": label} for label in self.labels]}

            def replace_issue_labels(self, _number, labels):
                self.replacements.append(list(labels))
                self.labels = list(labels)

        github = LabelGitHub(["kind:parent", "phase:integration"])
        _advance_parent_to_user_review(github, 26)
        self.assertIn("phase:user-review", github.labels)
        self.assertEqual(len(github.replacements), 1)

        with self.assertRaisesRegex(CLIError, "no longer in unblocked User Review"):
            _require_parent_user_review_phase({"number": 26, "state": "open",
                                               "labels": [{"name": "kind:parent"},
                                                          {"name": "phase:integration"}]}, 26)
        _advance_parent_to_user_review(github, 26)
        self.assertEqual(len(github.replacements), 1)

        waiting = LabelGitHub(["kind:parent", "phase:integration", "attention:waiting-dependency"])
        with self.assertRaisesRegex(CLIError, "clear parent waiting/blocked attention"):
            _advance_parent_to_user_review(waiting, 26)
        self.assertEqual(waiting.replacements, [])

    def test_legacy_parent_label_migration_preflight_apply_retry_conflict_and_partial_failure(self):
        class LabelMigrationGitHub:
            def __init__(self, labels, *, fail_after_write=False):
                self.labels = list(labels)
                self.fail_after_write = fail_after_write
                self.fail_definition_name = None
                self.writes = 0
                self.definitions = {
                    "enhancement": {"name": "enhancement", "color": "a2eeef", "description": "New feature"}}

            def issue(self, _number):
                return {"number": 26, "state": "open", "pull_request": None,
                        "repository_url": "https://api.github.com/repos/octo/repo",
                        "labels": [{"name": label} for label in self.labels]}

            def repository_labels(self):
                return list(self.definitions.values())

            def create_repository_label(self, name, color, description):
                if self.fail_definition_name == name:
                    self.fail_definition_name = None
                    raise GitHubError("simulated response loss before label definition write")
                row = {"name": name, "color": color, "description": description}
                if name in self.definitions and self.definitions[name] != row:
                    raise GitHubError("conflicting label definition")
                self.definitions[name] = row
                return row

            def replace_issue_labels(self, _number, labels):
                self.writes += 1
                self.labels = list(labels)
                if self.fail_after_write:
                    self.fail_after_write = False
                    raise GitHubError("simulated response loss after GitHub write")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=False), "octo/repo", LabelMigrationGitHub(["enhancement"]))
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["labels_after"],
                         ["enhancement", "kind:parent", "phase:integration"])

        github = LabelMigrationGitHub(["enhancement"])
        for expected_status in ("MIGRATED", "ALREADY_MIGRATED"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = _delivery_parent_label_migration(
                    SimpleNamespace(issue=26, apply=True), "octo/repo", github)
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], expected_status)
        self.assertEqual(github.writes, 1)

        conflict = LabelMigrationGitHub(["enhancement", "phase:requirements"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", conflict)
        self.assertEqual(status, 2)
        self.assertIn("conflicts with an existing phase", json.loads(output.getvalue())["reasons"][0])
        self.assertEqual(conflict.writes, 0)

        partial = LabelMigrationGitHub(["enhancement"], fail_after_write=True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", partial)
        self.assertEqual(status, 2)
        self.assertEqual(partial.labels, ["enhancement", "kind:parent", "phase:integration"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", partial)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "ALREADY_MIGRATED")
        self.assertEqual(partial.writes, 1)

        definition_partial = LabelMigrationGitHub(["enhancement"])
        definition_partial.fail_definition_name = "phase:integration"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", definition_partial)
        self.assertEqual(status, 2)
        self.assertIn("response loss", json.loads(output.getvalue())["reasons"][0])
        self.assertIn("kind:parent", definition_partial.definitions)
        self.assertNotIn("phase:integration", definition_partial.definitions)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", definition_partial)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "MIGRATED")
        self.assertEqual(definition_partial.labels,
                         ["enhancement", "kind:parent", "phase:integration"])

    def test_delivery_parent_requires_integration_and_approval_does_not_activate_or_merge(self):
        blocked_inputs = integration_fixture()
        blocked_inputs["child_issue_rows"][-1]["state"] = "open"
        blocked = evaluate_parent_integration(**blocked_inputs)
        args = SimpleNamespace(issue=26, verification_comment_id=None, acceptance_comment_id=None)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch("p_ases.cli._read_parent_integration", return_value=(blocked, Path(directory) / "blocked.json", None, None)), \
                patch("p_ases.cli._advance_parent_to_user_review") as advance_phase, \
                contextlib.redirect_stdout(output):
            status = _delivery_parent(args, "octo/repo", Path(directory), object())
            self.assertFalse((Path(directory) / ".p_ases" / "user-review" / "26").exists())
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())["parent_user_review"], "NOT_EVALUATED")
        advance_phase.assert_not_called()

        passed = evaluate_parent_integration(**integration_fixture())
        review_subject = _parent_review_subject_from_integration(passed)
        review_comment_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(
            timespec="seconds").replace("+00:00", "Z")
        comment_row = {
            "id": 811, "created_at": review_comment_time, "updated_at": review_comment_time,
            "body": f"P-ASES-DECISION: APPROVED\nP-ASES-SUBJECT: {review_subject.sha256}",
            "user": {"id": 42, "login": "octocat", "type": "User"},
            "html_url": "https://github.com/octo/repo/issues/26#issuecomment-811",
        }
        parent_issue = {"number": 26, "state": "open", "pull_request": None,
                        "repository_url": "https://api.github.com/repos/octo/repo", "body": "parent",
                        "labels": [{"name": "kind:parent"}, {"name": "phase:user-review"}]}

        class ParentGitHub:
            def issue(self, _number):
                return parent_issue

            def issue_comments(self, _number):
                return [comment_row]

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with patch("p_ases.cli._read_parent_integration",
                       return_value=(passed, Path(directory) / "integration.json", None, None)), \
                    patch("p_ases.cli._parent_adc_authority", return_value=("b" * 64, object())), \
                    patch("p_ases.cli._advance_parent_to_user_review"), \
                    contextlib.redirect_stdout(output):
                status = _delivery_parent(args, "octo/repo", Path(directory), ParentGitHub())
            self.assertEqual(status, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "READY_FOR_EXPLICIT_ACTIVATION_APPROVAL")
            self.assertEqual(result["parent_user_review"], "APPROVED")
            self.assertFalse(result["merge_authorized"])
            self.assertFalse(result["activation_issued"])

    def test_legacy_parent_adc_reference_comes_from_current_approved_child_adc(self):
        content = (
            f"Parent contract: `{PARENT_ISSUE_CONTRACT_SOURCE}` at `{PARENT_ISSUE_CONTRACT_COMMIT}`\n"
            f"Parent ADC SHA-256: `{'f' * 64}`\n"
        ).encode()
        self.assertEqual(_parent_contract_declaration(content), (
            PARENT_ISSUE_CONTRACT_SOURCE, PARENT_ISSUE_CONTRACT_COMMIT, "f" * 64,
        ))

        pointer = SimpleNamespace(state="approved")
        approved_adc = SimpleNamespace(
            contract=SimpleNamespace(content=content),
            pointer=pointer,
        )

        class ContentGitHub:
            def __init__(self):
                self.calls = []

            def content_at_ref(self, path, ref):
                self.calls.append((path, ref))
                return b"pinned migration contract source\n"

        github = ContentGitHub()
        with patch("p_ases.parent_gate.verify_adc", return_value=approved_adc) as verify:
            parent_digest, child_pointer = _parent_adc_authority(github)
        verify.assert_called_once_with(github, 31)
        self.assertEqual(parent_digest, "f" * 64)
        self.assertIs(child_pointer, pointer)
        self.assertEqual(github.calls, [(PARENT_ISSUE_CONTRACT_SOURCE, PARENT_ISSUE_CONTRACT_COMMIT)])

    def test_parent_contract_reference_must_be_unique_and_exactly_pinned(self):
        valid = (
            f"Parent contract: `{PARENT_ISSUE_CONTRACT_SOURCE}` at `{PARENT_ISSUE_CONTRACT_COMMIT}`\n"
            f"Parent ADC SHA-256: `{'f' * 64}`\n"
        ).encode()
        invalid = (
            valid + valid,
            valid.replace(PARENT_ISSUE_CONTRACT_COMMIT.encode(), b"0" * 40),
            valid.replace(b"f" * 64, b"not-a-digest"),
            b"\xff",
        )
        for content in invalid:
            with self.subTest(content=content[:50]), self.assertRaises(IntegrationError):
                _parent_contract_declaration(content)

    def test_parent_adc_authority_requires_approved_pointer_and_pinned_source(self):
        content = (
            f"Parent contract: `{PARENT_ISSUE_CONTRACT_SOURCE}` at `{PARENT_ISSUE_CONTRACT_COMMIT}`\n"
            f"Parent ADC SHA-256: `{'f' * 64}`\n"
        ).encode()
        for state, source in (("draft", b"present"), ("approved", b"")):
            with self.subTest(state=state, source=source):
                adc = SimpleNamespace(
                    contract=SimpleNamespace(content=content),
                    pointer=SimpleNamespace(state=state),
                )

                class ContentGitHub:
                    def content_at_ref(self, path, ref):
                        return source

                with patch("p_ases.parent_gate.verify_adc", return_value=adc):
                    with self.assertRaises(IntegrationError):
                        _parent_adc_authority(ContentGitHub())

    def test_u07_six_closed_merged_children_and_exact_evidence_can_pass(self):
        result = evaluate_parent_integration(**integration_fixture())
        self.assertEqual(result.status, "PASS")
        self.assertEqual(tuple(row.issue_number for row in result.subject.children), EXPECTED)
        self.assertEqual(result.subject.expected_child_issue_numbers, EXPECTED)
        self.assertEqual(tuple(number for number, _dependencies in result.subject.declared_dependency_graph), EXPECTED)
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(len({child.merge_sha40 for child in result.subject.children}), 6)

    def test_u07_unmerged_or_open_child_blocks_without_guessing_provenance(self):
        for target in ("issue", "pr", "merge"):
            with self.subTest(target=target):
                kwargs = integration_fixture()
                if target == "issue":
                    kwargs["child_issue_rows"][-1]["state"] = "open"
                elif target == "pr":
                    kwargs["merged_pr_rows"][-1]["merged_at"] = None
                else:
                    kwargs["merged_pr_rows"][-1]["merge_commit_sha"] = "bad"
                self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_u07_unaccepted_or_missing_integration_evidence_blocks(self):
        for name, value in (
            ("integration_verification", None),
            ("integration_acceptance", None),
            ("integration_verification", IntegrationGateEvidence(
                "verification", "octo/repo", 26, "b" * 64, MAIN, "FAIL", "c" * 64, "issue-comment:803")),
            ("integration_acceptance", IntegrationGateEvidence(
                "acceptance", "octo/repo", 26, "b" * 64, "f" * 40, "PASS", "d" * 64, "issue-comment:804")),
        ):
            kwargs = integration_fixture()
            kwargs[name] = value
            self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_native_children_duplicates_and_missing_records_block(self):
        cases = (
            lambda a: a["native_sub_issues"].pop(),
            lambda a: a["native_sub_issues"].append(dict(a["native_sub_issues"][0])),
            lambda a: a["child_issue_rows"].pop(),
            lambda a: a["merged_pr_rows"].pop(),
            lambda a: a["merged_pr_rows"].append(dict(a["merged_pr_rows"][0])),
        )
        for mutate in cases:
            kwargs = integration_fixture()
            mutate(kwargs)
            self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_dependency_cycle_and_incomplete_graph_block(self):
        kwargs = integration_fixture()
        kwargs["declared_dependencies"] = {**DAG, 27: (32,)}
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")
        kwargs = integration_fixture()
        kwargs["actual_blockers_by_issue"][31] = (999,)
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_child_merge_timestamps_must_follow_the_declared_dependencies(self):
        kwargs = integration_fixture()
        kwargs["merged_pr_rows"][0]["merged_at"] = "2026-10-12T00:05:00Z"
        result = evaluate_parent_integration(**kwargs)
        self.assertEqual(result.status, "BLOCKED")
        self.assertTrue(any("merged before dependency" in reason for reason in result.reasons))

    def test_parent_closing_reference_is_rejected(self):
        kwargs = integration_fixture()
        kwargs["merged_pr_rows"][0]["body"] += "\nCloses #26\n"
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_merge_commit_must_be_confirmed_in_current_main(self):
        kwargs = integration_fixture()
        kwargs["merge_sha_ancestry"].pop(f"{27:040x}")
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")
        kwargs = integration_fixture()
        kwargs["merge_sha_ancestry"][f"{27:040x}"] = False
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_parent_pass_record_cannot_claim_a_stale_child_merge(self):
        result = evaluate_parent_integration(**integration_fixture())
        children = (replace(result.subject.children[0], merge_sha_in_main=False), *result.subject.children[1:])
        invalid = replace(result, subject=replace(result.subject, children=children))
        with self.assertRaisesRegex(IntegrationError, "PASS lacks the exact child"):
            invalid.validate()

    def test_typed_parent_gate_evidence_round_trips_exact_subject(self):
        kwargs = integration_fixture()
        evidence = kwargs["integration_verification"]
        self.assertEqual(IntegrationGateEvidence.from_dict(__import__("json").loads(evidence.to_bytes())), evidence)
        stale = IntegrationGateEvidence.from_dict(__import__("json").loads(evidence.to_bytes()))
        self.assertNotEqual(stale.main_sha40, "f" * 40)

    def test_parent_gate_evidence_comment_uses_real_git_sha_and_double_reads_external_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "P-ASES test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "pases@example.invalid"], check=True)
            (repo / "README.md").write_text("real target commit\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "record target main"], check=True)
            main_sha = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            github = trusted_actions_fixture(main_sha)
            bundle = _parent_gate_bundle_from_actions(github, 500, "verification", "octo/repo",
                                                      "b" * 64, main_sha)
            comment_id = 9876
            comment = {
                "id": comment_id, "body": bundle.to_body(),
                "created_at": "2026-10-12T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
                "issue_url": "https://api.github.com/repos/octo/repo/issues/26",
                "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id}",
                "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id}",
                "user": {"id": 42, "login": "octocat", "type": "User"},
            }

            class CommentGitHub:
                def __init__(self, actions):
                    self.actions = actions
                    self.row = comment
                    self.reads = 0
                    self.list_reads = 0
                    self.duplicate = False
                    self.extra = None
                    self.response_overrides = {}
                def __getattr__(self, name):
                    return getattr(self.actions, name)
                def _response(self, source, index, value):
                    result = dict(value)
                    override = self.response_overrides.get((source, index), {})
                    if "user" in override:
                        result["user"] = {**result.get("user", {}), **override["user"]}
                    result.update({key: value for key, value in override.items() if key != "user"})
                    if "user" in result:
                        result["user"] = {
                            **result["user"],
                            "avatar_url": f"https://avatars.example/{source}?read={index}",
                        }
                    return result
                def issue_comment(self, _issue, _comment):
                    index = self.reads
                    self.reads += 1
                    if self.row is None:
                        raise GitHubError("comment deleted")
                    return self._response("direct", index, self.row)
                def issue_comments(self, _issue):
                    index = self.list_reads
                    self.list_reads += 1
                    if self.row is None:
                        return []
                    if self.extra is not None:
                        return [self._response("list", index, self.row), dict(self.extra)]
                    return ([self._response("list", index, self.row),
                             self._response("list", index, self.row)] if self.duplicate
                            else [self._response("list", index, self.row)])
                def authenticated_user(self):
                    return {"id": 42, "login": "octocat", "type": "User"}

            github = CommentGitHub(github)
            # Direct-comment and issue-comment-list APIs return different avatar URLs;
            # those volatile profile fields must not affect comment identity.
            evidence = _load_parent_gate_evidence_from_github(
                github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            self.assertEqual(evidence.source_reference, f"issue-comment:{comment_id}")
            self.assertEqual(evidence.main_sha40, main_sha)
            self.assertEqual(github.reads, 6)

            payload = json.loads(bundle.result_bytes)
            check = payload["checks"][0]
            fake_reference = check["evidence_reference"]
            fake_content = b"verified by handwritten PASS data\n"
            check["evidence_sha256"] = hashlib.sha256(fake_content).hexdigest()
            fake_bundle = replace(
                bundle,
                result_bytes=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n",
                artifacts=tuple((name, fake_content if name == fake_reference else content)
                                for name, content in bundle.artifacts),
            )
            github.row = {**comment, "body": fake_bundle.to_body()}
            with self.assertRaisesRegex(IntegrationError, "trusted Actions run result"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.row = comment

            with self.assertRaisesRegex(IntegrationError, "exact current main/ADC subject"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "f" * 64)
            github.row = {**comment, "issue_url": "https://api.github.com/repos/octo/repo/issues/27"}
            with self.assertRaisesRegex(IntegrationError, "repository or Issue identity"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.row = comment
            github.duplicate = True
            with self.assertRaisesRegex(IntegrationError, "missing or duplicated"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.duplicate = False
            github.extra = {**comment, "id": comment_id + 1,
                            "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id + 1}",
                            "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id + 1}"}
            with self.assertRaisesRegex(IntegrationError, "duplicate or mismatched comment IDs"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.extra = None

            with self.assertRaisesRegex(IntegrationError, "current main/ADC subject"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, "f" * 40, "verification", "octo/repo", "b" * 64)
            github.row = {**comment, "updated_at": "2026-10-12T00:01:00Z"}
            with self.assertRaisesRegex(IntegrationError, "edited"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.row = {**comment, "user": {"id": 99, "login": "other", "type": "User"}}
            with self.assertRaisesRegex(IntegrationError, "author is not the authenticated"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.row = None
            with self.assertRaisesRegex(GitHubError, "comment deleted"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)

    def test_parent_evidence_comment_rejects_stable_author_identity_changes_in_each_read(self):
        main_sha = "c" * 40
        actions = trusted_actions_fixture(main_sha)
        bundle = _parent_gate_bundle_from_actions(actions, 500, "verification", "octo/repo",
                                                  "b" * 64, main_sha)
        comment_id = 9876
        comment = {
            "id": comment_id, "body": bundle.to_body(),
            "created_at": "2026-10-12T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
            "issue_url": "https://api.github.com/repos/octo/repo/issues/26",
            "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id}",
            "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id}",
            "user": {"id": 42, "login": "octocat", "type": "User"},
        }

        class CommentGitHub:
            def __init__(self):
                self.actions = actions
                self.row = comment
                self.direct_reads = 0
                self.list_reads = 0
                self.overrides = {}
                self.authenticated = {"id": 42, "login": "octocat", "type": "User"}
            def __getattr__(self, name):
                return getattr(self.actions, name)
            def _read(self, source, index, value):
                row = dict(value)
                override = self.overrides.get((source, index), {})
                if "user" in override:
                    row["user"] = {**row["user"], **override["user"]}
                row.update({key: item for key, item in override.items() if key != "user"})
                return row
            def issue_comment(self, _issue, _comment):
                index = self.direct_reads
                self.direct_reads += 1
                return self._read("direct", index, self.row)
            def issue_comments(self, _issue):
                index = self.list_reads
                self.list_reads += 1
                return [self._read("list", index, self.row)]
            def authenticated_user(self):
                return self.authenticated

        # The first direct response, collection response, and second direct response
        # are each independently security-sensitive.
        for source, read_index in (("direct", 0), ("list", 0), ("direct", 1)):
            for field, invalid_value in (("id", 99), ("login", "impostor"), ("type", "Bot")):
                with self.subTest(source=source, read_index=read_index, field=field):
                    github = CommentGitHub()
                    github.overrides[(source, read_index)] = {"user": {field: invalid_value}}
                    with self.assertRaises(IntegrationError):
                        _load_parent_gate_evidence_from_github(
                            github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)

        github = CommentGitHub()
        github.authenticated = {"id": 42, "login": "OctoCat", "type": "User"}
        github.overrides[("direct", 0)] = {"user": {"login": "OCTOCAT"}}
        github.overrides[("list", 0)] = {"user": {"login": "octocat"}}
        github.overrides[("direct", 1)] = {"user": {"login": "OcToCaT"}}
        evidence = _load_parent_gate_evidence_from_github(
            github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
        self.assertEqual(evidence.source_reference, f"issue-comment:{comment_id}")

        github = CommentGitHub()
        github.authenticated = {"id": 42, "login": "different-login", "type": "User"}
        with self.assertRaisesRegex(IntegrationError, "authenticated GitHub user"):
            _load_parent_gate_evidence_from_github(
                github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)

        for invalid_id in (0, -1, True):
            with self.subTest(author_invalid_id=invalid_id):
                github = CommentGitHub()
                github.overrides[("direct", 0)] = {"user": {"id": invalid_id}}
                with self.assertRaises(IntegrationError):
                    _load_parent_gate_evidence_from_github(
                        github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            with self.subTest(authenticated_invalid_id=invalid_id):
                github = CommentGitHub()
                github.authenticated = {"id": invalid_id, "login": "octocat", "type": "User"}
                with self.assertRaises(IntegrationError):
                    _load_parent_gate_evidence_from_github(
                        github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)

        github = CommentGitHub()
        github.row = {**comment, "user": {key: value for key, value in comment["user"].items()
                                           if key != "id"}}
        with self.assertRaises(IntegrationError):
            _load_parent_gate_evidence_from_github(
                github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)

        github = CommentGitHub()
        github.authenticated = {"login": "octocat", "type": "User"}
        with self.assertRaises(IntegrationError):
            _load_parent_gate_evidence_from_github(
                github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)

    def test_parent_evidence_comment_rejects_changes_to_each_stable_comment_field(self):
        main_sha = "d" * 40
        actions = trusted_actions_fixture(main_sha)
        bundle = _parent_gate_bundle_from_actions(actions, 500, "verification", "octo/repo",
                                                  "b" * 64, main_sha)
        comment_id = 9876
        original = {
            "id": comment_id, "body": bundle.to_body(),
            "created_at": "2026-10-12T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
            "issue_url": "https://api.github.com/repos/octo/repo/issues/26",
            "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id}",
            "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id}",
            "user": {"id": 42, "login": "octocat", "type": "User"},
        }

        class CommentGitHub:
            def __init__(self, row):
                self.actions = actions
                self.row = row
            def __getattr__(self, name):
                return getattr(self.actions, name)
            def issue_comment(self, _issue, _comment):
                return dict(self.row)
            def issue_comments(self, _issue):
                return [dict(self.row)]
            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

        mutations = {
            "id": comment_id + 1,
            "body": original["body"] + "tampered",
            "created_at": "2026-10-11T00:00:00Z",
            "updated_at": "2026-10-12T00:01:00Z",
            "issue_url": "https://api.github.com/repos/octo/repo/issues/27",
            "html_url": "https://github.com/octo/repo/issues/27#issuecomment-9876",
            "url": "https://api.github.com/repos/octo/repo/issues/comments/9877",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = {**original, field: value}
                with self.assertRaises(IntegrationError):
                    _load_parent_gate_evidence_from_github(
                        CommentGitHub(changed), comment_id, main_sha, "verification", "octo/repo", "b" * 64)

    def test_parent_evidence_blocks_failed_or_stale_actions_and_acceptance_steps(self):
        main_sha = "1" * 40
        github = trusted_actions_fixture(main_sha)
        github.jobs[0]["steps"][0]["conclusion"] = "failure"
        with self.assertRaisesRegex(IntegrationError, "did not pass"):
            _parent_gate_bundle_from_actions(github, 500, "verification", "octo/repo", "b" * 64, main_sha)

        github = trusted_actions_fixture(main_sha)
        with self.assertRaisesRegex(IntegrationError, "stale or ambiguous"):
            _parent_gate_bundle_from_actions(github, 499, "verification", "octo/repo", "b" * 64, main_sha)

        github = trusted_actions_fixture(main_sha)
        original_reader = github.workflow_runs_for_ref

        def superseded_run(sha, *, workflow_path, event):
            return [*original_reader(sha, workflow_path=workflow_path, event=event),
                    {**github.run, "id": 501, "run_number": 501, "conclusion": "failure"}]

        github.workflow_runs_for_ref = superseded_run
        with self.assertRaisesRegex(IntegrationError, "stale or ambiguous"):
            _parent_gate_bundle_from_actions(github, 500, "verification", "octo/repo", "b" * 64, main_sha)

        github = trusted_actions_fixture(main_sha)
        github.checks[0]["app"]["id"] = 1
        with self.assertRaisesRegex(IntegrationError, "Check Run provenance"):
            _parent_gate_bundle_from_actions(github, 500, "verification", "octo/repo", "b" * 64, main_sha)

        github = trusted_actions_fixture(main_sha)
        github.jobs[0]["check_run_url"] = "https://api.github.com/repos/attacker/repo/check-runs/9001"
        with self.assertRaisesRegex(IntegrationError, "foreign-repository Check Run URL"):
            _parent_gate_bundle_from_actions(github, 500, "verification", "octo/repo", "b" * 64, main_sha)

        github = trusted_actions_fixture(main_sha)
        github.jobs.pop(0)
        with self.assertRaisesRegex(IntegrationError, "complete fixed job set"):
            _parent_gate_bundle_from_actions(github, 500, "verification", "octo/repo", "b" * 64, main_sha)

        acceptance = trusted_actions_fixture(main_sha, "acceptance", 700)
        acceptance.jobs[0]["steps"][-1]["conclusion"] = "skipped"
        with self.assertRaisesRegex(IntegrationError, "acceptance step did not pass"):
            _parent_gate_bundle_from_actions(acceptance, 700, "acceptance", "octo/repo", "b" * 64, main_sha)

        acceptance = trusted_actions_fixture(main_sha, "acceptance", 700)
        generated_distribution = next(step for step in acceptance.jobs[0]["steps"]
                                      if step["name"] == "Check generated distributions")
        generated_distribution["conclusion"] = "failure"
        with self.assertRaisesRegex(IntegrationError, "acceptance step did not pass"):
            _parent_gate_bundle_from_actions(acceptance, 700, "acceptance", "octo/repo", "b" * 64, main_sha)

    def test_parent_evidence_rejects_the_old_pull_request_run_for_both_kinds(self):
        for kind, expected_path, expected_event in (
            ("verification", PARENT_CI_WORKFLOW, "push"),
            ("acceptance", PARENT_ACCEPTANCE_WORKFLOW, "workflow_dispatch"),
        ):
            with self.subTest(kind=kind):
                github = trusted_actions_fixture(MAIN, kind, 38232034746)
                github.run.update({
                    "path": PARENT_CI_WORKFLOW,
                    "event": "pull_request",
                    "head_branch": "pases/old-pr",
                    "head_sha": "d2a9d3d" + "0" * 33,
                })
                original = github.workflow_runs_for_ref
                requested = []

                def record_request(sha, *, workflow_path, event):
                    requested.append((workflow_path, event))
                    return original(sha, workflow_path=workflow_path, event=event)

                github.workflow_runs_for_ref = record_request
                with self.assertRaisesRegex(IntegrationError, "no .* GitHub Actions run exists"):
                    _parent_gate_bundle_from_actions(
                        github, 38232034746, kind, "octo/repo", "b" * 64, MAIN)
                self.assertEqual(requested, [(expected_path, expected_event)])

    def test_integration_skill_cli_examples_match_event_and_id_contracts(self):
        skill = (ROOT / "workflow/skills/integration-validation/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`.github/workflows/ci.yml`", skill)
        self.assertIn("`push`", skill)
        self.assertIn("`.github/workflows/parent-integration.yml`", skill)
        self.assertIn("`workflow_dispatch`", skill)
        self.assertIn("exact current `main` SHA", skill)
        self.assertNotIn("38232034746", skill)
        issue_skill = (ROOT / "workflow/skills/issue-decomposition/SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("issue integration-check 26", issue_skill)

        blocks = skill.split("~~~sh")[1:]
        commands = []
        for block in blocks:
            commands.extend(line.strip() for line in block.split("~~~", 1)[0].splitlines()
                            if line.strip().startswith("python -m p_ases "))
        self.assertEqual(len(commands), 4, commands)
        replacements = {
            "VERIFICATION_RUN_ID": "501",
            "ACCEPTANCE_RUN_ID": "702",
            "VERIFICATION_COMMENT_ID": "801",
            "ACCEPTANCE_COMMENT_ID": "802",
        }
        parser = _parser()
        parsed = []
        for command in commands:
            for placeholder, value in replacements.items():
                command = command.replace(placeholder, value)
            argv = shlex.split(command)
            self.assertEqual(argv[:3], ["python", "-m", "p_ases"])
            parsed.append(parser.parse_args(argv[3:]))
        self.assertEqual([(args.namespace, args.verb) for args in parsed], [
            ("delivery", "parent-evidence"), ("delivery", "parent-evidence"),
            ("issue", "integration-check"), ("delivery", "parent"),
        ])
        self.assertEqual([(parsed[0].kind, parsed[0].run_id), (parsed[1].kind, parsed[1].run_id)],
                         [("verification", 501), ("acceptance", 702)])
        for args in parsed[2:]:
            self.assertEqual((args.verification_comment_id, args.acceptance_comment_id), (801, 802))

    def test_separate_current_main_runs_and_comment_ids_produce_parent_integration_pass(self):
        verification_actions = trusted_actions_fixture(MAIN, "verification", 501)
        acceptance_actions = trusted_actions_fixture(MAIN, "acceptance", 702)
        verification_bundle = _parent_gate_bundle_from_actions(
            verification_actions, 501, "verification", "octo/repo", "b" * 64, MAIN)
        acceptance_bundle = _parent_gate_bundle_from_actions(
            acceptance_actions, 702, "acceptance", "octo/repo", "b" * 64, MAIN)
        self.assertNotEqual(verification_bundle.workflow_run_id, acceptance_bundle.workflow_run_id)
        verification_run = json.loads(verification_bundle.result_bytes)["workflow_run"]
        acceptance_run = json.loads(acceptance_bundle.result_bytes)["workflow_run"]
        self.assertEqual((verification_run["id"], verification_run["path"], verification_run["event"],
                          verification_run["head_branch"], verification_run["head_sha40"]),
                         (501, PARENT_CI_WORKFLOW, "push", "main", MAIN))
        self.assertEqual((acceptance_run["id"], acceptance_run["path"], acceptance_run["event"],
                          acceptance_run["head_branch"], acceptance_run["head_sha40"]),
                         (702, PARENT_ACCEPTANCE_WORKFLOW, "workflow_dispatch", "main", MAIN))

        def comment(comment_id, bundle):
            return {
                "id": comment_id, "body": bundle.to_body(),
                "created_at": "2026-10-12T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
                "issue_url": "https://api.github.com/repos/octo/repo/issues/26",
                "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id}",
                "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id}",
                "user": {"id": 42, "login": "octocat", "type": "User"},
            }

        comments = {
            801: comment(801, verification_bundle),
            802: comment(802, acceptance_bundle),
        }

        class EvidenceGitHub:
            def __init__(self):
                self.active_actions = None
                self.action_sources = (verification_actions, acceptance_actions)
                self.direct_reads = 0
                self.list_reads = 0

            def workflow_runs_for_ref(self, sha, *, workflow_path, event):
                for source in self.action_sources:
                    runs = source.workflow_runs_for_ref(sha, workflow_path=workflow_path, event=event)
                    if runs:
                        self.active_actions = source
                        return runs
                return []

            def workflow_run_jobs(self, run_id):
                return self.active_actions.workflow_run_jobs(run_id)

            def check_runs_for_ref(self, sha):
                return self.active_actions.check_runs_for_ref(sha)

            def issue_comment(self, issue_id, comment_id):
                self.assert_issue(issue_id)
                row = dict(comments[comment_id])
                row["user"] = {**row["user"], "avatar_url":
                                f"https://avatars.example/direct?read={self.direct_reads}"}
                self.direct_reads += 1
                return row

            def issue_comments(self, issue_id):
                self.assert_issue(issue_id)
                rows = []
                for row in comments.values():
                    item = dict(row)
                    item["user"] = {**item["user"], "avatar_url":
                                    f"https://avatars.example/list?read={self.list_reads}"}
                    rows.append(item)
                self.list_reads += 1
                return rows

            @staticmethod
            def assert_issue(issue_id):
                if issue_id != 26:
                    raise AssertionError(issue_id)

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

        github = EvidenceGitHub()
        verification = _load_parent_gate_evidence_from_github(
            github, 801, MAIN, "verification", "octo/repo", "b" * 64)
        acceptance = _load_parent_gate_evidence_from_github(
            github, 802, MAIN, "acceptance", "octo/repo", "b" * 64)
        self.assertEqual((verification.source_reference, acceptance.source_reference),
                         ("issue-comment:801", "issue-comment:802"))

        args = _parser().parse_args([
            "issue", "integration-check", "26",
            "--verification-comment-id", "801", "--acceptance-comment-id", "802",
            "--repo", "octo/repo", "--root", ".",
        ])
        integration_github = parent_integration_github_fixture(
            verification_bundle, acceptance_bundle, verification_actions, acceptance_actions)
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = _issue_integration_check(
                    args, "octo/repo", Path(directory), integration_github)
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["parent_issue"], 26)
        self.assertEqual(len(result["integration_sha256"]), 64)
        self.assertIn("issue-comment:801", result["evidence_refs"])
        self.assertIn("issue-comment:802", result["evidence_refs"])
        self.assertEqual(integration_github.direct_comment_ids.count(801), 12)
        self.assertEqual(integration_github.direct_comment_ids.count(802), 12)
        self.assertEqual(integration_github.sub_issue_reads, 2)
        self.assertEqual(integration_github.blocked_by_calls, [*EXPECTED, *EXPECTED])

        # The same exact comment IDs cannot pass after main advances to another SHA.
        integration_github.main_sha40 = "f" * 40
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = _issue_integration_check(
                    args, "octo/repo", Path(directory), integration_github)
        self.assertEqual(status, 2)
        blocked = json.loads(output.getvalue())
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn("exact current main/ADC subject", blocked["reasons"][0])

    def test_parent_evidence_publish_reuses_exact_comment_and_rejects_conflict(self):
        main_sha = "1" * 40
        pointer = object()
        actions = trusted_actions_fixture(main_sha)

        class PublishGitHub:
            def __init__(self):
                self.actions = actions
                self.comments = []
                self.posts = 0
                self.issue_body = "parent contract"
                self.direct_reads = 0
                self.list_reads = 0

            def __getattr__(self, name):
                return getattr(self.actions, name)

            def issue(self, _number):
                return {"number": 26, "state": "open", "pull_request": None,
                        "repository_url": "https://api.github.com/repos/octo/repo",
                        "body": self.issue_body}

            def issue_comments(self, _number):
                rows = []
                for row in self.comments:
                    item = dict(row)
                    item["user"] = {**item["user"], "avatar_url":
                                    f"https://avatars.example/list?read={self.list_reads}"}
                    rows.append(item)
                self.list_reads += 1
                return rows

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

            def create_issue_comment(self, _number, body):
                self.posts += 1
                comment_id = 9000 + self.posts
                row = {"id": comment_id, "body": body,
                       "created_at": "2026-10-12T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
                       "issue_url": "https://api.github.com/repos/octo/repo/issues/26",
                       "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id}",
                       "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id}",
                       "user": {"id": 42, "login": "octocat", "type": "User"}}
                self.comments.append(row)
                return row

            def issue_comment(self, _number, comment_id):
                row = next(dict(row) for row in self.comments if row["id"] == comment_id)
                row["user"] = {**row["user"], "avatar_url":
                                f"https://avatars.example/direct?read={self.direct_reads}"}
                self.direct_reads += 1
                return row

        github = PublishGitHub()
        args = SimpleNamespace(issue=26, kind="verification", run_id=500)
        patches = (patch("p_ases.cli._parent_adc_authority", return_value=("b" * 64, pointer)),
                   patch("p_ases.cli._parent_current_main_sha", return_value=main_sha))
        for active in patches:
            active.start()
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = _publish_parent_gate_evidence(args, "octo/repo", ROOT, github)
            self.assertEqual(status, 0)
            first = json.loads(output.getvalue())
            self.assertEqual(first["status"], "PUBLISHED")
            self.assertEqual(github.posts, 1)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = _publish_parent_gate_evidence(args, "octo/repo", ROOT, github)
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "REUSED")
            self.assertEqual(github.posts, 1)
            github.comments[0]["user"]["login"] = "different-login"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = _publish_parent_gate_evidence(args, "octo/repo", ROOT, github)
            self.assertEqual(status, 2)
            self.assertIn("authenticated", json.loads(output.getvalue())["reasons"][0])
            self.assertEqual(github.posts, 1)
            github.comments[0]["user"]["login"] = "octocat"

            github.actions.jobs[0]["steps"][0]["conclusion"] = "failure"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = _publish_parent_gate_evidence(args, "octo/repo", ROOT, github)
            self.assertEqual(status, 2)
            self.assertIn("did not pass", json.loads(output.getvalue())["reasons"][0])
            self.assertEqual(github.posts, 1)
        finally:
            for active in patches:
                active.stop()

    def test_github_parent_label_definition_adapter_is_readback_checked(self):
        github = GitHub("octo/repo")
        expected = {"name": "phase:integration", "color": "0e8a16",
                    "description": "Workflow phase: integration"}
        with patch.object(github, "request", return_value=expected) as request:
            self.assertEqual(github.create_repository_label(**expected), expected)
        self.assertEqual(request.call_args.args[:2], ("POST", "repos/octo/repo/labels"))
        self.assertEqual(request.call_args.args[2], expected)
        with patch.object(github, "request", return_value={**expected, "color": "ffffff"}):
            with self.assertRaisesRegex(GitHubError, "did not match"):
                github.create_repository_label(**expected)

    def test_frozen_child_set_cannot_be_empty_or_duplicate(self):
        kwargs = integration_fixture()
        kwargs["expected_child_issue_numbers"] = (27, 27)
        with self.assertRaises(IntegrationError):
            evaluate_parent_integration(**kwargs)


if __name__ == "__main__":
    unittest.main()
