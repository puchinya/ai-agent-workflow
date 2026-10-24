# Issue #46 ADC Successor Amendment — Owner-Authorized UNAVAILABLE Continuation

**Repository:** `puchinya/ai-agent-workflow` (repository ID `1401910271`)  
**Issue:** #46 (stable ID `5846549384`)  
**Candidate state:** Draft forward-only successor amendment; not approved, published, or implemented.  
**Current approved ADC body:** Issue comment #6371444320; SHA-256 `e7fda8f61a28c31e50b118c44e7cbb9e42c2b3a00270338a9f441919504ff66b`; approved pointer #6371443467.  
**Owner policy proposal:** Issue comment #6385026889, supplemented by the Owner-provided Implementation Contract “Owner-Authorized UNAVAILABLE Continuation.” The proposal is not an exact exception-plan approval.  
**Inspected source HEAD:** `88fd54d21eb104a01c6a7fff137aada9a23268e3`.  
**Inspected PR:** #67, OPEN/draft, base `main`, head branch `codex/issue-46-multi-host-independent-review`.  
**Current Issue state:** OPEN, `phase:execution`, `kind:single`.  
**Current Activation / Adoption / Gate / Phase history:** Preserve the existing #57 Activation, Adoption #6378977263, Gate #6378981726, and phase receipts #6378987892, #6379017206, and #6379085920 byte-for-byte.  
**Frozen base and branch:** `main` / `a5203917d2e3f784f68c05cba48c7428689e777e`; `codex/issue-46-multi-host-independent-review`; keep the existing worktree and ancestry.

> This amendment is proposed scope only. Implementation must wait for exact successor ADC approval and the forward-only phase/document rebaseline. Do not redesign the architecture or silently change the approved requirement.

## 1. Successor relationship and scope

When approved and published, this amendment becomes a forward-only successor to the current approved ADC identified above. It adopts every predecessor requirement, decision, invariant, risk disclosure, and non-goal unchanged except for the replacement text of `REQ-F06-006` below and the new `REQ-F06-010` through `REQ-F06-013`. The old ADC, pointer, bindings, adoption/gate records, and phase receipts remain immutable.

The scope is a narrowly bounded owner-authorized continuation when, and only when, the selected host genuinely cannot deliver native child-review capture to the P-ASES runtime. It permits a separate, visibly degraded readiness and delivery result. It never reports that an Independent Review occurred or passed, and it does not waive Verification, Acceptance, Self-Audit, Required CI, dependencies, human User Review, PR merge authorization, merge, or Issue closure.

This amendment does not alter the Independent Review `HOST_VERIFIED`, `INDEPENDENT_ATTESTED`, `SELF_REVIEW`, or `UNAVAILABLE` meanings; V1/V2 review serializers or digests; native-capture fabrication refusal; or the committed `minimum_assurance` policy. The optional exception behavior is separately configured, owner-authorized, exact-subject, and default-off.

## 2. Replacement requirement

### REQ-F06-006 — Readiness and downstream gates (successor text)

Independent-review ingestion, ordinary Readiness, and ordinary Final Delivery require a positive current review eligible under the committed profile. Existing V1 `PASS` behavior and all V1 bytes remain unchanged. A separate V2 readiness result may be `READY_WITH_EXCEPTION` only when a valid exact-subject owner exception satisfies `REQ-F06-010` through `REQ-F06-013` and every other readiness gate passes.

The exception may replace only the missing-review condition caused by a positively observed `HOST_NATIVE_CAPTURE_UNAVAILABLE` capability. It must preserve `review_assurance=UNAVAILABLE` and must never create an Independent Review PASS record or label. `SELF_REVIEW`, stale or malformed evidence, missing Verification Plan, wrong subject, failed or incomplete Required CI, failed Verification/Acceptance/Self-Audit, unresolved dependency, or any other unavailable cause remains `BLOCKED`.

A current completed native review with verdict `FAIL`, `BLOCKED`, or `CONCERNS`, or any unresolved A/B/C finding, is not eligible for the exception. A stale historical diagnostic is not a current review result and is not converted into one. A blocked review or invalid exception causes zero User Review session starts and zero Phase mutations.

## 3. Additional requirements

### REQ-F06-010 — Explicit opt-in and typed capture-unavailability decision

Profile Schema 2 may add `independent_review.unavailable_handling` with exactly `block` or `owner_exception`. Omission defaults to `block` for every repository. `minimum_assurance` remains unchanged. Only `puchinya/ai-agent-workflow` may commit `owner_exception`, and that opt-in applies only to repository ID `1401910271`, Issue #46 / stable ID `5846549384`, and PR #67. It may be committed only after this successor ADC is approved and its required phase/document rebaseline is complete. Host detection, CLI flags, environment variables, and Issue identity cannot enable the exception.

The runtime must produce a typed eligibility decision distinguishing `HOST_NATIVE_CAPTURE_UNAVAILABLE`, `REVIEW_FAILED`, and `INVALID_EVIDENCE`. Only an observed absence of the host-to-runtime native capture capability qualifies. Missing plan/evidence, stale subject, malformed input, failed CI, or a genuine failed review never qualifies. A genuine eligible native review takes the existing ordinary V1 readiness path and is not shadowed by the exception.

### REQ-F06-011 — Exact plan, Owner authorization, and append-only exception record

Provide read-only canonical `PASES_REVIEW_UNAVAILABLE_EXCEPTION_PLAN_V1` and immutable `PASES_REVIEW_UNAVAILABLE_EXCEPTION_V1` records. The plan binds repository name and ID; Owner user ID `3744776`; Issue number and stable ID; PR number, base ref, base SHA, branch, and exact HEAD; current approved ADC comment ID and SHA; frozen Verification Plan SHA; current ExecutionBinding and PRBinding SHA; committed profile SHA; observed host surface; reason `HOST_NATIVE_CAPTURE_UNAVAILABLE`; digest references for the capability observations; enumerated risk `INDEPENDENT_REVIEW_NOT_PERFORMED`; and the plan SHA-256. The risk statement must disclose that code defects may go undetected because no independent review result was available; it must not imply review completion or acceptance of any actual review finding.

The plan command emits the exact approval text. The repository Owner (stable GitHub user ID `3744776`) must personally post that exact text as a comment on Issue #46. The implementation agent must never create or edit the Owner approval comment. The canonical marker is:

```text
<!-- PASES_REVIEW_UNAVAILABLE_APPROVAL_V1
{"approved":true,"issue_number":46,"plan_sha256":"<64-digit digest from the actual plan>","pr_number":67,"repository":"puchinya/ai-agent-workflow","schema":"PASES_REVIEW_UNAVAILABLE_APPROVAL_V1"}
-->
```

The verifier compares the complete literal comment with its canonical formatter; authenticates the stable Owner ID; verifies repository, Issue, comment API URL, Issue URL, HTML URL, exact unedited content and timestamp; and performs direct/list/direct readback. Missing, edited, duplicated, conflicting, wrong-Owner, stale, or mismatched approval blocks before writes. This establishes Owner-account operational provenance, not cryptographic or physical-device proof.

After verifying the Owner comment, Apply is the sole writer of a distinct append-only Issue receipt `PASES_REVIEW_UNAVAILABLE_EXCEPTION_V1` and its immutable local evidence record. The exception receipt records the exact plan SHA, Owner comment ID and digest, all bound subject/profile identities, the typed unavailable reason, and enumerated risk. The Owner approval comment and the implementation-authored exception receipt are separate records; the latter never represents Owner approval. Apply rechecks all bound inputs immediately before writing and reads the receipt back directly, through the complete list, and directly again. Exact replay is a read-only NOOP. Ambiguous outcome, duplicate/conflicting history, stale plan, or partial readback blocks without blind retry or replacement. Missing frozen Verification Plan blocks plan generation; the Legacy Adoption plan is not a substitute.

### REQ-F06-012 — Versioned readiness and delivery results

Preserve all `PASES_REVIEW_READINESS_V1` serializers, readers, bytes, and behavior. Add distinct `PASES_REVIEW_READINESS_V2` with statuses `READY_WITH_EXCEPTION` or `BLOCKED`, `review_assurance=UNAVAILABLE`, exact Verification subject and profile digests, exception record and Owner comment IDs/digests, and the enumerated accepted risk. `READY_WITH_EXCEPTION` is valid only if every non-review gate is PASS and the exact Owner exception remains current.

Preserve all V1 final-delivery bytes and behavior. Add a distinct `PASES_FINAL_DELIVERY_V2` result for the exception route. Its ready status is `READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION`; it must disclose `review_assurance=UNAVAILABLE`, bind the exact exception digest, and set `merge_authorized=false`. This result does not itself authorize or perform a merge.

### REQ-F06-013 — Downstream consumption and exact-subject revalidation

User Review may start from ordinary `PASES_REVIEW_READINESS_V1 PASS` or exact current `PASES_REVIEW_READINESS_V2 READY_WITH_EXCEPTION`. It remains a separate explicit human decision. Preserve V1 User Review artifact bytes. On every readiness recomputation, User Review start/submit, and Final Delivery evaluation, reread and validate exact PR/HEAD, ADC, Verification Plan, ExecutionBinding, PRBinding, profile, exception record, Owner comment, Required CI, dependencies, Verification, Acceptance, and Self-Audit.

A change in any bound input invalidates the exception before side effects. The exception never bypasses a draft PR, failed check, dirty checkout, unmet dependency, actual current review failure, or explicit `PR_MERGE` authorization. Apply the same semantics on Codex Cloud, local Codex CLI/Desktop, and Claude Code; adapters must continue to report actual capabilities truthfully. Agent-writable Claude Hook records never establish `HOST_VERIFIED`.

## 4. Required design and test-oracle rebaseline

After exact successor ADC approval and before runtime implementation, forward-rebaseline the affected normative artifacts while preserving all previous receipt-bound bytes and journal entries:

- `docs/specs/workflow-spec.md`: replace `REQ-F06-006`; add `REQ-F06-010` through `REQ-F06-013`.
- `docs/design/workflow-design.md`: add a separate exception plan/record, eligibility decision, V2 readiness/final-delivery variants, and downstream revalidation. Do not alter old receipt-bound bytes in place; use the repository's forward phase-rebaseline procedure.
- `docs/testing/pases-lifecycle-tests.md`: add tests for default blocking, exact owner opt-in, valid exception, stale/missing/malformed/wrong-owner input, actual review FAIL, and all downstream gates.
- `docs/testing/runtime-tests.md`: add profile schema, approval parsing, exact readback, replay/recovery, and versioned-consumer cases.
- `docs/testing/traceability.md`: map every added requirement through a design decision and test Oracle to executable evidence.

No runtime or profile behavior changes before those approved successor artifacts and required phase receipts exist.

## 5. Implementation change set after governance approval

- `runtime/p_ases/profile.py`: strict optional `unavailable_handling`; absent remains `block`.
- New `runtime/p_ases/review_unavailable_exception.py`: strict canonical plans, exact Owner approval verification, immutable records, full identity/digest checks, unique-history/replay/conflict checks, and fail-closed recovery.
- `runtime/p_ases/review_assurance.py`: retain native assurance logic; add only a typed capture-unavailability eligibility decision.
- `runtime/p_ases/delivery.py`: keep V1 results unchanged; add V2 readiness and final-delivery result types and readers. Factor common non-review checks only where V1 output remains byte-identical.
- `runtime/p_ases/user_review.py`: accept exact current V1 PASS or V2 READY_WITH_EXCEPTION, preserving existing User Review bytes.
- `runtime/p_ases/cli.py`: add exactly:
  - `delivery review-unavailable-plan ISSUE PR HEAD VERIFICATION_PLAN --host-surface SURFACE --output PLAN_FILE`, where surface is `codex_cloud`, `codex_local_cli`, `codex_desktop`, or `claude_code`;
  - `delivery review-unavailable-apply ISSUE PR HEAD VERIFICATION_PLAN --plan PLAN_FILE --approval-comment-id ID` as the sole writer.
  - Readiness and final-delivery commands retain the current positional independent-review input for normal use. It may be omitted only when `--review-unavailable-exception PATH` is supplied; reject both or neither. Revalidate the same selected evidence through `_delivery_readiness`, `_require_readiness_review_assurance`, `_user_review_run`, and `_delivery_final`.
- Update review, User Review, and delivery Skills; `adapters/openai/README.md`, `adapters/claude/README.md`; and `docs/status/issue-46-review-assurance.md`. Keep all four host surfaces consistent. Regenerate all three distributions only with `python tools/build_dist.py`.
- Add `tests/test_review_unavailable_exception.py`; extend profile, review assurance, readiness, User Review CLI, P-ASES CLI, and final-delivery tests.

## 6. Invariants and non-goals

- Never call `UNAVAILABLE` an Independent Review PASS or `INDEPENDENT_ATTESTED`.
- Never set the native capture capability flag to true without an actual host API; never fabricate host IDs, child returns, approval, or evidence.
- Never override an actual current `FAIL`, `BLOCKED`, `CONCERNS`, or unresolved A/B/C finding.
- No global force flag, blanket project downgrade, skipped CI, skipped human User Review, implicit merge authority, or Issue closure authority.
- No modification of Issue #63/PR #64, Activation, #26–#32, approved ADC/pointer/history, old Adoption/Gate/Phase/Binding records, or historical raw review bytes.
- Preserve V1 review/readiness/final-delivery/User Review bytes and behavior exactly.
- Use only the existing PR #67. Do not open another implementation PR.

## 7. Required validation after implementation

Run and report each result on the exact current HEAD:

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

Read back Required CI for Ubuntu Python 3.10/3.14, Windows Python 3.14, macOS Python 3.14, and PR metadata on the exact HEAD. Report unavailable host/OS smoke as `NOT RUN` or `UNAVAILABLE`.

## 8. Ordered execution and completion

1. Prepare this exact successor ADC candidate and obtain its Owner approval; publish the approved pointer without rewriting predecessor history.
2. Append the appropriate successor Binding on the same worktree, base, and branch. Forward-rebaseline the spec/design/test-oracle and obtain the required receipts before implementation.
3. Implement and verify the typed exception path in the existing PR #67. The project opt-in is committed only after governance approval.
4. Require a frozen current Verification Plan, current passing Verification/Acceptance/Self-Audit/Required CI, clean exact subject, current PRBinding, and a non-draft eligible PR before producing an exception plan.
5. Present the exact plan; the Owner personally posts the exact approval comment. The implementation agent never posts it. Apply once and read back.
6. Require current V2 `READY_WITH_EXCEPTION`, then real User Review and separate exact-HEAD `PR_MERGE` authorization through the ordinary process.

Report the successor ADC/pointer, forward phase receipts, Binding generations/digests, plan and Owner comment IDs/digests, exception record, V2 Readiness and Final Delivery, tests/CI, User Review, explicit merge decision, unverified hosts, and deviations. If approval or a technical prerequisite is unavailable, report `BLOCKED`, not `COMPLETE`. Do not invent a merge SHA or Issue closure.

## 9. Current observed prerequisites (not approvals)

- Approved ADC predecessor: comment #6371444320 / SHA-256 `e7fda8f61a28c31e50b118c44e7cbb9e42c2b3a00270338a9f441919504ff66b`; pointer comment #6371443467.
- Latest reviewed PR HEAD: `88fd54d21eb104a01c6a7fff137aada9a23268e3`; CI #40097753905 passed all five jobs.
- Local `.p_ases/plans/46` has no frozen Verification Plan. The Legacy Adoption plan SHA is a different plan type and cannot fill this field.
- Current local PRBinding generation #000001 has digest `f729ca3ad0652e12e257ea71e0fbc04c660d4a8ae9aab8ef1561a4f506b0b16d` and binds older PR HEAD `487eb11ac30bbb9dc8590c39fa7eec9271ca0bfa`; preserve it and append a new binding generation before an exact-current-head exception plan.
- These facts do not constitute approval of this candidate, an exception plan, or an Owner grant.
