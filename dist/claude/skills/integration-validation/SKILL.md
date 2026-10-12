---
name: integration-validation
description: Validate the complete child DAG and parent evidence against current GitHub and Actions readback.
---
# Integration validation

## Owner and inputs

Owner: runtime/p_ases/integration.py, issue_graph.py, and user_review.py. Inputs are the parent ADC, fixed child set and dependency DAG, child Issues and PRs, merged SHAs, current main, and trusted GitHub Actions evidence.

## Workflow

1. Re-read every child Issue and PR. Require same repository, base main, standalone child closure, merged state, and dependency order.
2. Reconstruct Verification or Acceptance evidence from GitHub Actions API Run, Job, Step, and Check Run data bound to current main and trusted App ID 15368.
3. Treat Issue #26 evidence comments as mutable pointers/cache. Double-read them and compare with the reconstructed canonical evidence.
4. Keep the parent blocked while any child is open, any PR is unmerged, or required evidence is stale or incomplete.
5. Keep Integration, parent User Review, Activation, merge, and release as separate decisions.

## CLI

~~~sh
python -m p_ases issue integration-check 26 --repo OWNER/REPO --root .
python -m p_ases delivery parent 26 --repo OWNER/REPO --root .
python -m p_ases delivery parent-evidence 26 verification 38232034746 --repo OWNER/REPO --root .
python -m p_ases delivery parent-evidence 26 acceptance 38232034746 --repo OWNER/REPO --root .
~~~

## Failure handling and output

Handwritten PASS, stale run, wrong repository/SHA/App, skipped step, incomplete matrix, open child, mutated pointer, or wrong merge ancestry blocks. Report the exact child or Actions source and the failed identity field. Do not treat #32's open PR as parent acceptance.

Next owner: delivery-control aggregates final parent status. See the [integration design](../../docs/design/workflow-design.md) and [workflow specification](../../docs/specs/workflow-spec.md).
