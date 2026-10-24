# Agent Development Contract — Issue #46 Owner-Authorized UNAVAILABLE Continuation

Repository: puchinya/ai-agent-workflow  
Issue: #46  
**Candidate state:** Forward successor draft correcting machine-readable artifact-impact declarations and recording the bounded reset/rebaseline order; not approved, published, or implemented.  
**Current approved predecessor ADC:** Issue comment #6390971577; SHA-256 `8fa50df07dcece244cd015d84a6e92f8dea7ccf3fcba16099665c6f9c5918f64`; pointer comment #6390971929.  
**Earlier approved ADC:** Issue comment #6371444320; SHA-256 `e7fda8f61a28c31e50b118c44e7cbb9e42c2b3a00270338a9f441919504ff66b`; pointer comment #6371445186.  
**Owner policy proposal:** Issue comment #6385026889 and the Owner-provided Implementation Contract “Owner-Authorized UNAVAILABLE Continuation.” The proposal is not an exact exception-plan approval.  
**Inspected source HEAD:** `867905bd7f597227794778e1df3ac3e55087253e`; CI #40143383351 passed all five jobs. Refresh before execution.  
**Inspected PR:** #67, OPEN/draft, base `main`, head branch `codex/issue-46-multi-host-independent-review`.  
**Current Issue state:** OPEN, `phase:execution`, `kind:single`.  
**Repository identity:** ID `1401910271`; Owner stable GitHub user ID `3744776`; Issue stable ID `5846549384`.  
**Prior history to preserve:** #57 Activation, Adoption #6378977263, Gate #6378981726, Phase receipts #6378987892, #6379017206, and #6379085920, and all prior ADC and Binding generations remain byte-for-byte unchanged.  
**Frozen base and branch:** `main` / `a5203917d2e3f784f68c05cba48c7428689e777e`; `codex/issue-46-multi-host-independent-review`; keep the existing worktree and ancestry.

> This is a proposed forward-only successor ADC. It is not effective until exact-byte approval, approved publication, and the required forward Phase/document rebaseline. Do not redesign the architecture or silently change the approved requirement.

## Issue

The current approved successor ADC #6390971577 enables a narrow Owner-authorized continuation when native Independent Review capture is unavailable, but its Artifact Impact prose does not use the exact labels consumed by `phase_evidence._artifact_impacts`. This forward successor keeps REQ-F06-006 and REQ-F06-010 through REQ-F06-013 unchanged and adds machine-readable Specification, Design, and Testing declarations. It also records the existing Legacy reset workflow as the bounded way to return this already-adopted Issue #46 from `execution` to `requirements` before changing receipt-bound normative documents. No normative document or runtime implementation change may precede this successor's approval and the separately approved Legacy reset plan/application.

## Scope

Create a per-repository-opt-in, exact-subject Owner exception route for Issue #46 / PR #67 only when the selected host genuinely cannot deliver native child-review capture to P-ASES. It may produce a distinct, visibly degraded Readiness and Final Delivery outcome. It never claims Independent Review occurred or passed. It does not waive Verification, Acceptance, Self-Audit, Required CI, dependencies, human User Review, explicit PR merge authorization, merge, or Issue closure.

The successor carries every current predecessor requirement, decision, invariant, risk disclosure, and non-goal unchanged. It does not replace or revise any requirement. Its addition is the exact parser-compatible artifact-impact mapping and the bounded, individually approved Legacy reset/rebaseline order. Preserve every old ADC, pointer, binding, adoption/gate record, Phase receipt, V1/V2 serializer, digest, and historical review byte.

## Change kind

Forward-only governance and lifecycle exception for a host capability that is positively observed to be unavailable. It does not lower `minimum_assurance`, change `HOST_VERIFIED`, `INDEPENDENT_ATTESTED`, `SELF_REVIEW`, or `UNAVAILABLE` meanings, weaken native-capture fabrication refusal, or make an actual failed review eligible for override.

## Requirements

- REQ-F06-006: Preserve ordinary review eligibility and add only the separately versioned, exact-subject exception described below; never relabel UNAVAILABLE as review PASS.
- REQ-F06-010: Add strict default-off project opt-in and typed distinction among host capture unavailability, review failure, and invalid evidence.
- REQ-F06-011: Bind the exception to an exact canonical plan, Owner-authored approval comment, and separate append-only application receipt.
- REQ-F06-012: Add distinct Readiness V2 and Final Delivery V2 results while preserving all V1 bytes and behavior.
- REQ-F06-013: Allow User Review from ordinary V1 PASS or current V2 READY_WITH_EXCEPTION only after full live exact-subject revalidation; retain all downstream gates.

### REQ-F06-006 — Readiness and downstream gates (successor text)

Independent-review ingestion, ordinary Readiness, and ordinary Final Delivery require a positive current review eligible under the committed profile. Existing V1 PASS behavior and every V1 byte remain unchanged. A separate V2 Readiness result may be `READY_WITH_EXCEPTION` only when a valid exact-subject Owner exception satisfies REQ-F06-010 through REQ-F06-013 and every other Readiness gate passes.

The exception may replace only the missing-review condition caused by positively observed `HOST_NATIVE_CAPTURE_UNAVAILABLE`. It preserves `review_assurance=UNAVAILABLE` and never creates an Independent Review PASS record or label. `SELF_REVIEW`, stale or malformed evidence, missing Verification Plan, wrong subject, failed or incomplete Required CI, failed Verification/Acceptance/Self-Audit, unresolved dependency, or any other unavailable cause remains BLOCKED.

A current completed native review with verdict `FAIL`, `BLOCKED`, or `CONCERNS`, or any unresolved A/B/C finding, is not eligible. A stale historical diagnostic is not a current review result and is not converted into one. A blocked review or invalid exception causes zero User Review session starts and zero Phase mutations.

### REQ-F06-010 — Explicit opt-in and typed capture-unavailability decision

Profile Schema 2 may add `independent_review.unavailable_handling` with exactly `block` or `owner_exception`. Omission defaults to `block` for every project. `minimum_assurance` remains unchanged. Only this repository may commit `owner_exception`, and the opt-in applies only to repository ID `1401910271`, Issue #46 / stable ID `5846549384`, and PR #67. Commit it only after successor approval and required Phase/document rebaseline. Host detection, CLI flags, environment variables, and Issue identity cannot enable the exception.

The runtime produces a typed eligibility decision distinguishing `HOST_NATIVE_CAPTURE_UNAVAILABLE`, `REVIEW_FAILED`, and `INVALID_EVIDENCE`. Only observed absence of host-to-runtime native capture qualifies. Missing plan/evidence, stale subject, malformed input, failed CI, and genuine failed review never qualify. A genuine eligible native review takes the existing ordinary V1 Readiness path and is not shadowed by the exception.

### REQ-F06-011 — Exact plan, Owner authorization, and append-only exception record

Provide read-only canonical `PASES_REVIEW_UNAVAILABLE_EXCEPTION_PLAN_V1` and immutable `PASES_REVIEW_UNAVAILABLE_EXCEPTION_V1` records. The plan binds repository name and ID; Owner user ID `3744776`; Issue number and stable ID; PR number, base ref, base SHA, branch, and exact HEAD; current approved ADC comment ID and SHA; frozen Verification Plan SHA; current ExecutionBinding and PRBinding SHA; committed profile SHA; observed host surface; reason `HOST_NATIVE_CAPTURE_UNAVAILABLE`; capability-observation digests; risk `INDEPENDENT_REVIEW_NOT_PERFORMED`; and plan SHA-256. Disclose that code defects may go undetected because no independent review result was available; do not imply review completion or acceptance of any actual finding.

The plan command emits exact approval text. The Owner (stable GitHub user ID `3744776`) personally posts that exact text as an Issue #46 comment. The implementation agent never creates or edits the Owner approval comment. Canonical marker:

```text
<!-- PASES_REVIEW_UNAVAILABLE_APPROVAL_V1
{"approved":true,"issue_number":46,"plan_sha256":"<64-digit digest from the actual plan>","pr_number":67,"repository":"puchinya/ai-agent-workflow","schema":"PASES_REVIEW_UNAVAILABLE_APPROVAL_V1"}
-->
```

The verifier compares the complete literal comment with its canonical formatter; authenticates stable Owner ID; verifies repository, Issue, comment API URL, Issue URL, HTML URL, exact unedited content and timestamp; and performs direct/list/direct readback. Missing, edited, duplicate, conflicting, wrong-Owner, stale, or mismatched approval blocks before writes. This is Owner-account operational provenance, not cryptographic or physical-device proof.

Apply is the sole writer of a distinct append-only Issue receipt `PASES_REVIEW_UNAVAILABLE_EXCEPTION_V1` and immutable local evidence after verifying the Owner comment. The receipt records plan SHA, Owner comment ID/digest, all bound subject/profile identities, typed unavailable reason, and risk. The Owner approval and implementation-authored receipt are separate; the latter never represents Owner approval. Apply rechecks inputs immediately before writing and reads the receipt direct/list/direct. Exact replay is read-only NOOP. Ambiguous outcome, duplicate/conflicting history, stale plan, or partial readback blocks without blind retry or replacement. Missing frozen Verification Plan blocks plan generation; Legacy Adoption plan is not a substitute.

### REQ-F06-012 — Versioned readiness and delivery results

Preserve all `PASES_REVIEW_READINESS_V1` serializers, readers, bytes, and behavior. Add `PASES_REVIEW_READINESS_V2` with statuses `READY_WITH_EXCEPTION` or `BLOCKED`, `review_assurance=UNAVAILABLE`, exact Verification subject and profile digests, exception record and Owner comment IDs/digests, and enumerated risk. `READY_WITH_EXCEPTION` requires every non-review gate PASS and the exact Owner exception current.

Preserve all V1 Final Delivery bytes and behavior. Add `PASES_FINAL_DELIVERY_V2` for the exception route. Its ready status is `READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION`; it discloses `review_assurance=UNAVAILABLE`, binds the exception digest, and sets `merge_authorized=false`. It does not authorize or perform a merge.

### REQ-F06-013 — Downstream consumption and exact-subject revalidation

User Review may start from ordinary `PASES_REVIEW_READINESS_V1 PASS` or exact current `PASES_REVIEW_READINESS_V2 READY_WITH_EXCEPTION`. It remains a separate explicit human decision. Preserve V1 User Review bytes. On every Readiness recomputation, User Review start/submit, and Final Delivery evaluation, reread and validate exact PR/HEAD, ADC, Verification Plan, ExecutionBinding, PRBinding, profile, exception record, Owner comment, Required CI, dependencies, Verification, Acceptance, and Self-Audit.

A change in any bound input invalidates the exception before side effects. The exception never bypasses a draft PR, failed check, dirty checkout, unmet dependency, actual current review failure, or explicit `PR_MERGE` authorization. Apply identical semantics on Codex Cloud, local Codex CLI/Desktop, and Claude Code; adapters report actual capabilities truthfully. Agent-writable Claude Hook records never establish `HOST_VERIFIED`.

## Architecture decisions

1. Preserve ordinary review evaluation and V1 artifacts/digests. The exception is a separate lifecycle path, never a review PASS.
2. Make opt-in explicit and default-off; keep `minimum_assurance` unchanged.
3. Use a typed exact-subject plan, Owner-authored approval comment, and separate append-only implementation receipt. No agent-generated Owner approval, legacy Adoption grant reuse, or cryptographic-host-authentication claim.
4. Qualify only positive evidence of missing host-to-runtime capture. Actual review failure, unresolved A/B/C findings, invalid/stale evidence, missing plan, and failed non-review gates remain blocking.
5. Preserve V1 outputs; add distinct V2 Readiness/Final Delivery with visible risk and no merge authority.
6. Revalidate the same exact subject at each consumer and apply equal semantics to Codex Cloud, local Codex, and Claude Code.
7. Isolate this change to Issue #46 / PR #67. Do not alter Issue #63 / PR #64, Activation, fixed Bootstrap #26–#32, or historical ADC/Gate/Phase/review evidence.

## Artifact impact

After exact successor ADC approval, append its Binding, obtain a fresh read-only `delivery legacy-reset-plan 46`, and receive the separate Owner approval comment for that exact plan before applying the existing Legacy reset. Only after verified `phase:requirements` may normative artifacts change. Preserve previous receipt-bound bytes and journal entries. These exact rows are consumed by `phase_evidence._artifact_impacts`:

- Specification: `docs/specs/workflow-spec.md`
- Design: `docs/design/workflow-design.md`
- Testing: `docs/testing/pases-lifecycle-tests.md`, `docs/testing/runtime-tests.md`, `docs/testing/traceability.md`

These files must express the already approved REQ-F06-006 and REQ-F06-010 through REQ-F06-013. Do not alter receipt-bound bytes in place; publish new-ADC-generation requirements→specification, specification→design, and design→ready receipts and perform the matching ordinary phase advances. Update `docs/status/issue-46-review-assurance.md`, canonical review/User Review/delivery Skills, `adapters/openai/README.md`, and `adapters/claude/README.md` as additional artifacts; confirm exact Skill paths before edits. Regenerate `dist/openai`, `dist/claude`, and `dist/antigravity` only with `python tools/build_dist.py`; never edit distributions manually.

## Exact changes

After approved successor artifacts and required Phase receipts exist:

- `runtime/p_ases/profile.py`: strict optional `unavailable_handling`; omission remains `block`.
- New `runtime/p_ases/review_unavailable_exception.py`: strict canonical plans, Owner approval verification, immutable records, identity/digest checks, unique-history/replay/conflict checks, and fail-closed recovery.
- `runtime/p_ases/review_assurance.py`: retain native assurance; add only typed capture-unavailability eligibility.
- `runtime/p_ases/delivery.py`: preserve V1; add V2 Readiness and Final Delivery types/readers. Factor common checks only if V1 output remains byte-identical.
- `runtime/p_ases/user_review.py`: accept exact current V1 PASS or V2 READY_WITH_EXCEPTION while preserving User Review bytes.
- `runtime/p_ases/cli.py`: add `delivery review-unavailable-plan ISSUE PR HEAD VERIFICATION_PLAN --host-surface SURFACE --output PLAN_FILE`, where surface is `codex_cloud`, `codex_local_cli`, `codex_desktop`, or `claude_code`; add `delivery review-unavailable-apply ISSUE PR HEAD VERIFICATION_PLAN --plan PLAN_FILE --approval-comment-id ID` as the sole writer. Readiness and Final Delivery retain the existing positional Independent Review input; omit it only with `--review-unavailable-exception PATH`, rejecting both or neither. Revalidate through `_delivery_readiness`, `_require_readiness_review_assurance`, `_user_review_run`, and `_delivery_final`.
- Add `tests/test_review_unavailable_exception.py`; extend profile, review assurance, Readiness, User Review CLI, P-ASES CLI, and Final Delivery tests.
- Use only PR #67; do not open a second implementation PR.

## Invariants

- `UNAVAILABLE` is never called an Independent Review PASS or `INDEPENDENT_ATTESTED`.
- Never set native capture capability true without an actual host API; never fabricate host IDs, child returns, approval, or evidence.
- Never override current `FAIL`, `BLOCKED`, `CONCERNS`, or unresolved A/B/C findings.
- No force flag, blanket downgrade, skipped CI, skipped human User Review, implicit merge authority, or Issue closure authority.
- Do not modify Issue #63/PR #64, Activation, #26–#32, approved ADC/pointer/history, old Adoption/Gate/Phase/Binding records, or historical review bytes.
- Preserve V1 review, Readiness, Final Delivery, and User Review bytes and behavior exactly.

## Non-goals

- No universal or automatic bypass, generated Owner approval, false host authenticity, or arbitrary JSON as capture evidence.
- No override of an actual failed review and no waiver of Verification, Acceptance, Self-Audit, Required CI, dependencies, human User Review, explicit merge authorization, merge, or closure.
- No Issue #63 / PR #64 work, Activation changes, second PR, historical receipt rewrite, or broader project opt-in.

## Verification obligations

Run and report on the exact current HEAD:

```text
python -m pip install -e .
python -m compileall runtime tools tests
python -m unittest discover -s tests -p 'test_*.py'
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

Read back Required CI for Ubuntu Python 3.10/3.14, Windows Python 3.14, macOS Python 3.14, and PR metadata on exact HEAD. Report unavailable host/OS smoke as `NOT RUN` or `UNAVAILABLE`, never PASS.

## Reviewer checklist

- [ ] Successor ADC is approved/published; predecessor records remain immutable.
- [ ] Default remains BLOCK; exact opt-in and one exact Owner grant are required.
- [ ] UNAVAILABLE and actual FAIL are never promoted to review PASS.
- [ ] V1 compatibility and strict exception identity/replay rules are verified.
- [ ] V2 Readiness and Final Delivery disclose risk; ordinary gates remain unchanged.
- [ ] User Review and Final Delivery revalidate all exact-subject facts.
- [ ] Codex Cloud, local Codex, and Claude Code report actual capability truthfully.
- [ ] Documentation, tests, traceability, distributions, Skills, and Required CI are current.
- [ ] Self-review records evidence; unavailable host/OS smoke is marked NOT RUN.

## Completion gates

1. Obtain exact-byte Owner approval for this candidate, publish the approved ADC pointer without rewriting predecessor history, append its Binding on the same worktree/base/branch, and verify all readbacks.
2. Run `delivery legacy-reset-plan 46` read-only against the current Issue/adoption/Binding. The Owner personally posts the exact generated approval comment. The implementation agent never writes or edits it.
3. Run the existing `delivery legacy-reset-apply 46` once with that exact plan and Owner comment ID. Verify the immutable Intent/Applied receipts and exact `phase:requirements` label by readback. On any stale/mismatch/block, perform no label or document mutation.
4. Commit the specification, design, test-oracle, and traceability updates in dependency order. Publish new-ADC-generation requirements→specification, specification→design, and design→ready receipts, advance the matching labels through the existing CLI, verify ready preparation, then re-enter execution.
5. Implement and verify the typed exception path on existing PR #67. Commit repository opt-in only after governance approval.
6. Require a frozen current Verification Plan; passing Verification/Acceptance/Self-Audit/Required CI; clean exact subject; current PRBinding; and eligible non-draft PR before making an exception plan.
7. Present the exact exception plan. The Owner personally posts its exact approval comment; the implementation agent never posts it. Apply once and read back.
8. Require current V2 `READY_WITH_EXCEPTION`, then real User Review and separately authorized exact-HEAD `PR_MERGE` through the ordinary process.

Report successor ADC/pointer, forward Phase receipts, Binding generations/digests, plan and Owner comment IDs/digests, exception record, V2 Readiness and Final Delivery, tests/CI, User Review, explicit merge decision, unverified hosts, and deviations. If approval or a technical prerequisite is unavailable, report BLOCKED, not COMPLETE. Never invent a merge SHA or Issue closure.

## Current observed prerequisites

- Approved predecessor ADC: comment #6390971577 / SHA-256 `8fa50df07dcece244cd015d84a6e92f8dea7ccf3fcba16099665c6f9c5918f64`; pointer comment #6390971929.
- PR #67 HEAD at contract authoring: `867905bd7f597227794778e1df3ac3e55087253e`; CI #40143383351 passed all five jobs. Refresh before each mutation.
- Read-only `delivery legacy-reset-plan 46` preflight returned `PLAN_READY` for current Issue labels, adoption record, and Owner identity; generated plan SHA-256 `a056f596a03940af2b728ad9c5bf7ff9b8b526448e0135a2a9db8f197b663787`. It was not saved or approved, and no reset was applied. Regenerate after the successor ADC/Binding update.
- Local `.p_ases/plans/46` has no frozen Verification Plan. The Legacy Adoption plan is a different plan type and cannot fill this field.
- ExecutionBinding now has a successor generation for ADC #6390971577, logical digest `664f11dc4f53016b50e5af49b97d3feb6d032b8e82c53388857d42c7a33b6213`; the frozen base/worktree/branch are unchanged.
- PRBinding generation #000001 still binds the earlier ADC and HEAD. Preserve it; append a current PRBinding through its supported path after the PR is eligible and before any exception plan.
- These facts are not approval of this corrected candidate, an exception plan, or an Owner exception grant.
