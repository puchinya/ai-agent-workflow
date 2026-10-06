---
name: delivery
description: Enforce current-HEAD review, Required Checks, PR handoff, and merged Issue finalization gates.
---
# Delivery

## Trigger and inputs
Use after implementation to establish or verify the review PR, before declaring handoff complete, or when finalizing a merged Issue. Inputs are Issue, optional existing PR, project profile, Verification, Untested, and configured Required Checks.

## Procedure
1. If implementation has no PR, prepare a truthful body file containing an own-line `Closes #N`, non-empty `## Verification`, and non-empty `## Untested`; then run `python -m agent_workflow ensure-review-pr <issue> --body-file <path>`. Pass the exact `base_ref` from `start-feature-branch` with `--base-ref` for stacked work. Do not improvise GitHub commands or request a separate PR-specific approval after contract execution was authorized.
2. After create/reuse, immediately follow the [self-review Skill](../self-review/SKILL.md) at the exact PR HEAD: prepare, review, validate, and publish. A new PR commit makes any prior self-review stale.
3. Run `python -m agent_workflow delivery-check <issue> <pr>` to read fresh authoritative state.
4. Require an open, non-draft PR with `Closes #N`, review phase, valid current-HEAD schema-v2 review, every contract section `pass`, no checklist item `fail`, and completed Verification/Untested. Contract-section `fail` or `untested` blocks handoff; checklist `untested` remains non-blocking by itself.
5. Require every configured Required Check green on the current HEAD; no configured checks is failure. If checks are pending after PR creation, report `BLOCKED_DELIVERY_CHECKS_PENDING`; implementation is not complete.
6. For merged delivery, verify PR merged and Issue closed, then run `python -m agent_workflow finalize-merged-issue <issue> <pr>`.
7. Confirm only stale `phase:review` was removed and repeat finalization safely if needed.

## Output and uncertainty
Report exact gate results and blockers. Never report complete on a test-only result or uncertain GitHub state.
