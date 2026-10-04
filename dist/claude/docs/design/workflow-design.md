<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# Portable Workflow Design

- Status: Approved
- Owning Issue: [Issue #7](https://github.com/puchinya/ai-agent-workflow/issues/7)
- Related specification: [Portable Workflow Specification](../specs/workflow-spec.md)

## Context and goals

The workflow must feel consistent in three agent hosts while respecting each host's plugin format. The source remains repository-owned Markdown, standards, and a standard-library Python CLI. Host packages are deterministic projections of that source, not separate authoring trees.

Goals are explicit Issue authority, progressive context loading, reliable local verification, recoverable exact-byte records, independent review evidence, and reproducible delivery gates. No remote service or persistent runtime process is introduced.

## Requirements traceability

| Requirement | Design consequence |
|---|---|
| One semantic owner per rule | Workflow phase policy lives in this specification; CLI data and failure semantics live in the [Runtime specification](../specs/runtime-spec.md). |
| Nine host-portable Skills | Hand-authored Skills live only under `workflow/skills/`; the distribution builder copies them. |
| Compact context routing | The runtime emits validated paths and identifiers rather than document contents. |
| Review is evidence, not approval | Review commands bind claims to checklist hash and exact PR HEAD; an independent human reviewer still judges the evidence. |
| Durable document decisions stay explicit through implementation | The Issue carries Specification, Design, and Status decisions; implementation checks them against the final diff, and self-review verifies alignment. |
| A current self-review fail blocks handoff | The delivery gate rejects current `fail` items and reports bounded IDs/text while treating `untested` as evidence rather than a global block. |
| Host-specific packages differ | The builder emits three isolated packages from shared sources and adapters. |
| Milestone and feature-branch lifecycle is reusable | Consumer policy stays in Schema 2 `.agent/project.json`; the requirements and implementation Skills call standard runtime commands. |

## Architecture

```text
workflow/ ─────┐
runtime/ ──────┼──> tools/build_dist.py ──> dist/openai|claude|antigravity
adapters/ ─────┘             │
                             └──> tools/validate_dist.py

consumer Issue + .agent/project.json
                 │
                 v
          agent_workflow CLI
          ├── profile/context/documents
          ├── versioning/git lifecycle
          ├── contract/review/delivery
          ├── git.py -> argv-only Git subprocesses
          └── github.py -> authenticated `gh api` for Issues, milestones, and repository metadata
```

`workflow/`, `runtime/`, and `adapters/` are canonical hand-authored trees. `dist/**` is generated and MUST NOT be hand-edited. The CLI is a one-shot Python 3.10+ application using the standard library. GitHub transport is isolated in one module. Git lifecycle commands are isolated in `git.py`; they use subprocess argv, never shell interpolation. Tests replace those boundaries with fakes and do not use network credentials.

## Data flow and ownership

1. A Skill starts from an Issue and reads only the routing data and documents relevant to that task. The Issue declares structured document decisions; older link-only sections remain routable.
2. A consumer's `.agent/project.json` is parsed and fully validated before profile-dependent output or hook execution.
3. Context resolution emits a compact, deterministic manifest. It never writes consumer-controlled files.
4. Contract and review payloads are validated locally before GitHub mutations. API responses are read back and checked before local state is promoted.
5. Handoff reads current Issue, PR, review, and Required Check state; merged delivery remains a separate operation.
6. `build_dist.py` constructs each host package in memory from canonical source and adapter metadata, then writes a deterministic path set.

## Failure handling

Malformed profiles and Document impact declarations fail closed before hooks or scoped validation. Unknown selected components and invalid doc selectors never broaden scope. Host or target requirement mismatches skip commands and remain unverified. Current review failures block handoff; `untested` remains non-blocking by itself. GitHub ambiguity fails closed. Atomic local replacements preserve the old verified bytes on failure. Build/check mismatches identify drift without silently accepting edited generated output.

## Alternatives considered

- Copying the reference repository or its 105 KiB CLI would introduce template ownership and a monolith. The new runtime uses focused modules and only carries forward specified behavior.
- Hand-authored host-specific Skill trees would drift. Adapters contain only explicit host differences.
- A database, MCP server, daemon, or hosted API would add a second authority and is outside the product boundary.
- A shared OpenAI/Antigravity `plugin.json` would violate their different schemas. Packages are separate directories.

## Verification strategy

Unit tests exercise module boundaries with injected Git/GitHub results. Package tests compare complete generated trees byte-for-byte, validate each host independently, and prove that modifying a generated file is detected by `--check`. The CI trust boundary is specified in the [Distribution specification](../specs/distribution-spec.md).
