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

For Issue #63, complete the implementation on PR #64 first. Then finalize and read back the successor ADC's exact bytes and SHA, obtain its separate exact-SHA `ADC_SUPERSEDE` approval, and publish/read back that generation. Finalize the successor ADC draft in the reviewed implementation commit. From the owner's fixed, clean checkout, create and confirm the exact local plan:

~~~sh
python -m p_ases delivery owner-authorize-plan ADC_SUPERSEDE --subject-file docs/contracts/issue-63-successor-adc-draft.md --output /tmp/pases-issue63-adc-plan.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery owner-authorize-commit --plan /tmp/pases-issue63-adc-plan.json --subject-file docs/contracts/issue-63-successor-adc-draft.md --repo puchinya/ai-agent-workflow --root .
~~~

The second command writes the V2 decision, publishes and reads back the exact approved ADC through the existing writer, then runs #63 phase rebaseline automatically. If it stops after publication, re-entry reuses the exact pointer and phase Intent/Applied evidence.

The authenticated P-ASES executor then automatically advances `phase:ready` to `phase:requirements` with append-only Intent/Applied logs and one label write; no phase approval is required. Establish that generation's Phase receipts before Activation. If an approved ADC publish was interrupted after pointer publication, resume the phase step with `python -m p_ases issue phase-rebaseline 63 --repo puchinya/ai-agent-workflow`; the route verifies the same pointer chain and recovers from its Intent/Applied records without repeating the label PUT. Complete Consumer Activation V2 through `ACTIVE` next. Its Setup PR must be reviewed and merged with its own exact-HEAD decision; this is separate from PR #64's merge. Only after the V2 record comment, `created_at`, Ruleset ID and effective policy all read back may PR #64's current HEAD gates and separate `PR_MERGE` decision be evaluated. Merge #64, preserve its standalone `Closes #63`, then read back Issue #63 closure. Never report completion while ADC approval, owner-local transport or verified broker, Activation, review, or merge evidence is blocked.

Activation may advance the frozen base from A to B through its one profile-only Setup PR. Preserve the original ExecutionBinding and V1 PRBinding bytes. Accept that change only with the exact create-only current-base evidence that binds the Activation V2 record, Setup PR merge, profile bytes, target PR identity, and unchanged PR code patch. Readiness and Final Delivery must repeat the same live checks. Any other base drift blocks.

When the user directly says `P-ASESを有効化して。` in a consumer repository, run Activation from that active repository context:

```sh
python -m p_ases delivery consumer-activation-setup
```

The command resolves the repository and Activation identity, validates the committed profile and Required Checks, and returns a typed persisted stage, required-setting inventory, checkpoint, and next permitted step. Do not ask the user to supply an Issue number. The command may create or reuse the marked Activation Issue and proposed ADC under the existing append-only rules. For V2 it prepares only the setup branch and profile commit first; it does not create the V2 setup PR until the required policy is verified. `PENDING_APPROVAL`, `ADMIN_AUTH_REQUIRED`, `BLOCKED`, and `SETUP_PENDING` are resumable states, never Activation success. Do not ask the owner to edit an Issue, PR, Ruleset, label, or Settings page manually.

For the #63 `solo_owner` profile, Activation builds a canonical Ruleset plan bound to the committed setup-branch HEAD and persists it in the checkpoint. If a write is needed, create the exact owner authorization plan and use the owner's independent trusted local TTY for `RULESET_PLAN_APPLY`:

```sh
python -m p_ases delivery owner-authorize-plan RULESET_PLAN_APPLY --ruleset-plan PLAN_PATH --output OWNER_PLAN_PATH
python -m p_ases delivery owner-authorize-commit --plan OWNER_PLAN_PATH --ruleset-plan PLAN_PATH
```

The command verifies the local authenticated owner, pinned repository identity, exact plan and Issue subjects, then requires the owner to type the displayed plan SHA. It appends the V2 decision and existing exact two-line Issue #57 plan approval, then reads both back. Codex Cloud, Cloud PTY, shared token variables, a generic “continue”, or an Admin credential are not approval. Pass the returned Issue #57 comment ID to the existing Admin apply continuation.

```sh
python -m p_ases delivery consumer-activation-admin-apply --plan CHECKPOINT_PLAN_PATH --approval-comment-id OWNER_APPROVAL_COMMENT_ID
```

The two Admin continuations accept `--auth-mode pat|isolated-gh-device`, defaulting to `pat`. Keep the existing PAT mode on a separate trusted owner-local TTY. To opt into the isolated device mode, add `--auth-mode isolated-gh-device` to the Admin command. It runs the exact `gh auth login --hostname github.com --web --git-protocol https --insecure-storage` command with a fresh mode-0700 private `GH_CONFIG_DIR`; the human completes the displayed device challenge. The login and Admin API children do not inherit `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`, or `GITHUB_ENTERPRISE_TOKEN`, and the normal `gh` profile remains unchanged. Device mode requires a real interactive input/output TTY and a host that can verify mode-0700 permissions. If the TTY, permissions, or login are unavailable, report `ADMIN_DEVICE_LOGIN_UNAVAILABLE`, make no Admin request, and keep the owner-local PAT fallback available; do not silently switch modes. Cleanup deletes only the private config. It does not revoke the GitHub OAuth grant, which requires a separate owner action and may affect other devices. A same-OS-user subprocess is not a strong sandbox.

Never request, print, or store the Admin credential in chat. The Admin TTY command verifies the pinned owner, repository, permission, exact plan and owner-local V2 decision, then uses the existing one-write/durable-intent/readback path. If Admin policy reads are unavailable to the normal client, the same owner-local TTY continuation may generate the bound plan; no setup PR is created until policy readback is `VERIFIED`. An exact already-owned policy is `NOOP`, performs zero writes, and needs no write approval. If the selected authentication mode cannot start, keep Activation resumably blocked at provisioning and report its exact error code.

After verified policy readback, Activation creates or reuses the exact V2 setup PR bound to the Ruleset ID, applied-record ID, and effective-policy digest. If required check names or trusted App IDs are missing, report `INPUT_REQUIRED` with their exact profile fields; never guess. Obtain separate independent review, current Required Checks, User Review, Final Delivery, and exact-HEAD `PR_MERGE` authorization. Use a fresh exact plan and owner-local TTY commit, or a positively verified broker, for the merge action; the decision for the Setup PR does not authorize PR #64. A successful Ruleset apply is not merge permission. For either PR merge, run the plan and commit commands from the owner's fixed, clean checkout at the reviewed implementation HEAD, on a trusted local TTY with local GitHub authentication and without shared token environment variables. The Setup PR plan binds Issue #57 in its canonical Activation V2 payload; it does not close Issue #57. Its commit rechecks the policy, ADC generation, exact HEAD, trusted Required Checks, independent approval, and resolved review threads. PR #64's commit requires fresh PASS Final Delivery inputs for the same repository, Issue, PR, and HEAD:

~~~sh
python -m p_ases delivery owner-authorize-plan PR_MERGE --pr SETUP_PR_NUMBER --head SETUP_HEAD_SHA --target-issue 57 --output /tmp/pases-setup-merge-plan.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery owner-authorize-commit --plan /tmp/pases-setup-merge-plan.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery owner-authorize-plan PR_MERGE --pr 64 --head CURRENT_PR64_HEAD_SHA --target-issue 63 --output /tmp/pases-pr64-merge-plan.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery owner-authorize-commit --plan /tmp/pases-pr64-merge-plan.json --readiness READINESS_JSON --delivery-plan VERIFICATION_PLAN_JSON --verification VERIFICATION_JSON --acceptance ACCEPTANCE_JSON --self-audit SELF_AUDIT_JSON --independent-review INDEPENDENT_REVIEW_JSON --user-review-record USER_REVIEW_JSON --repo puchinya/ai-agent-workflow --root .
~~~

Each commit confirms the displayed plan SHA locally, writes one V2 decision, re-runs its target gates, records a durable merge attempt, and calls GitHub once with the exact HEAD. Repeated commit or resume commands read back the PR and never repeat a merge request. A successful call is not Activation completion; #57 still requires its post-merge V2 verification and ACTIVE record before PR #64 is eligible.

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

Next owners: integration-validation supplies parent gates; user-review supplies current feedback. See the [delivery design](../../docs/design/workflow-design.md).
