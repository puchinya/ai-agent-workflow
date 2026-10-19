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

from p_ases.delivery import ReadinessResult
from p_ases.evidence_store import VerificationSubject
from p_ases.github import GitHubError
from p_ases.phases import Attention, IssueKind, Phase
from p_ases.user_review import (
    FeedbackSnapshot, UserReviewError, UserReviewResult, UserReviewSession, UserReviewSubject,
    feedback_snapshot_path, review_session_path, write_review_session,
)
from p_ases.cli import (
    _latest_review_snapshot, _parser, _readiness_phase_blocker, _review_phase_transition, _user_review_run,
)


HEAD = "a" * 40
VERIFICATION_SUBJECT = VerificationSubject(
    "octo/repo", 31, 37, 123, "b" * 64, "c" * 64, HEAD).validate()
READINESS = ReadinessResult("PASS", VERIFICATION_SUBJECT, (), ("d" * 64,), "e" * 64).validate()
USER_SUBJECT = UserReviewSubject(VERIFICATION_SUBJECT, READINESS.sha256).validate()


class UserReviewCliRegressionTests(unittest.TestCase):
    class FakeGitHub:
        def __init__(self, phase="verification", attention=None, kind_labels=None):
            self.phase = phase
            self.attention = attention
            self.kind_labels = list(kind_labels if kind_labels is not None else ["kind:child"])
            self.label_writes = []
            self.lose_next_label_response = False
            self.issue_reads = 0
            self.add_attention_on_issue_read = None

        def issue(self, _number):
            self.issue_reads += 1
            if self.issue_reads == self.add_attention_on_issue_read:
                self.attention = "blocked"
            labels = ([{"name": name} for name in self.kind_labels]
                      + [{"name": f"phase:{self.phase}"}])
            if self.attention is not None:
                labels.append({"name": f"attention:{self.attention}"})
            return {"number": 31, "state": "open", "pull_request": None, "labels": labels}

        def replace_issue_labels(self, _number, labels):
            self.label_writes.append(list(labels))
            self.phase = next(label.removeprefix("phase:") for label in labels
                              if label.startswith("phase:"))
            attention_labels = [label.removeprefix("attention:") for label in labels
                                if label.startswith("attention:")]
            self.attention = attention_labels[0] if attention_labels else None
            if self.lose_next_label_response:
                self.lose_next_label_response = False
                raise GitHubError("simulated lost label PUT response")

        def pull_request(self, _number):
            return {"number": 37, "head": {"sha": HEAD}}

        def authenticated_user(self):
            return {"id": 42, "login": "octocat", "type": "User"}

    @staticmethod
    def _run_review(root, github, verb, *, readiness=READINESS, current_adc=None,
                    final_adc=None, requested_head=HEAD, requested_kind=None):
        verified_adc = current_adc or SimpleNamespace(
            pointer=SimpleNamespace(state="approved", comment_id=5, sha256="f" * 64),
        )

        def feedback(_github, subject, *, observed_at):
            return FeedbackSnapshot(subject, (), (), observed_at).validate()

        argv = ["user-review", verb, "31", "37", requested_head,
                str(root / "plan.json"), str(root / "readiness.json"),
                "--repo", "octo/repo", "--root", str(root)]
        if requested_kind is not None:
            argv.extend(["--kind", requested_kind])
        args = _parser().parse_args(argv)
        output = io.StringIO()
        with patch("p_ases.cli._approved_issue_adc", side_effect=lambda gh, _n, _r: (gh.issue(31), verified_adc)), \
                patch("p_ases.cli.verify_adc", return_value=final_adc or verified_adc), \
                patch("p_ases.cli._load_plan", return_value=(object(), (), (), ())), \
                patch("p_ases.cli._subject", return_value=VERIFICATION_SUBJECT), \
                patch("p_ases.cli._readback_current_pr", return_value={"head_sha": HEAD}), \
                patch("p_ases.cli.load_profile", return_value=SimpleNamespace(
                    final_delivery_review_mode="external_reviewer")), \
                patch("p_ases.cli.read_readiness", return_value=readiness), \
                patch("p_ases.cli._review_payload_from_github", side_effect=feedback), \
                patch("p_ases.cli._review_phase_transition", wraps=_review_phase_transition) as transition, \
                contextlib.redirect_stdout(output):
            status = _user_review_run(args, "octo/repo", root, github)
        return status, json.loads(output.getvalue()), transition

    def test_user_review_parser_leaves_kind_unset_unless_explicitly_requested(self):
        for verb in ("start", "sync", "status"):
            with self.subTest(verb=verb):
                args = _parser().parse_args([
                    "user-review", verb, "31", "37", HEAD, "plan.json", "readiness.json",
                ])
                self.assertIsNone(args.kind)
                explicit = _parser().parse_args([
                    "user-review", verb, "31", "37", HEAD, "plan.json", "readiness.json",
                    "--kind", "single",
                ])
                self.assertEqual(explicit.kind, "single")

    def test_single_issue_omitted_kind_starts_and_syncs_from_issue_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = self.FakeGitHub(phase="verification", kind_labels=["kind:single"])
            status, result, transition = self._run_review(root, github, "start")
            self.assertEqual((status, result["status"]), (2, "PENDING"))
            self.assertTrue(review_session_path(root, USER_SUBJECT).is_file())
            self.assertEqual(github.phase, "user-review")
            self.assertEqual(github.kind_labels, ["kind:single"])
            self.assertEqual(github.label_writes, [["kind:single", "phase:user-review"]])
            transition.assert_called_once()

            status, result, transition = self._run_review(root, github, "sync")
            self.assertEqual((status, result["status"]), (2, "PENDING"))
            self.assertEqual(github.phase, "user-review")
            self.assertEqual(len(github.label_writes), 1)
            transition.assert_called_once()

    def test_child_issue_omitted_kind_remains_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = self.FakeGitHub(phase="verification", kind_labels=["kind:child"])
            status, result, _transition = self._run_review(root, github, "start")
            self.assertEqual((status, result["status"]), (2, "PENDING"))
            self.assertEqual(github.kind_labels, ["kind:child"])
            self.assertEqual(github.label_writes, [["kind:child", "phase:user-review"]])

    def test_explicit_kind_mismatch_blocks_before_session_snapshot_result_or_label_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = self.FakeGitHub(phase="verification", kind_labels=["kind:single"])
            status, result, transition = self._run_review(
                root, github, "start", requested_kind="child",
            )
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("--kind differs", " ".join(result["reasons"]))
            self.assertEqual(list(root.rglob("*")), [])
            self.assertEqual(github.label_writes, [])
            transition.assert_not_called()

    def test_malformed_or_duplicate_kind_labels_block_before_any_write(self):
        cases = (
            ("malformed", ["kind:singel"]),
            ("duplicate", ["kind:single", "kind:child"]),
        )
        for name, kind_labels in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                github = self.FakeGitHub(phase="verification", kind_labels=kind_labels)
                status, result, transition = self._run_review(root, github, "start")
                self.assertEqual(status, 2)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertFalse(review_session_path(root, USER_SUBJECT).exists())
                self.assertEqual(list(root.rglob("*")), [])
                self.assertEqual(github.label_writes, [])
                transition.assert_not_called()

    def test_start_sync_status_reaches_pending_and_preserves_session_across_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = self.FakeGitHub(phase="verification")
            saved_bytes = None
            for verb in ("start", "sync", "status"):
                status, result, transition = self._run_review(root, github, verb)
                self.assertEqual(result["status"], "PENDING")
                self.assertEqual(status, 2)
                session_path = review_session_path(root, USER_SUBJECT)
                self.assertTrue(session_path.is_file())
                if saved_bytes is None:
                    saved_bytes = session_path.read_bytes()
                self.assertEqual(session_path.read_bytes(), saved_bytes)
                self.assertEqual(transition.call_count, 0 if verb == "status" else 1)
            self.assertEqual(github.phase, "user-review")
            self.assertEqual(len(github.label_writes), 1)
            self.assertIsNone(result["selected_approval_event"])

    def test_phase_user_review_resumes_only_existing_exact_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_path = review_session_path(root, USER_SUBJECT)
            write_review_session(session_path, UserReviewSession(USER_SUBJECT, "2026-10-12T00:00:00Z"))
            original = session_path.read_bytes()
            status, result, transition = self._run_review(root, self.FakeGitHub(phase="user-review"), "start")
            self.assertEqual(result["status"], "PENDING")
            self.assertEqual(status, 2)
            self.assertEqual(session_path.read_bytes(), original)
            transition.assert_called_once()

    def test_phase_user_review_without_session_blocks_before_snapshot_or_session_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status, result, transition = self._run_review(root, self.FakeGitHub(phase="user-review"), "start")
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(review_session_path(root, USER_SUBJECT).exists())
            self.assertFalse(feedback_snapshot_path(root, FeedbackSnapshot(
                USER_SUBJECT, (), (), "2026-10-12T00:00:00Z").validate()).parent.exists())
            transition.assert_not_called()

    def test_user_review_rejects_phases_before_session_or_snapshot_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status, result, transition = self._run_review(root, self.FakeGitHub(phase="ready"), "start")
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(review_session_path(root, USER_SUBJECT).exists())
            transition.assert_not_called()

    def test_sync_without_session_does_not_create_session_or_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status, result, transition = self._run_review(root, self.FakeGitHub(phase="verification"), "sync")
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(review_session_path(root, USER_SUBJECT).exists())
            self.assertFalse(feedback_snapshot_path(root, FeedbackSnapshot(
                USER_SUBJECT, (), (), "2026-10-12T00:00:00Z").validate()).parent.exists())
            transition.assert_not_called()

    def test_sync_recovers_phase_transition_from_verification_with_same_session(self):
        class MutableIssue:
            phase = "verification"
            writes = 0

            def issue(self, _number):
                return {"number": 31, "state": "open", "pull_request": None,
                        "labels": [{"name": "kind:child"}, {"name": f"phase:{self.phase}"}]}

            def replace_issue_labels(self, _number, labels):
                self.writes += 1
                self.phase = next(label.removeprefix("phase:") for label in labels
                                  if label.startswith("phase:"))

        github = MutableIssue()
        pending = UserReviewResult("PENDING", USER_SUBJECT, "f" * 64, ("awaiting review",),
                                   "user-review").validate()
        _review_phase_transition(github, 31, IssueKind.CHILD, pending, "sync")
        self.assertEqual(github.phase, "user-review")
        self.assertEqual(github.writes, 1)

    def test_readiness_phase_guard_requires_verification_or_exact_user_review_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(_readiness_phase_blocker(
                IssueKind.CHILD, Phase.VERIFICATION, frozenset(), VERIFICATION_SUBJECT, READINESS, root))
            self.assertIn("phase is ready", _readiness_phase_blocker(
                IssueKind.CHILD, Phase.READY, frozenset(), VERIFICATION_SUBJECT, READINESS, root))
            reason = _readiness_phase_blocker(
                IssueKind.CHILD, Phase.USER_REVIEW, frozenset(), VERIFICATION_SUBJECT, READINESS, root)
            self.assertIn("immutable session", reason)
            review_subject = UserReviewSubject(VERIFICATION_SUBJECT, READINESS.sha256).validate()
            write_review_session(review_session_path(root, review_subject),
                                 UserReviewSession(review_subject, "2026-10-12T00:00:00Z"))
            self.assertIsNone(_readiness_phase_blocker(
                IssueKind.CHILD, Phase.USER_REVIEW, frozenset(), VERIFICATION_SUBJECT, READINESS, root))

    def test_attention_blocks_readiness_and_user_review_before_any_session_or_label_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for attention in (Attention.BLOCKED, Attention.WAITING_USER, Attention.WAITING_DEPENDENCY):
                with self.subTest(attention=attention.value):
                    github = self.FakeGitHub(phase="verification", attention=attention.value)
                    reason = _readiness_phase_blocker(
                        IssueKind.CHILD, Phase.VERIFICATION, frozenset({attention}),
                        VERIFICATION_SUBJECT, READINESS, root,
                    )
                    self.assertIn("attention:*", reason)
                    status, result, transition = self._run_review(root, github, "start")
                    self.assertEqual(status, 2)
                    self.assertEqual(result["status"], "BLOCKED")
                    self.assertIn("attention:*", " ".join(result["reasons"]))
                    self.assertFalse(review_session_path(root, USER_SUBJECT).exists())
                    snapshot_dir = feedback_snapshot_path(
                        root, FeedbackSnapshot(USER_SUBJECT, (), (), "2026-10-12T00:00:00Z").validate(),
                    ).parent
                    self.assertFalse(snapshot_dir.exists())
                    self.assertEqual(github.label_writes, [])
                    transition.assert_not_called()

    def test_attention_added_during_review_blocks_snapshot_result_and_phase_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = self.FakeGitHub(phase="verification")
            # _approved_issue_adc, pre-session check, and post-evaluation check run first.
            # The final pre-persistence read then observes a newly added attention label.
            github.add_attention_on_issue_read = 4
            status, result, transition = self._run_review(root, github, "start")
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("attention", " ".join(result["reasons"]))
            session_path = review_session_path(root, USER_SUBJECT)
            self.assertTrue(session_path.is_file())
            self.assertEqual(sorted(path.name for path in session_path.parent.iterdir()), ["session.json"])
            self.assertEqual(github.phase, "verification")
            self.assertEqual(github.attention, "blocked")
            self.assertEqual(github.label_writes, [])
            transition.assert_not_called()

    def test_lost_phase_put_response_is_recovered_by_exact_readback_and_retry_does_not_put_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            github = self.FakeGitHub(phase="verification")
            github.lose_next_label_response = True
            status, result, _transition = self._run_review(root, github, "start")
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "PENDING")
            self.assertEqual(github.phase, "user-review")
            self.assertEqual(len(github.label_writes), 1)
            session_path = review_session_path(root, USER_SUBJECT)
            self.assertTrue(session_path.is_file())
            started_at = json.loads(session_path.read_text(encoding="utf-8"))["started_at"]

            status, result, _transition = self._run_review(root, github, "sync")
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "PENDING")
            self.assertEqual(len(github.label_writes), 1)
            self.assertEqual(json.loads(session_path.read_text(encoding="utf-8"))["started_at"], started_at)

    def test_stale_head_readiness_or_adc_does_not_reuse_existing_review_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_path = review_session_path(root, USER_SUBJECT)
            write_review_session(session_path, UserReviewSession(USER_SUBJECT, "2026-10-12T00:00:00Z"))
            original = session_path.read_bytes()

            github = self.FakeGitHub(phase="verification")
            status, result, _transition = self._run_review(root, github, "start", requested_head="f" * 40)
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(session_path.read_bytes(), original)
            self.assertEqual(github.label_writes, [])

            changed_subject = VerificationSubject(
                "octo/repo", 31, 37, 123, "b" * 64, "c" * 64, "f" * 40,
            ).validate()
            stale_readiness = ReadinessResult(
                "PASS", changed_subject, (), ("d" * 64,), "e" * 64,
            ).validate()
            status, result, _transition = self._run_review(
                root, github, "start", readiness=stale_readiness,
            )
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(session_path.read_bytes(), original)
            self.assertEqual(github.label_writes, [])

            changed_adc = SimpleNamespace(
                pointer=SimpleNamespace(state="approved", comment_id=6, sha256="1" * 64),
            )
            status, result, _transition = self._run_review(
                root, github, "start", final_adc=changed_adc,
            )
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(session_path.read_bytes(), original)
            self.assertEqual(sorted(path.name for path in session_path.parent.iterdir()), ["session.json"])
            self.assertEqual(github.label_writes, [])

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
