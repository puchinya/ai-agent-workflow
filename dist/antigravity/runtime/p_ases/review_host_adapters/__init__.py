"""Per-host native Independent Review capture adapters."""

from .claude_code import ClaudeCodeReviewAdapter
from .codex_cloud import CodexCloudReviewAdapter
from .codex_desktop import CodexDesktopReviewAdapter
from .codex_local_cli import CodexLocalCLIReviewAdapter

__all__ = [
    "ClaudeCodeReviewAdapter", "CodexCloudReviewAdapter",
    "CodexDesktopReviewAdapter", "CodexLocalCLIReviewAdapter",
]
