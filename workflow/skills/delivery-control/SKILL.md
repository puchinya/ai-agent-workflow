---
name: delivery-control
description: Evaluate Review Readiness and Final Delivery without merging or publishing.
---
# Delivery control

## Owner and inputs

Owner: runtime/p_ases/delivery.py and gate_policy.py. Inputs are current PR identity, exact HEAD, final Verification and Acceptance, audit and review evidence, User Review, required Checks, branch protection, and explicit user permissions.

## Workflow

1. Read the gate policy for the Issue. Fixed Bootstrap Issues #27–#32 use the separate technical evaluator before activation.
2. After a PASS from the dedicated fresh host-native Independent Review child, re-read current Phase, Binding, Verification, Acceptance, Self-Audit, and Required CI. If every required item is current and PASS, evaluate ordinary Review Readiness from those exact-subject inputs. Do not substitute Bootstrap technical readiness for normal product gates.
3. When `delivery readiness` returns PASS, automatically run `user-review start` for the same repository, Issue, PR, approved ADC, HEAD, and Readiness digest without asking for extra confirmation to start. This records an active session only. Obtain and record the user's explicit final decision separately; never fabricate it. ChatGPT may be the Owner-selected User Review method for code review, so do not demand a duplicate code review, but the chat review alone is not the formal User Review approval record.
4. For final delivery, re-read User Review, GitHub formal review, Required Checks, branch protection, and mergeability.
5. Verify ordinary auto-close or complete an authorized deferred Issue close with the finalize command.
6. Present PR number, exact HEAD, technical checks, risks, and intended order before any merge request. A successful check is not user merge permission.

Ordinary PR deliveries retain one standalone `Closes #N` line and GitHub's normal auto-close behavior. `Refs #N` is reserved for an explicitly deferred completion path whose Issue stays open after merge.

## Consumer Activation request

### Issue #63 delivery order

For Issue #63, complete the implementation on PR #64 first. Finalize the successor ADC bytes in the reviewed implementation and calculate its SHA-256. Provide the canonical `.md` file and render its complete contents as Markdown in this same chat before requesting approval; do not wrap the ADC in a fenced source-code block or HTML disclosure/container. A file link, excerpt, or SHA alone is insufficient. If the selection UI cannot contain the whole document, render the complete Markdown in the immediately preceding message in this conversation, link the canonical file, and make the approval prompt explicitly refer to that rendered document. Include the exact ADC SHA, current approved predecessor pointer, `ADC_SUPERSEDE` operation, plan SHA, approval-scope SHA, and resulting automatic Phase update in the prompt. If any ADC byte changes, recalculate the SHA, provide and render the complete new Markdown again, and request fresh approval. Prior approval for an older SHA does not transfer. The `owner-authorize-plan` CLI command is a read-only preview; `owner-authorize-commit` is disabled because a CLI cannot prove chat user-role provenance. When the current chat host exposes the actual user-role approval event, the in-process integration records a V3 scope and uses the existing ADC publisher/readback. If the host cannot supply that event, report `CHAT_PROVENANCE_UNAVAILABLE` and stop before a GitHub write.

After approved pointer readback, the regular P-ASES executor automatically advances #63 from `phase:ready` to `phase:requirements` with append-only Intent/Applied evidence and at most one label update. No `PHASE_REBASE` approval is requested. Establish that generation's Phase receipts before merge. If publication was interrupted, use the existing read-only/resume routes and never repeat a confirmed pointer or label write. Before #64 merges, verify the required solo-owner Ruleset policy; any write needs its own exact Ruleset plan approval and isolated Admin apply. Then complete the current #64 CI, Independent Review, User Review, Final Delivery, and separate exact-HEAD `PR_MERGE` gates. Keep the PR body on exactly one standalone `Refs #63` line. The shared close detector recognizes GitHub's case-insensitive `close`/`closes`/`closed`, `fix`/`fixes`/`fixed`, and `resolve`/`resolves`/`resolved` forms, optional colons, and both `#N` and `OWNER/REPO#N`; repository-qualified references are compared case-insensitively. Before merge, re-read the body, all commits, planned merge request, GitHub `closingIssuesReferences`, and Issue cross-reference metadata; any closer token, auto-close link or uncertain/incomplete result blocks before merge. Apply the same detector to merged PR and merge-commit readback. After the normal-gated merge, verify Issue #63 remains OPEN and report `MERGED_AWAITING_ISSUE_COMPLETION`.

Only after #64 is merged, complete Consumer Activation V2 on a clean default worktree at current main. The Setup PR has its own exact-HEAD review and merge decision, separate from #64. Verify the V2 record, `created_at`, Ruleset ID and current effective policy. Its `created_at` must be later than #64's merge. Then `delivery finalize 63 64` may close #63 using one durable intent, one GitHub Issue PATCH, and direct/list/direct readback. Missing/invalid Activation evidence or an ambiguous close leaves the Issue open and prohibits retrying the PATCH. Never report completion while any exact approval, chat provenance, Activation, review, or merge evidence is blocked.

When an approved successor ADC makes the existing ExecutionBinding stale, inspect it first with `python -m p_ases context show ISSUE --repo OWNER/REPO --root WORKTREE`. Use the current approved ADC and the exact existing binding values shown by the readback to run `python -m p_ases work bind ISSUE --base-ref BASE_REF --base-sha BASE_SHA40 --branch-ref BRANCH_REF --repo OWNER/REPO --root WORKTREE`. `work bind` appends the new ADC generation while retaining the original base SHA, branch, worktree, and initial HEAD; then confirm `context show` reports `BOUND` and verify the prior binding-history prefix is unchanged. Do not run `work base` to select a replacement base or recreate the binding. Keep the original PRBinding unchanged. Only after the rebind is verified, publish and independently verify the current generation's `requirements → specification → design → ready` Phase receipts before Activation.

The existing typed current-base proof remains available for workflows where Activation precedes a PR merge. For Issue #63, Activation is post-merge, so its Setup PR does not advance PR #64's pre-merge base. Preserve the original ExecutionBinding and V1 PRBinding bytes; never use general base drift as a substitute for the exact typed proof.

### Worktree boundaries for Issue #63

Keep two checkouts distinct throughout the delivery:

- **PR #64 implementation worktree:** stay on the PR #64 feature branch. Run `context show`, the successor ADC `work bind`, and the new-generation Issue #63 Phase evidence here. Preserve this worktree's feature branch, HEAD, `ExecutionBinding`, `PRBinding`, and Issue #63 history when preparing Activation.
- **Activation worktree:** select a separate, clean checkout of the repository's default branch at the exact current remote HEAD. Run `consumer-activation-setup` only with this worktree as `--root`. The setup preflight rejects a feature branch, dirty worktree, detached HEAD, or stale default-branch commit before any GitHub write.

Before running Activation, inspect available checkouts with `git worktree list`, then perform a read-only preflight on the selected Activation worktree:

```sh
git -C ACTIVATION_WORKTREE status --porcelain --untracked-files=all
git -C ACTIVATION_WORKTREE symbolic-ref --short HEAD
git -C ACTIVATION_WORKTREE rev-parse HEAD^{commit}
git -C ACTIVATION_WORKTREE ls-remote origin refs/heads/DEFAULT_BRANCH
gh api repos/OWNER/REPO/branches/DEFAULT_BRANCH --jq .commit.sha
```

Require an empty status, the symbolic branch equal to the repository's default branch, and the local HEAD, `git ls-remote` SHA, and `gh api` SHA to match exactly. If no checkout satisfies these conditions, create/select a separate worktree through Git's existing worktree boundary; do not reset or rebase the PR #64 worktree. If the default ref needs updating, update only the separate Activation worktree with a verified fast-forward, then repeat the full preflight. Do not infer the Activation root from the current directory.

The successor ADC's `work bind`, Phase evidence, current-head gates, User Review, Final Delivery, and exact PR #64 merge authorization remain in the PR #64 implementation worktree and must be complete before merge. After #64 merges and Issue #63 is confirmed OPEN, use the separate Activation worktree at the latest default-branch HEAD for Ruleset/Setup PR/Activation V2 continuation and the final `delivery finalize 63 64` Issue close. Do not return to the already-merged feature worktree for an updated #64 merge gate.

When the user directly requests Consumer Activation, run it against the explicitly selected Activation worktree:

```sh
python -m p_ases delivery consumer-activation-setup --repo OWNER/REPO --root ACTIVATION_WORKTREE
```

The command resolves the repository and Activation identity, validates the committed profile and Required Checks, and returns the persisted stage, setting inventory, checkpoint, and next step. Do not ask the user for an Issue number or for manual GitHub edits. `PENDING_APPROVAL`, `ADMIN_AUTH_REQUIRED`, `BLOCKED`, and `SETUP_PENDING` are resumable states, never Activation success.

For the #63 pre-merge `solo_owner` Ruleset gate, build the canonical plan from the clean PR #64 final HEAD and `.agent/project.json` Required Checks with `activation_binding` omitted. An exact owned policy is a zero-write `NOOP`; if a write is needed, preview the exact plan and ask for a separate chat approval that shows the repository, Issue #57 target, operation `RULESET_PLAN_APPLY`, exact plan SHA, and diff. Only a direct user-role approval in this same chat can create the V3 owner record and existing exact two-line Issue #57 approval. The record is operator-reported chat approval plus authenticated GitHub actor evidence; it is not a signed chat event. Vague continuation, assistant text, an older approval, CLI flag, or JSON/file consent is invalid. If user-role provenance is unavailable, stop without a GitHub write. This pre-merge Ruleset work does not run Activation: create/review/merge the V2 Setup PR only after #64 is merged and Issue #63 is confirmed OPEN.

```sh
python -m p_ases delivery owner-authorize-plan RULESET_PLAN_APPLY --ruleset-plan PLAN_PATH --output OWNER_PLAN_PATH
```

`owner-authorize-commit` is intentionally fail-closed. The in-process chat integration must revalidate the exact plan and authenticated owner, post via `gh`, and direct/list/direct read back both the V3 record and the existing two-line Issue #57 approval. Pass that approval comment ID to the existing Admin apply continuation.

```sh
python -m p_ases delivery consumer-activation-admin-apply --plan CHECKPOINT_PLAN_PATH --approval-comment-id OWNER_APPROVAL_COMMENT_ID
```

Admin browser device authentication is the standard mode. It runs `gh auth login --hostname github.com --web --git-protocol https --insecure-storage` with a fresh mode-0700 private `GH_CONFIG_DIR`; a runner-managed PTY may show the URL/code for browser authentication without an owner-local terminal. The login and Admin API children remove all ambient GitHub token variables, and normal `gh` configuration remains unchanged. If the runner cannot display the device challenge, report `ADMIN_DEVICE_LOGIN_UNAVAILABLE` and make no Admin request. PAT is a nonstandard explicit fallback requiring a trusted owner-local TTY. Cleanup deletes only the private config and does not revoke the OAuth grant. Never request, print, or store an Admin credential in chat.

Before PR #64 merges, read the exact canonical Ruleset plan. An already-owned matching Ruleset is a zero-write `NOOP`; if creation/update is needed, request separate exact-plan `RULESET_PLAN_APPLY` approval and use the isolated Admin flow. Do not create a duplicate Ruleset. After #64 is merged and remains open at the Issue level, Activation creates or reuses the exact V2 Setup PR from current main. Obtain separate review and exact-head chat approval for Setup PR `PR_MERGE`; the decision does not authorize #64 or Issue closure. After Setup PR merge and Activation V2 `ACTIVE` readback, verify its effective time is after #64 merge and re-read current policy. Use the same policy and record proof in `delivery finalize 63 64` before the one-shot #63 close.

After merge, run:

```sh
python -m p_ases delivery consumer-activation-verify PR
```

The verifier reconstructs the merge, Required Checks, ADC journal, admin identity, default-branch ancestry, and effective policy before appending Activation history. V2 becomes effective only at the Activation record comment's GitHub `created_at`, not at setup PR merge time. If verification blocks, report the exact reason and do not claim Activation. Once verified, a later Issue can be selected with:

```sh
python -m p_ases delivery gate-policy ISSUE
```

Pre-Activation Issues remain untouched. Subsequent policy approval uses a successor setup PR; existing Gate Selections remain pinned to their original Activation record.

An already-owned matching Ruleset is read back as `NOOP`; #64's effective policy is verified before merge, while the full #63 Activation runs after merge. `external_reviewer` keeps its existing V1 behavior and does not receive unauthorized solo-owner policy writes; show the mode-specific setting inventory and block any unsupported or unmet mandatory requirement. Existing V1 records and Gate Selections remain read-only history.

## CLI

~~~sh
python -m p_ases delivery readiness 32 42 HEAD40 path/to/plan.json path/to/verification.json path/to/acceptance.json path/to/self-audit.json path/to/independent-review.json --repo OWNER/REPO --root .
python -m p_ases delivery bootstrap-check 32 42 --repo OWNER/REPO --root .
python -m p_ases delivery final 32 42 HEAD40 path/to/plan.json path/to/verification.json path/to/acceptance.json path/to/self-audit.json path/to/independent-review.json path/to/readiness.json path/to/user-review.json --repo OWNER/REPO --root .
python -m p_ases delivery finalize 32 42 --repo OWNER/REPO --root .
python -m p_ases delivery parent-migrate-labels 26 --repo OWNER/REPO --root .
~~~

Parent label migration is preflight-only unless the explicit apply option is supplied and authorized. Bootstrap review waiver does not waive exact identity, tests, current-head CI, provenance, or the user's separate merge permission.

## Failure handling and output

Stale evidence, missing required checks, wrong App ID, draft/foreign PR, blocked user review, or unavailable branch protection is not ready. Report the exact blocker and evidence refs. Never merge, tag, publish a Release, activate the parent, or close #26 under this Issue #32 contract.

Next owners: integration-validation supplies parent gates; user-review supplies current feedback. See the [delivery design](../../../docs/design/workflow-design.md).
