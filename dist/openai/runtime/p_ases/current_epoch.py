"""Current-only, Issue-neutral reader for an immutable execution epoch.

The current approved ADC, local canonical epoch/attachment and exact GitHub
applied carriers are authoritative. Superseded ADC bodies and chains are never
read by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .adc import VerifiedADC, verify_adc
from .git import current_branch, head_sha40, is_ancestor
from .github import GitHub, GitHubError
from .path_safety import path_has_symlink


class CurrentEpochError(ValueError):
    pass


SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
ORIGIN_SCHEMA = "PASES_ISSUE_EXECUTION_EPOCH_V3"
ATTACHMENT_SCHEMA = "PASES_EXECUTION_EPOCH_ATTACHMENT_V3"
ORIGIN_INTENT = "PASES_ISSUE_PHASE_EPOCH_REBASE_INTENT_V1"
ORIGIN_APPLIED = "PASES_ISSUE_PHASE_EPOCH_REBASE_APPLIED_V1"
REWORK_INTENT = "PASES_ISSUE_VERIFICATION_REWORK_INTENT_V3"
REWORK_APPLIED = "PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V3"


def _canonical(data: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(data), ensure_ascii=True, separators=(",", ":"),
                       sort_keys=True) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise CurrentEpochError("epoch JSON contains a duplicate field")
        result[key] = value
    return result


def _private_json(path: Path, root: Path) -> dict[str, Any]:
    if path_has_symlink(path, root=root) or not path.is_file():
        raise CurrentEpochError("epoch state must be a regular non-symlink file")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentEpochError("epoch state is not valid canonical JSON") from exc
    if not isinstance(value, dict) or _canonical(value) != raw:
        raise CurrentEpochError("epoch state bytes are not canonical")
    return value


def epoch_paths(root: Path, issue_number: int) -> tuple[Path, Path]:
    if type(issue_number) is not int or issue_number < 1:
        raise CurrentEpochError("epoch Issue number must be positive")
    state = Path(root) / ".p_ases" / "state" / str(issue_number)
    return state / "execution-epoch.json", state / "execution-epoch-attachment.json"


@dataclass(frozen=True)
class ActiveExecutionEpoch:
    """Current authority projected onto one origin record without history traversal."""

    origin: Mapping[str, Any]
    adc_comment_id: int
    adc_sha256: str
    applied_comment_id: int
    applied_body_sha256: str

    @property
    def schema(self) -> str:
        return str(self.origin["schema"])

    @property
    def repository(self) -> str:
        return str(self.origin["repository"])

    @property
    def issue_number(self) -> int:
        return int(self.origin["issue_number"])

    @property
    def issue_id(self) -> int:
        return int(self.origin["issue_id"])

    @property
    def base_ref(self) -> str:
        return str(self.origin["base_ref"])

    @property
    def base_sha40(self) -> str:
        return str(self.origin["base_sha40"])

    @property
    def branch_ref(self) -> str:
        return str(self.origin["branch_ref"])

    @property
    def epoch_id(self) -> str:
        return str(self.origin["epoch_id"])

    @property
    def sha256(self) -> str:
        return str(self.origin["sha256"])

    @property
    def historical_binding_provenance(self) -> str:
        return str(self.origin["historical_binding_provenance"])

    def validate(self) -> "ActiveExecutionEpoch":
        if (self.schema != ORIGIN_SCHEMA
                or not REPOSITORY.fullmatch(self.repository)
                or self.issue_number < 1 or self.issue_id < 1
                or not SHA40.fullmatch(self.base_sha40)
                or not SHA256.fullmatch(self.sha256)
                or not SHA256.fullmatch(self.epoch_id)
                or self.adc_comment_id < 1 or not SHA256.fullmatch(self.adc_sha256)
                or self.applied_comment_id < 1 or not SHA256.fullmatch(self.applied_body_sha256)):
            raise CurrentEpochError("current execution epoch identity is invalid")
        return self


def _carrier(github: GitHub, issue_number: int, comment_id: int, expected_schema: str,
             expected_sha: str | None, owner_id: int) -> tuple[dict[str, Any], str]:
    row = github.issue_comment(issue_number, comment_id)
    body = row.get("body") if isinstance(row, dict) else None
    prefix = f"<!-- {expected_schema}\n"
    if not isinstance(body, str) or not body.startswith(prefix) or not body.endswith("\n-->"):
        raise CurrentEpochError("execution epoch applied carrier has an unexpected schema")
    if (row.get("id") != comment_id
            or row.get("issue_url") != f"https://api.github.com/repos/{github.repo}/issues/{issue_number}"
            or row.get("created_at") != row.get("updated_at")
            or not isinstance(row.get("user"), dict)
            or row["user"].get("id") != owner_id):
        raise CurrentEpochError("execution epoch applied carrier identity, author, or timestamps changed")
    digest = _sha(body.encode("utf-8"))
    if expected_sha is not None and digest != expected_sha:
        raise CurrentEpochError("execution epoch applied carrier digest does not match")
    raw = body[len(prefix):-len("\n-->")]
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs)
    except json.JSONDecodeError as exc:
        raise CurrentEpochError("execution epoch applied carrier JSON is invalid") from exc
    if (not isinstance(value, dict)
            or json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) != raw
            or value.get("schema") != expected_schema):
        raise CurrentEpochError("execution epoch applied carrier is not canonical")
    return value, digest


def read_current_epoch(github: GitHub, root: Path, issue_number: int,
                       verified: VerifiedADC | None = None) -> ActiveExecutionEpoch:
    """Read the active epoch using the latest current state, never older ADCs."""
    root = Path(root).resolve()
    epoch_path, attachment_path = epoch_paths(root, issue_number)
    epoch = _private_json(epoch_path, root)
    attachment = _private_json(attachment_path, root)
    base = dict(epoch)
    digest = base.pop("sha256", None)
    if (epoch.get("schema") != ORIGIN_SCHEMA or not isinstance(digest, str)
            or digest != _sha(_canonical(base).rstrip(b"\n"))
            or epoch.get("repository", "").casefold() != github.repo.casefold()
            or epoch.get("issue_number") != issue_number):
        raise CurrentEpochError("execution epoch record digest or Issue identity is invalid")
    expected_attachment = {
        "schema": ATTACHMENT_SCHEMA,
        "repository": epoch["repository"], "issue_number": issue_number,
        "adc_comment_id": epoch["adc_comment_id"], "adc_sha256": epoch["adc_sha256"],
        "base_ref": epoch["base_ref"], "base_sha40": epoch["base_sha40"],
        "branch_ref": epoch["branch_ref"], "epoch_id": epoch["epoch_id"],
        "epoch_sha256": digest,
        "intent_comment_id": epoch["intent_comment_id"],
        "intent_body_sha256": epoch["intent_body_sha256"],
        "applied_comment_id": epoch["applied_comment_id"],
        "applied_body_sha256": epoch["applied_body_sha256"],
        "work_directory": str(root),
    }
    if attachment != expected_attachment:
        raise CurrentEpochError("execution epoch attachment does not match the exact checkout")
    current = verified or verify_adc(github, issue_number)
    if current.pointer.state != "approved":
        raise CurrentEpochError("execution epoch requires the current approved ADC")
    metadata = github.repository_metadata()
    owner = metadata.get("owner") if isinstance(metadata, dict) else None
    owner_id = owner.get("id") if isinstance(owner, dict) else None
    issue = github.issue(issue_number)
    labels = issue.get("labels") if isinstance(issue, dict) else None
    names = [row.get("name") for row in labels] if isinstance(labels, list) else []
    if (type(owner_id) is not int or owner_id < 1
            or not isinstance(issue, dict) or issue.get("number") != issue_number
            or issue.get("id") != epoch.get("issue_id") or issue.get("state") != "open"
            or issue.get("pull_request") is not None
            or issue.get("repository_url") != f"https://api.github.com/repos/{github.repo}"
            or len(names) != len(set(names))
            or sum(isinstance(n, str) and n.startswith("kind:") for n in names) != 1
            or sum(isinstance(n, str) and n.startswith("phase:") for n in names) != 1):
        raise CurrentEpochError("execution epoch Issue or owner identity changed")
    if (current_branch(root) != epoch["branch_ref"]
            or not is_ancestor(root, epoch["base_sha40"], head_sha40(root))
            or github.branch(epoch["branch_ref"]).get("commit", {}).get("sha") != head_sha40(root)):
        raise CurrentEpochError("execution epoch local/remote HEAD or frozen base changed")
    origin, _digest = _carrier(
        github, issue_number, epoch["applied_comment_id"], ORIGIN_APPLIED,
        epoch["applied_body_sha256"], owner_id,
    )
    if (origin.get("repository", "").casefold() != github.repo.casefold()
            or origin.get("issue_number") != issue_number or origin.get("epoch_id") != epoch["epoch_id"]
            or origin.get("adc_comment_id") != epoch["adc_comment_id"]
            or origin.get("adc_sha256") != epoch["adc_sha256"]):
        raise CurrentEpochError("execution epoch origin Applied does not match the immutable origin")
    if (origin.get("intent_comment_id") != epoch["intent_comment_id"]
            or origin.get("intent_body_sha256") != epoch["intent_body_sha256"]):
        raise CurrentEpochError("execution epoch origin Applied does not bind its exact Intent")
    origin_intent, _intent_digest = _carrier(
        github, issue_number, epoch["intent_comment_id"], ORIGIN_INTENT,
        epoch["intent_body_sha256"], owner_id,
    )
    if (origin_intent.get("repository", "").casefold() != github.repo.casefold()
            or origin_intent.get("issue_number") != issue_number
            or origin_intent.get("epoch_id") != epoch["epoch_id"]
            or origin_intent.get("adc_comment_id") != epoch["adc_comment_id"]
            or origin_intent.get("adc_sha256") != epoch["adc_sha256"]):
        raise CurrentEpochError("execution epoch origin Intent does not match its Applied")
    active_id = epoch["applied_comment_id"]
    active_sha = epoch["applied_body_sha256"]
    # Only records newer than this immutable epoch origin can define its active
    # Phase generation. Never scan older Issue/ADC comments to find a rework.
    count = issue.get("comments")
    if type(count) is not int or count < 1:
        raise CurrentEpochError("current Issue comment count is unavailable")
    origin_id = epoch["applied_comment_id"]
    reached_origin = False
    for page in github.issue_comment_pages_newest(issue_number, count):
        if not isinstance(page, list):
            raise CurrentEpochError("current Issue comment page is malformed")
        for row in reversed(page):
            identifier = row.get("id") if isinstance(row, dict) else None
            if type(identifier) is not int or identifier < 1:
                raise CurrentEpochError("current Issue comment has an invalid ID")
            if identifier == origin_id:
                reached_origin = True
                break
            body = row.get("body")
            if not isinstance(body, str) or not body.startswith(f"<!-- {REWORK_APPLIED}\n"):
                continue
            data, active_sha = _carrier(
                github, issue_number, identifier, REWORK_APPLIED, None, owner_id,
            )
            if (data.get("repository", "").casefold() != github.repo.casefold()
                    or data.get("issue_number") != issue_number
                    or data.get("active_epoch_id") != epoch["epoch_id"]
                    or data.get("active_epoch_sha256") != digest
                    or data.get("branch_ref") != epoch["branch_ref"]):
                raise CurrentEpochError("current Phase Applied does not bind the active epoch")
            intent_id = data.get("intent_comment_id")
            intent_sha = data.get("intent_body_sha256")
            if (type(intent_id) is not int or intent_id < 1
                    or not isinstance(intent_sha, str) or SHA256.fullmatch(intent_sha) is None):
                raise CurrentEpochError("current Phase Applied lacks an exact Intent reference")
            active_intent, _phase_intent_digest = _carrier(
                github, issue_number, intent_id, REWORK_INTENT, intent_sha, owner_id,
            )
            if (active_intent.get("repository", "").casefold() != github.repo.casefold()
                    or active_intent.get("issue_number") != issue_number
                    or active_intent.get("active_epoch_id") != epoch["epoch_id"]
                    or active_intent.get("active_epoch_sha256") != digest
                    or active_intent.get("branch_ref") != epoch["branch_ref"]
                    or active_intent.get("adc_comment_id") != data.get("adc_comment_id")
                    or active_intent.get("adc_sha256") != data.get("adc_sha256")):
                raise CurrentEpochError("current Phase Intent does not match its Applied")
            active_id = identifier
            break
        if reached_origin or active_id != origin_id:
            break
    if not reached_origin and active_id == origin_id:
        raise CurrentEpochError("immutable epoch origin was not found in current Issue comments")
    # The newest-first window can shift as comments arrive; never return a
    # potentially stale generation selected from a changed pagination count.
    if github.issue(issue_number).get("comments") != count:
        raise CurrentEpochError("current Issue comment count changed during epoch lookup")
    return ActiveExecutionEpoch(
        epoch, current.pointer.comment_id, current.pointer.sha256, active_id, active_sha,
    ).validate()
