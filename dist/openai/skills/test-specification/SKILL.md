---
name: test-specification
description: Define independent Oracles and positive and negative test cases for approved requirements.
---
# Test specification

## Owner and inputs

Owner: workflow/standards/test-specification.md, workflow/templates/test-spec-template.md, and docs/testing/. Inputs are approved REQ and DES IDs, product outcomes, trust boundaries, platform requirements, and threat cases.

## Workflow

1. Write expected behavior from the requirement before inspecting the implementation result.
2. Define an Oracle with the exact input, observation, pass condition, fail condition, and evidence source.
3. Cover positive and negative cases, including stale subjects, changed pointers, missing authority, partial failure, and unsafe paths.
4. Map each test ID to one or more requirements and Oracles without using implementation details as the expected answer.
5. Keep OS and host-smoke-test coverage explicit. An unrun platform is unverified.

## CLI

~~~sh
python -m p_ases docs validate --root .
~~~

CI runs the independent specification, design, and test-oracle traceability validators. Document validation does not execute tests or claim their result.

## Failure handling and output

A missing independent Oracle, untraceable case, implementation-derived expectation, or unreported platform gap blocks a test plan. Output the test specification, case matrix, Oracle references, and unverified targets.

Next owner: verification-evidence freezes a plan from these sources. See the [test specification standard](../../standards/test-specification.md) and the [workflow specification](../../docs/specs/workflow-spec.md).
