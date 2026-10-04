---
name: self-review
description: Evaluate every effective Reviewer Checklist item against concrete evidence at the exact current PR HEAD.
---
# Self-review

## Trigger and inputs
Use after implementation and before handing off a PR. Inputs are approved contract, Issue checklist, current diff, tests, and exact PR HEAD.

## Procedure
1. Resolve checklist precedence and hash with `python -m agent_workflow prepare-self-review <issue> <pr>`.
2. Inspect every item independently; cite a path, line/symbol, command result, or API state.
3. Compare the final diff and changed documents with every Specification, Design, and Status decision in `## Document impact`; verify that linked owners exist and any `unchanged`/`evidence-only` reason matches the evidence.
4. Classify findings A contract violation, B ambiguity, C new requirement, or D optional improvement.
5. Run `python -m agent_workflow validate-self-review <issue> <pr>`, then `python -m agent_workflow publish-self-review <issue> <pr>`; submitted claims remain evidence to check, not approval.
6. Recreate review after any new commit because HEAD binding becomes stale.

## Output and uncertainty
Report each item and evidence, plus untested targets. Never mark unsupported evidence as passed. See [review specification](../../docs/specs/runtime-spec.md).
