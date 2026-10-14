<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# Canonical Document Traceability Matrix

- Status: Approved for Issue #28
- Owning contract: https://github.com/puchinya/ai-agent-workflow/issues/28

<!-- contents:start -->
**Contents**
- [1 Test purpose](#1-test-purpose)
- [2 Test conditions and oracles](#2-test-conditions-and-oracles)
- [3 Artifact impact](#3-artifact-impact)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
<!-- heading-map:end -->


<a id="test-purpose"></a>
## 1 Test purpose

Provide a complete auditable link from every canonical requirement through its design and independent test Oracle to an executable evidence source.

The stable traceability IDs are retained across the P-ASES interface migration. Evidence links point to the current focused test modules; legacy behavior remains required only where the migrated P-ASES runtime still owns it.

<a id="test-conditions-and-oracles"></a>
## 2 Test conditions and oracles

A row is complete only when each linked stable ID resolves to its owning document and the evidence file exists.

| REQ | DES | Oracle | Test | Evidence |
|---|---|---|---|---|
| [REQ-WF-001](../specs/workflow-spec.md#req-wf-001) | [DES-WF-001](../design/workflow-design.md#des-wf-001) | [ORA-WF-001](workflow-tests.md#ora-wf-001) | [TST-WF-001](workflow-tests.md#tst-wf-001) | [test source](../../tests/test_issue_phases.py) |
| [REQ-WF-001](../specs/workflow-spec.md#req-wf-001) | [DES-WF-002](../design/workflow-design.md#des-wf-002) | [ORA-WF-009](workflow-tests.md#ora-wf-009) | [TST-WF-009](workflow-tests.md#tst-wf-009) | [phase evidence tests](../../tests/test_issue_phases.py), [phase advance CLI tests](../../tests/test_p_ases_cli.py) |
| [REQ-WF-002](../specs/workflow-spec.md#req-wf-002) | [DES-WF-003](../design/workflow-design.md#des-wf-003) | [ORA-WF-002](workflow-tests.md#ora-wf-002) | [TST-WF-002](workflow-tests.md#tst-wf-002) | [test source](../../tests/test_work_execution.py) |
| [REQ-WF-003](../specs/workflow-spec.md#req-wf-003) | [DES-WF-005](../design/workflow-design.md#des-wf-005) | [ORA-WF-003](workflow-tests.md#ora-wf-003) | [TST-WF-003](workflow-tests.md#tst-wf-003) | [test source](../../tests/test_pr_ensure.py) |
| [REQ-WF-004](../specs/workflow-spec.md#req-wf-004) | [DES-WF-001](../design/workflow-design.md#des-wf-001) | [ORA-WF-004](workflow-tests.md#ora-wf-004) | [TST-WF-004](workflow-tests.md#tst-wf-004) | [test source](../../tests/test_distribution.py) |
| [REQ-WF-005](../specs/workflow-spec.md#req-wf-005) | [DES-WF-005](../design/workflow-design.md#des-wf-005) | [ORA-WF-005](workflow-tests.md#ora-wf-005) | [TST-WF-005](workflow-tests.md#tst-wf-005) | [test source](../../tests/test_work_readiness.py) |
| [REQ-WF-006](../specs/workflow-spec.md#req-wf-006) | [DES-WF-002](../design/workflow-design.md#des-wf-002) | [ORA-WF-006](workflow-tests.md#ora-wf-006) | [TST-WF-006](workflow-tests.md#tst-wf-006) | [test source](../../tests/test_distribution.py) |
| [REQ-WF-007](../specs/workflow-spec.md#req-wf-007) | [DES-WF-004](../design/workflow-design.md#des-wf-004) | [ORA-WF-007](workflow-tests.md#ora-wf-007) | [TST-WF-007](workflow-tests.md#tst-wf-007) | [test source](../../tests/test_issue_phases.py) |
| [REQ-WF-008](../specs/workflow-spec.md#req-wf-008) | [DES-WF-004](../design/workflow-design.md#des-wf-004) | [ORA-WF-008](workflow-tests.md#ora-wf-008) | [TST-WF-008](workflow-tests.md#tst-wf-008) | [test source](../../tests/test_verification_security.py) |
| [REQ-WF-009](../specs/workflow-spec.md#req-wf-009) | [DES-WF-006](../design/workflow-design.md#des-wf-006) | [ORA-UR-001](pases-lifecycle-tests.md#ora-ur-001) | [TST-UR-001](pases-lifecycle-tests.md#tst-ur-001) | [test source](../../tests/test_user_review.py) |
| [REQ-WF-009](../specs/workflow-spec.md#req-wf-009) | [DES-WF-006](../design/workflow-design.md#des-wf-006) | [ORA-UR-002](pases-lifecycle-tests.md#ora-ur-002) | [TST-UR-002](pases-lifecycle-tests.md#tst-ur-002) | [test source](../../tests/test_github_user_review.py) |
| [REQ-WF-010](../specs/workflow-spec.md#req-wf-010) | [DES-WF-006](../design/workflow-design.md#des-wf-006) | [ORA-UR-003](pases-lifecycle-tests.md#ora-ur-003) | [TST-UR-003](pases-lifecycle-tests.md#tst-ur-003) | [test source](../../tests/test_parent_integration.py) |
| [REQ-WF-010](../specs/workflow-spec.md#req-wf-010) | [DES-WF-006](../design/workflow-design.md#des-wf-006) | [ORA-UR-004](pases-lifecycle-tests.md#ora-ur-004) | [TST-UR-004](pases-lifecycle-tests.md#tst-ur-004) | [test source](../../tests/test_final_delivery.py) |
| [REQ-WF-010](../specs/workflow-spec.md#req-wf-010) | [DES-WF-006](../design/workflow-design.md#des-wf-006) | [ORA-UR-005](pases-lifecycle-tests.md#ora-ur-005) | [TST-UR-005](pases-lifecycle-tests.md#tst-ur-005) | [test source](../../tests/test_parent_integration.py) |
| [REQ-RT-001](../specs/runtime-spec.md#req-rt-001) | [DES-RT-001](../design/runtime-design.md#des-rt-001) | [ORA-RT-001](runtime-tests.md#ora-rt-001) | [TST-RT-001](runtime-tests.md#tst-rt-001) | [test source](../../tests/test_cli_project_context.py) |
| [REQ-RT-001](../specs/runtime-spec.md#req-rt-001) | [DES-RT-001](../design/runtime-design.md#des-rt-001) | [ORA-RT-002](runtime-tests.md#ora-rt-002) | [TST-RT-002](runtime-tests.md#tst-rt-002) | [test source](../../tests/test_cli_project_context.py) |
| [REQ-RT-002](../specs/runtime-spec.md#req-rt-002) | [DES-RT-002](../design/runtime-design.md#des-rt-002) | [ORA-RT-003](runtime-tests.md#ora-rt-003) | [TST-RT-003](runtime-tests.md#tst-rt-003) | [test source](../../tests/test_docs_cli.py) |
| [REQ-RT-003](../specs/runtime-spec.md#req-rt-003) | [DES-RT-003](../design/runtime-design.md#des-rt-003) | [ORA-RT-004](runtime-tests.md#ora-rt-004) | [TST-RT-004](runtime-tests.md#tst-rt-004) | [test source](../../tests/test_work_execution.py) |
| [REQ-RT-004](../specs/runtime-spec.md#req-rt-004) | [DES-RT-003](../design/runtime-design.md#des-rt-003) | [ORA-RT-005](runtime-tests.md#ora-rt-005) | [TST-RT-005](runtime-tests.md#tst-rt-005) | [test source](../../tests/test_work_execution.py) |
| [REQ-RT-005](../specs/runtime-spec.md#req-rt-005) | [DES-RT-004](../design/runtime-design.md#des-rt-004) | [ORA-RT-006](runtime-tests.md#ora-rt-006) | [TST-RT-006](runtime-tests.md#tst-rt-006) | [test source](../../tests/test_work_execution.py) |
| [REQ-RT-006](../specs/runtime-spec.md#req-rt-006) | [DES-RT-005](../design/runtime-design.md#des-rt-005) | [ORA-RT-007](runtime-tests.md#ora-rt-007) | [TST-RT-007](runtime-tests.md#tst-rt-007) | [test source](../../tests/test_pr_ensure.py) |
| [REQ-RT-007](../specs/runtime-spec.md#req-rt-007) | [DES-RT-002](../design/runtime-design.md#des-rt-002) | [ORA-RT-008](runtime-tests.md#ora-rt-008) | [TST-RT-008](runtime-tests.md#tst-rt-008) | [test source](../../tests/test_adc_intake.py) |
| [REQ-RT-008](../specs/runtime-spec.md#req-rt-008) | [DES-RT-002](../design/runtime-design.md#des-rt-002) | [ORA-RT-009](runtime-tests.md#ora-rt-009) | [TST-RT-009](runtime-tests.md#tst-rt-009) | [test source](../../tests/test_work_readiness.py) |
| [REQ-RT-008](../specs/runtime-spec.md#req-rt-008) | [DES-RT-005](../design/runtime-design.md#des-rt-005) | [ORA-RT-010](runtime-tests.md#ora-rt-010) | [TST-RT-010](runtime-tests.md#tst-rt-010) | [test source](../../tests/test_work_readiness.py) |
| [REQ-RT-009](../specs/runtime-spec.md#req-rt-009) | [DES-RT-006](../design/runtime-design.md#des-rt-006) | [ORA-RT-011](runtime-tests.md#ora-rt-011) | [TST-RT-011](runtime-tests.md#tst-rt-011) | [test source](../../tests/test_bootstrap_cli_security.py) |
| [REQ-RT-010](../specs/runtime-spec.md#req-rt-010) | [DES-RT-001](../design/runtime-design.md#des-rt-001) | [ORA-RT-012](runtime-tests.md#ora-rt-012) | [TST-RT-012](runtime-tests.md#tst-rt-012) | [test source](../../tests/test_p_ases_cli.py) |
| [REQ-RT-011](../specs/runtime-spec.md#req-rt-011) | [DES-RT-001](../design/runtime-design.md#des-rt-001) | [ORA-RT-013](runtime-tests.md#ora-rt-013) | [TST-RT-013](runtime-tests.md#tst-rt-013) | [test source](../../tests/test_verification_plan.py) |
| [REQ-RT-012](../specs/runtime-spec.md#req-rt-012) | [DES-RT-006](../design/runtime-design.md#des-rt-006) | [ORA-RT-014](runtime-tests.md#ora-rt-014) | [TST-RT-014](runtime-tests.md#tst-rt-014) | [test source](../../tests/test_verification_security.py) |
| [REQ-RT-013](../specs/runtime-spec.md#req-rt-013) | [DES-RT-006](../design/runtime-design.md#des-rt-006) | [ORA-RT-015](runtime-tests.md#ora-rt-015) | [TST-RT-015](runtime-tests.md#tst-rt-015) | [test source](../../tests/test_bootstrap_cli_security.py) |
| [REQ-DIST-001](../specs/distribution-spec.md#req-dist-001) | [DES-DIST-003](../design/distribution-design.md#des-dist-003) | [ORA-DIST-001](distribution-tests.md#ora-dist-001) | [TST-DIST-001](distribution-tests.md#tst-dist-001) | [test source](../../tests/test_distribution.py) |
| [REQ-DIST-002](../specs/distribution-spec.md#req-dist-002) | [DES-DIST-003](../design/distribution-design.md#des-dist-003) | [ORA-DIST-002](distribution-tests.md#ora-dist-002) | [TST-DIST-002](distribution-tests.md#tst-dist-002) | [test source](../../tests/test_distribution.py) |
| [REQ-DIST-003](../specs/distribution-spec.md#req-dist-003) | [DES-DIST-003](../design/distribution-design.md#des-dist-003) | [ORA-DIST-003](distribution-tests.md#ora-dist-003) | [TST-DIST-003](distribution-tests.md#tst-dist-003) | [test source](../../tests/test_distribution.py) |
| [REQ-DIST-004](../specs/distribution-spec.md#req-dist-004) | [DES-DIST-002](../design/distribution-design.md#des-dist-002) | [ORA-DIST-004](distribution-tests.md#ora-dist-004) | [TST-DIST-004](distribution-tests.md#tst-dist-004) | [test source](../../tests/test_distribution.py) |
| [REQ-DIST-005](../specs/distribution-spec.md#req-dist-005) | [DES-DIST-004](../design/distribution-design.md#des-dist-004) | [ORA-DIST-005](distribution-tests.md#ora-dist-005) | [TST-DIST-005](distribution-tests.md#tst-dist-005) | [test source](../../tests/test_distribution.py) |
| [REQ-DIST-006](../specs/distribution-spec.md#req-dist-006) | [DES-DIST-001](../design/distribution-design.md#des-dist-001) | [ORA-DIST-006](distribution-tests.md#ora-dist-006) | [TST-DIST-006](distribution-tests.md#tst-dist-006) | [test source](../../tests/test_distribution.py) |
| [REQ-DIST-007](../specs/distribution-spec.md#req-dist-007) | [DES-DIST-005](../design/distribution-design.md#des-dist-005) | [ORA-DIST-007](distribution-tests.md#ora-dist-007) | [TST-DIST-007](distribution-tests.md#tst-dist-007) | [test source](../../tests/test_distribution.py) |
| [REQ-DIST-008](../specs/distribution-spec.md#req-dist-008) | [DES-DIST-005](../design/distribution-design.md#des-dist-005) | [ORA-DIST-008](distribution-tests.md#ora-dist-008) | [TST-DIST-008](distribution-tests.md#tst-dist-008) | [test source](../../tests/test_distribution.py) |
| [REQ-DOC-001](../specs/documentation-tooling-spec.md#req-doc-001) | [DES-DOC-001](../design/documentation-tooling-design.md#des-doc-001) | [ORA-DOC-001](documentation-tests.md#ora-doc-001) | [TST-DOC-001](documentation-tests.md#tst-doc-001) | [test source](../../tests/test_documents.py) |
| [REQ-DOC-002](../specs/documentation-tooling-spec.md#req-doc-002) | [DES-DOC-004](../design/documentation-tooling-design.md#des-doc-004) | [ORA-DOC-002](documentation-tests.md#ora-doc-002) | [TST-DOC-002](documentation-tests.md#tst-doc-002) | [test source](../../tests/test_documents.py) |
| [REQ-DOC-003](../specs/documentation-tooling-spec.md#req-doc-003) | [DES-DOC-002](../design/documentation-tooling-design.md#des-doc-002) | [ORA-DOC-003](documentation-tests.md#ora-doc-003) | [TST-DOC-003](documentation-tests.md#tst-doc-003) | [test source](../../tests/test_document_format.py) |
| [REQ-DOC-004](../specs/documentation-tooling-spec.md#req-doc-004) | [DES-DOC-002](../design/documentation-tooling-design.md#des-doc-002) | [ORA-DOC-004](documentation-tests.md#ora-doc-004) | [TST-DOC-004](documentation-tests.md#tst-doc-004) | [test source](../../tests/test_document_format.py) |
| [REQ-DOC-005](../specs/documentation-tooling-spec.md#req-doc-005) | [DES-DOC-003](../design/documentation-tooling-design.md#des-doc-003) | [ORA-DOC-005](documentation-tests.md#ora-doc-005) | [TST-DOC-005](documentation-tests.md#tst-doc-005) | [test source](../../tests/test_document_format.py) |
| [REQ-DOC-006](../specs/documentation-tooling-spec.md#req-doc-006) | [DES-DOC-003](../design/documentation-tooling-design.md#des-doc-003) | [ORA-DOC-006](documentation-tests.md#ora-doc-006) | [TST-DOC-006](documentation-tests.md#tst-doc-006) | [test source](../../tests/test_document_format.py) |
| [REQ-DOC-007](../specs/documentation-tooling-spec.md#req-doc-007) | [DES-DOC-005](../design/documentation-tooling-design.md#des-doc-005) | [ORA-DOC-007](documentation-tests.md#ora-doc-007) | [TST-DOC-007](documentation-tests.md#tst-doc-007) | [test source](../../tests/test_docs_cli.py) |

<a id="artifact-impact"></a>
## 3 Artifact impact

- Specification: updated existing workflow/runtime/distribution specs and created the documentation-tooling specification.
- Design: updated existing workflow/runtime/distribution designs and created the documentation-tooling design.
- Testing: created workflow/runtime/distribution/documentation test specifications and the traceability matrix.
- Status: evidence-only — verification results are recorded on Issue #28 and its PR.
