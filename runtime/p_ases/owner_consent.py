"""Read-only verifier for owner-authorized, operation-specific GitHub decisions.

A GitHub comment proves an authenticated GitHub actor, not the source of chat
consent. The separate relay must check direct human consent and permissions
before writing; this module never creates an approval or modifies GitHub.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

SCHEMA = "PASES_OWNER_DECISION_V1"
OPERATIONS = frozenset({"PHASE_REBASE", "ADC_SUPERSEDE", "RULESET_PLAN_APPLY", "PR_MERGE"})
FIELDS = frozenset({
    "schema", "repository", "issue_number", "operation", "subject_sha256",
    "pr_number", "pr_head_sha40", "owner_id", "evidence_channel",
    "predecessor_comment_id",
})
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
START = "<!-- PASES_OWNER_DECISION_V1\n"
END = "\n-->"


class OwnerDecisionError(ValueError):
    """Invalid, ambiguous or unauthenticated delegated owner evidence."""


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise OwnerDecisionError("duplicate owner-decision field")
        result[key] = value
    return result


@dataclass(frozen=True)
class OwnerDecision:
    repository: str
    issue_number: int
    operation: str
    subject_sha256: str
    owner_id: int
    pr_number: int | None
    pr_head_sha40: str | None
    predecessor_comment_id: int | None
    evidence_channel: str = "delegated_github_relay"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "repository": self.repository, "issue_number": self.issue_number,
            "operation": self.operation, "subject_sha256": self.subject_sha256,
            "owner_id": self.owner_id, "pr_number": self.pr_number,
            "pr_head_sha40": self.pr_head_sha40,
            "predecessor_comment_id": self.predecessor_comment_id,
            "evidence_channel": self.evidence_channel,
        }


def parse_owner_decision(body: str) -> OwnerDecision:
    if not isinstance(body, str) or not body.startswith(START) or not body.endswith(END):
        raise OwnerDecisionError("owner decision marker is missing")
    raw = body[len(START):-len(END)]
    try:
        data = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, TypeError) as exc:
        raise OwnerDecisionError("invalid owner decision JSON") from exc
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise OwnerDecisionError("unexpected owner decision fields")
    if (json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")) != raw
            or data["schema"] != SCHEMA or data["operation"] not in OPERATIONS
            or data["evidence_channel"] != "delegated_github_relay"):
        raise OwnerDecisionError("noncanonical or unsupported owner decision")
    if (not isinstance(data["repository"], str) or REPOSITORY.fullmatch(data["repository"]) is None
            or not _positive(data["issue_number"]) or not _positive(data["owner_id"])
            or not isinstance(data["subject_sha256"], str)
            or SHA256.fullmatch(data["subject_sha256"]) is None):
        raise OwnerDecisionError("owner decision subject is invalid")
    predecessor = data["predecessor_comment_id"]
    if predecessor is not None and not _positive(predecessor):
        raise OwnerDecisionError("owner decision predecessor is invalid")
    pr, head = data["pr_number"], data["pr_head_sha40"]
    if (pr is None) != (head is None):
        raise OwnerDecisionError("PR subject must contain both number and HEAD")
    if pr is not None and (not _positive(pr) or not isinstance(head, str) or SHA40.fullmatch(head) is None):
        raise OwnerDecisionError("owner decision PR subject is invalid")
    if data["operation"] in {"PHASE_REBASE", "ADC_SUPERSEDE"} and pr is not None:
        raise OwnerDecisionError("ADC operations must not bind a PR")
    if data["operation"] == "PR_MERGE" and pr is None:
        raise OwnerDecisionError("merge decision must bind a PR")
    return OwnerDecision(
        data["repository"], data["issue_number"], data["operation"],
        data["subject_sha256"], data["owner_id"], pr, head, predecessor,
    )


def verify_owner_decision_history(
    comments: Iterable[dict[str, Any]], repository: str, issue_number: int,
    owner_id: int, operation: str, subject_sha256: str,
) -> OwnerDecision:
    """Verify an append-only chain and select exactly one matching operation.

    For a live operation the caller must first obtain a complete paginated
    comment list and independently read back each linked comment by ID.
    No caller-provided identity or comment body is itself human consent.
    """
    if (not isinstance(repository, str) or not _positive(issue_number)
            or not _positive(owner_id) or operation not in OPERATIONS
            or not isinstance(subject_sha256, str) or SHA256.fullmatch(subject_sha256) is None):
        raise OwnerDecisionError("invalid requested owner decision scope")
    scoped: list[tuple[int, OwnerDecision]] = []
    for row in comments:
        if not isinstance(row, dict):
            raise OwnerDecisionError("malformed owner comment")
        body = row.get("body")
        if not isinstance(body, str) or not body.startswith("<!-- PASES_OWNER_DECISION_V1"):
            continue
        record = parse_owner_decision(body)
        if record.repository != repository or record.issue_number != issue_number:
            raise OwnerDecisionError("owner decision belongs to another repository or Issue")
        user = row.get("user")
        if (not isinstance(user, dict) or user.get("type") != "User"
                or user.get("id") != owner_id or record.owner_id != owner_id):
            raise OwnerDecisionError("owner decision actor is not the configured owner")
        comment_id = row.get("id")
        if not _positive(comment_id):
            raise OwnerDecisionError("owner decision comment ID is invalid")
        scoped.append((comment_id, record))
    scoped.sort(key=lambda pair: pair[0])
    prior: int | None = None
    seen: set[tuple[str, str, int | None, str | None]] = set()
    for comment_id, record in scoped:
        if record.predecessor_comment_id != prior:
            raise OwnerDecisionError("broken owner decision predecessor chain")
        key = (record.operation, record.subject_sha256, record.pr_number, record.pr_head_sha40)
        if key in seen:
            raise OwnerDecisionError("replayed owner decision")
        seen.add(key)
        prior = comment_id
    matches = [record for _id, record in scoped
               if record.operation == operation and record.subject_sha256 == subject_sha256]
    if len(matches) != 1:
        raise OwnerDecisionError("missing or ambiguous exact owner operation/subject")
    return matches[0]
