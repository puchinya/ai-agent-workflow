---
name: user-review
description: Capture, synchronize, and evaluate human feedback for the exact current PR subject.
---
# User review

## Owner and inputs

Owner: runtime/p_ases/user_review.py, with runtime/p_ases/user_review_relay.py verifying the dedicated self-authored `solo_owner` carrier. Inputs are an open PR, current HEAD, approved ADC, final Verification, completed Acceptance, readiness record, selected repository review mode, and GitHub feedback surfaces or a trusted host-attested direct-chat event. The CLI supplies review mode and owner identity only after reading the repository profile and verifying GitHub identities.

## Workflow

1. Start a review session bound to the exact Issue, PR, HEAD, and plan.
2. Synchronize conversation comments, formal reviews, inline comments, and review threads with pagination and edit/deletion readback.
3. Treat changed HEAD as stale and restart only from current state.
4. Record direct-chat decisions only through a trusted host verifier. Raw caller JSON is not identity authority.
5. Route newly requested scope to requirements; do not silently absorb it into the current contract.
6. In the default `external_reviewer` mode, accept the existing authenticated PR review or verified host-chat approval. An Issue comment does not become an approval in this mode.
7. In explicitly configured `solo_owner` mode, require the same personal repository owner, authenticated User, and PR author. A PR author cannot submit a valid formal approval on their own PR. After an approved Issue-specific relay contract, the isolated ChatGPT relay broker may read back the exact repository, Issue, PR, HEAD, Readiness digest, ADC digest, and immutable review session ID, wait for a distinct direct `USER_REVIEW` confirmation, and append one canonical `PASES_USER_REVIEW_DECISION_V1` record to the Issue. The record binds those exact fields and the stable owner User ID; read it back directly/list/directly and pass it through the dedicated verifier and normal complete feedback/thread evaluation. It is GitHub owner-decision evidence, not a formal PR review, host-attested chat event, or `PASES_OWNER_DECISION_V1`. The deployment must prove that the broker credential/write route is unavailable to both the runtime and the Codex implementation agent. Neither the GitHub actor ID nor this Skill text proves separation; if the host boundary is unavailable or unverified, block. No generic continuation authorizes this write, and User Review does not satisfy independent review or merge authorization.

## CLI

~~~sh
python -m p_ases user-review start 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review sync 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review status 32 42 HEAD40 path/to/plan.json path/to/readiness.json --repo OWNER/REPO --root .
python -m p_ases user-review record 32 42 path/to/host-event.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

Edited/deleted feedback history, unresolved threads, stale HEAD, missing user decision, wrong-mode approval carrier, mismatched owner identity, noncanonical Issue permalink, or incomplete Acceptance blocks approval. The current CLI intentionally fails closed for untrusted direct-chat payloads. Output subject, synchronized feedback, decision, and blockers. User Review is not merge authorization.

Next owners: integration-validation handles parent feedback; delivery-control keeps merge permission separate. See the [User Review specification](../../../docs/specs/workflow-spec.md).
