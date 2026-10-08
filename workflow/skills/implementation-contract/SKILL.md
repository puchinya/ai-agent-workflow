---
name: implementation-contract
description: Save, publish, restore, and verify Issue Implementation Contracts with safe checklist canonicalization and exact published-byte binding.
---
# Implementation Contract

## Trigger and inputs
Use when creating or checking the Issue contract pointer or local mirror. Inputs are an Issue number and optionally the exact UTF-8 source file.

## Procedure
1. Run `python -m agent_workflow verify-implementation-contract <issue>` before relying on an existing pointer.
   Approval or publishing alone does not allocate a workspace; isolation is considered only when the approved Contract is executed.
2. Never hand-edit the approved contract comment or Issue pointer. The body pointer has exactly this canonical form and no appended prose:

   ```text
   ## Implementation Contract
   Comment ID: <comment-id>
   SHA-256: <sha256>
   State: approved
   ```

3. Saving or publishing automatically canonicalizes a recognizable legacy `Reviewer Checklist` H2. The runtime preserves each checkbox item's exact text and order plus every byte outside that H2, inserts the canonical markers and approved introduction, and reports whether conversion occurred. It recognizes `Implementer MUST self-review every item.` as a legacy introduction. The hash and byte count bind the normalized payload saved or published. Duplicate headings, malformed/missing items, or unrelated prose fail before GitHub mutation; never discard prose or infer checklist items. Historical contract reads and restores remain byte-for-byte and are never normalized.
4. Save with `python -m agent_workflow save-implementation-contract <issue> <path>` or publish with `python -m agent_workflow publish-implementation-contract <issue>`. Changed approved contracts use `python -m agent_workflow publish-implementation-contract <issue> --supersede`.
5. Run `python -m agent_workflow restore-implementation-contract <issue>` to restore only the recorded comment ID; use `--replace-stale` only after inspecting its SHA-specific backup behavior.
6. Verify Issue identity, comment association, SHA-256, normalized byte count, and exact published bytes.

## Output and uncertainty
Report Issue, comment ID, SHA, normalized byte count, whether normalization occurred, and mirror path. On identity/API/hash ambiguity, stop and preserve verified local bytes. Never print payloads or credentials. See [runtime specification](../../../docs/specs/runtime-spec.md).
