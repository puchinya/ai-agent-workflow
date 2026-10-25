<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# P-ASES Human Review and Integration Test Specification

- Status: Approved for Issues #31 and #42
- Owning specification: ../specs/workflow-spec.md

<!-- contents:start -->
**Contents**
- [1 Test purpose](#1-test-purpose)
- [2 Test conditions and oracles](#2-test-conditions-and-oracles)
  - [2.1 TST-UR-001 User Review identity and exact subject](#21-tst-ur-001-user-review-identity-and-exact-subject)
    - [2.1.1 ORA-UR-001 Expected result](#211-ora-ur-001-expected-result)
  - [2.2 TST-UR-002 Feedback loops and host provenance](#22-tst-ur-002-feedback-loops-and-host-provenance)
    - [2.2.1 ORA-UR-002 Expected result](#221-ora-ur-002-expected-result)
  - [2.3 TST-UR-003 Parent Integration evidence](#23-tst-ur-003-parent-integration-evidence)
    - [2.3.1 ORA-UR-003 Expected result](#231-ora-ur-003-expected-result)
  - [2.4 TST-UR-004 Final Delivery separation](#24-tst-ur-004-final-delivery-separation)
    - [2.4.1 ORA-UR-004 Expected result](#241-ora-ur-004-expected-result)
  - [2.5 TST-UR-005 Parent User Review](#25-tst-ur-005-parent-user-review)
    - [2.5.1 ORA-UR-005 Expected result](#251-ora-ur-005-expected-result)
  - [2.6 TST-UR-006 Parent Activation provenance and comment history](#26-tst-ur-006-parent-activation-provenance-and-comment-history)
    - [2.6.1 ORA-UR-006 Expected result](#261-ora-ur-006-expected-result)
  - [2.7 TST-F01-001 Fixed migration and consumer routing separation](#27-tst-f01-001-fixed-migration-and-consumer-routing-separation)
    - [2.7.1 ORA-F01-001 Expected result](#271-ora-f01-001-expected-result)
  - [2.8 TST-F01-002 Automatic Activation setup](#28-tst-f01-002-automatic-activation-setup)
    - [2.8.1 ORA-F01-002 Expected result](#281-ora-f01-002-expected-result)
  - [2.9 TST-F01-003 Immutable Activation evidence](#29-tst-f01-003-immutable-activation-evidence)
    - [2.9.1 ORA-F01-003 Expected result](#291-ora-f01-003-expected-result)
  - [2.10 TST-F01-004 Prompt and approval boundary](#210-tst-f01-004-prompt-and-approval-boundary)
    - [2.10.1 ORA-F01-004 Expected result](#2101-ora-f01-004-expected-result)
  - [2.11 TST-F01-005 Strict new-Issue timing](#211-tst-f01-005-strict-new-issue-timing)
    - [2.11.1 ORA-F01-005 Expected result](#2111-ora-f01-005-expected-result)
  - [2.12 TST-F01-006 Historical pin preservation](#212-tst-f01-006-historical-pin-preservation)
    - [2.12.1 ORA-F01-006 Expected result](#2121-ora-f01-006-expected-result)
  - [2.13 TST-F01-007 Successor/reapproval](#213-tst-f01-007-successorreapproval)
    - [2.13.1 ORA-F01-007 Expected result](#2131-ora-f01-007-expected-result)
  - [2.14 TST-F07-001 Legacy Gate is prospective and typed](#214-tst-f07-001-legacy-gate-is-prospective-and-typed)
    - [2.14.1 ORA-F07-001 Expected result](#2141-ora-f07-001-expected-result)
  - [2.15 TST-F07-002 Exact bootstrap authorization](#215-tst-f07-002-exact-bootstrap-authorization)
    - [2.15.1 ORA-F07-002 Expected result](#2151-ora-f07-002-expected-result)
  - [2.16 TST-F07-003 Exact Adoption plan and Owner UI grant](#216-tst-f07-003-exact-adoption-plan-and-owner-ui-grant)
    - [2.16.1 ORA-F07-003 Expected result](#2161-ora-f07-003-expected-result)
  - [2.17 TST-F07-004 Append-only Adoption, Gate, and recovery](#217-tst-f07-004-append-only-adoption-gate-and-recovery)
    - [2.17.1 ORA-F07-004 Expected result](#2171-ora-f07-004-expected-result)
  - [2.18 TST-F07-005 Reset and resume normal governance](#218-tst-f07-005-reset-and-resume-normal-governance)
    - [2.18.1 ORA-F07-005 Expected result](#2181-ora-f07-005-expected-result)
  - [2.19 TST-F06-001 Independent Review V2 and V1 compatibility](#219-tst-f06-001-independent-review-v2-and-v1-compatibility)
    - [2.19.1 ORA-F06-001 Expected result](#2191-ora-f06-001-expected-result)
  - [2.20 TST-F06-002 Host-verified provenance](#220-tst-f06-002-host-verified-provenance)
    - [2.20.1 ORA-F06-002 Expected result](#2201-ora-f06-002-expected-result)
  - [2.21 TST-F06-003 Native attested result](#221-tst-f06-003-native-attested-result)
    - [2.21.1 ORA-F06-003 Expected result](#2211-ora-f06-003-expected-result)
  - [2.22 TST-F06-004 Canonical identity, freshness, and replay](#222-tst-f06-004-canonical-identity-freshness-and-replay)
    - [2.22.1 ORA-F06-004 Expected result](#2221-ora-f06-004-expected-result)
  - [2.23 TST-F06-005 Committed minimum assurance](#223-tst-f06-005-committed-minimum-assurance)
    - [2.23.1 ORA-F06-005 Expected result](#2231-ora-f06-005-expected-result)
  - [2.24 TST-F06-006 Readiness and downstream enforcement](#224-tst-f06-006-readiness-and-downstream-enforcement)
    - [2.24.1 ORA-F06-006 Expected result](#2241-ora-f06-006-expected-result)
  - [2.25 TST-F06-007 Host-specific adapters](#225-tst-f06-007-host-specific-adapters)
    - [2.25.1 ORA-F06-007 Expected result](#2251-ora-f06-007-expected-result)
  - [2.26 TST-F06-008 Capability documentation and package distributions](#226-tst-f06-008-capability-documentation-and-package-distributions)
    - [2.26.1 ORA-F06-008 Expected result](#2261-ora-f06-008-expected-result)
  - [2.27 TST-F06-009 Issue #63 / PR #64 isolation](#227-tst-f06-009-issue-63-pr-64-isolation)
    - [2.27.1 ORA-F06-009 Expected result](#2271-ora-f06-009-expected-result)
  - [2.28 TST-F06-010 Explicit opt-in and typed capture-unavailability eligibility](#228-tst-f06-010-explicit-opt-in-and-typed-capture-unavailability-eligibility)
    - [2.28.1 ORA-F06-010 Expected result](#2281-ora-f06-010-expected-result)
  - [2.29 TST-F06-011 Exact exception plan, Owner grant, and append-only record](#229-tst-f06-011-exact-exception-plan-owner-grant-and-append-only-record)
    - [2.29.1 ORA-F06-011 Expected result](#2291-ora-f06-011-expected-result)
  - [2.30 TST-F06-012 Versioned Readiness and Final Delivery compatibility](#230-tst-f06-012-versioned-readiness-and-final-delivery-compatibility)
    - [2.30.1 ORA-F06-012 Expected result](#2301-ora-f06-012-expected-result)
  - [2.31 TST-F06-013 User Review and downstream exact-subject revalidation](#231-tst-f06-013-user-review-and-downstream-exact-subject-revalidation)
    - [2.31.1 ORA-F06-013 Expected result](#2311-ora-f06-013-expected-result)
  - [2.32 TST-F06-014 Review occurrence with unavailable host provenance](#232-tst-f06-014-review-occurrence-with-unavailable-host-provenance)
    - [2.32.1 ORA-F06-014 Expected result](#2321-ora-f06-014-expected-result)
  - [2.33 TST-F06-015 ADC-authorized one-time Requirements Rebaseline](#233-tst-f06-015-adc-authorized-one-time-requirements-rebaseline)
    - [2.33.1 ORA-F06-015 Expected result](#2331-ora-f06-015-expected-result)
  - [2.34 TST-F06-016 Active-chat approval and technical evidence](#234-tst-f06-016-active-chat-approval-and-technical-evidence)
    - [2.34.1 ORA-F06-016 Expected result](#2341-ora-f06-016-expected-result)
  - [2.35 TST-F06-017 Operator-reported provenance and history](#235-tst-f06-017-operator-reported-provenance-and-history)
    - [2.35.1 ORA-F06-017 Expected result](#2351-ora-f06-017-expected-result)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [TST-UR-001](#tst-ur-001) — 2.1 TST-UR-001 User Review identity and exact subject
- [ORA-UR-001](#ora-ur-001) — 2.1.1 ORA-UR-001 Expected result
- [TST-UR-002](#tst-ur-002) — 2.2 TST-UR-002 Feedback loops and host provenance
- [ORA-UR-002](#ora-ur-002) — 2.2.1 ORA-UR-002 Expected result
- [TST-UR-003](#tst-ur-003) — 2.3 TST-UR-003 Parent Integration evidence
- [ORA-UR-003](#ora-ur-003) — 2.3.1 ORA-UR-003 Expected result
- [TST-UR-004](#tst-ur-004) — 2.4 TST-UR-004 Final Delivery separation
- [ORA-UR-004](#ora-ur-004) — 2.4.1 ORA-UR-004 Expected result
- [TST-UR-005](#tst-ur-005) — 2.5 TST-UR-005 Parent User Review
- [ORA-UR-005](#ora-ur-005) — 2.5.1 ORA-UR-005 Expected result
- [TST-UR-006](#tst-ur-006) — 2.6 TST-UR-006 Parent Activation provenance and comment history
- [ORA-UR-006](#ora-ur-006) — 2.6.1 ORA-UR-006 Expected result
- [TST-F01-001](#tst-f01-001) — 2.7 TST-F01-001 Fixed migration and consumer routing separation
- [ORA-F01-001](#ora-f01-001) — 2.7.1 ORA-F01-001 Expected result
- [TST-F01-002](#tst-f01-002) — 2.8 TST-F01-002 Automatic Activation setup
- [ORA-F01-002](#ora-f01-002) — 2.8.1 ORA-F01-002 Expected result
- [TST-F01-003](#tst-f01-003) — 2.9 TST-F01-003 Immutable Activation evidence
- [ORA-F01-003](#ora-f01-003) — 2.9.1 ORA-F01-003 Expected result
- [TST-F01-004](#tst-f01-004) — 2.10 TST-F01-004 Prompt and approval boundary
- [ORA-F01-004](#ora-f01-004) — 2.10.1 ORA-F01-004 Expected result
- [TST-F01-005](#tst-f01-005) — 2.11 TST-F01-005 Strict new-Issue timing
- [ORA-F01-005](#ora-f01-005) — 2.11.1 ORA-F01-005 Expected result
- [TST-F01-006](#tst-f01-006) — 2.12 TST-F01-006 Historical pin preservation
- [ORA-F01-006](#ora-f01-006) — 2.12.1 ORA-F01-006 Expected result
- [TST-F01-007](#tst-f01-007) — 2.13 TST-F01-007 Successor/reapproval
- [ORA-F01-007](#ora-f01-007) — 2.13.1 ORA-F01-007 Expected result
- [TST-F07-001](#tst-f07-001) — 2.14 TST-F07-001 Legacy Gate is prospective and typed
- [ORA-F07-001](#ora-f07-001) — 2.14.1 ORA-F07-001 Expected result
- [TST-F07-002](#tst-f07-002) — 2.15 TST-F07-002 Exact bootstrap authorization
- [ORA-F07-002](#ora-f07-002) — 2.15.1 ORA-F07-002 Expected result
- [TST-F07-003](#tst-f07-003) — 2.16 TST-F07-003 Exact Adoption plan and Owner UI grant
- [ORA-F07-003](#ora-f07-003) — 2.16.1 ORA-F07-003 Expected result
- [TST-F07-004](#tst-f07-004) — 2.17 TST-F07-004 Append-only Adoption, Gate, and recovery
- [ORA-F07-004](#ora-f07-004) — 2.17.1 ORA-F07-004 Expected result
- [TST-F07-005](#tst-f07-005) — 2.18 TST-F07-005 Reset and resume normal governance
- [ORA-F07-005](#ora-f07-005) — 2.18.1 ORA-F07-005 Expected result
- [TST-F06-001](#tst-f06-001) — 2.19 TST-F06-001 Independent Review V2 and V1 compatibility
- [ORA-F06-001](#ora-f06-001) — 2.19.1 ORA-F06-001 Expected result
- [TST-F06-002](#tst-f06-002) — 2.20 TST-F06-002 Host-verified provenance
- [ORA-F06-002](#ora-f06-002) — 2.20.1 ORA-F06-002 Expected result
- [TST-F06-003](#tst-f06-003) — 2.21 TST-F06-003 Native attested result
- [ORA-F06-003](#ora-f06-003) — 2.21.1 ORA-F06-003 Expected result
- [TST-F06-004](#tst-f06-004) — 2.22 TST-F06-004 Canonical identity, freshness, and replay
- [ORA-F06-004](#ora-f06-004) — 2.22.1 ORA-F06-004 Expected result
- [TST-F06-005](#tst-f06-005) — 2.23 TST-F06-005 Committed minimum assurance
- [ORA-F06-005](#ora-f06-005) — 2.23.1 ORA-F06-005 Expected result
- [TST-F06-006](#tst-f06-006) — 2.24 TST-F06-006 Readiness and downstream enforcement
- [ORA-F06-006](#ora-f06-006) — 2.24.1 ORA-F06-006 Expected result
- [TST-F06-007](#tst-f06-007) — 2.25 TST-F06-007 Host-specific adapters
- [ORA-F06-007](#ora-f06-007) — 2.25.1 ORA-F06-007 Expected result
- [TST-F06-008](#tst-f06-008) — 2.26 TST-F06-008 Capability documentation and package distributions
- [ORA-F06-008](#ora-f06-008) — 2.26.1 ORA-F06-008 Expected result
- [TST-F06-009](#tst-f06-009) — 2.27 TST-F06-009 Issue #63 / PR #64 isolation
- [ORA-F06-009](#ora-f06-009) — 2.27.1 ORA-F06-009 Expected result
- [TST-F06-010](#tst-f06-010) — 2.28 TST-F06-010 Explicit opt-in and typed capture-unavailability eligibility
- [ORA-F06-010](#ora-f06-010) — 2.28.1 ORA-F06-010 Expected result
- [TST-F06-011](#tst-f06-011) — 2.29 TST-F06-011 Exact exception plan, Owner grant, and append-only record
- [ORA-F06-011](#ora-f06-011) — 2.29.1 ORA-F06-011 Expected result
- [TST-F06-012](#tst-f06-012) — 2.30 TST-F06-012 Versioned Readiness and Final Delivery compatibility
- [ORA-F06-012](#ora-f06-012) — 2.30.1 ORA-F06-012 Expected result
- [TST-F06-013](#tst-f06-013) — 2.31 TST-F06-013 User Review and downstream exact-subject revalidation
- [ORA-F06-013](#ora-f06-013) — 2.31.1 ORA-F06-013 Expected result
- [TST-F06-014](#tst-f06-014) — 2.32 TST-F06-014 Review occurrence with unavailable host provenance
- [ORA-F06-014](#ora-f06-014) — 2.32.1 ORA-F06-014 Expected result
- [TST-F06-015](#tst-f06-015) — 2.33 TST-F06-015 ADC-authorized one-time Requirements Rebaseline
- [ORA-F06-015](#ora-f06-015) — 2.33.1 ORA-F06-015 Expected result
- [TST-F06-016](#tst-f06-016) — 2.34 TST-F06-016 Active-chat approval and technical evidence
- [ORA-F06-016](#ora-f06-016) — 2.34.1 ORA-F06-016 Expected result
- [TST-F06-017](#tst-f06-017) — 2.35 TST-F06-017 Operator-reported provenance and history
- [ORA-F06-017](#ora-f06-017) — 2.35.1 ORA-F06-017 Expected result
<!-- heading-map:end -->


<a id="test-purpose"></a>
## 1 Test purpose

Verify human User Review, child Integration, and final merge gates as independent exact-subject records. The normal child phase evidence and initial kind/phase labels are covered by [TST-WF-009](workflow-tests.md#tst-wf-009); these parent migration tests continue to exercise the fixed #26–#32 exception boundary.

<a id="test-conditions-and-oracles"></a>
## 2 Test conditions and oracles

<a id="tst-ur-001"></a>
<a id="tst-ur-001-user-review-identity-and-exact-subject"></a>
### 2.1 TST-UR-001 User Review identity and exact subject

**Setup and action:** Submit current and stale approvals from human, bot, and unrelated accounts; change HEAD, ADC, Readiness, feedback, and review-thread resolution between reads. Drive the CLI through `start → sync → status` with `session.json` present in the snapshot directory. Then alter a correctly named snapshot without changing its SHA filename and add an unknown JSON filename.

<a id="ora-ur-001"></a>
<a id="ora-ur-001-expected-result"></a>
#### 2.1.1 ORA-UR-001 Expected result

Only a current human approval on the exact subject passes. Edits, deletions, stale state, incomplete pagination, or unresolved threads invalidate approval. Without approval the three-step CLI sequence reaches PENDING; a valid filename with modified bytes or an unexpected JSON filename fails closed.

<a id="tst-ur-002"></a>
<a id="tst-ur-002-feedback-loops-and-host-provenance"></a>
### 2.2 TST-UR-002 Feedback loops and host provenance

**Setup and action:** Exercise all four GitHub feedback surfaces, repeated/edited/deleted events, direct host approval, a quoted message, an attachment, and an unverified CLI JSON event. For PR conversation and diff comments, test the exact two-line `P-ASES-DECISION: CHANGES_REQUESTED` plus `P-ASES-HEAD: <SHA-40>` body, current versus stale HEAD, inline `commit_id` match, authorized versus unrelated human, bot, quote, malformed syntax, and ordinary natural-language requests.

<a id="ora-ur-002"></a>
<a id="ora-ur-002-expected-result"></a>
#### 2.2.1 ORA-UR-002 Expected result

Only a current authorized human's exact, unquoted, whole-body decision on the current HEAD returns the same Issue/PR to execution. Inline `commit_id` must match. Bot, unauthorized, stale, quoted, malformed, and natural-language comments do not trigger the transition. Host events require verified current-user provenance; questions and unresolved threads do not approve.

<a id="tst-ur-003"></a>
<a id="tst-ur-003-parent-integration-evidence"></a>
### 2.3 TST-UR-003 Parent Integration evidence

**Setup and action:** Remove, duplicate, open, fork, unmerged, out-of-main, and cyclic child records; invert a dependency merge timestamp; alter a merge SHA; omit or stale typed Verification/Acceptance evidence; and submit an arbitrary local PASS JSON with fabricated artifact bytes. Create a real temporary Git commit and bind its actual HEAD SHA to fake GitHub Actions run/job/step/Check Run API records. Test CI push-run selection, latest run/attempt, exact `main` SHA/repository/workflow path, all four matrix jobs, App ID `15368`, job Check Run URL binding, exact step conclusions, the manual parent-acceptance workflow, and missing/failed/skipped steps. Confirm the verifier reconstructs the evidence comment from API data and rejects a caller payload even when all fabricated SHA-256 values are internally consistent. Test double read by exact comment ID, edit timestamp/body, deletion, wrong author, wrong repository/Issue, wrong main/ADC, duplicate same-run comments, changed bytes, stale/superseded runs, and wrong App ID. Vary volatile avatar/profile URLs and login casing across direct, list, and second-direct reads; the same ID/type and case-insensitive login must pass, while a different normalized login or immutable comment/actor field blocks. Require author and authenticated-user IDs to be positive integers (excluding booleans); missing, zero, negative, and boolean IDs block. Exercise the publisher's `REUSED` path with those avatar variants, asserting no additional POST and blocking an authenticated-author mismatch. Exercise the public `issue integration-check` route with fixture GitHub endpoints while leaving `_read_parent_integration` unmocked; assert PASS with both exact comment IDs and BLOCKED when `main` advances but the comments remain bound to the old SHA. For legacy #26 labels, preflight current `[enhancement]`, apply once, retry idempotently, conflict with an existing phase, and simulate an API response loss after a partial label write. For the parent ADC, omit a pointer and verify the evaluator uses only the current approved child #31 ADC's unique pinned parent-contract declaration; reject duplicate declarations, a different source path/commit, an unapproved child pointer, or an unavailable pinned source.

<a id="ora-ur-003"></a>
<a id="ora-ur-003-expected-result"></a>
#### 2.3.1 ORA-UR-003 Expected result

Integration passes only for the frozen native child set, exact dependency DAG, closed Issues, one merged same-repository PR per child, main ancestry, and current-main evidence reconstructed from trusted exact-SHA GitHub Actions run/job/step/Check Run API records. An authenticated exact-ID Issue #26 comment stores the derived bytes and run identity outside the named commit; comment edits/deletion, arbitrary local PASS data, wrong App, failed or skipped steps, stale SHA, or superseded run fail closed. Volatile avatar/profile URL differences and login casing alone do not change the authenticated author identity; author and authenticated-user IDs must be positive non-boolean integers, and missing, zero, negative, or boolean IDs fail closed. A different normalized login, author type, or immutable comment field also blocks. The publisher reuses an exact existing subject without POSTing another comment. The actual `issue integration-check` route reads both comments and the native graph through `_read_parent_integration`; it passes only for current-SHA evidence and blocks old-SHA comments after `main` advances. The real-commit test demonstrates the main SHA is not embedded in that commit's own tree.

<a id="tst-ur-004"></a>
<a id="tst-ur-004-final-delivery-separation"></a>
### 2.4 TST-UR-004 Final Delivery separation

**Setup and action:** Vary User Review, GitHub formal review, Required Checks, branch protection, mergeability, and explicit merge authorization independently.

<a id="ora-ur-004"></a>
<a id="ora-ur-004-expected-result"></a>
#### 2.4.1 ORA-UR-004 Expected result

Each gate must be checked separately. Final Delivery never authorizes or performs merge, release, Issue closure, or parent activation.

<a id="tst-ur-005"></a>
<a id="tst-ur-005-parent-user-review"></a>
### 2.5 TST-UR-005 Parent User Review

**Setup and action:** With parent Integration blocked, verify no parent review session starts and `phase:user-review` is not set. With a passing fixed Integration subject, verify the parent phase moves from `integration` to `user-review`, an immutable session binds the parent ADC, six child/merge pairs, and Integration digest, and the first invocation returns pending. Then vary exact parent Issue decision subject, actor identity/type, session timestamp, comment edit/deletion, ADC digest, child merge SHA, and Integration digest. Confirm an exact current human approval is recognized, while approval never sets merge authorization or activation.

<a id="ora-ur-005"></a>
<a id="ora-ur-005-expected-result"></a>
#### 2.5.1 ORA-UR-005 Expected result

Parent User Review starts only after exact Integration PASS. Only a new whole-body `P-ASES-DECISION: APPROVED` plus `P-ASES-SUBJECT: <SHA-256>` parent Issue comment from the authenticated human can approve. Stale, edited, deleted, incomplete, or changed-subject decisions fail closed. Approval leaves parent close, activation, merge, and release as separate gates.

<a id="tst-ur-006"></a>
<a id="tst-ur-006-parent-activation-provenance-and-comment-history"></a>
### 2.6 TST-UR-006 Parent Activation provenance and comment history

**Setup and action:** Build a fixed #26 Activation fixture with six closed child Issues, six merged same-repository PRs, the V1 integration envelope, V2 Verification and Acceptance comments, Actions runs/jobs/steps/Check Runs, an owner approval, and an Activation record. Verify a valid fixture passes after reconstructing both typed V2 comments from GitHub APIs. Then independently vary each V1 PASS flag, digest, HTTPS ref, comment ID, run ID, parent ADC, activation SHA, child merge SHA, Actions App ID, workflow/job/step/check identity, and run status; include nonexistent Actions references and self-asserted PASS with fabricated matching hashes. Add missing, duplicated, edited, deleted, wrong-Issue, wrong-URL, wrong-ID, wrong-owner-ID/login/type, and timestamp-edited approval, Activation, V1 integration, and V2 evidence comments. Change a target comment between direct/list/direct reads. Vary avatar/profile URLs and login casing without changing stable author identity. For historical evidence, issue on successful run R/attempt 1, advance main to a descendant, add failed or successful attempt 2 and a newer run, then verify Activation still reconstructs R/attempt 1 using the attempt-specific run/jobs APIs and exact Check Run IDs. Reject if that attempt is unavailable, its run metadata differs, or any pinned job, step, App, SHA, or Check Run changed; new evidence issuance must reject superseded attempts/runs. Finally advance current main to a descendant commit after successful Activation and verify the original Activation remains valid; move the Activation commit off main and verify it blocks.

<a id="ora-ur-006"></a>
<a id="ora-ur-006-expected-result"></a>
#### 2.6.1 ORA-UR-006 Expected result

Activation passes only when the complete exact-SHA Verification and Acceptance evidence is reconstructed from trusted GitHub Actions API records (App ID 15368), the approved parent ADC and all six real child merge SHAs match, and current main contains the activation commit. New evidence issuance requires the latest successful matching run and attempt. Historical Activation validation pins the run ID/attempt recorded in each V2 comment and rebuilds that attempt using GitHub's attempt-specific run and jobs APIs; a newer run/attempt does not invalidate it. A missing/unavailable historical attempt, changed run metadata, or altered job/step/Check Run must block without fallback to comment PASS fields or cache. Caller PASS flags, digests, or URLs alone never establish Activation. Approval, Activation, and referenced evidence comments pass only when each is unique and direct/list/direct identity matches across ID, exact body, `created_at == updated_at`, Issue/HTML/API URLs, and stable owner User ID/login/type. Edited, deleted, duplicated, misattributed, misbound, or changing records and any API failure block. Avatar/profile-only differences and login casing are tolerated. Advancing main preserves a valid historical activation as long as its commit remains on main.

<a id="tst-f01-001"></a>
<a id="tst-f01-001-fixed-migration-and-consumer-routing-separation"></a>
### 2.7 TST-F01-001 Fixed migration and consumer routing separation

**Setup and action:** Keep the existing #26–#32 fixed-cohort fixtures. Route ordinary Issue #27 in a distinct owner/repository through consumer Activation. Vary repository case, missing locator, wrong repository URL, PR resource, pre-Activation creation time, and a same-number Issue in a different repository.

<a id="ora-f01-001"></a>
<a id="ora-f01-001-expected-result"></a>
#### 2.7.1 ORA-F01-001 Expected result

Only exact P-ASES repository/cohort pairs use migration Bootstrap. A consumer Issue numbered #27 has no migration authority; it receives a consumer Gate Selection only when its repository-specific Activation record is valid and its creation time is later.

<a id="tst-f01-002"></a>
<a id="tst-f01-002-automatic-activation-setup"></a>
### 2.8 TST-F01-002 Automatic Activation setup

**Setup and action:** Run setup with no profile and no marked Issue, with a valid profile and no Activation locator, with an existing unique marker/open PR, and with duplicate Issue/PR markers. Use a local Git repository and bare remote to verify that a dirty `.agent/project.json` is the only path staged and pushed. Simulate a transient PR creation API failure after push, then retry without mocking profile writing or Git commits; verify exact branch recovery creates the PR. Repeat the failure with an independent checkout B cloned using `--single-branch --branch main` before the setup branch is pushed; retry from B, verify it fetches the exact remote branch and matches the previously observed full SHA before creating a local branch, then confirm the PR is created from the recovered commit. Add an unrelated staged, modified, or untracked path and verify staging is rejected. Re-run exact setup and verify it reuses the same Issue/PR.

<a id="ora-f01-002"></a>
<a id="ora-f01-002-expected-result"></a>
#### 2.8.1 ORA-F01-002 Expected result

The direct prompt needs no Issue number. One marked Activation Issue and one exact setup PR are created or reused. Only `.agent/project.json` is committed. After a PR API failure, an exact pushed branch can resume from the original checkout or an independent checkout that fetched only the default branch; remote `ls-remote` and fetched full SHA must match before the local branch is created. A branch with changed ancestry, extra paths, different bytes, or an SHA race between observation and fetch blocks. The PR is reviewable; setup alone cannot activate or relabel Issues.

<a id="tst-f01-003"></a>
<a id="tst-f01-003-immutable-activation-evidence"></a>
### 2.9 TST-F01-003 Immutable Activation evidence

**Setup and action:** Verify an admin-merged setup PR with exact `.agent/project.json`, approved ADC pointer, one latest required check per trusted App ID that was created and completed successfully no later than `merged_at`, and merge SHA on current main. Vary missing/malformed ADC pointer, comment deletion/edit, duplicate approval/record, wrong user ID/login/type, non-admin merger, wrong PR file/base/head/repository, failed or pending latest Check Run at merge, post-merge successful retry, equal `created_at` timestamps with distinct Check Run IDs, wrong merge SHA, and a mutation between direct/list/direct reads. Verify that the Check Run ID tie-break is deterministic, that a post-merge success cannot replace a failed/pending run at merge, and that a successful pre-merge run remains pinned when a later post-merge rerun appears. Record exact qualifying Check Run IDs and validate historical records by those IDs. Append a successor and verify its predecessor.

<a id="ora-f01-003"></a>
<a id="ora-f01-003-expected-result"></a>
#### 2.9.1 ORA-F01-003 Expected result

Activation is recorded only from the exact verified merge by the authenticated current admin. Every approval/record pair binds ADC proposal and approval, canonical profile digest, PR identity, merge, actor, predecessor, and exact successful Check Run IDs/evidence. New issuance chooses the latest run created by merge time, ordered by `(created_at, Check Run ID)`, and requires its successful completion no later than `merged_at`. A failed or pending selected run blocks even if a later rerun succeeds; a successful pre-merge run remains the pinned evidence when a later post-merge rerun appears. History reads fetch pinned run IDs and verify the recorded completion time does not exceed merge time. Any edit, deletion, duplicate, ambiguous history, API failure, or mid-read change fails closed. Exact retries do not append duplicate history.

<a id="tst-f01-004"></a>
<a id="tst-f01-004-prompt-and-approval-boundary"></a>
### 2.10 TST-F01-004 Prompt and approval boundary

**Setup and action:** Execute the exact prompt `P-ASESを有効化して。` from a consumer repository. Confirm the first command creates only the Issue, proposed ADC, project config branch, and PR. Try verification before merge, by a non-admin, under another authenticated user, with a caller-supplied identity, stale ADC, and without a successful trusted check. Then merge the exact setup PR as an admin and retry verification.

<a id="ora-f01-004"></a>
<a id="ora-f01-004-expected-result"></a>
#### 2.10.1 ORA-F01-004 Expected result

The prompt requests setup only. The exact admin merge is explicit policy approval; post-merge verification appends one approval and record only after reconstructing all evidence. ADC publication, ownership metadata, caller identity, or PASS text alone never activates.

<a id="tst-f01-005"></a>
<a id="tst-f01-005-strict-new-issue-timing"></a>
### 2.11 TST-F01-005 Strict new-Issue timing

**Setup and action:** Compare Issue creation times before, equal to, and after setup PR `merged_at`, including an Issue created after merge but before the record comment is published. Vary repository identity and PR status. Verify old Issues and existing labels remain unchanged and that an eligible Issue receives one immutable Gate Selection containing Activation Issue number, record ID, and digest.

<a id="ora-f01-005"></a>
<a id="ora-f01-005-expected-result"></a>
#### 2.11.1 ORA-F01-005 Expected result

Only same-repository non-PR Issues created strictly after the verified setup PR merge time select `p-ases-v1`. An Issue created between merge and evidence publication is eligible; an Issue created at or before merge remains `UNDETERMINED` without label side effects.

<a id="tst-f01-006"></a>
<a id="tst-f01-006-historical-pin-preservation"></a>
### 2.12 TST-F01-006 Historical pin preservation

**Setup and action:** Create and persist a Gate Selection against Activation A, append successor B, and call gate-policy again for the already-selected Issue. Also create an unselected Issue between A and B and select it only after B exists. Vary the pinned comment ID/digest, predecessor chain, current Issue ADC, kind/phase labels, work binding, receipts, and exact-subject evidence.

<a id="ora-f01-006"></a>
<a id="ora-f01-006-expected-result"></a>
#### 2.12.1 ORA-F01-006 Expected result

An existing selection remains bound to its exact historical record and gate-policy reuses it after B. A new selection for an Issue created between A and B uses A; an Issue created after B uses B. The complete chain and default-branch ancestry validate, and a successor cannot rewrite a selection or bypass ordinary phase checks.

<a id="tst-f01-007"></a>
<a id="tst-f01-007-successorreapproval"></a>
### 2.13 TST-F01-007 Successor/reapproval

**Setup and action:** Supersede the Activation ADC or remove/restore the profile locator. Attempt selection before the successor merge, replay an old setup PR, and append a valid successor after a new admin merge.

<a id="ora-f01-007"></a>
<a id="ora-f01-007-expected-result"></a>
#### 2.13.1 ORA-F01-007 Expected result

Policy or locator changes require a new setup PR and explicit admin merge. The successor links the previous record, governs only later-created Issues, and leaves earlier Activation records and Gate Selections unchanged. Removing the locator blocks new selections.

<a id="tst-f07-001"></a>
<a id="tst-f07-001-legacy-gate-is-prospective-and-typed"></a>
### 2.14 TST-F07-001 Legacy Gate is prospective and typed
<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->

**Setup and action:** Exercise the ordinary timestamp selector at pre-Activation, equal, and post-Activation creation times, plus the fixed #26–#32 Bootstrap cohort. Then read Issues with no Gate, one ordinary V1 Gate, one Owner-adopted legacy Gate, duplicate records, and conflicting V1/legacy records.

<a id="ora-f07-001"></a>
<a id="ora-f07-001-expected-result"></a>
#### 2.14.1 ORA-F07-001 Expected result

Ordinary selection and the fixed cohort retain their existing behavior. No old Issue receives a Gate without the exact adoption workflow. `read_gate_selection` returns a typed V1 or legacy record and blocks duplicate/conflicting history.

<a id="tst-f07-002"></a>
<a id="tst-f07-002-exact-bootstrap-authorization"></a>
### 2.15 TST-F07-002 Exact bootstrap authorization
<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->

**Setup and action:** Verify the canonical local grant record against its approved scope digest, repository/Owner IDs, Issue stable ID, approved ADC, Activation prefix, Binding generation, branch, exact pre-work remote HEAD, changed-file budget, decision, and time. Mutate each field, scope SHA, record key, or budget path; also try a tracked file outside the budget.

<a id="ora-f07-002"></a>
<a id="ora-f07-002-expected-result"></a>
#### 2.15.1 ORA-F07-002 Expected result

Only the complete canonical operator-reported grant for the exact scope verifies. The record does not claim cryptographic chat-host authentication. Any stale, malformed, mismatched, or out-of-budget case blocks before the first tracked edit and produces no Phase PASS evidence.

<a id="tst-f07-003"></a>
<a id="tst-f07-003-exact-adoption-plan-and-owner-ui-grant"></a>
### 2.16 TST-F07-003 Exact Adoption plan and Owner UI grant
<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->

**Setup and action:** Build a canonical per-Issue plan and vary repository/Owner ID, Issue ID/creation time/kind/phase/attention labels, Activation prefix, ADC pointer/state, Binding history/base/branch, remote HEAD, and proposed action. Verify an Owner-authored UI comment with correct/incorrect actor, operation, plan SHA, Issue attribution URLs, timestamps, direct/list/direct snapshots, missing pages, and duplicate comments.

<a id="ora-f07-003"></a>
<a id="ora-f07-003-expected-result"></a>
#### 2.16.1 ORA-F07-003 Expected result

Plan SHA covers every bound input and the planned Gate payload. For the Issue #46 risk-bound V2 plan, the repository ID `1401910271`, Issue stable ID `5846549384`, and Owner User ID `3744776` are exact; only one exact, immutable comment by that Owner User ID approves it. The authenticated writer must also be that Owner. Runtime, CLI flags, local JSON, another actor, another Issue, edited comment, or stale plan cannot substitute.

<a id="tst-f07-004"></a>
<a id="tst-f07-004-append-only-adoption-gate-and-recovery"></a>
### 2.17 TST-F07-004 Append-only Adoption, Gate, and recovery
<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->

**Setup and action:** Validate a V2 plan that binds both exact risk IDs and the Owner-only single-writer condition. Apply an approved exact plan as the authenticated Owner, lose the first response, lose the second response, replay a complete pair, inject one exact partial Adoption, and vary duplicate/conflicting/edited records, non-Owner writer, approval, ADC, Activation, Binding, labels, remote HEAD, observed concurrent modification, and Issue state. Keep the barrier-synchronized duplicate-write and privileged-marker-removal reproductions in the known-risk report; label them `KNOWN_RISK`, not PASS.

<a id="ora-f07-004"></a>
<a id="ora-f07-004-expected-result"></a>
#### 2.17.1 ORA-F07-004 Expected result

The Adoption record binds the exact planned Gate payload digest. The Gate references that Adoption record without a cyclic ID. Readback of Adoption completes before Gate append. The V2 plan binds `owner_trusted_single_writer_v1`, the Owner writer ID, and both known-risk IDs. A non-Owner process, stale input, observed duplicate, ambiguity, edit, drift, or conflict blocks and never writes a phase label. Exact complete records are read-only `NOOP`; a lost response recovers only through complete exact readback. Concurrent races between reads and privileged deletion/marker removal remain disclosed `KNOWN_RISK` cases and are not represented as passing guarantees.

<a id="tst-f07-005"></a>
<a id="tst-f07-005-reset-and-resume-normal-governance"></a>
### 2.18 TST-F07-005 Reset and resume normal governance
<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->

**Setup and action:** Adopt an Issue already at requirements and an eligible Issue in a later phase. Verify the separate reset plan/grant, Intent/Applied sequence, parent/dependency state, complete label set, one label PUT, lost response, existing attention, `phase:user-review` or resolved Owner decision, closed Issue, and readback failure. Then publish a new requirements-to-specification receipt for the adopted Issue. Separately create a Ready receipt at commit R and a descendant H: test both unchanged and changed ADC-declared artifacts, exact Issue #46 Ready-rebaseline plan/Owner approval, one append-only Intent/Applied checkpoint, and the subsequent ordinary `ready → execution` advance. Vary the approved ADC, ExecutionBinding, PR/base/HEAD, prior receipt, changed-path allowlist, Owner identity/comment edits, candidate document validation, duplicate history, changed plan or head between reads, partial/lost responses, and replay.

<a id="ora-f07-005"></a>
<a id="ora-f07-005-expected-result"></a>
#### 2.18.1 ORA-F07-005 Expected result

Requirements adoption makes no label change. A later-phase reset requires its own exact Owner grant, complete append-only Intent/Applied evidence, valid dependencies, and one verified label replacement; User Review decisions and closed Issues block, and the phase graph gains no backward edge. Phase receipts restart from requirements and bind current ADC/HEAD/documents. The separate Issue #46 Ready checkpoint never rewrites its historical receipt or relaxes exact-HEAD verification: every descendant, including one with unchanged Ready artifact hashes, requires a fresh exact-subject Owner grant, and changed Ready artifacts must preserve the ADC-declared path/role set and pass current document/traceability validation. Only a complete checkpoint can permit the normal `ready → execution` command; stale, denied, duplicate, conflicting, or incomplete evidence leaves the Issue label unchanged. All ordinary Design, Test Oracle, readiness, review, and delivery gates remain active.

<a id="tst-f06-001"></a>
### 2.19 TST-F06-001 Independent Review V2 and V1 compatibility

**Setup and action:** Round-trip exact V2 review records and compare fixed V1 fixture bytes and digests before and after adding V2. Pass a V1-only record to Readiness.

<a id="ora-f06-001"></a>
#### 2.19.1 ORA-F06-001 Expected result

V2 canonical bytes round-trip and preserve exact assurance. V1 bytes and reads remain unchanged, but V1-only evidence blocks current Readiness.

<a id="tst-f06-002"></a>
### 2.20 TST-F06-002 Host-verified provenance

**Setup and action:** Supply agent-writable, missing, ambiguous, wrong-parent, wrong-child, wrong-subject, and unverified host event wrappers; attempt `HOST_VERIFIED` evaluation.

<a id="ora-f06-002"></a>
#### 2.20.1 ORA-F06-002 Expected result

Only a trusted registered host verifier can establish `HOST_VERIFIED`. With no verifier configured, all such records block and no host ID or provenance is synthesized.

<a id="tst-f06-003"></a>
### 2.21 TST-F06-003 Native attested result

**Setup and action:** Supply both locally synthesized byte bundles and host-captured request, terminal return, and child-output bytes. Vary a task-name-only summary, parent-authored output, same-context result, missing completion, stale subject, mismatched request/output digest, and absence of a registered host capture boundary.

<a id="ora-f06-003"></a>
#### 2.21.1 ORA-F06-003 Expected result

Only exact bytes obtained through a registered native capture boundary with successful completion and a separate reviewer context may yield effective `INDEPENDENT_ATTESTED`. Locally synthesized, internally consistent JSON does not prove native execution. While no capture boundary is registered, every supplied bundle blocks with effective assurance `UNAVAILABLE`, including when the project explicitly selects `independent_attested`.

<a id="tst-f06-004"></a>
### 2.22 TST-F06-004 Canonical identity, freshness, and replay

**Setup and action:** Vary duplicate JSON keys, base64 encoding, evidence digests, issue/PR/HEAD/ADC/plan, ExecutionBinding, profile, optional host IDs, findings order, duplicate history, and replay. Submit child-authored output with a shortened `{repo, issue, pr, head}` subject, an `INFO` finding, and unsorted finding IDs.

<a id="ora-f06-004"></a>
#### 2.22.1 ORA-F06-004 Expected result

Exact null host IDs remain null. Child output must use the exact seven-field `VerificationSubject.as_dict()` subject; findings use only A/B/C severity and unique lexicographically sorted IDs. Every malformed, changed, stale, duplicate, replayed, conflicting, or blocking result is rejected before Readiness persistence. Historical malformed child bytes are never rewritten into canonical form.

<a id="tst-f06-005"></a>
### 2.23 TST-F06-005 Committed minimum assurance

**Setup and action:** Evaluate the same attested review with no setting, explicit `host_verified`, explicit `independent_attested`, and a changed profile digest.

<a id="ora-f06-005"></a>
#### 2.23.1 ORA-F06-005 Expected result

Absent setting defaults to `host_verified`. Attested evidence passes only the explicit `independent_attested` minimum and only with the exact current profile digest.

<a id="tst-f06-006"></a>
### 2.24 TST-F06-006 Readiness and downstream enforcement

**Setup and action:** Exercise ordinary V1 PASS and current eligible native V2 results, then Readiness and Final Delivery with V1-only, stale, unresolved, SELF_REVIEW, UNAVAILABLE, policy-drifted, and exact chat-exception inputs. For UNAVAILABLE, vary no review report, a current separate-context PASS report, same-context report, stale/wrong-subject report, FAIL/BLOCKED/CONCERNS, unresolved A/B/C findings, and missing report references. Include positive capture-unavailability with all non-review gates passing, missing Verification Plan, and each failing non-review gate.

<a id="ora-f06-006"></a>
#### 2.24.1 ORA-F06-006 Expected result

Ordinary review eligibility and V1 bytes remain unchanged. Only positive current native evidence meeting the committed minimum uses the ordinary path. A provenance exception may yield distinct Readiness only for `HOST_NATIVE_CAPTURE_UNAVAILABLE` after one exact-current separate-context review report has verdict PASS and no unresolved A/B/C findings. The result records that review occurred and discloses `review_assurance=UNAVAILABLE` plus `INDEPENDENT_REVIEW_PROVENANCE_UNAVAILABLE`. No review report, same-context report, stale/wrong-subject evidence, actual review failure, unresolved A/B/C finding, or any non-review failure remains blocked with zero User Review starts and zero phase mutations.

<a id="tst-f06-007"></a>
### 2.25 TST-F06-007 Host-specific adapters

**Setup and action:** Exercise separate Cloud, local CLI, Desktop, and Claude Code adapters with observed native requests, returns, IDs, and completion. Ensure no agent executable or agent-writable Hook is used as trusted host evidence.

<a id="ora-f06-007"></a>
#### 2.25.1 ORA-F06-007 Expected result

Each adapter reports only capabilities actually available on its surface. Unavailable native capture and trusted host verification are reported unavailable; a unit fixture does not count as a live host smoke test.

<a id="tst-f06-008"></a>
### 2.26 TST-F06-008 Capability documentation and package distributions

**Setup and action:** Read the per-surface status report and compare generated package files with canonical runtime, adapters, Skills, specs, design, test-oracles, and traceability.

<a id="ora-f06-008"></a>
#### 2.26.1 ORA-F06-008 Expected result

Each host/OS smoke status is PASS only after direct observation; inaccessible surfaces are NOT RUN or UNAVAILABLE. All distributions are generator-consistent.

<a id="tst-f06-009"></a>
### 2.27 TST-F06-009 Issue #63 / PR #64 isolation

**Setup and action:** Snapshot Issue #63, PR #64, their ADC/pointer/Binding/profile and labels before an Issue #46 run, then compare after all #46 commands.

<a id="ora-f06-009"></a>
#### 2.27.1 ORA-F06-009 Expected result

All #63/#64 workflow and evidence snapshots remain byte-for-byte unchanged. Any attempt to issue #63 review, User Review, policy, Activation, merge, or closure evidence is rejected.

<a id="tst-f06-010"></a>
<a id="tst-f06-010-explicit-opt-in-and-typed-capture-unavailability-eligibility"></a>
### 2.28 TST-F06-010 Explicit opt-in and typed capture-unavailability eligibility

**Setup and action:** Evaluate a default profile with capture unavailable, each permitted `unavailable_handling` value, unknown values, and the Issue #46 repository/Issue/PR identity tuple and nearby mismatches. Compare positive host-to-runtime capture absence with an actual failed review, unresolved A/B/C finding, malformed or stale evidence, missing Verification Plan, and failed CI/Verification/Acceptance/Self-Audit.

<a id="ora-f06-010"></a>
<a id="ora-f06-010-expected-result"></a>
#### 2.28.1 ORA-F06-010 Expected result

Omission and `block` remain blocking. Only an explicit committed `owner_exception` for repository ID `1401910271`, Issue #46 / stable ID `5846549384`, and PR #67 plus typed `HOST_NATIVE_CAPTURE_UNAVAILABLE` is eligible to plan an exception. `REVIEW_FAILED`, `INVALID_EVIDENCE`, unknown values, other subjects, and normal native-review success never take the exception path.

<a id="tst-f06-011"></a>
<a id="tst-f06-011-exact-exception-plan-owner-grant-and-append-only-record"></a>
### 2.29 TST-F06-011 Exact exception plan, Owner grant, and append-only record

**Setup and action:** Vary every canonical plan field and digest, Owner ID, Issue/repository/PR identity, base/HEAD, ADC, frozen Verification Plan, ExecutionBinding, PRBinding, profile, host surface, reason, observation digest, and risk. Add missing, edited, deleted, duplicate, conflicting, wrong-Owner, wrong-URL, timestamp-edited, and changed-between-direct/list/direct approval comments. Exercise exact apply, response loss, exact replay, and partial/conflicting local or Issue history.

<a id="ora-f06-011"></a>
<a id="ora-f06-011-expected-result"></a>
#### 2.29.1 ORA-F06-011 Expected result

Only the one canonical current plan and exact operation-scoped active-chat decision record can produce the separate implementation-authored exception record. The Owner does not post an approval comment. Every identity and subject binding is exact, and direct/list/direct reads match. Stale or invalid input writes nothing; exact replay is read-only; uncertain or conflicting state is not retried or replaced. The record says `operator_reported_chat`; it does not claim cryptographic chat origin.

<a id="tst-f06-012"></a>
<a id="tst-f06-012-versioned-readiness-and-final-delivery-compatibility"></a>
### 2.30 TST-F06-012 Versioned Readiness and Final Delivery compatibility

**Setup and action:** Compare fixed V1 Readiness, Final Delivery, and User Review bytes before and after adding V2. Evaluate valid and invalid exception cases, all non-review gates, risk fields, status values, and `merge_authorized` behavior.

<a id="ora-f06-012"></a>
<a id="ora-f06-012-expected-result"></a>
#### 2.30.1 ORA-F06-012 Expected result

All V1/V2 bytes and behavior remain identical. The forward chat-exception path emits Readiness V3 `READY_WITH_EXCEPTION` or `BLOCKED`, and Final Delivery V3 `READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION` or blocked. Both disclose that an independent review occurred, bind its actual outcome/findings digest, state `review_assurance=UNAVAILABLE` and `INDEPENDENT_REVIEW_PROVENANCE_UNAVAILABLE`, and preserve `merge_authorized=false`.

<a id="tst-f06-013"></a>
<a id="tst-f06-013-user-review-and-downstream-exact-subject-revalidation"></a>
### 2.31 TST-F06-013 User Review and downstream exact-subject revalidation

**Setup and action:** Start and submit User Review from ordinary Readiness V1 PASS and current Readiness V2 READY_WITH_EXCEPTION. Before every start/sync/status decision, recompute current Verification and Required Checks, the Readiness-bound Acceptance observations, Self-Audit references, dependencies, PR/base/HEAD, bindings, profile, and exception history without publishing or persisting. Between every recomputation, session start/submit, and Final Delivery read, mutate PR/HEAD, ADC, Verification Plan, ExecutionBinding, PRBinding, profile, exception record, Owner comment, Required CI, dependency, Verification, Acceptance, Self-Audit, and review-failure state; include a draft PR and dirty worktree. Exercise malformed, duplicate, and conflicting exception markers for the same HEAD after a valid receipt was applied. Check the Issue's actual unique kind/phase/attention labels before any session/snapshot/result write, compare pre-write label readbacks, then recheck identity and labels immediately before the phase PUT. Include `phase:execution`, wrong `--kind`, active attention, a label race, and an ambiguous label-write response.

<a id="ora-f06-013"></a>
<a id="ora-f06-013-expected-result"></a>
#### 2.31.1 ORA-F06-013 Expected result

Only the exact still-current V1 or V2 source can start the separate human User Review. Any changed non-review gate or bound input blocks before session, feedback snapshot, result, or phase writes. A current same-HEAD conflicting/malformed exception marker blocks every consumer. The unique live `kind:*` label is authoritative; wrong phase, kind, or attention blocks before persistence. Phase mutation uses another current identity/label readback. User Review remains independent, and explicit `PR_MERGE`, merge, and Issue closure are never authorized by the exception.

<a id="tst-f06-014"></a>
### 2.32 TST-F06-014 Review occurrence with unavailable host provenance

**Setup and action:** For the exact current Issue #46 / PR #67 subject, provide no review report, a separate-context occurrence with actual PASS and no findings linked to an UNAVAILABLE/BLOCKED V2 provenance result, a same-context report, wrong/stale subject, malformed report, FAIL/BLOCKED/CONCERNS, and a PASS with unresolved A/B/C findings. Verify the `PASES_INDEPENDENT_REVIEW_OCCURRENCE_V1` exact-output bytes and digest, matching V2 result, distinct context IDs, exact subject, Binding/profile digests, occurrence/outcome/findings fields, and direct file readback. Evaluate the exception plan and Readiness path for each case.

<a id="ora-f06-014"></a>
#### 2.32.1 ORA-F06-014 Expected result

`UNAVAILABLE` is accepted only as a host-provenance limitation attached to one actual current separate-context review. The legacy V2 result remains formally `BLOCKED`; the matching occurrence V1 carries actual PASS/FAIL and findings. No report or occurrence record, same-context, stale, malformed, non-PASS outcome, or unresolved blocking finding prevents exception planning and Readiness. The occurrence record retains the exact reviewer output bytes, actual outcome, findings, and matching V2/subject/binding/profile digests. A valid PASS occurrence labels only the residual risk `INDEPENDENT_REVIEW_PROVENANCE_UNAVAILABLE`; it never claims the review was skipped or cryptographically host-verified.

<a id="tst-f06-015"></a>
### 2.33 TST-F06-015 ADC-authorized one-time Requirements Rebaseline

**Setup and action:** After the exact successor ADC approval, vary ADC pointer, predecessor receipt, ExecutionBinding, PR/base/HEAD, complete Issue labels, and plan digest. Run the fresh read-only plan and apply to the exact current `phase:user-review` Issue.

<a id="ora-f06-015"></a>
#### 2.33.1 ORA-F06-015 Expected result

The ADC approval authorizes only one `phase:user-review` to `phase:requirements` transition under its stated preconditions. No second plan approval is requested. Drift or replay causes zero additional label writes; the first successful application records append-only Intent/Applied evidence and one label PUT.

<a id="tst-f06-016"></a>
### 2.34 TST-F06-016 Active-chat approval and technical evidence

**Setup and action:** Exercise exact affirmative and negative UI choices, stale or unrelated responses, wrong operation/scope/subject SHA, duplicate/conflicting records, and technical-record post/readback failure for ADC, exception, User Review, and PR merge scopes.

<a id="ora-f06-016"></a>
#### 2.34.1 ORA-F06-016 Expected result

Only `承認する` returned for the current active request grants the exact named operation. `承認しない`, cancellation, no response, stale text, or a different scope performs zero protected writes. The workflow may append its technical evidence record after approval; the user is never asked to post an approval comment.

<a id="tst-f06-017"></a>
### 2.35 TST-F06-017 Operator-reported provenance and history

**Setup and action:** Inspect newly written chat decisions and their Issue technical comment carriers across direct/list/direct reads. Vary recorder actor, predecessor ordering, comment location metadata, timestamps, edits, deletion, and duplicate operation/subject pairs.

<a id="ora-f06-017"></a>
#### 2.35.1 ORA-F06-017 Expected result

Records identify `operator_reported_chat` and separately identify the authenticated GitHub recorder. They do not claim a cryptographic chat signature or that the recorder authored the chat response. Technical records remain append-only; invalid location, changed body, duplicate or non-monotonic history blocks.
