# ai-agent-workflow

Portable, Issue-first development workflow for OpenAI/Codex, Claude Code, and Google Antigravity 2.0. It provides nine progressive-disclosure Skills, shared standards, application profiles, and a deterministic local Python CLI. It does not generate application source or synchronize projects.

## Quick start

Use the generated package for your host. The repository includes OpenAI and Claude Code Git marketplaces for local discovery. Antigravity can load `dist/antigravity` as a plugin. Product-specific CLI/IDE smoke tests require the corresponding product to be installed.

For a consumer repository, install the runtime from the generated package (or install this checkout with `python -m pip install -e .` during development), then run `python -m agent_workflow init-project` and inspect `.agent/project.json`. Profile selection is explicit: the runtime never infers application type from a stack or repository contents. Start with the [requirements Skill](workflow/skills/requirements/SKILL.md) and [specification standard](workflow/standards/specification.md).

## Development

Python 3.10+ is required; runtime code uses the standard library. Install the local CLI for development with `python -m pip install -e .`. Build generated packages and validate them with:

```sh
python -m compileall runtime tools tests
python -m unittest discover -s tests -p "test_*.py"
python tools/build_dist.py
python tools/build_dist.py --check
python tools/validate_dist.py
git diff --check
```

GitHub operations use authenticated `gh api` through `agent_workflow.github`; unit tests use fakes and never require live credentials. The generated trees under `dist/` are not edited by hand.

## External formats

- [OpenAI Agent Plugins](https://developers.openai.com/plugins/build/plugins) and [Skills](https://developers.openai.com/plugins/build/skills)
- [Claude Code plugins](https://platform.claude.com/docs/en/manage-claude/plugins-api), [marketplaces](https://code.claude.com/docs/en/plugins/create-marketplace), and [Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Antigravity plugins](https://www.antigravity.google/docs/plugins)
