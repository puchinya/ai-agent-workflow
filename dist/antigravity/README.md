# Google Antigravity plugin package

This generated package has an Antigravity-specific root `plugin.json` and host-neutral Skills under `skills/`. Load `dist/antigravity` with an Antigravity 2.0 CLI or IDE installation to run a product smoke test.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/antigravity`, then run `python -m agent_workflow init-project`. The source of truth is `workflow/`, `runtime/`, and this adapter. Run `python tools/build_dist.py` after editing canonical files.
