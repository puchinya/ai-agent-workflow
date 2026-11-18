"""One-shot, exact-ADC-authorized Issue #71 verification phase rework."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .adc import (
    ADCError, VerifiedADC, verify_adc, verify_adc_forward_generations,
    verify_adc_generation, refresh_adc_forward_generation_session,
)
from .checkpoint import PRBinding, WorkCheckpoint, checkpoint_path, write_checkpoint, write_pr_binding
from .delivery import ReadinessResult, read_readiness, readiness_path
from .github import GitHub, GitHubError
from .git import (
    GitError, changed_paths_between, commit_parents_sha40, current_branch,
    head_sha40, is_ancestor, remote_branch_sha, run_git, worktree_clean,
)
from .path_safety import path_has_symlink

REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
OWNER_ID = 3744776
ISSUE_NUMBER = 71
ISSUE_ID = 6135294757
ISSUE_BODY_SHA256 = "5f910c8de4cbe3ec391edf18b69fabe0f4c42880b59357083647a8b06e7a6a36"
REWORK_ADC_COMMENT_ID = 6887429739
REWORK_ADC_SHA256 = "c4de9fc1308c63f0de3ba4b8269fa779d2c38688cf420c59031911d1522cb8e2"
REWORK_ADC_BYTES = 15113
RECOVERY_ADC_COMMENT_ID = 6888665795
RECOVERY_ADC_SHA256 = "a12b71873e64a10f119a38df94e55c96c64d6cb1fc2e510432cf7d40116c7e4f"
RECOVERY_ADC_BYTES = 15501
RECOVERY_AUTH_MARKER_SHA256 = "3b229664d98735478bf764c420058a1dec72e4412618548b5045e6734583ec9d"
RECOVERY_AUTH_MARKER_BYTES = 2347
PREDECESSOR_ADC_COMMENT_ID = 6886911700
PREDECESSOR_ADC_SHA256 = "a3c171ab44bf2145aea25b9e43b35fc235b04748e9ad2228847c7379f404e350"
EPOCH_ORIGIN_ADC_COMMENT_ID = 6881591677
EPOCH_ORIGIN_ADC_SHA256 = "3c6b3ac28270357b57047dc5da0a2c1fbdbada269d55225ea33a656cd3076e17"
ACTIVE_EPOCH_ID = "50af48a8a0d92f65f362ee371959152de755ab7057604a47a9155e938357ee8a"
ACTIVE_EPOCH_SHA256 = "086a8e23601a869e4ec678a80ef82836c1cf76d50be13788658b02e037c51d00"
ACTIVE_PHASE_COMMENT_ID = 6881839877
ACTIVE_PHASE_SHA256 = "133cba8d9fb815581de12552bac9d76cb634819d012513e9e3be086e4180a3c5"
BASELINE_HEAD = "b781ddf1bd6eb5067e87f269da4b1306341e682d"
BASE_REF = "main"
BASE_SHA40 = "07481c4b451a81750a6c2e1a6a18bdfd4e3459c2"
BRANCH_REF = "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3"
PR_NUMBER = 75
PR_TITLE = "[P-ASES] Issue #71 local Activation V2 epoch-3"
PR_BODY_SHA256 = "12f3dc5d45a8ca9d1155a80608d05b31402acd0d39d33f61afeee844b93efff7"
PR_BASE_REF = "main"
PR_BASE_SHA40 = "07481c4b451a81750a6c2e1a6a18bdfd4e3459c2"
PRIOR_READINESS_SHA256 = "62e1ab213abe3ffe81939a4bfaae92f86bbf1c465b787a81eab8d6cee129448e"
LABELS_BEFORE = ["enhancement", "kind:single", "phase:verification"]
LABELS_AFTER = ["enhancement", "kind:single", "phase:requirements"]
AUTH_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_AUTHORIZATION_V2"
INTENT_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_INTENT_V2"
APPLIED_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V2"
INTENT_START = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_START = f"<!-- {APPLIED_SCHEMA}\n"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")

BOOTSTRAP_PATH_ALLOWLIST = (
    "dist/antigravity/docs/design/runtime-design.md",
    "dist/antigravity/docs/design/workflow-design.md",
    "dist/antigravity/docs/specs/runtime-spec.md",
    "dist/antigravity/docs/specs/workflow-spec.md",
    "dist/antigravity/runtime/p_ases/cli.py",
    "dist/antigravity/runtime/p_ases/phase_epoch_rebaseline.py",
    "dist/antigravity/runtime/p_ases/phase_rework.py",
    "dist/claude/docs/design/runtime-design.md",
    "dist/claude/docs/design/workflow-design.md",
    "dist/claude/docs/specs/runtime-spec.md",
    "dist/claude/docs/specs/workflow-spec.md",
    "dist/claude/runtime/p_ases/cli.py",
    "dist/claude/runtime/p_ases/phase_epoch_rebaseline.py",
    "dist/claude/runtime/p_ases/phase_rework.py",
    "dist/openai/docs/design/runtime-design.md",
    "dist/openai/docs/design/workflow-design.md",
    "dist/openai/docs/specs/runtime-spec.md",
    "dist/openai/docs/specs/workflow-spec.md",
    "dist/openai/runtime/p_ases/cli.py",
    "dist/openai/runtime/p_ases/phase_epoch_rebaseline.py",
    "dist/openai/runtime/p_ases/phase_rework.py",
    "docs/design/runtime-design.md",
    "docs/design/workflow-design.md",
    "docs/specs/runtime-spec.md",
    "docs/specs/workflow-spec.md",
    "docs/testing/pases-lifecycle-tests.md",
    "docs/testing/runtime-tests.md",
    "docs/testing/traceability.md",
    "runtime/p_ases/cli.py",
    "runtime/p_ases/phase_epoch_rebaseline.py",
    "runtime/p_ases/phase_rework.py",
    "runtime/p_ases/phases.py",
    "tests/test_p_ases_cli.py",
    "tests/test_phase_epoch_rebaseline.py",
    "tests/test_phase_rework.py",
)

AUTHORIZATION: dict[str, Any] = {
    "active_epoch_id": ACTIVE_EPOCH_ID,
    "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
    "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
    "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
    "baseline_head_sha40": BASELINE_HEAD,
    "baseline_pr_head_sha40": BASELINE_HEAD,
    "bootstrap_path_allowlist": list(BOOTSTRAP_PATH_ALLOWLIST),
    "branch_ref": BRANCH_REF,
    "current_issue_body_sha256": ISSUE_BODY_SHA256,
    "epoch_origin_adc_comment_id": EPOCH_ORIGIN_ADC_COMMENT_ID,
    "epoch_origin_adc_sha256": EPOCH_ORIGIN_ADC_SHA256,
    "existing_user_review_session": "absent",
    "from_phase": "verification",
    "issue_number": ISSUE_NUMBER,
    "labels_after": LABELS_AFTER,
    "labels_before": LABELS_BEFORE,
    "max_applications": 1,
    "max_bootstrap_commits": 3,
    "owner_id": OWNER_ID,
    "pr_base_ref": PR_BASE_REF,
    "pr_base_sha40": PR_BASE_SHA40,
    "pr_number": PR_NUMBER,
    "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
    "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
    "prior_readiness_sha256": PRIOR_READINESS_SHA256,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "require_fresh_readiness": True,
    "schema": AUTH_SCHEMA,
    "target_issue": ISSUE_NUMBER,
    "to_phase": "requirements",
}
AUTH_FIELDS = frozenset(AUTHORIZATION)
REWORK_AUTH_MARKER_BYTES = 3063
REWORK_AUTH_MARKER_SHA256 = "fde0de816339ae96cbb327bb287cca4da02afecd60f1921b2a32b8b7ef8e4394"
RECOVERY_AUTH_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_RECOVERY_AUTHORIZATION_V1"
RECOVERY_AUTHORIZATION: dict[str, Any] = {
    "active_epoch_id": ACTIVE_EPOCH_ID,
    "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
    "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
    "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
    "branch_ref": BRANCH_REF,
    "current_issue_body_sha256": ISSUE_BODY_SHA256,
    "executor_user_id": OWNER_ID,
    "intent_attempt_payload_sha256": "7466f59e2e797e1f4116c31e07cdde1d73784dbefe44c25875f7e405f2d7b701",
    "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
    "intent_comment_id": 6888474848,
    "intent_readiness_sha256": "520cd31540b5ab6ed27ed6e11afbef85ad93ce371625713ab2f914a4224834e6",
    "intent_readiness_subject_sha256": "faad0f2917297526c89fdb948a5219dd7952a85b6ac8ebe0eec195c6c837d9cc",
    "issue_id": ISSUE_ID,
    "issue_number": ISSUE_NUMBER,
    "labels_after": LABELS_AFTER,
    "labels_before": LABELS_BEFORE,
    "max_recovery_applications": 1,
    "max_recovery_commits": 1,
    "owner_id": OWNER_ID,
    "predecessor_adc_comment_id": REWORK_ADC_COMMENT_ID,
    "predecessor_adc_sha256": REWORK_ADC_SHA256,
    "pre_recovery_head_sha40": "4185a510054a2a8781659191c1a48178336f8571",
    "pr_base_ref": PR_BASE_REF,
    "pr_base_sha40": PR_BASE_SHA40,
    "pr_number": PR_NUMBER,
    "recovery_path_allowlist": [
        "dist/antigravity/docs/design/workflow-design.md",
        "dist/antigravity/docs/specs/workflow-spec.md",
        "dist/antigravity/runtime/p_ases/phase_rework.py",
        "dist/claude/docs/design/workflow-design.md",
        "dist/claude/docs/specs/workflow-spec.md",
        "dist/claude/runtime/p_ases/phase_rework.py",
        "dist/openai/docs/design/workflow-design.md",
        "dist/openai/docs/specs/workflow-spec.md",
        "dist/openai/runtime/p_ases/phase_rework.py",
        "docs/design/workflow-design.md",
        "docs/specs/workflow-spec.md",
        "docs/testing/pases-lifecycle-tests.md",
        "docs/testing/runtime-tests.md",
        "docs/testing/traceability.md",
        "runtime/p_ases/phase_rework.py",
        "tests/test_phase_rework.py",
    ],
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "schema": RECOVERY_AUTH_SCHEMA,
}
RECOVERY_AUTH_FIELDS = frozenset(RECOVERY_AUTHORIZATION)
TIMESTAMP_RECOVERY_ADC_COMMENT_ID = 6890080277
TIMESTAMP_RECOVERY_ADC_SHA256 = "5fe132fba564d931da116bfa94f3a21efe2f35d943e790bf2087edf2423c52c5"
TIMESTAMP_RECOVERY_ADC_BYTES = 15762
TIMESTAMP_RECOVERY_AUTH_SCHEMA = "PASES_ISSUE_PHASE_REWORK_APPLIED_TIMESTAMP_RECOVERY_AUTHORIZATION_V1"
TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256 = "6563450ede995620762d364e04c6819a5009bf95b8158a8608e6aabd27d459d0"
TIMESTAMP_RECOVERY_AUTH_MARKER_BYTES = 2258
TIMESTAMP_RECOVERY_AUTHORIZATION: dict[str, Any] = {
    "active_epoch_id": ACTIVE_EPOCH_ID,
    "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
    "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
    "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
    "applied_at": "2026-11-15T05:50:01Z",
    "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
    "applied_comment_created_at": "2026-11-15T05:50:04Z",
    "applied_comment_id": 6889965335,
    "applied_max_skew_seconds": 300,
    "applied_timestamp_delta_seconds": 3,
    "branch_ref": BRANCH_REF,
    "current_head_sha40": "574d7970323840933c34c37e874ad1616d577a8a",
    "current_issue_body_sha256": ISSUE_BODY_SHA256,
    "executor_user_id": OWNER_ID,
    "followup_path_allowlist": RECOVERY_AUTHORIZATION["recovery_path_allowlist"],
    "frozen_base_ref": BASE_REF,
    "frozen_base_sha40": BASE_SHA40,
    "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
    "intent_comment_id": 6888474848,
    "issue_id": ISSUE_ID,
    "issue_number": ISSUE_NUMBER,
    "labels_after": LABELS_AFTER,
    "max_followup_commits": 1,
    "owner_id": OWNER_ID,
    "predecessor_adc_comment_id": RECOVERY_ADC_COMMENT_ID,
    "predecessor_adc_sha256": RECOVERY_ADC_SHA256,
    "pr_number": PR_NUMBER,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "schema": TIMESTAMP_RECOVERY_AUTH_SCHEMA,
}
TIMESTAMP_RECOVERY_AUTH_FIELDS = frozenset(TIMESTAMP_RECOVERY_AUTHORIZATION)
PATH_CORRECTION_ADC_COMMENT_ID = 6891800412
PATH_CORRECTION_ADC_SHA256 = "ca22ada47ffb31479ccc57664052486808fa86de3eabf2c1fb5680ca33b05280"
PATH_CORRECTION_ADC_BYTES = 9188
PATH_CORRECTION_ARTIFACT_IMPACT = (
    "## Artifact impact\n\n"
    "- Specification: `docs/specs/workflow-spec.md`.\n"
    "- Design: `docs/design/workflow-design.md`.\n"
    "- Testing: `docs/testing/pases-lifecycle-tests.md`, `docs/testing/runtime-tests.md`, "
    "`docs/testing/traceability.md`."
)
CONTINUATION_ADC_COMMENT_ID = 6891926625
CONTINUATION_ADC_SHA256 = "64c8d8d3ceb06f5e04d6c9eb780c0bb3a0607dc61440e136b00bcdf63cf941a8"
CONTINUATION_ADC_BYTES = 16060
CONTINUATION_AUTH_SCHEMA = "PASES_ISSUE_PHASE_EVIDENCE_CONTINUATION_AUTHORIZATION_V1"
CONTINUATION_AUTH_MARKER_BYTES = 2155
CONTINUATION_AUTH_MARKER_SHA256 = "f74bcd07095019aade9bfb4247bdfba1efe92d6daf925f0988f88b79d04199a5"
CONTINUATION_ARTIFACT_IMPACT = (
    "## Artifact impact\n\n"
    "- Specification: `docs/specs/workflow-spec.md`.\n"
    "- Design: `docs/design/workflow-design.md`.\n"
    "- Testing: `docs/testing/pases-lifecycle-tests.md`, `docs/testing/traceability.md`."
)
CONTINUATION_AUTHORIZATION: dict[str, Any] = {
    "active_epoch_id": ACTIVE_EPOCH_ID,
    "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
    "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
    "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
    "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
    "applied_comment_id": 6889965335,
    "branch_ref": BRANCH_REF,
    "current_head_sha40": "cb02a9fccfb988300dff82c5ad2ccfe946cd4dd3",
    "current_issue_body_sha256": ISSUE_BODY_SHA256,
    "executor_user_id": OWNER_ID,
    "followup_path_allowlist": [
        "dist/antigravity/docs/design/workflow-design.md",
        "dist/antigravity/docs/specs/workflow-spec.md",
        "dist/antigravity/runtime/p_ases/phase_rework.py",
        "dist/claude/docs/design/workflow-design.md",
        "dist/claude/docs/specs/workflow-spec.md",
        "dist/claude/runtime/p_ases/phase_rework.py",
        "dist/openai/docs/design/workflow-design.md",
        "dist/openai/docs/specs/workflow-spec.md",
        "dist/openai/runtime/p_ases/phase_rework.py",
        "docs/design/workflow-design.md",
        "docs/specs/workflow-spec.md",
        "docs/testing/pases-lifecycle-tests.md",
        "docs/testing/traceability.md",
        "runtime/p_ases/phase_rework.py",
        "tests/test_p_ases_cli.py",
        "tests/test_phase_rework.py",
    ],
    "frozen_base_ref": BASE_REF,
    "frozen_base_sha40": BASE_SHA40,
    "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
    "intent_comment_id": 6888474848,
    "issue_id": ISSUE_ID,
    "issue_number": ISSUE_NUMBER,
    "labels_before": LABELS_AFTER,
    "max_followup_commits": 1,
    "owner_id": OWNER_ID,
    "predecessor_adc_comment_id": PATH_CORRECTION_ADC_COMMENT_ID,
    "predecessor_adc_sha256": PATH_CORRECTION_ADC_SHA256,
    "pr_base_ref": PR_BASE_REF,
    "pr_base_sha40": PR_BASE_SHA40,
    "pr_number": PR_NUMBER,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "schema": CONTINUATION_AUTH_SCHEMA,
}
CONTINUATION_AUTH_FIELDS = frozenset(CONTINUATION_AUTHORIZATION)
TRACEABILITY_CORRECTION_ADC_COMMENT_ID = 6893385802
TRACEABILITY_CORRECTION_ADC_SHA256 = "65e5c9b928ce5b554ea16cf6fc8af2d1867018a0464d3247809c163e69ecd6ab"
TRACEABILITY_CORRECTION_ADC_BYTES = 9955
READER_CONTINUATION_ADC_COMMENT_ID = 6893557456
READER_CONTINUATION_ADC_SHA256 = "b19dca5243f90d96d013a432b41ece5892f39fc8217ebf63fccb8f0ada4fd81f"
READER_CONTINUATION_ADC_BYTES = 16823
READER_CONTINUATION_AUTH_SCHEMA = "PASES_ISSUE_PHASE_EVIDENCE_READER_CONTINUATION_V1"
READER_CONTINUATION_AUTH_MARKER_BYTES = 2168
READER_CONTINUATION_AUTH_MARKER_SHA256 = "abd0bf59c4758e6adcb2ab6e73fb97cebae2e3ecc5d9c19e6e200b13dff878f7"
READER_CONTINUATION_ARTIFACT_IMPACT = (
    "## Artifact impact\n\n"
    "- Specification: `docs/specs/workflow-spec.md`.\n"
    "- Design: `docs/design/workflow-design.md`.\n"
    "- Testing: `docs/testing/pases-lifecycle-tests.md`, `docs/testing/traceability.md`."
)
READER_CONTINUATION_AUTHORIZATION: dict[str, Any] = {
    "active_epoch_id": ACTIVE_EPOCH_ID,
    "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
    "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
    "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
    "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
    "applied_comment_id": 6889965335,
    "branch_ref": BRANCH_REF,
    "current_issue_body_sha256": ISSUE_BODY_SHA256,
    "followup_path_allowlist": [
        "dist/antigravity/docs/design/workflow-design.md",
        "dist/antigravity/docs/specs/workflow-spec.md",
        "dist/antigravity/runtime/p_ases/phase_rework.py",
        "dist/claude/docs/design/workflow-design.md",
        "dist/claude/docs/specs/workflow-spec.md",
        "dist/claude/runtime/p_ases/phase_rework.py",
        "dist/openai/docs/design/workflow-design.md",
        "dist/openai/docs/specs/workflow-spec.md",
        "dist/openai/runtime/p_ases/phase_rework.py",
        "docs/design/workflow-design.md",
        "docs/specs/workflow-spec.md",
        "docs/testing/pases-lifecycle-tests.md",
        "docs/testing/traceability.md",
        "runtime/p_ases/phase_rework.py",
        "tests/test_phase_rework.py",
    ],
    "frozen_base_ref": BASE_REF,
    "frozen_base_sha40": BASE_SHA40,
    "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
    "intent_comment_id": 6888474848,
    "issue_id": ISSUE_ID,
    "issue_number": ISSUE_NUMBER,
    "labels_at_start": ["enhancement", "kind:single", "phase:design"],
    "max_followup_commits": 1,
    "owner_id": OWNER_ID,
    "pr_base_ref": PR_BASE_REF,
    "pr_base_sha40": PR_BASE_SHA40,
    "pr_body_sha256": PR_BODY_SHA256,
    "pr_number": PR_NUMBER,
    "predecessor_adc_comment_id": TRACEABILITY_CORRECTION_ADC_COMMENT_ID,
    "predecessor_adc_sha256": TRACEABILITY_CORRECTION_ADC_SHA256,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "schema": READER_CONTINUATION_AUTH_SCHEMA,
    "starting_head_sha40": "b31cca21da15e18d0e1665827621700f7d774d0a",
}
READER_CONTINUATION_AUTH_FIELDS = frozenset(READER_CONTINUATION_AUTHORIZATION)
EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID = 6894441752
EXECUTION_RECEIPT_READER_CONTINUATION_ADC_SHA256 = "99dbd0f77ef19df5fb9da6bd02cd8b52235e8bfbb498734ca8846de165cda449"
EXECUTION_RECEIPT_READER_CONTINUATION_ADC_BYTES = 16073
EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_SCHEMA = (
    "PASES_ISSUE_PHASE_EVIDENCE_EXECUTION_RECEIPT_READER_CONTINUATION_V1"
)
EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_BYTES = 2204
EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256 = (
    "25bf67faf49da88b52120d06e5d6ac2cb8737ea1898f1a511c90f22bf07637da"
)
EXECUTION_RECEIPT_READER_CONTINUATION_ARTIFACT_IMPACT = (
    "## Artifact impact\n\n"
    "- Specification: `docs/specs/workflow-spec.md`.\n"
    "- Design: `docs/design/workflow-design.md`.\n"
    "- Testing: `docs/testing/pases-lifecycle-tests.md`, `docs/testing/traceability.md`."
)
EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION: dict[str, Any] = {
    "active_epoch_id": ACTIVE_EPOCH_ID,
    "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
    "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
    "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
    "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
    "applied_comment_id": 6889965335,
    "branch_ref": BRANCH_REF,
    "current_issue_body_sha256": ISSUE_BODY_SHA256,
    "followup_path_allowlist": [
        "dist/antigravity/docs/design/workflow-design.md",
        "dist/antigravity/docs/specs/workflow-spec.md",
        "dist/antigravity/runtime/p_ases/phase_rework.py",
        "dist/claude/docs/design/workflow-design.md",
        "dist/claude/docs/specs/workflow-spec.md",
        "dist/claude/runtime/p_ases/phase_rework.py",
        "dist/openai/docs/design/workflow-design.md",
        "dist/openai/docs/specs/workflow-spec.md",
        "dist/openai/runtime/p_ases/phase_rework.py",
        "docs/design/workflow-design.md",
        "docs/specs/workflow-spec.md",
        "docs/testing/pases-lifecycle-tests.md",
        "docs/testing/traceability.md",
        "runtime/p_ases/phase_rework.py",
        "tests/test_phase_rework.py",
    ],
    "frozen_base_ref": BASE_REF,
    "frozen_base_sha40": BASE_SHA40,
    "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
    "intent_comment_id": 6888474848,
    "issue_id": ISSUE_ID,
    "issue_number": ISSUE_NUMBER,
    "labels_at_start": ["enhancement", "kind:single", "phase:design"],
    "max_followup_commits": 1,
    "owner_id": OWNER_ID,
    "predecessor_adc_comment_id": READER_CONTINUATION_ADC_COMMENT_ID,
    "predecessor_adc_sha256": READER_CONTINUATION_ADC_SHA256,
    "pr_base_ref": PR_BASE_REF,
    "pr_base_sha40": PR_BASE_SHA40,
    "pr_body_sha256": PR_BODY_SHA256,
    "pr_number": PR_NUMBER,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "schema": EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_SCHEMA,
    "starting_head_sha40": "b5d3c005a5004e3d56103b17c48c13e7bca8e900",
}
EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_FIELDS = frozenset(
    EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION
)
MARKDOWN_PREDECESSOR_READER_ADC_COMMENT_ID = 6896448736
MARKDOWN_PREDECESSOR_READER_ADC_SHA256 = (
    "fa94892d653cc037195b8886073e94d06118675450559bf5adb6b7ba289eeade"
)
MARKDOWN_PREDECESSOR_READER_ADC_BYTES = 12453
MARKDOWN_PREDECESSOR_READER_AUTH_SCHEMA = (
    "PASES_ISSUE_PHASE_REWORK_MARKDOWN_PREDECESSOR_READER_V1"
)
MARKDOWN_PREDECESSOR_READER_AUTH_MARKER_BYTES = 2180
MARKDOWN_PREDECESSOR_READER_AUTH_MARKER_SHA256 = (
    "2bfcb609196f8dab167f42d209b9854fdec503ef91d625ce6e3845ba85b450e8"
)
MARKDOWN_PREDECESSOR_READER_ARTIFACT_IMPACT = (
    "## Artifact impact\n\n"
    "- Specification: `docs/specs/workflow-spec.md`.\n"
    "- Design: `docs/design/workflow-design.md`.\n"
    "- Testing: `docs/testing/pases-lifecycle-tests.md`, "
    "`docs/testing/traceability.md`."
)
MARKDOWN_PREDECESSOR_READER_AUTHORIZATION: dict[str, Any] = {
    "active_epoch_id": ACTIVE_EPOCH_ID,
    "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
    "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
    "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
    "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
    "applied_comment_id": 6889965335,
    "branch_ref": BRANCH_REF,
    "current_issue_body_sha256": ISSUE_BODY_SHA256,
    "followup_path_allowlist": [
        "dist/antigravity/docs/design/workflow-design.md",
        "dist/antigravity/docs/specs/workflow-spec.md",
        "dist/antigravity/runtime/p_ases/phase_rework.py",
        "dist/claude/docs/design/workflow-design.md",
        "dist/claude/docs/specs/workflow-spec.md",
        "dist/claude/runtime/p_ases/phase_rework.py",
        "dist/openai/docs/design/workflow-design.md",
        "dist/openai/docs/specs/workflow-spec.md",
        "dist/openai/runtime/p_ases/phase_rework.py",
        "docs/design/workflow-design.md",
        "docs/specs/workflow-spec.md",
        "docs/testing/pases-lifecycle-tests.md",
        "docs/testing/traceability.md",
        "runtime/p_ases/phase_rework.py",
        "tests/test_phase_rework.py",
    ],
    "frozen_base_ref": BASE_REF,
    "frozen_base_sha40": BASE_SHA40,
    "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
    "intent_comment_id": 6888474848,
    "issue_id": ISSUE_ID,
    "issue_number": ISSUE_NUMBER,
    "labels_at_start": ["enhancement", "kind:single", "phase:design"],
    "max_followup_commits": 1,
    "owner_id": OWNER_ID,
    "predecessor_adc_comment_id": EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID,
    "predecessor_adc_sha256": EXECUTION_RECEIPT_READER_CONTINUATION_ADC_SHA256,
    "pr_base_ref": PR_BASE_REF,
    "pr_base_sha40": PR_BASE_SHA40,
    "pr_body_sha256": PR_BODY_SHA256,
    "pr_number": PR_NUMBER,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "schema": MARKDOWN_PREDECESSOR_READER_AUTH_SCHEMA,
    "starting_head_sha40": "93477af0aefc22f5723c3de1e5fc7b8dade7ec21",
}
MARKDOWN_PREDECESSOR_READER_AUTH_FIELDS = frozenset(
    MARKDOWN_PREDECESSOR_READER_AUTHORIZATION
)
APPROVED_HISTORY_READER_ADC_COMMENT_ID = 6897385343
APPROVED_HISTORY_READER_ADC_SHA256 = (
    "eded3887c7a8eae192d4b27c2ccccd1a2adaef8a6d14ff821d12b0d8f7ad0ef7"
)
APPROVED_HISTORY_READER_ADC_BYTES = 18487
APPROVED_HISTORY_READER_AUTH_SCHEMA = (
    "PASES_ISSUE_PHASE_REWORK_APPROVED_HISTORY_READER_V1"
)
APPROVED_HISTORY_READER_AUTH_MARKER_BYTES = 4464
APPROVED_HISTORY_READER_AUTH_MARKER_SHA256 = (
    "c6ece509dcb63ccff8a383a02e163e3af9c4daabd06f0316b567abd5651d27d8"
)
APPROVED_HISTORY_READER_ARTIFACT_IMPACT = MARKDOWN_PREDECESSOR_READER_ARTIFACT_IMPACT
APPROVED_HISTORY_READER_AUTHORIZATION = json.loads(
    (
        '{"active_authorization_digests":{"continuation":"17c3144432b4c5a9310c58fc6274643970bfad3c30f698cd550'
        'd8ea851832dd3","execution_receipt_reader_continuation":"3af7439eb308e879c727942359e1e136c85e593e4701'
        '04e6211cafdc6295d11c","reader_continuation":"fff82a9ab1ab3f3138c064e2f99f820ae7af0da3f72657f98cacb5d'
        '5ba12e844","recovery":"c6b06e27cbd3dfc0b70d575caba2366380f8af6561fec239e2e75b900ad58f0c","rework":"c'
        'f4363631407e51b6c229d2b7d63eb318968e8af2966fce2d9938b8bc88eb7e9","timestamp_recovery":"880bf8227c978'
        '85a0782dbbc3074b45b49e6ff4a4225b63c8763cbbce02c7b86"},"active_epoch_id":"50af48a8a0d92f65f362ee37195'
        '9152de755ab7057604a47a9155e938357ee8a","active_epoch_sha256":"086a8e23601a869e4ec678a80ef82836c1cf76'
        'd50be13788658b02e037c51d00","active_phase_generation_comment_id":6881839877,"active_phase_generation'
        '_sha256":"133cba8d9fb815581de12552bac9d76cb634819d012513e9e3be086e4180a3c5","applied_body_sha256":"b'
        '8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18","applied_comment_id":6889965335,"ap'
        'proved_history":[{"byte_length":13519,"comment_id":6886911700,"sha256":"a3c171ab44bf2145aea25b9e43b3'
        '5fc235b04748e9ad2228847c7379f404e350","state":"approved"},{"byte_length":15113,"comment_id":68874297'
        '39,"sha256":"c4de9fc1308c63f0de3ba4b8269fa779d2c38688cf420c59031911d1522cb8e2","state":"approved"},{'
        '"byte_length":15501,"comment_id":6888665795,"sha256":"a12b71873e64a10f119a38df94e55c96c64d6cb1fc2e51'
        '0432cf7d40116c7e4f","state":"approved"},{"byte_length":15762,"comment_id":6890080277,"sha256":"5fe13'
        '2fba564d931da116bfa94f3a21efe2f35d943e790bf2087edf2423c52c5","state":"approved"},{"byte_length":9188'
        ',"comment_id":6891800412,"sha256":"ca22ada47ffb31479ccc57664052486808fa86de3eabf2c1fb5680ca33b05280"'
        ',"state":"approved"},{"byte_length":16060,"comment_id":6891926625,"sha256":"64c8d8d3ceb06f5e04d6c9eb'
        '780c0bb3a0607dc61440e136b00bcdf63cf941a8","state":"approved"},{"byte_length":9955,"comment_id":68933'
        '85802,"sha256":"65e5c9b928ce5b554ea16cf6fc8af2d1867018a0464d3247809c163e69ecd6ab","state":"approved"'
        '},{"byte_length":16823,"comment_id":6893557456,"sha256":"b19dca5243f90d96d013a432b41ece5892f39fc8217'
        'ebf63fccb8f0ada4fd81f","state":"approved"},{"byte_length":16073,"comment_id":6894441752,"sha256":"99'
        'dbd0f77ef19df5fb9da6bd02cd8b52235e8bfbb498734ca8846de165cda449","state":"approved"},{"byte_length":1'
        '2453,"comment_id":6896448736,"sha256":"fa94892d653cc037195b8886073e94d06118675450559bf5adb6b7ba289ee'
        'ade","state":"approved"},{"byte_length":14389,"comment_id":6896831619,"sha256":"fcf6bc9062565b0b5ce0'
        '35c99cee24c51a39116ce1cbc633c6b792f15281f684","state":"approved"}],"branch_ref":"pases/issue-71-loca'
        'l-activation-v2-phase-rebaseline-epoch-3","current_issue_body_sha256":"5f910c8de4cbe3ec391edf18b69fa'
        'be0f4c42880b59357083647a8b06e7a6a36","followup_path_allowlist":["dist/antigravity/docs/design/workfl'
        'ow-design.md","dist/antigravity/docs/specs/workflow-spec.md","dist/antigravity/runtime/p_ases/phase_'
        'rework.py","dist/claude/docs/design/workflow-design.md","dist/claude/docs/specs/workflow-spec.md","d'
        'ist/claude/runtime/p_ases/phase_rework.py","dist/openai/docs/design/workflow-design.md","dist/openai'
        '/docs/specs/workflow-spec.md","dist/openai/runtime/p_ases/phase_rework.py","docs/design/workflow-des'
        'ign.md","docs/specs/workflow-spec.md","docs/testing/pases-lifecycle-tests.md","docs/testing/traceabi'
        'lity.md","runtime/p_ases/phase_rework.py","tests/test_phase_rework.py"],"frozen_base_ref":"main","fr'
        'ozen_base_sha40":"07481c4b451a81750a6c2e1a6a18bdfd4e3459c2","history_predecessor_boundary":{"comment'
        '_id":6886739124,"sha256":"9c28ac5098565f74ffb5a74ece39a5a92c1264d793c2542b12e5d2efabc8c007"},"intent'
        '_body_sha256":"ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5","intent_comment_id"'
        ':6888474848,"issue_id":6135294757,"issue_number":71,"labels_at_start":["enhancement","kind:single","'
        'phase:design"],"max_followup_commits":1,"owner_id":3744776,"pr_base_ref":"main","pr_base_sha40":"074'
        '81c4b451a81750a6c2e1a6a18bdfd4e3459c2","pr_body_sha256":"12f3dc5d45a8ca9d1155a80608d05b31402acd0d39d'
        '33f61afeee844b93efff7","pr_number":75,"predecessor_adc_byte_length":14389,"predecessor_adc_comment_i'
        'd":6896831619,"predecessor_adc_sha256":"fcf6bc9062565b0b5ce035c99cee24c51a39116ce1cbc633c6b792f15281'
        'f684","repository":"puchinya/ai-agent-workflow","repository_id":1401910271,"schema":"PASES_ISSUE_PHA'
        'SE_REWORK_APPROVED_HISTORY_READER_V1","starting_head_sha40":"d1704c125d4de49e84ffffceb14756c9cc55596'
        '2"}'
    )
)
APPROVED_HISTORY_READER_AUTH_FIELDS = frozenset(
    APPROVED_HISTORY_READER_AUTHORIZATION
)
ISSUE71_PHASE_AND_USER_REVIEW_ADC_COMMENT_ID = 6902977193
ISSUE71_PHASE_AND_USER_REVIEW_ADC_SHA256 = (
    "ea7cf163c6f9811cd3b540f04c577bfa2aec4ef514fd3694532b1a1de02bce2c"
)
ISSUE71_PHASE_AND_USER_REVIEW_ADC_BYTES = 29876
ISSUE71_PHASE_AND_USER_REVIEW_SCHEMA = "PASES_ISSUE_PHASE_AND_USER_REVIEW_V1"
ISSUE71_PHASE_AND_USER_REVIEW_MARKER_FIELDS = frozenset({
    "active_authorization_digests", "active_epoch_id", "active_epoch_sha256",
    "active_phase_generation_comment_id", "active_phase_generation_sha256",
    "applied_body_sha256", "applied_comment_id", "approved_history", "branch_ref",
    "current_issue_body_sha256", "followup_path_allowlist", "frozen_base_ref",
    "frozen_base_sha40", "history_predecessor_boundary", "intent_body_sha256",
    "intent_comment_id", "issue71_user_review_authorization", "issue_id", "issue_number",
    "labels_at_start", "max_followup_commits", "owner_id", "phase_receipt_reconciliation",
    "pr_base_ref", "pr_base_sha40", "pr_body_sha256", "pr_number",
    "predecessor_adc_byte_length", "predecessor_adc_comment_id", "predecessor_adc_sha256",
    "repository", "repository_id", "schema", "starting_head_sha40",
})
ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_COMMENT_ID = 6904919120
ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_SHA256 = (
    "0cca59c49e16e8e2eacc2627cc9ea21667513d2123143ae6b2f641da74a5ac31"
)
ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_BYTES = 27420
ISSUE71_CURRENT_DOCUMENT_REISSUE_SCHEMA = "PASES_ISSUE_PHASE_AND_USER_REVIEW_V2"
ISSUE71_CURRENT_DOCUMENT_REISSUE_MARKER_BYTES = 10590
ISSUE71_CURRENT_DOCUMENT_REISSUE_MARKER_SHA256 = (
    "78409757fb2ffef2dbe1bf23a6206a8f03aee3e7e90cc18d800fb8e9332ab426"
)
ISSUE71_CURRENT_DOCUMENT_REISSUE_MARKER_FIELDS = (
    ISSUE71_PHASE_AND_USER_REVIEW_MARKER_FIELDS | {"historical_document_reissue_authorization"}
)
ISSUE71_COMPREHENSIVE_READER_ADC_COMMENT_ID = 6917910120
ISSUE71_COMPREHENSIVE_READER_ADC_SHA256 = (
    "fe89e0150761291fd07745feaf6d23e68fa4cef66f7ad7feb413254d5ba9a691"
)
ISSUE71_COMPREHENSIVE_READER_ADC_BYTES = 32793
ISSUE71_COMPREHENSIVE_READER_SCHEMA = "PASES_ISSUE_PHASE_AND_USER_REVIEW_V2"
ISSUE71_COMPREHENSIVE_READER_MARKER_BYTES = 13050
ISSUE71_COMPREHENSIVE_READER_MARKER_SHA256 = (
    "dc7cd4377d0bd0b4379e11cc6a6a1048a49ca5104e763bc6e45bf028c2d14df6"
)
ISSUE71_COMPREHENSIVE_READER_MARKER_FIELDS = (
    ISSUE71_CURRENT_DOCUMENT_REISSUE_MARKER_FIELDS | {"current_document_snapshot_authorization"}
)
ISSUE71_WINDOWS_PROFILE_READER_ADC_COMMENT_ID = 6919153830
ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256 = (
    "c3aa49e906479beb9989dcc7ada64a4aff7145545aefb8b7103e58870f32541d"
)
ISSUE71_WINDOWS_PROFILE_READER_ADC_BYTES = 28018
ISSUE71_WINDOWS_PROFILE_READER_SCHEMA = "PASES_ISSUE_PHASE_AND_USER_REVIEW_V2"
ISSUE71_WINDOWS_PROFILE_READER_MARKER_BYTES = 13135
ISSUE71_WINDOWS_PROFILE_READER_MARKER_SHA256 = (
    "83e4ef63098d51eeeb4442a8893c56974416418be257e432ee8d8faf30b2dc90"
)
ISSUE71_WINDOWS_PROFILE_READER_MARKER_FIELDS = ISSUE71_COMPREHENSIVE_READER_MARKER_FIELDS
ISSUE71_WINDOWS_FIXTURE_READER_ADC_COMMENT_ID = 6920550362
ISSUE71_WINDOWS_FIXTURE_READER_ADC_SHA256 = (
    "c2ace5524388354b2b78394d4cd7165070a1a858d4b71cff7440c628dcf45664"
)
ISSUE71_WINDOWS_FIXTURE_READER_ADC_BYTES = 25230
ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_COMMENT_ID = 6920296275
ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_SHA256 = (
    "c19f74bcfa893fad3b357b3d00c3fe212159db4021663d93c3fda82881414f94"
)
ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_BYTES = 25989
ISSUE71_WINDOWS_FIXTURE_READER_SCHEMA = "PASES_ISSUE_PHASE_AND_USER_REVIEW_V2"
ISSUE71_WINDOWS_FIXTURE_READER_MARKER_BYTES = 11499
ISSUE71_WINDOWS_FIXTURE_READER_MARKER_SHA256 = (
    "173b81a61d1d1e871e488e9ffc1fc494da1de3ff2d43e3c138e9f9da20c9c8e3"
)
ISSUE71_WINDOWS_FIXTURE_READER_MARKER_FIELDS = ISSUE71_WINDOWS_PROFILE_READER_MARKER_FIELDS
ISSUE71_CURRENT_COMBINED_SCHEMA = "PASES_ISSUE_PHASE_AND_USER_REVIEW_V2"
ISSUE71_CURRENT_COMBINED_MARKER_FIELDS = ISSUE71_WINDOWS_FIXTURE_READER_MARKER_FIELDS
ISSUE71_PHASE_AND_USER_REVIEW_V3_SCHEMA = "PASES_ISSUE_PHASE_AND_USER_REVIEW_V3"
TIMESTAMP_CONTINUATION_AUTH_SCHEMA = "PASES_ISSUE71_PHASE_REWORK_TIMESTAMP_CONTINUATION_V1"
TIMESTAMP_CONTINUATION_AUTH_SCHEMA_V2 = "PASES_ISSUE71_PHASE_REWORK_TIMESTAMP_CONTINUATION_V2"
TIMESTAMP_CONTINUATION_ORIGIN_ADC = (
    6963966853, "ea66f7e9504908391bec106fd1ce84ac1c2fd2b994880e9171aa34e8e3128cdf",
)
TIMESTAMP_CONTINUATION_ORIGIN_BYTES = 53083
TIMESTAMP_CONTINUATION_PHASE_REWORK_ORIGIN = {
    "adc_comment_id": 6963966853,
    "adc_sha256": "ea66f7e9504908391bec106fd1ce84ac1c2fd2b994880e9171aa34e8e3128cdf",
    "generation_authorization_sha256": "dfe3f08c122d9b070c2fcd861f0d4b3c316fc78d553de0232ee6d86acf907a97",
    "generation_number": 2,
    "intent": {
        "body_byte_length": 1939,
        "body_sha256": "90bef1741ed3c685d650a82f15550912cff9c77af1227f79d1747c3e606ffbb8",
        "comment_created_at": "2026-11-18T01:48:30Z",
        "comment_id": 6966536610,
        "event_time": "2026-11-18T01:43:35Z",
        "event_to_publication_delta_seconds": 295,
        "schema": "PASES_ISSUE_VERIFICATION_REWORK_INTENT_V3",
    },
    "applied": {
        "body_byte_length": 2060,
        "body_sha256": "9f60a9f13a8d5e10899ecedc661ada1ee67e3804cb26c454bf4625cf208312c6",
        "comment_created_at": "2026-11-18T01:51:53Z",
        "comment_id": 6966591228,
        "event_time": "2026-11-18T01:50:37Z",
        "event_to_publication_delta_seconds": 76,
        "schema": "PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V3",
    },
    "label_writes_already_performed": 1,
    "post_rework_phase": "requirements",
    "predecessor_v3_marker_byte_length": 33243,
    "predecessor_v3_marker_sha256": "37bf5bd793823b4302f12179ae8d1f3c3cde32a4d57d7a244321f45073a38066",
    "prior_v2_applied": {
        "body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "comment_id": 6889965335,
    },
    "prior_v2_intent": {
        "body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
        "comment_id": 6888474848,
    },
    "readiness_sha256": "ae86935f703d863ce7bc11b677ece78bce002f5492c5a6313b0450fb09026372",
    "readiness_subject_sha256": "4174e5412e284bf960730f42a76974ed122372bf796753739c95c5095b578c07",
    "recovery_mode": "read-only exact NOOP reconciliation; no further Intent, Applied, or label write",
    "v3_exact_readback_sha256": "36d7c9f35b39506d8cf076196f2568d01f6ea5d306da88e2beafd8ebcdeb6aa6",
    "v3_final_readback_blocker_sha256": "dd976cc6afd71f7606ff92afee104af16ae6d7a9ea1d1a1b74779476b87eaa49",
}
ISSUE71_PHASE_AND_USER_REVIEW_V3_FIELDS = frozenset({
    "active_authorization_digests", "active_epoch_id", "active_epoch_sha256",
    "active_phase_generation_comment_id", "active_phase_generation_sha256",
    "applied_body_sha256", "applied_comment_id", "approved_history",
    "batch_reader_authorization", "branch_ref", "current_document_snapshot_authorization",
    "current_issue_body_sha256", "followup_path_allowlist", "frozen_base_ref",
    "frozen_base_sha40", "historical_document_reissue_authorization",
    "history_predecessor_boundary", "intent_body_sha256", "intent_comment_id",
    "issue71_user_review_authorization", "issue_id", "issue_number", "labels_at_start",
    "max_followup_commits", "owner_id", "phase_receipt_reconciliation",
    "phase_rework_generation_authorization", "post_followup_document_authorization",
    "pr_base_ref", "pr_base_sha40", "pr_body_sha256", "pr_number",
    "predecessor_adc_byte_length", "predecessor_adc_comment_id", "predecessor_adc_sha256",
    "repository", "repository_id", "schema", "starting_head_sha40",
})
ISSUE71_REWORK_INTENT_V3_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_INTENT_V3"
ISSUE71_REWORK_APPLIED_V3_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V3"
ISSUE71_CURRENT_DOCUMENT_REISSUE_PATH_ALLOWLIST = (
    "dist/antigravity/runtime/p_ases/phase_evidence.py",
    "dist/antigravity/runtime/p_ases/phase_rework.py",
    "dist/claude/runtime/p_ases/phase_evidence.py",
    "dist/claude/runtime/p_ases/phase_rework.py",
    "dist/openai/runtime/p_ases/phase_evidence.py",
    "dist/openai/runtime/p_ases/phase_rework.py",
    "runtime/p_ases/phase_evidence.py",
    "runtime/p_ases/phase_rework.py",
    "tests/test_phase_evidence.py",
    "tests/test_phase_rework.py",
)
ISSUE71_COMPREHENSIVE_READER_PATH_ALLOWLIST = (
    "dist/antigravity/docs/design/workflow-design.md",
    "dist/antigravity/docs/specs/workflow-spec.md",
    "dist/antigravity/runtime/p_ases/cli.py",
    "dist/antigravity/runtime/p_ases/owner_authorization.py",
    "dist/antigravity/runtime/p_ases/phase_evidence.py",
    "dist/antigravity/runtime/p_ases/phase_rework.py",
    "dist/claude/docs/design/workflow-design.md",
    "dist/claude/docs/specs/workflow-spec.md",
    "dist/claude/runtime/p_ases/cli.py",
    "dist/claude/runtime/p_ases/owner_authorization.py",
    "dist/claude/runtime/p_ases/phase_evidence.py",
    "dist/claude/runtime/p_ases/phase_rework.py",
    "dist/openai/docs/design/workflow-design.md",
    "dist/openai/docs/specs/workflow-spec.md",
    "dist/openai/runtime/p_ases/cli.py",
    "dist/openai/runtime/p_ases/owner_authorization.py",
    "dist/openai/runtime/p_ases/phase_evidence.py",
    "dist/openai/runtime/p_ases/phase_rework.py",
    "docs/design/workflow-design.md",
    "docs/specs/workflow-spec.md",
    "docs/testing/pases-lifecycle-tests.md",
    "docs/testing/runtime-tests.md",
    "docs/testing/traceability.md",
    "runtime/p_ases/cli.py",
    "runtime/p_ases/owner_authorization.py",
    "runtime/p_ases/phase_evidence.py",
    "runtime/p_ases/phase_rework.py",
    "tests/test_owner_authorization.py",
    "tests/test_phase_evidence.py",
    "tests/test_phase_rework.py",
    "tests/test_user_review_cli.py",
)
ISSUE71_WINDOWS_PROFILE_READER_PATH_ALLOWLIST = (
    "dist/antigravity/docs/design/workflow-design.md",
    "dist/antigravity/docs/specs/workflow-spec.md",
    "dist/antigravity/runtime/p_ases/cli.py",
    "dist/antigravity/runtime/p_ases/owner_authorization.py",
    "dist/antigravity/runtime/p_ases/phase_rework.py",
    "dist/antigravity/runtime/p_ases/profile.py",
    "dist/claude/docs/design/workflow-design.md",
    "dist/claude/docs/specs/workflow-spec.md",
    "dist/claude/runtime/p_ases/cli.py",
    "dist/claude/runtime/p_ases/owner_authorization.py",
    "dist/claude/runtime/p_ases/phase_rework.py",
    "dist/claude/runtime/p_ases/profile.py",
    "dist/openai/docs/design/workflow-design.md",
    "dist/openai/docs/specs/workflow-spec.md",
    "dist/openai/runtime/p_ases/cli.py",
    "dist/openai/runtime/p_ases/owner_authorization.py",
    "dist/openai/runtime/p_ases/phase_rework.py",
    "dist/openai/runtime/p_ases/profile.py",
    "docs/design/workflow-design.md",
    "docs/specs/workflow-spec.md",
    "docs/testing/pases-lifecycle-tests.md",
    "docs/testing/runtime-tests.md",
    "docs/testing/traceability.md",
    "runtime/p_ases/cli.py",
    "runtime/p_ases/owner_authorization.py",
    "runtime/p_ases/phase_rework.py",
    "runtime/p_ases/profile.py",
    "tests/test_owner_authorization.py",
    "tests/test_phase_evidence.py",
    "tests/test_phase_rework.py",
    "tests/test_user_review_cli.py",
)
ISSUE71_WINDOWS_FIXTURE_READER_PATH_ALLOWLIST = (
    "dist/antigravity/runtime/p_ases/phase_rework.py",
    "dist/claude/runtime/p_ases/phase_rework.py",
    "dist/openai/runtime/p_ases/phase_rework.py",
    "runtime/p_ases/phase_rework.py",
    "tests/test_owner_authorization.py",
    "tests/test_phase_rework.py",
    "tests/test_user_review_cli.py",
)
ISSUE71_HISTORICAL_DOCUMENT_REISSUE_AUTHORIZATION: dict[str, Any] = json.loads(
    '{"branch_ref":"pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3",'
    '"cross_generation_digest_equality_required":false,'
    '"current_head_sha40":"c464ae659efaae856aad669d69c3bfe2389efd18",'
    '"current_phase_generation_comment_id":6889965335,'
    '"current_phase_generation_sha256":"b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",'
    '"current_source_document_digests":[{"path":"docs/design/workflow-design.md",'
    '"sha256":"0fe7e16ca5f358df081bca694fe08652c0da2ad33502430e8eb788e5639b4802"},'
    '{"path":"docs/specs/workflow-spec.md",'
    '"sha256":"dcfe53a34c7bec88174c5e73808e9dee4095cf8c8d238a42ff1eed43fd6faa78"}],'
    '"frozen_base_ref":"main",'
    '"frozen_base_sha40":"07481c4b451a81750a6c2e1a6a18bdfd4e3459c2",'
    '"historical_document_policy":"verify_exact_bytes_at_each_receipt_recorded_commit",'
    '"historical_receipt_adc_comment_id":6891926625,'
    '"historical_receipt_adc_sha256":"64c8d8d3ceb06f5e04d6c9eb780c0bb3a0607dc61440e136b00bcdf63cf941a8",'
    '"historical_receipt_commit_sha40":"b31cca21da15e18d0e1665827621700f7d774d0a",'
    '"historical_receipts":[{"body_sha256":"67402fbb84567844ef7399868d8aa09538526fe41b101cd00d362c60019cc5b9",'
    '"comment_id":6892886558,"documents":[{"path":"docs/design/workflow-design.md",'
    '"sha256":"f64c7dfc6ba43c0ac62c84dcbc21c560bdd34be4004fa24804b512b191b64450"}]},'
    '{"body_sha256":"ee9fba19f51b06f9ceae63e16bdac5ea54ac0f5b0bae72eef6eba397e64334ef",'
    '"comment_id":6892997518,"documents":[{"path":"docs/design/workflow-design.md",'
    '"sha256":"f64c7dfc6ba43c0ac62c84dcbc21c560bdd34be4004fa24804b512b191b64450"},'
    '{"path":"docs/specs/workflow-spec.md",'
    '"sha256":"4104666b05561b5b70caff0b0c26b7c9dea65d6811af78a1a51a7d0b58bff90c"}]}],'
    '"issue_number":71,"pr_base_ref":"main",'
    '"pr_base_sha40":"07481c4b451a81750a6c2e1a6a18bdfd4e3459c2",'
    '"pr_number":75,"reissue_document_policy":"bind_exact_current_committed_documents_at_current_pushed_head",'
    '"repository":"puchinya/ai-agent-workflow","repository_id":1401910271,'
    '"schema":"PASES_ISSUE71_HISTORICAL_DOCUMENT_REISSUE_V1"}'
)
ISSUE71_COMPREHENSIVE_CURRENT_DOCUMENT_SNAPSHOT_AUTHORIZATION: dict[str, Any] = {
    "branch_ref": BRANCH_REF,
    "current_source_document_digests": [
        {
            "path": "docs/design/workflow-design.md",
            "sha256": "83ab3a0acf3e8519c78dd194bc7162aeddcbcb44804ddfc2fbd910cd10065225",
        },
        {
            "path": "docs/specs/workflow-spec.md",
            "sha256": "aa1d050093af2f60d988d6db02af293254dbebafda903f805a96b5dba66f5ffa",
        },
    ],
    "issue_number": ISSUE_NUMBER,
    "repository_id": REPOSITORY_ID,
    "schema": "PASES_ISSUE71_CURRENT_DOCUMENT_SNAPSHOT_V1",
    "source_commit_policy": "exact_current_pushed_head",
}
ISSUE71_WINDOWS_PROFILE_CURRENT_DOCUMENT_SNAPSHOT_AUTHORIZATION: dict[str, Any] = {
    "branch_ref": BRANCH_REF,
    "current_source_document_digests": [
        {
            "path": "docs/design/workflow-design.md",
            "sha256": "25b2e1187d40e9816f5c9f3b3ab62954f4d436d82702ada25e8a69f2465ec960",
        },
        {
            "path": "docs/specs/workflow-spec.md",
            "sha256": "07055c992c9d1a49494cbb0077c2cd254ea1824e9a74e016fa9141a5a743f8fd",
        },
    ],
    "issue_number": ISSUE_NUMBER,
    "repository_id": REPOSITORY_ID,
    "schema": "PASES_ISSUE71_CURRENT_DOCUMENT_SNAPSHOT_V1",
    "source_commit_policy": "exact_current_pushed_head",
}
ISSUE71_CURRENT_DOCUMENT_REISSUE_ARTIFACT_IMPACT = (
    "- Runtime: `runtime/p_ases/phase_evidence.py`, `runtime/p_ases/phase_rework.py`.\n"
    "- Tests: `tests/test_phase_evidence.py`, `tests/test_phase_rework.py`.\n"
    "- Generated mirrors: the six matching `phase_evidence.py` and `phase_rework.py` paths under "
    "`dist/antigravity/runtime/p_ases/`, `dist/claude/runtime/p_ases/`, and "
    "`dist/openai/runtime/p_ases/` listed in the marker.\n"
    "- Canonical specification/design already describe historical-document verification and "
    "current-document binding; no canonical doc change is needed for this correction."
)
ISSUE71_COMPREHENSIVE_READER_ARTIFACT_IMPACT = (
    "- Specification: docs/specs/workflow-spec.md\n"
    "- Design: docs/design/workflow-design.md\n"
    "- Testing: docs/testing/pases-lifecycle-tests.md, docs/testing/runtime-tests.md, docs/testing/traceability.md\n"
    "- Status: evidence-only; exact-subject results are recorded through Issue #71 and PR #75 receipts.\n"
    "- Runtime implementation: runtime/p_ases/phase_rework.py, runtime/p_ases/phase_evidence.py, runtime/p_ases/cli.py, runtime/p_ases/owner_authorization.py\n"
    "- Tests: tests/test_phase_rework.py, tests/test_phase_evidence.py, tests/test_user_review_cli.py, tests/test_owner_authorization.py\n"
    "- Generated mirrors: the exact twelve runtime and six Specification/Design paths listed in the marker for Antigravity, Claude, and OpenAI."
)
ISSUE71_WINDOWS_PROFILE_READER_ARTIFACT_IMPACT = (
    "- Specification: docs/specs/workflow-spec.md\n"
    "- Design: docs/design/workflow-design.md\n"
    "- Testing: docs/testing/pases-lifecycle-tests.md, docs/testing/runtime-tests.md, docs/testing/traceability.md\n"
    "- Status: evidence-only; exact-subject results are recorded through Issue #71 and PR #75 receipts.\n"
    "- Runtime implementation: runtime/p_ases/profile.py, runtime/p_ases/cli.py, runtime/p_ases/owner_authorization.py, runtime/p_ases/phase_rework.py\n"
    "- Tests: tests/test_phase_rework.py, tests/test_phase_evidence.py, tests/test_user_review_cli.py, tests/test_owner_authorization.py\n"
    "- Generated mirrors: the exact twelve runtime and six Specification/Design paths listed in the marker for Antigravity, Claude, and OpenAI."
)
ISSUE71_WINDOWS_FIXTURE_READER_ARTIFACT_IMPACT = (
    "- Runtime: `runtime/p_ases/phase_rework.py`.\n"
    "- Tests: `tests/test_owner_authorization.py`, `tests/test_phase_rework.py`, and "
    "`tests/test_user_review_cli.py`.\n"
    "- Generated mirrors: `dist/antigravity/runtime/p_ases/phase_rework.py`, "
    "`dist/claude/runtime/p_ases/phase_rework.py`, and "
    "`dist/openai/runtime/p_ases/phase_rework.py`."
)
ISSUE71_PHASE_RECEIPT_AUTH_SCHEMA = "PASES_ISSUE_PHASE_RECEIPT_RECONCILIATION_AUTH_V1"
ISSUE71_PHASE_RECEIPT_AUTH_FIELDS = frozenset({
    "active_epoch_id", "active_epoch_sha256", "active_phase_generation_comment_id",
    "active_phase_generation_sha256", "applied_body_sha256", "applied_comment_id",
    "branch_ref", "followup_path_allowlist", "frozen_base_ref", "frozen_base_sha40",
    "historical_receipt_adc_comment_id", "historical_receipt_adc_sha256",
    "historical_receipt_commit_sha40", "historical_receipts", "intent_body_sha256",
    "intent_comment_id", "issue_body_sha256", "issue_id", "issue_number", "labels_at_start",
    "max_followup_commits", "owner_id", "permitted_current_adc_edges",
    "permitted_label_transitions", "pr_base_ref", "pr_base_sha40", "pr_body_sha256",
    "pr_number", "predecessor_adc_comment_id", "predecessor_adc_sha256",
    "historical_commit_segments", "reissue_edges",
    "repository", "repository_id", "schema", "starting_head_sha40",
})
ISSUE71_USER_REVIEW_AUTH_SCHEMA = "PASES_ISSUE71_SOLO_OWNER_USER_REVIEW_AUTH_V1"
ISSUE71_USER_REVIEW_AUTH_FIELDS = frozenset({
    "decision_carrier_issue_number", "decision_schema", "direct_chat_confirmation_required",
    "issue63_access", "issue_number", "max_decisions_per_session", "owner_id", "pr_number",
    "project_profile_sha256", "repository_id", "review_mode", "schema", "subject_fields",
})
ISSUE71_COMBINED_ADC_PREDECESSOR = (APPROVED_HISTORY_READER_ADC_COMMENT_ID,
                                    APPROVED_HISTORY_READER_ADC_SHA256)
ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY = (
    6886739124, "9c28ac5098565f74ffb5a74ece39a5a92c1264d793c2542b12e5d2efabc8c007",
)
ISSUE71_COMBINED_ADC_HISTORY = (
    (6886911700, "a3c171ab44bf2145aea25b9e43b35fc235b04748e9ad2228847c7379f404e350", 13519),
    (6887429739, "c4de9fc1308c63f0de3ba4b8269fa779d2c38688cf420c59031911d1522cb8e2", 15113),
    (6888665795, "a12b71873e64a10f119a38df94e55c96c64d6cb1fc2e510432cf7d40116c7e4f", 15501),
    (6890080277, "5fe132fba564d931da116bfa94f3a21efe2f35d943e790bf2087edf2423c52c5", 15762),
    (6891800412, "ca22ada47ffb31479ccc57664052486808fa86de3eabf2c1fb5680ca33b05280", 9188),
    (6891926625, "64c8d8d3ceb06f5e04d6c9eb780c0bb3a0607dc61440e136b00bcdf63cf941a8", 16060),
    (6893385802, "65e5c9b928ce5b554ea16cf6fc8af2d1867018a0464d3247809c163e69ecd6ab", 9955),
    (6893557456, "b19dca5243f90d96d013a432b41ece5892f39fc8217ebf63fccb8f0ada4fd81f", 16823),
    (6894441752, "99dbd0f77ef19df5fb9da6bd02cd8b52235e8bfbb498734ca8846de165cda449", 16073),
    (6896448736, "fa94892d653cc037195b8886073e94d06118675450559bf5adb6b7ba289eeade", 12453),
    (6896831619, "fcf6bc9062565b0b5ce035c99cee24c51a39116ce1cbc633c6b792f15281f684", 14389),
    (6897385343, "eded3887c7a8eae192d4b27c2ccccd1a2adaef8a6d14ff821d12b0d8f7ad0ef7", 18487),
)
ISSUE71_CURRENT_DOCUMENT_REISSUE_HISTORY = (
    *ISSUE71_COMBINED_ADC_HISTORY,
    (ISSUE71_PHASE_AND_USER_REVIEW_ADC_COMMENT_ID,
     ISSUE71_PHASE_AND_USER_REVIEW_ADC_SHA256,
     ISSUE71_PHASE_AND_USER_REVIEW_ADC_BYTES),
)
ISSUE71_COMPREHENSIVE_READER_HISTORY = (
    *ISSUE71_CURRENT_DOCUMENT_REISSUE_HISTORY,
    (ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_COMMENT_ID,
     ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_SHA256,
     ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_BYTES),
)
ISSUE71_WINDOWS_PROFILE_READER_HISTORY = (
    *ISSUE71_COMPREHENSIVE_READER_HISTORY,
    (ISSUE71_COMPREHENSIVE_READER_ADC_COMMENT_ID,
     ISSUE71_COMPREHENSIVE_READER_ADC_SHA256,
     ISSUE71_COMPREHENSIVE_READER_ADC_BYTES),
)
ISSUE71_WINDOWS_FIXTURE_READER_HISTORY = (
    *ISSUE71_WINDOWS_PROFILE_READER_HISTORY,
    (ISSUE71_WINDOWS_PROFILE_READER_ADC_COMMENT_ID,
     ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256,
     ISSUE71_WINDOWS_PROFILE_READER_ADC_BYTES),
    (ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_COMMENT_ID,
     ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_SHA256,
     ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_BYTES),
)
ISSUE71_COMBINED_FOLLOWUP_PATH_ALLOWLIST = (
    "dist/antigravity/docs/design/workflow-design.md",
    "dist/antigravity/docs/specs/workflow-spec.md",
    "dist/antigravity/runtime/p_ases/cli.py",
    "dist/antigravity/runtime/p_ases/owner_authorization.py",
    "dist/antigravity/runtime/p_ases/phase_evidence.py",
    "dist/antigravity/runtime/p_ases/phase_rework.py",
    "dist/claude/docs/design/workflow-design.md",
    "dist/claude/docs/specs/workflow-spec.md",
    "dist/claude/runtime/p_ases/cli.py",
    "dist/claude/runtime/p_ases/owner_authorization.py",
    "dist/claude/runtime/p_ases/phase_evidence.py",
    "dist/claude/runtime/p_ases/phase_rework.py",
    "dist/openai/docs/design/workflow-design.md",
    "dist/openai/docs/specs/workflow-spec.md",
    "dist/openai/runtime/p_ases/cli.py",
    "dist/openai/runtime/p_ases/owner_authorization.py",
    "dist/openai/runtime/p_ases/phase_evidence.py",
    "dist/openai/runtime/p_ases/phase_rework.py",
    "docs/design/workflow-design.md",
    "docs/specs/workflow-spec.md",
    "docs/testing/pases-lifecycle-tests.md",
    "docs/testing/runtime-tests.md",
    "docs/testing/traceability.md",
    "runtime/p_ases/cli.py",
    "runtime/p_ases/owner_authorization.py",
    "runtime/p_ases/phase_evidence.py",
    "runtime/p_ases/phase_rework.py",
    "tests/test_owner_authorization.py",
    "tests/test_p_ases_cli.py",
    "tests/test_phase_evidence.py",
    "tests/test_phase_rework.py",
    "tests/test_user_review_cli.py",
)
COMMON_FIELDS = frozenset({
    "repository", "repository_id", "issue_number", "issue_id", "adc_comment_id", "adc_sha256",
    "authorization_sha256", "predecessor_adc_comment_id", "predecessor_adc_sha256",
    "epoch_origin_adc_comment_id", "epoch_origin_adc_sha256", "active_epoch_id", "active_epoch_sha256",
    "active_phase_generation_comment_id", "active_phase_generation_sha256", "baseline_head_sha40",
    "bootstrap_head_sha40", "branch_ref", "pr_number", "pr_base_ref", "pr_base_sha40", "pr_head_sha40",
    "readiness_sha256", "readiness_subject_sha256", "issue_body_sha256", "labels_before", "labels_after",
    "from_phase", "to_phase", "max_applications", "owner_id", "executor_user_id",
})
INTENT_FIELDS = COMMON_FIELDS | {"schema", "created_at"}
APPLIED_FIELDS = COMMON_FIELDS | {"schema", "intent_comment_id", "intent_body_sha256", "applied_at"}
ISSUE71_REWORK_INTENT_V3_FIELDS = INTENT_FIELDS | {"generation_number"}
ISSUE71_REWORK_APPLIED_V3_FIELDS = APPLIED_FIELDS | {"generation_number"}


class PhaseReworkError(ValueError):
    """Issue #71 phase rework authorization, evidence, or journal is invalid."""


@dataclass(frozen=True)
class PhaseReworkRecord:
    comment_id: int
    schema: str
    payload: dict[str, Any]
    body: str
    actor_id: int
    created_at: str

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _Live:
    current_adc: VerifiedADC
    epoch: Any
    issue: dict[str, Any]
    labels: tuple[str, ...]
    branch_ref: str
    head_sha40: str
    pr: dict[str, Any]
    executor_user_id: int
    authorization_sha256: str
    root: Path
    recovery_authorization: dict[str, Any] | None = None
    recovery_authorization_sha256: str | None = None
    timestamp_recovery_authorization: dict[str, Any] | None = None
    timestamp_recovery_authorization_sha256: str | None = None
    continuation_authorization: dict[str, Any] | None = None
    continuation_authorization_sha256: str | None = None
    reader_continuation_authorization: dict[str, Any] | None = None
    reader_continuation_authorization_sha256: str | None = None
    execution_receipt_reader_continuation_authorization: dict[str, Any] | None = None
    execution_receipt_reader_continuation_authorization_sha256: str | None = None
    phase_rework_generation_authorization: dict[str, Any] | None = None
    phase_rework_generation_authorization_sha256: str | None = None
    phase_rework_origin_adc_comment_id: int | None = None
    phase_rework_origin_adc_sha256: str | None = None
    timestamp_policy: dict[str, Any] | None = None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PhaseReworkError("phase rework JSON contains duplicate fields")
        result[key] = value
    return result


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise PhaseReworkError(f"{label} must be a lowercase SHA-256")
    return value


def _strict_utc(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PhaseReworkError(f"{label} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PhaseReworkError(f"{label} is malformed") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed) or parsed.isoformat(timespec="seconds") != value[:-1] + "+00:00":
        raise PhaseReworkError(f"{label} must be canonical UTC")
    return value


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_authorization(verified: VerifiedADC) -> tuple[dict[str, Any], str]:
    if (verified.pointer.state == "approved"
            and verified.pointer.comment_id == RECOVERY_ADC_COMMENT_ID
            and verified.contract.sha256 == RECOVERY_ADC_SHA256
            and verified.contract.byte_length == RECOVERY_ADC_BYTES
            and verified.contract.repository.casefold() == REPOSITORY.casefold()):
        text = verified.contract.content.decode("utf-8", errors="strict")
        start_marker = f"<!-- {RECOVERY_AUTH_SCHEMA}\n"
        if text.count(start_marker) != 1:
            raise PhaseReworkError("current recovery ADC must contain exactly one recovery authorization marker")
        start = text.index(start_marker)
        close = text.find("\n-->", start + len(start_marker))
        if close < 0:
            raise PhaseReworkError("recovery authorization marker is incomplete")
        raw = text[start + len(start_marker):close]
        try:
            value = json.loads(raw, object_pairs_hook=_pairs)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PhaseReworkError("recovery authorization JSON is malformed") from exc
        marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
        if (len(marker_bytes) != RECOVERY_AUTH_MARKER_BYTES
                or hashlib.sha256(marker_bytes).hexdigest() != RECOVERY_AUTH_MARKER_SHA256):
            raise PhaseReworkError("recovery authorization bytes differ from the exact approved marker")
        if not isinstance(value, dict) or set(value) != RECOVERY_AUTH_FIELDS:
            raise PhaseReworkError("recovery authorization has unknown fields")
        if value != RECOVERY_AUTHORIZATION:
            raise PhaseReworkError("recovery authorization differs from the exact pending Intent tuple")
        predecessor = re.search(
            r"^Predecessor ADC: Issue #71 comment #(\d+), SHA-256 ([0-9a-f]{64})$", text, re.M,
        )
        if (predecessor is None or int(predecessor.group(1)) != REWORK_ADC_COMMENT_ID
                or predecessor.group(2) != REWORK_ADC_SHA256):
            raise PhaseReworkError("recovery ADC predecessor declaration differs from its exact pointer")
        return value, hashlib.sha256(marker_bytes).hexdigest()
    if (verified.pointer.state != "approved" or verified.pointer.comment_id != REWORK_ADC_COMMENT_ID
            or verified.contract.sha256 != REWORK_ADC_SHA256
            or verified.contract.byte_length != REWORK_ADC_BYTES
            or verified.contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("current approved ADC differs from the exact Issue #71 rework contract")
    text = verified.contract.content.decode("utf-8", errors="strict")
    start_marker = f"<!-- {AUTH_SCHEMA}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError("current ADC must contain exactly one rework authorization marker")
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0:
        raise PhaseReworkError("rework authorization marker is incomplete")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("rework authorization JSON is malformed") from exc
    if not isinstance(value, dict) or set(value) != AUTH_FIELDS or _canonical(value) != raw:
        raise PhaseReworkError("rework authorization has unknown fields or noncanonical JSON")
    if value != AUTHORIZATION:
        raise PhaseReworkError("rework authorization does not match its exact Issue #71 tuple")
    predecessor = re.search(
        r"^Predecessor ADC: Issue #71 comment #(\d+), SHA-256 ([0-9a-f]{64})$", text, re.M,
    )
    if (predecessor is None or int(predecessor.group(1)) != PREDECESSOR_ADC_COMMENT_ID
            or predecessor.group(2) != PREDECESSOR_ADC_SHA256):
        raise PhaseReworkError("current ADC predecessor declaration differs from the exact approved pointer")
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    return value, hashlib.sha256(marker_bytes).hexdigest()


def parse_timestamp_recovery_authorization(verified: VerifiedADC) -> tuple[dict[str, Any], str]:
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id != TIMESTAMP_RECOVERY_ADC_COMMENT_ID
            or verified.contract.sha256 != TIMESTAMP_RECOVERY_ADC_SHA256
            or verified.contract.byte_length != TIMESTAMP_RECOVERY_ADC_BYTES
            or verified.contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("current timestamp-recovery ADC differs from its exact approved tuple")
    text = verified.contract.content.decode("utf-8", errors="strict")
    start_marker = f"<!-- {TIMESTAMP_RECOVERY_AUTH_SCHEMA}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError("current timestamp-recovery ADC must contain one authorization marker")
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0:
        raise PhaseReworkError("timestamp-recovery authorization marker is incomplete")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("timestamp-recovery authorization JSON is malformed") from exc
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    if (len(marker_bytes) != TIMESTAMP_RECOVERY_AUTH_MARKER_BYTES
            or hashlib.sha256(marker_bytes).hexdigest() != TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256):
        raise PhaseReworkError("timestamp-recovery marker bytes differ from the exact approved marker")
    if (not isinstance(value, dict) or set(value) != TIMESTAMP_RECOVERY_AUTH_FIELDS
            or value != TIMESTAMP_RECOVERY_AUTHORIZATION):
        raise PhaseReworkError("timestamp-recovery marker differs from its exact tuple")
    predecessor = re.search(
        r"^Predecessor ADC: Issue #71 comment #(\d+), SHA-256 ([0-9a-f]{64})$", text, re.M,
    )
    if (predecessor is None or int(predecessor.group(1)) != RECOVERY_ADC_COMMENT_ID
            or predecessor.group(2) != RECOVERY_ADC_SHA256):
        raise PhaseReworkError("timestamp-recovery ADC predecessor differs from its exact pointer")
    return value, hashlib.sha256(marker_bytes).hexdigest()


def _validate_adc_predecessor(text: str, comment_id: int, digest: str, label: str,
                              *, allow_inline_code: bool = False) -> None:
    digest_pattern = r"([0-9a-f]{64})"
    if allow_inline_code:
        digest_pattern = r"([0-9a-f]{64}|`[0-9a-f]{64}`)"
    predecessor = re.search(
        rf"^Predecessor ADC: Issue #71 comment #(\d+), SHA-256 {digest_pattern}$", text, re.M,
    )
    declared_digest = predecessor.group(2) if predecessor is not None else None
    if allow_inline_code and isinstance(declared_digest, str) and declared_digest.startswith("`"):
        declared_digest = declared_digest[1:-1]
    if (predecessor is None or int(predecessor.group(1)) != comment_id
            or declared_digest != digest):
        raise PhaseReworkError(f"{label} predecessor declaration differs from its exact approved pointer")


def parse_path_correction_generation(verified: VerifiedADC) -> None:
    """Validate the immutable ADC generation that corrected the artifact paths."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id != PATH_CORRECTION_ADC_COMMENT_ID
            or contract.sha256 != PATH_CORRECTION_ADC_SHA256
            or contract.byte_length != PATH_CORRECTION_ADC_BYTES
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("path-correction ADC differs from its exact approved generation")
    text = contract.content.decode("utf-8", errors="strict")
    _validate_adc_predecessor(
        text, TIMESTAMP_RECOVERY_ADC_COMMENT_ID, TIMESTAMP_RECOVERY_ADC_SHA256,
        "path-correction ADC",
    )
    if text.count(PATH_CORRECTION_ARTIFACT_IMPACT) != 1:
        raise PhaseReworkError("path-correction ADC does not declare the exact corrected Artifact impact paths")


def parse_continuation_authorization(verified: VerifiedADC) -> tuple[dict[str, Any], str]:
    """Parse the one exact continuation marker authorized by the current ADC."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id != CONTINUATION_ADC_COMMENT_ID
            or contract.sha256 != CONTINUATION_ADC_SHA256
            or contract.byte_length != CONTINUATION_ADC_BYTES
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("current continuation ADC differs from its exact approved generation")
    text = contract.content.decode("utf-8", errors="strict")
    start_marker = f"<!-- {CONTINUATION_AUTH_SCHEMA}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError("current continuation ADC must contain exactly one authorization marker")
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0:
        raise PhaseReworkError("continuation authorization marker is incomplete")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("continuation authorization JSON is malformed") from exc
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    if (len(marker_bytes) != CONTINUATION_AUTH_MARKER_BYTES
            or hashlib.sha256(marker_bytes).hexdigest() != CONTINUATION_AUTH_MARKER_SHA256):
        raise PhaseReworkError("continuation authorization bytes differ from the exact approved marker")
    if (not isinstance(value, dict) or set(value) != CONTINUATION_AUTH_FIELDS
            or _canonical(value) != raw or value != CONTINUATION_AUTHORIZATION):
        raise PhaseReworkError("continuation authorization differs from its exact canonical tuple")
    _validate_adc_predecessor(
        text, PATH_CORRECTION_ADC_COMMENT_ID, PATH_CORRECTION_ADC_SHA256,
        "continuation ADC",
    )
    if text.count(CONTINUATION_ARTIFACT_IMPACT) != 1:
        raise PhaseReworkError("continuation ADC does not declare the exact corrected Artifact impact paths")
    return value, hashlib.sha256(marker_bytes).hexdigest()


def parse_traceability_source_correction_generation(verified: VerifiedADC) -> None:
    """Validate the immutable documentation-only ADC between the two reader generations."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id != TRACEABILITY_CORRECTION_ADC_COMMENT_ID
            or contract.sha256 != TRACEABILITY_CORRECTION_ADC_SHA256
            or contract.byte_length != TRACEABILITY_CORRECTION_ADC_BYTES
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("traceability-correction ADC differs from its exact approved generation")
    text = contract.content.decode("utf-8", errors="strict")
    _validate_adc_predecessor(
        text, CONTINUATION_ADC_COMMENT_ID, CONTINUATION_ADC_SHA256,
        "traceability-correction ADC",
    )


def parse_reader_continuation_authorization(verified: VerifiedADC) -> tuple[dict[str, Any], str]:
    """Parse the exact approved marker that appends one reader-correction commit."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id != READER_CONTINUATION_ADC_COMMENT_ID
            or contract.sha256 != READER_CONTINUATION_ADC_SHA256
            or contract.byte_length != READER_CONTINUATION_ADC_BYTES
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("current reader-continuation ADC differs from its exact approved generation")
    text = contract.content.decode("utf-8", errors="strict")
    start_marker = f"<!-- {READER_CONTINUATION_AUTH_SCHEMA}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError("reader-continuation ADC must contain exactly one authorization marker")
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0:
        raise PhaseReworkError("reader-continuation authorization marker is incomplete")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("reader-continuation authorization JSON is malformed") from exc
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    if (len(marker_bytes) != READER_CONTINUATION_AUTH_MARKER_BYTES
            or hashlib.sha256(marker_bytes).hexdigest() != READER_CONTINUATION_AUTH_MARKER_SHA256):
        raise PhaseReworkError("reader-continuation marker bytes differ from the exact approved marker")
    if (not isinstance(value, dict) or set(value) != READER_CONTINUATION_AUTH_FIELDS
            or _canonical(value) != raw or value != READER_CONTINUATION_AUTHORIZATION):
        raise PhaseReworkError("reader-continuation marker differs from its exact canonical tuple")
    _validate_adc_predecessor(
        text, TRACEABILITY_CORRECTION_ADC_COMMENT_ID, TRACEABILITY_CORRECTION_ADC_SHA256,
        "reader-continuation ADC",
    )
    if text.count(READER_CONTINUATION_ARTIFACT_IMPACT) != 1:
        raise PhaseReworkError("reader-continuation ADC does not declare the exact Artifact impact paths")
    return value, hashlib.sha256(marker_bytes).hexdigest()


def parse_execution_receipt_reader_continuation_authorization(
    verified: VerifiedADC,
) -> tuple[dict[str, Any], str]:
    """Parse the exact approved marker that appends one execution-receipt reader commit."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id != EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID
            or contract.sha256 != EXECUTION_RECEIPT_READER_CONTINUATION_ADC_SHA256
            or contract.byte_length != EXECUTION_RECEIPT_READER_CONTINUATION_ADC_BYTES
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError(
            "current execution-receipt reader ADC differs from its exact approved generation"
        )
    text = contract.content.decode("utf-8", errors="strict")
    start_marker = f"<!-- {EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_SCHEMA}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError(
            "execution-receipt reader ADC must contain exactly one authorization marker"
        )
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0:
        raise PhaseReworkError("execution-receipt reader authorization marker is incomplete")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("execution-receipt reader authorization JSON is malformed") from exc
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    if (len(marker_bytes) != EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_BYTES
            or hashlib.sha256(marker_bytes).hexdigest()
            != EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256):
        raise PhaseReworkError(
            "execution-receipt reader marker bytes differ from the exact approved marker"
        )
    if (not isinstance(value, dict)
            or set(value) != EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_FIELDS
            or _canonical(value) != raw
            or value != EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION):
        raise PhaseReworkError(
            "execution-receipt reader marker differs from its exact canonical tuple"
        )
    _validate_adc_predecessor(
        text, READER_CONTINUATION_ADC_COMMENT_ID, READER_CONTINUATION_ADC_SHA256,
        "execution-receipt reader ADC", allow_inline_code=True,
    )
    if text.count(EXECUTION_RECEIPT_READER_CONTINUATION_ARTIFACT_IMPACT) != 1:
        raise PhaseReworkError(
            "execution-receipt reader ADC does not declare the exact Artifact impact paths"
        )
    return value, hashlib.sha256(marker_bytes).hexdigest()


def _adc_predecessor_header(text: str, label: str) -> tuple[int, str]:
    section = re.search(r"(?m)^##[ \t]", text)
    preamble = text if section is None else text[:section.start()]
    headers = [line for line in text.splitlines() if line.startswith("Predecessor ADC:")]
    preamble_headers = [line for line in preamble.splitlines()
                        if line.startswith("Predecessor ADC:")]
    if len(headers) != 1 or len(preamble_headers) != 1:
        raise PhaseReworkError(f"{label} must have exactly one predecessor header")
    match = re.fullmatch(
        r"Predecessor ADC: Issue #71 comment #([0-9]+), SHA-256 "
        r"(?:([0-9a-f]{64})|`([0-9a-f]{64})`)( {0}| {2})",
        headers[0],
    )
    if match is None:
        raise PhaseReworkError(f"{label} predecessor header is malformed")
    return int(match.group(1)), match.group(2) or match.group(3)


def _optional_historical_adc_predecessor_header(
    text: str, label: str, verified_body_byte_length: int,
) -> tuple[int, str] | None:
    """Validate an optional body-level link and exact byte annotation on immutable ADC history."""
    lines = text.splitlines()
    if not any(line.startswith("Predecessor ADC:") for line in lines):
        return None
    if (type(verified_body_byte_length) is not int or verified_body_byte_length < 1
            or len(text.encode("utf-8")) != verified_body_byte_length):
        raise PhaseReworkError(f"{label} verified body byte length is inconsistent")
    section = re.search(r"(?m)^##[ \t]", text)
    preamble = text if section is None else text[:section.start()]
    headers = [line for line in lines if line.startswith("Predecessor ADC:")]
    preamble_headers = [line for line in preamble.splitlines()
                        if line.startswith("Predecessor ADC:")]
    if len(headers) != 1 or len(preamble_headers) != 1:
        raise PhaseReworkError(f"{label} must have exactly one predecessor header")
    match = re.fullmatch(
        r"Predecessor ADC: Issue #71 comment #([0-9]+), SHA-256 "
        r"(?:([0-9a-f]{64})|`([0-9a-f]{64})`)"
        r"(?: \(((?:[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)) bytes\))?"
        r"( {0}| {2})",
        headers[0],
    )
    if match is None:
        raise PhaseReworkError(f"{label} predecessor header is malformed")
    annotation = re.search(r" \(([^()]*) bytes\)(?: {0}| {2})$", headers[0])
    if annotation is not None:
        annotated = int(annotation.group(1).replace(",", ""))
        if annotated != verified_body_byte_length:
            raise PhaseReworkError(f"{label} predecessor byte annotation differs from verified body length")
    return int(match.group(1)), match.group(2) or match.group(3)


def parse_markdown_predecessor_reader_authorization(
    verified: VerifiedADC,
) -> tuple[dict[str, Any], str]:
    """Strictly parse the predecessor-reader ADC when it is the current pointer."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id != MARKDOWN_PREDECESSOR_READER_ADC_COMMENT_ID
            or contract.sha256 != MARKDOWN_PREDECESSOR_READER_ADC_SHA256
            or contract.byte_length != MARKDOWN_PREDECESSOR_READER_ADC_BYTES
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError(
            "current Markdown predecessor reader ADC differs from its exact approved generation"
        )
    text = contract.content.decode("utf-8", errors="strict")
    start_marker = f"<!-- {MARKDOWN_PREDECESSOR_READER_AUTH_SCHEMA}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError(
            "Markdown predecessor reader ADC must contain exactly one authorization marker"
        )
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0:
        raise PhaseReworkError("Markdown predecessor reader authorization marker is incomplete")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("Markdown predecessor reader authorization JSON is malformed") from exc
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    if (len(marker_bytes) != MARKDOWN_PREDECESSOR_READER_AUTH_MARKER_BYTES
            or hashlib.sha256(marker_bytes).hexdigest()
            != MARKDOWN_PREDECESSOR_READER_AUTH_MARKER_SHA256):
        raise PhaseReworkError(
            "Markdown predecessor reader marker bytes differ from the exact approved marker"
        )
    if (not isinstance(value, dict)
            or set(value) != MARKDOWN_PREDECESSOR_READER_AUTH_FIELDS
            or _canonical(value) != raw
            or value != MARKDOWN_PREDECESSOR_READER_AUTHORIZATION):
        raise PhaseReworkError(
            "Markdown predecessor reader marker differs from its exact canonical tuple"
        )
    if _adc_predecessor_header(text, "Markdown predecessor reader ADC") != (
            EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID,
            EXECUTION_RECEIPT_READER_CONTINUATION_ADC_SHA256):
        raise PhaseReworkError(
            "Markdown predecessor reader ADC predecessor differs from its exact pointer"
        )
    if text.count(MARKDOWN_PREDECESSOR_READER_ARTIFACT_IMPACT) != 1:
        raise PhaseReworkError(
            "Markdown predecessor reader ADC does not declare the exact Artifact impact paths"
        )
    return value, hashlib.sha256(marker_bytes).hexdigest()


def parse_approved_history_reader_authorization(
    verified: VerifiedADC,
) -> tuple[dict[str, Any], str]:
    """Strictly parse the current ADC marker that authorizes generic history validation."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id != APPROVED_HISTORY_READER_ADC_COMMENT_ID
            or verified.pointer.sha256 != APPROVED_HISTORY_READER_ADC_SHA256
            or contract.sha256 != APPROVED_HISTORY_READER_ADC_SHA256
            or contract.byte_length != APPROVED_HISTORY_READER_ADC_BYTES
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError(
            "current approved-history reader ADC differs from its exact approved generation"
        )
    text = contract.content.decode("utf-8", errors="strict")
    start_marker = f"<!-- {APPROVED_HISTORY_READER_AUTH_SCHEMA}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError(
            "current approved-history reader ADC must contain exactly one authorization marker"
        )
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0:
        raise PhaseReworkError("approved-history authorization marker is incomplete")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("approved-history authorization JSON is malformed") from exc
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    if (len(marker_bytes) != APPROVED_HISTORY_READER_AUTH_MARKER_BYTES
            or hashlib.sha256(marker_bytes).hexdigest()
            != APPROVED_HISTORY_READER_AUTH_MARKER_SHA256):
        raise PhaseReworkError(
            "approved-history authorization marker differs from its exact approved bytes"
        )
    if (not isinstance(value, dict)
            or set(value) != APPROVED_HISTORY_READER_AUTH_FIELDS
            or _canonical(value) != raw
            or value != APPROVED_HISTORY_READER_AUTHORIZATION):
        raise PhaseReworkError(
            "approved-history authorization differs from its exact canonical tuple"
        )
    if _adc_predecessor_header(text, "approved-history reader ADC") != (
            APPROVED_HISTORY_READER_AUTHORIZATION["predecessor_adc_comment_id"],
            APPROVED_HISTORY_READER_AUTHORIZATION["predecessor_adc_sha256"]):
        raise PhaseReworkError(
            "approved-history reader ADC predecessor differs from its exact approved pointer"
        )
    if text.count(APPROVED_HISTORY_READER_ARTIFACT_IMPACT) != 1:
        raise PhaseReworkError(
            "approved-history reader ADC does not declare the exact Artifact impact paths"
        )
    active_authorization_digests = {
        "continuation": hashlib.sha256(_canonical(CONTINUATION_AUTHORIZATION).encode("utf-8")).hexdigest(),
        "execution_receipt_reader_continuation": hashlib.sha256(
            _canonical(EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION).encode("utf-8")
        ).hexdigest(),
        "reader_continuation": hashlib.sha256(
            _canonical(READER_CONTINUATION_AUTHORIZATION).encode("utf-8")
        ).hexdigest(),
        "recovery": hashlib.sha256(_canonical(RECOVERY_AUTHORIZATION).encode("utf-8")).hexdigest(),
        "rework": hashlib.sha256(_canonical(AUTHORIZATION).encode("utf-8")).hexdigest(),
        "timestamp_recovery": hashlib.sha256(
            _canonical(TIMESTAMP_RECOVERY_AUTHORIZATION).encode("utf-8")
        ).hexdigest(),
    }
    if value["active_authorization_digests"] != active_authorization_digests:
        raise PhaseReworkError(
            "approved-history marker does not bind the exact active authorization tuples"
        )
    return value, hashlib.sha256(marker_bytes).hexdigest()


def _verify_approved_history_reader_chain(
    github: GitHub, current: VerifiedADC, authorization: Mapping[str, Any],
) -> tuple[VerifiedADC, ...]:
    try:
        chain = verify_adc_forward_generations(
            github, ISSUE_NUMBER,
            prior_comment_id=PREDECESSOR_ADC_COMMENT_ID,
            prior_sha256=PREDECESSOR_ADC_SHA256,
            current_comment_id=APPROVED_HISTORY_READER_ADC_COMMENT_ID,
            current_sha256=APPROVED_HISTORY_READER_ADC_SHA256,
        )
    except ADCError as exc:
        raise PhaseReworkError(f"approved ADC history readback failed: {exc}") from exc
    expected_history = authorization["approved_history"]
    if not isinstance(expected_history, list) or not expected_history:
        raise PhaseReworkError("approved ADC history authorization must contain prior generations")
    for item in chain:
        pointer = item.pointer
        contract = item.contract
        content = contract.content
        if (pointer.state != "approved" or pointer.sha256 != contract.sha256
                or contract.repository.casefold() != REPOSITORY.casefold()
                or len(content) != contract.byte_length):
            raise PhaseReworkError(
                f"approved ADC history body or pointer readback differs at comment #{pointer.comment_id}"
            )
    actual_history = [
        {
            "byte_length": item.contract.byte_length,
            "comment_id": item.pointer.comment_id,
            "sha256": item.contract.sha256,
            "state": item.pointer.state,
        }
        for item in chain[:-1]
    ]
    current_entry = {
        "byte_length": current.contract.byte_length,
        "comment_id": current.pointer.comment_id,
        "sha256": current.contract.sha256,
        "state": current.pointer.state,
    }
    expected_current = {
        "byte_length": APPROVED_HISTORY_READER_ADC_BYTES,
        "comment_id": APPROVED_HISTORY_READER_ADC_COMMENT_ID,
        "sha256": APPROVED_HISTORY_READER_ADC_SHA256,
        "state": "approved",
    }
    if (actual_history != expected_history or current_entry != expected_current
            or not chain or chain[-1].pointer != current.pointer):
        raise PhaseReworkError(
            "approved ADC history is missing, reordered, changed, unapproved, or not current"
        )
    previous = authorization["history_predecessor_boundary"]
    for item, expected in zip(chain, [previous, *expected_history]):
        text = item.contract.content.decode("utf-8", errors="strict")
        if _adc_predecessor_header(text, f"historical ADC #{item.pointer.comment_id}") != (
                expected["comment_id"], expected["sha256"]):
            raise PhaseReworkError(
                f"historical ADC #{item.pointer.comment_id} predecessor link differs from its exact chain"
            )
        previous = {"comment_id": item.pointer.comment_id, "sha256": item.contract.sha256}
    return chain



def _has_issue71_current_combined_marker(verified: VerifiedADC) -> bool:
    try:
        content = verified.contract.content.decode("utf-8", errors="strict")
    except (AttributeError, UnicodeError):
        return False
    return (f"<!-- {ISSUE71_CURRENT_COMBINED_SCHEMA}\n" in content
            or f"<!-- {ISSUE71_PHASE_AND_USER_REVIEW_V3_SCHEMA}\n" in content)


def _has_issue71_timestamp_continuation_marker(verified: VerifiedADC) -> bool:
    try:
        content = verified.contract.content.decode("utf-8", errors="strict")
    except (AttributeError, UnicodeError):
        return False
    return any(f"<!-- {schema}\n" in content
               for schema in (TIMESTAMP_CONTINUATION_AUTH_SCHEMA,
                              TIMESTAMP_CONTINUATION_AUTH_SCHEMA_V2))


def parse_timestamp_continuation_authorization(
    verified: VerifiedADC,
) -> tuple[dict[str, Any], str]:
    """Parse the exact current approved marker using its declared lineage and scope."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.comment_id < 1
            or verified.pointer.sha256 != contract.sha256
            or contract.byte_length != len(contract.content)
            or hashlib.sha256(contract.content).hexdigest() != contract.sha256
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("current timestamp-continuation ADC differs from its approved bytes")
    text = contract.content.decode("utf-8", errors="strict")
    schemas = (TIMESTAMP_CONTINUATION_AUTH_SCHEMA, TIMESTAMP_CONTINUATION_AUTH_SCHEMA_V2)
    markers = [(schema, f"<!-- {schema}\n") for schema in schemas
               if text.count(f"<!-- {schema}\n") == 1]
    total_markers = sum(text.count(f"<!-- {schema}\n") for schema in schemas)
    if len(markers) != 1 or total_markers != 1:
        raise PhaseReworkError("timestamp-continuation ADC must contain one supported authorization marker")
    marker_schema, start_marker = markers[0]
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0 or text[close + len("\n-->"):].strip():
        raise PhaseReworkError("timestamp-continuation marker is incomplete or not terminal")
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("timestamp-continuation marker JSON is malformed") from exc
    if _canonical(value) != raw:
        raise PhaseReworkError("timestamp-continuation marker JSON is not canonical")
    expected_fields = {
        "approved_history", "branch_ref", "checkpoint_before_publication",
        "current_adc_predecessor", "current_head_sha40", "current_issue", "current_pr",
        "followup_commit_authorization", "history_boundary", "issue_number",
        "max_same_head_binding_checkpoint_pairs",
        "no_admin_ruleset_activation_issue63_merge_release_tag_or_issue_close", "owner_id",
        "phase_edges", "phase_reissue_policy", "phase_rework_origin",
        "pr_binding_before_publication", "repository", "repository_id",
        "required_gates_after_followup_head", "reviewer_checklist_count", "schema",
        "timestamp_policy", "user_review", "v2_record_immutability", "v3_record_immutability",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise PhaseReworkError("timestamp-continuation marker fields are incomplete or unknown")
    if (value.get("schema") != marker_schema
            or value.get("repository") != REPOSITORY
            or value.get("repository_id") != REPOSITORY_ID
            or value.get("owner_id") != OWNER_ID
            or value.get("issue_number") != ISSUE_NUMBER
            or value.get("branch_ref") != BRANCH_REF
            or type(value.get("reviewer_checklist_count")) is not int
            or not 1 <= value["reviewer_checklist_count"] <= 100
            or value.get("max_same_head_binding_checkpoint_pairs") != 1
            or value.get("no_admin_ruleset_activation_issue63_merge_release_tag_or_issue_close") is not True
            or value.get("v2_record_immutability") is not True
            or value.get("v3_record_immutability") is not True):
        raise PhaseReworkError("timestamp-continuation marker does not match the approved Issue #71 subject")
    if marker_schema == TIMESTAMP_CONTINUATION_AUTH_SCHEMA_V2:
        checklist_start = text.find("## Reviewer checklist")
        if checklist_start < 0:
            raise PhaseReworkError("timestamp-continuation V2 ADC has no Reviewer checklist")
        checklist_end = text.find("\n## ", checklist_start + len("## Reviewer checklist"))
        if checklist_end < 0:
            checklist_end = len(text)
        checklist_text = text[checklist_start:checklist_end]
        actual_checklist_count = len(re.findall(r"(?m)^- \[ \] ", checklist_text))
        if value["reviewer_checklist_count"] != actual_checklist_count:
            raise PhaseReworkError("timestamp-continuation V2 Reviewer checklist count differs from its marker")
    head = value.get("current_head_sha40")
    if not isinstance(head, str) or SHA40.fullmatch(head) is None:
        raise PhaseReworkError("timestamp-continuation marker current HEAD is malformed")
    issue = value.get("current_issue")
    if (not isinstance(issue, dict) or set(issue) != {"body_sha256", "id", "labels", "number", "state"}
            or issue.get("body_sha256") != ISSUE_BODY_SHA256 or issue.get("id") != ISSUE_ID
            or issue.get("number") != ISSUE_NUMBER or issue.get("state") != "open"
            or not isinstance(issue.get("labels"), list)
            or len(issue["labels"]) != len(set(issue["labels"]))
            or "phase:requirements" not in issue["labels"]):
        raise PhaseReworkError("timestamp-continuation Issue identity or starting phase differs")
    pull = value.get("current_pr")
    if (not isinstance(pull, dict)
            or set(pull) != {"base_ref", "base_sha40", "body_sha256", "draft", "head_sha40",
                             "merged", "number", "state"}
            or pull.get("base_ref") != PR_BASE_REF or pull.get("base_sha40") != PR_BASE_SHA40
            or pull.get("body_sha256") != PR_BODY_SHA256 or pull.get("draft") is not False
            or pull.get("head_sha40") != head or pull.get("merged") is not False
            or pull.get("number") != PR_NUMBER or pull.get("state") != "open"):
        raise PhaseReworkError("timestamp-continuation PR identity or starting refs differ")
    boundary = value.get("history_boundary")
    if (not isinstance(boundary, dict) or set(boundary) != {"comment_id", "sha256"}
            or type(boundary.get("comment_id")) is not int or boundary["comment_id"] < 1
            or not isinstance(boundary.get("sha256"), str)
            or not SHA256.fullmatch(boundary["sha256"])
            or boundary["comment_id"] >= verified.pointer.comment_id):
        raise PhaseReworkError("timestamp-continuation history boundary is malformed")
    predecessor = _adc_predecessor_header(text, "timestamp-continuation ADC")
    current_predecessor = value.get("current_adc_predecessor")
    if (not isinstance(current_predecessor, dict)
            or set(current_predecessor) != {"byte_length", "comment_id", "sha256"}
            or type(current_predecessor.get("byte_length")) is not int
            or current_predecessor["byte_length"] < 1
            or type(current_predecessor.get("comment_id")) is not int
            or current_predecessor["comment_id"] < 1
            or not isinstance(current_predecessor.get("sha256"), str)
            or not SHA256.fullmatch(current_predecessor["sha256"])
            or predecessor != (current_predecessor["comment_id"], current_predecessor["sha256"])):
        raise PhaseReworkError("timestamp-continuation ADC predecessor differs from its marker")
    history = value.get("approved_history")
    if not isinstance(history, list) or not history:
        raise PhaseReworkError("timestamp-continuation marker has no approved history")
    ids: list[int] = []
    for row in history:
        if (not isinstance(row, dict) or set(row) != {"byte_length", "comment_id", "sha256", "state"}
                or type(row.get("byte_length")) is not int or row["byte_length"] < 1
                or type(row.get("comment_id")) is not int or row["comment_id"] <= boundary["comment_id"]
                or not isinstance(row.get("sha256"), str) or not SHA256.fullmatch(row["sha256"])
                or row.get("state") != "approved"):
            raise PhaseReworkError("timestamp-continuation approved history contains an invalid row")
        ids.append(row["comment_id"])
    expected_predecessor_row = {
        "byte_length": current_predecessor["byte_length"],
        "comment_id": current_predecessor["comment_id"],
        "sha256": current_predecessor["sha256"],
        "state": "approved",
    }
    if ids != sorted(set(ids)) or history[-1] != expected_predecessor_row:
        raise PhaseReworkError("timestamp-continuation approved history order or predecessor differs")
    followup = value.get("followup_commit_authorization")
    allowlist = followup.get("path_allowlist") if isinstance(followup, dict) else None
    if (not isinstance(followup, dict)
            or set(followup) != {"max_commits", "parent_sha40", "path_allowlist",
                                 "require_direct_child", "require_push_to_existing_branch"}
            or followup.get("max_commits") != 1 or followup.get("parent_sha40") != head
            or not isinstance(allowlist, list) or not allowlist
            or allowlist != sorted(set(allowlist))
            or any(not isinstance(path, str) or not path or path.startswith("/")
                   or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/"))
                   for path in allowlist)
            or followup.get("require_direct_child") is not True
            or followup.get("require_push_to_existing_branch") is not True):
        raise PhaseReworkError("timestamp-continuation commit boundary or exact allowlist differs")
    timestamp_policy = value.get("timestamp_policy")
    if (not isinstance(timestamp_policy, dict)
            or set(timestamp_policy) != {"applied_event_field", "applies_to", "intent_event_field",
                                         "max_skew_seconds", "minimum_skew_seconds", "reason", "rule", "schema"}
            or timestamp_policy.get("schema") != "PASES_ISSUE_PHASE_EVENT_PUBLICATION_WINDOW_V1"
            or timestamp_policy.get("minimum_skew_seconds") != 0
            or timestamp_policy.get("max_skew_seconds") != 300
            or timestamp_policy.get("intent_event_field") != "created_at"
            or timestamp_policy.get("applied_event_field") != "applied_at"
            or timestamp_policy.get("applies_to") != [INTENT_SCHEMA, APPLIED_SCHEMA,
                                                       ISSUE71_REWORK_INTENT_V3_SCHEMA,
                                                       ISSUE71_REWORK_APPLIED_V3_SCHEMA]
            or timestamp_policy.get("rule") != (
                "Both timestamps must be strict UTC. comment created_at minus embedded event time "
                "must be in the inclusive range 0..300 seconds.")):
        raise PhaseReworkError("timestamp-continuation timestamp policy is invalid")
    if value.get("phase_rework_origin") != TIMESTAMP_CONTINUATION_PHASE_REWORK_ORIGIN:
        raise PhaseReworkError("timestamp-continuation V3 origin differs from the immutable journal")
    if value.get("phase_edges") != [
            ["requirements", "specification"], ["specification", "design"], ["design", "ready"],
            ["ready", "execution"], ["execution", "verification"], ["verification", "user-review"]]:
        raise PhaseReworkError("timestamp-continuation phase edges differ from the authorized sequence")
    if value.get("phase_reissue_policy") != {
            "bind_current_committed_document_bytes_at_exact_followup_head": True,
            "documents": ["requirements", "specification", "design", "ready"],
            "preserve_historical_receipts": True}:
        raise PhaseReworkError("timestamp-continuation phase reissue policy differs")
    if value.get("user_review") != {
            "decision_allowed": False, "existing_session": "absent",
            "feedback_snapshot": "complete and immutable", "max_sessions": 1,
            "must_start_after_final_readiness_pass": True, "required_final_state": "PENDING"}:
        raise PhaseReworkError("timestamp-continuation User Review gate differs")
    return value, hashlib.sha256(marker_bytes).hexdigest()

def _validate_historical_commit_segments(
    segments: Any,
    approved_history: Sequence[Mapping[str, Any]],
    start_head: Any,
    end_head: Any,
) -> None:
    """Validate the current ADC's exact, ordered authorization map for prior commits."""
    if (not isinstance(start_head, str) or SHA40.fullmatch(start_head) is None
            or not isinstance(end_head, str) or SHA40.fullmatch(end_head) is None
            or start_head == end_head or not isinstance(segments, list) or not segments):
        raise PhaseReworkError("historical commit segment map has invalid endpoints or is empty")
    history_positions = {
        row["comment_id"]: (index, row["sha256"])
        for index, row in enumerate(approved_history)
    }
    previous_head = start_head
    previous_history_index = -1
    seen_commits: set[str] = set()
    for segment in segments:
        if (not isinstance(segment, dict)
                or set(segment) != {
                    "adc_comment_id", "adc_sha256", "commit_sha40", "parent_sha40",
                    "path_allowlist",
                }):
            raise PhaseReworkError("historical commit segment has unknown or missing fields")
        adc_id = segment.get("adc_comment_id")
        adc_sha256 = segment.get("adc_sha256")
        parent = segment.get("parent_sha40")
        commit = segment.get("commit_sha40")
        paths = segment.get("path_allowlist")
        history_row = history_positions.get(adc_id) if type(adc_id) is int else None
        if (history_row is None or not isinstance(adc_sha256, str)
                or history_row[1] != adc_sha256 or SHA256.fullmatch(adc_sha256) is None):
            raise PhaseReworkError("historical commit segment does not bind an approved ADC history row")
        history_index = history_row[0]
        if history_index <= previous_history_index:
            raise PhaseReworkError("historical commit segments reorder or reuse approved ADC generations")
        if (not isinstance(parent, str) or SHA40.fullmatch(parent) is None
                or parent != previous_head or not isinstance(commit, str)
                or SHA40.fullmatch(commit) is None or commit in seen_commits):
            raise PhaseReworkError("historical commit segments contain a gap, duplicate, or invalid SHA")
        if (not isinstance(paths, list) or not paths
                or any(not isinstance(path, str) or not path or path.startswith("/")
                       or "\\" in path or any(part in {"", ".", ".."}
                                               for part in path.split("/"))
                       for path in paths)
                or paths != sorted(set(paths))):
            raise PhaseReworkError("historical commit segment path allowlist is malformed")
        previous_head = commit
        previous_history_index = history_index
        seen_commits.add(commit)
    if previous_head != end_head:
        raise PhaseReworkError("historical commit segment map does not end at the exact current start HEAD")


def parse_issue71_phase_and_user_review_authorization(
    verified: VerifiedADC,
) -> dict[str, Any]:
    """Validate the canonical current Issue #71 marker and its internal bindings."""
    contract = verified.contract
    if (verified.pointer.state != "approved"
            or verified.pointer.sha256 != contract.sha256
            or contract.byte_length != len(contract.content)
            or contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("current Issue #71 ADC pointer and exact bytes do not agree")
    try:
        text = contract.content.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise PhaseReworkError("current Issue #71 combined ADC is not valid UTF-8") from exc

    if f"<!-- {ISSUE71_PHASE_AND_USER_REVIEW_V3_SCHEMA}\n" in text:
        return _parse_issue71_phase_and_user_review_v3_authorization(verified, text)

    schema = ISSUE71_CURRENT_COMBINED_SCHEMA
    start_marker = f"<!-- {schema}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError("current Issue #71 ADC must contain exactly one combined authorization marker")
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0 or text[close + len("\n-->"):].strip():
        raise PhaseReworkError("current Issue #71 combined authorization marker is incomplete or not terminal")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("current Issue #71 combined authorization JSON is malformed") from exc
    expected_fields = ISSUE71_CURRENT_COMBINED_MARKER_FIELDS
    if (not isinstance(value, dict)
            or set(value) != expected_fields
            or value.get("schema") != schema
            or _canonical(value) != raw):
        raise PhaseReworkError("current Issue #71 combined authorization is not canonical or complete")

    history = value.get("approved_history")
    if not isinstance(history, list) or not history:
        raise PhaseReworkError("current Issue #71 marker must carry its complete approved history")
    history_rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for item in history:
        if (not isinstance(item, dict)
                or set(item) != {"byte_length", "comment_id", "sha256", "state"}
                or type(item.get("comment_id")) is not int or item["comment_id"] < 1
                or type(item.get("byte_length")) is not int or item["byte_length"] < 1
                or not isinstance(item.get("sha256"), str)
                or not SHA256.fullmatch(item["sha256"])
                or item.get("state") != "approved"
                or item["comment_id"] in seen_ids):
            raise PhaseReworkError("current Issue #71 approved history contains a malformed or duplicate entry")
        seen_ids.add(item["comment_id"])
        history_rows.append(item)
    predecessor = history_rows[-1]
    if (type(value.get("predecessor_adc_comment_id")) is not int
            or type(value.get("predecessor_adc_byte_length")) is not int
            or value.get("predecessor_adc_comment_id") != predecessor["comment_id"]
            or value.get("predecessor_adc_sha256") != predecessor["sha256"]
            or value.get("predecessor_adc_byte_length") != predecessor["byte_length"]
            or _adc_predecessor_header(text, "current Issue #71 ADC") != (
                predecessor["comment_id"], predecessor["sha256"])):
        raise PhaseReworkError("current Issue #71 predecessor does not match the verified history declaration")

    starting_head = value.get("starting_head_sha40")
    allowlist = value.get("followup_path_allowlist")
    if (not isinstance(starting_head, str) or not SHA40.fullmatch(starting_head)
            or not isinstance(allowlist, list) or not allowlist
            or any(not isinstance(path, str) or not path or path.startswith("/")
                   or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/"))
                   for path in allowlist)
            or allowlist != sorted(set(allowlist))):
        raise PhaseReworkError("current Issue #71 start HEAD or follow-up allowlist is malformed")

    phase = value.get("phase_receipt_reconciliation")
    user_review = value.get("issue71_user_review_authorization")
    if (not isinstance(phase, dict) or set(phase) != ISSUE71_PHASE_RECEIPT_AUTH_FIELDS
            or not isinstance(user_review, dict) or set(user_review) != ISSUE71_USER_REVIEW_AUTH_FIELDS):
        raise PhaseReworkError("current Issue #71 ADC authorization tuples have unknown or missing fields")
    historical_commit_segments = phase.get("historical_commit_segments")
    _validate_historical_commit_segments(
        historical_commit_segments, history_rows,
        APPROVED_HISTORY_READER_AUTHORIZATION["starting_head_sha40"],
        phase.get("starting_head_sha40"),
    )
    historical_documents = value.get("historical_document_reissue_authorization")
    if historical_documents != ISSUE71_HISTORICAL_DOCUMENT_REISSUE_AUTHORIZATION:
        raise PhaseReworkError("historical document reissue authorization differs from its immutable tuple")

    snapshot = value.get("current_document_snapshot_authorization")
    snapshot_fields = {
        "branch_ref", "current_source_document_digests", "issue_number",
        "repository_id", "schema", "source_commit_policy",
    }
    if (not isinstance(snapshot, dict) or set(snapshot) != snapshot_fields
            or snapshot.get("schema") != "PASES_ISSUE71_CURRENT_DOCUMENT_SNAPSHOT_V1"
            or snapshot.get("repository_id") != REPOSITORY_ID
            or snapshot.get("issue_number") != ISSUE_NUMBER
            or snapshot.get("branch_ref") != BRANCH_REF
            or snapshot.get("source_commit_policy") != "exact_current_pushed_head"):
        raise PhaseReworkError("current Issue #71 document snapshot authorization is malformed")
    document_rows = snapshot.get("current_source_document_digests")
    expected_document_paths = [
        "docs/design/workflow-design.md",
        "docs/specs/workflow-spec.md",
    ]
    if (not isinstance(document_rows, list) or len(document_rows) != len(expected_document_paths)
            or [row.get("path") if isinstance(row, dict) else None for row in document_rows]
               != expected_document_paths
            or any(set(row) != {"path", "sha256"}
                   or not isinstance(row.get("sha256"), str)
                   or not SHA256.fullmatch(row["sha256"])
                   for row in document_rows)):
        raise PhaseReworkError("current Issue #71 Specification/Design document snapshot is incomplete")

    expected_phase = {
        "schema": ISSUE71_PHASE_RECEIPT_AUTH_SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER,
        "issue_id": ISSUE_ID,
        "owner_id": OWNER_ID,
        "issue_body_sha256": ISSUE_BODY_SHA256,
        "labels_at_start": ["enhancement", "kind:single", "phase:design"],
        "branch_ref": BRANCH_REF,
        "frozen_base_ref": BASE_REF,
        "frozen_base_sha40": BASE_SHA40,
        "pr_number": PR_NUMBER,
        "pr_base_ref": PR_BASE_REF,
        "pr_base_sha40": PR_BASE_SHA40,
        "pr_body_sha256": PR_BODY_SHA256,
        "predecessor_adc_comment_id": predecessor["comment_id"],
        "predecessor_adc_sha256": predecessor["sha256"],
        "active_epoch_id": ACTIVE_EPOCH_ID,
        "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "active_phase_generation_comment_id": 6889965335,
        "active_phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "intent_comment_id": 6888474848,
        "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
        "applied_comment_id": 6889965335,
        "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "historical_receipt_adc_comment_id": 6891926625,
        "historical_receipt_adc_sha256": "64c8d8d3ceb06f5e04d6c9eb780c0bb3a0607dc61440e136b00bcdf63cf941a8",
        "historical_receipt_commit_sha40": "b31cca21da15e18d0e1665827621700f7d774d0a",
        "historical_receipts": [
            {
                "body_sha256": "67402fbb84567844ef7399868d8aa09538526fe41b101cd00d362c60019cc5b9",
                "comment_id": 6892886558,
                "commit_sha40": "b31cca21da15e18d0e1665827621700f7d774d0a",
                "from_phase": "requirements",
                "phase_generation_comment_id": 6889965335,
                "phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
                "to_phase": "specification",
            },
            {
                "body_sha256": "ee9fba19f51b06f9ceae63e16bdac5ea54ac0f5b0bae72eef6eba397e64334ef",
                "comment_id": 6892997518,
                "commit_sha40": "b31cca21da15e18d0e1665827621700f7d774d0a",
                "from_phase": "specification",
                "phase_generation_comment_id": 6889965335,
                "phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
                "to_phase": "design",
            },
        ],
        "reissue_edges": [["requirements", "specification"], ["specification", "design"]],
        "permitted_current_adc_edges": [["requirements", "specification"],
                                         ["specification", "design"], ["design", "ready"]],
        "permitted_label_transitions": [["design", "ready"], ["ready", "execution"],
                                        ["execution", "verification"], ["verification", "user-review"]],
        "max_followup_commits": 1,
        "starting_head_sha40": starting_head,
        "followup_path_allowlist": allowlist,
        "historical_commit_segments": historical_commit_segments,
    }
    expected_user_review = {
        "schema": ISSUE71_USER_REVIEW_AUTH_SCHEMA,
        "repository_id": REPOSITORY_ID,
        "owner_id": OWNER_ID,
        "issue_number": ISSUE_NUMBER,
        "pr_number": PR_NUMBER,
        "decision_carrier_issue_number": ISSUE_NUMBER,
        "decision_schema": "PASES_USER_REVIEW_DECISION_V3",
        "review_mode": "solo_owner",
        "project_profile_sha256": "396379272080348b5b7b2a78faac09ab28dcdb001106a238c5e62945eaf8f820",
        "subject_fields": ["adc_sha256", "feedback_sha256", "pr_head_sha40",
                           "readiness_sha256", "review_session_sha256"],
        "max_decisions_per_session": 1,
        "direct_chat_confirmation_required": True,
        "issue63_access": "none",
    }
    fixed_authorizations = {
        "continuation": CONTINUATION_AUTHORIZATION,
        "execution_receipt_reader_continuation": EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
        "reader_continuation": READER_CONTINUATION_AUTHORIZATION,
        "recovery": RECOVERY_AUTHORIZATION,
        "rework": AUTHORIZATION,
        "timestamp_recovery": TIMESTAMP_RECOVERY_AUTHORIZATION,
    }
    expected_digests = {
        name: hashlib.sha256(_canonical(item).encode("utf-8")).hexdigest()
        for name, item in fixed_authorizations.items()
    }
    expected_digests.update({
        "current_document_snapshot": hashlib.sha256(_canonical(snapshot).encode("utf-8")).hexdigest(),
        "historical_document_reissue": hashlib.sha256(
            _canonical(historical_documents).encode("utf-8")
        ).hexdigest(),
        "issue71_user_review": hashlib.sha256(_canonical(user_review).encode("utf-8")).hexdigest(),
        "phase_receipt_reconciliation": hashlib.sha256(_canonical(phase).encode("utf-8")).hexdigest(),
    })
    if (user_review != expected_user_review
            or phase != expected_phase
            or value.get("active_authorization_digests") != expected_digests):
        raise PhaseReworkError("current Issue #71 marker authorization tuple or digest differs")

    expected_top = {
        "active_authorization_digests": expected_digests,
        "active_epoch_id": ACTIVE_EPOCH_ID,
        "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "active_phase_generation_comment_id": 6889965335,
        "active_phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "applied_comment_id": 6889965335,
        "approved_history": history_rows,
        "branch_ref": BRANCH_REF,
        "current_document_snapshot_authorization": snapshot,
        "current_issue_body_sha256": ISSUE_BODY_SHA256,
        "followup_path_allowlist": allowlist,
        "frozen_base_ref": BASE_REF,
        "frozen_base_sha40": BASE_SHA40,
        "historical_document_reissue_authorization": historical_documents,
        "history_predecessor_boundary": {
            "comment_id": ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[0],
            "sha256": ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[1],
        },
        "intent_body_sha256": expected_phase["intent_body_sha256"],
        "intent_comment_id": expected_phase["intent_comment_id"],
        "issue71_user_review_authorization": expected_user_review,
        "issue_id": ISSUE_ID,
        "issue_number": ISSUE_NUMBER,
        "labels_at_start": expected_phase["labels_at_start"],
        "max_followup_commits": 1,
        "owner_id": OWNER_ID,
        "phase_receipt_reconciliation": expected_phase,
        "pr_base_ref": PR_BASE_REF,
        "pr_base_sha40": PR_BASE_SHA40,
        "pr_body_sha256": PR_BODY_SHA256,
        "pr_number": PR_NUMBER,
        "predecessor_adc_byte_length": predecessor["byte_length"],
        "predecessor_adc_comment_id": predecessor["comment_id"],
        "predecessor_adc_sha256": predecessor["sha256"],
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "schema": schema,
        "starting_head_sha40": starting_head,
    }
    if value != expected_top:
        mismatches = [key for key in expected_top if value.get(key) != expected_top[key]]
        raise PhaseReworkError(
            "current Issue #71 marker fields differ from its authorized values: "
            + ", ".join(mismatches)
        )

    try:
        from .phase_evidence import _artifact_impacts
        impacts, reasons = _artifact_impacts(verified)
    except (ImportError, ValueError) as exc:
        raise PhaseReworkError(f"current Issue #71 Artifact impact is invalid: {exc}") from exc
    if (reasons
            or impacts.get("specification") != ("docs/specs/workflow-spec.md",)
            or impacts.get("design") != ("docs/design/workflow-design.md",)
            or not impacts.get("test-oracle")):
        raise PhaseReworkError(
            "current Issue #71 Artifact impact must use the generic Specification/Design/Testing path grammar"
        )
    return value


def _parse_issue71_phase_and_user_review_v3_authorization(
    verified: VerifiedADC, text: str,
) -> dict[str, Any]:
    """Validate the approved V3 marker and every duplicated authorization binding."""
    schema = ISSUE71_PHASE_AND_USER_REVIEW_V3_SCHEMA
    start_marker = f"<!-- {schema}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError("current Issue #71 V3 ADC must contain one authorization marker")
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0 or text[close + len("\n-->"):].strip():
        raise PhaseReworkError("current Issue #71 V3 marker is incomplete or not terminal")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("current Issue #71 V3 marker JSON is malformed") from exc
    if (not isinstance(value, dict) or set(value) != ISSUE71_PHASE_AND_USER_REVIEW_V3_FIELDS
            or value.get("schema") != schema or _canonical(value) != raw):
        raise PhaseReworkError("current Issue #71 V3 marker fields or canonical JSON are invalid")

    history = value.get("approved_history")
    history_rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    if not isinstance(history, list) or not history:
        raise PhaseReworkError("current Issue #71 V3 marker has no approved ADC history")
    for item in history:
        if (not isinstance(item, dict)
                or set(item) != {"byte_length", "comment_id", "sha256", "state"}
                or type(item.get("comment_id")) is not int or item["comment_id"] < 1
                or type(item.get("byte_length")) is not int or item["byte_length"] < 1
                or not isinstance(item.get("sha256"), str)
                or not SHA256.fullmatch(item["sha256"])
                or item.get("state") != "approved"
                or item["comment_id"] in seen_ids):
            raise PhaseReworkError("current Issue #71 V3 ADC history is malformed or duplicated")
        seen_ids.add(item["comment_id"])
        history_rows.append(item)
    if [row["comment_id"] for row in history_rows] != sorted(seen_ids):
        raise PhaseReworkError("current Issue #71 V3 ADC history is not in forward order")
    predecessor = history_rows[-1]
    if (value.get("predecessor_adc_comment_id") != predecessor["comment_id"]
            or value.get("predecessor_adc_sha256") != predecessor["sha256"]
            or value.get("predecessor_adc_byte_length") != predecessor["byte_length"]
            or _adc_predecessor_header(text, "current Issue #71 V3 ADC")
            != (predecessor["comment_id"], predecessor["sha256"])):
        raise PhaseReworkError("current Issue #71 V3 predecessor differs from approved history")

    boundary = {
        "comment_id": ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[0],
        "sha256": ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[1],
    }
    if value.get("history_predecessor_boundary") != boundary:
        raise PhaseReworkError("current Issue #71 V3 history boundary differs from its fixed predecessor")
    starting_head = value.get("starting_head_sha40")
    allowlist = value.get("followup_path_allowlist")
    if (starting_head != "a6f76b3639fd713ab3701d0c6e98691f6a306abc"
            or not isinstance(allowlist, list) or not allowlist
            or allowlist != sorted(set(allowlist))
            or any(not isinstance(path, str) or not path or path.startswith("/")
                   or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/"))
                   for path in allowlist)
            or value.get("max_followup_commits") != 1):
        raise PhaseReworkError("current Issue #71 V3 start HEAD or follow-up allowlist is invalid")

    generation = value.get("phase_rework_generation_authorization")
    generation_fields = {
        "active_epoch_id", "active_epoch_sha256", "branch_ref", "current_issue_body_sha256",
        "existing_user_review_session", "followup_path_allowlist", "from_phase", "issue_id",
        "issue_number", "labels_after", "labels_before", "max_applications",
        "max_bootstrap_commits", "max_followup_commits", "new_applied_schema",
        "new_generation_number", "new_intent_schema", "owner_id", "pr_base_ref",
        "pr_base_sha40", "pr_number", "predecessor_adc_comment_id", "predecessor_adc_sha256",
        "preserve_existing_rework_records_byte_for_byte", "preserve_prior_v2_applied_body_sha256",
        "preserve_prior_v2_applied_comment_id", "preserve_prior_v2_intent_body_sha256",
        "preserve_prior_v2_intent_comment_id", "prior_phase_generation_comment_id",
        "prior_phase_generation_sha256", "repository", "repository_id",
        "require_current_adc_forward_chain",
        "require_fresh_exact_subject_verification_acceptance_self_audit_independent_review_readiness",
        "schema", "starting_head_sha40", "to_phase",
    }
    expected_generation = {
        "active_epoch_id": ACTIVE_EPOCH_ID,
        "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "branch_ref": BRANCH_REF,
        "current_issue_body_sha256": ISSUE_BODY_SHA256,
        "existing_user_review_session": "absent",
        "followup_path_allowlist": allowlist,
        "from_phase": "verification",
        "issue_id": ISSUE_ID,
        "issue_number": ISSUE_NUMBER,
        "labels_after": LABELS_AFTER,
        "labels_before": LABELS_BEFORE,
        "max_applications": 1,
        "max_bootstrap_commits": 1,
        "max_followup_commits": 1,
        "new_applied_schema": ISSUE71_REWORK_APPLIED_V3_SCHEMA,
        "new_generation_number": 2,
        "new_intent_schema": ISSUE71_REWORK_INTENT_V3_SCHEMA,
        "owner_id": OWNER_ID,
        "pr_base_ref": PR_BASE_REF,
        "pr_base_sha40": PR_BASE_SHA40,
        "pr_number": PR_NUMBER,
        "predecessor_adc_comment_id": predecessor["comment_id"],
        "predecessor_adc_sha256": predecessor["sha256"],
        "preserve_existing_rework_records_byte_for_byte": True,
        "preserve_prior_v2_applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "preserve_prior_v2_applied_comment_id": 6889965335,
        "preserve_prior_v2_intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
        "preserve_prior_v2_intent_comment_id": 6888474848,
        "prior_phase_generation_comment_id": 6889965335,
        "prior_phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "require_current_adc_forward_chain": True,
        "require_fresh_exact_subject_verification_acceptance_self_audit_independent_review_readiness": True,
        "schema": "PASES_ISSUE71_PHASE_REWORK_GENERATION_V3",
        "starting_head_sha40": starting_head,
        "to_phase": "requirements",
    }
    if (not isinstance(generation, dict) or set(generation) != generation_fields
            or generation != expected_generation):
        raise PhaseReworkError("current Issue #71 V3 phase-rework authorization differs")

    batch = value.get("batch_reader_authorization")
    batch_fields = {
        "history_start_comment_id", "history_start_sha256", "issue_number",
        "max_complete_issue_comment_snapshots_per_range", "per_generation_direct_comment_reads",
        "predecessor_adc_comment_id", "predecessor_adc_sha256", "repository",
        "repository_id", "schema", "snapshot_requirements",
    }
    expected_batch = {
        "history_start_comment_id": boundary["comment_id"],
        "history_start_sha256": boundary["sha256"],
        "issue_number": ISSUE_NUMBER,
        "max_complete_issue_comment_snapshots_per_range": 2,
        "per_generation_direct_comment_reads": 2,
        "predecessor_adc_comment_id": predecessor["comment_id"],
        "predecessor_adc_sha256": predecessor["sha256"],
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "schema": "PASES_ADC_FORWARD_HISTORY_BATCH_READ_V1",
        "snapshot_requirements": [
            "Validate the complete ordered approved pointer journal from the initial complete paginated snapshot.",
            "Direct-read each selected ADC body before and after; require exact repository/Issue identity, bytes, SHA-256, length, approved state, and predecessor adjacency.",
            "Read the complete paginated comment journal once after the range and require all pointer records and selected ADC list entries to match the initial snapshot.",
            "Reject missing, duplicate, edited, reordered, malformed, or drifted pointer or ADC records before returning verified generations.",
            "The complete paginated comment-list sweep count is independent of selected ADC range length.",
        ],
    }
    if not isinstance(batch, dict) or set(batch) != batch_fields or batch != expected_batch:
        raise PhaseReworkError("current Issue #71 V3 batch-reader authorization differs")

    snapshot = value.get("current_document_snapshot_authorization")
    snapshot_fields = {
        "branch_ref", "current_source_document_digests", "issue_number",
        "repository_id", "schema", "source_commit_policy",
    }
    expected_document_paths = ["docs/design/workflow-design.md", "docs/specs/workflow-spec.md"]
    document_rows = snapshot.get("current_source_document_digests") if isinstance(snapshot, dict) else None
    if (not isinstance(snapshot, dict) or set(snapshot) != snapshot_fields
            or snapshot.get("schema") != "PASES_ISSUE71_CURRENT_DOCUMENT_SNAPSHOT_V1"
            or snapshot.get("branch_ref") != BRANCH_REF or snapshot.get("issue_number") != ISSUE_NUMBER
            or snapshot.get("repository_id") != REPOSITORY_ID
            or snapshot.get("source_commit_policy") != "exact_current_pushed_head"
            or not isinstance(document_rows, list) or len(document_rows) != 2
            or [row.get("path") if isinstance(row, dict) else None for row in document_rows]
               != expected_document_paths
            or any(set(row) != {"path", "sha256"} or not isinstance(row.get("sha256"), str)
                   or not SHA256.fullmatch(row["sha256"]) for row in document_rows)):
        raise PhaseReworkError("current Issue #71 V3 document snapshot authorization is malformed")

    historical_documents = value.get("historical_document_reissue_authorization")
    if historical_documents != ISSUE71_HISTORICAL_DOCUMENT_REISSUE_AUTHORIZATION:
        raise PhaseReworkError("current Issue #71 V3 historical document authorization differs")
    post_documents = value.get("post_followup_document_authorization")
    expected_post_documents = {
        "branch_ref": BRANCH_REF,
        "followup_path_allowlist": allowlist,
        "historical_receipt_policy": "preserve_original_receipt_ids_and_validate_document_bytes_at_each_recorded_historical_commit",
        "issue_number": ISSUE_NUMBER,
        "reissued_phase_document_policy": "bind_exact_current_committed_specification_design_and_test_oracle_bytes_at_followup_head",
        "repository_id": REPOSITORY_ID,
        "schema": "PASES_ISSUE71_POST_FOLLOWUP_DOCUMENT_SNAPSHOT_V1",
        "source_commit_policy": "exact_direct_child_followup_commit",
        "starting_head_sha40": starting_head,
    }
    if not isinstance(post_documents, dict) or post_documents != expected_post_documents:
        raise PhaseReworkError("current Issue #71 V3 post-follow-up document authorization differs")

    phase = value.get("phase_receipt_reconciliation")
    phase_fields = ISSUE71_PHASE_RECEIPT_AUTH_FIELDS | {"post_followup_document_policy"}
    segments = phase.get("historical_commit_segments") if isinstance(phase, dict) else None
    _validate_historical_commit_segments(
        segments, history_rows, APPROVED_HISTORY_READER_AUTHORIZATION["starting_head_sha40"], starting_head,
    )
    expected_phase = {
        "schema": ISSUE71_PHASE_RECEIPT_AUTH_SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER,
        "issue_id": ISSUE_ID,
        "owner_id": OWNER_ID,
        "issue_body_sha256": ISSUE_BODY_SHA256,
        "labels_at_start": ["enhancement", "kind:single", "phase:design"],
        "branch_ref": BRANCH_REF,
        "frozen_base_ref": BASE_REF,
        "frozen_base_sha40": BASE_SHA40,
        "pr_number": PR_NUMBER,
        "pr_base_ref": PR_BASE_REF,
        "pr_base_sha40": PR_BASE_SHA40,
        "pr_body_sha256": PR_BODY_SHA256,
        "predecessor_adc_comment_id": 6943309043,
        "predecessor_adc_sha256": "a886858fe635c4b74c7208524f00ad94f8091a44e89f266fce00ffb7413c8a11",
        "active_epoch_id": ACTIVE_EPOCH_ID,
        "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "active_phase_generation_comment_id": 6889965335,
        "active_phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "intent_comment_id": 6888474848,
        "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
        "applied_comment_id": 6889965335,
        "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "historical_receipt_adc_comment_id": 6891926625,
        "historical_receipt_adc_sha256": "64c8d8d3ceb06f5e04d6c9eb780c0bb3a0607dc61440e136b00bcdf63cf941a8",
        "historical_receipt_commit_sha40": "b31cca21da15e18d0e1665827621700f7d774d0a",
        "historical_receipts": [
            {"body_sha256": "67402fbb84567844ef7399868d8aa09538526fe41b101cd00d362c60019cc5b9",
             "comment_id": 6892886558, "commit_sha40": "b31cca21da15e18d0e1665827621700f7d774d0a",
             "from_phase": "requirements", "phase_generation_comment_id": 6889965335,
             "phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
             "to_phase": "specification"},
            {"body_sha256": "ee9fba19f51b06f9ceae63e16bdac5ea54ac0f5b0bae72eef6eba397e64334ef",
             "comment_id": 6892997518, "commit_sha40": "b31cca21da15e18d0e1665827621700f7d774d0a",
             "from_phase": "specification", "phase_generation_comment_id": 6889965335,
             "phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
             "to_phase": "design"},
        ],
        "reissue_edges": [["requirements", "specification"], ["specification", "design"]],
        "permitted_current_adc_edges": [["requirements", "specification"],
                                         ["specification", "design"], ["design", "ready"]],
        "permitted_label_transitions": [["verification", "requirements"],
                                        ["requirements", "specification"],
                                        ["specification", "design"], ["design", "ready"],
                                        ["ready", "execution"], ["execution", "verification"],
                                        ["verification", "user-review"]],
        "post_followup_document_policy": "bind_exact_current_committed_documents_at_exact_followup_head",
        "max_followup_commits": 1,
        "starting_head_sha40": starting_head,
        "followup_path_allowlist": allowlist,
        "historical_commit_segments": segments,
    }
    if not isinstance(phase, dict) or set(phase) != phase_fields or phase != expected_phase:
        mismatches = [key for key in expected_phase
                      if not isinstance(phase, dict) or phase.get(key) != expected_phase[key]]
        raise PhaseReworkError(
            "current Issue #71 V3 phase-receipt authorization differs: " + ", ".join(mismatches)
        )

    user_review = value.get("issue71_user_review_authorization")
    expected_user_review = {
        "schema": ISSUE71_USER_REVIEW_AUTH_SCHEMA,
        "repository_id": REPOSITORY_ID,
        "owner_id": OWNER_ID,
        "issue_number": ISSUE_NUMBER,
        "pr_number": PR_NUMBER,
        "decision_carrier_issue_number": ISSUE_NUMBER,
        "decision_schema": "PASES_USER_REVIEW_DECISION_V3",
        "review_mode": "solo_owner",
        "project_profile_sha256": "396379272080348b5b7b2a78faac09ab28dcdb001106a238c5e62945eaf8f820",
        "subject_fields": ["adc_sha256", "feedback_sha256", "pr_head_sha40",
                           "readiness_sha256", "review_session_sha256"],
        "max_decisions_per_session": 1,
        "direct_chat_confirmation_required": True,
        "issue63_access": "none",
    }
    fixed_authorizations = {
        "continuation": CONTINUATION_AUTHORIZATION,
        "execution_receipt_reader_continuation": EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
        "reader_continuation": READER_CONTINUATION_AUTHORIZATION,
        "recovery": RECOVERY_AUTHORIZATION,
        "rework": AUTHORIZATION,
        "timestamp_recovery": TIMESTAMP_RECOVERY_AUTHORIZATION,
    }
    digests = {name: hashlib.sha256(_canonical(item).encode("utf-8")).hexdigest()
               for name, item in fixed_authorizations.items()}
    digest_auths = {
        "batch_reader": batch,
        "current_document_snapshot": snapshot,
        "historical_document_reissue": historical_documents,
        "issue71_user_review": user_review,
        "phase_receipt_reconciliation": phase,
        "phase_rework_generation": generation,
        "post_followup_documents": post_documents,
    }
    digests.update({name: hashlib.sha256(_canonical(item).encode("utf-8")).hexdigest()
                    for name, item in digest_auths.items()})
    if (not isinstance(user_review, dict) or set(user_review) != ISSUE71_USER_REVIEW_AUTH_FIELDS
            or user_review != expected_user_review
            or value.get("active_authorization_digests") != digests):
        declared_digests = value.get("active_authorization_digests")
        digest_mismatches = [key for key in digests
                             if not isinstance(declared_digests, dict)
                             or declared_digests.get(key) != digests[key]]
        raise PhaseReworkError(
            "current Issue #71 V3 digest map or User Review authorization differs: "
            + ", ".join(digest_mismatches)
        )

    expected_top = {
        "active_authorization_digests": digests,
        "active_epoch_id": ACTIVE_EPOCH_ID,
        "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "active_phase_generation_comment_id": 6889965335,
        "active_phase_generation_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "applied_body_sha256": "b8648cfd2c9c1479791554179069bfc3b57ab5c7d26ccf255184087dcf388b18",
        "applied_comment_id": 6889965335,
        "approved_history": history_rows,
        "batch_reader_authorization": batch,
        "branch_ref": BRANCH_REF,
        "current_document_snapshot_authorization": snapshot,
        "current_issue_body_sha256": ISSUE_BODY_SHA256,
        "followup_path_allowlist": allowlist,
        "frozen_base_ref": BASE_REF,
        "frozen_base_sha40": BASE_SHA40,
        "historical_document_reissue_authorization": historical_documents,
        "history_predecessor_boundary": boundary,
        "intent_body_sha256": "ad2b75b99d4d0aa11d2cf021605eae9ecd9386a436f8032033a4cf87e5bd5be5",
        "intent_comment_id": 6888474848,
        "issue71_user_review_authorization": expected_user_review,
        "issue_id": ISSUE_ID,
        "issue_number": ISSUE_NUMBER,
        "labels_at_start": ["enhancement", "kind:single", "phase:design"],
        "max_followup_commits": 1,
        "owner_id": OWNER_ID,
        "phase_receipt_reconciliation": expected_phase,
        "phase_rework_generation_authorization": expected_generation,
        "post_followup_document_authorization": expected_post_documents,
        "pr_base_ref": PR_BASE_REF,
        "pr_base_sha40": PR_BASE_SHA40,
        "pr_body_sha256": PR_BODY_SHA256,
        "pr_number": PR_NUMBER,
        "predecessor_adc_byte_length": predecessor["byte_length"],
        "predecessor_adc_comment_id": predecessor["comment_id"],
        "predecessor_adc_sha256": predecessor["sha256"],
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "schema": schema,
        "starting_head_sha40": starting_head,
    }
    if value != expected_top:
        mismatches = [key for key in expected_top if value.get(key) != expected_top[key]]
        raise PhaseReworkError("current Issue #71 V3 top-level bindings differ: " + ", ".join(mismatches))

    try:
        from .phase_evidence import _artifact_impacts
        impacts, reasons = _artifact_impacts(verified)
    except (ImportError, ValueError) as exc:
        raise PhaseReworkError(f"current Issue #71 V3 Artifact impact is invalid: {exc}") from exc
    if (reasons or impacts.get("specification") != ("docs/specs/workflow-spec.md",)
            or impacts.get("design") != ("docs/design/workflow-design.md",)
            or not impacts.get("test-oracle")):
        raise PhaseReworkError("current Issue #71 V3 Artifact impact does not use the approved path grammar")
    return value


def _verified_timestamp_continuation_origin(
    chain: Sequence[VerifiedADC], origin_record: Mapping[str, Any],
) -> VerifiedADC | None:
    """Find the immutable V3 origin by its own identity, separate from the current predecessor."""
    if (origin_record.get("adc_comment_id") != TIMESTAMP_CONTINUATION_ORIGIN_ADC[0]
            or origin_record.get("adc_sha256") != TIMESTAMP_CONTINUATION_ORIGIN_ADC[1]):
        raise PhaseReworkError("immutable V3 origin identity differs from its approved record")
    matches = [row for row in chain
               if row.pointer.comment_id == origin_record["adc_comment_id"]]
    if len(matches) != 1:
        return None
    origin = matches[0]
    if (origin.pointer.sha256 != origin_record["adc_sha256"]
            or origin.pointer.state != "approved"
            or origin.contract.byte_length != TIMESTAMP_CONTINUATION_ORIGIN_BYTES):
        raise PhaseReworkError("immutable V3 origin differs from its exact approved bytes")
    return origin


def verify_issue71_phase_and_user_review_adc_chain(
    github: GitHub, verified: VerifiedADC,
) -> tuple[dict[str, Any], tuple[VerifiedADC, ...]]:
    """Verify the exact approved history declared by the current combined marker."""
    if _has_issue71_timestamp_continuation_marker(verified):
        authorization, _marker_sha = parse_timestamp_continuation_authorization(verified)
        boundary = authorization["history_boundary"]
        try:
            chain = verify_adc_forward_generations(
                github, ISSUE_NUMBER,
                prior_comment_id=boundary["comment_id"],
                prior_sha256=boundary["sha256"],
                current_comment_id=verified.pointer.comment_id,
                current_sha256=verified.contract.sha256,
            )
        except ADCError as exc:
            raise PhaseReworkError(f"timestamp-continuation ADC history readback failed: {exc}") from exc
        actual_history = [
            {"byte_length": row.contract.byte_length, "comment_id": row.pointer.comment_id,
             "sha256": row.contract.sha256, "state": row.pointer.state}
            for row in chain[1:-1]
        ]
        if (not chain or chain[0].pointer.comment_id != boundary["comment_id"]
                or chain[0].contract.sha256 != boundary["sha256"]
                or chain[-1].pointer != verified.pointer
                or actual_history != authorization["approved_history"]):
            raise PhaseReworkError(
                "timestamp-continuation approved history is missing, reordered, changed, or not current"
            )
        previous = (boundary["comment_id"], boundary["sha256"])
        for row in chain[1:-1]:
            body = row.contract.content.decode("utf-8", errors="strict")
            declared = _optional_historical_adc_predecessor_header(
                body, f"approved historical ADC #{row.pointer.comment_id}", row.contract.byte_length,
            )
            if declared is not None and declared != previous:
                raise PhaseReworkError(
                    f"timestamp-continuation historical predecessor differs at #{row.pointer.comment_id}"
                )
            previous = (row.pointer.comment_id, row.contract.sha256)
        current_text = verified.contract.content.decode("utf-8", errors="strict")
        if _adc_predecessor_header(current_text, "timestamp-continuation ADC") != previous:
            raise PhaseReworkError("timestamp-continuation predecessor differs from its approved history")
        origin_record = authorization["phase_rework_origin"]
        origin = _verified_timestamp_continuation_origin(chain, origin_record)
        if origin is None:
            raise PhaseReworkError("immutable V3 origin ADC is absent from the verified forward chain")
        origin_authorization = parse_issue71_phase_and_user_review_authorization(origin)
        origin_generation = origin_authorization.get("phase_rework_generation_authorization")
        origin_content = origin.contract.content.decode("utf-8", errors="strict")
        origin_marker_start = f"<!-- {ISSUE71_PHASE_AND_USER_REVIEW_V3_SCHEMA}\n"
        if origin_content.count(origin_marker_start) != 1:
            raise PhaseReworkError("immutable V3 origin ADC has no unique authorization marker")
        origin_start = origin_content.index(origin_marker_start)
        origin_close = origin_content.find("\n-->", origin_start + len(origin_marker_start))
        if origin_close < 0:
            raise PhaseReworkError("immutable V3 origin marker is incomplete")
        origin_marker = origin_content[origin_start:origin_close + len("\n-->")].encode("utf-8")
        if (len(origin_marker) != origin_record["predecessor_v3_marker_byte_length"]
                or hashlib.sha256(origin_marker).hexdigest()
                != origin_record["predecessor_v3_marker_sha256"]
                or not isinstance(origin_generation, dict)
                or hashlib.sha256(_canonical(origin_generation).encode("utf-8")).hexdigest()
                != origin_record["generation_authorization_sha256"]
                or origin_generation.get("new_generation_number") != origin_record["generation_number"]
                or origin_authorization.get("intent_comment_id")
                != origin_record["prior_v2_intent"]["comment_id"]
                or origin_authorization.get("intent_body_sha256")
                != origin_record["prior_v2_intent"]["body_sha256"]
                or origin_authorization.get("applied_comment_id")
                != origin_record["prior_v2_applied"]["comment_id"]
                or origin_authorization.get("applied_body_sha256")
                != origin_record["prior_v2_applied"]["body_sha256"]):
            raise PhaseReworkError("immutable V3 origin authorization or marker digest differs")
        return origin_authorization, chain
    authorization = parse_issue71_phase_and_user_review_authorization(verified)
    boundary_value = authorization.get("history_predecessor_boundary")
    if boundary_value is None:
        boundary_value = {
            "comment_id": ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[0],
            "sha256": ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[1],
        }
    if (not isinstance(boundary_value, dict)
            or set(boundary_value) != {"comment_id", "sha256"}
            or type(boundary_value.get("comment_id")) is not int
            or not isinstance(boundary_value.get("sha256"), str)
            or not SHA256.fullmatch(boundary_value["sha256"])):
        raise PhaseReworkError("combined ADC history boundary is malformed")
    boundary = (boundary_value["comment_id"], boundary_value["sha256"])
    try:
        chain = verify_adc_forward_generations(
            github, ISSUE_NUMBER,
            prior_comment_id=boundary[0],
            prior_sha256=boundary[1],
            current_comment_id=verified.pointer.comment_id,
            current_sha256=verified.contract.sha256,
        )
    except ADCError as exc:
        raise PhaseReworkError(f"combined ADC approved history readback failed: {exc}") from exc
    if (not chain or chain[0].pointer.comment_id != boundary[0]
            or chain[0].contract.sha256 != boundary[1]
            or chain[-1].pointer != verified.pointer):
        raise PhaseReworkError("combined ADC history boundary or current pointer differs")
    for item in chain:
        if (item.pointer.state != "approved"
                or item.pointer.sha256 != item.contract.sha256
                or item.contract.repository.casefold() != REPOSITORY.casefold()
                or item.contract.byte_length != len(item.contract.content)):
            raise PhaseReworkError(
                f"approved ADC history body or pointer readback differs at comment #{item.pointer.comment_id}"
            )
    actual = [
        {
            "byte_length": item.contract.byte_length,
            "comment_id": item.pointer.comment_id,
            "sha256": item.contract.sha256,
            "state": item.pointer.state,
        }
        for item in chain[1:-1]
    ]
    if actual != authorization["approved_history"]:
        raise PhaseReworkError(
            "combined ADC approved history is incomplete, reordered, edited, or unapproved"
        )
    previous = boundary
    for item in chain[1:-1]:
        body = item.contract.content.decode("utf-8", errors="strict")
        declared = _optional_historical_adc_predecessor_header(
            body, f"approved ADC #{item.pointer.comment_id}", item.contract.byte_length,
        )
        if declared is not None and declared != previous:
            raise PhaseReworkError(
                f"approved historical ADC predecessor header differs at comment #{item.pointer.comment_id}"
            )
        previous = (item.pointer.comment_id, item.contract.sha256)
    current_body = chain[-1].contract.content.decode("utf-8", errors="strict")
    if _adc_predecessor_header(current_body, "current Issue #71 ADC") != previous:
        raise PhaseReworkError("current Issue #71 predecessor header differs from its exact approved chain")
    return authorization, chain


def _verify_combined_followup_commit_set(root: Path, head: str,
                                         authorization: Mapping[str, Any]) -> None:
    start = authorization.get("starting_head_sha40")
    allowlist = authorization.get("followup_path_allowlist")
    if (not isinstance(start, str) or not isinstance(allowlist, list) or not allowlist
            or any(not isinstance(path, str) or not path for path in allowlist)
            or len(allowlist) != len(set(allowlist))
            or authorization.get("max_followup_commits") != 1
            or not is_ancestor(root, start, head)):
        raise PhaseReworkError("combined ADC follow-up commit boundary or allowlist is invalid")
    rows = run_git(root, "rev-list", "--reverse", f"{start}..{head}").splitlines()
    if len(rows) != 1 or commit_parents_sha40(root, rows[0]) != (start,):
        raise PhaseReworkError("combined ADC requires exactly one direct-child implementation commit")
    changed = changed_paths_between(root, start, rows[0])
    if not changed or any(path not in allowlist for path in changed) or rows[0] != head:
        raise PhaseReworkError("combined ADC implementation commit exceeds its exact path allowlist")


def _verify_timestamp_continuation_commit_set(
    root: Path, head: str, authorization: Mapping[str, Any],
) -> None:
    followup = authorization.get("followup_commit_authorization")
    if not isinstance(followup, dict):
        raise PhaseReworkError("timestamp-continuation commit authorization is missing")
    start = followup.get("parent_sha40")
    allowlist = followup.get("path_allowlist")
    if (not isinstance(start, str) or start != authorization.get("current_head_sha40")
            or SHA40.fullmatch(start) is None
            or not isinstance(allowlist, list) or not allowlist
            or allowlist != sorted(set(allowlist))
            or any(not isinstance(path, str) or not path for path in allowlist)
            or any(path.startswith("/") or "\\" in path
                   or any(part in {"", ".", ".."} for part in path.split("/"))
                   for path in allowlist)
            or not is_ancestor(root, start, head)):
        raise PhaseReworkError("timestamp-continuation parent or path allowlist is invalid")
    rows = run_git(root, "rev-list", "--reverse", f"{start}..{head}").splitlines()
    if not rows:
        if head != start:
            raise PhaseReworkError("timestamp-continuation HEAD does not equal its authorized start")
        return
    if (len(rows) != 1 or rows[0] != head
            or commit_parents_sha40(root, rows[0]) != (start,)):
        raise PhaseReworkError("timestamp continuation requires zero or one direct-child commit")
    changed = changed_paths_between(root, start, rows[0])
    if not changed or any(path not in allowlist for path in changed):
        raise PhaseReworkError("timestamp-continuation commit exceeds its exact path allowlist")

def _authorization_context(github: GitHub, current: VerifiedADC) -> tuple[Any, ...]:
    """Resolve the original rework authorization and its exact approved successors."""
    if _has_issue71_timestamp_continuation_marker(current):
        phase_authorization, _chain = verify_issue71_phase_and_user_review_adc_chain(github, current)
        continuation, _marker_sha = parse_timestamp_continuation_authorization(current)
        policy = continuation["timestamp_policy"]
        policy_sha = hashlib.sha256(_canonical(policy).encode("utf-8")).hexdigest()
        return (
            AUTHORIZATION, REWORK_AUTH_MARKER_SHA256,
            RECOVERY_AUTHORIZATION, RECOVERY_AUTH_MARKER_SHA256,
            policy, policy_sha,
            CONTINUATION_AUTHORIZATION, CONTINUATION_AUTH_MARKER_SHA256,
            READER_CONTINUATION_AUTHORIZATION, READER_CONTINUATION_AUTH_MARKER_SHA256,
            EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
            EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256,
            phase_authorization,
        )
    if _has_issue71_current_combined_marker(current):
        phase_authorization, _chain = verify_issue71_phase_and_user_review_adc_chain(github, current)
        return (
            AUTHORIZATION, REWORK_AUTH_MARKER_SHA256,
            RECOVERY_AUTHORIZATION, RECOVERY_AUTH_MARKER_SHA256,
            TIMESTAMP_RECOVERY_AUTHORIZATION, TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256,
            CONTINUATION_AUTHORIZATION, CONTINUATION_AUTH_MARKER_SHA256,
            READER_CONTINUATION_AUTHORIZATION, READER_CONTINUATION_AUTH_MARKER_SHA256,
            EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
            EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256,
            phase_authorization,
        )
    if current.pointer.comment_id == APPROVED_HISTORY_READER_ADC_COMMENT_ID:
        authorization, _current_marker_sha = parse_approved_history_reader_authorization(current)
        _verify_approved_history_reader_chain(github, current, authorization)
        return (
            AUTHORIZATION, REWORK_AUTH_MARKER_SHA256,
            RECOVERY_AUTHORIZATION, RECOVERY_AUTH_MARKER_SHA256,
            TIMESTAMP_RECOVERY_AUTHORIZATION, TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256,
            CONTINUATION_AUTHORIZATION, CONTINUATION_AUTH_MARKER_SHA256,
            READER_CONTINUATION_AUTHORIZATION, READER_CONTINUATION_AUTH_MARKER_SHA256,
            EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
            EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256,
            None,
        )
    if current.pointer.comment_id == REWORK_ADC_COMMENT_ID:
        try:
            chain = verify_adc_forward_generations(
                github, ISSUE_NUMBER,
                prior_comment_id=PREDECESSOR_ADC_COMMENT_ID,
                prior_sha256=PREDECESSOR_ADC_SHA256,
                current_comment_id=current.pointer.comment_id,
                current_sha256=current.contract.sha256,
            )
        except ADCError as exc:
            raise PhaseReworkError(f"approved rework ADC chain readback failed: {exc}") from exc
        if tuple((row.pointer.comment_id, row.contract.sha256) for row in chain) != (
                (PREDECESSOR_ADC_COMMENT_ID, PREDECESSOR_ADC_SHA256),
                (REWORK_ADC_COMMENT_ID, REWORK_ADC_SHA256)):
            raise PhaseReworkError("current ADC is not the exact approved successor of #6886911700")
        authorization, authorization_sha = parse_authorization(current)
        return (authorization, authorization_sha, None, None, None, None, None, None,
                None, None, None, None, None)
    if current.pointer.comment_id == EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID:
        execution_reader_authorization, execution_reader_sha = (
            parse_execution_receipt_reader_continuation_authorization(current)
        )
        try:
            chain = verify_adc_forward_generations(
                github, ISSUE_NUMBER,
                prior_comment_id=PREDECESSOR_ADC_COMMENT_ID,
                prior_sha256=PREDECESSOR_ADC_SHA256,
                current_comment_id=current.pointer.comment_id,
                current_sha256=current.contract.sha256,
            )
        except ADCError as exc:
            raise PhaseReworkError(
                f"approved execution-receipt reader ADC chain readback failed: {exc}"
            ) from exc
        expected_chain = (
            (PREDECESSOR_ADC_COMMENT_ID, PREDECESSOR_ADC_SHA256),
            (REWORK_ADC_COMMENT_ID, REWORK_ADC_SHA256),
            (RECOVERY_ADC_COMMENT_ID, RECOVERY_ADC_SHA256),
            (TIMESTAMP_RECOVERY_ADC_COMMENT_ID, TIMESTAMP_RECOVERY_ADC_SHA256),
            (PATH_CORRECTION_ADC_COMMENT_ID, PATH_CORRECTION_ADC_SHA256),
            (CONTINUATION_ADC_COMMENT_ID, CONTINUATION_ADC_SHA256),
            (TRACEABILITY_CORRECTION_ADC_COMMENT_ID, TRACEABILITY_CORRECTION_ADC_SHA256),
            (READER_CONTINUATION_ADC_COMMENT_ID, READER_CONTINUATION_ADC_SHA256),
            (EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID,
             EXECUTION_RECEIPT_READER_CONTINUATION_ADC_SHA256),
        )
        actual_chain = tuple((item.pointer.comment_id, item.contract.sha256) for item in chain)
        if (actual_chain != expected_chain
                or any(item.pointer.state != "approved" for item in chain)):
            raise PhaseReworkError(
                "execution-receipt reader ADC is not the complete exact nine-generation approved chain"
            )
        authorization, authorization_sha = parse_authorization(chain[1])
        recovery_authorization, recovery_sha = parse_authorization(chain[2])
        timestamp_authorization, timestamp_sha = parse_timestamp_recovery_authorization(chain[3])
        parse_path_correction_generation(chain[4])
        continuation_authorization, continuation_sha = parse_continuation_authorization(chain[5])
        parse_traceability_source_correction_generation(chain[6])
        reader_authorization, reader_sha = parse_reader_continuation_authorization(chain[7])
        if (recovery_authorization.get("predecessor_adc_comment_id") != chain[1].pointer.comment_id
                or recovery_authorization.get("predecessor_adc_sha256") != chain[1].contract.sha256
                or timestamp_authorization.get("predecessor_adc_comment_id") != chain[2].pointer.comment_id
                or timestamp_authorization.get("predecessor_adc_sha256") != chain[2].contract.sha256
                or continuation_authorization.get("predecessor_adc_comment_id") != chain[4].pointer.comment_id
                or continuation_authorization.get("predecessor_adc_sha256") != chain[4].contract.sha256
                or reader_authorization.get("predecessor_adc_comment_id") != chain[6].pointer.comment_id
                or reader_authorization.get("predecessor_adc_sha256") != chain[6].contract.sha256
                or execution_reader_authorization.get("predecessor_adc_comment_id")
                != chain[7].pointer.comment_id
                or execution_reader_authorization.get("predecessor_adc_sha256")
                != chain[7].contract.sha256):
            raise PhaseReworkError(
                "execution-receipt reader marker does not bind its exact approved predecessor chain"
            )
        return (authorization, authorization_sha, recovery_authorization, recovery_sha,
                timestamp_authorization, timestamp_sha, continuation_authorization,
                continuation_sha, reader_authorization, reader_sha,
                execution_reader_authorization, execution_reader_sha, None)
    if current.pointer.comment_id == READER_CONTINUATION_ADC_COMMENT_ID:
        reader_authorization, reader_sha = parse_reader_continuation_authorization(current)
        try:
            chain = verify_adc_forward_generations(
                github, ISSUE_NUMBER,
                prior_comment_id=PREDECESSOR_ADC_COMMENT_ID,
                prior_sha256=PREDECESSOR_ADC_SHA256,
                current_comment_id=current.pointer.comment_id,
                current_sha256=current.contract.sha256,
            )
        except ADCError as exc:
            raise PhaseReworkError(f"approved reader-continuation ADC chain readback failed: {exc}") from exc
        expected_chain = (
            (PREDECESSOR_ADC_COMMENT_ID, PREDECESSOR_ADC_SHA256),
            (REWORK_ADC_COMMENT_ID, REWORK_ADC_SHA256),
            (RECOVERY_ADC_COMMENT_ID, RECOVERY_ADC_SHA256),
            (TIMESTAMP_RECOVERY_ADC_COMMENT_ID, TIMESTAMP_RECOVERY_ADC_SHA256),
            (PATH_CORRECTION_ADC_COMMENT_ID, PATH_CORRECTION_ADC_SHA256),
            (CONTINUATION_ADC_COMMENT_ID, CONTINUATION_ADC_SHA256),
            (TRACEABILITY_CORRECTION_ADC_COMMENT_ID, TRACEABILITY_CORRECTION_ADC_SHA256),
            (READER_CONTINUATION_ADC_COMMENT_ID, READER_CONTINUATION_ADC_SHA256),
        )
        actual_chain = tuple((item.pointer.comment_id, item.contract.sha256) for item in chain)
        if (actual_chain != expected_chain
                or any(item.pointer.state != "approved" for item in chain)):
            raise PhaseReworkError("reader-continuation ADC is not the complete exact eight-generation approved chain")
        authorization, authorization_sha = parse_authorization(chain[1])
        recovery_authorization, recovery_sha = parse_authorization(chain[2])
        timestamp_authorization, timestamp_sha = parse_timestamp_recovery_authorization(chain[3])
        parse_path_correction_generation(chain[4])
        continuation_authorization, continuation_sha = parse_continuation_authorization(chain[5])
        parse_traceability_source_correction_generation(chain[6])
        if (recovery_authorization.get("predecessor_adc_comment_id") != chain[1].pointer.comment_id
                or recovery_authorization.get("predecessor_adc_sha256") != chain[1].contract.sha256
                or timestamp_authorization.get("predecessor_adc_comment_id") != chain[2].pointer.comment_id
                or timestamp_authorization.get("predecessor_adc_sha256") != chain[2].contract.sha256
                or continuation_authorization.get("predecessor_adc_comment_id") != chain[4].pointer.comment_id
                or continuation_authorization.get("predecessor_adc_sha256") != chain[4].contract.sha256
                or reader_authorization.get("predecessor_adc_comment_id") != chain[6].pointer.comment_id
                or reader_authorization.get("predecessor_adc_sha256") != chain[6].contract.sha256):
            raise PhaseReworkError("reader-continuation marker does not bind its exact approved predecessor chain")
        return (authorization, authorization_sha, recovery_authorization, recovery_sha,
                timestamp_authorization, timestamp_sha, continuation_authorization,
                continuation_sha, reader_authorization, reader_sha, None, None, None)
    if current.pointer.comment_id == CONTINUATION_ADC_COMMENT_ID:
        continuation_authorization, continuation_sha = parse_continuation_authorization(current)
        try:
            chain = verify_adc_forward_generations(
                github, ISSUE_NUMBER,
                prior_comment_id=PREDECESSOR_ADC_COMMENT_ID,
                prior_sha256=PREDECESSOR_ADC_SHA256,
                current_comment_id=current.pointer.comment_id,
                current_sha256=current.contract.sha256,
            )
        except ADCError as exc:
            raise PhaseReworkError(f"approved continuation ADC chain readback failed: {exc}") from exc
        expected_chain = (
            (PREDECESSOR_ADC_COMMENT_ID, PREDECESSOR_ADC_SHA256),
            (REWORK_ADC_COMMENT_ID, REWORK_ADC_SHA256),
            (RECOVERY_ADC_COMMENT_ID, RECOVERY_ADC_SHA256),
            (TIMESTAMP_RECOVERY_ADC_COMMENT_ID, TIMESTAMP_RECOVERY_ADC_SHA256),
            (PATH_CORRECTION_ADC_COMMENT_ID, PATH_CORRECTION_ADC_SHA256),
            (CONTINUATION_ADC_COMMENT_ID, CONTINUATION_ADC_SHA256),
        )
        actual_chain = tuple((item.pointer.comment_id, item.contract.sha256) for item in chain)
        if (actual_chain != expected_chain
                or any(item.pointer.state != "approved" for item in chain)):
            raise PhaseReworkError("continuation ADC is not the complete exact six-generation approved chain")
        authorization, authorization_sha = parse_authorization(chain[1])
        recovery_authorization, recovery_sha = parse_authorization(chain[2])
        timestamp_recovery_authorization, timestamp_recovery_sha = (
            parse_timestamp_recovery_authorization(chain[3])
        )
        parse_path_correction_generation(chain[4])
        if (recovery_authorization.get("predecessor_adc_comment_id") != chain[1].pointer.comment_id
                or recovery_authorization.get("predecessor_adc_sha256") != chain[1].contract.sha256
                or timestamp_recovery_authorization.get("predecessor_adc_comment_id") != chain[2].pointer.comment_id
                or timestamp_recovery_authorization.get("predecessor_adc_sha256") != chain[2].contract.sha256
                or continuation_authorization.get("predecessor_adc_comment_id") != chain[4].pointer.comment_id
                or continuation_authorization.get("predecessor_adc_sha256") != chain[4].contract.sha256):
            raise PhaseReworkError("continuation authorization does not bind its exact approved predecessor chain")
        return (authorization, authorization_sha, recovery_authorization, recovery_sha,
                timestamp_recovery_authorization, timestamp_recovery_sha,
                continuation_authorization, continuation_sha, None, None, None, None, None)
    if current.pointer.comment_id == TIMESTAMP_RECOVERY_ADC_COMMENT_ID:
        timestamp_recovery_authorization, timestamp_recovery_sha = (
            parse_timestamp_recovery_authorization(current)
        )
        try:
            chain = verify_adc_forward_generations(
                github, ISSUE_NUMBER,
                prior_comment_id=PREDECESSOR_ADC_COMMENT_ID,
                prior_sha256=PREDECESSOR_ADC_SHA256,
                current_comment_id=current.pointer.comment_id,
                current_sha256=current.contract.sha256,
            )
        except ADCError as exc:
            raise PhaseReworkError(f"approved timestamp-recovery ADC chain readback failed: {exc}") from exc
        expected_chain = (
            (PREDECESSOR_ADC_COMMENT_ID, PREDECESSOR_ADC_SHA256),
            (REWORK_ADC_COMMENT_ID, REWORK_ADC_SHA256),
            (RECOVERY_ADC_COMMENT_ID, RECOVERY_ADC_SHA256),
            (TIMESTAMP_RECOVERY_ADC_COMMENT_ID, TIMESTAMP_RECOVERY_ADC_SHA256),
        )
        actual_chain = tuple((item.pointer.comment_id, item.contract.sha256) for item in chain)
        if actual_chain != expected_chain:
            raise PhaseReworkError("timestamp-recovery ADC is not the complete exact approved successor chain")
        authorization, authorization_sha = parse_authorization(chain[1])
        recovery_authorization, recovery_sha = parse_authorization(chain[2])
        if (recovery_authorization.get("predecessor_adc_comment_id") != chain[1].pointer.comment_id
                or recovery_authorization.get("predecessor_adc_sha256") != chain[1].contract.sha256
                or timestamp_recovery_authorization.get("predecessor_adc_comment_id") != chain[2].pointer.comment_id
                or timestamp_recovery_authorization.get("predecessor_adc_sha256") != chain[2].contract.sha256):
            raise PhaseReworkError("timestamp-recovery authorization does not bind its exact approved predecessor")
        return (authorization, authorization_sha, recovery_authorization, recovery_sha,
                timestamp_recovery_authorization, timestamp_recovery_sha,
                None, None, None, None, None, None, None)
    recovery_authorization, recovery_sha = parse_authorization(current)
    if current.pointer.comment_id != RECOVERY_ADC_COMMENT_ID:
        raise PhaseReworkError("current ADC is not an exact Issue #71 rework generation")
    try:
        chain = verify_adc_forward_generations(
            github, ISSUE_NUMBER,
            prior_comment_id=PREDECESSOR_ADC_COMMENT_ID,
            prior_sha256=PREDECESSOR_ADC_SHA256,
            current_comment_id=current.pointer.comment_id,
            current_sha256=current.contract.sha256,
        )
    except ADCError as exc:
        raise PhaseReworkError(f"approved recovery ADC chain readback failed: {exc}") from exc
    expected_chain = (
        (PREDECESSOR_ADC_COMMENT_ID, PREDECESSOR_ADC_SHA256),
        (REWORK_ADC_COMMENT_ID, REWORK_ADC_SHA256),
        (RECOVERY_ADC_COMMENT_ID, RECOVERY_ADC_SHA256),
    )
    actual_chain = tuple((item.pointer.comment_id, item.contract.sha256) for item in chain)
    if actual_chain != expected_chain:
        raise PhaseReworkError("recovery ADC is not the complete exact approved successor chain")
    authorization, authorization_sha = parse_authorization(chain[1])
    if (recovery_authorization.get("predecessor_adc_comment_id") != chain[1].pointer.comment_id
            or recovery_authorization.get("predecessor_adc_sha256") != chain[1].contract.sha256):
        raise PhaseReworkError("recovery authorization does not bind its exact approved predecessor")
    return (authorization, authorization_sha, recovery_authorization, recovery_sha,
            None, None, None, None, None, None, None, None, None)


def _label_names(issue: Mapping[str, Any]) -> tuple[str, ...]:
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PhaseReworkError("Issue label readback is incomplete")
    names = [row.get("name") for row in rows]
    if any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
        raise PhaseReworkError("Issue labels are malformed or duplicated")
    return tuple(sorted(names))


def _issue(github: GitHub, *, expected_labels: tuple[str, ...] | None = None) -> tuple[dict[str, Any], tuple[str, ...]]:
    try:
        issue = github.issue(ISSUE_NUMBER)
    except GitHubError as exc:
        raise PhaseReworkError(f"Issue #71 readback failed: {exc}") from exc
    if (not isinstance(issue, dict) or issue.get("number") != ISSUE_NUMBER or issue.get("id") != ISSUE_ID
            or issue.get("state") != "open" or issue.get("pull_request") is not None
            or issue.get("repository_url") != f"https://api.github.com/repos/{REPOSITORY}"
            or not isinstance(issue.get("body"), str)
            or hashlib.sha256(issue["body"].encode("utf-8")).hexdigest() != ISSUE_BODY_SHA256):
        raise PhaseReworkError("Issue #71 identity, body, or state differs from the approved marker")
    labels = _label_names(issue)
    if expected_labels is not None and labels != expected_labels:
        raise PhaseReworkError("Issue #71 full labels differ from the expected rework state")
    return issue, labels


def _pr(github: GitHub, head_sha40: str) -> dict[str, Any]:
    try:
        pull = github.pull_request(PR_NUMBER)
    except GitHubError as exc:
        raise PhaseReworkError(f"PR #75 readback failed: {exc}") from exc
    base = pull.get("base") if isinstance(pull, dict) else None
    head = pull.get("head") if isinstance(pull, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    if (not isinstance(pull, dict) or pull.get("number") != PR_NUMBER or pull.get("state") != "open"
            or pull.get("draft") is not False or pull.get("merged_at") is not None
            or not isinstance(base, dict) or base.get("ref") != PR_BASE_REF
            or base.get("sha") != PR_BASE_SHA40 or not isinstance(head, dict)
            or head.get("ref") != BRANCH_REF or head.get("sha") != head_sha40
            or not isinstance(base_repo, dict) or base_repo.get("id") != REPOSITORY_ID
            or not isinstance(head_repo, dict) or head_repo.get("full_name", "").casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("PR #75 is not the exact open, non-draft bootstrap subject")
    if head_repo.get("id") != REPOSITORY_ID:
        raise PhaseReworkError("PR #75 head repository stable ID differs from the pinned repository")
    return pull


def _reader_continuation_allowed_labels(live: _Live) -> set[tuple[str, ...]]:
    phases = {"design", "ready", "execution"}
    if _has_issue71_current_combined_marker(live.current_adc):
        phases.update({"verification", "user-review"})
    if _has_issue71_timestamp_continuation_marker(live.current_adc):
        authorization, _marker_sha = parse_timestamp_continuation_authorization(live.current_adc)
        edges = authorization["phase_edges"]
        # The current approved contract owns the legal phase graph. Include both
        # edge endpoints so the exact starting phase and every authorized next
        # state are accepted by all inherited continuation readers.
        phases = {phase for edge in edges for phase in edge}
    return {
        tuple(sorted(("enhancement", "kind:single", f"phase:{phase}")))
        for phase in phases
    }


def _validate_reader_continuation_subject(live: _Live) -> None:
    authorization = live.reader_continuation_authorization
    if authorization is None:
        return
    allowed_labels = _reader_continuation_allowed_labels(live)
    body = live.issue.get("body")
    if (not isinstance(body, str) or authorization != READER_CONTINUATION_AUTHORIZATION
            or live.reader_continuation_authorization_sha256 != READER_CONTINUATION_AUTH_MARKER_SHA256
            or hashlib.sha256(body.encode("utf-8")).hexdigest() != authorization["current_issue_body_sha256"]):
        raise PhaseReworkError("reader-continuation Issue or marker differs from its exact approved identity")
    pull = live.pr
    if (live.labels not in allowed_labels or live.branch_ref != authorization["branch_ref"]
            or pull.get("title") != PR_TITLE or not isinstance(pull.get("body"), str)
            or hashlib.sha256(pull["body"].encode("utf-8")).hexdigest()
            != authorization["pr_body_sha256"]):
        raise PhaseReworkError("reader-continuation labels, branch, or PR metadata differ from the exact marker")


def _validate_execution_receipt_reader_continuation_subject(live: _Live) -> None:
    authorization = live.execution_receipt_reader_continuation_authorization
    if authorization is None:
        return
    allowed_labels = _reader_continuation_allowed_labels(live)
    body = live.issue.get("body")
    if (not isinstance(body, str)
            or authorization != EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION
            or live.execution_receipt_reader_continuation_authorization_sha256
            != EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256
            or hashlib.sha256(body.encode("utf-8")).hexdigest()
            != authorization["current_issue_body_sha256"]):
        raise PhaseReworkError(
            "execution-receipt reader Issue or marker differs from its exact approved identity"
        )
    pull = live.pr
    if (live.labels not in allowed_labels or live.branch_ref != authorization["branch_ref"]
            or pull.get("title") != PR_TITLE or not isinstance(pull.get("body"), str)
            or hashlib.sha256(pull["body"].encode("utf-8")).hexdigest()
            != authorization["pr_body_sha256"]):
        raise PhaseReworkError(
            "execution-receipt reader labels, branch, or PR metadata differ from the exact marker"
        )


def _validate_post_rework_labels(labels: tuple[str, ...]) -> None:
    if labels == tuple(sorted(LABELS_AFTER)):
        return
    phases = [label for label in labels if label.startswith("phase:")]
    kinds = [label for label in labels if label.startswith("kind:")]
    recognized_phases = {
        "phase:requirements", "phase:specification", "phase:design", "phase:ready",
        "phase:verification", "phase:execution", "phase:integration", "phase:user-review",
    }
    if (len(phases) != 1 or phases[0] not in recognized_phases
            or kinds != ["kind:single"] or "enhancement" not in labels):
        raise PhaseReworkError("post-rework Issue labels do not have one active forward phase")


def _verify_commit_set(root: Path, head: str, allowlist: tuple[str, ...]) -> None:
    if head == BASELINE_HEAD or not is_ancestor(root, BASELINE_HEAD, head):
        raise PhaseReworkError("bootstrap HEAD must be a descendant of the exact pre-bootstrap baseline")
    rows = run_git(root, "rev-list", "--reverse", f"{BASELINE_HEAD}..{head}").splitlines()
    if not 1 <= len(rows) <= 3 or len(rows) > AUTHORIZATION["max_bootstrap_commits"]:
        raise PhaseReworkError("bootstrap must contain one to three descendant commits")
    parent = BASELINE_HEAD
    for commit in rows:
        if not SHA40.fullmatch(commit) or commit_parents_sha40(root, commit) != (parent,):
            raise PhaseReworkError("bootstrap commit chain contains a merge or unexpected parent")
        changed = changed_paths_between(root, parent, commit)
        if not changed or any(path not in allowlist for path in changed):
            raise PhaseReworkError("bootstrap commit changes a path outside the exact allowlist")
        parent = commit
    if parent != head:
        raise PhaseReworkError("bootstrap commit enumeration does not end at the exact HEAD")


def _verify_execution_receipt_reader_commit_set(
    root: Path,
    head: str,
    recovery_authorization: Mapping[str, Any],
    timestamp_recovery_authorization: Mapping[str, Any] | None,
    continuation_authorization: Mapping[str, Any] | None,
    reader_continuation_authorization: Mapping[str, Any] | None,
    execution_receipt_reader_authorization: Mapping[str, Any],
) -> None:
    followup_head = execution_receipt_reader_authorization.get("starting_head_sha40")
    allowlist = execution_receipt_reader_authorization.get("followup_path_allowlist")
    if (execution_receipt_reader_authorization != EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION
            or followup_head != EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION[
                "starting_head_sha40"
            ]
            or execution_receipt_reader_authorization.get("max_followup_commits") != 1
            or allowlist != EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION[
                "followup_path_allowlist"
            ]
            or reader_continuation_authorization != READER_CONTINUATION_AUTHORIZATION
            or continuation_authorization != CONTINUATION_AUTHORIZATION
            or timestamp_recovery_authorization != TIMESTAMP_RECOVERY_AUTHORIZATION):
        raise PhaseReworkError(
            "execution-receipt reader marker differs from the exact follow-up commit tuple"
        )
    _verify_recovery_commit_set(
        root, followup_head, recovery_authorization, timestamp_recovery_authorization,
        continuation_authorization, reader_continuation_authorization,
    )
    if not is_ancestor(root, followup_head, head):
        raise PhaseReworkError(
            "execution-receipt reader HEAD must descend from its exact starting HEAD"
        )
    rows = run_git(root, "rev-list", "--reverse", f"{followup_head}..{head}").splitlines()
    if len(rows) != execution_receipt_reader_authorization["max_followup_commits"]:
        raise PhaseReworkError(
            "execution-receipt reader continuation must contain exactly one authorized commit"
        )
    if commit_parents_sha40(root, rows[0]) != (followup_head,):
        raise PhaseReworkError("execution-receipt reader commit has an unexpected parent")
    changed = changed_paths_between(root, followup_head, rows[0])
    if (not isinstance(allowlist, list) or len(allowlist) != len(set(allowlist))
            or not changed or any(path not in allowlist for path in changed)):
        raise PhaseReworkError(
            "execution-receipt reader commit changes a path outside its exact allowlist"
        )
    if rows[0] != head:
        raise PhaseReworkError("execution-receipt reader commit enumeration does not end at the exact HEAD")


def _verify_markdown_predecessor_reader_commit_set(
    root: Path,
    head: str,
    recovery_authorization: Mapping[str, Any],
    timestamp_recovery_authorization: Mapping[str, Any] | None,
    continuation_authorization: Mapping[str, Any] | None,
    reader_continuation_authorization: Mapping[str, Any] | None,
    execution_receipt_reader_authorization: Mapping[str, Any] | None,
    markdown_predecessor_reader_authorization: Mapping[str, Any],
) -> None:
    followup_head = markdown_predecessor_reader_authorization.get("starting_head_sha40")
    allowlist = markdown_predecessor_reader_authorization.get("followup_path_allowlist")
    if (markdown_predecessor_reader_authorization != MARKDOWN_PREDECESSOR_READER_AUTHORIZATION
            or execution_receipt_reader_authorization
            != EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION
            or followup_head != MARKDOWN_PREDECESSOR_READER_AUTHORIZATION["starting_head_sha40"]
            or markdown_predecessor_reader_authorization.get("max_followup_commits") != 1
            or allowlist != MARKDOWN_PREDECESSOR_READER_AUTHORIZATION["followup_path_allowlist"]
            or reader_continuation_authorization != READER_CONTINUATION_AUTHORIZATION
            or continuation_authorization != CONTINUATION_AUTHORIZATION
            or timestamp_recovery_authorization != TIMESTAMP_RECOVERY_AUTHORIZATION):
        raise PhaseReworkError(
            "Markdown predecessor reader marker differs from the exact follow-up commit tuple"
        )
    _verify_execution_receipt_reader_commit_set(
        root, followup_head, recovery_authorization, timestamp_recovery_authorization,
        continuation_authorization, reader_continuation_authorization,
        execution_receipt_reader_authorization,
    )
    if not is_ancestor(root, followup_head, head):
        raise PhaseReworkError(
            "Markdown predecessor reader HEAD must descend from its exact starting HEAD"
        )
    rows = run_git(root, "rev-list", "--reverse", f"{followup_head}..{head}").splitlines()
    if len(rows) != markdown_predecessor_reader_authorization["max_followup_commits"]:
        raise PhaseReworkError(
            "Markdown predecessor reader continuation must contain exactly one authorized commit"
        )
    if commit_parents_sha40(root, rows[0]) != (followup_head,):
        raise PhaseReworkError("Markdown predecessor reader commit has an unexpected parent")
    changed = changed_paths_between(root, followup_head, rows[0])
    if (not isinstance(allowlist, list) or len(allowlist) != len(set(allowlist))
            or not changed or any(path not in allowlist for path in changed)):
        raise PhaseReworkError(
            "Markdown predecessor reader commit changes a path outside its exact allowlist"
        )
    if rows[0] != head:
        raise PhaseReworkError(
            "Markdown predecessor reader commit enumeration does not end at the exact HEAD"
        )


def _verify_approved_history_reader_commit_set(
    root: Path,
    head: str,
    recovery_authorization: Mapping[str, Any],
    timestamp_recovery_authorization: Mapping[str, Any] | None,
    continuation_authorization: Mapping[str, Any] | None,
    reader_continuation_authorization: Mapping[str, Any] | None,
    execution_receipt_reader_authorization: Mapping[str, Any] | None,
    markdown_predecessor_reader_authorization: Mapping[str, Any],
    approved_history_reader_authorization: Mapping[str, Any],
    historical_commit_segments: Sequence[Mapping[str, Any]],
    approved_history: Sequence[Mapping[str, Any]],
) -> None:
    if (approved_history_reader_authorization != APPROVED_HISTORY_READER_AUTHORIZATION
            or markdown_predecessor_reader_authorization
            != MARKDOWN_PREDECESSOR_READER_AUTHORIZATION
            or approved_history_reader_authorization.get("starting_head_sha40")
            != "d1704c125d4de49e84ffffceb14756c9cc555962"
            or approved_history_reader_authorization.get("max_followup_commits") != 1
            or approved_history_reader_authorization.get("followup_path_allowlist")
            != APPROVED_HISTORY_READER_AUTHORIZATION["followup_path_allowlist"]):
        raise PhaseReworkError(
            "approved-history authorization differs from the exact successor commit tuple"
        )
    predecessor_head = approved_history_reader_authorization["starting_head_sha40"]
    _verify_markdown_predecessor_reader_commit_set(
        root, predecessor_head, recovery_authorization, timestamp_recovery_authorization,
        continuation_authorization, reader_continuation_authorization,
        execution_receipt_reader_authorization, markdown_predecessor_reader_authorization,
    )
    _validate_historical_commit_segments(
        list(historical_commit_segments), list(approved_history), predecessor_head, head,
    )
    rows = run_git(root, "rev-list", "--reverse", f"{predecessor_head}..{head}").splitlines()
    expected_rows = [segment["commit_sha40"] for segment in historical_commit_segments]
    if rows != expected_rows:
        raise PhaseReworkError(
            "approved-history commit enumeration differs from the exact authorized segment map"
        )
    parent = predecessor_head
    for row, segment in zip(rows, historical_commit_segments):
        if commit_parents_sha40(root, row) != (parent,):
            raise PhaseReworkError("approved-history segment commit has an unexpected direct parent")
        changed = changed_paths_between(root, parent, row)
        if changed != tuple(segment["path_allowlist"]):
            raise PhaseReworkError(
                "approved-history segment changed paths differ from its exact path allowlist"
            )
        parent = row
    if parent != head:
        raise PhaseReworkError(
            "approved-history segment enumeration does not end at the exact current start HEAD"
        )


def _verify_recovery_commit_set(root: Path, head: str,
                                recovery_authorization: Mapping[str, Any],
                                timestamp_recovery_authorization: Mapping[str, Any] | None = None,
                                continuation_authorization: Mapping[str, Any] | None = None,
                                reader_continuation_authorization: Mapping[str, Any] | None = None,
                                execution_receipt_reader_authorization: Mapping[str, Any] | None = None,
                                markdown_predecessor_reader_authorization: Mapping[str, Any] | None = None,
                                approved_history_reader_authorization: Mapping[str, Any] | None = None,
                                historical_commit_segments: Sequence[Mapping[str, Any]] | None = None,
                                approved_history: Sequence[Mapping[str, Any]] | None = None) -> None:
    if approved_history_reader_authorization is not None:
        if (markdown_predecessor_reader_authorization is None
                or historical_commit_segments is None or approved_history is None):
            raise PhaseReworkError("approved-history lineage lacks its exact segment map and predecessor reader")
        _verify_approved_history_reader_commit_set(
            root, head, recovery_authorization, timestamp_recovery_authorization,
            continuation_authorization, reader_continuation_authorization,
            execution_receipt_reader_authorization, markdown_predecessor_reader_authorization,
            approved_history_reader_authorization, historical_commit_segments, approved_history,
        )
        return
    if markdown_predecessor_reader_authorization is not None:
        _verify_markdown_predecessor_reader_commit_set(
            root, head, recovery_authorization, timestamp_recovery_authorization,
            continuation_authorization, reader_continuation_authorization,
            execution_receipt_reader_authorization,
            markdown_predecessor_reader_authorization,
        )
        return
    if execution_receipt_reader_authorization is not None:
        _verify_execution_receipt_reader_commit_set(
            root, head, recovery_authorization, timestamp_recovery_authorization,
            continuation_authorization, reader_continuation_authorization,
            execution_receipt_reader_authorization,
        )
        return
    if reader_continuation_authorization is not None:
        followup_head = reader_continuation_authorization.get("starting_head_sha40")
        if (followup_head != READER_CONTINUATION_AUTHORIZATION["starting_head_sha40"]
                or reader_continuation_authorization.get("max_followup_commits") != 1
                or reader_continuation_authorization.get("followup_path_allowlist")
                != READER_CONTINUATION_AUTHORIZATION["followup_path_allowlist"]
                or continuation_authorization != CONTINUATION_AUTHORIZATION
                or timestamp_recovery_authorization != TIMESTAMP_RECOVERY_AUTHORIZATION):
            raise PhaseReworkError("reader-continuation marker differs from the exact follow-up commit tuple")
        _verify_recovery_commit_set(
            root, followup_head, recovery_authorization, timestamp_recovery_authorization,
            continuation_authorization,
        )
        if not is_ancestor(root, followup_head, head):
            raise PhaseReworkError("reader-continuation HEAD must descend from its exact starting HEAD")
        rows = run_git(root, "rev-list", "--reverse", f"{followup_head}..{head}").splitlines()
        if len(rows) != reader_continuation_authorization["max_followup_commits"]:
            raise PhaseReworkError("reader continuation must contain exactly one authorized follow-up commit")
        if commit_parents_sha40(root, rows[0]) != (followup_head,):
            raise PhaseReworkError("reader-continuation commit has an unexpected parent")
        changed = changed_paths_between(root, followup_head, rows[0])
        allowlist = reader_continuation_authorization["followup_path_allowlist"]
        if (not isinstance(allowlist, list) or len(allowlist) != len(set(allowlist))
                or not changed or any(path not in allowlist for path in changed)):
            raise PhaseReworkError("reader-continuation commit changes a path outside its exact allowlist")
        if rows[0] != head:
            raise PhaseReworkError("reader-continuation commit enumeration does not end at the exact HEAD")
        return
    if continuation_authorization is not None:
        followup_head = continuation_authorization.get("current_head_sha40")
        if (followup_head != "cb02a9fccfb988300dff82c5ad2ccfe946cd4dd3"
                or continuation_authorization.get("max_followup_commits") != 1
                or timestamp_recovery_authorization is None):
            raise PhaseReworkError("continuation marker differs from the exact follow-up commit tuple")
        _verify_recovery_commit_set(
            root, followup_head, recovery_authorization, timestamp_recovery_authorization,
        )
        if not is_ancestor(root, followup_head, head):
            raise PhaseReworkError("continuation HEAD must descend from its exact starting HEAD")
        rows = run_git(root, "rev-list", "--reverse", f"{followup_head}..{head}").splitlines()
        if len(rows) != continuation_authorization.get("max_followup_commits"):
            raise PhaseReworkError("continuation must contain exactly one authorized follow-up commit")
        if commit_parents_sha40(root, rows[0]) != (followup_head,):
            raise PhaseReworkError("continuation commit has an unexpected parent")
        changed = changed_paths_between(root, followup_head, rows[0])
        allowlist = continuation_authorization.get("followup_path_allowlist")
        if (not isinstance(allowlist, list) or len(allowlist) != len(set(allowlist))
                or not changed or any(path not in allowlist for path in changed)):
            raise PhaseReworkError("continuation commit changes a path outside its exact allowlist")
        if rows[0] != head:
            raise PhaseReworkError("continuation commit enumeration does not end at the exact HEAD")
        return
    if timestamp_recovery_authorization is not None:
        followup_head = timestamp_recovery_authorization.get("current_head_sha40")
        if (followup_head != "574d7970323840933c34c37e874ad1616d577a8a"
                or timestamp_recovery_authorization.get("max_followup_commits") != 1):
            raise PhaseReworkError("timestamp-recovery marker differs from the exact follow-up commit tuple")
        _verify_recovery_commit_set(root, followup_head, recovery_authorization)
        if not is_ancestor(root, followup_head, head):
            raise PhaseReworkError("timestamp-recovery HEAD must descend from its exact starting HEAD")
        rows = run_git(root, "rev-list", "--reverse", f"{followup_head}..{head}").splitlines()
        if len(rows) != timestamp_recovery_authorization.get("max_followup_commits"):
            raise PhaseReworkError("timestamp recovery must contain exactly one authorized follow-up commit")
        if commit_parents_sha40(root, rows[0]) != (followup_head,):
            raise PhaseReworkError("timestamp-recovery commit has an unexpected parent")
        changed = changed_paths_between(root, followup_head, rows[0])
        allowlist = timestamp_recovery_authorization.get("followup_path_allowlist")
        if (not isinstance(allowlist, list) or not changed
                or any(path not in allowlist for path in changed)):
            raise PhaseReworkError("timestamp-recovery commit changes a path outside its exact allowlist")
        if rows[0] != head:
            raise PhaseReworkError("timestamp-recovery commit enumeration does not end at the exact HEAD")
        return
    pre_recovery_head = recovery_authorization.get("pre_recovery_head_sha40")
    if (not isinstance(pre_recovery_head, str) or SHA40.fullmatch(pre_recovery_head) is None
            or pre_recovery_head != "4185a510054a2a8781659191c1a48178336f8571"
            or not is_ancestor(root, pre_recovery_head, head)):
        raise PhaseReworkError("recovery HEAD must descend from the exact pre-recovery HEAD")
    rows = run_git(root, "rev-list", "--reverse", f"{pre_recovery_head}..{head}").splitlines()
    if len(rows) != recovery_authorization.get("max_recovery_commits"):
        raise PhaseReworkError("recovery must contain exactly one authorized descendant commit")
    if commit_parents_sha40(root, rows[0]) != (pre_recovery_head,):
        raise PhaseReworkError("recovery commit has an unexpected parent")
    changed = changed_paths_between(root, pre_recovery_head, rows[0])
    allowlist = recovery_authorization.get("recovery_path_allowlist")
    if (not isinstance(allowlist, list) or not changed
            or any(path not in allowlist for path in changed)):
        raise PhaseReworkError("recovery commit changes a path outside its exact allowlist")


def _verify_issue71_commit_lineage(root: Path, head: str,
                                   authorization: Mapping[str, Any],
                                   recovery_authorization: Mapping[str, Any] | None,
                                   timestamp_recovery_authorization: Mapping[str, Any] | None,
                                   continuation_authorization: Mapping[str, Any] | None = None,
                                   reader_continuation_authorization: Mapping[str, Any] | None = None,
                                   execution_receipt_reader_authorization: Mapping[str, Any] | None = None,
                                   markdown_predecessor_reader_authorization: Mapping[str, Any] | None = None,
                                   approved_history_reader_authorization: Mapping[str, Any] | None = None,
                                   historical_commit_segments: Sequence[Mapping[str, Any]] | None = None,
                                   approved_history: Sequence[Mapping[str, Any]] | None = None) -> None:
    if recovery_authorization is not None:
        if ((continuation_authorization is not None or reader_continuation_authorization is not None
             or execution_receipt_reader_authorization is not None
             or markdown_predecessor_reader_authorization is not None
             or approved_history_reader_authorization is not None)
                and timestamp_recovery_authorization is None):
            raise PhaseReworkError("continuation lineage lacks the exact timestamp-recovery generation")
        if timestamp_recovery_authorization is None:
            allowlist = tuple(sorted(set(authorization["bootstrap_path_allowlist"])
                                     | set(recovery_authorization["recovery_path_allowlist"])))
            _verify_commit_set(root, head, allowlist)
        else:
            bootstrap_head = recovery_authorization.get("pre_recovery_head_sha40")
            if not isinstance(bootstrap_head, str) or SHA40.fullmatch(bootstrap_head) is None:
                raise PhaseReworkError("timestamp recovery lacks the exact original bootstrap boundary")
            _verify_commit_set(root, bootstrap_head,
                               tuple(authorization["bootstrap_path_allowlist"]))
        _verify_recovery_commit_set(
            root, head, recovery_authorization, timestamp_recovery_authorization,
            continuation_authorization, reader_continuation_authorization,
            execution_receipt_reader_authorization, markdown_predecessor_reader_authorization,
            approved_history_reader_authorization, historical_commit_segments, approved_history,
        )
    elif head != BASELINE_HEAD:
        _verify_commit_set(root, head, tuple(authorization["bootstrap_path_allowlist"]))


def _user_review_absent(root: Path) -> None:
    folder = root / ".p_ases" / "user-review" / str(ISSUE_NUMBER)
    if path_has_symlink(folder, root=root):
        raise PhaseReworkError("User Review state path traverses a symlink")
    if not folder.exists():
        return
    if not folder.is_dir():
        raise PhaseReworkError("User Review state path is not a directory")
    for candidate in folder.rglob("session.json"):
        if path_has_symlink(candidate, root=root) or candidate.is_file():
            raise PhaseReworkError("an Issue #71 User Review session already exists")


def _live(github: GitHub, root: Path, *, phase: str | None = None,
          require_clean: bool = True) -> _Live:
    from . import phase_epoch_rebaseline as epoch_module

    try:
        current = verify_adc(github, ISSUE_NUMBER)
        current_timestamp_continuation = _has_issue71_timestamp_continuation_marker(current)
        current_combined = (_has_issue71_current_combined_marker(current)
                            or current_timestamp_continuation)
        authorization, authorization_sha, recovery_authorization, recovery_sha, \
            timestamp_recovery_authorization, timestamp_recovery_sha, \
            continuation_authorization, continuation_sha, \
            reader_authorization, reader_sha, \
            execution_reader_authorization, execution_reader_sha, \
            combined_authorization = (
            _authorization_context(github, current)
        )
        if not current_combined:
            combined_authorization = None
        generation_authorization = (
            combined_authorization.get("phase_rework_generation_authorization")
            if isinstance(combined_authorization, dict)
            and combined_authorization.get("schema") == ISSUE71_PHASE_AND_USER_REVIEW_V3_SCHEMA
            else None
        )
        generation_authorization_sha256 = (
            hashlib.sha256(_canonical(generation_authorization).encode("utf-8")).hexdigest()
            if isinstance(generation_authorization, dict) else None
        )
        actor = github.authenticated_user()
        metadata = github.repository_metadata()
        if (not isinstance(actor, dict) or actor.get("id") != OWNER_ID or actor.get("type") != "User"
                or not isinstance(metadata, dict) or metadata.get("id") != REPOSITORY_ID
                or metadata.get("full_name", "").casefold() != REPOSITORY.casefold()):
            raise PhaseReworkError("authenticated owner or repository stable identity is not exact")
        issue, labels = _issue(github)
        if phase is not None:
            expected = tuple(sorted(LABELS_BEFORE if phase == "verification" else LABELS_AFTER))
            if labels != expected:
                raise PhaseReworkError("Issue #71 phase labels differ from the exact rework state")
        epoch, verified_again, origin, issue_from_epoch = epoch_module.read_epoch_origin(
            github, root, current,
        )
        if (verified_again.pointer != current.pointer
                or issue_from_epoch.get("body") != issue.get("body")
                or issue_from_epoch.get("state") != issue.get("state")
                or _label_names(issue_from_epoch) != labels
                or issue_from_epoch.get("repository_url") != issue.get("repository_url")):
            raise PhaseReworkError("Issue or ADC identity changed during epoch-origin readback")
        if (epoch.adc_comment_id != EPOCH_ORIGIN_ADC_COMMENT_ID
                or epoch.adc_sha256 != EPOCH_ORIGIN_ADC_SHA256
                or epoch.epoch_id != authorization["active_epoch_id"]
                or epoch.sha256 != authorization["active_epoch_sha256"]
                or epoch.applied_comment_id != authorization["active_phase_generation_comment_id"]
                or epoch.applied_body_sha256 != authorization["active_phase_generation_sha256"]):
            raise PhaseReworkError("active epoch origin or pre-rework Phase generation differs from the marker")
        branch = current_branch(root)
        head = head_sha40(root)
        markdown_predecessor_reader_authorization = (
            MARKDOWN_PREDECESSOR_READER_AUTHORIZATION
            if (current.pointer.comment_id in {
                    MARKDOWN_PREDECESSOR_READER_ADC_COMMENT_ID,
                    APPROVED_HISTORY_READER_ADC_COMMENT_ID,
                } or current_combined)
            else None
        )
        approved_history_reader_authorization = (
            APPROVED_HISTORY_READER_AUTHORIZATION
            if current.pointer.comment_id == APPROVED_HISTORY_READER_ADC_COMMENT_ID or current_combined
            else None
        )
        if branch != BRANCH_REF or not is_ancestor(root, BASELINE_HEAD, head):
            raise PhaseReworkError("local branch or HEAD differs from the authorized bootstrap ancestry")
        if require_clean and not worktree_clean(root):
            raise PhaseReworkError("phase rework requires a clean local worktree")
        pull = _pr(github, head)
        remote_head = remote_branch_sha(root, BRANCH_REF)
        if remote_head != head:
            raise PhaseReworkError("local bootstrap HEAD differs from the remote PR branch HEAD")
        if current_combined:
            lineage_head = combined_authorization["starting_head_sha40"]
            phase_authorization = combined_authorization["phase_receipt_reconciliation"]
            _verify_issue71_commit_lineage(
                root, lineage_head, authorization, recovery_authorization, timestamp_recovery_authorization,
                continuation_authorization, reader_authorization, execution_reader_authorization,
                markdown_predecessor_reader_authorization, approved_history_reader_authorization,
                phase_authorization["historical_commit_segments"],
                combined_authorization["approved_history"],
            )
            _verify_combined_followup_commit_set(root, head, combined_authorization)
            if current_timestamp_continuation:
                timestamp_continuation, _marker_sha = parse_timestamp_continuation_authorization(current)
                _verify_timestamp_continuation_commit_set(root, head, timestamp_continuation)
        else:
            _verify_issue71_commit_lineage(
                root, head, authorization, recovery_authorization, timestamp_recovery_authorization,
                continuation_authorization, reader_authorization, execution_reader_authorization,
                markdown_predecessor_reader_authorization, approved_history_reader_authorization,
            )
        live = _Live(current, epoch, issue, labels, branch, head, pull,
                     actor["id"], authorization_sha, root,
                     recovery_authorization, recovery_sha,
                     timestamp_recovery_authorization, timestamp_recovery_sha,
                     continuation_authorization, continuation_sha,
                     reader_authorization, reader_sha,
                     execution_reader_authorization, execution_reader_sha,
                     generation_authorization, generation_authorization_sha256,
                     (TIMESTAMP_CONTINUATION_ORIGIN_ADC[0]
                      if current_timestamp_continuation else None),
                     (TIMESTAMP_CONTINUATION_ORIGIN_ADC[1]
                      if current_timestamp_continuation else None),
                     (parse_timestamp_continuation_authorization(current)[0]["timestamp_policy"]
                      if current_timestamp_continuation else None))
        _validate_reader_continuation_subject(live)
        _validate_execution_receipt_reader_continuation_subject(live)
        return live
    except (ADCError, GitError, GitHubError, ValueError) as exc:
        raise PhaseReworkError(str(exc)) from exc


def _comment_fingerprint(row: Any, comment_id: int) -> tuple[Any, ...]:
    if (not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] != comment_id
            or not isinstance(row.get("body"), str)):
        raise PhaseReworkError("phase rework journal comment is malformed")
    author = row.get("user")
    if (not isinstance(author, dict) or author.get("type") != "User"
            or type(author.get("id")) is not int or author.get("id") != OWNER_ID
            or not isinstance(author.get("login"), str) or not author.get("login")):
        raise PhaseReworkError("phase rework journal actor is not the authenticated owner User")
    created, updated = row.get("created_at"), row.get("updated_at")
    if not isinstance(created, str) or updated != created:
        raise PhaseReworkError("phase rework journal comment was edited or has no stable timestamp")
    _strict_utc(created, "journal comment created_at")
    expected = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}",
        f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
    )
    actual = (row.get("issue_url"), row.get("html_url"), row.get("url"))
    if actual != expected:
        raise PhaseReworkError("phase rework journal comment URLs differ from Issue #71")
    return (comment_id, row["body"], created, updated, author["id"], author["login"].casefold(), *actual)


def _is_rework_candidate(body: str) -> bool:
    header = body.lstrip()
    offset = 0
    while offset < len(header) and header[offset] in "<!-/ >":
        offset += 1
    return header[offset:].startswith("PASES_ISSUE_VERIFICATION_REWORK_")


def _parse_record(row: Any, schema: str) -> PhaseReworkRecord:
    if not isinstance(row, dict):
        raise PhaseReworkError("phase rework journal row is malformed")
    comment_id = row.get("id")
    body = row.get("body")
    if type(comment_id) is not int or comment_id < 1 or not isinstance(body, str):
        raise PhaseReworkError("phase rework journal identity is malformed")
    start = f"<!-- {schema}\n"
    if not body.startswith(start) or not body.endswith("\n-->"):
        raise PhaseReworkError("phase rework journal marker framing is malformed")
    raw = body[len(start):-len("\n-->")]
    try:
        payload = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("phase rework journal JSON is malformed") from exc
    if schema == INTENT_SCHEMA:
        expected_fields = INTENT_FIELDS
    elif schema == APPLIED_SCHEMA:
        expected_fields = APPLIED_FIELDS
    elif schema == ISSUE71_REWORK_INTENT_V3_SCHEMA:
        expected_fields = ISSUE71_REWORK_INTENT_V3_FIELDS
    elif schema == ISSUE71_REWORK_APPLIED_V3_SCHEMA:
        expected_fields = ISSUE71_REWORK_APPLIED_V3_FIELDS
    else:
        raise PhaseReworkError("phase rework journal uses an unsupported generation schema")
    if (not isinstance(payload, dict) or set(payload) != expected_fields
            or payload.get("schema") != schema or _canonical(payload) != raw):
        raise PhaseReworkError("phase rework journal fields or canonical JSON are invalid")
    fingerprint = _comment_fingerprint(row, comment_id)
    return PhaseReworkRecord(comment_id, schema, payload, body, fingerprint[4], fingerprint[2])


def _read_history(github: GitHub) -> tuple[PhaseReworkRecord, ...]:
    try:
        first = github.issue_comments(ISSUE_NUMBER)
        first_rows: list[tuple[dict[str, Any], str]] = []
        for row in first:
            body = row.get("body") if isinstance(row, dict) else None
            if not isinstance(body, str):
                continue
            candidate = body.lstrip()
            if not _is_rework_candidate(body):
                continue
            schema = next((value for value in (
                               INTENT_SCHEMA, APPLIED_SCHEMA,
                               ISSUE71_REWORK_INTENT_V3_SCHEMA, ISSUE71_REWORK_APPLIED_V3_SCHEMA,
                           )
                           if candidate.startswith(f"<!-- {value}\n")), None)
            if schema is None or body != candidate:
                raise PhaseReworkError("malformed reserved Issue #71 phase rework marker")
            first_rows.append((row, schema))
        ids = [row.get("id") for row, _schema in first_rows]
        if any(type(value) is not int or value < 1 for value in ids) or ids != sorted(set(ids)):
            raise PhaseReworkError("phase rework comment history is duplicated or unordered")
        before = {comment_id: github.issue_comment(ISSUE_NUMBER, comment_id) for comment_id in ids}
        second = github.issue_comments(ISSUE_NUMBER)
        second_rows = []
        for row in second:
            body = row.get("body") if isinstance(row, dict) else None
            if isinstance(body, str) and _is_rework_candidate(body):
                second_rows.append(row)
        second_ids = [row.get("id") if isinstance(row, dict) else None for row in second_rows]
        if second_ids != ids:
            raise PhaseReworkError("phase rework journal changed during direct/list/direct readback")
        after = {comment_id: github.issue_comment(ISSUE_NUMBER, comment_id) for comment_id in ids}
    except GitHubError as exc:
        raise PhaseReworkError(f"phase rework journal readback failed: {exc}") from exc
    records: list[PhaseReworkRecord] = []
    for listed, schema in first_rows:
        comment_id = listed["id"]
        fingerprints = tuple(_comment_fingerprint(row, comment_id)
                             for row in (before[comment_id],
                                         next(row for row in second_rows if row.get("id") == comment_id),
                                         after[comment_id]))
        if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
            raise PhaseReworkError("phase rework journal comment changed during direct/list/direct readback")
        records.append(_parse_record(before[comment_id], schema))
    return tuple(records)


def _validate_intent(record: PhaseReworkRecord, live: _Live,
                     readiness: ReadinessResult | None = None, *,
                     allow_bootstrap_descendant: bool = False) -> None:
    payload = record.payload
    if (record.schema != INTENT_SCHEMA or set(payload) != INTENT_FIELDS
            or payload.get("schema") != INTENT_SCHEMA):
        raise PhaseReworkError("phase rework Intent has an invalid schema")
    expected = {
        "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER, "issue_id": ISSUE_ID,
        "adc_comment_id": REWORK_ADC_COMMENT_ID, "adc_sha256": REWORK_ADC_SHA256,
        "authorization_sha256": live.authorization_sha256,
        "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
        "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
        "epoch_origin_adc_comment_id": EPOCH_ORIGIN_ADC_COMMENT_ID,
        "epoch_origin_adc_sha256": EPOCH_ORIGIN_ADC_SHA256,
        "active_epoch_id": ACTIVE_EPOCH_ID, "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
        "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
        "baseline_head_sha40": BASELINE_HEAD,
        "bootstrap_head_sha40": payload.get("pr_head_sha40"),
        "branch_ref": BRANCH_REF, "pr_number": PR_NUMBER,
        "pr_base_ref": PR_BASE_REF, "pr_base_sha40": PR_BASE_SHA40,
        "pr_head_sha40": payload.get("bootstrap_head_sha40"),
        "issue_body_sha256": ISSUE_BODY_SHA256,
        "labels_before": LABELS_BEFORE, "labels_after": LABELS_AFTER,
        "from_phase": "verification", "to_phase": "requirements",
        "max_applications": 1, "owner_id": OWNER_ID, "executor_user_id": live.executor_user_id,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise PhaseReworkError(f"phase rework Intent field {key} differs from the live exact subject")
    bootstrap_head = payload.get("bootstrap_head_sha40")
    if (not isinstance(bootstrap_head, str) or SHA40.fullmatch(bootstrap_head) is None
            or payload.get("pr_head_sha40") != bootstrap_head
            or record.actor_id != live.executor_user_id or live.executor_user_id != OWNER_ID):
        raise PhaseReworkError("phase rework Intent author or bootstrap HEAD is invalid")
    if allow_bootstrap_descendant:
        if (not is_ancestor(live.root, BASELINE_HEAD, bootstrap_head)
                or not is_ancestor(live.root, bootstrap_head, live.head_sha40)):
            raise PhaseReworkError("active bootstrap HEAD is not on the current authorized branch ancestry")
    elif bootstrap_head != live.head_sha40:
        raise PhaseReworkError("phase rework Intent bootstrap HEAD differs from the exact live subject")
    _sha(payload.get("readiness_sha256"), "Intent Readiness SHA-256")
    subject_sha = _sha(payload.get("readiness_subject_sha256"), "Intent Readiness subject SHA-256")
    if payload["readiness_sha256"] == PRIOR_READINESS_SHA256:
        raise PhaseReworkError("historical Readiness cannot authorize the one-shot rework")
    _strict_utc(payload.get("created_at"), "Intent created_at")
    _validate_phase_event_timestamp(
        record.schema, payload.get("created_at"), record.created_at, live, "Intent",
    )
    if readiness is not None:
        _validate_readiness(readiness, live)
        if (readiness.sha256 != payload["readiness_sha256"]
                or readiness.subject.sha256 != subject_sha):
            raise PhaseReworkError("phase rework Intent differs from the fresh current Readiness")


def _validate_readiness(readiness: ReadinessResult, live: _Live) -> None:
    try:
        readiness.validate()
    except ValueError as exc:
        raise PhaseReworkError(f"fresh Review Readiness is invalid: {exc}") from exc
    subject = readiness.subject
    if (readiness.status != "PASS" or readiness.sha256 == PRIOR_READINESS_SHA256
            or subject.repository.casefold() != REPOSITORY.casefold()
            or subject.issue_number != ISSUE_NUMBER or subject.pr_number != PR_NUMBER
            or subject.adc_comment_id != live.current_adc.pointer.comment_id
            or subject.adc_sha256 != live.current_adc.contract.sha256
            or subject.pr_head_sha40 != live.head_sha40):
        raise PhaseReworkError("fresh PASS Readiness is stale or bound to another ADC/PR/HEAD")
    location = readiness_path(live.root, readiness)
    try:
        on_disk = read_readiness(location)
    except ValueError as exc:
        raise PhaseReworkError(f"fresh Readiness bytes are not durably available: {exc}") from exc
    if on_disk != readiness:
        raise PhaseReworkError("fresh Readiness file differs from the reported current result")


def _applied_timestamp_delta_seconds(applied_at: str, comment_created_at: str,
                                    max_skew_seconds: int) -> int:
    event_time = datetime.fromisoformat(_strict_utc(applied_at, "Applied applied_at")[:-1] + "+00:00")
    published_time = datetime.fromisoformat(
        _strict_utc(comment_created_at, "Applied comment created_at")[:-1] + "+00:00"
    )
    delta = int((published_time - event_time).total_seconds())
    if delta < 0 or delta > max_skew_seconds:
        raise PhaseReworkError("Applied event/publication timestamps exceed the authorized UTC skew")
    return delta


def _phase_event_publication_delta_seconds(
    event_time: Any, published_time: Any, max_skew_seconds: int, label: str,
) -> int:
    event = datetime.fromisoformat(_strict_utc(event_time, f"{label} event timestamp")[:-1] + "+00:00")
    published = datetime.fromisoformat(
        _strict_utc(published_time, f"{label} comment created_at")[:-1] + "+00:00"
    )
    delta = int((published - event).total_seconds())
    if delta < 0 or delta > max_skew_seconds:
        raise PhaseReworkError(
            f"{label} event/publication timestamps exceed the authorized UTC skew"
        )
    return delta


def _validate_phase_event_timestamp(
    schema: str, event_time: Any, published_time: Any, live: _Live, label: str,
) -> None:
    event = _strict_utc(event_time, f"{label} event timestamp")
    published = _strict_utc(published_time, f"{label} comment created_at")
    policy = live.timestamp_policy
    if policy is None:
        if event != published and label in {"V3 Applied", "Applied"}:
            raise PhaseReworkError(f"{label} event timestamp differs from its immutable Issue comment")
        return
    if (schema not in policy.get("applies_to", ())
            or policy.get("schema") != "PASES_ISSUE_PHASE_EVENT_PUBLICATION_WINDOW_V1"):
        raise PhaseReworkError("timestamp policy does not cover this phase-rework event schema")
    _phase_event_publication_delta_seconds(
        event, published, policy["max_skew_seconds"], label,
    )


def _validate_applied(applied: PhaseReworkRecord, intent: PhaseReworkRecord,
                      live: _Live, *, allow_bootstrap_descendant: bool = False) -> None:
    if (applied.schema != APPLIED_SCHEMA or applied.comment_id <= intent.comment_id
            or applied.actor_id != intent.actor_id
            or applied.payload.get("intent_comment_id") != intent.comment_id
            or applied.payload.get("intent_body_sha256") != intent.body_sha256):
        raise PhaseReworkError("phase rework Applied does not reference its exact Intent")
    applied_at = _strict_utc(applied.payload.get("applied_at"), "Applied applied_at")
    comment_created_at = _strict_utc(applied.created_at, "Applied comment created_at")
    timestamp_authorization = live.timestamp_recovery_authorization
    if live.timestamp_policy is not None:
        _validate_phase_event_timestamp(
            applied.schema, applied_at, comment_created_at, live, "Applied",
        )
    elif timestamp_authorization is None:
        if applied_at != comment_created_at:
            raise PhaseReworkError("phase rework Applied timestamp differs from its Issue comment")
    else:
        delta = _applied_timestamp_delta_seconds(
            applied_at, comment_created_at,
            timestamp_authorization["applied_max_skew_seconds"],
        )
        if (intent.comment_id != timestamp_authorization["intent_comment_id"]
                or intent.body_sha256 != timestamp_authorization["intent_body_sha256"]
                or applied.comment_id != timestamp_authorization["applied_comment_id"]
                or applied.body_sha256 != timestamp_authorization["applied_body_sha256"]
                or applied_at != timestamp_authorization["applied_at"]
                or comment_created_at != timestamp_authorization["applied_comment_created_at"]
                or delta != timestamp_authorization["applied_timestamp_delta_seconds"]):
            raise PhaseReworkError("Applied differs from the exact timestamp-recovery journal record")
    for key in COMMON_FIELDS:
        if applied.payload.get(key) != intent.payload.get(key):
            raise PhaseReworkError(f"phase rework Applied changed Intent field {key}")
    _validate_intent(intent, live, allow_bootstrap_descendant=allow_bootstrap_descendant)


def _active_rework_records(history: tuple[PhaseReworkRecord, ...],
                           current_adc: VerifiedADC,
                           generation: Mapping[str, Any] | None = None) -> tuple[PhaseReworkRecord | None,
                                                              PhaseReworkRecord | None]:
    if generation is not None:
        intent, applied = _active_v3_rework_records(history, current_adc, generation)
        if _has_issue71_timestamp_continuation_marker(current_adc):
            authorization, _marker_sha = parse_timestamp_continuation_authorization(current_adc)
            origin = authorization["phase_rework_origin"]
            if intent is None or applied is None:
                raise PhaseReworkError("timestamp continuation requires the exact already-applied V3 pair")
            for record, expected, field in (
                    (intent, origin["intent"], "created_at"),
                    (applied, origin["applied"], "applied_at")):
                event_time = record.payload.get(field)
                delta = _phase_event_publication_delta_seconds(
                    event_time, record.created_at, authorization["timestamp_policy"]["max_skew_seconds"],
                    record.schema,
                )
                if (record.comment_id != expected["comment_id"]
                        or record.schema != expected["schema"]
                        or len(record.body.encode("utf-8")) != expected["body_byte_length"]
                        or record.body_sha256 != expected["body_sha256"]
                        or record.created_at != expected["comment_created_at"]
                        or event_time != expected["event_time"]
                        or delta != expected["event_to_publication_delta_seconds"]):
                    raise PhaseReworkError(
                        "immutable V3 phase-rework record differs from the approved continuation tuple"
                    )
        return intent, applied
    if _has_issue71_current_combined_marker(current_adc):
        authorization = parse_issue71_phase_and_user_review_authorization(current_adc)
        generation = authorization.get("phase_rework_generation_authorization")
        if isinstance(generation, dict):
            return _active_v3_rework_records(history, current_adc, generation)
    if len(history) > 2:
        raise PhaseReworkError("Issue #71 phase rework has duplicate or unrelated records")
    intents = [row for row in history if row.schema == INTENT_SCHEMA]
    applied = [row for row in history if row.schema == APPLIED_SCHEMA]
    if len(intents) > 1 or len(applied) > 1:
        raise PhaseReworkError("Issue #71 phase rework Intent/Applied is duplicated")
    if applied and not intents:
        raise PhaseReworkError("phase rework Applied has no matching Intent")
    for row in history:
        if (row.payload.get("adc_comment_id") != REWORK_ADC_COMMENT_ID
                or row.payload.get("adc_sha256") != REWORK_ADC_SHA256):
            raise PhaseReworkError("phase rework journal belongs to another ADC generation")
    if intents and applied:
        if applied[0].comment_id <= intents[0].comment_id:
            raise PhaseReworkError("phase rework journal is not append-only")
    if current_adc.pointer.comment_id < REWORK_ADC_COMMENT_ID:
        raise PhaseReworkError("current ADC predates the authorized phase rework generation")
    return (intents[0] if intents else None, applied[0] if applied else None)


def _v3_rework_records(
    history: tuple[PhaseReworkRecord, ...], generation: Mapping[str, Any],
) -> tuple[PhaseReworkRecord | None, PhaseReworkRecord | None]:
    """Validate immutable V2 history and return the optional single V3 pair."""
    comment_ids = [row.comment_id for row in history]
    if comment_ids != sorted(set(comment_ids)):
        raise PhaseReworkError("Issue #71 phase-rework history is duplicated or out of order")
    v2_intents = [row for row in history if row.schema == INTENT_SCHEMA]
    v2_applied = [row for row in history if row.schema == APPLIED_SCHEMA]
    v3_intents = [row for row in history if row.schema == ISSUE71_REWORK_INTENT_V3_SCHEMA]
    v3_applied = [row for row in history if row.schema == ISSUE71_REWORK_APPLIED_V3_SCHEMA]
    if (len(v2_intents) != 1 or len(v2_applied) != 1
            or v2_intents[0].comment_id != generation["preserve_prior_v2_intent_comment_id"]
            or v2_intents[0].body_sha256 != generation["preserve_prior_v2_intent_body_sha256"]
            or v2_applied[0].comment_id != generation["preserve_prior_v2_applied_comment_id"]
            or v2_applied[0].body_sha256 != generation["preserve_prior_v2_applied_body_sha256"]
            or v2_applied[0].comment_id <= v2_intents[0].comment_id):
        raise PhaseReworkError("existing V2 Intent/Applied bytes differ from the immutable V3 preservation tuple")
    if (len(v3_intents) > 1 or len(v3_applied) > 1
            or (v3_applied and not v3_intents)):
        raise PhaseReworkError("V3 phase-rework Intent/Applied is duplicated or incomplete")
    if v3_intents and v3_intents[0].comment_id <= v2_applied[0].comment_id:
        raise PhaseReworkError("V3 phase-rework Intent does not follow the preserved V2 generation")
    if v3_applied and v3_applied[0].comment_id <= v3_intents[0].comment_id:
        raise PhaseReworkError("V3 phase-rework Applied is not append-only")
    if len(history) != 2 + len(v3_intents) + len(v3_applied):
        raise PhaseReworkError("Issue #71 phase-rework history contains an unrelated generation")
    return (v3_intents[0] if v3_intents else None,
            v3_applied[0] if v3_applied else None)


def _active_v3_rework_records(
    history: tuple[PhaseReworkRecord, ...], current_adc: VerifiedADC,
    generation: Mapping[str, Any],
) -> tuple[PhaseReworkRecord | None, PhaseReworkRecord | None]:
    v3_intent, v3_applied = _v3_rework_records(history, generation)
    if current_adc.pointer.comment_id < generation["predecessor_adc_comment_id"]:
        raise PhaseReworkError("current ADC predates the authorized V3 phase-rework generation")
    if v3_intent is not None or v3_applied is not None:
        return v3_intent, v3_applied
    # Keep the already completed V2 record as the active phase generation until
    # the authorized V3 pair has been applied.
    v2_intent = next(row for row in history if row.schema == INTENT_SCHEMA)
    v2_applied = next(row for row in history if row.schema == APPLIED_SCHEMA)
    return v2_intent, v2_applied


def _validate_recorded_readiness(root: Path, intent: PhaseReworkRecord) -> None:
    payload = intent.payload
    subject_sha = _sha(payload.get("readiness_subject_sha256"), "Readiness subject SHA-256")
    readiness_sha = _sha(payload.get("readiness_sha256"), "Readiness SHA-256")
    path = (Path(root).absolute() / ".p_ases" / "readiness" / str(ISSUE_NUMBER)
            / subject_sha / f"{readiness_sha}.json")
    try:
        readiness = read_readiness(path)
    except ValueError as exc:
        raise PhaseReworkError(f"the exact Readiness bound by the Intent is missing or invalid: {exc}") from exc
    if (readiness.status != "PASS" or readiness.sha256 != readiness_sha
            or readiness.subject.sha256 != subject_sha
            or readiness.subject.adc_comment_id != REWORK_ADC_COMMENT_ID
            or readiness.subject.adc_sha256 != REWORK_ADC_SHA256
            or readiness.subject.pr_number != PR_NUMBER
            or readiness.subject.pr_head_sha40 != payload.get("bootstrap_head_sha40")):
        raise PhaseReworkError("Intent-bound Readiness is not the exact fresh bootstrap PASS")


def _v3_intent_payload(live: _Live, readiness: ReadinessResult) -> dict[str, Any]:
    generation = live.phase_rework_generation_authorization
    if not isinstance(generation, dict):
        raise PhaseReworkError("current ADC has no V3 phase-rework authorization")
    if not isinstance(readiness, ReadinessResult):
        raise PhaseReworkError("V3 phase rework requires typed fresh Readiness")
    _validate_readiness(readiness, live)
    return {
        "schema": ISSUE71_REWORK_INTENT_V3_SCHEMA,
        "generation_number": generation["new_generation_number"],
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER,
        "issue_id": ISSUE_ID,
        "adc_comment_id": live.current_adc.pointer.comment_id,
        "adc_sha256": live.current_adc.contract.sha256,
        "authorization_sha256": live.phase_rework_generation_authorization_sha256,
        "predecessor_adc_comment_id": generation["predecessor_adc_comment_id"],
        "predecessor_adc_sha256": generation["predecessor_adc_sha256"],
        "epoch_origin_adc_comment_id": EPOCH_ORIGIN_ADC_COMMENT_ID,
        "epoch_origin_adc_sha256": EPOCH_ORIGIN_ADC_SHA256,
        "active_epoch_id": generation["active_epoch_id"],
        "active_epoch_sha256": generation["active_epoch_sha256"],
        "active_phase_generation_comment_id": generation["prior_phase_generation_comment_id"],
        "active_phase_generation_sha256": generation["prior_phase_generation_sha256"],
        "baseline_head_sha40": generation["starting_head_sha40"],
        "bootstrap_head_sha40": live.head_sha40,
        "branch_ref": generation["branch_ref"],
        "pr_number": generation["pr_number"],
        "pr_base_ref": generation["pr_base_ref"],
        "pr_base_sha40": generation["pr_base_sha40"],
        "pr_head_sha40": live.head_sha40,
        "readiness_sha256": readiness.sha256,
        "readiness_subject_sha256": readiness.subject.sha256,
        "issue_body_sha256": generation["current_issue_body_sha256"],
        "labels_before": generation["labels_before"],
        "labels_after": generation["labels_after"],
        "from_phase": generation["from_phase"],
        "to_phase": generation["to_phase"],
        "max_applications": generation["max_applications"],
        "owner_id": generation["owner_id"],
        "executor_user_id": live.executor_user_id,
        "created_at": _timestamp(),
    }


def _validate_v3_intent(
    intent: PhaseReworkRecord, live: _Live, *,
    readiness: ReadinessResult | None = None, allow_bootstrap_descendant: bool = False,
) -> None:
    generation = live.phase_rework_generation_authorization
    payload = intent.payload
    if not isinstance(generation, dict):
        raise PhaseReworkError("V3 phase-rework authorization is unavailable")
    if (intent.schema != ISSUE71_REWORK_INTENT_V3_SCHEMA
            or set(payload) != ISSUE71_REWORK_INTENT_V3_FIELDS
            or payload.get("schema") != ISSUE71_REWORK_INTENT_V3_SCHEMA
            or payload.get("generation_number") != generation["new_generation_number"]):
        raise PhaseReworkError("V3 phase-rework Intent schema or generation is invalid")
    origin_comment_id = (live.phase_rework_origin_adc_comment_id
                         if live.phase_rework_origin_adc_comment_id is not None
                         else live.current_adc.pointer.comment_id)
    origin_sha256 = (live.phase_rework_origin_adc_sha256
                     if live.phase_rework_origin_adc_sha256 is not None
                     else live.current_adc.contract.sha256)
    expected = {
        "schema": ISSUE71_REWORK_INTENT_V3_SCHEMA,
        "generation_number": generation["new_generation_number"],
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER,
        "issue_id": ISSUE_ID,
        "adc_comment_id": origin_comment_id,
        "adc_sha256": origin_sha256,
        "authorization_sha256": live.phase_rework_generation_authorization_sha256,
        "predecessor_adc_comment_id": generation["predecessor_adc_comment_id"],
        "predecessor_adc_sha256": generation["predecessor_adc_sha256"],
        "epoch_origin_adc_comment_id": EPOCH_ORIGIN_ADC_COMMENT_ID,
        "epoch_origin_adc_sha256": EPOCH_ORIGIN_ADC_SHA256,
        "active_epoch_id": generation["active_epoch_id"],
        "active_epoch_sha256": generation["active_epoch_sha256"],
        "active_phase_generation_comment_id": generation["prior_phase_generation_comment_id"],
        "active_phase_generation_sha256": generation["prior_phase_generation_sha256"],
        "baseline_head_sha40": generation["starting_head_sha40"],
        "bootstrap_head_sha40": payload.get("pr_head_sha40"),
        "branch_ref": generation["branch_ref"],
        "pr_number": generation["pr_number"],
        "pr_base_ref": generation["pr_base_ref"],
        "pr_base_sha40": generation["pr_base_sha40"],
        "pr_head_sha40": payload.get("bootstrap_head_sha40"),
        "readiness_sha256": payload.get("readiness_sha256"),
        "readiness_subject_sha256": payload.get("readiness_subject_sha256"),
        "issue_body_sha256": generation["current_issue_body_sha256"],
        "labels_before": generation["labels_before"],
        "labels_after": generation["labels_after"],
        "from_phase": generation["from_phase"],
        "to_phase": generation["to_phase"],
        "max_applications": generation["max_applications"],
        "owner_id": generation["owner_id"],
        "executor_user_id": live.executor_user_id,
        "created_at": payload.get("created_at"),
    }
    if payload != expected:
        raise PhaseReworkError("V3 phase-rework Intent differs from the exact ADC and active subject")
    if (intent.actor_id != live.executor_user_id or live.executor_user_id != OWNER_ID
            or live.phase_rework_generation_authorization_sha256
            != hashlib.sha256(_canonical(generation).encode("utf-8")).hexdigest()):
        raise PhaseReworkError("V3 phase-rework Intent author or authorization digest is invalid")
    bootstrap_head = payload.get("bootstrap_head_sha40")
    if (not isinstance(bootstrap_head, str) or SHA40.fullmatch(bootstrap_head) is None
            or payload.get("pr_head_sha40") != bootstrap_head):
        raise PhaseReworkError("V3 phase-rework Intent HEAD is malformed")
    if allow_bootstrap_descendant:
        if (not is_ancestor(live.root, generation["starting_head_sha40"], bootstrap_head)
                or not is_ancestor(live.root, bootstrap_head, live.head_sha40)):
            raise PhaseReworkError("V3 Intent HEAD is not on the exact authorized follow-up ancestry")
    elif bootstrap_head != live.head_sha40:
        raise PhaseReworkError("V3 Intent does not bind the exact current follow-up HEAD")
    _sha(payload.get("readiness_sha256"), "V3 Intent Readiness SHA-256")
    _sha(payload.get("readiness_subject_sha256"), "V3 Intent Readiness subject SHA-256")
    _strict_utc(payload.get("created_at"), "V3 Intent created_at")
    _validate_phase_event_timestamp(
        intent.schema, payload.get("created_at"), intent.created_at, live, "V3 Intent",
    )
    if readiness is not None:
        _validate_readiness(readiness, live)
        if (readiness.sha256 != payload["readiness_sha256"]
                or readiness.subject.sha256 != payload["readiness_subject_sha256"]):
            raise PhaseReworkError("V3 Intent differs from the fresh exact-subject Readiness")


def _validate_v3_applied(
    applied: PhaseReworkRecord, intent: PhaseReworkRecord, live: _Live,
    *, allow_bootstrap_descendant: bool = False,
) -> None:
    if (applied.schema != ISSUE71_REWORK_APPLIED_V3_SCHEMA
            or set(applied.payload) != ISSUE71_REWORK_APPLIED_V3_FIELDS
            or applied.comment_id <= intent.comment_id
            or applied.actor_id != intent.actor_id
            or applied.payload.get("generation_number") != intent.payload.get("generation_number")
            or applied.payload.get("intent_comment_id") != intent.comment_id
            or applied.payload.get("intent_body_sha256") != intent.body_sha256):
        raise PhaseReworkError("V3 phase-rework Applied does not reference its exact Intent")
    _validate_phase_event_timestamp(
        applied.schema, applied.payload.get("applied_at"), applied.created_at, live, "V3 Applied",
    )
    expected = {key: value for key, value in intent.payload.items() if key != "created_at"}
    expected.update({
        "schema": ISSUE71_REWORK_APPLIED_V3_SCHEMA,
        "intent_comment_id": intent.comment_id,
        "intent_body_sha256": intent.body_sha256,
        "applied_at": applied.payload.get("applied_at"),
    })
    if applied.payload != expected:
        raise PhaseReworkError("V3 phase-rework Applied changed the exact Intent payload")
    _validate_v3_intent(intent, live, allow_bootstrap_descendant=allow_bootstrap_descendant)


def _validate_v3_recorded_readiness(root: Path, intent: PhaseReworkRecord) -> None:
    payload = intent.payload
    subject_sha = _sha(payload.get("readiness_subject_sha256"), "V3 Readiness subject SHA-256")
    readiness_sha = _sha(payload.get("readiness_sha256"), "V3 Readiness SHA-256")
    path = (Path(root).absolute() / ".p_ases" / "readiness" / str(ISSUE_NUMBER)
            / subject_sha / f"{readiness_sha}.json")
    try:
        readiness = read_readiness(path)
    except ValueError as exc:
        raise PhaseReworkError(f"V3 Intent-bound Readiness is missing or invalid: {exc}") from exc
    if (readiness.status != "PASS" or readiness.sha256 != readiness_sha
            or readiness.subject.sha256 != subject_sha
            or readiness.subject.repository.casefold() != REPOSITORY.casefold()
            or readiness.subject.issue_number != ISSUE_NUMBER
            or readiness.subject.pr_number != PR_NUMBER
            or readiness.subject.adc_comment_id != intent.payload.get("adc_comment_id")
            or readiness.subject.adc_sha256 != intent.payload.get("adc_sha256")
            or readiness.subject.pr_head_sha40 != intent.payload.get("bootstrap_head_sha40")):
        raise PhaseReworkError("V3 Intent-bound Readiness is not the exact current PASS")


def _read_exact_attempt_marker(root: Path, operation: str,
                               payload_sha256: str) -> bool:
    path = _record_path(root, operation)
    if path_has_symlink(path, root=Path(root).resolve()):
        raise PhaseReworkError(f"{operation} attempt path traverses a symlink")
    if not path.exists():
        return False
    try:
        actual = path.read_bytes()
    except OSError as exc:
        raise PhaseReworkError(f"{operation} attempt marker cannot be read") from exc
    expected = (_canonical({
        "schema": "PASES_ISSUE_PHASE_REWORK_LOCAL_ATTEMPT_V1",
        "operation": operation,
        "payload_sha256": payload_sha256,
    }) + "\n").encode()
    if actual != expected:
        raise PhaseReworkError(f"{operation} attempt marker differs from the exact authorized payload")
    return True


def _validate_recovery_intent(intent: PhaseReworkRecord, live: _Live,
                              root: Path) -> None:
    recovery = live.recovery_authorization
    current_adc_id = live.current_adc.pointer.comment_id
    current_combined = _has_issue71_current_combined_marker(live.current_adc)
    timestamp_authorization = live.timestamp_recovery_authorization
    continuation_authorization = live.continuation_authorization
    reader_authorization = live.reader_continuation_authorization
    execution_reader_authorization = live.execution_receipt_reader_continuation_authorization
    markdown_predecessor_reader_authorization = None
    markdown_predecessor_reader_sha256 = None
    approved_history_reader_authorization = None
    approved_history_reader_marker_sha256 = None
    combined_authorization = None
    if current_adc_id == MARKDOWN_PREDECESSOR_READER_ADC_COMMENT_ID:
        (markdown_predecessor_reader_authorization,
         markdown_predecessor_reader_sha256) = (
            parse_markdown_predecessor_reader_authorization(live.current_adc)
        )
    elif current_adc_id == APPROVED_HISTORY_READER_ADC_COMMENT_ID:
        markdown_predecessor_reader_authorization = MARKDOWN_PREDECESSOR_READER_AUTHORIZATION
        markdown_predecessor_reader_sha256 = MARKDOWN_PREDECESSOR_READER_AUTH_MARKER_SHA256
        (approved_history_reader_authorization,
         approved_history_reader_marker_sha256) = (
            parse_approved_history_reader_authorization(live.current_adc)
        )
    elif current_combined:
        markdown_predecessor_reader_authorization = MARKDOWN_PREDECESSOR_READER_AUTHORIZATION
        markdown_predecessor_reader_sha256 = MARKDOWN_PREDECESSOR_READER_AUTH_MARKER_SHA256
        approved_history_reader_authorization = APPROVED_HISTORY_READER_AUTHORIZATION
        approved_history_reader_marker_sha256 = APPROVED_HISTORY_READER_AUTH_MARKER_SHA256
        combined_authorization = parse_issue71_phase_and_user_review_authorization(live.current_adc)
    if (recovery is None
            or (current_adc_id not in {
                RECOVERY_ADC_COMMENT_ID, TIMESTAMP_RECOVERY_ADC_COMMENT_ID,
                CONTINUATION_ADC_COMMENT_ID, READER_CONTINUATION_ADC_COMMENT_ID,
                EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID,
                MARKDOWN_PREDECESSOR_READER_ADC_COMMENT_ID,
                APPROVED_HISTORY_READER_ADC_COMMENT_ID,
            } and not current_combined)
            or (current_adc_id == RECOVERY_ADC_COMMENT_ID
                and (timestamp_authorization is not None or continuation_authorization is not None
                     or reader_authorization is not None or execution_reader_authorization is not None))
            or (current_adc_id == TIMESTAMP_RECOVERY_ADC_COMMENT_ID
                and (timestamp_authorization != TIMESTAMP_RECOVERY_AUTHORIZATION
                     or live.timestamp_recovery_authorization_sha256
                     != TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256
                     or continuation_authorization is not None or reader_authorization is not None
                     or execution_reader_authorization is not None))
            or (current_adc_id == CONTINUATION_ADC_COMMENT_ID
                and (timestamp_authorization != TIMESTAMP_RECOVERY_AUTHORIZATION
                     or live.timestamp_recovery_authorization_sha256
                     != TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256
                     or continuation_authorization != CONTINUATION_AUTHORIZATION
                     or live.continuation_authorization_sha256
                     != CONTINUATION_AUTH_MARKER_SHA256 or reader_authorization is not None
                     or execution_reader_authorization is not None))
            or (current_adc_id == READER_CONTINUATION_ADC_COMMENT_ID
                and (timestamp_authorization != TIMESTAMP_RECOVERY_AUTHORIZATION
                     or live.timestamp_recovery_authorization_sha256
                     != TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256
                     or continuation_authorization != CONTINUATION_AUTHORIZATION
                     or live.continuation_authorization_sha256 != CONTINUATION_AUTH_MARKER_SHA256
                     or reader_authorization != READER_CONTINUATION_AUTHORIZATION
                     or live.reader_continuation_authorization_sha256
                     != READER_CONTINUATION_AUTH_MARKER_SHA256
                     or execution_reader_authorization is not None))
            or (current_adc_id == EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID
                and (timestamp_authorization != TIMESTAMP_RECOVERY_AUTHORIZATION
                     or live.timestamp_recovery_authorization_sha256
                     != TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256
                     or continuation_authorization != CONTINUATION_AUTHORIZATION
                     or live.continuation_authorization_sha256 != CONTINUATION_AUTH_MARKER_SHA256
                     or reader_authorization != READER_CONTINUATION_AUTHORIZATION
                     or live.reader_continuation_authorization_sha256
                     != READER_CONTINUATION_AUTH_MARKER_SHA256
                     or execution_reader_authorization
                     != EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION
                     or live.execution_receipt_reader_continuation_authorization_sha256
                     != EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256))
            or ((current_adc_id in {
                    MARKDOWN_PREDECESSOR_READER_ADC_COMMENT_ID,
                    APPROVED_HISTORY_READER_ADC_COMMENT_ID,
            } or current_combined)
                and (timestamp_authorization != TIMESTAMP_RECOVERY_AUTHORIZATION
                     or live.timestamp_recovery_authorization_sha256
                     != TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256
                     or continuation_authorization != CONTINUATION_AUTHORIZATION
                     or live.continuation_authorization_sha256 != CONTINUATION_AUTH_MARKER_SHA256
                     or reader_authorization != READER_CONTINUATION_AUTHORIZATION
                     or live.reader_continuation_authorization_sha256
                     != READER_CONTINUATION_AUTH_MARKER_SHA256
                     or execution_reader_authorization
                     != EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION
                     or live.execution_receipt_reader_continuation_authorization_sha256
                     != EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256
                     or markdown_predecessor_reader_authorization
                     != MARKDOWN_PREDECESSOR_READER_AUTHORIZATION
                     or markdown_predecessor_reader_sha256
                     != MARKDOWN_PREDECESSOR_READER_AUTH_MARKER_SHA256
                     or (current_adc_id == MARKDOWN_PREDECESSOR_READER_ADC_COMMENT_ID
                         and (approved_history_reader_authorization is not None
                              or approved_history_reader_marker_sha256 is not None))
                     or (current_adc_id == APPROVED_HISTORY_READER_ADC_COMMENT_ID
                         and (approved_history_reader_authorization
                              != APPROVED_HISTORY_READER_AUTHORIZATION
                              or approved_history_reader_marker_sha256
                              != APPROVED_HISTORY_READER_AUTH_MARKER_SHA256))
                    or (current_combined
                         and (approved_history_reader_authorization
                              != APPROVED_HISTORY_READER_AUTHORIZATION
                              or approved_history_reader_marker_sha256
                              != APPROVED_HISTORY_READER_AUTH_MARKER_SHA256
                              or not isinstance(combined_authorization, dict)))))):
        raise PhaseReworkError("current ADC does not authorize pending Intent recovery")
    if (intent.comment_id != recovery["intent_comment_id"]
            or intent.body_sha256 != recovery["intent_body_sha256"]
            or intent.body != _record_body(INTENT_SCHEMA, intent.payload)
            or intent.payload.get("readiness_sha256") != recovery["intent_readiness_sha256"]
            or intent.payload.get("readiness_subject_sha256") != recovery["intent_readiness_subject_sha256"]):
        raise PhaseReworkError("pending Intent or original Readiness differs from the exact Recovery ADC tuple")
    _validate_intent(intent, live, allow_bootstrap_descendant=True)
    _validate_recorded_readiness(root, intent)
    if hashlib.sha256(_canonical(intent.payload).encode()).hexdigest() != recovery["intent_attempt_payload_sha256"]:
        raise PhaseReworkError("pending Intent payload differs from its one-shot local attempt binding")
    if not _read_exact_attempt_marker(
            root, "intent", recovery["intent_attempt_payload_sha256"]):
        raise PhaseReworkError("the original local Intent attempt marker is missing")


def _recovery_pr_binding_candidate(live: _Live) -> PRBinding:
    pull = live.pr
    if (pull.get("title") != PR_TITLE or not isinstance(pull.get("body"), str)
            or hashlib.sha256(pull["body"].encode("utf-8")).hexdigest() != PR_BODY_SHA256):
        raise PhaseReworkError("PR #75 title or body differs from the exact preserved Recovery subject")
    try:
        return PRBinding(
            REPOSITORY, ISSUE_NUMBER, live.current_adc.pointer.comment_id,
            live.current_adc.contract.sha256, BASE_SHA40, BRANCH_REF, PR_NUMBER,
            live.head_sha40, execution_epoch_sha256=live.epoch.sha256,
        ).validate()
    except (AttributeError, ValueError) as exc:
        raise PhaseReworkError(f"current Recovery PRBinding identity is invalid: {exc}") from exc


def _recovery_checkpoint_matches(checkpoint: WorkCheckpoint, binding: PRBinding) -> bool:
    return (
        checkpoint.execution_epoch_sha256 == ACTIVE_EPOCH_SHA256
        and checkpoint.execution_binding_sha256 is None
        and checkpoint.execution_adoption_sha256 is None
        and checkpoint.current_head_sha40 == binding.pr_head_sha40
        and checkpoint.worktree_clean is True
        and checkpoint.completed_stage == "pr"
        and checkpoint.artifact_digests == tuple(sorted((
            ("execution-epoch", ACTIVE_EPOCH_SHA256),
            ("pr-binding", binding.sha256),
        )))
    )


def _recovery_binding_history(github: GitHub, root: Path) -> list[tuple[Path, PRBinding]]:
    from .work import WorkError, read_pr_binding_history

    try:
        rows = read_pr_binding_history(root, ISSUE_NUMBER, github=github)
    except (WorkError, GitHubError, OSError, ValueError) as exc:
        raise PhaseReworkError(f"immutable PRBinding history is invalid: {exc}") from exc
    if not rows:
        raise PhaseReworkError("Recovery requires the existing immutable PRBinding history")
    for _path, row in rows:
        if (row.repository.casefold() != REPOSITORY.casefold()
                or row.issue_number != ISSUE_NUMBER or row.pr_number != PR_NUMBER
                or row.base_sha40 != BASE_SHA40 or row.branch_ref != BRANCH_REF
                or row.execution_epoch_sha256 != ACTIVE_EPOCH_SHA256
                or row.adoption_id is not None):
            raise PhaseReworkError("PRBinding history changes the frozen Issue #71 PR execution identity")
    return rows


def _verify_recovery_pr_binding(live: _Live, github: GitHub) -> tuple[PRBinding, Path, str]:
    from .work import WorkError, latest_checkpoint

    root = live.root
    candidate = _recovery_pr_binding_candidate(live)
    rows = _recovery_binding_history(github, root)
    latest_path, latest = rows[-1]
    if latest != candidate:
        raise PhaseReworkError("PRBinding does not name the current Recovery ADC and exact HEAD")
    try:
        checkpoint = latest_checkpoint(root, ISSUE_NUMBER)
    except (WorkError, OSError, ValueError) as exc:
        raise PhaseReworkError(f"Recovery PR checkpoint history is invalid: {exc}") from exc
    if checkpoint is None or not _recovery_checkpoint_matches(checkpoint[1], candidate):
        raise PhaseReworkError("PR checkpoint does not bind the current Recovery PRBinding and exact HEAD")
    return candidate, latest_path, checkpoint[1].sha256


def rebind_issue71_recovery_pr(github: GitHub, root: Path, issue_number: int) -> dict[str, Any]:
    """Append the exact Issue #71 Recovery PRBinding/checkpoint without a GitHub write."""
    if (type(issue_number) is not int or issue_number != ISSUE_NUMBER
            or github.repo.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("Recovery PR rebinding is fixed to puchinya/ai-agent-workflow Issue #71")
    root = Path(root).resolve()
    live = _live(github, root, require_clean=True)
    if live.recovery_authorization is None:
        raise PhaseReworkError("current ADC does not authorize Recovery PR rebinding")
    history = _read_history(github)
    intent, applied = _active_rework_records(history, live.current_adc)
    if intent is None:
        raise PhaseReworkError("Recovery PR rebinding requires the exact existing Intent")
    _validate_recovery_intent(intent, live, root)
    label_payload = _recovery_label_attempt_payload(intent)
    label_attempted = _read_exact_attempt_marker(
        root, "labels", hashlib.sha256(_canonical(label_payload).encode()).hexdigest(),
    )
    if applied is None:
        if live.labels != tuple(sorted(LABELS_BEFORE)):
            raise PhaseReworkError("pending Recovery PR rebinding requires the exact before-label state")
        if label_attempted:
            raise PhaseReworkError("pending Recovery PR rebinding is blocked after a label-attempt marker")
    else:
        if live.timestamp_recovery_authorization is None:
            raise PhaseReworkError("Applied Recovery PR rebinding requires the exact timestamp ADC")
        _validate_applied(applied, intent, live, allow_bootstrap_descendant=True)
        _validate_post_rework_labels(live.labels)
        _validate_recorded_readiness(root, intent)
        if not label_attempted:
            raise PhaseReworkError("Applied Recovery PR rebinding lacks the exact label-attempt marker")
        applied_payload_sha = hashlib.sha256(_canonical(applied.payload).encode()).hexdigest()
        if not _read_exact_attempt_marker(root, "applied", applied_payload_sha):
            raise PhaseReworkError("Applied Recovery PR rebinding lacks its exact Applied-attempt marker")

    candidate = _recovery_pr_binding_candidate(live)
    rows = _recovery_binding_history(github, root)
    latest_path, latest = rows[-1]
    from .work import (
        WorkError, _pr_binding_version_path, _same_pr_execution_identity,
        _verify_pr_binding_successor, latest_checkpoint,
    )
    try:
        if latest != candidate:
            if (not _same_pr_execution_identity(latest, candidate)
                    or not is_ancestor(root, latest.pr_head_sha40, candidate.pr_head_sha40)):
                raise PhaseReworkError("Recovery PRBinding is not a forward-only successor of its prior row")
            _verify_pr_binding_successor(github, ISSUE_NUMBER, latest, candidate)
        previous_checkpoint = latest_checkpoint(root, ISSUE_NUMBER)
    except (WorkError, GitError, GitHubError, OSError, ValueError) as exc:
        raise PhaseReworkError(f"Recovery PRBinding successor validation failed: {exc}") from exc

    # Re-read the complete live subject immediately before the first local append.
    fresh = _live(github, root, require_clean=True)
    fresh_history = _read_history(github)
    fresh_intent, fresh_applied = _active_rework_records(fresh_history, fresh.current_adc)
    if (fresh.recovery_authorization != live.recovery_authorization
            or fresh.recovery_authorization_sha256 != live.recovery_authorization_sha256
            or fresh.timestamp_recovery_authorization != live.timestamp_recovery_authorization
            or fresh.timestamp_recovery_authorization_sha256 != live.timestamp_recovery_authorization_sha256
            or fresh.continuation_authorization != live.continuation_authorization
            or fresh.continuation_authorization_sha256 != live.continuation_authorization_sha256
            or fresh.reader_continuation_authorization != live.reader_continuation_authorization
            or fresh.reader_continuation_authorization_sha256 != live.reader_continuation_authorization_sha256
            or fresh.execution_receipt_reader_continuation_authorization
            != live.execution_receipt_reader_continuation_authorization
            or fresh.execution_receipt_reader_continuation_authorization_sha256
            != live.execution_receipt_reader_continuation_authorization_sha256
            or fresh.current_adc.pointer != live.current_adc.pointer
            or fresh.current_adc.contract.sha256 != live.current_adc.contract.sha256
            or fresh.epoch.sha256 != live.epoch.sha256 or fresh.issue != live.issue
            or fresh.labels != live.labels or fresh.branch_ref != live.branch_ref
            or fresh.head_sha40 != live.head_sha40 or fresh.pr != live.pr
            or fresh_intent != intent or fresh_applied != applied):
        raise PhaseReworkError("Recovery PR subject changed immediately before immutable local binding")
    if (current_branch(root) != BRANCH_REF or head_sha40(root) != candidate.pr_head_sha40
            or not worktree_clean(root)
            or remote_branch_sha(root, BRANCH_REF) != candidate.pr_head_sha40
            or remote_branch_sha(root, BASE_REF) != BASE_SHA40):
        raise PhaseReworkError("local or remote refs changed before Recovery PRBinding append")

    if latest != candidate:
        try:
            write_pr_binding(
                _pr_binding_version_path(root, ISSUE_NUMBER, len(rows) + 1), candidate,
            )
        except (WorkError, OSError, ValueError) as exc:
            raise PhaseReworkError(f"could not append immutable Recovery PRBinding: {exc}") from exc
    try:
        current_checkpoint = latest_checkpoint(root, ISSUE_NUMBER)
        if current_checkpoint is not None and _recovery_checkpoint_matches(current_checkpoint[1], candidate):
            checkpoint_file, checkpoint = current_checkpoint
        else:
            expected_prior = latest if latest != candidate else (rows[-2][1] if len(rows) > 1 else None)
            if (expected_prior is None or previous_checkpoint is None
                    or previous_checkpoint[1].execution_epoch_sha256 != ACTIVE_EPOCH_SHA256
                    or previous_checkpoint[1].current_head_sha40 != expected_prior.pr_head_sha40
                    or previous_checkpoint[1].artifact_digests != tuple(sorted((
                        ("execution-epoch", ACTIVE_EPOCH_SHA256),
                        ("pr-binding", expected_prior.sha256),
                    )))):
                raise PhaseReworkError("prior PR checkpoint does not match the immutable binding predecessor")
            checkpoint = WorkCheckpoint(
                None, candidate.pr_head_sha40, True, "pr", tuple(sorted((
                    ("execution-epoch", ACTIVE_EPOCH_SHA256), ("pr-binding", candidate.sha256),
                ))), previous_checkpoint[1].step + 1,
                execution_epoch_sha256=ACTIVE_EPOCH_SHA256,
            ).validate()
            checkpoint_file = checkpoint_path(root, ISSUE_NUMBER, checkpoint.step)
            write_checkpoint(checkpoint_file, checkpoint)
    except (WorkError, GitError, OSError, ValueError) as exc:
        raise PhaseReworkError(f"could not append Recovery PR checkpoint: {exc}") from exc
    final_live = _live(github, root, require_clean=True)
    if (final_live.recovery_authorization != fresh.recovery_authorization
            or final_live.recovery_authorization_sha256 != fresh.recovery_authorization_sha256
            or final_live.timestamp_recovery_authorization != fresh.timestamp_recovery_authorization
            or final_live.timestamp_recovery_authorization_sha256
            != fresh.timestamp_recovery_authorization_sha256
            or final_live.continuation_authorization != fresh.continuation_authorization
            or final_live.continuation_authorization_sha256 != fresh.continuation_authorization_sha256
            or final_live.reader_continuation_authorization != fresh.reader_continuation_authorization
            or final_live.reader_continuation_authorization_sha256
            != fresh.reader_continuation_authorization_sha256
            or final_live.execution_receipt_reader_continuation_authorization
            != fresh.execution_receipt_reader_continuation_authorization
            or final_live.execution_receipt_reader_continuation_authorization_sha256
            != fresh.execution_receipt_reader_continuation_authorization_sha256
            or final_live.current_adc.pointer != fresh.current_adc.pointer
            or final_live.current_adc.contract.sha256 != fresh.current_adc.contract.sha256
            or final_live.epoch.sha256 != fresh.epoch.sha256 or final_live.issue != fresh.issue
            or final_live.labels != fresh.labels or final_live.branch_ref != fresh.branch_ref
            or final_live.head_sha40 != fresh.head_sha40 or final_live.pr != fresh.pr):
        raise PhaseReworkError("Recovery PR subject changed during immutable binding append")
    verified, binding_path, checkpoint_sha = _verify_recovery_pr_binding(final_live, github)
    if verified != candidate:
        raise PhaseReworkError("Recovery PRBinding/checkpoint direct readback differs from the append")
    return {
        "status": "PR_BOUND", "issue": ISSUE_NUMBER, "pr_number": PR_NUMBER,
        "adc_comment_id": live.current_adc.pointer.comment_id,
        "head_sha40": candidate.pr_head_sha40,
        "execution_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "pr_binding_sha256": candidate.sha256,
        "pr_binding_path": str(binding_path),
        "checkpoint_path": str(checkpoint_file), "checkpoint_sha256": checkpoint_sha,
        "github_writes": 0,
    }


def _recovery_label_attempt_payload(intent: PhaseReworkRecord) -> dict[str, Any]:
    return {
        "intent_comment_id": intent.comment_id,
        "intent_body_sha256": intent.body_sha256,
        "labels_before": LABELS_BEFORE,
        "labels_after": LABELS_AFTER,
        "schema": "PASES_ISSUE_PHASE_REWORK_LABEL_ATTEMPT_V1",
    }


def _record_body(schema: str, payload: Mapping[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(dict(payload))}\n-->"


def _record_path(root: Path, operation: str) -> Path:
    paths = {
        "intent": "phase-rework-v2", "labels": "phase-rework-v2", "applied": "phase-rework-v2",
        "intent_v3": "phase-rework-v3", "labels_v3": "phase-rework-v3",
        "applied_v3": "phase-rework-v3",
    }
    folder = paths.get(operation)
    if folder is None:
        raise PhaseReworkError("phase rework local attempt operation is invalid")
    return Path(root).resolve() / ".p_ases" / "state" / str(ISSUE_NUMBER) / folder / "attempts" / f"{operation}.json"


def _write_attempt_once(root: Path, operation: str, payload: Mapping[str, Any]) -> None:
    path = _record_path(root, operation)
    if path_has_symlink(path, root=Path(root).resolve()):
        raise PhaseReworkError("phase rework attempt path traverses a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (_canonical({"schema": "PASES_ISSUE_PHASE_REWORK_LOCAL_ATTEMPT_V1",
                        "operation": operation,
                        "payload_sha256": hashlib.sha256(_canonical(dict(payload)).encode()).hexdigest()}) + "\n").encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PhaseReworkError(f"{operation} was previously attempted; read-only recovery only") from exc
    except OSError as exc:
        raise PhaseReworkError(f"could not write the one-shot {operation} attempt marker") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise PhaseReworkError(f"could not durably write the one-shot {operation} attempt marker") from exc


def _post_record_once(github: GitHub, root: Path, schema: str,
                      payload: Mapping[str, Any], *,
                      before_write: Callable[[], None] | None = None) -> PhaseReworkRecord:
    body = _record_body(schema, payload)
    records = _read_history(github)
    matching = [record for record in records if record.schema == schema and record.body == body]
    if len(matching) == 1:
        return matching[0]
    if any(record.schema == schema for record in records):
        raise PhaseReworkError(f"a conflicting {schema} record already exists")
    operation = {
        INTENT_SCHEMA: "intent",
        APPLIED_SCHEMA: "applied",
        ISSUE71_REWORK_INTENT_V3_SCHEMA: "intent_v3",
        ISSUE71_REWORK_APPLIED_V3_SCHEMA: "applied_v3",
    }.get(schema)
    if operation is None:
        raise PhaseReworkError("phase rework writer does not support this record schema")
    if before_write is None:
        raise PhaseReworkError("phase rework comment write requires fresh subject validation")
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    try:
        before_write()
    except BaseException:
        refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
        raise
    _write_attempt_once(root, operation, payload)
    write_error: GitHubError | None = None
    created_id = None
    try:
        created = github.create_issue_comment(ISSUE_NUMBER, body)
        created_id = created.get("id") if isinstance(created, dict) else None
    except GitHubError as exc:
        write_error = exc
    finally:
        refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    try:
        after = _read_history(github)
    except PhaseReworkError as exc:
        if write_error is not None:
            raise PhaseReworkError(f"{operation} POST failed and readback is unavailable; no retry") from write_error
        raise
    matching = [record for record in after if record.schema == schema and record.body == body]
    if len(matching) != 1:
        reason = "POST outcome is ambiguous" if write_error else "POST has no unique exact readback"
        raise PhaseReworkError(f"{reason}; {operation} will not be retried")
    record = matching[0]
    if created_id is not None and created_id != record.comment_id:
        raise PhaseReworkError("POST Comment ID differs from direct/list/direct readback")
    if record.actor_id != payload.get("executor_user_id"):
        raise PhaseReworkError("phase rework comment author differs from its authenticated executor")
    return record


def _validate_label_attempt(root: Path, intent: PhaseReworkRecord) -> bool:
    path = _record_path(root, "labels")
    if path_has_symlink(path, root=Path(root).resolve()):
        raise PhaseReworkError("label attempt path traverses a symlink")
    return path.exists()


def _replace_issue_labels_at_boundary(
    github: GitHub, labels: Sequence[str], *, before_write: Callable[[], None],
) -> GitHubError | None:
    """Invalidate immutable-history reuse around a fully validated label PUT."""
    if not callable(before_write):
        raise PhaseReworkError("phase rework label write requires fresh subject validation")
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    try:
        before_write()
    except BaseException:
        refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
        raise
    write_error: GitHubError | None = None
    try:
        github.replace_issue_labels(ISSUE_NUMBER, list(labels))
    except GitHubError as exc:
        write_error = exc
    finally:
        refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    return write_error


def _replace_labels_once(github: GitHub, root: Path, intent: PhaseReworkRecord) -> None:
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    live = _live(github, root, phase="verification")
    recovery = live.recovery_authorization is not None
    if recovery:
        _validate_recovery_intent(intent, live, root)
    else:
        _validate_intent(intent, live)
        _validate_recorded_readiness(root, intent)
    _user_review_absent(root)
    issue, labels = live.issue, live.labels
    label_payload = _recovery_label_attempt_payload(intent)
    label_marker_exists = (
        _read_exact_attempt_marker(
            root, "labels", hashlib.sha256(_canonical(label_payload).encode()).hexdigest(),
        ) if recovery else _validate_label_attempt(root, intent)
    )
    if labels == tuple(sorted(LABELS_AFTER)):
        if recovery and not label_marker_exists:
            raise PhaseReworkError("after-label state lacks the one-shot label-attempt marker")
        return
    if labels != tuple(sorted(LABELS_BEFORE)):
        raise PhaseReworkError("Issue labels match neither the exact before nor after state")
    if label_marker_exists:
        raise PhaseReworkError("label PUT was previously attempted; read-only recovery only")

    def validate_before_label_write() -> None:
        current = _live(github, root, phase="verification")
        if recovery:
            _validate_recovery_intent(intent, current, root)
            current_payload = _recovery_label_attempt_payload(intent)
            current_attempt_exists = _read_exact_attempt_marker(
                root, "labels", hashlib.sha256(_canonical(current_payload).encode()).hexdigest(),
            )
        else:
            _validate_intent(intent, current)
            _validate_recorded_readiness(root, intent)
            current_attempt_exists = _validate_label_attempt(root, intent)
        _user_review_absent(root)
        if current_attempt_exists:
            raise PhaseReworkError("label PUT was previously attempted; read-only recovery only")
        _write_attempt_once(root, "labels", label_payload)

    write_error = _replace_issue_labels_at_boundary(
        github, LABELS_AFTER, before_write=validate_before_label_write,
    )
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    after, after_labels = _issue(github)
    if after_labels != tuple(sorted(LABELS_AFTER)):
        if after_labels == tuple(sorted(LABELS_BEFORE)) and write_error is not None:
            raise PhaseReworkError("label PUT failed with before-state unchanged; retry is prohibited") from write_error
        raise PhaseReworkError("label PUT outcome is not the exact authorized after-state")
    if after.get("body") != issue.get("body") or after.get("state") != "open":
        raise PhaseReworkError("Issue body or state changed during the phase rework label transition")


def _intent_payload(live: _Live, readiness: ReadinessResult) -> dict[str, Any]:
    if not isinstance(readiness, ReadinessResult):
        raise PhaseReworkError("phase rework requires a typed fresh Readiness result")
    _validate_readiness(readiness, live)
    return {
        "schema": INTENT_SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER,
        "issue_id": ISSUE_ID,
        "adc_comment_id": live.current_adc.pointer.comment_id,
        "adc_sha256": live.current_adc.contract.sha256,
        "authorization_sha256": live.authorization_sha256,
        "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
        "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
        "epoch_origin_adc_comment_id": EPOCH_ORIGIN_ADC_COMMENT_ID,
        "epoch_origin_adc_sha256": EPOCH_ORIGIN_ADC_SHA256,
        "active_epoch_id": ACTIVE_EPOCH_ID,
        "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
        "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
        "baseline_head_sha40": BASELINE_HEAD,
        "bootstrap_head_sha40": live.head_sha40,
        "branch_ref": BRANCH_REF,
        "pr_number": PR_NUMBER,
        "pr_base_ref": PR_BASE_REF,
        "pr_base_sha40": PR_BASE_SHA40,
        "pr_head_sha40": live.head_sha40,
        "readiness_sha256": readiness.sha256,
        "readiness_subject_sha256": readiness.subject.sha256,
        "issue_body_sha256": ISSUE_BODY_SHA256,
        "labels_before": LABELS_BEFORE,
        "labels_after": LABELS_AFTER,
        "from_phase": "verification",
        "to_phase": "requirements",
        "max_applications": 1,
        "owner_id": OWNER_ID,
        "executor_user_id": live.executor_user_id,
        "created_at": _timestamp(),
    }


def _applied_payload(intent: PhaseReworkRecord) -> dict[str, Any]:
    payload = {key: value for key, value in intent.payload.items() if key != "created_at"}
    payload["schema"] = APPLIED_SCHEMA
    payload["intent_comment_id"] = intent.comment_id
    payload["intent_body_sha256"] = intent.body_sha256
    payload["applied_at"] = _timestamp()
    return payload


def _check_labels_after(github: GitHub) -> None:
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    issue, labels = _issue(github, expected_labels=tuple(sorted(LABELS_AFTER)))
    if issue.get("state") != "open":
        raise PhaseReworkError("Issue #71 closed during the authorized phase transition")


def _ensure_active_record_context(live: _Live, record: PhaseReworkRecord, root: Path) -> None:
    payload = record.payload
    if (payload.get("bootstrap_head_sha40") != live.head_sha40
            or payload.get("pr_head_sha40") != live.head_sha40
            or live.branch_ref != BRANCH_REF):
        if (live.recovery_authorization is None
                or not is_ancestor(root, payload.get("bootstrap_head_sha40", ""), live.head_sha40)):
            raise PhaseReworkError("incomplete phase rework must remain on its exact authorized branch ancestry")
    if live.recovery_authorization is not None:
        _validate_recovery_intent(record, live, root)
    else:
        _validate_intent(record, live)
        _validate_recorded_readiness(root, record)


def active_phase_generation_for_epoch(github: GitHub, root: Path, current_adc: VerifiedADC,
                                      origin_epoch: Any, issue: Mapping[str, Any]) -> tuple[int, str]:
    """Return the active rework Applied generation or the immutable epoch Applied."""
    (_authorization, authorization_sha, recovery_authorization, recovery_sha,
     timestamp_recovery_authorization, timestamp_recovery_sha,
     continuation_authorization, continuation_sha,
     reader_authorization, reader_sha,
     execution_reader_authorization, execution_reader_sha,
     combined) = (
        _authorization_context(github, current_adc)
    )
    generation = (
        combined.get("phase_rework_generation_authorization")
        if isinstance(combined, dict)
        and combined.get("schema") == ISSUE71_PHASE_AND_USER_REVIEW_V3_SCHEMA
        else None
    )
    current_timestamp_continuation = _has_issue71_timestamp_continuation_marker(current_adc)
    timestamp_policy = (
        parse_timestamp_continuation_authorization(current_adc)[0]["timestamp_policy"]
        if current_timestamp_continuation else None
    )
    origin = TIMESTAMP_CONTINUATION_PHASE_REWORK_ORIGIN if current_timestamp_continuation else {}
    generation_sha = (
        hashlib.sha256(_canonical(generation).encode("utf-8")).hexdigest()
        if isinstance(generation, dict) else None
    )
    history = _read_history(github)
    intent, applied = _active_rework_records(history, current_adc, generation)
    issue_labels = _label_names(issue)
    if intent is None:
        if recovery_authorization is not None:
            raise PhaseReworkError("Recovery ADC has no exact pending phase rework Intent")
        if applied is not None or issue_labels != tuple(sorted(LABELS_BEFORE)):
            raise PhaseReworkError("Issue labels changed without the authorized rework Intent")
        if (origin_epoch.epoch_id != ACTIVE_EPOCH_ID
                or origin_epoch.sha256 != ACTIVE_EPOCH_SHA256
                or origin_epoch.applied_comment_id != ACTIVE_PHASE_COMMENT_ID
                or origin_epoch.applied_body_sha256 != ACTIVE_PHASE_SHA256):
            raise PhaseReworkError("immutable epoch-origin Phase generation differs from the marker")
        return origin_epoch.applied_comment_id, origin_epoch.applied_body_sha256
    root = Path(root).resolve()
    current_head = head_sha40(root)
    live = _Live(current_adc, origin_epoch, dict(issue), issue_labels, BRANCH_REF,
                 current_head, _pr(github, current_head), OWNER_ID,
                 authorization_sha, root, recovery_authorization, recovery_sha,
                 timestamp_recovery_authorization, timestamp_recovery_sha,
                 continuation_authorization, continuation_sha, reader_authorization, reader_sha,
                 execution_reader_authorization, execution_reader_sha,
                 generation, generation_sha,
                 origin.get("adc_comment_id"), origin.get("adc_sha256"), timestamp_policy)
    _validate_reader_continuation_subject(live)
    _validate_execution_receipt_reader_continuation_subject(live)
    if intent.schema == ISSUE71_REWORK_INTENT_V3_SCHEMA:
        _validate_v3_intent(intent, live, allow_bootstrap_descendant=True)
        if applied is None:
            raise PhaseReworkError("V3 phase rework has an incomplete Intent; phase operations are blocked")
        _validate_v3_applied(applied, intent, live, allow_bootstrap_descendant=True)
        _validate_post_rework_labels(issue_labels)
        bootstrap_head = intent.payload["bootstrap_head_sha40"]
        if (not is_ancestor(root, bootstrap_head, current_head)
                or current_branch(root) != BRANCH_REF):
            raise PhaseReworkError("active V3 rework is not on the exact authorized branch ancestry")
        _validate_v3_recorded_readiness(root, intent)
        return applied.comment_id, applied.body_sha256
    if recovery_authorization is not None:
        _validate_recovery_intent(intent, live, root)
    _validate_intent(intent, live, allow_bootstrap_descendant=True)
    if applied is None:
        raise PhaseReworkError("phase rework has an incomplete Intent; phase operations are blocked")
    _validate_applied(applied, intent, live, allow_bootstrap_descendant=True)
    _validate_post_rework_labels(issue_labels)
    bootstrap_head = intent.payload["bootstrap_head_sha40"]
    current_head = head_sha40(Path(root))
    if (not is_ancestor(Path(root), bootstrap_head, current_head)
            or current_branch(Path(root)) != BRANCH_REF):
        raise PhaseReworkError("active rework generation is not on the current epoch-3 branch ancestry")
    _validate_recorded_readiness(Path(root), intent)
    return applied.comment_id, applied.body_sha256


def _write_applied(github: GitHub, root: Path, intent: PhaseReworkRecord,
                   live: _Live) -> PhaseReworkRecord:
    _check_labels_after(github)
    fresh = _live(github, root, phase="requirements", require_clean=False)
    if fresh.recovery_authorization is not None:
        _validate_recovery_intent(intent, fresh, root)
        label_payload = _recovery_label_attempt_payload(intent)
        if not _read_exact_attempt_marker(
                root, "labels", hashlib.sha256(_canonical(label_payload).encode()).hexdigest()):
            raise PhaseReworkError("Applied cannot be written without the exact one-shot label attempt record")
    else:
        _validate_intent(intent, fresh)
        if _validate_label_attempt(root, intent) is False:
            raise PhaseReworkError("Applied cannot be written without the one-shot label attempt record")

    def validate_applied_subject_before_write() -> None:
        current = _live(github, root, phase="requirements", require_clean=False)
        if current.recovery_authorization is not None:
            _validate_recovery_intent(intent, current, root)
            label_payload = _recovery_label_attempt_payload(intent)
            if not _read_exact_attempt_marker(
                root, "labels", hashlib.sha256(_canonical(label_payload).encode()).hexdigest(),
            ):
                raise PhaseReworkError("Applied cannot be written without the exact one-shot label attempt record")
        else:
            _validate_intent(intent, current)
            if _validate_label_attempt(root, intent) is False:
                raise PhaseReworkError("Applied cannot be written without the one-shot label attempt record")
            _validate_recorded_readiness(root, intent)
        _user_review_absent(root)

    applied = _post_record_once(
        github, root, APPLIED_SCHEMA, _applied_payload(intent),
        before_write=validate_applied_subject_before_write,
    )
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    final_live = _live(github, root, phase="requirements", require_clean=False)
    _validate_applied(
        applied, intent, final_live,
        allow_bootstrap_descendant=final_live.recovery_authorization is not None,
    )
    return applied


def _verify_v3_subject(
    github: GitHub, root: Path, live: _Live, *, expected_labels: Sequence[str],
) -> None:
    """Recheck the V3 Issue, ADC, owner, PR, branch, base, and local HEAD."""
    try:
        current = verify_adc(github, ISSUE_NUMBER)
        _authorization_context(github, current)
        actor = github.authenticated_user()
        metadata = github.repository_metadata()
        issue, labels = _issue(github)
        branch = current_branch(root)
        head = head_sha40(root)
        pull = _pr(github, head)
        remote_head = remote_branch_sha(root, BRANCH_REF)
        remote_base = remote_branch_sha(root, BASE_REF)
    except (ADCError, GitError, GitHubError, ValueError) as exc:
        raise PhaseReworkError(f"V3 phase-rework subject readback failed: {exc}") from exc
    if (current.pointer != live.current_adc.pointer
            or current.contract.sha256 != live.current_adc.contract.sha256
            or not isinstance(actor, dict) or actor.get("id") != OWNER_ID or actor.get("type") != "User"
            or not isinstance(metadata, dict) or metadata.get("id") != REPOSITORY_ID
            or metadata.get("full_name", "").casefold() != REPOSITORY.casefold()
            or issue.get("repository_url") != live.issue.get("repository_url")
            or issue.get("number") != ISSUE_NUMBER
            or issue.get("body") != live.issue.get("body")
            or issue.get("state") != "open"
            or labels != tuple(sorted(expected_labels))
            or branch != BRANCH_REF or head != live.head_sha40
            or remote_head != head or remote_base != BASE_SHA40
            or not worktree_clean(root)):
        raise PhaseReworkError("V3 phase-rework exact subject or labels changed")
    pull_base = pull.get("base") if isinstance(pull, dict) else None
    pull_head = pull.get("head") if isinstance(pull, dict) else None
    if (pull.get("number") != PR_NUMBER or pull.get("state") != "open"
            or pull.get("draft") is not False or pull.get("merged_at") is not None
            or pull.get("title") != PR_TITLE
            or not isinstance(pull.get("body"), str)
            or hashlib.sha256(pull["body"].encode("utf-8")).hexdigest() != PR_BODY_SHA256
            or not isinstance(pull_base, dict) or pull_base.get("ref") != PR_BASE_REF
            or pull_base.get("sha") != PR_BASE_SHA40
            or not isinstance(pull_head, dict) or pull_head.get("ref") != BRANCH_REF
            or pull_head.get("sha") != head):
        raise PhaseReworkError("V3 phase-rework exact PR identity or refs changed")
    if (live.phase_rework_generation_authorization is None
            or live.phase_rework_generation_authorization_sha256
            != hashlib.sha256(_canonical(live.phase_rework_generation_authorization)
                              .encode("utf-8")).hexdigest()):
        raise PhaseReworkError("V3 phase-rework authorization digest changed")


def _v3_applied_payload(intent: PhaseReworkRecord) -> dict[str, Any]:
    payload = {key: value for key, value in intent.payload.items() if key != "created_at"}
    payload["schema"] = ISSUE71_REWORK_APPLIED_V3_SCHEMA
    payload["intent_comment_id"] = intent.comment_id
    payload["intent_body_sha256"] = intent.body_sha256
    payload["applied_at"] = _timestamp()
    return payload


def _apply_v3_phase_rework(
    github: GitHub, root: Path, live: _Live, history: tuple[PhaseReworkRecord, ...],
    readiness_factory: Callable[[], ReadinessResult] | None,
) -> dict[str, Any]:
    generation = live.phase_rework_generation_authorization
    if not isinstance(generation, dict):
        raise PhaseReworkError("current approved ADC does not authorize a V3 phase rework")
    intent, applied = _v3_rework_records(history, generation)
    if intent is not None:
        _validate_v3_intent(intent, live, allow_bootstrap_descendant=True)
        _validate_v3_recorded_readiness(root, intent)
        if applied is None:
            raise PhaseReworkError("V3 phase-rework records are partial; retry writes are prohibited")
        _validate_v3_applied(applied, intent, live, allow_bootstrap_descendant=True)
        if live.labels != tuple(sorted(generation["labels_after"])):
            raise PhaseReworkError("completed V3 phase rework has labels outside its exact after-state")
        return {"status": "NOOP", "issue": ISSUE_NUMBER,
                "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 0}

    if live.labels != tuple(sorted(generation["labels_before"])):
        raise PhaseReworkError("V3 rework is permitted only from its exact verification before-state")
    _user_review_absent(root)
    if readiness_factory is None:
        raise PhaseReworkError("fresh exact-subject Readiness evidence is required for V3 rework")
    readiness = readiness_factory()
    _validate_readiness(readiness, live)
    payload = _v3_intent_payload(live, readiness)
    intent_attempt_sha = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if _read_exact_attempt_marker(root, "intent_v3", intent_attempt_sha):
        raise PhaseReworkError("V3 Intent was previously attempted; read-only recovery only")
    for operation, marker_payload in (
        ("labels_v3", {"generation_number": generation["new_generation_number"]}),
        ("applied_v3", {"generation_number": generation["new_generation_number"]}),
    ):
        marker_sha = hashlib.sha256(_canonical(marker_payload).encode("utf-8")).hexdigest()
        if _read_exact_attempt_marker(root, operation, marker_sha):
            raise PhaseReworkError(f"V3 {operation} was previously attempted; read-only recovery only")

    def verify_intent_subject_before_write() -> None:
        fresh_readiness = readiness_factory()
        _validate_readiness(fresh_readiness, live)
        if fresh_readiness != readiness:
            raise PhaseReworkError("V3 Readiness changed immediately before the one-shot Intent")
        _verify_v3_subject(
            github, root, live, expected_labels=generation["labels_before"],
        )
        fresh_payload = _v3_intent_payload(live, fresh_readiness)
        stable_payload = {key: value for key, value in payload.items() if key != "created_at"}
        stable_fresh_payload = {key: value for key, value in fresh_payload.items() if key != "created_at"}
        if stable_fresh_payload != stable_payload:
            raise PhaseReworkError("V3 ADC, Issue, branch, PR, or Readiness changed before Intent")
        _user_review_absent(root)
        latest = _read_history(github)
        _v3_rework_records(latest, generation)
        if any(row.schema in {ISSUE71_REWORK_INTENT_V3_SCHEMA,
                              ISSUE71_REWORK_APPLIED_V3_SCHEMA} for row in latest):
            raise PhaseReworkError("V3 phase-rework journal changed before its first write")

    intent = _post_record_once(
        github, root, ISSUE71_REWORK_INTENT_V3_SCHEMA, payload,
        before_write=verify_intent_subject_before_write,
    )
    if not _read_exact_attempt_marker(
        root, "intent_v3", hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest(),
    ):
        raise PhaseReworkError("V3 Intent exact one-shot attempt marker is missing")
    _validate_v3_intent(intent, live, readiness=readiness)
    _validate_v3_recorded_readiness(root, intent)

    label_payload = {
        "schema": "PASES_ISSUE_PHASE_REWORK_LOCAL_ATTEMPT_V1",
        "operation": "labels_v3",
        "payload_sha256": hashlib.sha256(_canonical({
            "generation_number": generation["new_generation_number"],
            "intent_body_sha256": intent.body_sha256,
            "intent_comment_id": intent.comment_id,
            "labels_after": generation["labels_after"],
            "labels_before": generation["labels_before"],
        }).encode("utf-8")).hexdigest(),
    }
    label_attempt_sha = hashlib.sha256(_canonical(label_payload).encode("utf-8")).hexdigest()
    if _read_exact_attempt_marker(root, "labels_v3", label_attempt_sha):
        raise PhaseReworkError("V3 label write was previously attempted; retry is prohibited")
    def verify_v3_label_subject_before_write() -> None:
        _verify_v3_subject(github, root, live, expected_labels=generation["labels_before"])
        _validate_v3_intent(intent, live, readiness=readiness)
        _write_attempt_once(root, "labels_v3", {
            "generation_number": generation["new_generation_number"],
            "intent_body_sha256": intent.body_sha256,
            "intent_comment_id": intent.comment_id,
            "labels_after": generation["labels_after"],
            "labels_before": generation["labels_before"],
        })

    write_error = _replace_issue_labels_at_boundary(
        github, generation["labels_after"],
        before_write=verify_v3_label_subject_before_write,
    )
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    issue_after, labels_after = _issue(github)
    if (labels_after != tuple(sorted(generation["labels_after"]))
            or issue_after.get("body") != live.issue.get("body")
            or issue_after.get("state") != "open"):
        if labels_after == tuple(sorted(generation["labels_before"])) and write_error is not None:
            raise PhaseReworkError("V3 label PUT failed; retry is prohibited") from write_error
        raise PhaseReworkError("V3 label PUT did not produce its exact after-state")
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    _verify_v3_subject(github, root, live, expected_labels=generation["labels_after"])

    applied_payload = _v3_applied_payload(intent)
    applied_attempt_sha = hashlib.sha256(_canonical(applied_payload).encode("utf-8")).hexdigest()
    if _read_exact_attempt_marker(root, "applied_v3", applied_attempt_sha):
        raise PhaseReworkError("V3 Applied was previously attempted; retry is prohibited")

    def verify_applied_subject_before_write() -> None:
        _verify_v3_subject(github, root, live, expected_labels=generation["labels_after"])
        _validate_v3_intent(intent, live)
        _validate_v3_recorded_readiness(root, intent)
        rows = _read_history(github)
        current_intent, current_applied = _v3_rework_records(rows, generation)
        if current_intent != intent or current_applied is not None:
            raise PhaseReworkError("V3 phase-rework journal changed before Applied")

    applied = _post_record_once(
        github, root, ISSUE71_REWORK_APPLIED_V3_SCHEMA, applied_payload,
        before_write=verify_applied_subject_before_write,
    )
    _validate_v3_applied(applied, intent, live, allow_bootstrap_descendant=True)
    refresh_adc_forward_generation_session(github, ISSUE_NUMBER)
    final_live = _live(github, root, phase="requirements", require_clean=True)
    if (final_live.phase_rework_generation_authorization != generation
            or final_live.head_sha40 != live.head_sha40
            or final_live.current_adc.pointer != live.current_adc.pointer
            or final_live.labels != tuple(sorted(generation["labels_after"]))):
        raise PhaseReworkError("completed V3 rework failed its final exact-subject readback")
    return {"status": "APPLIED", "issue": ISSUE_NUMBER,
            "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
            "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 1}


def apply_issue71_phase_rework(
    github: GitHub,
    root: Path,
    issue_number: int,
    *,
    readiness_factory: Callable[[], ReadinessResult] | None = None,
) -> dict[str, Any]:
    """Apply or recover the one authorized verification-to-requirements rework."""
    if (type(issue_number) is not int or issue_number != ISSUE_NUMBER
            or github.repo.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("phase rework is fixed to puchinya/ai-agent-workflow Issue #71")
    root = Path(root).resolve()
    live = _live(github, root, require_clean=True)
    history = _read_history(github)
    if live.phase_rework_generation_authorization is not None:
        return _apply_v3_phase_rework(github, root, live, history, readiness_factory)
    intent, applied = _active_rework_records(history, live.current_adc)
    if live.recovery_authorization is not None:
        if intent is None:
            raise PhaseReworkError("Recovery ADC only authorizes its exact existing pending Intent")
        _validate_recovery_intent(intent, live, root)
        label_payload = _recovery_label_attempt_payload(intent)
        label_attempted = _read_exact_attempt_marker(
            root, "labels", hashlib.sha256(_canonical(label_payload).encode()).hexdigest(),
        )
        if applied is not None:
            _validate_applied(applied, intent, live, allow_bootstrap_descendant=True)
            _validate_post_rework_labels(live.labels)
            if not label_attempted:
                raise PhaseReworkError("Applied recovery lacks the exact label-attempt marker")
            if live.timestamp_recovery_authorization is not None:
                applied_payload_sha = hashlib.sha256(_canonical(applied.payload).encode()).hexdigest()
                if not _read_exact_attempt_marker(root, "applied", applied_payload_sha):
                    raise PhaseReworkError("Applied recovery lacks its exact Applied-attempt marker")
                _validate_recorded_readiness(root, intent)
                if readiness_factory is None:
                    return rebind_issue71_recovery_pr(github, root, issue_number)
            _verify_recovery_pr_binding(live, github)
            return {"status": "NOOP", "issue": ISSUE_NUMBER,
                    "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                    "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 0}
        if live.labels == tuple(sorted(LABELS_BEFORE)):
            if label_attempted:
                raise PhaseReworkError("label PUT was previously attempted; read-only recovery only")
            if readiness_factory is None:
                return rebind_issue71_recovery_pr(github, root, issue_number)
            _verify_recovery_pr_binding(live, github)
            _replace_labels_once(github, root, intent)
            _check_labels_after(github)
            applied = _write_applied(github, root, intent, live)
            return {"status": "RECOVERED", "issue": ISSUE_NUMBER,
                    "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                    "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 1}
        if live.labels == tuple(sorted(LABELS_AFTER)):
            if not label_attempted:
                raise PhaseReworkError("after-label state lacks the one-shot label-attempt marker")
            _verify_recovery_pr_binding(live, github)
            _ensure_active_record_context(live, intent, root)
            applied = _write_applied(github, root, intent, live)
            return {"status": "RECOVERED", "issue": ISSUE_NUMBER,
                    "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                    "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 0}
        raise PhaseReworkError("pending phase rework labels match neither exact state")
    if applied is not None:
        if intent is None:
            raise PhaseReworkError("phase rework Applied has no Intent")
        _validate_applied(applied, intent, live, allow_bootstrap_descendant=True)
        _validate_post_rework_labels(live.labels)
        _validate_recorded_readiness(root, intent)
        return {"status": "NOOP", "issue": ISSUE_NUMBER,
                "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 0}
    if intent is not None:
        if live.labels == tuple(sorted(LABELS_BEFORE)):
            raise PhaseReworkError("an Intent exists with before-labels unchanged; label PUT is never retried")
        if live.labels != tuple(sorted(LABELS_AFTER)):
            raise PhaseReworkError("pending phase rework labels match neither exact state")
        _ensure_active_record_context(live, intent, root)
        applied = _write_applied(github, root, intent, live)
        return {"status": "RECOVERED", "issue": ISSUE_NUMBER,
                "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 0}

    if live.labels != tuple(sorted(LABELS_BEFORE)):
        raise PhaseReworkError("new phase rework is permitted only from exact phase:verification labels")
    _user_review_absent(root)
    if readiness_factory is None:
        raise PhaseReworkError("fresh exact-subject Readiness evidence is required for first application")
    readiness = readiness_factory()
    _validate_readiness(readiness, live)
    payload = _intent_payload(live, readiness)
    if set(payload) != INTENT_FIELDS:
        raise PhaseReworkError("phase rework Intent payload fields are incomplete")

    def verify_intent_subject_before_write() -> None:
        # Readiness may take long enough for the mutable GitHub or local subject
        # to change. Re-evaluate the evidence, then make the complete live
        # identity read the final check before the one-shot marker and POST.
        fresh_readiness = readiness_factory()
        _validate_readiness(fresh_readiness, live)
        if fresh_readiness != readiness:
            raise PhaseReworkError("Readiness changed immediately before the one-shot Intent")
        fresh_live = _live(github, root, phase="verification", require_clean=True)
        _validate_readiness(fresh_readiness, fresh_live)
        fresh_payload = _intent_payload(fresh_live, fresh_readiness)
        stable_payload = {key: value for key, value in payload.items() if key != "created_at"}
        stable_fresh_payload = {key: value for key, value in fresh_payload.items() if key != "created_at"}
        if stable_fresh_payload != stable_payload:
            raise PhaseReworkError("Issue, ADC, branch, PR, or executor identity changed immediately before Intent")
        _user_review_absent(root)

    intent = _post_record_once(
        github, root, INTENT_SCHEMA, payload,
        before_write=verify_intent_subject_before_write,
    )

    # The just-recorded Intent makes the active epoch incomplete, so normal
    # Readiness recomputation is expected to block. Reuse the exact PASS that
    # the Intent binds, then reread the complete live subject before the PUT.
    before_labels = _live(github, root, phase="verification")
    _validate_intent(intent, before_labels)
    _validate_recorded_readiness(root, intent)
    _replace_labels_once(github, root, intent)
    _check_labels_after(github)
    applied = _write_applied(github, root, intent, before_labels)
    return {"status": "APPLIED", "issue": ISSUE_NUMBER,
            "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
            "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 1}
