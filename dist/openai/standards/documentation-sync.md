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

## Validation

`python -m agent_workflow validate-docs` without a selector keeps the full scan. Use mutually exclusive `--issue N` to validate only that Issue's declared existing owners or `--changed BASE` to validate only changed `docs/**/*.md` files from `BASE...HEAD`. Issue-scoped validation fails on a linked missing owner or malformed/wrong-tree decision; unchanged and evidence-only rows require no file. Changed-scope validation ignores deletions and fails on an unknown base without broadening. Git ref/diff resolution stays in `git.py`; neither scoped command runs shell hooks. The validator is offline and does not claim an external URL is current.

## Related resources

See [specification standard](specification.md), [design standard](design.md), and the [status template](../templates/status-template.md).
