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

    def _paginate(self, endpoint: str, key: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            separator = "&" if "?" in endpoint else "?"
            response = self.request("GET", f"{endpoint}{separator}page={page}&per_page=100")
            if key is not None:
                if not isinstance(response, dict) or key not in response:
                    raise GitHubError(f"GitHub collection {endpoint} page {page} is missing {key}")
                selected = response[key]
            else:
                selected = response
            if not isinstance(selected, list) or any(not isinstance(item, dict) for item in selected):
                raise GitHubError(f"GitHub collection {endpoint} page {page} must contain an array of objects")
            items.extend(selected)
            if len(selected) < 100:
                return items
            page += 1

    def issue(self, number: int) -> dict[str, Any]:
        return self.request("GET", f"{self.prefix}/issues/{number}")

    def repository(self) -> dict[str, Any]:
        result = self.request("GET", self.prefix)
        if not isinstance(result, dict) or not isinstance(result.get("default_branch"), str) or not result["default_branch"]:
            raise GitHubError("GitHub repository metadata is missing default_branch")
        return result

    def milestones(self) -> list[dict[str, Any]]:
        return self._paginate(f"{self.prefix}/milestones?state=all")

    def create_milestone(self, title: str) -> dict[str, Any]:
        result = self.request("POST", f"{self.prefix}/milestones", {"title": title})
        if (not isinstance(result, dict) or result.get("title") != title
                or not isinstance(result.get("number"), int) or isinstance(result.get("number"), bool)
                or result.get("number") < 1 or result.get("state") != "open"):
            raise GitHubError("created GitHub milestone did not match the requested open milestone")
        return result

    def assign_issue_milestone(self, number: int, milestone: int) -> dict[str, Any]:
        result = self.request("PATCH", f"{self.prefix}/issues/{number}", {"milestone": milestone})
        if not isinstance(result, dict) or not isinstance(result.get("milestone"), dict):
            raise GitHubError("GitHub Issue milestone assignment was not confirmed")
        assigned_number = result["milestone"].get("number")
        if not isinstance(assigned_number, int) or isinstance(assigned_number, bool) or assigned_number != milestone:
            raise GitHubError("GitHub Issue milestone assignment did not match the requested milestone")
        return result

    def issue_comments(self, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"{self.prefix}/issues/{number}/comments")

    def issue_events(self, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"{self.prefix}/issues/{number}/events")

    def issue_comment(self, number: int, comment_id: int) -> dict[str, Any]:
        # Direct ID fetch avoids scanning or downloading unrelated comments.
        return self.request("GET", f"{self.prefix}/issues/comments/{comment_id}")

    def create_issue_comment(self, number: int, body: str) -> dict[str, Any]:
        return self.request("POST", f"{self.prefix}/issues/{number}/comments", {"body": body})

    def update_issue(self, number: int, body: str) -> dict[str, Any]:
        return self.request("PATCH", f"{self.prefix}/issues/{number}", {"body": body})

    def pull(self, number: int) -> dict[str, Any]:
        return self.request("GET", f"{self.prefix}/pulls/{number}")

    def open_pull_requests(self, head_branch: str, base_branch: str) -> list[dict[str, Any]]:
        """List open same-base PR candidates and filter exact head/base refs, including fork heads."""
        if (not isinstance(head_branch, str) or not head_branch or "\n" in head_branch or "\r" in head_branch
                or not isinstance(base_branch, str) or not base_branch or "\n" in base_branch or "\r" in base_branch):
            raise GitHubError("PR head and base branches must be non-empty single-line refs")
        candidates = self._paginate(
            f"{self.prefix}/pulls?state=open&base={quote(base_branch, safe='')}"
        )
        return [pull for pull in candidates
                if isinstance(pull.get("head"), dict) and isinstance(pull.get("base"), dict)
                and pull["head"].get("ref") == head_branch
                and pull["base"].get("ref") == base_branch]

    def create_pull_request(self, title: str, head: str, base: str, body: str) -> dict[str, Any]:
        result = self.request("POST", f"{self.prefix}/pulls", {
            "title": title, "head": head, "base": base, "body": body, "draft": False,
        })
        if (not isinstance(result, dict) or not isinstance(result.get("number"), int)
                or isinstance(result.get("number"), bool) or result.get("number") < 1
                or result.get("state") != "open" or result.get("draft") is not False):
            raise GitHubError("created PR did not match the requested open non-draft PR")
        return result

    def update_pull_request(self, number: int, title: str, body: str) -> dict[str, Any]:
        result = self.request("PATCH", f"{self.prefix}/pulls/{number}", {"title": title, "body": body})
        if (not isinstance(result, dict) or result.get("number") != number
                or result.get("title") != title or result.get("body") != body):
            raise GitHubError("updated PR did not match the requested title and body")
        return result

    def pull_comments(self, number: int) -> list[dict[str, Any]]:
        return self.request("GET", f"{self.prefix}/issues/{number}/comments?per_page=100")

    def pull_comment(self, comment_id: int) -> dict[str, Any]:
        return self.request("GET", f"{self.prefix}/issues/comments/{comment_id}")

    def create_pull_comment(self, number: int, body: str) -> dict[str, Any]:
        return self.request("POST", f"{self.prefix}/issues/{number}/comments", {"body": body})

    def update_pull(self, number: int, body: str) -> dict[str, Any]:
        return self.request("PATCH", f"{self.prefix}/pulls/{number}", {"body": body})

    def check_runs(self, ref: str) -> list[dict[str, Any]]:
        return self._paginate(f"{self.prefix}/commits/{quote(ref, safe='')}/check-runs", "check_runs")

    def statuses(self, ref: str) -> list[dict[str, Any]]:
        return self._paginate(f"{self.prefix}/commits/{quote(ref, safe='')}/statuses")

    def add_issue_label(self, number: int, label: str) -> None:
        self.request("POST", f"{self.prefix}/issues/{number}/labels", {"labels": [label]})

    def replace_issue_labels(self, number: int, labels: list[str]) -> list[dict[str, Any]]:
        if (not isinstance(labels, list) or any(not isinstance(label, str) or not label for label in labels)
                or len(set(labels)) != len(labels)):
            raise GitHubError("Issue label replacement requires unique non-empty label names")
        result = self.request("PUT", f"{self.prefix}/issues/{number}/labels", {"labels": labels})
        if (not isinstance(result, list) or any(not isinstance(label, dict) for label in result)
                or {label.get("name") for label in result} != set(labels)):
            raise GitHubError("Issue label replacement response did not match the requested labels")
        return result

    def remove_issue_label(self, number: int, label: str) -> None:
        self.request("DELETE", f"{self.prefix}/issues/{number}/labels/{quote(label, safe='')}")
