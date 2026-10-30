---
name: contract-audit
description: Check the final change against every approved contract requirement and invariant.
---
# Contract audit

## One-time Issue #63 / PR #64 adoption

Do not audit or publish ordinary PASS evidence against the missing historical Binding. The one-time bootstrap may be implemented before adoption, but its code/readability review is not an Independent Review artifact and no ordinary Phase/QA/Readiness PASS is allowed yet. Wait until bootstrap is pushed, exact-final-HEAD CI is green, and a separate exact-plan V3 `EXECUTION_ADOPTION` owner decision has been applied. After verified adoption, bind every audit to the adopted epoch and current HEAD, then use the normal contract-audit and fresh Independent Review process. Do not treat adoption as `USER_REVIEW`, `RULESET_PLAN_APPLY`, `Activation`, or merge approval.

## Owner and inputs

Owner: runtime/p_ases/audits.py. Inputs are the verified ADC, current PR HEAD, requirement and checklist identifiers, source diff, and evidence references.

## Workflow

1. Read the exact approved contract and verify its current pointer.
2. Compare each requirement and invariant against the final diff and exact-HEAD evidence.
3. Record PASS, FAIL, or UNTESTED with concrete source, test, or Actions references.
4. Treat missing approval, changed scope, unsafe paths, or stale evidence as blockers.
5. Keep the Bootstrap #32 review-procedure waiver scoped to its fixed implementation process; it does not change product runtime requirements.
6. After self-review passes, hand off to a dedicated fresh host-native subagent for Independent Review. The host must spawn and join it and obtain the child-authored result. The child records `context_id` as its context, one evidence-backed `review_units` result for every required ADC requirement/checklist ID, typed `blocks_readiness` values for findings, and any available `spawn_session_id`, `reviewer_id`, and `implementation_binding_id` values in canonical JSON in `provenance`. The parent compares every available ID with host metadata/current binding, then passes the unchanged V2 context artifact to `audit independent`. Missing IDs alone do not block; the resulting V3 record reports `LIMITED` confidence and missing values. An incomplete/duplicate/unknown review unit, available mismatch, absent child result, failed/unknown spawn or join, or same-context result blocks. The child must read the full approved Contract, checklist, exact PR/HEAD, full diff, and test evidence, then author its own findings and unit results. The implementation context cannot author, edit, or replace that result.

## Lifecycle handoff

For ordinary single/child Issues, the host follows one sequence: approved ADC and optional Phase rebaseline; exact frozen Binding; specification/design/Test Oracle artifacts and receipts; `ready`; `execution`; implementation; current Verification, Acceptance, Self-Audit, and a fresh native Independent Review; `verification`; Review Readiness; then `user-review start`. Blocking review findings are fixed while phase is `execution`, and every changed HEAD gets a fresh child review. Only after the complete current PASS set may the host advance to `verification`; a required code change after that phase blocks as `BLOCKED_PHASE_REWORK_DECISION_REQUIRED`. CLI commands remain one-shot mutations/readbacks; Skills and adapters own orchestration.

Readiness cannot newly PASS outside `verification`; in `user-review`, it may only reproduce the exact subject and Readiness SHA already held by the immutable session. User Review checks phase before writing a session or feedback snapshot. In `verification`, `start` may create one session; in `user-review`, only a matching existing session may resume. If interruption leaves the exact session in `verification`, `sync` preserves its `started_at`, completes snapshot readback, and performs the normal Phase update/readback. Missing or mismatched sessions block without overwrite. `PENDING` (exit code 2) is ordinary waiting; report `WAITING_USER_REVIEW_DECISION` only after reading back the session, complete feedback snapshot, and `phase:user-review`. This does not record approval.

## CLI

~~~sh
python -m p_ases audit self 32 42 HEAD40 path/to/plan.json path/to/self-audit.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

A requirement without evidence, unresolved contract violation, changed HEAD, unverified ADC, unavailable native child, missing child result, failed/unknown spawn or join, known same-context result, available mismatching binding, incomplete review-unit coverage, or invented PASS blocks the audit. Missing host IDs alone do not block a valid joined child result; record `LIMITED` confidence and identify unavailable IDs. Report each review unit, status, exact evidence, findings, and remediation. A/B findings, child-designated blocking C findings, and failed checklist units block Readiness and User Review. After fixes that change HEAD, run a new child review; do not retry without progress on the same HEAD. The parent may ingest the child's unedited artifact through the existing `audit independent` route, but context-ID distinctness is not proof of host authenticity. Do not add a runtime spawn API or shell out to an agent executable. An audit never authorizes merge or release.

Next owners: independent-review provides separate review; delivery-control checks readiness. See the [ADC specification](../../../docs/specs/workflow-spec.md).
