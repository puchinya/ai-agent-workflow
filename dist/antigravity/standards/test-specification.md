# Test specification standard

A test specification owns test conditions, procedures, inputs, expected results, independent Oracles, and the evidence source that can demonstrate each result. It is not a second normative specification.

## Stable identifiers

- TST-AREA-NNN identifies a reproducible test condition and procedure.
- ORA-AREA-NNN identifies an expected result derived from an approved requirement, independently of the implementation being tested.
- Each test/Oracle pair links to one or more REQ and DES owners and to an executable evidence source.

## Test case fields

Record setup, action, expected result, failure boundaries, and evidence source. Manual or host-specific procedures state the environment and remain unverified until executed there. Tests that do not apply to a requirement state a technical reason and an alternative acceptance condition.

The traceability matrix in docs/testing/traceability.md provides a complete path REQ to DES to ORA/Test to Evidence. Do not describe an implementation detail as an Oracle.

## Related resources

Use the [test specification template](../templates/test-spec-template.md), [product specification standard](product-specification.md), and [technical design standard](technical-design.md).
