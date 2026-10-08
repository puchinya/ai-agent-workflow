# Claude Code plugin package

The plugin manifest is `.claude-plugin/plugin.json`; Skills live in `skills/`. Register `https://github.com/puchinya/ai-agent-workflow` as a Claude Code plugin marketplace, then install `ai-agent-workflow`. The generated repository-root `.claude-plugin/marketplace.json` points to `./dist/claude` inside the marketplace checkout. Refresh the marketplace in Claude Code after repository updates. Validate with `claude plugin validate ./dist/claude` when Claude Code is installed.

Marketplace installation reads the GitHub repository snapshot and does not download a Release asset. Use the versioned Claude Release ZIP and `SHA256SUMS` for a pinned or offline manual install.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/claude`, then run `python -m agent_workflow init-project`. The source of truth is `workflow/`, `runtime/`, and this adapter. Run `python tools/build_dist.py` after editing canonical files.

When executing an approved Contract, resolve the selected base ref and SHA before requesting isolation. Claude Code reuses an existing bound worktree or uses native in-session `EnterWorktree` only when the current surface can preserve that exact selected base; verify the initial HEAD before binding. For a stacked/non-default base the surface cannot select or guarantee, `auto` falls back to the current-checkout flow and `required` blocks before edits. Do not create a worktree from the wrong base and repair it. Claude owns worktree resume and cleanup. The plugin does not invoke the Claude Code binary or create raw sibling worktrees. Product behavior has not been smoke-tested by this repository workflow.

### Worktree ignore configuration

Claude Code’s default worktree location is `<repo>/.claude/worktrees/<name>/`. The consumer project owner should add `.claude/worktrees/` to that repository’s root `.gitignore` to keep the default nested worktree contents out of the main checkout’s untracked-file status. The owner maintains this rule; the plugin does not edit consumer ignore files.

To inspect the default path’s matching ignore rule from the main checkout, the owner can run this read-only diagnostic:

```sh
git check-ignore -v --no-index .claude/worktrees/probe
```

An ignored result identifies the matching source and pattern. No matching result requires owner review. This command makes no file changes, and `probe` does not need to exist. It is guidance, not a mandatory plugin command or workflow gate. See the [Git `check-ignore` documentation](https://git-scm.com/docs/git-check-ignore).

If the host uses a custom worktree destination, ignore only its actual relative directory when it is inside the repository. No `.gitignore` rule in this checkout is needed for a destination outside it. `WorktreeCreate` hooks can replace the default destination, so the plugin does not inspect the effective host path or infer it from project configuration. Claude Code retains ownership of worktree creation, resume, and cleanup.

`.gitignore` and optional `.worktreeinclude` have different purposes. `.worktreeinclude` is project-owned, opt-in configuration for explicitly copying selected ignored files into a new worktree; it does not replace `.gitignore`. The plugin does not create or populate `.worktreeinclude`, copy ignored resources, or create worktrees itself. For host behavior and configuration details, see the [official Claude Code worktree documentation](https://code.claude.com/docs/en/worktrees).
