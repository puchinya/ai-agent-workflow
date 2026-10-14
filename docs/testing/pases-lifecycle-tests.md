<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# P-ASES Human Review and Integration Test Specification

- Status: Approved for Issue #31
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
<!-- heading-map:end -->


<a id="test-purpose"></a>
## 1 Test purpose

Verify human User Review, child Integration, and final merge gates as independent exact-subject records. The normal child phase evidence and initial kind/phase labels are covered by [TST-WF-009](workflow-tests.md#tst-wf-009); these parent migration tests continue to exercise the fixed #26–#32 exception boundary.

<a id="test-conditions-and-oracles"></a>
## 2 Test conditions and oracles

<a id="tst-ur-001"></a>
### 2.1 TST-UR-001 User Review identity and exact subject

**Setup and action:** Submit current and stale approvals from human, bot, and unrelated accounts; change HEAD, ADC, Readiness, feedback, and review-thread resolution between reads. Drive the CLI through `start → sync → status` with `session.json` present in the snapshot directory. Then alter a correctly named snapshot without changing its SHA filename and add an unknown JSON filename.

<a id="ora-ur-001"></a>
#### 2.1.1 ORA-UR-001 Expected result

Only a current human approval on the exact subject passes. Edits, deletions, stale state, incomplete pagination, or unresolved threads invalidate approval. Without approval the three-step CLI sequence reaches PENDING; a valid filename with modified bytes or an unexpected JSON filename fails closed.

<a id="tst-ur-002"></a>
### 2.2 TST-UR-002 Feedback loops and host provenance

**Setup and action:** Exercise all four GitHub feedback surfaces, repeated/edited/deleted events, direct host approval, a quoted message, an attachment, and an unverified CLI JSON event. For PR conversation and diff comments, test the exact two-line `P-ASES-DECISION: CHANGES_REQUESTED` plus `P-ASES-HEAD: <SHA-40>` body, current versus stale HEAD, inline `commit_id` match, authorized versus unrelated human, bot, quote, malformed syntax, and ordinary natural-language requests.

<a id="ora-ur-002"></a>
#### 2.2.1 ORA-UR-002 Expected result

Only a current authorized human's exact, unquoted, whole-body decision on the current HEAD returns the same Issue/PR to execution. Inline `commit_id` must match. Bot, unauthorized, stale, quoted, malformed, and natural-language comments do not trigger the transition. Host events require verified current-user provenance; questions and unresolved threads do not approve.

<a id="tst-ur-003"></a>
### 2.3 TST-UR-003 Parent Integration evidence

**Setup and action:** Remove, duplicate, open, fork, unmerged, out-of-main, and cyclic child records; invert a dependency merge timestamp; alter a merge SHA; omit or stale typed Verification/Acceptance evidence; and submit an arbitrary local PASS JSON with fabricated artifact bytes. Create a real temporary Git commit and bind its actual HEAD SHA to fake GitHub Actions run/job/step/Check Run API records. Test CI push-run selection, latest run/attempt, exact `main` SHA/repository/workflow path, all four matrix jobs, App ID `15368`, job Check Run URL binding, exact step conclusions, the manual parent-acceptance workflow, and missing/failed/skipped steps. Confirm the verifier reconstructs the evidence comment from API data and rejects a caller payload even when all fabricated SHA-256 values are internally consistent. Test double read by exact comment ID, edit timestamp/body, deletion, wrong author, wrong repository/Issue, wrong main/ADC, duplicate same-run comments, changed bytes, stale/superseded runs, and wrong App ID. Vary volatile avatar/profile URLs and login casing across direct, list, and second-direct reads; the same ID/type and case-insensitive login must pass, while a different normalized login or immutable comment/actor field blocks. Require author and authenticated-user IDs to be positive integers (excluding booleans); missing, zero, negative, and boolean IDs block. Exercise the publisher's `REUSED` path with those avatar variants, asserting no additional POST and blocking an authenticated-author mismatch. Exercise the public `issue integration-check` route with fixture GitHub endpoints while leaving `_read_parent_integration` unmocked; assert PASS with both exact comment IDs and BLOCKED when `main` advances but the comments remain bound to the old SHA. For legacy #26 labels, preflight current `[enhancement]`, apply once, retry idempotently, conflict with an existing phase, and simulate an API response loss after a partial label write. For the parent ADC, omit a pointer and verify the evaluator uses only the current approved child #31 ADC's unique pinned parent-contract declaration; reject duplicate declarations, a different source path/commit, an unapproved child pointer, or an unavailable pinned source.

<a id="ora-ur-003"></a>
#### 2.3.1 ORA-UR-003 Expected result

Integration passes only for the frozen native child set, exact dependency DAG, closed Issues, one merged same-repository PR per child, main ancestry, and current-main evidence reconstructed from trusted exact-SHA GitHub Actions run/job/step/Check Run API records. An authenticated exact-ID Issue #26 comment stores the derived bytes and run identity outside the named commit; comment edits/deletion, arbitrary local PASS data, wrong App, failed or skipped steps, stale SHA, or superseded run fail closed. Volatile avatar/profile URL differences and login casing alone do not change the authenticated author identity; author and authenticated-user IDs must be positive non-boolean integers, and missing, zero, negative, or boolean IDs fail closed. A different normalized login, author type, or immutable comment field also blocks. The publisher reuses an exact existing subject without POSTing another comment. The actual `issue integration-check` route reads both comments and the native graph through `_read_parent_integration`; it passes only for current-SHA evidence and blocks old-SHA comments after `main` advances. The real-commit test demonstrates the main SHA is not embedded in that commit's own tree.

<a id="tst-ur-004"></a>
### 2.4 TST-UR-004 Final Delivery separation

**Setup and action:** Vary User Review, GitHub formal review, Required Checks, branch protection, mergeability, and explicit merge authorization independently.

<a id="ora-ur-004"></a>
#### 2.4.1 ORA-UR-004 Expected result

Each gate must be checked separately. Final Delivery never authorizes or performs merge, release, Issue closure, or parent activation.

<a id="tst-ur-005"></a>
### 2.5 TST-UR-005 Parent User Review

**Setup and action:** With parent Integration blocked, verify no parent review session starts and `phase:user-review` is not set. With a passing fixed Integration subject, verify the parent phase moves from `integration` to `user-review`, an immutable session binds the parent ADC, six child/merge pairs, and Integration digest, and the first invocation returns pending. Then vary exact parent Issue decision subject, actor identity/type, session timestamp, comment edit/deletion, ADC digest, child merge SHA, and Integration digest. Confirm an exact current human approval is recognized, while approval never sets merge authorization or activation.

<a id="ora-ur-005"></a>
#### 2.5.1 ORA-UR-005 Expected result

Parent User Review starts only after exact Integration PASS. Only a new whole-body `P-ASES-DECISION: APPROVED` plus `P-ASES-SUBJECT: <SHA-256>` parent Issue comment from the authenticated human can approve. Stale, edited, deleted, incomplete, or changed-subject decisions fail closed. Approval leaves parent close, activation, merge, and release as separate gates.

<a id="tst-ur-006"></a>
### 2.6 TST-UR-006 Parent Activation provenance and comment history

**Setup and action:** Build a fixed #26 Activation fixture with six closed child Issues, six merged same-repository PRs, the V1 integration envelope, V2 Verification and Acceptance comments, Actions runs/jobs/steps/Check Runs, an owner approval, and an Activation record. Verify a valid fixture passes after reconstructing both typed V2 comments from GitHub APIs. Then independently vary each V1 PASS flag, digest, HTTPS ref, comment ID, run ID, parent ADC, activation SHA, child merge SHA, Actions App ID, workflow/job/step/check identity, and run status; include nonexistent Actions references and self-asserted PASS with fabricated matching hashes. Add missing, duplicated, edited, deleted, wrong-Issue, wrong-URL, wrong-ID, wrong-owner-ID/login/type, and timestamp-edited approval, Activation, V1 integration, and V2 evidence comments. Change a target comment between direct/list/direct reads. Vary avatar/profile URLs and login casing without changing stable author identity. Finally advance current main to a descendant commit after successful Activation and verify the original Activation remains valid; move the Activation commit off main and verify it blocks.

<a id="ora-ur-006"></a>
#### 2.6.1 ORA-UR-006 Expected result

Activation passes only when the complete exact-SHA Verification and Acceptance evidence is reconstructed from trusted GitHub Actions API records (App ID 15368), the approved parent ADC and all six real child merge SHAs match, and current main contains the activation commit. Caller PASS flags, digests, or URLs alone never establish Activation. Approval, Activation, and referenced evidence comments pass only when each is unique and direct/list/direct identity matches across ID, exact body, `created_at == updated_at`, Issue/HTML/API URLs, and stable owner User ID/login/type. Edited, deleted, duplicated, misattributed, misbound, or changing records and any API failure block. Avatar/profile-only differences and login casing are tolerated. Advancing main preserves a valid historical activation as long as its commit remains on main.
