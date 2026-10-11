"""Strict project configuration readback for P-ASES work and delivery."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .path_safety import path_has_symlink
from .verification import RequiredCheckPolicy, VerificationError


class ProfileError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError(f"project configuration contains duplicate key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class ProjectProfile:
    root: Path
    project_name: str
    branch_prefix: str
    required_checks: tuple[tuple[str, int | None], ...]

    def required_check_policy(self) -> RequiredCheckPolicy:
        if any(app_id is None for _, app_id in self.required_checks):
            raise ProfileError("Required Check trusted_app_id is not configured")
        try:
            return RequiredCheckPolicy(tuple((name, app_id) for name, app_id in self.required_checks
                                             if app_id is not None)).validate()
        except VerificationError as exc:
            raise ProfileError(str(exc)) from exc


def load_profile(repository_root: Path) -> ProjectProfile:
    root = Path(os.path.abspath(repository_root))
    if root.is_symlink() or not root.is_dir():
        raise ProfileError("repository root must be an existing non-symlink directory")
    path = root / ".agent" / "project.json"
    if path_has_symlink(path, root=root) or not path.is_file():
        raise ProfileError("project configuration is missing or traverses a symbolic link")
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileError("project configuration is unreadable JSON") from exc
    expected = {"schema_version", "initialized", "project_name", "components", "branch", "workspace", "milestones", "hooks"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ProfileError("project configuration has unknown or missing top-level fields")
    if value["schema_version"] != 2 or value["initialized"] is not True:
        raise ProfileError("project configuration schema is unknown or not initialized")
    project_name = value["project_name"]
    if not isinstance(project_name, str) or not project_name.strip():
        raise ProfileError("project_name must be non-empty text")
    branch = value["branch"]
    branch_fields = {"prefix", "max_slug_length", "cleanup_on_switch", "required_checks"}
    if not isinstance(branch, dict) or set(branch) != branch_fields:
        raise ProfileError("branch configuration has unknown or missing fields")
    prefix = branch["prefix"]
    if not isinstance(prefix, str) or not prefix.strip() or any(c in prefix for c in "\x00\r\n /\\"):
        raise ProfileError("branch.prefix is invalid")
    rows = branch["required_checks"]
    if not isinstance(rows, list) or not rows:
        raise ProfileError("branch.required_checks must be a non-empty list")
    checks: list[tuple[str, int | None]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) not in ({"name"}, {"name", "trusted_app_id"}):
            raise ProfileError(f"required Check {index + 1} has unknown or missing fields")
        name, app_id = row.get("name"), row.get("trusted_app_id")
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ProfileError(f"required Check {index + 1} name is invalid")
        if app_id is not None and (type(app_id) is not int or app_id < 1):
            raise ProfileError(f"required Check {index + 1} trusted_app_id is invalid")
        checks.append((name, app_id))
    if len({name for name, _ in checks}) != len(checks):
        raise ProfileError("required Check names must be unique")
    for key in ("components", "workspace", "milestones", "hooks"):
        if not isinstance(value[key], (dict, list)):
            raise ProfileError(f"project {key} configuration has an invalid type")
    return ProjectProfile(root, project_name.strip(), prefix, tuple(checks))
