---
name: implementation-contract
description: Save, publish, restore, and verify exact-byte Issue Implementation Contracts safely.
---
# Implementation Contract

## Trigger and inputs
Use when creating or checking the Issue contract pointer or local mirror. Inputs are an Issue number and optionally the exact UTF-8 source file.

## Procedure
1. Run `python -m agent_workflow verify-implementation-contract <issue>` before relying on an existing pointer.
2. Never hand-edit the approved contract comment or Issue pointer. The body pointer has exactly this canonical form and no appended prose:

   ```text
   ## Implementation Contract
   Comment ID: <comment-id>
   SHA-256: <sha256>
   State: approved
   ```

3. When authoring a new or superseding contract Reviewer Checklist, keep its H2 to the canonical `AGENT_REVIEWER_CHECKLIST_V1` block and the approved introduction `The implementer must self-review every item in this checklist.` Do not place unique normative requirements, architecture decisions, verification requirements, exceptions, or completion gates outside the checklist items. The runtime checks this structure before publication and rejects extra prose without a GitHub mutation. This is a write-boundary rule only: restoring, verifying, or reading an already-approved historical contract must not apply the new authoring whitelist or alter its exact bytes.
4. Save with `python -m agent_workflow save-implementation-contract <issue> <path>` or publish with `python -m agent_workflow publish-implementation-contract <issue>`. Changed approved contracts use `python -m agent_workflow publish-implementation-contract <issue> --supersede`.
5. Run `python -m agent_workflow restore-implementation-contract <issue>` to restore only the recorded comment ID; use `--replace-stale` only after inspecting its SHA-specific backup behavior.
6. Verify Issue identity, comment association, SHA-256, raw byte count, and exact bytes.

## Output and uncertainty
Report Issue, comment ID, SHA, bytes, and mirror path. On identity/API/hash ambiguity, stop and preserve verified local bytes. Never print payloads or credentials. See [runtime specification](../../docs/specs/runtime-spec.md).
