<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Distribution Specification

- Status: Approved
- Owning Issue: [Issue #1](https://github.com/puchinya/ai-agent-workflow/issues/1)
- Related design: [Distribution design](../design/distribution-design.md)

## Purpose

Define a deterministic build of three physically separate installable packages from one canonical workflow source, and the independent validation required for each host.

## Scope

Canonical inputs are `workflow/`, `runtime/`, and `adapters/`. Generated outputs are `dist/openai/`, `dist/claude/`, and `dist/antigravity/`. Host products are OpenAI/Codex, Claude Code, and Google Antigravity 2.0. The host specifications were checked against their current official documentation on 2026-10-02: [OpenAI Plugins](https://developers.openai.com/plugins/build/plugins), [OpenAI Skills](https://developers.openai.com/plugins/build/skills), [Claude Plugins API](https://platform.claude.com/docs/en/manage-claude/plugins-api), [Claude Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview), [Claude marketplace creation](https://code.claude.com/docs/en/plugins/create-marketplace), and [Antigravity Plugins](https://www.antigravity.google/docs/plugins).

## Normative requirements

### OpenAI package

`dist/openai/plugin.json` is a portable Agent Plugins manifest at package root. It uses the current `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` schema and portable `name`, `version`, and `description` fields. Skills are under root `skills/`; the portable manifest relies on fixed package paths and does not require a `skills` field. OpenAI-specific presentation and configuration belongs only under `extensions.com.openai`. `.codex-plugin/plugin.json` is included only if an explicit compatibility need is verified.

The repository includes `.agents/plugins/marketplace.json` for local test discovery. Its `source.path` is a `./`-prefixed path relative to the marketplace root, with `source: local`, and points to `./dist/openai`. Plugin installation/authentication policy and picker name follow the current official local marketplace example.

### Claude package

`dist/claude/.claude-plugin/plugin.json` is the sole Claude plugin manifest. It declares a lowercase, unique marketplace name of up to 64 letters/digits/hyphens; `displayName` is at most 64 characters and `description` at most 500. Skills are under root `skills/` and each `SKILL.md` has valid YAML frontmatter with `name` and `description`. No file is placed under a top-level `bin/` directory.

The generated repository-root `.claude-plugin/marketplace.json` uses Claude Code's current `name`, `owner`, and `plugins` format. Its plugin entry uses a `./`-prefixed source path relative to repository root and points to `./dist/claude`. The Antigravity manifest uses the schema URL as its validator reference; the manifest itself contains only the schema's allowed `name` and optional `description` properties. The Enterprise Plugins API upload format remains an archive or set of files; it is not treated as a local manifest schema.

### Antigravity package

`dist/antigravity/plugin.json` is a separate root manifest using `https://antigravity.google/schemas/v1/plugin.json`. The current schema requires `name`, permits `description`, and rejects unrecognized properties. Skills are under root `skills/`. `agents/`, `rules/`, `hooks.json`, and `mcp_config.json` are omitted unless a concrete Skill behavior requires them.

### Generation and validation

`python tools/build_dist.py` deterministically regenerates all package files. `python tools/build_dist.py --check` compares the complete expected path/content map and fails for missing, extra, or edited generated files. No hand edits under `dist/**` are allowed.

CI MUST run `--check` before unit tests or generation can rewrite committed outputs. After tests and generation, `git diff --exit-code -- dist .agents/plugins/marketplace.json .claude-plugin/marketplace.json` MUST prove the generated paths remain identical to the checkout. Executable Skill examples MUST use `python -m agent_workflow <subcommand>`; distribution validation rejects bare runtime command examples.

`python tools/validate_dist.py` validates each host package independently: manifest path and schema-specific fields, unique package/Skill names, required frontmatter, safe relative resource paths, required supporting runtime/standards, host separation, and marketplace metadata. It rejects forbidden reference-template synchronization files and any MCP/agent/rules/hooks placeholders.

## Observable behavior

Each package can be inspected and validated without installing another host package. Generated Skills have identical workflow semantics, while manifests and marketplace metadata remain host-specific. Build and validation require no network access.

## Security and privacy

Generated files include no credentials, service endpoints, or copied consumer state. Plugin schemas are validated locally; runtime package generation does not fetch external schemas.

## Error and boundary behavior

| Condition | Required behavior |
|---|---|
| Generated file differs from canonical inputs | `build_dist.py --check` reports drift and exits nonzero without writing. |
| Host package uses another host's manifest | Fail distribution validation; never normalize the foreign manifest. |
| Skill metadata or referenced resource is invalid/missing | Identify the package and path and fail. |
| Unsupported optional host component is empty or placeholder-only | Reject it from the package. |
| External plugin specification cannot be accessed | Report the exact unverified host/spec and do not claim package conformance. |

## Verification strategy

Tests compare two fresh builds byte-for-byte, prove `--check` detects hand-edited generated files, independently accept/reject host manifest fixtures, verify every Skill's links, and prove OpenAI and Antigravity root manifests are not shared. Host application/IDE smoke tests are reported only when the actual product is installed and run; otherwise they remain untested.
