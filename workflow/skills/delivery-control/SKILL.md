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
   For Issue #46 / PR #67 only, if the approved successor ADC and Phase rebaseline are current and native capture is positively unavailable, the repository-specific opt-in may use the separate `delivery review-unavailable-plan` / `delivery review-unavailable-apply` route. This produces a visibly degraded Readiness V2 with `review_assurance=UNAVAILABLE`; it does not label Independent Review PASS or waive any verification, acceptance, CI, dependency, User Review, or merge requirement.
3. For final delivery, re-read User Review, GitHub formal review, Required Checks, branch protection, and mergeability.
4. Verify an already merged PR and closed Issue only with the finalize command.
5. Present PR number, exact HEAD, technical checks, risks, and intended order before any merge request. A successful check is not user merge permission.

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
python -m p_ases delivery review-unavailable-plan 46 67 HEAD40 path/to/frozen-plan.json --host-surface codex_cloud --output /tmp/review-unavailable-plan.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery review-unavailable-apply 46 67 HEAD40 path/to/frozen-plan.json --plan /tmp/review-unavailable-plan.json --approval-comment-id OWNER_COMMENT_ID --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery readiness 46 67 HEAD40 path/to/plan.json path/to/verification.json path/to/acceptance.json path/to/self-audit.json --review-unavailable-exception path/to/exception.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery bootstrap-check 32 42 --repo OWNER/REPO --root .
python -m p_ases delivery final 32 42 HEAD40 path/to/plan.json path/to/verification.json path/to/acceptance.json path/to/self-audit.json path/to/independent-review.json path/to/readiness.json path/to/user-review.json --repo OWNER/REPO --root .
python -m p_ases delivery final 46 67 HEAD40 path/to/plan.json path/to/verification.json path/to/acceptance.json path/to/self-audit.json path/to/readiness-v2.json path/to/user-review.json --review-unavailable-exception path/to/exception.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery finalize 32 42 --repo OWNER/REPO --root .
python -m p_ases delivery parent-migrate-labels 26 --repo OWNER/REPO --root .
~~~

Parent label migration is preflight-only unless the explicit apply option is supplied and authorized. Bootstrap review waiver does not waive exact identity, tests, current-head CI, provenance, or the user's separate merge permission.

## Failure handling and output

Stale evidence, missing required checks, wrong App ID, draft/foreign PR, blocked user review, or unavailable branch protection is not ready. Report the exact blocker and evidence refs. A V2 exception never authorizes merge. Never merge, tag, publish a Release, activate the parent, or close #26 under this Issue #32 contract.

Next owners: integration-validation supplies parent gates; user-review supplies current feedback. See the [delivery design](../../../docs/design/workflow-design.md).
