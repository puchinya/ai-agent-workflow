---
name: user-review
description: Capture, synchronize, and evaluate human feedback for the exact current PR subject.
---
# User review

## Owner and inputs

Owner: runtime/p_ases/user_review.py. Inputs are an open PR, current HEAD, approved ADC, final Verification, completed Acceptance, readiness record, selected repository review mode, and GitHub feedback surfaces or a trusted host-attested direct-chat event. The CLI supplies review mode and owner identity only after reading the repository profile and verifying GitHub identities.

## Workflow

1. Start a review session bound to the exact Issue, PR, HEAD, and plan.
2. Synchronize conversation comments, formal reviews, inline comments, and review threads with pagination and edit/deletion readback.
3. Treat changed HEAD as stale and restart only from current state.
4. Record direct-chat decisions only through a trusted host verifier. Raw caller JSON is not identity authority.
5. Route newly requested scope to requirements; do not silently absorb it into the current contract.
6. In the default `external_reviewer` mode, accept the existing authenticated PR review or verified host-chat approval. An Issue comment does not become an approval in this mode.
7. In explicitly configured `solo_owner` mode, require the same personal repository owner, authenticated User, and PR author. The standard approval remains the exact two-line subject-bound Issue decision after immutable session start. Under an approved Issue-specific relay contract, the Cloud route may instead read back the exact repository, Issue, PR, HEAD, and Readiness digest, wait for a distinct direct `USER_REVIEW` confirmation, and have the authenticated ChatGPT GitHub connector submit a formal `APPROVED` PR review with `commit_id` set to that HEAD. Read the formal review back through the usual feedback sync and require the stable owner User ID/type, exact HEAD, post-session timestamp, current Readiness, complete feedback, and no unresolved threads. The formal review object is the evidence; the chat message and owner-decision relay record are not. No generic continuation authorizes this write, and this approval does not satisfy independent review or merge authorization.

## CLI

~~~sh
python -m p_ases user-review start 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review sync 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review status 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review record 32 42 path/to/host-event.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

Edited/deleted feedback history, unresolved threads, stale HEAD, missing user decision, wrong-mode approval carrier, mismatched owner identity, noncanonical Issue permalink, or incomplete Acceptance blocks approval. The current CLI intentionally fails closed for untrusted direct-chat payloads. Output subject, synchronized feedback, decision, and blockers. User Review is not merge authorization.

Next owners: integration-validation handles parent feedback; delivery-control keeps merge permission separate. See the [User Review specification](../../docs/specs/workflow-spec.md).
