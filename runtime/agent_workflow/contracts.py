"""Exact-byte Issue contract storage, publication, restoration, and verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .documents import section_body
from .github import GitHub


class ContractError(ValueError):
    pass


HEADER = re.compile(r"^<!-- agent-contract:v1 issue=(\d+) sha256=([0-9a-f]{64}) bytes=(\d+) -->\n\n")
PTR_ID = re.compile(r"^Comment ID: (\d+)$", re.M)
PTR_SHA = re.compile(r"^SHA-256: ([0-9a-f]{64})$", re.M)
OBVIOUS_SECRET = re.compile(
    r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{16,}|bearer\s+[A-Za-z0-9._~+/-]{16,}|(?:password|secret|client[_-]?secret|authorization|api[_-]?key|access[_-]?token)\s*[:=]\s*\S+)"
)


def contract_dir(repo: Path, issue: int) -> Path:
    return repo / ".agent-state" / "issues" / str(issue)


def payload_path(repo: Path, issue: int) -> Path:
    return contract_dir(repo, issue) / "implementation-contract.md"


def record_path(repo: Path, issue: int) -> Path:
    return contract_dir(repo, issue) / "implementation-contract.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_payload(data: bytes, issue: int) -> tuple[str, int, str]:
    if not isinstance(data, bytes) or not data:
        raise ContractError("Implementation Contract payload must be non-empty bytes")
    if len(data) > 65536:
        raise ContractError(f"Implementation Contract is {len(data)} raw bytes; maximum is 65536")
    if b"\x00" in data:
        raise ContractError("Implementation Contract contains a NUL byte")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContractError("Implementation Contract must be valid UTF-8") from exc
    if OBVIOUS_SECRET.search(text):
        raise ContractError("Implementation Contract appears to contain credential material")
    digest = sha256(data)
    header = f"<!-- agent-contract:v1 issue={issue} sha256={digest} bytes={len(data)} -->\n\n"
    if len(header + text) > 65536:
        raise ContractError("rendered GitHub comment including metadata exceeds 65536 characters")
    return digest, len(data), text


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.",
                                         suffix=".tmp", delete=False) as stream:
            temp_name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def _write_mirror(repo: Path, issue: int, data: bytes) -> dict[str, Any]:
    digest, count, _ = validate_payload(data, issue)
    record = {"schema_version": 1, "issue": issue, "sha256": digest, "bytes": count}
    payload_file, record_file = payload_path(repo, issue), record_path(repo, issue)
    old_payload = payload_file.read_bytes() if payload_file.exists() else None
    old_record = record_file.read_bytes() if record_file.exists() else None
    try:
        atomic_write(payload_file, data)
        atomic_write(record_file, (json.dumps(record, sort_keys=True, indent=2) + "\n").encode())
    except OSError:
        # Roll back the first replacement if the metadata replacement failed.
        if old_payload is None:
            payload_file.unlink(missing_ok=True)
        else:
            atomic_write(payload_file, old_payload)
        if old_record is None:
            record_file.unlink(missing_ok=True)
        else:
            atomic_write(record_file, old_record)
        raise
    return record


def save_contract(repo: Path, issue: int, source: Path | None = None) -> dict[str, Any]:
    path = source or Path("IMPLEMENTATION_CONTRACT.md")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"could not read contract source {path}: {exc}") from exc
    result = _write_mirror(repo, issue, raw)
    return {**result, "path": str(payload_path(repo, issue))}


def parse_pointer(issue_body: str) -> tuple[int, str]:
    headings = re.findall(r"^##\s+Implementation Contract\s*#*\s*$", issue_body or "", re.M | re.I)
    if len(headings) != 1:
        raise ContractError("Issue body must contain exactly one ## Implementation Contract section")
    body = section_body(issue_body or "", "Implementation Contract")
    if body is None:
        raise ContractError("Issue body has no Implementation Contract pointer section")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    allowed = {"Comment ID", "SHA-256", "State"}
    values: dict[str, str] = {}
    for line in lines:
        if ": " not in line:
            raise ContractError("Implementation Contract pointer section has unexpected content")
        key, value = line.split(": ", 1)
        if key not in allowed or key in values:
            raise ContractError("Implementation Contract pointer section has unexpected or duplicate fields")
        values[key] = value
    if set(values) != allowed or values["State"] != "approved":
        raise ContractError("Implementation Contract pointer must contain Comment ID, SHA-256, and State: approved")
    if not values["Comment ID"].isdigit() or not re.fullmatch(r"[0-9a-f]{64}", values["SHA-256"]):
        raise ContractError("Implementation Contract pointer ID or SHA-256 is malformed")
    return int(values["Comment ID"]), values["SHA-256"]


def parse_comment(body: str, issue: int) -> tuple[bytes, str]:
    match = HEADER.match(body or "")
    if not match:
        raise ContractError("named comment does not have a valid Implementation Contract header")
    number, expected_sha, expected_bytes = int(match.group(1)), match.group(2), int(match.group(3))
    if number != issue:
        raise ContractError("Implementation Contract comment names a different Issue")
    payload = (body[match.end():]).encode("utf-8")
    digest, count, _ = validate_payload(payload, issue)
    if digest != expected_sha or count != expected_bytes:
        raise ContractError("Implementation Contract comment header does not match exact payload bytes")
    return payload, digest


def _issue_identity(issue_obj: dict[str, Any], gh: GitHub, issue: int) -> None:
    expected = f"https://api.github.com/repos/{gh.repo}/issues/{issue}"
    if issue_obj.get("number") != issue or issue_obj.get("repository_url") != f"https://api.github.com/repos/{gh.repo}" or issue_obj.get("pull_request"):
        raise ContractError("requested Issue identity does not match the configured repository")


def _comment_identity(comment: dict[str, Any], gh: GitHub, issue: int, expected_id: int | None = None) -> None:
    expected = f"https://api.github.com/repos/{gh.repo}/issues/{issue}"
    if comment.get("issue_url") != expected or comment.get("id") is None or (expected_id is not None and comment.get("id") != expected_id):
        raise ContractError("named comment is not associated with the requested Issue")


def _pointer_body(current_body: str, comment_id: int, digest: str) -> str:
    old = section_body(current_body or "", "Implementation Contract")
    new_text = f"## Implementation Contract\n\nComment ID: {comment_id}\nSHA-256: {digest}\nState: approved"
    if old is None:
        base = (current_body or "").rstrip()
        return f"{base}\n\n{new_text}\n" if base else f"{new_text}\n"
    # Replace precisely the section content while preserving all other Issue text.
    lines = (current_body or "").splitlines()
    start = end = None
    level = 0
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+Implementation Contract\s*#*\s*$", line, re.I)
        if m:
            start, level = i, len(m.group(1))
            break
    if start is None:
        raise ContractError("could not safely locate Implementation Contract heading")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s+", lines[i])
        if m and len(m.group(1)) <= level:
            end = i
            break
    replacement = new_text.splitlines()
    return "\n".join(lines[:start] + replacement + lines[end:]).rstrip() + "\n"


def _record_local(repo: Path, issue: int) -> tuple[dict[str, Any], bytes]:
    try:
        record = json.loads(record_path(repo, issue).read_text(encoding="utf-8"))
        data = payload_path(repo, issue).read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"local verified contract record is missing or invalid: {exc}") from exc
    digest, count, _ = validate_payload(data, issue)
    if record.get("issue") != issue or record.get("sha256") != digest or record.get("bytes") != count:
        raise ContractError("local contract bytes do not match their verified record")
    return record, data


def publish_contract(repo: Path, issue: int, gh: GitHub, source: Path | None = None,
                     supersede: bool = False) -> dict[str, Any]:
    source_path = source or payload_path(repo, issue)
    try:
        data = source_path.read_bytes()
    except OSError as exc:
        raise ContractError(f"could not read contract source {source_path}: {exc}") from exc
    digest, count, text = validate_payload(data, issue)  # reject locally before any network mutation
    local_has_state = payload_path(repo, issue).exists() or record_path(repo, issue).exists()
    local_record = None
    if local_has_state:
        local_record, local_bytes = _record_local(repo, issue)
        if local_bytes != data and not supersede:
            raise ContractError("local verified contract has a different SHA; explicit --supersede is required")
    issue_obj = gh.issue(issue)
    _issue_identity(issue_obj, gh, issue)
    current_id = None
    current_sha = None
    pointer_body = section_body(issue_obj.get("body") or "", "Implementation Contract")
    if pointer_body is not None:
        current_id, current_sha = parse_pointer(issue_obj.get("body") or "")
    if current_sha == digest:
        comment = gh.issue_comment(issue, current_id)
        _comment_identity(comment, gh, issue, current_id)
        remote_payload, remote_sha = parse_comment(comment.get("body", ""), issue)
        if remote_sha != digest or remote_payload != data:
            raise ContractError("current Issue pointer comment differs from local source bytes")
        if local_has_state and local_bytes != data:
            raise ContractError("local mirror differs from the current Issue contract; use restore --replace-stale explicitly")
        result = _write_mirror(repo, issue, data)
        return {**result, "comment_id": current_id, "idempotent": True}
    if current_sha is not None and not supersede:
        raise ContractError("a different approved contract is current; explicit --supersede is required")

    # Reuse an identical pending/current comment if one already exists.
    matching_id = None
    for comment in gh.issue_comments(issue):
        if comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{issue}":
            continue
        body = comment.get("body", "")
        match = HEADER.match(body)
        if not match or int(match.group(1)) != issue or match.group(2) != digest:
            continue
        candidate, candidate_sha = parse_comment(body, issue)
        if candidate == data and candidate_sha == digest:
            matching_id = int(comment["id"])
            break
    if matching_id is None:
        comment_body = f"<!-- agent-contract:v1 issue={issue} sha256={digest} bytes={count} -->\n\n{text}"
        if len(comment_body) > 65536:
            raise ContractError("rendered GitHub comment including metadata exceeds 65536 characters")
        created = gh.create_issue_comment(issue, comment_body)
        matching_id = int(created["id"])
    comment = gh.issue_comment(issue, matching_id)
    _comment_identity(comment, gh, issue, matching_id)
    verified_payload, verified_sha = parse_comment(comment.get("body", ""), issue)
    if verified_payload != data or verified_sha != digest:
        raise ContractError("created contract comment failed exact-byte readback")

    # Immediate read-before-write protects unrelated body sections from concurrent edits.
    latest = gh.issue(issue)
    _issue_identity(latest, gh, issue)
    if (latest.get("body") or "") != (issue_obj.get("body") or ""):
        raise ContractError("Issue body changed concurrently; pointer was not updated")
    updated_body = _pointer_body(latest.get("body") or "", matching_id, digest)
    gh.update_issue(issue, updated_body)
    readback = gh.issue(issue)
    _issue_identity(readback, gh, issue)
    read_id, read_sha = parse_pointer(readback.get("body") or "")
    if read_id != matching_id or read_sha != digest:
        raise ContractError("Issue contract pointer failed readback verification")
    result = _write_mirror(repo, issue, data)
    return {**result, "comment_id": matching_id, "idempotent": False}


def restore_contract(repo: Path, issue: int, gh: GitHub, replace_stale: bool = False) -> dict[str, Any]:
    issue_obj = gh.issue(issue)
    _issue_identity(issue_obj, gh, issue)
    comment_id, pointer_sha = parse_pointer(issue_obj.get("body") or "")
    comment = gh.issue_comment(issue, comment_id)
    _comment_identity(comment, gh, issue, comment_id)
    data, digest = parse_comment(comment.get("body", ""), issue)
    if digest != pointer_sha:
        raise ContractError("Issue pointer SHA does not match its named comment")
    local = payload_path(repo, issue)
    if local.exists() and local.read_bytes() != data:
        try:
            _record_local(repo, issue)
            valid_record = True
        except ContractError:
            valid_record = False
        if not replace_stale:
            raise ContractError("local mirror differs from verified Issue contract; use --replace-stale explicitly")
        backup = local.with_name(f"implementation-contract.{sha256(local.read_bytes())}.bak")
        if not backup.exists():
            atomic_write(backup, local.read_bytes())
    result = _write_mirror(repo, issue, data)
    return {**result, "path": str(local), "comment_id": comment_id}


def verify_contract(repo: Path, issue: int, gh: GitHub) -> dict[str, Any]:
    record, local_data = _record_local(repo, issue)
    issue_obj = gh.issue(issue)
    _issue_identity(issue_obj, gh, issue)
    comment_id, pointer_sha = parse_pointer(issue_obj.get("body") or "")
    comment = gh.issue_comment(issue, comment_id)
    _comment_identity(comment, gh, issue, comment_id)
    remote_data, digest = parse_comment(comment.get("body", ""), issue)
    if pointer_sha != digest or local_data != remote_data:
        raise ContractError("local mirror, named comment, and Issue pointer do not agree")
    return {**record, "comment_id": comment_id, "verified": True}
