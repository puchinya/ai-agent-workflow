# Agent Development Contract standard

An Agent Development Contract (ADC) is the Issue-owned implementation authority for one bounded work item. It binds repository and Issue identity, requirements, dependencies, change kind, architecture decisions, exact change set, invariants, verification obligations, acceptance conditions, and reporting obligations.

## Stable obligations

- Give each requirement a stable REQ-AREA-NNN identifier and link it through a design decision and a test or independent Oracle to executable evidence.
- State artifact impact for specifications, designs, tests, and status as create, update, unchanged with a reason, or not applicable with a reason. For changed specification, design, or test/Oracle artifacts, name every committed path under `docs/specs/`, `docs/design/`, or `docs/testing/` in its matching row.
- Use the approved specification/design unchanged reason as the matching phase-skip reason. The runtime receipt records the reason but does not approve or expand the ADC.
- Ordinary single/child transitions into `specification`, `design`, or `ready` require a `PASES_PHASE_DECISION_V1` receipt bound to this approved ADC, its actual kind label, the current branch commit, and the declared document bytes. Parent #26 and fixed Bootstrap Issues #27–#32 keep their migration-specific path.
- Before `ready`, include `docs/testing/traceability.md` in the Testing artifact paths and ensure each ADC requirement reaches a design, independent Oracle, test case, and existing test source.
- Pin source decisions and upstream contracts to immutable commit or comment identities when required.
- Treat published ADC comments as immutable. Supersede a contract by publishing a new comment and pointer record; do not edit an older ADC or restore its pointer without an explicit workflow operation.
- Report implementation choices that are not fixed by the ADC. Stop dependent work when a choice would materially change architecture or scope.
- Record only commands and results that were actually observed. A skipped or unavailable environment remains unverified.

## Repository tools

Use python -m p_ases adc validate, publish, verify, or restore for P-ASES ADC operations. The runtime validates bytes and comment pointers; it does not invent user approval or merge authorization.

## Related resources

Use the [ADC template](../templates/adc-template.md), [product specification standard](product-specification.md), [technical design standard](technical-design.md), and [test specification standard](test-specification.md).
