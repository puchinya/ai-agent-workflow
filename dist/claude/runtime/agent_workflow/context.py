"""Read-only, compact Issue and project-profile routing context."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .documents import resolve_document_impact, section_body
from .github import GitHub
from .profile import ProfileError, load_profile, normalize_arch, normalize_host


class ContextError(ValueError):
    pass


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=repo, check=False, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def affected_components(issue_body: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    components = profile.get("components", []) if profile.get("schema_version") == 2 else []
    by_id = {item["id"]: item for item in components}
    raw_section = section_body(issue_body or "", "Affected components")
    if raw_section is None:
        if len(components) == 1:
            return [components[0]]
        if len(components) > 1:
            raise ContextError("multi-component profile requires a non-empty ## Affected components section")
        return []
    selected: list[str] = []
    for line in raw_section.splitlines():
        if not line.strip():
            continue
        match = re.match(r"^\s*[-*+]\s+(.+?)\s*$", line)
        if match:
            value = match.group(1).strip()
            if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
                value = value[1:-1]
            selected.append(value)
        else:
            raise ContextError("## Affected components must contain only component ID bullets")
    if not selected:
        raise ContextError("## Affected components section must contain one or more component IDs")
    unknown = [cid for cid in selected if cid not in by_id]
    if unknown:
        raise ContextError(f"unknown affected component ID(s): {', '.join(unknown)}")
    if len(set(selected)) != len(selected):
        raise ContextError("## Affected components contains duplicate IDs")
    # Preserve project profile order, not Issue prose order.
    return [component for component in components if component["id"] in selected]


def _contract_pointer(body: str) -> dict[str, Any] | None:
    section = section_body(body or "", "Implementation Contract")
    if not section:
        return None
    values = {}
    for line in section.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            values[key.strip()] = value.strip()
    if not values:
        return None
    return {"comment_id": values.get("Comment ID"), "sha256": values.get("SHA-256"),
            "state": values.get("State")}


def _pull_requests(issue_number: int, gh: GitHub) -> list[dict[str, Any]]:
    results = []
    for event in gh.issue_events(issue_number):
        source = (event.get("source") or {}).get("issue") or {}
        if "pull_request" in source and isinstance(source.get("number"), int):
            results.append({"number": source["number"], "url": source.get("html_url"), "state": source.get("state")})
    unique = {item["number"]: item for item in results}
    return list(unique.values())


def build_context(repo: Path, issue_number: int, gh: GitHub, runtime_host: str | None = None,
                  architecture: str | None = None) -> dict[str, Any]:
    issue = gh.issue(issue_number)
    expected_url = f"https://api.github.com/repos/{gh.repo}"
    if issue.get("number") != issue_number or issue.get("repository_url") != expected_url or issue.get("pull_request"):
        raise ContextError("requested Issue identity does not match configured repository")
    profile = load_profile(repo, allow_uninitialized=True)
    labels = {str(item.get("name", "")) for item in issue.get("labels", [])}
    phase_labels = sorted(label for label in labels if label.startswith("phase:"))
    if issue.get("state") == "closed":
        phase = "closed"
    elif len(phase_labels) > 1:
        raise ContextError(f"Issue has ambiguous phase labels: {', '.join(phase_labels)}")
    else:
        phase = phase_labels[0].split(":", 1)[1] if phase_labels else None
    closed = issue.get("state") == "closed"
    chosen = [] if closed else affected_components(issue.get("body") or "", profile)
    owners, planned, document_impact, link_diagnostics = (
        ([], [], None, []) if closed else resolve_document_impact(issue.get("body") or "", repo, gh.repo)
    )
    app_types = sorted({app for component in chosen for app in component.get("application_types", []) if app != "generic"})
    context = {
        "issue": {"number": issue_number, "url": issue.get("html_url"), "state": issue.get("state"),
                  "phase": phase, "labels": sorted(labels)},
        "workflow": None if closed else {"active": True, "phase": phase},
        "repository": gh.repo,
        "branch": _git(repo, "branch", "--show-current"),
        "head": _git(repo, "rev-parse", "HEAD"),
        "pull_requests": _pull_requests(issue_number, gh),
        "implementation_contract": _contract_pointer(issue.get("body") or ""),
        "profile": {"schema_version": profile.get("schema_version"), "initialized": profile.get("initialized", True),
                    "runtime_host": f"{normalize_host(runtime_host)}/{normalize_arch(architecture)}"},
        "affected_components": [{"id": component["id"], "roots": component.get("roots", []),
                                 "stacks": component.get("stacks", []),
                                 "application_types": component.get("application_types", []),
                                 "targets": [target.get("id") for target in component.get("targets", [])]}
                                for component in chosen],
        "application_profile_paths": [f"workflow/standards/application-profiles/{app}.md" for app in app_types],
        "document_owners": owners,
        "planned_owners": planned,
        "document_impact": document_impact,
        "diagnostics": link_diagnostics[:12],
    }
    return context


def format_context(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
