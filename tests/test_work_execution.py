from __future__ import annotations

import subprocess
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.checkpoint import (
    PRBinding, WorkCheckpoint, checkpoint_path, read_checkpoint, read_pr_binding,
    write_checkpoint, write_pr_binding,
)
from p_ases.execution import ExecutionBinding, binding_digest, read_binding, read_binding_history
from p_ases.git import head_sha40, run_git
from p_ases import work as work_module
from p_ases.work import (
    WorkError, bind_work, ensure_branch, ensure_epoch_pull_request, ensure_pull_request,
    latest_checkpoint, recover_work,
)


class WorkExecutionTests(unittest.TestCase):
    def _repo(self, root: Path) -> tuple[Path, Path, str]:
        work = root / "work"
        bare = root / "remote.git"
        work.mkdir()
        run_git(work, "init", "--quiet", "--initial-branch=main")
        run_git(work, "config", "user.email", "test@example.invalid")
        run_git(work, "config", "user.name", "P-ASES tests")
        (work / ".gitignore").write_text(".p_ases/\n", encoding="utf-8")
        (work / "README.md").write_text("baseline\n", encoding="utf-8")
        run_git(work, "add", ".gitignore", "README.md")
        run_git(work, "commit", "--quiet", "-m", "baseline")
        base = head_sha40(work)
        run_git(root, "init", "--quiet", "--bare", str(bare))
        run_git(work, "remote", "add", "origin", str(bare))
        run_git(work, "push", "--quiet", "--set-upstream", "origin", "main")
        run_git(work, "switch", "--quiet", "--create", "pases/work")
        return work, bare, base

    def test_bind_and_recover_preserve_the_frozen_base(self):
        with tempfile.TemporaryDirectory() as temporary:
            work, _bare, base = self._repo(Path(temporary))
            result = bind_work(
                work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                adc_sha256="a" * 64, base_ref="main", branch_ref="pases/work",
                expected_base_sha40=base,
            )
            self.assertEqual(result.status, "BOUND")
            self.assertEqual(result.binding.base_sha, base)
            self.assertEqual(result.binding.initial_head_sha, base)
            self.assertEqual(result.context.execution_binding_sha256, binding_digest(result.binding))
            resumed = recover_work(
                work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                adc_sha256="a" * 64, expected_branch_ref="pases/work",
            )
            self.assertEqual(resumed.status, "RECOVERED")
            self.assertEqual(resumed.binding.base_sha, base)
            self.assertEqual(read_binding(work / ".p_ases/state/30/execution-binding.json"), result.binding)
            self.assertEqual(read_checkpoint(resumed.checkpoint_path).sha256, resumed.checkpoint_sha256)

    def test_recover_does_not_synthesize_a_missing_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            work, _bare, _base = self._repo(Path(temporary))
            binding_path = work / ".p_ases/state/30/execution-binding.json"
            with self.assertRaisesRegex(WorkError, "frozen ExecutionBinding cannot be recovered"):
                recover_work(
                    work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                    adc_sha256="a" * 64, expected_branch_ref="pases/work",
                )
            self.assertFalse(binding_path.exists())

    def test_issue71_generic_bind_and_recover_cannot_create_a_v1_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            work, _bare, base = self._repo(Path(temporary))
            binding_path = work / ".p_ases/state/71/execution-binding.json"
            with self.assertRaisesRegex(WorkError, "active epoch-3 identity"):
                bind_work(
                    work, repository="puchinya/ai-agent-workflow", issue_number=71,
                    adc_comment_id=6881591677,
                    adc_sha256="3c6b3ac28270357b57047dc5da0a2c1fbdbada269d55225ea33a656cd3076e17",
                    base_ref="main", branch_ref="pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3",
                )
            with self.assertRaisesRegex(WorkError, "active epoch-3 identity"):
                recover_work(
                    work, repository="puchinya/ai-agent-workflow", issue_number=71,
                    adc_comment_id=6881591677,
                    adc_sha256="3c6b3ac28270357b57047dc5da0a2c1fbdbada269d55225ea33a656cd3076e17",
                    expected_branch_ref="pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3",
                )
            ordinary = ExecutionBinding(
                repository="puchinya/ai-agent-workflow", issue_number=71,
                adc_comment_id=6881591677,
                adc_sha256="3c6b3ac28270357b57047dc5da0a2c1fbdbada269d55225ea33a656cd3076e17",
                base_ref="main", base_sha=base,
                work_directory=str(work.resolve()),
                branch_ref="pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3", initial_head_sha=base,
            ).validate()
            epoch_file = work / ".p_ases" / "state" / "71" / "execution-epoch.json"
            epoch_file.parent.mkdir(parents=True, exist_ok=True)
            epoch_file.write_text("{}")
            with self.assertRaisesRegex(WorkError, "existing adopted or epoch execution identity"):
                ensure_pull_request(
                    work, None, repository="puchinya/ai-agent-workflow", issue_number=71,
                    binding=ordinary, branch_ref=ordinary.branch_ref, base_ref="main",
                    title="Issue #71", body="Closes #71",
                )
            self.assertFalse(binding_path.exists())

    def _issue71_epoch_pr_fixture(self, root: Path, *, malformed_checkpoint: bool = False,
                                  unbound_checkpoint_digest: bool = False,
                                  checkpoint_stage: str = "pr", initial_no_history: bool = False,
                                  checkpoint_clean: bool = True, checkpoint_epoch_mismatch: bool = False,
                                  missing_checkpoint_artifact: bool = False):
        directory = root / ".p_ases" / "state" / "71"
        directory.mkdir(parents=True)
        branch = "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3"
        base = "b" * 40
        head = "c" * 40
        epoch_sha = "d" * 64
        old_adc_sha = "4eb60c4a1a7c3f161f1fbaaf64fa2f174399d01c06637b68f21a5f32b1bcfd84"
        old_binding = None
        prior_checkpoint = None
        prior_checkpoint_path = checkpoint_path(root, 71, 1)
        if not initial_no_history:
            old_binding = PRBinding(
                "puchinya/ai-agent-workflow", 71, 6934055740, old_adc_sha,
                base, branch, 75, head, execution_epoch_sha256=epoch_sha,
            ).validate()
            write_pr_binding(directory / "pr-binding-000001.json", old_binding)
            artifacts = [
                ("execution-epoch", epoch_sha),
                ("pr-binding", old_binding.sha256),
            ]
            checkpoint_epoch_sha = epoch_sha
            if checkpoint_epoch_mismatch:
                checkpoint_epoch_sha = "e" * 64
                artifacts = [
                    (name, checkpoint_epoch_sha if name == "execution-epoch" else digest)
                    for name, digest in artifacts
                ]
            if missing_checkpoint_artifact:
                artifacts = [(name, digest) for name, digest in artifacts if name != "pr-binding"]
            if malformed_checkpoint:
                artifacts.append(("unexpected", "e" * 64))
            if unbound_checkpoint_digest:
                artifacts = [
                    (name, "f" * 64 if name == "pr-binding" else digest)
                    for name, digest in artifacts
                ]
            prior_checkpoint = WorkCheckpoint(
                None, head, checkpoint_clean, checkpoint_stage, tuple(sorted(artifacts)), 1,
                execution_epoch_sha256=checkpoint_epoch_sha,
            ).validate()
            write_checkpoint(prior_checkpoint_path, prior_checkpoint)
        epoch = SimpleNamespace(
            sha256=epoch_sha,
            adc_comment_id=6935541245,
            adc_sha256="03252cba1e337944fe43fa66346482d2614320999c10d5a2f3c195a473235479",
            base_ref="main",
            base_sha40=base,
            branch_ref=branch,
        )

        def history(*_args, **_kwargs):
            paths = sorted(directory.glob("pr-binding-*.json"))
            return [(path, read_pr_binding(path)) for path in paths]

        class FakeGitHub:
            repo = "puchinya/ai-agent-workflow"

            def pull_requests_for_refs(self, *, base_ref: str, head_ref: str):
                self.assert_refs = (base_ref, head_ref)
                return [{"number": 75}]

        github = FakeGitHub()
        pull = {"number": 75, "title": "Issue #71", "body": "Closes #71"}
        patches = (
            patch.object(work_module, "read_active_epoch", return_value=epoch),
            patch.object(work_module, "is_issue71_execution_epoch", return_value=True),
            patch.object(work_module, "worktree_clean", return_value=True),
            patch.object(work_module, "current_branch", return_value=branch),
            patch.object(work_module, "head_sha40", return_value=head),
            patch.object(work_module, "is_ancestor", return_value=True),
            patch.object(work_module, "remote_branch_sha", side_effect=lambda _root, ref:
                         head if ref == branch else base),
            patch.object(work_module, "read_pr_binding_history", side_effect=history),
            patch.object(work_module, "_readback_pull", return_value=pull),
        )
        return github, epoch, old_binding, prior_checkpoint_path, prior_checkpoint, patches

    def test_issue71_same_head_adc_pr_binding_appends_checkpoint_and_retry_reuses_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github, epoch, old_binding, prior_path, prior_checkpoint, patches = \
                self._issue71_epoch_pr_fixture(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                    patches[6], patches[7], patches[8]:
                first = ensure_epoch_pull_request(
                    root, github, repository="puchinya/ai-agent-workflow", issue_number=71,
                    execution_epoch=epoch, branch_ref=epoch.branch_ref, base_ref=epoch.base_ref,
                    title="Issue #71", body="Closes #71",
                )
                old_bytes = prior_path.read_bytes()
                self.assertEqual(read_checkpoint(prior_path), prior_checkpoint)
                self.assertEqual(first.binding.adc_comment_id, epoch.adc_comment_id)
                self.assertEqual(first.checkpoint_path, checkpoint_path(root.resolve(), 71, 2))
                self.assertEqual(read_checkpoint(first.checkpoint_path).artifact_digests, tuple(sorted((
                    ("execution-epoch", epoch.sha256), ("pr-binding", first.binding.sha256),
                ))))
                self.assertEqual(len(list((root / ".p_ases/state/71").glob("pr-binding-*.json"))), 2)
                self.assertEqual(len(list((root / ".p_ases/state/71").glob("checkpoint-*.json"))), 2)

                second = ensure_epoch_pull_request(
                    root, github, repository="puchinya/ai-agent-workflow", issue_number=71,
                    execution_epoch=epoch, branch_ref=epoch.branch_ref, base_ref=epoch.base_ref,
                    title="Issue #71", body="Closes #71",
                )
                self.assertEqual(second.binding, first.binding)
                self.assertEqual(second.checkpoint_path, first.checkpoint_path)
                self.assertEqual(second.checkpoint_sha256, first.checkpoint_sha256)
                self.assertEqual(prior_path.read_bytes(), old_bytes)
                self.assertEqual(len(list((root / ".p_ases/state/71").glob("pr-binding-*.json"))), 2)
                self.assertEqual(len(list((root / ".p_ases/state/71").glob("checkpoint-*.json"))), 2)

    def test_issue71_same_head_checkpoint_conflict_blocks_before_binding_append(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github, epoch, _old_binding, prior_path, prior_checkpoint, patches = \
                self._issue71_epoch_pr_fixture(root, malformed_checkpoint=True)
            original_bytes = prior_path.read_bytes()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                    patches[6], patches[7], patches[8]:
                with self.assertRaisesRegex(WorkError, "same-HEAD checkpoint conflicts"):
                    ensure_epoch_pull_request(
                        root, github, repository="puchinya/ai-agent-workflow", issue_number=71,
                        execution_epoch=epoch, branch_ref=epoch.branch_ref, base_ref=epoch.base_ref,
                        title="Issue #71", body="Closes #71",
                    )
            self.assertEqual(read_checkpoint(prior_path), prior_checkpoint)
            self.assertEqual(prior_path.read_bytes(), original_bytes)
            self.assertEqual(len(list((root / ".p_ases/state/71").glob("pr-binding-*.json"))), 1)
            self.assertEqual(len(list((root / ".p_ases/state/71").glob("checkpoint-*.json"))), 1)

    def test_issue71_same_head_checkpoint_must_reference_binding_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github, epoch, _old_binding, prior_path, prior_checkpoint, patches = \
                self._issue71_epoch_pr_fixture(root, unbound_checkpoint_digest=True)
            original_bytes = prior_path.read_bytes()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                    patches[6], patches[7], patches[8]:
                with self.assertRaisesRegex(WorkError, "same-HEAD checkpoint conflicts"):
                    ensure_epoch_pull_request(
                        root, github, repository="puchinya/ai-agent-workflow", issue_number=71,
                        execution_epoch=epoch, branch_ref=epoch.branch_ref, base_ref=epoch.base_ref,
                        title="Issue #71", body="Closes #71",
                    )
            self.assertEqual(read_checkpoint(prior_path), prior_checkpoint)
            self.assertEqual(prior_path.read_bytes(), original_bytes)
            self.assertEqual(len(list((root / ".p_ases/state/71").glob("pr-binding-*.json"))), 1)
            self.assertEqual(len(list((root / ".p_ases/state/71").glob("checkpoint-*.json"))), 1)

    def test_issue71_same_head_non_pr_checkpoint_blocks_before_any_history_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github, epoch, _old_binding, prior_path, _prior_checkpoint, patches = \
                self._issue71_epoch_pr_fixture(root, checkpoint_stage="verification")
            directory = root / ".p_ases/state/71"
            original = {path.name: path.read_bytes() for path in directory.iterdir()
                        if path.name.startswith(("pr-binding-", "checkpoint-"))}
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                    patches[6], patches[7], patches[8]:
                with self.assertRaisesRegex(WorkError, "same-HEAD checkpoint conflicts"):
                    ensure_epoch_pull_request(
                        root, github, repository="puchinya/ai-agent-workflow", issue_number=71,
                        execution_epoch=epoch, branch_ref=epoch.branch_ref, base_ref=epoch.base_ref,
                        title="Issue #71", body="Closes #71",
                    )
            current = {path.name: path.read_bytes() for path in directory.iterdir()
                       if path.name.startswith(("pr-binding-", "checkpoint-"))}
            self.assertEqual(current, original)
            self.assertEqual(prior_path.read_bytes(), original[prior_path.name])

    def test_issue71_same_head_checkpoint_must_reference_latest_binding_not_any_history_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github, epoch, _old_binding, prior_path, _prior_checkpoint, patches = \
                self._issue71_epoch_pr_fixture(root)
            directory = root / ".p_ases/state/71"
            latest_binding = PRBinding(
                "puchinya/ai-agent-workflow", 71, epoch.adc_comment_id, epoch.adc_sha256,
                epoch.base_sha40, epoch.branch_ref, 75, "c" * 40,
                execution_epoch_sha256=epoch.sha256,
            ).validate()
            write_pr_binding(directory / "pr-binding-000002.json", latest_binding)
            original = {path.name: path.read_bytes() for path in directory.iterdir()
                        if path.name.startswith(("pr-binding-", "checkpoint-"))}
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                    patches[6], patches[7], patches[8]:
                with self.assertRaisesRegex(WorkError, "same-HEAD checkpoint conflicts"):
                    ensure_epoch_pull_request(
                        root, github, repository="puchinya/ai-agent-workflow", issue_number=71,
                        execution_epoch=epoch, branch_ref=epoch.branch_ref, base_ref=epoch.base_ref,
                        title="Issue #71", body="Closes #71",
                    )
            current = {path.name: path.read_bytes() for path in directory.iterdir()
                       if path.name.startswith(("pr-binding-", "checkpoint-"))}
            self.assertEqual(current, original)
            self.assertEqual(prior_path.read_bytes(), original[prior_path.name])

    def test_issue71_same_head_dirty_wrong_epoch_or_missing_artifact_checkpoint_fails_closed(self):
        cases = (
            ("dirty", {"checkpoint_clean": False}),
            ("wrong epoch", {"checkpoint_epoch_mismatch": True}),
            ("missing artifact", {"missing_checkpoint_artifact": True}),
        )
        for label, options in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                github, epoch, _old_binding, _prior_path, _prior_checkpoint, patches = \
                    self._issue71_epoch_pr_fixture(root, **options)
                directory = root / ".p_ases/state/71"
                original = {path.name: path.read_bytes() for path in directory.iterdir()
                            if path.name.startswith(("pr-binding-", "checkpoint-"))}
                with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                        patches[6], patches[7], patches[8]:
                    with self.assertRaises(WorkError):
                        ensure_epoch_pull_request(
                            root, github, repository="puchinya/ai-agent-workflow", issue_number=71,
                            execution_epoch=epoch, branch_ref=epoch.branch_ref, base_ref=epoch.base_ref,
                            title="Issue #71", body="Closes #71",
                        )
                current = {path.name: path.read_bytes() for path in directory.iterdir()
                           if path.name.startswith(("pr-binding-", "checkpoint-"))}
                self.assertEqual(current, original)

    def test_issue71_initial_pr_path_without_binding_history_creates_first_binding_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github, epoch, _old_binding, _prior_path, _prior_checkpoint, patches = \
                self._issue71_epoch_pr_fixture(root, initial_no_history=True)
            directory = root / ".p_ases/state/71"
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                    patches[6], patches[7], patches[8]:
                result = ensure_epoch_pull_request(
                    root, github, repository="puchinya/ai-agent-workflow", issue_number=71,
                    execution_epoch=epoch, branch_ref=epoch.branch_ref, base_ref=epoch.base_ref,
                    title="Issue #71", body="Closes #71",
                )
            self.assertEqual(result.binding.adc_comment_id, epoch.adc_comment_id)
            self.assertEqual(result.checkpoint_path, checkpoint_path(root.resolve(), 71, 1))
            self.assertTrue((directory / "pr-binding-000001.json").exists())
            self.assertTrue(result.checkpoint_path.exists())
            self.assertEqual(len(list(directory.glob("pr-binding-*.json"))), 1)
            self.assertEqual(len(list(directory.glob("checkpoint-*.json"))), 1)

    def test_reapproved_adc_appends_binding_generation_without_changing_issue_branch_or_base(self):
        with tempfile.TemporaryDirectory() as temporary:
            work, _bare, base = self._repo(Path(temporary))
            first = bind_work(
                work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                adc_sha256="a" * 64, base_ref="main", branch_ref="pases/work",
                expected_base_sha40=base,
            )
            second = bind_work(
                work, repository="owner/repo", issue_number=30, adc_comment_id=124,
                adc_sha256="b" * 64, base_ref="main", branch_ref="pases/work",
                expected_base_sha40=base,
            )
            history = read_binding_history(work / ".p_ases/state/30/execution-binding.json")
            self.assertEqual(history, (first.binding, second.binding))
            self.assertEqual(second.binding.base_sha, base)
            self.assertEqual(second.binding.branch_ref, "pases/work")

    def test_explicit_bind_upgrades_legacy_binding_with_the_selected_issue_branch(self):
        with tempfile.TemporaryDirectory() as temporary:
            work, _bare, base = self._repo(Path(temporary))
            path = work / ".p_ases/state/30/execution-binding.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "repository": "owner/repo", "issue_number": 30, "adc_comment_id": 123,
                "adc_sha256": "a" * 64, "base_ref": "main", "base_sha": base,
                "work_directory": str(work.resolve()), "initial_head_sha": base,
            }), encoding="utf-8")
            result = bind_work(
                work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                adc_sha256="a" * 64, base_ref="main", branch_ref="pases/work",
                expected_base_sha40=base,
            )
            self.assertEqual(result.binding.branch_ref, "pases/work")
            self.assertEqual(len(read_binding_history(path)), 1)

    def test_remote_base_drift_blocks_recovery_without_rewriting_binding_or_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work, bare, base = self._repo(root)
            bound = bind_work(work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                              adc_sha256="a" * 64, base_ref="main", branch_ref="pases/work")
            clone = root / "other"
            run_git(root, "clone", "--quiet", "--branch", "main", str(bare), str(clone))
            run_git(clone, "config", "user.email", "test@example.invalid")
            run_git(clone, "config", "user.name", "P-ASES tests")
            (clone / "README.md").write_text("advanced\n", encoding="utf-8")
            run_git(clone, "commit", "--quiet", "-am", "advance base")
            run_git(clone, "push", "--quiet", "origin", "main")
            before = latest_checkpoint(work, 30)
            resumed = recover_work(work, repository="owner/repo", issue_number=30,
                                   adc_comment_id=123, adc_sha256="a" * 64,
                                   expected_branch_ref="pases/work")
            after = latest_checkpoint(work, 30)
            self.assertEqual(resumed.status, "BLOCKED")
            self.assertIn("frozen base was retained", resumed.reasons[0])
            self.assertEqual(resumed.binding.base_sha, base)
            self.assertEqual(read_binding(work / ".p_ases/state/30/execution-binding.json"), bound.binding)
            self.assertEqual(after, before)

    def test_dirty_or_branch_drift_fails_without_replacing_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            work, _bare, _base = self._repo(Path(temporary))
            (work / "dirty.txt").write_text("untracked\n", encoding="utf-8")
            with self.assertRaises(WorkError):
                bind_work(work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                          adc_sha256="a" * 64, base_ref="main", branch_ref="pases/work")
            self.assertFalse((work / ".p_ases/state/30/execution-binding.json").exists())

        with tempfile.TemporaryDirectory() as temporary:
            work, _bare, _base = self._repo(Path(temporary))
            bound = bind_work(work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                              adc_sha256="a" * 64, base_ref="main", branch_ref="pases/work")
            run_git(work, "switch", "--quiet", "main")
            with self.assertRaises(WorkError):
                recover_work(work, repository="owner/repo", issue_number=30, adc_comment_id=123,
                             adc_sha256="a" * 64, expected_branch_ref="pases/work")
            self.assertEqual(read_binding(work / ".p_ases/state/30/execution-binding.json"), bound.binding)

    def test_branch_creation_uses_only_the_exact_frozen_remote_sha(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work, _bare, base = self._repo(root)
            run_git(work, "switch", "--quiet", "main")
            run_git(work, "branch", "--delete", "--force", "pases/work")
            result = ensure_branch(work, "main", base, "pases/work")
            self.assertEqual(result.status, "READY")
            self.assertEqual(head_sha40(work), base)
            self.assertEqual(run_git(work, "symbolic-ref", "--short", "HEAD"), "pases/work")
            with self.assertRaises(WorkError):
                ensure_branch(work, "main", "f" * 40, "pases/other")


if __name__ == "__main__":
    unittest.main()
