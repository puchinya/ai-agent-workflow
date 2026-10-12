# Design standard

## Purpose

Design documents explain decisions that satisfy approved specifications without becoming a second source of behavior.

## Rules

- Use Schema 2 markers and the design template.
- Link to the owning Issue and specifications.
- Describe context/goals, REQ traceability, architecture, data/control flow, ownership, failures/recovery, and rejected alternatives.
- Keep test procedures and results in docs/testing and verification evidence rather than repeating them in designs.
- A material specification change updates its specification before dependent design or implementation.
- Keep unresolved choices visible; do not disguise them as implementation details.

## Validation

Run `python -m agent_workflow validate-docs`, then review the traceability table against current requirements and tests.

## Related resources

See [specification standard](specification.md), [documentation synchronization](documentation-sync.md), and [design template](../templates/design-template.md).
