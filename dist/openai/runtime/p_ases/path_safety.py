"""Workspace-scoped symbolic-link checks that tolerate OS path aliases."""

from __future__ import annotations

import os
from pathlib import Path


def path_has_symlink(path: Path, *, root: Path | None = None) -> bool:
    location = Path(os.path.abspath(path))
    if root is not None:
        anchor = Path(os.path.abspath(root))
        if anchor.is_symlink():
            return True
        try:
            relative = location.relative_to(anchor)
        except ValueError:
            return location.is_symlink() or location.parent.is_symlink()
        candidates = [anchor]
        current = anchor
        for part in relative.parts:
            current = current / part
            candidates.append(current)
        return any(candidate.is_symlink() for candidate in candidates)

    # Durable P-ASES state always lives below .p_ases. Stop there so trusted
    # system aliases such as macOS /var -> /private/var are not mistaken for
    # a workspace symlink. Generic standalone schema paths check their parent.
    candidates = [location]
    current = location
    has_workspace_state = ".p_ases" in location.parts
    while current != current.parent:
        current = current.parent
        candidates.append(current)
        if current.name == ".p_ases":
            break
        if not has_workspace_state and len(candidates) >= 2:
            break
    return any(candidate.is_symlink() for candidate in candidates)
