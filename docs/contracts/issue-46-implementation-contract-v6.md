# Implementation Contract v6 — Issue #46 Controlled Risk Override

**Repository:** `puchinya/ai-agent-workflow`  
**Issue:** [#46](https://github.com/puchinya/ai-agent-workflow/issues/46)  
**Purpose:** Make progress through the existing Legacy Admission bootstrap without falsely claiming guarantees that GitHub does not provide.  
**Status:** Owner-selected policy direction, **not** an already issued SHA-bound runtime authorization, Phase receipt, or Independent Review PASS.

> This document is an Implementation Contract. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, do not silently choose an alternative. Report the exact conflict and continue only with independent valid work.

## 1. Repository Baseline

- #46 is OPEN at `phase:requirements`; existing branch `codex/issue-46-multi-host-independent-review` retains HEAD `eff1562a809ecafd3979a620ae51bd670778ee77` in the last confirmed report. Verify HEAD and working-tree changes again before taking action.
- Current approved successor ADC is Issue comment `#6319520907`, SHA-256 `574e5cc7ebc900152e91ae2e582cce618e9db31e80bbea1b9e0bb60364160ca0`; original ADC, subsequent binding generations, Activation #57, and frozen base/branch/worktree remain immutable.
- Previous owner-approved Bootstrap plan SHA: `0128761738cc88f1d941966b4c6b735fe5665e7a4a17307d291343827cb095f5`. A subsequent path-manifest approval reportedly authorized generating **18 distribution artifacts**. Codex reports **122 Stage 1 tests PASS**, distribution verification PASS, and 16-Skills verification PASS. Do not infer exact IDs/paths or test results that have not been read back.
- Native independent child review disclosed two genuine limitations: (1) concurrent Adoption writers can create duplicate records, and (2) deleting a Gate marker can allow the same Owner grant to produce a new Gate record. Repository rules do not presently prevent privileged history deletion. The underlying raw review and reproduction cases must be retained; never mark these checks PASS when they fail.
- Authoritative code boundaries: `runtime/p_ases/gate_policy.py::{select_gate,read_gate_selection,pin_gate_selection}`, `runtime/p_ases/phase_evidence.py::_check_activation`, new Stage 1 `runtime/p_ases/legacy_adoption.py`, the Issue-46 ADC `REQ-F07-001..006`, and `docs/specs/workflow-spec.md`/`docs/design/workflow-design.md`. For Stage 2, use #46 requirements `REQ-F06-001..009`.

## 2. Architecture Decisions

1. **Adopt a bounded trust model instead of claiming universal exactly-once/tamper-proof semantics.** For **the one-time admission of Issue #46**, the trusted GitHub repository Owner is the administrator and the **sole permitted writer** of an adoption at a time. Privileged deletion of issue comments and concurrent independent writers are **out of the supported operational envelope**. This limitation must be visible in the record and documentation. It is *not* `HOST_VERIFIED` evidence or an immutable-history claim.
2. **Explicitly accept, do not conceal, the two P1 findings within that bounded model.** Preserve the independent child's raw findings and reproducing tests in an auditable limitation report. Show `KNOWN_RISK_ACCEPTED_BY_OWNER` (or an equivalent separately typed status) rather than `PASS` for the unsupported guarantees. In-scope tests (including positive adoption, identity binding, single-writer retry, conflict detection, stale data, and no unauthorized Phase writes) must still PASS.
3. **One-time Owner authorization remains required.** A new `legacy-adoption-plan` must include the exact Issue, ADC, Binding, Activation, pushed HEAD, permitted single-writer condition, and **both enumerated accepted risks** in its canonical SHA. The Owner must separately authorize that exact plan before any Adoption/Gate write. The general statement “ignore blockers” is not a substitute for a SHA-bound Owner grant.
4. **Handle observed conflict by failing closed.** Before and after the one-shot write, reread the complete current Issue history; if duplicate/edited/conflicting markers or any mismatch is actually observed, report `BLOCKED`, do not perform Phase writes, and do not retry blindly. If a marker was silently deleted by a privileged actor, the system **cannot certify** that it never existed; disclose this assurance limit rather than inventing a detection mechanism.
5. **Do not override current immutable ADC semantics by comment alone.** If `REQ-F07-004/005`, the approved Bootstrap plan, or lifecycle tests require concurrency safety or deletion-detection even under this limited scope, prepare the minimal forward successor ADC and new specific Bootstrap scope approval **before** changing that behavior. Do not amend an approved comment or reuse its SHA. This is a single **bounded risk reauthorization**, not repeated requests for ad hoc approval.
6. **Stage 1 != final acceptance.** Commit/push the approved Stage 1 artifacts and allow a one-time risk-accepted Legacy Gate, then perform legitimate specification/design/ready/`execution` transitions for #46. Implement F06 under `execution`. The final code, tests, docs, generated distributions, CI, independent review and User Review remain mandatory. No automatic waiver for unrelated P1 defects.
7. **Scope boundary:** No Issue #66 implementation, no changes to #63/PR #64 frozen evidence, no changed timestamps, no default weakening of `p-ases-v1`, no fixed Bootstrap cohort expansion, no refactoring of the #63-only Owner authorization or rebaseline path.

### Rejected alternatives

- **Unconditional `--force` pass** that fabricates a Gate, Phase receipt, risk-free PASS, or Owner identity.
- Treating the current `create_issue_comment` read-before-write flow as atomic across hosts.
- Claiming a GitHub Issue-comment history is undeletable without appropriate repository controls.
- Blocking all Stage 1 work until the much larger F06 Stage 2 implementation passes.

## 3. Exact Change Set

- `runtime/p_ases/legacy_adoption.py`: encode single-writer supported-mode preconditions and two exact risk disclosures in the canonical adoption plan. Preserve double readback before/after the write, duplicate/conflict and stale-input rejection, and replay result reporting. Do not silently turn duplicate rows into successful Gate state.
- `runtime/p_ases/gate_policy.py`, `runtime/p_ases/phase_evidence.py`: accept only the valid typed `legacy-issue-adopted-v1` record bound to the Owner-authorized plan; ordinary date-based Gate and fixed historical Bootstrap behavior remain unchanged.
- `runtime/p_ases/cli.py`: report policy acceptance and assurance limitations distinctly from technical PASS. Do **not** add a generic CLI flag permitting arbitrary agents to waive security controls.
- `docs/specs/workflow-spec.md`, `docs/design/workflow-design.md`, `docs/testing/pases-lifecycle-tests.md`, `docs/testing/runtime-tests.md`, `docs/testing/traceability.md`: adopt a single-writer supported-mode requirement and the limited administrative trust boundary, preserving all original finding text in `docs/status/issue-46-bootstrap-known-risks.md`. Where current approved documents already require stronger semantics, use a *new approved ADC generation before editing*.
- Only owner-approved source paths and the precise 18 generated distribution outputs (read back the manifest) may be written. `tools/build_dist.py` itself is not to be changed absent a demonstrated builder defect and distinct authorization.

## 4. Implementation Sequence

1. **Read-only:** preserve worktree; inspect current approved ADC/Binding, the latest Owner grant and 18-path manifest, Stage 1 child review, the two reproductions, complete Issue history, and exact remote HEAD. Classify the affected existing contract statements; do not invent file paths or reported tests.
2. **Single policy authorization:** if approved ADC is inconsistent with bounded trust, prepare a minimal successor ADC + linked bounded-scope bootstrap grant for the specific two accepted risks; present actual SHA(s) and obtain authentic Owner decisions. No extra code writes prior to approval.
3. **Finalize Stage 1:** run all **in-scope** 122+ tests, all focused negative cases, dist generation/check, 16 Skills and static checks. Reproduce/document known out-of-scope concurrency and privileged-deletion weaknesses; they are **KNOWN RISK**, not tests that passed. Have a fresh native child evaluate the *reduced guarantee* and ensure there is no unaccepted in-scope P1.
4. Commit/push authorized Stage 1 changes; verify exact remote SHA and deterministic generated manifest. No Gate/Phase mutation before the new plan approval.
5. Prepare a new exact-HEAD Legacy Adoption plan, including the risk acceptance and sole-writer condition; obtain Owner-authored SHA-bound consent, then apply at most once. Verify exactly one currently effective Gate, linked records and Issue state; no label writes from admission itself. On any observed ambiguity, BLOCK.
6. Complete requirements→specification→design→ready→execution using committed actual docs, REQ-F06/F07 traceability and real executable test sources. Implement F06 adapters and V2 review under execution, then fix all final regressions.
7. Push one `Closes #46` PR, verify required CI, record a genuine fresh Independent Review and Owner User Review, get separate exact-HEAD `PR_MERGE` authorization, merge and read back Issue closure. Absence of these events is BLOCKED, not COMPLETE.

## 5. Required Runtime Semantics

**Normal supported case:** one Owner-authorized writer, current history consistent, immutable ADC/Binding/HEAD matches, single Adoption/Gate with linked readback, no Phase label mutation until ordinary transition. Repeated apply with the *same still-present complete record* is a read-only `NOOP`.

**Failure:** stale Owner approval, mismatched HEAD/ADC/Binding, ambiguous write, unknown post result, multiple or conflicting markers, concurrent modification observed, or incomplete readback results in `BLOCKED` with **zero Phase PUTs** and no fabricated success. Lost-response recovery only accepts the complete exact original readback, never a blind repost. Cancellation/destruction cannot convert uncertain completion to success.

**Assurance limit:** Without GitHub protection or an independently durable ledger, deletion by a privileged administrator may erase evidence. Under this Owner-trusted single-writer mode that attack is not prevented or retrospectively detectable. Report the boundary. If the application is later used by multiple writers or untrusted administrators, the mode must be disabled and stronger atomic coordination/history protection must be designed and verified first.

## 6. Non-goals / Forbidden Changes

No global “ignore blockers” switch; no broad waiver of failed CI/QA; no mass issue/label changes; no silent test skipping; no rewriting approved ADC, journal, Binding, or historical Gate records; no unsupported claims of atomic GitHub Issue comments or cryptographic integrity of deletable markers.

## 7. Concrete Tests

- Single-writer fresh Owner plan → one unique linked Adoption/Gate and no Phase label write.
- Exact retry with intact record → read-only NOOP, no new comment.
- Stale Issue/ADC/Binding/Activation/HEAD, Owner mismatch, duplicate present, conflicting history, partial post, unknown outcome → BLOCK, Phase PUT=0.
- Concurrent duplicate reproduction and Gate-marker deletion/reissue reproduction remain recorded as **known unsupported threat-model cases**, with the actual observed result. Do not assert that these passed.
- Ordinary post-Activation Issue and fixed #26–32 retain their historical Gate semantics; legacy owner approval does not override either.
- Stage 2 V2 preserves V1 hashes and enforces real child raw output/terminal return, correct assurance labeling and approved project minimum.

## 8. Verification

Stage 1: reproduce results for focused tests, `python -m compileall runtime tools tests`, `python tools/build_dist.py --check`, `python tools/validate_dist.py`, `python tools/validate_parent_acceptance.py 16-skills-package`, `git diff --check`. Run and accurately report entire suite and traceability even if F06 incomplete; stage-local authorization determines admissibility.

Final PR: `python -m pip install -e .`; `python -m unittest discover -s tests -p 'test_*.py'`; `python -m p_ases docs validate --root .`; `python -m p_ases docs format --check --root .`; `python tools/validate_pases_traceability.py specification`, `design`, `test-oracle`; `python tools/build_dist.py`; `python tools/build_dist.py --check`; `python tools/validate_dist.py`; `python tools/validate_parent_acceptance.py 16-skills-package`; `python -m compileall runtime tools tests`; `git diff --check`; five Required PR CI checks and separate host smoke tests. **Every in-scope final acceptance check must pass**; any risk exception remains clearly disclosed and Owner-approved, not a false green test.

## 9. Reviewer Checklist

- [ ] Owner trust model and both accepted risks are explicit, issue- and HEAD-bound
- [ ] Existing approved requirements do not silently conflict with reduced guarantee
- [ ] No agent can grant itself a generic waiver
- [ ] In-scope duplicates/conflicts fail closed without a Phase write
- [ ] Known reproductions and child findings are retained unaltered
- [ ] Original ADC, Binding, base and all historical records are preserved
- [ ] F06 is not implemented before normal execution phase
- [ ] Dist is generator-consistent and expected tests/CI were actually run
- [ ] PR #46 review, User Review, PR_MERGE and actual merge/close were performed

## 10. Completion Report

Provide files changed, exact approved scope/grant IDs/SHA, 18 generated files, 122+ focused test counts, observed known-risk reproduction outputs, all final tests/CI, unverified surfaces, Phase and Gate IDs, deviations, checklist, **PR URL**, merge SHA, and Issue closure status. If approval or gates are unavailable, report `BLOCKED`, not complete.
