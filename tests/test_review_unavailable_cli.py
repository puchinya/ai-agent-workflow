from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import cli
from p_ases.checkpoint import PRBinding, write_pr_binding
from p_ases.evidence_store import VerificationSubject
from p_ases.execution import ExecutionBinding, write_binding
from p_ases.verification import VerificationResult
from p_ases.verification_plan import PlanEntry, create_plan
from p_ases.work import execution_binding_path, pr_binding_path


REPOSITORY = "puchinya/ai-agent-workflow"
ISSUE = 46
PR = 67
HEAD = "a" * 40
STALE_HEAD = "b" * 40
BASE_SHA = "c" * 40
ADC_COMMENT_ID = 6391179626
ADC_SHA = "d" * 64
BRANCH_REF = "codex/issue-46-multi-host-independent-review"


class FakeGitHub:
    def __init__(self, *, base_ref="main", base_sha=BASE_SHA, head_ref=BRANCH_REF,
                 head_sha=HEAD, body="Refs #46\n\nCloses #46"):
        self.base_ref = base_ref
        self.base_sha = base_sha
        self.head_ref = head_ref
        self.head_sha = head_sha
        self.body = body
        self.posts = 0

    def repository_metadata(self):
        return {"id": cli.REVIEW_EXCEPTION_REPOSITORY_ID}

    def pull_request(self, number):
        return {
            "number": number, "state": "open", "draft": False, "body": self.body,
            "base": {"ref": self.base_ref, "sha": self.base_sha,
                     "repo": {"full_name": REPOSITORY}},
            "head": {"ref": self.head_ref, "sha": self.head_sha,
                     "repo": {"full_name": REPOSITORY}},
        }


def _verification_plan():
    return create_plan(
        repository=REPOSITORY, issue_number=ISSUE, adc_comment_id=ADC_COMMENT_ID,
        adc_sha256=ADC_SHA,
        source_digests=(
            ("specification", "docs/specs/workflow-spec.md", "1" * 64),
            ("test_specification", "docs/testing/pases-lifecycle-tests.md", "2" * 64),
            ("oracle", "docs/design/workflow-design.md", "3" * 64),
        ),
        entries=(PlanEntry(
            req_id="REQ-F06-006", oracle_id="ORA-F06-006", test_id="TST-F06-006",
            target="linux", environment="ubuntu-py314", command=("/usr/bin/python", "-m", "unittest"),
            risk="high", acceptance="verify the current exact-subject review policy",
            evidence_required=("result",),
        ),),
        required_req_ids=("REQ-F06-006",),
    )


def _write_profile(root: Path) -> None:
    path = root / ".agent" / "project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 2, "initialized": True, "project_name": "ai-agent-workflow",
        "components": [],
        "branch": {"prefix": "codex", "max_slug_length": 48, "cleanup_on_switch": [],
                   "required_checks": [{"name": "ci", "trusted_app_id": 15368}]},
        "workspace": {}, "milestones": {}, "hooks": {},
        "independent_review": {"minimum_assurance": "host_verified",
                               "unavailable_handling": "owner_exception"},
    }), encoding="utf-8")


def _write_bindings(root: Path, *, base_sha=BASE_SHA, execution_branch=BRANCH_REF,
                    pr_binding_base_sha=BASE_SHA, pr_binding_branch=BRANCH_REF) -> None:
    binding = ExecutionBinding(
        repository=REPOSITORY, issue_number=ISSUE, adc_comment_id=ADC_COMMENT_ID,
        adc_sha256=ADC_SHA, base_ref="main", base_sha=base_sha,
        branch_ref=execution_branch, work_directory=str(root), initial_head_sha=base_sha,
    ).validate()
    write_binding(execution_binding_path(root, ISSUE), binding)
    pr_binding = PRBinding(
        REPOSITORY, ISSUE, ADC_COMMENT_ID, ADC_SHA, pr_binding_base_sha,
        pr_binding_branch, PR, HEAD,
    ).validate()
    write_pr_binding(pr_binding_path(root, ISSUE), pr_binding)


def _run_setup(github: FakeGitHub, root: Path, *, requested_head=HEAD,
               execution_base_sha=BASE_SHA, execution_branch=BRANCH_REF,
               pr_binding_base_sha=BASE_SHA, pr_binding_branch=BRANCH_REF):
    _write_profile(root)
    _write_bindings(root, base_sha=execution_base_sha, execution_branch=execution_branch,
                    pr_binding_base_sha=pr_binding_base_sha, pr_binding_branch=pr_binding_branch)
    plan = _verification_plan()
    verified_adc = SimpleNamespace(pointer=SimpleNamespace(comment_id=ADC_COMMENT_ID, sha256=ADC_SHA))
    args = SimpleNamespace(issue=ISSUE, pr=PR, head=requested_head, plan=root / "frozen-plan.json")

    def current_verification(calculation_args, repository, _root, _github):
        current_subject = cli._subject(
            repository, ISSUE, PR, calculation_args.head, verified_adc, plan,
        )
        result = VerificationResult(
            "PASS", current_subject, tuple(sorted(plan.source_digests)), "4" * 64,
            "5" * 64, ("6" * 64,), (),
        ).validate()
        return result, ()

    return plan, verified_adc, args, current_verification


def _patch_context(stack, github, root, plan, verified_adc, current_verification):
    stack.enter_context(patch(
        "p_ases.cli._approved_issue_adc",
        return_value=({"id": 5846549384}, verified_adc),
    ))
    stack.enter_context(patch("p_ases.cli._load_plan", return_value=(plan, (), (), ())))
    stack.enter_context(patch("p_ases.cli._calculate_verification", side_effect=current_verification))
    stack.enter_context(patch("p_ases.cli.head_sha40", return_value=HEAD))
    stack.enter_context(patch("p_ases.cli.worktree_clean", return_value=True))
    stack.enter_context(patch("p_ases.cli.current_branch", side_effect=lambda _root: github.head_ref))
    stack.enter_context(patch("p_ases.cli.remote_branch_sha", return_value=HEAD))


class ReviewUnavailableCliTests(unittest.TestCase):
    def test_flat_pr_readback_drives_context_and_plan_without_github_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = FakeGitHub()
            plan, verified_adc, args, current_verification = _run_setup(github, root)
            output_plan = root / "exception-plan.json"
            args.verification_plan = args.plan
            args.host_surface = "codex_cloud"
            args.output = output_plan

            output = io.StringIO()
            with contextlib.ExitStack() as stack:
                _patch_context(stack, github, root, plan, verified_adc, current_verification)
                normalized = cli._readback_current_pr(
                    github,
                    VerificationSubject(REPOSITORY, ISSUE, PR, ADC_COMMENT_ID, ADC_SHA,
                                         plan.sha256, HEAD).validate(),
                )
                self.assertEqual(normalized["base_ref"], "main")
                self.assertEqual(normalized["base_sha"], BASE_SHA)
                self.assertEqual(normalized["head_ref"], BRANCH_REF)
                self.assertEqual(normalized["head_sha"], HEAD)
                self.assertNotIn("base", normalized)
                self.assertNotIn("head", normalized)

                snapshot, eligibility = cli._review_unavailable_current_context(
                    github, REPOSITORY, root, ISSUE, PR, HEAD, args.verification_plan, args.host_surface,
                )
                self.assertEqual(eligibility.status, "HOST_NATIVE_CAPTURE_UNAVAILABLE")
                self.assertEqual(snapshot["base_ref"], "main")
                self.assertEqual(snapshot["base_sha40"], BASE_SHA)
                self.assertEqual(snapshot["branch_ref"], BRANCH_REF)

                with contextlib.redirect_stdout(output):
                    status = cli._delivery_review_unavailable_plan(args, REPOSITORY, root, github)

            result = json.loads(output.getvalue())
            self.assertEqual(status, 0)
            self.assertEqual(result["status"], "PLAN_READY")
            self.assertEqual(result["plan"]["snapshot"]["base_ref"], "main")
            self.assertEqual(result["plan"]["snapshot"]["base_sha40"], BASE_SHA)
            self.assertEqual(result["plan"]["snapshot"]["branch_ref"], BRANCH_REF)
            self.assertEqual(result["plan"]["snapshot"]["head_sha40"], HEAD)
            self.assertTrue(output_plan.is_file())
            self.assertEqual(github.posts, 0)

    def test_plan_cli_returns_structured_blocked_for_stale_pr_or_binding_identity(self):
        cases = (
            ("stale requested HEAD", {"requested_head": STALE_HEAD}, {}),
            ("wrong PR base ref", {}, {"base_ref": "release"}),
            ("wrong PR branch ref", {}, {"head_ref": "codex/other-issue"}),
            ("wrong ExecutionBinding base", {"execution_base_sha": "7" * 40}, {}),
            ("wrong ExecutionBinding branch", {"execution_branch": "codex/other-issue"}, {}),
            ("wrong PRBinding base", {"pr_binding_base_sha": "8" * 40}, {}),
            ("wrong PRBinding branch", {"pr_binding_branch": "codex/other-issue"}, {}),
        )
        for label, setup_overrides, github_overrides in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                github = FakeGitHub(**github_overrides)
                plan, verified_adc, args, current_verification = _run_setup(
                    github, root, **setup_overrides,
                )
                args.verification_plan = args.plan
                args.host_surface = "codex_cloud"
                args.output = root / "exception-plan.json"
                output = io.StringIO()
                with contextlib.ExitStack() as stack:
                    _patch_context(stack, github, root, plan, verified_adc, current_verification)
                    with contextlib.redirect_stdout(output):
                        status = cli._delivery_review_unavailable_plan(args, REPOSITORY, root, github)
                result = json.loads(output.getvalue())
                self.assertEqual(status, 2)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertTrue(result["reasons"])
                self.assertFalse(args.output.exists())
                self.assertEqual(github.posts, 0)


if __name__ == "__main__":
    unittest.main()
