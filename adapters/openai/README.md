# OpenAI Agent Plugins package

This generated package contains portable Agent Plugins metadata at `plugin.json`, host-neutral Skills under `skills/`, shared standards/templates, and the local `agent_workflow` runtime. Repo marketplace metadata lives at `.agents/plugins/marketplace.json` and points to `./dist/openai`.

To use the CLI from a consumer checkout, install this directory with `python -m pip install /path/to/dist/openai`, then run `python -m agent_workflow init-project`. The source of truth is `workflow/`, `runtime/`, and this adapter. Run `python tools/build_dist.py` from the repository root after editing canonical files.
