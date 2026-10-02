---
name: self-review
description: Evaluate every effective Reviewer Checklist item against concrete evidence at the exact current PR HEAD.
---
# Self-review

## Trigger and inputs
Use after implementation and before handing off a PR. Inputs are approved contract, Issue checklist, current diff, tests, and exact PR HEAD.

## Procedure
1. Resolve checklist precedence and hash with `prepare-self-review`.
2. Inspect every item independently; cite a path, line/symbol, command result, or API state.
3. Classify findings A contract violation, B ambiguity, C new requirement, or D optional improvement.
4. Validate the draft; submitted claims remain evidence to check, not approval.
5. Recreate review after any new commit because HEAD binding becomes stale.

## Output and uncertainty
Report each item and evidence, plus untested targets. Never mark unsupported evidence as passed. See [review specification](../../docs/specs/runtime-spec.md).
