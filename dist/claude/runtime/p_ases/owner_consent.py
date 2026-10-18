"""Verify append-only owner decisions from all supported authorization routes.

V1 remains delegated relay evidence and V2 remains owner-local TTY evidence.
V3 records an operator-reported direct chat confirmation followed by a
GitHub-authenticated action. V3 is not a chat-host signature or an independent
approval relay.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .github import GitHubError

SCHEMA = "PASES_OWNER_DECISION_V1"
SCHEMA_V2 = "PASES_OWNER_DECISION_V2"
SCHEMA_V3 = "PASES_OWNER_DECISION_V3"
SCHEMAS = frozenset({SCHEMA, SCHEMA_V2, SCHEMA_V3})
OPERATIONS = frozenset({"ADC_SUPERSEDE", "RULESET_PLAN_APPLY", "PR_MERGE", "EXECUTION_ADOPTION"})
FIELDS = frozenset({
    "schema", "repository", "issue_number", "operation", "subject_sha256",
    "pr_number", "pr_head_sha40", "owner_id", "evidence_channel",
    "predecessor_comment_id",
})
FIELDS_V2 = FIELDS | {"plan_sha256", "operation_plan_sha256"}
FIELDS_V3 = FIELDS | {
    "plan_sha256", "operation_plan_sha256", "approval_scope_sha256",
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
START = "<!-- PASES_OWNER_DECISION_V1\n"
START_V2 = "<!-- PASES_OWNER_DECISION_V2\n"
START_V3 = "<!-- PASES_OWNER_DECISION_V3\n"
END = "\n-->"
OWNER_ID = 3744776
REPOSITORY_ID = 1401910271
OWNER_DECISION_MARKER_PREFIX = "<!-- PASES_OWNER_DECISION_"


class OwnerDecisionError(ValueError):
    """Invalid, ambiguous or unauthenticated delegated owner evidence."""


@dataclass(frozen=True)
class VerifiedOwnerDecision:
    """One exact, immutable GitHub carrier verified against its Issue history."""

    comment_id: int
    decision: "OwnerDecision"
    body_sha256: str
    created_at: str


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
    schema: str = SCHEMA
    plan_sha256: str | None = None
    operation_plan_sha256: str | None = None
    approval_scope_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "repository": self.repository, "issue_number": self.issue_number,
            "operation": self.operation, "subject_sha256": self.subject_sha256,
            "owner_id": self.owner_id, "pr_number": self.pr_number,
            "pr_head_sha40": self.pr_head_sha40,
            "predecessor_comment_id": self.predecessor_comment_id,
            "evidence_channel": self.evidence_channel,
            **({"plan_sha256": self.plan_sha256,
                "operation_plan_sha256": self.operation_plan_sha256}
               if self.schema in {SCHEMA_V2, SCHEMA_V3} else {}),
            **({"approval_scope_sha256": self.approval_scope_sha256}
               if self.schema == SCHEMA_V3 else {}),
        }


def parse_owner_decision(body: str) -> OwnerDecision:
    if not isinstance(body, str) or not body.endswith(END):
        raise OwnerDecisionError("owner decision marker is missing")
    if body.startswith(START):
        schema, start, expected_fields, channel = SCHEMA, START, FIELDS, "delegated_github_relay"
    elif body.startswith(START_V2):
        schema, start, expected_fields, channel = SCHEMA_V2, START_V2, FIELDS_V2, "owner_local_tty_v1"
    elif body.startswith(START_V3):
        schema, start, expected_fields, channel = SCHEMA_V3, START_V3, FIELDS_V3, "chat_confirmed_gh_v1"
    else:
        raise OwnerDecisionError("owner decision marker is missing")
    raw = body[len(start):-len(END)]
    try:
        data = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, TypeError) as exc:
        raise OwnerDecisionError("invalid owner decision JSON") from exc
    if not isinstance(data, dict) or set(data) != expected_fields:
        raise OwnerDecisionError("unexpected owner decision fields")
    if (json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")) != raw
            or data["schema"] != schema or data["operation"] not in OPERATIONS
            or data["evidence_channel"] != channel):
        raise OwnerDecisionError("noncanonical or unsupported owner decision")
    if (not isinstance(data["repository"], str) or REPOSITORY.fullmatch(data["repository"]) is None
            or not _positive(data["issue_number"]) or not _positive(data["owner_id"])
            or not isinstance(data["subject_sha256"], str)
            or SHA256.fullmatch(data["subject_sha256"]) is None):
        raise OwnerDecisionError("owner decision subject is invalid")
    if schema in {SCHEMA_V2, SCHEMA_V3} and (not isinstance(data["plan_sha256"], str)
                                            or SHA256.fullmatch(data["plan_sha256"]) is None):
        raise OwnerDecisionError("owner-local decision plan digest is invalid")
    operation_plan_sha256 = data.get("operation_plan_sha256")
    if schema in {SCHEMA_V2, SCHEMA_V3} and operation_plan_sha256 is not None and (
            not isinstance(operation_plan_sha256, str)
            or SHA256.fullmatch(operation_plan_sha256) is None):
        raise OwnerDecisionError("operation plan digest is invalid")
    if (schema in {SCHEMA_V2, SCHEMA_V3} and data["operation"] in {"RULESET_PLAN_APPLY", "EXECUTION_ADOPTION"}
            and operation_plan_sha256 != data["subject_sha256"]):
        raise OwnerDecisionError("operation plan digest differs from its decision subject")
    approval_scope_sha256 = data.get("approval_scope_sha256")
    if schema == SCHEMA_V3 and (not isinstance(approval_scope_sha256, str)
                                or SHA256.fullmatch(approval_scope_sha256) is None):
        raise OwnerDecisionError("chat-confirmed approval scope digest is invalid")
    if data["operation"] == "EXECUTION_ADOPTION" and schema != SCHEMA_V3:
        raise OwnerDecisionError("execution adoption requires the exact chat-confirmed V3 decision")
    predecessor = data["predecessor_comment_id"]
    if predecessor is not None and not _positive(predecessor):
        raise OwnerDecisionError("owner decision predecessor is invalid")
    pr, head = data["pr_number"], data["pr_head_sha40"]
    if (pr is None) != (head is None):
        raise OwnerDecisionError("PR subject must contain both number and HEAD")
    if pr is not None and (not _positive(pr) or not isinstance(head, str) or SHA40.fullmatch(head) is None):
        raise OwnerDecisionError("owner decision PR subject is invalid")
    if data["operation"] == "ADC_SUPERSEDE" and pr is not None:
        raise OwnerDecisionError("ADC operations must not bind a PR")
    if data["operation"] == "RULESET_PLAN_APPLY" and pr is not None:
        raise OwnerDecisionError("Ruleset plan decisions must not bind a PR")
    if data["operation"] in {"PR_MERGE", "EXECUTION_ADOPTION"} and pr is None:
        raise OwnerDecisionError("PR merge/adoption decision must bind an exact PR")
    if data["operation"] == "EXECUTION_ADOPTION" and pr != 64:
        raise OwnerDecisionError("execution adoption is bound only to PR #64")
    return OwnerDecision(
        data["repository"], data["issue_number"], data["operation"],
        data["subject_sha256"], data["owner_id"], pr, head, predecessor,
        channel, schema, data.get("plan_sha256"), operation_plan_sha256,
        approval_scope_sha256,
    )


def _has_owner_decision_marker(body: Any) -> bool:
    # Carrier markers are structural prefixes. Prose may discuss the schema
    # names without creating an owner-decision record.
    return isinstance(body, str) and body.startswith(OWNER_DECISION_MARKER_PREFIX)


def _comment_fingerprint(row: Any, repository: str, issue_number: int) -> tuple[Any, ...]:
    if not isinstance(row, dict):
        raise OwnerDecisionError("owner decision carrier is not an object")
    comment_id = row.get("id")
    user = row.get("user")
    if not _positive(comment_id) or not isinstance(user, dict):
        raise OwnerDecisionError("owner decision carrier identity is incomplete")
    if (type(user.get("id")) is not int or user.get("id") < 1
            or not isinstance(user.get("login"), str) or not user["login"]
            or user.get("type") != "User"):
        raise OwnerDecisionError("owner decision carrier has no stable human author")
    body, created, updated = row.get("body"), row.get("created_at"), row.get("updated_at")
    if not isinstance(body, str) or not isinstance(created, str) or created != updated:
        raise OwnerDecisionError("owner decision carrier was edited or lacks exact timestamps")
    if not created.endswith("Z"):
        raise OwnerDecisionError("owner decision carrier timestamp is not UTC")
    try:
        parsed = datetime.fromisoformat(created[:-1] + "+00:00")
    except ValueError as exc:
        raise OwnerDecisionError("owner decision carrier timestamp is malformed") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise OwnerDecisionError("owner decision carrier timestamp is not UTC")
    expected = {
        "url": f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}",
        "issue_url": f"https://api.github.com/repos/{repository}/issues/{issue_number}",
        "html_url": f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}",
    }
    if any(row.get(key) != value for key, value in expected.items()):
        raise OwnerDecisionError("owner decision carrier belongs to a different repository or Issue")
    return (comment_id, body, created, updated, user["id"], user["login"].casefold(),
            user["type"], row.get("url"), row.get("issue_url"), row.get("html_url"))


def read_verified_owner_decision(
    github: Any, *, issue_number: int, owner_id: int, operation: str,
    subject_sha256: str, expected_pr_number: int | None = None,
    expected_pr_head_sha40: str | None = None, expected_plan_sha256: str | None = None,
    repository_id: int | None = None, expected_approval_scope_sha256: str | None = None,
    expected_schema: str | None = None,
) -> VerifiedOwnerDecision:
    """Read one exact owner decision after full issue and direct/list/direct checks.

    This is a read-only verifier. Chat-origin handling belongs to the in-process
    host integration and is reported rather than cryptographically attested; a
    GitHub comment alone never creates consent.
    """
    repository = getattr(github, "repo", None)
    if (not isinstance(repository, str) or REPOSITORY.fullmatch(repository) is None
            or not _positive(issue_number) or not _positive(owner_id) or operation not in OPERATIONS
            or not isinstance(subject_sha256, str) or SHA256.fullmatch(subject_sha256) is None):
        raise OwnerDecisionError("invalid requested owner decision scope")
    if ((expected_pr_number is None) != (expected_pr_head_sha40 is None)
            or (expected_pr_number is not None and (not _positive(expected_pr_number)
                or not isinstance(expected_pr_head_sha40, str)
                or SHA40.fullmatch(expected_pr_head_sha40) is None))):
        raise OwnerDecisionError("expected PR identity must contain both number and HEAD")
    if (operation in {"PR_MERGE", "EXECUTION_ADOPTION"}) != (expected_pr_number is not None):
        raise OwnerDecisionError("PR merge/adoption operations require an exact PR number and HEAD")
    if operation == "EXECUTION_ADOPTION" and (issue_number != 63 or expected_pr_number != 64):
        raise OwnerDecisionError("execution adoption is restricted to Issue #63 / PR #64")
    if repository_id is not None and not _positive(repository_id):
        raise OwnerDecisionError("configured repository ID is invalid")
    if expected_plan_sha256 is not None and (
            not isinstance(expected_plan_sha256, str) or SHA256.fullmatch(expected_plan_sha256) is None):
        raise OwnerDecisionError("expected owner decision plan digest is invalid")
    if expected_approval_scope_sha256 is not None and (
            not isinstance(expected_approval_scope_sha256, str)
            or SHA256.fullmatch(expected_approval_scope_sha256) is None):
        raise OwnerDecisionError("expected approval scope digest is invalid")
    if expected_schema is not None and expected_schema not in SCHEMAS:
        raise OwnerDecisionError("expected owner decision schema is unsupported")
    try:
        metadata = github.repository_metadata()
        owner = metadata.get("owner") if isinstance(metadata, dict) else None
        issue = github.issue(issue_number)
        expected_repo_url = f"https://api.github.com/repos/{repository}"
        full_name = metadata.get("full_name") if isinstance(metadata, dict) else None
        if (not isinstance(metadata, dict) or not isinstance(full_name, str)
                or full_name.casefold() != repository.casefold()
                or (repository_id is not None and metadata.get("id") != repository_id)
                or not isinstance(owner, dict) or owner.get("type") != "User" or owner.get("id") != owner_id):
            raise OwnerDecisionError("repository identity differs from the configured decision owner")
        if (not isinstance(issue, dict) or issue.get("number") != issue_number or issue.get("state") != "open"
                or issue.get("pull_request") is not None or issue.get("repository_url") != expected_repo_url):
            raise OwnerDecisionError("owner decision target is not the configured open repository Issue")

        initial = github.issue_comments(issue_number)
        initial_candidates = [row for row in initial if _has_owner_decision_marker(
            row.get("body") if isinstance(row, dict) else None)]
        initial_ids: list[int] = []
        for row in initial_candidates:
            if not isinstance(row, dict) or not _positive(row.get("id")):
                raise OwnerDecisionError("owner decision carrier has no valid comment ID")
            initial_ids.append(row["id"])
        if len(initial_ids) != len(set(initial_ids)):
            raise OwnerDecisionError("owner decision carrier ID is duplicated")
        direct_before = {comment_id: github.issue_comment(issue_number, comment_id)
                         for comment_id in initial_ids}
        listed = github.issue_comments(issue_number)
        listed_candidates = [row for row in listed if _has_owner_decision_marker(
            row.get("body") if isinstance(row, dict) else None)]
        listed_ids = [row.get("id") if isinstance(row, dict) else None for row in listed_candidates]
        if listed_ids != initial_ids:
            raise OwnerDecisionError("complete owner decision history changed during direct/list/direct readback")
        direct_after = {comment_id: github.issue_comment(issue_number, comment_id)
                        for comment_id in initial_ids}
        for row in listed_candidates:
            fingerprint = _comment_fingerprint(row, repository, issue_number)
            comment_id = fingerprint[0]
            if (_comment_fingerprint(direct_before[comment_id], repository, issue_number) != fingerprint
                    or _comment_fingerprint(direct_after[comment_id], repository, issue_number) != fingerprint):
                raise OwnerDecisionError("owner decision carrier changed during direct/list/direct readback")
        decision = verify_owner_decision_history(
            listed, repository, issue_number, owner_id, operation, subject_sha256,
        )
        if (decision.pr_number != expected_pr_number
                or decision.pr_head_sha40 != expected_pr_head_sha40):
            raise OwnerDecisionError("owner decision PR identity differs from the requested operation")
        if expected_plan_sha256 is not None and decision.plan_sha256 != expected_plan_sha256:
            raise OwnerDecisionError("owner decision plan digest differs from the requested operation")
        if (expected_approval_scope_sha256 is not None
                and decision.approval_scope_sha256 != expected_approval_scope_sha256):
            raise OwnerDecisionError("owner decision approval scope differs from the presented operation")
        if expected_schema is not None and decision.schema != expected_schema:
            raise OwnerDecisionError("owner decision evidence version differs from the required route")
        selected = [(comment_id, row) for comment_id, row in zip(listed_ids, listed_candidates)
                    if parse_owner_decision(row["body"]) == decision]
        if len(selected) != 1:
            raise OwnerDecisionError("exact owner decision carrier is missing or ambiguous")
        comment_id, row = selected[0]
        return VerifiedOwnerDecision(comment_id, decision,
                                     hashlib.sha256(row["body"].encode("utf-8")).hexdigest(),
                                     row["created_at"])
    except (GitHubError, AttributeError) as exc:
        raise OwnerDecisionError(str(exc)) from exc


def verify_owner_decision_history(
    comments: Iterable[dict[str, Any]], repository: str, issue_number: int,
    owner_id: int, operation: str, subject_sha256: str, *,
    expected_plan_sha256: str | None = None,
    expected_approval_scope_sha256: str | None = None,
    expected_schema: str | None = None,
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
    scoped = verify_owner_decision_history_tail(comments, repository, issue_number, owner_id)
    matches = [record for _id, record in scoped
               if record.operation == operation and record.subject_sha256 == subject_sha256]
    if expected_plan_sha256 is not None:
        matches = [record for record in matches if record.plan_sha256 == expected_plan_sha256]
    if expected_approval_scope_sha256 is not None:
        matches = [record for record in matches
                   if record.approval_scope_sha256 == expected_approval_scope_sha256]
    if expected_schema is not None:
        matches = [record for record in matches if record.schema == expected_schema]
    if not matches:
        raise OwnerDecisionError("missing exact owner operation/subject")
    if len(matches) != 1:
        raise OwnerDecisionError("ambiguous exact owner operation/subject")
    return matches[0]


def verify_owner_decision_history_tail(
    comments: Iterable[dict[str, Any]], repository: str, issue_number: int, owner_id: int,
) -> tuple[tuple[int, OwnerDecision], ...]:
    """Verify the complete cross-version append-only decision chain."""
    if (not isinstance(repository, str) or REPOSITORY.fullmatch(repository) is None
            or not _positive(issue_number) or not _positive(owner_id)):
        raise OwnerDecisionError("invalid requested owner history scope")
    scoped: list[tuple[int, OwnerDecision]] = []
    for row in comments:
        if not isinstance(row, dict):
            raise OwnerDecisionError("malformed owner comment")
        body = row.get("body")
        if not isinstance(body, str):
            continue
        if (body.startswith(OWNER_DECISION_MARKER_PREFIX)
                and not any(body.startswith(f"<!-- {schema}\n") for schema in SCHEMAS)):
            raise OwnerDecisionError("unknown or malformed owner decision marker")
        if not any(body.startswith(f"<!-- {schema}") for schema in SCHEMAS):
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
            raise OwnerDecisionError("replayed owner decision across evidence versions")
        seen.add(key)
        prior = comment_id
    return tuple(scoped)
