"""Local Codex CLI native child-agent result adapter."""

from .base import NativeReviewAdapter


class CodexLocalCLIReviewAdapter(NativeReviewAdapter):
    surface = "codex_local_cli"
