"""Exact-subject human User Review: GitHub evidence and a fail-closed chat boundary.

Only the host can authenticate a direct chat event. Never deserialize a claimed
chat identity from a file or external text as a trusted approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .delivery import ReadinessResult
from .evidence_store import VerificationSubject
from .path_safety import path_has_symlink

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CHANNELS = {"issue-comment", "pr-comment", "pr-review", "diff-comment", "chat"}
KINDS = {"pending", "questions", "changes_requested", "blocked", "approved"}
STATES = {"PENDING", "QUESTIONS", "CHANGES_REQUESTED", "BLOCKED", "APPROVED"}


class UserReviewError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _time(value: str) -> datetime:
    if not isinstance(value, str) or not value or not value.endswith("Z"):
        raise UserReviewError("feedback timestamp must be UTC ISO-8601")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise UserReviewError("feedback timestamp is invalid") from exc
    if result.utcoffset() != timezone.utc.utcoffset(result):
        raise UserReviewError("feedback timestamp is not UTC")
    return result


@dataclass(frozen=True)
class UserReviewSubject:
    verification_subject: VerificationSubject
    readiness_sha256: str

    def validate(self) -> "UserReviewSubject":
        if not isinstance(self.verification_subject, VerificationSubject):
            raise UserReviewError("User Review must bind to the exact Verification subject")
        self.verification_subject.validate()
        if not isinstance(self.readiness_sha256, str) or not SHA256.fullmatch(self.readiness_sha256):
            raise UserReviewError("User Review needs a full Readiness SHA-256")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"verification_subject": self.verification_subject.as_dict(),
                "readiness_sha256": self.readiness_sha256}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()


@dataclass(frozen=True)
class UserReviewSession:
    """Immutable start point; only feedback created or updated after it can decide."""

    subject: UserReviewSubject
    started_at: str

    def validate(self) -> "UserReviewSession":
        self.subject.validate()
        _time(self.started_at)
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"schema": "PASES_USER_REVIEW_SESSION_V1", "started_at": self.started_at,
                "subject": self.subject.as_dict()}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()

    def to_bytes(self) -> bytes:
        value = {**self.as_dict(), "session_sha256": self.sha256}
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "UserReviewSession":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UserReviewError("User Review session is not valid UTF-8 JSON") from exc
        expected = {"schema", "started_at", "subject", "session_sha256"}
        if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_USER_REVIEW_SESSION_V1":
            raise UserReviewError("User Review session has unknown or missing fields")
        raw_subject = value["subject"]
        if not isinstance(raw_subject, dict) or set(raw_subject) != {"verification_subject", "readiness_sha256"}:
            raise UserReviewError("User Review session subject is invalid")
        subject = UserReviewSubject(
            VerificationSubject.from_dict(raw_subject["verification_subject"]), raw_subject["readiness_sha256"]
        ).validate()
        session = cls(subject, value["started_at"]).validate()
        if value["session_sha256"] != session.sha256 or session.to_bytes() != raw:
            raise UserReviewError("User Review session digest or canonical bytes do not match")
        return session


@dataclass(frozen=True)
class FeedbackEvent:
    channel: str
    event_id: str
    actor_id: int | None
    actor_login: str | None
    actor_type: str
    created_at: str
    updated_at: str
    kind: str
    head_sha40: str | None
    body_sha256: str
    source_url: str
    deleted: bool = False
    resolved: bool | None = None
    host_attestation_sha256: str | None = None
    deleted_at: str | None = None
    edited: bool = False
    subject_sha256: str | None = None

    def validate(self) -> "FeedbackEvent":
        if self.channel not in CHANNELS or self.kind not in KINDS:
            raise UserReviewError("unknown feedback channel or decision")
        if not isinstance(self.event_id, str) or not self.event_id or len(self.event_id) > 256:
            raise UserReviewError("feedback event ID is invalid")
        if self.actor_id is not None and (type(self.actor_id) is not int or self.actor_id < 1):
            raise UserReviewError("feedback actor ID is invalid")
        if self.actor_login is not None and (not isinstance(self.actor_login, str) or not self.actor_login):
            raise UserReviewError("feedback actor login is invalid")
        if not isinstance(self.actor_type, str) or not self.actor_type:
            raise UserReviewError("feedback actor type is missing")
        if _time(self.updated_at) < _time(self.created_at):
            raise UserReviewError("feedback edit timestamp predates creation")
        if self.head_sha40 is not None and (not isinstance(self.head_sha40, str) or not SHA40.fullmatch(self.head_sha40)):
            raise UserReviewError("feedback HEAD must be a full SHA-40")
        if not isinstance(self.body_sha256, str) or not SHA256.fullmatch(self.body_sha256):
            raise UserReviewError("feedback body digest must be SHA-256")
        if not isinstance(self.source_url, str) or not self.source_url.strip():
            raise UserReviewError("feedback permalink is missing")
        if type(self.deleted) is not bool:
            raise UserReviewError("feedback deletion flag is not boolean")
        if self.deleted:
            _time(self.deleted_at)
        elif self.deleted_at is not None:
            raise UserReviewError("live feedback cannot carry a deletion timestamp")
        if type(self.edited) is not bool:
            raise UserReviewError("feedback edit state is invalid")
        if self.resolved is not None and type(self.resolved) is not bool:
            raise UserReviewError("feedback resolution flag is invalid")
        if self.channel == "chat":
            if not isinstance(self.host_attestation_sha256, str) or not SHA256.fullmatch(self.host_attestation_sha256):
                raise UserReviewError("chat feedback requires host identity attestation")
            if not isinstance(self.subject_sha256, str) or not SHA256.fullmatch(self.subject_sha256):
                raise UserReviewError("chat feedback requires an exact review-subject digest")
        elif self.host_attestation_sha256 is not None:
            raise UserReviewError("GitHub feedback cannot carry a chat host attestation")
        elif self.subject_sha256 is not None:
            raise UserReviewError("GitHub feedback cannot carry a host chat subject digest")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {key: getattr(self, key) for key in (
            "channel", "event_id", "actor_id", "actor_login", "actor_type",
            "created_at", "updated_at", "kind", "head_sha40", "body_sha256",
            "source_url", "deleted", "resolved", "host_attestation_sha256", "deleted_at", "edited",
            "subject_sha256",
        )}


def _feedback_row(row: dict[str, Any], channel: str) -> FeedbackEvent:
    if not isinstance(row, dict) or channel not in CHANNELS - {"chat"}:
        raise UserReviewError("GitHub feedback row is malformed")
    identifier, user = row.get("id"), row.get("user")
    if type(identifier) is not int or identifier < 1 or not isinstance(user, dict):
        raise UserReviewError("GitHub feedback is missing numeric ID or user")
    actor_id, login, actor_type = user.get("id"), user.get("login"), user.get("type")
    if type(actor_id) is not int or actor_id < 1:
        raise UserReviewError("GitHub feedback actor has no verified numeric user ID")
    if not isinstance(login, str) or not login or not isinstance(actor_type, str):
        raise UserReviewError("GitHub feedback actor login/type is missing")
    created = row.get("submitted_at") if channel == "pr-review" else row.get("created_at")
    # PENDING PR reviews are unpublished and may not have submitted_at.
    if created is None and channel == "pr-review":
        created = row.get("created_at")
    updated = row.get("updated_at") or created
    body = row.get("body")
    if body is not None and not isinstance(body, str):
        raise UserReviewError("GitHub feedback body is not text")
    if channel == "pr-review":
        state = row.get("state")
        if state == "APPROVED":
            kind = "approved"
        elif state == "CHANGES_REQUESTED":
            kind = "changes_requested"
        elif state == "DISMISSED":
            kind = "blocked"
        elif state in {"PENDING", "COMMENTED"}:
            kind = "pending" if state == "PENDING" else "questions"
        else:
            raise UserReviewError("GitHub review has unsupported state")
        head = row.get("commit_id")
    else:
        # Ordinary comments can request clarification, not grant approval.
        kind = "questions"
        head = row.get("commit_id") if channel == "diff-comment" else None
    link = row.get("html_url")
    if not isinstance(link, str) or not link.startswith("https://github.com/"):
        raise UserReviewError("GitHub feedback has no canonical permalink")
    return FeedbackEvent(channel, str(identifier), actor_id, login, actor_type, created,
                         updated, kind, head, hashlib.sha256((body or "").encode("utf-8")).hexdigest(),
                         link, bool(row.get("deleted", False)), row.get("is_resolved"),
                         edited=_time(updated) > _time(created)).validate()


def normalize_github_feedback(
    *,
    issue_comments: Iterable[dict[str, Any]],
    pr_comments: Iterable[dict[str, Any]],
    pr_reviews: Iterable[dict[str, Any]],
    diff_comments: Iterable[dict[str, Any]],
) -> tuple[FeedbackEvent, ...]:
    """Time-order all GitHub surfaces; conflicting duplicates reject the snapshot."""
    found: dict[tuple[str, str], FeedbackEvent] = {}
    for channel, rows in (
        ("issue-comment", issue_comments), ("pr-comment", pr_comments),
        ("pr-review", pr_reviews), ("diff-comment", diff_comments),
    ):
        for row in rows:
            event = _feedback_row(row, channel)
            key = (event.channel, event.event_id)
            if key in found and found[key] != event:
                raise UserReviewError("GitHub feedback contains conflicting duplicate IDs")
            found[key] = event
    return tuple(sorted(found.values(), key=lambda e: (_time(e.updated_at), _time(e.created_at), e.channel, e.event_id)))


def feedback_digest(events: Iterable[FeedbackEvent]) -> str:
    ordered = tuple(events)
    if len({(e.channel, e.event_id) for e in ordered}) != len(ordered):
        raise UserReviewError("feedback snapshot has duplicate IDs")
    return hashlib.sha256(_canonical([event.as_dict() for event in ordered])).hexdigest()


@dataclass(frozen=True)
class UserReviewResult:
    status: str
    subject: UserReviewSubject
    feedback_sha256: str
    reasons: tuple[str, ...]
    next_phase: str
    selected_approval_event: str | None = None
    unresolved_thread_ids: tuple[str, ...] = ()

    def validate(self) -> "UserReviewResult":
        self.subject.validate()
        if self.status not in STATES:
            raise UserReviewError("User Review status is invalid")
        if not SHA256.fullmatch(self.feedback_sha256):
            raise UserReviewError("User Review feedback SHA-256 is invalid")
        if not isinstance(self.reasons, tuple) or any(not isinstance(x, str) or not x for x in self.reasons):
            raise UserReviewError("User Review reasons are invalid")
        if self.status == "APPROVED" and (self.reasons or not self.selected_approval_event):
            raise UserReviewError("User Review approval needs a proven event and no reasons")
        if self.status != "APPROVED" and not self.reasons:
            raise UserReviewError("non-approved User Review needs reasons")
        if self.next_phase not in {"user-review", "execution", "requirements"}:
            raise UserReviewError("User Review next phase is invalid")
        if (type(self.unresolved_thread_ids) is not tuple
                or any(not isinstance(x, str) or not x for x in self.unresolved_thread_ids)
                or self.unresolved_thread_ids != tuple(sorted(set(self.unresolved_thread_ids)))):
            raise UserReviewError("unresolved review thread IDs are invalid")
        if self.status == "APPROVED" and self.unresolved_thread_ids:
            raise UserReviewError("User Review cannot approve with unresolved discussion threads")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"status": self.status, "subject": self.subject.as_dict(),
                "feedback_sha256": self.feedback_sha256, "reasons": list(self.reasons),
                "next_phase": self.next_phase, "selected_approval_event": self.selected_approval_event,
                "unresolved_thread_ids": list(self.unresolved_thread_ids)}

    @classmethod
    def from_dict(cls, value: Any) -> "UserReviewResult":
        expected = {"feedback_sha256", "next_phase", "reasons", "selected_approval_event",
                    "status", "subject", "unresolved_thread_ids"}
        if not isinstance(value, dict) or set(value) != expected:
            raise UserReviewError("User Review result has unknown or missing fields")
        raw_subject = value["subject"]
        if not isinstance(raw_subject, dict) or set(raw_subject) != {"verification_subject", "readiness_sha256"}:
            raise UserReviewError("User Review subject is invalid")
        subject = UserReviewSubject(
            VerificationSubject.from_dict(raw_subject["verification_subject"]), raw_subject["readiness_sha256"]
        ).validate()
        if (not isinstance(value["reasons"], list)
                or not isinstance(value["unresolved_thread_ids"], list)):
            raise UserReviewError("User Review reasons or thread IDs are invalid")
        return cls(value["status"], subject, value["feedback_sha256"], tuple(value["reasons"]),
                   value["next_phase"], value["selected_approval_event"],
                   tuple(value["unresolved_thread_ids"])).validate()


def evaluate_user_review(
    subject: UserReviewSubject,
    readiness: ReadinessResult,
    current_pr_head_sha40: str,
    events: Iterable[FeedbackEvent],
    *,
    allowed_human_user_ids: Iterable[int],
    previous_feedback_sha256: str | None = None,
    required_after: str | None = None,
    all_feedback_surfaces_read: bool = True,
    new_scope_requested: bool = False,
    unresolved_thread_ids: Iterable[str] = (),
) -> UserReviewResult:
    """Read-only gate. This function never calls GitHub or changes an Issue."""
    subject.validate()
    rows = tuple(events)
    digest = feedback_digest(rows)
    ids = tuple(allowed_human_user_ids)
    if not ids or any(type(x) is not int or x < 1 for x in ids) or len(set(ids)) != len(ids):
        raise UserReviewError("trusted human user ID allowlist must be nonempty and unique")
    reasons: list[str] = []
    unresolved = tuple(sorted(set(unresolved_thread_ids)))
    if any(not isinstance(value, str) or not value for value in unresolved):
        raise UserReviewError("unresolved review thread IDs must be non-empty strings")
    if not isinstance(readiness, ReadinessResult):
        reasons.append("Review Readiness is missing")
    else:
        readiness.validate()
        if (readiness.status != "PASS" or readiness.subject != subject.verification_subject
                or readiness.sha256 != subject.readiness_sha256):
            reasons.append("current exact-subject Review Readiness PASS is missing or stale")
    if not isinstance(current_pr_head_sha40, str) or not SHA40.fullmatch(current_pr_head_sha40):
        reasons.append("current PR HEAD is invalid")
    elif current_pr_head_sha40 != subject.verification_subject.pr_head_sha40:
        reasons.append("PR HEAD changed; approval is stale")
    if not all_feedback_surfaces_read:
        reasons.append("GitHub feedback enumeration is incomplete")
    if required_after is not None:
        _time(required_after)
    if previous_feedback_sha256 is not None and previous_feedback_sha256 != digest:
        reasons.append("feedback snapshot changed since the previous decision")
    deletion_times = [event.deleted_at for event in rows if event.deleted and event.deleted_at is not None]
    if unresolved:
        reasons.append("unresolved GitHub review threads remain")
    eligible = [event for event in rows if event.actor_id in ids and event.actor_type == "User"
                and not event.deleted and (event.channel != "chat" or
                    (event.host_attestation_sha256 is not None and event.subject_sha256 == subject.sha256))]
    eligible.sort(key=lambda x: (_time(x.updated_at), _time(x.created_at), x.channel, x.event_id))
    latest = eligible[-1] if eligible else None
    if deletion_times and (latest is None or _time(latest.updated_at) <= max(_time(value) for value in deletion_times)):
        reasons.append("GitHub feedback was deleted; prior approval is invalid")
    if latest and latest.kind == "approved":
        if required_after is not None and _time(latest.updated_at) < _time(required_after):
            reasons.append("latest approval predates this exact User Review session")
        if latest.edited:
            reasons.append("latest formal approval was edited; a fresh approval is required")
        if any(event.kind == "questions" and _time(event.updated_at) >= _time(latest.updated_at)
               for event in eligible):
            reasons.append("authorized human questions are not resolved by a later formal approval")
    if new_scope_requested:
        return UserReviewResult("CHANGES_REQUESTED", subject, digest,
                                tuple(reasons + ["change requires new requirements decision"]),
                                "requirements", None, unresolved).validate()
    if latest and latest.kind == "changes_requested":
        if latest.head_sha40 != current_pr_head_sha40:
            reasons.append("latest change request targets a stale PR HEAD")
        elif required_after is not None and _time(latest.updated_at) < _time(required_after):
            reasons.append("latest change request predates this exact User Review session")
        else:
            return UserReviewResult("CHANGES_REQUESTED", subject, digest,
                                    tuple(reasons + ["authorized user requested changes; reuse same PR"]),
                                    "execution", None, unresolved).validate()
    if (latest and latest.channel in {"pr-review", "chat"} and latest.kind == "approved"
            and latest.head_sha40 == current_pr_head_sha40 and not reasons):
        return UserReviewResult("APPROVED", subject, digest, (), "user-review",
                                f"{latest.channel}:{latest.event_id}", unresolved).validate()
    if latest and latest.kind == "approved" and latest.head_sha40 != current_pr_head_sha40:
        reasons.append("latest human approval targets a stale or missing commit")
    if not latest:
        reasons.append("no eligible authenticated human GitHub PR review")
    if latest and latest.kind in {"blocked", "pending"}:
        reasons.append("latest human review is blocked or pending")
    if latest and latest.kind == "questions":
        reasons.append("latest authorized human feedback contains questions; approval is still required")
    status = "BLOCKED" if reasons and any(
        token in reason for reason in reasons
        for token in ("stale", "missing", "changed", "incomplete", "deleted", "edited", "unresolved", "predates")
    ) else "PENDING"
    return UserReviewResult(status, subject, digest, tuple(reasons or ["no explicit current user approval"]),
                            "user-review", None, unresolved).validate()


def reject_unattested_chat_event(_: Any) -> None:
    """The CLI/filesystem has no authenticated host identity capability."""
    raise UserReviewError("UNVERIFIABLE_CHAT_IDENTITY: only a trusted direct host event can assert chat provenance")


def capture_authenticated_chat_event(payload: Any, host_verifier: Any) -> FeedbackEvent:
    """Convert a direct host event only after an installed host adapter verifies its provenance.

    The verifier is a capability supplied by the active chat host, not data from
    the event itself or a CLI file. It returns a structured assertion after
    checking the author, direct conversation, quote/attachment state, and the
    explicit decision produced by the host UI.
    """
    if not callable(host_verifier):
        return reject_unattested_chat_event(payload)
    try:
        assertion = host_verifier(payload)
    except Exception as exc:
        raise UserReviewError("UNVERIFIABLE_CHAT_IDENTITY: host provenance check failed") from exc
    required = {"event_id", "actor_id", "actor_login", "actor_type", "created_at", "updated_at",
                "decision", "conversation_ref", "body_sha256", "attestation_sha256",
                "is_direct", "is_quoted", "has_attachments", "author_is_current_user", "head_sha40",
                "subject_sha256"}
    if not isinstance(assertion, dict) or set(assertion) != required:
        raise UserReviewError("UNVERIFIABLE_CHAT_IDENTITY: host assertion is incomplete")
    if (assertion["is_direct"] is not True or assertion["is_quoted"] is not False
            or assertion["has_attachments"] is not False or assertion["author_is_current_user"] is not True):
        raise UserReviewError("UNVERIFIABLE_CHAT_IDENTITY: chat event is not a direct unquoted user decision")
    event = FeedbackEvent(
        "chat", assertion["event_id"], assertion["actor_id"], assertion["actor_login"],
        assertion["actor_type"], assertion["created_at"], assertion["updated_at"],
        assertion["decision"], assertion["head_sha40"], assertion["body_sha256"],
        assertion["conversation_ref"], False, None, assertion["attestation_sha256"],
        subject_sha256=assertion["subject_sha256"],
    )
    return event.validate()


def add_authenticated_chat_event(
    snapshot: "FeedbackSnapshot", session: UserReviewSession, payload: Any,
    host_verifier: Any,
) -> "FeedbackSnapshot":
    """Attach a verified direct chat decision to the current GitHub feedback snapshot."""
    snapshot.validate()
    session.validate()
    if snapshot.subject != session.subject:
        raise UserReviewError("chat decision and feedback snapshot belong to different review sessions")
    event = capture_authenticated_chat_event(payload, host_verifier)
    if event.subject_sha256 != session.subject.sha256:
        raise UserReviewError("chat decision belongs to a stale or different User Review subject")
    if _time(event.updated_at) < _time(session.started_at):
        raise UserReviewError("chat decision predates this exact User Review session")
    events = {(item.channel, item.event_id): item for item in snapshot.events}
    key = (event.channel, event.event_id)
    if key in events and events[key] != event:
        raise UserReviewError("host chat event ID conflicts with existing feedback bytes")
    events[key] = event
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return FeedbackSnapshot(session.subject, tuple(sorted(events.values(), key=lambda item: (item.channel, item.event_id))),
                            snapshot.unresolved_thread_ids, observed_at).validate()


@dataclass(frozen=True)
class FeedbackSnapshot:
    """Immutable readback of all GitHub feedback surfaces for one User Review subject."""

    subject: UserReviewSubject
    events: tuple[FeedbackEvent, ...]
    unresolved_thread_ids: tuple[str, ...]
    observed_at: str

    def validate(self) -> "FeedbackSnapshot":
        self.subject.validate()
        if type(self.events) is not tuple or any(not isinstance(row, FeedbackEvent) for row in self.events):
            raise UserReviewError("feedback snapshot events are invalid")
        for row in self.events:
            row.validate()
        keys = [(row.channel, row.event_id) for row in self.events]
        if keys != sorted(set(keys)):
            raise UserReviewError("feedback snapshot rows must be sorted and unique")
        if (type(self.unresolved_thread_ids) is not tuple
                or self.unresolved_thread_ids != tuple(sorted(set(self.unresolved_thread_ids)))
                or any(not isinstance(x, str) or not x for x in self.unresolved_thread_ids)):
            raise UserReviewError("feedback snapshot unresolved thread IDs are invalid")
        _time(self.observed_at)
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"events": [row.as_dict() for row in self.events],
                "observed_at": self.observed_at,
                "schema": "PASES_USER_REVIEW_FEEDBACK_V1",
                "subject": self.subject.as_dict(),
                "unresolved_thread_ids": list(self.unresolved_thread_ids)}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["snapshot_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "FeedbackSnapshot":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UserReviewError("feedback snapshot is not valid UTF-8 JSON") from exc
        expected = {"events", "observed_at", "schema", "snapshot_sha256", "subject", "unresolved_thread_ids"}
        if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_USER_REVIEW_FEEDBACK_V1":
            raise UserReviewError("feedback snapshot has unknown or missing fields")
        subject_raw = value["subject"]
        if not isinstance(subject_raw, dict) or set(subject_raw) != {"verification_subject", "readiness_sha256"}:
            raise UserReviewError("feedback snapshot subject is invalid")
        subject = UserReviewSubject(VerificationSubject.from_dict(subject_raw["verification_subject"]),
                                    subject_raw["readiness_sha256"]).validate()
        events = tuple(FeedbackEvent(**row) for row in value["events"] if isinstance(row, dict))
        if len(events) != len(value["events"]):
            raise UserReviewError("feedback snapshot contains a malformed event")
        snapshot = cls(subject, events, tuple(value["unresolved_thread_ids"]), value["observed_at"]).validate()
        if value["snapshot_sha256"] != snapshot.sha256 or snapshot.to_bytes() != raw:
            raise UserReviewError("feedback snapshot digest or canonical bytes do not match")
        return snapshot


def merge_feedback_history(previous: FeedbackSnapshot | None, current: FeedbackSnapshot) -> FeedbackSnapshot:
    """Preserve deletions and edits from API snapshots as immutable tombstones."""
    current.validate()
    if previous is None:
        return current
    previous.validate()
    if previous.subject != current.subject:
        raise UserReviewError("feedback history belongs to another exact User Review subject")
    live = {(event.channel, event.event_id): event for event in current.events}
    for old in previous.events:
        key = (old.channel, old.event_id)
        if key not in live:
            if old.channel == "chat":
                # Chat events are supplied by the host adapter, not a GitHub collection.
                live[key] = old
            else:
                live[key] = FeedbackEvent(**{**old.as_dict(), "deleted": True,
                                             "deleted_at": current.observed_at})
    return FeedbackSnapshot(current.subject, tuple(sorted(live.values(), key=lambda x: (x.channel, x.event_id))),
                            current.unresolved_thread_ids, current.observed_at).validate()


def feedback_snapshot_path(root: Path, snapshot: FeedbackSnapshot) -> Path:
    snapshot.validate()
    return Path(root).absolute() / ".p_ases" / "user-review" / str(snapshot.subject.verification_subject.issue_number) / snapshot.subject.sha256 / f"{snapshot.sha256}.json"


def review_session_path(root: Path, session: UserReviewSession | UserReviewSubject) -> Path:
    subject = session.subject if isinstance(session, UserReviewSession) else session
    subject.validate()
    return (Path(root).absolute() / ".p_ases" / "user-review"
            / str(subject.verification_subject.issue_number) / subject.sha256 / "session.json")


def read_review_session(path: Path) -> UserReviewSession:
    location = Path(path)
    if path_has_symlink(location):
        raise UserReviewError("User Review session path must not traverse a symbolic link")
    try:
        return UserReviewSession.from_bytes(location.read_bytes())
    except OSError as exc:
        raise UserReviewError("User Review session is missing or unreadable") from exc


def write_review_session(path: Path, session: UserReviewSession) -> UserReviewSession:
    session.validate()
    destination = Path(path)
    if path_has_symlink(destination):
        raise UserReviewError("User Review session path must not traverse a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(destination):
        raise UserReviewError("User Review session path must not traverse a symbolic link")
    raw = session.to_bytes()
    if destination.exists():
        prior = read_review_session(destination)
        if prior.subject != session.subject:
            raise UserReviewError("User Review session path belongs to another exact subject")
        return prior
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            prior = read_review_session(destination)
            if prior.subject != session.subject:
                raise UserReviewError("User Review session path belongs to another exact subject")
            return prior
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise UserReviewError("could not atomically store User Review session") from exc
    if read_review_session(destination) != session:
        raise UserReviewError("User Review session readback changed")
    return session


def read_feedback_snapshot(path: Path) -> FeedbackSnapshot:
    location = Path(path)
    if path_has_symlink(location):
        raise UserReviewError("feedback snapshot path must not traverse a symbolic link")
    try:
        return FeedbackSnapshot.from_bytes(location.read_bytes())
    except OSError as exc:
        raise UserReviewError("feedback snapshot is missing or unreadable") from exc


def write_feedback_snapshot(path: Path, snapshot: FeedbackSnapshot) -> str:
    snapshot.validate()
    destination = Path(path)
    if path_has_symlink(destination):
        raise UserReviewError("feedback snapshot path must not traverse a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(destination):
        raise UserReviewError("feedback snapshot path must not traverse a symbolic link")
    raw = snapshot.to_bytes()
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != raw:
                raise UserReviewError("feedback snapshot identity exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise UserReviewError("could not atomically store feedback snapshot") from exc
    if read_feedback_snapshot(destination) != snapshot:
        raise UserReviewError("feedback snapshot readback changed")
    return snapshot.sha256
