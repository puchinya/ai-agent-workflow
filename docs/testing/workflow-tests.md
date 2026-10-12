<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Test Specification

- Status: Approved
- Owning specification: ../specs/

<!-- contents:start -->
**Contents**
- [1 Test purpose](#1-test-purpose)
- [2 Test conditions and oracles](#2-test-conditions-and-oracles)
  - [2.1 TST-WF-001 Issue authority and artifact ownership](#21-tst-wf-001-issue-authority-and-artifact-ownership)
    - [2.1.1 ORA-WF-001 Expected result](#211-ora-wf-001-expected-result)
  - [2.2 TST-WF-002 Exact-base workspace continuation](#22-tst-wf-002-exact-base-workspace-continuation)
    - [2.2.1 ORA-WF-002 Expected result](#221-ora-wf-002-expected-result)
  - [2.3 TST-WF-003 Authorization continuity boundary](#23-tst-wf-003-authorization-continuity-boundary)
    - [2.3.1 ORA-WF-003 Expected result](#231-ora-wf-003-expected-result)
  - [2.4 TST-WF-004 Triggered Skill loading](#24-tst-wf-004-triggered-skill-loading)
    - [2.4.1 ORA-WF-004 Expected result](#241-ora-wf-004-expected-result)
  - [2.5 TST-WF-005 Independent review and delivery gates](#25-tst-wf-005-independent-review-and-delivery-gates)
    - [2.5.1 ORA-WF-005 Expected result](#251-ora-wf-005-expected-result)
  - [2.6 TST-WF-006 Portable host behavior](#26-tst-wf-006-portable-host-behavior)
    - [2.6.1 ORA-WF-006 Expected result](#261-ora-wf-006-expected-result)
  - [2.7 TST-WF-007 Malformed inputs and failures](#27-tst-wf-007-malformed-inputs-and-failures)
    - [2.7.1 ORA-WF-007 Expected result](#271-ora-wf-007-expected-result)
  - [2.8 TST-WF-008 Security boundary](#28-tst-wf-008-security-boundary)
    - [2.8.1 ORA-WF-008 Expected result](#281-ora-wf-008-expected-result)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [TST-WF-001](#tst-wf-001) — 2.1 TST-WF-001 Issue authority and artifact ownership
- [ORA-WF-001](#ora-wf-001) — 2.1.1 ORA-WF-001 Expected result
- [TST-WF-002](#tst-wf-002) — 2.2 TST-WF-002 Exact-base workspace continuation
- [ORA-WF-002](#ora-wf-002) — 2.2.1 ORA-WF-002 Expected result
- [TST-WF-003](#tst-wf-003) — 2.3 TST-WF-003 Authorization continuity boundary
- [ORA-WF-003](#ora-wf-003) — 2.3.1 ORA-WF-003 Expected result
- [TST-WF-004](#tst-wf-004) — 2.4 TST-WF-004 Triggered Skill loading
- [ORA-WF-004](#ora-wf-004) — 2.4.1 ORA-WF-004 Expected result
- [TST-WF-005](#tst-wf-005) — 2.5 TST-WF-005 Independent review and delivery gates
- [ORA-WF-005](#ora-wf-005) — 2.5.1 ORA-WF-005 Expected result
- [TST-WF-006](#tst-wf-006) — 2.6 TST-WF-006 Portable host behavior
- [ORA-WF-006](#ora-wf-006) — 2.6.1 ORA-WF-006 Expected result
- [TST-WF-007](#tst-wf-007) — 2.7 TST-WF-007 Malformed inputs and failures
- [ORA-WF-007](#ora-wf-007) — 2.7.1 ORA-WF-007 Expected result
- [TST-WF-008](#tst-wf-008) — 2.8 TST-WF-008 Security boundary
- [ORA-WF-008](#ora-wf-008) — 2.8.1 ORA-WF-008 Expected result
<!-- heading-map:end -->


<a id="test-purpose"></a>
## 1 Test purpose

Define reproducible conditions and expected results independently of implementation details.

<a id="test-conditions-and-oracles"></a>
## 2 Test conditions and oracles

<a id="tst-wf-001"></a>
<a id="tst-wf-001-issue-authority-and-artifact-ownership"></a>
### 2.1 TST-WF-001 Issue authority and artifact ownership

**Setup and action:** Create an open Issue with specification/design/status impact decisions; route implementation context.

<a id="ora-wf-001"></a>
<a id="ora-wf-001-expected-result"></a>
#### 2.1.1 ORA-WF-001 Expected result

Only declared owners are routed; unchanged and evidence-only decisions create no missing-owner error.

<a id="tst-wf-002"></a>
<a id="tst-wf-002-exact-base-workspace-continuation"></a>
### 2.2 TST-WF-002 Exact-base workspace continuation

**Setup and action:** Bind an execution to a selected base SHA, advance its remote branch, then recover the same PR continuation.

<a id="ora-wf-002"></a>
<a id="ora-wf-002-expected-result"></a>
#### 2.2.1 ORA-WF-002 Expected result

The frozen base tuple is reused; dirty, mismatched, or wrong-base workspaces fail before source mutation.

<a id="tst-wf-003"></a>
<a id="tst-wf-003-authorization-continuity-boundary"></a>
### 2.3 TST-WF-003 Authorization continuity boundary

**Setup and action:** Run an approved Issue-scoped implementation through PR establishment, then request a destructive merge action.

<a id="ora-wf-003"></a>
<a id="ora-wf-003-expected-result"></a>
#### 2.3.1 ORA-WF-003 Expected result

Routine commit/push/PR handoff can proceed; merge, release, force-push, and unrelated mutation remain outside the authority.

<a id="tst-wf-004"></a>
<a id="tst-wf-004-triggered-skill-loading"></a>
### 2.4 TST-WF-004 Triggered Skill loading

**Setup and action:** Compare canonical Skill directories with generated OpenAI, Claude, and Antigravity package directories after a build.

<a id="ora-wf-004"></a>
<a id="ora-wf-004-expected-result"></a>
#### 2.4.1 ORA-WF-004 Expected result

Each source and generated host package contains exactly the canonical 16 Skills with matching `SKILL.md` files; no deprecated Skill alias is present.

<a id="tst-wf-005"></a>
<a id="tst-wf-005-independent-review-and-delivery-gates"></a>
### 2.5 TST-WF-005 Independent review and delivery gates

**Setup and action:** Evaluate a current PR with a pending required check and no merge authorization.

<a id="ora-wf-005"></a>
<a id="ora-wf-005-expected-result"></a>
#### 2.5.1 ORA-WF-005 Expected result

Delivery remains blocked on required evidence/checks and never merges the PR.

<a id="tst-wf-006"></a>
<a id="tst-wf-006-portable-host-behavior"></a>
### 2.6 TST-WF-006 Portable host behavior

**Setup and action:** Build and inspect the host packages from common workflow sources.

<a id="ora-wf-006"></a>
<a id="ora-wf-006-expected-result"></a>
#### 2.6.1 ORA-WF-006 Expected result

Shared workflow semantics are preserved while host-specific manifests and resource paths stay isolated.

<a id="tst-wf-007"></a>
<a id="tst-wf-007-malformed-inputs-and-failures"></a>
### 2.7 TST-WF-007 Malformed inputs and failures

**Setup and action:** Supply an invalid profile, malformed impact declaration, and ambiguous GitHub state.

<a id="ora-wf-007"></a>
<a id="ora-wf-007-expected-result"></a>
#### 2.7.1 ORA-WF-007 Expected result

Each invalid case fails closed before hooks or unrelated mutation and reports its owning boundary.

<a id="tst-wf-008"></a>
<a id="tst-wf-008-security-boundary"></a>
### 2.8 TST-WF-008 Security boundary

**Setup and action:** Exercise invalid local paths and simulated API/process errors using fake transports.

<a id="ora-wf-008"></a>
<a id="ora-wf-008-expected-result"></a>
#### 2.8.1 ORA-WF-008 Expected result

Paths cannot escape the repo, credentials are not printed, and no network/service fallback is introduced.
