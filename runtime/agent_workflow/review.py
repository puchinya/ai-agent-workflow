"""Checklist extraction, full-contract self-review, and current-HEAD records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import classify_reviewer_checklist_h2, parse_comment, parse_pointer
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
    return [m.group(1).strip() for line in section.splitlines() if (m := CHECK.match(line))]


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
    first_reviewable = next(
        (heading.start for index, heading in enumerate(headings) if index not in excluded_checklist),
        len(contract),
    )
    preamble = contract[:first_reviewable]
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
