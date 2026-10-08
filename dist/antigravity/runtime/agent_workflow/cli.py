"""Command-line entry point for local workflow operations."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .context import ContextError, affected_components, build_context, format_context
from .contracts import (ContractError, publish_contract, restore_contract, save_contract,
                        validate_contract_structure, verify_contract)
from .delivery import DeliveryError, delivery_check, ensure_review_pr, finalize_merged_issue
from .documents import resolve_document_impact, validate_docs
from .execution import ExecutionError, prepare_implementation, resolve_implementation_base
from .github import GitHub, GitHubError, discover_repository
from .git import GitLifecycleError, changed_document_paths, start_feature_branch
from .profile import (APPLICATION_TYPES, ProfileError, build_hook_plan, load_profile,
                      normalize_host, validate_profile)
from .process import ProcessError, run_command
from .qa import QAError, prepare_qa, publish_qa, validate_public_qa, validate_qa
from .review import (ReviewError, load_review, load_review_surface, prepare_review,
                     prepare_pr_review, pr_review_path, publish_pr_review, publish_review,
                     review_path, validate_pr_review, validate_public_pr_review,
                     validate_public_review)
from .versioning import VersionError, resolve_milestone_version
from .verification import VerificationError, validate_public_final_verification, verify_final


class CLIError(RuntimeError):
    pass


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _repo_arg(value: str | None = None) -> Path:
    start = Path(value or os.getcwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise CLIError("could not find repository root (.git)")


def _gh(repo: Path) -> GitHub:
    return GitHub(discover_repository(repo))


def _number(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("Issue and PR numbers must be positive integers")
    return int(value)


def _detect_stacks(repo: Path) -> list[str]:
    candidates = [("python", "pyproject.toml"), ("rust", "Cargo.toml"),
                  ("javascript", "package.json"), ("go", "go.mod")]
    return [name for name, marker in candidates if (repo / marker).is_file()]


def _init_project(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_arg(args.repo)
    destination = repo / ".agent" / "project.json"
    if destination.exists():
        raise ProfileError(f"project profile already exists and will not be rewritten: {destination}")
    app_types = ([part.strip() for value in args.application_type for part in value.split(",") if part.strip()]
                 if args.application_type else ["generic"])
    if any(value not in APPLICATION_TYPES for value in app_types):
        raise ProfileError(f"application type must be one of: {', '.join(sorted(APPLICATION_TYPES))}")
    stacks = ([part.strip() for value in args.stack for part in value.split(",") if part.strip()]
              if args.stack is not None else _detect_stacks(repo))
    target_ids = [part.strip() for value in args.target for part in value.split(",") if part.strip()]
    if len(set(target_ids)) != len(target_ids):
        raise ProfileError("--target values must be unique")
    component_hooks = {"verify_quick": [], "verify_final": []}
    targets = [{"id": target, "runnable_on": ["any"],
                "hooks": {"verify_quick": [], "verify_final": []}} for target in target_ids]
    global_hooks = {"branch_switch": ["cargo clean"] if args.cargo_clean == "on" and "rust" in stacks else [],
                    "verify_quick": [], "verify_final": []}
    profile = {"schema_version": 2, "initialized": True,
               "project_name": args.name or repo.name,
               "components": [{"id": "root", "roots": ["."], "stacks": stacks,
                               "application_types": app_types, "targets": targets,
                               "hooks": component_hooks}],
               "branch": {"prefix": "feature", "max_slug_length": 48,
                          "cleanup_on_switch": [], "required_checks": []},
               "workspace": {"isolation": "auto"},
               "milestones": {"mode": "auto", "version_source": "auto"}, "hooks": global_hooks}
    validate_profile(profile, repo)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
    # Exclusive creation protects against a concurrent initializer.
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
    return {"path": str(destination), "profile": profile,
            "warning": "generic application type selected; choose an explicit application profile when known" if "generic" in app_types else None}


def _issue_components(issue_number: int, repo: Path, gh: GitHub, profile: dict[str, Any]) -> list[str]:
    issue = gh.issue(issue_number)
    if issue.get("number") != issue_number or issue.get("repository_url") != f"https://api.github.com/repos/{gh.repo}" or issue.get("pull_request"):
        raise ContextError("Issue identity does not match configured repository")
    if issue.get("state") != "open":
        raise ContextError("closed Issue has no active workflow to route hooks")
    return [component["id"] for component in affected_components(issue.get("body") or "", profile)]


def _workflow_issue(issue_number: int, gh: GitHub) -> dict[str, Any]:
    issue = gh.issue(issue_number)
    expected_url = f"https://api.github.com/repos/{gh.repo}"
    if (not isinstance(issue, dict) or not isinstance(issue.get("number"), int)
            or isinstance(issue.get("number"), bool) or issue.get("number") != issue_number
            or issue.get("repository_url") != expected_url or issue.get("pull_request")):
        raise ContextError("Issue identity does not match configured repository or the identifier is a pull request")
    if issue.get("state") != "open":
        raise ContextError("Issue must be open for milestone or feature branch lifecycle operations")
    return issue


def _ensure_milestone(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_arg(args.repo)
    profile = load_profile(repo)
    if profile.get("schema_version") != 2:
        raise ProfileError("ensure-milestone requires a Schema 2 project profile")
    gh = _gh(repo)
    issue = _workflow_issue(args.issue, gh)
    policy = profile["milestones"]
    if policy["mode"] == "disabled":
        return {"issue": args.issue, "status": "DISABLED"}
    version, version_origin = resolve_milestone_version(
        repo, policy["version_source"], getattr(args, "target_version", None)
    )
    if version is None:
        if policy["mode"] == "required":
            raise VersionError("required milestone mode has no resolvable version")
        return {"issue": args.issue, "status": "NOT_APPLICABLE", "reason": "version_unresolved",
                "version": None, "version_origin": version_origin}

    existing = issue.get("milestone")
    if existing is not None:
        if (not isinstance(existing, dict) or not isinstance(existing.get("number"), int)
                or isinstance(existing.get("number"), bool) or existing.get("number") < 1):
            raise GitHubError("Issue milestone metadata is invalid")
        current_title = existing.get("title") if isinstance(existing.get("title"), str) else None
        if current_title is not None and current_title != version:
            raise GitHubError(
                f"Issue already belongs to a different milestone '{current_title}' "
                f"(#{existing['number']}); requested milestone '{version}'"
            )

    milestones = gh.milestones()
    current_title = None
    if existing is not None:
        current_title = existing.get("title") if isinstance(existing.get("title"), str) else None
        if current_title is None:
            current = next((item for item in milestones if item.get("number") == existing["number"]), None)
            current_title = current.get("title") if isinstance(current, dict) and isinstance(current.get("title"), str) else None
        if current_title is not None and current_title != version:
            raise GitHubError(
                f"Issue already belongs to a different milestone '{current_title}' "
                f"(#{existing['number']}); requested milestone '{version}'"
            )

    matches = [item for item in milestones if item.get("title") == version]
    if len(matches) > 1:
        raise GitHubError("multiple exact-title milestones already exist")
    milestone = matches[0] if matches else None
    if milestone is not None:
        if (not isinstance(milestone.get("number"), int) or isinstance(milestone.get("number"), bool)
                or milestone.get("number") < 1):
            raise GitHubError("exact-title milestone is missing a valid number")
        if milestone.get("state") != "open":
            raise GitHubError("exact-title milestone is closed")

    if existing is not None:
        if milestone is None or existing.get("number") != milestone.get("number"):
            current = f"'{current_title}' (#{existing['number']})" if current_title is not None else f"#{existing['number']}"
            raise GitHubError(
                f"Issue already belongs to a different milestone {current}; requested milestone '{version}'"
            )
        return {"issue": args.issue, "status": "ASSIGNED", "milestone": milestone["number"],
                "created": False, "assigned": False, "version": version,
                "version_origin": version_origin}

    created = milestone is None
    if created:
        milestone = gh.create_milestone(version)
        matches = [item for item in gh.milestones() if item.get("title") == version]
        if (len(matches) != 1 or not isinstance(matches[0].get("number"), int)
                or isinstance(matches[0].get("number"), bool)
                or matches[0].get("number") != milestone.get("number") or matches[0].get("state") != "open"):
            raise GitHubError("new exact-title milestone could not be verified as unique and open")
        milestone = matches[0]
    gh.assign_issue_milestone(args.issue, milestone["number"])
    return {"issue": args.issue, "status": "ASSIGNED", "milestone": milestone["number"],
            "created": created, "assigned": True, "version": version,
            "version_origin": version_origin}


def _start_feature_branch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    repo = _repo_arg(args.repo)
    profile = load_profile(repo)
    if profile.get("schema_version") != 2:
        raise ProfileError("start-feature-branch requires a Schema 2 project profile")
    gh = _gh(repo)
    _workflow_issue(args.issue, gh)
    return start_feature_branch(repo, profile, args.issue, " ".join(args.description), gh,
                                getattr(args, "base_ref", None), getattr(args, "expected_base_sha", None))


def _ensure_review_pr(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    repo = _repo_arg(args.repo)
    try:
        body = args.body_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CLIError("could not read --body-file as UTF-8 text") from exc
    result = ensure_review_pr(repo, args.issue, body, _gh(repo), args.title, args.base_ref)
    return result, 0 if result.get("success") else 1


def _validate_docs(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    repo = _repo_arg(args.repo)
    if args.issue is not None:
        gh = _gh(repo)
        issue = gh.issue(args.issue)
        expected_repo = f"https://api.github.com/repos/{gh.repo}"
        if (issue.get("number") != args.issue or issue.get("repository_url") != expected_repo
                or issue.get("pull_request") is not None):
            raise ContextError("Issue identity does not match configured repository or the identifier is a pull request")
        owners, planned, impact, diagnostics = resolve_document_impact(issue.get("body") or "", repo, gh.repo)
        errors = list(diagnostics)
        errors.extend(f"linked planned document owner is missing: {path}" for path in planned)
        errors.extend(validate_docs(repo, [repo / path for path in owners]))
        result = {"valid": not errors, "scope": "issue", "issue": args.issue,
                  "files": len(owners), "document_impact": impact, "errors": errors}
        return result, 0 if not errors else 1
    if args.changed is not None:
        paths = changed_document_paths(repo, args.changed)
        errors = validate_docs(repo, paths)
        result = {"valid": not errors, "scope": "changed", "base": args.changed,
                  "files": len(paths), "errors": errors}
        return result, 0 if not errors else 1
    errors = validate_docs(repo)
    count = len(list((repo / "docs").rglob("*.md"))) if (repo / "docs").exists() else 0
    return {"valid": not errors, "files": count, "errors": errors}, 0 if not errors else 1


def _do_hook(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_arg(args.repo)
    profile = load_profile(repo)
    if args.hook == "branch_switch":
        if args.issue or args.component or args.capability:
            raise ProfileError("branch_switch accepts global hooks only; selectors are not allowed")
        selected = None
    else:
        if args.issue and args.component:
            raise ProfileError("--issue and --component are mutually exclusive")
        if args.issue and profile.get("schema_version") == 1:
            raise ProfileError("Issue routing requires a Schema 2 component profile")
        if args.component and profile.get("schema_version") == 1:
            raise ProfileError("--component cannot be used with a flat Schema 1 profile")
        if args.issue and args.hook != "verify_quick":
            raise ProfileError("--issue only applies to verify_quick")
        selected = args.component or None
        if args.issue:
            selected = _issue_components(args.issue, repo, _gh(repo), profile)
    plan = build_hook_plan(profile, args.hook, selected, args.runtime_host, args.architecture, args.capability)
    result = {"executed": [], "skipped_targets": []}
    for skipped in plan.skipped:
        entry = {"component": skipped.component, "target": skipped.target, "reason": skipped.reason}
        result["skipped_targets"].append(entry)
        print(f"SKIPPED_TARGET_VERIFICATION component={skipped.component} target={skipped.target} reason={skipped.reason}")
    for step in plan.steps:
        completed = run_command(step.command, repo, diagnostic=getattr(args, "diagnostic", False))
        result["executed"].append({"component": step.component, "target": step.target,
                                   "returncode": completed.returncode})
    return result


def _validate_self_review(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_arg(args.repo)
    path = args.input or review_path(repo, args.issue, args.pr)
    draft = load_review(path)
    if draft.get("issue") != args.issue or draft.get("pr") != args.pr:
        raise ReviewError("self-review draft does not match requested Issue and PR")
    gh = _gh(repo)
    pull = gh.pull(args.pr)
    issue = gh.issue(args.issue)
    if (not isinstance(issue, dict) or type(issue.get("number")) is not int
            or issue.get("number") != args.issue
            or issue.get("repository_url") != f"https://api.github.com/repos/{gh.repo}"
            or issue.get("pull_request")):
        raise ReviewError("Issue identity does not match configured repository")
    base = pull.get("base") if isinstance(pull, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    full_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    if (not isinstance(pull, dict) or type(pull.get("number")) is not int or pull.get("number") != args.pr
            or not isinstance(full_name, str) or full_name.casefold() != gh.repo.casefold()):
        raise ReviewError("PR repository identity mismatch")
    surface = load_review_surface(args.issue, issue.get("body") or "", gh)
    head_data = pull.get("head")
    current_head = head_data.get("sha") if isinstance(head_data, dict) else None
    if current_head != draft.get("head"):
        raise ReviewError("self-review draft is stale for current PR HEAD")
    if draft.get("contract_comment_id") != surface["contract_comment_id"]:
        raise ReviewError("self-review draft is stale for the current approved Implementation Contract comment ID")
    if draft.get("contract_sha256") != surface["contract_sha256"]:
        raise ReviewError("self-review draft is stale for the current approved Implementation Contract SHA")
    if [(s["id"], s["title"], s["section_sha256"]) for s in draft["contract_sections"]] != [
        (s["id"], s["title"], s["section_sha256"]) for s in surface["contract_sections"]
    ]:
        raise ReviewError("self-review contract sections are stale for the current approved contract")
    if draft.get("checklist_sha256") != surface["checklist_sha256"]:
        raise ReviewError("self-review draft is stale for the current effective Reviewer Checklist")
    if [(i["id"], i["text"]) for i in draft["items"]] != [
        (i["id"], i["text"]) for i in surface["items"]
    ]:
        raise ReviewError("self-review items do not match effective checklist")
    return {
        "valid": True,
        "schema_version": 2,
        "items": len(draft["items"]),
        "contract_section_count": len(draft["contract_sections"]),
        "head": draft["head"],
        "contract_comment_id": surface["contract_comment_id"],
        "contract_sha256": surface["contract_sha256"],
        "checklist_sha256": surface["checklist_sha256"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agent_workflow")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init-project")
    init.add_argument("--repo")
    init.add_argument("--name")
    init.add_argument("--stack", action="append")
    init.add_argument("--application-type", action="append")
    init.add_argument("--target", action="append", default=[])
    init.add_argument("--cargo-clean", choices=("on", "off"), default="off")

    ctx = commands.add_parser("agent-context")
    ctx.add_argument("issue", type=_number)
    ctx.add_argument("--runtime-host", choices=("windows", "macos", "linux"))
    ctx.add_argument("--architecture")
    ctx.add_argument("--repo")

    docs = commands.add_parser("validate-docs")
    doc_scope = docs.add_mutually_exclusive_group()
    doc_scope.add_argument("--issue", type=_number)
    doc_scope.add_argument("--changed", metavar="BASE")
    docs.add_argument("--repo")

    milestone = commands.add_parser("ensure-milestone")
    milestone.add_argument("issue", type=_number)
    milestone.add_argument("--target-version", metavar="VERSION")
    milestone.add_argument("--repo")

    feature = commands.add_parser("start-feature-branch")
    feature.add_argument("issue", type=_number)
    feature.add_argument("description", nargs="+")
    feature.add_argument("--base-ref", metavar="BRANCH")
    feature.add_argument("--expected-base-sha", metavar="SHA40")
    feature.add_argument("--repo")

    resolve_base = commands.add_parser("resolve-implementation-base")
    resolve_base.add_argument("issue", type=_number)
    resolve_base.add_argument("--base-ref", metavar="BRANCH")
    resolve_base.add_argument("--expected-base-sha", metavar="SHA40")
    resolve_base.add_argument("--repo")

    implementation = commands.add_parser("prepare-implementation")
    implementation.add_argument("issue", type=_number)
    implementation.add_argument("--base-ref", metavar="BRANCH")
    implementation.add_argument("--expected-base-sha", metavar="SHA40")
    implementation.add_argument("--mode", choices=("isolated", "current"), required=True)
    implementation.add_argument("--supersede", action="store_true")
    implementation.add_argument("--repo")

    review_pr = commands.add_parser("ensure-review-pr")
    review_pr.add_argument("issue", type=_number)
    review_pr.add_argument("--body-file", type=Path, required=True)
    review_pr.add_argument("--title")
    review_pr.add_argument("--base-ref", metavar="BRANCH")
    review_pr.add_argument("--repo")

    hook = commands.add_parser("run-hook")
    hook.add_argument("hook", choices=("branch_switch", "verify_quick", "verify_final"))
    scopes = hook.add_mutually_exclusive_group()
    scopes.add_argument("--component", action="append")
    scopes.add_argument("--issue", type=_number)
    hook.add_argument("--runtime-host", choices=("windows", "macos", "linux"))
    hook.add_argument("--architecture")
    hook.add_argument("--capability", action="append", default=[])
    hook.add_argument("--diagnostic", action="store_true")
    hook.add_argument("--repo")

    final = commands.add_parser("verify-final")
    final.add_argument("issue", type=_number)
    final.add_argument("pr", type=_number)
    final.add_argument("--runtime-host", choices=("windows", "macos", "linux"))
    final.add_argument("--architecture")
    final.add_argument("--capability", action="append", default=[])
    final.add_argument("--diagnostic", action="store_true")
    final.add_argument("--repo")

    public_final = commands.add_parser("validate-public-final-verification")
    public_final.add_argument("issue", type=_number)
    public_final.add_argument("pr", type=_number)
    public_final.add_argument("--repo")

    save = commands.add_parser("save-implementation-contract")
    save.add_argument("issue", type=_number)
    save.add_argument("path", nargs="?", type=Path)
    save.add_argument("--repo")
    structure = commands.add_parser("validate-implementation-contract-structure")
    structure.add_argument("issue", type=_number)
    structure.add_argument("path", type=Path)
    structure.add_argument("--repo")
    publish = commands.add_parser("publish-implementation-contract")
    publish.add_argument("issue", type=_number)
    publish.add_argument("--source", type=Path)
    publish.add_argument("--supersede", action="store_true")
    publish.add_argument("--repo")
    restore = commands.add_parser("restore-implementation-contract")
    restore.add_argument("issue", type=_number)
    restore.add_argument("--replace-stale", action="store_true")
    restore.add_argument("--repo")
    verify = commands.add_parser("verify-implementation-contract")
    verify.add_argument("issue", type=_number)
    verify.add_argument("--repo")

    prep = commands.add_parser("prepare-self-review")
    prep.add_argument("issue", type=_number)
    prep.add_argument("pr", type=_number)
    prep.add_argument("--repo")
    val = commands.add_parser("validate-self-review")
    val.add_argument("issue", type=_number)
    val.add_argument("pr", type=_number)
    val.add_argument("--input", type=Path)
    val.add_argument("--repo")
    pub = commands.add_parser("publish-self-review")
    pub.add_argument("issue", type=_number)
    pub.add_argument("pr", type=_number)
    pub.add_argument("--input", type=Path)
    pub.add_argument("--repo")
    public = commands.add_parser("validate-public-review")
    public.add_argument("issue", type=_number)
    public.add_argument("pr", type=_number)
    public.add_argument("--repo")

    prepare_independent = commands.add_parser("prepare-pr-review")
    prepare_independent.add_argument("issue", type=_number)
    prepare_independent.add_argument("pr", type=_number)
    prepare_independent.add_argument("--repo")
    validate_independent = commands.add_parser("validate-pr-review")
    validate_independent.add_argument("issue", type=_number)
    validate_independent.add_argument("pr", type=_number)
    validate_independent.add_argument("--input", type=Path)
    validate_independent.add_argument("--repo")
    publish_independent = commands.add_parser("publish-pr-review")
    publish_independent.add_argument("issue", type=_number)
    publish_independent.add_argument("pr", type=_number)
    publish_independent.add_argument("--input", type=Path)
    publish_independent.add_argument("--repo")
    validate_public_independent = commands.add_parser("validate-public-pr-review")
    validate_public_independent.add_argument("issue", type=_number)
    validate_public_independent.add_argument("pr", type=_number)
    validate_public_independent.add_argument("--repo")

    prepare_qa_cmd = commands.add_parser("prepare-qa")
    prepare_qa_cmd.add_argument("issue", type=_number)
    prepare_qa_cmd.add_argument("pr", type=_number)
    prepare_qa_cmd.add_argument("--repo")
    validate_qa_cmd = commands.add_parser("validate-qa")
    validate_qa_cmd.add_argument("issue", type=_number)
    validate_qa_cmd.add_argument("pr", type=_number)
    validate_qa_cmd.add_argument("--input", type=Path)
    validate_qa_cmd.add_argument("--repo")
    publish_qa_cmd = commands.add_parser("publish-qa")
    publish_qa_cmd.add_argument("issue", type=_number)
    publish_qa_cmd.add_argument("pr", type=_number)
    publish_qa_cmd.add_argument("--input", type=Path)
    publish_qa_cmd.add_argument("--repo")
    public_qa_cmd = commands.add_parser("validate-public-qa")
    public_qa_cmd.add_argument("issue", type=_number)
    public_qa_cmd.add_argument("pr", type=_number)
    public_qa_cmd.add_argument("--repo")

    gate = commands.add_parser("delivery-check")
    gate.add_argument("issue", type=_number)
    gate.add_argument("pr", type=_number)
    gate.add_argument("--repo")
    finalize = commands.add_parser("finalize-merged-issue")
    finalize.add_argument("issue", type=_number)
    finalize.add_argument("pr", type=_number)
    finalize.add_argument("--repo")
    return parser


def _dispatch(args: argparse.Namespace) -> tuple[Any, int]:
    if args.command == "init-project":
        result = _init_project(args)
    elif args.command == "agent-context":
        repo = _repo_arg(args.repo)
        result = build_context(repo, args.issue, _gh(repo), args.runtime_host, args.architecture)
    elif args.command == "validate-docs":
        return _validate_docs(args)
    elif args.command == "ensure-milestone":
        result = _ensure_milestone(args)
    elif args.command == "start-feature-branch":
        return _start_feature_branch(args)
    elif args.command == "resolve-implementation-base":
        repo = _repo_arg(args.repo)
        result = resolve_implementation_base(
            repo, args.issue, _gh(repo), base_ref=args.base_ref,
            expected_base_sha=args.expected_base_sha,
        )
    elif args.command == "prepare-implementation":
        repo = _repo_arg(args.repo)
        result = prepare_implementation(
            repo, args.issue, _gh(repo), mode=args.mode, base_ref=args.base_ref,
            expected_base_sha=args.expected_base_sha, supersede=args.supersede,
        )
    elif args.command == "ensure-review-pr":
        return _ensure_review_pr(args)
    elif args.command == "run-hook":
        result = _do_hook(args)
    elif args.command == "verify-final":
        repo = _repo_arg(args.repo)
        result = verify_final(repo, args.issue, args.pr, _gh(repo),
                              runtime_host=args.runtime_host, architecture=args.architecture,
                              capabilities=args.capability, diagnostic=args.diagnostic)
        return result, 0 if result["result"] == "pass" else 1
    elif args.command == "validate-public-final-verification":
        repo = _repo_arg(args.repo)
        result = validate_public_final_verification(args.issue, args.pr, _gh(repo))
        return result, 1 if result["stale"] else 0
    elif args.command == "save-implementation-contract":
        repo = _repo_arg(args.repo)
        result = save_contract(repo, args.issue, args.path)
    elif args.command == "validate-implementation-contract-structure":
        if not args.path.is_file():
            raise ContractError("Implementation Contract path must name an existing regular file")
        try:
            raw = args.path.read_bytes()
        except OSError as exc:
            raise ContractError("could not read Implementation Contract path") from exc
        result = validate_contract_structure(raw, args.issue)
    elif args.command == "publish-implementation-contract":
        repo = _repo_arg(args.repo)
        result = publish_contract(repo, args.issue, _gh(repo), args.source, args.supersede)
    elif args.command == "restore-implementation-contract":
        repo = _repo_arg(args.repo)
        result = restore_contract(repo, args.issue, _gh(repo), args.replace_stale)
    elif args.command == "verify-implementation-contract":
        repo = _repo_arg(args.repo)
        result = verify_contract(repo, args.issue, _gh(repo))
    elif args.command == "prepare-self-review":
        repo = _repo_arg(args.repo)
        result = prepare_review(repo, args.issue, args.pr, _gh(repo))
    elif args.command == "validate-self-review":
        result = _validate_self_review(args)
    elif args.command == "publish-self-review":
        repo = _repo_arg(args.repo)
        result = publish_review(repo, args.issue, args.pr, _gh(repo), args.input)
    elif args.command == "validate-public-review":
        repo = _repo_arg(args.repo)
        result = validate_public_review(args.issue, args.pr, _gh(repo))
        result = {key: result[key] for key in (
            "comment_id", "sha256", "head", "contract_comment_id", "current_contract_comment_id",
            "contract_sha256", "current_contract_sha256",
            "contract_section_count", "current_contract_section_count", "checklist_sha256",
            "schema_version", "contract_conformance", "stale", "stale_reasons", "current_head",
        )}
        return result, 1 if result["stale"] else 0
    elif args.command == "prepare-pr-review":
        repo = _repo_arg(args.repo)
        result = prepare_pr_review(repo, args.issue, args.pr, _gh(repo))
    elif args.command == "validate-pr-review":
        repo = _repo_arg(args.repo)
        result = validate_pr_review(repo, args.issue, args.pr, _gh(repo), args.input)
        return result, 0 if result["passed"] else 1
    elif args.command == "publish-pr-review":
        repo = _repo_arg(args.repo)
        result = publish_pr_review(repo, args.issue, args.pr, _gh(repo), args.input)
    elif args.command == "validate-public-pr-review":
        repo = _repo_arg(args.repo)
        result = validate_public_pr_review(args.issue, args.pr, _gh(repo))
        result = {key: result[key] for key in (
            "comment_id", "sha256", "head", "contract_comment_id", "current_contract_comment_id",
            "contract_sha256", "current_contract_sha256", "checklist_sha256", "fresh_context",
            "contract_units_pass", "checklist_fail_count", "finding_count", "blocking_finding_count",
            "blocking_findings", "stale", "stale_reasons", "passed",
        )}
        return result, 0 if result["passed"] else 1
    elif args.command == "prepare-qa":
        repo = _repo_arg(args.repo)
        result = prepare_qa(repo, args.issue, args.pr, _gh(repo))
    elif args.command == "validate-qa":
        repo = _repo_arg(args.repo)
        result = validate_qa(repo, args.issue, args.pr, _gh(repo), args.input)
        return result, 0 if result["passed"] else 1
    elif args.command == "publish-qa":
        repo = _repo_arg(args.repo)
        result = publish_qa(repo, args.issue, args.pr, _gh(repo), args.input)
        return result, 0 if result["result"] in {"pass", "not_applicable"} else 1
    elif args.command == "validate-public-qa":
        repo = _repo_arg(args.repo)
        result = validate_public_qa(args.issue, args.pr, _gh(repo))
        result = {key: result[key] for key in (
            "comment_id", "sha256", "result", "passed", "stale", "stale_reasons",
            "current_head", "current_contract_comment_id", "current_contract_sha256",
        )}
        return result, 0 if result["passed"] else 1
    elif args.command == "delivery-check":
        repo = _repo_arg(args.repo)
        result = delivery_check(repo, args.issue, args.pr, _gh(repo))
        return result, 0 if result["passed"] else 1
    elif args.command == "finalize-merged-issue":
        repo = _repo_arg(args.repo)
        result = finalize_merged_issue(args.issue, args.pr, _gh(repo))
    else:
        raise CLIError(f"unsupported command: {args.command}")
    return result, 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result, status = _dispatch(args)
        if args.command == "agent-context":
            print(format_context(result))
        else:
            _json(result)
        return status
    except (ProfileError, ContextError, ContractError, ExecutionError, ReviewError, VerificationError, QAError, DeliveryError,
            GitHubError, GitLifecycleError, VersionError, ProcessError, CLIError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.returncode if isinstance(exc, ProcessError) else 1
