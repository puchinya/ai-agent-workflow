<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Specification

- Status: Existing content approved; REQ-F01-014 and REQ-F01-015 are drafts pending Issue #63 successor ADC approval and phase evidence.
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
- [9 Consumer Activation workflow contract](#9-consumer-activation-workflow-contract)
  - [9.1 REQ-F01-001 Repository boundary](#91-req-f01-001-repository-boundary)
  - [9.2 REQ-F01-003 Append-only approval and Activation history](#92-req-f01-003-append-only-approval-and-activation-history)
  - [9.3 REQ-F01-005 Eligibility by Activation time](#93-req-f01-005-eligibility-by-activation-time)
  - [9.4 REQ-F01-007 Successor Activation](#94-req-f01-007-successor-activation)
  - [9.5 REQ-F01-008 Verified V2 Activation policy](#95-req-f01-008-verified-v2-activation-policy)
  - [9.6 REQ-F01-009 Approved Ruleset management](#96-req-f01-009-approved-ruleset-management)
  - [9.7 REQ-F01-010 Existing Issue preservation](#97-req-f01-010-existing-issue-preservation)
  - [9.8 REQ-F01-011 V2 effective time](#98-req-f01-011-v2-effective-time)
  - [9.9 REQ-F01-012 Activation history prefix](#99-req-f01-012-activation-history-prefix)
  - [9.10 REQ-F01-013 Bootstrap and review gates](#910-req-f01-013-bootstrap-and-review-gates)
  - [9.11 REQ-F01-014 Activation-scoped temporary admin authentication](#911-req-f01-014-activation-scoped-temporary-admin-authentication)
  - [9.12 REQ-F01-015 Owner-authorized relay decisions and separated operations](#912-req-f01-015-owner-authorized-relay-decisions-and-separated-operations)
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
- [REQ-F01-001](#req-f01-001) — 9.1 REQ-F01-001 Repository boundary
- [REQ-F01-003](#req-f01-003) — 9.2 REQ-F01-003 Append-only approval and Activation history
- [REQ-F01-005](#req-f01-005) — 9.3 REQ-F01-005 Eligibility by Activation time
- [REQ-F01-007](#req-f01-007) — 9.4 REQ-F01-007 Successor Activation
- [REQ-F01-008](#req-f01-008) — 9.5 REQ-F01-008 Verified V2 Activation policy
- [REQ-F01-009](#req-f01-009) — 9.6 REQ-F01-009 Approved Ruleset management
- [REQ-F01-010](#req-f01-010) — 9.7 REQ-F01-010 Existing Issue preservation
- [REQ-F01-011](#req-f01-011) — 9.8 REQ-F01-011 V2 effective time
- [REQ-F01-012](#req-f01-012) — 9.9 REQ-F01-012 Activation history prefix
- [REQ-F01-013](#req-f01-013) — 9.10 REQ-F01-013 Bootstrap and review gates
- [REQ-F01-014](#req-f01-014) — 9.11 REQ-F01-014 Activation-scoped temporary admin authentication
- [REQ-F01-015](#req-f01-015) — 9.12 REQ-F01-015 Owner-authorized relay decisions and separated operations
<!-- heading-map:end -->


<a id="purpose"></a>
## 1 Purpose

Define the reusable development workflow shared by OpenAI/Codex, Claude Code, and Google Antigravity 2.0. The product provides workflow behavior and deterministic local tools; it does not scaffold application source or synchronize projects with another repository.

<a id="scope"></a>
## 2 Scope

The repository owns exactly 16 canonical Skills, shared standards and templates, ADC and Issue workflows, immutable verification and acceptance evidence, audit and user review, delivery gates, project/context readback, deterministic documentation validation, and host-specific packages. The current public CLI uses the `project`, `context`, `adc`, `issue`, `docs`, `work`, `pr`, `verification`, `acceptance`, `audit`, `user-review`, and `delivery` namespaces. A consumer project owns its source, `.agent/project.json`, Issue-specific artifacts, and verification commands.

The product does not own a service, database, daemon, GUI, project-template repository, source synchronization, automatic semantic document rewriting, stack-wide detectors, or existing-consumer migration.

Legacy note: the historical procedures retained in Section 3 are reference material only, except for the current Skill inventory in §3.4. Retired flat CLI commands and the ten-Skill workflow are superseded by the current P-ASES route table and canonical Skill source under `workflow/skills/`.

<a id="normative-requirements"></a>
## 3 Normative requirements

<a id="req-wf-001"></a>
<a id="req-wf-001-workflow-phases"></a>
### 3.1 REQ-WF-001 Workflow phases

Single and child Issues use `requirements -> [specification] -> [design] -> ready -> execution -> verification -> user-review -> closed`. Specification is required when observable product behavior is being decided or changed; design is required when a material technical decision is being made. Each omitted phase has its own explicit reason. The only skip edges are `requirements -> design`, `specification -> ready`, and `requirements -> ready` (the last requires separate specification and design reasons). The parent lifecycle is separate: `requirements -> ready -> execution -> integration -> user-review -> closed`.

The current `kind:*` Issue label is the source of Issue kind, and each open Issue has exactly one `phase:*` label and at most one `attention:*` label. A new child Issue is created with `kind:child` and `phase:requirements`; existing phases are never reset. Parent #26 and fixed Bootstrap Issues #27–#32 retain their migration treatment and are not rewritten by the normal lifecycle gate. `closed` describes the actual closed GitHub Issue after separately authorized merge; it is not a GitHub `phase:closed` label.

An Issue is the authority for a work item. Repository-changing work begins from an owning Issue, one dedicated feature branch, its frozen work binding, and its current approved ADC. The ADC scopes the work; it does not replace product specifications, design, or independent tests. The approved ADC is the approval authority for the decisions recorded in it. A phase decision comment is only a technical receipt bound to that ADC generation, the actual Issue kind, frozen base/branch/worktree, branch commit, document bytes, and any independent skip reasons.

The supported `ExecutionBinding` format is strict: each binding row contains the current nine fields, including `branch_ref`; the append-only history wrapper contains rows in that same format. An older eight-field row is outside the supported contract and may be rejected by read/resume commands. Callers must not assume compatibility, branch inference, migration, or automatic rewrite.

At a specification, design, or ready boundary, the runtime records a canonical `PASES_PHASE_DECISION_V1` Issue comment. Its payload binds the repository and Issue, verified kind and phase pair, approved ADC comment ID and digest (the receipt generation), branch ref and commit SHA, sorted document role/path/SHA-256 entries, and explicit skip reasons. The frozen execution binding must match the Issue, repository, ADC, dedicated branch, base, and worktree; current HEAD must descend from its frozen base. A new approved ADC generation appends a binding record without changing that frozen tuple. Each transition validates only the artifacts needed through that stage: specification validates its declared specification; design validates its declared design and the completed specification receipt/artifacts when specification was not skipped; ready validates the required prior receipt chain plus the declared specification/design/test-Oracle artifacts. A document digest is read from a regular file in the branch commit tree and checked against its bytes; uncommitted working-tree content is not evidence. Before `ready`, the approved ADC must declare test impact; each requirement must resolve through `REQ`, `DES`, `ORA`, and `TST` links whose canonical targets exist in that same commit, contain the linked anchors, and match the ADC impact or an explicit unchanged decision; every linked executable test source must also exist in that commit. The test source may be an intentionally failing scaffold: `ready` verifies its committed identity and path, not a passing test result. The test case and independent Oracle are fixed before `ready`; execution may implement or extend the source, and verification determines whether it passes. If the source file is absent at `ready`, the transition remains blocked. Changing a completed specification or design blocks dependent transitions until the work returns to requirements with a newly approved ADC generation. Missing, edited, stale, duplicate, non-canonical, or mismatched evidence blocks without changing Issue labels. Every ordinary single/child phase-label transition verifies the actual Issue kind, approved ADC, and current Activation/Gate Selection. Entering execution from ready also rebuilds and rereads the current ready receipt and frozen binding. Comment readback consists of two complete direct/list/direct snapshots with exact Issue, HTML, and API URLs; label writes are read back against the complete intended label set, and an ambiguous race fails closed.

Requirements, specifications, design, code/tests, and status/evidence have distinct owners and must agree in the final result. A material decision change updates its owning documents and dependent implementation before work proceeds. One document owns each durable rule; other documents link to it instead of copying policy.

Every new durable work item records explicit specification, design, testing, and status decisions in the approved ADC's `## Artifact impact` section. Create/update decisions name paths under the corresponding `docs/specs/`, `docs/design/`, or `docs/testing/` tree; unchanged or not-applicable decisions include a reason. A reason for skipping a specification or design phase must agree with the matching approved ADC decision. Feature work uses the `work` namespace's exact-base, branch, bind, and recover operations after the owning Issue and approved ADC are validated. The frozen execution identity is the Issue, repository, ADC generation, base ref/SHA, dedicated branch ref, worktree, and initial HEAD. Phase-bound specification and test artifacts are authored on this bound branch before their phase receipts are published.

<a id="req-wf-002"></a>
<a id="req-wf-002-host-managed-implementation-workspaces"></a>
### 3.2 REQ-WF-002 Host-managed implementation workspaces

Publishing, reviewing, or approving an Implementation Contract does not allocate a workspace. Execution of the approved Contract is the trigger. The normal user request remains “Implement this Contract”; the Skill reads the Schema 2 `workspace.isolation` policy before edits and lets the active host establish or reuse isolation.

Before phase-bound artifact work or implementation, `context show` reads the current approved ADC and existing binding; `work base` resolves an exact base; `work branch` and `work bind` establish the frozen execution identity, including the dedicated Issue branch. Existing bindings are reused only when their Issue, repository, ADC generation, base, branch, worktree, and HEAD ancestry invariants still match. An explicitly reapproved ADC generation is appended to the binding history while retaining the original base, branch, worktree, and initial HEAD.

For a verified existing continuation, `work recover` restores a binding only after the exact Issue, ADC, PR, base, branch, and HEAD tuple is checked. It fails closed on mismatch and does not switch branches, create worktrees, or mutate GitHub.

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

P-ASES exposes no public milestone command. Skills must not infer or mutate milestones through a hidden or retired CLI route.

<a id="req-wf-003"></a>
<a id="req-wf-003-authorization-continuity-and-implementation-handoff"></a>
### 3.3 REQ-WF-003 Authorization continuity and implementation handoff

Once a user authorizes execution of an approved Issue-scoped Implementation Contract, that authorization continues through the routine Issue-scoped mutations required to reach a review-ready PR: commit, non-force push, PR create/reuse and required title/body update, transition to `phase:review`, exact-HEAD Agent Self-Review publication, CI/Required Check reads, and the final delivery gate. Skills MUST NOT request a separate conversational confirmation solely for those operations. Host-enforced security prompts may still apply.

That authorization does not cover material scope or architecture changes, contract supersession, an ambiguous or conflicting owning Issue/base, force-push or branch deletion, merge, tag/release creation, publication outside the review PR workflow, credential or permission escalation, mutation of an unrelated Issue/PR, or an explicit user request to stop before PR creation. A conflict requiring one of these decisions blocks only the dependent work.

The current handoff is owned by `verification`, `acceptance`, `audit`, `pr`, `delivery`, and `user-review` routes as appropriate to the artifact. Evidence is bound to exact subjects and read back before acceptance. User Review is a separate recorded gate. The implementation context does not author independent-review evidence. The workflow does not claim runtime proof of fresh context and does not merge or release automatically.

<a id="req-wf-004"></a>
<a id="req-wf-004-skills"></a>
### 3.4 REQ-WF-004 Skills

Canonical Skill source is `workflow/skills/`. It contains exactly these 16 task areas:

1. `request-intake`
2. `adc-authoring`
3. `adc-registry`
4. `issue-decomposition`
5. `product-specification`
6. `technical-design`
7. `test-specification`
8. `work-execution`
9. `verification-evidence`
10. `acceptance-validation`
11. `contract-audit`
12. `independent-review`
13. `user-review`
14. `integration-validation`
15. `delivery-control`
16. `work-checkpoint`

Each Skill MUST have concise YAML frontmatter with `name` and `description`. Detailed shared policy belongs in standards or referenced resources. A Skill MUST state its trigger, expected inputs, ordered procedure, output, uncertainty behavior, and supporting resources where relevant. Skill copies in `dist/**` are generated.

Skills route work through the public namespaces above. ADC Skills preserve exact approved bytes and verify named-comment readback; Issue Skills validate dependencies and parent integration; work Skills freeze base and binding identity; verification and acceptance Skills bind results to declared subjects; delivery Skills re-read all required gates; user-review records the separate user decision. Mutations require the authority defined by the approved ADC and remain limited to the named repository and Issue/PR.

ADC authoring and registry instructions define current ADC payload structure, validation, publication, exact comment readback, and supersession. Historical Implementation Contract artifacts remain historical evidence and do not define the current P-ASES command surface. The portable Chat project-instructions template describes only capabilities available to the active host or plugin.

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
<a id="req-wf-009-exact-subject-user-review"></a>
### 8.1 REQ-WF-009 Exact-subject User Review

Final human User Review begins only after Review Readiness is PASS for the same repository, Issue, PR, approved ADC digest, exact PR HEAD, and Readiness digest. An immutable session start time is created for that exact subject; a prior approval or change request cannot satisfy a newly started session. The runtime reads every page of Issue comments, PR conversation comments, formal PR reviews, and inline diff comments. It records numeric actor identity and type, object ID, creation/update times, body digest, formal review state, target commit, permalink, and deletion/resolution observations. Snapshot history is immutable so removed or edited feedback makes earlier approval evidence stale.

Only a current human identity can decide User Review. A formal GitHub `APPROVED` review is valid only when it is authored by an eligible reviewer on the exact current HEAD; a PR author cannot approve their own PR. A direct chat decision is eligible only through a host adapter that attests the current user, direct conversation, explicit decision, and absence of quoted or attached third-party content. For a self-authored PR in explicitly selected `solo_owner` mode, an approved Issue-specific relay contract may instead use a dedicated `PASES_USER_REVIEW_DECISION_V1` record appended to the same Issue by the authenticated GitHub owner relay, after exact subject readback and a separate direct `USER_REVIEW` confirmation. The canonical JSON has exactly `schema, repository, issue_number, pr_number, decision, owner_id, review_session_id, readiness_sha256, adc_sha256, pr_head_sha40, evidence_channel, predecessor_comment_id`; `decision` is `APPROVED` and `evidence_channel` is `delegated_github_relay`. `review_session_id` equals the immutable `PASES_USER_REVIEW_SESSION_V1.session_sha256`. The record binds repository, Issue, PR, stable owner ID, review session, Readiness digest, exact PR HEAD, approved ADC digest, and predecessor comment; its GitHub actor must be the same stable owner ID and its timestamp must follow the session start. It is read back and accepted once for that session by the User Review evaluator. It is a GitHub owner decision record, not a formal PR approval, host-attested chat event, or `PASES_OWNER_DECISION_V1`; it cannot satisfy independent review or PR merge authorization. The implementation runtime has no relay write credential or write-capable connector route; the separately mediated ChatGPT relay owns that capability. If this execution/permission boundary cannot be verified, the relay operation blocks. The runtime still verifies the record's actor, schema, exact subject, complete feedback snapshot, and resolved threads. A filesystem payload, bot event, PR existence, generic comment text, stale or replayed record, or unverifiable chat identity cannot approve.

For this carrier, the verifier accepts a validated `UserReviewSession` object, not a caller-supplied session digest alone. It verifies the full Issue comment history with complete pagination and direct/list/direct reads of every carrier record. The first carrier in the `(repository, issue, PR, owner ID)` chain has `predecessor_comment_id: null`; each later carrier must point to the immediately preceding valid carrier comment ID, with strictly increasing comment IDs. Orphaned, skipped, missing, edited, deleted, duplicated, or cross-session replayed links fail closed. The current carrier's `created_at` must be strictly later than `session.started_at`, and `updated_at` must equal `created_at`.

For every listed and direct-read carrier, the verifier MUST validate the GitHub comment's actual `url`, `issue_url`, and `html_url` against the configured API/web hosts, exact repository, Issue number, and comment ID. It MUST also compare these fields across direct/list/direct reads. A body-declared repository or Issue, or agreement among copies that all point to a different Issue/repository, MUST NOT satisfy origin verification.

The evaluator seam is `evaluate_user_review(session, readiness, current_pr_head_sha40, snapshot, *, review_mode, pr_author_user_id, repository_owner_user_id, authenticated_verifier_user_id, allowed_human_user_ids, relay_approval, all_feedback_surfaces_read, ...)`. The dedicated read-only GitHub client obtains `authenticated_verifier_user_id` from `GET /user`; this identifies the principal that performed the reads and may differ from the owner. Its read route must be separately scoped from broker writes, and that separation must be positively verified; if not, User Review fails closed. It grants no approval authority and is never compared to the carrier owner. `repository_owner_user_id` is the trusted owner ID pinned by the approved repository/Issue authority (for this #63 successor ADC draft, `3744776`); it is passed explicitly and is not inferred from `authenticated_verifier_user_id` or the relay credential. Before evaluation, the client must validate the configured stable repository ID and exact `full_name` against the fresh `GET /repos/{owner}/{repo}` response, including `owner.type=User` and `owner.id == repository_owner_user_id`; for this draft the repository ID is `1401910271`. Missing or changed repository metadata, a non-User repository owner, or any mismatch fails closed; the runtime must not dynamically adopt a changed repository owner. The current PR author ID comes from the fresh pull request's `user.id` and must equal `repository_owner_user_id`; the carrier's `owner_id` and GitHub comment actor ID must also equal it. `allowed_human_user_ids` comes from approved repository review policy, not from `/user` or the relay credential. A formal approval by the PR author is always rejected in `solo_owner`, even when that author is allowlisted; only the verified typed carrier can provide that approval. The evaluator consumes the exact `UserReviewSession`, complete `FeedbackSnapshot`, resolved-thread set, and the verifier's typed `UserReviewRelayApproval`. The verified carrier remains `user-review-relay` evidence and is never converted into a formal `pr-review`, host-attested `chat`, or generic Issue-comment approval. In the feedback snapshot, the carrier's exact Issue-comment row is matched by comment ID and body digest and excluded from generic question handling only after successful carrier verification; other later feedback, deletion tombstones, incomplete feedback surfaces, or unresolved threads still block or supersede it.

The selected relay approval is persisted in the User Review result as typed evidence containing the carrier comment ID, canonical body SHA-256, stable owner ID, creation time, session SHA-256, predecessor comment ID, and delegated evidence channel. The result record binds that evidence to the full feedback snapshot SHA-256 and exact User Review subject. A new `PASES_USER_REVIEW_RESULT_V2` result schema carries this field; existing V1 records remain immutable and cannot prove a relay approval. Both `sync` and Final Delivery re-fetch and verify the full carrier chain and feedback snapshot, then re-run the evaluator and require the same selected evidence and result. A direct/list/direct disagreement, incomplete page, or changed/deleted record blocks both paths.

A PR conversation or inline comment requests in-scope changes only when its entire body has exactly these two lines:

```text
P-ASES-DECISION: CHANGES_REQUESTED
P-ASES-HEAD: <current full SHA-40>
```

The authenticated current human must have authored the comment; an inline comment's `commit_id` must equal the named SHA. Quoted, extended, malformed, stale-head, bot, unauthorized, and natural-language comments do not trigger the execution transition. Other comments remain questions. Changes requested on the current scope return the same Issue and PR to execution; a separately triaged scope change returns to requirements. Questions, pending reviews, unresolved discussion threads, stale HEAD/ADC/Readiness, and incomplete API reads remain blockers.

<a id="req-wf-010"></a>
<a id="req-wf-010-parent-integration-and-final-delivery"></a>
### 8.2 REQ-WF-010 Parent Integration and Final Delivery

Parent Integration uses the declared native child Issue set and dependency DAG. It reads every child Issue, native blocker edge, merged PR, standalone child-closing line, actual merge commit, merge timestamp, and final-main ancestry from GitHub. Each dependency must have merged no later than its dependent child. The child set, dependency graph, current main SHA, parent ADC, and typed Integration Verification/Acceptance records form one immutable subject. For this migration, legacy parent Issue #26 has no ADC pointer journal; the current approved child #31 ADC is therefore the authority for the parent ADC digest and the immutable `planning/p-ases/08-migration-contract.md` source at commit `f34f166f11bbbe6c45b1555827f37f9467b1e49b`. The evaluator verifies that declaration and source availability, then double-reads the child ADC pointer and parent Issue body while collecting the Integration snapshot.

**Parent evidence authority decision for this migration:** the exact-main GitHub Actions run, job, step, and Check Run API records are authoritative. Issue #26 comments store only a discoverable pointer/cache for the reconstructed result; a comment by itself is never proof. This is the selected resolution to the Git self-reference conflict: execution proof stays outside the commit whose SHA it names, and a deleted or edited comment fails closed without falling back to local files or comment-authored PASS claims. Typed Verification and Acceptance evidence is published outside `main` in canonical `PASES_PARENT_GATE_EVIDENCE_COMMENT_V2` Issue comments on #26. `delivery parent-evidence <issue> <kind> <run-id>` reads a completed run for the exact current `main` SHA and reconstructs its result and artifact bytes from those API responses.

New Verification evidence must use the latest `.github/workflows/ci.yml` `push` run and latest attempt for the exact current `main` SHA, `head_branch=main`, same-repository `head_repository`, completed/success, and GitHub Actions App ID `15368`. The run must contain the four fixed Python/OS matrix jobs; each job Check Run URL must resolve to a completed/success Check Run from that App on the same SHA and same repository. The API job steps `Compile runtime, tools, and tests`, `Check committed distributions before mutation`, `Unit tests`, `Validate repository documentation`, `Generate distributions`, `Check generated distributions`, `Validate distributions`, `Confirm generated paths remain unchanged`, and `Check committed diff whitespace` must each be completed/success in every matrix job. A newer failed attempt or run blocks new evidence publication.

New Acceptance evidence must use the latest `.github/workflows/parent-integration.yml` `workflow_dispatch` run and latest attempt for the exact current `main` SHA and same-repository `main` branch, also completed/success from App ID `15368`. Its `parent-acceptance` job Check Run and six named steps prove specification traceability, design traceability, test-oracle traceability, the exact canonical 16-Skill package, generated-distribution consistency, and distribution validation. That workflow is dispatched only after the fixed migration cohort is present; it does not permit the legacy 10-Skill package to pass.

The result stores run ID/attempt/path, every required job Check Run identity, step conclusions, cited artifact bytes, and SHA-256 digests. On publication and current Integration reads, the adapter re-fetches the latest matching workflow run and attempt, jobs, steps, and exact-SHA Check Runs, reconstructs the canonical V2 payload, and requires byte-for-byte equality. When validating an already-issued Activation, it instead pins the run ID and attempt stored in that Activation's V2 evidence comment and fetches that exact attempt plus its jobs from the GitHub Actions attempt API. It verifies the run still has the recorded workflow, event, repository, branch, and activation SHA and reconstructs every job, step, and Check Run from that attempt. A later run or attempt does not invalidate this historical evidence. If GitHub cannot return the pinned attempt or any provenance record is incomplete, changed, or unsuccessful, validation is BLOCKED; there is no fallback to comments or cached PASS data. A hand-authored result with plausible hashes, a local-only PASS, wrong App, stale SHA, failed/skipped step, or incomplete matrix is BLOCKED even when posted by the authenticated user.

This boundary avoids storing a commit's own SHA inside that commit. `delivery parent` and `issue integration-check` require exact Issue #26 comment IDs. For each ID, the reader GETs the comment, finds that same ID exactly once in Issue #26's paginated comment list, GETs it again, and compares ID, body, timestamps, Issue/API/HTML URLs, and author. It also requires exactly one evidence comment for each kind and current parent/main subject. `updated_at` must equal `created_at`; the current authenticated GitHub `User` ID must equal the comment author; the workflow provenance, payload subject, canonical bytes, result digest, artifact digests, and fixed check set must all match. A deleted ID, edit, duplicate subject, wrong repository/Issue, wrong author, malformed payload, changed ADC, stale main, failed/superseded run, or untrusted App blocks without fallback. GitHub comments can be edited or deleted, so this detects mutations at each read; it does not claim GitHub provides immutable comment storage.

Legacy parent #26 labels are migrated only by `delivery parent-migrate-labels 26`. Default invocation is read-only preflight: the Issue must be open in the same repository, and any conflicting kind/phase blocks. `--apply` re-reads the exact current labels, creates only the P-ASES-owned definitions needed for `kind:parent`, `phase:integration`, and the next `phase:user-review` transition when absent, and verifies each definition's exact name, description, and color. The owned definitions are `kind:parent` (`c5def5`, `P-ASES Issue kind: parent`), `phase:integration` (`0e8a16`, `Workflow phase: integration`), and `phase:user-review` (`d93f0b`, `Workflow phase: user review`). Existing definitions with different metadata fail without overwrite. It then adds only the needed parent/Integration labels, preserves unrelated labels such as `enhancement` and attention labels, and confirms the complete Issue state. A lost definition or Issue-label write response is retried by re-reading and recognizing the exact prior write; conflicting or incomplete states fail closed. Parent delivery does not run this migration implicitly.

After Integration passes, `delivery parent` moves parent Issue #26 from `phase:integration` to `phase:user-review` and starts one immutable parent review session. Its exact subject binds the repository, parent Issue, approved parent ADC digest, six child Issue/merge-SHA pairs, and Integration result digest. The first invocation starts the session; a decision must be a new parent Issue comment with exactly these two lines:

```text
P-ASES-DECISION: APPROVED
P-ASES-SUBJECT: <current parent User Review SHA-256>
```

`CHANGES_REQUESTED` may be used in the first line to withhold parent approval. Only the authenticated current human on the open parent Issue can decide. Edited/deleted comments, a decision predating the session, or a changed ADC, child merge, or Integration subject invalidates prior approval. Child User Review snapshot discovery accepts only `<64 lowercase hex>.json` filenames, verifies that the filename digest equals the parsed snapshot digest, and rejects unexpected files; `session.json` and `*.result.json` are not feedback snapshots. Parent approval only makes the result ready for a separate explicit activation decision; it does not close or activate the parent or authorize merge/release.

Final Delivery keeps human User Review, GitHub's required formal review decision, exact-HEAD Required Check evidence, branch protection, explicit merge authorization, merge readback, Issue closure, and parent activation as separate gates. A delivery result never performs a merge, release, Issue close, or parent activation. Finalization only reports what GitHub confirms after a separately authorized merge.

Gate selection is recorded immutably when work starts and remains fixed if the PR HEAD changes or a check becomes blocked. `p-ases-v1` applies only to Issues created after activation. Activation requires all six child PRs to be merged by the repository owner with explicit user authorization, all six Issues closed, parent integration documentation/tests/16 Skills/distribution checks passing, and an explicit activation approval comment authored by the repository owner. A unique `PASES_ACTIVATION_V1` record binds the repository, child Issues and PR merge SHAs, integration-evidence digest, gate version, and activation commit.

Activation does not trust `PASES_INTEGRATION_EVIDENCE_V1` PASS fields, HTTPS references, or a caller-supplied digest by themselves. Its evidence references MUST identify exactly one parent Verification V2 comment and one parent Acceptance V2 comment, with the corresponding Actions run IDs and attempts. At issuance those references MUST be the latest successful matching run/attempt. On later Activation reads the runtime MUST pin the recorded run ID/attempt and reconstruct that exact historical attempt from GitHub's attempt-specific run and jobs APIs; a newer attempt or run MUST NOT replace it. Both pinned attempts MUST be successful on the activation commit SHA, use the approved parent ADC digest, and satisfy the fixed workflow, job, step, and trusted App ID 15368 requirements. If GitHub cannot return the exact attempt or its provenance, validation MUST fail closed. The six child Issues, PRs, and actual merge SHAs MUST match the Activation record and be present in that commit. Self-reported PASS fields, an HTTPS URL, or a digest without this API reconstruction cannot authorize Activation.

Activation approval, Activation record, and every referenced integration evidence comment MUST be unique, undeleted, authored by the repository owner’s stable GitHub User identity, attached to Issue #26, and unchanged since creation (`created_at == updated_at`). Each read MUST compare the direct comment, its unique Issue-list entry, and a second direct read using comment ID, body, timestamps, Issue/HTML/API URLs, and author ID/login/type. Profile and avatar fields are not part of this stable identity. Any edit, deletion, duplicate, author/identity mismatch, or readback failure MUST block the activation decision. The current default branch MUST contain the activation commit. After a valid activation, later main commits do not invalidate that historical record while its activation commit remains on main. Missing, stale, duplicated, or mismatched activation evidence blocks new P-ASES work.

Bootstrap evidence remains append-only and binds its exact ADC, PR, HEAD, CI, local checks, blockers, and a digest of the Bootstrap evaluator and trusted adapters. New results set `review_mode` to `WAIVED_BOOTSTRAP`, use `BOOTSTRAP_TECHNICAL_READY` for success, leave reviewer/context IDs null, review evidence empty, `separate_context_confirmed` false, and `can_request_final_user_review` false. Historical `BOOTSTRAP_REVIEW_READY` records remain readable with their original meaning and are never promoted automatically. The clean checkout is rechecked after local tests, after GitHub technical evidence collection, and before publication. Before and after publication the evaluator re-reads the complete ADC pointer, pinned gate selection, PR number/state/draft, base/head repository/ref/SHA, and full body including the exact standalone Issue-closing line. If any subject field changes after publication, a newer `BOOTSTRAP_BLOCKED` observation is appended and read back as the latest record. Tool changes append a new attempt without changing the pinned Issue gate; changes to the subject or evidence invalidate the previous result. The normal Delivery Readiness gate, trusted Required Check App-ID verification, phase transitions, review requirements for ordinary P-ASES issues, and separate explicit permission for PR merge remain unchanged.

The Bootstrap evaluator may live on a downstream PR while an earlier stacked PR is being evaluated. Run its CLI from the evaluator checkout, with `--root` set to a separate clean checkout of the target PR at its exact current HEAD. The evaluator code and fingerprint come from the evaluator checkout; local checks and branch/HEAD cleanliness checks run against the target checkout. Never copy downstream evaluator changes into the target branch or claim a result for a target HEAD different from the PR's current GitHub HEAD.

When migrating a legacy Issue-body ADC pointer to the append-only journal, retain the original `## Agent Development Contract` pointer block unchanged. The first journal record names the old pointer Comment ID as its predecessor (or `none` if there was no old pointer). Do not remove or edit that anchor unless a separately approved migration format records its exact prior bytes and predecessor.

Consumer Activation is separate from the fixed migration Activation. The consumer repository's approved Activation Issue ADC and append-only approval/record comments authorize only later-created non-PR Issues in that repository. New Gate Selections carry the exact Activation record identity; successor policy keeps prior selections pinned.

<a id="consumer-activation-workflow-contract"></a>
## 9 Consumer Activation workflow contract

<a id="req-f01-001"></a>
<a id="req-f01-001-repository-boundary"></a>
### 9.1 REQ-F01-001 Repository boundary

Migration issue numbers, child sets, branch pairs, and parent evidence MUST NOT supply authority in another repository.

<a id="req-f01-003"></a>
<a id="req-f01-003-append-only-approval-and-activation-history"></a>
### 9.2 REQ-F01-003 Append-only approval and Activation history

Consumer approval and Activation history are append-only comments. A record identifies the exact approved ADC, canonical Activation profile digest, setup PR merge and verified `merged_at`, admin, predecessor, and the exact trusted Required Check Run IDs with their name, App ID, head SHA, status, conclusion, and timestamps. For each required check, issuance selects the latest matching run created no later than `merged_at`, ordered by `(created_at, Check Run ID)` to resolve timestamp ties deterministically. The selected run must be completed successfully with `completed_at <= merged_at`. A failed or pending latest run at merge blocks Activation even if a later rerun succeeds; only a qualifying pre-merge run ID may be pinned. Verified PR `merged_at`, rather than the later comment publication time, is the effective Activation time. Historical reads fetch each recorded Check Run by ID and compare its pinned evidence and merge-time bound; later reruns do not replace the issuance-time evidence.

<a id="req-f01-005"></a>
<a id="req-f01-005-eligibility-by-activation-time"></a>
### 9.3 REQ-F01-005 Eligibility by Activation time

New P-ASES work is eligible only for same-repository non-PR Issues created strictly after verified setup PR `merged_at`. For a successor chain, choose the latest Activation whose verified merge time precedes the Issue creation time. Re-running gate-policy for an Issue with an existing valid Gate Selection reuses that exact historical Activation record and selection. Pre-Activation Issues remain untouched.

<a id="req-f01-007"></a>
<a id="req-f01-007-successor-activation"></a>
### 9.4 REQ-F01-007 Successor Activation

Policy or locator changes require a new setup PR and merge, append a successor Activation effective at its verified `merged_at`, and preserve prior records and selections. The successor governs only Issues created after that merge time.

<a id="req-f01-008"></a>
### 9.5 REQ-F01-008 Verified V2 Activation policy

Before recording a V2 Activation, the runtime MUST verify that the default branch has active effective protection matching the committed review mode and the complete trusted Required Check `(context, App ID)` set. It MUST read the branch, effective rules, Ruleset details, and legacy branch-protection endpoint with the same authenticated administrator identity. Missing or forbidden evidence is unavailable, not proof that protection is absent.

<a id="req-f01-009"></a>
### 9.6 REQ-F01-009 Approved Ruleset management

Ruleset writes MUST use a canonical plan bound to repository and owner IDs, the configured Activation Issue number, default branch, committed profile bytes, review mode, trusted checks, existing managed Ruleset identity and digest, its applied-record predecessor, desired API payload, current policy evidence, and open PR impact. A write requires a separate exact-plan approval comment authored by the repository owner on the Activation Issue configured by `activation.issue_number`; for this repository that value is 57. The agent MUST NOT create that approval. Before its single POST or PUT, the runtime MUST persist a durable intent bound to the exact plan, approval, and predecessor. After interruption it may recover only the uniquely matching expected Ruleset and verified effective policy, then append the exact applied record without another write. An unowned same-name Ruleset without that intent MUST remain blocked. Independently observed legacy protection constraints MUST remain represented in the effective policy assessment; a managed Ruleset cannot overwrite a conflicting legacy approval requirement. Writes are limited to the uniquely owned repository Ruleset named `P-ASES Final Delivery (managed)`; organization Rulesets, other repository Rulesets, and legacy protection are read-only. Ambiguous ownership, collisions, stale plans, missing admin access, partial writes, or failed effective-policy readback MUST block without retrying or rolling back blindly.

<a id="req-f01-010"></a>
### 9.7 REQ-F01-010 Existing Issue preservation

V1 Activation comments, their original `merged_at`, and every existing Issue ADC, Gate Selection, phase, PR binding, and evidence remain immutable. Runtime bug fixes and current CI, Ruleset, and review checks apply to existing Issues. An existing Issue continues to use its selected Activation and MUST NOT be moved to a successor Activation.

<a id="req-f01-011"></a>
### 9.8 REQ-F01-011 V2 effective time

V2 setup, approval, and Activation records are append-only and versioned. V2 becomes effective at the GitHub `created_at` timestamp of the Activation record comment. An Issue created after setup PR merge but before that comment is not authorized by V2; if eligible under V1, it continues to use V1.

<a id="req-f01-012"></a>
### 9.9 REQ-F01-012 Activation history prefix

Validation of an existing Gate Selection MUST validate only the authenticated Activation-history prefix ending at its selected record. A V2 record binds the exact earlier Ruleset applied-policy record ID, and its Ruleset ownership history is validated only through that record. Corruption after either selected prefix MUST NOT invalidate the existing Issue. Corruption within either selected prefix MUST block. New Gate Selections and successor Activation issuance MUST validate the complete Activation and Ruleset ownership histories.

<a id="req-f01-013"></a>
### 9.10 REQ-F01-013 Bootstrap and review gates

The #63 implementation branch MUST be able to create the initial Ruleset before its PR is merged. This bootstrap does not skip CI, independent review, User Review, Final Delivery, or owner merge authorization. The #60 implementation and PR #62 remain independent and are integrated after #63.

<a id="req-f01-014"></a>
### 9.11 REQ-F01-014 Activation-scoped temporary admin authentication

Only the explicit `delivery consumer-activation-admin-plan` and `delivery consumer-activation-admin-apply` commands may request temporary administrator authentication for Consumer Activation. Each command MUST accept the credential only from the repository owner through `getpass` on that owner's interactive local TTY, in a separate short-lived session. The owner creates a repository-limited, short-lived fine-grained PAT with at least Administration read/write and only the minimum additional permissions required by the existing Activation Issue read/write path, then revokes it on GitHub after use; ending a local session does not revoke the PAT. Non-interactive or sandboxed execution MUST stop with `ADMIN_AUTH_INTERACTIVE_REQUIRED`. The system MUST NOT request the PAT in chat or store it in a file, command argument, log, JSON, worktree, process-global environment, or persistent GitHub CLI credential store, and MUST NOT use browser automation or `gh auth login --web`.

The temporary credential MUST be passed only to the `gh api` child processes owned by the authenticated `GitHub` client through a private per-client override and child-process environment. It MUST NOT mutate `os.environ`, default `gh` authentication, or unrelated subprocess environments. The override MUST be cleared on normal return, errors, and interruption; complete erasure from Python memory is not guaranteed. Before any Ruleset action, the command MUST verify the authenticated stable user ID equals the repository owner's ID, the owner login and repository ID match the target, repository `permissions.admin=true`, collaborator permission is `admin`, and default-branch protection, Ruleset inventory, and effective branch rules are completely readable. A 403 or incomplete readback MUST block rather than imply absent protection.

Admin-plan is read-only and MAY write a canonical plan file only when its status is `PLANNED` with no blockers. Admin-apply MUST revalidate the exact plan, repository identity, effective policy, and a separate exact-plan owner approval on the configured Activation Issue, then reuse the existing one-write/durable-intent/apply/readback path. Temporary authentication alone is neither Ruleset approval nor PR merge authorization. The ordinary preflight and existing plan/apply commands MUST retain their current authentication behavior and MUST NOT prompt or escalate automatically.

The bootstrap Admin commands MUST run in a separate owner-operated trusted environment with an interactive local TTY after the Cloud implementation work has produced a reviewable, exact plan. Codex Cloud and its connected browser cannot provide this local TTY and MUST NOT substitute browser automation or another credential route. If the owner has no trusted local TTY environment, only the Ruleset plan/apply stage remains blocked; other work may continue.

<a id="req-f01-015"></a>
### 9.12 REQ-F01-015 Owner-authorized relay decisions and separated operations

For the self-authored `solo_owner` User Review path, `evaluate_user_review` MUST receive the validated `UserReviewSession`, full `FeedbackSnapshot` with `all_feedback_surfaces_read=true`, `pr_author_user_id`, trusted `repository_owner_user_id`, `authenticated_verifier_user_id`, `review_mode`, approved-policy `allowed_human_user_ids`, and the verifier's typed `UserReviewRelayApproval`. `repository_owner_user_id` MUST be pinned by the approved repository/Issue authority and explicitly supplied; for the #63 successor ADC it is `3744776`, paired with stable repository ID `1401910271`. The fresh repository response MUST match the pinned repository ID and exact `full_name`, have `owner.type=User`, and report `owner.id == repository_owner_user_id`; runtime MUST NOT dynamically adopt a changed owner or transferred repository. `pr_author_user_id` MUST come from the fresh PR response and equal the pinned owner ID. The carrier `owner_id` and actual GitHub comment actor MUST also equal it. `authenticated_verifier_user_id` MUST come from `GET /user` through a dedicated read-only client and MAY differ from the repository owner; it identifies the read principal only and MUST NOT be treated as owner approval. The two identities MUST remain separate in the API and in Cloud operation; no runtime path may obtain the relay's privileged credential implicitly. `allowed_human_user_ids` MUST come from approved repository review policy, not from the read principal or relay credential. Any unavailable or mismatched value MUST fail closed. A formal approval by the PR author MUST be rejected in `solo_owner`, even when that user is allowlisted. The evaluator MUST select the typed carrier only when all approval identities and subject digests match. The `UserReviewResult` and persisted result wrapper MUST retain the selected carrier evidence and full snapshot digest. Final Delivery MUST re-read the carrier chain and snapshot and reproduce the same result before accepting a saved relay-backed approval. The carrier MUST retain its dedicated evidence type throughout evaluation and persistence.

For delegated GitHub relay operations, the owner MUST first receive a readback of the exact operation, repository, Issue/PR, and subject SHA/HEAD in ChatGPT, then directly confirm that operation in chat. A generic request to continue, an Issue comment, model-generated text, a CLI flag, or caller-supplied JSON is not an operation-specific decision. The ChatGPT GitHub connector acts as a delegated relay under its authenticated GitHub account; its GitHub records are delegated evidence and MUST NOT be described as a signed or host-attested chat event. The relay write capability MUST be isolated from the implementation runtime: the runtime and its subprocesses have no relay credential or write-capable connector route. This separation MUST be established by the execution/tool boundary, not inferred from the GitHub actor ID. If that boundary, actor, target, or subject cannot be verified, the operation MUST block before its write.

The deployment MUST also make the relay write route unavailable to the Codex implementation agent, not merely to repository subprocesses. GitHub's stable actor ID does not prove which agent invoked the shared connector. Before using any relay write, the deployment's separate broker route and credential scope MUST be positively verified. The contract text or an exact chat confirmation alone does not prove that separation; when the deployment proof is absent or inconclusive, all delegated relay writes MUST remain blocked.

`PHASE_REBASE`, `ADC_SUPERSEDE`, `RULESET_PLAN_APPLY`, `USER_REVIEW`, and `PR_MERGE` are distinct, one-time decisions. Each decision MUST bind its exact ADC SHA, blocker-free plan SHA, or current PR HEAD as applicable and MUST NOT be replayed for a different operation, repository, Issue, PR, or subject. The four delegated GitHub relay decisions (`PHASE_REBASE`, `ADC_SUPERSEDE`, `RULESET_PLAN_APPLY`, and `PR_MERGE`) use `PASES_OWNER_DECISION_V1` records identifying the `delegated_github_relay` evidence channel, stable GitHub actor ID, operation and exact subject, plus the predecessor comment ID. The relay appends the record through GitHub and reads it back from the target Issue; the runtime verifies canonical bytes, stable owner ID, comment sequence, and unused decision scope. This record proves the delegated GitHub action and actor; it does not claim cryptographic linkage to a chat event. `USER_REVIEW` is not represented by that relay record: it uses the existing host-attested direct-chat path, an eligible external reviewer's native GitHub `APPROVED` review, or, only for a self-authored PR in `solo_owner` mode under an approved Issue-specific relay contract, a distinct `PASES_USER_REVIEW_DECISION_V1` record. That record is bound to the exact session ID, Readiness digest, ADC digest, PR HEAD, repository, Issue, PR, and stable owner ID. A separate exact direct `USER_REVIEW` confirmation is required before the isolated ChatGPT relay appends it. The implementation runtime cannot access the relay's write credential/capability; if this separate execution boundary is unavailable or unverifiable, the operation blocks. The runtime verifies canonical bytes, actor, exact subject and one-time session use. The implementation executor MUST NOT create a decision record in the owner's name, infer chat intent from a GitHub record, or treat a `PASES_OWNER_DECISION_V1` record as User Review evidence.

For Issue #63, `PHASE_REBASE` MUST bind the exact successor ADC SHA and authorize one bootstrap-only `phase:ready` to `phase:requirements` label replacement while preserving every other label and immutable Issue history. Because the normal runtime cannot move `ready` back to `requirements` and the successor ADC cannot receive new-generation phase receipts until that move, this single bootstrap operation is performed by the isolated GitHub relay after the bootstrap exception is included in the exact successor ADC and the owner gives a separate direct `PHASE_REBASE` confirmation. Before recording the decision or changing labels, the relay MUST reread the open Issue, complete label set, active predecessor ADC and pointer journal; it MUST verify the exact ADC bytes against the confirmed SHA. It appends and reads back the canonical decision, then replaces only the phase label and performs complete post-write Issue readbacks. This is not a general phase-transition API. After implementation, `phase_rebaseline.py` MUST only verify the broker-produced decision/history and already-rebased label set; it MUST return a no-op result and MUST block if the bootstrap write is absent, never repeating the label write. `ADC_SUPERSEDE` MUST be separately approved for that same exact ADC SHA and use the supported append-only publication path through the isolated relay, with comment and pointer-journal readback. A `RULESET_PLAN_APPLY` decision MUST bind the exact blocker-free canonical plan SHA; only the separately confirmed GitHub relay may then append the existing exact two-line Issue #57 approval comment as an explicitly scoped exception to the predecessor's agent-posting prohibition. The comment MUST read back with the configured stable owner User ID; an unknown actor MUST block. Existing one-write, durable-intent, readback, and fail-closed Ruleset semantics remain mandatory. `USER_REVIEW` MUST use the existing host-attested direct-chat path, an eligible native external-reviewer PR review, or the exact-session `PASES_USER_REVIEW_DECISION_V1` carrier for self-authored `solo_owner` PRs; a formal approval by the PR author is invalid. The dedicated record MUST pass actor, schema, session, Readiness, ADC, HEAD, replay, feedback, and thread checks and MUST NOT be confused with `PASES_OWNER_DECISION_V1`. `PR_MERGE` requires its own current-HEAD decision after all independent review, CI, User Review, and Final Delivery gates pass.
