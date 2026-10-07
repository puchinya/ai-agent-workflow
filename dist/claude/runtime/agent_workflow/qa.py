"""Current-HEAD QA records, validation, and immutable PR evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import OBVIOUS_SECRET
from .github import GitHub, GitHubError
from .review import ReviewError, load_review_surface


class QAError(ValueError):
    pass


def _utf8_size(value: str, where: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise QAError(f"{where} contains invalid Unicode text") from exc


QA_RESULTS = {"pending", "pass", "fail", "untested"}
PUBLIC_RESULTS = {"pass", "fail", "untested", "not_applicable"}
MAX_EVIDENCE_BYTES = 16 * 1024
MAX_QA_BYTES = 65536
POINTER_TITLE = "Agent QA"
HEADER = re.compile(
    r"^<!-- agent-qa:v1 issue=(\d+) pr=(\d+) head=([0-9a-f]{40}) "
    r"contract_comment=(\d+) contract=([0-9a-f]{64}) mode=(required|not_applicable) "
    r"result=(pass|fail|untested|not_applicable) sha256=([0-9a-f]{64}) -->$"
)


def qa_path(repo: Path, issue: int, pr: int) -> Path:
    return repo / ".agent-state" / "issues" / str(issue) / f"qa-pr-{pr}.json"


def _atomic_write(path: Path, data: bytes) -> None:
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


def _issue_identity(issue_obj: Any, issue: int, gh: GitHub) -> None:
    if (not isinstance(issue_obj, dict) or type(issue_obj.get("number")) is not int
            or issue_obj.get("number") != issue
            or issue_obj.get("repository_url") != f"https://api.github.com/repos/{gh.repo}"
            or issue_obj.get("pull_request") or issue_obj.get("state") != "open"):
        raise QAError("Issue identity must match the configured repository and remain open")


def _pull_identity(pull: Any, issue: int, pr: int, gh: GitHub) -> str:
    if not isinstance(pull, dict) or type(pull.get("number")) is not int or pull.get("number") != pr:
        raise QAError("PR identity does not match the requested PR")
    base, head = pull.get("base"), pull.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    if (not isinstance(base_repo, dict) or not isinstance(head_repo, dict)
            or str(base_repo.get("full_name", "")).casefold() != gh.repo.casefold()
            or str(head_repo.get("full_name", "")).casefold() != gh.repo.casefold()):
        raise QAError("PR head and base must belong to the configured repository")
    if pull.get("state") != "open" or pull.get("draft") is not False or pull.get("merged") is True:
        raise QAError("QA requires an open, non-draft PR")
    body = pull.get("body")
    if not isinstance(body, str) or not re.search(rf"(?im)^\s*closes\s+#{issue}\s*$", body):
        raise QAError(f"PR body must contain a standalone Closes #{issue} line")
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise QAError("PR HEAD must be a full 40-character SHA")
    return sha


def _current_state(issue: int, pr: int, gh: GitHub,
                   issue_obj: dict[str, Any] | None = None,
                   pull: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    issue_obj = issue_obj if issue_obj is not None else gh.issue(issue)
    pull = pull if pull is not None else gh.pull(pr)
    _issue_identity(issue_obj, issue, gh)
    head = _pull_identity(pull, issue, pr, gh)
    try:
        surface = load_review_surface(issue, issue_obj.get("body") or "", gh)
    except ReviewError as exc:
        raise QAError(f"could not validate approved Implementation Contract: {exc}") from exc
    return issue_obj, pull, surface, head


def _write_draft(path: Path, draft: dict[str, Any]) -> None:
    try:
        data = (json.dumps(draft, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise QAError("QA draft contains invalid Unicode text") from exc
    if len(data) > MAX_QA_BYTES:
        raise QAError("QA draft exceeds 65536 bytes")
    _atomic_write(path, data)


def prepare_qa(repo: Path, issue: int, pr: int, gh: GitHub) -> dict[str, Any]:
    issue_obj, _pull, surface, head = _current_state(issue, pr, gh)
    draft = {
        "schema_version": 1,
        "issue": issue,
        "pr": pr,
        "head": head,
        "contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": surface["contract_sha256"],
        "mode": "required",
        "reason": None,
        "cases": [{"name": "", "action": "", "expected": "", "result": "pending", "evidence": ""}],
    }
    path = qa_path(repo, issue, pr)
    if path.exists():
        try:
            old = path.read_bytes()
        except OSError as exc:
            raise QAError(f"could not preserve prior QA draft: {exc}") from exc
        try:
            previous = json.loads(old.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            previous = None
        if (isinstance(previous, dict) and previous.get("schema_version") == 1
                and previous.get("issue") == issue and previous.get("pr") == pr
                and previous.get("head") == head
                and previous.get("contract_comment_id") == surface["contract_comment_id"]
                and previous.get("contract_sha256") == surface["contract_sha256"]):
            _validate_qa_data(previous, issue, pr, allow_pending=True)
            return {"path": str(path), "head": head, "mode": previous.get("mode"),
                    "case_count": len(previous.get("cases", [])) if isinstance(previous.get("cases"), list) else 0,
                    "reused": True}
        digest = hashlib.sha256(old).hexdigest()
        backup = path.with_name(f"{path.stem}.{digest}.stale.json")
        if not backup.exists():
            _atomic_write(backup, old)
    _write_draft(path, draft)
    return {"path": str(path), "head": head, "mode": "required", "case_count": 1, "reused": False}


def _validate_qa_data(value: Any, issue: int, pr: int, *, allow_pending: bool) -> dict[str, Any]:
    required_keys = {"schema_version", "issue", "pr", "head", "contract_comment_id",
                     "contract_sha256", "mode", "reason", "cases"}
    if not isinstance(value, dict) or set(value) != required_keys or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise QAError("QA payload has an invalid or unsupported schema")
    if (type(value.get("issue")) is not int or value["issue"] != issue
            or type(value.get("pr")) is not int or value["pr"] != pr):
        raise QAError("QA payload Issue/PR identity mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", str(value.get("head", ""))):
        raise QAError("QA payload HEAD is malformed")
    if type(value.get("contract_comment_id")) is not int or value["contract_comment_id"] < 1:
        raise QAError("QA payload contract comment ID is malformed")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("contract_sha256", ""))):
        raise QAError("QA payload contract SHA-256 is malformed")
    mode = value.get("mode")
    cases = value.get("cases")
    if not isinstance(mode, str) or mode not in {"required", "not_applicable"} or not isinstance(cases, list):
        raise QAError("QA mode or cases are malformed")
    reason = value.get("reason")
    if mode == "not_applicable":
        if cases:
            raise QAError("not_applicable QA must contain zero cases")
        if not isinstance(reason, str) or len(reason.strip()) < 16 or reason.strip().casefold() in {
            "n/a", "na", "not applicable", "tbd", "todo", "pending", "none",
        }:
            raise QAError("not_applicable QA requires a concrete reason of at least 16 characters")
    elif reason is not None:
        raise QAError("required QA must not contain a not_applicable reason")
    if mode == "required" and not cases:
        raise QAError("required QA must contain at least one case")
    seen: set[str] = set()
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict) or set(case) != {"name", "action", "expected", "result", "evidence"}:
            raise QAError(f"QA case {index} has an invalid schema")
        result = case.get("result")
        allowed_results = QA_RESULTS if allow_pending else {"pass", "fail", "untested"}
        if not isinstance(result, str) or result not in allowed_results:
            raise QAError(f"QA case {index} result must be pass, fail, or untested")
        for field, max_bytes in (("name", 256), ("action", 4096), ("expected", 4096), ("evidence", MAX_EVIDENCE_BYTES)):
            text = case.get(field)
            if not isinstance(text, str) or _utf8_size(text, f"QA case {index} {field}") > max_bytes:
                raise QAError(f"QA case {index} {field} is malformed or oversized")
            if (OBVIOUS_SECRET.search(text) or (text and not text.strip())):
                raise QAError(f"QA case {index} {field} is empty or contains credential-like material")
        if result == "pending" and allow_pending:
            continue
        if any(not case[field].strip() for field in ("name", "action", "expected", "evidence")):
            raise QAError(f"QA case {index} requires name, action, expected, and concrete evidence")
        normalized_name = case["name"].strip().casefold()
        if normalized_name in seen:
            raise QAError("QA case names must be unique")
        seen.add(normalized_name)
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    if _utf8_size(serialized, "QA payload") > MAX_QA_BYTES or OBVIOUS_SECRET.search(serialized):
        raise QAError("QA payload is oversized or contains credential-like material")
    return value


def _read_qa(path: Path, issue: int, pr: int, *, allow_pending: bool) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QAError(f"could not read QA JSON: {exc}") from exc
    if len(raw) > MAX_QA_BYTES:
        raise QAError("QA draft exceeds 65536 bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QAError("QA draft must be valid UTF-8 JSON") from exc
    return _validate_qa_data(value, issue, pr, allow_pending=allow_pending)


def _current_matches(qa: dict[str, Any], head: str, surface: dict[str, Any]) -> bool:
    return (qa["head"] == head and qa["contract_comment_id"] == surface["contract_comment_id"]
            and qa["contract_sha256"] == surface["contract_sha256"])


def validate_qa(repo: Path, issue: int, pr: int, gh: GitHub, source: Path | None = None) -> dict[str, Any]:
    path = source or qa_path(repo, issue, pr)
    qa = _read_qa(path, issue, pr, allow_pending=False)
    _issue, _pull, surface, head = _current_state(issue, pr, gh)
    stale = not _current_matches(qa, head, surface)
    result = _qa_result(qa)
    passed = not stale and result in {"pass", "not_applicable"}
    return {"valid": True, "passed": passed, "stale": stale,
            "stale_reasons": (["PR HEAD or approved contract changed"] if stale else []),
            "head": qa["head"], "mode": qa["mode"], "result": result,
            "case_count": len(qa["cases"])}


def _qa_result(qa: dict[str, Any]) -> str:
    if qa["mode"] == "not_applicable":
        return "not_applicable"
    results = [case["result"] for case in qa["cases"]]
    if any(value == "fail" for value in results):
        return "fail"
    if any(value == "untested" for value in results):
        return "untested"
    return "pass"


def _pointer(body: str) -> dict[str, Any] | None:
    heading = re.compile(r"^##\s+Agent QA\s*$", re.I | re.M)
    matches = list(heading.finditer(body or ""))
    if not matches:
        return None
    if len(matches) != 1:
        raise QAError("PR body must contain at most one Agent QA pointer")
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
                raise QAError("QA pointer contains duplicate fields")
            fields[key] = value.strip()
    if set(fields) != {"Comment ID", "SHA-256", "HEAD", "Contract Comment ID", "Contract SHA-256", "Mode", "Result"}:
        raise QAError("QA pointer is malformed")
    try:
        comment_id = int(fields["Comment ID"])
        contract_id = int(fields["Contract Comment ID"])
    except ValueError as exc:
        raise QAError("QA pointer contains a malformed comment ID") from exc
    if (comment_id < 1 or contract_id < 1
            or not re.fullmatch(r"[0-9a-f]{64}", fields["SHA-256"])
            or not re.fullmatch(r"[0-9a-f]{40}", fields["HEAD"])
            or not re.fullmatch(r"[0-9a-f]{64}", fields["Contract SHA-256"])
            or fields["Mode"] not in {"required", "not_applicable"}
            or fields["Result"] not in PUBLIC_RESULTS):
        raise QAError("QA pointer contains malformed identity or hash fields")
    return {"comment_id": comment_id, "sha256": fields["SHA-256"], "head": fields["HEAD"],
            "contract_comment_id": contract_id, "contract_sha256": fields["Contract SHA-256"],
            "mode": fields["Mode"], "result": fields["Result"]}


def _with_pointer(body: str, qa: dict[str, Any], comment_id: int, digest: str) -> str:
    block = [f"## {POINTER_TITLE}", "", f"Comment ID: {comment_id}", f"SHA-256: {digest}",
             f"HEAD: {qa['head']}", f"Contract Comment ID: {qa['contract_comment_id']}",
             f"Contract SHA-256: {qa['contract_sha256']}", f"Mode: {qa['mode']}",
             f"Result: {_qa_result(qa)}"]
    lines = (body or "").splitlines()
    matches = [i for i, line in enumerate(lines) if re.fullmatch(r"##\s+Agent QA\s*", line, re.I)]
    if not matches:
        base = (body or "").rstrip()
        return (base + "\n\n" if base else "") + "\n".join(block) + "\n"
    if len(matches) != 1:
        raise QAError("PR body must contain at most one Agent QA pointer")
    start = matches[0]
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^#{1,2}\s+", lines[i])), len(lines))
    return "\n".join(lines[:start] + block + lines[end:]).rstrip() + "\n"


def publish_qa(repo: Path, issue: int, pr: int, gh: GitHub, source: Path | None = None) -> dict[str, Any]:
    path = source or qa_path(repo, issue, pr)
    qa = _read_qa(path, issue, pr, allow_pending=False)
    issue_obj, pull, surface, head = _current_state(issue, pr, gh)
    if not _current_matches(qa, head, surface):
        raise QAError("QA draft is stale for current PR HEAD or approved Implementation Contract")
    _pointer(pull.get("body") or "")
    result = _qa_result(qa)
    payload = json.dumps(qa, ensure_ascii=False, sort_keys=True, indent=2)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    comment_body = (
        f"<!-- agent-qa:v1 issue={issue} pr={pr} head={head} "
        f"contract_comment={surface['contract_comment_id']} contract={surface['contract_sha256']} "
        f"mode={qa['mode']} result={result} sha256={digest} -->\n\n{payload}"
    )
    if _utf8_size(comment_body, "QA comment") > MAX_QA_BYTES:
        raise QAError("QA comment exceeds 65536 bytes")
    created = gh.create_pull_comment(pr, comment_body)
    try:
        comment_id = int(created["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QAError("QA comment creation returned an invalid ID") from exc
    try:
        named = gh.pull_comment(comment_id)
    except GitHubError as exc:
        raise QAError(f"QA comment {comment_id} could not be read back by ID") from exc
    if (not isinstance(named, dict) or named.get("id") != comment_id
            or named.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}"
            or named.get("body") != comment_body):
        raise QAError("QA comment named readback differs from submitted bytes")
    _latest_issue, latest_pull, latest_surface, latest_head = _current_state(issue, pr, gh)
    if latest_head != head or not _current_matches(qa, latest_head, latest_surface):
        raise QAError("Issue contract or PR HEAD changed while publishing QA")
    updated = _with_pointer(latest_pull.get("body") or "", qa, comment_id, digest)
    gh.update_pull(pr, updated)
    readback_pull = gh.pull(pr)
    expected_pointer = {"comment_id": comment_id, "sha256": digest, "head": head,
                        "contract_comment_id": surface["contract_comment_id"],
                        "contract_sha256": surface["contract_sha256"], "mode": qa["mode"], "result": result}
    if _pointer(readback_pull.get("body") or "") != expected_pointer:
        raise QAError("PR QA pointer failed readback verification")
    return {"comment_id": comment_id, "sha256": digest, "head": head,
            "contract_comment_id": surface["contract_comment_id"],
            "contract_sha256": surface["contract_sha256"], "mode": qa["mode"],
            "result": result, "case_count": len(qa["cases"])}


def validate_public_qa(issue: int, pr: int, gh: GitHub, *,
                       issue_obj: dict[str, Any] | None = None,
                       pull: dict[str, Any] | None = None) -> dict[str, Any]:
    issue_obj, pull, surface, current_head = _current_state(issue, pr, gh, issue_obj, pull)
    pointer = _pointer(pull.get("body") or "")
    if pointer is None:
        raise QAError("PR has no Agent QA pointer")
    try:
        comment = gh.pull_comment(pointer["comment_id"])
    except GitHubError as exc:
        raise QAError("named QA comment could not be read") from exc
    if (not isinstance(comment, dict) or comment.get("id") != pointer["comment_id"]
            or comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}"):
        raise QAError("named QA comment belongs to a different PR")
    body = comment.get("body", "")
    if not isinstance(body, str) or _utf8_size(body, "named QA comment") > MAX_QA_BYTES or OBVIOUS_SECRET.search(body):
        raise QAError("named QA comment is oversized or contains credential-like material")
    header, separator, payload_text = body.partition("\n\n")
    match = HEADER.fullmatch(header)
    if not separator or match is None or int(match.group(1)) != issue or int(match.group(2)) != pr:
        raise QAError("named QA comment metadata is malformed")
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    if pointer["sha256"] != digest or match.group(8) != digest:
        raise QAError("QA pointer and comment SHA-256 disagree")
    try:
        qa = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise QAError("named QA payload is invalid JSON") from exc
    _validate_qa_data(qa, issue, pr, allow_pending=False)
    result = _qa_result(qa)
    metadata = {"head": match.group(3), "contract_comment_id": int(match.group(4)),
                "contract_sha256": match.group(5), "mode": match.group(6), "result": match.group(7)}
    expected = {"head": qa["head"], "contract_comment_id": qa["contract_comment_id"],
                "contract_sha256": qa["contract_sha256"], "mode": qa["mode"], "result": result}
    expected_pointer = {"comment_id": pointer["comment_id"], "sha256": digest, **expected}
    if metadata != expected or pointer != expected_pointer:
        raise QAError("QA pointer, comment metadata, and payload disagree")
    stale_reasons = []
    if qa["head"] != current_head:
        stale_reasons.append("PR HEAD changed")
    if (qa["contract_comment_id"] != surface["contract_comment_id"]
            or qa["contract_sha256"] != surface["contract_sha256"]):
        stale_reasons.append("approved Implementation Contract comment/SHA changed")
    passed = not stale_reasons and result in {"pass", "not_applicable"}
    return {"qa": qa, "comment_id": pointer["comment_id"], "sha256": digest,
            "result": result, "passed": passed, "stale": bool(stale_reasons),
            "stale_reasons": stale_reasons, "current_head": current_head,
            "current_contract_comment_id": surface["contract_comment_id"],
            "current_contract_sha256": surface["contract_sha256"]}
