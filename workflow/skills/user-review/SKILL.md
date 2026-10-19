---
name: user-review
description: Capture, synchronize, and evaluate human feedback for the exact current PR subject.
---
# User review

## Owner and inputs

Owner: runtime/p_ases/user_review.py, with runtime/p_ases/user_review_relay.py verifying the dedicated self-authored `solo_owner` carrier. Inputs are an open PR, current HEAD, approved ADC, final Verification, completed Acceptance, readiness record, selected repository review mode, and GitHub feedback surfaces or a trusted host-attested direct-chat event. The CLI supplies review mode and owner identity only after reading the repository profile and verifying GitHub identities.

## Workflow

1. Before writing a session, snapshot, or result, read the exact Issue kind, phase, and attention labels. Require one valid kind and phase and no attention state; unknown or multiple attention labels fail closed. Do not clear attention here. In `phase:verification`, `start` may create the one immutable session; in `phase:user-review`, resume only an existing session with the exact same subject and Readiness SHA. Other phases and missing/mismatched sessions block without overwrite.
2. Synchronize conversation comments, formal reviews, inline comments, and review threads with pagination and edit/deletion readback. If interruption left the exact session in `verification`, `sync` preserves `started_at`, persists/readbacks the complete feedback snapshot, and completes the normal Issue phase update/readback. Re-read kind/phase/attention immediately before the label update. If its response is lost, confirm the full intended label set by readback and do not repeat a confirmed update.
3. Treat changed HEAD as stale and restart only from current state. Readiness cannot be newly PASS outside `verification`; in `user-review`, only recompute the same subject/Readiness SHA already bound to the immutable session.
4. Record direct-chat decisions only through a trusted host verifier. Raw caller JSON is not identity authority.
5. Route newly requested scope to requirements; do not silently absorb it into the current contract.
6. In the default `external_reviewer` mode, accept the existing authenticated PR review or verified host-chat approval. An Issue comment does not become an approval in this mode.
7. In explicitly configured `solo_owner` mode, pin the personal repository owner and current PR author; a PR author cannot submit a formal approval on their own PR. Preserve V1 delegated and V2 `owner_local_tty_v1` evidence exactly. The standard V3 `PASES_USER_REVIEW_DECISION_V3` uses `chat_confirmed_gh_v1` after the current user directly approves the displayed exact repository, Issue, PR, HEAD, Readiness, ADC, immutable session, prior feedback, plan and scope in this same conversation. It binds feedback and approval-scope digests and is direct/list/direct verified before typed evidence enters the normal full feedback/thread evaluator. V3 is operator-reported chat approval plus GitHub actor evidence, not a chat-host signature or independent relay. If the host cannot provide actual user-role provenance, return `CHAT_PROVENANCE_UNAVAILABLE` without a write. No owner-local approval TTY, CLI flag, JSON consent, or GitHub UI comment is accepted. User Review does not satisfy independent review or PR merge authorization.

Consumer Activation owns provisioning before this later review gate: its setup action prepares the exact policy plan, requests separate chat approval for `RULESET_PLAN_APPLY`, uses isolated browser device Admin authentication when required, verifies policy, and only then creates the Setup PR. Admin authentication, Ruleset approval, User Review, and PR merge decisions remain distinct. No owner-local TTY is required for chat approval.

## Lifecycle handoff

For ordinary single/child Issues, the host follows one sequence: approved ADC and optional Phase rebaseline; exact frozen Binding; specification/design/Test Oracle artifacts and receipts; `ready`; `execution`; implementation; current Verification, Acceptance, Self-Audit, and a fresh native Independent Review; `verification`; Review Readiness; then `user-review start`. Blocking review findings are fixed while phase is `execution`, and every changed HEAD gets a fresh child review. Only after the complete current PASS set may the host advance to `verification`; a required code change after that phase blocks as `BLOCKED_PHASE_REWORK_DECISION_REQUIRED`. CLI commands remain one-shot mutations/readbacks; Skills and adapters own orchestration.

Readiness cannot newly PASS outside `verification` or while any attention label is present; in `user-review`, it may only reproduce the exact subject and Readiness SHA already held by the immutable session. User Review checks kind/phase/attention before writing a session or feedback snapshot. In `verification`, `start` may create one session; in `user-review`, only a matching existing session may resume. If interruption leaves the exact session in `verification`, `sync` preserves its `started_at`, completes snapshot readback, and performs the normal Phase update/readback. Missing or mismatched sessions block without overwrite. `PENDING` (exit code 2) is ordinary waiting; report `WAITING_USER_REVIEW_DECISION` only after reading back the session, complete feedback snapshot, and `phase:user-review`. This does not record approval.

For `user-review start`, `sync`, and `status`, the current GitHub Issue's unique valid `kind:*` label supplies the Issue kind when `--kind` is omitted. Pass `--kind` only as an explicit assertion; the runtime rejects a mismatch. Missing, malformed, unknown, or duplicate `kind:*` labels block before session, snapshot, result, or Issue-label writes. Ordinary User Review remains limited to `single` and `child` Issues.

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
