"""Validate completed, owner-authorized Issue #63 phase bootstrap.

The one-time label mutation belongs to a separately permissioned broker.
The implementation runtime is deliberately read-only and never repeats it.
"""
from __future__ import annotations

import re
from typing import Any

from .owner_consent import OwnerDecisionError, parse_owner_decision, verify_owner_decision_history

SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PhaseRebaselineError(ValueError):
    """The externally bootstrapped phase label cannot be trusted."""


def _identity(row: Any, repository: str, issue_number: int, comment_id: int, owner_id: int) -> tuple[Any, ...]:
    if not isinstance(row, dict) or row.get("id") != comment_id:
        raise PhaseRebaselineError("owner decision comment ID changed")
    user = row.get("user")
    if not isinstance(user, dict) or user.get("id") != owner_id or user.get("type") != "User":
        raise PhaseRebaselineError("owner decision author changed")
    expected = {
        "issue_url": f"https://api.github.com/repos/{repository}/issues/{issue_number}",
        "url": f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}",
        "html_url": f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}",
    }
    if any(row.get(key) != value for key, value in expected.items()):
        raise PhaseRebaselineError("owner decision comment is outside the authorized Issue")
    if (not isinstance(row.get("created_at"), str)
            or row.get("created_at") != row.get("updated_at")):
        raise PhaseRebaselineError("owner decision was edited or is missing timestamps")
    return (row["id"], row.get("body"), user.get("id"), user.get("type"),
            row.get("created_at"), row.get("updated_at"),
            row.get("issue_url"), row.get("url"), row.get("html_url"))


def rebaseline_issue_phase(github: Any, issue_number: int, decision_comment_id: int,
                           successor_adc_sha256: str) -> None:
    """Verify exact broker evidence and already committed requirements labels.

    Any remaining ready label is a BLOCK rather than permission to mutate.
    """
    if (issue_number != 63 or type(decision_comment_id) is not int or decision_comment_id <= 0
            or not isinstance(successor_adc_sha256, str)
            or SHA256.fullmatch(successor_adc_sha256) is None
            or github.repo != "puchinya/ai-agent-workflow"):
        raise PhaseRebaselineError("invalid or unapproved bootstrap target")
    owner_id = 3744776
    try:
        issue_before = github.issue(issue_number)
        labels = issue_before.get("labels") if isinstance(issue_before, dict) else None
        if (issue_before.get("number") != issue_number or issue_before.get("state") != "open"
                or not isinstance(labels, list)
                or any(not isinstance(row, dict) or not isinstance(row.get("name"), str)
                       for row in labels)):
            raise PhaseRebaselineError("Issue readback is incomplete")
        names = [row["name"] for row in labels]
        if (names.count("phase:requirements") != 1
                or any(name.startswith("phase:") and name != "phase:requirements" for name in names)
                or names.count("kind:single") != 1):
            raise PhaseRebaselineError("broker bootstrap phase mutation is not complete")
        before = github.issue_comment(issue_number, decision_comment_id)
        comments = github.issue_comments(issue_number)
        after = github.issue_comment(issue_number, decision_comment_id)
        listed = [c for c in comments if isinstance(c, dict) and c.get("id") == decision_comment_id]
        if len(listed) != 1:
            raise PhaseRebaselineError("owner decision absent or duplicated")
        identity = _identity(before, github.repo, issue_number, decision_comment_id, owner_id)
        if (_identity(listed[0], github.repo, issue_number, decision_comment_id, owner_id) != identity
                or _identity(after, github.repo, issue_number, decision_comment_id, owner_id) != identity):
            raise PhaseRebaselineError("owner decision changed across readback")
        decision = verify_owner_decision_history(
            comments, github.repo, issue_number, owner_id, "PHASE_REBASE", successor_adc_sha256,
        )
        if parse_owner_decision(before.get("body")).as_dict() != decision.as_dict():
            raise PhaseRebaselineError("selected decision differs from canonical comment")
        issue_after = github.issue(issue_number)
        if (issue_before != issue_after):
            raise PhaseRebaselineError("Issue changed during bootstrap validation")
    except OwnerDecisionError as exc:
        raise PhaseRebaselineError(str(exc)) from exc
