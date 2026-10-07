# ai-agent-workflow

Portable, Issue-first development workflow for OpenAI/Codex, Claude Code, and Google Antigravity 2.0. It provides ten progressive-disclosure Skills, shared standards, application profiles, and a deterministic local Python CLI. It does not generate application source or synchronize projects.

## Quick start

Use the generated package for your host. This GitHub repository hosts the OpenAI/Codex and Claude Code marketplaces; register the repository with the host and install `ai-agent-workflow` from its marketplace. Antigravity remains a local/manual plugin install. Product-specific CLI/IDE smoke tests require the corresponding product to be installed.

For a consumer repository, install the runtime from the generated package (or install this checkout with `python -m pip install -e .` during development), then run `python -m agent_workflow init-project` and inspect `.agent/project.json`. Profile selection is explicit: the runtime never infers application type from a stack or repository contents. New profiles use milestone mode `auto`, so versionless repositories proceed without a milestone; choose `required` or `disabled` explicitly when appropriate. Start with the [requirements Skill](workflow/skills/requirements/SKILL.md) and [specification standard](workflow/standards/specification.md).

After an open Issue exists, `python -m agent_workflow ensure-milestone <issue> [--target-version <version>]` reuses or creates its exact-title milestone. Pass `--target-version` only when the Issue's approved requirements/contract explicitly name the intended release; Skills must not infer it. The explicit target is preserved unchanged and bypasses the profile version source. Without it, the profile source remains the fallback; `disabled` mode always skips, `auto` accepts unresolved fallback as `NOT_APPLICABLE`, and `required` fails when fallback is unresolved. The command never moves an Issue from a different Milestone. Before editing, `python -m agent_workflow start-feature-branch <issue> <description...>` validates the Issue and starts the configured feature branch from GitHub's default branch. For stacked work, pass `--base-ref <remote-branch>` and optionally `--expected-base-sha <40-character-sha>`; only same-repository remote branches are accepted, and the expected SHA is checked before a switch, cleanup, or hook. Existing targets remain in place and are never rebased. Branch switches can remove configured `cleanup_on_switch` paths and then run global `branch_switch` hooks; retries on the current target branch skip that work.

New durable Issues record Specification, Design, and Status choices under `## Document impact`; use matching `docs/specs/`, `docs/design/`, and `docs/status/` links, or a reason for `unchanged` and `evidence-only` decisions. Requirements/design establish the choices, implementation checks them against the final diff, and self-review verifies the final match.

Approval of an Issue-scoped Implementation Contract authorizes routine execution through a review-ready PR, including commit, non-force push, PR creation or reuse, the `phase:review` transition, and current-HEAD evidence publication. The sequence is `verify_quick` -> commit/PR -> `verify-final` -> self-review -> QA -> fresh-context independent PR review -> `delivery-check`. The implementation session must not author the independent review; if a fresh reviewer is unavailable, report the blocker and PR URL. Run `python -m agent_workflow ensure-review-pr <issue> --body-file <path>` to push the current clean Issue branch and create or reuse its non-draft PR. The body file must contain an own-line `Closes #N` plus non-empty `## Verification` and `## Untested` sections. Pass `--base-ref` with the exact branch returned by `start-feature-branch` for stacked work. Pending evidence or Required Checks leave the PR open and block completion; merge, release, destructive Git operations, and material contract changes remain outside this authorization.

`python -m agent_workflow validate-docs` without a selector keeps the full repository scan. Use mutually exclusive `--issue <number>` to validate only declared existing owners or `--changed <base>` to validate changed `docs/**/*.md` paths from `<base>...HEAD`; deletions are ignored, and invalid scope fails closed. Hook output remains suppressed by default. `python -m agent_workflow run-hook <hook> --diagnostic` prints no child output on success and only a credential-redacted failure tail of at most 16 KiB combined. Contract pointers must use the exact three-field format managed by `publish-implementation-contract`; do not hand-edit them. Saving/publishing safely canonicalizes recognizable legacy Reviewer Checklist formatting, preserves checklist wording and the rest of the contract, and hashes the normalized bytes. Ambiguous prose fails before GitHub mutation. Publish approved changes with `--supersede`.

Schema-v2 self-review binds the complete approved contract comment ID/SHA and each non-checklist section to the exact PR HEAD, alongside the separate Reviewer Checklist summary. Existing v1 reviews are diagnostic-only and must be republished before handoff. Contract-section `fail` or `untested` blocks delivery; checklist `fail` blocks, while checklist `untested` remains non-blocking by itself.

`verify-final` requires a clean worktree and local HEAD identical to PR HEAD. Its immutable receipt stores command hashes and execution identities, never raw commands or output; skipped and empty plans are visible but do not pass. QA records required test cases or a concrete N/A reason and passes only when all cases pass or N/A applies. Independent review binds the same HEAD, contract units, and checklist, requires a `fresh_context: true` reviewer attestation, and blocks for any non-passing contract unit, checklist failure, or blocking A/B/C finding. Runtime checks the attestation but cannot prove reviewer provenance. Delivery evaluates Final Verification, self-review, QA, and Independent Review before Required Checks.

## Development

Python 3.10+ is required; runtime code uses the standard library. Install the local CLI for development with `python -m pip install -e .`. Build generated packages and validate them with:

```sh
python -m compileall runtime tools tests
python tools/build_dist.py --check
python -m unittest discover -s tests -p "test_*.py"
python tools/build_dist.py
python tools/build_dist.py --check
python tools/validate_dist.py
git diff --exit-code -- dist .agents/plugins/marketplace.json .claude-plugin/marketplace.json
git diff --check
```

GitHub operations use authenticated `gh api` through `agent_workflow.github`; Git lifecycle operations use argv-only subprocess calls in `agent_workflow.git`. Unit tests use fakes and local temporary repositories without live credentials. The generated trees under `dist/` are not edited by hand.

## GitHub marketplaces

Register `https://github.com/puchinya/ai-agent-workflow` as a plugin marketplace in Codex or Claude Code, then install `ai-agent-workflow`. The OpenAI marketplace resolves `./dist/openai`; the Claude marketplace resolves `./dist/claude` from the repository checkout. After new commits are available, use the host's marketplace refresh action to update the checkout and discover the new package contents. Installation reads the repository marketplace snapshot and does not use GitHub Release assets.

For a pinned or offline manual install, use a versioned GitHub Release ZIP and verify it with `SHA256SUMS`. Antigravity remains a local/manual install from `dist/antigravity` or its Release ZIP; third-party GitHub marketplace support has not been confirmed.

## Releases

Bump only `runtime/agent_workflow/__init__.py::__version__` in a normal Issue/PR, regenerate with `python tools/build_dist.py`, and run the development verification above before merging. Setuptools and generated OpenAI/Claude manifests use that canonical version; Antigravity stays versionless. After merge, push the matching stable SemVer tag `vX.Y.Z` on a commit contained in `main`. Actions checks tag/version/main ancestry, runs the four-platform CI matrix, and publishes a GitHub Release using `GITHUB_TOKEN`.

The Release assets are `ai-agent-workflow-openai-vX.Y.Z.zip`, `ai-agent-workflow-claude-vX.Y.Z.zip`, `ai-agent-workflow-antigravity-vX.Y.Z.zip`, and `SHA256SUMS`. Each archive contains its host package at root, including Claude's `.claude-plugin/plugin.json`. These are version-fixed manual/offline downloads; marketplace installation uses the repository checkout. Same-tag reruns replace the expected assets. Local packaging checks drift and host validation without regenerating:

```sh
python tools/package_release.py --tag vX.Y.Z --output-dir /path/to/temporary/release-assets
```

Replace `X.Y.Z` with the canonical version. Release publication does not bump versions or push source/tags. OpenAI public Plugins Directory submission, Claude Enterprise Plugins API publication, other provider publication, and PyPI are outside this workflow. See the [distribution specification](docs/specs/distribution-spec.md) and [design](docs/design/distribution-design.md).

## External formats

- [OpenAI Agent Plugins](https://developers.openai.com/plugins/build/plugins) and [Skills](https://developers.openai.com/plugins/build/skills)
- [Claude Code plugins](https://platform.claude.com/docs/en/manage-claude/plugins-api), [marketplaces](https://code.claude.com/docs/en/plugins/create-marketplace), and [Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Antigravity plugins](https://www.antigravity.google/docs/plugins)
