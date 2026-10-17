"""Validate completed, owner-authorized Issue #63 phase bootstrap.

The one-time label mutation belongs to a separately permissioned broker.
The implementation runtime is deliberately read-only and never repeats it.
"""
from __future__ import annotations

import re
from typing import Any

from .owner_consent import OwnerDecisionError, read_verified_owner_decision

SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PhaseRebaselineError(ValueError):
    """The externally bootstrapped phase label cannot be trusted."""


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
        decision_before = read_verified_owner_decision(
            github, issue_number=issue_number, owner_id=owner_id,
            operation="PHASE_REBASE", subject_sha256=successor_adc_sha256,
        )
        if decision_before.comment_id != decision_comment_id:
            raise PhaseRebaselineError("exact bootstrap decision comment ID changed")
        issue_before = github.issue(issue_number)
        labels = issue_before.get("labels") if isinstance(issue_before, dict) else None
        if (issue_before.get("number") != issue_number or issue_before.get("state") != "open"
                or issue_before.get("repository_url") != f"https://api.github.com/repos/{github.repo}"
                or issue_before.get("pull_request") is not None
                or not isinstance(labels, list)
                or any(not isinstance(row, dict) or not isinstance(row.get("name"), str)
                       for row in labels)):
            raise PhaseRebaselineError("Issue readback is incomplete")
        names = [row["name"] for row in labels]
        if (names.count("phase:requirements") != 1
                or any(name.startswith("phase:") and name != "phase:requirements" for name in names)
                or names.count("kind:single") != 1):
            raise PhaseRebaselineError("broker bootstrap phase mutation is not complete")
        decision_after = read_verified_owner_decision(
            github, issue_number=issue_number, owner_id=owner_id,
            operation="PHASE_REBASE", subject_sha256=successor_adc_sha256,
        )
        if decision_before != decision_after:
            raise PhaseRebaselineError("owner decision changed across complete history readback")
        issue_after = github.issue(issue_number)
        if (issue_before != issue_after):
            raise PhaseRebaselineError("Issue changed during bootstrap validation")
    except OwnerDecisionError as exc:
        raise PhaseRebaselineError(str(exc)) from exc
