---
name: delivery-control
description: Evaluate Review Readiness and Final Delivery without merging or publishing.
---
# Delivery control

## Owner and inputs

Owner: runtime/p_ases/delivery.py, branch_policy.py, and gate_policy.py. Inputs are current PR identity, exact HEAD, final Verification and Acceptance, audit and review evidence, User Review, the trusted profile Required Checks, the selected review mode, and read-only GitHub branch/ruleset evidence.

## Workflow

1. Read the gate policy for the Issue. Fixed Bootstrap Issues #27–#32 use the separate technical evaluator before activation.
2. Evaluate ordinary Review Readiness from current exact-subject inputs. Do not substitute Bootstrap technical readiness for normal product gates.
3. For final delivery, re-read User Review, all formal PR reviews, current-head Required Checks, effective branch policy, and mergeability; repeat those reads before publishing the result.
4. Report branch policy as `VERIFIED`, `NOT_CONFIGURED`, `UNAVAILABLE`, `UNVERIFIED`, or `MISMATCH`, including the exact branch, readable sources, HTTP errors, stable reason codes, and required owner action. A 403 is unavailable evidence; a 404 by itself is unverified evidence. Neither is proof that policy is absent or satisfied.
5. Keep `external_reviewer` as the default. It requires current-head approval from a different human and policy requiring at least one formal approval. `solo_owner` is explicit opt-in for a personal repository when its owner, authenticated User, and PR author IDs match; it requires an active applicable ruleset with required PR, exact trusted Checks/App IDs, zero approvals, force-push prohibition, and no bypass actors.
6. Verify an already merged PR and closed Issue only with the finalize command. In `solo_owner`, the authenticated owner and PR author must still match and `merged_by` must be that same User.
7. Present PR number, exact HEAD, technical checks, policy diagnostics, risks, and intended order before any merge request. `READY_FOR_EXPLICIT_MERGE_AUTHORIZATION` returns `merge_authorized: false`; a successful check is not user merge permission.

## Consumer Activation request

When the user directly says `P-ASESを有効化して。` in a consumer repository, run setup from that active repository context:

```sh
python -m p_ases delivery consumer-activation-setup
```

The command resolves the repository from the workspace, creates or reuses one marked Activation Issue, publishes a proposed default Activation ADC only if none exists, adds `activation.issue_number` to `.agent/project.json` on a setup branch, and opens or reuses the reviewable PR. Do not ask the user to supply an Issue number. Setup does not activate the repository and does not change phase labels.

Present the Issue and PR. The authenticated repository admin reviews the proposed ADC and the exact `.agent/project.json` change, configures `branch.required_checks` with the repository's real check names and trusted App IDs if the generated list is empty, then merges the setup PR. The agent must not merge it on this prompt alone. After the admin confirms the merge, run:

```sh
python -m p_ases delivery consumer-activation-verify PR
```

Run the verifier as the same authenticated human who merged the PR. It reconstructs the merge, required checks, ADC journal, admin identity, and default-branch ancestry before it appends Activation history. If verification blocks, report the exact reason and do not claim Activation. Once verified, a later Issue can be selected with:

```sh
python -m p_ases delivery gate-policy ISSUE
```

Pre-Activation Issues remain untouched. Subsequent policy approval uses a successor setup PR; existing Gate Selections remain pinned to their original Activation record.

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

Stale evidence, missing required checks, wrong App ID, draft/foreign PR, blocked user review, unavailable or unverified branch policy, or a policy mismatch is not ready. Report the exact blocker, policy source readbacks, required owner action, and evidence refs. This workflow only reads GitHub branch settings; it never changes protection, bypass, or permissions and never merges. Never tag, publish a Release, activate the parent, or close #26 under this Issue #32 contract.

Next owners: integration-validation supplies parent gates; user-review supplies current feedback. See the [delivery design](../../docs/design/workflow-design.md).
