<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Design

- Status: Existing content approved; DES-F01-014 and DES-F01-015 are drafts pending Issue #63 successor ADC approval and phase evidence.
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related specification: [Portable Workflow Specification](../specs/workflow-spec.md)

<!-- contents:start -->
**Contents**
- [1 Context and goals](#1-context-and-goals)
- [2 Requirements traceability](#2-requirements-traceability)
- [3 DES-WF-001 Architecture](#3-des-wf-001-architecture)
- [4 DES-WF-002 Data flow and ownership](#4-des-wf-002-data-flow-and-ownership)
- [5 DES-F01 Consumer gate routing and history](#5-des-f01-consumer-gate-routing-and-history)
  - [5.1 DES-F01-008 Effective branch-policy assessment](#51-des-f01-008-effective-branch-policy-assessment)
  - [5.2 DES-F01-009 Exact-plan Ruleset writes](#52-des-f01-009-exact-plan-ruleset-writes)
  - [5.3 DES-F01-010 V1 preservation and current checks](#53-des-f01-010-v1-preservation-and-current-checks)
  - [5.4 DES-F01-011 Versioned V2 setup and record](#54-des-f01-011-versioned-v2-setup-and-record)
  - [5.5 DES-F01-012 Record-comment effective time](#55-des-f01-012-record-comment-effective-time)
  - [5.6 DES-F01-013 Bootstrap and independent delivery gates](#56-des-f01-013-bootstrap-and-independent-delivery-gates)
  - [5.7 DES-F01-014 Activation-scoped administrator session](#57-des-f01-014-activation-scoped-administrator-session)
  - [5.8 DES-F01-015 Delegated owner decision relay](#58-des-f01-015-delegated-owner-decision-relay)
- [6 DES-WF-003 Workspace execution flow](#6-des-wf-003-workspace-execution-flow)
- [7 DES-WF-004 Failure handling](#7-des-wf-004-failure-handling)
- [8 DES-WF-005 Authorization boundary and PR handoff](#8-des-wf-005-authorization-boundary-and-pr-handoff)
- [9 Alternatives considered](#9-alternatives-considered)
- [10 Migration gate routing](#10-migration-gate-routing)
- [11 DES-WF-006 Human review and final delivery](#11-des-wf-006-human-review-and-final-delivery)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [DES-WF-001](#des-wf-001) — 3 DES-WF-001 Architecture
- [DES-WF-002](#des-wf-002) — 4 DES-WF-002 Data flow and ownership
- [DES-F01-008](#des-f01-008) — 5.1 DES-F01-008 Effective branch-policy assessment
- [DES-F01-009](#des-f01-009) — 5.2 DES-F01-009 Exact-plan Ruleset writes
- [DES-F01-010](#des-f01-010) — 5.3 DES-F01-010 V1 preservation and current checks
- [DES-F01-011](#des-f01-011) — 5.4 DES-F01-011 Versioned V2 setup and record
- [DES-F01-012](#des-f01-012) — 5.5 DES-F01-012 Record-comment effective time
- [DES-F01-013](#des-f01-013) — 5.6 DES-F01-013 Bootstrap and independent delivery gates
- [DES-F01-014](#des-f01-014) — 5.7 DES-F01-014 Activation-scoped administrator session
- [DES-F01-015](#des-f01-015) — 5.8 DES-F01-015 Delegated owner decision relay
- [DES-WF-003](#des-wf-003) — 6 DES-WF-003 Workspace execution flow
- [DES-WF-004](#des-wf-004) — 7 DES-WF-004 Failure handling
- [DES-WF-005](#des-wf-005) — 8 DES-WF-005 Authorization boundary and PR handoff
- [DES-WF-006](#des-wf-006) — 11 DES-WF-006 Human review and final delivery
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
| Activation administrator authority is temporary and owner-mediated | Only the two explicit Activation admin commands create a one-command TTY session; ordinary commands retain ambient authentication and never escalate. |
| Implementation owns end-to-end handoff | The implementation flow continues through a review-ready PR, exact-HEAD self-review, and delivery gate before reporting completion. |
| New Contract layout is checked without changing legacy publication | A separate read-only preflight validates the canonical template's physical H2 structure before new-template contracts are saved or published; the historical comment and mirror path remains unchanged. |
| Chat project instructions work across hosts | One Japanese project-instructions body uses one repository URL substitution and describes only capabilities available to the active chat; it does not depend on installing this workflow plugin. |

<a id="des-wf-001"></a>
<a id="des-wf-001-architecture-and-phase-authority"></a>
<a id="des-wf-001-architecture"></a>
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
<a id="des-wf-002-data-flow-and-ownership"></a>
## 4 DES-WF-002 Data flow and ownership

1. A Skill starts from an Issue and reads only the routing data and documents relevant to that task. The Issue declares structured document decisions; older link-only sections remain routable.
2. A consumer's `.agent/project.json` is parsed and fully validated before profile-dependent output or hook execution.
3. Context resolution emits a compact, deterministic manifest. It never writes consumer-controlled files.
4. Contract, receipt, QA, and review payloads are validated locally before GitHub mutations. New contract input with a recognizable legacy Reviewer Checklist H2 is structurally normalized before its exact payload SHA is computed; item text/order and bytes outside the checklist remain unchanged, and ambiguous prose fails closed. Historical approved bytes remain readable and restorable unchanged. Final Verification requires a clean worktree and exact local/PR HEAD equality, then publishes only command identities and hashes. Self-review binds the named approved contract ID and verified SHA, derives exact-byte section identities, and keeps contract conformance separate from checklist review. QA remains a separate HEAD/contract-bound result. Independent review requires a fresh-context attestation and binds every contract unit and checklist item; the implementation session does not author it. Each immutable comment is read back by exact ID before its pointer is changed; a failed readback or changed state leaves orphan evidence.
5. Current work routes through ADC and Issue validation, exact-base work binding, PR establishment, subject-bound Verification and Acceptance evidence, separate Audit and User Review, and the delivery gate. Each mutation is followed by exact readback; any new subject commit invalidates evidence bound to the previous HEAD.
6. `build_dist.py` constructs each host package in memory from canonical source and adapter metadata, then writes a deterministic path set.

`phase_evidence.py` owns the `PASES_PHASE_DECISION_V1` model, canonical JSON codec, document hashing, generation-scoped predecessor lookup, and two complete direct/list/direct identity snapshots. The record is a technical receipt derived from the current approved ADC, not a user approval. `ExecutionBinding` records the dedicated Issue branch and the `work` route appends an immutable binding generation when the approved ADC is explicitly superseded, retaining the original base, branch, worktree, and initial HEAD. Specification receipts inspect only specification artifacts; design receipts also verify the unchanged specification predecessor; ready receipts verify the completed predecessor chain and ready-stage documents. A changed prior artifact blocks dependent receipts. Ready resolves each `REQ`/`DES`/`ORA`/`TST` link to a canonical file in the same commit, checks the actual anchor, verifies the ADC path or explicit unchanged decision, and reads each executable test source from the commit tree. `github.py` reads and writes comments, Issues, labels, definitions, and branch refs; `git.py` supplies the local branch, HEAD, and ancestry checks. Every ordinary single/child phase transition verifies the actual kind, approved ADC, current Activation/Gate Selection, branch, and binding. `ready -> execution` rebuilds the ready decision on the current HEAD before any label write. Advance re-reads the Issue and evidence immediately before its label mutation and then reads the full Issue state back. Unchanged labels survive the transition. Existing child Issues are checked in place and never reset to requirements.

<a id="des-f01-workflow-consumer-activation"></a>
<a id="des-f01-consumer-gate-routing-and-history"></a>
## 5 DES-F01 Consumer gate routing and history

Migration routing is selected only for the exact P-ASES repository plus its fixed #26–#32 cohort. The consumer path is selected for other repository/Issue pairs even when the Issue number overlaps that cohort. The project locator names the consumer's one marked Activation Issue; it is not proof. ADC comments and their pointer journal define the proposed and approved policy generations.

Setup is a two-stage state machine: the exact PR merge by a current human admin approves policy, and the post-merge verifier then appends approval and Activation comments. Git stages only `.agent/project.json` after validating that it is the sole changed path; after push it reads back a clean worktree and the exact remote commit. If PR creation fails after push, retry resumes only a direct-child branch whose sole diff and committed profile bytes match the original setup subject. For a remote-only branch, retry fetches the exact ref and verifies its full commit SHA against the preceding `ls-remote` observation before creating a local branch, then repeats all parent, diff, profile, cleanliness, and remote-readback checks. No phase label changes during setup or Activation verification. Each successful Activation comment is linked to the previous record ID. For each Required Check, issuance selects the latest run created no later than the exact PR `merged_at`, with Check Run ID as the deterministic tie-breaker for equal `created_at`; that run must be completed successfully at or before merge. A pending or failed run at merge cannot be rescued by a post-merge rerun. History reads validate every comment, ADC generation, PR subject, main ancestry, pinned Required Check Run IDs/results and their completion-before-merge bound, merger, and predecessor, then compare complete marker snapshots before returning. A partial approval without its Activation record is never treated as active; an exact retry can finish that same PR only.

The setup PR's verified `merged_at` controls strict Issue creation-time routing; the later record-comment timestamp is retained and checked as history. A later Activation appends a successor and does not change older Gate Selection payloads. New selection chooses the latest merged Activation before the Issue's `created_at`; re-running gate-policy follows an existing selection's exact Activation Comment ID and digest through history. Phase validation resolves the same historical authority. The consumer path stores the Activation Issue number in the Gate Selection while preserving the existing fixed-cohort payload shape.

<a id="des-f01-008"></a>
<a id="des-f01-008-effective-branch-policy-assessment"></a>
### 5.1 DES-F01-008 Effective branch-policy assessment

`branch_policy.py` remains pure: it combines the branch flag, legacy protection read, effective branch rules, Ruleset details, current profile mode, and exact trusted checks into the #62-compatible `EffectiveBranchPolicy`. `github.py` owns the GitHub reads and reports HTTP status codes without logging credentials. A 403 is `UNAVAILABLE`; only a verified 404 is evidence that legacy protection is absent. V2 issuance requires `VERIFIED` plus the active repository Ruleset and readable policy endpoints.

<a id="des-f01-009"></a>
<a id="des-f01-009-exact-plan-ruleset-writes"></a>
### 5.2 DES-F01-009 Exact-plan Ruleset writes

`ruleset_management.py` builds a canonical plan from committed `.agent/project.json`, repository/owner identity, the configured Activation Issue, branch state, the one same-name repository Ruleset, current policy evidence, and open PRs. The plan digest covers the desired exact GitHub payload, predecessor applied-record ID, and a create/update/no-op diff. Apply verifies the exact owner comment on the configured Activation Issue; this repository's committed `activation.issue_number` is 57. Before a POST or PUT it atomically writes a local intent bound to the plan, approval ID, and predecessor. A retry after `WRITE_STARTED` performs reads only: it verifies the original preconditions, the unique exact Ruleset ID/body, and the effective policy, then appends or reuses the one matching ownership record. No intent means an unowned same-name Ruleset cannot be adopted. Ambiguous state blocks without a second write or rollback.

The managed state is `P-ASES Final Delivery (managed)` at repository scope, active on `~DEFAULT_BRANCH`, with no bypass actors, the exact trusted Required Check set, zero required approvals, resolved review threads, supported merge methods, and `non_fast_forward`. The exact body digest, owner-approval comment ID, and predecessor form append-only ownership evidence on the configured Activation Issue. Future PUTs require the prior ruleset ID and digest from that evidence. Other Rulesets and legacy protection are never mutated. An independently observed legacy approval requirement is retained as a constraint; it cannot be overwritten by the managed Ruleset's lower approval count.

<a id="des-f01-010"></a>
<a id="des-f01-010-v1-preservation-and-current-checks"></a>
### 5.3 DES-F01-010 V1 preservation and current checks

V1 record payloads, creation-time semantics, and existing Gate Selections retain their original representation. Existing Issues resolve their pinned record through a shared strict-prefix history reader, then run the current live policy and runtime checks. A later corrupt V2 record is outside an older Issue's validated prefix; corruption in the selected prefix still blocks. New selection and successor setup read the full Activation chain.

<a id="des-f01-011"></a>
<a id="des-f01-011-versioned-v2-setup-and-record"></a>
### 5.4 DES-F01-011 Versioned V2 setup and record

V2 uses separate setup, approval, and record markers. Its setup binds the raw committed profile bytes, explicit `solo_owner` mode, required `(context, App ID)` checks, managed Ruleset ID, exact earlier Ruleset applied-record ID, and effective-policy digest. Verification reads current policy during merged-PR validation and repeats the full read immediately before publishing the Activation record; both snapshots must match the setup's Ruleset ID, applied-record ID, and policy digest. The record keeps the V1 merge and check evidence and adds those V2 fields. V1 serialization remains byte-for-byte stable. Existing V2 history validates the Ruleset ownership prefix through its bound applied-record ID; new V2 issuance checks the full ownership history.

<a id="des-f01-012"></a>
<a id="des-f01-012-record-comment-effective-time"></a>
### 5.5 DES-F01-012 Record-comment effective time

For V1, `activated_at` remains the setup PR `merged_at`. For V2, the record's GitHub comment `created_at` supplies `activated_at`; it is retained from direct/list/direct readback rather than inferred from a setup PR. Gate selection compares Issue `created_at` strictly with that time, so an Issue in the merge-to-record gap continues to use the previous eligible V1 record.

<a id="des-f01-013"></a>
<a id="des-f01-013-bootstrap-and-independent-delivery-gates"></a>
### 5.6 DES-F01-013 Bootstrap and independent delivery gates

The #63 branch contains the policy APIs and exact-plan writer needed to bootstrap its own repository Ruleset before merge. The initial Ruleset plan and human approval are still bound to the exact branch state. User Review, independent review, required CI, Final Delivery, and owner merge authorization remain separate gates. PR #62 later reuses the shared branch-policy and profile APIs without changing its #60 ADC or closing association.

`ExecutionBinding` uses the current nine-field row, including `branch_ref`, either as a single record or inside the append-only history wrapper. The prior eight-field form is outside the supported contract and may be rejected by read/resume commands; callers must not assume compatibility, branch inference, migration, or automatic rewrite. At `ready`, a linked test source file must already exist in the branch commit, but it may be a failing scaffold awaiting implementation; the receipt binds its path and bytes without claiming a test pass. Execution may extend that source, and later verification establishes the outcome.

After `issue advance` attempts its label PUT, both a normal response and an error/lost response take the same readback path. The runtime checks Issue number, repository URL, non-PR/open identity, unchanged body and complete intended label set, including kind, phase, and attention. Ordinary Issues also revalidate the current approved ADC pointer and comment generation. Any mismatch returns `BLOCKED` and states that the PUT may already have applied; the runtime does not roll labels back or retry automatically.

The kind labels share the P-ASES color `c5def5`: `kind:single` has description `P-ASES Issue kind: single`, `kind:child` has description `P-ASES Issue kind: child`, and the existing `kind:parent` definition remains migration-owned. `issue_graph.py` owns only the two child initialization definitions: `kind:child` (`c5def5`, `P-ASES Issue kind: child`) and `phase:requirements` (`0e8a16`, `Workflow phase: requirements`). It checks repository definitions before creating a child, creates missing definitions with exact readback, then creates the child with those labels and existing `enhancement`. Existing children must already have one `kind:child`, one valid phase, and at most one attention label. Fixed legacy Bootstrap children #27–#32 are read without automatic relabeling. A create response lost after GitHub writes is recovered only when one exact child marker can be read back.

The structural Contract preflight is a separate local flow: the CLI reads the explicit source path, `contracts.py` reuses `_prepare_contract_input` and `_contract_h2_headings`, and bounded JSON reports the normalized payload identity. It neither writes a mirror nor contacts GitHub. The implementation Skill invokes it before saving or publishing new contracts created from the canonical template; legacy contract APIs and historical reads do not depend on it.

<a id="des-f01-014"></a>
### 5.7 DES-F01-014 Activation-scoped administrator session

`admin_auth.py::temporary_admin_client(repo, *, stdin, getpass_fn, github_factory)` owns the explicit interactive session boundary. The two new CLI commands first require an interactive local TTY in the separate trusted admin environment, then call `getpass` to read the owner-created, repository-scoped, short-lived fine-grained PAT without echo. Codex Cloud never prompts for or receives this credential. The PAT has Administration read/write and only the minimum additional permissions required by the existing Activation Issue read/write path. Each command creates a separate session; neither session is reused by another command. Non-TTY/sandbox execution returns `ADMIN_AUTH_INTERACTIVE_REQUIRED` before reading credentials or making GitHub requests. The command does not create or revoke the PAT. The owner must revoke it in GitHub after the plan/apply operation; clearing the local session does not revoke GitHub-side authority.

`GitHub` receives an optional private credential override that is excluded from representation and diagnostic output. For each `gh api` request it copies the inherited child environment, sets the override as `GH_TOKEN`, removes competing token variables such as `GITHUB_TOKEN`, and passes that environment only to the `gh api` subprocess. It never assigns `os.environ`, invokes persistent `gh auth` flows, or passes the token in argv. A `finally` path clears the client override on success, API error, exception, or interruption; Python cannot guarantee erasure of prior string copies from memory. Other subprocesses and default CLI authentication remain unchanged.

Before planning or applying, the authenticated API reads the owner login and stable user ID, repository and owner IDs, repository `permissions.admin`, collaborator permission, main branch legacy protection, repository Ruleset inventory, and effective branch rules. The authenticated stable user ID must equal the repository owner ID; the login and repository ID must match the configured target; both repository admin and collaborator permission must report admin; every protection read must be complete. A 403 or incomplete response blocks as unavailable. Admin-plan builds the existing canonical Ruleset plan and writes it outside the worktree only when it has no blockers and a `PLANNED` status. Admin-apply loads the supplied canonical plan, rechecks identity and current policy, verifies the exact independent owner approval on the configured Activation Issue, then delegates to the existing apply and durable-intent flow. Existing plan, approval, single-write, recovery, and effective-policy readback rules remain the only Ruleset mutation path.

The public surface adds exactly these two commands:

```sh
python -m p_ases delivery consumer-activation-admin-plan --repo puchinya/ai-agent-workflow --root . --output /tmp/pases-issue63-plan.json
python -m p_ases delivery consumer-activation-admin-apply --repo puchinya/ai-agent-workflow --root . --plan /tmp/pases-issue63-plan.json --approval-comment-id COMMENT_ID
```

Before the second command, ChatGPT reads back the exact plan SHA and obtains a separate `RULESET_PLAN_APPLY` confirmation; the GitHub relay records the exact approval on Issue #57 and the command verifies its actor, body, and subject. The owner supplies an Admin credential only in the separate trusted TTY environment. Authentication does not imply plan approval or authorize PR merge. Ordinary preflight/plan/apply commands do not start an admin session and preserve their existing behavior. `delivery-control` documents the local TTY operation, separate chat approval, and PAT revocation without asking the owner to transmit a secret to the agent.

<a id="des-f01-015"></a>
### 5.8 DES-F01-015 Delegated owner decision relay

Before a relay operation, ChatGPT reads back the exact operation, repository, Issue/PR, and subject SHA/HEAD and waits for the owner's direct, operation-specific chat confirmation. A generic request to continue does not authorize a write. The ChatGPT GitHub connector then acts as a delegated GitHub relay under its authenticated account; relay comments and label changes are delegated GitHub evidence, not signed or host-attested chat events. The runtime does not require Cloud host signatures, browser OAuth, or a TTY for this relay path. It blocks an operation when the GitHub actor, target, or subject cannot be verified.

`owner_consent.py` exposes `parse_owner_decision(body)` and `verify_owner_decision_history(comments, repository, issue_number, owner_id, operation, subject_sha256)`. It parses and validates canonical `PASES_OWNER_DECISION_V1` records for `PHASE_REBASE`, `ADC_SUPERSEDE`, `RULESET_PLAN_APPLY`, and `PR_MERGE`, with `schema`, `repository`, `issue_number`, `operation`, `subject_sha256`, `pr_number`, `pr_head_sha40`, `owner_id`, `evidence_channel`, and `predecessor_comment_id`; unused PR fields are null and `evidence_channel` is exactly `delegated_github_relay`. It rejects `USER_REVIEW` records because that decision retains its existing host-attested path. The GitHub relay appends each supported record to the target Issue and reads it back. The runtime verifies canonical bytes, configured stable owner ID, unchanged comment body, monotonic predecessor/comment IDs, and one-time use of the operation/subject. The comment records the GitHub actor and delegated action; it does not claim a cryptographic link to a chat message. The implementation executor cannot create a record in the owner's name or infer chat intent from the record alone.

The five decisions remain non-interchangeable; the relay records the four GitHub operations described above, while `USER_REVIEW` uses its existing host-attested flow. A subject or operation mismatch blocks. `phase_rebaseline.py::rebaseline_issue_phase(github, issue_number, decision_comment_id, successor_adc_sha256)` verifies the exact Phase Rebase decision and changes only the complete label set needed to move #63 from `phase:ready` to `phase:requirements`; it preserves `kind:single` and all unrelated labels and never changes Issue text or prior evidence. ADC publication requires a separate confirmation. For Rulesets, the relay posts the exact two-line #57 plan approval only after a separate exact-plan confirmation for a blocker-free plan and under the successor ADC's relay-only exception. The comment must read back with the configured stable owner ID. PR merge remains separate and binds to the current PR HEAD after all required checks and independent review pass.

For the existing PR #64, the original PRBinding V1 remains byte-for-byte immutable. A successor PRBinding generation may be appended only when the repository, Issue #63, PR #64, branch, base SHA, and commit ancestry remain fixed; the ADC journal verifies the approved forward successor and the new ExecutionBinding matches the frozen execution identity. Reject missing, duplicated, non-contiguous, stale, backward, or cross-PR generations. `pr ensure`, Review Readiness, and Final Delivery evaluate the latest valid generation while preserving legacy single-generation behavior.

<a id="des-wf-003"></a>
<a id="des-wf-003-workspace-execution-flow"></a>
<a id="5-des-wf-003-workspace-execution-flow"></a>
## 6 DES-WF-003 Workspace execution flow

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
<a id="6-des-wf-004-failure-handling"></a>
## 7 DES-WF-004 Failure handling

Malformed profiles and Document impact declarations fail closed before hooks or scoped validation. Unknown selected components and invalid doc selectors never broaden scope. Host or target requirement mismatches skip commands and remain unverified. Self-review contract `fail`/`untested`, checklist `fail`, Final Verification other than PASS, QA other than PASS/N/A, independent contract units not all PASS, independent checklist `fail`, and blocking A/B/C findings block handoff. Independent D findings and checklist `untested` remain non-blocking by themselves. Legacy schema-v1 self-reviews remain diagnostic-only. GitHub ambiguity fails closed. Atomic local replacements preserve the old verified bytes on failure. Build/check mismatches identify drift without silently accepting edited generated output.

<a id="des-wf-005"></a>
<a id="des-wf-005-authorization-boundary-and-pr-handoff"></a>
<a id="7-des-wf-005-authorization-boundary-and-pr-handoff"></a>
## 8 DES-WF-005 Authorization boundary and PR handoff

The approved Issue contract is the authority for routine work through a review-ready PR. The implementation Skill retains ownership after local verification and invokes the delivery Skill for PR establishment and gates. A separate decision is reserved for material scope/architecture changes, contract supersession, ambiguous ownership/base, destructive Git operations, merge/release, permission escalation, unrelated GitHub mutation, or an explicit request to stop. A missing PR is an implementation blocker, not a reason to return a “next step.” Pending CI leaves the PR in place and reports blocked delivery.

<a id="alternatives-considered"></a>
<a id="8-alternatives-considered"></a>
## 9 Alternatives considered

- Copying the reference repository or its 105 KiB CLI would introduce template ownership and a monolith. The new runtime uses focused modules and only carries forward specified behavior.
- Hand-authored host-specific Skill trees would drift. Adapters contain only explicit host differences.
- A database, MCP server, daemon, or hosted API would add a second authority and is outside the product boundary.
- A shared OpenAI/Antigravity `plugin.json` would violate their different schemas. Packages are separate directories.

<a id="migration-gate-routing"></a>
<a id="9-migration-gate-routing"></a>
## 10 Migration gate routing

`runtime/p_ases/gate_policy.py` owns a versioned gate decision alongside, not inside, `delivery.evaluate_readiness`. Only Issues #26–#32 in `puchinya/ai-agent-workflow` select `bootstrap-legacy-v1`; repository identity comparisons are case-insensitive and all other repositories fail closed. A `PASES_GATE_SELECTION_V1` Issue comment pins the selection. Other Issues require a unique, exact-readback `PASES_ACTIVATION_V1` plus an explicit earlier `PASES_ACTIVATION_APPROVAL_V1`; without them routing is `UNDETERMINED` and stops.

`delivery bootstrap-check` reads the current approved ADC and PR, runs the bounded local verification commands, and reads current-head Check Runs and the Actions workflow run through `github.py`. Review comments, review citations, and independent-context artifacts are not inputs to this fixed-cohort technical decision. A new result records `review_mode=WAIVED_BOOTSTRAP`; technical success is `BOOTSTRAP_TECHNICAL_READY`, with reviewer/context IDs null, review evidence empty, the separate-context flag false, and final-user-review eligibility false. The checkout is rechecked after local tests, after GitHub evidence collection, and immediately before publishing. The full PR identity and body, ADC pointer, and immutable gate selection are re-read before and after publication. If any field changes after a result is published, a newer `BOOTSTRAP_BLOCKED` observation is appended and read back as latest. Failed or stale technical inputs return machine-readable `BOOTSTRAP_BLOCKED`; normal P-ASES readiness, phase advancement, and review requirements remain unchanged. This policy does not grant PR merge permission or close an Issue.

When the Bootstrap evaluator lives on a downstream stacked PR, run its CLI from that evaluator checkout and pass `--root` pointing to a separate clean checkout of the earlier target PR's exact current HEAD. The evaluator fingerprint comes from the evaluator checkout while local checks and cleanliness checks run against the target checkout; do not copy evaluator code into the target branch. For legacy Issue-body ADC pointers, retain the original `## Agent Development Contract` block as the first journal record's predecessor anchor (or record `none` when absent); do not edit or delete the old anchor during migration.

`gate_policy.py` treats the V1 integration comment only as an envelope that names the typed Verification and Acceptance V2 comments. It verifies their complete direct/list/direct comment identities, reconstructs both referenced Actions runs through `parent_gate.py` on the Activation commit SHA and approved parent ADC, checks App ID 15368 and the fixed job/step/check sets, and verifies all six actual child merge SHAs are in that commit. Activation approval, Activation record, and evidence comments must be unique and unedited (`created_at == updated_at`), attached to Issue #26, and authored by the repository owner's stable GitHub User identity. Identity equality includes ID, case-normalized login, type, body, timestamps, and canonical URLs while ignoring avatar/profile presentation fields. Every API error, deletion, duplicate, identity mismatch, or direct/list/direct change blocks. At issuance the activation SHA must be on main; later main advances preserve the record while that SHA remains an ancestor. Existing activation history is read-only. No activation record is issued during child implementation.

<a id="des-wf-006"></a>
<a id="10-des-wf-006-human-review-and-final-delivery"></a>
<a id="des-wf-006-human-review-and-final-delivery"></a>
## 11 DES-WF-006 Human review and final delivery

`user_review.py` owns the subject-bound human decision, immutable session start, and feedback snapshots. A child session binds the current ADC, PR HEAD, plan, and Readiness digest; older approvals and change requests cannot satisfy it. Ordinary comments are questions. The only comment-driven execution transition is the whole-body `P-ASES-DECISION: CHANGES_REQUESTED` / `P-ASES-HEAD: <sha40>` pair from the authenticated human; inline comments must name their GitHub `commit_id`. `github.py` is the only network boundary and paginates the four REST feedback surfaces plus GraphQL review-thread state. A previously stored snapshot is compared with every complete new read; missing records are retained as deletion tombstones. Review history treats only `<64 lowercase hex>.json` as a feedback snapshot; `session.json` and canonical `*.result.json` records are separate schemas, and unexpected filenames or a content/name digest mismatch fail closed. Review evaluation derives decisions from the authenticated GitHub user or a verified host adapter, never from CLI-supplied identity fields.

`integration.py` owns the fixed parent child set, native dependency DAG, merged PR/Issue readback, main ancestry, and typed Integration Verification/Acceptance evidence. `parent_gate.py` owns shared reconstruction of these evidence bundles from GitHub Actions run, job, step, and Check Run APIs; the #26 comments are discoverable pointers/cache and cannot prove execution on their own. This resolves Git's self-reference conflict by keeping proof outside the named commit, while deletion or edit fails closed. `delivery parent-evidence <issue> <kind> <run-id>` reconstructs new evidence from those API records and requires the latest matching run and attempt on exact main. New Verification requires all four configured matrix jobs, App ID 15368, and successful compile, committed/generated distribution checks, unit tests, documentation validation, distribution build/validation, generated-path stability, and committed-diff whitespace steps. New Acceptance requires the latest exact-main `parent-integration.yml` workflow_dispatch run and successful specification/design/test-oracle traceability, exact 16-Skill package, generated-distribution consistency, and distribution validation. Each referenced job Check Run URL must name the same repository and resolve to that App's completed/success Check Run on the exact SHA. The reader rejects caller-supplied PASS JSON even when all supplied artifact hashes match. When validating an already-issued Activation, `parent_gate.py` uses the exact run ID/attempt embedded in the referenced V2 evidence comment and the attempt-specific GitHub Actions run/jobs APIs; it verifies that attempt's workflow, event, branch, repository, SHA, jobs, steps, and Check Runs without comparing it to the latest attempt. If the historical attempt cannot be fetched or any API provenance is incomplete, it blocks with no comment/cache fallback. Thus retries do not erase valid historical evidence while issuance still rejects stale results. Each Activation read emits a debug diagnostic with the GitHub API request count and cumulative client-observed latency; these metrics do not affect or skip evidence checks. Since parent #26 predates ADC pointer journals, the shared module obtains its pinned ADC digest and source declaration from the approved child #31 ADC and verifies the pinned migration-contract source. The Issue evidence comment remains editable/deletable GitHub storage: exact comment ID/body/actor/repository/subject are double-read, detected mutation blocks, and no intrinsic immutability is claimed. The dedicated parent-label migration remains read-only by default and mutates labels only under explicit `--apply`; parent delivery never applies it implicitly. After Integration PASS, parent User Review binds the ADC, six child merge pairs, and Integration result digest; approval never activates, closes, or merges the parent.

The CLI performs phase transitions only after re-reading the Issue and confirming its current labels. An in-scope request returns the same Issue to execution; an explicitly triaged new scope returns it to requirements. Finalize is a readback command and has no merge or close mutation. Parent final delivery remains blocked until child Integration and the separate parent review/activation gates are satisfied.
