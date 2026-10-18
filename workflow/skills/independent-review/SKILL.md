---
name: independent-review
description: Review an exact PR subject in a separate context and record evidence-backed findings.
---
# Independent review

## Owner and inputs

Owner: the active host owns subagent lifecycle and provenance; `runtime/p_ases/audits.py` validates and records the existing review artifact. Inputs are the exact approved ADC/Contract, Issue/PR identity, HEAD, complete diff, every checklist item, test evidence, implementation binding ID, and host-reported spawn/session and reviewer IDs.

## Workflow

1. The host must spawn and join a dedicated fresh native subagent, isolated from the implementation context. If native delegation or host-reported identity cannot be verified, stop with `INDEPENDENT_SUBAGENT_UNAVAILABLE`. Do not use a same-agent second prompt, a human fallback, or User Review as a substitute.
2. The child reads back the exact repository, Issue, PR, current HEAD, approved ADC/Contract, complete source diff, complete contract, checklist, test evidence, and the host-provided implementation binding ID and spawn/session metadata.
3. The child itself inspects every contract section and checklist item, classifies findings with severity and evidence, and authors the raw result. The parent MUST NOT edit or rewrite the child findings, verdict, or context IDs. Distinct context IDs alone do not prove host authenticity.
4. The parent may pass the unedited child result to the existing `audit independent` CLI for exact-subject/digest/ID validation. Do not add a spawn API to the Python CLI or invoke another coding-agent executable from it. If the existing artifact schema cannot capture a required host provenance field, report that precise limitation rather than inventing a value.
5. A/B findings, blocking C findings, checklist failures, stale HEAD, or an unknown spawn/join outcome block. After a fix produces a new HEAD, the host starts a new child review; do not repeat on the same HEAD without progress. D findings remain non-blocking.
6. After child PASS, inspect current Phase, Binding, Verification, Acceptance, Self-Audit, and Required CI. Only if all are current and PASS run `delivery readiness`; if it passes, start `user-review start` automatically without extra confirmation to start. Never fabricate the user's final User Review decision.
7. Preserve ordinary product review gates. Issue #32's fixed Bootstrap waiver only waives review procedure for that PR.

## CLI

~~~sh
python -m p_ases audit independent 32 42 HEAD40 path/to/plan.json path/to/independent-review.json --repo OWNER/REPO --root .
~~~

## Failure handling and output

Missing/unavailable native subagent, missing host-reported spawn/session or reviewer identity, same-context review, mismatched PR/HEAD/ADC, unresolved blocking finding, failed checklist, or unknown spawn/join outcome remains non-passing. Report the exact host capability and evidence without fabricating independent review, readiness, or user approval.

Next owners: user-review receives human feedback; delivery-control checks exact readiness. See the [review design](../../../docs/design/workflow-design.md).
