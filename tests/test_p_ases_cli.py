from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import publish_adc
from p_ases.cli import (
    CLI_ADVANCE_TARGETS, CLIError, OwnerAuthorizationError, _delivery_final,
    _owner_merge_gate, _parser, _work_command, main,
)
from p_ases.delivery import ReadinessResult
from p_ases.evidence_store import VerificationSubject
from p_ases.github import GitHubError
from p_ases.owner_consent import OwnerDecisionError
from p_ases.phase_evidence import PhaseEvidenceError
from p_ases.user_review import UserReviewResult, UserReviewSubject
from p_ases.verification import VerificationResult
from test_adc_intake import FakeGitHub, adc_bytes


def verified_adc(comment_id: int = 77, digest: str = "a" * 64):
    return SimpleNamespace(
        pointer=SimpleNamespace(comment_id=comment_id, sha256=digest, byte_length=1, state="approved"),
        contract=SimpleNamespace(sha256=digest),
    )


def ordinary_context(github, adc=None):
    return (copy.deepcopy(github.record), adc or verified_adc(), None, "pases/issue-1", "b" * 40)


class PasesCLITests(unittest.TestCase):
    def test_owner_merge_gate_accepts_only_well_shaped_final_delivery_schemas(self):
        head = "a" * 40
        subject = {
            "repository": "puchinya/ai-agent-workflow", "issue_number": 63,
            "pr_number": 64, "pr_head_sha40": head,
        }
        plan = {"target_issue_number": 63, "pr_number": 64, "pr_head_sha40": head}
        args = SimpleNamespace(
            delivery_plan=Path("plan.json"), readiness=Path("readiness.json"),
            verification=Path("verification.json"), acceptance=Path("acceptance.json"),
            self_audit=Path("self-audit.json"), independent_review=Path("independent-review.json"),
            user_review_record=Path("user-review.json"),
        )

        def check(payload):
            output = io.StringIO()
            with patch("p_ases.cli._delivery_final", side_effect=lambda *_args, **_kwargs: (
                    print(json.dumps(payload)), 0)[1]), contextlib.redirect_stdout(output):
                return _owner_merge_gate(args, Path("."), object(), plan)

        common = {
            "status": "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION", "merge_authorized": False,
            "final_delivery_sha256": "9" * 64, "subject": subject, "blockers": [],
        }
        v3 = common | {
            "schema": "PASES_FINAL_DELIVERY_V3", "review_mode": "solo_owner",
            "branch_protection_sha256": None, "user_review_sha256": "1" * 64,
            "required_check_result_sha256": "2" * 64,
        }
        self.assertEqual(check(v3)["final_delivery_schema"], "PASES_FINAL_DELIVERY_V3")

        v1 = common | {
            "schema": "PASES_FINAL_DELIVERY_V1", "branch_protection_sha256": "3" * 64,
        }
        self.assertEqual(check(v1)["final_delivery_schema"], "PASES_FINAL_DELIVERY_V1")
        v2 = common | {
            "schema": "PASES_FINAL_DELIVERY_V2", "branch_protection_sha256": "3" * 64,
            "current_base_advance_sha256": "4" * 64,
        }
        self.assertEqual(check(v2)["final_delivery_schema"], "PASES_FINAL_DELIVERY_V2")

        for invalid in (
            v3 | {"review_mode": "external_reviewer"},
            v3 | {"branch_protection_sha256": "5" * 64},
            v3 | {"required_check_result_sha256": None},
            v1 | {"branch_protection_sha256": "not-a-digest"},
            v1 | {"review_mode": "solo_owner"},
            v2 | {"current_base_advance_sha256": None},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(OwnerAuthorizationError, "Final Delivery gates"):
                    check(invalid)

    def test_solo_owner_final_delivery_does_not_call_ruleset_or_branch_policy_apis(self):
        repository = "puchinya/ai-agent-workflow"
        head = "a" * 40
        subject = VerificationSubject(repository, 63, 64, 9064, "b" * 64, "c" * 64, head).validate()
        readiness = ReadinessResult("PASS", subject, (), ("d" * 64,), "e" * 64).validate()
        user_subject = UserReviewSubject(subject, readiness.sha256).validate()
        user_review = UserReviewResult(
            "APPROVED", user_subject, "f" * 64, (), "user-review", "user-review-relay:555", (),
            {
                "evidence_type": "PASES_USER_REVIEW_DECISION_V3",
                "evidence_channel": "chat_confirmed_gh_v1", "comment_id": 555,
                "body_sha256": "1" * 64, "owner_id": 3744776,
                "created_at": "2026-10-18T00:00:00Z", "review_session_sha256": "2" * 64,
                "predecessor_comment_id": None, "feedback_sha256": "3" * 64,
                "plan_sha256": "4" * 64, "approval_scope_sha256": "5" * 64,
            },
        ).validate()
        verification = VerificationResult("PASS", subject, (), "6" * 64, "7" * 64, ("8" * 64,), ()).validate()
        adc = verified_adc(700, "b" * 64)
        pr = {"number": 64, "state": "open", "head_sha": head, "base_ref": "main", "base_sha": "9" * 40}
        raw_pr = {"draft": False, "mergeable": True, "head": {"sha": head}}
        aggregate = {"headRefOid": head, "reviewDecision": None}
        snapshot_sha = "a" * 64
        session = SimpleNamespace(subject=user_subject, started_at="2026-10-18T00:00:00Z")
        snapshot = SimpleNamespace(sha256=snapshot_sha, subject=user_subject, events=())
        fresh = SimpleNamespace(events=(), unresolved_thread_ids=())
        readiness_path = Path("/tmp/pases-readiness.json")
        identity = object()
        pr_binding = object()
        profile = SimpleNamespace(final_delivery_review_mode="solo_owner", required_checks=(("ci", 15368),))
        github = SimpleNamespace(
            pull_request=Mock(return_value=raw_pr),
            pull_review_decision=Mock(return_value=aggregate),
            branch_protection=Mock(side_effect=GitHubError("forbidden", status_code=403)),
            repository_rulesets=Mock(side_effect=GitHubError("forbidden", status_code=403)),
            effective_branch_rules=Mock(side_effect=GitHubError("forbidden", status_code=403)),
            authenticated_user=Mock(return_value={"id": 3744776}),
        )
        args = SimpleNamespace(
            issue=63, pr=64, head=head, plan=Path("plan.json"),
            readiness=Path("readiness.json"), verification=Path("verification.json"),
            acceptance=Path("acceptance.json"), self_audit=Path("self-audit.json"),
            independent_review=Path("independent-review.json"),
            user_review_record=Path("user-review.json"),
        )

        def run_readiness(*_args, **_kwargs):
            print(json.dumps({"path": str(readiness_path)}))
            return 0

        patch_values = {
            "_approved_issue_adc": {"return_value": ({"number": 63}, adc)},
            "_load_plan": {"return_value": (object(), (), (), ())},
            "_subject": {"return_value": subject},
            "_readback_current_pr": {"return_value": pr},
            "load_profile": {"return_value": profile},
            "_read_execution_identity": {"return_value": identity},
            "pr_binding_path": {"return_value": Path("binding.json")},
            "read_pr_binding": {"return_value": pr_binding},
            "execution_identity_base": {"return_value": ("main", "9" * 40)},
            "_current_base_evidence_for_pr": {"return_value": None},
            "_solo_owner_identity": {"return_value": (3744776, 3744776, 3744776)},
            "read_readiness": {"return_value": readiness},
            "_delivery_readiness": {"side_effect": run_readiness},
            "_read_review_record": {"return_value": (user_subject, user_review, snapshot_sha)},
            "review_session_path": {"return_value": Path("session.json")},
            "read_review_session": {"return_value": session},
            "read_feedback_snapshot": {"return_value": snapshot},
            "feedback_digest": {"return_value": "f" * 64},
            "_review_payload_from_github": {"return_value": fresh},
            "_latest_review_snapshot": {"return_value": None},
            "merge_feedback_history": {"side_effect": lambda _old, current: current},
            "_read_user_review_relay_approval": {"return_value": {"approval": True}},
            "evaluate_user_review": {"return_value": user_review},
            "read_verification_result": {"return_value": verification},
            "_calculate_verification": {"return_value": (verification, ())},
            "verify_adc": {"return_value": adc},
            "_same_snapshot_payload": {"return_value": True},
            "_write_immutable": {"return_value": None},
            "build_ruleset_plan": {"side_effect": GitHubError("forbidden", status_code=403)},
        }
        def run_delivery():
            output = io.StringIO()
            with ExitStack() as stack, contextlib.redirect_stdout(output):
                patched = {
                    name: stack.enter_context(patch(f"p_ases.cli.{name}", **kwargs))
                    for name, kwargs in patch_values.items()
                }
                exit_code = _delivery_final(args, repository, Path("/tmp"), github)
            return exit_code, json.loads(output.getvalue()), patched

        exit_code, result, patched = run_delivery()
        self.assertEqual(exit_code, 0, result)
        self.assertEqual(result["status"], "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION")
        self.assertEqual(result["schema"], "PASES_FINAL_DELIVERY_V3")
        self.assertEqual(result["review_mode"], "solo_owner")
        patched["build_ruleset_plan"].assert_not_called()
        github.repository_rulesets.assert_not_called()
        github.effective_branch_rules.assert_not_called()
        github.branch_protection.assert_not_called()

        protection = {
            "required_status_checks": {"contexts": ["ci"]},
            "required_pull_request_reviews": {"required_approving_review_count": 1},
        }
        profile.final_delivery_review_mode = "external_reviewer"
        aggregate["reviewDecision"] = "APPROVED"
        github.pull_review_decision.return_value = aggregate
        github.branch_protection.side_effect = None
        github.branch_protection.return_value = protection
        exit_code, external_result, external_patched = run_delivery()
        self.assertEqual(exit_code, 0, external_result)
        self.assertEqual(external_result["status"], "READY_FOR_EXPLICIT_MERGE_AUTHORIZATION")
        self.assertEqual(external_result["schema"], "PASES_FINAL_DELIVERY_V1")
        external_patched["build_ruleset_plan"].assert_not_called()
        github.repository_rulesets.assert_not_called()
        github.effective_branch_rules.assert_not_called()

    def test_adoption_refresh_cli_is_exact_issue_scoped(self):
        args = _parser().parse_args([
            "work", "adoption-refresh", "63", "--repo", "puchinya/ai-agent-workflow",
            "--root", str(ROOT),
        ])
        self.assertEqual((args.namespace, args.verb, args.issue, args.repo),
                         ("work", "adoption-refresh", 63, "puchinya/ai-agent-workflow"))

    def test_adoption_refresh_rejects_other_issue_before_refresh(self):
        args = _parser().parse_args([
            "work", "adoption-refresh", "62", "--repo", "puchinya/ai-agent-workflow",
            "--root", str(ROOT),
        ])
        fake_github = SimpleNamespace()
        verified = verified_adc(200, "a" * 64)
        with patch("p_ases.cli._approved_issue_adc", return_value=({}, verified)), \
                patch("p_ases.cli.refresh_adopted_pr_binding") as refresh:
            with self.assertRaisesRegex(CLIError, "restricted to .* Issue #63"):
                _work_command(args, "puchinya/ai-agent-workflow", ROOT, fake_github)
        refresh.assert_not_called()

    def test_cli_exposes_exactly_twelve_namespaces_and_adds_project_context(self):
        namespaces = _parser()._subparsers._group_actions[0].choices
        self.assertEqual(set(namespaces), {
            "project", "context", "adc", "issue", "docs", "work", "pr",
            "verification", "acceptance", "audit", "user-review", "delivery",
        })
        self.assertEqual(_parser().parse_args(["project", "status", "--root", str(ROOT)]).verb, "status")
        context = _parser().parse_args(["context", "show", "32", "--root", str(ROOT),
                                        "--repo", "owner/repo"])
        self.assertEqual((context.verb, context.issue, context.repo), ("show", 32, "owner/repo"))

    def test_unbound_issue63_cannot_be_switched_to_a_new_work_branch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(verb="branch", issue=63, base_ref="main", base_sha="a" * 40,
                                   branch_ref="codex/issue-63-new", output=None)
            with patch("p_ases.cli._approved_issue_adc", return_value=(
                    {"number": 63}, verified_adc())):
                with patch("p_ases.cli.ensure_branch") as ensure_branch:
                    with self.assertRaisesRegex(CLIError, "open-PR continuation"):
                        _work_command(args, "puchinya/ai-agent-workflow", root, Mock())
            ensure_branch.assert_not_called()

    def test_consumer_ruleset_routes_parse_exact_approval_arguments(self):
        preflight = _parser().parse_args([
            "delivery", "consumer-activation-preflight", "--root", str(ROOT),
        ])
        self.assertEqual((preflight.namespace, preflight.verb),
                         ("delivery", "consumer-activation-preflight"))
        plan = _parser().parse_args([
            "delivery", "consumer-activation-ruleset-plan", "--output", "/tmp/pases-plan.json",
            "--root", str(ROOT),
        ])
        self.assertEqual((plan.verb, plan.output),
                         ("consumer-activation-ruleset-plan", Path("/tmp/pases-plan.json")))
        apply = _parser().parse_args([
            "delivery", "consumer-activation-ruleset-apply", "--plan", "/tmp/pases-plan.json",
            "--approval-comment-id", "123", "--root", str(ROOT),
        ])
        self.assertEqual((apply.verb, apply.plan, apply.approval_comment_id),
                         ("consumer-activation-ruleset-apply", Path("/tmp/pases-plan.json"), 123))
        no_approval = _parser().parse_args([
            "delivery", "consumer-activation-ruleset-apply", "--plan", "/tmp/pases-plan.json",
            "--root", str(ROOT),
        ])
        self.assertIsNone(no_approval.approval_comment_id)
        admin_apply = _parser().parse_args([
            "delivery", "consumer-activation-admin-apply", "--plan", "/tmp/pases-plan.json",
            "--repo", "puchinya/ai-agent-workflow", "--root", str(ROOT),
        ])
        self.assertIsNone(admin_apply.approval_comment_id)
        self.assertEqual(admin_apply.auth_mode, "isolated-gh-device")
        admin_plan = _parser().parse_args([
            "delivery", "consumer-activation-admin-plan", "--output", "/tmp/pases-plan.json",
            "--auth-mode", "isolated-gh-device", "--root", str(ROOT),
        ])
        self.assertEqual(admin_plan.auth_mode, "isolated-gh-device")
        device_apply = _parser().parse_args([
            "delivery", "consumer-activation-admin-apply", "--plan", "/tmp/pases-plan.json",
            "--auth-mode", "isolated-gh-device", "--root", str(ROOT),
        ])
        self.assertEqual(device_apply.auth_mode, "isolated-gh-device")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _parser().parse_args([
                "delivery", "consumer-activation-admin-plan", "--output", "/tmp/pases-plan.json",
                "--auth-mode", "unknown", "--root", str(ROOT),
            ])

    def test_admin_plan_forwards_selected_auth_mode_to_temporary_client(self):
        admin = SimpleNamespace(
            authenticated_user=lambda: {"id": 3744776, "type": "User", "login": "owner"},
            repository_metadata=lambda: {
                "id": 1401910271, "full_name": "puchinya/ai-agent-workflow",
                "owner": {"id": 3744776, "type": "User", "login": "owner"},
                "permissions": {"admin": True}, "default_branch": "main",
            },
            collaborator_permission=lambda _login: {"permission": "admin"},
            branch_protection=Mock(side_effect=GitHubError("legacy protection is not configured", status_code=404)),
            repository_rulesets=Mock(return_value=[]), effective_branch_rules=Mock(return_value=[]),
        )
        modes = []

        def admin_context(_repository, *, auth_mode):
            modes.append(auth_mode)
            return contextlib.nullcontext(admin)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint = root / "missing-checkpoint.json"
            with patch("p_ases.cli._runtime_root", return_value=root), \
                 patch("p_ases.cli.discover_repository", return_value="puchinya/ai-agent-workflow"), \
                 patch("p_ases.cli.GitHub", return_value=SimpleNamespace(repo="puchinya/ai-agent-workflow")), \
                 patch("p_ases.cli.load_profile", return_value=SimpleNamespace(activation_issue_number=57)), \
                 patch("p_ases.cli.activation_checkpoint_path", return_value=checkpoint), \
                 patch("p_ases.cli.temporary_admin_client", side_effect=admin_context), \
                 patch("p_ases.cli.build_ruleset_plan", return_value={
                     "blockers": [], "plan_sha256": "a" * 64, "diff": {"operation": "create"},
                 }), patch("p_ases.cli.write_ruleset_plan"), patch("p_ases.cli._json"):
                result = main([
                    "delivery", "consumer-activation-admin-plan", "--output", str(root / "plan.json"),
                    "--auth-mode", "isolated-gh-device", "--repo", "puchinya/ai-agent-workflow",
                    "--root", str(root),
                ])
        self.assertEqual(result, 0)
        self.assertEqual(modes, ["isolated-gh-device"])
        admin.branch_protection.assert_not_called()
        admin.repository_rulesets.assert_not_called()
        admin.effective_branch_rules.assert_not_called()

    def test_admin_apply_leaves_policy_preflight_to_ruleset_apply_verifier(self):
        admin = SimpleNamespace(
            authenticated_user=lambda: {"id": 3744776, "type": "User", "login": "owner"},
            repository_metadata=lambda: {
                "id": 1401910271, "full_name": "puchinya/ai-agent-workflow",
                "owner": {"id": 3744776, "type": "User", "login": "owner"},
                "permissions": {"admin": True}, "default_branch": "main",
            },
            collaborator_permission=lambda _login: {"permission": "admin"},
            branch_protection=Mock(side_effect=GitHubError("legacy protection is not configured", status_code=404)),
            repository_rulesets=Mock(return_value=[]), effective_branch_rules=Mock(return_value=[]),
        )
        plan = {"plan_sha256": "a" * 64, "diff": {"operation": "create"},
                "profile_ref": None, "activation_binding": None}

        def admin_context(_repository, *, auth_mode):
            self.assertEqual(auth_mode, "isolated-gh-device")
            return contextlib.nullcontext(admin)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("p_ases.cli._runtime_root", return_value=root), \
                    patch("p_ases.cli.discover_repository", return_value="puchinya/ai-agent-workflow"), \
                    patch("p_ases.cli.GitHub", return_value=SimpleNamespace(repo="puchinya/ai-agent-workflow")), \
                    patch("p_ases.cli.load_profile", return_value=SimpleNamespace(activation_issue_number=57)), \
                    patch("p_ases.cli.temporary_admin_client", side_effect=admin_context), \
                    patch("p_ases.cli._ruleset_operation_plan", return_value=(plan, 800)), \
                    patch("p_ases.cli._verify_activation_plan_checkpoint"), \
                    patch("p_ases.cli.apply_ruleset_plan", return_value={"status": "VERIFIED"}) as apply_plan, \
                    patch("p_ases.cli._json"):
                result = main([
                    "delivery", "consumer-activation-admin-apply", "--plan", str(root / "plan.json"),
                    "--approval-comment-id", "900", "--auth-mode", "isolated-gh-device",
                    "--repo", "puchinya/ai-agent-workflow", "--root", str(root),
                ])
        self.assertEqual(result, 0)
        apply_plan.assert_called_once()
        admin.branch_protection.assert_not_called()
        admin.repository_rulesets.assert_not_called()
        admin.effective_branch_rules.assert_not_called()

    def test_ruleset_write_route_never_self_authorizes_from_a_plan_or_admin_credential(self):
        plan = {
            "repository": "puchinya/ai-agent-workflow", "repository_id": 1401910271,
            "owner_id": 3744776, "activation_issue_number": 57,
            "plan_sha256": "a" * 64, "diff": {"operation": "create"},
        }
        fake_github = SimpleNamespace(repo="puchinya/ai-agent-workflow")
        with patch("p_ases.cli._runtime_root", return_value=ROOT), \
                patch("p_ases.cli.discover_repository", return_value="puchinya/ai-agent-workflow"), \
                patch("p_ases.cli.GitHub", return_value=fake_github), \
                patch("p_ases.cli.read_ruleset_plan", return_value=plan), \
                patch("p_ases.cli.read_verified_owner_decision",
                      side_effect=OwnerDecisionError("missing exact owner operation/subject")), \
                patch("p_ases.cli.apply_ruleset_plan") as apply_plan, \
                patch("p_ases.cli._json") as emit:
            result = main([
                "delivery", "consumer-activation-ruleset-apply", "--plan", "/tmp/pases-plan.json",
                "--approval-comment-id", "123", "--repo", "puchinya/ai-agent-workflow",
                "--root", str(ROOT),
            ])
        self.assertEqual(result, 2)
        self.assertEqual(emit.call_args.args[0]["status"], "PENDING_APPROVAL")
        apply_plan.assert_not_called()

    def test_owner_authorize_commit_cli_fails_closed_without_reading_stdin_or_writing(self):
        fake_github = SimpleNamespace(repo="puchinya/ai-agent-workflow", writes=0)
        stdin = Mock()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch("p_ases.cli._runtime_root", return_value=Path(temp_dir)), \
                patch("p_ases.cli.discover_repository", return_value="puchinya/ai-agent-workflow"), \
                patch("p_ases.cli.GitHub", return_value=fake_github), \
                patch("p_ases.cli.sys.stdin", stdin), \
                contextlib.redirect_stdout(output):
            status = main([
                "delivery", "owner-authorize-commit", "--plan", str(Path(temp_dir) / "plan.json"),
                "--repo", "puchinya/ai-agent-workflow", "--root", temp_dir,
            ])
        self.assertEqual(status, 2)
        self.assertIn("CHAT_CONFIRMATION_REQUIRED", output.getvalue())
        stdin.read.assert_not_called()
        self.assertEqual(fake_github.writes, 0)

    def test_activation_setup_pending_stage_is_not_a_success_exit_code(self):
        fake_github = SimpleNamespace(repo="puchinya/ai-agent-workflow")
        pending = {"status": "PENDING_APPROVAL", "stage": "AWAIT_OWNER_POLICY_DECISION",
                   "plan_sha256": "a" * 64}
        with patch("p_ases.cli._runtime_root", return_value=ROOT), \
                patch("p_ases.cli.discover_repository", return_value="puchinya/ai-agent-workflow"), \
                patch("p_ases.cli.GitHub", return_value=fake_github), \
                patch("p_ases.cli.setup_consumer_activation", return_value=pending), \
                patch("p_ases.cli._json") as emit:
            status = main(["delivery", "consumer-activation-setup", "--repo",
                           "puchinya/ai-agent-workflow", "--root", str(ROOT)])
        self.assertEqual(status, 2)
        self.assertEqual(emit.call_args.args[0], pending)

    def test_advance_cli_excludes_readiness_approval_and_close_targets(self):
        self.assertNotIn("user-review", CLI_ADVANCE_TARGETS)
        self.assertNotIn("closed", CLI_ADVANCE_TARGETS)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            _parser().parse_args([
                "issue", "advance", "1", "closed", "--kind", "child", "--repo", "octo/repo",
            ])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_advance_help_documents_later_evidence_and_github_readback(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            _parser().parse_args(["issue", "advance", "--help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("Review Readiness", help_text)
        self.assertIn("Issues #30 and #31", help_text)
        self.assertNotIn("closed", help_text)

    def test_phase_evidence_route_and_advance_require_explicit_receipt_reference(self):
        rebaseline = _parser().parse_args([
            "issue", "phase-rebaseline", "63", "--repo", "puchinya/ai-agent-workflow",
        ])
        self.assertEqual((rebaseline.namespace, rebaseline.verb, rebaseline.issue),
                         ("issue", "phase-rebaseline", 63))
        evidence = _parser().parse_args([
            "issue", "phase-evidence", "12", "requirements", "specification",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((evidence.namespace, evidence.verb, evidence.issue),
                         ("issue", "phase-evidence", 12))
        advance = _parser().parse_args([
            "issue", "advance", "12", "specification", "--kind", "child",
            "--phase-evidence-comment-id", "99", "--root", str(ROOT), "--repo", "octo/repo",
        ])
        self.assertEqual((advance.phase_evidence_comment_id, advance.root), (99, ROOT))

    def test_issue_63_approved_adc_publish_requires_exact_supersede_and_runs_phase_bootstrap(self):
        pointer = SimpleNamespace(comment_id=6228771810, sha256="a" * 64,
                                  byte_length=7, state="approved")
        predecessor = SimpleNamespace(comment_id=6228771805, sha256="b" * 64,
                                      byte_length=7, state="approved")
        decision = SimpleNamespace(comment_id=8123)
        github = SimpleNamespace(repo="puchinya/ai-agent-workflow")
        output = io.StringIO()
        with patch("p_ases.cli.GitHub", return_value=github), \
                patch("p_ases.cli.parse_adc", return_value=SimpleNamespace(sha256="a" * 64)), \
                patch("p_ases.cli.read_verified_owner_decision", return_value=decision) as read_decision, \
                patch("p_ases.cli.verify_adc", return_value=SimpleNamespace(pointer=predecessor)), \
                patch("p_ases.cli.publish_adc", return_value=pointer) as publish, \
                patch("p_ases.cli.rebaseline_issue_phase", return_value={"status": "APPLIED"}) as rebaseline, \
                contextlib.redirect_stdout(output):
            status = main([
                "adc", "publish", "63", str(Path(__file__)),
                "--repo", "puchinya/ai-agent-workflow", "--state", "approved", "--supersede",
                "--approval-comment-id", str(decision.comment_id),
            ])
        self.assertEqual(status, 0)
        self.assertIn('"phase_rebaseline": {\n    "status": "APPLIED"', output.getvalue())
        read_decision.assert_called_once_with(
            github, issue_number=63, owner_id=3744776,
                operation="ADC_SUPERSEDE", subject_sha256="a" * 64,
                repository_id=1401910271,
        )
        publish.assert_called_once()
        self.assertIs(publish.call_args.kwargs["expected_current"], predecessor)
        rebaseline.assert_called_once_with(github, 63)

    def test_issue_63_approved_adc_without_exact_supersede_is_pending_and_never_publishes(self):
        github = SimpleNamespace(repo="puchinya/ai-agent-workflow")
        output = io.StringIO()
        with patch("p_ases.cli.GitHub", return_value=github), \
                patch("p_ases.cli.publish_adc") as publish, \
                contextlib.redirect_stdout(output):
            status = main([
                "adc", "publish", "63", str(Path(__file__)),
                "--repo", "puchinya/ai-agent-workflow", "--state", "approved", "--supersede",
            ])
        self.assertEqual(status, 2)
        self.assertIn('"status": "PENDING_APPROVAL"', output.getvalue())
        publish.assert_not_called()

    def test_advance_refuses_caller_kind_mismatch_without_label_write(self):
        class GitHub:
            repo = "octo/repo"

            def __init__(self):
                self.record = {
                    "id": 1, "number": 1, "repository_url": "https://api.github.com/repos/octo/repo",
                    "state": "open", "body": "Issue body", "pull_request": None,
                    "labels": [{"name": "kind:single"}, {"name": "phase:requirements"}],
                }
                self.writes = 0

            def issue(self, _number):
                return copy.deepcopy(self.record)

            def replace_issue_labels(self, _number, _labels):
                self.writes += 1

        github = GitHub()
        stderr = io.StringIO()
        with patch("p_ases.cli._repo_root", return_value=ROOT), \
                patch("p_ases.cli.GitHub", return_value=github), \
                contextlib.redirect_stderr(stderr):
            status = main(["issue", "advance", "1", "specification", "--kind", "child",
                           "--phase-evidence-comment-id", "9", "--root", str(ROOT), "--repo", "octo/repo"])
        self.assertEqual(status, 2)
        self.assertEqual(github.writes, 0)
        self.assertIn("verified kind", stderr.getvalue())

    def test_advance_refuses_labels_changed_during_proof_readback_without_write(self):
        class GitHub:
            repo = "octo/repo"

            def __init__(self):
                self.record = {
                    "id": 1, "number": 1, "repository_url": "https://api.github.com/repos/octo/repo",
                    "state": "open", "body": "Issue body", "pull_request": None,
                    "labels": [{"name": "kind:child"}, {"name": "phase:requirements"}],
                }
                self.writes = 0

            def issue(self, _number):
                return copy.deepcopy(self.record)

            def replace_issue_labels(self, _number, _labels):
                self.writes += 1

        github = GitHub()
        reads = 0

        def change_after_proof(*_args, **_kwargs):
            nonlocal reads
            reads += 1
            if reads == 2:
                github.record["labels"] = [
                    {"name": "kind:child"}, {"name": "phase:design"},
                ]

        stderr = io.StringIO()
        with patch("p_ases.cli._repo_root", return_value=ROOT), \
                patch("p_ases.cli.GitHub", return_value=github), \
                patch("p_ases.cli.verify_ordinary_issue_context",
                      side_effect=lambda *_args, **_kwargs: ordinary_context(github)), \
                patch("p_ases.cli.verify_phase_evidence", side_effect=change_after_proof), \
                contextlib.redirect_stderr(stderr):
            status = main(["issue", "advance", "1", "specification", "--kind", "child",
                           "--phase-evidence-comment-id", "9", "--root", str(ROOT), "--repo", "octo/repo"])
        self.assertEqual(status, 2)
        self.assertEqual(github.writes, 0)
        self.assertIn("changed before the phase label write", stderr.getvalue())

    def test_advance_recovers_lost_label_write_response_only_after_exact_readback(self):
        class GitHub:
            repo = "octo/repo"

            def __init__(self):
                self.record = {
                    "id": 1, "number": 1, "repository_url": "https://api.github.com/repos/octo/repo",
                    "state": "open", "body": "Issue body", "pull_request": None,
                    "labels": [{"name": "enhancement"}, {"name": "kind:child"},
                               {"name": "phase:execution"}, {"name": "priority:high"}],
                }
                self.writes = 0

            def issue(self, _number):
                return copy.deepcopy(self.record)

            def replace_issue_labels(self, _number, labels):
                self.writes += 1
                self.record["labels"] = [{"name": label} for label in labels]
                raise GitHubError("simulated successful write with lost response")

        github = GitHub()
        stdout = io.StringIO()
        with patch("p_ases.cli.GitHub", return_value=github), \
                patch("p_ases.cli.verify_ordinary_issue_context",
                      side_effect=lambda *_args, **_kwargs: ordinary_context(github)), \
                contextlib.redirect_stdout(stdout):
            status = main(["issue", "advance", "1", "verification", "--kind", "child",
                           "--root", str(ROOT), "--repo", "octo/repo"])
        self.assertEqual(status, 0)
        self.assertEqual(github.writes, 1)
        self.assertIn('"status": "ADVANCED"', stdout.getvalue())
        self.assertEqual({row["name"] for row in github.record["labels"]}, {
            "enhancement", "kind:child", "phase:verification", "priority:high",
        })

    def test_advance_blocks_successful_put_when_postwrite_issue_identity_or_body_changes(self):
        for changed_field in ("body", "repository_url"):
            class GitHub:
                repo = "octo/repo"

                def __init__(self):
                    self.record = {
                        "id": 1, "number": 1, "repository_url": "https://api.github.com/repos/octo/repo",
                        "state": "open", "body": "Issue body", "pull_request": None,
                        "labels": [{"name": "kind:child"}, {"name": "phase:execution"}],
                    }
                    self.writes = 0

                def issue(self, _number):
                    return copy.deepcopy(self.record)

                def replace_issue_labels(self, _number, labels):
                    self.writes += 1
                    self.record["labels"] = [{"name": label} for label in labels]
                    self.record[changed_field] = (
                        "changed after PUT" if changed_field == "body"
                        else "https://api.github.com/repos/other/repo"
                    )

            github = GitHub()
            stderr = io.StringIO()
            with self.subTest(changed_field=changed_field), \
                    patch("p_ases.cli.GitHub", return_value=github), \
                    patch("p_ases.cli.verify_ordinary_issue_context",
                          side_effect=lambda *_args, **_kwargs: ordinary_context(github)), \
                    contextlib.redirect_stderr(stderr):
                status = main(["issue", "advance", "1", "verification", "--kind", "child",
                               "--root", str(ROOT), "--repo", "octo/repo"])
            self.assertEqual(status, 2)
            self.assertEqual(github.writes, 1)
            self.assertIn("BLOCKED after phase label write", stderr.getvalue())
            self.assertIn("label PUT may already have applied", stderr.getvalue())

    def test_advance_blocks_lost_put_response_when_body_changes_after_write(self):
        class GitHub:
            repo = "octo/repo"

            def __init__(self):
                self.record = {
                    "id": 1, "number": 1, "repository_url": "https://api.github.com/repos/octo/repo",
                    "state": "open", "body": "Issue body", "pull_request": None,
                    "labels": [{"name": "kind:child"}, {"name": "phase:execution"}],
                }
                self.writes = 0

            def issue(self, _number):
                return copy.deepcopy(self.record)

            def replace_issue_labels(self, _number, labels):
                self.writes += 1
                self.record["labels"] = [{"name": label} for label in labels]
                self.record["body"] = "ADC pointer changed after label PUT"
                raise GitHubError("simulated lost response")

        github = GitHub()
        stderr = io.StringIO()
        with patch("p_ases.cli.GitHub", return_value=github), \
                patch("p_ases.cli.verify_ordinary_issue_context",
                      side_effect=lambda *_args, **_kwargs: ordinary_context(github)), \
                contextlib.redirect_stderr(stderr):
            status = main(["issue", "advance", "1", "verification", "--kind", "child",
                           "--root", str(ROOT), "--repo", "octo/repo"])
        self.assertEqual(status, 2)
        self.assertEqual(github.writes, 1)
        self.assertIn("BLOCKED after phase label write", stderr.getvalue())
        self.assertIn("label PUT may already have applied", stderr.getvalue())

    def test_advance_blocks_when_approved_adc_generation_changes_after_put(self):
        class GitHub:
            repo = "octo/repo"

            def __init__(self):
                self.record = {
                    "id": 1, "number": 1, "repository_url": "https://api.github.com/repos/octo/repo",
                    "state": "open", "body": "Issue body", "pull_request": None,
                    "labels": [{"name": "kind:child"}, {"name": "phase:execution"}],
                }

            def issue(self, _number):
                return copy.deepcopy(self.record)

            def replace_issue_labels(self, _number, labels):
                self.record["labels"] = [{"name": label} for label in labels]

        github = GitHub()
        context_calls = 0

        def context_after_current_read(*_args, **_kwargs):
            nonlocal context_calls
            context_calls += 1
            adc = verified_adc() if context_calls < 3 else verified_adc(88, "c" * 64)
            return ordinary_context(github, adc)

        stderr = io.StringIO()
        with patch("p_ases.cli.GitHub", return_value=github), \
                patch("p_ases.cli.verify_ordinary_issue_context", side_effect=context_after_current_read), \
                contextlib.redirect_stderr(stderr):
            status = main(["issue", "advance", "1", "verification", "--kind", "child",
                           "--root", str(ROOT), "--repo", "octo/repo"])
        self.assertEqual(status, 2)
        self.assertIn("approved ADC pointer or generation changed after the phase label write", stderr.getvalue())
        self.assertNotIn("ADVANCED", stderr.getvalue())

    def test_ordinary_phase_advance_blocks_missing_activation_adc_or_binding(self):
        class GitHub:
            repo = "octo/repo"

            def __init__(self):
                self.record = {
                    "id": 40, "number": 40, "repository_url": "https://api.github.com/repos/octo/repo",
                    "state": "open", "body": "Issue body", "pull_request": None,
                    "labels": [{"name": "kind:child"}, {"name": "phase:ready"}],
                }
                self.writes = 0

            def issue(self, _number):
                return copy.deepcopy(self.record)

            def replace_issue_labels(self, _number, _labels):
                self.writes += 1

        for failure in ("Activation missing", "approved ADC missing", "frozen binding missing"):
            github = GitHub()
            stderr = io.StringIO()
            with self.subTest(failure=failure), \
                    patch("p_ases.cli.GitHub", return_value=github), \
                    patch("p_ases.cli.verify_ordinary_issue_context",
                          side_effect=PhaseEvidenceError(failure)), \
                    contextlib.redirect_stderr(stderr):
                status = main(["issue", "advance", "40", "execution", "--kind", "child",
                               "--root", str(ROOT), "--repo", "octo/repo"])
            self.assertEqual(status, 2)
            self.assertEqual(github.writes, 0)
            self.assertIn(failure, stderr.getvalue())

    def test_ready_to_execution_requires_current_ready_receipt_before_label_write(self):
        class GitHub:
            repo = "octo/repo"

            def __init__(self):
                self.record = {
                    "id": 40, "number": 40, "repository_url": "https://api.github.com/repos/octo/repo",
                    "state": "open", "body": "Issue body", "pull_request": None,
                    "labels": [{"name": "kind:child"}, {"name": "phase:ready"}],
                }
                self.writes = 0

            def issue(self, _number):
                return copy.deepcopy(self.record)

            def replace_issue_labels(self, _number, _labels):
                self.writes += 1

        github = GitHub()
        stderr = io.StringIO()
        with patch("p_ases.cli.GitHub", return_value=github), \
                patch("p_ases.cli.verify_ordinary_issue_context",
                      side_effect=lambda *_args, **_kwargs: ordinary_context(github)), \
                patch("p_ases.cli.verify_ready_preparation",
                      side_effect=PhaseEvidenceError("ready receipt is stale")), \
                contextlib.redirect_stderr(stderr):
            status = main(["issue", "advance", "40", "execution", "--kind", "child",
                           "--root", str(ROOT), "--repo", "octo/repo"])
        self.assertEqual(status, 2)
        self.assertEqual(github.writes, 0)
        self.assertIn("ready receipt is stale", stderr.getvalue())

    def test_explicit_repository_lets_github_commands_run_without_local_checkout(self):
        github = FakeGitHub()
        publish_adc(github, 1, adc_bytes(), state="approved", explicitly_approved=True)
        output = io.StringIO()
        with patch("p_ases.cli._repo_root", side_effect=AssertionError("checkout lookup was attempted")), \
                patch("p_ases.cli.GitHub", return_value=github), \
                contextlib.redirect_stdout(output):
            status = main(["adc", "verify", "1", "--repo", "octo/repo"])
        self.assertEqual(status, 0)
        self.assertIn('"status": "VERIFIED"', output.getvalue())

    def test_issue_31_cli_namespaces_are_present_and_chat_file_fails_closed(self):
        args = _parser().parse_args([
            "user-review", "start", "31", "37", "a" * 40, "plan.json", "readiness.json",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((args.namespace, args.verb), ("user-review", "start"))
        args = _parser().parse_args([
            "issue", "integration-check", "26", "--verification-comment-id", "100",
            "--acceptance-comment-id", "101",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((args.namespace, args.verb), ("issue", "integration-check"))
        self.assertEqual((args.verification_comment_id, args.acceptance_comment_id), (100, 101))
        migration = _parser().parse_args([
            "delivery", "parent-migrate-labels", "26", "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertFalse(migration.apply)
        evidence = _parser().parse_args([
            "delivery", "parent-evidence", "26", "verification", "600",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((evidence.verb, evidence.kind), ("parent-evidence", "verification"))
        self.assertEqual(evidence.run_id, 600)
        stdout = io.StringIO()
        with patch("p_ases.cli._repo_root", return_value=ROOT), contextlib.redirect_stdout(stdout):
            status = main(["user-review", "record", "31", "37", "untrusted.json",
                           "--repo", "octo/repo", "--root", str(ROOT)])
        self.assertEqual(status, 2)
        self.assertIn("UNVERIFIABLE_CHAT_IDENTITY", stdout.getvalue())

    def test_final_delivery_cli_exposes_all_distinct_gates(self):
        args = _parser().parse_args([
            "delivery", "final", "31", "37", "a" * 40, "plan.json", "verification.json",
            "acceptance.json", "self.json", "independent.json", "readiness.json", "review.json",
            "--repo", "octo/repo", "--root", str(ROOT),
        ])
        self.assertEqual((args.namespace, args.verb), ("delivery", "final"))


if __name__ == "__main__":
    unittest.main()
