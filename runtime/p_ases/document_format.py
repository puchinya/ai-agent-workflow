"""Deterministic source formatting for Markdown documents."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit


class DocumentFormatError(ValueError):
    pass


_MARKERS = {
    "contents": ("<!-- contents:start -->", "<!-- contents:end -->"),
    "heading-map": ("<!-- heading-map:start -->", "<!-- heading-map:end -->"),
}
_GENERATED_MARKERS = frozenset(marker for pair in _MARKERS.values() for marker in pair)
_FENCE = re.compile(r"^ {0,3}(" + re.escape(chr(96)) + r"{3,}|~{3,})")
_ATX = re.compile(r"^( {0,3})(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-{3,})[ \t]*$")
_AUTO_NUMBER = re.compile(r"^(\d+(?:\.\d+)*\.?)\s+")
_STABLE_ID = re.compile(r"\b(?:REQ|DES|TST|ORA)-[A-Z0-9]+-\d{3}\b")
_ANCHOR = re.compile(r"<a\s+[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"][^>]*>\s*</a\s*>", re.I)
_LINK = re.compile(r"(?:(?P<image>!\[[^\]]*\])|(?<!!)(?P<text>\[[^\]]*\]))\((?P<target><[^>]+>|[^\s)]+)(?P<tail>[^)]*)\)")
_REFERENCE = re.compile(r"^(\s*\[[^\]]+\]:\s*)(<([^>]+)>|(\S+))(.*)$")
_INLINE_CODE = chr(96)


@dataclass(frozen=True)
class Heading:
    line: int
    level: int
    title: str
    slug: str
    stable_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FormattedMarkdown:
    text: str
    link_map: dict[str, str]


def _strip_generated_blocks(markdown: str) -> str:
    lines = markdown.splitlines()
    protected = _protected_lines(lines, expose_generated_markers=True)
    removed: set[int] = set()
    for start, end in _MARKERS.values():
        block_start: int | None = None
        for index, line in enumerate(lines):
            if protected[index]:
                continue
            marker = line
            if block_start is None and marker == start:
                block_start = index
            elif block_start is not None and marker == end:
                removed.update(range(block_start, index + 1))
                block_start = None

    kept = [line for index, line in enumerate(lines) if index not in removed]
    protected = _protected_lines(kept)
    normalized: list[str] = []
    index = 0
    while index < len(kept):
        if kept[index] != "" or protected[index]:
            normalized.append(kept[index])
            index += 1
            continue
        end = index + 1
        while end < len(kept) and kept[end] == "" and not protected[end]:
            end += 1
        normalized.extend(kept[index:min(end, index + 1)])
        index = end
    return "\n".join(normalized)


def _protected_lines(lines: list[str], *, expose_generated_markers: bool = False) -> list[bool]:
    protected = [False] * len(lines)
    next_nonblank_indented = [False] * len(lines)
    following_nonblank_is_indented = False
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            following_nonblank_is_indented = _has_indented_code_prefix(lines[index])
        next_nonblank_indented[index] = following_nonblank_is_indented
    in_fence: str | None = None
    fence_length = 0
    in_comment = False
    in_pre = False
    in_indented_code = False
    front_matter = bool(lines and lines[0].strip() == "---")
    for index, line in enumerate(lines):
        if front_matter:
            protected[index] = True
            if index > 0 and line.strip() in {"---", "..."}:
                front_matter = False
            continue
        if in_fence is not None:
            protected[index] = True
            marker = _FENCE.match(line)
            if (
                marker
                and marker.group(1)[0] == in_fence
                and len(marker.group(1)) >= fence_length
                and not line[marker.end():].strip()
            ):
                in_fence = None
                fence_length = 0
            continue
        if in_comment:
            protected[index] = True
            if "-->" in line:
                in_comment = False
            continue
        if in_pre:
            protected[index] = True
            if re.search(r"</pre\s*>", line, re.I):
                in_pre = False
            continue
        if in_indented_code:
            if not line.strip():
                if next_nonblank_indented[index]:
                    protected[index] = True
                    continue
                in_indented_code = False
            if _has_indented_code_prefix(line):
                protected[index] = True
                continue
            if line.strip():
                in_indented_code = False
        if _has_indented_code_prefix(line) and line.strip():
            protected[index] = True
            in_indented_code = True
            continue
        if expose_generated_markers and line in _GENERATED_MARKERS:
            continue
        marker = _FENCE.match(line)
        if marker:
            protected[index] = True
            in_fence = marker.group(1)[0]
            fence_length = len(marker.group(1))
            continue
        if "<!--" in line:
            protected[index] = True
            if "-->" not in line[line.find("<!--") + 4:]:
                in_comment = True
            continue
        if re.search(r"<pre(?:\s|>)", line, re.I):
            protected[index] = True
            if not re.search(r"</pre\s*>", line, re.I):
                in_pre = True
    return protected


def _has_indented_code_prefix(line: str) -> bool:
    """Return whether leading whitespace reaches Markdown's four-column indent."""
    columns = 0
    for character in line:
        if character == " ":
            columns += 1
        elif character == "\t":
            columns += 4 - (columns % 4)
        else:
            return columns >= 4
    return columns >= 4


def _manual_anchors(markdown: str) -> set[str]:
    lines = markdown.splitlines()
    protected = _protected_lines(lines)
    return {
        value.casefold()
        for index, line in enumerate(lines)
        if not protected[index]
        for value in _ANCHOR.findall(line)
    }


def _plain_heading(value: str) -> str:
    value = re.sub(r"<[^>]*>", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"(?<!\\)" + _INLINE_CODE + r"+(.*?)" + _INLINE_CODE + r"+", r"\1", value)
    value = re.sub(r"[*_~]", "", value)
    return value.strip()


def slugify_heading(value: str) -> str:
    value = _plain_heading(value).casefold()
    value = re.sub(r"[^\w\-\s]", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "-", value.strip())
    return value


def _numbered_headings(markdown: str) -> tuple[str, dict[str, str]]:
    lines = markdown.splitlines()
    protected = _protected_lines(lines)
    duplicate_counts: dict[str, int] = {}
    new_duplicate_counts: dict[str, int] = {}
    counters = [0] * 7
    link_map: dict[str, str] = {}
    output: list[str] = []
    explicit_anchors = _manual_anchors(markdown)

    index = 0
    while index < len(lines):
        if protected[index]:
            output.append(lines[index])
            index += 1
            continue
        match = _ATX.match(lines[index])
        setext_level = None
        if not match and index + 1 < len(lines) and not protected[index + 1]:
            setext = _SETEXT.match(lines[index + 1])
            if setext and lines[index].strip():
                setext_level = 1 if setext.group(1).startswith("=") else 2
        if match:
            indent, hashes, source_title = match.groups()
            level = len(hashes)
        elif setext_level is not None:
            indent, hashes = "", "#" * setext_level
            source_title = lines[index].strip()
            level = setext_level
        else:
            output.append(lines[index])
            index += 1
            continue

        old_slug_base = slugify_heading(source_title)
        old_count = duplicate_counts.get(old_slug_base, 0)
        duplicate_counts[old_slug_base] = old_count + 1
        old_slug = old_slug_base if old_count == 0 else f"{old_slug_base}-{old_count}"

        if level == 1:
            counters = [0] * 7
            title = source_title.strip()
            new_title = title
        else:
            for missing_level in range(2, level):
                if counters[missing_level] == 0:
                    counters[missing_level] = 1
            expected_parts = [*counters[2:level], counters[level] + 1]
            expected_number = ".".join(str(item) for item in expected_parts)
            numbered = _AUTO_NUMBER.match(source_title.strip())
            if numbered and numbered.group(1).rstrip(".") == expected_number:
                title = source_title.strip()[numbered.end():].strip()
            else:
                title = source_title.strip()
            counters[level] += 1
            for deeper in range(level + 1, 7):
                counters[deeper] = 0
            number = ".".join(str(counters[item]) for item in range(2, level + 1))
            new_title = f"{number} {title}"

        new_slug_base = slugify_heading(new_title)
        new_count = new_duplicate_counts.get(new_slug_base, 0)
        new_duplicate_counts[new_slug_base] = new_count + 1
        new_slug = new_slug_base if new_count == 0 else f"{new_slug_base}-{new_count}"
        if old_slug != new_slug:
            if old_slug not in explicit_anchors:
                link_map.setdefault(old_slug, new_slug)
                output.append(f'<a id="{old_slug}"></a>')

        output.append(f"{indent}{hashes} {new_title}")
        index += 1
        if setext_level is not None:
            index += 1

    return "\n".join(output), link_map


def extract_headings(markdown: str) -> list[Heading]:
    source = _strip_generated_blocks(markdown)
    lines = source.splitlines()
    protected = _protected_lines(lines)
    duplicate_counts: dict[str, int] = {}
    headings: list[Heading] = []
    index = 0
    while index < len(lines):
        if protected[index]:
            index += 1
            continue
        match = _ATX.match(lines[index])
        title = None
        level = 0
        if match:
            level = len(match.group(2))
            title = match.group(3).strip()
        elif index + 1 < len(lines) and not protected[index + 1]:
            setext = _SETEXT.match(lines[index + 1])
            if setext and lines[index].strip():
                level = 1 if setext.group(1).startswith("=") else 2
                title = lines[index].strip()
        if title is None:
            index += 1
            continue
        slug_base = slugify_heading(title)
        count = duplicate_counts.get(slug_base, 0)
        duplicate_counts[slug_base] = count + 1
        slug = slug_base if count == 0 else f"{slug_base}-{count}"
        headings.append(Heading(index, level, title, slug, tuple(_STABLE_ID.findall(title))))
        index += 2 if not match else 1
    return headings


def _rewrite_target(target: str, source: Path, link_maps: dict[Path, dict[str, str]]) -> str:
    try:
        parsed = urlsplit(target)
    except ValueError:
        return target
    if parsed.scheme or parsed.netloc or not parsed.fragment:
        return target
    if parsed.path:
        candidate = (source.parent / unquote(parsed.path)).resolve()
    else:
        candidate = source.resolve()
    mapping = link_maps.get(candidate)
    if not mapping:
        return target
    replacement = mapping.get(unquote(parsed.fragment))
    if replacement is None:
        return target
    return urlunsplit(("", "", parsed.path, parsed.query, quote(replacement, safe="-._~")))


def _inline_code_ranges(line: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(line):
        if line[index] != _INLINE_CODE or (index > 0 and line[index - 1] == "\\"):
            index += 1
            continue
        run = 1
        while index + run < len(line) and line[index + run] == _INLINE_CODE:
            run += 1
        closer = line.find(_INLINE_CODE * run, index + run)
        if closer < 0:
            index += run
            continue
        ranges.append((index, closer + run))
        index = closer + run
    return ranges


def _inside(ranges: list[tuple[int, int]], point: int) -> bool:
    return any(start <= point < end for start, end in ranges)


def _rewrite_line(line: str, source: Path, link_maps: dict[Path, dict[str, str]]) -> str:
    code_ranges = _inline_code_ranges(line)
    changes: list[tuple[int, int, str]] = []
    for match in _LINK.finditer(line):
        if _inside(code_ranges, match.start()):
            continue
        raw_target = match.group("target")
        wrapped = raw_target.startswith("<") and raw_target.endswith(">")
        target = raw_target[1:-1] if wrapped else raw_target
        if target is None:
            continue
        rewritten = _rewrite_target(target, source, link_maps)
        if rewritten != target:
            replacement = f"<{rewritten}>" if wrapped else rewritten
            changes.append((match.start("target"), match.end("target"),
                            replacement))
    if changes:
        for start, end, value in reversed(changes):
            line = line[:start] + value + line[end:]

    definition = _REFERENCE.match(line)
    if definition and not _inside(code_ranges, definition.start(2)):
        target = definition.group(3) or definition.group(4)
        rewritten = _rewrite_target(target, source, link_maps)
        if rewritten != target:
            value = f"<{rewritten}>" if definition.group(3) is not None else rewritten
            line = line[:definition.start(2)] + value + line[definition.end(2):]
    return line


def rewrite_markdown_links(markdown: str, source: Path,
                           link_maps: dict[Path, dict[str, str]]) -> str:
    lines = markdown.splitlines()
    protected = _protected_lines(lines)
    output = [line if protected[index] else _rewrite_line(line, source, link_maps)
              for index, line in enumerate(lines)]
    return "\n".join(output)


def _contents_blocks(markdown: str) -> str:
    headings = extract_headings(markdown)
    toc = ["<!-- contents:start -->", "**Contents**"]
    for heading in headings:
        if heading.level < 2:
            continue
        indent = "  " * (heading.level - 2)
        label = heading.title.replace("]", r"\]")
        toc.append(f"{indent}- [{label}](#{heading.slug})")
    toc.append("<!-- contents:end -->")

    stable = ["<!-- heading-map:start -->", "**Stable heading map**"]
    for heading in headings:
        for stable_id in heading.stable_ids:
            stable.append(f"- [{stable_id}](#{stable_id.casefold()}) — {heading.title}")
    stable.append("<!-- heading-map:end -->")

    lines = markdown.splitlines()
    protected = _protected_lines(lines)
    first_h1 = next((heading for heading in headings if heading.level == 1), None)
    insertion = first_h1.line + 1 if first_h1 else 0
    if first_h1:
        next_heading = next((heading for heading in headings if heading.line > first_h1.line), None)
        insertion = next_heading.line if next_heading else len(lines)
    while insertion > 0 and (
        not protected[insertion - 1]
        and (_ANCHOR.fullmatch(lines[insertion - 1].strip())
             or not lines[insertion - 1].strip())
    ):
        insertion -= 1
    blocks = ["", *toc, "", *stable, ""]
    lines[insertion:insertion] = blocks
    return "\n".join(lines).rstrip() + "\n"


def format_markdown(markdown: str) -> FormattedMarkdown:
    clean = _strip_generated_blocks(markdown)
    body, link_map = _numbered_headings(clean)
    return FormattedMarkdown(_contents_blocks(body), link_map)


def _markdown_files(root: Path) -> list[Path]:
    docs = root / "docs"
    if docs.is_symlink():
        raise DocumentFormatError("refusing symlinked documentation root: docs")
    if not docs.is_dir():
        raise DocumentFormatError(f"documentation root does not exist: {docs}")
    files = sorted(docs.rglob("*.md"))
    symlinks = [path for path in files if path.is_symlink()]
    if symlinks:
        raise DocumentFormatError(f"refusing to format symlink: {symlinks[0].relative_to(root).as_posix()}")
    return files


def format_tree(root: Path, *, write: bool) -> tuple[str, ...]:
    root = root.resolve()
    files = _markdown_files(root)
    prepared: dict[Path, str] = {}
    link_maps: dict[Path, dict[str, str]] = {}
    originals: dict[Path, str] = {}
    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DocumentFormatError(f"cannot read UTF-8 Markdown {path.relative_to(root)}: {exc}") from exc
        resolved = path.resolve()
        originals[resolved] = original
        formatted = format_markdown(original)
        prepared[resolved] = _strip_generated_blocks(formatted.text)
        link_maps[resolved] = formatted.link_map

    changed: list[str] = []
    final_texts: dict[Path, str] = {}
    for path in files:
        resolved = path.resolve()
        rewritten = rewrite_markdown_links(prepared[resolved], resolved, link_maps)
        final = _contents_blocks(rewritten)
        final_texts[resolved] = final
        if final != originals[resolved]:
            changed.append(path.relative_to(root).as_posix())

    if write:
        for rel in changed:
            path = root / rel
            if path.is_symlink() or not path.is_file():
                raise DocumentFormatError(f"refusing to replace non-regular document: {rel}")
            mode = stat.S_IMODE(path.stat().st_mode)
            content = final_texts[path.resolve()].encode("utf-8")
            fd, temporary = tempfile.mkstemp(prefix=".pases-doc-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, mode)
                os.replace(temporary, path)
            except Exception:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
    return tuple(changed)
