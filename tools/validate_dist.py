#!/usr/bin/env python3
"""Validate each generated plugin against its independent host contract."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from agent_workflow import __version__  # noqa: E402
from agent_workflow.documents import validate_markdown_file  # noqa: E402

HOSTS = ("openai", "claude", "antigravity")
SKILLS = ("requirements", "design", "implementation-contract", "implementation",
          "evidence", "checkpoint", "self-review", "pr-review", "delivery")
OPENAI_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
ANTIGRAVITY_SCHEMA = "https://antigravity.google/schemas/v1/plugin.json"
FORBIDDEN_PATH = re.compile(r"(?i)(?:update-template|refresh-template-manifest|template-manifest|update_template|refresh_template)")
RUNTIME_COMMANDS = (
    "init-project", "agent-context", "validate-docs", "run-hook",
    "save-implementation-contract", "publish-implementation-contract",
    "restore-implementation-contract", "verify-implementation-contract", "ensure-review-pr",
    "resolve-implementation-base",
    "prepare-self-review", "validate-self-review", "publish-self-review",
    "validate-public-review", "delivery-check", "finalize-merged-issue",
)
BARE_RUNTIME_COMMAND = re.compile(
    r"(?:^|[;&|]\s*)(?:\$\s+)?(" + "|".join(RUNTIME_COMMANDS) + r")(?=\s|$)"
)


def validate_skill_commands(text: str, rel: str) -> list[str]:
    """Check executable examples in inline code and fenced command blocks."""
    examples = re.findall(r"(?<!`)`([^`\n]+)`(?!`)", text)
    for block in re.finditer(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n(.*?)^\s*\1\s*$", text):
        examples.extend(block.group(2).splitlines())
    errors = []
    for example in examples:
        match = BARE_RUNTIME_COMMAND.search(example.strip())
        if match:
            errors.append(f"{rel}: execute {match.group(1)} with python -m agent_workflow")
    return errors


def _load(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid or unreadable JSON ({exc})")
        return None


def _repository_source_target(path: object) -> tuple[Path | None, str | None]:
    """Resolve a marketplace path only when it stays inside this checkout."""
    if not isinstance(path, str) or not path.startswith("./") or "\\" in path:
        return None, "source must be a repository-relative ./ path"
    relative = PurePosixPath(path)
    if relative.is_absolute() or PureWindowsPath(path).is_absolute() or ".." in relative.parts:
        return None, "source path must not be absolute or escape the repository"
    target = (ROOT / Path(*relative.parts)).resolve()
    if target == ROOT.resolve() or ROOT.resolve() not in target.parents:
        return None, "source path resolves outside the repository"
    return target, None


def _validate_openai(errors: list[str]) -> None:
    root = ROOT / "dist/openai"
    manifest = _load(root / "plugin.json", errors)
    if isinstance(manifest, dict):
        name = manifest.get("name")
        if manifest.get("$schema") != OPENAI_SCHEMA or not isinstance(name, str):
            errors.append("dist/openai/plugin.json: missing portable Agent Plugins schema/name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name) or "--" in name or ".." in name or len(name) > 64:
            errors.append("dist/openai/plugin.json: name violates portable schema")
        if not isinstance(manifest.get("version"), str) or not isinstance(manifest.get("description"), str):
            errors.append("dist/openai/plugin.json: version and description must be strings")
        if manifest.get("version") != __version__:
            errors.append("dist/openai/plugin.json: version must equal agent_workflow.__version__")
        allowed = {"$schema", "name", "version", "description", "author", "homepage", "repository", "license", "keywords", "extensions"}
        if set(manifest) - allowed:
            errors.append("dist/openai/plugin.json: unsupported portable manifest field")
        for field in ("homepage", "repository", "license"):
            if field in manifest and not isinstance(manifest[field], str):
                errors.append(f"dist/openai/plugin.json: {field} must be a string")
        author = manifest.get("author")
        if author is not None and (not isinstance(author, dict) or set(author) - {"name", "email", "url"}
                                   or any(not isinstance(value, str) for value in author.values())):
            errors.append("dist/openai/plugin.json: author must contain only string name/email/url fields")
        keywords = manifest.get("keywords")
        if keywords is not None and (not isinstance(keywords, list) or any(not isinstance(value, str) for value in keywords)):
            errors.append("dist/openai/plugin.json: keywords must be an array of strings")
        extensions = manifest.get("extensions", {})
        if not isinstance(extensions, dict):
            errors.append("dist/openai/plugin.json: extensions must be an object")
        elif set(extensions) - {"com.openai"}:
            errors.append("dist/openai/plugin.json: host-specific fields must use extensions.com.openai")
        elif any(not isinstance(value, dict) for value in extensions.values()):
            errors.append("dist/openai/plugin.json: each extension namespace value must be an object")
    market = _load(ROOT / ".agents/plugins/marketplace.json", errors)
    if isinstance(market, dict):
        if market.get("name") != "ai-agent-workflow":
            errors.append(".agents/plugins/marketplace.json: marketplace name must be ai-agent-workflow")
        plugins = market.get("plugins")
        if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
            errors.append(".agents/plugins/marketplace.json: expected one plugin entry")
        else:
            entry = plugins[0]
            source = entry.get("source", {})
            path = source.get("path", "") if isinstance(source, dict) else ""
            target, path_error = _repository_source_target(path)
            if not isinstance(source, dict) or source.get("source") != "local" or path_error:
                errors.append(".agents/plugins/marketplace.json: marketplace-source error: "
                              + (path_error or "source type must be local"))
            elif target is not None and not target.is_dir():
                errors.append(".agents/plugins/marketplace.json: marketplace-source error: package directory does not exist")
            elif path != "./dist/openai":
                errors.append(".agents/plugins/marketplace.json: marketplace-source error: source path must be ./dist/openai")
            elif target is not None and not (target / "plugin.json").is_file():
                errors.append(".agents/plugins/marketplace.json: marketplace-source error: dist/openai/plugin.json does not exist")
            manifest_name = manifest.get("name") if isinstance(manifest, dict) else None
            if manifest_name != "ai-agent-workflow":
                errors.append("dist/openai/plugin.json: marketplace entry and manifest name must be ai-agent-workflow")
            if entry.get("name") != manifest_name:
                errors.append(".agents/plugins/marketplace.json: plugin entry name does not match the OpenAI manifest name")
            if entry.get("category") != "Productivity":
                errors.append(".agents/plugins/marketplace.json: plugin category must be Productivity")
            policy = entry.get("policy", {})
            if not isinstance(policy, dict) or policy.get("installation") != "AVAILABLE" or policy.get("authentication") != "ON_INSTALL":
                errors.append(".agents/plugins/marketplace.json: installation/authentication policy is invalid")
        interface = market.get("interface", {})
        if not isinstance(interface, dict) or not isinstance(interface.get("displayName"), str) or not interface.get("displayName"):
            errors.append(".agents/plugins/marketplace.json: interface.displayName is required for picker presentation")


def _validate_claude(errors: list[str]) -> None:
    root = ROOT / "dist/claude"
    manifest = _load(root / ".claude-plugin/plugin.json", errors)
    if isinstance(manifest, dict):
        name = manifest.get("name", "")
        if manifest.get("version") != __version__:
            errors.append("dist/claude/.claude-plugin/plugin.json: version must equal agent_workflow.__version__")
        if not isinstance(name, str) or len(name) > 64 or not re.fullmatch(r"[a-z0-9-]+", name):
            errors.append("dist/claude/.claude-plugin/plugin.json: name must be lowercase letters/digits/hyphens, max 64")
        display_name = manifest.get("displayName", "")
        if not isinstance(display_name, str):
            errors.append("dist/claude/.claude-plugin/plugin.json: displayName must be a string")
        elif len(display_name) > 64:
            errors.append("dist/claude/.claude-plugin/plugin.json: displayName exceeds 64 characters")
        if len(str(manifest.get("description", ""))) > 500:
            errors.append("dist/claude/.claude-plugin/plugin.json: description exceeds 500 characters")
        if not name or not manifest.get("description"):
            errors.append("dist/claude/.claude-plugin/plugin.json: name and description are required")
        for field in ("version", "description", "homepage", "repository", "license"):
            if field in manifest and not isinstance(manifest[field], str):
                errors.append(f"dist/claude/.claude-plugin/plugin.json: {field} must be a string")
        keywords = manifest.get("keywords")
        if keywords is not None and (not isinstance(keywords, list) or any(not isinstance(value, str) for value in keywords)):
            errors.append("dist/claude/.claude-plugin/plugin.json: keywords must be an array of strings")
    if (root / "bin").exists():
        errors.append("dist/claude/bin is unsupported")
    market = _load(ROOT / ".claude-plugin/marketplace.json", errors)
    if isinstance(market, dict):
        if market.get("name") != "ai-agent-workflow" or not isinstance(market.get("owner"), dict) or not market["owner"].get("name") or not isinstance(market.get("plugins"), list):
            errors.append(".claude-plugin/marketplace.json: name, owner.name, and plugins are required")
        else:
            manifest_name = manifest.get("name") if isinstance(manifest, dict) else None
            entries = market["plugins"]
            if len(entries) != 1 or not isinstance(entries[0], dict):
                errors.append(".claude-plugin/marketplace.json: expected one plugin entry")
            else:
                entry = entries[0]
                target, path_error = _repository_source_target(entry.get("source"))
                if path_error:
                    errors.append(".claude-plugin/marketplace.json: marketplace-source error: " + path_error)
                elif target is not None and not target.is_dir():
                    errors.append(".claude-plugin/marketplace.json: marketplace-source error: package directory does not exist")
                elif entry.get("source") != "./dist/claude":
                    errors.append(".claude-plugin/marketplace.json: marketplace-source error: source path must be ./dist/claude")
                elif target is not None and not (target / ".claude-plugin/plugin.json").is_file():
                    errors.append(".claude-plugin/marketplace.json: marketplace-source error: "
                                  "dist/claude/.claude-plugin/plugin.json does not exist")
                if entry.get("name") != manifest_name:
                    errors.append(".claude-plugin/marketplace.json: plugin entry name does not match the Claude manifest name")
                if manifest_name != "ai-agent-workflow":
                    errors.append("dist/claude/.claude-plugin/plugin.json: marketplace entry and manifest name must be ai-agent-workflow")


def _validate_antigravity(errors: list[str]) -> None:
    manifest = _load(ROOT / "dist/antigravity/plugin.json", errors)
    if isinstance(manifest, dict):
        if set(manifest) - {"name", "description"}:
            errors.append("dist/antigravity/plugin.json: only schema-supported name and description are allowed")
        if not isinstance(manifest.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", manifest.get("name", "")):
            errors.append(f"dist/antigravity/plugin.json: name violates {ANTIGRAVITY_SCHEMA}")
        if not isinstance(manifest.get("description"), str):
            errors.append("dist/antigravity/plugin.json: description must be a string")
    root = ROOT / "dist/antigravity"
    for placeholder in ("agents", "rules", "hooks.json", "mcp_config.json"):
        if (root / placeholder).exists():
            errors.append(f"dist/antigravity/{placeholder}: placeholder-only host component is forbidden")


def validate() -> list[str]:
    errors: list[str] = []
    _validate_openai(errors)
    _validate_claude(errors)
    _validate_antigravity(errors)
    for host, forbidden in (("openai", (".claude-plugin/plugin.json",)),
                            ("claude", ("plugin.json",)),
                            ("antigravity", (".claude-plugin/plugin.json",))):
        for rel in forbidden:
            if (ROOT / "dist" / host / rel).exists():
                errors.append(f"dist/{host}/{rel}: foreign host manifest is forbidden")
    manifests = []
    for host in HOSTS:
        root = ROOT / "dist" / host
        if not root.is_dir():
            errors.append(f"dist/{host}: generated package is missing")
            continue
        manifest_path = root / (".claude-plugin/plugin.json" if host == "claude" else "plugin.json")
        manifests.append((host, _load(manifest_path, errors)))
        for name in SKILLS:
            skill_path = root / "skills" / name / "SKILL.md"
            try:
                text = skill_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                errors.append(f"dist/{host}/skills/{name}/SKILL.md: missing or invalid UTF-8")
                continue
            fm = re.match(r"(?s)^---\s*\n(.*?)\n---\s*\n", text)
            if not fm:
                errors.append(f"dist/{host}/skills/{name}/SKILL.md: missing YAML frontmatter")
            else:
                fields = dict(re.findall(r"^(name|description):\s*(.+?)\s*$", fm.group(1), re.M))
                if fields.get("name") != name or not fields.get("description"):
                    errors.append(f"dist/{host}/skills/{name}/SKILL.md: invalid name/description metadata")
            errors.extend(validate_markdown_file(skill_path, root))
            errors.extend(validate_skill_commands(text, skill_path.relative_to(ROOT).as_posix()))
        for required in ("runtime/agent_workflow/__init__.py", "runtime/agent_workflow/cli.py",
                         "standards/specification.md", "standards/design.md", "standards/documentation-sync.md",
                         "templates/spec-template.md", "templates/design-template.md", "templates/status-template.md",
                         "pyproject.toml"):
            if not (root / required).is_file():
                errors.append(f"dist/{host}/{required}: required supporting resource missing")
        for path in root.rglob("*"):
            if FORBIDDEN_PATH.search(path.name):
                errors.append(f"{path.relative_to(ROOT)}: forbidden reference synchronization artifact")
        for path in root.rglob("*.md"):
            errors.extend(validate_markdown_file(path, root))
    if len(manifests) == 3:
        if manifests[0][1] == manifests[2][1]:
            errors.append("OpenAI and Antigravity root manifests must remain physically/schema distinct")
        if manifests[0][1] == manifests[1][1] or manifests[1][1] == manifests[2][1]:
            errors.append("host package manifests must not be shared")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("OpenAI, Claude Code, and Antigravity packages validate independently")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
