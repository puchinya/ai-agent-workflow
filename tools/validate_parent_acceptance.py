#!/usr/bin/env python3
"""Validate acceptance conditions that require the final parent migration cohort."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dist import EXPECTED_SKILLS  # noqa: E402
from validate_pases_traceability import validate as validate_traceability  # noqa: E402

PARENT_CANONICAL_SKILLS = (
    "request-intake", "adc-authoring", "adc-registry", "issue-decomposition",
    "product-specification", "technical-design", "test-specification", "work-execution",
    "verification-evidence", "acceptance-validation", "contract-audit", "independent-review",
    "user-review", "integration-validation", "delivery-control", "work-checkpoint",
)


def validate_skill_package(root: Path = ROOT) -> tuple[str, ...]:
    root = Path(root).resolve()
    errors: list[str] = []
    expected = set(EXPECTED_SKILLS)
    if tuple(EXPECTED_SKILLS) != PARENT_CANONICAL_SKILLS:
        errors.append("canonical distribution builder does not match the pinned 16-Skill architecture")
    canonical_root = root / "workflow/skills"
    try:
        canonical = {path.name for path in canonical_root.iterdir() if path.is_dir()}
    except OSError:
        canonical = set()
        errors.append("canonical workflow/skills directory is missing or unreadable")
    if canonical != expected:
        errors.append("canonical Skill directories do not match the distribution builder's exact set")
    for host in ("openai", "claude", "antigravity"):
        package_root = root / "dist" / host / "skills"
        try:
            packaged = {path.name for path in package_root.iterdir() if path.is_dir()}
        except OSError:
            packaged = set()
            errors.append(f"{host} Skill package is missing or unreadable")
        if packaged != expected:
            errors.append(f"{host} package does not contain the exact canonical Skill set")
    return tuple(errors)


def validate(root: Path, scope: str) -> tuple[str, ...]:
    if scope == "16-skills-package":
        return validate_skill_package(root)
    return validate_traceability(root, scope)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=("specification", "design", "test-oracle", "16-skills-package"))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    errors = validate(args.root, args.scope)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    print(f"{args.scope} acceptance validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
