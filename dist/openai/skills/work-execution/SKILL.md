---
name: work-execution
description: Execute only a verified approved ADC in the correct frozen work context.
---
# Work execution

## Owner and inputs

Owner: runtime/p_ases/execution.py, work.py, git.py, and github.py. Inputs are an open same-repository Issue, current approved ADC, exact base ref and SHA, project profile, and host-selected workspace.

## Workflow

1. Run request-intake and verify the exact approved ADC. New approved generations must have passed the approval-ready publication preflight; historical generations remain byte-identical and are not retroactively normalized.
2. Read current context before any branch or workspace action.
3. For a new binding, resolve the base once, confirm it is the required same-repository ref, and bind the dedicated Issue branch and exact SHA before committing phase artifacts.
4. Complete the required specification/design/test-Oracle decisions and their predecessor-checked phase receipts before entering `ready` or editing implementation code.
5. Reuse an existing valid binding without resolving a newer base. After a newly approved ADC generation, append a binding record while retaining the frozen base, branch, and worktree. Never rebase or replace a conflicting binding.
6. Implement only approved scope. Keep GitHub requests in github.py and Git subprocesses in git.py.
7. Run the authorized local checks, then prepare an exact-HEAD PR with one standalone closure line. Do not merge or release.
8. Complete the Contract Conformance Review and Reviewer Checklist Review for the final diff and exact HEAD. Then hand off automatically to `independent-review`; the host must spawn one dedicated fresh native subagent without asking for another user confirmation.
9. After the child returns, inspect its unedited result. If it has blocking findings, fix them and push a new HEAD, then start a new child review. Never retry without progress on the same HEAD. If it passes, read current Phase, Binding, Verification, Acceptance, Self-Audit, and Required CI while the Issue remains in `execution`. When all are current and PASS, run `issue advance ISSUE verification` and read it back; then run `delivery readiness`; on PASS, start `user-review start` automatically. This starts the User Review session only; wait for the user's explicit decision.

## Lifecycle handoff

For ordinary single/child Issues, the host follows one sequence: approved ADC and optional Phase rebaseline; exact frozen Binding; specification/design/Test Oracle artifacts and receipts; `ready`; `execution`; implementation; current Verification, Acceptance, Self-Audit, and a fresh native Independent Review; `verification`; Review Readiness; then `user-review start`. Blocking review findings are fixed while phase is `execution`, and every changed HEAD gets a fresh child review. Only after the complete current PASS set may the host advance to `verification`; a required code change after that phase blocks as `BLOCKED_PHASE_REWORK_DECISION_REQUIRED`. CLI commands remain one-shot mutations/readbacks; Skills and adapters own orchestration.

Readiness cannot newly PASS outside `verification`; in `user-review`, it may only reproduce the exact subject and Readiness SHA already held by the immutable session. User Review checks phase before writing a session or feedback snapshot. In `verification`, `start` may create one session; in `user-review`, only a matching existing session may resume. If interruption leaves the exact session in `verification`, `sync` preserves its `started_at`, completes snapshot readback, and performs the normal Phase update/readback. Missing or mismatched sessions block without overwrite. `PENDING` (exit code 2) is ordinary waiting; report `WAITING_USER_REVIEW_DECISION` only after reading back the session, complete feedback snapshot, and `phase:user-review`. This does not record approval.

## CLI

~~~sh
python -m p_ases context show 32 --root . --repo OWNER/REPO
python -m p_ases work base 32 --base-ref main --repo OWNER/REPO --root .
python -m p_ases work branch 32 --base-ref main --base-sha SHA40 --branch-ref pases/distribution-migration --repo OWNER/REPO --root .
python -m p_ases work bind 32 --base-ref main --base-sha SHA40 --branch-ref pases/distribution-migration --repo OWNER/REPO --root .
python -m p_ases pr ensure 32 --branch-ref pases/distribution-migration --base-ref main --title 'P-ASES change' --body-file path/to/pr-body.md --repo OWNER/REPO --root .
~~~

## Failure handling and output

Closed Issue, changed ADC pointer, dirty worktree, wrong base SHA, foreign remote, unverified workspace, conflicting binding, or mismatched PR identity blocks execution. An unavailable fresh host-native subagent, unknown spawn/join result, or missing host-reported spawn/session, reviewer, or implementation-binding identity blocks Independent Review as `INDEPENDENT_SUBAGENT_UNAVAILABLE`; the parent compares child `context_id` and canonical `provenance` with host metadata and ingests the child-authored artifact unchanged. No same-agent, human, or User Review fallback is allowed. If the active host cannot provide the actual provenance, report it unverified. Report the exact status and preserve state after errors. Do not claim a PR is ready without current-head verification and required checks.

Next owner: work-checkpoint records and resumes the same frozen context; verification-evidence binds results to the final HEAD. See the [workflow specification](../../docs/specs/workflow-spec.md).
