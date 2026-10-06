<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# Runtime and CLI Design

- Status: Approved
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related specification: [Runtime and CLI Specification](../specs/runtime-spec.md)

## Context and goals

The CLI must be easy to run from a consumer checkout, fakeable in tests, and safe when GitHub or local state is uncertain. Python 3.10+ standard library supplies filesystem, hashing, process, and JSON support. There is no MCP server, dependency service, or daemon.

## Requirements traceability

| Requirement | Design consequence |
|---|---|
| GitHub operations have one owner | `github.py` is the only module that invokes `gh api`; callers use typed repository/Issue/PR operations. |
| Safe branch publication has one owner | `git.py` validates the Issue branch/base/worktree, pushes only the current branch without force, and verifies remote HEAD. |
| PR establishment is deterministic and retryable | `delivery.py` sequences validation, verified push, exact head/base query, create/reuse, phase replacement, and readback; retries reuse the same PR. |
| Fail before side effects on malformed input | `profile.py`, `contracts.py`, and `review.py` expose pure validators used before `process.py` or GitHub calls. |
| Exact payload bytes and atomic mirrors | Contract codecs operate on `bytes`; `documents.py` owns same-repository Markdown path checks; a shared atomic writer uses sibling temporary files and `os.replace`. |
| Stable sequential hook composition | `profile.py` returns an ordered immutable command/skip plan before `process.py` executes it. |
| Current state gates delivery | `delivery.py` composes fresh Issue, PR, review, and Required Check responses; it never trusts a local submitted claim alone. |
| Document decisions are structured and scoped | `documents.py` parses canonical decisions plus legacy links; `context.py` reports decisions and owners; `git.py` resolves changed-doc ranges. |
| Review failures block handoff | `delivery.py` checks current review layers, returns bounded failure/untested details, blocks contract-section `fail` and `untested`, and preserves non-blocking checklist `untested`. |
| Complete contract conformance is machine-bound | `contracts.py` shares structural Reviewer Checklist H2 classification between publication validation and review derivation; `review.py` excludes only strict-canonical checklist H2 and includes legacy/non-canonical H2 units, while binding schema v2 to the approved contract comment ID/SHA, unit identities, checklist, and exact HEAD. |
| Stacked branch creation is fail-closed | `git.py` fetches the selected same-repository remote branch, verifies an optional expected SHA before switching, and never rebases existing targets. |
| Hook diagnostics are safe and temporary | `process.py` keeps output silent by default and emits only a redacted bounded tail from temporary capture files on diagnostic failure. |
| Milestones and branches follow consumer policy | `versioning.py` resolves an approved Issue target or configured fallback; `git.py` owns only argv-based local Git lifecycle; remote metadata and milestone mutations remain in `github.py`. |

## Architecture

`cli.py` parses commands and converts domain errors into stable nonzero exit codes. `profile.py` validates Schema 1/2 and selects components/targets. `versioning.py` resolves and validates an Issue-scoped target or the configured fallback without dependencies; the existing `resolve_version()` API remains the fallback resolver. `git.py` owns branch lifecycle and changed-doc ref/diff subprocesses through argv; it coordinates clean-worktree checks, selected-base resolution, expected-SHA comparison, branch selection, safe cleanup, and the global switch-hook plan. `context.py` formats routing output, including structured document decisions. `documents.py` parses Issue document impact and validates durable Markdown structure and local links. `contracts.py` owns exact bytes, pointer format, mirror state, publication/restore flows, strict publication-time authoring validation, and the shared structural Reviewer Checklist H2 classification. `review.py` owns historical-compatible checklist extraction and contract-unit derivation, section/item evidence validation, current contract comment ID/SHA/checklist/HEAD binding, v1 diagnostics, race-safe v2 public review records, named-comment readback, and pointer readback. `delivery.py` owns handoff enforcement, bounded contract failure/untested reporting, and merged gates. `github.py` owns repository identity, default-branch metadata, Issue milestone state, and every `gh api` invocation. `process.py` executes configured non-GitHub hook commands sequentially; diagnostic output is captured temporarily and redacted before emission.

The dependency direction is CLI -> domain modules -> injected GitHub/process boundaries. Pure validators do not make network calls. `git.py` invokes Git only through argument arrays and never invokes the trusted shell-hook boundary for Git operations. GitHub functions return parsed JSON or raise explicit operation errors; they do not print payloads. Runtime code never imports files from the reference repository.

## Data flow and ownership

1. Parse arguments and discover repository root.
2. Load and validate all local profile/document state needed for the command.
3. Resolve scope and build an immutable plan. For context, parse structured Document impact or preserve routing from legacy links.
4. For milestone workflows, load the valid profile and same-repository Issue, then apply milestone policy before version resolution: disabled skips without a target override; otherwise an approved explicit Issue target bypasses the profile version source, while an absent target uses the configured fallback. Validate the selected title before any Milestone read that could lead to mutation. Branch workflows read authoritative repository/Issue state before mutation; fetch base refs only after a clean-worktree and same-repository Issue check, and compare an expected base SHA before any branch switch, cleanup, or hook.
5. For self-review publication, read the Issue pointer and named contract comment, then PR HEAD, derive exact-byte section and checklist identities, and validate the local draft. After creating the immutable review comment, immediately fetch that exact comment ID and verify ID, PR association, and exact body. Only after named-comment readback succeeds, re-read Issue/contract first and PR HEAD second; only matching state may update the pointer. A failed readback or race leaves an unreferenced immutable comment. For other remote workflows, read authoritative metadata, validate all identity/pointer preconditions, and prepare a temporary structured payload.
6. Perform one mutation only after preconditions pass; read it back and validate it. Milestone reuse and assignment are exact-title/idempotent; a different existing Issue Milestone fails without create/assign. Branch cleanup and hooks follow only an actual switch.
7. Commit local state with atomic replacement only after remote verification, or keep old verified bytes on failure.
8. Clean temporary files in `finally` paths and print bounded diagnostics. Hook diagnostics stay silent on success and emit only a redacted combined tail of at most 16 KiB on failure. Post-switch failures preserve and report the switched branch.

### Review-PR establishment sequence

The CLI reads the required body file and delegates to `delivery.ensure_review_pr`. Delivery validates body structure, repository/Issue/default/base identity, and the requested title, then asks `git.py` to verify clean worktree, current Issue feature branch, one same-repository origin fetch and push URL, no mirror-push configuration, non-default branch, selected-base ancestry, and a positive ahead count. Only after those checks does `git.py` push the current branch without force or tag following and verify origin's branch SHA against local HEAD. Delivery then queries exact base/head candidates through `github.py`, fails closed on duplicates, drafts, forks, or conflicting Issue closures, and creates or updates one compatible PR. Finally it replaces phase labels with exactly `phase:review`, preserving non-phase labels, and verifies fresh Issue and PR state. If label replacement/readback fails, the error includes the established PR identity; retries reuse that PR. No step merges the PR or weakens later self-review/Required Check gates.

## Failure handling

`gh api` receives argument arrays. Large body values travel through JSON temporary files, not command arguments. The environment owns authentication. Git commands use argv arrays. Default hook output is suppressed; diagnostic capture is removed on all handled paths and credential-redacted before a bounded failure tail is emitted. Issue identifiers, repository owner/name, remote refs, expected SHAs, returned comment/PR associations, hashes, and lengths are checked before success. Atomic writes preserve previous verified data on ordinary failures.

## Alternatives considered

- One monolithic `agent_tool.py` would couple profile, GitHub, and review logic. Focused modules make fake transports and focused tests possible.
- A general HTTP client would need a new credential boundary. The existing authenticated `gh api` transport is explicit and testable.
- GitHub mutations carry user data as structured JSON over stdin and never interpolate payloads into a shell command. Explicit local hook strings run in the user's shell because the profile is trusted configuration; child output is suppressed by default, with an opt-in redacted diagnostic tail for failures.
- Parallel hook execution would destroy declared order and complicate failure evidence. Hooks remain sequential.

## Verification strategy

Each module has pure boundary tests, while API workflows inject a fake `github.py` interface. Tests assert both expected calls and forbidden calls, especially zero hook execution on invalid profiles, no unrelated-comment fetch on restore, no write on bad identity, and no mutation on failed delivery checks.
