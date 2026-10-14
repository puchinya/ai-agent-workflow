---
name: technical-design
description: Record an implementation design that satisfies the approved product specification and runtime boundaries.
---
# Technical design

## Owner and inputs

Owner: workflow/standards/technical-design.md, workflow/templates/technical-design-template.md, and docs/design/. Inputs are the approved product specification, existing architecture, threat boundaries, portability requirements, and repository constraints.

## Workflow

1. Map each requirement to an owned module or external boundary.
2. Preserve the one-shot standard-library runtime, GitHub API boundary, Git subprocess boundary, host-specific schemas, and immutable evidence rules.
3. Explain data flow, failure behavior, idempotency, migration impact, and any security-relevant alternatives.
4. Link designs to the exact specification and keep existing DES identifiers stable.
5. Validate links and traceability before the design is presented for approval.
6. Commit the design on the bound Issue branch after the approved specification receipt. Publish the design receipt against that exact commit; it must verify the predecessor receipt and unchanged specification hashes. Use the ADC's unchanged reason when specification is intentionally skipped.

## CLI

~~~sh
python -m p_ases docs validate --root .
~~~

The CLI checks documents; it does not decide or approve an architectural alternative.

## Failure handling and output

Do not change trust roots, package identity, supported hosts, or persistent formats silently. A material conflict with approved requirements must be reported before implementing that boundary. Output the design, module ownership, migration notes, risks, and requirement links.

Next owner: test-specification defines an independent Oracle for each outcome. See the [design standard](../../standards/technical-design.md) and [architecture design](../../docs/design/runtime-design.md).
