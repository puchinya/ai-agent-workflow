#!/usr/bin/env python3
"""Deterministically generate physically separate host plugin packages."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from agent_workflow import __version__  # noqa: E402

HOSTS = ("openai", "claude", "antigravity")
EXPECTED_SKILLS = ("requirements", "design", "implementation-contract", "implementation",
                   "evidence", "checkpoint", "self-review", "pr-review", "qa", "delivery")
GENERATED_ROOT_FILES = {".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json"}


class BuildError(RuntimeError):
    pass


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BuildError(f"required canonical input missing/unreadable: {path.relative_to(ROOT)}") from exc


def _json(path: Path) -> object:
    try:
        return json.loads(_read(path).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid JSON adapter input: {path.relative_to(ROOT)}") from exc


def expected_files() -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    skill_roots = sorted((ROOT / "workflow" / "skills").iterdir())
    names = {path.name for path in skill_roots if path.is_dir()}
    if names != set(EXPECTED_SKILLS):
        raise BuildError(f"canonical Skills must be exactly {', '.join(EXPECTED_SKILLS)}; found {', '.join(names)}")
    for host in HOSTS:
        prefix = f"dist/{host}"
        adapter = ROOT / "adapters" / host
        if host in ("openai", "claude"):
            manifest = _json(adapter / "plugin.json")
            if not isinstance(manifest, dict):
                raise BuildError(f"adapters/{host}/plugin.json: manifest must be a JSON object")
            if "version" in manifest:
                raise BuildError(f"adapters/{host}/plugin.json: adapter-owned version is forbidden; use agent_workflow.__version__")
            manifest["version"] = __version__
            manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if host == "openai":
            result[f"{prefix}/plugin.json"] = manifest_bytes
            marketplace = _json(adapter / "marketplace.json")
            result[".agents/plugins/marketplace.json"] = (json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n").encode()
        elif host == "claude":
            result[f"{prefix}/.claude-plugin/plugin.json"] = manifest_bytes
            marketplace = _json(adapter / "marketplace.json")
            result[".claude-plugin/marketplace.json"] = (json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n").encode()
        else:
            result[f"{prefix}/plugin.json"] = _read(adapter / "plugin.json")
        result[f"{prefix}/README.md"] = _read(adapter / "README.md")
        result[f"{prefix}/LICENSE"] = _read(ROOT / "LICENSE")
        result[f"{prefix}/pyproject.toml"] = _read(ROOT / "pyproject.toml")
        for skill in EXPECTED_SKILLS:
            source = ROOT / "workflow" / "skills" / skill
            for file in sorted(path for path in source.rglob("*") if path.is_file()):
                rel = file.relative_to(source).as_posix()
                data = _read(file)
                # Canonical Skills link to repo specs three levels up; packages use two.
                if file.suffix.lower() == ".md":
                    data = data.replace(b"../../../docs/specs/", b"../../docs/specs/")
                result[f"{prefix}/skills/{skill}/{rel}"] = data
        for folder in ("standards", "templates"):
            for file in sorted((ROOT / "workflow" / folder).rglob("*")):
                if file.is_file():
                    rel = file.relative_to(ROOT / "workflow" / folder).as_posix()
                    result[f"{prefix}/{folder}/{rel}"] = _read(file)
        for folder in ("specs", "design"):
            for file in sorted((ROOT / "docs" / folder).rglob("*")):
                if file.is_file():
                    rel = file.relative_to(ROOT / "docs").as_posix()
                    result[f"{prefix}/docs/{rel}"] = _read(file)
        for file in sorted((ROOT / "runtime" / "agent_workflow").glob("*.py")):
            result[f"{prefix}/runtime/agent_workflow/{file.name}"] = _read(file)
    return result


def _actual_paths() -> set[str]:
    actual: set[str] = set()
    for host in HOSTS:
        root = ROOT / "dist" / host
        if root.exists():
            actual.update(path.relative_to(ROOT).as_posix() for path in root.rglob("*") if path.is_file())
    actual.update(path for path in GENERATED_ROOT_FILES if (ROOT / path).is_file())
    return actual


def check(files: dict[str, bytes]) -> list[str]:
    expected = set(files)
    actual = _actual_paths()
    errors = [f"missing generated file: {path}" for path in sorted(expected - actual)]
    errors.extend(f"extra generated file: {path}" for path in sorted(actual - expected))
    for path in sorted(expected & actual):
        if (ROOT / path).read_bytes() != files[path]:
            errors.append(f"generated file drift: {path}")
    return errors


def build(files: dict[str, bytes]) -> None:
    # The complete expected map has been validated before any destination changes.
    roots = [ROOT / "dist" / host for host in HOSTS]
    for path, data in sorted(files.items()):
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(data)
        try:
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    expected_by_root = {host: {path for path in files if path.startswith(f"dist/{host}/")} for host in HOSTS}
    for host, root in zip(HOSTS, roots):
        if root.exists():
            for path in sorted((p for p in root.rglob("*") if p.is_file()), reverse=True):
                if path.relative_to(ROOT).as_posix() not in expected_by_root[host]:
                    path.unlink()
            for path in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
                try:
                    path.rmdir()
                except OSError:
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        files = expected_files()
        if args.check:
            errors = check(files)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print(f"generated package tree matches {len(files)} expected files")
            return 0
        build(files)
        errors = check(files)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print(f"generated {len(files)} files across three plugin packages")
        return 0
    except BuildError as exc:
        print(f"build error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
