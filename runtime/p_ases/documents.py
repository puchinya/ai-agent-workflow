"""Validation for canonical specification, design, and test documents."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit

from .document_format import (
    DocumentFormatError, _LINK, _REFERENCE, _inline_code_ranges, _manual_anchors,
    _inside, extract_headings, format_tree,
)


class DocumentError(ValueError):
    pass


_DOC_MARKERS = {
    "specs": ("specification", {"purpose", "scope", "normative requirements",
                                "observable behavior", "error and boundary behavior",
                                "security and privacy"}),
    "design": ("design", {"context and goals", "requirements traceability", "architecture",
                           "data flow and ownership", "failure handling", "alternatives considered"}),
    "testing": ("test-specification", {"test purpose", "test conditions and oracles"}),
}
_ID = re.compile(r"^(REQ|DES|TST|ORA)-[A-Z0-9]+-\d{3}$")
_LINK_ID = re.compile(r"\[((?:REQ|DES|TST|ORA)-[A-Z0-9]+-\d{3})\]\(([^)]+)\)")
_FENCE = re.compile(r"^ {0,3}(" + re.escape(chr(96)) + r"{3,}|~{3,})")
_IMPACT_MATRIX_HEADER = ("REQ", "DES", "Oracle", "Test", "Evidence")


def _tree(path: Path, docs: Path) -> str | None:
    try:
        relative = path.relative_to(docs).parts
    except ValueError:
        return None
    return relative[0] if relative and relative[0] in _DOC_MARKERS else None


def _valid_local_links(path: Path, repo: Path) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        return [f"{path.relative_to(repo).as_posix()}: symlinked documentation is not allowed"]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{path.relative_to(repo).as_posix()}: cannot read UTF-8 Markdown ({exc})"]
    lines = text.splitlines()
    in_fence: str | None = None
    fence_length = 0
    in_comment = False
    reference_targets: list[str] = []
    inline_targets: list[str] = []
    for line in lines:
        marker = _FENCE.match(line)
        if in_fence is not None:
            if marker and marker.group(1)[0] == in_fence and len(marker.group(1)) >= fence_length:
                in_fence = None
                fence_length = 0
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if marker:
            in_fence = marker.group(1)[0]
            fence_length = len(marker.group(1))
            continue
        if "<!--" in line:
            if "-->" not in line[line.find("<!--") + 4:]:
                in_comment = True
            continue
        code_ranges = _inline_code_ranges(line)
        for match in _LINK.finditer(line):
            if _inside(code_ranges, match.start()):
                continue
            raw = match.group("target")
            inline_targets.append(raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw)
        reference = _REFERENCE.match(line)
        if reference and not _inside(code_ranges, reference.start(2)):
            reference_targets.append(reference.group(3) or reference.group(4))

    anchors: dict[Path, set[str]] = {}
    for raw in inline_targets + reference_targets:
        try:
            parsed = urlsplit(unquote(raw.strip()))
        except ValueError:
            errors.append(f"{path.relative_to(repo).as_posix()}: malformed Markdown link: {raw[:120]}")
            continue
        if parsed.scheme.lower() in {"http", "https", "mailto", "tel", "data", "ftp"} or parsed.netloc:
            continue
        target = unquote(parsed.path)
        windows_path = PureWindowsPath(target)
        if windows_path.is_absolute() or windows_path.drive or parsed.scheme:
            errors.append(f"{path.relative_to(repo).as_posix()}: absolute or unsupported local link: {raw[:120]}")
            continue
        if target:
            destination = (path.parent / PurePosixPath(target)).resolve()
        else:
            destination = path.resolve()
        if destination != repo.resolve() and repo.resolve() not in destination.parents:
            errors.append(f"{path.relative_to(repo).as_posix()}: local link escapes repository: {raw[:120]}")
            continue
        if destination.is_dir():
            destination = destination / "README.md"
        if not destination.is_file():
            errors.append(f"{path.relative_to(repo).as_posix()}: broken local link: {raw[:120]}")
            continue
        fragment = unquote(parsed.fragment)
        if fragment and destination.suffix.lower() == ".md":
            if destination not in anchors:
                try:
                    target_text = destination.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
                headings = {heading.slug for heading in extract_headings(target_text)}
                manual = _manual_anchors(target_text)
                anchors[destination] = headings | manual
            if fragment.casefold() not in anchors[destination]:
                errors.append(
                    f"{path.relative_to(repo).as_posix()}: missing link fragment #{fragment} "
                    f"in {destination.relative_to(repo).as_posix()}"
                )
    return errors


def validate_markdown_file(path: Path, repo: Path) -> list[str]:
    """Validate one package Markdown file's UTF-8 encoding and repository-local links."""
    repository = Path(repo)
    if repository.is_symlink() or not repository.is_dir():
        return ["Markdown repository root must be a regular directory"]
    root = repository.resolve()
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    source = source.absolute()
    try:
        relative = source.relative_to(root)
    except ValueError:
        return ["Markdown file must stay inside its repository root"]
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return [f"{relative.as_posix()}: symlinked Markdown path is not allowed"]
    if not current.is_file():
        return [f"{relative.as_posix()}: Markdown file is missing or not a regular file"]
    return _valid_local_links(current, root)


def _definitions(path: Path, repo: Path, docs: Path,
                 errors: list[str]) -> dict[str, Path]:
    definitions: dict[str, Path] = {}
    tree = _tree(path, docs)
    if tree is None:
        return definitions
    doc_type, required = _DOC_MARKERS[tree]
    rel = path.relative_to(repo).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{rel}: cannot read UTF-8 Markdown ({exc})")
        return definitions
    lines = text.splitlines()
    if f"<!-- agent-doc-type: {doc_type} -->" not in lines[:3]:
        errors.append(f"{rel}: missing agent-doc-type marker for {doc_type}")
    if "<!-- agent-doc-schema: 2 -->" not in lines[:3]:
        errors.append(f"{rel}: missing agent-doc-schema: 2 marker")
    headings = extract_headings(text)
    title = next((heading for heading in headings if heading.level == 1), None)
    if title is None:
        errors.append(f"{rel}: missing H1 title")
    heading_names = set()
    for heading in headings:
        name = re.sub(r"^\d+(?:\.\d+)*\s+", "", heading.title).strip()
        name = re.sub(r"^(?:REQ|DES|TST|ORA)-[A-Z0-9]+-\d{3}\s+", "", name)
        heading_names.add(name.casefold())
    for missing in sorted(required - heading_names):
        errors.append(f"{rel}: missing required heading {missing!r}")
    if tree == "specs" and any(heading.title.casefold().endswith("verification strategy")
                                for heading in headings):
        errors.append(f"{rel}: verification strategy belongs in docs/testing, not a product specification")
    expected_prefix = {"specs": "REQ", "design": "DES", "testing": None}[tree]
    for heading in headings:
        ids = re.findall(r"\b(?:REQ|DES|TST|ORA)-[A-Z0-9]+-\d{3}\b", heading.title)
        for stable_id in ids:
            prefix = stable_id.split("-", 1)[0]
            if not _ID.fullmatch(stable_id):
                errors.append(f"{rel}: malformed stable ID {stable_id}")
                continue
            if expected_prefix and prefix != expected_prefix:
                errors.append(f"{rel}: {stable_id} is in the wrong document tree")
            if tree == "testing" and prefix not in {"TST", "ORA"}:
                errors.append(f"{rel}: {stable_id} is in the wrong document tree")
            if stable_id in definitions:
                errors.append(f"{rel}: duplicate stable ID definition {stable_id}")
            else:
                definitions[stable_id] = path
            if stable_id.casefold() not in _manual_anchors(text):
                errors.append(f"{rel}: stable ID {stable_id} needs a manual anchor")
    return definitions


def _matrix_rows(path: Path, repo: Path, errors: list[str]) -> list[dict[str, str]]:
    rel = path.relative_to(repo).as_posix()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        errors.append(f"{rel}: cannot read traceability matrix ({exc})")
        return []
    rows: list[dict[str, str]] = []
    header_found = False
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        normalized = tuple(cell.casefold() for cell in cells)
        if normalized[:5] == tuple(item.casefold() for item in _IMPACT_MATRIX_HEADER):
            header_found = True
            continue
        if not header_found or not cells or set(cells[0]) <= {"-", ":"}:
            continue
        if len(cells) != 5:
            errors.append(f"{rel}: traceability row must contain exactly five cells")
            continue
        record: dict[str, str] = {}
        for key, cell in zip(("REQ", "DES", "ORA", "TST", "Evidence"), cells):
            if key == "Evidence":
                evidence = re.search(r"\[[^\]]+\]\(([^)]+)\)", cell)
                if not evidence:
                    errors.append(f"{rel}: matrix row has no linked evidence file")
                else:
                    record[key] = evidence.group(1)
                continue
            links = list(_LINK_ID.finditer(cell))
            if len(links) != 1:
                errors.append(f"{rel}: matrix row requires exactly one linked {key} ID")
                continue
            label, target = links[0].groups()
            expected = key if key != "ORA" else "ORA"
            if label.split("-", 1)[0] != expected:
                errors.append(f"{rel}: matrix {key} cell links the wrong stable ID type")
            fragment = unquote(urlsplit(target).fragment).casefold()
            if fragment != label.casefold():
                errors.append(f"{rel}: {label} link must use its stable ID fragment")
            record[key] = label
            record[f"{key}_target"] = target
        if len(record) >= 5:
            rows.append(record)
    if not header_found:
        errors.append(f"{rel}: missing REQ/DES/Oracle/Test/Evidence matrix")
    if not rows:
        errors.append(f"{rel}: traceability matrix has no data rows")
    return rows


def validate_documents(repo: Path) -> list[str]:
    repo = repo.resolve()
    docs = repo / "docs"
    errors: list[str] = []
    if docs.is_symlink():
        return ["docs/: symlinked documentation root is not allowed"]
    if not docs.is_dir():
        return ["docs/: canonical documentation root is missing"]
    markdown = sorted(docs.rglob("*.md"))
    definitions: dict[str, Path] = {}
    for path in markdown:
        errors.extend(_valid_local_links(path, repo))
        for stable_id, owner in _definitions(path, repo, docs, errors).items():
            if stable_id in definitions:
                errors.append(f"{path.relative_to(repo).as_posix()}: duplicate stable ID definition {stable_id}")
            else:
                definitions[stable_id] = owner

    matrix_path = docs / "testing" / "traceability.md"
    if not matrix_path.is_file():
        errors.append("docs/testing/traceability.md: traceability matrix is missing")
        rows = []
    else:
        rows = _matrix_rows(matrix_path, repo, errors)

    represented: dict[str, set[str]] = {key: set() for key in ("REQ", "DES", "ORA", "TST")}
    for row in rows:
        for key in ("REQ", "DES", "ORA", "TST"):
            stable_id = row.get(key)
            if stable_id:
                represented[key].add(stable_id)
                if stable_id not in definitions:
                    errors.append(f"docs/testing/traceability.md: undefined stable ID {stable_id}")
                target = row.get(f"{key}_target")
                if target:
                    parsed = urlsplit(target)
                    expected = ((matrix_path.parent / unquote(parsed.path)).resolve()
                                if parsed.path else matrix_path.resolve())
                    if stable_id in definitions and expected != definitions[stable_id].resolve():
                        errors.append(f"docs/testing/traceability.md: {stable_id} links to the wrong owner")
        evidence = row.get("Evidence")
        if evidence:
            parsed = urlsplit(evidence)
            evidence_path = (matrix_path.parent / unquote(parsed.path)).resolve()
            if not evidence_path.is_file():
                errors.append(f"docs/testing/traceability.md: evidence file does not exist: {evidence}")

    for stable_id in definitions:
        prefix = stable_id.split("-", 1)[0]
        key = "ORA" if prefix == "ORA" else prefix
        if stable_id not in represented.get(key, set()):
            errors.append(f"{definitions[stable_id].relative_to(repo).as_posix()}: {stable_id} is not traceable")

    try:
        drift = format_tree(repo, write=False)
    except DocumentFormatError as exc:
        errors.append(str(exc))
    else:
        for rel in drift:
            errors.append(f"{rel}: Markdown formatting drift; run docs format --write")
    return errors
