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
                        verify_contract)
from .delivery import DeliveryError, delivery_check, finalize_merged_issue
from .documents import validate_docs
from .github import GitHub, GitHubError, discover_repository
from .profile import (APPLICATION_TYPES, ProfileError, build_hook_plan, load_profile,
                      normalize_host, validate_profile)
from .process import ProcessError, run_command
from .review import (ReviewError, effective_checklist, load_review, prepare_review,
                     publish_review, review_path, validate_public_review)


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
               "branch": {"prefix": "feature", "max_slug_length": 48, "required_checks": []},
               "milestones": {"enabled": False, "version_source": "auto"}, "hooks": global_hooks}
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
        completed = run_command(step.command, repo)
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
    items, digest = effective_checklist(args.issue, issue.get("body") or "", gh)
    if pull.get("head", {}).get("sha") != draft.get("head") or digest != draft.get("checklist_sha256"):
        raise ReviewError("self-review draft is stale for current PR HEAD or checklist")
    if [(i["id"], i["text"]) for i in draft["items"]] != [(i["id"], i["text"]) for i in items]:
        raise ReviewError("self-review items do not match effective checklist")
    return {"valid": True, "items": len(draft["items"]), "head": draft["head"], "checklist_sha256": digest}


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
    docs.add_argument("--repo")

    hook = commands.add_parser("run-hook")
    hook.add_argument("hook", choices=("branch_switch", "verify_quick", "verify_final"))
    scopes = hook.add_mutually_exclusive_group()
    scopes.add_argument("--component", action="append")
    scopes.add_argument("--issue", type=_number)
    hook.add_argument("--runtime-host", choices=("windows", "macos", "linux"))
    hook.add_argument("--architecture")
    hook.add_argument("--capability", action="append", default=[])
    hook.add_argument("--repo")

    save = commands.add_parser("save-implementation-contract")
    save.add_argument("issue", type=_number)
    save.add_argument("path", nargs="?", type=Path)
    save.add_argument("--repo")
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
        repo = _repo_arg(args.repo)
        errors = validate_docs(repo)
        result = {"valid": not errors, "files": len(list((repo / "docs").rglob("*.md"))) if (repo / "docs").exists() else 0,
                  "errors": errors}
        return result, 0 if not errors else 1
    elif args.command == "run-hook":
        result = _do_hook(args)
    elif args.command == "save-implementation-contract":
        repo = _repo_arg(args.repo)
        result = save_contract(repo, args.issue, args.path)
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
        result = {key: result[key] for key in ("comment_id", "sha256", "head", "checklist_sha256", "stale", "current_head")}
        return result, 1 if result["stale"] else 0
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
    except (ProfileError, ContextError, ContractError, ReviewError, DeliveryError,
            GitHubError, ProcessError, CLIError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.returncode if isinstance(exc, ProcessError) else 1
