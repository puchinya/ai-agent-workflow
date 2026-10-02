---
name: checkpoint
description: Save and resume Issue-scoped progress without losing branch, HEAD, decisions, or verification state.
---
# Checkpoint

## Trigger and inputs
Use before interruption, context handoff, or a long verification wait. Read Issue, branch, HEAD, diff, active decision, and evidence.

## Procedure
1. Record completed and in-progress work with paths and current commit.
2. Record contract/spec/design owners and unresolved questions.
3. Record commands/results and untested targets separately.
4. State the next safe action and any operation that must not be repeated.
5. On resume, re-read Issue, branch, HEAD, and working tree before acting.

## Output and uncertainty
Write a concise Issue-scoped status/checkpoint using `workflow/templates/status-template.md`. Treat stale HEAD or changed Issue state as requiring fresh routing.
