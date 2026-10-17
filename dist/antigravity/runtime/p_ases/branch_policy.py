"""Pure, fail-closed assessment of effective GitHub branch policy."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .verification import RequiredCheckPolicy


class BranchPolicyError(ValueError):
    pass


STATUSES = {"VERIFIED", "NOT_CONFIGURED", "UNAVAILABLE", "UNVERIFIED", "MISMATCH"}
MODES = {"external_reviewer", "solo_owner"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _check_pairs(rows: Any, *, app_key: str) -> tuple[tuple[str, int], ...] | None:
    if not isinstance(rows, list):
        return None
    result: list[tuple[str, int]] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        name = row.get("context")
        app_id = row.get(app_key)
        if (not isinstance(name, str) or not name or name != name.strip()
                or not _positive_int(app_id)):
            return None
        result.append((name, app_id))
    if len({name for name, _app_id in result}) != len(result):
        return None
    return tuple(sorted(result))


def _branch_matches(details: dict[str, Any], branch: str, default_branch: str) -> bool | None:
    conditions = details.get("conditions")
    if conditions is None:
        return True
    if not isinstance(conditions, dict):
        return None
    ref = conditions.get("ref_name")
    if ref is None:
        return True
    if not isinstance(ref, dict):
        return None
    include, exclude = ref.get("include"), ref.get("exclude")
    if (not isinstance(include, list) or any(not isinstance(item, str) or not item for item in include)
            or not isinstance(exclude, list) or any(not isinstance(item, str) or not item for item in exclude)):
        return None
    full = f"refs/heads/{branch}"

    def matches(pattern: str) -> bool:
        if pattern == "~ALL":
            return True
        if pattern == "~DEFAULT_BRANCH":
            return branch == default_branch
        return fnmatch.fnmatchcase(full, pattern) or fnmatch.fnmatchcase(branch, pattern)

    selected = not include or any(matches(pattern) for pattern in include)
    return selected and not any(matches(pattern) for pattern in exclude)


def _detail_rule_map(details: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    rows = details.get("rules")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("type")
        if not isinstance(name, str) or not name or name in result:
            return None
        parameters = row.get("parameters", {})
        if not isinstance(parameters, dict):
            return None
        result[name] = parameters
    return result


def _ruleset_summary(
    *, repository: str, branch: str, default_branch: str, effective_rules: list[dict[str, Any]],
    details_rows: list[dict[str, Any]], required: tuple[tuple[str, int], ...], minimum_approvals: int,
    require_no_bypass_or_force_push: bool,
) -> tuple[bool, tuple[str, ...], int | None]:
    reasons: list[str] = []
    effective_ids: list[int] = []
    for row in effective_rules:
        ruleset_id = row.get("ruleset_id")
        name = row.get("type")
        parameters = row.get("parameters", {})
        if (not _positive_int(ruleset_id) or not isinstance(name, str)
                or not isinstance(parameters, dict)):
            return False, ("EFFECTIVE_RULE_SHAPE_INVALID",), None
        effective_ids.append(ruleset_id)
    unique_ids = sorted(set(effective_ids))
    if len(unique_ids) != len(effective_ids) and len(effective_ids) != len(set((row.get("ruleset_id"), row.get("type")) for row in effective_rules)):
        reasons.append("DUPLICATE_EFFECTIVE_RULE")
    if len(unique_ids) != 1:
        reasons.append("ACTIVE_RULESET_MISSING_OR_AMBIGUOUS")
    details_by_id: dict[int, dict[str, Any]] = {}
    for details in details_rows:
        identifier = details.get("id")
        if not _positive_int(identifier) or identifier in details_by_id:
            reasons.append("RULESET_DETAIL_ID_INVALID_OR_DUPLICATE")
            continue
        details_by_id[identifier] = details
    if len(unique_ids) != len(details_by_id) or any(identifier not in details_by_id for identifier in unique_ids):
        reasons.append("RULESET_DETAIL_UNAVAILABLE")
    if reasons:
        return False, tuple(sorted(set(reasons))), None

    identifier = unique_ids[0]
    details = details_by_id[identifier]
    if (details.get("enforcement") != "active" or details.get("target") != "branch"
            or details.get("source_type") not in {"Repository", "Organization"}
            or not isinstance(details.get("source"), str) or not details.get("source")):
        reasons.append("RULESET_NOT_ACTIVE_OR_SOURCE_UNVERIFIED")
    else:
        owner = repository.split("/", 1)[0]
        expected_source = repository if details["source_type"] == "Repository" else owner
        if details["source"].casefold() != expected_source.casefold():
            reasons.append("RULESET_SOURCE_MISMATCH")
    for row in effective_rules:
        row_type = row.get("ruleset_source_type", row.get("source_type"))
        row_source = row.get("ruleset_source", row.get("source"))
        if (row.get("ruleset_id") == identifier
                and (row_type != details.get("source_type") or row_source != details.get("source"))):
            reasons.append("EFFECTIVE_RULE_SOURCE_MISMATCH")
    matches = _branch_matches(details, branch, default_branch)
    if matches is None:
        reasons.append("RULESET_SCOPE_UNVERIFIED")
    elif not matches:
        reasons.append("RULESET_DOES_NOT_APPLY_TO_BRANCH")

    bypass = details.get("bypass_actors")
    if not isinstance(bypass, list) or any(not isinstance(row, dict) for row in bypass):
        reasons.append("RULESET_BYPASS_ACTORS_UNVERIFIED")
    elif bypass and require_no_bypass_or_force_push:
        reasons.append("RULESET_BYPASS_ACTORS_PRESENT")

    detail_rules = _detail_rule_map(details)
    if detail_rules is None:
        reasons.append("RULESET_DETAIL_RULES_INVALID")
        return False, tuple(sorted(set(reasons))), identifier
    effective_by_type: dict[str, dict[str, Any]] = {}
    for row in effective_rules:
        if row.get("ruleset_id") != identifier:
            continue
        name = row.get("type")
        if name in effective_by_type:
            reasons.append("DUPLICATE_EFFECTIVE_RULE")
        effective_by_type[name] = row.get("parameters", {})
    if (set(detail_rules) != set(effective_by_type)
            or any(_canonical(detail_rules.get(name)) != _canonical(effective_by_type.get(name))
                   for name in set(detail_rules) & set(effective_by_type))):
        reasons.append("EFFECTIVE_RULES_DIFFER_FROM_RULESET_DETAIL")

    status_parameters = detail_rules.get("required_status_checks")
    status_rows = status_parameters.get("required_status_checks") if isinstance(status_parameters, dict) else None
    pairs = _check_pairs(status_rows, app_key="integration_id")
    if pairs is None:
        # GitHub's legacy shape may use app_id in fixture or a compatible response.
        pairs = _check_pairs(status_rows, app_key="app_id")
    if pairs != required:
        reasons.append("REQUIRED_CHECK_SET_MISMATCH")

    pull_request = detail_rules.get("pull_request")
    approvals = pull_request.get("required_approving_review_count") if isinstance(pull_request, dict) else None
    if (type(approvals) is not int or approvals < minimum_approvals
            or minimum_approvals == 0 and approvals != 0):
        reasons.append("APPROVAL_COUNT_MISMATCH")
    if require_no_bypass_or_force_push and "non_fast_forward" not in detail_rules:
        reasons.append("FORCE_PUSH_NOT_DISABLED")
    if reasons:
        return False, tuple(sorted(set(reasons))), approvals if type(approvals) is int else None
    return True, (), approvals


@dataclass(frozen=True)
class EffectiveBranchPolicy:
    repository: str
    branch: str
    source: tuple[str, ...]
    review_mode: str
    status: str
    required_checks: tuple[tuple[str, int], ...]
    pull_request_required: bool | None
    minimum_approvals: int | None
    force_push_disabled: bool | None
    bypass_actor_count: int | None
    reason_codes: tuple[str, ...]
    source_errors: tuple[tuple[str, int | None], ...]
    required_actions: tuple[str, ...]
    source_evidence_sha256: str

    def validate(self) -> "EffectiveBranchPolicy":
        if not isinstance(self.repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise BranchPolicyError("branch-policy repository is invalid")
        if not isinstance(self.branch, str) or not self.branch or any(c in self.branch for c in "\x00\r\n"):
            raise BranchPolicyError("branch-policy branch is invalid")
        if self.review_mode not in MODES or self.status not in STATUSES:
            raise BranchPolicyError("branch-policy mode or status is invalid")
        if (type(self.source) is not tuple or any(not isinstance(row, str) or not row for row in self.source)
                or self.source != tuple(sorted(set(self.source)))):
            raise BranchPolicyError("branch-policy evidence sources are invalid")
        if type(self.required_checks) is not tuple or any(
                type(row) is not tuple or len(row) != 2 or not isinstance(row[0], str) or not row[0]
                or not _positive_int(row[1]) for row in self.required_checks):
            raise BranchPolicyError("branch-policy Required Check pairs are invalid")
        if type(self.reason_codes) is not tuple or any(not isinstance(row, str) or not row for row in self.reason_codes):
            raise BranchPolicyError("branch-policy reason codes are invalid")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise BranchPolicyError("branch-policy reason codes must be sorted and unique")
        if (type(self.source_errors) is not tuple
                or any(type(row) is not tuple or len(row) != 2 or not isinstance(row[0], str) or not row[0]
                       or row[1] is not None and (type(row[1]) is not int or row[1] < 100 or row[1] > 599)
                       for row in self.source_errors)
                or self.source_errors != tuple(sorted(set(self.source_errors)))):
            raise BranchPolicyError("branch-policy source error details are invalid")
        if (type(self.required_actions) is not tuple
                or any(not isinstance(row, str) or not row for row in self.required_actions)
                or self.required_actions != tuple(sorted(set(self.required_actions)))):
            raise BranchPolicyError("branch-policy required actions are invalid")
        if not isinstance(self.source_evidence_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.source_evidence_sha256):
            raise BranchPolicyError("branch-policy source evidence digest is invalid")
        for value in (self.pull_request_required, self.force_push_disabled):
            if value is not None and type(value) is not bool:
                raise BranchPolicyError("branch-policy rule state must be boolean or unknown")
        for value in (self.minimum_approvals, self.bypass_actor_count):
            if value is not None and (type(value) is not int or value < 0):
                raise BranchPolicyError("branch-policy count must be nonnegative or unknown")
        if (self.status == "VERIFIED" and (self.reason_codes or not self.required_checks
                or self.pull_request_required is not True or self.minimum_approvals is None)):
            raise BranchPolicyError("verified branch-policy evidence is incomplete")
        if (self.status == "VERIFIED" and self.review_mode == "solo_owner"
                and (self.minimum_approvals != 0 or self.force_push_disabled is not True
                     or self.bypass_actor_count != 0)):
            raise BranchPolicyError("verified solo-owner ruleset proof is incomplete")
        if self.status == "VERIFIED" and self.required_actions:
            raise BranchPolicyError("verified branch policy cannot require administrator action")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "branch": self.branch,
            "bypass_actor_count": self.bypass_actor_count,
            "force_push_disabled": self.force_push_disabled,
            "minimum_approvals": self.minimum_approvals,
            "pull_request_required": self.pull_request_required,
            "reason_codes": list(self.reason_codes),
            "repository": self.repository,
            "required_actions": list(self.required_actions),
            "required_checks": [{"app_id": app_id, "name": name} for name, app_id in self.required_checks],
            "review_mode": self.review_mode,
            "schema": "PASES_EFFECTIVE_BRANCH_POLICY_V1",
            "source": list(self.source),
            "source_errors": [{"http_status": code, "source": source} for source, code in self.source_errors],
            "source_evidence_sha256": self.source_evidence_sha256,
            "status": self.status,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()


def assess_branch_policy(
    *, repository: str, branch: str, review_mode: str,
    required_check_policy: RequiredCheckPolicy,
    branch_info: dict[str, Any] | None,
    legacy_protection: dict[str, Any] | None,
    effective_rules: Iterable[dict[str, Any]] | None,
    ruleset_details: Iterable[dict[str, Any]] | None,
    source_errors: Mapping[str, int | None],
    default_branch: str = "main",
) -> EffectiveBranchPolicy:
    """Combine named GitHub observations; never issue HTTP or infer missing protection."""
    if review_mode not in MODES:
        raise BranchPolicyError("final-delivery review mode is unknown")
    if not isinstance(required_check_policy, RequiredCheckPolicy):
        raise BranchPolicyError("trusted Required Check policy is missing")
    required_check_policy.validate()
    if not required_check_policy.checks:
        raise BranchPolicyError("trusted Required Check policy is empty")
    if not isinstance(source_errors, Mapping):
        raise BranchPolicyError("branch-policy source errors must be a mapping")
    errors: dict[str, int | None] = {}
    for source, code in source_errors.items():
        if not isinstance(source, str) or not source or (code is not None and (type(code) is not int or code < 100 or code > 599)):
            raise BranchPolicyError("branch-policy source error is malformed")
        errors[source] = code
    rules = None if effective_rules is None else list(effective_rules)
    details = None if ruleset_details is None else list(ruleset_details)
    if rules is not None and any(not isinstance(row, dict) for row in rules):
        raise BranchPolicyError("effective branch rules must be objects")
    if details is not None and any(not isinstance(row, dict) for row in details):
        raise BranchPolicyError("ruleset details must be objects")
    required = tuple(sorted(required_check_policy.checks))
    sources: set[str] = set()
    if branch_info is not None:
        sources.add("branch")
    if legacy_protection is not None:
        sources.add("legacy-protection")
    if rules is not None:
        sources.add("effective-rules")
    if details is not None:
        sources.add("ruleset-details")
    reasons: set[str] = set()
    status = "UNVERIFIED"
    pull_request_required: bool | None = None
    minimum_approvals: int | None = None
    force_push_disabled: bool | None = None
    bypass_actor_count: int | None = None

    codes = set(errors.values())
    if 403 in codes:
        status = "UNAVAILABLE"
        reasons.add("POLICY_HTTP_403")
    elif branch_info is None or rules is None or details is None:
        status = "UNVERIFIED"
        reasons.add("POLICY_SOURCE_UNVERIFIED")
    elif any(code not in {None, 404} for code in codes):
        status = "UNAVAILABLE"
        reasons.add("POLICY_SOURCE_UNAVAILABLE")
    elif errors.get("legacy_protection") is None and "legacy_protection" in errors:
        status = "UNVERIFIED"
        reasons.add("POLICY_SOURCE_UNVERIFIED")
    elif any(code in {None, 404} for source, code in errors.items() if source != "legacy_protection"):
        status = "UNVERIFIED"
        reasons.add("POLICY_SOURCE_UNVERIFIED")
    elif (not isinstance(branch_info, dict) or type(branch_info.get("protected")) is not bool
          or (branch_info.get("name") is not None and branch_info.get("name") != branch)):
        status = "UNVERIFIED"
        reasons.add("BRANCH_READBACK_UNVERIFIED")
    else:
        if details and not rules:
            status = "UNVERIFIED"
            reasons.add("RULESET_DETAIL_WITHOUT_EFFECTIVE_RULE")
        if (not branch_info["protected"] and not rules and not details and legacy_protection is None
                and errors.get("legacy_protection") == 404):
            status = "NOT_CONFIGURED"
            reasons.add("POLICY_NOT_CONFIGURED")
        else:
            if not branch_info["protected"] and legacy_protection is not None:
                reasons.add("BRANCH_PROTECTED_FLAG_CONFLICT")
            expected_approvals = 0 if review_mode == "solo_owner" else 1
            if legacy_protection is not None:
                if not isinstance(legacy_protection, dict):
                    reasons.add("LEGACY_PROTECTION_SHAPE_INVALID")
                else:
                    status_checks = legacy_protection.get("required_status_checks")
                    if isinstance(status_checks, dict):
                        rows = status_checks.get("checks")
                        pairs = _check_pairs(rows, app_key="app_id")
                        if pairs is None:
                            contexts = status_checks.get("contexts")
                            if isinstance(contexts, list) and all(isinstance(x, str) for x in contexts):
                                reasons.add("LEGACY_CHECK_APP_ID_UNVERIFIED")
                            else:
                                reasons.add("LEGACY_CHECK_SET_INVALID")
                        elif pairs != required:
                            reasons.add("REQUIRED_CHECK_SET_MISMATCH")
                    else:
                        reasons.add("LEGACY_REQUIRED_CHECKS_MISSING")
                    review = legacy_protection.get("required_pull_request_reviews")
                    count = review.get("required_approving_review_count") if isinstance(review, dict) else None
                    if type(count) is not int or count < 0:
                        reasons.add("LEGACY_APPROVAL_POLICY_UNVERIFIED")
                    elif count < expected_approvals or (review_mode == "solo_owner" and count != 0):
                        reasons.add("APPROVAL_COUNT_MISMATCH")
                    else:
                        minimum_approvals = count
                        pull_request_required = True
                    force = legacy_protection.get("allow_force_pushes")
                    if isinstance(force, dict) and type(force.get("enabled")) is bool:
                        force_push_disabled = force["enabled"] is False
                    else:
                        force_push_disabled = None
            elif errors.get("legacy_protection") == 404 and not rules:
                # 404 without an independently readable policy is not proof that nothing applies.
                pass

            if rules:
                sources.add("effective-rules")
                ok, rule_reasons, ruleset_approvals = _ruleset_summary(
                    repository=repository, branch=branch, default_branch=default_branch, effective_rules=rules,
                    details_rows=details, required=required, minimum_approvals=expected_approvals,
                    require_no_bypass_or_force_push=review_mode == "solo_owner",
                )
                reasons.update(rule_reasons)
                if ok:
                    pull_request_required = True
                    minimum_approvals = ruleset_approvals
                    matching_detail = next((row for row in details if row.get("id") in {
                        item.get("ruleset_id") for item in rules
                    }), None)
                    bypass = matching_detail.get("bypass_actors") if matching_detail else None
                    bypass_actor_count = len(bypass) if isinstance(bypass, list) else None
                    detail_rules = _detail_rule_map(matching_detail) if matching_detail else None
                    force_push_disabled = "non_fast_forward" in detail_rules if detail_rules is not None else None
                elif not rule_reasons:
                    reasons.add("EFFECTIVE_RULESET_MISMATCH")
            elif review_mode == "solo_owner":
                reasons.add("SOLO_OWNER_ACTIVE_RULESET_REQUIRED")

            if review_mode == "solo_owner" and legacy_protection is not None and minimum_approvals != 0:
                reasons.add("SOLO_OWNER_LEGACY_APPROVAL_POLICY_CONFLICT")
            if not rules and review_mode == "external_reviewer" and minimum_approvals is None:
                reasons.add("FORMAL_REVIEW_POLICY_MISSING")
            if errors.get("legacy_protection") == 404 and not rules and legacy_protection is None:
                if not branch_info["protected"] and not details:
                    status = "NOT_CONFIGURED"
                    reasons.add("POLICY_NOT_CONFIGURED")
                else:
                    status = "UNVERIFIED"
                    reasons.add("POLICY_HTTP_404")
            elif reasons:
                status = "UNVERIFIED" if reasons & {"LEGACY_CHECK_APP_ID_UNVERIFIED", "LEGACY_APPROVAL_POLICY_UNVERIFIED"} else "MISMATCH"
            else:
                status = "VERIFIED"

    action_map = {
        "UNAVAILABLE": "Restore read access for the GitHub policy endpoint(s) listed in source_errors, then rerun Final Delivery.",
        "UNVERIFIED": "Have a repository owner verify the exact branch policy and provide the missing branch, legacy-protection, or ruleset evidence.",
        "NOT_CONFIGURED": "Have a repository owner configure an approved branch policy matching the trusted Required Check profile.",
        "MISMATCH": "Have a repository owner align the effective branch rules with the trusted Required Check profile and selected review mode.",
    }
    required_actions = () if status == "VERIFIED" else (action_map[status],)

    result = EffectiveBranchPolicy(
        repository, branch, tuple(sorted(sources)), review_mode, status, required,
        pull_request_required, minimum_approvals, force_push_disabled, bypass_actor_count,
        tuple(sorted(reasons)), tuple(sorted(errors.items())), required_actions,
        hashlib.sha256(_canonical({
            "branch_info": branch_info,
            "default_branch": default_branch,
            "effective_rules": rules,
            "legacy_protection": legacy_protection,
            "ruleset_details": details,
            "source_errors": errors,
        })).hexdigest(),
    ).validate()
    return result
