"""Current-only, Issue-neutral reader for an immutable execution epoch.

The current approved ADC, local canonical epoch/attachment and exact GitHub
applied carriers are authoritative. Superseded ADC bodies and chains are never
read by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
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
REWORK_TIMESTAMP_MARKER = "PASES_ISSUE71_PHASE_REWORK_TIMESTAMP_CONTINUATION_V2"
UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")


def _canonical(data: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(data), ensure_ascii=True, separators=(",", ":"),
                       sort_keys=True) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_matches(value: Any, repository: str) -> bool:
    return isinstance(value, str) and value.casefold() == repository.casefold()


def _strict_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        raise CurrentEpochError(f"{label} must be a canonical UTC Z timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise CurrentEpochError(f"{label} is not a valid UTC timestamp") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise CurrentEpochError(f"{label} is not canonical UTC")
    return parsed


def _rework_candidate_kind(body: str) -> str | None:
    """Recognize reserved rework headers even after punctuation/spacing edits."""
    if not isinstance(body, str):
        return None
    first_line = body.splitlines()[0] if body.splitlines() else ""
    header = first_line.lstrip()
    if not header.startswith("<!--"):
        return None
    normalized = "<!--" + "".join(
        character for character in header[4:]
        if not character.isspace() and character not in "_-"
    ).casefold()
    family = "<!--pasesissueverificationrework"
    if not normalized.startswith(family):
        return None
    if normalized.startswith(family + "intent"):
        return "intent"
    if normalized.startswith(family + "applied"):
        return "applied"
    return "unknown"


def validate_rework_publication_window(payload: Mapping[str, Any], row: Mapping[str, Any],
                                       event_field: str) -> int:
    """Validate an immutable V2/V3 rework event against GitHub publication time."""
    event_time = _strict_utc(payload.get(event_field), f"Phase rework {event_field}")
    published_at = _strict_utc(row.get("created_at"), "Phase rework comment created_at")
    if row.get("created_at") != row.get("updated_at"):
        raise CurrentEpochError("Phase rework comment timestamps are mutable")
    delta = int((published_at - event_time).total_seconds())
    if delta < 0 or delta > 300:
        raise CurrentEpochError("Phase rework event/publication time is outside 0..300 seconds")
    return delta


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
             expected_sha: str | None, owner_id: int) -> tuple[dict[str, Any], str, dict[str, Any]]:
    row = github.issue_comment(issue_number, comment_id)
    if not isinstance(row, dict):
        raise CurrentEpochError("execution epoch carrier is malformed")
    body = row.get("body")
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
    return value, digest, row


def _validate_pinned_rework_timestamps(
        github: GitHub, issue_number: int, verified: VerifiedADC, owner_id: int,
) -> tuple[set[int], set[int]] | None:
    """Read only the four V2/V3 carriers directly pinned by the current ADC marker."""
    content = getattr(getattr(verified, "contract", None), "content", None)
    if not isinstance(content, bytes):
        return None
    prefix = f"<!-- {REWORK_TIMESTAMP_MARKER}\n".encode("ascii")
    if prefix not in content:
        return None
    if content.count(prefix) != 1:
        raise CurrentEpochError("current Phase timestamp continuation marker is ambiguous")
    start = content.index(prefix) + len(prefix)
    end = content.find(b"\n-->", start)
    if end < 0:
        raise CurrentEpochError("current Phase timestamp continuation marker is incomplete")
    raw = content[start:end]
    try:
        marker = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentEpochError("current Phase timestamp continuation marker is malformed") from exc
    if (not isinstance(marker, dict)
            or json.dumps(marker, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode() != raw
            or marker.get("schema") != REWORK_TIMESTAMP_MARKER):
        raise CurrentEpochError("current Phase timestamp continuation marker is not canonical")
    policy = marker.get("timestamp_policy")
    expected_schemas = {
        "PASES_ISSUE_VERIFICATION_REWORK_INTENT_V2": "created_at",
        "PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V2": "applied_at",
        REWORK_INTENT: "created_at",
        REWORK_APPLIED: "applied_at",
    }
    if (not isinstance(policy, dict)
            or policy.get("schema") != "PASES_ISSUE_PHASE_EVENT_PUBLICATION_WINDOW_V1"
            or policy.get("applies_to") != list(expected_schemas)
            or policy.get("intent_event_field") != "created_at"
            or policy.get("applied_event_field") != "applied_at"
            or type(policy.get("minimum_skew_seconds")) is not int
            or policy.get("minimum_skew_seconds") != 0
            or type(policy.get("max_skew_seconds")) is not int
            or policy.get("max_skew_seconds") != 300):
        raise CurrentEpochError("current Phase timestamp policy does not match its declared schemas")
    origin = marker.get("phase_rework_origin")
    if not isinstance(origin, dict):
        raise CurrentEpochError("current Phase timestamp marker lacks its pinned rework records")
    references = (
        (origin.get("prior_v2_intent"), "PASES_ISSUE_VERIFICATION_REWORK_INTENT_V2", "created_at", False),
        (origin.get("prior_v2_applied"), "PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V2", "applied_at", False),
        (origin.get("intent"), REWORK_INTENT, "created_at", True),
        (origin.get("applied"), REWORK_APPLIED, "applied_at", True),
    )
    ids: set[int] = set()
    v3_ids: set[int] = set()
    for reference, schema, event_field, detailed in references:
        if (not isinstance(reference, dict)
                or detailed and reference.get("schema") != schema
                or type(reference.get("comment_id")) is not int or reference["comment_id"] < 1
                or not isinstance(reference.get("body_sha256"), str)
                or SHA256.fullmatch(reference["body_sha256"]) is None
                or detailed and (type(reference.get("body_byte_length")) is not int
                                or reference["body_byte_length"] < 1)):
            raise CurrentEpochError("current Phase timestamp marker has an invalid direct reference")
        comment_id = reference["comment_id"]
        if comment_id in ids:
            raise CurrentEpochError("current Phase timestamp marker repeats a comment ID")
        ids.add(comment_id)
        if schema in {REWORK_INTENT, REWORK_APPLIED}:
            v3_ids.add(comment_id)
        payload, _digest, row = _carrier(
            github, issue_number, comment_id, schema, reference["body_sha256"], owner_id,
        )
        body = row.get("body")
        if (not isinstance(body, str)
                or detailed and len(body.encode("utf-8")) != reference["body_byte_length"]
                or detailed and row.get("created_at") != reference.get("comment_created_at")
                or not _repo_matches(payload.get("repository"), github.repo)
                or payload.get("issue_number") != issue_number):
            raise CurrentEpochError("current Phase timestamp direct reference differs from its pinned metadata")
        delta = validate_rework_publication_window(payload, row, event_field)
        if (detailed and (payload.get(event_field) != reference.get("event_time")
                          or delta != reference.get("event_to_publication_delta_seconds"))):
            raise CurrentEpochError("current Phase timestamp event differs from its pinned metadata")
    return ids, v3_ids


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
            or not _repo_matches(epoch.get("repository"), github.repo)
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
    names = ([row.get("name") for row in labels]
             if isinstance(labels, list) and all(isinstance(row, dict) for row in labels) else [])
    if (type(owner_id) is not int or owner_id < 1
            or not isinstance(labels, list) or any(not isinstance(row, dict) for row in labels)
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
    origin, _digest, origin_row = _carrier(
        github, issue_number, epoch["applied_comment_id"], ORIGIN_APPLIED,
        epoch["applied_body_sha256"], owner_id,
    )
    if (not _repo_matches(origin.get("repository"), github.repo)
            or origin.get("issue_number") != issue_number or origin.get("epoch_id") != epoch["epoch_id"]
            or origin.get("adc_comment_id") != epoch["adc_comment_id"]
            or origin.get("adc_sha256") != epoch["adc_sha256"]
            or origin.get("base_ref") != epoch.get("base_ref")
            or origin.get("base_sha40") != epoch.get("base_sha40")
            or origin.get("branch_ref") != epoch.get("branch_ref")):
        raise CurrentEpochError("execution epoch origin Applied does not match the immutable origin")
    if (origin.get("intent_comment_id") != epoch["intent_comment_id"]
            or origin.get("intent_body_sha256") != epoch["intent_body_sha256"]):
        raise CurrentEpochError("execution epoch origin Applied does not bind its exact Intent")
    origin_intent, _intent_digest, _origin_intent_row = _carrier(
        github, issue_number, epoch["intent_comment_id"], ORIGIN_INTENT,
        epoch["intent_body_sha256"], owner_id,
    )
    if (not _repo_matches(origin_intent.get("repository"), github.repo)
            or origin_intent.get("issue_number") != issue_number
            or origin_intent.get("epoch_id") != epoch["epoch_id"]
            or origin_intent.get("adc_comment_id") != epoch["adc_comment_id"]
            or origin_intent.get("adc_sha256") != epoch["adc_sha256"]
            or origin_intent.get("base_ref") != epoch.get("base_ref")
            or origin_intent.get("base_sha40") != epoch.get("base_sha40")
            or origin_intent.get("branch_ref") != epoch.get("branch_ref")):
        raise CurrentEpochError("execution epoch origin Intent does not match its Applied")
    pinned = _validate_pinned_rework_timestamps(github, issue_number, current, owner_id)
    pinned_rework_ids = pinned[0] if pinned is not None else None
    pinned_v3_ids = pinned[1] if pinned is not None else None
    active_id = epoch["applied_comment_id"]
    active_sha = epoch["applied_body_sha256"]
    # Only records newer than this immutable epoch origin can define its active
    # Phase generation. Every post-origin V3 Intent/Applied must form one exact pair.
    count = issue.get("comments")
    if type(count) is not int or count < 1:
        raise CurrentEpochError("current Issue comment count is unavailable")
    origin_id = epoch["applied_comment_id"]
    reached_origin = False
    rework_intents: list[tuple[int, dict[str, Any], str]] = []
    rework_applied: list[tuple[int, dict[str, Any], str]] = []
    scanned_ids: set[int] = set()
    previous_page_min: int | None = None
    for page in github.issue_comment_pages_newest(issue_number, count):
        if not isinstance(page, list):
            raise CurrentEpochError("current Issue comment page is malformed")
        page_ids = [row.get("id") if isinstance(row, dict) else None for row in page]
        if (any(type(identifier) is not int or identifier < 1 for identifier in page_ids)
                or page_ids != sorted(set(page_ids))):
            raise CurrentEpochError("current Issue comment page order or IDs are invalid")
        if previous_page_min is not None and page_ids and page_ids[-1] >= previous_page_min:
            raise CurrentEpochError("current Issue comment page order overlaps or regresses")
        if page_ids:
            previous_page_min = page_ids[0]
        for row in reversed(page):
            identifier = row["id"]
            if identifier in scanned_ids:
                raise CurrentEpochError("current Issue comment pages contain a duplicate ID")
            scanned_ids.add(identifier)
            if identifier == origin_id:
                if (row.get("body") != origin_row.get("body")
                        or row.get("created_at") != origin_row.get("created_at")
                        or row.get("updated_at") != origin_row.get("updated_at")):
                    raise CurrentEpochError("immutable epoch origin differs between direct and page reads")
                reached_origin = True
                break
            if identifier < origin_id:
                raise CurrentEpochError("current Issue comment ordering crossed the immutable epoch origin")
            body = row.get("body")
            if not isinstance(body, str):
                raise CurrentEpochError("current Issue comment body is malformed")
            candidate_kind = _rework_candidate_kind(body)
            if candidate_kind == "intent":
                if body.startswith("<!-- PASES_ISSUE_VERIFICATION_REWORK_INTENT_V2\n"):
                    if pinned_rework_ids is not None and identifier in pinned_rework_ids:
                        continue
                    raise CurrentEpochError("post-origin V2 Phase Intent is not pinned by the current ADC")
                if not body.startswith(f"<!-- {REWORK_INTENT}\n"):
                    raise CurrentEpochError("post-origin Phase Intent has an unsupported or malformed schema")
                data, _digest, direct = _carrier(
                    github, issue_number, identifier, REWORK_INTENT, None, owner_id,
                )
                if (row.get("body") != direct.get("body")
                        or row.get("created_at") != direct.get("created_at")
                        or row.get("updated_at") != direct.get("updated_at")):
                    raise CurrentEpochError("current Phase Intent differs between direct and page reads")
                validate_rework_publication_window(data, direct, "created_at")
                if (not _repo_matches(data.get("repository"), github.repo)
                        or data.get("issue_number") != issue_number
                        or data.get("active_epoch_id") != epoch["epoch_id"]
                        or data.get("active_epoch_sha256") != digest
                        or data.get("branch_ref") != epoch["branch_ref"]):
                    raise CurrentEpochError("current Phase Intent does not bind the active epoch")
                rework_intents.append((identifier, data, _sha(direct["body"].encode("utf-8"))))
            elif candidate_kind == "applied":
                if body.startswith("<!-- PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V2\n"):
                    if pinned_rework_ids is not None and identifier in pinned_rework_ids:
                        continue
                    raise CurrentEpochError("post-origin V2 Phase Applied is not pinned by the current ADC")
                if not body.startswith(f"<!-- {REWORK_APPLIED}\n"):
                    raise CurrentEpochError("post-origin Phase Applied has an unsupported or malformed schema")
                data, applied_digest, direct = _carrier(
                    github, issue_number, identifier, REWORK_APPLIED, None, owner_id,
                )
                if (row.get("body") != direct.get("body")
                        or row.get("created_at") != direct.get("created_at")
                        or row.get("updated_at") != direct.get("updated_at")):
                    raise CurrentEpochError("current Phase Applied differs between direct and page reads")
                validate_rework_publication_window(data, direct, "applied_at")
                if (not _repo_matches(data.get("repository"), github.repo)
                        or data.get("issue_number") != issue_number
                        or data.get("active_epoch_id") != epoch["epoch_id"]
                        or data.get("active_epoch_sha256") != digest
                        or data.get("branch_ref") != epoch["branch_ref"]):
                    raise CurrentEpochError("current Phase Applied does not bind the active epoch")
                rework_applied.append((identifier, data, applied_digest))
            elif candidate_kind is not None:
                raise CurrentEpochError("post-origin Phase rework marker has an unsupported or malformed schema")
        if reached_origin:
            break
    if not reached_origin:
        raise CurrentEpochError("immutable epoch origin was not found in current Issue comments")
    if len(rework_intents) > 1 or len(rework_applied) > 1:
        raise CurrentEpochError("post-origin Phase rework contains duplicate Intent or Applied records")
    if len(rework_intents) != len(rework_applied):
        raise CurrentEpochError("post-origin Phase rework has an unmatched Intent or Applied record")
    if rework_intents:
        intent_id, intent_data, intent_sha = rework_intents[0]
        applied_id, applied_data, applied_sha = rework_applied[0]
        if (intent_id >= applied_id
                or applied_data.get("intent_comment_id") != intent_id
                or applied_data.get("intent_body_sha256") != intent_sha
                or any(intent_data.get(key) != applied_data.get(key)
                       for key in ("repository", "issue_number", "active_epoch_id",
                                   "active_epoch_sha256", "branch_ref", "adc_comment_id", "adc_sha256"))):
            raise CurrentEpochError("post-origin Phase Intent/Applied order or Intent digest is mismatched")
        active_id, active_sha = applied_id, applied_sha
    if pinned_rework_ids is not None:
        v3_ids = {identifier for identifier, _data, _sha_value in rework_intents + rework_applied}
        if v3_ids != pinned_v3_ids:
            raise CurrentEpochError("current ADC-pinned V3 Phase pair differs from the active generation")
    # The newest-first window can shift as comments arrive; never return a
    # potentially stale generation selected from a changed pagination count.
    if github.issue(issue_number).get("comments") != count:
        raise CurrentEpochError("current Issue comment count changed during epoch lookup")
    return ActiveExecutionEpoch(
        epoch, current.pointer.comment_id, current.pointer.sha256, active_id, active_sha,
    ).validate()
