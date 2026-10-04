"""Fail-closed pull request handoff and merged-delivery gates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .context import affected_components
from .github import GitHub
from .profile import ProfileError, load_profile
from .review import ReviewError, effective_checklist, validate_public_review


class DeliveryError(ValueError):
    pass


def _identity(issue_obj: dict[str, Any], pull: dict[str, Any], issue: int, pr: int, gh: GitHub) -> None:
    expected_repo_url = f"https://api.github.com/repos/{gh.repo}"
    if issue_obj.get("number") != issue or issue_obj.get("repository_url") != expected_repo_url or issue_obj.get("pull_request"):
        raise DeliveryError("Issue identity does not match configured repository")
    if pull.get("number") != pr or pull.get("base", {}).get("repo", {}).get("full_name", "").lower() != gh.repo.lower():
        raise DeliveryError("PR base repository identity does not match the Issue repository")


def _labels(issue_obj: dict[str, Any]) -> set[str]:
    return {str(label.get("name", "")) for label in issue_obj.get("labels", [])}


def _section(body: str, title: str) -> str | None:
    lines = body.splitlines()
    start = None
    level = 0
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if m and m.group(2).strip().casefold() == title.casefold():
            start, level = i + 1, len(m.group(1))
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start, len(lines)):
        m = re.match(r"^(#{1,6})\s+", lines[i])
        if m and len(m.group(1)) <= level:
            end = i
            break
    value = "\n".join(lines[start:end]).strip()
    if not value or re.fullmatch(r"(?is)(?:tbd|todo|pending|<[^>]+>|\[.*\])", value):
        return None
    return value


def _required_checks(profile: dict[str, Any]) -> list[Any]:
    branch = profile.get("branch", {})
    checks = branch.get("required_checks", profile.get("required_checks", [])) if isinstance(branch, dict) else []
    if not isinstance(checks, list):
        raise DeliveryError("configured Required Checks must be an array")
    return checks


def _base_details(pull: dict[str, Any], gh: GitHub) -> dict[str, Any]:
    base_ref = pull.get("base", {}).get("ref")
    if not isinstance(base_ref, str) or not base_ref:
        raise DeliveryError("PR base branch ref is missing")
    metadata = gh.repository()
    default_ref = metadata.get("default_branch") if isinstance(metadata, dict) else None
    if not isinstance(default_ref, str) or not default_ref:
        raise DeliveryError("GitHub repository default branch is missing")
    return {"base_ref": base_ref, "default_base_ref": default_ref,
            "stacked": base_ref != default_ref}


def _check_passed(required: Any, check_runs: list[dict[str, Any]], statuses: list[dict[str, Any]], head: str) -> bool:
    if isinstance(required, str):
        name, app_id = required, None
    elif isinstance(required, dict) and isinstance(required.get("name"), str) and required["name"]:
        name, app_id = required["name"], required.get("app_id")
    else:
        raise DeliveryError(f"invalid Required Check entry: {required!r}")
    for run in check_runs:
        if run.get("name") != name or run.get("head_sha") != head or run.get("status") != "completed":
            continue
        if app_id is not None and run.get("app", {}).get("id") != app_id:
            continue
        if run.get("conclusion") in {"success", "skipped", "neutral"}:
            return True
    # Legacy commit statuses have no app identity and must report the exact SHA.
    if app_id is None and any(s.get("context") == name and s.get("sha") == head and s.get("state") == "success" for s in statuses):
        return True
    return False


def delivery_check(repo: Path, issue: int, pr: int, gh: GitHub) -> dict[str, Any]:
    issue_obj = gh.issue(issue)
    pull = gh.pull(pr)
    _identity(issue_obj, pull, issue, pr, gh)
    base_details = _base_details(pull, gh)
    labels = _labels(issue_obj)
    head = pull.get("head", {}).get("sha")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{7,40}", head):
        raise DeliveryError("PR head SHA is missing or malformed")
    profile = load_profile(repo, allow_uninitialized=True)
    errors: list[str] = []
    if pull.get("merged"):
        if issue_obj.get("state") != "closed":
            errors.append("merged PR requires a closed Issue")
        if any(label.startswith("phase:") for label in labels):
            errors.append("merged delivery still has a phase label; run finalize-merged-issue after resolving unexpected labels")
        return {"gate": "merged", "passed": not errors, "errors": errors, "issue": issue,
                "pr": pr, "head": head, **base_details}

    if issue_obj.get("state") != "open":
        errors.append("handoff requires an open Issue")
    if pull.get("state") != "open":
        errors.append("handoff requires an open PR")
    if pull.get("draft"):
        errors.append("handoff requires a non-draft PR")
    if not re.search(rf"(?im)^\s*closes\s+#{issue}\b", pull.get("body") or ""):
        errors.append(f"PR body must contain Closes #{issue}")
    if "phase:review" not in labels:
        errors.append("Issue must have phase:review")
    if _section(pull.get("body") or "", "Verification") is None:
        errors.append("PR Verification field is empty")
    if _section(pull.get("body") or "", "Untested") is None:
        errors.append("PR Untested field is empty")
    review_failures: list[dict[str, str]] = []
    review_failure_count = 0
    try:
        published = validate_public_review(issue, pr, gh)
        review_current = True
        if published["stale"] or published["head"] != head:
            errors.append("published self-review is stale for the current PR HEAD")
            review_current = False
        current_items, current_list_sha = effective_checklist(issue, issue_obj.get("body") or "", gh)
        if current_list_sha != published["checklist_sha256"]:
            errors.append("published self-review checklist is stale")
            review_current = False
        if [(i["id"], i["text"]) for i in published["review"].get("items", [])] != [(i["id"], i["text"]) for i in current_items]:
            errors.append("published self-review items do not match the current effective checklist")
            review_current = False
        if review_current:
            failed = [item for item in published["review"].get("items", []) if item.get("result") == "fail"]
            review_failure_count = len(failed)
            review_failures = [{"id": str(item.get("id", "item"))[:64],
                                "text": str(item.get("text", ""))[:240]} for item in failed[:10]]
            if failed:
                summary = "; ".join(f"{item['id']}: {item['text']}" for item in review_failures)
                if len(failed) > len(review_failures):
                    summary += f"; and {len(failed) - len(review_failures)} more"
                errors.append(f"published self-review has {len(failed)} current failed item(s): {summary}")
    except (ReviewError, ValueError) as exc:
        errors.append(f"published self-review is invalid: {exc}")
    checks = _required_checks(profile)
    if not checks:
        errors.append("no Required Checks are configured")
    else:
        check_runs = gh.check_runs(head)
        statuses = gh.statuses(head)
        for required in checks:
            if not _check_passed(required, check_runs, statuses, head):
                check_name = required if isinstance(required, str) else required.get("name", "<invalid>") if isinstance(required, dict) else "<invalid>"
                errors.append(f"Required Check is not green on current HEAD: {check_name}")
    affected = affected_components(issue_obj.get("body") or "", profile)
    generic = any("generic" in c.get("application_types", []) for c in affected)
    if generic and not re.search(r"(?im)^\s*Generic profile rationale:\s*\S.+$", pull.get("body") or ""):
        errors.append("PR affecting a generic component requires a concrete Generic profile rationale:")
    return {"gate": "handoff", "passed": not errors, "errors": errors,
            "issue": issue, "pr": pr, "head": head, "required_checks": checks,
            "review_failures": review_failures, "review_failure_count": review_failure_count,
            **base_details}


def finalize_merged_issue(issue: int, pr: int, gh: GitHub) -> dict[str, Any]:
    issue_obj = gh.issue(issue)
    pull = gh.pull(pr)
    _identity(issue_obj, pull, issue, pr, gh)
    if not pull.get("merged"):
        raise DeliveryError("cannot finalize Issue before its PR is merged")
    if issue_obj.get("state") != "closed":
        raise DeliveryError("cannot finalize Issue before it is closed")
    labels = _labels(issue_obj)
    other_phase = sorted(label for label in labels if label.startswith("phase:") and label != "phase:review")
    if other_phase:
        raise DeliveryError(f"unexpected phase label(s); no mutation performed: {', '.join(other_phase)}")
    if "phase:review" not in labels:
        return {"issue": issue, "pr": pr, "finalized": True, "changed": False}
    latest = gh.issue(issue)
    _identity(latest, pull, issue, pr, gh)
    if latest.get("state") != "closed":
        raise DeliveryError("Issue state changed before finalization; no mutation performed")
    latest_labels = _labels(latest)
    latest_other_phase = sorted(label for label in latest_labels if label.startswith("phase:") and label != "phase:review")
    if latest_other_phase:
        raise DeliveryError(f"unexpected phase label(s); no mutation performed: {', '.join(latest_other_phase)}")
    if "phase:review" not in latest_labels:
        return {"issue": issue, "pr": pr, "finalized": True, "changed": False}
    gh.remove_issue_label(issue, "phase:review")
    readback = gh.issue(issue)
    remaining = _labels(readback)
    if "phase:review" in remaining:
        raise DeliveryError("phase:review label removal failed readback")
    if any(label.startswith("phase:") for label in remaining):
        raise DeliveryError("unexpected phase label remains after finalization")
    return {"issue": issue, "pr": pr, "finalized": True, "changed": True}
