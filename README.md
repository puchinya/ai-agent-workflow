# Puchinya Agentic Software Engineering System (P-ASES)

P-ASES provides 16 host-neutral Skills, shared workflow standards, templates, and a one-shot Python CLI for contract-driven software engineering. The GitHub repository remains [`puchinya/ai-agent-workflow`](https://github.com/puchinya/ai-agent-workflow); the product, plugin, and distribution name is `p-ases`.

## Install and inspect

Install the runtime from a host package or from this checkout for development:

```sh
python -m pip install -e .
python -m p_ases --help
python -m p_ases project status --root .
```

`project status` reads the existing `.agent/project.json` profile. It does not initialize or modify a project. `context show` reads an open Issue, its exact approved ADC pointer and bytes, and any existing frozen work binding:

```sh
python -m p_ases context show 32 --root . --repo puchinya/ai-agent-workflow
```

An unavailable profile, missing or closed Issue, unverified ADC, or absent/stale binding is reported as a non-success state. These read-only commands do not create Issues, resolve a new base, switch branches, or create a worktree.

## Public CLI

The CLI is `python -m p_ases <namespace> <verb> [args]` with exactly these namespaces:

| Namespace | Public verbs |
| --- | --- |
| `project` | `status` |
| `context` | `show` |
| `adc` | `validate`, `publish`, `verify`, `restore` |
| `issue` | `validate-split`, `split`, `advance`, `integration-check` |
| `docs` | `validate`, `format` |
| `work` | `base`, `branch`, `bind`, `recover` |
| `pr` | `ensure` |
| `verification` | `plan`, `collect`, `validate`, `final`, `published` |
| `acceptance` | `prepare`, `validate`, `publish`, `verify` |
| `audit` | `self`, `independent` |
| `user-review` | `start`, `sync`, `record`, `status` |
| `delivery` | `readiness`, `gate-policy`, `bootstrap-check`, `final`, `finalize`, `parent`, `parent-evidence`, `parent-migrate-labels` |

Command help and JSON results describe the accepted arguments and typed outcomes. Failures remain nonzero and fail closed. `delivery bootstrap-check` is the separate fixed-cohort Bootstrap evaluator. Parent evidence is reconstructed from GitHub Actions API Run/Job/Step/Check Run data; comments are mutable pointers, not success authority.

GitHub API access is confined to `runtime/p_ases/github.py`; Git subprocesses are confined to `runtime/p_ases/git.py`. The runtime is standard-library based and single-shot. It does not run a daemon, cross-import host runtimes, log secrets, infer missing bindings, or merge/release on a user's behalf.

## Canonical Skills

The repository publishes exactly these Skills from `workflow/skills/<id>/SKILL.md`:

`request-intake`, `adc-authoring`, `adc-registry`, `issue-decomposition`, `product-specification`, `technical-design`, `test-specification`, `work-execution`, `verification-evidence`, `acceptance-validation`, `contract-audit`, `independent-review`, `user-review`, `integration-validation`, `delivery-control`, and `work-checkpoint`.

Each host package contains its own manifest, complete `runtime/p_ases`, the same 16 Skills, standards, templates, specifications, designs, license, and host README. OpenAI and Claude marketplaces use their local relative package paths. Antigravity remains a local/manual install while third-party marketplace support is unconfirmed. No placeholder agents, rules, hooks, or MCP servers are generated.

## Development and distribution

The manually authored version is `runtime/p_ases/__init__.py::__version__`, currently `0.8.0`. Setuptools packages only `p_ases`. Generated OpenAI and Claude manifests use that version; Antigravity remains versionless.

Generate distributions only from canonical sources:

```sh
python tools/build_dist.py
python tools/build_dist.py --check
python tools/validate_dist.py
```

The builder computes the full expected set before writing. Its `--check` mode is read-only and detects missing, extra, or edited outputs. Repeated generation is deterministic and removes stale files only under generator-owned paths.

## Verification

Run the full supported verification set from a clean feature checkout:

```sh
python -m pip install -e .
python -m compileall runtime tools tests
python -m unittest discover -s tests -p 'test_*.py'
python -m p_ases --help
python -m p_ases docs validate --root .
python -m p_ases docs format --check --root .
python tools/validate_pases_traceability.py specification
python tools/validate_pases_traceability.py design
python tools/validate_pases_traceability.py test-oracle
python tools/build_dist.py
python tools/build_dist.py --check
python tools/validate_dist.py
python tools/validate_parent_acceptance.py 16-skills-package
python tools/package_release.py --tag v0.8.0 --output-dir /tmp/pases32-release-dryrun
python tools/build_dist.py --check
git diff --check
```

CI retains Ubuntu Python 3.10 and 3.14, Windows Python 3.14, macOS Python 3.14, and PR metadata. Do not report an unrun OS or host installation smoke test as passing.

## Marketplaces and release assets

Codex and Claude Code marketplace sources are `./dist/openai` and `./dist/claude` within this repository checkout. Installation does not fall back to Release assets. Antigravity is installed locally from `dist/antigravity` or its ZIP.

Release workflow behavior remains tag-only and permission-limited. A local dry run produces `p-ases-openai-vX.Y.Z.zip`, `p-ases-claude-vX.Y.Z.zip`, `p-ases-antigravity-vX.Y.Z.zip`, and `SHA256SUMS`. Packaging validates but never regenerates distributions. This migration does not bump the version, create tags, publish releases, or submit to PyPI or provider directories.
