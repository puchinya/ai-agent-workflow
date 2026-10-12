# Technical design standard

A technical design records how approved requirements are realized. It owns architecture, module responsibilities, data flow, ownership, failure handling, and rejected alternatives; it does not restate normative behavior.

## Required content

- Stable DES-AREA-NNN identifiers.
- Context and goals, a REQ traceability table, architecture, data flow and ownership, failure handling, and alternatives considered.
- Links to the exact REQ owners and test/Oracle owners.
- A reasoned statement of specification impact when behavior remains unchanged.

## Authoring rules

Use one stable design ID for each decision that downstream implementation or validation depends on. Keep implementation details only where they establish module boundaries or ownership. Do not put test procedures or results in a design document.

Run python -m p_ases docs validate to verify REQ/DES/Oracle/Test/Evidence reachability and local links.

## Related resources

Use the [technical design template](../templates/technical-design-template.md), [product specification standard](product-specification.md), and [test specification standard](test-specification.md).
