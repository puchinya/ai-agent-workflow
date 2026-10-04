---
name: design
description: Turn an approved Issue contract into traceable specifications and implementation design before coding.
---
# Design

## Trigger and inputs
Use after requirements are approved and before implementation. Read the owning Issue, relevant existing docs, repository constraints, and the [design standard](../../standards/design.md).

## Procedure
1. Identify durable rules and assign one specification owner to each.
2. Set the Issue's Specification, Design, and Status decisions before writing; each row uses matching-tree links or its allowed unchanged/evidence-only reason.
3. Write or update Schema 2 specs, then design documents with traceability.
4. Record boundaries, errors, data ownership, security, alternatives, and verification.
5. Link Issue, specification, and design owners; validate local links, required sections, and the declared Document impact.
6. Publish the Reviewer Checklist before implementation.

## Output and uncertainty
Produce linked specs/design and unresolved-decision list. Do not invent a decision when the contract is incomplete; route it back to requirements. Use the repository templates under `workflow/templates/`.
