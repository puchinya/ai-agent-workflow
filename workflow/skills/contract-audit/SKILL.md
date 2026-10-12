---
name: contract-audit
description: Check the final change against every approved contract requirement and invariant.
---
# Contract audit

## Owner and inputs

Owner: runtime/p_ases/audits.py. Inputs are the verified ADC, current PR HEAD, requirement and checklist identifiers, source diff, and evidence references.

## Workflow

1. Read the exact approved contract and verify its current pointer.
2. Compare each requirement and invariant against the final diff and exact-HEAD evidence.
3. Record PASS, FAIL, or UNTESTED with concrete source, test, or Actions references.
4. Treat missing approval, changed scope, unsafe paths, or stale evidence as blockers.
5. Keep the Bootstrap #32 review-procedure waiver scoped to its fixed implementation process; it does not change product runtime requirements.

## CLI

~~~sh
python -m p_ases audit self 32 42 HEAD40 path/to/plan.json path/to/self-audit.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

A requirement without evidence, unresolved contract violation, changed HEAD, unverified ADC, or invented PASS blocks the audit. Report each item, status, exact evidence, and remediation. An audit never authorizes merge or release.

Next owners: independent-review provides separate review; delivery-control checks readiness. See the [ADC specification](../../../docs/specs/workflow-spec.md).
