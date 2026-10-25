# Issue #46 Independent Review V2 capability status

**Evidence state:** Native review capture remains unavailable. The approved Owner-authorized UNAVAILABLE continuation is implemented in code, including the exact Owner plan/receipt flow and separate Readiness V2 / Final Delivery V2; no exception has been applied and no User Review has started. A unit fixture is not a host smoke test.

<!-- contents:start -->
**Contents**
- [1 Current repository observations](#1-current-repository-observations)
- [2 Surface and OS status](#2-surface-and-os-status)
- [3 Acceptance boundary](#3-acceptance-boundary)
- [4 Ready receipt ancestry and recovery](#4-ready-receipt-ancestry-and-recovery)
- [5 UNAVAILABLE exception runtime path](#5-unavailable-exception-runtime-path)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
<!-- heading-map:end -->


<a id="current-repository-observations"></a>
## 1 Current repository observations

- Runtime: Python unit and schema tests exercise exact native request, terminal return, child output, identity binding, profile policy, and V1-only rejection.
- `HOST_VERIFIED`: unavailable. No trusted host-owned event verifier is configured. A JSON event or an agent-writable Hook cannot satisfy this assurance.
- `INDEPENDENT_ATTESTED`: the data model validates internal byte bundles, but no adapter captures a host-native invocation. The attestation factory refuses caller-supplied bytes, the CLI reports `UNAVAILABLE` without writing a V2 review, and Readiness blocks even a manually constructed claim.
- Host IDs remain optional and are never synthesized.
- The project profile explicitly selects `independent_attested` and, for the approved Issue #46 / PR #67 scope, `unavailable_handling: owner_exception`. The latter does not change the minimum assurance or make caller-supplied or fabricated bytes acceptable.
- On 2026-10-24, a separate Codex Cloud collaboration child was started for exact HEAD `67f9252bbfa348e3dbb572a25a885b1ed710e7c1`. The host returned its child-authored `FINAL_ANSWER`; the exact request and answer text are preserved in [the capture observation](issue-46-native-capture-smoke-2026-10-24.json). The child verdict was `FAIL` because the runtime adapter still has no native capture path. The captured observation is operator-copied from tool messages, not host-signed evidence or an `IndependentReviewV2`.
- A second blind probe child completed through `spawn_agent` → `wait_agent` on HEAD `fe34716412a0a6ff17197608b0eedbffe80dca28` and confirmed that the parent conversation receives the child result, while the Python runtime has no bridge for the raw host request/terminal/output. Its tool request, completion, and `FINAL_ANSWER` are kept as a separate exchange in the same observation file. This verifies the host orchestration call only, not the runtime adapter.
- PR review comment [#6384605256](https://github.com/puchinya/ai-agent-workflow/pull/67#issuecomment-6384605256) confirmed that the stored review child output is diagnostic only: its subject uses four legacy keys instead of the seven canonical `VerificationSubject` keys, its `INFO` severities are invalid, and it was reviewed against an older HEAD. The raw bytes remain unchanged; a separate validation note records why they cannot be ingested as V2. At this worktree snapshot, `.p_ases/plans/46` contains no frozen Verification Plan; the existing `legacy-adoption-plan.json` digest is a different plan type and cannot be substituted for `plan_sha256`.
- The same review reconfirmed the external capability blocker: this environment exposes no supported host-to-Python capture API. The runtime therefore remains fail-closed for Independent Review, with all native runtime adapter smoke tests NOT RUN or UNAVAILABLE. The exception path can disclose this absence only after an exact Owner grant and the other delivery gates pass.

<a id="surface-and-os-status"></a>
## 2 Surface and OS status

| Surface | Native capture integration | Trusted host event verifier | Smoke-test status |
|---|---|---|---|
| Codex Cloud | Host-level `spawn_agent` child result observed; not connected to this runtime package | Unavailable | Host delegation observed; runtime adapter E2E NOT RUN; child verdict FAIL |
| Codex local CLI | Not connected by this runtime package | Unavailable | NOT RUN |
| Codex Desktop | Not connected by this runtime package | Unavailable | NOT RUN |
| Claude Code | Not connected by this runtime package; Hook files are not trusted provenance | Unavailable | NOT RUN |
| Linux / Windows / macOS host behavior | No host-native E2E executed | Unavailable | NOT RUN |

<a id="acceptance-boundary"></a>
## 3 Acceptance boundary

No runtime or OS adapter integration is reported as verified by unit tests. The direct Codex Cloud collaboration call demonstrated that this parent conversation can receive a real child response, but no supported transport passes the host-owned request/terminal event into the Python runtime. The current package therefore has no verifiable host-capture boundary; locally supplied, self-consistent request/terminal/output JSON is not accepted as evidence that a child actually ran. The public attestation factory refuses to issue an `INDEPENDENT_ATTESTED` record from such bytes; if a claim is constructed outside that factory, evaluation downgrades it to effective `UNAVAILABLE` and blocks ordinary Readiness. The approved exception path records `review_assurance=UNAVAILABLE` and `INDEPENDENT_REVIEW_NOT_PERFORMED`; it does not create a review PASS. A future runtime capture integration and trusted host verifier must be independently implemented and tested before any surface can issue `HOST_VERIFIED`.

<a id="ready-receipt-ancestry-and-recovery"></a>
## 4 Ready receipt ancestry and recovery

- A `PASES_PHASE_DECISION_V1` Ready receipt remains bound to its exact branch HEAD. A descendant commit does not silently satisfy `ready → execution`, even when all ADC-declared specification, design, and test-oracle bytes have the same hashes.
- Issue #46 has a narrowly scoped `PASES_READY_REBASELINE_V1` recovery checkpoint. Its plan binds the exact approved ADC, ExecutionBinding, prior Ready receipt, current PR/HEAD, current candidate Ready decision, and changed paths. Changed Ready artifacts must retain the ADC-declared path/role set and pass the repository document and traceability validation.
- The Owner must post the exact generated approval comment on Issue #46. Applying it appends one Intent and one Applied record and does not edit old receipts or change the Phase label. Only the exact Applied comment ID may authorize the normal `ready → execution` command to use that checkpoint.
- Every descendant, including one with unchanged Ready artifact hashes, requires a fresh exact-subject checkpoint approval. Stale plans, a second checkpoint attempt, missing or edited approval, changed HEAD/Binding/ADC/PR, and incomplete writes fail closed. The approved checkpoint #6392478403 was verified and applied; Intent #6392495592 and Applied #6392509109 were read back, and Issue #46 advanced from `ready` to `execution`.

<a id="unavailable-exception-runtime-path"></a>
## 5 UNAVAILABLE exception runtime path

- `runtime/p_ases/review_unavailable_exception.py` defines canonical exact-subject plan, Owner approval, append-only Issue receipt, and immutable local receipt types. Owner and receipt comments are verified by direct/list/direct readback with stable IDs, Issue/API/HTML URLs, unchanged body, and creation/update timestamps.
- `review-unavailable-plan` requires the frozen current Verification Plan, current exact Verification PASS / Required Checks, clean non-draft exact PR subject, current ADC and both bindings, committed `owner_exception` profile, and a positive adapter capability observation. It prints the exact approval text and does not write to GitHub.
- `review-unavailable-apply` is the sole writer of the implementation-authored exception receipt. It does not create the Owner grant. Exact replay is read-only; conflicting, duplicate, stale, edited, or ambiguous evidence fails closed.
- Shared non-review Readiness checks now produce a typed `ReadinessCore`. Ordinary `PASES_REVIEW_READINESS_V1` serialization remains unchanged. The exception route emits `PASES_REVIEW_READINESS_V2` with `READY_WITH_EXCEPTION` or `BLOCKED`, explicit `UNAVAILABLE`, exception/Owner identities, and the accepted risk.
- User Review can consume V1 `PASS` or exact V2 `READY_WITH_EXCEPTION`; its V1 artifact bytes and human approval semantics remain unchanged. Final Delivery emits a separate V2 result with `READY_FOR_EXPLICIT_MERGE_AUTHORIZATION_WITH_EXCEPTION`, `merge_authorized=false`, and the same visible disclosure.
- Follow-up review #6394569165 hardening: every User Review start/sync/status now recomputes and compares the full current Readiness inputs before use and before writes; same-HEAD malformed, duplicate, and conflicting exception history is rejected by readers; actual Issue kind/phase/attention is checked before persistence and immediately before any phase update; exception-path runtime failures are returned as structured `BLOCKED` output. The added CLI/history regressions and full local unit suite pass (425 tests); exact candidate-HEAD CI is pending.
- **Not yet performed:** no frozen Verification Plan, exact exception plan, Owner exception approval, or applied exception receipt is currently recorded; no live User Review or Final Delivery has run. Codex local/Desktop and Claude runtime smoke remain `NOT RUN`. This report must be refreshed after verification and exact-head CI.
