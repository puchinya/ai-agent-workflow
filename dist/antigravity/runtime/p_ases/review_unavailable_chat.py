"""Forward chat-approved provenance exception records for Issue #46.

The older Owner-comment exception schemas remain readable elsewhere. This
module stores new chat decisions and exception receipts without reinterpreting
those older records.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .chat_decisions import ChatDecisionError, OperatorReportedChatDecision, read_chat_decision
from .github import GitHub, GitHubError
from .path_safety import path_has_symlink

REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
ISSUE_NUMBER = 46
ISSUE_ID = 5846549384
PR_NUMBER = 67
OWNER_USER_ID = 3744776
PLAN_SCHEMA = "PASES_REVIEW_UNAVAILABLE_EXCEPTION_PLAN_V2"
RECORD_SCHEMA = "PASES_REVIEW_UNAVAILABLE_EXCEPTION_V2"
CHAT_OPERATION = "REVIEW_UNAVAILABLE_EXCEPTION"
REASON = "HOST_NATIVE_CAPTURE_UNAVAILABLE"
RISK = "INDEPENDENT_REVIEW_PROVENANCE_UNAVAILABLE"
DISCLOSURE = "An independent review was performed; host provenance could not be verified."
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

PLAN_SNAPSHOT_FIELDS = {
    "adc_comment_id", "adc_sha256", "base_ref", "base_sha40", "branch_ref",
    "capability_observation_sha256s", "execution_binding_sha256", "head_sha40",
    "host_surface", "independent_review_sha256", "review_occurrence_sha256", "issue_id", "issue_number",
    "owner_user_id", "pr_binding_sha256", "pr_number", "profile_sha256", "reason",
    "repository", "repository_id", "risk", "verification_plan_sha256",
}


class ChatExceptionError(ValueError):
    """Malformed or mismatched chat-bound provenance exception evidence."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ChatExceptionError("chat exception data is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _positive_int(value: Any, label: str) -> None:
    if type(value) is not int or value < 1:
        raise ChatExceptionError(f"{label} must be a positive integer")


def _validate_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PLAN_SNAPSHOT_FIELDS:
        raise ChatExceptionError("chat exception snapshot has unknown or missing fields")
    if (value.get("repository") != REPOSITORY or value.get("repository_id") != REPOSITORY_ID
            or value.get("owner_user_id") != OWNER_USER_ID or value.get("issue_number") != ISSUE_NUMBER
            or value.get("issue_id") != ISSUE_ID or value.get("pr_number") != PR_NUMBER
            or value.get("reason") != REASON or value.get("risk") != RISK
            or value.get("base_ref") != "main"):
        raise ChatExceptionError("chat exception snapshot is outside the approved Issue #46 / PR #67 scope")
    for field in ("adc_comment_id",):
        _positive_int(value.get(field), field)
    for field in ("adc_sha256", "execution_binding_sha256",
                  "independent_review_sha256", "pr_binding_sha256", "profile_sha256",
                  "review_occurrence_sha256", "verification_plan_sha256"):
        candidate = value.get(field)
        if not isinstance(candidate, str) or not SHA256.fullmatch(candidate):
            raise ChatExceptionError(f"chat exception {field} is invalid")
    observations = value.get("capability_observation_sha256s")
    if (not isinstance(observations, list) or not observations
            or any(not isinstance(item, str) or not SHA256.fullmatch(item) for item in observations)
            or observations != sorted(set(observations))):
        raise ChatExceptionError("chat exception capability observation digests are invalid")
    for field in ("base_sha40", "head_sha40"):
        if not isinstance(value.get(field), str) or not SHA40.fullmatch(value[field]):
            raise ChatExceptionError(f"chat exception {field} is invalid")
    if (not isinstance(value.get("branch_ref"), str) or not value["branch_ref"].strip()
            or value.get("host_surface") not in {"codex_cloud", "codex_local_cli", "codex_desktop", "claude_code"}):
        raise ChatExceptionError("chat exception branch or host surface is invalid")
    return value


def _timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ChatExceptionError("chat exception timestamp must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ChatExceptionError("chat exception timestamp is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ChatExceptionError("chat exception timestamp is not UTC")


@dataclass(frozen=True)
class ChatReviewUnavailablePlan:
    value: dict[str, Any]

    def validate(self) -> "ChatReviewUnavailablePlan":
        if (not isinstance(self.value, dict)
                or set(self.value) != {"disclosure", "generated_at", "plan_sha256", "schema", "snapshot"}
                or self.value.get("schema") != PLAN_SCHEMA or self.value.get("disclosure") != DISCLOSURE):
            raise ChatExceptionError("chat exception plan has unknown or missing fields")
        _timestamp(self.value.get("generated_at"))
        _validate_snapshot(self.value.get("snapshot"))
        digest = self.value.get("plan_sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ChatExceptionError("chat exception plan digest is invalid")
        if _digest({key: item for key, item in self.value.items() if key != "plan_sha256"}) != digest:
            raise ChatExceptionError("chat exception plan digest does not match its canonical content")
        return self

    @property
    def sha256(self) -> str:
        return self.validate().value["plan_sha256"]

    @property
    def snapshot(self) -> dict[str, Any]:
        return self.validate().value["snapshot"]

    @property
    def approval_scope(self) -> dict[str, Any]:
        return {"head_sha40": self.snapshot["head_sha40"], "issue_number": ISSUE_NUMBER,
                "operation": CHAT_OPERATION, "plan_sha256": self.sha256,
                "pr_number": PR_NUMBER, "repository": REPOSITORY,
                "review_sha256": self.snapshot["independent_review_sha256"],
                "review_occurrence_sha256": self.snapshot["review_occurrence_sha256"]}

    @property
    def approval_scope_sha256(self) -> str:
        return _digest(self.approval_scope)

    @classmethod
    def create(cls, snapshot: dict[str, Any], *, generated_at: str | None = None) -> "ChatReviewUnavailablePlan":
        stamp = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        value = {"disclosure": DISCLOSURE, "generated_at": stamp, "schema": PLAN_SCHEMA,
                 "snapshot": _validate_snapshot(snapshot)}
        value["plan_sha256"] = _digest(value)
        return cls(value).validate()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ChatReviewUnavailablePlan":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChatExceptionError("chat exception plan is not UTF-8 JSON") from exc
        if not isinstance(value, dict) or _canonical(value) + b"\n" != raw:
            raise ChatExceptionError("chat exception plan is not canonical JSON with one trailing newline")
        return cls(value).validate()

    def to_bytes(self) -> bytes:
        return _canonical(self.validate().value) + b"\n"


def read_plan(path: Path) -> ChatReviewUnavailablePlan:
    location = Path(path)
    if path_has_symlink(location) or not location.is_file():
        raise ChatExceptionError("chat exception plan must be a regular non-symlink file")
    return ChatReviewUnavailablePlan.from_bytes(location.read_bytes())


def write_plan(path: Path, plan: ChatReviewUnavailablePlan) -> None:
    target = Path(path)
    if path_has_symlink(target) or target.exists():
        raise ChatExceptionError("chat exception plan output exists or traverses a symbolic link")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(plan.to_bytes())
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True)
class ChatReviewUnavailableException:
    value: dict[str, Any]

    def validate(self) -> "ChatReviewUnavailableException":
        expected = {"chat_decision_comment_id", "chat_decision_sha256", "exception_comment_id",
                    "exception_comment_sha256", "plan", "plan_sha256", "publisher_user_id", "schema"}
        if (not isinstance(self.value, dict) or set(self.value) != expected
                or self.value.get("schema") != RECORD_SCHEMA or not isinstance(self.value.get("plan"), dict)):
            raise ChatExceptionError("chat exception receipt has unknown or missing fields")
        plan = ChatReviewUnavailablePlan(self.value["plan"]).validate()
        if self.value.get("plan_sha256") != plan.sha256:
            raise ChatExceptionError("chat exception receipt plan digest is mismatched")
        for field in ("chat_decision_comment_id", "exception_comment_id", "publisher_user_id"):
            _positive_int(self.value.get(field), field)
        for field in ("chat_decision_sha256", "exception_comment_sha256"):
            candidate = self.value.get(field)
            if not isinstance(candidate, str) or not SHA256.fullmatch(candidate):
                raise ChatExceptionError(f"chat exception {field} is invalid")
        return self

    @property
    def snapshot(self) -> dict[str, Any]:
        return ChatReviewUnavailablePlan(self.value["plan"]).snapshot

    @property
    def plan_sha256(self) -> str:
        return self.validate().value["plan_sha256"]

    @property
    def sha256(self) -> str:
        return _digest(self.validate().value)

    def to_bytes(self) -> bytes:
        return _canonical({**self.validate().value, "exception_sha256": self.sha256}) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ChatReviewUnavailableException":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChatExceptionError("chat exception receipt is not UTF-8 JSON") from exc
        if not isinstance(value, dict) or _canonical(value) + b"\n" != raw:
            raise ChatExceptionError("chat exception receipt is not canonical JSON")
        expected = {"chat_decision_comment_id", "chat_decision_sha256", "exception_comment_id",
                    "exception_comment_sha256", "exception_sha256", "plan", "plan_sha256",
                    "publisher_user_id", "schema"}
        if set(value) != expected or value.get("schema") != RECORD_SCHEMA:
            raise ChatExceptionError("chat exception receipt has unknown or missing fields")
        digest = value.pop("exception_sha256")
        record = cls(value).validate()
        if digest != record.sha256:
            raise ChatExceptionError("chat exception receipt digest is invalid")
        return record


def exception_path(root: Path, record: ChatReviewUnavailableException) -> Path:
    return (Path(root).absolute() / ".p_ases" / "review-unavailable-exceptions" / str(ISSUE_NUMBER)
            / record.plan_sha256 / f"{record.sha256}.json")


def read_exception(path: Path) -> ChatReviewUnavailableException:
    location = Path(path)
    if path_has_symlink(location) or not location.is_file():
        raise ChatExceptionError("chat exception receipt must be a regular non-symlink file")
    return ChatReviewUnavailableException.from_bytes(location.read_bytes())


def _read_chat_grant(github: GitHub, plan: ChatReviewUnavailablePlan,
                     comment_id: int) -> OperatorReportedChatDecision:
    try:
        decision = read_chat_decision(
            github, comment_id, operation=CHAT_OPERATION,
            subject_sha256=plan.sha256, scope_sha256=plan.approval_scope_sha256,
        )
    except ChatDecisionError as exc:
        raise ChatExceptionError(f"active-chat exception decision is invalid: {exc}") from exc
    if decision.payload["scope"] != plan.approval_scope:
        raise ChatExceptionError("active-chat exception decision does not bind the displayed exact plan")
    return decision


def _exception_body(plan: ChatReviewUnavailablePlan, decision: OperatorReportedChatDecision,
                    publisher_user_id: int) -> str:
    payload = {"chat_decision_comment_id": decision.comment_id,
               "chat_decision_sha256": decision.body_sha256,
               "plan": plan.value, "plan_sha256": plan.sha256,
               "publisher_user_id": publisher_user_id, "schema": RECORD_SCHEMA}
    return f"<!-- {RECORD_SCHEMA}\n{_canonical(payload).decode('utf-8')}\n-->"


def _verify_exception_comment(github: GitHub, comment_id: int, body: str,
                              publisher_user_id: int) -> dict[str, Any]:
    expected_issue = f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}"
    expected_api = f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}"
    expected_html = f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}"
    try:
        first = github.issue_comment(ISSUE_NUMBER, comment_id)
        listed = [row for row in github.issue_comments(ISSUE_NUMBER)
                  if row.get("id") == comment_id or row.get("body") == body]
        second = github.issue_comment(ISSUE_NUMBER, comment_id)
    except GitHubError as exc:
        raise ChatExceptionError("exception receipt direct/list/direct readback failed") from exc
    if len(listed) != 1:
        raise ChatExceptionError("exception receipt is missing or duplicated")
    for row in (first, listed[0], second):
        user = row.get("user") if isinstance(row, dict) else None
        if (row.get("id") != comment_id or row.get("body") != body
                or row.get("issue_url") != expected_issue or row.get("url") != expected_api
                or row.get("html_url") != expected_html or row.get("created_at") != row.get("updated_at")
                or not isinstance(user, dict) or user.get("type") != "User"
                or user.get("id") != publisher_user_id):
            raise ChatExceptionError("exception receipt location, publisher, or immutable body is invalid")
    if first != listed[0] or first != second:
        raise ChatExceptionError("exception receipt changed during direct/list/direct readback")
    return second


def apply_exception(github: GitHub, plan: ChatReviewUnavailablePlan, decision_comment_id: int,
                    *, local_root: Path) -> tuple[ChatReviewUnavailableException, Path, bool]:
    plan.validate()
    decision = _read_chat_grant(github, plan, decision_comment_id)
    issue = github.issue(ISSUE_NUMBER)
    repo = github.repository_metadata()
    if issue.get("id") != ISSUE_ID or issue.get("state") != "open" or repo.get("id") != REPOSITORY_ID:
        raise ChatExceptionError("Issue or repository identity changed before chat exception apply")
    principal = github.authenticated_user()
    if (principal.get("type") != "User" or type(principal.get("id")) is not int
            or not isinstance(principal.get("login"), str) or not principal["login"]):
        raise ChatExceptionError("technical exception recorder is not an authenticated GitHub User")
    publisher_id = principal["id"]
    body = _exception_body(plan, decision, publisher_id)
    try:
        comments = github.issue_comments(ISSUE_NUMBER)
    except GitHubError as exc:
        raise ChatExceptionError("exception receipt history could not be read before append") from exc
    marker = f"<!-- {RECORD_SCHEMA}"
    head_records: list[dict[str, Any]] = []
    for row in comments:
        current_body = row.get("body") if isinstance(row, dict) else None
        if not isinstance(current_body, str) or marker not in current_body:
            continue
        existing = _record_from_body(row)
        if existing.snapshot["head_sha40"] == plan.snapshot["head_sha40"]:
            head_records.append(row)
    if len(head_records) > 1:
        raise ChatExceptionError("multiple chat exception receipts exist for this exact PR HEAD")
    if head_records:
        row = head_records[0]
        if row.get("body") != body:
            raise ChatExceptionError("a conflicting chat exception receipt already exists for this PR HEAD")
        cid = row.get("id")
        _verify_exception_comment(github, cid, body, publisher_id)
        record = _make_record(plan, decision, publisher_id, cid, body)
        path = exception_path(local_root, record)
        _write_local(path, record)
        return record, path, True
    try:
        created = github.create_issue_comment(ISSUE_NUMBER, body)
        cid = created.get("id") if isinstance(created, dict) else None
    except GitHubError as exc:
        after = [row for row in github.issue_comments(ISSUE_NUMBER) if row.get("body") == body]
        if len(after) != 1:
            raise ChatExceptionError("exception receipt append is ambiguous; refusing a blind retry") from exc
        cid = after[0].get("id")
    _positive_int(cid, "exception receipt comment ID")
    _verify_exception_comment(github, cid, body, publisher_id)
    record = _make_record(plan, decision, publisher_id, cid, body)
    path = exception_path(local_root, record)
    _write_local(path, record)
    return record, path, False


def _record_from_body(row: dict[str, Any]) -> ChatReviewUnavailableException:
    body = row.get("body")
    prefix = f"<!-- {RECORD_SCHEMA}\n"
    if not isinstance(body, str) or not body.startswith(prefix) or not body.endswith("\n-->"):
        raise ChatExceptionError("chat exception history marker framing is invalid")
    encoded = body[len(prefix):-len("\n-->")]
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise ChatExceptionError("chat exception history marker JSON is invalid") from exc
    expected = {"chat_decision_comment_id", "chat_decision_sha256", "plan", "plan_sha256",
                "publisher_user_id", "schema"}
    if (not isinstance(value, dict) or set(value) != expected or value.get("schema") != RECORD_SCHEMA
            or _canonical(value).decode("utf-8") != encoded):
        raise ChatExceptionError("chat exception history marker is noncanonical")
    cid = row.get("id")
    _positive_int(cid, "chat exception history comment ID")
    return ChatReviewUnavailableException({
        "chat_decision_comment_id": value["chat_decision_comment_id"],
        "chat_decision_sha256": value["chat_decision_sha256"],
        "exception_comment_id": cid,
        "exception_comment_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "plan": value["plan"], "plan_sha256": value["plan_sha256"],
        "publisher_user_id": value["publisher_user_id"], "schema": value["schema"],
    }).validate()


def _make_record(plan: ChatReviewUnavailablePlan, decision: OperatorReportedChatDecision,
                 publisher_id: int, comment_id: int, body: str) -> ChatReviewUnavailableException:
    return ChatReviewUnavailableException({
        "chat_decision_comment_id": decision.comment_id,
        "chat_decision_sha256": decision.body_sha256,
        "exception_comment_id": comment_id,
        "exception_comment_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "plan": plan.value, "plan_sha256": plan.sha256,
        "publisher_user_id": publisher_id, "schema": RECORD_SCHEMA,
    }).validate()


def _write_local(path: Path, record: ChatReviewUnavailableException) -> None:
    target = Path(path)
    if path_has_symlink(target):
        raise ChatExceptionError("chat exception path traverses a symbolic link")
    target.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(target):
        raise ChatExceptionError("chat exception path traverses a symbolic link")
    raw = record.to_bytes()
    if target.exists():
        if read_exception(target) != record:
            raise ChatExceptionError("chat exception local receipt conflicts with existing bytes")
        return
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if read_exception(target) != record:
                raise ChatExceptionError("chat exception local receipt raced with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ChatExceptionError("could not persist immutable chat exception receipt") from exc
    if read_exception(target) != record:
        raise ChatExceptionError("chat exception local readback differs from the written receipt")


def verify_exception(github: GitHub, record: ChatReviewUnavailableException) -> dict[str, Any]:
    record.validate()
    decision = _read_chat_grant(github, ChatReviewUnavailablePlan(record.value["plan"]),
                                record.value["chat_decision_comment_id"])
    if decision.body_sha256 != record.value["chat_decision_sha256"]:
        raise ChatExceptionError("chat exception decision record changed")
    body = _exception_body(ChatReviewUnavailablePlan(record.value["plan"]), decision,
                           record.value["publisher_user_id"])
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != record.value["exception_comment_sha256"]:
        raise ChatExceptionError("chat exception technical receipt digest changed")
    return _verify_exception_comment(github, record.value["exception_comment_id"], body,
                                     record.value["publisher_user_id"])
