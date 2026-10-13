<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Design

- Status: Approved
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related specification: [Portable Workflow Specification](../specs/workflow-spec.md)

<!-- contents:start -->
**Contents**
- [1 Context and goals](#1-context-and-goals)
- [2 Requirements traceability](#2-requirements-traceability)
- [3 DES-WF-001 Architecture](#3-des-wf-001-architecture)
- [4 DES-WF-002 Data flow and ownership](#4-des-wf-002-data-flow-and-ownership)
- [5 DES-WF-003 Workspace execution flow](#5-des-wf-003-workspace-execution-flow)
- [6 DES-WF-004 Failure handling](#6-des-wf-004-failure-handling)
- [7 DES-WF-005 Authorization boundary and PR handoff](#7-des-wf-005-authorization-boundary-and-pr-handoff)
- [8 Alternatives considered](#8-alternatives-considered)
- [9 Migration gate routing](#9-migration-gate-routing)
- [10 DES-WF-006 Human review and final delivery](#10-des-wf-006-human-review-and-final-delivery)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [DES-WF-001](#des-wf-001) — 3 DES-WF-001 Architecture
- [DES-WF-002](#des-wf-002) — 4 DES-WF-002 Data flow and ownership
- [DES-WF-003](#des-wf-003) — 5 DES-WF-003 Workspace execution flow
- [DES-WF-004](#des-wf-004) — 6 DES-WF-004 Failure handling
- [DES-WF-005](#des-wf-005) — 7 DES-WF-005 Authorization boundary and PR handoff
- [DES-WF-006](#des-wf-006) — 10 DES-WF-006 Human review and final delivery
<!-- heading-map:end -->


<a id="context-and-goals"></a>
## 1 Context and goals

The workflow must feel consistent in three agent hosts while respecting each host's plugin format. The source remains repository-owned Markdown, standards, and a standard-library Python CLI. Host packages are deterministic projections of that source, not separate authoring trees.

Goals are explicit Issue authority, progressive context loading, reliable local verification, exact-byte records, independent review evidence, and reproducible delivery gates. The current product exposes 16 Skills and the `python -m p_ases` namespace CLI; no remote service or persistent runtime process is introduced.

Legacy design note: detailed procedures below that still mention the former flat CLI or ten-Skill execution sequence are historical Agent Workflow behavior. The current interface and Skill inventory are defined by `python -m p_ases --help`, the README, and `workflow/skills/`.

<a id="requirements-traceability"></a>
## 2 Requirements traceability

| Requirement | Design consequence |
|---|---|
| One semantic owner per rule | Workflow phase policy lives in this specification; CLI data and failure semantics live in the [Runtime specification](../specs/runtime-spec.md). |
| Sixteen host-portable Skills | The exact canonical inventory lives under `workflow/skills/`; the distribution builder copies it unchanged. |
| Compact context routing | The runtime emits validated paths and identifiers rather than document contents. |
| Review is evidence, not approval | Self-review and independent-review records bind claims to contract units, checklist, and exact PR HEAD; runtime validates the fresh-context attestation but cannot prove provenance. |
| Self-review covers the complete approved contract | A schema-v2 contract-conformance layer records evidence for deterministic H2 units; safely normalized new Reviewer Checklist H2 may be excluded, while legacy/non-canonical historical checklist H2 remains covered as a unit. The Reviewer Checklist remains a separate concise summary. |
| Durable documents agree in the final result | The Issue carries Specification, Design, and Status decisions; implementation checks them against the final diff, and self-review verifies alignment. Artifact creation/edit order is not an acceptance condition. |
| Four evidence gates precede Required Checks | The delivery gate checks Final Verification, self-review, QA, and Independent Review in order before Required Checks for the same current HEAD. |
| Host-specific packages differ | The builder emits three isolated packages from shared sources and adapters. |
| Work context is reproducible | `work base`, `work branch`, `work bind`, and `work recover` freeze and verify the exact Issue execution identity. |
| Approved Contract execution has a stable workspace | The Contract execution Skill asks the host to reuse/create its native isolated workspace according to policy, then writes a local Issue execution binding before edits; host lifecycle stays outside the runtime. |
| Execution authorization continues to the review PR | An approved Issue contract covers routine Issue-scoped commit/push/PR/review-phase/self-review/check operations; Skills do not add a PR-specific prompt. |
| Implementation owns end-to-end handoff | The implementation flow continues through a review-ready PR, exact-HEAD self-review, and delivery gate before reporting completion. |
| New Contract layout is checked without changing legacy publication | A separate read-only preflight validates the canonical template's physical H2 structure before new-template contracts are saved or published; the historical comment and mirror path remains unchanged. |
| Chat project instructions work across hosts | One Japanese project-instructions body uses one repository URL substitution and describes only capabilities available to the active chat; it does not depend on installing this workflow plugin. |

<a id="des-wf-001"></a>
<a id="des-wf-001-architecture-and-phase-authority"></a>
## 3 DES-WF-001 Architecture

```text
workflow/ ─────┐
runtime/ ──────┼──> tools/build_dist.py ──> dist/openai|claude|antigravity
adapters/ ─────┘             │
                             └──> tools/validate_dist.py

consumer Issue + .agent/project.json
                 │
                 v
          P-ASES CLI (python -m p_ases)
          ├── project status / context show (read-only)
          ├── ADC / Issue / work / PR routes
          ├── verification / acceptance / audit / review
          ├── delivery and parent integration
          └── authenticated GitHub API boundary
```

`workflow/`, `runtime/`, and `adapters/` are canonical hand-authored trees. `dist/**` is generated and MUST NOT be hand-edited. The CLI is a one-shot Python 3.10+ application using the standard library. GitHub transport is isolated in one module. Git lifecycle commands are isolated in `git.py`; they use subprocess argv, never shell interpolation. Tests replace those boundaries with fakes and do not use network credentials.

The ordinary single/child phase path is `requirements -> [specification] -> [design] -> ready -> execution -> verification -> user-review -> closed`. Parent Issues keep `requirements -> ready -> execution -> integration -> user-review -> closed`. The only optional-phase edges are the two single skips and the combined skip from requirements to ready; each skip has an independent ADC-backed reason. `closed` remains an internal terminal state and is never a repository label. Fixed parent #26 and Bootstrap #27–#32 bypass the new ordinary evidence gate.

<a id="des-wf-002"></a>
<a id="des-wf-002-data-flow-and-artifact-ownership"></a>
## 4 DES-WF-002 Data flow and ownership

1. A Skill starts from an Issue and reads only the routing data and documents relevant to that task. The Issue declares structured document decisions; older link-only sections remain routable.
2. A consumer's `.agent/project.json` is parsed and fully validated before profile-dependent output or hook execution.
3. Context resolution emits a compact, deterministic manifest. It never writes consumer-controlled files.
4. Contract, receipt, QA, and review payloads are validated locally before GitHub mutations. New contract input with a recognizable legacy Reviewer Checklist H2 is structurally normalized before its exact payload SHA is computed; item text/order and bytes outside the checklist remain unchanged, and ambiguous prose fails closed. Historical approved bytes remain readable and restorable unchanged. Final Verification requires a clean worktree and exact local/PR HEAD equality, then publishes only command identities and hashes. Self-review binds the named approved contract ID and verified SHA, derives exact-byte section identities, and keeps contract conformance separate from checklist review. QA remains a separate HEAD/contract-bound result. Independent review requires a fresh-context attestation and binds every contract unit and checklist item; the implementation session does not author it. Each immutable comment is read back by exact ID before its pointer is changed; a failed readback or changed state leaves orphan evidence.
5. Current work routes through ADC and Issue validation, exact-base work binding, PR establishment, subject-bound Verification and Acceptance evidence, separate Audit and User Review, and the delivery gate. Each mutation is followed by exact readback; any new subject commit invalidates evidence bound to the previous HEAD.
6. `build_dist.py` constructs each host package in memory from canonical source and adapter metadata, then writes a deterministic path set.

`phase_evidence.py` owns the `PASES_PHASE_DECISION_V1` model, canonical JSON codec, document hashing, generation-scoped predecessor lookup, and two complete direct/list/direct identity snapshots. The record is a technical receipt derived from the current approved ADC, not a user approval. `ExecutionBinding` records the dedicated Issue branch and the `work` route appends an immutable binding generation when the approved ADC is explicitly superseded, retaining the original base, branch, worktree, and initial HEAD. Specification receipts inspect only specification artifacts; design receipts also verify the unchanged specification predecessor; ready receipts verify the completed predecessor chain and ready-stage documents. A changed prior artifact blocks dependent receipts. Ready resolves each `REQ`/`DES`/`ORA`/`TST` link to a canonical file in the same commit, checks the actual anchor, verifies the ADC path or explicit unchanged decision, and reads each executable test source from the commit tree. `github.py` reads and writes comments, Issues, labels, definitions, and branch refs; `git.py` supplies the local branch, HEAD, and ancestry checks. Every ordinary single/child phase transition verifies the actual kind, approved ADC, current Activation/Gate Selection, branch, and binding. `ready -> execution` rebuilds the ready decision on the current HEAD before any label write. Advance re-reads the Issue and evidence immediately before its label mutation and then reads the full Issue state back. Unchanged labels survive the transition. Existing child Issues are checked in place and never reset to requirements.

The kind labels share the P-ASES color `c5def5`: `kind:single` has description `P-ASES Issue kind: single`, `kind:child` has description `P-ASES Issue kind: child`, and the existing `kind:parent` definition remains migration-owned. `issue_graph.py` owns only the two child initialization definitions: `kind:child` (`c5def5`, `P-ASES Issue kind: child`) and `phase:requirements` (`0e8a16`, `Workflow phase: requirements`). It checks repository definitions before creating a child, creates missing definitions with exact readback, then creates the child with those labels and existing `enhancement`. Existing children must already have one `kind:child`, one valid phase, and at most one attention label. Fixed legacy Bootstrap children #27–#32 are read without automatic relabeling. A create response lost after GitHub writes is recovered only when one exact child marker can be read back.

The structural Contract preflight is a separate local flow: the CLI reads the explicit source path, `contracts.py` reuses `_prepare_contract_input` and `_contract_h2_headings`, and bounded JSON reports the normalized payload identity. It neither writes a mirror nor contacts GitHub. The implementation Skill invokes it before saving or publishing new contracts created from the canonical template; legacy contract APIs and historical reads do not depend on it.

<a id="des-wf-003"></a>
<a id="des-wf-003-workspace-execution-flow"></a>
## 5 DES-WF-003 Workspace execution flow

```text
approved Contract
 -> context show (read-only)
 -> existing valid binding?
      yes -> reuse frozen execution identity
      no  -> work base -> exact base_ref/base_sha
             -> work branch / bind
             -> existing continuation? work recover after exact readback
 -> implementation
 -> canonical remote branch / PR
 -> evidence gates / independent review
```

Issue and PR remain the user-facing identities. One implementation writer owns an execution; corrections reuse the same host workspace and binding, including its frozen base ref/SHA. On a new execution, native isolation is eligible only when the host can start the workspace at the exact selected base SHA; `auto` otherwise falls back to the current checkout and `required` blocks before edits. The host owns worktree creation, resume, access control, and cleanup. The runtime never shells out to another coding-agent binary, creates raw automatic sibling worktrees, copies secrets, or routes work globally. Independent Review stays in a fresh context separate from the implementation execution.

Git cleanliness sees untracked content in the main checkout. Claude Code’s default `.claude/worktrees/` location is nested under that checkout, but host settings or `WorktreeCreate` hooks can place worktrees elsewhere. Project-owned ignore rules are therefore guidance and configuration, not runtime host-path inference or a universal preflight. This does not change host-owned worktree lifecycle or PR gates. If a local binding is lost, a verified exact PR continuation can restore an Issue-scoped Schema 2 binding without changing branches or worktrees; normal new executions continue to resolve and bind the selected base.

<a id="des-wf-004"></a>
<a id="des-wf-004-failure-handling"></a>
## 6 DES-WF-004 Failure handling

Malformed profiles and Document impact declarations fail closed before hooks or scoped validation. Unknown selected components and invalid doc selectors never broaden scope. Host or target requirement mismatches skip commands and remain unverified. Self-review contract `fail`/`untested`, checklist `fail`, Final Verification other than PASS, QA other than PASS/N/A, independent contract units not all PASS, independent checklist `fail`, and blocking A/B/C findings block handoff. Independent D findings and checklist `untested` remain non-blocking by themselves. Legacy schema-v1 self-reviews remain diagnostic-only. GitHub ambiguity fails closed. Atomic local replacements preserve the old verified bytes on failure. Build/check mismatches identify drift without silently accepting edited generated output.

<a id="des-wf-005"></a>
<a id="des-wf-005-authorization-boundary-and-pr-handoff"></a>
## 7 DES-WF-005 Authorization boundary and PR handoff

The approved Issue contract is the authority for routine work through a review-ready PR. The implementation Skill retains ownership after local verification and invokes the delivery Skill for PR establishment and gates. A separate decision is reserved for material scope/architecture changes, contract supersession, ambiguous ownership/base, destructive Git operations, merge/release, permission escalation, unrelated GitHub mutation, or an explicit request to stop. A missing PR is an implementation blocker, not a reason to return a “next step.” Pending CI leaves the PR in place and reports blocked delivery.

<a id="alternatives-considered"></a>
## 8 Alternatives considered

- Copying the reference repository or its 105 KiB CLI would introduce template ownership and a monolith. The new runtime uses focused modules and only carries forward specified behavior.
- Hand-authored host-specific Skill trees would drift. Adapters contain only explicit host differences.
- A database, MCP server, daemon, or hosted API would add a second authority and is outside the product boundary.
- A shared OpenAI/Antigravity `plugin.json` would violate their different schemas. Packages are separate directories.

<a id="migration-gate-routing"></a>
## 9 Migration gate routing

`runtime/p_ases/gate_policy.py` owns a versioned gate decision alongside, not inside, `delivery.evaluate_readiness`. Only Issues #26–#32 in `puchinya/ai-agent-workflow` select `bootstrap-legacy-v1`; repository identity comparisons are case-insensitive and all other repositories fail closed. A `PASES_GATE_SELECTION_V1` Issue comment pins the selection. Other Issues require a unique, exact-readback `PASES_ACTIVATION_V1` plus an explicit earlier `PASES_ACTIVATION_APPROVAL_V1`; without them routing is `UNDETERMINED` and stops.

`delivery bootstrap-check` reads the current approved ADC and PR, runs the bounded local verification commands, and reads current-head Check Runs and the Actions workflow run through `github.py`. Review comments, review citations, and independent-context artifacts are not inputs to this fixed-cohort technical decision. A new result records `review_mode=WAIVED_BOOTSTRAP`; technical success is `BOOTSTRAP_TECHNICAL_READY`, with reviewer/context IDs null, review evidence empty, the separate-context flag false, and final-user-review eligibility false. The checkout is rechecked after local tests, after GitHub evidence collection, and immediately before publishing. The full PR identity and body, ADC pointer, and immutable gate selection are re-read before and after publication. If any field changes after a result is published, a newer `BOOTSTRAP_BLOCKED` observation is appended and read back as latest. Failed or stale technical inputs return machine-readable `BOOTSTRAP_BLOCKED`; normal P-ASES readiness, phase advancement, and review requirements remain unchanged. This policy does not grant PR merge permission or close an Issue.

When the Bootstrap evaluator lives on a downstream stacked PR, run its CLI from that evaluator checkout and pass `--root` pointing to a separate clean checkout of the earlier target PR's exact current HEAD. The evaluator fingerprint comes from the evaluator checkout while local checks and cleanliness checks run against the target checkout; do not copy evaluator code into the target branch. For legacy Issue-body ADC pointers, retain the original `## Agent Development Contract` block as the first journal record's predecessor anchor (or record `none` when absent); do not edit or delete the old anchor during migration.

The activation reader validates the fixed six-child set, each merged PR and closed Issue, a separate integration-evidence record covering docs/tests/16 Skills/distribution, and a distinct immutable approval comment. The activation record binds those PR merge SHAs and the integration digest. Policy readers reject duplicates, stale subjects, mismatched byte/digest values, forks, and non-current PR heads. No activation record is issued during child implementation.

<a id="des-wf-006"></a>
## 10 DES-WF-006 Human review and final delivery

`user_review.py` owns the subject-bound human decision, immutable session start, and feedback snapshots. A child session binds the current ADC, PR HEAD, plan, and Readiness digest; older approvals and change requests cannot satisfy it. Ordinary comments are questions. The only comment-driven execution transition is the whole-body `P-ASES-DECISION: CHANGES_REQUESTED` / `P-ASES-HEAD: <sha40>` pair from the authenticated human; inline comments must name their GitHub `commit_id`. `github.py` is the only network boundary and paginates the four REST feedback surfaces plus GraphQL review-thread state. A previously stored snapshot is compared with every complete new read; missing records are retained as deletion tombstones. Review history treats only `<64 lowercase hex>.json` as a feedback snapshot; `session.json` and canonical `*.result.json` records are separate schemas, and unexpected filenames or a content/name digest mismatch fail closed. Review evaluation derives decisions from the authenticated GitHub user or a verified host adapter, never from CLI-supplied identity fields.

`integration.py` owns the fixed parent child set, native dependency DAG, merged PR/Issue readback, main ancestry, and typed Integration Verification/Acceptance evidence. The authority decision for this migration is exact-main GitHub Actions run, job, step, and Check Run API data; the #26 comment is only a discoverable pointer/cache and cannot prove execution on its own. This resolves Git's self-reference conflict by keeping proof outside the named commit, while deletion or edit fails closed. `delivery parent-evidence <issue> <kind> <run-id>` reconstructs evidence from those API records. Verification requires the latest exact-main `ci.yml` push run, all four configured matrix jobs, App ID 15368, and successful compile, committed/generated distribution checks, unit tests, documentation validation, distribution build/validation, generated-path stability, and committed-diff whitespace steps. Acceptance requires the latest exact-main `parent-integration.yml` workflow_dispatch run and successful specification/design/test-oracle traceability, exact 16-Skill package, generated-distribution consistency, and distribution validation. Each referenced job Check Run URL must name the same repository and resolve to that App's completed/success Check Run on the exact SHA. The reader rejects caller-supplied PASS JSON even when all supplied artifact hashes match; it re-fetches and reconstructs the exact V2 payload on every read. Since parent #26 predates ADC pointer journals, the CLI obtains its pinned ADC digest and source declaration from the approved child #31 ADC, verifies the pinned migration-contract source, and double-reads the child ADC pointer plus parent Issue body. The Issue evidence comment remains editable/deletable GitHub storage: exact comment ID/body/actor/repository/subject are double-read, detected mutation blocks, and no intrinsic immutability is claimed. The dedicated parent-label migration remains read-only by default and mutates labels only under explicit `--apply`; parent delivery never applies it implicitly. After Integration PASS, parent User Review binds the ADC, six child merge pairs, and Integration result digest; approval never activates, closes, or merges the parent.

The CLI performs phase transitions only after re-reading the Issue and confirming its current labels. An in-scope request returns the same Issue to execution; an explicitly triaged new scope returns it to requirements. Finalize is a readback command and has no merge or close mutation. Parent final delivery remains blocked until child Integration and the separate parent review/activation gates are satisfied.
