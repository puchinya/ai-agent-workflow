"""Exact-base worktree lifecycle over the existing immutable ExecutionBinding."""

from __future__ import annotations

import re
import os
from dataclasses import dataclass
from pathlib import Path

from .checkpoint import (
    CheckpointError, PRBinding, WorkCheckpoint, checkpoint_path, read_checkpoint,
    read_pr_binding, validate_ref, write_checkpoint, write_pr_binding,
)
from .context import WorkContext
from .execution import ExecutionBinding, ExecutionError, binding_digest, read_binding, write_binding
from .git import (
    GitError, branch_exists, create_branch, current_branch, head_sha40, is_ancestor,
    remote_branch_sha, switch_branch, worktree_clean,
)
from .github import GitHub, GitHubError
from .path_safety import path_has_symlink


class WorkError(RuntimeError):
    pass


def _reject_symlink_path(path: Path, label: str) -> None:
    if path_has_symlink(path):
        raise WorkError(f"{label} must not traverse a symbolic link")


@dataclass(frozen=True)
class WorkResult:
    status: str
    binding: ExecutionBinding | None
    context: WorkContext | None
    remote_base_sha40: str
    checkpoint_path: Path | None = None
    checkpoint_sha256: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PREnsureResult:
    pull_request: dict[str, object]
    binding: PRBinding
    checkpoint_path: Path
    checkpoint_sha256: str
    reused: bool


CLOSING_REF = re.compile(r"(?i)\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s+#([1-9][0-9]*)\b")
OWN_CLOSING_LINE = re.compile(r"(?im)^Closes #([1-9][0-9]*)\s*$")


def _validate_pr_body(body: str, issue_number: int) -> None:
    if not isinstance(body, str):
        raise WorkError("PR body must be text")
    closes = [int(value) for value in CLOSING_REF.findall(body)]
    own_line = [int(value) for value in OWN_CLOSING_LINE.findall(body)]
    if closes != [issue_number] or own_line != [issue_number]:
        raise WorkError(f"PR body must have exactly one standalone Closes #{issue_number} line")


def _readback_pull(github: GitHub, pull: dict[str, object], *, repository: str,
                   issue_number: int, base_ref: str, base_sha40: str,
                   head_ref: str, head_sha40: str) -> dict[str, object]:
    number = pull.get("number")
    if type(number) is not int or number < 1:
        raise WorkError("PR search returned a candidate without a valid number")
    try:
        row = github.pull_request(number)
    except GitHubError as exc:
        raise WorkError(f"PR API readback failed: {exc}") from exc
    base, head = row.get("base"), row.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    head_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    if (row.get("number") != number or row.get("state") != "open" or row.get("draft") is not False
            or not isinstance(base, dict) or base.get("ref") != base_ref or base.get("sha") != base_sha40
            or not isinstance(head, dict) or head.get("ref") != head_ref or head.get("sha") != head_sha40
            or not isinstance(base_name, str) or base_name.lower() != repository.lower()
            or not isinstance(head_name, str) or head_name.lower() != repository.lower()):
        raise WorkError("existing PR is closed, draft, forked, or mismatched in Issue/base/head/HEAD")
    _validate_pr_body(row.get("body"), issue_number)
    return row


def ensure_pull_request(repository_root: Path, github: GitHub, *, repository: str,
                        issue_number: int, binding: ExecutionBinding,
                        branch_ref: str, base_ref: str, title: str, body: str) -> PREnsureResult:
    """Reuse one exact eligible PR or create once, then read it back before binding."""
    root = Path(repository_root).absolute()
    branch_ref, base_ref = validate_ref(branch_ref), validate_ref(base_ref)
    _validate_pr_body(body, issue_number)
    binding.validate()
    if (binding.repository != repository or binding.issue_number != issue_number
            or binding.base_ref != base_ref or Path(binding.work_directory) != root):
        raise WorkError("ExecutionBinding does not match the requested PR repository, Issue, base, or worktree")
    if not worktree_clean(root) or current_branch(root) != branch_ref:
        raise WorkError("PR ensure requires a clean worktree on the exact bound branch")
    local_head = head_sha40(root)
    if not is_ancestor(root, binding.base_sha, local_head):
        raise WorkError("local PR HEAD does not descend from the frozen base")
    remote_head, remote_base = remote_branch_sha(root, branch_ref), remote_branch_sha(root, base_ref)
    if remote_head != local_head:
        raise WorkError("remote branch HEAD differs from the exact local worktree HEAD")
    if remote_base != binding.base_sha:
        raise WorkError("remote base drifted from the immutable ExecutionBinding base")
    binding_history = read_pr_binding_history(root, issue_number)
    if binding_history:
        history_identity = binding_history[0][1]
        prior_head: str | None = None
        for _path, item in binding_history:
            if not _same_pr_binding_identity(history_identity, item):
                raise WorkError("immutable PRBinding history changes PR, base, Issue, or ADC identity")
            if prior_head is not None:
                try:
                    descends = is_ancestor(root, prior_head, item.pr_head_sha40)
                except GitError as exc:
                    raise WorkError(f"could not verify immutable PRBinding HEAD history: {exc}") from exc
                if not descends:
                    raise WorkError("immutable PRBinding HEAD history is not a forward-only chain")
            prior_head = item.pr_head_sha40
    stored_binding = binding_history[-1][1] if binding_history else None
    try:
        candidates = github.pull_requests_for_refs(base_ref=base_ref, head_ref=branch_ref)
    except GitHubError as exc:
        raise WorkError(f"PR search failed: {exc}") from exc
    if len(candidates) > 1:
        raise WorkError("multiple PRs match the exact head/base refs; refusing ambiguous reuse")
    reused = bool(candidates)
    if candidates:
        pull = _readback_pull(github, candidates[0], repository=repository,
                              issue_number=issue_number, base_ref=base_ref, base_sha40=binding.base_sha,
                              head_ref=branch_ref, head_sha40=local_head)
    elif stored_binding is not None:
        try:
            prior = github.pull_request(stored_binding.pr_number)
        except GitHubError as exc:
            raise WorkError(f"bound PR readback failed; refusing replacement: {exc}") from exc
        if prior.get("state") != "open":
            raise WorkError("stored PRBinding refers to a non-open PR; refusing replacement")
        raise WorkError("stored PRBinding PR was not returned by exact branch/base search")
    else:
        try:
            created = github.create_pull_request(title=title, body=body,
                                                head_ref=branch_ref, base_ref=base_ref)
            pull = github.pull_request(created["number"])
        except GitHubError as exc:
            # A lost POST response is recovered only by exact re-search; never POST twice blindly.
            try:
                recovered = github.pull_requests_for_refs(base_ref=base_ref, head_ref=branch_ref)
            except GitHubError as search_exc:
                raise WorkError(f"PR create/readback failed and recovery search failed: {search_exc}") from exc
            if len(recovered) != 1:
                raise WorkError(f"PR create failed ({exc}); recovery found {len(recovered)} candidates") from exc
            reused = True
            pull = _readback_pull(github, recovered[0], repository=repository, issue_number=issue_number,
                                  base_ref=base_ref, base_sha40=binding.base_sha,
                                  head_ref=branch_ref, head_sha40=local_head)
        else:
            pull = _readback_pull(github, pull, repository=repository, issue_number=issue_number,
                                  base_ref=base_ref, base_sha40=binding.base_sha,
                                  head_ref=branch_ref, head_sha40=local_head)
    if candidates and stored_binding is not None:
        selected = pull.get("number")
        if stored_binding.pr_number != selected:
            raise WorkError("existing PRBinding conflicts with the exact-search PR identity")
    if (head_sha40(root) != local_head or not worktree_clean(root) or current_branch(root) != branch_ref
            or remote_branch_sha(root, branch_ref) != local_head
            or remote_branch_sha(root, base_ref) != binding.base_sha):
        raise WorkError("worktree, branch, or remote changed during PR readback; PR exists but binding was not advanced")
    pr_number = pull.get("number")
    if type(pr_number) is not int or pr_number < 1:
        raise WorkError("PR readback has no valid number")
    pr_binding = PRBinding(repository, issue_number, binding.adc_comment_id, binding.adc_sha256,
                           binding.base_sha, branch_ref, pr_number, local_head).validate()
    if stored_binding is not None and stored_binding != pr_binding:
        if not _same_pr_binding_identity(stored_binding, pr_binding):
            raise WorkError("existing immutable PRBinding history conflicts with the current PR identity")
        if not is_ancestor(root, stored_binding.pr_head_sha40, local_head):
            raise WorkError("new PRBinding HEAD does not descend from the latest immutable PRBinding")
        version = len(binding_history) + 1
        write_pr_binding(_pr_binding_version_path(root, issue_number, version), pr_binding)
    elif stored_binding is None:
        write_pr_binding(_pr_binding_version_path(root, issue_number, 1), pr_binding)
    checkpoint_file, checkpoint = _save_checkpoint(
        root, issue_number, binding, local_head, True, "pr",
        tuple(sorted((("execution-binding", binding_digest(binding)), ("pr-binding", pr_binding.sha256)))),
    )
    return PREnsureResult(pull, pr_binding, checkpoint_file, checkpoint.sha256, reused)


def execution_binding_path(work_directory: Path, issue_number: int) -> Path:
    if type(issue_number) is not int or issue_number < 1:
        raise WorkError("Issue number must be positive")
    root = Path(work_directory)
    if not root.is_absolute():
        raise WorkError("work directory must be absolute")
    return root / ".p_ases" / "state" / str(issue_number) / "execution-binding.json"


def pr_binding_path(work_directory: Path, issue_number: int) -> Path:
    history = read_pr_binding_history(work_directory, issue_number)
    if history:
        return history[-1][0]
    return execution_binding_path(work_directory, issue_number).with_name("pr-binding-000001.json")


def _pr_binding_version_path(work_directory: Path, issue_number: int, version: int) -> Path:
    if type(version) is not int or version < 1:
        raise WorkError("PRBinding version must be a positive integer")
    return execution_binding_path(work_directory, issue_number).with_name(f"pr-binding-{version:06d}.json")


def _same_pr_binding_identity(left: PRBinding, right: PRBinding) -> bool:
    return (left.repository == right.repository and left.issue_number == right.issue_number
            and left.adc_comment_id == right.adc_comment_id and left.adc_sha256 == right.adc_sha256
            and left.base_sha40 == right.base_sha40 and left.branch_ref == right.branch_ref
            and left.pr_number == right.pr_number)


def read_pr_binding_history(work_directory: Path, issue_number: int) -> list[tuple[Path, PRBinding]]:
    """Read a contiguous immutable PRBinding history, accepting the old single-file name."""
    directory = execution_binding_path(work_directory, issue_number).parent
    _reject_symlink_path(directory, "PRBinding history directory")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise WorkError("PRBinding history path is not a directory")
    legacy = directory / "pr-binding.json"
    numbered: dict[int, Path] = {}
    for path in directory.glob("pr-binding-*.json"):
        if path.is_symlink():
            raise WorkError("PRBinding history must not contain symbolic links")
        match = re.fullmatch(r"pr-binding-([0-9]{6})\.json", path.name)
        if not match:
            raise WorkError("PRBinding history contains an unexpected filename")
        version = int(match.group(1))
        if version < 1 or version in numbered:
            raise WorkError("PRBinding history has an invalid or duplicate version")
        numbered[version] = path
    if legacy.is_symlink():
        raise WorkError("PRBinding history must not contain symbolic links")
    offset = 1 if legacy.exists() else 0
    expected = list(range(1 + offset, 1 + offset + len(numbered)))
    if sorted(numbered) != expected:
        raise WorkError("PRBinding versions must be contiguous and monotonic")
    rows = [(legacy, read_pr_binding(legacy))] if legacy.exists() else []
    rows.extend((numbered[version], read_pr_binding(numbered[version])) for version in sorted(numbered))
    return rows


def _checkpoint_files(work_directory: Path, issue_number: int) -> list[Path]:
    directory = Path(work_directory) / ".p_ases" / "state" / str(issue_number)
    _reject_symlink_path(directory, "checkpoint directory")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise WorkError("checkpoint directory path is not a directory")
    paths = sorted(directory.glob("checkpoint-*.json"))
    if any(path.is_symlink() for path in paths):
        raise WorkError("checkpoint history must not contain symbolic links")
    if any(not re.fullmatch(r"checkpoint-[0-9]{6}\.json", path.name) for path in paths):
        raise WorkError("checkpoint history contains an unexpected filename")
    return paths


def latest_checkpoint(work_directory: Path, issue_number: int) -> tuple[Path, WorkCheckpoint] | None:
    rows: list[tuple[Path, WorkCheckpoint]] = []
    for path in _checkpoint_files(work_directory, issue_number):
        rows.append((path, read_checkpoint(path)))
    if not rows:
        return None
    rows.sort(key=lambda item: item[1].step)
    if [checkpoint.step for _, checkpoint in rows] != list(range(1, len(rows) + 1)):
        raise WorkError("checkpoint steps must be contiguous and monotonic")
    return rows[-1]


def _save_checkpoint(work_directory: Path, issue_number: int, binding: ExecutionBinding,
                     current_head: str, clean: bool, stage: str,
                     artifact_digests: tuple[tuple[str, str], ...]) -> tuple[Path, WorkCheckpoint]:
    digest = binding_digest(binding)
    previous = latest_checkpoint(work_directory, issue_number)
    step = 1 if previous is None else previous[1].step + 1
    if previous is not None:
        old = previous[1]
        if old.completed_stage == stage and old.current_head_sha40 == current_head:
            candidate = WorkCheckpoint(digest, current_head, clean, stage, artifact_digests, old.step).validate()
            if candidate == old:
                return previous
            raise WorkError("retry conflicts with the immutable checkpoint for this stage and HEAD")
    checkpoint = WorkCheckpoint(digest, current_head, clean, stage, artifact_digests, step).validate()
    path = checkpoint_path(work_directory, issue_number, step)
    write_checkpoint(path, checkpoint)
    return path, checkpoint


def resolve_base(repository_root: Path, base_ref: str, *, expected_sha40: str | None = None) -> str:
    ref = validate_ref(base_ref)
    try:
        selected = remote_branch_sha(repository_root, ref)
    except GitError as exc:
        raise WorkError(f"could not read exact remote base: {exc}") from exc
    if expected_sha40 is not None and selected != expected_sha40:
        raise WorkError("remote base SHA differs from the explicitly expected SHA")
    return selected


def ensure_branch(repository_root: Path, base_ref: str, base_sha40: str, branch_ref: str) -> WorkResult:
    root = Path(repository_root)
    base_ref, branch_ref = validate_ref(base_ref), validate_ref(branch_ref)
    if not worktree_clean(root):
        raise WorkError("branch operation requires a clean worktree")
    before_head = head_sha40(root)
    before_branch = current_branch(root)
    remote_before = resolve_base(root, base_ref, expected_sha40=base_sha40)
    try:
        if branch_exists(root, branch_ref):
            if before_branch != branch_ref:
                switch_branch(root, branch_ref)
        else:
            create_branch(root, branch_ref, base_sha40)
    except GitError as exc:
        raise WorkError(f"branch operation failed: {exc}") from exc
    after_branch, after_head = current_branch(root), head_sha40(root)
    after_clean = worktree_clean(root)
    remote_after = resolve_base(root, base_ref)
    if (after_branch != branch_ref or not after_clean or remote_before != remote_after
            or (after_head != base_sha40 and not is_ancestor(root, base_sha40, after_head))):
        raise WorkError("branch operation raced or produced a mismatched worktree; inspect without resetting")
    return WorkResult("READY", None, None, remote_after,
                      reasons=(f"previous_head={before_head}",))


def bind_work(repository_root: Path, *, repository: str, issue_number: int, adc_comment_id: int,
              adc_sha256: str, base_ref: str, branch_ref: str,
              expected_base_sha40: str | None = None) -> WorkResult:
    root = Path(repository_root).absolute()
    base_ref, branch_ref = validate_ref(base_ref), validate_ref(branch_ref)
    path = execution_binding_path(root, issue_number)
    _reject_symlink_path(path, "ExecutionBinding path")
    before_clean, before_head, before_branch = worktree_clean(root), head_sha40(root), current_branch(root)
    if not before_clean:
        raise WorkError("ExecutionBinding requires a clean worktree")
    if before_branch != branch_ref:
        raise WorkError("current branch differs from the requested bound branch")
    base_sha = resolve_base(root, base_ref, expected_sha40=expected_base_sha40)
    if before_head != base_sha and not is_ancestor(root, base_sha, before_head):
        raise WorkError("current branch is not a descendant of the selected frozen base")
    if path.exists():
        binding = read_binding(path)
        expected = ExecutionBinding(repository, issue_number, adc_comment_id, adc_sha256,
                                    base_ref, base_sha, str(root), base_sha).validate()
        if binding != expected:
            raise WorkError("existing ExecutionBinding conflicts; it is never replaced")
    else:
        binding = ExecutionBinding(repository, issue_number, adc_comment_id, adc_sha256,
                                   base_ref, base_sha, str(root), base_sha).validate()
        write_binding(path, binding)
    remote_after = resolve_base(root, base_ref)
    after_head, after_branch, after_clean = head_sha40(root), current_branch(root), worktree_clean(root)
    if (remote_after != base_sha or after_head != before_head or after_branch != before_branch
            or not after_clean):
        raise WorkError("worktree or remote base changed during binding; frozen evidence was retained")
    context = WorkContext(binding, after_head, after_branch, after_clean, binding_digest(binding)).validate()
    checkpoint_file, checkpoint = _save_checkpoint(
        root, issue_number, binding, after_head, after_clean, "bind",
        (("execution-binding", binding_digest(binding)),),
    )
    return WorkResult("BOUND", binding, context, remote_after, checkpoint_file, checkpoint.sha256)


def recover_work(repository_root: Path, *, repository: str, issue_number: int,
                 adc_comment_id: int, adc_sha256: str, expected_branch_ref: str) -> WorkResult:
    root = Path(repository_root).absolute()
    path = execution_binding_path(root, issue_number)
    _reject_symlink_path(path, "ExecutionBinding path")
    try:
        binding = read_binding(path)
    except ExecutionError as exc:
        raise WorkError(f"frozen ExecutionBinding cannot be recovered: {exc}") from exc
    if (binding.repository != repository or binding.issue_number != issue_number
            or binding.adc_comment_id != adc_comment_id or binding.adc_sha256 != adc_sha256
            or Path(binding.work_directory) != root):
        raise WorkError("ExecutionBinding belongs to a different repository, Issue, ADC, or worktree")
    if not worktree_clean(root):
        raise WorkError("recover requires a clean worktree; existing owner files are preserved")
    branch, current = current_branch(root), head_sha40(root)
    if branch != validate_ref(expected_branch_ref):
        raise WorkError("current branch differs from the explicitly expected work branch")
    if current != binding.base_sha and not is_ancestor(root, binding.base_sha, current):
        raise WorkError("current HEAD diverges from the frozen base; no reset or new base is selected")
    remote_now = resolve_base(root, binding.base_ref)
    drift = remote_now != binding.base_sha
    context = WorkContext(binding, current, branch, True, binding_digest(binding)).validate()
    if drift:
        return WorkResult(
            "BLOCKED", binding, context, remote_now, reasons=(
                "remote base has advanced; the original frozen base was retained and no rebase/reset was attempted",
            ),
        )
    checkpoint_file, checkpoint = _save_checkpoint(
        root, issue_number, binding, current, True, "recover",
        (("execution-binding", binding_digest(binding)),),
    )
    return WorkResult("RECOVERED", binding, context, remote_now,
                      checkpoint_file, checkpoint.sha256)
