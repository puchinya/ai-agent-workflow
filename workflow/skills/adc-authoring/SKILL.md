---
name: adc-authoring
description: Author measurable Agent Development Contracts from an explicit user request.
---
# ADC authoring

## Owner and inputs

Owner: runtime/p_ases/adc.py. Inputs are an explicitly authorized request, repository and Issue identity, applicable product specifications, and the canonical ADC template. Requirements must state observable acceptance conditions; include scope, architecture decisions, affected artifacts, exact changes, invariants, non-goals, verification obligations, checklist, and completion gates. Workflow or delivery policy changes must preserve existing profile defaults, name accepted trust sources and failure statuses, bind evidence to an exact subject, and state which GitHub mutations remain outside the implementation.

## Workflow

1. Confirm the request's source and execution intent with request-intake.
2. Read the current approved pointer before proposing a successor. Preserve immutable predecessor comments and their exact bytes.
3. Draft requirement IDs and measurable outcomes without deriving the Oracle from the implementation.
4. Validate the local candidate. Validation is syntax and structure checking; it does not approve content.
5. Present the complete draft for the user's decision. Publish as approved only after an explicit approval for those exact bytes.
6. For profile, Activation, or branch-policy work, specify whether a committed profile change needs a successor Activation and separate owner/admin approval. Do not make an ADC or profile value imply GitHub protection edits, merge authority, or Issue closure.

## CLI

~~~sh
python -m p_ases adc validate 32 path/to/contract.md --repo OWNER/REPO
python -m p_ases adc publish 32 path/to/contract.md --state draft --repo OWNER/REPO
python -m p_ases adc publish 32 path/to/contract.md --state approved --repo OWNER/REPO
~~~

The approved publication example is permitted only after the user has approved the exact contract. Use the supersede option only for a genuinely approved successor.

## Failure handling and output

Malformed sections, duplicate requirement IDs, secret-like content, wrong repository or Issue, changed source bytes, stale pointer history, or uncertain approval blocks publication. Report the candidate hash and byte length only after validation. Never alter historical ADC comments or claim that validation grants execution authority, branch-policy mutation, merge, or closure of a source Issue.

Next owner: adc-registry verifies the published pointer; issue-decomposition consumes approved requirements. See the [ADC specification](../../../docs/specs/workflow-spec.md).
