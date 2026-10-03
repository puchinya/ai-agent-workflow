# Google Antigravity plugin package

This generated package has an Antigravity-specific root `plugin.json` and host-neutral Skills under `skills/`. Third-party GitHub marketplace support has not been confirmed, so install locally from `dist/antigravity` or use the versioned Antigravity Release ZIP with `SHA256SUMS`. Load the package with an Antigravity 2.0 CLI or IDE installation to run a product smoke test.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/antigravity`, then run `python -m agent_workflow init-project`. The source of truth is `workflow/`, `runtime/`, and this adapter. Run `python tools/build_dist.py` after editing canonical files.
