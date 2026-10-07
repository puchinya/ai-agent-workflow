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
| Exact published bytes and atomic mirrors | `contracts.py` first bounds and validates source bytes, then structurally normalizes only a recognizable Reviewer Checklist H2; checklist items and bytes outside it remain exact. Hashes bind the normalized payload. Historical reads/restores do not normalize. A shared atomic writer uses sibling temporary files and `os.replace`. |
| Stable sequential hook composition | `profile.py` returns an ordered immutable command/skip plan before `process.py` executes it. |
| Current state gates delivery | `delivery.py` uses the initial Issue/PR pair as the evidence snapshot, validates Final Verification, self-review, QA, and Independent Review before evaluating Required Checks on the current HEAD, then re-reads Issue/PR and requires unchanged HEAD, exact bodies, open/draft/merged state, and `phase:review` presence. |
| Document decisions are structured and scoped | `documents.py` parses canonical decisions plus legacy links; `context.py` reports decisions and owners; `git.py` resolves changed-doc ranges. |
| Review and QA findings block handoff | `delivery.py` blocks non-pass verification, QA other than PASS/N/A, non-passing independent contract units, checklist failures, and blocking A/B/C findings; non-blocking checklist `untested` and D findings remain visible but do not block. |
| Complete contract conformance is machine-bound | `contracts.py` shares structural Reviewer Checklist H2 classification between safe Markdown-checkbox normalization, publication validation, and review derivation; `review.py` derives units only from actual Markdown H2 headings, excludes only strict-canonical checklist H2, and binds schema v2 to the approved contract comment ID/SHA, unit identities, checklist, and exact HEAD. |
| Stacked branch creation is fail-closed | `git.py` fetches the selected same-repository remote branch, verifies an optional expected SHA before switching, and never rebases existing targets. |
| Hook diagnostics are safe and temporary | `process.py` keeps output silent by default and emits only a redacted bounded tail from temporary capture files on diagnostic failure. |
| Milestones and branches follow consumer policy | `versioning.py` resolves an approved Issue target or configured fallback; `git.py` owns only argv-based local Git lifecycle; remote metadata and milestone mutations remain in `github.py`. |
| Workspace policy is enforced at execution start | `execution.py` verifies the approved Contract and atomically binds an Issue to a selected workspace/base; `git.py` reports Git metadata and publishes an isolated execution to its frozen canonical branch. The host owns creation, access control, resume, and cleanup. |

## Architecture

`cli.py` parses commands and converts domain errors into stable nonzero exit codes. `profile.py` validates Schema 1/2 and selects components/targets. `versioning.py` resolves and validates an Issue-scoped target or the configured fallback without dependencies; the existing `resolve_version()` API remains the fallback resolver. `git.py` owns branch lifecycle and changed-doc ref/diff subprocesses through argv; it coordinates clean-worktree checks, selected-base resolution, expected-SHA comparison, branch selection, safe cleanup, and the global switch-hook plan. `context.py` formats routing output, including structured document decisions. `documents.py` parses Issue document impact and validates durable Markdown structure and local links. `contracts.py` owns source-byte validation, safe Markdown checkbox normalization within a recognizable Reviewer Checklist H2, normalized exact-byte hashes, pointer format, mirror state, publication/restore flows, and the shared structural classifier. `verification.py` owns exact-HEAD final hook plans, command-hash-only receipts, and immutable public evidence. `review.py` derives contract units only from actual Markdown H2 headings and extracts checklist items from the canonical marker block first, then the narrow Markdown Reviewer Checklist H2 fallback using Markdown checkbox syntax; it also owns self-review v2 and current-HEAD independent-review drafts/publication/staleness. `qa.py` owns separate functional QA records with PASS/N/A semantics and immutable public evidence. `delivery.py` checks the four evidence gates before Required Checks and owns merged gates. `github.py` owns repository identity, default-branch metadata, Issue milestone state, and every `gh api` invocation. `process.py` executes configured non-GitHub hook commands sequentially; diagnostic output is captured temporarily and redacted before emission.

The dependency direction is CLI -> domain modules -> injected GitHub/process boundaries. Pure validators do not make network calls. `git.py` invokes Git only through argument arrays and never invokes the trusted shell-hook boundary for Git operations. GitHub functions return parsed JSON or raise explicit operation errors; they do not print payloads. Runtime code never imports files from the reference repository.

## Data flow and ownership

1. Parse arguments and discover repository root.
2. Load and validate all local profile/document state needed for the command.
3. Resolve scope and build an immutable plan. For context, parse structured Document impact or preserve routing from legacy links.
4. For milestone workflows, load the valid profile and same-repository Issue, then apply milestone policy before version resolution: disabled skips without a target override; otherwise an approved explicit Issue target bypasses the profile version source, while an absent target uses the configured fallback. Validate the selected title before any Milestone read that could lead to mutation. Branch workflows read authoritative repository/Issue state before mutation; fetch base refs only after a clean-worktree and same-repository Issue check, and compare an expected base SHA before any branch switch, cleanup, or hook.
5. For receipt, QA, self-review, and independent-review publication, validate current Issue/contract/PR identities and local payloads first. After creating each immutable comment, fetch its exact ID and verify PR association and exact body. Re-read Issue/contract and PR HEAD before updating its pointer; a failed named readback or race leaves an unreferenced immutable comment. Final Verification also requires a clean local worktree and local HEAD equal to the full PR HEAD before and after hooks. Independent-review publication accepts `fresh_context: true` only as a reviewer attestation and does not claim to prove provenance. For delivery, the initial Issue/PR pair is the shared validation snapshot; after the evidence gates and Required Checks, final readback compares exact Issue/PR body text, PR HEAD, Issue/PR state, and `phase:review` presence with that snapshot. Any difference fails handoff, and the final Issue body is parsed again for the approved contract as defense in depth.
6. Perform one mutation only after preconditions pass; read it back and validate it. Milestone reuse and assignment are exact-title/idempotent; a different existing Issue Milestone fails without create/assign. Branch cleanup and hooks follow only an actual switch.
7. Commit local state with atomic replacement only after remote verification, or keep old verified bytes on failure.
8. Clean temporary files in `finally` paths and print bounded diagnostics. Hook diagnostics stay silent on success and emit only a redacted combined tail of at most 16 KiB on failure. Post-switch failures preserve and report the switched branch.

### Workspace binding and publication

The implementation Skill resolves the selected base ref and exact SHA before evaluating host capability. Isolation is available only when the host can establish the workspace at that exact SHA; otherwise `auto` uses the current-checkout flow and `required` blocks. A valid managed linked worktree is reused; a new one is entered only after its starting base is verified. Before source edits, `prepare-implementation` verifies the Issue, exact approved Contract pointer, clean current workspace, base ref/SHA, initial HEAD, and execution mode. A local binding under `.agent-state/issues/N/execution.json` is atomic and ignored. Reuse after commits retains the frozen base and canonical branch. Explicit Contract supersession changes only its bound comment ID/SHA.

`execution.py` receives a GitHub boundary and calls Git helpers; it owns no raw subprocess or GitHub transport. `git.py` detects a linked worktree by comparing Git's per-worktree git directory with its common git directory. For isolated mode it leaves the local host branch or detached HEAD unchanged, but pushes HEAD to the binding's canonical branch using the existing non-force and remote-readback protections. Current mode and no-binding calls retain the existing configured-feature-branch requirement. Neither module creates or cleans up worktrees.

### Review-PR establishment sequence

`execution.py` freezes the selected base ref/SHA and canonical branch in the execution binding. The CLI reads the required body file and delegates to `delivery.ensure_review_pr`. Delivery validates body structure, repository/Issue/default/base identity, and the requested title, then loads the current execution binding. A binding's `base_ref` selects the PR base in both current and isolated mode; conflicting explicit values fail before push or PR/label mutation. With no binding, the explicit/default selection remains unchanged. `git.py` validates and publishes against that selected base, including selected-base ancestry, positive ahead count, and (for a bound execution) ancestry of the frozen base SHA. The remote base may advance as long as existing ancestry checks pass. With isolated mode it pushes HEAD to the frozen canonical Issue branch without changing the host-owned local branch; current mode and no binding retain the attached configured-feature-branch check. Delivery uses the published head branch and selected base for exact PR lookup/create/reuse, then replaces phase labels with exactly `phase:review`, preserving non-phase labels, and verifies fresh Issue and PR state. A failed phase transition retains PR identity for retry. No step merges the PR or weakens later self-review/Required Check gates.

## Failure handling

`gh api` receives argument arrays. Large body values travel through JSON temporary files, not command arguments. The environment owns authentication. Git commands use argv arrays. Default hook output is suppressed; diagnostic capture is removed on all handled paths and credential-redacted before a bounded failure tail is emitted. Issue identifiers, repository owner/name, remote refs, expected SHAs, returned comment/PR associations, hashes, and lengths are checked before success. Atomic writes preserve previous verified data on ordinary failures.

## Alternatives considered

- One monolithic `agent_tool.py` would couple profile, GitHub, and review logic. Focused modules make fake transports and focused tests possible.
- A general HTTP client would need a new credential boundary. The existing authenticated `gh api` transport is explicit and testable.
- GitHub mutations carry user data as structured JSON over stdin and never interpolate payloads into a shell command. Explicit local hook strings run in the user's shell because the profile is trusted configuration; child output is suppressed by default, with an opt-in redacted diagnostic tail for failures.
- Parallel hook execution would destroy declared order and complicate failure evidence. Hooks remain sequential.

## Verification strategy

Each module has pure boundary tests, while API workflows inject a fake `github.py` interface. Tests assert both expected calls and forbidden calls, especially zero hook execution on invalid profiles, no unrelated-comment fetch on restore, no write on bad identity, and no mutation on failed delivery checks.
