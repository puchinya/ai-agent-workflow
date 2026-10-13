# Agent Development Contract standard

An Agent Development Contract (ADC) is the Issue-owned implementation authority for one bounded work item. It binds repository and Issue identity, requirements, dependencies, change kind, architecture decisions, exact change set, invariants, verification obligations, acceptance conditions, and reporting obligations.

## Stable obligations

- Give each requirement a stable REQ-AREA-NNN identifier and link it through a design decision and a test or independent Oracle to executable evidence.
- State artifact impact for specifications, designs, tests, and status as create, update, unchanged with a reason, or not applicable with a reason. For changed specification, design, or test/Oracle artifacts, name every committed path under `docs/specs/`, `docs/design/`, or `docs/testing/` in its matching row.
- Use the approved specification/design unchanged reason as the matching phase-skip reason. The runtime receipt records the reason but does not approve or expand the ADC.
- Every ordinary single/child phase transition verifies the actual kind label, current approved ADC, and Activation/Gate Selection. Transitions into `specification`, `design`, or `ready` additionally require a `PASES_PHASE_DECISION_V1` receipt bound to this ADC generation and the Issue's frozen dedicated branch/base/worktree. Stage receipts validate only the artifacts needed through that stage, then verify the complete predecessor chain and unchanged completed artifact hashes. `ready -> execution` rechecks the current ready receipt and binding before the label write. Parent #26 and fixed Bootstrap Issues #27–#32 keep their migration-specific path.
- Before `ready`, include `docs/testing/traceability.md` in the Testing artifact paths and ensure each ADC requirement reaches a design, independent Oracle, test case, and existing test source. The ready receipt verifies each canonical target, actual anchor, committed bytes, declared artifact path or explicit unchanged decision, and executable source in the branch commit.
- Pin source decisions and upstream contracts to immutable commit or comment identities when required.
- Treat published ADC comments as immutable. Supersede a contract by publishing a new comment and pointer record; do not edit an older ADC or restore its pointer without an explicit workflow operation.
- Report implementation choices that are not fixed by the ADC. Stop dependent work when a choice would materially change architecture or scope.
- Record only commands and results that were actually observed. A skipped or unavailable environment remains unverified.

## Repository tools

Use python -m p_ases adc validate, publish, verify, or restore for P-ASES ADC operations. The runtime validates bytes and comment pointers; it does not invent user approval or merge authorization.

## Related resources

Use the [ADC template](../templates/adc-template.md), [product specification standard](product-specification.md), [technical design standard](technical-design.md), and [test specification standard](test-specification.md).
