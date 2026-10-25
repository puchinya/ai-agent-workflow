---
name: user-review
description: Capture, synchronize, and evaluate human feedback for the exact current PR subject.
---
# User review

## Owner and inputs

Owner: runtime/p_ases/user_review.py. Inputs are an open PR, current HEAD, approved ADC, final Verification, completed Acceptance, current Readiness V1 `PASS` or exact-subject provenance-exception Readiness, GitHub feedback surfaces, and the active chat decision UI.

## Workflow

1. Before every start, sync, or status evaluation, recompute the saved Readiness from current Verification/Required Checks, Acceptance observations, Self-Audit evidence, dependencies, PR/work bindings, profile, review evidence, and any Owner exception. This read-only recomputation must match the saved V1/V2 result; repeat it before any session, snapshot, result, or phase write.
2. Read the Issue's unique live `kind:*`, `phase:*`, and `attention:*` labels. The actual kind label is authoritative; reject a conflicting `--kind`, `phase:execution` or any other invalid source phase, and active attention before creating User Review files. Read the same Issue identity/labels again before a phase update.
3. Start a review session bound to the exact Issue, PR, HEAD, and plan.
4. Synchronize conversation comments, formal reviews, inline comments, and review threads with pagination and edit/deletion readback.
5. Treat changed HEAD as stale and restart only from current state.
6. Request the User Review decision in the active chat UI after showing the exact session, HEAD, readiness, feedback digest, unresolved threads, and consequences. Offer `承認する` and `承認しない`. Only the direct answer to that active request is used; record an affirmative answer as `operator_reported_chat` and validate the technical record before User Review persistence. Do not claim cryptographic chat-origin proof or require an Owner-authored Issue/PR approval comment.
7. Route newly requested scope to requirements; do not silently absorb it into the current contract.
8. When a provenance exception is selected, retain the visible `review_assurance=UNAVAILABLE` and `INDEPENDENT_REVIEW_PROVENANCE_UNAVAILABLE` risk. Before asking for exception approval, the current exact-subject `PASES_INDEPENDENT_REVIEW_V2` and linked `PASES_INDEPENDENT_REVIEW_OCCURRENCE_V1` must show `review_occurrence=COMPLETED`, the separate-context review, its actual verdict, and findings. Reject a missing report, non-PASS verdict, unresolved A/B/C finding, malformed, duplicate, or conflicting exception receipt for the same HEAD. `UNAVAILABLE` never means the review was skipped and never replaces the separate human User Review decision.

## CLI

~~~sh
python -m p_ases user-review start 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review sync 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review status 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review start 46 67 HEAD40 path/to/plan.json path/to/readiness-v2.json --review-unavailable-exception path/to/exception.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases chat-decision record 46 67 USER_REVIEW USER_REVIEW_SUBJECT_SHA256 path/to/user-review-scope.json QUESTION_ITEM_ID '承認する' --repo puchinya/ai-agent-workflow --root .
python -m p_ases user-review sync 46 67 HEAD40 path/to/plan.json path/to/readiness-v2.json --review-unavailable-exception path/to/exception.json --chat-decision-comment-id DECISION_COMMENT_ID --repo puchinya/ai-agent-workflow --root .
python -m p_ases user-review record 32 42 path/to/host-event.json --repo OWNER/REPO --root .
~~~

For Issue #46, `user-review start` opens the review session and reports an exact chat approval scope. Present that scope and the PR's review surface in the active chat UI before recording the user's answer. A `承認しない` answer creates no decision record; do not pass it to an affirmative path.

## Failure handling and output

Edited/deleted feedback history, unresolved threads, stale HEAD, changed non-review gates, invalid Issue phase/kind/attention, conflicting exception history, missing user decision, invalid recorder identity, or incomplete Acceptance blocks approval before relevant persistence. Legacy `user-review record` still fails closed for untrusted chat payload files; Issue #46 uses the separate operator-reported active-chat decision record. Output subject, synchronized feedback, decision, review occurrence/outcome/provenance, and blockers. User Review is not merge authorization.

Next owners: integration-validation handles parent feedback; delivery-control keeps merge permission separate. See the [User Review specification](../../docs/specs/workflow-spec.md).
