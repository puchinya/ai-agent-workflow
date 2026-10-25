"""Authenticated GitHub API transport. No other runtime module invokes gh."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode


class GitHubError(RuntimeError):
    pass


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise GitHubError(f"{label} must be a positive integer")
    return value


@dataclass
class GitHub:
    repo: str
    _api_request_count: int = field(default=0, init=False, repr=False)
    _api_elapsed_ms: float = field(default=0.0, init=False, repr=False)

    @property
    def api_metrics(self) -> dict[str, int | float]:
        """Return in-process API call count and cumulative client-observed latency."""
        return {"api_calls": self._api_request_count, "elapsed_ms": round(self._api_elapsed_ms, 3)}

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
        started = time.perf_counter()
        self._api_request_count += 1
        try:
            result = subprocess.run(
                argv, input=input_text, text=True, encoding="utf-8", errors="replace",
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise GitHubError(f"could not start GitHub API client: {exc}") from exc
        finally:
            self._api_elapsed_ms += (time.perf_counter() - started) * 1000
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

    def repository_metadata(self) -> dict[str, Any]:
        result = self.request("GET", self.prefix)
        if not isinstance(result, dict) or not isinstance(result.get("default_branch"), str):
            raise GitHubError("GitHub repository metadata has no default branch")
        return result

    def issue_comments(self, number: int) -> list[dict[str, Any]]:
        number = _positive_int(number, "Issue number")
        return self._paginate(f"{self.prefix}/issues/{number}/comments")

    def repository_labels(self) -> list[dict[str, Any]]:
        """Read existing repository labels without creating or changing definitions."""
        return self._paginate(f"{self.prefix}/labels")

    def create_repository_label(self, name: str, color: str, description: str) -> dict[str, Any]:
        if (not isinstance(name, str) or not name or any(char in name for char in "\x00\r\n")
                or not isinstance(color, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", color)
                or not isinstance(description, str) or not description.strip()):
            raise GitHubError("repository label definition is invalid")
        result = self.request("POST", f"{self.prefix}/labels", {
            "name": name, "color": color.lower(), "description": description,
        })
        if (not isinstance(result, dict) or result.get("name") != name
                or not isinstance(result.get("color"), str)
                or result["color"].casefold() != color.casefold()
                or result.get("description") != description):
            raise GitHubError("created repository label did not match its requested definition")
        return result

    def pull_requests_for_refs(self, *, base_ref: str, head_ref: str) -> list[dict[str, Any]]:
        """Read all PRs matching exact same-repository head/base refs, including closed ones."""
        if (not isinstance(base_ref, str) or not base_ref or any(c in base_ref for c in "\x00\r\n")
                or not isinstance(head_ref, str) or not head_ref or any(c in head_ref for c in "\x00\r\n")):
            raise GitHubError("PR search requires non-empty base and head refs")
        owner, _name = self.repo.split("/", 1)
        query = urlencode({"state": "all", "base": base_ref, "head": f"{owner}:{head_ref}"})
        return self._paginate(f"{self.prefix}/pulls?{query}")

    def pull_request(self, number: int) -> dict[str, Any]:
        number = _positive_int(number, "PR number")
        result = self.request("GET", f"{self.prefix}/pulls/{number}")
        if not isinstance(result, dict) or result.get("number") != number:
            raise GitHubError("GitHub PR readback is missing or has a mismatched number")
        return result

    def pull_request_files(self, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"{self.prefix}/pulls/{_positive_int(number, 'PR number')}/files")

    def collaborator_permission(self, login: str) -> dict[str, Any]:
        if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]+", login):
            raise GitHubError("collaborator login is invalid")
        result = self.request("GET", f"{self.prefix}/collaborators/{quote(login, safe='')}/permission")
        user = result.get("user") if isinstance(result, dict) else None
        if (not isinstance(result, dict) or result.get("permission") not in
                {"admin", "maintain", "write", "triage", "read"}
                or not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] < 1
                or not isinstance(user.get("login"), str) or user["login"].casefold() != login.casefold()
                or user.get("type") != "User"):
            raise GitHubError("collaborator permission response is incomplete or mismatched")
        return result

    def create_pull_request(self, *, title: str, body: str, head_ref: str, base_ref: str) -> dict[str, Any]:
        if not isinstance(title, str) or not title.strip() or any(c in title for c in "\x00\r\n"):
            raise GitHubError("new PR title must be a non-empty single line")
        if not isinstance(body, str) or not isinstance(head_ref, str) or not isinstance(base_ref, str):
            raise GitHubError("new PR body and refs must be text")
        owner, _name = self.repo.split("/", 1)
        result = self.request("POST", f"{self.prefix}/pulls", {
            "title": title, "body": body, "head": f"{owner}:{head_ref}", "base": base_ref,
            "draft": False,
        })
        if not isinstance(result, dict) or type(result.get("number")) is not int or result["number"] < 1:
            raise GitHubError("created PR response is missing a valid number")
        return result

    def pull_reviews(self, number: int) -> list[dict[str, Any]]:
        """Paginate formal GitHub PR reviews, preserving actor/commit/edit state."""
        number = _positive_int(number, "PR number")
        return self._paginate(f"{self.prefix}/pulls/{number}/reviews")

    def pull_diff_comments(self, number: int) -> list[dict[str, Any]]:
        """Paginate inline PR discussion comments (not plain conversation comments)."""
        number = _positive_int(number, "PR number")
        return self._paginate(f"{self.prefix}/pulls/{number}/comments")

    def pull_conversation_comments(self, number: int) -> list[dict[str, Any]]:
        """PR conversation comments use GitHub Issues comments API."""
        number = _positive_int(number, "PR number")
        return self.issue_comments(number)

    def authenticated_user(self) -> dict[str, Any]:
        """Read the authenticated human identity; caller-supplied IDs are never authority."""
        result = self.request("GET", "user")
        if (not isinstance(result, dict) or type(result.get("id")) is not int or result["id"] < 1
                or not isinstance(result.get("login"), str) or result.get("type") != "User"):
            raise GitHubError("authenticated GitHub identity is missing or is not a human User")
        return result

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or not isinstance(variables, dict):
            raise GitHubError("GitHub GraphQL query inputs are invalid")
        body = json.dumps({"query": query, "variables": variables}, separators=(",", ":"))
        try:
            result = subprocess.run(
                ["gh", "api", "graphql", "--input", "-"], input=body, text=True,
                encoding="utf-8", errors="replace", check=False,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise GitHubError(f"could not start GitHub GraphQL client: {exc}") from exc
        if result.returncode:
            raise GitHubError(f"GitHub GraphQL request failed (gh exit status {result.returncode})")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError("GitHub GraphQL returned invalid JSON") from exc
        if not isinstance(value, dict) or value.get("errors") or not isinstance(value.get("data"), dict):
            raise GitHubError("GitHub GraphQL response is incomplete or contains errors")
        return value["data"]

    def pull_review_threads(self, number: int) -> list[dict[str, Any]]:
        """Read every review thread/comment, including resolution and outdated state."""
        number = _positive_int(number, "PR number")
        owner, name = self.repo.split("/", 1)
        thread_query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String){
          repository(owner:$owner,name:$name){pullRequest(number:$number){
            reviewThreads(first:100,after:$cursor){nodes{id isResolved isOutdated
              comments(first:100){nodes{databaseId body createdAt updatedAt path author{login __typename ... on User {databaseId} ... on Bot {databaseId}} commit{oid}}
                pageInfo{hasNextPage endCursor}}
            } pageInfo{hasNextPage endCursor}
          }}}
        }"""
        comment_query = """query($threadId:ID!,$cursor:String){node(id:$threadId){... on PullRequestReviewThread{
          comments(first:100,after:$cursor){nodes{databaseId body createdAt updatedAt path author{login __typename ... on User {databaseId} ... on Bot {databaseId}} commit{oid}}
            pageInfo{hasNextPage endCursor}}}}}"""
        threads: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            data = self._graphql(thread_query, {"owner": owner, "name": name,
                                                "number": number, "cursor": cursor})
            repository = data.get("repository")
            pr = repository.get("pullRequest") if isinstance(repository, dict) else None
            connection = pr.get("reviewThreads") if isinstance(pr, dict) else None
            nodes = connection.get("nodes") if isinstance(connection, dict) else None
            page = connection.get("pageInfo") if isinstance(connection, dict) else None
            if not isinstance(nodes, list) or any(not isinstance(row, dict) for row in nodes) or not isinstance(page, dict):
                raise GitHubError("GitHub review-thread page is incomplete")
            for thread in nodes:
                if (not isinstance(thread.get("id"), str) or type(thread.get("isResolved")) is not bool
                        or type(thread.get("isOutdated")) is not bool):
                    raise GitHubError("GitHub review thread identity/state is incomplete")
                comments = thread.get("comments")
                if not isinstance(comments, dict) or not isinstance(comments.get("nodes"), list):
                    raise GitHubError("GitHub review-thread comments are incomplete")
                rows = list(comments["nodes"])
                comment_page = comments.get("pageInfo")
                while isinstance(comment_page, dict) and comment_page.get("hasNextPage") is True:
                    next_cursor = comment_page.get("endCursor")
                    if not isinstance(next_cursor, str) or not next_cursor:
                        raise GitHubError("GitHub review-thread comment cursor is missing")
                    more_data = self._graphql(comment_query, {"threadId": thread["id"], "cursor": next_cursor})
                    node = more_data.get("node")
                    more = node.get("comments") if isinstance(node, dict) else None
                    if (not isinstance(more, dict) or not isinstance(more.get("nodes"), list)
                            or not isinstance(more.get("pageInfo"), dict)):
                        raise GitHubError("GitHub review-thread comment page is incomplete")
                    rows.extend(more["nodes"])
                    comment_page = more["pageInfo"]
                if any(not isinstance(row, dict) for row in rows):
                    raise GitHubError("GitHub review-thread comment row is malformed")
                threads.append({**thread, "comments": rows})
            if page.get("hasNextPage") is not True:
                break
            cursor = page.get("endCursor")
            if not isinstance(cursor, str) or not cursor:
                raise GitHubError("GitHub review-thread cursor is missing")
        return threads

    def pull_review_decision(self, number: int) -> dict[str, Any]:
        """Read GitHub's aggregate formal review decision from its authoritative PR object."""
        number = _positive_int(number, "PR number")
        owner, name = self.repo.split("/", 1)
        query = """query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){
          pullRequest(number:$number){number reviewDecision headRefOid baseRefName isDraft state}}}"""
        data = self._graphql(query, {"owner": owner, "name": name, "number": number})
        repository = data.get("repository")
        pr = repository.get("pullRequest") if isinstance(repository, dict) else None
        if (not isinstance(pr, dict) or pr.get("number") != number
                or pr.get("reviewDecision") not in {"APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED", None}
                or not isinstance(pr.get("headRefOid"), str)):
            raise GitHubError("GitHub aggregate review decision readback is incomplete")
        return pr

    def branch_protection(self, branch: str) -> dict[str, Any]:
        if not isinstance(branch, str) or not branch or any(char in branch for char in "\x00\r\n"):
            raise GitHubError("branch protection lookup requires a branch name")
        result = self.request("GET", f"{self.prefix}/branches/{quote(branch, safe='')}/protection")
        if not isinstance(result, dict):
            raise GitHubError("branch protection response must be an object")
        return result

    def branch(self, branch: str) -> dict[str, Any]:
        if not isinstance(branch, str) or not branch or any(char in branch for char in "\x00\r\n"):
            raise GitHubError("branch lookup requires a branch name")
        result = self.request("GET", f"{self.prefix}/branches/{quote(branch, safe='')}")
        if (not isinstance(result, dict) or not isinstance(result.get("commit"), dict)
                or not isinstance(result["commit"].get("sha"), str)):
            raise GitHubError("GitHub branch response is incomplete")
        return result

    def compare_commits(self, base_sha40: str, head_sha40: str) -> dict[str, Any]:
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)
               for value in (base_sha40, head_sha40)):
            raise GitHubError("commit comparison requires full SHA-40 values")
        result = self.request("GET", f"{self.prefix}/compare/{base_sha40}...{head_sha40}")
        if not isinstance(result, dict) or result.get("status") not in {"ahead", "behind", "identical", "diverged"}:
            raise GitHubError("GitHub commit comparison response is incomplete")
        return result

    def pull_requests_all(self) -> list[dict[str, Any]]:
        """Read full PR set for exact parent-integration merge evidence."""
        return self._paginate(f"{self.prefix}/pulls?state=all")

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
            for run in runs:
                app = run.get("app")
                if (type(run.get("id")) is not int or run["id"] < 1
                        or not isinstance(run.get("name"), str) or not run["name"]
                        or run.get("head_sha") != head_sha40
                        or not isinstance(app, dict) or type(app.get("id")) is not int or app["id"] < 1):
                    raise GitHubError(f"GitHub Check Runs page {page} contains incomplete identity/provenance")
            items.extend(runs)
            if len(runs) < 100:
                if len(items) != total_count:
                    raise GitHubError("GitHub Check Runs pagination count does not match total_count")
                ids = [run["id"] for run in items]
                if len(ids) != len(set(ids)):
                    raise GitHubError("GitHub Check Runs pagination contains duplicate run IDs")
                return items
            page += 1

    def check_run(self, check_run_id: int) -> dict[str, Any]:
        """Read one historical Check Run by its immutable GitHub ID."""
        if type(check_run_id) is not int or check_run_id < 1:
            raise GitHubError("Check Run ID must be a positive integer")
        result = self.request("GET", f"{self.prefix}/check-runs/{check_run_id}")
        app = result.get("app") if isinstance(result, dict) else None
        if (not isinstance(result, dict) or result.get("id") != check_run_id
                or not isinstance(result.get("name"), str) or not result["name"]
                or not isinstance(result.get("head_sha"), str)
                or not isinstance(app, dict) or type(app.get("id")) is not int or app["id"] < 1):
            raise GitHubError("GitHub Check Run resource has incomplete identity/provenance")
        return result

    def workflow_job(self, job_id: int) -> dict[str, Any]:
        """Read one Actions job by its immutable ID, including its creation time."""
        job_id = _positive_int(job_id, "Workflow job ID")
        result = self.request("GET", f"{self.prefix}/actions/jobs/{job_id}")
        check_run_url = f"https://api.github.com/{self.prefix}/check-runs/{job_id}"
        if (not isinstance(result, dict) or result.get("id") != job_id
                or type(result.get("run_id")) is not int or result["run_id"] < 1
                or type(result.get("run_attempt")) is not int or result["run_attempt"] < 1
                or not isinstance(result.get("name"), str) or not result["name"]
                or not isinstance(result.get("head_sha"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", result["head_sha"])
                or not isinstance(result.get("check_run_url"), str)
                or result["check_run_url"].casefold() != check_run_url.casefold()
                or not isinstance(result.get("created_at"), str)
                or not result["created_at"]
                or not isinstance(result.get("status"), str)
                or (result.get("conclusion") is not None and not isinstance(result.get("conclusion"), str))
                or (result.get("started_at") is not None and not isinstance(result.get("started_at"), str))
                or (result.get("completed_at") is not None and not isinstance(result.get("completed_at"), str))):
            raise GitHubError("GitHub Actions job resource has incomplete or mismatched identity data")
        return result

    def workflow_job_for_check_run(self, check_run: dict[str, Any]) -> dict[str, Any]:
        """Resolve an Actions job only when it is the exact job linked to a Check Run."""
        if not isinstance(check_run, dict):
            raise GitHubError("Check Run resource must be an object")
        check_run_id = _positive_int(check_run.get("id"), "Check Run ID")
        job = self.workflow_job(check_run_id)
        identity_fields = ("name", "head_sha", "status", "conclusion", "started_at", "completed_at")
        if any(job.get(field) != check_run.get(field) for field in identity_fields):
            raise GitHubError("GitHub Actions job does not match the Check Run identity or result")
        return job

    def workflow_runs_for_ref(
        self, head_sha40: str, *, workflow_path: str = ".github/workflows/ci.yml",
        event: str = "pull_request",
    ) -> list[dict[str, Any]]:
        """Read all runs for an exact SHA, workflow path, and GitHub event."""
        if not isinstance(head_sha40, str) or not re.fullmatch(r"[0-9a-f]{40}", head_sha40):
            raise GitHubError("workflow run ref must be a full lowercase commit SHA")
        if (not isinstance(workflow_path, str) or not workflow_path.startswith(".github/workflows/")
                or any(char in workflow_path for char in "\x00\r\n?#")):
            raise GitHubError("workflow path is invalid")
        if not isinstance(event, str) or event not in {"pull_request", "push", "workflow_dispatch"}:
            raise GitHubError("workflow event is not supported for evidence readback")
        from urllib.parse import quote, urlencode
        workflow_id = workflow_path.rsplit("/", 1)[-1]
        encoded_path = quote(workflow_id, safe="._-")
        query = urlencode({"head_sha": head_sha40, "event": event, "per_page": 100})
        endpoint = f"{self.prefix}/actions/workflows/{encoded_path}/runs?{query}"
        items: list[dict[str, Any]] = []
        page = 1
        total_count: int | None = None
        while True:
            result = self.request("GET", f"{endpoint}&page={page}")
            if not isinstance(result, dict):
                raise GitHubError(f"GitHub workflow runs page {page} must be an object")
            count, runs = result.get("total_count"), result.get("workflow_runs")
            if (type(count) is not int or count < 0 or not isinstance(runs, list)
                    or any(not isinstance(run, dict) for run in runs)):
                raise GitHubError(f"GitHub workflow runs page {page} has an invalid response shape")
            if total_count is None:
                total_count = count
            elif total_count != count:
                raise GitHubError("GitHub workflow runs total_count changed during pagination")
            for run in runs:
                head_repo = run.get("head_repository")
                if (type(run.get("id")) is not int or run["id"] < 1
                        or type(run.get("run_number")) is not int or run["run_number"] < 1
                        or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1
                        or run.get("path") != workflow_path or run.get("head_sha") != head_sha40
                        or run.get("event") != event
                        or not isinstance(run.get("status"), str)
                        or (run.get("conclusion") is not None and not isinstance(run.get("conclusion"), str))
                        or not isinstance(run.get("head_branch"), str) or not run["head_branch"]
                        or not isinstance(head_repo, dict)
                        or not isinstance(head_repo.get("full_name"), str)
                        or (event == "pull_request" and not isinstance(run.get("pull_requests"), list))):
                    raise GitHubError(f"GitHub workflow run page {page} contains incomplete identity data")
            items.extend(runs)
            if len(runs) < 100:
                if len(items) != total_count:
                    raise GitHubError("GitHub workflow run pagination count does not match total_count")
                ids = [run["id"] for run in items]
                if len(ids) != len(set(ids)):
                    raise GitHubError("GitHub workflow run pagination contains duplicate IDs")
                return items
            page += 1

    def workflow_run_attempt(self, run_id: int, attempt_number: int) -> dict[str, Any]:
        """Read one exact historical or current attempt for a workflow run."""
        run_id = _positive_int(run_id, "Workflow run ID")
        attempt_number = _positive_int(attempt_number, "Workflow run attempt")
        result = self.request(
            "GET", f"{self.prefix}/actions/runs/{run_id}/attempts/{attempt_number}",
        )
        repository = result.get("head_repository") if isinstance(result, dict) else None
        if (not isinstance(result, dict) or type(result.get("id")) is not int or result["id"] != run_id
                or type(result.get("run_number")) is not int or result["run_number"] < 1
                or type(result.get("run_attempt")) is not int
                or result["run_attempt"] != attempt_number
                or not isinstance(result.get("path"), str) or not result["path"].startswith(".github/workflows/")
                or result.get("event") not in {"push", "workflow_dispatch", "pull_request"}
                or not isinstance(result.get("head_sha"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", result["head_sha"])
                or not isinstance(result.get("head_branch"), str) or not result["head_branch"]
                or not isinstance(result.get("status"), str)
                or (result.get("conclusion") is not None and not isinstance(result.get("conclusion"), str))
                or not isinstance(repository, dict)
                or not isinstance(repository.get("full_name"), str) or not repository["full_name"]):
            raise GitHubError("GitHub workflow attempt response has incomplete or mismatched identity data")
        return result

    def workflow_run_jobs(self, run_id: int, attempt_number: int | None = None) -> list[dict[str, Any]]:
        """Read every job and step for the latest run or one exact attempt."""
        run_id = _positive_int(run_id, "Workflow run ID")
        if attempt_number is not None:
            attempt_number = _positive_int(attempt_number, "Workflow run attempt")
            endpoint = f"{self.prefix}/actions/runs/{run_id}/attempts/{attempt_number}/jobs"
        else:
            endpoint = f"{self.prefix}/actions/runs/{run_id}/jobs"
        items: list[dict[str, Any]] = []
        page = 1
        total_count: int | None = None
        while True:
            result = self.request(
                "GET", f"{endpoint}?page={page}&per_page=100",
            )
            if not isinstance(result, dict):
                raise GitHubError(f"GitHub workflow jobs page {page} must be an object")
            count, jobs = result.get("total_count"), result.get("jobs")
            if (type(count) is not int or count < 0 or not isinstance(jobs, list)
                    or any(not isinstance(job, dict) for job in jobs)):
                raise GitHubError(f"GitHub workflow jobs page {page} has an invalid response shape")
            if total_count is None:
                total_count = count
            elif total_count != count:
                raise GitHubError("GitHub workflow jobs total_count changed during pagination")
            for job in jobs:
                steps = job.get("steps")
                if (type(job.get("id")) is not int or job["id"] < 1
                        or not isinstance(job.get("name"), str) or not job["name"]
                        or job.get("run_id") != run_id
                        or not isinstance(job.get("status"), str)
                        or (job.get("conclusion") is not None and not isinstance(job.get("conclusion"), str))
                        or not isinstance(job.get("check_run_url"), str)
                        or not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps)):
                    raise GitHubError(f"GitHub workflow jobs page {page} contains incomplete identity data")
                for step in steps:
                    if (type(step.get("number")) is not int or step["number"] < 1
                            or not isinstance(step.get("name"), str) or not step["name"]
                            or not isinstance(step.get("status"), str)
                            or (step.get("conclusion") is not None and not isinstance(step.get("conclusion"), str))):
                        raise GitHubError(f"GitHub workflow job {job['id']} has an incomplete step")
            items.extend(jobs)
            if len(jobs) < 100:
                if len(items) != total_count:
                    raise GitHubError("GitHub workflow jobs pagination count does not match total_count")
                ids = [job["id"] for job in items]
                if len(ids) != len(set(ids)):
                    raise GitHubError("GitHub workflow jobs pagination contains duplicate IDs")
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

    def content_at_ref(self, path: str, ref: str) -> bytes:
        """Read one regular repository file at an exact commit and verify its Git blob ID."""
        if (not isinstance(path, str) or not path or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(char in path for char in "\\\x00\r\n?#:")):
            raise GitHubError("evidence content path is invalid")
        if not isinstance(ref, str) or not re.fullmatch(r"[0-9a-f]{40}", ref):
            raise GitHubError("evidence content ref must be a full commit SHA")
        endpoint = f"{self.prefix}/contents/{quote(path, safe='/')}?ref={ref}"
        result = self.request("GET", endpoint)
        if (not isinstance(result, dict) or result.get("path") != path or result.get("type") != "file"
                or result.get("encoding") != "base64" or not isinstance(result.get("content"), str)
                or not isinstance(result.get("sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", result["sha"])):
            raise GitHubError("evidence content readback is incomplete or not a regular file")
        try:
            encoded = re.sub(r"\s+", "", result["content"])
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise GitHubError("evidence content encoding is invalid") from exc
        git_blob_sha = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\x00" + content).hexdigest()
        if git_blob_sha != result["sha"]:
            raise GitHubError("evidence content does not match its Git blob ID")
        return content

    def regular_blob_sha_at_ref(self, path: str, ref: str) -> str:
        """Resolve one Git tree path and reject symlinks, submodules, and non-files."""
        if (not isinstance(path, str) or not path or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(char in path for char in "\\\x00\r\n?#:")):
            raise GitHubError("evidence content path is invalid")
        if not isinstance(ref, str) or not re.fullmatch(r"[0-9a-f]{40}", ref):
            raise GitHubError("evidence content ref must be a full commit SHA")
        commit = self.request("GET", f"{self.prefix}/git/commits/{ref}")
        tree_ref = commit.get("tree", {}).get("sha") if isinstance(commit, dict) and isinstance(
            commit.get("tree"), dict) else None
        if not isinstance(tree_ref, str) or not re.fullmatch(r"[0-9a-f]{40}", tree_ref):
            raise GitHubError("evidence commit tree readback is incomplete")
        parts = path.split("/")
        for index, part in enumerate(parts):
            tree = self.request("GET", f"{self.prefix}/git/trees/{tree_ref}")
            entries = tree.get("tree") if isinstance(tree, dict) else None
            if (not isinstance(entries, list) or tree.get("truncated") is True
                    or any(not isinstance(row, dict) for row in entries)):
                raise GitHubError("evidence Git tree readback is incomplete or truncated")
            matches = [row for row in entries if row.get("path") == part]
            if len(matches) != 1:
                raise GitHubError("evidence Git tree path is missing or ambiguous")
            entry = matches[0]
            is_leaf = index == len(parts) - 1
            if is_leaf:
                if entry.get("type") != "blob" or entry.get("mode") not in {"100644", "100755"}:
                    raise GitHubError("evidence path is not a regular file (symlinks and submodules are forbidden)")
                sha = entry.get("sha")
                if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
                    raise GitHubError("evidence Git blob SHA is malformed")
                return sha
            if entry.get("type") != "tree" or entry.get("mode") != "040000":
                raise GitHubError("evidence path contains a non-directory component")
            tree_ref = entry.get("sha")
            if not isinstance(tree_ref, str) or not re.fullmatch(r"[0-9a-f]{40}", tree_ref):
                raise GitHubError("evidence Git subtree SHA is malformed")
        raise GitHubError("evidence Git tree path is incomplete")

    def regular_content_at_ref(self, path: str, ref: str) -> bytes:
        """Read content only when the exact commit tree marks its path as a regular blob."""
        expected_sha = self.regular_blob_sha_at_ref(path, ref)
        content = self.content_at_ref(path, ref)
        actual_sha = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\x00" + content).hexdigest()
        if actual_sha != expected_sha:
            raise GitHubError("evidence content differs from its regular Git tree entry")
        return content

    def pull_request(self, number: int) -> dict[str, Any]:
        """Read the current Pull Request resource, including base/head repository identities."""
        number = _positive_int(number, "Pull Request number")
        result = self.request("GET", f"{self.prefix}/pulls/{number}")
        if not isinstance(result, dict) or result.get("number") != number:
            raise GitHubError("GitHub Pull Request response is missing or has a mismatched number")
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
