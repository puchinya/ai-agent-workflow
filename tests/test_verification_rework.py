"""Issue #79: deterministic regression tests for bounded verification rework."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHubError
from p_ases.evidence_store import VerificationSubject
from p_ases.verification import VerificationResult
from p_ases.verification_rework import (
    APPLIED_SCHEMA, INTENT_SCHEMA, VerificationReworkError, MAX_CYCLES,
    _current_plan, _evidence, _require_review_not_started, read_rework_history,
    require_rework_progress, verification_rework,
)

REPO = "puchinya/ai-agent-workflow"
HEAD = "a" * 40
ADC_SHA = "b" * 64
BIND_SHA = "c" * 64


class FakeGitHub:
    repo = REPO

    def __init__(self, *, lost_put=None):
        self.labels = ["kind:single", "phase:verification"]
        self.comments = []
        self.comment_posts = 0
        self.label_puts = 0
        self.lost_put = lost_put
        self.head = HEAD
        self.actor_id = 3744776
        self.author_association = "OWNER"

    def repository_metadata(self):
        return {"full_name": REPO, "id": 1401910271,
                "owner": {"id": 3744776, "login": "puchinya", "type": "User"}}

    def authenticated_user(self):
        return {"id": self.actor_id, "login": "actor", "type": "User"}

    def issue(self, number):
        return {
            "id": 7900, "number": number, "state": "open",
            "pull_request": None, "body": "Issue 79",
            "repository_url": f"https://api.github.com/repos/{REPO}",
            "labels": [{"name": name} for name in self.labels],
        }

    def pull_request(self, number):
        return {
            "number": number, "state": "open", "draft": False, "merged": False,
            "head": {"ref": "fix/issue79", "sha": self.head,
                     "repo": {"full_name": REPO}},
            "base": {"ref": "main", "sha": "d" * 40,
                     "repo": {"full_name": REPO}},
            "body": "Closes #79",
        }

    def issue_comments(self, number):
        return list(self.comments)

    def issue_comment(self, number, comment_id):
        return next(item for item in self.comments if item["id"] == comment_id)

    def create_issue_comment(self, number, body):
        self.comment_posts += 1
        cid = 7000 + len(self.comments)
        row = {
            "id": cid, "body": body, "created_at": "2026-11-23T12:01:01Z",
            "updated_at": "2026-11-23T12:01:01Z",
            "user": {"id": self.actor_id, "login": "puchinya", "type": "User"},
            "author_association": self.author_association,
            "url": f"https://api.github.com/repos/{REPO}/issues/comments/{cid}",
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/79",
            "html_url": f"https://github.com/{REPO}/issues/79#issuecomment-{cid}",
        }
        self.comments.append(row)
        return row

    def replace_issue_labels(self, number, labels):
        self.label_puts += 1
        if self.lost_put == "before":
            raise GitHubError("lost before apply")
        self.labels = sorted(labels)
        if self.lost_put == "after":
            raise GitHubError("lost after apply")
        return [{"name": label} for label in labels]


class VerificationReworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.github = FakeGitHub()

    def subject(self):
        verified = SimpleNamespace(pointer=SimpleNamespace(comment_id=7099602476),
                                   contract=SimpleNamespace(sha256=ADC_SHA))
        binding = SimpleNamespace(base_ref="main")
        return SimpleNamespace(
            repository=REPO, repository_id=1401910271, issue_number=79, issue_id=7900,
            labels=tuple(sorted(self.github.labels)), verified_adc=verified,
            binding=binding, binding_sha256=BIND_SHA, binding_generation=1,
            head_sha40=self.github.head, branch_ref="fix/issue79", executor_user_id=self.github.actor_id,
            issue=self.github.issue(79),
        )

    def run_rework(self):
        with patch("p_ases.verification_rework._live_subject", side_effect=lambda *_a, **_k: self.subject()), \
                patch("p_ases.verification_rework._require_review_not_started"), \
                patch("p_ases.verification_rework._phase_generation", return_value=(6000, "f" * 64)), \
                patch("p_ases.verification_rework._current_plan", return_value="1" * 64), \
                patch("p_ases.verification_rework._evidence",
                      return_value=("independent_review_A", "e" * 64)):
            return verification_rework(
                self.github, self.root, 79, 80,
                self.root / "review.json", "F-01", "Correct a confirmed ADC violation",
                self.root / "plan.json",
            )

    def test_one_intent_one_label_update_one_applied_then_noop(self):
        applied = self.run_rework()
        self.assertEqual(applied["status"], "APPLIED")
        self.assertEqual(applied["rework_cycle"], 1)
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (2, 1))
        self.assertEqual(self.github.labels, ["kind:single", "phase:execution"])
        records = read_rework_history(self.github, 79)
        self.assertEqual([item.schema for item in records], [INTENT_SCHEMA, APPLIED_SCHEMA])
        self.assertEqual(self.run_rework()["status"], "NOOP")
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (2, 1))

    def test_lost_put_after_apply_is_recovered_with_zero_second_put(self):
        self.github.lost_put = "after"
        result = self.run_rework()
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (2, 1))
        self.assertEqual(self.run_rework()["status"], "NOOP")

    def test_lost_put_before_apply_blocks_but_never_retries(self):
        self.github.lost_put = "before"
        with self.assertRaisesRegex(VerificationReworkError, "ambiguous PUT"):
            self.run_rework()
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (1, 1))
        self.github.lost_put = None
        with self.assertRaisesRegex(VerificationReworkError, "no blind retry"):
            self.run_rework()
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (1, 1))

    def test_recovery_after_successful_put_without_applied(self):
        self.github.lost_put = "before"
        with self.assertRaises(VerificationReworkError):
            self.run_rework()
        self.github.labels = ["kind:single", "phase:execution"]
        self.github.lost_put = None
        recovered = self.run_rework()
        self.assertEqual(recovered["status"], "RECOVERED")
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (2, 1))

    def test_malformed_or_edited_journal_blocks(self):
        self.run_rework()
        self.github.comments[0]["updated_at"] = "2026-11-23T12:02:01Z"
        with self.assertRaisesRegex(VerificationReworkError, "edited"):
            read_rework_history(self.github, 79)

    def test_user_review_session_blocks_before_any_write(self):
        with patch("p_ases.verification_rework._live_subject", side_effect=lambda *_a, **_k: self.subject()), \
                patch("p_ases.verification_rework._require_review_not_started",
                      side_effect=VerificationReworkError("User Review started")), \
                patch("p_ases.verification_rework._current_plan", return_value="1" * 64), \
                patch("p_ases.verification_rework._evidence",
                      return_value=("independent_review_A", "e" * 64)):
            with self.assertRaisesRegex(VerificationReworkError, "User Review started"):
                verification_rework(
                    self.github, self.root, 79, 80,
                    self.root / "review.json", "F-01", "Fix an ADC violation",
                    self.root / "plan.json",
                )
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (0, 0))

    def test_no_progress_rejects_same_head_after_applied(self):
        self.run_rework()
        with self.assertRaisesRegex(VerificationReworkError, "NO_PROGRESS"):
            require_rework_progress(
                self.github, self.root, 79,
                current_head=HEAD, adc_comment_id=7099602476,
            )

    def test_new_descendant_head_clears_no_progress_gate(self):
        self.run_rework()
        with patch("p_ases.verification_rework.is_ancestor", return_value=True):
            require_rework_progress(
                self.github, self.root, 79,
                current_head="f" * 40, adc_comment_id=7099602476,
            )

    def test_three_corrections_per_adc_generation_are_bounded(self):
        for cycle in range(MAX_CYCLES):
            self.github.labels = ["kind:single", "phase:verification"]
            self.github.head = f"{cycle + 1:040x}"
            result = self.run_rework()
            self.assertEqual(result["rework_cycle"], cycle + 1)
        self.assertEqual((self.github.label_puts, self.github.comment_posts), (MAX_CYCLES, 2 * MAX_CYCLES))
        self.github.labels = ["kind:single", "phase:verification"]
        self.github.head = "e" * 40
        with self.assertRaisesRegex(VerificationReworkError, "BLOCKED_REWORK_LIMIT"):
            self.run_rework()
        self.assertEqual((self.github.label_puts, self.github.comment_posts), (MAX_CYCLES, 2 * MAX_CYCLES))

    def test_live_pr_head_change_prevents_any_rework_write(self):
        def changed_pr(number):
            pr = FakeGitHub.pull_request(self.github, number)
            pr["head"]["sha"] = "d" * 40
            return pr
        self.github.pull_request = changed_pr
        with self.assertRaisesRegex(VerificationReworkError, "stale or mismatched"):
            self.run_rework()
        self.assertEqual((self.github.label_puts, self.github.comment_posts), (0, 0))


    def test_pending_intent_blocks_execution_to_verification_without_progress(self):
        self.github.lost_put = "before"
        with self.assertRaises(VerificationReworkError):
            self.run_rework()
        self.github.labels = ["kind:single", "phase:execution"]
        with self.assertRaisesRegex(VerificationReworkError, "BLOCKED_REWORK_PENDING"):
            require_rework_progress(
                self.github, self.root, 79,
                current_head="f" * 40, adc_comment_id=7099602476,
            )
        self.assertEqual(self.github.comment_posts, 1)
        self.assertEqual(self.github.label_puts, 1)

    def test_untrusted_marker_comments_do_not_poison_rework_history(self):
        suspicious = self.github.create_issue_comment(
            79, "<!-- PASES_VERIFICATION_REWORK_UNKNOWN\\nmalformed\\n-->",
        )
        suspicious["user"] = {"id": 999999, "login": "outsider", "type": "User"}
        self.assertEqual(read_rework_history(self.github, 79), ())
        self.assertEqual(self.run_rework()["status"], "APPLIED")
        self.assertEqual(len(read_rework_history(self.github, 79)), 2)
        # Even an exact canonical carrier from an outsider is not authoritative.
        copied = self.github.create_issue_comment(79, self.github.comments[-1]["body"])
        copied["user"] = {"id": 999999, "login": "outsider", "type": "User"}
        self.assertEqual(len(read_rework_history(self.github, 79)), 2)

    def test_failing_evidence_must_match_repository_adc_comment_and_plan(self):
        expected = {
            "repository": REPO,
            "issue_number": 79,
            "pr_number": 80,
            "adc_comment_id": 7099602476,
            "adc_sha256": ADC_SHA,
            "plan_sha256": "1" * 64,
            "pr_head_sha40": HEAD,
        }
        file = self.root / "verification-result.json"
        for wrong_field, wrong_value in (
                (None, None),
                ("repository", "attacker/other"),
                ("plan_sha256", "2" * 64),
                ("adc_comment_id", 999)):
            subject = VerificationSubject(**{
                **expected, **({wrong_field: wrong_value} if wrong_field else {})
            }).validate()
            result = VerificationResult(
                "FAIL", subject, (), None, None, (), ("Mandatory check failed",)
            ).validate()
            file.write_bytes(result.to_bytes())
            options = {
                "root": self.root, "repository": REPO, "issue": 79, "pr": 80,
                "head": HEAD, "adc_comment_id": 7099602476, "adc_sha256": ADC_SHA,
                "plan_sha256": "1" * 64, "finding_id": "mandatory-check",
            }
            options.update({"github": self.github, "plan_path": self.root / "plan.json"})
            if wrong_field is None:
                with patch("p_ases.cli._calculate_verification", return_value=(result, [])):
                    self.assertEqual(_evidence(file, **options)[0], "verification_FAIL")
            else:
                with self.subTest(wrong_field=wrong_field):
                    with patch("p_ases.cli._calculate_verification", return_value=(result, [])):
                        with self.assertRaisesRegex(VerificationReworkError, "current ADC/PR/HEAD"):
                            _evidence(file, **options)

    def test_live_mandatory_fail_proof_rejects_fabricated_receipt(self):
        subject = VerificationSubject(
            REPO, 79, 80, 7099602476, ADC_SHA, "1" * 64, HEAD,
        ).validate()
        fabricated = VerificationResult(
            "FAIL", subject, (), None, None, (), ("Mandatory check failed",)
        ).validate()
        file = self.root / "synthetic.json"
        file.write_bytes(fabricated.to_bytes())
        options = {
            "root": self.root, "repository": REPO, "issue": 79, "pr": 80,
            "head": HEAD, "adc_comment_id": 7099602476, "adc_sha256": ADC_SHA,
            "plan_sha256": "1" * 64, "finding_id": "mandatory-check",
            "github": self.github, "plan_path": self.root / "plan.json",
        }
        with patch("p_ases.cli._calculate_verification", side_effect=ValueError("no trusted check provenance")):
            with self.assertRaisesRegex(VerificationReworkError, "cannot be independently reproduced"):
                _evidence(file, **options)
        with patch("p_ases.cli._calculate_verification", return_value=(
                VerificationResult("PASS", subject, (), "2" * 64, "3" * 64,
                                   ("4" * 64,), ()).validate(), []
        )):
            with self.assertRaisesRegex(VerificationReworkError, "not the live mandatory"):
                _evidence(file, **options)
        self.assertEqual(self.github.label_puts, 0)

    def test_full_plan_loader_and_canonical_path_are_mandatory(self):
        plan = SimpleNamespace(sha256="1" * 64, repository=REPO, issue_number=79)
        canonical = self.root / ".p_ases" / "plans" / "79" / f"{plan.sha256}.json"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"canonical stub")
        (self.root / "other.json").write_bytes(b"fake Plan")
        with (patch("p_ases.verification_rework.read_plan", return_value=plan),
              patch("p_ases.cli._load_plan", return_value=(plan, ("REQ-1",), (), ())) as full):
            self.assertEqual(_current_plan(self.root, canonical, self.subject()), "1" * 64)
            self.assertEqual(full.call_count, 1)
            with self.assertRaisesRegex(VerificationReworkError, "not the canonical"):
                _current_plan(self.root, self.root / "other.json", self.subject())
        # Valid self-hashed Plan bytes alone are insufficient: the existing
        # normative requirement / Oracle / Test evaluator must also accept it.
        with (patch("p_ases.verification_rework.read_plan", return_value=plan),
              patch("p_ases.cli._load_plan", side_effect=ValueError("missing Oracle"))):
            with self.assertRaisesRegex(ValueError, "missing Oracle"):
                _current_plan(self.root, canonical, self.subject())

    def test_trusted_journal_survives_executor_handoff(self):
        self.github.actor_id = 10
        self.github.author_association = "COLLABORATOR"
        self.run_rework()
        self.github.actor_id = 11
        self.github.author_association = "COLLABORATOR"
        self.assertEqual(len(read_rework_history(self.github, 79)), 2)
        with self.assertRaisesRegex(VerificationReworkError, "NO_PROGRESS"):
            require_rework_progress(self.github, self.root, 79,
                                    current_head=HEAD, adc_comment_id=7099602476)
        self.github.labels = ["kind:single", "phase:verification"]
        self.github.head = "d" * 40
        self.assertEqual(self.run_rework()["rework_cycle"], 2)
        self.assertEqual([row.actor_id for row in read_rework_history(self.github, 79)],
                         [10, 10, 11, 11])

    def test_new_collaborator_recovers_prior_executor_intent_without_second_put(self):
        self.github.actor_id = 10
        self.github.author_association = "COLLABORATOR"
        self.github.lost_put = "before"
        with self.assertRaises(VerificationReworkError):
            self.run_rework()
        self.github.labels = ["kind:single", "phase:execution"]
        self.github.actor_id = 11
        self.github.lost_put = None
        self.assertEqual(self.run_rework()["status"], "RECOVERED")
        self.assertEqual(self.github.label_puts, 1)
        self.assertEqual([row.actor_id for row in read_rework_history(self.github, 79)], [10, 11])

    def test_outsider_fake_user_review_decision_cannot_block_rework(self):
        row = self.github.create_issue_comment(
            79, '{"schema":"PASES_USER_REVIEW_DECISION_FAKE"}',
        )
        row["user"] = {"id": 9999, "type": "User", "login": "outsider"}
        row["author_association"] = "NONE"
        _require_review_not_started(self.github, self.root, 79, 80, ADC_SHA,
                                    self.github.issue_comments(79))
        self.assertEqual(self.run_rework()["status"], "APPLIED")

    def test_wrong_phase_blocks_without_writes(self):
        self.github.labels = ["kind:single", "phase:ready"]
        with self.assertRaisesRegex(VerificationReworkError, "phase:verification"):
            self.run_rework()
        self.assertEqual((self.github.comment_posts, self.github.label_puts), (0, 0))


if __name__ == "__main__":
    unittest.main()
