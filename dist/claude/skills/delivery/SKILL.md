---
name: delivery
description: Enforce current-HEAD review, Required Checks, PR handoff, and merged Issue finalization gates.
---
# Delivery

## Trigger and inputs
Use before declaring handoff complete or finalizing a merged Issue. Inputs are Issue, PR, project profile, published review pointer, Verification, Untested, and configured Required Checks.

## Procedure
1. Run `python -m agent_workflow delivery-check <issue> <pr>` to read fresh authoritative state.
2. Require an open, non-draft PR with `Closes #N`, review phase, valid current-HEAD schema-v2 review, every contract section `pass`, no checklist item `fail`, and completed Verification/Untested. Contract-section `fail` or `untested` blocks handoff; checklist `untested` remains non-blocking by itself.
3. Require every configured Required Check green on the current HEAD; no configured checks is failure.
4. For merged delivery, verify PR merged and Issue closed, then run `python -m agent_workflow finalize-merged-issue <issue> <pr>`.
5. Confirm only stale `phase:review` was removed and repeat finalization safely if needed.

## Output and uncertainty
Report exact gate results and blockers. Never report complete on a test-only result or uncertain GitHub state.
