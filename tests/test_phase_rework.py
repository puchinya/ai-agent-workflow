from __future__ import annotations

import hashlib
import base64
import json
import sys
import tempfile
import unittest
import zlib
from dataclasses import replace
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


def timestamp_recovery_contract(authorization: dict | None = None) -> SimpleNamespace:
    authorization = authorization or module.TIMESTAMP_RECOVERY_AUTHORIZATION
    raw = json.dumps(authorization, separators=(",", ":"))
    text = (
        f"Predecessor ADC: Issue #71 comment #{module.RECOVERY_ADC_COMMENT_ID}, "
        f"SHA-256 {module.RECOVERY_ADC_SHA256}\n\n"
        f"<!-- {module.TIMESTAMP_RECOVERY_AUTH_SCHEMA}\n{raw}\n-->\n"
    )
    content = text.encode("utf-8")
    return verified_contract(
        module.TIMESTAMP_RECOVERY_ADC_COMMENT_ID, hashlib.sha256(content).hexdigest(),
        len(content), module.REPOSITORY, content,
    )


def path_correction_contract() -> SimpleNamespace:
    text = (
        f"Predecessor ADC: Issue #71 comment #{module.TIMESTAMP_RECOVERY_ADC_COMMENT_ID}, "
        f"SHA-256 {module.TIMESTAMP_RECOVERY_ADC_SHA256}\n\n"
        f"{module.PATH_CORRECTION_ARTIFACT_IMPACT}\n"
    )
    content = text.encode("utf-8")
    content += b" " * (module.PATH_CORRECTION_ADC_BYTES - len(content))
    return verified_contract(
        module.PATH_CORRECTION_ADC_COMMENT_ID, module.PATH_CORRECTION_ADC_SHA256,
        module.PATH_CORRECTION_ADC_BYTES, module.REPOSITORY, content,
    )


def continuation_contract(authorization: dict | None = None,
                          *, predecessor_id: int | None = None,
                          predecessor_sha: str | None = None,
                          artifact_impact: str | None = None,
                          duplicate_marker: bool = False,
                          missing_marker: bool = False,
                          repository: str | None = None) -> SimpleNamespace:
    authorization = authorization or module.CONTINUATION_AUTHORIZATION
    predecessor_id = predecessor_id or module.PATH_CORRECTION_ADC_COMMENT_ID
    predecessor_sha = predecessor_sha or module.PATH_CORRECTION_ADC_SHA256
    impact = artifact_impact or module.CONTINUATION_ARTIFACT_IMPACT
    marker = (
        f"<!-- {module.CONTINUATION_AUTH_SCHEMA}\n"
        f"{module._canonical(authorization)}\n-->"
    )
    marker_section = "" if missing_marker else f"\n\n{marker}"
    if duplicate_marker:
        marker_section += f"\n{marker}"
    text = (
        f"Predecessor ADC: Issue #71 comment #{predecessor_id}, SHA-256 {predecessor_sha}\n\n"
        f"{impact}{marker_section}\n"
    )
    content = text.encode("utf-8")
    if len(content) > module.CONTINUATION_ADC_BYTES:
        raise AssertionError("continuation fixture exceeds pinned ADC byte length")
    content += b" " * (module.CONTINUATION_ADC_BYTES - len(content))
    return verified_contract(
        module.CONTINUATION_ADC_COMMENT_ID, module.CONTINUATION_ADC_SHA256,
        module.CONTINUATION_ADC_BYTES, repository or module.REPOSITORY, content,
    )


def traceability_source_correction_contract() -> SimpleNamespace:
    text = (
        f"Predecessor ADC: Issue #71 comment #{module.CONTINUATION_ADC_COMMENT_ID}, "
        f"SHA-256 {module.CONTINUATION_ADC_SHA256}\n\n"
    )
    content = text.encode("utf-8")
    content += b" " * (module.TRACEABILITY_CORRECTION_ADC_BYTES - len(content))
    return verified_contract(
        module.TRACEABILITY_CORRECTION_ADC_COMMENT_ID,
        module.TRACEABILITY_CORRECTION_ADC_SHA256,
        module.TRACEABILITY_CORRECTION_ADC_BYTES, module.REPOSITORY, content,
    )


def reader_continuation_contract(authorization: dict | None = None,
                                 *, predecessor_id: int | None = None,
                                 predecessor_sha: str | None = None,
                                 artifact_impact: str | None = None,
                                 duplicate_marker: bool = False,
                                 missing_marker: bool = False,
                                 repository: str | None = None) -> SimpleNamespace:
    authorization = authorization or module.READER_CONTINUATION_AUTHORIZATION
    predecessor_id = predecessor_id or module.TRACEABILITY_CORRECTION_ADC_COMMENT_ID
    predecessor_sha = predecessor_sha or module.TRACEABILITY_CORRECTION_ADC_SHA256
    impact = artifact_impact or module.READER_CONTINUATION_ARTIFACT_IMPACT
    marker = (
        f"<!-- {module.READER_CONTINUATION_AUTH_SCHEMA}\n"
        f"{module._canonical(authorization)}\n-->"
    )
    marker_section = "" if missing_marker else f"\n\n{marker}"
    if duplicate_marker:
        marker_section += f"\n{marker}"
    text = (
        f"Predecessor ADC: Issue #71 comment #{predecessor_id}, SHA-256 {predecessor_sha}\n\n"
        f"{impact}{marker_section}\n"
    )
    content = text.encode("utf-8")
    if len(content) > module.READER_CONTINUATION_ADC_BYTES:
        raise AssertionError("reader-continuation fixture exceeds pinned ADC byte length")
    content += b" " * (module.READER_CONTINUATION_ADC_BYTES - len(content))
    return verified_contract(
        module.READER_CONTINUATION_ADC_COMMENT_ID, module.READER_CONTINUATION_ADC_SHA256,
        module.READER_CONTINUATION_ADC_BYTES, repository or module.REPOSITORY, content,
    )


def execution_receipt_reader_continuation_contract(
    authorization: dict | None = None,
    *,
    predecessor_id: int | None = None,
    predecessor_sha: str | None = None,
    predecessor_sha_format: str = "inline",
    artifact_impact: str | None = None,
    duplicate_marker: bool = False,
    missing_marker: bool = False,
    repository: str | None = None,
) -> SimpleNamespace:
    authorization = authorization or module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION
    predecessor_id = predecessor_id or module.READER_CONTINUATION_ADC_COMMENT_ID
    predecessor_sha = predecessor_sha or module.READER_CONTINUATION_ADC_SHA256
    digest_forms = {
        "bare": predecessor_sha,
        "inline": f"`{predecessor_sha}`",
        "open": f"`{predecessor_sha}",
        "close": f"{predecessor_sha}`",
        "double": f"``{predecessor_sha}``",
    }
    declared_sha = digest_forms[predecessor_sha_format]
    impact = artifact_impact or module.EXECUTION_RECEIPT_READER_CONTINUATION_ARTIFACT_IMPACT
    marker = (
        f"<!-- {module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_SCHEMA}\n"
        f"{module._canonical(authorization)}\n-->"
    )
    marker_section = "" if missing_marker else f"\n\n{marker}"
    if duplicate_marker:
        marker_section += f"\n{marker}"
    text = (
        f"Predecessor ADC: Issue #71 comment #{predecessor_id}, SHA-256 {declared_sha}\n\n"
        f"{impact}{marker_section}\n"
    )
    content = text.encode("utf-8")
    if len(content) > module.EXECUTION_RECEIPT_READER_CONTINUATION_ADC_BYTES:
        raise AssertionError("execution-receipt reader fixture exceeds pinned ADC byte length")
    content += b" " * (module.EXECUTION_RECEIPT_READER_CONTINUATION_ADC_BYTES - len(content))
    return verified_contract(
        module.EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID,
        module.EXECUTION_RECEIPT_READER_CONTINUATION_ADC_SHA256,
        module.EXECUTION_RECEIPT_READER_CONTINUATION_ADC_BYTES,
        repository or module.REPOSITORY, content,
    )


def approved_history_reader_contract(
    authorization: dict | None = None,
    *,
    predecessor_id: int | None = None,
    predecessor_sha: str | None = None,
    artifact_impact: str | None = None,
    marker_json: str | None = None,
    duplicate_marker: bool = False,
    missing_marker: bool = False,
    repository: str | None = None,
) -> SimpleNamespace:
    authorization = authorization or module.APPROVED_HISTORY_READER_AUTHORIZATION
    predecessor_id = predecessor_id or authorization["predecessor_adc_comment_id"]
    predecessor_sha = predecessor_sha or authorization["predecessor_adc_sha256"]
    impact = artifact_impact or module.APPROVED_HISTORY_READER_ARTIFACT_IMPACT
    raw = marker_json or module._canonical(authorization)
    marker = (
        f"<!-- {module.APPROVED_HISTORY_READER_AUTH_SCHEMA}\n"
        f"{raw}\n-->"
    )
    marker_section = "" if missing_marker else f"\n\n{marker}"
    if duplicate_marker:
        marker_section += f"\n{marker}"
    text = (
        f"Predecessor ADC: Issue #71 comment #{predecessor_id}, "
        f"SHA-256 `{predecessor_sha}`\n\n{impact}{marker_section}\n"
    )
    content = text.encode("utf-8")
    if len(content) > module.APPROVED_HISTORY_READER_ADC_BYTES:
        raise AssertionError("approved-history reader fixture exceeds pinned ADC byte length")
    content += b" " * (module.APPROVED_HISTORY_READER_ADC_BYTES - len(content))
    return verified_contract(
        module.APPROVED_HISTORY_READER_ADC_COMMENT_ID,
        module.APPROVED_HISTORY_READER_ADC_SHA256,
        module.APPROVED_HISTORY_READER_ADC_BYTES,
        repository or module.REPOSITORY, content,
    )


def approved_history_chain(current: SimpleNamespace) -> tuple[SimpleNamespace, ...]:
    authorization = module.APPROVED_HISTORY_READER_AUTHORIZATION
    previous = authorization["history_predecessor_boundary"]
    rows = []
    for entry in authorization["approved_history"]:
        text = (
            f"Predecessor ADC: Issue #71 comment #{previous['comment_id']}, "
            f"SHA-256 {previous['sha256']}\n\n"
            "<!-- deliberately malformed historical authorization marker"
        ).encode("utf-8")
        content = text + b" " * (entry["byte_length"] - len(text))
        row = verified_contract(
            entry["comment_id"], entry["sha256"], entry["byte_length"],
            module.REPOSITORY, content,
        )
        rows.append(row)
        previous = entry
    rows.append(current)
    return tuple(rows)


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


class PostReworkLabelValidationTests(unittest.TestCase):
    def test_accepts_each_known_single_issue_lifecycle_phase(self):
        phases = (
            "phase:requirements", "phase:specification", "phase:design", "phase:ready",
            "phase:verification", "phase:execution", "phase:integration", "phase:user-review",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                module._validate_post_rework_labels(
                    tuple(sorted(("enhancement", "kind:single", phase)))
                )

    def test_rejects_unknown_or_duplicate_phases(self):
        invalid_labels = (
            ("enhancement", "kind:single", "phase:unknown"),
            ("enhancement", "kind:single", "phase:verification", "phase:execution"),
            ("enhancement", "kind:single", "phase:verification", "phase:verification"),
            ("enhancement", "kind:single", "phase:"),
        )
        for labels in invalid_labels:
            with self.subTest(labels=labels), self.assertRaises(module.PhaseReworkError):
                module._validate_post_rework_labels(tuple(sorted(labels)))

    def test_rejects_duplicate_or_mismatched_kinds_and_missing_enhancement(self):
        invalid_labels = (
            ("enhancement", "kind:single", "kind:single", "phase:verification"),
            ("enhancement", "kind:child", "phase:verification"),
            ("enhancement", "kind:single", "kind:child", "phase:verification"),
            ("kind:single", "phase:verification"),
        )
        for labels in invalid_labels:
            with self.subTest(labels=labels), self.assertRaises(module.PhaseReworkError):
                module._validate_post_rework_labels(tuple(sorted(labels)))


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
            authorization, authorization_sha, recovery, recovery_sha, timestamp, timestamp_sha, continuation, continuation_sha, reader, reader_sha, execution_reader, execution_reader_sha, _phase_authorization = module._authorization_context(
                SimpleNamespace(), current,
            )
        self.assertEqual(authorization, module.AUTHORIZATION)
        self.assertEqual(recovery, module.RECOVERY_AUTHORIZATION)
        self.assertIsNone(timestamp)
        self.assertIsNone(timestamp_sha)
        self.assertIsNone(continuation)
        self.assertIsNone(continuation_sha)
        self.assertIsNone(reader)
        self.assertIsNone(reader_sha)
        self.assertIsNone(execution_reader)
        self.assertIsNone(execution_reader_sha)
        self.assertEqual(len(authorization_sha), 64)
        self.assertEqual(len(recovery_sha), 64)

        with patch.object(module, "verify_adc_forward_generations", return_value=(predecessor, current)), \
                self.assertRaisesRegex(module.PhaseReworkError, "complete exact approved successor chain"):
            module._authorization_context(SimpleNamespace(), current)

    def test_exact_timestamp_recovery_marker_and_four_generation_chain(self):
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
        recovery = marker_contract(
            module.RECOVERY_AUTH_SCHEMA, module.RECOVERY_AUTHORIZATION,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256,
            module.RECOVERY_ADC_COMMENT_ID, module.RECOVERY_ADC_SHA256,
            module.RECOVERY_ADC_BYTES,
        )
        current = timestamp_recovery_contract()
        timestamp_sha = module.TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256
        marker_bytes = module.TIMESTAMP_RECOVERY_AUTH_MARKER_BYTES
        with patch.object(module, "TIMESTAMP_RECOVERY_ADC_SHA256", current.contract.sha256), \
                patch.object(module, "TIMESTAMP_RECOVERY_ADC_BYTES", current.contract.byte_length), \
                patch.object(module, "verify_adc_forward_generations",
                             return_value=(predecessor, old, recovery, current)):
            timestamp, parsed_sha = module.parse_timestamp_recovery_authorization(current)
            self.assertEqual(timestamp, module.TIMESTAMP_RECOVERY_AUTHORIZATION)
            self.assertEqual(parsed_sha, timestamp_sha)
            self.assertEqual(len(parsed_sha), 64)
            authorization, authorization_sha, recovery_auth, recovery_sha, timestamp_auth, _, continuation_auth, continuation_sha, reader_auth, reader_sha, execution_reader, execution_reader_sha, _phase_authorization = (
                module._authorization_context(SimpleNamespace(), current)
            )
        self.assertEqual(authorization, module.AUTHORIZATION)
        self.assertEqual(recovery_auth, module.RECOVERY_AUTHORIZATION)
        self.assertEqual(timestamp_auth, module.TIMESTAMP_RECOVERY_AUTHORIZATION)
        self.assertIsNone(continuation_auth)
        self.assertIsNone(continuation_sha)
        self.assertIsNone(reader_auth)
        self.assertIsNone(reader_sha)
        self.assertIsNone(execution_reader)
        self.assertIsNone(execution_reader_sha)
        self.assertEqual(marker_bytes, 2258)
        self.assertEqual(len(authorization_sha), 64)
        self.assertEqual(len(recovery_sha), 64)

        with patch.object(module, "TIMESTAMP_RECOVERY_ADC_SHA256", current.contract.sha256), \
                patch.object(module, "TIMESTAMP_RECOVERY_ADC_BYTES", current.contract.byte_length), \
                patch.object(module, "verify_adc_forward_generations",
                             return_value=(predecessor, old, recovery)), \
                self.assertRaisesRegex(module.PhaseReworkError, "complete exact approved successor chain"):
            module._authorization_context(SimpleNamespace(), current)

    def test_continuation_marker_and_corrected_artifact_impact_are_exact(self):
        current = continuation_contract()
        marker = (
            f"<!-- {module.CONTINUATION_AUTH_SCHEMA}\n"
            f"{module._canonical(module.CONTINUATION_AUTHORIZATION)}\n-->"
        ).encode("utf-8")
        self.assertEqual(len(marker), module.CONTINUATION_AUTH_MARKER_BYTES)
        self.assertEqual(hashlib.sha256(marker).hexdigest(), module.CONTINUATION_AUTH_MARKER_SHA256)
        authorization, marker_sha = module.parse_continuation_authorization(current)
        self.assertEqual(authorization, module.CONTINUATION_AUTHORIZATION)
        self.assertEqual(marker_sha, module.CONTINUATION_AUTH_MARKER_SHA256)
        module.parse_path_correction_generation(path_correction_contract())

        wrong_path_correction_artifact = path_correction_contract()
        wrong_path_correction_artifact.contract.content = (
            wrong_path_correction_artifact.contract.content.replace(
                b"docs/testing/runtime-tests.md", b"docs/testing/failure-tests.md",
            )
        )
        with self.assertRaisesRegex(module.PhaseReworkError, "path-correction ADC does not declare"):
            module.parse_path_correction_generation(wrong_path_correction_artifact)

        wrong_predecessor = continuation_contract(predecessor_id=module.RECOVERY_ADC_COMMENT_ID)
        wrong_artifact = continuation_contract(
            artifact_impact=module.CONTINUATION_ARTIFACT_IMPACT.replace(
                "docs/testing/traceability.md", "docs/testing/traceability.md."
            ),
        )
        for invalid in (wrong_predecessor, wrong_artifact):
            with self.assertRaises(module.PhaseReworkError):
                module.parse_continuation_authorization(invalid)

    def test_continuation_marker_rejects_missing_duplicate_and_mismatched_identity(self):
        for invalid in (
                continuation_contract(missing_marker=True),
                continuation_contract(duplicate_marker=True),
                continuation_contract({**module.CONTINUATION_AUTHORIZATION, "owner_id": module.OWNER_ID + 1}),
                continuation_contract({**module.CONTINUATION_AUTHORIZATION, "repository_id": 1}),
                continuation_contract({**module.CONTINUATION_AUTHORIZATION, "intent_comment_id": 1}),
                continuation_contract({**module.CONTINUATION_AUTHORIZATION, "applied_comment_id": 1}),
                continuation_contract({**module.CONTINUATION_AUTHORIZATION, "branch_ref": "other"}),
                continuation_contract({**module.CONTINUATION_AUTHORIZATION, "pr_base_sha40": "0" * 40}),
                continuation_contract({**module.CONTINUATION_AUTHORIZATION, "current_head_sha40": "0" * 40}),
                continuation_contract(repository="other/repo")):
            with self.assertRaises(module.PhaseReworkError):
                module.parse_continuation_authorization(invalid)

        invalid_state = continuation_contract()
        invalid_state.pointer.state = "draft"
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved generation"):
            module.parse_continuation_authorization(invalid_state)

    def test_continuation_requires_the_exact_six_generation_approved_chain(self):
        predecessor = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=module.PREDECESSOR_ADC_COMMENT_ID,
                                    state="approved", sha256=module.PREDECESSOR_ADC_SHA256),
            contract=SimpleNamespace(sha256=module.PREDECESSOR_ADC_SHA256,
                                     repository=module.REPOSITORY),
        )
        old = marker_contract(
            module.AUTH_SCHEMA, module.AUTHORIZATION,
            module.PREDECESSOR_ADC_COMMENT_ID, module.PREDECESSOR_ADC_SHA256,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256, module.REWORK_ADC_BYTES,
        )
        recovery = marker_contract(
            module.RECOVERY_AUTH_SCHEMA, module.RECOVERY_AUTHORIZATION,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256,
            module.RECOVERY_ADC_COMMENT_ID, module.RECOVERY_ADC_SHA256,
            module.RECOVERY_ADC_BYTES,
        )
        timestamp = timestamp_recovery_contract()
        timestamp.pointer.sha256 = module.TIMESTAMP_RECOVERY_ADC_SHA256
        timestamp.contract.sha256 = module.TIMESTAMP_RECOVERY_ADC_SHA256
        timestamp.contract.byte_length = module.TIMESTAMP_RECOVERY_ADC_BYTES
        path_correction = path_correction_contract()
        current = continuation_contract()
        chain = (predecessor, old, recovery, timestamp, path_correction, current)
        with patch.object(module, "verify_adc_forward_generations", return_value=chain):
            result = module._authorization_context(SimpleNamespace(), current)
        self.assertEqual(result[0], module.AUTHORIZATION)
        self.assertEqual(result[2], module.RECOVERY_AUTHORIZATION)
        self.assertEqual(result[4], module.TIMESTAMP_RECOVERY_AUTHORIZATION)
        self.assertEqual(result[6], module.CONTINUATION_AUTHORIZATION)
        self.assertEqual(result[7], module.CONTINUATION_AUTH_MARKER_SHA256)

        wrong_chain = (predecessor, old, recovery, timestamp, current, path_correction)
        with patch.object(module, "verify_adc_forward_generations", return_value=wrong_chain), \
                self.assertRaisesRegex(module.PhaseReworkError, "complete exact six-generation"):
            module._authorization_context(SimpleNamespace(), current)

    def test_reader_continuation_marker_is_exact_and_binds_traceability_predecessor(self):
        current = reader_continuation_contract()
        marker = (
            f"<!-- {module.READER_CONTINUATION_AUTH_SCHEMA}\n"
            f"{module._canonical(module.READER_CONTINUATION_AUTHORIZATION)}\n-->"
        ).encode("utf-8")
        self.assertEqual(len(marker), module.READER_CONTINUATION_AUTH_MARKER_BYTES)
        self.assertEqual(hashlib.sha256(marker).hexdigest(), module.READER_CONTINUATION_AUTH_MARKER_SHA256)
        authorization, marker_sha = module.parse_reader_continuation_authorization(current)
        self.assertEqual(authorization, module.READER_CONTINUATION_AUTHORIZATION)
        self.assertEqual(marker_sha, module.READER_CONTINUATION_AUTH_MARKER_SHA256)
        module.parse_traceability_source_correction_generation(traceability_source_correction_contract())

        invalids = (
            reader_continuation_contract(predecessor_id=module.CONTINUATION_ADC_COMMENT_ID),
            reader_continuation_contract(
                artifact_impact=module.READER_CONTINUATION_ARTIFACT_IMPACT.replace(
                    "docs/testing/traceability.md", "docs/testing/traceability.md."
                ),
            ),
            reader_continuation_contract(missing_marker=True),
            reader_continuation_contract(duplicate_marker=True),
            reader_continuation_contract(
                {**module.READER_CONTINUATION_AUTHORIZATION, "starting_head_sha40": "0" * 40}
            ),
            reader_continuation_contract(repository="other/repo"),
        )
        for invalid in invalids:
            with self.assertRaises(module.PhaseReworkError):
                module.parse_reader_continuation_authorization(invalid)

        invalid_state = reader_continuation_contract()
        invalid_state.pointer.state = "draft"
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved generation"):
            module.parse_reader_continuation_authorization(invalid_state)

    def test_reader_continuation_requires_the_exact_eight_generation_chain(self):
        predecessor = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=module.PREDECESSOR_ADC_COMMENT_ID,
                                    state="approved", sha256=module.PREDECESSOR_ADC_SHA256),
            contract=SimpleNamespace(sha256=module.PREDECESSOR_ADC_SHA256,
                                     repository=module.REPOSITORY),
        )
        old = marker_contract(
            module.AUTH_SCHEMA, module.AUTHORIZATION,
            module.PREDECESSOR_ADC_COMMENT_ID, module.PREDECESSOR_ADC_SHA256,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256, module.REWORK_ADC_BYTES,
        )
        recovery = marker_contract(
            module.RECOVERY_AUTH_SCHEMA, module.RECOVERY_AUTHORIZATION,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256,
            module.RECOVERY_ADC_COMMENT_ID, module.RECOVERY_ADC_SHA256,
            module.RECOVERY_ADC_BYTES,
        )
        timestamp = timestamp_recovery_contract()
        timestamp.pointer.sha256 = module.TIMESTAMP_RECOVERY_ADC_SHA256
        timestamp.contract.sha256 = module.TIMESTAMP_RECOVERY_ADC_SHA256
        timestamp.contract.byte_length = module.TIMESTAMP_RECOVERY_ADC_BYTES
        path_correction = path_correction_contract()
        continuation = continuation_contract()
        traceability = traceability_source_correction_contract()
        current = reader_continuation_contract()
        chain = (predecessor, old, recovery, timestamp, path_correction,
                 continuation, traceability, current)
        with patch.object(module, "verify_adc_forward_generations", return_value=chain):
            result = module._authorization_context(SimpleNamespace(), current)
        self.assertEqual(result[0], module.AUTHORIZATION)
        self.assertEqual(result[2], module.RECOVERY_AUTHORIZATION)
        self.assertEqual(result[4], module.TIMESTAMP_RECOVERY_AUTHORIZATION)
        self.assertEqual(result[6], module.CONTINUATION_AUTHORIZATION)
        self.assertEqual(result[8], module.READER_CONTINUATION_AUTHORIZATION)
        self.assertEqual(result[9], module.READER_CONTINUATION_AUTH_MARKER_SHA256)

        wrong_chain = (predecessor, old, recovery, timestamp, path_correction,
                       continuation, current, traceability)
        with patch.object(module, "verify_adc_forward_generations", return_value=wrong_chain), \
                self.assertRaisesRegex(module.PhaseReworkError, "complete exact eight-generation"):
            module._authorization_context(SimpleNamespace(), current)

        unapproved = traceability
        unapproved.pointer.state = "draft"
        chain_with_unapproved = (*chain[:6], unapproved, current)
        with patch.object(module, "verify_adc_forward_generations", return_value=chain_with_unapproved), \
                self.assertRaisesRegex(module.PhaseReworkError, "complete exact eight-generation"):
            module._authorization_context(SimpleNamespace(), current)

    def test_execution_receipt_reader_marker_is_exact_and_binds_reader_predecessor(self):
        current = execution_receipt_reader_continuation_contract()
        marker = (
            f"<!-- {module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_SCHEMA}\n"
            f"{module._canonical(module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION)}\n-->"
        ).encode("utf-8")
        self.assertEqual(len(marker), module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_BYTES)
        self.assertEqual(
            hashlib.sha256(marker).hexdigest(),
            module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256,
        )
        authorization, marker_sha = module.parse_execution_receipt_reader_continuation_authorization(
            current
        )
        self.assertEqual(authorization, module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION)
        self.assertEqual(marker_sha, module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256)
        bare = execution_receipt_reader_continuation_contract(predecessor_sha_format="bare")
        self.assertEqual(
            module.parse_execution_receipt_reader_continuation_authorization(bare)[0],
            module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
        )

        invalids = (
            execution_receipt_reader_continuation_contract(
                predecessor_id=module.CONTINUATION_ADC_COMMENT_ID,
            ),
            execution_receipt_reader_continuation_contract(predecessor_sha_format="open"),
            execution_receipt_reader_continuation_contract(predecessor_sha_format="close"),
            execution_receipt_reader_continuation_contract(predecessor_sha_format="double"),
            execution_receipt_reader_continuation_contract(
                artifact_impact=(
                    module.EXECUTION_RECEIPT_READER_CONTINUATION_ARTIFACT_IMPACT
                    .replace("docs/testing/traceability.md", "docs/testing/traceability.md.")
                ),
            ),
            execution_receipt_reader_continuation_contract(missing_marker=True),
            execution_receipt_reader_continuation_contract(duplicate_marker=True),
            execution_receipt_reader_continuation_contract(
                {**module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
                 "starting_head_sha40": "0" * 40}
            ),
            execution_receipt_reader_continuation_contract(repository="other/repo"),
        )
        for invalid in invalids:
            with self.assertRaises(module.PhaseReworkError):
                module.parse_execution_receipt_reader_continuation_authorization(invalid)

        invalid_state = execution_receipt_reader_continuation_contract()
        invalid_state.pointer.state = "draft"
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved generation"):
            module.parse_execution_receipt_reader_continuation_authorization(invalid_state)

    def test_approved_history_reader_marker_is_exact_and_binds_current_predecessor(self):
        current = approved_history_reader_contract()
        marker = (
            f"<!-- {module.APPROVED_HISTORY_READER_AUTH_SCHEMA}\n"
            f"{module._canonical(module.APPROVED_HISTORY_READER_AUTHORIZATION)}\n-->"
        ).encode("utf-8")
        self.assertEqual(len(marker), module.APPROVED_HISTORY_READER_AUTH_MARKER_BYTES)
        self.assertEqual(
            hashlib.sha256(marker).hexdigest(),
            module.APPROVED_HISTORY_READER_AUTH_MARKER_SHA256,
        )
        authorization, marker_sha = module.parse_approved_history_reader_authorization(current)
        self.assertEqual(authorization, module.APPROVED_HISTORY_READER_AUTHORIZATION)
        self.assertEqual(marker_sha, module.APPROVED_HISTORY_READER_AUTH_MARKER_SHA256)

        invalids = (
            approved_history_reader_contract(
                predecessor_id=module.EXECUTION_RECEIPT_READER_CONTINUATION_ADC_COMMENT_ID,
            ),
            approved_history_reader_contract(predecessor_sha="0" * 64),
            approved_history_reader_contract(
                artifact_impact=module.APPROVED_HISTORY_READER_ARTIFACT_IMPACT.replace(
                    "traceability.md", "traceability.md."
                ),
            ),
            approved_history_reader_contract(missing_marker=True),
            approved_history_reader_contract(duplicate_marker=True),
            approved_history_reader_contract(marker_json="{}"),
            approved_history_reader_contract(
                marker_json=module._canonical({
                    **module.APPROVED_HISTORY_READER_AUTHORIZATION,
                    "unexpected": True,
                }),
            ),
            approved_history_reader_contract(marker_json='{"a":1,"a":1}'),
            approved_history_reader_contract(marker_json="{"),
            approved_history_reader_contract(repository="other/repo"),
        )
        for invalid in invalids:
            with self.assertRaises(module.PhaseReworkError):
                module.parse_approved_history_reader_authorization(invalid)

        invalid_state = approved_history_reader_contract()
        invalid_state.pointer.state = "draft"
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved generation"):
            module.parse_approved_history_reader_authorization(invalid_state)
        invalid_pointer = approved_history_reader_contract()
        invalid_pointer.pointer.sha256 = "0" * 64
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved generation"):
            module.parse_approved_history_reader_authorization(invalid_pointer)

    def test_historical_predecessor_header_accepts_only_documented_markdown_forms(self):
        sha = "a" * 64
        self.assertEqual(
            module._adc_predecessor_header(
                f"Predecessor ADC: Issue #71 comment #123, SHA-256 {sha}", "test ADC",
            ),
            (123, sha),
        )
        self.assertEqual(
            module._adc_predecessor_header(
                f"Predecessor ADC: Issue #71 comment #123, SHA-256 `{sha}`  ", "test ADC",
            ),
            (123, sha),
        )
        invalid_headers = (
            f"Predecessor ADC: Issue #72 comment #123, SHA-256 {sha}",
            f"Predecessor ADC: Issue #71 comment #123, SHA-256 `{sha}",
            f"Predecessor ADC: Issue #71 comment #123, SHA-256 ``{sha}``",
            f"Predecessor ADC: Issue #71 comment #123, SHA-256 {sha} ",
            f"Predecessor ADC: Issue #71 comment #123, SHA-256 {sha}    ",
            f"Predecessor ADC: Issue #71 comment #１２３, SHA-256 {sha}",
        )
        for header in invalid_headers:
            with self.subTest(header=header):
                with self.assertRaises(module.PhaseReworkError):
                    module._adc_predecessor_header(header, "test ADC")
        with self.assertRaisesRegex(module.PhaseReworkError, "exactly one predecessor"):
            module._adc_predecessor_header(
                f"Predecessor ADC: Issue #71 comment #123, SHA-256 {sha}\n"
                f"## Body\nPredecessor ADC: Issue #71 comment #123, SHA-256 {sha}",
                "test ADC",
            )

    def test_execution_receipt_reader_requires_the_exact_nine_generation_chain(self):
        predecessor = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=module.PREDECESSOR_ADC_COMMENT_ID,
                                    state="approved", sha256=module.PREDECESSOR_ADC_SHA256),
            contract=SimpleNamespace(sha256=module.PREDECESSOR_ADC_SHA256,
                                     repository=module.REPOSITORY),
        )
        old = marker_contract(
            module.AUTH_SCHEMA, module.AUTHORIZATION,
            module.PREDECESSOR_ADC_COMMENT_ID, module.PREDECESSOR_ADC_SHA256,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256, module.REWORK_ADC_BYTES,
        )
        recovery = marker_contract(
            module.RECOVERY_AUTH_SCHEMA, module.RECOVERY_AUTHORIZATION,
            module.REWORK_ADC_COMMENT_ID, module.REWORK_ADC_SHA256,
            module.RECOVERY_ADC_COMMENT_ID, module.RECOVERY_ADC_SHA256,
            module.RECOVERY_ADC_BYTES,
        )
        timestamp = timestamp_recovery_contract()
        timestamp.pointer.sha256 = module.TIMESTAMP_RECOVERY_ADC_SHA256
        timestamp.contract.sha256 = module.TIMESTAMP_RECOVERY_ADC_SHA256
        timestamp.contract.byte_length = module.TIMESTAMP_RECOVERY_ADC_BYTES
        path_correction = path_correction_contract()
        continuation = continuation_contract()
        traceability = traceability_source_correction_contract()
        reader = reader_continuation_contract()
        current = execution_receipt_reader_continuation_contract()
        chain = (predecessor, old, recovery, timestamp, path_correction,
                 continuation, traceability, reader, current)
        with patch.object(module, "verify_adc_forward_generations", return_value=chain):
            result = module._authorization_context(SimpleNamespace(), current)
        self.assertEqual(result[0], module.AUTHORIZATION)
        self.assertEqual(result[2], module.RECOVERY_AUTHORIZATION)
        self.assertEqual(result[4], module.TIMESTAMP_RECOVERY_AUTHORIZATION)
        self.assertEqual(result[6], module.CONTINUATION_AUTHORIZATION)
        self.assertEqual(result[8], module.READER_CONTINUATION_AUTHORIZATION)
        self.assertEqual(result[9], module.READER_CONTINUATION_AUTH_MARKER_SHA256)
        self.assertEqual(result[10], module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION)
        self.assertEqual(
            result[11], module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256,
        )

        wrong_chain = (predecessor, old, recovery, timestamp, path_correction,
                       continuation, traceability, current, reader)
        with patch.object(module, "verify_adc_forward_generations", return_value=wrong_chain), \
                self.assertRaisesRegex(module.PhaseReworkError, "complete exact nine-generation"):
            module._authorization_context(SimpleNamespace(), current)

        unapproved = traceability
        unapproved.pointer.state = "draft"
        chain_with_unapproved = (*chain[:6], unapproved, reader, current)
        with patch.object(module, "verify_adc_forward_generations",
                          return_value=chain_with_unapproved), \
                self.assertRaisesRegex(module.PhaseReworkError, "complete exact nine-generation"):
            module._authorization_context(SimpleNamespace(), current)

    def test_execution_receipt_reader_commit_segment_is_bounded(self):
        start = module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION["starting_head_sha40"]
        commit = "1" * 40
        allowed_path = module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION[
            "followup_path_allowlist"
        ][-1]
        base_args = (
            Path("/tmp/repo"), commit, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            module.READER_CONTINUATION_AUTHORIZATION,
            module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
        )
        with patch.object(module, "_verify_recovery_commit_set") as verify_prior, \
                patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=commit), \
                patch.object(module, "commit_parents_sha40", return_value=(start,)), \
                patch.object(module, "changed_paths_between", return_value=(allowed_path,)):
            module._verify_execution_receipt_reader_commit_set(*base_args)
        verify_prior.assert_called_once_with(
            Path("/tmp/repo"), start, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            module.READER_CONTINUATION_AUTHORIZATION,
        )

        invalid_cases = (
            ("extra descendant", {"run_git": {"return_value": f"{commit}\n{'2' * 40}"}},
             "exactly one authorized commit"),
            ("wrong parent", {"commit_parents_sha40": {"return_value": ("3" * 40,)}},
             "unexpected parent"),
            ("outside allowlist", {"changed_paths_between": {"return_value": ("outside.py",)}},
             "outside its exact allowlist"),
            ("missing ancestry", {"is_ancestor": {"return_value": False}},
             "must descend from its exact starting HEAD"),
        )
        for name, overrides, message in invalid_cases:
            with self.subTest(name=name):
                patchers = {
                    "is_ancestor": patch.object(module, "is_ancestor", return_value=True),
                    "run_git": patch.object(module, "run_git", return_value=commit),
                    "commit_parents_sha40": patch.object(
                        module, "commit_parents_sha40", return_value=(start,),
                    ),
                    "changed_paths_between": patch.object(
                        module, "changed_paths_between", return_value=(allowed_path,),
                    ),
                }
                patchers.update({key: patch.object(module, key, **kwargs)
                                 for key, kwargs in overrides.items()})
                with patch.object(module, "_verify_recovery_commit_set"), \
                        patchers["is_ancestor"], patchers["run_git"], \
                        patchers["commit_parents_sha40"], patchers["changed_paths_between"], \
                        self.assertRaisesRegex(module.PhaseReworkError, message):
                    module._verify_execution_receipt_reader_commit_set(*base_args)

    def test_approved_history_reader_uses_exact_chain_without_parsing_history_markers(self):
        current = approved_history_reader_contract()
        chain = approved_history_chain(current)
        github = SimpleNamespace()
        with patch.object(module, "verify_adc_forward_generations", return_value=chain) as verify:
            result = module._authorization_context(github, current)
        verify.assert_called_once_with(
            github, module.ISSUE_NUMBER,
            prior_comment_id=module.PREDECESSOR_ADC_COMMENT_ID,
            prior_sha256=module.PREDECESSOR_ADC_SHA256,
            current_comment_id=module.APPROVED_HISTORY_READER_ADC_COMMENT_ID,
            current_sha256=module.APPROVED_HISTORY_READER_ADC_SHA256,
        )
        self.assertEqual(result[0], module.AUTHORIZATION)
        self.assertEqual(result[1], module.REWORK_AUTH_MARKER_SHA256)
        self.assertEqual(result[2], module.RECOVERY_AUTHORIZATION)
        self.assertEqual(result[4], module.TIMESTAMP_RECOVERY_AUTHORIZATION)
        self.assertEqual(result[6], module.CONTINUATION_AUTHORIZATION)
        self.assertEqual(result[8], module.READER_CONTINUATION_AUTHORIZATION)
        self.assertEqual(
            result[10], module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
        )
        self.assertEqual(len(chain) - 1, 11)
        # Historical bodies deliberately contain malformed markers. Their approved pointer
        # identity and predecessor links are enough; only the current marker is parsed.
        self.assertTrue(all(
            b"deliberately malformed historical authorization marker" in row.contract.content
            for row in chain[:-1]
        ))

    def test_approved_history_reader_rejects_changed_or_broken_history(self):
        current = approved_history_reader_contract()
        authorization = module.APPROVED_HISTORY_READER_AUTHORIZATION

        def rejected(chain):
            with patch.object(module, "verify_adc_forward_generations", return_value=chain):
                with self.assertRaises(module.PhaseReworkError):
                    module._verify_approved_history_reader_chain(
                        SimpleNamespace(), current, authorization,
                    )

        chain = list(approved_history_chain(current))
        chain[2].contract.sha256 = "0" * 64
        rejected(chain)

        chain = list(approved_history_chain(current))
        chain[2].contract.byte_length += 1
        rejected(chain)

        chain = list(approved_history_chain(current))
        chain[2].pointer.state = "draft"
        rejected(chain)

        chain = list(approved_history_chain(current))
        chain[2].pointer.sha256 = "0" * 64
        rejected(chain)

        chain = list(approved_history_chain(current))
        chain[2], chain[3] = chain[3], chain[2]
        rejected(chain)

        chain = list(approved_history_chain(current))
        chain.pop(4)
        rejected(chain)

        chain = list(approved_history_chain(current))
        chain.insert(-1, chain[0])
        rejected(chain)

        chain = list(approved_history_chain(current))
        broken = chain[2].contract.content.replace(
            authorization["approved_history"][1]["sha256"].encode(), b"0" * 64, 1,
        )
        chain[2].contract.content = broken
        rejected(chain)

    def test_approved_history_reader_validates_every_exact_historical_segment(self):
        authorization = module.APPROVED_HISTORY_READER_AUTHORIZATION
        history = authorization["approved_history"]
        start = authorization["starting_head_sha40"]
        middle, head = "1" * 40, "2" * 40
        path_one = authorization["followup_path_allowlist"][0]
        path_two = authorization["followup_path_allowlist"][-1]
        segments = [
            {
                "adc_comment_id": history[0]["comment_id"],
                "adc_sha256": history[0]["sha256"],
                "parent_sha40": start,
                "commit_sha40": middle,
                "path_allowlist": [path_one],
            },
            {
                "adc_comment_id": history[1]["comment_id"],
                "adc_sha256": history[1]["sha256"],
                "parent_sha40": middle,
                "commit_sha40": head,
                "path_allowlist": [path_two],
            },
        ]
        root = Path("/tmp/repo")
        args = (
            root, head, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            module.READER_CONTINUATION_AUTHORIZATION,
            module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
            module.MARKDOWN_PREDECESSOR_READER_AUTHORIZATION,
            authorization, segments, history,
        )
        with patch.object(module, "_verify_markdown_predecessor_reader_commit_set") as verify_prior, \
                patch.object(module, "run_git", return_value=f"{middle}\n{head}"), \
                patch.object(module, "commit_parents_sha40", side_effect=[(start,), (middle,)]), \
                patch.object(module, "changed_paths_between", side_effect=[(path_one,), (path_two,)]):
            module._verify_approved_history_reader_commit_set(*args)
        verify_prior.assert_called_once_with(
            root, start, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            module.READER_CONTINUATION_AUTHORIZATION,
            module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
            module.MARKDOWN_PREDECESSOR_READER_AUTHORIZATION,
        )

        invalid_cases = (
            ("extra descendant", {"rows": f"{middle}\n{head}\n{'3' * 40}"},
             "enumeration differs"),
            ("missing descendant", {"rows": middle}, "enumeration differs"),
            ("wrong parent", {"parents": [("4" * 40,)]}, "unexpected direct parent"),
            ("wrong changed paths", {"paths": [("outside.py",), (path_two,)]},
             "differ from its exact path allowlist"),
        )
        for name, overrides, message in invalid_cases:
            with self.subTest(name=name):
                rows = overrides.get("rows", f"{middle}\n{head}")
                parents = overrides.get("parents", [(start,), (middle,)])
                paths = overrides.get("paths", [(path_one,), (path_two,)])
                with patch.object(module, "_verify_markdown_predecessor_reader_commit_set"), \
                        patch.object(module, "run_git", return_value=rows), \
                        patch.object(module, "commit_parents_sha40", side_effect=parents), \
                        patch.object(module, "changed_paths_between", side_effect=paths), \
                        self.assertRaisesRegex(module.PhaseReworkError, message):
                    module._verify_approved_history_reader_commit_set(*args)

        malformed = [dict(segments[0]), dict(segments[1])]
        malformed[1]["parent_sha40"] = "4" * 40
        with self.assertRaisesRegex(module.PhaseReworkError, "gap, duplicate"):
            module._validate_historical_commit_segments(malformed, history, start, head)
        malformed = [dict(segments[0]), dict(segments[1])]
        malformed[0]["adc_sha256"] = "0" * 64
        with self.assertRaisesRegex(module.PhaseReworkError, "approved ADC history row"):
            module._validate_historical_commit_segments(malformed, history, start, head)
        malformed = [dict(segments[0]), dict(segments[1])]
        malformed.reverse()
        with self.assertRaises(module.PhaseReworkError):
            module._validate_historical_commit_segments(malformed, history, start, head)
        with self.assertRaisesRegex(module.PhaseReworkError, "does not end"):
            module._validate_historical_commit_segments(segments, history, start, "5" * 40)

    def test_historical_segment_parser_rejects_duplicate_commit_and_wrong_adc_identity(self):
        authorization = module.APPROVED_HISTORY_READER_AUTHORIZATION
        history = authorization["approved_history"]
        start = authorization["starting_head_sha40"]
        middle, head = "1" * 40, "2" * 40
        path_one = authorization["followup_path_allowlist"][0]
        path_two = authorization["followup_path_allowlist"][-1]
        segments = [
            {
                "adc_comment_id": history[0]["comment_id"],
                "adc_sha256": history[0]["sha256"],
                "parent_sha40": start,
                "commit_sha40": middle,
                "path_allowlist": [path_one],
            },
            {
                "adc_comment_id": history[1]["comment_id"],
                "adc_sha256": history[1]["sha256"],
                "parent_sha40": middle,
                "commit_sha40": head,
                "path_allowlist": [path_two],
            },
        ]

        duplicate = [dict(segment) for segment in segments]
        duplicate[1]["commit_sha40"] = middle
        with self.assertRaisesRegex(module.PhaseReworkError, "gap, duplicate"):
            module._validate_historical_commit_segments(duplicate, history, start, head)

        wrong_identity = [dict(segment) for segment in segments]
        wrong_identity[0]["adc_comment_id"] = history[1]["comment_id"]
        with self.assertRaisesRegex(module.PhaseReworkError, "approved ADC history row"):
            module._validate_historical_commit_segments(wrong_identity, history, start, head)

    def test_approved_history_reader_rejects_merge_and_each_exact_path_drift(self):
        authorization = module.APPROVED_HISTORY_READER_AUTHORIZATION
        history = authorization["approved_history"]
        start = authorization["starting_head_sha40"]
        middle, head = "1" * 40, "2" * 40
        path_one = authorization["followup_path_allowlist"][0]
        path_two = authorization["followup_path_allowlist"][-1]
        segments = [
            {
                "adc_comment_id": history[0]["comment_id"],
                "adc_sha256": history[0]["sha256"],
                "parent_sha40": start,
                "commit_sha40": middle,
                "path_allowlist": [path_one, path_two],
            },
            {
                "adc_comment_id": history[1]["comment_id"],
                "adc_sha256": history[1]["sha256"],
                "parent_sha40": middle,
                "commit_sha40": head,
                "path_allowlist": [path_two],
            },
        ]
        root = Path("/tmp/repo")
        args = (
            root, head, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            module.READER_CONTINUATION_AUTHORIZATION,
            module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
            module.MARKDOWN_PREDECESSOR_READER_AUTHORIZATION,
            authorization, segments, history,
        )
        rows = chr(10).join((middle, head))
        with (
            patch.object(module, "_verify_markdown_predecessor_reader_commit_set"),
            patch.object(module, "run_git", return_value=rows),
            patch.object(module, "commit_parents_sha40", return_value=(start, "4" * 40)),
            patch.object(module, "changed_paths_between") as changed_paths,
            self.assertRaisesRegex(module.PhaseReworkError, "unexpected direct parent"),
        ):
            module._verify_approved_history_reader_commit_set(*args)
        changed_paths.assert_not_called()

        cases = (
            ("added path", (path_one, path_two, "outside.py")),
            ("omitted path", (path_one,)),
            ("duplicate path", (path_one, path_one, path_two)),
            ("reordered paths", (path_two, path_one)),
        )
        for name, actual_paths in cases:
            with self.subTest(name=name):
                with (
                    patch.object(module, "_verify_markdown_predecessor_reader_commit_set"),
                    patch.object(module, "run_git", return_value=rows),
                    patch.object(
                        module, "commit_parents_sha40",
                        side_effect=[(start,), (middle,)],
                    ),
                    patch.object(
                        module, "changed_paths_between",
                        side_effect=[actual_paths, (path_two,)],
                    ),
                    self.assertRaisesRegex(
                        module.PhaseReworkError,
                        "differ from its exact path allowlist",
                    ),
                ):
                    module._verify_approved_history_reader_commit_set(*args)

    def test_approved_history_lineage_keeps_prior_segments_separate(self):
        root = Path("/tmp/repo")
        head = "f" * 40
        with patch.object(module, "_verify_commit_set") as verify_bootstrap, \
                patch.object(module, "_verify_recovery_commit_set") as verify_segments:
            module._verify_issue71_commit_lineage(
                root, head, module.AUTHORIZATION, module.RECOVERY_AUTHORIZATION,
                module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
                module.READER_CONTINUATION_AUTHORIZATION,
                module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
                module.MARKDOWN_PREDECESSOR_READER_AUTHORIZATION,
                module.APPROVED_HISTORY_READER_AUTHORIZATION,
            )
        verify_bootstrap.assert_called_once_with(
            root, module.RECOVERY_AUTHORIZATION["pre_recovery_head_sha40"],
            tuple(module.AUTHORIZATION["bootstrap_path_allowlist"]),
        )
        verify_segments.assert_called_once_with(
            root, head, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            module.READER_CONTINUATION_AUTHORIZATION,
            module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
            module.MARKDOWN_PREDECESSOR_READER_AUTHORIZATION,
            module.APPROVED_HISTORY_READER_AUTHORIZATION, None, None,
        )


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

    def test_timestamp_recovery_validates_bootstrap_and_each_successor_segment(self):
        root = Path("/tmp/repo")
        head = "f" * 40
        bootstrap_head = module.RECOVERY_AUTHORIZATION["pre_recovery_head_sha40"]
        with patch.object(module, "_verify_commit_set") as verify_bootstrap, \
                patch.object(module, "_verify_recovery_commit_set") as verify_successors:
            module._verify_issue71_commit_lineage(
                root, head, module.AUTHORIZATION, module.RECOVERY_AUTHORIZATION,
                module.TIMESTAMP_RECOVERY_AUTHORIZATION,
            )
        verify_bootstrap.assert_called_once_with(
            root, bootstrap_head, tuple(module.AUTHORIZATION["bootstrap_path_allowlist"]),
        )
        verify_successors.assert_called_once_with(
            root, head, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, None, None, None, None, None,
            None, None,
        )

    def test_continuation_lineage_preserves_three_separate_one_commit_segments(self):
        root = Path("/tmp/repo")
        head = "f" * 40
        bootstrap_head = module.RECOVERY_AUTHORIZATION["pre_recovery_head_sha40"]
        with patch.object(module, "_verify_commit_set") as verify_bootstrap, \
                patch.object(module, "_verify_recovery_commit_set") as verify_segments:
            module._verify_issue71_commit_lineage(
                root, head, module.AUTHORIZATION, module.RECOVERY_AUTHORIZATION,
                module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            )
        verify_bootstrap.assert_called_once_with(
            root, bootstrap_head, tuple(module.AUTHORIZATION["bootstrap_path_allowlist"]),
        )
        verify_segments.assert_called_once_with(
            root, head, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            None, None, None, None, None, None,
        )

    def test_reader_continuation_lineage_preserves_four_separate_one_commit_segments(self):
        root = Path("/tmp/repo")
        head = "f" * 40
        bootstrap_head = module.RECOVERY_AUTHORIZATION["pre_recovery_head_sha40"]
        with patch.object(module, "_verify_commit_set") as verify_bootstrap, \
                patch.object(module, "_verify_recovery_commit_set") as verify_segments:
            module._verify_issue71_commit_lineage(
                root, head, module.AUTHORIZATION, module.RECOVERY_AUTHORIZATION,
                module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
                module.READER_CONTINUATION_AUTHORIZATION,
            )
        verify_bootstrap.assert_called_once_with(
            root, bootstrap_head, tuple(module.AUTHORIZATION["bootstrap_path_allowlist"]),
        )
        verify_segments.assert_called_once_with(
            root, head, module.RECOVERY_AUTHORIZATION,
            module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
            module.READER_CONTINUATION_AUTHORIZATION, None, None, None, None, None,
        )

    def test_continuation_commit_is_one_direct_child_on_its_exact_allowlist(self):
        root = Path("/tmp/repo")
        head = "f" * 40
        recovery_commit = "574d7970323840933c34c37e874ad1616d577a8a"
        start = module.CONTINUATION_AUTHORIZATION["current_head_sha40"]
        ranges = {
            f"{module.RECOVERY_AUTHORIZATION['pre_recovery_head_sha40']}..574d7970323840933c34c37e874ad1616d577a8a": recovery_commit,
            f"574d7970323840933c34c37e874ad1616d577a8a..{start}": start,
            f"{start}..{head}": head,
        }
        parents = {
            recovery_commit: (module.RECOVERY_AUTHORIZATION["pre_recovery_head_sha40"],),
            start: ("574d7970323840933c34c37e874ad1616d577a8a",),
            head: (start,),
        }

        def check(*, continuation_parent: tuple[str, ...] = (start,),
                  continuation_rows: str = head,
                  continuation_paths: tuple[str, ...] = ("tests/test_phase_rework.py",)):
            rows_by_range = {**ranges, f"{start}..{head}": continuation_rows}
            commit_parents = {**parents, head: continuation_parent}

            def run_git(_root, *_args):
                return rows_by_range[_args[-1]]

            def changed_paths(_root, _parent, commit):
                if commit == recovery_commit or commit == start:
                    return ("runtime/p_ases/phase_rework.py",)
                return continuation_paths

            with patch.object(module, "is_ancestor", return_value=True), \
                    patch.object(module, "run_git", side_effect=run_git), \
                    patch.object(module, "commit_parents_sha40", side_effect=lambda _root, commit: commit_parents[commit]), \
                    patch.object(module, "changed_paths_between", side_effect=changed_paths):
                module._verify_recovery_commit_set(
                    root, head, module.RECOVERY_AUTHORIZATION,
                    module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
                )

        check()
        with self.assertRaisesRegex(module.PhaseReworkError, "unexpected parent"):
            check(continuation_parent=("e" * 40,))
        with self.assertRaisesRegex(module.PhaseReworkError, "exactly one authorized"):
            check(continuation_rows=f"{head}\n{'e' * 40}")
        with self.assertRaisesRegex(module.PhaseReworkError, "outside its exact allowlist"):
            check(continuation_paths=("runtime/p_ases/github.py",))

    def test_reader_continuation_commit_is_one_direct_child_on_its_exact_allowlist(self):
        root = Path("/tmp/repo")
        head = "f" * 40
        recovery_commit = "574d7970323840933c34c37e874ad1616d577a8a"
        timestamp_commit = "cb02a9fccfb988300dff82c5ad2ccfe946cd4dd3"
        continuation_commit = module.READER_CONTINUATION_AUTHORIZATION["starting_head_sha40"]
        recovery_start = module.RECOVERY_AUTHORIZATION["pre_recovery_head_sha40"]
        timestamp_start = module.TIMESTAMP_RECOVERY_AUTHORIZATION["current_head_sha40"]
        continuation_start = module.CONTINUATION_AUTHORIZATION["current_head_sha40"]
        ranges = {
            f"{recovery_start}..{recovery_commit}": recovery_commit,
            f"{recovery_commit}..{timestamp_commit}": timestamp_commit,
            f"{timestamp_commit}..{continuation_commit}": continuation_commit,
            f"{continuation_commit}..{head}": head,
        }
        parents = {
            recovery_commit: (recovery_start,),
            timestamp_commit: (recovery_commit,),
            continuation_commit: (timestamp_commit,),
            head: (continuation_commit,),
        }

        def check(*, reader_parent: tuple[str, ...] = (continuation_commit,),
                  reader_rows: str = head,
                  reader_paths: tuple[str, ...] = ("docs/specs/workflow-spec.md",)):
            rows_by_range = {**ranges, f"{continuation_commit}..{head}": reader_rows}
            commit_parents = {**parents, head: reader_parent}

            def run_git(_root, *_args):
                return rows_by_range[_args[-1]]

            def changed_paths(_root, _parent, commit):
                if commit == recovery_commit or commit == timestamp_commit:
                    return ("runtime/p_ases/phase_rework.py",)
                if commit == continuation_commit:
                    return ("tests/test_phase_rework.py",)
                return reader_paths

            with patch.object(module, "is_ancestor", return_value=True), \
                    patch.object(module, "run_git", side_effect=run_git), \
                    patch.object(module, "commit_parents_sha40", side_effect=lambda _root, commit: commit_parents[commit]), \
                    patch.object(module, "changed_paths_between", side_effect=changed_paths):
                module._verify_recovery_commit_set(
                    root, head, module.RECOVERY_AUTHORIZATION,
                    module.TIMESTAMP_RECOVERY_AUTHORIZATION, module.CONTINUATION_AUTHORIZATION,
                    module.READER_CONTINUATION_AUTHORIZATION,
                )

        check()
        with self.assertRaisesRegex(module.PhaseReworkError, "unexpected parent"):
            check(reader_parent=("e" * 40,))
        with self.assertRaisesRegex(module.PhaseReworkError, "exactly one authorized"):
            check(reader_rows=f"{head}\n{'e' * 40}")
        with self.assertRaisesRegex(module.PhaseReworkError, "outside its exact allowlist"):
            check(reader_paths=("runtime/p_ases/github.py",))

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

    def test_applied_timestamp_skew_is_utc_ordered_and_inclusive_at_300_seconds(self):
        delta = module._applied_timestamp_delta_seconds
        self.assertEqual(
            delta("2026-11-15T05:50:04Z", "2026-11-15T05:50:04Z", 300), 0,
        )
        self.assertEqual(
            delta("2026-11-15T05:50:01Z", "2026-11-15T05:50:04Z", 300), 3,
        )
        self.assertEqual(
            delta("2026-11-15T05:45:04Z", "2026-11-15T05:50:04Z", 300), 300,
        )
        with self.assertRaisesRegex(module.PhaseReworkError, "authorized UTC skew"):
            delta("2026-11-15T05:45:03Z", "2026-11-15T05:50:04Z", 300)
        with self.assertRaisesRegex(module.PhaseReworkError, "authorized UTC skew"):
            delta("2026-11-15T05:50:05Z", "2026-11-15T05:50:04Z", 300)
        with self.assertRaisesRegex(module.PhaseReworkError, "canonical UTC"):
            delta("2026-11-15 05:50:01Z", "2026-11-15T05:50:04Z", 300)

    def test_timestamp_recovery_binds_exact_existing_intent_and_applied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _result = intent_record(root)
            payload = module._applied_payload(intent)
            payload["applied_at"] = "2026-11-15T05:50:01Z"
            body = module._record_body(module.APPLIED_SCHEMA, payload)
            applied = module.PhaseReworkRecord(
                module.TIMESTAMP_RECOVERY_AUTHORIZATION["applied_comment_id"],
                module.APPLIED_SCHEMA, payload, body, module.OWNER_ID,
                module.TIMESTAMP_RECOVERY_AUTHORIZATION["applied_comment_created_at"],
            )
            timestamp_authorization = dict(module.TIMESTAMP_RECOVERY_AUTHORIZATION)
            timestamp_authorization.update({
                "intent_comment_id": intent.comment_id,
                "intent_body_sha256": intent.body_sha256,
                "applied_body_sha256": applied.body_sha256,
            })
            current = replace(
                live_subject(root, head=intent.payload["bootstrap_head_sha40"]),
                current_adc=SimpleNamespace(
                    pointer=SimpleNamespace(comment_id=module.TIMESTAMP_RECOVERY_ADC_COMMENT_ID,
                                            state="approved"),
                    contract=SimpleNamespace(sha256=module.TIMESTAMP_RECOVERY_ADC_SHA256),
                ),
                timestamp_recovery_authorization=timestamp_authorization,
            )
            module._validate_applied(applied, intent, current)

            with self.assertRaisesRegex(module.PhaseReworkError, "exact Intent"):
                wrong_intent = dict(payload, intent_comment_id=intent.comment_id + 1)
                wrong_body = module._record_body(module.APPLIED_SCHEMA, wrong_intent)
                module._validate_applied(
                    replace(applied, payload=wrong_intent, body=wrong_body), intent, current,
                )
            with self.assertRaisesRegex(module.PhaseReworkError, "exact timestamp-recovery journal"):
                module._validate_applied(replace(applied, comment_id=applied.comment_id + 1), intent, current)
            with self.assertRaisesRegex(module.PhaseReworkError, "exact timestamp-recovery journal"):
                module._validate_applied(replace(applied, body=body + " "), intent, current)
            with self.assertRaisesRegex(module.PhaseReworkError, "exact timestamp-recovery journal"):
                module._validate_applied(
                    replace(applied, created_at="2026-11-15T05:50:05Z"), intent, current,
                )

    def test_recovery_intent_accepts_only_the_exact_timestamp_adc_successor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _readiness, live = recovery_fixture(root)
            current_adc = SimpleNamespace(
                pointer=SimpleNamespace(
                    comment_id=module.TIMESTAMP_RECOVERY_ADC_COMMENT_ID, state="approved",
                ),
                contract=SimpleNamespace(sha256=module.TIMESTAMP_RECOVERY_ADC_SHA256),
            )
            current = replace(
                live, current_adc=current_adc,
                timestamp_recovery_authorization=module.TIMESTAMP_RECOVERY_AUTHORIZATION,
                timestamp_recovery_authorization_sha256=module.TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256,
            )
            with patch.object(module, "_validate_intent"), \
                    patch.object(module, "_validate_recorded_readiness"), \
                    patch.object(module, "_read_exact_attempt_marker", return_value=True):
                module._validate_recovery_intent(intent, current, root)
                continuation = replace(
                    current,
                    current_adc=SimpleNamespace(
                        pointer=SimpleNamespace(
                            comment_id=module.CONTINUATION_ADC_COMMENT_ID, state="approved",
                        ),
                        contract=SimpleNamespace(sha256=module.CONTINUATION_ADC_SHA256),
                    ),
                    continuation_authorization=module.CONTINUATION_AUTHORIZATION,
                    continuation_authorization_sha256=module.CONTINUATION_AUTH_MARKER_SHA256,
                )
                module._validate_recovery_intent(intent, continuation, root)
                with self.assertRaisesRegex(module.PhaseReworkError, "current ADC does not authorize"):
                    module._validate_recovery_intent(
                        intent, replace(continuation, continuation_authorization_sha256="0" * 64), root,
                    )
                with self.assertRaisesRegex(module.PhaseReworkError, "current ADC does not authorize"):
                    module._validate_recovery_intent(
                        intent, replace(current, timestamp_recovery_authorization=None), root,
                    )

    def test_continuation_reconciliation_is_a_zero_issue_write_noop(self):
        class WriteCounter:
            repo = module.REPOSITORY

            def __init__(self):
                self.writes = []

            def __getattr__(self, name):
                if any(part in name.casefold() for part in ("comment", "label", "update", "post")):
                    def record_write(*_args, **_kwargs):
                        self.writes.append(name)
                        raise AssertionError(f"unexpected GitHub write: {name}")
                    return record_write
                raise AttributeError(name)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent = SimpleNamespace(
                comment_id=module.TIMESTAMP_RECOVERY_AUTHORIZATION["intent_comment_id"],
                body_sha256=module.TIMESTAMP_RECOVERY_AUTHORIZATION["intent_body_sha256"],
                schema=module.INTENT_SCHEMA,
                payload={"adc_comment_id": module.REWORK_ADC_COMMENT_ID,
                         "adc_sha256": module.REWORK_ADC_SHA256,
                         "readiness_sha256": "e" * 64},
            )
            applied = SimpleNamespace(
                comment_id=module.TIMESTAMP_RECOVERY_AUTHORIZATION["applied_comment_id"],
                schema=module.APPLIED_SCHEMA,
                payload={"adc_comment_id": module.REWORK_ADC_COMMENT_ID,
                         "adc_sha256": module.REWORK_ADC_SHA256},
            )
            current_adc = SimpleNamespace(
                pointer=SimpleNamespace(
                    comment_id=module.CONTINUATION_ADC_COMMENT_ID, state="approved",
                ),
                contract=SimpleNamespace(sha256=module.CONTINUATION_ADC_SHA256),
            )
            live = replace(
                live_subject(root, labels=tuple(sorted(module.LABELS_AFTER))),
                current_adc=current_adc,
                recovery_authorization=module.RECOVERY_AUTHORIZATION,
                timestamp_recovery_authorization=module.TIMESTAMP_RECOVERY_AUTHORIZATION,
                timestamp_recovery_authorization_sha256=module.TIMESTAMP_RECOVERY_AUTH_MARKER_SHA256,
                continuation_authorization=module.CONTINUATION_AUTHORIZATION,
                continuation_authorization_sha256=module.CONTINUATION_AUTH_MARKER_SHA256,
            )
            github = WriteCounter()
            with patch.object(module, "_live", return_value=live), \
                    patch.object(module, "_read_history", return_value=(intent, applied)), \
                    patch.object(module, "_validate_recovery_intent"), \
                    patch.object(module, "_validate_applied"), \
                    patch.object(module, "_validate_post_rework_labels"), \
                    patch.object(module, "_read_exact_attempt_marker", return_value=True), \
                    patch.object(module, "_validate_recorded_readiness"), \
                    patch.object(module, "_verify_recovery_pr_binding") as verify_binding:
                result = module.apply_issue71_phase_rework(
                    github, root, module.ISSUE_NUMBER, readiness_factory=object(),
                )

        self.assertEqual(result["status"], "NOOP")
        self.assertEqual(result["intent_comment_id"], intent.comment_id)
        self.assertEqual(result["applied_comment_id"], applied.comment_id)
        self.assertEqual(github.writes, [])
        verify_binding.assert_called_once()


class OneShotWriteTests(unittest.TestCase):
    def test_comment_post_invalidates_history_session_around_every_v2_v3_record(self):
        schemas = (
            module.INTENT_SCHEMA,
            module.APPLIED_SCHEMA,
            module.ISSUE71_REWORK_INTENT_V3_SCHEMA,
            module.ISSUE71_REWORK_APPLIED_V3_SCHEMA,
        )
        for schema in schemas:
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                events: list[str] = []
                payload = {"schema": schema, "executor_user_id": module.OWNER_ID}
                body = module._record_body(schema, payload)
                record = SimpleNamespace(
                    schema=schema, body=body, comment_id=201, actor_id=module.OWNER_ID,
                )
                history_reads = iter(((), (record,)))

                class FakeGitHub:
                    def create_issue_comment(self, _issue: int, _body: str) -> dict:
                        events.append("post")
                        return {"id": 201}

                def read_history(_github):
                    events.append("history")
                    return next(history_reads)

                with patch.object(module, "_read_history", side_effect=read_history), \
                        patch.object(
                            module, "refresh_adc_forward_generation_session",
                            side_effect=lambda *_args: events.append("refresh"),
                        ):
                    result = module._post_record_once(
                        FakeGitHub(), root, schema, payload,
                        before_write=lambda: events.append("fresh-validation"),
                    )

                self.assertIs(result, record)
                self.assertEqual(
                    events,
                    ["history", "refresh", "fresh-validation", "post", "refresh", "history"],
                )

    def test_comment_post_requires_fresh_validation_before_attempt_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = {"schema": module.INTENT_SCHEMA, "executor_user_id": module.OWNER_ID}

            class FakeGitHub:
                posts = 0

                def create_issue_comment(self, _issue: int, _body: str) -> dict:
                    self.posts += 1
                    return {"id": 202}

            github = FakeGitHub()
            with patch.object(module, "_read_history", return_value=()), \
                    self.assertRaisesRegex(module.PhaseReworkError, "requires fresh subject validation"):
                module._post_record_once(github, root, module.INTENT_SCHEMA, payload)

            self.assertEqual(github.posts, 0)
            self.assertFalse(module._record_path(root, "intent").exists())

    def test_changed_approved_history_at_comment_boundary_blocks_before_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = {"schema": module.INTENT_SCHEMA, "executor_user_id": module.OWNER_ID}
            approved_history = {"sha256": "approved-before-preflight"}
            events: list[str] = []

            class FakeGitHub:
                posts = 0

                def create_issue_comment(self, _issue: int, _body: str) -> dict:
                    self.posts += 1
                    return {"id": 204}

            github = FakeGitHub()

            def read_phase_history(_github):
                events.append("phase-history-preflight")
                approved_history["sha256"] = "approved-history-changed-at-boundary"
                return ()

            def verify_current_history():
                events.append("current-adc-history-validation")
                if approved_history["sha256"] != "approved-before-preflight":
                    raise module.PhaseReworkError("approved ADC history changed before write")

            with patch.object(module, "_read_history", side_effect=read_phase_history), \
                    patch.object(module, "refresh_adc_forward_generation_session",
                                 side_effect=lambda *_args: events.append("invalidate")):
                with self.assertRaisesRegex(module.PhaseReworkError, "approved ADC history changed"):
                    module._post_record_once(
                        github, root, module.INTENT_SCHEMA, payload,
                        before_write=verify_current_history,
                    )

            self.assertEqual(
                events,
                ["phase-history-preflight", "invalidate", "current-adc-history-validation", "invalidate"],
            )
            self.assertEqual(github.posts, 0)
            self.assertFalse(module._record_path(root, "intent").exists())

    def test_v2_applied_route_supplies_fresh_subject_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _result = intent_record(root)
            current = live_subject(root, labels=tuple(sorted(module.LABELS_AFTER)))
            current = module._Live(**{**current.__dict__, "issue": {"body": "fixed", "state": "open"}})
            payload = module._applied_payload(intent)
            body = module._record_body(module.APPLIED_SCHEMA, payload)
            record = SimpleNamespace(
                schema=module.APPLIED_SCHEMA, body=body, comment_id=203,
                actor_id=module.OWNER_ID,
            )
            history_reads = iter(((), (record,)))
            events: list[str] = []

            class FakeGitHub:
                def create_issue_comment(self, _issue: int, _body: str) -> dict:
                    events.append("post")
                    return {"id": 203}

            def read_history(_github):
                events.append("history")
                return next(history_reads)

            def read_live(*_args, **_kwargs):
                events.append("live-validation")
                return current

            with patch.object(module, "_check_labels_after"), \
                    patch.object(module, "_live", side_effect=read_live), \
                    patch.object(module, "_validate_intent"), \
                    patch.object(module, "_validate_label_attempt", return_value=True), \
                    patch.object(module, "_validate_recorded_readiness"), \
                    patch.object(module, "_user_review_absent"), \
                    patch.object(module, "_read_history", side_effect=read_history), \
                    patch.object(module, "_validate_applied"), \
                    patch.object(module, "refresh_adc_forward_generation_session",
                                 side_effect=lambda *_args: events.append("refresh")):
                module._write_applied(FakeGitHub(), root, intent, current)

            post_index = events.index("post")
            self.assertEqual(events[post_index - 2:post_index], ["refresh", "live-validation"])
            self.assertEqual(events[post_index + 1:post_index + 4],
                             ["refresh", "history", "refresh"])
            self.assertEqual(events[post_index + 4], "live-validation")

    def test_label_put_boundary_invalidates_before_validation_and_after_all_outcomes(self):
        for apply_then_lose_response in (False, True):
            with self.subTest(apply_then_lose_response=apply_then_lose_response):
                events: list[str] = []

                class FakeGitHub:
                    def replace_issue_labels(self, _issue: int, _labels: list[str]) -> None:
                        events.append("put")
                        if apply_then_lose_response:
                            raise GitHubError("lost response after applying request")
                        raise GitHubError("failed before applying request")

                with patch.object(
                    module, "refresh_adc_forward_generation_session",
                    side_effect=lambda *_args: events.append("refresh"),
                ):
                    error = module._replace_issue_labels_at_boundary(
                        FakeGitHub(), module.LABELS_AFTER,
                        before_write=lambda: events.append("fresh-validation"),
                    )

                self.assertIsInstance(error, GitHubError)
                self.assertEqual(events, ["refresh", "fresh-validation", "put", "refresh"])

    def test_changed_approved_history_at_label_boundary_blocks_put(self):
        events: list[str] = []

        class FakeGitHub:
            writes = 0

            def replace_issue_labels(self, _issue: int, _labels: list[str]) -> None:
                self.writes += 1

        def reject_changed_history():
            events.append("current-adc-history-validation")
            raise module.PhaseReworkError("approved ADC history changed before label PUT")

        github = FakeGitHub()
        with patch.object(module, "refresh_adc_forward_generation_session",
                          side_effect=lambda *_args: events.append("invalidate")):
            with self.assertRaisesRegex(module.PhaseReworkError, "approved ADC history changed"):
                module._replace_issue_labels_at_boundary(
                    github, module.LABELS_AFTER, before_write=reject_changed_history,
                )

        self.assertEqual(events, ["invalidate", "current-adc-history-validation", "invalidate"])
        self.assertEqual(github.writes, 0)

    def test_v2_label_route_refreshes_before_prewrite_validation_and_issue_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent, _result = intent_record(root)
            issue_before = {"body": "fixed", "state": "open"}
            labels_before = tuple(sorted(module.LABELS_BEFORE))
            current = module._Live(**{
                **live_subject(root, labels=labels_before).__dict__, "issue": issue_before,
            })
            events: list[str] = []

            class FakeGitHub:
                def replace_issue_labels(self, _number: int, _labels: list[str]) -> None:
                    events.append("put")

            def read_live(*_args, **_kwargs):
                events.append("live-validation")
                return current

            def read_issue(_github):
                events.append("issue-readback")
                return {"body": "fixed", "state": "open"}, tuple(sorted(module.LABELS_AFTER))

            with patch.object(module, "refresh_adc_forward_generation_session",
                              side_effect=lambda *_args: events.append("refresh")), \
                    patch.object(module, "_live", side_effect=read_live), \
                    patch.object(module, "_validate_intent"), \
                    patch.object(module, "_validate_recorded_readiness"), \
                    patch.object(module, "_user_review_absent"), \
                    patch.object(module, "_issue", side_effect=read_issue):
                module._replace_labels_once(FakeGitHub(), root, intent)

            put_index = events.index("put")
            self.assertEqual(events[put_index - 2:put_index], ["refresh", "live-validation"])
            self.assertEqual(events[put_index + 1:], ["refresh", "refresh", "issue-readback"])

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
        live_reads = [live, live, live] if not after_labels else [live]
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
                                            live.recovery_authorization, live.recovery_authorization_sha256,
                                            None, None, None, None, None, None, None, None, None)), \
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
                                 return_value=(module.AUTHORIZATION, "c" * 64, None, None,
                                               None, None, None, None, None, None, None, None, None)), \
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
                                 return_value=(module.AUTHORIZATION, "c" * 64, None, None,
                                               None, None, None, None, None, None, None, None, None)), \
                    patch.object(module, "head_sha40", return_value="e" * 40), \
                    patch.object(module, "_pr", return_value={}), \
                    patch.object(module, "is_ancestor", return_value=True):
                with self.assertRaisesRegex(module.PhaseReworkError, "incomplete Intent"):
                    module.active_phase_generation_for_epoch(
                        SimpleNamespace(), root, current_adc, SimpleNamespace(), issue,
                    )


class V3PhaseReworkTests(unittest.TestCase):
    @staticmethod
    def _current_timestamp_adc(schema: str, *, checklist_count: int = 1,
                               actual_checklist_count: int = 1):
        predecessor_id, current_id = 8123400001, 8123400002
        predecessor_sha, head = "b" * 64, "c" * 40
        allowlist = ["docs/specs/workflow-spec.md", "runtime/p_ases/phase_rework.py"]
        phase_edges = [
            ["requirements", "specification"], ["specification", "design"],
            ["design", "ready"], ["ready", "execution"],
            ["execution", "verification"], ["verification", "user-review"],
        ]
        marker = {
            "approved_history": [{
                "byte_length": 123, "comment_id": predecessor_id,
                "sha256": predecessor_sha, "state": "approved",
            }],
            "branch_ref": module.BRANCH_REF,
            "checkpoint_before_publication": {"path": ".p_ases/checkpoint.json", "sha256": "d" * 64},
            "current_adc_predecessor": {
                "byte_length": 123, "comment_id": predecessor_id, "sha256": predecessor_sha,
            },
            "current_head_sha40": head,
            "current_issue": {
                "body_sha256": module.ISSUE_BODY_SHA256, "id": module.ISSUE_ID,
                "labels": ["enhancement", "kind:single", "phase:requirements"],
                "number": module.ISSUE_NUMBER, "state": "open",
            },
            "current_pr": {
                "base_ref": module.PR_BASE_REF, "base_sha40": module.PR_BASE_SHA40,
                "body_sha256": module.PR_BODY_SHA256, "draft": False,
                "head_sha40": head, "merged": False, "number": module.PR_NUMBER, "state": "open",
            },
            "followup_commit_authorization": {
                "max_commits": 1, "parent_sha40": head, "path_allowlist": allowlist,
                "require_direct_child": True, "require_push_to_existing_branch": True,
            },
            "history_boundary": {"comment_id": 8123399999, "sha256": "a" * 64},
            "issue_number": module.ISSUE_NUMBER,
            "max_same_head_binding_checkpoint_pairs": 1,
            "no_admin_ruleset_activation_issue63_merge_release_tag_or_issue_close": True,
            "owner_id": module.OWNER_ID,
            "phase_edges": phase_edges,
            "phase_reissue_policy": {
                "bind_current_committed_document_bytes_at_exact_followup_head": True,
                "documents": ["requirements", "specification", "design", "ready"],
                "preserve_historical_receipts": True,
            },
            "phase_rework_origin": dict(module.TIMESTAMP_CONTINUATION_PHASE_REWORK_ORIGIN),
            "pr_binding_before_publication": {"path": ".p_ases/pr-binding.json", "sha256": "e" * 64},
            "repository": module.REPOSITORY,
            "repository_id": module.REPOSITORY_ID,
            "required_gates_after_followup_head": ["Verification", "Acceptance", "Self-Audit"],
            "reviewer_checklist_count": checklist_count,
            "schema": schema,
            "timestamp_policy": {
                "applied_event_field": "applied_at",
                "applies_to": [module.INTENT_SCHEMA, module.APPLIED_SCHEMA,
                               module.ISSUE71_REWORK_INTENT_V3_SCHEMA,
                               module.ISSUE71_REWORK_APPLIED_V3_SCHEMA],
                "intent_event_field": "created_at", "max_skew_seconds": 300,
                "minimum_skew_seconds": 0,
                "reason": "The event timestamp is created before the GitHub POST; created_at is the server publication time. Bounded latency is validated consistently for every supported Issue #71 phase-rework record.",
                "rule": "Both timestamps must be strict UTC. comment created_at minus embedded event time must be in the inclusive range 0..300 seconds.",
                "schema": "PASES_ISSUE_PHASE_EVENT_PUBLICATION_WINDOW_V1",
            },
            "user_review": {
                "decision_allowed": False, "existing_session": "absent",
                "feedback_snapshot": "complete and immutable", "max_sessions": 1,
                "must_start_after_final_readiness_pass": True, "required_final_state": "PENDING",
            },
            "v2_record_immutability": True,
            "v3_record_immutability": True,
        }
        checkboxes = "".join(f"- [ ] checklist item {index}\n"
                              for index in range(actual_checklist_count))
        start = f"<!-- {schema}\n"
        body = (
            "# Agent Development Contract\n\n"
            f"Repository: {module.REPOSITORY}\nIssue: 71\n"
            f"Predecessor ADC: Issue #71 comment #{predecessor_id}, SHA-256 {predecessor_sha}\n\n"
            f"## Reviewer checklist\n{checkboxes}\n"
            f"{start}{json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}\n-->"
        ).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        return SimpleNamespace(
            contract=SimpleNamespace(
                content=body, repository=module.REPOSITORY,
                sha256=digest, byte_length=len(body),
            ),
            pointer=SimpleNamespace(
                comment_id=current_id, sha256=digest, byte_length=len(body), state="approved",
            ),
        )

    def test_timestamp_marker_uses_dynamic_pointer_lineage_and_versioned_checklist_rules(self):
        v1 = self._current_timestamp_adc(
            module.TIMESTAMP_CONTINUATION_AUTH_SCHEMA, checklist_count=14, actual_checklist_count=1,
        )
        v1_auth, _ = module.parse_timestamp_continuation_authorization(v1)
        self.assertEqual(v1_auth["current_adc_predecessor"]["comment_id"], 8123400001)

        v2 = self._current_timestamp_adc(module.TIMESTAMP_CONTINUATION_AUTH_SCHEMA_V2)
        v2_auth, _ = module.parse_timestamp_continuation_authorization(v2)
        self.assertEqual(v2_auth["schema"], module.TIMESTAMP_CONTINUATION_AUTH_SCHEMA_V2)

    def test_v2_timestamp_marker_rejects_checklist_count_and_path_drift(self):
        mismatch = self._current_timestamp_adc(
            module.TIMESTAMP_CONTINUATION_AUTH_SCHEMA_V2, checklist_count=2, actual_checklist_count=1,
        )
        with self.assertRaisesRegex(module.PhaseReworkError, "checklist count"):
            module.parse_timestamp_continuation_authorization(mismatch)

        bad_path = self._current_timestamp_adc(module.TIMESTAMP_CONTINUATION_AUTH_SCHEMA_V2)
        body = bad_path.contract.content.decode("utf-8")
        bad_path.contract.content = body.replace("docs/specs/workflow-spec.md", "../workflow-spec.md").encode("utf-8")
        bad_path.contract.byte_length = len(bad_path.contract.content)
        bad_path.contract.sha256 = hashlib.sha256(bad_path.contract.content).hexdigest()
        bad_path.pointer.byte_length = bad_path.contract.byte_length
        bad_path.pointer.sha256 = bad_path.contract.sha256
        with self.assertRaisesRegex(module.PhaseReworkError, "allowlist"):
            module.parse_timestamp_continuation_authorization(bad_path)

    @staticmethod
    def _timestamp_policy() -> dict:
        return {
            "schema": "PASES_ISSUE_PHASE_EVENT_PUBLICATION_WINDOW_V1",
            "applies_to": [module.INTENT_SCHEMA, module.APPLIED_SCHEMA,
                           module.ISSUE71_REWORK_INTENT_V3_SCHEMA,
                           module.ISSUE71_REWORK_APPLIED_V3_SCHEMA],
            "minimum_skew_seconds": 0,
            "max_skew_seconds": 300,
        }

    def test_current_v3_marker_uses_authorized_history_route(self):
        current = SimpleNamespace(
            contract=SimpleNamespace(content=(
                f"<!-- {module.ISSUE71_PHASE_AND_USER_REVIEW_V3_SCHEMA}\n{{}}\n-->"
            ).encode("utf-8")),
            pointer=SimpleNamespace(comment_id=7999999999, state="approved"),
        )
        github = Mock()
        with patch.object(module, "verify_issue71_phase_and_user_review_adc_chain",
                          return_value=({}, ())) as verify_chain:
            authorization = module._authorization_context(github, current)
        verify_chain.assert_called_once_with(github, current)
        self.assertEqual(authorization[0], module.AUTHORIZATION)

    def test_timestamp_continuation_readers_derive_labels_from_approved_phase_edges(self):
        issue_body = "exact Issue body"
        pr_body = "exact PR body"
        issue_body_sha = hashlib.sha256(issue_body.encode("utf-8")).hexdigest()
        pr_body_sha = hashlib.sha256(pr_body.encode("utf-8")).hexdigest()
        reader_authorization = dict(module.READER_CONTINUATION_AUTHORIZATION)
        reader_authorization.update({
            "branch_ref": module.BRANCH_REF,
            "current_issue_body_sha256": issue_body_sha,
            "pr_body_sha256": pr_body_sha,
        })
        execution_authorization = dict(
            module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION,
        )
        execution_authorization.update({
            "branch_ref": module.BRANCH_REF,
            "current_issue_body_sha256": issue_body_sha,
            "pr_body_sha256": pr_body_sha,
        })
        edges = [
            ["requirements", "specification"], ["specification", "design"],
            ["design", "ready"], ["ready", "execution"],
            ["execution", "verification"], ["verification", "user-review"],
        ]
        live = SimpleNamespace(
            current_adc=object(),
            reader_continuation_authorization=reader_authorization,
            reader_continuation_authorization_sha256=module.READER_CONTINUATION_AUTH_MARKER_SHA256,
            execution_receipt_reader_continuation_authorization=execution_authorization,
            execution_receipt_reader_continuation_authorization_sha256=(
                module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTH_MARKER_SHA256
            ),
            issue={"body": issue_body},
            labels=tuple(sorted(("enhancement", "kind:single", "phase:requirements"))),
            branch_ref=module.BRANCH_REF,
            pr={"title": module.PR_TITLE, "body": pr_body},
        )
        with patch.object(module, "READER_CONTINUATION_AUTHORIZATION", reader_authorization), \
                patch.object(module, "EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION",
                             execution_authorization), \
                patch.object(module, "_has_issue71_current_combined_marker", return_value=False), \
                patch.object(module, "_has_issue71_timestamp_continuation_marker", return_value=True), \
                patch.object(module, "parse_timestamp_continuation_authorization",
                             return_value=({"phase_edges": edges}, "f" * 64)):
            allowed = module._reader_continuation_allowed_labels(live)
            self.assertEqual(
                {row[-1].removeprefix("phase:") for row in allowed},
                {phase for edge in edges for phase in edge},
            )
            for phase in {phase for edge in edges for phase in edge}:
                live.labels = tuple(sorted((
                    "enhancement", "kind:single", f"phase:{phase}",
                )))
                module._validate_reader_continuation_subject(live)
                module._validate_execution_receipt_reader_continuation_subject(live)
            live.labels = tuple(sorted(("enhancement", "kind:single", "phase:integration")))
            with self.assertRaisesRegex(module.PhaseReworkError, "labels, branch, or PR metadata"):
                module._validate_reader_continuation_subject(live)
            with self.assertRaisesRegex(module.PhaseReworkError, "labels, branch, or PR metadata"):
                module._validate_execution_receipt_reader_continuation_subject(live)

    def test_timestamp_continuation_origin_is_distinct_from_immediate_predecessor(self):
        predecessor_id = 6969836772
        predecessor_sha = "ac67852fac757d394333d834d5f211b21157549e7dca597ea417a5bb44c5b909"
        origin = SimpleNamespace(
            pointer=SimpleNamespace(
                comment_id=module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[0],
                sha256=module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[1],
                state="approved",
            ),
            contract=SimpleNamespace(byte_length=module.TIMESTAMP_CONTINUATION_ORIGIN_BYTES),
        )
        predecessor = SimpleNamespace(
            pointer=SimpleNamespace(
                comment_id=predecessor_id,
                sha256=predecessor_sha,
                state="approved",
            ),
            contract=SimpleNamespace(byte_length=32651),
        )
        boundary = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=1, sha256="a" * 64, state="approved"),
            contract=SimpleNamespace(byte_length=1),
        )
        chain = (boundary, origin, predecessor)
        record = dict(module.TIMESTAMP_CONTINUATION_PHASE_REWORK_ORIGIN)
        self.assertIs(module._verified_timestamp_continuation_origin(chain, record), origin)
        self.assertIsNone(module._verified_timestamp_continuation_origin((boundary, predecessor), record))

        bad_record = dict(record, adc_sha256="b" * 64)
        with self.assertRaisesRegex(module.PhaseReworkError, "origin identity"):
            module._verified_timestamp_continuation_origin(chain, bad_record)
        bad_origin = SimpleNamespace(
            pointer=SimpleNamespace(
                comment_id=module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[0],
                sha256="b" * 64,
                state="approved",
            ),
            contract=origin.contract,
        )
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved bytes"):
            module._verified_timestamp_continuation_origin((boundary, bad_origin, predecessor), record)
        unapproved_origin = SimpleNamespace(
            pointer=SimpleNamespace(
                comment_id=module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[0],
                sha256=module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[1],
                state="draft",
            ),
            contract=origin.contract,
        )
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved bytes"):
            module._verified_timestamp_continuation_origin(
                (boundary, unapproved_origin, predecessor), record,
            )
        wrong_length_origin = SimpleNamespace(
            pointer=origin.pointer,
            contract=SimpleNamespace(byte_length=module.TIMESTAMP_CONTINUATION_ORIGIN_BYTES - 1),
        )
        with self.assertRaisesRegex(module.PhaseReworkError, "exact approved bytes"):
            module._verified_timestamp_continuation_origin(
                (boundary, wrong_length_origin, predecessor), record,
            )

    def test_timestamp_continuation_commit_boundary_comes_from_current_marker(self):
        start = "a" * 40
        commit = "d" * 40
        allowlist = ["docs/specs/workflow-spec.md", "runtime/p_ases/phase_rework.py"]
        authorization = {
            "current_head_sha40": start,
            "followup_commit_authorization": {
                "max_commits": 1,
                "parent_sha40": start,
                "path_allowlist": allowlist,
                "require_direct_child": True,
                "require_push_to_existing_branch": True,
            },
        }
        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=""), \
                patch.object(module, "commit_parents_sha40") as parents:
            module._verify_timestamp_continuation_commit_set(Path("/tmp/repo"), start, authorization)
        parents.assert_not_called()

        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=commit), \
                patch.object(module, "commit_parents_sha40", return_value=(start,)), \
                patch.object(module, "changed_paths_between", return_value=(allowlist[-1],)):
            module._verify_timestamp_continuation_commit_set(Path("/tmp/repo"), commit, authorization)

        invalid_cases = (
            ("wrong marker parent", {**authorization,
             "followup_commit_authorization": {**authorization["followup_commit_authorization"],
                                              "parent_sha40": "b" * 40}},
             "parent or path allowlist"),
            ("wrong marker start", {**authorization, "current_head_sha40": "b" * 40},
             "parent or path allowlist"),
            ("reordered path list", {**authorization,
             "followup_commit_authorization": {**authorization["followup_commit_authorization"],
                                              "path_allowlist": list(reversed(allowlist))}},
             "parent or path allowlist"),
        )
        for name, invalid, message in invalid_cases:
            with self.subTest(name=name), self.assertRaisesRegex(module.PhaseReworkError, message):
                module._verify_timestamp_continuation_commit_set(Path("/tmp/repo"), commit, invalid)

        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=f"{commit}\n{'e' * 40}"), \
                self.assertRaisesRegex(module.PhaseReworkError, "zero or one direct-child"):
            module._verify_timestamp_continuation_commit_set(
                Path("/tmp/repo"), "e" * 40, authorization,
            )

        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=commit), \
                patch.object(module, "commit_parents_sha40", return_value=(start, "c" * 40)), \
                self.assertRaisesRegex(module.PhaseReworkError, "direct-child"):
            module._verify_timestamp_continuation_commit_set(Path("/tmp/repo"), commit, authorization)

        with patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=commit), \
                patch.object(module, "commit_parents_sha40", return_value=(start,)), \
                patch.object(module, "changed_paths_between", return_value=("outside.py",)), \
                self.assertRaisesRegex(module.PhaseReworkError, "commit exceeds its exact path allowlist"):
            module._verify_timestamp_continuation_commit_set(Path("/tmp/repo"), commit, authorization)

    @staticmethod
    def _v2_pair() -> tuple[module.PhaseReworkRecord, module.PhaseReworkRecord]:
        intent_body = "immutable V2 Intent bytes"
        applied_body = "immutable V2 Applied bytes"
        intent = module.PhaseReworkRecord(
            101, module.INTENT_SCHEMA, {}, intent_body, module.OWNER_ID,
            "2026-11-15T00:00:00Z",
        )
        applied = module.PhaseReworkRecord(
            102, module.APPLIED_SCHEMA, {}, applied_body, module.OWNER_ID,
            "2026-11-15T00:00:01Z",
        )
        return intent, applied

    @staticmethod
    def _generation(v2_intent: module.PhaseReworkRecord,
                    v2_applied: module.PhaseReworkRecord) -> dict:
        return {
            "new_generation_number": 2,
            "preserve_prior_v2_intent_comment_id": v2_intent.comment_id,
            "preserve_prior_v2_intent_body_sha256": v2_intent.body_sha256,
            "preserve_prior_v2_applied_comment_id": v2_applied.comment_id,
            "preserve_prior_v2_applied_body_sha256": v2_applied.body_sha256,
            "predecessor_adc_comment_id": module.REWORK_ADC_COMMENT_ID - 1,
            "predecessor_adc_sha256": "d" * 64,
            "active_epoch_id": module.ACTIVE_EPOCH_ID,
            "active_epoch_sha256": module.ACTIVE_EPOCH_SHA256,
            "prior_phase_generation_comment_id": module.ACTIVE_PHASE_COMMENT_ID,
            "prior_phase_generation_sha256": module.ACTIVE_PHASE_SHA256,
            "starting_head_sha40": "e" * 40,
            "branch_ref": module.BRANCH_REF,
            "pr_number": module.PR_NUMBER,
            "pr_base_ref": module.PR_BASE_REF,
            "pr_base_sha40": module.PR_BASE_SHA40,
            "current_issue_body_sha256": module.ISSUE_BODY_SHA256,
            "labels_before": list(module.LABELS_BEFORE),
            "labels_after": list(module.LABELS_AFTER),
            "from_phase": "verification",
            "to_phase": "requirements",
            "max_applications": 1,
            "owner_id": module.OWNER_ID,
        }

    @staticmethod
    def _live(root: Path, generation: dict, *, after: bool = False) -> module._Live:
        base = live_subject(
            root, labels=tuple(sorted(generation["labels_after" if after else "labels_before"])),
        )
        digest = hashlib.sha256(module._canonical(generation).encode("utf-8")).hexdigest()
        return replace(
            base, phase_rework_generation_authorization=generation,
            phase_rework_generation_authorization_sha256=digest,
        )

    @staticmethod
    def _v3_record(schema: str, comment_id: int, payload: dict | None = None
                   ) -> module.PhaseReworkRecord:
        payload = payload or {"schema": schema, "generation_number": 2}
        body = module._record_body(schema, payload)
        timestamp = payload.get("created_at", payload.get("applied_at", "2026-11-15T00:00:02Z"))
        return module.PhaseReworkRecord(comment_id, schema, payload, body, module.OWNER_ID, timestamp)

    def test_history_preserves_v2_bytes_and_accepts_one_ordered_v3_pair(self):
        v2_intent, v2_applied = self._v2_pair()
        original = (v2_intent.body, v2_applied.body)
        generation = self._generation(v2_intent, v2_applied)
        self.assertEqual(module._v3_rework_records((v2_intent, v2_applied), generation), (None, None))
        intent = self._v3_record(module.ISSUE71_REWORK_INTENT_V3_SCHEMA, 103)
        applied = self._v3_record(module.ISSUE71_REWORK_APPLIED_V3_SCHEMA, 104)
        self.assertEqual(
            module._v3_rework_records((v2_intent, v2_applied, intent, applied), generation),
            (intent, applied),
        )
        self.assertEqual((v2_intent.body, v2_applied.body), original)

    def test_history_rejects_partial_duplicate_and_out_of_order_v3_records(self):
        v2_intent, v2_applied = self._v2_pair()
        generation = self._generation(v2_intent, v2_applied)
        intent = self._v3_record(module.ISSUE71_REWORK_INTENT_V3_SCHEMA, 103)
        applied = self._v3_record(module.ISSUE71_REWORK_APPLIED_V3_SCHEMA, 104)
        with self.assertRaisesRegex(module.PhaseReworkError, "duplicated or incomplete"):
            module._v3_rework_records((v2_intent, v2_applied, applied), generation)
        with self.assertRaisesRegex(module.PhaseReworkError, "duplicated or out of order"):
            module._v3_rework_records((v2_intent, v2_applied, intent, intent), generation)
        with self.assertRaisesRegex(module.PhaseReworkError, "duplicated or out of order"):
            module._v3_rework_records((v2_intent, v2_applied, applied, intent), generation)

    def test_v3_intent_binds_exact_current_adc_and_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v2_intent, v2_applied = self._v2_pair()
            generation = self._generation(v2_intent, v2_applied)
            live = self._live(root, generation)
            result = readiness(root)
            with patch.object(module, "_validate_readiness"):
                payload = module._v3_intent_payload(live, result)
            intent = self._v3_record(module.ISSUE71_REWORK_INTENT_V3_SCHEMA, 103, payload)
            with patch.object(module, "_validate_readiness"):
                module._validate_v3_intent(intent, live, readiness=result)
                with self.assertRaisesRegex(module.PhaseReworkError, "exact current follow-up HEAD"):
                    module._validate_v3_intent(intent, replace(live, head_sha40="f" * 40))
                stale_adc = SimpleNamespace(
                    pointer=SimpleNamespace(comment_id=live.current_adc.pointer.comment_id + 1),
                    contract=SimpleNamespace(sha256="f" * 64),
                )
                with self.assertRaisesRegex(module.PhaseReworkError, "exact ADC and active subject"):
                    module._validate_v3_intent(intent, replace(live, current_adc=stale_adc))

    def test_v2_and_v3_event_publication_window_is_uniform_and_inclusive(self):
        event = "2026-11-18T10:00:00Z"
        cases = ((0, "2026-11-18T10:00:00Z"),
                 (3, "2026-11-18T10:00:03Z"),
                 (76, "2026-11-18T10:01:16Z"),
                 (295, "2026-11-18T10:04:55Z"),
                 (300, "2026-11-18T10:05:00Z"))
        for schema in self._timestamp_policy()["applies_to"]:
            for expected_delta, published in cases:
                with self.subTest(schema=schema, delta=expected_delta):
                    self.assertEqual(
                        module._phase_event_publication_delta_seconds(
                            event, published, 300, schema,
                        ),
                        expected_delta,
                    )
        for schema in self._timestamp_policy()["applies_to"]:
            with self.subTest(schema=schema, delta=301):
                with self.assertRaisesRegex(module.PhaseReworkError, "authorized UTC skew"):
                    module._phase_event_publication_delta_seconds(
                        event, "2026-11-18T10:05:01Z", 300, schema,
                    )
            with self.subTest(schema=schema, delta=-1):
                with self.assertRaisesRegex(module.PhaseReworkError, "authorized UTC skew"):
                    module._phase_event_publication_delta_seconds(
                        "2026-11-18T10:00:01Z", event, 300, schema,
                    )
            with self.subTest(schema=schema, malformed=True):
                with self.assertRaisesRegex(module.PhaseReworkError, "canonical UTC"):
                    module._phase_event_publication_delta_seconds(
                        "2026-11-18 10:00:00Z", event, 300, schema,
                    )

    def test_v3_intent_reader_uses_origin_adc_and_generic_timestamp_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v2_intent, v2_applied = self._v2_pair()
            generation = self._generation(v2_intent, v2_applied)
            live = self._live(root, generation)
            payload = {
                "schema": module.ISSUE71_REWORK_INTENT_V3_SCHEMA,
                "generation_number": generation["new_generation_number"],
                "repository": module.REPOSITORY,
                "repository_id": module.REPOSITORY_ID,
                "issue_number": module.ISSUE_NUMBER,
                "issue_id": module.ISSUE_ID,
                "adc_comment_id": module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[0],
                "adc_sha256": module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[1],
                "authorization_sha256": live.phase_rework_generation_authorization_sha256,
                "predecessor_adc_comment_id": generation["predecessor_adc_comment_id"],
                "predecessor_adc_sha256": generation["predecessor_adc_sha256"],
                "epoch_origin_adc_comment_id": module.EPOCH_ORIGIN_ADC_COMMENT_ID,
                "epoch_origin_adc_sha256": module.EPOCH_ORIGIN_ADC_SHA256,
                "active_epoch_id": generation["active_epoch_id"],
                "active_epoch_sha256": generation["active_epoch_sha256"],
                "active_phase_generation_comment_id": generation["prior_phase_generation_comment_id"],
                "active_phase_generation_sha256": generation["prior_phase_generation_sha256"],
                "baseline_head_sha40": generation["starting_head_sha40"],
                "bootstrap_head_sha40": generation["starting_head_sha40"],
                "branch_ref": generation["branch_ref"],
                "pr_number": generation["pr_number"],
                "pr_base_ref": generation["pr_base_ref"],
                "pr_base_sha40": generation["pr_base_sha40"],
                "pr_head_sha40": generation["starting_head_sha40"],
                "readiness_sha256": "a" * 64,
                "readiness_subject_sha256": "b" * 64,
                "issue_body_sha256": generation["current_issue_body_sha256"],
                "labels_before": generation["labels_before"],
                "labels_after": generation["labels_after"],
                "from_phase": generation["from_phase"],
                "to_phase": generation["to_phase"],
                "max_applications": generation["max_applications"],
                "owner_id": generation["owner_id"],
                "executor_user_id": module.OWNER_ID,
                "created_at": "2026-11-18T10:00:00Z",
            }
            body = module._record_body(module.ISSUE71_REWORK_INTENT_V3_SCHEMA, payload)
            intent = module.PhaseReworkRecord(
                103, module.ISSUE71_REWORK_INTENT_V3_SCHEMA, payload, body,
                module.OWNER_ID, "2026-11-18T10:04:55Z",
            )
            current_adc = SimpleNamespace(
                pointer=SimpleNamespace(comment_id=6969836772),
                contract=SimpleNamespace(
                    sha256="ac67852fac757d394333d834d5f211b21157549e7dca597ea417a5bb44c5b909",
                ),
            )
            current = replace(
                live, current_adc=current_adc,
                phase_rework_origin_adc_comment_id=module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[0],
                phase_rework_origin_adc_sha256=module.TIMESTAMP_CONTINUATION_ORIGIN_ADC[1],
                timestamp_policy=self._timestamp_policy(),
            )
            module._validate_v3_intent(intent, current)
            too_late = replace(intent, created_at="2026-11-18T10:05:01Z")
            with self.assertRaisesRegex(module.PhaseReworkError, "authorized UTC skew"):
                module._validate_v3_intent(too_late, current)

    def test_v3_apply_writes_once_and_exact_retry_is_noop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v2_intent, v2_applied = self._v2_pair()
            generation = self._generation(v2_intent, v2_applied)
            before = self._live(root, generation)
            after = self._live(root, generation, after=True)
            result = readiness(root)
            history = [v2_intent, v2_applied]
            events: list[str] = []

            class FakeGitHub:
                repo = module.REPOSITORY
                label_writes = 0

                def replace_issue_labels(self, _number: int, _labels: list[str]) -> None:
                    self.label_writes += 1
                    events.append("put")

            github = FakeGitHub()
            next_comment_id = 103
            posts: list[str] = []

            def post_once(_github, local_root, schema, payload, *, before_write=None):
                nonlocal next_comment_id
                if before_write is not None:
                    before_write()
                operation = {
                    module.ISSUE71_REWORK_INTENT_V3_SCHEMA: "intent_v3",
                    module.ISSUE71_REWORK_APPLIED_V3_SCHEMA: "applied_v3",
                }[schema]
                module._write_attempt_once(local_root, operation, payload)
                record = self._v3_record(schema, next_comment_id, dict(payload))
                next_comment_id += 1
                history.append(record)
                posts.append(schema)
                return record

            def verify_v3_subject(_github, _root, _live, *, expected_labels):
                events.append(
                    "verify-before" if tuple(expected_labels) == tuple(generation["labels_before"])
                    else "verify-after"
                )

            def read_issue(_github):
                events.append("issue-readback")
                return ({"body": before.issue.get("body"), "state": "open"},
                        tuple(sorted(generation["labels_after"])))

            with patch.object(module, "_live", side_effect=[before, after]), \
                    patch.object(module, "_read_history", side_effect=lambda _github: tuple(history)), \
                    patch.object(module, "_user_review_absent"), \
                    patch.object(module, "_validate_readiness"), \
                    patch.object(module, "_validate_v3_intent"), \
                    patch.object(module, "_validate_v3_recorded_readiness"), \
                    patch.object(module, "_validate_v3_applied"), \
                    patch.object(module, "_verify_v3_subject", side_effect=verify_v3_subject), \
                    patch.object(module, "_issue", side_effect=read_issue), \
                    patch.object(module, "refresh_adc_forward_generation_session",
                                 side_effect=lambda *_args: events.append("refresh")), \
                    patch.object(module, "_post_record_once", side_effect=post_once):
                applied_result = module.apply_issue71_phase_rework(
                    github, root, 71, readiness_factory=lambda: result,
                )
            self.assertEqual(applied_result["status"], "APPLIED")
            self.assertEqual(applied_result["label_write_count"], 1)
            self.assertEqual(github.label_writes, 1)
            self.assertEqual(posts, [module.ISSUE71_REWORK_INTENT_V3_SCHEMA,
                                     module.ISSUE71_REWORK_APPLIED_V3_SCHEMA])
            put_index = events.index("put")
            self.assertEqual(events[put_index - 2:put_index], ["refresh", "verify-before"])
            self.assertEqual(
                events[put_index + 1:put_index + 5],
                ["refresh", "refresh", "issue-readback", "refresh"],
            )
            self.assertEqual(events[put_index + 5], "verify-after")

            with patch.object(module, "_live", return_value=after), \
                    patch.object(module, "_read_history", return_value=tuple(history)), \
                    patch.object(module, "_validate_v3_intent"), \
                    patch.object(module, "_validate_v3_recorded_readiness"), \
                    patch.object(module, "_validate_v3_applied"), \
                    patch.object(module, "_post_record_once") as post_again:
                retry_result = module.apply_issue71_phase_rework(github, root, 71)
            self.assertEqual(retry_result["status"], "NOOP")
            self.assertEqual(retry_result["label_write_count"], 0)
            self.assertEqual(github.label_writes, 1)
            post_again.assert_not_called()

    def test_partial_v3_intent_fails_without_retrying_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v2_intent, v2_applied = self._v2_pair()
            generation = self._generation(v2_intent, v2_applied)
            live = self._live(root, generation)
            intent = self._v3_record(module.ISSUE71_REWORK_INTENT_V3_SCHEMA, 103)
            class FakeGitHub:
                repo = module.REPOSITORY
                label_writes = 0

                def replace_issue_labels(self, _number: int, _labels: list[str]) -> None:
                    self.label_writes += 1

            github = FakeGitHub()
            with patch.object(module, "_validate_v3_intent"), \
                    patch.object(module, "_validate_v3_recorded_readiness"), \
                    patch.object(module, "_post_record_once") as post_again, \
                    self.assertRaisesRegex(module.PhaseReworkError, "partial; retry writes are prohibited"):
                module._apply_v3_phase_rework(
                    github, root, live, (v2_intent, v2_applied, intent), None,
                )
            self.assertEqual(github.label_writes, 0)
            post_again.assert_not_called()


WINDOWS_PROFILE_MARKER_FIXTURE_B64 = (
    'eNrtW2tvG8cV/Z5f0fKzGM37IRQFDEeABaS2YdnOB8NYzOOOtQ1FMnzYUYz8955ZktJSpBTWlVK3MAxb4u7szJ37OPecWfpvfx0O'
    '//LyyfnpeXN2fv7mtHn5DB+aJ89/aN6cn75qXp2+PTv9qXkrvvs8CGnRfqQmLBcXk1n7W1i0k3GT2w80X8wHJ58HaTJetONld31w'
    'MuA2Sa6UkiKqpIOXnCXtSjLCKqOktyyWkGWSrBjvUtaaZUfBae6kyFkOjgZpOZvReNHkSVpe1l/m4zCdX0wWmN4Lbp2O+GuSDZyU'
    'stFw64uT3BanGJYiyt4mE6IUxhbGVNbJsOINzwnT06+Ult0uZpSonS7wM2SaNbd2IkOxMJiiZI6c9ckK65WQ2hMnLk1ymrSXpCzj'
    'TJERnKdQMnbqdcbvWOqinS/gtBRGN5uZUTufLwkLUPEsumCV90IH40u22WjOs4eHCpE0wcJV3YaMZ+SjDEpKybBtybXBAt1UljfL'
    'Oeyf0ceWPmHixApPTHoMFczA/0wYSabwwIWQHNNzybzWgkTBhLYIrOdtFrxw7oTHxNOLMKeeg+Cb1I7ajW+cJVmETSEJGCZMYNxl'
    'WEeGB5tJURbJ8pgTi3A7D8ZIZpXjRjhlvMxYYb/TSylOBB8iR/iK5NIlZhTs9AixYIFsKCwHWaww2hZkUEhRZx2xNXJKdROnyUea'
    'XVVHmMgMwc6YZS4wxrKsrU4hBiFhk2PFhWK04YWSQKwFWR09YyEjZ1nqZvs0mf1c54KrDP5wxSxpHk0SwmcRETOJHOHOG6RJKMIb'
    'g5CJ7L100cXkHEVL1amL9hJVEy6nTc9G51ARTsBIb53TgVkncoypOiwqHZVH5IoKSggdjUzO4h/cJwYXR2cGvx9tapSmk3TRtBmz'
    'ahaKcsEFlr3ADos0Ahlludeea5GxTx3gDm0Nw9w24KomWCy1JWxjcGvS+UUQyLiTAXMmOIL3GA/OeIQ6GYuFGGETDlXBU7EmaxZR'
    'I9iQ0S4yQUzapHlm7GbiVYp9oDHNVqCSJpddhdQNGOe8N1pKfff4a5vgBeVSQc75xJX1tm5GARWY8bEkGbUNUSckuEmpCA2sAVDY'
    'nIp0LnJXbZpORy3lJk7y1aNMfOfmptMZUiE3K6xARrz7PIhXC2pGNP6wuBiccKm5BypuT2A855axo8G1sUEmblE2SsUiuNKBcCMi'
    'QjJKXZDeOjKFIiQfshDCOWWTlYBOBfSSukYGybmoyLQxCrl12xjgk9wxxirhrfQ9Y5LK5EsCzrhkJEqWZAwqOgGYC9aicJJ0eBJV'
    'JQBQngGWgHxITZEi8utAYzTjO8Y4A2Twuu8ZjjLlzgIDVeAAR+6DdIA8RVonb5JR2aTI4SRUNkPvQg5nxThHkyFVDjTGGnHbGECJ'
    'Y8LanjG6oDBEiUFjVbTHHLAMeqJXRQbBqQDspM5eSUKeIZRIKMpFoPMkLZI+yBjPnduxhTv0Qi76UQoC0I/yLwUIhgRPKWEbRjEt'
    'FMKDbooiR+wowJDES9S4mIKUESPcgSlj0IN2jfHCGNGPklHJZXSRRADtoonVoKD9WqzIInofpkFpGbALVvtvZCymXICGCCTA6DDH'
    'oO3t2CKl0whT3xa09uSjFy6Rjqh5CsiFAmCvCJ+5M2j6AFdQmiyFgokAiNpjPaUM5nGgY5yQu8ZobZU2PWMi9zkFRESCMGRvMuOV'
    'CIBgcfRn7QDwErXmQI0owh8loYQKq4Et2fFyaJTsrjEgctzqvme8zzGzYi0VmFV0iT4Hg0siZRdRvlKTiyWib6HgVArAGWQQNzrB'
    'HuUPM0YovWuMUQpT9j1TqwbbB2uSCYSndrdYAQBbIa8yA/VApLTSTGsAtg45mmjR/J2nSj8OM0ZJ53eNAeE0vA95BfkRE1oDPgJq'
    '0RfQ9ZBFHvxNgAvzIH1FFOIpAhMlyIlF6AB5iJFx6jBjHHywY4xFAksle8ZQpoweBIRHtw6EassqgmMIVHjKPNSyR8cOJnNVKReg'
    'V0Qw8QLGiVZuDzJGIMTmljGeoRUgEFvGBJsKyiMZEDYw44zGqVhhcIq1gD4RKCkqGqZkaTxiL8D/eAbFAc8R6TBj0ITYjjEKQMNF'
    'v02yhFryCbSKG0KnoZCSgDpJwBrgr0G+cAkqDKKsZCATQZ8UUNqqoAO0zUHGSEiF2wnswRs42zamEDKRcc2s4cLzkplF8RcCKc0C'
    'cAL8VYkKGCXiYguh5KXQqvJdD8Ww35j3R4M4C2OwthkV3JmCN82PO6kwtHw4mkCPDDtS1fGo4Ucx7LjVcEYRP0btmIYd6xveq8a2'
    'JWGVgo+w6nyynCW6WfxaeIIlTUN19QD35seZ5u2H8XHl6mU0+TRcff7+siqNa2+DDgkCJNTeTshEdJnkC+hRiFW0qaIyOH52wrJa'
    'HwJIVmWZUGgHoAmsi3N/1fmU8O/1ovXjrSUZKHbFADBIVJ3y+APyzhBmlGIWXWNxQoGTWYVEMEA0jmam8VEWV1bR7JzYjJeXkWaD'
    'E8urKplO5m3li11uQZMgzUE0cGueLugyYOmevodCfPrm1avT56+bH148ffOP+sv58ycvz5+9eN287bJo5eeasO2imU5GbarihH5F'
    'xJpNMKbL+UVlqoDOqjo2l1fmbTNnXWAP+jlhu6APCdAHEsNdrPwvEisqKVGlDxS0tgzCARrEVbVmgwmyatsyGcGpy2lTPd6E+mEE'
    'jozQDzJ+HgcIxw+z8LFdXB3/YQ7sf+LO+O0Mny3HVb0dT5surdOo/X56dcDAySfIle1KOezBjQCvxh34xGxS2hH1BqdRWGY60Dn9'
    'wff7ZT3yXpfsH3O/N/Y/c4cj7hi844PJlMahPdAH/cH3+2A98l4f7B9zvw/2P3OHD+4YvOWDP9z3/XutdxdA3Hb84bhD9OGoLZSu'
    '0oiG9fp8z7i1PXfeX8xCgqBoR0ji1e273Hio6/7QXfe5qDOzM665c4HemNXk9LHNNE50x+3+2r2bvWO6Zr1JwHuZTX6jcRNXD9be'
    'eRna8WD7BpBVsa6hKMdTPRmC5AE3Z8FAtXKAJsA1lwwpr0BvxP2nj4/bu2eT+bx/ULNq2g39sgw15ljkl2U7A1U5KWE0p5tOUjvL'
    '9U4TxBX4l/ZUQiCnTQjZGJ+NTzJCJYOVU8ndIct1gzr0SOnOBx7y6OdROAwrZMFcwWGL1C4X5nhMYCmqEHNGi8RyJffYJYNgZFQP'
    'H50jbaSPCiL3CzgM9kRaBog5Gyk5ZB2IO0FzMEc+EynmdSoO3R4xCUqUwonApEoGnQnWdRzmz0zya/rykWZtuWpWLKYS9HkTkIeh'
    'S/Sbo+1ZXh/QtYvtGTeDQk7NXecXdwx/yGONPUusidrGYVFyyBpRD5M0cQcJByGjQWSNqKeExWboiszC3slWmbjN34xVTEDFO6WN'
    'dQrqzErvncFWQkC8ITiFKaR4hKRJmTEIN5EMAw9NSccq8285TNSzYO26XtCF6QsLAGoMVVegnoOSiYWEdZ3K0NSCJ21YzFmqiKRk'
    'CsoSKa+ihrYFP45GKQ0S/76Ta1vbJfIlBu6hQWuUINmBPBJOjDkg14NWIbFSVX0gKwiKDMAnvSWjpIRz9mzXewjJr2G7/3a9K86U'
    'MUhErQ2POlqWQiksMujkaCFkKBidDZR8KNYFqJX60gdU3sVSPEvVw3tVy3S2p/43F7+g9vHo9fS6iqLVkrs4ENtxbra1zKqAFij8'
    '6wBVbNgndfpyqzbHZbpox1fhOLTDgNaxGG6cOfgSYfbs7Pz1i1dnT5/8eKPNXp2uXstCmv2+qdirZoqWiYqdzydw2WQ5zqHa83nn'
    'zQAqlQvVP7NLwiGNmUcT1cWqUmIVmJhLekhNiFMujMrWywRFiuQRpLNA243JJWjVakQ7XtQ1tssm1PdfqHafK7gEztEuCxPcMNQM'
    '1bNQL51B4primBRMyqDQKSzpmHWkepa9nvf2GX59UaHc3hecu9wFXmnnXbsPs1mLgbupdz3kVhT6r7t/OH16dn724nnzVnYMG/AI'
    'wy5qVkzGpZ1dhvVb4w17WcyWtDbRyCakGhvMPJ6MabAv/y/Dr83GkHkzhaGgWfNuE7i7Ip/VAdIqZevJ2q0EB239Z7VpTV9v4iC9'
    'kdYLKxjcrFyt2SjQedF+E/MhCpdTRmPhnJmAJg1IM8IrBKm4+lr1/sRdu/1ykus503wymqyI8uDOnD5/8eOL5sVPz+HbvoOfvHn9'
    'bH3csIzdTkpLo1yRcdDrmeAE4A8xpJ9vrsATPXK4ensM1gmeeT1kbebapZvr73/fRKJLLS41Nm613RefUYg06mBgvgiz7qSBxhfg'
    'xVRzE0v8DBw5mUPDjGjzjvxkhdqVx9fwXh9arPBlfmdk732//vnbG93/3Te6D6ikvh2BfTsC+3YE9u0I7NsR2H9+OvBNyz+Clv9y'
    '0xHYy1Wm4Lk1pV7J5A05OoBHPCqBWEyu7ato0Bb4uaNnf+rxwQN5eHsHX6GL1zS6Ozj4L0rNh3+N+TWKD5qtzz42xx0V5Sh/oAof'
    '726X43buvD96t5NN12a82/y6UmjA9vf95bo9Nmh+Y0jNKoK75W4/cvRu/Vvvu9rd1ZtPR6uj3b5NWxeOBrXPDNffiO6MePizp+1U'
    '4aLInHRWOrgUfOaoBogow1Ckun67jokAcM3SZymL4QEit35jOXpJpXTfuNmR+zfnPTtdq/dtktvjHvLbJZsztQdIjvePeI62/g8M'
    'r06fnp69rOdnT188f3r249mT1/U8p3fuUEsLJbT9pgllqQrwizkuC3ElEf6Y0dBFUTmq+rVu4YTvvmr9f5BH+76p9HXk2uNmx+5/'
    'b3mAjPhuOPz7vwByiJfR'
)

class CombinedAuthorizationTests(unittest.TestCase):
    @staticmethod
    def _with_test_historical_segment(marker: bytes) -> bytes:
        prefix = b"<!-- PASES_ISSUE_PHASE_AND_USER_REVIEW_V2\n"
        suffix = b"\n-->"
        value = json.loads(marker[len(prefix):-len(suffix)])
        phase = value["phase_receipt_reconciliation"]
        approval = value["approved_history"][-1]
        phase["historical_commit_segments"] = [{
            "adc_comment_id": approval["comment_id"],
            "adc_sha256": approval["sha256"],
            "parent_sha40": module.APPROVED_HISTORY_READER_AUTHORIZATION[
                "starting_head_sha40"
            ],
            "commit_sha40": phase["starting_head_sha40"],
            "path_allowlist": ["runtime/p_ases/phase_rework.py"],
        }]
        value["active_authorization_digests"]["phase_receipt_reconciliation"] = (
            hashlib.sha256(module._canonical(phase).encode("utf-8")).hexdigest()
        )
        return prefix + module._canonical(value).encode("utf-8") + suffix

    @staticmethod
    def _windows_profile_verified(marker: bytes | None = None):
        if marker is None:
            marker = zlib.decompress(base64.b64decode(WINDOWS_PROFILE_MARKER_FIXTURE_B64))
        marker = CombinedAuthorizationTests._with_test_historical_segment(marker)
        content = (
            "# Agent Development Contract — Issue #71 Windows-stable profile identity and phase continuation\n\n"
            "Repository: puchinya/ai-agent-workflow\n"
            "Predecessor ADC: Issue #71 comment #6917910120, SHA-256 "
            "fe89e0150761291fd07745feaf6d23e68fa4cef66f7ad7feb413254d5ba9a691\n\n"
            "## Artifact impact\n\n"
            f"{module.ISSUE71_WINDOWS_PROFILE_READER_ARTIFACT_IMPACT}\n\n"
        ).encode("utf-8") + marker + b"\n"
        digest = hashlib.sha256(content).hexdigest()
        contract = SimpleNamespace(
            sha256=digest,
            byte_length=len(content),
            repository=module.REPOSITORY,
            content=content,
            section=lambda _name: module.ISSUE71_WINDOWS_PROFILE_READER_ARTIFACT_IMPACT,
        )
        return SimpleNamespace(
            pointer=SimpleNamespace(
                comment_id=module.ISSUE71_WINDOWS_PROFILE_READER_ADC_COMMENT_ID,
                sha256=digest,
                state="approved",
            ),
            contract=contract,
        ), digest, len(content)

    @staticmethod
    def _windows_fixture_verified():
        prefix = b"<!-- PASES_ISSUE_PHASE_AND_USER_REVIEW_V2\n"
        suffix = b"\n-->"
        previous = zlib.decompress(base64.b64decode(WINDOWS_PROFILE_MARKER_FIXTURE_B64))
        value = json.loads(previous[len(prefix):-len(suffix)])
        history_entries = (
            {
                "byte_length": module.ISSUE71_WINDOWS_PROFILE_READER_ADC_BYTES,
                "comment_id": module.ISSUE71_WINDOWS_PROFILE_READER_ADC_COMMENT_ID,
                "sha256": module.ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256,
                "state": "approved",
            },
            {
                "byte_length": module.ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_BYTES,
                "comment_id": module.ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_COMMENT_ID,
                "sha256": module.ISSUE71_WINDOWS_FIXTURE_READER_PREDECESSOR_ADC_SHA256,
                "state": "approved",
            },
            {
                "byte_length": 25230,
                "comment_id": 6920550362,
                "sha256": "c2ace5524388354b2b78394d4cd7165070a1a858d4b71cff7440c628dcf45664",
                "state": "approved",
            },
            {
                "byte_length": 27319,
                "comment_id": 6923286006,
                "sha256": "a4409eaf60f18138e7465263b3df938ccbc9396a7adc04b16e960d6f13830f29",
                "state": "approved",
            },
            {
                "byte_length": 29094,
                "comment_id": 6923451031,
                "sha256": "56bbf15be816c894f23333b275e0ceaa98a0328cf0db5565f24093895b059fbb",
                "state": "approved",
            },
            {
                "byte_length": 19648,
                "comment_id": 6924871574,
                "sha256": "998da293cc84b1e472fb438c125295ac806da6b823fe60a9a7a22f110771b88f",
                "state": "approved",
            },
            {
                "byte_length": 18621,
                "comment_id": 6925118922,
                "sha256": "e1b1b4b2c83c0022571b9b07d63b01f38eaaa8dde027a0996ce4f786449f21bc",
                "state": "approved",
            },
            {
                "byte_length": 18358,
                "comment_id": 6925241207,
                "sha256": "6ae7ba3fb203c7c0cb3ddde817c4e7a4ca1f9f690a42a79d3ae4b83454b1a141",
                "state": "approved",
            },
        )
        value["approved_history"].extend(history_entries)
        predecessor = history_entries[-1]
        paths = [
            "dist/antigravity/runtime/p_ases/phase_rework.py",
            "dist/claude/runtime/p_ases/phase_rework.py",
            "dist/openai/runtime/p_ases/phase_rework.py",
            "runtime/p_ases/phase_rework.py",
            "tests/test_phase_rework.py",
        ]
        phase = value["phase_receipt_reconciliation"]
        phase.update(
            predecessor_adc_comment_id=predecessor["comment_id"],
            predecessor_adc_sha256=predecessor["sha256"],
            starting_head_sha40="588b6f73b41477960cb0ad9a0e01b2ebe9d50ba3",
            followup_path_allowlist=paths,
        )
        value["active_authorization_digests"]["phase_receipt_reconciliation"] = hashlib.sha256(
            module._canonical(phase).encode("utf-8")
        ).hexdigest()
        value.update(
            predecessor_adc_byte_length=predecessor["byte_length"],
            predecessor_adc_comment_id=predecessor["comment_id"],
            predecessor_adc_sha256=predecessor["sha256"],
            starting_head_sha40="588b6f73b41477960cb0ad9a0e01b2ebe9d50ba3",
            followup_path_allowlist=paths,
        )
        marker = CombinedAuthorizationTests._with_test_historical_segment(
            prefix + module._canonical(value).encode("utf-8") + suffix
        )
        value = json.loads(marker[len(prefix):-len(suffix)])
        canonical = module._canonical(value).encode("utf-8")
        marker = prefix + canonical + suffix
        q = chr(96)
        artifact_impact = (
            f"- Specification: {q}docs/specs/workflow-spec.md{q}.\n"
            f"- Design: {q}docs/design/workflow-design.md{q}.\n"
            f"- Testing: {q}docs/testing/pases-lifecycle-tests.md{q}, "
            f"{q}docs/testing/runtime-tests.md{q}, {q}docs/testing/traceability.md{q}.\n"
            f"- Runtime implementation: {q}runtime/p_ases/phase_evidence.py{q}, "
            f"{q}runtime/p_ases/phase_rework.py{q}.\n"
            f"- Tests: {q}tests/test_phase_evidence.py{q}, {q}tests/test_phase_rework.py{q}.\n"
            "- Generated mirrors: the six matching phase_evidence.py and phase_rework.py files under "
            "Antigravity, Claude, and OpenAI."
        )
        content = (
            "# Agent Development Contract — Issue #71 generic marker and phase-evidence completion\n\n"
            "Repository: puchinya/ai-agent-workflow\n"
            "Predecessor ADC: Issue #71 comment #6925241207, SHA-256 "
            "6ae7ba3fb203c7c0cb3ddde817c4e7a4ca1f9f690a42a79d3ae4b83454b1a141\n\n"
            "## Artifact impact\n\n"
            f"{artifact_impact}\n\n"
        ).encode("utf-8") + marker + b"\n"
        digest = hashlib.sha256(content).hexdigest()
        contract = SimpleNamespace(
            sha256=digest,
            byte_length=len(content),
            repository=module.REPOSITORY,
            content=content,
            section=lambda _name: artifact_impact,
        )
        return SimpleNamespace(
            pointer=SimpleNamespace(comment_id=7999999999, sha256=digest, state="approved"),
            contract=contract,
        ), digest, len(content), marker

    def test_windows_profile_current_marker_accepts_exact_authorized_generation(self):
        verified, digest, byte_length = self._windows_profile_verified()
        with patch.object(module, "ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256", digest), \
                patch.object(module, "ISSUE71_WINDOWS_PROFILE_READER_ADC_BYTES", byte_length):
            authorization = module.parse_issue71_phase_and_user_review_authorization(verified)
        self.assertEqual(authorization["predecessor_adc_comment_id"],
                         module.ISSUE71_COMPREHENSIVE_READER_ADC_COMMENT_ID)
        self.assertEqual(len(authorization["approved_history"]), 15)
        self.assertEqual(len(authorization["followup_path_allowlist"]), 31)
        self.assertEqual(authorization["followup_path_allowlist"],
                         list(module.ISSUE71_WINDOWS_PROFILE_READER_PATH_ALLOWLIST))
        self.assertEqual(
            authorization["current_document_snapshot_authorization"],
            module.ISSUE71_WINDOWS_PROFILE_CURRENT_DOCUMENT_SNAPSHOT_AUTHORIZATION,
        )

    def test_generic_current_marker_accepts_unseen_pointer_after_exact_history(self):
        verified, digest, byte_length, marker = self._windows_fixture_verified()
        authorization = module.parse_issue71_phase_and_user_review_authorization(verified)
        self.assertEqual(verified.pointer.comment_id, 7999999999)
        self.assertEqual(verified.pointer.sha256, digest)
        self.assertEqual(verified.contract.byte_length, byte_length)
        self.assertGreater(len(marker), 0)
        self.assertEqual(authorization["predecessor_adc_comment_id"], 6925241207)
        self.assertEqual(len(authorization["approved_history"]), 23)
        self.assertEqual(
            authorization["followup_path_allowlist"],
            [
                "dist/antigravity/runtime/p_ases/phase_rework.py",
                "dist/claude/runtime/p_ases/phase_rework.py",
                "dist/openai/runtime/p_ases/phase_rework.py",
                "runtime/p_ases/phase_rework.py",
                "tests/test_phase_rework.py",
            ],
        )
        self.assertEqual(
            authorization["current_document_snapshot_authorization"],
            module.ISSUE71_WINDOWS_PROFILE_CURRENT_DOCUMENT_SNAPSHOT_AUTHORIZATION,
        )

    def test_generic_current_marker_requires_complete_ordered_historical_commit_segments(self):
        verified, _digest, _byte_length, marker = self._windows_fixture_verified()
        prefix = b"<!-- PASES_ISSUE_PHASE_AND_USER_REVIEW_V2\n"
        suffix = b"\n-->"
        start = marker.index(prefix)
        end = marker.index(suffix, start) + len(suffix)
        original = marker[start:end]
        base = json.loads(original[len(prefix):-len(suffix)])
        invalid_cases = (
            ("missing map", lambda phase: phase.pop("historical_commit_segments"),
             "unknown or missing fields"),
            ("wrong ADC digest", lambda phase: phase["historical_commit_segments"][0].update(
                adc_sha256="0" * 64), "approved ADC history row"),
            ("chain gap", lambda phase: phase["historical_commit_segments"][0].update(
                parent_sha40="1" * 40), "gap, duplicate"),
            ("noncanonical paths", lambda phase: phase["historical_commit_segments"][0].update(
                path_allowlist=["z.py", "a.py"]), "path allowlist is malformed"),
        )
        for name, mutate, message in invalid_cases:
            with self.subTest(name=name):
                value = json.loads(json.dumps(base))
                phase = value["phase_receipt_reconciliation"]
                mutate(phase)
                value["active_authorization_digests"]["phase_receipt_reconciliation"] = (
                    hashlib.sha256(module._canonical(phase).encode("utf-8")).hexdigest()
                )
                altered = prefix + module._canonical(value).encode("utf-8") + suffix
                content = verified.contract.content.replace(original, altered, 1)
                digest = hashlib.sha256(content).hexdigest()
                contract = SimpleNamespace(
                    sha256=digest, byte_length=len(content), repository=module.REPOSITORY,
                    content=content, section=verified.contract.section,
                )
                candidate = SimpleNamespace(
                    pointer=SimpleNamespace(
                        comment_id=verified.pointer.comment_id, sha256=digest, state="approved",
                    ),
                    contract=contract,
                )
                with self.assertRaisesRegex(module.PhaseReworkError, message):
                    module.parse_issue71_phase_and_user_review_authorization(candidate)

    def test_generic_current_marker_still_requires_its_predecessor_header(self):
        verified, _digest, _byte_length, _marker = self._windows_fixture_verified()
        content = verified.contract.content.replace(
            b"Predecessor ADC: Issue #71 comment #6925241207, SHA-256 "
            b"6ae7ba3fb203c7c0cb3ddde817c4e7a4ca1f9f690a42a79d3ae4b83454b1a141\n",
            b"",
            1,
        )
        digest = hashlib.sha256(content).hexdigest()
        verified.contract.content = content
        verified.contract.sha256 = digest
        verified.contract.byte_length = len(content)
        verified.pointer.sha256 = digest
        with self.assertRaisesRegex(module.PhaseReworkError, "exactly one predecessor header"):
            module.parse_issue71_phase_and_user_review_authorization(verified)

    def test_generic_current_marker_verifies_full_chain_for_unseen_pointer(self):
        verified, _digest, _byte_length, _marker = self._windows_fixture_verified()
        authorization = module.parse_issue71_phase_and_user_review_authorization(verified)

        def historical(item, predecessor):
            if item["comment_id"] == 6924871574:
                body = b"Historical approved ADC without a body-level predecessor header\n"
            else:
                body = (
                    f"Predecessor ADC: Issue #71 comment #{predecessor[0]}, "
                    f"SHA-256 {predecessor[1]}\n"
                ).encode("utf-8")
            body += b" " * (item["byte_length"] - len(body))
            return SimpleNamespace(
                pointer=SimpleNamespace(
                    comment_id=item["comment_id"], sha256=item["sha256"], state="approved",
                ),
                contract=SimpleNamespace(
                    sha256=item["sha256"], byte_length=item["byte_length"],
                    repository=module.REPOSITORY, content=body,
                ),
            )

        boundary = module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY
        boundary_body = b"x" * 512
        rows = [SimpleNamespace(
            pointer=SimpleNamespace(comment_id=boundary[0], sha256=boundary[1], state="approved"),
            contract=SimpleNamespace(
                sha256=boundary[1], byte_length=len(boundary_body),
                repository=module.REPOSITORY, content=boundary_body,
            ),
        )]
        previous = boundary
        for item in authorization["approved_history"]:
            rows.append(historical(item, previous))
            previous = (item["comment_id"], item["sha256"])
        rows.append(verified)
        github = SimpleNamespace()
        with patch.object(module, "verify_adc_forward_generations", return_value=tuple(rows)) as verify:
            parsed, chain = module.verify_issue71_phase_and_user_review_adc_chain(
                github, verified,
            )
        self.assertEqual(parsed, authorization)
        self.assertEqual(len(chain) - 2, 23)
        verify.assert_called_once_with(
            github, module.ISSUE_NUMBER,
            prior_comment_id=boundary[0], prior_sha256=boundary[1],
            current_comment_id=verified.pointer.comment_id,
            current_sha256=verified.contract.sha256,
        )

        headerless = next(row for row in rows if row.pointer.comment_id == 6924871574)
        item = next(row for row in authorization["approved_history"]
                    if row["comment_id"] == 6924871574)
        conflict = (
            "Predecessor ADC: Issue #71 comment #1, SHA-256 " + "0" * 64 + "\n"
        ).encode("utf-8")
        headerless.contract.content = conflict + b" " * (item["byte_length"] - len(conflict))
        with patch.object(module, "verify_adc_forward_generations", return_value=tuple(rows)):
            with self.assertRaisesRegex(
                    module.PhaseReworkError, "historical ADC predecessor header differs"):
                module.verify_issue71_phase_and_user_review_adc_chain(github, verified)

    def test_windows_profile_current_marker_rejects_unapproved_allowlist_change(self):
        marker = zlib.decompress(base64.b64decode(WINDOWS_PROFILE_MARKER_FIXTURE_B64))
        prefix = b"<!-- PASES_ISSUE_PHASE_AND_USER_REVIEW_V2\n"
        suffix = b"\n-->"
        raw = marker[len(prefix):-len(suffix)]
        value = json.loads(raw)
        value["followup_path_allowlist"][-1] = "tests/z.py"
        import p_ases.phase_rework as phase_module
        altered_marker = prefix + phase_module._canonical(value).encode("utf-8") + suffix
        verified, digest, byte_length = self._windows_profile_verified(altered_marker)
        with patch.object(module, "ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256", digest), \
                patch.object(module, "ISSUE71_WINDOWS_PROFILE_READER_ADC_BYTES", byte_length), \
                patch.object(module, "ISSUE71_WINDOWS_PROFILE_READER_MARKER_BYTES", len(altered_marker)), \
                patch.object(module, "ISSUE71_WINDOWS_PROFILE_READER_MARKER_SHA256",
                             hashlib.sha256(altered_marker).hexdigest()):
            with self.assertRaisesRegex(module.PhaseReworkError, "differs"):
                module.parse_issue71_phase_and_user_review_authorization(verified)

    def test_windows_profile_current_marker_rejects_wrong_pointer_identity(self):
        verified, digest, byte_length = self._windows_profile_verified()
        verified.pointer.sha256 = "0" * 64
        with patch.object(module, "ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256", digest), \
                patch.object(module, "ISSUE71_WINDOWS_PROFILE_READER_ADC_BYTES", byte_length):
            with self.assertRaisesRegex(module.PhaseReworkError, "pointer and exact bytes"):
                module.parse_issue71_phase_and_user_review_authorization(verified)

    def test_comprehensive_reader_accepts_exact_fourteen_generation_history(self):
        history = [
            {"comment_id": comment_id, "sha256": digest, "byte_length": size, "state": "approved"}
            for comment_id, digest, size in module.ISSUE71_COMPREHENSIVE_READER_HISTORY
        ]
        authorization = {"approved_history": history}

        def generation(comment_id, digest, size, predecessor):
            body = (
                f"Predecessor ADC: Issue #71 comment #{predecessor[0]}, "
                f"SHA-256 {predecessor[1]}\n"
            ).encode()
            body += b" " * (size - len(body))
            return SimpleNamespace(
                pointer=SimpleNamespace(comment_id=comment_id, sha256=digest, state="approved"),
                contract=SimpleNamespace(sha256=digest, byte_length=size,
                                         repository=module.REPOSITORY, content=body),
            )

        boundary = module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY
        rows = [generation(*boundary, 512, (1, "0" * 64))]
        previous = boundary
        for comment_id, digest, size in module.ISSUE71_COMPREHENSIVE_READER_HISTORY:
            rows.append(generation(comment_id, digest, size, previous))
            previous = (comment_id, digest)
        current_body = (
            f"Predecessor ADC: Issue #71 comment #{previous[0]}, SHA-256 {previous[1]}\n"
        ).encode()
        current_body += b" " * (module.ISSUE71_COMPREHENSIVE_READER_ADC_BYTES - len(current_body))
        current = verified_contract(
            module.ISSUE71_COMPREHENSIVE_READER_ADC_COMMENT_ID,
            module.ISSUE71_COMPREHENSIVE_READER_ADC_SHA256,
            module.ISSUE71_COMPREHENSIVE_READER_ADC_BYTES,
            module.REPOSITORY,
            current_body,
        )
        rows.append(current)
        with patch.object(module, "parse_issue71_phase_and_user_review_authorization",
                          return_value=authorization), \
                patch.object(module, "verify_adc_forward_generations", return_value=tuple(rows)) as verify:
            parsed, chain = module.verify_issue71_phase_and_user_review_adc_chain(SimpleNamespace(), current)
        self.assertEqual(parsed, authorization)
        self.assertEqual(len(chain) - 2, 14)
        verify.assert_called_once_with(
            SimpleNamespace(), module.ISSUE_NUMBER,
            prior_comment_id=module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[0],
            prior_sha256=module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[1],
            current_comment_id=module.ISSUE71_COMPREHENSIVE_READER_ADC_COMMENT_ID,
            current_sha256=module.ISSUE71_COMPREHENSIVE_READER_ADC_SHA256,
        )

        altered = dict(authorization)
        altered["approved_history"] = history[:-1]
        with patch.object(module, "parse_issue71_phase_and_user_review_authorization",
                          return_value=altered), \
                patch.object(module, "verify_adc_forward_generations", return_value=tuple(rows)):
            with self.assertRaisesRegex(module.PhaseReworkError, "incomplete, reordered, edited, or unapproved"):
                module.verify_issue71_phase_and_user_review_adc_chain(SimpleNamespace(), current)

    def test_windows_profile_reader_accepts_exact_fifteen_generation_history(self):
        history = [
            {"comment_id": comment_id, "sha256": digest, "byte_length": size, "state": "approved"}
            for comment_id, digest, size in module.ISSUE71_WINDOWS_PROFILE_READER_HISTORY
        ]
        authorization = {"approved_history": history}

        def generation(comment_id, digest, size, predecessor):
            body = (
                f"Predecessor ADC: Issue #71 comment #{predecessor[0]}, "
                f"SHA-256 {predecessor[1]}\n"
            ).encode()
            body += b" " * (size - len(body))
            return SimpleNamespace(
                pointer=SimpleNamespace(comment_id=comment_id, sha256=digest, state="approved"),
                contract=SimpleNamespace(sha256=digest, byte_length=size,
                                         repository=module.REPOSITORY, content=body),
            )

        boundary = module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY
        rows = [generation(*boundary, 512, (1, "0" * 64))]
        previous = boundary
        for comment_id, digest, size in module.ISSUE71_WINDOWS_PROFILE_READER_HISTORY:
            rows.append(generation(comment_id, digest, size, previous))
            previous = (comment_id, digest)
        current_body = (
            f"Predecessor ADC: Issue #71 comment #{previous[0]}, SHA-256 {previous[1]}\n"
        ).encode()
        current_body += b" " * (module.ISSUE71_WINDOWS_PROFILE_READER_ADC_BYTES - len(current_body))
        current = verified_contract(
            module.ISSUE71_WINDOWS_PROFILE_READER_ADC_COMMENT_ID,
            module.ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256,
            module.ISSUE71_WINDOWS_PROFILE_READER_ADC_BYTES,
            module.REPOSITORY,
            current_body,
        )
        rows.append(current)
        with patch.object(module, "parse_issue71_phase_and_user_review_authorization",
                          return_value=authorization), \
                patch.object(module, "verify_adc_forward_generations", return_value=tuple(rows)) as verify:
            parsed, chain = module.verify_issue71_phase_and_user_review_adc_chain(SimpleNamespace(), current)
        self.assertEqual(parsed, authorization)
        self.assertEqual(len(chain) - 2, 15)
        verify.assert_called_once_with(
            SimpleNamespace(), module.ISSUE_NUMBER,
            prior_comment_id=module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[0],
            prior_sha256=module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[1],
            current_comment_id=module.ISSUE71_WINDOWS_PROFILE_READER_ADC_COMMENT_ID,
            current_sha256=module.ISSUE71_WINDOWS_PROFILE_READER_ADC_SHA256,
        )

    def test_current_document_reissue_reader_accepts_exact_thirteen_generation_history(self):
        history = [
            {"comment_id": comment_id, "sha256": digest, "byte_length": size, "state": "approved"}
            for comment_id, digest, size in module.ISSUE71_CURRENT_DOCUMENT_REISSUE_HISTORY
        ]
        authorization = {"approved_history": history}

        def generation(comment_id, digest, size, predecessor, *, content=None):
            body = content or (
                f"Predecessor ADC: Issue #71 comment #{predecessor[0]}, "
                f"SHA-256 {predecessor[1]}\n"
            ).encode()
            body = body + b" " * (size - len(body))
            return SimpleNamespace(
                pointer=SimpleNamespace(comment_id=comment_id, sha256=digest, state="approved"),
                contract=SimpleNamespace(sha256=digest, byte_length=size,
                                         repository=module.REPOSITORY, content=body),
            )

        boundary = module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY
        rows = [generation(*boundary, 512, (1, "0" * 64))]
        previous = boundary
        for comment_id, digest, size in module.ISSUE71_CURRENT_DOCUMENT_REISSUE_HISTORY:
            rows.append(generation(comment_id, digest, size, previous))
            previous = (comment_id, digest)
        current_content = (
            f"Predecessor ADC: Issue #71 comment #{previous[0]}, "
            f"SHA-256 {previous[1]}\n"
        ).encode()
        current_content += b" " * (module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_BYTES
                                    - len(current_content))
        current = verified_contract(
            module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_COMMENT_ID,
            module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_SHA256,
            module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_BYTES,
            module.REPOSITORY,
            current_content,
        )
        rows.append(current)
        with patch.object(module, "parse_issue71_phase_and_user_review_authorization",
                          return_value=authorization), \
                patch.object(module, "verify_adc_forward_generations", return_value=tuple(rows)) as verify:
            parsed, chain = module.verify_issue71_phase_and_user_review_adc_chain(SimpleNamespace(), current)
        self.assertEqual(parsed, authorization)
        self.assertEqual(len(chain) - 2, 13)
        verify.assert_called_once_with(
            SimpleNamespace(), module.ISSUE_NUMBER,
            prior_comment_id=module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[0],
            prior_sha256=module.ISSUE71_COMBINED_ADC_HISTORY_BOUNDARY[1],
            current_comment_id=module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_COMMENT_ID,
            current_sha256=module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_SHA256,
        )

    def test_current_document_reissue_reader_dispatches_through_combined_authorization(self):
        current = verified_contract(
            module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_COMMENT_ID,
            module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_SHA256,
            module.ISSUE71_CURRENT_DOCUMENT_REISSUE_ADC_BYTES,
            module.REPOSITORY, b"approved ADC bytes",
        )
        with patch.object(module, "_has_issue71_current_combined_marker", return_value=True), \
                patch.object(module, "verify_issue71_phase_and_user_review_adc_chain",
                             return_value=({}, ())) as verify:
            result = module._authorization_context(SimpleNamespace(), current)
        verify.assert_called_once_with(SimpleNamespace(), current)
        self.assertEqual(result[0], module.AUTHORIZATION)
        self.assertEqual(result[2], module.RECOVERY_AUTHORIZATION)
        self.assertEqual(result[4], module.TIMESTAMP_RECOVERY_AUTHORIZATION)
        self.assertEqual(result[8], module.READER_CONTINUATION_AUTHORIZATION)
        self.assertEqual(result[10], module.EXECUTION_RECEIPT_READER_CONTINUATION_AUTHORIZATION)

    def test_combined_marker_rejects_duplicate_current_marker_before_payload_parsing(self):
        marker = f"<!-- {module.ISSUE71_PHASE_AND_USER_REVIEW_SCHEMA}\n{{}}\n-->"
        content = (marker + "\n" + marker).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        verified = verified_contract(
            module.ISSUE71_PHASE_AND_USER_REVIEW_ADC_COMMENT_ID,
            digest, len(content), module.REPOSITORY, content,
        )
        with patch.object(module, "ISSUE71_PHASE_AND_USER_REVIEW_ADC_SHA256", digest), \
                patch.object(module, "ISSUE71_PHASE_AND_USER_REVIEW_ADC_BYTES", len(content)), \
                self.assertRaisesRegex(module.PhaseReworkError, "exactly one combined authorization marker"):
            module.parse_issue71_phase_and_user_review_authorization(verified)

    def test_windows_profile_followup_requires_one_allowlisted_direct_child(self):
        start = "3524f9790813fe14351abd0bb2f4db48e8a28296"
        head = "f" * 40
        authorization = {
            "starting_head_sha40": start,
            "max_followup_commits": 1,
            "followup_path_allowlist": list(module.ISSUE71_WINDOWS_PROFILE_READER_PATH_ALLOWLIST),
        }
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=head), \
                patch.object(module, "commit_parents_sha40", return_value=(start,)), \
                patch.object(module, "changed_paths_between", return_value=(
                    "runtime/p_ases/profile.py", "docs/specs/workflow-spec.md")):
            module._verify_combined_followup_commit_set(Path(temporary), head, authorization)

    def test_windows_profile_followup_rejects_paths_outside_exact_allowlist(self):
        head = "f" * 40
        start = "3524f9790813fe14351abd0bb2f4db48e8a28296"
        authorization = {
            "starting_head_sha40": start,
            "max_followup_commits": 1,
            "followup_path_allowlist": list(module.ISSUE71_WINDOWS_PROFILE_READER_PATH_ALLOWLIST),
        }
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=head), \
                patch.object(module, "commit_parents_sha40",
                             return_value=(authorization["starting_head_sha40"],)), \
                patch.object(module, "changed_paths_between", return_value=("runtime/p_ases/adc.py",)):
            with self.assertRaisesRegex(module.PhaseReworkError, "exceeds its exact path allowlist"):
                module._verify_combined_followup_commit_set(Path(temporary), head, authorization)
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=head), \
                patch.object(module, "commit_parents_sha40", return_value=(start,)), \
                patch.object(module, "changed_paths_between", return_value=("runtime/p_ases/github.py",)):
            with self.assertRaisesRegex(module.PhaseReworkError, "exact path allowlist"):
                module._verify_combined_followup_commit_set(Path(temporary), head, authorization)

    def test_current_document_reissue_commit_uses_its_exact_direct_child_allowlist(self):
        start = "c464ae659efaae856aad669d69c3bfe2389efd18"
        head = "f" * 40
        authorization = {
            "starting_head_sha40": start,
            "max_followup_commits": 1,
            "followup_path_allowlist": list(module.ISSUE71_CURRENT_DOCUMENT_REISSUE_PATH_ALLOWLIST),
        }
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(module, "is_ancestor", return_value=True), \
                patch.object(module, "run_git", return_value=head), \
                patch.object(module, "commit_parents_sha40", return_value=(start,)), \
                patch.object(module, "changed_paths_between", return_value=(
                    "runtime/p_ases/phase_evidence.py", "tests/test_phase_evidence.py")):
            module._verify_combined_followup_commit_set(Path(temporary), head, authorization)


if __name__ == "__main__":
    unittest.main()
