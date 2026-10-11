from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.execution import binding_digest
from p_ases.git import head_sha40, run_git
from p_ases.github import GitHubError
from p_ases.work import WorkError, bind_work, ensure_pull_request


BODY = "Review implementation and evidence.\n\nCloses #30\n"


class FakeGitHub:
    repo = "owner/repo"

    def __init__(self, root: Path, base_sha: str):
        self.root, self.base_sha = root, base_sha
        self.pull = None
        self.create_count = 0
        self.lose_create_response = False

    def pull_requests_for_refs(self, *, base_ref, head_ref):
        if self.pull is None:
            return []
        return [self.pull]

    def create_pull_request(self, *, title, body, head_ref, base_ref):
        self.create_count += 1
        self.pull = self._pull(body=body, head_ref=head_ref, base_ref=base_ref)
        if self.lose_create_response:
            raise GitHubError("simulated POST response timeout")
        return {"number": self.pull["number"]}

    def pull_request(self, number):
        if self.pull is None or self.pull["number"] != number:
            raise GitHubError("PR not found")
        return self.pull

    def _pull(self, *, body, head_ref, base_ref, draft=False, state="open", issue_close=30):
        repository = {"full_name": self.repo}
        return {
            "number": 73, "state": state, "draft": draft, "body": body,
            "base": {"ref": base_ref, "sha": self.base_sha, "repo": repository},
            "head": {"ref": head_ref, "sha": head_sha40(self.root), "repo": repository},
            "closing_issue": issue_close,
        }


class PREnsureTests(unittest.TestCase):
    def _bound_repo(self, root: Path):
        repo, bare = root / "repo", root / "remote.git"
        repo.mkdir()
        run_git(repo, "init", "--quiet", "--initial-branch=main")
        run_git(repo, "config", "user.email", "test@example.invalid")
        run_git(repo, "config", "user.name", "P-ASES tests")
        (repo / ".gitignore").write_text(".p_ases/\n", encoding="utf-8")
        (repo / "source.txt").write_text("baseline\n", encoding="utf-8")
        run_git(repo, "add", ".gitignore", "source.txt")
        run_git(repo, "commit", "--quiet", "-m", "baseline")
        base = head_sha40(repo)
        run_git(root, "init", "--quiet", "--bare", str(bare))
        run_git(repo, "remote", "add", "origin", str(bare))
        run_git(repo, "push", "--quiet", "--set-upstream", "origin", "main")
        run_git(repo, "switch", "--quiet", "--create", "pases/work")
        (repo / "change.txt").write_text("implementation\n", encoding="utf-8")
        run_git(repo, "add", "change.txt")
        run_git(repo, "commit", "--quiet", "-m", "implementation")
        run_git(repo, "push", "--quiet", "--set-upstream", "origin", "pases/work")
        binding = bind_work(repo, repository="owner/repo", issue_number=30, adc_comment_id=123,
                            adc_sha256="a" * 64, base_ref="main", branch_ref="pases/work",
                            expected_base_sha40=base)
        return repo, base, binding.binding

    def test_lost_create_response_recovers_exact_pr_and_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, base, binding = self._bound_repo(root)
            github = FakeGitHub(repo, base)
            github.lose_create_response = True
            result = ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                         binding=binding, branch_ref="pases/work", base_ref="main",
                                         title="Issue #30 work", body=BODY)
            self.assertTrue(result.reused)
            self.assertEqual(github.create_count, 1)
            self.assertEqual(result.binding.pr_head_sha40, head_sha40(repo))
            retry = ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                        binding=binding, branch_ref="pases/work", base_ref="main",
                                        title="Issue #30 work", body=BODY)
            self.assertTrue(retry.reused)
            self.assertEqual(github.create_count, 1)
            self.assertEqual(retry.binding, result.binding)
            self.assertEqual(retry.checkpoint_sha256, result.checkpoint_sha256)

    def test_draft_closed_mismatched_and_duplicate_candidates_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, base, binding = self._bound_repo(root)
            github = FakeGitHub(repo, base)
            github.pull = github._pull(body=BODY, head_ref="pases/work", base_ref="main", draft=True)
            with self.assertRaises(WorkError):
                ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                    binding=binding, branch_ref="pases/work", base_ref="main",
                                    title="Issue work", body=BODY)
            github.pull = None
            github.create_count = 0
            with self.assertRaises(WorkError):
                ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                    binding=binding, branch_ref="pases/work", base_ref="main",
                                    title="Issue work", body="Closes #26\n\nCloses #30\n")
            github.pull = github._pull(body=BODY, head_ref="wrong/branch", base_ref="main")
            with self.assertRaises(WorkError):
                ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                    binding=binding, branch_ref="pases/work", base_ref="main",
                                    title="Issue work", body=BODY)
            github.pull = None

            def duplicate(*, base_ref, head_ref):
                return [github._pull(body=BODY, head_ref=head_ref, base_ref=base_ref),
                        dict(github._pull(body=BODY, head_ref=head_ref, base_ref=base_ref), number=74)]
            github.pull_requests_for_refs = duplicate
            with self.assertRaises(WorkError):
                ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                    binding=binding, branch_ref="pases/work", base_ref="main",
                                    title="Issue work", body=BODY)
            self.assertEqual(github.create_count, 0)


if __name__ == "__main__":
    unittest.main()
