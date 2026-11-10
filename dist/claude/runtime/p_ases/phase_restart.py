"""Exact-ADC-authorized, append-only Phase restart for ordinary Issues."""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .adc import ADCPointer, ADCError, VerifiedADC, verify_adc, verify_adc_generation
from .execution import ExecutionBinding, ExecutionError, binding_digest, read_binding_history
from .github import GitHub, GitHubError
from .git import GitError, current_branch, head_sha40, is_ancestor
from .phases import IssueKind, Phase, PhaseError, parse_phase_labels
from .phase_evidence import (
    PhaseDecision,
    PhaseEvidenceError,
    SENTINEL_V2 as DECISION_V2_SCHEMA,
    verify_historical_phase_decision,
)
from .work import execution_binding_path


AUTH_SCHEMA = "PASES_PHASE_RESTART_AUTHORIZATION_V1"
INTENT_SCHEMA = "PASES_PHASE_RESTART_INTENT_V1"
APPLIED_SCHEMA = "PASES_PHASE_RESTART_APPLIED_V1"
AUTH_OPEN = f"<!-- {AUTH_SCHEMA}"
INTENT_OPEN = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_OPEN = f"<!-- {APPLIED_SCHEMA}\n"
DECISION_MARKER_FAMILY = "PASES_PHASE_DECISION_V"
RESTART_PREFIX = "<!-- PASES_PHASE_RESTART_"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
AUTH_FIELDS = {"schema", "target_issue", "from_phase", "to_phase", "max_applications", "reason"}
COMMON_FIELDS = {
    "repository", "repository_id", "issue_number", "issue_id", "labels_before", "labels_after",
    "adc_comment_id", "adc_sha256", "adc_byte_length", "binding_generation",
    "binding_generation_id", "binding_sha256", "predecessor_phase_generation_comment_id",
    "predecessor_phase_generation_sha256", "authorization_sha256", "from_phase", "to_phase",
    "reason", "executor_user_id",
}
INTENT_FIELDS = COMMON_FIELDS | {"schema", "created_at"}
APPLIED_FIELDS = COMMON_FIELDS | {"schema", "intent_comment_id", "intent_sha256", "applied_at"}


class PhaseRestartError(ValueError):
    """The authorization, live Issue, or append-only restart history is invalid."""


@dataclass(frozen=True)
class RestartAuthorization:
    target_issue: str
    from_phase: str
    to_phase: str
    max_applications: int
    reason: str
    sha256: str


@dataclass(frozen=True)
class RestartRecord:
    comment_id: int
    schema: str
    payload: dict[str, Any]
    body: str
    actor_id: int
    created_at: str

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PhaseGeneration:
    comment_id: int
    sha256: str
    adc_comment_id: int
    adc_sha256: str
    binding_generation: int
    binding_generation_id: int
    binding_sha256: str


@dataclass(frozen=True)
class _LiveSubject:
    repository: str
    repository_id: int
    issue_number: int
    issue_id: int
    issue: dict[str, Any]
    labels: tuple[str, ...]
    verified_adc: VerifiedADC
    authorization: RestartAuthorization | None
    bindings: tuple[ExecutionBinding, ...]
    binding: ExecutionBinding
    binding_generation: int
    binding_sha256: str
    branch_ref: str
    head_sha40: str
    executor_user_id: int


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PhaseRestartError("authorization or restart JSON contains duplicate fields")
        result[key] = value
    return result


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise PhaseRestartError(f"{field} must be a lowercase SHA-256")
    return value


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise PhaseRestartError(f"{field} must be a positive integer")
    return value


def _strict_utc(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PhaseRestartError(f"{field} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PhaseRestartError(f"{field} is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PhaseRestartError(f"{field} must be UTC")
    if parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != value:
        raise PhaseRestartError(f"{field} is not canonical")
    return value


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_authorization(content: bytes, issue_number: int) -> RestartAuthorization:
    """Parse exactly one canonical authorization marker outside fenced code blocks."""
    if type(issue_number) is not int or issue_number < 1:
        raise PhaseRestartError("target Issue number must be positive")
    try:
        text = content.decode("utf-8", errors="strict")
    except (AttributeError, UnicodeDecodeError) as exc:
        raise PhaseRestartError("approved ADC must be valid UTF-8") from exc
    lines = text.splitlines()
    fence: tuple[str, int] | None = None
    blocks: list[str] = []
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        if fence is not None:
            marker, length = fence
            if re.match(rf"^ {{0,3}}{re.escape(marker)}{{{length},}}[ \t]*$", line):
                fence = None
            line_index += 1
            continue
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_match and (fence_match.group(1)[0] == "~" or "`" not in fence_match.group(2)):
            fence = (fence_match.group(1)[0], len(fence_match.group(1)))
            line_index += 1
            continue
        if AUTH_OPEN in line:
            if line != AUTH_OPEN or line_index + 2 >= len(lines) or lines[line_index + 2] != "-->":
                raise PhaseRestartError("authorization marker block is malformed")
            blocks.append(lines[line_index + 1])
            line_index += 3
            continue
        line_index += 1
    if len(blocks) != 1:
        raise PhaseRestartError("current approved ADC must contain exactly one authorization marker outside code fences")
    raw = blocks[0]
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseRestartError("authorization payload is malformed JSON") from exc
    if not isinstance(value, dict) or set(value) != AUTH_FIELDS:
        raise PhaseRestartError("authorization payload has unknown or missing fields")
    if _canonical(value) != raw:
        raise PhaseRestartError("authorization payload is not canonical JSON")
    if (value.get("schema") != AUTH_SCHEMA or value.get("target_issue") != "self"
            or value.get("from_phase") != Phase.EXECUTION.value
            or value.get("to_phase") != Phase.REQUIREMENTS.value
            or type(value.get("max_applications")) is not int or value["max_applications"] != 1):
        raise PhaseRestartError("authorization payload does not allow this exact one-time transition")
    reason = value.get("reason")
    if (not isinstance(reason, str) or reason != reason.strip() or not reason
            or len(reason) > 500 or any(ord(char) < 32 or ord(char) == 127 for char in reason)):
        raise PhaseRestartError("authorization reason must be trimmed text of 1–500 printable characters")
    return RestartAuthorization(
        value["target_issue"], value["from_phase"], value["to_phase"], value["max_applications"],
        reason, hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _parse_payload(body: Any, schema: str) -> dict[str, Any]:
    start = f"<!-- {schema}\n"
    if not isinstance(body, str) or not body.startswith(start) or not body.endswith("\n-->"):
        raise PhaseRestartError("Phase restart comment is malformed")
    raw = body[len(start):-len("\n-->")]
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseRestartError("Phase restart record JSON is malformed") from exc
    expected_fields = INTENT_FIELDS if schema == INTENT_SCHEMA else APPLIED_FIELDS
    if not isinstance(payload, dict) or set(payload) != expected_fields or payload.get("schema") != schema:
        raise PhaseRestartError("Phase restart record has unknown or missing fields")
    if _canonical(payload) != raw:
        raise PhaseRestartError("Phase restart record JSON is not canonical")
    _validate_record_payload(payload, schema)
    return payload


def _validate_record_payload(payload: dict[str, Any], schema: str) -> None:
    repository = payload.get("repository")
    if (not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)):
        raise PhaseRestartError("Phase restart repository is invalid")
    for key in ("repository_id", "issue_number", "issue_id", "adc_comment_id", "adc_byte_length",
                "binding_generation", "binding_generation_id", "executor_user_id"):
        _positive_int(payload.get(key), key)
    if payload["binding_generation_id"] != payload["adc_comment_id"]:
        raise PhaseRestartError("Binding generation ID must identify its ADC generation")
    if payload["adc_byte_length"] < 1:
        raise PhaseRestartError("ADC byte length must be positive")
    for key in ("adc_sha256", "binding_sha256", "authorization_sha256"):
        _sha256(payload.get(key), key)
    before, after = payload.get("labels_before"), payload.get("labels_after")
    if (not isinstance(before, list) or not isinstance(after, list)
            or any(not isinstance(label, str) or not label for label in before + after)
            or before != sorted(set(before)) or after != sorted(set(after))):
        raise PhaseRestartError("Phase restart label snapshots must be sorted, unique complete label sets")
    if (before.count("phase:execution") != 1
            or any(label.startswith("phase:") and label != "phase:execution" for label in before)
            or sum(label in {"kind:single", "kind:child"} for label in before) != 1
            or any(label.startswith("kind:") and label not in {"kind:single", "kind:child"} for label in before)):
        raise PhaseRestartError("Phase restart before-labels do not identify one eligible ordinary execution Issue")
    expected_after = sorted([label for label in before if label != "phase:execution"] + ["phase:requirements"])
    if after != expected_after:
        raise PhaseRestartError("Phase restart after-labels do not describe the exact transition")
    prior_id = payload.get("predecessor_phase_generation_comment_id")
    prior_sha = payload.get("predecessor_phase_generation_sha256")
    if (prior_id is None) != (prior_sha is None):
        raise PhaseRestartError("predecessor Phase generation identity and digest must both be null or present")
    if prior_id is not None:
        _positive_int(prior_id, "predecessor_phase_generation_comment_id")
        _sha256(prior_sha, "predecessor_phase_generation_sha256")
    if payload.get("from_phase") != Phase.EXECUTION.value or payload.get("to_phase") != Phase.REQUIREMENTS.value:
        raise PhaseRestartError("Phase restart record describes an unsupported transition")
    reason = payload.get("reason")
    if (not isinstance(reason, str) or not reason or reason != reason.strip() or len(reason) > 500
            or any(ord(char) < 32 or ord(char) == 127 for char in reason)):
        raise PhaseRestartError("Phase restart reason is invalid")
    if schema == INTENT_SCHEMA:
        _strict_utc(payload.get("created_at"), "created_at")
    else:
        _positive_int(payload.get("intent_comment_id"), "intent_comment_id")
        _sha256(payload.get("intent_sha256"), "intent_sha256")
        _strict_utc(payload.get("applied_at"), "applied_at")


def _parse_record(row: Any, schema: str) -> RestartRecord:
    if not isinstance(row, dict):
        raise PhaseRestartError("Phase restart carrier is not an object")
    comment_id = _positive_int(row.get("id"), "Phase restart Comment ID")
    user = row.get("user")
    if (not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] < 1
            or not isinstance(user.get("login"), str) or not user.get("login") or user.get("type") != "User"):
        raise PhaseRestartError("Phase restart carrier must have a human GitHub User author")
    body = row.get("body")
    payload = _parse_payload(body, schema)
    created_at = row.get("created_at")
    _strict_utc(created_at, "GitHub created_at")
    if row.get("updated_at") != created_at:
        raise PhaseRestartError("Phase restart carrier was edited")
    return RestartRecord(comment_id, schema, payload, body, user["id"], created_at)


def _expected_urls(repository: str, issue_number: int, comment_id: int) -> tuple[str, str, str]:
    return (
        f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}",
        f"https://api.github.com/repos/{repository}/issues/{issue_number}",
        f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}",
    )


def _row_fingerprint(row: Any, repository: str, issue_number: int) -> tuple[Any, ...]:
    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1:
        raise PhaseRestartError("Phase history carrier ID is invalid")
    expected = _expected_urls(repository, issue_number, row["id"])
    actual = (row.get("url"), row.get("issue_url"), row.get("html_url"))
    if actual != expected:
        raise PhaseRestartError("Phase history comment belongs to a different repository or Issue")
    user = row.get("user")
    if (not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] < 1
            or user.get("type") != "User" or not isinstance(user.get("login"), str) or not user["login"]):
        raise PhaseRestartError("Phase history comment author is incomplete or not a human User")
    body = row.get("body")
    created, updated = row.get("created_at"), row.get("updated_at")
    _strict_utc(created, "GitHub created_at")
    if not isinstance(body, str) or updated != created:
        raise PhaseRestartError("Phase history comment body or immutable timestamps are invalid")
    return (row["id"], body, created, updated, user["id"], user["login"].casefold(), user["type"], *actual)


def _is_phase_decision_candidate(body: str) -> bool:
    """Treat malformed edits of a reserved decision header as history, then fail closed."""
    first_line = body.split("\n", 1)[0].lstrip()
    return first_line.startswith(DECISION_MARKER_FAMILY)


def _is_restart_candidate(body: str) -> bool:
    """Keep malformed edits of Intent/Applied markers visible to every journal reader."""
    first_line = body.split("\n", 1)[0].lstrip()
    if first_line.startswith("PASES_PHASE_RESTART_"):
        return True
    return re.match(r"^<[\s!\-]{0,12}PASES_PHASE_RESTART_", first_line) is not None


@dataclass(frozen=True)
class _History:
    restarts: tuple[RestartRecord, ...]
    decisions: tuple[tuple[int, Any, str, int], ...]


def _read_history(github: GitHub, issue_number: int) -> _History:
    """Read every restart and Phase decision carrier with complete direct/list/direct snapshots."""
    try:
        first = github.issue_comments(issue_number)
        first_rows = [row for row in first if isinstance(row, dict)
                      and isinstance(row.get("body"), str)
                      and (_is_restart_candidate(row["body"])
                           or _is_phase_decision_candidate(row["body"]))]
        ids = [row.get("id") for row in first_rows]
        if (any(type(value) is not int or value < 1 for value in ids)
                or ids != sorted(ids) or len(ids) != len(set(ids))):
            raise PhaseRestartError("Phase history is duplicated or not append-only")
        def direct_readback() -> dict[int, dict[str, Any]]:
            if not ids:
                return {}
            with ThreadPoolExecutor(max_workers=min(8, len(ids))) as executor:
                rows = list(executor.map(lambda value: github.issue_comment(issue_number, value), ids))
            return dict(zip(ids, rows, strict=True))
        before = direct_readback()
        second = github.issue_comments(issue_number)
        second_rows = [row for row in second if isinstance(row, dict)
                       and isinstance(row.get("body"), str)
                       and (_is_restart_candidate(row["body"])
                            or _is_phase_decision_candidate(row["body"]))]
        second_ids = [row.get("id") for row in second_rows]
        if second_ids != ids:
            raise PhaseRestartError("Phase history changed during direct/list/direct readback")
        after = direct_readback()
    except GitHubError as exc:
        raise PhaseRestartError(f"Phase history readback failed: {exc}") from exc

    restarts: list[RestartRecord] = []
    decisions: list[tuple[int, Any, str, int]] = []
    needs_authenticated_decision_author = any(
        _is_phase_decision_candidate(row["body"]) for row in first_rows
    )
    try:
        authenticated = github.authenticated_user() if needs_authenticated_decision_author else None
    except GitHubError as exc:
        raise PhaseRestartError(f"Phase decision author identity is unavailable: {exc}") from exc
    for listed, second_row in zip(first_rows, second_rows, strict=True):
        comment_id = listed["id"]
        triples = tuple(_row_fingerprint(row, github.repo, issue_number)
                        for row in (before[comment_id], second_row, after[comment_id]))
        if triples[0] != triples[1] or triples[1] != triples[2]:
            raise PhaseRestartError("Phase history identity changed during direct/list/direct readback")
        body = listed["body"]
        if _is_restart_candidate(body):
            schema = INTENT_SCHEMA if body.startswith(INTENT_OPEN) else (
                APPLIED_SCHEMA if body.startswith(APPLIED_OPEN) else None
            )
            if schema is None:
                raise PhaseRestartError("unknown or malformed Phase restart marker")
            restarts.append(_parse_record(before[comment_id], schema))
        else:
            try:
                decision = PhaseDecision.from_body(body)
            except PhaseEvidenceError as exc:
                raise PhaseRestartError(f"Phase Decision reserved marker is malformed: {exc}") from exc
            author = before[comment_id].get("user")
            if (not isinstance(authenticated, dict) or not isinstance(author, dict)
                    or author.get("id") != authenticated.get("id")
                    or not isinstance(author.get("login"), str)
                    or not isinstance(authenticated.get("login"), str)
                    or author["login"].casefold() != authenticated["login"].casefold()
                    or author.get("type") != "User" or authenticated.get("type") != "User"):
                raise PhaseRestartError("Phase Decision author is not the authenticated GitHub User")
            decisions.append((comment_id, decision, body, before[comment_id]["user"]["id"]))
    return _History(tuple(restarts), tuple(decisions))


def _record_generation(record: RestartRecord) -> tuple[int, str]:
    return record.comment_id, record.body_sha256


def _validate_history(github: GitHub, issue: dict[str, Any], repository_id: int,
                      bindings: tuple[ExecutionBinding, ...], history: _History,
                      *, allow_pending_adc_comment_id: int | None = None) -> tuple[RestartRecord, ...]:
    issue_number, issue_id = issue.get("number"), issue.get("id")
    ordered = sorted(history.restarts, key=lambda record: record.comment_id)
    if tuple(ordered) != history.restarts:
        raise PhaseRestartError("Phase restart records are not ordered by comment ID")
    decisions = sorted(history.decisions, key=lambda row: row[0])
    for comment_id, decision, body, _actor_id in decisions:
        payload = decision.payload
        if (payload.get("repository", "").casefold() != github.repo.casefold()
                or payload.get("issue_number") != issue_number or not body.endswith("\n")):
            raise PhaseRestartError("historical Phase decision belongs to a different Issue")
        if payload.get("schema") == "PASES_PHASE_DECISION_V2":
            generation_id = payload.get("phase_generation_comment_id")
            generation_sha = payload.get("phase_generation_sha256")
            matches = [record for record in ordered if record.schema == APPLIED_SCHEMA
                       and record.comment_id == generation_id and record.body_sha256 == generation_sha]
            if len(matches) != 1 or matches[0].comment_id >= comment_id:
                raise PhaseRestartError("Phase Decision V2 does not reference one prior Applied generation")

    duplicate_decisions: set[tuple[Any, ...]] = set()
    for _comment_id, decision, _body, _actor_id in decisions:
        payload = decision.payload
        key = (payload.get("adc_comment_id"), payload.get("adc_sha256"), payload.get("from_phase"),
               payload.get("to_phase"), payload.get("phase_generation_comment_id"),
               payload.get("phase_generation_sha256"))
        if key in duplicate_decisions:
            raise PhaseRestartError("Phase decision history contains a duplicate transition subject")
        duplicate_decisions.add(key)

    grouped_intents: dict[int, list[RestartRecord]] = {}
    grouped_applied: dict[int, list[RestartRecord]] = {}
    for record in ordered:
        payload = record.payload
        if (payload["repository"].casefold() != github.repo.casefold()
                or payload["repository_id"] != repository_id
                or payload["issue_number"] != issue_number or payload["issue_id"] != issue_id):
            raise PhaseRestartError("Phase restart history belongs to a different repository or Issue identity")
        if record.schema == INTENT_SCHEMA:
            grouped_intents.setdefault(payload["adc_comment_id"], []).append(record)
        else:
            grouped_applied.setdefault(payload["adc_comment_id"], []).append(record)

    if any(len(rows) != 1 for rows in grouped_intents.values()) or any(
            len(rows) != 1 for rows in grouped_applied.values()):
        raise PhaseRestartError("ADC phase restart authorization was duplicated")
    if set(grouped_applied) - set(grouped_intents):
        raise PhaseRestartError("Applied Phase restart has no Intent")

    previous_restart_applied: RestartRecord | None = None
    for intent in ordered:
        if intent.schema != INTENT_SCHEMA:
            continue
        payload = intent.payload
        applied_rows = grouped_applied.get(payload["adc_comment_id"], [])
        applied = applied_rows[0] if applied_rows else None
        if intent.comment_id <= payload["adc_comment_id"]:
            raise PhaseRestartError("Phase restart Intent predates its approved ADC")
        if intent.actor_id != payload["executor_user_id"]:
            raise PhaseRestartError("Phase restart Intent author differs from its recorded human executor")
        if (payload["predecessor_phase_generation_comment_id"] is not None
                and intent.comment_id <= payload["predecessor_phase_generation_comment_id"]):
            raise PhaseRestartError("Phase restart Intent predates its active Phase predecessor")
        if previous_restart_applied is not None and intent.comment_id <= previous_restart_applied.comment_id:
            raise PhaseRestartError("Phase restart Intent chain is not append-only")
        # The active generation is the latest phase journal event before the
        # Intent. A later Phase Decision can supersede an older Applied record.
        predecessor_id, predecessor_sha = _active_generation_before(history, intent.comment_id)
        if (payload["predecessor_phase_generation_comment_id"] != predecessor_id
                or payload["predecessor_phase_generation_sha256"] != predecessor_sha):
            raise PhaseRestartError("Phase restart Intent does not bind the prior active Phase generation")

        binding_rows = [(index, binding) for index, binding in enumerate(bindings, start=1)
                        if binding.adc_comment_id == payload["binding_generation_id"]]
        if len(binding_rows) != 1:
            raise PhaseRestartError("Phase restart history references a missing/duplicate Binding generation")
        index, binding = binding_rows[0]
        if (index != payload["binding_generation"] or binding.adc_sha256 != payload["adc_sha256"]
                or binding.repository.casefold() != github.repo.casefold()
                or binding.issue_number != issue_number
                or binding_digest(binding) != payload["binding_sha256"]):
            raise PhaseRestartError("Phase restart history does not match its immutable Binding generation")
        try:
            old_adc = verify_adc_generation(
                github, issue_number, payload["adc_comment_id"], payload["adc_sha256"], state="approved",
            )
            old_auth = parse_authorization(old_adc.contract.content, issue_number)
        except (ADCError, GitHubError) as exc:
            raise PhaseRestartError(f"Phase restart history ADC readback failed: {exc}") from exc
        if (old_adc.pointer.byte_length != payload["adc_byte_length"]
                or old_auth.sha256 != payload["authorization_sha256"]
                or old_auth.reason != payload["reason"]):
            raise PhaseRestartError("Phase restart history no longer matches its approved ADC authorization")

        if applied is not None:
            if (applied.comment_id <= intent.comment_id
                    or applied.payload["intent_comment_id"] != intent.comment_id
                    or applied.payload["intent_sha256"] != intent.body_sha256
                    or intent.actor_id != intent.payload["executor_user_id"]
                    or applied.actor_id != intent.actor_id):
                raise PhaseRestartError("Applied Phase restart does not match its exact Intent author and digest")
            for key in COMMON_FIELDS:
                if applied.payload[key] != payload[key]:
                    raise PhaseRestartError("Applied Phase restart changed its Intent subject")
            previous_restart_applied = applied
        else:
            if payload["adc_comment_id"] != allow_pending_adc_comment_id:
                raise PhaseRestartError("an incomplete prior-ADC Phase restart Intent blocks a new generation")
            if (any(record.comment_id > intent.comment_id for record in ordered)
                    or any(comment_id > intent.comment_id for comment_id, _decision, _body, _actor in decisions)):
                raise PhaseRestartError("incomplete Phase restart Intent is not the latest phase journal operation")
    return ordered


def _binding_history(root: Path, issue_number: int) -> tuple[ExecutionBinding, ...]:
    path = execution_binding_path(root.resolve(), issue_number)
    try:
        rows = read_binding_history(path)
    except ExecutionError as exc:
        raise PhaseRestartError(f"a complete append-only ExecutionBinding history is required: {exc}") from exc
    if not rows:
        raise PhaseRestartError("ExecutionBinding history is empty")
    return rows


def _live_subject(github: GitHub, root: Path, issue_number: int, *, require_execution_phase: bool) -> _LiveSubject:
    if type(issue_number) is not int or issue_number < 1:
        raise PhaseRestartError("Issue number must be positive")
    if issue_number == 63:
        raise PhaseRestartError("Issue #63 must use its existing specialized phase-rebaseline route")
    try:
        metadata = github.repository_metadata()
        full_name = metadata.get("full_name")
        if (type(metadata.get("id")) is not int or metadata["id"] < 1
                or not isinstance(full_name, str) or full_name.casefold() != github.repo.casefold()):
            raise PhaseRestartError("repository stable identity is missing or mismatched")
        issue = github.issue(issue_number)
        repository_url = issue.get("repository_url")
        if (type(issue.get("number")) is not int or issue.get("number") != issue_number
                or type(issue.get("id")) is not int or issue["id"] < 1
                or issue.get("state") != "open" or issue.get("pull_request") is not None
                or not isinstance(repository_url, str) or repository_url.casefold()
                != f"https://api.github.com/repos/{github.repo}".casefold()):
            raise PhaseRestartError("restart requires the exact open non-PR Issue in this repository")
        label_rows = issue.get("labels")
        if not isinstance(label_rows, list) or any(not isinstance(row, dict) for row in label_rows):
            raise PhaseRestartError("Issue label readback is incomplete")
        labels = [row.get("name") for row in label_rows]
        if any(not isinstance(label, str) or not label for label in labels) or len(labels) != len(set(labels)):
            raise PhaseRestartError("Issue label set is malformed or duplicated")
        stable_labels = tuple(sorted(labels))
        kind_labels = [label for label in stable_labels if label.startswith("kind:")]
        if len(kind_labels) != 1 or kind_labels[0] not in {"kind:single", "kind:child"}:
            raise PhaseRestartError("restart requires exactly one kind:single or kind:child label")
        phase = parse_phase_labels(stable_labels)
        if require_execution_phase and phase is not Phase.EXECUTION:
            raise PhaseRestartError("restart applies only from the exact phase:execution state")
        verified = verify_adc(github, issue_number)
        if verified.pointer.state != "approved":
            raise PhaseRestartError("current ADC pointer is not approved")
        authorization = parse_authorization(verified.contract.content, issue_number)
        bindings = _binding_history(root, issue_number)
        binding = bindings[-1]
        branch_ref = current_branch(root)
        head_sha = head_sha40(root)
        remote_branch = github.branch(branch_ref)
        remote_sha = remote_branch.get("commit", {}).get("sha")
        if (binding.repository.casefold() != github.repo.casefold() or binding.issue_number != issue_number
                or binding.adc_comment_id != verified.pointer.comment_id
                or binding.adc_sha256 != verified.contract.sha256
                or binding.branch_ref != branch_ref
                or Path(binding.work_directory).resolve() != root.resolve()
                or binding.initial_head_sha != binding.base_sha
                or not is_ancestor(root, binding.base_sha, head_sha)
                or remote_branch.get("name") != branch_ref or remote_sha != head_sha):
            raise PhaseRestartError("current approved ADC and frozen ExecutionBinding do not match the live branch/worktree")
        actor = github.authenticated_user()
        return _LiveSubject(
            github.repo, metadata["id"], issue_number, issue["id"], issue, stable_labels,
            verified, authorization, bindings, binding, len(bindings), binding_digest(binding),
            branch_ref, head_sha, actor["id"],
        )
    except (ADCError, ExecutionError, GitError, GitHubError, PhaseError) as exc:
        raise PhaseRestartError(str(exc)) from exc


def _active_generation_before(history: _History, before_comment_id: int | None = None
                              ) -> tuple[int | None, str | None]:
    """Return the latest Applied or Phase Decision event before an operation."""
    events: list[tuple[int, str]] = []
    for record in history.restarts:
        if (record.schema == APPLIED_SCHEMA
                and (before_comment_id is None or record.comment_id < before_comment_id)):
            events.append(_record_generation(record))
    for comment_id, _decision, body, _actor_id in history.decisions:
        if before_comment_id is None or comment_id < before_comment_id:
            events.append((comment_id, hashlib.sha256(body.encode("utf-8")).hexdigest()))
    return max(events, key=lambda event: event[0]) if events else (None, None)


def _validate_journal(github: GitHub, subject: _LiveSubject, history: _History,
                      *, allow_pending_adc_comment_id: int | None = None) -> tuple[RestartRecord, ...]:
    return _validate_history(
        github, subject.issue, subject.repository_id, subject.bindings, history,
        allow_pending_adc_comment_id=allow_pending_adc_comment_id,
    )


def _record_body(schema: str, payload: Mapping[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(payload)}\n-->"


def _intent_payload(subject: _LiveSubject, history: _History) -> dict[str, Any]:
    if subject.authorization is None:
        raise PhaseRestartError("current approved ADC has no typed Phase restart authorization")
    labels_before = list(subject.labels)
    labels_after = sorted([label for label in labels_before if label != "phase:execution"]
                          + ["phase:requirements"])
    predecessor_id, predecessor_sha = _active_generation_before(history)
    return {
        "schema": INTENT_SCHEMA,
        "repository": subject.repository,
        "repository_id": subject.repository_id,
        "issue_number": subject.issue_number,
        "issue_id": subject.issue_id,
        "labels_before": labels_before,
        "labels_after": labels_after,
        "adc_comment_id": subject.verified_adc.pointer.comment_id,
        "adc_sha256": subject.verified_adc.contract.sha256,
        "adc_byte_length": subject.verified_adc.contract.byte_length,
        "binding_generation": subject.binding_generation,
        "binding_generation_id": subject.binding.adc_comment_id,
        "binding_sha256": subject.binding_sha256,
        "predecessor_phase_generation_comment_id": predecessor_id,
        "predecessor_phase_generation_sha256": predecessor_sha,
        "authorization_sha256": subject.authorization.sha256,
        "from_phase": Phase.EXECUTION.value,
        "to_phase": Phase.REQUIREMENTS.value,
        "reason": subject.authorization.reason,
        "executor_user_id": subject.executor_user_id,
        "created_at": _timestamp(),
    }


def _applied_payload(intent: RestartRecord) -> dict[str, Any]:
    payload = dict(intent.payload)
    payload["schema"] = APPLIED_SCHEMA
    payload.pop("created_at")
    payload["intent_comment_id"] = intent.comment_id
    payload["intent_sha256"] = intent.body_sha256
    payload["applied_at"] = _timestamp()
    return payload


def _post_once(github: GitHub, issue_number: int, schema: str, payload: Mapping[str, Any]) -> RestartRecord:
    body = _record_body(schema, payload)
    write_error: GitHubError | None = None
    try:
        created = github.create_issue_comment(issue_number, body)
        comment_id = created.get("id") if isinstance(created, dict) else None
    except GitHubError as exc:
        write_error = exc
        comment_id = None
    try:
        history = _read_history(github, issue_number)
    except PhaseRestartError as exc:
        if write_error is not None:
            raise PhaseRestartError(f"Phase record POST failed and readback is unavailable: {exc}") from write_error
        raise
    candidates = [row for row in history.restarts if row.schema == schema and row.body == body]
    if len(candidates) != 1:
        reason = "lost response could not be reconciled" if write_error else "POST response has no unique exact readback"
        raise PhaseRestartError(f"{reason}; no retry was attempted")
    record = candidates[0]
    if comment_id is not None and comment_id != record.comment_id:
        raise PhaseRestartError("POST response Comment ID differs from exact direct/list/direct readback")
    if record.payload["executor_user_id"] != record.actor_id:
        raise PhaseRestartError("Phase record author does not match its authenticated executor")
    return record


def _refresh_labels(github: GitHub, subject: _LiveSubject) -> tuple[dict[str, Any], tuple[str, ...]]:
    try:
        issue = github.issue(subject.issue_number)
    except GitHubError as exc:
        raise PhaseRestartError(f"Issue label readback failed: {exc}") from exc
    rows = issue.get("labels")
    repository_url = issue.get("repository_url")
    if (type(issue.get("number")) is not int or issue.get("number") != subject.issue_number
            or type(issue.get("id")) is not int or issue.get("id") != subject.issue_id
            or issue.get("state") != "open" or issue.get("pull_request") is not None
            or not isinstance(repository_url, str) or repository_url.casefold()
            != f"https://api.github.com/repos/{subject.repository}".casefold()
            or issue.get("body") != subject.issue.get("body")
            or not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)):
        raise PhaseRestartError("Issue identity changed during Phase restart")
    labels = [row.get("name") for row in rows]
    if any(not isinstance(label, str) for label in labels) or len(labels) != len(set(labels)):
        raise PhaseRestartError("Issue labels changed to an incomplete or duplicate state")
    return issue, tuple(sorted(labels))


def _validated_current_journal(github: GitHub, subject: _LiveSubject,
                               *, allow_pending_adc_comment_id: int | None = None) -> _History:
    history = _read_history(github, subject.issue_number)
    _validate_journal(github, subject, history,
                       allow_pending_adc_comment_id=allow_pending_adc_comment_id)
    return history


def current_phase_generation(github: GitHub, root: Path, issue_number: int,
                             verified_adc: VerifiedADC) -> PhaseGeneration | None:
    """Return the exact active restart Applied record for the current ADC/Binding, if any."""
    bindings = _binding_history(root, issue_number)
    binding = bindings[-1]
    if (binding.repository.casefold() != github.repo.casefold() or binding.issue_number != issue_number
            or binding.adc_comment_id != verified_adc.pointer.comment_id
            or binding.adc_sha256 != verified_adc.contract.sha256):
        raise PhaseRestartError("phase generation requires the current ADC-bound ExecutionBinding")
    try:
        comments = github.issue_comments(issue_number)
    except GitHubError as exc:
        raise PhaseRestartError(f"Phase restart generation history is unavailable: {exc}") from exc
    markers = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
               and _is_restart_candidate(row["body"])]
    decision_candidates = [row for row in comments
                           if isinstance(row, dict) and isinstance(row.get("body"), str)
                           and _is_phase_decision_candidate(row["body"])]
    if not markers:
        if decision_candidates:
            history = _read_history(github, issue_number)
            expected_decisions = [(row.get("id"), row["body"]) for row in decision_candidates]
            observed_decisions = [(comment_id, body)
                                  for comment_id, _decision, body, _actor_id in history.decisions]
            if history.restarts or observed_decisions != expected_decisions:
                raise PhaseRestartError("Phase history changed during generation read")
            if any(decision.payload.get("schema") == DECISION_V2_SCHEMA
                   for _comment_id, decision, _body, _actor_id in history.decisions):
                raise PhaseRestartError("Phase Decision V2 exists without its Applied generation history")
        return None
    issue = github.issue(issue_number)
    metadata = github.repository_metadata()
    subject = _LiveSubject(
        github.repo, metadata.get("id"), issue_number, issue.get("id"), issue,
        tuple(sorted(row.get("name") for row in issue.get("labels", []) if isinstance(row, dict))),
        verified_adc, None, bindings, binding,
        len(bindings), binding_digest(binding), binding.branch_ref, "0" * 40, 1,
    )
    history = _validated_current_journal(github, subject)
    intents = [record for record in history.restarts if record.schema == INTENT_SCHEMA
               and record.payload["adc_comment_id"] == verified_adc.pointer.comment_id]
    applied = [record for record in history.restarts if record.schema == APPLIED_SCHEMA
               and record.payload["adc_comment_id"] == verified_adc.pointer.comment_id]
    if len(intents) > 1 or len(applied) > 1:
        raise PhaseRestartError("current ADC phase restart history is duplicated")
    if intents and not applied:
        raise PhaseRestartError("current ADC has an incomplete Phase restart Intent")
    if not applied:
        return None
    record = applied[0]
    if (record.payload["binding_generation_id"] != binding.adc_comment_id
            or record.payload["binding_sha256"] != binding_digest(binding)):
        raise PhaseRestartError("current ADC Applied Phase generation does not match the current Binding")
    return PhaseGeneration(
        record.comment_id, record.body_sha256, verified_adc.pointer.comment_id,
        verified_adc.contract.sha256, len(bindings), binding.adc_comment_id, binding_digest(binding),
    )


def _verify_generation_history(github: GitHub, subject: _LiveSubject, history: _History,
                               *, allow_pending_adc_comment_id: int | None = None
                               ) -> tuple[RestartRecord, ...]:
    rows = _validate_journal(github, subject, history,
                             allow_pending_adc_comment_id=allow_pending_adc_comment_id)
    for record in rows:
        payload = record.payload
        binding = subject.bindings[payload["binding_generation"] - 1]
        if binding.adc_comment_id != payload["binding_generation_id"]:
            raise PhaseRestartError("restart history Binding generation index is inconsistent")
    return rows


def _labels_for_phase(labels: list[str] | tuple[str, ...], phase: Phase) -> tuple[str, ...]:
    return tuple(sorted([label for label in labels if not label.startswith("phase:")]
                        + [f"phase:{phase.value}"]))


def _verified_phase_after_restart(github: GitHub, subject: _LiveSubject, applied: RestartRecord,
                                  history: _History, root: Path) -> Phase:
    """Validate the same-generation Phase Decision chain after an Applied record."""
    phase = Phase.REQUIREMENTS
    previous_commit: str | None = None
    allowed_edges = {
        (Phase.REQUIREMENTS, Phase.SPECIFICATION),
        (Phase.REQUIREMENTS, Phase.DESIGN),
        (Phase.REQUIREMENTS, Phase.READY),
        (Phase.SPECIFICATION, Phase.DESIGN),
        (Phase.SPECIFICATION, Phase.READY),
        (Phase.DESIGN, Phase.READY),
    }
    later = [row for row in history.decisions if row[0] > applied.comment_id]
    for comment_id, decision, _body, _actor_id in later:
        payload = decision.payload
        if payload.get("schema") != DECISION_V2_SCHEMA:
            raise PhaseRestartError("Phase Decision after Applied is not generation-bound V2")
        if (payload.get("phase_generation_comment_id") != applied.comment_id
                or payload.get("phase_generation_sha256") != applied.body_sha256
                or payload.get("adc_comment_id") != applied.payload["adc_comment_id"]
                or payload.get("adc_sha256") != applied.payload["adc_sha256"]
                or payload.get("repository", "").casefold() != subject.repository.casefold()
                or payload.get("issue_number") != subject.issue_number
                or payload.get("issue_kind") != next(
                    label.removeprefix("kind:") for label in subject.labels if label.startswith("kind:")
                )
                or payload.get("branch_ref") != subject.branch_ref):
            raise PhaseRestartError("Phase Decision does not match the current Applied ADC/Binding generation")
        source = Phase(payload["from_phase"])
        target = Phase(payload["to_phase"])
        if source is not phase or (source, target) not in allowed_edges:
            raise PhaseRestartError("same-generation Phase Decision chain is discontinuous or not forward-only")
        commit = payload["commit_sha40"]
        try:
            if (not is_ancestor(root, commit, subject.head_sha40)
                    or (previous_commit is not None and not is_ancestor(root, previous_commit, commit))):
                raise PhaseRestartError("Phase Decision commit is stale or out of chain order")
        except GitError as exc:
            raise PhaseRestartError(f"Phase Decision commit ancestry cannot be verified: {exc}") from exc
        try:
            kind_label = next(label for label in subject.labels if label.startswith("kind:"))
            verify_historical_phase_decision(
                github, root, subject.issue_number, decision,
                verified_adc=subject.verified_adc, issue_kind=IssueKind(kind_label.removeprefix("kind:")),
                branch_ref=subject.branch_ref, current_sha40=subject.head_sha40,
                phase_generation=(applied.comment_id, applied.body_sha256),
            )
        except PhaseEvidenceError as exc:
            raise PhaseRestartError(f"same-generation Phase Decision is not valid: {exc}") from exc
        phase = target
        previous_commit = commit
    return phase


def _verify_ready_before_execution(github: GitHub, root: Path, subject: _LiveSubject,
                                   applied: RestartRecord) -> None:
    """Revalidate the same-generation READY proof for a later execution label."""
    try:
        from .phase_evidence import (
            PhaseEvidenceError, VerifiedOrdinaryIssueContext, verify_ready_preparation,
        )

        labels = list(applied.payload["labels_after"])
        ready_labels = list(_labels_for_phase(labels, Phase.READY))
        ready_issue = dict(subject.issue)
        ready_issue["labels"] = [{"name": label} for label in ready_labels]
        kind_label = next(label for label in ready_labels if label.startswith("kind:"))
        kind = IssueKind(kind_label.removeprefix("kind:"))
        context = VerifiedOrdinaryIssueContext(
            ready_issue, subject.verified_adc, kind, subject.branch_ref,
            subject.head_sha40, True,
        )
        verify_ready_preparation(github, root, subject.issue_number, kind, verified_context=context)
    except PhaseEvidenceError as exc:
        raise PhaseRestartError(f"same-generation READY proof is not valid for execution: {exc}") from exc


def restart_issue_phase(github: GitHub, root: Path, issue_number: int) -> dict[str, Any]:
    """Apply or read-only recover one ADC-authorized ordinary Issue phase restart."""
    subject = _live_subject(github, root, issue_number, require_execution_phase=False)
    try:
        history = _read_history(github, issue_number)
        records = _verify_generation_history(
            github, subject, history,
            allow_pending_adc_comment_id=subject.verified_adc.pointer.comment_id,
        )
    except GitHubError as exc:
        raise PhaseRestartError(f"Phase restart history is unavailable: {exc}") from exc
    current_id = subject.verified_adc.pointer.comment_id
    intents = [record for record in records if record.schema == INTENT_SCHEMA
               and record.payload["adc_comment_id"] == current_id]
    applied = [record for record in records if record.schema == APPLIED_SCHEMA
               and record.payload["adc_comment_id"] == current_id]
    if len(intents) > 1 or len(applied) > 1:
        raise PhaseRestartError("current ADC authorization has conflicting duplicate restart records")
    if applied:
        if not intents:
            raise PhaseRestartError("current ADC Applied record has no Intent")
        record = applied[0]
        forward_phase = _verified_phase_after_restart(github, subject, record, history, root)
        exact_after = tuple(record.payload["labels_after"])
        live_phase = parse_phase_labels(subject.labels)
        exact_forward_labels = _labels_for_phase(exact_after, forward_phase)
        execution_labels = _labels_for_phase(exact_after, Phase.EXECUTION)
        if subject.labels == exact_after:
            pass
        elif subject.labels == exact_forward_labels and live_phase is forward_phase:
            pass
        elif (forward_phase is Phase.READY and live_phase is Phase.EXECUTION
              and subject.labels == execution_labels):
            _verify_ready_before_execution(github, root, subject, record)
        else:
            raise PhaseRestartError(
                "Applied restart conflicts with the live complete label set; "
                "no verified same-generation Phase chain explains the current phase"
            )
        return {"status": "NOOP", "issue": issue_number,
                "intent_comment_id": intents[0].comment_id, "applied_comment_id": record.comment_id,
                "phase_generation_sha256": record.body_sha256, "label_write_count": 0}

    if intents:
        intent = intents[0]
        if intent.actor_id != subject.executor_user_id:
            raise PhaseRestartError("incomplete Intent must be recovered by the same authenticated human User")
        _issue, live_labels = _refresh_labels(github, subject)
        if live_labels == tuple(intent.payload["labels_before"]):
            raise PhaseRestartError("Intent is pending with the before-labels unchanged; label write will not be retried")
        if live_labels != tuple(intent.payload["labels_after"]):
            raise PhaseRestartError("Intent is pending but live labels match neither exact before nor after state")
        current = _live_subject(github, root, issue_number, require_execution_phase=False)
        if (current.verified_adc.pointer != subject.verified_adc.pointer
                or current.binding_sha256 != subject.binding_sha256
                or current.labels != live_labels):
            raise PhaseRestartError("subject changed before read-only Intent recovery")
        applied_record = _post_once(github, issue_number, APPLIED_SCHEMA, _applied_payload(intent))
        return {"status": "RECOVERED", "issue": issue_number,
                "intent_comment_id": intent.comment_id, "applied_comment_id": applied_record.comment_id,
                "phase_generation_sha256": applied_record.body_sha256, "label_write_count": 0}

    if parse_phase_labels(subject.labels) is not Phase.EXECUTION:
        raise PhaseRestartError("restart applies only when the current label is phase:execution")
    if issue_number == 63:
        raise PhaseRestartError("Issue #63 must use its existing specialized phase-rebaseline route")
    intent_payload = _intent_payload(subject, history)
    _validate_record_payload(intent_payload, INTENT_SCHEMA)
    intent = _post_once(github, issue_number, INTENT_SCHEMA, intent_payload)

    # Re-read every mutable subject after the durable Intent and immediately
    # before the one permitted label update.
    latest = _live_subject(github, root, issue_number, require_execution_phase=True)
    latest_history = _validated_current_journal(
        github, latest, allow_pending_adc_comment_id=current_id,
    )
    exact_intents = [record for record in latest_history.restarts
                     if record.schema == INTENT_SCHEMA and record.payload["adc_comment_id"] == current_id]
    if (len(exact_intents) != 1 or exact_intents[0].body != intent.body
            or latest.verified_adc.pointer != subject.verified_adc.pointer
            or latest.binding_sha256 != subject.binding_sha256
            or latest.issue_id != subject.issue_id or latest.labels != tuple(intent_payload["labels_before"])):
        raise PhaseRestartError("live subject or unique Intent changed before the label write")
    _latest_issue, immediate_labels = _refresh_labels(github, latest)
    if immediate_labels != tuple(intent_payload["labels_before"]):
        raise PhaseRestartError("complete Issue labels changed immediately before the one label update")

    write_error: GitHubError | None = None
    try:
        github.replace_issue_labels(issue_number, list(intent_payload["labels_after"]))
    except GitHubError as exc:
        write_error = exc
    try:
        _updated_issue, after_labels = _refresh_labels(github, latest)
    except PhaseRestartError as exc:
        if write_error is not None:
            raise PhaseRestartError(f"label PUT failed and read-only recovery is unavailable: {exc}") from write_error
        raise
    if after_labels != tuple(intent_payload["labels_after"]):
        reason = "label PUT outcome is ambiguous" if write_error is not None else "label PUT readback differs"
        raise PhaseRestartError(f"{reason}; the label write was not repeated")

    current = _live_subject(github, root, issue_number, require_execution_phase=False)
    if (current.verified_adc.pointer != subject.verified_adc.pointer
            or current.binding_sha256 != subject.binding_sha256 or current.labels != after_labels):
        raise PhaseRestartError("ADC, Binding, or complete label state changed after the one label write")
    applied_record = _post_once(github, issue_number, APPLIED_SCHEMA, _applied_payload(intent))
    return {"status": "APPLIED", "issue": issue_number,
            "intent_comment_id": intent.comment_id, "applied_comment_id": applied_record.comment_id,
            "phase_generation_sha256": applied_record.body_sha256, "label_write_count": 1}
