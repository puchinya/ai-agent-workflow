# Documentation synchronization standard

## Purpose

Keep durable requirements, design decisions, code, tests, and evidence aligned without automatic semantic rewrites. Completion is evaluated from the final aggregate result; artifact authoring chronology is not a requirement.

## Rules

Requirements, specifications, design, code/tests, and status/evidence have distinct owners and must agree in the final result. Product behavior is decided before dependent design is approved; artifact editing itself has no fixed chronology. When a decision changes, ensure its owner and every affected dependent document or implementation reflect the approved final decision. Link to owners instead of copying rules. This repository does not synchronize another repository, migrate existing consumer documents, or rewrite prose automatically.

New durable P-ASES Issue work records its decisions in the approved ADC's structured `## Artifact impact` section:

```markdown
## Artifact impact
- Specification: <create/update docs/specs/<path>.md | unchanged/not applicable — reason>
- Design: <create/update docs/design/<path>.md | unchanged/not applicable — reason>
- Testing: <create/update docs/testing/<path>.md | unchanged/not applicable — reason>
- Status: <create/update links | evidence-only/unchanged/not applicable — reason>
```

Each row selects one applicable decision. Specification, Design, and Testing create/update paths belong under `docs/specs/`, `docs/design/`, and `docs/testing/` respectively. Unchanged or not-applicable decisions need a reason; a skipped specification or design phase must use the same reason. `evidence-only` means verification evidence is recorded on the Issue/PR and no status document needs to change. Do not create a document merely to avoid an unchanged or evidence-only decision. Legacy `## Document impact` sections remain supported for existing document routing, but they do not replace the approved ADC's `## Artifact impact` for new phase evidence.

Before `ready`, the approved ADC names the test/Oracle artifact and includes `docs/testing/traceability.md`. Each requirement links through design, an independent Oracle, a test case, and one or more existing executable test sources. A source may be a failing scaffold awaiting implementation; `ready` verifies its committed identity and path, while Verification later establishes the result. A missing source file blocks `ready`. Every linked canonical document must exist in the same Issue branch commit and contain the linked anchor; its path must match the approved ADC impact or an explicit unchanged decision. The frozen Issue binding is established before phase artifacts are committed. The phase receipt binds committed artifact bytes to the Issue branch commit and verifies the completed predecessor receipt chain; it records technical evidence and is not a separate approval.

Requirements and design establish the decisions. During implementation, compare the final diff with all three rows and update the decisions if needed. Self-review verifies that the final docs and diff still match the Issue decisions.

Use stable REQ-AREA-NNN IDs for normative requirements, DES-AREA-NNN for design decisions, TST-AREA-NNN for test conditions, and ORA-AREA-NNN for independent Oracles. docs/testing/traceability.md links every REQ through a DES and an ORA/TST to executable evidence. These identities do not depend on numbered headings.

P-ASES provides `python -m p_ases docs validate` and `python -m p_ases docs format (--write|--check)`. Formatting deterministically numbers H2+ headings, preserves manual/legacy anchors, updates contents and heading maps, and repairs local Markdown fragments. It processes Markdown under docs only; it never formats immutable ADC comments or generated dist files. The check form does not write.

## Validation

Run `python -m p_ases docs validate --root PATH` for the complete repository scan. It validates local Markdown structure, links, and traceability without fetching external URLs or executing shell hooks. Use `python -m p_ases docs format --check --root PATH` to read deterministic formatting state; the check mode does not write. Git ref and diff operations remain owned by `runtime/p_ases/git.py`.

## Related resources

See [specification standard](specification.md), [design standard](design.md), and the [status template](../templates/status-template.md).
