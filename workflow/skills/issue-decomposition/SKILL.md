---
name: issue-decomposition
description: Split approved requirements into a same-repository Issue DAG with explicit dependencies.
---
# Issue decomposition

## Owner and inputs

Owner: runtime/p_ases/issue_graph.py and runtime/p_ases/phases.py. Inputs are the parent Issue, its approved ADC, requirement IDs, child scopes, dependency edges, acceptance evidence, and repository identity.

## Workflow

1. Build one child proposal per independently executable scope. Link each child to its parent and assign requirement IDs without gaps or duplication.
2. Draw the dependency DAG from the approved architecture. Do not use stacked feature branches when the contract requires children to target main.
3. Validate every child has measurable acceptance conditions, an owner, and verification obligations.
4. Review the proposed Issue set with the user before creation. Native Issue creation must preserve exact links and read back each result.
5. Advance phase labels only through the implemented issue route. Never use phase labels as proof of verification or approval.

## CLI

~~~sh
python -m p_ases issue validate-split path/to/split-plan.json --repo OWNER/REPO
python -m p_ases issue split path/to/split-plan.json --dry-run --repo OWNER/REPO
python -m p_ases issue integration-check 26 --repo OWNER/REPO --root .
~~~

Omit dry-run only when the approved contract authorizes creation and the complete plan has been validated.

## Failure handling and output

Duplicate or missing requirement IDs, cycles, unavailable dependencies, foreign repositories, existing conflicting children, closed Issues, or a mismatched ADC block the operation. Return the planned children, exact DAG, and validation result. Do not silently change scope or create a partial substitute graph.

Next owners: product-specification, technical-design, and integration-validation. See the [workflow specification](../../../docs/specs/workflow-spec.md).
