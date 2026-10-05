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

The repository owns nine Skills, shared standards and templates, application profiles, implementation-contract handling, evidence and checkpoints, self-review, PR delivery, project-profile routing, deterministic validation, and host-specific packages. A consumer project owns its source, `.agent/project.json`, Issue-specific documents, hooks, and verification commands.

The product does not own a service, database, daemon, GUI, project-template repository, source synchronization, automatic semantic document rewriting, stack-wide detectors, or existing-consumer migration.

## Normative requirements

### Workflow phases

The shared Issue lifecycle is exactly:

`requirements -> design -> ready -> implementation -> review -> closed`

An Issue is the authority for a work item. Repository-changing work begins from an owning Issue, one feature branch, an approved decision-complete Implementation Contract, and linked specification/design owners when durable behavior changes. No implementation begins before the contract and Reviewer Checklist are available on the Issue.

The durable document sequence is `requirements -> specs -> design -> code/tests -> status/evidence`. A material change to requirements updates the owning specification before dependent design or code. One document owns each durable rule; other documents link to it instead of copying its policy.

Every new durable work item records explicit specification, design, and status decisions in the Issue's `## Document impact` section. Link decisions point into the matching `docs/specs/`, `docs/design/`, or `docs/status/` tree; unchanged decisions and evidence-only status decisions include a reason. Requirements and design establish these decisions, implementation re-evaluates them against the final diff, and self-review checks final alignment. An unchanged or evidence-only decision does not require creating a document.

Feature work uses `python -m agent_workflow start-feature-branch <issue> <description...>` after its open Issue and project profile are validated. The runtime derives a deterministic `<prefix>/<issue>-<slug>` branch name, checks the worktree, and performs cleanup and global `branch_switch` hooks only after an actual branch switch. Repeating the command on the current target branch performs no cleanup or hooks.

After an Issue exists, the requirements Skill runs `python -m agent_workflow ensure-milestone <issue>` unless an approved Issue contract explicitly names a target release, in which case it passes that unchanged value with `--target-version <version>`. Skills MUST NOT invent or infer a target version. Milestones follow the consumer profile's `auto`, `required`, or `disabled` mode. `disabled` always skips and cannot be overridden by a target. Otherwise an explicit target takes precedence over the repository version source; absent a target, the existing profile source applies. `auto` accepts an unresolved fallback as `NOT_APPLICABLE`; `required` fails closed when no fallback version can be resolved. Exact-title reuse is idempotent, and closed or duplicate milestones are never silently reopened or replaced. An Issue's existing Milestone is immutable through this command: a different current assignment fails without mutation.

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
9. `delivery` — enforce PR handoff and merged-delivery gates.

Each Skill MUST have concise YAML frontmatter with `name` and `description`. Detailed shared policy belongs in standards or referenced resources. A Skill MUST state its trigger, expected inputs, ordered procedure, output, uncertainty behavior, and supporting resources where relevant. Skill copies in `dist/**` are generated.

The requirements Skill creates/validates the Issue first and then runs `ensure-milestone`, passing `--target-version` only when the approved Issue requirements explicitly supply it; it may continue after `NOT_APPLICABLE` only when the profile mode is `auto`. The implementation Skill starts the feature branch with `start-feature-branch` before changing source files and preserves any approved target version unchanged through the implementation handoff.

### Review and delivery principles

Self-review is evidence, never approval. Review findings use these categories:

- A — Contract violation
- B — Contract ambiguity
- C — Newly discovered requirement
- D — Optional improvement

Category C is not implementer failure. An implementation is complete only through the PR delivery gate; passing tests alone is insufficient. A new PR commit invalidates review against an older HEAD. Missing or unavailable verification remains unverified and MUST NOT be reported as passing.

A self-review has two separate layers: Contract Conformance Review covers the complete approved Implementation Contract, and Reviewer Checklist Review covers every effective Contract/Issue checklist item. The Reviewer Checklist is a concise summary review surface, not a substitute for reading and checking the full approved contract. Both layers bind to the same exact PR HEAD, approved contract comment ID, and approved contract SHA.

Strict Reviewer Checklist H2 authoring validation applies at the write boundary when a new or superseding contract is published. It does not invalidate already-approved historical contract bytes. Historical checklist extraction keeps the canonical-block precedence and narrow-heading fallback; a legacy/non-canonical Reviewer Checklist H2 is also included in contract-conformance coverage, while a strict-canonical H2 may be excluded. Self-review publication reads back the exact named comment after creation and verifies its PR association and body before any pointer update; this check is separate from the subsequent HEAD and contract race revalidation.

A current contract section or checklist item with `result: fail` blocks handoff even when Required Checks are green. Contract-section `untested` is valid evidence of an unresolved blocker and blocks handoff. Checklist-level `untested` remains valid, non-blocking evidence by itself; its evidence must identify the unavailable verification or residual uncertainty. A source/diff-reviewable contract section must not be marked `untested` to avoid checking it. Mandatory verification and configured Required Checks remain independent gates.

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
| Submitted self-review without matching evidence | Treat it as a claim to check, never as proof. |

## Security and privacy

The workflow never prints or stores credentials in contract payloads, logs, Skills, generated packages, or PR evidence. Local hooks are trusted explicit commands, not a sandbox. Network-backed operations fail closed on uncertain ownership, identity, authorization, or state.

## Verification strategy

Validate Skill metadata and references, stable Issue and phase routing, document-owner links, generated package parity, review evidence, and each delivery-gate condition independently. The [Runtime specification](runtime-spec.md) owns command-level acceptance cases; the [Distribution specification](distribution-spec.md) owns host-package acceptance cases.
