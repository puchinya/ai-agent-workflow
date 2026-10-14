from __future__ import annotations

import hashlib
import json
import sys
import unittest.mock
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.gate_policy import (
    ActivationRecord, BootstrapIndependentReview, BootstrapReviewContextArtifact,
    BootstrapSelfReview, BootstrapSubject, VerifiedReviewEvidence,
    GatePolicyError, LocalCheck, ReviewFinding, ReviewItem, evaluate_bootstrap,
    parse_independent_review_comment, parse_self_review_comment, publish_immutable_record, read_review_comment,
    read_bootstrap_adc, read_bootstrap_evidence, select_gate,
    pin_gate_selection, read_gate_selection, read_latest_bootstrap_evidence,
    read_activation_record, _require_repository_owner_actor,
    _validate_activation_candidate, bootstrap_policy_digest, BootstrapResult,
    verify_bootstrap_review_evidence, verify_independent_context_artifact,
    run_local_bootstrap_checks_bound,
)
from p_ases.github import GitHubError
from p_ases.integration import IntegrationError, ParentGateEvidenceComment


REPO = "puchinya/ai-agent-workflow"
HEAD = "a" * 40
BASE = "b" * 40
ADC = "c" * 64


def subject(**overrides):
    values = dict(repository=REPO, issue_number=27, pr_number=33, adc_comment_id=100,
                  adc_sha256=ADC, base_ref="main", base_sha40=BASE,
                  head_ref="pases/adc-core", head_sha40=HEAD)
    values.update(overrides)
    return BootstrapSubject(**values)


def local_checks():
    names = ("compileall", "unittest", "dist-build-check", "dist-validation", "diff-check")
    return tuple(LocalCheck(name, ("python", name), "completed", 0, "d" * 64, False) for name in names)


def minimal_adc_bytes():
    return ("# Agent Development Contract — test\n\n"
            f"Repository: {REPO}\nIssue: 27\nChild key: adc-core\n\n"
            "## Issue\nA test child issue.\n\n"
            "## Scope\nValidate the legacy Bootstrap pointer.\n\n"
            "## Change Kind\nTesting only.\n\n"
            "## Requirements\n- REQ-01: Read exact ADC bytes.\n\n"
            "## Architecture Decisions\nNo architecture changes.\n\n"
            "## Artifact Impact\nNo artifacts.\n\n"
            "## Exact Changes\nRead the immutable comment.\n\n"
            "## Invariants\nPreserve exact bytes.\n\n"
            "## Non-goals\nDo not infer approval.\n\n"
            "## Verification Obligations\nVerify SHA-256.\n\n"
            "## Reviewer Checklist\n- [ ] Exact bytes are read back.\n\n"
            "## Completion Gates\nReturn a typed result.\n").encode("utf-8")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


PARENT_ADC = "f" * 64
OWNER_ID = 3744776
ACTIVATION_SHA = "b" * 40
VERIFY_RUN = 500
ACCEPTANCE_RUN = 501
VERIFY_COMMENT = 302
ACCEPTANCE_COMMENT = 303
ACTIVATION_COMMENT = 304


def _activation_comment_row(comment_id, body, created_at, *, login="puchinya", user_id=OWNER_ID,
                            user_type="User", updated_at=None):
    issue_url = f"https://api.github.com/repos/{REPO}/issues/26"
    return {
        "id": comment_id, "body": body, "created_at": created_at,
        "updated_at": created_at if updated_at is None else updated_at,
        "issue_url": issue_url,
        "html_url": f"https://github.com/{REPO}/issues/26#issuecomment-{comment_id}",
        "url": f"https://api.github.com/repos/{REPO}/issues/comments/{comment_id}",
        "user": {"id": user_id, "login": login, "type": user_type,
                 "name": "Owner", "avatar_url": "https://avatars.example/owner"},
    }


def activation_fixture(*, approval_author="puchinya", merged_by="puchinya", open_child=None,
                       evidence_refs=None, integration_overrides=None):
    child_prs = tuple((issue, issue + 6, f"{issue:040x}") for issue in range(27, 33))
    expected_child_prs = [{"issue_number": issue, "pr_number": pr, "merge_sha40": sha}
                          for issue, pr, sha in child_prs]
    refs = evidence_refs or [
        f"https://github.com/{REPO}/actions/runs/{VERIFY_RUN}",
        f"https://github.com/{REPO}/actions/runs/{ACCEPTANCE_RUN}",
        f"https://github.com/{REPO}/issues/26#issuecomment-{VERIFY_COMMENT}",
        f"https://github.com/{REPO}/issues/26#issuecomment-{ACCEPTANCE_COMMENT}",
    ]
    integration = {
        "documentation_pass": True, "distribution_pass": True,
        "evidence_refs": refs,
        "integration_commit_sha40": ACTIVATION_SHA, "repository": REPO,
        "schema": "PASES_INTEGRATION_EVIDENCE_V1", "skills_count": 16,
        "status": "PASS", "tests_pass": True, "child_prs": expected_child_prs,
    }
    if integration_overrides:
        integration.update(integration_overrides)
    integration_sha = hashlib.sha256(canonical(integration).encode()).hexdigest()
    approval = {
        "approved": True, "activation_commit_sha40": ACTIVATION_SHA,
        "child_issue_numbers": list(range(27, 33)), "child_prs": expected_child_prs,
        "integration_evidence_sha256": integration_sha, "repository": REPO,
        "schema": "PASES_ACTIVATION_APPROVAL_V1",
    }
    record = ActivationRecord(
        REPO, tuple(range(27, 33)), child_prs, tuple(range(27, 33)), integration_sha,
        300, "p-ases-v1", ACTIVATION_SHA, 301, "2026-10-11T01:30:00Z",
    )
    integration_body = f"<!-- PASES_INTEGRATION_EVIDENCE_V1\n{canonical(integration)}\n-->"
    approval_body = f"<!-- PASES_ACTIVATION_APPROVAL_V1\n{canonical(approval)}\n-->"
    verify_bundle = ParentGateEvidenceComment(
        "verification", REPO, 26, PARENT_ADC, ACTIVATION_SHA, VERIFY_RUN, 1,
        ".github/workflows/ci.yml", b"{}\n", (("actions/fixture.json", b"verification"),),
    ).validate()
    acceptance_bundle = ParentGateEvidenceComment(
        "acceptance", REPO, 26, PARENT_ADC, ACTIVATION_SHA, ACCEPTANCE_RUN, 1,
        ".github/workflows/parent-integration.yml", b"{}\n", (("actions/fixture.json", b"acceptance"),),
    ).validate()
    activation_body = f"<!-- PASES_ACTIVATION_V1\n{canonical(record.payload())}\n-->"
    comments = [
        _activation_comment_row(VERIFY_COMMENT, verify_bundle.to_body(), "2026-10-11T00:10:00Z"),
        _activation_comment_row(ACCEPTANCE_COMMENT, acceptance_bundle.to_body(), "2026-10-11T00:20:00Z"),
        _activation_comment_row(300, integration_body, "2026-10-11T00:30:00Z"),
        _activation_comment_row(301, approval_body, "2026-10-11T01:00:00Z", login=approval_author),
        _activation_comment_row(ACTIVATION_COMMENT, activation_body, "2026-10-11T01:30:00Z"),
    ]
    prs = {}
    for issue, pr_number, merge_sha in child_prs:
        pair = {
            27: ("main", "pases/adc-core"), 28: ("main", "pases/documentation"),
            29: ("main", "pases/verification"), 30: ("main", "pases/work-readiness"),
            31: ("main", "pases/user-review-integration"), 32: ("main", "pases/distribution-migration"),
        }[issue]
        prs[pr_number] = {
            "number": pr_number, "state": "closed", "merged": True,
            "merge_commit_sha": merge_sha, "merged_by": {"login": merged_by},
            "base": {"ref": pair[0], "repo": {"full_name": REPO}},
            "head": {"ref": pair[1], "repo": {"full_name": REPO}},
            "body": f"Closes #{issue}\n",
        }

    class ActivationGitHub(FakeGitHub):
        def __init__(self):
            super().__init__()
            self.rows = comments
            self.main_sha = ACTIVATION_SHA
            self.activation_is_ancestor = True

        def issue_comment(self, issue_number, comment_id):
            if issue_number != 26:
                raise GitHubError("wrong Issue")
            for row in self.rows:
                if row["id"] == comment_id:
                    return row
            raise GitHubError("comment deleted")

        def issue_comments(self, issue_number):
            return list(self.rows) if issue_number == 26 else []

        def repository_metadata(self):
            return {"default_branch": "main", "owner": {"id": OWNER_ID, "login": "puchinya", "type": "User"}}

        def branch(self, branch_name):
            if branch_name != "main":
                raise GitHubError("wrong branch")
            return {"commit": {"sha": self.main_sha}}

        def compare_commits(self, base_sha40, head_sha40):
            if base_sha40 == head_sha40:
                return {"status": "identical"}
            if base_sha40 == ACTIVATION_SHA and head_sha40 == self.main_sha:
                return {"status": "ahead" if self.activation_is_ancestor else "diverged"}
            return {"status": "ahead" if head_sha40 == ACTIVATION_SHA else "identical"}

        def issue(self, issue_number):
            state = "open" if issue_number == open_child else "closed"
            return {"number": issue_number, "state": state}

        def pull_request(self, pr_number):
            return prs[pr_number]

    return ActivationGitHub(), record


def activation_trust_patches(record, *, current_main=None, loader_error=None):
    calls = []

    def load_evidence(github, comment_id, main_sha40, kind, repository, parent_adc_sha256,
                      *, require_authenticated_author=True, use_recorded_attempt=False):
        calls.append((comment_id, main_sha40, kind, repository, parent_adc_sha256,
                      require_authenticated_author, use_recorded_attempt))
        if loader_error is not None:
            raise IntegrationError(loader_error)
        if (main_sha40 != record.activation_commit_sha40 or repository.casefold() != record.repository.casefold()
                or parent_adc_sha256 != PARENT_ADC or require_authenticated_author is not False):
            raise IntegrationError("wrong activation evidence subject")
        matching = []
        for row in github.issue_comments(26):
            body = row.get("body")
            if not isinstance(body, str) or not body.startswith("P-ASES-PARENT-EVIDENCE-V2\n"):
                continue
            bundle = ParentGateEvidenceComment.from_body(body)
            if (bundle.kind == kind and bundle.repository.casefold() == repository.casefold()
                    and bundle.parent_issue_number == 26 and bundle.parent_adc_sha256 == parent_adc_sha256
                    and bundle.main_sha40 == main_sha40):
                matching.append(row.get("id"))
        if matching != [comment_id]:
            raise IntegrationError("duplicate or mismatched parent evidence comment")

    return unittest.mock.patch.multiple(
        "p_ases.gate_policy",
        _parent_adc_authority=unittest.mock.Mock(return_value=(PARENT_ADC, None)),
        _parent_current_main_sha=unittest.mock.Mock(return_value=current_main or record.activation_commit_sha40),
        _load_parent_gate_evidence_from_github=unittest.mock.Mock(side_effect=load_evidence),
    ), calls

def pr_readback(**overrides):
    value = {
        "number": 33,
        "state": "open",
        "draft": False,
        "base": {"ref": "main", "sha": BASE, "repo": {"full_name": REPO}},
        "head": {"ref": "pases/adc-core", "sha": HEAD, "repo": {"full_name": REPO}},
        "body": "Closes #27\n",
    }
    value.update(overrides)
    return value


def workflow_run(**overrides):
    value = {"id": 500, "run_number": 3, "run_attempt": 1, "path": ".github/workflows/ci.yml", "head_sha": HEAD,
             "event": "pull_request", "status": "completed", "conclusion": "success",
             "head_branch": "pases/adc-core", "head_repository": {"full_name": REPO},
             "pull_requests": [{"number": 33}]}
    value.update(overrides)
    return value


def check_runs(names=("test-a", "test-b", "pull-request-metadata")):
    return [{"id": 600 + index, "name": name, "head_sha": HEAD, "status": "completed",
             "conclusion": "success", "app": {"id": 789}}
            for index, name in enumerate(names)]


def self_review(subj=None, items=None, verified=True):
    subj = subj or subject()
    rows = items or (
        ReviewItem("CHECKLIST-001", "PASS", (f"https://github.com/{REPO}/blob/{subj.head_sha40}/runtime/p_ases/cli.py",
                                              f"https://github.com/{REPO}/actions/runs/500")),
        ReviewItem("CHECKLIST-002", "PASS", (f"https://github.com/{REPO}/blob/{subj.head_sha40}/runtime/p_ases/gate_policy.py",
                                              f"https://github.com/{REPO}/actions/runs/500")),
        ReviewItem("REQ-08", "PASS", (f"https://github.com/{REPO}/pull/33/files",)),
    )
    evidence = tuple(VerifiedReviewEvidence(item.item_id, ref,
                                            "workflow-run" if "/actions/runs/" in ref else
                                            "pull-request" if "/pull/" in ref else "git-blob",
                                            "d" * 64, subj.head_sha40)
                     for item in rows for ref in item.evidence_refs)
    return BootstrapSelfReview(subj, "implementation-context", tuple(rows), 200,
                               evidence if verified else ())


def independent_review(subj=None, context="review-context", findings=(), verdict="PASS"):
    subj = subj or subject()
    artifact = BootstrapReviewContextArtifact(subj, context, True,
                                             "Independent review executed in a separate context", 202)
    digest = hashlib.sha256(artifact.comment_body().encode("utf-8")).hexdigest()
    return BootstrapIndependentReview(subj or subject(), context, "implementation-context",
                                      f"https://github.com/{REPO}/issues/{subj.issue_number}#issuecomment-202",
                                      digest, True, tuple(findings), verdict, 201, True, 202)


def evaluate(**overrides):
    values = dict(subject=subject(), pr=pr_readback(), response_repository=REPO,
                  workflow_runs=[workflow_run()], check_runs=check_runs(),
                  required_check_names=("test-a", "test-b"), local_checks=local_checks(),
                  adc_requirement_ids=("REQ-08",), adc_checklist_ids=("CHECKLIST-001", "CHECKLIST-002"),
                  self_review=self_review(), independent_review=independent_review(), unverified_hosts=("none",),
                  bootstrap_policy_sha256="f" * 64)
    values.update(overrides)
    return evaluate_bootstrap(**values)


class BootstrapPolicyTests(unittest.TestCase):
    def test_fixed_cohort_selection_is_pinned_and_unknown_issue_has_no_fallback(self):
        selected = select_gate(REPO, 27, selected_at="2026-10-11T00:00:00Z")
        self.assertEqual(selected.policy_version, "bootstrap-legacy-v1")
        parent_selected = select_gate(REPO, 26, selected_at="2026-10-11T00:00:00Z")
        self.assertEqual(parent_selected.policy_version, "bootstrap-legacy-v1")
        self.assertIsNone(select_gate(REPO, 33, selected_at="2026-10-11T00:00:00Z"))
        with self.assertRaises(GatePolicyError):
            subject(issue_number=33).validate()

    def test_fixed_bootstrap_cohort_is_bound_to_repository_identity_case_insensitively(self):
        upper = "PUCHINYA/AI-AGENT-WORKFLOW"
        self.assertEqual(select_gate(upper, 27, selected_at="2026-10-11T00:00:00Z").policy_version,
                         "bootstrap-legacy-v1")
        self.assertEqual(subject(repository=upper).validate().repository, upper)
        self.assertIsNone(select_gate("another-owner/another-repo", 27,
                                      selected_at="2026-10-11T00:00:00Z"))
        with self.assertRaisesRegex(GatePolicyError, "non-cohort"):
            type(select_gate(REPO, 27, selected_at="2026-10-11T00:00:00Z"))(
                "another-owner/another-repo", 27, "bootstrap-legacy-v1", "2026-10-11T00:00:00Z").validate()
        with self.assertRaisesRegex(GatePolicyError, "fixed cohort repository"):
            subject(repository="another-owner/another-repo").validate()

    def test_activation_selects_normal_gate_only_for_work_started_after_activation(self):
        activation = ActivationRecord(
            REPO, tuple(range(27, 33)), tuple((issue, issue + 6, "a" * 40) for issue in range(27, 33)),
            tuple(range(27, 33)), "d" * 64, 300, "p-ases-v1", "b" * 40, 301,
            "2026-10-11T00:00:00Z")
        selected = select_gate(REPO, 33, selected_at="2026-10-11T00:00:01Z", activation=activation,
                               activation_comment_id=302, activation_sha256=activation.sha256,
                               issue_created_at="2026-10-11T00:00:00.500Z")
        self.assertEqual(selected.policy_version, "p-ases-v1")
        self.assertIsNone(select_gate(REPO, 33, selected_at="2026-10-10T23:59:59Z", activation=activation,
                                      activation_comment_id=302, activation_sha256=activation.sha256,
                                      issue_created_at="2026-10-10T23:00:00Z"))
        self.assertIsNone(select_gate(REPO, 33, selected_at="2026-10-11T00:00:01Z", activation=activation,
                                      activation_comment_id=302, activation_sha256=activation.sha256,
                                      issue_created_at="2026-10-10T23:59:59Z"))
        self.assertIsNone(select_gate(REPO, 33, selected_at="2026-10-11T00:00:01Z", activation=activation,
                                      activation_comment_id=302, activation_sha256=activation.sha256))
        self.assertEqual(select_gate(REPO, 27, selected_at="2026-10-11T00:00:01Z", activation=activation).policy_version,
                         "bootstrap-legacy-v1")

    def test_valid_current_subject_can_be_bootstrap_technical_ready_without_review(self):
        result = evaluate()
        self.assertEqual(result.status, "BOOTSTRAP_TECHNICAL_READY")
        self.assertEqual(result.workflow_run_id, 500)
        self.assertEqual(result.payload()["schema"], "PASES_BOOTSTRAP_REVIEW_V1")
        self.assertIn("unverified_hosts", result.payload())
        self.assertEqual(result.review_mode, "WAIVED_BOOTSTRAP")
        self.assertEqual(result.payload()["verified_review_evidence"], [])
        self.assertIsNone(result.payload()["self_review_comment_id"])
        self.assertIsNone(result.payload()["independent_review_comment_id"])
        self.assertIsNone(result.payload()["independent_context_artifact_comment_id"])
        self.assertFalse(result.payload()["separate_context_confirmed"])
        self.assertEqual(result.payload()["independence_assurance"], "NOT_APPLICABLE_REVIEW_WAIVED")
        self.assertFalse(result.payload()["can_request_final_user_review"])

    def test_bootstrap_policy_digest_is_a_full_sha256(self):
        self.assertRegex(bootstrap_policy_digest(), r"^[0-9a-f]{64}$")

    def test_historical_blocked_v1_result_without_policy_digest_remains_readable(self):
        old_payload = evaluate(independent_review=None).payload()
        old_payload.pop("review_mode")
        old_payload.pop("independence_assurance")
        old_payload.pop("verified_review_evidence")
        old_payload.pop("independent_context_artifact_comment_id")
        old_payload.pop("independent_context_artifact_sha256")
        old_payload.pop("separate_context_confirmed")
        old_payload["status"] = "BOOTSTRAP_BLOCKED"
        old_payload["can_request_final_user_review"] = False
        old_payload["reasons"] = ["historical evidence was incomplete"]
        del old_payload["bootstrap_policy_sha256"]
        historical = BootstrapResult.from_payload(old_payload)
        self.assertEqual(historical.status, "BOOTSTRAP_BLOCKED")
        self.assertIsNone(historical.bootstrap_policy_sha256)

    def test_pr_state_repo_fork_branch_and_closes_must_match(self):
        cases = (
            pr_readback(state="closed"),
            pr_readback(draft=True),
            pr_readback(head={"ref": "pases/adc-core", "sha": HEAD, "repo": {"full_name": "fork/repo"}}),
            pr_readback(base={"ref": "other", "sha": BASE, "repo": {"full_name": REPO}}),
            pr_readback(body="Closes #28\n"),
            pr_readback(body="Closes #27\nCloses #28\n"),
            pr_readback(number=99),
        )
        for row in cases:
            with self.subTest(row=row):
                self.assertEqual(evaluate(pr=row).status, "BOOTSTRAP_BLOCKED")
        self.assertEqual(evaluate(response_repository="fork/repo").status, "BOOTSTRAP_BLOCKED")

    def test_pr29_uses_main_only_after_parent_merge_and_unapproved_pairs_fail_closed(self):
        verification_subject = replace(
            subject(), issue_number=29, pr_number=34, base_ref="main",
            head_ref="pases/verification")
        verification_pr = pr_readback(
            number=34,
            base={"ref": "main", "sha": BASE, "repo": {"full_name": REPO}},
            head={"ref": "pases/verification", "sha": HEAD, "repo": {"full_name": REPO}},
            body="Closes #29\n")
        verification_run = workflow_run(
            head_branch="pases/verification", pull_requests=[{"number": 34}])
        self.assertEqual(evaluate(subject=verification_subject, pr=verification_pr,
                                  workflow_runs=[verification_run]).status,
                         "BOOTSTRAP_TECHNICAL_READY")

        obsolete_subject = replace(verification_subject, base_ref="pases/adc-core")
        obsolete_pr = dict(verification_pr)
        obsolete_pr["base"] = {"ref": "pases/adc-core", "sha": BASE,
                                "repo": {"full_name": REPO}}
        self.assertEqual(evaluate(subject=obsolete_subject, pr=obsolete_pr,
                                  workflow_runs=[verification_run]).status,
                         "BOOTSTRAP_BLOCKED")

        undocumented_subject = replace(
            verification_subject, issue_number=32, pr_number=42,
            base_ref="unapproved-base", head_ref="unapproved-head")
        undocumented_pr = pr_readback(
            number=42,
            base={"ref": "unapproved-base", "sha": BASE, "repo": {"full_name": REPO}},
            head={"ref": "unapproved-head", "sha": HEAD, "repo": {"full_name": REPO}},
            body="Closes #32\n")
        undocumented_run = workflow_run(
            head_branch="unapproved-head", pull_requests=[{"number": 42}])
        result = evaluate(subject=undocumented_subject, pr=undocumented_pr,
                          workflow_runs=[undocumented_run])
        self.assertEqual(result.status, "BOOTSTRAP_BLOCKED")
        self.assertIn("PR base/head branch pair does not match the approved child branch contract",
                      result.reasons)

    def test_pr32_uses_the_approved_main_distribution_migration_branch_pair(self):
        migration_subject = replace(
            subject(), issue_number=32, pr_number=42, base_ref="main",
            head_ref="pases/distribution-migration")
        migration_pr = pr_readback(
            number=42,
            base={"ref": "main", "sha": BASE, "repo": {"full_name": REPO}},
            head={"ref": "pases/distribution-migration", "sha": HEAD,
                  "repo": {"full_name": REPO}},
            body="Closes #32\n")
        migration_run = workflow_run(
            head_branch="pases/distribution-migration", pull_requests=[{"number": 42}])
        self.assertEqual(evaluate(subject=migration_subject, pr=migration_pr,
                                  workflow_runs=[migration_run]).status,
                         "BOOTSTRAP_TECHNICAL_READY")

        for wrong_base, wrong_head in (
            ("pases/work-readiness", "pases/distribution-migration"),
            ("main", "pases/issue-32"),
        ):
            with self.subTest(base=wrong_base, head=wrong_head):
                wrong_subject = replace(migration_subject, base_ref=wrong_base, head_ref=wrong_head)
                wrong_pr = dict(migration_pr)
                wrong_pr["base"] = {"ref": wrong_base, "sha": BASE, "repo": {"full_name": REPO}}
                wrong_pr["head"] = {"ref": wrong_head, "sha": HEAD, "repo": {"full_name": REPO}}
                wrong_run = workflow_run(
                    head_branch=wrong_head, pull_requests=[{"number": 42}])
                self.assertEqual(evaluate(subject=wrong_subject, pr=wrong_pr,
                                          workflow_runs=[wrong_run]).status,
                                 "BOOTSTRAP_BLOCKED")

    def test_pr31_uses_main_and_exact_review_branch_and_rejects_other_refs(self):
        review_subject = replace(
            subject(), issue_number=31, pr_number=37, base_ref="main",
            head_ref="pases/user-review-integration")
        review_pr = pr_readback(
            number=37, base={"ref": "main", "sha": BASE, "repo": {"full_name": REPO}},
            head={"ref": "pases/user-review-integration", "sha": HEAD,
                  "repo": {"full_name": REPO}}, body="Closes #31\n")
        review_run = workflow_run(
            head_branch="pases/user-review-integration",
            pull_requests=[{"number": 37}])
        self.assertEqual(
            evaluate(subject=review_subject, pr=review_pr,
                     workflow_runs=[review_run]).status, "BOOTSTRAP_TECHNICAL_READY")
        bad_base = replace(review_subject, base_ref="pases/work-readiness")
        bad_pr = dict(review_pr)
        bad_pr["base"] = {"ref": "pases/work-readiness", "sha": BASE,
                          "repo": {"full_name": REPO}}
        self.assertEqual(
            evaluate(subject=bad_base, pr=bad_pr,
                     workflow_runs=[review_run]).status, "BOOTSTRAP_BLOCKED")
        bad_head = replace(review_subject, head_ref="pases/issue-31")
        changed_pr = dict(review_pr)
        changed_pr["head"] = {"ref": "pases/issue-31", "sha": HEAD,
                              "repo": {"full_name": REPO}}
        self.assertEqual(
            evaluate(subject=bad_head, pr=changed_pr,
                     workflow_runs=[review_run]).status, "BOOTSTRAP_BLOCKED")

    def test_pr28_uses_approved_documentation_pair_and_rejects_other_refs(self):
        documentation_subject = replace(
            subject(), issue_number=28, pr_number=36, base_ref="main",
            head_ref="pases/documentation")
        documentation_pr = pr_readback(
            number=36,
            base={"ref": "main", "sha": BASE, "repo": {"full_name": REPO}},
            head={"ref": "pases/documentation", "sha": HEAD, "repo": {"full_name": REPO}},
            body="Closes #28\n")
        documentation_run = workflow_run(
            head_branch="pases/documentation", pull_requests=[{"number": 36}])
        ready = evaluate(subject=documentation_subject, pr=documentation_pr,
                         workflow_runs=[documentation_run])
        self.assertEqual(ready.status, "BOOTSTRAP_TECHNICAL_READY")

        wrong_base_subject = replace(documentation_subject, base_ref="pases/adc-core")
        wrong_base_pr = dict(documentation_pr)
        wrong_base_pr["base"] = {"ref": "pases/adc-core", "sha": BASE,
                                  "repo": {"full_name": REPO}}
        self.assertEqual(evaluate(subject=wrong_base_subject, pr=wrong_base_pr,
                                  workflow_runs=[documentation_run]).status,
                         "BOOTSTRAP_BLOCKED")

        wrong_head_subject = replace(documentation_subject, head_ref="pases/issue-28")
        wrong_head_pr = dict(documentation_pr)
        wrong_head_pr["head"] = {"ref": "pases/issue-28", "sha": HEAD,
                                  "repo": {"full_name": REPO}}
        wrong_head_run = workflow_run(
            head_branch="pases/issue-28", pull_requests=[{"number": 36}])
        self.assertEqual(evaluate(subject=wrong_head_subject, pr=wrong_head_pr,
                                  workflow_runs=[wrong_head_run]).status,
                         "BOOTSTRAP_BLOCKED")

    def test_stale_pr_head_and_changed_base_snapshot_block(self):
        stale = pr_readback(head={"ref": "pases/adc-core", "sha": "f" * 40, "repo": {"full_name": REPO}})
        self.assertEqual(evaluate(pr=stale).status, "BOOTSTRAP_BLOCKED")
        changed_base = pr_readback(base={"ref": "main", "sha": "f" * 40, "repo": {"full_name": REPO}})
        self.assertEqual(evaluate(pr=changed_base).status, "BOOTSTRAP_BLOCKED")

    def test_ci_needs_latest_current_head_successful_workflow_and_every_required_check(self):
        self.assertEqual(evaluate(check_runs=check_runs(("test-a", "pull-request-metadata"))).status,
                         "BOOTSTRAP_BLOCKED")
        skipped = check_runs()
        skipped[0]["conclusion"] = "skipped"
        self.assertEqual(evaluate(check_runs=skipped).status, "BOOTSTRAP_BLOCKED")
        failed_rerun = check_runs() + [{"id": 999, "name": "test-a", "head_sha": HEAD,
                                         "status": "completed", "conclusion": "failure", "app": {"id": 789}}]
        self.assertEqual(evaluate(check_runs=failed_rerun).status, "BOOTSTRAP_BLOCKED")
        stale_workflow = workflow_run(conclusion="failure", run_number=4)
        self.assertEqual(evaluate(workflow_runs=[workflow_run(), stale_workflow]).status,
                         "BOOTSTRAP_BLOCKED")
        failed_attempt = workflow_run(conclusion="failure", run_attempt=2, id=501)
        self.assertEqual(evaluate(workflow_runs=[workflow_run(), failed_attempt]).status,
                         "BOOTSTRAP_BLOCKED")
        wrong_pr = workflow_run(pull_requests=[{"number": 35}])
        self.assertEqual(evaluate(workflow_runs=[wrong_pr]).status, "BOOTSTRAP_BLOCKED")
        wrong_head = check_runs()
        wrong_head[1]["head_sha"] = "f" * 40
        self.assertEqual(evaluate(check_runs=wrong_head).status, "BOOTSTRAP_BLOCKED")

    def test_required_ci_configuration_cannot_be_empty_or_duplicated(self):
        self.assertEqual(evaluate(required_check_names=()).status, "BOOTSTRAP_BLOCKED")
        self.assertEqual(evaluate(required_check_names=("test-a", "test-a")).status,
                         "BOOTSTRAP_BLOCKED")

    def test_local_checks_must_run_cleanly_and_report_complete_set(self):
        failed = list(local_checks())
        failed[2] = LocalCheck("dist-build-check", ("python", "tools/build_dist.py", "--check"),
                               "completed", 1, "d" * 64, False)
        self.assertEqual(evaluate(local_checks=tuple(failed)).status, "BOOTSTRAP_BLOCKED")
        self.assertEqual(evaluate(local_checks=()).status, "BOOTSTRAP_BLOCKED")

    def test_review_inputs_are_ignored_by_technical_bootstrap_readiness(self):
        incomplete = self_review(items=(ReviewItem("REQ-08", "PASS", ("evidence",)),))
        self.assertEqual(evaluate(self_review=incomplete).status, "BOOTSTRAP_TECHNICAL_READY")
        wrong_subject = self_review(subj=subject(head_sha40="f" * 40))
        self.assertEqual(evaluate(self_review=wrong_subject).status, "BOOTSTRAP_TECHNICAL_READY")
        self.assertEqual(evaluate(self_review=None).status, "BOOTSTRAP_TECHNICAL_READY")
        self.assertEqual(evaluate(self_review=object()).status, "BOOTSTRAP_TECHNICAL_READY")
        unverified = replace(self_review(), verified_evidence=())
        self.assertEqual(evaluate(self_review=unverified).status, "BOOTSTRAP_TECHNICAL_READY")

    def test_independent_review_inputs_are_ignored_by_technical_bootstrap_readiness(self):
        same_context = independent_review(context="implementation-context")
        self.assertEqual(evaluate(independent_review=same_context).status, "BOOTSTRAP_TECHNICAL_READY")
        finding = ReviewFinding("A-01", "A", False, "blocking issue", "https://github.com/octo/repo/pull/33")
        unresolved = independent_review(findings=(finding,), verdict="CONCERNS")
        self.assertEqual(evaluate(independent_review=unresolved).status, "BOOTSTRAP_TECHNICAL_READY")
        self.assertEqual(evaluate(independent_review=None).status, "BOOTSTRAP_TECHNICAL_READY")
        self.assertEqual(evaluate(independent_review=object()).status, "BOOTSTRAP_TECHNICAL_READY")
        unverified_context = replace(independent_review(), context_artifact_verified=False,
                                     context_artifact_comment_id=None)
        self.assertEqual(evaluate(independent_review=unverified_context).status, "BOOTSTRAP_TECHNICAL_READY")
        unconfirmed = replace(independent_review(), separate_context_confirmed=False)
        self.assertEqual(evaluate(independent_review=unconfirmed).status, "BOOTSTRAP_TECHNICAL_READY")

    def test_bootstrap_waiver_cannot_expand_to_another_repository_or_issue(self):
        with self.assertRaisesRegex(GatePolicyError, "fixed cohort"):
            evaluate(subject=subject(repository="fork/repo"))
        with self.assertRaisesRegex(GatePolicyError, "fixed Bootstrap cohort"):
            evaluate(subject=subject(issue_number=33))

    def test_technical_bootstrap_payload_is_strict_and_does_not_claim_review(self):
        payload = evaluate().payload()
        self.assertEqual(BootstrapResult.from_payload(payload).payload(), payload)
        for mutation in (
                {"review_mode": None},
                {"status": "BOOTSTRAP_REVIEW_READY"},
                {"can_request_final_user_review": True},
                {"self_review_comment_id": 200},
                {"verified_review_evidence": [{"fake": "review"}]},
                {"separate_context_confirmed": True},
                {"independence_assurance": "reviewer-attested"},
        ):
            changed = dict(payload)
            changed.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(GatePolicyError):
                BootstrapResult.from_payload(changed)
        missing_mode = dict(payload)
        del missing_mode["review_mode"]
        with self.assertRaises(GatePolicyError):
            BootstrapResult.from_payload(missing_mode)

    def test_review_comment_payloads_are_canonical_and_digest_bound(self):
        self_body = self_review().comment_body()
        parsed_self = parse_self_review_comment(self_body, 200)
        self.assertEqual(parsed_self.verified_evidence, ())
        with self.assertRaisesRegex(GatePolicyError, "not read back"):
            parsed_self.validate(("CHECKLIST-001", "CHECKLIST-002", "REQ-08"))
        parsed_self = replace(parsed_self, verified_evidence=self_review().verified_evidence)
        parsed_self.validate(("CHECKLIST-001", "CHECKLIST-002", "REQ-08"))
        with self.assertRaises(GatePolicyError):
            parse_self_review_comment(self_body + " ", 200)
        independent = independent_review()
        parsed_independent = parse_independent_review_comment(independent.comment_body(), 201)
        with self.assertRaisesRegex(GatePolicyError, "has not been read back"):
            parsed_independent.validate()
        parsed_independent = replace(parsed_independent, context_artifact_verified=True,
                                     context_artifact_comment_id=202)
        parsed_independent.validate()
        with self.assertRaises(GatePolicyError):
            parse_self_review_comment("<!-- PASES_BOOTSTRAP_SELF_REVIEW_V1\n[]\n-->", 202)
        with self.assertRaises(GatePolicyError):
            parse_independent_review_comment("<!-- PASES_BOOTSTRAP_INDEPENDENT_REVIEW_V1\nnull\n-->", 203)

    def test_review_comments_are_read_back_by_id_and_issue(self):
        github = FakeGitHub()
        review = self_review()
        github.rows.append({"id": 200, "body": review.comment_body(),
                            "issue_url": f"https://api.github.com/repos/{REPO}/issues/27"})
        found = read_review_comment(github, 27, 200, "PASES_BOOTSTRAP_SELF_REVIEW_V1")
        self.assertEqual(parse_self_review_comment(found["body"], 200).subject, subject())
        with self.assertRaises(GatePolicyError):
            read_review_comment(github, 28, 200, "PASES_BOOTSTRAP_SELF_REVIEW_V1")

    def test_legacy_child_adc_is_read_back_without_inventing_approval(self):
        content = minimal_adc_bytes().replace(b"Child key: adc-core", b"Child key: `adc-core`")
        digest = __import__("hashlib").sha256(content).hexdigest()
        comment_id = 500
        issue_body = ("Child of #26.\n\n- child_key: `adc-core`\n"
                      f"- child_adc_comment_id: {comment_id}\n"
                      f"- child_adc_sha256: `{digest}`\n"
                      f"- child_adc_comment_url: https://github.com/{REPO}/issues/27#issuecomment-{comment_id}\n")

        class LegacyGitHub(FakeGitHub):
            def issue(self, issue_number):
                return {"number": issue_number, "state": "open", "body": issue_body,
                        "repository_url": f"https://api.github.com/repos/{REPO}",
                        "url": f"https://api.github.com/repos/{REPO}/issues/{issue_number}",
                        "html_url": f"https://github.com/{REPO}/issues/{issue_number}"}

            def issue_comments(self, issue_number):
                return [{"id": comment_id, "body": content.decode("utf-8"),
                         "issue_url": f"https://api.github.com/repos/{REPO}/issues/{issue_number}"}]

            def issue_comment(self, issue_number, requested_id):
                return {"id": requested_id, "body": content.decode("utf-8"),
                        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{issue_number}"}

        result = read_bootstrap_adc(LegacyGitHub(), 27)
        self.assertEqual(result.pointer.comment_id, comment_id)
        self.assertEqual(result.pointer.sha256, digest)
        self.assertEqual(result.pointer.state, "unverified")
        self.assertEqual(result.contract.requirement_ids, ("REQ-01",))

        with self.assertRaises(GatePolicyError):
            read_bootstrap_adc(LegacyGitHub(), 28)

    def test_activation_requires_exact_child_set_and_user_approval_reference(self):
        record = ActivationRecord(
            REPO, tuple(range(27, 33)), tuple((issue, issue + 6, "a" * 40) for issue in range(27, 33)),
            tuple(range(27, 33)), "d" * 64, 300, "p-ases-v1", "b" * 40, 301,
            "2026-10-11T00:00:00Z")
        self.assertEqual(record.validate().payload()["schema"], "PASES_ACTIVATION_V1")
        with self.assertRaises(GatePolicyError):
            ActivationRecord(REPO, tuple(range(27, 32)), record.child_prs, record.closed_issue_numbers,
                             "d" * 64, 300, "p-ases-v1", "b" * 40, 301,
                             "2026-10-11T00:00:00Z").validate()

    def test_activation_reader_does_not_fallback_when_record_is_absent(self):
        self.assertIsNone(read_activation_record(FakeGitHub(), REPO))

    def test_activation_requires_repository_owner_for_explicit_approval_and_merges(self):
        _require_repository_owner_actor({"login": "puchinya"}, REPO, "Activation approval")
        with self.assertRaises(GatePolicyError):
            _require_repository_owner_actor({"login": "automation-bot"}, REPO, "Activation approval")
        with self.assertRaises(GatePolicyError):
            _require_repository_owner_actor(None, REPO, "child PR merge")

    def test_activation_readback_requires_owner_approval_and_owner_merges(self):
        github, record = activation_fixture(approval_author="automation-bot")
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "Activation approval comment is not authored"):
            _validate_activation_candidate(github, record)

        github, record = activation_fixture(merged_by="automation-bot")
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "child PR #33 merge must be explicitly performed"):
            _validate_activation_candidate(github, record)

    def test_activation_reconstructs_both_trusted_parent_actions_records(self):
        github, record = activation_fixture()
        patches, calls = activation_trust_patches(record)
        with patches:
            self.assertEqual(read_activation_record(github, REPO), (record, ACTIVATION_COMMENT))
        self.assertEqual({row[2] for row in calls}, {"verification", "acceptance"})
        self.assertEqual({row[0] for row in calls}, {VERIFY_COMMENT, ACCEPTANCE_COMMENT})
        self.assertTrue(all(row[1] == record.activation_commit_sha40 for row in calls))
        self.assertTrue(all(row[4] == PARENT_ADC for row in calls))
        self.assertTrue(all(row[6] is True for row in calls))

    def test_activation_issuance_uses_current_latest_attempt_policy(self):
        github, record = activation_fixture()
        patches, calls = activation_trust_patches(record)
        with patches:
            _validate_activation_candidate(github, record)
        self.assertTrue(calls)
        self.assertTrue(all(row[6] is False for row in calls))

    def test_activation_rejects_self_asserted_pass_and_nonexistent_actions_refs(self):
        github, record = activation_fixture()
        patches, _calls = activation_trust_patches(record, loader_error="no trusted Actions run")
        with patches, self.assertRaisesRegex(GatePolicyError, "no trusted Actions run"):
            _validate_activation_candidate(github, record)

        github, record = activation_fixture(evidence_refs=[
            f"https://github.com/{REPO}/actions/runs/998",
            f"https://github.com/{REPO}/actions/runs/999",
            f"https://github.com/{REPO}/issues/26#issuecomment-{VERIFY_COMMENT}",
            f"https://github.com/{REPO}/issues/26#issuecomment-{ACCEPTANCE_COMMENT}",
        ])
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "activation SHA, ADC, or run reference"):
            _validate_activation_candidate(github, record)

        github, record = activation_fixture(integration_overrides={"tests_pass": False})
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "parent integration evidence is incomplete"):
            _validate_activation_candidate(github, record)

    def test_activation_after_main_advances_preserves_the_historical_record(self):
        advanced_main = "c" * 40
        github, record = activation_fixture()
        github.main_sha = advanced_main
        patches, calls = activation_trust_patches(record, current_main=advanced_main)
        with patches:
            self.assertEqual(read_activation_record(github, REPO), (record, ACTIVATION_COMMENT))
        self.assertEqual({row[1] for row in calls}, {record.activation_commit_sha40})

        github.activation_is_ancestor = False
        patches, _calls = activation_trust_patches(record, current_main=advanced_main)
        with patches, self.assertRaisesRegex(GatePolicyError, "no longer contained in current main"):
            _validate_activation_candidate(github, record)

    def test_activation_comments_reject_edits_duplicates_and_author_changes(self):
        mutations = (
            (301, {"updated_at": "2026-10-11T01:00:01Z"}, "edited after creation"),
            (ACTIVATION_COMMENT, {"updated_at": "2026-10-11T01:30:01Z"}, "edited after creation"),
            (ACTIVATION_COMMENT, {"issue_url": f"https://api.github.com/repos/{REPO}/issues/27"},
             "Issue URL does not match"),
            (301, {"id": 9999}, "comment readback failed"),
            (300, {"user": {"id": OWNER_ID + 1, "login": "puchinya", "type": "User"}},
             "not authored by the repository owner"),
            (301, {"user": {"id": OWNER_ID, "login": "automation-bot", "type": "User"}},
             "not authored by the repository owner"),
            (ACTIVATION_COMMENT, {"user": {"id": OWNER_ID, "login": "puchinya", "type": "Bot"}},
             "author identity is malformed"),
        )
        for comment_id, updates, message in mutations:
            with self.subTest(comment_id=comment_id, message=message):
                github, record = activation_fixture()
                row = next(item for item in github.rows if item["id"] == comment_id)
                row.update(updates)
                patches, _calls = activation_trust_patches(record)
                with patches, self.assertRaisesRegex(GatePolicyError, message):
                    read_activation_record(github, REPO)

        for duplicate_id in (300, 301, ACTIVATION_COMMENT, VERIFY_COMMENT):
            with self.subTest(duplicate_id=duplicate_id):
                github, record = activation_fixture()
                duplicate = dict(next(item for item in github.rows if item["id"] == duplicate_id))
                duplicate["id"] = 900 + duplicate_id
                duplicate["html_url"] = f"https://github.com/{REPO}/issues/26#issuecomment-{duplicate['id']}"
                duplicate["url"] = f"https://api.github.com/repos/{REPO}/issues/comments/{duplicate['id']}"
                github.rows.append(duplicate)
                patches, _calls = activation_trust_patches(record)
                with patches, self.assertRaises(GatePolicyError):
                    read_activation_record(github, REPO)

        github, record = activation_fixture()
        github.rows = [row for row in github.rows if row["id"] != 301]
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "comment readback failed"):
            read_activation_record(github, REPO)

    def test_activation_readback_rejects_a_change_between_direct_list_direct(self):
        github, record = activation_fixture()
        original = github.issue_comment
        calls = 0

        def mutate_activation_between_reads(issue_number, comment_id):
            nonlocal calls
            row = dict(original(issue_number, comment_id))
            if comment_id == ACTIVATION_COMMENT:
                calls += 1
                if calls == 2:
                    row["body"] = row["body"].replace('"gate_version":"p-ases-v1"',
                                                       '"gate_version":"changed"')
            return row

        github.issue_comment = mutate_activation_between_reads
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "changed during direct/list/direct"):
            read_activation_record(github, REPO)

        github, record = activation_fixture()
        original = github.issue_comment
        calls = 0

        def mutate_approval_between_reads(issue_number, comment_id):
            nonlocal calls
            row = dict(original(issue_number, comment_id))
            if comment_id == 301:
                calls += 1
                if calls == 2:
                    row["body"] = row["body"].replace('"approved":true', '"approved":false')
            return row

        github.issue_comment = mutate_approval_between_reads
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "changed during direct/list/direct"):
            read_activation_record(github, REPO)

    def test_activation_readback_rechecks_history_after_actions_and_child_apis(self):
        github, record = activation_fixture()
        original_pull_request = github.pull_request
        changed = False

        def mutate_approval_during_child_readback(pr_number):
            nonlocal changed
            result = original_pull_request(pr_number)
            if pr_number == 38 and not changed:
                approval = next(row for row in github.rows if row["id"] == 301)
                approval["body"] = approval["body"].replace('"approved":true', '"approved":false')
                approval["updated_at"] = "2026-10-11T01:00:01Z"
                changed = True
            return result

        github.pull_request = mutate_approval_during_child_readback
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "edited after creation"):
            read_activation_record(github, REPO)

    def test_activation_readback_ignores_profile_fields_and_login_casing(self):
        github, record = activation_fixture()
        original = github.issue_comment
        calls = 0

        def vary_profile_and_case(issue_number, comment_id):
            nonlocal calls
            row = dict(original(issue_number, comment_id))
            row["user"] = dict(row["user"])
            calls += 1
            row["user"].update({"login": "PUCHINYA" if calls % 2 else "puchinya",
                                "name": f"Owner {calls}",
                                "avatar_url": f"https://avatars.example/{calls}",
                                "html_url": f"https://github.com/user-{calls}"})
            return row

        github.issue_comment = vary_profile_and_case
        patches, _calls = activation_trust_patches(record)
        with patches:
            self.assertEqual(read_activation_record(github, REPO), (record, ACTIVATION_COMMENT))

    def test_activation_refuses_open_child_and_mismatched_branch_pair(self):
        github, record = activation_fixture(open_child=27)
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "child Issue #27 is not closed"):
            _validate_activation_candidate(github, record)

        github, record = activation_fixture()
        original_pull_request = github.pull_request

        def wrong_child_base(pr_number):
            result = dict(original_pull_request(pr_number))
            if pr_number == 38:
                result["base"] = {"ref": "pases/verification", "repo": {"full_name": REPO}}
            return result

        github.pull_request = wrong_child_base
        patches, _calls = activation_trust_patches(record)
        with patches, self.assertRaisesRegex(GatePolicyError, "child PR #38 has no matching approved base/head branch contract"):
            _validate_activation_candidate(github, record)

    def test_gate_selection_refuses_comment_readback_from_another_issue(self):
        class MisboundCommentGitHub(FakeGitHub):
            def issue_comment(self, issue_number, comment_id):
                row = dict(super().issue_comment(issue_number, comment_id))
                row["issue_url"] = f"https://api.github.com/repos/{REPO}/issues/28"
                return row

        with self.assertRaises(GatePolicyError):
            pin_gate_selection(MisboundCommentGitHub(),
                               select_gate(REPO, 27, selected_at="2026-10-11T00:00:00Z"))


class FakeGitHub:
    repo = REPO

    def __init__(self):
        self.rows = []
        self.next_id = 1000

    def issue_comments(self, issue_number):
        return list(self.rows)

    def issue(self, issue_number):
        return {"number": issue_number, "state": "open", "created_at": "2026-10-11T00:00:00Z"}

    def create_issue_comment(self, issue_number, body):
        row = {"id": self.next_id, "body": body,
               "issue_url": f"https://api.github.com/repos/{REPO}/issues/{issue_number}"}
        self.next_id += 1
        self.rows.append(row)
        return row

    def issue_comment(self, issue_number, comment_id):
        return next(row for row in self.rows if row["id"] == comment_id)


class ReviewArtifactGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.contents = {
            (HEAD, "runtime/p_ases/cli.py"): b"cli artifact at exact head",
            (HEAD, "runtime/p_ases/gate_policy.py"): b"gate artifact at exact head",
        }

    def content_at_ref(self, path, ref):
        try:
            return self.contents[(ref, path)]
        except KeyError as exc:
            raise GitHubError("not found") from exc


class ReviewEvidenceVerificationTests(unittest.TestCase):
    def _context(self, review):
        artifact = BootstrapReviewContextArtifact(review.subject, review.reviewer_context_id, True,
                                                 "Independent review executed in a separate context", 202)
        return {"id": 202, "body": artifact.comment_body(),
                "issue_url": f"https://api.github.com/repos/{REPO}/issues/{review.subject.issue_number}"}

    def test_current_source_ci_and_pr_refs_are_read_back_and_head_bound(self):
        github = ReviewArtifactGitHub()
        raw_self = self_review(verified=False)
        raw_independent = independent_review()
        github.rows.append(self._context(raw_independent))
        verified_independent = verify_independent_context_artifact(github, subject(), raw_independent)
        evidence = verify_bootstrap_review_evidence(
            github, subject(), self_review=raw_self, independent_review=verified_independent,
            pr=pr_readback(), workflow_runs=[workflow_run()])
        self.assertEqual(len(evidence), sum(len(item.evidence_refs) for item in raw_self.items))
        verified_self = replace(raw_self, verified_evidence=evidence)
        self.assertEqual(evaluate(self_review=verified_self, independent_review=verified_independent).status,
                         "BOOTSTRAP_TECHNICAL_READY")
        self.assertEqual({row.evidence_kind for row in evidence}, {"git-blob", "workflow-run", "pull-request"})

    def test_missing_or_wrong_head_source_refs_cannot_be_used(self):
        github = ReviewArtifactGitHub()
        missing = self_review(verified=False, items=(ReviewItem(
            "REQ-08", "PASS", (f"https://github.com/{REPO}/blob/{HEAD}/missing.md",)),))
        with self.assertRaisesRegex(GatePolicyError, "could not be read"):
            verify_bootstrap_review_evidence(github, subject(), self_review=missing,
                                             independent_review=None, pr=pr_readback(),
                                             workflow_runs=[workflow_run()])
        stale_ref = f"https://github.com/{REPO}/blob/{'f' * 40}/runtime/p_ases/cli.py"
        stale = self_review(verified=False, items=(ReviewItem("REQ-08", "PASS", (stale_ref,)),))
        with self.assertRaisesRegex(GatePolicyError, "not pinned"):
            verify_bootstrap_review_evidence(github, subject(), self_review=stale,
                                             independent_review=None, pr=pr_readback(),
                                             workflow_runs=[workflow_run()])

    def test_independent_context_requires_existing_exact_subject_digest_and_attestation(self):
        github = ReviewArtifactGitHub()
        review = independent_review()
        github.rows.append(self._context(review))
        verified = verify_independent_context_artifact(github, subject(), review)
        self.assertTrue(verified.context_artifact_verified)
        self.assertEqual(verified.context_artifact_comment_id, 202)
        altered = replace(review, context_artifact_sha256="e" * 64)
        with self.assertRaisesRegex(GatePolicyError, "digest does not match"):
            verify_independent_context_artifact(github, subject(), altered)
        unconfirmed_artifact = BootstrapReviewContextArtifact(subject(), review.reviewer_context_id, False,
                                                             "Separate session not confirmed", 202)
        github.rows[0]["body"] = unconfirmed_artifact.comment_body()
        altered = replace(review, context_artifact_sha256=hashlib.sha256(
            github.rows[0]["body"].encode("utf-8")).hexdigest())
        with self.assertRaisesRegex(GatePolicyError, "does not confirm"):
            verify_independent_context_artifact(github, subject(), altered)


class CheckoutRecheckTests(unittest.TestCase):
    def test_checkout_mutations_during_local_checks_block(self):
        mutations = (
            ("tracked", {"status": " M runtime/p_ases/cli.py"}),
            ("staged", {"status": "M  runtime/p_ases/cli.py"}),
            ("untracked", {"status": "?? scratch.tmp"}),
            ("head", {"head": "f" * 40}),
            ("branch", {"branch": "other-branch"}),
        )
        for label, update in mutations:
            with self.subTest(label=label):
                state = {"head": HEAD, "branch": "pases/adc-core", "status": ""}

                def git_stub(_root, *args):
                    if args[0] == "rev-parse":
                        return state["head"]
                    if args[0] == "symbolic-ref":
                        return state["branch"]
                    if args[0] == "status":
                        return state["status"]
                    raise AssertionError(args)

                def process_stub(_root):
                    state.update(update)
                    return local_checks()

                with unittest.mock.patch("p_ases.gate_policy.run_git", side_effect=git_stub), \
                        unittest.mock.patch("p_ases.gate_policy.run_local_bootstrap_checks",
                                            side_effect=process_stub):
                    with self.assertRaisesRegex(GatePolicyError, "HEAD|branch|not clean"):
                        run_local_bootstrap_checks_bound(Path("/fake/repo"), subject())


class ImmutableBootstrapRecordTests(unittest.TestCase):
    def test_gate_selection_is_immutable_and_exact_retry_is_reused(self):
        github = FakeGitHub()
        first = select_gate(REPO, 27, selected_at="2026-10-11T00:00:00Z")
        first_id, _ = pin_gate_selection(github, first)
        read_id, read_selection, read_body = read_gate_selection(github, 27)
        self.assertEqual(read_id, first_id)
        self.assertEqual(read_selection.payload(), first.payload())
        self.assertTrue(read_body.startswith("<!-- PASES_GATE_SELECTION_V1\n"))
        retry = select_gate(REPO, 27, selected_at="2026-10-11T01:00:00Z")
        retry_id, _ = pin_gate_selection(github, retry)
        self.assertEqual(first_id, retry_id)
        conflict = select_gate(REPO, 27, selected_at="2026-10-11T02:00:00Z")
        conflict = type(conflict)(REPO, 27, "p-ases-v1", "2026-10-11T02:00:00Z", 500, "f" * 64)
        with self.assertRaises(GatePolicyError):
            pin_gate_selection(github, conflict)

    def test_exact_retry_reuses_comment_and_changed_observation_appends_linked_record(self):
        github = FakeGitHub()
        first = evaluate().payload()
        first_id, _ = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", first)
        self.assertEqual(read_bootstrap_evidence(github, 27, first_id), first)
        retry_id, _ = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", first)
        self.assertEqual(first_id, retry_id)
        second = evaluate(bootstrap_policy_sha256="e" * 64).payload()
        second_id, second_body = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", second)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(read_bootstrap_evidence(github, 27, second_id), second)
        self.assertIn('"attempt":2', second_body)
        self.assertIn(f'"previous_comment_id":{first_id}', second_body)
        self.assertEqual(read_latest_bootstrap_evidence(github, 27), (second_id, second))

    def test_historical_review_ready_payload_remains_exact_when_new_technical_attempt_is_appended(self):
        github = FakeGitHub()
        historical = evaluate().payload()
        historical.pop("review_mode")
        historical["status"] = "BOOTSTRAP_REVIEW_READY"
        historical["can_request_final_user_review"] = True
        historical["self_review_comment_id"] = 200
        historical["independent_review_comment_id"] = 201
        historical["verified_review_evidence"] = [VerifiedReviewEvidence(
            "REQ-08", "https://github.com/puchinya/ai-agent-workflow/pull/33/files",
            "pull-request", "a" * 64, HEAD).as_dict()]
        historical["independent_context_artifact_comment_id"] = 202
        historical["independent_context_artifact_sha256"] = "a" * 64
        historical["separate_context_confirmed"] = True
        historical["independence_assurance"] = (
            "reviewer-attested; the host/session identity is not cryptographically verified")
        # Keep a schema-valid old record; its exact payload bytes remain in history.
        BootstrapResult.from_payload(historical)
        old_id, _ = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", historical)
        current = evaluate().payload()
        new_id, _ = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", current)
        self.assertGreater(new_id, old_id)
        self.assertEqual(read_bootstrap_evidence(github, 27, old_id), historical)
        self.assertEqual(read_bootstrap_evidence(github, 27, new_id), current)
        self.assertFalse(current["can_request_final_user_review"])

    def test_policy_source_digest_change_appends_new_bootstrap_attempt(self):
        github = FakeGitHub()
        first = evaluate(bootstrap_policy_sha256="f" * 64).payload()
        first_id, _ = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", first)
        updated_policy = evaluate(bootstrap_policy_sha256="e" * 64).payload()
        second_id, _ = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", updated_policy)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(read_bootstrap_evidence(github, 27, second_id), updated_policy)


if __name__ == "__main__":
    unittest.main()
