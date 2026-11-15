<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Specification

- Status: Issue #63 is OPEN at `phase:requirements`. Current approved ADC comment #6471580482 has SHA-256 `22ec1585a11d9a791eaf9b0e89baf604775e5168b3f5844a290485a7aab5d218`; its Phase V2 Intent/Applied pair is #6472026312/#6472411402. The V3 recovery generations remain #6469356263/#6469538910 and #6469619562/#6470070164. PR #64 HEAD immediately before this documentation update was `5d1267f1ba436d3681ea261372aca6ea084a757e`; it had no current-head Independent Review V2, Readiness PASS, or User Review record. These changes require fresh exact-HEAD evidence.
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related design: [Workflow design](../design/workflow-design.md)
- Runtime contract: [Runtime specification](runtime-spec.md)

<!-- contents:start -->
**Contents**
- [1 Purpose](#1-purpose)
- [2 Scope](#2-scope)
- [3 Normative requirements](#3-normative-requirements)
  - [3.1 REQ-WF-001 Workflow phases](#31-req-wf-001-workflow-phases)
  - [3.2 REQ-WF-002 Host-managed implementation workspaces](#32-req-wf-002-host-managed-implementation-workspaces)
  - [3.3 REQ-WF-003 Authorization continuity and implementation handoff](#33-req-wf-003-authorization-continuity-and-implementation-handoff)
  - [3.4 REQ-WF-004 Skills](#34-req-wf-004-skills)
  - [3.5 REQ-WF-005 Review and delivery principles](#35-req-wf-005-review-and-delivery-principles)
- [4 REQ-WF-006 Observable behavior](#4-req-wf-006-observable-behavior)
- [5 REQ-WF-007 Error and boundary behavior](#5-req-wf-007-error-and-boundary-behavior)
- [6 REQ-WF-008 Security and privacy](#6-req-wf-008-security-and-privacy)
- [7 P-ASES migration Bootstrap gates](#7-p-ases-migration-bootstrap-gates)
- [8 P-ASES human review and final delivery](#8-p-ases-human-review-and-final-delivery)
  - [8.1 REQ-WF-009 Exact-subject User Review](#81-req-wf-009-exact-subject-user-review)
  - [8.2 REQ-WF-010 Parent Integration and Final Delivery](#82-req-wf-010-parent-integration-and-final-delivery)
- [9 Consumer Activation workflow contract](#9-consumer-activation-workflow-contract)
  - [9.1 REQ-F01-001 Repository boundary](#91-req-f01-001-repository-boundary)
  - [9.2 REQ-F01-003 Append-only approval and Activation history](#92-req-f01-003-append-only-approval-and-activation-history)
  - [9.3 REQ-F01-005 Eligibility by Activation time](#93-req-f01-005-eligibility-by-activation-time)
  - [9.4 REQ-F01-007 Successor Activation](#94-req-f01-007-successor-activation)
  - [9.5 REQ-F01-008 Verified V2 Activation policy](#95-req-f01-008-verified-v2-activation-policy)
  - [9.6 REQ-F01-009 Approved Ruleset management](#96-req-f01-009-approved-ruleset-management)
  - [9.7 REQ-F01-010 Existing Issue preservation](#97-req-f01-010-existing-issue-preservation)
  - [9.8 REQ-F01-011 V2 effective time](#98-req-f01-011-v2-effective-time)
  - [9.9 REQ-F01-012 Activation history prefix](#99-req-f01-012-activation-history-prefix)
  - [9.10 REQ-F01-013 Bootstrap and review gates](#910-req-f01-013-bootstrap-and-review-gates)
  - [9.11 REQ-F01-014 Activation-scoped temporary admin authentication](#911-req-f01-014-activation-scoped-temporary-admin-authentication)
  - [9.12 REQ-F01-015 Owner-authorized decisions and separated operations](#912-req-f01-015-owner-authorized-decisions-and-separated-operations)
  - [9.13 REQ-F01-016 Native Independent Review execution and confidence](#913-req-f01-016-native-independent-review-execution-and-confidence)
  - [9.14 REQ-F01-018 Exact Phase evidence recovery](#914-req-f01-018-exact-phase-evidence-recovery)
  - [9.15 REQ-F01-031 Generic Phase restart authorization](#915-req-f01-031-generic-phase-restart-authorization)
  - [9.16 REQ-F01-032 Eligible Issue and Binding](#916-req-f01-032-eligible-issue-and-binding)
  - [9.17 REQ-F01-033 Append-only Phase restart records](#917-req-f01-033-append-only-phase-restart-records)
  - [9.18 REQ-F01-034 One-shot label transition and recovery](#918-req-f01-034-one-shot-label-transition-and-recovery)
  - [9.19 REQ-F01-035 Active Phase generation](#919-req-f01-035-active-phase-generation)
  - [9.20 REQ-F01-036 Issue #63 compatibility](#920-req-f01-036-issue-63-compatibility)
  - [9.21 REQ-F01-037 ADC is the sole Phase restart approval](#921-req-f01-037-adc-is-the-sole-phase-restart-approval)
  - [9.22 REQ-F01-038 Missing historical Binding provenance](#922-req-f01-038-missing-historical-binding-provenance)
  - [9.23 REQ-F01-039 One-time epoch authorization](#923-req-f01-039-one-time-epoch-authorization)
  - [9.24 REQ-F01-040 Append-only epoch journal](#924-req-f01-040-append-only-epoch-journal)
  - [9.25 REQ-F01-041 One-shot epoch migration](#925-req-f01-041-one-shot-epoch-migration)
  - [9.26 REQ-F01-042 V2 current-epoch evidence](#926-req-f01-042-v2-current-epoch-evidence)
  - [9.27 REQ-F01-043 Agent-neutral local eligibility](#927-req-f01-043-agent-neutral-local-eligibility)
  - [9.28 REQ-F01-044 Isolated device authentication and complete Admin readback](#928-req-f01-044-isolated-device-authentication-and-complete-admin-readback)
  - [9.29 REQ-F01-045 Separated Ruleset and merge authority](#929-req-f01-045-separated-ruleset-and-merge-authority)
  - [9.30 REQ-F01-046 Compatibility and epoch test coverage](#930-req-f01-046-compatibility-and-epoch-test-coverage)
  - [9.31 REQ-F01-047 Retire the first V1 migration](#931-req-f01-047-retire-the-first-v1-migration)
  - [9.32 REQ-F01-048 Exact V2 marker binding](#932-req-f01-048-exact-v2-marker-binding)
  - [9.33 REQ-F01-049 Distinct V2 Intent and Applied records](#933-req-f01-049-distinct-v2-intent-and-applied-records)
  - [9.34 REQ-F01-050 Partial migration is permanently non-retryable](#934-req-f01-050-partial-migration-is-permanently-non-retryable)
  - [9.35 REQ-F01-051 Fresh Phase evidence before implementation](#935-req-f01-051-fresh-phase-evidence-before-implementation)
  - [9.36 REQ-F01-052 Local Activation V2 implementation scope](#936-req-f01-052-local-activation-v2-implementation-scope)
  - [9.37 REQ-F01-053 Synchronized artifacts and distributions](#937-req-f01-053-synchronized-artifacts-and-distributions)
  - [9.38 REQ-F01-054 Required focused and regression tests](#938-req-f01-054-required-focused-and-regression-tests)
  - [9.39 REQ-F01-067 Epoch-3 predecessor preservation](#939-req-f01-067-epoch-3-predecessor-preservation)
  - [9.40 REQ-F01-068 Canonical Phase artifact impact](#940-req-f01-068-canonical-phase-artifact-impact)
  - [9.41 REQ-F01-069 Frozen migration preflight](#941-req-f01-069-frozen-migration-preflight)
  - [9.42 REQ-F01-070 Exact successor authorization](#942-req-f01-070-exact-successor-authorization)
  - [9.43 REQ-F01-071 One-shot epoch-3 transition and recovery](#943-req-f01-071-one-shot-epoch-3-transition-and-recovery)
  - [9.44 REQ-F01-072 Fresh Phase receipts before implementation](#944-req-f01-072-fresh-phase-receipts-before-implementation)
  - [9.45 REQ-F01-073 Active identity in Readiness evidence](#945-req-f01-073-active-identity-in-readiness-evidence)
  - [9.46 REQ-F01-074 Supersede the prior implementation PR](#946-req-f01-074-supersede-the-prior-implementation-pr)
  - [9.47 REQ-F01-075 Inherited Activation and delivery gates](#947-req-f01-075-inherited-activation-and-delivery-gates)
  - [9.48 REQ-F01-090 Preserve the current execution origin](#948-req-f01-090-preserve-the-current-execution-origin)
  - [9.49 REQ-F01-091 Exact verification-rework authority](#949-req-f01-091-exact-verification-rework-authority)
  - [9.50 REQ-F01-092 Bounded bootstrap commits](#950-req-f01-092-bounded-bootstrap-commits)
  - [9.51 REQ-F01-093 Exact PR #75 subject](#951-req-f01-093-exact-pr-75-subject)
  - [9.52 REQ-F01-094 Fresh exact-head delivery evidence](#952-req-f01-094-fresh-exact-head-delivery-evidence)
  - [9.53 REQ-F01-095 One-shot verification-to-requirements rework](#953-req-f01-095-one-shot-verification-to-requirements-rework)
  - [9.54 REQ-F01-096 Fresh Phase sequence before implementation](#954-req-f01-096-fresh-phase-sequence-before-implementation)
  - [9.55 REQ-F01-097 Separate delivery and Admin gates](#955-req-f01-097-separate-delivery-and-admin-gates)
  - [9.56 REQ-F01-098 Preserve the pending rework operation](#956-req-f01-098-preserve-the-pending-rework-operation)
  - [9.57 REQ-F01-099 Bound the Recovery commit](#957-req-f01-099-bound-the-recovery-commit)
  - [9.58 REQ-F01-100 Verify the successor Recovery authorization](#958-req-f01-100-verify-the-successor-recovery-authorization)
  - [9.59 REQ-F01-101 Continue the exact pending Intent once](#959-req-f01-101-continue-the-exact-pending-intent-once)
  - [9.60 REQ-F01-102 Cover Recovery and no-retry behavior](#960-req-f01-102-cover-recovery-and-no-retry-behavior)
  - [9.61 REQ-F01-103 Require exact-HEAD Recovery gates](#961-req-f01-103-require-exact-head-recovery-gates)
  - [9.62 REQ-F01-104 Resume the approved Phase sequence](#962-req-f01-104-resume-the-approved-phase-sequence)
  - [9.63 REQ-F01-105 Preserve separate delivery and Admin gates](#963-req-f01-105-preserve-separate-delivery-and-admin-gates)
  - [9.64 REQ-F01-106 Preserve the existing phase journal](#964-req-f01-106-preserve-the-existing-phase-journal)
  - [9.65 REQ-F01-107 Bound Applied event and publication time](#965-req-f01-107-bound-applied-event-and-publication-time)
  - [9.66 REQ-F01-108 Permit one timestamp-reader correction commit](#966-req-f01-108-permit-one-timestamp-reader-correction-commit)
  - [9.67 REQ-F01-109 Verify the timestamp-recovery ADC successor](#967-req-f01-109-verify-the-timestamp-recovery-adc-successor)
  - [9.68 REQ-F01-110 Test exact Applied reconciliation without writes](#968-req-f01-110-test-exact-applied-reconciliation-without-writes)
  - [9.69 REQ-F01-111 Gate the exact follow-up HEAD](#969-req-f01-111-gate-the-exact-follow-up-head)
  - [9.70 REQ-F01-112 Resume Phase evidence after reconciliation](#970-req-f01-112-resume-phase-evidence-after-reconciliation)
  - [9.71 REQ-F01-113 Preserve separate authorization boundaries](#971-req-f01-113-preserve-separate-authorization-boundaries)
  - [9.72 REQ-F01-120 Preserve the approved Issue #71 continuation subject](#972-req-f01-120-preserve-the-approved-issue-71-continuation-subject)
  - [9.73 REQ-F01-121 Verify the exact continuation ADC chain and marker](#973-req-f01-121-verify-the-exact-continuation-adc-chain-and-marker)
  - [9.74 REQ-F01-122 Bound the continuation commit lineage](#974-req-f01-122-bound-the-continuation-commit-lineage)
  - [9.75 REQ-F01-123 Test authorization, lineage, and no-write behavior](#975-req-f01-123-test-authorization-lineage-and-no-write-behavior)
  - [9.76 REQ-F01-124 Gate and bind the exact pushed HEAD](#976-req-f01-124-gate-and-bind-the-exact-pushed-head)
  - [9.77 REQ-F01-125 Reconcile before issuing Phase evidence](#977-req-f01-125-reconcile-before-issuing-phase-evidence)
  - [9.78 REQ-F01-126 Declare exact Phase artifact paths](#978-req-f01-126-declare-exact-phase-artifact-paths)
  - [9.79 REQ-F01-127 Preserve operation boundaries](#979-req-f01-127-preserve-operation-boundaries)
  - [9.80 REQ-F01-128 Preserve the exact reader-continuation subject](#980-req-f01-128-preserve-the-exact-reader-continuation-subject)
  - [9.81 REQ-F01-129 Verify the exact approved ADC chain](#981-req-f01-129-verify-the-exact-approved-adc-chain)
  - [9.82 REQ-F01-130 Bound the reader-continuation commit](#982-req-f01-130-bound-the-reader-continuation-commit)
  - [9.83 REQ-F01-131 Repair executable-source traceability](#983-req-f01-131-repair-executable-source-traceability)
  - [9.84 REQ-F01-132 Gate the exact HEAD and resume Phase transitions](#984-req-f01-132-gate-the-exact-head-and-resume-phase-transitions)
  - [9.85 REQ-F01-133 Record the supported execution transition](#985-req-f01-133-record-the-supported-execution-transition)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [REQ-WF-001](#req-wf-001) — 3.1 REQ-WF-001 Workflow phases
- [REQ-WF-002](#req-wf-002) — 3.2 REQ-WF-002 Host-managed implementation workspaces
- [REQ-WF-003](#req-wf-003) — 3.3 REQ-WF-003 Authorization continuity and implementation handoff
- [REQ-WF-004](#req-wf-004) — 3.4 REQ-WF-004 Skills
- [REQ-WF-005](#req-wf-005) — 3.5 REQ-WF-005 Review and delivery principles
- [REQ-WF-006](#req-wf-006) — 4 REQ-WF-006 Observable behavior
- [REQ-WF-007](#req-wf-007) — 5 REQ-WF-007 Error and boundary behavior
- [REQ-WF-008](#req-wf-008) — 6 REQ-WF-008 Security and privacy
- [REQ-WF-009](#req-wf-009) — 8.1 REQ-WF-009 Exact-subject User Review
- [REQ-WF-010](#req-wf-010) — 8.2 REQ-WF-010 Parent Integration and Final Delivery
- [REQ-F01-001](#req-f01-001) — 9.1 REQ-F01-001 Repository boundary
- [REQ-F01-003](#req-f01-003) — 9.2 REQ-F01-003 Append-only approval and Activation history
- [REQ-F01-005](#req-f01-005) — 9.3 REQ-F01-005 Eligibility by Activation time
- [REQ-F01-007](#req-f01-007) — 9.4 REQ-F01-007 Successor Activation
- [REQ-F01-008](#req-f01-008) — 9.5 REQ-F01-008 Verified V2 Activation policy
- [REQ-F01-009](#req-f01-009) — 9.6 REQ-F01-009 Approved Ruleset management
- [REQ-F01-010](#req-f01-010) — 9.7 REQ-F01-010 Existing Issue preservation
- [REQ-F01-011](#req-f01-011) — 9.8 REQ-F01-011 V2 effective time
- [REQ-F01-012](#req-f01-012) — 9.9 REQ-F01-012 Activation history prefix
- [REQ-F01-013](#req-f01-013) — 9.10 REQ-F01-013 Bootstrap and review gates
- [REQ-F01-014](#req-f01-014) — 9.11 REQ-F01-014 Activation-scoped temporary admin authentication
- [REQ-F01-015](#req-f01-015) — 9.12 REQ-F01-015 Owner-authorized decisions and separated operations
- [REQ-F01-016](#req-f01-016) — 9.13 REQ-F01-016 Native Independent Review execution and confidence
- [REQ-F01-018](#req-f01-018) — 9.14 REQ-F01-018 Exact Phase evidence recovery
- [REQ-F01-031](#req-f01-031) — 9.15 REQ-F01-031 Generic Phase restart authorization
- [REQ-F01-032](#req-f01-032) — 9.16 REQ-F01-032 Eligible Issue and Binding
- [REQ-F01-033](#req-f01-033) — 9.17 REQ-F01-033 Append-only Phase restart records
- [REQ-F01-034](#req-f01-034) — 9.18 REQ-F01-034 One-shot label transition and recovery
- [REQ-F01-035](#req-f01-035) — 9.19 REQ-F01-035 Active Phase generation
- [REQ-F01-036](#req-f01-036) — 9.20 REQ-F01-036 Issue #63 compatibility
- [REQ-F01-037](#req-f01-037) — 9.21 REQ-F01-037 ADC is the sole Phase restart approval
- [REQ-F01-038](#req-f01-038) — 9.22 REQ-F01-038 Missing historical Binding provenance
- [REQ-F01-039](#req-f01-039) — 9.23 REQ-F01-039 One-time epoch authorization
- [REQ-F01-040](#req-f01-040) — 9.24 REQ-F01-040 Append-only epoch journal
- [REQ-F01-041](#req-f01-041) — 9.25 REQ-F01-041 One-shot epoch migration
- [REQ-F01-042](#req-f01-042) — 9.26 REQ-F01-042 V2 current-epoch evidence
- [REQ-F01-043](#req-f01-043) — 9.27 REQ-F01-043 Agent-neutral local eligibility
- [REQ-F01-044](#req-f01-044) — 9.28 REQ-F01-044 Isolated device authentication and complete Admin readback
- [REQ-F01-045](#req-f01-045) — 9.29 REQ-F01-045 Separated Ruleset and merge authority
- [REQ-F01-046](#req-f01-046) — 9.30 REQ-F01-046 Compatibility and epoch test coverage
- [REQ-F01-047](#req-f01-047) — 9.31 REQ-F01-047 Retire the first V1 migration
- [REQ-F01-048](#req-f01-048) — 9.32 REQ-F01-048 Exact V2 marker binding
- [REQ-F01-049](#req-f01-049) — 9.33 REQ-F01-049 Distinct V2 Intent and Applied records
- [REQ-F01-050](#req-f01-050) — 9.34 REQ-F01-050 Partial migration is permanently non-retryable
- [REQ-F01-051](#req-f01-051) — 9.35 REQ-F01-051 Fresh Phase evidence before implementation
- [REQ-F01-052](#req-f01-052) — 9.36 REQ-F01-052 Local Activation V2 implementation scope
- [REQ-F01-053](#req-f01-053) — 9.37 REQ-F01-053 Synchronized artifacts and distributions
- [REQ-F01-054](#req-f01-054) — 9.38 REQ-F01-054 Required focused and regression tests
- [REQ-F01-067](#req-f01-067) — 9.39 REQ-F01-067 Epoch-3 predecessor preservation
- [REQ-F01-068](#req-f01-068) — 9.40 REQ-F01-068 Canonical Phase artifact impact
- [REQ-F01-069](#req-f01-069) — 9.41 REQ-F01-069 Frozen migration preflight
- [REQ-F01-070](#req-f01-070) — 9.42 REQ-F01-070 Exact successor authorization
- [REQ-F01-071](#req-f01-071) — 9.43 REQ-F01-071 One-shot epoch-3 transition and recovery
- [REQ-F01-072](#req-f01-072) — 9.44 REQ-F01-072 Fresh Phase receipts before implementation
- [REQ-F01-073](#req-f01-073) — 9.45 REQ-F01-073 Active identity in Readiness evidence
- [REQ-F01-074](#req-f01-074) — 9.46 REQ-F01-074 Supersede the prior implementation PR
- [REQ-F01-075](#req-f01-075) — 9.47 REQ-F01-075 Inherited Activation and delivery gates
- [REQ-F01-090](#req-f01-090) — 9.48 REQ-F01-090 Preserve the current execution origin
- [REQ-F01-091](#req-f01-091) — 9.49 REQ-F01-091 Exact verification-rework authority
- [REQ-F01-092](#req-f01-092) — 9.50 REQ-F01-092 Bounded bootstrap commits
- [REQ-F01-093](#req-f01-093) — 9.51 REQ-F01-093 Exact PR #75 subject
- [REQ-F01-094](#req-f01-094) — 9.52 REQ-F01-094 Fresh exact-head delivery evidence
- [REQ-F01-095](#req-f01-095) — 9.53 REQ-F01-095 One-shot verification-to-requirements rework
- [REQ-F01-096](#req-f01-096) — 9.54 REQ-F01-096 Fresh Phase sequence before implementation
- [REQ-F01-097](#req-f01-097) — 9.55 REQ-F01-097 Separate delivery and Admin gates
- [REQ-F01-098](#req-f01-098) — 9.56 REQ-F01-098 Preserve the pending rework operation
- [REQ-F01-099](#req-f01-099) — 9.57 REQ-F01-099 Bound the Recovery commit
- [REQ-F01-100](#req-f01-100) — 9.58 REQ-F01-100 Verify the successor Recovery authorization
- [REQ-F01-101](#req-f01-101) — 9.59 REQ-F01-101 Continue the exact pending Intent once
- [REQ-F01-102](#req-f01-102) — 9.60 REQ-F01-102 Cover Recovery and no-retry behavior
- [REQ-F01-103](#req-f01-103) — 9.61 REQ-F01-103 Require exact-HEAD Recovery gates
- [REQ-F01-104](#req-f01-104) — 9.62 REQ-F01-104 Resume the approved Phase sequence
- [REQ-F01-105](#req-f01-105) — 9.63 REQ-F01-105 Preserve separate delivery and Admin gates
- [REQ-F01-106](#req-f01-106) — 9.64 REQ-F01-106 Preserve the existing phase journal
- [REQ-F01-107](#req-f01-107) — 9.65 REQ-F01-107 Bound Applied event and publication time
- [REQ-F01-108](#req-f01-108) — 9.66 REQ-F01-108 Permit one timestamp-reader correction commit
- [REQ-F01-109](#req-f01-109) — 9.67 REQ-F01-109 Verify the timestamp-recovery ADC successor
- [REQ-F01-110](#req-f01-110) — 9.68 REQ-F01-110 Test exact Applied reconciliation without writes
- [REQ-F01-111](#req-f01-111) — 9.69 REQ-F01-111 Gate the exact follow-up HEAD
- [REQ-F01-112](#req-f01-112) — 9.70 REQ-F01-112 Resume Phase evidence after reconciliation
- [REQ-F01-113](#req-f01-113) — 9.71 REQ-F01-113 Preserve separate authorization boundaries
- [REQ-F01-120](#req-f01-120) — 9.72 REQ-F01-120 Preserve the approved Issue #71 continuation subject
- [REQ-F01-121](#req-f01-121) — 9.73 REQ-F01-121 Verify the exact continuation ADC chain and marker
- [REQ-F01-122](#req-f01-122) — 9.74 REQ-F01-122 Bound the continuation commit lineage
- [REQ-F01-123](#req-f01-123) — 9.75 REQ-F01-123 Test authorization, lineage, and no-write behavior
- [REQ-F01-124](#req-f01-124) — 9.76 REQ-F01-124 Gate and bind the exact pushed HEAD
- [REQ-F01-125](#req-f01-125) — 9.77 REQ-F01-125 Reconcile before issuing Phase evidence
- [REQ-F01-126](#req-f01-126) — 9.78 REQ-F01-126 Declare exact Phase artifact paths
- [REQ-F01-127](#req-f01-127) — 9.79 REQ-F01-127 Preserve operation boundaries
- [REQ-F01-128](#req-f01-128) — 9.80 REQ-F01-128 Preserve the exact reader-continuation subject
- [REQ-F01-129](#req-f01-129) — 9.81 REQ-F01-129 Verify the exact approved ADC chain
- [REQ-F01-130](#req-f01-130) — 9.82 REQ-F01-130 Bound the reader-continuation commit
- [REQ-F01-131](#req-f01-131) — 9.83 REQ-F01-131 Repair executable-source traceability
- [REQ-F01-132](#req-f01-132) — 9.84 REQ-F01-132 Gate the exact HEAD and resume Phase transitions
- [REQ-F01-133](#req-f01-133) — 9.85 REQ-F01-133 Record the supported execution transition
<!-- heading-map:end -->


<a id="purpose"></a>
## 1 Purpose

Define the reusable development workflow shared by OpenAI/Codex, Claude Code, and Google Antigravity 2.0. The product provides workflow behavior and deterministic local tools; it does not scaffold application source or synchronize projects with another repository.

<a id="scope"></a>
## 2 Scope

The repository owns exactly 16 canonical Skills, shared standards and templates, ADC and Issue workflows, immutable verification and acceptance evidence, audit and user review, delivery gates, project/context readback, deterministic documentation validation, and host-specific packages. The current public CLI uses the `project`, `context`, `adc`, `issue`, `docs`, `work`, `pr`, `verification`, `acceptance`, `audit`, `user-review`, and `delivery` namespaces. A consumer project owns its source, `.agent/project.json`, Issue-specific artifacts, and verification commands.

The product does not own a service, database, daemon, GUI, project-template repository, source synchronization, automatic semantic document rewriting, stack-wide detectors, or existing-consumer migration.

Legacy note: the historical procedures retained in Section 3 are reference material only, except for the current Skill inventory in §3.4. Retired flat CLI commands and the ten-Skill workflow are superseded by the current P-ASES route table and canonical Skill source under `workflow/skills/`.

<a id="normative-requirements"></a>
## 3 Normative requirements

<a id="req-wf-001"></a>
<a id="req-wf-001-workflow-phases"></a>
### 3.1 REQ-WF-001 Workflow phases

Single and child Issues use `requirements -> [specification] -> [design] -> ready -> execution -> verification -> user-review -> closed`. Specification is required when observable product behavior is being decided or changed; design is required when a material technical decision is being made. Each omitted phase has its own explicit reason. The only skip edges are `requirements -> design`, `specification -> ready`, and `requirements -> ready` (the last requires separate specification and design reasons). The parent lifecycle is separate: `requirements -> ready -> execution -> integration -> user-review -> closed`. An ordinary single/child Issue may also perform the one ADC-authorized `execution -> requirements` recovery edge defined by REQ-F01-031–037; it creates a new active Phase evidence generation and does not rewrite prior receipts.

The current `kind:*` Issue label is the source of Issue kind, and each open Issue has exactly one `phase:*` label and at most one `attention:*` label. A new child Issue is created with `kind:child` and `phase:requirements`. A backward phase transition is allowed only through the exact typed authorization in the current approved ADC and the append-only recovery procedure in REQ-F01-031–037; ordinary phase advancement remains forward-only. Parent #26 and fixed Bootstrap Issues #27–#32 retain their migration treatment and are not rewritten by the normal lifecycle gate. `closed` describes the actual closed GitHub Issue after separately authorized merge; it is not a GitHub `phase:closed` label.

An Issue is the authority for a work item. Repository-changing work begins from an owning Issue, one dedicated feature branch, its frozen work binding, and its current approved ADC. The ADC scopes the work; it does not replace product specifications, design, or independent tests. The approved ADC is the approval authority for the decisions recorded in it. A phase decision comment is only a technical receipt bound to that ADC generation, the actual Issue kind, frozen base/branch/worktree, branch commit, document bytes, and any independent skip reasons.

The supported `ExecutionBinding` format is strict: each binding row contains the current nine fields, including `branch_ref`; the append-only history wrapper contains rows in that same format. An older eight-field row is outside the supported contract and may be rejected by read/resume commands. Callers must not assume compatibility, branch inference, migration, or automatic rewrite.

At a specification, design, or ready boundary, the runtime records a canonical `PASES_PHASE_DECISION_V1` Issue comment. Its payload binds the repository and Issue, verified kind and phase pair, approved ADC comment ID and digest (the receipt generation), branch ref and commit SHA, sorted document role/path/SHA-256 entries, and explicit skip reasons. The frozen execution binding must match the Issue, repository, ADC, dedicated branch, base, and worktree; current HEAD must descend from its frozen base. A new approved ADC generation appends a binding record without changing that frozen tuple. Each transition validates only the artifacts needed through that stage: specification validates its declared specification; design validates its declared design and the completed specification receipt/artifacts when specification was not skipped; ready validates the required prior receipt chain plus the declared specification/design/test-Oracle artifacts. A document digest is read from a regular file in the branch commit tree and checked against its bytes; uncommitted working-tree content is not evidence. Before `ready`, the approved ADC must declare test impact; each requirement must resolve through `REQ`, `DES`, `ORA`, and `TST` links whose canonical targets exist in that same commit, contain the linked anchors, and match the ADC impact or an explicit unchanged decision; every linked executable test source must also exist in that commit. The test source may be an intentionally failing scaffold: `ready` verifies its committed identity and path, not a passing test result. The test case and independent Oracle are fixed before `ready`; execution may implement or extend the source, and verification determines whether it passes. If the source file is absent at `ready`, the transition remains blocked. Changing a completed specification or design blocks dependent transitions until the work returns to requirements with a newly approved ADC generation. Missing, edited, stale, duplicate, non-canonical, or mismatched evidence blocks without changing Issue labels. Every ordinary single/child phase-label transition verifies the actual Issue kind, approved ADC, and current Activation/Gate Selection. Entering execution from ready also rebuilds and rereads the current ready receipt and frozen binding. Comment readback consists of two complete direct/list/direct snapshots with exact Issue, HTML, and API URLs; label writes are read back against the complete intended label set, and an ambiguous race fails closed.

Requirements, specifications, design, code/tests, and status/evidence have distinct owners and must agree in the final result. A material decision change updates its owning documents and dependent implementation before work proceeds. One document owns each durable rule; other documents link to it instead of copying policy.

Every new durable work item records explicit specification, design, testing, and status decisions in the approved ADC's `## Artifact impact` section. Create/update decisions name paths under the corresponding `docs/specs/`, `docs/design/`, or `docs/testing/` tree; unchanged or not-applicable decisions include a reason. A reason for skipping a specification or design phase must agree with the matching approved ADC decision. Feature work uses the `work` namespace's exact-base, branch, bind, and recover operations after the owning Issue and approved ADC are validated. The frozen execution identity is the Issue, repository, ADC generation, base ref/SHA, dedicated branch ref, worktree, and initial HEAD. Phase-bound specification and test artifacts are authored on this bound branch before their phase receipts are published.

<a id="req-wf-002"></a>
<a id="req-wf-002-host-managed-implementation-workspaces"></a>
### 3.2 REQ-WF-002 Host-managed implementation workspaces

Publishing, reviewing, or approving an Implementation Contract does not allocate a workspace. Execution of the approved Contract is the trigger. The normal user request remains “Implement this Contract”; the Skill reads the Schema 2 `workspace.isolation` policy before edits and lets the active host establish or reuse isolation.

Before phase-bound artifact work or implementation, `context show` reads the current approved ADC and existing binding; `work base` resolves an exact base; `work branch` and `work bind` establish the frozen execution identity, including the dedicated Issue branch. Existing bindings are reused only when their Issue, repository, ADC generation, base, branch, worktree, and HEAD ancestry invariants still match. An explicitly reapproved ADC generation is appended to the binding history while retaining the original base, branch, worktree, and initial HEAD.

For a verified existing continuation, `work recover` validates an existing immutable ExecutionBinding file only after the exact Issue, ADC, PR, base, branch, worktree, and HEAD tuple is checked. It fails closed on mismatch and does not switch branches, create worktrees, synthesize a missing Binding, or mutate GitHub.

For Issue #63 / PR #64 only, the separately approved one-time provenance exception uses a new `PASES_EXECUTION_ADOPTION_V1` epoch; it never recreates an `ExecutionBinding` or claims the missing historical tuple. Bootstrap code and tests may be committed while the original binding is unavailable, but no ordinary phase receipt or QA/Review/Readiness PASS is recorded before adoption. After that bootstrap commit is pushed and all Required Checks pass on the exact final HEAD, `work adoption-plan 63` is a read-only preview. Its canonical digest binds the pinned repo/owner, complete sorted Issue label snapshot, approved ADC and Phase Intent/Applied IDs, PR ID/author/body/title digest/base/ref/head/branch, five trusted exact-HEAD check-run identities, and current workspace attachment identity. The complete plan must receive a distinct exact-scope `EXECUTION_ADOPTION` Owner decision through the authenticated chat-confirmed V3 route before `work adoption-apply 63` can append its single Intent/Applied pair and local workspace attachment. Apply persists the full canonical approved plan beside the epoch; every later read verifies that snapshot against the epoch and journal digest. The journal payload's canonical UTC `created_at` is captured before POST; GitHub's immutable carrier `created_at` and `updated_at` are assigned at persistence and are validated separately, without requiring the two timestamps to be equal. If the plan is unavailable, the typed decision is missing, or any exact subject drifts, adoption blocks without a write. `work recover` remains an existing-binding resume operation; normal Issue starts and other repositories cannot use this exception.

The adopted epoch separates the prospective selected base SHA from the existing PR HEAD observed at adoption and permanently records `historical_binding_provenance=UNVERIFIED`. From that epoch onward, local workspace attachment, PRBinding lineage, Phase receipts, Verification, Acceptance, Self-Audit, Independent Review, Readiness, and User Review use the normal validators. The adoption decision is not a User Review, Ruleset, Activation, or merge approval. Durable remote anchors and reattachment for ordinary new executions remain a separately scoped follow-up; this one-time route does not add them globally.

For this exact Issue #63 adopted epoch, a later approved ADC is a forward successor of the immutable origin rather than a replacement adoption. The original epoch and its adoption Owner decision, Intent/Applied journal, and first PRBinding remain byte-identical. The runtime accepts a later ADC only through the complete approved forward-generation chain and its own completed Phase V2 Intent/Applied pair. Until that pair exists, verification reports `ADC_REFRESH_PENDING_PHASE_REBASELINE`; after the pair but before the dedicated `work adoption-refresh 63`, ordinary verification reports `ADC_REFRESH_REQUIRED`. That exact Issue-only command appends one PRBinding V3 with the same adoption ID and frozen base/branch/PR, the new ADC pointer, and exact current PR HEAD, then appends a V2 checkpoint retaining the original epoch digest. An interrupted checkpoint is resumed by verifying the existing PRBinding and writing only the missing checkpoint; a complete retry is a zero-write NOOP. `work recover` stays read-only, and ordinary `pr ensure` may append only a same-effective-ADC HEAD successor; it never performs the generation refresh.

- Before host isolation, resolve the selected same-repository base ref and its full SHA. For an already-bound execution, reuse its frozen `base_ref` and `base_sha`.
- Resume a valid binding in its existing workspace after commits without rerunning `start-feature-branch` or resolving the frozen SHA against a newer remote tip. `prepare-implementation` may validate reuse and explicit Contract supersession; it must not reinitialize the workspace.
- When the local binding file is missing on an existing open PR continuation, `work recover` cannot restore it. Search existing worktrees and immutable artifacts read-only. Unless the original frozen tuple can be independently authenticated and a supported append-only path can preserve it, stop as `BLOCKED_BINDING_PROVENANCE_MISSING`; do not infer the original base, branch, worktree, or initial HEAD from current GitHub refs.
- Native isolation is available only when the active host surface can create or reuse a workspace whose initial `HEAD` is exactly the selected base SHA. A host worktree feature alone does not satisfy this requirement. Verify the initial HEAD before `prepare-implementation`.
- `auto` prefers exact-base native isolation when available. Otherwise it uses the existing current-checkout branch flow with the same `base_ref` and expected SHA.
- `required` stops before edits when host-managed isolation at the exact selected base cannot be established.
- `disabled` does not request a new worktree and does not force a session already in a worktree back to the main checkout.

Codex uses its current surface's managed worktree or task-fork capability when exposed and selects the approved starting ref when supported; the resulting HEAD must equal the selected SHA. Claude Code reuses a valid worktree or enters one through native `EnterWorktree` only when it can preserve the exact selected base. For unsupported stacked/non-default bases, and any other unverified exact-base capability, `auto` falls back and `required` blocks. Do not create a wrong-base workspace and repair it by switching, resetting, merging, or rebasing. The runtime never invokes another coding-agent binary or runs raw automatic `git worktree add`; it does not manage host permissions, placement, resume, or cleanup and cannot prove session provenance.

Issue/PR identity remains the user's routing key. One implementation writer owns an execution, and ordinary follow-up answers or corrections reuse the same binding and workspace. A changed approved Contract blocks continuation until explicit supersession refreshes only its bound comment ID/SHA. This version does not add global task discovery, a database, daemon, Issue DAG scheduler, or parallelism setting.

`.worktreeinclude` may contain explicit project-owned patterns for local ignored files needed in host-created worktrees. The workflow never creates that file, infers secrets, or copies ignored files without an explicit pattern. Independent Review is performed by a dedicated fresh host-native subagent; the host owns its spawn, isolation, join, cancellation, and provenance. The implementation execution cannot substitute its own second prompt, a human fallback, or User Review.

When Claude Code uses its default in-repository `.claude/worktrees/` location, the consumer project owns ignoring that path in its root `.gitignore`. Custom in-repository locations require an ignore rule for their actual relative path; external locations need no rule for those files. The workflow documents this expectation but neither mutates ignore files nor performs generic ignore-path preflight/availability checks.

P-ASES exposes no public milestone command. Skills must not infer or mutate milestones through a hidden or retired CLI route.

<a id="req-wf-003"></a>
<a id="req-wf-003-authorization-continuity-and-implementation-handoff"></a>
### 3.3 REQ-WF-003 Authorization continuity and implementation handoff

Once a user authorizes execution of an approved Issue-scoped Implementation Contract, that authorization continues through the routine Issue-scoped mutations required to reach a review-ready PR: commit, non-force push, PR create/reuse and required title/body update, transition to `phase:review`, exact-HEAD Agent Self-Review publication, CI/Required Check reads, and the final delivery gate. Skills MUST NOT request a separate conversational confirmation solely for those operations. Host-enforced security prompts may still apply.

That authorization does not cover material scope or architecture changes, contract supersession, an ambiguous or conflicting owning Issue/base, force-push or branch deletion, merge, tag/release creation, publication outside the review PR workflow, credential or permission escalation, mutation of an unrelated Issue/PR, or an explicit user request to stop before PR creation. A conflict requiring one of these decisions blocks only the dependent work.

The current handoff is owned by `verification`, `acceptance`, `audit`, `pr`, `delivery`, and `user-review` routes as appropriate to the artifact. Evidence is bound to exact subjects and read back before acceptance. User Review is a separate recorded gate. The implementation context does not author independent-review evidence. The workflow does not claim that runtime context-ID inequality proves host provenance, and it does not merge or release automatically.

<a id="req-wf-004"></a>
<a id="req-wf-004-skills"></a>
### 3.4 REQ-WF-004 Skills

Canonical Skill source is `workflow/skills/`. It contains exactly these 16 task areas:

1. `request-intake`
2. `adc-authoring`
3. `adc-registry`
4. `issue-decomposition`
5. `product-specification`
6. `technical-design`
7. `test-specification`
8. `work-execution`
9. `verification-evidence`
10. `acceptance-validation`
11. `contract-audit`
12. `independent-review`
13. `user-review`
14. `integration-validation`
15. `delivery-control`
16. `work-checkpoint`

Each Skill MUST have concise YAML frontmatter with `name` and `description`. Detailed shared policy belongs in standards or referenced resources. A Skill MUST state its trigger, expected inputs, ordered procedure, output, uncertainty behavior, and supporting resources where relevant. Skill copies in `dist/**` are generated.

Skills route work through the public namespaces above. ADC Skills preserve exact approved bytes and verify named-comment readback; Issue Skills validate dependencies and parent integration; work Skills freeze base and binding identity; verification and acceptance Skills bind results to declared subjects; delivery Skills re-read all required gates; user-review records the separate user decision. Mutations require the authority defined by the approved ADC and remain limited to the named repository and Issue/PR.

The host orchestrates one ordered lifecycle through the Skills and host adapters; P-ASES CLI commands remain individual state mutations and readbacks and do not introduce a persistent second phase state machine. For an ordinary single/child Issue, the host completes optional Phase rebaseline, verifies the exact frozen Binding, establishes Specification/Design/Test Oracle decisions and ordinary receipts, enters `ready`, then `execution`. After implementation at the current PR HEAD, current Verification, Acceptance, Self-Audit, and a fresh host-native Independent Review must pass before `issue advance ... verification`; only then may Review Readiness pass and automatically start User Review.

ADC authoring and registry instructions define current ADC payload structure, validation, publication, exact comment readback, and supersession. Historical Implementation Contract artifacts remain historical evidence and do not define the current P-ASES command surface. The portable Chat project-instructions template describes only capabilities available to the active host or plugin.

<a id="req-wf-005"></a>
<a id="req-wf-005-review-and-delivery-principles"></a>
### 3.5 REQ-WF-005 Review and delivery principles

Self-review is evidence, never approval. Review findings use these categories:

- A — Contract violation
- B — Contract ambiguity
- C — Newly discovered requirement
- D — Optional improvement

Category C is not implementer failure. An implementation is complete only through the PR delivery gate; passing tests alone is insufficient. A new PR commit invalidates review against an older HEAD. Missing or unavailable verification remains unverified and MUST NOT be reported as passing.

A self-review has two separate layers: Contract Conformance Review covers the complete approved Implementation Contract, and Reviewer Checklist Review covers every effective Contract/Issue checklist item. The Reviewer Checklist is a concise summary review surface, not a substitute for reading and checking the full approved contract. Both layers bind to the same exact PR HEAD, approved contract comment ID, and approved contract SHA.

Independent PR review is a separate artifact bound to the same exact HEAD, approved contract, complete source diff, contract review units, and checklist. A dedicated fresh host-native subagent is mandatory, and the host must spawn it, join it, and obtain its actual review result; unavailable host identifiers do not mean the review was skipped. The child itself reads the exact subject, approved ADC/Contract, checklist, full diff, and test evidence, then authors the raw result and findings. `PASES_INDEPENDENT_REVIEW_CONTEXT_V2` maps `context_id` to the child's reviewer context ID and includes one evidence-backed `review_units` result for every ADC requirement ID and Reviewer Checklist ID returned by the current subject. Each unit has `item_id`, `status` (`PASS` or `FAIL`), and nonempty `evidence_refs`; the set must exactly match the current required IDs. Finding rows include `blocks_readiness`, which may be true only for a severity C finding. The `provenance` string may contain compact canonical JSON with `spawn_session_id`, `reviewer_id`, and `implementation_binding_id`; absent values are represented as null or omitted, and an empty provenance string means all three are unavailable. If present, `implementation_binding_id` must match the current binding. The runtime stores `PASES_INDEPENDENT_REVIEW_V3` with the child-authored review units, typed C blocking choices, each available host identifier, and explicit confidence: `HIGH` when all three IDs are available and valid, otherwise `LIMITED`. Missing identifiers alone never block an otherwise valid review or Readiness. V1/V2 persisted review readers and bytes remain available for historical inspection, but those schemas lack checklist coverage and cannot satisfy current Readiness. A known same-context identity, available mismatching binding, malformed identity, stale subject, incomplete review-unit set, invalid child result, or non-PASS unit blocks. The parent preserves the child's raw result and MUST NOT edit its findings, verdict, context ID, review units, or provenance. Context IDs and caller-provided host IDs are not cryptographic proof of host authenticity; the host owns child lifecycle and reports which identifiers it could verify.

The implementation session cannot author a substitute review, invoke another coding-agent executable through the P-ASES CLI, request a same-agent second prompt, or replace an unavailable native subagent with a human or User Review. No child result, failed/unknown spawn or join, same-context result, stale subject, malformed artifact, available mismatching binding, incomplete or failed review unit, A/B finding, reviewer-designated unresolved blocking C finding, or non-PASS verdict blocks Readiness and User Review. Missing `spawn_session_id`, `reviewer_id`, or `implementation_binding_id` by itself does not block when the host did obtain and join a fresh child's valid exact-subject result; the record and Readiness output must show `LIMITED` provenance confidence and identify missing values. A complete matching identity set is `HIGH`. Fixes require a new PR HEAD and a newly spawned child; do not retry without progress on the same HEAD. Do not add a runtime spawn API or claim host provenance from caller-provided context IDs. Existing `PASES_INDEPENDENT_REVIEW_V1` and V2 bytes and readers remain unchanged; current Readiness requires V3 coverage.

After a child review PASS, the host reads current Phase, Binding, Verification, Acceptance, Self-Audit, and Required CI for that exact subject. Only when all required evidence is current and PASS does it run `issue advance ... verification`, then `delivery readiness`. A PASS automatically starts `user-review start` without asking the user for an extra confirmation to begin the session. This automation starts the gate only; it does not decide or record approval. A blocking finding is fixed during `execution` and receives a fresh review at the new HEAD. Once the Issue enters `verification`, code changes are not sent backward through an implicit phase edge; a required change blocks as `BLOCKED_PHASE_REWORK_DECISION_REQUIRED` pending an authorized decision.

QA is a separate record bound to current HEAD and contract. A `required` QA record has at least one completed test case with action, expected outcome, result, and concrete evidence. A `not_applicable` record has no cases and a concrete reason. Delivery accepts only all-PASS cases or N/A; failures, untested/pending cases, or stale records block. QA evidence does not substitute for self-review or independent review.

When saving or publishing a new contract, the runtime automatically canonicalizes a recognizable legacy Reviewer Checklist H2 before hashing. It preserves checkbox wording and order plus every byte outside that H2, inserts the required markers and approved introduction, and rejects ambiguous headings, malformed/missing items, or unrelated prose before GitHub mutation. The contract SHA binds the normalized exact bytes. This does not invalidate or rewrite already-approved historical contract bytes; restoration remains byte-for-byte. Historical checklist extraction keeps canonical-block precedence and the narrow-heading fallback; a legacy/non-canonical historical H2 remains included in contract-conformance coverage, while a strict-canonical H2 may be excluded. Self-review publication reads back the exact named comment after creation and verifies its PR association and body before any pointer update; this check is separate from the subsequent HEAD and contract race revalidation.

A current contract section or checklist item with `result: fail` blocks handoff even when Required Checks are green. Contract-section `untested` is valid evidence of an unresolved blocker and blocks handoff. Checklist-level `untested` remains valid, non-blocking evidence by itself; its evidence must identify the unavailable verification or residual uncertainty. A source/diff-reviewable contract section must not be marked `untested` to avoid checking it. Mandatory verification and configured Required Checks remain independent gates.

Final Verification is a machine-generated current-HEAD receipt. It requires a clean local worktree whose HEAD equals the full PR HEAD, runs Issue-routed final hooks, stores only command identities and hashes, and publishes an immutable receipt. A skipped target yields `partial`, and an empty plan yields `empty`; neither satisfies delivery. A passing receipt needs at least one executed command and no skipped target. This gate is independent from Required Checks.

Schema-v1 public self-reviews may be read for diagnostics, but they do not establish full-contract conformance and cannot satisfy handoff. Delivery gives explicit guidance to regenerate and publish a schema-v2 review with the current workflow; historical comments are not rewritten automatically.

<a id="req-wf-006"></a>
<a id="req-wf-006-observable-behavior"></a>
## 4 REQ-WF-006 Observable behavior

The portable workflow routes agents from an owning Issue to its active phase, affected components, applicable application profiles, explicit document impact decisions and linked specification/design/status owners, relevant symbols and tests, and current diff. It does not require reading every standard or generated project summary by default. Skills describe when to load additional standards; they do not duplicate full policy text.

The consumer's explicit project profile is the machine authority for components, stacks, application types, targets, hooks, and branch/milestone policy. Application type, stack, target, and runtime host are independent concepts. Application type is never inferred from repository contents, stack, target, or host.

<a id="req-wf-007"></a>
<a id="req-wf-007-error-and-boundary-behavior"></a>
## 5 REQ-WF-007 Error and boundary behavior

| Condition | Required behavior |
|---|---|
| No owning Issue or no decision-complete contract | Stop repository-changing work and establish the missing Issue artifact first. |
| Material requirement conflict | Report the exact conflict and continue only with independent valid work. |
| Newly discovered category-C requirement | Record it for explicit triage; do not silently treat it as implementer failure or rewrite the approved scope. |
| Unavailable platform, tool, credential, or CI result | Record it as unverified and identify the concrete blocker. |
| Authorized implementation has no review PR | Continue through the deterministic PR-establishment command without a second conversational approval. |
| PR establishment or phase transition fails | Report the precise blocker; a PR created before a phase failure is identified for an idempotent retry. |
| Required Checks remain pending after PR creation | Report `BLOCKED_DELIVERY_CHECKS_PENDING`; do not report implementation complete. |
| Submitted self-review without matching evidence | Treat it as a claim to check, never as proof. |

<a id="req-wf-008"></a>
<a id="req-wf-008-security-and-privacy"></a>
## 6 REQ-WF-008 Security and privacy

The workflow never prints or stores credentials in contract payloads, logs, Skills, generated packages, or PR evidence. Local hooks are trusted explicit commands, not a sandbox. Network-backed operations fail closed on uncertain ownership, identity, authorization, or state.

<a id="p-ases-migration-bootstrap-gates"></a>
## 7 P-ASES migration Bootstrap gates

The migration from the legacy workflow to P-ASES uses two separately named gates. The fixed Bootstrap cohort is parent Issue #26 and child Issues #27–#32 **in `puchinya/ai-agent-workflow` only**. Repository identity is compared case-insensitively. Those child Issues use `bootstrap-legacy-v1`; no label, issue text, caller flag, or agent decision can add another Issue or repository to that set. Existing non-cohort Issues created before activation remain on the existing legacy workflow and are never migrated automatically. Only a non-cohort Issue created after the verified activation timestamp selects `p-ases-v1`; missing or invalid activation and pre-activation Issues are `UNDETERMINED` in the new router, which never falls back automatically.

Bootstrap reports `BOOTSTRAP_TECHNICAL_READY` or `BOOTSTRAP_BLOCKED` for the fixed migration cohort only. Technical readiness requires the current approved child ADC, exact open/non-draft same-repository PR and current HEAD, standalone `Closes #N`, a clean checkout, executed local tests/static/distribution checks, successful current-head required GitHub CI jobs with provenance, fixed gate selection and evaluator digest, and explicit unverified-environment disclosure. Self-review, independent review, review artifacts, ordinary `PASES_REVIEW_READINESS_V1: PASS`, GitHub approval, and final User Review are not Bootstrap prerequisites. Technical readiness does not claim any of those reviews occurred or passed, does not grant merge permission, and does not cause an Issue phase transition. The #27 legacy ADC approval state and the Issue dependency graph remain required technical gates; #28 acceptance remains a dependency.

<a id="p-ases-human-review-and-final-delivery"></a>
## 8 P-ASES human review and final delivery

<a id="req-wf-009"></a>
<a id="req-wf-009-exact-subject-user-review"></a>
### 8.1 REQ-WF-009 Exact-subject User Review

For ordinary single/child Issues, new Review Readiness PASS may be produced only while the Issue is `phase:verification`. During `phase:user-review`, Readiness may be recomputed only when the immutable session for the exact same subject and Readiness SHA already exists; other phases cannot produce PASS. The current GitHub Issue's unique valid `kind:*` label is the authority for Issue kind. `user-review start`, `sync`, and `status` use that value when `--kind` is omitted; an explicit `--kind` is only an assertion and must match. Missing, malformed, unknown, or duplicate `kind:*` labels fail closed. Before Readiness PASS or the first User Review session/snapshot/result write, the runtime reads exactly one valid `kind:*`, one valid `phase:*`, and zero `attention:*` labels. An attention state observed at a gate blocks Readiness PASS and any subsequent User Review evidence writes; malformed or multiple attention labels also fail closed. If attention appears after session creation, retain that immutable session but stop before writing a snapshot/result or changing labels. Clearing attention remains the responsibility of the existing attention workflow. `user-review start` validates the exact kind, phase, attention state, exact subject, Readiness PASS, and allowed phase transition before writing a session or feedback snapshot: `phase:verification` may create one session, while `phase:user-review` may only resume its matching existing session. A `sync` with an existing session in `phase:verification` recovers an interruption after session creation but before the Phase update, preserves `started_at`, and completes the normal `issue advance` readback. The phase transition re-reads the complete kind/phase/attention state immediately before its label update. If the write response is lost, exact Issue-label readback determines whether it applied; a confirmed transition is not written a second time. Missing, malformed, or unrelated sessions are never overwritten. `PENDING` is the normal waiting result and retains exit code 2; the host reports `WAITING_USER_REVIEW_DECISION` only after it reads back the immutable session, feedback snapshot, and `phase:user-review`. A blocking finding is fixed in `execution` with a fresh review at the new HEAD. After entering `verification`, any required code change blocks as `BLOCKED_PHASE_REWORK_DECISION_REQUIRED`; no backward Phase edge is inferred.

Final human User Review begins only after Review Readiness is PASS for the same repository, Issue, PR, approved ADC digest, exact PR HEAD, and Readiness digest. After all current gates pass, the host automatically starts `user-review start`; no extra confirmation is needed to start, while the final explicit user decision remains required. An immutable session start time is created for that exact subject; a prior approval or change request cannot satisfy a newly started session. The runtime reads every page of Issue comments, PR conversation comments, formal PR reviews, and inline diff comments. It records numeric actor identity and type, object ID, creation/update times, body digest, formal review state, target commit, permalink, and deletion/resolution observations. Snapshot history is immutable so removed or edited feedback makes earlier approval evidence stale.

The Owner-selected User Review method may be a code review performed by ChatGPT. That review is the selected method and must not be duplicated by demanding another code review; it does not itself create the formal exact-subject User Review approval record. User Review remains incomplete until the current session's final explicit approval is recorded. This is separate from the mandatory Independent Review performed by the fresh host-native subagent.

Only a current human identity can decide User Review. A formal GitHub APPROVED review is valid only when authored by an eligible reviewer on the exact current HEAD; a PR author cannot approve their own PR. In explicitly selected `solo_owner` mode, preserve V1 delegated evidence and V2 `owner_local_tty_v1` evidence without changing their meaning. The standard V3 carrier, `PASES_USER_REVIEW_DECISION_V3`, records operator-reported direct same-conversation user approval plus the authenticated GitHub owner action under `chat_confirmed_gh_v1`; it is not a signed chat-host event or independent relay. It binds the exact repository, Issue, PR, HEAD, Readiness, ADC, session, prior complete feedback digest, plan and approval-scope digest. The chat host must supply the actual direct user-role event; if unavailable, block as `CHAT_PROVENANCE_UNAVAILABLE`. No owner-local approval TTY, SHA retyping, CLI flag, JSON/file consent, or manual GitHub UI comment is accepted. Carrier detection uses the actual carrier structure (the HTML comment prefix for owner decisions and the top-level JSON `schema` for User Review decisions); prose that mentions schema names is not a record, while unknown or malformed carrier-shaped records block. The typed carrier enters the existing full feedback/thread evaluator after complete direct/list/direct checks and owner/URL/session verification. Final Delivery re-reads the complete carrier chain and snapshot. Formal self-approval, generic comments, vague continuation, assistant text, stale subjects and replay never approve.

For this carrier, the verifier accepts a validated `UserReviewSession` object, not a caller-supplied session digest alone. It verifies the full Issue comment history with complete pagination and direct/list/direct reads of every carrier record. The first carrier in the `(repository, issue, PR, owner ID)` chain has `predecessor_comment_id: null`; each later carrier must point to the immediately preceding valid carrier comment ID, with strictly increasing comment IDs. Orphaned, skipped, missing, edited, deleted, duplicated, or cross-session replayed links fail closed. The current carrier's `created_at` must be strictly later than `session.started_at`, and `updated_at` must equal `created_at`.

For every listed and direct-read carrier, the verifier MUST validate the GitHub comment's actual `url`, `issue_url`, and `html_url` against the configured API/web hosts, exact repository, Issue number, and comment ID. It MUST also compare these fields across direct/list/direct reads. A body-declared repository or Issue, or agreement among copies that all point to a different Issue/repository, MUST NOT satisfy origin verification.

The evaluator seam is `evaluate_user_review(session, readiness, current_pr_head_sha40, snapshot, *, review_mode, pr_author_user_id, repository_owner_user_id, authenticated_verifier_user_id, allowed_human_user_ids, relay_approval, all_feedback_surfaces_read, ...)`. The dedicated read-only GitHub client obtains `authenticated_verifier_user_id` from `GET /user`; this identifies the principal that performed the reads and may differ from the owner. Its read route must be separately scoped from broker writes, and that separation must be positively verified; if not, User Review fails closed. It grants no approval authority and is never compared to the carrier owner. `repository_owner_user_id` is the trusted owner ID pinned by the approved repository/Issue authority (for this #63 successor ADC draft, `3744776`); it is passed explicitly and is not inferred from `authenticated_verifier_user_id` or the relay credential. Before evaluation, the client must validate the configured stable repository ID and exact `full_name` against the fresh `GET /repos/{owner}/{repo}` response, including `owner.type=User` and `owner.id == repository_owner_user_id`; for this draft the repository ID is `1401910271`. Missing or changed repository metadata, a non-User repository owner, or any mismatch fails closed; the runtime must not dynamically adopt a changed repository owner. The current PR author ID comes from the fresh pull request's `user.id` and must equal `repository_owner_user_id`; the carrier's `owner_id` and GitHub comment actor ID must also equal it. `allowed_human_user_ids` comes from approved repository review policy, not from `/user` or the relay credential. A formal approval by the PR author is always rejected in `solo_owner`, even when that author is allowlisted; only the verified typed carrier can provide that approval. The evaluator consumes the exact `UserReviewSession`, complete `FeedbackSnapshot`, resolved-thread set, and the verifier's typed `UserReviewRelayApproval`. The verified carrier remains `user-review-relay` evidence and is never converted into a formal `pr-review`, host-attested `chat`, or generic Issue-comment approval. In the feedback snapshot, the carrier's exact Issue-comment row is matched by comment ID and body digest and excluded from generic question handling only after successful carrier verification; other later feedback, deletion tombstones, incomplete feedback surfaces, or unresolved threads still block or supersede it.

The selected relay approval is persisted in the User Review result as typed evidence containing the carrier comment ID, canonical body SHA-256, stable owner ID, creation time, session SHA-256, predecessor comment ID, and delegated evidence channel. The result record binds that evidence to the full feedback snapshot SHA-256 and exact User Review subject. A new `PASES_USER_REVIEW_RESULT_V2` result schema carries this field; existing V1 records remain immutable and cannot prove a relay approval. Both `sync` and Final Delivery re-fetch and verify the full carrier chain and feedback snapshot, then re-run the evaluator and require the same selected evidence and result. A direct/list/direct disagreement, incomplete page, or changed/deleted record blocks both paths.

A PR conversation or inline comment requests in-scope changes only when its entire body has exactly these two lines:

```text
P-ASES-DECISION: CHANGES_REQUESTED
P-ASES-HEAD: <current full SHA-40>
```

The authenticated current human must have authored the comment; an inline comment's `commit_id` must equal the named SHA. Quoted, extended, malformed, stale-head, bot, unauthorized, and natural-language comments do not trigger the execution transition. Other comments remain questions. Changes requested on the current scope return the same Issue and PR to execution; a separately triaged scope change returns to requirements. Questions, pending reviews, unresolved discussion threads, stale HEAD/ADC/Readiness, and incomplete API reads remain blockers.

<a id="req-wf-010"></a>
<a id="req-wf-010-parent-integration-and-final-delivery"></a>
### 8.2 REQ-WF-010 Parent Integration and Final Delivery

Parent Integration uses the declared native child Issue set and dependency DAG. It reads every child Issue, native blocker edge, merged PR, standalone child-closing line, actual merge commit, merge timestamp, and final-main ancestry from GitHub. Each dependency must have merged no later than its dependent child. The child set, dependency graph, current main SHA, parent ADC, and typed Integration Verification/Acceptance records form one immutable subject. For this migration, legacy parent Issue #26 has no ADC pointer journal; the current approved child #31 ADC is therefore the authority for the parent ADC digest and the immutable `planning/p-ases/08-migration-contract.md` source at commit `f34f166f11bbbe6c45b1555827f37f9467b1e49b`. The evaluator verifies that declaration and source availability, then double-reads the child ADC pointer and parent Issue body while collecting the Integration snapshot.

**Parent evidence authority decision for this migration:** the exact-main GitHub Actions run, job, step, and Check Run API records are authoritative. Issue #26 comments store only a discoverable pointer/cache for the reconstructed result; a comment by itself is never proof. This is the selected resolution to the Git self-reference conflict: execution proof stays outside the commit whose SHA it names, and a deleted or edited comment fails closed without falling back to local files or comment-authored PASS claims. Typed Verification and Acceptance evidence is published outside `main` in canonical `PASES_PARENT_GATE_EVIDENCE_COMMENT_V2` Issue comments on #26. `delivery parent-evidence <issue> <kind> <run-id>` reads a completed run for the exact current `main` SHA and reconstructs its result and artifact bytes from those API responses.

New Verification evidence must use the latest `.github/workflows/ci.yml` `push` run and latest attempt for the exact current `main` SHA, `head_branch=main`, same-repository `head_repository`, completed/success, and GitHub Actions App ID `15368`. The run must contain the four fixed Python/OS matrix jobs; each job Check Run URL must resolve to a completed/success Check Run from that App on the same SHA and same repository. The API job steps `Compile runtime, tools, and tests`, `Check committed distributions before mutation`, `Unit tests`, `Validate repository documentation`, `Generate distributions`, `Check generated distributions`, `Validate distributions`, `Confirm generated paths remain unchanged`, and `Check committed diff whitespace` must each be completed/success in every matrix job. A newer failed attempt or run blocks new evidence publication.

New Acceptance evidence must use the latest `.github/workflows/parent-integration.yml` `workflow_dispatch` run and latest attempt for the exact current `main` SHA and same-repository `main` branch, also completed/success from App ID `15368`. Its `parent-acceptance` job Check Run and six named steps prove specification traceability, design traceability, test-oracle traceability, the exact canonical 16-Skill package, generated-distribution consistency, and distribution validation. That workflow is dispatched only after the fixed migration cohort is present; it does not permit the legacy 10-Skill package to pass.

The result stores run ID/attempt/path, every required job Check Run identity, step conclusions, cited artifact bytes, and SHA-256 digests. On publication and current Integration reads, the adapter re-fetches the latest matching workflow run and attempt, jobs, steps, and exact-SHA Check Runs, reconstructs the canonical V2 payload, and requires byte-for-byte equality. When validating an already-issued Activation, it instead pins the run ID and attempt stored in that Activation's V2 evidence comment and fetches that exact attempt plus its jobs from the GitHub Actions attempt API. It verifies the run still has the recorded workflow, event, repository, branch, and activation SHA and reconstructs every job, step, and Check Run from that attempt. A later run or attempt does not invalidate this historical evidence. If GitHub cannot return the pinned attempt or any provenance record is incomplete, changed, or unsuccessful, validation is BLOCKED; there is no fallback to comments or cached PASS data. A hand-authored result with plausible hashes, a local-only PASS, wrong App, stale SHA, failed/skipped step, or incomplete matrix is BLOCKED even when posted by the authenticated user.

This boundary avoids storing a commit's own SHA inside that commit. `delivery parent` and `issue integration-check` require exact Issue #26 comment IDs. For each ID, the reader GETs the comment, finds that same ID exactly once in Issue #26's paginated comment list, GETs it again, and compares ID, body, timestamps, Issue/API/HTML URLs, and author. It also requires exactly one evidence comment for each kind and current parent/main subject. `updated_at` must equal `created_at`; the current authenticated GitHub `User` ID must equal the comment author; the workflow provenance, payload subject, canonical bytes, result digest, artifact digests, and fixed check set must all match. A deleted ID, edit, duplicate subject, wrong repository/Issue, wrong author, malformed payload, changed ADC, stale main, failed/superseded run, or untrusted App blocks without fallback. GitHub comments can be edited or deleted, so this detects mutations at each read; it does not claim GitHub provides immutable comment storage.

Legacy parent #26 labels are migrated only by `delivery parent-migrate-labels 26`. Default invocation is read-only preflight: the Issue must be open in the same repository, and any conflicting kind/phase blocks. `--apply` re-reads the exact current labels, creates only the P-ASES-owned definitions needed for `kind:parent`, `phase:integration`, and the next `phase:user-review` transition when absent, and verifies each definition's exact name, description, and color. The owned definitions are `kind:parent` (`c5def5`, `P-ASES Issue kind: parent`), `phase:integration` (`0e8a16`, `Workflow phase: integration`), and `phase:user-review` (`d93f0b`, `Workflow phase: user review`). Existing definitions with different metadata fail without overwrite. It then adds only the needed parent/Integration labels, preserves unrelated labels such as `enhancement` and attention labels, and confirms the complete Issue state. A lost definition or Issue-label write response is retried by re-reading and recognizing the exact prior write; conflicting or incomplete states fail closed. Parent delivery does not run this migration implicitly.

After Integration passes, `delivery parent` moves parent Issue #26 from `phase:integration` to `phase:user-review` and starts one immutable parent review session. Its exact subject binds the repository, parent Issue, approved parent ADC digest, six child Issue/merge-SHA pairs, and Integration result digest. The first invocation starts the session; a decision must be a new parent Issue comment with exactly these two lines:

```text
P-ASES-DECISION: APPROVED
P-ASES-SUBJECT: <current parent User Review SHA-256>
```

`CHANGES_REQUESTED` may be used in the first line to withhold parent approval. Only the authenticated current human on the open parent Issue can decide. Edited/deleted comments, a decision predating the session, or a changed ADC, child merge, or Integration subject invalidates prior approval. Child User Review snapshot discovery accepts only `<64 lowercase hex>.json` filenames, verifies that the filename digest equals the parsed snapshot digest, and rejects unexpected files; `session.json` and `*.result.json` are not feedback snapshots. Parent approval only makes the result ready for a separate explicit activation decision; it does not close or activate the parent or authorize merge/release.

Final Delivery keeps human User Review, mode-specific GitHub review evidence, exact-HEAD Required Check evidence, explicit merge authorization, merge readback, Issue closure, and parent activation as separate gates. External-reviewer mode keeps its existing formal-review/legacy branch-protection behavior. Solo-owner mode does not inspect branch protection or Rulesets; GitHub enforces native branch and merge constraints when merge is requested. A delivery result never performs a merge, release, Issue close, or parent activation. Finalization only reports what GitHub confirms after a separately authorized merge.

Gate selection is recorded immutably when work starts and remains fixed if the PR HEAD changes or a check becomes blocked. `p-ases-v1` applies only to Issues created after activation. Activation requires all six child PRs to be merged by the repository owner with explicit user authorization, all six Issues closed, parent integration documentation/tests/16 Skills/distribution checks passing, and an explicit activation approval comment authored by the repository owner. A unique `PASES_ACTIVATION_V1` record binds the repository, child Issues and PR merge SHAs, integration-evidence digest, gate version, and activation commit.

Activation does not trust `PASES_INTEGRATION_EVIDENCE_V1` PASS fields, HTTPS references, or a caller-supplied digest by themselves. Its evidence references MUST identify exactly one parent Verification V2 comment and one parent Acceptance V2 comment, with the corresponding Actions run IDs and attempts. At issuance those references MUST be the latest successful matching run/attempt. On later Activation reads the runtime MUST pin the recorded run ID/attempt and reconstruct that exact historical attempt from GitHub's attempt-specific run and jobs APIs; a newer attempt or run MUST NOT replace it. Both pinned attempts MUST be successful on the activation commit SHA, use the approved parent ADC digest, and satisfy the fixed workflow, job, step, and trusted App ID 15368 requirements. If GitHub cannot return the exact attempt or its provenance, validation MUST fail closed. The six child Issues, PRs, and actual merge SHAs MUST match the Activation record and be present in that commit. Self-reported PASS fields, an HTTPS URL, or a digest without this API reconstruction cannot authorize Activation.

Activation approval, Activation record, and every referenced integration evidence comment MUST be unique, undeleted, authored by the repository owner’s stable GitHub User identity, attached to Issue #26, and unchanged since creation (`created_at == updated_at`). Each read MUST compare the direct comment, its unique Issue-list entry, and a second direct read using comment ID, body, timestamps, Issue/HTML/API URLs, and author ID/login/type. Profile and avatar fields are not part of this stable identity. Any edit, deletion, duplicate, author/identity mismatch, or readback failure MUST block the activation decision. The current default branch MUST contain the activation commit. After a valid activation, later main commits do not invalidate that historical record while its activation commit remains on main. Missing, stale, duplicated, or mismatched activation evidence blocks new P-ASES work.

Bootstrap evidence remains append-only and binds its exact ADC, PR, HEAD, CI, local checks, blockers, and a digest of the Bootstrap evaluator and trusted adapters. New results set `review_mode` to `WAIVED_BOOTSTRAP`, use `BOOTSTRAP_TECHNICAL_READY` for success, leave reviewer/context IDs null, review evidence empty, `separate_context_confirmed` false, and `can_request_final_user_review` false. Historical `BOOTSTRAP_REVIEW_READY` records remain readable with their original meaning and are never promoted automatically. The clean checkout is rechecked after local tests, after GitHub technical evidence collection, and before publication. Before and after publication the evaluator re-reads the complete ADC pointer, pinned gate selection, PR number/state/draft, base/head repository/ref/SHA, and full body including the exact standalone Issue-closing line. If any subject field changes after publication, a newer `BOOTSTRAP_BLOCKED` observation is appended and read back as the latest record. Tool changes append a new attempt without changing the pinned Issue gate; changes to the subject or evidence invalidate the previous result. The normal Delivery Readiness gate, trusted Required Check App-ID verification, phase transitions, review requirements for ordinary P-ASES issues, and separate explicit permission for PR merge remain unchanged.

The Bootstrap evaluator may live on a downstream PR while an earlier stacked PR is being evaluated. Run its CLI from the evaluator checkout, with `--root` set to a separate clean checkout of the target PR at its exact current HEAD. The evaluator code and fingerprint come from the evaluator checkout; local checks and branch/HEAD cleanliness checks run against the target checkout. Never copy downstream evaluator changes into the target branch or claim a result for a target HEAD different from the PR's current GitHub HEAD.

When migrating a legacy Issue-body ADC pointer to the append-only journal, retain the original `## Agent Development Contract` pointer block unchanged. The first journal record names the old pointer Comment ID as its predecessor (or `none` if there was no old pointer). Do not remove or edit that anchor unless a separately approved migration format records its exact prior bytes and predecessor.

Consumer Activation is separate from the fixed migration Activation. The consumer repository's approved Activation Issue ADC and append-only approval/record comments authorize only later-created non-PR Issues in that repository. New Gate Selections carry the exact Activation record identity; successor policy keeps prior selections pinned.

<a id="consumer-activation-workflow-contract"></a>
## 9 Consumer Activation workflow contract

<a id="req-f01-001"></a>
<a id="req-f01-001-repository-boundary"></a>
### 9.1 REQ-F01-001 Repository boundary

Migration issue numbers, child sets, branch pairs, and parent evidence MUST NOT supply authority in another repository.

<a id="req-f01-003"></a>
<a id="req-f01-003-append-only-approval-and-activation-history"></a>
### 9.2 REQ-F01-003 Append-only approval and Activation history

Consumer approval and Activation history are append-only comments. A record identifies the exact approved ADC, canonical Activation profile digest, setup PR merge and verified `merged_at`, admin, predecessor, and the exact trusted Required Check Run IDs with their name, App ID, head SHA, status, conclusion, and timestamps. For each required check, issuance selects the latest matching run created no later than `merged_at`, ordered by `(created_at, Check Run ID)` to resolve timestamp ties deterministically. The selected run must be completed successfully with `completed_at <= merged_at`. A failed or pending latest run at merge blocks Activation even if a later rerun succeeds; only a qualifying pre-merge run ID may be pinned. Verified PR `merged_at`, rather than the later comment publication time, is the effective Activation time. Historical reads fetch each recorded Check Run by ID and compare its pinned evidence and merge-time bound; later reruns do not replace the issuance-time evidence.

<a id="req-f01-005"></a>
<a id="req-f01-005-eligibility-by-activation-time"></a>
### 9.3 REQ-F01-005 Eligibility by Activation time

New P-ASES work is eligible only for same-repository non-PR Issues created strictly after verified setup PR `merged_at`. For a successor chain, choose the latest Activation whose verified merge time precedes the Issue creation time. Re-running gate-policy for an Issue with an existing valid Gate Selection reuses that exact historical Activation record and selection. Pre-Activation Issues remain untouched.

<a id="req-f01-007"></a>
<a id="req-f01-007-successor-activation"></a>
### 9.4 REQ-F01-007 Successor Activation

Policy or locator changes require a new setup PR and merge, append a successor Activation effective at its verified `merged_at`, and preserve prior records and selections. The successor governs only Issues created after that merge time.

<a id="req-f01-008"></a>
### 9.5 REQ-F01-008 Verified V2 Activation policy

The public Consumer Activation setup action MUST orchestrate discovery, safe setup-branch preparation, exact policy planning, any required owner decision and isolated device-auth Admin continuation, effective-policy verification, setup-PR creation, and post-merge V2 recording as one resumable transaction. Live Admin and Activation V2 operations MUST run only from an owner-controlled local interactive host (local Codex, local Claude Code, or owner-controlled local VM), pass the shared host-control guard, and use `isolated-gh-device`. Cloud, hosted, CI, remote, noninteractive, and unconfirmed contexts MUST block before live writes. The guard is an operational trust check, not cryptographic host attestation. The command MUST NOT require the user to run an unrelated manual Ruleset preparation flow before Activation. Before a V2 setup PR exists, the committed setup-branch profile bytes and exact HEAD MUST be bound to the canonical policy plan. The PR marker and V2 record MUST bind the verified setup branch, Ruleset ID, applied-record ID, and effective-policy digest. If current policy differs from an existing immutable setup PR proposal, the runtime MUST prepare a new exact setup generation and plan; it MUST NOT rewrite the old proposal or mark its old policy evidence as current. Before recording V2, the runtime MUST verify the default branch's active effective protection and complete trusted Required Check `(context, App ID)` set, and repeat the readback immediately before publication. It MUST read the branch, effective rules, Ruleset details, and legacy branch-protection endpoint; an HTTP 403 or partial response is `UNAVAILABLE`, never evidence that protection is absent. The Activation result MUST include a complete mode-specific required-setting inventory using `VERIFIED`, `NEEDS_APPLY`, `UNSUPPORTED`, or `BLOCKED`; in `external_reviewer`, V1 does not require the solo-owner managed Ruleset, so its inventory reports that setting as `UNSUPPORTED` without treating it as unmet. It MUST NOT claim `ACTIVE` while a mode-required setting is unmet.

<a id="req-f01-009"></a>
### 9.6 REQ-F01-009 Approved Ruleset management

Ruleset planning, ownership verification, effective-policy verification, and Ruleset writes MUST be owned by Consumer Activation. Ruleset writes MUST use the existing canonical plan and only the uniquely owned repository Ruleset named `P-ASES Final Delivery (managed)`. In `solo_owner`, the plan MUST bind repository and owner IDs, the Activation Issue number, default branch and current effective policy, exact committed setup-branch profile bytes/HEAD, ADC generation and Activation predecessor, trusted checks, existing managed Ruleset identity/digest and applied-record predecessor, desired payload, and open-PR impact. The setup PR MUST NOT be created until that policy is `VERIFIED`. If a write is required, one fresh `RULESET_PLAN_APPLY` chat-confirmed V3 owner decision MUST bind the exact blocker-free plan SHA and displayed approval scope. The owner action also appends and owner-authenticates the existing exact two-line Issue #57 approval through `gh`; the implementation agent does not self-authorize. Apply uses the isolated Admin browser-device client and existing durable intent, single POST/PUT, readback, and ownership-record path. An exact match is a zero-write `NOOP` and does not require a write approval. After interruption it may recover only the uniquely matching expected Ruleset and verified effective policy, then append or reuse the exact applied record without another write. An unowned same-name Ruleset, legacy conflict, 403, stale plan, or ambiguous state MUST block without mutation, blind retry, or rollback. Organization Rulesets, unrelated repository settings, permissions, secrets, and legacy protection remain read-only. For ordinary `single` and `child` workflows in either `solo_owner` or `external_reviewer` mode, Phase, Verification, Readiness, User Review, Final Delivery, and owner merge gates MUST NOT read or require Ruleset inventory, managed ownership, `NOOP`, or effective policy as a P-ASES PASS condition. GitHub enforces its branch and merge constraints when the merge is requested.

<a id="req-f01-010"></a>
### 9.7 REQ-F01-010 Existing Issue preservation

V1 Activation comments, their original `merged_at`, and every existing Issue ADC, Gate Selection, phase, PR binding, and evidence remain immutable. Runtime bug fixes and current CI, Ruleset, and review checks apply to existing Issues. An existing Issue continues to use its selected Activation and MUST NOT be moved to a successor Activation.

<a id="req-f01-011"></a>
### 9.8 REQ-F01-011 V2 effective time

V2 setup, approval, and Activation records are append-only and versioned. V2 becomes effective at the GitHub `created_at` timestamp of the Activation record comment. An Issue created after setup PR merge but before that comment is not authorized by V2; if eligible under V1, it continues to use V1.

<a id="req-f01-012"></a>
### 9.9 REQ-F01-012 Activation history prefix

Validation of an existing Gate Selection MUST validate only the authenticated Activation-history prefix ending at its selected record. A V2 record binds the exact earlier Ruleset applied-policy record ID and setup branch generation, and its Ruleset ownership history is validated only through that record. Corruption after either selected prefix MUST NOT invalidate the existing Issue. Corruption within either selected prefix MUST block. New Gate Selections and successor Activation issuance MUST validate the complete Activation and Ruleset ownership histories.

<a id="req-f01-013"></a>
### 9.10 REQ-F01-013 Bootstrap and review gates

Issue #63 MUST complete implementation first, then separately formalize the exact successor ADC and its generation-scoped Phase evidence. Before PR #64 merges, its current-HEAD CI, independent review, User Review, Final Delivery, and separate exact-HEAD `PR_MERGE` decision MUST pass. Final Delivery MUST evaluate current P-ASES evidence (including exact HEAD, approved ADC/Binding/Phase, Verification, Acceptance, Self-Audit, fresh Independent Review, User Review, trusted Required Checks, PR identity, and mergeability) without reading or requiring a Ruleset or effective policy. For `solo_owner`, it emits `PASES_FINAL_DELIVERY_V3` with `review_mode=solo_owner`, null `branch_protection_sha256`, and only the P-ASES evidence it actually verified; existing V1/V2 payload and digest semantics remain unchanged. Final Delivery readiness is not merge authorization. GitHub applies its own branch and merge constraints at merge time; a rejection or ambiguous response blocks or enters read-only recovery, without bypass or a second merge request. Because Activation is post-merge work, only PR #64 uses one standalone `Refs #63` line, not a GitHub auto-closing association; ordinary PRs retain standalone `Closes #N` and GitHub's normal auto-close behavior. The shared closer detector MUST recognize GitHub's case-insensitive `close`/`closes`/`closed`, `fix`/`fixes`/`fixed`, and `resolve`/`resolves`/`resolved` keywords, with an optional colon and either `#N` or `OWNER/REPO#N`. Repository-qualified references are normalized case-insensitively before Issue identity is compared; a same-number reference to a different repository is not the same Issue. The #64 merge preflight MUST read the complete PR body, all commit messages, the planned merge message, GitHub `closingIssuesReferences`, and Issue cross-reference metadata; any auto-close relation, closer token, or incomplete read blocks the merge. Immediately after merge, Issue #63 MUST read back OPEN. The Setup PR for Consumer Activation V2 has its own exact-HEAD review and merge decision and is performed after PR #64. Only a fully verified V2 `ACTIVE` record and effective policy whose `created_at` is later than the PR #64 merge allow the finalizer to close #63 with one durable close intent and GitHub API write. If Activation or policy verification fails, #63 stays OPEN. All Ruleset discovery, plan/apply, ownership evidence, and effective-policy verification needed for Activation occur in the post-merge Consumer Activation flow; they are not pre-merge PR #64 gates.

The typed Activation-owned current-base transition remains narrow for any supported workflow where Activation precedes a PR merge. It MUST preserve the original `ExecutionBinding`, V1 `PRBinding`, and frozen base bytes, and accepts only a create-only record proving frozen base A is an ancestor and the first parent of the exact Activation V2 setup merge B; the V2 record and setup PR identities agree; the setup PR and A..B change only `.agent/project.json`; current main and PR base equal B; the profile bytes at B and exact PR HEAD match the Activation profile digest; and the target code patch is unchanged across A→B. The latest PRBinding generation references this evidence. `pr ensure`, Readiness, and Final Delivery apply the same live verification. Ordinary or unknown main advancement, wrong setup PR/merge SHA, profile mismatch, missing evidence, or a different PR/repository/Issue blocks; generic base drift is never accepted. In the Issue #63 two-stage order, Activation occurs after PR #64 merges, so a later Activation base advance is not a prerequisite or substitute for #64's pre-merge base checks.

<a id="req-f01-014"></a>
### 9.11 REQ-F01-014 Activation-scoped temporary admin authentication

Only `delivery consumer-activation-admin-plan` and `delivery consumer-activation-admin-apply` may request temporary administrator authentication. Each command uses a separate child-process session. `isolated-gh-device` is the only supported mode: run `gh auth login --hostname github.com --web --git-protocol https --insecure-storage` from the confirmed local interactive terminal in a new private mode-0700 `GH_CONFIG_DIR`, with ambient `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`, and `GITHUB_ENTERPRISE_TOKEN` removed from the login and later Admin API child environments. Verify the authenticated human owner and repository Admin permission before complete policy reads. If local confirmation, device authentication, owner identity, or any policy source is unavailable or incomplete, stop as `UNAVAILABLE/BLOCKED`; never use normal `gh` configuration, PAT, App, Network-secret, SDK, direct REST, or another writer as a fallback.

Device authentication is authentication only, not approval. Clear the private device config in `finally`; deleting that directory does not revoke the GitHub OAuth grant. Normal `GH_CONFIG_DIR`, token variables, and ordinary `gh` commands remain unchanged. Do not expose credentials in logs, arguments, JSON, artifacts, or chat. Same-OS-user subprocesses are not a strong sandbox.

Before any Ruleset action, the selected Admin client MUST verify the authenticated stable user ID equals the configured repository owner ID, repository ID and owner login match, `permissions.admin=true`, collaborator permission is `admin`, and branch protection, Ruleset inventory, and effective branch rules are fully readable. A 403 or incomplete read is unavailable, never evidence of absent protection. Admin-plan is read-only against GitHub and writes a canonical local plan only when blocker-free; Admin-apply revalidates that exact plan and the independent operation approval before using the existing durable-intent/single-writer/readback path. Ruleset verification remains part of the resumable Activation transaction. GitHub API calls in P-ASES use only `gh` through `runtime/p_ases/github.py`; request JSON is passed on stdin with `gh api --input -`.

<a id="req-f01-015"></a>
### 9.12 REQ-F01-015 Owner-authorized decisions and separated operations

For self-authored `solo_owner` User Review, `evaluate_user_review` receives the validated session, full feedback snapshot, pinned `repository_owner_user_id`, fresh `pr_author_user_id`, independent `authenticated_verifier_user_id`, policy-derived `allowed_human_user_ids`, and typed V1, V2, or V3 User Review evidence. Repository ID `1401910271` and owner User ID `3744776` are pinned independently of the authenticated read-only verifier. Fresh repository metadata and PR author data must match those pins; comment actor ID must match the pinned owner. The read-only verifier is a transport identity and may differ from the owner; it is never approval evidence or the owner allowlist. A PR author's formal `APPROVED` review is never accepted in `solo_owner` mode.

V1 delegated-relay and V2 `owner_local_tty_v1` meanings remain unchanged. V3 uses `PASES_OWNER_DECISION_V3` or `PASES_USER_REVIEW_DECISION_V3` and `evidence_channel=chat_confirmed_gh_v1`. It records operator-reported direct same-conversation user approval plus an authenticated GitHub owner action; it is not an independent relay and not a signed or cryptographically authenticated chat event. The approval scope digest binds the presentation; it does not attest who said it. The chat integration must receive the actual user-role event in the same conversation and ask for approval of the displayed repository, Issue, operation, exact ADC/plan SHA or PR+HEAD, and scope. A vague continuation, assistant text, another chat without trusted transfer, CLI flag, arbitrary JSON/file, or unverified role fails with `CHAT_CONFIRMATION_REQUIRED` or `CHAT_PROVENANCE_UNAVAILABLE`. If the host cannot provide the direct user-role event, do not claim approval or write a V3 record. Owner-decision carriers are recognized only at the exact HTML comment prefix; User Review carriers are recognized from the top-level JSON `schema`. Incidental prose mentions do not enter either history, and unknown/malformed records in carrier position still fail closed. No approval TTY, plan-SHA retyping, or manual GitHub UI comment is required.

`delivery owner-authorize-plan` remains a read-only exact-scope preview. The CLI `owner-authorize-commit` fails closed because a CLI cannot authenticate a chat user-role event. Only the in-process chat integration may pass an ephemeral typed grant to the runtime. Immediately before a GitHub write it must revalidate the clean source HEAD, exact plan, pinned repository/owner IDs, current Issue/PR/ADC/Ruleset subject, and authenticated GitHub actor ID. A stale subject, non-owner actor, 403, malformed comment URL, edited/deleted/duplicate record, or ambiguous write blocks. Every GitHub API operation uses `gh` via `GitHub`; POST JSON goes to stdin. Repository fetch/push and remote-ref/object readback use the existing Git boundary and are the only GitHub-hosted transport exception; they do not read or write GitHub API state. Read-only recovery never repeats a POST.

`ADC_SUPERSEDE`, `RULESET_PLAN_APPLY`, `USER_REVIEW`, and each exact PR_MERGE target are separate one-time operations. V3 records bind repository, Issue, operation, subject digest, plan and approval-scope digests, optional PR/HEAD, owner actor, evidence channel, and append-only predecessor. Keep all V1/V2 bytes and meanings. Cross-version replays, duplicates, gaps, edits, deletions, incomplete pagination, and wrong direct/list/direct identity fail closed. `ADC_SUPERSEDE` binds the successor bytes and current approved predecessor pointer; after its exact approval, the existing ADC writer publishes/readbacks the generation. The phase runtime verifies the typed V3 `ADC_SUPERSEDE` decision against the current ADC SHA before appending technical Intent/Applied records. This is automatic technical phase evidence and does not create a separate `PHASE_REBASE` decision. `RULESET_PLAN_APPLY` binds the exact blocker-free Ruleset plan; after V3 owner decision it also appends and owner-authenticates the existing exact two-line Issue #57 approval, then uses the existing single Ruleset writer. `USER_REVIEW` V3 binds exact session, Readiness, ADC, PR HEAD, prior full feedback digest, plan and approval scope; its typed evidence enters the same evaluator and Final Delivery rereads the full carrier chain and feedback snapshot. It never creates a formal self-approval. Setup PR merge and PR #64 merge each require separate exact current HEAD plans and approvals. A merge is issued at most once after all gates pass; uncertain responses are resolved by GitHub readback only.

For Issue #63, preserve the existing `PASES_PHASE_REBASE_INTENT_V1` / `PASES_PHASE_REBASE_APPLIED_V1` pair as the immutable record of the original physical `ready -> requirements` label update, bound to its historical baseline and first approved successor ADC pointers. Both publicly published V1 payloads include `executor_user_id`; validate it against the stable GitHub User author and require the Applied author to match the Intent author. Retain backward compatibility for a V1 payload whose optional field is absent by using the stable GitHub User author as actor evidence; do not reinterpret V1 against a newer current pointer or rewrite history. Ordinary later ADC generations append contiguous `PASES_PHASE_REBASE_INTENT_V2` / `PASES_PHASE_REBASE_APPLIED_V2` pairs linked to the immediately preceding Applied ID and canonical digest. The two exact #63 recovery generations authorized by the current ADC use V3 instead, as defined by REQ-F01-018. Duplicates, skipped or incomplete earlier generations, pointer drift, edited evidence, and missing predecessors block. When an ordinary V2 generation finds #63 already at `phase:requirements`, it uses `adopt_existing_requirements`, preserves the complete sorted label set, and makes zero label-write calls. Every append rechecks full history, Issue body/labels, approved ADC pointer, and authenticated executor. An interrupted Intent may be completed only by appending its exact matching Applied record after readback; a completed generation is a read-only `NOOP`.

Before a new ADC is published with `state=approved`, the shared approval-ready preflight MUST reject a draft/proposal title, a draft-only header, a nonfinal `State`/`Status`, a malformed predecessor declaration, or a declared predecessor that does not match the current verified approved pointer. An Issue #63 successor MUST declare that current pointer. The owner-authorization preview, chat-confirmed commit, ADC publisher, and direct CLI publication MUST use the same check before any publication write. This preflight does not grant or replace exact-SHA approval. Structural `parse_adc`, historical-generation verification, and draft publication retain compatibility with immutable older approved records whose body contains draft-only text; no historical comment or pointer is rewritten.

<a id="req-f01-016"></a>
### 9.13 REQ-F01-016 Native Independent Review execution and confidence

A current exact-subject Independent Review requires one dedicated fresh host-native child reviewer to be spawned and joined and to return its own valid result for the repository, Issue, PR, approved ADC, HEAD, complete diff, checklist, and test evidence. Its V2 context artifact must provide an evidence-backed result for every current ADC requirement and Reviewer Checklist ID, with exact set equality; an omitted, duplicated, unknown, or non-PASS unit blocks. The child authors the complete result. The host must perform the child lifecycle even when it cannot provide spawn/session, reviewer, or implementation-binding identifiers. Those identifiers are optional provenance metadata: record every value the host provides; report `HIGH` confidence only when all required available identities match, and report `LIMITED` with the missing identifiers otherwise. Missing identifiers alone never mean the review was skipped and never block an otherwise valid review.

No child result, failed or unknown spawn/join, same-context reviewer identity, stale or malformed result, available mismatching binding, incomplete checklist/unit set, non-PASS verdict, unresolved A/B finding, or unresolved reviewer-designated blocking C finding remains a blocker. `PASES_INDEPENDENT_REVIEW_V3` carries exact review-unit results and a boolean `blocks_readiness` on each finding; it may be true only for C. Unresolved A/B findings remain blocking by severity, and unresolved C findings block only when the child marks them. A parent or implementation agent cannot author or complete a missing child result. The raw child result remains unchanged. Preserve V1/V2 artifact bytes and all other Verification, Acceptance, Self-Audit, Required CI, Readiness, User Review, Final Delivery, and merge gates. Context IDs and operator-reported host IDs are not cryptographic proof of host authenticity.

<a id="req-f01-018"></a>
### 9.14 REQ-F01-018 Exact Phase evidence recovery

For Issue #63 only, the current approved ADC authorizes `PASES_PHASE_REBASE_INTENT_V3` / `PASES_PHASE_REBASE_APPLIED_V3` for exactly two incomplete historical ADC edges: #6271832228 (SHA-256 `221e62a86a5b682237948abec1ee287d24d3808a9ad4fa22960be2c869fdcd05`) → #6468215907 (SHA-256 `6b2ab1c83aead86efe602b700bdfd33807d1675a56089a6a3ffc29175e2b601a`), then #6468215907 → #6469056354 (SHA-256 `f03465611fda6df485b323beab212f132cb9df2145827d46d0f0525445584efe`). Preserve all V1 and V2 records and bytes. The first V3 edge records and, only if the complete current label state is exactly `phase:execution`, performs at most one label update to `phase:requirements`. The second edge adopts existing `phase:requirements`, records identical before/after labels, and performs zero label updates. Each V3 Intent and Applied record binds the exact ADC predecessor/successor IDs and SHA-256 values, immediately preceding Applied ID and payload digest, Issue body digest, full sorted label state, operation/phases, and authenticated executor. Every mutation is followed by exact readback. Exact retries are read-only; an interrupted write may append only its matching Applied record after proving whether the one permitted label update already took effect. Any other ADC edge, phase, label change, history gap, edited/deleted record, duplicate, actor mismatch, or uncertain API result blocks without a repeated label write. After both exact recovery generations, ordinary later ADC generations use V2.

<a id="req-f01-031"></a>
### 9.15 REQ-F01-031 Generic Phase restart authorization

The current approved ADC may contain one strict marker block `<!-- PASES_PHASE_RESTART_AUTHORIZATION_V1\n<canonical-json>\n-->` outside fenced code. Its JSON has exactly `schema`, `target_issue`, `from_phase`, `to_phase`, `max_applications`, and `reason`; it must be canonical, unique, and have schema `PASES_PHASE_RESTART_AUTHORIZATION_V1`, `target_issue=self`, `from_phase=execution`, `to_phase=requirements`, and integer `max_applications=1`. `reason` is trimmed non-empty text of at most 500 characters with no control characters. The whole current ADC pointer/SHA and marker digest identify the authority. Prose, CLI flags, local files, assistant text, fixed Issue IDs, or SHA allowlists are not authorization.

<a id="req-f01-032"></a>
### 9.16 REQ-F01-032 Eligible Issue and Binding

The generic restart accepts only an open non-PR ordinary Issue with exactly one kind label in `{kind:single, kind:child}`, exactly one `phase:execution`, and a fully verified current ExecutionBinding. Repository/Issue IDs, current approved ADC pointer/SHA, frozen base, dedicated branch, worktree, initial HEAD, and Binding generation must all match. Read every label and full ADC/Binding/Phase history before a write. Missing, stale, edited, duplicate, mismatched, incomplete, 401/403/404, 429, or 5xx reads block with zero GitHub writes. Issue #63 remains on its existing specialized path.

<a id="req-f01-033"></a>
### 9.17 REQ-F01-033 Append-only Phase restart records

Append canonical `PASES_PHASE_RESTART_INTENT_V1` and `PASES_PHASE_RESTART_APPLIED_V1` technical records. Bind repository name/ID, Issue number/stable ID, complete sorted labels before/after, approved ADC comment ID/SHA/length, Binding generation ID/digest, predecessor active Phase generation ID/digest (nullable only when none exists), authorization marker digest, transition, reason, authenticated human executor ID, and canonical UTC timestamps. The predecessor is the latest verified Applied or Phase Decision event before Intent. An incomplete restart Intent from any earlier ADC generation blocks new Phase operations. Restart history discovery MUST conservatively retain any comment whose first non-whitespace text begins `PASES_PHASE_RESTART_` or whose bounded malformed comment prefix made only of comment punctuation/whitespace is followed by that reserved family; it MUST then reject every noncanonical candidate instead of treating it as absent. Ordinary prose that mentions the family away from the comment-header position is not a candidate. Read each record direct/list/direct and validate Issue/repository/API/HTML URLs, author, created/updated equality, and exact body. Preserve every predecessor ADC, Binding, Phase Decision/receipt, Gate, and Activation record byte-for-byte.

<a id="req-f01-034"></a>
### 9.18 REQ-F01-034 One-shot label transition and recovery

After complete read-only preflight, append and verify the exact Intent; re-read the approved ADC, Binding, full labels, and predecessor Phase generation; then perform at most one full-label replacement from the exact `phase:execution` snapshot to the exact `phase:requirements` snapshot and read it back. Append Applied only after exact state readback. On timeout or ambiguous response, reconcile through read-only reads; never resend a possibly applied label write. An exact completed replay is read-only `NOOP` only when the complete current labels equal the recorded after-state, or a contiguous, current-generation Phase Decision chain proves the current phase. Every receipt used by that chain is independently revalidated against the current ADC artifact allowlist, ADC-authorized skip reasons, the exact regular blobs and SHA-256 values at its recorded branch commit, and the normal READY traceability checks; its Issue carrier must still be immutable and authored by the authenticated GitHub User. Historical READY validation MUST materialize every relevant traceability target at the receipt commit, including documents linked for ADC-authorized skipped specification or design roles, while loading executable test sources only from rows for requirements in the current ADC. The ordinary traceability validator MUST still enforce path, anchor, allowlist/skip, exact-blob, and source checks. A later `phase:execution` requires rebuilding the same-generation READY proof. Rollback, unexplained phase movement, malformed reserved restart or Decision markers, or unrelated label changes block. GitHub API label replacement does not provide a repository-wide lock; the runtime enforces one P-ASES writer and rechecks immediately before the write.

<a id="req-f01-035"></a>
### 9.19 REQ-F01-035 Active Phase generation

The exact Applied record starts the new active Phase generation, bound to the current approved ADC and Binding generation. Normal phase evidence must verify that generation before issuing new receipts. After a restart, new phase receipts use `PASES_PHASE_DECISION_V2`, binding the Applied comment ID and exact body SHA-256; V1 serialization and prior V1 bytes remain unchanged. The decision reader recognizes the exact plain-text `PhaseDecision.body()` format for both V1 and V2 and verifies each history carrier direct/list/direct. Every generation lookup MUST compare the initially discovered restart/Decision candidate IDs and exact bodies with the subsequent verified history before returning, so an edited/deleted marker cannot disappear between reads. When no restart record exists, a current-generation lookup MUST reject malformed reserved Phase Decision candidates and canonical V2 decisions that lack an Applied predecessor; well-formed historical V1-only history remains compatible and returns the ordinary ADC/Binding generation. Existing specification/design/ready/execution receipts remain readable historical evidence but cannot satisfy a transition in the restarted generation. Requirements through later Execution evidence are produced again with the normal validators.

<a id="req-f01-036"></a>
### 9.20 REQ-F01-036 Issue #63 compatibility

Keep Issue #63's specialized phase-rebaseline implementation, ADC/Owner checks, V1/V2/V3 receipt readers, and recovery semantics unchanged. The generic command rejects Issue #63 and never routes it through the ordinary path. Do not change PR #64, Activation Issue #57 V1, or Issue #63 history.

<a id="req-f01-037"></a>
### 9.21 REQ-F01-037 ADC is the sole Phase restart approval

The exact approved ADC and its single valid typed authorization are the sole approval for this one phase reset. No separate Owner plan, terminal input, approval comment, or chat confirmation is required. Intent/Applied comments are technical records, not approval. This authority cannot be reused for Ruleset, Activation, review, merge, or Issue closure.

<a id="req-f01-038"></a>
### 9.22 REQ-F01-038 Missing historical Binding provenance

When the original ExecutionBinding bytes are unavailable, report BLOCKED_BINDING_PROVENANCE_MISSING and keep the reported five-generation digest as an opaque historical reference. Its provenance remains UNVERIFIED. Never reconstruct, relabel, append to, or overwrite that history, and never synthesize a V1 ExecutionBinding or describe this epoch as a sixth Binding generation.

<a id="req-f01-039"></a>
### 9.23 REQ-F01-039 One-time epoch authorization

Only the exact approved successor ADC authorization marker may create a prospective Issue #71 execution epoch. Bind the current approved ADC bytes, repository and owner IDs, Issue identity and body digest, predecessor ADC and active Phase generation, retired Intent, selected base and branch, transition, reason, and max_applications=1. Missing, changed, duplicate, stale, or reordered values block before a write.

<a id="req-f01-040"></a>
### 9.24 REQ-F01-040 Append-only epoch journal

Record a distinct canonical V2 Intent and matching Applied comment. Bind stable repository and Issue IDs, authenticated owner actor, current ADC pointer and marker digest, predecessor Phase generation, retired V1 Intent identity and digest, UNVERIFIED Binding provenance, exact base and branch, complete before/after labels, unique epoch ID, timestamps, and exact Intent digest. GitHub is the durable journal; local state is only a verified attachment for that epoch.

<a id="req-f01-041"></a>
### 9.25 REQ-F01-041 One-shot epoch migration

After complete direct/list/direct readback, establish the dedicated branch and workspace at the exact authorized base, append one Intent, make at most one complete-label replacement from phase:ready to phase:requirements, verify the full Issue snapshot, and append one matching Applied record. An interruption, timeout, duplicate, or mismatch is read-only recovery; never resend an ambiguous label update or append a duplicate record.

<a id="req-f01-042"></a>
### 9.26 REQ-F01-042 V2 current-epoch evidence

A complete V2 Intent/Applied pair and verified workspace attachment establish the current execution epoch. Phase, readiness, verification, review, PR, and delivery readers for Issue #71 must bind to that epoch and accept only its current evidence. Earlier Phase receipts and V1 history remain immutable and readable as history but cannot yield current-epoch PASS. Missing, stale, duplicated, edited, or mismatched epoch state fails closed.

The Issue #71 PR bridge stores the active digest in `PASES_PR_BINDING_V4.execution_epoch_sha256`; its work checkpoint stores it in `PASES_WORK_CHECKPOINT_V3.execution_epoch_sha256`. Neither schema may also carry an ExecutionBinding V1 or Issue #63 adoption identity. Ordinary V1 and adopted PRBinding/checkpoint bytes remain unchanged. `work base`, `work branch`, `work bind`, and `work recover` cannot create or reconstruct the Issue #71 epoch; the dedicated epoch reader is authoritative.

<a id="req-f01-043"></a>
### 9.27 REQ-F01-043 Agent-neutral local eligibility

One shared eligibility guard at CLI and direct-runtime live-operation entrypoints admits owner-controlled local interactive Codex, Claude Code, and owner-controlled local VMs with identical semantics. It requires an interactive owner-controlled host, operator confirmation, authenticated owner identity, and complete current Admin readback. Known hosted, Cloud, CI, remote, noninteractive, and unknown-control contexts are rejected before live writes. Agent identity and absence of a Cloud marker are not proof of locality; owner control is an operational assumption, not cryptographic host attestation.

<a id="req-f01-044"></a>
### 9.28 REQ-F01-044 Isolated device authentication and complete Admin readback

Live Admin access uses only isolated-gh-device and gh api with a fresh private mode-0700 GH_CONFIG_DIR. Remove GH_TOKEN, GITHUB_TOKEN, GH_ENTERPRISE_TOKEN, and GITHUB_ENTERPRISE_TOKEN from Admin children. Never fall back to ordinary credentials, PAT, App tokens, network secrets, SDKs, direct REST clients, or a second writer. Repeat complete local policy readback before any proposed plan or apply. 401, 403, 429, 5xx, malformed, incomplete, or identity-mismatched reads remain UNAVAILABLE/BLOCKED; a legacy-protection 404 is NOT_CONFIGURED only after all required repository, identity, branch, effective-rule, and Ruleset reads are complete and consistent.

<a id="req-f01-045"></a>
### 9.29 REQ-F01-045 Separated Ruleset and merge authority

ruleset_management.py::apply_ruleset_plan remains the sole Ruleset writer. Applying a Ruleset requires separate exact-plan RULESET_PLAN_APPLY authority for the recomputed current plan and complete before/after readback. Setup PR merge requires separate exact-HEAD PR_MERGE authority. ADC approval, authentication, Issue edits, epoch creation, CI, and code review authorize neither operation. Missing chat user-role provenance yields CHAT_PROVENANCE_UNAVAILABLE and zero approval-dependent writes. Keep Issue #63 open until V2 ACTIVE and all post-activation and time-order checks pass.

<a id="req-f01-046"></a>
### 9.30 REQ-F01-046 Compatibility and epoch test coverage

Preserve Issue #57 V1, Issue #63 and PR #64 history, predecessor ADC/Binding/Phase comments, and Issue #72/PR #73 byte-for-byte and behavior-for-behavior. Cover epoch authorization, journaling and recovery; active-reader isolation; local Codex/Claude parity and local VM acceptance; hosted, CI, remote, and unknown-context refusal; direct-runtime enforcement; device-auth separation; Admin 401/403/404/429/5xx and partial reads; stale plans; separate approvals; and zero writes on every blocked path.

<a id="req-f01-047"></a>
### 9.31 REQ-F01-047 Retire the first V1 migration

Preserve the first successor ADC, its exact incomplete Intent, dedicated branch, predecessor ADC/Phase/Binding records, Issue #57 V1, Issue #63, PR #64, and Issue #72/PR #73 unchanged. The incomplete V1 Intent is retired history: never edit, delete, retry, complete, attach, or select it as the current epoch.

<a id="req-f01-048"></a>
### 9.32 REQ-F01-048 Exact V2 marker binding

The sole new migration authority is the exact PASES_EXECUTION_EPOCH_AUTHORIZATION_V2 marker in the current approved ADC. It binds the predecessor ADC, retired Intent and body digest, active Phase Applied and digest, repository/owner/Issue identities, exact Issue body digest, base ref/SHA, dedicated branch, reason, ready-to-requirements transition, and max_applications=1. Any missing, changed, duplicate, stale, or reordered field blocks before writes.

<a id="req-f01-049"></a>
### 9.33 REQ-F01-049 Distinct V2 Intent and Applied records

The V2 journal binds the current ADC marker digest, stable repository and Issue IDs, owner actor, predecessor Phase generation, retired V1 Intent, old Binding provenance UNVERIFIED, exact base and branch, complete labels, unique epoch ID, canonical timestamps, and exact Intent body digest. V1 and V2 journals remain distinct, and ExecutionBinding V1 is never mutated.

<a id="req-f01-050"></a>
### 9.34 REQ-F01-050 Partial migration is permanently non-retryable

Create the authorized epoch-2 branch and workspace from the exact base, then perform the one authorized Intent/label/Applied sequence. On interruption or ambiguous outcome, recovery is read-only. Any partial V2 result stays blocked and requires a separately approved successor ADC that defines the next safe action.

<a id="req-f01-051"></a>
### 9.35 REQ-F01-051 Fresh Phase evidence before implementation

Keep the Issue body unchanged through the migration and fresh requirements, specification, design, and ready Phase receipts so the pinned body digest remains valid. Establish the new epoch before issuing any current-epoch Phase PASS. Retired V1 Intent and predecessor READY/PASS receipts remain history and cannot produce current-epoch PASS.

<a id="req-f01-052"></a>
### 9.36 REQ-F01-052 Local Activation V2 implementation scope

After the new epoch and Phase sequence pass, implement the inherited Issue #71 local Activation V2 contract, including common CLI and direct-runtime locality enforcement, local Codex and Claude Code parity, isolated device authentication, and Admin readback failure semantics. Reuse the merged Activation V2 implementation and sole Ruleset writer. Require separate exact-plan RULESET_PLAN_APPLY and exact-HEAD PR_MERGE authority; do not add a provenance bypass.

<a id="req-f01-053"></a>
### 9.37 REQ-F01-053 Synchronized artifacts and distributions

Update the affected specifications, design, test Oracles and traceability, applicable workflow Skills, all three adapter READMEs, and Issue status evidence. Generate dist outputs only through python tools/build_dist.py. Keep the OpenAI, Claude, and Antigravity host packages independent.

<a id="req-f01-054"></a>
### 9.38 REQ-F01-054 Required focused and regression tests

Cover retired V1 handling, exact V2 marker and journal validation, active-reader isolation, one successful transition, failure after each V2 write boundary, local Codex/Claude parity, local VM acceptance, Cloud/hosted/CI/unknown refusal, direct-runtime enforcement, authentication separation, Admin read failures, separated approval gates, and zero writes on every blocked path.

<a id="req-f01-067"></a>
### 9.39 REQ-F01-067 Epoch-3 predecessor preservation

Preserve every predecessor ADC, Binding, epoch, Phase receipt, Issue comment, and PR #74 byte-for-byte. The historical Binding remains UNVERIFIED; the epoch-3 execution identity is a distinct forward generation and never claims to restore or extend that Binding. Only the exact current approved successor ADC pointer and verified epoch-3 Intent/Applied pair and attachment can establish the active generation.

<a id="req-f01-068"></a>
### 9.40 REQ-F01-068 Canonical Phase artifact impact

The approved successor ADC must parse exactly one Specification row for docs/specs/workflow-spec.md and docs/specs/runtime-spec.md, one Design row for docs/design/workflow-design.md, and one Testing row for docs/testing/pases-lifecycle-tests.md, docs/testing/runtime-tests.md, and docs/testing/traceability.md. Commit these final bytes before issuing fresh Phase receipts. Other impacted runtime, tests, Skills, adapters, status evidence, and generated distribution files remain within the inherited contract but do not change the Phase artifact-role rows.

<a id="req-f01-069"></a>
### 9.41 REQ-F01-069 Frozen migration preflight

Before the one-time migration, verify the exact approved ADC and predecessor chain, complete Issue body and labels, pinned repository/Issue/owner IDs, old epoch and READY evidence, deviation and blocker records, PR #74 head, main@07481c4b451a81750a6c2e1a6a18bdfd4e3459c2, and the existing clean local epoch-3 branch at that base with no remote branch. Drift, missing evidence, or incomplete reads block before a journal or label write. Do not recreate, reset, commit, or push the branch as part of this migration preflight.

<a id="req-f01-070"></a>
### 9.42 REQ-F01-070 Exact successor authorization

Only the unique canonical PASES_ISSUE_PHASE_EPOCH_REBASE_AUTHORIZATION_V1 marker in the current approved ADC authorizes the epoch-3 transition. Its exact typed payload binds the approved predecessor and successor ADCs, repository/Issue/owner, Issue body, predecessor epoch and phase generation, old READY receipt, deviation and blocker, PR head, base and local branch, complete before/after labels, transition, and one-application limit. Missing, duplicate, reordered, edited, stale, or mismatched evidence blocks without writes.

<a id="req-f01-071"></a>
### 9.43 REQ-F01-071 One-shot epoch-3 transition and recovery

Append and verify one immutable Intent, perform at most one complete-label replacement from the exact phase:ready state to phase:requirements, append one matching Applied record, and verify the local epoch identity and workspace attachment. Read direct/list/direct comment evidence and full Issue labels. Ambiguous Intent, label, or Applied writes are reconciled only through read-only readback; a persistent attempt marker prevents a second POST or PUT. Preserve older migration records as history and never reconstruct the V1 Binding.

<a id="req-f01-072"></a>
### 9.44 REQ-F01-072 Fresh Phase receipts before implementation

Commit the final specification, design, and test-oracle documents before reissuing requirements → specification → design → ready receipts under the epoch-3 generation. The READY receipt must validate the current document bytes and traceability at the exact pushed branch HEAD. Only after READY passes may Issue #71 advance normally to phase:execution. PR #74 product/runtime/test changes and its A/P2 fix are carried only after that transition; its old Phase, Binding, checkpoint, readiness, and delivery evidence remain historical.

<a id="req-f01-073"></a>
### 9.45 REQ-F01-073 Active identity in Readiness evidence

Readiness evidence references must be derived from the fully validated active execution identity. Issue #71 uses its epoch file and verified workspace attachment, ordinary Issues use only their validated V1 Binding, and Issue #63 uses its adopted-epoch evidence. Every emitted identity path must exist and be the active validated source. Issue #71 must not report the retired missing execution-binding.json path.

<a id="req-f01-074"></a>
### 9.46 REQ-F01-074 Supersede the prior implementation PR

Keep PR #74 open and unchanged until one replacement, non-draft Issue #71 PR from epoch 3 is fully verified. Then update PR #74's body to identify the replacement and close PR #74 as superseded. Do not merge either PR without separate explicit owner authorization for that exact PR at its current HEAD.

<a id="req-f01-075"></a>
### 9.47 REQ-F01-075 Inherited Activation and delivery gates

All inherited Issue #71 local Codex/Claude Code Admin authentication, complete current policy readback, separate exact Ruleset, Setup PR merge, and Activation approvals remain in force. Issue #63 protections and all inherited tests, documentation, review, CI, and delivery gates remain unchanged. A 403 or incomplete policy read is unavailable evidence, never proof that protection is absent. No Ruleset write, Setup PR merge, Activation, Issue #63 closure, PR merge, release, tag push, or parent activation occurs without its separate exact authorization.

<a id="req-f01-090"></a>
### 9.48 REQ-F01-090 Preserve the current execution origin

Keep the approved ADC chain, Issue #71 body, epoch-3 origin identity and attachment, historical Binding, branch/worktree, PR #74, and prior evidence unchanged. The epoch remains rooted at ADC #6881591677 and must be verified through the complete approved successor chain. Keep Issue #71 open.

<a id="req-f01-091"></a>
### 9.49 REQ-F01-091 Exact verification-rework authority

Only the canonical `PASES_ISSUE_VERIFICATION_REWORK_AUTHORIZATION_V2` marker in the exact approved successor ADC may authorize this transition. It binds predecessor ADC #6886911700, immutable epoch origin and Phase generation, pre-bootstrap branch/PR baseline, full Issue state, and the bootstrap path allowlist. The predecessor V1 marker remains immutable history and cannot authorize rework.

<a id="req-f01-092"></a>
### 9.50 REQ-F01-092 Bounded bootstrap commits

Permit one to three descendant commits from pre-bootstrap HEAD `b781ddf1bd6eb5067e87f269da4b1306341e682d`; every changed path must be in the exact successor ADC allowlist. The complete local worktree must be clean after commits. Bootstrap must not change User Review identity, profile review mode, Activation, PR #74, or Issue #63 behavior.

<a id="req-f01-093"></a>
### 9.51 REQ-F01-093 Exact PR #75 subject

Push only the authorized bootstrap commits to existing PR #75. Before evidence collection and rework, require the PR open and non-draft, based on `main@07481c4b451a81750a6c2e1a6a18bdfd4e3459c2`, with its HEAD equal to the exact local bootstrap HEAD. Re-read local, remote, and GitHub identities immediately before the Intent and label update.

<a id="req-f01-094"></a>
### 9.52 REQ-F01-094 Fresh exact-head delivery evidence

After the bootstrap push, produce fresh Verification, Acceptance, Self-Audit, Independent Review, Required CI, and Review Readiness at the exact pushed HEAD under the current approved ADC. Bind the rework Intent to the actual ADC pointer, bootstrap/PR HEAD, fresh Readiness digest, epoch origin, active Phase generation, Issue body/labels, owner, and repository identities. The earlier Readiness digest is historical only. Any stale gate or identity mismatch blocks before writes.

<a id="req-f01-095"></a>
### 9.53 REQ-F01-095 One-shot verification-to-requirements rework

Use one append-only Intent, at most one full-label replacement from the exact verification state to requirements, and one matching Applied record. Verify direct/list/direct comment history and full Issue state. Never retry an ambiguous write. Applied becomes the active Phase generation while epoch 3 and its attachment remain unchanged.

<a id="req-f01-096"></a>
### 9.54 REQ-F01-096 Fresh Phase sequence before implementation

At the same bootstrap HEAD, publish fresh requirements → specification → design → READY receipts under the new active Phase generation. Only after READY passes may Issue #71 advance normally to execution and receive the Issue #71-only `solo_owner` User Review identity correction. Preserve Issue #63 behavior. Run final exact-head evidence, CI, Readiness, and User Review required by the inherited contract.

<a id="req-f01-097"></a>
### 9.55 REQ-F01-097 Separate delivery and Admin gates

Keep all other inherited delivery gates unchanged. PR merge requires separate owner authorization for exact current PR #75 HEAD. This ADC does not authorize Admin policy changes, Ruleset or Setup PR writes, Activation, release, tag, Issue #63, or Issue-close writes.

<a id="req-f01-098"></a>
### 9.56 REQ-F01-098 Preserve the pending rework operation

Keep Issue #71, its body and OPEN state, approved ADC history, epoch-3 origin, active Phase generation, branch/worktree, PR #74 and PR #75, original pre-Intent PASS Readiness, pending Intent #6888474848, and all historical records unchanged. Recovery must bind the exact existing Intent and must not post another Intent.

<a id="req-f01-099"></a>
### 9.57 REQ-F01-099 Bound the Recovery commit

Permit at most one Recovery commit descended from `4185a510054a2a8781659191c1a48178336f8571`. Require every changed path to be in the Recovery ADC's exact 16-path allowlist. Generate the three distribution mirrors only with `python tools/build_dist.py`. Require a clean worktree and equal local/remote HEADs before any Issue write.

<a id="req-f01-100"></a>
### 9.58 REQ-F01-100 Verify the successor Recovery authorization

Validate the exact approved ADC #6888665795 and its exact-byte Recovery marker, the complete approved ADC chain, the exact pending Intent comment/body digest, the original ADC identity in that Intent, the recorded original Readiness bytes and subject, and the local Intent attempt marker. Recheck repository, owner, Issue, epoch, Phase generation, frozen base, PR #75, branch, and current HEAD before a write. Before Recovery code gates, append a V4 PRBinding and V3 checkpoint for the current Recovery ADC and exact Recovery HEAD through the P-ASES recovery command. Preserve PR #75 title/body bytes; the ordinary PR ensure path stays blocked while Intent is incomplete.

<a id="req-f01-101"></a>
### 9.59 REQ-F01-101 Continue the exact pending Intent once

When the exact pending Intent exists, labels equal the exact before-state, and no label-attempt marker exists, reuse only the exact pre-Intent PASS Readiness bound by the Intent. Do not recompute Readiness after Intent. Write the label-attempt marker before the only complete-label PUT, read back the exact after-state, and append one matching Applied record. A prior marker forbids another PUT. Ambiguous outcomes permit read-only reconciliation only.

<a id="req-f01-102"></a>
### 9.60 REQ-F01-102 Cover Recovery and no-retry behavior

Test Recovery marker and chain validation, original Intent and Readiness reuse, absence of post-Intent Readiness recomputation, before-label continuation with no marker, marker-present no-retry, after-label Applied recovery, and wrong Intent, Readiness, ADC, HEAD, PR, owner or labels. Run focused tests and the full inherited verification suite at the Recovery HEAD.

<a id="req-f01-103"></a>
### 9.61 REQ-F01-103 Require exact-HEAD Recovery gates

At the Recovery HEAD, require compileall, the full unit suite, documentation validation and formatting, generated distribution check and validation, specification/design/oracle traceability, all 16-Skill acceptance checks, whitespace validation, all configured Required Checks, a fresh Self-Audit, and a fresh native Independent Review. The V4 PRBinding and V3 checkpoint must bridge the Recovery ADC, immutable epoch-3 identity, frozen PR #75, and Recovery HEAD before these gates are evaluated. The existing original PASS Readiness remains the sole Readiness authorizing Intent #6888474848; do not claim a new PASS Readiness while rework is incomplete.

<a id="req-f01-104"></a>
### 9.62 REQ-F01-104 Resume the approved Phase sequence

Only after Applied is read back, publish fresh requirements → specification → design → READY receipts at the exact Recovery HEAD and new active Phase generation, then advance normally to execution. Only then implement the inherited Issue #71 `solo_owner` User Review identity correction. Preserve Issue #63 behavior.

<a id="req-f01-105"></a>
### 9.63 REQ-F01-105 Preserve separate delivery and Admin gates

Keep PR #75 open and unmerged, preserving its title and body. Admin policy and Activation remain blocked until complete owner-controlled Admin policy readback and separate approvals. Merge, Activation, release, tag, Issue #63, and Issue-close operations retain their separate authorization gates.

<a id="req-f01-106"></a>
### 9.64 REQ-F01-106 Preserve the existing phase journal

Preserve Issue #71's body and open state, the approved ADC chain, epoch, branch, PR #75, Intent #6888474848, Applied #6889965335, local attempt markers, and all historical records. Do not edit or duplicate either journal comment.

<a id="req-f01-107"></a>
### 9.65 REQ-F01-107 Bound Applied event and publication time

For the exact Issue #71 phase-rework Applied record, parse `applied_at` and GitHub `created_at` as strict UTC. Treat `applied_at` as the local event time and `created_at` as publication time. Accept only when `0 <= created_at - applied_at <= 300` seconds. Reject future event times, larger differences, malformed timestamps, or any mismatch in the exact Applied identity and fields. Do not change timestamp rules for other Issues or record types.

<a id="req-f01-108"></a>
### 9.66 REQ-F01-108 Permit one timestamp-reader correction commit

Permit exactly one follow-up commit parented by `574d7970323840933c34c37e874ad1616d577a8a`, with every changed path in the exact timestamp-recovery marker allowlist. Validate the original bootstrap prefix through `4185a510054a2a8781659191c1a48178336f8571` using the original ADC's bootstrap bound, then validate the Recovery and timestamp follow-up commits against their separate exact markers. Together with the existing Recovery commit, the branch has exactly two descendants of `4185a510054a2a8781659191c1a48178336f8571`. Generate distribution mirrors only with `python tools/build_dist.py`.

<a id="req-f01-109"></a>
### 9.67 REQ-F01-109 Verify the timestamp-recovery ADC successor

Validate the exact successor ADC #6890080277, its predecessor #6888665795, exact marker, complete approved ADC chain, and existing Intent/Applied records. Preserve the existing epoch and all exact Issue, owner, ADC, branch, PR, base, HEAD, labels, and local attempt-marker checks. Generic phase semantics and other Issues remain unchanged.

<a id="req-f01-110"></a>
### 9.68 REQ-F01-110 Test exact Applied reconciliation without writes

Cover timestamp equality, the observed three-second difference, the inclusive 300-second limit, over-limit and future values, malformed timestamps, wrong Applied comment ID/body digest, wrong Intent, and no-write reconciliation. Reconciliation performs no Issue label or comment write.

<a id="req-f01-111"></a>
### 9.69 REQ-F01-111 Gate the exact follow-up HEAD

At the single follow-up commit HEAD, require compileall, the full unit suite, documentation validation and formatting, generated distribution check and validation, specification/design/test-oracle traceability, all 16-Skill acceptance checks, whitespace validation, configured GitHub Required Checks, a fresh Self-Audit, and a fresh native Independent Review. Rebind PR #75 with P-ASES at that HEAD. Preserve the PR title, body, base, open state, and unmerged state.

<a id="req-f01-112"></a>
### 9.70 REQ-F01-112 Resume Phase evidence after reconciliation

After read-only reconciliation confirms the exact existing Applied record and current binding, issue fresh requirements → specification → design → READY receipts at the corrected HEAD and active Phase generation, then advance normally to execution. Only then continue the inherited Issue #71 `solo_owner` User Review identity correction. Preserve Issue #63 behavior.

<a id="req-f01-113"></a>
### 9.71 REQ-F01-113 Preserve separate authorization boundaries

Do not create duplicate Intent or Applied comments, another backward Phase transition, PR merge, Admin policy or Ruleset operation, Setup PR, Activation, release, tag, Issue #63 write, or Issue close.

<a id="req-f01-120"></a>
### 9.72 REQ-F01-120 Preserve the approved Issue #71 continuation subject

Preserve the OPEN Issue #71 body and approved ADC history, epoch-3 identity and attachment, execution identity, branch/worktree, frozen base, PR #75, current labels, and existing Intent #6888474848 and Applied #6889965335. Treat those Intent/Applied records and all earlier ADC generations as immutable history. Do not edit, duplicate, restore, or roll back them.

<a id="req-f01-121"></a>
### 9.73 REQ-F01-121 Verify the exact continuation ADC chain and marker

Accept the continuation only when the approved chain is exactly #6886911700 → #6887429739 → #6888665795 → #6890080277 → #6891800412 → #6891926625 with the pinned SHA-256 values. Validate the exact current canonical continuation marker, its 2,155-byte digest, predecessor, repository/Issue/owner, epoch, phase, labels, branch, base, PR, HEAD, Intent/Applied IDs and digests, and exact path allowlist. Reject missing, duplicate, reordered, unapproved, edited, stale, or mismatched generations.

<a id="req-f01-122"></a>
### 9.74 REQ-F01-122 Bound the continuation commit lineage

Permit exactly one continuation commit whose sole parent is `cb02a9fccfb988300dff82c5ad2ccfe946cd4dd3`. Preserve the existing recovery and timestamp-reconciliation commits as separate one-commit segments after `4185a510054a2a8781659191c1a48178336f8571`; validate each segment against its own exact allowlist. Reject merge commits, unexpected parents, extra descendants, and paths outside the continuation allowlist. Generate mirrors only with `python tools/build_dist.py`.

<a id="req-f01-123"></a>
### 9.75 REQ-F01-123 Test authorization, lineage, and no-write behavior

Cover the six-generation ADC chain, canonical marker and artifact declarations, wrong/missing/duplicate marker, wrong identity, changed Intent/Applied tuple, invalid branch/base/HEAD, wrong parent, extra descendant, and outside-allowlist change. Prove that exact existing Applied reconciliation is a read-only NOOP with zero Issue comment or label writes. Keep timestamp boundary and prior no-write regressions.

<a id="req-f01-124"></a>
### 9.76 REQ-F01-124 Gate and bind the exact pushed HEAD

At the one pushed continuation HEAD, require compileall, full unit tests, documentation validation and formatting, generated distribution check and validation, specification/design/test-oracle traceability, all 16-Skill acceptance checks, whitespace validation, configured Required Checks, fresh Self-Audit, and fresh native Independent Review. Rebind PR #75 through P-ASES at that HEAD. Keep its title, body, base, open state, and unmerged state unchanged.

<a id="req-f01-125"></a>
### 9.77 REQ-F01-125 Reconcile before issuing Phase evidence

After current ADC, binding, commit lineage, local marker, and live PR checks pass, reconcile the existing Intent/Applied pair read-only and require NOOP with zero Issue writes. Only then publish and verify fresh requirements → specification → design → READY receipts at the exact HEAD, applying each adjacent P-ASES phase transition only after its receipt and complete labels are verified. Stop at execution.

<a id="req-f01-126"></a>
### 9.78 REQ-F01-126 Declare exact Phase artifact paths

Declare Specification as `docs/specs/workflow-spec.md`, Design as `docs/design/workflow-design.md`, and Testing as `docs/testing/pases-lifecycle-tests.md` plus `docs/testing/traceability.md`, with each path inside inline code so sentence punctuation is outside the path. Confirm committed blob bytes match the local regular files. Do not change the generic document path parser or create substitute files.

<a id="req-f01-127"></a>
### 9.79 REQ-F01-127 Preserve operation boundaries

Do not add an Intent/Applied or recovery marker, move phases backward, merge PR #75, change Admin policy or Rulesets, create a Setup PR, run Activation, implement User Review identity, release, push tags, write Issue #63, or close Issue #71.

<a id="req-f01-128"></a>
### 9.80 REQ-F01-128 Preserve the exact reader-continuation subject

Preserve Issue #71 OPEN and its exact body, the complete approved ADC history, active epoch and execution identity, branch and frozen base, PR #75 metadata, existing rework Intent/Applied, current phase labels before continuation, and completed requirements→specification and specification→design receipts as immutable history.

<a id="req-f01-129"></a>
### 9.81 REQ-F01-129 Verify the exact approved ADC chain

Accept the current approved reader-continuation ADC only after verifying every generation in the exact approved chain, every predecessor digest, canonical marker bytes and fields, and the pinned Issue, owner, epoch, branch, PR/base, Intent, Applied, phase, labels, and HEAD identities. Reject missing, duplicate, reordered, edited, unapproved, stale, or mismatched generations.

<a id="req-f01-130"></a>
### 9.82 REQ-F01-130 Bound the reader-continuation commit

Preserve the validated continuation through `b31cca21da15e18d0e1665827621700f7d774d0a`, then permit exactly one direct-child commit with the marker's exact 15-path allowlist. Reject merges, wrong parents, extra commits, outside paths, and any later descendant. Generate distribution mirrors only with `python tools/build_dist.py`.

<a id="req-f01-131"></a>
### 9.83 REQ-F01-131 Repair executable-source traceability

Add `../../tests/test_phase_rework.py` to the REQ-F01-124 traceability row while preserving its existing links. Add complete traceability rows for REQ-F01-128 through REQ-F01-132, each with exactly one linked Specification, Design, Oracle, and Test plus at least one repository-contained executable test source.

<a id="req-f01-132"></a>
### 9.84 REQ-F01-132 Gate the exact HEAD and resume Phase transitions

At the one exact pushed HEAD, pass every required local and hosted verification gate, fresh exact-subject Verification/Acceptance/Self-Audit/Independent Review, and P-ASES PRBinding. Reconcile the existing Applied record read-only with a zero-write NOOP. Then publish and verify the fresh design→ready receipt, advance to READY, and use the supported execution transition evidence defined by REQ-F01-133. Keep Issue #71 OPEN and PR #75 OPEN/non-draft/unmerged; stop at execution.

<a id="req-f01-133"></a>
### 9.85 REQ-F01-133 Record the supported execution transition

The `ready → execution` transition uses the ordinary `issue advance 71 execution` operation at the exact current subject. Before changing the label, it revalidates the current READY proof; after the label write, it returns success and reads back the complete Issue state with `phase:execution`. Preserve the command result, READY proof reference, pre-write and post-write Issue snapshots, and their exact timestamps and digests as the transition record. Do not require or publish a distinct execution-target `PASES_PHASE_DECISION_V1` comment.
