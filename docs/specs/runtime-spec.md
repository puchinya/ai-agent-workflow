<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Runtime and CLI Specification

- Status: Approved
- Owning Issue: [Issue #1](https://github.com/puchinya/ai-agent-workflow/issues/1)
- Related design: [Runtime design](../design/runtime-design.md)
- Workflow invariants: [Portable Workflow Specification](workflow-spec.md)

## Purpose

Define observable behavior for the Python 3.10+ command `python -m agent_workflow <command>`. The runtime is standard-library-first, synchronous, and one-shot. GitHub I/O is owned only by `agent_workflow.github` and uses authenticated `gh api` with argument arrays and structured JSON.

## Scope

The CLI MUST provide `init-project`, `agent-context`, `validate-docs`, `run-hook`, `save-implementation-contract`, `publish-implementation-contract`, `restore-implementation-contract`, `verify-implementation-contract`, `prepare-self-review`, `validate-self-review`, `publish-self-review`, `validate-public-review`, `delivery-check`, and `finalize-merged-issue`.

The commands `update-template` and `refresh-template-manifest` are forbidden. No module other than `github.py` may invoke `gh` directly. Every GitHub mutation uses JSON input files or structured fields, never shell interpolation of user payloads.

GitHub comment, event, check-run, and commit-status collections MUST paginate with explicit `page=N&per_page=100` GET requests until a selected page contains fewer than 100 items. The transport preserves API order and fails with `GitHubError` on malformed page shapes. Direct named-comment verification remains a single-ID fetch.

## Normative requirements

### Project profile and context

`.agent/project.json` is the consumer's machine authority. Schema 1 remains readable with its existing flat hooks and is never rewritten automatically. New `init-project` output is Schema 2. Unsupported versions and malformed profiles fail before routing, output, or configured command execution.

Schema 2 separates components, stacks, application types, targets, and invocation-time runtime host. Application types are exactly `generic`, `desktop-gui`, `cli`, `mobile`, `server`, `embedded`, and `library`; `generic` does not select a profile document. Types are never inferred. Explicit unknown non-empty stack IDs remain opaque. Component roots are safe repository-relative paths; components and targets have unique IDs in their scope; hook values are arrays of non-empty trusted command strings. Target `runnable_on` contains only `any`, `windows`, `macos`, or `linux`. Optional target `requirements` has exactly three required arrays: `architectures`, `tools`, `capabilities`.

`init-project` deterministically writes a validated root component with root `.`, detected or explicitly supplied stacks, generic unless explicitly selected, and no targets unless requested. New targets default to `runnable_on: ["any"]`. Branch and milestone policy are objects; new projects use branch prefix `feature`, slug limit 48, and milestones disabled with automatic version source. `cargo clean` is added only to the global `branch_switch` hook when Rust is detected and `--cargo-clean on` is explicit. Initializing a generic component emits a warning.

`agent-context N` reports existing workflow/branch/HEAD/PR/contract fields plus profile schema, normalized runtime host, affected components, component metadata, applicable non-generic profile paths, and explicit document owners. One-component profiles default to that component when the Issue omits `## Affected components`; multi-component profiles require a non-empty canonical section. Unknown IDs fail. `all` has no special meaning. Document owners are emitted only from explicit same-repository links under `## Document impact` to existing paths in `docs/specs/`, `docs/design/`, or `docs/status/`; planned paths remain `planned_owner`. Ambiguous, malformed, or foreign URLs produce bounded diagnostics. Context is read-only, path-only, and never fetches linked pages or inlines document/comment/issue bodies. Closed Issue state takes precedence over phase labels and yields `phase=closed` with no workflow.

Schema 1 retains flat project-wide command strings. Schema 2 project hooks own `branch_switch`, `verify_quick`, and `verify_final`; component and target hooks own only the two verification names. `run-hook branch_switch` runs global hooks only and accepts no component or Issue selector.

`run-hook verify_quick` and `verify_final` run sequentially in the exact order project hooks, all selected component hooks in profile order, then compatible target hooks in profile order, preserving command order. Without a selector, both verification hooks select all components. Quick accepts mutually exclusive repeatable `--component` or `--issue`; Issue routing failures occur before hooks. Target gates run OS, normalized architecture, PATH tools (`shutil.which`), then explicit `--capability` values; only the first mismatch is reported. A mismatch skips the target command and emits `SKIPPED_TARGET_VERIFICATION component=<id> target=<id> reason=host_mismatch|architecture_mismatch|missing_tool|missing_capability`; skipped targets stay unverified. Python command aliases may fall back between `python` and `python3` only when the requested executable is unavailable; other command text is unchanged. Hook output is suppressed so commands cannot accidentally disclose tokens or payloads.

### Document validation

Specifications and designs use Schema-2 document markers and their respective required section sets. `validate-docs` validates markers, required headings, and local relative Markdown links (including reference links and fragments). It ignores links inside fenced code, does not fetch external links, and performs no migration or template operations.

### Implementation Contract bytes and storage

The complete contract is one top-level comment on its owning Issue. The Issue body `## Implementation Contract` section contains only `Comment ID: <integer>`, `SHA-256: <64 lowercase hex>`, and `State: approved`. The comment first line is `<!-- agent-contract:v1 issue=N sha256=HEX bytes=DECIMAL -->`, followed by one blank line and the exact original UTF-8 payload bytes.

Payloads are non-empty, valid UTF-8, NUL-free, free of obvious credential material, and at most 65,536 raw bytes. The rendered comment including header is at most 65,536 characters and is rejected locally before a remote mutation if too large. Hashes and byte counts cover the raw payload only; line endings and final newline are preserved.

`save-implementation-contract N [path]` saves a local Issue-scoped mirror without normalizing bytes. `publish-implementation-contract N [--source PATH] [--supersede]` validates Issue identity, reuses an identical pending/current comment, verifies the comment by ID and readback, and updates only the pointer section after an immediate body read; it reads the resulting body back. Same Issue/SHA is idempotent. A changed SHA requires explicit `--supersede` and leaves the old comment intact. API uncertainty never changes a verified local mirror.

`restore-implementation-contract N [--replace-stale]` reads only the recorded comment by ID. It validates ownership, Issue association, size, SHA, and exact bytes before writing. A differing mirror fails unless replacement is explicit; replacement first saves a SHA-specific backup then uses temp-file plus atomic replace. An update failure leaves local verified state unchanged.

`verify-implementation-contract N` validates the local record, current pointer, and named source comment without listing unrelated comments.

### Self-review and delivery

The effective checklist is approved Contract checklist items in source order as `C001...`, then Issue Reviewer Checklist items in source order as `I001...`. A valid `AGENT_REVIEWER_CHECKLIST_V1` canonical block wins; otherwise only a narrow `Reviewer Checklist` heading matches, optionally with a numeric prefix and one ASCII or Japanese parenthetical qualifier.

`prepare-self-review` binds a review draft to the current Issue, effective checklist SHA, and exact PR HEAD. `validate-self-review` requires each item to have a supported result and concrete evidence; evidence formatting is not proof. `publish-self-review` validates against current HEAD, stores one top-level PR comment, verifies comment association/SHA/checklist/HEAD, then writes only the PR body pointer. `validate-public-review` fetches only the named comment and marks it stale whenever PR HEAD differs.

Handoff requires the requested Issue and PR to belong to the same repository; open non-draft PR; `Closes #N`; Issue label `phase:review`; PR head equal to the published review HEAD; valid named review and effective checklist; filled Verification and Untested fields; schema-valid project profile allowing `initialized:false`; and every configured Required Check green on the current HEAD. No configured checks is a failure. App-scoped checks require the exact app; source-unrestricted or legacy checks may match a successful check-run or commit status. Check-run conclusions `success`, `skipped`, and `neutral` pass; commit statuses require `success`.

Merged delivery requires a merged PR, closed Issue, and no phase label. `finalize-merged-issue` verifies merged/closed state and removes only `phase:review`; any other `phase:*` label fails without mutation. Repeating after that label is gone succeeds without mutation. A PR affecting a generic component needs a concrete `Generic profile rationale:`.

### Failure, logging, and cleanup

Malformed profiles fail before hooks. Unknown scope never broadens. Subprocess failures retain the exit status and identify the command without secrets. GitHub identity/API ambiguity fails closed. Temporary payloads are removed on handled success/failure paths. Tokens and payload contents are never printed. Skipped targets and unexecuted platform tests are reported as unverified, not passed.

## Observable behavior

Commands produce bounded JSON or explicitly described skip lines. They identify affected Issue, component, target, contract SHA, review HEAD, and gate result without printing payload content or credentials. Read-only commands never mutate Issue, PR, profile, or source documents.

## Data and API formats

Schema-2 profile fields are `schema_version`, `initialized`, `project_name`, `components`, `branch`, `milestones`, and project `hooks`. `branch.required_checks` is an array of names or `{name, app_id}` entries; an empty array prevents handoff. Each component declares `id`, `roots`, `stacks`, `application_types`, `targets`, and verification `hooks`; targets declare `id`, `runnable_on`, verification `hooks`, and optional `requirements`. Hook arrays contain command strings; project hooks may include `branch_switch`, while component and target hooks may not.

The canonical checklist block is delimited by the exact lines `<!-- AGENT_REVIEWER_CHECKLIST_V1 -->` and `<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->`; valid checkbox items inside it take precedence over the narrow `Reviewer Checklist` heading fallback.

Issue-scoped local state lives below `.agent-state/issues/N/`. Contract state contains the exact payload and SHA metadata. Self-review state records Issue, PR, HEAD, checklist SHA, and item evidence. Temporary JSON/payload files are outside committed source and are removed after use.

## Security and privacy

GitHub requests use authenticated `gh api` through one module. User payloads travel as structured JSON input, not shell strings. Local contract state is Issue-scoped and should remain uncommitted; temporary data is cleaned after use.

## Error and boundary behavior

| Condition | Required behavior |
|---|---|
| Unsupported profile or malformed target requirements | Fail before output or any configured hook. |
| Missing/malformed Issue component list | Fail before hook execution or partial context output. |
| Host/architecture/tool/capability mismatch | Skip only the target and report it unverified. |
| Contract hash, comment, Issue, or mirror mismatch | Fail closed; preserve prior verified bytes. |
| Concurrent Issue body change | Stop, preserve unrelated sections, report unsupported concurrency. |
| Stale review HEAD or absent/pending/failed required check | Fail handoff. |
| Premature merge finalization or unexpected phase label | Fail without label mutation. |
| Network/API/auth failure | Report exact command/stage and fail closed. |

## Verification strategy

The test suite uses fake GitHub responses and temporary directories. It covers Schema 1/2 boundaries, routing and hook order, no-execution skips, local links, exact-byte hashes and limits, pointer races, comment identity, mirror backup/atomic replacement, checklist precedence, stale review, every handoff precondition, Required Checks, idempotent finalization, and path behavior on POSIX and Windows. The contract command list and acceptance matrix are kept in tests; this specification owns semantics.
