"""Generic current-ADC-authorized verification-to-requirements phase rework.

No repository or Issue-number exceptions. A completed immutable V3 Applied/Intent
pair is read directly; new operations require a typed authorization in the
current ADC, exact fresh Readiness, and one-shot comment/label attempt markers.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .adc import ADCError, verify_adc
from .current_epoch import CurrentEpochError, read_current_epoch
from .epoch_lifecycle import (
    EpochLifecycleError, _attempt, _json, _live, _post, _sha,
)
from .git import GitError
from .github import GitHub, GitHubError
from .issue_association import IssueAssociationError, parse_issue_association
from .path_safety import path_has_symlink

AUTH_SCHEMA = "PASES_PHASE_REWORK_AUTH_V1"
INTENT_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_INTENT_V3"
APPLIED_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V3"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
AUTH_FIELDS = {
    "schema", "repository", "issue_number", "issue_id", "owner_id",
    "base_ref", "base_sha40", "branch_ref", "pr_number", "pr_head_sha40",
    "active_epoch_id", "active_epoch_sha256", "from_phase", "to_phase",
    "labels_before", "labels_after", "max_applications",
}


class PhaseReworkLifecycleError(ValueError):
    """Unapproved, stale, duplicate or ambiguous Phase rework operation."""


def _authorization(content: bytes, repository: str, issue_number: int) -> tuple[dict[str, Any], str]:
    if not isinstance(content, bytes):
        raise PhaseReworkLifecycleError("current ADC has no exact source bytes")
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise PhaseReworkLifecycleError("current ADC is not UTF-8") from exc
    prefix = f"<!-- {AUTH_SCHEMA}\n"
    pieces = text.split(prefix)
    if len(pieces) != 2 or "\n-->" not in pieces[1]:
        raise PhaseReworkLifecycleError("one typed Phase rework authorization is required")
    raw, _rest = pieces[1].split("\n-->", 1)
    try:
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise PhaseReworkLifecycleError("Phase rework authorization has duplicate keys")
                result[key] = value
            return result
        auth = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise PhaseReworkLifecycleError("Phase rework authorization is malformed") from exc
    if (not isinstance(auth, dict) or set(auth) != AUTH_FIELDS
            or _json(auth).decode("utf-8") != raw
            or auth.get("schema") != AUTH_SCHEMA
            or auth.get("repository", "").casefold() != repository.casefold()
            or auth.get("issue_number") != issue_number
            or type(auth.get("issue_id")) is not int or auth["issue_id"] < 1
            or type(auth.get("owner_id")) is not int or auth["owner_id"] < 1
            or type(auth.get("pr_number")) is not int or auth["pr_number"] < 1
            or any(not isinstance(auth.get(x), str) or SHA40.fullmatch(auth[x]) is None
                   for x in ("base_sha40", "pr_head_sha40"))
            or any(not isinstance(auth.get(x), str) or SHA256.fullmatch(auth[x]) is None
                   for x in ("active_epoch_id", "active_epoch_sha256"))
            or not isinstance(auth.get("base_ref"), str) or not auth["base_ref"]
            or not isinstance(auth.get("branch_ref"), str) or not auth["branch_ref"]
            or auth.get("from_phase") != "verification"
            or auth.get("to_phase") != "requirements"
            or auth.get("max_applications") != 1):
        raise PhaseReworkLifecycleError("Phase rework authorization does not bind the current subject")
    before, after = auth["labels_before"], auth["labels_after"]
    if (not isinstance(before, list) or not isinstance(after, list)
            or any(not isinstance(x, str) for x in before + after)
            or before != sorted(set(before)) or after != sorted(set(after))
            or [x for x in before if x.startswith("phase:")] != ["phase:verification"]
            or [x for x in after if x.startswith("phase:")] != ["phase:requirements"]
            or [x for x in before if not x.startswith("phase:")]
               != [x for x in after if not x.startswith("phase:")]
            or sum(x.startswith("kind:") for x in before) != 1):
        raise PhaseReworkLifecycleError("Phase rework authorization has invalid exact labels")
    return auth, _sha(_json(auth))


def _completed(github: GitHub, issue_number: int, epoch: Any) -> int | None:
    """Verify the latest applied V3 and its referenced Intent without older ADCs."""
    origin = epoch.origin
    if epoch.applied_comment_id == origin["applied_comment_id"]:
        return None
    try:
        row = github.issue_comment(issue_number, epoch.applied_comment_id)
        text = row.get("body") if isinstance(row, dict) else None
        prefix = f"<!-- {APPLIED_SCHEMA}\n"
        if (not isinstance(text, str) or not text.startswith(prefix) or not text.endswith("\n-->")
                or _sha(text.encode("utf-8")) != epoch.applied_body_sha256):
            raise PhaseReworkLifecycleError("active Phase Applied digest or schema differs")
        raw = text[len(prefix):-len("\n-->")]
        payload = json.loads(raw)
        if (not isinstance(payload, dict)
                or _json(payload).decode("utf-8") != raw
                or payload.get("active_epoch_id") != epoch.epoch_id
                or payload.get("active_epoch_sha256") != epoch.sha256
                or payload.get("repository", "").casefold() != github.repo.casefold()
                or payload.get("issue_number") != issue_number
                or payload.get("schema") != APPLIED_SCHEMA):
            raise PhaseReworkLifecycleError("active Phase Applied does not bind the immutable epoch")
        intent_id = payload.get("intent_comment_id")
        digest = payload.get("intent_body_sha256")
        if (type(intent_id) is not int or intent_id < 1
                or not isinstance(digest, str) or SHA256.fullmatch(digest) is None):
            raise PhaseReworkLifecycleError("active Phase Applied lacks an exact Intent proof")
        intent = github.issue_comment(issue_number, intent_id)
        body = intent.get("body") if isinstance(intent, dict) else None
        if (not isinstance(body, str) or _sha(body.encode("utf-8")) != digest
                or not body.startswith(f"<!-- {INTENT_SCHEMA}\n")
                or not body.endswith("\n-->")
                or intent.get("issue_url") != row.get("issue_url")
                or intent.get("created_at") != intent.get("updated_at")):
            raise PhaseReworkLifecycleError("active Phase Intent is missing or changed")
        return epoch.applied_comment_id
    except (GitHubError, ValueError, TypeError) as exc:
        if isinstance(exc, PhaseReworkLifecycleError):
            raise
        raise PhaseReworkLifecycleError(f"active Phase rework readback failed: {exc}") from exc


def _readiness(readiness: Any, *, repository: str, issue_number: int,
               adc: Any, auth: Mapping[str, Any]) -> tuple[str, str]:
    subject = getattr(readiness, "subject", None)
    if (getattr(readiness, "status", None) != "PASS"
            or not isinstance(getattr(readiness, "sha256", None), str)
            or SHA256.fullmatch(readiness.sha256) is None
            or subject is None
            or getattr(subject, "repository", "").casefold() != repository.casefold()
            or getattr(subject, "issue_number", None) != issue_number
            or getattr(subject, "pr_number", None) != auth["pr_number"]
            or getattr(subject, "pr_head_sha40", None) != auth["pr_head_sha40"]
            or getattr(subject, "adc_comment_id", None) != adc.pointer.comment_id
            or getattr(subject, "adc_sha256", None) != adc.pointer.sha256
            or not isinstance(getattr(subject, "sha256", None), str)
            or SHA256.fullmatch(subject.sha256) is None):
        raise PhaseReworkLifecycleError("fresh exact-subject PASS Readiness is required")
    return readiness.sha256, subject.sha256


def _verify_pr(github: GitHub, issue_number: int, auth: Mapping[str, Any]) -> None:
    pr = github.pull_request(auth["pr_number"])
    head, base = pr.get("head"), pr.get("base")
    owner = pr.get("user")
    if (pr.get("number") != auth["pr_number"] or pr.get("state") != "open"
            or pr.get("draft") is not False or pr.get("merged") is True
            or pr.get("merged_at") is not None
            or not isinstance(head, dict) or not isinstance(base, dict)
            or head.get("sha") != auth["pr_head_sha40"]
            or head.get("ref") != auth["branch_ref"]
            or base.get("ref") != auth["base_ref"]
            or not isinstance(head.get("repo"), dict)
            or head["repo"].get("full_name", "").casefold() != github.repo.casefold()
            or not isinstance(base.get("repo"), dict)
            or base["repo"].get("full_name", "").casefold() != github.repo.casefold()
            or not isinstance(owner, dict) or owner.get("id") != auth["owner_id"]
            or owner.get("type") != "User"):
        raise PhaseReworkLifecycleError("Phase rework PR exact owner/ref/HEAD changed")
    try:
        association = parse_issue_association(pr.get("body"), issue_number)
    except IssueAssociationError as exc:
        raise PhaseReworkLifecycleError(f"Phase rework PR Issue association is invalid: {exc}") from exc
    if association not in {"auto_close", "deferred_close"}:
        raise PhaseReworkLifecycleError("Phase rework PR Issue association is unsupported")


def _no_review_session(root: Path, issue_number: int) -> None:
    folder = root / ".p_ases" / "user-review" / str(issue_number)
    if path_has_symlink(folder, root=root):
        raise PhaseReworkLifecycleError("User Review state path traverses a symlink")
    if folder.exists() and (not folder.is_dir()
            or any(True for path in folder.rglob("session.json"))):
        raise PhaseReworkLifecycleError("User Review session already exists")


def apply_phase_rework(github: GitHub, root: Path, issue_number: int, *,
                       readiness_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    if type(issue_number) is not int or issue_number < 1:
        raise PhaseReworkLifecycleError("Phase rework Issue number must be positive")
    try:
        adc = verify_adc(github, issue_number)
        if adc.pointer.state != "approved":
            raise PhaseReworkLifecycleError("Phase rework requires current approved ADC")
        epoch = read_current_epoch(github, root, issue_number, adc)
        completed = _completed(github, issue_number, epoch)
        if completed is not None:
            return {"status": "NOOP", "issue": issue_number,
                    "applied_comment_id": completed, "writes_performed": 0}
        auth, auth_sha = _authorization(adc.contract.content, github.repo, issue_number)
        if (auth["active_epoch_id"] != epoch.epoch_id
                or auth["active_epoch_sha256"] != epoch.sha256
                or auth["branch_ref"] != epoch.branch_ref
                or auth["base_sha40"] != epoch.base_sha40):
            raise PhaseReworkLifecycleError("Phase rework authorization differs from the active epoch")
        _live(github, root, issue_number, adc, auth, auth["labels_before"])
        _verify_pr(github, issue_number, auth)
        _no_review_session(root, issue_number)
        if readiness_factory is None:
            raise PhaseReworkLifecycleError("fresh exact-subject PASS Readiness is required")
        ready = readiness_factory()
        ready_sha, subject_sha = _readiness(ready, repository=github.repo, issue_number=issue_number,
                                          adc=adc, auth=auth)
        # A different session cannot silently alter the subject after the first
        # evidence calculation, especially before the one-shot Intent POST.
        _live(github, root, issue_number, adc, auth, auth["labels_before"])
        _verify_pr(github, issue_number, auth)
        if _readiness(readiness_factory(), repository=github.repo,
                      issue_number=issue_number, adc=adc, auth=auth) != (ready_sha, subject_sha):
            raise PhaseReworkLifecycleError("fresh Readiness changed before Phase rework Intent")
        intent = {
            **auth, "schema": INTENT_SCHEMA,
            "adc_comment_id": adc.pointer.comment_id,
            "adc_sha256": adc.pointer.sha256,
            "authorization_sha256": auth_sha,
            "readiness_sha256": ready_sha, "readiness_subject_sha256": subject_sha,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        intent_id, intent_sha = _post(
            github, root, issue_number, "intent", INTENT_SCHEMA, intent,
            auth["owner_id"], namespace="phase-rework",
        )
        _live(github, root, issue_number, adc, auth, auth["labels_before"])
        _verify_pr(github, issue_number, auth)
        _attempt(root, issue_number, "labels", _sha(_json({
            "intent_id": intent_id, "intent_sha256": intent_sha,
            "labels_after": auth["labels_after"],
        })), namespace="phase-rework")
        try:
            github.replace_issue_labels(issue_number, auth["labels_after"])
        except GitHubError as exc:
            raise PhaseReworkLifecycleError("Phase rework label PUT is ambiguous; never retry") from exc
        _live(github, root, issue_number, adc, auth, auth["labels_after"])
        _verify_pr(github, issue_number, auth)
        applied = {
            **{k: v for k, v in intent.items() if k != "created_at"},
            "schema": APPLIED_SCHEMA,
            "repository": github.repo, "issue_number": issue_number,
            "active_epoch_id": epoch.epoch_id, "active_epoch_sha256": epoch.sha256,
            "intent_comment_id": intent_id, "intent_body_sha256": intent_sha,
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        applied_id, _digest = _post(
            github, root, issue_number, "applied", APPLIED_SCHEMA, applied,
            auth["owner_id"], namespace="phase-rework",
        )
        newest = read_current_epoch(github, root, issue_number, adc)
        if newest.applied_comment_id != applied_id or _completed(github, issue_number, newest) != applied_id:
            raise PhaseReworkLifecycleError("new Phase rework generation failed exact readback")
        return {"status": "APPLIED", "issue": issue_number,
                "intent_comment_id": intent_id, "applied_comment_id": applied_id,
                "readiness_sha256": ready_sha, "writes_performed": 3}
    except (ADCError, CurrentEpochError, EpochLifecycleError, GitHubError, GitError, OSError) as exc:
        raise PhaseReworkLifecycleError(str(exc)) from exc
