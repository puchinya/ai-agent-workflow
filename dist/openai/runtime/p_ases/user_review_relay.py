"""Verify owner-relayed User Review comments without granting the runtime write access.

Only the isolated, permissioned relay may create PASES_USER_REVIEW_DECISION_V1.
This verifier proves exact GitHub source, stable actor, chain and session;
the caller separately verifies current Readiness, PR and full feedback.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

USER_REVIEW_DECISION_SCHEMA = "PASES_USER_REVIEW_DECISION_V1"
FIELDS = frozenset({
    "schema", "repository", "issue_number", "pr_number", "decision",
    "owner_id", "review_session_id", "readiness_sha256", "adc_sha256",
    "pr_head_sha40", "evidence_channel", "predecessor_comment_id",
})
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")


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
    if not isinstance(payload, dict) or set(payload) != FIELDS or _canonical(payload) != body:
        raise UserReviewRelayError("dedicated review fields or canonical bytes differ")
    if (payload["schema"] != USER_REVIEW_DECISION_SCHEMA or payload["decision"] != "APPROVED"
            or payload["evidence_channel"] != "delegated_github_relay"
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
    return payload


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

    def as_selected_evidence(self) -> dict[str, Any]:
        return {
            "evidence_type": USER_REVIEW_DECISION_SCHEMA,
            "evidence_channel": self.evidence_channel,
            "comment_id": self.comment_id, "body_sha256": self.body_sha256,
            "owner_id": self.owner_id, "created_at": self.created_at,
            "review_session_sha256": self.review_session_sha256,
            "predecessor_comment_id": self.predecessor_comment_id,
        }


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
        if not body.startswith('{"'):
            continue
        if USER_REVIEW_DECISION_SCHEMA not in body:
            continue
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
            current.append((comment_id, decision, identity))
    if len(current) != 1:
        raise UserReviewRelayError("expected exactly one current-session carrier")
    comment_id, decision, identity = current[0]
    return UserReviewRelayApproval(
        comment_id=comment_id, body_sha256=hashlib.sha256(identity[1].encode("utf-8")).hexdigest(),
        owner_id=repository_owner_user_id, created_at=identity[2],
        review_session_sha256=session.sha256, predecessor_comment_id=decision["predecessor_comment_id"],
    )
