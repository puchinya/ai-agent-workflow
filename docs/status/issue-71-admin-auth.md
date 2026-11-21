# Issue #71 Admin authentication status

Updated: 2026-11-14

<!-- contents:start -->
**Contents**
- [1 Current implementation boundary](#1-current-implementation-boundary)
- [2 Readback evidence and blocker](#2-readback-evidence-and-blocker)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
<!-- heading-map:end -->


<a id="current-implementation-boundary"></a>
## 1 Current implementation boundary

Issue #71 uses only `isolated-gh-device` for Admin requests. Each session creates a fresh mode-0700 `GH_CONFIG_DIR`, removes `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`, and `GITHUB_ENTERPRISE_TOKEN` from the `gh` login/API child environment, verifies the authenticated human owner identity, and keeps the client usable only inside that verified device session. PAT, GitHub App, Network-secret, SDK, ordinary-credential, and other API fallbacks are disabled.

Live Admin and Activation V2 entrypoints share an interactive host-control guard. It rejects known Cloud, hosted, CI, SSH, and remote markers; requires an interactive local terminal and an explicit owner confirmation; and requires the active isolated device-auth client. The confirmation is an operational trust assumption, not cryptographic host attestation. Local Codex, local Claude Code, and owner-controlled local VMs use identical checks.

Ruleset planning reads the authenticated user, collaborator permission, repository Admin permission, repository Rulesets, default branch, legacy protection, effective rules, Ruleset details, and open-PR impact. A failed, malformed, incomplete, or unauthorized source blocks planning. Legacy protection `404` is treated as `NOT_CONFIGURED` only when the complete remaining policy read succeeds. Ruleset apply performs a fresh Admin and policy read before any Ruleset mutation.

<a id="readback-evidence-and-blocker"></a>
## 2 Readback evidence and blocker

The 2026-11-13 handoff records a later read through the existing Device-login route that GitHub evaluated as an integration credential: `GET /repos/puchinya/ai-agent-workflow/branches/main/protection` returned HTTP 403, `X-Accepted-GitHub-Permissions: administration=read`, empty `X-Oauth-Scopes`, and `Resource not accessible by integration`. The same response was observed inside and outside the Codex sandbox. The handoff could verify owner User ID `3744776`, repository ID `1401910271`, and Admin permissions, but it could not confirm where the Device login identity became the effective integration credential.

An earlier Issue narrative reports a successful `NOT_CONFIGURED` readback. That older observation does not resolve the later 403 and is not evidence of current policy state. The current execution channel has no interactive TTY; the local guard cannot obtain an owner-controlled terminal confirmation here, so no new complete policy readback was performed during this implementation pass.

No Ruleset, Setup PR, Activation, or Issue #63 write was performed. Do not interpret the 403, an empty Rulesets response, or the older `NOT_CONFIGURED` observation as proof that all branch protection is absent. The implementation target remains `IMPLEMENTATION_READY / ACTIVATION_DELIVERY_BLOCKED` until an owner-controlled local device session completes the full current Admin policy readback.
