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
   For Issue #46 / PR #67 only, if native capture is positively unavailable, first run a separate-context Independent Review of the exact current HEAD and record its actual verdict and findings. `UNAVAILABLE` describes host provenance only. A missing report, non-PASS verdict, unresolved A/B/C finding, or stale report blocks. After the approved ADC's opt-in is current, the exception route may disclose `INDEPENDENT_REVIEW_PROVENANCE_UNAVAILABLE`; it never means the review was skipped. Request any required operation approval through the active chat UI (`承認する` / `承認しない`); do not ask the Owner to post an approval comment. No verification, acceptance, CI, dependency, User Review, or merge gate is waived.
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
python -m p_ases audit independent 46 67 HEAD40 path/to/frozen-plan.json path/to/separate-context-review.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery review-unavailable-plan 46 67 HEAD40 path/to/frozen-plan.json --host-surface codex_cloud --output /tmp/review-unavailable-plan.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases chat-decision record 46 67 REVIEW_UNAVAILABLE_EXCEPTION PLAN_SHA256 /tmp/review-unavailable-scope.json QUESTION_ITEM_ID '承認する' --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery review-unavailable-apply 46 67 HEAD40 path/to/frozen-plan.json --plan /tmp/review-unavailable-plan.json --chat-decision-comment-id DECISION_COMMENT_ID --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery readiness 46 67 HEAD40 path/to/plan.json path/to/verification.json path/to/acceptance.json path/to/self-audit.json --review-unavailable-exception path/to/exception.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery bootstrap-check 32 42 --repo OWNER/REPO --root .
python -m p_ases delivery final 32 42 HEAD40 path/to/plan.json path/to/verification.json path/to/acceptance.json path/to/self-audit.json path/to/independent-review.json path/to/readiness.json path/to/user-review.json --repo OWNER/REPO --root .
python -m p_ases delivery final 46 67 HEAD40 path/to/plan.json path/to/verification.json path/to/acceptance.json path/to/self-audit.json path/to/readiness-v2.json path/to/user-review.json --review-unavailable-exception path/to/exception.json --repo puchinya/ai-agent-workflow --root .
python -m p_ases delivery finalize 32 42 --repo OWNER/REPO --root .
python -m p_ases delivery parent-migrate-labels 26 --repo OWNER/REPO --root .
~~~

The `audit independent` command is required before the Issue #46 exception plan. It records a completed separate-context review and its actual findings even when host provenance is `UNAVAILABLE`. The plan/apply commands never substitute for that review. Show the full plan in the active chat approval UI before recording the user's `承認する` or `承認しない` answer; the Owner does not author an Issue approval comment. `chat-decision record` appends only a technical record after the direct active-chat choice.

Parent label migration is preflight-only unless the explicit apply option is supplied and authorized. Bootstrap review waiver does not waive exact identity, tests, current-head CI, provenance, or the user's separate merge permission.

## Failure handling and output

Stale evidence, missing required checks, wrong App ID, draft/foreign PR, blocked user review, or unavailable branch protection is not ready. Report the exact blocker and evidence refs. A V2 exception never authorizes merge. Never merge, tag, publish a Release, activate the parent, or close #26 under this Issue #32 contract.

Next owners: integration-validation supplies parent gates; user-review supplies current feedback. See the [delivery design](../../docs/design/workflow-design.md).
