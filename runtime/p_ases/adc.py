"""Agent Development Contract validation, immutable publication, and recovery."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlsplit

from .github import GitHub, GitHubError


class ADCError(ValueError):
    pass


SHA256 = re.compile(r"^[0-9a-f]{64}$")
ADC_DIRECT_READ_MAX_WORKERS = 16
ISSUE_NUMBER = re.compile(r"^(?:#)?([1-9][0-9]*)$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REQ_ID = re.compile(r"(?m)^ {0,3}[-*+]\s+(REQ-(?:[0-9]+|[A-Z][A-Z0-9]*-[0-9]{3})):\s*\S.*$")
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
REQUIRED_SECTIONS = {
    "issue", "scope", "change_kind", "requirements", "architecture_decisions",
    "artifact_impact", "exact_changes", "invariants", "non_goals",
    "verification_obligations", "reviewer_checklist", "completion_gates",
}
PREDECESSOR_ADC_FIELDS = re.compile(
    r"^Predecessor ADC:\s*Issue\s+#?([1-9][0-9]*)\s+comment\s+#?([1-9][0-9]*),\s*"
    r"SHA-256\s+`?([0-9a-f]{64})`?(?:[ \t]+\(([1-9][0-9]{0,9}) bytes\))?$"
)


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


@dataclass
class _ADCForwardGenerationScope:
    github: GitHub
    issue_number: int
    repository: str
    prior_comment_id: int
    prior_sha256: str
    current_comment_id: int
    current_sha256: str
    verified: tuple[VerifiedADC, ...] | None = None


@dataclass
class _ADCForwardGenerationSession:
    github: GitHub
    issue_number: int
    repository: str
    # Each tuple was read back against the live Issue and pointer journal. The
    # boolean is true only when its final generation was also proven current.
    ranges: list[tuple[tuple[VerifiedADC, ...], bool]]


_ADC_FORWARD_GENERATION_SCOPE: ContextVar[_ADCForwardGenerationScope | None] = ContextVar(
    "pases_adc_forward_generation_scope", default=None,
)
_ADC_FORWARD_GENERATION_SESSION: ContextVar[_ADCForwardGenerationSession | None] = ContextVar(
    "pases_adc_forward_generation_session", default=None,
)


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


def validate_approval_ready_adc(
    data: bytes,
    repository: str,
    issue_number: int,
    *,
    current_pointer: ADCPointer | None = None,
    check_current_pointer: bool = False,
) -> ADC:
    """Validate a new approved publication without changing historical reads.

    ``parse_adc`` remains structural and is intentionally used by verification of
    old immutable generations. This stricter check applies only when preparing a
    new approved publication or its exact owner-authorization plan.
    """
    contract = parse_adc(data, repository, issue_number)
    if check_current_pointer and current_pointer is not None and not isinstance(current_pointer, ADCPointer):
        raise ADCError("current ADC predecessor pointer is malformed")

    text = data.decode("utf-8", errors="strict")
    lines = text.splitlines()
    first_nonempty = next((line.strip() for line in lines if line.strip()), "")
    if not first_nonempty.startswith("# Agent Development Contract"):
        raise ADCError("approved ADC must have a final Agent Development Contract title")
    if re.search(r"(?i)\b(?:draft|proposal|unapproved)\b", first_nonempty):
        raise ADCError("approved ADC title still marks the contract as a draft or proposal")

    preamble: list[str] = []
    for line in lines:
        if re.match(r"^ {0,3}##(?:[ \t]+|$)", line):
            break
        preamble.append(line)
    for line in preamble:
        value = line.strip()
        if re.match(r"(?i)^draft\b", value):
            raise ADCError("approved ADC header still contains a draft-only status")
        status = re.match(r"(?i)^(?:status|state)\s*:\s*(.+)$", value)
        if status and re.match(r"(?i)^(?:draft|unapproved|pending|not approved)\b", status.group(1).strip()):
            raise ADCError("approved ADC header status is not final")

    predecessor_lines = [line.strip() for line in preamble
                         if line.strip().startswith("Predecessor ADC:")]
    if len(predecessor_lines) > 1:
        raise ADCError("approved ADC header has multiple predecessor declarations")
    declared: tuple[int, int, str, int | None] | None = None
    if predecessor_lines:
        match = PREDECESSOR_ADC_FIELDS.fullmatch(predecessor_lines[0])
        if match is None:
            raise ADCError("approved ADC predecessor declaration is malformed")
        declared = (int(match.group(1)), int(match.group(2)), match.group(3),
                    int(match.group(4)) if match.group(4) is not None else None)

    if declared is not None and declared[3] is not None and not check_current_pointer:
        raise ADCError("predecessor byte length requires the direct current pointer")
    if check_current_pointer and declared is not None:
        # Current contracts may name their immediate predecessor, but no
        # historical ADC declaration or Issue-specific policy is required.
        if current_pointer is None:
            raise ADCError("approved ADC declares a predecessor but the current pointer is absent")
        if (declared[3] is not None
                and (type(current_pointer.byte_length) is not int or current_pointer.byte_length < 1)):
            raise ADCError("current ADC predecessor pointer byte length is invalid")
        if (declared[0] != issue_number or declared[1] != current_pointer.comment_id
                or declared[2] != current_pointer.sha256
                or declared[3] is not None and declared[3] != current_pointer.byte_length):
            raise ADCError("approved ADC predecessor does not match the current approved pointer")
    return contract


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


def _repository_owner_id(github: GitHub) -> int:
    try:
        metadata = github.repository_metadata()
    except GitHubError as exc:
        raise ADCError(f"could not verify repository owner for ADC carrier: {exc}") from exc
    owner = metadata.get("owner") if isinstance(metadata, dict) else None
    expected_owner = github.repo.split("/", 1)[0]
    if (not isinstance(metadata, dict)
            or not isinstance(metadata.get("full_name"), str)
            or metadata["full_name"].casefold() != github.repo.casefold()
            or not isinstance(owner, dict) or type(owner.get("id")) is not int
            or owner["id"] < 1 or owner.get("type") != "User"
            or not isinstance(owner.get("login"), str)
            or owner["login"].casefold() != expected_owner.casefold()):
        raise ADCError("repository owner identity is incomplete or differs from the selected repository")
    return owner["id"]


def _comment_carrier_role(
    github: GitHub, comment: Any, owner_id: int,
    permission_cache: dict[str, tuple[int, str | None]] | None = None,
) -> str | None:
    """Return owner/publisher only for a currently authorized human commenter.

    Known Bot/Organization accounts are nonparticipants until an explicit App
    policy exists. Missing or contradictory identities and uncertain permission
    lookups fail closed instead of treating author_association as authority.
    """
    author = comment.get("user") if isinstance(comment, dict) else None
    if (not isinstance(author, dict) or type(author.get("id")) is not int or author["id"] < 1
            or not isinstance(author.get("login"), str)
            or not re.fullmatch(r"[A-Za-z0-9-]+(?:\[bot\])?", author["login"])
            or not isinstance(author.get("type"), str)):
        raise ADCError("ADC carrier commenter identity is missing or malformed")
    if author["type"] != "User":
        if author["type"] in {"Bot", "Organization"}:
            return None
        raise ADCError("ADC carrier commenter type is unknown")
    if author["id"] == owner_id:
        return "owner"

    login_key = author["login"].casefold()
    cached = permission_cache.get(login_key) if permission_cache is not None else None
    if cached is not None:
        cached_id, cached_role = cached
        if cached_id != author["id"]:
            raise ADCError("cached ADC commenter identity changed during readback")
        return cached_role
    try:
        permission_row = github.collaborator_permission(author["login"])
    except GitHubError as exc:
        if exc.status_code == 404:
            if permission_cache is not None:
                permission_cache[login_key] = (author["id"], None)
            return None
        raise ADCError(f"could not verify ADC carrier commenter permission: {exc}") from exc
    permission_user = permission_row.get("user") if isinstance(permission_row, dict) else None
    permission = permission_row.get("permission") if isinstance(permission_row, dict) else None
    if (permission not in {"none", "read", "triage", "write", "maintain", "admin"}
            or not isinstance(permission_user, dict)
            or type(permission_user.get("id")) is not int
            or permission_user.get("id") != author["id"]
            or not isinstance(permission_user.get("login"), str)
            or permission_user["login"].casefold() != login_key
            or permission_user.get("type") != "User"):
        raise ADCError("collaborator permission response is incomplete or mismatched for ADC carrier")
    role = "publisher" if permission in {"write", "maintain", "admin"} else None
    if permission_cache is not None:
        permission_cache[login_key] = (author["id"], role)
    return role


def _require_carrier_role(role: str | None, state: str, label: str) -> None:
    if role is None:
        raise ADCError(f"{label} author lacks verified current repository publishing permission")
    if state == "approved" and role != "owner":
        raise ADCError(f"approved {label} requires the repository Owner author")


def _require_current_publisher(github: GitHub, state: str) -> None:
    owner_id = _repository_owner_id(github)
    try:
        user = github.authenticated_user()
    except GitHubError as exc:
        raise ADCError(f"could not verify authenticated ADC publisher: {exc}") from exc
    role = _comment_carrier_role(github, {"user": user}, owner_id)
    _require_carrier_role(role, state, "ADC publication")


def _latest_pointer_record(
    github: GitHub,
    issue_number: int,
    *,
    issue_body: str,
    comments: Sequence[dict[str, Any]] | None = None,
) -> tuple[ADCPointer | None, str | None, int | None]:
    """Read only the current ADC pointer; never validate superseded generations."""
    if comments is not None:
        return _latest_current_adc_pointer(
            github, issue_number, {"body": issue_body}, pages=(comments,),
        )
    issue = _check_issue(github.issue(issue_number), github.repo, issue_number)
    if issue.get("body") != issue_body:
        raise ADCError("Issue body changed during current ADC pointer selection")
    return _latest_current_adc_pointer(github, issue_number, issue)


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
        owner_id = _repository_owner_id(github)
        permission_cache: dict[str, tuple[int, str | None]] = {}
        listed_comments = github.issue_comments(issue_number)
        same_operation: list[dict[str, Any]] = []
        for listed in listed_comments:
            if not isinstance(listed, dict) or not isinstance(listed.get("body"), str):
                continue
            if not listed["body"].startswith(PUBLISH_TXN_SENTINEL):
                continue
            author_role = _comment_carrier_role(github, listed, owner_id, permission_cache)
            if author_role is None:
                continue
            listed_id = listed.get("id")
            if type(listed_id) is not int or listed_id < 1:
                raise ADCError("ADC publication marker has an invalid Comment ID")
            _check_comment(listed, github.repo, issue_number, listed_id)
            match = PUBLISH_TXN_FIELDS.fullmatch(listed["body"])
            if match is None:
                raise ADCError("malformed ADC publication marker; refusing to publish")
            marker_operation_id, marker_predecessor, marker_sha, marker_bytes, marker_state = match.groups()
            _require_carrier_role(author_role, marker_state, "ADC publication marker")
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
            _require_current_publisher(github, state)
            created = github.create_issue_comment(issue_number, marker_body)
            marker_id = created.get("id") if isinstance(created, dict) else None
            if type(marker_id) is not int or marker_id < 1:
                raise ADCError("ADC publication marker is missing a valid Comment ID")
        readback = _check_comment(
            github.issue_comment(issue_number, marker_id), github.repo, issue_number, marker_id,
        )
        readback_role = _comment_carrier_role(github, readback, owner_id, permission_cache)
        _require_carrier_role(readback_role, state, "ADC publication marker")
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
    state: str,
) -> int | None:
    """Find only a matching ADC created after this exact operation's marker."""
    matches: list[int] = []
    owner_id = _repository_owner_id(github)
    permission_cache: dict[str, tuple[int, str | None]] = {}
    for listed in github.issue_comments(issue_number):
        if not isinstance(listed, dict) or not isinstance(listed.get("body"), str):
            continue
        listed_bytes = listed["body"].encode("utf-8", errors="strict")
        if listed_bytes != contract.content:
            continue
        comment_id = listed.get("id")
        # Older exact matches are complete historical publications, not candidates
        # for this operation's recovery and therefore not current control carriers.
        if type(comment_id) is int and (comment_id <= transaction_marker_id
                or (current_pointer is not None and comment_id == current_pointer.comment_id)):
            continue
        author_role = _comment_carrier_role(github, listed, owner_id, permission_cache)
        if author_role is None:
            continue
        if type(comment_id) is not int or comment_id < 1:
            raise ADCError("matching unpointed ADC comment has an invalid Comment ID")
        _check_comment(listed, github.repo, issue_number, comment_id)
        _require_carrier_role(author_role, state, "ADC comment")
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
    expected_current: ADCPointer | None = None,
) -> ADCPointer:
    """Publish exact ADC bytes and commit an append-only pointer record."""
    if state not in {"draft", "approved"}:
        raise ADCError("ADC state must be draft or approved")
    if type(supersede) is not bool or type(explicitly_approved) is not bool:
        raise ADCError("ADC approval and supersession flags must be explicit booleans")
    if expected_current is not None and not isinstance(expected_current, ADCPointer):
        raise ADCError("expected current ADC pointer is malformed")
    if state == "approved" and explicitly_approved is not True:
        raise ADCError("publishing an approved ADC requires explicit user approval")
    # Parse before reading the live pointer; strict approval validation runs
    # below once the directly observed predecessor pointer is available.
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
    if state == "approved":
        # Validate a new publication against the currently verified generation
        # before creating its durable transaction marker or any other comment.
        validate_approval_ready_adc(
            data, github.repo, issue_number,
            current_pointer=existing_pointer, check_current_pointer=True,
        )
    if expected_current is not None and existing_pointer != expected_current:
        raise ADCError("current ADC pointer differs from the exact expected predecessor")
    _require_current_publisher(github, state)
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
            transaction_marker_id=transaction_marker_id, state=state,
        )
        if comment_id is None:
            created = github.create_issue_comment(issue_number, body_text)
            comment_id = created.get("id") if isinstance(created, dict) else None
        if type(comment_id) is not int or comment_id < 1:
            raise ADCError("created ADC comment is missing a valid Comment ID")
        named = _check_comment(
            github.issue_comment(issue_number, comment_id), github.repo, issue_number, comment_id,
        )
        owner_id = _repository_owner_id(github)
        permission_cache: dict[str, tuple[int, str | None]] = {}
        named_role = _comment_carrier_role(github, named, owner_id, permission_cache)
        _require_carrier_role(named_role, state, "ADC comment")
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
        # The comment journal is the source of truth; its comment IDs define ordering.
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
            listed_id = listed.get("id")
            pointer_role = _comment_carrier_role(
                github, listed, owner_id, permission_cache,
            )
            if pointer_role is None:
                continue
            if type(listed_id) is not int or listed_id < 1:
                raise ADCError("ADC pointer record has an invalid Comment ID")
            _check_comment(listed, github.repo, issue_number, listed_id)
            match = _parse_pointer_record_body(listed_body, github.repo, issue_number)
            if match is None:
                raise ADCError("malformed ADC pointer record; refusing to publish")
            _require_carrier_role(pointer_role, match.group(6), "ADC pointer record")
            if match.group(1) == operation_id:
                committed.append((listed_id, listed_body))
        if len(committed) > 1 and len({body for _comment_id, body in committed}) != 1:
            raise ADCError("conflicting pointer records exist for this publication operation")
        if committed:
            record_id, existing_record_body = max(committed)
            if existing_record_body != record_body:
                raise ADCError("ADC pointer record does not match the requested publication")
        else:
            created_record = github.create_issue_comment(issue_number, record_body)
            record_id = created_record.get("id") if isinstance(created_record, dict) else None
            if type(record_id) is not int or record_id <= comment_id:
                raise ADCError("created ADC pointer record is missing a valid later Comment ID")
        named_record = _check_comment(
            github.issue_comment(issue_number, record_id), github.repo, issue_number, record_id,
        )
        pointer_role = _comment_carrier_role(github, named_record, owner_id, permission_cache)
        _require_carrier_role(pointer_role, state, "ADC pointer record")
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


def _latest_current_adc_pointer(
    github: GitHub, issue_number: int, issue: dict[str, Any],
    *, pages: Sequence[Sequence[dict[str, Any]]] | None = None,
) -> tuple[ADCPointer | None, str | None, int | None]:
    """Select the newest pointer, without validating superseded ADC generations.

    Validate the selected marker's exact identity and at most one immediately
    preceding marker to detect competing writes from the same predecessor.
    This reader never dereferences an old ADC body or traverses the full chain.
    """
    if pages is None:
        count = issue.get("comments")
        recent_reader = getattr(github, "issue_comment_pages_newest", None)
        if callable(recent_reader) and type(count) is int and count >= 0:
            pages = recent_reader(issue_number, count)
        else:
            # Legacy transports and test doubles supply their own local snapshot.
            pages = (github.issue_comments(issue_number),)

    selected: list[tuple[int, str, str, ADCPointer]] = []
    owner_id: int | None = None
    permission_cache: dict[str, tuple[int, str | None]] = {}
    for page in pages:
        for row in reversed(page):
            body = row.get("body") if isinstance(row, dict) else None
            if not isinstance(body, str) or not body.startswith(POINTER_RECORD_SENTINEL):
                continue
            if owner_id is None:
                owner_id = _repository_owner_id(github)
            author_role = _comment_carrier_role(github, row, owner_id, permission_cache)
            if author_role is None:
                continue
            record_id = row.get("id")
            if type(record_id) is not int or record_id < 1:
                raise ADCError("current ADC pointer record has no valid comment ID")
            _check_comment(row, github.repo, issue_number, record_id)
            match = _parse_pointer_record_body(body, github.repo, issue_number)
            if match is None:
                raise ADCError("current ADC pointer marker is malformed")
            operation, predecessor, adc_id, digest, byte_length, state = match.groups()
            _require_carrier_role(author_role, state, "ADC pointer record")
            pointer = ADCPointer(int(adc_id), digest, int(byte_length), state)
            if (pointer.comment_id >= record_id or operation != _publication_operation_id(
                    github.repo, issue_number, predecessor, digest, pointer.byte_length, state)):
                raise ADCError("current ADC pointer marker identity or order is invalid")
            selected.append((record_id, operation, predecessor, pointer))
            if len(selected) == 2:
                break
        if len(selected) == 2:
            break
    if not selected:
        return parse_pointer(issue.get("body") or ""), None, None

    current = selected[0]
    if len(selected) == 2:
        previous = selected[1]
        if (current[2] == previous[2]
                and (current[1] != previous[1] or current[3] != previous[3])):
            raise ADCError("current ADC pointer contains competing publications from one predecessor")
        if current[2] != str(previous[3].comment_id):
            raise ADCError("current ADC pointer does not name the directly previous trusted generation")
        if current[3].comment_id <= previous[3].comment_id:
            raise ADCError("current ADC pointer generation is not strictly forward")
    else:
        legacy = parse_pointer(issue.get("body") or "")
        expected_predecessor = "none" if legacy is None else str(legacy.comment_id)
        if current[2] != expected_predecessor:
            raise ADCError("current ADC pointer does not continue the legacy pointer")
        if legacy is not None and current[3].comment_id <= legacy.comment_id:
            raise ADCError("current ADC pointer generation is not strictly forward")
    return current[3], current[1], current[0]


def verify_adc(github: GitHub, issue_number: int) -> VerifiedADC:
    try:
        issue = _check_issue(github.issue(issue_number), github.repo, issue_number)
        pointer, _operation_id, _record_id = _latest_current_adc_pointer(
            github, issue_number, issue,
        )
        if pointer is None:
            raise ADCError("Issue has no Agent Development Contract pointer")
        named = github.issue_comment(issue_number, pointer.comment_id)
        comment = _check_comment(named, github.repo, issue_number, pointer.comment_id)
        owner_id = _repository_owner_id(github)
        comment_role = _comment_carrier_role(github, comment, owner_id)
        _require_carrier_role(comment_role, pointer.state, "named ADC comment")
        issue_after = _check_issue(github.issue(issue_number), github.repo, issue_number)
        if (issue.get("body") != issue_after.get("body")
                or issue.get("state") != issue_after.get("state")
                or issue.get("comments") != issue_after.get("comments")):
            raise ADCError("Issue changed during current ADC readback")
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


def _verify_adc_comment_triplet(
    github: GitHub,
    issue_number: int,
    pointer: ADCPointer,
    direct_before: Any,
    listed: Any,
    direct_after: Any,
) -> VerifiedADC:
    """Validate one ADC carrier against direct/list/direct reads from one operation."""
    fingerprints: list[tuple[Any, ...]] = []
    for row in (direct_before, listed, direct_after):
        _check_comment(row, github.repo, issue_number, pointer.comment_id)
        body = row.get("body")
        created, updated = row.get("created_at"), row.get("updated_at")
        author = row.get("user")
        if (not isinstance(body, str) or not isinstance(created, str) or not isinstance(updated, str)
                or created != updated or not isinstance(author, dict)
                or type(author.get("id")) is not int or author["id"] < 1
                or not isinstance(author.get("login"), str) or not author["login"]
                or author.get("type") != "User"):
            raise ADCError("historical ADC comment was edited or has no stable human author")
        fingerprints.append((row.get("id"), body, created, updated,
                             author["id"], author["login"].casefold(), author["type"],
                             row.get("issue_url"), row.get("html_url"), row.get("url")))
    if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
        raise ADCError("historical ADC comment changed during direct/list/direct readback")
    comment_id = pointer.comment_id
    expected_urls = (f"https://api.github.com/repos/{github.repo}/issues/{issue_number}",
                     f"https://github.com/{github.repo}/issues/{issue_number}#issuecomment-{comment_id}",
                     f"https://api.github.com/repos/{github.repo}/issues/comments/{comment_id}")
    actual_urls = tuple(value.casefold() if isinstance(value, str) else None
                         for value in fingerprints[1][7:])
    if actual_urls != tuple(value.casefold() for value in expected_urls):
        raise ADCError("historical ADC comment repository URLs do not match its Issue")
    data = fingerprints[1][1].encode("utf-8", errors="strict")
    contract = parse_adc(data, github.repo, issue_number)
    digest = hashlib.sha256(data).hexdigest()
    if digest != pointer.sha256 or len(data) != pointer.byte_length:
        raise ADCError("historical ADC comment does not match its immutable pointer")
    if contract.sha256 != digest or contract.byte_length != pointer.byte_length:
        raise ADCError("historical ADC comment does not match its immutable pointer")
    return VerifiedADC(contract, pointer)


def _ordered_comment_snapshot(comments: Sequence[dict[str, Any]]) -> None:
    """Reject incomplete-looking, duplicated, or reordered paginated snapshots."""
    ids = [row.get("id") if isinstance(row, dict) else None for row in comments]
    if (any(type(comment_id) is not int or comment_id < 1 for comment_id in ids)
            or ids != sorted(set(ids))):
        raise ADCError("complete Issue comment snapshot is duplicated or reordered")


def _pointer_snapshot(
    github: GitHub,
    issue_number: int,
    issue_body: str,
    comments: Sequence[dict[str, Any]],
) -> tuple[tuple[tuple[int, str, str, ADCPointer], ...], ADCPointer | None,
           str | None, int | None]:
    """Validate the full pointer chain from one complete comment snapshot."""
    _ordered_comment_snapshot(comments)
    try:
        latest, latest_operation, latest_record_id = _latest_pointer_record(
            github, issue_number, issue_body=issue_body, comments=comments,
        )
    except ADCError:
        raise

    rows: list[tuple[int, str, str, ADCPointer]] = []
    operation_ids: set[str] = set()
    for listed in comments:
        body = listed.get("body") if isinstance(listed, dict) else None
        if not isinstance(body, str) or not body.startswith(POINTER_RECORD_SENTINEL):
            continue
        record_id = listed.get("id")
        if type(record_id) is not int or record_id < 1:
            raise ADCError("ADC pointer record has an invalid Comment ID")
        _check_comment(listed, github.repo, issue_number, record_id)
        match = _parse_pointer_record_body(body, github.repo, issue_number)
        if match is None:
            raise ADCError("ADC pointer journal contains a malformed generation")
        operation_id, predecessor_id, adc_id_text, digest, byte_text, state = match.groups()
        pointer = ADCPointer(int(adc_id_text), digest, int(byte_text), state)
        if (operation_id in operation_ids
                or operation_id != _publication_operation_id(
                    github.repo, issue_number, predecessor_id, digest, pointer.byte_length, state,
                )):
            raise ADCError("ADC pointer journal duplicates or misidentifies a publication operation")
        operation_ids.add(operation_id)
        if pointer.comment_id >= record_id:
            raise ADCError("ADC generation pointer is not forward of its journal record")
        rows.append((record_id, body, predecessor_id, pointer))

    legacy = parse_pointer(issue_body)
    pointers: list[ADCPointer] = []
    if legacy is not None:
        pointers.append(legacy)
    previous_id = "none" if legacy is None else str(legacy.comment_id)
    for record_id, _body, predecessor_id, pointer in rows:
        if predecessor_id != previous_id:
            raise ADCError("ADC pointer journal contains a gap, rollback, or reordered predecessor")
        if pointers and pointer.comment_id <= pointers[-1].comment_id:
            raise ADCError("ADC generation journal is duplicated or not forward-only")
        pointers.append(pointer)
        previous_id = str(pointer.comment_id)
    if latest != (pointers[-1] if pointers else None):
        raise ADCError("current ADC pointer is not the terminal generation in its journal")
    if rows and latest_record_id != rows[-1][0]:
        raise ADCError("current ADC pointer journal record is not terminal")
    return tuple(rows), latest, latest_operation, latest_record_id


def _adc_snapshot_rows(
    github: GitHub,
    issue_number: int,
    comments: Sequence[dict[str, Any]],
    pointers: Sequence[ADCPointer],
) -> dict[int, dict[str, Any]]:
    wanted = {pointer.comment_id for pointer in pointers}
    found: dict[int, dict[str, Any]] = {}
    for row in comments:
        comment_id = row.get("id") if isinstance(row, dict) else None
        if comment_id not in wanted:
            continue
        _check_comment(row, github.repo, issue_number, comment_id)
        if comment_id in found:
            raise ADCError("ADC generation comment is duplicated in the complete Issue snapshot")
        found[comment_id] = row
    if set(found) != wanted:
        raise ADCError("ADC generation comment is missing from the complete Issue snapshot")
    return found


def verify_adc_generation(github: GitHub, issue_number: int, comment_id: int, sha256: str,
                         *, state: str) -> VerifiedADC:
    """Verify an exact historical ADC generation from the append-only pointer journal."""
    if type(comment_id) is not int or comment_id < 1 or not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
        raise ADCError("historical ADC identity is malformed")
    if state not in {"draft", "approved"}:
        raise ADCError("historical ADC state is unknown")
    try:
        issue = _check_issue(github.issue(issue_number), github.repo, issue_number)
        journal_comments = github.issue_comments(issue_number)
        # Validate the complete predecessor chain before selecting an older entry.
        _latest_pointer_record(
            github, issue_number, issue_body=issue.get("body") or "", comments=journal_comments,
        )
        generations: list[ADCPointer] = []
        legacy = parse_pointer(issue.get("body") or "")
        if legacy is not None:
            generations.append(legacy)
        for row in journal_comments:
            body = row.get("body") if isinstance(row, dict) else None
            if not isinstance(body, str) or not body.startswith(POINTER_RECORD_SENTINEL):
                continue
            record_id = row.get("id")
            if type(record_id) is not int or record_id < 1:
                raise ADCError("ADC pointer record has an invalid Comment ID")
            _check_comment(row, github.repo, issue_number, record_id)
            match = _parse_pointer_record_body(body, github.repo, issue_number)
            if match is None:
                raise ADCError("malformed ADC pointer record; refusing historical readback")
            groups = match.groups()
            generations.append(ADCPointer(int(groups[2]), groups[3], int(groups[4]), groups[5]))
        matching = [row for row in generations
                    if row.comment_id == comment_id and row.sha256 == sha256 and row.state == state]
        if len(matching) != 1:
            raise ADCError("historical ADC generation is missing, duplicated, or has the wrong state")
        direct = _check_comment(github.issue_comment(issue_number, comment_id),
                                github.repo, issue_number, comment_id)
        readback_comments = github.issue_comments(issue_number)
        listed = [row for row in readback_comments
                  if isinstance(row, dict) and row.get("id") == comment_id]
        after = _check_comment(github.issue_comment(issue_number, comment_id),
                               github.repo, issue_number, comment_id)
    except GitHubError as exc:
        raise ADCError(str(exc)) from exc
    if len(listed) != 1:
        raise ADCError("historical ADC comment is missing or duplicated")
    return _verify_adc_comment_triplet(github, issue_number, matching[0], direct, listed[0], after)


def _verify_adc_forward_generations_uncached(
    github: GitHub, issue_number: int, *, prior_comment_id: int, prior_sha256: str,
    current_comment_id: int, current_sha256: str, allow_historical_target: bool = False,
) -> tuple[VerifiedADC, ...]:
    """Verify an approved range in the current ADC chain.

    New state must end at the current pointer. Immutable history may validate an
    earlier edge of that same current chain by explicitly opting into a
    historical target.
    """
    if (type(prior_comment_id) is not int or prior_comment_id < 1
            or type(current_comment_id) is not int or current_comment_id <= prior_comment_id
            or not isinstance(prior_sha256, str) or not SHA256.fullmatch(prior_sha256)
            or not isinstance(current_sha256, str) or not SHA256.fullmatch(current_sha256)
            or type(allow_historical_target) is not bool):
        raise ADCError("ADC successor range is malformed, stale or backward")
    try:
        issue_before = _check_issue(github.issue(issue_number), github.repo, issue_number)
        initial_comments = github.issue_comments(issue_number)
        initial_records, current_pointer, current_operation, current_record_id = _pointer_snapshot(
            github, issue_number, issue_before.get("body") or "", initial_comments,
        )
        if current_pointer is None or current_pointer.state != "approved":
            raise ADCError("current ADC pointer is missing or not approved")
        if (not allow_historical_target
                and (current_pointer.comment_id != current_comment_id
                     or current_pointer.sha256 != current_sha256)):
            raise ADCError("PRBinding does not match the current approved ADC pointer")

        legacy = parse_pointer(issue_before.get("body") or "")
        pointers = ([legacy] if legacy is not None else []) + [row[3] for row in initial_records]
        pointer_ids = [row.comment_id for row in pointers]
        prior_matches = [index for index, row in enumerate(pointers)
                         if row.comment_id == prior_comment_id and row.sha256 == prior_sha256]
        target_matches = [index for index, row in enumerate(pointers)
                          if row.comment_id == current_comment_id and row.sha256 == current_sha256]
        if (len(pointer_ids) != len(set(pointer_ids))
                or len(prior_matches) != 1 or len(target_matches) != 1
                or prior_matches[0] >= target_matches[0]):
            raise ADCError("ADC successor journal has a gap, rollback, duplicate, or unknown generation")
        selected = pointers[prior_matches[0]:target_matches[0] + 1]
        if any(pointer.state != "approved" for pointer in selected):
            raise ADCError("ADC successor range contains a non-approved generation")

        targets = list(selected)
        if current_pointer not in targets:
            targets.append(current_pointer)
        initial_adc_rows = _adc_snapshot_rows(github, issue_number, initial_comments, targets)
        def direct_read_batch(label: str) -> tuple[dict[int, dict[str, Any] | None], str | None]:
            rows: dict[int, dict[str, Any] | None] = {}
            failures: list[str] = []

            def read(pointer: ADCPointer) -> dict[str, Any]:
                return _check_comment(
                    github.issue_comment(issue_number, pointer.comment_id), github.repo,
                    issue_number, pointer.comment_id,
                )

            if not targets:
                return rows, None
            with ThreadPoolExecutor(
                    max_workers=min(ADC_DIRECT_READ_MAX_WORKERS, len(targets)),
                    thread_name_prefix="pases-adc-read") as executor:
                futures = [(pointer, executor.submit(read, pointer)) for pointer in targets]
                for pointer, future in futures:
                    try:
                        rows[pointer.comment_id] = future.result()
                    except Exception as exc:
                        rows[pointer.comment_id] = None
                        if not failures:
                            if isinstance(exc, (ADCError, GitHubError)):
                                failures.append(str(exc))
                            else:
                                failures.append(f"unexpected {type(exc).__name__}")
            if failures:
                return rows, f"{label}: {failures[0]}"
            return rows, None

        direct_before, direct_before_error = direct_read_batch("direct-before read failed")

        issue_after_snapshot = _check_issue(github.issue(issue_number), github.repo, issue_number)
        final_comments = github.issue_comments(issue_number)
        final_records, final_pointer, final_operation, final_record_id = _pointer_snapshot(
            github, issue_number, issue_after_snapshot.get("body") or "", final_comments,
        )
        if (issue_after_snapshot.get("body") != issue_before.get("body")
                or issue_after_snapshot.get("number") != issue_before.get("number")
                or issue_after_snapshot.get("repository_url") != issue_before.get("repository_url")
                or issue_after_snapshot.get("pull_request") != issue_before.get("pull_request")
                or issue_after_snapshot.get("state") != issue_before.get("state")):
            raise ADCError("Issue identity or body changed during ADC range validation")
        if (initial_records != final_records or final_pointer != current_pointer
                or final_operation != current_operation or final_record_id != current_record_id):
            raise ADCError("ADC pointer journal changed during the complete snapshot readback")
        final_adc_rows = _adc_snapshot_rows(github, issue_number, final_comments, targets)
        direct_after, direct_after_error = direct_read_batch("direct-after read failed")
        if direct_before_error is not None:
            raise ADCError(f"ADC generation direct read failed during the snapshot window: {direct_before_error}")
        if direct_after_error is not None:
            raise ADCError(f"ADC generation final direct read failed: {direct_after_error}")
    except GitHubError as exc:
        raise ADCError(str(exc)) from exc

    def fingerprint(row: dict[str, Any], comment_id: int) -> tuple[Any, ...]:
        _check_comment(row, github.repo, issue_number, comment_id)
        author = row.get("user")
        if not isinstance(author, dict):
            raise ADCError("ADC generation comment has no stable human author")
        return (
            row.get("id"), row.get("body"), row.get("created_at"), row.get("updated_at"),
            author.get("id"), author.get("login"), author.get("type"),
            row.get("issue_url"), row.get("html_url"), row.get("url"),
        )

    verified_by_id: dict[int, VerifiedADC] = {}
    for pointer in targets:
        comment_id = pointer.comment_id
        before = direct_before.get(comment_id)
        after = direct_after.get(comment_id)
        if before is None or after is None:
            raise ADCError("ADC generation direct read is missing")
        if (fingerprint(initial_adc_rows[comment_id], comment_id)
                != fingerprint(final_adc_rows[comment_id], comment_id)):
            raise ADCError("ADC generation list entry changed between complete snapshots")
        verified_by_id[comment_id] = _verify_adc_comment_triplet(
            github, issue_number, pointer, before,
            initial_adc_rows[comment_id], after,
        )
    if verified_by_id[current_pointer.comment_id].pointer != current_pointer:
        raise ADCError("current ADC body differs from its approved pointer")
    return tuple(verified_by_id[pointer.comment_id] for pointer in selected)


@contextmanager
def adc_forward_generation_scope(
    github: Any,
    issue_number: int,
    *,
    prior_comment_id: int,
    prior_sha256: str,
    current_comment_id: int,
    current_sha256: str,
) -> Iterator[None]:
    """Share one validated ADC range across a single immutable history read."""
    if not isinstance(github, GitHub):
        yield
        return
    if (type(issue_number) is not int or issue_number < 1
            or type(prior_comment_id) is not int or prior_comment_id < 1
            or type(current_comment_id) is not int or current_comment_id <= prior_comment_id
            or not isinstance(prior_sha256, str) or not SHA256.fullmatch(prior_sha256)
            or not isinstance(current_sha256, str) or not SHA256.fullmatch(current_sha256)):
        raise ADCError("ADC successor scope is malformed, stale or backward")
    scope = _ADCForwardGenerationScope(
        github, issue_number, github.repo.casefold(), prior_comment_id, prior_sha256,
        current_comment_id, current_sha256,
    )
    token: Token[_ADCForwardGenerationScope | None] = _ADC_FORWARD_GENERATION_SCOPE.set(scope)
    try:
        yield
    finally:
        _ADC_FORWARD_GENERATION_SCOPE.reset(token)


@contextmanager
def adc_forward_generation_session(github: Any, issue_number: int) -> Iterator[None]:
    """Reuse exact verified ADC ranges during one read-only lifecycle command."""
    if not isinstance(github, GitHub):
        yield
        return
    if type(issue_number) is not int or issue_number < 1:
        raise ADCError("ADC successor session Issue is malformed")
    repository = github.repo.casefold()
    existing = _ADC_FORWARD_GENERATION_SESSION.get()
    if (existing is not None and existing.github is github
            and existing.issue_number == issue_number and existing.repository == repository):
        # Nested lifecycle readers share the outer command's immutable range.
        yield
        return
    session = _ADCForwardGenerationSession(github, issue_number, repository, [])
    token: Token[_ADCForwardGenerationSession | None] = _ADC_FORWARD_GENERATION_SESSION.set(session)
    try:
        yield
    finally:
        _ADC_FORWARD_GENERATION_SESSION.reset(token)


def refresh_adc_forward_generation_session(github: Any, issue_number: int) -> None:
    """Discard request-local history before a command's final live readback."""
    session = _ADC_FORWARD_GENERATION_SESSION.get()
    if (session is not None and session.github is github
            and session.issue_number == issue_number
            and session.repository == github.repo.casefold()):
        session.ranges.clear()


def _select_verified_adc_range(
    generations: tuple[VerifiedADC, ...],
    *,
    prior_comment_id: int,
    prior_sha256: str,
    current_comment_id: int,
    current_sha256: str,
) -> tuple[VerifiedADC, ...]:
    prior_matches = [index for index, row in enumerate(generations)
                     if row.pointer.comment_id == prior_comment_id and row.pointer.sha256 == prior_sha256]
    current_matches = [index for index, row in enumerate(generations)
                       if row.pointer.comment_id == current_comment_id and row.pointer.sha256 == current_sha256]
    if (len(prior_matches) != 1 or len(current_matches) != 1
            or prior_matches[0] >= current_matches[0]):
        raise ADCError("ADC successor journal has a gap, rollback or unknown generation")
    return generations[prior_matches[0]:current_matches[0] + 1]


def _cached_session_range(
    session: _ADCForwardGenerationSession,
    *,
    prior_comment_id: int,
    prior_sha256: str,
    current_comment_id: int,
    current_sha256: str,
    require_current: bool,
) -> tuple[VerifiedADC, ...] | None:
    if session.repository != session.github.repo.casefold():
        return None
    for generations, current_verified in reversed(session.ranges):
        if (not generations or any(row.pointer.state != "approved" for row in generations)
                or (require_current and (not current_verified
                                         or generations[-1].pointer.comment_id != current_comment_id
                                         or generations[-1].pointer.sha256 != current_sha256))):
            continue
        try:
            return _select_verified_adc_range(
                generations, prior_comment_id=prior_comment_id, prior_sha256=prior_sha256,
                current_comment_id=current_comment_id, current_sha256=current_sha256,
            )
        except ADCError:
            continue
    return None


def verify_adc_forward_generations(
    github: GitHub,
    issue_number: int,
    *,
    prior_comment_id: int,
    prior_sha256: str,
    current_comment_id: int,
    current_sha256: str,
    allow_historical_target: bool = False,
) -> tuple[VerifiedADC, ...]:
    """Verify an approved ADC range, reusing a request-scoped immutable history check."""
    if (type(prior_comment_id) is not int or prior_comment_id < 1
            or type(current_comment_id) is not int or current_comment_id <= prior_comment_id
            or not isinstance(prior_sha256, str) or not SHA256.fullmatch(prior_sha256)
            or not isinstance(current_sha256, str) or not SHA256.fullmatch(current_sha256)
            or type(allow_historical_target) is not bool):
        raise ADCError("ADC successor range is malformed, stale or backward")
    scope = _ADC_FORWARD_GENERATION_SCOPE.get()
    session = _ADC_FORWARD_GENERATION_SESSION.get()
    if (session is not None
            and (session.github is not github or session.issue_number != issue_number
                 or session.repository != github.repo.casefold())):
        session = None
    if (scope is not None and scope.github is github and scope.issue_number == issue_number
            and scope.repository == github.repo.casefold()
            and allow_historical_target):
        if scope.verified is None:
            scope.verified = (_cached_session_range(
                session, prior_comment_id=scope.prior_comment_id,
                prior_sha256=scope.prior_sha256, current_comment_id=scope.current_comment_id,
                current_sha256=scope.current_sha256, require_current=False,
            ) if session is not None else None)
            if scope.verified is None:
                scope.verified = _verify_adc_forward_generations_uncached(
                    github, issue_number,
                    prior_comment_id=scope.prior_comment_id, prior_sha256=scope.prior_sha256,
                    current_comment_id=scope.current_comment_id, current_sha256=scope.current_sha256,
                    allow_historical_target=True,
                )
                if session is not None:
                    session.ranges.append((scope.verified, False))
        return _select_verified_adc_range(
            scope.verified, prior_comment_id=prior_comment_id, prior_sha256=prior_sha256,
            current_comment_id=current_comment_id, current_sha256=current_sha256,
        )
    if session is not None:
        cached = _cached_session_range(
            session, prior_comment_id=prior_comment_id, prior_sha256=prior_sha256,
            current_comment_id=current_comment_id, current_sha256=current_sha256,
            require_current=not allow_historical_target,
        )
        if cached is not None:
            return cached
        verified = _verify_adc_forward_generations_uncached(
            github, issue_number,
            prior_comment_id=prior_comment_id, prior_sha256=prior_sha256,
            current_comment_id=current_comment_id, current_sha256=current_sha256,
            allow_historical_target=allow_historical_target,
        )
        session.ranges.append((verified, not allow_historical_target))
        return verified
    return _verify_adc_forward_generations_uncached(
        github, issue_number,
        prior_comment_id=prior_comment_id, prior_sha256=prior_sha256,
        current_comment_id=current_comment_id, current_sha256=current_sha256,
        allow_historical_target=allow_historical_target,
    )


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
