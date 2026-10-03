# Specification standard

## Purpose

Specifications own durable, testable product behavior. Each normative rule has one owner; designs, Skills, and status documents link to it.

## Rules

- Use Schema 2 marker comments and the specification template.
- State purpose, scope, normative requirements, observable behavior, errors/boundaries, security/privacy, and verification.
- Use MUST/SHOULD/MAY only when the obligation is intentional and testable.
- Link to the owning Issue and design. Separate confirmed behavior from open questions.
- Keep examples illustrative and label them; do not let examples silently become policy.

## Validation

Run `python -m agent_workflow validate-docs` and connect every requirement to observable evidence. External links are not fetched by the validator.

## Related resources

See [design standard](design.md), [documentation synchronization](documentation-sync.md), and [specification template](../templates/spec-template.md).
