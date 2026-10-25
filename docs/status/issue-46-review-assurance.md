# Issue #46 Independent Review V2 capability status

<!-- contents:start -->
**Contents**
- [1 Current policy and follow-up](#1-current-policy-and-follow-up)
  - [1.1 Historical evidence state at the snapshot below](#11-historical-evidence-state-at-the-snapshot-below)
- [2 1 Current repository observations](#2-1-current-repository-observations)
- [3 2 Surface and OS status](#3-2-surface-and-os-status)
- [4 3 Acceptance boundary](#4-3-acceptance-boundary)
- [5 4 Ready receipt ancestry and recovery](#5-4-ready-receipt-ancestry-and-recovery)
- [6 5 UNAVAILABLE exception runtime path](#6-5-unavailable-exception-runtime-path)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
<!-- heading-map:end -->


<a id="current-policy-and-follow-up"></a>
## 1 Current policy and follow-up

The approved forward successor ADC for Issue #46 / PR #67 requires the Independent Review itself to occur even when its host provenance is `UNAVAILABLE`. `UNAVAILABLE` describes only the missing host-to-runtime provenance assurance. Preserve the legacy V2 result's `UNAVAILABLE`/`BLOCKED` meaning; a linked `PASES_INDEPENDENT_REVIEW_OCCURRENCE_V1` retains the exact reviewer output bytes, actual outcome/findings, exact subject, both bindings, and profile. No matching report means no review occurred and blocks the exception, Readiness, and User Review.

Approvals for Issue #46 lifecycle actions use the direct active chat UI with `承認する` / `承認しない`. The Owner is not asked to post an approval comment. A GitHub comment may still carry the typed technical evidence record; its author is recorded as the technical recorder, not the person who selected the chat answer. Chat provenance is operator-reported and is not claimed to be cryptographic.

This policy addendum supersedes older workflow descriptions below. The evidence statements in the following 2026-10-25 snapshot remain historical and must not be read as current status. A fresh review is required after every change to HEAD, ADC, plan, Binding, or profile. As of the pre-implementation source HEAD `261ebda9c686a27935373301c5b59e269d59a1b4`, no current review occurrence for the implementation changes in this worktree has been recorded; no unavailable-provenance exception, Readiness, User Review approval, merge authorization, or merge is claimed.

<a id="historical-evidence-state-at-the-snapshot-below"></a>
### 1.1 Historical evidence state at the snapshot below

Native review capture remained unavailable. The earlier Owner-comment exception implementation had no current review report and had not started User Review. The report and waiver status stated below describe that historical state only; they do not satisfy the current occurrence requirement.

**Snapshot date:** 2026-10-25, immediately before the PRBinding continuation patch was committed or pushed. This page records evidence state at the cited HEAD; later verification results are tracked in the PR conversation.

<a id="current-repository-observations"></a>
<a id="1-current-repository-observations"></a>
## 2 1 Current repository observations

- Runtime: Python unit and schema tests exercise exact native request, terminal return, child output, identity binding, profile policy, and V1-only rejection.
- `HOST_VERIFIED`: unavailable. No trusted host-owned event verifier is configured. A JSON event or an agent-writable Hook cannot satisfy this assurance.
- `INDEPENDENT_ATTESTED`: the data model validates internal byte bundles, but no adapter captures a host-native invocation. The attestation factory refuses caller-supplied bytes, the CLI reports `UNAVAILABLE` without writing a V2 review, and Readiness blocks even a manually constructed claim.
- Host IDs remain optional and are never synthesized.
- The project profile explicitly selects `independent_attested` and, for the approved Issue #46 / PR #67 scope, `unavailable_handling: owner_exception`. The latter does not change the minimum assurance or make caller-supplied or fabricated bytes acceptable.
- On 2026-10-24, a separate Codex Cloud collaboration child was started for exact HEAD `67f9252bbfa348e3dbb572a25a885b1ed710e7c1`. The host returned its child-authored `FINAL_ANSWER`; the exact request and answer text are preserved in [the capture observation](issue-46-native-capture-smoke-2026-10-24.json). The child verdict was `FAIL` because the runtime adapter still has no native capture path. The captured observation is operator-copied from tool messages, not host-signed evidence or an `IndependentReviewV2`.
- A second blind probe child completed through `spawn_agent` → `wait_agent` on HEAD `fe34716412a0a6ff17197608b0eedbffe80dca28` and confirmed that the parent conversation receives the child result, while the Python runtime has no bridge for the raw host request/terminal/output. Its tool request, completion, and `FINAL_ANSWER` are kept as a separate exchange in the same observation file. This verifies the host orchestration call only, not the runtime adapter.
- The stored review child output remains diagnostic only: its subject uses four legacy keys instead of the seven canonical `VerificationSubject` keys, its `INFO` severities are invalid, and it was reviewed against an older HEAD. The raw bytes remain unchanged; a separate validation note records why they cannot be ingested as V2. A current frozen Verification Plan now exists at `.p_ases/plans/46/309ab187bc57b6b3b0851fe4dda2747f89881f49afd3b482149d9cf708d36eef.json`; it is distinct from `legacy-adoption-plan.json`.
- On PR #67 HEAD `2359d6093fc2de247da40394f8087347e52e7628`, the exact Verification result `f7b913760891d9415e2f4b7f1b7e5447fc3441c0e33d87ae399ab799a2f47eb9` (Issue comment #6398087563), Acceptance result `9b3e29ce9e8e151617395508e31918336dc40bd1381f84a789d10d0446e1e955` (Issue comment #6398102484), Self-Audit `2c94dac154430f03fa2383b96c7d3ec59b9af252d9cea2be23bf151697b00be7`, and Actions run #40192916605 were reported PASS. The PR body contains the required sole closing line `Closes #46` and the PR is ready, not draft. These results are historical once the current local changes are committed.
- The remaining live exception prerequisite was the missing current PRBinding: generation #000001 still binds ADC comment #6371444320 / SHA-256 `e7fda8f61a28c31e50b118c44e7cbb9e42c2b3a00270338a9f441919504ff66b` and an older HEAD. The current approved ADC is comment #6391179626 / SHA-256 `fed22bd6c2fdb17f180ea1fce61f60dc62809cbccc163a9ea8d6b530d8a97d0a`. This code change adds a forward-only PRBinding append path; no current successor PRBinding or exception receipt has yet been applied.
- The environment still exposes no supported host-to-Python capture API. Independent Review remains `UNAVAILABLE`, and native runtime adapter smoke tests remain NOT RUN or UNAVAILABLE. The exception path can disclose this absence only after an exact Owner grant and the other delivery gates pass.

<a id="surface-and-os-status"></a>
<a id="2-surface-and-os-status"></a>
## 3 2 Surface and OS status

| Surface | Native capture integration | Trusted host event verifier | Smoke-test status |
|---|---|---|---|
| Codex Cloud | Host-level `spawn_agent` child result observed; not connected to this runtime package | Unavailable | Host delegation observed; runtime adapter E2E NOT RUN; child verdict FAIL |
| Codex local CLI | Not connected by this runtime package | Unavailable | NOT RUN |
| Codex Desktop | Not connected by this runtime package | Unavailable | NOT RUN |
| Claude Code | Not connected by this runtime package; Hook files are not trusted provenance | Unavailable | NOT RUN |
| Linux / Windows / macOS host behavior | No host-native E2E executed | Unavailable | NOT RUN |

<a id="acceptance-boundary"></a>
<a id="3-acceptance-boundary"></a>
## 4 3 Acceptance boundary

No runtime or OS adapter integration is reported as verified by unit tests. The direct Codex Cloud collaboration call demonstrated that this parent conversation can receive a real child response, but no supported transport passes the host-owned request/terminal event into the Python runtime. The current package therefore has no verifiable host-capture boundary; locally supplied, self-consistent request/terminal/output JSON is not accepted as evidence that a child actually ran. The public attestation factory refuses to issue an `INDEPENDENT_ATTESTED` record from such bytes; if a claim is constructed outside that factory, evaluation downgrades it to effective `UNAVAILABLE` and blocks ordinary Readiness. The approved exception path records `review_assurance=UNAVAILABLE` and `INDEPENDENT_REVIEW_NOT_PERFORMED`; it does not create a review PASS. A future runtime capture integration and trusted host verifier must be independently implemented and tested before any surface can issue `HOST_VERIFIED`.

<a id="ready-receipt-ancestry-and-recovery"></a>
<a id="4-ready-receipt-ancestry-and-recovery"></a>
## 5 4 Ready receipt ancestry and recovery

- A `PASES_PHASE_DECISION_V1` Ready receipt remains bound to its exact branch HEAD. A descendant commit does not silently satisfy `ready → execution`, even when all ADC-declared specification, design, and test-oracle bytes have the same hashes.
- Issue #46 has a narrowly scoped `PASES_READY_REBASELINE_V1` recovery checkpoint. Its plan binds the exact approved ADC, ExecutionBinding, prior Ready receipt, current PR/HEAD, current candidate Ready decision, and changed paths. Changed Ready artifacts must retain the ADC-declared path/role set and pass the repository document and traceability validation.
- The Owner must post the exact generated approval comment on Issue #46. Applying it appends one Intent and one Applied record and does not edit old receipts or change the Phase label. Only the exact Applied comment ID may authorize the normal `ready → execution` command to use that checkpoint.
- Every descendant, including one with unchanged Ready artifact hashes, requires a fresh exact-subject checkpoint approval. Stale plans, a second checkpoint attempt, missing or edited approval, changed HEAD/Binding/ADC/PR, and incomplete writes fail closed. The approved checkpoint #6392478403 was verified and applied; Intent #6392495592 and Applied #6392509109 were read back, and Issue #46 advanced from `ready` to `execution`.

<a id="unavailable-exception-runtime-path"></a>
<a id="5-unavailable-exception-runtime-path"></a>
## 6 5 UNAVAILABLE exception runtime path

- `runtime/p_ases/review_unavailable_exception.py` defines canonical exact-subject plan, Owner approval, append-only Issue receipt, and immutable local receipt types. Owner and receipt comments are verified by direct/list/direct readback with stable IDs, Issue/API/HTML URLs, unchanged body, and creation/update timestamps.
- `review-unavailable-plan` requires the frozen current Verification Plan, current exact Verification PASS / Required Checks, clean non-draft exact PR subject, current ADC and both bindings, committed `owner_exception` profile, and a positive adapter capability observation. It prints the exact approval text and does not write to GitHub.
- `review-unavailable-apply` is the sole writer of the implementation-authored exception receipt. It does not create the Owner grant. Exact replay is read-only; conflicting, duplicate, stale, edited, or ambiguous evidence fails closed.
- Shared non-review Readiness checks now produce a typed `ReadinessCore`. Ordinary `PASES_REVIEW_READINESS_V1` serialization remains unchanged. The exception route emits `PASES_REVIEW_READINESS_V2` with `READY_WITH_EXCEPTION` or `BLOCKED`, explicit `UNAVAILABLE`, exception/Owner identities, and the accepted risk.
- User Review can consume V1 `PASS` or exact V2 `READY_WITH_EXCEPTION`; its V1 artifact bytes and human approval semantics remain unchanged. Final Delivery emits a separate V2 result with `READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION`, `merge_authorized=false`, and the same visible disclosure.
- Follow-up review #6393047728 findings on User Review are addressed in the source at this snapshot: every start/sync/status recomputes all non-review gates before feedback or writes; exception consumers reject malformed, duplicate, or conflicting same-HEAD marker history; actual Issue kind/phase/attention is checked before persistence and again before phase update. A V2 consumer regression supplies a failed current Acceptance and asserts no feedback read, session/result file, or phase transition. PRBinding lineage tests cover approved-successor append, old-byte preservation, stale ExecutionBinding rejection, and ADC rollback. The local patch worktree passes 433 unit tests, compileall, documentation validation/format, all three traceability checks, distribution validation, and 16-Skill acceptance. `python -m pip install -e .` could not install into the read-only default user site; document commands passed with `PYTHONPATH=runtime`.
- **Gate status at this snapshot (pre-push):** exact-HEAD CI and refreshed Verification/Acceptance/Self-Audit/Required Check evidence, successor PRBinding readback, exact exception plan and Owner approval, live Readiness V2, User Review, and Final Delivery remained pending. No merge authorization is recorded. Codex local/Desktop and Claude runtime smoke remain `NOT RUN`. Later results are recorded in the PR conversation rather than inferred from this historical status snapshot.
