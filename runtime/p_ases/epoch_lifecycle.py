"""Issue-neutral one-shot execution epoch reset bound to the current approved ADC.

New resets use a typed exact-subject authorization and append-only Intent/Applied.
Older ADC bodies and pointer chains are never consulted. An existing active epoch
is always read via the immutable current-epoch reader.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .adc import ADCError, VerifiedADC, verify_adc
from .current_epoch import CurrentEpochError, epoch_paths, read_current_epoch
from .git import GitError, current_branch, head_sha40, is_ancestor, worktree_clean
from .github import GitHub, GitHubError
from .path_safety import path_has_symlink

AUTH_SCHEMA = "PASES_EXECUTION_EPOCH_RESET_AUTH_V1"
INTENT_SCHEMA = "PASES_ISSUE_PHASE_EPOCH_REBASE_INTENT_V1"
APPLIED_SCHEMA = "PASES_ISSUE_PHASE_EPOCH_REBASE_APPLIED_V1"
ORIGIN_SCHEMA = "PASES_ISSUE_EXECUTION_EPOCH_V3"
ATTACHMENT_SCHEMA = "PASES_EXECUTION_EPOCH_ATTACHMENT_V3"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
AUTH_FIELDS = {
    "schema", "repository", "issue_number", "issue_id", "owner_id", "base_ref",
    "base_sha40", "branch_ref", "from_phase", "to_phase", "labels_before",
    "labels_after", "historical_binding_provenance", "historical_binding_sha256",
    "predecessor_epoch_id", "predecessor_epoch_sha256", "max_applications",
}


class EpochLifecycleError(ValueError):
    """The current subject is not authorized or an operation may have been attempted."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EpochLifecycleError("authorization JSON has duplicate keys")
        result[key] = value
    return result


def _json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(schema: str, payload: Mapping[str, Any]) -> str:
    return f"<!-- {schema}\n{_json(payload).decode('utf-8')}\n-->"


def _authorization(verified: VerifiedADC, repository: str, issue_number: int) -> tuple[dict[str, Any], str]:
    content = verified.contract.content
    if not isinstance(content, bytes):
        raise EpochLifecycleError("current approved ADC content is unavailable")
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EpochLifecycleError("current ADC is not UTF-8") from exc
    prefix = f"<!-- {AUTH_SCHEMA}\n"
    rows = [part.split("\n-->", 1)[0] for part in text.split(prefix)[1:]]
    if len(rows) != 1 or not text.count(prefix) == 1 or "\n-->" not in text.split(prefix)[1]:
        raise EpochLifecycleError("current ADC must declare one canonical execution epoch reset")
    raw = rows[0]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, TypeError) as exc:
        raise EpochLifecycleError("epoch reset authorization is malformed") from exc
    if (not isinstance(value, dict) or set(value) != AUTH_FIELDS
            or _json(value).decode("utf-8") != raw
            or value.get("schema") != AUTH_SCHEMA
            or value.get("repository", "").casefold() != repository.casefold()
            or value.get("issue_number") != issue_number
            or type(value.get("issue_id")) is not int or value["issue_id"] < 1
            or type(value.get("owner_id")) is not int or value["owner_id"] < 1
            or value.get("from_phase") not in {"ready", "execution", "verification"}
            or value.get("to_phase") != "requirements"
            or value.get("max_applications") != 1
            or value.get("historical_binding_provenance") != "UNVERIFIED"
            or not isinstance(value.get("base_sha40"), str)
            or SHA40.fullmatch(value["base_sha40"]) is None
            or any(x is not None and (not isinstance(x, str) or SHA256.fullmatch(x) is None)
                   for x in (value.get("historical_binding_sha256"),
                             value.get("predecessor_epoch_id"),
                             value.get("predecessor_epoch_sha256")))
            or (value.get("predecessor_epoch_id") is None)
               != (value.get("predecessor_epoch_sha256") is None)
            or not isinstance(value.get("base_ref"), str) or not value["base_ref"]
            or not isinstance(value.get("branch_ref"), str) or not value["branch_ref"]):
        raise EpochLifecycleError("epoch reset authorization does not bind the current exact subject")
    before, after = value["labels_before"], value["labels_after"]
    if (not isinstance(before, list) or not isinstance(after, list)
            or any(not isinstance(x, str) for x in before + after)
            or before != sorted(set(before)) or after != sorted(set(after))
            or not any(x.startswith("kind:") for x in before)
            or sorted(x for x in before if not x.startswith("phase:"))
               != sorted(x for x in after if not x.startswith("phase:"))
            or [x for x in before if x.startswith("phase:")] != [f"phase:{value['from_phase']}"]
            or [x for x in after if x.startswith("phase:")] != ["phase:requirements"]):
        raise EpochLifecycleError("epoch reset authorization has invalid exact label sets")
    return value, _sha(_json(value))


def _live(github: GitHub, root: Path, issue_number: int, adc: VerifiedADC,
          auth: Mapping[str, Any], labels: list[str]) -> tuple[dict[str, Any], int, int, str]:
    """Check the entire mutable subject at each write boundary."""
    try:
        current = verify_adc(github, issue_number)
        metadata = github.repository_metadata()
        actor = github.authenticated_user()
        issue = github.issue(issue_number)
        branch = current_branch(root)
        head = head_sha40(root)
        remote = github.branch(branch)
        label_rows = issue.get("labels") if isinstance(issue, dict) else None
        names = [row.get("name") for row in label_rows] if isinstance(label_rows, list) else []
        owner = metadata.get("owner") if isinstance(metadata, dict) else None
        owner_id = owner.get("id") if isinstance(owner, dict) else None
        if (current.pointer != adc.pointer or current.pointer.state != "approved"
                or current.contract.sha256 != adc.contract.sha256
                or not isinstance(metadata, dict)
                or metadata.get("full_name", "").casefold() != github.repo.casefold()
                or type(metadata.get("id")) is not int or metadata["id"] < 1
                or not isinstance(owner, dict) or owner.get("type") != "User"
                or owner_id != auth["owner_id"]
                or not isinstance(actor, dict) or actor.get("type") != "User"
                or actor.get("id") != owner_id
                or not isinstance(issue, dict) or issue.get("number") != issue_number
                or issue.get("id") != auth["issue_id"] or issue.get("state") != "open"
                or issue.get("pull_request") is not None
                or issue.get("repository_url") != f"https://api.github.com/repos/{github.repo}"
                or sorted(names) != labels or len(names) != len(set(names))
                or branch != auth["branch_ref"]
                or remote.get("commit", {}).get("sha") != head
                or not is_ancestor(root, auth["base_sha40"], head)
                or not worktree_clean(root)):
            raise EpochLifecycleError("epoch reset live ADC, owner, Issue, labels or worktree changed")
        if not isinstance(issue.get("body"), str):
            raise EpochLifecycleError("epoch reset requires unchanged textual Issue body")
        return issue, metadata["id"], owner_id, head
    except (ADCError, GitHubError, GitError, OSError) as exc:
        raise EpochLifecycleError(f"epoch reset live readback failed: {exc}") from exc


def _attempt(root: Path, issue_number: int, name: str, digest: str, *,
             namespace: str = "epoch-reset") -> None:
    if namespace not in {"epoch-reset", "phase-rework"}:
        raise EpochLifecycleError("unsupported one-shot journal namespace")
    directory = root / ".p_ases" / "state" / str(issue_number)
    path = directory / f"{namespace}-{name}.attempt"
    if path_has_symlink(path, root=root):
        raise EpochLifecycleError("epoch reset attempt marker uses a symbolic link")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise EpochLifecycleError(f"{namespace} operation was already attempted; read-only reconciliation required") from exc
    with os.fdopen(fd, "wb") as stream:
        stream.write((digest + "\n").encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())


def _post(github: GitHub, root: Path, issue_number: int, label: str,
          schema: str, payload: Mapping[str, Any], owner_id: int, *,
          namespace: str = "epoch-reset") -> tuple[int, str]:
    body = _record(schema, payload)
    _attempt(root, issue_number, label, _sha(body.encode("utf-8")),
             namespace=namespace)
    try:
        created = github.create_issue_comment(issue_number, body)
        comment_id = created.get("id") if isinstance(created, dict) else None
        if type(comment_id) is not int or comment_id < 1:
            raise EpochLifecycleError("epoch comment POST has no valid ID")
        record = github.issue_comment(issue_number, comment_id)
    except GitHubError as exc:
        raise EpochLifecycleError("epoch comment outcome is ambiguous; never retry POST") from exc
    if (not isinstance(record, dict) or record.get("body") != body
            or record.get("id") != comment_id
            or record.get("issue_url") != f"https://api.github.com/repos/{github.repo}/issues/{issue_number}"
            or record.get("created_at") != record.get("updated_at")
            or not isinstance(record.get("user"), dict)
            or record["user"].get("id") != owner_id):
        raise EpochLifecycleError("epoch comment direct readback differs from the posted record")
    return comment_id, _sha(body.encode("utf-8"))


def _create_once(path: Path, raw: bytes, root: Path) -> None:
    if path_has_symlink(path, root=root):
        raise EpochLifecycleError("epoch state path uses a symbolic link")
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            raise EpochLifecycleError("immutable execution epoch file has conflicting bytes")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise EpochLifecycleError("epoch state was concurrently created") from exc
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def reset_execution_epoch(github: GitHub, root: Path, issue_number: int) -> dict[str, Any]:
    """Append a newly authorized epoch exactly once; completed retries do no writes."""
    root = Path(root).resolve()
    if type(issue_number) is not int or issue_number < 1:
        raise EpochLifecycleError("execution epoch Issue number must be positive")
    local, attachment_path = epoch_paths(root, issue_number)
    if (local.exists() or local.is_symlink()
            or attachment_path.exists() or attachment_path.is_symlink()):
        try:
            active = read_current_epoch(github, root, issue_number)
        except (CurrentEpochError, GitHubError, ValueError, OSError) as exc:
            raise EpochLifecycleError(f"existing epoch is incomplete or invalid: {exc}") from exc
        return {"status": "NOOP", "issue": issue_number,
                "epoch_id": active.epoch_id, "applied_comment_id": active.applied_comment_id,
                "writes_performed": 0}
    binding = local.with_name("execution-binding.json")
    if binding.exists() or binding.is_symlink():
        raise EpochLifecycleError("cannot reset an Issue with a current V1 Binding")
    try:
        verified = verify_adc(github, issue_number)
        if verified.pointer.state != "approved":
            raise EpochLifecycleError("epoch reset requires the current approved ADC")
        auth, auth_sha = _authorization(verified, github.repo, issue_number)
        issue, repo_id, owner_id, head = _live(
            github, root, issue_number, verified, auth, auth["labels_before"],
        )
        issue_sha = _sha(issue["body"].encode("utf-8"))
        epoch_id = _sha(_json({
            "schema": ORIGIN_SCHEMA, "repository": github.repo,
            "issue_number": issue_number, "issue_id": auth["issue_id"],
            "adc_comment_id": verified.pointer.comment_id,
            "adc_sha256": verified.pointer.sha256,
            "authorization_sha256": auth_sha, "branch_ref": auth["branch_ref"],
            "base_sha40": auth["base_sha40"],
        }))
        intent = {
            **auth, "schema": INTENT_SCHEMA, "repository_id": repo_id,
            "adc_comment_id": verified.pointer.comment_id, "adc_sha256": verified.pointer.sha256,
            "authorization_sha256": auth_sha, "epoch_id": epoch_id,
            "head_sha40": head, "issue_body_sha256": issue_sha,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        _live(github, root, issue_number, verified, auth, auth["labels_before"])
        # This is a one-shot writer. A missing local journal is never permission
        # to duplicate an already published remote Intent or Applied record.
        existing = github.issue_comments(issue_number)
        if any(isinstance(row, dict) and isinstance(row.get("body"), str)
               and row["body"].startswith((
                   f"<!-- {INTENT_SCHEMA}\n", f"<!-- {APPLIED_SCHEMA}\n",
               )) for row in existing):
            raise EpochLifecycleError("remote epoch reset journal already exists; read-only reconciliation required")
        intent_id, intent_sha = _post(
            github, root, issue_number, "intent", INTENT_SCHEMA, intent, owner_id,
        )
        _live(github, root, issue_number, verified, auth, auth["labels_before"])
        _attempt(root, issue_number, "labels", _sha(_json({
            "intent_id": intent_id, "intent_sha256": intent_sha, "labels_after": auth["labels_after"],
        })))
        try:
            github.replace_issue_labels(issue_number, auth["labels_after"])
        except GitHubError as exc:
            raise EpochLifecycleError("epoch label PUT is ambiguous; no retry is permitted") from exc
        after_issue, *_ = _live(github, root, issue_number, verified, auth, auth["labels_after"])
        if after_issue.get("body") != issue["body"]:
            raise EpochLifecycleError("epoch Issue body changed after label update")
        applied = {
            **{k: v for k, v in intent.items() if k != "created_at"},
            "schema": APPLIED_SCHEMA, "intent_comment_id": intent_id,
            "intent_body_sha256": intent_sha,
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        applied_id, applied_sha = _post(
            github, root, issue_number, "applied", APPLIED_SCHEMA, applied, owner_id,
        )
        origin = {
            "schema": ORIGIN_SCHEMA, "repository": github.repo,
            "issue_number": issue_number, "issue_id": auth["issue_id"],
            "adc_comment_id": verified.pointer.comment_id,
            "adc_sha256": verified.pointer.sha256, "base_ref": auth["base_ref"],
            "base_sha40": auth["base_sha40"], "branch_ref": auth["branch_ref"],
            "epoch_id": epoch_id, "intent_comment_id": intent_id,
            "intent_body_sha256": intent_sha, "applied_comment_id": applied_id,
            "applied_body_sha256": applied_sha,
            "predecessor_epoch_id": auth["predecessor_epoch_id"],
            "predecessor_epoch_sha256": auth["predecessor_epoch_sha256"],
            "historical_binding_provenance": "UNVERIFIED",
            "historical_binding_sha256": auth["historical_binding_sha256"],
        }
        origin["sha256"] = _sha(_json(origin))
        attachment = {
            "schema": ATTACHMENT_SCHEMA, "repository": github.repo,
            "issue_number": issue_number,
            "adc_comment_id": verified.pointer.comment_id,
            "adc_sha256": verified.pointer.sha256,
            "base_ref": auth["base_ref"], "base_sha40": auth["base_sha40"],
            "branch_ref": auth["branch_ref"], "epoch_id": epoch_id,
            "epoch_sha256": origin["sha256"],
            "intent_comment_id": intent_id, "intent_body_sha256": intent_sha,
            "applied_comment_id": applied_id, "applied_body_sha256": applied_sha,
            "work_directory": str(root),
        }
        _create_once(local, _json(origin) + b"\n", root)
        _create_once(attachment_path, _json(attachment) + b"\n", root)
        active = read_current_epoch(github, root, issue_number, verified)
        if active.epoch_id != epoch_id:
            raise EpochLifecycleError("new execution epoch failed exact origin readback")
        return {"status": "APPLIED", "issue": issue_number,
                "epoch_id": epoch_id, "applied_comment_id": applied_id,
                "writes_performed": 3}
    except (ADCError, GitError, GitHubError, CurrentEpochError, OSError) as exc:
        raise EpochLifecycleError(str(exc)) from exc
