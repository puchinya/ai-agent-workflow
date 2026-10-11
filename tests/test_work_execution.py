from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.checkpoint import read_checkpoint
from p_ases.execution import binding_digest, read_binding
from p_ases.git import head_sha40, run_git
from p_ases.work import WorkError, bind_work, ensure_branch, latest_checkpoint, recover_work


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
