<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Runtime and CLI Specification

- Status: Approved
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related design: [Runtime design](../design/runtime-design.md)
- Workflow invariants: [Portable Workflow Specification](workflow-spec.md)

<!-- contents:start -->
**Contents**
- [1 Purpose](#1-purpose)
- [2 Scope](#2-scope)
- [3 Normative requirements](#3-normative-requirements)
  - [3.1 REQ-RT-001 Project profile and context](#31-req-rt-001-project-profile-and-context)
  - [3.2 REQ-RT-002 Document validation](#32-req-rt-002-document-validation)
  - [3.3 REQ-RT-003 Feature branch bases](#33-req-rt-003-feature-branch-bases)
  - [3.4 REQ-RT-004 Implementation base resolution](#34-req-rt-004-implementation-base-resolution)
  - [3.5 REQ-RT-005 Implementation execution workspaces](#35-req-rt-005-implementation-execution-workspaces)
  - [3.6 REQ-RT-006 Review PR establishment](#36-req-rt-006-review-pr-establishment)
  - [3.7 REQ-RT-007 Implementation Contract bytes and storage](#37-req-rt-007-implementation-contract-bytes-and-storage)
  - [3.8 REQ-RT-008 Self-review and delivery](#38-req-rt-008-self-review-and-delivery)
  - [3.9 REQ-RT-009 Failure, logging, and cleanup](#39-req-rt-009-failure-logging-and-cleanup)
- [4 REQ-RT-010 Observable behavior](#4-req-rt-010-observable-behavior)
- [5 REQ-RT-011 Data and API formats](#5-req-rt-011-data-and-api-formats)
- [6 REQ-RT-012 Security and privacy](#6-req-rt-012-security-and-privacy)
- [7 REQ-RT-013 Error and boundary behavior](#7-req-rt-013-error-and-boundary-behavior)
- [8 P-ASES Bootstrap commands](#8-p-ases-bootstrap-commands)
- [9 Consumer Activation runtime contract](#9-consumer-activation-runtime-contract)
  - [9.1 REQ-F01-002 Activation locator](#91-req-f01-002-activation-locator)
  - [9.2 REQ-F01-004 Setup request and verification](#92-req-f01-004-setup-request-and-verification)
  - [9.3 REQ-F01-006 Historical Activation pin](#93-req-f01-006-historical-activation-pin)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [REQ-RT-001](#req-rt-001) — 3.1 REQ-RT-001 Project profile and context
- [REQ-RT-002](#req-rt-002) — 3.2 REQ-RT-002 Document validation
- [REQ-RT-003](#req-rt-003) — 3.3 REQ-RT-003 Feature branch bases
- [REQ-RT-004](#req-rt-004) — 3.4 REQ-RT-004 Implementation base resolution
- [REQ-RT-005](#req-rt-005) — 3.5 REQ-RT-005 Implementation execution workspaces
- [REQ-RT-006](#req-rt-006) — 3.6 REQ-RT-006 Review PR establishment
- [REQ-RT-007](#req-rt-007) — 3.7 REQ-RT-007 Implementation Contract bytes and storage
- [REQ-RT-008](#req-rt-008) — 3.8 REQ-RT-008 Self-review and delivery
- [REQ-RT-009](#req-rt-009) — 3.9 REQ-RT-009 Failure, logging, and cleanup
- [REQ-RT-010](#req-rt-010) — 4 REQ-RT-010 Observable behavior
- [REQ-RT-011](#req-rt-011) — 5 REQ-RT-011 Data and API formats
- [REQ-RT-012](#req-rt-012) — 6 REQ-RT-012 Security and privacy
- [REQ-RT-013](#req-rt-013) — 7 REQ-RT-013 Error and boundary behavior
- [REQ-F01-002](#req-f01-002) — 9.1 REQ-F01-002 Activation locator
- [REQ-F01-004](#req-f01-004) — 9.2 REQ-F01-004 Setup request and verification
- [REQ-F01-006](#req-f01-006) — 9.3 REQ-F01-006 Historical Activation pin
<!-- heading-map:end -->


<a id="purpose"></a>
## 1 Purpose

Define observable behavior for the Python 3.10+ P-ASES runtime, invoked as `python -m p_ases <namespace> <verb>`. It is synchronous and one-shot. GitHub I/O uses authenticated `gh api` through the runtime's GitHub boundary with argument arrays and structured JSON.

<a id="scope"></a>
## 2 Scope

The public CLI namespaces are `project`, `context`, `adc`, `issue`, `docs`, `work`, `pr`, `verification`, `acceptance`, `audit`, `user-review`, and `delivery`. Their verbs are defined by `python -m p_ases --help` and the canonical Skills. The route set includes `project status`, `context show`, ADC validate/publish/verify/restore, Issue validate-split/split/advance/integration-check, docs validate/format, work base/branch/bind/recover, PR ensure, verification plan/collect/validate/final/published, acceptance prepare/validate/publish/verify, audit self/independent, user-review start/sync/record/status, and delivery readiness/final/finalize/parent/gate-policy/bootstrap-check/parent-evidence/parent-migrate-labels.

The detailed command semantics retained in Sections 3.3–7 below are the explicitly legacy `agent-workflow` runtime specification. They preserve historical requirement identifiers for traceability; their retired command names, profile schema, and data contracts do not define the current P-ASES interface.

The commands `update-template` and `refresh-template-manifest` are forbidden. No module other than `github.py` may invoke `gh` directly. Every GitHub mutation uses JSON input files or structured fields, never shell interpolation of user payloads.

GitHub comment, review, check-run, and commit-status collections MUST paginate with explicit `page=N&per_page=100` GET requests until a selected page contains fewer than 100 items. The transport preserves API order and fails with `GitHubError` on malformed page shapes. Direct named-comment verification remains a single-ID fetch. Git lifecycle subprocesses are owned only by the `git` boundary, use argv arrays, and never pass through the trusted shell-hook boundary.

<a id="normative-requirements"></a>
## 3 Normative requirements

<a id="req-rt-001"></a>
<a id="req-rt-001-project-profile-and-context"></a>
### 3.1 REQ-RT-001 Project profile and context

`project status [--root PATH]` performs read-only profile validation. It reports a bounded `READY` or `UNAVAILABLE` result and never creates or repairs profile files.

`context show ISSUE [--root PATH] [--repo OWNER/NAME]` reads the current same-repository Issue, exact current ADC pointer and named comment, and any existing local execution binding. It reports current Issue/ADC/binding state without resolving a base, creating or updating a binding, switching branches, creating worktrees, changing labels, or mutating GitHub. Missing, closed, unapproved, stale, malformed, and unbound states are explicit bounded results. A valid binding is summarized only by identity, digest, base/HEAD, branch, mode, and current state; local workspace paths and arbitrary environment data are not exposed.

<a id="req-rt-002"></a>
<a id="req-rt-002-document-validation"></a>
### 3.2 REQ-RT-002 Document validation

`docs validate [--root PATH]` validates canonical documentation structure, internal links, stable requirement/decision identifiers, and cross-document traceability. `docs format (--write|--check) [--root PATH]` deterministically numbers headings and refreshes generated contents maps; check mode reports drift without writing. Neither route fetches external links or performs semantic document migration.

<a id="req-rt-003"></a>
<a id="req-rt-003-feature-branch-bases"></a>
### 3.3 REQ-RT-003 Feature branch bases

`start-feature-branch N <description...> [--base-ref BRANCH] [--expected-base-sha SHA40]` uses the GitHub default branch when `--base-ref` is omitted. An explicit base must name an existing same-repository remote branch; a SHA cannot be supplied as the base branch. The runtime fetches and resolves `origin/<base-ref>`, then checks `--expected-base-sha` before any branch switch, cleanup, or hook. A new target branch starts directly at that fetched base. Existing current, local, and remote targets remain idempotent and are never rebased. Results include `base_ref`, `base_sha`, `stacked`, and `creation_source` (`current`, `local`, `remote`, or `new`). A base SHA mismatch leaves the current branch and worktree unchanged.

<a id="req-rt-004"></a>
<a id="req-rt-004-implementation-base-resolution"></a>
### 3.4 REQ-RT-004 Implementation base resolution

`resolve-implementation-base ISSUE [--base-ref BRANCH] [--expected-base-sha SHA40] [--repo PATH]` resolves the exact base identity for a new Implementation Contract execution before host capability selection. It is owned by `execution.py` for orchestration, calls the approved-contract and profile validation boundaries, and delegates remote-ref validation/fetch only to `git.py`'s `fetch_base_ref`. It requires a positive Issue number, Schema 2 profile, origin fetch repository matching the configured GitHub repository, an open same-repository non-PR Issue, the current approved Contract pointer and exact named comment bytes, a valid GitHub default branch, and a valid selected same-origin branch. Omitted `--base-ref` selects the GitHub default branch; an explicit value selects that branch. The resolver returns only Issue/repository identity, Contract comment ID/SHA, default/base refs, exact 40-character base SHA, and `stacked` (true exactly when base ref differs from default).

The successful JSON result has exactly this identity-only shape:

~~~json
{
  "issue": 20,
  "repository": "owner/repo",
  "contract_comment_id": 123,
  "contract_sha256": "<64 lowercase hex>",
  "default_base_ref": "main",
  "base_ref": "feature/100-base",
  "base_sha": "<40 lowercase hex>",
  "stacked": true
}
~~~

It does not require a clean worktree. Its only Git side effect is fetching the selected origin branch; it never switches or creates branches/worktrees, runs hooks, writes execution state, edits source, or mutates GitHub.

When supplied, `--expected-base-sha` must be exactly 40 lowercase hexadecimal characters and equal the fetched selected-base SHA. A syntax or value mismatch fails closed before host isolation or any branch/worktree/binding/hook/GitHub mutation. This expected-SHA check is used by later setup commands to detect remote advancement between resolution and binding; callers must restart resolution deliberately rather than silently adopt a newer tip. A valid existing binding skips this command and reuses its frozen base ref/SHA.

<a id="req-rt-005"></a>
<a id="req-rt-005-implementation-execution-workspaces"></a>
### 3.5 REQ-RT-005 Implementation execution workspaces

`WorkspaceIdentity` is read from Git metadata: the absolute worktree root, per-worktree git directory, common git directory, whether the checkout is linked, full HEAD SHA, and attached branch or null for detached HEAD. The runtime does not infer isolation from path names or scan sibling directories.

`prepare-implementation ISSUE [--base-ref BRANCH] [--expected-base-sha SHA40] --mode isolated|current [--supersede]` binds an execution after the host has selected the workspace and before source edits. It validates an open same-repository non-PR Issue, the byte-verified approved Contract pointer, Schema 2 profile, clean worktree, same-repository remote base, and local HEAD equal to the resolved base SHA. An expected SHA must match exactly. Isolated mode requires a linked worktree; current mode requires the attached configured Issue branch. Canonical branch names use the configured prefix and slug rules and are frozen in the binding.

`recover-implementation-binding ISSUE PR --base-ref BRANCH --expected-base-sha SHA40 [--repo PATH]` is only for a clean current checkout that already is the exact continuation head of an open same-repository PR for the Issue, when its local binding was lost. It requires positive Issue/PR numbers, a Schema 2 profile whose isolation policy is not `required`, matching origin/configured repository, the open non-PR Issue and exact approved Contract, the canonical Issue branch, an open non-draft unmerged same-repository PR with a standalone `Closes #ISSUE` line, local branch/HEAD equal to the PR head, PR base ref/SHA equal to the supplied ref/SHA, the fetched same-origin base equal to that SHA, and the base commit to be an ancestor of current HEAD. It rechecks PR, base, Contract, Issue title, and workspace identity immediately before writing. Existing bindings, dirty worktrees, malformed authority, mismatches, or races fail without binding creation. The only Git side effect is fetching the selected base; no branch/worktree, hook, source, Issue, PR, push, merge, rebase, reset, or host-launch operation occurs.

On success it atomically creates a Schema 2 current-mode binding with the Schema 1 fields plus exactly `recovery: {kind, pr, head_sha}` where `kind` is `verified-open-pr-continuation` and `head_sha` is the exact recovered PR head. `base_ref`/`base_sha` remain frozen and `initial_head` is the base SHA; the recovery object explicitly records that this is a verified continuation checkpoint, not proof the missing local file was previously present. Schema 1 records and normal `prepare-implementation` creation remain unchanged. Schema 2 reuse requires the canonical branch and that the recovered head remains an ancestor of current HEAD. Run `prepare-implementation --mode current --base-ref BRANCH --expected-base-sha SHA40 --supersede` after recovery to validate the current approved Contract. New executions still use `resolve-implementation-base`.

The successful command returns exactly this bounded identity shape; the local workspace path and GitHub response bodies are excluded:

~~~json
{
  "issue": 24,
  "repository": "owner/repo",
  "contract_comment_id": 123,
  "contract_sha256": "<64 lowercase hex>",
  "pr": 25,
  "canonical_branch": "feature/24-example",
  "mode": "current",
  "base_ref": "main",
  "base_sha": "<40 lowercase hex>",
  "initial_head": "<40 lowercase hex>",
  "recovered_head": "<40 lowercase hex>",
  "recovered": true
}
~~~

The ignored local binding is `.agent-state/issues/N/execution.json`. A normal binding is Schema 1 with exactly `schema_version`, `issue`, `repository`, `contract_comment_id`, `contract_sha256`, `workspace_root`, `mode`, `base_ref`, `base_sha`, `initial_head`, and `canonical_branch`. A recovered continuation is Schema 2 with those fields plus exactly `recovery: {kind, pr, head_sha}` as defined above. Both forms are atomically written, never published, and are not evidence of host or session provenance. Reuse requires the same Issue, repository, workspace root, mode, and current approved Contract; a recovered binding also requires the same canonical branch and recovered checkpoint to remain an ancestor of HEAD. Bindings remain valid after descendant commits without resetting HEAD or re-resolving the frozen base. A changed Contract is stale until explicit `--supersede`; supersession updates only the Contract comment ID and SHA.

For an isolated binding, the local branch may be host-owned or HEAD may be detached. The runtime never renames or switches that branch. `ensure-review-pr` uses the binding's `base_ref` as the PR base for both isolated and current bindings. A supplied `--base-ref` must match that frozen ref or the command fails before push, PR mutation, or label mutation. Without a binding, explicit/default base selection remains unchanged. For a bound execution, `base_sha` remains the frozen initial base commit: HEAD must contain it at handoff, while the selected remote base may have advanced. The fetched selected remote base must also be an ancestor of HEAD under the existing publication checks; no automatic rebase or merge is performed. `ensure-review-pr` supplies the frozen canonical branch for isolated publication, and `git.py` pushes `HEAD` non-force to that branch. It retains clean-worktree, same-origin, selected-base ancestry, ahead-of-base, non-force, and remote-HEAD readback checks. A divergent remote branch fails without rebase or overwrite. Current-mode and unbound publication retain the existing attached configured-feature-branch check exactly.

`context show N` summarizes a valid binding only by repository/Issue identity, ADC comment ID and digest, base ref/SHA, worktree mode, initial HEAD, canonical branch, and current/stale state; it never exposes the workspace path or arbitrary environment data.

<a id="req-rt-006"></a>
<a id="req-rt-006-review-pr-establishment"></a>
### 3.6 REQ-RT-006 Review PR establishment

`ensure-review-pr N --body-file PATH [--title TITLE] [--base-ref BRANCH]` pushes the current Issue feature branch safely, creates or reuses exactly one open same-repository review PR, verifies its identity, replaces phase labels so only `phase:review` remains among them, and reads the final state back. It establishes the PR required by self-review; it does not prepare or publish self-review itself. Success JSON contains `issue`, `pr`, `pr_url`, `head_sha`, `head_branch`, `base_branch`, `created`, `reused`, `push`, and `phase_transition`. A post-create phase failure returns a failed result with PR identity so a retry can reuse it.

The command requires a readable UTF-8 body file. Before any push or PR/Issue mutation, validate a standalone logical line `Closes #N` for the owning Issue, a non-empty `## Verification` section, and a non-empty `## Untested` section. The command never invents claims. Resolve repository, open same-repository non-PR Issue, repository default branch, selected base, current branch, and HEAD. Load the execution binding before selecting the publication base. A binding's `base_ref` is authoritative in current and isolated modes; a differing explicit `--base-ref` fails before push or any PR/label mutation. Without a binding, if base is omitted use the default branch; otherwise retain the explicit base. An approved stacked branch passes the exact `base_ref` from `start-feature-branch`; never infer a different base.

Before push, require a clean worktree, the current configured Issue feature branch (or the frozen canonical publication branch in isolated mode), exactly one origin fetch URL and push URL both resolving to the same repository, no origin mirror-push configuration, and a publication target different from both the repository default branch and selected PR base in both modes. Also require a valid same-repository remote base and at least one commit ahead of that base with the base contained in the current branch history. For a binding, require the frozen `base_sha` to be an ancestor of HEAD; do not require the remote base tip to equal it, since that branch may advance after implementation starts. GitHub reads may establish identity and default/base metadata, but all local preconditions must pass before network mutation. Push only HEAD to the selected target branch with argv-based Git, no force option, and no automatic tag following, then verify the remote branch SHA equals local HEAD. Push failure or mismatch prevents PR and phase mutation.

After verified push, query open PRs on the exact base and filter the exact head branch, including fork heads so cross-repository matches fail closed. Create one non-draft PR when none matches. Reuse exactly one matching same-repository PR; update its title/body only when the body has no conflicting `Closes #N` and the requested payload differs. Fail closed for multiple matches, any conflicting Issue closure, draft PRs, missing/cross-repository head identity, or invalid PR identity/state. Do not create duplicates, rewrite a conflicting PR, or convert a draft. Verify head repository/ref/SHA, base repository/ref, open state, non-draft status, and Issue association after create/reuse. A repeated call reuses the same PR; a later HEAD may update the same branch/PR.

Only after a compatible PR exists, read the latest Issue labels, preserve every non-`phase:*` label, replace all phase labels with exactly `phase:review` in one `github.py` label-replacement call, and read back Issue and PR state. A failed transition reports the PR number and URL; retry reuses that PR. Successful repeated calls are idempotent. Pending Required Checks do not prevent PR creation. Existing exact-HEAD self-review and delivery gates remain unchanged; a new HEAD stales the old review and requires republishing.

| Condition | Required behavior |
|---|---|
| Missing/invalid body file, absent `Closes #N`, empty Verification/Untested | Fail before push, PR mutation, or label mutation. |
| Dirty worktree, default-branch execution, invalid Issue branch/origin/base, or no commit ahead | Fail before push and all GitHub mutation. |
| Push failure or remote HEAD mismatch | Fail before PR create/update and phase transition. |
| Multiple exact matches, conflicting Issue PR, draft PR, or fork/cross-repository head | Fail closed without PR update/create or label mutation. |
| PR created/reused but label replacement or readback fails | Return failure with PR identity; a retry reuses the same PR. |
| Required Checks pending after PR creation | PR establishment succeeds; overall delivery stays blocked. |

<a id="req-rt-007"></a>
<a id="req-rt-007-implementation-contract-bytes-and-storage"></a>
### 3.7 REQ-RT-007 Implementation Contract bytes and storage

The complete contract is one top-level comment on its owning Issue. The Issue body `## Implementation Contract` section contains only `Comment ID: <integer>`, `SHA-256: <64 lowercase hex>`, and `State: approved`. The comment first line is `<!-- agent-contract:v1 issue=N sha256=HEX bytes=DECIMAL -->`, followed by one blank line and the exact normalized UTF-8 payload bytes.

ADC requirement bullets preserve stable `REQ-N` and area-scoped `REQ-AREA-NNN` identifiers (for example, `REQ-WF-001`) for downstream specification/design/test traceability. Phase evidence does not infer a requirement or rewrite its identifier; before `ready`, every exact ADC requirement identifier must resolve through the canonical test/Oracle traceability matrix.

Input payloads are non-empty, valid UTF-8, NUL-free, free of obvious credential material, and at most 65,536 raw bytes. Before saving or publishing, the runtime recognizes a single `Reviewer Checklist` H2 and converts safe legacy formatting into the canonical block. It preserves every checkbox item's exact text and order and all bytes outside that H2. It inserts the required markers and approved introduction, and recognizes `Implementer MUST self-review every item.` as a legacy form of that introduction. Duplicate/ambiguous headings, malformed items, missing items, or other prose in that H2 fail before GitHub mutation; the runtime never drops prose or invents checklist items. Normalization is deterministic and idempotent. The rendered comment including header is at most 65,536 characters and is rejected locally before a remote mutation if too large. Hashes and byte counts cover the normalized payload, which is the exact content stored in the mirror and published comment. Historical comments are read and restored byte-for-byte without normalization.

`save-implementation-contract N [path]` and `publish-implementation-contract N [--source PATH] [--supersede]` canonicalize safe Reviewer Checklist formatting before hashing or mirroring. Save reports whether normalization occurred. Publish validates Issue identity, reuses an identical pending/current comment, verifies the comment by ID and readback, and updates only the pointer section after an immediate body read; it reads the resulting body back. Same Issue/SHA is idempotent. A changed approved SHA requires explicit `--supersede` and leaves the old comment intact. API uncertainty never changes a verified local mirror.

`restore-implementation-contract N [--replace-stale]` reads only the recorded comment by ID. It validates ownership, Issue association, size, SHA, and exact bytes before writing. A differing mirror fails unless replacement is explicit; replacement first saves a SHA-specific backup then uses temp-file plus atomic replace. An update failure leaves local verified state unchanged.

`verify-implementation-contract N` validates the local record, current pointer, and named source comment without listing unrelated comments.

`validate-implementation-contract-structure N PATH [--repo PATH]` is a separate, read-only preflight for new contracts authored from the canonical template. It reads only the explicit input path, using the same current-working-directory resolution for relative paths as contract source paths. The path must name an existing regular file. The command does not inspect or mutate Issue/PR state, write a mirror, invoke Git or `gh`, or contact a network.

The pure `validate_contract_structure(data: bytes, issue: int)` validator first calls `_prepare_contract_input`, thereby reusing the established payload bounds, UTF-8/NUL/credential checks, and safe in-memory Reviewer Checklist normalization. It then reuses `_contract_h2_headings` to inspect physical H2 headings while ignoring headings inside fenced code. It requires exactly once and in order these titles: `1. Repository Baseline`, `2. Architecture Decisions`, `3. Exact Change Set`, `4. Implementation Outcomes`, `5. Required Runtime Semantics`, `6. Non-goals / Forbidden Changes`, `7. Concrete Tests`, `8. Verification`, `9. Reviewer Checklist`, and `10. Completion Report`. Each required section must contain non-whitespace text before the next physical H2; the strict canonical checklist block counts as content. Duplicate, missing, out-of-order, malformed-numbered reserved-name, or empty required sections fail with a bounded section-specific error. Other nonreserved H2 headings are allowed and remain full-contract review units; H3 subdivisions are allowed. This structural H2 order is document format only; it does not impose an authoring or implementation timeline.

The preflight rejects unresolved double-braced uppercase snake-case authoring tokens anywhere in the normalized payload, including fenced code, without printing token contents. It does not normalize headings, whitespace, or other content and performs no semantic/NLP obligation analysis. Success JSON contains `valid`, `issue`, `normalized`, `section_count`, `sha256`, and `bytes` for the normalized would-be-published payload. Errors use `ContractError`, exit nonzero, and do not expose contract text or credentials. Repeated identical inputs have deterministic results.

For preflight only, a Reviewer Checklist containing either canonical marker must contain exactly one ordered begin/end pair. A marker-free legacy checkbox layout may still be safely normalized in memory. This distinction does not change the legacy save, publish, restore, or verify APIs.

This command is not a hard gate in save, publish, verify, restore, or supersession APIs. The requirements and implementation-contract Skills require this preflight before saving or publishing new contracts created from the canonical template. Historical approved comments and mirrors remain readable/restorable and are never rewritten or rehashed solely because they lack this section layout. Actual publication continues to bind the exact normalized bytes through the existing comment and pointer flow; a valid structure result does not approve architecture or assert full-contract review.

Pointer errors show this canonical block and prohibit appended prose:

```text
## Implementation Contract
Comment ID: <comment-id>
SHA-256: <sha256>
State: approved

Do not append prose to this block.
```

<a id="req-rt-008"></a>
<a id="req-rt-008-self-review-and-delivery"></a>
### 3.8 REQ-RT-008 Self-review and delivery

The effective Reviewer Checklist is the approved Contract's checklist items in source order as `C001...`, followed by Issue Reviewer Checklist items as `I001...`. A valid `AGENT_REVIEWER_CHECKLIST_V1` canonical block wins; otherwise only the narrow Markdown `Reviewer Checklist` H2 fallback matches. The Reviewer Checklist is a summary review surface, not a substitute for full-contract review.

Before saving or publishing a new contract, the runtime normalizes a recognizable legacy `Reviewer Checklist` H2 and then enforces the strict canonical block rule. This happens before any GitHub mutation. The normalizer performs only structural edits, preserves checklist item text/order and bytes outside the H2, and fails closed on ambiguous or unrelated prose. It is not a migration prerequisite for reading or restoring an already-approved contract: historical exact bytes remain readable and restorable without normalization or supersession. The structural classifier is shared by normalization, authoring validation, and review-unit derivation and distinguishes an absent, strict-canonical, or legacy/non-canonical Reviewer Checklist H2. It ignores headings inside fenced code and does not infer prose semantics.

Checklist extraction retains the existing canonical-block precedence and narrow-heading fallback for historical contracts. A strict-canonical Reviewer Checklist H2 is excluded from `contract_sections`, because new publication validation guarantees that it contains no unique normative prose. A legacy/non-canonical Reviewer Checklist H2 remains readable and its complete exact-byte section is included as a contract review unit, even when its checklist items also appear in the checklist review layer. Thus historical prose cannot disappear from conformance coverage.

Contract review units are derived from the exact approved payload returned by the named contract parser, not from the Issue summary. Ignore H2 headings inside fenced code and preserve source order. Add preamble unit `P000` titled `Contract Preamble` only when non-whitespace bytes precede the first H2. Every non-checklist H2 gets `S001...`, including task-specific H2 sections. A Reviewer Checklist H2 is excluded only when the shared structural classifier identifies it as strict-canonical; otherwise the whole H2 is included as a contract review unit. Do not hard-code standard section names or infer sentence-level obligations. `section_sha256` covers the exact original UTF-8 bytes of the unit, including its heading and line endings. Review records and comments include IDs, titles, hashes, results, and evidence, never contract section bodies.

New drafts and published reviews use schema version 2 and contain:

~~~json
{
  "schema_version": 2,
  "issue": 123,
  "pr": 456,
  "head": "<current-pr-head>",
  "contract_comment_id": 789,
  "contract_sha256": "<approved-contract-sha256>",
  "checklist_sha256": "<effective-checklist-sha256>",
  "contract_sections": [],
  "items": []
}
~~~

`contract_comment_id` identifies the named approved contract comment actually reviewed. `contract_sha256` reuses the exact SHA already verified through the canonical Issue pointer/comment. Each contract section has `id`, `title`, `section_sha256`, `result`, and non-empty concrete `evidence`; results are `pass`, `fail`, or `untested`. Contract `untested` evidence names the concrete unavailable verification or residual uncertainty; both `fail` and `untested` are valid publishable evidence that blocks delivery. Missing, pending, malformed, duplicate, reordered, title-mismatched, or hash-mismatched units fail validation. Runtime enforces structure and identity, not semantic truth. For every section marked `pass`, the Skill requires section-specific evidence naming the important obligations checked, citing reproducible paths/symbols/diff facts/command results/API state, and explaining why the final implementation conforms. Generic evidence alone is insufficient for multi-obligation sections; runtime does not score evidence with NLP/LLM heuristics.

`prepare-self-review`, `validate-self-review`, `publish-self-review`, `validate-public-review`, and `delivery-check` treat current state as authoritative. Reviews bind exact PR HEAD, approved contract comment ID, contract SHA, unit IDs/order/titles/hashes, and checklist SHA/items. Any change makes a prepared/published v2 review stale, including a changed comment ID with the same SHA. Re-preparation reuses a draft only if Issue/PR identity and every bound identity are unchanged; otherwise it preserves a stale backup and creates a fresh pending v2 draft. Validation is side-effect free.

Publish v2 comments with metadata `<!-- agent-self-review:v2 issue=N pr=N head=HEAD contract_comment=ID contract=CONTRACT_SHA checklist=CHECKLIST_SHA -->`. The PR `## Agent Self-Review` pointer has `Comment ID`, payload `SHA-256`, `HEAD`, `Contract Comment ID`, `Contract SHA-256`, and `Checklist SHA-256`. Publication reads Issue and canonical contract pointer, fetches/verifies the named contract comment, reads PR HEAD, derives units/checklist, validates the local draft, then creates an immutable comment. Immediately after creation it fetches the exact created comment through the single-ID `pull_comment(comment_id)` boundary and verifies the returned ID, PR `issue_url`, and exact submitted body. This named-comment GET readback is separate from the later race check. Only after it succeeds does publication re-read the Issue pointer and named contract, then PR HEAD, recompute contract/unit/checklist identities, update the pointer only when every identity matches, and read back the pointer. If named-comment readback fails or any identity changed, publication fails, leaves the comment as immutable orphan evidence, and does not edit/delete it or point to it. Historical comments are never rewritten.

QA drafts use `.agent-state/issues/<issue>/qa-pr-<pr>.json` and bind the exact PR HEAD and approved contract comment ID/SHA. A `required` QA payload contains at least one named case with action, expected outcome, `pass|fail|untested` result, and concrete evidence. A `not_applicable` payload contains zero cases and a concrete reason. Pending, stale, malformed, oversized, or credential-bearing evidence cannot pass. `prepare-qa`, `validate-qa`, `publish-qa`, and `validate-public-qa` use an immutable named PR comment plus `## Agent QA` pointer and readback/race checks. Pointer field keys are stripped before duplicate detection, and whitespace variants of a key are rejected. QA accepts only every case `pass` or a valid `not_applicable` record; `fail`, `untested`, and stale records block. QA is a separate gate and cannot substitute for either review.

Independent-review drafts use `.agent-state/issues/<issue>/pr-review-pr-<pr>.json` and bind exact HEAD, contract comment ID/SHA, contract review units, checklist SHA/items, findings, and a required `fresh_context: true` attestation. `prepare-pr-review`, `validate-pr-review`, `publish-pr-review`, and `validate-public-pr-review` publish immutable `Agent Independent Review` comments and pointers with named readback and race checks. Every contract unit and checklist item must be present with evidence. A/B findings block; D findings do not; C findings require an explicit boolean `blocking`. The runtime validates this declaration and the artifact but cannot prove that a separate session or person supplied it. The `pr-review` Skill requires a new session/subagent or human reviewer; the implementation session must not author this artifact. No host-specific session API is assumed.

`validate-public-review` may parse structurally valid schema-v1 records for diagnostics; its result exposes schema version 1 and indicates full-contract conformance is absent. It does not upgrade v1. Delivery rejects v1 with explicit remediation equivalent to: `published self-review schema v1 has no full Implementation Contract conformance; regenerate and publish a schema v2 self-review with the current workflow`.

Handoff requires same-repository Issue/PR identity; open non-draft PR; `Closes #N`; Issue label `phase:review`; current Final Verification result `pass`; current exact-HEAD schema-v2 self-review; current QA result `pass` or valid `not_applicable`; current fresh-context-attested independent review with every contract unit `pass`, no checklist `fail`, and no blocking finding; filled Verification and Untested fields; schema-valid project profile allowing `initialized:false`; and every configured Required Check green on the current HEAD. Self-review contract `fail` and `untested` both block; checklist `untested` remains non-blocking by itself. Independent review checklist `untested` does not block by itself. Final Verification `partial`/`empty`, QA `fail`/`untested`/pending, stale evidence, A/B/blocking-C findings, and untested/failing independent contract units block. Required Checks are evaluated after all evidence gates. The initial Issue/PR objects read by `delivery-check` are the evidence-validation snapshot. After all evidence and checks are evaluated, final readback must preserve PR HEAD, exact PR body text, exact Issue body text, Issue/PR open/draft/merged state, and presence of `phase:review`; any difference blocks delivery. The approved contract is parsed again from the final Issue body as a defense-in-depth check. Any new PR commit invalidates all HEAD-bound evidence; contract supersession invalidates contract-bound evidence.

The repository self-host `.agent/project.json` configures four global `verify_final` commands in this order: `python -m compileall runtime tools tests`, `python -m unittest discover -s tests -p "test_*.py"`, `python tools/build_dist.py --check`, and `python tools/validate_dist.py`. Final Verification must execute all four successfully on the clean exact PR HEAD to pass; an empty or partial receipt remains non-passing.

Preserve checklist failure fields `review_failures` and `review_failure_count`; return at most ten checklist IDs with text truncated to 240 characters. Add `review_schema_version`, `contract_comment_id`, `contract_sha256`, `contract_review_failures`, `contract_review_failure_count`, and `contract_review_untested`/`contract_review_untested_count`. Return bounded summaries for Final Verification, QA, and Independent Review including current result, staleness, and finding/unit counts, without command bodies, evidence bodies, or contract text. The failure and untested detail arrays are each capped at ten entries with bounded ID/title text only; counts report all affected sections and no contract body is emitted. Contract `untested` details identify incomplete conformance. No configured checks is a failure. App-scoped checks require the exact app; source-unrestricted or legacy checks may match a successful check-run or commit status. Check-run conclusions `success`, `skipped`, and `neutral` pass; commit statuses require `success`. Delivery reports `base_ref`, `default_base_ref`, and `stacked` for the PR.

Merged delivery requires a merged PR, closed Issue, and no phase label. `finalize-merged-issue` verifies merged/closed state and removes only `phase:review`; any other `phase:*` label fails without mutation. Repeating after that label is gone succeeds without mutation. A PR affecting a generic component needs a concrete `Generic profile rationale:`.
<a id="req-rt-009"></a>
<a id="req-rt-009-failure-logging-and-cleanup"></a>
### 3.9 REQ-RT-009 Failure, logging, and cleanup

Malformed profiles fail before hooks. Unknown scope never broadens. Subprocess failures retain the exit status and identify the command without secrets. GitHub identity/API ambiguity fails closed. Temporary payloads are removed on handled success/failure paths. Tokens and payload contents are never printed. Skipped targets and unexecuted platform tests are reported as unverified, not passed.

Branch cleanup and hooks occur only after a successful switch. Failures in these post-switch steps leave the current branch in place and report the failed stage; retries on that current target branch are non-destructive.

<a id="req-rt-010"></a>
<a id="req-rt-010-observable-behavior"></a>
## 4 REQ-RT-010 Observable behavior

Commands produce bounded JSON or explicitly described skip lines. They identify affected Issue, component, target, contract SHA, review HEAD, and gate result without printing payload content or credentials. Read-only commands never mutate Issue, PR, profile, or source documents.

<a id="req-rt-011"></a>
<a id="req-rt-011-data-and-api-formats"></a>
## 5 REQ-RT-011 Data and API formats

Schema-2 profile fields are `schema_version`, `initialized`, `project_name`, `components`, `branch`, `workspace`, `milestones`, and project `hooks`. `branch` contains `prefix`, `max_slug_length`, optional `cleanup_on_switch` (default `[]`), and `required_checks`. `branch.required_checks` is an array of names or `{name, app_id}` entries; an empty array prevents handoff. `workspace` contains only `isolation`, one of `auto|required|disabled`, defaulting to `auto` when omitted. `milestones` contains `mode` and `version_source`, with the legacy `enabled` compatibility mapping described above. Each component declares `id`, `roots`, `stacks`, `application_types`, `targets`, and verification `hooks`; targets declare `id`, `runnable_on`, verification `hooks`, and optional `requirements`. Hook arrays contain command strings; project hooks may include `branch_switch`, while component and target hooks may not.

The canonical checklist block is delimited by the exact lines `<!-- AGENT_REVIEWER_CHECKLIST_V1 -->` and `<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->`; valid Markdown checkbox items inside it take precedence over the narrow Markdown `Reviewer Checklist` H2 fallback. Safe normalization recognizes only legacy Markdown checkbox formatting in one recognizable checklist H2, preserving item text, order, and all bytes outside that H2. Bare Unicode `☐` items and plain numbered prose headings are not accepted substitutes for Markdown checklist syntax.

Issue-scoped local state lives below `.agent-state/issues/N/`. Contract state contains the exact payload and SHA metadata. Execution state contains only the binding fields defined above and is never published or used as host-provenance evidence. Self-review state records schema version, Issue, PR, HEAD, approved contract comment ID/SHA, ordered contract section identities/evidence, checklist SHA, and checklist item evidence. Temporary JSON/payload files are outside committed source and are removed after use.

<a id="req-rt-012"></a>
<a id="req-rt-012-security-and-privacy"></a>
## 6 REQ-RT-012 Security and privacy

GitHub requests use authenticated `gh api` through one module. User payloads travel as structured JSON input, not shell strings. Local contract and execution state is Issue-scoped and should remain uncommitted; temporary data is cleaned after use. Host worktree placement, access control, resume, and cleanup remain host-owned. `.worktreeinclude` is optional project-owned configuration for ignored files; no secrets or ignored files are inferred or copied.

<a id="req-rt-013"></a>
<a id="req-rt-013-error-and-boundary-behavior"></a>
## 7 REQ-RT-013 Error and boundary behavior

| Condition | Required behavior |
|---|---|
| Unsupported profile or malformed target requirements | Fail before output or any configured hook. |
| Conflicting auto-detected versions or duplicate/closed exact-title milestones | Fail before Issue milestone assignment; report `VERSION_AMBIGUOUS` for version conflicts. |
| Invalid explicit target milestone version | Fail before listing, creating, or assigning a Milestone. |
| Issue already assigned to a different Milestone | Fail before create/assign and report the current and requested titles when available. |
| Dirty worktree or invalid/non-open/foreign/PR Issue | Fail before any branch switch. |
| Dirty worktree/default-branch/no-ahead feature handoff | Fail before push and before PR/Issue mutation. |
| Push failure or remote HEAD mismatch | Fail before PR mutation and phase transition. |
| Conflicting/draft/fork/multiple matching PR | Fail closed without rewriting, converting, duplicating, or changing Issue phase. |
| PR exists but phase transition fails | Return PR identity and allow an idempotent retry. |
| Required Checks pending after PR establishment | Keep the PR and report delivery blocked, not complete. |
| Invalid/unknown base branch or mismatched expected base SHA | Fail before branch switch, cleanup, or hooks; preserve the current branch and worktree. |
| Invalid workspace policy or unknown workspace fields | Fail Schema 2 profile validation before output, hooks, or GitHub mutation. |
| Required isolation unavailable | Stop before source edits or binding creation. |
| Isolated mode on the main checkout, dirty initial workspace, wrong base SHA, or current mode off the configured Issue branch | Fail before writing the execution binding. |
| Execution binding belongs to another Issue, repository, or workspace | Fail closed without rebinding it. |
| Approved Contract changed after binding | Require explicit `--supersede`; preserve workspace, base, initial HEAD, and canonical branch. |
| Isolated review branch cannot fast-forward or remote readback differs | Fail without force push, rebase, rename, or branch cleanup. |
| Cleanup path escapes the repository | Reject the profile before Git mutation. |
| Cleanup or hook fails after a real switch | Keep the new branch, report current branch and failed stage, and do not rerun switch work on same-branch retry. |
| Missing/malformed Issue component list | Fail before hook execution or partial context output. |
| Current ADC is missing, unapproved, stale, or malformed during `context show` | Report the bounded invalid state without binding or other mutation. |
| Host/architecture/tool/capability mismatch | Skip only the target and report it unverified. |
| Contract hash, named comment identity, Issue, or mirror mismatch | Fail closed; preserve prior verified bytes. |
| Concurrent Issue body change | Stop, preserve unrelated sections, report unsupported concurrency. |
| Non-pass Final Verification; QA other than PASS/N/A; stale evidence; independent unit not PASS, checklist FAIL, or blocking A/B/C finding; absent/pending/failed Required Check | Fail handoff and return bounded gate summaries. |
| Premature merge finalization or unexpected phase label | Fail without label mutation. |
| Network/API/auth failure | Report exact command/stage and fail closed. |

<a id="p-ases-bootstrap-commands"></a>
## 8 P-ASES Bootstrap commands

`python -m p_ases delivery gate-policy ISSUE` pins and reads the immutable gate selection for an Issue. Only Issues #26–#32 in `puchinya/ai-agent-workflow` select `bootstrap-legacy-v1`; repository identity is compared case-insensitively. A non-cohort Issue requires the current unique activation record and a GitHub `created_at` later than activation to select `p-ases-v1`. Pre-activation existing Issues and Issues without a valid activation return `UNDETERMINED`; the new router does not switch them to another gate. The command never changes phase labels.

`python -m p_ases delivery bootstrap-check ISSUE PR --unverified-host HOST` checks only child Issues #27–#32 in the fixed repository. It reads the current approved ADC and PR, verifies same-repository open/non-draft state, the approved base/head branch pair, current exact HEAD, and standalone `Closes #ISSUE`; it pins gate selection; it requires a clean local checkout at that exact PR head; then it runs bounded compile, full-unittest, distribution-build check, distribution validation, and `git diff --check` commands. The checkout HEAD, branch, tracked/untracked/staged cleanliness is rechecked after local commands, after GitHub technical evidence collection, and immediately before publishing. It reads the current Actions workflow run and latest required Check Run for each configured check plus `pull-request-metadata`; only current-head completed/success observations with provenance count. Review inputs and review artifact readback do not participate in this technical gate. The legacy `--self-review-comment` and `--independent-review-comment` options remain accepted for compatibility and are ignored. Missing technical evidence, unapproved ADC, stale subjects, fork/draft PR, skipped/neutral/failed checks, missing branch policy, dirty checkout, or API errors return `BOOTSTRAP_BLOCKED` with machine-readable reasons and nonzero exit status; complete technical evidence returns `BOOTSTRAP_TECHNICAL_READY` with exit status zero.

Base/head pairs are explicit per-Issue policy, not inferred from branch names or dependency labels. When an upstream PR is merged and a child PR base moves, the PR subject changes and old Bootstrap evidence is stale; update the fixed pair and regression tests before evaluating the new subject. A child without an approved pair remains `BOOTSTRAP_BLOCKED` until its pair is specified.

The independent context artifact uses a canonical `PASES_BOOTSTRAP_INDEPENDENT_CONTEXT_V1` Issue-comment body with fields `subject`, `reviewer_context_id`, `separate_context_confirmed: true`, and a non-empty `report`. The `PASES_BOOTSTRAP_INDEPENDENT_REVIEW_V1` record points to that comment permalink and includes the SHA-256 of the complete artifact body. The reviewer confirms the separate execution; the comment digest proves which report was read back, not the host or session identity.

If a fixed-cohort Issue still uses the legacy split marker (`child_adc_comment_id`, `child_adc_sha256`, `child_adc_comment_url`, and `child_key`) instead of a P-ASES pointer record, Bootstrap reads the exact named comment, validates its digest, repository, Issue, child key, and ADC schema, then re-reads the Issue marker. Because that legacy marker has no approval state, the result records the exact ADC subject but remains `BOOTSTRAP_BLOCKED`; Bootstrap does not publish a replacement ADC pointer or infer approval.

When migrating a legacy Issue-body ADC pointer to the append-only journal, retain the original `## Agent Development Contract` pointer block unchanged. The first journal record must name the legacy pointer Comment ID as its predecessor (or `none` when there was no legacy pointer). Do not delete or rewrite this anchor unless a separately approved migration format records its exact prior bytes and predecessor.

An exact subject binds repository, Issue, PR, ADC Comment ID/SHA, base ref/SHA, and head ref/SHA. Each result also binds a source digest of the Bootstrap evaluator, CLI, GitHub/ADC/Git/process/profile adapters; a tool update changes the result and appends a new attempt while the pinned gate selection stays fixed. Historical blocked V1 records without that digest remain readable as history, but cannot be treated as current readiness. `PASES_BOOTSTRAP_REVIEW_V1` records are append-only, linked by attempt number and predecessor Comment ID; exact retry reuses the existing record, while different observations append a new record without editing history. New results set `review_mode=WAIVED_BOOTSTRAP`, represent technical success as `BOOTSTRAP_TECHNICAL_READY`, keep reviewer/context IDs null, verified review evidence empty, the separate-context flag false, and final-user-review eligibility false. The historic `BOOTSTRAP_REVIEW_READY` shape remains readable without automatic promotion. Before publication and again after publication, the evaluator re-reads and compares the complete ADC pointer, unique pinned gate selection, PR number/state/draft, base and head repository/ref/SHA, and complete PR body including its standalone `Closes #N` association. If any field drifts after a record is written, a newer `BOOTSTRAP_BLOCKED` observation is appended and read back as the latest record. A publication/readback failure cannot produce a successful result. Bootstrap technical readiness does not claim ordinary P-ASES readiness, any review or approval, merge permission, or Issue closure.

The Bootstrap evaluator may be newer than the PR being evaluated because it is introduced by a downstream migration PR. Run the evaluator from its own clean checkout and pass `--root` pointing to a separate clean checkout whose HEAD is the exact target PR HEAD. For example: `PYTHONPATH=<evaluator-checkout>/runtime python -m p_ases delivery bootstrap-check <issue> <pr> --repo <owner/name> --root <target-pr-checkout>`. The evaluator fingerprint comes from the evaluator checkout; local checks, branch/HEAD/cleanliness checks, and PR subject validation use the target checkout. Do not copy downstream evaluator files into the target PR branch or report a result for any HEAD other than the target PR's current HEAD.

The activation reader accepts only a unique `PASES_ACTIVATION_V1` record with six closed child Issues, six merged PRs at the declared merge SHAs with exact `Closes #N` associations and repository-owner merge attribution, matching parent integration evidence (documentation/tests/16 Skills/distribution), and a separate `PASES_ACTIVATION_APPROVAL_V1` comment authored by the repository owner. The legacy integration comment is only a pointer and digest envelope: its PASS fields and HTTPS URLs are not trusted until exactly one Verification V2 comment and one Acceptance V2 comment are read back and their referenced GitHub Actions run, job, step, and Check Run APIs are reconstructed on the activation commit SHA, approved parent ADC digest, and fixed trusted App ID 15368. Issuance requires the latest successful run and attempt; historical Activation reads fetch the exact recorded run ID/attempt and its jobs through the attempt-specific GitHub Actions APIs, so later runs or attempts do not replace valid issuance-time evidence. If GitHub cannot return the pinned attempt or provenance, the record blocks without fallback. Each read records a debug diagnostic with the number of GitHub API requests and cumulative client-observed latency; metrics never bypass evidence checks. Child merge SHAs must be present in that activation commit. Approval, activation, and referenced evidence comments require unique Issue #26 list entries and identical direct/list/direct snapshots of ID, body, creation/update timestamps, Issue/HTML/API URLs, and stable owner User ID/login/type; `created_at` must equal `updated_at`. Profile/avatar changes are ignored. Edits, deletions, duplicates, identity mismatches, or readback errors block. The current main branch must contain the activation commit, but advancing main after activation preserves a still-ancestral valid record. Normal `delivery readiness`, Required Check trusted App-ID validation, and phase transitions are unchanged.

<a id="consumer-activation-runtime-contract"></a>
## 9 Consumer Activation runtime contract

<a id="req-f01-002"></a>
<a id="req-f01-002-activation-locator"></a>
### 9.1 REQ-F01-002 Activation locator

`.agent/project.json` MAY contain only `activation: {"issue_number": N}` as its Activation locator. The positive Issue number must resolve to one marked Issue in the same repository. The locator is not activation evidence. Unknown or malformed profile data blocks before GitHub reads or label writes.

<a id="req-f01-004"></a>
<a id="req-f01-004-setup-request-and-verification"></a>
### 9.2 REQ-F01-004 Setup request and verification

The required request is `P-ASESを有効化して。`. It creates or reuses the marked Activation Issue, proposes a default ADC only when none exists, writes the locator on a setup branch, and opens/reuses one exact setup PR. The setup branch may commit only the intended `.agent/project.json` change; before staging, Git must verify that no other staged, modified, or untracked path exists. After push, the worktree and exact remote commit must pass readback. If PR creation fails after push, an exact one-parent, one-file branch matching the current subject remains resumable on retry; any drift or ambiguous PR state fails closed. When that branch exists only on the remote, the retry fetches its exact ref and verifies the fetched full SHA against the prior `ls-remote` observation before creating a local branch; all parent, diff, profile, clean-worktree, and remote-SHA checks still apply. No Activation is recorded before merge. A trusted verifier requires the exact setup PR merged by the authenticated current repository admin, exact `.agent/project.json`, approved ADC, issuance-time trusted Required Check evidence pinned by exact Check Run IDs, and merge ancestry on the default branch before publishing approval and record comments. Each required check is selected from the latest matching Check Run created no later than the exact PR `merged_at`, ordered by `(created_at, Check Run ID)` so timestamp ties are deterministic. That selected run must be completed successfully with `completed_at <= merged_at`; a pending or failed run at merge cannot be replaced by a later successful rerun. The record binds only these qualifying run IDs and timestamps, and historical reads revalidate those exact runs by ID.

<a id="req-f01-006"></a>
<a id="req-f01-006-historical-activation-pin"></a>
### 9.3 REQ-F01-006 Historical Activation pin

Phase validation resolves an existing Gate Selection to its exact historical Activation record, even after a successor Activation. Existing ADC, kind/phase labels, frozen work binding, receipts, and exact-subject checks remain mandatory.
