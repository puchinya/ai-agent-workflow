<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Specification

- Status: Approved
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related design: [Workflow design](../design/workflow-design.md)
- Runtime contract: [Runtime specification](runtime-spec.md)

<!-- contents:start -->
**Contents**
- [1 Purpose](#1-purpose)
- [2 Scope](#2-scope)
- [3 Normative requirements](#3-normative-requirements)
  - [3.1 REQ-WF-001 Workflow phases](#31-req-wf-001-workflow-phases)
  - [3.2 REQ-WF-002 Host-managed implementation workspaces](#32-req-wf-002-host-managed-implementation-workspaces)
  - [3.3 REQ-WF-003 Authorization continuity and implementation handoff](#33-req-wf-003-authorization-continuity-and-implementation-handoff)
  - [3.4 REQ-WF-004 Skills](#34-req-wf-004-skills)
  - [3.5 REQ-WF-005 Review and delivery principles](#35-req-wf-005-review-and-delivery-principles)
- [4 REQ-WF-006 Observable behavior](#4-req-wf-006-observable-behavior)
- [5 REQ-WF-007 Error and boundary behavior](#5-req-wf-007-error-and-boundary-behavior)
- [6 REQ-WF-008 Security and privacy](#6-req-wf-008-security-and-privacy)
- [7 P-ASES migration Bootstrap gates](#7-p-ases-migration-bootstrap-gates)
- [8 P-ASES human review and final delivery](#8-p-ases-human-review-and-final-delivery)
  - [8.1 REQ-WF-009 Exact-subject User Review](#81-req-wf-009-exact-subject-user-review)
  - [8.2 REQ-WF-010 Parent Integration and Final Delivery](#82-req-wf-010-parent-integration-and-final-delivery)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [REQ-WF-001](#req-wf-001) — 3.1 REQ-WF-001 Workflow phases
- [REQ-WF-002](#req-wf-002) — 3.2 REQ-WF-002 Host-managed implementation workspaces
- [REQ-WF-003](#req-wf-003) — 3.3 REQ-WF-003 Authorization continuity and implementation handoff
- [REQ-WF-004](#req-wf-004) — 3.4 REQ-WF-004 Skills
- [REQ-WF-005](#req-wf-005) — 3.5 REQ-WF-005 Review and delivery principles
- [REQ-WF-006](#req-wf-006) — 4 REQ-WF-006 Observable behavior
- [REQ-WF-007](#req-wf-007) — 5 REQ-WF-007 Error and boundary behavior
- [REQ-WF-008](#req-wf-008) — 6 REQ-WF-008 Security and privacy
- [REQ-WF-009](#req-wf-009) — 8.1 REQ-WF-009 Exact-subject User Review
- [REQ-WF-010](#req-wf-010) — 8.2 REQ-WF-010 Parent Integration and Final Delivery
<!-- heading-map:end -->


<a id="purpose"></a>
## 1 Purpose

Define the reusable development workflow shared by OpenAI/Codex, Claude Code, and Google Antigravity 2.0. The product provides workflow behavior and deterministic local tools; it does not scaffold application source or synchronize projects with another repository.

<a id="scope"></a>
## 2 Scope

The repository owns ten Skills, shared standards and templates, application profiles, implementation-contract handling, evidence and checkpoints, self-review, independent PR review, QA, PR delivery, project-profile routing, deterministic validation, and host-specific packages. Canonical reusable documents under `workflow/templates/` include specification/design/status templates, a ten-section Implementation Contract starting point, and one portable Chat project-instructions body. A consumer project owns its source, `.agent/project.json`, Issue-specific documents, hooks, and verification commands.

The product does not own a service, database, daemon, GUI, project-template repository, source synchronization, automatic semantic document rewriting, stack-wide detectors, or existing-consumer migration.

<a id="normative-requirements"></a>
## 3 Normative requirements

<a id="req-wf-001"></a>
<a id="req-wf-001-workflow-phases"></a>
### 3.1 REQ-WF-001 Workflow phases

The shared Issue lifecycle is exactly:

`requirements -> design -> ready -> implementation -> review -> closed`

An Issue is the authority for a work item. Repository-changing work begins from an owning Issue, one feature branch, an approved decision-complete Implementation Contract, and linked specification/design owners when durable behavior changes. No implementation begins before the contract and Reviewer Checklist are available on the Issue.

Requirements, specifications, design, code/tests, and status/evidence have distinct owners and must agree in the final result. The workflow imposes no chronology for creating or editing those artifacts. A material decision change requires the owning documents and dependent implementation to reflect the approved final decision. One document owns each durable rule; other documents link to it instead of copying its policy.

Every new durable work item records explicit specification, design, and status decisions in the Issue's `## Document impact` section. Link decisions point into the matching `docs/specs/`, `docs/design/`, or `docs/status/` tree; unchanged decisions and evidence-only status decisions include a reason. Requirements and design establish these decisions, implementation re-evaluates them against the final diff, and self-review checks final alignment. An unchanged or evidence-only decision does not require creating a document.

Feature work uses `python -m agent_workflow start-feature-branch <issue> <description...>` after its open Issue and project profile are validated. The runtime derives a deterministic `<prefix>/<issue>-<slug>` branch name, checks the worktree, and performs cleanup and global `branch_switch` hooks only after an actual branch switch. Repeating the command on the current target branch performs no cleanup or hooks.

<a id="req-wf-002"></a>
<a id="req-wf-002-host-managed-implementation-workspaces"></a>
### 3.2 REQ-WF-002 Host-managed implementation workspaces

Publishing, reviewing, or approving an Implementation Contract does not allocate a workspace. Execution of the approved Contract is the trigger. The normal user request remains “Implement this Contract”; the Skill reads the Schema 2 `workspace.isolation` policy before edits and lets the active host establish or reuse isolation.

For every new execution, after `agent-context` confirms that no valid binding exists and before host capability selection, the implementation Skill MUST run `python -m agent_workflow resolve-implementation-base ISSUE` (adding `--base-ref BRANCH` for a selected stacked base). The returned `base_ref` and `base_sha` are authoritative for host exact-base capability, host starting-ref selection, initial isolated HEAD verification, current-mode `start-feature-branch`, and `prepare-implementation`; current-mode setup passes both `--base-ref` and `--expected-base-sha`. Expected-SHA mismatch fails closed if the remote advances. Existing valid bindings skip resolution and reuse their frozen tuple without re-fetching a newer remote tip. Resolution permits a dirty current checkout, validates the approved execution authority and exact same-repository remote branch, and only fetches that branch; it creates no binding or workspace and performs no branch, hook, source, or GitHub mutation.

If a checkout already contains the open PR continuation for the same Issue but its local binding is missing, do not treat it as a normal new execution or re-resolve it onto the PR HEAD. The implementation Skill may run `recover-implementation-binding ISSUE PR --base-ref BRANCH --expected-base-sha SHA40` only when PR, local branch/HEAD, same-repository identity, current Contract, clean state, and exact base ancestry all verify. It creates a Schema 2 local continuation binding that records both the frozen base and verified PR checkpoint; then `prepare-implementation --supersede` validates the current approved Contract. Recovery fails closed on any mismatch and does not switch/create branches or worktrees, run hooks, or mutate GitHub. Normal new executions continue to use `resolve-implementation-base`.

- Before host isolation, resolve the selected same-repository base ref and its full SHA. For an already-bound execution, reuse its frozen `base_ref` and `base_sha`.
- Resume a valid binding in its existing workspace after commits without rerunning `start-feature-branch` or resolving the frozen SHA against a newer remote tip. `prepare-implementation` may validate reuse and explicit Contract supersession; it must not reinitialize the workspace.
- When a local binding is missing on an existing open PR continuation, use the narrowly scoped recovery command only after every PR/base/HEAD check succeeds. Recovery is current-mode only and is not a general way to bind an arbitrary checkout or substitute for the normal resolver.
- Native isolation is available only when the active host surface can create or reuse a workspace whose initial `HEAD` is exactly the selected base SHA. A host worktree feature alone does not satisfy this requirement. Verify the initial HEAD before `prepare-implementation`.
- `auto` prefers exact-base native isolation when available. Otherwise it uses the existing current-checkout branch flow with the same `base_ref` and expected SHA.
- `required` stops before edits when host-managed isolation at the exact selected base cannot be established.
- `disabled` does not request a new worktree and does not force a session already in a worktree back to the main checkout.

Codex uses its current surface's managed worktree or task-fork capability when exposed and selects the approved starting ref when supported; the resulting HEAD must equal the selected SHA. Claude Code reuses a valid worktree or enters one through native `EnterWorktree` only when it can preserve the exact selected base. For unsupported stacked/non-default bases, and any other unverified exact-base capability, `auto` falls back and `required` blocks. Do not create a wrong-base workspace and repair it by switching, resetting, merging, or rebasing. The runtime never invokes another coding-agent binary or runs raw automatic `git worktree add`; it does not manage host permissions, placement, resume, or cleanup and cannot prove session provenance.

Issue/PR identity remains the user's routing key. One implementation writer owns an execution, and ordinary follow-up answers or corrections reuse the same binding and workspace. A changed approved Contract blocks continuation until explicit supersession refreshes only its bound comment ID/SHA. This version does not add global task discovery, a database, daemon, Issue DAG scheduler, or parallelism setting.

`.worktreeinclude` may contain explicit project-owned patterns for local ignored files needed in host-created worktrees. The workflow never creates that file, infers secrets, or copies ignored files without an explicit pattern. Independent Review remains a fresh session, subagent, or human review and is not authored by the implementation execution.

When Claude Code uses its default in-repository `.claude/worktrees/` location, the consumer project owns ignoring that path in its root `.gitignore`. Custom in-repository locations require an ignore rule for their actual relative path; external locations need no rule for those files. The workflow documents this expectation but neither mutates ignore files nor performs generic ignore-path preflight/availability checks.

After an Issue exists, the requirements Skill runs `python -m agent_workflow ensure-milestone <issue>` unless an approved Issue contract explicitly names a target release, in which case it passes that unchanged value with `--target-version <version>`. Skills MUST NOT invent or infer a target version. Milestones follow the consumer profile's `auto`, `required`, or `disabled` mode. `disabled` always skips and cannot be overridden by a target. Otherwise an explicit target takes precedence over the repository version source; absent a target, the existing profile source applies. `auto` accepts an unresolved fallback as `NOT_APPLICABLE`; `required` fails closed when no fallback version can be resolved. Exact-title reuse is idempotent, and closed or duplicate milestones are never silently reopened or replaced. An Issue's existing Milestone is immutable through this command: a different current assignment fails without mutation.

<a id="req-wf-003"></a>
<a id="req-wf-003-authorization-continuity-and-implementation-handoff"></a>
### 3.3 REQ-WF-003 Authorization continuity and implementation handoff

Once a user authorizes execution of an approved Issue-scoped Implementation Contract, that authorization continues through the routine Issue-scoped mutations required to reach a review-ready PR: commit, non-force push, PR create/reuse and required title/body update, transition to `phase:review`, exact-HEAD Agent Self-Review publication, CI/Required Check reads, and the final delivery gate. Skills MUST NOT request a separate conversational confirmation solely for those operations. Host-enforced security prompts may still apply.

That authorization does not cover material scope or architecture changes, contract supersession, an ambiguous or conflicting owning Issue/base, force-push or branch deletion, merge, tag/release creation, publication outside the review PR workflow, credential or permission escalation, mutation of an unrelated Issue/PR, or an explicit user request to stop before PR creation. A conflict requiring one of these decisions blocks only the dependent work.

For an authorized contract, the implementation Skill owns the full sequence: `verify_quick` -> commit -> `ensure-review-pr` (safe non-force push and PR create/reuse) -> `verify-final` -> exact-HEAD self-review -> QA -> fresh-context independent PR review -> `delivery-check`. The implementation session MUST NOT author the independent review artifact; the `pr-review` Skill requires a new session/subagent or human. If that reviewer is unavailable, report the exact blocker with the review PR URL. The workflow MUST NOT claim runtime proof of fresh context or assume a host-specific session API. It MUST NOT report implementation complete before an open, non-draft review PR exists. Pending Required Checks are reported as `BLOCKED_DELIVERY_CHECKS_PENDING`; the review PR must already exist. Automatic merge is forbidden.

<a id="req-wf-004"></a>
<a id="req-wf-004-skills"></a>
### 3.4 REQ-WF-004 Skills

Canonical Skill source is `workflow/skills/`. It contains exactly these task areas:

1. `requirements` — elicit decisions and establish an Issue-owned contract.
2. `design` — create traceable specification and design documents.
3. `implementation-contract` — preserve, publish, restore, and verify approved contract bytes.
4. `implementation` — work from the approved Issue and scoped context.
5. `evidence` — record reproducible verification and unverified targets.
6. `checkpoint` — save and resume Issue-scoped progress.
7. `self-review` — review every approved contract section and every effective checklist item against evidence.
8. `pr-review` — review a change independently against its contract and current HEAD.
9. `qa` — record current-HEAD functional cases or a reasoned not-applicable result.
10. `delivery` — enforce PR handoff and merged-delivery gates.

Each Skill MUST have concise YAML frontmatter with `name` and `description`. Detailed shared policy belongs in standards or referenced resources. A Skill MUST state its trigger, expected inputs, ordered procedure, output, uncertainty behavior, and supporting resources where relevant. Skill copies in `dist/**` are generated.

The requirements Skill creates/validates the Issue first and then runs `ensure-milestone`, passing `--target-version` only when the approved Issue requirements explicitly supply it; it may continue after `NOT_APPLICABLE` only when the profile mode is `auto`. On approved Contract execution, the implementation Skill checks workspace policy, establishes/reuses host-managed isolation where available, starts the feature branch only in the allowed current-checkout path, and runs `prepare-implementation` before source edits. It preserves any approved target version unchanged through the implementation handoff.

New Implementation Contracts use `workflow/templates/implementation-contract-template.md` as a starting point. Before saving or publishing a new contract created from that template, the requirements and implementation-contract Skills run `python -m agent_workflow validate-implementation-contract-structure <issue> <path>`. This deterministic read-only preflight checks the required numbered H2 layout and filled authoring markers; it does not approve contract content or change the existing publication flow. Historical contracts are not retroactively gated. The Japanese `workflow/templates/chat-project-instructions-template.md` is a single copy/paste project-instructions body whose only repository-specific substitution is its top repository URL line; it does not claim capabilities supplied only by a host or plugin.

<a id="req-wf-005"></a>
<a id="req-wf-005-review-and-delivery-principles"></a>
### 3.5 REQ-WF-005 Review and delivery principles

Self-review is evidence, never approval. Review findings use these categories:

- A — Contract violation
- B — Contract ambiguity
- C — Newly discovered requirement
- D — Optional improvement

Category C is not implementer failure. An implementation is complete only through the PR delivery gate; passing tests alone is insufficient. A new PR commit invalidates review against an older HEAD. Missing or unavailable verification remains unverified and MUST NOT be reported as passing.

A self-review has two separate layers: Contract Conformance Review covers the complete approved Implementation Contract, and Reviewer Checklist Review covers every effective Contract/Issue checklist item. The Reviewer Checklist is a concise summary review surface, not a substitute for reading and checking the full approved contract. Both layers bind to the same exact PR HEAD, approved contract comment ID, and approved contract SHA.

Independent PR review is a separate public artifact bound to the same exact HEAD, contract, contract review units, and checklist. Its required `fresh_context: true` is a reviewer attestation only; runtime verifies the payload and binding but cannot prove who or which session authored it. A/B findings block delivery; D findings do not; each C finding states an explicit `blocking` value. Delivery also requires every independent contract unit to pass and no independent checklist item to fail. The implementation session cannot prepare, edit, validate as its own, or publish this artifact; a new session/subagent or human reviewer performs it.

QA is a separate record bound to current HEAD and contract. A `required` QA record has at least one completed test case with action, expected outcome, result, and concrete evidence. A `not_applicable` record has no cases and a concrete reason. Delivery accepts only all-PASS cases or N/A; failures, untested/pending cases, or stale records block. QA evidence does not substitute for self-review or independent review.

When saving or publishing a new contract, the runtime automatically canonicalizes a recognizable legacy Reviewer Checklist H2 before hashing. It preserves checkbox wording and order plus every byte outside that H2, inserts the required markers and approved introduction, and rejects ambiguous headings, malformed/missing items, or unrelated prose before GitHub mutation. The contract SHA binds the normalized exact bytes. This does not invalidate or rewrite already-approved historical contract bytes; restoration remains byte-for-byte. Historical checklist extraction keeps canonical-block precedence and the narrow-heading fallback; a legacy/non-canonical historical H2 remains included in contract-conformance coverage, while a strict-canonical H2 may be excluded. Self-review publication reads back the exact named comment after creation and verifies its PR association and body before any pointer update; this check is separate from the subsequent HEAD and contract race revalidation.

A current contract section or checklist item with `result: fail` blocks handoff even when Required Checks are green. Contract-section `untested` is valid evidence of an unresolved blocker and blocks handoff. Checklist-level `untested` remains valid, non-blocking evidence by itself; its evidence must identify the unavailable verification or residual uncertainty. A source/diff-reviewable contract section must not be marked `untested` to avoid checking it. Mandatory verification and configured Required Checks remain independent gates.

Final Verification is a machine-generated current-HEAD receipt. It requires a clean local worktree whose HEAD equals the full PR HEAD, runs Issue-routed final hooks, stores only command identities and hashes, and publishes an immutable receipt. A skipped target yields `partial`, and an empty plan yields `empty`; neither satisfies delivery. A passing receipt needs at least one executed command and no skipped target. This gate is independent from Required Checks.

Schema-v1 public self-reviews may be read for diagnostics, but they do not establish full-contract conformance and cannot satisfy handoff. Delivery gives explicit guidance to regenerate and publish a schema-v2 review with the current workflow; historical comments are not rewritten automatically.

<a id="req-wf-006"></a>
<a id="req-wf-006-observable-behavior"></a>
## 4 REQ-WF-006 Observable behavior

The portable workflow routes agents from an owning Issue to its active phase, affected components, applicable application profiles, explicit document impact decisions and linked specification/design/status owners, relevant symbols and tests, and current diff. It does not require reading every standard or generated project summary by default. Skills describe when to load additional standards; they do not duplicate full policy text.

The consumer's explicit project profile is the machine authority for components, stacks, application types, targets, hooks, and branch/milestone policy. Application type, stack, target, and runtime host are independent concepts. Application type is never inferred from repository contents, stack, target, or host.

<a id="req-wf-007"></a>
<a id="req-wf-007-error-and-boundary-behavior"></a>
## 5 REQ-WF-007 Error and boundary behavior

| Condition | Required behavior |
|---|---|
| No owning Issue or no decision-complete contract | Stop repository-changing work and establish the missing Issue artifact first. |
| Material requirement conflict | Report the exact conflict and continue only with independent valid work. |
| Newly discovered category-C requirement | Record it for explicit triage; do not silently treat it as implementer failure or rewrite the approved scope. |
| Unavailable platform, tool, credential, or CI result | Record it as unverified and identify the concrete blocker. |
| Authorized implementation has no review PR | Continue through the deterministic PR-establishment command without a second conversational approval. |
| PR establishment or phase transition fails | Report the precise blocker; a PR created before a phase failure is identified for an idempotent retry. |
| Required Checks remain pending after PR creation | Report `BLOCKED_DELIVERY_CHECKS_PENDING`; do not report implementation complete. |
| Submitted self-review without matching evidence | Treat it as a claim to check, never as proof. |

<a id="req-wf-008"></a>
<a id="req-wf-008-security-and-privacy"></a>
## 6 REQ-WF-008 Security and privacy

The workflow never prints or stores credentials in contract payloads, logs, Skills, generated packages, or PR evidence. Local hooks are trusted explicit commands, not a sandbox. Network-backed operations fail closed on uncertain ownership, identity, authorization, or state.

<a id="p-ases-migration-bootstrap-gates"></a>
## 7 P-ASES migration Bootstrap gates

The migration from the legacy workflow to P-ASES uses two separately named gates. The fixed Bootstrap cohort is parent Issue #26 and child Issues #27–#32 **in `puchinya/ai-agent-workflow` only**. Repository identity is compared case-insensitively. Those child Issues use `bootstrap-legacy-v1`; no label, issue text, caller flag, or agent decision can add another Issue or repository to that set. Existing non-cohort Issues created before activation remain on the existing legacy workflow and are never migrated automatically. Only a non-cohort Issue created after the verified activation timestamp selects `p-ases-v1`; missing or invalid activation and pre-activation Issues are `UNDETERMINED` in the new router, which never falls back automatically.

Bootstrap reports `BOOTSTRAP_TECHNICAL_READY` or `BOOTSTRAP_BLOCKED` for the fixed migration cohort only. Technical readiness requires the current approved child ADC, exact open/non-draft same-repository PR and current HEAD, standalone `Closes #N`, a clean checkout, executed local tests/static/distribution checks, successful current-head required GitHub CI jobs with provenance, fixed gate selection and evaluator digest, and explicit unverified-environment disclosure. Self-review, independent review, review artifacts, ordinary `PASES_REVIEW_READINESS_V1: PASS`, GitHub approval, and final User Review are not Bootstrap prerequisites. Technical readiness does not claim any of those reviews occurred or passed, does not grant merge permission, and does not cause an Issue phase transition. The #27 legacy ADC approval state and the Issue dependency graph remain required technical gates; #28 acceptance remains a dependency.

<a id="p-ases-human-review-and-final-delivery"></a>
## 8 P-ASES human review and final delivery

<a id="req-wf-009"></a>
### 8.1 REQ-WF-009 Exact-subject User Review

Final human User Review begins only after Review Readiness is PASS for the same repository, Issue, PR, approved ADC digest, exact PR HEAD, and Readiness digest. An immutable session start time is created for that exact subject; a prior approval or change request cannot satisfy a newly started session. The runtime reads every page of Issue comments, PR conversation comments, formal PR reviews, and inline diff comments. It records numeric actor identity and type, object ID, creation/update times, body digest, formal review state, target commit, permalink, and deletion/resolution observations. Snapshot history is immutable so removed or edited feedback makes earlier approval evidence stale.

Only a current human identity can decide User Review. GitHub approval requires a formal `APPROVED` review on the exact current HEAD. A direct chat decision is eligible only through a host adapter that attests the current user, direct conversation, explicit decision, and absence of quoted or attached third-party content. A filesystem payload, bot event, PR existence, generic comment text, or unverifiable chat identity cannot approve. A PR conversation or inline comment requests in-scope changes only when its entire body has exactly these two lines:

```text
P-ASES-DECISION: CHANGES_REQUESTED
P-ASES-HEAD: <current full SHA-40>
```

The authenticated current human must have authored the comment; an inline comment's `commit_id` must equal the named SHA. Quoted, extended, malformed, stale-head, bot, unauthorized, and natural-language comments do not trigger the execution transition. Other comments remain questions. Changes requested on the current scope return the same Issue and PR to execution; a separately triaged scope change returns to requirements. Questions, pending reviews, unresolved discussion threads, stale HEAD/ADC/Readiness, and incomplete API reads remain blockers.

<a id="req-wf-010"></a>
### 8.2 REQ-WF-010 Parent Integration and Final Delivery

Parent Integration uses the declared native child Issue set and dependency DAG. It reads every child Issue, native blocker edge, merged PR, standalone child-closing line, actual merge commit, merge timestamp, and final-main ancestry from GitHub. Each dependency must have merged no later than its dependent child. The child set, dependency graph, current main SHA, parent ADC, and typed Integration Verification/Acceptance records form one immutable subject. For this migration, legacy parent Issue #26 has no ADC pointer journal; the current approved child #31 ADC is therefore the authority for the parent ADC digest and the immutable `planning/p-ases/08-migration-contract.md` source at commit `f34f166f11bbbe6c45b1555827f37f9467b1e49b`. The evaluator verifies that declaration and source availability, then double-reads the child ADC pointer and parent Issue body while collecting the Integration snapshot.

**Parent evidence authority decision for this migration:** the exact-main GitHub Actions run, job, step, and Check Run API records are authoritative. Issue #26 comments store only a discoverable pointer/cache for the reconstructed result; a comment by itself is never proof. This is the selected resolution to the Git self-reference conflict: execution proof stays outside the commit whose SHA it names, and a deleted or edited comment fails closed without falling back to local files or comment-authored PASS claims. Typed Verification and Acceptance evidence is published outside `main` in canonical `PASES_PARENT_GATE_EVIDENCE_COMMENT_V2` Issue comments on #26. `delivery parent-evidence <issue> <kind> <run-id>` reads a completed run for the exact current `main` SHA and reconstructs its result and artifact bytes from those API responses.

Verification must use the latest `.github/workflows/ci.yml` `push` run for the exact current `main` SHA, `head_branch=main`, same-repository `head_repository`, completed/success, and GitHub Actions App ID `15368`. The run must contain the four fixed Python/OS matrix jobs; each job Check Run URL must resolve to a completed/success Check Run from that App on the same SHA and same repository. The API job steps `Compile runtime, tools, and tests`, `Check committed distributions before mutation`, `Unit tests`, `Validate repository documentation`, `Generate distributions`, `Check generated distributions`, `Validate distributions`, `Confirm generated paths remain unchanged`, and `Check committed diff whitespace` must each be completed/success in every matrix job. A newer failed attempt or run invalidates an older success.

Acceptance must use the latest `.github/workflows/parent-integration.yml` `workflow_dispatch` run for the exact current `main` SHA and same-repository `main` branch, also completed/success from App ID `15368`. Its `parent-acceptance` job Check Run and six named steps prove specification traceability, design traceability, test-oracle traceability, the exact canonical 16-Skill package, generated-distribution consistency, and distribution validation. That workflow is dispatched only after the fixed migration cohort is present; it does not permit the legacy 10-Skill package to pass.

The result stores run ID/attempt/path, every required job Check Run identity, step conclusions, cited artifact bytes, and SHA-256 digests. On publication and every later read, the adapter re-fetches the latest matching workflow run, jobs, steps, and exact-SHA Check Runs, reconstructs the canonical V2 payload, and requires byte-for-byte equality. Thus a hand-authored result with plausible hashes, a local-only PASS, wrong App, stale SHA, failed/skipped step, incomplete matrix, or superseded run is BLOCKED even when posted by the authenticated user.

This boundary avoids storing a commit's own SHA inside that commit. `delivery parent` and `issue integration-check` require exact Issue #26 comment IDs. For each ID, the reader GETs the comment, finds that same ID exactly once in Issue #26's paginated comment list, GETs it again, and compares ID, body, timestamps, Issue/API/HTML URLs, and author. It also requires exactly one evidence comment for each kind and current parent/main subject. `updated_at` must equal `created_at`; the current authenticated GitHub `User` ID must equal the comment author; the workflow provenance, payload subject, canonical bytes, result digest, artifact digests, and fixed check set must all match. A deleted ID, edit, duplicate subject, wrong repository/Issue, wrong author, malformed payload, changed ADC, stale main, failed/superseded run, or untrusted App blocks without fallback. GitHub comments can be edited or deleted, so this detects mutations at each read; it does not claim GitHub provides immutable comment storage.

Legacy parent #26 labels are migrated only by `delivery parent-migrate-labels 26`. Default invocation is read-only preflight: the Issue must be open in the same repository, and any conflicting kind/phase blocks. `--apply` re-reads the exact current labels, creates only the P-ASES-owned definitions needed for `kind:parent`, `phase:integration`, and the next `phase:user-review` transition when absent, and verifies each definition's exact name, description, and color. The owned definitions are `kind:parent` (`c5def5`, `P-ASES Issue kind: parent`), `phase:integration` (`0e8a16`, `Workflow phase: integration`), and `phase:user-review` (`d93f0b`, `Workflow phase: user review`). Existing definitions with different metadata fail without overwrite. It then adds only the needed parent/Integration labels, preserves unrelated labels such as `enhancement` and attention labels, and confirms the complete Issue state. A lost definition or Issue-label write response is retried by re-reading and recognizing the exact prior write; conflicting or incomplete states fail closed. Parent delivery does not run this migration implicitly.

After Integration passes, `delivery parent` moves parent Issue #26 from `phase:integration` to `phase:user-review` and starts one immutable parent review session. Its exact subject binds the repository, parent Issue, approved parent ADC digest, six child Issue/merge-SHA pairs, and Integration result digest. The first invocation starts the session; a decision must be a new parent Issue comment with exactly these two lines:

```text
P-ASES-DECISION: APPROVED
P-ASES-SUBJECT: <current parent User Review SHA-256>
```

`CHANGES_REQUESTED` may be used in the first line to withhold parent approval. Only the authenticated current human on the open parent Issue can decide. Edited/deleted comments, a decision predating the session, or a changed ADC, child merge, or Integration subject invalidates prior approval. Child User Review snapshot discovery accepts only `<64 lowercase hex>.json` filenames, verifies that the filename digest equals the parsed snapshot digest, and rejects unexpected files; `session.json` and `*.result.json` are not feedback snapshots. Parent approval only makes the result ready for a separate explicit activation decision; it does not close or activate the parent or authorize merge/release.

Final Delivery keeps human User Review, GitHub's required formal review decision, exact-HEAD Required Check evidence, branch protection, explicit merge authorization, merge readback, Issue closure, and parent activation as separate gates. A delivery result never performs a merge, release, Issue close, or parent activation. Finalization only reports what GitHub confirms after a separately authorized merge.

Gate selection is recorded immutably when work starts and remains fixed if the PR HEAD changes or a check becomes blocked. `p-ases-v1` applies only to Issues created after activation. Activation requires all six child PRs to be merged by the repository owner with explicit user authorization, all six Issues closed, parent integration documentation/tests/16 Skills/distribution checks passing, and an explicit activation approval comment authored by the repository owner. A unique `PASES_ACTIVATION_V1` record binds the repository, child Issues and PR merge SHAs, integration-evidence digest, gate version, and activation commit. Missing, stale, duplicated, or mismatched activation evidence blocks new P-ASES work.

Bootstrap evidence remains append-only and binds its exact ADC, PR, HEAD, CI, local checks, blockers, and a digest of the Bootstrap evaluator and trusted adapters. New results set `review_mode` to `WAIVED_BOOTSTRAP`, use `BOOTSTRAP_TECHNICAL_READY` for success, leave reviewer/context IDs null, review evidence empty, `separate_context_confirmed` false, and `can_request_final_user_review` false. Historical `BOOTSTRAP_REVIEW_READY` records remain readable with their original meaning and are never promoted automatically. The clean checkout is rechecked after local tests, after GitHub technical evidence collection, and before publication. Before and after publication the evaluator re-reads the complete ADC pointer, pinned gate selection, PR number/state/draft, base/head repository/ref/SHA, and full body including the exact standalone Issue-closing line. If any subject field changes after publication, a newer `BOOTSTRAP_BLOCKED` observation is appended and read back as the latest record. Tool changes append a new attempt without changing the pinned Issue gate; changes to the subject or evidence invalidate the previous result. The normal Delivery Readiness gate, trusted Required Check App-ID verification, phase transitions, review requirements for ordinary P-ASES issues, and separate explicit permission for PR merge remain unchanged.

The Bootstrap evaluator may live on a downstream PR while an earlier stacked PR is being evaluated. Run its CLI from the evaluator checkout, with `--root` set to a separate clean checkout of the target PR at its exact current HEAD. The evaluator code and fingerprint come from the evaluator checkout; local checks and branch/HEAD cleanliness checks run against the target checkout. Never copy downstream evaluator changes into the target branch or claim a result for a target HEAD different from the PR's current GitHub HEAD.

When migrating a legacy Issue-body ADC pointer to the append-only journal, retain the original `## Agent Development Contract` pointer block unchanged. The first journal record names the old pointer Comment ID as its predecessor (or `none` if there was no old pointer). Do not remove or edit that anchor unless a separately approved migration format records its exact prior bytes and predecessor.
