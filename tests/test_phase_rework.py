from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.delivery import ReadinessResult, readiness_path, write_readiness  # noqa: E402
from p_ases.checkpoint import (
    PRBinding, WorkCheckpoint, checkpoint_path, read_pr_binding,
    write_checkpoint, write_pr_binding,
)  # noqa: E402
from p_ases.evidence_store import VerificationSubject  # noqa: E402
from p_ases.github import GitHubError  # noqa: E402
from p_ases import work as work_module  # noqa: E402
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


def verified_contract(pointer_id: int, digest: str, byte_length: int,
                      repository: str, content: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        pointer=SimpleNamespace(comment_id=pointer_id, state="approved", sha256=digest),
        contract=SimpleNamespace(
            sha256=digest, byte_length=byte_length, repository=repository, content=content,
        ),
    )


def marker_contract(schema: str, authorization: dict, predecessor_id: int,
                    predecessor_sha: str, comment_id: int, digest: str,
                    byte_length: int) -> SimpleNamespace:
    raw = json.dumps(
        authorization, sort_keys=schema != module.RECOVERY_AUTH_SCHEMA,
        separators=(",", ":"),
    )
    text = (
        f"Predecessor ADC: Issue #71 comment #{predecessor_id}, SHA-256 {predecessor_sha}\n\n"
        f"<!-- {schema}\n{raw}\n-->\n"
    )
    content = text.encode()
    if len(content) > byte_length:
        raise AssertionError("marker fixture exceeds pinned contract byte length")
    content += b" " * (byte_length - len(content))
    return verified_contract(comment_id, digest, byte_length, module.REPOSITORY, content)


def recovery_fixture(root: Path, *, labels: tuple[str, ...] | None = None,
                     current_head: str = "f" * 40):
    intent, original_readiness = intent_record(
        root, head="4185a510054a2a8781659191c1a48178336f8571",
    )
    body = module._record_body(module.INTENT_SCHEMA, intent.payload)
    intent = module.PhaseReworkRecord(
        module.RECOVERY_AUTHORIZATION["intent_comment_id"], intent.schema,
        intent.payload, body, module.OWNER_ID, intent.created_at,
    )
    recovery_authorization = dict(module.RECOVERY_AUTHORIZATION)
    recovery_authorization.update({
        "intent_comment_id": intent.comment_id,
        "intent_body_sha256": intent.body_sha256,
        "intent_readiness_sha256": original_readiness.sha256,
        "intent_readiness_subject_sha256": original_readiness.subject.sha256,
        "intent_attempt_payload_sha256": hashlib.sha256(
            module._canonical(intent.payload).encode()
        ).hexdigest(),
    })
    module._write_attempt_once(root, "intent", intent.payload)
    old = live_subject(
        root, head="4185a510054a2a8781659191c1a48178336f8571",
        labels=tuple(sorted(module.LABELS_BEFORE)),
    )
    current_adc = SimpleNamespace(
        pointer=SimpleNamespace(comment_id=module.RECOVERY_ADC_COMMENT_ID, state="approved"),
        contract=SimpleNamespace(sha256=module.RECOVERY_ADC_SHA256),
    )
    live = module._Live(
        current_adc=current_adc,
        epoch=SimpleNamespace(),
        issue={"number": 71, "body": "fixed", "state": "open"},
        labels=labels or tuple(sorted(module.LABELS_BEFORE)),
        branch_ref=module.BRANCH_REF,
        head_sha40=current_head,
        pr={},
        executor_user_id=module.OWNER_ID,
        authorization_sha256=old.authorization_sha256,
        root=root,
        recovery_authorization=recovery_authorization,
        recovery_authorization_sha256="d" * 64,
    )
    return intent, original_readiness, live


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

    def test_exact_recovery_marker_bytes_bind_the_pending_intent(self):
        verified = marker_contract(
            module.RECOVERY_AUTH_SCHEMA, module.RECOVERY_AUTHORIZATION,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256,
            module.RECOVERY_ADC_COMMENT_ID, module.RECOVERY_ADC_SHA256,
            module.RECOVERY_ADC_BYTES,
        )
        payload, marker_sha = module.parse_authorization(verified)
        self.assertEqual(payload, module.RECOVERY_AUTHORIZATION)
        self.assertEqual(len(marker_sha), 64)

        wrong = dict(module.RECOVERY_AUTHORIZATION)
        wrong["intent_comment_id"] += 1
        invalid = marker_contract(
            module.RECOVERY_AUTH_SCHEMA, wrong,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256,
            module.RECOVERY_ADC_COMMENT_ID, module.RECOVERY_ADC_SHA256,
            module.RECOVERY_ADC_BYTES,
        )
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved marker"):
            module.parse_authorization(invalid)

    def test_recovery_authorization_requires_complete_three_generation_chain(self):
        predecessor = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=module.PREDECESSOR_ADC_COMMENT_ID,
                                    state="approved", sha256=module.PREDECESSOR_ADC_SHA256),
            contract=SimpleNamespace(sha256=module.PREDECESSOR_ADC_SHA256),
        )
        old = marker_contract(
            module.AUTH_SCHEMA, module.AUTHORIZATION,
            module.PREDECESSOR_ADC_COMMENT_ID, module.PREDECESSOR_ADC_SHA256,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256, module.REWORK_ADC_BYTES,
        )
        current = marker_contract(
            module.RECOVERY_AUTH_SCHEMA, module.RECOVERY_AUTHORIZATION,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256,
            module.RECOVERY_ADC_COMMENT_ID, module.RECOVERY_ADC_SHA256, module.RECOVERY_ADC_BYTES,
        )
        with patch.object(module, "verify_adc_forward_generations", return_value=(predecessor, old, current)):
            authorization, authorization_sha, recovery, recovery_sha = module._authorization_context(
                SimpleNamespace(), current,
            )
        self.assertEqual(authorization, module.AUTHORIZATION)
        self.assertEqual(recovery, module.RECOVERY_AUTHORIZATION)
        self.assertEqual(len(authorization_sha), 64)
        self.assertEqual(len(recovery_sha), 64)

        with patch.object(module, "verify_adc_forward_generations", return_value=(predecessor, current)), \
                self.assertRaisesRegex(module.PhaseReworkError, "complete exact approved successor chain"):
            module._authorization_context(SimpleNamespace(), current)


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

    def test_recovery_commit_is_exactly_one_descendant_and_uses_its_narrow_allowlist(self):
        commit = "f" * 40
        authorization = module.RECOVERY_AUTHORIZATION
        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=commit), \
                patch.object(module, "commit_parents_sha40", return_value=(authorization["pre_recovery_head_sha40"],)), \
                patch.object(module, "changed_paths_between", return_value=("runtime/p_ases/phase_rework.py",)):
            module._verify_recovery_commit_set(Path("/tmp/repo"), commit, authorization)

        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=f"{commit}\n{'e' * 40}"), \
                self.assertRaisesRegex(module.PhaseReworkError, "exactly one authorized descendant"):
            module._verify_recovery_commit_set(Path("/tmp/repo"), "e" * 40, authorization)

        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=commit), \
                patch.object(module, "commit_parents_sha40", return_value=(authorization["pre_recovery_head_sha40"],)), \
                patch.object(module, "changed_paths_between", return_value=("runtime/p_ases/github.py",)), \
                self.assertRaisesRegex(module.PhaseReworkError, "outside its exact allowlist"):
            module._verify_recovery_commit_set(Path("/tmp/repo"), commit, authorization)

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
    def test_intent_prewrite_live_head_drift_blocks_before_marker_or_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = readiness(root)
            initial = live_subject(root)
            drifted = live_subject(root, head="f" * 40)

            class FakeGitHub:
                repo = module.REPOSITORY
                posts = 0

                def create_issue_comment(self, _issue: int, _body: str) -> dict:
                    self.posts += 1
                    return {"id": 201}

            github = FakeGitHub()
            with patch.object(module, "_live", side_effect=[initial, drifted]), \
                    patch.object(module, "_read_history", return_value=()), \
                    patch.object(module, "_user_review_absent"), \
                    self.assertRaisesRegex(module.PhaseReworkError, "stale or bound"):
                module.apply_issue71_phase_rework(
                    github, root, 71, readiness_factory=lambda: result,
                )

            self.assertEqual(github.posts, 0)
            self.assertFalse(module._record_path(root, "intent").exists())

    def test_intent_prewrite_readiness_drift_blocks_before_marker_or_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial_readiness = readiness(root)
            changed_readiness = ReadinessResult(
                "PASS", initial_readiness.subject, (), (), "c" * 64,
            ).validate()
            write_readiness(readiness_path(root, changed_readiness), changed_readiness)
            initial = live_subject(root)

            class FakeGitHub:
                repo = module.REPOSITORY
                posts = 0

                def create_issue_comment(self, _issue: int, _body: str) -> dict:
                    self.posts += 1
                    return {"id": 202}

            github = FakeGitHub()
            with patch.object(module, "_live", return_value=initial), \
                    patch.object(module, "_read_history", return_value=()), \
                    patch.object(module, "_user_review_absent"), \
                    self.assertRaisesRegex(module.PhaseReworkError, "Readiness changed"):
                module.apply_issue71_phase_rework(
                    github, root, 71,
                    readiness_factory=Mock(side_effect=[initial_readiness, changed_readiness]),
                )

            self.assertEqual(github.posts, 0)
            self.assertFalse(module._record_path(root, "intent").exists())

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


class PendingRecoveryTests(unittest.TestCase):
    def _fixture(self, root: Path, *, labels: tuple[str, ...] | None = None):
        intent, saved_readiness, live = recovery_fixture(root, labels=labels)
        with patch.object(module, "is_ancestor", return_value=True):
            module._validate_recovery_intent(intent, live, root)
        return intent, saved_readiness, live

    def _seed_pr_binding_history(self, root: Path) -> list[tuple[Path, PRBinding]]:
        rows = [
            PRBinding(
                module.REPOSITORY, module.ISSUE_NUMBER, module.EPOCH_ORIGIN_ADC_COMMENT_ID,
                module.EPOCH_ORIGIN_ADC_SHA256, module.BASE_SHA40, module.BRANCH_REF,
                module.PR_NUMBER, module.BASELINE_HEAD,
                execution_epoch_sha256=module.ACTIVE_EPOCH_SHA256,
            ).validate(),
            PRBinding(
                module.REPOSITORY, module.ISSUE_NUMBER, module.REWORK_ADC_COMMENT_ID,
                module.REWORK_ADC_SHA256, module.BASE_SHA40, module.BRANCH_REF,
                module.PR_NUMBER, "218a810a5d016ea99143c5ec5757db9eaa8fa00f",
                execution_epoch_sha256=module.ACTIVE_EPOCH_SHA256,
            ).validate(),
            PRBinding(
                module.REPOSITORY, module.ISSUE_NUMBER, module.REWORK_ADC_COMMENT_ID,
                module.REWORK_ADC_SHA256, module.BASE_SHA40, module.BRANCH_REF,
                module.PR_NUMBER, module.RECOVERY_AUTHORIZATION["pre_recovery_head_sha40"],
                execution_epoch_sha256=module.ACTIVE_EPOCH_SHA256,
            ).validate(),
        ]
        paths: list[tuple[Path, PRBinding]] = []
        for index, binding in enumerate(rows, start=1):
            path = root / ".p_ases" / "state" / "71" / f"pr-binding-{index:06d}.json"
            write_pr_binding(path, binding)
            checkpoint = WorkCheckpoint(
                None, binding.pr_head_sha40, True, "pr", tuple(sorted((
                    ("execution-epoch", module.ACTIVE_EPOCH_SHA256),
                    ("pr-binding", binding.sha256),
                ))), index, execution_epoch_sha256=module.ACTIVE_EPOCH_SHA256,
            ).validate()
            write_checkpoint(checkpoint_path(root, 71, index), checkpoint)
            paths.append((path, binding))
        return paths

    def test_recovery_pr_rebind_is_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)
            body = "preserved PR body"
            live = module._Live(**{
                **live.__dict__,
                "epoch": SimpleNamespace(sha256=module.ACTIVE_EPOCH_SHA256),
                "pr": {"title": module.PR_TITLE, "body": body},
            })
            paths = self._seed_pr_binding_history(root)

            def binding_history(*_args, **_kwargs):
                directory = root / ".p_ases" / "state" / "71"
                return [(path, read_pr_binding(path)) for path in sorted(directory.glob("pr-binding-*.json"))]

            class FakeGitHub:
                repo = module.REPOSITORY

            github = FakeGitHub()
            with patch.object(module, "PR_BODY_SHA256", hashlib.sha256(body.encode()).hexdigest()), \
                    patch.object(module, "_live", side_effect=[live, live, live, live, live, live]), \
                    patch.object(module, "_read_history", return_value=(intent,)), \
                    patch.object(module, "_active_rework_records", return_value=(intent, None)), \
                    patch.object(module, "_validate_recovery_intent"), \
                    patch.object(module, "is_ancestor", return_value=True), \
                    patch.object(module, "current_branch", return_value=module.BRANCH_REF), \
                    patch.object(module, "head_sha40", return_value=live.head_sha40), \
                    patch.object(module, "worktree_clean", return_value=True), \
                    patch.object(module, "remote_branch_sha", side_effect=lambda _root, ref:
                                 module.BASE_SHA40 if ref == module.BASE_REF else live.head_sha40), \
                    patch.object(work_module, "read_pr_binding_history", side_effect=binding_history), \
                    patch.object(work_module, "_verify_pr_binding_successor") as verify_successor:
                result = module.rebind_issue71_recovery_pr(github, root, 71)
                self.assertEqual(result["status"], "PR_BOUND")
                self.assertEqual(result["github_writes"], 0)
                self.assertEqual(result["head_sha40"], live.head_sha40)
                self.assertEqual(result["pr_binding_path"], str(root / ".p_ases" / "state" / "71"
                                                                  / "pr-binding-000004.json"))
                binding_after = read_pr_binding(Path(result["pr_binding_path"]))
                self.assertEqual(binding_after.adc_comment_id, module.RECOVERY_ADC_COMMENT_ID)
                self.assertEqual(binding_after.pr_head_sha40, live.head_sha40)
                self.assertEqual(verify_successor.call_count, 1)
                self.assertEqual(len(paths), 3)
                again = module.rebind_issue71_recovery_pr(github, root, 71)
                self.assertEqual(again["pr_binding_sha256"], result["pr_binding_sha256"])
                self.assertEqual(again["checkpoint_sha256"], result["checkpoint_sha256"])
                self.assertEqual(len(list((root / ".p_ases" / "state" / "71").glob("pr-binding-*.json"))), 4)
                self.assertEqual(len(list((root / ".p_ases" / "state" / "71").glob("checkpoint-*.json"))), 4)

    def test_recovery_pr_rebind_blocks_changed_pr_metadata_before_append(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)
            live = module._Live(**{
                **live.__dict__,
                "epoch": SimpleNamespace(sha256=module.ACTIVE_EPOCH_SHA256),
                "pr": {"title": module.PR_TITLE, "body": "changed PR body"},
            })
            self._seed_pr_binding_history(root)

            class FakeGitHub:
                repo = module.REPOSITORY

            with patch.object(module, "_live", return_value=live), \
                    patch.object(module, "_read_history", return_value=(intent,)), \
                    patch.object(module, "_active_rework_records", return_value=(intent, None)), \
                    patch.object(module, "_validate_recovery_intent"), \
                    patch.object(module, "PR_BODY_SHA256", hashlib.sha256(b"expected").hexdigest()), \
                    self.assertRaisesRegex(module.PhaseReworkError, "title or body differs"):
                module.rebind_issue71_recovery_pr(FakeGitHub(), root, 71)
            self.assertFalse((root / ".p_ases" / "state" / "71" / "pr-binding-000004.json").exists())

    def test_pending_phase_rework_without_gate_inputs_only_rebinds_pr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)

            class FakeGitHub:
                repo = module.REPOSITORY
                label_writes = 0
                comment_writes = 0

                def replace_issue_labels(self, *_args):
                    self.label_writes += 1

                def create_issue_comment(self, *_args):
                    self.comment_writes += 1

            github = FakeGitHub()
            expected = {"status": "PR_BOUND", "github_writes": 0}
            with patch.object(module, "_live", return_value=live), \
                    patch.object(module, "_read_history", return_value=(intent,)), \
                    patch.object(module, "_active_rework_records", return_value=(intent, None)), \
                    patch.object(module, "_validate_recovery_intent"), \
                    patch.object(module, "_read_exact_attempt_marker", return_value=False), \
                    patch.object(module, "rebind_issue71_recovery_pr", return_value=expected) as rebind:
                result = module.apply_issue71_phase_rework(github, root, 71)
            self.assertEqual(result, expected)
            rebind.assert_called_once_with(github, root.resolve(), 71)
            self.assertEqual(github.label_writes, 0)
            self.assertEqual(github.comment_writes, 0)

    def test_recovery_reuses_exact_intent_readiness_and_local_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, saved, live = self._fixture(root)
            self.assertEqual(intent.comment_id, live.recovery_authorization["intent_comment_id"])
            self.assertEqual(intent.payload["readiness_sha256"], saved.sha256)
            self.assertEqual(intent.payload["readiness_subject_sha256"], saved.subject.sha256)

            wrong_id = module.PhaseReworkRecord(
                intent.comment_id + 1, intent.schema, intent.payload, intent.body,
                intent.actor_id, intent.created_at,
            )
            with patch.object(module, "is_ancestor", return_value=True), \
                    self.assertRaisesRegex(module.PhaseReworkError, "exact Recovery ADC tuple"):
                module._validate_recovery_intent(wrong_id, live, root)

            bad_payload = dict(intent.payload)
            bad_payload["readiness_sha256"] = "0" * 64
            bad_record = module.PhaseReworkRecord(
                intent.comment_id, intent.schema, bad_payload,
                module._record_body(module.INTENT_SCHEMA, bad_payload),
                intent.actor_id, intent.created_at,
            )
            with patch.object(module, "is_ancestor", return_value=True), \
                    self.assertRaisesRegex(module.PhaseReworkError, "exact Recovery ADC tuple"):
                module._validate_recovery_intent(bad_record, live, root)

            module._record_path(root, "intent").write_text("{}\n", encoding="utf-8")
            with patch.object(module, "is_ancestor", return_value=True), \
                    self.assertRaisesRegex(module.PhaseReworkError, "attempt marker differs"):
                module._validate_recovery_intent(intent, live, root)

    def test_recovery_rejects_wrong_current_adc_before_continuation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)
            wrong_adc = SimpleNamespace(
                pointer=SimpleNamespace(comment_id=module.REWORK_ADC_COMMENT_ID, state="approved"),
                contract=SimpleNamespace(sha256=module.REWORK_ADC_SHA256),
            )
            drifted = module._Live(**{**live.__dict__, "current_adc": wrong_adc})
            with patch.object(module, "is_ancestor", return_value=True), \
                    self.assertRaisesRegex(module.PhaseReworkError, "does not authorize pending Intent"):
                module._validate_recovery_intent(intent, drifted, root)

    def test_recovery_rejects_wrong_current_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)
            drifted = module._Live(**{**live.__dict__, "head_sha40": "0" * 40})
            with patch.object(module, "is_ancestor", side_effect=[True, False]), \
                    self.assertRaisesRegex(module.PhaseReworkError, "authorized branch ancestry"):
                module._validate_recovery_intent(intent, drifted, root)

    def test_recovery_rejects_wrong_authenticated_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)
            drifted = module._Live(**{**live.__dict__, "executor_user_id": module.OWNER_ID + 1})
            with patch.object(module, "is_ancestor", return_value=True), \
                    self.assertRaisesRegex(module.PhaseReworkError, "executor_user_id"):
                module._validate_recovery_intent(intent, drifted, root)

    def test_recovery_rejects_pr_base_or_head_drift(self):
        head = "f" * 40
        wrong_pr = {
            "number": module.PR_NUMBER, "state": "open", "draft": False, "merged_at": None,
            "base": {"ref": module.PR_BASE_REF, "sha": "0" * 40,
                     "repo": {"id": module.REPOSITORY_ID}},
            "head": {"ref": module.BRANCH_REF, "sha": head,
                     "repo": {"id": module.REPOSITORY_ID, "full_name": module.REPOSITORY}},
        }

        class FakeGitHub:
            def pull_request(self, _number: int) -> dict:
                return wrong_pr

        with self.assertRaisesRegex(module.PhaseReworkError, "exact open, non-draft bootstrap subject"):
            module._pr(FakeGitHub(), head)

    def test_recovery_rejects_unexpected_labels_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)
            drifted = module._Live(**{
                **live.__dict__, "labels": tuple(sorted((*module.LABELS_BEFORE, "unexpected"))),
            })

            class FakeGitHub:
                repo = module.REPOSITORY
                label_writes = 0
                comment_writes = 0

                def replace_issue_labels(self, _number: int, _labels: list[str]) -> None:
                    self.label_writes += 1

                def create_issue_comment(self, _number: int, _body: str) -> dict:
                    self.comment_writes += 1
                    return {"id": 203}

            github = FakeGitHub()
            with patch.object(module, "_live", return_value=drifted), \
                    patch.object(module, "_read_history", return_value=(intent,)), \
                    patch.object(module, "is_ancestor", return_value=True), \
                    self.assertRaisesRegex(module.PhaseReworkError, "match neither exact state"):
                module.apply_issue71_phase_rework(github, root, 71)
            self.assertEqual(github.label_writes, 0)
            self.assertEqual(github.comment_writes, 0)
            self.assertFalse(module._record_path(root, "labels").exists())

    def test_recovery_lost_put_response_after_server_apply_is_readback_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)

            class FakeGitHub:
                repo = module.REPOSITORY
                label_writes = 0

                def replace_issue_labels(self, _number: int, _labels: list[str]) -> None:
                    self.label_writes += 1
                    raise GitHubError("connection closed after server applied request")

            github = FakeGitHub()
            after = ({"body": "fixed", "state": "open"}, tuple(sorted(module.LABELS_AFTER)))
            with patch.object(module, "_live", return_value=live), \
                    patch.object(module, "_issue", return_value=after), \
                    patch.object(module, "is_ancestor", return_value=True):
                module._replace_labels_once(github, root, intent)
            self.assertEqual(github.label_writes, 1)
            self.assertTrue(module._record_path(root, "labels").is_file())

    def test_recovery_lost_put_response_with_before_state_never_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)

            class FakeGitHub:
                repo = module.REPOSITORY
                label_writes = 0

                def replace_issue_labels(self, _number: int, _labels: list[str]) -> None:
                    self.label_writes += 1
                    raise GitHubError("connection failed before server applied request")

            github = FakeGitHub()
            before = ({"body": "fixed", "state": "open"}, tuple(sorted(module.LABELS_BEFORE)))
            with patch.object(module, "_live", return_value=live), \
                    patch.object(module, "_issue", return_value=before), \
                    patch.object(module, "is_ancestor", return_value=True):
                with self.assertRaisesRegex(module.PhaseReworkError, "retry is prohibited"):
                    module._replace_labels_once(github, root, intent)
                with self.assertRaisesRegex(module.PhaseReworkError, "previously attempted"):
                    module._replace_labels_once(github, root, intent)
            self.assertEqual(github.label_writes, 1)
            self.assertTrue(module._record_path(root, "labels").is_file())

    def _apply_pending(self, root: Path, *, after_labels: bool = False,
                       prior_label_attempt: bool = False) -> tuple[Mock, Mock, dict]:
        labels = tuple(sorted(module.LABELS_AFTER if after_labels else module.LABELS_BEFORE))
        intent, _saved, live = self._fixture(root, labels=labels)
        if prior_label_attempt:
            payload = module._recovery_label_attempt_payload(intent)
            module._write_attempt_once(root, "labels", payload)
        issue_after = ({"body": "fixed", "state": "open"}, tuple(sorted(module.LABELS_AFTER)))

        class FakeGitHub:
            repo = module.REPOSITORY

            def __init__(self):
                self.label_writes = 0
                self.comment_writes = 0

            def replace_issue_labels(self, _issue_number: int, _labels: list[str]) -> None:
                self.label_writes += 1

            def create_issue_comment(self, _issue_number: int, _body: str) -> dict:
                self.comment_writes += 1
                return {"id": 202}

        github = FakeGitHub()
        applied_payload = module._applied_payload(intent)
        applied = module.PhaseReworkRecord(
            202, module.APPLIED_SCHEMA, applied_payload,
            module._record_body(module.APPLIED_SCHEMA, applied_payload),
            module.OWNER_ID, applied_payload["applied_at"],
        )
        live_reads = [live, live] if not after_labels else [live]
        with patch.object(module, "_live", side_effect=live_reads), \
                patch.object(module, "_read_history", return_value=(intent,)), \
                patch.object(module, "_issue", return_value=issue_after), \
                patch.object(module, "_check_labels_after"), \
                patch.object(module, "_write_applied", return_value=applied), \
                patch.object(module, "_verify_recovery_pr_binding", return_value=(None, None, None)), \
                patch.object(module, "is_ancestor", return_value=True):
            readiness_factory = Mock(side_effect=AssertionError("Recovery must not recompute Readiness"))
            result = module.apply_issue71_phase_rework(
                github, root, 71, readiness_factory=readiness_factory,
            )
        readiness_factory.assert_not_called()
        self.assertEqual(github.comment_writes, 0)
        return github, readiness_factory, result

    def test_before_labels_without_marker_continues_once_without_new_intent_or_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            github, _factory, result = self._apply_pending(Path(temporary))
            self.assertEqual(result["status"], "RECOVERED")
            self.assertEqual(result["label_write_count"], 1)
            self.assertEqual(github.label_writes, 1)

    def test_marker_present_before_labels_blocks_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)
            module._write_attempt_once(root, "labels", module._recovery_label_attempt_payload(intent))

            class FakeGitHub:
                repo = module.REPOSITORY
                label_writes = 0

                def replace_issue_labels(self, _issue_number: int, _labels: list[str]) -> None:
                    self.label_writes += 1

            with patch.object(module, "_live", return_value=live), \
                    patch.object(module, "_read_history", return_value=(intent,)), \
                    patch.object(module, "is_ancestor", return_value=True), \
                    self.assertRaisesRegex(module.PhaseReworkError, "previously attempted"):
                module.apply_issue71_phase_rework(FakeGitHub(), root, 71)

    def test_after_labels_with_marker_finishes_applied_without_put(self):
        with tempfile.TemporaryDirectory() as temporary:
            github, _factory, result = self._apply_pending(
                Path(temporary), after_labels=True, prior_label_attempt=True,
            )
            self.assertEqual(result["status"], "RECOVERED")
            self.assertEqual(result["label_write_count"], 0)
            self.assertEqual(github.label_writes, 0)

    def test_after_labels_without_marker_cannot_be_adopted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _intent, _saved, live = self._fixture(
                root, labels=tuple(sorted(module.LABELS_AFTER)),
            )

            class FakeGitHub:
                repo = module.REPOSITORY
                label_writes = 0

                def replace_issue_labels(self, _issue_number: int, _labels: list[str]) -> None:
                    self.label_writes += 1

            with patch.object(module, "_live", return_value=live), \
                    patch.object(module, "_read_history", return_value=(_intent,)), \
                    patch.object(module, "is_ancestor", return_value=True), \
                    self.assertRaisesRegex(module.PhaseReworkError, "after-label state lacks"):
                module.apply_issue71_phase_rework(FakeGitHub(), root, 71)

    def test_applied_generation_is_active_after_recovery_adc_successor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _saved, live = self._fixture(root)
            label_payload = module._recovery_label_attempt_payload(intent)
            module._write_attempt_once(root, "labels", label_payload)
            applied_payload = module._applied_payload(intent)
            applied = module.PhaseReworkRecord(
                intent.comment_id + 1, module.APPLIED_SCHEMA, applied_payload,
                module._record_body(module.APPLIED_SCHEMA, applied_payload),
                module.OWNER_ID, applied_payload["applied_at"],
            )
            issue = {"labels": [{"name": label} for label in module.LABELS_AFTER]}
            with patch.object(module, "_authorization_context",
                              return_value=(module.AUTHORIZATION, live.authorization_sha256,
                                            live.recovery_authorization, live.recovery_authorization_sha256)), \
                    patch.object(module, "_read_history", return_value=(intent, applied)), \
                    patch.object(module, "head_sha40", return_value=live.head_sha40), \
                    patch.object(module, "_pr", return_value={}), \
                    patch.object(module, "is_ancestor", return_value=True), \
                    patch.object(module, "current_branch", return_value=module.BRANCH_REF):
                self.assertEqual(
                    module.active_phase_generation_for_epoch(
                        SimpleNamespace(), root, live.current_adc, SimpleNamespace(), issue,
                    ),
                    (applied.comment_id, applied.body_sha256),
                )


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
                    patch.object(module, "_authorization_context",
                                 return_value=(module.AUTHORIZATION, "c" * 64, None, None)), \
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
                    patch.object(module, "_authorization_context",
                                 return_value=(module.AUTHORIZATION, "c" * 64, None, None)), \
                    patch.object(module, "head_sha40", return_value="e" * 40), \
                    patch.object(module, "_pr", return_value={}), \
                    patch.object(module, "is_ancestor", return_value=True):
                with self.assertRaisesRegex(module.PhaseReworkError, "incomplete Intent"):
                    module.active_phase_generation_for_epoch(
                        SimpleNamespace(), root, current_adc, SimpleNamespace(), issue,
                    )


if __name__ == "__main__":
    unittest.main()
