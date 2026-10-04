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
5. Draft concise contract text and a Reviewer Checklist; keep secrets out.
6. Publish the full approved contract as one top-level Issue comment and verify its bytes and pointer.
7. Confirm the Issue links to its specification/design owners and that any unchanged/evidence-only decisions have reasons.

## Output and uncertainty
Return the Issue URL, contract SHA, decisions, and explicit open questions. Stop repository-changing work if scope or ownership is ambiguous. Follow [documentation synchronization](../../standards/documentation-sync.md) and the Implementation Contract rules in the runtime specification.
