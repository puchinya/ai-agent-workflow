"""Claude Code native task-result adapter.

Agent-writable Hook files are never treated as host-owned provenance.
"""

from .base import NativeReviewAdapter


class ClaudeCodeReviewAdapter(NativeReviewAdapter):
    surface = "claude_code"
