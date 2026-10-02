# Documentation synchronization standard

## Purpose

Keep durable requirements, design decisions, code, tests, and evidence aligned without automatic semantic rewrites.

## Rules

The authority sequence is `requirements -> specs -> design -> code/tests -> status/evidence`. Update the owning artifact first when its meaning changes. Link to owners instead of copying rules. This repository does not synchronize another repository, migrate existing consumer documents, or rewrite prose automatically.

## Validation

Use local Markdown links and `validate-docs`; inspect Issue links and affected-document declarations manually. The validator is offline and does not claim an external URL is current.

## Related resources

See [specification standard](specification.md), [design standard](design.md), and the [status template](../templates/status-template.md).
