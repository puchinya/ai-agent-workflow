from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import ADCError, parse_adc, publish_adc, verify_adc  # noqa: E402
from p_ases.consumer_activation import (  # noqa: E402
    APPROVAL_MARKER, ISSUE_MARKER, RECORD_MARKER, ConsumerActivationError, ConsumerActivationRecord,
    RequiredCheckEvidence, _default_activation_adc, _default_profile, activation_checkpoint_path,
    read_activation_checkpoint,
    read_consumer_activation_history, read_consumer_activation_record,
    setup_consumer_activation,
    verify_and_record_activation,
)
from p_ases.github import GitHubError  # noqa: E402
from p_ases.checkpoint import PRBinding, write_pr_binding  # noqa: E402
from p_ases.execution import ExecutionBinding, write_binding  # noqa: E402
from p_ases.gate_policy import (  # noqa: E402
    PASES_POLICY, choose_gate_for_new_issue, pin_gate_selection, read_gate_selection,
)
from p_ases.git import (  # noqa: E402
    GitError, activation_profile_bytes_at_commit, changed_paths_between, commit_and_push_one_path,
    fetch_remote_branch_exact, head_sha40, remote_branch_sha, run_git, worktree_clean,
)
from p_ases.work import execution_binding_path  # noqa: E402


REPO = "owner/consumer"
ISSUE = 71
PR = 81
MERGE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MAIN_SHA = "c" * 40
APP_ID = 15368
MERGED_AT = "2026-10-14T12:00:00Z"
USER = {"id": 42, "login": "repo-admin", "type": "User"}


def comment_row(comment_id: int, body: str, *, author: dict | None = None,
                timestamp: str = "2026-10-14T12:01:00Z", issue_number: int = ISSUE) -> dict:
    return {
        "id": comment_id, "body": body, "created_at": timestamp,
        "updated_at": timestamp,
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{issue_number}",
        "html_url": f"https://github.com/{REPO}/issues/{issue_number}#issuecomment-{comment_id}",
        "url": f"https://api.github.com/repos/{REPO}/issues/comments/{comment_id}",
        "user": copy.deepcopy(author or USER),
    }


class FakeGitHub:
    repo = REPO

    def __init__(self):
        self.comments: list[dict] = []
        self.other_comments: dict[int, list[dict]] = {}
        self.issue_row = {
            "number": ISSUE, "state": "open", "pull_request": None,
            "repository_url": f"https://api.github.com/repos/{REPO}",
            "body": f"{ISSUE_MARKER}\n\nActivation policy and history.",
        }
        self.main_sha = MAIN_SHA
        self.comment_time = "2026-10-14T12:01:00Z"
        self.duplicate_issue = False
        self.issue_comment_list_calls = 0
        self.mutate_on_list_call: int | None = None
        self.mutate_marker = APPROVAL_MARKER
        self.fail_record_once = False
        self.fail_create_pr_once = False
        self.check_runs_reads = 0
        self.workflow_job_reads = 0
        self.workflow_jobs: dict[int, dict] = {}
        self.permission = "admin"
        self.ordinary_created_at = "2026-10-14T12:02:00Z"
        self.issue_created_at_by_number: dict[int, str] = {}
        self.head_sha = HEAD_SHA
        self.checks = [{"id": 1, "name": "ci", "head_sha": self.head_sha,
                        "created_at": "2026-10-14T11:59:00Z",
                        "started_at": "2026-10-14T11:59:01Z",
                        "completed_at": "2026-10-14T11:59:02Z",
                        "status": "completed", "conclusion": "success", "app": {"id": APP_ID}}]
        self.profile_bytes = json.dumps({
            "schema_version": 2, "initialized": True, "project_name": "consumer",
            "components": [], "branch": {"prefix": "feature", "max_slug_length": 48,
                                             "cleanup_on_switch": [],
                                             "required_checks": [{"name": "ci", "trusted_app_id": APP_ID}]},
            "workspace": {"isolation": "auto"},
            "milestones": {"mode": "optional", "version_source": None},
            "hooks": {"branch_switch": [], "verify_quick": [], "verify_final": []},
            "activation": {"issue_number": ISSUE},
        }).encode()
        self.pr = None
        self.prs: dict[int, dict] = {}
        self.next_pr_number = PR
        self.profile_by_commit = {MERGE_SHA: self.profile_bytes}
        self.setup_root: Path | None = None

    def repository_metadata(self):
        return {"default_branch": "main", "id": 9001, "full_name": REPO,
                "owner": {"id": USER["id"], "login": "owner", "type": "User"}}

    def branch(self, branch):
        sha = self.main_sha if branch == "main" else self.head_sha
        return {"name": branch, "commit": {"sha": sha}}

    def compare_commits(self, _base, _head):
        return {"status": "ahead"}

    def compare_commits(self, base, head):
        return {"status": "identical" if base == head else "ahead"}

    def authenticated_user(self):
        return copy.deepcopy(USER)

    def collaborator_permission(self, login):
        return {"permission": self.permission, "user": copy.deepcopy(USER)}

    def issues(self):
        if self.issue_row is None:
            return []
        rows = [copy.deepcopy(self.issue_row)]
        if self.duplicate_issue:
            duplicate = copy.deepcopy(self.issue_row)
            duplicate["number"] += 1
            rows.append(duplicate)
        return rows

    def create_issue(self, title, body):
        self.issue_row = {
            "number": ISSUE, "state": "open", "pull_request": None,
            "repository_url": f"https://api.github.com/repos/{REPO}", "body": body,
        }
        return {"number": ISSUE}

    def issue(self, number):
        if number == ISSUE:
            return copy.deepcopy(self.issue_row)
        return {"number": number, "state": "open", "pull_request": None,
                "repository_url": f"https://api.github.com/repos/{REPO}",
                "created_at": self.issue_created_at_by_number.get(number, self.ordinary_created_at)}

    def issue_comments(self, number):
        self.issue_comment_list_calls += 1
        selected_comments = self.comments if number == ISSUE else self.other_comments.get(number, [])
        if number == ISSUE and self.mutate_on_list_call == self.issue_comment_list_calls:
            target_id = next(row["id"] for row in self.comments
                             if row["body"].startswith(self.mutate_marker))
            target = next(row for row in self.comments if row["id"] == target_id)
            target["body"] += "\nmutated"
            self.mutate_on_list_call = None
        return copy.deepcopy(selected_comments)

    def issue_comment(self, number, comment_id):
        selected_comments = self.comments if number == ISSUE else self.other_comments.get(number, [])
        matches = [row for row in selected_comments if row["id"] == comment_id]
        if len(matches) != 1:
            raise GitHubError("comment missing or duplicated")
        return copy.deepcopy(matches[0])

    def create_issue_comment(self, number, body):
        if body.startswith(RECORD_MARKER) and self.fail_record_once:
            self.fail_record_once = False
            raise GitHubError("simulated lost record publication")
        selected_comments = self.comments if number == ISSUE else self.other_comments.setdefault(number, [])
        comment_id = max((row["id"] for row in selected_comments), default=0) + 1
        selected_comments.append(comment_row(comment_id, body, timestamp=self.comment_time, issue_number=number))
        return {"id": comment_id}

    def pull_requests_for_refs(self, **kwargs):
        return [copy.deepcopy(row) for row in self.prs.values()
                if row.get("base", {}).get("ref") == kwargs["base_ref"]
                and row.get("head", {}).get("ref") == kwargs["head_ref"]]

    def create_pull_request(self, *, title, body, head_ref, base_ref):
        if self.fail_create_pr_once:
            self.fail_create_pr_once = False
            raise GitHubError("simulated transient PR creation failure")
        adc = verify_adc(self, ISSUE)
        number = self.next_pr_number
        self.next_pr_number += 1
        head_sha = head_sha40(self.setup_root) if self.setup_root is not None else self.head_sha
        self.pr = {
            "number": number, "id": 800 + number, "state": "open", "merged": False, "draft": False,
            "html_url": f"https://github.com/{REPO}/pull/{PR}", "body": body,
            "base": {"ref": base_ref, "sha": MAIN_SHA, "repo": {"full_name": REPO, "id": 9001}},
            "head": {"ref": head_ref, "sha": head_sha, "repo": {"full_name": REPO, "id": 9001}},
        }
        self.pr["html_url"] = f"https://github.com/{REPO}/pull/{number}"
        self.prs[number] = self.pr
        self.proposed_adc = adc
        return {"number": number}

    def pull_request(self, number):
        if number not in self.prs:
            raise GitHubError("wrong PR")
        return copy.deepcopy(self.prs[number])

    def pull_request_files(self, number):
        return [{"filename": ".agent/project.json", "status": "modified"}]

    def regular_content_at_ref(self, path, ref):
        if path != ".agent/project.json" or ref not in self.profile_by_commit:
            raise GitHubError("wrong merged profile subject")
        return self.profile_by_commit[ref]

    def check_runs_for_ref(self, sha):
        self.check_runs_reads += 1
        return copy.deepcopy([row for row in self.checks if row["head_sha"] == sha])

    def check_run(self, check_run_id):
        matches = [row for row in self.checks if row["id"] == check_run_id]
        if len(matches) != 1:
            raise GitHubError("Check Run is missing or duplicated")
        return copy.deepcopy(matches[0])

    def workflow_job_for_check_run(self, check_run):
        self.workflow_job_reads += 1
        job = self.workflow_jobs.get(check_run.get("id"))
        if not isinstance(job, dict):
            raise GitHubError("Actions job is missing")
        if any(job.get(field) != check_run.get(field) for field in
               ("name", "head_sha", "status", "conclusion", "started_at", "completed_at")):
            raise GitHubError("Actions job does not match Check Run")
        return copy.deepcopy(job)


def setup_fake(github: FakeGitHub, *, merge: bool = True) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        profile_path = root / ".agent" / "project.json"
        profile_path.parent.mkdir(parents=True)
        setup_profile = json.loads(github.profile_bytes)
        if github.issue_row is None:
            setup_profile.pop("activation", None)
        profile_path.write_text(json.dumps(setup_profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        with patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation.remote_branch_exists", return_value=False), \
                patch("p_ases.consumer_activation.branch_exists", return_value=False), \
                patch("p_ases.consumer_activation._ensure_setup_branch",
                      side_effect=lambda *_args: (github.head_sha, False)), \
                patch("p_ases.consumer_activation.switch_branch"):
            result = setup_consumer_activation(root, github)
    if result["status"] != "SETUP_PENDING" or result["pr"] != PR:
        raise AssertionError(result)
    if merge:
        github.pr.update({"state": "closed", "merged": True, "merged_at": MERGED_AT,
                          "merged_by": copy.deepcopy(USER), "merge_commit_sha": MERGE_SHA})
        github.prs[github.pr["number"]] = github.pr
        github.profile_by_commit[MERGE_SHA] = github.profile_bytes


def local_consumer_checkout(parent: Path) -> tuple[Path, str]:
    root = parent / "consumer"
    root.mkdir()
    run_git(root, "init", "--quiet", "--initial-branch=main")
    run_git(root, "config", "user.email", "test@example.invalid")
    run_git(root, "config", "user.name", "P-ASES tests")
    project = root / ".agent" / "project.json"
    project.parent.mkdir()
    profile = _default_profile(REPO)
    profile["branch"]["required_checks"] = [{"name": "ci", "trusted_app_id": APP_ID}]
    project.write_text(json.dumps(profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    run_git(root, "add", "--", ".agent/project.json")
    run_git(root, "commit", "--quiet", "-m", "baseline")
    base = head_sha40(root)
    bare = parent / "github.com" / "owner" / "consumer.git"
    bare.parent.mkdir(parents=True)
    run_git(parent, "init", "--quiet", "--bare", str(bare))
    # Keep the fake local remote's path GitHub-shaped on Windows too, where
    # native paths otherwise use backslashes and fail discover_repository().
    run_git(root, "remote", "add", "origin", bare.as_posix())
    run_git(root, "push", "--quiet", "--set-upstream", "origin", "main")
    return root, base


def clone_main_only(parent: Path, remote: Path) -> Path:
    root = parent / "consumer-independent-checkout"
    run_git(parent, "clone", "--quiet", "--single-branch", "--branch", "main",
            remote.as_posix(), str(root))
    run_git(root, "config", "user.email", "test@example.invalid")
    run_git(root, "config", "user.name", "P-ASES tests")
    return root


def watch_activation_writes(github: FakeGitHub):
    return {
        name: unittest.mock.Mock(wraps=getattr(github, name))
        for name in ("create_issue", "create_issue_comment", "create_pull_request")
    }


class ConsumerActivationTests(unittest.TestCase):
    def test_activation_setup_rejects_feature_worktree_before_writes_and_preserves_issue63_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, base = local_consumer_checkout(Path(temporary))
            branch = "codex/issue-63-feature"
            run_git(root, "switch", "--quiet", "--create", branch)
            run_git(root, "commit", "--allow-empty", "--quiet", "-m", "PR #64 feature work")
            feature_head = head_sha40(root)

            exclude = root / ".git" / "info" / "exclude"
            exclude.write_text(exclude.read_text(encoding="utf-8") + "\n/.p_ases/\n", encoding="utf-8")
            execution_path = execution_binding_path(root, 63)
            execution = ExecutionBinding(
                repository=REPO, issue_number=63, adc_comment_id=6236636013,
                adc_sha256="a" * 64, base_ref="main", base_sha=base,
                branch_ref=branch, work_directory=str(root.resolve()), initial_head_sha=base,
            )
            write_binding(execution_path, execution)
            pr_binding_path = execution_path.with_name("pr-binding-000001.json")
            write_pr_binding(pr_binding_path, PRBinding(
                repository=REPO, issue_number=63, adc_comment_id=6236636013,
                adc_sha256="a" * 64, base_sha40=base, branch_ref=branch,
                pr_number=64, pr_head_sha40=feature_head,
            ))
            execution_bytes = execution_path.read_bytes()
            pr_binding_bytes = pr_binding_path.read_bytes()
            self.assertTrue(worktree_clean(root))

            github = FakeGitHub()
            github.main_sha = base
            github.other_comments[63] = [comment_row(700, "existing Issue #63 receipt", issue_number=63)]
            issue63_history = copy.deepcopy(github.other_comments[63])
            issue_before = copy.deepcopy(github.issue_row)
            writes = watch_activation_writes(github)
            for name, spy in writes.items():
                setattr(github, name, spy)

            with self.assertRaisesRegex(ConsumerActivationError, "default branch"):
                setup_consumer_activation(root, github)

            self.assertEqual(run_git(root, "symbolic-ref", "--short", "HEAD"), branch)
            self.assertEqual(head_sha40(root), feature_head)
            self.assertEqual(execution_path.read_bytes(), execution_bytes)
            self.assertEqual(pr_binding_path.read_bytes(), pr_binding_bytes)
            self.assertEqual(github.other_comments[63], issue63_history)
            self.assertEqual(github.issue_row, issue_before)
            self.assertTrue(worktree_clean(root))
            for spy in writes.values():
                spy.assert_not_called()

    def test_activation_setup_rejects_dirty_worktree_before_github_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, base = local_consumer_checkout(Path(temporary))
            dirty_path = root / "untracked.txt"
            dirty_path.write_text("local work in progress\n", encoding="utf-8")
            github = FakeGitHub()
            github.main_sha = base
            writes = watch_activation_writes(github)
            for name, spy in writes.items():
                setattr(github, name, spy)

            with self.assertRaisesRegex(ConsumerActivationError, "clean repository worktree"):
                setup_consumer_activation(root, github)

            self.assertEqual(run_git(root, "symbolic-ref", "--short", "HEAD"), "main")
            self.assertEqual(head_sha40(root), base)
            self.assertEqual(dirty_path.read_text(encoding="utf-8"), "local work in progress\n")
            for spy in writes.values():
                spy.assert_not_called()

    def test_activation_setup_rejects_detached_and_stale_default_worktrees_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root, base = local_consumer_checkout(parent)
            github = FakeGitHub()
            github.main_sha = base
            writes = watch_activation_writes(github)
            for name, spy in writes.items():
                setattr(github, name, spy)

            run_git(root, "checkout", "--quiet", "--detach", base)
            with self.assertRaises(ConsumerActivationError):
                setup_consumer_activation(root, github)
            self.assertEqual(head_sha40(root), base)
            for spy in writes.values():
                spy.assert_not_called()

            stale_parent = parent / "stale"
            stale_parent.mkdir()
            stale_root, stale_base = local_consumer_checkout(stale_parent)
            stale_github = FakeGitHub()
            stale_github.main_sha = "d" * 40
            stale_writes = watch_activation_writes(stale_github)
            for name, spy in stale_writes.items():
                setattr(stale_github, name, spy)
            self.assertEqual(remote_branch_sha(stale_root, "main"), stale_base)
            with self.assertRaisesRegex(ConsumerActivationError, "match GitHub default-branch HEAD"):
                setup_consumer_activation(stale_root, stale_github)
            self.assertEqual(run_git(stale_root, "symbolic-ref", "--short", "HEAD"), "main")
            self.assertEqual(head_sha40(stale_root), stale_base)
            for spy in stale_writes.values():
                spy.assert_not_called()

    def test_solo_owner_empty_ruleset_persists_exact_plan_and_waits_before_setup_pr(self):
        github = FakeGitHub()
        profile = _default_profile(REPO)
        profile["branch"]["required_checks"] = [{"name": "ci", "trusted_app_id": APP_ID}]
        profile["final_delivery"] = {"review_mode": "solo_owner"}
        profile["activation"] = {"issue_number": ISSUE}
        builder = unittest.mock.Mock(return_value={
            "blockers": [], "diff": {"operation": "create"}, "plan_sha256": "d" * 64,
            "policy_proof": {"status": "NOT_CONFIGURED"},
        })
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation._ensure_setup_branch", return_value=(HEAD_SHA, False)), \
                patch("p_ases.consumer_activation.switch_branch"), \
                patch("p_ases.consumer_activation.build_ruleset_plan", builder), \
                patch("p_ases.consumer_activation.write_ruleset_plan") as write_plan, \
                patch("p_ases.consumer_activation.read_verified_managed_policy") as read_policy:
            profile_path = Path(tmp) / ".agent" / "project.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps(profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            result = setup_consumer_activation(Path(tmp), github)
            checkpoint = read_activation_checkpoint(activation_checkpoint_path(Path(tmp), ISSUE))
        self.assertEqual(result["status"], "PENDING_APPROVAL")
        self.assertEqual(result["stage"], "AWAIT_OWNER_POLICY_DECISION")
        self.assertEqual(result["operation"], "CREATE")
        self.assertEqual(result["required_setting_inventory"]["repository_ruleset"], "NEEDS_APPLY")
        self.assertEqual(github.prs, {})
        self.assertEqual(checkpoint.plan_sha256, "d" * 64)
        self.assertEqual(checkpoint.stage, "AWAIT_OWNER_POLICY_DECISION")
        self.assertEqual(checkpoint.setup_commit_sha40, HEAD_SHA)
        self.assertEqual(builder.call_args.kwargs["profile_ref"], HEAD_SHA)
        binding = builder.call_args.kwargs["activation_binding"]
        self.assertEqual(binding["setup_commit_sha40"], HEAD_SHA)
        self.assertEqual(binding["activation_issue_number"], ISSUE)
        write_plan.assert_called_once()
        read_policy.assert_not_called()

    def test_solo_owner_policy_read_403_persists_owner_admin_continuation(self):
        github = FakeGitHub()
        profile = _default_profile(REPO)
        profile["branch"]["required_checks"] = [{"name": "ci", "trusted_app_id": APP_ID}]
        profile["final_delivery"] = {"review_mode": "solo_owner"}
        profile["activation"] = {"issue_number": ISSUE}
        plan = {"blockers": ["CURRENT_BRANCH_POLICY_READBACK_INCOMPLETE",
                              "REPOSITORY_RULESET_INVENTORY_UNAVAILABLE"],
                "diff": {"operation": "blocked"}, "plan_sha256": "d" * 64,
                "policy_proof": {"status": "UNAVAILABLE"}}
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation._ensure_setup_branch", return_value=(HEAD_SHA, False)), \
                patch("p_ases.consumer_activation.switch_branch"), \
                patch("p_ases.consumer_activation.build_ruleset_plan", return_value=plan), \
                patch("p_ases.consumer_activation.write_ruleset_plan") as write_plan:
            profile_path = Path(tmp) / ".agent" / "project.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps(profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            result = setup_consumer_activation(Path(tmp), github)
            checkpoint = read_activation_checkpoint(activation_checkpoint_path(Path(tmp), ISSUE))
        self.assertEqual(result["status"], "ADMIN_POLICY_UNAVAILABLE")
        self.assertEqual(result["stage"], "POLICY_PLAN")
        self.assertEqual(checkpoint.status, "ADMIN_AUTH_REQUIRED")
        self.assertIn("consumer-activation-admin-plan", result["next_permitted_step"])
        self.assertEqual(github.prs, {})
        write_plan.assert_not_called()

    def test_solo_owner_noop_policy_is_double_read_before_setup_pr_creation(self):
        github = FakeGitHub()
        profile = _default_profile(REPO)
        profile["branch"]["required_checks"] = [{"name": "ci", "trusted_app_id": APP_ID}]
        profile["final_delivery"] = {"review_mode": "solo_owner"}
        profile["activation"] = {"issue_number": ISSUE}
        policy = {"ruleset_id": 123, "effective_policy_sha256": "c" * 64,
                  "applied_record_id": 456}
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation._ensure_setup_branch", return_value=(HEAD_SHA, False)), \
                patch("p_ases.consumer_activation.switch_branch"), \
                patch("p_ases.consumer_activation.build_ruleset_plan", return_value={
                    "blockers": [], "diff": {"operation": "noop"}, "plan_sha256": "e" * 64,
                    "policy_proof": {"status": "VERIFIED"},
                }), \
                patch("p_ases.consumer_activation.write_ruleset_plan"), \
                patch("p_ases.consumer_activation.read_verified_managed_policy",
                      return_value=policy) as read_policy:
            profile_path = Path(tmp) / ".agent" / "project.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps(profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            result = setup_consumer_activation(Path(tmp), github)
            checkpoint = read_activation_checkpoint(activation_checkpoint_path(Path(tmp), ISSUE))
        self.assertEqual(result["status"], "SETUP_PENDING")
        self.assertEqual(result["stage"], "SETUP_PR_REVIEW_AND_MERGE")
        self.assertEqual(len(github.prs), 1)
        self.assertEqual(github.pr["head"]["sha"], HEAD_SHA)
        self.assertEqual(read_policy.call_count, 2)
        payload = github.pr["body"]
        self.assertIn('"ruleset_id":123', payload)
        self.assertIn('"ruleset_applied_record_id":456', payload)
        self.assertEqual(checkpoint.status, "SETUP_PENDING")
        self.assertEqual(checkpoint.policy_status, "VERIFIED")

    def test_changed_policy_creates_a_new_policy_bound_setup_generation(self):
        github = FakeGitHub()
        profile = _default_profile(REPO)
        profile["branch"]["required_checks"] = [{"name": "ci", "trusted_app_id": APP_ID}]
        profile["final_delivery"] = {"review_mode": "solo_owner"}
        profile["activation"] = {"issue_number": ISSUE}
        old_policy = {"ruleset_id": 123, "effective_policy_sha256": "c" * 64,
                      "applied_record_id": 456}
        new_policy = {"ruleset_id": 123, "effective_policy_sha256": "d" * 64,
                      "applied_record_id": 457}

        def plan_builder(_root, _github, *, activation_binding, **_kwargs):
            return {"blockers": [], "diff": {"operation": "noop"},
                    "plan_sha256": "f" * 64 if "-g" in activation_binding["setup_branch"] else "e" * 64,
                    "policy_proof": {"status": "VERIFIED"}}

        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation._ensure_setup_branch", return_value=(HEAD_SHA, False)), \
                patch("p_ases.consumer_activation.switch_branch"), \
                patch("p_ases.consumer_activation.build_ruleset_plan", side_effect=plan_builder) as builder, \
                patch("p_ases.consumer_activation.write_ruleset_plan"), \
                patch("p_ases.consumer_activation.read_verified_managed_policy",
                      side_effect=[old_policy, old_policy, new_policy, new_policy, new_policy, new_policy]):
            profile_path = Path(tmp) / ".agent" / "project.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps(profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            first = setup_consumer_activation(Path(tmp), github)
            old_pr = copy.deepcopy(github.prs[first["pr"]])
            second = setup_consumer_activation(Path(tmp), github)
            checkpoint = read_activation_checkpoint(activation_checkpoint_path(Path(tmp), ISSUE))

        self.assertEqual(first["status"], "SETUP_PENDING")
        self.assertEqual(second["status"], "SETUP_PENDING")
        self.assertNotEqual(first["setup_branch"], second["setup_branch"])
        self.assertEqual(github.prs[first["pr"]], old_pr)
        self.assertEqual(github.prs[second["pr"]]["head"]["ref"], second["setup_branch"])
        payload = github.prs[second["pr"]]["body"]
        self.assertIn('"branch_policy_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"',
                      payload)
        self.assertIn('"ruleset_applied_record_id":457', payload)
        self.assertEqual(checkpoint.setup_pr_number, second["pr"])
        self.assertEqual(checkpoint.effective_policy_sha256, new_policy["effective_policy_sha256"])
        self.assertEqual(builder.call_count, 3)
        self.assertEqual(builder.call_args_list[0].kwargs["activation_binding"]["setup_branch"],
                         builder.call_args_list[1].kwargs["activation_binding"]["setup_branch"])
        self.assertNotEqual(builder.call_args_list[1].kwargs["activation_binding"]["setup_branch"],
                            builder.call_args_list[2].kwargs["activation_binding"]["setup_branch"])

    def test_external_reviewer_inventory_is_explicit_and_missing_checks_do_not_create_pr(self):
        github = FakeGitHub()
        profile = _default_profile(REPO)
        profile["activation"] = {"issue_number": ISSUE}
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA):
            profile_path = Path(tmp) / ".agent" / "project.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps(profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            missing = setup_consumer_activation(Path(tmp), github)
        self.assertEqual(missing["status"], "INPUT_REQUIRED")
        self.assertEqual(missing["required_setting_inventory"]["required_checks"], "BLOCKED")
        self.assertEqual(missing["required_setting_inventory"]["repository_ruleset"], "UNSUPPORTED")
        self.assertEqual(github.prs, {})

        profile["branch"]["required_checks"] = [{"name": "ci", "trusted_app_id": APP_ID}]
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation._ensure_setup_branch", return_value=(HEAD_SHA, False)), \
                patch("p_ases.consumer_activation.switch_branch"):
            profile_path = Path(tmp) / ".agent" / "project.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps(profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            configured = setup_consumer_activation(Path(tmp), github)
        self.assertEqual(configured["status"], "SETUP_PENDING")
        inventory = configured["required_setting_inventory"]
        self.assertEqual(inventory["review_mode"], "VERIFIED")
        self.assertEqual(inventory["required_checks"], "VERIFIED")
        self.assertEqual(inventory["repository_ruleset"], "UNSUPPORTED")
        self.assertEqual(inventory["effective_default_branch_policy"], "UNSUPPORTED")

    def test_empty_consumer_creates_issue_proposed_adc_profile_pr_then_admin_merge_activates(self):
        github = FakeGitHub()
        self.assertEqual(parse_adc(_default_activation_adc(REPO, ISSUE), REPO, ISSUE).requirement_ids,
                         ("REQ-01", "REQ-02", "REQ-03"))
        setup_fake(github)
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))
        self.assertFalse(any(row["body"].startswith(RECORD_MARKER) for row in github.comments))
        record, record_id = verify_and_record_activation(github, PR)
        self.assertEqual(record.activation_issue_number, ISSUE)
        self.assertEqual(record.setup_pr_number, PR)
        self.assertEqual(record.activated_at, MERGED_AT)
        self.assertEqual(read_consumer_activation_record(github, REPO, ISSUE), (record, record_id))
        github.main_sha = "d" * 40
        self.assertEqual(read_consumer_activation_record(github, REPO, ISSUE), (record, record_id))

    def test_setup_commits_only_written_profile_and_resumes_after_transient_pr_api_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, base = local_consumer_checkout(Path(temporary))
            github = FakeGitHub()
            github.main_sha = base
            github.setup_root = root
            github.fail_create_pr_once = True
            self.assertEqual(run_git(root, "symbolic-ref", "--short", "HEAD"), "main")
            self.assertTrue(worktree_clean(root))
            self.assertEqual(remote_branch_sha(root, "main"), base)
            self.assertEqual(github.main_sha, base)
            with self.assertRaisesRegex(ConsumerActivationError, "PR creation failed"):
                setup_consumer_activation(root, github)
            self.assertEqual(run_git(root, "symbolic-ref", "--short", "HEAD"), "main")
            self.assertTrue(worktree_clean(root))
            branch_ref = "pases/consumer-activation-71-"
            remote_rows = run_git(root, "ls-remote", "--heads", "origin").splitlines()
            pushed = [row.split() for row in remote_rows if row.split()[1].startswith(f"refs/heads/{branch_ref}")]
            self.assertEqual(len(pushed), 1)
            commit_sha = pushed[0][0]
            self.assertEqual(changed_paths_between(root, base, commit_sha), (".agent/project.json",))
            self.assertEqual(activation_profile_bytes_at_commit(root, commit_sha),
                             (json.dumps({**_default_profile(REPO),
                                          "branch": {**_default_profile(REPO)["branch"],
                                                     "required_checks": [{"name": "ci", "trusted_app_id": APP_ID}]},
                                          "activation": {"issue_number": ISSUE}},
                                         sort_keys=True, indent=2) + "\n").encode())

            result = setup_consumer_activation(root, github)
            self.assertEqual(result["status"], "SETUP_PENDING")
            self.assertTrue(result["reused"])
            self.assertEqual(result["pr"], PR)
            self.assertEqual(github.pr["head"]["sha"], commit_sha)
            self.assertEqual(remote_branch_sha(root, result["setup_branch"]), commit_sha)
            self.assertEqual(remote_branch_sha(root, "main"), base)
            self.assertEqual(run_git(root, "symbolic-ref", "--short", "HEAD"), "main")
            self.assertTrue(worktree_clean(root))

    def test_setup_resumes_remote_only_branch_from_independent_main_only_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root_a, base = local_consumer_checkout(parent)
            bare = parent / "github.com" / "owner" / "consumer.git"
            root_b = clone_main_only(parent, bare)
            self.assertEqual(run_git(root_b, "for-each-ref", "--format=%(refname:short)",
                                     "refs/remotes/origin"), "origin/main")

            github = FakeGitHub()
            github.main_sha = base
            github.setup_root = root_a
            github.fail_create_pr_once = True
            with self.assertRaisesRegex(ConsumerActivationError, "PR creation failed"):
                setup_consumer_activation(root_a, github)
            self.assertTrue(worktree_clean(root_a))

            branch_rows = run_git(root_b, "ls-remote", "--heads", "origin").splitlines()
            setup_rows = [row.split() for row in branch_rows
                          if row.split()[1].startswith("refs/heads/pases/consumer-activation-71-")]
            self.assertEqual(len(setup_rows), 1)
            branch_ref = setup_rows[0][1].removeprefix("refs/heads/")
            self.assertEqual(run_git(root_b, "for-each-ref", "--format=%(refname:short)",
                                     "refs/heads"), "main")
            self.assertEqual(run_git(root_b, "for-each-ref", "--format=%(refname:short)",
                                     "refs/remotes/origin"), "origin/main")
            observed_sha = remote_branch_sha(root_b, branch_ref)
            github.setup_root = root_b
            result = setup_consumer_activation(root_b, github)
            self.assertEqual(result["status"], "SETUP_PENDING")
            self.assertTrue(result["reused"])
            self.assertEqual(github.pr["head"]["sha"], observed_sha)
            self.assertEqual(head_sha40(root_b), base)
            self.assertEqual(run_git(root_b, "symbolic-ref", "--short", "HEAD"), "main")
            self.assertTrue(worktree_clean(root_b))

    def test_remote_branch_fetch_rejects_sha_change_since_ls_remote_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root_a, _base = local_consumer_checkout(parent)
            bare = parent / "github.com" / "owner" / "consumer.git"
            root_b = clone_main_only(parent, bare)
            branch_ref = "pases/fetch-race"
            run_git(root_a, "switch", "--quiet", "--create", branch_ref)
            project = root_a / ".agent" / "project.json"
            project.write_text(project.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            run_git(root_a, "add", "--", ".agent/project.json")
            run_git(root_a, "commit", "--quiet", "-m", "initial setup subject")
            observed_sha = head_sha40(root_a)
            run_git(root_a, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch_ref}")
            self.assertEqual(fetch_remote_branch_exact(root_b, branch_ref, observed_sha), observed_sha)

            run_git(root_a, "commit", "--allow-empty", "--quiet", "-m", "remote branch advanced")
            run_git(root_a, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch_ref}")
            with self.assertRaisesRegex(GitError, "differs from its observed SHA"):
                fetch_remote_branch_exact(root_b, branch_ref, observed_sha)
            self.assertEqual(run_git(root_b, "for-each-ref", "--format=%(refname:short)",
                                     "refs/heads"), "main")

    def test_git_setup_commit_rejects_any_other_staged_modified_or_untracked_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, base = local_consumer_checkout(Path(temporary))
            run_git(root, "switch", "--quiet", "--create", "pases/activation-test", base)
            project = root / ".agent" / "project.json"
            project.write_text(json.dumps({**_default_profile(REPO),
                                          "activation": {"issue_number": ISSUE}}, sort_keys=True, indent=2)
                              + "\n", encoding="utf-8")
            (root / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
            with self.assertRaisesRegex(GitError, "only its intended project.json"):
                commit_and_push_one_path(root, "pases/activation-test", ".agent/project.json", "setup")
            self.assertEqual(run_git(root, "diff", "--cached", "--name-only"), "")
            self.assertEqual(run_git(root, "symbolic-ref", "--short", "HEAD"), "pases/activation-test")

    def test_setup_creates_issue_when_missing_and_duplicate_markers_block(self):
        github = FakeGitHub()
        github.issue_row = None
        setup_fake(github, merge=False)
        self.assertIn(ISSUE_MARKER, github.issue_row["body"])
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))
        self.assertFalse(any(row["body"].startswith(RECORD_MARKER) for row in github.comments))

        duplicate = FakeGitHub()
        duplicate.duplicate_issue = True
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA):
            with self.assertRaisesRegex(ConsumerActivationError, "multiple marked"):
                setup_consumer_activation(Path(tmp), duplicate)
        self.assertEqual(duplicate.comments, [])

    def test_merge_is_required_and_authenticated_verifier_must_match_merger(self):
        github = FakeGitHub()
        setup_fake(github, merge=False)
        with self.assertRaisesRegex(ConsumerActivationError, "merged setup PR"):
            verify_and_record_activation(github, PR)
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))

        github = FakeGitHub()
        setup_fake(github)
        github.authenticated_user = lambda: {"id": 43, "login": "different-admin", "type": "User"}
        with self.assertRaisesRegex(ConsumerActivationError, "authenticated human"):
            verify_and_record_activation(github, PR)
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))
        github.authenticated_user = lambda: copy.deepcopy(USER)
        record, record_id = verify_and_record_activation(github, PR)
        self.assertEqual(read_consumer_activation_record(github, REPO, ISSUE), (record, record_id))

    def test_non_admin_bad_check_and_wrong_app_fail_before_activation_comments(self):
        github = FakeGitHub()
        setup_fake(github)
        github.permission = "write"
        with self.assertRaisesRegex(ConsumerActivationError, "current repository admin"):
            verify_and_record_activation(github, PR)
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))

        github = FakeGitHub()
        setup_fake(github)
        github.checks[0]["conclusion"] = "failure"
        with self.assertRaisesRegex(ConsumerActivationError, "did not pass"):
            verify_and_record_activation(github, PR)

        github = FakeGitHub()
        setup_fake(github)
        failed_rerun = copy.deepcopy(github.checks[0])
        failed_rerun.update({"id": 2, "created_at": "2026-10-14T11:59:03Z",
                             "started_at": "2026-10-14T11:59:04Z",
                             "completed_at": "2026-10-14T11:59:05Z", "conclusion": "failure"})
        github.checks.append(failed_rerun)
        with self.assertRaisesRegex(ConsumerActivationError, "did not pass"):
            verify_and_record_activation(github, PR)

        github = FakeGitHub()
        setup_fake(github)
        github.checks[0]["app"]["id"] += 1
        with self.assertRaisesRegex(ConsumerActivationError, "did not pass"):
            verify_and_record_activation(github, PR)

    def test_check_run_creation_time_uses_the_exact_linked_actions_job(self):
        github = FakeGitHub()
        setup_fake(github)
        check = github.checks[0]
        check.pop("created_at")
        job_created_at = "2026-10-14T11:58:59Z"
        github.workflow_jobs[check["id"]] = {
            "id": check["id"], "run_id": 3001, "run_attempt": 1,
            "name": check["name"], "head_sha": check["head_sha"],
            "check_run_url": f"https://api.github.com/repos/{REPO}/check-runs/{check['id']}",
            "created_at": job_created_at, "started_at": check["started_at"],
            "completed_at": check["completed_at"], "status": check["status"],
            "conclusion": check["conclusion"],
        }

        record, record_id = verify_and_record_activation(github, PR)

        self.assertEqual(record.required_check_runs[0].created_at, job_created_at)
        self.assertGreaterEqual(github.workflow_job_reads, 2)
        self.assertEqual(read_consumer_activation_record(github, REPO, ISSUE), (record, record_id))

    def test_post_merge_success_cannot_rescue_failed_or_pending_check_at_merge(self):
        for merge_run in (
            {"status": "completed", "conclusion": "failure",
             "completed_at": "2026-10-14T11:59:05Z"},
            {"status": "in_progress", "conclusion": None, "completed_at": None},
        ):
            with self.subTest(status=merge_run["status"]):
                github = FakeGitHub()
                setup_fake(github)
                at_merge = copy.deepcopy(github.checks[0])
                at_merge.update({"id": 2, "created_at": "2026-10-14T11:59:03Z",
                                 "started_at": "2026-10-14T11:59:04Z", **merge_run})
                after_merge = copy.deepcopy(github.checks[0])
                after_merge.update({"id": 3, "created_at": "2026-10-14T12:05:00Z",
                                    "started_at": "2026-10-14T12:05:01Z",
                                    "completed_at": "2026-10-14T12:05:02Z"})
                github.checks.extend((at_merge, after_merge))
                github.issue_created_at_by_number[72] = "2026-10-14T12:02:00Z"
                self.assertGreater(github.issue_created_at_by_number[72], MERGED_AT)
                with self.assertRaisesRegex(ConsumerActivationError, "latest Check Run at merge did not pass"):
                    verify_and_record_activation(github, PR)
                self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))
                self.assertIsNone(choose_gate_for_new_issue(
                    github, REPO, 72, "2026-10-14T12:06:00Z", activation_issue_number=ISSUE,
                ))

    def test_check_run_timestamp_ties_use_run_id_for_deterministic_selection(self):
        github = FakeGitHub()
        setup_fake(github)
        tied = copy.deepcopy(github.checks[0])
        tied.update({"id": 2, "completed_at": "2026-10-14T11:59:03Z"})
        github.checks = [tied, github.checks[0]]
        record, _record_id = verify_and_record_activation(github, PR)
        self.assertEqual([item.check_run_id for item in record.required_check_runs], [2])
        self.assertLessEqual(record.required_check_runs[0].completed_at, MERGED_AT)

    def test_partial_approval_retry_is_idempotent(self):
        github = FakeGitHub()
        setup_fake(github)
        github.fail_record_once = True
        with self.assertRaisesRegex(ConsumerActivationError, "publication failed"):
            verify_and_record_activation(github, PR)
        self.assertEqual(sum(row["body"].startswith(APPROVAL_MARKER) for row in github.comments), 1)
        record, _ = verify_and_record_activation(github, PR)
        self.assertEqual(sum(row["body"].startswith(RECORD_MARKER) for row in github.comments), 1)

    def test_issued_activation_pins_check_run_identity_across_later_reruns(self):
        github = FakeGitHub()
        setup_fake(github)
        record, record_id = verify_and_record_activation(github, PR)
        self.assertEqual([item.check_run_id for item in record.required_check_runs], [1])
        self.assertLess(record.required_check_runs[0].completed_at, record.merged_at)
        reads_before = github.check_runs_reads
        rerun = copy.deepcopy(github.checks[0])
        rerun.update({"id": 2, "created_at": "2026-10-14T12:04:00Z",
                      "started_at": "2026-10-14T12:04:01Z",
                      "completed_at": "2026-10-14T12:04:02Z"})
        github.checks.append(rerun)
        self.assertEqual(read_consumer_activation_record(github, REPO, ISSUE), (record, record_id))
        self.assertEqual(github.check_runs_reads, reads_before)
        self.assertEqual(verify_and_record_activation(github, PR), (record, record_id))
        self.assertEqual(github.check_runs_reads, reads_before)

    def test_stale_adc_deletion_and_mid_read_mutation_fail_closed(self):
        github = FakeGitHub()
        setup_fake(github)
        proposed = github.proposed_adc.contract.content.replace(
            b"Every Gate Selection stays bound to the exact Activation record that authorized it.",
            b"Every Gate Selection stays bound to the exact approved Activation record.",
        )
        publish_adc(github, ISSUE, proposed, state="draft", supersede=True)
        with self.assertRaisesRegex(ConsumerActivationError, "stale or superseded"):
            verify_and_record_activation(github, PR)

        github = FakeGitHub()
        setup_fake(github)
        proposal_id = github.proposed_adc.pointer.comment_id
        github.comments = [row for row in github.comments if row["id"] != proposal_id]
        with self.assertRaisesRegex(ConsumerActivationError, "Activation ADC is missing"):
            verify_and_record_activation(github, PR)

        github = FakeGitHub()
        setup_fake(github)
        _record, _record_id = verify_and_record_activation(github, PR)
        github.issue_comment_list_calls = 0
        github.mutate_marker = RECORD_MARKER
        github.mutate_on_list_call = 2
        with self.assertRaisesRegex(ConsumerActivationError, "changed during direct/list/direct"):
            read_consumer_activation_record(github, REPO, ISSUE)

    def test_edited_duplicate_and_wrong_author_history_fail_closed(self):
        github = FakeGitHub()
        setup_fake(github)
        record, comment_id = verify_and_record_activation(github, PR)
        record_row = next(row for row in github.comments if row["id"] == comment_id)
        record_row["updated_at"] = "2026-10-14T12:03:00Z"
        with self.assertRaisesRegex(ConsumerActivationError, "edited"):
            read_consumer_activation_record(github, REPO, ISSUE)

        github = FakeGitHub()
        setup_fake(github)
        _record, _record_id = verify_and_record_activation(github, PR)
        duplicate = copy.deepcopy(next(row for row in github.comments if row["body"].startswith(RECORD_MARKER)))
        duplicate["id"] += 100
        github.comments.append(duplicate)
        with self.assertRaisesRegex(ConsumerActivationError, "history"):
            read_consumer_activation_record(github, REPO, ISSUE)

        github = FakeGitHub()
        setup_fake(github)
        _record, _record_id = verify_and_record_activation(github, PR)
        approval = next(row for row in github.comments if row["body"].startswith(APPROVAL_MARKER))
        approval["user"] = {"id": 777, "login": "other-user", "type": "User"}
        with self.assertRaisesRegex(ConsumerActivationError, "author"):
            read_consumer_activation_record(github, REPO, ISSUE)

    def test_consumer_issue_27_uses_consumer_activation_not_fixed_bootstrap(self):
        github = FakeGitHub()
        setup_fake(github)
        record, _ = verify_and_record_activation(github, PR)
        selected = choose_gate_for_new_issue(
            github, REPO, 27, "2026-10-14T12:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.policy_version, PASES_POLICY)
        self.assertEqual(selected.activation_issue_number, ISSUE)
        self.assertEqual(selected.activation_comment_id, read_consumer_activation_record(github, REPO, ISSUE)[1])
        github.ordinary_created_at = "2026-10-14T12:00:30Z"
        between_merge_and_record = choose_gate_for_new_issue(
            github, REPO, 27, "2026-10-14T12:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertIsNotNone(between_merge_and_record)
        self.assertEqual(between_merge_and_record.activation_comment_id,
                         read_consumer_activation_record(github, REPO, ISSUE)[1])
        github.ordinary_created_at = record.activated_at
        self.assertIsNone(choose_gate_for_new_issue(
            github, REPO, 27, "2026-10-14T12:03:00Z", activation_issue_number=ISSUE,
        ))

    @patch("p_ases.consumer_activation.verify_applied_policy_record", return_value={})
    def test_successor_activation_appends_chain_and_old_selection_keeps_old_record(self, _policy_record_mock):
        github = FakeGitHub()
        setup_fake(github)
        first, first_id = verify_and_record_activation(github, PR)
        selected_before = choose_gate_for_new_issue(
            github, REPO, 28, "2026-10-14T12:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertIsNotNone(selected_before)
        self.assertEqual(selected_before.activation_comment_id, first_id)
        pinned_id, pinned_body = pin_gate_selection(github, selected_before)
        self.assertEqual(read_gate_selection(github, 28), (pinned_id, selected_before, pinned_body))
        github.issue_created_at_by_number[29] = "2026-10-14T12:30:00Z"

        revised = github.proposed_adc.contract.content.replace(
            b"Every Gate Selection stays bound to the exact Activation record that authorized it.",
            b"Every Gate Selection stays bound to the exact successor Activation record that authorized it.",
        )
        publish_adc(github, ISSUE, revised, state="draft", supersede=True, explicitly_approved=False)
        github.comment_time = "2026-10-14T13:01:00Z"
        github.head_sha = "d" * 40
        github.checks.append({"id": 2, "name": "ci", "head_sha": github.head_sha,
                             "created_at": "2026-10-14T12:59:00Z",
                             "started_at": "2026-10-14T12:59:01Z",
                             "completed_at": "2026-10-14T12:59:02Z",
                             "status": "completed", "conclusion": "success", "app": {"id": APP_ID}})
        v2_profile = _default_profile(REPO)
        v2_profile["branch"]["required_checks"] = [{"name": "ci", "trusted_app_id": APP_ID}]
        v2_profile["final_delivery"] = {"review_mode": "solo_owner"}
        v2_profile["activation"] = {"issue_number": ISSUE}
        policy_evidence = {"ruleset_id": 123, "effective_policy_sha256": "c" * 64,
                           "applied_record_id": 456}
        setup_bytes: dict[str, bytes] = {}
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation.remote_branch_exists", return_value=False), \
                patch("p_ases.consumer_activation.branch_exists", return_value=False), \
                patch("p_ases.consumer_activation._ensure_setup_branch",
                      side_effect=lambda _root, _ref, _head, content:
                      (setup_bytes.setdefault("profile", content) and (github.head_sha, False))), \
                patch("p_ases.consumer_activation.switch_branch"), \
                patch("p_ases.consumer_activation.build_ruleset_plan", return_value={
                    "blockers": [], "diff": {"operation": "noop"}, "plan_sha256": "d" * 64,
                    "policy_proof": {"status": "VERIFIED"},
                }), \
                patch("p_ases.consumer_activation.write_ruleset_plan"), \
                patch("p_ases.consumer_activation.read_verified_managed_policy",
                      return_value=policy_evidence):
            profile_path = Path(tmp) / ".agent" / "project.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps(v2_profile, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            result = setup_consumer_activation(Path(tmp), github)
        second_pr = result["pr"]
        self.assertNotEqual(second_pr, PR)
        second_merge = "e" * 40
        second = github.prs[second_pr]
        second.update({"state": "closed", "merged": True, "merged_at": "2026-10-14T13:00:00Z",
                       "merged_by": copy.deepcopy(USER), "merge_commit_sha": second_merge})
        github.profile_by_commit[second_merge] = setup_bytes["profile"]
        github.main_sha = "f" * 40
        with patch("p_ases.consumer_activation.read_verified_managed_policy",
                   return_value=policy_evidence) as policy_reads:
            successor, successor_id = verify_and_record_activation(github, second_pr)
        self.assertEqual(policy_reads.call_count, 2)
        self.assertEqual(successor.predecessor_record_id, first_id)
        self.assertGreater(successor_id, first_id)
        history = read_consumer_activation_record(github, REPO, ISSUE)
        self.assertEqual(history, (successor, successor_id))
        self.assertEqual(read_consumer_activation_history(github, REPO, ISSUE),
                         [(first, first_id), (successor, successor_id)])
        github.issue_created_at_by_number[28] = "2026-10-14T12:02:00Z"
        reselected = choose_gate_for_new_issue(
            github, REPO, 28, "2026-10-14T13:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertEqual(reselected, selected_before)
        self.assertEqual(choose_gate_for_new_issue(
            github, REPO, 28, "2026-10-14T13:03:00Z", activation_issue_number=None,
        ), selected_before)
        self.assertEqual(pin_gate_selection(github, reselected), (pinned_id, pinned_body))
        self.assertEqual(read_gate_selection(github, 28), (pinned_id, selected_before, pinned_body))
        between_successors = choose_gate_for_new_issue(
            github, REPO, 29, "2026-10-14T13:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertEqual(between_successors.activation_comment_id, first_id)
        github.issue_created_at_by_number[30] = "2026-10-14T13:02:00Z"
        later_selection = choose_gate_for_new_issue(
            github, REPO, 30, "2026-10-14T13:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertEqual(later_selection.activation_comment_id, successor_id)

        successor_comment = next(row for row in github.comments if row["id"] == successor_id)
        successor_comment["body"] += "\ncorrupt successor payload"
        successor_comment["id"] = "invalid successor comment ID"
        self.assertEqual(read_consumer_activation_history(
            github, REPO, ISSUE, through_record_id=first_id,
        ), [(first, first_id)])
        self.assertEqual(choose_gate_for_new_issue(
            github, REPO, 28, "2026-10-14T13:04:00Z", activation_issue_number=ISSUE,
        ), selected_before)
        with self.assertRaisesRegex(ConsumerActivationError, "canonical|history|schema"):
            read_consumer_activation_history(github, REPO, ISSUE)

    def test_v2_activation_uses_record_comment_created_at_as_effective_time(self):
        v1 = ConsumerActivationRecord(
            repository=REPO, activation_issue_number=ISSUE, proposed_adc_comment_id=100,
            proposed_adc_sha256="a" * 64, proposed_adc_state="approved", adc_comment_id=100,
            adc_sha256="a" * 64, activation_profile_sha256="b" * 64, setup_pr_number=PR,
            setup_pr_id=PR + 1000, merge_commit_sha40=MERGE_SHA, merged_at=MERGED_AT,
            merger_id=USER["id"], merger_login=USER["login"], merger_type="User",
            approval_comment_id=101, predecessor_record_id=None,
            required_check_runs=(sample_check_evidence(),),
        )
        v2 = ConsumerActivationRecord(
            **{**v1.__dict__, "record_created_at": "2026-10-14T12:05:00Z", "schema_version": 2,
               "review_mode": "solo_owner", "ruleset_id": 123, "branch_policy_sha256": "c" * 64,
               "ruleset_applied_record_id": 456,
               "setup_branch": "pases/consumer-activation-71-aabb-initial-v2-bcccccccc"},
        )
        self.assertEqual(v1.activated_at, MERGED_AT)
        self.assertEqual(v2.activated_at, "2026-10-14T12:05:00Z")
        self.assertEqual(v2.payload()["schema"], "PASES_CONSUMER_ACTIVATION_V2")
        self.assertEqual(v2.payload()["ruleset_applied_record_id"], 456)


def sample_check_evidence():
    return RequiredCheckEvidence(
        1, "ci", APP_ID, HEAD_SHA, "2026-10-14T11:59:00Z", "2026-10-14T11:59:01Z",
        "2026-10-14T11:59:02Z", "completed", "success",
    )


if __name__ == "__main__":
    unittest.main()
