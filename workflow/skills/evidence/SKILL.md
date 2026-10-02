---
name: evidence
description: Record reproducible verification results and clearly identify checks that were not run.
---
# Evidence

## Trigger and inputs
Use after a change, before review, and when resuming work. Inputs are commands, environment/target, exit status, concise output, commit HEAD, and affected Issue.

## Procedure
1. Run only the verification required by the approved contract/profile.
2. Capture command, platform, version, exit status, and relevant bounded result.
3. Distinguish passed, failed, and untested; a skip is never a pass.
4. Link evidence to the Issue/status owner and current HEAD.

## Output and uncertainty
Provide reproducible evidence and explicit blockers. Do not claim a host IDE, OS, credentialed service, or check passed unless actually run. See [status template](../../templates/status-template.md).
