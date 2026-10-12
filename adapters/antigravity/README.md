# Google Antigravity plugin package

This generated P-ASES package has an Antigravity-specific root `plugin.json` and the canonical 16 host-neutral Skills under `skills/`. The plugin slug is `p-ases`. Third-party GitHub marketplace support has not been confirmed, so install locally from `dist/antigravity` or use the versioned Antigravity Release ZIP with `SHA256SUMS`. Load the package with an Antigravity 2.0 CLI or IDE installation to run a product smoke test.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/antigravity`, then run `python -m p_ases --help`. `python -m p_ases project status` reads an existing profile without initializing or changing it. The source of truth is `workflow/`, `runtime/p_ases/`, and this adapter. Run `python tools/build_dist.py` after editing canonical files.

Host-managed worktree support in Antigravity is unverified. With `workspace.isolation=auto`, the `work-execution` Skill uses the current-checkout flow; `required` blocks before source edits when no verified native isolation capability is available.
