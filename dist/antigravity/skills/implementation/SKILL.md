---
name: implementation
description: Implement an approved Issue contract in a scoped feature branch with profile-aware context and verification.
---
# Implementation

## Trigger and inputs
Use only after Issue, contract, Reviewer Checklist, and required design are approved. Read current Issue phase, branch/HEAD, affected components, project profile, `document_impact`, explicit doc owners, and diff.

## Procedure
1. Run `python -m agent_workflow agent-context <issue>` and inspect only routed documents and relevant code/tests.
2. Before changing files, run `python -m agent_workflow start-feature-branch <issue> <description...> [--base-ref <branch>] [--expected-base-sha <sha>]` and inspect the returned target branch. The runtime requires a clean worktree and an open same-repository Issue.
3. Confirm branch and scope; change specifications first if a material requirement changes.
4. Implement the smallest complete behavior, then add focused tests with fake GitHub boundaries.
5. Re-evaluate all three Document impact decisions against the final diff; update the Issue rows if the spec, design, or status choice changed. Validate declared owners with `python -m agent_workflow validate-docs --issue <issue>`.
6. Run configured hooks in declared order and record skipped targets as unverified.
7. Preserve any approved Issue-scoped target release exactly through the handoff; do not derive or substitute a version. Include the target selection and contracted milestone command/result in delivery evidence when milestone assignment is part of the contract. Save checkpoints/evidence and request triage for category-C discoveries.
8. After final local verification, continue without another conversational prompt: commit the approved Issue-scoped changes, then run `python -m agent_workflow ensure-review-pr <issue> --body-file <path>`, which safely pushes the current branch and creates or reuses the review PR. Pass the exact `base_ref` from `start-feature-branch` with `--base-ref` for stacked work. Prepare, validate, and publish the exact-HEAD self-review, then run `python -m agent_workflow delivery-check <issue> <pr>` and read Required Checks.
9. Do not report implementation complete until an open, non-draft review PR exists. If Required Checks are pending after PR creation, report `BLOCKED_DELIVERY_CHECKS_PENDING`; keep the PR and continue the authorized review/delivery sequence. Report another blocker only after making the authorized, non-destructive progress available.

## Output and uncertainty
Report changed paths, commit/push/PR state, exact-HEAD review evidence, Required Check state, unverified checks, and delivery result. Approval of the contract execution authorizes the routine handoff operations above; do not ask for a separate PR-creation approval. Stop on contract conflict that requires a new decision; never broaden unknown scope or infer application type. See the [application profile index](../../standards/application-profiles/README.md).
