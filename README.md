# ai-agent-workflow

Portable, Issue-first development workflow for OpenAI/Codex, Claude Code, and Google Antigravity 2.0. It provides nine progressive-disclosure Skills, shared standards, application profiles, and a deterministic local Python CLI. It does not generate application source or synchronize projects.

## Quick start

Use the generated package for your host. The repository includes OpenAI and Claude Code Git marketplaces for local discovery. Antigravity can load `dist/antigravity` as a plugin. Product-specific CLI/IDE smoke tests require the corresponding product to be installed.

For a consumer repository, install the runtime from the generated package (or install this checkout with `python -m pip install -e .` during development), then run `python -m agent_workflow init-project` and inspect `.agent/project.json`. Profile selection is explicit: the runtime never infers application type from a stack or repository contents. Start with the [requirements Skill](workflow/skills/requirements/SKILL.md) and [specification standard](workflow/standards/specification.md).

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

GitHub operations use authenticated `gh api` through `agent_workflow.github`; unit tests use fakes and never require live credentials. The generated trees under `dist/` are not edited by hand.

## Releases

Bump only `runtime/agent_workflow/__init__.py::__version__` in a normal Issue/PR, regenerate with `python tools/build_dist.py`, and run the development verification above before merging. Setuptools and generated OpenAI/Claude manifests use that canonical version; Antigravity stays versionless. After merge, push the matching stable SemVer tag `vX.Y.Z` on a commit contained in `main`. Actions checks tag/version/main ancestry, runs the four-platform CI matrix, and publishes a GitHub Release using `GITHUB_TOKEN`.

The Release assets are `ai-agent-workflow-openai-vX.Y.Z.zip`, `ai-agent-workflow-claude-vX.Y.Z.zip`, `ai-agent-workflow-antigravity-vX.Y.Z.zip`, and `SHA256SUMS`. Each archive contains its host package at root, including Claude's `.claude-plugin/plugin.json`. Same-tag reruns replace the expected assets. Local packaging checks drift and host validation without regenerating:

```sh
python tools/package_release.py --tag vX.Y.Z --output-dir /path/to/temporary/release-assets
```

Replace `X.Y.Z` with the canonical version. Release publication does not bump versions or push source/tags. OpenAI public Plugins Directory submission, Claude Enterprise Plugins API publication, other provider publication, and PyPI are outside this workflow. See the [distribution specification](docs/specs/distribution-spec.md) and [design](docs/design/distribution-design.md).

## External formats

- [OpenAI Agent Plugins](https://developers.openai.com/plugins/build/plugins) and [Skills](https://developers.openai.com/plugins/build/skills)
- [Claude Code plugins](https://platform.claude.com/docs/en/manage-claude/plugins-api), [marketplaces](https://code.claude.com/docs/en/plugins/create-marketplace), and [Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Antigravity plugins](https://www.antigravity.google/docs/plugins)
