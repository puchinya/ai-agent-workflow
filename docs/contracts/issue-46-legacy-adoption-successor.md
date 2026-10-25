# Agent Development Contract — Issue #46 Legacy Issue Admission and Multi-host Independent Review

Repository: puchinya/ai-agent-workflow  
Issue: #46  
**Candidate state:** Draft forward-only successor; not approved or published.  
**Current approved ADC:** Issue comment #6319520907; SHA-256 `574e5cc7ebc900152e91ae2e582cce618e9db31e80bbea1b9e0bb60364160ca0`.  
**Current ADC pointer:** Issue comment #6319523006.  
Earlier ADC generation: Issue comment #6318010120, SHA-256 `642bed4ee96801b72fdba496275909e3155d7862c5cd6264132168bb98e77242`
Earlier predecessor ADC: Issue comment #6315899913, SHA-256 `e47bda0c224b52f78d7070520ee8c52bc228416cdb9747366caa76c518fef2f6`
Correction in this successor: use the exact Specification/Design/Testing impact labels consumed by the existing phase-evidence validator; no requirement or implementation scope changes.  
Source instructions: Issue #46 comment #6315392033 (Contract v2) and the owner-provided Implementation Contract SHA-256 `4f318e4f9c24d7d2bbf2f3e22872437ff16aa44d597ec16a6d2c9fd085f683d7`  
Current Issue state: OPEN, `kind:single`, `phase:requirements`; created `2026-10-14T10:57:28Z`  
Activation #57: record #6198732262, effective `2026-10-15T17:37:00Z`  
Frozen #46 Binding history currently has three approved-ADC generations; history file SHA-256 `af5633c41ca295875e6c59de2e04a46f0aae7bf52b49c00bbb1533b0aa08c9e9`; current generation comment #6319520907 has Binding digest `0991b36a41e2eb979f1f6b8511d1dc308e59c9be5407623594cc0b5765a8115d`; base `main` / `a5203917d2e3f784f68c05cba48c7428689e777e`; branch `codex/issue-46-multi-host-independent-review`; worktree `/workspace/ai-agent-workflow-issue46`; initial HEAD is the frozen base  
Current branch HEAD: `eff1562a809ecafd3979a620ae51bd670778ee77`; this is the pushed specification commit and the only branch commit after the frozen base. It remains in the branch ancestry.

> This ADC is the explicit successor scope for Issue #46. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, report the exact conflict and continue only with independent valid work.

## Issue

Issue #46 was created before Consumer Activation #57 became effective and is tracked as an open single Issue in `phase:requirements`. The ordinary `p-ases-v1` selector correctly rejects Issues created before Activation, so #46 cannot produce its ordinary requirements-to-specification phase receipt under the existing policy. The previously approved #46 ADC covers multi-host Independent Review assurance, but does not authorize or specify legacy Issue admission.

## Scope

Add a narrowly scoped, prospective, Owner-approved admission path for eligible pre-Activation Issues and carry forward the approved multi-host Independent Review scope. Preserve ordinary timestamp eligibility, the fixed historical Bootstrap cohort (#26–#32), the original #46 ADC, the frozen Binding, and the already-pushed specification commit. Do not treat the prior failed phase-evidence command as a phase receipt or PASS. Implement both features under Issue #46 in one implementation PR.

## Change kind

Enhancement to P-ASES Gate selection, phase evidence, and Independent Review assurance. This is not a policy relaxation for ordinary `p-ases-v1` Issues.

## Requirements

- REQ-F07-001: Separate typed legacy Gate without changing ordinary timestamp selection.
- REQ-F07-002: Require exact Owner authorization for the Issue #46 pre-phase bootstrap scope.
- REQ-F07-003: Require a per-Issue, exact-plan Owner grant for legacy adoption.
- REQ-F07-004: Preserve append-only, linked adoption and Gate records with one effective Gate.
- REQ-F07-005: Make apply, replay, and lost-response recovery fail closed without phase writes.
- REQ-F07-006: Resume normal phase governance without falsifying history.
- REQ-F06-001: Add Independent Review V2 while preserving V1 bytes and behavior.
- REQ-F06-002: Require trusted host-owned evidence for HOST_VERIFIED.
- REQ-F06-003: Bind attested native request, completion, and child output without claiming host authentication.
- REQ-F06-004: Validate canonical evidence, exact identity, freshness, replay, and conflict rules.
- REQ-F06-005: Keep host_verified as the default committed assurance minimum.
- REQ-F06-006: Enforce eligible current review evidence before downstream gates.
- REQ-F06-007: Provide distinct adapters for each supported host surface.
- REQ-F06-008: Document observed capability and regenerate distributions from canonical sources.
- REQ-F06-009: Keep Issue #63 / PR #64 workflow evidence and state isolated.

### REQ-F07-001 — Separate typed legacy Gate

Add the typed Gate `legacy-issue-adopted-v1` for an individually adopted, open pre-Activation Issue. Keep `select_gate` and `choose_gate_for_new_issue` ordinary `p-ases-v1` timestamp behavior unchanged. Do not widen `bootstrap-legacy-v1` beyond Issues #26–#32. Without one valid legacy Gate, an eligible old Issue remains `UNDETERMINED` and phase evidence blocks.

### REQ-F07-002 — Exact Issue #46 bootstrap authorization

Before editing any runtime or normative implementation file for Stage 1, require a distinct Owner approval of a canonical SHA-256-bound `PASES_LEGACY_BOOTSTRAP_AUTHORIZATION_V1` scope. It binds repository and owner IDs, Issue #46 stable ID and current labels, approved successor ADC comment ID and digest, verified Activation #57 prefix/record ID and digest, frozen Binding identity/digest, branch, and exact pre-work remote HEAD. It also binds the permitted changed-file budget, bootstrap purpose, and scope digest.

The approved scope permits only the minimum legacy-admission implementation and its necessary specification/design/test-oracle changes and tests that make Issue #46 eligible for normal governance. It grants no ordinary Phase PASS, no Review or QA waiver, no User Review or merge authority, and no authority for the multi-host feature implementation. A caller-supplied boolean, CLI flag, arbitrary JSON, assistant statement, or old ADC approval cannot substitute for the typed Owner authorization. Define the canonical approval record, exact approval text, verifier, and failure cases in the specification, design, and tests before applying the grant. Recheck the bound inputs before the first write. Record bootstrap commits and test results as `BOOTSTRAP_PRE_PHASE`, never as completed historical phases.

### REQ-F07-003 — Exact per-Issue adoption plan and Owner grant

Provide a read-only canonical `PASES_LEGACY_ADOPTION_PLAN_V1` binding repository/owner IDs; Issue number, stable ID, and original creation time; verified Activation #57 prefix, record ID, and digest; current kind, phase, and attention labels; approved ADC ID/digest; frozen Binding digest/base/branch when present; current remote HEAD; proposed phase action; and exact plan SHA-256.

The Owner must approve that exact plan through an Owner-authored GitHub user-interface comment. The agent must not post the Owner approval. The verifier must authenticate the repository owner actor ID, check the target repository/Issue identity and GitHub issue/comment metadata, compare the immutable approval text and timestamp, and perform direct/list/direct readback. This is an operational trust boundary; it does not claim proof of a physical browser or device. Missing, ambiguous, edited, wrong-owner, stale, or mismatched approval blocks before mutation. Recheck all plan inputs immediately before each write.

### REQ-F07-004 — Append-only adoption and Gate records

Append one `PASES_LEGACY_ISSUE_ADOPTION_V1` and one `PASES_GATE_SELECTION_LEGACY_V1`. Use an unambiguous one-way link: the adoption record binds the exact planned Gate payload digest; the Gate record references the adoption record ID. Read back the first record before appending the second. Preserve every existing ADC, Gate, Activation, and Binding record byte-for-byte.

Allow at most one effective Gate per Issue. If ordinary and legacy selections conflict, or duplicate/conflicting/edited legacy records exist, block without choosing one. Change `read_gate_selection` to return a typed union and update every consumer that currently assumes only `PASES_GATE_SELECTION_V1`. `phase_evidence._check_activation` must validate each Gate kind independently and verify the authenticated Activation history prefix and the exact Owner grant. Never rewrite the original Issue creation time or Activation timestamp.

### REQ-F07-005 — Safe apply, replay, and recovery

Add `delivery legacy-adoption-plan 46` as a read-only operation and `delivery legacy-adoption-apply 46 --plan ... --approval-comment-id ...` as the only adoption writer. Apply validates the unique Owner-approved exact plan and all bound inputs twice, appends precisely the two records in REQ-F07-004, and verifies complete readback. It does not modify Issue labels or phase.

An exact already-completed adoption is `NOOP` after readback. A stale plan, wrong owner, duplicate/conflicting Gate, changed HEAD/ADC/Binding/Activation/labels, concurrent apply, edited record, or ambiguous partial history is `BLOCKED`. If the first record exists but its response was lost, recover only by exact direct/list/direct match and then continue the same immutable plan; never blindly retry or create a duplicate. A partial or ambiguous state never writes a phase label.

### REQ-F07-006 — Resume ordinary phase governance without falsifying history

After a valid legacy Gate is selected, #46 must emit a new requirements-to-specification receipt bound to the then-current approved ADC, HEAD, and normative artifact digests, then follow ordinary Design, Test Oracle, ready, execution, verification, Readiness, User Review, and delivery gates. The pre-phase work remains explicitly `BOOTSTRAP_PRE_PHASE`; do not create historical PASS receipts, bypass phase labels, or count bootstrap commits as completed ordinary phases.

For another eligible pre-Activation open Issue already in a later Phase, any reset to requirements requires an individually approved `RESET_TO_REQUIREMENTS` plan plus separate immutable Intent and Applied records and exactly one verified label write. Requirements is a no-op. Closed Issues, resolved Owner decisions, conflicting attention, and parent-dependency failures block. Do not add a generic backward edge to `phases.py` or silently reset another Issue.

### REQ-F06-001 — Independent Review V2 and V1 compatibility

Carry forward the approved multi-host Independent Review scope. Add `PASES_INDEPENDENT_REVIEW_V2` while preserving every existing `PASES_INDEPENDENT_REVIEW_V1` byte, digest, reader, and behavior. V2 records exactly one of `HOST_VERIFIED`, `INDEPENDENT_ATTESTED`, `SELF_REVIEW`, or `UNAVAILABLE`, separately representing review occurrence and source assurance.

### REQ-F06-002 — Host-verified provenance

`HOST_VERIFIED` requires a trusted host-owned, agent-nonwritable source binding one parent, a unique native spawn, a distinct child, successful terminal completion, the exact reviewed subject, and child-authored result. Missing, ambiguous, agent-writable, or unverified host evidence cannot reach this level.

### REQ-F06-003 — Independently attested native result

`INDEPENDENT_ATTESTED` requires the exact native delegation request, successful terminal tool return/completion, and actual child-authored review bytes preserved byte-for-byte and SHA-256-bound to repository, Issue/PR, HEAD, ADC, plan, Binding, and implementation context. Record `evidence_origin=operator_captured_native_tool_result` and state that this proves tamper evidence after capture, not cryptographic host authentication. Task names/status, parent-authored summaries, arbitrary JSON, and same-agent prompts do not qualify.

### REQ-F06-004 — Canonical evidence and identity checks

Provide strict canonical `IndependentReviewV2`, `AttestedNativeDelegationEvidenceV1`, optional `HostProvenanceV1`, and assurance evaluation. Host spawn/child/join IDs may be null when unavailable; do not synthesize or relabel them. `execution_identity_context_id` is mandatory. Stale subject, ADC, Binding, profile, replay, duplicate/conflicting results, incomplete completion, changed bytes, or blocking findings fail closed.

### REQ-F06-005 — Explicit project minimum assurance

Profile Schema 2 supports `independent_review.minimum_assurance` values `host_verified` and `independent_attested`; absent configuration defaults to `host_verified`. The former accepts only `HOST_VERIFIED`; the latter accepts `HOST_VERIFIED` or `INDEPENDENT_ATTESTED`. Re-read the exact committed profile and digest when evidence is issued and consumed. Host detection, Issue number, PR comment, CLI override, or one-run setting cannot lower the minimum.

### REQ-F06-006 — Readiness and downstream gates

Independent-review ingestion, Readiness, and Final Delivery require a positive current review eligible under the committed profile. V1-only, `SELF_REVIEW`, `UNAVAILABLE`, stale evidence, incomplete checklist, blocking A/B/C findings, and policy drift block. A blocked review causes zero Phase mutations and zero User Review session starts.

### REQ-F06-007 — Host-specific adapters

Provide distinct adapters for Codex Cloud, local Codex CLI, Codex Desktop, and Claude Code. Each exposes only actual native requests, returns, completion, and optional trusted host events observable on that surface. Executor CLI flags do not establish Cloud capability. Agent-writable Hook files do not establish `HOST_VERIFIED`. The P-ASES runtime does not spawn another coding-agent executable.

### REQ-F06-008 — Capability documentation and distributions

Record per-surface capabilities and host/OS smoke-test status in `docs/status/issue-46-review-assurance.md`. Update canonical specification, design, test oracles, traceability, Skills, adapter documentation, and generated distributions. Unavailable host/OS tests are `NOT RUN` or `UNAVAILABLE`, never passing.

### REQ-F06-009 — Issue #63 / PR #64 isolation

Keep Issue #63 and PR #64 evidence and workflow state unchanged during #46 implementation. Do not create an Independent Review PASS for #63, change its profile minimum, advance its phase, authorize User Review, Ruleset changes, Activation, merge, or closure. Any later #64 application requires a separately approved forward-generation policy and exact-subject review.

## Architecture decisions

1. **Two-stage self-bootstrap.** First approve and publish this successor ADC; append a same-base/same-branch successor ExecutionBinding generation after exact readback. Separately authorize the exact bootstrap scope before editing Stage 1 implementation files. No bootstrap authorization is implied by ADC approval.
2. **Narrow, prospective legacy admission.** A legacy Gate is separately typed and requires an exact per-Issue plan and Owner grant. It does not relax ordinary `p-ases-v1` time selection or expand the fixed Bootstrap cohort.
3. **Append-only history.** ADC, Gate, Adoption, Activation, phase, and Binding histories remain immutable; schema changes add readers/variants and do not reinterpret V1. One effective Gate is enforced.
4. **One-way record association.** Adoption contains the exact future Gate payload digest; after Adoption direct/list/direct readback, the Gate record cites its Adoption ID. No cyclic IDs or blind retries.
5. **Bootstrap record semantics.** Pre-phase code and verification are identified as `BOOTSTRAP_PRE_PHASE`, not retroactive phase evidence. Normal lifecycle begins with a new requirements-to-specification receipt after admission.
6. **Review assurance remains strict.** The original #46 multi-host requirements remain in force. Attested evidence is not host-authenticated; the default assurance minimum remains host-verified.

## Artifact impact

- Specification: `docs/specs/workflow-spec.md`.
- Design: `docs/design/workflow-design.md`.
- Testing: `docs/testing/pases-lifecycle-tests.md`, `docs/testing/runtime-tests.md`, and `docs/testing/traceability.md`.
- Additional contract/status: commit the approved successor contract as `docs/contracts/issue-46-legacy-adoption-successor.md`; add `docs/status/issue-46-review-assurance.md`.
- Runtime Stage 1: new `runtime/p_ases/legacy_adoption.py`; `runtime/p_ases/gate_policy.py`; `runtime/p_ases/phase_evidence.py`; `runtime/p_ases/cli.py`; and only directly required shared types/readers. Keep all GitHub I/O in `runtime/p_ases/github.py`; do not change Issue #63-only `owner_authorization.py` or reuse `phase_rebaseline.py`.
- Runtime Stage 2: new `runtime/p_ases/review_assurance.py` and `runtime/p_ases/review_host_adapters/{__init__,codex_cloud,codex_local,claude_code}.py`; extend `runtime/p_ases/{audits,cli,delivery,profile}.py`.
- Tests: add focused legacy-adoption/bootstrap tests; update gate-policy and phase-evidence tests; add/update review-assurance, adapter, profile, CLI, delivery, and V1-golden tests.
- Skills/adapters/package: update `workflow/skills/{work-execution,independent-review}/SKILL.md`, relevant delivery-control guidance, `adapters/{openai,claude,antigravity}/README.md`, `tools/build_dist.py` only for canonical packaged files, and regenerate `dist/` through the generator.
- No change to PR #64 frozen worktree or its normative snapshots.

## Exact changes

1. Re-read current Issue/ADC pointer, Binding file and digest, branch and remote HEAD, frozen base and ancestry, Activation #57 prefix, and Issue/PR #63/#64 identity. Confirm no phase receipt was posted for the failed attempt.
2. Validate and obtain exact Owner approval for this successor ADC. Publish it as the approved successor through the normal ADC workflow while preserving the exact bytes and pointer history of comments #6315899913, #6318010120, and #6319520907.
3. Re-read the approved successor comment/pointer and exact branch/Binding state. Append a new Binding generation using `work bind` on the same worktree, base, and branch; do not rebase, recreate `eff1562a809ecafd3979a620ae51bd670778ee77`, or create another worktree.
4. Generate the canonical limited bootstrap scope from current Issue, approved ADC, Activation, Binding, labels, and exact remote HEAD. Present the SHA-256 and permitted changed-file budget. Obtain separate exact Owner approval before any Stage 1 code or normative implementation edit. Implement the typed grant verifier and minimum legacy-admission path; keep changes within the approved scope. Record commits and checks as `BOOTSTRAP_PRE_PHASE`.
5. Have an independent reviewer assess the trust-sensitive bootstrap/adoption implementation before applying it. A reviewer must provide actual independent native review output. If unavailable, do not self-certify or apply the Gate; report the blocker and continue only with valid independent read-only/spec work.
6. Recompute a fresh adoption plan with current HEAD, approved ADC, Binding, Activation, labels, and Issue identity. Obtain separate exact Owner approval of that plan through the Owner-authored GitHub UI comment. Apply and read back Adoption then Gate, with no phase write.
7. Resume ordinary #46 lifecycle with a current requirements-to-specification receipt and the normal Design, Test Oracle, ready, execution, Verification, Readiness, User Review, and Delivery stages.
8. Implement the carried-forward multi-host Independent Review assurance feature only after its normal pre-implementation phase receipts are valid. Keep V1 bytes and behavior unchanged.
9. Run required verification, commit/push to the existing #46 branch, and open one PR with `Closes #46`. Complete that PR's independent review, User Review, Required CI, and ordinary delivery gates. PR merge and Issue closure remain separate explicit decisions.

## Invariants and non-goals

- Preserve ADC comments #6315899913, #6318010120, and #6319520907, their exact bytes/digests and all pointer history including #6319523006, frozen base/branch/worktree/initial HEAD, all Binding generations, and commit `eff1562a809ecafd3979a620ae51bd670778ee77`.
- Preserve Issue #57 Activation record and ordinary timestamp selector behavior; never backdate, change issue timestamps, widen #26–#32, or infer admission from a comment timestamp.
- Do not reuse the #63-only owner authorization or phase rebaseline paths for #46.
- No raw or unapproved label updates; no fabricated Owner approval, host ID, review, phase receipt, or historical PASS.
- No adoption-triggered phase advance. Never skip Design/Test Oracle/ready/verification/Readiness/User Review/merge/Activation checks.
- No same-agent substitute for Independent Review; no silent downgrade of the default assurance threshold.
- Do not modify Issue #63 / PR #64 frozen ADC, pointer, phase/adoption records, Binding, normative files, Ruleset, activation, User Review, merge, or close state.
- No Issue #66 dependency or implementation PR. Issue #46 is the sole implementation issue and has one PR.

## Verification obligations

Run in the real #46 worktree and report each command and exit status:

```bash
python -m pip install -e .
python -m compileall runtime tools tests
python -m unittest discover -s tests -p "test_*.py"
python -m p_ases docs validate --root .
python -m p_ases docs format --check --root .
python tools/validate_pases_traceability.py specification
python tools/validate_pases_traceability.py design
python tools/validate_pases_traceability.py test-oracle
python tools/build_dist.py
python tools/build_dist.py --check
python tools/validate_dist.py
python tools/validate_parent_acceptance.py 16-skills-package
git diff --check
```

Required PR CI: Ubuntu Python 3.10 and 3.14, Windows Python 3.14, macOS Python 3.14, and PR metadata on the exact current HEAD. Separately report Codex Cloud, available local Codex CLI/Desktop OS surfaces, and Claude Code smoke checks. A test in one environment does not verify another; inaccessible environments are `NOT RUN` or `UNAVAILABLE`.

## Reviewer checklist

- [ ] Successor ADC approved/published; original ADC and pointer preserved.
- [ ] Successor Binding is append-only on the frozen worktree/base/branch; `eff1562` ancestry retained.
- [ ] Bootstrap grant binds the exact scope and inputs; no bootstrap edit precedes approval.
- [ ] Bootstrap changes and checks are recorded only as `BOOTSTRAP_PRE_PHASE`.
- [ ] Ordinary time selector and #26–#32 Bootstrap cohort remain behaviorally unchanged.
- [ ] Legacy Adoption and Gate records are unique, typed, linked, Owner-authorized, authenticated, and fully read back.
- [ ] Replay, drift, wrong Owner, duplicate, partial write, race, edit, and lost-response cases fail closed without phase mutation.
- [ ] A fresh ordinary requirements-to-specification receipt follows admission; normal phase gates remain active.
- [ ] Independent Review V1 serialization/digests/readers remain byte-compatible; V2 accurately separates assurance.
- [ ] Default `host_verified` is strict; attested evidence requires exact captured native request, terminal completion, and child-authored bytes.
- [ ] Host capability claims match observed tests; unavailable platforms are reported honestly.
- [ ] Specifications, design, test oracle, traceability, Skills, generated distributions, and CI agree.
- [ ] Issue #63 / PR #64 evidence and workflow state remain unchanged.
- [ ] One Issue #46 PR with `Closes #46` is opened only after ordinary gates; merge and closure are not implied.

## Completion gates

Report the successor ADC approval and pointer IDs/SHA; successor Binding generation/digest and preserved base/branch; bootstrap scope SHA, approved record, changed-file budget, commits and check hashes; legacy adoption plan/approval/Adoption/Gate IDs and exact readback; phase receipts; changed files; every verification result; exact PR URL/HEAD and CI; Independent Review classification and findings; host/OS smoke matrix; unverified environments; blockers/deviations; and confirmation that #63/#64 stayed unchanged.

Do not report COMPLETE until the single PR exists at its exact HEAD and all required review, User Review, CI, Readiness, and delivery gates are satisfied. Merge and Issue #46 closure require separate explicit authorization.


## Forward-only amendment — one-time bounded risk acceptance for Issue #46

**Repository:** `puchinya/ai-agent-workflow` (repository ID `1401910271`)  
**Issue:** `#46` (stable ID `5846549384`)  
**Predecessor ADC:** Issue comment `#6319520907`, SHA-256 `574e5cc7ebc900152e91ae2e582cce618e9db31e80bbea1b9e0bb60364160ca0`  
**Owner policy input:** Implementation Contract v6, SHA-256 `e3cb0fabb1c50e385e88102a1b68369c3cdfcfcec1102a50d344b6f95c01daaa`  
**Scope:** one Legacy Admission operation for Issue #46 only. This amendment is forward-only; it does not edit or reinterpret any prior ADC, Binding, Gate, or Phase record.

This amendment resolves the exact implementation conflict in REQ-F07-005. For this one operation, the supported operational envelope is one repository Owner-authenticated writer at a time. The current GitHub Issue-comment API does not provide atomic compare-and-set or idempotency keys. A privileged repository administrator can also delete comments or remove record markers, and the available Issue history API does not return deletion tombstones.

For this single Issue #46 admission, this amendment narrows the assurance meaning of existing clauses without deleting or rewriting their approved text. Architecture Decision 3's statement that histories remain immutable means this runtime does not edit or delete records; it does not claim GitHub will retain Issue comments against a privileged administrator. REQ-F07-004's append-only and preservation requirements apply to records visible in the current complete readback; they do not assert that a privileged administrator cannot delete a record or that such deletion can always be detected. In REQ-F07-005, “concurrent apply ... is `BLOCKED`” means an observed concurrent modification or conflicting history blocks. It does not claim that the runtime can atomically prevent every race between independent writers. The supported operation therefore requires the Owner to ensure one active writer; the runtime cannot independently prove that condition. All stale-input, duplicate/conflict, edited-record, incomplete-readback, and uncertain-outcome checks remain fail-closed, with zero Phase or label writes on failure.

For this one-time Issue #46 operation, `PASES_LEGACY_ADOPTION_PLAN_V2` replaces the V1 plan as the required authorization subject. It preserves all V1 identity and freshness inputs and additionally binds the repository and Issue IDs above, `writer_mode=owner_trusted_single_writer_v1`, required writer User ID `3744776`, maximum active writers `1`, and both exact accepted risk IDs:

- `CONCURRENT_ADOPTION_WRITES_NOT_ATOMIC`
- `PRIVILEGED_COMMENT_DELETION_OR_MARKER_REMOVAL_UNDETECTABLE`

The Owner's exact GitHub UI approval of this V2 plan is the only way to accept these risks. A plan awaiting that comment is not yet accepted. A successful application and readback reports `KNOWN_RISK_ACCEPTED_BY_OWNER` separately from technical status `APPLIED`. The linked Adoption/Gate records bind the V2 plan digest and the two risk IDs. The runtime must never report either unsupported guarantee as PASS, atomic, immutable, or tamper-proof.

The Owner-authenticated User ID must match repository Owner ID `3744776` before each Adoption or Gate write. The runtime still blocks any duplicate, conflicting, stale, edited, incomplete, uncertain, or changed history it actually observes, and performs zero Phase or label writes during admission. An intact complete exact Adoption/Gate pair is a read-only NOOP. A lost response may be recovered only when the complete exact original record is read back; otherwise the current invocation blocks and does not repost.

The following limits are explicitly accepted for this one-time operation: concurrent independent requests may race between reads and create duplicates; deleting a record or removing its marker may make the prior record undetectable. The Owner must ensure no competing writer is active. The runtime cannot prove that operational condition or detect privileged deletion after the fact. These cases remain `KNOWN_RISK`, not passing concurrency/deletion tests. Preserve the independent child's raw findings and reproductions unchanged in `docs/status/issue-46-bootstrap-known-risks.md`.

Do not use this bounded mode for another Issue, multiple writers, or a repository where an untrusted administrator can act. Any later use in those conditions blocks until a separate stronger coordination and history-protection design is approved and verified. This amendment does not create a generic bypass and does not waive CI, review, Phase, Readiness, User Review, merge, Activation, or closure requirements.
