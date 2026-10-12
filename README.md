# P-ASES — Puchinya Agentic Software Engineering System

**[日本語](README.ja.md) | English**

P-ASES is an Issue-centered development workflow for coding agents. It connects **requirements, product specifications, technical designs, implementation, tests, reviews, and delivery** through an Agent Development Contract (ADC) and verifiable GitHub evidence.

It includes 16 portable Skills, Markdown standards and templates, and a Python CLI. Packages are generated for **Codex (OpenAI), Claude Code, and Google Antigravity** from one canonical source tree.

> **Migration status:** The P-ASES migration is not activated merely because its component PRs merged or CI passed. Parent [Issue #26](https://github.com/puchinya/ai-agent-workflow/issues/26) has separate Integration, User Review, and Activation gates. The current phase CLI does **not** by itself certify that a specification or design was approved. See [Current limitations](#current-limitations).

## How the workflow works

An Issue and its approved **ADC** define the scope, decisions, verification obligations, and completion conditions. Product specifications describe *what* must happen; designs describe *how*; test specifications define independent expected outcomes. Implementation is checked against all three.

```text
Request → Issue + approved ADC
        → requirements
        → [specification] → [design] → ready
        → execution (code, tests, branch, push, PR)
        → verification (exact-HEAD checks, acceptance, reviews)
        → user-review (human decision)
        → separately authorized merge → GitHub Issue closed
```

The square-bracketed phases are **conditional**, not forgotten: `specification` is required when product behavior must be decided or changed; `design` is required when material technical decisions must be made. Each skipped phase needs its own recorded justification. Test specifications, Oracles, and the Verification Plan are established before declaring readiness; they are artifacts, not an additional Issue phase. Changed requirements return to the relevant decision owner before dependent work proceeds.

| Phase | Purpose |
| --- | --- |
| `requirements` | Scope, requirements, acceptance outcomes, and approved ADC |
| `specification` | Confirm observable product behavior in `docs/specs/` when applicable |
| `design` | Confirm architecture, ownership, failures, and compatibility in `docs/design/` when applicable |
| `ready` | Decisions and independent test/verification criteria are ready for execution |
| `execution` | Implement and test on an Issue-scoped branch, then commit, push, and open a PR |
| `verification` | Check the exact PR HEAD, acceptance, CI, self/independent review, and Review Readiness |
| `user-review` | Collect the human user's final decision and handle changes on the same Issue/PR |
| `closed` | Actual GitHub Issue closure after an explicitly authorized merge; no `phase:closed` label |

Parent Issues follow a different lifecycle: `requirements → ready → execution → integration → user-review → closed`. Parent Integration validates the native child-Issue set and dependency DAG, merged PRs, main ancestry, and external evidence. It does not substitute for parent review or activation. The migration's fixed Bootstrap exceptions apply **only** to [Issues #27–#32](https://github.com/puchinya/ai-agent-workflow/issues/26); they are not normal workflow defaults.

**Important boundaries:** an ADC is not a product specification; CI success is not User Review; an agent self-review is not independent review; human feedback does not automatically grant GitHub merge permission. `BLOCKED`, missing evidence, and untested platforms must be reported as such.

## Getting started

**Requirements:** Python 3.10+, Git, and the `gh` CLI with suitable GitHub authentication for operations that access GitHub. An agent host is needed to run Skills, but the Python CLI can be inspected independently.

For development from this repository:

```sh
python -m pip install -e .
python -m p_ases --help
python -m p_ases project status --root .
```

`project status` **reads** an existing `.agent/project.json` (Schema 2); it does not create one. For an existing open Issue with an approved ADC:

```sh
python -m p_ases context show 123 --repo OWNER/REPO --root .
python -m p_ases adc verify 123 --repo OWNER/REPO
```

Replace `123` and `OWNER/REPO` with a real Issue and repository. `context show` is read-only and does not bind an execution or create a worktree. Use the relevant Skill and `python -m p_ases <namespace> <verb> --help` for an operation's complete argument contract; do not treat the example commands as approval to mutate an Issue or PR.

### Install in an agent host

| Host | Package | Installation route |
| --- | --- | --- |
| Codex / OpenAI | `dist/openai` | Add this repository as a plugin marketplace, then install `p-ases`; see [OpenAI package guide](adapters/openai/README.md) |
| Claude Code | `dist/claude` | Add this repository as a plugin marketplace, then install `p-ases`; see [Claude package guide](adapters/claude/README.md) |
| Google Antigravity | `dist/antigravity` | Local/manual installation; third-party marketplace support has not been confirmed; see [Antigravity guide](adapters/antigravity/README.md) |

Marketplace packages refer to directories **inside this repository**, not to GitHub Release assets. Versioned release ZIPs and `SHA256SUMS` are intended for pinned/offline manual installation. Runtime and host-specific behavior should be smoke-tested in the actual environment; publishing a package is not a host test.

## Documents and responsibilities

| Artifact | Authoritative location | Owns |
| --- | --- | --- |
| Product specification | [`docs/specs/`](docs/specs/) | Observable behavior, constraints, errors, compatibility, requirements (`REQ`) |
| Technical design | [`docs/design/`](docs/design/) | Architecture, ownership, lifecycle, failure behavior, alternatives (`DES`) |
| Test specification | [`docs/testing/`](docs/testing/) | Independent Oracles, test inputs, expected results, evidence links (`TST` / `ORA`) |
| Implementation authority | Issue's approved ADC | Exact changes, decisions, non-goals, tests, reviewer checklist, handoff obligations |
| Status and evidence | GitHub Issue/PR, CI and typed evidence; `docs/status/` only when needed | Observed results, approvals, outstanding blockers |

A durable change records the specification/design/status impact; `unchanged` and `not applicable` require an explanation rather than unnecessary documents. Traceability is **REQ → DES → TST/ORA → evidence**. Consult the [documentation guide](docs/README.md) and [workflow standards](workflow/standards/).

## CLI and Skills

The public interface is `python -m p_ases <namespace> <verb> [args]`.

| Area | CLI namespaces |
| --- | --- |
| Request/Issue/contract | `project`, `context`, `adc`, `issue` |
| Source and execution | `docs`, `work`, `pr` |
| Quality and review | `verification`, `acceptance`, `audit`, `user-review` |
| Final gates | `delivery` |

The canonical [16 Skills](workflow/skills/) cover request intake, ADC authoring and registry, Issue decomposition, product specification, technical design, test specification, work execution and checkpointing, verification and acceptance, contract audit, independent review, user review, integration validation, and delivery control. Their source is under `workflow/skills/`, with shared standards/templates under `workflow/`. Generated `dist/**` files are **not** edited by hand.

The CLI is a one-shot, Python-standard-library runtime; it does not provide a background service, automatically create host worktrees, or automatically merge, activate, or release. Host-managed isolated workspace support is conditional on the host's ability to honor the exact approved base SHA.

## Validate and develop

```sh
python -m compileall runtime tools tests
python -m unittest discover -s tests -p 'test_*.py'
python -m p_ases docs validate --root .
python -m p_ases docs format --check --root .
python tools/validate_pases_traceability.py specification
python tools/validate_pases_traceability.py design
python tools/validate_pases_traceability.py test-oracle
python tools/build_dist.py --check
python tools/validate_dist.py
python tools/validate_parent_acceptance.py 16-skills-package
git diff --check
```

After editing canonical runtime, Skills, standards, templates, or adapters, regenerate generated packages with `python tools/build_dist.py`, then run the checks above. CI covers Ubuntu (Python 3.10/3.14), Windows (3.14), and macOS (3.14); do not claim an unrun host smoke test or platform is verified. Version is defined in `runtime/p_ases/__init__.py` (currently `0.8.0`). Releases are separately authorized tag-based operations.

## Current limitations

As of **2026-10-12**, the implementation has `specification` and `design` phase names and supports recorded skip reasons, but the foundational `issue advance` operation validates **phase-label transitions**, not the semantic approval of specification/design artifacts. `issue split` currently creates children without their initial `phase:*` label, so the normal advance path is not yet seamless. Parts of [`docs/specs/workflow-spec.md`](docs/specs/workflow-spec.md) still contain a labeled legacy lifecycle, which should not be confused with the intended P-ASES child lifecycle above. These are open workflow-consistency findings, **not passing acceptance criteria**. They must be resolved and tested before claiming the general workflow is fully enforced.

P-ASES uses **fail-closed** gates for missing or stale evidence. See the [migration Issue #26](https://github.com/puchinya/ai-agent-workflow/issues/26) for its distinct parent Integration and Activation status.

## License

See [LICENSE](LICENSE).
