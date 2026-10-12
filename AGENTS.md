# P-ASES repository guidance

- For Issue #32, follow its latest approved ADC and the implementation contract that names it. Preserve the GitHub repository slug `puchinya/ai-agent-workflow`.
- Canonical authored inputs are `workflow/skills/`, `workflow/standards/`, `workflow/templates/`, `runtime/p_ases/`, `adapters/`, and `docs/`.
- The only public Python package is `p_ases`; use `python -m p_ases <namespace> <verb> [args]`. Do not add legacy `agent_workflow` APIs or command aliases.
- Keep GitHub API access in `runtime/p_ases/github.py` and Git subprocess access in `runtime/p_ases/git.py`.
- Generate `dist/**` and root marketplace JSON only with `python tools/build_dist.py`. Never hand-edit generated outputs.
- Keep the three host packages independent and preserve exact-subject ADC, work-binding, Verification, Acceptance, and delivery checks.
- Do not merge PRs, publish releases, push tags, activate the parent, or close Issue #26 under this contract.
