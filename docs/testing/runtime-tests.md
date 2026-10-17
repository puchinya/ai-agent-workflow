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
  - [2.19 TST-RT-019 Exact chat approval, V3 history, and transport boundary](#219-tst-rt-019-exact-chat-approval-v3-history-and-transport-boundary)
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
- [TST-RT-019](#tst-rt-019) — 2.19 TST-RT-019 Exact chat approval, V3 history, and transport boundary
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

**Setup and action:** Build plans from fake GitHub responses and validate canonical plan digest round trips. Mutate every bound identity/evidence field, including repository/owner IDs, configured Activation Issue, ADC generation, setup-branch commit/generation, profile ref/digest, predecessor, and policy evidence. Verify a V2 plan may consume only its exact remote setup-branch HEAD and that `apply_ruleset_plan` rejects a file changed after owner-decision verification. Simulate one POST, one PUT, zero-write NOOP, process death after successful POST/PUT, exact retry recovery, an unowned same-name Ruleset without intent, lost responses, direct/list/direct approval mismatch, an old policy-bound open setup PR followed by a new branch/plan/PR generation, and corruption after an exact V2 applied-record prefix. Verify external-reviewer inventory marks solo-owner policy `UNSUPPORTED` but blocks missing required checks. Inspect the fake transport's complete request sequence.

<a id="ora-rt-017"></a>
#### 2.17.1 ORA-RT-017 Expected result

Plan digests change when any bound input changes, including setup generation. Activation does not create a V2 setup PR before policy verification. If an existing proposal's immutable policy binding is stale, the old PR stays unchanged and a new setup branch, plan, and PR bind the current policy. Only a fresh exact `RULESET_PLAN_APPLY` V3 chat-confirmed decision plus the owner-authenticated two-line Issue #57 approval can reach the single managed Ruleset writer. A durable intent recovers the same exact Ruleset and approval after process death without a second POST/PUT; without intent, an unowned same-name Ruleset is rejected. An exact owned policy performs no write and requires no write approval. Historical V2 verification reads only through its bound applied-record ID while new issuance validates the full history. External-reviewer V1 reports the complete inventory and cannot be ACTIVE with missing required checks. Every ambiguous write result performs reads only and never triggers a second POST/PUT or rollback.

<a id="tst-rt-018"></a>
### 2.18 TST-RT-018 Temporary child-process credential isolation

**Setup and action:** Use fake `gh` children and a subprocess recorder to inspect every argument, environment mapping, output stream, and client state. Device auth is the default: fake successful and failed `gh auth login` calls, verify the exact argv, mode-0700 one-time `GH_CONFIG_DIR`, runner-managed PTY display of the challenge, host permission-verification failure, later API use of the same directory, and cleanup on normal return, exception, SIGINT, and handled SIGTERM. For explicit nonstandard `pat` fallback, enter a marker credential through the injectable owner-controlled TTY input boundary. Vary all four standard/enterprise token variables and the parent `GH_CONFIG_DIR`; assert they are removed from isolated children and parent/default `gh` state is byte-for-byte unchanged. Cover identity/admin mismatch, 403, stale plan and failed device login as zero Ruleset writes, plus ambiguous request recovery as read-only. In a Cloud-like environment, permit the runner-managed PTY to display a device challenge without requiring an owner-local TTY; if that capability is unavailable, assert `ADMIN_DEVICE_LOGIN_UNAVAILABLE` without an Admin API call. Inspect `os.environ`, unrelated child environments, temporary files, logs, and object representation before, during, and after both modes.

<a id="ora-rt-018"></a>
#### 2.18.1 ORA-RT-018 Expected result

Only the `gh api` child process for the active authenticated client receives the Admin authentication context: PAT fallback uses its designated child-only token override; device mode uses its private per-command `GH_CONFIG_DIR`, with ambient token variables removed. The normal parent `gh` environment, configuration, and unrelated children remain unchanged. PAT bytes never appear in argv, logs, JSON, files, object representation, `os.environ`, another subprocess, or later ordinary requests. The device OAuth token exists only in its private temporary GitHub CLI config while the session is active; cleanup removes that directory but does not revoke the GitHub-side grant. Device login uses a runner-managed interactive PTY when required and does not require an owner-local TTY. It never silently falls back. If the runner cannot present the challenge, return `ADMIN_DEVICE_LOGIN_UNAVAILABLE` and make no Admin API request. Normal return, API error, exception, SIGINT, and handled SIGTERM clear client bindings and remove only the private device config. Same-OS-user subprocesses are not a strong sandbox. Identity/admin mismatch, 403, stale plan, and unavailable device login cause zero Ruleset writes; an interrupted or ambiguous write follows durable-intent recovery and never triggers a second POST/PUT.

<a id="tst-rt-019"></a>
### 2.19 TST-RT-019 Exact chat approval, V3 history, and transport boundary

Test V1 delegated, V2 owner-local TTY, and V3 `chat_confirmed_gh_v1` as immutable schemas in one predecessor chain. V3 ordinary and User Review bodies must bind exact repository/Issue/operation/subject, plan SHA, approval-scope SHA, optional PR/HEAD, owner actor, channel, and immediate predecessor. Verify canonical bytes, stable owner ID 3744776, repository ID 1401910271, actual `url`/`issue_url`/`html_url`, created=updated, complete pagination and direct/list/direct equality. Reject wrong actor/source, unknown channel/field, changed scope, duplicate/replay across versions, stale subject, missing page, edit/deletion and broken predecessor. Preserve V1/V2 bytes and PRBinding V1.

Verify the transport boundary separately: GitHub API resources (Issues, PRs, comments, reviews, checks, Actions, Rulesets, policy, merge, labels and closure) must go through `gh` in `github.py`; request JSON uses `--input -` stdin and no SDK, connector or direct HTTP is called. Repository fetch/push and remote-ref/object readback use only the existing Git boundary and Git commands. Assert no Git command is used as a substitute for GitHub API state, and no API writer is added outside `github.py`.

`capture_direct_chat_confirmation` accepts only a direct current user-role approval in the same conversation and only for the exact displayed scope. Test explicit approval success; vague “continue”, assistant-authored text, wrong role, different conversation, stale ADC/plan/PR HEAD, changed wording/scope, and non-owner GitHub actor must make zero GitHub writes. The scope digest is not a chat signature. If the host cannot provide the direct role event, assert `CHAT_PROVENANCE_UNAVAILABLE`. The CLI `owner-authorize-commit` must fail closed and must not read stdin, accept `--approved`, or accept a consent file. The in-process hook must re-read live subjects and authenticated owner before a single V3 append; lost POST is read-only recovery with no second POST.

For `RULESET_PLAN_APPLY`, require a blocker-free canonical plan and exact V3 approval; then append/read back the existing exact two-line Issue #57 comment from owner ID 3744776. Assert wrong Issue/repository/actor/body, duplicate/missing approval, stale plan, and 403 cause zero Ruleset writes. Exact owned policy remains a zero-write NOOP and the existing canonical writer/durable intent remains unique.

For V3 `USER_REVIEW`, bind session, Readiness, ADC, exact PR HEAD, prior full feedback digest, plan and scope digests. Verify null genesis, immediate predecessor, strict `created_at > started_at`, unchanged timestamps, direct/list/direct URLs and distinct read-only verifier identity. The evaluator accepts only a typed V3 carrier; current feedback excluding that carrier must equal the bound prior digest, all surfaces must be read, and no unresolved thread/later feedback may remain. Persist V3 selected evidence in `PASES_USER_REVIEW_RESULT_V2`; Final Delivery re-reads full history and snapshot and reproduces the exact result. Reject wrong actor/author/owner, stale or changed scope, self-approval, edits/deletions, incomplete pagination, replay, and unresolved threads.

For PR merge, keep separate exact-HEAD grants for the Issue #57 Setup PR and PR #64. Test stale HEAD, failed current gates, wrong PR/repository/target and non-owner actor as zero merge requests. Simulate lost merge response; durable attempt and read-only resume must never issue a second request. The Phase bootstrap remains automatic after approved ADC and uses only technical Intent/Applied evidence with at most one label PUT.

<a id="ora-rt-019"></a>
#### 2.19.1 ORA-RT-019 Expected result

Only a direct same-conversation explicit user-role event bound to the current exact scope can produce an operator-reported V3 grant. The runtime reports `chat_confirmed_gh_v1` without claiming a signed chat attestation. Owner and repository IDs, actual GitHub actor, comment URLs, operation and predecessor are independently checked; the read-only verifier principal may differ from the pinned owner. CLI/flags/files/vague continuation cannot authorize a write. If user-role provenance is unavailable, V3 is unavailable and no carrier is written. V1/V2 remain read-compatible and unmodified.

V3 User Review enters the complete-session/snapshot evaluator and carries exact session, Readiness, ADC, HEAD, prior feedback, plan and scope. Final Delivery re-reads the complete chain and snapshot. Ruleset requires both the V3 exact-plan owner record and exact #57 two-line comment. Setup PR and PR #64 decisions remain separate exact-HEAD authorizations. Merge is unavailable until Required Checks, independent review, User Review, Final Delivery and Activation V2 gates pass. Phase bootstrap remains automatic after approved ADC publication with Intent/Applied only.
