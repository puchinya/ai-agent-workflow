"""Resolved, read-only work context derived from a frozen ExecutionBinding."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .checkpoint import validate_ref
from .execution import (
    AdoptedExecutionEpoch, ExecutionBinding, ExecutionError, ExecutionIdentity,
    execution_identity_digest,
)


class WorkContextError(ValueError):
    pass


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class WorkContext:
    execution_identity: ExecutionIdentity
    current_head_sha40: str
    branch_ref: str
    worktree_clean: bool
    execution_identity_sha256: str

    def validate(self) -> "WorkContext":
        if not isinstance(self.execution_identity, (ExecutionBinding, AdoptedExecutionEpoch)):
            raise WorkContextError("WorkContext must reference a typed ExecutionBinding or adopted epoch")
        try:
            self.execution_identity.validate()
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
        if not isinstance(self.execution_identity_sha256, str) or not SHA256.fullmatch(self.execution_identity_sha256):
            raise WorkContextError("WorkContext execution identity digest is invalid")
        if self.execution_identity_sha256 != execution_identity_digest(self.execution_identity):
            raise WorkContextError("WorkContext digest does not match its typed execution identity")
        return self

    @property
    def execution_binding(self) -> ExecutionBinding:
        """Compatibility accessor for code that explicitly requires normal V1."""
        if not isinstance(self.execution_identity, ExecutionBinding):
            raise WorkContextError("adopted execution epoch is not a normal ExecutionBinding V1")
        return self.execution_identity

    @property
    def execution_binding_sha256(self) -> str | None:
        """Legacy read accessor; adopted epochs never masquerade as V1 bindings."""
        if not isinstance(self.execution_identity, ExecutionBinding):
            return None
        return self.execution_identity_sha256
