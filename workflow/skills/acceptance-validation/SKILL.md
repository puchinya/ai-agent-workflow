---
name: acceptance-validation
description: Evaluate whether a produced artifact satisfies its independent acceptance plan.
---
# Acceptance validation

## Owner and inputs

Owner: runtime/p_ases/acceptance.py. Inputs are the exact ADC and PR subject, frozen Verification Plan, typed artifact-specific observations, final Verification result, and acceptance Oracles.

## Workflow

1. Confirm the artifact type and current PR HEAD.
2. Prepare a subject-bound observation template and fill it only with actual observations.
3. Validate every acceptance case against its independent Oracle and final Verification.
4. Publish and verify the recomputed result after all required observations pass.
5. Keep P-ASES parent acceptance separate from child acceptance and ordinary User Review.

## CLI

~~~sh
python -m p_ases acceptance prepare 32 42 HEAD40 path/to/plan.json spec_change path/to/observations.json --repo OWNER/REPO --root .
python -m p_ases acceptance validate 32 42 HEAD40 path/to/plan.json spec_change path/to/observations.json path/to/verification.json --repo OWNER/REPO --root .
python -m p_ases acceptance publish 32 path/to/result.json --repo OWNER/REPO --root .
python -m p_ases acceptance verify 32 path/to/result.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

Missing evidence, changed artifact, stale subject, failed Verification, wrong artifact type, or mismatched publication readback remains non-success. Do not convert incomplete or manually asserted data to PASS. Output each case status, result digest, and evidence reference.

Next owner: integration-validation combines completed child evidence. See the [acceptance design](../../../docs/design/workflow-design.md).
