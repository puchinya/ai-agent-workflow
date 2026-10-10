"""Agent Development Contract validation, immutable publication, and recovery."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .github import GitHub, GitHubError


class ADCError(ValueError):
    pass


SHA256 = re.compile(r"^[0-9a-f]{64}$")
ISSUE_NUMBER = re.compile(r"^(?:#)?([1-9][0-9]*)$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REQ_ID = re.compile(r"(?m)^ {0,3}[-*+]\s+(REQ-[0-9]+):\s*\S.*$")
CHECKLIST_ITEM = re.compile(r"^ {0,3}[-*+]\s+\[[ xX]\]\s+\S.*$")
SECRET_VALUE = re.compile(
    r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{16,}|"
    r"(?:password|client[_-]?secret|authorization|api[_-]?key|access[_-]?token)"
    r"\s*[:=]\s*\S+)"
)
POINTER_TITLE = "Agent Development Contract"
POINTER_FIELDS = re.compile(
    r"^## Agent Development Contract\n"
    r"Comment ID: ([1-9][0-9]*)\n"
    r"SHA-256: ([0-9a-f]{64})\n"
    r"Bytes: ([0-9]+)\n"
    r"State: (draft|approved)\n?$"
)
PUBLISH_TXN_PREFIX = "<!-- PASES_ADC_PUBLISH_V1\n"
PUBLISH_TXN_FIELDS = re.compile(
    r"^<!-- PASES_ADC_PUBLISH_V1\n"
    r"Operation ID: ([0-9a-f]{64})\n"
    r"Predecessor Comment ID: (none|[1-9][0-9]*)\n"
    r"ADC SHA-256: ([0-9a-f]{64})\n"
    r"Bytes: ([0-9]+)\n"
    r"State: (draft|approved)\n"
    r"-->$"
)
REQUIRED_SECTIONS = {
    "issue", "scope", "change_kind", "requirements", "architecture_decisions",
    "artifact_impact", "exact_changes", "invariants", "non_goals",
    "verification_obligations", "reviewer_checklist", "completion_gates",
}


@dataclass(frozen=True)
class ADC:
    repository: str
    issue_number: int
    content: bytes
    sha256: str
    byte_length: int
    sections: tuple[tuple[str, str], ...]
    requirement_ids: tuple[str, ...]
    child_key: str | None = None

    def section(self, name: str) -> str:
        for key, value in self.sections:
            if key == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True)
class ADCPointer:
    comment_id: int
    sha256: str
    byte_length: int
    state: str


@dataclass(frozen=True)
class VerifiedADC:
    contract: ADC
    pointer: ADCPointer


def _repo_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ADCError("ADC Repository metadata is required")
    candidate = value.strip()
    if candidate.startswith(("https://", "http://")):
        parsed = urlsplit(candidate)
        if parsed.hostname is None or parsed.hostname.lower() not in {"github.com", "api.github.com"}:
            raise ADCError("ADC Repository must identify a GitHub owner/name")
        candidate = parsed.path.strip("/")
        if parsed.hostname.lower() == "api.github.com":
            if not candidate.startswith("repos/"):
                raise ADCError("GitHub API repository metadata must use /repos/owner/name")
            candidate = candidate.removeprefix("repos/")
        if candidate.endswith(".git"):
            candidate = candidate[:-4]
    if not REPOSITORY.fullmatch(candidate):
        raise ADCError("ADC Repository must be owner/name")
    return candidate.lower()


def _metadata(text: str) -> tuple[str, str | None, int | None]:
    repos: list[str] = []
    child_keys: list[str] = []
    issue_values: list[str] = []
    fence: tuple[str, int] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if fence is not None:
            marker, length = fence
            if re.match(rf"^ {{0,3}}{re.escape(marker)}{{{length},}}[ \t]*$", line):
                fence = None
            continue
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_match and (fence_match.group(1)[0] == "~" or "`" not in fence_match.group(2)):
            fence = (fence_match.group(1)[0], len(fence_match.group(1)))
            continue
        if re.match(r"^ {0,3}##[ \t]+", line):
            break
        repo_match = re.fullmatch(r"Repository:[ \t]*(\S+)[ \t]*", line)
        child_match = re.fullmatch(r"Child key:[ \t]*([A-Za-z0-9][A-Za-z0-9._-]{0,63})[ \t]*", line)
        issue_match = re.fullmatch(r"Issue:[ \t]*(.+?)[ \t]*", line)
        if repo_match:
            repos.append(repo_match.group(1))
        if child_match:
            child_keys.append(child_match.group(1))
        if issue_match:
            issue_values.append(issue_match.group(1))
    if len(repos) != 1:
        raise ADCError("ADC must contain exactly one Repository: owner/name metadata line")
    if len(child_keys) > 1:
        raise ADCError("ADC has multiple Child key metadata lines")
    if len(issue_values) > 1:
        raise ADCError("ADC has multiple Issue metadata lines")
    issue_number: int | None = None
    if issue_values:
        match = ISSUE_NUMBER.fullmatch(issue_values[0].strip())
        if not match:
            raise ADCError("ADC Issue metadata must be a positive issue number")
        issue_number = int(match.group(1))
    return _repo_name(repos[0]), child_keys[0] if child_keys else None, issue_number


def _outside_fence_text(text: str) -> str:
    """Remove fenced code so examples cannot become contract fields."""
    lines: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        if fence is not None:
            marker, length = fence
            if re.match(rf"^ {{0,3}}{re.escape(marker)}{{{length},}}[ \t]*$", line):
                fence = None
            continue
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match and (match.group(1)[0] == "~" or "`" not in match.group(2)):
            fence = (match.group(1)[0], len(match.group(1)))
            continue
        lines.append(line)
    return "\n".join(lines)


def _outside_h2(text: str) -> tuple[tuple[int, str], ...]:
    headings: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        if fence is not None:
            marker, length = fence
            if re.match(rf"^ {{0,3}}{re.escape(marker)}{{{length},}}[ \t]*$", raw):
                fence = None
        else:
            fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", raw)
            if fence_match and (fence_match.group(1)[0] == "~" or "`" not in fence_match.group(2)):
                fence = (fence_match.group(1)[0], len(fence_match.group(1)))
            else:
                heading = re.match(r"^ {0,3}##[ \t]+(.+?)[ \t]*#*[ \t]*$", raw)
                if heading:
                    title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(1)).strip()
                    headings.append((offset, title))
        offset += len(line)
    return tuple(headings)


def _canonical_section(title: str) -> set[str]:
    title = re.sub(r"^\s*\d+[.)]?\s*", "", title).strip().lower()
    title = re.sub(r"\s+", " ", title)
    aliases = {
        "issue": {"issue"},
        "scope": {"scope", "scope and change kind"},
        "change_kind": {"change kind", "scope and change kind"},
        "requirements": {"requirements", "requirements and acceptance"},
        "architecture_decisions": {"architecture decisions", "design decisions"},
        "artifact_impact": {"artifact impact"},
        "exact_changes": {"exact changes", "exact change set"},
        "invariants": {"invariants", "invariants and non-goals"},
        "non_goals": {"non-goals", "non-goals / forbidden changes", "invariants and non-goals"},
        "verification_obligations": {"verification obligations", "verification"},
        "reviewer_checklist": {"reviewer checklist"},
        "completion_gates": {"completion gates", "completion criteria"},
    }
    return {key for key, titles in aliases.items() if title in titles}


def _sections(data: bytes) -> tuple[tuple[str, str], ...]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ADCError("ADC must be valid UTF-8") from exc
    first_content = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not re.fullmatch(r"# Agent Development Contract(?:\s+[—–-].*)?", first_content):
        raise ADCError("ADC must start with an Agent Development Contract H1")
    result: list[tuple[str, str]] = []
    text_lines = text.splitlines(keepends=True)
    starts: list[tuple[int, int, str]] = []
    fence = None
    line_offset = 0
    for line in text_lines:
        raw = line.rstrip("\r\n")
        if fence is not None:
            marker, length = fence
            if re.match(rf"^ {{0,3}}{re.escape(marker)}{{{length},}}[ \t]*$", raw):
                fence = None
        else:
            fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", raw)
            if fence_match and (fence_match.group(1)[0] == "~" or "`" not in fence_match.group(2)):
                fence = (fence_match.group(1)[0], len(fence_match.group(1)))
            else:
                heading = re.match(r"^ {0,3}##[ \t]+(.+?)[ \t]*#*[ \t]*$", raw)
                if heading:
                    title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(1)).strip()
                    starts.append((line_offset, line_offset + len(line), title))
        line_offset += len(line)
    for index, (_heading_start, body_start, title) in enumerate(starts):
        next_start = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        # Include the heading in the section value so requirement/changelog prose
        # remains available for evidence and future restoration.
        body = text[body_start:next_start].strip()
        keys = _canonical_section(title)
        for key in keys:
            if any(existing == key for existing, _ in result):
                raise ADCError(f"ADC contains duplicate section for {key}")
            result.append((key, body))
    return tuple(result)


def parse_adc(data: bytes, repository: str, issue_number: int) -> ADC:
    if not isinstance(data, bytes) or not data:
        raise ADCError("ADC must be non-empty exact bytes")
    if b"\x00" in data:
        raise ADCError("ADC must not contain NUL bytes")
    if type(issue_number) is not int or issue_number < 1:
        raise ADCError("Issue number must be a positive integer")
    expected_repo = _repo_name(repository)
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ADCError("ADC must be valid UTF-8") from exc
    if SECRET_VALUE.search(text):
        raise ADCError("ADC appears to contain a credential or secret value")
    actual_repo, child_key, declared_issue = _metadata(text)
    if actual_repo != expected_repo:
        raise ADCError("ADC Repository does not match the selected repository")
    if declared_issue is not None and declared_issue != issue_number:
        raise ADCError("ADC Issue metadata does not match the selected Issue")
    sections = _sections(data)
    section_map = dict(sections)
    missing = sorted(REQUIRED_SECTIONS - section_map.keys())
    if missing:
        raise ADCError("ADC is missing required sections: " + ", ".join(missing))
    empty = sorted(key for key in REQUIRED_SECTIONS if not section_map[key].strip())
    if empty:
        raise ADCError("ADC has empty required sections: " + ", ".join(empty))
    requirement_ids = tuple(REQ_ID.findall(_outside_fence_text(section_map["requirements"])))
    if not requirement_ids:
        raise ADCError("ADC Requirements must include at least one stable REQ-ID")
    if len(set(requirement_ids)) != len(requirement_ids):
        raise ADCError("ADC Requirements contain duplicate REQ-IDs")
    checklist = [line for line in _outside_fence_text(section_map["reviewer_checklist"]).splitlines()
                 if line.strip()]
    if not checklist or any(not CHECKLIST_ITEM.fullmatch(line) for line in checklist):
        raise ADCError("ADC Reviewer Checklist must contain only Markdown checkbox items")
    return ADC(
        repository=expected_repo,
        issue_number=issue_number,
        content=data,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_length=len(data),
        sections=tuple(sorted(sections)),
        requirement_ids=requirement_ids,
        child_key=child_key,
    )


def parse_pointer(body: str) -> ADCPointer | None:
    if not isinstance(body, str):
        raise ADCError("Issue body must be text")
    headings = [(start, title) for start, title in _outside_h2(body) if title == POINTER_TITLE]
    if not headings:
        return None
    if len(headings) != 1:
        raise ADCError("Issue body must contain at most one Agent Development Contract pointer")
    start = headings[0][0]
    next_heading = next((position for position, _ in _outside_h2(body) if position > start), None)
    end = len(body) if next_heading is None else next_heading
    block = body[start:end].strip("\r\n")
    match = POINTER_FIELDS.fullmatch(block)
    if match is None:
        raise ADCError("Agent Development Contract pointer is malformed")
    return ADCPointer(int(match.group(1)), match.group(2), int(match.group(3)), match.group(4))


def _pointer_block(pointer: ADCPointer) -> str:
    return (
        f"## {POINTER_TITLE}\n"
        f"Comment ID: {pointer.comment_id}\n"
        f"SHA-256: {pointer.sha256}\n"
        f"Bytes: {pointer.byte_length}\n"
        f"State: {pointer.state}\n"
    )


def _replace_pointer(body: str, pointer: ADCPointer) -> str:
    headings = [(start, title) for start, title in _outside_h2(body) if title == POINTER_TITLE]
    if len(headings) > 1:
        raise ADCError("Issue body contains multiple Agent Development Contract pointers")
    block = _pointer_block(pointer)
    if not headings:
        separator = "" if not body else ("\n" if body.endswith("\n") else "\n\n")
        return body + separator + block
    current = parse_pointer(body)
    if current is None:
        raise ADCError("Agent Development Contract pointer is missing")
    start = headings[0][0]
    next_heading = next((position for position, _ in _outside_h2(body) if position > start), None)
    end = len(body) if next_heading is None else next_heading
    return body[:start] + block + body[end:]


def _check_issue(issue: Any, repository: str, issue_number: int) -> dict[str, Any]:
    expected_repo = _repo_name(repository)
    expected_url = f"https://api.github.com/repos/{expected_repo}"
    repository_url = issue.get("repository_url") if isinstance(issue, dict) else None
    if (not isinstance(issue, dict) or type(issue.get("number")) is not int
            or issue.get("number") != issue_number or not isinstance(repository_url, str)
            or repository_url.lower() != expected_url
            or issue.get("pull_request") is not None):
        raise ADCError("GitHub Issue identity does not match the selected repository and Issue")
    return issue


def _check_comment(comment: Any, repository: str, issue_number: int, comment_id: int) -> dict[str, Any]:
    expected_issue_url = f"https://api.github.com/repos/{_repo_name(repository)}/issues/{issue_number}"
    issue_url = comment.get("issue_url") if isinstance(comment, dict) else None
    if (not isinstance(comment, dict) or type(comment.get("id")) is not int
            or comment.get("id") != comment_id or not isinstance(issue_url, str)
            or issue_url.lower() != expected_issue_url):
        raise ADCError("named ADC comment does not belong to the selected Issue")
    return comment


def _publication_operation_id(
    repository: str,
    issue_number: int,
    predecessor_id: str,
    adc_sha256: str,
    byte_length: int,
    state: str,
) -> str:
    """Bind retries to the pointer they started from, so A→B→A is a new operation."""
    data = (
        f"{_repo_name(repository)}\n{issue_number}\n{predecessor_id}\n"
        f"{adc_sha256}\n{byte_length}\n{state}\n"
    ).encode("ascii")
    return hashlib.sha256(data).hexdigest()


def _publication_transaction(
    github: GitHub,
    issue_number: int,
    contract: ADC,
    *,
    state: str,
    current_pointer: ADCPointer | None,
) -> tuple[str, int]:
    """Find or write a durable marker that identifies this exact publish attempt."""
    predecessor_id = "none" if current_pointer is None else str(current_pointer.comment_id)
    operation_id = _publication_operation_id(
        github.repo, issue_number, predecessor_id, contract.sha256, contract.byte_length, state,
    )
    marker_body = (
        "<!-- PASES_ADC_PUBLISH_V1\n"
        f"Operation ID: {operation_id}\n"
        f"Predecessor Comment ID: {predecessor_id}\n"
        f"ADC SHA-256: {contract.sha256}\n"
        f"Bytes: {contract.byte_length}\n"
        f"State: {state}\n"
        "-->"
    )
    try:
        listed_comments = github.issue_comments(issue_number)
        same_operation: list[dict[str, Any]] = []
        for listed in listed_comments:
            if not isinstance(listed, dict) or not isinstance(listed.get("body"), str):
                continue
            if not listed["body"].startswith(PUBLISH_TXN_PREFIX):
                continue
            match = PUBLISH_TXN_FIELDS.fullmatch(listed["body"])
            if match is None:
                raise ADCError("malformed ADC publication marker; refusing to publish")
            marker_operation_id, marker_predecessor, marker_sha, marker_bytes, marker_state = match.groups()
            computed_id = _publication_operation_id(
                github.repo, issue_number, marker_predecessor, marker_sha, int(marker_bytes), marker_state,
            )
            if marker_operation_id != computed_id:
                raise ADCError("ADC publication marker identity does not match its fields")
            if marker_operation_id == operation_id:
                same_operation.append(listed)
            elif marker_predecessor == predecessor_id:
                raise ADCError(
                    "another ADC publication is unresolved for this pointer; resume it before starting a different publish"
                )
        if len(same_operation) > 1:
            raise ADCError("multiple ADC publication markers exist for this operation; refusing recovery")
        if same_operation:
            marker = same_operation[0]
            marker_id = marker.get("id")
            if type(marker_id) is not int or marker_id < 1:
                raise ADCError("ADC publication marker has an invalid Comment ID")
            if marker["body"] != marker_body:
                raise ADCError("ADC publication marker does not match the requested operation")
        else:
            created = github.create_issue_comment(issue_number, marker_body)
            marker_id = created.get("id") if isinstance(created, dict) else None
            if type(marker_id) is not int or marker_id < 1:
                raise ADCError("ADC publication marker is missing a valid Comment ID")
        readback = _check_comment(
            github.issue_comment(issue_number, marker_id), github.repo, issue_number, marker_id,
        )
        if readback.get("body") != marker_body:
            raise ADCError("ADC publication marker readback does not match the requested operation")
        return operation_id, marker_id
    except GitHubError as exc:
        raise ADCError(str(exc)) from exc


def _find_reusable_comment(
    github: GitHub,
    issue_number: int,
    contract: ADC,
    *,
    current_pointer: ADCPointer | None,
    transaction_marker_id: int,
) -> int | None:
    """Find only a matching ADC created after this exact operation's marker."""
    matches: list[int] = []
    for listed in github.issue_comments(issue_number):
        if not isinstance(listed, dict) or not isinstance(listed.get("body"), str):
            continue
        listed_bytes = listed["body"].encode("utf-8", errors="strict")
        if listed_bytes != contract.content:
            continue
        comment_id = listed.get("id")
        if type(comment_id) is not int or comment_id < 1:
            raise ADCError("matching unpointed ADC comment has an invalid Comment ID")
        # A permanent marker is written before this publication's ADC comment.
        # Older exact matches are completed historical publications, not retry artifacts.
        if comment_id <= transaction_marker_id:
            continue
        if current_pointer is not None and comment_id == current_pointer.comment_id:
            continue
        _check_comment(listed, github.repo, issue_number, comment_id)
        digest = hashlib.sha256(listed_bytes).hexdigest()
        if digest != contract.sha256 or len(listed_bytes) != contract.byte_length:
            raise ADCError("matching unpointed ADC comment does not match the exact submitted bytes")
        matches.append(comment_id)
    if len(matches) > 1:
        raise ADCError("multiple identical unpointed ADC comments exist; refusing ambiguous recovery")
    return matches[0] if matches else None


def publish_adc(
    github: GitHub,
    issue_number: int,
    data: bytes,
    *,
    state: str = "draft",
    explicitly_approved: bool = False,
    supersede: bool = False,
) -> ADCPointer:
    """Publish exact ADC bytes with a hidden immutable transaction marker for safe retries."""
    if state not in {"draft", "approved"}:
        raise ADCError("ADC state must be draft or approved")
    if type(supersede) is not bool or type(explicitly_approved) is not bool:
        raise ADCError("ADC approval and supersession flags must be explicit booleans")
    if state == "approved" and explicitly_approved is not True:
        raise ADCError("publishing an approved ADC requires explicit user approval")
    contract = parse_adc(data, github.repo, issue_number)
    try:
        before = _check_issue(github.issue(issue_number), github.repo, issue_number)
    except GitHubError as exc:
        raise ADCError(str(exc)) from exc
    if before.get("state") != "open":
        raise ADCError("ADC can only be published to an open Issue")
    if before.get("body") is not None and not isinstance(before.get("body"), str):
        raise ADCError("GitHub Issue body is not text")
    old_body = before.get("body") or ""
    existing_pointer = parse_pointer(old_body)
    if existing_pointer is not None and not supersede:
        raise ADCError("Issue already has an ADC; use explicit supersession to publish another immutable comment")
    try:
        body_text = data.decode("utf-8", errors="strict")
        _operation_id, transaction_marker_id = _publication_transaction(
            github, issue_number, contract, state=state, current_pointer=existing_pointer,
        )
        after_marker = _check_issue(github.issue(issue_number), github.repo, issue_number)
        if after_marker.get("state") != "open" or after_marker.get("body", "") != old_body:
            raise ADCError("Issue identity, state, or ADC pointer changed during publication")
        comment_id = _find_reusable_comment(
            github, issue_number, contract, current_pointer=existing_pointer,
            transaction_marker_id=transaction_marker_id,
        )
        if comment_id is None:
            created = github.create_issue_comment(issue_number, body_text)
            comment_id = created.get("id") if isinstance(created, dict) else None
        if type(comment_id) is not int or comment_id < 1:
            raise ADCError("created ADC comment is missing a valid Comment ID")
        named = _check_comment(github.issue_comment(issue_number, comment_id), github.repo, issue_number, comment_id)
        if not isinstance(named.get("body"), str):
            raise ADCError("named ADC comment has no text body")
        readback = named["body"].encode("utf-8", errors="strict")
        digest = hashlib.sha256(readback).hexdigest()
        if (readback != contract.content or digest != contract.sha256
                or len(readback) != contract.byte_length):
            raise ADCError("named ADC comment readback does not match the exact submitted bytes")
        after_comment = _check_issue(github.issue(issue_number), github.repo, issue_number)
        if after_comment.get("state") != "open" or after_comment.get("body", "") != old_body:
            raise ADCError("Issue identity, state, or ADC pointer changed during publication")
        pointer = ADCPointer(comment_id, digest, len(readback), state)
        new_body = _replace_pointer(old_body, pointer)
        updated = _check_issue(github.update_issue(issue_number, new_body), github.repo, issue_number)
        if updated.get("body") != new_body or updated.get("state") != "open":
            raise ADCError("updated Issue did not preserve the verified ADC pointer")
        final = _check_issue(github.issue(issue_number), github.repo, issue_number)
        if final.get("body") != new_body or parse_pointer(final["body"]) != pointer:
            raise ADCError("ADC pointer readback did not match the published comment")
        return pointer
    except GitHubError as exc:
        raise ADCError(str(exc)) from exc


def verify_adc(github: GitHub, issue_number: int) -> VerifiedADC:
    try:
        issue = _check_issue(github.issue(issue_number), github.repo, issue_number)
        pointer = parse_pointer(issue.get("body") or "")
        if pointer is None:
            raise ADCError("Issue has no Agent Development Contract pointer")
        comment = _check_comment(
            github.issue_comment(issue_number, pointer.comment_id), github.repo, issue_number, pointer.comment_id
        )
    except GitHubError as exc:
        raise ADCError(str(exc)) from exc
    if not isinstance(comment.get("body"), str):
        raise ADCError("named ADC comment has no text body")
    content = comment["body"].encode("utf-8", errors="strict")
    digest = hashlib.sha256(content).hexdigest()
    if digest != pointer.sha256 or len(content) != pointer.byte_length:
        raise ADCError("ADC pointer SHA-256 or byte length does not match the named comment")
    contract = parse_adc(content, github.repo, issue_number)
    return VerifiedADC(contract, pointer)


def restore_adc(github: GitHub, issue_number: int, destination: Path) -> VerifiedADC:
    verified = verify_adc(github, issue_number)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temp_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(verified.contract.content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise
    return verified
