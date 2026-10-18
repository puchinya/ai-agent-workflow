---
name: integration-validation
description: Validate the complete child DAG and parent evidence against current GitHub and Actions readback.
---
# Integration validation

## Owner and inputs

Owner: runtime/p_ases/integration.py, issue_graph.py, and user_review.py. Inputs are the parent ADC, fixed child set and dependency DAG, child Issues and PRs, merged SHAs, current main, and trusted GitHub Actions evidence.

## Workflow

1. Re-read the parent ADC and its current approval pointer. Confirm the fixed child Issues #27–#32 are all closed, each closing PR is merged into `main`, every dependency edge is correct, and all six merge commits are ancestors of the current `main` commit. If any child remains open or unmerged, stop with parent Integration blocked.
2. Read the current `main` SHA once. In GitHub Actions, select the latest completed run by run number and attempt for that exact SHA and same repository for each evidence kind:

   | Evidence kind | Workflow file | Required event | Subject |
   | --- | --- | --- | --- |
   | Verification | `.github/workflows/ci.yml` | `push` | `head_branch=main`, exact current `main` SHA |
   | Acceptance | `.github/workflows/parent-integration.yml` | `workflow_dispatch` | `head_branch=main`, the same current `main` SHA |

   Both runs must conclude successfully and satisfy the trusted App ID and required job/step checks. Do not use a `pull_request` run, an older successful run superseded by a newer attempt, or the same run ID for both kinds. If either latest matching run failed, stop; an older success cannot replace it.
3. Publish and read back each typed result separately, using its own run ID:

~~~sh
python -m p_ases delivery parent-evidence 26 verification VERIFICATION_RUN_ID --repo OWNER/REPO --root .
python -m p_ases delivery parent-evidence 26 acceptance ACCEPTANCE_RUN_ID --repo OWNER/REPO --root .
~~~

   Save each command's `comment_id` from its JSON output. These are Issue #26 comment IDs, not Actions run IDs. The publisher re-reads the current main SHA, approved ADC, selected run, trusted checks, and exact evidence comment; continue only when each command returns success and its `comment_id`.
4. Pass both returned comment IDs to the Integration readback, then to the parent delivery gate:

~~~sh
python -m p_ases issue integration-check 26 --verification-comment-id VERIFICATION_COMMENT_ID --acceptance-comment-id ACCEPTANCE_COMMENT_ID --repo OWNER/REPO --root .
python -m p_ases delivery parent 26 --verification-comment-id VERIFICATION_COMMENT_ID --acceptance-comment-id ACCEPTANCE_COMMENT_ID --repo OWNER/REPO --root .
~~~

   Require `issue integration-check` to return `PASS` before interpreting the `delivery parent` result. Both commands re-read the exact current comments and their Actions provenance. Parent Integration, parent User Review, Activation, merge, and release remain separate decisions.


## Lifecycle handoff

Child Issues in the parent DAG follow the ordinary single/child sequence: approved ADC/rebaseline, exact frozen Binding, specification/design/Test Oracle artifacts and receipts, `ready`, `execution`, implementation, current Verification/Acceptance/Self-Audit and fresh native Independent Review, then `verification`, Review Readiness, and `user-review start`. Parent Integration and parent User Review remain on their separate parent route. Blocking findings are fixed during `execution` at a new HEAD with a fresh child. Runtime commands are one-shot mutations/readbacks; Skills and adapters own orchestration. Readiness cannot PASS outside its permitted phase/session, and PENDING is waiting only after session, feedback snapshot, and `phase:user-review` readback.

## Failure handling and output

Handwritten PASS, stale run, wrong repository/SHA/App/event/workflow, skipped step, incomplete matrix, open child, mutated pointer, or wrong merge ancestry blocks. Report the exact child or Actions source and failed identity field. Do not treat #32's open PR as parent acceptance.

Next owner: delivery-control aggregates final parent status. See the [integration design](../../../docs/design/workflow-design.md) and [workflow specification](../../../docs/specs/workflow-spec.md).
