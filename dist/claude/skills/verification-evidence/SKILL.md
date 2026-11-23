---
name: verification-evidence
description: Freeze an exact-subject verification plan and record evidence from independent Oracles.
---
# Verification evidence

## Owner and inputs

Owner: runtime/p_ases/verification_plan.py, oracle_trace.py, verification.py, and evidence_store.py. Inputs are the approved ADC, specification and test-specification digests, independent Oracles, test cases, exact PR HEAD, and typed execution observations.

## Workflow

1. Freeze requirement, source, Oracle, and test identities before collecting results.
2. Require each normative requirement to map to a test and an independent Oracle.
3. Collect observations only for the exact repository, Issue, PR, HEAD, and Plan.
4. Re-evaluate final evidence after implementation changes. Empty plans and skipped checks remain non-passing.
5. Publish only the recomputed exact-subject result and read it back.
6. For a pre-User-Review, in-scope correction from verification, the distinct `issue verification-rework` operation requires `--plan` pointing to the current canonical frozen Plan and a failure artifact matching the repository, Issue, PR, ADC comment/digest, Plan SHA and HEAD. Never treat a failure from a different Plan as correction authority. Revalidate the Plan and normative source digests before label mutation or Applied recovery; after a new HEAD regenerate the entire required gate set.

## CLI

~~~sh
python -m p_ases verification plan 32 path/to/plan-input.json --repo OWNER/REPO --root .
python -m p_ases verification collect 32 42 HEAD40 path/to/plan.json path/to/observation.json --repo OWNER/REPO --root .
python -m p_ases verification validate 32 42 HEAD40 path/to/plan.json --repo OWNER/REPO --root .
python -m p_ases verification final 32 42 HEAD40 path/to/plan.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

A changed source digest, stale HEAD, missing case, skipped/neutral required check, fabricated observation, wrong App ID, incomplete Actions job/step, or failed command blocks PASS. Report exact status, subject digest, evidence references, and unverified platforms.

Next owner: acceptance-validation consumes final Verification. See the [Verification specification](../../docs/specs/runtime-spec.md).
