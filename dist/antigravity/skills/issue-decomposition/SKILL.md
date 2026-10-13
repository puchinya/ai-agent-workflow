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
5. New children start with verified `kind:child` and `phase:requirements` labels. Reused children retain their current phase; never reset them to requirements.
6. For an ordinary Issue, establish the dedicated branch and frozen work binding before committing phase artifacts. Every ordinary phase change verifies the actual kind, current approved ADC, and Activation/Gate Selection. Specification, design, and ready transitions also require a `PASES_PHASE_DECISION_V1` receipt from `issue phase-evidence`, then the exact returned comment ID on `issue advance`. Each later receipt validates the predecessor receipt and preserves its completed artifact hashes. Ready-to-execution revalidates the current ready receipt and binding. The receipt proves bytes and identity only; the approved ADC remains the decision authority.

## CLI

~~~sh
python -m p_ases issue validate-split path/to/split-plan.json --repo OWNER/REPO
python -m p_ases issue split path/to/split-plan.json --dry-run --repo OWNER/REPO
python -m p_ases issue phase-evidence 123 requirements specification --repo OWNER/REPO --root .
python -m p_ases issue advance 123 specification --kind child --phase-evidence-comment-id COMMENT_ID --root . --repo OWNER/REPO
~~~

Omit dry-run only when the approved contract authorizes creation and the complete plan has been validated.

## Failure handling and output

Duplicate or missing requirement IDs, cycles, unavailable dependencies, foreign repositories, existing conflicting children, closed Issues, or a mismatched ADC block the operation. Return the planned children, exact DAG, and validation result. Do not silently change scope or create a partial substitute graph.

Next owners: product-specification, technical-design, and integration-validation. See the [workflow specification](../../docs/specs/workflow-spec.md).
