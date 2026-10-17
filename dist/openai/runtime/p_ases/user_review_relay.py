"""Verify User Review decision carriers from the delegated and owner-local paths.

V1 remains delegated relay evidence. V2 is owner-local TTY evidence and does
not claim a ChatGPT signature. The evaluator still checks the complete current
feedback snapshot and exact review subject.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

USER_REVIEW_DECISION_SCHEMA = "PASES_USER_REVIEW_DECISION_V1"
USER_REVIEW_DECISION_SCHEMA_V2 = "PASES_USER_REVIEW_DECISION_V2"
FIELDS_V1 = frozenset({
    "schema", "repository", "issue_number", "pr_number", "decision",
    "owner_id", "review_session_id", "readiness_sha256", "adc_sha256",
    "pr_head_sha40", "evidence_channel", "predecessor_comment_id",
})
FIELDS_V2 = FIELDS_V1 | {"feedback_sha256", "plan_sha256"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
DECISION_MARKERS = re.compile(r"PASES_USER_REVIEW_DECISION_[A-Z0-9_]+")


class UserReviewRelayError(ValueError):
    """Incomplete or contradictory dedicated User Review evidence."""


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _field(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in items:
        if k in out:
            raise UserReviewRelayError("duplicate dedicated approval field")
        out[k] = v
    return out


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise UserReviewRelayError("approval timestamp is absent or not UTC")
    try:
        t = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise UserReviewRelayError("approval timestamp is malformed") from exc
    if t.utcoffset() != timezone.utc.utcoffset(t):
        raise UserReviewRelayError("approval timestamp is not UTC")
    return t


def parse_user_review_decision(body: Any) -> dict[str, Any]:
    if not isinstance(body, str):
        raise UserReviewRelayError("dedicated review record must be text")
    try:
        payload = json.loads(body, object_pairs_hook=_unique)
    except (ValueError, TypeError) as exc:
        raise UserReviewRelayError("invalid dedicated review JSON") from exc
    schema = payload.get("schema") if isinstance(payload, dict) else None
    fields = FIELDS_V1 if schema == USER_REVIEW_DECISION_SCHEMA else FIELDS_V2
    channel = "delegated_github_relay" if schema == USER_REVIEW_DECISION_SCHEMA else "owner_local_tty_v1"
    if not isinstance(payload, dict) or set(payload) != fields or _canonical(payload) != body:
        raise UserReviewRelayError("dedicated review fields or canonical bytes differ")
    if (payload["schema"] not in {USER_REVIEW_DECISION_SCHEMA, USER_REVIEW_DECISION_SCHEMA_V2}
            or payload["decision"] != "APPROVED"
            or payload["evidence_channel"] != channel
            or not isinstance(payload["repository"], str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", payload["repository"])
            or not all(_positive(payload[x]) for x in ("issue_number", "pr_number", "owner_id"))
            or not all(isinstance(payload[x], str) and SHA256.fullmatch(payload[x])
                       for x in ("review_session_id", "readiness_sha256", "adc_sha256"))
            or not isinstance(payload["pr_head_sha40"], str)
            or not SHA40.fullmatch(payload["pr_head_sha40"])
            or (payload["predecessor_comment_id"] is not None
                and not _positive(payload["predecessor_comment_id"]))):
        raise UserReviewRelayError("invalid review-decision subject, owner, or schema")
    if schema == USER_REVIEW_DECISION_SCHEMA_V2 and not all(
            isinstance(payload[key], str) and SHA256.fullmatch(payload[key])
            for key in ("feedback_sha256", "plan_sha256")):
        raise UserReviewRelayError("owner-local User Review plan/feedback digest is invalid")
    return payload


def has_user_review_decision_marker(body: Any) -> bool:
    """Return true for the known carrier or any malformed/unknown version marker."""
    return isinstance(body, str) and DECISION_MARKERS.search(body) is not None


@dataclass(frozen=True)
class UserReviewDecisionHistory:
    listed_comments: tuple[Any, ...]
    direct_before: Mapping[int, Any]
    direct_after: Mapping[int, Any]
    pagination_complete: bool


@dataclass(frozen=True)
class UserReviewRelayApproval:
    comment_id: int
    body_sha256: str
    owner_id: int
    created_at: str
    review_session_sha256: str
    predecessor_comment_id: int | None
    evidence_channel: str = "delegated_github_relay"
    evidence_type: str = USER_REVIEW_DECISION_SCHEMA
    feedback_sha256: str | None = None
    plan_sha256: str | None = None

    def as_selected_evidence(self) -> dict[str, Any]:
        evidence = {
            "evidence_type": self.evidence_type,
            "evidence_channel": self.evidence_channel,
            "comment_id": self.comment_id, "body_sha256": self.body_sha256,
            "owner_id": self.owner_id, "created_at": self.created_at,
            "review_session_sha256": self.review_session_sha256,
            "predecessor_comment_id": self.predecessor_comment_id,
        }
        if self.evidence_type == USER_REVIEW_DECISION_SCHEMA_V2:
            evidence["feedback_sha256"] = self.feedback_sha256
            evidence["plan_sha256"] = self.plan_sha256
        return evidence


def _identity(comment: Any, repo: str, issue: int, expected_owner_id: int) -> tuple[Any, ...]:
    comment_id = _field(comment, "id")
    user = _field(comment, "user")
    if not _positive(comment_id) or not isinstance(user, dict):
        raise UserReviewRelayError("comment ID or authenticated actor is missing")
    if user.get("id") != expected_owner_id or user.get("type") != "User":
        raise UserReviewRelayError("comment is not authored by the configured GitHub owner")
    urls = {
        "url": f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}",
        "issue_url": f"https://api.github.com/repos/{repo}/issues/{issue}",
        "html_url": f"https://github.com/{repo}/issues/{issue}#issuecomment-{comment_id}",
    }
    if any(_field(comment, k) != value for k, value in urls.items()):
        raise UserReviewRelayError("dedicated review comment has incorrect GitHub origin")
    created, updated = _field(comment, "created_at"), _field(comment, "updated_at")
    _timestamp(created)
    if created != updated:
        raise UserReviewRelayError("dedicated review comment has been edited")
    body = _field(comment, "body")
    if not isinstance(body, str):
        raise UserReviewRelayError("comment has no body")
    return (comment_id, body, created, updated, user["id"], user["type"],
            urls["url"], urls["issue_url"], urls["html_url"])


def verify_user_review_decision_history(
    history: UserReviewDecisionHistory,
    *, repository: str, issue_number: int, pr_number: int,
    repository_owner_user_id: int, authenticated_verifier_user_id: int,
    session: Any, readiness_sha256: str, adc_sha256: str, pr_head_sha40: str,
    feedback_sha256: str | None = None, plan_sha256: str | None = None,
) -> UserReviewRelayApproval:
    if (not isinstance(history, UserReviewDecisionHistory)
            or history.pagination_complete is not True
            or not _positive(repository_owner_user_id)
            or not _positive(authenticated_verifier_user_id)
            or not _positive(issue_number) or not _positive(pr_number)
            or not isinstance(repository, str)):
        raise UserReviewRelayError("dedicated carrier collection is incomplete")
    try:
        session.validate()
    except (AttributeError, ValueError, TypeError) as exc:
        raise UserReviewRelayError("valid immutable UserReviewSession is required") from exc
    subj = session.subject.verification_subject
    if (subj.repository != repository or subj.issue_number != issue_number
            or subj.pr_number != pr_number or subj.adc_sha256 != adc_sha256
            or subj.pr_head_sha40 != pr_head_sha40
            or session.subject.readiness_sha256 != readiness_sha256):
        raise UserReviewRelayError("session and requested review subject mismatch")
    matching: list[tuple[int, dict[str, Any], tuple[Any, ...]]] = []
    for comment in history.listed_comments:
        body = _field(comment, "body")
        if not isinstance(body, str):
            raise UserReviewRelayError("missing GitHub Issue comment body")
        markers = DECISION_MARKERS.findall(body)
        if not markers:
            continue
        if len(markers) != 1 or markers[0] not in {
                USER_REVIEW_DECISION_SCHEMA, USER_REVIEW_DECISION_SCHEMA_V2}:
            raise UserReviewRelayError("unknown or malformed dedicated User Review marker")
        decision = parse_user_review_decision(body)
        if (decision["repository"] != repository or decision["issue_number"] != issue_number
                or decision["pr_number"] != pr_number
                or decision["owner_id"] != repository_owner_user_id):
            raise UserReviewRelayError("carrier in this Issue has a different review owner or scope")
        one = _identity(comment, repository, issue_number, repository_owner_user_id)
        direct_before = history.direct_before.get(one[0])
        direct_after = history.direct_after.get(one[0])
        if (direct_before is None or direct_after is None
                or _identity(direct_before, repository, issue_number, repository_owner_user_id) != one
                or _identity(direct_after, repository, issue_number, repository_owner_user_id) != one):
            raise UserReviewRelayError("dedicated carrier direct/list/direct readback disagrees")
        matching.append((one[0], decision, one))
    if not matching:
        raise UserReviewRelayError("no dedicated carrier in complete Issue history")
    matching.sort(key=lambda x: x[0])
    preceding: int | None = None
    sessions: set[str] = set()
    current: list[tuple[int, dict[str, Any], tuple[Any, ...]]] = []
    for comment_id, decision, identity in matching:
        if decision["predecessor_comment_id"] != preceding:
            raise UserReviewRelayError("carrier has a missing, skipped or nonmonotonic predecessor")
        preceding = comment_id
        if decision["review_session_id"] in sessions:
            raise UserReviewRelayError("dedicated User Review session has repeated approval")
        sessions.add(decision["review_session_id"])
        if decision["review_session_id"] == session.sha256:
            if (_timestamp(identity[2]) <= _timestamp(session.started_at)
                    or decision["readiness_sha256"] != readiness_sha256
                    or decision["adc_sha256"] != adc_sha256
                    or decision["pr_head_sha40"] != pr_head_sha40):
                raise UserReviewRelayError("carrier predates session or has stale approval subject")
            if decision["schema"] == USER_REVIEW_DECISION_SCHEMA_V2:
                if ((feedback_sha256 is not None and decision["feedback_sha256"] != feedback_sha256)
                        or (plan_sha256 is not None and decision["plan_sha256"] != plan_sha256)):
                    raise UserReviewRelayError("owner-local User Review feedback or plan digest is stale")
            current.append((comment_id, decision, identity))
    if len(current) != 1:
        raise UserReviewRelayError("expected exactly one current-session carrier")
    comment_id, decision, identity = current[0]
    return UserReviewRelayApproval(
        comment_id=comment_id, body_sha256=hashlib.sha256(identity[1].encode("utf-8")).hexdigest(),
        owner_id=repository_owner_user_id, created_at=identity[2],
        review_session_sha256=session.sha256, predecessor_comment_id=decision["predecessor_comment_id"],
        evidence_channel=decision["evidence_channel"], evidence_type=decision["schema"],
        feedback_sha256=decision.get("feedback_sha256"), plan_sha256=decision.get("plan_sha256"),
    )


def _history_rows(history: UserReviewDecisionHistory, repository: str, issue_number: int,
                  pr_number: int, owner_id: int) -> tuple[tuple[int, dict[str, Any], tuple[Any, ...]], ...]:
    if not isinstance(history, UserReviewDecisionHistory) or history.pagination_complete is not True:
        raise UserReviewRelayError("dedicated carrier collection is incomplete")
    collected: list[tuple[int, dict[str, Any], tuple[Any, ...]]] = []
    for row in history.listed_comments:
        body = _field(row, "body")
        markers = DECISION_MARKERS.findall(body) if isinstance(body, str) else []
        if not markers:
            continue
        if len(markers) != 1 or markers[0] not in {
                USER_REVIEW_DECISION_SCHEMA, USER_REVIEW_DECISION_SCHEMA_V2}:
            raise UserReviewRelayError("unknown or malformed dedicated User Review marker")
        decision = parse_user_review_decision(body)
        if (decision["repository"] != repository or decision["issue_number"] != issue_number
                or decision["pr_number"] != pr_number or decision["owner_id"] != owner_id):
            raise UserReviewRelayError("dedicated carrier history contains a different repository, Issue, PR, or owner")
        identity = _identity(row, repository, issue_number, owner_id)
        before, after = history.direct_before.get(identity[0]), history.direct_after.get(identity[0])
        if (before is None or after is None
                or _identity(before, repository, issue_number, owner_id) != identity
                or _identity(after, repository, issue_number, owner_id) != identity):
            raise UserReviewRelayError("dedicated carrier direct/list/direct readback disagrees")
        collected.append((identity[0], decision, identity))
    collected.sort(key=lambda item: item[0])
    if len({item[0] for item in collected}) != len(collected):
        raise UserReviewRelayError("dedicated carrier comment ID is duplicated")
    predecessor: int | None = None
    sessions: set[str] = set()
    for comment_id, decision, _identity_row in collected:
        if decision["predecessor_comment_id"] != predecessor:
            raise UserReviewRelayError("dedicated carrier history has a skipped or wrong predecessor")
        session_id = decision["review_session_id"]
        if session_id in sessions:
            raise UserReviewRelayError("dedicated User Review session is replayed across evidence versions")
        sessions.add(session_id)
        predecessor = comment_id
    return tuple(collected)


def user_review_decision_v2_body(
    *, repository: str, issue_number: int, pr_number: int, owner_id: int,
    review_session_id: str, readiness_sha256: str, adc_sha256: str,
    pr_head_sha40: str, feedback_sha256: str, plan_sha256: str,
    predecessor_comment_id: int | None,
) -> str:
    payload = {
        "schema": USER_REVIEW_DECISION_SCHEMA_V2, "repository": repository,
        "issue_number": issue_number, "pr_number": pr_number, "decision": "APPROVED",
        "owner_id": owner_id, "review_session_id": review_session_id,
        "readiness_sha256": readiness_sha256, "adc_sha256": adc_sha256,
        "pr_head_sha40": pr_head_sha40, "feedback_sha256": feedback_sha256,
        "plan_sha256": plan_sha256, "evidence_channel": "owner_local_tty_v1",
        "predecessor_comment_id": predecessor_comment_id,
    }
    body = _canonical(payload)
    parse_user_review_decision(body)
    return body


def publish_owner_local_user_review_decision(
    github: Any, *, repository: str, issue_number: int, pr_number: int,
    repository_owner_user_id: int, session: Any, readiness_sha256: str,
    adc_sha256: str, pr_head_sha40: str, feedback_sha256: str,
    plan_sha256: str,
) -> UserReviewRelayApproval:
    """Append one V2 carrier after the caller has performed exact local TTY confirmation."""
    session.validate()

    def read_history() -> UserReviewDecisionHistory:
        first = github.issue_comments(issue_number)
        ids = []
        for row in first:
            body = row.get("body") if isinstance(row, dict) else None
            if has_user_review_decision_marker(body):
                comment_id = row.get("id") if isinstance(row, dict) else None
                if not _positive(comment_id):
                    raise UserReviewRelayError("dedicated User Review carrier has no valid ID")
                ids.append(comment_id)
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise UserReviewRelayError("dedicated User Review history IDs are not append-only")
        before = {comment_id: github.issue_comment(issue_number, comment_id) for comment_id in ids}
        listed = github.issue_comments(issue_number)
        second_ids = [row.get("id") for row in listed
                      if isinstance(row, dict) and has_user_review_decision_marker(row.get("body"))]
        if second_ids != ids:
            raise UserReviewRelayError("dedicated User Review history changed during readback")
        after = {comment_id: github.issue_comment(issue_number, comment_id) for comment_id in ids}
        history = UserReviewDecisionHistory(tuple(listed), before, after, True)
        _history_rows(history, repository, issue_number, pr_number, repository_owner_user_id)
        return history

    subject = session.subject.verification_subject
    if (subject.repository != repository or subject.issue_number != issue_number
            or subject.pr_number != pr_number or subject.adc_sha256 != adc_sha256
            or subject.pr_head_sha40 != pr_head_sha40
            or session.subject.readiness_sha256 != readiness_sha256):
        raise UserReviewRelayError("owner-local User Review plan differs from its immutable session")
    history = read_history()
    rows = _history_rows(history, repository, issue_number, pr_number, repository_owner_user_id)
    if any(decision["review_session_id"] == session.sha256 for _id, decision, _row in rows):
        raise UserReviewRelayError("this immutable User Review session already has a decision")
    predecessor = rows[-1][0] if rows else None
    body = user_review_decision_v2_body(
        repository=repository, issue_number=issue_number, pr_number=pr_number,
        owner_id=repository_owner_user_id, review_session_id=session.sha256,
        readiness_sha256=readiness_sha256, adc_sha256=adc_sha256,
        pr_head_sha40=pr_head_sha40, feedback_sha256=feedback_sha256,
        plan_sha256=plan_sha256, predecessor_comment_id=predecessor,
    )
    write_error: Exception | None = None
    try:
        github.create_issue_comment(issue_number, body)
    except Exception as exc:  # the POST may have succeeded before transport loss
        write_error = exc
    try:
        new_history = read_history()
        approval = verify_user_review_decision_history(
            new_history, repository=repository, issue_number=issue_number, pr_number=pr_number,
            repository_owner_user_id=repository_owner_user_id,
            authenticated_verifier_user_id=repository_owner_user_id,
            session=session, readiness_sha256=readiness_sha256, adc_sha256=adc_sha256,
            pr_head_sha40=pr_head_sha40, feedback_sha256=feedback_sha256,
            plan_sha256=plan_sha256,
        )
        if approval.evidence_type != USER_REVIEW_DECISION_SCHEMA_V2:
            raise UserReviewRelayError("readback did not select the owner-local V2 carrier")
        return approval
    except Exception as read_error:
        if write_error is not None:
            raise UserReviewRelayError("owner-local User Review POST is ambiguous; no retry was attempted") from read_error
        raise
