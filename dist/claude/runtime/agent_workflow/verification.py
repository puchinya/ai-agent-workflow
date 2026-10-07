"""Exact-HEAD final-verification receipts and public PR pointers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .context import ContextError, affected_components
from .github import GitHub, GitHubError
from .git import GitLifecycleError, local_head_sha, require_clean_worktree
from .process import run_command
from .profile import build_hook_plan, load_profile, normalize_arch, normalize_host
from .review import load_review_surface


class VerificationError(ValueError):
    pass


HEADER = re.compile(
    r"^<!-- agent-final-verification:v1 issue=(\d+) pr=(\d+) head=([0-9a-f]{40}) "
    r"contract_comment=(\d+) contract=([0-9a-f]{64}) plan=([0-9a-f]{64}) "
    r"result=(pass|partial|empty) sha256=([0-9a-f]{64}) -->$"
)
POINTER_TITLE = "Agent Final Verification"
RECEIPT_RESULTS = {"pass", "partial", "empty"}
SECRET = re.compile(
    r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{16,}|bearer\s+[A-Za-z0-9._~+/-]{16,})"
)


def _verify_issue(issue_obj: Any, issue: int, gh: GitHub) -> None:
    if (not isinstance(issue_obj, dict) or type(issue_obj.get("number")) is not int
            or issue_obj.get("number") != issue
            or issue_obj.get("repository_url") != f"https://api.github.com/repos/{gh.repo}"
            or issue_obj.get("pull_request") or issue_obj.get("state") != "open"):
        raise VerificationError("Issue identity must match the configured repository and remain open")


def _verify_pull(pull: Any, issue: int, pr: int, gh: GitHub) -> str:
    if not isinstance(pull, dict) or type(pull.get("number")) is not int or pull.get("number") != pr:
        raise VerificationError("PR identity does not match the requested PR")
    base, head = pull.get("base"), pull.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    if (not isinstance(base_repo, dict) or not isinstance(head_repo, dict)
            or str(base_repo.get("full_name", "")).casefold() != gh.repo.casefold()
            or str(head_repo.get("full_name", "")).casefold() != gh.repo.casefold()):
        raise VerificationError("PR head and base must belong to the configured repository")
    if pull.get("state") != "open" or pull.get("draft") is not False or pull.get("merged") is True:
        raise VerificationError("final verification requires an open, non-draft PR")
    body = pull.get("body")
    if not isinstance(body, str) or not re.search(rf"(?im)^\s*closes\s+#{issue}\s*$", body):
        raise VerificationError(f"PR body must contain a standalone Closes #{issue} line")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise VerificationError("PR HEAD must be a full 40-character SHA")
    return head_sha


def _plan_identities(plan: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    executed = []
    for index, step in enumerate(plan.steps, 1):
        if step.component == "project":
            scope = "project"
        elif step.target is None:
            scope = "component"
        else:
            scope = "target"
        executed.append({
            "scope": scope,
            "component": step.component,
            "target": step.target,
            "index": index,
            "command_sha256": hashlib.sha256(step.command.encode("utf-8")).hexdigest(),
        })
    skipped = [
        {"component": item.component, "target": item.target, "reason": item.reason}
        for item in plan.skipped
    ]
    return executed, skipped


def _plan_sha256(components: list[str], host: str, arch: str, capabilities: list[str],
                 executed: list[dict[str, Any]], skipped: list[dict[str, str]]) -> str:
    plan = {
        "components": components,
        "host": host,
        "architecture": arch,
        "capabilities": capabilities,
        "executed": executed,
        "skipped_targets": skipped,
    }
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pointer(pr_body: str) -> dict[str, Any] | None:
    pattern = re.compile(r"^##\s+Agent Final Verification\s*$", re.I | re.M)
    matches = list(pattern.finditer(pr_body or ""))
    if not matches:
        return None
    if len(matches) != 1:
        raise VerificationError("PR body must contain at most one Agent Final Verification pointer")
    lines = (pr_body or "").splitlines()
    start = next(i for i, line in enumerate(lines) if pattern.fullmatch(line))
    fields: dict[str, str] = {}
    for line in lines[start + 1:]:
        if re.match(r"^#{1,6}\s+", line):
            break
        if ": " in line:
            key, value = line.split(": ", 1)
            key = key.strip()
            if key in fields:
                raise VerificationError("final-verification pointer has duplicate fields")
            fields[key] = value.strip()
    expected = {"Comment ID", "SHA-256", "HEAD", "Contract Comment ID", "Contract SHA-256",
                "Plan SHA-256", "Result"}
    if set(fields) != expected:
        raise VerificationError("final-verification pointer is malformed")
    try:
        comment_id = int(fields["Comment ID"])
        contract_id = int(fields["Contract Comment ID"])
    except ValueError as exc:
        raise VerificationError("final-verification pointer contains a malformed comment ID") from exc
    if (comment_id < 1 or contract_id < 1
            or not re.fullmatch(r"[0-9a-f]{64}", fields["SHA-256"])
            or not re.fullmatch(r"[0-9a-f]{40}", fields["HEAD"])
            or not re.fullmatch(r"[0-9a-f]{64}", fields["Contract SHA-256"])
            or not re.fullmatch(r"[0-9a-f]{64}", fields["Plan SHA-256"])
            or fields["Result"] not in RECEIPT_RESULTS):
        raise VerificationError("final-verification pointer contains malformed identity or hash fields")
    return {
        "comment_id": comment_id,
        "sha256": fields["SHA-256"],
        "head": fields["HEAD"],
        "contract_comment_id": contract_id,
        "contract_sha256": fields["Contract SHA-256"],
        "plan_sha256": fields["Plan SHA-256"],
        "result": fields["Result"],
    }


def _with_pointer(body: str, receipt: dict[str, Any], comment_id: int, digest: str) -> str:
    block = [
        f"## {POINTER_TITLE}", "", f"Comment ID: {comment_id}", f"SHA-256: {digest}",
        f"HEAD: {receipt['head']}", f"Contract Comment ID: {receipt['contract_comment_id']}",
        f"Contract SHA-256: {receipt['contract_sha256']}", f"Plan SHA-256: {receipt['plan_sha256']}",
        f"Result: {receipt['result']}",
    ]
    lines = (body or "").splitlines()
    matches = [i for i, line in enumerate(lines) if re.fullmatch(r"##\s+Agent Final Verification\s*", line, re.I)]
    if not matches:
        base = (body or "").rstrip()
        return (base + "\n\n" if base else "") + "\n".join(block) + "\n"
    if len(matches) != 1:
        raise VerificationError("PR body must contain at most one Agent Final Verification pointer")
    start = matches[0]
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^#{1,2}\s+", lines[i])), len(lines))
    return "\n".join(lines[:start] + block + lines[end:]).rstrip() + "\n"


def _validate_receipt(receipt: Any, issue: int, pr: int) -> dict[str, Any]:
    if not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int or receipt.get("schema_version") != 1:
        raise VerificationError("final-verification payload has an unsupported schema")
    if (type(receipt.get("issue")) is not int or receipt.get("issue") != issue
            or type(receipt.get("pr")) is not int or receipt.get("pr") != pr):
        raise VerificationError("final-verification payload Issue/PR identity mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("head", ""))):
        raise VerificationError("final-verification payload HEAD is malformed")
    contract_id = receipt.get("contract_comment_id")
    if type(contract_id) is not int or contract_id < 1:
        raise VerificationError("final-verification payload contract comment ID is malformed")
    for field in ("contract_sha256", "plan_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(field, ""))):
            raise VerificationError(f"final-verification payload {field} is malformed")
    host, arch = receipt.get("host"), receipt.get("architecture")
    if not isinstance(host, str) or host not in {"windows", "macos", "linux"} or not isinstance(arch, str) or not arch:
        raise VerificationError("final-verification payload runtime host/architecture is malformed")
    capabilities = receipt.get("capabilities")
    components = receipt.get("components")
    executed = receipt.get("executed")
    skipped = receipt.get("skipped_targets")
    if (not isinstance(capabilities, list) or any(not isinstance(v, str) or not v for v in capabilities)
            or capabilities != sorted(set(capabilities))):
        raise VerificationError("final-verification payload capabilities are malformed")
    if (not isinstance(components, list) or not components
            or any(not isinstance(v, str) or not v for v in components)
            or len(components) != len(set(components))):
        raise VerificationError("final-verification payload components are malformed")
    if not isinstance(executed, list) or not isinstance(skipped, list):
        raise VerificationError("final-verification payload plan entries are malformed")
    required_identity = {"scope", "component", "target", "index", "command_sha256"}
    for position, identity in enumerate(executed, 1):
        if (not isinstance(identity, dict) or set(identity) != required_identity
                or not isinstance(identity.get("scope"), str)
                or identity.get("scope") not in {"project", "component", "target"}
                or not isinstance(identity.get("component"), str) or not identity["component"]
                or (identity.get("target") is not None and not isinstance(identity.get("target"), str))
                or type(identity.get("index")) is not int or identity["index"] != position
                or not re.fullmatch(r"[0-9a-f]{64}", str(identity.get("command_sha256", "")))):
            raise VerificationError("final-verification payload contains a malformed executed identity")
        if ((identity["scope"] == "project" and (identity["component"] != "project" or identity["target"] is not None))
                or (identity["scope"] == "component" and (identity["component"] == "project" or identity["target"] is not None))
                or (identity["scope"] == "target" and (identity["component"] == "project" or not identity["target"]))):
            raise VerificationError("final-verification payload executed scope is inconsistent")
        if identity["scope"] != "project" and identity["component"] not in components:
            raise VerificationError("final-verification payload identity names an unselected component")
    for target in skipped:
        if (not isinstance(target, dict) or set(target) != {"component", "target", "reason"}
                or any(not isinstance(target.get(field), str) or not target[field]
                       for field in ("component", "target", "reason"))):
            raise VerificationError("final-verification payload contains a malformed skipped target")
    result = receipt.get("result")
    if not isinstance(result, str) or result not in RECEIPT_RESULTS:
        raise VerificationError("final-verification payload result is malformed")
    if result == "pass" and (not executed or skipped):
        raise VerificationError("PASS requires executed commands and no skipped targets")
    if result == "partial" and not skipped:
        raise VerificationError("partial result requires explicitly unverified skipped targets")
    if result == "empty" and (executed or skipped):
        raise VerificationError("empty result cannot contain executed or skipped targets")
    expected_plan = _plan_sha256(components, host, arch, capabilities, executed, skipped)
    if receipt["plan_sha256"] != expected_plan:
        raise VerificationError("final-verification plan SHA-256 does not match its identities")
    serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2)
    if len(serialized.encode("utf-8")) > 65536 or SECRET.search(serialized):
        raise VerificationError("final-verification payload is oversized or contains credential material")
    return receipt


def _same_contract(surface: dict[str, Any], receipt: dict[str, Any]) -> bool:
    return (surface.get("contract_comment_id") == receipt["contract_comment_id"]
            and surface.get("contract_sha256") == receipt["contract_sha256"])


def verify_final(repo: Path, issue: int, pr: int, gh: GitHub, *, runtime_host: str | None = None,
                 architecture: str | None = None, capabilities: list[str] | None = None,
                 diagnostic: bool = False) -> dict[str, Any]:
    if type(issue) is not int or issue < 1 or type(pr) is not int or pr < 1:
        raise VerificationError("Issue and PR numbers must be positive integers")
    require_clean_worktree(repo)
    head = local_head_sha(repo)
    issue_obj = gh.issue(issue)
    _verify_issue(issue_obj, issue, gh)
    pull = gh.pull(pr)
    pr_head = _verify_pull(pull, issue, pr, gh)
    if head != pr_head:
        raise VerificationError("local HEAD must exactly match the PR HEAD before final verification")
    surface = load_review_surface(issue, issue_obj.get("body") or "", gh)
    profile = load_profile(repo)
    if profile.get("schema_version") != 2:
        raise VerificationError("final verification requires a Schema 2 component profile")
    selected = affected_components(issue_obj.get("body") or "", profile)
    if not selected:
        raise VerificationError("Issue does not route final verification to any component")
    component_ids = [item["id"] for item in selected]
    host = normalize_host(runtime_host)
    arch = normalize_arch(architecture)
    supplied_capabilities = capabilities or []
    if (not isinstance(supplied_capabilities, list)
            or any(not isinstance(cap, str) or not cap or len(cap) > 128 or "\n" in cap or "\r" in cap
                   or SECRET.search(cap) for cap in supplied_capabilities)):
        raise VerificationError("capabilities must be short non-credential names")
    caps = sorted(set(supplied_capabilities))
    plan = build_hook_plan(profile, "verify_final", component_ids, host, arch, caps)
    executed, skipped = _plan_identities(plan)
    plan_sha = _plan_sha256(component_ids, host, arch, caps, executed, skipped)

    # Commands and child output stay transient. Only identity hashes are retained.
    for step in plan.steps:
        run_command(step.command, repo, diagnostic=diagnostic)

    require_clean_worktree(repo)
    if local_head_sha(repo) != head:
        raise VerificationError("local HEAD changed while final verification was running")
    result = "pass" if executed and not skipped else "partial" if skipped else "empty"
    receipt = {
        "schema_version": 1,
        "issue": issue,
        "pr": pr,
        "head": head,
        "contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": surface["contract_sha256"],
        "host": host,
        "architecture": arch,
        "capabilities": caps,
        "components": component_ids,
        "plan_sha256": plan_sha,
        "executed": executed,
        "skipped_targets": skipped,
        "result": result,
    }
    _validate_receipt(receipt, issue, pr)
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    comment_body = (
        f"<!-- agent-final-verification:v1 issue={issue} pr={pr} head={head} "
        f"contract_comment={surface['contract_comment_id']} contract={surface['contract_sha256']} "
        f"plan={plan_sha} result={result} sha256={digest} -->\n\n{payload}"
    )
    if len(comment_body) > 65536:
        raise VerificationError("final-verification comment exceeds 65536 characters")
    _pointer(pull.get("body") or "")
    created = gh.create_pull_comment(pr, comment_body)
    try:
        comment_id = int(created["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError("final-verification comment creation returned an invalid ID") from exc
    try:
        named = gh.pull_comment(comment_id)
    except GitHubError as exc:
        raise VerificationError(f"final-verification comment {comment_id} could not be read back by ID") from exc
    if (not isinstance(named, dict) or named.get("id") != comment_id
            or named.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}"
            or named.get("body") != comment_body):
        raise VerificationError("final-verification comment named readback does not match submitted bytes")

    latest_issue = gh.issue(issue)
    _verify_issue(latest_issue, issue, gh)
    latest_surface = load_review_surface(issue, latest_issue.get("body") or "", gh)
    latest_pull = gh.pull(pr)
    latest_head = _verify_pull(latest_pull, issue, pr, gh)
    if latest_head != head or not _same_contract(latest_surface, receipt):
        raise VerificationError("Issue contract or PR HEAD changed while publishing final verification")
    old_pointer = _pointer(latest_pull.get("body") or "")
    updated = _with_pointer(latest_pull.get("body") or "", receipt, comment_id, digest)
    gh.update_pull(pr, updated)
    readback = gh.pull(pr)
    actual_pointer = _pointer(readback.get("body") or "")
    expected_pointer = {
        "comment_id": comment_id,
        "sha256": digest,
        "head": head,
        "contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": surface["contract_sha256"],
        "plan_sha256": plan_sha,
        "result": result,
    }
    if actual_pointer != expected_pointer:
        raise VerificationError("PR final-verification pointer failed readback verification")
    return {"comment_id": comment_id, "sha256": digest, "head": head,
            "contract_comment_id": surface["contract_comment_id"],
            "contract_sha256": surface["contract_sha256"], "plan_sha256": plan_sha,
            "result": result, "executed_count": len(executed),
            "skipped_target_count": len(skipped), "old_pointer": old_pointer}


def validate_public_final_verification(issue: int, pr: int, gh: GitHub, *,
                                       issue_obj: dict[str, Any] | None = None,
                                       pull: dict[str, Any] | None = None) -> dict[str, Any]:
    issue_obj = issue_obj if issue_obj is not None else gh.issue(issue)
    pull = pull if pull is not None else gh.pull(pr)
    _verify_issue(issue_obj, issue, gh)
    head = _verify_pull(pull, issue, pr, gh)
    pointer = _pointer(pull.get("body") or "")
    if pointer is None:
        raise VerificationError("PR has no Agent Final Verification pointer")
    try:
        comment = gh.pull_comment(pointer["comment_id"])
    except GitHubError as exc:
        raise VerificationError("named final-verification comment could not be read") from exc
    if (not isinstance(comment, dict) or comment.get("id") != pointer["comment_id"]
            or comment.get("issue_url") != f"https://api.github.com/repos/{gh.repo}/issues/{pr}"):
        raise VerificationError("named final-verification comment belongs to a different PR")
    body = comment.get("body", "")
    if not isinstance(body, str) or len(body.encode("utf-8")) > 65536 or SECRET.search(body):
        raise VerificationError("named final-verification comment is oversized or contains credential material")
    header, separator, payload_text = body.partition("\n\n")
    match = HEADER.fullmatch(header)
    if not separator or match is None:
        raise VerificationError("named final-verification comment has malformed metadata")
    if int(match.group(1)) != issue or int(match.group(2)) != pr:
        raise VerificationError("named final-verification comment has wrong Issue/PR identity")
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    if digest != match.group(8) or pointer["sha256"] != digest:
        raise VerificationError("final-verification pointer and comment SHA-256 disagree")
    try:
        receipt = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise VerificationError("named final-verification payload is invalid JSON") from exc
    _validate_receipt(receipt, issue, pr)
    metadata = {
        "head": match.group(3), "contract_comment_id": int(match.group(4)),
        "contract_sha256": match.group(5), "plan_sha256": match.group(6),
        "result": match.group(7),
    }
    expected_metadata = {
        "head": receipt["head"], "contract_comment_id": receipt["contract_comment_id"],
        "contract_sha256": receipt["contract_sha256"], "plan_sha256": receipt["plan_sha256"],
        "result": receipt["result"],
    }
    if metadata != expected_metadata or pointer != {
        "comment_id": pointer["comment_id"], "sha256": digest, **expected_metadata,
    }:
        raise VerificationError("final-verification pointer, comment metadata, and payload disagree")
    surface = load_review_surface(issue, issue_obj.get("body") or "", gh)
    stale_reasons = []
    if receipt["head"] != head:
        stale_reasons.append("PR HEAD changed")
    if not _same_contract(surface, receipt):
        stale_reasons.append("approved Implementation Contract comment/SHA changed")
    return {
        "receipt": receipt,
        "comment_id": pointer["comment_id"],
        "sha256": digest,
        "stale": bool(stale_reasons),
        "stale_reasons": stale_reasons,
        "current_head": head,
        "current_contract_comment_id": surface["contract_comment_id"],
        "current_contract_sha256": surface["contract_sha256"],
    }
