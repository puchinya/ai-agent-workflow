<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# Distribution Design

- Status: Approved
- Owning Issue: [Issue #1](https://github.com/puchinya/ai-agent-workflow/issues/1)
- Release automation: [Issue #3 contract](https://github.com/puchinya/ai-agent-workflow/issues/3#issuecomment-5963850384)
- Related specification: [Distribution Specification](../specs/distribution-spec.md)

## Context and goals

OpenAI Agent Plugins and Antigravity both use root `plugin.json` but validate different schemas. Claude uses `.claude-plugin/plugin.json`. The build therefore creates three separate directories, each with its own manifest and host-specific packaging metadata, while copying Skills and runtime support from a single source tree.

## Requirements traceability

| Requirement | Design consequence |
|---|---|
| One hand-authored source | `workflow/skills`, `workflow/standards`, `workflow/templates`, `runtime/agent_workflow`, and `adapters` are the only authored inputs. |
| Distinct host schemas | `adapters/openai`, `adapters/claude`, and `adapters/antigravity` own small manifests/marketplace data. |
| GitHub-hosted OpenAI/Claude marketplaces | The repository hosts root marketplace manifests; GitHub marketplace registration resolves `./dist/openai` or `./dist/claude` within its checkout. |
| Separate Release distribution | Existing version-fixed ZIPs and `SHA256SUMS` serve manual/offline installs; marketplace installs do not look up Releases or use Release assets. |
| Conservative Antigravity support | Keep Antigravity local/manual because third-party GitHub marketplace support is unconfirmed. |
| No manual generated edits | The builder computes an expected file map, then either writes it or compares it with disk. |
| Independent validation | The validator uses one explicit validation function per host and produces package-specific errors. |
| Single version authority | Setuptools reads the runtime attribute; the builder rejects adapter versions and injects it for OpenAI/Claude only. |
| Gated tag publication | Full-history `prepare` checks stable SemVer/version and main ancestry before the four-platform `verify` matrix can enable `publish`. |
| Deterministic release assets | A local standard-library ZIP packager checks drift/validation and normalizes layout, timestamps, permissions, and checksums. |
| Idempotent publication with limited permission | Tag concurrency serializes reruns; only `publish` gets write access and uses `gh release upload --clobber`. |

## Architecture

Each adapter owns only its host manifest and marketplace metadata, excluding version. The GitHub repository itself is the marketplace host for OpenAI/Codex and Claude Code: marketplace registration checks out the repository, then the host resolves a relative source under `dist/`. The package builder combines the host-specific descriptors with one canonical copy of Skills, standards, templates, documentation, and runtime modules. The canonical runtime `__version__` also supplies setuptools dynamic metadata and generated OpenAI/Claude versions. Antigravity's restricted schema remains versionless and its installation remains local/manual.

## Data flow and ownership

Canonical files are read as bytes and mapped to package-relative paths. The complete path/content map is prepared before generated destinations are changed. Root marketplace files are generated from adapter metadata and point at the corresponding isolated package inside this same repository checkout. The GitHub repository supplies transport; generated source paths remain relative and repository-contained.

`.gitattributes` pins serialized OpenAI/Claude generated manifest JSON and repository marketplace JSON to LF so Windows Git checkout conversion cannot introduce drift before generation. Other copied resources retain their existing byte-copy semantics.

### Build flow

1. Read the fixed canonical inputs as UTF-8 bytes.
2. Parse OpenAI/Claude adapter JSON objects, reject adapter-owned version keys, inject `agent_workflow.__version__`, and serialize sorted keys with stable indentation and a trailing LF. Preserve the Antigravity manifest without adding version metadata.
3. Copy only required Skills, standards, templates, and runtime modules into the package.
4. Create the OpenAI repository marketplace entry with category `Productivity` and source `./dist/openai`; preserve its existing policy.
5. Sort package paths and serialize JSON with stable indentation/newlines.
6. In normal mode, write the expected path set and remove only stale files under the generated `dist/**` roots. In `--check` mode, make no writes and report all path/content mismatches.
7. Validate each package separately after build; `validate_dist.py` can also validate existing output without rebuilding.

## Package boundaries

The OpenAI package uses the portable root manifest and optionally references only resources supported by the current Agent Plugins format. The repository-root `.agents/plugins/marketplace.json` has one `ai-agent-workflow` entry for `./dist/openai`. The Claude package has its nested manifest and Claude-specific marketplace metadata; its root marketplace manifest has one matching `ai-agent-workflow` entry for `./dist/claude`. Each path stays inside the GitHub marketplace checkout and targets the corresponding manifest. Neither marketplace source refers to GitHub Release assets or API lookups. Antigravity uses its own root manifest, includes no empty components, and stays local/manual while GitHub marketplace support is unconfirmed. Shared Skills keep host-neutral Markdown; adapters contain host installation and discovery instructions.

Generated packages include `skills/`, `standards/`, `templates/`, and `runtime/agent_workflow/` as required resources. No top-level `bin/` is emitted. No `update-template` or reference repository files are emitted.

### Release flow

The tag workflow checks out the tag with full history. `prepare` passes the tag through the packager's pure `validate_tag` function, fetches `origin/main`, and uses `git merge-base --is-ancestor HEAD origin/main`. Annotated tags work because checkout resolves to the tagged commit. `verify` depends on `prepare` and duplicates the current CI matrix and command sequence. `publish` depends on the entire matrix and runs on Ubuntu/Python 3.14. Global permissions are read-only; only the publication job overrides contents permission to write. Tag-keyed concurrency queues reruns without cancelling an active publication.

The packager builds the complete expected map in memory, compares existing distributions/marketplaces without writes, and then runs host validation. Only after both succeed does it create the output directory. It archives the verified map's host bytes, stripping `dist/<host>/` and sorting relative POSIX paths. Standard-library `ZipFile` uses stored entries, avoiding zlib-version variability; each entry has the DOS epoch timestamp (1980-01-01 00:00:00), Unix creator system, and regular-file mode 0644. No directory entries are needed. Sorted ZIP filenames determine the SHA-256 manifest order; UTF-8 bytes with LF preserve checksum output across platforms.

The workflow packages into runner temporary storage, then probes the Release with `gh release view`. Only the explicit `release not found` response triggers `gh release create --verify-tag`; other lookup errors fail immediately. `--verify-tag` prevents accidental tag creation. `gh release upload` names all four files explicitly and uses `--clobber` to replace those expected assets on reruns. The Release/tag is reused; no external publication credentials or provider APIs are involved.

## Failure handling

Build inputs that are missing or malformed fail before destination mutation. Normal build prepares the complete expected map before writing. `--check` never repairs drift. The validator reports all independent package errors in one run but exits nonzero if any package is invalid. External network access is not used by build or validation.

Marketplace validation rejects absolute paths, traversal, paths that resolve outside the repository, unexpected host paths, missing directories/manifests, mismatched entry/manifest names, and incorrect OpenAI category or policy. Hosts refresh the registered marketplace from its GitHub checkout. A failed fetch or refresh is reported by the host and never redirects installation to a Release, a newer tag, or a network lookup.

The packager checks tag syntax and version before reading distributions and checks drift before host validation; each failure has a distinct diagnostic and creates no artifacts. Failed main ancestry or any matrix job blocks publication. Shell failure propagation reports failed creation/upload operations; lookup errors also name the failed operation. Publication cannot modify source or tags. A failed upload can leave a partial Release asset set; a same-tag rerun replaces expected assets to converge on the four intended outputs.

## Alternatives considered

- A shared OpenAI/Antigravity manifest cannot satisfy both schemas.
- A separate registry, marketplace server, Release-asset source, or install-time API lookup would duplicate GitHub marketplace hosting and violate the repository-contained source contract.
- Claiming a GitHub marketplace for Antigravity without confirmed third-party support would overstate the host capability; its local/manual path stays in place.
- Hand-editing `dist/**` would make fixes non-reproducible.
- Fetching schemas at runtime would make local builds network-dependent; current host requirements are recorded and validators remain deterministic.
- Adding placeholder hooks, agents, rules, or MCP configuration would claim unsupported behavior.
- Merge-driven releases, adapter-owned versions, automatic commit-derived version bumps, and release-management frameworks conflict with the explicit tag/canonical-version contract.
- Shell ZIP and third-party release actions would bypass the explicit deterministic Python packager and `gh release` publication boundary.

## Verification strategy

Build twice in separate temporary directories and compare all relative paths and bytes. Edit one generated file and verify `--check` catches it. Validate the three manifests from their own package paths, verify local marketplace links, and run the optional Claude/Antigravity/OpenAI product smoke tests only when the actual host is available.

Package twice into independent temporary directories and compare all four output bytes, root manifests, member contents/order/metadata, and recomputed SHA-256 entries. Regressions separately exercise invalid syntax, version mismatch, drift, and schema validation failures without output. Workflow tests compare verification commands and matrix directly against CI and inspect dependency, ancestry, concurrency, token, explicit asset, and permission boundaries. Product installation, external directory/Enterprise publication, and actual tag-triggered GitHub Release publication remain unverified unless executed.
