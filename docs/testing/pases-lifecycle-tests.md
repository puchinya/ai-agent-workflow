<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# P-ASES Human Review and Integration Test Specification

- Status: Existing cases approved for Issues #31 and #42; TST-F01-014 and TST-F01-015 are drafts pending Issue #63 successor ADC approval and phase evidence.
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
  - [2.14 TST-F01-008 Effective V2 policy](#214-tst-f01-008-effective-v2-policy)
    - [2.14.1 ORA-F01-008 Expected result](#2141-ora-f01-008-expected-result)
  - [2.15 TST-F01-009 Exact approved Ruleset plan](#215-tst-f01-009-exact-approved-ruleset-plan)
    - [2.15.1 ORA-F01-009 Expected result](#2151-ora-f01-009-expected-result)
  - [2.16 TST-F01-010 Existing Issue non-retroactivity](#216-tst-f01-010-existing-issue-non-retroactivity)
    - [2.16.1 ORA-F01-010 Expected result](#2161-ora-f01-010-expected-result)
  - [2.17 TST-F01-011 V2 record creation time](#217-tst-f01-011-v2-record-creation-time)
    - [2.17.1 ORA-F01-011 Expected result](#2171-ora-f01-011-expected-result)
  - [2.18 TST-F01-012 Prefix and full-history validation](#218-tst-f01-012-prefix-and-full-history-validation)
    - [2.18.1 ORA-F01-012 Expected result](#2181-ora-f01-012-expected-result)
  - [2.19 TST-F01-013 Pre-merge bootstrap gates](#219-tst-f01-013-pre-merge-bootstrap-gates)
    - [2.19.1 ORA-F01-013 Expected result](#2191-ora-f01-013-expected-result)
  - [2.20 TST-F01-014 Activation admin session and approval separation](#220-tst-f01-014-activation-admin-session-and-approval-separation)
    - [2.20.1 ORA-F01-014 Expected result](#2201-ora-f01-014-expected-result)
  - [2.21 TST-F01-015 Owner authorization transport and lifecycle gates](#221-tst-f01-015-owner-authorization-transport-and-lifecycle-gates)
    - [2.21.1 ORA-F01-015 Expected result](#2211-ora-f01-015-expected-result)
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
- [TST-F01-008](#tst-f01-008) — 2.14 TST-F01-008 Effective V2 policy
- [ORA-F01-008](#ora-f01-008) — 2.14.1 ORA-F01-008 Expected result
- [TST-F01-009](#tst-f01-009) — 2.15 TST-F01-009 Exact approved Ruleset plan
- [ORA-F01-009](#ora-f01-009) — 2.15.1 ORA-F01-009 Expected result
- [TST-F01-010](#tst-f01-010) — 2.16 TST-F01-010 Existing Issue non-retroactivity
- [ORA-F01-010](#ora-f01-010) — 2.16.1 ORA-F01-010 Expected result
- [TST-F01-011](#tst-f01-011) — 2.17 TST-F01-011 V2 record creation time
- [ORA-F01-011](#ora-f01-011) — 2.17.1 ORA-F01-011 Expected result
- [TST-F01-012](#tst-f01-012) — 2.18 TST-F01-012 Prefix and full-history validation
- [ORA-F01-012](#ora-f01-012) — 2.18.1 ORA-F01-012 Expected result
- [TST-F01-013](#tst-f01-013) — 2.19 TST-F01-013 Pre-merge bootstrap gates
- [ORA-F01-013](#ora-f01-013) — 2.19.1 ORA-F01-013 Expected result
- [TST-F01-014](#tst-f01-014) — 2.20 TST-F01-014 Activation admin session and approval separation
- [ORA-F01-014](#ora-f01-014) — 2.20.1 ORA-F01-014 Expected result
- [TST-F01-015](#tst-f01-015) — 2.21 TST-F01-015 Owner authorization transport and lifecycle gates
- [ORA-F01-015](#ora-f01-015) — 2.21.1 ORA-F01-015 Expected result
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

<a id="tst-f01-008"></a>
### 2.14 TST-F01-008 Effective V2 policy

**Setup and action:** Configure explicit `solo_owner`, the four trusted Required Checks with App ID 15368, and the Activation Issue/history. Start with an empty Ruleset and invoke `consumer-activation-setup`; verify the exact committed setup branch and canonical policy plan are persisted but no V2 setup PR or Ruleset write exists. Exercise exact owner decision plus trusted Admin apply, then resume Activation and verify it reads the already-owned policy as zero-write `NOOP` before creating the policy-bound setup PR. Also test a matching owned Ruleset, an owned drift requiring one authorized PUT, stale profile/branch/plan subjects and automatic plan regeneration, a changed effective-policy digest against an existing open setup PR (preserve the old immutable proposal and create a new branch/plan/PR generation), missing check/App ID inputs, wrong default branch, inactive enforcement, wrong check context/App ID, nonzero approvals, bypass actors, missing `non_fast_forward`, unresolved review threads, unowned collision, legacy conflict, and unavailable 403 reads. In `external_reviewer`, verify a missing required-check identity is `INPUT_REQUIRED` with no setup PR and that the complete inventory reports the solo-owner managed Ruleset as `UNSUPPORTED` while preserving V1 behavior.

<a id="ora-f01-008"></a>
#### 2.14.1 ORA-F01-008 Expected result

Empty policy is a resumable exact-plan/approval stage, not a missing-Ruleset setup failure; the V2 setup PR is absent until policy verification succeeds. Once owner decision and trusted Admin apply complete, the same Activation resumes, sees a zero-write NOOP, and only then creates the PR bound to Ruleset ID, applied-record ID, setup branch, and effective-policy digest. A stale policy-bound PR stays unchanged; the next authorized policy generation has a fresh exact branch/plan subject and a separate setup PR. V2 is recorded only when branch, effective rules, Ruleset details, legacy protection, mode, checks, and admin identity are all readable and match. A 403 is `UNAVAILABLE`, never “not configured.” Stale profile/branch/plan inputs, missing trusted checks, unowned collision, or legacy conflict cannot produce an ACTIVE result. The external-reviewer inventory is complete and reports only mode-inapplicable solo-owner policy as `UNSUPPORTED`; missing required checks remain `INPUT_REQUIRED` and cannot be reported as ACTIVE.

<a id="tst-f01-009"></a>
### 2.15 TST-F01-009 Exact approved Ruleset plan

**Setup and action:** Generate a plan for empty, exact, owned-different, and same-name-unowned repository Ruleset states. Change repository ID, owner ID, configured Activation Issue, default branch SHA, committed profile bytes, mode, checks/App IDs, Ruleset ID/digest, predecessor, PR impact, and approval comment between planning and apply. Vary wrong author, edited/deleted/duplicated comment, wrong Issue, wrong repository, invalid plan digest, missing admin permission, API 403, and concurrent state changes. Simulate process death after a successful POST or PUT but before ownership-record publication, then retry from a fresh invocation with the exact plan and approval. Also combine legacy required approvals of one with a valid Ruleset requiring zero.

<a id="ora-f01-009"></a>
#### 2.15.1 ORA-F01-009 Expected result

Only the exact unedited owner approval for the unchanged canonical plan permits one POST or one PUT to the uniquely owned repository Ruleset. A persisted write intent lets a fresh invocation recover the exact Ruleset ID/body and predecessor, verify effective policy, and append the matching ownership record with no second write. An unowned same-name Ruleset with no intent cannot be adopted. An exact current state is a no-op. All stale, ambiguous, unauthorized, raced, or unreadable states block without modifying other Rulesets or retrying blindly. A legacy approval requirement of one plus Ruleset approvals of zero is `MISMATCH`; the legacy requirement is never replaced by the Ruleset value. Successful writes require exact detail and effective-policy readback plus append-only ownership evidence.

<a id="tst-f01-010"></a>
### 2.16 TST-F01-010 Existing Issue non-retroactivity

**Setup and action:** Pin an Issue to V1, append V2, then corrupt only a successor record and call both gate-policy and phase evidence for the old Issue. Separately alter its selected V1 prefix and current live Ruleset. Compare Issue ADC, Gate Selection comment, labels, PRBinding, checkpoints, and prior evidence before and after.

<a id="ora-f01-010"></a>
#### 2.16.1 ORA-F01-010 Expected result

Successor-only corruption does not invalidate a valid old V1 Issue. Corruption within its selected prefix or a current live policy mismatch blocks without rewriting its gate, labels, ADC, PR, or historical evidence.

<a id="tst-f01-011"></a>
### 2.17 TST-F01-011 V2 record creation time

**Setup and action:** Compare Issue `created_at` with the V2 setup PR `merged_at` and Activation record comment `created_at`. Create Issues before merge, between merge and record publication, exactly at record time, and after record time.

<a id="ora-f01-011"></a>
#### 2.17.1 ORA-F01-011 Expected result

V2 eligibility begins strictly after the Activation record comment's GitHub creation time. Issues in the merge-to-record interval continue using the latest eligible V1 Activation.

<a id="tst-f01-012"></a>
### 2.18 TST-F01-012 Prefix and full-history validation

**Setup and action:** Create a two-record V1→V2 chain and a Ruleset ownership chain. Read existing Gate Selections pinned to V1 and V2 while corrupting later Activation and Ruleset applied records. Then corrupt the selected Activation or its bound Ruleset applied-record prefix. Run new Issue selection, V2 setup, and successor issuance against the same full histories.

<a id="ora-f01-012"></a>
#### 2.18.1 ORA-F01-012 Expected result

Existing Issue reads validate exactly the Activation prefix through their selected record and, for V2, the Ruleset ownership prefix through its exact bound applied-record ID. Corruption after either selected prefix is ignored. A new selection or successor issuance validates the full Activation and Ruleset ownership histories and blocks on any malformed record.

<a id="tst-f01-013"></a>
### 2.19 TST-F01-013 Pre-merge bootstrap gates

**Setup and action:** Exercise the required order: implementation, successor ADC publication and generation-scoped Phase receipts, Activation V2 `ACTIVE` (including its separately reviewed/merged Setup PR), PR #64 merge, then Issue #63 closure readback. Keep PR #64 open after the Setup PR merge and attempt its merge before `ACTIVE`; that must block. After `ACTIVE`, independently remove or stale each #64 CI, Independent Review, User Review, Final Delivery, and exact-HEAD `PR_MERGE` input and verify merge remains blocked. Keep #60/PR #62 and all old #57/#63 evidence unchanged.

<a id="ora-f01-013"></a>
#### 2.19.1 ORA-F01-013 Expected result

ADC formalization and its Phase receipts precede Activation. Activation reaches `ACTIVE` only after the exact Setup PR merge, V2 record comment ID/`created_at`, Ruleset ID and effective policy all read back. A Setup PR merge alone cannot authorize #64. PR #64 merge requires its own exact HEAD gates and distinct `PR_MERGE`; Issue closure is read back only after #64 merge.

For the Activation-owned base transition, construct A, one profile-only setup commit, its exact merge commit B, and PR #64 HEAD with B integrated. Verify `pr ensure` appends a V2 PRBinding and readiness accepts the same typed evidence while the original ExecutionBinding and V1 PRBinding bytes stay unchanged. Reject ordinary main drift, any intervening or extra main commit, a wrong Setup PR ID or merge SHA, a profile mismatch at B or target HEAD, a changed code patch, a different target PR identity, and an absent/tampered evidence file. Final Delivery must re-read the same live evidence; changing current main or target base after Readiness blocks it.

<a id="tst-f01-014"></a>
<a id="220-tst-f01-014-activation-admin-session-and-approval-separation"></a>
### 2.20 TST-F01-014 Activation admin session and approval separation

**Setup and action:** Run each of the two explicit admin commands with a local interactive TTY, a missing/non-interactive TTY, empty input, and input cancellation. For the interactive path, use a repository-limited owner PAT with correct and incorrect owner/repository identity, admin permission, legacy protection, Ruleset inventory, and effective branch-rule responses; include 403 and incomplete readbacks. Exercise a clean plan, a blocked plan, exact and missing Issue #57 plan approvals, plan drift, and two separate command invocations. Interrupt apply after POST or PUT and retry with the same plan and approval. Record prompts, output, plan-file creation, API method sequence, and Issue #57 history before and after.

<a id="ora-f01-014"></a>
<a id="2201-ora-f01-014-expected-result"></a>
#### 2.20.1 ORA-F01-014 Expected result

Only the two explicit commands accept a credential, and only from an interactive owner-controlled TTY. A missing TTY, cancellation, identity/admin mismatch, 403, incomplete readback, blocked plan, absent exact approval, or plan drift produces no Ruleset write; a plan file is created only for a blocker-free canonical plan. A valid apply reaches at most the existing single POST or PUT path after exact Issue #57 approval. Interruption recovery performs reads only and does not issue a second write. Credentials do not appear in observable output, persisted files, or unrelated command behavior. Authentication, plan approval, User Review, Final Delivery, and merge authorization remain distinct.
<a id="tst-f01-015"></a>
<a id="221-tst-f01-015-owner-decision-relay-and-lifecycle-gates"></a>
### 2.21 TST-F01-015 Owner authorization transport and lifecycle gates

For the dedicated User Review carrier, assert the exact evaluator seam receives a validated session object, complete feedback snapshot, mode and PR author ID, and a typed verifier result. Verify the selected typed approval is persisted in the versioned result record and revalidated by Final Delivery against a fresh snapshot and full carrier chain. Preserve the carrier's `user-review-relay` identity end to end; it cannot be recast as formal PR review, host-attested chat, or a generic Issue comment. Cover current approved input, later feedback, unresolved threads, changed/deleted carrier, and mismatch between selected evidence and persisted result.

**Setup and action:** For the one-time #63 bootstrap, first publish an exact successor ADC as approved after its separate `ADC_SUPERSEDE` approval and verify the complete approved forward generation chain. Run the regular authenticated executor without any `PHASE_REBASE` decision. Assert it reads the exact old/new ADC IDs and SHA values, open Issue, body, and full label set; appends canonical Intent and confirms direct/list/direct; issues at most one label PUT replacing only `phase:ready`; double-reads Issue and ADC; then appends and reads Applied evidence. Changed ADC bytes, a stale/draft pointer, wrong current phase, closed Issue, incomplete readback, drifted label, or wrong Issue/repository comment URL must block. An existing Intent with target labels completes Applied without a second PUT; an existing Intent with the old or drifted labels blocks without a second PUT. Completed matching Applied evidence returns a read-only no-op. A GitHub 403 reports `BLOCKED_PERMISSION`. `ADC_SUPERSEDE` remains a separate exact-SHA approval and append-only pointer publication gate.

For `phase_rebaseline.py`, assert success with no phase-decision history and one bounded label PUT after matching approved ADC and forward-generation verification. Assert restart after PUT response loss completes Applied evidence without a second PUT; restart with Intent but old labels or drift blocks; completed matching evidence is a no-op. Reject duplicate/edited/deleted carriers, wrong actor metadata, wrong source URLs, stale or unapproved ADC, changed Issue body, wrong phase, and permission denial.

For the dedicated User Review carrier, assert the exact evaluator seam receives a validated session object, complete feedback snapshot, mode and PR author ID, and a typed verifier result. Verify the selected typed approval is persisted in the versioned result record and revalidated by Final Delivery against a fresh snapshot and full carrier chain. Preserve the carrier's `user-review-relay` identity end to end; it cannot be recast as formal PR review, host-attested chat, or a generic Issue comment. Cover current approved input, later feedback, unresolved threads, changed/deleted carrier, and mismatch between selected evidence and persisted result.

For self-authored `solo_owner` review, test both the existing delegated V1 route and owner-local V2 fallback. The V2 plan must bind exact repository/Issue/PR/HEAD/Readiness/ADC/session and prior feedback digest; a trusted owner TTY types the plan SHA, writes once, and reads back direct/list/direct. A distinct read-only principal may verify the owner carrier. Reject Cloud/non-TTY/shared auth, wrong owner, changed feedback, unresolved threads, cross-version session replay and formal self-approval. Re-run Final Delivery against current full feedback and require exact reproduction of the selected typed evidence and saved snapshot digest.

<a id="ora-f01-015"></a>
<a id="2211-ora-f01-015-expected-result"></a>
#### 2.21.1 ORA-F01-015 Expected result

For the #63 bootstrap, an approved exact successor ADC and verified pointer chain allow the regular authenticated P-ASES executor to perform the one phase label replacement. Intent and Applied comments are execution logs, not approvals. Target labels after interruption permit recovery without another write; old labels after Intent, unrelated drift, or invalid evidence block. The phase route remains unique to #63. `ADC_SUPERSEDE`, exact Ruleset plan approval, User Review, and PR merge retain their own separate gates. For `solo_owner` User Review, only the exact-session typed carrier returned by complete chain/readback verification can enter `evaluate_user_review`. The authenticated read-only verifier principal, obtained from the separate read client's `GET /user`, may differ from the owner and has no approval authority. The approved repository/Issue authority supplies the pinned stable repository ID and owner User ID (for this #63 ADC draft, `1401910271` and `3744776`). The current repository response must match those IDs, exact `full_name`, `owner.type=User`, and `owner.id`; ownership is not dynamically rebound. The current PR response supplies the author ID, which must match the configured owner. Approval requires the repository owner, PR author, carrier owner, and actual comment actor to agree, plus the exact session, Readiness, ADC, HEAD, full feedback snapshot, and resolved-thread state. The verifier also confirms each comment's actual `url`, `issue_url`, and `html_url` point to the intended host, repository, Issue, and comment ID in direct/list/direct reads. The persisted result contains the selected carrier proof and binds the full snapshot digest. Final Delivery revalidates both and must reproduce the saved result exactly. Missing or invalid origin/chain evidence, generic Issue comments, formal self-approval, `PASES_OWNER_DECISION_V1`, stale/replayed evidence, changed feedback, and unresolved threads never approve.

Delegated V1 is accepted only when the broker credential and route are positively isolated. Otherwise only a canonical V2 record from the configured owner-local TTY is accepted. V1 and V2 share one predecessor chain and cross-version operation/subject or session replay is rejected. Ruleset apply requires the separate exact #57 two-line approval and existing Admin continuation. ADC, Ruleset, User Review, Setup PR merge and PR #64 merge remain separate exact subjects. Phase bootstrap after approved ADC needs no phase approval and retains append-only Intent/Applied recovery. The Issue #57 Setup PR and PR #64 require separate exact-HEAD plans and decisions. #57 requires its canonical V2 payload, current policy and ADC generation, trusted passing checks, independent exact-HEAD approval and resolved threads without closing Issue #57; #64 requires fresh Final Delivery for the exact subject. A create-only durable attempt record precedes one exact-HEAD merge request. Lost responses and repeated invocations read GitHub only and never issue a second merge request. PRBinding V1 remains byte-identical.
