"""Fail-closed pull request handoff and merged-delivery gates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .context import affected_components
from .execution import ExecutionError, load_execution
from .github import GitHub, GitHubError
from .git import GitLifecycleError, push_review_branch
from .profile import ProfileError, load_profile
from .qa import QAError, validate_public_qa
from .review import ReviewError, load_review_surface, validate_public_pr_review, validate_public_review
from .verification import VerificationError, validate_public_final_verification


class DeliveryError(ValueError):
    pass


def _issue_identity(issue_obj: dict[str, Any], issue: int, gh: GitHub) -> None:
    expected_repo_url = f"https://api.github.com/repos/{gh.repo}"
    if (not isinstance(issue_obj, dict) or issue_obj.get("number") != issue
            or issue_obj.get("repository_url") != expected_repo_url
            or issue_obj.get("pull_request")):
        raise DeliveryError("Issue identity does not match configured repository")


_CLOSING_KEYWORD = re.compile(r"\b(?:close[sd]?|fix(?:es|ed)?|resolve(?:s|d)?)\b[ \t]*:?", re.I)
_CLOSING_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>\d+)\b"
)
_CLOSING_AND = re.compile(r"and\b", re.I)


def _skip_horizontal_space(text: str, position: int) -> int:
    while position < len(text) and text[position] in " \t":
        position += 1
    return position


def _closing_clause_references(clause: str, current_repository: str) -> set[tuple[str, int]]:
    """Consume one closing target and only comma/and-separated targets after it."""
    position = _skip_horizontal_space(clause, 0)
    first = _CLOSING_REFERENCE.match(clause, position)
    if first is None:
        return set()

    references: set[tuple[str, int]] = set()

    def add(reference: re.Match[str]) -> None:
        repository = reference.group("repository")
        references.add(((repository or current_repository).casefold(), int(reference.group("number"))))

    add(first)
    position = first.end()
    while True:
        position = _skip_horizontal_space(clause, position)
        if position < len(clause) and clause[position] == ",":
            position = _skip_horizontal_space(clause, position + 1)
            conjunction = _CLOSING_AND.match(clause, position)
            if conjunction is not None:
                position = _skip_horizontal_space(clause, conjunction.end())
        else:
            conjunction = _CLOSING_AND.match(clause, position)
            if conjunction is None:
                break
            position = _skip_horizontal_space(clause, conjunction.end())

        reference = _CLOSING_REFERENCE.match(clause, position)
        if reference is None:
            break
        add(reference)
        position = reference.end()
    return references


def _closing_references(body: str, current_repository: str) -> set[tuple[str, int]]:
    """Return repository-qualified GitHub closing targets found in closing-keyword lines."""
    if (not isinstance(body, str)
            or not isinstance(current_repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", current_repository)):
        raise DeliveryError("closing-reference body or repository identity is malformed")
    current = current_repository.casefold()
    references: set[tuple[str, int]] = set()
    for line in body.splitlines():
        for keyword in _CLOSING_KEYWORD.finditer(line):
            references.update(_closing_clause_references(line[keyword.end():], current))
    return references


def _has_conflicting_closing_reference(body: str, issue: int, repository: str) -> bool:
    owning_target = (repository.casefold(), issue)
    return any(target != owning_target for target in _closing_references(body, repository))


def _review_pr_identity(pull: dict[str, Any], issue: int, gh: GitHub, head_branch: str,
                        base_branch: str, head_sha: str) -> None:
    if not isinstance(pull, dict):
        raise DeliveryError("matching PR metadata is malformed")
    number = pull.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise DeliveryError("matching PR number is missing or malformed")
    head, base = pull.get("head"), pull.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise DeliveryError("matching PR head/base metadata is missing")
    head_repo = head.get("repo")
    base_repo = base.get("repo")
    if not isinstance(head_repo, dict) or not isinstance(base_repo, dict):
        raise DeliveryError("matching PR head/base repository identity is missing")
    if str(head_repo.get("full_name", "")).casefold() != gh.repo.casefold():
        raise DeliveryError("matching PR head is from a fork or another repository")
    if str(base_repo.get("full_name", "")).casefold() != gh.repo.casefold():
        raise DeliveryError("matching PR base is from another repository")
    if head.get("ref") != head_branch or base.get("ref") != base_branch:
        raise DeliveryError("matching PR head or base branch does not match the requested branches")
    if head.get("sha") != head_sha:
        raise DeliveryError("matching PR head SHA does not match the pushed local HEAD")
    if pull.get("state") != "open" or pull.get("merged") is True or pull.get("draft") is not False:
        raise DeliveryError("matching PR must be open and non-draft")
    body = pull.get("body") or ""
    if not isinstance(body, str):
        raise DeliveryError("matching PR body is malformed")
    if _has_conflicting_closing_reference(body, issue, gh.repo):
        raise DeliveryError("matching PR closes a different Issue or repository; it was not changed")
    url = pull.get("html_url")
    if not isinstance(url, str) or url != f"https://github.com/{gh.repo}/pull/{number}":
        raise DeliveryError("matching PR URL is missing or does not match the repository")


def ensure_review_pr(repo: Path, issue: int, body: str, gh: GitHub, title: str | None = None,
                     base_ref: str | None = None) -> dict[str, Any]:
    """Push the current Issue branch and establish exactly one compatible review PR."""
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        raise DeliveryError("Issue number must be a positive integer")
    if not isinstance(body, str):
        raise DeliveryError("PR body must be UTF-8 text")
    if not re.search(rf"(?im)^\s*closes\s+#{issue}\s*$", body):
        raise DeliveryError(f"PR body must contain a standalone Closes #{issue} line")
    if _section(body, "Verification") is None:
        raise DeliveryError("PR body must contain a non-empty ## Verification section")
    if _section(body, "Untested") is None:
        raise DeliveryError("PR body must contain a non-empty ## Untested section")
    if _has_conflicting_closing_reference(body, issue, gh.repo):
        raise DeliveryError("PR body contains a closing reference outside the owning Issue")

    profile = load_profile(repo)
    if profile.get("schema_version") != 2:
        raise DeliveryError("ensure-review-pr requires a Schema 2 project profile")
    issue_obj = gh.issue(issue)
    _issue_identity(issue_obj, issue, gh)
    if issue_obj.get("state") != "open":
        raise DeliveryError("owning Issue must be open before establishing a review PR")
    default_base = gh.repository().get("default_branch")
    if not isinstance(default_base, str) or not default_base:
        raise DeliveryError("GitHub repository default branch is missing")
    if base_ref is None:
        selected_base = default_base
    elif not isinstance(base_ref, str) or not base_ref:
        raise DeliveryError("--base-ref must name a non-empty branch")
    else:
        selected_base = base_ref
    requested_title = title if title is not None else issue_obj.get("title")
    if not isinstance(requested_title, str) or not requested_title.strip() or "\n" in requested_title or "\r" in requested_title:
        raise DeliveryError("PR title must be a non-empty single-line value")

    try:
        binding = load_execution(repo, issue, gh)
    except (ExecutionError, GitLifecycleError, GitHubError) as exc:
        raise DeliveryError(str(exc)) from exc
    publication_branch = (
        binding["canonical_branch"]
        if binding is not None and binding["mode"] == "isolated"
        else None
    )
    try:
        if publication_branch is None:
            pushed = push_review_branch(repo, profile, issue, gh.repo, selected_base, default_base)
        else:
            pushed = push_review_branch(
                repo, profile, issue, gh.repo, selected_base, default_base,
                publication_branch=publication_branch,
            )
    except GitLifecycleError as exc:
        raise DeliveryError(str(exc)) from exc
    head_branch, head_sha = pushed["head_branch"], pushed["head_sha"]
    matches = gh.open_pull_requests(head_branch, selected_base)
    if not isinstance(matches, list):
        raise DeliveryError("GitHub PR query returned an invalid candidate list")
    if len(matches) > 1:
        raise DeliveryError("multiple open PRs match the exact Issue branch and base; refusing mutation")

    created = False
    if matches:
        pull = matches[0]
        _review_pr_identity(pull, issue, gh, head_branch, selected_base, head_sha)
        if pull.get("title") != requested_title or pull.get("body") != body:
            gh.update_pull_request(pull["number"], requested_title, body)
    else:
        pull = gh.create_pull_request(requested_title, head_branch, selected_base, body)
        created = True

    pr_number = pull.get("number")
    pr_url = pull.get("html_url")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
        raise DeliveryError("established PR number is missing or malformed")
    if not isinstance(pr_url, str) or pr_url != f"https://github.com/{gh.repo}/pull/{pr_number}":
        raise DeliveryError(f"established PR #{pr_number} URL is missing or invalid")
    phase_changed = False
    try:
        verified_pull = gh.pull(pr_number)
        _review_pr_identity(verified_pull, issue, gh, head_branch, selected_base, head_sha)
        if verified_pull.get("title") != requested_title or verified_pull.get("body") != body:
            raise DeliveryError("established PR title/body did not match the requested handoff payload")
        latest_issue = gh.issue(issue)
        _issue_identity(latest_issue, issue, gh)
        if latest_issue.get("state") != "open":
            raise DeliveryError("owning Issue closed before the review phase transition")
        labels = _labels(latest_issue)
        expected_labels = {label for label in labels if not label.startswith("phase:")} | {"phase:review"}
        if labels != expected_labels:
            gh.replace_issue_labels(issue, sorted(expected_labels))
            phase_changed = True
        readback_issue = gh.issue(issue)
        _issue_identity(readback_issue, issue, gh)
        if readback_issue.get("state") != "open":
            raise DeliveryError("owning Issue is no longer open after phase transition")
        readback_pull = gh.pull(pr_number)
        _review_pr_identity(readback_pull, issue, gh, head_branch, selected_base, head_sha)
        actual_labels = _labels(readback_issue)
        if actual_labels != expected_labels:
            raise DeliveryError("Issue phase-label replacement failed readback")
    except (DeliveryError, GitHubError) as exc:
        return {"success": False, "issue": issue, "pr": pr_number, "pr_url": pr_url,
                "head_sha": head_sha, "head_branch": head_branch, "base_branch": selected_base,
                "created": created, "reused": not created, "push": pushed,
                "phase_transition": {"changed": phase_changed, "label": "phase:review", "verified": False},
                "error": str(exc)}

    return {"success": True, "issue": issue, "pr": pr_number, "pr_url": pr_url,
            "head_sha": head_sha, "head_branch": head_branch, "base_branch": selected_base,
            "created": created, "reused": not created, "push": pushed,
            "phase_transition": {"changed": phase_changed, "label": "phase:review", "verified": True}}


def _identity(issue_obj: dict[str, Any], pull: dict[str, Any], issue: int, pr: int, gh: GitHub) -> None:
    expected_repo_url = f"https://api.github.com/repos/{gh.repo}"
    if issue_obj.get("number") != issue or issue_obj.get("repository_url") != expected_repo_url or issue_obj.get("pull_request"):
        raise DeliveryError("Issue identity does not match configured repository")
    base = pull.get("base")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    full_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    if pull.get("number") != pr or not isinstance(full_name, str) or full_name.casefold() != gh.repo.casefold():
        raise DeliveryError("PR base repository identity does not match the Issue repository")


def _labels(issue_obj: dict[str, Any]) -> set[str]:
    labels = issue_obj.get("labels") if isinstance(issue_obj, dict) else None
    if (not isinstance(labels, list) or any(not isinstance(label, dict)
                                            or not isinstance(label.get("name"), str)
                                            or not label["name"] for label in labels)):
        raise DeliveryError("Issue labels are missing or malformed")
    return {label["name"] for label in labels}


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
    snapshot_issue_body = issue_obj.get("body")
    snapshot_pr_body = pull.get("body")
    snapshot_states = (issue_obj.get("state"), pull.get("state"), pull.get("draft"), pull.get("merged"))
    snapshot_has_review_phase = "phase:review" in labels
    gate_issue = issue_obj
    gate_pull_body = pull.get("body") or ""
    profile = load_profile(repo, allow_uninitialized=True)
    errors: list[str] = []
    if pull.get("merged"):
        if issue_obj.get("state") != "closed":
            errors.append("merged PR requires a closed Issue")
        if any(label.startswith("phase:") for label in labels):
            errors.append("merged delivery still has a phase label; run finalize-merged-issue after resolving unexpected labels")
        return {"gate": "merged", "passed": not errors, "errors": errors, "issue": issue,
                "pr": pr, "head": head, "review_failures": [], "review_failure_count": 0,
                "contract_review_failures": [], "contract_review_failure_count": 0,
                "contract_review_untested": [], "contract_review_untested_count": 0,
                "contract_comment_id": None, "contract_sha256": None,
                "review_schema_version": None, "final_verification_status": None,
                "final_verification": None, "qa_status": None, "qa": None,
                "independent_review_status": None, "independent_review": None, **base_details}

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
    contract_review_failures: list[dict[str, str]] = []
    contract_review_failure_count = 0
    contract_review_untested: list[dict[str, str]] = []
    contract_review_untested_count = 0
    contract_comment_id = None
    contract_sha256 = None
    review_schema_version = None
    final_verification_status = None
    final_verification = None
    evidence_contract_comment_id = None
    evidence_contract_sha256 = None
    try:
        verification = validate_public_final_verification(issue, pr, gh, issue_obj=issue_obj, pull=pull)
        receipt = verification["receipt"]
        evidence_contract_comment_id = receipt.get("contract_comment_id")
        evidence_contract_sha256 = receipt.get("contract_sha256")
        final_verification_status = receipt.get("result")
        final_verification = {"comment_id": verification.get("comment_id"),
                              "sha256": verification.get("sha256"),
                              "head": receipt.get("head"), "result": final_verification_status,
                              "stale": verification.get("stale"),
                              "stale_reasons": verification.get("stale_reasons", []),
                              "host": receipt.get("host"), "architecture": receipt.get("architecture"),
                              "components": receipt.get("components"),
                              "executed_count": len(receipt.get("executed", [])),
                              "skipped_target_count": len(receipt.get("skipped_targets", []))}
        if verification.get("stale") or receipt.get("head") != head:
            errors.append("published final verification is stale for current PR HEAD or approved contract")
        if final_verification_status != "pass":
            errors.append(f"published final verification result must be pass; got {final_verification_status}")
    except (VerificationError, ValueError) as exc:
        errors.append(f"published final verification is invalid: {exc}")
    try:
        published = validate_public_review(issue, pr, gh, issue_obj=issue_obj, pull=pull)
        review_schema_version = published.get("schema_version")
        contract_comment_id = published.get("current_contract_comment_id")
        contract_sha256 = published.get("current_contract_sha256")
        if ((contract_comment_id is not None and evidence_contract_comment_id is not None
             and contract_comment_id != evidence_contract_comment_id)
                or (contract_sha256 is not None and evidence_contract_sha256 is not None
                    and contract_sha256 != evidence_contract_sha256)):
            errors.append("self-review was validated against a different approved Implementation Contract")
        review_current = not published.get("stale", True) and published.get("head") == head
        if review_schema_version == 1:
            errors.append(
                "published self-review schema v1 has no full Implementation Contract conformance; "
                "regenerate the self-review with the current prepare-self-review / publish-self-review workflow"
            )
            review_current = False
        if published.get("head_stale"):
            errors.append("published self-review is stale for the current PR HEAD")
        elif published.get("head") != head:
            errors.append("published self-review is stale for the current PR HEAD")
        if published.get("contract_stale"):
            errors.append(
                "published self-review is stale: approved Implementation Contract comment/SHA or contract review units changed; "
                "restore/read the current contract and regenerate the self-review"
            )
        if published.get("checklist_stale"):
            errors.append("published self-review checklist is stale")
        if published.get("stale") and not any(
            (published.get("head_stale"), published.get("contract_stale"), published.get("checklist_stale"))
        ):
            errors.append("published self-review is stale for current Issue/PR state")
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
            contract_sections = published["review"].get("contract_sections", [])
            contract_failed = [section for section in contract_sections if section.get("result") == "fail"]
            contract_review_failure_count = len(contract_failed)
            contract_review_failures = [
                {"id": str(section.get("id", "section"))[:64],
                 "title": str(section.get("title", ""))[:120]}
                for section in contract_failed[:10]
            ]
            contract_review_untested_count = sum(
                section.get("result") == "untested" for section in contract_sections
            )
            contract_untested = [
                section for section in contract_sections if section.get("result") == "untested"
            ]
            contract_review_untested = [
                {"id": str(section.get("id", "section"))[:64],
                 "title": str(section.get("title", ""))[:120]}
                for section in contract_untested[:10]
            ]
            if contract_failed:
                summary = "; ".join(
                    f"{section['id']}: {section['title']}" for section in contract_review_failures
                )
                if len(contract_failed) > len(contract_review_failures):
                    summary += f"; and {len(contract_failed) - len(contract_review_failures)} more"
                errors.append(
                    f"published self-review has {len(contract_failed)} current failed contract section(s): {summary}"
                )
            if contract_untested:
                summary = "; ".join(
                    f"{section['id']}: {section['title']}" for section in contract_review_untested
                )
                if len(contract_untested) > len(contract_review_untested):
                    summary += f"; and {len(contract_untested) - len(contract_review_untested)} more"
                errors.append(
                    f"published self-review has {len(contract_untested)} current untested contract section(s); "
                    f"contract conformance is incomplete and handoff is blocked: {summary}"
                )
    except (ReviewError, ValueError) as exc:
        errors.append(f"published self-review is invalid: {exc}")

    qa_status = None
    qa_summary = None
    try:
        qa_public = validate_public_qa(issue, pr, gh, issue_obj=issue_obj, pull=pull)
        qa_status = qa_public.get("result")
        if (evidence_contract_comment_id is not None
                and qa_public.get("current_contract_comment_id") != evidence_contract_comment_id
                or evidence_contract_sha256 is not None
                and qa_public.get("current_contract_sha256") != evidence_contract_sha256):
            errors.append("QA was validated against a different approved Implementation Contract")
        qa_summary = {"comment_id": qa_public.get("comment_id"), "sha256": qa_public.get("sha256"),
                      "result": qa_status, "mode": qa_public.get("qa", {}).get("mode"),
                      "case_count": len(qa_public.get("qa", {}).get("cases", [])),
                      "stale": qa_public.get("stale"), "stale_reasons": qa_public.get("stale_reasons", [])}
        if qa_public.get("stale"):
            errors.append("published QA is stale for current PR HEAD or approved contract")
        if qa_status not in {"pass", "not_applicable"}:
            errors.append(f"published QA result must be pass or not_applicable; got {qa_status}")
    except (QAError, ValueError) as exc:
        errors.append(f"published QA is invalid: {exc}")

    independent_review_status = None
    independent_review = None
    try:
        independent = validate_public_pr_review(issue, pr, gh, issue_obj=issue_obj, pull=pull)
        if (evidence_contract_comment_id is not None
                and independent.get("current_contract_comment_id") != evidence_contract_comment_id
                or evidence_contract_sha256 is not None
                and independent.get("current_contract_sha256") != evidence_contract_sha256):
            errors.append("independent review was validated against a different approved Implementation Contract")
        independent_review_status = "pass" if independent.get("passed") else "blocked"
        independent_review = {"comment_id": independent.get("comment_id"),
                              "sha256": independent.get("sha256"), "head": independent.get("head"),
                              "fresh_context": independent.get("fresh_context"),
                              "stale": independent.get("stale"),
                              "stale_reasons": independent.get("stale_reasons", []),
                              "contract_units_pass": independent.get("contract_units_pass"),
                              "contract_unit_fail_count": independent.get("contract_unit_fail_count", 0),
                              "contract_unit_untested_count": independent.get("contract_unit_untested_count", 0),
                              "checklist_fail_count": independent.get("checklist_fail_count"),
                              "finding_count": independent.get("finding_count"),
                              "blocking_finding_count": independent.get("blocking_finding_count"),
                              "blocking_findings": independent.get("blocking_findings", [])}
        if independent.get("stale") or independent.get("head") != head:
            errors.append("published independent review is stale for current PR HEAD, contract, or checklist")
        if not independent.get("contract_units_pass"):
            errors.append("independent review requires every Implementation Contract unit to PASS")
        if independent.get("checklist_fail_count", 0):
            errors.append("independent review contains failed Reviewer Checklist items")
        if independent.get("blocking_finding_count", 0):
            errors.append(f"independent review has {independent['blocking_finding_count']} blocking finding(s)")
    except (ReviewError, ValueError) as exc:
        errors.append(f"published independent review is invalid: {exc}")

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
    try:
        final_issue = gh.issue(issue)
        final_pull = gh.pull(pr)
        _identity(final_issue, final_pull, issue, pr, gh)
        gate_issue = final_issue
        final_head_obj = final_pull.get("head") if isinstance(final_pull.get("head"), dict) else {}
        final_head = final_head_obj.get("sha")
        final_body = final_pull.get("body")
        if not isinstance(final_body, str):
            raise DeliveryError("final PR body is missing or malformed")
        gate_pull_body = final_body
        if final_issue.get("state") != "open" or final_pull.get("state") != "open" or final_pull.get("draft"):
            errors.append("Issue or PR state changed while delivery evidence was being validated")
        if final_head != head:
            errors.append("PR HEAD changed while delivery evidence was being validated")
        if final_pull.get("body") != snapshot_pr_body:
            errors.append("PR body changed after evidence validation (current-evidence-state race)")
        if final_issue.get("body") != snapshot_issue_body:
            errors.append("Issue body changed after evidence validation (current-evidence-state race)")
        final_states = (final_issue.get("state"), final_pull.get("state"),
                        final_pull.get("draft"), final_pull.get("merged"))
        if final_states != snapshot_states:
            errors.append("Issue/PR open/draft/merged state changed after evidence validation")
        final_has_review_phase = "phase:review" in _labels(final_issue)
        if final_has_review_phase != snapshot_has_review_phase:
            errors.append("Issue phase:review presence changed after evidence validation")
        if not final_has_review_phase:
            errors.append("Issue phase changed while delivery evidence was being validated")
        if not re.search(rf"(?im)^\s*closes\s+#{issue}\b", final_body):
            errors.append("final PR body no longer contains Closes #N")
        if _section(final_body, "Verification") is None or _section(final_body, "Untested") is None:
            errors.append("final PR Verification or Untested field is empty")
        final_surface = load_review_surface(issue, final_issue.get("body") or "", gh)
        expected_contract_id = evidence_contract_comment_id or contract_comment_id
        expected_contract_sha = evidence_contract_sha256 or contract_sha256
        if ((expected_contract_id is not None and final_surface["contract_comment_id"] != expected_contract_id)
                or (expected_contract_sha is not None and final_surface["contract_sha256"] != expected_contract_sha)):
            errors.append("approved Implementation Contract changed while delivery evidence was being validated")
    except (ReviewError, ValueError, GitHubError) as exc:
        errors.append(f"could not confirm current Issue/PR/contract after evidence validation: {exc}")
    affected = affected_components(gate_issue.get("body") or "", profile)
    generic = any("generic" in c.get("application_types", []) for c in affected)
    if generic and not re.search(r"(?im)^\s*Generic profile rationale:\s*\S.+$", gate_pull_body):
        errors.append("PR affecting a generic component requires a concrete Generic profile rationale:")
    return {"gate": "handoff", "passed": not errors, "errors": errors,
            "issue": issue, "pr": pr, "head": head, "required_checks": checks,
            "review_failures": review_failures, "review_failure_count": review_failure_count,
            "contract_review_failures": contract_review_failures,
            "contract_review_failure_count": contract_review_failure_count,
            "contract_review_untested": contract_review_untested,
            "contract_review_untested_count": contract_review_untested_count,
            "contract_comment_id": contract_comment_id,
            "contract_sha256": contract_sha256,
            "review_schema_version": review_schema_version,
            "final_verification_status": final_verification_status,
            "final_verification": final_verification,
            "qa_status": qa_status,
            "qa": qa_summary,
            "independent_review_status": independent_review_status,
            "independent_review": independent_review,
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
