"""Exact-plan, approval-bound management of the P-ASES repository Ruleset."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .branch_policy import EffectiveBranchPolicy, assess_branch_policy
from .git import GitError, discover_repository, head_sha40, worktree_clean
from .github import GitHub, GitHubError
from .profile import ProfileError, load_profile


class RulesetManagementError(ValueError):
    pass


RULESET_NAME = "P-ASES Final Delivery (managed)"
ACTIVATION_ISSUE = 57
APPLIED_MARKER = "<!-- PASES_RULESET_APPLIED_V1\n"
PLAN_SCHEMA = "PASES_RULESET_PLAN_V1"
PLAN_FIELDS = {
    "activation_issue_number", "blockers", "default_branch", "default_branch_sha40", "diff",
    "existing_ruleset_id", "existing_ruleset_sha256", "owner_id", "plan_schema", "policy_evidence",
    "policy_proof", "profile_review_mode", "profile_sha256", "repository", "repository_id",
    "required_checks", "desired_ruleset", "existing_pr_impact", "plan_sha256",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise RulesetManagementError(f"{label} must be a lowercase SHA-256")
    return value


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise RulesetManagementError(f"{label} must be a positive integer")
    return value


def _managed_body(value: dict[str, Any]) -> dict[str, Any]:
    """Project an API response or request onto the exact mutable ruleset body."""
    keys = ("name", "target", "enforcement", "conditions", "rules", "bypass_actors")
    if any(key not in value for key in keys):
        raise RulesetManagementError("managed Ruleset body is incomplete")
    body = {key: value[key] for key in keys}
    if (body["name"] != RULESET_NAME or body["target"] != "branch"
            or body["enforcement"] != "active" or not isinstance(body["conditions"], dict)
            or not isinstance(body["rules"], list) or not isinstance(body["bypass_actors"], list)):
        raise RulesetManagementError("managed Ruleset body has an invalid shape")
    normalized_rules: list[dict[str, Any]] = []
    for row in body["rules"]:
        if not isinstance(row, dict) or not isinstance(row.get("type"), str):
            raise RulesetManagementError("managed Ruleset contains a malformed rule")
        normalized = dict(row)
        if row["type"] == "non_fast_forward" and normalized.get("parameters") == {}:
            normalized.pop("parameters")
        if row["type"] == "required_status_checks" and isinstance(normalized.get("parameters"), dict):
            params = dict(normalized["parameters"])
            checks = params.get("required_status_checks")
            if isinstance(checks, list):
                params["required_status_checks"] = sorted(
                    checks, key=lambda check: (check.get("context", ""), check.get("integration_id", 0))
                    if isinstance(check, dict) else ("", 0)
                )
            normalized["parameters"] = params
        normalized_rules.append(normalized)
    body["rules"] = sorted(normalized_rules, key=lambda row: row["type"])
    return body


def _body_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(_managed_body(value))).hexdigest()


def _desired_payload(repository: str, checks: tuple[tuple[str, int], ...]) -> dict[str, Any]:
    if not checks or len({name for name, _app in checks}) != len(checks):
        raise RulesetManagementError("trusted Required Checks are empty or duplicated")
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "pull_request", "parameters": {
                "required_approving_review_count": 0,
                "dismiss_stale_reviews_on_push": False,
                "require_code_owner_review": False,
                "require_last_push_approval": False,
                "required_review_thread_resolution": True,
                "allowed_merge_methods": ["merge", "squash", "rebase"],
            }},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": False,
                "required_status_checks": [
                    {"context": name, "integration_id": app_id} for name, app_id in sorted(checks)
                ],
            }},
            {"type": "non_fast_forward"},
        ],
        "bypass_actors": [],
    }


def _comments_for_marker(github: GitHub, issue_number: int) -> list[dict[str, Any]]:
    return [row for row in github.issue_comments(issue_number)
            if isinstance(row, dict) and isinstance(row.get("body"), str)
            and row["body"].startswith(APPLIED_MARKER)]


def _decode_record(body: Any) -> dict[str, Any]:
    if not isinstance(body, str) or not body.startswith(APPLIED_MARKER):
        raise RulesetManagementError("Ruleset ownership record marker is invalid")
    end = body.find("\n-->", len(APPLIED_MARKER))
    if end < 0 or end + 4 != len(body):
        raise RulesetManagementError("Ruleset ownership record envelope is invalid")
    raw = body[len(APPLIED_MARKER):end]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RulesetManagementError("Ruleset ownership record JSON is invalid") from exc
    if not isinstance(payload, dict) or _canonical(payload).decode("utf-8") != raw:
        raise RulesetManagementError("Ruleset ownership record is not canonical")
    expected = {
        "actor_id", "actor_login", "approval_comment_id", "plan_sha256", "predecessor_comment_id",
        "effective_policy_sha256", "repository", "repository_id", "ruleset_body_sha256", "ruleset_id", "schema",
    }
    if set(payload) != expected or payload.get("schema") != "PASES_RULESET_APPLIED_V1":
        raise RulesetManagementError("Ruleset ownership record has unknown or missing fields")
    _positive(payload.get("actor_id"), "Ruleset apply actor ID")
    _positive(payload.get("approval_comment_id"), "Ruleset approval comment ID")
    _positive(payload.get("repository_id"), "Ruleset repository ID")
    _positive(payload.get("ruleset_id"), "managed Ruleset ID")
    _sha(payload.get("plan_sha256"), "Ruleset plan digest")
    _sha(payload.get("ruleset_body_sha256"), "managed Ruleset body digest")
    _sha(payload.get("effective_policy_sha256"), "effective policy digest")
    if (not isinstance(payload.get("repository"), str) or not REPOSITORY.fullmatch(payload["repository"])
            or not isinstance(payload.get("actor_login"), str) or not payload["actor_login"]
            or (payload.get("predecessor_comment_id") is not None
                and (type(payload["predecessor_comment_id"]) is not int
                     or payload["predecessor_comment_id"] < 1))):
        raise RulesetManagementError("Ruleset ownership record identity is invalid")
    return payload


def _read_ownership_history(github: GitHub, repository_id: int, owner_id: int) -> list[tuple[int, dict[str, Any]]]:
    listed = _comments_for_marker(github, ACTIVATION_ISSUE)
    all_comments = github.issue_comments(ACTIVATION_ISSUE)
    listed.sort(key=lambda row: row.get("id", 0))
    ids = [row.get("id") for row in listed]
    if (any(type(value) is not int or value < 1 for value in ids) or len(ids) != len(set(ids))):
        raise RulesetManagementError("Ruleset ownership comments contain invalid or duplicate IDs")
    result: list[tuple[int, dict[str, Any]]] = []
    predecessor: int | None = None
    seen: set[tuple[int, str]] = set()
    for row in listed:
        comment_id = row["id"]
        first = github.issue_comment(ACTIVATION_ISSUE, comment_id)
        second_list = _comments_for_marker(github, ACTIVATION_ISSUE)
        second_matches = [item for item in second_list if item.get("id") == comment_id]
        final = github.issue_comment(ACTIVATION_ISSUE, comment_id)
        expected_issue_url = f"https://api.github.com/repos/{github.repo}/issues/{ACTIVATION_ISSUE}"
        if (len(second_matches) != 1 or first.get("id") != comment_id or final.get("id") != comment_id
                or first.get("body") != row.get("body")
                or second_matches[0].get("body") != row.get("body")
                or final.get("body") != first.get("body")
                or final.get("html_url") != row.get("html_url")
                or not isinstance(final.get("issue_url"), str)
                or final["issue_url"].casefold() != expected_issue_url.casefold()
                or final.get("created_at") != row.get("created_at")
                or final.get("updated_at") != final.get("created_at")):
            raise RulesetManagementError("Ruleset ownership evidence changed during direct/list/direct readback")
        payload = _decode_record(final.get("body"))
        approval_id = payload["approval_comment_id"]
        expected_approval = (f"PASES-RULESET-APPROVE: {payload['plan_sha256']}\n"
                             f"PASES-REPOSITORY: {github.repo}")
        approval_listed = [item for item in all_comments if item.get("id") == approval_id]
        approval_first = github.issue_comment(ACTIVATION_ISSUE, approval_id)
        approval_final_list = github.issue_comments(ACTIVATION_ISSUE)
        approval_listed_again = [item for item in approval_final_list if item.get("id") == approval_id]
        approval_final = github.issue_comment(ACTIVATION_ISSUE, approval_id)
        approval_user = approval_final.get("user") if isinstance(approval_final.get("user"), dict) else {}
        if (approval_id >= comment_id or len(approval_listed) != 1 or len(approval_listed_again) != 1
                or approval_first.get("id") != approval_id or approval_final.get("id") != approval_id
                or approval_first.get("body") != expected_approval
                or approval_final.get("body") != expected_approval
                or approval_listed[0].get("body") != expected_approval
                or approval_final.get("html_url") != approval_listed_again[0].get("html_url")
                or approval_final.get("html_url") != approval_listed[0].get("html_url")
                or approval_final.get("created_at") != approval_listed_again[0].get("created_at")
                or approval_final.get("created_at") != approval_listed[0].get("created_at")
                or approval_listed_again[0].get("body") != expected_approval
                or not isinstance(approval_final.get("issue_url"), str)
                or approval_final.get("updated_at") != approval_final.get("created_at")
                or approval_user.get("id") != owner_id or approval_user.get("type") != "User"
                or approval_final.get("issue_url", "").casefold()
                != f"https://api.github.com/repos/{github.repo}/issues/{ACTIVATION_ISSUE}".casefold()):
            raise RulesetManagementError("Ruleset apply record does not name one exact owner approval comment")
        user = final.get("user")
        if (not isinstance(user, dict) or user.get("type") != "User"
                or type(user.get("id")) is not int or not isinstance(user.get("login"), str)
                or payload["actor_id"] != user["id"]
                or payload["actor_login"].casefold() != user["login"].casefold()
                or payload["actor_id"] != owner_id
                or payload["repository_id"] != repository_id
                or payload["repository"].casefold() != github.repo.casefold()
                or payload["predecessor_comment_id"] != predecessor
                or (payload["ruleset_id"], payload["ruleset_body_sha256"]) in seen):
            raise RulesetManagementError("Ruleset ownership evidence chain is invalid")
        predecessor = comment_id
        seen.add((payload["ruleset_id"], payload["ruleset_body_sha256"]))
        result.append((comment_id, payload))
    final_list = _comments_for_marker(github, ACTIVATION_ISSUE)
    if [row.get("id") for row in final_list] != [row.get("id") for row in listed]:
        raise RulesetManagementError("Ruleset ownership history changed during readback")
    return result


def _read_policy(github: GitHub, repository: str, branch: str, review_mode: str,
                 checks: tuple[tuple[str, int], ...], default_branch: str
                 ) -> tuple[EffectiveBranchPolicy, dict[str, Any]]:
    errors: dict[str, int | None] = {}
    branch_info: dict[str, Any] | None = None
    legacy: dict[str, Any] | None = None
    effective: list[dict[str, Any]] | None = None
    details: list[dict[str, Any]] | None = None
    try:
        branch_info = github.branch(branch)
    except GitHubError as exc:
        errors["branch"] = exc.status_code
    try:
        legacy = github.branch_protection(branch)
    except GitHubError as exc:
        errors["legacy_protection"] = exc.status_code
    try:
        effective = github.effective_branch_rules(branch)
    except GitHubError as exc:
        errors["effective_rules"] = exc.status_code
    if effective is not None:
        details = []
        seen: set[int] = set()
        for row in effective:
            ruleset_id = row.get("ruleset_id")
            source_type = row.get("ruleset_source_type", row.get("source_type"))
            if type(ruleset_id) is not int or ruleset_id < 1 or ruleset_id in seen:
                errors["ruleset_details"] = None
                continue
            seen.add(ruleset_id)
            try:
                details.append(github.ruleset_details(ruleset_id, source_type=source_type))
            except GitHubError as exc:
                errors["ruleset_details"] = exc.status_code
    policy = assess_branch_policy(
        repository=repository, branch=branch, review_mode=review_mode,
        required_check_policy=_required_policy(checks), branch_info=branch_info,
        legacy_protection=legacy, effective_rules=effective, ruleset_details=details,
        source_errors=errors, default_branch=default_branch,
    )
    evidence = {
        "branch": branch_info,
        "effective_rules": effective,
        "legacy_protection": legacy,
        "ruleset_details": details,
        "source_errors": dict(sorted(errors.items())),
    }
    return policy, evidence


def _required_policy(checks: tuple[tuple[str, int], Any] | tuple[tuple[str, int], ...]) -> Any:
    from .verification import RequiredCheckPolicy
    return RequiredCheckPolicy(tuple(checks)).validate()


def _existing_pr_impact(github: GitHub, default_branch: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in github.pull_requests_all():
        base = row.get("base") if isinstance(row.get("base"), dict) else {}
        head = row.get("head") if isinstance(row.get("head"), dict) else {}
        head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
        if row.get("state") == "open" and base.get("ref") == default_branch:
            result.append({
                "base_ref": default_branch,
                "draft": row.get("draft"),
                "head_ref": head.get("ref"),
                "head_repository": head_repo.get("full_name"),
                "head_sha": head.get("sha"),
                "number": row.get("number"),
                "title": row.get("title"),
            })
    result.sort(key=lambda row: row["number"] if type(row["number"]) is int else 0)
    return result


def build_ruleset_plan(root: Path, github: GitHub) -> dict[str, Any]:
    """Read a canonical current-state plan. This function never mutates GitHub."""
    root = Path(root).resolve()
    blockers: list[str] = []
    if not worktree_clean(root):
        raise RulesetManagementError("Ruleset planning requires a clean worktree")
    try:
        if discover_repository(root).casefold() != github.repo.casefold():
            raise RulesetManagementError("GitHub repository does not match the active workspace origin")
        profile = load_profile(root)
    except (GitError, ProfileError) as exc:
        raise RulesetManagementError(f"Ruleset planning requires the valid active project profile: {exc}") from exc
    if profile.activation_issue_number != ACTIVATION_ISSUE:
        blockers.append("ACTIVATION_LOCATOR_MISMATCH")
    if profile.final_delivery_review_mode != "solo_owner":
        blockers.append("REVIEW_MODE_MUST_BE_EXPLICIT_SOLO_OWNER")
    if not profile.required_checks or any(app_id is None for _, app_id in profile.required_checks):
        blockers.append("TRUSTED_REQUIRED_CHECKS_MISSING")
    checks = tuple((name, app_id) for name, app_id in profile.required_checks if app_id is not None)
    if blockers and not checks:
        checks = ()

    try:
        local_sha = head_sha40(root)
        committed_profile = github.regular_content_at_ref(".agent/project.json", local_sha)
        local_profile = (root / ".agent" / "project.json").read_bytes()
        if committed_profile != local_profile:
            blockers.append("PROFILE_DIFFERS_FROM_COMMITTED_TREE")
        profile_sha = hashlib.sha256(committed_profile).hexdigest()
    except (GitError, GitHubError, OSError) as exc:
        raise RulesetManagementError(f"committed project profile could not be bound: {exc}") from exc

    metadata = github.repository_metadata()
    repository_id = _positive(metadata.get("id"), "repository ID")
    owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
    owner_id = _positive(owner.get("id"), "repository owner ID")
    default_branch = metadata.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise RulesetManagementError("repository default branch is unavailable")
    desired = _desired_payload(github.repo, checks) if checks else None

    try:
        inventory = github.repository_rulesets()
    except GitHubError as exc:
        blockers.append("REPOSITORY_RULESET_INVENTORY_UNAVAILABLE")
        inventory = []
    named = [row for row in inventory if row.get("name") == RULESET_NAME]
    if len(named) > 1:
        blockers.append("MANAGED_RULESET_NAME_COLLISION")
    existing_detail: dict[str, Any] | None = None
    existing_id: int | None = None
    if len(named) == 1:
        existing_id = _positive(named[0].get("id"), "managed Ruleset ID")
        try:
            existing_detail = github.ruleset_details(existing_id, source_type="Repository")
        except GitHubError:
            blockers.append("MANAGED_RULESET_DETAIL_UNAVAILABLE")
    existing_digest = _body_digest(existing_detail) if existing_detail is not None else None
    history = _read_ownership_history(github, repository_id, owner_id)
    last_owner_record = history[-1] if history else None
    if existing_id is not None:
        if last_owner_record is None:
            blockers.append("MANAGED_RULESET_HAS_NO_OWNERSHIP_EVIDENCE")
        elif (last_owner_record[1]["ruleset_id"] != existing_id
              or last_owner_record[1]["ruleset_body_sha256"] != existing_digest):
            blockers.append("MANAGED_RULESET_OWNERSHIP_DIGEST_MISMATCH")
    elif last_owner_record is not None:
        blockers.append("OWNERSHIP_RECORD_REFERENCES_MISSING_RULESET")

    try:
        policy, policy_evidence = _read_policy(
            github, github.repo, default_branch, profile.final_delivery_review_mode,
            checks, default_branch,
        ) if checks else (None, {})
    except (GitHubError, ValueError) as exc:
        blockers.append("CURRENT_BRANCH_POLICY_READBACK_INCOMPLETE")
        policy, policy_evidence = None, {"error": str(exc)}
    if isinstance(policy, EffectiveBranchPolicy):
        if policy.status not in {"NOT_CONFIGURED", "VERIFIED"}:
            blockers.append("CURRENT_BRANCH_POLICY_READBACK_INCOMPLETE")
        if any(status != 404 for _source, status in policy.source_errors):
            # In particular, 403 is an authorization failure, never evidence that a
            # ruleset or branch protection setting is absent.
            blockers.append("CURRENT_BRANCH_POLICY_READBACK_INCOMPLETE")
    try:
        pr_impact = _existing_pr_impact(github, default_branch)
    except GitHubError as exc:
        blockers.append("OPEN_PULL_REQUEST_IMPACT_READBACK_UNAVAILABLE")
        pr_impact = []
    current_branch = policy_evidence.get("branch") if isinstance(policy_evidence, dict) else None
    default_branch_sha = (current_branch.get("commit", {}).get("sha")
                          if isinstance(current_branch, dict) else None)
    if (not isinstance(default_branch_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", default_branch_sha)):
        blockers.append("DEFAULT_BRANCH_HEAD_UNVERIFIED")

    operation = "blocked"
    if desired is not None and not any(item in blockers for item in (
            "MANAGED_RULESET_NAME_COLLISION", "MANAGED_RULESET_DETAIL_UNAVAILABLE",
            "MANAGED_RULESET_HAS_NO_OWNERSHIP_EVIDENCE", "MANAGED_RULESET_OWNERSHIP_DIGEST_MISMATCH",
            "OWNERSHIP_RECORD_REFERENCES_MISSING_RULESET", "REPOSITORY_RULESET_INVENTORY_UNAVAILABLE")):
        if existing_detail is None:
            operation = "create"
        elif _canonical(_managed_body(existing_detail)) == _canonical(_managed_body(desired)):
            operation = "noop"
        else:
            operation = "update"
    if blockers:
        operation = "blocked"

    before_body = _managed_body(existing_detail) if existing_detail is not None else None
    after_body = _managed_body(desired) if desired is not None else None
    diff = {
        "operation": operation,
        "before": existing_detail,
        "before_body_sha256": existing_digest,
        "after": desired,
        "changed_fields": sorted(
            key for key in (set(before_body or {}) | set(after_body or {}))
            if _canonical((before_body or {}).get(key)) != _canonical((after_body or {}).get(key))
            and key in {"name", "target", "enforcement", "conditions", "rules", "bypass_actors"}
        ),
    }
    plan = {
        "activation_issue_number": ACTIVATION_ISSUE,
        "blockers": sorted(set(blockers)),
        "default_branch": default_branch,
        "default_branch_sha40": default_branch_sha,
        "diff": diff,
        "existing_ruleset_id": existing_id,
        "existing_ruleset_sha256": existing_digest,
        "owner_id": owner_id,
        "plan_schema": PLAN_SCHEMA,
        "policy_evidence": policy_evidence,
        "policy_proof": policy.as_dict() if isinstance(policy, EffectiveBranchPolicy) else None,
        "profile_review_mode": profile.final_delivery_review_mode,
        "profile_sha256": profile_sha,
        "repository": github.repo,
        "repository_id": repository_id,
        "required_checks": [{"context": name, "integration_id": app_id} for name, app_id in checks],
        "desired_ruleset": desired,
        "existing_pr_impact": pr_impact,
    }
    plan["plan_sha256"] = hashlib.sha256(_canonical(plan)).hexdigest()
    return plan


def validate_plan(value: Any) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != PLAN_FIELDS
            or value.get("plan_schema") != PLAN_SCHEMA):
        raise RulesetManagementError("Ruleset plan has an unknown schema")
    if not isinstance(value.get("diff"), dict):
        raise RulesetManagementError("Ruleset plan diff is malformed")
    supplied = value.get("plan_sha256")
    payload = {key: item for key, item in value.items() if key != "plan_sha256"}
    actual = hashlib.sha256(_canonical(payload)).hexdigest()
    if supplied != actual:
        raise RulesetManagementError("Ruleset plan digest does not match its canonical content")
    if (not isinstance(value.get("repository"), str) or not REPOSITORY.fullmatch(value["repository"])
            or type(value.get("repository_id")) is not int or value["repository_id"] < 1
            or type(value.get("owner_id")) is not int or value["owner_id"] < 1
            or value.get("activation_issue_number") != ACTIVATION_ISSUE
            or value.get("profile_review_mode") != "solo_owner"
            or value.get("diff", {}).get("operation") not in {"create", "update", "noop"}
            or value.get("blockers") != []):
        raise RulesetManagementError("Ruleset plan is blocked or has invalid bound identity")
    _sha(value.get("profile_sha256"), "committed profile digest")
    if (not isinstance(value.get("default_branch"), str) or not value["default_branch"]
            or not isinstance(value.get("default_branch_sha40"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", value["default_branch_sha40"])):
        raise RulesetManagementError("Ruleset plan default-branch binding is invalid")
    checks = value.get("required_checks")
    if not isinstance(checks, list) or not checks:
        raise RulesetManagementError("Ruleset plan has no trusted Required Checks")
    pairs: list[tuple[str, int]] = []
    for row in checks:
        if (not isinstance(row, dict) or set(row) != {"context", "integration_id"}
                or not isinstance(row.get("context"), str) or not row["context"]
                or row["context"] != row["context"].strip()
                or type(row.get("integration_id")) is not int or row["integration_id"] < 1):
            raise RulesetManagementError("Ruleset plan Required Check identity is malformed")
        pairs.append((row["context"], row["integration_id"]))
    if len({name for name, _app_id in pairs}) != len(pairs):
        raise RulesetManagementError("Ruleset plan Required Checks contain duplicate contexts")
    if value.get("desired_ruleset") != _desired_payload(value["repository"], tuple(pairs)):
        raise RulesetManagementError("Ruleset plan desired Ruleset does not match its trusted profile")
    if (not isinstance(value.get("diff"), dict)
            or set(value["diff"]) != {"operation", "before", "before_body_sha256", "after", "changed_fields"}
            or value["diff"].get("after") != value["desired_ruleset"]
            or not isinstance(value["diff"].get("changed_fields"), list)
            or any(field not in {"name", "target", "enforcement", "conditions", "rules", "bypass_actors"}
                   for field in value["diff"]["changed_fields"])):
        raise RulesetManagementError("Ruleset plan diff is malformed or does not bind its desired policy")
    operation = value["diff"]["operation"]
    existing_id = value.get("existing_ruleset_id")
    existing_digest = value.get("existing_ruleset_sha256")
    if operation == "create":
        if existing_id is not None or existing_digest is not None or value["diff"].get("before") is not None:
            raise RulesetManagementError("Ruleset create plan unexpectedly names an existing Ruleset")
    else:
        _positive(existing_id, "existing managed Ruleset ID")
        _sha(existing_digest, "existing managed Ruleset digest")
        before = value["diff"].get("before")
        if not isinstance(before, dict) or _body_digest(before) != existing_digest:
            raise RulesetManagementError("Ruleset plan existing body does not match its bound digest")
        if operation == "noop" and _canonical(_managed_body(before)) != _canonical(
                _managed_body(value["desired_ruleset"])):
            raise RulesetManagementError("Ruleset no-op plan does not already match the desired body")
    return value


def write_plan(path: Path, plan: dict[str, Any]) -> None:
    plan = validate_plan(plan)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.",
                                         delete=False, mode="wb") as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise RulesetManagementError("could not atomically write Ruleset plan") from exc


def read_plan(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise RulesetManagementError("Ruleset plan contains a duplicate JSON key")
            result[key] = item
        return result
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RulesetManagementError("Ruleset plan file is not valid UTF-8 JSON") from exc
    return validate_plan(value)


def _verify_exact_approval(github: GitHub, plan: dict[str, Any], comment_id: int) -> dict[str, Any]:
    comment_id = _positive(comment_id, "Ruleset approval comment ID")
    expected = (f"PASES-RULESET-APPROVE: {plan['plan_sha256']}\n"
                f"PASES-REPOSITORY: {github.repo}")
    issue = github.issue(ACTIVATION_ISSUE)
    expected_repo_url = f"https://api.github.com/repos/{github.repo}"
    if (issue.get("number") != ACTIVATION_ISSUE or issue.get("pull_request") is not None
            or issue.get("state") != "open"
            or not isinstance(issue.get("repository_url"), str)
            or issue["repository_url"].casefold() != expected_repo_url.casefold()):
        raise RulesetManagementError("Ruleset approval Issue #57 identity is invalid")
    first = github.issue_comment(ACTIVATION_ISSUE, comment_id)
    listed = github.issue_comments(ACTIVATION_ISSUE)
    matches = [row for row in listed if row.get("id") == comment_id]
    final = github.issue_comment(ACTIVATION_ISSUE, comment_id)
    user = final.get("user") if isinstance(final.get("user"), dict) else {}
    if (len(matches) != 1 or first.get("id") != comment_id or final.get("id") != comment_id
            or first.get("body") != expected or final.get("body") != expected
            or final.get("created_at") != matches[0].get("created_at")
            or final.get("html_url") != matches[0].get("html_url")
            or not isinstance(final.get("issue_url"), str)
            or final["issue_url"].casefold() != f"{expected_repo_url}/issues/{ACTIVATION_ISSUE}".casefold()
            or final.get("updated_at") != final.get("created_at")
            or type(user.get("id")) is not int or user.get("id") != plan["owner_id"]
            or user.get("type") != "User" or not isinstance(user.get("login"), str)):
        raise RulesetManagementError("exact human Ruleset approval comment failed direct/list/direct verification")
    duplicates = [row for row in listed if row.get("body") == expected]
    if len(duplicates) != 1:
        raise RulesetManagementError("Ruleset approval comment is duplicated")
    return final


def _require_current_admin(github: GitHub, owner_id: int) -> dict[str, Any]:
    user = github.authenticated_user()
    if user.get("id") != owner_id:
        raise RulesetManagementError("authenticated GitHub user is not the repository owner")
    permission = github.collaborator_permission(user.get("login", ""))
    if (permission.get("permission") != "admin"
            or permission.get("user", {}).get("id") != user.get("id")):
        raise RulesetManagementError("authenticated GitHub user lacks verified repository admin permission")
    metadata = github.repository_metadata()
    permissions = metadata.get("permissions") if isinstance(metadata.get("permissions"), dict) else {}
    if permissions.get("admin") is not True:
        raise RulesetManagementError("repository metadata does not verify admin access")
    return user


def _publish_applied_record(github: GitHub, plan: dict[str, Any], approval_id: int,
                            ruleset_id: int, body_digest: str, policy_digest: str,
                            actor: dict[str, Any]) -> int:
    history = _read_ownership_history(github, plan["repository_id"], plan["owner_id"])
    matching_attempts = [
        (comment_id, payload) for comment_id, payload in history
        if payload["plan_sha256"] == plan["plan_sha256"]
    ]
    if matching_attempts:
        if (len(matching_attempts) != 1
                or matching_attempts[0][1]["approval_comment_id"] != approval_id
                or matching_attempts[0][1]["ruleset_id"] != ruleset_id
                or matching_attempts[0][1]["ruleset_body_sha256"] != body_digest
                or matching_attempts[0][1]["effective_policy_sha256"] != policy_digest):
            raise RulesetManagementError("existing Ruleset application record conflicts with this exact plan")
        return matching_attempts[0][0]
    predecessor = history[-1][0] if history else None
    payload = {
        "actor_id": actor["id"], "actor_login": actor["login"],
        "approval_comment_id": approval_id, "plan_sha256": plan["plan_sha256"],
        "effective_policy_sha256": policy_digest, "predecessor_comment_id": predecessor, "repository": github.repo,
        "repository_id": plan["repository_id"], "ruleset_body_sha256": body_digest,
        "ruleset_id": ruleset_id, "schema": "PASES_RULESET_APPLIED_V1",
    }
    expected_body = f"{APPLIED_MARKER}{_canonical(payload).decode('utf-8')}\n-->"
    existing = [row for row in _comments_for_marker(github, ACTIVATION_ISSUE)
                if row.get("body") == expected_body]
    if len(existing) > 1:
        raise RulesetManagementError("Ruleset application record is duplicated")
    if existing:
        comment_id = _positive(existing[0].get("id"), "Ruleset application comment ID")
    else:
        try:
            response = github.create_issue_comment(ACTIVATION_ISSUE, expected_body)
            comment_id = _positive(response.get("id"), "Ruleset application comment ID")
        except (GitHubError, RulesetManagementError) as exc:
            # A comment POST may succeed while its response is lost. Reconcile the
            # exact immutable record once; never publish a second ownership record.
            try:
                recovered = [row for row in _comments_for_marker(github, ACTIVATION_ISSUE)
                             if row.get("body") == expected_body]
            except GitHubError as read_error:
                raise RulesetManagementError(
                    "Ruleset ownership record POST result is ambiguous; no retry was attempted"
                ) from read_error
            if len(recovered) != 1:
                raise RulesetManagementError(
                    "Ruleset ownership record POST result could not be reconciled uniquely; no retry was attempted"
                ) from exc
            candidate_user = recovered[0].get("user") if isinstance(recovered[0].get("user"), dict) else {}
            if candidate_user.get("id") != actor["id"] or candidate_user.get("type") != "User":
                raise RulesetManagementError(
                    "recovered Ruleset ownership record was not authored by the verified applying owner"
                ) from exc
            comment_id = _positive(recovered[0].get("id"), "Ruleset application comment ID")
    final = github.issue_comment(ACTIVATION_ISSUE, comment_id)
    listed = _comments_for_marker(github, ACTIVATION_ISSUE)
    matches = [row for row in listed if row.get("id") == comment_id]
    reread = github.issue_comment(ACTIVATION_ISSUE, comment_id)
    final_user = final.get("user") if isinstance(final.get("user"), dict) else {}
    if (len(matches) != 1 or final.get("id") != comment_id or reread.get("id") != comment_id
            or final.get("body") != expected_body or reread.get("body") != expected_body
            or final.get("html_url") != matches[0].get("html_url")
            or not isinstance(final.get("issue_url"), str)
            or final["issue_url"].casefold()
            != f"https://api.github.com/repos/{github.repo}/issues/{ACTIVATION_ISSUE}".casefold()
            or final.get("created_at") != matches[0].get("created_at")
            or final.get("updated_at") != final.get("created_at")
            or final_user.get("id") != actor["id"] or final_user.get("type") != "User"):
        raise RulesetManagementError("Ruleset application record failed exact direct/list/direct readback")
    verified_history = _read_ownership_history(github, plan["repository_id"], plan["owner_id"])
    if (not verified_history or verified_history[-1][0] != comment_id
            or verified_history[-1][1] != payload):
        raise RulesetManagementError("Ruleset application record did not become the valid latest ownership evidence")
    return comment_id


def _read_managed_candidate(github: GitHub) -> tuple[int, dict[str, Any]]:
    rows = [row for row in github.repository_rulesets() if row.get("name") == RULESET_NAME]
    if len(rows) != 1:
        raise RulesetManagementError("managed Ruleset is missing or ambiguous after write")
    ruleset_id = _positive(rows[0].get("id"), "managed Ruleset ID")
    return ruleset_id, github.ruleset_details(ruleset_id, source_type="Repository")


def apply_ruleset_plan(root: Path, github: GitHub, plan_path: Path,
                       approval_comment_id: int) -> dict[str, Any]:
    """Apply one approved plan once, read it back, and append ownership evidence."""
    plan = read_plan(plan_path)
    if plan["repository"].casefold() != github.repo.casefold():
        raise RulesetManagementError("Ruleset plan repository does not match the GitHub client")
    approval = _verify_exact_approval(github, plan, approval_comment_id)
    actor = _require_current_admin(github, plan["owner_id"])
    current = build_ruleset_plan(root, github)
    if current["plan_sha256"] != plan["plan_sha256"]:
        raise RulesetManagementError("Ruleset plan preconditions changed before apply")
    # The entire read-only plan and approval are fetched again immediately before any write.
    approval = _verify_exact_approval(github, plan, approval_comment_id)
    actor = _require_current_admin(github, plan["owner_id"])
    current = build_ruleset_plan(root, github)
    if current["plan_sha256"] != plan["plan_sha256"]:
        raise RulesetManagementError("Ruleset plan preconditions changed during apply preflight")
    current_policy = current.get("policy_proof")
    if (not isinstance(current_policy, dict)
            or current_policy.get("status") not in {"NOT_CONFIGURED", "VERIFIED"}
            or any(row.get("source") in {"legacy_protection", "effective_rules", "ruleset_details", "branch"}
                   and row.get("http_status") not in {404}
                   for row in current_policy.get("source_errors", []))):
        raise RulesetManagementError(
            "current branch-protection sources are not fully readable with the applying admin credential"
        )
    if approval.get("id") != approval_comment_id:
        raise RulesetManagementError("Ruleset approval identity changed during apply preflight")

    operation = plan["diff"]["operation"]
    desired = plan["desired_ruleset"]
    if not isinstance(desired, dict):
        raise RulesetManagementError("Ruleset plan has no desired API payload")
    ruleset_id = plan.get("existing_ruleset_id")
    if operation == "create":
        try:
            created = github.create_repository_ruleset(desired)
            ruleset_id = _positive(created.get("id"), "created managed Ruleset ID")
        except GitHubError as exc:
            # A lost/failed response is reconciled by one fresh inventory read. Never POST twice.
            try:
                ruleset_id, detail = _read_managed_candidate(github)
            except (GitHubError, RulesetManagementError) as read_error:
                raise RulesetManagementError("Ruleset POST result is ambiguous; no retry was attempted") from read_error
            if _canonical(_managed_body(detail)) != _canonical(_managed_body(desired)):
                raise RulesetManagementError("Ruleset POST failed and the managed candidate differs from plan") from exc
    elif operation == "update":
        if type(ruleset_id) is not int or ruleset_id < 1:
            raise RulesetManagementError("Ruleset update has no previously owned stable ID")
        try:
            github.update_repository_ruleset(ruleset_id, desired)
        except GitHubError as exc:
            try:
                recovered_id, detail = _read_managed_candidate(github)
            except (GitHubError, RulesetManagementError) as read_error:
                raise RulesetManagementError("Ruleset PUT result is ambiguous; no retry was attempted") from read_error
            if (recovered_id != ruleset_id
                    or _canonical(_managed_body(detail)) != _canonical(_managed_body(desired))):
                raise RulesetManagementError("Ruleset PUT failed and the managed Ruleset differs from plan") from exc
    elif operation != "noop":
        raise RulesetManagementError("Ruleset plan operation is not applicable")

    if type(ruleset_id) is not int or ruleset_id < 1:
        raise RulesetManagementError("managed Ruleset ID is unavailable after apply")
    detail = github.ruleset_details(ruleset_id, source_type="Repository")
    if _canonical(_managed_body(detail)) != _canonical(_managed_body(desired)):
        raise RulesetManagementError("managed Ruleset detail differs from the exact approved payload")
    policy, evidence = _read_policy(
        github, plan["repository"], plan["default_branch"], plan["profile_review_mode"],
        tuple((row["context"], row["integration_id"]) for row in plan["required_checks"]),
        plan["default_branch"],
    )
    if policy.status != "VERIFIED":
        raise RulesetManagementError(
            "effective branch policy is not VERIFIED after Ruleset apply: "
            + ", ".join(policy.reason_codes or (policy.status,))
        )
    if (not isinstance(evidence.get("branch"), dict)
            or evidence["branch"].get("protected") is not True):
        raise RulesetManagementError("default branch protected flag is not verified after Ruleset apply")
    digest = _body_digest(detail)
    record_id = None
    if operation != "noop":
        policy_digest = effective_policy_sha256(policy, ruleset_id, digest)
        record_id = _publish_applied_record(
            github, plan, approval_comment_id, ruleset_id, digest, policy_digest, actor,
        )
    return {
        "activation_issue_number": ACTIVATION_ISSUE,
        "approval_comment_id": approval_comment_id,
        "effective_policy": policy.as_dict(),
        "operation": operation.upper(),
        "plan_sha256": plan["plan_sha256"],
        "record_comment_id": record_id,
        "repository": github.repo,
        "ruleset_body_sha256": digest,
        "ruleset_id": ruleset_id,
        "status": "VERIFIED",
    }


def preflight(root: Path, github: GitHub) -> dict[str, Any]:
    """Read-only readiness report for Activation's current ruleset prerequisites."""
    plan = build_ruleset_plan(root, github)
    policy = plan.get("policy_proof")
    return {
        "blockers": plan["blockers"],
        "default_branch": plan["default_branch"],
        "default_branch_sha40": plan["default_branch_sha40"],
        "operation": plan["diff"]["operation"],
        "plan_sha256": plan["plan_sha256"],
        "policy_status": policy.get("status") if isinstance(policy, dict) else "UNVERIFIED",
        "profile_review_mode": plan["profile_review_mode"],
        "profile_sha256": plan["profile_sha256"],
        "repository": plan["repository"],
        "repository_id": plan["repository_id"],
        "required_checks": plan["required_checks"],
        "ruleset_id": plan["existing_ruleset_id"],
    }


def effective_policy_sha256(policy: EffectiveBranchPolicy, ruleset_id: int,
                            body_digest: str) -> str:
    """Stable policy digest excluding the moving default-branch commit SHA."""
    value = policy.as_dict()
    value.pop("source_evidence_sha256", None)
    value["ruleset_body_sha256"] = _sha(body_digest, "managed Ruleset body digest")
    value["ruleset_id"] = _positive(ruleset_id, "managed Ruleset ID")
    return hashlib.sha256(_canonical(value)).hexdigest()


def read_verified_managed_policy(github: GitHub, branch: str,
                                 checks: tuple[tuple[str, int], ...], review_mode: str
                                 ) -> dict[str, Any]:
    """Verify the unique owned Ruleset against live branch policy for Activation V2."""
    metadata = github.repository_metadata()
    repository_id = _positive(metadata.get("id"), "repository ID")
    owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
    owner_id = _positive(owner.get("id"), "repository owner ID")
    default_branch = metadata.get("default_branch")
    if branch != default_branch:
        raise RulesetManagementError("Activation policy must target the repository default branch")
    rows = [row for row in github.repository_rulesets() if row.get("name") == RULESET_NAME]
    if len(rows) != 1:
        raise RulesetManagementError("Activation requires exactly one repository-managed Ruleset")
    ruleset_id = _positive(rows[0].get("id"), "managed Ruleset ID")
    detail = github.ruleset_details(ruleset_id, source_type="Repository")
    desired = _desired_payload(github.repo, checks)
    if _canonical(_managed_body(detail)) != _canonical(_managed_body(desired)):
        raise RulesetManagementError("managed Ruleset body does not match the committed review profile")
    body_digest = _body_digest(detail)
    history = _read_ownership_history(github, repository_id, owner_id)
    if not history or (history[-1][1]["ruleset_id"] != ruleset_id
                       or history[-1][1]["ruleset_body_sha256"] != body_digest):
        raise RulesetManagementError("managed Ruleset has no current append-only ownership proof")
    policy, evidence = _read_policy(
        github, github.repo, branch, review_mode, checks, default_branch,
    )
    if policy.status != "VERIFIED":
        raise RulesetManagementError(
            "effective branch policy is not VERIFIED: " + ", ".join(policy.reason_codes or (policy.status,))
        )
    policy_digest = effective_policy_sha256(policy, ruleset_id, body_digest)
    if history[-1][1]["effective_policy_sha256"] != policy_digest:
        raise RulesetManagementError("live effective policy differs from the latest applied-policy evidence")
    branch_info = evidence.get("branch")
    if not isinstance(branch_info, dict) or branch_info.get("protected") is not True:
        raise RulesetManagementError("default branch protected state is not verified")
    return {
        "effective_policy_sha256": policy_digest,
        "policy": policy,
        "ruleset_body_sha256": body_digest,
        "ruleset_id": ruleset_id,
    }


def verify_applied_policy_record(github: GitHub, activation_record_id: int,
                                 ruleset_id: int, policy_digest: str) -> dict[str, Any]:
    """Bind a historical V2 Activation to an earlier append-only Ruleset apply record."""
    activation_record_id = _positive(activation_record_id, "Activation record Comment ID")
    ruleset_id = _positive(ruleset_id, "managed Ruleset ID")
    policy_digest = _sha(policy_digest, "effective policy digest")
    metadata = github.repository_metadata()
    repository_id = _positive(metadata.get("id"), "repository ID")
    owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
    owner_id = _positive(owner.get("id"), "repository owner ID")
    history = _read_ownership_history(github, repository_id, owner_id)
    matches = [(comment_id, payload) for comment_id, payload in history
               if comment_id < activation_record_id and payload["ruleset_id"] == ruleset_id
               and payload["effective_policy_sha256"] == policy_digest]
    if len(matches) != 1:
        raise RulesetManagementError("V2 Activation does not bind one earlier Ruleset applied-policy record")
    return matches[0][1]
