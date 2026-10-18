"""Shared parsing for GitHub PR auto-close and P-ASES deferred-close links."""

from __future__ import annotations

import re


_CLOSING_REF = re.compile(r"(?i)\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s+#([1-9][0-9]*)\b")
_CLOSING_LINE = re.compile(r"(?im)^\s*(Closes|Fixes|Resolves)\s+#([1-9][0-9]*)\s*$")
_ISSUE_REF = re.compile(r"(?i)\bRefs?\s+#([1-9][0-9]*)\b")
_ISSUE_REF_LINE = re.compile(r"(?im)^\s*Refs\s+#([1-9][0-9]*)\s*$")


class IssueAssociationError(ValueError):
    pass


def closing_issue_references(body: str) -> tuple[int, ...]:
    if not isinstance(body, str):
        raise IssueAssociationError("Issue-closing text must be text")
    return tuple(int(value) for value in _CLOSING_REF.findall(body))


def parse_issue_association(body: str, issue_number: int) -> str:
    """Return ``auto_close`` or ``deferred_close`` for one exact standalone link."""
    if not isinstance(body, str):
        raise IssueAssociationError("PR body must be text")
    if type(issue_number) is not int or issue_number < 1:
        raise IssueAssociationError("PR association Issue number must be positive")
    closes = list(closing_issue_references(body))
    close_lines = [(keyword.casefold(), int(value)) for keyword, value in _CLOSING_LINE.findall(body)]
    refs = [int(value) for value in _ISSUE_REF.findall(body)]
    ref_lines = [int(value) for value in _ISSUE_REF_LINE.findall(body)]
    if closes:
        if closes != [issue_number] or close_lines != [("closes", issue_number)] or refs:
            raise IssueAssociationError("PR body has competing, duplicate, or mismatched closing/reference associations")
        return "auto_close"
    if refs:
        if refs != [issue_number] or ref_lines != [issue_number]:
            raise IssueAssociationError("deferred PR body must have exactly one standalone Refs #N for its Issue")
        return "deferred_close"
    raise IssueAssociationError(
        f"PR body must have exactly one standalone Closes #{issue_number} or Refs #{issue_number} line"
    )
