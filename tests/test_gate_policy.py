from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.gate_policy import (
    ActivationRecord, BootstrapIndependentReview, BootstrapSelfReview, BootstrapSubject,
    GatePolicyError, LocalCheck, ReviewFinding, ReviewItem, evaluate_bootstrap,
    parse_independent_review_comment, parse_self_review_comment, publish_immutable_record, read_review_comment,
    read_bootstrap_evidence, select_gate,
    pin_gate_selection, read_activation_record, _require_repository_owner_actor,
)


REPO = "octo/repo"
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


def self_review(subj=None, items=None):
    subj = subj or subject()
    rows = items or (
        ReviewItem("CHECKLIST-001", "PASS", ("https://github.com/octo/repo/pull/33/files",)),
        ReviewItem("CHECKLIST-002", "PASS", ("https://github.com/octo/repo/pull/33/files",)),
        ReviewItem("REQ-08", "PASS", ("https://github.com/octo/repo/pull/33/files",)),
    )
    return BootstrapSelfReview(subj, "implementation-context", tuple(rows), 200)


def independent_review(subj=None, context="review-context", findings=(), verdict="PASS"):
    return BootstrapIndependentReview(subj or subject(), context, "implementation-context",
                                      "https://github.com/octo/repo/issues/27#issuecomment-201",
                                      "e" * 64, tuple(findings), verdict, 201)


def evaluate(**overrides):
    values = dict(subject=subject(), pr=pr_readback(), response_repository=REPO,
                  workflow_runs=[workflow_run()], check_runs=check_runs(),
                  required_check_names=("test-a", "test-b"), local_checks=local_checks(),
                  adc_requirement_ids=("REQ-08",), adc_checklist_ids=("CHECKLIST-001", "CHECKLIST-002"),
                  self_review=self_review(), independent_review=independent_review(), unverified_hosts=("none",))
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

    def test_valid_current_subject_can_be_bootstrap_review_ready(self):
        result = evaluate()
        self.assertEqual(result.status, "BOOTSTRAP_REVIEW_READY")
        self.assertEqual(result.workflow_run_id, 500)
        self.assertEqual(result.payload()["schema"], "PASES_BOOTSTRAP_REVIEW_V1")
        self.assertIn("unverified_hosts", result.payload())

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

    def test_self_review_must_cover_every_adc_requirement_and_checklist(self):
        incomplete = self_review(items=(ReviewItem("REQ-08", "PASS", ("evidence",)),))
        self.assertEqual(evaluate(self_review=incomplete).status, "BOOTSTRAP_BLOCKED")
        wrong_subject = self_review(subj=subject(head_sha40="f" * 40))
        self.assertEqual(evaluate(self_review=wrong_subject).status, "BOOTSTRAP_BLOCKED")
        self.assertEqual(evaluate(self_review=None).status, "BOOTSTRAP_BLOCKED")

    def test_independent_review_requires_distinct_context_and_zero_unresolved_ab(self):
        same_context = independent_review(context="implementation-context")
        self.assertEqual(evaluate(independent_review=same_context).status, "BOOTSTRAP_BLOCKED")
        finding = ReviewFinding("A-01", "A", False, "blocking issue", "https://github.com/octo/repo/pull/33")
        unresolved = independent_review(findings=(finding,), verdict="CONCERNS")
        self.assertEqual(evaluate(independent_review=unresolved).status, "BOOTSTRAP_BLOCKED")
        self.assertEqual(evaluate(independent_review=None).status, "BOOTSTRAP_BLOCKED")

    def test_review_comment_payloads_are_canonical_and_digest_bound(self):
        self_body = self_review().comment_body()
        parsed_self = parse_self_review_comment(self_body, 200)
        parsed_self.validate(("CHECKLIST-001", "CHECKLIST-002", "REQ-08"))
        with self.assertRaises(GatePolicyError):
            parse_self_review_comment(self_body + " ", 200)
        independent = independent_review()
        parsed_independent = parse_independent_review_comment(independent.comment_body(), 201)
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
        _require_repository_owner_actor({"login": "octo"}, REPO, "Activation approval")
        with self.assertRaises(GatePolicyError):
            _require_repository_owner_actor({"login": "automation-bot"}, REPO, "Activation approval")
        with self.assertRaises(GatePolicyError):
            _require_repository_owner_actor(None, REPO, "child PR merge")

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


class ImmutableBootstrapRecordTests(unittest.TestCase):
    def test_gate_selection_is_immutable_and_exact_retry_is_reused(self):
        github = FakeGitHub()
        first = select_gate(REPO, 27, selected_at="2026-10-11T00:00:00Z")
        first_id, _ = pin_gate_selection(github, first)
        retry = select_gate(REPO, 27, selected_at="2026-10-11T01:00:00Z")
        retry_id, _ = pin_gate_selection(github, retry)
        self.assertEqual(first_id, retry_id)
        conflict = select_gate(REPO, 27, selected_at="2026-10-11T02:00:00Z")
        conflict = type(conflict)(REPO, 27, "p-ases-v1", "2026-10-11T02:00:00Z", 500, "f" * 64)
        with self.assertRaises(GatePolicyError):
            pin_gate_selection(github, conflict)

    def test_exact_retry_reuses_comment_and_changed_observation_appends_linked_record(self):
        github = FakeGitHub()
        first = evaluate(independent_review=None).payload()
        first_id, _ = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", first)
        self.assertEqual(read_bootstrap_evidence(github, 27, first_id), first)
        retry_id, _ = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", first)
        self.assertEqual(first_id, retry_id)
        second = evaluate().payload()
        second_id, second_body = publish_immutable_record(github, 27, "PASES_BOOTSTRAP_REVIEW_V1", second)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(read_bootstrap_evidence(github, 27, second_id), second)
        self.assertIn('"attempt":2', second_body)
        self.assertIn(f'"previous_comment_id":{first_id}', second_body)


if __name__ == "__main__":
    unittest.main()
