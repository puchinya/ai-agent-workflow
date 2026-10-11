"""Authenticated GitHub API transport. No other runtime module invokes gh."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any


class GitHubError(RuntimeError):
    pass


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise GitHubError(f"{label} must be a positive integer")
    return value


@dataclass
class GitHub:
    repo: str

    def __post_init__(self) -> None:
        if not isinstance(self.repo, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo
        ):
            raise GitHubError("repository must be owner/name")

    @property
    def prefix(self) -> str:
        return f"repos/{self.repo}"

    def request(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        verb = method.upper() if isinstance(method, str) else ""
        if verb not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
            raise GitHubError("unsupported GitHub API method")
        if (not isinstance(endpoint, str) or endpoint.startswith("/")
                or any(part in {"", ".", ".."} for part in endpoint.split("/"))
                or "\n" in endpoint or "\r" in endpoint):
            raise GitHubError("invalid GitHub API endpoint")
        argv = ["gh", "api", "--method", verb, endpoint]
        input_text = None
        if payload is not None:
            if not isinstance(payload, dict):
                raise GitHubError("GitHub API payload must be an object")
            argv.extend(["--input", "-"])
            input_text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        try:
            result = subprocess.run(
                argv, input=input_text, text=True, encoding="utf-8", errors="replace",
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise GitHubError(f"could not start GitHub API client: {exc}") from exc
        if result.returncode:
            # gh stderr may include credentials or payload values; never return it.
            raise GitHubError(f"GitHub API {verb} {endpoint} failed (gh exit status {result.returncode})")
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"GitHub API {verb} {endpoint} returned invalid JSON") from exc

    def _paginate(self, endpoint: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            separator = "&" if "?" in endpoint else "?"
            selected = self.request("GET", f"{endpoint}{separator}page={page}&per_page=100")
            if not isinstance(selected, list) or any(not isinstance(item, dict) for item in selected):
                raise GitHubError(f"GitHub collection {endpoint} page {page} must be an array of objects")
            items.extend(selected)
            if len(selected) < 100:
                return items
            page += 1

    def issue(self, number: int) -> dict[str, Any]:
        number = _positive_int(number, "Issue number")
        result = self.request("GET", f"{self.prefix}/issues/{number}")
        if not isinstance(result, dict):
            raise GitHubError("GitHub Issue response must be an object")
        return result

    def issue_comments(self, number: int) -> list[dict[str, Any]]:
        number = _positive_int(number, "Issue number")
        return self._paginate(f"{self.prefix}/issues/{number}/comments")

    def check_runs_for_ref(self, head_sha40: str) -> list[dict[str, Any]]:
        """Read every Check Run for an exact commit SHA; never fall back to statuses."""
        if not isinstance(head_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", head_sha40):
            raise GitHubError("Check Runs ref must be a full lowercase commit SHA")
        items: list[dict[str, Any]] = []
        page = 1
        total_count: int | None = None
        while True:
            result = self.request(
                "GET",
                f"{self.prefix}/commits/{head_sha40}/check-runs?filter=all&page={page}&per_page=100",
            )
            if not isinstance(result, dict):
                raise GitHubError(f"GitHub Check Runs page {page} must be an object")
            count = result.get("total_count")
            runs = result.get("check_runs")
            if (type(count) is not int or count < 0 or not isinstance(runs, list)
                    or any(not isinstance(run, dict) for run in runs)):
                raise GitHubError(f"GitHub Check Runs page {page} has an invalid response shape")
            if total_count is None:
                total_count = count
            elif total_count != count:
                raise GitHubError("GitHub Check Runs total_count changed during pagination")
            items.extend(runs)
            if len(runs) < 100:
                if len(items) < total_count:
                    raise GitHubError("GitHub Check Runs pagination ended before total_count")
                return items
            page += 1

    def issues(self) -> list[dict[str, Any]]:
        return self._paginate(f"{self.prefix}/issues?state=all")

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(title, str) or not title.strip() or any(c in title for c in "\x00\r\n"):
            raise GitHubError("new Issue title must be a non-empty single line")
        if not isinstance(body, str):
            raise GitHubError("new Issue body must be text")
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels is not None:
            if any(not isinstance(label, str) or not label for label in labels) or len(set(labels)) != len(labels):
                raise GitHubError("Issue labels must be unique non-empty strings")
            payload["labels"] = labels
        result = self.request("POST", f"{self.prefix}/issues", payload)
        if not isinstance(result, dict) or type(result.get("number")) is not int or result["number"] < 1:
            raise GitHubError("created Issue response is missing a valid number")
        return result

    def issue_comment(self, number: int, comment_id: int) -> dict[str, Any]:
        _positive_int(number, "Issue number")
        comment_id = _positive_int(comment_id, "Comment ID")
        result = self.request("GET", f"{self.prefix}/issues/comments/{comment_id}")
        if not isinstance(result, dict):
            raise GitHubError("GitHub Issue comment response must be an object")
        return result

    def create_issue_comment(self, number: int, body: str) -> dict[str, Any]:
        number = _positive_int(number, "Issue number")
        if not isinstance(body, str):
            raise GitHubError("Issue comment body must be text")
        result = self.request("POST", f"{self.prefix}/issues/{number}/comments", {"body": body})
        if not isinstance(result, dict) or type(result.get("id")) is not int or result["id"] < 1:
            raise GitHubError("created Issue comment response is missing a valid ID")
        return result

    def update_issue(self, number: int, body: str) -> dict[str, Any]:
        number = _positive_int(number, "Issue number")
        if not isinstance(body, str):
            raise GitHubError("Issue body must be text")
        result = self.request("PATCH", f"{self.prefix}/issues/{number}", {"body": body})
        if not isinstance(result, dict) or result.get("number") != number or result.get("body") != body:
            raise GitHubError("updated Issue body did not match the requested payload")
        return result

    def replace_issue_labels(self, number: int, labels: list[str]) -> list[dict[str, Any]]:
        number = _positive_int(number, "Issue number")
        if (not isinstance(labels, list) or any(not isinstance(label, str) or not label for label in labels)
                or len(set(labels)) != len(labels)):
            raise GitHubError("Issue label replacement requires unique non-empty names")
        result = self.request("PUT", f"{self.prefix}/issues/{number}/labels", {"labels": labels})
        if (not isinstance(result, list) or any(not isinstance(item, dict) for item in result)
                or {item.get("name") for item in result} != set(labels)):
            raise GitHubError("Issue label readback does not match the requested labels")
        return result

    def sub_issues(self, parent_number: int) -> list[dict[str, Any]]:
        parent_number = _positive_int(parent_number, "Parent Issue number")
        return self._paginate(f"{self.prefix}/issues/{parent_number}/sub_issues")

    def add_sub_issue(self, parent_number: int, child_issue_id: int) -> dict[str, Any]:
        parent_number = _positive_int(parent_number, "Parent Issue number")
        child_issue_id = _positive_int(child_issue_id, "Child Issue ID")
        current = self.sub_issues(parent_number)
        if any(item.get("id") == child_issue_id for item in current):
            return next(item for item in current if item.get("id") == child_issue_id)
        self.request("POST", f"{self.prefix}/issues/{parent_number}/sub_issues", {
            "sub_issue_id": child_issue_id,
        })
        readback = self.sub_issues(parent_number)
        matches = [item for item in readback if item.get("id") == child_issue_id]
        if len(matches) != 1:
            raise GitHubError("native Sub-issue relation was not confirmed by readback")
        return matches[0]

    def blocked_by(self, issue_number: int) -> list[dict[str, Any]]:
        issue_number = _positive_int(issue_number, "Issue number")
        return self._paginate(f"{self.prefix}/issues/{issue_number}/dependencies/blocked_by")

    def add_blocked_by(self, issue_number: int, blocking_issue_id: int) -> dict[str, Any]:
        issue_number = _positive_int(issue_number, "Issue number")
        blocking_issue_id = _positive_int(blocking_issue_id, "Blocking Issue ID")
        current = self.blocked_by(issue_number)
        if any(item.get("id") == blocking_issue_id for item in current):
            return next(item for item in current if item.get("id") == blocking_issue_id)
        self.request("POST", f"{self.prefix}/issues/{issue_number}/dependencies/blocked_by", {
            "issue_id": blocking_issue_id,
        })
        readback = self.blocked_by(issue_number)
        matches = [item for item in readback if item.get("id") == blocking_issue_id]
        if len(matches) != 1:
            raise GitHubError("Issue dependency was not confirmed by readback")
        return matches[0]
