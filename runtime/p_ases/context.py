"""Resolved, read-only work context derived from a frozen ExecutionBinding."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .checkpoint import validate_ref
from .execution import ExecutionBinding, ExecutionError, binding_digest


class WorkContextError(ValueError):
    pass


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class WorkContext:
    execution_binding: ExecutionBinding
    current_head_sha40: str
    branch_ref: str
    worktree_clean: bool
    execution_binding_sha256: str

    def validate(self) -> "WorkContext":
        if not isinstance(self.execution_binding, ExecutionBinding):
            raise WorkContextError("WorkContext must reference the frozen ExecutionBinding")
        try:
            self.execution_binding.validate()
        except ExecutionError as exc:
            raise WorkContextError(str(exc)) from exc
        if not isinstance(self.current_head_sha40, str) or not SHA40.fullmatch(self.current_head_sha40):
            raise WorkContextError("WorkContext current HEAD must be a full SHA-40")
        try:
            validate_ref(self.branch_ref)
        except ValueError as exc:
            raise WorkContextError(str(exc)) from exc
        if type(self.worktree_clean) is not bool:
            raise WorkContextError("WorkContext worktree_clean must be boolean")
        if not isinstance(self.execution_binding_sha256, str) or not SHA256.fullmatch(self.execution_binding_sha256):
            raise WorkContextError("WorkContext binding digest is invalid")
        if self.execution_binding_sha256 != binding_digest(self.execution_binding):
            raise WorkContextError("WorkContext binding digest does not match the frozen binding")
        return self
