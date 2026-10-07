---
name: pr-review
description: Independently review a pull request against its approved contract, effective checklist, and exact current HEAD.
---
# PR review

## Trigger and inputs
Use only from a fresh review context, a different subagent, or a human reviewer to review an open PR. The implementation session MUST NOT author or publish the independent-review artifact. Inputs are the complete approved contract, owning Issue, effective checklist, PR diff and HEAD, review evidence, and current checks.

## Procedure
1. Verify PR/Issue repository and scope association. Fetch only named contract/review comments; reject stale HEAD or invalid hashes.
2. Run `python -m agent_workflow prepare-pr-review <issue> <pr>` to create or refresh `.agent-state/issues/<issue>/pr-review-pr-<pr>.json`.
3. Independently reread and check every approved contract unit and every effective checklist item against source, diff, and reproducible evidence, even when the published v2 self-review is clean. Historical non-canonical Reviewer Checklist H2 content remains in full-contract review coverage; do not require old approved bytes to pass the new publication-time authoring whitelist.
4. Fill every contract unit and checklist item with `pass`, `fail`, or `untested` plus concrete evidence. Set `fresh_context: true` only as an explicit reviewer attestation that this artifact was authored in a separate session/subagent or by a human. Runtime validates the attestation and artifact but cannot prove its provenance.
5. Record findings with unique IDs, severity A/B/C/D, title, concrete evidence, and boolean `blocking`. A/B findings MUST block; D findings MUST NOT block; every C finding MUST state whether it blocks. Include paths/lines and practical impact.
6. Run `python -m agent_workflow validate-pr-review <issue> <pr>`, then `python -m agent_workflow publish-pr-review <issue> <pr>` and `python -m agent_workflow validate-public-pr-review <issue> <pr>`.
7. State unverified checks and whether Required Checks are current.

## Output and uncertainty
Return actionable findings first, then residual risk and untested environments. A clean schema-v2 self-review is evidence only, not approval or a substitute for this independent full-contract review. Every contract unit must pass, checklist failures block, and blocking findings prevent handoff. Stop if ownership or current state is ambiguous; if a fresh context is unavailable, leave this gate pending and report the exact blocker with the PR URL. Do not use host-specific session-spawning APIs.
