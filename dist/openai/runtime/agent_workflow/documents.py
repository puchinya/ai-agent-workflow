"""Offline validation and routing helpers for durable Markdown documents."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit


class DocumentError(ValueError):
    pass


MARKERS = {
    "specification": "<!-- agent-doc-type: specification -->",
    "design": "<!-- agent-doc-type: design -->",
}
REQUIRED_HEADINGS = {
    "specification": {"purpose", "scope", "normative requirements", "observable behavior",
                      "error and boundary behavior", "security and privacy", "verification strategy"},
    "design": {"context and goals", "requirements traceability", "architecture", "data flow and ownership",
                "failure handling", "alternatives considered", "verification strategy"},
}
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)")
_REF = re.compile(r"^\s*\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))", re.M)
_REF_USE = re.compile(r"(?<!!)\[([^\]]+)\]\s*\[([^\]]*)\]")


def without_fenced_blocks(text: str) -> str:
    output = []
    fence_char = None
    fence_len = 0
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence_char is None:
            if marker:
                fence_char = marker.group(1)[0]
                fence_len = len(marker.group(1))
                output.append("")
            else:
                output.append(line)
        elif marker and marker.group(1)[0] == fence_char and len(marker.group(1)) >= fence_len:
            fence_char = None
            fence_len = 0
            output.append("")
        else:
            output.append("")
    return "\n".join(output)


def _without_fences(text: str) -> str:
    return "\n".join(re.sub(r"(?<!`)`+[^\n]*?`+(?!`)", "", line)
                       for line in without_fenced_blocks(text).splitlines())


def _slug(heading: str) -> str:
    value = heading.lower().strip()
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"[^\w\-\s]", "", value, flags=re.UNICODE)
    return re.sub(r"\s+", "-", value)


def _anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    result = set()
    for line in without_fenced_blocks(text).splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        slug = _slug(match.group(1))
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def _link_target_matches(text: str) -> list[str]:
    clean = _without_fences(text)
    targets = []
    for match in _LINK.finditer(clean):
        targets.append(match.group(1) or match.group(2))
    for match in _REF.finditer(clean):
        targets.append(match.group(1) or match.group(2))
    return targets


def _reference_errors(text: str, rel: str) -> list[str]:
    clean = _without_fences(text)
    definitions = {}
    for match in re.finditer(r"^\s*\[([^\]]+)\]:\s*(?:<([^>]+)>|(\S+))", clean, re.M):
        definitions[re.sub(r"\s+", " ", match.group(1).strip().casefold())] = match.group(2) or match.group(3)
    errors = []
    for match in _REF_USE.finditer(clean):
        label = re.sub(r"\s+", " ", (match.group(2) or match.group(1)).strip().casefold())
        if label not in definitions:
            errors.append(f"{rel}: unresolved Markdown reference link: [{match.group(1)}][{match.group(2)}]")
    return errors


def validate_markdown_file(path: Path, repo: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{path.relative_to(repo).as_posix()}: cannot read UTF-8 Markdown ({exc})"]
    rel = path.relative_to(repo).as_posix()
    doc_type = "specification" if rel.startswith("docs/specs/") else "design" if rel.startswith("docs/design/") else None
    if doc_type:
        if MARKERS[doc_type] not in text.splitlines()[:3]:
            errors.append(f"{rel}: missing Schema-2 {doc_type} marker")
        if "<!-- agent-doc-schema: 2 -->" not in text.splitlines()[:3]:
            errors.append(f"{rel}: missing agent-doc-schema: 2 marker")
        headings = {m.group(1).strip().lower() for line in text.splitlines()
                    if (m := re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line))}
        for required in sorted(REQUIRED_HEADINGS[doc_type] - headings):
            errors.append(f"{rel}: missing required heading {required!r}")
    for raw in _link_target_matches(text):
        target = unquote(raw.strip())
        if not target:
            continue
        parts = urlsplit(target)
        if parts.scheme.lower() in {"http", "https", "mailto", "tel", "data", "ftp"} or parts.netloc:
            continue
        windows_target = PureWindowsPath(target)
        if windows_target.drive or windows_target.is_absolute() or parts.scheme:
            errors.append(f"{rel}: absolute or unsupported local link: {raw}")
            continue
        link_path = parts.path
        fragment = unquote(parts.fragment)
        if not link_path:
            target_path = path
        else:
            try:
                candidate = (path.parent / PurePosixPath(link_path)).resolve()
            except (OSError, ValueError):
                errors.append(f"{rel}: malformed local link: {raw}")
                continue
            if candidate != repo.resolve() and repo.resolve() not in candidate.parents:
                errors.append(f"{rel}: local link escapes repository: {raw}")
                continue
            target_path = candidate
        if target_path.is_dir():
            target_path = target_path / "README.md"
        if not target_path.is_file():
            errors.append(f"{rel}: broken local link: {raw}")
            continue
        if fragment and target_path.suffix.lower() == ".md":
            try:
                target_text = target_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if fragment not in _anchors(target_text):
                # `target_path` is resolved above; normalize `repo` too so diagnostics work
                # when the checkout is reached through a symlink or Windows short path.
                errors.append(f"{rel}: missing link fragment #{fragment} in {target_path.relative_to(repo.resolve()).as_posix()}")
    errors.extend(_reference_errors(text, rel))
    return errors


def validate_docs(repo: Path) -> list[str]:
    docs = repo / "docs"
    files = sorted(docs.rglob("*.md")) if docs.exists() else []
    return [error for path in files for error in validate_markdown_file(path, repo)]


def section_body(markdown: str, title: str) -> str | None:
    lines = markdown.splitlines()
    wanted = title.casefold().strip()
    start = None
    level = None
    fences = _without_fences(markdown).splitlines()
    for index, line in enumerate(fences):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match and match.group(2).casefold().strip() == wanted:
            start, level = index + 1, len(match.group(1))
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start, len(lines)):
        match = re.match(r"^(#{1,6})\s+", fences[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def resolve_document_impact(issue_body: str, repo: Path, repository: str | None = None) -> tuple[list[str], list[str], list[str]]:
    """Return existing owners, planned owners, and bounded diagnostics."""
    body = section_body(issue_body, "Document impact")
    if not body:
        return [], [], []
    links = _link_target_matches(body)
    errors: list[str] = []
    owners: list[str] = []
    planned: list[str] = []
    for raw in links:
        parsed = urlsplit(unquote(raw))
        if parsed.scheme or parsed.netloc:
            if parsed.netloc not in {"github.com", "www.github.com"}:
                errors.append(f"foreign document link ignored: {raw[:160]}")
                continue
            bits = parsed.path.strip("/").split("/")
            if len(bits) < 5 or bits[2] != "blob":
                errors.append(f"GitHub document link is not a same-repository file link: {raw[:160]}")
                continue
            if repository and "/".join(bits[:2]).lower() != repository.lower():
                errors.append(f"foreign repository document link ignored: {raw[:160]}")
                continue
            path_text = "/".join(bits[4:])
        else:
            path_text = parsed.path
        rel = PurePosixPath(path_text)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            errors.append(f"unsafe document path ignored: {raw[:160]}")
            continue
        parts = rel.parts
        if len(parts) < 3 or parts[0] != "docs" or parts[1] not in {"specs", "design", "status"} or rel.suffix != ".md":
            errors.append(f"document owner must be under docs/specs, docs/design, or docs/status: {raw[:160]}")
            continue
        name = rel.as_posix()
        try:
            dest = repo.joinpath(*parts).resolve()
        except (OSError, ValueError):
            errors.append(f"malformed document path ignored: {raw[:160]}")
            continue
        if repo.resolve() not in dest.parents:
            errors.append(f"document path escapes repository: {raw[:160]}")
        elif dest.is_file():
            owners.append(name)
        else:
            planned.append(name)
    return list(dict.fromkeys(owners)), list(dict.fromkeys(planned)), errors[:12]
