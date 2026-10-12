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

    def test_generated_markers_and_blank_lines_inside_fences_are_preserved(self):
        fence = (
            "```markdown\n"
            "<!-- contents:start -->\n"
            "Sample source content that MUST remain\n"
            "\n\n"
            "<!-- contents:end -->\n"
            "## Example heading\n"
            "```"
        )
        source = f"# Title\n\n{fence}\n\n## Actual\n"

        formatted = format_markdown(source).text

        self.assertIn(fence, formatted)
        self.assertEqual(format_markdown(formatted).text, formatted)
        actual_contents = formatted.rindex("<!-- contents:start -->")
        actual_heading = formatted.index("## 1 Actual")
        fence_end = formatted.index("```", formatted.index("## Example heading"))
        self.assertLess(fence_end, actual_contents)
        self.assertLess(actual_contents, actual_heading)

    def test_fence_info_string_cannot_close_an_open_fence(self):
        fenced = (
            "```text\n"
            "```python\n"
            "<!-- contents:start -->\n"
            "Keep this source code example.\n"
            "<!-- contents:end -->\n"
            "```"
        )
        source = (
            "# Document\n\n"
            f"{fenced}\n\n"
            "## Actual\n"
        )

        formatted = format_markdown(source).text

        self.assertIn(fenced, formatted)
        self.assertEqual(format_markdown(formatted).text, formatted)

    def test_indented_code_markers_and_blank_lines_are_preserved(self):
        example = (
            "    <!-- contents:start -->\n"
            "    Keep this indented code example.\n"
            "\n\n"
            "    <!-- contents:end -->"
        )
        source = f"# Document\n\n{example}\n\n## Actual\n"

        formatted = format_markdown(source).text

        self.assertIn(example, formatted)
        self.assertEqual(format_markdown(formatted).text, formatted)

    def test_tree_write_and_check_preserve_opaque_code_examples(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            doc = repo / "docs" / "specs" / "a.md"
            doc.parent.mkdir(parents=True)
            fenced = (
                "```text\n"
                "```python\n"
                "<!-- contents:start -->\n"
                "Keep this source code example.\n"
                "<!-- contents:end -->\n```"
            )
            indented = (
                "    <!-- contents:start -->\n"
                "    Keep this indented code example.\n"
                "\n\n"
                "    <!-- contents:end -->"
            )
            doc.write_text(f"# Document\n\n{fenced}\n\n{indented}\n\n## Actual\n", encoding="utf-8")

            format_tree(repo, write=True)
            result = doc.read_text(encoding="utf-8")
            self.assertIn(fenced, result)
            self.assertIn(indented, result)
            self.assertEqual(format_tree(repo, write=False), ())
            self.assertEqual(format_tree(repo, write=True), ())

    def test_generated_markers_inside_front_matter_comments_and_pre_are_preserved(self):
        examples = (
            "---\n"
            "example: |\n"
            "  <!-- contents:start -->\n"
            "  Front matter sample MUST remain\n"
            "  <!-- contents:end -->\n"
            "---\n\n# Title\n",
            "<!-- documentation example\n"
            "<!-- contents:start -->\n"
            "HTML comment sample MUST remain\n"
            "<!-- contents:end -->\n"
            "-->\n\n# Title\n",
            "<pre>\n"
            "<!-- contents:start -->\n"
            "Preformatted sample MUST remain\n"
            "<!-- contents:end -->\n"
            "</pre>\n\n# Title\n",
        )
        for source in examples:
            with self.subTest(source=source):
                formatted = format_markdown(source).text
                for sample in (
                    "Front matter sample MUST remain",
                    "HTML comment sample MUST remain",
                    "Preformatted sample MUST remain",
                ):
                    if sample in source:
                        self.assertIn(sample, formatted)

    def test_headings_after_fences_are_selected_for_contents_insertion(self):
        source = "# Title\n\n```md\n## Example\n```\n\n## Actual\n"
        formatted = format_markdown(source).text
        contents_start = formatted.rindex("<!-- contents:start -->")
        actual_heading = formatted.index("## 1 Actual")
        fence_end = formatted.index("```", formatted.index("## Example"))
        self.assertLess(fence_end, contents_start)
        self.assertLess(contents_start, actual_heading)
        self.assertIn("## Example", formatted)
        self.assertEqual(format_markdown(formatted).text, formatted)

    def test_meaningful_numeric_heading_prefixes_are_retained(self):
        source = "# 2026 Roadmap\n\n## 2026 Changes\n\n## Heading\n"
        formatted = format_markdown(source).text
        self.assertIn("# 2026 Roadmap", formatted)
        self.assertIn("## 1 2026 Changes", formatted)
        self.assertIn("## 2 Heading", formatted)
        self.assertEqual(format_markdown(formatted).text, formatted)

        generated = format_markdown("# Title\n\n## 1 Heading\n").text
        self.assertIn("## 1 Heading", generated)
        self.assertEqual(format_markdown(generated).text, generated)

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
