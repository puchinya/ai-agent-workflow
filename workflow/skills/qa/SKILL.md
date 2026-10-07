---
name: qa
description: Record current-HEAD functional QA cases or a reasoned not-applicable result and publish the evidence.
---
# QA

## Trigger and inputs
Use after `verify-final` and self-review, when the review PR exists and its exact HEAD is stable. Inputs are the approved contract, PR HEAD, testable user-visible or system behavior, and reproducible test evidence. QA runs may use the implementation session; QA never substitutes for self-review or independent PR review.

## Procedure
1. Run `python -m agent_workflow prepare-qa <issue> <pr>` and use the generated `.agent-state/issues/<issue>/qa-pr-<pr>.json` draft.
2. For applicable behavior, provide at least one case with a unique `name`, concrete `action`, `expected` outcome, `result` (`pass`, `fail`, or `untested`), and concrete evidence. Evidence identifies the command/action, outcome, and relevant environment or artifact without credentials.
3. Use `mode: not_applicable` only when QA truly does not apply. Set `cases` to an empty array and give a concrete reason. Do not use N/A to hide unavailable or failed tests.
4. Run `python -m agent_workflow validate-qa <issue> <pr>`. Correct malformed or incomplete evidence and rerun validation. Any new PR commit or contract supersession requires regenerating the record.
5. Run `python -m agent_workflow publish-qa <issue> <pr>`, then `python -m agent_workflow validate-public-qa <issue> <pr>` to confirm the named comment and `## Agent QA` pointer.
6. Report case results and residual uncertainty. A valid but failing or untested record is published as evidence and blocks delivery.

## Output and uncertainty
Delivery accepts only all-PASS cases or a valid N/A record. FAIL, UNTESTED, pending, malformed, credential-bearing, oversized, or stale evidence blocks. QA is an independent gate from Final Verification, self-review, independent review, and Required Checks. See the [runtime specification](../../../docs/specs/runtime-spec.md).
