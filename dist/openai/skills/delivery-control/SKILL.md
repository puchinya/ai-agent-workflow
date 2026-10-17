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

For Issue #63, complete the implementation on PR #64 first. Then finalize and read back the successor ADC's exact bytes and SHA, obtain separate exact-SHA `PHASE_REBASE` and `ADC_SUPERSEDE` approvals, publish/read back that generation, and establish its Phase receipts. Complete Consumer Activation V2 through `ACTIVE` next. Its Setup PR must be reviewed and merged with its own exact-HEAD decision; this is separate from PR #64's merge. Only after the V2 record comment, `created_at`, Ruleset ID and effective policy all read back may PR #64's current HEAD gates and separate `PR_MERGE` decision be evaluated. Merge #64, preserve its standalone `Closes #63`, then read back Issue #63 closure. Never report completion while ADC approval, broker boundary, Activation, review, or merge evidence is blocked.

Activation may advance the frozen base from A to B through its one profile-only Setup PR. Preserve the original ExecutionBinding and V1 PRBinding bytes. Accept that change only with the exact create-only current-base evidence that binds the Activation V2 record, Setup PR merge, profile bytes, target PR identity, and unchanged PR code patch. Readiness and Final Delivery must repeat the same live checks. Any other base drift blocks.

When the user directly says `P-ASESを有効化して。` in a consumer repository, run Activation from that active repository context:

```sh
python -m p_ases delivery consumer-activation-setup
```

The command resolves the repository and Activation identity, validates the committed profile and Required Checks, and returns a typed persisted stage, required-setting inventory, checkpoint, and next permitted step. Do not ask the user to supply an Issue number. The command may create or reuse the marked Activation Issue and proposed ADC under the existing append-only rules. For V2 it prepares only the setup branch and profile commit first; it does not create the V2 setup PR until the required policy is verified. `PENDING_APPROVAL`, `ADMIN_AUTH_REQUIRED`, `BLOCKED`, and `SETUP_PENDING` are resumable states, never Activation success. Do not ask the owner to edit an Issue, PR, Ruleset, label, or Settings page manually.

For the #63 `solo_owner` profile, Activation builds a canonical Ruleset plan bound to the committed setup-branch HEAD and persists it in the checkpoint. If a write is needed, present the exact plan SHA and request the distinct `RULESET_PLAN_APPLY` decision through the isolated owner relay. A generic “continue” or an Admin credential is not approval. The Codex executor must not create the Issue #57 approval evidence. Once the isolated relay records the decision and exact plan approval, the owner resumes that checkpoint from a trusted local TTY:

```sh
python -m p_ases delivery consumer-activation-admin-apply --plan CHECKPOINT_PLAN_PATH --approval-comment-id RELAY_COMMENT_ID
```

Never request, print, or store the Admin credential in chat. The TTY command verifies the pinned owner, repository, permission, exact plan and relay evidence, then uses the existing one-write/durable-intent/readback path. If Admin policy reads are unavailable to the normal client, the same owner-local TTY continuation may generate the bound plan; no setup PR is created until policy readback is `VERIFIED`. An exact already-owned policy is `NOOP`, performs zero writes, and needs no write approval. If the local TTY or credentials are unavailable, keep Activation resumably blocked at provisioning and continue independent code/review work.

After verified policy readback, Activation creates or reuses the exact V2 setup PR bound to the Ruleset ID, applied-record ID, and effective-policy digest. If required check names or trusted App IDs are missing, report `INPUT_REQUIRED` with their exact profile fields; never guess. Obtain the separate independent review, current Required Checks, User Review, Final Delivery, and exact-HEAD `PR_MERGE` decision before the isolated relay performs a merge. A successful Ruleset apply is not merge permission. After merge, run:

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

Next owners: integration-validation supplies parent gates; user-review supplies current feedback. See the [delivery design](../../docs/design/workflow-design.md).
