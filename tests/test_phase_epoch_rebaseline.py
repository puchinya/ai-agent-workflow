from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import cli, phase_epoch_rebaseline as module  # noqa: E402
from p_ases import phase_evidence, phase_restart  # noqa: E402


def marker_bytes(payload: dict) -> bytes:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return f"\n<!-- {module.AUTH_SCHEMA}\n{raw}\n-->\n".encode("utf-8")


def verified_adc(content: bytes):
    return SimpleNamespace(contract=SimpleNamespace(content=content))


def sample_epoch() -> module.Issue71ExecutionEpoch:
    return module.Issue71ExecutionEpoch(
        repository=module.REPOSITORY,
        issue_number=module.ISSUE_NUMBER,
        issue_id=module.ISSUE_ID,
        adc_comment_id=6881591677,
        adc_sha256=module.CURRENT_ADC_SHA256,
        base_ref=module.BASE_REF,
        base_sha40=module.BASE_SHA40,
        branch_ref=module.BRANCH_REF,
        epoch_id="a" * 64,
        intent_comment_id=6881828764,
        intent_body_sha256="b" * 64,
        applied_comment_id=6881839877,
        applied_body_sha256="c" * 64,
        predecessor_epoch_id=module.OLD_EPOCH_ID,
        predecessor_epoch_sha256=module.OLD_EPOCH_SHA256,
        historical_binding_provenance="UNVERIFIED",
        historical_binding_sha256="b828daa98c9cab2c5243019e71158231e43f8c06826c7c31e6ca48ea3f5ac868",
        sha256="d" * 64,
    )


class EpochAuthorizationTests(unittest.TestCase):
    def test_exact_compact_authorization_marker_is_accepted(self):
        content = marker_bytes(module.AUTHORIZATION)
        payload, digest = module._parse_marker(verified_adc(content))
        self.assertEqual(payload, module.AUTHORIZATION)
        self.assertEqual(len(digest), 64)

    def test_duplicate_marker_key_is_rejected(self):
        raw = json.dumps(module.AUTHORIZATION, separators=(",", ":"), ensure_ascii=True)
        raw = raw.replace('"base_ref":"main"', '"base_ref":"main","base_ref":"main"', 1)
        content = f"<!-- {module.AUTH_SCHEMA}\n{raw}\n-->".encode()
        with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "duplicate"):
            module._parse_marker(verified_adc(content))

    def test_noncanonical_or_wrong_tuple_is_rejected(self):
        raw = json.dumps(module.AUTHORIZATION, separators=(",", ":"), ensure_ascii=True)
        with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "canonical"):
            module._parse_marker(verified_adc(
                f"<!-- {module.AUTH_SCHEMA}\n{raw} \n-->".encode()
            ))
        changed = dict(module.AUTHORIZATION)
        changed["branch_ref"] = "pases/wrong-branch"
        with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "exact tuple"):
            module._parse_marker(verified_adc(marker_bytes(changed)))

    def test_duplicate_authorization_marker_is_rejected(self):
        content = marker_bytes(module.AUTHORIZATION) + marker_bytes(module.AUTHORIZATION)
        with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "exactly one"):
            module._parse_marker(verified_adc(content))


    def test_malformed_reserved_journal_header_is_not_ignored(self):
        fake_github = SimpleNamespace(issue_comments=lambda _issue: [{
            "id": 99, "body": "<!--PASES_ISSUE_PHASE_EPOCH_REBASE_INTENT_V1\n{}\n-->",
        }])
        with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "malformed reserved"):
            module._read_rebaseline_history(fake_github)


class EpochIdentityTests(unittest.TestCase):
    def test_identity_rejects_changed_historical_binding_provenance(self):
        identity = sample_epoch()
        with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "frozen tuple"):
            module.Issue71ExecutionEpoch(
                **{**identity.__dict__, "historical_binding_provenance": "VERIFIED"}
            ).validate()

    def test_canonical_local_identity_and_attachment_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = {
                "adc_comment_id": 6881591677,
                "adc_sha256": module.CURRENT_ADC_SHA256,
                "epoch_id": "e" * 64,
            }
            intent = module.RebaselineRecord(
                comment_id=6881828764, schema=module.INTENT_SCHEMA,
                payload=source, body="intent body", actor_id=module.OWNER_ID,
                created_at="2026-11-14T17:59:00Z",
            )
            applied = module.RebaselineRecord(
                comment_id=6881839877, schema=module.APPLIED_SCHEMA,
                payload=source, body="applied body", actor_id=module.OWNER_ID,
                created_at="2026-11-14T18:00:00Z",
            )
            epoch, attachment = module._epoch_payload(intent, applied, root)
            epoch_path, attachment_path = module.epoch_paths(root)
            module._write_exact_private_json(epoch_path, epoch, root)
            module._write_exact_private_json(attachment_path, attachment, root)
            loaded = module._load_local_epoch(
                root, expected_adc_comment_id=6881591677,
                expected_adc_sha256=module.CURRENT_ADC_SHA256,
            )
            self.assertEqual(loaded.epoch_id, "e" * 64)
            self.assertEqual(loaded.sha256, epoch["sha256"])

    def test_tampered_workspace_attachment_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = {
                "adc_comment_id": 6881591677,
                "adc_sha256": module.CURRENT_ADC_SHA256,
                "epoch_id": "f" * 64,
            }
            intent = module.RebaselineRecord(
                comment_id=6881828764, schema=module.INTENT_SCHEMA,
                payload=source, body="intent body", actor_id=module.OWNER_ID,
                created_at="2026-11-14T17:59:00Z",
            )
            applied = module.RebaselineRecord(
                comment_id=6881839877, schema=module.APPLIED_SCHEMA,
                payload=source, body="applied body", actor_id=module.OWNER_ID,
                created_at="2026-11-14T18:00:00Z",
            )
            epoch, attachment = module._epoch_payload(intent, applied, root)
            epoch_path, attachment_path = module.epoch_paths(root)
            module._write_exact_private_json(epoch_path, epoch, root)
            attachment["work_directory"] = "/wrong/worktree"
            attachment_path.parent.mkdir(parents=True, exist_ok=True)
            attachment_path.write_text(module._canonical(attachment) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "attachment"):
                module._load_local_epoch(
                    root, expected_adc_comment_id=6881591677,
                    expected_adc_sha256=module.CURRENT_ADC_SHA256,
                )

    def test_phase_evidence_selects_epoch3_without_a_binding_file(self):
        epoch = sample_epoch()
        fake_github = SimpleNamespace(repo=module.REPOSITORY)
        verified = SimpleNamespace(pointer=SimpleNamespace(comment_id=6881591677),
                                   contract=SimpleNamespace(sha256=module.CURRENT_ADC_SHA256))
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(module, "read_active_epoch", return_value=epoch), \
             patch.object(phase_evidence, "is_ancestor", return_value=True):
            root = Path(temporary)
            self.assertFalse((root / ".p_ases" / "state" / "71" / "execution-binding.json").exists())
            phase_evidence._verify_frozen_binding(
                fake_github, root, 71, verified, module.BRANCH_REF, module.BASE_SHA40,
            )

    def test_phase_generation_reader_uses_epoch3_applied_record(self):
        epoch = sample_epoch()
        fake_github = SimpleNamespace(repo=module.REPOSITORY)
        verified = SimpleNamespace(pointer=SimpleNamespace(comment_id=6881591677),
                                   contract=SimpleNamespace(sha256=module.CURRENT_ADC_SHA256))
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(module, "read_active_epoch", return_value=epoch):
            generation = phase_restart.current_phase_generation(
                fake_github, Path(temporary), 71, verified,
            )
        self.assertEqual(generation.comment_id, epoch.applied_comment_id)
        self.assertEqual(generation.sha256, epoch.applied_body_sha256)
        self.assertEqual(generation.epoch_sha256, epoch.sha256)

    def test_epoch_rebaseline_cli_route_is_issue71_scoped(self):
        args = cli._parser().parse_args([
            "issue", "phase-epoch-rebaseline", "71", "--repo",
            module.REPOSITORY, "--root", "/tmp/issue71-epoch3",
        ])
        self.assertEqual(args.verb, "phase-epoch-rebaseline")
        self.assertEqual(args.issue, 71)
        self.assertEqual(args.root, Path("/tmp/issue71-epoch3"))

    def test_active_reader_requires_pinned_repository_and_single_issue_kind(self):
        fake_github = SimpleNamespace(
            repo=module.REPOSITORY,
            repository_metadata=lambda: {
                "id": module.REPOSITORY_ID, "full_name": module.REPOSITORY,
            },
            issue=lambda _number: {"labels": [
                {"name": "kind:child"}, {"name": "phase:requirements"},
            ]},
        )
        current = SimpleNamespace(
            pointer=SimpleNamespace(state="approved", comment_id=6881591677),
            contract=SimpleNamespace(sha256=module.CURRENT_ADC_SHA256, repository=module.REPOSITORY),
        )
        with patch.object(module, "verify_adc", return_value=current), \
             patch.object(module, "_parse_marker", return_value=(module.AUTHORIZATION, "a" * 64)), \
             patch.object(module, "_check_issue", side_effect=lambda issue: issue):
            with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
                module.PhaseEpochRebaselineError, "kind:single"
            ):
                module.read_active_epoch(fake_github, Path(temporary), current)


class FakeJournalGitHub:
    repo = module.REPOSITORY

    def __init__(self, failure: str):
        self.failure = failure
        self.comments: list[dict] = []
        self.post_calls = 0
        self.next_id = 101

    def issue_comments(self, _issue_number: int):
        return list(self.comments)

    def issue_comment(self, _issue_number: int, comment_id: int):
        return next(row for row in self.comments if row["id"] == comment_id)

    def create_issue_comment(self, issue_number: int, body: str):
        self.post_calls += 1
        if self.failure == "before":
            raise module.GitHubError("lost response before server apply")
        comment_id = self.next_id
        self.next_id += 1
        now = "2026-11-14T18:01:00Z"
        row = {
            "id": comment_id,
            "body": body,
            "created_at": now,
            "updated_at": now,
            "user": {"id": module.OWNER_ID, "login": "puchinya", "type": "User"},
            "issue_url": f"https://api.github.com/repos/{module.REPOSITORY}/issues/{issue_number}",
            "html_url": f"https://github.com/{module.REPOSITORY}/issues/{issue_number}#issuecomment-{comment_id}",
            "url": f"https://api.github.com/repos/{module.REPOSITORY}/issues/comments/{comment_id}",
        }
        self.comments.append(row)
        if self.failure == "after":
            raise module.GitHubError("lost response after server apply")
        return {"id": comment_id}


def empty_intent_payload() -> dict:
    payload = {field: None for field in module.INTENT_FIELDS}
    payload.update({
        "schema": module.INTENT_SCHEMA,
        "created_at": "2026-11-14T18:00:00Z",
    })
    return payload


class OneShotJournalTests(unittest.TestCase):
    def test_ambiguous_intent_post_is_never_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeJournalGitHub("before")
            with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "will not be retried"):
                module._post_record_once(github, root, module.INTENT_SCHEMA, empty_intent_payload())
            with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "read-only recovery"):
                module._post_record_once(github, root, module.INTENT_SCHEMA, empty_intent_payload())
            self.assertEqual(github.post_calls, 1)

    def test_post_response_loss_after_apply_recovers_by_exact_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            github = FakeJournalGitHub("after")
            first = module._post_record_once(
                github, root, module.INTENT_SCHEMA, empty_intent_payload(),
            )
            second = module._post_record_once(
                github, root, module.INTENT_SCHEMA, empty_intent_payload(),
            )
            self.assertEqual(first.comment_id, second.comment_id)
            self.assertEqual(github.post_calls, 1)


class OneShotLabelTests(unittest.TestCase):
    def test_completed_label_write_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent = module.RebaselineRecord(
                comment_id=6881828764, schema=module.INTENT_SCHEMA,
                payload={}, body="exact intent body", actor_id=module.OWNER_ID,
                created_at="2026-11-14T17:59:00Z",
            )
            calls: list[str] = []
            remote = SimpleNamespace(
                replace_issue_labels=lambda *_args: calls.append("PUT")
            )
            reads = [{"state": "open"}, {"state": "open"}]
            with patch.object(module, "_read_issue_labels", side_effect=lambda *_a: reads.pop(0)):
                module._replace_labels_once(remote, root, intent)
            self.assertEqual(calls, ["PUT"])
            with patch.object(module, "_read_issue_labels", return_value={"state": "open"}):
                with self.assertRaisesRegex(module.PhaseEpochRebaselineError, "no retry"):
                    module._replace_labels_once(remote, root, intent)
            self.assertEqual(calls, ["PUT"])


if __name__ == "__main__":
    unittest.main()
