"""Checklist extraction, full-contract self-review, and current-HEAD records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import (ContractError, classify_reviewer_checklist_h2,
                        normalize_reviewer_checklist, parse_comment, parse_pointer)
from .documents import without_fenced_blocks
from .github import GitHub, GitHubError


class ReviewError(ValueError):
    pass


CANONICAL_BEGIN = "<!-- AGENT_REVIEWER_CHECKLIST_V1 -->"
CANONICAL_END = "<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->"
CHECK = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s+(.+?)\s*$")
REVIEW_HEADER_V1 = re.compile(
    r"^<!-- agent-self-review:v1 issue=(\d+) pr=(\d+) head=([0-9a-f]{7,40}) checklist=([0-9a-f]{64}) -->$"
)
REVIEW_HEADER_V2 = re.compile(
    r"^<!-- agent-self-review:v2 issue=(\d+) pr=(\d+) head=([0-9a-f]{7,40}) "
    r"contract_comment=(\d+) contract=([0-9a-f]{64}) checklist=([0-9a-f]{64}) -->$"
)
RESULTS = {"pass", "fail", "untested"}
REVIEW_SECRET = re.compile(
    r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{16,}|bearer\s+[A-Za-z0-9._~+/-]{16,})"
)
PR_REVIEW_HEADER = re.compile(
    r"^<!-- agent-pr-review:v1 issue=(\d+) pr=(\d+) head=([0-9a-f]{40}) "
    r"contract_comment=(\d+) contract=([0-9a-f]{64}) checklist=([0-9a-f]{64}) "
    r"fresh_context=true sha256=([0-9a-f]{64}) -->$"
)
PR_REVIEW_POINTER_TITLE = "Agent Independent Review"
PR_REVIEW_RESULTS = {"pending", "pass", "fail", "untested"}
PR_REVIEW_FINDING_SEVERITIES = {"A", "B", "C", "D"}


def _review_utf8_size(value: str, where: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ReviewError(f"{where} contains invalid Unicode text") from exc


def _heading_section(text: str, title: str) -> str | None:
    lines = text.splitlines()
    clean_lines = without_fenced_blocks(text).splitlines()
    start = None
    level = 0
    for i, line in enumerate(clean_lines):
        m = re.match(
            r"^(#{1,6})\s*(?:\d+[.)]?\s*)?Reviewer Checklist(?:\s*[（(][^()（）]*[)）])?\s*#*\s*$",
            line,
            re.I,
        )
        if m:
            start, level = i + 1, len(m.group(1))
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start, len(lines)):
        m = re.match(r"^(#{1,6})\s+", clean_lines[i])
        if m and len(m.group(1)) <= level:
            end = i
            break
    return "\n".join(lines[start:end])


def _extract_items(text: str) -> list[str]:
    try:
        raw = text.encode("utf-8")
        classification = classify_reviewer_checklist_h2(raw)
        if len(classification.checklist_indexes) == 1:
            index = classification.checklist_indexes[0]
            heading = classification.headings[index]
            end = classification.headings[index + 1].start if index + 1 < len(classification.headings) else len(raw)
            section = raw[heading.end:end].decode("utf-8")
            if CANONICAL_BEGIN not in section and CANONICAL_END not in section:
                text = normalize_reviewer_checklist(raw).decode("utf-8")
    except (ContractError, UnicodeEncodeError):
        pass
    text = without_fenced_blocks(text)
    lines = text.splitlines()
    begins = [i for i, line in enumerate(lines) if line.strip() == CANONICAL_BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == CANONICAL_END]
    section = None
    if len(begins) == 1 and len(ends) == 1 and ends[0] > begins[0]:
        section = "\n".join(lines[begins[0] + 1:ends[0]])
    if section is None:
        section = _heading_section(text, "Reviewer Checklist")
    if section is None:
        return []
    items = []
    for line in section.splitlines():
        match = CHECK.match(line)
        if match:
            items.append(match.group(1).strip())
    return items


def contract_review_units(contract: bytes) -> list[dict[str, str]]:
    """Derive ordered review units and hash their exact original UTF-8 bytes."""
    if not isinstance(contract, bytes):
        raise ReviewError("approved Implementation Contract must be exact bytes")
    classification = classify_reviewer_checklist_h2(contract)
    headings = classification.headings
    excluded_checklist = (
        set(classification.checklist_indexes)
        if classification.state == "strict-canonical" else set()
    )

    units: list[dict[str, str]] = []
    first_heading = headings[0].start if headings else len(contract)
    preamble = contract[:first_heading]
    if preamble.strip():
        units.append({
            "id": "P000",
            "title": "Contract Preamble",
            "section_sha256": hashlib.sha256(preamble).hexdigest(),
        })

    section_number = 0
    for index, heading in enumerate(headings):
        if index in excluded_checklist:
            continue
        end = headings[index + 1].start if index + 1 < len(headings) else len(contract)
        section_number += 1
        units.append({
            "id": f"S{section_number:03d}",
            "title": heading.title,
            "section_sha256": hashlib.sha256(contract[heading.start:end]).hexdigest(),
        })
    return units


def _load_approved_contract(issue: int, issue_body: str, gh: GitHub) -> dict[str, Any]:
    """Fetch and verify the exact named approved contract once for a state snapshot."""
    contract_id, contract_sha = parse_pointer(issue_body or "")
    comment = gh.issue_comment(issue, contract_id)
    if (comment.get("id") != contract_id
            or comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{issue}"):
        raise ReviewError("Implementation Contract comment is associated with a different Issue")
    contract, actual_sha = parse_comment(comment.get("body", ""), issue)
    if actual_sha != contract_sha:
        raise ReviewError("Implementation Contract pointer and source SHA disagree")
    return {
        "contract_comment_id": contract_id,
        "contract_sha256": actual_sha,
        "contract_bytes": contract,
    }


def _derive_review_surface(issue_body: str, approved: dict[str, Any]) -> dict[str, Any]:
    contract = approved["contract_bytes"]
    text = contract.decode("utf-8")
    contract_items = _extract_items(text)
    issue_items = _extract_items(issue_body or "")
    items = (
        [{"id": f"C{n:03d}", "text": value} for n, value in enumerate(contract_items, 1)]
        + [{"id": f"I{n:03d}", "text": value} for n, value in enumerate(issue_items, 1)]
    )
    if not items:
        raise ReviewError("effective Reviewer Checklist is empty")
    canonical = json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "contract_comment_id": approved["contract_comment_id"],
        "contract_sha256": approved["contract_sha256"],
        "contract_sections": contract_review_units(contract),
        "items": items,
        "checklist_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def load_review_surface(issue: int, issue_body: str, gh: GitHub) -> dict[str, Any]:
    """Read the named approved contract once and derive both mandatory review layers."""
    return _derive_review_surface(issue_body, _load_approved_contract(issue, issue_body, gh))


def effective_checklist(issue_number: int, issue_body: str, gh: GitHub) -> tuple[list[dict[str, str]], str]:
    surface = load_review_surface(issue_number, issue_body, gh)
    return surface["items"], surface["checklist_sha256"]


def _verify_issue_identity(issue_obj: Any, issue: int, gh: GitHub) -> None:
    if (not isinstance(issue_obj, dict) or type(issue_obj.get("number")) is not int
            or issue_obj.get("number") != issue
            or issue_obj.get("repository_url") != f"https://api.github.com/repos/{gh.repo}"
            or issue_obj.get("pull_request")):
        raise ReviewError("Issue identity does not match configured repository")


def _verify_pull_identity(pull: Any, pr: int, gh: GitHub) -> None:
    base = pull.get("base") if isinstance(pull, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    full_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    if (not isinstance(pull, dict) or type(pull.get("number")) is not int
            or pull.get("number") != pr or not isinstance(full_name, str)
            or full_name.casefold() != gh.repo.casefold()):
        raise ReviewError("PR repository identity mismatch")


def _pull_head(pull: dict[str, Any]) -> Any:
    head = pull.get("head")
    return head.get("sha") if isinstance(head, dict) else None


def review_path(repo: Path, issue: int, pr: int) -> Path:
    return repo / ".agent-state" / "issues" / str(issue) / f"self-review-pr-{pr}.json"


def _write_review(path: Path, draft: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(draft, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temp_name = stream.name
            stream.write(raw)
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


def _surface_identity(surface: dict[str, Any]) -> tuple[Any, ...]:
    return (
        surface["contract_comment_id"],
        surface["contract_sha256"],
        tuple((unit["id"], unit["title"], unit["section_sha256"])
              for unit in surface["contract_sections"]),
        surface["checklist_sha256"],
        tuple((item["id"], item["text"]) for item in surface["items"]),
    )


def _draft_surface_identity(draft: dict[str, Any]) -> tuple[Any, ...]:
    return (
        draft.get("contract_comment_id"),
        draft.get("contract_sha256"),
        tuple((unit.get("id"), unit.get("title"), unit.get("section_sha256"))
              for unit in draft.get("contract_sections", []) if isinstance(unit, dict)),
        draft.get("checklist_sha256"),
        tuple((item.get("id"), item.get("text"))
              for item in draft.get("items", []) if isinstance(item, dict)),
    )


def prepare_review(repo: Path, issue: int, pr: int, gh: GitHub) -> dict[str, Any]:
    issue_obj = gh.issue(issue)
    _verify_issue_identity(issue_obj, issue, gh)
    pull = gh.pull(pr)
    _verify_pull_identity(pull, pr, gh)
    head = _pull_head(pull)
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{7,40}", head):
        raise ReviewError("PR current HEAD is missing or malformed")
    surface = load_review_surface(issue, issue_obj.get("body") or "", gh)
    draft = {
        "schema_version": 2,
        "issue": issue,
        "pr": pr,
        "head": head,
        "contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": surface["contract_sha256"],
        "checklist_sha256": surface["checklist_sha256"],
        "contract_sections": [
            {**unit, "result": "pending", "evidence": ""}
            for unit in surface["contract_sections"]
        ],
        "items": [
            {**item, "result": "pending", "evidence": ""}
            for item in surface["items"]
        ],
    }
    path = review_path(repo, issue, pr)
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if (
            isinstance(previous, dict)
            and previous.get("schema_version") == 2
            and previous.get("issue") == issue
            and previous.get("pr") == pr
            and previous.get("head") == head
            and isinstance(previous.get("contract_sections"), list)
            and all(isinstance(unit, dict) for unit in previous["contract_sections"])
            and isinstance(previous.get("items"), list)
            and all(isinstance(item, dict) for item in previous["items"])
            and _draft_surface_identity(previous) == _surface_identity(surface)
        ):
            return {
                "path": str(path),
                "schema_version": 2,
                "head": head,
                "contract_comment_id": surface["contract_comment_id"],
                "contract_sha256": surface["contract_sha256"],
                "contract_section_count": len(surface["contract_sections"]),
                "checklist_sha256": surface["checklist_sha256"],
                "items": len(surface["items"]),
                "reused": True,
            }
        previous_bytes = path.read_bytes()
        backup_sha = hashlib.sha256(previous_bytes).hexdigest()
        backup = path.with_name(f"{path.stem}.{backup_sha}.stale.json")
        if not backup.exists():
            backup.write_bytes(previous_bytes)
    _write_review(path, draft)
    return {
        "path": str(path),
        "schema_version": 2,
        "head": head,
        "contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": surface["contract_sha256"],
        "contract_section_count": len(surface["contract_sections"]),
        "checklist_sha256": surface["checklist_sha256"],
        "items": len(surface["items"]),
    }


def _validate_section_order(sections: list[dict[str, Any]]) -> None:
    ids = [section["id"] for section in sections]
    if len(ids) != len(set(ids)):
        raise ReviewError("self-review contains duplicate contract section IDs")
    expected: list[str] = []
    start = 0
    if ids and ids[0] == "P000":
        expected.append("P000")
        start = 1
    expected.extend(f"S{n:03d}" for n in range(1, len(ids) - start + 1))
    if ids != expected:
        raise ReviewError("self-review contract sections are missing or reordered")


def _validate_review_data(draft: Any, *, allow_legacy: bool = False) -> dict[str, Any]:
    if not isinstance(draft, dict):
        raise ReviewError("self-review payload has invalid schema")
    schema = draft.get("schema_version")
    if type(schema) is not int or schema not in ({1, 2} if allow_legacy else {2}):
        raise ReviewError("self-review payload has unsupported schema version")
    for field in ("issue", "pr"):
        if type(draft.get(field)) is not int or draft[field] < 1:
            raise ReviewError(f"self-review payload has invalid {field.upper()} identity")
    if not isinstance(draft.get("items"), list) or not draft["items"]:
        raise ReviewError("self-review payload has invalid checklist items")
    if not re.fullmatch(r"[0-9a-f]{7,40}", str(draft.get("head", ""))):
        raise ReviewError("self-review payload has invalid HEAD")
    if not re.fullmatch(r"[0-9a-f]{64}", str(draft.get("checklist_sha256", ""))):
        raise ReviewError("self-review payload has invalid checklist SHA")
    if schema == 2:
        if type(draft.get("contract_comment_id")) is not int or draft["contract_comment_id"] < 1:
            raise ReviewError("self-review payload has invalid approved contract comment ID")
        if not re.fullmatch(r"[0-9a-f]{64}", str(draft.get("contract_sha256", ""))):
            raise ReviewError("self-review payload has invalid contract SHA")
        if not isinstance(draft.get("contract_sections"), list):
            raise ReviewError("self-review payload has invalid contract sections")
        sections = draft["contract_sections"]
        for section in sections:
            if not isinstance(section, dict):
                raise ReviewError("self-review contains malformed contract section")
            section_id = section.get("id")
            title = section.get("title")
            digest = section.get("section_sha256")
            if (not isinstance(section_id, str)
                    or not (section_id == "P000" or re.fullmatch(r"S\d{3,}", section_id))
                    or not isinstance(title, str) or not title.strip()
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ReviewError("self-review contains malformed contract section identity")
            if (not isinstance(section.get("result"), str) or section["result"] not in RESULTS
                    or not isinstance(section.get("evidence"), str)
                    or not section["evidence"].strip()):
                raise ReviewError(f"{section_id}: result must be pass/fail/untested with concrete evidence")
            if REVIEW_SECRET.search(title + "\n" + section["evidence"]):
                raise ReviewError(f"{section_id}: self-review contains credential material")
        _validate_section_order(sections)
    elif "contract_sections" in draft or "contract_sha256" in draft or "contract_comment_id" in draft:
        raise ReviewError("schema v1 self-review cannot claim full contract conformance")

    seen: set[str] = set()
    for item in draft["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in seen:
            raise ReviewError("self-review contains malformed or duplicate checklist item")
        seen.add(item["id"])
        if (not isinstance(item.get("result"), str) or item["result"] not in RESULTS
                or not isinstance(item.get("evidence"), str) or not item["evidence"].strip()):
            raise ReviewError(f"{item.get('id', 'item')}: result must be pass/fail/untested with concrete evidence")
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ReviewError("self-review item text is empty")
        if REVIEW_SECRET.search(item["text"] + "\n" + item["evidence"]):
            raise ReviewError(f"{item['id']}: self-review contains credential material")
    return draft


def load_review(path: Path) -> dict[str, Any]:
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"could not read self-review JSON: {exc}") from exc
    if (not isinstance(draft, dict) or type(draft.get("schema_version")) is not int
            or draft.get("schema_version") != 2):
        raise ReviewError("self-review draft must use schema version 2")
    return _validate_review_data(draft)


def _review_payload(draft: dict[str, Any]) -> str:
    return json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=2)


def _pointer(pr_body: str) -> tuple[int, str, str, str, int | None, str | None]:
    lines = (pr_body or "").splitlines()
    if len(re.findall(r"^##\s+Agent Self-Review\s*$", pr_body or "", re.M | re.I)) != 1:
        raise ReviewError("PR body must contain exactly one ## Agent Self-Review pointer section")
    for i, line in enumerate(lines):
        if re.match(r"^##\s+Agent Self-Review\s*$", line, re.I):
            fields: dict[str, str] = {}
            for entry in lines[i + 1:]:
                if re.match(r"^#{1,6}\s+", entry):
                    break
                if ": " in entry:
                    key, val = entry.split(": ", 1)
                    key = key.strip()
                    if key in fields:
                        raise ReviewError("PR review pointer contains duplicate fields")
                    fields[key] = val.strip()
            try:
                cid = int(fields["Comment ID"])
                sha = fields["SHA-256"]
                head = fields["HEAD"]
                checklist = fields["Checklist SHA-256"]
                contract_comment = fields.get("Contract Comment ID")
                contract = fields.get("Contract SHA-256")
            except (KeyError, ValueError) as exc:
                raise ReviewError("PR review pointer is malformed") from exc
            try:
                contract_comment_id = int(contract_comment) if contract_comment is not None else None
            except ValueError as exc:
                raise ReviewError("PR review pointer contains malformed contract comment ID") from exc
            if (cid < 1
                    or not re.fullmatch(r"[0-9a-f]{64}", sha)
                    or not re.fullmatch(r"[0-9a-f]{7,40}", head)
                    or not re.fullmatch(r"[0-9a-f]{64}", checklist)
                    or (contract_comment_id is not None and contract_comment_id < 1)
                    or (contract is not None and not re.fullmatch(r"[0-9a-f]{64}", contract))):
                raise ReviewError("PR review pointer contains malformed hash/HEAD")
            return cid, sha, head, checklist, contract_comment_id, contract
    raise ReviewError("PR has no Agent Self-Review pointer")


def _with_pointer(
    body: str, comment_id: int, sha: str, head: str, checklist_sha: str,
    contract_comment_id: int, contract_sha: str,
) -> str:
    block = [
        "## Agent Self-Review", "", f"Comment ID: {comment_id}", f"SHA-256: {sha}",
        f"HEAD: {head}", f"Contract Comment ID: {contract_comment_id}",
        f"Contract SHA-256: {contract_sha}",
        f"Checklist SHA-256: {checklist_sha}",
    ]
    lines = (body or "").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^##\s+Agent Self-Review\s*$", line, re.I)),
        None,
    )
    if start is None:
        base = (body or "").rstrip()
        return (base + "\n\n" if base else "") + "\n".join(block) + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,2}\s+", lines[i]):
            end = i
            break
    return "\n".join(lines[:start] + block + lines[end:]).rstrip() + "\n"


def _unit_identities(sections: list[dict[str, Any]]) -> tuple[tuple[str, str, str], ...]:
    return tuple((section["id"], section["title"], section["section_sha256"]) for section in sections)


def _same_surface(review: dict[str, Any], surface: dict[str, Any]) -> bool:
    return (
        review.get("contract_comment_id") == surface["contract_comment_id"]
        and review.get("contract_sha256") == surface["contract_sha256"]
        and _unit_identities(review.get("contract_sections", [])) == _unit_identities(surface["contract_sections"])
        and review.get("checklist_sha256") == surface["checklist_sha256"]
        and [(item.get("id"), item.get("text")) for item in review.get("items", [])]
        == [(item["id"], item["text"]) for item in surface["items"]]
    )


def publish_review(
    repo: Path, issue: int, pr: int, gh: GitHub, draft_path: Path | None = None
) -> dict[str, Any]:
    path = draft_path or review_path(repo, issue, pr)
    draft = load_review(path)
    if draft.get("issue") != issue or draft.get("pr") != pr:
        raise ReviewError("self-review draft Issue/PR identity mismatch")
    issue_obj = gh.issue(issue)
    _verify_issue_identity(issue_obj, issue, gh)
    approved = _load_approved_contract(issue, issue_obj.get("body") or "", gh)
    pull = gh.pull(pr)
    _verify_pull_identity(pull, pr, gh)
    current_head = _pull_head(pull)
    surface = _derive_review_surface(issue_obj.get("body") or "", approved)
    if draft["head"] != current_head:
        raise ReviewError("self-review draft is stale: PR HEAD changed")
    if draft.get("contract_comment_id") != surface["contract_comment_id"]:
        raise ReviewError("self-review draft is stale: approved Implementation Contract comment ID changed")
    if draft.get("contract_sha256") != surface["contract_sha256"]:
        raise ReviewError("self-review draft is stale: approved Implementation Contract SHA changed")
    if not _same_surface(draft, surface):
        raise ReviewError("self-review draft is stale: approved contract comment/SHA, contract sections, or checklist changed")

    payload = _review_payload(draft)
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    comment_body = (
        f"<!-- agent-self-review:v2 issue={issue} pr={pr} head={current_head} "
        f"contract_comment={surface['contract_comment_id']} contract={surface['contract_sha256']} "
        f"checklist={surface['checklist_sha256']} -->\n\n{payload}"
    )
    if len(comment_body) > 65536:
        raise ReviewError("self-review comment exceeds 65536 characters")
    created = gh.create_pull_comment(pr, comment_body)
    try:
        cid = int(created["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewError("published self-review comment creation returned an invalid ID") from exc

    try:
        named_comment = gh.pull_comment(cid)
    except GitHubError as exc:
        raise ReviewError(f"published self-review comment {cid} could not be read back by ID") from exc
    if not isinstance(named_comment, dict) or named_comment.get("id") != cid:
        raise ReviewError("published self-review comment named readback returned a different ID")
    if named_comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}":
        raise ReviewError("published self-review comment named readback belongs to a different PR")
    if named_comment.get("body") != comment_body:
        raise ReviewError("published self-review comment named readback body differs from submitted bytes")

    # Re-read the Issue and named approved comment first, then PR HEAD. The
    # immutable comment remains orphan evidence if any identity has changed.
    latest_issue = gh.issue(issue)
    _verify_issue_identity(latest_issue, issue, gh)
    latest_approved = _load_approved_contract(issue, latest_issue.get("body") or "", gh)
    latest = gh.pull(pr)
    _verify_pull_identity(latest, pr, gh)
    if _pull_head(latest) != current_head:
        raise ReviewError("PR HEAD changed while publishing self-review")
    latest_surface = _derive_review_surface(latest_issue.get("body") or "", latest_approved)
    if not _same_surface(draft, latest_surface):
        raise ReviewError("approved contract comment/SHA, contract units, or checklist changed while publishing self-review")

    updated = _with_pointer(
        latest.get("body") or "", cid, sha, current_head,
        surface["checklist_sha256"], surface["contract_comment_id"], surface["contract_sha256"],
    )
    gh.update_pull(pr, updated)
    readback = gh.pull(pr)
    pointer = _pointer(readback.get("body") or "")
    if pointer != (cid, sha, current_head, surface["checklist_sha256"],
                   surface["contract_comment_id"], surface["contract_sha256"]):
        raise ReviewError("PR self-review pointer failed readback verification")
    return {
        "comment_id": cid,
        "sha256": sha,
        "head": current_head,
        "contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": surface["contract_sha256"],
        "contract_section_count": len(surface["contract_sections"]),
        "checklist_sha256": surface["checklist_sha256"],
        "schema_version": 2,
    }


def validate_public_review(
    issue: int, pr: int, gh: GitHub, *, issue_obj: dict[str, Any] | None = None,
    pull: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_obj = issue_obj if issue_obj is not None else gh.issue(issue)
    pull = pull if pull is not None else gh.pull(pr)
    _verify_issue_identity(issue_obj, issue, gh)
    _verify_pull_identity(pull, pr, gh)
    (cid, expected_sha, reviewed_head, checklist_sha,
     pointer_contract_comment, pointer_contract) = _pointer(pull.get("body") or "")
    # Fetch only the specifically named review comment.
    comment = gh.pull_comment(cid)
    if comment.get("id") != cid or comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}":
        raise ReviewError("published review comment belongs to a different PR")
    body = comment.get("body", "")
    header, sep, payload_text = body.partition("\n\n")
    version1 = REVIEW_HEADER_V1.match(header)
    version2 = REVIEW_HEADER_V2.match(header)
    if not sep or not (version1 or version2):
        raise ReviewError("named public review comment has invalid metadata")
    match = version1 or version2
    schema = 1 if version1 else 2
    if int(match.group(1)) != issue or int(match.group(2)) != pr:
        raise ReviewError("named public review comment has invalid metadata")
    contract_comment_id = None if schema == 1 else int(version2.group(4))
    contract_sha = None if schema == 1 else version2.group(5)
    header_checklist = version1.group(4) if schema == 1 else version2.group(6)
    if schema == 1 and (pointer_contract_comment is not None or pointer_contract is not None):
        raise ReviewError("schema v1 review pointer cannot claim a contract SHA")
    if schema == 2 and (pointer_contract_comment != contract_comment_id or pointer_contract != contract_sha):
        raise ReviewError("PR pointer and public review contract identity disagree")
    payload_sha = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    if payload_sha != expected_sha or match.group(3) != reviewed_head or header_checklist != checklist_sha:
        raise ReviewError("published review pointer and comment metadata disagree")
    try:
        review = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ReviewError("published review body is invalid JSON") from exc
    if (not isinstance(review, dict) or review.get("issue") != issue or review.get("pr") != pr
            or review.get("head") != reviewed_head or review.get("checklist_sha256") != checklist_sha
            or review.get("schema_version") != schema):
        raise ReviewError("published review payload identity is inconsistent")
    _validate_review_data(review, allow_legacy=True)
    if schema == 2 and (review.get("contract_comment_id") != contract_comment_id
                        or review.get("contract_sha256") != contract_sha):
        raise ReviewError("published review contract identity differs from its metadata")

    surface = load_review_surface(issue, issue_obj.get("body") or "", gh)
    current_head = _pull_head(pull)
    stale_reasons: list[str] = []
    head_stale = current_head != reviewed_head
    if head_stale:
        stale_reasons.append("PR HEAD changed")
    checklist_stale = (
        surface["checklist_sha256"] != checklist_sha
        or [(item["id"], item["text"]) for item in review["items"]]
        != [(item["id"], item["text"]) for item in surface["items"]]
    )
    if checklist_stale:
        stale_reasons.append("effective Reviewer Checklist changed")
    contract_stale = False
    if schema == 2:
        contract_stale = (
            surface["contract_comment_id"] != contract_comment_id
            or surface["contract_sha256"] != contract_sha
            or _unit_identities(review["contract_sections"]) != _unit_identities(surface["contract_sections"])
        )
        if contract_stale:
            stale_reasons.append("approved Implementation Contract comment/SHA or contract review units changed")
    return {
        "comment_id": cid,
        "sha256": expected_sha,
        "head": reviewed_head,
        "contract_comment_id": contract_comment_id,
        "current_contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": contract_sha,
        "current_contract_sha256": surface["contract_sha256"],
        "contract_section_count": len(review.get("contract_sections", [])),
        "current_contract_section_count": len(surface["contract_sections"]),
        "checklist_sha256": checklist_sha,
        "schema_version": schema,
        "contract_conformance": schema == 2,
        "stale": bool(stale_reasons),
        "stale_reasons": stale_reasons,
        "head_stale": head_stale,
        "contract_stale": contract_stale,
        "checklist_stale": checklist_stale,
        "current_head": current_head,
        "review": review,
    }


def pr_review_path(repo: Path, issue: int, pr: int) -> Path:
    return repo / ".agent-state" / "issues" / str(issue) / f"pr-review-pr-{pr}.json"


def _write_pr_review(path: Path, draft: dict[str, Any]) -> None:
    try:
        _write_review(path, draft)
    except UnicodeEncodeError as exc:
        raise ReviewError("independent-review draft contains invalid Unicode text") from exc


def _atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temp_name = stream.name
            stream.write(raw)
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


def _pr_review_current(issue: int, pr: int, gh: GitHub) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    issue_obj = gh.issue(issue)
    _verify_issue_identity(issue_obj, issue, gh)
    if issue_obj.get("state") != "open":
        raise ReviewError("independent review requires an open Issue")
    pull = gh.pull(pr)
    _verify_pull_identity(pull, pr, gh)
    head_repo = pull.get("head", {}).get("repo") if isinstance(pull.get("head"), dict) else None
    if (not isinstance(head_repo, dict)
            or str(head_repo.get("full_name", "")).casefold() != gh.repo.casefold()):
        raise ReviewError("independent review requires a same-repository PR head")
    if pull.get("state") != "open" or pull.get("draft") is not False or pull.get("merged") is True:
        raise ReviewError("independent review requires an open, non-draft PR")
    body = pull.get("body")
    if not isinstance(body, str) or not re.search(rf"(?im)^\s*closes\s+#{issue}\s*$", body):
        raise ReviewError(f"PR body must contain a standalone Closes #{issue} line")
    head = _pull_head(pull)
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReviewError("independent review requires a full current PR HEAD SHA")
    surface = load_review_surface(issue, issue_obj.get("body") or "", gh)
    return issue_obj, pull, surface, head


def prepare_pr_review(repo: Path, issue: int, pr: int, gh: GitHub) -> dict[str, Any]:
    _issue_obj, _pull, surface, head = _pr_review_current(issue, pr, gh)
    draft = {
        "schema_version": 1,
        "issue": issue,
        "pr": pr,
        "head": head,
        "contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": surface["contract_sha256"],
        "contract_sections": [
            {**unit, "result": "pending", "evidence": ""}
            for unit in surface["contract_sections"]
        ],
        "checklist_sha256": surface["checklist_sha256"],
        "items": [
            {**item, "result": "pending", "evidence": ""}
            for item in surface["items"]
        ],
        "fresh_context": False,
        "findings": [],
    }
    path = pr_review_path(repo, issue, pr)
    if path.exists():
        try:
            previous_bytes = path.read_bytes()
        except OSError as exc:
            raise ReviewError(f"could not preserve prior independent-review draft: {exc}") from exc
        try:
            previous = json.loads(previous_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            previous = None
        if (isinstance(previous, dict) and previous.get("schema_version") == 1
                and previous.get("issue") == issue and previous.get("pr") == pr
                and previous.get("head") == head
                and previous.get("contract_comment_id") == surface["contract_comment_id"]
                and previous.get("contract_sha256") == surface["contract_sha256"]
                and previous.get("checklist_sha256") == surface["checklist_sha256"]
                and _pr_review_matches(previous, head, surface)):
            _validate_pr_review_data(previous, issue, pr, allow_pending=True)
            return {"path": str(path), "head": head, "contract_comment_id": surface["contract_comment_id"],
                    "contract_sha256": surface["contract_sha256"],
                    "contract_section_count": len(surface["contract_sections"]),
                    "checklist_sha256": surface["checklist_sha256"], "items": len(surface["items"]),
                    "reused": True}
        digest = hashlib.sha256(previous_bytes).hexdigest()
        backup = path.with_name(f"{path.stem}.{digest}.stale.json")
        if not backup.exists():
            _atomic_bytes(backup, previous_bytes)
    _write_pr_review(path, draft)
    return {"path": str(path), "head": head, "contract_comment_id": surface["contract_comment_id"],
            "contract_sha256": surface["contract_sha256"],
            "contract_section_count": len(surface["contract_sections"]),
            "checklist_sha256": surface["checklist_sha256"], "items": len(surface["items"]),
            "reused": False}


def _validate_pr_review_data(value: Any, issue: int, pr: int, *, allow_pending: bool) -> dict[str, Any]:
    required = {"schema_version", "issue", "pr", "head", "contract_comment_id", "contract_sha256",
                "contract_sections", "checklist_sha256", "items", "fresh_context", "findings"}
    if not isinstance(value, dict) or set(value) != required or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ReviewError("independent-review payload has an invalid or unsupported schema")
    if type(value.get("issue")) is not int or value["issue"] != issue or type(value.get("pr")) is not int or value["pr"] != pr:
        raise ReviewError("independent-review payload Issue/PR identity mismatch")
    if not isinstance(value.get("head"), str) or not re.fullmatch(r"[0-9a-f]{40}", value["head"]):
        raise ReviewError("independent-review payload HEAD is malformed")
    if type(value.get("contract_comment_id")) is not int or value["contract_comment_id"] < 1:
        raise ReviewError("independent-review contract comment ID is malformed")
    if not isinstance(value.get("contract_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["contract_sha256"]):
        raise ReviewError("independent-review contract SHA-256 is malformed")
    if not isinstance(value.get("checklist_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["checklist_sha256"]):
        raise ReviewError("independent-review checklist SHA-256 is malformed")
    if type(value.get("fresh_context")) is not bool:
        raise ReviewError("independent-review fresh_context attestation must be boolean")
    if not allow_pending and value["fresh_context"] is not True:
        raise ReviewError("independent review requires fresh_context: true attestation")
    sections, items, findings = value.get("contract_sections"), value.get("items"), value.get("findings")
    if not isinstance(sections, list) or not isinstance(items, list) or not items or not isinstance(findings, list) or len(findings) > 100:
        raise ReviewError("independent-review sections, checklist, or findings are malformed")
    for kind, entries in (("contract", sections), ("checklist", items)):
        seen: set[str] = set()
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                raise ReviewError(f"independent-review {kind} item {index} is malformed")
            if kind == "contract":
                if set(entry) != {"id", "title", "section_sha256", "result", "evidence"}:
                    raise ReviewError(f"independent-review contract unit {index} has an invalid schema")
                item_id, text = entry.get("id"), entry.get("title")
                if (not isinstance(item_id, str) or not (item_id == "P000" or re.fullmatch(r"S\d{3,}", item_id))
                        or not isinstance(entry.get("section_sha256"), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", entry["section_sha256"])):
                    raise ReviewError(f"independent-review contract unit {index} identity is malformed")
            else:
                if set(entry) != {"id", "text", "result", "evidence"}:
                    raise ReviewError(f"independent-review checklist item {index} has an invalid schema")
                item_id, text = entry.get("id"), entry.get("text")
                if not isinstance(item_id, str) or not re.fullmatch(r"[CI]\d{3,}", item_id):
                    raise ReviewError(f"independent-review checklist item {index} identity is malformed")
            if item_id in seen:
                raise ReviewError(f"independent-review {kind} IDs must be unique")
            seen.add(item_id)
            result, evidence = entry.get("result"), entry.get("evidence")
            if not isinstance(text, str) or not text.strip() or not isinstance(result, str) or result not in PR_REVIEW_RESULTS:
                raise ReviewError(f"{item_id}: independent-review item has malformed text or result")
            if not isinstance(evidence, str) or (result != "pending" and not evidence.strip()):
                raise ReviewError(f"{item_id}: independent-review result requires concrete evidence")
            if any(_review_utf8_size(field, f"{item_id} evidence") > 16384 or REVIEW_SECRET.search(field)
                   for field in (text, evidence)):
                raise ReviewError(f"{item_id}: independent-review evidence is oversized or contains credential material")
            if result == "pending" and not allow_pending:
                raise ReviewError(f"{item_id}: independent review is incomplete")
    finding_ids: set[str] = set()
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict) or set(finding) != {"id", "severity", "title", "evidence", "blocking"}:
            raise ReviewError(f"independent-review finding {index} has an invalid schema")
        fid, severity = finding.get("id"), finding.get("severity")
        title, evidence, blocking = finding.get("title"), finding.get("evidence"), finding.get("blocking")
        if (not isinstance(fid, str) or not re.fullmatch(r"F\d{3,}", fid) or fid in finding_ids
                or not isinstance(severity, str) or severity not in PR_REVIEW_FINDING_SEVERITIES
                or not isinstance(title, str) or not title.strip()
                or not isinstance(evidence, str) or not evidence.strip() or type(blocking) is not bool):
            raise ReviewError(f"independent-review finding {index} is malformed")
        finding_ids.add(fid)
        if (severity in {"A", "B"} and not blocking) or (severity == "D" and blocking):
            raise ReviewError(f"{fid}: A/B findings must block and D findings must not block")
        if any(_review_utf8_size(field, f"{fid} finding") > 16384 or REVIEW_SECRET.search(field)
               for field in (title, evidence)):
            raise ReviewError(f"{fid}: finding is oversized or contains credential material")
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if _review_utf8_size(serialized, "independent-review payload") > 65536 or REVIEW_SECRET.search(serialized):
        raise ReviewError("independent-review payload is oversized or contains credential material")
    return value


def _read_pr_review(path: Path, issue: int, pr: int, *, allow_pending: bool) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReviewError(f"could not read independent-review JSON: {exc}") from exc
    if len(raw) > 65536:
        raise ReviewError("independent-review draft exceeds 65536 bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewError("independent-review draft must be valid UTF-8 JSON") from exc
    return _validate_pr_review_data(value, issue, pr, allow_pending=allow_pending)


def _pr_review_matches(value: dict[str, Any], head: str, surface: dict[str, Any]) -> bool:
    return (value["head"] == head
            and value["contract_comment_id"] == surface["contract_comment_id"]
            and value["contract_sha256"] == surface["contract_sha256"]
            and _unit_identities(value["contract_sections"]) == _unit_identities(surface["contract_sections"])
            and value["checklist_sha256"] == surface["checklist_sha256"]
            and [(item["id"], item["text"]) for item in value["items"]]
            == [(item["id"], item["text"]) for item in surface["items"]])


def validate_pr_review(repo: Path, issue: int, pr: int, gh: GitHub, source: Path | None = None) -> dict[str, Any]:
    value = _read_pr_review(source or pr_review_path(repo, issue, pr), issue, pr, allow_pending=False)
    _issue_obj, _pull, surface, head = _pr_review_current(issue, pr, gh)
    stale = not _pr_review_matches(value, head, surface)
    return {"valid": True, "stale": stale,
            "stale_reasons": (["PR HEAD, approved contract, or effective checklist changed"] if stale else []),
            "fresh_context": value["fresh_context"], "head": value["head"],
            "contract_comment_id": value["contract_comment_id"],
            "contract_sha256": value["contract_sha256"],
            "contract_section_count": len(value["contract_sections"]), "item_count": len(value["items"]),
            "finding_count": len(value["findings"]),
            "blocking_finding_count": sum(bool(finding["blocking"]) for finding in value["findings"]),
            "contract_units_pass": all(section["result"] == "pass" for section in value["contract_sections"]),
            "checklist_fail_count": sum(item["result"] == "fail" for item in value["items"]),
            "passed": (not stale and all(section["result"] == "pass" for section in value["contract_sections"])
                       and not any(item["result"] == "fail" for item in value["items"])
                       and not any(finding["blocking"] for finding in value["findings"]))}


def _pr_review_pointer(body: str) -> dict[str, Any] | None:
    heading = re.compile(r"^##\s+Agent Independent Review\s*$", re.I | re.M)
    matches = list(heading.finditer(body or ""))
    if not matches:
        return None
    if len(matches) != 1:
        raise ReviewError("PR body must contain at most one Agent Independent Review pointer")
    lines = (body or "").splitlines()
    start = next(i for i, line in enumerate(lines) if heading.fullmatch(line))
    fields: dict[str, str] = {}
    for line in lines[start + 1:]:
        if re.match(r"^#{1,6}\s+", line):
            break
        if ": " in line:
            key, value = line.split(": ", 1)
            key = key.strip()
            if key in fields:
                raise ReviewError("independent-review pointer contains duplicate fields")
            fields[key] = value.strip()
    expected = {"Comment ID", "SHA-256", "HEAD", "Contract Comment ID", "Contract SHA-256",
                "Checklist SHA-256", "Fresh Context"}
    if set(fields) != expected:
        raise ReviewError("independent-review pointer is malformed")
    try:
        comment_id, contract_id = int(fields["Comment ID"]), int(fields["Contract Comment ID"])
    except ValueError as exc:
        raise ReviewError("independent-review pointer contains a malformed comment ID") from exc
    if (comment_id < 1 or contract_id < 1 or not re.fullmatch(r"[0-9a-f]{64}", fields["SHA-256"])
            or not re.fullmatch(r"[0-9a-f]{40}", fields["HEAD"])
            or not re.fullmatch(r"[0-9a-f]{64}", fields["Contract SHA-256"])
            or not re.fullmatch(r"[0-9a-f]{64}", fields["Checklist SHA-256"])
            or fields["Fresh Context"] != "true"):
        raise ReviewError("independent-review pointer contains malformed identity or hash fields")
    return {"comment_id": comment_id, "sha256": fields["SHA-256"], "head": fields["HEAD"],
            "contract_comment_id": contract_id, "contract_sha256": fields["Contract SHA-256"],
            "checklist_sha256": fields["Checklist SHA-256"], "fresh_context": True}


def _with_pr_review_pointer(body: str, value: dict[str, Any], comment_id: int, digest: str) -> str:
    block = [f"## {PR_REVIEW_POINTER_TITLE}", "", f"Comment ID: {comment_id}", f"SHA-256: {digest}",
             f"HEAD: {value['head']}", f"Contract Comment ID: {value['contract_comment_id']}",
             f"Contract SHA-256: {value['contract_sha256']}", f"Checklist SHA-256: {value['checklist_sha256']}",
             "Fresh Context: true"]
    lines = (body or "").splitlines()
    matches = [i for i, line in enumerate(lines) if re.fullmatch(r"##\s+Agent Independent Review\s*", line, re.I)]
    if not matches:
        base = (body or "").rstrip()
        return (base + "\n\n" if base else "") + "\n".join(block) + "\n"
    if len(matches) != 1:
        raise ReviewError("PR body must contain at most one Agent Independent Review pointer")
    start = matches[0]
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^#{1,2}\s+", lines[i])), len(lines))
    return "\n".join(lines[:start] + block + lines[end:]).rstrip() + "\n"


def publish_pr_review(repo: Path, issue: int, pr: int, gh: GitHub, source: Path | None = None) -> dict[str, Any]:
    path = source or pr_review_path(repo, issue, pr)
    value = _read_pr_review(path, issue, pr, allow_pending=False)
    if value["fresh_context"] is not True:
        raise ReviewError("independent review requires fresh_context: true attestation")
    _issue_obj, pull, surface, head = _pr_review_current(issue, pr, gh)
    if not _pr_review_matches(value, head, surface):
        raise ReviewError("independent-review draft is stale for current HEAD, contract, or checklist")
    _pr_review_pointer(pull.get("body") or "")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    comment_body = (f"<!-- agent-pr-review:v1 issue={issue} pr={pr} head={head} "
                    f"contract_comment={surface['contract_comment_id']} contract={surface['contract_sha256']} "
                    f"checklist={surface['checklist_sha256']} fresh_context=true sha256={digest} -->\n\n{payload}")
    if _review_utf8_size(comment_body, "independent-review comment") > 65536 or REVIEW_SECRET.search(comment_body):
        raise ReviewError("independent-review comment is oversized or contains credential material")
    created = gh.create_pull_comment(pr, comment_body)
    try:
        comment_id = int(created["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewError("independent-review comment creation returned an invalid ID") from exc
    try:
        named = gh.pull_comment(comment_id)
    except GitHubError as exc:
        raise ReviewError(f"independent-review comment {comment_id} could not be read back by ID") from exc
    if (not isinstance(named, dict) or named.get("id") != comment_id
            or named.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}"
            or named.get("body") != comment_body):
        raise ReviewError("independent-review named readback differs from submitted bytes")
    _latest_issue, latest_pull, latest_surface, latest_head = _pr_review_current(issue, pr, gh)
    if latest_head != head or not _pr_review_matches(value, latest_head, latest_surface):
        raise ReviewError("Issue contract, checklist, or PR HEAD changed while publishing independent review")
    updated = _with_pr_review_pointer(latest_pull.get("body") or "", value, comment_id, digest)
    gh.update_pull(pr, updated)
    readback = gh.pull(pr)
    expected = {"comment_id": comment_id, "sha256": digest, "head": head,
                "contract_comment_id": surface["contract_comment_id"],
                "contract_sha256": surface["contract_sha256"],
                "checklist_sha256": surface["checklist_sha256"], "fresh_context": True}
    if _pr_review_pointer(readback.get("body") or "") != expected:
        raise ReviewError("PR independent-review pointer failed readback verification")
    return {**expected, "contract_section_count": len(surface["contract_sections"]),
            "item_count": len(surface["items"]), "finding_count": len(value["findings"]),
            "blocking_finding_count": sum(bool(finding["blocking"]) for finding in value["findings"])}


def validate_public_pr_review(issue: int, pr: int, gh: GitHub, *,
                              issue_obj: dict[str, Any] | None = None,
                              pull: dict[str, Any] | None = None) -> dict[str, Any]:
    issue_obj, pull, surface, current_head = _pr_review_current(issue, pr, gh)
    pointer = _pr_review_pointer(pull.get("body") or "")
    if pointer is None:
        raise ReviewError("PR has no Agent Independent Review pointer")
    try:
        comment = gh.pull_comment(pointer["comment_id"])
    except GitHubError as exc:
        raise ReviewError("named independent-review comment could not be read") from exc
    if (not isinstance(comment, dict) or comment.get("id") != pointer["comment_id"]
            or comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}"):
        raise ReviewError("named independent-review comment belongs to a different PR")
    body = comment.get("body", "")
    if not isinstance(body, str) or _review_utf8_size(body, "named independent-review comment") > 65536 or REVIEW_SECRET.search(body):
        raise ReviewError("named independent-review comment is oversized or contains credential material")
    header, separator, payload_text = body.partition("\n\n")
    match = PR_REVIEW_HEADER.fullmatch(header)
    if not separator or match is None or int(match.group(1)) != issue or int(match.group(2)) != pr:
        raise ReviewError("named independent-review comment metadata is malformed")
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    if pointer["sha256"] != digest or match.group(7) != digest:
        raise ReviewError("independent-review pointer and comment SHA-256 disagree")
    try:
        value = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ReviewError("named independent-review payload is invalid JSON") from exc
    _validate_pr_review_data(value, issue, pr, allow_pending=False)
    metadata = {"head": match.group(3), "contract_comment_id": int(match.group(4)),
                "contract_sha256": match.group(5), "checklist_sha256": match.group(6),
                "fresh_context": True}
    expected = {key: value[key] for key in ("head", "contract_comment_id", "contract_sha256", "checklist_sha256")}
    expected["fresh_context"] = value["fresh_context"]
    expected_pointer = {"comment_id": pointer["comment_id"], "sha256": digest, **expected}
    if metadata != expected or pointer != expected_pointer:
        raise ReviewError("independent-review pointer, comment metadata, and payload disagree")
    stale_reasons = []
    if value["head"] != current_head:
        stale_reasons.append("PR HEAD changed")
    if (value["contract_comment_id"] != surface["contract_comment_id"]
            or value["contract_sha256"] != surface["contract_sha256"]
            or _unit_identities(value["contract_sections"]) != _unit_identities(surface["contract_sections"])):
        stale_reasons.append("approved Implementation Contract changed")
    if (value["checklist_sha256"] != surface["checklist_sha256"]
            or [(item["id"], item["text"]) for item in value["items"]]
            != [(item["id"], item["text"]) for item in surface["items"]]):
        stale_reasons.append("effective Reviewer Checklist changed")
    contract_sections = value["contract_sections"]
    findings = value["findings"]
    all_units_pass = all(section["result"] == "pass" for section in contract_sections)
    no_checklist_fail = not any(item["result"] == "fail" for item in value["items"])
    blocking = [finding for finding in findings if finding["blocking"]]
    passed = not stale_reasons and all_units_pass and no_checklist_fail and not blocking
    return {"comment_id": pointer["comment_id"], "sha256": digest, "head": value["head"],
            "contract_comment_id": value["contract_comment_id"],
            "current_contract_comment_id": surface["contract_comment_id"],
            "contract_sha256": value["contract_sha256"],
            "current_contract_sha256": surface["contract_sha256"],
            "checklist_sha256": value["checklist_sha256"], "fresh_context": value["fresh_context"],
            "contract_units_pass": all_units_pass, "checklist_fail_count": sum(item["result"] == "fail" for item in value["items"]),
            "contract_unit_fail_count": sum(section["result"] == "fail" for section in contract_sections),
            "contract_unit_untested_count": sum(section["result"] == "untested" for section in contract_sections),
            "finding_count": len(findings), "blocking_finding_count": len(blocking),
            "blocking_findings": [{"id": finding["id"], "severity": finding["severity"],
                                   "title": finding["title"][:200]} for finding in blocking[:10]],
            "stale": bool(stale_reasons), "stale_reasons": stale_reasons, "passed": passed,
            "review": value}
