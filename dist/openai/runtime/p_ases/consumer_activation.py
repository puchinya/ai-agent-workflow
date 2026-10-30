"""Repository-scoped Consumer Activation setup and append-only history."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adc import ADCError, VerifiedADC, publish_adc, verify_adc, verify_adc_generation
from .github import GitHub, GitHubError
from .git import (
    GitError, activation_profile_bytes_at_commit, branch_exists, changed_paths_between,
    commit_and_push_one_path, commit_parent_sha40, create_branch, current_branch, discover_repository,
    fetch_remote_branch_exact, head_sha40, push_branch_exact, remote_branch_exists, remote_branch_sha,
    switch_branch, worktree_clean,
)
from .path_safety import path_has_symlink
from .profile import ProfileError, load_profile
from .ruleset_management import (
    ACTIVATION_BINDING_SCHEMA, RulesetManagementError, build_ruleset_plan, read_verified_managed_policy,
    verify_applied_policy_record, write_plan as write_ruleset_plan,
)


class ConsumerActivationError(ValueError):
    pass


ISSUE_MARKER = "<!-- PASES_CONSUMER_ACTIVATION_ISSUE_V1 -->"
SETUP_MARKER = "<!-- PASES_CONSUMER_ACTIVATION_SETUP_V1\n"
APPROVAL_MARKER = "<!-- PASES_CONSUMER_ACTIVATION_APPROVAL_V1\n"
RECORD_MARKER = "<!-- PASES_CONSUMER_ACTIVATION_V1\n"
SETUP_MARKER_V2 = "<!-- PASES_CONSUMER_ACTIVATION_SETUP_V2\n"
APPROVAL_MARKER_V2 = "<!-- PASES_CONSUMER_ACTIVATION_APPROVAL_V2\n"
RECORD_MARKER_V2 = "<!-- PASES_CONSUMER_ACTIVATION_V2\n"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
ACTIVATION_CHECKPOINT_SCHEMA = "PASES_CONSUMER_ACTIVATION_CHECKPOINT_V1"
ACTIVATION_STAGES = frozenset({
    "DISCOVER_AND_PREFLIGHT", "PREPARE_SETUP_BRANCH", "POLICY_PLAN",
    "AWAIT_OWNER_POLICY_DECISION", "APPLY_AND_READBACK", "SETUP_PR_REVIEW_AND_MERGE",
    "ACTIVATION_RECORD",
})


@dataclass(frozen=True)
class ActivationCheckpoint:
    repository: str
    repository_id: int
    owner_id: int
    activation_issue_number: int
    adc_comment_id: int
    adc_sha256: str
    predecessor_record_id: int | None
    default_branch: str
    default_branch_sha40: str
    review_mode: str
    required_checks: tuple[tuple[str, int], ...]
    stage: str
    status: str
    setup_branch: str | None = None
    setup_commit_sha40: str | None = None
    profile_sha256: str | None = None
    plan_sha256: str | None = None
    policy_status: str | None = None
    ruleset_id: int | None = None
    applied_record_id: int | None = None
    effective_policy_sha256: str | None = None
    setup_pr_number: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "activation_issue_number": self.activation_issue_number,
            "adc_comment_id": self.adc_comment_id,
            "adc_sha256": self.adc_sha256,
            "applied_record_id": self.applied_record_id,
            "default_branch": self.default_branch,
            "default_branch_sha40": self.default_branch_sha40,
            "effective_policy_sha256": self.effective_policy_sha256,
            "owner_id": self.owner_id,
            "plan_sha256": self.plan_sha256,
            "policy_status": self.policy_status,
            "predecessor_record_id": self.predecessor_record_id,
            "profile_sha256": self.profile_sha256,
            "repository": self.repository,
            "repository_id": self.repository_id,
            "required_checks": [{"context": name, "integration_id": app_id}
                                for name, app_id in self.required_checks],
            "review_mode": self.review_mode,
            "ruleset_id": self.ruleset_id,
            "schema": ACTIVATION_CHECKPOINT_SCHEMA,
            "setup_branch": self.setup_branch,
            "setup_commit_sha40": self.setup_commit_sha40,
            "setup_pr_number": self.setup_pr_number,
            "stage": self.stage,
            "status": self.status,
        }

    def validate(self) -> "ActivationCheckpoint":
        if (self.stage not in ACTIVATION_STAGES
                or self.status not in {"RUNNING", "PENDING_APPROVAL", "ADMIN_AUTH_REQUIRED",
                                       "SETUP_PENDING", "BLOCKED", "ACTIVE"}
                or not isinstance(self.repository, str) or not self.repository
                or type(self.repository_id) is not int or self.repository_id < 1
                or type(self.owner_id) is not int or self.owner_id < 1
                or type(self.activation_issue_number) is not int or self.activation_issue_number < 1
                or type(self.adc_comment_id) is not int or self.adc_comment_id < 1
                or not SHA256.fullmatch(self.adc_sha256)
                or (self.predecessor_record_id is not None
                    and (type(self.predecessor_record_id) is not int or self.predecessor_record_id < 1))
                or not isinstance(self.default_branch, str) or not self.default_branch
                or not SHA40.fullmatch(self.default_branch_sha40)
                or self.review_mode != "solo_owner"
                or not isinstance(self.required_checks, tuple) or not self.required_checks
                or any(not isinstance(name, str) or not name or type(app_id) is not int or app_id < 1
                       for name, app_id in self.required_checks)):
            raise ConsumerActivationError("Activation checkpoint is malformed")
        for label, value in (("setup commit", self.setup_commit_sha40),
                             ("profile digest", self.profile_sha256), ("plan digest", self.plan_sha256),
                             ("effective policy digest", self.effective_policy_sha256)):
            if value is not None and not (SHA40 if label == "setup commit" else SHA256).fullmatch(value):
                raise ConsumerActivationError(f"Activation checkpoint {label} is malformed")
        for label, value in (("Ruleset ID", self.ruleset_id), ("applied record ID", self.applied_record_id),
                             ("setup PR number", self.setup_pr_number)):
            if value is not None and (type(value) is not int or value < 1):
                raise ConsumerActivationError(f"Activation checkpoint {label} is malformed")
        if self.setup_branch is not None and not self.setup_branch.startswith("pases/consumer-activation-"):
            raise ConsumerActivationError("Activation checkpoint setup branch is malformed")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()


def activation_checkpoint_path(root: Path, issue_number: int) -> Path:
    return (Path(root).resolve() / ".p_ases" / "state" / str(_positive(issue_number, "Activation Issue number"))
            / "activation-v2" / "checkpoint.json")


def activation_plan_path(root: Path, issue_number: int) -> Path:
    return activation_checkpoint_path(root, issue_number).with_name("ruleset-plan.json")


def write_activation_checkpoint(path: Path, checkpoint: ActivationCheckpoint, *, root: Path) -> str:
    checkpoint.validate()
    destination = Path(path)
    if path_has_symlink(destination, root=Path(root).resolve()):
        raise ConsumerActivationError("Activation checkpoint path traverses a symbolic link")
    payload = checkpoint.as_dict()
    payload["checkpoint_sha256"] = checkpoint.sha256
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.",
                                         delete=False, mode="wb") as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ConsumerActivationError("could not atomically persist Activation checkpoint") from exc
    return checkpoint.sha256


def read_activation_checkpoint(path: Path) -> ActivationCheckpoint:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ConsumerActivationError("Activation checkpoint is unavailable") from exc
    value = _json_object(raw, "Activation checkpoint")
    expected = {
        "activation_issue_number", "adc_comment_id", "adc_sha256", "applied_record_id", "checkpoint_sha256",
        "default_branch", "default_branch_sha40", "effective_policy_sha256", "owner_id", "plan_sha256",
        "policy_status", "predecessor_record_id", "profile_sha256", "repository", "repository_id",
        "required_checks", "review_mode", "ruleset_id", "schema", "setup_branch", "setup_commit_sha40",
        "setup_pr_number", "stage", "status",
    }
    if set(value) != expected or value.get("schema") != ACTIVATION_CHECKPOINT_SCHEMA:
        raise ConsumerActivationError("Activation checkpoint has an unknown schema")
    supplied = value.pop("checkpoint_sha256")
    if supplied != hashlib.sha256(_canonical(value)).hexdigest():
        raise ConsumerActivationError("Activation checkpoint digest does not match its contents")
    checks = value.get("required_checks")
    if not isinstance(checks, list) or any(not isinstance(row, dict) or set(row) != {"context", "integration_id"}
                                            for row in checks):
        raise ConsumerActivationError("Activation checkpoint Required Checks are malformed")
    checkpoint = ActivationCheckpoint(
        repository=value["repository"], repository_id=value["repository_id"], owner_id=value["owner_id"],
        activation_issue_number=value["activation_issue_number"], adc_comment_id=value["adc_comment_id"],
        adc_sha256=value["adc_sha256"], predecessor_record_id=value["predecessor_record_id"],
        default_branch=value["default_branch"], default_branch_sha40=value["default_branch_sha40"],
        review_mode=value["review_mode"],
        required_checks=tuple((row["context"], row["integration_id"]) for row in checks),
        stage=value["stage"], status=value["status"], setup_branch=value["setup_branch"],
        setup_commit_sha40=value["setup_commit_sha40"], profile_sha256=value["profile_sha256"],
        plan_sha256=value["plan_sha256"], policy_status=value["policy_status"],
        ruleset_id=value["ruleset_id"], applied_record_id=value["applied_record_id"],
        effective_policy_sha256=value["effective_policy_sha256"], setup_pr_number=value["setup_pr_number"],
    ).validate()
    return checkpoint


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ConsumerActivationError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConsumerActivationError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
        raise ConsumerActivationError(f"{label} is not a valid past timestamp")
    return parsed


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ConsumerActivationError(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConsumerActivationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ConsumerActivationError(f"{label} must be a JSON object")
    return value


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ConsumerActivationError(f"{label} must be a positive integer")
    return value


def _body(marker: str, payload: dict[str, Any]) -> str:
    return f"{marker}{_canonical(payload).decode('utf-8')}\n-->"


def _decode(body: Any, marker: str, label: str, *, allow_trailer: bool = False) -> dict[str, Any]:
    if not isinstance(body, str) or not body.startswith(marker):
        raise ConsumerActivationError(f"{label} has an invalid schema marker")
    end = body.find("\n-->", len(marker))
    if end < 0 or (not allow_trailer and end + 4 != len(body)):
        raise ConsumerActivationError(f"{label} has an incomplete or non-canonical envelope")
    value = _json_object(body[len(marker):end].encode("utf-8"), label)
    if _body(marker, value) != body[:end + 4]:
        raise ConsumerActivationError(f"{label} JSON is not canonical")
    return value


def _identity(user: Any, label: str) -> tuple[int, str, str]:
    if (not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] < 1
            or not isinstance(user.get("login"), str) or not user["login"]
            or user.get("type") != "User"):
        raise ConsumerActivationError(f"{label} is not a stable human GitHub identity")
    return user["id"], user["login"].casefold(), "User"


def activation_profile(issue_number: int) -> dict[str, int]:
    return {"issue_number": _positive(issue_number, "Activation Issue number")}


def _has_issue_marker(body: Any) -> bool:
    return isinstance(body, str) and body.splitlines()[:1] == [ISSUE_MARKER]


def _profile_digest(issue_number: int) -> str:
    return hashlib.sha256(_canonical(activation_profile(issue_number))).hexdigest()


def _default_profile(repository: str) -> dict[str, Any]:
    return {
        "schema_version": 2, "initialized": True, "project_name": repository.split("/", 1)[1],
        "components": [],
        "branch": {"prefix": "feature", "max_slug_length": 48,
                   "cleanup_on_switch": [], "required_checks": []},
        "workspace": {"isolation": "auto"},
        "milestones": {"mode": "optional", "version_source": None},
        "hooks": {"branch_switch": [], "verify_quick": [], "verify_final": []},
    }


def _profile_for_setup(root: Path, repository: str, issue_number: int) -> tuple[dict[str, Any], bytes]:
    path = root / ".agent" / "project.json"
    if path_has_symlink(path, root=root):
        raise ConsumerActivationError("project.json path traverses a symbolic link")
    original = path.read_bytes() if path.is_file() else None
    if original is not None:
        try:
            value = _json_object(original, "project.json")
            load_profile(root)
        except (OSError, ProfileError, ConsumerActivationError) as exc:
            raise ConsumerActivationError(f"existing project.json is invalid: {exc}") from exc
    else:
        value = _default_profile(repository)
    current = value.get("activation")
    if current is not None:
        if not isinstance(current, dict) or set(current) != {"issue_number"}:
            raise ConsumerActivationError("project.json activation setting is malformed")
        if _positive(current.get("issue_number"), "Activation Issue number") != issue_number:
            raise ConsumerActivationError("project.json already points to a different Activation Issue")
    value["activation"] = activation_profile(issue_number)
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if original == content:
        # A successor policy still needs a reviewable setup commit. Reordering JSON keys
        # changes only presentation; the parsed profile and canonical Activation object stay exact.
        keys = list(value)
        if len(keys) > 1:
            rotated = keys[1:] + keys[:1]
            content = (json.dumps({key: value[key] for key in rotated}, ensure_ascii=False,
                                  sort_keys=False, indent=2) + "\n").encode("utf-8")
    return value, content


def _write_profile(root: Path, content: bytes) -> None:
    directory = root / ".agent"
    if path_has_symlink(directory, root=root):
        raise ConsumerActivationError(".agent path traverses a symbolic link")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "project.json"
    if path_has_symlink(target, root=root):
        raise ConsumerActivationError("project.json path traverses a symbolic link")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".project.json.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ConsumerActivationError("could not atomically write project.json") from exc


def _default_activation_adc(repository: str, issue_number: int) -> bytes:
    text = f"""# Agent Development Contract — consumer-p-ases-activation
Repository: {repository}
Issue: {issue_number}

## Issue
Define the default P-ASES Activation policy for this consumer repository.

## Scope
Authorize the normal P-ASES gate only for same-repository Issues created after verified Activation. Preserve existing Issue routing and Gate Selections.

## Change Kind
Policy definition for the consumer repository's P-ASES Activation.

## Requirements
- REQ-01: Only a non-pull-request Issue in this repository whose GitHub creation time is later than the verified Activation time may select the normal P-ASES gate.
- REQ-02: Existing or pre-Activation Issues keep their existing gate state and are never silently relabeled or migrated.
- REQ-03: Every Gate Selection stays bound to the exact Activation record that authorized it.

## Architecture Decisions
The approved ADC on this Issue is the policy authority. The project profile stores only this Issue number as a locator; verified Activation history is the evidence of authorization.

## Artifact Impact
Specification: No consumer product specification changes; this ADC defines repository workflow policy.
Design: No consumer product design changes; this ADC defines repository workflow policy.
Testing: Verify Activation timing, immutable Gate Selection, and preservation of existing Issue routing.

## Exact Changes
Use the repository's normal P-ASES gate for eligible Issues after verified Activation.

## Invariants
The repository, Activation Issue, approved ADC generation, human administrator, and Activation history must match exactly. Missing, ambiguous, edited, stale, or unauthorized evidence blocks.

## Non-goals
Do not migrate existing Issues, change their labels, or alter the separate P-ASES migration Bootstrap history.

## Verification Obligations
Check the exact Activation Issue and ADC, human admin permission, setup PR merge, required checks, default-branch ancestry, and immutable per-Issue Gate Selection.

## Reviewer Checklist
- [ ] Only later same-repository non-PR Issues can select the P-ASES gate.
- [ ] Existing Issues and Gate Selections remain unchanged.
- [ ] Activation history is complete, immutable, and authorized.

## Completion Gates
Activate only after the exact setup PR is merged by a verified repository administrator and all Activation evidence passes readback.
"""
    from .adc import parse_adc
    data = text.encode("utf-8")
    parse_adc(data, repository, issue_number)
    return data


def _fingerprint(row: Any, issue_number: int, comment_id: int, marker: str,
                 label: str) -> tuple[Any, ...]:
    if (not isinstance(row, dict) or row.get("id") != comment_id
            or not isinstance(row.get("body"), str) or not row["body"].startswith(marker)):
        raise ConsumerActivationError(f"{label} comment identity or schema is invalid")
    created, updated = row.get("created_at"), row.get("updated_at")
    if not isinstance(created, str) or created != updated:
        raise ConsumerActivationError(f"{label} comment was edited or has invalid timestamps")
    identity = _identity(row.get("user"), f"{label} author")
    return (comment_id, row["body"], created, updated, identity,
            row.get("issue_url"), row.get("html_url"), row.get("url"))


def _read_comment(github: GitHub, issue_number: int, comment_id: int, marker: str,
                  label: str, *, unique_marker: bool = True) -> dict[str, Any]:
    try:
        direct = github.issue_comment(issue_number, comment_id)
        listed = github.issue_comments(issue_number)
        matches = [row for row in listed if isinstance(row, dict) and row.get("id") == comment_id]
        marked = [row for row in listed if isinstance(row, dict) and isinstance(row.get("body"), str)
                  and row["body"].startswith(marker)]
        if (len(matches) != 1 or not any(row.get("id") == comment_id for row in marked)
                or (unique_marker and len(marked) != 1)):
            raise ConsumerActivationError(f"{label} is missing, duplicated, or ambiguous")
        after = github.issue_comment(issue_number, comment_id)
    except GitHubError as exc:
        raise ConsumerActivationError(f"{label} readback failed: {exc}") from exc
    fingerprints = [_fingerprint(row, issue_number, comment_id, marker, label)
                    for row in (direct, matches[0], after)]
    if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
        raise ConsumerActivationError(f"{label} changed during direct/list/direct readback")
    repository = github.repo
    expected_urls = (f"https://api.github.com/repos/{repository}/issues/{issue_number}",
                     f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}",
                     f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}")
    actual_urls = tuple(value.casefold() if isinstance(value, str) else None
                        for value in fingerprints[1][5:])
    if actual_urls != tuple(value.casefold() for value in expected_urls):
        raise ConsumerActivationError(f"{label} URLs do not identify the exact Issue and comment")
    return matches[0]


def _publish_comment(github: GitHub, issue_number: int, marker: str, payload: dict[str, Any],
                     label: str, *, allow_history: bool = False) -> tuple[int, str]:
    body = _body(marker, payload)
    try:
        comments = github.issue_comments(issue_number)
        matches = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                   and row["body"].startswith(marker)]
        exact = [row for row in matches if row.get("body") == body]
        if len(matches) > 1 and not allow_history:
            raise ConsumerActivationError(f"multiple {label} comments exist")
        if len(exact) > 1:
            raise ConsumerActivationError(f"duplicate exact {label} comments exist")
        if exact:
            comment_id = _positive(exact[0].get("id"), f"{label} Comment ID")
        else:
            created = github.create_issue_comment(issue_number, body)
            comment_id = _positive(created.get("id") if isinstance(created, dict) else None,
                                   f"created {label} Comment ID")
        row = _read_comment(github, issue_number, comment_id, marker, label,
                            unique_marker=not allow_history)
    except GitHubError as exc:
        raise ConsumerActivationError(f"{label} publication failed: {exc}") from exc
    if row.get("body") != body:
        raise ConsumerActivationError(f"{label} exact-body readback failed")
    return comment_id, body


def _resolve_issue(github: GitHub, configured: int | None) -> dict[str, Any] | None:
    try:
        issues = github.issues()
    except GitHubError as exc:
        raise ConsumerActivationError(f"Activation Issue lookup failed: {exc}") from exc
    marked = [row for row in issues if isinstance(row, dict) and row.get("pull_request") is None
              and _has_issue_marker(row.get("body"))]
    if any(type(row.get("number")) is not int or row["number"] < 1 for row in marked):
        raise ConsumerActivationError("marked Activation Issue has an invalid number")
    if len(marked) > 1:
        raise ConsumerActivationError("multiple marked Activation Issues exist")
    if configured is not None:
        matches = [row for row in marked if row.get("number") == configured]
        if len(matches) != 1:
            raise ConsumerActivationError("configured Activation Issue does not uniquely match its marker")
        selected = matches[0]
    else:
        selected = marked[0] if marked else None
    def signature(rows: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
        values = [(row.get("number"), row.get("state"), row.get("repository_url"), row.get("body"))
                  for row in rows]
        return tuple(sorted(values, key=lambda row: row[0]))

    if selected is None:
        try:
            after_marked = [row for row in github.issues() if isinstance(row, dict)
                            and row.get("pull_request") is None and _has_issue_marker(row.get("body"))]
        except GitHubError as exc:
            raise ConsumerActivationError(f"Activation Issue lookup readback failed: {exc}") from exc
        if (any(type(row.get("number")) is not int or row["number"] < 1 for row in after_marked)
                or signature(marked) != signature(after_marked)):
            raise ConsumerActivationError("Activation Issue marker set changed during readback")
        return None

    repo_url = selected.get("repository_url")
    if (selected.get("state") != "open" or not isinstance(repo_url, str)
            or repo_url.casefold() != f"https://api.github.com/repos/{github.repo}".casefold()):
        raise ConsumerActivationError("marked Activation Issue has invalid repository, number, or state")
    try:
        direct = github.issue(selected["number"])
        after_marked = [row for row in github.issues() if isinstance(row, dict)
                        and row.get("pull_request") is None and _has_issue_marker(row.get("body"))]
    except GitHubError as exc:
        raise ConsumerActivationError(f"Activation Issue direct readback failed: {exc}") from exc
    if (any(type(row.get("number")) is not int or row["number"] < 1 for row in after_marked)
            or signature(marked) != signature(after_marked)):
        raise ConsumerActivationError("Activation Issue marker set changed during readback")
    if (not isinstance(direct, dict) or direct.get("number") != selected["number"]
            or direct.get("state") != selected.get("state")
            or direct.get("pull_request") is not None
            or direct.get("repository_url") != selected.get("repository_url")
            or direct.get("body") != selected.get("body")
            or not _has_issue_marker(direct.get("body"))):
        raise ConsumerActivationError("Activation Issue changed during list/direct/list readback")
    return direct


def _ensure_adc(github: GitHub, issue_number: int) -> VerifiedADC:
    try:
        return verify_adc(github, issue_number)
    except ADCError as exc:
        if "Issue has no Agent Development Contract pointer" not in str(exc):
            raise ConsumerActivationError(f"Activation Issue ADC is invalid: {exc}") from exc
    data = _default_activation_adc(github.repo, issue_number)
    try:
        pointer = publish_adc(github, issue_number, data, state="draft")
        verified = verify_adc(github, issue_number)
    except ADCError as exc:
        raise ConsumerActivationError(f"proposed default Activation ADC could not be published: {exc}") from exc
    if verified.pointer != pointer or verified.contract.content != data:
        raise ConsumerActivationError("proposed default Activation ADC did not pass exact readback")
    return verified


def _setup_payload(issue_number: int, adc: VerifiedADC, predecessor_record_id: int | None) -> dict[str, Any]:
    if adc.pointer.state not in {"draft", "approved"}:
        raise ConsumerActivationError("Activation ADC pointer state is invalid")
    return {"activation_issue_number": issue_number,
            "activation_profile_sha256": _profile_digest(issue_number),
            "adc_comment_id": adc.pointer.comment_id, "adc_sha256": adc.pointer.sha256,
            "adc_state": adc.pointer.state, "predecessor_record_id": predecessor_record_id,
            "schema": "PASES_CONSUMER_ACTIVATION_SETUP_V1"}


def _setup_payload_v2(issue_number: int, adc: VerifiedADC, predecessor_record_id: int | None,
                      profile_content: bytes, review_mode: str, ruleset_id: int,
                      policy_sha256: str, applied_record_id: int,
                      checks: tuple[tuple[str, int], ...], setup_branch: str) -> dict[str, Any]:
    if review_mode != "solo_owner" or not checks:
        raise ConsumerActivationError("Activation V2 requires solo_owner and trusted Required Checks")
    if not isinstance(setup_branch, str) or not setup_branch.startswith("pases/consumer-activation-"):
        raise ConsumerActivationError("Activation V2 setup branch identity is invalid")
    return {
        "activation_issue_number": issue_number,
        "activation_profile_sha256": hashlib.sha256(profile_content).hexdigest(),
        "adc_comment_id": adc.pointer.comment_id,
        "adc_sha256": adc.pointer.sha256,
        "adc_state": adc.pointer.state,
        "branch_policy_sha256": policy_sha256,
        "ruleset_applied_record_id": applied_record_id,
        "predecessor_record_id": predecessor_record_id,
        "required_checks": [{"context": name, "integration_id": app_id} for name, app_id in checks],
        "review_mode": review_mode,
        "ruleset_id": ruleset_id,
        "setup_branch": setup_branch,
        "schema": "PASES_CONSUMER_ACTIVATION_SETUP_V2",
    }


def _setup_marker(expected: dict[str, Any]) -> str:
    return SETUP_MARKER_V2 if expected.get("schema") == "PASES_CONSUMER_ACTIVATION_SETUP_V2" else SETUP_MARKER


def _setup_branch(issue_number: int, adc_sha256: str, predecessor_record_id: int | None,
                  *, version: int = 1, base_sha40: str | None = None,
                  generation_sha256: str | None = None) -> str:
    predecessor = "initial" if predecessor_record_id is None else str(predecessor_record_id)
    suffix = "" if version == 1 else f"-v{version}"
    if version == 2:
        if not isinstance(base_sha40, str) or not SHA40.fullmatch(base_sha40):
            raise ConsumerActivationError("Activation V2 setup branch requires an exact default-branch base SHA")
        suffix += f"-b{base_sha40[:8]}"
        if generation_sha256 is not None:
            if not SHA256.fullmatch(generation_sha256):
                raise ConsumerActivationError("Activation V2 setup generation digest is invalid")
            suffix += f"-g{generation_sha256[:8]}"
    return f"pases/consumer-activation-{issue_number}-{adc_sha256[:8]}-{predecessor}{suffix}"


def _repositories_match(base: Any, head: Any, repository: str, *, expected_id: int | None = None) -> bool:
    if not isinstance(base, dict) or not isinstance(head, dict):
        return False
    base_name, head_name = base.get("full_name"), head.get("full_name")
    base_id, head_id = base.get("id"), head.get("id")
    if (not isinstance(base_name, str) or not isinstance(head_name, str)
            or base_name.casefold() != repository.casefold()
            or head_name.casefold() != repository.casefold()
            or type(base_id) is not int or base_id < 1 or base_id != head_id):
        return False
    return expected_id is None or base_id == expected_id


def _check_setup_pr(github: GitHub, pr: dict[str, Any], expected: dict[str, Any],
                    default_branch: str, repository_id: int) -> dict[str, Any]:
    base, head = pr.get("base"), pr.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    payload = _decode(pr.get("body"), _setup_marker(expected), "setup PR", allow_trailer=True)
    if (pr.get("state") != "open" or pr.get("merged") is True or pr.get("draft") is not False
            or payload != expected or not isinstance(base, dict) or base.get("ref") != default_branch
            or not isinstance(head, dict) or head.get("ref") != (
                expected.get("setup_branch") if expected.get("schema") == "PASES_CONSUMER_ACTIVATION_SETUP_V2"
                else _setup_branch(expected["activation_issue_number"], expected["adc_sha256"],
                                   expected["predecessor_record_id"], version=1))
            or not _repositories_match(base_repo, head_repo, github.repo, expected_id=repository_id)):
        raise ConsumerActivationError("existing setup PR is closed, forked, draft, or mismatched")
    files = github.pull_request_files(_positive(pr.get("number"), "setup PR number"))
    if len(files) != 1 or files[0].get("filename") != ".agent/project.json":
        raise ConsumerActivationError("setup PR must change exactly .agent/project.json")
    return pr


def verify_setup_pr_ready_to_merge(github: GitHub, pr_number: int) -> dict[str, Any]:
    """Require fresh Activation V2 policy, checks and independent review before merge."""
    def snapshot() -> dict[str, Any]:
        metadata = github.repository_metadata()
        owner = metadata.get("owner") if isinstance(metadata, dict) else None
        if (not isinstance(metadata, dict) or metadata.get("id") != 1401910271
                or metadata.get("full_name") != "puchinya/ai-agent-workflow"
                or not isinstance(owner, dict) or owner.get("id") != 3744776 or owner.get("type") != "User"):
            raise ConsumerActivationError("Activation merge repository identity differs from its pinned owner/repository")
        default_branch = metadata.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            raise ConsumerActivationError("Activation merge default branch is unavailable")
        pr = github.pull_request(pr_number)
        if (pr.get("state") != "open" or pr.get("merged") is True or pr.get("draft") is not False
                or pr.get("mergeable") is not True):
            raise ConsumerActivationError("Activation Setup PR is not open, mergeable and non-draft")
        expected = _decode(pr.get("body"), SETUP_MARKER_V2, "Activation Setup PR", allow_trailer=True)
        if expected.get("activation_issue_number") != 57 or expected.get("schema") != "PASES_CONSUMER_ACTIVATION_SETUP_V2":
            raise ConsumerActivationError("PR is not the configured Activation V2 Setup PR for Issue #57")
        _check_setup_pr(github, pr, expected, default_branch, 1401910271)
        base, head = pr.get("base"), pr.get("head")
        base_sha = base.get("sha") if isinstance(base, dict) else None
        head_sha = head.get("sha") if isinstance(head, dict) else None
        author = pr.get("user")
        author_id = author.get("id") if isinstance(author, dict) else None
        if (not isinstance(base_sha, str) or not SHA40.fullmatch(base_sha)
                or not isinstance(head_sha, str) or not SHA40.fullmatch(head_sha)
                or type(author_id) is not int or author_id < 1):
            raise ConsumerActivationError("Activation Setup PR base, HEAD or author identity is incomplete")
        branch_sha = github.branch(default_branch).get("commit", {}).get("sha")
        if branch_sha != base_sha:
            raise ConsumerActivationError("Activation Setup PR base is stale; regenerate it from current default branch")

        issue = github.issue(57)
        if (issue.get("number") != 57 or issue.get("state") != "open" or issue.get("pull_request") is not None
                or not _has_issue_marker(issue.get("body"))
                or issue.get("repository_url") != "https://api.github.com/repos/puchinya/ai-agent-workflow"):
            raise ConsumerActivationError("Activation Issue #57 identity or marker is invalid")
        history = read_consumer_activation_history(github, github.repo, 57, allow_pending_approval=True)
        predecessor = history[-1][1] if history else None
        if expected.get("predecessor_record_id") != predecessor:
            raise ConsumerActivationError("Activation Setup PR predecessor is stale")
        proposed = verify_adc_generation(
            github, 57, expected.get("adc_comment_id"), expected.get("adc_sha256"),
            state=expected.get("adc_state"),
        )
        current_adc = verify_adc(github, 57)
        if (current_adc.pointer.sha256 != proposed.pointer.sha256
                or current_adc.contract.content != proposed.contract.content):
            raise ConsumerActivationError("Activation ADC changed after this Setup PR was created")

        profile_bytes = github.regular_content_at_ref(".agent/project.json", head_sha)
        profile, required_checks = _validate_profile_bytes(profile_bytes, 57)
        expected_checks = tuple(sorted((row.get("context"), row.get("integration_id"))
                                       for row in expected.get("required_checks", [])
                                       if isinstance(row, dict)))
        if (hashlib.sha256(profile_bytes).hexdigest() != expected.get("activation_profile_sha256")
                or profile.get("final_delivery") != {"review_mode": "solo_owner"}
                or tuple(sorted(required_checks)) != expected_checks):
            raise ConsumerActivationError("Activation Setup PR profile bytes or Required Checks changed")
        try:
            policy = read_verified_managed_policy(
                github, default_branch, required_checks, "solo_owner", 57,
            )
        except RulesetManagementError as exc:
            raise ConsumerActivationError(f"Activation effective policy is not VERIFIED: {exc}") from exc
        if (policy.get("ruleset_id") != expected.get("ruleset_id")
                or policy.get("applied_record_id") != expected.get("ruleset_applied_record_id")
                or policy.get("effective_policy_sha256") != expected.get("branch_policy_sha256")):
            raise ConsumerActivationError("Activation Setup PR policy binding is stale")

        runs = github.check_runs_for_ref(head_sha)
        check_evidence: list[tuple[Any, ...]] = []
        for name, app_id in required_checks:
            matching = [row for row in runs if row.get("name") == name and row.get("head_sha") == head_sha
                        and isinstance(row.get("app"), dict) and row["app"].get("id") == app_id]
            if not matching:
                raise ConsumerActivationError(f"Required Check {name} has no trusted Check Run on the Setup PR HEAD")
            dated: list[tuple[datetime, int, dict[str, Any]]] = []
            for row in matching:
                resolved = _check_run_with_creation_time(github, row)
                created = _timestamp(resolved.get("created_at"), f"Required Check {name} creation time")
                dated.append((created, _positive(row.get("id"), f"Required Check {name} Run ID"), resolved))
            _created, run_id, selected = max(dated, key=lambda item: (item[0], item[1]))
            completed = _timestamp(selected.get("completed_at"), f"Required Check {name} completion time")
            if (selected.get("status") != "completed" or selected.get("conclusion") != "success"
                    or selected.get("head_sha") != head_sha or completed < max(item[0] for item in dated)):
                raise ConsumerActivationError(f"Required Check {name} is not currently successful on the Setup PR HEAD")
            check_evidence.append((name, app_id, run_id, selected.get("status"),
                                   selected.get("conclusion"), selected.get("completed_at")))

        aggregate = github.pull_review_decision(pr_number)
        if (aggregate.get("state") != "OPEN" or aggregate.get("headRefOid") != head_sha
                or aggregate.get("reviewDecision") != "APPROVED"):
            raise ConsumerActivationError("Activation Setup PR lacks an approved review decision on its exact HEAD")
        reviews = github.pull_reviews(pr_number)
        independent = [row for row in reviews if row.get("state") == "APPROVED"
                       and row.get("commit_id") == head_sha
                       and isinstance(row.get("user"), dict)
                       and type(row["user"].get("id")) is int and row["user"]["id"] != author_id
                       and row["user"].get("type") == "User"]
        if not independent:
            raise ConsumerActivationError("Activation Setup PR lacks an independent human approval on its exact HEAD")
        threads = github.pull_review_threads(pr_number)
        unresolved = [thread for thread in threads if thread.get("isResolved") is not True]
        if unresolved:
            raise ConsumerActivationError("Activation Setup PR has unresolved review threads")

        return {
            "pr_number": pr_number, "head_sha40": head_sha, "base_sha40": base_sha,
            "setup_payload_sha256": hashlib.sha256(_canonical(expected)).hexdigest(),
            "activation_adc_sha256": proposed.pointer.sha256,
            "activation_predecessor_record_id": predecessor,
            "policy_sha256": policy["effective_policy_sha256"], "ruleset_id": policy["ruleset_id"],
            "applied_record_id": policy["applied_record_id"],
            "check_evidence": check_evidence,
            "reviewer_ids": sorted({row["user"]["id"] for row in independent}),
            "resolved_thread_count": len(threads),
        }

    first = snapshot()
    second = snapshot()
    if first != second:
        raise ConsumerActivationError("Activation Setup PR gates changed during merge preflight")
    return {"status": "READY", **second}


def _validate_profile_bytes(raw: bytes, issue_number: int) -> tuple[dict[str, Any], tuple[tuple[str, int], ...]]:
    profile = _json_object(raw, "merged project.json")
    try:
        with tempfile.TemporaryDirectory(prefix="pases-profile-check-") as tmp:
            path = Path(tmp) / ".agent" / "project.json"
            path.parent.mkdir()
            path.write_bytes(raw)
            parsed = load_profile(Path(tmp))
    except (OSError, ProfileError) as exc:
        raise ConsumerActivationError(f"merged project.json is invalid: {exc}") from exc
    activation = profile.get("activation")
    if not isinstance(activation, dict) or activation != activation_profile(issue_number):
        raise ConsumerActivationError("merged project.json does not contain the exact Activation Issue locator")
    checks = parsed.required_checks
    if not checks or any(app_id is None for _name, app_id in checks):
        raise ConsumerActivationError("merged project.json must configure trusted Required Checks")
    return profile, tuple((name, app_id) for name, app_id in checks if app_id is not None)


def _check_run_with_creation_time(github: GitHub, row: dict[str, Any]) -> dict[str, Any]:
    """Use the linked Actions Job timestamp when GitHub omits Check Run created_at."""
    if row.get("created_at") is not None:
        return row
    try:
        job = github.workflow_job_for_check_run(row)
    except GitHubError as exc:
        raise ConsumerActivationError("Required Check creation time could not be verified") from exc
    created_at = job.get("created_at") if isinstance(job, dict) else None
    if not isinstance(created_at, str):
        raise ConsumerActivationError("Required Check creation time could not be verified")
    return {**row, "created_at": created_at}


def _required_check_evidence(
    github: GitHub, head_sha40: str, checks: tuple[tuple[str, int], ...],
    expected: tuple[RequiredCheckEvidence, ...] | None, merged_at: str,
) -> tuple[RequiredCheckEvidence, ...]:
    merge_time = _timestamp(merged_at, "setup PR merge time")
    if expected is not None:
        if tuple((item.name, item.app_id) for item in expected) != checks:
            raise ConsumerActivationError("pinned Required Check identities do not match the merged project profile")
        evidence: list[RequiredCheckEvidence] = []
        for pinned in expected:
            current_row = _check_run_with_creation_time(github, github.check_run(pinned.check_run_id))
            current = RequiredCheckEvidence.from_run(current_row)
            if (current != pinned or current.head_sha40 != head_sha40
                    or _timestamp(current.completed_at, f"Required Check {current.name} completion time") > merge_time):
                raise ConsumerActivationError(
                    f"pinned Required Check {pinned.name} no longer matches its successful pre-merge Check Run"
                )
            evidence.append(current)
        return tuple(evidence)

    runs = github.check_runs_for_ref(head_sha40)
    evidence = []
    for name, app_id in checks:
        matching = [row for row in runs if row.get("name") == name and row.get("head_sha") == head_sha40
                    and isinstance(row.get("app"), dict) and row["app"].get("id") == app_id]
        if not matching:
            raise ConsumerActivationError(f"Required Check {name} did not pass: no trusted Check Run on PR HEAD")
        dated: list[tuple[datetime, int, dict[str, Any]]] = []
        seen_ids: set[int] = set()
        for row in matching:
            resolved = _check_run_with_creation_time(github, row)
            created = _timestamp(resolved.get("created_at"), f"Required Check {name} creation time")
            run_id = _positive(row.get("id"), f"Required Check {name} Run ID")
            if run_id in seen_ids:
                raise ConsumerActivationError(f"Required Check {name} has duplicate Check Run IDs")
            seen_ids.add(run_id)
            if created <= merge_time:
                dated.append((created, run_id, resolved))
        if not dated:
            raise ConsumerActivationError(f"Required Check {name} did not exist by setup PR merge")
        # GitHub timestamps can tie across reruns; the numeric Run ID gives a
        # stable order independent of API response ordering.
        _created, _run_id, latest = max(dated, key=lambda item: (item[0], item[1]))
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ConsumerActivationError(f"Required Check {name} latest Check Run at merge did not pass")
        selected = RequiredCheckEvidence.from_run(latest)
        if (_timestamp(selected.completed_at, f"Required Check {name} completion time") > merge_time):
            raise ConsumerActivationError(f"Required Check {name} completed after setup PR merge")
        if selected.head_sha40 != head_sha40:
            raise ConsumerActivationError(f"Required Check {name} belongs to a different PR HEAD")
        evidence.append(selected)
    return tuple(evidence)


def _validate_merged_setup(github: GitHub, pr_number: int, expected: dict[str, Any], *,
                           require_current_adc: bool, require_current_admin: bool,
                           require_current_policy: bool = True,
                           expected_check_runs: tuple[RequiredCheckEvidence, ...] | None = None
                           ) -> tuple[dict[str, Any], dict[str, Any], VerifiedADC,
                                      tuple[RequiredCheckEvidence, ...]]:
    try:
        pr = github.pull_request(pr_number)
        metadata = github.repository_metadata()
        default_branch = metadata.get("default_branch")
        repository_id = metadata.get("id")
        base, head = pr.get("base"), pr.get("head")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        head_repo = head.get("repo") if isinstance(head, dict) else None
        merger = pr.get("merged_by")
        merge_sha, merged_at = pr.get("merge_commit_sha"), pr.get("merged_at")
        is_v2 = expected.get("schema") == "PASES_CONSUMER_ACTIVATION_SETUP_V2"
        if (pr.get("state") != "closed" or pr.get("merged") is not True or pr.get("draft") is not False
                or _decode(pr.get("body"), _setup_marker(expected), "setup PR", allow_trailer=True) != expected
                or not isinstance(default_branch, str) or not isinstance(base, dict)
                or base.get("ref") != default_branch or not isinstance(head, dict)
                or type(repository_id) is not int or repository_id < 1
                or not _repositories_match(base_repo, head_repo, github.repo, expected_id=repository_id)
                or not isinstance(head.get("sha"), str) or not SHA40.fullmatch(head["sha"])
                or (is_v2 and (not isinstance(expected.get("setup_branch"), str)
                               or head.get("ref") != expected.get("setup_branch")))
                or not isinstance(merge_sha, str) or not SHA40.fullmatch(merge_sha)
                or not isinstance(merged_at, str)):
            raise ConsumerActivationError("merged setup PR identity is incomplete or mismatched")
        merger_identity = _identity(merger, "setup PR merger")
        if require_current_admin:
            permission = github.collaborator_permission(merger["login"])
            if (permission.get("permission") != "admin"
                    or _identity(permission.get("user"), "setup PR merger") != merger_identity):
                raise ConsumerActivationError("setup PR must be merged by a current repository admin")
        current_default_sha = github.branch(default_branch).get("commit", {}).get("sha")
        if (not isinstance(current_default_sha, str) or not SHA40.fullmatch(current_default_sha)
                or github.compare_commits(merge_sha, current_default_sha).get("status") not in {"ahead", "identical"}):
            raise ConsumerActivationError("setup PR merge commit is not on the current default branch")
        files = github.pull_request_files(pr_number)
        if len(files) != 1 or files[0].get("filename") != ".agent/project.json":
            raise ConsumerActivationError("setup PR must change exactly .agent/project.json")
        raw_profile = github.regular_content_at_ref(".agent/project.json", merge_sha)
        profile_value, checks = _validate_profile_bytes(raw_profile, expected["activation_issue_number"])
        if is_v2:
            if (hashlib.sha256(raw_profile).hexdigest() != expected["activation_profile_sha256"]
                    or profile_value.get("final_delivery") != {"review_mode": expected.get("review_mode")}
                    or expected.get("review_mode") != "solo_owner"):
                raise ConsumerActivationError("setup PR V2 profile bytes or review mode are invalid")
            expected_checks = tuple((row.get("context"), row.get("integration_id"))
                                    for row in expected.get("required_checks", [])
                                    if isinstance(row, dict))
            if tuple(sorted(checks)) != tuple(sorted(expected_checks)) or not checks:
                raise ConsumerActivationError("setup PR V2 Required Checks differ from its exact profile")
            _positive(expected.get("ruleset_id"), "Activation V2 Ruleset ID")
            _positive(expected.get("ruleset_applied_record_id"), "Activation V2 applied-policy record ID")
            if not isinstance(expected.get("branch_policy_sha256"), str) or not SHA256.fullmatch(
                    expected["branch_policy_sha256"]):
                raise ConsumerActivationError("Activation V2 effective-policy digest is invalid")
        elif hashlib.sha256(_canonical(activation_profile(expected["activation_issue_number"]))).hexdigest() != expected["activation_profile_sha256"]:
            raise ConsumerActivationError("setup PR Activation profile digest is invalid")
        check_evidence = _required_check_evidence(
            github, head["sha"], checks, expected_check_runs, merged_at,
        )
        if is_v2 and require_current_policy:
            try:
                managed = read_verified_managed_policy(
                    github, default_branch, checks, expected["review_mode"],
                    expected["activation_issue_number"],
                )
            except RulesetManagementError as exc:
                raise ConsumerActivationError(f"V2 effective branch policy could not be verified: {exc}") from exc
            if (managed["ruleset_id"] != expected["ruleset_id"]
                    or managed["effective_policy_sha256"] != expected["branch_policy_sha256"]
                    or managed["applied_record_id"] != expected["ruleset_applied_record_id"]):
                raise ConsumerActivationError("V2 setup PR effective-policy evidence is stale or mismatched")
        issue_number = expected["activation_issue_number"]
        issue = github.issue(issue_number)
        issue_repository_url = issue.get("repository_url")
        if (issue.get("number") != issue_number or issue.get("pull_request") is not None
                or not _has_issue_marker(issue.get("body"))
                or not isinstance(issue_repository_url, str)
                or issue_repository_url.casefold() != f"https://api.github.com/repos/{github.repo}".casefold()):
            raise ConsumerActivationError("Activation Issue marker or repository identity is invalid")
    except GitHubError as exc:
        raise ConsumerActivationError(f"merged setup PR evidence readback failed: {exc}") from exc
    try:
        proposed = verify_adc_generation(
            github, expected["activation_issue_number"], expected["adc_comment_id"],
            expected["adc_sha256"], state=expected["adc_state"],
        )
        if require_current_adc:
            latest = verify_adc(github, expected["activation_issue_number"])
            same_content = (latest.pointer.sha256 == proposed.pointer.sha256
                           and latest.contract.content == proposed.contract.content)
            exact_proposal = latest.pointer == proposed.pointer
            promoted = (expected["adc_state"] == "draft" and latest.pointer.state == "approved"
                        and same_content)
            if not exact_proposal and not promoted:
                raise ConsumerActivationError("setup PR refers to a stale or superseded Activation ADC")
    except ADCError as exc:
        raise ConsumerActivationError(f"Activation ADC is missing, changed, or not journaled: {exc}") from exc
    return pr, issue, proposed, check_evidence


@dataclass(frozen=True)
class RequiredCheckEvidence:
    check_run_id: int
    name: str
    app_id: int
    head_sha40: str
    created_at: str
    started_at: str
    completed_at: str
    status: str
    conclusion: str

    def validate(self) -> "RequiredCheckEvidence":
        _positive(self.check_run_id, "Required Check Run ID")
        _positive(self.app_id, "Required Check App ID")
        if (not isinstance(self.name, str) or not self.name
                or not isinstance(self.head_sha40, str) or not SHA40.fullmatch(self.head_sha40)
                or self.status != "completed" or self.conclusion != "success"):
            raise ConsumerActivationError("Required Check evidence is not a successful trusted Check Run")
        created = _timestamp(self.created_at, "Check Run creation time")
        started = _timestamp(self.started_at, "Check Run start time")
        completed = _timestamp(self.completed_at, "Check Run completion time")
        if not created <= started <= completed:
            raise ConsumerActivationError("Required Check Run timestamps are out of order")
        return self

    @classmethod
    def from_run(cls, value: Any) -> "RequiredCheckEvidence":
        app = value.get("app") if isinstance(value, dict) else None
        if not isinstance(value, dict) or not isinstance(app, dict):
            raise ConsumerActivationError("Required Check API response is malformed")
        return cls(value.get("id"), value.get("name"), app.get("id"), value.get("head_sha"),
                   value.get("created_at"), value.get("started_at"), value.get("completed_at"),
                   value.get("status"), value.get("conclusion")).validate()

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "app_id": self.app_id, "check_run_id": self.check_run_id,
            "completed_at": self.completed_at, "conclusion": self.conclusion,
            "created_at": self.created_at, "head_sha40": self.head_sha40,
            "name": self.name, "started_at": self.started_at, "status": self.status,
        }

    @classmethod
    def from_payload(cls, value: Any) -> "RequiredCheckEvidence":
        expected = {"app_id", "check_run_id", "completed_at", "conclusion", "created_at",
                    "head_sha40", "name", "started_at", "status"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ConsumerActivationError("Required Check evidence has unknown schema or fields")
        return cls(value["check_run_id"], value["name"], value["app_id"], value["head_sha40"],
                   value["created_at"], value["started_at"], value["completed_at"],
                   value["status"], value["conclusion"]).validate()


@dataclass(frozen=True)
class ConsumerActivationRecord:
    repository: str
    activation_issue_number: int
    proposed_adc_comment_id: int
    proposed_adc_sha256: str
    proposed_adc_state: str
    adc_comment_id: int
    adc_sha256: str
    activation_profile_sha256: str
    setup_pr_number: int
    setup_pr_id: int
    merge_commit_sha40: str
    merged_at: str
    merger_id: int
    merger_login: str
    merger_type: str
    approval_comment_id: int
    predecessor_record_id: int | None
    required_check_runs: tuple["RequiredCheckEvidence", ...]
    record_created_at: str | None = None
    schema_version: int = 1
    review_mode: str | None = None
    ruleset_id: int | None = None
    branch_policy_sha256: str | None = None
    ruleset_applied_record_id: int | None = None
    setup_branch: str | None = None

    def validate(self) -> "ConsumerActivationRecord":
        if not isinstance(self.repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise ConsumerActivationError("Activation repository is invalid")
        for value, label in ((self.activation_issue_number, "Activation Issue"),
                             (self.proposed_adc_comment_id, "proposed ADC comment"),
                             (self.adc_comment_id, "approved ADC comment"),
                             (self.setup_pr_number, "setup PR"), (self.setup_pr_id, "setup PR ID"),
                             (self.merger_id, "PR merger"), (self.approval_comment_id, "approval comment")):
            _positive(value, label)
        for digest, label in ((self.proposed_adc_sha256, "proposed ADC"),
                              (self.adc_sha256, "approved ADC"),
                              (self.activation_profile_sha256, "Activation profile")):
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise ConsumerActivationError(f"{label} digest is invalid")
        if self.proposed_adc_sha256 != self.adc_sha256 or self.proposed_adc_state not in {"draft", "approved"}:
            raise ConsumerActivationError("proposed and approved Activation ADC do not match")
        if not isinstance(self.merge_commit_sha40, str) or not SHA40.fullmatch(self.merge_commit_sha40):
            raise ConsumerActivationError("Activation merge SHA is invalid")
        if (not isinstance(self.merger_login, str) or not re.fullmatch(r"[A-Za-z0-9-]+", self.merger_login)
                or self.merger_type != "User"):
            raise ConsumerActivationError("Activation merger identity is invalid")
        merged = _timestamp(self.merged_at, "setup PR merge time")
        if self.record_created_at is not None:
            if _timestamp(self.record_created_at, "Activation comment creation time") < merged:
                raise ConsumerActivationError("Activation record was created before its setup PR merge")
        if self.predecessor_record_id is not None:
            _positive(self.predecessor_record_id, "predecessor Activation record")
        if self.schema_version == 1:
            if any(value is not None for value in (self.review_mode, self.ruleset_id, self.branch_policy_sha256,
                                                   self.ruleset_applied_record_id, self.setup_branch)):
                raise ConsumerActivationError("V1 Activation record cannot contain V2 policy fields")
        elif self.schema_version == 2:
            if (self.review_mode != "solo_owner" or type(self.ruleset_id) is not int or self.ruleset_id < 1
                    or not isinstance(self.branch_policy_sha256, str)
                    or not SHA256.fullmatch(self.branch_policy_sha256)
                    or type(self.ruleset_applied_record_id) is not int
                    or self.ruleset_applied_record_id < 1
                    or not isinstance(self.setup_branch, str)
                    or not self.setup_branch.startswith("pases/consumer-activation-")):
                raise ConsumerActivationError("V2 Activation policy evidence is incomplete")
        else:
            raise ConsumerActivationError("Activation record version is unknown")
        if (not isinstance(self.required_check_runs, tuple) or not self.required_check_runs
                or any(not isinstance(item, RequiredCheckEvidence) for item in self.required_check_runs)
                or len({item.name for item in self.required_check_runs}) != len(self.required_check_runs)):
            raise ConsumerActivationError("Activation required-check evidence is missing, duplicate, or malformed")
        for item in self.required_check_runs:
            item.validate()
            if _timestamp(item.completed_at, f"Required Check {item.name} completion time") > merged:
                raise ConsumerActivationError(
                    f"Required Check {item.name} completed after the setup PR merge"
                )
        return self

    @property
    def activated_at(self) -> str:
        self.validate()
        if self.schema_version == 2:
            if self.record_created_at is None:
                raise ConsumerActivationError("V2 Activation record creation time is missing")
            return self.record_created_at
        return self.merged_at

    def payload(self) -> dict[str, Any]:
        self.validate()
        value = {
            "activation_issue_number": self.activation_issue_number,
            "activation_profile_sha256": self.activation_profile_sha256,
            "adc_comment_id": self.adc_comment_id, "adc_sha256": self.adc_sha256,
            "approval_comment_id": self.approval_comment_id,
            "merge_commit_sha40": self.merge_commit_sha40, "merged_at": self.merged_at,
            "merger_id": self.merger_id, "merger_login": self.merger_login,
            "merger_type": self.merger_type,
            "predecessor_record_id": self.predecessor_record_id,
            "proposed_adc_comment_id": self.proposed_adc_comment_id,
            "proposed_adc_sha256": self.proposed_adc_sha256,
            "proposed_adc_state": self.proposed_adc_state,
            "required_check_runs": [item.payload() for item in self.required_check_runs],
            "repository": self.repository, "setup_pr_id": self.setup_pr_id,
            "setup_pr_number": self.setup_pr_number,
            "schema": f"PASES_CONSUMER_ACTIVATION_V{self.schema_version}",
        }
        if self.schema_version == 2:
            value.update({
                "branch_policy_sha256": self.branch_policy_sha256,
                "review_mode": self.review_mode,
                "ruleset_id": self.ruleset_id,
                "ruleset_applied_record_id": self.ruleset_applied_record_id,
                "setup_branch": self.setup_branch,
            })
        return value

    @classmethod
    def from_payload(cls, value: Any) -> "ConsumerActivationRecord":
        common = {"activation_issue_number", "activation_profile_sha256", "adc_comment_id", "adc_sha256",
                    "approval_comment_id", "merge_commit_sha40", "merged_at", "merger_id", "merger_login",
                    "merger_type", "predecessor_record_id", "proposed_adc_comment_id", "proposed_adc_sha256",
                    "proposed_adc_state", "required_check_runs", "repository", "setup_pr_id",
                    "setup_pr_number", "schema"}
        if not isinstance(value, dict):
            raise ConsumerActivationError("Activation record has unknown schema or fields")
        version = 1 if value.get("schema") == "PASES_CONSUMER_ACTIVATION_V1" else (
            2 if value.get("schema") == "PASES_CONSUMER_ACTIVATION_V2" else None)
        expected = common if version == 1 else common | {
            "branch_policy_sha256", "review_mode", "ruleset_id", "ruleset_applied_record_id", "setup_branch",
        } if version == 2 else set()
        if not expected or set(value) != expected:
            raise ConsumerActivationError("Activation record has unknown schema or fields")
        if not isinstance(value["required_check_runs"], list):
            raise ConsumerActivationError("Activation required-check evidence must be a list")
        return cls(
            repository=value["repository"], activation_issue_number=value["activation_issue_number"],
            proposed_adc_comment_id=value["proposed_adc_comment_id"],
            proposed_adc_sha256=value["proposed_adc_sha256"], proposed_adc_state=value["proposed_adc_state"],
            adc_comment_id=value["adc_comment_id"], adc_sha256=value["adc_sha256"],
            activation_profile_sha256=value["activation_profile_sha256"],
            setup_pr_number=value["setup_pr_number"], setup_pr_id=value["setup_pr_id"],
            merge_commit_sha40=value["merge_commit_sha40"], merged_at=value["merged_at"],
            merger_id=value["merger_id"], merger_login=value["merger_login"],
            merger_type=value["merger_type"], approval_comment_id=value["approval_comment_id"],
            predecessor_record_id=value["predecessor_record_id"],
            required_check_runs=tuple(RequiredCheckEvidence.from_payload(row)
                                      for row in value["required_check_runs"]),
            schema_version=version,
            review_mode=value.get("review_mode"), ruleset_id=value.get("ruleset_id"),
            branch_policy_sha256=value.get("branch_policy_sha256"),
            ruleset_applied_record_id=value.get("ruleset_applied_record_id"),
            setup_branch=value.get("setup_branch"),
        ).validate()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()


def _approval_payload(record_fields: dict[str, Any], *, predecessor: int | None) -> dict[str, Any]:
    version = 2 if record_fields.get("schema") == "PASES_CONSUMER_ACTIVATION_V2" else 1
    value = {
        "activation_issue_number": record_fields["activation_issue_number"],
        "activation_profile_sha256": record_fields["activation_profile_sha256"],
        "adc_comment_id": record_fields["adc_comment_id"], "adc_sha256": record_fields["adc_sha256"],
        "approved": True, "merge_commit_sha40": record_fields["merge_commit_sha40"],
        "merged_at": record_fields["merged_at"], "merger_id": record_fields["merger_id"],
        "merger_login": record_fields["merger_login"], "merger_type": record_fields["merger_type"],
        "predecessor_record_id": predecessor,
        "proposed_adc_comment_id": record_fields["proposed_adc_comment_id"],
        "proposed_adc_sha256": record_fields["proposed_adc_sha256"],
        "proposed_adc_state": record_fields["proposed_adc_state"],
        "required_check_runs": record_fields["required_check_runs"],
        "repository": record_fields["repository"], "setup_pr_id": record_fields["setup_pr_id"],
        "setup_pr_number": record_fields["setup_pr_number"],
        "schema": f"PASES_CONSUMER_ACTIVATION_APPROVAL_V{version}",
    }
    if version == 2:
        value.update({
            "branch_policy_sha256": record_fields["branch_policy_sha256"],
            "review_mode": record_fields["review_mode"],
            "ruleset_id": record_fields["ruleset_id"],
            "ruleset_applied_record_id": record_fields["ruleset_applied_record_id"],
            "setup_branch": record_fields["setup_branch"],
        })
    return value


def _ensure_setup_branch(root: Path, branch_ref: str, base_sha40: str, content: bytes) -> tuple[str, bool]:
    """Create or resume the one-path Activation branch, then pin its exact pushed commit."""
    local_exists = branch_exists(root, branch_ref)
    remote_exists = remote_branch_exists(root, branch_ref)
    resumed = local_exists or remote_exists
    if not resumed:
        create_branch(root, branch_ref, base_sha40)
        _write_profile(root, content)
        commit_sha = commit_and_push_one_path(
            root, branch_ref, ".agent/project.json", "chore: prepare P-ASES consumer activation",
        )
        remote_exists = True
    else:
        remote_sha = remote_branch_sha(root, branch_ref) if remote_exists else None
        if local_exists:
            switch_branch(root, branch_ref)
            commit_sha = head_sha40(root)
            if remote_sha is not None and remote_sha != commit_sha:
                raise ConsumerActivationError("local and remote Activation setup branch commits differ")
            if not remote_exists and commit_sha == base_sha40:
                _write_profile(root, content)
                commit_sha = commit_and_push_one_path(
                    root, branch_ref, ".agent/project.json", "chore: prepare P-ASES consumer activation",
                )
                remote_exists = True
        else:
            if remote_sha is None:
                raise ConsumerActivationError("remote Activation setup branch disappeared during readback")
            fetched_sha = fetch_remote_branch_exact(root, branch_ref, remote_sha)
            create_branch(root, branch_ref, fetched_sha)
            commit_sha = head_sha40(root)
    if (current_branch(root) != branch_ref or head_sha40(root) != commit_sha
            or commit_parent_sha40(root, commit_sha) != base_sha40
            or changed_paths_between(root, base_sha40, commit_sha) != (".agent/project.json",)
            or activation_profile_bytes_at_commit(root, commit_sha) != content
            or not worktree_clean(root)):
        raise ConsumerActivationError(
            "Activation setup branch is not the exact one-file change for the current subject"
        )
    if not remote_exists:
        push_branch_exact(root, branch_ref, commit_sha)
    if remote_branch_sha(root, branch_ref) != commit_sha or not worktree_clean(root):
        raise ConsumerActivationError("Activation setup branch failed exact remote/worktree readback")
    return commit_sha, resumed


def _checkpoint_v2(root: Path, *, repository: str, repository_id: int, owner_id: int,
                   issue_number: int, adc: VerifiedADC, predecessor_record_id: int | None,
                   default_branch: str, default_branch_sha40: str, checks: tuple[tuple[str, int], ...],
                   stage: str, status: str, setup_branch: str | None = None,
                   setup_commit_sha40: str | None = None, profile_sha256: str | None = None,
                   plan_sha256: str | None = None, policy_status: str | None = None,
                   ruleset_id: int | None = None, applied_record_id: int | None = None,
                   effective_policy_sha256: str | None = None, setup_pr_number: int | None = None
                   ) -> tuple[ActivationCheckpoint, Path, str]:
    checkpoint = ActivationCheckpoint(
        repository=repository, repository_id=repository_id, owner_id=owner_id,
        activation_issue_number=issue_number, adc_comment_id=adc.pointer.comment_id,
        adc_sha256=adc.pointer.sha256, predecessor_record_id=predecessor_record_id,
        default_branch=default_branch, default_branch_sha40=default_branch_sha40,
        review_mode="solo_owner", required_checks=checks, stage=stage, status=status,
        setup_branch=setup_branch, setup_commit_sha40=setup_commit_sha40,
        profile_sha256=profile_sha256, plan_sha256=plan_sha256,
        policy_status=policy_status, ruleset_id=ruleset_id, applied_record_id=applied_record_id,
        effective_policy_sha256=effective_policy_sha256, setup_pr_number=setup_pr_number,
    ).validate()
    path = activation_checkpoint_path(root, issue_number)
    digest = write_activation_checkpoint(path, checkpoint, root=root)
    return checkpoint, path, digest


def _policy_inventory(operation: str, *, verified: bool, blockers: tuple[str, ...] = ()) -> dict[str, str]:
    if verified:
        return {"activation_profile": "VERIFIED", "review_mode": "VERIFIED",
                "repository_ruleset": "VERIFIED", "effective_default_branch_policy": "VERIFIED",
                "required_checks": "VERIFIED"}
    if blockers:
        return {"activation_profile": "VERIFIED", "review_mode": "VERIFIED",
                "repository_ruleset": "BLOCKED", "effective_default_branch_policy": "BLOCKED",
                "required_checks": "VERIFIED"}
    if operation in {"create", "update"}:
        return {"activation_profile": "VERIFIED", "review_mode": "VERIFIED",
                "repository_ruleset": "NEEDS_APPLY", "effective_default_branch_policy": "NEEDS_APPLY",
                "required_checks": "VERIFIED"}
    return {"activation_profile": "VERIFIED", "review_mode": "VERIFIED",
            "repository_ruleset": "BLOCKED", "effective_default_branch_policy": "BLOCKED",
            "required_checks": "VERIFIED"}


def activation_setting_inventory(review_mode: str, *, required_checks_verified: bool,
                                 policy_verified: bool = False, blocked: bool = False) -> dict[str, str]:
    """Report every Activation setting and distinguish unsupported V1 policy from unmet requirements."""
    checks = "VERIFIED" if required_checks_verified else "BLOCKED"
    profile = "VERIFIED" if required_checks_verified else "BLOCKED"
    if review_mode == "solo_owner":
        policy = "BLOCKED" if blocked else ("VERIFIED" if policy_verified else "NEEDS_APPLY")
        return {"activation_profile": profile, "review_mode": "VERIFIED",
                "repository_ruleset": policy, "effective_default_branch_policy": policy,
                "required_checks": checks}
    if review_mode == "external_reviewer":
        return {"activation_profile": profile, "review_mode": "VERIFIED",
                "repository_ruleset": "UNSUPPORTED", "effective_default_branch_policy": "UNSUPPORTED",
                "required_checks": checks}
    return {"activation_profile": "BLOCKED", "review_mode": "BLOCKED",
            "repository_ruleset": "BLOCKED", "effective_default_branch_policy": "BLOCKED",
            "required_checks": checks}


def _stale_policy_bound_setup_pr(github: GitHub, pr: dict[str, Any], expected: dict[str, Any],
                                 default_branch: str, repository_id: int) -> bool:
    """Recognize only an otherwise exact open PR whose immutable policy binding is stale."""
    policy_fields = {"branch_policy_sha256", "ruleset_applied_record_id", "ruleset_id"}
    try:
        payload = _decode(pr.get("body"), SETUP_MARKER_V2, "setup PR", allow_trailer=True)
        base, head = pr.get("base"), pr.get("head")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        head_repo = head.get("repo") if isinstance(head, dict) else None
        if (pr.get("state") != "open" or pr.get("merged") is True or pr.get("draft") is not False
                or not isinstance(base, dict) or base.get("ref") != default_branch
                or not isinstance(head, dict) or head.get("ref") != expected.get("setup_branch")
                or not _repositories_match(base_repo, head_repo, github.repo, expected_id=repository_id)):
            return False
        if ({key: value for key, value in payload.items() if key not in policy_fields}
                != {key: value for key, value in expected.items() if key not in policy_fields}):
            return False
        actual_policy = {key: payload.get(key) for key in policy_fields}
        expected_policy = {key: expected.get(key) for key in policy_fields}
        if actual_policy == expected_policy:
            return False
        files = github.pull_request_files(_positive(pr.get("number"), "setup PR number"))
        return len(files) == 1 and files[0].get("filename") == ".agent/project.json"
    except (ConsumerActivationError, GitHubError):
        return False


def _activation_binding(issue_number: int, adc: VerifiedADC, predecessor: int | None,
                        base_sha40: str, branch_ref: str, setup_commit: str) -> dict[str, Any]:
    return {
        "activation_issue_number": issue_number,
        "adc_comment_id": adc.pointer.comment_id,
        "adc_sha256": adc.pointer.sha256,
        "base_sha40": base_sha40,
        "predecessor_record_id": predecessor,
        "schema": ACTIVATION_BINDING_SCHEMA,
        "setup_branch": branch_ref,
        "setup_commit_sha40": setup_commit,
    }


def _policy_read_access_blocked(error: BaseException | None = None,
                                blockers: tuple[str, ...] = ()) -> bool:
    access_codes = {
        "CURRENT_BRANCH_POLICY_READBACK_INCOMPLETE", "REPOSITORY_RULESET_INVENTORY_UNAVAILABLE",
        "MANAGED_RULESET_DETAIL_UNAVAILABLE", "DEFAULT_BRANCH_HEAD_UNVERIFIED",
        "OPEN_PULL_REQUEST_IMPACT_READBACK_UNAVAILABLE",
    }
    if blockers and set(blockers).issubset(access_codes):
        return True
    current = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "status_code", None) == 403:
            return True
        current = current.__cause__
    return False


def _setup_consumer_activation_v2_impl(
    root: Path, github: GitHub, *, default_branch: str, repository_id: int,
    owner_id: int, issue_number: int, adc: VerifiedADC, history: list[tuple[ConsumerActivationRecord, int]],
    profile_value: dict[str, Any], profile_content: bytes, configured_issue: int | None,
    required_checks: tuple[tuple[str, int], ...], policy_github: GitHub | None = None,
) -> dict[str, Any]:
    """Drive solo_owner Activation through a resumable plan/apply/readback lifecycle."""
    policy_reader = policy_github or github
    profile_sha256 = hashlib.sha256(profile_content).hexdigest()
    latest = history[-1][0] if history else None
    predecessor = history[-1][1] if history else None
    checkpoint_path = activation_checkpoint_path(root, issue_number)
    plan_path = activation_plan_path(root, issue_number)

    # An already-recorded V2 is reusable only after two equal fresh policy reads.
    if (latest is not None and latest.schema_version == 2 and configured_issue == issue_number
            and adc.pointer.state == "approved" and latest.adc_sha256 == adc.pointer.sha256
            and latest.activation_profile_sha256 == profile_sha256):
        try:
            first = read_verified_managed_policy(
                policy_reader, default_branch, required_checks, "solo_owner", issue_number,
            )
            second = read_verified_managed_policy(
                policy_reader, default_branch, required_checks, "solo_owner", issue_number,
            )
            if first == second and (latest.ruleset_id == first["ruleset_id"]
                                    and latest.branch_policy_sha256 == first["effective_policy_sha256"]
                                    and latest.ruleset_applied_record_id == first["applied_record_id"]):
                _, saved_path, checkpoint_sha = _checkpoint_v2(
                    root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
                    issue_number=issue_number, adc=adc,
                    predecessor_record_id=latest.predecessor_record_id,
                    default_branch=default_branch,
                    default_branch_sha40=github.branch(default_branch)["commit"]["sha"],
                    checks=required_checks, stage="ACTIVATION_RECORD", status="ACTIVE",
                    profile_sha256=profile_sha256, policy_status="VERIFIED",
                    ruleset_id=first["ruleset_id"], applied_record_id=first["applied_record_id"],
                    effective_policy_sha256=first["effective_policy_sha256"],
                )
                return {"status": "ACTIVE", "stage": "ACTIVATION_RECORD", "repository": github.repo,
                        "issue": issue_number, "activation_comment_id": history[-1][1],
                        "activated_at": latest.activated_at, "adc_comment_id": adc.pointer.comment_id,
                        "adc_sha256": adc.pointer.sha256, "checkpoint_path": str(saved_path),
                        "checkpoint_sha256": checkpoint_sha, "required_setting_inventory":
                        _policy_inventory("noop", verified=True), "reused": True}
        except (GitHubError, RulesetManagementError):
            # A current V2 record remains historical. The transaction continues into a fresh plan.
            pass

    base_sha40 = head_sha40(root)
    branch_ref = _setup_branch(issue_number, adc.pointer.sha256, predecessor, version=2,
                               base_sha40=base_sha40)
    _checkpoint_v2(
        root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
        issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
        default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
        stage="DISCOVER_AND_PREFLIGHT", status="RUNNING", profile_sha256=profile_sha256,
    )
    before = (root / ".agent" / "project.json").read_bytes()
    try:
        setup_commit, resumed_branch = _ensure_setup_branch(root, branch_ref, base_sha40, profile_content)
    except (GitHubError, GitError, OSError) as exc:
        _checkpoint_v2(
            root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
            issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
            default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
            stage="PREPARE_SETUP_BRANCH", status="BLOCKED", setup_branch=branch_ref,
            profile_sha256=profile_sha256,
        )
        raise ConsumerActivationError(f"Activation setup branch preparation failed closed: {exc}") from exc
    finally:
        if current_branch(root) == branch_ref:
            switch_branch(root, default_branch)
        if not worktree_clean(root) and not (root / ".agent" / "project.json").exists():
            _write_profile(root, before)
    if not worktree_clean(root) or current_branch(root) != default_branch:
        raise ConsumerActivationError("Activation setup did not restore the clean default-branch worktree")

    binding = _activation_binding(issue_number, adc, predecessor, base_sha40, branch_ref, setup_commit)
    _checkpoint_v2(
        root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
        issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
        default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
        stage="POLICY_PLAN", status="RUNNING", setup_branch=branch_ref,
        setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
    )
    try:
        plan = build_ruleset_plan(root, policy_reader, profile_ref=setup_commit, activation_binding=binding)
    except RulesetManagementError as exc:
        if policy_reader is github and _policy_read_access_blocked(exc):
            _, saved_path, checkpoint_sha = _checkpoint_v2(
                root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
                issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
                default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
                stage="POLICY_PLAN", status="ADMIN_AUTH_REQUIRED", setup_branch=branch_ref,
                setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
            )
            return {"status": "ADMIN_POLICY_UNAVAILABLE", "stage": "POLICY_PLAN",
                    "repository": github.repo, "issue": issue_number,
                    "setup_branch": branch_ref, "setup_commit_sha40": setup_commit,
                    "checkpoint_path": str(saved_path), "checkpoint_sha256": checkpoint_sha,
                    "required_setting_inventory": _policy_inventory(
                        "blocked", verified=False, blockers=(str(exc),)),
                    "reasons": [str(exc)],
                    "next_permitted_step": "Resume with consumer-activation-admin-plan using isolated browser device authentication; a runner-managed PTY must display the challenge."}
        raise
    if plan["blockers"]:
        blockers = tuple(plan["blockers"])
        if policy_reader is github and _policy_read_access_blocked(blockers=blockers):
            _, saved_path, checkpoint_sha = _checkpoint_v2(
                root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
                issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
                default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
                stage="POLICY_PLAN", status="ADMIN_AUTH_REQUIRED", setup_branch=branch_ref,
                setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
                plan_sha256=plan["plan_sha256"], policy_status=(
                    plan.get("policy_proof", {}).get("status")
                    if isinstance(plan.get("policy_proof"), dict) else None),
            )
            return {"status": "ADMIN_POLICY_UNAVAILABLE", "stage": "POLICY_PLAN",
                    "repository": github.repo, "issue": issue_number,
                    "plan_sha256": plan["plan_sha256"], "blockers": list(blockers),
                    "plan_path": str(plan_path), "checkpoint_path": str(saved_path),
                    "checkpoint_sha256": checkpoint_sha,
                    "required_setting_inventory": _policy_inventory(
                        "blocked", verified=False, blockers=blockers),
                    "next_permitted_step": "Resume with consumer-activation-admin-plan using isolated browser device authentication; a runner-managed PTY must display the challenge."}
        _, saved_path, checkpoint_sha = _checkpoint_v2(
            root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
            issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
            default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
            stage="POLICY_PLAN", status="BLOCKED", setup_branch=branch_ref,
            setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
            plan_sha256=plan["plan_sha256"], policy_status=(
                plan.get("policy_proof", {}).get("status") if isinstance(plan.get("policy_proof"), dict) else None),
        )
        return {"status": "BLOCKED", "stage": "POLICY_PLAN", "repository": github.repo,
                "issue": issue_number, "plan_sha256": plan["plan_sha256"],
                "blockers": list(blockers), "checkpoint_path": str(saved_path),
                "checkpoint_sha256": checkpoint_sha, "required_setting_inventory":
                _policy_inventory("blocked", verified=False, blockers=blockers), "reused": resumed_branch}

    write_ruleset_plan(plan_path, plan)
    if plan["diff"]["operation"] in {"create", "update"}:
        _, saved_path, checkpoint_sha = _checkpoint_v2(
            root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
            issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
            default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
            stage="AWAIT_OWNER_POLICY_DECISION", status="PENDING_APPROVAL", setup_branch=branch_ref,
            setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
            plan_sha256=plan["plan_sha256"], policy_status=(
                plan.get("policy_proof", {}).get("status") if isinstance(plan.get("policy_proof"), dict) else None),
        )
        return {"status": "PENDING_APPROVAL", "stage": "AWAIT_OWNER_POLICY_DECISION",
                "repository": github.repo, "issue": issue_number, "plan_sha256": plan["plan_sha256"],
                "operation": plan["diff"]["operation"].upper(), "plan_path": str(plan_path),
                "setup_branch": branch_ref, "setup_commit_sha40": setup_commit,
                "checkpoint_path": str(saved_path), "checkpoint_sha256": checkpoint_sha,
                "next_permitted_step": "RULESET_PLAN_APPLY exact owner decision, then trusted local consumer-activation-admin-apply",
                "required_setting_inventory": _policy_inventory(plan["diff"]["operation"], verified=False),
                "reused": resumed_branch}

    try:
        policy_evidence = read_verified_managed_policy(
            policy_reader, default_branch, required_checks, "solo_owner", issue_number,
        )
        repeated_policy = read_verified_managed_policy(
            policy_reader, default_branch, required_checks, "solo_owner", issue_number,
        )
    except (GitHubError, RulesetManagementError) as exc:
        _, saved_path, checkpoint_sha = _checkpoint_v2(
            root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
            issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
            default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
            stage="APPLY_AND_READBACK", status="BLOCKED", setup_branch=branch_ref,
            setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
            plan_sha256=plan["plan_sha256"], policy_status="BLOCKED",
        )
        return {"status": "BLOCKED", "stage": "APPLY_AND_READBACK", "repository": github.repo,
                "issue": issue_number, "plan_sha256": plan["plan_sha256"], "blockers": [str(exc)],
                "checkpoint_path": str(saved_path), "checkpoint_sha256": checkpoint_sha,
                "required_setting_inventory": _policy_inventory("blocked", verified=False,
                                                                   blockers=(str(exc),)),
                "reused": resumed_branch}
    if policy_evidence != repeated_policy:
        raise ConsumerActivationError("effective managed policy changed during Activation readback")

    expected = _setup_payload_v2(
        issue_number, adc, predecessor, profile_content, "solo_owner",
        policy_evidence["ruleset_id"], policy_evidence["effective_policy_sha256"],
        policy_evidence["applied_record_id"], required_checks, branch_ref,
    )
    candidates = github.pull_requests_for_refs(base_ref=default_branch, head_ref=branch_ref)
    if len(candidates) > 1:
        raise ConsumerActivationError("multiple setup PRs match the exact Activation branch")
    if candidates and candidates[0].get("state") == "open":
        if _stale_policy_bound_setup_pr(github, candidates[0], expected, default_branch, repository_id):
            generation_sha256 = hashlib.sha256(_canonical({
                "branch_policy_sha256": policy_evidence["effective_policy_sha256"],
                "ruleset_applied_record_id": policy_evidence["applied_record_id"],
                "ruleset_id": policy_evidence["ruleset_id"],
            })).hexdigest()
            branch_ref = _setup_branch(
                issue_number, adc.pointer.sha256, predecessor, version=2,
                base_sha40=base_sha40, generation_sha256=generation_sha256,
            )
            try:
                setup_commit, resumed_branch = _ensure_setup_branch(
                    root, branch_ref, base_sha40, profile_content,
                )
            except (GitHubError, GitError, OSError) as exc:
                _checkpoint_v2(
                    root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
                    issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
                    default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
                    stage="PREPARE_SETUP_BRANCH", status="BLOCKED", setup_branch=branch_ref,
                    setup_commit_sha40=None, profile_sha256=profile_sha256,
                )
                raise ConsumerActivationError(
                    f"new policy-bound Activation setup generation could not be prepared: {exc}"
                ) from exc
            finally:
                if current_branch(root) != default_branch:
                    switch_branch(root, default_branch)
            if not worktree_clean(root):
                raise ConsumerActivationError("new policy-bound Activation setup generation left a dirty worktree")
            binding = _activation_binding(
                issue_number, adc, predecessor, base_sha40, branch_ref, setup_commit,
            )
            _checkpoint_v2(
                root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
                issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
                default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
                stage="POLICY_PLAN", status="RUNNING", setup_branch=branch_ref,
                setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
            )
            plan = build_ruleset_plan(
                root, policy_reader, profile_ref=setup_commit, activation_binding=binding,
            )
            if plan["blockers"]:
                blockers = tuple(plan["blockers"])
                _, saved_path, checkpoint_sha = _checkpoint_v2(
                    root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
                    issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
                    default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
                    stage="POLICY_PLAN", status="BLOCKED", setup_branch=branch_ref,
                    setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
                    plan_sha256=plan["plan_sha256"], policy_status=(
                        plan.get("policy_proof", {}).get("status")
                        if isinstance(plan.get("policy_proof"), dict) else None),
                )
                return {"status": "BLOCKED", "stage": "POLICY_PLAN", "repository": github.repo,
                        "issue": issue_number, "plan_sha256": plan["plan_sha256"],
                        "blockers": list(blockers), "checkpoint_path": str(saved_path),
                        "checkpoint_sha256": checkpoint_sha,
                        "required_setting_inventory": _policy_inventory(
                            "blocked", verified=False, blockers=blockers),
                        "reused": resumed_branch}
            write_ruleset_plan(plan_path, plan)
            if plan["diff"]["operation"] in {"create", "update"}:
                _, saved_path, checkpoint_sha = _checkpoint_v2(
                    root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
                    issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
                    default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
                    stage="AWAIT_OWNER_POLICY_DECISION", status="PENDING_APPROVAL", setup_branch=branch_ref,
                    setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
                    plan_sha256=plan["plan_sha256"], policy_status=(
                        plan.get("policy_proof", {}).get("status")
                        if isinstance(plan.get("policy_proof"), dict) else None),
                )
                return {"status": "PENDING_APPROVAL", "stage": "AWAIT_OWNER_POLICY_DECISION",
                        "repository": github.repo, "issue": issue_number,
                        "plan_sha256": plan["plan_sha256"],
                        "operation": plan["diff"]["operation"].upper(), "plan_path": str(plan_path),
                        "setup_branch": branch_ref, "setup_commit_sha40": setup_commit,
                        "checkpoint_path": str(saved_path), "checkpoint_sha256": checkpoint_sha,
                        "next_permitted_step": "RULESET_PLAN_APPLY exact owner decision, then trusted local consumer-activation-admin-apply",
                        "required_setting_inventory": _policy_inventory(plan["diff"]["operation"], verified=False),
                        "reused": resumed_branch}
            try:
                policy_evidence = read_verified_managed_policy(
                    policy_reader, default_branch, required_checks, "solo_owner", issue_number,
                )
                repeated_policy = read_verified_managed_policy(
                    policy_reader, default_branch, required_checks, "solo_owner", issue_number,
                )
            except (GitHubError, RulesetManagementError) as exc:
                raise ConsumerActivationError(
                    f"new policy-bound Activation generation could not verify policy: {exc}"
                ) from exc
            if policy_evidence != repeated_policy:
                raise ConsumerActivationError("effective managed policy changed while creating a successor setup generation")
            expected = _setup_payload_v2(
                issue_number, adc, predecessor, profile_content, "solo_owner",
                policy_evidence["ruleset_id"], policy_evidence["effective_policy_sha256"],
                policy_evidence["applied_record_id"], required_checks, branch_ref,
            )
            candidates = github.pull_requests_for_refs(base_ref=default_branch, head_ref=branch_ref)
            if len(candidates) > 1:
                raise ConsumerActivationError("multiple setup PRs match the successor policy generation")
        if candidates and candidates[0].get("state") == "open":
            pr = _check_setup_pr(github, candidates[0], expected, default_branch, repository_id)
            _, saved_path, checkpoint_sha = _checkpoint_v2(
                root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
                issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
                default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
                stage="SETUP_PR_REVIEW_AND_MERGE", status="SETUP_PENDING", setup_branch=branch_ref,
                setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
                plan_sha256=plan["plan_sha256"], policy_status="VERIFIED",
                ruleset_id=policy_evidence["ruleset_id"], applied_record_id=policy_evidence["applied_record_id"],
                effective_policy_sha256=policy_evidence["effective_policy_sha256"], setup_pr_number=pr["number"],
            )
            return {"status": "SETUP_PENDING", "stage": "SETUP_PR_REVIEW_AND_MERGE",
                    "repository": github.repo, "issue": issue_number, "adc_comment_id": adc.pointer.comment_id,
                    "adc_sha256": adc.pointer.sha256, "pr": pr["number"], "pr_url": pr.get("html_url"),
                    "setup_branch": branch_ref, "setup_commit_sha40": setup_commit,
                    "plan_sha256": plan["plan_sha256"], "checkpoint_path": str(saved_path),
                    "checkpoint_sha256": checkpoint_sha,
                    "required_setting_inventory": _policy_inventory("noop", verified=True),
                    "next_permitted_step": "independent review, User Review, Final Delivery, and separate exact-HEAD PR_MERGE decision",
                    "reused": True}
    if candidates and candidates[0].get("merged") is True:
        record, record_id = verify_and_record_activation(github, candidates[0]["number"], root=root)
        return {"status": "ACTIVE", "stage": "ACTIVATION_RECORD", "repository": github.repo,
                "issue": issue_number, "activation_comment_id": record_id, "activated_at": record.activated_at,
                "pr": candidates[0]["number"], "checkpoint_path": str(checkpoint_path),
                "required_setting_inventory": _policy_inventory("noop", verified=True), "reused": True}
    if candidates:
        raise ConsumerActivationError("an ambiguous closed setup PR already exists for this ADC generation")

    if github.branch(branch_ref).get("commit", {}).get("sha") != setup_commit:
        raise ConsumerActivationError("setup branch changed before policy-bound setup PR creation")
    body = _body(_setup_marker(expected), expected) + "\n\nMerge this PR to approve the Activation ADC and authorize P-ASES for new Issues."
    try:
        created = github.create_pull_request(
            title="P-ASES: prepare consumer Activation", body=body,
            head_ref=branch_ref, base_ref=default_branch,
        )
        pr = github.pull_request(created["number"])
    except GitHubError as exc:
        recovered = github.pull_requests_for_refs(base_ref=default_branch, head_ref=branch_ref)
        if len(recovered) != 1:
            raise ConsumerActivationError("setup PR creation failed and exact recovery was ambiguous") from exc
        pr = recovered[0]
    pr = _check_setup_pr(github, pr, expected, default_branch, repository_id)
    if pr.get("head", {}).get("sha") != setup_commit:
        raise ConsumerActivationError("setup PR HEAD differs from the policy-bound profile commit")
    _, saved_path, checkpoint_sha = _checkpoint_v2(
        root, repository=github.repo, repository_id=repository_id, owner_id=owner_id,
        issue_number=issue_number, adc=adc, predecessor_record_id=predecessor,
        default_branch=default_branch, default_branch_sha40=base_sha40, checks=required_checks,
        stage="SETUP_PR_REVIEW_AND_MERGE", status="SETUP_PENDING", setup_branch=branch_ref,
        setup_commit_sha40=setup_commit, profile_sha256=profile_sha256,
        plan_sha256=plan["plan_sha256"], policy_status="VERIFIED",
        ruleset_id=policy_evidence["ruleset_id"], applied_record_id=policy_evidence["applied_record_id"],
        effective_policy_sha256=policy_evidence["effective_policy_sha256"], setup_pr_number=pr["number"],
    )
    return {"status": "SETUP_PENDING", "stage": "SETUP_PR_REVIEW_AND_MERGE",
            "repository": github.repo, "issue": issue_number, "adc_comment_id": adc.pointer.comment_id,
            "adc_sha256": adc.pointer.sha256, "pr": pr["number"], "pr_url": pr.get("html_url"),
            "setup_branch": branch_ref, "setup_commit_sha40": setup_commit,
            "plan_sha256": plan["plan_sha256"], "checkpoint_path": str(checkpoint_path),
            "checkpoint_sha256": checkpoint_sha, "required_checks_configured": True,
            "required_setting_inventory": _policy_inventory("noop", verified=True),
            "next_permitted_step": "independent review, User Review, Final Delivery, and separate exact-HEAD PR_MERGE decision",
            "reused": resumed_branch}


def _setup_consumer_activation_v2(
    root: Path, github: GitHub, *, default_branch: str, repository_id: int,
    owner_id: int, issue_number: int, adc: VerifiedADC, history: list[tuple[ConsumerActivationRecord, int]],
    profile_value: dict[str, Any], profile_content: bytes, configured_issue: int | None,
    required_checks: tuple[tuple[str, int], ...], policy_github: GitHub | None = None,
) -> dict[str, Any]:
    """Persist unexpected V2 transaction failures against the exact current checkpoint."""
    try:
        return _setup_consumer_activation_v2_impl(
            root, github, default_branch=default_branch, repository_id=repository_id,
            owner_id=owner_id, issue_number=issue_number, adc=adc, history=history,
            profile_value=profile_value, profile_content=profile_content,
            configured_issue=configured_issue, required_checks=required_checks,
            policy_github=policy_github,
        )
    except Exception as exc:
        path = activation_checkpoint_path(root, issue_number)
        if path.is_file():
            try:
                checkpoint = read_activation_checkpoint(path)
                predecessor = history[-1][1] if history else None
                if (checkpoint.repository.casefold() == github.repo.casefold()
                        and checkpoint.repository_id == repository_id and checkpoint.owner_id == owner_id
                        and checkpoint.activation_issue_number == issue_number
                        and checkpoint.adc_comment_id == adc.pointer.comment_id
                        and checkpoint.adc_sha256 == adc.pointer.sha256
                        and checkpoint.predecessor_record_id == predecessor):
                    blocked = replace(checkpoint, status="BLOCKED")
                    digest = write_activation_checkpoint(path, blocked, root=root)
                    reason = str(exc) or exc.__class__.__name__
                    return {
                        "status": "BLOCKED", "stage": blocked.stage, "repository": github.repo,
                        "issue": issue_number, "plan_sha256": blocked.plan_sha256,
                        "setup_branch": blocked.setup_branch,
                        "setup_commit_sha40": blocked.setup_commit_sha40,
                        "checkpoint_path": str(path), "checkpoint_sha256": digest,
                        "blockers": [reason],
                        "required_setting_inventory": _policy_inventory(
                            "blocked", verified=False, blockers=(reason,)),
                        "next_permitted_step": "Resolve the blocker and rerun consumer-activation-setup; stale plan subjects must be rebuilt.",
                    }
            except (ConsumerActivationError, OSError):
                pass
        raise


def setup_consumer_activation(root: Path, github: GitHub, *, policy_github: GitHub | None = None) -> dict[str, Any]:
    """Prepare a marked Activation Issue, proposed ADC, project.json setup PR; never activate pre-merge."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ConsumerActivationError("Activation setup requires an existing non-symlink repository directory")
    root = root.resolve()
    if not worktree_clean(root):
        raise ConsumerActivationError("Activation setup requires a clean repository worktree")
    try:
        local_repository = discover_repository(root)
    except GitError as exc:
        raise ConsumerActivationError(f"could not resolve the active repository from this workspace: {exc}") from exc
    if local_repository.casefold() != github.repo.casefold():
        raise ConsumerActivationError("GitHub repository does not match the active workspace origin")
    if policy_github is not None and policy_github.repo.casefold() != github.repo.casefold():
        raise ConsumerActivationError("Activation policy reader targets a different repository")
    profile_path = root / ".agent" / "project.json"
    configured = None
    review_mode = "external_reviewer"
    if profile_path.exists() or profile_path.is_symlink():
        if path_has_symlink(profile_path, root=root):
            raise ConsumerActivationError("project.json path traverses a symbolic link")
        try:
            profile = load_profile(root)
            configured = profile.activation_issue_number
            review_mode = profile.final_delivery_review_mode
        except ProfileError as exc:
            raise ConsumerActivationError(f"existing project.json is invalid: {exc}") from exc
    try:
        metadata = github.repository_metadata()
        default_branch = metadata.get("default_branch")
        repository_id = _positive(metadata.get("id"), "repository ID")
        owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
        owner_id = _positive(owner.get("id"), "repository owner ID") if owner else None
        full_name = metadata.get("full_name")
        if not isinstance(default_branch, str) or current_branch(root) != default_branch:
            raise ConsumerActivationError("Activation setup must start on the repository default branch")
        head = head_sha40(root)
        if github.branch(default_branch).get("commit", {}).get("sha") != head:
            raise ConsumerActivationError("local default branch must match GitHub default-branch HEAD")
        if review_mode == "solo_owner":
            if (not isinstance(full_name, str) or full_name.casefold() != github.repo.casefold()
                    or not owner or owner.get("type") != "User" or owner_id is None):
                raise ConsumerActivationError("solo_owner requires a stable repository owner identity")
            if github.repo.casefold() == "puchinya/ai-agent-workflow" and (
                    repository_id != 1401910271 or owner_id != 3744776
                    or str(owner.get("login", "")).casefold() != "puchinya"):
                raise ConsumerActivationError("fresh repository identity differs from the configured #63 owner")
        user = github.authenticated_user()
        _identity(user, "authenticated user")
        issue = _resolve_issue(github, configured)
        if issue is None:
            created = github.create_issue(
                "P-ASES Consumer Activation",
                f"{ISSUE_MARKER}\n\nThis Issue stores the approved Activation ADC and append-only Activation history for `{github.repo}`.\n",
            )
            created_number = _positive(created.get("number"), "created Activation Issue number")
            issue = _resolve_issue(github, created_number)
            if issue is None or issue.get("number") != created_number:
                raise ConsumerActivationError("created Activation Issue did not pass exact readback")
        issue_number = _positive(issue.get("number"), "Activation Issue number")
        adc = _ensure_adc(github, issue_number)
        history = read_consumer_activation_history(github, github.repo, issue_number)
        value, content = _profile_for_setup(root, github.repo, issue_number)
        version = 2 if review_mode == "solo_owner" else 1
        if version == 2:
            configured_profile = load_profile(root)
            configured_checks = configured_profile.required_checks
            missing = []
            if not configured_checks:
                missing.append(".agent/project.json:branch.required_checks")
            if any(app_id is None for _name, app_id in configured_checks):
                missing.append(".agent/project.json:branch.required_checks[].trusted_app_id")
            checks = tuple(sorted((name, app_id) for name, app_id in configured_checks if app_id is not None))
            if missing:
                return {"status": "INPUT_REQUIRED", "stage": "DISCOVER_AND_PREFLIGHT",
                        "repository": github.repo, "issue": issue_number,
                        "required_setting_inventory": activation_setting_inventory(
                            "solo_owner", required_checks_verified=False, blocked=True),
                        "input_required": missing,
                        "reasons": ["Use trusted committed Required Check names and App IDs; do not guess them."]}
            if owner_id is None:
                raise ConsumerActivationError("solo_owner repository owner stable ID is unavailable")
            return _setup_consumer_activation_v2(
                root, github, default_branch=default_branch, repository_id=repository_id,
                owner_id=owner_id, issue_number=issue_number, adc=adc, history=history,
                profile_value=value, profile_content=content,
                configured_issue=configured, required_checks=checks, policy_github=policy_github,
            )
        if profile_path.is_file():
            try:
                configured_profile = load_profile(root)
            except ProfileError as exc:
                raise ConsumerActivationError(f"existing project.json is invalid: {exc}") from exc
            configured_checks = configured_profile.required_checks
        else:
            configured_checks = ()
        missing = []
        if not configured_checks:
            missing.append(".agent/project.json:branch.required_checks")
        if any(app_id is None for _name, app_id in configured_checks):
            missing.append(".agent/project.json:branch.required_checks[].trusted_app_id")
        checks = tuple(sorted((name, app_id) for name, app_id in configured_checks if app_id is not None))
        if missing:
            return {"status": "INPUT_REQUIRED", "stage": "DISCOVER_AND_PREFLIGHT",
                    "repository": github.repo, "issue": issue_number,
                    "required_setting_inventory": activation_setting_inventory(
                        "external_reviewer", required_checks_verified=False),
                    "input_required": missing,
                    "reasons": ["Use trusted committed Required Check names and App IDs; do not guess."]}
        if (history and configured == issue_number and adc.pointer.state == "approved"
                and history[-1][0].adc_sha256 == adc.pointer.sha256
                and history[-1][0].schema_version == version):
            active, record_id = history[-1]
            recorded_checks = tuple(sorted((item.name, item.app_id) for item in active.required_check_runs))
            if recorded_checks != checks:
                return {"status": "BLOCKED", "stage": "DISCOVER_AND_PREFLIGHT",
                        "repository": github.repo, "issue": issue_number,
                        "activation_comment_id": record_id,
                        "required_setting_inventory": activation_setting_inventory(
                            review_mode, required_checks_verified=False, blocked=True),
                        "reasons": ["current trusted Required Checks differ from the recorded Activation"]}
            return {"status": "ACTIVE", "repository": github.repo, "issue": issue_number,
                    "activation_comment_id": record_id, "activated_at": active.activated_at,
                    "adc_comment_id": adc.pointer.comment_id, "adc_sha256": adc.pointer.sha256,
                    "required_setting_inventory": activation_setting_inventory(
                        review_mode, required_checks_verified=True),
                    "reused": True}
        predecessor = history[-1][1] if history else None
        branch_ref = _setup_branch(issue_number, adc.pointer.sha256, predecessor, version=1)
        expected = _setup_payload(issue_number, adc, predecessor)
        candidates = github.pull_requests_for_refs(base_ref=default_branch, head_ref=branch_ref)
        if len(candidates) > 1:
            raise ConsumerActivationError("multiple setup PRs match the exact Activation branch")
        if candidates and candidates[0].get("state") == "open":
            pr = _check_setup_pr(github, candidates[0], expected, default_branch, repository_id)
            return {"status": "SETUP_PENDING", "repository": github.repo, "issue": issue_number,
                    "adc_comment_id": adc.pointer.comment_id, "adc_sha256": adc.pointer.sha256,
                    "pr": pr["number"], "pr_url": pr.get("html_url"),
                    "required_setting_inventory": activation_setting_inventory(
                        review_mode, required_checks_verified=True),
                    "reused": True}
        if candidates and candidates[0].get("merged") is True:
            record, record_id = verify_and_record_activation(github, candidates[0]["number"])
            return {"status": "ACTIVE", "repository": github.repo, "issue": issue_number,
                    "activation_comment_id": record_id, "activated_at": record.activated_at,
                    "pr": candidates[0]["number"],
                    "required_setting_inventory": activation_setting_inventory(
                        review_mode, required_checks_verified=True,
                        policy_verified=record.schema_version == 2),
                    "reused": True}
        if candidates:
            raise ConsumerActivationError("an ambiguous closed setup PR already exists for this ADC generation")
        before = profile_path.read_bytes() if profile_path.exists() else None
        try:
            commit_sha, resumed_branch = _ensure_setup_branch(root, branch_ref, head, content)
            body = _body(_setup_marker(expected), expected) + "\n\nMerge this PR to approve the Activation ADC and authorize P-ASES for new Issues."
            try:
                created_pr = github.create_pull_request(
                    title="P-ASES: prepare consumer Activation", body=body,
                    head_ref=branch_ref, base_ref=default_branch,
                )
                pr = github.pull_request(created_pr["number"])
            except GitHubError as exc:
                recovered = github.pull_requests_for_refs(base_ref=default_branch, head_ref=branch_ref)
                if len(recovered) != 1:
                    raise ConsumerActivationError("setup PR creation failed and exact recovery was ambiguous") from exc
                pr = recovered[0]
            pr = _check_setup_pr(github, pr, expected, default_branch, repository_id)
            if pr.get("head", {}).get("sha") != commit_sha:
                raise ConsumerActivationError("setup PR HEAD differs from the pushed project.json commit")
        except Exception:
            if current_branch(root) == branch_ref:
                if not worktree_clean(root):
                    if before is None:
                        profile_path.unlink(missing_ok=True)
                    else:
                        _write_profile(root, before)
                if worktree_clean(root):
                    switch_branch(root, default_branch)
            raise
        switch_branch(root, default_branch)
        return {"status": "SETUP_PENDING", "repository": github.repo, "issue": issue_number,
                "adc_comment_id": adc.pointer.comment_id, "adc_sha256": adc.pointer.sha256,
                    "pr": pr["number"], "pr_url": pr.get("html_url"), "setup_branch": branch_ref,
                "required_checks_configured": bool(value.get("branch", {}).get("required_checks")),
                "required_setting_inventory": activation_setting_inventory(
                    review_mode, required_checks_verified=True),
                "reasons": ([] if value.get("branch", {}).get("required_checks") else
                            ["Add trusted branch.required_checks in project.json before merging this setup PR."]),
                "reused": resumed_branch}
    except (GitHubError, GitError, OSError, ADCError, RulesetManagementError) as exc:
        raise ConsumerActivationError(f"Activation setup failed closed: {exc}") from exc


def _record_checkpoint_active(root: Path | None, github: GitHub, record: ConsumerActivationRecord,
                             pr_number: int) -> None:
    if root is None or record.schema_version != 2:
        return
    path = activation_checkpoint_path(root, record.activation_issue_number)
    if not path.exists():
        return
    checkpoint = read_activation_checkpoint(path)
    if (checkpoint.repository.casefold() != github.repo.casefold()
            or checkpoint.activation_issue_number != record.activation_issue_number
            or checkpoint.setup_pr_number not in {None, pr_number}
            or checkpoint.adc_sha256 != record.proposed_adc_sha256
            or checkpoint.plan_sha256 is None):
        raise ConsumerActivationError("Activation checkpoint does not match the verified setup PR record")
    active = replace(checkpoint, stage="ACTIVATION_RECORD", status="ACTIVE")
    write_activation_checkpoint(path, active, root=root)


def verify_and_record_activation(github: GitHub, pr_number: int, *, root: Path | None = None
                                 ) -> tuple[ConsumerActivationRecord, int]:
    """Verify an admin-merged setup PR, approve its exact ADC generation, and append history."""
    try:
        pr = github.pull_request(pr_number)
        setup_marker = (SETUP_MARKER_V2 if isinstance(pr.get("body"), str)
                        and pr["body"].startswith(SETUP_MARKER_V2) else SETUP_MARKER)
        setup = _decode(pr.get("body"), setup_marker, "setup PR", allow_trailer=True)
        schema_version = 2 if setup_marker == SETUP_MARKER_V2 else 1
        issue_number = _positive(setup.get("activation_issue_number"), "Activation Issue number")
        if (not isinstance(setup.get("adc_sha256"), str) or not SHA256.fullmatch(setup["adc_sha256"])
                or not isinstance(setup.get("activation_profile_sha256"), str)
                or not SHA256.fullmatch(setup["activation_profile_sha256"])):
            raise ConsumerActivationError("setup PR ADC or Activation profile digest is invalid")
        history = read_consumer_activation_history(github, github.repo, issue_number,
                                                   allow_pending_approval=True)
        for existing, existing_id in history:
            if existing.setup_pr_number == pr_number:
                if (existing.proposed_adc_comment_id != setup["adc_comment_id"]
                        or existing.proposed_adc_sha256 != setup["adc_sha256"]
                        or existing.merge_commit_sha40 != pr.get("merge_commit_sha")):
                    raise ConsumerActivationError("setup PR already has a conflicting Activation record")
                _record_checkpoint_active(root, github, existing, pr_number)
                return existing, existing_id
        checked_pr, _issue, proposed, check_evidence = _validate_merged_setup(
            github, pr_number, setup, require_current_adc=True, require_current_admin=True,
        )
        merger = checked_pr["merged_by"]
        merger_id, merger_login, _kind = _identity(merger, "setup PR merger")
        if _identity(github.authenticated_user(), "authenticated verifier") != (merger_id, merger_login, "User"):
            raise ConsumerActivationError("post-merge verifier must be the authenticated human who merged the setup PR")
        predecessor = history[-1][1] if history else None
        if setup.get("predecessor_record_id") != predecessor:
            raise ConsumerActivationError("setup PR predecessor does not match the latest Activation history")
        try:
            latest_adc = verify_adc(github, issue_number)
            if latest_adc.pointer.state == "approved":
                approved = latest_adc
            elif (latest_adc.pointer == proposed.pointer and proposed.pointer.state == "draft"):
                pointer = publish_adc(github, issue_number, proposed.contract.content,
                                      state="approved", explicitly_approved=True, supersede=True,
                                      expected_current=proposed.pointer)
                approved = verify_adc(github, issue_number)
                if approved.pointer != pointer:
                    raise ConsumerActivationError("approved ADC pointer did not pass exact current readback")
            else:
                raise ConsumerActivationError("Activation ADC changed before its setup PR was verified")
        except ADCError as exc:
            raise ConsumerActivationError(f"could not approve the exact merged Activation ADC: {exc}") from exc
        if (approved.pointer.sha256 != proposed.pointer.sha256
                or approved.contract.content != proposed.contract.content
                or approved.pointer.state != "approved"):
            raise ConsumerActivationError("approved Activation ADC differs from the setup PR proposal")
        fields = {
            "activation_issue_number": issue_number,
            "activation_profile_sha256": setup["activation_profile_sha256"],
            "adc_comment_id": approved.pointer.comment_id, "adc_sha256": approved.pointer.sha256,
            "merge_commit_sha40": checked_pr["merge_commit_sha"], "merged_at": checked_pr["merged_at"],
            "merger_id": merger_id, "merger_login": merger_login, "merger_type": "User",
            "predecessor_record_id": predecessor,
            "proposed_adc_comment_id": proposed.pointer.comment_id,
            "proposed_adc_sha256": proposed.pointer.sha256,
            "proposed_adc_state": proposed.pointer.state,
            "required_check_runs": [item.payload() for item in check_evidence],
            "repository": github.repo,
            "setup_pr_id": _positive(checked_pr.get("id"), "setup PR ID"),
            "setup_pr_number": pr_number,
            "schema": f"PASES_CONSUMER_ACTIVATION_V{schema_version}",
        }
        if schema_version == 2:
            fields.update({
                "branch_policy_sha256": setup["branch_policy_sha256"],
                "review_mode": setup["review_mode"],
                "ruleset_id": setup["ruleset_id"],
                "ruleset_applied_record_id": setup["ruleset_applied_record_id"],
                "setup_branch": setup["setup_branch"],
            })
        approval_payload = _approval_payload(fields, predecessor=predecessor)
        comments = github.issue_comments(issue_number)
        approved_ids = {record.approval_comment_id for record, _ in history}
        orphans = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                   and row["body"].startswith((APPROVAL_MARKER, APPROVAL_MARKER_V2))
                   and row.get("id") not in approved_ids]
        if len(orphans) > 1:
            raise ConsumerActivationError("multiple unpaired Activation approvals exist")
        if orphans:
            approval_id = _positive(orphans[0].get("id"), "pending Activation approval Comment ID")
            orphan_marker = (APPROVAL_MARKER_V2 if orphans[0]["body"].startswith(APPROVAL_MARKER_V2)
                             else APPROVAL_MARKER)
            readback = _read_comment(github, issue_number, approval_id, orphan_marker,
                                     "Activation approval", unique_marker=False)
            if (_decode(readback.get("body"), orphan_marker, "Activation approval") != approval_payload
                    or _identity(readback.get("user"), "Activation approval author")
                    != (merger_id, merger_login.casefold(), "User")):
                raise ConsumerActivationError("pending Activation approval does not match this exact merged PR")
        else:
            approval_marker = APPROVAL_MARKER_V2 if schema_version == 2 else APPROVAL_MARKER
            approval_id, _ = _publish_comment(github, issue_number, approval_marker, approval_payload,
                                              "Activation approval", allow_history=True)
        record = ConsumerActivationRecord(
            repository=github.repo, activation_issue_number=issue_number,
            proposed_adc_comment_id=proposed.pointer.comment_id,
            proposed_adc_sha256=proposed.pointer.sha256, proposed_adc_state=proposed.pointer.state,
            adc_comment_id=approved.pointer.comment_id, adc_sha256=approved.pointer.sha256,
            activation_profile_sha256=setup["activation_profile_sha256"],
            setup_pr_number=pr_number, setup_pr_id=fields["setup_pr_id"],
            merge_commit_sha40=checked_pr["merge_commit_sha"], merged_at=checked_pr["merged_at"],
            merger_id=merger_id, merger_login=merger_login, merger_type="User",
            approval_comment_id=approval_id, predecessor_record_id=predecessor,
            required_check_runs=check_evidence,
            schema_version=schema_version,
            review_mode=setup.get("review_mode") if schema_version == 2 else None,
            ruleset_id=setup.get("ruleset_id") if schema_version == 2 else None,
            branch_policy_sha256=setup.get("branch_policy_sha256") if schema_version == 2 else None,
            ruleset_applied_record_id=(setup.get("ruleset_applied_record_id")
                                       if schema_version == 2 else None),
            setup_branch=setup.get("setup_branch") if schema_version == 2 else None,
        ).validate()
        record_marker = RECORD_MARKER_V2 if schema_version == 2 else RECORD_MARKER
        if schema_version == 2:
            # The earlier read is part of merged-PR validation. Take a second
            # complete read immediately before publishing the effective record.
            # This catches policy changes during ADC/approval processing.
            try:
                latest_policy = read_verified_managed_policy(
                    github, checked_pr["base"]["ref"],
                    tuple((item.name, item.app_id) for item in check_evidence),
                    setup["review_mode"], issue_number,
                )
            except RulesetManagementError as exc:
                raise ConsumerActivationError(f"V2 policy changed or became unreadable before recording: {exc}") from exc
            if (latest_policy["ruleset_id"] != setup["ruleset_id"]
                    or latest_policy["effective_policy_sha256"] != setup["branch_policy_sha256"]
                    or latest_policy["applied_record_id"] != setup["ruleset_applied_record_id"]):
                raise ConsumerActivationError("V2 policy changed before the Activation record was published")
        record_id, _ = _publish_comment(github, issue_number, record_marker, record.payload(),
                                        "Activation record", allow_history=True)
        result = read_consumer_activation_record(github, github.repo, issue_number)
        if result is None or result[1] != record_id or result[0].payload() != record.payload():
            raise ConsumerActivationError("Activation record did not pass complete readback")
        _record_checkpoint_active(root, github, result[0], pr_number)
        return result[0], record_id
    except GitHubError as exc:
        raise ConsumerActivationError(f"post-merge Activation verification failed: {exc}") from exc


def read_consumer_activation_history(
    github: GitHub, repository: str, issue_number: int, *, allow_pending_approval: bool = False,
    through_record_id: int | None = None,
) -> list[tuple[ConsumerActivationRecord, int]]:
    try:
        if repository.casefold() != github.repo.casefold():
            raise ConsumerActivationError("Activation repository does not match the GitHub client")
        issue = github.issue(issue_number)
        issue_repository_url = issue.get("repository_url")
        if (issue.get("number") != issue_number or issue.get("pull_request") is not None
                or not _has_issue_marker(issue.get("body"))
                or not isinstance(issue_repository_url, str)
                or issue_repository_url.casefold() != f"https://api.github.com/repos/{repository}".casefold()):
            raise ConsumerActivationError("Activation Issue does not match its repository marker")
        if through_record_id is not None:
            through_record_id = _positive(through_record_id, "Activation prefix record Comment ID")
        comments = github.issue_comments(issue_number)
        if not isinstance(comments, list) or any(not isinstance(row, dict) for row in comments):
            raise ConsumerActivationError("Activation Issue comment list is malformed")

        def comments_through_selected_record(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if through_record_id is None:
                return rows
            target_records = [row for row in rows if isinstance(row.get("body"), str)
                              and row["body"].startswith((RECORD_MARKER, RECORD_MARKER_V2))
                              and row.get("id") == through_record_id]
            target_positions = [index for index, row in enumerate(rows) if row.get("id") == through_record_id]
            if len(target_records) != 1 or len(target_positions) != 1:
                raise ConsumerActivationError("selected Activation prefix target is missing or duplicated")
            return rows[:target_positions[0] + 1]

        prefix_comments = comments_through_selected_record(comments)
        all_records = [row for row in prefix_comments if isinstance(row.get("body"), str)
                       and row["body"].startswith((RECORD_MARKER, RECORD_MARKER_V2))]
        all_approvals = [row for row in prefix_comments if isinstance(row.get("body"), str)
                         and row["body"].startswith((APPROVAL_MARKER, APPROVAL_MARKER_V2))]
        if (any(type(row.get("id")) is not int or row["id"] < 1
                or through_record_id is not None and row["id"] > through_record_id
                for row in all_records + all_approvals)):
            raise ConsumerActivationError("Activation history contains an invalid GitHub comment ID")
        records, approvals = all_records, all_approvals
        if not records:
            if approvals and not allow_pending_approval:
                raise ConsumerActivationError("Activation history contains an orphan approval")
            if len(approvals) > (1 if allow_pending_approval else 0):
                raise ConsumerActivationError("Activation history contains duplicate orphan approvals")
            return []
        records.sort(key=lambda row: row.get("id", 0))
        record_ids = [row.get("id") for row in records]
        approval_ids = [row.get("id") for row in approvals]
        if (any(type(value) is not int or value < 1 for value in record_ids + approval_ids)
                or len(record_ids) != len(set(record_ids)) or len(approval_ids) != len(set(approval_ids))
                or len(approvals) not in ({len(records), len(records) + 1}
                                          if allow_pending_approval else {len(records)})):
            raise ConsumerActivationError("Activation history has missing or duplicate approval/record IDs")
        def marker_for(row: dict[str, Any], v1: str, v2: str) -> str:
            body = row.get("body")
            if isinstance(body, str) and body.startswith(v2):
                return v2
            if isinstance(body, str) and body.startswith(v1):
                return v1
            raise ConsumerActivationError("Activation history comment has an unknown schema marker")

        def marker_snapshot(rows: list[dict[str, Any]], v1: str, v2: str, label: str) -> list[tuple[Any, ...]]:
            return sorted((_fingerprint(row, issue_number, row["id"], marker_for(row, v1, v2), label)
                           for row in rows), key=lambda row: row[0])

        initial_markers = {
            "records": marker_snapshot(records, RECORD_MARKER, RECORD_MARKER_V2, "Activation record"),
            "approvals": marker_snapshot(approvals, APPROVAL_MARKER, APPROVAL_MARKER_V2, "Activation approval"),
        }
        result: list[tuple[ConsumerActivationRecord, int]] = []
        used_approvals: set[int] = set()
        used_prs: set[int] = set()
        predecessor: int | None = None
        predecessor_merge: datetime | None = None
        for listed_record in records:
            record_id = _positive(listed_record["id"], "Activation record Comment ID")
            record_marker = marker_for(listed_record, RECORD_MARKER, RECORD_MARKER_V2)
            record = ConsumerActivationRecord.from_payload(
                _decode(listed_record.get("body"), record_marker, "Activation record"))
            if (record.activation_issue_number != issue_number or record.repository.casefold() != repository.casefold()
                    or record.predecessor_record_id != predecessor or record.setup_pr_number in used_prs
                    or (record.schema_version == 1
                        and record.activation_profile_sha256 != _profile_digest(issue_number))):
                raise ConsumerActivationError("Activation history is misordered or belongs to another subject")
            used_prs.add(record.setup_pr_number)
            record_row = _read_comment(github, issue_number, record_id, record_marker,
                                       "Activation record", unique_marker=False)
            if record_row.get("body") != listed_record.get("body"):
                raise ConsumerActivationError("Activation record changed after its initial list read")
            record = replace(record, record_created_at=record_row.get("created_at")).validate()
            merge_time = _timestamp(record.merged_at, "setup PR merge time")
            if predecessor_merge is not None and merge_time < predecessor_merge:
                raise ConsumerActivationError("successor Activation merge time predates its predecessor")
            predecessor_merge = merge_time
            approval_row = next((row for row in approvals if row.get("id") == record.approval_comment_id
                                 and row["body"].startswith(
                                     APPROVAL_MARKER_V2 if record.schema_version == 2 else APPROVAL_MARKER)), None)
            if approval_row is None or record.approval_comment_id in used_approvals:
                raise ConsumerActivationError("Activation record has a missing or reused approval comment")
            used_approvals.add(record.approval_comment_id)
            approval_marker = APPROVAL_MARKER_V2 if record.schema_version == 2 else APPROVAL_MARKER
            approval = _read_comment(github, issue_number, record.approval_comment_id,
                                     approval_marker, "Activation approval", unique_marker=False)
            expected_approval = _approval_payload(record.payload(), predecessor=record.predecessor_record_id)
            if (_decode(approval.get("body"), approval_marker, "Activation approval") != expected_approval
                    or _identity(approval.get("user"), "Activation approval author")
                    != (record.merger_id, record.merger_login.casefold(), record.merger_type)
                    or _identity(record_row.get("user"), "Activation record author")
                    != (record.merger_id, record.merger_login.casefold(), record.merger_type)):
                raise ConsumerActivationError("Activation approval/record author or payload does not match")
            approval_time = _timestamp(approval.get("created_at"), "Activation approval creation time")
            record_time = _timestamp(record_row.get("created_at"), "Activation record creation time")
            if merge_time > approval_time or approval_time > record_time:
                raise ConsumerActivationError("Activation approval and record do not follow the verified PR merge")
            expected_setup = {
                "activation_issue_number": record.activation_issue_number,
                "activation_profile_sha256": record.activation_profile_sha256,
                "adc_comment_id": record.proposed_adc_comment_id,
                "adc_sha256": record.proposed_adc_sha256,
                "adc_state": record.proposed_adc_state,
                "predecessor_record_id": record.predecessor_record_id,
                "schema": f"PASES_CONSUMER_ACTIVATION_SETUP_V{record.schema_version}",
            }
            if record.schema_version == 2:
                expected_setup.update({
                    "branch_policy_sha256": record.branch_policy_sha256,
                    "required_checks": [{"context": item.name, "integration_id": item.app_id}
                                         for item in record.required_check_runs],
                    "review_mode": record.review_mode,
                    "ruleset_id": record.ruleset_id,
                    "ruleset_applied_record_id": record.ruleset_applied_record_id,
                    "setup_branch": record.setup_branch,
                })
            pr, _issue, proposed, _pinned_checks = _validate_merged_setup(
                github, record.setup_pr_number, expected_setup,
                require_current_adc=False, require_current_admin=False,
                require_current_policy=False,
                expected_check_runs=record.required_check_runs,
            )
            if record.schema_version == 2:
                try:
                    verify_applied_policy_record(
                        github, issue_number, record_id, record.ruleset_applied_record_id,
                        record.ruleset_id, record.branch_policy_sha256,
                    )
                except RulesetManagementError as exc:
                    raise ConsumerActivationError(f"historical V2 policy evidence is invalid: {exc}") from exc
            approved = verify_adc_generation(github, issue_number, record.adc_comment_id,
                                             record.adc_sha256, state="approved")
            if (proposed.contract.content != approved.contract.content
                    or pr.get("id") != record.setup_pr_id
                    or pr.get("merge_commit_sha") != record.merge_commit_sha40
                    or pr.get("merged_at") != record.merged_at
                    or _identity(pr.get("merged_by"), "setup PR merger")
                    != (record.merger_id, record.merger_login.casefold(), record.merger_type)):
                raise ConsumerActivationError("Activation record no longer matches its merged setup PR and ADC")
            final = _read_comment(github, issue_number, record_id, record_marker,
                                  "Activation record", unique_marker=False)
            if (final.get("body") != record_row.get("body")
                    or final.get("created_at") != record_row.get("created_at")
                    or _identity(final.get("user"), "Activation record author")
                    != (record.merger_id, record.merger_login.casefold(), record.merger_type)):
                raise ConsumerActivationError("Activation record changed during PR/evidence validation")
            result.append((record, record_id))
            predecessor = record_id
        orphan_ids = set(approval_ids) - used_approvals
        if orphan_ids:
            if not allow_pending_approval or len(orphan_ids) != 1:
                raise ConsumerActivationError("Activation history contains an orphan approval")
            orphan_row = next(row for row in approvals if row.get("id") in orphan_ids)
            orphan_id = _positive(orphan_row.get("id"), "pending Activation approval Comment ID")
            orphan_marker = marker_for(orphan_row, APPROVAL_MARKER, APPROVAL_MARKER_V2)
            readback = _read_comment(github, issue_number, orphan_id, orphan_marker,
                                     "Activation approval", unique_marker=False)
            payload = _decode(readback.get("body"), orphan_marker, "Activation approval")
            if (payload.get("schema") not in {"PASES_CONSUMER_ACTIVATION_APPROVAL_V1",
                                               "PASES_CONSUMER_ACTIVATION_APPROVAL_V2"}
                    or payload.get("activation_issue_number") != issue_number
                    or payload.get("repository") != repository
                    or payload.get("predecessor_record_id") != predecessor
                    or type(payload.get("setup_pr_number")) is not int
                    or payload.get("setup_pr_number") in used_prs):
                raise ConsumerActivationError("orphan approval is not a valid pending Activation successor")
        final_comments = github.issue_comments(issue_number)
        if not isinstance(final_comments, list) or any(not isinstance(row, dict) for row in final_comments):
            raise ConsumerActivationError("Activation Issue final comment list is malformed")
        final_prefix_comments = comments_through_selected_record(final_comments)
        final_records = [row for row in final_prefix_comments if isinstance(row.get("body"), str)
                             and row["body"].startswith((RECORD_MARKER, RECORD_MARKER_V2))]
        final_approvals = [row for row in final_prefix_comments if isinstance(row.get("body"), str)
                               and row["body"].startswith((APPROVAL_MARKER, APPROVAL_MARKER_V2))]
        final_markers = {
            "records": marker_snapshot(final_records, RECORD_MARKER, RECORD_MARKER_V2, "Activation record"),
            "approvals": marker_snapshot(final_approvals, APPROVAL_MARKER, APPROVAL_MARKER_V2, "Activation approval"),
        }
        if initial_markers != final_markers:
            raise ConsumerActivationError("Activation history prefix changed during readback")
        return result
    except (GitHubError, ADCError, RulesetManagementError) as exc:
        raise ConsumerActivationError(f"Activation history readback failed: {exc}") from exc


def read_consumer_activation_record(
    github: GitHub, repository: str, issue_number: int,
) -> tuple[ConsumerActivationRecord, int] | None:
    history = read_consumer_activation_history(github, repository, issue_number)
    return history[-1] if history else None
