"""Safe, one-shot Git lifecycle operations. All Git calls use argv arrays."""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

from .process import ProcessError, run_command
from .profile import build_hook_plan


class GitLifecycleError(RuntimeError):
    pass


def feature_slug(description: str, max_length: int) -> str:
    ascii_text = unicodedata.normalize("NFKD", description).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = re.sub(r"-+", "-", slug)[:max_length].rstrip("-")
    if not slug:
        raise GitLifecycleError("feature description produces an empty branch slug")
    return slug


def _invoke(repo: Path, args: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8", errors="replace",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, shell=False)
    except OSError as exc:
        raise GitLifecycleError(f"could not start Git {args[0]}") from exc
    if result.returncode and not allow_failure:
        raise GitLifecycleError(f"Git {args[0]} failed (exit status {result.returncode})")
    return result


def _validate_ref(repo: Path, ref: str, description: str = "branch") -> None:
    if (not isinstance(ref, str) or not ref or "\x00" in ref
            or _invoke(repo, ["check-ref-format", "--branch", ref], allow_failure=True).returncode):
        raise GitLifecycleError(f"{description} is not a valid Git branch name")


def _require_clean(repo: Path) -> None:
    result = _invoke(repo, ["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"])
    if result.stdout:
        raise GitLifecycleError("worktree must be clean before starting a feature branch")


def require_clean_worktree(repo: Path) -> None:
    """Public read-only clean-worktree check for exact-HEAD evidence workflows."""
    _require_clean(repo)


def local_head_sha(repo: Path) -> str:
    """Return the full commit SHA at local HEAD, failing closed on malformed output."""
    result = _invoke(repo, ["rev-parse", "--verify", "HEAD^{commit}"])
    sha = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GitLifecycleError("local HEAD did not resolve to a full commit SHA")
    return sha


def _branch_exists(repo: Path, branch: str) -> bool:
    result = _invoke(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], allow_failure=True)
    if result.returncode not in {0, 1}:
        raise GitLifecycleError(f"Git show-ref failed (exit status {result.returncode})")
    return result.returncode == 0


def _current_branch(repo: Path) -> str | None:
    result = _invoke(repo, ["branch", "--show-current"])
    return result.stdout.strip() or None


def _remote_branch_sha(repo: Path, branch: str) -> str | None:
    remote = _invoke(repo, ["ls-remote", "--heads", "origin", f"refs/heads/{branch}"])
    matches = [fields[0] for line in remote.stdout.splitlines()
               if len(fields := line.split("\t", 1)) == 2 and fields[1] == f"refs/heads/{branch}"]
    if len(matches) > 1 or (matches and not re.fullmatch(r"[0-9a-f]{40}", matches[0])):
        raise GitLifecycleError(f"origin/{branch} returned an invalid remote branch SHA")
    return matches[0] if matches else None


def _fetch_base_ref(repo: Path, branch: str) -> str:
    if _remote_branch_sha(repo, branch) is None:
        raise GitLifecycleError(f"base-ref must name an existing same-repository remote branch: {branch}")
    _invoke(repo, ["fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"])
    resolved = _invoke(repo, ["rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"], allow_failure=True)
    sha = resolved.stdout.strip()
    if resolved.returncode or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GitLifecycleError(f"could not resolve fetched origin/{branch} to a commit SHA")
    return sha


def _fetch_target_ref(repo: Path, branch: str) -> bool:
    if _remote_branch_sha(repo, branch) is None:
        return False
    _invoke(repo, ["fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"])
    return True


def changed_document_paths(repo: Path, base: str) -> list[Path]:
    """Resolve BASE and return only added/changed Markdown paths under docs/."""
    if not isinstance(base, str) or not base.strip() or "\x00" in base:
        raise GitLifecycleError("--changed requires a valid Git base ref")
    resolved = _invoke(repo, ["rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"],
                       allow_failure=True)
    sha = resolved.stdout.strip()
    if resolved.returncode or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GitLifecycleError(f"unknown --changed base ref: {base[:120]}")
    diff = _invoke(repo, ["diff", "--name-only", "--no-renames", "--diff-filter=ACMRTUXB", "-z",
                          f"{sha}...HEAD", "--", "docs"], allow_failure=True)
    if diff.returncode:
        raise GitLifecycleError(f"could not resolve docs diff from --changed base: {base[:120]}")
    paths: list[Path] = []
    for raw in diff.stdout.split("\x00"):
        if not raw:
            continue
        rel = PurePosixPath(raw)
        if not raw.startswith("docs/") or rel.suffix.casefold() != ".md":
            continue
        if rel.is_absolute() or ".." in rel.parts or "\\" in raw:
            raise GitLifecycleError("Git returned an unsafe changed document path")
        paths.append(repo.joinpath(*rel.parts))
    return sorted(set(paths))


def _remove_cleanup_path(repo: Path, relative: str) -> bool:
    path = repo.joinpath(*PurePosixPath(relative).parts)
    root = repo.resolve()
    parent = path.parent.resolve()
    if parent != root and root not in parent.parents:
        raise OSError(f"cleanup path escapes repository: {relative}")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode):
        path.unlink()
    elif stat.S_ISDIR(mode):
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def start_feature_branch(repo: Path, profile: dict[str, Any], issue_number: int,
                         description: str, github: Any, base_ref: str | None = None,
                         expected_base_sha: str | None = None) -> tuple[dict[str, Any], int]:
    """Switch/create a feature branch, then perform cleanup and global switch hooks."""
    policy = profile["branch"]
    slug = feature_slug(description, policy["max_slug_length"])
    target = f"{policy['prefix']}/{issue_number}-{slug}"
    if expected_base_sha is not None and not re.fullmatch(r"[0-9a-f]{40}", expected_base_sha):
        raise GitLifecycleError("--expected-base-sha must be exactly 40 lowercase hexadecimal characters")
    if base_ref is not None:
        _validate_ref(repo, base_ref, "--base-ref")

    _require_clean(repo)
    metadata = github.repository()
    default_branch = metadata["default_branch"]
    _validate_ref(repo, default_branch, "GitHub default branch")
    selected_base = base_ref or default_branch
    _validate_ref(repo, selected_base, "--base-ref")
    base_sha = _fetch_base_ref(repo, selected_base)
    if expected_base_sha is not None and expected_base_sha != base_sha:
        raise GitLifecycleError(
            f"expected base SHA does not match origin/{selected_base}; current branch and worktree are unchanged"
        )
    stacked = selected_base != default_branch
    has_remote_target = _fetch_target_ref(repo, target)

    current = _current_branch(repo)
    if current == target:
        return ({"issue": issue_number, "branch": target, "switched": False,
                 "base_ref": selected_base, "base_sha": base_sha, "stacked": stacked,
                 "creation_source": "current",
                 "cleanup_paths_removed": 0, "hooks_run": 0}, 0)

    local_target = _branch_exists(repo, target)
    if local_target:
        creation_source = "local"
        _invoke(repo, ["switch", "--", target])
    elif has_remote_target:
        creation_source = "remote"
        _invoke(repo, ["switch", "--track", "--create", target, f"origin/{target}"])
    else:
        creation_source = "new"
        _invoke(repo, ["switch", "--no-track", "--create", target, f"origin/{selected_base}"])

    result_metadata = {"base_ref": selected_base, "base_sha": base_sha,
                       "stacked": stacked, "creation_source": creation_source}

    cleanup_removed = 0
    try:
        for path in policy["cleanup_on_switch"]:
            cleanup_removed += int(_remove_cleanup_path(repo, path))
    except (OSError, GitLifecycleError) as exc:
        return ({"issue": issue_number, "branch": _current_branch(repo), "switched": True,
                 **result_metadata,
                 "cleanup_paths_removed": cleanup_removed, "hooks_run": 0,
                 "failure": {"stage": "cleanup", "message": str(exc)[:256]}}, 1)

    plan = build_hook_plan(profile, "branch_switch")
    hooks_run = 0
    try:
        for step in plan.steps:
            run_command(step.command, repo)
            hooks_run += 1
    except ProcessError as exc:
        return ({"issue": issue_number, "branch": _current_branch(repo), "switched": True,
                 **result_metadata,
                 "cleanup_paths_removed": cleanup_removed, "hooks_run": hooks_run,
                 "failure": {"stage": "branch_switch", "message": str(exc)[:256]}}, 1)

    return ({"issue": issue_number, "branch": target, "switched": True,
             **result_metadata,
             "cleanup_paths_removed": cleanup_removed, "hooks_run": hooks_run}, 0)


def _repository_from_remote_url(url: str) -> str:
    match = re.search(r"(?:^|@|://)github\.com[:/]([^/\s:?#]+/[^/\s:?#]+?)(?:\.git)?/?$", url, re.I)
    if not match:
        raise GitLifecycleError("origin is not a recognizable GitHub repository")
    return match.group(1)


def _origin_repository(repo: Path, *, push: bool = False) -> str:
    """Return the sole GitHub repository configured for origin fetch or push."""
    args = ["remote", "get-url"]
    if push:
        args.append("--push")
    args.extend(["--all", "origin"])
    urls = _invoke(repo, args, allow_failure=True)
    if urls.returncode:
        raise GitLifecycleError("could not identify the origin repository")
    values = [line.strip() for line in urls.stdout.splitlines() if line.strip()]
    if len(values) != 1:
        raise GitLifecycleError("origin must have exactly one fetch and push URL")
    return _repository_from_remote_url(values[0])


def push_review_branch(repo: Path, profile: dict[str, Any], issue_number: int,
                       repository: str, base_ref: str, default_base_ref: str) -> dict[str, Any]:
    """Validate and push the current Issue branch without force, then verify remote HEAD."""
    _require_clean(repo)
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise GitLifecycleError("owning repository identity is invalid")
    if not isinstance(default_base_ref, str) or not default_base_ref:
        raise GitLifecycleError("repository default branch is missing")
    _validate_ref(repo, default_base_ref, "GitHub default branch")
    if not isinstance(base_ref, str) or not base_ref:
        raise GitLifecycleError("selected base branch is missing")
    _validate_ref(repo, base_ref, "selected base branch")

    branch = _current_branch(repo)
    if branch is None:
        raise GitLifecycleError("HEAD must be attached to the Issue feature branch")
    _validate_ref(repo, branch, "current branch")
    if branch == default_base_ref:
        raise GitLifecycleError("refusing to push the repository default branch")
    prefix = profile.get("branch", {}).get("prefix")
    expected = rf"{re.escape(prefix)}/{issue_number}-[a-z0-9]+(?:-[a-z0-9]+)*" if isinstance(prefix, str) else ""
    if not expected or not re.fullmatch(expected, branch):
        raise GitLifecycleError("current branch is not the configured feature branch for this Issue")
    if (_origin_repository(repo).casefold() != repository.casefold()
            or _origin_repository(repo, push=True).casefold() != repository.casefold()):
        raise GitLifecycleError("origin repository does not match the owning Issue repository")
    mirror = _invoke(repo, ["config", "--bool", "--get", "remote.origin.mirror"], allow_failure=True)
    mirror_value = mirror.stdout.strip().casefold()
    if mirror.returncode == 0 and mirror_value == "true":
        raise GitLifecycleError("origin mirror-push configuration is not allowed for review handoff")
    if mirror.returncode not in {0, 1} or (mirror.returncode == 0 and mirror_value not in {"true", "false"}):
        raise GitLifecycleError("could not verify origin mirror-push configuration")

    head_result = _invoke(repo, ["rev-parse", "--verify", "HEAD^{commit}"], allow_failure=True)
    head_sha = head_result.stdout.strip()
    if head_result.returncode or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise GitLifecycleError("current HEAD is not a valid commit SHA")

    base_sha = _fetch_base_ref(repo, base_ref)
    ancestor = _invoke(repo, ["merge-base", "--is-ancestor", base_sha, head_sha], allow_failure=True)
    if ancestor.returncode == 1:
        raise GitLifecycleError("current branch does not contain the selected base; automatic rebase is forbidden")
    if ancestor.returncode:
        raise GitLifecycleError(f"Git merge-base failed (exit status {ancestor.returncode})")
    ahead_result = _invoke(repo, ["rev-list", "--count", f"{base_sha}..{head_sha}"], allow_failure=True)
    ahead_text = ahead_result.stdout.strip()
    if ahead_result.returncode or not ahead_text.isdigit():
        raise GitLifecycleError("could not determine commits ahead of the selected base")
    ahead_by = int(ahead_text)
    if ahead_by < 1:
        raise GitLifecycleError("current branch has no commit ahead of the selected base")

    remote_before = _remote_branch_sha(repo, branch)
    pushed = False
    if remote_before != head_sha:
        push = _invoke(repo, ["push", "--porcelain", "--no-follow-tags", "origin",
                              f"HEAD:refs/heads/{branch}"],
                       allow_failure=True)
        if push.returncode:
            raise GitLifecycleError(f"Git push failed (exit status {push.returncode})")
        pushed = True
    remote_after = _remote_branch_sha(repo, branch)
    if remote_after != head_sha:
        raise GitLifecycleError("remote branch HEAD does not match local HEAD after push")
    return {"head_sha": head_sha, "head_branch": branch, "base_branch": base_ref,
            "base_sha": base_sha, "ahead_by": ahead_by, "pushed": pushed,
            "remote_head": remote_after, "remote_head_verified": True}
