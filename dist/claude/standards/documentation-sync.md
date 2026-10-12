# Documentation synchronization standard

## Purpose

Keep durable requirements, design decisions, code, tests, and evidence aligned without automatic semantic rewrites. Completion is evaluated from the final aggregate result; artifact authoring chronology is not a requirement.

## Rules

Requirements, specifications, design, code/tests, and status/evidence have distinct owners and must agree in the final result. The workflow does not require a particular order for creating or editing those artifacts. When a decision changes, ensure its owner and every affected dependent document or implementation reflect the approved final decision. Link to owners instead of copying rules. This repository does not synchronize another repository, migrate existing consumer documents, or rewrite prose automatically.

New durable Issue work includes a structured `## Document impact` section:

```markdown
## Document impact
- Specification: <links> | unchanged — <reason>
- Design: <links> | unchanged — <reason>
- Status: <links> | evidence-only — <reason> | unchanged — <reason>
```

Each row selects exactly one alternative. Specification links belong under `docs/specs/`, Design links under `docs/design/`, and Status links under `docs/status/`; each row may contain multiple Markdown links. An `unchanged` decision needs a reason. `evidence-only` means verification evidence is recorded on the Issue/PR and no status document needs to change. Do not create a document merely to avoid an unchanged or evidence-only decision. Legacy link-only `Document impact` sections remain supported.

Requirements and design establish the decisions. During implementation, compare the final diff with all three rows and update the decisions if needed. Self-review verifies that the final docs and diff still match the Issue decisions.

Use stable REQ-AREA-NNN IDs for normative requirements, DES-AREA-NNN for design decisions, TST-AREA-NNN for test conditions, and ORA-AREA-NNN for independent Oracles. docs/testing/traceability.md links every REQ through a DES and an ORA/TST to executable evidence. These identities do not depend on numbered headings.

P-ASES provides `python -m p_ases docs validate` and `python -m p_ases docs format (--write|--check)`. Formatting deterministically numbers H2+ headings, preserves manual/legacy anchors, updates contents and heading maps, and repairs local Markdown fragments. It processes Markdown under docs only; it never formats immutable ADC comments or generated dist files. The check form does not write.

## Validation

Run `python -m p_ases docs validate --root PATH` for the complete repository scan. It validates local Markdown structure, links, and traceability without fetching external URLs or executing shell hooks. Use `python -m p_ases docs format --check --root PATH` to read deterministic formatting state; the check mode does not write. Git ref and diff operations remain owned by `runtime/p_ases/git.py`.

## Related resources

See [specification standard](specification.md), [design standard](design.md), and the [status template](../templates/status-template.md).
