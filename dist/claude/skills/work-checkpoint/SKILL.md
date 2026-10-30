---
name: work-checkpoint
description: Save and resume the existing immutable work binding and checkpoint history.
---
# Work checkpoint

## One-time Issue #63 / PR #64 adoption

For the exact #63/#64 exception, a missing original Binding is not repaired by `work recover`, and no synthetic `initial_head == base_sha` row may be created. Bootstrap source/test changes are allowed before adoption, but no ordinary Phase/QA/Review/Readiness PASS is allowed. After bootstrap push and exact-final-HEAD CI PASS, produce and preserve the complete read-only `work adoption-plan 63`; require a distinct authenticated same-chat V3 `EXECUTION_ADOPTION` decision for its full plan SHA and PR HEAD before `work adoption-apply 63`. The append-only epoch and workspace attachment mark historical provenance `UNVERIFIED`. Verify `context show` reports `ADOPTED_EPOCH`, or use `work recover` only as a read-only verification of that same attached adopted workspace. A different workspace cannot claim the old attachment. The adopted epoch remains separate from V1; ordinary Issues keep their existing binding behavior.

For a later approved ADC on that same adopted epoch, preserve the original epoch digest in every checkpoint. After the current generation's V2 Applied receipt, `work adoption-refresh 63` appends a current ADC/HEAD PRBinding V3 and a V2 checkpoint. Refresh preflight validates the whole ADC chain, owner/adoption records, attachment, clean forward branch, PR identity and contiguous histories. A retry after only the PRBinding exists writes only the absent checkpoint; an exact complete retry writes nothing. `work recover` is always read-only and cannot perform this refresh.

## Owner and inputs

Owner: runtime/p_ases/checkpoint.py and work.py. Inputs are the current Issue, exact approved ADC, existing ExecutionBinding, PRBinding history, and checkpoint digests.

## Workflow

1. Before resuming, read context and verify the exact ADC pointer.
2. Inspect the existing binding and checkpoint history without rewriting them.
3. Recover only the same Issue, repository, ADC, base ref/SHA, branch, and workspace identity.
4. Use ordinary work routes to append checkpoints after successful state transitions.
5. Never resolve a newer base for a bound execution. A changed or missing checkpoint is not silently reconstructed from current Git state. If the original ExecutionBinding cannot be authenticated, stop as `BLOCKED_BINDING_PROVENANCE_MISSING`; do not infer the frozen tuple from the current branch or `main`.

## Lifecycle handoff

For ordinary single/child Issues, the host follows one sequence: approved ADC and optional Phase rebaseline; exact frozen Binding; specification/design/Test Oracle artifacts and receipts; `ready`; `execution`; implementation; current Verification, Acceptance, Self-Audit, and a fresh native Independent Review; `verification`; Review Readiness; then `user-review start`. Blocking review findings are fixed while phase is `execution`, and every changed HEAD gets a fresh child review. Only after the complete current PASS set may the host advance to `verification`; a required code change after that phase blocks as `BLOCKED_PHASE_REWORK_DECISION_REQUIRED`. CLI commands remain one-shot mutations/readbacks; Skills and adapters own orchestration.

Readiness cannot newly PASS outside `verification`; in `user-review`, it may only reproduce the exact subject and Readiness SHA already held by the immutable session. User Review checks phase before writing a session or feedback snapshot. In `verification`, `start` may create one session; in `user-review`, only a matching existing session may resume. If interruption leaves the exact session in `verification`, `sync` preserves its `started_at`, completes snapshot readback, and performs the normal Phase update/readback. Missing or mismatched sessions block without overwrite. `PENDING` (exit code 2) is ordinary waiting; report `WAITING_USER_REVIEW_DECISION` only after reading back the session, complete feedback snapshot, and `phase:user-review`. This does not record approval.

## CLI

~~~sh
python -m p_ases context show 32 --root . --repo OWNER/REPO
python -m p_ases work recover 32 --branch-ref pases/distribution-migration --repo OWNER/REPO --root .
~~~

Checkpoint persistence is owned by work operations. There is no separate public checkpoint namespace.

## Failure handling and output

Missing, corrupt, symlinked, non-contiguous, or mismatched binding/checkpoint records fail closed. A stale ADC or changed worktree must be reported rather than rebound. Output the immutable binding digest, last valid checkpoint, and exact recovery result without exposing unrelated environment data.

Next owner: work-execution continues only after a matching recovery. See the [work design](../../docs/design/runtime-design.md).
