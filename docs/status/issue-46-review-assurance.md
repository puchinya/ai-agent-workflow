# Issue #46 Independent Review V2 capability status

**Evidence state:** Code-level validation is implemented. A live Codex Cloud collaboration child returned a real review response, but the Python runtime cannot consume the host event; runtime adapter verification is not established. A unit fixture is not a host smoke test.

<!-- contents:start -->
**Contents**
- [1 Current repository observations](#1-current-repository-observations)
- [2 Surface and OS status](#2-surface-and-os-status)
- [3 Acceptance boundary](#3-acceptance-boundary)
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
- The project profile explicitly selects `independent_attested`. This is an Owner-authorized project setting; it does not make caller-supplied or fabricated bytes acceptable and does not bypass actual capture.
- On 2026-10-24, a separate Codex Cloud collaboration child was started for exact HEAD `67f9252bbfa348e3dbb572a25a885b1ed710e7c1`. The host returned its child-authored `FINAL_ANSWER`; the exact request and answer text are preserved in [the capture observation](issue-46-native-capture-smoke-2026-10-24.json). The child verdict was `FAIL` because the runtime adapter still has no native capture path. The captured observation is operator-copied from tool messages, not host-signed evidence or an `IndependentReviewV2`.
- A second blind probe child completed through `spawn_agent` → `wait_agent` on HEAD `fe34716412a0a6ff17197608b0eedbffe80dca28` and confirmed that the parent conversation receives the child result, while the Python runtime has no bridge for the raw host request/terminal/output. Its tool request, completion, and `FINAL_ANSWER` are kept as a separate exchange in the same observation file. This verifies the host orchestration call only, not the runtime adapter.
- PR review comment [#6384605256](https://github.com/puchinya/ai-agent-workflow/pull/67#issuecomment-6384605256) confirmed that the stored review child output is diagnostic only: its subject uses four legacy keys instead of the seven canonical `VerificationSubject` keys, its `INFO` severities are invalid, and it was reviewed against an older HEAD. The raw bytes remain unchanged; a separate validation note records why they cannot be ingested as V2. At this worktree snapshot, `.p_ases/plans/46` contains no frozen Verification Plan; the existing `legacy-adoption-plan.json` digest is a different plan type and cannot be substituted for `plan_sha256`.
- The same review reconfirmed the external capability blocker: this environment exposes no supported host-to-Python capture API. The runtime therefore remains fail-closed, with all native runtime adapter smoke tests NOT RUN or UNAVAILABLE. Do not set the capture-boundary flag or issue a V2 record without that API.

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

No runtime or OS adapter integration is reported as verified by unit tests. The direct Codex Cloud collaboration call demonstrated that this parent conversation can receive a real child response, but no supported transport passes the host-owned request/terminal event into the Python runtime. The current package therefore has no verifiable host-capture boundary; locally supplied, self-consistent request/terminal/output JSON is not accepted as evidence that a child actually ran. The public attestation factory refuses to issue an `INDEPENDENT_ATTESTED` record from such bytes; if a claim is constructed outside that factory, evaluation downgrades it to effective `UNAVAILABLE` and blocks Readiness. A future runtime capture integration and trusted host verifier must be independently implemented and tested before any surface can issue `HOST_VERIFIED`.
