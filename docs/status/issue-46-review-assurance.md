# Issue #46 Independent Review V2 capability status

**Evidence state:** Code-level validation is implemented; live host verification is not established. A unit fixture is not a host smoke test.

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
- `INDEPENDENT_ATTESTED`: the runtime can validate captured native request, terminal, and child-output byte bundles. This records `operator_captured_native_tool_result`; it proves tamper evidence after capture, not cryptographic host origin.
- Host IDs remain optional and are never synthesized.
- Project profile default remains `host_verified`. `independent_attested` requires an explicit committed profile setting.

<a id="surface-and-os-status"></a>
## 2 Surface and OS status

| Surface | Native capture integration | Trusted host event verifier | Smoke-test status |
|---|---|---|---|
| Codex Cloud | Not connected by this runtime package | Unavailable | NOT RUN |
| Codex local CLI | Not connected by this runtime package | Unavailable | NOT RUN |
| Codex Desktop | Not connected by this runtime package | Unavailable | NOT RUN |
| Claude Code | Not connected by this runtime package; Hook files are not trusted provenance | Unavailable | NOT RUN |
| Linux / Windows / macOS host behavior | No host-native E2E executed | Unavailable | NOT RUN |

<a id="acceptance-boundary"></a>
## 3 Acceptance boundary

No host or OS integration is reported as verified by unit tests. A surface must provide its actual native request, successful terminal completion, and child-authored bytes before an attested record is emitted. A future trusted host verifier must be independently implemented and tested before any surface can issue `HOST_VERIFIED`.
