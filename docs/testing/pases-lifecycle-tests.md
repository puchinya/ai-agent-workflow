<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# P-ASES Human Review and Integration Test Specification

- Status: Existing cases approved for Issues #31 and #42; TST-F01-014 and TST-F01-015 are drafts pending Issue #63 successor ADC approval and phase evidence. TST-UR-007 and TST-UR-008 specify host-owned Independent Review handoff and automatic User Review start; host integration execution is required where the active host exposes native subagents.
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
  - [2.19 TST-F01-013 Deferred Issue close and Activation ordering](#219-tst-f01-013-deferred-issue-close-and-activation-ordering)
    - [2.19.1 ORA-F01-013 Expected result](#2191-ora-f01-013-expected-result)
  - [2.20 TST-F01-014 Activation admin session and approval separation](#220-tst-f01-014-activation-admin-session-and-approval-separation)
    - [2.20.1 ORA-F01-014 Expected result](#2201-ora-f01-014-expected-result)
  - [2.21 TST-F01-015 Chat-confirmed authorization and lifecycle gates](#221-tst-f01-015-chat-confirmed-authorization-and-lifecycle-gates)
    - [2.21.1 ORA-F01-015 Expected result](#2211-ora-f01-015-expected-result)
  - [2.22 TST-UR-007 Native Independent Review handoff and User Review start](#222-tst-ur-007-native-independent-review-handoff-and-user-review-start)
    - [2.22.1 ORA-UR-007 Expected result](#2221-ora-ur-007-expected-result)
  - [2.23 TST-UR-008 Independent Review blockers and host provenance](#223-tst-ur-008-independent-review-blockers-and-host-provenance)
    - [2.23.1 ORA-UR-008 Expected result](#2231-ora-ur-008-expected-result)
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
- [TST-F01-013](#tst-f01-013) — 2.19 TST-F01-013 Deferred Issue close and Activation ordering
- [ORA-F01-013](#ora-f01-013) — 2.19.1 ORA-F01-013 Expected result
- [TST-F01-014](#tst-f01-014) — 2.20 TST-F01-014 Activation admin session and approval separation
- [ORA-F01-014](#ora-f01-014) — 2.20.1 ORA-F01-014 Expected result
- [TST-F01-015](#tst-f01-015) — 2.21 TST-F01-015 Chat-confirmed authorization and lifecycle gates
- [ORA-F01-015](#ora-f01-015) — 2.21.1 ORA-F01-015 Expected result
- [TST-UR-007](#tst-ur-007) — 2.22 TST-UR-007 Native Independent Review handoff and User Review start
- [ORA-UR-007](#ora-ur-007) — 2.22.1 ORA-UR-007 Expected result
- [TST-UR-008](#tst-ur-008) — 2.23 TST-UR-008 Independent Review blockers and host provenance
- [ORA-UR-008](#ora-ur-008) — 2.23.1 ORA-UR-008 Expected result
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

**Setup and action:** Run setup with no profile and no marked Issue, with a valid profile and no Activation locator, with an existing unique marker/open PR, and with duplicate Issue/PR markers. Use a local Git repository and bare remote to verify that a dirty `.agent/project.json` is the only path staged and pushed. Simulate a transient PR creation API failure after push, then retry without mocking profile writing or Git commits; verify exact branch recovery creates the PR. Repeat the failure with an independent checkout B cloned using `--single-branch --branch main` before the setup branch is pushed; retry from B, verify it fetches the exact remote branch and matches the previously observed full SHA before creating a local branch, then confirm the PR is created from the recovered commit. Add an unrelated staged, modified, or untracked path and verify staging is rejected. Re-run exact setup and verify it reuses the same Issue/PR. Also call setup from a clean PR feature branch, a dirty default worktree, a detached checkout, and a default checkout whose local HEAD differs from the GitHub branch SHA; assert each is rejected with zero GitHub writes. For the feature branch, snapshot its HEAD, Issue #63 `ExecutionBinding`, V1 `PRBinding`, and Issue #63 history and verify all remain unchanged. The positive setup case must start on a clean default branch whose local HEAD, bare-remote SHA, and GitHub branch SHA are identical.

<a id="ora-f01-002"></a>
<a id="ora-f01-002-expected-result"></a>
#### 2.8.1 ORA-F01-002 Expected result

The direct prompt needs no Issue number. One marked Activation Issue and one exact setup PR are created or reused. Only `.agent/project.json` is committed. After a PR API failure, an exact pushed branch can resume from the original checkout or an independent checkout that fetched only the default branch; remote `ls-remote` and fetched full SHA must match before the local branch is created. A branch with changed ancestry, extra paths, different bytes, or an SHA race between observation and fetch blocks. Setup starts only from a clean worktree on the repository default branch with local HEAD equal to the GitHub default-branch SHA. Feature, dirty, detached, or stale checkouts fail before a GitHub write; rejection leaves the PR #64 branch, bindings, and Issue #63 history unchanged. The PR is reviewable; setup alone cannot activate or relabel Issues.

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
### 2.19 TST-F01-013 Deferred Issue close and Activation ordering

**Setup and action:** Preserve the ordinary `Closes #41` path: after GitHub auto-closes the Issue, Final Delivery reports finalized without sending another close write. Exercise the Issue #63 order: implementation, successor ADC publication and generation-scoped Phase receipts, pre-merge solo-owner Ruleset verification (or an independently approved exact plan/apply), then fresh PR #64 CI, Independent Review, User Review, Final Delivery, and exact-HEAD `PR_MERGE`. Require exactly one standalone `Refs #63`. The shared detector recognizes case-insensitive `close`/`closes`/`closed`, `fix`/`fixes`/`fixed`, and `resolve`/`resolves`/`resolved`, with optional colons and both `#N` and `OWNER/REPO#N`; repository-qualified references compare owner/repository case-insensitively, so another repository's same-number Issue is not classified as this Issue. Inject `Fixes: #63`, `Closes: #63`, `Resolves puchinya/ai-agent-workflow#63` in PR title/body, every commit message, and planned merge title/message, plus a foreign-repository `...#63` case, duplicate/wrong `Refs`, PR number other than 64, non-empty GitHub `closingIssuesReferences`, an auto-closing Issue cross-reference, and incomplete GraphQL pagination; every unsafe or incomplete case must block before merge with zero merge requests. Confirm the keyword tests block even when `closingIssuesReferences` is empty. Verify that `Refs #63` alone remains safe and the exact safe merge request and current Issue metadata are re-read immediately before merge. The merged PR and actual merge commit readback must use the same closing-reference detector. After merge, verify Issue #63 is still OPEN and return `MERGED_AWAITING_ISSUE_COMPLETION`. Only then complete Activation V2 and separately review/merge its Setup PR. Require the V2 record ID/`created_at`, current owned Ruleset and effective policy to read back from a clean default worktree, with Activation `created_at` later than #64 merge. Finalize #63 with one durable close intent, one Issue PATCH, and direct/list/direct OPEN→CLOSED readback. Test no V2 record, V1-only history, wrong/older effective time, policy drift/403, closed Issue without matching intent, lost close response, and an existing intent while Issue remains OPEN; none may cause a second PATCH or reopen. Keep #60/PR #62 and old #57/#63 evidence unchanged.

<a id="ora-f01-013"></a>
#### 2.19.1 ORA-F01-013 Expected result

Ordinary PRs retain standalone `Closes #N` and GitHub auto-close. ADC formalization and its Phase receipts precede PR #64 merge. Activation `ACTIVE` is not a #64 merge prerequisite; the pre-merge gate still requires its own exact-HEAD CI, independent review, User Review, Final Delivery and distinct `PR_MERGE`, plus a verified effective Ruleset. Only PR #64 uses `Refs #63`; its body, every commit message, planned merge message, GitHub closing-Issue references and Issue cross-reference metadata must prove that merge cannot close #63. Issue #63 remains OPEN after the merge. Post-merge Activation reaches `ACTIVE` only after its separate Setup PR merge, V2 record comment ID/`created_at`, Ruleset ID and effective policy all read back from the current clean default worktree. Only a V2 effective time later than the #64 merge permits the one-shot durable Issue close; every missing, stale, ambiguous or failed proof leaves #63 OPEN and never repeats an ambiguous PATCH.

Retain the existing Activation-owned base-transition regression as a separate compatibility test: construct A, one profile-only setup commit, exact merge B, and a PR HEAD with B integrated. Verify `pr ensure` appends a V2 PRBinding while original ExecutionBinding and V1 PRBinding bytes stay unchanged. Reject ordinary main drift, intervening/extra commits, wrong Setup PR ID or merge SHA, profile mismatch, changed code patch, wrong target identity and absent/tampered evidence. Final Delivery re-reads the typed evidence. This path does not advance PR #64 in the new Issue #63 order because its Activation is post-merge.

<a id="tst-f01-014"></a>
<a id="220-tst-f01-014-activation-admin-session-and-approval-separation"></a>
### 2.20 TST-F01-014 Activation admin session and approval separation

**Setup and action:** Run each of the two explicit Admin commands with default `--auth-mode isolated-gh-device`. Fake success, failure, and interruption of the exact `gh auth login --hostname github.com --web --git-protocol https --insecure-storage` call; verify the private mode-0700 `GH_CONFIG_DIR`, runner-managed PTY challenge display without owner-local TTY, ambient token stripping, parent `gh` config preservation, and cleanup. Cover explicit nonstandard `--auth-mode pat` fallback with local interactive TTY, missing/non-interactive TTY, empty input, cancellation, and a repository-limited owner PAT. Exercise correct and incorrect owner/repository identity, admin permission, legacy protection, Ruleset inventory, and effective branch-rule responses; include 403 and incomplete readbacks. Exercise a clean plan, blocked plan, exact and missing Issue #57 plan approvals, plan drift, and separate command invocations. Interrupt apply after POST or PUT and retry with the same plan and approval. Record prompts, output, plan-file creation, API method sequence, and Issue #57 history before and after. If the runner cannot display the browser challenge, record `ADMIN_DEVICE_LOGIN_UNAVAILABLE` and verify zero Admin/Ruleset writes; do not fabricate PTY availability.

<a id="ora-f01-014"></a>
<a id="2201-ora-f01-014-expected-result"></a>
#### 2.20.1 ORA-F01-014 Expected result

Only the two explicit commands accept Admin authentication. Device mode is the default and uses the human-completed isolated browser challenge with a mode-0700 private config, no inherited token variables, and no change to normal `gh` config; a runner-managed PTY may display the challenge without an owner-local TTY. Explicit PAT fallback reads the owner-created PAT through `getpass` from a trusted owner-local TTY. Unavailable device login, non-TTY PAT fallback, cancellation, identity/admin mismatch, 403, incomplete readback, blocked plan, absent exact approval, or plan drift produces no Ruleset write; a plan file is created only for a blocker-free canonical plan. A valid apply reaches at most the existing single POST or PUT path after exact Issue #57 approval. Interruption recovery performs reads only and does not issue a second write. PAT bytes do not appear in observable output, persisted files, or unrelated command behavior. Device config cleanup does not revoke the GitHub OAuth grant; same-OS-user subprocesses are not a strong sandbox. Authentication, plan approval, User Review, Final Delivery, and merge authorization remain distinct.
<a id="tst-f01-015"></a>
<a id="221-tst-f01-015-owner-decision-relay-and-lifecycle-gates"></a>
### 2.21 TST-F01-015 Chat-confirmed authorization and lifecycle gates

For the dedicated User Review carrier, assert the exact evaluator seam receives a validated session, complete feedback snapshot, mode, PR author ID and typed V1/V2/V3 evidence. Persist selected V3 scope evidence in the result and revalidate it in Final Delivery against a fresh snapshot and full carrier chain. Preserve `user-review-relay` identity; never recast it as formal PR review or signed host chat. Cover current approval, later feedback, unresolved threads, changed/deleted carrier and result mismatch.

**Setup and action:** Verify the approved successor ADC and complete forward pointer chain, then run the phase executor without any `PHASE_REBASE` decision. For the first approved successor, assert the legacy V1 ready→requirements pair and at most one label PUT, including recovery after a lost PUT response without a second PUT. Validate the actual historical V1 payload, which omits `executor_user_id`, and also verify a present legacy extension matches its GitHub actor. For later ADC generations, seed that exact historical V1 pair and `phase:requirements` state; assert a V2 `adopt_existing_requirements` pair that links predecessor/successor ADC pointers and the preceding Applied ID plus canonical payload digest, double-reads the exact current Issue body and full labels, and makes zero label PUT calls. Assert the old V1/V2 comment bodies remain byte-identical, subsequent generations link contiguously, and a completed current generation is read-only NOOP. Test process interruption after V2 Intent by recovering with only the matching Applied append. Reject duplicate records, an incomplete historical V1 pair, missing or skipped V2 generations, wrong predecessor/digest, stale ADC pointer, changed Issue body/labels, wrong Issue/repository URL, missing pagination page, 403, edit/deletion, and ambiguous readback with no label write or duplicate POST.

For an ADC-generation change with an existing binding, create the old approved generation's Phase receipt, then return a newer approved ADC from `context show`. Verify it reports `STALE_BINDING` and exposes the exact frozen base ref/SHA, branch ref, worktree and initial HEAD. Run the real `work bind` CLI using those values and the newer ADC; assert binding history retains the exact old prefix and appends one new generation with unchanged frozen identity. Snapshot a valid PRBinding V1 file and assert its bytes remain unchanged. Confirm `context show` returns `BOUND`, then publish and read back the same phase transition for the new ADC. Assert the old receipt remains unchanged and the new receipt binds the new ADC pointer/SHA. Verify `work base` is not used to resolve a replacement base.

For chat approval, capture only a current same-conversation user-role response after showing exact repository, Issue, operation, final ADC/plan SHA or PR+HEAD, and diff/gates. Correct explicit approval produces only a bound ephemeral grant; vague “continue”, assistant text, another conversation without trusted transfer, CLI flag, JSON/file, stale subject and non-owner actor produce zero writes. Assert scope hash is not represented as chat signature. When role metadata is unavailable, expect `CHAT_PROVENANCE_UNAVAILABLE`. V1/V2 histories remain unchanged; V3 direct/list/direct must verify exact owner, URL, time, plan/scope, and predecessor.

Carrier discovery must ignore prose/comments that merely mention `PASES_OWNER_DECISION_*` or `PASES_USER_REVIEW_DECISION_*`; unknown/malformed schemas at the actual owner HTML-marker or User Review top-level JSON carrier position still block. Include the Issue #63 contract-comment shape that mentions the schema in prose.

For self-authored `solo_owner` review, preserve delegated V1 and owner-local V2 as legacy records, and test V3 binding of repository/Issue/PR/HEAD/Readiness/ADC/session/prior-feedback/plan/scope. A separate read-only principal can verify the configured owner. Reject wrong owner/actor/PR author, later feedback, unresolved threads, cross-version replay, formal self-approval and incomplete pagination. Re-run Final Delivery against the full current snapshot and require the exact saved selected evidence.

<a id="ora-f01-015"></a>
<a id="2211-ora-f01-015-expected-result"></a>
#### 2.21.1 ORA-F01-015 Expected result

A direct same-conversation exact-scope user-role response can produce operator-reported V3 evidence only when the host provides that role event. This evidence is not a signed chat attestation. V1/V2 meaning and bytes remain unchanged. Separate pinned owner, PR author, actual comment actor, and read-only verifier identities are verified independently. ADC, Ruleset, User Review, Setup PR merge and PR #64 merge remain distinct exact scopes. Phase bootstrap requires no owner decision: the immutable V1 pair records the original physical label transition, while each later ADC generation gets a V2 technical pair. V2 adopts the existing `requirements` phase with unchanged complete labels and zero label writes, links to the immediately preceding Applied payload digest, and rejects gaps or stale Issue/pointer state; interrupted latest V2 work can append only its matching Applied record after readback. Ruleset needs the exact V3 plan decision plus the owner-authenticated #57 two-line approval. Setup and #64 each require exact HEAD gates, with at most one merge request and read-only recovery. Preserve PRBinding V1.

<a id="tst-ur-007"></a>
<a id="tst-ur-007-native-independent-review-handoff-and-user-review-start"></a>
### 2.22 TST-UR-007 Native Independent Review handoff and User Review start

**Setup and action:** Use a current exact PR HEAD, approved ADC/Implementation Contract, complete checklist, full source diff, and test evidence. Exercise the host-native subagent workflow and verify all of the following: (1) one dedicated child is spawned and joined without another user confirmation, in a context distinct from implementation; (2) the child itself reads the exact repository/Issue/PR/HEAD, full Contract, all checklist items, full diff, and tests; (3) the host supplies the actual spawn/session ID, reviewer ID, and implementation binding ID, while the child authors the raw review and the parent does not edit findings, verdict, or context IDs; (4) after child PASS, current Phase, Binding, Verification, Acceptance, Self-Audit, and Required CI are read; (5) if all are current and PASS, `delivery readiness` runs and a PASS automatically invokes `user-review start` exactly once without extra confirmation; (6) the resulting User Review session is pending and no approval is created automatically; (7) ChatGPT is accepted as the Owner-selected code-review method without requiring a duplicate review; (8) existing review history, PR #64 `Refs #63`, User Review V3, and Required CI checks remain part of their existing gates.

<a id="ora-ur-007"></a>
<a id="ora-ur-007-expected-result"></a>
#### 2.22.1 ORA-UR-007 Expected result

Only a host-created and host-joined dedicated child can supply Independent Review. It authors the raw exact-subject result after reading the whole Contract, checklist, diff, and tests; the parent ingests that result unchanged through the existing audit path. The host owns and reports actual spawn/session, reviewer, and implementation binding identities; context ID inequality alone is not authenticity proof. A fully current PASS evidence set leads to `delivery readiness` and one automatic User Review start, without recording or implying the user's final approval. ChatGPT's selected User Review code-review method is not duplicated and does not replace the explicit User Review decision. Existing history, V3 evidence, `Refs #63`, and Required CI behavior remains unchanged.

<a id="tst-ur-008"></a>
<a id="tst-ur-008-independent-review-blockers-and-host-provenance"></a>
### 2.23 TST-UR-008 Independent Review blockers and host provenance

**Setup and action:** Against the host workflow, inject: (1) an unresolved A or B finding, a blocking C finding, or a failed checklist item; (2) a child reviewed on an older HEAD followed by a new commit; (3) spawn unavailable, spawn/join failure, timeout, or unknown completion; (4) missing or unverified host-reported spawn/session, reviewer, or implementation binding identity; (5) an attempted same-agent second prompt, human fallback, or User Review substitution; (6) repeated retry on the same HEAD without progress; (7) an active adapter with unverified native subagent capability; and (8) a current PR with absent/stale Phase, Binding, Verification, Acceptance, Self-Audit, or Required CI evidence. Observe readiness and User Review start commands and all claims made in the host result/PR report.

<a id="ora-ur-008"></a>
<a id="ora-ur-008-expected-result"></a>
#### 2.23.1 ORA-UR-008 Expected result

Every blocker prevents Readiness and User Review start. An unavailable or unverifiable native subagent fails closed as `INDEPENDENT_SUBAGENT_UNAVAILABLE`; no fallback can produce PASS. A HEAD change requires a new child; same-HEAD retries require progress. Host evidence unavailable at the active surface is explicitly reported as unverified and is not claimed as a completed subagent review. Existing PASES independent-review context IDs and digest validation remain intact; they are not upgraded to host-authenticated provenance. No final User Review approval is fabricated.
