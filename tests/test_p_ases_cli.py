from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import publish_adc
from p_ases.cli import (CLI_ADVANCE_TARGETS, _parser, _solo_owner_merge_actor_matches,
                        _verify_solo_owner_issue_approval, main)
from p_ases.evidence_store import VerificationSubject
from p_ases.github import GitHubError
from p_ases.phase_evidence import PhaseEvidenceError
from p_ases.user_review import FeedbackEvent, FeedbackSnapshot, UserReviewSubject
from p_ases.delivery import ReadinessResult
from test_adc_intake import FakeGitHub, adc_bytes


def verified_adc(comment_id: int = 77, digest: str = "a" * 64):
    return SimpleNamespace(
        pointer=SimpleNamespace(comment_id=comment_id, sha256=digest, byte_length=1, state="approved"),
        contract=SimpleNamespace(sha256=digest),
    )


def ordinary_context(github, adc=None):
    return (copy.deepcopy(github.record), adc or verified_adc(), None, "pases/issue-1", "b" * 40)


class PasesCLITests(unittest.TestCase):
    def test_solo_owner_finalize_requires_the_verified_human_merge_actor(self):
        owner_pr = {"merged_by": {"id": 42, "type": "User"}}
        self.assertTrue(_solo_owner_merge_actor_matches(owner_pr, 42))
        self.assertFalse(_solo_owner_merge_actor_matches({"merged_by": {"id": 99, "type": "User"}}, 42))
        self.assertFalse(_solo_owner_merge_actor_matches({"merged_by": {"id": 42, "type": "Bot"}}, 42))
        self.assertFalse(_solo_owner_merge_actor_matches({"merged_by": None}, 42))

    def test_solo_owner_issue_approval_uses_direct_list_direct_identity_readback(self):
        verification_subject = VerificationSubject(
            "octo/repo", 60, 61, 77, "a" * 64, "b" * 64, "c" * 40,
        ).validate()
        readiness = ReadinessResult("PASS", verification_subject, (), ("d" * 64,), "e" * 64).validate()
        subject = UserReviewSubject(verification_subject, readiness.sha256).validate()
        body = f"P-ASES-DECISION: APPROVED\nP-ASES-SUBJECT: {subject.sha256}"
        created = "2026-10-12T00:02:00Z"
        html_url = "https://github.com/octo/repo/issues/60#issuecomment-501"
        issue_url = "https://api.github.com/repos/octo/repo/issues/60"
        user = {"id": 42, "login": "owner", "type": "User"}
        comment = {"id": 501, "body": body, "created_at": created, "updated_at": created,
                   "html_url": html_url, "issue_url": issue_url, "user": user}
        event = FeedbackEvent(
            "issue-comment", "501", 42, "owner", "User", created, created, "approved", None,
            hashlib.sha256(body.encode("utf-8")).hexdigest(), html_url,
            subject_sha256=subject.sha256,
        ).validate()
        snapshot = FeedbackSnapshot(subject, (event,), (), "2026-10-12T00:03:00Z").validate()

        class GitHub:
            def __init__(self):
                self.direct_count = 0
                self.list_count = 0

            def issue_comments(self, _issue):
                self.list_count += 1
                return [deepcopy(comment)]

            def issue_comment(self, _issue, _comment):
                self.direct_count += 1
                return deepcopy(comment)

        github = GitHub()
        _verify_solo_owner_issue_approval(github, "octo/repo", 60, snapshot, 42)
        self.assertEqual(github.list_count, 2)
        self.assertEqual(github.direct_count, 2)

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
