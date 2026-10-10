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
    r"Comment ID: ([1-9][0-9]{0,19})\n"
    r"SHA-256: ([0-9a-f]{64})\n"
    r"Bytes: ([0-9]{1,10})\n"
    r"State: (draft|approved)\n?$"
)
PUBLISH_TXN_PREFIX = "<!-- PASES_ADC_PUBLISH_V1\n"
PUBLISH_TXN_SENTINEL = "<!-- PASES_ADC_PUBLISH_V1"
PUBLISH_TXN_FIELDS = re.compile(
    r"^<!-- PASES_ADC_PUBLISH_V1\n"
    r"Operation ID: ([0-9a-f]{64})\n"
    r"Predecessor Comment ID: (none|[1-9][0-9]{0,19})\n"
    r"ADC SHA-256: ([0-9a-f]{64})\n"
    r"Bytes: ([0-9]{1,10})\n"
    r"State: (draft|approved)\n"
    r"-->$"
)
POINTER_RECORD_SENTINEL = "<!-- PASES_ADC_POINTER_V1"
POINTER_RECORD_FIELDS = re.compile(
    r"^<!-- PASES_ADC_POINTER_V1\n"
    r"Operation ID: ([0-9a-f]{64})\n"
    r"Predecessor Comment ID: (none|[1-9][0-9]{0,19})\n"
    r"ADC Comment ID: ([1-9][0-9]{0,19})\n"
    r"SHA-256: ([0-9a-f]{64})\n"
    r"Bytes: ([0-9]{1,10})\n"
    r"State: (draft|approved)\n"
    r"-->$"
)
TRUSTED_PUBLISHER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
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


def _claims_trusted_publisher_association(comment: Any) -> bool:
    return (isinstance(comment, dict)
            and comment.get("author_association") in TRUSTED_PUBLISHER_ASSOCIATIONS)


def _is_trusted_publisher_comment(comment: Any) -> bool:
    """Trust GitHub-authenticated repository owners, members, and collaborators as publishers."""
    return (_claims_trusted_publisher_association(comment)
            and isinstance(comment.get("user"), dict)
            and type(comment["user"].get("id")) is int
            and comment["user"]["id"] > 0)


def _require_trusted_publisher_comment(
    comment: Any, repository: str, issue_number: int, comment_id: int,
) -> dict[str, Any]:
    if not _is_trusted_publisher_comment(comment):
        raise ADCError("ADC publication comment was not issued by a trusted repository publisher")
    return _check_comment(comment, repository, issue_number, comment_id)


def _latest_pointer_record(
    github: GitHub,
    issue_number: int,
    *,
    issue_body: str,
) -> tuple[ADCPointer | None, str | None, int | None]:
    """Read the append-only pointer journal; fall back to the legacy Issue-body pointer."""
    try:
        records: list[tuple[int, str, str, ADCPointer]] = []
        operation_records: dict[str, tuple[str, str, ADCPointer, int]] = {}
        for listed in github.issue_comments(issue_number):
            body = listed.get("body") if isinstance(listed, dict) else None
            if not isinstance(body, str) or not body.startswith(POINTER_RECORD_SENTINEL):
                continue
            # Ignore comments from ordinary issue participants. GitHub supplies author and
            # author_association independently of the comment body, so body text cannot claim trust.
            if not _claims_trusted_publisher_association(listed):
                continue
            if not _is_trusted_publisher_comment(listed):
                raise ADCError("trusted ADC pointer record has malformed publisher identity")
            comment_id = listed.get("id")
            if type(comment_id) is not int or comment_id < 1:
                raise ADCError("trusted ADC pointer record has an invalid Comment ID")
            _check_comment(listed, github.repo, issue_number, comment_id)
            match = _parse_pointer_record_body(body, github.repo, issue_number)
            if match is None:
                raise ADCError("malformed trusted ADC pointer record; refusing to select a pointer")
            (operation_id, predecessor_id, adc_comment_id_text, digest, byte_length_text, state) = match.groups()
            adc_comment_id = int(adc_comment_id_text)
            byte_length = int(byte_length_text)
            computed_id = _publication_operation_id(
                github.repo, issue_number, predecessor_id, digest, byte_length, state,
            )
            if operation_id != computed_id or adc_comment_id >= comment_id:
                raise ADCError("trusted ADC pointer record identity or comment order is invalid")
            pointer = ADCPointer(adc_comment_id, digest, byte_length, state)
            prior = operation_records.get(operation_id)
            if prior is not None and prior[:3] != (body, predecessor_id, pointer):
                raise ADCError("trusted ADC pointer records conflict for one publication operation")
            if prior is None or comment_id > prior[3]:
                operation_records[operation_id] = (body, predecessor_id, pointer, comment_id)
        for operation_id, (_body, predecessor_id, pointer, record_id) in operation_records.items():
            records.append((record_id, operation_id, predecessor_id, pointer))
        if records:
            ordered = sorted(records)
            for previous, current in zip(ordered, ordered[1:]):
                if current[2] != str(previous[3].comment_id):
                    raise ADCError(
                        "trusted ADC pointer journal contains concurrent publications from the same predecessor"
                    )
            record_id, operation_id, _predecessor_id, pointer = ordered[-1]
            return pointer, operation_id, record_id
    except GitHubError as exc:
        raise ADCError(str(exc)) from exc
    return parse_pointer(issue_body), None, None


def _pointer_record_body(
    operation_id: str,
    predecessor_id: str,
    pointer: ADCPointer,
    repository: str,
    issue_number: int,
) -> str:
    fields = (
        "<!-- PASES_ADC_POINTER_V1\n"
        f"Operation ID: {operation_id}\n"
        f"Predecessor Comment ID: {predecessor_id}\n"
        f"ADC Comment ID: {pointer.comment_id}\n"
        f"SHA-256: {pointer.sha256}\n"
        f"Bytes: {pointer.byte_length}\n"
        f"State: {pointer.state}\n"
        "-->"
    )
    comment_url = (
        f"https://github.com/{_repo_name(repository)}/issues/{issue_number}"
        f"#issuecomment-{pointer.comment_id}"
    )
    summary = (
        f"ADC pointer: [comment #{pointer.comment_id}]({comment_url}) · "
        f"SHA-256 `{pointer.sha256}` · {pointer.byte_length} bytes · state `{pointer.state}`."
    )
    return fields + "\n\n" + summary


def _parse_pointer_record_body(body: str, repository: str, issue_number: int) -> re.Match[str] | None:
    parts = body.split("\n\n", 1)
    if len(parts) != 2:
        return None
    match = POINTER_RECORD_FIELDS.fullmatch(parts[0])
    if match is None:
        return None
    _operation_id, _predecessor_id, adc_comment_id_text, digest, byte_length_text, state = match.groups()
    pointer = ADCPointer(int(adc_comment_id_text), digest, int(byte_length_text), state)
    expected = _pointer_record_body(
        _operation_id, _predecessor_id, pointer, repository, issue_number,
    ).split("\n\n", 1)[1]
    return match if parts[1] == expected else None


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
            if not listed["body"].startswith(PUBLISH_TXN_SENTINEL):
                continue
            # Untrusted issue participants cannot reserve operation IDs or block publication.
            if not _claims_trusted_publisher_association(listed):
                continue
            if not _is_trusted_publisher_comment(listed):
                raise ADCError("trusted ADC publication marker has malformed publisher identity")
            listed_id = listed.get("id")
            if type(listed_id) is not int or listed_id < 1:
                raise ADCError("trusted ADC publication marker has an invalid Comment ID")
            _check_comment(listed, github.repo, issue_number, listed_id)
            match = PUBLISH_TXN_FIELDS.fullmatch(listed["body"])
            if match is None:
                raise ADCError("malformed trusted ADC publication marker; refusing to publish")
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
            _require_trusted_publisher_comment(created, github.repo, issue_number, marker_id)
        readback = _check_comment(
            github.issue_comment(issue_number, marker_id), github.repo, issue_number, marker_id,
        )
        _require_trusted_publisher_comment(readback, github.repo, issue_number, marker_id)
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
        if _claims_trusted_publisher_association(listed) and not _is_trusted_publisher_comment(listed):
            raise ADCError("trusted ADC comment has malformed publisher identity")
        if not _is_trusted_publisher_comment(listed):
            continue
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
    """Publish exact ADC bytes and commit an append-only, trusted pointer record."""
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
    existing_pointer, _existing_operation_id, _existing_record_id = _latest_pointer_record(
        github, issue_number, issue_body=old_body,
    )
    current_verified: VerifiedADC | None = None
    if existing_pointer is not None:
        current_verified = verify_adc(github, issue_number)
        if current_verified.pointer != existing_pointer:
            raise ADCError("current ADC pointer changed while it was being verified")
        if (existing_pointer.sha256 == contract.sha256
                and existing_pointer.byte_length == contract.byte_length
                and existing_pointer.state == state):
            # This also makes a retry after the pointer record was created idempotent.
            if current_verified.contract.content != contract.content:
                raise ADCError("current ADC comment does not match the requested exact bytes")
            return current_verified.pointer
        if not supersede:
            raise ADCError("Issue already has an ADC; use explicit supersession to publish another immutable comment")
    try:
        body_text = data.decode("utf-8", errors="strict")
        operation_id, transaction_marker_id = _publication_transaction(
            github, issue_number, contract, state=state, current_pointer=existing_pointer,
        )
        after_marker = _check_issue(github.issue(issue_number), github.repo, issue_number)
        if after_marker.get("state") != "open" or after_marker.get("body", "") != old_body:
            raise ADCError("Issue identity, state, or ADC pointer changed during publication")
        marker_pointer, _marker_operation_id, _marker_record_id = _latest_pointer_record(
            github, issue_number, issue_body=after_marker.get("body") or "",
        )
        if marker_pointer != existing_pointer:
            raise ADCError("ADC pointer journal advanced during publication")
        comment_id = _find_reusable_comment(
            github, issue_number, contract, current_pointer=existing_pointer,
            transaction_marker_id=transaction_marker_id,
        )
        if comment_id is None:
            created = github.create_issue_comment(issue_number, body_text)
            comment_id = created.get("id") if isinstance(created, dict) else None
        if type(comment_id) is not int or comment_id < 1:
            raise ADCError("created ADC comment is missing a valid Comment ID")
        named = _require_trusted_publisher_comment(
            github.issue_comment(issue_number, comment_id), github.repo, issue_number, comment_id,
        )
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
        predecessor_id = "none" if existing_pointer is None else str(existing_pointer.comment_id)
        record_body = _pointer_record_body(
            operation_id, predecessor_id, pointer, github.repo, issue_number,
        )
        # Pointer publication is append-only. GitHub does not support conditional PATCH on
        # Issues, so changing the body after a GET would risk replacing another writer's edit.
        # The trusted comment journal is the source of truth; its comment IDs define ordering.
        latest_before_commit, _latest_operation_id, _latest_record_id = _latest_pointer_record(
            github, issue_number, issue_body=after_comment.get("body") or "",
        )
        if latest_before_commit != existing_pointer:
            raise ADCError("ADC pointer journal advanced during publication; refusing a stale commit")
        committed: list[tuple[int, str]] = []
        for listed in github.issue_comments(issue_number):
            listed_body = listed.get("body") if isinstance(listed, dict) else None
            if not isinstance(listed_body, str) or not listed_body.startswith(POINTER_RECORD_SENTINEL):
                continue
            if not _claims_trusted_publisher_association(listed):
                continue
            if not _is_trusted_publisher_comment(listed):
                raise ADCError("trusted ADC pointer record has malformed publisher identity")
            listed_id = listed.get("id")
            if type(listed_id) is not int or listed_id < 1:
                raise ADCError("trusted ADC pointer record has an invalid Comment ID")
            _check_comment(listed, github.repo, issue_number, listed_id)
            match = _parse_pointer_record_body(listed_body, github.repo, issue_number)
            if match is None:
                raise ADCError("malformed trusted ADC pointer record; refusing to publish")
            if match.group(1) == operation_id:
                committed.append((listed_id, listed_body))
        if len(committed) > 1 and len({body for _comment_id, body in committed}) != 1:
            raise ADCError("conflicting trusted pointer records exist for this publication operation")
        if committed:
            record_id, existing_record_body = max(committed)
            if existing_record_body != record_body:
                raise ADCError("trusted ADC pointer record does not match the requested publication")
        else:
            created_record = github.create_issue_comment(issue_number, record_body)
            record_id = created_record.get("id") if isinstance(created_record, dict) else None
            if type(record_id) is not int or record_id <= comment_id:
                raise ADCError("created ADC pointer record is missing a valid later Comment ID")
            _require_trusted_publisher_comment(
                created_record, github.repo, issue_number, record_id,
            )
        named_record = _require_trusted_publisher_comment(
            github.issue_comment(issue_number, record_id), github.repo, issue_number, record_id,
        )
        if named_record.get("body") != record_body:
            raise ADCError("ADC pointer record readback does not match the requested publication")
        final = _check_issue(github.issue(issue_number), github.repo, issue_number)
        if final.get("state") != "open":
            raise ADCError("Issue closed during ADC publication")
        final_pointer, final_operation_id, final_record_id = _latest_pointer_record(
            github, issue_number, issue_body=final.get("body") or "",
        )
        if (final_pointer != pointer or final_operation_id != operation_id
                or final_record_id is None or final_record_id < record_id):
            raise ADCError("ADC pointer journal readback changed during publication")
        return pointer
    except GitHubError as exc:
        raise ADCError(str(exc)) from exc


def verify_adc(github: GitHub, issue_number: int) -> VerifiedADC:
    try:
        issue = _check_issue(github.issue(issue_number), github.repo, issue_number)
        pointer, operation_id, _record_id = _latest_pointer_record(
            github, issue_number, issue_body=issue.get("body") or "",
        )
        if pointer is None:
            raise ADCError("Issue has no Agent Development Contract pointer")
        named = github.issue_comment(issue_number, pointer.comment_id)
        comment = (
            _require_trusted_publisher_comment(named, github.repo, issue_number, pointer.comment_id)
            if operation_id is not None
            else _check_comment(named, github.repo, issue_number, pointer.comment_id)
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
