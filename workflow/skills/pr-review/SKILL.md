---
name: pr-review
description: Independently review a pull request against its approved contract, effective checklist, and exact current HEAD.
---
# PR review

## Trigger and inputs
Use when asked to review an open PR. Independently read the complete approved contract, owning Issue, effective checklist, PR diff and HEAD, review evidence, and current checks.

## Procedure
1. Verify PR/Issue repository and scope association.
2. Fetch only named contract/review comments; reject stale HEAD or invalid hashes.
3. Independently reread and check every approved contract section and every effective checklist item against source and reproducible evidence, even when the published v2 self-review is clean. Historical non-canonical Reviewer Checklist H2 content remains in full-contract review coverage; do not require old approved bytes to pass the new publication-time authoring whitelist.
4. Report findings by A/B/C/D with paths/lines and concrete impact.
5. State unverified checks and whether required checks are current.

## Output and uncertainty
Return actionable findings first, then residual risk and untested environments. A clean schema-v2 self-review is evidence only, not approval or a substitute for this independent full-contract review. Stop if ownership or current state is ambiguous.
