"""Narrow, append-only proof for Activation-owned default-branch advancement."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checkpoint import CheckpointError, PRBinding, _canonical, read_pr_binding, validate_ref
from .consumer_activation import ConsumerActivationError, read_consumer_activation_record
from .execution import AdoptedExecutionEpoch, ExecutionBinding, ExecutionIdentity, execution_identity_base
from .git import (
    GitError, changed_paths_between, commit_parents_sha40, fetch_remote_branch_exact,
    is_ancestor, patch_sha256_excluding_activation_profile, remote_branch_sha,
)
from .github import GitHub, GitHubError
from .issue_association import IssueAssociationError, parse_issue_association
from .path_safety import path_has_symlink


class CurrentBaseError(ValueError):
    pass


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PROFILE_PATH = ".agent/project.json"


@dataclass(frozen=True)
class CurrentBaseAdvanceEvidence:
    repository: str
    issue_number: int
    pr_number: int
    pr_id: int
    branch_ref: str
    frozen_base_sha40: str
    current_base_sha40: str
    activation_issue_number: int
    activation_record_id: int
    activation_record_sha256: str
    setup_pr_number: int
    setup_pr_id: int
    setup_branch: str
    setup_head_sha40: str
    setup_merge_sha40: str
    original_pr_binding_sha256: str
    original_pr_head_sha40: str
    transition_pr_head_sha40: str
    activation_profile_sha256: str
    original_code_patch_sha256: str
    transition_code_patch_sha256: str

    def validate(self) -> "CurrentBaseAdvanceEvidence":
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository):
            raise CurrentBaseError("current-base repository must be owner/name")
        for value, label in ((self.issue_number, "target Issue"), (self.pr_number, "target PR"),
                             (self.pr_id, "target PR ID"),
                             (self.activation_issue_number, "Activation Issue"),
                             (self.activation_record_id, "Activation record ID"),
                             (self.setup_pr_number, "Activation setup PR"),
                             (self.setup_pr_id, "Activation setup PR ID")):
            if type(value) is not int or value < 1:
                raise CurrentBaseError(f"current-base {label} must be positive")
        validate_ref(self.branch_ref)
        validate_ref(self.setup_branch)
        for value, label in ((self.frozen_base_sha40, "frozen base"),
                             (self.current_base_sha40, "current base"),
                             (self.setup_head_sha40, "setup HEAD"),
                             (self.setup_merge_sha40, "setup merge"),
                             (self.original_pr_head_sha40, "original target PR HEAD"),
                             (self.transition_pr_head_sha40, "transition target PR HEAD")):
            if not isinstance(value, str) or not SHA40.fullmatch(value):
                raise CurrentBaseError(f"current-base {label} must be a full SHA-40")
        if self.current_base_sha40 == self.frozen_base_sha40:
            raise CurrentBaseError("current-base evidence must describe a base advance")
        for value, label in ((self.activation_record_sha256, "Activation record"),
                             (self.original_pr_binding_sha256, "original PRBinding"),
                             (self.activation_profile_sha256, "Activation profile"),
                             (self.original_code_patch_sha256, "original code patch"),
                             (self.transition_code_patch_sha256, "transition code patch")):
            if not isinstance(value, str) or not SHA256.fullmatch(value):
                raise CurrentBaseError(f"current-base {label} digest is invalid")
        if self.original_code_patch_sha256 != self.transition_code_patch_sha256:
            raise CurrentBaseError("Activation base transition changed the target PR code patch")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "activation_issue_number": self.activation_issue_number,
            "activation_profile_sha256": self.activation_profile_sha256,
            "activation_record_id": self.activation_record_id,
            "activation_record_sha256": self.activation_record_sha256,
            "branch_ref": self.branch_ref,
            "current_base_sha40": self.current_base_sha40,
            "frozen_base_sha40": self.frozen_base_sha40,
            "issue_number": self.issue_number,
            "original_code_patch_sha256": self.original_code_patch_sha256,
            "original_pr_binding_sha256": self.original_pr_binding_sha256,
            "original_pr_head_sha40": self.original_pr_head_sha40,
            "pr_id": self.pr_id,
            "pr_number": self.pr_number,
            "repository": self.repository,
            "schema": "PASES_CURRENT_BASE_ADVANCE_V1",
            "setup_branch": self.setup_branch,
            "setup_head_sha40": self.setup_head_sha40,
            "setup_merge_sha40": self.setup_merge_sha40,
            "setup_pr_id": self.setup_pr_id,
            "setup_pr_number": self.setup_pr_number,
            "transition_code_patch_sha256": self.transition_code_patch_sha256,
            "transition_pr_head_sha40": self.transition_pr_head_sha40,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["current_base_advance_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "CurrentBaseAdvanceEvidence":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CurrentBaseError("current-base evidence is not valid UTF-8 JSON") from exc
        fields = {
            "activation_issue_number", "activation_profile_sha256", "activation_record_id",
            "activation_record_sha256", "branch_ref", "current_base_advance_sha256",
            "current_base_sha40", "frozen_base_sha40", "issue_number",
            "original_code_patch_sha256", "original_pr_binding_sha256", "original_pr_head_sha40",
            "pr_id", "pr_number", "repository", "schema", "setup_branch", "setup_head_sha40",
            "setup_merge_sha40", "setup_pr_id", "setup_pr_number", "transition_code_patch_sha256",
            "transition_pr_head_sha40",
        }
        if (not isinstance(value, dict) or set(value) != fields
                or value.get("schema") != "PASES_CURRENT_BASE_ADVANCE_V1"):
            raise CurrentBaseError("current-base evidence has unknown/missing fields or schema")
        result = cls(
            repository=value["repository"], issue_number=value["issue_number"],
            pr_number=value["pr_number"], pr_id=value["pr_id"], branch_ref=value["branch_ref"],
            frozen_base_sha40=value["frozen_base_sha40"], current_base_sha40=value["current_base_sha40"],
            activation_issue_number=value["activation_issue_number"],
            activation_record_id=value["activation_record_id"],
            activation_record_sha256=value["activation_record_sha256"],
            setup_pr_number=value["setup_pr_number"], setup_pr_id=value["setup_pr_id"],
            setup_branch=value["setup_branch"], setup_head_sha40=value["setup_head_sha40"],
            setup_merge_sha40=value["setup_merge_sha40"],
            original_pr_binding_sha256=value["original_pr_binding_sha256"],
            original_pr_head_sha40=value["original_pr_head_sha40"],
            transition_pr_head_sha40=value["transition_pr_head_sha40"],
            activation_profile_sha256=value["activation_profile_sha256"],
            original_code_patch_sha256=value["original_code_patch_sha256"],
            transition_code_patch_sha256=value["transition_code_patch_sha256"],
        ).validate()
        if value["current_base_advance_sha256"] != result.sha256 or result.to_bytes() != raw:
            raise CurrentBaseError("current-base evidence digest or canonical bytes do not match")
        return result


def current_base_advance_path(repository_root: Path, issue_number: int) -> Path:
    if type(issue_number) is not int or issue_number < 1 or not Path(repository_root).is_absolute():
        raise CurrentBaseError("current-base workspace and Issue are invalid")
    return Path(repository_root) / ".p_ases" / "state" / str(issue_number) / "current-base-advance.json"


def read_current_base_advance(path: Path) -> CurrentBaseAdvanceEvidence:
    location = Path(path)
    if path_has_symlink(location):
        raise CurrentBaseError("current-base evidence path must not traverse a symbolic link")
    try:
        return CurrentBaseAdvanceEvidence.from_bytes(location.read_bytes())
    except OSError as exc:
        raise CurrentBaseError("current-base evidence is missing or unreadable") from exc


def write_current_base_advance(path: Path, evidence: CurrentBaseAdvanceEvidence) -> str:
    evidence.validate()
    destination = Path(path)
    if path_has_symlink(destination):
        raise CurrentBaseError("current-base evidence path must not traverse a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(destination):
        raise CurrentBaseError("current-base evidence path must not traverse a symbolic link")
    data = evidence.to_bytes()
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp",
                                                    dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != data:
                raise CurrentBaseError("current-base evidence already exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise CurrentBaseError("could not atomically store current-base evidence") from exc
    if read_current_base_advance(destination) != evidence:
        raise CurrentBaseError("current-base evidence readback changed")
    return evidence.sha256


def verify_current_base_advance(
    repository_root: Path,
    github: GitHub,
    *,
    repository: str,
    issue_number: int,
    execution_binding: ExecutionIdentity,
    prior_pr_binding: PRBinding,
    current_pr: dict[str, Any],
    activation_issue_number: int,
) -> CurrentBaseAdvanceEvidence:
    """Create or revalidate the one Activation-owned A->B transition for this exact PR."""
    root = Path(repository_root).resolve()
    destination = current_base_advance_path(root, issue_number)
    base_ref, frozen_base = execution_identity_base(execution_binding)
    current_base = _nested(current_pr, "base", "sha")
    if not isinstance(current_base, str) or not SHA40.fullmatch(current_base):
        raise CurrentBaseError("current PR base SHA is malformed")
    existing = read_current_base_advance(destination) if destination.exists() else None
    if existing is not None:
        evidence = existing
        _verify_existing(root, github, repository, issue_number, execution_binding,
                         prior_pr_binding, current_pr, activation_issue_number, evidence)
        return evidence

    if prior_pr_binding.current_base_sha40 is not None:
        raise CurrentBaseError("PRBinding refers to a missing current-base evidence record")
    if prior_pr_binding.base_sha40 != frozen_base or current_base == frozen_base:
        raise CurrentBaseError("current PR base does not describe the required frozen-base transition")
    if (prior_pr_binding.repository.casefold() != repository.casefold()
            or prior_pr_binding.issue_number != issue_number
            or prior_pr_binding.pr_number != current_pr.get("number")
            or prior_pr_binding.branch_ref != _nested(current_pr, "head", "ref")):
        raise CurrentBaseError("original PRBinding identity differs from the current PR")

    record, record_id = _read_activation(github, repository, activation_issue_number)
    _setup_pr, setup_head, profile_bytes = _read_setup_proof(
        root, github, repository, frozen_base, current_base, base_ref,
        record,
    )
    _verify_target_pr(repository, issue_number, prior_pr_binding, current_pr,
                      current_base, base_ref)
    _verify_git_transition(root, frozen_base, current_base, prior_pr_binding.pr_head_sha40,
                           current_pr, setup_head, profile_bytes)
    _verify_live_refs(root, github, base_ref, current_base)
    current_head = _nested(current_pr, "head", "sha")
    if (hashlib.sha256(github.content_at_ref(PROFILE_PATH, current_base)).hexdigest()
            != hashlib.sha256(profile_bytes).hexdigest()
            or hashlib.sha256(github.content_at_ref(PROFILE_PATH, current_head)).hexdigest()
            != hashlib.sha256(profile_bytes).hexdigest()):
        raise CurrentBaseError("GitHub profile bytes at main or the exact target PR HEAD differ")
    original_patch = patch_sha256_excluding_activation_profile(
        root, frozen_base, prior_pr_binding.pr_head_sha40)
    transition_head = _nested(current_pr, "head", "sha")
    transition_patch = patch_sha256_excluding_activation_profile(root, current_base, transition_head)
    if original_patch != transition_patch:
        raise CurrentBaseError("Activation merge changed code in the existing PR patch")
    evidence = CurrentBaseAdvanceEvidence(
        repository=repository, issue_number=issue_number, pr_number=prior_pr_binding.pr_number,
        pr_id=_positive(current_pr.get("id"), "target PR ID"), branch_ref=prior_pr_binding.branch_ref,
        frozen_base_sha40=frozen_base, current_base_sha40=current_base,
        activation_issue_number=activation_issue_number, activation_record_id=record_id,
        activation_record_sha256=record.sha256,
        setup_pr_number=record.setup_pr_number, setup_pr_id=record.setup_pr_id,
        setup_branch=record.setup_branch, setup_head_sha40=setup_head,
        setup_merge_sha40=record.merge_commit_sha40,
        original_pr_binding_sha256=prior_pr_binding.sha256,
        original_pr_head_sha40=prior_pr_binding.pr_head_sha40,
        transition_pr_head_sha40=transition_head,
        activation_profile_sha256=hashlib.sha256(profile_bytes).hexdigest(),
        original_code_patch_sha256=original_patch,
        transition_code_patch_sha256=transition_patch,
    ).validate()
    write_current_base_advance(destination, evidence)
    _verify_existing(root, github, repository, issue_number, execution_binding,
                     prior_pr_binding, current_pr, activation_issue_number, evidence)
    return evidence


def _verify_existing(root: Path, github: GitHub, repository: str, issue_number: int,
                     execution_binding: ExecutionIdentity, pr_binding: PRBinding,
                     current_pr: dict[str, Any], activation_issue_number: int,
                     evidence: CurrentBaseAdvanceEvidence) -> None:
    base_ref, frozen_base = execution_identity_base(execution_binding)
    if isinstance(execution_binding, AdoptedExecutionEpoch):
        binding_reference_matches = (pr_binding.adoption_id == execution_binding.adoption_id and (
            (pr_binding.current_base_sha40 is None
             and pr_binding.sha256 == evidence.original_pr_binding_sha256
             and pr_binding.pr_head_sha40 == evidence.original_pr_head_sha40)
            or (pr_binding.current_base_sha40 == evidence.current_base_sha40
                and pr_binding.current_base_advance_sha256 == evidence.sha256)))
    else:
        binding_reference_matches = (
        (pr_binding.current_base_sha40 is None
         and pr_binding.sha256 == evidence.original_pr_binding_sha256
         and pr_binding.pr_head_sha40 == evidence.original_pr_head_sha40)
        or (pr_binding.current_base_sha40 == evidence.current_base_sha40
            and pr_binding.current_base_advance_sha256 == evidence.sha256)
        )
    if (evidence.repository.casefold() != repository.casefold() or evidence.issue_number != issue_number
            or evidence.pr_number != current_pr.get("number") or evidence.pr_id != current_pr.get("id")
            or evidence.branch_ref != _nested(current_pr, "head", "ref")
            or evidence.frozen_base_sha40 != frozen_base
            or evidence.current_base_sha40 != _nested(current_pr, "base", "sha")
            or evidence.activation_issue_number != activation_issue_number
            or not binding_reference_matches):
        raise CurrentBaseError("current-base evidence does not match the exact PR or immutable PRBinding")
    _verify_source_binding(root, issue_number, evidence, execution_binding)
    record, record_id = _read_activation(github, repository, activation_issue_number)
    if (record_id != evidence.activation_record_id or record.sha256 != evidence.activation_record_sha256
            or record.setup_pr_number != evidence.setup_pr_number
            or record.setup_pr_id != evidence.setup_pr_id
            or record.merge_commit_sha40 != evidence.setup_merge_sha40):
        raise CurrentBaseError("Activation V2 record differs from current-base evidence")
    setup_pr, setup_head, profile_bytes = _read_setup_proof(
        root, github, repository, evidence.frozen_base_sha40, evidence.current_base_sha40,
        base_ref, record,
    )
    if (setup_pr.get("id") != evidence.setup_pr_id or setup_head != evidence.setup_head_sha40
            or hashlib.sha256(profile_bytes).hexdigest() != evidence.activation_profile_sha256):
        raise CurrentBaseError("Activation setup PR differs from current-base evidence")
    _verify_target_pr(repository, issue_number, pr_binding, current_pr,
                      evidence.current_base_sha40, base_ref)
    transition_head = evidence.transition_pr_head_sha40
    current_head = _nested(current_pr, "head", "sha")
    try:
        if (not is_ancestor(root, evidence.frozen_base_sha40, evidence.current_base_sha40)
                or not is_ancestor(root, evidence.original_pr_head_sha40, transition_head)
                or not is_ancestor(root, evidence.current_base_sha40, transition_head)
                or not is_ancestor(root, transition_head, current_head)):
            raise CurrentBaseError("PR HEAD history does not preserve both the original work and Activation base")
        paths = changed_paths_between(root, evidence.frozen_base_sha40, evidence.current_base_sha40)
        parents = commit_parents_sha40(root, evidence.current_base_sha40)
        setup_parents = commit_parents_sha40(root, evidence.setup_head_sha40)
        if paths != (PROFILE_PATH,) or parents[0:1] != (evidence.frozen_base_sha40,):
            raise CurrentBaseError("main advanced with changes outside the exact Activation setup merge")
        if setup_parents != (evidence.frozen_base_sha40,):
            raise CurrentBaseError("Activation setup PR head is not one exact profile-only commit from the frozen base")
        if len(parents) == 2 and parents[1] != evidence.setup_head_sha40:
            raise CurrentBaseError("Activation merge commit second parent differs from its setup PR HEAD")
        if len(parents) not in {1, 2}:
            raise CurrentBaseError("Activation merge commit has an unknown parent shape")
        if patch_sha256_excluding_activation_profile(root, evidence.frozen_base_sha40,
                                                     evidence.original_pr_head_sha40) != evidence.original_code_patch_sha256:
            raise CurrentBaseError("original PR patch differs from recorded current-base evidence")
        if patch_sha256_excluding_activation_profile(root, evidence.current_base_sha40,
                                                     transition_head) != evidence.transition_code_patch_sha256:
            raise CurrentBaseError("transition PR patch differs from recorded current-base evidence")
    except GitError as exc:
        raise CurrentBaseError(f"could not verify current-base Git ancestry: {exc}") from exc
    _verify_live_refs(root, github, base_ref, evidence.current_base_sha40)
    for ref in (evidence.current_base_sha40, current_head):
        if hashlib.sha256(github.content_at_ref(PROFILE_PATH, ref)).hexdigest() != evidence.activation_profile_sha256:
            raise CurrentBaseError("Activation profile bytes differ between main and the target PR HEAD")


def _read_activation(github: GitHub, repository: str, activation_issue_number: int):
    try:
        result = read_consumer_activation_record(github, repository, activation_issue_number)
    except (ConsumerActivationError, GitHubError) as exc:
        raise CurrentBaseError(f"Activation V2 record readback failed: {exc}") from exc
    if result is None or result[0].schema_version != 2:
        raise CurrentBaseError("Activation V2 ACTIVE record is missing")
    record, record_id = result
    if (record.repository.casefold() != repository.casefold() or record.activation_issue_number != activation_issue_number
            or not isinstance(record.setup_branch, str) or not record.setup_branch):
        raise CurrentBaseError("Activation V2 record belongs to a different repository or Issue")
    return record, record_id


def _read_setup_proof(root: Path, github: GitHub, repository: str, frozen_base: str,
                      current_base: str, base_ref: str, record: Any
                      ) -> tuple[dict[str, Any], str, bytes]:
    try:
        setup_pr = github.pull_request(record.setup_pr_number)
        setup_base_repo = _nested(setup_pr, "base", "repo", "full_name")
        setup_head_repo = _nested(setup_pr, "head", "repo", "full_name")
        if (setup_pr.get("number") != record.setup_pr_number or setup_pr.get("id") != record.setup_pr_id
                or setup_pr.get("state") != "closed" or setup_pr.get("merged") is not True
                or setup_pr.get("merge_commit_sha") != record.merge_commit_sha40
                or setup_pr.get("merged_at") != record.merged_at
                or _nested(setup_pr, "base", "ref") != base_ref
                or _nested(setup_pr, "head", "ref") != record.setup_branch
                or not isinstance(setup_base_repo, str) or setup_base_repo.casefold() != repository.casefold()
                or not isinstance(setup_head_repo, str) or setup_head_repo.casefold() != repository.casefold()):
            raise CurrentBaseError("Activation record and setup PR identities or merge readback disagree")
        setup_head = _nested(setup_pr, "head", "sha")
        if not isinstance(setup_head, str) or not SHA40.fullmatch(setup_head):
            raise CurrentBaseError("Activation setup PR HEAD is malformed")
        files = github.pull_request_files(record.setup_pr_number)
        if (not isinstance(files, list) or len(files) != 1
                or not isinstance(files[0], dict) or files[0].get("filename") != PROFILE_PATH):
            raise CurrentBaseError("Activation setup PR must change only .agent/project.json")
        merge = github.commit_details(current_base)
        setup_commit = github.commit_details(setup_head)
        merge_parents = tuple(row["sha"] for row in merge["parents"])
        setup_parents = tuple(row["sha"] for row in setup_commit["parents"])
        if setup_parents != (frozen_base,) or merge.get("sha") != record.merge_commit_sha40:
            raise CurrentBaseError("Activation setup commit does not have the exact frozen-base parent")
        if merge_parents[0:1] != (frozen_base,) or len(merge_parents) not in {1, 2}:
            raise CurrentBaseError("default branch has an unknown or intervening commit before Activation")
        if len(merge_parents) == 2 and merge_parents[1] != setup_head:
            raise CurrentBaseError("Activation merge commit does not include the recorded setup PR HEAD")
        if not is_ancestor(root, frozen_base, current_base):
            raise CurrentBaseError("Activation current base is not a descendant of the frozen base")
        paths = changed_paths_between(root, frozen_base, current_base)
        setup_paths = changed_paths_between(root, frozen_base, setup_head)
        if paths != (PROFILE_PATH,) or setup_paths != (PROFILE_PATH,):
            raise CurrentBaseError("Activation transition includes a change outside .agent/project.json")
        profile = github.content_at_ref(PROFILE_PATH, current_base)
        if hashlib.sha256(profile).hexdigest() != record.activation_profile_sha256:
            raise CurrentBaseError("default branch profile bytes differ from the Activation V2 record")
        return setup_pr, setup_head, profile
    except (GitHubError, GitError) as exc:
        raise CurrentBaseError(f"Activation setup PR/base readback failed: {exc}") from exc


def _verify_target_pr(repository: str, issue_number: int, binding: PRBinding,
                      pr: dict[str, Any], current_base: str, base_ref: str) -> None:
    base_repo = _nested(pr, "base", "repo", "full_name")
    head_repo = _nested(pr, "head", "repo", "full_name")
    if (pr.get("number") != binding.pr_number or pr.get("state") != "open" or pr.get("draft") is not False
            or (issue_number == 63 and binding.pr_number != 64)
            or not isinstance(base_repo, str) or base_repo.casefold() != repository.casefold()
            or not isinstance(head_repo, str) or head_repo.casefold() != repository.casefold()
            or _nested(pr, "base", "sha") != current_base or _nested(pr, "base", "ref") != base_ref
            or _nested(pr, "head", "ref") != binding.branch_ref
            or not isinstance(_nested(pr, "head", "sha"), str)
            or not SHA40.fullmatch(_nested(pr, "head", "sha"))):
        raise CurrentBaseError("target PR identity/base/head readback differs from the exact transition")
    body = pr.get("body")
    try:
        association = parse_issue_association(body, issue_number)
    except IssueAssociationError as exc:
        raise CurrentBaseError(f"target PR Issue association is invalid: {exc}") from exc
    if association != ("deferred_close" if issue_number == 63 else "auto_close"):
        raise CurrentBaseError("target PR Issue association mode differs from the delivery contract")


def _verify_git_transition(root: Path, frozen_base: str, current_base: str, original_head: str,
                           current_pr: dict[str, Any], setup_head: str, profile_bytes: bytes) -> None:
    current_head = _nested(current_pr, "head", "sha")
    try:
        parents = commit_parents_sha40(root, current_base)
        setup_parents = commit_parents_sha40(root, setup_head)
        if (not is_ancestor(root, frozen_base, current_base)
                or not is_ancestor(root, original_head, current_head)
                or not is_ancestor(root, current_base, current_head)
                or parents[0:1] != (frozen_base,) or len(parents) not in {1, 2}
                or (len(parents) == 2 and parents[1] != setup_head)
                or setup_parents != (frozen_base,)):
            raise CurrentBaseError("target PR HEAD does not preserve frozen work and the exact Activation merge")
        if changed_paths_between(root, frozen_base, current_base) != (PROFILE_PATH,):
            raise CurrentBaseError("frozen base to current base has unknown changes")
        if changed_paths_between(root, frozen_base, setup_head) != (PROFILE_PATH,):
            raise CurrentBaseError("Activation setup commit changed an unexpected path")
        if hashlib.sha256(github_profile_bytes(root, current_head)).hexdigest() != hashlib.sha256(profile_bytes).hexdigest():
            raise CurrentBaseError("target PR HEAD profile differs from the Activation profile")
    except GitError as exc:
        raise CurrentBaseError(f"could not verify target PR Git ancestry: {exc}") from exc


def github_profile_bytes(root: Path, commit_sha40: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "show", f"{commit_sha40}:{PROFILE_PATH}"], cwd=root, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise CurrentBaseError("could not read target PR profile from its exact HEAD") from exc
    if result.returncode:
        raise CurrentBaseError("target PR HEAD does not contain .agent/project.json")
    return result.stdout


def _verify_live_refs(root: Path, github: GitHub, base_ref: str, expected_sha: str) -> None:
    try:
        metadata = github.repository_metadata()
        if metadata.get("default_branch") != base_ref:
            raise CurrentBaseError("Activation base transition does not target the current default branch")
        live_branch = github.branch(base_ref)
        live_sha = _nested(live_branch, "commit", "sha")
        remote_sha = remote_branch_sha(root, base_ref)
        if live_sha != expected_sha or remote_sha != expected_sha:
            raise CurrentBaseError("default branch advanced beyond or differs from the verified Activation commit")
        fetch_remote_branch_exact(root, base_ref, expected_sha)
    except (GitHubError, GitError) as exc:
        raise CurrentBaseError(f"current default branch readback failed: {exc}") from exc


def _verify_source_binding(root: Path, issue_number: int,
                           evidence: CurrentBaseAdvanceEvidence,
                           execution_identity: ExecutionIdentity) -> None:
    directory = current_base_advance_path(root, issue_number).parent
    rows: list[PRBinding] = []
    for path in sorted(directory.glob("pr-binding-*.json")):
        try:
            rows.append(read_pr_binding(path))
        except (OSError, CheckpointError) as exc:
            raise CurrentBaseError(f"immutable PRBinding history is invalid: {exc}") from exc
    if not rows:
        legacy = directory / "pr-binding.json"
        if legacy.exists():
            try:
                rows.append(read_pr_binding(legacy))
            except (OSError, CheckpointError) as exc:
                raise CurrentBaseError(f"immutable PRBinding history is invalid: {exc}") from exc
    source = next((row for row in rows if row.sha256 == evidence.original_pr_binding_sha256), None)
    expected_adoption = (execution_identity.adoption_id
                         if isinstance(execution_identity, AdoptedExecutionEpoch) else None)
    if (source is None or source.current_base_sha40 is not None
            or source.pr_head_sha40 != evidence.original_pr_head_sha40
            or source.repository.casefold() != evidence.repository.casefold()
            or source.issue_number != issue_number or source.pr_number != evidence.pr_number
            or source.base_sha40 != evidence.frozen_base_sha40
            or source.adoption_id != expected_adoption
            or source.branch_ref != evidence.branch_ref):
        raise CurrentBaseError("current-base evidence is not anchored to the immutable PRBinding/epoch")


def _nested(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise CurrentBaseError(f"{label} must be positive")
    return value
