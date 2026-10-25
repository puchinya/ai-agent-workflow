# Claude Code plugin package

The plugin manifest is `.claude-plugin/plugin.json`; the canonical 16 Skills live in `skills/`. Register `https://github.com/puchinya/ai-agent-workflow` as a Claude Code plugin marketplace, then install `p-ases`. The generated repository-root `.claude-plugin/marketplace.json` points to `./dist/claude` inside the marketplace checkout. Refresh the marketplace in Claude Code after repository updates. Validate with `claude plugin validate ./dist/claude` when Claude Code is installed.

Marketplace installation reads the GitHub repository snapshot and does not download a Release asset. Use the versioned Claude Release ZIP and `SHA256SUMS` for a pinned or offline manual install.

Independent Review V2 requires exact native task request, successful terminal result, and child-authored output. This package does not read Claude Code internals or claim that agent-writable Hook files are trusted host provenance. No live Claude native-result adapter or trusted host-event verifier is configured; Claude smoke status is `NOT RUN`. The profile default remains `host_verified`; opt into `independent_attested` only through committed project configuration when operator-captured evidence is an accepted minimum.

The Issue #46 / PR #67 successor ADC defines a repository-specific, owner-authorized continuation for positively observed missing native-capture integration. It retains `review_assurance=UNAVAILABLE` and the risk that no independent review was performed. It does not turn the missing result into a PASS or waive Verification, Acceptance, Self-Audit, Required CI, dependencies, human User Review, or explicit merge authorization. Agent-writable Claude Hook records remain untrusted. This opt-in is not available to other projects by default.

The runtime exposes `delivery review-unavailable-plan` and `delivery review-unavailable-apply` for that exact Issue/PR only. The plan prints a canonical Owner approval comment; the Owner posts it personally, then Apply verifies the Owner's stable GitHub ID and exact comment before publishing a separate exception receipt. Readiness V2 and Final Delivery V2 remain visibly degraded and do not authorize merging. A saved exception is invalidated by changes to the approved ADC, Plan, PR/base/HEAD, bindings, profile, or host capability observation. Claude Hooks never establish capture availability or Owner identity.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/claude`, then run `python -m p_ases --help`. `python -m p_ases project status` reads an existing profile without initializing or changing it. The source of truth is `workflow/`, `runtime/p_ases/`, and this adapter. Run `python tools/build_dist.py` after editing canonical files.

For approved ADC work, the `work-execution` Skill resolves the selected base ref and SHA before requesting isolation. Claude Code reuses an existing bound worktree or uses native in-session `EnterWorktree` only when the current surface can preserve that exact selected base; verify the initial HEAD before binding. For a stacked/non-default base the surface cannot select or guarantee, `auto` falls back to the current-checkout flow and `required` blocks before edits. Do not create a worktree from the wrong base and repair it. Claude owns worktree resume and cleanup. The plugin does not invoke the Claude Code binary or create raw sibling worktrees. Product behavior has not been smoke-tested by this repository workflow.

### Worktree ignore configuration

Claude Code’s default worktree location is `<repo>/.claude/worktrees/<name>/`. The consumer project owner should add `.claude/worktrees/` to that repository’s root `.gitignore` to keep the default nested worktree contents out of the main checkout’s untracked-file status. The owner maintains this rule; the plugin does not edit consumer ignore files.

To inspect the default path’s matching ignore rule from the main checkout, the owner can run this read-only diagnostic:

```sh
git check-ignore -v --no-index .claude/worktrees/probe
```

An ignored result identifies the matching source and pattern. No matching result requires owner review. This command makes no file changes, and `probe` does not need to exist. It is guidance, not a mandatory plugin command or workflow gate. See the [Git `check-ignore` documentation](https://git-scm.com/docs/git-check-ignore).

If the host uses a custom worktree destination, ignore only its actual relative directory when it is inside the repository. No `.gitignore` rule in this checkout is needed for a destination outside it. `WorktreeCreate` hooks can replace the default destination, so the plugin does not inspect the effective host path or infer it from project configuration. Claude Code retains ownership of worktree creation, resume, and cleanup.

`.gitignore` and optional `.worktreeinclude` have different purposes. `.worktreeinclude` is project-owned, opt-in configuration for explicitly copying selected ignored files into a new worktree; it does not replace `.gitignore`. The plugin does not create or populate `.worktreeinclude`, copy ignored resources, or create worktrees itself. For host behavior and configuration details, see the [official Claude Code worktree documentation](https://code.claude.com/docs/en/worktrees).
