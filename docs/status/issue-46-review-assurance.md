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
- `INDEPENDENT_ATTESTED`: the runtime validates the internal byte bundle, but the current adapters accept caller-supplied bytes and do not capture a host-native invocation. Readiness therefore reports the effective assurance as `UNAVAILABLE` and blocks it, even when the profile explicitly selects `independent_attested`.
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

No host or OS integration is reported as verified by unit tests. The current package has no verifiable host-capture boundary; locally supplied, self-consistent request/terminal/output JSON is not accepted as evidence that a child actually ran. Until a surface-specific native capture integration exists, `INDEPENDENT_ATTESTED` has effective assurance `UNAVAILABLE` and cannot satisfy Readiness. A future trusted host verifier must be independently implemented and tested before any surface can issue `HOST_VERIFIED`.
