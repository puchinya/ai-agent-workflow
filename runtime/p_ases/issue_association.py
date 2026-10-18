"""Shared parsing for GitHub PR auto-close and P-ASES deferred-close links."""

from __future__ import annotations

import re


_REPOSITORY_PART = r"[A-Za-z0-9_.-]+"
_CLOSING_REF = re.compile(
    rf"(?i)\b(?P<keyword>close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s*:?[\t ]*"
    rf"(?:(?P<owner>{_REPOSITORY_PART})/(?P<repository>{_REPOSITORY_PART}))?"
    r"#(?P<number>[1-9][0-9]*)\b"
)
_CLOSING_LINE = re.compile(r"(?im)^\s*(Closes|Fixes|Resolves)\s+#([1-9][0-9]*)\s*$")
_ISSUE_REF = re.compile(r"(?i)\bRefs?\s+#([1-9][0-9]*)\b")
_ISSUE_REF_LINE = re.compile(r"(?im)^\s*Refs\s+#([1-9][0-9]*)\s*$")


class IssueAssociationError(ValueError):
    pass


def closing_issue_references(body: str, repository: str | None = None) -> tuple[int, ...]:
    """Return auto-close Issue numbers, optionally scoped to one repository.

    Unqualified ``#N`` references are relative to the PR's repository. When a
    repository is supplied, qualified ``OWNER/REPO#N`` references are counted
    only if their normalized repository matches it. Without a repository, all
    qualified references are returned so security preflights can reject any
    unexpected auto-close syntax.
    """
    if not isinstance(body, str):
        raise IssueAssociationError("Issue-closing text must be text")
    normalized_repository = None
    if repository is not None:
        if (not isinstance(repository, str)
                or re.fullmatch(rf"{_REPOSITORY_PART}/{_REPOSITORY_PART}", repository) is None):
            raise IssueAssociationError("repository must be one OWNER/REPO name")
        normalized_repository = repository.casefold()
    references = []
    for match in _CLOSING_REF.finditer(body):
        owner, name = match.group("owner"), match.group("repository")
        qualified_repository = f"{owner}/{name}".casefold() if owner and name else None
        if (normalized_repository is not None and qualified_repository is not None
                and qualified_repository != normalized_repository):
            continue
        references.append(int(match.group("number")))
    return tuple(references)


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
