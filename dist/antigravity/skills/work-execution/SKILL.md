---
name: work-execution
description: Execute only a verified approved ADC in the correct frozen work context.
---
# Work execution

## Owner and inputs

Owner: runtime/p_ases/execution.py, work.py, git.py, and github.py. Inputs are an open same-repository Issue, current approved ADC, exact base ref and SHA, project profile, and host-selected workspace.

## Workflow

1. Run request-intake and verify the exact approved ADC.
2. Read current context before any branch or workspace action.
3. For a new binding, resolve the base once, confirm it is the required same-repository ref, and bind the dedicated Issue branch and exact SHA before committing phase artifacts.
4. Complete the required specification/design/test-Oracle decisions and their predecessor-checked phase receipts before entering `ready` or editing implementation code.
5. Reuse an existing valid binding without resolving a newer base. After a newly approved ADC generation, append a binding record while retaining the frozen base, branch, and worktree. Never rebase or replace a conflicting binding.
6. Implement only approved scope. Keep GitHub requests in github.py and Git subprocesses in git.py.
7. Run the authorized local checks, then prepare an exact-HEAD PR with one standalone closure line. Do not merge or release.

## CLI

~~~sh
python -m p_ases context show 32 --root . --repo OWNER/REPO
python -m p_ases work base 32 --base-ref main --repo OWNER/REPO --root .
python -m p_ases work branch 32 --base-ref main --base-sha SHA40 --branch-ref pases/distribution-migration --repo OWNER/REPO --root .
python -m p_ases work bind 32 --base-ref main --base-sha SHA40 --branch-ref pases/distribution-migration --repo OWNER/REPO --root .
python -m p_ases pr ensure 32 --branch-ref pases/distribution-migration --base-ref main --title 'P-ASES change' --body-file path/to/pr-body.md --repo OWNER/REPO --root .
~~~

## Failure handling and output

Closed Issue, changed ADC pointer, dirty worktree, wrong base SHA, foreign remote, unverified workspace, conflicting binding, or mismatched PR identity blocks execution. Report the exact status and preserve state after errors. Do not claim a PR is ready without current-head verification and required checks.

Next owner: work-checkpoint records and resumes the same frozen context; verification-evidence binds results to the final HEAD. See the [workflow specification](../../docs/specs/workflow-spec.md).
