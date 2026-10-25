---
name: user-review
description: Capture, synchronize, and evaluate human feedback for the exact current PR subject.
---
# User review

## Owner and inputs

Owner: runtime/p_ases/user_review.py. Inputs are an open PR, current HEAD, approved ADC, final Verification, completed Acceptance, current Readiness V1 `PASS` or exact-subject Readiness V2 `READY_WITH_EXCEPTION`, and GitHub feedback surfaces or a trusted host-attested direct-chat event.

## Workflow

1. Start a review session bound to the exact Issue, PR, HEAD, and plan.
2. Synchronize conversation comments, formal reviews, inline comments, and review threads with pagination and edit/deletion readback.
3. Treat changed HEAD as stale and restart only from current state.
4. Record direct-chat decisions only through a trusted host verifier. Raw caller JSON is not identity authority.
5. Route newly requested scope to requirements; do not silently absorb it into the current contract.
6. When a valid Readiness V2 exception is selected, retain the visible `review_assurance=UNAVAILABLE` and `INDEPENDENT_REVIEW_NOT_PERFORMED` risk. It does not count as an independent review or replace the separate human User Review decision.

## CLI

~~~sh
python -m p_ases user-review start 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review sync 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review status 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review record 32 42 path/to/host-event.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

Edited/deleted feedback history, unresolved threads, stale HEAD, missing user decision, invalid host identity, or incomplete Acceptance blocks approval. The current CLI intentionally fails closed for untrusted direct-chat payloads. Output subject, synchronized feedback, decision, and blockers. User Review is not merge authorization.

Next owners: integration-validation handles parent feedback; delivery-control keeps merge permission separate. See the [User Review specification](../../docs/specs/workflow-spec.md).
