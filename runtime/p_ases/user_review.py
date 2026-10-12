"""Exact-subject human User Review: GitHub evidence and a fail-closed chat boundary.

Only the host can authenticate a direct chat event. Never deserialize a claimed
chat identity from a file or external text as a trusted approval.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .delivery import ReadinessResult
from .evidence_store import VerificationSubject

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
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {key: getattr(self, key) for key in (
            "channel", "event_id", "actor_id", "actor_login", "actor_type",
            "created_at", "updated_at", "kind", "head_sha40", "body_sha256",
            "source_url", "deleted",
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
                         link).validate()


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
    return tuple(sorted(found.values(), key=lambda e: (_time(e.created_at), e.channel, e.event_id)))


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
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"status": self.status, "subject": self.subject.as_dict(),
                "feedback_sha256": self.feedback_sha256, "reasons": list(self.reasons),
                "next_phase": self.next_phase, "selected_approval_event": self.selected_approval_event}


def evaluate_user_review(
    subject: UserReviewSubject,
    readiness: ReadinessResult,
    current_pr_head_sha40: str,
    events: Iterable[FeedbackEvent],
    *,
    allowed_human_user_ids: Iterable[int],
    previous_feedback_sha256: str | None = None,
    all_feedback_surfaces_read: bool = True,
    new_scope_requested: bool = False,
) -> UserReviewResult:
    """Read-only gate. This function never calls GitHub or changes an Issue."""
    subject.validate()
    rows = tuple(events)
    digest = feedback_digest(rows)
    ids = tuple(allowed_human_user_ids)
    if not ids or any(type(x) is not int or x < 1 for x in ids) or len(set(ids)) != len(ids):
        raise UserReviewError("trusted human user ID allowlist must be nonempty and unique")
    reasons: list[str] = []
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
    if previous_feedback_sha256 is not None and previous_feedback_sha256 != digest:
        reasons.append("feedback snapshot changed since the previous decision")
    if any(event.deleted for event in rows):
        reasons.append("GitHub feedback was deleted; prior approval is invalid")
    eligible = [event for event in rows if event.actor_id in ids and event.actor_type == "User"
                and event.channel == "pr-review"]
    eligible.sort(key=lambda x: (_time(x.created_at), x.event_id))
    latest = eligible[-1] if eligible else None
    if new_scope_requested:
        return UserReviewResult("CHANGES_REQUESTED", subject, digest,
                                tuple(reasons + ["change requires new requirements decision"]),
                                "requirements").validate()
    if latest and latest.kind == "changes_requested":
        return UserReviewResult("CHANGES_REQUESTED", subject, digest,
                                tuple(reasons + ["authorized user requested changes; reuse same PR"]),
                                "execution").validate()
    if latest and latest.kind == "approved" and latest.head_sha40 == current_pr_head_sha40 and not reasons:
        return UserReviewResult("APPROVED", subject, digest, (), "user-review",
                                f"{latest.channel}:{latest.event_id}").validate()
    if latest and latest.kind == "approved" and latest.head_sha40 != current_pr_head_sha40:
        reasons.append("latest human approval targets a stale or missing commit")
    if not latest:
        reasons.append("no eligible authenticated human GitHub PR review")
    if latest and latest.kind in {"blocked", "pending"}:
        reasons.append("latest human review is blocked or pending")
    status = "BLOCKED" if reasons and any("stale" in x or "missing" in x or "changed" in x or "incomplete" in x or "deleted" in x for x in reasons) else "PENDING"
    return UserReviewResult(status, subject, digest, tuple(reasons or ["no explicit current user approval"]), "user-review").validate()


def reject_unattested_chat_event(_: Any) -> None:
    """The CLI/filesystem has no authenticated host identity capability."""
    raise UserReviewError("UNVERIFIABLE_CHAT_IDENTITY: only a trusted direct host event can assert chat provenance")
