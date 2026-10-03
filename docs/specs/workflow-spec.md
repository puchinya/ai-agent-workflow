<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Specification

- Status: Approved
- Owning Issue: [Issue #1](https://github.com/puchinya/ai-agent-workflow/issues/1)
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

### Skills

Canonical Skill source is `workflow/skills/`. It contains exactly these task areas:

1. `requirements` — elicit decisions and establish an Issue-owned contract.
2. `design` — create traceable specification and design documents.
3. `implementation-contract` — preserve, publish, restore, and verify approved contract bytes.
4. `implementation` — work from the approved Issue and scoped context.
5. `evidence` — record reproducible verification and unverified targets.
6. `checkpoint` — save and resume Issue-scoped progress.
7. `self-review` — evaluate every effective checklist item against evidence.
8. `pr-review` — review a change independently against its contract and current HEAD.
9. `delivery` — enforce PR handoff and merged-delivery gates.

Each Skill MUST have concise YAML frontmatter with `name` and `description`. Detailed shared policy belongs in standards or referenced resources. A Skill MUST state its trigger, expected inputs, ordered procedure, output, uncertainty behavior, and supporting resources where relevant. Skill copies in `dist/**` are generated.

### Review and delivery principles

Self-review is evidence, never approval. Review findings use these categories:

- A — Contract violation
- B — Contract ambiguity
- C — Newly discovered requirement
- D — Optional improvement

Category C is not implementer failure. An implementation is complete only through the PR delivery gate; passing tests alone is insufficient. A new PR commit invalidates review against an older HEAD. Missing or unavailable verification remains unverified and MUST NOT be reported as passing.

## Observable behavior

The portable workflow routes agents from an owning Issue to its active phase, affected components, applicable application profiles, linked specification/design/status owners, relevant symbols and tests, and current diff. It does not require reading every standard or generated project summary by default. Skills describe when to load additional standards; they do not duplicate full policy text.

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
