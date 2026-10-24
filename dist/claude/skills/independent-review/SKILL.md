---
name: independent-review
description: Review an exact PR subject in a separate context and record evidence-backed findings.
---
# Independent review

## Owner and inputs

Owner: `runtime/p_ases/audits.py` for V1 compatibility and `runtime/p_ases/review_assurance.py` for V2 assurance. Inputs are the exact approved ADC, PR number, HEAD, review plan, complete diff, current ExecutionBinding, committed project profile, and an independent reviewer context.

## Workflow

1. Establish a separate context from the implementation session. Read back the same PR HEAD and approved ADC before reviewing.
2. Inspect every contract section and checklist item; classify findings with severity and evidence.
3. Capture the exact native delegation request, terminal return, and child-authored output bytes. Record their digests and the exact subject in V2. Do not replace native bytes with a parent-authored summary.
4. Re-run after HEAD or ADC changes; do not reuse stale review evidence.
5. Preserve ordinary product review gates. Issue #32's fixed Bootstrap waiver only waives review procedure for that PR.

V2 separates review occurrence from provenance assurance. `HOST_VERIFIED` requires a real trusted host event verifier; agent-writable logs and Hook files do not qualify. `INDEPENDENT_ATTESTED` records `operator_captured_native_tool_result` and proves tamper evidence after capture, not cryptographic host authentication. The `host_spawn_id`, `host_child_id`, and `host_join_id` fields remain null when the host does not expose them. A self-consistent JSON bundle supplied by the implementation agent does not prove that native delegation occurred. The current adapters have no host-capture boundary, so such a record evaluates to effective assurance `UNAVAILABLE` and blocks Readiness.

The project profile sets `independent_review.minimum_assurance`. Omission means `host_verified`. Select `independent_attested` only in committed project configuration when that assurance is accepted; do not use a host, issue, comment, or one-run override. Current adapters validate captured bytes but are not connected to live host delegate APIs, and no trusted host-event verifier is configured. The current host/OS status is recorded in `docs/status/issue-46-review-assurance.md`.

## CLI

~~~sh
python -m p_ases audit independent 32 42 HEAD40 path/to/plan.json path/to/independent-review.json --repo OWNER/REPO --root .
~~~

For V2 native capture, the `audit independent` input schema is `PASES_NATIVE_REVIEW_CAPTURE_INPUT_V1` and carries canonical base64+SHA-256 objects for the native request, successful terminal return, and child output, plus the exact subject, Binding identity, and profile digest. V1 inputs remain readable but cannot satisfy current Readiness.

## Failure handling and output

Same-context review, mismatched PR/HEAD, missing terminal completion, changed bytes, stale ADC/profile/Binding, duplicate record, unresolved blocking finding, or unsupported assurance remains non-passing. Report findings and evidence without fabricating host verification, readiness, or user approval.

Next owners: user-review receives human feedback; delivery-control checks exact readiness. See the [review design](../../docs/design/workflow-design.md).
