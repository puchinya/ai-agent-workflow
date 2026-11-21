from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import phase_evidence as module  # noqa: E402
from p_ases.phases import IssueKind, Phase  # noqa: E402


REPOSITORY = "octo/repo"
HEAD = "d" * 40
ADC_SHA = "a" * 64
GENERATION = (6889965335, "b" * 64)


def decision() -> module.PhaseDecision:
    return module.PhaseDecision({
        "schema": module.SENTINEL_V2,
        "repository": REPOSITORY,
        "issue_number": 128,
        "issue_kind": "single",
        "from_phase": "requirements",
        "to_phase": "specification",
        "adc_comment_id": 6902977193,
        "adc_sha256": ADC_SHA,
        "branch_ref": "pases/work",
        "commit_sha40": HEAD,
        "documents": [{
            "role": "specification",
            "path": "docs/specs/workflow-spec.md",
            "sha256": "c" * 64,
        }],
        "skip_reasons": {},
        "phase_generation_comment_id": GENERATION[0],
        "phase_generation_sha256": GENERATION[1],
    })


class GenericPhaseEvidenceTests(unittest.TestCase):
    def test_precomputed_receipt_matches_current_generation_and_head(self):
        prior = decision()
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "is_ancestor", return_value=True):
            result, previous = module._verify_predecessor_receipt(
                SimpleNamespace(repo=REPOSITORY), Path(directory), 128,
                (Phase.REQUIREMENTS, Phase.SPECIFICATION),
                SimpleNamespace(
                    pointer=SimpleNamespace(comment_id=6902977193),
                    contract=SimpleNamespace(sha256=ADC_SHA),
                ),
                IssueKind.SINGLE, "pases/work", HEAD,
                {"specification": ("docs/specs/workflow-spec.md",)}, {},
                {"docs/specs/workflow-spec.md": {
                    "role": "specification", "path": "docs/specs/workflow-spec.md", "sha256": "c" * 64,
                }},
                None, GENERATION, (6893000001, prior),
            )
        self.assertIs(result, prior)
        self.assertEqual(previous, HEAD)

    def test_stale_predecessor_commit_is_rejected(self):
        prior = decision()
        prior.payload["commit_sha40"] = "e" * 40
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(module.PhaseEvidenceError, "current authorized subject"):
                module._verify_predecessor_receipt(
                    SimpleNamespace(repo=REPOSITORY), Path(directory), 128,
                    (Phase.REQUIREMENTS, Phase.SPECIFICATION),
                    SimpleNamespace(pointer=SimpleNamespace(comment_id=6902977193),
                                    contract=SimpleNamespace(sha256=ADC_SHA)),
                    IssueKind.SINGLE, "pases/work", HEAD,
                    {"specification": ("docs/specs/workflow-spec.md",)}, {},
                    {"docs/specs/workflow-spec.md": {
                        "role": "specification", "path": "docs/specs/workflow-spec.md", "sha256": "c" * 64,
                    }},
                    None, GENERATION, (6893000001, prior),
                )

    def test_publish_uses_current_issue_and_adc_for_arbitrary_issue(self):
        issue = {"number": 128, "state": "open", "labels": [{"name": "phase:specification"}],
                 "body": "unchanged", "repository_url": "https://api.github.com/repos/octo/repo"}
        pointer = SimpleNamespace(comment_id=6902977193, state="approved", sha256=ADC_SHA)
        verified = SimpleNamespace(pointer=pointer, contract=SimpleNamespace(sha256=ADC_SHA))
        github = SimpleNamespace(
            repo=REPOSITORY,
            issue_comments=Mock(return_value=[]),
            issue=Mock(return_value=issue),
            branch=Mock(return_value={"commit": {"sha": HEAD}}),
            create_issue_comment=Mock(return_value={"id": 9001}),
        )
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(module, "_collect_payload", return_value=(
                    decision(), issue, verified, "pases/work", HEAD)) as collect, \
                patch.object(module, "_readback", return_value=decision()) as readback, \
                patch.object(module, "verify_adc", return_value=verified), \
                patch.object(module, "refresh_adc_forward_generation_session"), \
                patch.object(module, "adc_forward_generation_session") as session:
            session.return_value.__enter__ = lambda _self: None
            session.return_value.__exit__ = lambda _self, _type, _exc, _tb: False
            comment_id, result = module.publish_phase_evidence(
                github, Path(directory), 128, Phase.REQUIREMENTS, Phase.SPECIFICATION,
            )
        self.assertEqual(comment_id, 9001)
        self.assertEqual(result.body(), decision().body())
        self.assertEqual(collect.call_count, 2)
        github.create_issue_comment.assert_called_once_with(128, decision().body())
        readback.assert_called_once()

    def test_publish_stale_issue_blocks_before_post(self):
        issue = {"number": 128, "state": "open", "labels": [{"name": "phase:specification"}],
                 "body": "initial", "repository_url": "https://api.github.com/repos/octo/repo"}
        changed = {**issue, "body": "concurrent edit"}
        pointer = SimpleNamespace(comment_id=6902977193, state="approved", sha256=ADC_SHA)
        verified = SimpleNamespace(pointer=pointer, contract=SimpleNamespace(sha256=ADC_SHA))
        github = SimpleNamespace(
            repo=REPOSITORY, issue_comments=Mock(return_value=[]),
            issue=Mock(return_value=changed),
            branch=Mock(return_value={"commit": {"sha": HEAD}}),
            create_issue_comment=Mock(),
        )
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(module, "_collect_payload", return_value=(
                    decision(), issue, verified, "pases/work", HEAD)), \
                patch.object(module, "verify_adc", return_value=verified), \
                patch.object(module, "refresh_adc_forward_generation_session"), \
                patch.object(module, "adc_forward_generation_session") as session:
            session.return_value.__enter__ = lambda _self: None
            session.return_value.__exit__ = lambda _self, _type, _exc, _tb: False
            # The preflight must use a fresh live Issue snapshot, not only the initial payload.
            with self.assertRaises(module.PhaseEvidenceError):
                module.publish_phase_evidence(
                    github, Path(directory), 128, Phase.REQUIREMENTS, Phase.SPECIFICATION,
                )
        github.create_issue_comment.assert_not_called()

    def test_ready_refresh_uses_generic_command_scope(self):
        github = SimpleNamespace(repo=REPOSITORY)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(module, "_refresh_ready_phase_evidence",
                             return_value=(9001, decision(), "REUSED")) as refresh, \
                patch.object(module, "adc_forward_generation_session") as session:
            session.return_value.__enter__ = lambda _self: None
            session.return_value.__exit__ = lambda _self, _type, _exc, _tb: False
            result = module.refresh_ready_phase_evidence(github, Path(directory), 128)
        self.assertEqual(result[0], 9001)
        refresh.assert_called_once()

    def test_artifact_impact_role_paths_are_generic(self):
        impact = ("- Specification: docs/specs/workflow-spec.md\n"
                  "- Design: docs/design/workflow-design.md\n"
                  "- Testing: docs/testing/pases-lifecycle-tests.md\n")
        verified = SimpleNamespace(contract=SimpleNamespace(section=lambda _name: impact))
        roles, reasons = module._artifact_impacts(verified)
        self.assertEqual(roles["specification"], ("docs/specs/workflow-spec.md",))
        self.assertEqual(roles["design"], ("docs/design/workflow-design.md",))
        self.assertIn("docs/testing/pases-lifecycle-tests.md", roles["test-oracle"])
        self.assertEqual(reasons, {})
        with self.assertRaises(module.PhaseEvidenceError):
            module._artifact_impacts(SimpleNamespace(contract=SimpleNamespace(
                section=lambda _name: impact + "- Specification: docs/specs/workflow-spec.md\n",
            )))


if __name__ == "__main__":
    unittest.main()
