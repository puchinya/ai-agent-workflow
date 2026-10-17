<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# Runtime and CLI Test Specification

- Status: Existing cases approved; TST-RT-018 and TST-RT-019 are drafts pending Issue #63 successor ADC approval and phase evidence.
- Owning specification: ../specs/

The stable RT test IDs preserve the earlier traceability graph. Current CLI cases use the namespaced P-ASES routes. Procedures for APIs that the Runtime Specification marks legacy are regression conditions for retained internal behavior, not public-command compatibility requirements.

<!-- contents:start -->
**Contents**
- [1 Test purpose](#1-test-purpose)
- [2 Test conditions and oracles](#2-test-conditions-and-oracles)
  - [2.1 TST-RT-001 Project profile validation](#21-tst-rt-001-project-profile-validation)
    - [2.1.1 ORA-RT-001 Expected result](#211-ora-rt-001-expected-result)
  - [2.2 TST-RT-002 Context routing](#22-tst-rt-002-context-routing)
    - [2.2.1 ORA-RT-002 Expected result](#221-ora-rt-002-expected-result)
  - [2.3 TST-RT-003 Document owner validation](#23-tst-rt-003-document-owner-validation)
    - [2.3.1 ORA-RT-003 Expected result](#231-ora-rt-003-expected-result)
  - [2.4 TST-RT-004 Feature branch base selection](#24-tst-rt-004-feature-branch-base-selection)
    - [2.4.1 ORA-RT-004 Expected result](#241-ora-rt-004-expected-result)
  - [2.5 TST-RT-005 Expected base SHA mismatch](#25-tst-rt-005-expected-base-sha-mismatch)
    - [2.5.1 ORA-RT-005 Expected result](#251-ora-rt-005-expected-result)
  - [2.6 TST-RT-006 Workspace binding](#26-tst-rt-006-workspace-binding)
    - [2.6.1 ORA-RT-006 Expected result](#261-ora-rt-006-expected-result)
  - [2.7 TST-RT-007 Review PR retry/readback](#27-tst-rt-007-review-pr-retryreadback)
    - [2.7.1 ORA-RT-007 Expected result](#271-ora-rt-007-expected-result)
  - [2.8 TST-RT-008 Contract byte identity](#28-tst-rt-008-contract-byte-identity)
    - [2.8.1 ORA-RT-008 Expected result](#281-ora-rt-008-expected-result)
  - [2.9 TST-RT-009 Contract execution authority](#29-tst-rt-009-contract-execution-authority)
    - [2.9.1 ORA-RT-009 Expected result](#291-ora-rt-009-expected-result)
  - [2.10 TST-RT-010 Review and delivery evidence](#210-tst-rt-010-review-and-delivery-evidence)
    - [2.10.1 ORA-RT-010 Expected result](#2101-ora-rt-010-expected-result)
  - [2.11 TST-RT-011 Failure, logging, and cleanup](#211-tst-rt-011-failure-logging-and-cleanup)
    - [2.11.1 ORA-RT-011 Expected result](#2111-ora-rt-011-expected-result)
  - [2.12 TST-RT-012 Observable CLI results](#212-tst-rt-012-observable-cli-results)
    - [2.12.1 ORA-RT-012 Expected result](#2121-ora-rt-012-expected-result)
  - [2.13 TST-RT-013 Data and API formats](#213-tst-rt-013-data-and-api-formats)
    - [2.13.1 ORA-RT-013 Expected result](#2131-ora-rt-013-expected-result)
  - [2.14 TST-RT-014 Security and privacy](#214-tst-rt-014-security-and-privacy)
    - [2.14.1 ORA-RT-014 Expected result](#2141-ora-rt-014-expected-result)
  - [2.15 TST-RT-015 Error and boundary cases](#215-tst-rt-015-error-and-boundary-cases)
    - [2.15.1 ORA-RT-015 Fail-closed result](#2151-ora-rt-015-fail-closed-result)
  - [2.16 TST-RT-016 Effective branch-policy assessment](#216-tst-rt-016-effective-branch-policy-assessment)
    - [2.16.1 ORA-RT-016 Expected result](#2161-ora-rt-016-expected-result)
  - [2.17 TST-RT-017 Canonical plan and write boundary](#217-tst-rt-017-canonical-plan-and-write-boundary)
    - [2.17.1 ORA-RT-017 Expected result](#2171-ora-rt-017-expected-result)
  - [2.18 TST-RT-018 Temporary child-process credential isolation](#218-tst-rt-018-temporary-child-process-credential-isolation)
    - [2.18.1 ORA-RT-018 Expected result](#2181-ora-rt-018-expected-result)
  - [2.19 TST-RT-019 Delegated owner decision record and replay protection](#219-tst-rt-019-delegated-owner-decision-record-and-replay-protection)
    - [2.19.1 ORA-RT-019 Expected result](#2191-ora-rt-019-expected-result)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [TST-RT-001](#tst-rt-001) — 2.1 TST-RT-001 Project profile validation
- [ORA-RT-001](#ora-rt-001) — 2.1.1 ORA-RT-001 Expected result
- [TST-RT-002](#tst-rt-002) — 2.2 TST-RT-002 Context routing
- [ORA-RT-002](#ora-rt-002) — 2.2.1 ORA-RT-002 Expected result
- [TST-RT-003](#tst-rt-003) — 2.3 TST-RT-003 Document owner validation
- [ORA-RT-003](#ora-rt-003) — 2.3.1 ORA-RT-003 Expected result
- [TST-RT-004](#tst-rt-004) — 2.4 TST-RT-004 Feature branch base selection
- [ORA-RT-004](#ora-rt-004) — 2.4.1 ORA-RT-004 Expected result
- [TST-RT-005](#tst-rt-005) — 2.5 TST-RT-005 Expected base SHA mismatch
- [ORA-RT-005](#ora-rt-005) — 2.5.1 ORA-RT-005 Expected result
- [TST-RT-006](#tst-rt-006) — 2.6 TST-RT-006 Workspace binding
- [ORA-RT-006](#ora-rt-006) — 2.6.1 ORA-RT-006 Expected result
- [TST-RT-007](#tst-rt-007) — 2.7 TST-RT-007 Review PR retry/readback
- [ORA-RT-007](#ora-rt-007) — 2.7.1 ORA-RT-007 Expected result
- [TST-RT-008](#tst-rt-008) — 2.8 TST-RT-008 Contract byte identity
- [ORA-RT-008](#ora-rt-008) — 2.8.1 ORA-RT-008 Expected result
- [TST-RT-009](#tst-rt-009) — 2.9 TST-RT-009 Contract execution authority
- [ORA-RT-009](#ora-rt-009) — 2.9.1 ORA-RT-009 Expected result
- [TST-RT-010](#tst-rt-010) — 2.10 TST-RT-010 Review and delivery evidence
- [ORA-RT-010](#ora-rt-010) — 2.10.1 ORA-RT-010 Expected result
- [TST-RT-011](#tst-rt-011) — 2.11 TST-RT-011 Failure, logging, and cleanup
- [ORA-RT-011](#ora-rt-011) — 2.11.1 ORA-RT-011 Expected result
- [TST-RT-012](#tst-rt-012) — 2.12 TST-RT-012 Observable CLI results
- [ORA-RT-012](#ora-rt-012) — 2.12.1 ORA-RT-012 Expected result
- [TST-RT-013](#tst-rt-013) — 2.13 TST-RT-013 Data and API formats
- [ORA-RT-013](#ora-rt-013) — 2.13.1 ORA-RT-013 Expected result
- [TST-RT-014](#tst-rt-014) — 2.14 TST-RT-014 Security and privacy
- [ORA-RT-014](#ora-rt-014) — 2.14.1 ORA-RT-014 Expected result
- [TST-RT-015](#tst-rt-015) — 2.15 TST-RT-015 Error and boundary cases
- [ORA-RT-015](#ora-rt-015) — 2.15.1 ORA-RT-015 Fail-closed result
- [TST-RT-016](#tst-rt-016) — 2.16 TST-RT-016 Effective branch-policy assessment
- [ORA-RT-016](#ora-rt-016) — 2.16.1 ORA-RT-016 Expected result
- [TST-RT-017](#tst-rt-017) — 2.17 TST-RT-017 Canonical plan and write boundary
- [ORA-RT-017](#ora-rt-017) — 2.17.1 ORA-RT-017 Expected result
- [TST-RT-018](#tst-rt-018) — 2.18 TST-RT-018 Temporary child-process credential isolation
- [ORA-RT-018](#ora-rt-018) — 2.18.1 ORA-RT-018 Expected result
- [TST-RT-019](#tst-rt-019) — 2.19 TST-RT-019 Delegated owner decision record and replay protection
- [ORA-RT-019](#ora-rt-019) — 2.19.1 ORA-RT-019 Expected result
<!-- heading-map:end -->


<a id="test-purpose"></a>
## 1 Test purpose

Define reproducible conditions and expected results independently of implementation details.

<a id="test-conditions-and-oracles"></a>
## 2 Test conditions and oracles

<a id="tst-rt-001"></a>
<a id="tst-rt-001-project-profile-validation"></a>
### 2.1 TST-RT-001 Project profile validation

**Setup and action:** Run `project status` with a valid, missing, and malformed `.agent/project.json` profile; inspect repository files before and after each invocation.

<a id="ora-rt-001"></a>
<a id="ora-rt-001-expected-result"></a>
#### 2.1.1 ORA-RT-001 Expected result

The valid profile reports `READY`; missing or malformed profiles report `UNAVAILABLE` with nonzero status. No case creates, repairs, or rewrites profile state.

<a id="tst-rt-002"></a>
<a id="tst-rt-002-context-routing"></a>
### 2.2 TST-RT-002 Context routing

**Setup and action:** Run `context show` for open, closed, and missing Issues; approved, unapproved, stale, or unverifiable ADC pointers; and absent, valid, stale, or malformed frozen bindings.

<a id="ora-rt-002"></a>
<a id="ora-rt-002-expected-result"></a>
#### 2.2.1 ORA-RT-002 Expected result

Results expose bounded identity and digest fields without issue/comment bodies or workspace paths. Every case is read-only and does not re-resolve a frozen base or create a binding.

<a id="tst-rt-003"></a>
<a id="tst-rt-003-document-owner-validation"></a>
### 2.3 TST-RT-003 Document owner validation

**Setup and action:** Run `docs validate` on valid, wrong-tree, missing, and malformed local document links, then run `docs format --check` on clean and drifted documents.

<a id="ora-rt-003"></a>
<a id="ora-rt-003-expected-result"></a>
#### 2.3.1 ORA-RT-003 Expected result

Valid docs pass; broken links and traceability fail with bounded errors. Format check reports drift without changing bytes.

<a id="tst-rt-004"></a>
<a id="tst-rt-004-feature-branch-base-selection"></a>
### 2.4 TST-RT-004 Feature branch base selection

**Setup and action:** Use `work base` and `work branch` with a valid same-repository base, then an invalid or foreign branch.

<a id="ora-rt-004"></a>
<a id="ora-rt-004-expected-result"></a>
#### 2.4.1 ORA-RT-004 Expected result

The exact selected ref is retained and an invalid selection is rejected before branch mutation.

<a id="tst-rt-005"></a>
<a id="tst-rt-005-expected-base-sha-mismatch"></a>
### 2.5 TST-RT-005 Expected base SHA mismatch

**Setup and action:** Advance the remote base after the caller records its expected full SHA.

<a id="ora-rt-005"></a>
<a id="ora-rt-005-expected-result"></a>
#### 2.5.1 ORA-RT-005 Expected result

Resolution fails closed and leaves the current branch, worktree, hooks, and binding untouched.

<a id="tst-rt-006"></a>
<a id="tst-rt-006-workspace-binding"></a>
### 2.6 TST-RT-006 Workspace binding

**Setup and action:** Use `work bind` and `work recover` with valid, mismatched, and stale binding subjects.

<a id="ora-rt-006"></a>
<a id="ora-rt-006-expected-result"></a>
#### 2.6.1 ORA-RT-006 Expected result

A binding is created only for the validated clean workspace and exact base; existing valid bindings are reused.

<a id="tst-rt-007"></a>
<a id="tst-rt-007-review-pr-retryreadback"></a>
### 2.7 TST-RT-007 Review PR retry/readback

**Setup and action:** Simulate no candidate, one matching open PR, an ambiguous result, and a lost create response.

<a id="ora-rt-007"></a>
<a id="ora-rt-007-expected-result"></a>
#### 2.7.1 ORA-RT-007 Expected result

Creation is followed by exact API readback; retries reuse one matching PR and ambiguity never creates duplicates.

<a id="tst-rt-008"></a>
<a id="tst-rt-008-contract-byte-identity"></a>
### 2.8 TST-RT-008 Contract byte identity

**Setup and action:** Validate, publish, verify, and restore a bounded ADC payload with exact bytes and named comment readback.

<a id="ora-rt-008"></a>
<a id="ora-rt-008-expected-result"></a>
#### 2.8.1 ORA-RT-008 Expected result

The approved comment ID/SHA and bytes match; invalid or changed pointers fail without overwriting verified content.

<a id="tst-rt-009"></a>
<a id="tst-rt-009-contract-execution-authority"></a>
### 2.9 TST-RT-009 Contract execution authority

**Setup and action:** Exercise a current approved ADC, a superseded ADC, and an unapproved ADC through context and work readiness routes.

<a id="ora-rt-009"></a>
<a id="ora-rt-009-expected-result"></a>
#### 2.9.1 ORA-RT-009 Expected result

Only the exact current approved ADC authorizes implementation work; no caller boolean substitutes for approval.

<a id="tst-rt-010"></a>
<a id="tst-rt-010-review-and-delivery-evidence"></a>
### 2.10 TST-RT-010 Review and delivery evidence

**Setup and action:** Supply current and stale Verification, Acceptance, self-Audit, independent review, User Review, and Required Check records to the delivery gate.

<a id="ora-rt-010"></a>
<a id="ora-rt-010-expected-result"></a>
#### 2.10.1 ORA-RT-010 Expected result

Delivery accepts only records bound to the same current PR HEAD and keeps missing or stale gates visible. It performs no merge.

<a id="tst-rt-011"></a>
<a id="tst-rt-011-failure-logging-and-cleanup"></a>
### 2.11 TST-RT-011 Failure, logging, and cleanup

**Setup and action:** Trigger process timeout, hook failure, GitHub failure, and atomic-write failure.

<a id="ora-rt-011"></a>
<a id="ora-rt-011-expected-result"></a>
#### 2.11.1 ORA-RT-011 Expected result

Secrets are redacted, temporary files are cleaned, and prior verified state remains intact.

<a id="tst-rt-012"></a>
<a id="tst-rt-012-observable-cli-results"></a>
### 2.12 TST-RT-012 Observable CLI results

**Setup and action:** Run `python -m p_ases --help`, inspect all 12 namespaces, and submit malformed/incomplete namespaced route inputs.

<a id="ora-rt-012"></a>
<a id="ora-rt-012-expected-result"></a>
#### 2.12.1 ORA-RT-012 Expected result

All 12 namespaces are present, retired flat commands are absent, and invalid route inputs fail with nonzero status.

<a id="tst-rt-013"></a>
<a id="tst-rt-013-data-and-api-formats"></a>
### 2.13 TST-RT-013 Data and API formats

**Setup and action:** Round-trip supported JSON payloads and reject unknown required fields or malformed API shapes.

<a id="ora-rt-013"></a>
<a id="ora-rt-013-expected-result"></a>
#### 2.13.1 ORA-RT-013 Expected result

Canonical schemas round-trip deterministically; incomplete transport responses fail closed.

<a id="tst-rt-014"></a>
<a id="tst-rt-014-security-and-privacy"></a>
### 2.14 TST-RT-014 Security and privacy

**Setup and action:** Inspect logs and persisted runtime state after fake API failures and validation errors.

<a id="ora-rt-014"></a>
<a id="ora-rt-014-expected-result"></a>
#### 2.14.1 ORA-RT-014 Expected result

No credentials or Issue bodies are emitted, and local state stays scoped to its owner.

<a id="tst-rt-015"></a>
<a id="tst-rt-015-error-and-boundary-cases"></a>
### 2.15 TST-RT-015 Error and boundary cases

**Setup and action:** Submit missing, malformed, stale, wrong-repository, and ambiguous inputs to their public runtime commands.

<a id="ora-rt-015"></a>
<a id="ora-rt-015-fail-closed-result"></a>
#### 2.15.1 ORA-RT-015 Fail-closed result

Every invalid boundary returns a nonzero bounded error before an unrelated local or GitHub mutation.

<a id="tst-rt-016"></a>
### 2.16 TST-RT-016 Effective branch-policy assessment

**Setup and action:** Feed `assess_branch_policy` branch, legacy protection, effective rules, and Ruleset detail fixtures for exact `solo_owner` and `external_reviewer` policies. Vary missing sources, HTTP 403/404, duplicate Ruleset IDs/rules, branch scope, enforcement, source, bypass actors, Required Check contexts and App IDs, approval count, and force-push rule. Include legacy approvals of one with a valid `solo_owner` Ruleset requiring zero.

<a id="ora-rt-016"></a>
#### 2.16.1 ORA-RT-016 Expected result

Policy status distinguishes `VERIFIED`, `NOT_CONFIGURED`, `UNAVAILABLE`, `UNVERIFIED`, and `MISMATCH` without treating forbidden reads as missing settings. Required Checks compare exact context/App ID pairs. A known legacy approval requirement remains an independent constraint and conflicting legacy/Ruleset values produce `MISMATCH`.

<a id="tst-rt-017"></a>
### 2.17 TST-RT-017 Canonical plan and write boundary

**Setup and action:** Build plans from fake GitHub responses and validate canonical plan digest round trips. Mutate every bound identity/evidence field, including the configured Activation Issue and predecessor. Simulate one POST, one PUT, no-op, process death after successful POST/PUT, exact retry recovery, an unowned same-name Ruleset without intent, lost responses, direct/list/direct approval mismatch, and corruption after an exact V2 applied-record prefix. Inspect the fake transport's complete request sequence.

<a id="ora-rt-017"></a>
#### 2.17.1 ORA-RT-017 Expected result

Plan digests change when any bound input changes. Only an exact, owner-authored approval on the configured Activation Issue can reach the one managed Ruleset write. A durable intent recovers the same exact Ruleset and approval after process death without a second POST/PUT; without intent, an unowned same-name Ruleset is rejected. Historical V2 verification reads only through its bound applied-record ID while new issuance validates the full history. Every ambiguous write result performs reads only and never triggers a second POST/PUT or rollback.

<a id="tst-rt-018"></a>
### 2.18 TST-RT-018 Temporary child-process credential isolation

**Setup and action:** Use a fake GitHub API executable and subprocess recorder to inspect every argument, environment mapping, output stream, and client state. Enter a marker credential through the injectable owner-controlled TTY input boundary. Vary preexisting `GH_TOKEN`, `GITHUB_TOKEN`, and enterprise token variables; successful and failed API requests; `getpass` cancellation; exceptions and interruption during POST/PUT; sequential admin-plan/admin-apply clients; and an ordinary `GitHub` client after the session. Assert that the bootstrap Admin commands require a separate owner-operated interactive local TTY, return `ADMIN_AUTH_INTERACTIVE_REQUIRED` in Cloud/non-TTY contexts before reading credentials or making requests, and have no Codex Cloud Browser/automation fallback. Inspect `os.environ`, unrelated child environments, persisted files, logs, and object representation before, during, and after the session.

<a id="ora-rt-018"></a>
#### 2.18.1 ORA-RT-018 Expected result

Only the `gh api` child process for the active authenticated client receives the temporary credential via its designated child environment. Conflicting token variables do not override it. The token never appears in argv, logs, JSON, files, object representation, `os.environ`, another subprocess, or later ordinary requests. Normal return, API error, exception, and interruption clear the client override; Python-memory erasure is not asserted. Cancellation or non-TTY/Cloud Browser context makes no API request and does not prompt. An interrupted write follows the existing durable-intent recovery contract and does not trigger a second POST/PUT.

<a id="tst-rt-019"></a>
### 2.19 TST-RT-019 Delegated owner decision record and replay protection

**Setup and action:** Feed canonical `delegated_github_relay` records for `PHASE_REBASE`, `ADC_SUPERSEDE`, `RULESET_PLAN_APPLY`, and `PR_MERGE` through the parser and verifier. Vary schema fields, stable GitHub actor ID, operation, repository, Issue/PR, subject SHA/HEAD, evidence channel, and predecessor/comment IDs. Test direct/list/direct comment readback, edited or deleted records, monotonic and duplicate IDs, repeated operation/subject pairs, mismatched decision scopes, interrupted record publication, and retry after exact durable readback. Verify that the isolated relay writes only after exact-subject readback and direct chat confirmation, and that the implementation runtime has no relay credential or write-capable route; an unavailable or unverifiable broker/runtime boundary blocks before mutation. Runtime evidence must not claim a host signature. For self-authored `solo_owner` PRs, verify `PASES_USER_REVIEW_DECISION_V1` parsing and readback against the exact repository, Issue, PR, stable owner ID, immutable session ID, Readiness digest, ADC digest, and current PR HEAD. Reject formal self-approval, ordinary `PASES_OWNER_DECISION_V1`, other schemas, changed or missing fields, duplicates, stale subjects, edits, deletions, and cross-session replay. After a distinct direct confirmation, verify exactly one append-only owner record reaches the ordinary feedback evaluator. For eligible external reviewers, retain the native formal `APPROVED` review path. Use fake GitHub clients and assert method counts and payload bytes.

<a id="ora-rt-019"></a>
#### 2.19.1 ORA-RT-019 Expected result

Each verifier accepts only its canonical evidence schema and current subject. The four ordinary relay operations require a delegated record with stable owner ID, evidence channel, exact operation scope, and predecessor sequence. The isolated broker writes once after exact-subject readback and direct chat confirmation; unchanged direct/list/direct readback is required before the scoped action proceeds. Replays, duplicate operation/subject pairs, stale or mismatched subjects, invalid predecessors, edits/deletions, and ambiguous write outcomes fail closed without another mutation. Records are delegated GitHub evidence, not host attestations. The implementation runtime has no relay write credential/route, and inability to establish that boundary blocks. For self-authored `solo_owner` PRs, User Review uses only a canonical `PASES_USER_REVIEW_DECISION_V1` record bound to the stable owner, exact repository/Issue/PR, immutable session ID, Readiness digest, ADC digest, and current HEAD; formal self-approval and ordinary owner-decision records are rejected. Eligible external reviewers continue to use native formal reviews. Feedback and resolved-thread checks remain mandatory. All decisions remain independent.
