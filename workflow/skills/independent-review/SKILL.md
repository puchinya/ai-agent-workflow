---
name: independent-review
description: Review an exact PR subject in a separate context and record evidence-backed findings.
---
# Independent review

## Owner and inputs

Owner: runtime/p_ases/audits.py. Inputs are the exact approved ADC, PR number, HEAD, review plan, complete diff, and an independent reviewer context.

## Workflow

1. Establish a separate context from the implementation session. Read back the same PR HEAD and approved ADC before reviewing.
2. Inspect every contract section and checklist item; classify findings with severity and evidence.
3. Record the fresh-context attestation and exact subject. Do not author this artifact from the implementation context.
4. Re-run after HEAD or ADC changes; do not reuse stale review evidence.
5. Preserve ordinary product review gates. Issue #32's fixed Bootstrap waiver only waives review procedure for that PR.

## CLI

~~~sh
python -m p_ases audit independent 32 42 HEAD40 path/to/plan.json path/to/independent-review.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

Same-context review, mismatched PR/HEAD, missing attestation, stale ADC, unresolved blocking finding, or unsupported reviewer identity remains non-passing. Report findings and evidence without fabricating readiness or user approval.

Next owners: user-review receives human feedback; delivery-control checks exact readiness. See the [review design](../../../docs/design/workflow-design.md).
