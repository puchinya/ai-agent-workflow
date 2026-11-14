from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from p_ases import execution_epoch as epoch
from p_ases import phase_evidence


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class FakeGitHub:
    def __init__(self, *, issue_body: str, phase_body: str, retired_body: str):
        self.repo = epoch.REPOSITORY
        self.issue_data = {
            "number": epoch.ISSUE_NUMBER,
            "id": epoch.ISSUE_ID,
            "state": "open",
            "pull_request": None,
            "repository_url": f"https://api.github.com/repos/{epoch.REPOSITORY}",
            "body": issue_body,
            "labels": [
                {"name": "enhancement"},
                {"name": "phase:ready"},
                {"name": "kind:single"},
            ],
        }
        self.comments = [
            self._comment(epoch.OLD_PHASE_COMMENT_ID, phase_body),
            self._comment(epoch.RETIRED_INTENT_COMMENT_ID, retired_body),
        ]
        self.next_id = 6875000000
        self.label_update_calls = 0
        self.fail_label_after_apply = False
        self.fail_after_applied_append = False
        self.change_body_after_intent = False

    def _comment(self, comment_id, body):
        return {
            "id": comment_id,
            "body": body,
            "user": {"id": epoch.OWNER_ID, "login": "puchinya", "type": "User"},
            "created_at": "2026-11-14T06:14:56Z",
            "issue_url": f"https://api.github.com/repos/{epoch.REPOSITORY}/issues/{epoch.ISSUE_NUMBER}",
            "html_url": f"https://github.com/{epoch.REPOSITORY}/issues/{epoch.ISSUE_NUMBER}#issuecomment-{comment_id}",
            "url": f"https://api.github.com/repos/{epoch.REPOSITORY}/issues/comments/{comment_id}",
        }

    @staticmethod
    def _copy(value):
        return copy.deepcopy(value)

    def repository_metadata(self):
        return {"id": epoch.REPOSITORY_ID, "owner": {"id": epoch.OWNER_ID}}

    def authenticated_user(self):
        return {"id": epoch.OWNER_ID, "login": "puchinya", "type": "User"}

    def issue(self, number):
        assert number == epoch.ISSUE_NUMBER
        return self._copy(self.issue_data)

    def issues_all(self):
        return [self._copy(self.issue_data)]

    def issue_comments(self, number):
        assert number == epoch.ISSUE_NUMBER
        return self._copy(self.comments)

    def issue_comment(self, number, comment_id):
        assert number == epoch.ISSUE_NUMBER
        row = next((row for row in self.comments if row["id"] == comment_id), None)
        if row is None:
            raise epoch.GitHubError("missing fake comment")
        return self._copy(row)

    def branch(self, ref):
        return {"name": ref, "commit": {"sha": epoch.BASE_SHA40}}

    def create_issue_comment(self, number, body):
        assert number == epoch.ISSUE_NUMBER
        comment_id = self.next_id
        self.next_id += 1
        self.comments.append(self._comment(comment_id, body))
        if body.startswith(epoch.INTENT_START) and self.change_body_after_intent:
            self.issue_data["body"] = "changed after Intent"
        if body.startswith(epoch.APPLIED_START) and self.fail_after_applied_append:
            raise epoch.GitHubError("injected lost Applied response")
        return {"id": comment_id}

    def replace_issue_labels(self, number, labels):
        assert number == epoch.ISSUE_NUMBER
        self.label_update_calls += 1
        self.issue_data["labels"] = [{"name": name} for name in labels]
        if self.fail_label_after_apply:
            raise epoch.GitHubError("injected lost label response")


class ExecutionEpochTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.issue_body = "fixed issue body"
        self.phase_body = "<!-- PASES_PHASE_RESTART_APPLIED_V1\n{}\n-->"
        self.retired_body = self._retired_body()
        self.issue_sha = sha(self.issue_body.encode())
        self.phase_sha = sha(self.phase_body.encode())
        self.retired_sha = sha(self.retired_body.encode())
        self.auth = dict(epoch.AUTHORIZATION)
        self.auth["issue_body_sha256"] = self.issue_sha
        self.auth["old_phase_generation_sha256"] = self.phase_sha
        self.auth["retired_intent_body_sha256"] = self.retired_sha
        self.adc_content = (
            "# Agent Development Contract\n\n" + epoch.REASON + "\n\n"
            + epoch.AUTH_START + canonical(self.auth) + "\n-->"
        ).encode("utf-8")
        self.adc_sha = sha(self.adc_content)
        self.adc = SimpleNamespace(
            pointer=SimpleNamespace(
                comment_id=epoch.ADC_COMMENT_ID, sha256=self.adc_sha, state="approved",
            ),
            contract=SimpleNamespace(content=self.adc_content, sha256=self.adc_sha),
        )
        self.github = FakeGitHub(
            issue_body=self.issue_body, phase_body=self.phase_body, retired_body=self.retired_body,
        )
        self.constants = [
            patch.object(epoch, "ADC_SHA256", self.adc_sha),
            patch.object(epoch, "ISSUE_BODY_SHA256", self.issue_sha),
            patch.object(epoch, "OLD_PHASE_SHA256", self.phase_sha),
            patch.object(epoch, "RETIRED_INTENT_SHA256", self.retired_sha),
            patch.object(epoch, "AUTHORIZATION", self.auth),
            patch.object(epoch, "verify_adc", return_value=self.adc),
            patch.object(epoch, "verify_adc_generation", return_value=None),
            patch.object(epoch, "discover_repository", return_value=epoch.REPOSITORY),
            patch.object(epoch, "verify_remote_repository", return_value=None),
            patch.object(epoch, "current_branch", return_value=epoch.BRANCH_REF),
            patch.object(epoch, "head_sha40", return_value=epoch.BASE_SHA40),
            patch.object(epoch, "remote_branch_sha", return_value=epoch.BASE_SHA40),
            patch.object(epoch, "is_ancestor", return_value=True),
        ]
        for item in self.constants:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self):
        self.temp.cleanup()

    def _retired_body(self):
        value = {
            "adc_comment_id": epoch.PREDECESSOR_ADC_COMMENT_ID,
            "adc_sha256": epoch.PREDECESSOR_ADC_SHA256,
            "base_sha40": epoch.BASE_SHA40,
            "branch_ref": epoch.RETIRED_BRANCH_REF,
            "historical_binding_provenance": "UNVERIFIED",
            "issue_id": epoch.ISSUE_ID,
            "issue_number": epoch.ISSUE_NUMBER,
            "repository": epoch.REPOSITORY,
            "repository_id": epoch.REPOSITORY_ID,
            "schema": epoch.V1_INTENT_SCHEMA,
        }
        return f"<!-- {epoch.V1_INTENT_SCHEMA}\n{canonical(value)}\n-->"

    def test_phase_reader_uses_only_the_v2_epoch_generation_for_issue_71(self):
        subject = (6874828409, "c" * 64)
        with patch("p_ases.execution_epoch.current_execution_epoch_generation", return_value=subject) as current_epoch:
            with patch("p_ases.phase_restart.current_phase_generation",
                       side_effect=AssertionError("V1 phase restart must not be read")):
                self.assertEqual(
                    phase_evidence._active_phase_generation_subject(
                        SimpleNamespace(repo=epoch.REPOSITORY), self.root, 71, object(),
                    ),
                    subject,
                )
        current_epoch.assert_called_once()

    def test_phase_reader_blocks_issue_71_without_a_verified_v2_epoch(self):
        with patch("p_ases.execution_epoch.current_execution_epoch_generation",
                   side_effect=epoch.ExecutionEpochError("missing Applied")):
            with patch("p_ases.phase_restart.current_phase_generation",
                       side_effect=AssertionError("must not fall back to V1")):
                with self.assertRaises(phase_evidence.PhaseEvidenceError):
                    phase_evidence._active_phase_generation_subject(
                        SimpleNamespace(repo=epoch.REPOSITORY), self.root, 71, object(),
                    )

    def test_documents_artifact_impact_maps_only_supported_phase_roots(self):
        text = (
            "- Runtime: runtime/p_ases/execution_epoch.py\n"
            "- Documents: docs/specs/workflow-spec.md docs/specs/runtime-spec.md "
            "docs/design/workflow-design.md docs/testing/pases-lifecycle-tests.md "
            "docs/testing/runtime-tests.md docs/testing/traceability.md "
            "docs/status/issue-71-admin-auth.md"
        )
        verified = SimpleNamespace(contract=SimpleNamespace(section=lambda name: text))
        paths, reasons = phase_evidence._artifact_impacts(verified)
        self.assertEqual(paths["specification"], ("docs/specs/runtime-spec.md", "docs/specs/workflow-spec.md"))
        self.assertEqual(paths["design"], ("docs/design/workflow-design.md",))
        self.assertEqual(paths["test-oracle"], (
            "docs/testing/pases-lifecycle-tests.md", "docs/testing/runtime-tests.md",
            "docs/testing/traceability.md",
        ))
        self.assertEqual(reasons, {})

    def test_documents_artifact_impact_rejects_unmapped_document_paths(self):
        text = (
            "- Documents: docs/specs/workflow-spec.md docs/specs/runtime-spec.md "
            "docs/design/workflow-design.md docs/testing/pases-lifecycle-tests.md "
            "docs/testing/runtime-tests.md docs/testing/traceability.md docs/unknown/file.md"
        )
        verified = SimpleNamespace(contract=SimpleNamespace(section=lambda name: text))
        with self.assertRaises(phase_evidence.PhaseEvidenceError):
            phase_evidence._artifact_impacts(verified)

    def test_marker_is_exact_and_reason_is_bound_by_adc_bytes(self):
        marker, digest = epoch._marker(self.adc)
        self.assertEqual(marker, self.auth)
        self.assertEqual(digest, sha(
            (epoch.AUTH_START + canonical(self.auth) + "\n-->").encode("utf-8")
        ))

    def test_marker_rejects_unknown_fields_and_changed_reason(self):
        bad = dict(self.auth)
        bad["extra"] = "unexpected"
        content = ("# ADC\n" + epoch.REASON + "\n" + epoch.AUTH_START
                   + canonical(bad) + "\n-->").encode()
        altered = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=epoch.ADC_COMMENT_ID, sha256=sha(content), state="approved"),
            contract=SimpleNamespace(content=content, sha256=sha(content)),
        )
        with patch.object(epoch, "ADC_SHA256", sha(content)):
            with self.assertRaises(epoch.ExecutionEpochError):
                epoch._marker(altered)
        content2 = ("# ADC\nDifferent reason\n" + epoch.AUTH_START
                    + canonical(self.auth) + "\n-->").encode()
        altered2 = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=epoch.ADC_COMMENT_ID, sha256=sha(content2), state="approved"),
            contract=SimpleNamespace(content=content2, sha256=sha(content2)),
        )
        with patch.object(epoch, "ADC_SHA256", sha(content2)):
            with self.assertRaises(epoch.ExecutionEpochError):
                epoch._marker(altered2)

    def test_retired_v1_intent_is_read_only_and_exact(self):
        value, comment_id, body_sha = epoch._read_v1_retired_triplet(self.github)
        self.assertEqual(comment_id, epoch.RETIRED_INTENT_COMMENT_ID)
        self.assertEqual(body_sha, self.retired_sha)
        self.assertEqual(value["schema"], epoch.V1_INTENT_SCHEMA)
        self.assertEqual(self.github.label_update_calls, 0)

    def test_inspect_is_read_only_and_reports_ready(self):
        result = epoch.inspect_execution_epoch(self.github, self.root)
        self.assertEqual(result["status"], "READY_TO_APPLY")
        self.assertEqual(result["labels_before"], ["enhancement", "kind:single", "phase:ready"])
        self.assertEqual(self.github.label_update_calls, 0)
        self.assertFalse(epoch.epoch_paths(self.root)[0].exists())

    def test_successful_apply_updates_complete_labels_once_and_writes_v2_journal(self):
        active = epoch.apply_execution_epoch(self.github, self.root)
        self.assertEqual(self.github.label_update_calls, 1)
        self.assertEqual(
            sorted(row["name"] for row in self.github.issue_data["labels"]),
            ["enhancement", "kind:single", "phase:requirements"],
        )
        self.assertEqual(sum(row["body"].startswith(epoch.INTENT_START) for row in self.github.comments), 1)
        self.assertEqual(sum(row["body"].startswith(epoch.APPLIED_START) for row in self.github.comments), 1)
        self.assertEqual(active.adc_comment_id, epoch.ADC_COMMENT_ID)
        self.assertEqual(active.historical_binding_provenance, "UNVERIFIED")
        self.assertEqual(epoch.IssueExecutionEpoch.from_bytes(active.to_bytes()), active)
        self.assertEqual(epoch.inspect_execution_epoch(self.github, self.root)["status"], "ACTIVE")

    def test_issue_drift_after_intent_sends_no_label_write_and_blocks_replay(self):
        self.github.change_body_after_intent = True
        with self.assertRaises(epoch.ExecutionEpochError):
            epoch.apply_execution_epoch(self.github, self.root)
        self.assertEqual(self.github.label_update_calls, 0)
        self.assertEqual(epoch.inspect_execution_epoch(self.github, self.root)["status"],
                         "BLOCKED_RECOVERY_REQUIRED")
        with self.assertRaises(epoch.ExecutionEpochError):
            epoch.apply_execution_epoch(self.github, self.root)
        self.assertEqual(self.github.label_update_calls, 0)
        self.assertEqual(sum(row["body"].startswith(epoch.INTENT_START) for row in self.github.comments), 1)

    def test_lost_label_response_is_not_retried(self):
        self.github.fail_label_after_apply = True
        with self.assertRaises(epoch.ExecutionEpochError):
            epoch.apply_execution_epoch(self.github, self.root)
        self.assertEqual(self.github.label_update_calls, 1)
        self.assertEqual(epoch.inspect_execution_epoch(self.github, self.root)["status"],
                         "BLOCKED_RECOVERY_REQUIRED")
        with self.assertRaises(epoch.ExecutionEpochError):
            epoch.apply_execution_epoch(self.github, self.root)
        self.assertEqual(self.github.label_update_calls, 1)
        self.assertEqual(sum(row["body"].startswith(epoch.APPLIED_START) for row in self.github.comments), 0)

    def test_lost_applied_response_recreates_only_local_attachment(self):
        self.github.fail_after_applied_append = True
        with self.assertRaises(epoch.ExecutionEpochError):
            epoch.apply_execution_epoch(self.github, self.root)
        self.assertEqual(self.github.label_update_calls, 1)
        self.assertEqual(epoch.inspect_execution_epoch(self.github, self.root)["status"],
                         "ACTIVE_ATTACHMENT_REQUIRED")
        intent_count = sum(row["body"].startswith(epoch.INTENT_START) for row in self.github.comments)
        applied_count = sum(row["body"].startswith(epoch.APPLIED_START) for row in self.github.comments)
        active = epoch.apply_execution_epoch(self.github, self.root)
        self.assertEqual(self.github.label_update_calls, 1)
        self.assertEqual(sum(row["body"].startswith(epoch.INTENT_START) for row in self.github.comments), intent_count)
        self.assertEqual(sum(row["body"].startswith(epoch.APPLIED_START) for row in self.github.comments), applied_count)
        self.assertEqual(epoch.inspect_execution_epoch(self.github, self.root)["status"], "ACTIVE")
        self.assertEqual(active.applied_comment_id, max(row["id"] for row in self.github.comments
                                                        if row["body"].startswith(epoch.APPLIED_START)))

    def test_duplicate_retired_v1_intent_blocks_preflight(self):
        duplicate_id = epoch.RETIRED_INTENT_COMMENT_ID + 100
        self.github.comments.append(self.github._comment(duplicate_id, self.retired_body))
        result = epoch.inspect_execution_epoch(self.github, self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.github.label_update_calls, 0)


if __name__ == "__main__":
    unittest.main()
