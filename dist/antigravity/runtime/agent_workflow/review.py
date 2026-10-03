"""Checklist extraction, self-review drafts, and current-HEAD public review records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import ContractError, parse_comment, parse_pointer
from .documents import without_fenced_blocks
from .github import GitHub


class ReviewError(ValueError):
    pass


CANONICAL_BEGIN = "<!-- AGENT_REVIEWER_CHECKLIST_V1 -->"
CANONICAL_END = "<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->"
CHECK = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s+(.+?)\s*$")
REVIEW_HEADER = re.compile(r"^<!-- agent-self-review:v1 issue=(\d+) pr=(\d+) head=([0-9a-f]+) checklist=([0-9a-f]{64}) -->$")
RESULTS = {"pass", "fail", "untested"}
REVIEW_SECRET = re.compile(r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{16,}|bearer\s+[A-Za-z0-9._~+/-]{16,})")


def _heading_section(text: str, title: str) -> str | None:
    lines = text.splitlines()
    clean_lines = without_fenced_blocks(text).splitlines()
    start = None
    level = 0
    for i, line in enumerate(clean_lines):
        m = re.match(r"^(#{1,6})\s*(?:\d+[.)]?\s*)?Reviewer Checklist(?:\s*[（(][^()（）]*[)）])?\s*#*\s*$", line, re.I)
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


def effective_checklist(issue_number: int, issue_body: str, gh: GitHub) -> tuple[list[dict[str, str]], str]:
    contract_id, contract_sha = parse_pointer(issue_body)
    comment = gh.issue_comment(issue_number, contract_id)
    if comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{issue_number}":
        raise ReviewError("Implementation Contract comment is associated with a different Issue")
    contract, actual_sha = parse_comment(comment.get("body", ""), issue_number)
    if actual_sha != contract_sha:
        raise ReviewError("Implementation Contract pointer and checklist source SHA disagree")
    contract_text = contract.decode("utf-8")
    c_items = _extract_items(contract_text)
    i_items = _extract_items(issue_body or "")
    items = ([{"id": f"C{n:03d}", "text": value} for n, value in enumerate(c_items, 1)] +
             [{"id": f"I{n:03d}", "text": value} for n, value in enumerate(i_items, 1)])
    if not items:
        raise ReviewError("effective Reviewer Checklist is empty")
    canonical = json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return items, hashlib.sha256(canonical).hexdigest()


def review_path(repo: Path, issue: int, pr: int) -> Path:
    return repo / ".agent-state" / "issues" / str(issue) / f"self-review-pr-{pr}.json"


def _write_review(path: Path, draft: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(draft, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.",
                                         suffix=".tmp", delete=False) as stream:
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


def prepare_review(repo: Path, issue: int, pr: int, gh: GitHub) -> dict[str, Any]:
    issue_obj = gh.issue(issue)
    if issue_obj.get("number") != issue or issue_obj.get("repository_url") != f"https://api.github.com/repos/{gh.repo}":
        raise ReviewError("Issue identity does not match configured repository")
    pull = gh.pull(pr)
    if pull.get("number") != pr or pull.get("base", {}).get("repo", {}).get("full_name", "").lower() != gh.repo.lower():
        raise ReviewError("PR identity does not match configured repository")
    head = pull.get("head", {}).get("sha")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{7,40}", head):
        raise ReviewError("PR current HEAD is missing or malformed")
    items, list_sha = effective_checklist(issue, issue_obj.get("body") or "", gh)
    draft = {"schema_version": 1, "issue": issue, "pr": pr, "head": head,
             "checklist_sha256": list_sha,
             "items": [{**item, "result": "pending", "evidence": ""} for item in items]}
    path = review_path(repo, issue, pr)
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if isinstance(previous, dict) and previous.get("head") == head and previous.get("checklist_sha256") == list_sha:
            return {"path": str(path), "head": head, "checklist_sha256": list_sha,
                    "items": len(items), "reused": True}
        previous_bytes = path.read_bytes()
        backup_sha = hashlib.sha256(previous_bytes).hexdigest()
        backup = path.with_name(f"{path.stem}.{backup_sha}.stale.json")
        if not backup.exists():
            backup.write_bytes(previous_bytes)
    _write_review(path, draft)
    return {"path": str(path), "head": head, "checklist_sha256": list_sha, "items": len(items)}


def load_review(path: Path) -> dict[str, Any]:
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"could not read self-review JSON: {exc}") from exc
    if not isinstance(draft, dict) or draft.get("schema_version") != 1 or not isinstance(draft.get("items"), list):
        raise ReviewError("self-review draft has invalid schema")
    if not re.fullmatch(r"[0-9a-f]{7,40}", str(draft.get("head", ""))):
        raise ReviewError("self-review draft has invalid HEAD")
    if not re.fullmatch(r"[0-9a-f]{64}", str(draft.get("checklist_sha256", ""))):
        raise ReviewError("self-review draft has invalid checklist SHA")
    seen: set[str] = set()
    for item in draft["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in seen:
            raise ReviewError("self-review contains malformed or duplicate checklist item")
        seen.add(item["id"])
        if item.get("result") not in RESULTS or not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            raise ReviewError(f"{item.get('id', 'item')}: result must be pass/fail/untested with concrete evidence")
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ReviewError("self-review item text is empty")
    return _validate_review_data(draft)


def _validate_review_data(draft: Any) -> dict[str, Any]:
    if not isinstance(draft, dict) or draft.get("schema_version") != 1 or not isinstance(draft.get("items"), list) or not draft["items"]:
        raise ReviewError("self-review payload has invalid schema")
    if not re.fullmatch(r"[0-9a-f]{7,40}", str(draft.get("head", ""))) or not re.fullmatch(r"[0-9a-f]{64}", str(draft.get("checklist_sha256", ""))):
        raise ReviewError("self-review payload has invalid HEAD or checklist SHA")
    seen: set[str] = set()
    for item in draft["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in seen:
            raise ReviewError("self-review payload contains malformed or duplicate checklist item")
        seen.add(item["id"])
        if not isinstance(item.get("result"), str) or item["result"] not in RESULTS or not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            raise ReviewError(f"{item.get('id', 'item')}: result must be pass/fail/untested with concrete evidence")
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ReviewError("self-review item text is empty")
        if REVIEW_SECRET.search(item["text"] + "\n" + item["evidence"]):
            raise ReviewError(f"{item['id']}: self-review contains credential material")
    return draft


def _review_payload(draft: dict[str, Any]) -> str:
    return json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=2)


def _pointer(pr_body: str) -> tuple[int, str, str, str]:
    lines = (pr_body or "").splitlines()
    if len(re.findall(r"^##\s+Agent Self-Review\s*$", pr_body or "", re.M | re.I)) != 1:
        raise ReviewError("PR body must contain exactly one ## Agent Self-Review pointer section")
    for i, line in enumerate(lines):
        if re.match(r"^##\s+Agent Self-Review\s*$", line, re.I):
            fields = {}
            for entry in lines[i + 1:]:
                if re.match(r"^#{1,6}\s+", entry):
                    break
                if ": " in entry:
                    key, val = entry.split(": ", 1)
                    fields[key.strip()] = val.strip()
            try:
                cid = int(fields["Comment ID"])
                sha = fields["SHA-256"]
                head = fields["HEAD"]
                checklist = fields["Checklist SHA-256"]
            except (KeyError, ValueError) as exc:
                raise ReviewError("PR review pointer is malformed") from exc
            if not re.fullmatch(r"[0-9a-f]{64}", sha) or not re.fullmatch(r"[0-9a-f]{7,40}", head) or not re.fullmatch(r"[0-9a-f]{64}", checklist):
                raise ReviewError("PR review pointer contains malformed hash/HEAD")
            return cid, sha, head, checklist
    raise ReviewError("PR has no Agent Self-Review pointer")


def _with_pointer(body: str, comment_id: int, sha: str, head: str, checklist_sha: str) -> str:
    title = "## Agent Self-Review"
    block = [title, "", f"Comment ID: {comment_id}", f"SHA-256: {sha}", f"HEAD: {head}",
             f"Checklist SHA-256: {checklist_sha}"]
    lines = (body or "").splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^##\s+Agent Self-Review\s*$", line, re.I)), None)
    if start is None:
        base = (body or "").rstrip()
        return (base + "\n\n" if base else "") + "\n".join(block) + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,2}\s+", lines[i]):
            end = i
            break
    return "\n".join(lines[:start] + block + lines[end:]).rstrip() + "\n"


def publish_review(repo: Path, issue: int, pr: int, gh: GitHub, draft_path: Path | None = None) -> dict[str, Any]:
    path = draft_path or review_path(repo, issue, pr)
    draft = load_review(path)
    if draft.get("issue") != issue or draft.get("pr") != pr:
        raise ReviewError("self-review draft Issue/PR identity mismatch")
    issue_obj = gh.issue(issue)
    pull = gh.pull(pr)
    if pull.get("base", {}).get("repo", {}).get("full_name", "").lower() != gh.repo.lower():
        raise ReviewError("PR repository identity mismatch")
    current_head = pull.get("head", {}).get("sha")
    items, checklist_sha = effective_checklist(issue, issue_obj.get("body") or "", gh)
    if draft["head"] != current_head or draft["checklist_sha256"] != checklist_sha:
        raise ReviewError("self-review draft is stale: PR HEAD or effective checklist changed")
    if [(x["id"], x["text"]) for x in draft["items"]] != [(x["id"], x["text"]) for x in items]:
        raise ReviewError("self-review items differ from the current effective checklist")
    payload = _review_payload(draft)
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    comment_body = f"<!-- agent-self-review:v1 issue={issue} pr={pr} head={current_head} checklist={checklist_sha} -->\n\n{payload}"
    if len(comment_body) > 65536:
        raise ReviewError("self-review comment exceeds 65536 characters")
    created = gh.create_pull_comment(pr, comment_body)
    cid = int(created["id"])
    comment = gh.pull_comment(cid)
    if comment.get("id") != cid or comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}" or comment.get("body") != comment_body:
        raise ReviewError("published self-review comment failed association/body readback")
    latest = gh.pull(pr)
    if latest.get("head", {}).get("sha") != current_head:
        raise ReviewError("PR HEAD changed while publishing self-review")
    updated = _with_pointer(latest.get("body") or "", cid, sha, current_head, checklist_sha)
    gh.update_pull(pr, updated)
    readback = gh.pull(pr)
    pointer = _pointer(readback.get("body") or "")
    if pointer != (cid, sha, current_head, checklist_sha):
        raise ReviewError("PR self-review pointer failed readback verification")
    return {"comment_id": cid, "sha256": sha, "head": current_head, "checklist_sha256": checklist_sha}


def validate_public_review(issue: int, pr: int, gh: GitHub) -> dict[str, Any]:
    pull = gh.pull(pr)
    cid, expected_sha, reviewed_head, checklist_sha = _pointer(pull.get("body") or "")
    # Only fetch the named comment.
    comment = gh.pull_comment(cid)
    if comment.get("id") != cid or comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}":
        raise ReviewError("published review comment belongs to a different PR")
    body = comment.get("body", "")
    header, sep, payload_text = body.partition("\n\n")
    match = REVIEW_HEADER.match(header)
    if not sep or not match or int(match.group(1)) != issue or int(match.group(2)) != pr:
        raise ReviewError("named public review comment has invalid metadata")
    payload_sha = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    if payload_sha != expected_sha or match.group(3) != reviewed_head or match.group(4) != checklist_sha:
        raise ReviewError("published review pointer and comment metadata disagree")
    try:
        review = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ReviewError("published review body is invalid JSON") from exc
    if review.get("issue") != issue or review.get("pr") != pr or review.get("head") != reviewed_head or review.get("checklist_sha256") != checklist_sha:
        raise ReviewError("published review payload identity is inconsistent")
    _validate_review_data(review)
    current_head = pull.get("head", {}).get("sha")
    return {"comment_id": cid, "sha256": expected_sha, "head": reviewed_head,
            "checklist_sha256": checklist_sha, "stale": current_head != reviewed_head,
            "current_head": current_head, "review": review}
