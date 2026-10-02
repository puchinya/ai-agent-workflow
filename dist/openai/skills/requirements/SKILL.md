---
name: requirements
description: Establish or refine an Issue-owned, decision-complete implementation contract before repository changes.
---
# Requirements

## Trigger and inputs
Use when work is proposed without an approved Issue contract, or a material requirement changes. Inputs are the user request, repository state, and relevant existing Issue/docs.

## Procedure
1. Confirm one owning Issue and inspect its current phase and contract pointer.
2. Resolve scope, observable outcomes, constraints, non-goals, acceptance evidence, and unresolved decisions with the user.
3. Draft concise contract text and a Reviewer Checklist; keep secrets out.
4. Publish the full approved contract as one top-level Issue comment and verify its bytes and pointer.
5. Link the Issue to specification/design owners where durable behavior changes.

## Output and uncertainty
Return the Issue URL, contract SHA, decisions, and explicit open questions. Stop repository-changing work if scope or ownership is ambiguous. Follow [documentation synchronization](../../standards/documentation-sync.md) and the Implementation Contract rules in the runtime specification.
