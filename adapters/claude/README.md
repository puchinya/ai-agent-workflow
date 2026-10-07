# Claude Code plugin package

The plugin manifest is `.claude-plugin/plugin.json`; Skills live in `skills/`. Register `https://github.com/puchinya/ai-agent-workflow` as a Claude Code plugin marketplace, then install `ai-agent-workflow`. The generated repository-root `.claude-plugin/marketplace.json` points to `./dist/claude` inside the marketplace checkout. Refresh the marketplace in Claude Code after repository updates. Validate with `claude plugin validate ./dist/claude` when Claude Code is installed.

Marketplace installation reads the GitHub repository snapshot and does not download a Release asset. Use the versioned Claude Release ZIP and `SHA256SUMS` for a pinned or offline manual install.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/claude`, then run `python -m agent_workflow init-project`. The source of truth is `workflow/`, `runtime/`, and this adapter. Run `python tools/build_dist.py` after editing canonical files.

When executing an approved Contract, Claude Code reuses an existing isolated worktree or uses native in-session `EnterWorktree` before edits. Claude owns worktree resume and cleanup. The plugin does not invoke the Claude Code binary or create raw sibling worktrees.
