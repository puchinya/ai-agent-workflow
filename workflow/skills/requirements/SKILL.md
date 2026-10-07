---
name: requirements
description: Establish or refine an Issue-owned, decision-complete implementation contract before repository changes.
---
# Requirements

## Trigger and inputs
Use when work is proposed without an approved Issue contract, or a material requirement changes. Inputs are the user request, repository state, and relevant existing Issue/docs.

## Procedure
1. Confirm one owning Issue and inspect its current phase and contract pointer.
2. After the Issue exists, read the approved requirements/contract for an explicit target release. Run `python -m agent_workflow ensure-milestone <issue> --target-version <version>` only when that target is explicitly approved; preserve it exactly and never infer or calculate one. Otherwise run `python -m agent_workflow ensure-milestone <issue>` and use the profile version source. Inspect the JSON result. `disabled` always skips even when a target is supplied; continue after `NOT_APPLICABLE` only when `.agent/project.json` sets `milestones.mode` to `auto`.
3. Resolve scope, observable outcomes, constraints, non-goals, acceptance evidence, and unresolved decisions with the user.
4. For new durable work, record the canonical `## Document impact` rows for Specification, Design, and Status. Use matching docs-tree links or a reason for `unchanged`/`evidence-only`; do not force a document change.
5. Draft concise contract text and a Reviewer Checklist; keep secrets out. The Reviewer Checklist summarizes critical review points and need not duplicate every contract obligation because final self-review covers the complete approved contract. The strict `## Reviewer Checklist` H2 authoring rule applies only when publishing a new or superseding contract. Before enforcing it, the runtime safely canonicalizes a recognizable legacy H2, preserving checkbox wording/order and all bytes outside that section. The normalized section may contain only the canonical `AGENT_REVIEWER_CHECKLIST_V1` block and approved short introduction, and MUST NOT contain unique normative requirements, architecture decisions, verification requirements, exceptions, or completion gates outside the checklist items. Use the approved introduction `The implementer must self-review every item in this checklist.`; ambiguous or prose-bearing content fails before GitHub mutation. Do not retroactively require an already-approved historical contract to meet this authoring rule.
6. Publish the full approved contract as one top-level Issue comment and verify its bytes and pointer.
7. Confirm the Issue links to its specification/design owners and that any unchanged/evidence-only decisions have reasons.
8. Once the user authorizes execution of the approved Issue-scoped contract, treat that authorization as continuing through commit, safe push, review-PR creation/reuse, `phase:review`, exact-HEAD self-review publication, check reads, and delivery-check. Do not request a later PR-specific conversational approval. Separate authority is still required for material scope/architecture changes, contract supersession, ambiguous ownership/base, destructive Git operations, merge/release, credential/permission escalation, unrelated Issue/PR mutations, or an explicit request to stop before PR creation.

## Output and uncertainty
Return the Issue URL, contract SHA, decisions, and explicit open questions. Stop repository-changing work if scope or ownership is ambiguous. Follow [documentation synchronization](../../standards/documentation-sync.md) and the Implementation Contract rules in the runtime specification.
