from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.adc import ADCError, parse_adc, publish_adc, restore_adc, verify_adc
from p_ases.github import GitHubError
from p_ases.intake import (
    Decision,
    Intent,
    decide,
    draft_from_request,
    from_chat,
    from_file,
    from_issue,
)


def adc_bytes(repository: str = "octo/repo", *, child_key: str | None = None,
              issue: int | None = 1, newline: str = "\n", requirement_id: str = "REQ-01") -> bytes:
    metadata = [
        "# Agent Development Contract",
        f"Repository: {repository}",
    ]
    if issue is not None:
        metadata.append(f"Issue: #{issue}")
    if child_key is not None:
        metadata.append(f"Child key: {child_key}")
    metadata.extend([
        "State: approved",
        "",
        "## Issue",
        "Implement the scoped workflow change.",
        "",
        "## Scope and change kind",
        "Scope: ADC intake and lifecycle.",
        "Change kind: implementation and tests.",
        "",
        "## Requirements",
        f"- {requirement_id}: Accept the explicit supported input paths.",
        "",
        "## Architecture decisions",
        "Use the standard-library runtime.",
        "",
        "## Artifact impact",
        "Runtime and tests are created; product behavior is unchanged.",
        "",
        "## Exact changes",
        "Add the scoped core modules.",
        "",
        "## Invariants and non-goals",
        "Keep payload bytes exact.",
        "",
        "## Verification obligations",
        "Run the focused regression tests.",
        "",
        "## Reviewer Checklist",
        "- [ ] Verify exact ADC identity.",
        "- [ ] Verify failure paths.",
        "",
        "## Completion gates",
        "Open a review-ready PR and stop at User Review.",
        "",
    ])
    return newline.join(metadata).encode("utf-8")


class FakeGitHub:
    repo = "octo/repo"

    def __init__(self) -> None:
        self.issue_data = {
            "id": 1001,
            "number": 1,
            "repository_url": "https://api.github.com/repos/octo/repo",
            "state": "open",
            "body": "# Parent issue\nKeep this text.\n",
            "pull_request": None,
        }
        self.comments: dict[int, dict[str, object]] = {}
        self.next_comment_id = 2001
        self.race_body: str | None = None
        self.wrong_comment_issue = False
        self.fail_update = False
        self.extra_listed_comments: list[dict[str, object]] = []
        self.altered_readback: dict[int, str] = {}

    def issue(self, number: int) -> dict[str, object]:
        assert number == 1
        return copy.deepcopy(self.issue_data)

    def create_issue_comment(self, number: int, body: str) -> dict[str, object]:
        assert number == 1
        comment_id = self.next_comment_id
        self.next_comment_id += 1
        self.comments[comment_id] = {
            "id": comment_id,
            "body": body,
            "issue_url": "https://api.github.com/repos/octo/repo/issues/1",
        }
        return copy.deepcopy(self.comments[comment_id])

    def issue_comment(self, number: int, comment_id: int) -> dict[str, object]:
        assert number == 1
        comment = copy.deepcopy(self.comments[comment_id])
        if comment_id in self.altered_readback:
            comment["body"] = self.altered_readback[comment_id]
        if self.race_body is not None:
            self.issue_data["body"] = self.race_body
        if self.wrong_comment_issue:
            comment["issue_url"] = "https://api.github.com/repos/octo/repo/issues/2"
        return comment

    def issue_comments(self, number: int) -> list[dict[str, object]]:
        assert number == 1
        return ([copy.deepcopy(comment) for comment in self.comments.values()]
                + copy.deepcopy(self.extra_listed_comments))

    def update_issue(self, number: int, body: str) -> dict[str, object]:
        assert number == 1
        if self.fail_update:
            raise GitHubError("simulated pointer write failure")
        self.issue_data["body"] = body
        return self.issue(number)


class ADCValidationTests(unittest.TestCase):
    def test_exact_bytes_and_crlf_are_preserved(self):
        payload = adc_bytes(newline="\r\n")
        contract = parse_adc(payload, "octo/repo", 1)
        self.assertEqual(contract.content, payload)
        self.assertEqual(contract.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(contract.byte_length, len(payload))
        self.assertEqual(contract.requirement_ids, ("REQ-01",))

    def test_repository_and_issue_must_match_selected_target(self):
        with self.assertRaisesRegex(ADCError, "Repository does not match"):
            parse_adc(adc_bytes("someone/else"), "octo/repo", 1)
        with self.assertRaisesRegex(ADCError, "Issue metadata does not match"):
            parse_adc(adc_bytes(issue=2), "octo/repo", 1)

    def test_code_fence_headings_are_not_sections(self):
        payload = adc_bytes().replace(
            b"## Exact changes\nAdd the scoped core modules.",
            b"## Exact changes\n```md\n## Requirements\n- REQ-99: not a section\n```\nAdd the scoped core modules.",
        )
        contract = parse_adc(payload, "octo/repo", 1)
        self.assertEqual(contract.requirement_ids, ("REQ-01",))

    def test_code_fence_requirement_examples_are_not_requirements(self):
        payload = adc_bytes().replace(
            b"- REQ-01: Accept the explicit supported input paths.",
            b"- REQ-01: Accept the explicit supported input paths.\n```md\n- REQ-99: example only\n```\n    - REQ-98: indented code example",
        )
        contract = parse_adc(payload, "octo/repo", 1)
        self.assertEqual(contract.requirement_ids, ("REQ-01",))

    def test_code_fence_metadata_cannot_override_the_contract_header(self):
        payload = adc_bytes().replace(
            b"Issue: #1\n",
            b"Issue: #1\n```md\nRepository: attacker/repo\nChild key: fake\n```\n",
        )
        contract = parse_adc(payload, "octo/repo", 1)
        self.assertIsNone(contract.child_key)

    def test_missing_section_duplicate_req_and_secret_fail_closed(self):
        payload = adc_bytes().replace(b"## Artifact impact\nRuntime and tests are created; product behavior is unchanged.\n\n", b"")
        with self.assertRaisesRegex(ADCError, "missing required sections"):
            parse_adc(payload, "octo/repo", 1)
        duplicate = adc_bytes().replace(b"- REQ-01: Accept", b"- REQ-01: First\n- REQ-01: Accept")
        with self.assertRaisesRegex(ADCError, "duplicate REQ-IDs"):
            parse_adc(duplicate, "octo/repo", 1)
        secret = adc_bytes().replace(b"Keep payload bytes exact.", b"api_key=example-secret-value")
        with self.assertRaisesRegex(ADCError, "credential or secret"):
            parse_adc(secret, "octo/repo", 1)


class ADCPublicationTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.payload = adc_bytes()

    def adc_comment_ids(self):
        return {
            comment_id for comment_id, comment in self.github.comments.items()
            if isinstance(comment.get("body"), str)
            and comment["body"].startswith("# Agent Development Contract")
        }

    def publication_marker_ids(self):
        return {
            comment_id for comment_id, comment in self.github.comments.items()
            if isinstance(comment.get("body"), str)
            and comment["body"].startswith("<!-- PASES_ADC_PUBLISH_V1\n")
        }

    def test_supersession_does_not_reuse_a_historical_adc_after_a_to_b_to_a(self):
        first_a = publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        payload_b = self.payload.replace(
            b"Accept the explicit supported input paths.",
            b"Accept the explicitly supported review input paths.",
        )
        published_b = publish_adc(
            self.github, 1, payload_b, state="approved", explicitly_approved=True, supersede=True,
        )
        second_a = publish_adc(
            self.github, 1, self.payload, state="approved", explicitly_approved=True, supersede=True,
        )

        self.assertEqual(len({first_a.comment_id, published_b.comment_id, second_a.comment_id}), 3)
        self.assertEqual(len(self.adc_comment_ids()), 3)
        self.assertEqual(len(self.publication_marker_ids()), 3)
        marker_bodies = {self.github.comments[comment_id]["body"] for comment_id in self.publication_marker_ids()}
        self.assertEqual(len(marker_bodies), 3)
        operation_ids = {body.splitlines()[1] for body in marker_bodies}
        self.assertEqual(len(operation_ids), 3)
        self.assertEqual(verify_adc(self.github, 1).pointer.comment_id, second_a.comment_id)

    def test_publish_reads_back_comment_before_pointer_and_verifies(self):
        pointer = publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        self.assertEqual(pointer.comment_id, 2002)
        self.assertEqual(len(self.adc_comment_ids()), 1)
        self.assertIn("# Parent issue\nKeep this text.\n", self.github.issue_data["body"])
        verified = verify_adc(self.github, 1)
        self.assertEqual(verified.contract.content, self.payload)
        self.assertEqual(verified.pointer, pointer)

    def test_pointer_example_in_code_fence_does_not_count_as_the_live_pointer(self):
        self.github.issue_data["body"] += (
            "\n```md\n## Agent Development Contract\n"
            "Comment ID: 9999\nSHA-256: " + "f" * 64 + "\nBytes: 1\nState: approved\n```\n"
        )
        pointer = publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        self.assertEqual(verify_adc(self.github, 1).pointer, pointer)

    def test_approved_publication_requires_explicit_user_decision(self):
        with self.assertRaisesRegex(ADCError, "explicit user approval"):
            publish_adc(self.github, 1, self.payload, state="approved")
        self.assertEqual(self.github.comments, {})

    def test_pointer_is_not_updated_when_issue_changes_during_publish(self):
        self.github.race_body = "# concurrently edited issue\n"
        with self.assertRaisesRegex(ADCError, "changed during publication"):
            publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        self.assertNotIn("## Agent Development Contract", self.github.issue_data["body"])

    def test_retry_reuses_exact_orphan_comment_after_pointer_write_failure(self):
        self.github.fail_update = True
        with self.assertRaisesRegex(ADCError, "pointer write failure"):
            publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        self.assertEqual(len(self.adc_comment_ids()), 1)
        self.assertEqual(len(self.github.comments), 2)  # transaction marker plus ADC comment
        self.github.fail_update = False
        pointer = publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        self.assertEqual(len(self.adc_comment_ids()), 1)
        self.assertEqual(len(self.github.comments), 2)
        self.assertEqual(pointer.comment_id, 2002)

    def test_comment_from_another_issue_cannot_satisfy_the_pointer(self):
        self.github.wrong_comment_issue = True
        with self.assertRaisesRegex(ADCError, "does not belong"):
            publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)

    def test_supersession_adds_a_new_comment_and_preserves_old_comment(self):
        first = publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        with self.assertRaisesRegex(ADCError, "explicit supersession"):
            publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        second = publish_adc(self.github, 1, self.payload, state="approved",
                             explicitly_approved=True, supersede=True)
        self.assertNotEqual(first.comment_id, second.comment_id)
        self.assertEqual(self.github.comments[first.comment_id]["body"], self.payload.decode())
        self.assertEqual(verify_adc(self.github, 1).pointer.comment_id, second.comment_id)

    def test_supersession_retry_reuses_unpointed_comment_after_pointer_patch_failure(self):
        first = publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        updated_payload = self.payload.replace(
            b"Accept the explicit supported input paths.",
            b"Accept the explicitly confirmed supported input paths.",
        )
        self.github.fail_update = True
        with self.assertRaisesRegex(ADCError, "pointer write failure"):
            publish_adc(self.github, 1, updated_payload, state="approved",
                        explicitly_approved=True, supersede=True)
        orphaned_id = self.github.next_comment_id - 1
        self.assertEqual(len(self.adc_comment_ids()), 2)
        self.assertEqual(len(self.publication_marker_ids()), 2)
        self.assertEqual(len(self.github.comments), 4)
        self.assertEqual(verify_adc(self.github, 1).pointer, first)

        self.github.fail_update = False
        retried = publish_adc(self.github, 1, updated_payload, state="approved",
                              explicitly_approved=True, supersede=True)
        self.assertEqual(len(self.adc_comment_ids()), 2)
        self.assertEqual(len(self.publication_marker_ids()), 2)
        self.assertEqual(len(self.github.comments), 4)
        self.assertEqual(retried.comment_id, orphaned_id)
        self.assertEqual(verify_adc(self.github, 1).contract.content, updated_payload)

    def test_different_publish_cannot_claim_an_unresolved_operation_candidate(self):
        publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        payload_b = self.payload.replace(b"REQ-01", b"REQ-02")
        payload_c = self.payload.replace(b"REQ-01", b"REQ-03")
        self.github.fail_update = True
        with self.assertRaisesRegex(ADCError, "pointer write failure"):
            publish_adc(self.github, 1, payload_b, state="approved",
                        explicitly_approved=True, supersede=True)

        self.github.fail_update = False
        with self.assertRaisesRegex(ADCError, "another ADC publication is unresolved"):
            publish_adc(self.github, 1, payload_c, state="approved",
                        explicitly_approved=True, supersede=True)
        self.assertEqual(len(self.publication_marker_ids()), 2)
        self.assertEqual(len(self.adc_comment_ids()), 2)

        retried = publish_adc(self.github, 1, payload_b, state="approved",
                              explicitly_approved=True, supersede=True)
        self.assertEqual(len(self.publication_marker_ids()), 2)
        self.assertEqual(len(self.adc_comment_ids()), 2)
        self.assertEqual(verify_adc(self.github, 1).contract.content, payload_b)
        self.assertGreater(retried.comment_id, max(self.publication_marker_ids()))

    def test_supersession_retry_fails_closed_for_duplicate_unpointed_comments(self):
        publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        updated_payload = self.payload.replace(b"REQ-01", b"REQ-02")
        self.github.fail_update = True
        with self.assertRaisesRegex(ADCError, "pointer write failure"):
            publish_adc(self.github, 1, updated_payload, state="approved",
                        explicitly_approved=True, supersede=True)
        duplicate = copy.deepcopy(self.github.comments[self.github.next_comment_id - 1])
        duplicate["id"] = self.github.next_comment_id
        self.github.extra_listed_comments.append(duplicate)
        self.github.fail_update = False

        with self.assertRaisesRegex(ADCError, "multiple identical unpointed"):
            publish_adc(self.github, 1, updated_payload, state="approved",
                        explicitly_approved=True, supersede=True)
        self.assertEqual(len(self.adc_comment_ids()), 2)

    def test_supersession_retry_rejects_candidate_owned_by_another_issue(self):
        publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        self.github.extra_listed_comments.append({
            "id": 2999,
            "body": self.payload.decode(),
            "issue_url": "https://api.github.com/repos/octo/repo/issues/2",
        })
        with self.assertRaisesRegex(ADCError, "does not belong to the selected Issue"):
            publish_adc(self.github, 1, self.payload, state="approved",
                        explicitly_approved=True, supersede=True)
        self.assertEqual(len(self.adc_comment_ids()), 1)

    def test_supersession_retry_rejects_changed_readback_for_candidate(self):
        publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        updated_payload = self.payload.replace(b"REQ-01", b"REQ-02")
        self.github.fail_update = True
        with self.assertRaisesRegex(ADCError, "pointer write failure"):
            publish_adc(self.github, 1, updated_payload, state="approved",
                        explicitly_approved=True, supersede=True)
        candidate_id = self.github.next_comment_id - 1
        self.github.altered_readback[candidate_id] = updated_payload.decode() + "tampered"
        self.github.fail_update = False
        with self.assertRaisesRegex(ADCError, "readback does not match"):
            publish_adc(self.github, 1, updated_payload, state="approved",
                        explicitly_approved=True, supersede=True)
        self.assertEqual(len(self.adc_comment_ids()), 2)

    def test_restore_writes_the_exact_verified_payload(self):
        publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "contract.md"
            restored = restore_adc(self.github, 1, destination)
            self.assertEqual(destination.read_bytes(), self.payload)
            self.assertEqual(restored.contract.sha256, hashlib.sha256(self.payload).hexdigest())


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.payload = adc_bytes()
        publish_adc(self.github, 1, self.payload, state="approved", explicitly_approved=True)
        self.verified = verify_adc(self.github, 1)

    def test_same_approved_contract_executes_from_file_chat_and_issue(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adc.md"
            path.write_bytes(self.payload)
            file_submission = from_file(
                path, repository="octo/repo", issue_number=1, explicitly_submitted=True,
                state="approved",
            )
        chat_submission = from_chat(
            self.payload.decode("utf-8"), repository="octo/repo", issue_number=1,
            explicitly_submitted=True, state="approved", actor_id="user-1",
            authenticated_actor_id="user-1",
        )
        issue_submission, verified = from_issue(self.github, 1, explicitly_submitted=True)
        results = [
            decide(file_submission, expected_repository="octo/repo", verified_adc=self.verified),
            decide(chat_submission, expected_repository="octo/repo", verified_adc=self.verified),
            decide(issue_submission, expected_repository="octo/repo", verified_adc=verified),
        ]
        self.assertTrue(all(result.decision is Decision.EXECUTE for result in results))
        self.assertEqual({result.submission.content for result in results}, {self.payload})

    def test_draft_and_review_only_requests_do_not_execute(self):
        draft = from_chat(
            self.payload.decode(), repository="octo/repo", issue_number=1, explicitly_submitted=True,
            intent=Intent.DRAFT_ONLY, actor_id="user-1", authenticated_actor_id="user-1",
        )
        review = from_chat(
            self.payload.decode(), repository="octo/repo", issue_number=1, explicitly_submitted=True,
            intent=Intent.REVIEW_ONLY, state="approved", actor_id="user-1", authenticated_actor_id="user-1",
        )
        self.assertIs(decide(draft, expected_repository="octo/repo").decision, Decision.DRAFT)
        self.assertIs(decide(review, expected_repository="octo/repo").decision, Decision.REVIEW_ONLY)

    def test_direct_request_creates_a_complete_unapproved_draft(self):
        proposal = draft_from_request(
            "Add a configurable retry limit.", repository="octo/repo", issue_number=1,
            actor_id="user-1", authenticated_actor_id="user-1",
        )
        draft = parse_adc(proposal.submission.content, "octo/repo", 1)
        self.assertEqual(draft.requirement_ids, ("REQ-01",))
        self.assertIs(decide(proposal.submission, expected_repository="octo/repo").decision, Decision.DRAFT)
        self.assertGreaterEqual(len(proposal.unresolved_questions), 1)

    def test_repository_invariant_conflict_stops_execution_with_a_concrete_question(self):
        submission = from_chat(
            self.payload.decode(), repository="octo/repo", issue_number=1, explicitly_submitted=True,
            state="approved", actor_id="user-1", authenticated_actor_id="user-1",
        )
        result = decide(
            submission, expected_repository="octo/repo", verified_adc=self.verified,
            invariant_conflicts=("Should the existing default remain unchanged?",),
        )
        self.assertIs(result.decision, Decision.BLOCKED)
        self.assertIn("Should the existing default remain unchanged?", result.reason)

    def test_unsubmitted_quoted_mismatched_and_unapproved_content_blocks(self):
        unsubmitted = from_file(
            Path(__file__), repository="octo/repo", issue_number=1, explicitly_submitted=False,
        )
        quoted = from_chat(
            self.payload.decode(), repository="octo/repo", issue_number=1, explicitly_submitted=True,
            state="approved", actor_id="user-1", authenticated_actor_id="user-1", quoted_or_forwarded=True,
        )
        wrong_repo = from_file(
            Path(__file__), repository="octo/other", issue_number=1, explicitly_submitted=True,
            state="approved",
        )
        unapproved = from_chat(
            self.payload.decode(), repository="octo/repo", issue_number=1, explicitly_submitted=True,
            state="draft", actor_id="user-1", authenticated_actor_id="user-1",
        )
        self.assertIs(decide(unsubmitted, expected_repository="octo/repo").decision, Decision.BLOCKED)
        self.assertIs(decide(quoted, expected_repository="octo/repo").decision, Decision.BLOCKED)
        self.assertIs(decide(wrong_repo, expected_repository="octo/repo").decision, Decision.BLOCKED)
        self.assertIs(decide(unapproved, expected_repository="octo/repo").decision, Decision.NEEDS_APPROVAL)

    def test_approved_source_needs_an_immutable_comment_readback_before_execution(self):
        approved = from_chat(
            self.payload.decode(), repository="octo/repo", issue_number=1, explicitly_submitted=True,
            state="approved", actor_id="user-1", authenticated_actor_id="user-1",
        )
        result = decide(approved, expected_repository="octo/repo")
        self.assertIs(result.decision, Decision.NEEDS_VERIFICATION)

    def test_chat_actor_must_match_the_authenticated_user(self):
        submission = from_chat(
            self.payload.decode(), repository="octo/repo", issue_number=1, explicitly_submitted=True,
            state="approved", actor_id="quoted-user", authenticated_actor_id="current-user",
        )
        self.assertIs(decide(submission, expected_repository="octo/repo").decision, Decision.BLOCKED)

    def test_closed_issue_cannot_start_execution(self):
        submission, _ = from_issue(self.github, 1, explicitly_submitted=True)
        self.github.issue_data["state"] = "closed"
        from p_ases.intake import Submission
        closed = Submission(**{**submission.__dict__, "issue_snapshot": self.github.issue(1)})
        self.assertIs(decide(closed, expected_repository="octo/repo").decision, Decision.BLOCKED)


if __name__ == "__main__":
    unittest.main()
