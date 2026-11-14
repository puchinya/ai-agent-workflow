from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.checkpoint import (
    CheckpointError, PRBinding, WorkCheckpoint, checkpoint_path, read_checkpoint,
    read_pr_binding, write_checkpoint, write_pr_binding,
)


class CheckpointSchemaTests(unittest.TestCase):
    def binding(self):
        return PRBinding(
            repository="octo/repo", issue_number=30, adc_comment_id=123, adc_sha256="a" * 64,
            base_sha40="b" * 40, branch_ref="pases/work-readiness", pr_number=55,
            pr_head_sha40="c" * 40,
        )

    def checkpoint(self, *, step=1, clean=True, stage="base"):
        return WorkCheckpoint(
            execution_binding_sha256="d" * 64, current_head_sha40="b" * 40,
            worktree_clean=clean, completed_stage=stage,
            artifact_digests=(("execution-binding", "d" * 64),), step=step,
        ).validate()

    def test_pr_binding_is_subject_specific_and_checks_refs(self):
        binding = self.binding().validate()
        self.assertEqual(len(binding.sha256), 64)
        with self.assertRaises(CheckpointError):
            replace(binding, branch_ref="../main").validate()
        with self.assertRaises(CheckpointError):
            replace(binding, pr_head_sha40="b" * 64).validate()

    def test_pr_binding_is_immutable_and_canonical_on_disk(self):
        binding = self.binding()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "pr-binding.json"
            self.assertEqual(write_pr_binding(path, binding), binding.sha256)
            self.assertEqual(read_pr_binding(path), binding)
            self.assertEqual(write_pr_binding(path, binding), binding.sha256)
            with self.assertRaises(CheckpointError):
                write_pr_binding(path, replace(binding, pr_number=56))

    def test_checkpoint_create_only_retry_and_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            path = checkpoint_path(Path(root), 30, 1)
            item = self.checkpoint()
            self.assertEqual(write_checkpoint(path, item), item.sha256)
            self.assertEqual(write_checkpoint(path, item), item.sha256)
            self.assertEqual(read_checkpoint(path), item)
            with self.assertRaises(CheckpointError):
                write_checkpoint(path, self.checkpoint(clean=False))

    def test_checkpoint_rejects_symlink_and_nonmonotonic_artifact_schema(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            target = base / "target.json"
            target.write_bytes(self.checkpoint().to_bytes())
            link = base / "link.json"
            link.symlink_to(target)
            with self.assertRaises(CheckpointError):
                read_checkpoint(link)
        with self.assertRaises(CheckpointError):
            replace(self.checkpoint(), artifact_digests=(("z", "a" * 64), ("a", "b" * 64))).validate()

    def test_checkpoint_storage_rejects_symlinked_pases_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            actual = base / "actual"
            actual.mkdir()
            workspace = base / "workspace"
            workspace.mkdir()
            (workspace / ".p_ases").symlink_to(actual, target_is_directory=True)
            path = checkpoint_path(workspace, 30, 1)
            with self.assertRaises(CheckpointError):
                write_checkpoint(path, self.checkpoint())

    def test_issue71_prbinding_v4_and_checkpoint_v3_round_trip_exact_epoch_digest(self):
        epoch_sha = "e" * 64
        binding = PRBinding(
            repository="puchinya/ai-agent-workflow", issue_number=71, adc_comment_id=6874553609,
            adc_sha256="aa0e69210dec4f2df1b069eafc4f5ce99ca3a71465a7ca59da3a05301fa023a4",
            base_sha40="07481c4b451a81750a6c2e1a6a18bdfd4e3459c2",
            branch_ref="pases/issue-71-local-activation-v2-epoch-2", pr_number=81,
            pr_head_sha40="c" * 40, execution_epoch_sha256=epoch_sha,
        ).validate()
        checkpoint = WorkCheckpoint(
            execution_binding_sha256=None, current_head_sha40="c" * 40,
            worktree_clean=True, completed_stage="pr",
            artifact_digests=tuple(sorted((
                ("execution-epoch", epoch_sha), ("pr-binding", binding.sha256),
            ))), step=1, execution_epoch_sha256=epoch_sha,
        ).validate()
        with tempfile.TemporaryDirectory() as root:
            pr_path = Path(root) / "pr-binding.json"
            checkpoint_file = checkpoint_path(Path(root), 71, 1)
            write_pr_binding(pr_path, binding)
            write_checkpoint(checkpoint_file, checkpoint)
            self.assertEqual(read_pr_binding(pr_path), binding)
            self.assertEqual(read_checkpoint(checkpoint_file), checkpoint)
            self.assertIn(b'"schema":"PASES_PR_BINDING_V4"', pr_path.read_bytes())
            self.assertIn(b'"schema":"PASES_WORK_CHECKPOINT_V3"', checkpoint_file.read_bytes())
        with self.assertRaises(CheckpointError):
            replace(binding, issue_number=63).validate()
        with self.assertRaises(CheckpointError):
            replace(binding, current_base_sha40="d" * 40, current_base_advance_sha256="f" * 64).validate()
        with self.assertRaises(CheckpointError):
            replace(checkpoint, execution_binding_sha256="a" * 64).validate()


if __name__ == "__main__":
    unittest.main()
