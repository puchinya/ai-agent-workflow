---
name: adc-registry
description: Verify and recover exact immutable ADC records and pointers on GitHub Issues.
---
# ADC registry

## Owner and inputs

Owner: runtime/p_ases/adc.py and runtime/p_ases/github.py. Inputs are the exact repository, Issue number, current Issue body, approved ADC pointer, and named comment.

## Workflow

1. Fetch the Issue and current pointer through the GitHub boundary.
2. Read the exact named comment and verify its repository/Issue association.
3. Compare UTF-8 byte length and SHA-256 before parsing the contract.
4. Restore only from a verified pointer. Treat local mirrors as copies, never as the authority.
5. Re-read the Issue after any operation where a concurrent body update could change pointer history.
6. For a new `approved` publication, require the shared approval-ready preflight and exact current predecessor match; historical verification must continue to read immutable generations without retroactively applying that publication-only check.

## CLI

~~~sh
python -m p_ases adc verify 32 --repo OWNER/REPO
python -m p_ases adc restore 32 path/to/contract.md --repo OWNER/REPO
~~~

## Failure handling and output

A missing or duplicate pointer, stale predecessor chain, edited/deleted comment, wrong comment association, hash/length mismatch, malformed ADC, or non-approved state is a failure. The pointer journal supplies the recorded state; a historically approved comment may contain a draft-only header from an older publication and remains readable without rewriting it. New approved writes must pass the stricter final-content and predecessor preflight. Do not guess a nearby comment ID or fall back to an old local copy. Report the exact pointer state, comment ID when verified, digest, byte length, and reason.

Next owners: work-execution requires a verified approved ADC; contract-audit checks exact subject identity. Historical records remain immutable. See the [workflow specification](../../docs/specs/workflow-spec.md).
