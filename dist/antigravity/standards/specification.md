# Specification standard

## Purpose

Specifications own durable, testable product behavior. Each normative rule has one owner; designs, Skills, and status documents link to it.

## Rules

- Use Schema 2 marker comments and the specification template.
- State purpose, scope, normative requirements, observable behavior, errors/boundaries, and security/privacy.
- Do not add a mandatory Verification Strategy chapter. Test procedures belong in docs/testing and results belong in verification evidence.
- Use MUST/SHOULD/MAY only when the obligation is intentional and testable.
- Link to the owning Issue and design. Separate confirmed behavior from open questions.
- Keep examples illustrative and label them; do not let examples silently become policy.
- For P-ASES work, the approved ADC is the authority for whether specification is required or explicitly unchanged. When required, commit the specification on the Issue branch before advancing to `specification`; publish the phase receipt for that exact commit. The workflow specification owns the lifecycle and receipt rules.
- Settle the product behavior before dependent design decisions are approved. File-edit chronology is flexible when the final decisions remain traceable and consistent.

## Validation

Run `python -m p_ases docs validate --root .` and connect every requirement to observable evidence. External links are not fetched by the validator.

## Related resources

See [design standard](design.md), [documentation synchronization](documentation-sync.md), and [specification template](../templates/spec-template.md).
