from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.document_format import DocumentFormatError, extract_headings, format_markdown, format_tree


class DocumentFormatTests(unittest.TestCase):
    def test_hierarchical_numbering_ignores_opaque_blocks_and_is_idempotent(self):
        source = """---
title: "## front matter"
---
# Title

## Parent
### Child
#### Grandchild
## Parent
### Child

<!--
## comment heading
-->

<pre>
## raw HTML heading
</pre>

~~~python
## fenced heading
~~~
"""
        first = format_markdown(source).text
        second = format_markdown(first).text
        self.assertEqual(first, second)
        titles = [heading.title for heading in extract_headings(first)]
        self.assertEqual(titles[:6], [
            "Title", "1 Parent", "1.1 Child", "1.1.1 Grandchild", "2 Parent", "2.1 Child",
        ])
        self.assertNotIn("1 front matter", first)
        self.assertIn("## comment heading", first)
        self.assertIn("## raw HTML heading", first)
        self.assertIn("## fenced heading", first)
        self.assertIn("<!-- contents:start -->", first)
        self.assertIn("<!-- heading-map:start -->", first)

    def test_setext_headings_and_duplicate_legacy_slugs_are_preserved(self):
        source = "# Title\n\nAlpha\n-----\n\n## Alpha\n\n## Alpha\n"
        formatted = format_markdown(source).text
        self.assertIn("## 1 Alpha", formatted)
        self.assertIn("## 2 Alpha", formatted)
        self.assertIn('<a id="alpha"></a>', formatted)
        self.assertIn('<a id="alpha-1"></a>', formatted)
        self.assertEqual(format_markdown(formatted).text, formatted)

    def test_explicit_anchor_and_links_to_it_remain_unchanged(self):
        source = "# Title\n\n<a id=\"intro\"></a>\n## Intro\n\n[manual](#intro)\n"
        formatted = format_markdown(source).text
        self.assertIn('<a id="intro"></a>', formatted)
        self.assertIn("[manual](#intro)", formatted)
        self.assertNotIn("[manual](#1-intro)", formatted)

    def test_tree_repairs_same_file_cross_file_and_reference_fragments(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            docs = repo / "docs"
            (docs / "specs").mkdir(parents=True)
            source = docs / "specs" / "source.md"
            target = docs / "specs" / "target.md"
            tick = chr(96)
            source.write_text(
                "# Source\n\n## Intro\n\n[self](#intro) [cross](target.md#topic) [ref][r]\n\n"
                "[r]: <target.md#topic>\n" + tick + "[example](#intro)" + tick + "\n",
                encoding="utf-8",
            )
            target.write_text("# Target\n\n## Topic\n", encoding="utf-8")
            changed = format_tree(repo, write=True)
            self.assertEqual(set(changed), {"docs/specs/source.md", "docs/specs/target.md"})
            result = source.read_text(encoding="utf-8")
            self.assertIn("[self](#1-intro)", result)
            self.assertIn("[cross](target.md#1-topic)", result)
            self.assertIn("[r]: <target.md#1-topic>", result)
            self.assertIn(f"{tick}[example](#intro){tick}", result)
            self.assertIn('<a id="intro"></a>', result)
            self.assertEqual(format_tree(repo, write=False), ())

    def test_check_mode_is_read_only_and_write_is_scoped_to_docs(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            doc = repo / "docs" / "specs" / "a.md"
            doc.parent.mkdir(parents=True)
            doc.write_text("# A\n\n## Heading\n", encoding="utf-8")
            protected = repo / "dist" / "copy.md"
            protected.parent.mkdir()
            protected.write_text("# Generated\n", encoding="utf-8")
            before = doc.read_bytes()
            generated_before = protected.read_bytes()
            self.assertEqual(format_tree(repo, write=False), ("docs/specs/a.md",))
            self.assertEqual(doc.read_bytes(), before)
            format_tree(repo, write=True)
            self.assertEqual(format_tree(repo, write=False), ())
            self.assertEqual(protected.read_bytes(), generated_before)

    def test_symlinked_document_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            docs = repo / "docs"
            docs.mkdir()
            outside = repo / "outside.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            link = docs / "linked.md"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(DocumentFormatError, "symlink"):
                format_tree(repo, write=True)


if __name__ == "__main__":
    unittest.main()
