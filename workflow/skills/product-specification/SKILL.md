---
name: product-specification
description: Turn approved requirements into a user-facing product specification with independent acceptance outcomes.
---
# Product specification

## Owner and inputs

Owner: workflow/standards/product-specification.md, workflow/templates/product-spec-template.md, and docs/specs/. Inputs are approved requirement IDs, user-visible behavior, supported application profiles, and existing product constraints.

## Workflow

1. State user goals and observable behavior before choosing implementation details.
2. Give every normative requirement a stable REQ identifier and a result that can be observed independently.
3. Record unsupported states, accessibility, error behavior, privacy, and compatibility where they affect the user.
4. Link the exact specification in the Issue's Document impact section and retain stable traceability anchors.
5. Ask the user to resolve conflicting or missing behavior before an implementation contract is approved.

## CLI

~~~sh
python -m p_ases docs validate --root .
~~~

The CLI validates document structure, local links, and traceability. It does not author or approve a product specification.

## Failure handling and output

Do not turn design preferences into product requirements without approval. Conflicting requirements, missing REQ IDs, unverifiable outcomes, or a broken owner link block completion. Output the specification, requirement-to-evidence map, and unresolved decisions.

Next owner: technical-design maps approved behavior to components. See the [specification standard](../../standards/product-specification.md) and [workflow specification](../../../docs/specs/workflow-spec.md).
