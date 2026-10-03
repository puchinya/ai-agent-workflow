---
name: pr-review
description: Independently review a pull request against its approved contract, effective checklist, and exact current HEAD.
---
# PR review

## Trigger and inputs
Use when asked to review an open PR. Read owning Issue, approved contract, effective checklist, PR diff and HEAD, review evidence, and current checks.

## Procedure
1. Verify PR/Issue repository and scope association.
2. Fetch only named contract/review comments; reject stale HEAD or invalid hashes.
3. Check each effective item against source and reproducible evidence.
4. Report findings by A/B/C/D with paths/lines and concrete impact.
5. State unverified checks and whether required checks are current.

## Output and uncertainty
Return actionable findings first, then residual risk and untested environments. A clean self-review is not independent approval. Stop if ownership or current state is ambiguous.
