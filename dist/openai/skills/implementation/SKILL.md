---
name: implementation
description: Implement an approved Issue contract in a scoped feature branch with profile-aware context and verification.
---
# Implementation

## Trigger and inputs
Use only after Issue, contract, Reviewer Checklist, and required design are approved. Read current Issue phase, branch/HEAD, affected components, project profile, explicit doc owners, and diff.

## Procedure
1. Run `agent-context <issue>` and inspect only routed documents and relevant code/tests.
2. Confirm branch and scope; change specifications first if a material requirement changes.
3. Implement the smallest complete behavior, then add focused tests with fake GitHub boundaries.
4. Run configured hooks in declared order and record skipped targets as unverified.
5. Save checkpoints/evidence and request triage for category-C discoveries.

## Output and uncertainty
Report changed paths, evidence, unverified checks, and next step. Stop on contract conflict; never broaden unknown scope or infer application type. See the [application profile index](../../standards/application-profiles/README.md).
