---
name: implementation-contract
description: Save, publish, restore, and verify exact-byte Issue Implementation Contracts safely.
---
# Implementation Contract

## Trigger and inputs
Use when creating or checking the Issue contract pointer or local mirror. Inputs are an Issue number and optionally the exact UTF-8 source file.

## Procedure
1. Run `verify-implementation-contract` before relying on an existing pointer.
2. Save or publish with the corresponding CLI command; use `--supersede` only for an approved changed contract.
3. Restore only the recorded comment ID; use `--replace-stale` only after inspecting its SHA-specific backup behavior.
4. Verify Issue identity, comment association, SHA-256, raw byte count, and exact bytes.

## Output and uncertainty
Report Issue, comment ID, SHA, bytes, and mirror path. On identity/API/hash ambiguity, stop and preserve verified local bytes. Never print payloads or credentials. See [runtime specification](../../../docs/specs/runtime-spec.md).
