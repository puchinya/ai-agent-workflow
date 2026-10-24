<!-- agent-doc-type: design -->
<!-- agent-doc-schema: 2 -->
# P-ASES Documentation Tool Design

- Status: Approved for Issue #28
- Owning Issue: https://github.com/puchinya/ai-agent-workflow/issues/28
- Related specification: ../specs/documentation-tooling-spec.md

<!-- contents:start -->
**Contents**
- [1 Context and goals](#1-context-and-goals)
- [2 Requirements traceability](#2-requirements-traceability)
- [3 Architecture](#3-architecture)
  - [3.1 DES-DOC-001 Command ownership](#31-des-doc-001-command-ownership)
  - [3.2 DES-DOC-002 Numbering transformation](#32-des-doc-002-numbering-transformation)
  - [3.3 DES-DOC-003 Anchor and link continuity](#33-des-doc-003-anchor-and-link-continuity)
  - [3.4 DES-DOC-004 Validation graph](#34-des-doc-004-validation-graph)
  - [3.5 DES-DOC-005 Atomic source updates](#35-des-doc-005-atomic-source-updates)
- [4 Data flow and ownership](#4-data-flow-and-ownership)
- [5 Failure handling](#5-failure-handling)
- [6 Alternatives considered](#6-alternatives-considered)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [DES-DOC-001](#des-doc-001) — 3.1 DES-DOC-001 Command ownership
- [DES-DOC-002](#des-doc-002) — 3.2 DES-DOC-002 Numbering transformation
- [DES-DOC-003](#des-doc-003) — 3.3 DES-DOC-003 Anchor and link continuity
- [DES-DOC-004](#des-doc-004) — 3.4 DES-DOC-004 Validation graph
- [DES-DOC-005](#des-doc-005) — 3.5 DES-DOC-005 Atomic source updates
<!-- heading-map:end -->


<a id="context-and-goals"></a>
## 1 Context and goals

The repository needs a deterministic Markdown source formatter and a validator that can prove requirement-to-evidence traceability without rewriting prose or reaching external services.

<a id="requirements-traceability"></a>
## 2 Requirements traceability

The complete REQ-to-DES-to-Oracle/Test-to-Evidence graph is maintained in the repository's `docs/testing/traceability.md`.

<a id="architecture"></a>
## 3 Architecture

<a id="des-doc-001"></a>
<a id="des-doc-001-command-ownership"></a>
### 3.1 DES-DOC-001 Command ownership

The p_ases CLI owns docs validate and docs format argument routing and machine-readable results. documents.py owns source document roles, IDs, local links, and traceability validation. document_format.py owns deterministic heading normalization, anchor preservation, generated maps, link repair, and bounded atomic writes. Neither module owns Git, GitHub, hooks, or network access.

<a id="des-doc-002"></a>
<a id="des-doc-002-numbering-transformation"></a>
### 3.2 DES-DOC-002 Numbering transformation

The formatter first removes only its exact generated contents/map marker lines outside front matter, fenced blocks, four-column indented code blocks, HTML comments, and raw pre blocks. It skips `docs/contracts/` artifacts entirely so exact ADC bytes and their published hashes are preserved. A fence closes only when its matching delimiter is long enough and has no non-whitespace suffix, so a fence-like line with an info string remains protected content. Indented code and its internal blank lines stay byte-for-byte unchanged. The shared ATX parser strips closing hashes only when whitespace separates them from the title, preserving suffixes such as `C#` and `name###`. It scans Markdown source using the same protected-line parser for numbering and contents insertion. H1 resets numbering; H2 through H6 use deterministic hierarchical counters. A numeric prefix is recognized as formatter-generated only when it matches the next counter at that level, so other leading numbers stay in the title. Setext headings normalize to ATX so the next run produces the same bytes.

<a id="des-doc-003"></a>
<a id="des-doc-003-anchor-and-link-continuity"></a>
### 3.3 DES-DOC-003 Anchor and link continuity

For every changed heading slug, the formatter records old-to-new occurrence mappings, adds an explicit legacy anchor if one does not already exist, and rewrites same-file and repository-relative Markdown link fragments. Duplicate heading occurrences receive GitHub-style suffixes before mapping. Explicit anchors are never deleted.

<a id="des-doc-004"></a>
<a id="des-doc-004-validation-graph"></a>
### 3.4 DES-DOC-004 Validation graph

documents.py scans canonical specs, design, and testing trees, builds a unique definition index, checks manual stable-ID anchors, parses the REQ/DES/Oracle/Test/Evidence matrix, and verifies local links and complete graph reachability. It uses the independent test specification as the Oracle source and the matrix's existing test source paths as evidence owners.

<a id="des-doc-005"></a>
<a id="des-doc-005-atomic-source-updates"></a>
### 3.5 DES-DOC-005 Atomic source updates

Formatting computes the complete docs tree result before writing. Each changed file is encoded as UTF-8 into a same-directory temporary file, flushed, assigned the original mode bits, and replaced atomically. Check mode uses the same deterministic calculation but never opens a write handle.

<a id="data-flow-and-ownership"></a>
## 4 Data flow and ownership

The CLI resolves a repository root. Validation reads docs and referenced local paths only. Formatting reads the docs Markdown set, computes per-file heading mappings, repairs links using the complete set of mappings, generates contents and stable-ID maps, and returns the changed path list. The write operation is a separate final step and refuses symlink targets.

<a id="failure-handling"></a>
## 5 Failure handling

Malformed UTF-8, missing docs roots, symlinks, paths escaping the repository, malformed stable IDs, ambiguous matrix rows, broken fragments, and formatting drift return bounded nonzero results. Atomic replacement leaves prior files intact if a temporary write fails before replacement.

<a id="alternatives-considered"></a>
## 6 Alternatives considered

- A prose rewriter could alter normative meaning; formatting is restricted to headings, generated maps, and link fragments.
- A network Markdown renderer would make validation unavailable offline and could change behavior independently of the source tree.
- Hand-authored contents maps drift; the formatter owns only marker-delimited generated blocks.
- Writing each target directly risks truncating a document; sibling temporary files and atomic replacement preserve the prior source on ordinary failures.
