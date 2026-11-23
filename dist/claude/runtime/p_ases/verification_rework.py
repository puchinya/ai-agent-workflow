"""Bounded exact-HEAD verification correction without rewriting Phase history.

The legacy execution->requirements restart remains independent. This module
accepts a verified current-head failing result and appends an immutable
Intent/Applied journal around at most one complete Issue-label update.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adc import ADCError, verify_adc
from .audits import AuditError, IndependentReviewV3, read_independent_review
from .git import GitError, is_ancestor
from .github import GitHub, GitHubError
from .path_safety import path_has_symlink
from .phase_restart import (
    PhaseRestartError, _live_subject, _validated_current_journal, _active_generation_before,
)
from .phases import Phase, PhaseError, parse_phase_labels, parse_attention_labels
from .user_review import UserReviewError, read_review_session
from .user_review_relay import (
    UserReviewRelayError, has_user_review_decision_marker,
    parse_user_review_decision, _identity as _review_decision_identity,
)
from .verification import VerificationError, VerificationResult
from .work import WorkError, parse_issue_association
from .verification_plan import PlanError, read_plan

INTENT_SCHEMA = "PASES_VERIFICATION_REWORK_INTENT_V1"
APPLIED_SCHEMA = "PASES_VERIFICATION_REWORK_APPLIED_V1"
PREFIX = "<!-- PASES_VERIFICATION_REWORK_"
MAX_CYCLES = 3
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class VerificationReworkError(ValueError):
    """A correction is unauthorized, stale, or cannot be recovered safely."""


@dataclass(frozen=True)
class ReworkRecord:
    comment_id: int
    schema: str
    payload: dict[str, Any]
    body: str
    actor_id: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _body(schema: str, value: dict[str, Any]) -> str:
    return f"<!-- {schema}\n{_canonical(value)}\n-->"


def _time() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fingerprint(row: Any, repo: str, issue: int) -> tuple[Any, ...]:
    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1:
        raise VerificationReworkError("rework journal has an invalid comment ID")
    comment_id = row["id"]
    urls = (
        f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}",
        f"https://api.github.com/repos/{repo}/issues/{issue}",
        f"https://github.com/{repo}/issues/{issue}#issuecomment-{comment_id}",
    )
    user = row.get("user")
    created, updated = row.get("created_at"), row.get("updated_at")
    body = row.get("body")
    if (not isinstance(user, dict) or user.get("type") != "User"
            or type(user.get("id")) is not int or user["id"] < 1
            or not isinstance(user.get("login"), str) or not user["login"]
            or not isinstance(created, str) or not created.endswith("Z")
            or created != updated or not isinstance(body, str)):
        raise VerificationReworkError("rework journal carrier is edited or not a human User comment")
    actual = (row.get("url"), row.get("issue_url"), row.get("html_url"))
    if any(not isinstance(a, str) or a.casefold() != e.casefold()
           for a, e in zip(actual, urls, strict=True)):
        raise VerificationReworkError("rework journal carrier has mismatched Issue origin")
    role = row.get("author_association")
    if role not in {"OWNER", "COLLABORATOR"}:
        raise VerificationReworkError("rework journal author is not the repository owner/collaborator")
    return comment_id, body, created, updated, user["id"], user["login"].casefold(), role, *actual


def _parse_record(row: dict[str, Any], repo: str, issue: int) -> ReworkRecord:
    comment_id, body, _created, _updated, actor_id, *_ = _fingerprint(row, repo, issue)
    schema = (INTENT_SCHEMA if body.startswith(f"<!-- {INTENT_SCHEMA}\n")
              else APPLIED_SCHEMA if body.startswith(f"<!-- {APPLIED_SCHEMA}\n") else None)
    if schema is None or not body.endswith("\n-->"):
        raise VerificationReworkError("unknown or malformed rework journal marker")
    raw = body[len(f"<!-- {schema}\n"):-len("\n-->")]
    try:
        value = json.loads(raw, object_pairs_hook=_unique_fields)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VerificationReworkError("rework journal contains malformed JSON") from exc
    if (not isinstance(value, dict) or _canonical(value) != raw
            or value.get("schema") != schema):
        raise VerificationReworkError("rework journal is noncanonical or has an unknown schema")
    common = {
        "schema", "repository", "repository_id", "issue_number", "issue_id",
        "adc_comment_id", "adc_sha256", "binding_sha256", "binding_generation",
        "pr_number", "pr_head_sha40", "pr_base_ref", "branch_ref",
        "phase_generation_comment_id", "phase_generation_sha256",
        "plan_sha256", "labels_before", "labels_after", "reason", "evidence_sha256",
        "evidence_type", "finding_id", "actor_id", "predecessor_comment_id",
        "predecessor_sha256",
    }
    expected = common | ({"created_at"} if schema == INTENT_SCHEMA
                         else {"intent_comment_id", "intent_sha256", "applied_at"})
    if set(value) != expected:
        raise VerificationReworkError("rework journal fields are missing or unknown")
    if (value.get("repository") != repo or value.get("issue_number") != issue
            or type(value.get("repository_id")) is not int or value["repository_id"] < 1
            or type(value.get("issue_id")) is not int or value["issue_id"] < 1
            or type(value.get("adc_comment_id")) is not int or value["adc_comment_id"] < 1
            or type(value.get("binding_generation")) is not int or value["binding_generation"] < 1
            or type(value.get("pr_number")) is not int or value["pr_number"] < 1
            or type(value.get("actor_id")) is not int or value["actor_id"] != actor_id
            or not isinstance(value.get("reason"), str)
            or not (1 <= len(value["reason"]) <= 500) or value["reason"].strip() != value["reason"]
            or not isinstance(value.get("finding_id"), str) or not value["finding_id"].strip()
            or value.get("evidence_type") not in {"independent_review_A", "verification_FAIL"}
            or not isinstance(value.get("branch_ref"), str) or not value["branch_ref"]
            or not isinstance(value.get("pr_base_ref"), str) or not value["pr_base_ref"]):
        raise VerificationReworkError("rework journal identity or reason is invalid")
    if (type(value.get("phase_generation_comment_id")) is not int
            or value["phase_generation_comment_id"] < 1):
        raise VerificationReworkError("current Phase generation ID is invalid")
    for key, pattern in (("adc_sha256", SHA256), ("binding_sha256", SHA256),
                         ("plan_sha256", SHA256),
                         ("phase_generation_sha256", SHA256),
                         ("pr_head_sha40", SHA40), ("evidence_sha256", SHA256)):
        if not isinstance(value.get(key), str) or pattern.fullmatch(value[key]) is None:
            raise VerificationReworkError(f"rework {key} is invalid")
    before, after = value.get("labels_before"), value.get("labels_after")
    if (not isinstance(before, list) or not isinstance(after, list)
            or any(not isinstance(x, str) or not x for x in before + after)
            or before != sorted(set(before)) or after != sorted(set(after))
            or before.count("phase:verification") != 1
            or any(x.startswith("phase:") and x != "phase:verification" for x in before)
            or any(x.startswith("attention:") for x in before)
            or sum(x in {"kind:single", "kind:child"} for x in before) != 1
            or after != sorted([x for x in before if x != "phase:verification"] + ["phase:execution"])):
        raise VerificationReworkError("rework labels are not an exact verification-to-execution replacement")
    prev_id, prev_sha = value.get("predecessor_comment_id"), value.get("predecessor_sha256")
    if (prev_id is None) != (prev_sha is None):
        raise VerificationReworkError("rework predecessor is partially specified")
    if prev_id is not None and (type(prev_id) is not int or prev_id < 1 or
                                not isinstance(prev_sha, str) or SHA256.fullmatch(prev_sha) is None):
        raise VerificationReworkError("rework predecessor identity is invalid")
    if schema == INTENT_SCHEMA:
        if not isinstance(value.get("created_at"), str) or not value["created_at"].endswith("Z"):
            raise VerificationReworkError("rework Intent creation time is invalid")
    else:
        if (type(value.get("intent_comment_id")) is not int or value["intent_comment_id"] < 1
                or not isinstance(value.get("intent_sha256"), str)
                or SHA256.fullmatch(value["intent_sha256"]) is None
                or not isinstance(value.get("applied_at"), str) or not value["applied_at"].endswith("Z")):
            raise VerificationReworkError("rework Applied linkage is invalid")
    return ReworkRecord(comment_id, schema, value, body, actor_id)


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationReworkError("rework journal has duplicate JSON keys")
        result[key] = value
    return result


def _repository_owner_id(github: GitHub) -> int:
    """Stable GitHub owner identity, independent of the current caller's token."""
    try:
        metadata = github.repository_metadata()
    except GitHubError as exc:
        raise VerificationReworkError("repository owner identity is unavailable") from exc
    owner = metadata.get("owner") if isinstance(metadata, dict) else None
    if (not isinstance(owner, dict) or owner.get("type") != "User"
            or type(owner.get("id")) is not int or owner["id"] < 1):
        raise VerificationReworkError("repository owner identity is invalid")
    return owner["id"]


def _trusted_rework_comment(row: dict[str, Any], owner_id: int) -> bool:
    """Use GitHub's recorded role at publication, not the current executor.

    OWNER must match the repository owner ID; COLLABORATOR identifies a
    repository-authorized participant. CONTRIBUTOR/NONE and arbitrary public
    Issue authors never own journal history.
    """
    user = row.get("user")
    if (not isinstance(user, dict) or user.get("type") != "User"
            or type(user.get("id")) is not int or user["id"] < 1):
        return False
    association = row.get("author_association")
    return (association == "OWNER" and user["id"] == owner_id
            or association == "COLLABORATOR")


def read_rework_history(github: GitHub, issue_number: int) -> tuple[ReworkRecord, ...]:
    """Two full list snapshots with direct reads for trusted journal carriers."""
    owner_id: int | None = None

    def selected() -> list[dict[str, Any]]:
        nonlocal owner_id
        rows = github.issue_comments(issue_number)
        candidates = [row for row in rows
                      if isinstance(row, dict) and isinstance(row.get("body"), str)
                      and row["body"].startswith(PREFIX)]
        if not candidates:
            return []
        if owner_id is None:
            owner_id = _repository_owner_id(github)
        return [row for row in candidates if _trusted_rework_comment(row, owner_id)]
    try:
        first = selected()
        ids = [row.get("id") for row in first]
        if (any(type(value) is not int or value < 1 for value in ids)
                or ids != sorted(ids) or len(ids) != len(set(ids))):
            raise VerificationReworkError("rework history IDs are invalid or duplicated")
        earlier = {comment_id: github.issue_comment(issue_number, comment_id) for comment_id in ids}
        second = selected()
        if [row.get("id") for row in second] != ids:
            raise VerificationReworkError("rework history changed during readback")
        later = {comment_id: github.issue_comment(issue_number, comment_id) for comment_id in ids}
        records: list[ReworkRecord] = []
        for row in second:
            cid = row["id"]
            f = _fingerprint(row, github.repo, issue_number)
            if (_fingerprint(earlier[cid], github.repo, issue_number) != f
                    or _fingerprint(later[cid], github.repo, issue_number) != f):
                raise VerificationReworkError("rework record was edited or moved during readback")
            records.append(_parse_record(row, github.repo, issue_number))
    except GitHubError as exc:
        raise VerificationReworkError("rework history is unavailable") from exc

    pending: ReworkRecord | None = None
    completed: ReworkRecord | None = None
    for record in records:
        if record.schema == INTENT_SCHEMA:
            if pending is not None:
                raise VerificationReworkError("a pending rework Intent was superseded")
            predecessor_id = completed.comment_id if completed else None
            predecessor_sha = completed.sha256 if completed else None
            if (record.payload["predecessor_comment_id"] != predecessor_id
                    or record.payload["predecessor_sha256"] != predecessor_sha):
                raise VerificationReworkError("rework journal predecessor chain is invalid")
            pending = record
        else:
            if pending is None or record.payload["intent_comment_id"] != pending.comment_id or (
                    record.payload["intent_sha256"] != pending.sha256):
                raise VerificationReworkError("orphan or mismatched rework Applied record")
            for key, value in pending.payload.items():
                if key not in {"schema", "created_at", "actor_id"} and record.payload.get(key) != value:
                    raise VerificationReworkError("rework Applied does not match its exact Intent")
            pending = None
            completed = record
    return tuple(records)


def _phase_generation(github: GitHub, subject: Any) -> tuple[int, str]:
    try:
        history = _validated_current_journal(
            github, subject, allow_pending_adc_comment_id=subject.verified_adc.pointer.comment_id,
        )
        comment_id, digest = _active_generation_before(history)
    except PhaseRestartError as exc:
        raise VerificationReworkError("current Phase generation history is invalid") from exc
    if (type(comment_id) is not int or comment_id < 1
            or not isinstance(digest, str) or SHA256.fullmatch(digest) is None):
        raise VerificationReworkError("verification correction requires a current committed Phase receipt")
    return comment_id, digest


def _post_once(github: GitHub, issue: int, schema: str, value: dict[str, Any]) -> ReworkRecord:
    expected = _body(schema, value)
    post_error = None
    created_id = None
    try:
        response = github.create_issue_comment(issue, expected)
        created_id = response.get("id") if isinstance(response, dict) else None
    except GitHubError as exc:
        post_error = exc
    records = read_rework_history(github, issue)
    matched = [row for row in records if row.schema == schema and row.body == expected]
    if len(matched) != 1 or (created_id is not None and created_id != matched[0].comment_id):
        raise VerificationReworkError(
            "ambiguous journal POST; readback could not prove one exact record; no retry"
        ) from post_error
    return matched[0]


def _require_review_not_started(github: GitHub, root: Path, issue: int, pr: int,
                                adc_sha256: str, comments: list[dict[str, Any]]) -> None:
    # Only canonical, GitHub-authenticated owner decisions can establish a
    # remote User Review boundary. Outsider marker comments are ordinary prose.
    owner_id: int | None = None
    for row in comments:
        body = row.get("body") if isinstance(row, dict) else None
        if not has_user_review_decision_marker(body):
            continue
        if owner_id is None:
            owner_id = _repository_owner_id(github)
        author = row.get("user") if isinstance(row, dict) else None
        if (not isinstance(author, dict) or author.get("id") != owner_id
                or author.get("type") != "User"):
            continue
        try:
            identity = _review_decision_identity(row, github.repo, issue, owner_id)
            direct = github.issue_comment(issue, identity[0])
            if _review_decision_identity(direct, github.repo, issue, owner_id) != identity:
                raise VerificationReworkError("User Review decision changed during readback")
            decision = parse_user_review_decision(body)
        except (GitHubError, UserReviewRelayError) as exc:
            raise VerificationReworkError("trusted User Review decision is invalid or unreadable") from exc
        if (decision["issue_number"] == issue and decision["pr_number"] == pr
                and decision["adc_sha256"] == adc_sha256):
            raise VerificationReworkError(
                "User Review decision already exists; use exact CHANGES_REQUESTED lifecycle"
            )
    directory = root / ".p_ases" / "user-review" / str(issue)
    if path_has_symlink(directory):
        raise VerificationReworkError("User Review directory traverses a symbolic link")
    if not directory.exists():
        return
    try:
        paths = sorted(directory.glob("*/session.json"))
    except OSError as exc:
        raise VerificationReworkError("User Review session history is unreadable") from exc
    for path in paths:
        try:
            session = read_review_session(path)
        except UserReviewError as exc:
            raise VerificationReworkError("User Review session history is malformed") from exc
        subject = session.subject.verification_subject
        if subject.pr_number == pr and subject.adc_sha256 == adc_sha256:
            raise VerificationReworkError(
                "User Review has started for this ADC and PR; use exact CHANGES_REQUESTED"
            )


def _evidence(path: Path, *, root: Path, repository: str, issue: int, pr: int, head: str,
              adc_comment_id: int, adc_sha256: str, plan_sha256: str,
              finding_id: str, github: GitHub | None = None,
              plan_path: Path | None = None) -> tuple[str, str]:
    location = Path(path).absolute()
    if (not location.is_relative_to(root) or path_has_symlink(location)
            or not location.is_file()):
        raise VerificationReworkError("rework evidence must be a regular file under the bound worktree")
    try:
        data = location.read_bytes()
        schema = json.loads(data.decode("utf-8")).get("schema")
        if schema == "PASES_INDEPENDENT_REVIEW_V3":
            review = read_independent_review(location)
            if not isinstance(review, IndependentReviewV3) or review.verdict != "FAIL":
                raise VerificationReworkError("rework requires a failing V3 independent review")
            matching = [row for row in review.findings
                        if row.finding_id == finding_id and row.severity == "A" and not row.resolved]
            if len(matching) != 1:
                raise VerificationReworkError("rework requires one unresolved A finding")
            identity = review.subject
            evidence_type = "independent_review_A"
        elif schema == "PASES_VERIFICATION_RESULT_V1":
            verification = VerificationResult.from_bytes(data)
            if verification.status != "FAIL" or finding_id != "mandatory-check":
                raise VerificationReworkError("rework requires a failing mandatory Verification result")
            if github is None or plan_path is None:
                raise VerificationReworkError("mandatory-check rework requires live verification authority")
            # Canonical FAIL JSON alone is insufficient: recompute actual
            # mandatory Evidence and trusted Check Runs at this exact HEAD.
            import argparse
            from .cli import CLIError, _calculate_verification
            try:
                observed, _refs = _calculate_verification(
                    argparse.Namespace(issue=issue, pr=pr, head=head, plan=plan_path),
                    repository, root, github,
                )
            except (ADCError, CLIError, GitError, GitHubError, PlanError,
                    VerificationError, OSError, ValueError) as exc:
                raise VerificationReworkError("current mandatory Verification cannot be independently reproduced") from exc
            if observed != verification or observed.status != "FAIL":
                raise VerificationReworkError("failing receipt is not the live mandatory Verification result")
            identity = verification.subject
            evidence_type = "verification_FAIL"
        else:
            raise VerificationReworkError("rework evidence schema is unsupported")
    except (OSError, UnicodeError, json.JSONDecodeError, AuditError, VerificationError) as exc:
        raise VerificationReworkError("rework evidence is malformed or unreadable") from exc
    if (identity.repository != repository or identity.issue_number != issue
            or identity.pr_number != pr or identity.pr_head_sha40 != head
            or identity.adc_comment_id != adc_comment_id
            or identity.adc_sha256 != adc_sha256 or identity.plan_sha256 != plan_sha256):
        raise VerificationReworkError("rework evidence does not match the current ADC/PR/HEAD")
    return evidence_type, hashlib.sha256(data).hexdigest()


def _refresh(github: GitHub, subject: Any, pr_number: int) -> tuple[str, ...]:
    # Fresh PR check before any mutation, not only when the command starts.
    pr = github.pull_request(pr_number)
    head, base = pr.get("head"), pr.get("base")
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    if (pr.get("number") != pr_number or pr.get("state") != "open" or pr.get("draft") is not False
            or pr.get("merged") is True or not isinstance(head, dict)
            or head.get("sha") != subject.head_sha40 or head.get("ref") != subject.branch_ref
            or not isinstance(head_repo, dict) or head_repo.get("full_name") != subject.repository
            or not isinstance(base, dict) or base.get("ref") != subject.binding.base_ref
            or not isinstance(base_repo, dict) or base_repo.get("full_name") != subject.repository):
        raise VerificationReworkError("current PR identity/base/head/branch is stale or mismatched")
    try:
        if parse_issue_association(pr.get("body"), subject.issue_number) != "auto_close":
            raise VerificationReworkError("ordinary rework requires one auto-closing Issue PR")
    except WorkError as exc:
        raise VerificationReworkError("rework PR association is invalid") from exc
    issue = github.issue(subject.issue_number)
    rows = issue.get("labels")
    if (issue.get("number") != subject.issue_number or issue.get("id") != subject.issue_id
            or issue.get("state") != "open" or issue.get("body") != subject.issue.get("body")
            or not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows)):
        raise VerificationReworkError("live rework Issue identity changed")
    labels = [row.get("name") for row in rows]
    if any(not isinstance(x, str) or not x for x in labels) or len(set(labels)) != len(labels):
        raise VerificationReworkError("rework labels are malformed")
    return tuple(sorted(labels))


def _applied(intent: ReworkRecord, *, executor_user_id: int) -> dict[str, Any]:
    result = {key: value for key, value in intent.payload.items() if key not in {"schema", "created_at"}}
    # A currently authorized collaborator may finish an interrupted previous
    # executor's label update. Both immutable comments retain their actual
    # GitHub-authenticated author identities.
    return {**result, "schema": APPLIED_SCHEMA, "actor_id": executor_user_id,
            "intent_comment_id": intent.comment_id,
            "intent_sha256": intent.sha256, "applied_at": _time()}


def _current_plan(root: Path, path: Path, subject: Any) -> str:
    """Use the same frozen Plan/Oracle/Test gate as ordinary Verification."""
    location = Path(path).absolute()
    if (not location.is_relative_to(root) or path_has_symlink(location)
            or not location.is_file()):
        raise VerificationReworkError("Verification Plan must be a regular file under the current worktree")
    # CLI owns normative requirement coverage, Oracle/Test trace, and
    # canonical frozen Plan path validation. Import lazily to avoid a cycle.
    from .cli import CLIError, _load_plan, _plans_root
    try:
        plan = read_plan(location.read_bytes())
        expected = _plans_root(root, subject.issue_number) / f"{plan.sha256}.json"
        if location != expected:
            raise VerificationReworkError("Verification Plan is not the canonical frozen Issue Plan")
        checked, _required, _oracles, _tests = _load_plan(
            root, subject.repository, subject.issue_number, location, subject.verified_adc,
        )
        if checked != plan:
            raise VerificationReworkError("frozen Verification Plan changed during validation")
    except (OSError, PlanError, CLIError) as exc:
        raise VerificationReworkError("current Verification Plan/Oracle/Test coverage is invalid") from exc
    return plan.sha256


def verification_rework(
    github: GitHub, root: Path, issue_number: int, pr_number: int,
    evidence: Path, finding_id: str, reason: str, plan_path: Path,
) -> dict[str, Any]:
    """Perform a bounded, resumable verification->execution correction."""
    root = Path(root).resolve()
    if (type(issue_number) is not int or issue_number < 1
            or type(pr_number) is not int or pr_number < 1
            or not isinstance(finding_id, str) or not finding_id.strip()
            or not isinstance(reason, str) or reason != reason.strip()
            or not (1 <= len(reason) <= 500)):
        raise VerificationReworkError("rework requires a bounded typed finding and reason")
    try:
        subject = _live_subject(github, root, issue_number, require_execution_phase=False)
        if parse_attention_labels(subject.labels):
            raise VerificationReworkError("attention state blocks rework")
        labels = _refresh(github, subject, pr_number)
        history = read_rework_history(github, issue_number)
        comments = github.issue_comments(issue_number)
    except (PhaseRestartError, PhaseError, GitHubError) as exc:
        raise VerificationReworkError(str(exc)) from exc
    plan_sha256 = _current_plan(root, plan_path, subject)
    last = history[-1] if history else None
    current_adc = subject.verified_adc.pointer.comment_id
    cycles = sum(row.schema == APPLIED_SCHEMA and row.payload["adc_comment_id"] == current_adc
                 for row in history)
    if last is not None and last.schema == APPLIED_SCHEMA and (
            last.payload["adc_comment_id"] == current_adc and
            last.payload["pr_head_sha40"] == subject.head_sha40 and
            labels == tuple(last.payload["labels_after"])):
        return {"status": "NOOP", "issue": issue_number, "label_write_count": 0,
                "applied_comment_id": last.comment_id, "rework_cycle": cycles}
    if last is not None and last.schema == INTENT_SCHEMA:
        intent = last
        if (intent.payload["adc_comment_id"] != current_adc
                or intent.payload["binding_sha256"] != subject.binding_sha256
                or intent.payload["plan_sha256"] != plan_sha256
                or intent.payload["pr_head_sha40"] != subject.head_sha40
                or intent.payload["pr_number"] != pr_number
                or intent.payload["finding_id"] != finding_id or intent.payload["reason"] != reason):
            raise VerificationReworkError("pending rework Intent does not match the current immutable subject")
        if labels == tuple(intent.payload["labels_before"]):
            raise VerificationReworkError(
                "rework Intent is pending before the label write; no blind retry is allowed"
            )
        if labels != tuple(intent.payload["labels_after"]):
            raise VerificationReworkError("pending rework label state is ambiguous")
        if _current_plan(root, plan_path, subject) != plan_sha256:
            raise VerificationReworkError("pending rework Plan changed before Applied recovery")
        _require_review_not_started(
            github, root, issue_number, pr_number, subject.verified_adc.contract.sha256, comments,
        )
        if _phase_generation(github, subject) != (
                intent.payload["phase_generation_comment_id"],
                intent.payload["phase_generation_sha256"]):
            raise VerificationReworkError("pending rework Phase generation has changed")
        evidence_type, evidence_sha256 = _evidence(
            evidence, root=root, repository=subject.repository, issue=issue_number,
            pr=pr_number, head=subject.head_sha40, adc_comment_id=current_adc,
            adc_sha256=subject.verified_adc.contract.sha256,
            plan_sha256=plan_sha256, finding_id=finding_id,
            github=github, plan_path=plan_path,
        )
        if (evidence_type != intent.payload["evidence_type"]
                or evidence_sha256 != intent.payload["evidence_sha256"]):
            raise VerificationReworkError("pending rework failing evidence has changed")
        record = _post_once(github, issue_number, APPLIED_SCHEMA, _applied(intent, executor_user_id=subject.executor_user_id))
        return {"status": "RECOVERED", "issue": issue_number, "label_write_count": 0,
                "intent_comment_id": intent.comment_id,
                "applied_comment_id": record.comment_id, "rework_cycle": cycles + 1}
    if parse_phase_labels(labels) is not Phase.VERIFICATION:
        raise VerificationReworkError("rework is permitted only from phase:verification")
    if labels != subject.labels:
        raise VerificationReworkError("Issue labels drifted during rework preflight")
    if cycles >= MAX_CYCLES:
        raise VerificationReworkError("BLOCKED_REWORK_LIMIT: three corrections per ADC generation")
    if any(row.schema == APPLIED_SCHEMA and row.payload["adc_comment_id"] == current_adc
           and row.payload["pr_head_sha40"] == subject.head_sha40 for row in history):
        raise VerificationReworkError("BLOCKED_REWORK_NO_PROGRESS: this HEAD already had a correction")
    _require_review_not_started(github, root, issue_number, pr_number, subject.verified_adc.contract.sha256, comments)
    phase_comment_id, phase_sha256 = _phase_generation(github, subject)
    evidence_type, evidence_sha256 = _evidence(
        evidence, root=root, repository=subject.repository, issue=issue_number,
        pr=pr_number, head=subject.head_sha40, adc_comment_id=current_adc,
        adc_sha256=subject.verified_adc.contract.sha256,
        plan_sha256=plan_sha256, finding_id=finding_id,
        github=github, plan_path=plan_path,
    )
    prev = next((row for row in reversed(history) if row.schema == APPLIED_SCHEMA), None)
    after_labels = sorted([x for x in labels if x != "phase:verification"] + ["phase:execution"])
    payload = {
        "schema": INTENT_SCHEMA, "repository": subject.repository,
        "repository_id": subject.repository_id, "issue_number": issue_number,
        "issue_id": subject.issue_id, "adc_comment_id": current_adc,
        "adc_sha256": subject.verified_adc.contract.sha256,
        "binding_generation": subject.binding_generation, "binding_sha256": subject.binding_sha256,
        "pr_number": pr_number, "pr_head_sha40": subject.head_sha40,
        "pr_base_ref": subject.binding.base_ref, "branch_ref": subject.branch_ref,
        "phase_generation_comment_id": phase_comment_id, "phase_generation_sha256": phase_sha256,
        "plan_sha256": plan_sha256, "labels_before": list(labels), "labels_after": after_labels,
        "reason": reason, "evidence_sha256": evidence_sha256,
        "evidence_type": evidence_type, "finding_id": finding_id,
        "actor_id": subject.executor_user_id,
        "predecessor_comment_id": prev.comment_id if prev else None,
        "predecessor_sha256": prev.sha256 if prev else None,
        "created_at": _time(),
    }
    # Use the exact same parser as readback before any network write.
    _parse_record({
        "id": 1, "body": _body(INTENT_SCHEMA, payload),
        "user": {"id": subject.executor_user_id, "login": "validated-user", "type": "User"},
        "author_association": ("OWNER" if subject.executor_user_id == _repository_owner_id(github)
                               else "COLLABORATOR"),
        "created_at": payload["created_at"], "updated_at": payload["created_at"],
        "url": f"https://api.github.com/repos/{subject.repository}/issues/comments/1",
        "issue_url": f"https://api.github.com/repos/{subject.repository}/issues/{issue_number}",
        "html_url": f"https://github.com/{subject.repository}/issues/{issue_number}#issuecomment-1",
    }, subject.repository, issue_number)
    intent = _post_once(github, issue_number, INTENT_SCHEMA, payload)
    # Re-check every mutable subject and the unique journal before the only PUT.
    try:
        current = _live_subject(github, root, issue_number, require_execution_phase=False)
        current_labels = _refresh(github, current, pr_number)
        current_history = read_rework_history(github, issue_number)
    except (PhaseRestartError, GitHubError) as exc:
        raise VerificationReworkError(str(exc)) from exc
    if (current.verified_adc.pointer != subject.verified_adc.pointer
            or current.binding_sha256 != subject.binding_sha256
            or current_labels != labels or current_labels != current.labels
            or not current_history or current_history[-1].body != intent.body
            or current_history[-1].comment_id != intent.comment_id):
        raise VerificationReworkError("rework subject changed before the label write")
    if _phase_generation(github, current) != (phase_comment_id, phase_sha256):
        raise VerificationReworkError("active Phase generation changed after the Intent")
    if _current_plan(root, plan_path, current) != plan_sha256:
        raise VerificationReworkError("Verification Plan or normative sources changed after the Intent")
    _require_review_not_started(
        github, root, issue_number, pr_number, subject.verified_adc.contract.sha256,
        github.issue_comments(issue_number),
    )
    latest_type, latest_digest = _evidence(
        evidence, root=root, repository=subject.repository, issue=issue_number,
        pr=pr_number, head=subject.head_sha40, adc_comment_id=current_adc,
        adc_sha256=subject.verified_adc.contract.sha256,
        plan_sha256=plan_sha256, finding_id=finding_id,
        github=github, plan_path=plan_path,
    )
    if (latest_type, latest_digest) != (evidence_type, evidence_sha256):
        raise VerificationReworkError("failing evidence changed after the Intent")
    write_error = None
    try:
        github.replace_issue_labels(issue_number, after_labels)
    except GitHubError as exc:
        write_error = exc
    latest = _refresh(github, current, pr_number)
    if latest != tuple(after_labels):
        reason_text = "ambiguous PUT response" if write_error else "label PUT readback differs"
        raise VerificationReworkError(reason_text + "; no label retry was attempted")
    after = _live_subject(github, root, issue_number, require_execution_phase=False)
    if (after.verified_adc.pointer != subject.verified_adc.pointer
            or after.binding_sha256 != subject.binding_sha256
            or after.labels != latest):
        raise VerificationReworkError("rework subject changed after the label write")
    record = _post_once(github, issue_number, APPLIED_SCHEMA, _applied(intent, executor_user_id=subject.executor_user_id))
    return {"status": "APPLIED", "issue": issue_number, "label_write_count": 1,
            "intent_comment_id": intent.comment_id, "applied_comment_id": record.comment_id,
            "rework_cycle": cycles + 1}


def require_rework_progress(github: GitHub, root: Path, issue_number: int,
                            *, current_head: str, adc_comment_id: int) -> None:
    """Forbid same-HEAD execution->verification after a committed correction."""
    history = read_rework_history(github, issue_number)
    active = [row for row in history if row.payload["adc_comment_id"] == adc_comment_id]
    if active and active[-1].schema == INTENT_SCHEMA:
        raise VerificationReworkError(
            "BLOCKED_REWORK_PENDING: incomplete Intent must be recovered before verification"
        )
    previous = next((row for row in reversed(active) if row.schema == APPLIED_SCHEMA), None)
    if previous is None:
        return
    old_head = previous.payload["pr_head_sha40"]
    if current_head == old_head:
        raise VerificationReworkError("BLOCKED_REWORK_NO_PROGRESS: no new commit since verification rework")
    try:
        if not is_ancestor(Path(root), old_head, current_head):
            raise VerificationReworkError("rework HEAD is not a descendant of the correction subject")
    except GitError as exc:
        raise VerificationReworkError("rework commit ancestry cannot be verified") from exc
