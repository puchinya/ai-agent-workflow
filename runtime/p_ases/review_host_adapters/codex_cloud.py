"""Codex Cloud native delegate/join result adapter."""

from .base import NativeReviewAdapter


class CodexCloudReviewAdapter(NativeReviewAdapter):
    surface = "codex_cloud"
