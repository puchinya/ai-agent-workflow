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
from p_ases.user_review import FeedbackSnapshot, UserReviewError, UserReviewSubject, feedback_snapshot_path
from p_ases.cli import _latest_review_snapshot, _user_review_run


HEAD = "a" * 40
VERIFICATION_SUBJECT = VerificationSubject(
    "octo/repo", 31, 37, 123, "b" * 64, "c" * 64, HEAD).validate()
READINESS = ReadinessResult("PASS", VERIFICATION_SUBJECT, (), ("d" * 64,), "e" * 64).validate()
USER_SUBJECT = UserReviewSubject(VERIFICATION_SUBJECT, READINESS.sha256).validate()


class UserReviewCliRegressionTests(unittest.TestCase):
    def test_start_sync_status_reaches_pending_with_session_in_snapshot_directory(self):
        class FakeGitHub:
            def issue(self, _number):
                return {"number": 31, "state": "open", "pull_request": None}

            def pull_request(self, _number):
                return {"number": 37, "head": {"sha": HEAD}}

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

        verified_adc = SimpleNamespace(pointer=SimpleNamespace(state="approved", comment_id=5, sha256="f" * 64))

        def feedback(_github, subject, *, observed_at):
            return FeedbackSnapshot(subject, (), (), observed_at).validate()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for verb in ("start", "sync", "status"):
                args = SimpleNamespace(verb=verb, issue=31, pr=37, head=HEAD,
                                       plan=root / "plan.json", readiness=root / "readiness.json",
                                       kind="child", new_scope=False)
                output = io.StringIO()
                with patch("p_ases.cli._approved_issue_adc", return_value=({}, verified_adc)), \
                        patch("p_ases.cli.verify_adc", return_value=verified_adc), \
                        patch("p_ases.cli._load_plan", return_value=(object(), (), (), ())), \
                        patch("p_ases.cli._subject", return_value=VERIFICATION_SUBJECT), \
                        patch("p_ases.cli._readback_current_pr", return_value={"head_sha": HEAD}), \
                        patch("p_ases.cli.load_profile", return_value=SimpleNamespace(
                            final_delivery_review_mode="external_reviewer")), \
                        patch("p_ases.cli.read_readiness", return_value=READINESS), \
                        patch("p_ases.cli._review_payload_from_github", side_effect=feedback), \
                        patch("p_ases.cli._review_phase_transition"), \
                        contextlib.redirect_stdout(output):
                    status = _user_review_run(args, "octo/repo", root, FakeGitHub())
                result = json.loads(output.getvalue())
                self.assertEqual(result["status"], "PENDING")
                self.assertEqual(status, 2)
                self.assertTrue((root / ".p_ases" / "user-review" / "31" / USER_SUBJECT.sha256
                                 / "session.json").is_file())

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
