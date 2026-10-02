# Claude Code plugin package

The plugin manifest is `.claude-plugin/plugin.json`; Skills live in `skills/`. Repository marketplace metadata is generated at the repository-root `.claude-plugin/marketplace.json` and points to `./dist/claude`. Validate with `claude plugin validate ./dist/claude` when Claude Code is installed.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/claude`, then run `python -m agent_workflow init-project`. The source of truth is `workflow/`, `runtime/`, and this adapter. Run `python tools/build_dist.py` after editing canonical files.
