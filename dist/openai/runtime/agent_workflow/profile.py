"""Consumer project profile validation and deterministic hook planning."""

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable


APPLICATION_TYPES = {"generic", "desktop-gui", "cli", "mobile", "server", "embedded", "library"}
RUNNABLE_ON = {"any", "windows", "macos", "linux"}
VERIFICATION_HOOKS = {"verify_quick", "verify_final"}
GLOBAL_HOOKS = {"branch_switch", *VERIFICATION_HOOKS}
HOOKS = GLOBAL_HOOKS


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class HookStep:
    component: str
    target: str | None
    command: str


@dataclass(frozen=True)
class SkippedTarget:
    component: str
    target: str
    reason: str


@dataclass(frozen=True)
class HookPlan:
    steps: tuple[HookStep, ...]
    skipped: tuple[SkippedTarget, ...]
    components: tuple[dict[str, Any], ...]


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ProfileError(message)


def _hooks(value: Any, where: str, allowed: set[str] | None = None) -> dict[str, list[str]]:
    _need(isinstance(value, dict), f"{where} must be an object")
    allowed = allowed or VERIFICATION_HOOKS
    unknown = set(value) - allowed
    _need(not unknown, f"{where} contains unsupported hook(s): {', '.join(sorted(unknown))}")
    out: dict[str, list[str]] = {}
    for name, commands in value.items():
        _need(name in allowed and isinstance(commands, list), f"{where}.{name} must be an array")
        _need(all(isinstance(command, str) and command.strip() and "\x00" not in command for command in commands),
              f"{where}.{name} commands must be non-empty strings")
        out[name] = commands
    return out


def _safe_roots(roots: Any, where: str, repo: Path) -> list[str]:
    _need(isinstance(roots, list) and roots, f"{where}.roots must be a non-empty array")
    normalized: list[str] = []
    for raw in roots:
        _need(isinstance(raw, str) and raw, f"{where}.roots entries must be non-empty strings")
        _need("\x00" not in raw, f"{where}.roots entry contains a NUL byte")
        windows = PureWindowsPath(raw)
        normalized_path = PurePosixPath(raw.replace("\\", "/"))
        _need(not windows.is_absolute() and not windows.drive and not normalized_path.is_absolute()
              and ".." not in normalized_path.parts, f"{where} root escapes the repository: {raw}")
        path = Path(*normalized_path.parts)
        resolved = (repo / path).resolve()
        _need(resolved == repo.resolve() or repo.resolve() in resolved.parents,
              f"{where} root escapes the repository through a symlink: {raw}")
        normalized.append("." if normalized_path == PurePosixPath(".") else normalized_path.as_posix().rstrip("/"))
    return normalized


def validate_profile(data: Any, repo: Path) -> dict[str, Any]:
    _need(isinstance(data, dict), "project profile must be a JSON object")
    _need("schema_version" in data, "project profile must declare schema_version 1 or 2")
    version = data["schema_version"]
    _need(isinstance(version, int) and not isinstance(version, bool) and version in {1, 2},
          f"unsupported project profile schema_version: {version!r}")
    if version == 1:
        # Schema 1's flat hooks remain readable; never rewrite this document.
        _need(isinstance(data.get("project_name", "project"), str), "schema 1 project_name must be a string")
        if "hooks" in data:
            data = dict(data)
            data["hooks"] = _hooks(data["hooks"], "hooks", GLOBAL_HOOKS)
        return data

    _need(isinstance(data.get("initialized"), bool), "initialized must be boolean")
    _need(isinstance(data.get("project_name"), str) and bool(data["project_name"].strip()), "project_name must be non-empty")
    branch = data.get("branch", {})
    _need(isinstance(branch, dict), "branch must be an object")
    required_checks = branch.get("required_checks", [])
    _need(isinstance(required_checks, list), "branch.required_checks must be an array")
    for index, check in enumerate(required_checks):
        if isinstance(check, str):
            _need(bool(check.strip()), f"branch.required_checks[{index}] must be a non-empty name")
        else:
            _need(isinstance(check, dict) and set(check) <= {"name", "app_id"}
                  and isinstance(check.get("name"), str) and bool(check["name"].strip()),
                  f"branch.required_checks[{index}] must be a name or {{name, app_id}} object")
            if "app_id" in check:
                _need(isinstance(check["app_id"], int) and not isinstance(check["app_id"], bool) and check["app_id"] > 0,
                      f"branch.required_checks[{index}].app_id must be a positive integer")
    _need(isinstance(data.get("milestones", {}), dict), "milestones must be an object")
    global_hooks = _hooks(data.get("hooks", {}), "hooks", GLOBAL_HOOKS)
    components = data.get("components")
    _need(isinstance(components, list) and components, "components must be a non-empty array")
    component_ids: set[str] = set()
    clean_components: list[dict[str, Any]] = []
    for index, comp in enumerate(components):
        where = f"components[{index}]"
        _need(isinstance(comp, dict), f"{where} must be an object")
        cid = comp.get("id")
        _need(isinstance(cid, str) and cid.strip(), f"{where}.id must be non-empty")
        _need(cid not in component_ids, f"duplicate component id: {cid}")
        component_ids.add(cid)
        roots = _safe_roots(comp.get("roots"), where, repo)
        stacks = comp.get("stacks", [])
        app_types = comp.get("application_types", ["generic"])
        targets = comp.get("targets", [])
        _need(isinstance(stacks, list) and all(isinstance(s, str) and s for s in stacks), f"{where}.stacks must contain strings")
        _need(isinstance(app_types, list) and app_types and all(isinstance(t, str) and t in APPLICATION_TYPES for t in app_types),
              f"{where}.application_types must use the supported explicit types")
        _need(len(set(app_types)) == len(app_types), f"{where}.application_types has duplicates")
        comp_hooks = _hooks(comp.get("hooks", {}), f"{where}.hooks")
        _need(isinstance(targets, list), f"{where}.targets must be an array")
        target_ids: set[str] = set()
        clean_targets = []
        for j, target in enumerate(targets):
            tw = f"{where}.targets[{j}]"
            _need(isinstance(target, dict), f"{tw} must be an object")
            tid = target.get("id")
            _need(isinstance(tid, str) and tid.strip(), f"{tw}.id must be non-empty")
            _need(tid not in target_ids, f"duplicate target id in {cid}: {tid}")
            target_ids.add(tid)
            runnable = target.get("runnable_on", ["any"])
            _need(isinstance(runnable, list) and runnable and all(isinstance(v, str) and v in RUNNABLE_ON for v in runnable),
                  f"{tw}.runnable_on must use any, windows, macos, or linux")
            _need(len(set(runnable)) == len(runnable), f"{tw}.runnable_on has duplicates")
            target_hooks = _hooks(target.get("hooks", {}), f"{tw}.hooks")
            requirements = target.get("requirements")
            if requirements is not None:
                _need(isinstance(requirements, dict) and set(requirements) == {"architectures", "tools", "capabilities"},
                      f"{tw}.requirements must contain exactly architectures, tools, capabilities arrays")
                for req in requirements.values():
                    _need(isinstance(req, list) and all(isinstance(x, str) and x for x in req),
                          f"{tw}.requirements values must be arrays of non-empty strings")
            clean_targets.append({**target, "id": tid, "runnable_on": runnable, "hooks": target_hooks})
        clean_components.append({**comp, "id": cid, "roots": roots, "stacks": stacks,
                                 "application_types": app_types, "targets": clean_targets, "hooks": comp_hooks})
    return {**data, "schema_version": 2, "hooks": global_hooks, "components": clean_components}


def load_profile(repo: Path, allow_uninitialized: bool = False) -> dict[str, Any]:
    path = repo / ".agent" / "project.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"project profile not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"could not read project profile: {exc}") from exc
    result = validate_profile(data, repo)
    if result.get("schema_version") == 2 and not result.get("initialized") and not allow_uninitialized:
        raise ProfileError("project profile is not initialized")
    return result


def normalize_host(value: str | None = None) -> str:
    raw = (value or platform.system()).lower()
    if raw.startswith("win"):
        return "windows"
    if raw == "darwin" or raw.startswith("mac"):
        return "macos"
    if raw.startswith("linux"):
        return "linux"
    return raw


def normalize_arch(value: str | None = None) -> str:
    raw = (value or platform.machine()).lower()
    return {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}.get(raw, raw)


def _gate_target(target: dict[str, Any], host: str, arch: str, capabilities: set[str]) -> str | None:
    runnable = target.get("runnable_on", ["any"])
    if "any" not in runnable and host not in runnable:
        return "host_mismatch"
    req = target.get("requirements") or {"architectures": [], "tools": [], "capabilities": []}
    accepted_architectures = {normalize_arch(value) for value in req["architectures"]}
    if accepted_architectures and arch not in accepted_architectures:
        return "architecture_mismatch"
    missing = next((tool for tool in req["tools"] if shutil.which(tool) is None), None)
    if missing:
        return "missing_tool"
    missing_cap = next((cap for cap in req["capabilities"] if cap not in capabilities), None)
    if missing_cap:
        return "missing_capability"
    return None


def build_hook_plan(profile: dict[str, Any], hook_name: str, components: Iterable[str] | None = None,
                    host: str | None = None, arch: str | None = None,
                    capabilities: Iterable[str] = ()) -> HookPlan:
    if hook_name not in HOOKS:
        raise ProfileError(f"unsupported hook: {hook_name}")
    comps = profile.get("components", []) if profile.get("schema_version") == 2 else []
    if profile.get("schema_version") == 1:
        if components is not None:
            raise ProfileError("Schema 1 profiles do not declare components; refusing to broaden requested scope")
        hooks = profile.get("hooks", {}).get(hook_name, [])
        # Legacy commands are flat; expose them as project-level steps.
        return HookPlan(tuple(HookStep("project", None, command) for command in hooks), (), ())
    if hook_name == "branch_switch":
        if components is not None:
            raise ProfileError("branch_switch accepts global hooks only")
        steps = tuple(HookStep("project", None, command) for command in profile.get("hooks", {}).get(hook_name, []))
        return HookPlan(steps, (), ())
    requested = list(components) if components is not None else [c["id"] for c in comps]
    by_id = {c["id"]: c for c in comps}
    unknown = [cid for cid in requested if cid not in by_id]
    if unknown:
        raise ProfileError(f"unknown component id(s): {', '.join(unknown)}")
    # Preserve profile order even when an explicit scope is supplied.
    chosen = [c for c in comps if c["id"] in requested]
    steps: list[HookStep] = []
    skipped: list[SkippedTarget] = []
    for command in profile.get("hooks", {}).get(hook_name, []):
        steps.append(HookStep("project", None, command))
    caps = set(capabilities)
    current_host, current_arch = normalize_host(host), normalize_arch(arch)
    for comp in chosen:
        for command in comp.get("hooks", {}).get(hook_name, []):
            steps.append(HookStep(comp["id"], None, command))
    for comp in chosen:
        for target in comp.get("targets", []):
            target_commands = target.get("hooks", {}).get(hook_name, [])
            if not target_commands:
                continue
            reason = _gate_target(target, current_host, current_arch, caps)
            if reason:
                skipped.append(SkippedTarget(comp["id"], target["id"], reason))
                continue
            for command in target_commands:
                steps.append(HookStep(comp["id"], target["id"], command))
    return HookPlan(tuple(steps), tuple(skipped), tuple(chosen))
