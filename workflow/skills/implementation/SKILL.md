---
name: implementation
description: Implement an approved Issue contract in a scoped feature branch with profile-aware context and verification.
---
# Implementation

## Trigger and inputs
Use only after Issue, contract, Reviewer Checklist, and required design are approved. Read current Issue phase, branch/HEAD, affected components, project profile, `document_impact`, explicit doc owners, and diff.

## Procedure
1. Run `python -m agent_workflow agent-context <issue>` and inspect only routed documents and relevant code/tests.
2. Before changing files, run `python -m agent_workflow start-feature-branch <issue> <description...> [--base-ref <branch>] [--expected-base-sha <sha>]` and confirm the returned target branch. The runtime requires a clean worktree and an open same-repository Issue.
3. Confirm branch and scope; change specifications first if a material requirement changes.
4. Implement the smallest complete behavior, then add focused tests with fake GitHub boundaries.
5. Re-evaluate all three Document impact decisions against the final diff; update the Issue rows if the spec, design, or status choice changed. Validate declared owners with `python -m agent_workflow validate-docs --issue <issue>`.
6. Run configured hooks in declared order and record skipped targets as unverified.
7. Save checkpoints/evidence and request triage for category-C discoveries.

## Output and uncertainty
Report changed paths, evidence, unverified checks, and next step. Stop on contract conflict; never broaden unknown scope or infer application type. See the [application profile index](../../standards/application-profiles/README.md).
