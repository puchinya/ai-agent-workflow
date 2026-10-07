---
name: delivery
description: Enforce Final Verification, self-review, QA, Independent Review, Required Checks, and merged Issue gates.
---
# Delivery

## Trigger and inputs
Use after implementation to establish or verify the review PR, before declaring handoff complete, or when finalizing a merged Issue. Inputs are Issue, PR, exact HEAD, Final Verification, self-review, QA, Independent Review, Verification, Untested, and configured Required Checks.

## Procedure
1. If implementation has no PR, prepare a truthful body file containing an own-line `Closes #N`, non-empty `## Verification`, and non-empty `## Untested`; then run `python -m agent_workflow ensure-review-pr <issue> --body-file <path>`. Pass the exact `base_ref` from `start-feature-branch` with `--base-ref` for stacked work. Do not improvise GitHub commands or request a separate PR-specific approval after contract execution was authorized.
2. At the exact current PR HEAD, publish Final Verification using `python -m agent_workflow verify-final <issue> <pr>`. A dirty worktree, different local HEAD, failed hook, skipped target, or empty plan cannot produce a passing receipt.
3. Follow the [self-review Skill](../self-review/SKILL.md), then the [QA Skill](../qa/SKILL.md). A new commit or contract change makes affected evidence stale.
4. Obtain the [Independent Review Skill](../pr-review/SKILL.md) result from a new session/subagent or human. The implementation session must not author its artifact; `fresh_context: true` is an attestation, not runtime proof. If no separate reviewer is available, leave handoff blocked and report the PR URL and blocker.
5. Run `python -m agent_workflow delivery-check <issue> <pr>` to read fresh authoritative state. It requires current Final Verification `pass`, self-review v2, QA all-PASS or N/A, Independent Review with every contract unit PASS/no checklist FAIL/no blocking finding, then every configured Required Check green on the same HEAD. No configured checks is failure.
6. If evidence or checks are stale/pending, keep the PR and report the exact gate. For pending Required Checks, report `BLOCKED_DELIVERY_CHECKS_PENDING`; implementation is not complete.
7. For merged delivery, verify PR merged and Issue closed, then run `python -m agent_workflow finalize-merged-issue <issue> <pr>`.
8. Confirm only stale `phase:review` was removed and repeat finalization safely if needed.

## Output and uncertainty
Report each of the four evidence-gate results, independent-review provenance limitation, Required Checks, and exact blockers. Never report complete on a test-only result or uncertain GitHub state.
