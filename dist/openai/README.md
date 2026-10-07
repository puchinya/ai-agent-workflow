# OpenAI Agent Plugins package

This generated package contains portable Agent Plugins metadata at `plugin.json`, host-neutral Skills under `skills/`, shared standards/templates, and the local `agent_workflow` runtime. Register `https://github.com/puchinya/ai-agent-workflow` as a marketplace in Codex, then install `ai-agent-workflow`. The generated `.agents/plugins/marketplace.json` entry uses `./dist/openai`, resolved inside the marketplace checkout. Refresh the marketplace in Codex after repository updates.

Marketplace installation reads the GitHub repository snapshot; it does not download a Release asset. Use the versioned OpenAI Release ZIP and `SHA256SUMS` when you need a pinned or offline manual install.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/openai`, then run `python -m agent_workflow init-project`. The source of truth is `workflow/`, `runtime/`, and this adapter. Run `python tools/build_dist.py` from the repository root after editing canonical files.

For Implementation Contract execution, Codex's native managed worktree or task-fork capability is preferred when the current surface exposes it. This plugin does not create sibling worktrees or shell out to another Codex process; `workspace.isolation=auto` falls back to the current checkout when native isolation is unavailable, while `required` blocks before edits.
