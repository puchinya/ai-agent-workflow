---
name: work-checkpoint
description: Save and resume the existing immutable work binding and checkpoint history.
---
# Work checkpoint

## Owner and inputs

Owner: runtime/p_ases/checkpoint.py and work.py. Inputs are the current Issue, exact approved ADC, existing ExecutionBinding, PRBinding history, and checkpoint digests.

## Workflow

1. Before resuming, read context and verify the exact ADC pointer.
2. Inspect the existing binding and checkpoint history without rewriting them.
3. Recover only the same Issue, repository, ADC, base ref/SHA, branch, and workspace identity. A formally approved ADC successor may be added only through the normal bind route, which appends an ExecutionBinding generation while preserving the frozen base, branch, and workspace.
4. Use ordinary work routes to append checkpoints and PRBinding generations after successful state transitions. A PRBinding for a later approved ADC is append-only: its PR, base, branch, and repository lineage must match, and its ADC generation must not move backward in ExecutionBinding history. Preserve every prior PRBinding byte.
5. Never resolve a newer base for a bound execution. A changed or missing checkpoint is not silently reconstructed from current Git state. A stale ExecutionBinding input or mismatched PRBinding history blocks before PR search or mutation.

## CLI

~~~sh
python -m p_ases context show 32 --root . --repo OWNER/REPO
python -m p_ases work recover 32 --branch-ref pases/distribution-migration --repo OWNER/REPO --root .
~~~

Checkpoint persistence is owned by work operations. There is no separate public checkpoint namespace.

## Failure handling and output

Missing, corrupt, symlinked, non-contiguous, or mismatched binding/checkpoint records fail closed. A stale ADC or changed worktree must be reported rather than rebound. Output the immutable binding digest, last valid checkpoint, and exact recovery result without exposing unrelated environment data.

Next owner: work-execution continues only after a matching recovery. See the [work design](../../../docs/design/runtime-design.md).
