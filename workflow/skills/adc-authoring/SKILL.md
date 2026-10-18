---
name: adc-authoring
description: Author measurable Agent Development Contracts from an explicit user request.
---
# ADC authoring

## Owner and inputs

Owner: runtime/p_ases/adc.py. Inputs are an explicitly authorized request, repository and Issue identity, applicable product specifications, and the canonical ADC template. Requirements must state observable acceptance conditions; include scope, architecture decisions, affected artifacts, exact changes, invariants, non-goals, verification obligations, checklist, and completion gates.

## Workflow

1. Confirm the request's source and execution intent with request-intake.
2. Read the current approved pointer before proposing a successor. Preserve immutable predecessor comments and their exact bytes.
3. Draft requirement IDs and measurable outcomes without deriving the Oracle from the implementation.
4. Validate the local candidate. Structural validation does not approve content. For a new approved publication, also run the shared approval-ready preflight against the current verified pointer; it rejects draft/proposal titles, draft-only headers or status, malformed predecessor declarations, and stale predecessor IDs/SHAs.
5. Present the complete final candidate for the user's decision. Publish only after explicit approval for those exact bytes; never normalize or edit the candidate after approval.

## CLI

~~~sh
python -m p_ases adc validate 32 path/to/contract.md --repo OWNER/REPO
python -m p_ases adc publish 32 path/to/contract.md --state draft --repo OWNER/REPO
python -m p_ases adc publish 32 path/to/contract.md --state approved --repo OWNER/REPO
~~~

Approved publication requires an exact user approval and a passing approval-ready preflight tied to the live approved predecessor. The preflight is separate from structural `adc validate`; a draft publication remains unchanged. Use supersede only for a final candidate whose declared predecessor matches the exact current approved pointer.

## Failure handling and output

Malformed sections, duplicate requirement IDs, secret-like content, wrong repository or Issue, changed source bytes, stale pointer history, or uncertain approval blocks publication. Report the candidate hash and byte length only after validation. Never alter historical ADC comments or claim that validation grants execution authority.

Next owner: adc-registry verifies the published pointer; issue-decomposition consumes approved requirements. See the [ADC specification](../../../docs/specs/workflow-spec.md).
