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
8. Run the Issue-routed `verify_quick` hook, then commit only the approved Issue-scoped changes; continue without another conversational prompt by running `python -m agent_workflow ensure-review-pr <issue> --body-file <path>`, which safely pushes the current branch and creates or reuses its non-draft PR. Pass the exact `base_ref` from `start-feature-branch` with `--base-ref` for stacked work.
9. At the resulting exact PR HEAD, run `python -m agent_workflow verify-final <issue> <pr>`, prepare/validate/publish the exact-HEAD self-review, and follow the [QA Skill](../qa/SKILL.md). Then hand the PR to a new session/subagent or human using the [PR review Skill](../pr-review/SKILL.md). The implementation session must not author that independent-review artifact. If no independent reviewer is available, keep the delivery gate blocked and report the PR URL and blocker. Run `python -m agent_workflow delivery-check <issue> <pr>` only after all four evidence records exist; read Required Checks from its result.
10. After any new PR commit or approved contract/checklist change, regenerate every affected HEAD- or contract-bound evidence record and rerun the delivery gate.
11. Do not report implementation complete until an open, non-draft review PR exists and Final Verification, self-review, QA, fresh-context Independent Review, and Required Checks pass. If the fresh reviewer or a Required Check is pending after PR creation, report the exact blocker with the PR URL; keep the PR and continue the authorized, non-destructive review/delivery sequence where possible.

## Output and uncertainty
Report changed paths, commit/push/PR state, exact-HEAD Verification/QA/self-review evidence, independent-review status, Required Check state, unverified checks, and delivery result. Approval of the contract execution authorizes the routine handoff operations above; do not ask for a separate PR-creation approval. Stop on contract conflict that requires a new decision; never broaden unknown scope or infer application type. See the [application profile index](../../standards/application-profiles/README.md).
