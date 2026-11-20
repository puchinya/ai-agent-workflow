# P-ASES repository guidance

## Mandatory Issue-neutral architecture

- Implement P-ASES features for every eligible Issue/PR, not for one numbered ticket. In generic runtime, authorization, Phase, Binding, adoption, Verification, Acceptance, recovery, and delivery paths, **never branch on literal Issue/PR numbers**, issue-specific branch names, or fixed state paths. Do not disguise single-ticket logic behind a one-entry mapping or feature flag.
- Treat Issue/PR numbers as **validated subject data**, not dispatch keys. Resolve behavior from typed schema/version, verified repository and owner identity, active ADC, Issue/PR readback, execution epoch/PRBinding, exact HEAD, signed operation plan, and owner decision.
- Preserve separately approved **immutable historical migration** readers and in-flight writers only within their exact previously authorized scope (for example Issue #63/PR #64 execution adoption V1). Keep their compatibility adapter isolated; never copy, widen, or infer new authorization from the old records.
- Before implementing a special case, return to the specification/design/ADC with a generic design and a documented historical compatibility boundary. If the contract conflicts, report the precise conflict rather than silently add an Issue-specific branch.
- In implementation self-review and independent review, inspect changed control-flow literals/maps for disguised Issue/PR exceptions. Require same-behavior tests for at least two distinct valid Issue/PR pairs plus cross-subject rejection tests. See `workflow/standards/technical-design.md` and `workflow/standards/design.md`.

- Issue #32 migration guidance: its latest approved ADC and named implementation contract governed work for that Issue; preserve the GitHub repository slug `puchinya/ai-agent-workflow`. This is historical scope and does not constrain later Issues or PRs.
- Canonical authored inputs are `workflow/skills/`, `workflow/standards/`, `workflow/templates/`, `runtime/p_ases/`, `adapters/`, and `docs/`.
- The only public Python package is `p_ases`; use `python -m p_ases <namespace> <verb> [args]`. Do not add legacy `agent_workflow` APIs or command aliases.
- Keep GitHub API access in `runtime/p_ases/github.py` and Git subprocess access in `runtime/p_ases/git.py`.
- Generate `dist/**` and root marketplace JSON only with `python tools/build_dist.py`. Never hand-edit generated outputs.
- Keep the three host packages independent and preserve exact-subject ADC, work-binding, Verification, Acceptance, and delivery checks.
- Implementation and review alone do not authorize PR merges, releases, tag pushes, parent activation, or closing Issue #26.
- A PR may be merged by an authorized agent only after the repository owner explicitly authorizes merging that specific PR at its current HEAD and all applicable GitHub merge requirements are satisfied.
- Releases, tag pushes, parent activation, and closing Issue #26 each require separate explicit authorization.
- Passing CI or receiving a code-review PASS is not merge authorization.
