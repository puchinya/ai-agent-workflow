<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# P-ASES Documentation Tool Specification

- Status: Approved for Issue #28
- Owning Issue: https://github.com/puchinya/ai-agent-workflow/issues/28
- Related design: ../design/documentation-tooling-design.md

<!-- contents:start -->
**Contents**
- [1 Purpose](#1-purpose)
- [2 Scope](#2-scope)
- [3 Normative requirements](#3-normative-requirements)
  - [3.1 REQ-DOC-001 Document roles](#31-req-doc-001-document-roles)
  - [3.2 REQ-DOC-002 Stable traceability](#32-req-doc-002-stable-traceability)
  - [3.3 REQ-DOC-003 Deterministic heading numbers](#33-req-doc-003-deterministic-heading-numbers)
  - [3.4 REQ-DOC-004 Contents maps and anchors](#34-req-doc-004-contents-maps-and-anchors)
  - [3.5 REQ-DOC-005 Local Markdown links](#35-req-doc-005-local-markdown-links)
  - [3.6 REQ-DOC-006 Read-only check and idempotent write](#36-req-doc-006-read-only-check-and-idempotent-write)
  - [3.7 REQ-DOC-007 Fail-closed boundaries](#37-req-doc-007-fail-closed-boundaries)
- [4 Observable behavior](#4-observable-behavior)
- [5 Error and boundary behavior](#5-error-and-boundary-behavior)
- [6 Security and privacy](#6-security-and-privacy)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [REQ-DOC-001](#req-doc-001) — 3.1 REQ-DOC-001 Document roles
- [REQ-DOC-002](#req-doc-002) — 3.2 REQ-DOC-002 Stable traceability
- [REQ-DOC-003](#req-doc-003) — 3.3 REQ-DOC-003 Deterministic heading numbers
- [REQ-DOC-004](#req-doc-004) — 3.4 REQ-DOC-004 Contents maps and anchors
- [REQ-DOC-005](#req-doc-005) — 3.5 REQ-DOC-005 Local Markdown links
- [REQ-DOC-006](#req-doc-006) — 3.6 REQ-DOC-006 Read-only check and idempotent write
- [REQ-DOC-007](#req-doc-007) — 3.7 REQ-DOC-007 Fail-closed boundaries
<!-- heading-map:end -->


<a id="purpose"></a>
## 1 Purpose

Define the offline validation and deterministic source formatting commands for P-ASES documentation.

<a id="scope"></a>
## 2 Scope

The commands are exposed through python -m p_ases docs. Validation covers Markdown under docs/specs, docs/design, and docs/testing. Formatting reads and writes Markdown under docs only. It does not contact GitHub, format immutable comments, edit workflow/templates, or hand-edit generated distributions.

<a id="normative-requirements"></a>
## 3 Normative requirements

<a id="req-doc-001"></a>
<a id="req-doc-001-document-roles"></a>
### 3.1 REQ-DOC-001 Document roles

Product behavior belongs in docs/specs; architecture and ownership belong in docs/design; test conditions, independent Oracles, and evidence sources belong in docs/testing. A product specification has no mandatory Verification Strategy chapter.

<a id="req-doc-002"></a>
<a id="req-doc-002-stable-traceability"></a>
### 3.2 REQ-DOC-002 Stable traceability

Requirements, design decisions, test conditions, and independent Oracles use unique stable REQ-AREA-NNN, DES-AREA-NNN, TST-AREA-NNN, and ORA-AREA-NNN identifiers. The traceability matrix must link every REQ through at least one DES and one ORA/TST to an existing executable evidence source. IDs and links are validated without fetching external URLs.

<a id="req-doc-003"></a>
<a id="req-doc-003-deterministic-heading-numbers"></a>
### 3.3 REQ-DOC-003 Deterministic heading numbers

The formatter leaves H1 titles unnumbered and assigns hierarchical numbering to H2 through H6 in document order. It ignores headings inside fenced code, four-column indented code blocks, HTML comments, raw pre blocks, and YAML front matter. A fenced block closes only on a matching fence character with a delimiter at least as long as the opener and whitespace only after the delimiter. For H2-H6, it treats a leading numeric prefix as a previously generated number only when it matches that heading's next hierarchical counter; other numeric prefixes remain part of the heading title. It converts Setext headings to the corresponding ATX form.

<a id="req-doc-004"></a>
<a id="req-doc-004-contents-maps-and-anchors"></a>
### 3.4 REQ-DOC-004 Contents maps and anchors

The formatter regenerates contents and stable-ID heading maps from source headings. It preserves explicit/manual anchors and inserts a legacy anchor when a generated heading slug changes, including the original occurrence slug for duplicate headings.

<a id="req-doc-005"></a>
<a id="req-doc-005-local-markdown-links"></a>
### 3.5 REQ-DOC-005 Local Markdown links

When numbering changes a heading slug, formatting updates matching same-file and relative Markdown links, including reference definitions. Links to external URLs, code examples, unknown fragments, and explicit manual anchors retain their values. The validator checks that local files and fragments resolve within the repository.

<a id="req-doc-006"></a>
<a id="req-doc-006-read-only-check-and-idempotent-write"></a>
### 3.6 REQ-DOC-006 Read-only check and idempotent write

docs format --check reports drift and performs no writes. docs format --write produces deterministic UTF-8 source and is idempotent. Writes use temporary sibling files and atomic replacement while preserving existing mode bits.

<a id="req-doc-007"></a>
<a id="req-doc-007-fail-closed-boundaries"></a>
### 3.7 REQ-DOC-007 Fail-closed boundaries

Formatting refuses symlinks, non-UTF-8 source, or paths outside docs. Validation reports malformed document markers, required sections, duplicate/misplaced IDs, incomplete traceability, broken local links, and formatting drift as nonzero results. Neither command invokes shell hooks, GitHub, or subprocesses.

<a id="observable-behavior"></a>
## 4 Observable behavior

docs validate returns a machine-readable result with status and bounded errors. docs format --check returns a clean result when formatting is stable and a nonzero drift result otherwise. docs format --write reports each changed docs-relative path and leaves a second run unchanged.

<a id="error-and-boundary-behavior"></a>
## 5 Error and boundary behavior

| Condition | Required behavior |
|---|---|
| Missing docs tree or malformed source encoding | Return a nonzero document error without broadening the path scope. |
| Broken local link, duplicate stable ID, or incomplete graph | Report the source path and defect; return nonzero. |
| Formatting check detects changes | Report drift without modifying any byte. |
| Formatting write encounters a symlink or write error | Refuse the target or report the failed path; do not follow the link outside docs. |
| External link is unreachable | Do not fetch it; external link status is not evaluated. |

<a id="security-and-privacy"></a>
## 6 Security and privacy

The formatter only accesses source Markdown below docs and uses local atomic filesystem writes. It does not print document bodies, invoke hooks, use credentials, or mutate GitHub state.
