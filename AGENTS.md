# P-ASES repository guidance

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
