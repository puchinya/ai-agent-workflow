---
name: user-review
description: Capture, synchronize, and evaluate human feedback for the exact current PR subject.
---
# User review

## Owner and inputs

Owner: runtime/p_ases/user_review.py. Inputs are an open PR, current HEAD, approved ADC, final Verification, completed Acceptance, current Readiness V1 `PASS` or exact-subject Readiness V2 `READY_WITH_EXCEPTION`, and GitHub feedback surfaces or a trusted host-attested direct-chat event.

## Workflow

1. Before every start, sync, or status evaluation, recompute the saved Readiness from current Verification/Required Checks, Acceptance observations, Self-Audit evidence, dependencies, PR/work bindings, profile, review evidence, and any Owner exception. This read-only recomputation must match the saved V1/V2 result; repeat it before any session, snapshot, result, or phase write.
2. Read the Issue's unique live `kind:*`, `phase:*`, and `attention:*` labels. The actual kind label is authoritative; reject a conflicting `--kind`, `phase:execution` or any other invalid source phase, and active attention before creating User Review files. Read the same Issue identity/labels again before a phase update.
3. Start a review session bound to the exact Issue, PR, HEAD, and plan.
4. Synchronize conversation comments, formal reviews, inline comments, and review threads with pagination and edit/deletion readback.
5. Treat changed HEAD as stale and restart only from current state.
6. Record direct-chat decisions only through a trusted host verifier. Raw caller JSON is not identity authority.
7. Route newly requested scope to requirements; do not silently absorb it into the current contract.
8. When a valid Readiness V2 exception is selected, retain the visible `review_assurance=UNAVAILABLE` and `INDEPENDENT_REVIEW_NOT_PERFORMED` risk. Reject malformed, duplicate, or conflicting exception receipts for the same HEAD on every read. The exception does not count as an independent review or replace the separate human User Review decision.

## CLI

~~~sh
python -m p_ases user-review start 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review sync 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review status 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review start 46 67 HEAD40 path/to/plan.json path/to/readiness-v2.json --review-unavailable-exception path/to/exception.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases user-review record 32 42 path/to/host-event.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

Edited/deleted feedback history, unresolved threads, stale HEAD, changed non-review gates, invalid Issue phase/kind/attention, conflicting exception history, missing user decision, invalid host identity, or incomplete Acceptance blocks approval before relevant persistence. The current CLI intentionally fails closed for untrusted direct-chat payloads. Output subject, synchronized feedback, decision, and blockers. User Review is not merge authorization.

Next owners: integration-validation handles parent feedback; delivery-control keeps merge permission separate. See the [User Review specification](../../docs/specs/workflow-spec.md).
