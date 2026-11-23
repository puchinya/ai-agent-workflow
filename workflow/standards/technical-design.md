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

## Issue-neutral architecture (required)

A P-ASES feature MUST be designed for all eligible Issues/PRs, not only the ticket that requested it.

- **No subject-number dispatch:** Generic runtime/CLI, workflow gates, Phase, authentication, PR association, work Binding, adoption, evidence, recovery, and delivery MUST NOT branch on literal Issue/PR numbers, issue-specific branch names or hardcoded `.p_ases/state/<number>` paths. A one-entry lookup table, special configuration flag, or proxy such as a matching PR number is equivalent to hardcoding and is also forbidden.
- **Validated subjects as data:** Issue/PR numbers MAY appear in input, immutable evidence, URLs built from checked subjects, log records, and test fixtures. Generic behavior MUST instead follow the validated repository/owner identities, Issue and PR readbacks, approved ADC, schema/capability, execution epoch, PRBinding, exact HEAD, operation plan, owner decision, and supported lifecycle state. Never infer missing approval from an Issue number.
- **Historical compatibility, not precedent:** A narrowly scoped, separately authorized legacy adapter MAY retain literal numbers and immutable hashes only to verify, reconcile, or finish an existing approved migration without changing its original authorization contract. Such exceptions MUST identify their immutable source and scope, preserve canonical bytes and digest semantics, and be isolated from new generic write paths. No new single-Issue behavior is permitted merely because an earlier historical migration used one.
- **Design before implementation:** State the generic ownership/lifetime, failure and retry semantics, compatibility behavior, source references, and rejected ticket-specific alternatives in the design. A material change to authorization, persistent schema, or lifecycle requires approved specification/ADC changes first. If safe generalization is impossible under the current contract, report a BLOCKER; do not implement a hidden ticket-specific workaround.
- **Acceptance and reviewer gate:** For newly shared behavior, tests MUST demonstrate equivalent normal paths for at least two distinct eligible Issue/PR numbers, refuse cross-Issue/PR/HEAD evidence and approvals, and verify that the sealed historical reader does not enable a new write. Implementation self-review and independent review MUST inspect new literals, mappings, feature flags, and paths for prohibited subject-dependent behavior. Approved historical literals remain confined to documented adapters and their focused fixtures.

## Related resources

Use the [technical design template](../templates/technical-design-template.md), [product specification standard](product-specification.md), and [test specification standard](test-specification.md).
