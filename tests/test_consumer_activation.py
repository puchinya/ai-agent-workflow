from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import ADCError, parse_adc, publish_adc, verify_adc  # noqa: E402
from p_ases.consumer_activation import (  # noqa: E402
    APPROVAL_MARKER, ISSUE_MARKER, RECORD_MARKER, ConsumerActivationError,
    _default_activation_adc, read_consumer_activation_history, read_consumer_activation_record,
    setup_consumer_activation,
    verify_and_record_activation,
)
from p_ases.github import GitHubError  # noqa: E402
from p_ases.gate_policy import PASES_POLICY, choose_gate_for_new_issue  # noqa: E402


REPO = "owner/consumer"
ISSUE = 71
PR = 81
MERGE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MAIN_SHA = "c" * 40
APP_ID = 15368
MERGED_AT = "2026-10-14T12:00:00Z"
USER = {"id": 42, "login": "repo-admin", "type": "User"}


def comment_row(comment_id: int, body: str, *, author: dict | None = None,
                timestamp: str = "2026-10-14T12:01:00Z") -> dict:
    return {
        "id": comment_id, "body": body, "created_at": timestamp,
        "updated_at": timestamp,
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{ISSUE}",
        "html_url": f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-{comment_id}",
        "url": f"https://api.github.com/repos/{REPO}/issues/comments/{comment_id}",
        "user": copy.deepcopy(author or USER),
    }


class FakeGitHub:
    repo = REPO

    def __init__(self):
        self.comments: list[dict] = []
        self.issue_row = {
            "number": ISSUE, "state": "open", "pull_request": None,
            "repository_url": f"https://api.github.com/repos/{REPO}",
            "body": f"{ISSUE_MARKER}\n\nActivation policy and history.",
        }
        self.main_sha = MAIN_SHA
        self.comment_time = "2026-10-14T12:01:00Z"
        self.duplicate_issue = False
        self.issue_comment_list_calls = 0
        self.mutate_on_list_call: int | None = None
        self.mutate_marker = APPROVAL_MARKER
        self.fail_record_once = False
        self.permission = "admin"
        self.ordinary_created_at = "2026-10-14T12:02:00Z"
        self.checks = [{"id": 1, "name": "ci", "head_sha": HEAD_SHA,
                        "status": "completed", "conclusion": "success", "app": {"id": APP_ID}}]
        self.profile_bytes = json.dumps({
            "schema_version": 2, "initialized": True, "project_name": "consumer",
            "components": [], "branch": {"prefix": "feature", "max_slug_length": 48,
                                             "cleanup_on_switch": [],
                                             "required_checks": [{"name": "ci", "trusted_app_id": APP_ID}]},
            "workspace": {"isolation": "auto"},
            "milestones": {"mode": "optional", "version_source": None},
            "hooks": {"branch_switch": [], "verify_quick": [], "verify_final": []},
            "activation": {"issue_number": ISSUE},
        }).encode()
        self.pr = None
        self.prs: dict[int, dict] = {}
        self.next_pr_number = PR
        self.profile_by_commit = {MERGE_SHA: self.profile_bytes}

    def repository_metadata(self):
        return {"default_branch": "main", "id": 9001}

    def branch(self, branch):
        return {"name": branch, "commit": {"sha": self.main_sha}}

    def compare_commits(self, base, head):
        return {"status": "identical" if base == head else "ahead"}

    def authenticated_user(self):
        return copy.deepcopy(USER)

    def collaborator_permission(self, login):
        return {"permission": self.permission, "user": copy.deepcopy(USER)}

    def issues(self):
        if self.issue_row is None:
            return []
        rows = [copy.deepcopy(self.issue_row)]
        if self.duplicate_issue:
            duplicate = copy.deepcopy(self.issue_row)
            duplicate["number"] += 1
            rows.append(duplicate)
        return rows

    def create_issue(self, title, body):
        self.issue_row = {
            "number": ISSUE, "state": "open", "pull_request": None,
            "repository_url": f"https://api.github.com/repos/{REPO}", "body": body,
        }
        return {"number": ISSUE}

    def issue(self, number):
        if number == ISSUE:
            return copy.deepcopy(self.issue_row)
        return {"number": number, "state": "open", "pull_request": None,
                "repository_url": f"https://api.github.com/repos/{REPO}",
                "created_at": self.ordinary_created_at}

    def issue_comments(self, number):
        self.issue_comment_list_calls += 1
        if self.mutate_on_list_call == self.issue_comment_list_calls:
            target_id = next(row["id"] for row in self.comments
                             if row["body"].startswith(self.mutate_marker))
            target = next(row for row in self.comments if row["id"] == target_id)
            target["body"] += "\nmutated"
            self.mutate_on_list_call = None
        return copy.deepcopy(self.comments) if number == ISSUE else []

    def issue_comment(self, number, comment_id):
        if number != ISSUE:
            raise GitHubError("wrong Issue")
        matches = [row for row in self.comments if row["id"] == comment_id]
        if len(matches) != 1:
            raise GitHubError("comment missing or duplicated")
        return copy.deepcopy(matches[0])

    def create_issue_comment(self, number, body):
        if body.startswith(RECORD_MARKER) and self.fail_record_once:
            self.fail_record_once = False
            raise GitHubError("simulated lost record publication")
        comment_id = max((row["id"] for row in self.comments), default=0) + 1
        self.comments.append(comment_row(comment_id, body, timestamp=self.comment_time))
        return {"id": comment_id}

    def pull_requests_for_refs(self, **kwargs):
        return [copy.deepcopy(row) for row in self.prs.values()
                if row.get("base", {}).get("ref") == kwargs["base_ref"]
                and row.get("head", {}).get("ref") == kwargs["head_ref"]]

    def create_pull_request(self, *, title, body, head_ref, base_ref):
        adc = verify_adc(self, ISSUE)
        number = self.next_pr_number
        self.next_pr_number += 1
        self.pr = {
            "number": number, "id": 800 + number, "state": "open", "merged": False, "draft": False,
            "html_url": f"https://github.com/{REPO}/pull/{PR}", "body": body,
            "base": {"ref": base_ref, "sha": MAIN_SHA, "repo": {"full_name": REPO, "id": 9001}},
            "head": {"ref": head_ref, "sha": HEAD_SHA, "repo": {"full_name": REPO, "id": 9001}},
        }
        self.pr["html_url"] = f"https://github.com/{REPO}/pull/{number}"
        self.prs[number] = self.pr
        self.proposed_adc = adc
        return {"number": number}

    def pull_request(self, number):
        if number not in self.prs:
            raise GitHubError("wrong PR")
        return copy.deepcopy(self.prs[number])

    def pull_request_files(self, number):
        return [{"filename": ".agent/project.json", "status": "modified"}]

    def regular_content_at_ref(self, path, ref):
        if path != ".agent/project.json" or ref not in self.profile_by_commit:
            raise GitHubError("wrong merged profile subject")
        return self.profile_by_commit[ref]

    def check_runs_for_ref(self, sha):
        return copy.deepcopy(self.checks)


def setup_fake(github: FakeGitHub, *, merge: bool = True) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation.remote_branch_exists", return_value=False), \
                patch("p_ases.consumer_activation.branch_exists", return_value=False), \
                patch("p_ases.consumer_activation.create_branch"), \
                patch("p_ases.consumer_activation._write_profile"), \
                patch("p_ases.consumer_activation.commit_and_push_one_path", return_value=HEAD_SHA), \
                patch("p_ases.consumer_activation.switch_branch"):
            result = setup_consumer_activation(root, github)
    if result["status"] != "SETUP_PENDING" or result["pr"] != PR:
        raise AssertionError(result)
    if merge:
        github.pr.update({"state": "closed", "merged": True, "merged_at": MERGED_AT,
                          "merged_by": copy.deepcopy(USER), "merge_commit_sha": MERGE_SHA})
        github.prs[github.pr["number"]] = github.pr
        github.profile_by_commit[MERGE_SHA] = github.profile_bytes


class ConsumerActivationTests(unittest.TestCase):
    def test_empty_consumer_creates_issue_proposed_adc_profile_pr_then_admin_merge_activates(self):
        github = FakeGitHub()
        self.assertEqual(parse_adc(_default_activation_adc(REPO, ISSUE), REPO, ISSUE).requirement_ids,
                         ("REQ-01", "REQ-02", "REQ-03"))
        setup_fake(github)
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))
        self.assertFalse(any(row["body"].startswith(RECORD_MARKER) for row in github.comments))
        record, record_id = verify_and_record_activation(github, PR)
        self.assertEqual(record.activation_issue_number, ISSUE)
        self.assertEqual(record.setup_pr_number, PR)
        self.assertEqual(record.activated_at, "2026-10-14T12:01:00Z")
        self.assertEqual(read_consumer_activation_record(github, REPO, ISSUE), (record, record_id))
        github.main_sha = "d" * 40
        self.assertEqual(read_consumer_activation_record(github, REPO, ISSUE), (record, record_id))

    def test_setup_creates_issue_when_missing_and_duplicate_markers_block(self):
        github = FakeGitHub()
        github.issue_row = None
        setup_fake(github, merge=False)
        self.assertIn(ISSUE_MARKER, github.issue_row["body"])
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))
        self.assertFalse(any(row["body"].startswith(RECORD_MARKER) for row in github.comments))

        duplicate = FakeGitHub()
        duplicate.duplicate_issue = True
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA):
            with self.assertRaisesRegex(ConsumerActivationError, "multiple marked"):
                setup_consumer_activation(Path(tmp), duplicate)
        self.assertEqual(duplicate.comments, [])

    def test_merge_is_required_and_authenticated_verifier_must_match_merger(self):
        github = FakeGitHub()
        setup_fake(github, merge=False)
        with self.assertRaisesRegex(ConsumerActivationError, "merged setup PR"):
            verify_and_record_activation(github, PR)
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))

        github = FakeGitHub()
        setup_fake(github)
        github.authenticated_user = lambda: {"id": 43, "login": "different-admin", "type": "User"}
        with self.assertRaisesRegex(ConsumerActivationError, "authenticated human"):
            verify_and_record_activation(github, PR)
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))
        github.authenticated_user = lambda: copy.deepcopy(USER)
        record, record_id = verify_and_record_activation(github, PR)
        self.assertEqual(read_consumer_activation_record(github, REPO, ISSUE), (record, record_id))

    def test_non_admin_bad_check_and_wrong_app_fail_before_activation_comments(self):
        github = FakeGitHub()
        setup_fake(github)
        github.permission = "write"
        with self.assertRaisesRegex(ConsumerActivationError, "current repository admin"):
            verify_and_record_activation(github, PR)
        self.assertFalse(any(row["body"].startswith(APPROVAL_MARKER) for row in github.comments))

        github = FakeGitHub()
        setup_fake(github)
        github.checks[0]["conclusion"] = "failure"
        with self.assertRaisesRegex(ConsumerActivationError, "did not pass"):
            verify_and_record_activation(github, PR)

        github = FakeGitHub()
        setup_fake(github)
        github.checks[0]["app"]["id"] += 1
        with self.assertRaisesRegex(ConsumerActivationError, "did not pass"):
            verify_and_record_activation(github, PR)

    def test_partial_approval_retry_is_idempotent(self):
        github = FakeGitHub()
        setup_fake(github)
        github.fail_record_once = True
        with self.assertRaisesRegex(ConsumerActivationError, "publication failed"):
            verify_and_record_activation(github, PR)
        self.assertEqual(sum(row["body"].startswith(APPROVAL_MARKER) for row in github.comments), 1)
        record, _ = verify_and_record_activation(github, PR)
        self.assertEqual(sum(row["body"].startswith(RECORD_MARKER) for row in github.comments), 1)

    def test_stale_adc_deletion_and_mid_read_mutation_fail_closed(self):
        github = FakeGitHub()
        setup_fake(github)
        proposed = github.proposed_adc.contract.content.replace(
            b"Every Gate Selection stays bound to the exact Activation record that authorized it.",
            b"Every Gate Selection stays bound to the exact approved Activation record.",
        )
        publish_adc(github, ISSUE, proposed, state="draft", supersede=True)
        with self.assertRaisesRegex(ConsumerActivationError, "stale or superseded"):
            verify_and_record_activation(github, PR)

        github = FakeGitHub()
        setup_fake(github)
        proposal_id = github.proposed_adc.pointer.comment_id
        github.comments = [row for row in github.comments if row["id"] != proposal_id]
        with self.assertRaisesRegex(ConsumerActivationError, "Activation ADC is missing"):
            verify_and_record_activation(github, PR)

        github = FakeGitHub()
        setup_fake(github)
        _record, _record_id = verify_and_record_activation(github, PR)
        github.issue_comment_list_calls = 0
        github.mutate_marker = RECORD_MARKER
        github.mutate_on_list_call = 2
        with self.assertRaisesRegex(ConsumerActivationError, "changed during direct/list/direct"):
            read_consumer_activation_record(github, REPO, ISSUE)

    def test_edited_duplicate_and_wrong_author_history_fail_closed(self):
        github = FakeGitHub()
        setup_fake(github)
        record, comment_id = verify_and_record_activation(github, PR)
        record_row = next(row for row in github.comments if row["id"] == comment_id)
        record_row["updated_at"] = "2026-10-14T12:03:00Z"
        with self.assertRaisesRegex(ConsumerActivationError, "edited"):
            read_consumer_activation_record(github, REPO, ISSUE)

        github = FakeGitHub()
        setup_fake(github)
        _record, _record_id = verify_and_record_activation(github, PR)
        duplicate = copy.deepcopy(next(row for row in github.comments if row["body"].startswith(RECORD_MARKER)))
        duplicate["id"] += 100
        github.comments.append(duplicate)
        with self.assertRaisesRegex(ConsumerActivationError, "history"):
            read_consumer_activation_record(github, REPO, ISSUE)

        github = FakeGitHub()
        setup_fake(github)
        _record, _record_id = verify_and_record_activation(github, PR)
        approval = next(row for row in github.comments if row["body"].startswith(APPROVAL_MARKER))
        approval["user"] = {"id": 777, "login": "other-user", "type": "User"}
        with self.assertRaisesRegex(ConsumerActivationError, "author"):
            read_consumer_activation_record(github, REPO, ISSUE)

    def test_consumer_issue_27_uses_consumer_activation_not_fixed_bootstrap(self):
        github = FakeGitHub()
        setup_fake(github)
        record, _ = verify_and_record_activation(github, PR)
        selected = choose_gate_for_new_issue(
            github, REPO, 27, "2026-10-14T12:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.policy_version, PASES_POLICY)
        self.assertEqual(selected.activation_issue_number, ISSUE)
        self.assertEqual(selected.activation_comment_id, read_consumer_activation_record(github, REPO, ISSUE)[1])
        github.ordinary_created_at = record.activated_at
        self.assertIsNone(choose_gate_for_new_issue(
            github, REPO, 27, "2026-10-14T12:03:00Z", activation_issue_number=ISSUE,
        ))

    def test_successor_activation_appends_chain_and_old_selection_keeps_old_record(self):
        github = FakeGitHub()
        setup_fake(github)
        first, first_id = verify_and_record_activation(github, PR)
        selected_before = choose_gate_for_new_issue(
            github, REPO, 28, "2026-10-14T12:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertEqual(selected_before.activation_comment_id, first_id)

        revised = github.proposed_adc.contract.content.replace(
            b"Every Gate Selection stays bound to the exact Activation record that authorized it.",
            b"Every Gate Selection stays bound to the exact successor Activation record that authorized it.",
        )
        publish_adc(github, ISSUE, revised, state="draft", supersede=True, explicitly_approved=False)
        github.comment_time = "2026-10-14T13:01:00Z"
        with tempfile.TemporaryDirectory() as tmp, \
                patch("p_ases.consumer_activation.worktree_clean", return_value=True), \
                patch("p_ases.consumer_activation.discover_repository", return_value=REPO), \
                patch("p_ases.consumer_activation.current_branch", return_value="main"), \
                patch("p_ases.consumer_activation.head_sha40", return_value=MAIN_SHA), \
                patch("p_ases.consumer_activation.remote_branch_exists", return_value=False), \
                patch("p_ases.consumer_activation.branch_exists", return_value=False), \
                patch("p_ases.consumer_activation.create_branch"), \
                patch("p_ases.consumer_activation._write_profile"), \
                patch("p_ases.consumer_activation.commit_and_push_one_path", return_value=HEAD_SHA), \
                patch("p_ases.consumer_activation.switch_branch"):
            result = setup_consumer_activation(Path(tmp), github)
        second_pr = result["pr"]
        self.assertNotEqual(second_pr, PR)
        second_merge = "e" * 40
        second = github.prs[second_pr]
        second.update({"state": "closed", "merged": True, "merged_at": "2026-10-14T13:00:00Z",
                       "merged_by": copy.deepcopy(USER), "merge_commit_sha": second_merge})
        github.profile_by_commit[second_merge] = github.profile_bytes
        github.main_sha = "f" * 40
        successor, successor_id = verify_and_record_activation(github, second_pr)
        self.assertEqual(successor.predecessor_record_id, first_id)
        self.assertGreater(successor_id, first_id)
        history = read_consumer_activation_record(github, REPO, ISSUE)
        self.assertEqual(history, (successor, successor_id))
        self.assertEqual(read_consumer_activation_history(github, REPO, ISSUE),
                         [(first, first_id), (successor, successor_id)])
        self.assertEqual(selected_before.activation_comment_id, first_id)
        github.ordinary_created_at = "2026-10-14T13:02:00Z"
        later_selection = choose_gate_for_new_issue(
            github, REPO, 29, "2026-10-14T13:03:00Z", activation_issue_number=ISSUE,
        )
        self.assertEqual(later_selection.activation_comment_id, successor_id)


if __name__ == "__main__":
    unittest.main()
