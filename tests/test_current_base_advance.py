from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.work import bind_work
from p_ases.git import commit_parents_sha40, head_sha40, run_git
from p_ases.work import WorkError, ensure_pull_request, read_pr_binding_history


ISSUE = 30
ACTIVATION_ISSUE = 57
REPOSITORY = "owner/repo"
BODY = "Review implementation.\n\nCloses #30\n"
OLD_PROFILE = b'{"activation":{"issue_number":57},"version":1}\n'
NEW_PROFILE = b'{"activation":{"issue_number":57},"version":2}\n'


class FakeGitHub:
    repo = REPOSITORY

    def __init__(self, root: Path, base_sha: str):
        self.root = root
        self.base_sha = base_sha
        self.target = None
        self.setup = None
        self.record = None

    def pull_requests_for_refs(self, *, base_ref, head_ref):
        if self.target is None:
            return []
        return [self.target]

    def create_pull_request(self, *, title, body, head_ref, base_ref):
        self.target = self._target(body, head_ref, base_ref, self.base_sha)
        return {"number": self.target["number"]}

    def pull_request(self, number):
        if self.target is not None and number == self.target["number"]:
            self.target["head"]["sha"] = head_sha40(self.root)
            self.target["base"]["sha"] = self.base_sha
            return self.target
        if self.setup is not None and number == self.setup["number"]:
            return self.setup
        raise RuntimeError("unexpected PR")

    def _target(self, body, head_ref, base_ref, base_sha):
        repo = {"full_name": REPOSITORY}
        return {
            "id": 7300, "number": 73, "state": "open", "draft": False, "body": body,
            "base": {"ref": base_ref, "sha": base_sha, "repo": repo},
            "head": {"ref": head_ref, "sha": head_sha40(self.root), "repo": repo},
        }

    def update_target(self, *, base_sha, head_ref):
        self.base_sha = base_sha
        self.target = self._target(BODY, head_ref, "main", base_sha)

    def pull_request_files(self, number):
        if self.setup is None or number != self.setup["number"]:
            raise RuntimeError("unexpected files request")
        return [{"filename": ".agent/project.json"}]

    def commit_details(self, sha):
        return {"sha": sha, "parents": [{"sha": parent} for parent in commit_parents_sha40(self.root, sha)]}

    def content_at_ref(self, path, ref):
        result = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=self.root,
                                check=True, stdout=subprocess.PIPE)
        return result.stdout

    def branch(self, branch):
        if branch != "main":
            raise RuntimeError("unexpected branch")
        return {"commit": {"sha": self.base_sha}}

    def repository_metadata(self):
        return {"default_branch": "main"}


class CurrentBaseAdvanceTests(unittest.TestCase):
    def _setup_repo(self, temporary: str):
        root = Path(temporary)
        repo, remote = root / "repo", root / "remote.git"
        repo.mkdir()
        run_git(repo, "init", "--quiet", "--initial-branch=main")
        run_git(repo, "config", "user.email", "test@example.invalid")
        run_git(repo, "config", "user.name", "P-ASES tests")
        (repo / ".gitignore").write_text(".p_ases/\n", encoding="utf-8")
        (repo / ".agent").mkdir()
        (repo / ".agent" / "project.json").write_bytes(OLD_PROFILE)
        (repo / "source.txt").write_text("baseline\n", encoding="utf-8")
        run_git(repo, "add", ".gitignore", ".agent/project.json", "source.txt")
        run_git(repo, "commit", "--quiet", "-m", "baseline")
        frozen = head_sha40(repo)
        run_git(root, "init", "--quiet", "--bare", str(remote))
        run_git(repo, "remote", "add", "origin", str(remote))
        run_git(repo, "push", "--quiet", "--set-upstream", "origin", "main")
        run_git(repo, "switch", "--quiet", "--create", "pases/work")
        (repo / "change.txt").write_text("implementation\n", encoding="utf-8")
        run_git(repo, "add", "change.txt")
        run_git(repo, "commit", "--quiet", "-m", "implementation")
        run_git(repo, "push", "--quiet", "--set-upstream", "origin", "pases/work")
        binding = bind_work(repo, repository=REPOSITORY, issue_number=ISSUE, adc_comment_id=123,
                            adc_sha256="a" * 64, base_ref="main", branch_ref="pases/work",
                            expected_base_sha40=frozen).binding
        github = FakeGitHub(repo, frozen)
        with patch("p_ases.work.load_profile", return_value=SimpleNamespace(
                activation_issue_number=ACTIVATION_ISSUE)):
            first = ensure_pull_request(repo, github, repository=REPOSITORY, issue_number=ISSUE,
                                        binding=binding, branch_ref="pases/work", base_ref="main",
                                        title="Issue #30 work", body=BODY)
        old_path, old_binding = read_pr_binding_history(repo, ISSUE)[0]
        old_bytes = old_path.read_bytes()
        return repo, frozen, binding, github, first, old_binding, old_path, old_bytes

    def _merge_activation_profile(self, repo: Path, frozen: str, github: FakeGitHub,
                                  *, change_target_profile: bool = False,
                                  unknown_main_change: bool = False):
        run_git(repo, "switch", "--quiet", "main")
        setup_branch = "pases/consumer-activation-57-baaaaaaaa"
        run_git(repo, "switch", "--quiet", "--create", setup_branch)
        (repo / ".agent" / "project.json").write_bytes(NEW_PROFILE)
        run_git(repo, "add", ".agent/project.json")
        run_git(repo, "commit", "--quiet", "-m", "Activation project profile")
        setup_head = head_sha40(repo)
        run_git(repo, "push", "--quiet", "--set-upstream", "origin", setup_branch)
        run_git(repo, "switch", "--quiet", "main")
        run_git(repo, "merge", "--quiet", "--no-ff", setup_branch, "-m", "Merge Activation setup")
        current_base = head_sha40(repo)
        if unknown_main_change:
            (repo / "unexpected.txt").write_text("unknown\n", encoding="utf-8")
            run_git(repo, "add", "unexpected.txt")
            run_git(repo, "commit", "--quiet", "-m", "unrelated main change")
            current_base = head_sha40(repo)
        run_git(repo, "push", "--quiet", "origin", "main")
        run_git(repo, "switch", "--quiet", "pases/work")
        run_git(repo, "merge", "--quiet", "--no-ff", "main", "-m", "Integrate Activation profile")
        if change_target_profile:
            (repo / ".agent" / "project.json").write_bytes(OLD_PROFILE)
            run_git(repo, "add", ".agent/project.json")
            run_git(repo, "commit", "--quiet", "-m", "change profile after activation")
        transition_head = head_sha40(repo)
        run_git(repo, "push", "--quiet", "origin", "pases/work")
        github.update_target(base_sha=current_base, head_ref="pases/work")
        repo_obj = {"full_name": REPOSITORY}
        github.setup = {
            "id": 7400, "number": 74, "state": "closed", "merged": True,
            "merge_commit_sha": current_base if not unknown_main_change else head_sha40(repo),
            "merged_at": "2026-10-17T12:00:00Z",
            "base": {"ref": "main", "repo": repo_obj},
            "head": {"ref": setup_branch, "sha": setup_head, "repo": repo_obj},
        }
        record = SimpleNamespace(
            repository=REPOSITORY, activation_issue_number=ACTIVATION_ISSUE, schema_version=2,
            setup_pr_number=74, setup_pr_id=7400, setup_branch=setup_branch,
            merge_commit_sha40=current_base if not unknown_main_change else frozen,
            merged_at="2026-10-17T12:00:00Z",
            activation_profile_sha256=hashlib.sha256(NEW_PROFILE).hexdigest(),
            sha256="d" * 64,
        )
        github.record = record
        return current_base, setup_head, transition_head

    def _activation_reader(self, github):
        return patch("p_ases.current_base.read_consumer_activation_record",
                     return_value=(github.record, 5757))

    def test_activation_setup_merge_appends_v2_binding_and_preserves_v1_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, frozen, binding, github, _first, old, old_path, old_bytes = self._setup_repo(temporary)
            current_base, _setup_head, transition_head = self._merge_activation_profile(repo, frozen, github)
            with self._activation_reader(github), patch("p_ases.work.load_profile", return_value=SimpleNamespace(
                    activation_issue_number=ACTIVATION_ISSUE)):
                result = ensure_pull_request(repo, github, repository=REPOSITORY, issue_number=ISSUE,
                                             binding=binding, branch_ref="pases/work", base_ref="main",
                                             title="Issue #30 work", body=BODY)
            rows = read_pr_binding_history(repo, ISSUE)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][1], old)
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertEqual(rows[1][1].base_sha40, frozen)
            self.assertEqual(rows[1][1].current_base_sha40, current_base)
            self.assertEqual(rows[1][1].pr_head_sha40, transition_head)
            self.assertEqual(result.binding.current_base_advance_sha256,
                             rows[1][1].current_base_advance_sha256)

    def test_unknown_main_drift_is_rejected_without_writing_transition_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, frozen, binding, github, _first, _old, _path, _bytes = self._setup_repo(temporary)
            self._merge_activation_profile(repo, frozen, github, unknown_main_change=True)
            with self._activation_reader(github), patch("p_ases.work.load_profile", return_value=SimpleNamespace(
                    activation_issue_number=ACTIVATION_ISSUE)):
                with self.assertRaisesRegex(WorkError, "not a verified Activation setup transition"):
                    ensure_pull_request(repo, github, repository=REPOSITORY, issue_number=ISSUE,
                                        binding=binding, branch_ref="pases/work", base_ref="main",
                                        title="Issue #30 work", body=BODY)
            self.assertFalse((repo / ".p_ases/state/30/current-base-advance.json").exists())

    def test_profile_mismatch_and_wrong_activation_merge_sha_are_rejected(self):
        for failure in ("target_profile", "merge_sha", "setup_pr_id", "target_pr_number"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                repo, frozen, binding, github, _first, _old, _path, _bytes = self._setup_repo(temporary)
                self._merge_activation_profile(repo, frozen, github,
                                               change_target_profile=failure == "target_profile")
                if failure == "merge_sha":
                    github.record = SimpleNamespace(**{**vars(github.record), "merge_commit_sha40": frozen})
                elif failure == "setup_pr_id":
                    github.record = SimpleNamespace(**{**vars(github.record), "setup_pr_id": 9999})
                elif failure == "target_pr_number":
                    github.target["number"] = 74
                with self._activation_reader(github), patch("p_ases.work.load_profile", return_value=SimpleNamespace(
                        activation_issue_number=ACTIVATION_ISSUE)):
                    with self.assertRaises(WorkError):
                        ensure_pull_request(repo, github, repository=REPOSITORY, issue_number=ISSUE,
                                            binding=binding, branch_ref="pases/work", base_ref="main",
                                            title="Issue #30 work", body=BODY)
                self.assertEqual(read_pr_binding_history(repo, ISSUE)[0][1].current_base_sha40, None)
                self.assertFalse((repo / ".p_ases/state/30/current-base-advance.json").exists())


if __name__ == "__main__":
    unittest.main()
