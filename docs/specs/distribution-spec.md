<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Distribution Specification

- Status: Approved
- Owning Issue: [Issue #1](https://github.com/puchinya/ai-agent-workflow/issues/1)
- Release automation: [Issue #3 contract](https://github.com/puchinya/ai-agent-workflow/issues/3#issuecomment-5963850384)
- Related design: [Distribution design](../design/distribution-design.md)

## Purpose

Define a deterministic build of three physically separate installable packages from one canonical workflow source, the repository-hosted marketplace paths for OpenAI/Codex and Claude Code, and independent validation required for each host.

## Scope

Canonical inputs are `workflow/`, `runtime/`, and `adapters/`. Generated outputs are `dist/openai/`, `dist/claude/`, and `dist/antigravity/`. Host products are OpenAI/Codex, Claude Code, and Google Antigravity 2.0. The host specifications were checked against current official documentation on 2026-10-03: [OpenAI Plugins](https://developers.openai.com/plugins/build/plugins), [OpenAI Skills](https://developers.openai.com/plugins/build/skills), [Claude Plugins API](https://platform.claude.com/docs/en/manage-claude/plugins-api), [Claude Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview), [Claude marketplace creation](https://code.claude.com/docs/en/plugins/create-marketplace), and [Antigravity Plugins](https://www.antigravity.google/docs/plugins). OpenAI/Codex and Claude Code can register a GitHub repository as a marketplace and resolve repository-relative plugin sources. Third-party GitHub marketplace support for Antigravity is unconfirmed.

The GitHub repository itself is the marketplace host for OpenAI/Codex and Claude Code. GitHub Releases remain the independent version-fixed/manual/offline distribution path. Antigravity remains local/manual until its third-party Git marketplace support is confirmed.

## Normative requirements

### OpenAI package

`dist/openai/plugin.json` is a portable Agent Plugins manifest at package root. It uses the current `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` schema and portable `name`, `version`, and `description` fields. Skills are under root `skills/`; the portable manifest relies on fixed package paths and does not require a `skills` field. OpenAI-specific presentation and configuration belongs only under `extensions.com.openai`. `.codex-plugin/plugin.json` is included only if an explicit compatibility need is verified.

The repository-root `.agents/plugins/marketplace.json` is the OpenAI/Codex GitHub marketplace manifest. Its sole plugin entry is named `ai-agent-workflow`, has category `Productivity`, preserves the existing installation/authentication policy, and uses `source: local` with `path: ./dist/openai`. Marketplace registration supplies Git transport; the relative source resolves within the checked-out repository. The path MUST be repository-relative, remain inside the checkout after resolution, and point to an existing directory containing `plugin.json`.

### Claude package

`dist/claude/.claude-plugin/plugin.json` is the sole Claude plugin manifest. It declares a lowercase, unique marketplace name of up to 64 letters/digits/hyphens; `displayName` is at most 64 characters and `description` at most 500. Skills are under root `skills/` and each `SKILL.md` has valid YAML frontmatter with `name` and `description`. No file is placed under a top-level `bin/` directory.

The generated repository-root `.claude-plugin/marketplace.json` uses Claude Code's current `name`, `owner`, and `plugins` format. It contains one plugin entry named `ai-agent-workflow`; its source is `./dist/claude`, relative to and contained within the marketplace repository checkout, with `.claude-plugin/plugin.json` present in that directory. GitHub marketplace registration supplies transport. The Antigravity manifest uses the schema URL as its validator reference; the manifest itself contains only the schema's allowed `name` and optional `description` properties. The Enterprise Plugins API upload format remains an archive or set of files; it is not treated as a local manifest schema.

### Antigravity package

`dist/antigravity/plugin.json` is a separate root manifest using `https://antigravity.google/schemas/v1/plugin.json`. The current schema requires `name`, permits `description`, and rejects unrecognized properties. Skills are under root `skills/`. `agents/`, `rules/`, `hooks.json`, and `mcp_config.json` are omitted unless a concrete Skill behavior requires them.

Install Antigravity locally/manual from `dist/antigravity` or its versioned Release ZIP. Do not claim GitHub marketplace support or resolve an Antigravity source through OpenAI/Claude marketplace metadata.

### Generation and validation

`runtime/agent_workflow/__init__.py::__version__` MUST be the sole hand-authored package version. `pyproject.toml` MUST obtain its dynamic version through `agent_workflow.__version__`. OpenAI/Claude adapters MUST NOT contain a `version` key: generation rejects it before writing and injects the canonical version into their deterministically serialized manifests. Validation MUST require both generated versions to equal the canonical version. Antigravity MUST remain versionless.

`python tools/build_dist.py` deterministically regenerates all package files. `python tools/build_dist.py --check` compares the complete expected path/content map and fails for missing, extra, or edited generated files. No hand edits under `dist/**` are allowed.

CI MUST run `--check` before unit tests or generation can rewrite committed outputs. After tests and generation, `git diff --exit-code -- dist .agents/plugins/marketplace.json .claude-plugin/marketplace.json` MUST prove the generated paths remain identical to the checkout. Executable Skill examples MUST use `python -m agent_workflow <subcommand>`; distribution validation rejects bare runtime command examples.

`python tools/validate_dist.py` validates each host package independently: manifest path and schema-specific fields, unique package/Skill names, required frontmatter, safe relative resource paths, required supporting runtime/standards, host separation, and marketplace metadata. It rejects forbidden reference-template synchronization files and any MCP/agent/rules/hooks placeholders.

Validation MUST require the OpenAI marketplace source to be the repository-contained `./dist/openai` directory with `plugin.json`, `category: Productivity`, the existing policy, and the sole entry name matching manifest name `ai-agent-workflow`. It MUST reject absolute/traversing paths, paths to another host, missing targets, and paths escaping the repository (including through symlinks). The Claude marketplace MUST have exactly one entry whose name matches the `ai-agent-workflow` manifest and whose repository-contained source is `./dist/claude` with `.claude-plugin/plugin.json`. Marketplace installation and refresh MUST use the checked-out GitHub repository snapshot and MUST NOT query Releases or silently fall back to a Release asset when marketplace refresh fails.

### GitHub Release assets

`.github/workflows/release.yml` MUST trigger on pushed `v*` tags. Before publication it MUST accept only stable SemVer `vMAJOR.MINOR.PATCH` (ASCII digits, no leading zeroes except zero itself, no prerelease/build suffix), require equality with the canonical version, and require the tagged commit to be an ancestor of fetched `origin/main`. `prepare` gates `verify`; all four current CI combinations (Ubuntu/Python 3.10, Ubuntu/3.14, Windows/3.14, macOS/3.14) gate `publish`. Verification MUST preserve the current CI command order including the pre-mutation drift check and post-generation cleanliness check. Tag-keyed concurrency MUST NOT cancel an in-progress publication.

These Release ZIP and checksum assets are version-fixed/manual/offline downloads. Marketplace installation does not depend on a Release, its assets, or GitHub API lookup; Release policy and semantics remain independent from marketplace sources.

`python tools/package_release.py --tag vX.Y.Z --output-dir PATH` MUST check tag/version, distribution drift, and independent host validation before producing assets. It MUST NOT repair distributions or call GitHub APIs. It MUST emit exactly these four files:

- `ai-agent-workflow-openai-vX.Y.Z.zip`
- `ai-agent-workflow-claude-vX.Y.Z.zip`
- `ai-agent-workflow-antigravity-vX.Y.Z.zip`
- `SHA256SUMS`

Each ZIP MUST contain the corresponding `dist/<host>/` contents at archive root without a `dist/` prefix. Root manifests are `plugin.json` for OpenAI/Antigravity and `.claude-plugin/plugin.json` for Claude. Sorted member paths, `/` separators, fixed timestamps and permissions MUST make identical inputs yield identical ZIP bytes. `SHA256SUMS` MUST contain lowercase SHA-256 hashes, two spaces, and ZIP filenames in filename order, one LF-terminated entry per ZIP.

Only `publish` MUST receive `contents: write`. Publication MUST use `GITHUB_TOKEN` through `gh release`, package into runner temporary storage, create a Release only if absent using the existing tag, and replace the four expected assets on same-tag reruns. Invalid tags, version mismatch, non-main commits, drift, validation failures, or failed matrix jobs MUST prevent publication. Failed `gh` operations MUST report failure without changing source or tags. This workflow MUST NOT bump versions, auto-commit, push source/tags, publish to PyPI, or submit to OpenAI/Anthropic/Google publication services. OpenAI public Plugins Directory submission and Claude Enterprise Plugins API publication remain outside scope.

## Observable behavior

Each package can be inspected and validated without installing another host package. Generated Skills have identical workflow semantics, while manifests and marketplace metadata remain host-specific. OpenAI/Codex and Claude Code install from a GitHub repository marketplace checkout and use the corresponding `./dist/<host>` source. Release ZIPs remain fixed-version/manual/offline artifacts. Antigravity uses local/manual installation. Build and validation require no network access.

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
| Invalid release tag or version mismatch | Reject before creating packaging artifacts or publishing. |
| Tagged commit not contained in main or verification fails | Stop before the publication job. |
| Packaging detects drift or invalid host output | Fail without repairing generated trees or creating assets. |
| GitHub Release operation fails | Report the failed `gh` operation; source/tag stay unchanged. A rerun replaces expected assets. |
| Marketplace source is absolute, traverses `..`, resolves outside the checkout, points at another host, or is missing | Report a marketplace-source validation error; do not install from a Release or another source. |
| Marketplace refresh fails | Report the refresh failure; do not silently fall back to a latest Release or query a Release API. |

## Verification strategy

Tests compare two fresh builds byte-for-byte, prove `--check` detects hand-edited generated files, independently accept/reject host manifest fixtures, verify every Skill's links, prove OpenAI and Antigravity root manifests are not shared, and validate repository-contained OpenAI/Claude marketplace paths, names, categories, and targets. Host application/IDE and remote marketplace smoke tests are reported only when the actual product is available and the pushed repository/ref is exercised; otherwise they remain unverified.

Release regressions verify version ownership/injection, adapter-version rejection, missing/mismatched generated versions, dynamic setuptools configuration, tag failure modes without output, drift versus schema failure, archive layout/metadata/content, byte-identical independent packaging runs, recomputed checksums, and workflow gates/matrix/permissions. Actual tag-triggered publication is verified only after an explicitly authorized release tag is pushed after merge.
