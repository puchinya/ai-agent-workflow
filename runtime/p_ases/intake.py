"""ADC source intake and execution-authority decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Any

from .adc import ADC, ADCPointer, ADCError, VerifiedADC, parse_adc, verify_adc
from .github import GitHub


class IntakeError(ValueError):
    pass


class Source(str, Enum):
    FILE = "file"
    CHAT = "chat"
    ISSUE = "issue"


class Intent(str, Enum):
    EXECUTE = "execute"
    DRAFT_ONLY = "draft_only"
    REVIEW_ONLY = "review_only"


class Decision(str, Enum):
    EXECUTE = "execute"
    DRAFT = "draft"
    REVIEW_ONLY = "review_only"
    NEEDS_APPROVAL = "needs_approval"
    NEEDS_VERIFICATION = "needs_verification"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Submission:
    source: Source
    repository: str
    issue_number: int
    content: bytes
    explicitly_submitted: bool
    intent: Intent
    state: str = "draft"
    quoted_or_forwarded: bool = False
    issue_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True)
class IntakeResult:
    decision: Decision
    reason: str
    submission: Submission
    verified_adc: VerifiedADC | None = None


@dataclass(frozen=True)
class DraftProposal:
    submission: Submission
    unresolved_questions: tuple[str, ...]


def draft_from_request(
    request: str,
    *,
    repository: str,
    issue_number: int,
) -> DraftProposal:
    """Turn a natural-language request into a non-executable ADC draft."""
    if not isinstance(request, str) or not request.strip() or "\x00" in request:
        raise IntakeError("direct request must be non-empty text without NUL bytes")
    quoted_request = "\n".join(f"> {line}" if line else ">" for line in request.strip().splitlines())
    content = "\n".join((
        "# Agent Development Contract",
        f"Repository: {repository}",
        f"Issue: #{issue_number}",
        "",
        "## Issue",
        "The following user request is the source for this unapproved draft:",
        quoted_request,
        "",
        "## Scope and change kind",
        "Draft: confirm the in-scope behavior and change kind against the current repository contract.",
        "",
        "## Requirements",
        "- REQ-01: Address the explicitly submitted request and define a measurable acceptance condition before execution.",
        "",
        "## Architecture decisions",
        "Draft: inspect the applicable specifications and designs, then record only decisions needed for this request.",
        "",
        "## Artifact impact",
        "Draft: identify affected source, tests, documentation, and generated artifacts during refinement.",
        "",
        "## Exact changes",
        "Draft: enumerate the files and symbols after repository inspection.",
        "",
        "## Invariants and non-goals",
        "Preserve repository invariants; stop and request clarification if the request conflicts with them.",
        "",
        "## Verification obligations",
        "Draft: define acceptance oracles and tests from the confirmed requirements.",
        "",
        "## Reviewer Checklist",
        "- [ ] The target repository and Issue are correct.",
        "- [ ] Scope, requirements, and acceptance evidence are confirmed.",
        "",
        "## Completion gates",
        "This draft is not approved for execution. Present it to the user for confirmation.",
        "",
    ))
    try:
        parse_adc(content.encode("utf-8"), repository, issue_number)
    except ADCError as exc:
        raise IntakeError(f"could not create a safe ADC draft: {exc}") from exc
    submission = from_chat(
        content, repository=repository, issue_number=issue_number, explicitly_submitted=True,
        intent=Intent.DRAFT_ONLY, state="draft",
    )
    return DraftProposal(submission, (
        f"Confirm that this draft targets {repository} Issue #{issue_number}.",
        "Confirm or revise the proposed requirement and measurable acceptance condition.",
        "Confirm the scope and exact files after repository inspection.",
    ))


def from_file(
    path: Path,
    *,
    repository: str,
    issue_number: int,
    explicitly_submitted: bool,
    intent: Intent = Intent.EXECUTE,
    state: str = "draft",
) -> Submission:
    try:
        content = Path(path).read_bytes()
    except OSError as exc:
        raise IntakeError(f"could not read submitted ADC file: {exc}") from exc
    return Submission(Source.FILE, repository, issue_number, content, explicitly_submitted,
                      Intent(intent), state)


def from_chat(
    text: str,
    *,
    repository: str,
    issue_number: int,
    explicitly_submitted: bool,
    intent: Intent = Intent.EXECUTE,
    state: str = "draft",
    quoted_or_forwarded: bool = False,
) -> Submission:
    if not isinstance(text, str):
        raise IntakeError("submitted chat ADC must be text")
    return Submission(Source.CHAT, repository, issue_number, text.encode("utf-8", errors="strict"),
                      explicitly_submitted, Intent(intent), state, quoted_or_forwarded)


def from_issue(github: GitHub, issue_number: int, *, explicitly_submitted: bool,
               intent: Intent = Intent.EXECUTE) -> tuple[Submission, VerifiedADC]:
    try:
        verified = verify_adc(github, issue_number)
        issue = github.issue(issue_number)
    except (ADCError, RuntimeError) as exc:
        raise IntakeError(str(exc)) from exc
    submission = Submission(
        Source.ISSUE, github.repo, issue_number, verified.contract.content,
        explicitly_submitted, Intent(intent), verified.pointer.state,
        issue_snapshot=issue,
    )
    return submission, verified


def decide(submission: Submission, *, expected_repository: str,
           verified_adc: VerifiedADC | None = None,
           invariant_conflicts: tuple[str, ...] = ()) -> IntakeResult:
    """Classify the submission without treating repository content as an instruction."""
    if not isinstance(submission, Submission):
        raise IntakeError("submission must be an Intake Submission")
    if (not isinstance(submission.source, Source) or not isinstance(submission.intent, Intent)
            or not isinstance(submission.state, str) or submission.state not in {"draft", "approved"}
            or type(submission.explicitly_submitted) is not bool
            or type(submission.quoted_or_forwarded) is not bool):
        raise IntakeError("submission source, intent, or state is invalid")
    if (not isinstance(expected_repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected_repository)):
        raise IntakeError("expected repository must be owner/name")
    expected = expected_repository.lower()
    if (not isinstance(submission.repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", submission.repository)
            or submission.repository.lower() != expected):
        return IntakeResult(Decision.BLOCKED, "submission targets a different repository", submission)
    if type(submission.issue_number) is not int or submission.issue_number < 1:
        return IntakeResult(Decision.BLOCKED, "submission has no valid target Issue", submission)
    if not submission.explicitly_submitted:
        return IntakeResult(Decision.BLOCKED, "content was not explicitly submitted by the current user", submission)
    if submission.quoted_or_forwarded:
        return IntakeResult(Decision.BLOCKED, "quoted or forwarded content is not an execution instruction", submission)
    if (not isinstance(invariant_conflicts, tuple)
            or any(not isinstance(question, str) or not question.strip() for question in invariant_conflicts)):
        raise IntakeError("invariant conflicts must be concrete clarification questions")
    if invariant_conflicts:
        return IntakeResult(
            Decision.BLOCKED,
            "clarification required before dependent work: " + "; ".join(invariant_conflicts),
            submission,
        )
    if submission.source is Source.ISSUE:
        issue = submission.issue_snapshot
        repository_url = issue.get("repository_url") if isinstance(issue, dict) else None
        if (not isinstance(issue, dict) or type(issue.get("number")) is not int
                or issue.get("number") != submission.issue_number
                or not isinstance(repository_url, str)
                or repository_url.lower() != f"https://api.github.com/repos/{expected}"):
            return IntakeResult(Decision.BLOCKED, "Issue identity does not match the selected repository and Issue", submission)
        if issue.get("pull_request") is not None:
            return IntakeResult(Decision.BLOCKED, "a pull request is not an ADC Issue", submission)
        if issue.get("state") != "open":
            return IntakeResult(Decision.BLOCKED, "closed Issue cannot start new execution", submission)
    if submission.intent is Intent.DRAFT_ONLY:
        return IntakeResult(Decision.DRAFT, "the user requested contract drafting only", submission, verified_adc)
    if submission.intent is Intent.REVIEW_ONLY:
        return IntakeResult(Decision.REVIEW_ONLY, "the user requested review only", submission, verified_adc)
    if submission.state != "approved":
        return IntakeResult(Decision.NEEDS_APPROVAL, "the ADC is not in the approved state", submission, verified_adc)
    if verified_adc is None:
        return IntakeResult(
            Decision.NEEDS_VERIFICATION,
            "the approved ADC has no verified immutable Issue comment pointer",
            submission,
        )
    if (not isinstance(verified_adc, VerifiedADC)
            or not isinstance(verified_adc.contract, ADC)
            or not isinstance(verified_adc.pointer, ADCPointer)):
        return IntakeResult(Decision.BLOCKED, "ADC verification record is invalid", submission)
    try:
        parsed = parse_adc(submission.content, expected, submission.issue_number)
    except ADCError as exc:
        return IntakeResult(Decision.BLOCKED, f"submitted ADC failed validation: {exc}", submission)
    if (type(verified_adc.pointer.comment_id) is not int or verified_adc.pointer.comment_id < 1
            or verified_adc.pointer.state != "approved"
            or verified_adc.contract.repository != expected
            or verified_adc.contract.issue_number != submission.issue_number
            or verified_adc.contract.content != submission.content
            or verified_adc.contract.sha256 != parsed.sha256
            or verified_adc.pointer.sha256 != parsed.sha256
            or verified_adc.pointer.byte_length != len(submission.content)):
        return IntakeResult(Decision.BLOCKED, "verified ADC does not match the submitted payload", submission)
    return IntakeResult(Decision.EXECUTE, "explicitly submitted approved ADC", submission, verified_adc)
