from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.execution import binding_digest
from p_ases.git import head_sha40, run_git
from p_ases.adc import ADCError
from p_ases.checkpoint import PRBinding, write_pr_binding
from p_ases.github import GitHubError
from p_ases.execution import write_binding
from p_ases.work import (WorkError, bind_work, ensure_pull_request, execution_binding_path,
                         _pr_binding_version_path,
                         closing_issue_references, parse_issue_association, read_pr_binding_history)


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

    def _pull(self, *, body, head_ref, base_ref, number=73, draft=False, state="open", issue_close=30):
        repository = {"full_name": self.repo}
        return {
            "number": number, "state": state, "draft": draft, "body": body,
            "base": {"ref": base_ref, "sha": self.base_sha, "repo": repository},
            "head": {"ref": head_ref, "sha": head_sha40(self.root), "repo": repository},
            "closing_issue": issue_close,
        }


class PREnsureTests(unittest.TestCase):
    def test_issue_association_parser_keeps_auto_close_default_and_explicit_deferred_mode(self):
        self.assertEqual(parse_issue_association("Summary\n\nCloses #41\n", 41), "auto_close")
        self.assertEqual(parse_issue_association("Summary\n\nRefs #63\n", 63), "deferred_close")
        for body, number in (
            ("Closes #41\n\nRefs #41\n", 41),
            ("Closes #41\nCloses #42\n", 41),
            ("Refs #63\nRefs #64\n", 63),
            ("Refs #64\n", 63),
            ("Fixes #41\n", 41),
        ):
            with self.subTest(body=body), self.assertRaises(WorkError):
                parse_issue_association(body, number)

    def test_github_closing_keyword_parser_handles_colons_and_repository_qualified_refs(self):
        for keyword in ("close", "closes", "closed", "fix", "fixes", "fixed",
                        "resolve", "resolves", "resolved"):
            text = f"{keyword.upper()}: #63"
            with self.subTest(text=text):
                self.assertEqual(closing_issue_references(text), (63,))
                self.assertEqual(closing_issue_references(text, "puchinya/ai-agent-workflow"), (63,))
        for text in ("Resolves puchinya/ai-agent-workflow#63",
                     "FIXED: PUCHINYA/AI-AGENT-WORKFLOW#63"):
            with self.subTest(text=text):
                self.assertEqual(closing_issue_references(text), (63,))
                self.assertEqual(closing_issue_references(text, "puchinya/ai-agent-workflow"), (63,))
        self.assertEqual(
            closing_issue_references("Resolves another-owner/another-repo#63", "puchinya/ai-agent-workflow"),
            (),
        )
        self.assertEqual(
            closing_issue_references("Closes puchinya/ai-agent-workflow#63", "PUCHINYA/AI-AGENT-WORKFLOW"),
            (63,),
        )
        with self.assertRaises(WorkError):
            closing_issue_references("Closes puchinya/ai-agent-workflow#63", "not-a-repository")

    def test_issue_63_pr_ensure_requires_refs_and_preserves_default_close_for_other_issues(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, base, binding = self._bound_repo(root)
            github = FakeGitHub(repo, base)
            issue_63_binding = replace(binding, issue_number=63)
            github.pull = github._pull(body="Review implementation.\n\nRefs #63\n",
                                       head_ref="pases/work", base_ref="main", number=64)
            with self.assertRaisesRegex(WorkError, "requires the standalone Refs #63"):
                ensure_pull_request(repo, github, repository="owner/repo", issue_number=63,
                                    binding=issue_63_binding, branch_ref="pases/work", base_ref="main",
                                    title="Issue #63 work", body="Closes #63\n")
            result = ensure_pull_request(repo, github, repository="owner/repo", issue_number=63,
                                         binding=issue_63_binding, branch_ref="pases/work", base_ref="main",
                                         title="Issue #63 work", body="Review implementation.\n\nRefs #63\n")
            self.assertEqual(result.pull_request["body"], "Review implementation.\n\nRefs #63\n")

    def test_issue_63_never_creates_or_selects_a_pr_other_than_existing_64(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, base, binding = self._bound_repo(root)
            github = FakeGitHub(repo, base)
            issue_63_binding = replace(binding, issue_number=63)
            with self.assertRaisesRegex(WorkError, "reuse existing PR #64"):
                ensure_pull_request(repo, github, repository="owner/repo", issue_number=63,
                                    binding=issue_63_binding, branch_ref="pases/work", base_ref="main",
                                    title="Issue #63 work", body="Review implementation.\n\nRefs #63\n")
            self.assertEqual(github.create_count, 0)
            github.pull = github._pull(body="Review implementation.\n\nRefs #63\n",
                                       head_ref="pases/work", base_ref="main", number=73)
            with self.assertRaisesRegex(WorkError, "existing PR #64"):
                ensure_pull_request(repo, github, repository="owner/repo", issue_number=63,
                                    binding=issue_63_binding, branch_ref="pases/work", base_ref="main",
                                    title="Issue #63 work", body="Review implementation.\n\nRefs #63\n")
            self.assertEqual(github.create_count, 0)

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

    def test_new_pr_head_creates_a_new_immutable_binding_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, base, binding = self._bound_repo(root)
            github = FakeGitHub(repo, base)
            first = ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                        binding=binding, branch_ref="pases/work", base_ref="main",
                                        title="Issue #30 work", body=BODY)
            history = read_pr_binding_history(repo, 30)
            self.assertEqual(len(history), 1)
            first_path, first_binding = history[0]
            first_bytes = first_path.read_bytes()

            (repo / "follow-up.txt").write_text("follow-up fix\n", encoding="utf-8")
            run_git(repo, "add", "follow-up.txt")
            run_git(repo, "commit", "--quiet", "-m", "follow-up fix")
            run_git(repo, "push", "--quiet", "origin", "pases/work")
            github.pull = github._pull(body=BODY, head_ref="pases/work", base_ref="main")

            updated = ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                          binding=binding, branch_ref="pases/work", base_ref="main",
                                          title="Issue #30 work", body=BODY)
            history = read_pr_binding_history(repo, 30)
            self.assertEqual([item[1].pr_head_sha40 for item in history],
                             [first_binding.pr_head_sha40, head_sha40(repo)])
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertNotEqual(updated.binding, first.binding)
            self.assertEqual(history[1][0].name, "pr-binding-000002.json")

            retry = ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                        binding=binding, branch_ref="pases/work", base_ref="main",
                                        title="Issue #30 work", body=BODY)
            self.assertEqual(retry.binding, updated.binding)
            self.assertEqual(retry.checkpoint_sha256, updated.checkpoint_sha256)

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

    def test_approved_adc_successor_appends_same_pr_generation_and_preserves_v1_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, base, binding = self._bound_repo(root)
            github = FakeGitHub(repo, base)
            first = ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                        binding=binding, branch_ref="pases/work", base_ref="main",
                                        title="Issue #30 work", body=BODY)
            first_path = read_pr_binding_history(repo, 30)[0][0]
            first_bytes = first_path.read_bytes()

            successor = replace(binding, adc_comment_id=124, adc_sha256="b" * 64)
            write_binding(execution_binding_path(repo, 30), successor)
            (repo / "successor.txt").write_text("same PR, new approved ADC\n", encoding="utf-8")
            run_git(repo, "add", "successor.txt")
            run_git(repo, "commit", "--quiet", "-m", "continue under successor ADC")
            run_git(repo, "push", "--quiet", "origin", "pases/work")
            github.pull = github._pull(body=BODY, head_ref="pases/work", base_ref="main")
            verified_chain = (
                SimpleNamespace(pointer=SimpleNamespace(comment_id=123, sha256="a" * 64)),
                SimpleNamespace(pointer=SimpleNamespace(comment_id=124, sha256="b" * 64)),
            )
            with patch("p_ases.work.verify_adc_forward_generations", return_value=verified_chain) as verify:
                updated = ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                              binding=successor, branch_ref="pases/work", base_ref="main",
                                              title="Issue #30 work", body=BODY)
                rows = read_pr_binding_history(repo, 30, github=github)
            self.assertEqual(updated.pull_request["number"], first.pull_request["number"])
            self.assertEqual([row[1].adc_comment_id for row in rows], [123, 124])
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertEqual(rows[1][0].name, "pr-binding-000002.json")
            self.assertGreaterEqual(verify.call_count, 2)
            self.assertIn(False, [call.kwargs.get("allow_historical_target", False)
                                  for call in verify.call_args_list])
            self.assertIn(True, [call.kwargs.get("allow_historical_target", False)
                                 for call in verify.call_args_list])

    def test_pr_binding_history_accepts_multiple_historical_adc_edges_in_current_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, base, _binding = self._bound_repo(root)
            current_head = head_sha40(repo)
            state = repo / ".p_ases" / "state" / "63"
            state.mkdir(parents=True)
            first = PRBinding(
                "owner/repo", 63, 123, "a" * 64, base, "pases/work", 73, current_head,
            ).validate()
            second = replace(first, adc_comment_id=124, adc_sha256="b" * 64).validate()
            third = replace(second, adc_comment_id=125, adc_sha256="c" * 64).validate()
            for version, binding in enumerate((first, second, third), start=1):
                write_pr_binding(_pr_binding_version_path(repo, 63, version), binding)

            pointers = {
                123: "a" * 64,
                124: "b" * 64,
                125: "c" * 64,
            }

            def verify_range(_github, _issue, *, prior_comment_id, prior_sha256,
                             current_comment_id, current_sha256, allow_historical_target=False):
                self.assertTrue(allow_historical_target)
                self.assertEqual(pointers[prior_comment_id], prior_sha256)
                self.assertEqual(pointers[current_comment_id], current_sha256)
                ids = list(pointers)
                selected = ids[ids.index(prior_comment_id):ids.index(current_comment_id) + 1]
                return tuple(SimpleNamespace(pointer=SimpleNamespace(
                    comment_id=comment_id, sha256=pointers[comment_id],
                )) for comment_id in selected)

            with patch("p_ases.work.verify_adc_forward_generations", side_effect=verify_range) as verify:
                rows = read_pr_binding_history(repo, 63, github=object())

            self.assertEqual([row[1].adc_comment_id for row in rows], [123, 124, 125])
            self.assertEqual(verify.call_count, 2)

    def test_pr_binding_adc_gap_or_backward_generation_blocks_append(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, base, binding = self._bound_repo(root)
            github = FakeGitHub(repo, base)
            ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                binding=binding, branch_ref="pases/work", base_ref="main",
                                title="Issue #30 work", body=BODY)
            successor = replace(binding, adc_comment_id=124, adc_sha256="b" * 64)
            write_binding(execution_binding_path(repo, 30), successor)
            before = read_pr_binding_history(repo, 30)[0][0].read_bytes()
            with patch("p_ases.work.verify_adc_forward_generations",
                       side_effect=ADCError("journal gap")):
                with self.assertRaisesRegex(WorkError, "complete approved forward generation"):
                    ensure_pull_request(repo, github, repository="owner/repo", issue_number=30,
                                        binding=successor, branch_ref="pases/work", base_ref="main",
                                        title="Issue #30 work", body=BODY)
            self.assertEqual(read_pr_binding_history(repo, 30)[0][0].read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
