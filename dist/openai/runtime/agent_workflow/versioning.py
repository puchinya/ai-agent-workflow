"""Resolve repository versions for milestone titles without adding dependencies."""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any


class VersionError(RuntimeError):
    pass


_MISSING = object()


def _split_command(command: str, *, windows: bool | None = None) -> list[str]:
    """Split a configured command while preserving Windows path separators."""
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return shlex.split(command)
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    # Backslash is part of Windows paths. Quotes still group arguments, but
    # treating every backslash as a shell escape corrupts executable paths.
    lexer.escape = ""
    return list(lexer)


def _safe_source_path(repo: Path, relative: str) -> Path:
    path = repo / relative
    root = repo.resolve()
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise VersionError("version source path escapes the repository")
    return path


def _version(value: Any, source: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise VersionError(f"version from {source} must be a non-empty single-line string")
    return value


def _json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _MISSING
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VersionError(f"could not read version source {path.name}") from exc


def _field(value: Any, dotted: str) -> Any:
    selected = value
    for name in dotted.split("."):
        if not isinstance(selected, dict) or name not in selected:
            return _MISSING
        selected = selected[name]
    return selected


def _strip_toml_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif quote == "'":
            if char == "'":
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == "#":
            return line[:index]
    return line


def _toml_string(value: str, source: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if value.startswith('"'):
        try:
            selected = json.loads(value)
        except json.JSONDecodeError as exc:
            raise VersionError(f"invalid TOML string in {source}") from exc
        if isinstance(selected, str):
            return selected
    raise VersionError(f"version in {source} must be a TOML string scalar")


def _toml_fields(path: Path, wanted: set[str]) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as exc:
        raise VersionError(f"could not read version source {path.name}") from exc
    result: dict[str, str] = {}
    section = ""
    for number, raw in enumerate(lines, 1):
        line = _strip_toml_comment(raw).strip()
        if not line:
            continue
        header = re.fullmatch(r"\[([A-Za-z0-9_.-]+)\]", line)
        if header:
            section = header.group(1)
            continue
        assignment = re.match(r"^([A-Za-z0-9_-]+)\s*=\s*(.*?)\s*$", line)
        if not assignment:
            continue
        key, scalar = assignment.groups()
        dotted = f"{section}.{key}" if section else key
        if dotted not in wanted:
            continue
        if dotted in result:
            raise VersionError(f"duplicate TOML version field {dotted} in {path.name}:{number}")
        result[dotted] = _toml_string(scalar, f"{path.name}:{number}")
    return result


def _read_python_attribute(path: Path, field: str) -> Any:
    try:
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source, filename=path.name)
    except FileNotFoundError:
        return _MISSING
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise VersionError(f"could not read Python version source {path.name}") from exc
    if "." in field:
        raise VersionError("python-attr sources support one module-level attribute name")
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == field for target in node.targets):
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == field:
            value_node = node.value
        else:
            continue
        try:
            return ast.literal_eval(value_node)
        except (ValueError, TypeError, SyntaxError) as exc:
            raise VersionError(f"Python version attribute {field} must be a string literal") from exc
    return _MISSING


def _explicit(repo: Path, source: dict[str, str]) -> str | None:
    kind = source["type"]
    if kind == "command":
        try:
            argv = _split_command(source["command"])
        except ValueError as exc:
            raise VersionError("version source command has invalid quoting") from exc
        if not argv:
            raise VersionError("version source command has no executable")
        try:
            result = subprocess.run(argv, cwd=repo, text=True, encoding="utf-8", errors="replace",
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VersionError("version source command could not complete") from exc
        if result.returncode:
            raise VersionError(f"version source command failed (exit status {result.returncode})")
        value = result.stdout
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith(("\r", "\n")):
            value = value[:-1]
        if not value:
            return None
    else:
        path = _safe_source_path(repo, source["path"])
        if kind == "json":
            value = _field(_json_file(path), source["field"])
        elif kind == "toml":
            fields = _toml_fields(path, {source["field"]})
            value = fields.get(source["field"], _MISSING)
        else:
            value = _read_python_attribute(path, source["field"])
    if value is _MISSING:
        return None
    return _version(value, source.get("path", kind))


def _auto(repo: Path) -> str | None:
    values: list[tuple[str, str]] = []
    package = _json_file(_safe_source_path(repo, "package.json"))
    package_version = _field(package, "version")
    if package_version is not _MISSING:
        values.append(("package.json:version", _version(package_version, "package.json:version")))

    cargo = _toml_fields(_safe_source_path(repo, "Cargo.toml"), {"package.version", "workspace.package.version"})
    values.extend((f"Cargo.toml:{key}", _version(value, f"Cargo.toml:{key}")) for key, value in cargo.items())

    pyproject = _toml_fields(_safe_source_path(repo, "pyproject.toml"), {"project.version"})
    if "project.version" in pyproject:
        value = pyproject["project.version"]
        values.append(("pyproject.toml:project.version", _version(value, "pyproject.toml:project.version")))

    distinct = {value for _, value in values}
    if not distinct:
        return None
    if len(distinct) > 1:
        sources = ", ".join(name for name, _ in values)
        raise VersionError(f"VERSION_AMBIGUOUS: conflicting version values from {sources}")
    return values[0][1]


def resolve_version(repo: Path, version_source: str | dict[str, str]) -> str | None:
    """Resolve a version source, preserving the selected string exactly."""
    if version_source == "auto":
        return _auto(repo)
    if not isinstance(version_source, dict):
        raise VersionError("invalid version source")
    return _explicit(repo, version_source)
