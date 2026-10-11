# Product specification standard

A product specification is the normative source for externally observable behavior. It records approved requirements without prescribing implementation or test execution.

## Required content

- Stable REQ-AREA-NNN identifiers for requirements.
- Purpose, scope, normative requirements, observable behavior, error and boundary behavior, and security and privacy.
- Explicit unresolved decisions rather than guessed behavior.
- Links to corresponding design decisions and test specifications.
- No mandatory Verification Strategy chapter. Procedures, test inputs, expected outcomes, and results belong in docs/testing and verification evidence.

## Authoring rules

State one externally meaningful requirement per stable ID. A documentation-only change preserves normative meaning unless the owner approves a behavior change. When external behavior changes, settle the specification before finalizing the design. A product specification may state a reasoned not-applicable test impact, but it does not copy test scripts or execution results.

Run python -m p_ases docs validate to validate document roles, stable IDs, local links, traceability, and formatter output.

## Related resources

Use the [product specification template](../templates/product-spec-template.md), [technical design standard](technical-design.md), and [test specification standard](test-specification.md).
