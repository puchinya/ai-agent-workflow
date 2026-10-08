<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Specification

- Status: Approved
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related design: [Workflow design](../design/workflow-design.md)
- Runtime contract: [Runtime specification](runtime-spec.md)

## Purpose

Define the reusable development workflow shared by OpenAI/Codex, Claude Code, and Google Antigravity 2.0. The product provides workflow behavior and deterministic local tools; it does not scaffold application source or synchronize projects with another repository.

## Scope

The repository owns ten Skills, shared standards and templates, application profiles, implementation-contract handling, evidence and checkpoints, self-review, independent PR review, QA, PR delivery, project-profile routing, deterministic validation, and host-specific packages. A consumer project owns its source, `.agent/project.json`, Issue-specific documents, hooks, and verification commands.

The product does not own a service, database, daemon, GUI, project-template repository, source synchronization, automatic semantic document rewriting, stack-wide detectors, or existing-consumer migration.

## Normative requirements

### Workflow phases

The shared Issue lifecycle is exactly:

`requirements -> design -> ready -> implementation -> review -> closed`

An Issue is the authority for a work item. Repository-changing work begins from an owning Issue, one feature branch, an approved decision-complete Implementation Contract, and linked specification/design owners when durable behavior changes. No implementation begins before the contract and Reviewer Checklist are available on the Issue.

The durable document sequence is `requirements -> specs -> design -> code/tests -> status/evidence`. A material change to requirements updates the owning specification before dependent design or code. One document owns each durable rule; other documents link to it instead of copying its policy.

Every new durable work item records explicit specification, design, and status decisions in the Issue's `## Document impact` section. Link decisions point into the matching `docs/specs/`, `docs/design/`, or `docs/status/` tree; unchanged decisions and evidence-only status decisions include a reason. Requirements and design establish these decisions, implementation re-evaluates them against the final diff, and self-review checks final alignment. An unchanged or evidence-only decision does not require creating a document.

Feature work uses `python -m agent_workflow start-feature-branch <issue> <description...>` after its open Issue and project profile are validated. The runtime derives a deterministic `<prefix>/<issue>-<slug>` branch name, checks the worktree, and performs cleanup and global `branch_switch` hooks only after an actual branch switch. Repeating the command on the current target branch performs no cleanup or hooks.

### Host-managed implementation workspaces

Publishing, reviewing, or approving an Implementation Contract does not allocate a workspace. Execution of the approved Contract is the trigger. The normal user request remains “Implement this Contract”; the Skill reads the Schema 2 `workspace.isolation` policy before edits and lets the active host establish or reuse isolation.

For every new execution, after `agent-context` confirms that no valid binding exists and before host capability selection, the implementation Skill MUST run `python -m agent_workflow resolve-implementation-base ISSUE` (adding `--base-ref BRANCH` for a selected stacked base). The returned `base_ref` and `base_sha` are authoritative for host exact-base capability, host starting-ref selection, initial isolated HEAD verification, current-mode `start-feature-branch`, and `prepare-implementation`; current-mode setup passes both `--base-ref` and `--expected-base-sha`. Expected-SHA mismatch fails closed if the remote advances. Existing valid bindings skip resolution and reuse their frozen tuple without re-fetching a newer remote tip. Resolution permits a dirty current checkout, validates the approved execution authority and exact same-repository remote branch, and only fetches that branch; it creates no binding or workspace and performs no branch, hook, source, or GitHub mutation.

- Before host isolation, resolve the selected same-repository base ref and its full SHA. For an already-bound execution, reuse its frozen `base_ref` and `base_sha`.
- Resume a valid binding in its existing workspace after commits without rerunning `start-feature-branch` or resolving the frozen SHA against a newer remote tip. `prepare-implementation` may validate reuse and explicit Contract supersession; it must not reinitialize the workspace.
- Native isolation is available only when the active host surface can create or reuse a workspace whose initial `HEAD` is exactly the selected base SHA. A host worktree feature alone does not satisfy this requirement. Verify the initial HEAD before `prepare-implementation`.
- `auto` prefers exact-base native isolation when available. Otherwise it uses the existing current-checkout branch flow with the same `base_ref` and expected SHA.
- `required` stops before edits when host-managed isolation at the exact selected base cannot be established.
- `disabled` does not request a new worktree and does not force a session already in a worktree back to the main checkout.

Codex uses its current surface's managed worktree or task-fork capability when exposed and selects the approved starting ref when supported; the resulting HEAD must equal the selected SHA. Claude Code reuses a valid worktree or enters one through native `EnterWorktree` only when it can preserve the exact selected base. For unsupported stacked/non-default bases, and any other unverified exact-base capability, `auto` falls back and `required` blocks. Do not create a wrong-base workspace and repair it by switching, resetting, merging, or rebasing. The runtime never invokes another coding-agent binary or runs raw automatic `git worktree add`; it does not manage host permissions, placement, resume, or cleanup and cannot prove session provenance.

Issue/PR identity remains the user's routing key. One implementation writer owns an execution, and ordinary follow-up answers or corrections reuse the same binding and workspace. A changed approved Contract blocks continuation until explicit supersession refreshes only its bound comment ID/SHA. This version does not add global task discovery, a database, daemon, Issue DAG scheduler, or parallelism setting.

`.worktreeinclude` may contain explicit project-owned patterns for local ignored files needed in host-created worktrees. The workflow never creates that file, infers secrets, or copies ignored files without an explicit pattern. Independent Review remains a fresh session, subagent, or human review and is not authored by the implementation execution.

After an Issue exists, the requirements Skill runs `python -m agent_workflow ensure-milestone <issue>` unless an approved Issue contract explicitly names a target release, in which case it passes that unchanged value with `--target-version <version>`. Skills MUST NOT invent or infer a target version. Milestones follow the consumer profile's `auto`, `required`, or `disabled` mode. `disabled` always skips and cannot be overridden by a target. Otherwise an explicit target takes precedence over the repository version source; absent a target, the existing profile source applies. `auto` accepts an unresolved fallback as `NOT_APPLICABLE`; `required` fails closed when no fallback version can be resolved. Exact-title reuse is idempotent, and closed or duplicate milestones are never silently reopened or replaced. An Issue's existing Milestone is immutable through this command: a different current assignment fails without mutation.

### Authorization continuity and implementation handoff

Once a user authorizes execution of an approved Issue-scoped Implementation Contract, that authorization continues through the routine Issue-scoped mutations required to reach a review-ready PR: commit, non-force push, PR create/reuse and required title/body update, transition to `phase:review`, exact-HEAD Agent Self-Review publication, CI/Required Check reads, and the final delivery gate. Skills MUST NOT request a separate conversational confirmation solely for those operations. Host-enforced security prompts may still apply.

That authorization does not cover material scope or architecture changes, contract supersession, an ambiguous or conflicting owning Issue/base, force-push or branch deletion, merge, tag/release creation, publication outside the review PR workflow, credential or permission escalation, mutation of an unrelated Issue/PR, or an explicit user request to stop before PR creation. A conflict requiring one of these decisions blocks only the dependent work.

For an authorized contract, the implementation Skill owns the full sequence: `verify_quick` -> commit -> `ensure-review-pr` (safe non-force push and PR create/reuse) -> `verify-final` -> exact-HEAD self-review -> QA -> fresh-context independent PR review -> `delivery-check`. The implementation session MUST NOT author the independent review artifact; the `pr-review` Skill requires a new session/subagent or human. If that reviewer is unavailable, report the exact blocker with the review PR URL. The workflow MUST NOT claim runtime proof of fresh context or assume a host-specific session API. It MUST NOT report implementation complete before an open, non-draft review PR exists. Pending Required Checks are reported as `BLOCKED_DELIVERY_CHECKS_PENDING`; the review PR must already exist. Automatic merge is forbidden.

### Skills

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

### Review and delivery principles

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

## Observable behavior

The portable workflow routes agents from an owning Issue to its active phase, affected components, applicable application profiles, explicit document impact decisions and linked specification/design/status owners, relevant symbols and tests, and current diff. It does not require reading every standard or generated project summary by default. Skills describe when to load additional standards; they do not duplicate full policy text.

The consumer's explicit project profile is the machine authority for components, stacks, application types, targets, hooks, and branch/milestone policy. Application type, stack, target, and runtime host are independent concepts. Application type is never inferred from repository contents, stack, target, or host.

## Error and boundary behavior

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

## Security and privacy

The workflow never prints or stores credentials in contract payloads, logs, Skills, generated packages, or PR evidence. Local hooks are trusted explicit commands, not a sandbox. Network-backed operations fail closed on uncertain ownership, identity, authorization, or state.

## Verification strategy

Validate Skill metadata and references, stable Issue and phase routing, document-owner links, generated package parity, review evidence, and each delivery-gate condition independently. The [Runtime specification](runtime-spec.md) owns command-level acceptance cases; the [Distribution specification](distribution-spec.md) owns host-package acceptance cases.
