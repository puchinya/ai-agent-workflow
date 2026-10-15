#!/usr/bin/env python3
"""Check that canonical P-ASES requirements, designs, and test oracles are linked."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/testing/traceability.md"
LINK = re.compile(r"\[((?:REQ|DES|ORA|TST)-[A-Z][A-Z0-9]*-\d+)\]\(([^)]+)\)")
ANCHOR = re.compile(r'<a\s+id="([a-z0-9-]+)"\s*>', re.IGNORECASE)
ID_ANCHOR = re.compile(r"^(req|des|ora|tst)-[a-z][a-z0-9]*-\d+$", re.IGNORECASE)
SCOPES = {
    "specification": ("REQ", ROOT / "docs/specs"),
    "design": ("DES", ROOT / "docs/design"),
    "test-oracle": (("ORA", "TST"), ROOT / "docs/testing"),
}


def _source_ids(root: Path, prefixes: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for path in sorted(root.rglob("*.md")):
        if path == MATRIX:
            continue
        text = path.read_text(encoding="utf-8")
        for anchor in ANCHOR.findall(text):
            match = ID_ANCHOR.fullmatch(anchor)
            if match and match.group(1).upper() in prefixes:
                found.add(anchor.upper())
    return found


def validate(root: Path, scope: str) -> tuple[str, ...]:
    root = Path(root).resolve()
    matrix = root / "docs/testing/traceability.md"
    if scope not in SCOPES:
        return (f"unknown traceability scope: {scope}",)
    if not matrix.is_file():
        return ("canonical docs/testing/traceability.md is missing",)
    prefixes, source_root = SCOPES[scope]
    source_root = root / source_root.relative_to(ROOT)
    try:
        matrix_text = matrix.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return (f"traceability matrix is unreadable: {exc}",)

    refs: dict[str, list[tuple[str, Path, str]]] = {}
    errors: list[str] = []
    for line_number, line in enumerate(matrix_text.splitlines(), 1):
        if not line.startswith("|") or "---" in line or line.casefold().startswith("| req |"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            errors.append(f"traceability row {line_number} must have five columns")
            continue
        links = LINK.findall(line)
        if len(links) != 4:
            errors.append(f"traceability row {line_number} must link one REQ, DES, ORA, and TST")
            continue
        categories = [re.match(r"^(REQ|DES|ORA|TST)-", label).group(1) for label, _url in links]
        if categories != ["REQ", "DES", "ORA", "TST"]:
            errors.append(f"traceability row {line_number} has columns out of canonical order")
            continue
        evidence_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", cells[4])
        if not evidence_links:
            errors.append(f"traceability row {line_number} must link at least one executable evidence source")
        for label, url in links:
            category = label.split("-", 1)[0]
            refs.setdefault(category, []).append((label.upper(), matrix, url))
        for url in evidence_links:
            refs.setdefault("EVIDENCE", []).append(("test source", matrix, url))

    for category in ("REQ", "DES", "ORA", "TST"):
        for label, source, url in refs.get(category, []):
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path or not parsed.fragment:
                errors.append(f"{label} must use a relative file link with an explicit anchor")
                continue
            target = (source.parent / parsed.path).resolve()
            if root not in target.parents or not target.is_file():
                errors.append(f"{label} target is missing or outside the repository: {parsed.path}")
                continue
            try:
                target_text = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                errors.append(f"{label} target is unreadable: {parsed.path}")
                continue
            anchors = {item.casefold() for item in ANCHOR.findall(target_text)}
            if parsed.fragment.casefold() not in anchors:
                errors.append(f"{label} target anchor is missing: {parsed.fragment}")

    for _label, source, url in refs.get("EVIDENCE", []):
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            errors.append("test evidence source must be a relative file path without a fragment")
            continue
        target = (source.parent / parsed.path).resolve()
        if root not in target.parents or not target.is_file():
            errors.append(f"test evidence source is missing or outside the repository: {parsed.path}")

    required_prefixes = (prefixes,) if isinstance(prefixes, str) else prefixes
    for prefix in required_prefixes:
        linked = {label for label, _source, _url in refs.get(prefix, [])}
        actual = _source_ids(source_root, (prefix,))
        missing = actual - linked
        if missing:
            errors.append(f"traceability matrix omits {prefix} IDs: {', '.join(sorted(missing))}")
    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=tuple(SCOPES))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    errors = validate(args.root, args.scope)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    print(f"{args.scope} traceability is complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
