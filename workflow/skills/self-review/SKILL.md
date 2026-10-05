---
name: self-review
description: Review the full approved Implementation Contract and every effective Reviewer Checklist item against evidence at the exact current PR HEAD.
---
# Self-review

## Trigger and inputs
Use after implementation and before handing off a PR. Inputs are approved contract, Issue checklist, current diff, tests, and exact PR HEAD.

## Procedure
1. Run `python -m agent_workflow verify-implementation-contract <issue>`.
2. Run `python -m agent_workflow restore-implementation-contract <issue>`.
3. Read the restored approved contract in full before assigning any contract-section result. Historical approved contracts remain readable even if their Reviewer Checklist H2 does not meet today's publication whitelist; review the generated legacy/non-canonical H2 as a contract unit as well as preserving its existing checklist extraction. If the verified pointer superseded a stale local mirror, inspect the mismatch and use `--replace-stale` only deliberately; never bypass contract verification.
4. Run `python -m agent_workflow prepare-self-review <issue> <pr>`.
5. Check every generated contract review unit against the exact final diff, source, tests, repository state, and required evidence.
6. For each section, name the important obligations checked, cite concrete source paths/symbols, diff facts, command results, API state, or other reproducible evidence, and explain why the final implementation conforms. Generic evidence such as “tests passed”, “diff reviewed”, “looks correct”, or “checklist passed” is insufficient by itself for a multi-obligation section. A source/diff-reviewable section must not be marked `untested` to avoid checking it.
7. Separately review every effective Reviewer Checklist item.
8. Re-evaluate `Document impact` against the final diff; verify linked owners and the reasons for `unchanged` or `evidence-only` decisions.
9. Classify findings A contract violation, B ambiguity, C new requirement, or D optional improvement. Run `python -m agent_workflow validate-self-review <issue> <pr>`, then `python -m agent_workflow publish-self-review <issue> <pr>`.
10. Recreate the entire review after any new PR commit, approved contract supersession, or effective checklist change.

> The Reviewer Checklist is a summary review surface, not a substitute for full Implementation Contract conformance review.

> Contract-section `untested` is valid evidence of a blocker but cannot satisfy delivery.

Do not report the final delivery result as passed before this review is published. Run `python -m agent_workflow delivery-check <issue> <pr>` as the post-review completion gate after publication and current Required Checks.

## Output and uncertainty
Report each contract section and checklist item with its evidence, plus untested targets. Contract-section `untested` blocks completion; checklist `untested` remains non-blocking by itself. Never mark unsupported evidence as passed. Self-review is evidence, never approval. See [review specification](../../../docs/specs/runtime-spec.md).
