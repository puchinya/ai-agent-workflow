from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.delivery import ReadinessResult, ReadinessResultV2
from p_ases.evidence_store import VerificationSubject
from p_ases.execution import ExecutionBinding, binding_digest, write_binding
from p_ases.git import GitError
from p_ases.profile import load_profile
from p_ases.review_assurance import IndependentReviewV2, write_independent_review_v2
from p_ases.user_review import (
    FeedbackSnapshot, UserReviewError, UserReviewSession, UserReviewSubject,
    feedback_snapshot_path, normalize_github_feedback, read_review_session,
    review_session_path, write_review_session,
)
from p_ases.verification import VerificationResult
from p_ases.cli import (
    CLIError, _delivery_final, _latest_review_snapshot, _recompute_user_review_readiness,
    _user_review_run,
)


HEAD = "a" * 40
VERIFICATION_SUBJECT = VerificationSubject(
    "octo/repo", 31, 37, 123, "b" * 64, "c" * 64, HEAD).validate()
READINESS = ReadinessResult("PASS", VERIFICATION_SUBJECT, (), ("d" * 64,), "e" * 64).validate()
USER_SUBJECT = UserReviewSubject(VERIFICATION_SUBJECT, READINESS.sha256).validate()


class UserReviewCliRegressionTests(unittest.TestCase):
    @staticmethod
    def _approved_feedback(subject, observed_at):
        event_at = "2026-10-25T10:02:00Z"
        events = normalize_github_feedback(
            issue_comments=(), pr_comments=(),
            pr_reviews=({
                "id": 700, "state": "APPROVED", "commit_id": HEAD, "body": "",
                "user": {"id": 42, "login": "octocat", "type": "User"},
                "submitted_at": event_at, "updated_at": event_at,
                "html_url": "https://github.com/octo/repo/pull/37#pullrequestreview-700",
            },),
            diff_comments=(),
        )
        return FeedbackSnapshot(subject, events, (), observed_at).validate()

    def _invoke_approved_start(self, root, github, clock_values, *, session_writer=None):
        verified_adc = SimpleNamespace(
            pointer=SimpleNamespace(state="approved", comment_id=5, sha256="f" * 64),
        )
        clock_values = iter(clock_values)
        clock_calls = []

        class FrozenClock:
            @staticmethod
            def now(_tz):
                value = next(clock_values)
                clock_calls.append(value)
                return value

        args = SimpleNamespace(
            verb="start", issue=31, pr=37, head=HEAD, plan=root / "plan.json",
            readiness=root / "readiness.json", kind="child", new_scope=False,
            review_unavailable_exception=None,
        )
        assurance = (object(), object())
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("p_ases.cli.datetime", FrozenClock))
            stack.enter_context(patch("p_ases.cli._approved_issue_adc", return_value=({}, verified_adc)))
            stack.enter_context(patch("p_ases.cli.verify_adc", return_value=verified_adc))
            stack.enter_context(patch("p_ases.cli._load_plan", return_value=(object(), (), (), ())))
            stack.enter_context(patch("p_ases.cli._subject", return_value=VERIFICATION_SUBJECT))
            stack.enter_context(patch("p_ases.cli._readback_current_pr", return_value={"head_sha": HEAD}))
            stack.enter_context(patch("p_ases.cli.read_readiness", return_value=READINESS))
            stack.enter_context(patch("p_ases.cli._recompute_user_review_readiness", return_value=READINESS))
            stack.enter_context(patch("p_ases.cli.read_binding", return_value=object()))
            stack.enter_context(patch("p_ases.cli._require_readiness_review_assurance", return_value=assurance))
            stack.enter_context(patch(
                "p_ases.cli._review_payload_from_github",
                side_effect=lambda _github, subject, *, observed_at: self._approved_feedback(subject, observed_at),
            ))
            if session_writer is not None:
                stack.enter_context(patch("p_ases.cli.write_review_session", side_effect=session_writer))
            stack.enter_context(contextlib.redirect_stdout(output))
            status = _user_review_run(args, "octo/repo", root, github)
        return status, json.loads(output.getvalue()), clock_calls

    def test_repeated_start_reuses_original_session_after_approval(self):
        class FakeGitHub:
            def __init__(self):
                self.labels = ["kind:child", "phase:verification"]
                self.label_writes = 0

            def issue(self, _number):
                return {"number": 31, "state": "open", "pull_request": None,
                        "labels": [{"name": label} for label in self.labels]}

            def pull_request(self, _number):
                return {"number": 37, "head": {"sha": HEAD}}

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

            def replace_issue_labels(self, _number, labels):
                self.label_writes += 1
                self.labels = list(labels)

        values = (
            datetime(2026, 10, 25, 10, 1, tzinfo=timezone.utc),  # session start T1
            datetime(2026, 10, 25, 10, 3, tzinfo=timezone.utc),  # first observation
            datetime(2026, 10, 25, 10, 4, tzinfo=timezone.utc),  # first final readback
            datetime(2026, 10, 25, 10, 5, tzinfo=timezone.utc),  # replay observation
            datetime(2026, 10, 25, 10, 6, tzinfo=timezone.utc),  # replay final readback
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = FakeGitHub()
            write_calls = []

            def count_write(path, session):
                write_calls.append(session)
                return write_review_session(path, session)

            first_status, first_result, first_clock_calls = self._invoke_approved_start(
                root, github, values[:3], session_writer=count_write,
            )
            second_status, second_result, second_clock_calls = self._invoke_approved_start(
                root, github, values[3:], session_writer=count_write,
            )

            session = read_review_session(review_session_path(root, USER_SUBJECT))
            self.assertEqual(first_status, 0)
            self.assertEqual(first_result["status"], "APPROVED")
            self.assertEqual(second_status, 0)
            self.assertEqual(second_result["status"], "APPROVED")
            self.assertFalse(any("predates" in reason for reason in second_result["reasons"]))
            self.assertEqual(session.started_at, "2026-10-25T10:01:00.000000Z")
            self.assertEqual(len(write_calls), 1)
            self.assertEqual(github.label_writes, 1)
            self.assertEqual(len(first_clock_calls), 3)
            self.assertEqual(len(second_clock_calls), 2)

    def test_concurrent_start_with_different_session_writes_no_feedback_or_phase(self):
        class FakeGitHub:
            def __init__(self):
                self.labels = ["kind:child", "phase:verification"]
                self.label_writes = 0

            def issue(self, _number):
                return {"number": 31, "state": "open", "pull_request": None,
                        "labels": [{"name": label} for label in self.labels]}

            def pull_request(self, _number):
                return {"number": 37, "head": {"sha": HEAD}}

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

            def replace_issue_labels(self, _number, labels):
                self.label_writes += 1
                self.labels = list(labels)

        def concurrent_writer(path, candidate):
            competing = UserReviewSession(candidate.subject, "2026-10-25T10:00:00Z").validate()
            write_review_session(path, competing)
            return write_review_session(path, candidate)

        values = (
            datetime(2026, 10, 25, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 10, 25, 10, 3, tzinfo=timezone.utc),
            datetime(2026, 10, 25, 10, 4, tzinfo=timezone.utc),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = FakeGitHub()
            status, result, _calls = self._invoke_approved_start(
                root, github, values, session_writer=concurrent_writer,
            )
            review_dir = review_session_path(root, USER_SUBJECT).parent
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("concurrent start" in reason for reason in result["reasons"]))
            self.assertEqual(sorted(path.name for path in review_dir.iterdir()), ["session.json"])
            self.assertEqual(github.label_writes, 0)

    def test_operator_supplied_native_bytes_block_all_user_review_verbs(self):
        class FakeGitHub:
            def __init__(self, phase):
                self.phase = phase

            def issue(self, _number):
                return {"number": 31, "state": "open", "pull_request": None,
                        "labels": [{"name": "kind:child"}, {"name": f"phase:{self.phase}"}]}

            def pull_request(self, _number):
                return {"number": 37, "head": {"sha": HEAD}}

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

        verified_adc = SimpleNamespace(pointer=SimpleNamespace(state="approved", comment_id=5, sha256="f" * 64))

        def feedback(_github, subject, *, observed_at):
            return FeedbackSnapshot(subject, (), (), observed_at).validate()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_value = {
                "schema_version": 2, "initialized": True, "project_name": "test",
                "components": [], "branch": {"prefix": "feature", "max_slug_length": 48,
                    "cleanup_on_switch": [], "required_checks": [{"name": "ci", "trusted_app_id": 2}]},
                "workspace": {}, "milestones": {}, "hooks": {},
                "independent_review": {"minimum_assurance": "independent_attested"},
            }
            profile_path = root / ".agent" / "project.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(profile_value), encoding="utf-8")
            profile = load_profile(root)
            binding = ExecutionBinding(
                repository="octo/repo", issue_number=31, adc_comment_id=123,
                adc_sha256="b" * 64, base_ref="main", base_sha="1" * 40,
                work_directory=str(root), branch_ref="feature/review", initial_head_sha="1" * 40,
            ).validate()
            write_binding(root / ".p_ases" / "state" / "31" / "execution-binding.json", binding)
            execution = f"execution-binding:{binding_digest(binding)}"
            review = IndependentReviewV2(
                subject=VERIFICATION_SUBJECT, assurance="UNAVAILABLE",
                reviewer_context_id="native-capture-unavailable",
                execution_identity_context_id=execution, verdict="BLOCKED", findings=(),
                profile_sha256=profile.profile_sha256,
                evidence_origin="no_host_native_capture_boundary",
            ).validate()
            review_path = (root / ".p_ases" / "audits" / "31" / VERIFICATION_SUBJECT.sha256
                           / f"independent-v2-{review.sha256}.json")
            write_independent_review_v2(review_path, review)
            readiness = ReadinessResult(
                "PASS", VERIFICATION_SUBJECT, (), tuple(sorted((review.sha256, profile.profile_sha256)),),
                "e" * 64,
            ).validate()
            user_subject = UserReviewSubject(VERIFICATION_SUBJECT, readiness.sha256).validate()
            for verb in ("start", "sync", "status"):
                phase = "verification" if verb == "start" else "user-review"
                args = SimpleNamespace(verb=verb, issue=31, pr=37, head=HEAD,
                                       plan=root / "plan.json", readiness=root / "readiness.json",
                                       kind="child", new_scope=False)
                output = io.StringIO()
                with patch("p_ases.cli._approved_issue_adc", return_value=({}, verified_adc)), \
                        patch("p_ases.cli.verify_adc", return_value=verified_adc), \
                        patch("p_ases.cli._load_plan", return_value=(object(), (), (), ())), \
                        patch("p_ases.cli._subject", return_value=VERIFICATION_SUBJECT), \
                        patch("p_ases.cli._readback_current_pr", return_value={"head_sha": HEAD}), \
                        patch("p_ases.cli.read_readiness", return_value=readiness), \
                        patch("p_ases.cli._recompute_user_review_readiness", return_value=readiness), \
                        patch("p_ases.cli._review_payload_from_github", side_effect=feedback), \
                        patch("p_ases.cli._review_phase_transition"), \
                        contextlib.redirect_stdout(output):
                    status = _user_review_run(args, "octo/repo", root, FakeGitHub(phase))
                result = json.loads(output.getvalue())
                self.assertEqual(result["status"], "BLOCKED")
                self.assertTrue(any("capture boundary" in reason for reason in result["reasons"]))
                self.assertEqual(status, 2)
                self.assertFalse((root / ".p_ases" / "user-review" / "31" / user_subject.sha256
                                  / "session.json").exists())

    def test_issue_phase_and_actual_kind_are_checked_before_any_user_review_side_effect(self):
        class FakeGitHub:
            def __init__(self, labels):
                self.labels = labels
                self.label_writes = 0

            def issue(self, _number):
                return {"number": 46, "state": "open", "pull_request": None,
                        "labels": [{"name": label} for label in self.labels]}

            def replace_issue_labels(self, _number, _labels):
                self.label_writes += 1

        cases = (
            (("kind:single", "phase:execution"), None, "invalid from phase:execution"),
            (("kind:single", "phase:verification"), "child", "--kind does not match"),
            (("kind:single", "phase:verification", "attention:blocked"), None, "attention:* label"),
        )
        for labels, requested_kind, expected in cases:
            with self.subTest(labels=labels, requested_kind=requested_kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                github = FakeGitHub(labels)
                args = SimpleNamespace(verb="start", issue=46, pr=67, head=HEAD,
                                       plan=root / "plan.json", readiness=root / "readiness.json",
                                       kind=requested_kind, new_scope=False)
                output = io.StringIO()
                with patch("p_ases.cli._approved_issue_adc", side_effect=AssertionError("must stop at phase preflight")), \
                        contextlib.redirect_stdout(output):
                    status = _user_review_run(args, "puchinya/ai-agent-workflow", root, github)
                result = json.loads(output.getvalue())
                self.assertEqual(status, 2)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertTrue(any(expected in reason for reason in result["reasons"]))
                self.assertEqual(github.label_writes, 0)
                self.assertFalse((root / ".p_ases").exists())

    def test_user_review_rechecks_all_readiness_gates_before_feedback_or_persistence(self):
        class FakeGitHub:
            def issue(self, _number):
                return {"number": 31, "state": "open", "pull_request": None,
                        "labels": [{"name": "kind:child"}, {"name": "phase:verification"}]}

            def pull_request(self, _number):
                return {"number": 37, "head": {"sha": HEAD}}

        verified_adc = SimpleNamespace(pointer=SimpleNamespace(state="approved", comment_id=5, sha256="f" * 64))
        verification = VerificationResult(
            "PASS", VERIFICATION_SUBJECT, (), "1" * 64, "2" * 64, ("3" * 64,), (),
        ).validate()
        readiness = ReadinessResultV2(
            "READY_WITH_EXCEPTION", VERIFICATION_SUBJECT, "UNAVAILABLE", "d" * 64,
            "e" * 64, 71, "f" * 64, 72, "a" * 64,
            ("INDEPENDENT_REVIEW_NOT_PERFORMED",), (),
            tuple(sorted(("d" * 64, "e" * 64, "f" * 64, "a" * 64,
                          "b" * 64, verification.sha256))),
            "b" * 64,
        ).validate()
        acceptance_saved = SimpleNamespace(subject=VERIFICATION_SUBJECT, sha256="4" * 64)
        acceptance_failed = SimpleNamespace(status="FAIL")
        binding, pr_binding = object(), object()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(verb="start", issue=31, pr=37, head=HEAD,
                                   plan=root / "plan.json", readiness=root / "readiness.json",
                                   kind="child", new_scope=False,
                                   review_unavailable_exception=root / "exception.json")
            output = io.StringIO()
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("p_ases.cli._approved_issue_adc", return_value=({}, verified_adc)))
                stack.enter_context(patch("p_ases.cli._load_plan", return_value=(object(), (), (), ())))
                stack.enter_context(patch("p_ases.cli._subject", return_value=VERIFICATION_SUBJECT))
                stack.enter_context(patch("p_ases.cli._readback_current_pr", return_value={"head_sha": HEAD}))
                stack.enter_context(patch("p_ases.cli.read_readiness", return_value=readiness))
                stack.enter_context(patch("p_ases.cli._readback_readiness_pr", return_value=object()))
                stack.enter_context(patch("p_ases.cli.read_binding", return_value=binding))
                stack.enter_context(patch("p_ases.cli.read_pr_binding", return_value=pr_binding))
                stack.enter_context(patch(
                    "p_ases.cli.WorkContext", return_value=SimpleNamespace(validate=lambda: object())))
                stack.enter_context(patch("p_ases.cli.head_sha40", return_value=HEAD))
                stack.enter_context(patch("p_ases.cli.current_branch", return_value="feature/review"))
                stack.enter_context(patch("p_ases.cli.worktree_clean", return_value=True))
                stack.enter_context(patch("p_ases.cli.binding_digest", return_value="5" * 64))
                stack.enter_context(patch("p_ases.cli._calculate_verification", return_value=(verification, [])))
                stack.enter_context(patch("p_ases.cli._exact_published", return_value=9876))
                stack.enter_context(patch("p_ases.cli._readiness_bound_artifact", return_value=acceptance_saved))
                stack.enter_context(patch("p_ases.cli._recompute_acceptance_readonly", return_value=acceptance_failed))
                stack.enter_context(patch(
                    "p_ases.cli._review_payload_from_github",
                    side_effect=AssertionError("feedback read must follow gate")))
                phase_transition = stack.enter_context(patch("p_ases.cli._review_phase_transition"))
                stack.enter_context(contextlib.redirect_stdout(output))
                status = _user_review_run(args, "octo/repo", root, FakeGitHub())
            result = json.loads(output.getvalue())
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("current Acceptance is not PASS", result["reasons"])
            phase_transition.assert_not_called()
            self.assertFalse((root / ".p_ases").exists())

    def test_current_readiness_recomputation_blocks_a_changed_acceptance(self):
        verification = VerificationResult(
            "PASS", VERIFICATION_SUBJECT, (), "1" * 64, "2" * 64, ("3" * 64,), (),
        ).validate()
        acceptance_saved = SimpleNamespace(subject=VERIFICATION_SUBJECT, sha256="4" * 64)
        acceptance_failed = SimpleNamespace(status="FAIL")
        readiness = SimpleNamespace(subject=VERIFICATION_SUBJECT,
                                    evidence_sha256s=(verification.sha256,))
        verified_adc = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=123, sha256="b" * 64),
            contract=SimpleNamespace(requirement_ids=("REQ-F06-001",), section=lambda _name: ""),
        )
        binding, pr_binding = object(), object()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(issue=31, pr=37, head=HEAD, plan=root / "plan.json",
                                   review_unavailable_exception=None)
            with patch("p_ases.cli._approved_issue_adc", return_value=({}, verified_adc)), \
                    patch("p_ases.cli._load_plan", return_value=(object(), (), (), ())), \
                    patch("p_ases.cli._subject", return_value=VERIFICATION_SUBJECT), \
                    patch("p_ases.cli._readback_readiness_pr", return_value=object()), \
                    patch("p_ases.cli.read_binding", return_value=binding), \
                    patch("p_ases.cli.read_pr_binding", return_value=pr_binding), \
                    patch("p_ases.cli.WorkContext", return_value=SimpleNamespace(validate=lambda: object())), \
                    patch("p_ases.cli.head_sha40", return_value=HEAD), \
                    patch("p_ases.cli.current_branch", return_value="feature/review"), \
                    patch("p_ases.cli.worktree_clean", return_value=True), \
                    patch("p_ases.cli.binding_digest", return_value="5" * 64), \
                    patch("p_ases.cli._calculate_verification", return_value=(verification, [])), \
                    patch("p_ases.cli._exact_published", return_value=9876), \
                    patch("p_ases.cli._readiness_bound_artifact", return_value=acceptance_saved), \
                    patch("p_ases.cli._recompute_acceptance_readonly", return_value=acceptance_failed):
                with self.assertRaisesRegex(CLIError, "Acceptance is not PASS"):
                    _recompute_user_review_readiness(args, "octo/repo", root, object(), readiness)

    def test_final_delivery_converts_runtime_git_failure_to_structured_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(issue=46, pr=67, head=HEAD, plan=root / "plan.json",
                                   readiness=root / "readiness.json", verification=root / "verification.json",
                                   acceptance=root / "acceptance.json", self_audit=root / "self-audit.json",
                                   user_review_record=root / "user-review.json")
            output = io.StringIO()
            with patch("p_ases.cli._approved_issue_adc", side_effect=GitError("broken exception evidence")), \
                    contextlib.redirect_stdout(output):
                status = _delivery_final(args, "puchinya/ai-agent-workflow", root, object())
            result = json.loads(output.getvalue())
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("broken exception evidence", result["reasons"])

    def test_snapshot_hash_name_is_required_and_tampered_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = FeedbackSnapshot(USER_SUBJECT, (), (), "2026-10-12T00:00:00Z").validate()
            path = feedback_snapshot_path(root, snapshot)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot.to_bytes())
            self.assertEqual(_latest_review_snapshot(root, USER_SUBJECT), snapshot)
            path.write_bytes(snapshot.to_bytes().replace(b"2026-10-12T00:00:00Z", b"2026-10-12T00:00:01Z"))
            with self.assertRaisesRegex(UserReviewError, "digest or canonical bytes"):
                _latest_review_snapshot(root, USER_SUBJECT)

    def test_suspicious_json_filename_is_rejected_without_reading_as_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / ".p_ases" / "user-review" / "31" / USER_SUBJECT.sha256
            folder.mkdir(parents=True)
            (folder / "not-a-snapshot.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(UserReviewError, "unexpected file"):
                _latest_review_snapshot(root, USER_SUBJECT)


if __name__ == "__main__":
    unittest.main()
