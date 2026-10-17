"""Exact-scope owner authorization plans and GitHub decision records.

V1/V2 remain read-compatible. The standard V3 path records an operator-reported
direct chat confirmation followed by a GitHub-authenticated owner action. The
runtime cannot cryptographically attest the chat host or its user-role metadata.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .git import GitError, head_sha40, worktree_clean
from .github import GitHubError
from .owner_consent import (
    END, FIELDS_V2, FIELDS_V3, OPERATIONS, OWNER_ID, REPOSITORY_ID,
    SCHEMA_V2, SCHEMA_V3, START_V2, START_V3,
    OwnerDecisionError, read_verified_owner_decision,
    verify_owner_decision_history_tail, _comment_fingerprint, _has_owner_decision_marker,
)

REPOSITORY = "puchinya/ai-agent-workflow"
ISSUE_NUMBER = 63
PLAN_SCHEMA = "PASES_OWNER_AUTHORIZATION_PLAN_V2"
PLAN_OPERATIONS = OPERATIONS | {"USER_REVIEW"}
PLAN_FIELDS = frozenset({
    "schema", "repository", "repository_id", "owner_id", "issue_number",
    "operation", "subject_sha256", "pr_number", "pr_head_sha40",
    "target_issue_number", "source_head_sha40", "details",
    "approval_scope_sha256", "plan_sha256",
})
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
RULESET_APPROVAL_PREFIX = "PASES-RULESET-APPROVE: "


class OwnerAuthorizationError(ValueError):
    """Invalid exact plan, unavailable owner transport, or failed readback."""


@dataclass(frozen=True)
class ChatApprovalGrant:
    """Ephemeral operator-reported confirmation from this direct chat session.

    This is an in-memory orchestration value, not a signed host attestation.
    It must be created only after the current owner directly approves the exact
    scope in the same conversation.
    """

    operation: str
    repository: str
    issue_number: int
    subject_sha256: str
    plan_sha256: str
    approval_scope_sha256: str
    pr_number: int | None
    pr_head_sha40: str | None
    outcome: str
    source: str


def _approval_scope_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "PASES_CHAT_APPROVAL_SCOPE_V1",
        "repository": plan["repository"], "repository_id": plan["repository_id"],
        "owner_id": plan["owner_id"], "issue_number": plan["issue_number"],
        "operation": plan["operation"], "subject_sha256": plan["subject_sha256"],
        "pr_number": plan["pr_number"], "pr_head_sha40": plan["pr_head_sha40"],
        "target_issue_number": plan["target_issue_number"],
        "source_head_sha40": plan["source_head_sha40"], "details": plan["details"],
    }


def _approval_scope_sha256(plan: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(_approval_scope_payload(plan))).hexdigest()


def authorization_presentation(plan: dict[str, Any]) -> dict[str, Any]:
    """Return the exact structured scope the agent must show before asking."""
    checked = _validate_plan(plan)
    return {
        **_approval_scope_payload(checked),
        "plan_sha256": checked["plan_sha256"],
        "approval_scope_sha256": checked["approval_scope_sha256"],
        "assurance": "operator-reported direct chat confirmation plus GitHub-authenticated action; not a signed chat-host attestation",
    }


def capture_direct_chat_confirmation(
    plan: dict[str, Any], *, response: str, user_role: str,
    same_conversation: bool,
) -> ChatApprovalGrant:
    """Capture a direct same-conversation answer; caller is the chat operator.

    The runtime checks the declared role, answer and exact plan binding, but it
    cannot independently authenticate chat-role metadata. This function must
    never be exposed as an approval CLI flag or accept a file as consent.
    """
    checked = _validate_plan(plan)
    if user_role != "user" or same_conversation is not True:
        raise OwnerAuthorizationError("CHAT_PROVENANCE_UNAVAILABLE: direct same-conversation user role is required")
    normalized = response.strip().casefold() if isinstance(response, str) else ""
    if normalized not in {"approve", "approved", "承認する", "このshaを承認する", "この計画を承認する", "この草案を承認する"}:
        raise OwnerAuthorizationError("CHAT_CONFIRMATION_REQUIRED: response is not an explicit approval")
    return ChatApprovalGrant(
        operation=checked["operation"], repository=checked["repository"],
        issue_number=checked["issue_number"], subject_sha256=checked["subject_sha256"],
        plan_sha256=checked["plan_sha256"], approval_scope_sha256=checked["approval_scope_sha256"],
        pr_number=checked["pr_number"], pr_head_sha40=checked["pr_head_sha40"],
        outcome="APPROVED", source="operator_reported_direct_user_message",
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _check_identity(github: Any, issue_number: int, target_issue_number: int | None,
                    pr_number: int | None, pr_head_sha40: str | None) -> None:
    if getattr(github, "repo", None) != REPOSITORY:
        raise OwnerAuthorizationError("owner authorization is configured only for the approved repository")
    metadata = github.repository_metadata()
    owner = metadata.get("owner") if isinstance(metadata, dict) else None
    if (not isinstance(metadata, dict) or metadata.get("id") != REPOSITORY_ID
            or metadata.get("full_name") != REPOSITORY
            or not isinstance(owner, dict) or owner.get("type") != "User"
            or owner.get("id") != OWNER_ID):
        raise OwnerAuthorizationError("fresh repository identity differs from the pinned owner and repository IDs")
    issue = github.issue(issue_number)
    repo_url = f"https://api.github.com/repos/{REPOSITORY}"
    if (not isinstance(issue, dict) or issue.get("number") != issue_number
            or issue.get("state") != "open" or issue.get("pull_request") is not None
            or issue.get("repository_url") != repo_url):
        raise OwnerAuthorizationError("authorization carrier is not the configured open repository Issue")
    if target_issue_number is not None:
        target = github.issue(target_issue_number)
        if (not isinstance(target, dict) or target.get("number") != target_issue_number
                or target.get("state") != "open" or target.get("pull_request") is not None
                or target.get("repository_url") != repo_url):
            raise OwnerAuthorizationError("operation target is not the configured open repository Issue")
    if (pr_number is None) != (pr_head_sha40 is None):
        raise OwnerAuthorizationError("PR authorization requires both the exact number and HEAD")
    if pr_number is not None:
        pr = github.pull_request(pr_number)
        head = pr.get("head") if isinstance(pr, dict) else None
        base = pr.get("base") if isinstance(pr, dict) else None
        head_repo = head.get("repo") if isinstance(head, dict) else None
        base_repo = base.get("repo") if isinstance(base, dict) else None
        if (pr.get("state") != "open" or pr.get("draft") is True
                or not isinstance(head, dict) or head.get("sha") != pr_head_sha40
                or not isinstance(head_repo, dict) or head_repo.get("full_name") != REPOSITORY
                or not isinstance(base_repo, dict) or base_repo.get("full_name") != REPOSITORY):
            raise OwnerAuthorizationError("live PR identity, state, repository, or HEAD differs from the plan")
        if target_issue_number is not None:
            body = pr.get("body")
            if target_issue_number == 63:
                closes = (re.findall(r"(?im)^\s*closes\s+#([1-9][0-9]*)\s*$", body)
                          if isinstance(body, str) else [])
                if closes != ["63"]:
                    raise OwnerAuthorizationError("implementation PR must close the exact Issue #63")
            elif target_issue_number == 57:
                # The Activation Setup PR is about Issue #57 but must leave that
                # long-lived control Issue open. Its canonical V2 carrier binds
                # the target Issue without using a Closes keyword.
                from .consumer_activation import ConsumerActivationError, SETUP_MARKER_V2, _decode
                try:
                    payload = _decode(body, SETUP_MARKER_V2, "Activation Setup PR", allow_trailer=True)
                except ConsumerActivationError as exc:
                    raise OwnerAuthorizationError("PR is not the exact Activation Setup PR for Issue #57") from exc
                if payload.get("activation_issue_number") != 57:
                    raise OwnerAuthorizationError("Activation Setup PR does not bind Issue #57")


def create_authorization_plan(
    github: Any, root: Path, *, operation: str, subject_sha256: str,
    issue_number: int = ISSUE_NUMBER, target_issue_number: int | None = None,
    pr_number: int | None = None, pr_head_sha40: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read live GitHub subjects and create an immutable canonical plan."""
    if operation not in PLAN_OPERATIONS:
        raise OwnerAuthorizationError("unsupported owner operation")
    if (issue_number != ISSUE_NUMBER or not isinstance(subject_sha256, str)
            or SHA256.fullmatch(subject_sha256) is None
            or (target_issue_number is not None and not _positive(target_issue_number))
            or (pr_number is not None and not _positive(pr_number))
            or (pr_head_sha40 is not None and (not isinstance(pr_head_sha40, str)
                                               or SHA40.fullmatch(pr_head_sha40) is None))
            or ((operation in {"PR_MERGE", "USER_REVIEW"}) != (pr_number is not None))):
        raise OwnerAuthorizationError("operation plan has an invalid exact subject")
    if operation == "PR_MERGE" and target_issue_number not in {57, 63}:
        raise OwnerAuthorizationError("PR merge decisions are limited to Activation #57 or implementation #63")
    if operation == "USER_REVIEW" and target_issue_number is not None:
        raise OwnerAuthorizationError("User Review decisions are stored on configured Issue #63")
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise OwnerAuthorizationError("owner authorization requires a regular repository root")
    try:
        if not worktree_clean(root):
            raise OwnerAuthorizationError("owner authorization requires the fixed reviewed commit in a clean worktree")
        source_head = head_sha40(root)
    except GitError as exc:
        raise OwnerAuthorizationError(str(exc)) from exc
    if details is None:
        details = {}
    if not isinstance(details, dict):
        raise OwnerAuthorizationError("authorization plan details must be an object")
    try:
        _canonical(details)
        _check_identity(github, issue_number, target_issue_number, pr_number, pr_head_sha40)
    except (GitHubError, TypeError, ValueError) as exc:
        if isinstance(exc, OwnerAuthorizationError):
            raise
        raise OwnerAuthorizationError(str(exc)) from exc
    payload = {
        "schema": PLAN_SCHEMA, "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "owner_id": OWNER_ID, "issue_number": issue_number, "operation": operation,
        "subject_sha256": subject_sha256, "pr_number": pr_number,
        "pr_head_sha40": pr_head_sha40, "target_issue_number": target_issue_number,
        "source_head_sha40": source_head, "details": details,
    }
    payload["approval_scope_sha256"] = _approval_scope_sha256(payload)
    return {**payload, "plan_sha256": hashlib.sha256(_canonical(payload)).hexdigest()}


def write_authorization_plan(path: Path, plan: dict[str, Any]) -> None:
    """Create a canonical plan file once; never replace an existing plan."""
    verified = _validate_plan(plan)
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise OwnerAuthorizationError("authorization plan output already exists")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical(verified) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise OwnerAuthorizationError("could not create immutable authorization plan") from exc


def _validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PLAN_FIELDS:
        raise OwnerAuthorizationError("authorization plan has unknown or missing fields")
    plan = dict(value)
    supplied = plan.pop("plan_sha256")
    if (plan.get("schema") != PLAN_SCHEMA or plan.get("repository") != REPOSITORY
            or plan.get("repository_id") != REPOSITORY_ID or plan.get("owner_id") != OWNER_ID
            or plan.get("issue_number") != ISSUE_NUMBER or plan.get("operation") not in PLAN_OPERATIONS
            or not isinstance(plan.get("subject_sha256"), str)
            or SHA256.fullmatch(plan["subject_sha256"]) is None
            or (plan.get("target_issue_number") is not None and not _positive(plan["target_issue_number"]))
            or (plan.get("pr_number") is not None and not _positive(plan["pr_number"]))
            or (plan.get("pr_head_sha40") is not None and (not isinstance(plan["pr_head_sha40"], str)
                                                            or SHA40.fullmatch(plan["pr_head_sha40"]) is None))
            or ((plan.get("pr_number") is None) != (plan.get("pr_head_sha40") is None))
            or ((plan["operation"] in {"PR_MERGE", "USER_REVIEW"}) != (plan.get("pr_number") is not None))
            or not isinstance(plan.get("source_head_sha40"), str)
            or SHA40.fullmatch(plan["source_head_sha40"]) is None
            or not isinstance(plan.get("details"), dict)
            or not isinstance(plan.get("approval_scope_sha256"), str)
            or SHA256.fullmatch(plan["approval_scope_sha256"]) is None
            or plan["approval_scope_sha256"] != _approval_scope_sha256(plan)
            or not isinstance(supplied, str) or SHA256.fullmatch(supplied) is None
            or hashlib.sha256(_canonical(plan)).hexdigest() != supplied):
        raise OwnerAuthorizationError("authorization plan digest or subject is invalid")
    details = plan["details"]
    if plan["operation"] == "ADC_SUPERSEDE" and details != {
            "predecessor_comment_id": details.get("predecessor_comment_id"),
            "predecessor_sha256": details.get("predecessor_sha256"),
            "predecessor_byte_length": details.get("predecessor_byte_length"),
            "predecessor_state": details.get("predecessor_state"),
    }:
        raise OwnerAuthorizationError("ADC_SUPERSEDE plan predecessor fields are invalid")
    if plan["operation"] == "ADC_SUPERSEDE":
        if (not _positive(details["predecessor_comment_id"])
                or not isinstance(details["predecessor_sha256"], str)
                or SHA256.fullmatch(details["predecessor_sha256"]) is None
                or not _positive(details["predecessor_byte_length"])
                or details["predecessor_state"] != "approved"):
            raise OwnerAuthorizationError("ADC_SUPERSEDE plan must bind its current approved predecessor")
    if plan["operation"] == "RULESET_PLAN_APPLY" and (
            details != {"activation_issue_number": 57} or plan["target_issue_number"] != 57):
        raise OwnerAuthorizationError("Ruleset authorization plan must bind Activation Issue #57")
    if plan["operation"] == "PR_MERGE" and (
            details != {"target_issue_number": plan["target_issue_number"]}
            or plan["target_issue_number"] not in {57, 63}):
        raise OwnerAuthorizationError("PR merge authorization plan target is invalid")
    if plan["operation"] == "USER_REVIEW":
        if (set(details) != {"review_session_sha256", "readiness_sha256", "adc_sha256",
                             "pr_head_sha40", "feedback_sha256"}
                or plan["target_issue_number"] is not None
                or details.get("pr_head_sha40") != plan["pr_head_sha40"]
                or any(not isinstance(details.get(key), str) or SHA256.fullmatch(details[key]) is None
                       for key in ("review_session_sha256", "readiness_sha256", "adc_sha256", "feedback_sha256"))
                or not isinstance(details.get("pr_head_sha40"), str)
                or SHA40.fullmatch(details["pr_head_sha40"]) is None):
            raise OwnerAuthorizationError("User Review authorization plan details are invalid")
    return {**plan, "plan_sha256": supplied}


def read_authorization_plan(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise OwnerAuthorizationError("authorization plan must be a regular file")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except OwnerAuthorizationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OwnerAuthorizationError("authorization plan is unreadable or invalid JSON") from exc
    plan = _validate_plan(value)
    if raw != _canonical(plan) + b"\n":
        raise OwnerAuthorizationError("authorization plan is not in canonical byte form")
    return plan


def _read_history(github: Any) -> tuple[tuple[int, Any], ...]:
    """Read every V1/V2 decision carrier direct/list/direct before appending."""
    _check_identity(github, ISSUE_NUMBER, None, None, None)
    initial = github.issue_comments(ISSUE_NUMBER)
    def marked(rows: list[Any]) -> list[dict[str, Any]]:
        selected = []
        for row in rows:
            body = row.get("body") if isinstance(row, dict) else None
            if _has_owner_decision_marker(body):
                selected.append(row)
        return selected
    first = marked(initial)
    ids = [row.get("id") for row in first]
    if (any(not _positive(value) for value in ids) or ids != sorted(ids)
            or len(ids) != len(set(ids))):
        raise OwnerAuthorizationError("owner decision history IDs are invalid or nonmonotonic")
    direct_before = {comment_id: github.issue_comment(ISSUE_NUMBER, comment_id) for comment_id in ids}
    second = marked(github.issue_comments(ISSUE_NUMBER))
    second_ids = [row.get("id") for row in second]
    if second_ids != ids:
        raise OwnerAuthorizationError("owner decision history changed during direct/list/direct readback")
    direct_after = {comment_id: github.issue_comment(ISSUE_NUMBER, comment_id) for comment_id in ids}
    for row in second:
        fingerprint = _comment_fingerprint(row, REPOSITORY, ISSUE_NUMBER)
        comment_id = fingerprint[0]
        if (_comment_fingerprint(direct_before[comment_id], REPOSITORY, ISSUE_NUMBER) != fingerprint
                or _comment_fingerprint(direct_after[comment_id], REPOSITORY, ISSUE_NUMBER) != fingerprint):
            raise OwnerAuthorizationError("owner decision carrier changed during direct/list/direct readback")
    try:
        return verify_owner_decision_history_tail(second, REPOSITORY, ISSUE_NUMBER, OWNER_ID)
    except OwnerDecisionError as exc:
        raise OwnerAuthorizationError(str(exc)) from exc


def _check_owner_local_tty(stdin: Any) -> None:
    terminal = sys.stdin if stdin is None else stdin
    try:
        interactive = bool(terminal.isatty())
    except (AttributeError, OSError, ValueError) as exc:
        raise OwnerAuthorizationError("AUTH_TRANSPORT_UNAVAILABLE: owner-local interactive TTY is required") from exc
    cloud_markers = ("CODEX_ENVIRONMENT_ID", "CODEX_EXEC_SERVER_REMOTE_BASE_URL", "CODEX_CLOUD", "CODESPACE_NAME")
    has_cloud_marker = any(os.environ.get(key) for key in cloud_markers)
    shared_auth = any(os.environ.get(key) for key in (
        "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"))
    if not interactive or has_cloud_marker or shared_auth:
        raise OwnerAuthorizationError(
            "AUTH_TRANSPORT_UNAVAILABLE: use the owner's independent trusted local TTY and local gh authentication"
        )


def _decision_body_v2(plan: dict[str, Any], predecessor: int | None) -> str:
    payload = {
        "schema": SCHEMA_V2, "repository": REPOSITORY, "issue_number": ISSUE_NUMBER,
        "operation": plan["operation"], "subject_sha256": plan["subject_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "operation_plan_sha256": (plan["subject_sha256"]
                                  if plan["operation"] == "RULESET_PLAN_APPLY" else None),
        "pr_number": plan["pr_number"],
        "pr_head_sha40": plan["pr_head_sha40"], "owner_id": OWNER_ID,
        "evidence_channel": "owner_local_tty_v1", "predecessor_comment_id": predecessor,
    }
    if set(payload) != FIELDS_V2:
        raise OwnerAuthorizationError("owner decision V2 schema contract is inconsistent")
    return f"{START_V2}{_canonical(payload).decode('utf-8')}\n-->"


def _decision_body_v3(plan: dict[str, Any], predecessor: int | None,
                      grant: ChatApprovalGrant) -> str:
    if (grant.outcome != "APPROVED"
            or grant.operation != plan["operation"]
            or grant.repository != plan["repository"]
            or grant.issue_number != plan["issue_number"]
            or grant.subject_sha256 != plan["subject_sha256"]
            or grant.plan_sha256 != plan["plan_sha256"]
            or grant.approval_scope_sha256 != plan["approval_scope_sha256"]
            or grant.pr_number != plan["pr_number"]
            or grant.pr_head_sha40 != plan["pr_head_sha40"]
            or grant.source != "operator_reported_direct_user_message"):
        raise OwnerAuthorizationError("CHAT_CONFIRMATION_REQUIRED: grant does not bind this exact operation")
    payload = {
        "schema": SCHEMA_V3, "repository": REPOSITORY, "issue_number": ISSUE_NUMBER,
        "operation": plan["operation"], "subject_sha256": plan["subject_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "operation_plan_sha256": (plan["subject_sha256"]
                                  if plan["operation"] == "RULESET_PLAN_APPLY" else None),
        "approval_scope_sha256": plan["approval_scope_sha256"],
        "pr_number": plan["pr_number"], "pr_head_sha40": plan["pr_head_sha40"],
        "owner_id": OWNER_ID, "evidence_channel": "chat_confirmed_gh_v1",
        "predecessor_comment_id": predecessor,
    }
    if set(payload) != FIELDS_V3:
        raise OwnerAuthorizationError("owner decision V3 schema contract is inconsistent")
    return f"{START_V3}{_canonical(payload).decode('utf-8')}\n-->"


def _verify_ruleset_plan_approval(github: Any, plan: dict[str, Any], *, write_missing: bool) -> int:
    if plan["operation"] != "RULESET_PLAN_APPLY" or plan["target_issue_number"] != 57:
        raise OwnerAuthorizationError("Ruleset plan approval requires configured Activation Issue #57")
    expected = f"{RULESET_APPROVAL_PREFIX}{plan['subject_sha256']}\nPASES-REPOSITORY: {REPOSITORY}"
    issue = github.issue(57)
    comments = [row for row in github.issue_comments(57) if isinstance(row, dict)]
    matches = [row for row in comments if row.get("body") == expected]
    if len(matches) > 1:
        raise OwnerAuthorizationError("exact Ruleset plan approval is duplicated")
    if not matches and write_missing:
        try:
            response = github.create_issue_comment(57, expected)
            comment_id = response.get("id") if isinstance(response, dict) else None
            if not _positive(comment_id):
                raise OwnerAuthorizationError("Ruleset plan approval response lacks a comment ID")
        except (GitHubError, OwnerAuthorizationError) as exc:
            # The result may be ambiguous. Read back once; never retry the POST.
            comments = [row for row in github.issue_comments(57) if isinstance(row, dict)]
            matches = [row for row in comments if row.get("body") == expected]
            if len(matches) != 1:
                raise OwnerAuthorizationError("Ruleset plan approval write is ambiguous; no retry was attempted") from exc
        else:
            comments = [row for row in github.issue_comments(57) if isinstance(row, dict)]
            matches = [row for row in comments if row.get("body") == expected]
    if len(matches) != 1:
        raise OwnerAuthorizationError("exact Ruleset plan approval is missing")
    selected = matches[0]
    comment_id = selected.get("id")
    if not _positive(comment_id):
        raise OwnerAuthorizationError("Ruleset plan approval comment ID is invalid")
    first = github.issue_comment(57, comment_id)
    listed_again = [row for row in github.issue_comments(57) if row.get("id") == comment_id]
    final = github.issue_comment(57, comment_id)
    user = final.get("user") if isinstance(final.get("user"), dict) else {}
    fingerprints = (_comment_fingerprint(first, REPOSITORY, 57),
                    _comment_fingerprint(listed_again[0], REPOSITORY, 57),
                    _comment_fingerprint(final, REPOSITORY, 57)) if len(listed_again) == 1 else ()
    if (len(listed_again) != 1 or fingerprints[0] != fingerprints[1]
            or fingerprints[1] != fingerprints[2] or final.get("body") != expected
            or user.get("id") != OWNER_ID or user.get("type") != "User"
            or not isinstance(issue, dict) or issue.get("number") != 57
            or issue.get("state") != "open" or issue.get("repository_url") != f"https://api.github.com/repos/{REPOSITORY}"):
        raise OwnerAuthorizationError("exact Ruleset approval failed owner/source/direct-list-direct verification")
    return comment_id


def authorize_plan(
    github: Any, root: Path, plan_path: Path, *, stdin: Any = None,
    input_fn: Callable[[str], str] = input, user_review_context: dict[str, Any] | None = None,
    source_validator: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Confirm and append one V2 owner decision; no blind retry is attempted."""
    _check_owner_local_tty(stdin)
    plan = read_authorization_plan(plan_path)
    try:
        if not worktree_clean(Path(root)) or head_sha40(Path(root)) != plan["source_head_sha40"]:
            raise OwnerAuthorizationError("fixed reviewed source HEAD changed or worktree is dirty")
    except GitError as exc:
        raise OwnerAuthorizationError(str(exc)) from exc
    identity = github.authenticated_user()
    if identity.get("type") != "User" or identity.get("id") != OWNER_ID:
        raise OwnerAuthorizationError("authenticated GitHub actor is not the configured owner")
    refreshed = create_authorization_plan(
        github, root, operation=plan["operation"], subject_sha256=plan["subject_sha256"],
        issue_number=plan["issue_number"], target_issue_number=plan["target_issue_number"],
        pr_number=plan["pr_number"], pr_head_sha40=plan["pr_head_sha40"], details=plan["details"],
    )
    if refreshed != plan:
        raise OwnerAuthorizationError("live repository, Issue, PR, subject, or plan changed; regenerate the plan")
    print("Owner-local GitHub authorization (this is not a ChatGPT signature):", file=sys.stderr)
    print(json.dumps({key: plan[key] for key in (
        "operation", "repository", "issue_number", "target_issue_number", "subject_sha256",
        "pr_number", "pr_head_sha40", "plan_sha256",
    )}, sort_keys=True, indent=2), file=sys.stderr)
    try:
        supplied = input_fn("Type the exact displayed plan SHA-256 to authorize: ").strip()
    except (EOFError, KeyboardInterrupt, OSError) as exc:
        raise OwnerAuthorizationError("owner authorization cancelled; no GitHub write was attempted") from exc
    if supplied != plan["plan_sha256"]:
        raise OwnerAuthorizationError("typed plan SHA does not match; no GitHub write was attempted")
    refreshed_after_confirmation = create_authorization_plan(
        github, root, operation=plan["operation"], subject_sha256=plan["subject_sha256"],
        issue_number=plan["issue_number"], target_issue_number=plan["target_issue_number"],
        pr_number=plan["pr_number"], pr_head_sha40=plan["pr_head_sha40"], details=plan["details"],
    )
    if refreshed_after_confirmation != plan:
        raise OwnerAuthorizationError("live subject changed after confirmation; no GitHub write was attempted")
    if source_validator is not None:
        revalidated_context = source_validator()
        if plan["operation"] == "USER_REVIEW":
            user_review_context = revalidated_context

    if plan["operation"] == "USER_REVIEW":
        if not isinstance(user_review_context, dict):
            raise OwnerAuthorizationError("USER_REVIEW commit requires its exact validated session and feedback context")
        details = plan["details"]
        session = user_review_context.get("session")
        if (getattr(session, "sha256", None) != details.get("review_session_sha256")
                or getattr(getattr(session, "subject", None), "readiness_sha256", None)
                   != details.get("readiness_sha256")
                or plan["pr_head_sha40"] != details.get("pr_head_sha40")
                or plan["subject_sha256"] != user_review_context.get("subject_sha256")):
            raise OwnerAuthorizationError("validated User Review context differs from the approved plan")
        from .user_review_relay import publish_owner_local_user_review_decision
        approval = publish_owner_local_user_review_decision(
            github, repository=REPOSITORY, issue_number=ISSUE_NUMBER,
            pr_number=plan["pr_number"], repository_owner_user_id=OWNER_ID,
            session=session, readiness_sha256=details["readiness_sha256"],
            adc_sha256=details["adc_sha256"], pr_head_sha40=details["pr_head_sha40"],
            feedback_sha256=details["feedback_sha256"], plan_sha256=plan["plan_sha256"],
        )
        return {
            "status": "AUTHORIZED", "operation": "USER_REVIEW",
            "plan_sha256": plan["plan_sha256"], "subject_sha256": plan["subject_sha256"],
            "owner_decision_comment_id": approval.comment_id,
            "evidence_type": approval.evidence_type,
            "evidence_channel": approval.evidence_channel, "chat_signature": False,
        }

    history = _read_history(github)
    same_subject = [(comment_id, decision) for comment_id, decision in history
                    if decision.operation == plan["operation"]
                    and decision.subject_sha256 == plan["subject_sha256"]
                    and decision.pr_number == plan["pr_number"]
                    and decision.pr_head_sha40 == plan["pr_head_sha40"]]
    if len(same_subject) > 1:
        raise OwnerAuthorizationError("operation subject already has duplicate owner decisions")
    if same_subject:
        comment_id, decision = same_subject[0]
        if (decision.schema != SCHEMA_V2 or decision.plan_sha256 != plan["plan_sha256"]
                or decision.evidence_channel != "owner_local_tty_v1"):
            raise OwnerAuthorizationError("operation subject is already authorized under a different record")
    else:
        predecessor = history[-1][0] if history else None
        body = _decision_body_v2(plan, predecessor)
        try:
            github.create_issue_comment(ISSUE_NUMBER, body)
        except GitHubError as exc:
            # Reconcile a possibly successful POST by complete readback. Never issue a second POST.
            try:
                verified = read_verified_owner_decision(
                    github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID,
                    operation=plan["operation"], subject_sha256=plan["subject_sha256"],
                    expected_pr_number=plan["pr_number"], expected_pr_head_sha40=plan["pr_head_sha40"],
                    expected_plan_sha256=plan["plan_sha256"], repository_id=REPOSITORY_ID,
                )
            except OwnerDecisionError as verify_error:
                raise OwnerAuthorizationError("owner decision POST is ambiguous; no retry was attempted") from verify_error
            decision = verified.decision
            comment_id = verified.comment_id
        else:
            verified = read_verified_owner_decision(
                github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID,
                operation=plan["operation"], subject_sha256=plan["subject_sha256"],
                expected_pr_number=plan["pr_number"], expected_pr_head_sha40=plan["pr_head_sha40"],
                expected_plan_sha256=plan["plan_sha256"], repository_id=REPOSITORY_ID,
            )
            decision = verified.decision
            comment_id = verified.comment_id
    result: dict[str, Any] = {
        "status": "AUTHORIZED", "operation": plan["operation"], "plan_sha256": plan["plan_sha256"],
        "subject_sha256": plan["subject_sha256"], "owner_decision_comment_id": comment_id,
        "evidence_type": SCHEMA_V2, "evidence_channel": "owner_local_tty_v1",
        "chat_signature": False,
    }
    if plan["operation"] == "RULESET_PLAN_APPLY":
        result["ruleset_approval_comment_id"] = _verify_ruleset_plan_approval(
            github, plan, write_missing=True,
        )
    return result


def authorize_chat_confirmed_plan(
    github: Any, root: Path, plan: dict[str, Any], grant: ChatApprovalGrant, *,
    user_review_context: dict[str, Any] | None = None,
    source_validator: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Append one V3 decision from an ephemeral same-chat confirmation grant.

    This is intentionally an in-process API: the CLI cannot authenticate a
    ChatGPT user-role event and therefore must never accept approval through a
    command-line switch or JSON file. The record describes operator-reported
    chat confirmation and the authenticated GitHub actor, not a signed chat.
    """
    checked = _validate_plan(plan)
    if not isinstance(grant, ChatApprovalGrant):
        raise OwnerAuthorizationError("CHAT_CONFIRMATION_REQUIRED: typed direct-chat grant is missing")
    # Bind every field before any GitHub write and verify the carrier body can
    # only be formed for this exact scope.
    _decision_body_v3(checked, None, grant)
    try:
        if not worktree_clean(Path(root)) or head_sha40(Path(root)) != checked["source_head_sha40"]:
            raise OwnerAuthorizationError("fixed reviewed source HEAD changed or worktree is dirty")
    except GitError as exc:
        raise OwnerAuthorizationError(str(exc)) from exc
    identity = github.authenticated_user()
    if identity.get("type") != "User" or identity.get("id") != OWNER_ID:
        raise OwnerAuthorizationError("authenticated GitHub actor is not the configured owner")
    refreshed = create_authorization_plan(
        github, root, operation=checked["operation"], subject_sha256=checked["subject_sha256"],
        issue_number=checked["issue_number"], target_issue_number=checked["target_issue_number"],
        pr_number=checked["pr_number"], pr_head_sha40=checked["pr_head_sha40"],
        details=checked["details"],
    )
    if refreshed != checked:
        raise OwnerAuthorizationError("live repository, Issue, PR, source, or plan changed after chat approval")
    if checked["operation"] == "ADC_SUPERSEDE":
        from .adc import ADCError, verify_adc
        try:
            predecessor = verify_adc(github, ISSUE_NUMBER).pointer
        except ADCError as exc:
            raise OwnerAuthorizationError("current approved ADC predecessor is unavailable") from exc
        details = checked["details"]
        if (predecessor.state != "approved"
                or predecessor.comment_id != details.get("predecessor_comment_id")
                or predecessor.sha256 != details.get("predecessor_sha256")
                or predecessor.byte_length != details.get("predecessor_byte_length")
                or predecessor.state != details.get("predecessor_state")):
            raise OwnerAuthorizationError("current approved ADC predecessor changed after plan creation")
    if source_validator is not None:
        revalidated_context = source_validator()
        if checked["operation"] == "USER_REVIEW":
            user_review_context = revalidated_context

    if checked["operation"] == "USER_REVIEW":
        if not isinstance(user_review_context, dict):
            raise OwnerAuthorizationError("USER_REVIEW requires its exact validated session and feedback context")
        details = checked["details"]
        session = user_review_context.get("session")
        if (getattr(session, "sha256", None) != details.get("review_session_sha256")
                or getattr(getattr(session, "subject", None), "readiness_sha256", None)
                   != details.get("readiness_sha256")
                or checked["pr_head_sha40"] != details.get("pr_head_sha40")
                or checked["subject_sha256"] != user_review_context.get("subject_sha256")):
            raise OwnerAuthorizationError("validated User Review context differs from the approved plan")
        from .user_review_relay import publish_chat_confirmed_user_review_decision
        approval = publish_chat_confirmed_user_review_decision(
            github, repository=REPOSITORY, issue_number=ISSUE_NUMBER,
            pr_number=checked["pr_number"], repository_owner_user_id=OWNER_ID,
            session=session, readiness_sha256=details["readiness_sha256"],
            adc_sha256=details["adc_sha256"], pr_head_sha40=details["pr_head_sha40"],
            feedback_sha256=details["feedback_sha256"], plan_sha256=checked["plan_sha256"],
            approval_scope_sha256=checked["approval_scope_sha256"],
        )
        return {
            "status": "AUTHORIZED", "operation": "USER_REVIEW",
            "plan_sha256": checked["plan_sha256"], "subject_sha256": checked["subject_sha256"],
            "approval_scope_sha256": checked["approval_scope_sha256"],
            "owner_decision_comment_id": approval.comment_id,
            "evidence_type": approval.evidence_type,
            "evidence_channel": approval.evidence_channel, "chat_signature": False,
        }

    history = _read_history(github)
    same_subject = [(comment_id, decision) for comment_id, decision in history
                    if decision.operation == checked["operation"]
                    and decision.subject_sha256 == checked["subject_sha256"]
                    and decision.pr_number == checked["pr_number"]
                    and decision.pr_head_sha40 == checked["pr_head_sha40"]]
    if same_subject:
        raise OwnerAuthorizationError("operation subject already has an owner decision; no replay or second V3 record")
    predecessor = history[-1][0] if history else None
    body = _decision_body_v3(checked, predecessor, grant)
    try:
        github.create_issue_comment(ISSUE_NUMBER, body)
    except GitHubError as exc:
        # Resolve an uncertain POST with reads only; never retry it.
        try:
            verified = read_verified_owner_decision(
                github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID,
                operation=checked["operation"], subject_sha256=checked["subject_sha256"],
                expected_pr_number=checked["pr_number"], expected_pr_head_sha40=checked["pr_head_sha40"],
                expected_plan_sha256=checked["plan_sha256"], repository_id=REPOSITORY_ID,
                expected_approval_scope_sha256=checked["approval_scope_sha256"],
                expected_schema=SCHEMA_V3,
            )
        except OwnerDecisionError as verify_error:
            raise OwnerAuthorizationError("V3 decision POST is ambiguous; no retry was attempted") from verify_error
        if verified.decision.evidence_channel != "chat_confirmed_gh_v1":
            raise OwnerAuthorizationError("readback selected an incompatible approval channel") from exc
    else:
        verified = read_verified_owner_decision(
            github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID,
            operation=checked["operation"], subject_sha256=checked["subject_sha256"],
            expected_pr_number=checked["pr_number"], expected_pr_head_sha40=checked["pr_head_sha40"],
            expected_plan_sha256=checked["plan_sha256"], repository_id=REPOSITORY_ID,
            expected_approval_scope_sha256=checked["approval_scope_sha256"],
            expected_schema=SCHEMA_V3,
        )
    if verified.decision.evidence_channel != "chat_confirmed_gh_v1":
        raise OwnerAuthorizationError("V3 decision readback has an incompatible evidence channel")
    result: dict[str, Any] = {
        "status": "AUTHORIZED", "operation": checked["operation"],
        "plan_sha256": checked["plan_sha256"], "subject_sha256": checked["subject_sha256"],
        "approval_scope_sha256": checked["approval_scope_sha256"],
        "owner_decision_comment_id": verified.comment_id,
        "evidence_type": SCHEMA_V3, "evidence_channel": "chat_confirmed_gh_v1",
        "chat_signature": False,
    }
    if checked["operation"] == "RULESET_PLAN_APPLY":
        result["ruleset_approval_comment_id"] = _verify_ruleset_plan_approval(
            github, checked, write_missing=True,
        )
    return result


def resume_authorization(github: Any, plan_path: Path) -> dict[str, Any]:
    """Read-only reconciliation for a decision that may have been posted."""
    plan = read_authorization_plan(plan_path)
    try:
        verified = read_verified_owner_decision(
            github, issue_number=ISSUE_NUMBER, owner_id=OWNER_ID,
            operation=plan["operation"], subject_sha256=plan["subject_sha256"],
            expected_pr_number=plan["pr_number"], expected_pr_head_sha40=plan["pr_head_sha40"],
            expected_plan_sha256=plan["plan_sha256"], repository_id=REPOSITORY_ID,
        )
    except OwnerDecisionError as exc:
        return {"status": "NOT_FOUND_OR_BLOCKED", "plan_sha256": plan["plan_sha256"], "reasons": [str(exc)]}
    decision = verified.decision
    if (decision.schema == SCHEMA_V3
            and decision.approval_scope_sha256 != plan["approval_scope_sha256"]):
        return {"status": "NOT_FOUND_OR_BLOCKED", "plan_sha256": plan["plan_sha256"],
                "reasons": ["V3 approval scope differs from the current canonical plan"]}
    result: dict[str, Any] = {
        "status": "AUTHORIZED", "operation": plan["operation"], "plan_sha256": plan["plan_sha256"],
        "subject_sha256": plan["subject_sha256"], "owner_decision_comment_id": verified.comment_id,
        "evidence_type": decision.schema, "evidence_channel": decision.evidence_channel,
        "chat_signature": False,
    }
    if decision.schema == SCHEMA_V3:
        result["approval_scope_sha256"] = decision.approval_scope_sha256
    if plan["operation"] == "RULESET_PLAN_APPLY":
        result["ruleset_approval_comment_id"] = _verify_ruleset_plan_approval(
            github, plan, write_missing=False,
        )
    return result
