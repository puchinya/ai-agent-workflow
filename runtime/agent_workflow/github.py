"""Authenticated GitHub API transport. No other runtime module invokes `gh`."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from typing import Any


class GitHubError(RuntimeError):
    pass


def discover_repository(repo: Path) -> str:
    """Return owner/name from the origin remote, without exposing credentialed URLs."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, check=True,
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GitHubError("could not identify origin repository") from exc
    match = re.search(r"(?:github\.com[:/])([^/\s:]+/[^/\s]+?)(?:\.git)?$", url, re.I)
    if not match:
        raise GitHubError("origin is not a recognizable GitHub repository")
    return match.group(1)


@dataclass
class GitHub:
    repo: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo):
            raise GitHubError("repository must be owner/name")

    def request(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        if endpoint.startswith("/") or ".." in endpoint.split("/"):
            raise GitHubError("invalid GitHub API endpoint")
        argv = ["gh", "api", "--method", method.upper(), endpoint]
        input_text = None
        if payload is not None:
            argv.extend(["--input", "-"])
            # ASCII-escaped JSON is UTF-8/Windows-console independent; gh decodes it back to Unicode.
            input_text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        try:
            result = subprocess.run(argv, input=input_text, text=True, encoding="utf-8", errors="replace", check=False,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            raise GitHubError(f"could not start GitHub API client: {exc}") from exc
        if result.returncode:
            # gh stderr can include credentials or payload details; do not write it to logs.
            raise GitHubError(f"GitHub API {method.upper()} {endpoint} failed (gh exit status {result.returncode})")
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"GitHub API {method.upper()} {endpoint} returned invalid JSON") from exc

    @property
    def prefix(self) -> str:
        return f"repos/{self.repo}"

    def issue(self, number: int) -> dict[str, Any]:
        return self.request("GET", f"{self.prefix}/issues/{number}")

    def issue_comments(self, number: int) -> list[dict[str, Any]]:
        return self.request("GET", f"{self.prefix}/issues/{number}/comments?per_page=100")

    def issue_events(self, number: int) -> list[dict[str, Any]]:
        return self.request("GET", f"{self.prefix}/issues/{number}/events?per_page=100")

    def issue_comment(self, number: int, comment_id: int) -> dict[str, Any]:
        # Direct ID fetch avoids scanning or downloading unrelated comments.
        return self.request("GET", f"{self.prefix}/issues/comments/{comment_id}")

    def create_issue_comment(self, number: int, body: str) -> dict[str, Any]:
        return self.request("POST", f"{self.prefix}/issues/{number}/comments", {"body": body})

    def update_issue(self, number: int, body: str) -> dict[str, Any]:
        return self.request("PATCH", f"{self.prefix}/issues/{number}", {"body": body})

    def pull(self, number: int) -> dict[str, Any]:
        return self.request("GET", f"{self.prefix}/pulls/{number}")

    def pull_comments(self, number: int) -> list[dict[str, Any]]:
        return self.request("GET", f"{self.prefix}/issues/{number}/comments?per_page=100")

    def pull_comment(self, comment_id: int) -> dict[str, Any]:
        return self.request("GET", f"{self.prefix}/issues/comments/{comment_id}")

    def create_pull_comment(self, number: int, body: str) -> dict[str, Any]:
        return self.request("POST", f"{self.prefix}/issues/{number}/comments", {"body": body})

    def update_pull(self, number: int, body: str) -> dict[str, Any]:
        return self.request("PATCH", f"{self.prefix}/pulls/{number}", {"body": body})

    def check_runs(self, ref: str) -> list[dict[str, Any]]:
        result = self.request("GET", f"{self.prefix}/commits/{quote(ref, safe='')}/check-runs?per_page=100")
        return result.get("check_runs", [])

    def statuses(self, ref: str) -> list[dict[str, Any]]:
        result = self.request("GET", f"{self.prefix}/commits/{quote(ref, safe='')}/statuses?per_page=100")
        return result if isinstance(result, list) else []

    def add_issue_label(self, number: int, label: str) -> None:
        self.request("POST", f"{self.prefix}/issues/{number}/labels", {"labels": [label]})

    def remove_issue_label(self, number: int, label: str) -> None:
        self.request("DELETE", f"{self.prefix}/issues/{number}/labels/{quote(label, safe='')}")
