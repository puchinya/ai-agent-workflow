"""One-shot, exact-ADC-authorized Issue #71 verification phase rework."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .adc import (
    ADCError, VerifiedADC, verify_adc, verify_adc_forward_generations,
    verify_adc_generation,
)
from .delivery import ReadinessResult, read_readiness, readiness_path
from .github import GitHub, GitHubError
from .git import (
    GitError, changed_paths_between, commit_parents_sha40, current_branch,
    head_sha40, is_ancestor, remote_branch_sha, run_git, worktree_clean,
)
from .path_safety import path_has_symlink

REPOSITORY = "puchinya/ai-agent-workflow"
REPOSITORY_ID = 1401910271
OWNER_ID = 3744776
ISSUE_NUMBER = 71
ISSUE_ID = 6135294757
ISSUE_BODY_SHA256 = "5f910c8de4cbe3ec391edf18b69fabe0f4c42880b59357083647a8b06e7a6a36"
REWORK_ADC_COMMENT_ID = 6887429739
REWORK_ADC_SHA256 = "c4de9fc1308c63f0de3ba4b8269fa779d2c38688cf420c59031911d1522cb8e2"
REWORK_ADC_BYTES = 15113
PREDECESSOR_ADC_COMMENT_ID = 6886911700
PREDECESSOR_ADC_SHA256 = "a3c171ab44bf2145aea25b9e43b35fc235b04748e9ad2228847c7379f404e350"
EPOCH_ORIGIN_ADC_COMMENT_ID = 6881591677
EPOCH_ORIGIN_ADC_SHA256 = "3c6b3ac28270357b57047dc5da0a2c1fbdbada269d55225ea33a656cd3076e17"
ACTIVE_EPOCH_ID = "50af48a8a0d92f65f362ee371959152de755ab7057604a47a9155e938357ee8a"
ACTIVE_EPOCH_SHA256 = "086a8e23601a869e4ec678a80ef82836c1cf76d50be13788658b02e037c51d00"
ACTIVE_PHASE_COMMENT_ID = 6881839877
ACTIVE_PHASE_SHA256 = "133cba8d9fb815581de12552bac9d76cb634819d012513e9e3be086e4180a3c5"
BASELINE_HEAD = "b781ddf1bd6eb5067e87f269da4b1306341e682d"
BASE_REF = "main"
BASE_SHA40 = "07481c4b451a81750a6c2e1a6a18bdfd4e3459c2"
BRANCH_REF = "pases/issue-71-local-activation-v2-phase-rebaseline-epoch-3"
PR_NUMBER = 75
PR_BASE_REF = "main"
PR_BASE_SHA40 = "07481c4b451a81750a6c2e1a6a18bdfd4e3459c2"
PRIOR_READINESS_SHA256 = "62e1ab213abe3ffe81939a4bfaae92f86bbf1c465b787a81eab8d6cee129448e"
LABELS_BEFORE = ["enhancement", "kind:single", "phase:verification"]
LABELS_AFTER = ["enhancement", "kind:single", "phase:requirements"]
AUTH_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_AUTHORIZATION_V2"
INTENT_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_INTENT_V2"
APPLIED_SCHEMA = "PASES_ISSUE_VERIFICATION_REWORK_APPLIED_V2"
INTENT_START = f"<!-- {INTENT_SCHEMA}\n"
APPLIED_START = f"<!-- {APPLIED_SCHEMA}\n"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")

BOOTSTRAP_PATH_ALLOWLIST = (
    "dist/antigravity/docs/design/runtime-design.md",
    "dist/antigravity/docs/design/workflow-design.md",
    "dist/antigravity/docs/specs/runtime-spec.md",
    "dist/antigravity/docs/specs/workflow-spec.md",
    "dist/antigravity/runtime/p_ases/cli.py",
    "dist/antigravity/runtime/p_ases/phase_epoch_rebaseline.py",
    "dist/antigravity/runtime/p_ases/phase_rework.py",
    "dist/claude/docs/design/runtime-design.md",
    "dist/claude/docs/design/workflow-design.md",
    "dist/claude/docs/specs/runtime-spec.md",
    "dist/claude/docs/specs/workflow-spec.md",
    "dist/claude/runtime/p_ases/cli.py",
    "dist/claude/runtime/p_ases/phase_epoch_rebaseline.py",
    "dist/claude/runtime/p_ases/phase_rework.py",
    "dist/openai/docs/design/runtime-design.md",
    "dist/openai/docs/design/workflow-design.md",
    "dist/openai/docs/specs/runtime-spec.md",
    "dist/openai/docs/specs/workflow-spec.md",
    "dist/openai/runtime/p_ases/cli.py",
    "dist/openai/runtime/p_ases/phase_epoch_rebaseline.py",
    "dist/openai/runtime/p_ases/phase_rework.py",
    "docs/design/runtime-design.md",
    "docs/design/workflow-design.md",
    "docs/specs/runtime-spec.md",
    "docs/specs/workflow-spec.md",
    "docs/testing/pases-lifecycle-tests.md",
    "docs/testing/runtime-tests.md",
    "docs/testing/traceability.md",
    "runtime/p_ases/cli.py",
    "runtime/p_ases/phase_epoch_rebaseline.py",
    "runtime/p_ases/phase_rework.py",
    "runtime/p_ases/phases.py",
    "tests/test_p_ases_cli.py",
    "tests/test_phase_epoch_rebaseline.py",
    "tests/test_phase_rework.py",
)

AUTHORIZATION: dict[str, Any] = {
    "active_epoch_id": ACTIVE_EPOCH_ID,
    "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
    "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
    "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
    "baseline_head_sha40": BASELINE_HEAD,
    "baseline_pr_head_sha40": BASELINE_HEAD,
    "bootstrap_path_allowlist": list(BOOTSTRAP_PATH_ALLOWLIST),
    "branch_ref": BRANCH_REF,
    "current_issue_body_sha256": ISSUE_BODY_SHA256,
    "epoch_origin_adc_comment_id": EPOCH_ORIGIN_ADC_COMMENT_ID,
    "epoch_origin_adc_sha256": EPOCH_ORIGIN_ADC_SHA256,
    "existing_user_review_session": "absent",
    "from_phase": "verification",
    "issue_number": ISSUE_NUMBER,
    "labels_after": LABELS_AFTER,
    "labels_before": LABELS_BEFORE,
    "max_applications": 1,
    "max_bootstrap_commits": 3,
    "owner_id": OWNER_ID,
    "pr_base_ref": PR_BASE_REF,
    "pr_base_sha40": PR_BASE_SHA40,
    "pr_number": PR_NUMBER,
    "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
    "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
    "prior_readiness_sha256": PRIOR_READINESS_SHA256,
    "repository": REPOSITORY,
    "repository_id": REPOSITORY_ID,
    "require_fresh_readiness": True,
    "schema": AUTH_SCHEMA,
    "target_issue": ISSUE_NUMBER,
    "to_phase": "requirements",
}
AUTH_FIELDS = frozenset(AUTHORIZATION)
COMMON_FIELDS = frozenset({
    "repository", "repository_id", "issue_number", "issue_id", "adc_comment_id", "adc_sha256",
    "authorization_sha256", "predecessor_adc_comment_id", "predecessor_adc_sha256",
    "epoch_origin_adc_comment_id", "epoch_origin_adc_sha256", "active_epoch_id", "active_epoch_sha256",
    "active_phase_generation_comment_id", "active_phase_generation_sha256", "baseline_head_sha40",
    "bootstrap_head_sha40", "branch_ref", "pr_number", "pr_base_ref", "pr_base_sha40", "pr_head_sha40",
    "readiness_sha256", "readiness_subject_sha256", "issue_body_sha256", "labels_before", "labels_after",
    "from_phase", "to_phase", "max_applications", "owner_id", "executor_user_id",
})
INTENT_FIELDS = COMMON_FIELDS | {"schema", "created_at"}
APPLIED_FIELDS = COMMON_FIELDS | {"schema", "intent_comment_id", "intent_body_sha256", "applied_at"}


class PhaseReworkError(ValueError):
    """Issue #71 phase rework authorization, evidence, or journal is invalid."""


@dataclass(frozen=True)
class PhaseReworkRecord:
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
class _Live:
    current_adc: VerifiedADC
    epoch: Any
    issue: dict[str, Any]
    labels: tuple[str, ...]
    branch_ref: str
    head_sha40: str
    pr: dict[str, Any]
    executor_user_id: int
    authorization_sha256: str
    root: Path


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PhaseReworkError("phase rework JSON contains duplicate fields")
        result[key] = value
    return result


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise PhaseReworkError(f"{label} must be a lowercase SHA-256")
    return value


def _strict_utc(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PhaseReworkError(f"{label} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PhaseReworkError(f"{label} is malformed") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed) or parsed.isoformat(timespec="seconds") != value[:-1] + "+00:00":
        raise PhaseReworkError(f"{label} must be canonical UTC")
    return value


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_authorization(verified: VerifiedADC) -> tuple[dict[str, Any], str]:
    if (verified.pointer.state != "approved" or verified.pointer.comment_id != REWORK_ADC_COMMENT_ID
            or verified.contract.sha256 != REWORK_ADC_SHA256
            or verified.contract.byte_length != REWORK_ADC_BYTES
            or verified.contract.repository.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("current approved ADC differs from the exact Issue #71 rework contract")
    text = verified.contract.content.decode("utf-8", errors="strict")
    start_marker = f"<!-- {AUTH_SCHEMA}\n"
    if text.count(start_marker) != 1:
        raise PhaseReworkError("current ADC must contain exactly one rework authorization marker")
    start = text.index(start_marker)
    close = text.find("\n-->", start + len(start_marker))
    if close < 0:
        raise PhaseReworkError("rework authorization marker is incomplete")
    raw = text[start + len(start_marker):close]
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("rework authorization JSON is malformed") from exc
    if not isinstance(value, dict) or set(value) != AUTH_FIELDS or _canonical(value) != raw:
        raise PhaseReworkError("rework authorization has unknown fields or noncanonical JSON")
    if value != AUTHORIZATION:
        raise PhaseReworkError("rework authorization does not match its exact Issue #71 tuple")
    predecessor = re.search(
        r"^Predecessor ADC: Issue #71 comment #(\d+), SHA-256 ([0-9a-f]{64})$", text, re.M,
    )
    if (predecessor is None or int(predecessor.group(1)) != PREDECESSOR_ADC_COMMENT_ID
            or predecessor.group(2) != PREDECESSOR_ADC_SHA256):
        raise PhaseReworkError("current ADC predecessor declaration differs from the exact approved pointer")
    marker_bytes = text[start:close + len("\n-->")].encode("utf-8")
    return value, hashlib.sha256(marker_bytes).hexdigest()


def _label_names(issue: Mapping[str, Any]) -> tuple[str, ...]:
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PhaseReworkError("Issue label readback is incomplete")
    names = [row.get("name") for row in rows]
    if any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
        raise PhaseReworkError("Issue labels are malformed or duplicated")
    return tuple(sorted(names))


def _issue(github: GitHub, *, expected_labels: tuple[str, ...] | None = None) -> tuple[dict[str, Any], tuple[str, ...]]:
    try:
        issue = github.issue(ISSUE_NUMBER)
    except GitHubError as exc:
        raise PhaseReworkError(f"Issue #71 readback failed: {exc}") from exc
    if (not isinstance(issue, dict) or issue.get("number") != ISSUE_NUMBER or issue.get("id") != ISSUE_ID
            or issue.get("state") != "open" or issue.get("pull_request") is not None
            or issue.get("repository_url") != f"https://api.github.com/repos/{REPOSITORY}"
            or not isinstance(issue.get("body"), str)
            or hashlib.sha256(issue["body"].encode("utf-8")).hexdigest() != ISSUE_BODY_SHA256):
        raise PhaseReworkError("Issue #71 identity, body, or state differs from the approved marker")
    labels = _label_names(issue)
    if expected_labels is not None and labels != expected_labels:
        raise PhaseReworkError("Issue #71 full labels differ from the expected rework state")
    return issue, labels


def _pr(github: GitHub, head_sha40: str) -> dict[str, Any]:
    try:
        pull = github.pull_request(PR_NUMBER)
    except GitHubError as exc:
        raise PhaseReworkError(f"PR #75 readback failed: {exc}") from exc
    base = pull.get("base") if isinstance(pull, dict) else None
    head = pull.get("head") if isinstance(pull, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    if (not isinstance(pull, dict) or pull.get("number") != PR_NUMBER or pull.get("state") != "open"
            or pull.get("draft") is not False or pull.get("merged_at") is not None
            or not isinstance(base, dict) or base.get("ref") != PR_BASE_REF
            or base.get("sha") != PR_BASE_SHA40 or not isinstance(head, dict)
            or head.get("ref") != BRANCH_REF or head.get("sha") != head_sha40
            or not isinstance(base_repo, dict) or base_repo.get("id") != REPOSITORY_ID
            or not isinstance(head_repo, dict) or head_repo.get("full_name", "").casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("PR #75 is not the exact open, non-draft bootstrap subject")
    if head_repo.get("id") != REPOSITORY_ID:
        raise PhaseReworkError("PR #75 head repository stable ID differs from the pinned repository")
    return pull


def _validate_post_rework_labels(labels: tuple[str, ...]) -> None:
    if labels == tuple(sorted(LABELS_AFTER)):
        return
    phases = [label for label in labels if label.startswith("phase:")]
    kinds = [label for label in labels if label.startswith("kind:")]
    if (len(phases) != 1 or phases[0] not in {
            "phase:specification", "phase:design", "phase:ready", "phase:execution",
            "phase:user-review", "phase:integration"}
            or kinds != ["kind:single"] or "enhancement" not in labels):
        raise PhaseReworkError("post-rework Issue labels do not have one active forward phase")


def _verify_commit_set(root: Path, head: str, allowlist: tuple[str, ...]) -> None:
    if head == BASELINE_HEAD or not is_ancestor(root, BASELINE_HEAD, head):
        raise PhaseReworkError("bootstrap HEAD must be a descendant of the exact pre-bootstrap baseline")
    rows = run_git(root, "rev-list", "--reverse", f"{BASELINE_HEAD}..{head}").splitlines()
    if not 1 <= len(rows) <= 3 or len(rows) > AUTHORIZATION["max_bootstrap_commits"]:
        raise PhaseReworkError("bootstrap must contain one to three descendant commits")
    parent = BASELINE_HEAD
    for commit in rows:
        if not SHA40.fullmatch(commit) or commit_parents_sha40(root, commit) != (parent,):
            raise PhaseReworkError("bootstrap commit chain contains a merge or unexpected parent")
        changed = changed_paths_between(root, parent, commit)
        if not changed or any(path not in allowlist for path in changed):
            raise PhaseReworkError("bootstrap commit changes a path outside the exact allowlist")
        parent = commit
    if parent != head:
        raise PhaseReworkError("bootstrap commit enumeration does not end at the exact HEAD")


def _user_review_absent(root: Path) -> None:
    folder = root / ".p_ases" / "user-review" / str(ISSUE_NUMBER)
    if path_has_symlink(folder, root=root):
        raise PhaseReworkError("User Review state path traverses a symlink")
    if not folder.exists():
        return
    if not folder.is_dir():
        raise PhaseReworkError("User Review state path is not a directory")
    for candidate in folder.rglob("session.json"):
        if path_has_symlink(candidate, root=root) or candidate.is_file():
            raise PhaseReworkError("an Issue #71 User Review session already exists")


def _live(github: GitHub, root: Path, *, phase: str | None = None,
          require_clean: bool = True) -> _Live:
    from . import phase_epoch_rebaseline as epoch_module

    try:
        current = verify_adc(github, ISSUE_NUMBER)
        authorization, authorization_sha = parse_authorization(current)
        chain = verify_adc_forward_generations(
            github, ISSUE_NUMBER,
            prior_comment_id=PREDECESSOR_ADC_COMMENT_ID,
            prior_sha256=PREDECESSOR_ADC_SHA256,
            current_comment_id=current.pointer.comment_id,
            current_sha256=current.contract.sha256,
        )
        if (len(chain) != 2 or chain[0].pointer.comment_id != PREDECESSOR_ADC_COMMENT_ID
                or chain[0].contract.sha256 != PREDECESSOR_ADC_SHA256
                or chain[1].pointer != current.pointer):
            raise PhaseReworkError("current ADC is not the exact approved successor of #6886739124")
        actor = github.authenticated_user()
        metadata = github.repository_metadata()
        if (not isinstance(actor, dict) or actor.get("id") != OWNER_ID or actor.get("type") != "User"
                or not isinstance(metadata, dict) or metadata.get("id") != REPOSITORY_ID
                or metadata.get("full_name", "").casefold() != REPOSITORY.casefold()):
            raise PhaseReworkError("authenticated owner or repository stable identity is not exact")
        issue, labels = _issue(github)
        if phase is not None:
            expected = tuple(sorted(LABELS_BEFORE if phase == "verification" else LABELS_AFTER))
            if labels != expected:
                raise PhaseReworkError("Issue #71 phase labels differ from the exact rework state")
        epoch, verified_again, origin, issue_from_epoch = epoch_module.read_epoch_origin(
            github, root, current,
        )
        if (verified_again.pointer != current.pointer
                or issue_from_epoch.get("body") != issue.get("body")
                or issue_from_epoch.get("state") != issue.get("state")
                or _label_names(issue_from_epoch) != labels
                or issue_from_epoch.get("repository_url") != issue.get("repository_url")):
            raise PhaseReworkError("Issue or ADC identity changed during epoch-origin readback")
        if (epoch.adc_comment_id != EPOCH_ORIGIN_ADC_COMMENT_ID
                or epoch.adc_sha256 != EPOCH_ORIGIN_ADC_SHA256
                or epoch.epoch_id != authorization["active_epoch_id"]
                or epoch.sha256 != authorization["active_epoch_sha256"]
                or epoch.applied_comment_id != authorization["active_phase_generation_comment_id"]
                or epoch.applied_body_sha256 != authorization["active_phase_generation_sha256"]):
            raise PhaseReworkError("active epoch origin or pre-rework Phase generation differs from the marker")
        branch = current_branch(root)
        head = head_sha40(root)
        if branch != BRANCH_REF or not is_ancestor(root, BASELINE_HEAD, head):
            raise PhaseReworkError("local branch or HEAD differs from the authorized bootstrap ancestry")
        if require_clean and not worktree_clean(root):
            raise PhaseReworkError("phase rework requires a clean local worktree")
        _pr(github, head)
        remote_head = remote_branch_sha(root, BRANCH_REF)
        if remote_head != head:
            raise PhaseReworkError("local bootstrap HEAD differs from the remote PR branch HEAD")
        if head != BASELINE_HEAD:
            _verify_commit_set(root, head, tuple(authorization["bootstrap_path_allowlist"]))
        return _Live(current, epoch, issue, labels, branch, head, _pr(github, head),
                     actor["id"], authorization_sha, root)
    except (ADCError, GitError, GitHubError, ValueError) as exc:
        raise PhaseReworkError(str(exc)) from exc


def _comment_fingerprint(row: Any, comment_id: int) -> tuple[Any, ...]:
    if (not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] != comment_id
            or not isinstance(row.get("body"), str)):
        raise PhaseReworkError("phase rework journal comment is malformed")
    author = row.get("user")
    if (not isinstance(author, dict) or author.get("type") != "User"
            or type(author.get("id")) is not int or author.get("id") != OWNER_ID
            or not isinstance(author.get("login"), str) or not author.get("login")):
        raise PhaseReworkError("phase rework journal actor is not the authenticated owner User")
    created, updated = row.get("created_at"), row.get("updated_at")
    if not isinstance(created, str) or updated != created:
        raise PhaseReworkError("phase rework journal comment was edited or has no stable timestamp")
    _strict_utc(created, "journal comment created_at")
    expected = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}#issuecomment-{comment_id}",
        f"https://api.github.com/repos/{REPOSITORY}/issues/comments/{comment_id}",
    )
    actual = (row.get("issue_url"), row.get("html_url"), row.get("url"))
    if actual != expected:
        raise PhaseReworkError("phase rework journal comment URLs differ from Issue #71")
    return (comment_id, row["body"], created, updated, author["id"], author["login"].casefold(), *actual)


def _is_rework_candidate(body: str) -> bool:
    header = body.lstrip()
    offset = 0
    while offset < len(header) and header[offset] in "<!-/ >":
        offset += 1
    return header[offset:].startswith("PASES_ISSUE_VERIFICATION_REWORK_")


def _parse_record(row: Any, schema: str) -> PhaseReworkRecord:
    if not isinstance(row, dict):
        raise PhaseReworkError("phase rework journal row is malformed")
    comment_id = row.get("id")
    body = row.get("body")
    if type(comment_id) is not int or comment_id < 1 or not isinstance(body, str):
        raise PhaseReworkError("phase rework journal identity is malformed")
    start = f"<!-- {schema}\n"
    if not body.startswith(start) or not body.endswith("\n-->"):
        raise PhaseReworkError("phase rework journal marker framing is malformed")
    raw = body[len(start):-len("\n-->")]
    try:
        payload = json.loads(raw, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PhaseReworkError("phase rework journal JSON is malformed") from exc
    expected_fields = INTENT_FIELDS if schema == INTENT_SCHEMA else APPLIED_FIELDS
    if (not isinstance(payload, dict) or set(payload) != expected_fields
            or payload.get("schema") != schema or _canonical(payload) != raw):
        raise PhaseReworkError("phase rework journal fields or canonical JSON are invalid")
    fingerprint = _comment_fingerprint(row, comment_id)
    return PhaseReworkRecord(comment_id, schema, payload, body, fingerprint[4], fingerprint[2])


def _read_history(github: GitHub) -> tuple[PhaseReworkRecord, ...]:
    try:
        first = github.issue_comments(ISSUE_NUMBER)
        first_rows: list[tuple[dict[str, Any], str]] = []
        for row in first:
            body = row.get("body") if isinstance(row, dict) else None
            if not isinstance(body, str):
                continue
            candidate = body.lstrip()
            if not _is_rework_candidate(body):
                continue
            schema = next((value for value in (INTENT_SCHEMA, APPLIED_SCHEMA)
                           if candidate.startswith(f"<!-- {value}\n")), None)
            if schema is None or body != candidate:
                raise PhaseReworkError("malformed reserved Issue #71 phase rework marker")
            first_rows.append((row, schema))
        ids = [row.get("id") for row, _schema in first_rows]
        if any(type(value) is not int or value < 1 for value in ids) or ids != sorted(set(ids)):
            raise PhaseReworkError("phase rework comment history is duplicated or unordered")
        before = {comment_id: github.issue_comment(ISSUE_NUMBER, comment_id) for comment_id in ids}
        second = github.issue_comments(ISSUE_NUMBER)
        second_rows = []
        for row in second:
            body = row.get("body") if isinstance(row, dict) else None
            if isinstance(body, str) and _is_rework_candidate(body):
                second_rows.append(row)
        second_ids = [row.get("id") if isinstance(row, dict) else None for row in second_rows]
        if second_ids != ids:
            raise PhaseReworkError("phase rework journal changed during direct/list/direct readback")
        after = {comment_id: github.issue_comment(ISSUE_NUMBER, comment_id) for comment_id in ids}
    except GitHubError as exc:
        raise PhaseReworkError(f"phase rework journal readback failed: {exc}") from exc
    records: list[PhaseReworkRecord] = []
    for listed, schema in first_rows:
        comment_id = listed["id"]
        fingerprints = tuple(_comment_fingerprint(row, comment_id)
                             for row in (before[comment_id],
                                         next(row for row in second_rows if row.get("id") == comment_id),
                                         after[comment_id]))
        if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
            raise PhaseReworkError("phase rework journal comment changed during direct/list/direct readback")
        records.append(_parse_record(before[comment_id], schema))
    return tuple(records)


def _validate_intent(record: PhaseReworkRecord, live: _Live,
                     readiness: ReadinessResult | None = None, *,
                     allow_bootstrap_descendant: bool = False) -> None:
    payload = record.payload
    if (record.schema != INTENT_SCHEMA or set(payload) != INTENT_FIELDS
            or payload.get("schema") != INTENT_SCHEMA):
        raise PhaseReworkError("phase rework Intent has an invalid schema")
    expected = {
        "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER, "issue_id": ISSUE_ID,
        "adc_comment_id": REWORK_ADC_COMMENT_ID, "adc_sha256": REWORK_ADC_SHA256,
        "authorization_sha256": live.authorization_sha256,
        "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
        "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
        "epoch_origin_adc_comment_id": EPOCH_ORIGIN_ADC_COMMENT_ID,
        "epoch_origin_adc_sha256": EPOCH_ORIGIN_ADC_SHA256,
        "active_epoch_id": ACTIVE_EPOCH_ID, "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
        "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
        "baseline_head_sha40": BASELINE_HEAD,
        "bootstrap_head_sha40": payload.get("pr_head_sha40"),
        "branch_ref": BRANCH_REF, "pr_number": PR_NUMBER,
        "pr_base_ref": PR_BASE_REF, "pr_base_sha40": PR_BASE_SHA40,
        "pr_head_sha40": payload.get("bootstrap_head_sha40"),
        "issue_body_sha256": ISSUE_BODY_SHA256,
        "labels_before": LABELS_BEFORE, "labels_after": LABELS_AFTER,
        "from_phase": "verification", "to_phase": "requirements",
        "max_applications": 1, "owner_id": OWNER_ID, "executor_user_id": live.executor_user_id,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise PhaseReworkError(f"phase rework Intent field {key} differs from the live exact subject")
    bootstrap_head = payload.get("bootstrap_head_sha40")
    if (not isinstance(bootstrap_head, str) or SHA40.fullmatch(bootstrap_head) is None
            or payload.get("pr_head_sha40") != bootstrap_head
            or record.actor_id != live.executor_user_id or live.executor_user_id != OWNER_ID):
        raise PhaseReworkError("phase rework Intent author or bootstrap HEAD is invalid")
    if allow_bootstrap_descendant:
        if (not is_ancestor(live.root, BASELINE_HEAD, bootstrap_head)
                or not is_ancestor(live.root, bootstrap_head, live.head_sha40)):
            raise PhaseReworkError("active bootstrap HEAD is not on the current authorized branch ancestry")
    elif bootstrap_head != live.head_sha40:
        raise PhaseReworkError("phase rework Intent bootstrap HEAD differs from the exact live subject")
    _sha(payload.get("readiness_sha256"), "Intent Readiness SHA-256")
    subject_sha = _sha(payload.get("readiness_subject_sha256"), "Intent Readiness subject SHA-256")
    if payload["readiness_sha256"] == PRIOR_READINESS_SHA256:
        raise PhaseReworkError("historical Readiness cannot authorize the one-shot rework")
    _strict_utc(payload.get("created_at"), "Intent created_at")
    if readiness is not None:
        _validate_readiness(readiness, live)
        if (readiness.sha256 != payload["readiness_sha256"]
                or readiness.subject.sha256 != subject_sha):
            raise PhaseReworkError("phase rework Intent differs from the fresh current Readiness")


def _validate_readiness(readiness: ReadinessResult, live: _Live) -> None:
    try:
        readiness.validate()
    except ValueError as exc:
        raise PhaseReworkError(f"fresh Review Readiness is invalid: {exc}") from exc
    subject = readiness.subject
    if (readiness.status != "PASS" or readiness.sha256 == PRIOR_READINESS_SHA256
            or subject.repository.casefold() != REPOSITORY.casefold()
            or subject.issue_number != ISSUE_NUMBER or subject.pr_number != PR_NUMBER
            or subject.adc_comment_id != live.current_adc.pointer.comment_id
            or subject.adc_sha256 != live.current_adc.contract.sha256
            or subject.pr_head_sha40 != live.head_sha40):
        raise PhaseReworkError("fresh PASS Readiness is stale or bound to another ADC/PR/HEAD")
    location = readiness_path(live.root, readiness)
    try:
        on_disk = read_readiness(location)
    except ValueError as exc:
        raise PhaseReworkError(f"fresh Readiness bytes are not durably available: {exc}") from exc
    if on_disk != readiness:
        raise PhaseReworkError("fresh Readiness file differs from the reported current result")


def _validate_applied(applied: PhaseReworkRecord, intent: PhaseReworkRecord,
                      live: _Live, *, allow_bootstrap_descendant: bool = False) -> None:
    if (applied.schema != APPLIED_SCHEMA or applied.comment_id <= intent.comment_id
            or applied.actor_id != intent.actor_id
            or applied.payload.get("intent_comment_id") != intent.comment_id
            or applied.payload.get("intent_body_sha256") != intent.body_sha256):
        raise PhaseReworkError("phase rework Applied does not reference its exact Intent")
    if _strict_utc(applied.payload.get("applied_at"), "Applied applied_at") != applied.created_at:
        raise PhaseReworkError("phase rework Applied timestamp differs from its Issue comment")
    for key in COMMON_FIELDS:
        if applied.payload.get(key) != intent.payload.get(key):
            raise PhaseReworkError(f"phase rework Applied changed Intent field {key}")
    _validate_intent(intent, live, allow_bootstrap_descendant=allow_bootstrap_descendant)


def _active_rework_records(history: tuple[PhaseReworkRecord, ...],
                           current_adc: VerifiedADC) -> tuple[PhaseReworkRecord | None,
                                                              PhaseReworkRecord | None]:
    if len(history) > 2:
        raise PhaseReworkError("Issue #71 phase rework has duplicate or unrelated records")
    intents = [row for row in history if row.schema == INTENT_SCHEMA]
    applied = [row for row in history if row.schema == APPLIED_SCHEMA]
    if len(intents) > 1 or len(applied) > 1:
        raise PhaseReworkError("Issue #71 phase rework Intent/Applied is duplicated")
    if applied and not intents:
        raise PhaseReworkError("phase rework Applied has no matching Intent")
    for row in history:
        if (row.payload.get("adc_comment_id") != REWORK_ADC_COMMENT_ID
                or row.payload.get("adc_sha256") != REWORK_ADC_SHA256):
            raise PhaseReworkError("phase rework journal belongs to another ADC generation")
    if intents and applied:
        if applied[0].comment_id <= intents[0].comment_id:
            raise PhaseReworkError("phase rework journal is not append-only")
    if current_adc.pointer.comment_id < REWORK_ADC_COMMENT_ID:
        raise PhaseReworkError("current ADC predates the authorized phase rework generation")
    return (intents[0] if intents else None, applied[0] if applied else None)


def _validate_recorded_readiness(root: Path, intent: PhaseReworkRecord) -> None:
    payload = intent.payload
    subject_sha = _sha(payload.get("readiness_subject_sha256"), "Readiness subject SHA-256")
    readiness_sha = _sha(payload.get("readiness_sha256"), "Readiness SHA-256")
    path = (Path(root).absolute() / ".p_ases" / "readiness" / str(ISSUE_NUMBER)
            / subject_sha / f"{readiness_sha}.json")
    try:
        readiness = read_readiness(path)
    except ValueError as exc:
        raise PhaseReworkError(f"the exact Readiness bound by the Intent is missing or invalid: {exc}") from exc
    if (readiness.status != "PASS" or readiness.sha256 != readiness_sha
            or readiness.subject.sha256 != subject_sha
            or readiness.subject.adc_comment_id != REWORK_ADC_COMMENT_ID
            or readiness.subject.adc_sha256 != REWORK_ADC_SHA256
            or readiness.subject.pr_number != PR_NUMBER
            or readiness.subject.pr_head_sha40 != payload.get("bootstrap_head_sha40")):
        raise PhaseReworkError("Intent-bound Readiness is not the exact fresh bootstrap PASS")


def _record_body(schema: str, payload: Mapping[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(dict(payload))}\n-->"


def _record_path(root: Path, operation: str) -> Path:
    if operation not in {"intent", "labels", "applied"}:
        raise PhaseReworkError("phase rework local attempt operation is invalid")
    return Path(root).resolve() / ".p_ases" / "state" / str(ISSUE_NUMBER) / "phase-rework-v2" / "attempts" / f"{operation}.json"


def _write_attempt_once(root: Path, operation: str, payload: Mapping[str, Any]) -> None:
    path = _record_path(root, operation)
    if path_has_symlink(path, root=Path(root).resolve()):
        raise PhaseReworkError("phase rework attempt path traverses a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (_canonical({"schema": "PASES_ISSUE_PHASE_REWORK_LOCAL_ATTEMPT_V1",
                        "operation": operation,
                        "payload_sha256": hashlib.sha256(_canonical(dict(payload)).encode()).hexdigest()}) + "\n").encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PhaseReworkError(f"{operation} was previously attempted; read-only recovery only") from exc
    except OSError as exc:
        raise PhaseReworkError(f"could not write the one-shot {operation} attempt marker") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise PhaseReworkError(f"could not durably write the one-shot {operation} attempt marker") from exc


def _post_record_once(github: GitHub, root: Path, schema: str,
                      payload: Mapping[str, Any]) -> PhaseReworkRecord:
    body = _record_body(schema, payload)
    records = _read_history(github)
    matching = [record for record in records if record.schema == schema and record.body == body]
    if len(matching) == 1:
        return matching[0]
    if any(record.schema == schema for record in records):
        raise PhaseReworkError(f"a conflicting {schema} record already exists")
    operation = "intent" if schema == INTENT_SCHEMA else "applied"
    _write_attempt_once(root, operation, payload)
    write_error: GitHubError | None = None
    created_id = None
    try:
        created = github.create_issue_comment(ISSUE_NUMBER, body)
        created_id = created.get("id") if isinstance(created, dict) else None
    except GitHubError as exc:
        write_error = exc
    try:
        after = _read_history(github)
    except PhaseReworkError as exc:
        if write_error is not None:
            raise PhaseReworkError(f"{operation} POST failed and readback is unavailable; no retry") from write_error
        raise
    matching = [record for record in after if record.schema == schema and record.body == body]
    if len(matching) != 1:
        reason = "POST outcome is ambiguous" if write_error else "POST has no unique exact readback"
        raise PhaseReworkError(f"{reason}; {operation} will not be retried")
    record = matching[0]
    if created_id is not None and created_id != record.comment_id:
        raise PhaseReworkError("POST Comment ID differs from direct/list/direct readback")
    if record.actor_id != payload.get("executor_user_id"):
        raise PhaseReworkError("phase rework comment author differs from its authenticated executor")
    return record


def _validate_label_attempt(root: Path, intent: PhaseReworkRecord) -> bool:
    path = _record_path(root, "labels")
    if path_has_symlink(path, root=Path(root).resolve()):
        raise PhaseReworkError("label attempt path traverses a symlink")
    return path.exists()


def _replace_labels_once(github: GitHub, root: Path, intent: PhaseReworkRecord) -> None:
    live = _live(github, root, phase="verification")
    _validate_intent(intent, live)
    _validate_recorded_readiness(root, intent)
    _user_review_absent(root)
    issue, labels = live.issue, live.labels
    if labels == tuple(sorted(LABELS_AFTER)):
        return
    if labels != tuple(sorted(LABELS_BEFORE)):
        raise PhaseReworkError("Issue labels match neither the exact before nor after state")
    if _validate_label_attempt(root, intent):
        raise PhaseReworkError("label PUT was previously attempted; read-only recovery only")
    marker_payload = {
        "intent_comment_id": intent.comment_id,
        "intent_body_sha256": intent.body_sha256,
        "labels_before": LABELS_BEFORE,
        "labels_after": LABELS_AFTER,
        "schema": "PASES_ISSUE_PHASE_REWORK_LABEL_ATTEMPT_V1",
    }
    _write_attempt_once(root, "labels", marker_payload)
    write_error: GitHubError | None = None
    try:
        github.replace_issue_labels(ISSUE_NUMBER, LABELS_AFTER)
    except GitHubError as exc:
        write_error = exc
    after, after_labels = _issue(github)
    if after_labels != tuple(sorted(LABELS_AFTER)):
        if after_labels == tuple(sorted(LABELS_BEFORE)) and write_error is not None:
            raise PhaseReworkError("label PUT failed with before-state unchanged; retry is prohibited") from write_error
        raise PhaseReworkError("label PUT outcome is not the exact authorized after-state")
    if after.get("body") != issue.get("body") or after.get("state") != "open":
        raise PhaseReworkError("Issue body or state changed during the phase rework label transition")


def _intent_payload(live: _Live, readiness: ReadinessResult) -> dict[str, Any]:
    if not isinstance(readiness, ReadinessResult):
        raise PhaseReworkError("phase rework requires a typed fresh Readiness result")
    _validate_readiness(readiness, live)
    return {
        "schema": INTENT_SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "issue_number": ISSUE_NUMBER,
        "issue_id": ISSUE_ID,
        "adc_comment_id": live.current_adc.pointer.comment_id,
        "adc_sha256": live.current_adc.contract.sha256,
        "authorization_sha256": live.authorization_sha256,
        "predecessor_adc_comment_id": PREDECESSOR_ADC_COMMENT_ID,
        "predecessor_adc_sha256": PREDECESSOR_ADC_SHA256,
        "epoch_origin_adc_comment_id": EPOCH_ORIGIN_ADC_COMMENT_ID,
        "epoch_origin_adc_sha256": EPOCH_ORIGIN_ADC_SHA256,
        "active_epoch_id": ACTIVE_EPOCH_ID,
        "active_epoch_sha256": ACTIVE_EPOCH_SHA256,
        "active_phase_generation_comment_id": ACTIVE_PHASE_COMMENT_ID,
        "active_phase_generation_sha256": ACTIVE_PHASE_SHA256,
        "baseline_head_sha40": BASELINE_HEAD,
        "bootstrap_head_sha40": live.head_sha40,
        "branch_ref": BRANCH_REF,
        "pr_number": PR_NUMBER,
        "pr_base_ref": PR_BASE_REF,
        "pr_base_sha40": PR_BASE_SHA40,
        "pr_head_sha40": live.head_sha40,
        "readiness_sha256": readiness.sha256,
        "readiness_subject_sha256": readiness.subject.sha256,
        "issue_body_sha256": ISSUE_BODY_SHA256,
        "labels_before": LABELS_BEFORE,
        "labels_after": LABELS_AFTER,
        "from_phase": "verification",
        "to_phase": "requirements",
        "max_applications": 1,
        "owner_id": OWNER_ID,
        "executor_user_id": live.executor_user_id,
        "created_at": _timestamp(),
    }


def _applied_payload(intent: PhaseReworkRecord) -> dict[str, Any]:
    payload = {key: value for key, value in intent.payload.items() if key != "created_at"}
    payload["schema"] = APPLIED_SCHEMA
    payload["intent_comment_id"] = intent.comment_id
    payload["intent_body_sha256"] = intent.body_sha256
    payload["applied_at"] = _timestamp()
    return payload


def _check_labels_after(github: GitHub) -> None:
    issue, labels = _issue(github, expected_labels=tuple(sorted(LABELS_AFTER)))
    if issue.get("state") != "open":
        raise PhaseReworkError("Issue #71 closed during the authorized phase transition")


def _ensure_active_record_context(live: _Live, record: PhaseReworkRecord, root: Path) -> None:
    payload = record.payload
    if (payload.get("bootstrap_head_sha40") != live.head_sha40
            or payload.get("pr_head_sha40") != live.head_sha40
            or live.branch_ref != BRANCH_REF):
        raise PhaseReworkError("incomplete phase rework must be recovered at its exact bootstrap HEAD")
    _validate_intent(record, live)
    _validate_recorded_readiness(root, record)


def active_phase_generation_for_epoch(github: GitHub, root: Path, current_adc: VerifiedADC,
                                      origin_epoch: Any, issue: Mapping[str, Any]) -> tuple[int, str]:
    """Return the active rework Applied generation or the immutable epoch Applied."""
    parse_authorization(current_adc)
    history = _read_history(github)
    intent, applied = _active_rework_records(history, current_adc)
    issue_labels = _label_names(issue)
    if intent is None:
        if applied is not None or issue_labels != tuple(sorted(LABELS_BEFORE)):
            raise PhaseReworkError("Issue labels changed without the authorized rework Intent")
        if (origin_epoch.epoch_id != ACTIVE_EPOCH_ID
                or origin_epoch.sha256 != ACTIVE_EPOCH_SHA256
                or origin_epoch.applied_comment_id != ACTIVE_PHASE_COMMENT_ID
                or origin_epoch.applied_body_sha256 != ACTIVE_PHASE_SHA256):
            raise PhaseReworkError("immutable epoch-origin Phase generation differs from the marker")
        return origin_epoch.applied_comment_id, origin_epoch.applied_body_sha256
    root = Path(root).resolve()
    current_head = head_sha40(root)
    live = _Live(current_adc, origin_epoch, dict(issue), issue_labels, BRANCH_REF,
                 current_head, _pr(github, current_head), OWNER_ID,
                 parse_authorization(current_adc)[1], root)
    _validate_intent(intent, live, allow_bootstrap_descendant=True)
    if applied is None:
        raise PhaseReworkError("phase rework has an incomplete Intent; phase operations are blocked")
    _validate_applied(applied, intent, live, allow_bootstrap_descendant=True)
    _validate_post_rework_labels(issue_labels)
    bootstrap_head = intent.payload["bootstrap_head_sha40"]
    current_head = head_sha40(Path(root))
    if (not is_ancestor(Path(root), bootstrap_head, current_head)
            or current_branch(Path(root)) != BRANCH_REF):
        raise PhaseReworkError("active rework generation is not on the current epoch-3 branch ancestry")
    _validate_recorded_readiness(Path(root), intent)
    return applied.comment_id, applied.body_sha256


def _write_applied(github: GitHub, root: Path, intent: PhaseReworkRecord,
                   live: _Live) -> PhaseReworkRecord:
    _check_labels_after(github)
    fresh = _live(github, root, phase="requirements", require_clean=False)
    _validate_intent(intent, fresh)
    if _validate_label_attempt(root, intent) is False:
        raise PhaseReworkError("Applied cannot be written without the one-shot label attempt record")
    applied = _post_record_once(github, root, APPLIED_SCHEMA, _applied_payload(intent))
    _validate_applied(applied, intent, fresh)
    return applied


def apply_issue71_phase_rework(
    github: GitHub,
    root: Path,
    issue_number: int,
    *,
    readiness_factory: Callable[[], ReadinessResult] | None = None,
) -> dict[str, Any]:
    """Apply or recover the one authorized verification-to-requirements rework."""
    if (type(issue_number) is not int or issue_number != ISSUE_NUMBER
            or github.repo.casefold() != REPOSITORY.casefold()):
        raise PhaseReworkError("phase rework is fixed to puchinya/ai-agent-workflow Issue #71")
    root = Path(root).resolve()
    live = _live(github, root, require_clean=True)
    history = _read_history(github)
    intent, applied = _active_rework_records(history, live.current_adc)
    if applied is not None:
        if intent is None:
            raise PhaseReworkError("phase rework Applied has no Intent")
        _validate_applied(applied, intent, live, allow_bootstrap_descendant=True)
        _validate_post_rework_labels(live.labels)
        _validate_recorded_readiness(root, intent)
        return {"status": "NOOP", "issue": ISSUE_NUMBER,
                "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 0}
    if intent is not None:
        if live.labels == tuple(sorted(LABELS_BEFORE)):
            raise PhaseReworkError("an Intent exists with before-labels unchanged; label PUT is never retried")
        if live.labels != tuple(sorted(LABELS_AFTER)):
            raise PhaseReworkError("pending phase rework labels match neither exact state")
        _ensure_active_record_context(live, intent, root)
        applied = _write_applied(github, root, intent, live)
        return {"status": "RECOVERED", "issue": ISSUE_NUMBER,
                "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
                "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 0}

    if live.labels != tuple(sorted(LABELS_BEFORE)):
        raise PhaseReworkError("new phase rework is permitted only from exact phase:verification labels")
    _user_review_absent(root)
    if readiness_factory is None:
        raise PhaseReworkError("fresh exact-subject Readiness evidence is required for first application")
    readiness = readiness_factory()
    _validate_readiness(readiness, live)
    payload = _intent_payload(live, readiness)
    if set(payload) != INTENT_FIELDS:
        raise PhaseReworkError("phase rework Intent payload fields are incomplete")
    intent = _post_record_once(github, root, INTENT_SCHEMA, payload)

    # Re-read the complete mutable subject and recompute the exact Readiness
    # after Intent. No label write occurs if any evidence or identity changed.
    before_labels = _live(github, root, phase="verification")
    _validate_intent(intent, before_labels)
    readiness_after_intent = readiness_factory()
    _validate_intent(intent, before_labels, readiness_after_intent)
    if readiness_after_intent != readiness:
        raise PhaseReworkError("Readiness changed after the one-shot Intent; label update is blocked")
    _replace_labels_once(github, root, intent)
    _check_labels_after(github)
    applied = _write_applied(github, root, intent, before_labels)
    return {"status": "APPLIED", "issue": ISSUE_NUMBER,
            "intent_comment_id": intent.comment_id, "applied_comment_id": applied.comment_id,
            "readiness_sha256": intent.payload["readiness_sha256"], "label_write_count": 1}
