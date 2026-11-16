from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import phase_evidence as module  # noqa: E402
from p_ases import phase_rework as rework  # noqa: E402
from p_ases.phases import IssueKind, Phase  # noqa: E402


REPOSITORY = "puchinya/ai-agent-workflow"
HEAD = "d" * 40
ADC_SHA = "a" * 64
GENERATION = (6889965335, "b" * 64)


def decision() -> module.PhaseDecision:
    return module.PhaseDecision({
        "schema": module.SENTINEL_V2,
        "repository": REPOSITORY,
        "issue_number": 71,
        "issue_kind": "single",
        "from_phase": "requirements",
        "to_phase": "specification",
        "adc_comment_id": 6902977193,
        "adc_sha256": ADC_SHA,
        "branch_ref": "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3",
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


class PhaseEvidenceContinuationTests(unittest.TestCase):
    def test_current_document_reissue_accepts_valid_current_bytes_after_historical_evolution(self):
        old_documents = {
            "docs/design/workflow-design.md": "f64c7dfc6ba43c0ac62c84dcbc21c560bdd34be4004fa24804b512b191b64450",
            "docs/specs/workflow-spec.md": "4104666b05561b5b70caff0b0c26b7c9dea65d6811af78a1a51a7d0b58bff90c",
        }
        current_documents = {
            row["path"]: row["sha256"]
            for row in rework.ISSUE71_HISTORICAL_DOCUMENT_REISSUE_AUTHORIZATION[
                "current_source_document_digests"
            ]
        }
        self.assertNotEqual(old_documents, current_documents)
        generation = GENERATION
        spec = module.PhaseDecision({
            "schema": module.SENTINEL_V2, "repository": REPOSITORY, "issue_number": 71,
            "issue_kind": "single", "from_phase": "requirements", "to_phase": "specification",
            "adc_comment_id": rework.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_COMMENT_ID,
            "adc_sha256": rework.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_SHA256,
            "branch_ref": rework.BRANCH_REF, "commit_sha40": HEAD,
            "documents": [{"role": "specification", "path": path, "sha256": digest}
                          for path, digest in current_documents.items()
                          if path == "docs/specs/workflow-spec.md"],
            "skip_reasons": {}, "phase_generation_comment_id": generation[0],
            "phase_generation_sha256": generation[1],
        })
        design = module.PhaseDecision({
            "schema": module.SENTINEL_V2, "repository": REPOSITORY, "issue_number": 71,
            "issue_kind": "single", "from_phase": "specification", "to_phase": "design",
            "adc_comment_id": rework.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_COMMENT_ID,
            "adc_sha256": rework.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_SHA256,
            "branch_ref": rework.BRANCH_REF, "commit_sha40": HEAD,
            "documents": [{"role": "design" if path.endswith("workflow-design.md") else "specification",
                            "path": path, "sha256": digest}
                           for path, digest in current_documents.items()],
            "skip_reasons": {}, "phase_generation_comment_id": generation[0],
            "phase_generation_sha256": generation[1],
        })
        module._validate_issue71_current_document_snapshot(
            (spec, design), rework.ISSUE71_HISTORICAL_DOCUMENT_REISSUE_AUTHORIZATION,
        )

    def test_current_document_reissue_rejects_current_snapshot_drift(self):
        authorization = rework.ISSUE71_HISTORICAL_DOCUMENT_REISSUE_AUTHORIZATION
        expected = authorization["current_source_document_digests"]
        design = module.PhaseDecision({
            "schema": module.SENTINEL_V2, "repository": REPOSITORY, "issue_number": 71,
            "issue_kind": "single", "from_phase": "specification", "to_phase": "design",
            "adc_comment_id": rework.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_COMMENT_ID,
            "adc_sha256": rework.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_SHA256,
            "branch_ref": rework.BRANCH_REF, "commit_sha40": HEAD,
            "documents": [{"role": "design" if row["path"].endswith("workflow-design.md") else "specification",
                            "path": row["path"],
                            "sha256": "0" * 64 if row["path"].endswith("workflow-design.md") else row["sha256"]}
                           for row in expected],
            "skip_reasons": {}, "phase_generation_comment_id": GENERATION[0],
            "phase_generation_sha256": GENERATION[1],
        })
        with self.assertRaisesRegex(module.PhaseEvidenceError, "approved reissue snapshot"):
            module._validate_issue71_current_document_snapshot(
                (design,), authorization,
            )

    def test_exact_precomputed_receipt_is_accepted_for_current_adc_generation_and_head(self):
        prior = decision()
        with tempfile.TemporaryDirectory() as temporary, patch.object(module, "is_ancestor", return_value=True):
            result, previous = module._verify_predecessor_receipt(
                SimpleNamespace(repo=REPOSITORY), Path(temporary), 71,
                (Phase.REQUIREMENTS, Phase.SPECIFICATION),
                SimpleNamespace(
                    pointer=SimpleNamespace(comment_id=6902977193),
                    contract=SimpleNamespace(sha256=ADC_SHA),
                ),
                IssueKind.SINGLE,
                "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3",
                HEAD,
                {"specification": ("docs/specs/workflow-spec.md",)},
                {},
                {"docs/specs/workflow-spec.md": {
                    "role": "specification", "path": "docs/specs/workflow-spec.md", "sha256": "c" * 64,
                }},
                None,
                GENERATION,
                (6893000001, prior),
            )
        self.assertIs(result, prior)
        self.assertEqual(previous, HEAD)

    def test_precomputed_receipt_with_wrong_commit_is_rejected(self):
        prior = decision()
        prior.payload["commit_sha40"] = "e" * 40
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(module.PhaseEvidenceError, "current authorized subject"):
                module._verify_predecessor_receipt(
                    SimpleNamespace(repo=REPOSITORY), Path(temporary), 71,
                    (Phase.REQUIREMENTS, Phase.SPECIFICATION),
                    SimpleNamespace(
                        pointer=SimpleNamespace(comment_id=6902977193),
                        contract=SimpleNamespace(sha256=ADC_SHA),
                    ),
                    IssueKind.SINGLE,
                    "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3",
                    HEAD,
                    {"specification": ("docs/specs/workflow-spec.md",)},
                    {},
                    {"docs/specs/workflow-spec.md": {
                        "role": "specification", "path": "docs/specs/workflow-spec.md", "sha256": "c" * 64,
                    }},
                    None,
                    GENERATION,
                    (6893000001, prior),
                )

    def test_design_ready_preflight_failure_performs_no_comment_or_label_write(self):
        github = SimpleNamespace(
            repo=REPOSITORY,
            create_issue_comment=Mock(),
            replace_issue_labels=Mock(),
        )
        current = SimpleNamespace(pointer=SimpleNamespace(comment_id=6902977193))
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(module, "verify_adc", return_value=current), \
                patch.object(module, "_issue71_reconciled_predecessors",
                             side_effect=module.PhaseEvidenceError("pinned receipt mismatch")):
            with self.assertRaisesRegex(module.PhaseEvidenceError, "pinned receipt mismatch"):
                module.publish_phase_evidence(
                    github, Path(temporary), 71, Phase.DESIGN, Phase.READY,
                )
        github.create_issue_comment.assert_not_called()
        github.replace_issue_labels.assert_not_called()

    def test_design_ready_reconciliation_does_not_dispatch_by_adc_comment_id(self):
        github = SimpleNamespace(
            repo=REPOSITORY,
            create_issue_comment=Mock(),
            replace_issue_labels=Mock(),
        )
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(
                    module, "_issue71_reconciled_predecessors",
                    side_effect=module.PhaseEvidenceError("generic current-marker route reached"),
                ) as reconcile:
            with self.assertRaisesRegex(module.PhaseEvidenceError, "generic current-marker route reached"):
                module.publish_phase_evidence(
                    github, Path(temporary), 71, Phase.DESIGN, Phase.READY,
                )
        reconcile.assert_called_once_with(github, Path(temporary), 71)
        github.create_issue_comment.assert_not_called()
        github.replace_issue_labels.assert_not_called()

    def test_predecessor_receipt_write_rechecks_exact_live_subject_and_pr_author(self):
        issue_body = "approved Issue body"
        pr_body = "approved PR body"
        phase_authorization = {
            "branch_ref": "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3",
            "issue_body_sha256": hashlib.sha256(issue_body.encode("utf-8")).hexdigest(),
            "labels_at_start": ["enhancement", "kind:single", "phase:design"],
        }

        def live_subject(*, labels=None, head=HEAD, author_id=3744776,
                         adc_id=rework.ISSUE71_WINDOWS_PROFILE_READER_ADC_COMMENT_ID):
            return SimpleNamespace(
                current_adc=SimpleNamespace(
                    pointer=SimpleNamespace(comment_id=adc_id),
                    contract=SimpleNamespace(sha256=rework.ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256),
                ),
                issue={"body": issue_body},
                labels=tuple(labels or ("enhancement", "kind:single", "phase:design")),
                branch_ref=phase_authorization["branch_ref"],
                head_sha40=head,
                pr={
                    "title": rework.PR_TITLE,
                    "body": pr_body,
                    "user": {"type": "User", "id": author_id},
                },
            )

        cases = (
            ("labels", {"labels": ("enhancement", "kind:single", "phase:ready")}),
            ("head", {"head": "e" * 40}),
            ("PR author", {"author_id": 999}),
            ("ADC pointer", {"adc_id": 123}),
        )
        for mismatch, changes in cases:
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as temporary:
                live = live_subject(**changes)
                receipt = decision()
                receipt.payload["adc_sha256"] = rework.ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256
                github = SimpleNamespace(
                    repo=REPOSITORY,
                    issue_comments=Mock(return_value=[]),
                    create_issue_comment=Mock(return_value={"id": 1234}),
                )
                with patch.object(rework, "_live", return_value=live), \
                        patch.object(
                            module,
                            "verify_ordinary_issue_context",
                            return_value=SimpleNamespace(
                                commit_sha40=live.head_sha40,
                                verified_adc=live.current_adc,
                            ),
                        ), \
                        patch.object(
                            rework,
                            "verify_issue71_phase_and_user_review_adc_chain",
                            return_value=({"phase_receipt_reconciliation": phase_authorization}, []),
                        ), \
                        patch.object(rework, "PR_BODY_SHA256", hashlib.sha256(pr_body.encode("utf-8")).hexdigest()):
                    with self.assertRaisesRegex(module.PhaseEvidenceError, "changed before predecessor receipt publication"):
                        module._publish_prepared_predecessor(
                            github, Path(temporary), 71, receipt, receipt.body(),
                        )
                github.create_issue_comment.assert_not_called()

    def test_windows_profile_artifact_impact_uses_generic_role_path_grammar(self):
        impact = rework.ISSUE71_WINDOWS_PROFILE_READER_ARTIFACT_IMPACT
        verified = SimpleNamespace(contract=SimpleNamespace(section=lambda _name: impact))
        paths, reasons = module._artifact_impacts(verified)
        self.assertEqual(paths, {
            "specification": ("docs/specs/workflow-spec.md",),
            "design": ("docs/design/workflow-design.md",),
            "test-oracle": (
                "docs/testing/pases-lifecycle-tests.md",
                "docs/testing/runtime-tests.md",
                "docs/testing/traceability.md",
            ),
        })
        self.assertEqual(reasons, {})

    def test_windows_profile_artifact_impact_rejects_duplicate_and_incomplete_roles(self):
        impact = rework.ISSUE71_WINDOWS_PROFILE_READER_ARTIFACT_IMPACT
        duplicate = impact.replace(
            "- Specification: docs/specs/workflow-spec.md",
            "- Specification: docs/specs/workflow-spec.md\n- Specification: docs/specs/workflow-spec.md",
        )
        with self.assertRaisesRegex(module.PhaseEvidenceError, "duplicates its Specification"):
            module._artifact_impacts(SimpleNamespace(contract=SimpleNamespace(section=lambda _name: duplicate)))
        incomplete = "- Specification: docs/specs/workflow-spec.md\n- Design: docs/design/workflow-design.md"
        with self.assertRaisesRegex(module.PhaseEvidenceError, "must declare Specification, Design, and Testing"):
            module._artifact_impacts(SimpleNamespace(contract=SimpleNamespace(section=lambda _name: incomplete)))

    def test_windows_profile_current_document_snapshot_accepts_only_authorized_hashes(self):
        authorization = rework.ISSUE71_WINDOWS_PROFILE_CURRENT_DOCUMENT_SNAPSHOT_AUTHORIZATION
        rows = authorization["current_source_document_digests"]
        spec = decision()
        spec.payload["documents"] = [{"role": "specification", **rows[1]}]
        design = decision()
        design.payload["from_phase"] = "specification"
        design.payload["to_phase"] = "design"
        design.payload["documents"] = [{"role": "design", **rows[0]}]
        decisions = (spec, design)
        module._validate_issue71_current_document_snapshot(decisions, authorization)
        changed = dict(authorization)
        changed["current_source_document_digests"] = [
            {**row, "sha256": "0" * 64} if row["path"].endswith("workflow-design.md") else row
            for row in rows
        ]
        with self.assertRaisesRegex(module.PhaseEvidenceError, "approved reissue snapshot"):
            module._validate_issue71_current_document_snapshot(decisions, changed)


if __name__ == "__main__":
    unittest.main()
