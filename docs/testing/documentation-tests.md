<!-- agent-doc-type: test-specification -->
<!-- agent-doc-schema: 2 -->
# Documentation Tool Test Specification

- Status: Approved for Issue #28
- Owning Issue: https://github.com/puchinya/ai-agent-workflow/issues/28

<!-- contents:start -->
**Contents**
- [1 Test purpose](#1-test-purpose)
- [2 Test conditions and oracles](#2-test-conditions-and-oracles)
  - [2.1 TST-DOC-001 Document role separation](#21-tst-doc-001-document-role-separation)
    - [2.1.1 ORA-DOC-001 Expected result](#211-ora-doc-001-expected-result)
  - [2.2 TST-DOC-002 Stable traceability graph](#22-tst-doc-002-stable-traceability-graph)
    - [2.2.1 ORA-DOC-002 Expected result](#221-ora-doc-002-expected-result)
  - [2.3 TST-DOC-003 Hierarchical heading numbering](#23-tst-doc-003-hierarchical-heading-numbering)
    - [2.3.1 ORA-DOC-003 Expected result](#231-ora-doc-003-expected-result)
  - [2.4 TST-DOC-004 Opaque source blocks](#24-tst-doc-004-opaque-source-blocks)
    - [2.4.1 ORA-DOC-004 Expected result](#241-ora-doc-004-expected-result)
  - [2.5 TST-DOC-005 Contents and anchor continuity](#25-tst-doc-005-contents-and-anchor-continuity)
    - [2.5.1 ORA-DOC-005 Expected result](#251-ora-doc-005-expected-result)
  - [2.6 TST-DOC-006 Markdown fragment repair](#26-tst-doc-006-markdown-fragment-repair)
    - [2.6.1 ORA-DOC-006 Expected result](#261-ora-doc-006-expected-result)
  - [2.7 TST-DOC-007 Read-only and write boundaries](#27-tst-doc-007-read-only-and-write-boundaries)
    - [2.7.1 ORA-DOC-007 Expected result](#271-ora-doc-007-expected-result)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
- [TST-DOC-001](#tst-doc-001) — 2.1 TST-DOC-001 Document role separation
- [ORA-DOC-001](#ora-doc-001) — 2.1.1 ORA-DOC-001 Expected result
- [TST-DOC-002](#tst-doc-002) — 2.2 TST-DOC-002 Stable traceability graph
- [ORA-DOC-002](#ora-doc-002) — 2.2.1 ORA-DOC-002 Expected result
- [TST-DOC-003](#tst-doc-003) — 2.3 TST-DOC-003 Hierarchical heading numbering
- [ORA-DOC-003](#ora-doc-003) — 2.3.1 ORA-DOC-003 Expected result
- [TST-DOC-004](#tst-doc-004) — 2.4 TST-DOC-004 Opaque source blocks
- [ORA-DOC-004](#ora-doc-004) — 2.4.1 ORA-DOC-004 Expected result
- [TST-DOC-005](#tst-doc-005) — 2.5 TST-DOC-005 Contents and anchor continuity
- [ORA-DOC-005](#ora-doc-005) — 2.5.1 ORA-DOC-005 Expected result
- [TST-DOC-006](#tst-doc-006) — 2.6 TST-DOC-006 Markdown fragment repair
- [ORA-DOC-006](#ora-doc-006) — 2.6.1 ORA-DOC-006 Expected result
- [TST-DOC-007](#tst-doc-007) — 2.7 TST-DOC-007 Read-only and write boundaries
- [ORA-DOC-007](#ora-doc-007) — 2.7.1 ORA-DOC-007 Expected result
<!-- heading-map:end -->


<a id="test-purpose"></a>
## 1 Test purpose

Define reproducible conditions and expected results independently of implementation details.

<a id="test-conditions-and-oracles"></a>
## 2 Test conditions and oracles

<a id="tst-doc-001"></a>
<a id="tst-doc-001-document-role-separation"></a>
### 2.1 TST-DOC-001 Document role separation

**Setup and action:** Validate a product spec, design, and test spec with the supported schemas.

<a id="ora-doc-001"></a>
<a id="ora-doc-001-expected-result"></a>
#### 2.1.1 ORA-DOC-001 Expected result

Each role accepts its own required sections; a product spec without Verification Strategy is valid.

<a id="tst-doc-002"></a>
<a id="tst-doc-002-stable-traceability-graph"></a>
### 2.2 TST-DOC-002 Stable traceability graph

**Setup and action:** Validate a complete matrix, then remove a REQ, DES, Oracle, Test, evidence link, and stable anchor in turn.

<a id="ora-doc-002"></a>
<a id="ora-doc-002-expected-result"></a>
#### 2.2.1 ORA-DOC-002 Expected result

The complete REQ-to-DES-to-Oracle/Test-to-Evidence path passes; each missing or duplicate edge returns a precise validation error.

<a id="tst-doc-003"></a>
<a id="tst-doc-003-hierarchical-heading-numbering"></a>
### 2.3 TST-DOC-003 Hierarchical heading numbering

**Setup and action:** Format mixed H1-H6 headings, repeated headings, already generated numbers, author titles beginning with years/numbers, and Setext headings.

<a id="ora-doc-003"></a>
<a id="ora-doc-003-expected-result"></a>
#### 2.3.1 ORA-DOC-003 Expected result

H1 remains unnumbered, including a year-leading title. H2-H6 have deterministic hierarchical counters; a numeric prefix is removed and re-added only when it matches the next counter. Other leading numbers remain part of the title, and a second format has no changes.

<a id="tst-doc-004"></a>
<a id="tst-doc-004-opaque-source-blocks"></a>
### 2.4 TST-DOC-004 Opaque source blocks

**Setup and action:** Place heading-like lines and generated contents markers inside fenced code, including a fence-like line with an info string that cannot close the block; four-column indented code with multiple internal blank lines; HTML comments; raw pre blocks; and front matter. Put a real heading after the protected examples following H1. Run `format_markdown` twice and run `format_tree --write` followed by `format_tree --check` on the same source document.

<a id="ora-doc-004"></a>
<a id="ora-doc-004-expected-result"></a>
#### 2.4.1 ORA-DOC-004 Expected result

Protected headings, generated-marker examples, and blank lines inside the examples are unchanged byte-for-byte. The info-string fence does not close a fenced block, and indented markers are never treated as generated markers. Formatting is idempotent; the second tree write changes no files and tree check reports clean. Contents and heading maps are inserted outside protected regions, before the first real heading after H1.

<a id="tst-doc-005"></a>
<a id="tst-doc-005-contents-and-anchor-continuity"></a>
### 2.5 TST-DOC-005 Contents and anchor continuity

**Setup and action:** Change heading titles/numbers with explicit anchors, duplicate slugs, and generated contents blocks.

<a id="ora-doc-005"></a>
<a id="ora-doc-005-expected-result"></a>
#### 2.5.1 ORA-DOC-005 Expected result

Maps are regenerated, explicit anchors remain, and previous occurrence slugs remain resolvable.

<a id="tst-doc-006"></a>
<a id="tst-doc-006-markdown-fragment-repair"></a>
### 2.6 TST-DOC-006 Markdown fragment repair

**Setup and action:** Use local links and reference definitions to old same-file and cross-file heading slugs.

<a id="ora-doc-006"></a>
<a id="ora-doc-006-expected-result"></a>
#### 2.6.1 ORA-DOC-006 Expected result

Known changed fragments point to current slugs; external, unknown, and inline-code examples remain unchanged.

<a id="tst-doc-007"></a>
<a id="tst-doc-007-read-only-and-write-boundaries"></a>
### 2.7 TST-DOC-007 Read-only and write boundaries

**Setup and action:** Run check on drift, then write twice; attempt a symlink and a target outside docs.

<a id="ora-doc-007"></a>
<a id="ora-doc-007-expected-result"></a>
#### 2.7.1 ORA-DOC-007 Expected result

Check changes no bytes; write is idempotent and atomic; unsafe targets are rejected.
