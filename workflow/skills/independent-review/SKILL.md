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
3. Build the review request from the current `VerificationSubject.as_dict()` returned by the runtime. The child-authored `PASES_CHILD_REVIEW_OUTPUT_V1` must contain exactly `findings`, `reviewer_context_id`, `schema`, `subject`, and `verdict`; `subject` must contain the exact seven canonical fields `repository`, `issue_number`, `pr_number`, `adc_comment_id`, `adc_sha256`, `plan_sha256`, and `pr_head_sha40`. Do not substitute a shortened `{repo, issue, pr, head}` object.
4. Each finding must contain exactly `description`, `evidence_ref`, `finding_id`, `resolved`, and `severity`. Use only severity `A`, `B`, or `C`; finding IDs must be unique and sorted lexicographically. Return an empty finding list when there are no findings. Do not add `INFO` findings or extra fields.
5. Capture the exact native delegation request, terminal return, and child-authored output bytes. Record their digests and the exact subject in V2. Do not replace native bytes with a parent-authored summary, normalize a child's output after the call, or repair a prior malformed result. Reissue a new exact-subject review after any request or subject correction.
6. Re-run after HEAD, ADC, Verification Plan, Binding, or profile changes; do not reuse stale review evidence.
7. Preserve ordinary product review gates. Issue #32's fixed Bootstrap waiver only waives review procedure for that PR.

V2 separates review occurrence from provenance assurance. `HOST_VERIFIED` requires a real trusted host event verifier; agent-writable logs and Hook files do not qualify. `INDEPENDENT_ATTESTED` records `operator_captured_native_tool_result` and proves tamper evidence after capture, not cryptographic host authentication. The `host_spawn_id`, `host_child_id`, and `host_join_id` fields remain null when the host does not expose them. A self-consistent JSON bundle supplied by the implementation agent does not prove that native delegation occurred. The current adapters have no host-capture boundary, so such a record evaluates to effective assurance `UNAVAILABLE` and blocks Readiness.

The project profile sets `independent_review.minimum_assurance`. Omission means `host_verified`. Select `independent_attested` only in committed project configuration when that assurance is accepted; do not use a host, issue, comment, or one-run override. Current adapters validate captured bytes but are not connected to live host delegate APIs, and no trusted host-event verifier is configured. The current host/OS status is recorded in `docs/status/issue-46-review-assurance.md`.

For Issue #46 / PR #67 only, the approved successor ADC defines a separate, opt-in path when host-to-runtime native capture is positively observed as unavailable. That path records `review_assurance=UNAVAILABLE` and `INDEPENDENT_REVIEW_NOT_PERFORMED`; it never creates a review PASS. Use its exact-subject exception plan and separate Owner-posted approval only after the required phase/document rebaseline. A genuine failed review, unresolved A/B/C finding, stale evidence, missing Verification Plan, or failed non-review gate remains blocking. The exception is not reusable for other repositories or Issues.

The exception plan is read-only and binds the current approved ADC, frozen Verification Plan, PR/base/HEAD, both bindings, profile, host capability observation, and accepted risk. The Owner must post the exact approval text printed by the plan command; the runtime must never post it on the Owner's behalf. Apply writes a separate implementation-authored receipt only after direct/list/direct Owner-comment verification. The Owner grant is account-authenticated operational provenance, not a host signature.

## CLI

~~~sh
python -m p_ases audit independent 32 42 HEAD40 path/to/plan.json path/to/independent-review.json --repo OWNER/REPO --root .
~~~

For V2 native capture, the `audit independent` input schema is `PASES_NATIVE_REVIEW_CAPTURE_INPUT_V1` and carries canonical base64+SHA-256 objects for the native request, successful terminal return, and child output, plus the exact subject, Binding identity, and profile digest. V1 inputs remain readable but cannot satisfy current Readiness.

For the Issue #46 capture-unavailable path:

~~~sh
python -m p_ases delivery review-unavailable-plan 46 67 HEAD40 path/to/frozen-plan.json --host-surface codex_cloud --output /tmp/review-unavailable-plan.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery review-unavailable-apply 46 67 HEAD40 path/to/frozen-plan.json --plan /tmp/review-unavailable-plan.json --approval-comment-id OWNER_COMMENT_ID --repo puchinya/ai-agent-workflow --root .
~~~

The plan is unavailable until the exact current Verification is PASS and the PR/worktree/profile/bindings match. After Owner approval and apply, pass the resulting local exception record with `--review-unavailable-exception` to Readiness and User Review. The fallback never substitutes for Verification, Acceptance, Self-Audit, Required CI, dependency checks, or the separate human User Review.

## Failure handling and output

Same-context review, mismatched PR/HEAD, missing terminal completion, changed bytes, stale ADC/profile/Binding, duplicate record, unresolved blocking finding, or unsupported assurance remains non-passing. Report findings and evidence without fabricating host verification, readiness, or user approval.

Next owners: user-review receives human feedback; delivery-control checks exact readiness. See the [review design](../../../docs/design/workflow-design.md).
