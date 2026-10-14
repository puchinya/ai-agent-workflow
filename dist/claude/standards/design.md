# Design standard

## Purpose

Design documents explain decisions that satisfy approved specifications without becoming a second source of behavior.

## Rules

- Use Schema 2 markers and the design template.
- Link to the owning Issue and specifications.
- Describe context/goals, REQ traceability, architecture, data/control flow, ownership, failures/recovery, and rejected alternatives.
- Keep test procedures and results in docs/testing and verification evidence rather than repeating them in designs.
- A material specification change updates its specification before dependent design or implementation.
- For P-ASES work, use the approved ADC's Design artifact impact and specification decision to determine whether design is required. Establish the frozen Issue binding before phase artifacts are committed. Commit required design artifacts on the Issue branch after the specification receipt, then bind the design receipt to that exact commit and predecessor chain. The receipt records verification; it does not approve the design or expand the ADC.
- Keep unresolved choices visible; do not disguise them as implementation details.

## Validation

Run `python -m p_ases docs validate --root .`, then review the traceability table against current requirements and tests.

## Related resources

See [specification standard](specification.md), [documentation synchronization](documentation-sync.md), and [design template](../templates/design-template.md).
