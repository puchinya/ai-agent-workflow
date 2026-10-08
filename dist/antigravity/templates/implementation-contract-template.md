# Implementation Contract — {{CHANGE_TITLE}}

Repository: {{REPOSITORY_URL}}
Owning Issue: {{ISSUE_URL}}
Baseline: {{BASE_REF_AND_SHA}}
Target release: {{APPROVED_TARGET_OR_NOT_APPLICABLE}}

> This document is an Implementation Contract. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, do not silently choose an alternative. Report the exact conflict and continue only with independent valid work.

## 1. Repository Baseline

- Owning Issue / relevant PRs: {{CURRENT_ISSUES_AND_PRS}}
- Approved spec/design: {{SPEC_AND_DESIGN_PATHS_AND_SECTIONS}}
- Current implementation: {{SOURCE_PATHS_AND_SYMBOLS}}
- Relevant tests: {{TEST_PATHS_AND_BEHAVIOR}}
- Preserved invariants / compatibility: {{INVARIANTS}}
- Repository Map (only necessary source/symbol/test/API boundaries): {{COMPACT_REPOSITORY_MAP}}

## 2. Architecture Decisions

- Adopted design and why: {{ADOPTED_DESIGN}}
- Ownership / lifetime / call ordering: {{OWNERSHIP_AND_ORDER}}
- Backend / host / protocol boundaries: {{BOUNDARIES}}
- Failure, cancellation, retry, reentrancy: {{FAILURE_AND_RETRY_DECISIONS}}
- Compatibility, migration: {{COMPATIBILITY}}
- Rejected alternatives and rationale: {{REJECTED_DESIGNS}}
- Which decisions are existing specification versus task-specific: {{DECISION_ORIGIN}}

## 3. Exact Change Set

- Required canonical files: {{FILES_TO_CHANGE}}
- Type / function / field / CLI signatures: {{EXACT_SYMBOL_CHANGES}}
- Expected Change Surface (file/symbol/test/generated paths): {{EXPECTED_CHANGE_SURFACE}}
- Boundaries explicitly left unchanged: {{UNTOUCHED_BOUNDARIES}}
- Generated outputs (builder only): {{GENERATED_OUTPUTS}}

## 4. Implementation Outcomes

List the required final artifacts, behaviors, tests, and handoff results. The list order is illustrative and does not constrain source edits, document edits, tests, commits, or publication timing. Completion is based on the aggregate final result.

- {{REQUIRED_OUTCOME_1}}
- {{REQUIRED_OUTCOME_2}}
- {{REQUIRED_OUTCOME_3}}
- {{REQUIRED_OUTCOME_4}}

## 5. Required Runtime Semantics

- Normal path / preconditions / postconditions: {{NORMAL_PATH}}
- Errors / missing capability / uncertain remote state: {{FAILURE_PATH}}
- Repeated calls / retries / reentrancy / concurrency: {{REPEATED_CALLS}}
- Cleanup / destruction / Drop / resource ownership (or why N/A): {{CLEANUP}}
- Exact observable output and state ordering: {{OBSERVABLE_SEMANTICS}}

## 6. Non-goals / Forbidden Changes

- {{FORBIDDEN_CHANGE_1}}
- {{FORBIDDEN_CHANGE_2}}
- {{FORBIDDEN_CHANGE_3}}

## 7. Concrete Tests

- {{TEST_1_SETUP_ACTION_EXPECTED}}
- {{TEST_2_SETUP_ACTION_EXPECTED}}
- {{TEST_3_NEGATIVE_OR_REGRESSION}}
- {{TEST_4_COMPATIBILITY_OR_PLATFORM_BOUNDARY}}

## 8. Verification

- Required checks and exact commands: {{VERIFICATION_COMMANDS}}
- Evidence binding and PR delivery checks: {{EVIDENCE_REQUIREMENTS}}
- Unverified target handling: {{UNVERIFIED_POLICY}}
- Expected artifacts: {{ARTIFACT_PATHS}}

## 9. Reviewer Checklist

The implementer must self-review every item in this checklist.

<!-- AGENT_REVIEWER_CHECKLIST_V1 -->
- [ ] Repository baseline and preserved invariants are verified against current source.
- [ ] Required code and tests match every architecture decision and Exact Change Set obligation.
- [ ] Required Runtime Semantics, including failure and retry paths, are covered.
- [ ] Out-of-surface changes are absent or explicitly justified against the Contract.
- [ ] Verification commands and required QA/evidence gates have been executed or precisely reported blocked.
- [ ] Spec/design/Skills/runtime/tests/generated packages are consistent wherever this Contract requires changes.
- [ ] Completion Report includes every changed file, test result, remaining blocker, and PR URL.
<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->

## 10. Completion Report

At handoff, report (do not pre-mark any item as achieved):

- Files changed; acceptance and checklist results.
- Commands/tests run, pass/fail details, unverified platforms/capabilities.
- Contract deviations, conflicts, newly discovered requirements, remaining work.
- Commit and push state; exact PR URL containing `Closes #{{ISSUE_NUMBER}}`.
- Issue/PR review-phase state and final delivery gate result.
- If PR creation or a required gate is blocked, status is **BLOCKED**, not complete.
