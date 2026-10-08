<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Design

- Status: Approved
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related specification: [Portable Workflow Specification](../specs/workflow-spec.md)

## Context and goals

The workflow must feel consistent in three agent hosts while respecting each host's plugin format. The source remains repository-owned Markdown, standards, and a standard-library Python CLI. Host packages are deterministic projections of that source, not separate authoring trees.

Goals are explicit Issue authority, progressive context loading, reliable local verification, recoverable exact-byte records, independent review evidence, and reproducible delivery gates. No remote service or persistent runtime process is introduced.

## Requirements traceability

| Requirement | Design consequence |
|---|---|
| One semantic owner per rule | Workflow phase policy lives in this specification; CLI data and failure semantics live in the [Runtime specification](../specs/runtime-spec.md). |
| Ten host-portable Skills | Hand-authored Skills live only under `workflow/skills/`; the distribution builder copies them. |
| Compact context routing | The runtime emits validated paths and identifiers rather than document contents. |
| Review is evidence, not approval | Self-review and independent-review records bind claims to contract units, checklist, and exact PR HEAD; runtime validates the fresh-context attestation but cannot prove provenance. |
| Self-review covers the complete approved contract | A schema-v2 contract-conformance layer records evidence for deterministic H2 units; safely normalized new Reviewer Checklist H2 may be excluded, while legacy/non-canonical historical checklist H2 remains covered as a unit. The Reviewer Checklist remains a separate concise summary. |
| Durable document decisions stay explicit through implementation | The Issue carries Specification, Design, and Status decisions; implementation checks them against the final diff, and self-review verifies alignment. |
| Four evidence gates precede Required Checks | The delivery gate checks Final Verification, self-review, QA, and Independent Review in order before Required Checks for the same current HEAD. |
| Host-specific packages differ | The builder emits three isolated packages from shared sources and adapters. |
| Milestone and feature-branch lifecycle is reusable | Milestone mode and fallback source stay in Schema 2 `.agent/project.json`; an approved target release is Issue-scoped input, and the requirements and implementation Skills call standard runtime commands. |
| Approved Contract execution has a stable workspace | The Contract execution Skill asks the host to reuse/create its native isolated workspace according to policy, then writes a local Issue execution binding before edits; host lifecycle stays outside the runtime. |
| Execution authorization continues to the review PR | An approved Issue contract covers routine Issue-scoped commit/push/PR/review-phase/self-review/check operations; Skills do not add a PR-specific prompt. |
| Implementation owns end-to-end handoff | The implementation flow continues through a review-ready PR, exact-HEAD self-review, and delivery gate before reporting completion. |
| New Contract layout is checked without changing legacy publication | A separate read-only preflight validates the canonical template's physical H2 structure before new-template contracts are saved or published; the historical comment and mirror path remains unchanged. |
| Chat project instructions work across hosts | One Japanese project-instructions body uses one repository URL substitution and describes only capabilities available to the active chat; it does not depend on installing this workflow plugin. |

## Architecture

```text
workflow/ ─────┐
runtime/ ──────┼──> tools/build_dist.py ──> dist/openai|claude|antigravity
adapters/ ─────┘             │
                             └──> tools/validate_dist.py

consumer Issue + .agent/project.json
                 │
                 v
          agent_workflow CLI
          ├── profile/context/documents
          ├── versioning/git lifecycle
          ├── contract/review/delivery
          ├── git.py -> argv-only Git subprocesses
          └── github.py -> authenticated `gh api` for Issues, milestones, and repository metadata
```

`workflow/`, `runtime/`, and `adapters/` are canonical hand-authored trees. `dist/**` is generated and MUST NOT be hand-edited. The CLI is a one-shot Python 3.10+ application using the standard library. GitHub transport is isolated in one module. Git lifecycle commands are isolated in `git.py`; they use subprocess argv, never shell interpolation. Tests replace those boundaries with fakes and do not use network credentials.

## Data flow and ownership

1. A Skill starts from an Issue and reads only the routing data and documents relevant to that task. The Issue declares structured document decisions; older link-only sections remain routable.
2. A consumer's `.agent/project.json` is parsed and fully validated before profile-dependent output or hook execution.
3. Context resolution emits a compact, deterministic manifest. It never writes consumer-controlled files.
4. Contract, receipt, QA, and review payloads are validated locally before GitHub mutations. New contract input with a recognizable legacy Reviewer Checklist H2 is structurally normalized before its exact payload SHA is computed; item text/order and bytes outside the checklist remain unchanged, and ambiguous prose fails closed. Historical approved bytes remain readable and restorable unchanged. Final Verification requires a clean worktree and exact local/PR HEAD equality, then publishes only command identities and hashes. Self-review binds the named approved contract ID and verified SHA, derives exact-byte section identities, and keeps contract conformance separate from checklist review. QA remains a separate HEAD/contract-bound result. Independent review requires a fresh-context attestation and binds every contract unit and checklist item; the implementation session does not author it. Each immutable comment is read back by exact ID before its pointer is changed; a failed readback or changed state leaves orphan evidence.
5. For an authorized implementation, the sequence is `verify_quick`, commit, `ensure-review-pr` (safe push and deterministic PR establishment), `verify-final`, exact-HEAD self-review, QA, fresh-context independent review, and `delivery-check`. Pending Required Checks block completion after PR creation. Handoff reads fresh Issue, PR, evidence, and Required Check state; merged delivery remains a separate operation.
6. `build_dist.py` constructs each host package in memory from canonical source and adapter metadata, then writes a deterministic path set.

The structural Contract preflight is a separate local flow: the CLI reads the explicit source path, `contracts.py` reuses `_prepare_contract_input` and `_contract_h2_headings`, and bounded JSON reports the normalized payload identity. It neither writes a mirror nor contacts GitHub. The implementation Skill invokes it before saving or publishing new contracts created from the canonical template; legacy contract APIs and historical reads do not depend on it.

## Workspace execution flow

```text
approved Contract
 -> agent-context
 -> existing binding?
      yes -> reuse frozen base_ref/base_sha -> prepare-implementation reuse
      no  -> resolve-implementation-base -> exact base_ref/base_sha
               -> exact-base host capability
               -> isolated | current fallback | blocked
               -> prepare-implementation binding
 -> implementation
 -> canonical remote branch / PR
 -> evidence gates / independent review
```

Issue and PR remain the user-facing identities. One implementation writer owns an execution; corrections reuse the same host workspace and binding, including its frozen base ref/SHA. On a new execution, native isolation is eligible only when the host can start the workspace at the exact selected base SHA; `auto` otherwise falls back to the current checkout and `required` blocks before edits. The host owns worktree creation, resume, access control, and cleanup. The runtime never shells out to another coding-agent binary, creates raw automatic sibling worktrees, copies secrets, or routes work globally. Independent Review stays in a fresh context separate from the implementation execution.

Git cleanliness sees untracked content in the main checkout. Claude Code’s default `.claude/worktrees/` location is nested under that checkout, but host settings or `WorktreeCreate` hooks can place worktrees elsewhere. Project-owned ignore rules are therefore guidance and configuration, not runtime host-path inference or a universal preflight. This does not change host-owned worktree lifecycle, the execution registry or binding, or PR gates.

## Failure handling

Malformed profiles and Document impact declarations fail closed before hooks or scoped validation. Unknown selected components and invalid doc selectors never broaden scope. Host or target requirement mismatches skip commands and remain unverified. Self-review contract `fail`/`untested`, checklist `fail`, Final Verification other than PASS, QA other than PASS/N/A, independent contract units not all PASS, independent checklist `fail`, and blocking A/B/C findings block handoff. Independent D findings and checklist `untested` remain non-blocking by themselves. Legacy schema-v1 self-reviews remain diagnostic-only. GitHub ambiguity fails closed. Atomic local replacements preserve the old verified bytes on failure. Build/check mismatches identify drift without silently accepting edited generated output.

## Authorization boundary and PR handoff

The approved Issue contract is the authority for routine work through a review-ready PR. The implementation Skill retains ownership after local verification and invokes the delivery Skill for PR establishment and gates. A separate decision is reserved for material scope/architecture changes, contract supersession, ambiguous ownership/base, destructive Git operations, merge/release, permission escalation, unrelated GitHub mutation, or an explicit request to stop. A missing PR is an implementation blocker, not a reason to return a “next step.” Pending CI leaves the PR in place and reports blocked delivery.

## Alternatives considered

- Copying the reference repository or its 105 KiB CLI would introduce template ownership and a monolith. The new runtime uses focused modules and only carries forward specified behavior.
- Hand-authored host-specific Skill trees would drift. Adapters contain only explicit host differences.
- A database, MCP server, daemon, or hosted API would add a second authority and is outside the product boundary.
- A shared OpenAI/Antigravity `plugin.json` would violate their different schemas. Packages are separate directories.

## Verification strategy

Unit tests exercise module boundaries with injected Git/GitHub results. Package tests compare complete generated trees byte-for-byte, validate each host independently, and prove that modifying a generated file is detected by `--check`. The CI trust boundary is specified in the [Distribution specification](../specs/distribution-spec.md).
