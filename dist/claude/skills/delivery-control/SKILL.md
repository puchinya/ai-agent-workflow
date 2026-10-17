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

When the user directly says `P-ASESを有効化して。` in a consumer repository, run setup from that active repository context:

```sh
python -m p_ases delivery consumer-activation-setup
```

The command resolves the repository from the workspace, creates or reuses one marked Activation Issue, publishes a proposed default Activation ADC only if none exists, adds `activation.issue_number` to `.agent/project.json` on a setup branch, and opens or reuses the reviewable PR. Do not ask the user to supply an Issue number. Setup does not activate the repository and does not change phase labels.

For an explicitly configured `final_delivery.review_mode: solo_owner`, prepare the repository Ruleset only from a committed and pushed implementation branch. Start with the read-only preflight, then write the canonical plan outside the repository worktree:

```sh
python -m p_ases delivery consumer-activation-preflight
python -m p_ases delivery consumer-activation-ruleset-plan --output /tmp/pases-ruleset-plan.json
```

Present the plan and its SHA-256. The repository owner must manually post this exact two-line comment on Activation Issue #57:

```text
PASES-RULESET-APPROVE: <64-digit plan SHA-256>
PASES-REPOSITORY: OWNER/REPOSITORY
```

The agent must not create or edit that approval. After the owner posts it, run apply with the plan path and exact comment ID:

```sh
python -m p_ases delivery consumer-activation-ruleset-apply --plan /tmp/pases-ruleset-plan.json --approval-comment-id COMMENT_ID
```

Apply rechecks the repository, profile, current policy, PR impact, owner identity, admin permission, and approval before a single Ruleset write. It then reads back the Ruleset and effective branch policy and appends ownership evidence to #57. A forbidden or incomplete read blocks; do not treat HTTP 403 as an unconfigured branch.

Present the Issue and PR. The authenticated repository admin reviews the proposed ADC and the exact `.agent/project.json` change, configures `branch.required_checks` with the repository's real check names and trusted App IDs if the generated list is empty, then merges the setup PR. The agent must not merge it on this prompt alone. After the admin confirms the merge, run:

```sh
python -m p_ases delivery consumer-activation-verify PR
```

Run the verifier as the same authenticated human who merged the PR. It reconstructs the merge, required checks, ADC journal, admin identity, and default-branch ancestry before it appends Activation history. If verification blocks, report the exact reason and do not claim Activation. Once verified, a later Issue can be selected with:

```sh
python -m p_ases delivery gate-policy ISSUE
```

Pre-Activation Issues remain untouched. Subsequent policy approval uses a successor setup PR; existing Gate Selections remain pinned to their original Activation record.

When an explicit `solo_owner` policy has an applied Ruleset, setup creates a versioned V2 successor that binds the exact profile bytes, mode, trusted Required Checks/App IDs, Ruleset ID, and effective policy digest. V2 uses the GitHub Activation-record comment creation time; Issues created between setup merge and record publication remain on their prior eligible Activation. Existing V1 records and Gate Selections are read-only history.

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
