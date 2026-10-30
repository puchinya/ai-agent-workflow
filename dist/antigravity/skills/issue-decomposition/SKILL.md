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
6. For an ordinary Issue, establish the dedicated branch and frozen work binding before committing phase artifacts. Every ordinary phase change verifies the actual kind, current approved ADC, and Activation/Gate Selection. Specification, design, and ready transitions also require a `PASES_PHASE_DECISION_V1` receipt from `issue phase-evidence`, then the exact returned comment ID on `issue advance`. Each later receipt validates the predecessor receipt and preserves its completed artifact hashes. If implementation commits have advanced the branch after the READY receipt, refresh that existing READY proof at the exact current HEAD before entering execution; the refresh is append-only, requires the same ADC, binding, labels, Issue body, and completed artifact hashes, and does not change Issue labels or authorize work. An exact repeat is read-only. Ready-to-execution then revalidates the current ready proof and binding. The receipt proves bytes and identity only; the approved ADC remains the decision authority. The host continues `ready` → `execution`, and keeps the Issue in `execution` through implementation, Verification, Acceptance, Self-Audit, and a fresh Independent Review. Only the complete current PASS set permits `issue advance ISSUE verification`; no implicit verification-to-execution edge is allowed.

## Lifecycle handoff

For ordinary single/child Issues, the host follows one sequence: approved ADC and optional Phase rebaseline; exact frozen Binding; specification/design/Test Oracle artifacts and receipts; `ready`; `execution`; implementation; current Verification, Acceptance, Self-Audit, and a fresh native Independent Review; `verification`; Review Readiness; then `user-review start`. Blocking review findings are fixed while phase is `execution`, and every changed HEAD gets a fresh child review. Only after the complete current PASS set may the host advance to `verification`; a required code change after that phase blocks as `BLOCKED_PHASE_REWORK_DECISION_REQUIRED`. CLI commands remain one-shot mutations/readbacks; Skills and adapters own orchestration.

Readiness cannot newly PASS outside `verification`; in `user-review`, it may only reproduce the exact subject and Readiness SHA already held by the immutable session. User Review checks phase before writing a session or feedback snapshot. In `verification`, `start` may create one session; in `user-review`, only a matching existing session may resume. If interruption leaves the exact session in `verification`, `sync` preserves its `started_at`, completes snapshot readback, and performs the normal Phase update/readback. Missing or mismatched sessions block without overwrite. `PENDING` (exit code 2) is ordinary waiting; report `WAITING_USER_REVIEW_DECISION` only after reading back the session, complete feedback snapshot, and `phase:user-review`. This does not record approval.

## CLI

~~~sh
python -m p_ases issue validate-split path/to/split-plan.json --repo OWNER/REPO
python -m p_ases issue split path/to/split-plan.json --dry-run --repo OWNER/REPO
python -m p_ases issue phase-evidence 123 requirements specification --repo OWNER/REPO --root .
python -m p_ases issue advance 123 specification --kind child --phase-evidence-comment-id COMMENT_ID --root . --repo OWNER/REPO
python -m p_ases issue phase-refresh-ready 123 --repo OWNER/REPO --root .
python -m p_ases issue advance 123 execution --kind child --root . --repo OWNER/REPO
~~~

Omit dry-run only when the approved contract authorizes creation and the complete plan has been validated.

## Failure handling and output

Duplicate or missing requirement IDs, cycles, unavailable dependencies, foreign repositories, existing conflicting children, closed Issues, or a mismatched ADC block the operation. Return the planned children, exact DAG, and validation result. Do not silently change scope or create a partial substitute graph.

Next owners: product-specification, technical-design, and integration-validation. See the [workflow specification](../../docs/specs/workflow-spec.md).
