#!/usr/bin/env python3
"""Package validated, unchanged distributions as deterministic GitHub assets."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import build_dist
import validate_dist

from agent_workflow import __version__


class PackageError(ValueError):
    pass


def validate_tag(tag: str) -> str:
    """Require stable SemVer without leading zeroes and canonical version equality."""
    if not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        raise PackageError(f"invalid release tag {tag!r}: expected stable SemVer vMAJOR.MINOR.PATCH")
    if tag[1:] != __version__:
        raise PackageError(f"tag version {tag[1:]} does not equal agent_workflow.__version__ {__version__}")
    return tag[1:]


def package(tag: str, output_dir: Path) -> list[Path]:
    validate_tag(tag)
    # Packaging must never regenerate or repair inputs, even when schemas validate.
    expected = build_dist.expected_files()
    errors = build_dist.check(expected)
    if errors:
        raise PackageError("distribution drift:\n" + "\n".join(errors))
    errors = validate_dist.validate()
    if errors:
        raise PackageError("distribution validation failed:\n" + "\n".join(errors))

    output_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    for host in build_dist.HOSTS:
        target = output_dir / f"ai-agent-workflow-{host}-{tag}.zip"
        prefix = f"dist/{host}/"
        with ZipFile(target, "w", compression=ZIP_STORED) as archive:
            for path in sorted(path for path in expected if path.startswith(prefix)):
                info = ZipInfo(path[len(prefix):], date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3  # Unix file type/permissions on every host.
                info.external_attr = 0o100644 << 16
                info.compress_type = ZIP_STORED  # Independent of zlib version.
                archive.writestr(info, expected[path])
        assets.append(target)
    checksums = output_dir / "SHA256SUMS"
    checksums.write_bytes("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(assets, key=lambda path: path.name)
    ).encode("utf-8"))
    return assets + [checksums]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        assets = package(args.tag, args.output_dir)
    except (PackageError, build_dist.BuildError, OSError) as exc:
        print(f"package error: {exc}", file=sys.stderr)
        return 1
    print("\n".join(str(path) for path in assets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
