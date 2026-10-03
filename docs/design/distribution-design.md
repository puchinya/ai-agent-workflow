<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# Distribution Design

- Status: Approved
- Owning Issue: [Issue #1](https://github.com/puchinya/ai-agent-workflow/issues/1)
- Related specification: [Distribution Specification](../specs/distribution-spec.md)

## Context and goals

OpenAI Agent Plugins and Antigravity both use root `plugin.json` but validate different schemas. Claude uses `.claude-plugin/plugin.json`. The build therefore creates three separate directories, each with its own manifest and host-specific packaging metadata, while copying Skills and runtime support from a single source tree.

## Requirements traceability

| Requirement | Design consequence |
|---|---|
| One hand-authored source | `workflow/skills`, `workflow/standards`, `workflow/templates`, `runtime/agent_workflow`, and `adapters` are the only authored inputs. |
| Distinct host schemas | `adapters/openai`, `adapters/claude`, and `adapters/antigravity` own small manifests/marketplace data. |
| No manual generated edits | The builder computes an expected file map, then either writes it or compares it with disk. |
| Independent validation | The validator uses one explicit validation function per host and produces package-specific errors. |

## Architecture

Each adapter owns only its host manifest and marketplace metadata. The package builder combines those host-specific descriptors with one canonical copy of Skills, standards, templates, documentation, and runtime modules.

## Data flow and ownership

Canonical files are read as bytes and mapped to package-relative paths. The complete path/content map is prepared before generated destinations are changed. Marketplace files are generated from adapter metadata and point at the corresponding isolated package.

### Build flow

1. Read the fixed canonical inputs as UTF-8 bytes.
2. Construct each package manifest from its adapter JSON and version metadata.
3. Copy only required Skills, standards, templates, and runtime modules into the package.
4. Create the OpenAI repo marketplace entry that points at `dist/openai`.
5. Sort package paths and serialize JSON with stable indentation/newlines.
6. In normal mode, write the expected path set and remove only stale files under the generated `dist/**` roots. In `--check` mode, make no writes and report all path/content mismatches.
7. Validate each package separately after build; `validate_dist.py` can also validate existing output without rebuilding.

## Package boundaries

The OpenAI package uses the portable root manifest and optionally references only resources supported by the current Agent Plugins format. The Claude package has its nested manifest and Claude-specific marketplace metadata; its manifest is never reused by the other hosts. The Antigravity package uses its own root manifest and includes no empty components. Shared Skills keep host-neutral Markdown; adapters contain only installation and host discovery instructions.

Generated packages include `skills/`, `standards/`, `templates/`, and `runtime/agent_workflow/` as required resources. No top-level `bin/` is emitted. No `update-template` or reference repository files are emitted.

## Failure handling

Build inputs that are missing or malformed fail before destination mutation. Normal build prepares the complete expected map before writing. `--check` never repairs drift. The validator reports all independent package errors in one run but exits nonzero if any package is invalid. External network access is not used by build or validation.

## Alternatives considered

- A shared OpenAI/Antigravity manifest cannot satisfy both schemas.
- Hand-editing `dist/**` would make fixes non-reproducible.
- Fetching schemas at runtime would make local builds network-dependent; current host requirements are recorded and validators remain deterministic.
- Adding placeholder hooks, agents, rules, or MCP configuration would claim unsupported behavior.

## Verification strategy

Build twice in separate temporary directories and compare all relative paths and bytes. Edit one generated file and verify `--check` catches it. Validate the three manifests from their own package paths, verify local marketplace links, and run the optional Claude/Antigravity/OpenAI product smoke tests only when the actual host is available.
