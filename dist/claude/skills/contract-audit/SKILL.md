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
6. After self-review passes, hand off to a dedicated fresh host-native subagent for Independent Review. The host spawns and joins it and provides the actual spawn/session ID, reviewer ID, and implementation binding ID. The child must read the full approved Contract, checklist, exact PR/HEAD, full diff, and test evidence, then author its own raw findings/result. The implementation context cannot author, edit, or replace that result.

## CLI

~~~sh
python -m p_ases audit self 32 42 HEAD40 path/to/plan.json path/to/self-audit.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

A requirement without evidence, unresolved contract violation, changed HEAD, unverified ADC, unavailable native subagent, unknown spawn/join outcome, missing host provenance, or invented PASS blocks the audit. Report each item, status, exact evidence, and remediation. A/B findings, blocking C findings, and checklist failures block Readiness and User Review. After fixes that change HEAD, run a new child review; do not retry without progress on the same HEAD. The parent may ingest the child's unedited artifact through the existing `audit independent` route, but context-ID distinctness is not proof of host authenticity. Do not add a runtime spawn API or shell out to an agent executable. An audit never authorizes merge or release.

Next owners: independent-review provides separate review; delivery-control checks readiness. See the [ADC specification](../../docs/specs/workflow-spec.md).
