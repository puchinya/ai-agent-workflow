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

from p_ases.delivery import ReadinessResult, readiness_path, write_readiness  # noqa: E402
from p_ases.evidence_store import VerificationSubject  # noqa: E402
from p_ases.github import GitHubError  # noqa: E402
from p_ases import phase_rework as module  # noqa: E402


def readiness(root: Path, head: str = "e" * 40) -> ReadinessResult:
    subject = VerificationSubject(
        repository=module.REPOSITORY,
        issue_number=module.ISSUE_NUMBER,
        pr_number=module.PR_NUMBER,
        adc_comment_id=module.REWORK_ADC_COMMENT_ID,
        adc_sha256=module.REWORK_ADC_SHA256,
        plan_sha256="a" * 64,
        pr_head_sha40=head,
    ).validate()
    result = ReadinessResult("PASS", subject, (), (), "b" * 64).validate()
    write_readiness(readiness_path(root, result), result)
    return result


def live_subject(root: Path, *, head: str = "e" * 40,
                 labels: tuple[str, ...] | None = None) -> module._Live:
    current_adc = SimpleNamespace(
        pointer=SimpleNamespace(comment_id=module.REWORK_ADC_COMMENT_ID, state="approved"),
        contract=SimpleNamespace(sha256=module.REWORK_ADC_SHA256),
    )
    issue_labels = labels or tuple(sorted(module.LABELS_BEFORE))
    return module._Live(
        current_adc=current_adc,
        epoch=SimpleNamespace(),
        issue={"number": 71},
        labels=issue_labels,
        branch_ref=module.BRANCH_REF,
        head_sha40=head,
        pr={},
        executor_user_id=module.OWNER_ID,
        authorization_sha256="c" * 64,
        root=root,
    )


def intent_record(root: Path, head: str = "e" * 40) -> tuple[module.PhaseReworkRecord, ReadinessResult]:
    current = live_subject(root, head=head)
    result = readiness(root, head)
    payload = module._intent_payload(current, result)
    body = module._record_body(module.INTENT_SCHEMA, payload)
    record = module.PhaseReworkRecord(
        101, module.INTENT_SCHEMA, payload, body, module.OWNER_ID, payload["created_at"],
    )
    return record, result


def issue_comment(record: module.PhaseReworkRecord, comment_id: int) -> dict:
    created = "2026-11-15T00:00:00Z"
    return {
        "id": comment_id,
        "body": record.body,
        "created_at": created,
        "updated_at": created,
        "user": {"id": module.OWNER_ID, "type": "User", "login": "puchinya"},
        "issue_url": f"https://api.github.com/repos/{module.REPOSITORY}/issues/{module.ISSUE_NUMBER}",
        "html_url": f"https://github.com/{module.REPOSITORY}/issues/{module.ISSUE_NUMBER}#issuecomment-{comment_id}",
        "url": f"https://api.github.com/repos/{module.REPOSITORY}/issues/comments/{comment_id}",
    }


class AuthorizationTests(unittest.TestCase):
    def test_exact_v2_marker_is_bound_to_adc_bytes_and_predecessor(self):
        raw = json.dumps(module.AUTHORIZATION, sort_keys=True, separators=(",", ":"))
        content = (
            f"Predecessor ADC: Issue #71 comment #{module.PREDECESSOR_ADC_COMMENT_ID}, "
            f"SHA-256 {module.PREDECESSOR_ADC_SHA256}\n\n"
            f"<!-- {module.AUTH_SCHEMA}\n{raw}\n-->\n"
        ).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        verified = SimpleNamespace(
            pointer=SimpleNamespace(state="approved", comment_id=module.REWORK_ADC_COMMENT_ID),
            contract=SimpleNamespace(
                sha256=digest, byte_length=len(content), repository=module.REPOSITORY,
                content=content,
            ),
        )
        with patch.object(module, "REWORK_ADC_SHA256", digest), \
                patch.object(module, "REWORK_ADC_BYTES", len(content)):
            payload, marker_sha = module.parse_authorization(verified)
        self.assertEqual(payload, module.AUTHORIZATION)
        self.assertEqual(len(marker_sha), 64)

    def test_noncanonical_marker_and_wrong_predecessor_fail_closed(self):
        raw = json.dumps(module.AUTHORIZATION, sort_keys=True, indent=1)
        content = (
            f"Predecessor ADC: Issue #71 comment #{module.PREDECESSOR_ADC_COMMENT_ID}, "
            f"SHA-256 {module.PREDECESSOR_ADC_SHA256}\n"
            f"<!-- {module.AUTH_SCHEMA}\n{raw}\n-->"
        ).encode()
        digest = hashlib.sha256(content).hexdigest()
        verified = SimpleNamespace(
            pointer=SimpleNamespace(state="approved", comment_id=module.REWORK_ADC_COMMENT_ID),
            contract=SimpleNamespace(sha256=digest, byte_length=len(content),
                                     repository=module.REPOSITORY, content=content),
        )
        with patch.object(module, "REWORK_ADC_SHA256", digest), \
                patch.object(module, "REWORK_ADC_BYTES", len(content)), \
                self.assertRaisesRegex(module.PhaseReworkError, "noncanonical"):
            module.parse_authorization(verified)

    def test_malformed_reserved_header_is_a_history_candidate(self):
        fake = SimpleNamespace(issue_comments=lambda _issue: [{
            "id": 101, "body": "<!----- PASES_ISSUE_VERIFICATION_REWORK_INTENT_V2\n{}\n-->",
        }])
        with self.assertRaisesRegex(module.PhaseReworkError, "malformed reserved"):
            module._read_history(fake)


class BootstrapAndReadinessTests(unittest.TestCase):
    def test_bootstrap_allowlist_contains_only_declared_three_host_mirrors(self):
        generated = [path for path in module.BOOTSTRAP_PATH_ALLOWLIST if path.startswith("dist/")]
        self.assertEqual(len(generated), 21)
        for host in ("antigravity", "claude", "openai"):
            for relative in (
                    "docs/design/runtime-design.md", "docs/design/workflow-design.md",
                    "docs/specs/runtime-spec.md", "docs/specs/workflow-spec.md",
                    "runtime/p_ases/cli.py", "runtime/p_ases/phase_epoch_rebaseline.py",
                    "runtime/p_ases/phase_rework.py"):
                self.assertIn(f"dist/{host}/{relative}", generated)
        self.assertEqual(list(module.AUTHORIZATION["bootstrap_path_allowlist"]),
                         list(module.BOOTSTRAP_PATH_ALLOWLIST))

    def test_bootstrap_commit_path_allowlist_is_enforced_per_commit(self):
        first, second = "1" * 40, "2" * 40
        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=f"{first}\n{second}\n"), \
                patch.object(module, "commit_parents_sha40", side_effect=[(module.BASELINE_HEAD,), (first,)]), \
                patch.object(module, "changed_paths_between", return_value=("runtime/p_ases/cli.py",)):
            module._verify_commit_set(Path("/tmp/repo"), second, module.BOOTSTRAP_PATH_ALLOWLIST)

        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=first), \
                patch.object(module, "commit_parents_sha40", return_value=(module.BASELINE_HEAD,)), \
                patch.object(module, "changed_paths_between", return_value=("runtime/p_ases/github.py",)):
            with self.assertRaisesRegex(module.PhaseReworkError, "outside the exact allowlist"):
                module._verify_commit_set(Path("/tmp/repo"), first, module.BOOTSTRAP_PATH_ALLOWLIST)

    def test_readiness_is_read_from_the_bound_worktree_and_exact_subject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = live_subject(root)
            result = readiness(root)
            module._validate_readiness(result, current)
            stale_head = readiness(root, "f" * 40)
            with self.assertRaisesRegex(module.PhaseReworkError, "stale or bound"):
                module._validate_readiness(stale_head, current)

    def test_intent_and_applied_preserve_exact_readiness_and_phase_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, result = intent_record(root)
            current = live_subject(root)
            module._validate_intent(intent, current, result)
            payload = module._applied_payload(intent)
            body = module._record_body(module.APPLIED_SCHEMA, payload)
            applied = module.PhaseReworkRecord(
                102, module.APPLIED_SCHEMA, payload, body, module.OWNER_ID, payload["applied_at"],
            )
            module._validate_applied(applied, intent, current)
            self.assertEqual(payload["readiness_sha256"], result.sha256)
            self.assertEqual(payload["active_epoch_id"], module.ACTIVE_EPOCH_ID)


class OneShotWriteTests(unittest.TestCase):
    def _run_label_update(self, root: Path, *, apply_then_lose_response: bool) -> tuple[int, bool]:
        intent, _result = intent_record(root)
        issue_before = {"body": "fixed", "state": "open"}
        issue_after = {"body": "fixed", "state": "open"}
        labels_before = tuple(sorted(module.LABELS_BEFORE))
        labels_after = tuple(sorted(module.LABELS_AFTER))

        class FakeGitHub:
            writes = 0

            def replace_issue_labels(self, _number: int, _labels: list[str]) -> None:
                self.writes += 1
                if apply_then_lose_response:
                    raise GitHubError("connection closed after server applied request")
                raise GitHubError("connection failed before server applied request")

        github = FakeGitHub()
        issue_reads = [(issue_after, labels_after)] if apply_then_lose_response else [
            (issue_before, labels_before),
        ]
        current = live_subject(root, labels=labels_before)
        current = module._Live(**{**current.__dict__, "issue": issue_before})
        with patch.object(module, "_live", return_value=current), \
                patch.object(module, "_validate_intent"), \
                patch.object(module, "_validate_recorded_readiness"), \
                patch.object(module, "_user_review_absent"), \
                patch.object(module, "_issue", side_effect=issue_reads):
            if apply_then_lose_response:
                module._replace_labels_once(github, root, intent)
                return github.writes, True
            with self.assertRaisesRegex(module.PhaseReworkError, "retry is prohibited"):
                module._replace_labels_once(github, root, intent)
            with patch.object(module, "_live", return_value=current), \
                    patch.object(module, "_validate_intent"), \
                    patch.object(module, "_validate_recorded_readiness"), \
                    patch.object(module, "_user_review_absent"), \
                    patch.object(module, "_issue", return_value=(issue_before, labels_before)):
                with self.assertRaisesRegex(module.PhaseReworkError, "previously attempted"):
                    module._replace_labels_once(github, root, intent)
            return github.writes, False

    def test_lost_label_put_response_is_never_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            writes, readback_confirmed = self._run_label_update(
                Path(temporary), apply_then_lose_response=True,
            )
            self.assertEqual(writes, 1)
            self.assertTrue(readback_confirmed)

    def test_before_state_after_lost_label_put_blocks_future_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            writes, readback_confirmed = self._run_label_update(
                Path(temporary), apply_then_lose_response=False,
            )
            self.assertEqual(writes, 1)
            self.assertFalse(readback_confirmed)


class ActiveGenerationTests(unittest.TestCase):
    def test_applied_phase_generation_survives_valid_descendant_commits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _result = intent_record(root)
            payload = module._applied_payload(intent)
            applied = module.PhaseReworkRecord(
                102, module.APPLIED_SCHEMA, payload,
                module._record_body(module.APPLIED_SCHEMA, payload),
                module.OWNER_ID, payload["applied_at"],
            )
            current_adc = live_subject(root).current_adc
            issue = {"labels": [{"name": label} for label in module.LABELS_AFTER]}
            with patch.object(module, "_read_history", return_value=(intent, applied)), \
                    patch.object(module, "parse_authorization", return_value=(module.AUTHORIZATION, "c" * 64)), \
                    patch.object(module, "head_sha40", return_value="f" * 40), \
                    patch.object(module, "_pr", return_value={}), \
                    patch.object(module, "is_ancestor", return_value=True), \
                    patch.object(module, "current_branch", return_value=module.BRANCH_REF):
                self.assertEqual(
                    module.active_phase_generation_for_epoch(
                        SimpleNamespace(), root, current_adc, SimpleNamespace(), issue,
                    ),
                    (applied.comment_id, applied.body_sha256),
                )

    def test_incomplete_intent_blocks_the_old_phase_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _result = intent_record(root)
            current_adc = live_subject(root).current_adc
            issue = {"labels": [{"name": label} for label in module.LABELS_BEFORE]}
            with patch.object(module, "_read_history", return_value=(intent,)), \
                    patch.object(module, "parse_authorization", return_value=(module.AUTHORIZATION, "c" * 64)), \
                    patch.object(module, "head_sha40", return_value="e" * 40), \
                    patch.object(module, "_pr", return_value={}), \
                    patch.object(module, "is_ancestor", return_value=True):
                with self.assertRaisesRegex(module.PhaseReworkError, "incomplete Intent"):
                    module.active_phase_generation_for_epoch(
                        SimpleNamespace(), root, current_adc, SimpleNamespace(), issue,
                    )


if __name__ == "__main__":
    unittest.main()
