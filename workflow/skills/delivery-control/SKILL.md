---
name: delivery-control
description: Evaluate Review Readiness and Final Delivery without merging or publishing.
---
# Delivery control

## Owner and inputs

Owner: runtime/p_ases/delivery.py and gate_policy.py. Inputs are current PR identity, exact HEAD, final Verification and Acceptance, audit and review evidence, User Review, required Checks, branch protection, and explicit user permissions.

## Workflow

1. Read the gate policy for the Issue. Fixed Bootstrap Issues #27–#32 use the separate technical evaluator before activation.
2. Evaluate ordinary Review Readiness from current exact-subject inputs. Do not substitute Bootstrap technical readiness for normal product gates.
3. For final delivery, re-read User Review, GitHub formal review, Required Checks, branch protection, and mergeability.
4. Verify an already merged PR and closed Issue only with the finalize command.
5. Present PR number, exact HEAD, technical checks, risks, and intended order before any merge request. A successful check is not user merge permission.

## Consumer Activation request

### Issue #63 delivery order

For Issue #63, complete the implementation on PR #64 first. Finalize the successor ADC bytes in the reviewed implementation and calculate its SHA-256. Provide the canonical `.md` file and render its complete contents as Markdown in this same chat before requesting approval; do not wrap the ADC in a fenced source-code block or HTML disclosure/container. A file link, excerpt, or SHA alone is insufficient. If the selection UI cannot contain the whole document, render the complete Markdown in the immediately preceding message in this conversation, link the canonical file, and make the approval prompt explicitly refer to that rendered document. Include the exact ADC SHA, current approved predecessor pointer, `ADC_SUPERSEDE` operation, plan SHA, approval-scope SHA, and resulting automatic Phase update in the prompt. If any ADC byte changes, recalculate the SHA, provide and render the complete new Markdown again, and request fresh approval. Prior approval for an older SHA does not transfer. The `owner-authorize-plan` CLI command is a read-only preview; `owner-authorize-commit` is disabled because a CLI cannot prove chat user-role provenance. When the current chat host exposes the actual user-role approval event, the in-process integration records a V3 scope and uses the existing ADC publisher/readback. If the host cannot supply that event, report `CHAT_PROVENANCE_UNAVAILABLE` and stop before a GitHub write.

After approved pointer readback, the regular P-ASES executor automatically advances #63 from `phase:ready` to `phase:requirements` with append-only Intent/Applied evidence and at most one label update. No `PHASE_REBASE` approval is requested. Establish that generation's Phase receipts before Activation. If publication was interrupted, use the existing read-only/resume routes and never repeat a confirmed pointer or label write. Complete Consumer Activation V2 through `ACTIVE` next. Its Setup PR has its own exact-HEAD review and merge decision, separate from PR #64. Only after the V2 record, `created_at`, Ruleset ID and effective policy read back may #64's current HEAD gates and separate `PR_MERGE` decision be evaluated. Merge #64, preserve `Closes #63`, then read back Issue #63 closure. Never report completion while any exact approval, chat provenance, Activation, review, or merge evidence is blocked.

When an approved successor ADC makes the existing ExecutionBinding stale, inspect it first with `python -m p_ases context show ISSUE --repo OWNER/REPO --root WORKTREE`. Use the current approved ADC and the exact existing binding values shown by the readback to run `python -m p_ases work bind ISSUE --base-ref BASE_REF --base-sha BASE_SHA40 --branch-ref BRANCH_REF --repo OWNER/REPO --root WORKTREE`. `work bind` appends the new ADC generation while retaining the original base SHA, branch, worktree, and initial HEAD; then confirm `context show` reports `BOUND` and verify the prior binding-history prefix is unchanged. Do not run `work base` to select a replacement base or recreate the binding. Keep the original PRBinding unchanged. Only after the rebind is verified, publish and independently verify the current generation's `requirements → specification → design → ready` Phase receipts before Activation.

Activation may advance the frozen base from A to B through its one profile-only Setup PR. Preserve the original ExecutionBinding and V1 PRBinding bytes. Accept that change only with the exact create-only current-base evidence binding the Activation V2 record, Setup PR merge, profile bytes, target PR identity, and unchanged PR code patch. Readiness and Final Delivery repeat the same live checks. Any other base drift blocks.

When the user directly requests Consumer Activation, run it from that active repository context:

```sh
python -m p_ases delivery consumer-activation-setup
```

The command resolves the repository and Activation identity, validates the committed profile and Required Checks, and returns the persisted stage, setting inventory, checkpoint, and next step. Do not ask the user for an Issue number or for manual GitHub edits. `PENDING_APPROVAL`, `ADMIN_AUTH_REQUIRED`, `BLOCKED`, and `SETUP_PENDING` are resumable states, never Activation success.

For the #63 `solo_owner` profile, Activation builds the canonical Ruleset plan and persists it in the checkpoint. If a write is needed, preview the exact plan and ask for a separate chat approval that shows the repository, Issue #57 target, operation `RULESET_PLAN_APPLY`, exact plan SHA, and diff. Only a direct user-role approval in this same chat can create the V3 owner record and existing exact two-line Issue #57 approval. The record is operator-reported chat approval plus authenticated GitHub actor evidence; it is not a signed chat event. Vague continuation, assistant text, an older approval, CLI flag, or JSON/file consent is invalid. If user-role provenance is unavailable, stop without a GitHub write.

```sh
python -m p_ases delivery owner-authorize-plan RULESET_PLAN_APPLY --ruleset-plan PLAN_PATH --output OWNER_PLAN_PATH
```

`owner-authorize-commit` is intentionally fail-closed. The in-process chat integration must revalidate the exact plan and authenticated owner, post via `gh`, and direct/list/direct read back both the V3 record and the existing two-line Issue #57 approval. Pass that approval comment ID to the existing Admin apply continuation.

```sh
python -m p_ases delivery consumer-activation-admin-apply --plan CHECKPOINT_PLAN_PATH --approval-comment-id OWNER_APPROVAL_COMMENT_ID
```

Admin browser device authentication is the standard mode. It runs `gh auth login --hostname github.com --web --git-protocol https --insecure-storage` with a fresh mode-0700 private `GH_CONFIG_DIR`; a runner-managed PTY may show the URL/code for browser authentication without an owner-local terminal. The login and Admin API children remove all ambient GitHub token variables, and normal `gh` configuration remains unchanged. If the runner cannot display the device challenge, report `ADMIN_DEVICE_LOGIN_UNAVAILABLE` and make no Admin request. PAT is a nonstandard explicit fallback requiring a trusted owner-local TTY. Cleanup deletes only the private config and does not revoke the OAuth grant. Never request, print, or store an Admin credential in chat.

After policy readback is `VERIFIED`, Activation creates or reuses the exact V2 Setup PR. Obtain separate review and exact-head chat approval for Setup PR `PR_MERGE`; the decision does not authorize PR #64. After Setup PR merge and Activation V2 `ACTIVE` readback, re-run all current PR #64 checks and gates. Request a separate exact-subject PR #64 `PR_MERGE` approval only after showing the current HEAD, Final Delivery, User Review, Independent Review, CI and base proof in this chat. Use a fresh `owner-authorize-plan` for reviewable scope, then the in-process V3 integration. Do not treat `owner-authorize-commit` or a generic continuation as approval. Merge attempts are at most once; uncertain outcomes are resolved by read-only PR readback.

After merge, run:

```sh
python -m p_ases delivery consumer-activation-verify PR
```

The verifier reconstructs the merge, Required Checks, ADC journal, admin identity, default-branch ancestry, and effective policy before appending Activation history. V2 becomes effective only at the Activation record comment's GitHub `created_at`, not at setup PR merge time. If verification blocks, report the exact reason and do not claim Activation. Once verified, a later Issue can be selected with:

```sh
python -m p_ases delivery gate-policy ISSUE
```

Pre-Activation Issues remain untouched. Subsequent policy approval uses a successor setup PR; existing Gate Selections remain pinned to their original Activation record.

An already-owned matching Ruleset is read back as `NOOP`; the #63 Activation runs before PR #64 merges and must not create a duplicate Ruleset. `external_reviewer` keeps its existing V1 behavior and does not receive unauthorized solo-owner policy writes; show the mode-specific setting inventory and block any unsupported or unmet mandatory requirement. Existing V1 records and Gate Selections remain read-only history.

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
