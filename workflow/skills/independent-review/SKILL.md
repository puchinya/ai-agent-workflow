---
name: independent-review
description: Review an exact PR subject in a separate context and record evidence-backed findings.
---
# Independent review

## One-time Issue #63 / PR #64 adoption context

No ordinary Independent Review may be recorded before the exact post-CI #63/#64 adoption is applied. Afterwards the host supplies the exact current implementation identity to the child: `execution-binding:<digest>` for a normal V1 binding or `execution-adoption:<epoch-sha256>` for the adopted epoch. The child records that value in `implementation_binding_id`; never fabricate a legacy V1 ID for an adopted epoch. Every review still binds the current exact PR HEAD, ADC, full contract, checklist, diff, and test evidence. Adoption approval is not User Review or merge approval.

For a later approved ADC on the same #63 adopted epoch, the child continues to bind the unchanged `execution-adoption:<epoch-sha256>` identity. The current ADC generation is separately established by its approved forward chain, completed V2 Phase pair, and latest PRBinding V3; do not substitute the new ADC or PRBinding digest for the immutable implementation identity.

## Owner and inputs

Owner: the active host owns subagent lifecycle and provenance; `runtime/p_ases/audits.py` validates and records the existing review artifact. Inputs are the exact approved ADC/Contract, Issue/PR identity, HEAD, complete diff, every checklist item, test evidence, implementation binding ID, and host-reported spawn/session and reviewer IDs.

## Workflow

1. The host must actually spawn and join a dedicated fresh native subagent, isolated from the implementation context, and obtain its review result. If native delegation fails, join status is unknown, or no child result is returned, stop with `INDEPENDENT_SUBAGENT_UNAVAILABLE`. Missing host IDs alone do not mean the child review did not happen. Do not use a same-agent second prompt, a human fallback, or User Review as a substitute.
2. The child reads the exact repository, Issue, PR, current HEAD, approved ADC/Contract, complete source diff, complete contract, checklist, and test evidence. The host supplies the current implementation identity and any available spawn/session metadata.
3. The child inspects every contract section and checklist item, classifies findings with severity and evidence, and authors the raw result. In `PASES_INDEPENDENT_REVIEW_CONTEXT_V1`, `context_id` is the child context. The `provenance` string may contain compact canonical JSON with `spawn_session_id`, `reviewer_id`, and `implementation_binding_id`; omit unavailable IDs or set them to null. The parent MUST NOT edit findings, verdict, context ID, or provenance. Distinct context IDs alone do not prove host authenticity.
4. The parent compares every available provenance value against host metadata and the exact current `execution-binding:<digest>` or `execution-adoption:<epoch-sha256>`, then passes the unchanged child result to `audit independent`. An available mismatching binding or known same-context spawn/reviewer identity blocks; unavailable IDs do not. The runtime stores `PASES_INDEPENDENT_REVIEW_V2`: confidence is `HIGH` when all three IDs are present and match, otherwise `LIMITED`, with the unavailable values recorded explicitly. Do not fabricate IDs, add a spawn API to the Python CLI, or invoke another coding-agent executable from it. The runtime stores the child artifact digest and identity context but does not authenticate host metadata itself.
5. A/B findings, blocking C findings, checklist failures, stale HEAD, no child result, or failed/unknown spawn or join block. Missing host IDs alone do not block a valid child result; disclose `LIMITED` confidence. After a fix produces a new HEAD, the host starts a new child review; do not repeat on the same HEAD without progress. D findings remain non-blocking.
6. After child PASS, inspect current Phase, Binding, Verification, Acceptance, Self-Audit, and Required CI while the Issue remains in `execution`. Blocking findings are fixed there and each new HEAD gets a fresh child. Only if all are current and PASS, run `issue advance ISSUE verification` and read it back, then `delivery readiness`; if it passes, start `user-review start` automatically without extra confirmation to start. Never fabricate the user's final User Review decision.
7. Preserve ordinary product review gates. Issue #32's fixed Bootstrap waiver only waives review procedure for that PR.

## Lifecycle handoff

For ordinary single/child Issues, the host follows one sequence: approved ADC and optional Phase rebaseline; exact frozen Binding; specification/design/Test Oracle artifacts and receipts; `ready`; `execution`; implementation; current Verification, Acceptance, Self-Audit, and a fresh native Independent Review; `verification`; Review Readiness; then `user-review start`. Blocking review findings are fixed while phase is `execution`, and every changed HEAD gets a fresh child review. Only after the complete current PASS set may the host advance to `verification`; a required code change after that phase blocks as `BLOCKED_PHASE_REWORK_DECISION_REQUIRED`. CLI commands remain one-shot mutations/readbacks; Skills and adapters own orchestration.

Readiness cannot newly PASS outside `verification`; in `user-review`, it may only reproduce the exact subject and Readiness SHA already held by the immutable session. User Review checks phase before writing a session or feedback snapshot. In `verification`, `start` may create one session; in `user-review`, only a matching existing session may resume. If interruption leaves the exact session in `verification`, `sync` preserves its `started_at`, completes snapshot readback, and performs the normal Phase update/readback. Missing or mismatched sessions block without overwrite. `PENDING` (exit code 2) is ordinary waiting; report `WAITING_USER_REVIEW_DECISION` only after reading back the session, complete feedback snapshot, and `phase:user-review`. This does not record approval.

## CLI

~~~sh
python -m p_ases audit independent 32 42 HEAD40 path/to/plan.json path/to/independent-review.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

Missing/unavailable native child result, same-context review, available mismatching binding, mismatched PR/HEAD/ADC, unresolved blocking finding, failed checklist, or failed/unknown spawn/join remains non-passing. Missing spawn/session, reviewer, or implementation-binding IDs alone are recorded as `LIMITED` confidence and do not block a valid joined child result. Report exactly what was reviewed and which provenance identifiers were unavailable; never fabricate independent review, readiness, or user approval.

Next owners: user-review receives human feedback; delivery-control checks exact readiness. See the [review design](../../../docs/design/workflow-design.md).
