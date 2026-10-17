from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.owner_authorization import (
    OwnerAuthorizationError, authorize_chat_confirmed_plan, authorize_plan,
    capture_direct_chat_confirmation, create_authorization_plan, resume_authorization,
    read_authorization_plan, write_authorization_plan,
)
from p_ases.github import GitHubError
from p_ases.cli import _create_merge_attempt, _perform_authorized_merge, _publish_owner_approved_adc
from p_ases.consumer_activation import verify_setup_pr_ready_to_merge


REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
OWNER_ID = 3744776
SUBJECT_SHA = "a" * 64
PLAN_HEAD = "b" * 40


class TTY:
    def isatty(self):
        return True


class FakeGitHub:
    repo = REPOSITORY

    def __init__(self, *, actor_id: int = OWNER_ID):
        self.actor_id = actor_id
        self.comments: dict[int, list[dict[str, object]]] = {63: [], 57: []}
        self.writes: list[tuple[int, str]] = []
        self.prs: dict[int, dict[str, object]] = {}

    def repository_metadata(self):
        return {"id": REPOSITORY_ID, "full_name": REPOSITORY,
                "owner": {"id": OWNER_ID, "login": "puchinya", "type": "User"}}

    def issue(self, number: int):
        return {"number": number, "state": "open", "pull_request": None,
                "repository_url": f"https://api.github.com/repos/{REPOSITORY}"}

    def authenticated_user(self):
        return {"id": self.actor_id, "login": "puchinya", "type": "User"}

    def pull_request(self, number: int):
        return self.prs[number]

    def issue_comments(self, number: int):
        return list(self.comments[number])

    def issue_comment(self, number: int, comment_id: int):
        for row in self.comments[number]:
            if row["id"] == comment_id:
                return row
        return None

    def create_issue_comment(self, number: int, body: str):
        comment_id = 100 + len(self.comments[number])
        row = {
            "id": comment_id, "body": body,
            "created_at": "2026-10-17T15:00:00Z", "updated_at": "2026-10-17T15:00:00Z",
            "user": {"id": self.actor_id, "login": "puchinya", "type": "User"},
            "url": f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{number}",
            "html_url": f"https://github.com/{REPOSITORY}/issues/{number}#issuecomment-{comment_id}",
        }
        self.comments[number].append(row)
        self.writes.append((number, body))
        return row


class FakeMergeGitHub:
    def __init__(self, *, lose_response: bool = False):
        self.calls = 0
        self.lose_response = lose_response
        self.pr = {
            "number": 64, "state": "open", "merged": False,
            "head": {"sha": "d" * 40, "repo": {"full_name": REPOSITORY}},
            "base": {"repo": {"full_name": REPOSITORY}}, "body": "Closes #63",
        }

    def pull_request(self, number: int):
        self.assert_number(number)
        return self.pr

    def assert_number(self, number: int):
        if number != 64:
            raise AssertionError("wrong PR number")

    def merge_pull_request(self, number: int, expected_head_sha40: str):
        self.assert_number(number)
        if expected_head_sha40 != "d" * 40:
            raise AssertionError("wrong expected HEAD")
        self.calls += 1
        if self.lose_response:
            raise GitHubError("lost merge response")
        self.pr.update({
            "state": "closed", "merged": True, "merge_commit_sha": "e" * 40,
            "merged_by": {"id": OWNER_ID, "type": "User"},
        })


class OwnerAuthorizationTests(unittest.TestCase):
    def make_plan(self, root: Path, github: FakeGitHub, directory: Path) -> Path:
        with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
            plan = create_authorization_plan(
                github, root, operation="ADC_SUPERSEDE", subject_sha256=SUBJECT_SHA,
                details={"predecessor_comment_id": 41, "predecessor_sha256": "9" * 64,
                         "predecessor_byte_length": 1234, "predecessor_state": "approved"},
            )
        path = directory / "owner-plan.json"
        write_authorization_plan(path, plan)
        self.assertEqual(read_authorization_plan(path), plan)
        return path

    def test_chat_grant_is_exact_and_publishes_only_v3_with_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            github.comments[63].append({
                "id": 99, "body": "Contract prose mentions `PASES_OWNER_DECISION_V1`.",
                "user": {"id": OWNER_ID, "login": "puchinya", "type": "User"},
            })
            details = {"predecessor_comment_id": 41, "predecessor_sha256": "9" * 64,
                       "predecessor_byte_length": 1234, "predecessor_state": "approved"}
            with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
                plan = create_authorization_plan(
                    github, root, operation="ADC_SUPERSEDE", subject_sha256=SUBJECT_SHA,
                    details=details,
                )
                grant = capture_direct_chat_confirmation(
                    plan, response="承認する", user_role="user", same_conversation=True,
                )
                with patch("p_ases.adc.verify_adc", return_value=SimpleNamespace(pointer=SimpleNamespace(
                        state="approved", comment_id=41, sha256="9" * 64, byte_length=1234))):
                    result = authorize_chat_confirmed_plan(github, root, plan, grant)
            self.assertEqual(result["evidence_type"], "PASES_OWNER_DECISION_V3")
            self.assertEqual(result["evidence_channel"], "chat_confirmed_gh_v1")
            self.assertFalse(result["chat_signature"])
            self.assertEqual(len(github.writes), 1)
            body = github.writes[0][1]
            self.assertIn("PASES_OWNER_DECISION_V3", body)
            self.assertIn(plan["approval_scope_sha256"], body)

    def test_resume_reports_v3_scope_and_channel_after_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            path = self.make_plan(root, github, root)
            plan = read_authorization_plan(path)
            grant = capture_direct_chat_confirmation(
                plan, response="承認する", user_role="user", same_conversation=True,
            )
            with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD), \
                    patch("p_ases.adc.verify_adc", return_value=SimpleNamespace(pointer=SimpleNamespace(
                        state="approved", comment_id=41, sha256="9" * 64, byte_length=1234))):
                authorize_chat_confirmed_plan(github, root, plan, grant)
                resumed = resume_authorization(github, path)
            self.assertEqual(resumed["status"], "AUTHORIZED")
            self.assertEqual(resumed["evidence_type"], "PASES_OWNER_DECISION_V3")
            self.assertEqual(resumed["evidence_channel"], "chat_confirmed_gh_v1")
            self.assertEqual(resumed["approval_scope_sha256"], plan["approval_scope_sha256"])

    def test_chat_grant_rejects_vague_response_and_untrusted_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
                plan = create_authorization_plan(
                    github, root, operation="ADC_SUPERSEDE", subject_sha256=SUBJECT_SHA,
                    details={"predecessor_comment_id": 41, "predecessor_sha256": "9" * 64,
                             "predecessor_byte_length": 1234, "predecessor_state": "approved"},
                )
                with self.assertRaisesRegex(OwnerAuthorizationError, "CHAT_CONFIRMATION_REQUIRED"):
                    capture_direct_chat_confirmation(
                        plan, response="続けて", user_role="user", same_conversation=True,
                    )
                with self.assertRaisesRegex(OwnerAuthorizationError, "CHAT_PROVENANCE_UNAVAILABLE"):
                    capture_direct_chat_confirmation(
                        plan, response="承認する", user_role="assistant", same_conversation=True,
                    )
            self.assertEqual(github.writes, [])

    def test_non_tty_cloud_and_shared_token_are_zero_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.make_plan(root, FakeGitHub(), root)
            github = FakeGitHub()
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(OwnerAuthorizationError, "AUTH_TRANSPORT_UNAVAILABLE"):
                    authorize_plan(github, root, path, stdin=object())
                self.assertEqual(github.writes, [])
            with patch.dict(os.environ, {"CODEX_ENVIRONMENT_ID": "cloud-test"}, clear=True):
                with self.assertRaisesRegex(OwnerAuthorizationError, "AUTH_TRANSPORT_UNAVAILABLE"):
                    authorize_plan(github, root, path, stdin=TTY())
                self.assertEqual(github.writes, [])
            with patch.dict(os.environ, {"GH_TOKEN": "shared"}, clear=True):
                with self.assertRaisesRegex(OwnerAuthorizationError, "AUTH_TRANSPORT_UNAVAILABLE"):
                    authorize_plan(github, root, path, stdin=TTY())
                self.assertEqual(github.writes, [])

    def test_activation_setup_merge_plan_targets_issue_without_closing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            head = "c" * 40
            payload = {"activation_issue_number": 57, "schema": "PASES_CONSUMER_ACTIVATION_SETUP_V2"}
            body = "<!-- PASES_CONSUMER_ACTIVATION_SETUP_V2\n" + json.dumps(
                payload, sort_keys=True, separators=(",", ":"),
            ) + "\n-->"
            github.prs[72] = {
                "number": 72, "state": "open", "draft": False, "body": body,
                "head": {"sha": head, "repo": {"full_name": REPOSITORY}},
                "base": {"repo": {"full_name": REPOSITORY}},
            }
            with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
                plan = create_authorization_plan(
                    github, root, operation="PR_MERGE", subject_sha256=SUBJECT_SHA,
                    target_issue_number=57, pr_number=72, pr_head_sha40=head,
                    details={"target_issue_number": 57},
                )
            self.assertEqual(plan["target_issue_number"], 57)

    def test_activation_setup_merge_plan_rejects_unbound_pr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            github.prs[72] = {
                "number": 72, "state": "open", "draft": False, "body": "Closes #57",
                "head": {"sha": "c" * 40, "repo": {"full_name": REPOSITORY}},
                "base": {"repo": {"full_name": REPOSITORY}},
            }
            with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
                with self.assertRaisesRegex(OwnerAuthorizationError, "Activation Setup PR"):
                    create_authorization_plan(
                        github, root, operation="PR_MERGE", subject_sha256=SUBJECT_SHA,
                        target_issue_number=57, pr_number=72, pr_head_sha40="c" * 40,
                        details={"target_issue_number": 57},
                    )

    def test_merge_attempt_is_at_most_once_and_recovers_by_readback(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeMergeGitHub()
            plan = {"plan_sha256": "f" * 64, "source_head_sha40": PLAN_HEAD,
                    "target_issue_number": 63, "pr_number": 64, "pr_head_sha40": "d" * 40}
            decision = {"status": "AUTHORIZED", "operation": "PR_MERGE",
                        "evidence_type": "PASES_OWNER_DECISION_V3",
                        "evidence_channel": "chat_confirmed_gh_v1", "chat_signature": False,
                        "owner_decision_comment_id": 123}
            with patch("p_ases.cli._owner_merge_gate", return_value={"status": "READY"}):
                first = _perform_authorized_merge(object(), root, github, plan, decision)
                second = _perform_authorized_merge(object(), root, github, plan, decision)
            self.assertEqual(first["status"], "MERGED")
            self.assertEqual(second["status"], "MERGED_READBACK")
            self.assertEqual(github.calls, 1)

    def test_adc_local_commit_dispatches_exact_publication_then_phase_rebaseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "successor.md"
            source.write_bytes(b"exact successor bytes\n")
            contract = SimpleNamespace(sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            previous = SimpleNamespace(pointer=SimpleNamespace(
                state="approved", comment_id=12, sha256="b" * 64, byte_length=1200))
            published_pointer = SimpleNamespace(state="approved", comment_id=13,
                                                 sha256=contract.sha256)
            published = SimpleNamespace(pointer=published_pointer,
                                        contract=SimpleNamespace(content=source.read_bytes()))
            verified_decision = SimpleNamespace(
                comment_id=123,
                decision=SimpleNamespace(schema="PASES_OWNER_DECISION_V3",
                                         evidence_channel="chat_confirmed_gh_v1"),
            )
            plan = {"subject_sha256": contract.sha256, "plan_sha256": "a" * 64,
                    "approval_scope_sha256": "d" * 64,
                    "details": {"predecessor_comment_id": 12, "predecessor_sha256": "b" * 64,
                                "predecessor_byte_length": 1200, "predecessor_state": "approved"}}
            decision = {"owner_decision_comment_id": 123}
            args = SimpleNamespace(subject_file=source)
            with patch("p_ases.cli.parse_adc", return_value=contract), \
                    patch("p_ases.cli.read_verified_owner_decision", return_value=verified_decision), \
                    patch("p_ases.cli.verify_adc", side_effect=[previous, published]), \
                    patch("p_ases.cli.publish_adc", return_value=published_pointer) as publish, \
                    patch("p_ases.cli.rebaseline_issue_phase", return_value={"status": "APPLIED"}) as rebaseline:
                result = _publish_owner_approved_adc(args, REPOSITORY, FakeGitHub(), plan, decision)
            self.assertEqual(result["status"], "PUBLISHED")
            self.assertEqual(result["phase_rebaseline"], {"status": "APPLIED"})
            self.assertEqual(publish.call_args.kwargs["state"], "approved")
            self.assertIs(publish.call_args.kwargs["expected_current"], previous.pointer)
            rebaseline.assert_called_once()

    def test_lost_merge_response_never_retries_while_pr_remains_open(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeMergeGitHub(lose_response=True)
            plan = {"plan_sha256": "a" * 64, "source_head_sha40": PLAN_HEAD,
                    "target_issue_number": 63, "pr_number": 64, "pr_head_sha40": "d" * 40}
            decision = {"status": "AUTHORIZED", "operation": "PR_MERGE",
                        "evidence_type": "PASES_OWNER_DECISION_V3",
                        "evidence_channel": "chat_confirmed_gh_v1", "chat_signature": False,
                        "owner_decision_comment_id": 123}
            with patch("p_ases.cli._owner_merge_gate", return_value={"status": "READY"}):
                with self.assertRaisesRegex(OwnerAuthorizationError, "no retry was attempted"):
                    _perform_authorized_merge(object(), root, github, plan, decision)
                with self.assertRaisesRegex(OwnerAuthorizationError, "read-only recovery only"):
                    _perform_authorized_merge(object(), root, github, plan, decision)
            self.assertEqual(github.calls, 1)

    def test_merge_attempt_claim_is_exclusive_for_concurrent_invocations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / ".p_ases" / "owner-authorization" / "merge-attempts" / ("a" * 64 + ".json")
            payload = {"plan_sha256": "a" * 64, "pr_number": 64, "head_sha40": "d" * 40}
            _create_merge_attempt(path, payload, root=root)
            with self.assertRaisesRegex(OwnerAuthorizationError, "another invocation"):
                _create_merge_attempt(path, payload, root=root)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)

    def test_setup_pr_preflight_requires_policy_checks_and_independent_review(self):
        class SetupGitHub:
            repo = REPOSITORY

            def __init__(self):
                now = datetime.now(timezone.utc)
                self.created = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
                self.completed = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
                self.head = "1" * 40
                self.base = "2" * 40
                self.payload = {"activation_issue_number": 57, "schema": "PASES_CONSUMER_ACTIVATION_SETUP_V2",
                                "adc_comment_id": 17, "adc_sha256": "a" * 64, "adc_state": "approved",
                                "activation_profile_sha256": hashlib.sha256(b"profile").hexdigest(),
                                "predecessor_record_id": None,
                                "required_checks": [{"context": "ci", "integration_id": 15368}],
                                "review_mode": "solo_owner", "ruleset_id": 4,
                                "ruleset_applied_record_id": 18, "branch_policy_sha256": "c" * 64,
                                "setup_branch": "pases/consumer-activation-57-v2", "schema": "PASES_CONSUMER_ACTIVATION_SETUP_V2"}
                self.pr = {
                    "number": 72, "state": "open", "merged": False, "draft": False, "mergeable": True,
                    "body": "setup", "user": {"id": OWNER_ID, "type": "User"},
                    "head": {"sha": self.head, "ref": self.payload["setup_branch"],
                             "repo": {"id": REPOSITORY_ID, "full_name": REPOSITORY}},
                    "base": {"sha": self.base, "ref": "main",
                             "repo": {"id": REPOSITORY_ID, "full_name": REPOSITORY}},
                }

            def repository_metadata(self):
                return {"id": REPOSITORY_ID, "full_name": REPOSITORY,
                        "default_branch": "main", "owner": {"id": OWNER_ID, "type": "User"}}

            def pull_request(self, number):
                self.assert_number(number)
                return self.pr

            def assert_number(self, number):
                if number != 72:
                    raise AssertionError("wrong PR number")

            def pull_request_files(self, number):
                self.assert_number(number)
                return [{"filename": ".agent/project.json"}]

            def branch(self, _name):
                return {"commit": {"sha": self.base}}

            def issue(self, number):
                if number != 57:
                    raise AssertionError("wrong Activation Issue")
                return {"number": 57, "state": "open", "pull_request": None,
                        "body": "<!-- PASES_CONSUMER_ACTIVATION_ISSUE_V1 -->",
                        "repository_url": f"https://api.github.com/repos/{REPOSITORY}"}

            def regular_content_at_ref(self, _path, _ref):
                return b"profile"

            def check_runs_for_ref(self, sha):
                return [{"id": 7, "name": "ci", "head_sha": sha,
                         "created_at": self.created, "completed_at": self.completed,
                         "status": "completed", "conclusion": "success", "app": {"id": 15368}}]

            def pull_review_decision(self, number):
                self.assert_number(number)
                return {"state": "OPEN", "headRefOid": self.head, "reviewDecision": "APPROVED"}

            def pull_reviews(self, number):
                self.assert_number(number)
                return [{"id": 19, "state": "APPROVED", "commit_id": self.head,
                         "user": {"id": OWNER_ID + 1, "type": "User"}}]

            def pull_review_threads(self, number):
                self.assert_number(number)
                return []

        github = SetupGitHub()
        verified_adc = SimpleNamespace(pointer=SimpleNamespace(sha256="a" * 64),
                                       contract=SimpleNamespace(content=b"adc"))
        with patch("p_ases.consumer_activation._decode", side_effect=lambda *_a, **_k: github.payload), \
                patch("p_ases.consumer_activation._check_setup_pr", return_value=github.pr), \
                patch("p_ases.consumer_activation.read_consumer_activation_history", return_value=[]), \
                patch("p_ases.consumer_activation.verify_adc_generation", return_value=verified_adc), \
                patch("p_ases.consumer_activation.verify_adc", return_value=verified_adc), \
                patch("p_ases.consumer_activation._validate_profile_bytes",
                      return_value=({"final_delivery": {"review_mode": "solo_owner"}}, (("ci", 15368),))), \
                patch("p_ases.consumer_activation.read_verified_managed_policy", return_value={
                    "ruleset_id": 4, "applied_record_id": 18, "effective_policy_sha256": "c" * 64,
                }):
            result = verify_setup_pr_ready_to_merge(github, 72)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["reviewer_ids"], [OWNER_ID + 1])
        github.pull_reviews = lambda _number: []
        with patch("p_ases.consumer_activation._decode", side_effect=lambda *_a, **_k: github.payload), \
                patch("p_ases.consumer_activation._check_setup_pr", return_value=github.pr), \
                patch("p_ases.consumer_activation.read_consumer_activation_history", return_value=[]), \
                patch("p_ases.consumer_activation.verify_adc_generation", return_value=verified_adc), \
                patch("p_ases.consumer_activation.verify_adc", return_value=verified_adc), \
                patch("p_ases.consumer_activation._validate_profile_bytes",
                      return_value=({"final_delivery": {"review_mode": "solo_owner"}}, (("ci", 15368),))), \
                patch("p_ases.consumer_activation.read_verified_managed_policy", return_value={
                    "ruleset_id": 4, "applied_record_id": 18, "effective_policy_sha256": "c" * 64,
                }):
            with self.assertRaisesRegex(ValueError, "independent human approval"):
                verify_setup_pr_ready_to_merge(github, 72)

    def test_authenticated_wrong_owner_is_zero_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.make_plan(root, FakeGitHub(), root)
            github = FakeGitHub(actor_id=OWNER_ID + 1)
            with patch.dict(os.environ, {}, clear=True), \
                    patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD), \
                    self.assertRaisesRegex(OwnerAuthorizationError, "not the configured owner"):
                authorize_plan(github, root, path, stdin=TTY(), input_fn=lambda _prompt: "")
            self.assertEqual(github.writes, [])

    def test_owner_local_commit_appends_v2_once_and_retries_by_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            path = self.make_plan(root, github, root)
            plan = read_authorization_plan(path)
            typed = lambda _prompt: plan["plan_sha256"]
            with patch.dict(os.environ, {}, clear=True), \
                    patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
                first = authorize_plan(github, root, path, stdin=TTY(), input_fn=typed)
                second = authorize_plan(github, root, path, stdin=TTY(), input_fn=typed)
            self.assertEqual(first["status"], "AUTHORIZED")
            self.assertEqual(first["evidence_type"], "PASES_OWNER_DECISION_V2")
            self.assertFalse(first["chat_signature"])
            self.assertEqual(second["owner_decision_comment_id"], first["owner_decision_comment_id"])
            self.assertEqual(len(github.writes), 1)
            body = github.writes[0][1]
            self.assertTrue(body.startswith("<!-- PASES_OWNER_DECISION_V2\n"))
            payload = json.loads(body.split("\n", 1)[1].removesuffix("\n-->"))
            self.assertEqual(payload["evidence_channel"], "owner_local_tty_v1")
            self.assertEqual(payload["plan_sha256"], plan["plan_sha256"])
            self.assertEqual(payload["subject_sha256"], SUBJECT_SHA)

    def test_ruleset_commit_writes_v2_and_existing_exact_two_line_issue_57_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeGitHub()
            with patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
                plan = create_authorization_plan(
                    github, root, operation="RULESET_PLAN_APPLY", subject_sha256="c" * 64,
                    target_issue_number=57, details={"activation_issue_number": 57},
                )
            path = root / "ruleset-owner-plan.json"
            write_authorization_plan(path, plan)
            with patch.dict(os.environ, {}, clear=True), \
                    patch("p_ases.owner_authorization.worktree_clean", return_value=True), \
                    patch("p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
                result = authorize_plan(
                    github, root, path, stdin=TTY(), input_fn=lambda _prompt: plan["plan_sha256"],
                )
            self.assertEqual(result["operation"], "RULESET_PLAN_APPLY")
            self.assertEqual(result["ruleset_approval_comment_id"], 100)
            self.assertEqual(len(github.comments[63]), 1)
            self.assertEqual(len(github.comments[57]), 1)
            expected = ("PASES-RULESET-APPROVE: " + "c" * 64 + "\n"
                        "PASES-REPOSITORY: " + REPOSITORY)
            self.assertEqual(github.comments[57][0]["body"], expected)
            decision = json.loads(github.comments[63][0]["body"].split("\n", 1)[1].removesuffix("\n-->"))
            self.assertEqual(decision["operation_plan_sha256"], "c" * 64)

    def test_typed_plan_mismatch_and_stale_live_issue_are_zero_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.make_plan(root, FakeGitHub(), root)
            github = FakeGitHub()
            with patch.dict(os.environ, {}, clear=True), patch(
                    "p_ases.owner_authorization.worktree_clean", return_value=True), patch(
                    "p_ases.owner_authorization.head_sha40", return_value=PLAN_HEAD):
                with self.assertRaisesRegex(OwnerAuthorizationError, "typed plan SHA"):
                    authorize_plan(github, root, path, stdin=TTY(), input_fn=lambda _prompt: "f" * 64)
            self.assertEqual(github.writes, [])

            stale = FakeGitHub()
            original_issue = stale.issue
            stale.issue = lambda number: {**original_issue(number), "state": "closed"}
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(OwnerAuthorizationError):
                    authorize_plan(stale, root, path, stdin=TTY(), input_fn=lambda _prompt: "")
            self.assertEqual(stale.writes, [])


if __name__ == "__main__":
    unittest.main()
