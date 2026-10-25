"""Owner-scoped, exact-subject records for unavailable native review capture.

These records disclose that no Independent Review was performed. They never
rewrite the meaning of Independent Review V1/V2 or authorize downstream actions.
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

from .github import GitHub, GitHubError
from .path_safety import path_has_symlink

REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
OWNER_USER_ID = 3744776
ISSUE_NUMBER = 46
ISSUE_ID = 5846549384
PR_NUMBER = 67
PLAN_SCHEMA = "PASES_REVIEW_UNAVAILABLE_EXCEPTION_PLAN_V1"
RECORD_SCHEMA = "PASES_REVIEW_UNAVAILABLE_EXCEPTION_V1"
APPROVAL_SCHEMA = "PASES_REVIEW_UNAVAILABLE_APPROVAL_V1"
REASON = "HOST_NATIVE_CAPTURE_UNAVAILABLE"
RISK = "INDEPENDENT_REVIEW_NOT_PERFORMED"
DISCLOSURE = "No independent review was performed; code defects may go undetected."
HOST_SURFACES = {"codex_cloud", "codex_local_cli", "codex_desktop", "claude_code"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_FIELDS = {
    "adc_comment_id", "adc_sha256", "base_ref", "base_sha40", "branch_ref",
    "capability_observation_sha256s", "execution_binding_sha256", "head_sha40",
    "host_surface", "issue_id", "issue_number", "owner_user_id", "pr_binding_sha256",
    "pr_number", "profile_sha256", "reason", "repository", "repository_id", "risk",
    "verification_plan_sha256",
}


class ReviewUnavailableError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _positive_int(value: Any, label: str) -> None:
    if type(value) is not int or value < 1:
        raise ReviewUnavailableError(f"{label} must be a positive integer")


def _time(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReviewUnavailableError(f"{label} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReviewUnavailableError(f"{label} is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReviewUnavailableError(f"{label} is not UTC")


def _validate_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != SNAPSHOT_FIELDS:
        raise ReviewUnavailableError("exception plan snapshot has unknown or missing fields")
    if (value.get("repository") != REPOSITORY or value.get("repository_id") != REPOSITORY_ID
            or value.get("owner_user_id") != OWNER_USER_ID
            or value.get("issue_number") != ISSUE_NUMBER or value.get("issue_id") != ISSUE_ID
            or value.get("pr_number") != PR_NUMBER or value.get("reason") != REASON
            or value.get("risk") != RISK or value.get("host_surface") not in HOST_SURFACES
            or value.get("base_ref") != "main"):
        raise ReviewUnavailableError("exception plan is outside the approved Issue #46 / PR #67 scope")
    for key in ("adc_comment_id",):
        _positive_int(value.get(key), key)
    for key in ("adc_sha256", "execution_binding_sha256", "pr_binding_sha256", "profile_sha256",
                "verification_plan_sha256"):
        if not isinstance(value.get(key), str) or not SHA256.fullmatch(value[key]):
            raise ReviewUnavailableError(f"exception plan {key} is invalid")
    for key in ("base_sha40", "head_sha40"):
        if not isinstance(value.get(key), str) or not SHA40.fullmatch(value[key]):
            raise ReviewUnavailableError(f"exception plan {key} is invalid")
    if not isinstance(value.get("branch_ref"), str) or not value["branch_ref"].strip():
        raise ReviewUnavailableError("exception plan branch ref is invalid")
    digests = value.get("capability_observation_sha256s")
    if (not isinstance(digests, list) or not digests
            or any(not isinstance(item, str) or not SHA256.fullmatch(item) for item in digests)
            or digests != sorted(set(digests))):
        raise ReviewUnavailableError("exception plan capability observation digests are invalid")
    return value


@dataclass(frozen=True)
class ReviewUnavailablePlan:
    value: dict[str, Any]

    def validate(self) -> "ReviewUnavailablePlan":
        if (not isinstance(self.value, dict)
                or set(self.value) != {"disclosure", "generated_at", "plan_sha256", "schema", "snapshot"}):
            raise ReviewUnavailableError("exception plan has unknown or missing fields")
        if self.value.get("schema") != PLAN_SCHEMA or self.value.get("disclosure") != DISCLOSURE:
            raise ReviewUnavailableError("exception plan schema is invalid")
        _time(self.value.get("generated_at"), "exception plan timestamp")
        _validate_snapshot(self.value.get("snapshot"))
        digest = self.value.get("plan_sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ReviewUnavailableError("exception plan digest is invalid")
        if _digest({key: item for key, item in self.value.items() if key != "plan_sha256"}) != digest:
            raise ReviewUnavailableError("exception plan digest does not match its canonical content")
        return self

    @property
    def sha256(self) -> str:
        return self.validate().value["plan_sha256"]

    @property
    def snapshot(self) -> dict[str, Any]:
        return self.validate().value["snapshot"]

    @classmethod
    def create(cls, snapshot: dict[str, Any], *, generated_at: str | None = None) -> "ReviewUnavailablePlan":
        stamp = generated_at or datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        value = {"disclosure": DISCLOSURE, "generated_at": stamp,
                 "schema": PLAN_SCHEMA, "snapshot": _validate_snapshot(snapshot)}
        value["plan_sha256"] = _digest(value)
        return cls(value).validate()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ReviewUnavailablePlan":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewUnavailableError("exception plan is not UTF-8 JSON") from exc
        if not isinstance(value, dict) or _canonical(value) + b"\n" != raw:
            raise ReviewUnavailableError("exception plan is not canonical JSON with one trailing newline")
        return cls(value).validate()

    def to_bytes(self) -> bytes:
        return _canonical(self.validate().value) + b"\n"


def read_plan(path: Path) -> ReviewUnavailablePlan:
    location = Path(path)
    if path_has_symlink(location) or not location.is_file():
        raise ReviewUnavailableError("exception plan must be a regular non-symlink file")
    try:
        return ReviewUnavailablePlan.from_bytes(location.read_bytes())
    except OSError as exc:
        raise ReviewUnavailableError("exception plan is unreadable") from exc


def write_plan(path: Path, plan: ReviewUnavailablePlan) -> None:
    raw = plan.to_bytes()
    destination = Path(path)
    if path_has_symlink(destination) or destination.exists():
        raise ReviewUnavailableError("exception plan output exists or traverses a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(destination):
        raise ReviewUnavailableError("exception plan output traverses a symbolic link")
    descriptor: int | None = None
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ReviewUnavailableError("exception plan output appeared during creation") from exc
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ReviewUnavailableError("could not persist canonical exception plan") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def approval_comment(plan: ReviewUnavailablePlan) -> str:
    plan.validate()
    return _approval_comment_for_digest(plan.sha256)


def _approval_comment_for_digest(plan_sha256: str) -> str:
    if not isinstance(plan_sha256, str) or not SHA256.fullmatch(plan_sha256):
        raise ReviewUnavailableError("Owner approval plan digest is invalid")
    payload = {"approved": True, "issue_number": ISSUE_NUMBER, "plan_sha256": plan_sha256,
               "pr_number": PR_NUMBER, "repository": REPOSITORY, "schema": APPROVAL_SCHEMA}
    return f"<!-- {APPROVAL_SCHEMA}\n{_canonical(payload).decode('utf-8')}\n-->"


def _comment_identity(row: Any, *, issue_number: int, body: str, author_id: int,
                      label: str) -> tuple[Any, ...]:
    if not isinstance(row, dict):
        raise ReviewUnavailableError(f"{label} comment is malformed")
    user = row.get("user")
    comment_id = row.get("id")
    expected_issue = f"https://api.github.com/repos/{REPOSITORY}/issues/{issue_number}"
    if (type(comment_id) is not int or comment_id < 1 or row.get("body") != body
            or not isinstance(user, dict) or user.get("id") != author_id or user.get("type") != "User"
            or not isinstance(user.get("login"), str) or not user["login"]
            or row.get("issue_url") != expected_issue
            or row.get("url") != f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}"
            or row.get("html_url") != f"https://github.com/{REPOSITORY}/issues/{issue_number}#issuecomment-{comment_id}"):
        raise ReviewUnavailableError(f"{label} comment identity, author, URL, or body does not match")
    created, updated = row.get("created_at"), row.get("updated_at")
    _time(created, f"{label} creation timestamp")
    _time(updated, f"{label} update timestamp")
    if created != updated:
        raise ReviewUnavailableError(f"{label} comment was edited")
    return (comment_id, author_id, user["login"].casefold(), row["body"], row["issue_url"],
            row["url"], row["html_url"], created, updated)


def _verify_repository_scope(github: GitHub) -> None:
    if not isinstance(getattr(github, "repo", None), str) or github.repo.casefold() != REPOSITORY.casefold():
        raise ReviewUnavailableError("GitHub client repository does not match the approved exception scope")
    try:
        metadata = github.repository_metadata()
    except GitHubError as exc:
        raise ReviewUnavailableError("GitHub repository identity readback failed") from exc
    if not isinstance(metadata, dict) or metadata.get("id") != REPOSITORY_ID:
        raise ReviewUnavailableError("GitHub repository stable ID does not match the approved exception scope")


def _read_comment_direct_list_direct(github: GitHub, *, issue_number: int, comment_id: int,
                                     body: str, author_id: int, label: str) -> dict[str, Any]:
    try:
        first = github.issue_comment(issue_number, comment_id)
        listed = github.issue_comments(issue_number)
        matching_id = [row for row in listed if row.get("id") == comment_id]
        matching_body = [row for row in listed if row.get("body") == body]
        second = github.issue_comment(issue_number, comment_id)
    except GitHubError as exc:
        raise ReviewUnavailableError(f"{label} direct/list/direct GitHub readback failed") from exc
    if len(matching_id) != 1 or len(matching_body) != 1:
        raise ReviewUnavailableError(f"{label} comment is missing, duplicated, or conflicting")
    signatures = [_comment_identity(row, issue_number=issue_number, body=body,
                                    author_id=author_id, label=label)
                  for row in (first, matching_id[0], second)]
    if signatures[0] != signatures[1] or signatures[0] != signatures[2]:
        raise ReviewUnavailableError(f"{label} comment changed during direct/list/direct readback")
    return second


def verify_owner_approval(github: GitHub, plan: ReviewUnavailablePlan, comment_id: int) -> tuple[str, dict[str, Any]]:
    plan.validate()
    _verify_repository_scope(github)
    _positive_int(comment_id, "Owner approval Comment ID")
    body = approval_comment(plan)
    comment = _read_comment_direct_list_direct(
        github, issue_number=ISSUE_NUMBER, comment_id=comment_id, body=body,
        author_id=OWNER_USER_ID, label="Owner exception approval",
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest(), comment


def verify_record_approval(github: GitHub, record: ReviewUnavailableException) -> dict[str, Any]:
    record.validate()
    _verify_repository_scope(github)
    body = _approval_comment_for_digest(record.plan_sha256)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if digest != record.value["owner_approval_sha256"]:
        raise ReviewUnavailableError("Owner approval digest differs from the immutable exception record")
    return _read_comment_direct_list_direct(
        github, issue_number=ISSUE_NUMBER, comment_id=record.value["owner_approval_comment_id"],
        body=body, author_id=OWNER_USER_ID, label="Owner exception approval",
    )


def _record_body(plan: ReviewUnavailablePlan, owner_comment_id: int,
                 owner_comment_sha256: str, publisher_user_id: int) -> str:
    plan.validate()
    payload = {"owner_approval_comment_id": owner_comment_id,
               "owner_approval_sha256": owner_comment_sha256,
               "plan_sha256": plan.sha256,
               "plan": plan.value,
               "publisher_user_id": publisher_user_id,
               "schema": RECORD_SCHEMA}
    return f"<!-- {RECORD_SCHEMA}\n{_canonical(payload).decode('utf-8')}\n-->"


@dataclass(frozen=True)
class ReviewUnavailableException:
    value: dict[str, Any]

    def validate(self) -> "ReviewUnavailableException":
        fields = {"exception_comment_id", "exception_comment_sha256", "owner_approval_comment_id",
                  "owner_approval_sha256", "plan", "plan_sha256", "publisher_user_id", "schema"}
        if not isinstance(self.value, dict) or set(self.value) != fields or self.value.get("schema") != RECORD_SCHEMA:
            raise ReviewUnavailableError("exception record has unknown or missing fields")
        if not isinstance(self.value.get("plan"), dict):
            raise ReviewUnavailableError("exception record's exact plan is missing")
        plan = ReviewUnavailablePlan(self.value["plan"]).validate()
        if self.value.get("plan_sha256") != plan.sha256:
            raise ReviewUnavailableError("exception record plan digest does not match its exact plan")
        for key in ("exception_comment_id", "owner_approval_comment_id", "publisher_user_id"):
            _positive_int(self.value.get(key), key)
        for key in ("exception_comment_sha256", "owner_approval_sha256", "plan_sha256"):
            if not isinstance(self.value.get(key), str) or not SHA256.fullmatch(self.value[key]):
                raise ReviewUnavailableError(f"exception record {key} is invalid")
        return self

    @property
    def sha256(self) -> str:
        return _digest(self.validate().value)

    @property
    def snapshot(self) -> dict[str, Any]:
        return self.validate().value["plan"]["snapshot"]

    @property
    def plan_sha256(self) -> str:
        return self.validate().value["plan_sha256"]

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ReviewUnavailableException":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewUnavailableError("exception record is not UTF-8 JSON") from exc
        expected = {"exception_comment_id", "exception_comment_sha256", "owner_approval_comment_id",
                    "owner_approval_sha256", "plan", "plan_sha256", "publisher_user_id", "schema",
                    "exception_sha256"}
        if (not isinstance(value, dict) or set(value) != expected or value.get("schema") != RECORD_SCHEMA
                or _canonical(value) + b"\n" != raw):
            raise ReviewUnavailableError("exception record is noncanonical or has unknown/missing fields")
        digest = value.pop("exception_sha256")
        record = cls(value).validate()
        if digest != record.sha256:
            raise ReviewUnavailableError("exception record digest does not match its content")
        return record

    def to_bytes(self) -> bytes:
        value = {**self.validate().value, "exception_sha256": self.sha256}
        return _canonical(value) + b"\n"


def exception_record_path(root: Path, record: ReviewUnavailableException) -> Path:
    return (Path(root).absolute() / ".p_ases" / "review-unavailable-exceptions" / str(ISSUE_NUMBER)
            / record.plan_sha256 / f"{record.sha256}.json")


def read_exception(path: Path) -> ReviewUnavailableException:
    location = Path(path)
    if path_has_symlink(location) or not location.is_file():
        raise ReviewUnavailableError("exception record must be a regular non-symlink file")
    try:
        return ReviewUnavailableException.from_bytes(location.read_bytes())
    except OSError as exc:
        raise ReviewUnavailableError("exception record is unreadable") from exc


def write_exception(path: Path, record: ReviewUnavailableException) -> None:
    raw = record.to_bytes()
    target = Path(path)
    if path_has_symlink(target):
        raise ReviewUnavailableError("exception record path traverses a symbolic link")
    target.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(target):
        raise ReviewUnavailableError("exception record path traverses a symbolic link")
    if target.exists():
        if read_exception(target) != record:
            raise ReviewUnavailableError("exception record identity exists with different bytes")
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
                raise ReviewUnavailableError("exception record identity raced with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise ReviewUnavailableError("could not persist immutable exception record") from exc
    if read_exception(target) != record:
        raise ReviewUnavailableError("exception record changed after local write")


def read_exception_comment(github: GitHub, record: ReviewUnavailableException) -> dict[str, Any]:
    record.validate()
    verify_record_approval(github, record)
    body = _record_body(
        ReviewUnavailablePlan(record.value["plan"]), record.value["owner_approval_comment_id"],
        record.value["owner_approval_sha256"],
        record.value["publisher_user_id"],
    )
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != record.value["exception_comment_sha256"]:
        raise ReviewUnavailableError("exception receipt body digest differs from its immutable record")
    return _read_comment_direct_list_direct(
        github, issue_number=ISSUE_NUMBER, comment_id=record.value["exception_comment_id"],
        body=body, author_id=record.value["publisher_user_id"], label="exception receipt",
    )


def apply_exception(github: GitHub, plan: ReviewUnavailablePlan, owner_comment_id: int,
                    *, local_root: Path) -> tuple[ReviewUnavailableException, Path, bool]:
    """Publish one exact exception receipt; return ``replayed`` on read-only replay."""
    plan.validate()
    owner_sha, _owner_comment = verify_owner_approval(github, plan, owner_comment_id)
    principal = github.authenticated_user()
    if (not isinstance(principal, dict) or principal.get("type") != "User"
            or not isinstance(principal.get("login"), str) or not principal["login"]):
        raise ReviewUnavailableError("exception receipt publisher is not a stable authenticated GitHub User")
    publisher_id = principal.get("id")
    _positive_int(publisher_id, "authenticated publisher User ID")
    expected_body = _record_body(plan, owner_comment_id, owner_sha, publisher_id)
    comments = github.issue_comments(ISSUE_NUMBER)
    marker_prefix = f"<!-- {RECORD_SCHEMA}\n"
    for item in comments:
        body = item.get("body")
        if not isinstance(body, str) or not body.startswith(marker_prefix):
            continue
        try:
            payload = json.loads(body[len(marker_prefix):].split("\n-->", 1)[0])
        except (json.JSONDecodeError, IndexError):
            raise ReviewUnavailableError("exception receipt history contains malformed marker data")
        nested_plan = payload.get("plan") if isinstance(payload, dict) else None
        snapshot = nested_plan.get("snapshot") if isinstance(nested_plan, dict) else None
        if isinstance(snapshot, dict) and snapshot.get("head_sha40") == plan.snapshot["head_sha40"]:
            if body != expected_body:
                raise ReviewUnavailableError("conflicting exception receipt already exists for this PR HEAD")
            matches = [row for row in comments if row.get("body") == expected_body]
            if len(matches) != 1:
                raise ReviewUnavailableError("exception receipt is duplicated")
            comment_id = item.get("id")
            row = _read_comment_direct_list_direct(github, issue_number=ISSUE_NUMBER,
                                                   comment_id=comment_id, body=expected_body,
                                                   author_id=publisher_id, label="exception receipt")
            record = _make_record(plan, owner_comment_id, owner_sha, publisher_id,
                                  row["id"], expected_body)
            path = exception_record_path(local_root, record)
            write_exception(path, record)
            return record, path, True
    try:
        created = github.create_issue_comment(ISSUE_NUMBER, expected_body)
        comment_id = created.get("id") if isinstance(created, dict) else None
    except GitHubError as exc:
        # A lost response is resolved by read-only exact-body lookup. Never POST twice.
        after = github.issue_comments(ISSUE_NUMBER)
        matches = [row for row in after if row.get("body") == expected_body]
        if len(matches) != 1:
            raise ReviewUnavailableError("exception receipt publication outcome is ambiguous; no retry was sent") from exc
        comment_id = matches[0].get("id")
    _positive_int(comment_id, "exception receipt Comment ID")
    row = _read_comment_direct_list_direct(github, issue_number=ISSUE_NUMBER,
                                           comment_id=comment_id, body=expected_body,
                                           author_id=publisher_id, label="exception receipt")
    record = _make_record(plan, owner_comment_id, owner_sha, publisher_id, comment_id, expected_body)
    path = exception_record_path(local_root, record)
    write_exception(path, record)
    return record, path, False


def _make_record(plan: ReviewUnavailablePlan, owner_comment_id: int, owner_sha: str,
                 publisher_id: int, comment_id: int, body: str) -> ReviewUnavailableException:
    return ReviewUnavailableException({
        "exception_comment_id": comment_id,
        "exception_comment_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "owner_approval_comment_id": owner_comment_id,
        "owner_approval_sha256": owner_sha,
        "plan": plan.value,
        "plan_sha256": plan.sha256,
        "publisher_user_id": publisher_id,
        "schema": RECORD_SCHEMA,
    }).validate()
