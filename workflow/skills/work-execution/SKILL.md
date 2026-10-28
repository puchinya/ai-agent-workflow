---
name: work-execution
description: Execute only a verified approved ADC in the correct frozen work context.
---
# Work execution

## Sandboxed GitHub CLI

Run every `gh` command, including `gh auth login`, through the normal sandboxed execution environment. A script that invokes `gh` must itself start inside that sandbox so its child process inherits the sandbox boundary. Do not request sandbox escalation or run `gh` outside the sandbox to work around missing authentication, network access, or permissions. If the sandboxed command cannot complete, report its exact failure and stop that GitHub operation.

## One-time Issue #63 / PR #64 adoption

This exception applies only to `puchinya/ai-agent-workflow` Issue #63 / PR #64. It permits bootstrap implementation and CI while the original Binding is missing; before adoption, do not publish ordinary Phase receipts or claim Verification, Acceptance, Self-Audit, Independent Review, Readiness, or User Review PASS. After the bootstrap is pushed and all five exact-HEAD Required Checks pass, run `work adoption-plan 63` and preserve the complete canonical plan bytes. Show the full plan and digest to the user, then obtain a distinct same-conversation direct user-role `EXECUTION_ADOPTION` approval for that exact plan and PR HEAD. The chat host must provide the actual user event to the in-process V3 authorization hook; the CLI, a file, prior broad permission, old HEAD approval, or vague continuation cannot authorize it. If role provenance is unavailable, stop with `CHAT_PROVENANCE_UNAVAILABLE`. Only then run `work adoption-apply 63` and verify its Intent/Applied readback, epoch, workspace attachment, and adopted PRBinding. The record explicitly marks historical provenance `UNVERIFIED` and does not create a normal V1 Binding. Resume ordinary requirements→specification→design→ready→execution phases and all normal current-HEAD gates after adoption. This approval does not authorize User Review, Ruleset, Activation, or merge. Durable anchor/reattachment for ordinary Issues remains separate follow-up work.

### Approved ADC successor on the existing adopted epoch

Do not repeat adoption. Keep the adopted epoch, original ADC fields, Owner decision, two-row adoption journal, workspace attachment, and prior PRBinding rows unchanged. A new approved #63 ADC must be a complete forward successor of the epoch ADC and have its own V2 Phase Intent/Applied pair before `work adoption-refresh 63 --repo puchinya/ai-agent-workflow --root .`. Until then ordinary work reads remain blocked as `ADC_REFRESH_PENDING_PHASE_REBASELINE` or `ADC_REFRESH_REQUIRED`. The dedicated refresh appends one same-adoption-ID PRBinding V3 for the current ADC/exact HEAD and a V2 checkpoint with the original epoch digest; repeated complete refresh is read-only. If only the checkpoint append was interrupted, retry verifies the existing PRBinding and creates only that checkpoint. `work recover` never refreshes, and `pr ensure` may advance HEAD only within the current ADC generation.

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

Closed Issue, changed ADC pointer, dirty worktree, wrong base SHA, foreign remote, unverified workspace, conflicting binding, or mismatched PR identity blocks execution. Independent Review requires a dedicated fresh child that was actually spawned and joined and returned a valid exact-subject result; absent result, failed/unknown spawn or join, a known same-context identity, stale evidence, or an available mismatching binding blocks as `INDEPENDENT_SUBAGENT_UNAVAILABLE` or the exact evidence error. Missing host-reported spawn/session, reviewer, or implementation-binding IDs alone do not block: record them as null/missing with `LIMITED` confidence and ingest the child-authored artifact unchanged. No same-agent, human, or User Review fallback is allowed. Report the exact status and preserve state after errors. Do not claim a PR is ready without current-head verification and required checks.

Next owner: work-checkpoint records and resumes the same frozen context; verification-evidence binds results to the final HEAD. See the [workflow specification](../../../docs/specs/workflow-spec.md).
