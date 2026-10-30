"""ADC-bound phase decision receipts for the ordinary Issue lifecycle."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NamedTuple
from urllib.parse import urlsplit

from .adc import ADCError, VerifiedADC, verify_adc
from .gate_policy import BOOTSTRAP_REPOSITORY, GatePolicyError, read_gate_selection, select_gate
from .consumer_activation import ConsumerActivationError, read_consumer_activation_history
from .github import GitHub, GitHubError
from .execution import ExecutionError, read_binding
from .git import GitError, current_branch, head_sha40, is_ancestor
from .path_safety import path_has_symlink
from .phases import IssueKind, Phase, parse_phase_labels
from .work import execution_binding_path


class PhaseEvidenceError(ValueError):
    pass


class VerifiedOrdinaryIssueContext(NamedTuple):
    """One exact read of the live facts needed to validate a phase receipt.

    Callers may reuse this value only within one command invocation. Mutation
    boundaries must acquire a fresh context; immutable history validation is
    therefore shared within a boundary without weakening before/after checks.
    """

    issue: dict[str, Any]
    verified_adc: VerifiedADC
    kind: IssueKind
    branch_ref: str
    commit_sha40: str
    binding_verified: bool


SENTINEL = "PASES_PHASE_DECISION_V1"
READY_REFRESH_SCHEMA = "PASES_PHASE_READY_REFRESH_V1"
READY_REFRESH_START = f"<!-- {READY_REFRESH_SCHEMA}\n"
FIELDS = {
    "schema", "repository", "issue_number", "issue_kind", "from_phase", "to_phase",
    "adc_comment_id", "adc_sha256", "branch_ref", "commit_sha40", "documents", "skip_reasons",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DOCUMENT_ROLES = {"specification", "design", "test-oracle"}
DOCUMENT_ROOTS = {
    "specification": "docs/specs/",
    "design": "docs/design/",
    "test-oracle": "docs/testing/",
}
BOOTSTRAP_ISSUES = {26, 27, 28, 29, 30, 31, 32}
IMPACT_LINE = re.compile(r"(?im)^\s*[-*]\s*(Specification|Design|Testing):\s*(.*?)\s*$")
CANONICAL_IMPACT_LINE = re.compile(r"(?im)^\s*Canonical:\s*(.*?)\s*$")
BRACED_DOC_PATH = re.compile(
    r"(docs/(?:specs|design|testing)/[A-Za-z0-9._/-]*?)\{([^{}]+)\}([A-Za-z0-9._/-]*)"
)
DOC_PATH = re.compile(r"(?<![A-Za-z0-9_.-])docs/(?:specs|design|testing)/[A-Za-z0-9._/-]+")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PhaseEvidenceError("phase decision JSON contains duplicate fields")
        result[key] = value
    return result


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _validate_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise PhaseEvidenceError("phase decision has unknown or missing fields")
    if value["schema"] != SENTINEL:
        raise PhaseEvidenceError("phase decision schema is unsupported")
    if not isinstance(value["repository"], str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]):
        raise PhaseEvidenceError("phase decision repository is invalid")
    if type(value["issue_number"]) is not int or value["issue_number"] < 1:
        raise PhaseEvidenceError("phase decision Issue number is invalid")
    if not isinstance(value["issue_kind"], str) or value["issue_kind"] not in {
            IssueKind.SINGLE.value, IssueKind.CHILD.value}:
        raise PhaseEvidenceError("phase evidence is only for single and child Issues")
    try:
        source, target = Phase(value["from_phase"]), Phase(value["to_phase"])
    except (ValueError, TypeError) as exc:
        raise PhaseEvidenceError("phase decision phase pair is invalid") from exc
    allowed = {
        (Phase.REQUIREMENTS, Phase.SPECIFICATION),
        (Phase.REQUIREMENTS, Phase.DESIGN),
        (Phase.REQUIREMENTS, Phase.READY),
        (Phase.SPECIFICATION, Phase.DESIGN),
        (Phase.SPECIFICATION, Phase.READY),
        (Phase.DESIGN, Phase.READY),
    }
    if (source, target) not in allowed:
        raise PhaseEvidenceError("phase decision does not describe a specification, design, or ready boundary")
    if type(value["adc_comment_id"]) is not int or value["adc_comment_id"] < 1:
        raise PhaseEvidenceError("phase decision ADC Comment ID is invalid")
    if not isinstance(value["adc_sha256"], str) or not SHA256.fullmatch(value["adc_sha256"]):
        raise PhaseEvidenceError("phase decision ADC digest is invalid")
    if not isinstance(value["branch_ref"], str) or not value["branch_ref"].strip() or any(
            char in value["branch_ref"] for char in "\x00\r\n"):
        raise PhaseEvidenceError("phase decision branch ref is invalid")
    if not isinstance(value["commit_sha40"], str) or not SHA40.fullmatch(value["commit_sha40"]):
        raise PhaseEvidenceError("phase decision commit SHA is invalid")
    rows = value["documents"]
    if not isinstance(rows, list):
        raise PhaseEvidenceError("phase decision documents must be an array")
    paths: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"role", "path", "sha256"}:
            raise PhaseEvidenceError("phase decision document entry has unknown or missing fields")
        role, path, digest = row["role"], row["path"], row["sha256"]
        if (not isinstance(role, str) or role not in DOCUMENT_ROLES
                or not isinstance(path, str) or not path.startswith(DOCUMENT_ROOTS[role])):
            raise PhaseEvidenceError("phase decision document role and path do not match")
        if (path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(char in path for char in "\x00\r\n?#:")):
            raise PhaseEvidenceError("phase decision document path is unsafe")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise PhaseEvidenceError("phase decision document SHA-256 is invalid")
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise PhaseEvidenceError("phase decision documents must be path-sorted and unique")
    skips = value["skip_reasons"]
    if not isinstance(skips, dict) or set(skips) - {"specification", "design"}:
        raise PhaseEvidenceError("phase decision skip reasons are invalid")
    if any(not isinstance(reason, str) or not reason.strip() or "\x00" in reason for reason in skips.values()):
        raise PhaseEvidenceError("phase decision skip reasons must be non-empty text")
    expected_skips = ({"specification"} if source is Phase.REQUIREMENTS and target is Phase.DESIGN else
                      {"specification", "design"} if source is Phase.REQUIREMENTS and target is Phase.READY else
                      {"design"} if source is Phase.SPECIFICATION and target is Phase.READY else set())
    if set(skips) != expected_skips:
        raise PhaseEvidenceError("phase decision skip reasons do not match its transition")
    if target is Phase.SPECIFICATION and not any(row["role"] == "specification" for row in rows):
        raise PhaseEvidenceError("specification decision has no committed specification artifact")
    if target is Phase.DESIGN and not any(row["role"] == "design" for row in rows):
        raise PhaseEvidenceError("design decision has no committed design artifact")
    if target is Phase.READY and not any(row["role"] == "test-oracle" for row in rows):
        raise PhaseEvidenceError("ready decision has no committed test/Oracle artifact")
    return value


@dataclass(frozen=True)
class PhaseDecision:
    payload: dict[str, Any]

    def body(self) -> str:
        return SENTINEL + "\n" + _canonical(_validate_payload(self.payload)) + "\n"

    @classmethod
    def from_body(cls, body: Any) -> "PhaseDecision":
        if not isinstance(body, str) or not body.endswith("\n"):
            raise PhaseEvidenceError("phase decision comment must end with LF")
        lines = body.splitlines()
        if len(lines) != 2 or lines[0] != SENTINEL:
            raise PhaseEvidenceError("phase decision comment format is invalid")
        try:
            payload = json.loads(lines[1], object_pairs_hook=_unique_pairs)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PhaseEvidenceError("phase decision JSON is malformed") from exc
        checked = _validate_payload(payload)
        if _canonical(checked) != lines[1]:
            raise PhaseEvidenceError("phase decision JSON is not canonical")
        return cls(checked)


READY_REFRESH_FIELDS = {
    "schema", "repository", "issue_number", "issue_kind", "phase", "adc_comment_id", "adc_sha256",
    "ready_decision_comment_id", "ready_decision_sha256", "branch_ref", "commit_sha40", "documents",
    "issue_body_sha256", "labels", "predecessor_comment_id", "predecessor_body_sha256",
}


def _validate_ready_refresh_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != READY_REFRESH_FIELDS:
        raise PhaseEvidenceError("ready refresh record has unknown or missing fields")
    if value["schema"] != READY_REFRESH_SCHEMA or value["phase"] != Phase.READY.value:
        raise PhaseEvidenceError("ready refresh record schema or phase is unsupported")
    if not isinstance(value["repository"], str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]):
        raise PhaseEvidenceError("ready refresh repository is invalid")
    if type(value["issue_number"]) is not int or value["issue_number"] < 1:
        raise PhaseEvidenceError("ready refresh Issue number is invalid")
    if (not isinstance(value["issue_kind"], str)
            or value["issue_kind"] not in {IssueKind.SINGLE.value, IssueKind.CHILD.value}):
        raise PhaseEvidenceError("ready refresh Issue kind is invalid")
    for key in ("adc_comment_id", "ready_decision_comment_id", "predecessor_comment_id"):
        if type(value[key]) is not int or value[key] < 1:
            raise PhaseEvidenceError(f"ready refresh {key} is invalid")
    for key in ("adc_sha256", "ready_decision_sha256", "issue_body_sha256", "predecessor_body_sha256"):
        if not isinstance(value[key], str) or not SHA256.fullmatch(value[key]):
            raise PhaseEvidenceError(f"ready refresh {key} is invalid")
    if not isinstance(value["branch_ref"], str) or not value["branch_ref"].strip() or any(
            char in value["branch_ref"] for char in "\x00\r\n"):
        raise PhaseEvidenceError("ready refresh branch ref is invalid")
    if not isinstance(value["commit_sha40"], str) or not SHA40.fullmatch(value["commit_sha40"]):
        raise PhaseEvidenceError("ready refresh commit SHA is invalid")
    rows = value["documents"]
    if not isinstance(rows, list):
        raise PhaseEvidenceError("ready refresh documents must be an array")
    paths: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"role", "path", "sha256"}:
            raise PhaseEvidenceError("ready refresh document entry has unknown or missing fields")
        role, path, digest = row["role"], row["path"], row["sha256"]
        if (not isinstance(role, str) or role not in DOCUMENT_ROLES
                or not isinstance(path, str) or not path.startswith(DOCUMENT_ROOTS[role])
                or not isinstance(digest, str) or not SHA256.fullmatch(digest)):
            raise PhaseEvidenceError("ready refresh document identity is invalid")
        if (path.startswith("/") or "\\" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(char in path for char in "\x00\r\n?#:")):
            raise PhaseEvidenceError("ready refresh document path is unsafe")
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise PhaseEvidenceError("ready refresh documents must be path-sorted and unique")
    labels = value["labels"]
    if (not isinstance(labels, list) or any(not isinstance(label, str) or not label for label in labels)
            or labels != sorted(set(labels)) or f"phase:{Phase.READY.value}" not in labels
            or f"kind:{value['issue_kind']}" not in labels):
        raise PhaseEvidenceError("ready refresh labels must be a complete sorted ready-phase label set")
    if not any(row["role"] == "test-oracle" for row in rows):
        raise PhaseEvidenceError("ready refresh has no committed test/Oracle artifact")
    return value


@dataclass(frozen=True)
class ReadyPhaseRefresh:
    payload: dict[str, Any]

    def body(self) -> str:
        checked = _validate_ready_refresh_payload(self.payload)
        return READY_REFRESH_START + _canonical(checked) + "\n-->"

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body().encode("utf-8")).hexdigest()

    @classmethod
    def from_body(cls, body: Any) -> "ReadyPhaseRefresh":
        if (not isinstance(body, str) or not body.startswith(READY_REFRESH_START)
                or not body.endswith("\n-->")):
            raise PhaseEvidenceError("ready refresh comment format is invalid")
        raw = body[len(READY_REFRESH_START):-len("\n-->")]
        try:
            payload = json.loads(raw, object_pairs_hook=_unique_pairs)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PhaseEvidenceError("ready refresh JSON is malformed") from exc
        checked = _validate_ready_refresh_payload(payload)
        if _canonical(checked) != raw:
            raise PhaseEvidenceError("ready refresh JSON is not canonical")
        return cls(checked)


def _artifact_impacts(verified: VerifiedADC) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    text = verified.contract.section("artifact_impact")
    lines: dict[str, str] = {}
    for match in IMPACT_LINE.finditer(text):
        role = {"Specification": "specification", "Design": "design", "Testing": "test-oracle"}[match.group(1)]
        if role in lines:
            raise PhaseEvidenceError(f"approved ADC duplicates its {match.group(1)} artifact impact")
        lines[role] = match.group(2).strip()
    if set(lines) != DOCUMENT_ROLES:
        canonical_matches = list(CANONICAL_IMPACT_LINE.finditer(text))
        if len(canonical_matches) != 1:
            raise PhaseEvidenceError(
                "approved ADC must declare Specification, Design, and Testing impacts or one Canonical path list"
            )
        canonical = canonical_matches[0].group(1)
        while True:
            expanded, count = BRACED_DOC_PATH.subn(
                lambda match: ", ".join(
                    match.group(1) + item.strip() + match.group(3)
                    for item in match.group(2).split(",") if item.strip()
                ), canonical,
            )
            canonical = expanded
            if count == 0:
                break
        declarations = {role: [] for role in DOCUMENT_ROLES}
        for path in DOC_PATH.findall(canonical):
            if path.startswith(DOCUMENT_ROOTS["specification"]):
                declarations["specification"].append(path)
            elif path.startswith(DOCUMENT_ROOTS["design"]):
                declarations["design"].append(path)
            elif path.startswith(DOCUMENT_ROOTS["test-oracle"]):
                declarations["test-oracle"].append(path)
        if lines:
            for role, declaration in lines.items():
                declarations[role].extend(DOC_PATH.findall(declaration))
        lines = {role: ", ".join(paths) for role, paths in declarations.items()}
    if set(lines) != DOCUMENT_ROLES:
        raise PhaseEvidenceError("approved ADC must declare Specification, Design, and Testing artifact impact")
    paths: dict[str, tuple[str, ...]] = {}
    reasons: dict[str, str] = {}
    for role, declaration in lines.items():
        matched = tuple(sorted(set(DOC_PATH.findall(declaration))))
        normalized = declaration.casefold()
        if "not applicable" in normalized or "unchanged" in normalized:
            if matched:
                raise PhaseEvidenceError(f"ADC {role} impact cannot be both unchanged and linked to artifacts")
            reason_match = re.search(r"(?:unchanged|not applicable)", declaration, re.IGNORECASE)
            reason = declaration[reason_match.end():] if reason_match else ""
            reason = re.sub(r"^\s*(?:with\s+(?:the\s+)?reason|reason)\s*[:=]?\s*", "", reason,
                            flags=re.IGNORECASE)
            reason = re.sub(r"^\s*(?:because|since|as)\s+", "", reason, flags=re.IGNORECASE)
            reason = reason.strip(" .;()—:-")
            if not reason or reason.startswith("<"):
                raise PhaseEvidenceError(f"approved ADC {role} impact needs an explicit skip reason")
            reasons[role] = reason
        elif not matched:
            raise PhaseEvidenceError(f"approved ADC {role} impact must name its committed document paths")
        for path in matched:
            if not path.startswith(DOCUMENT_ROOTS[role]):
                raise PhaseEvidenceError(f"approved ADC {role} path is outside {DOCUMENT_ROOTS[role]}")
        paths[role] = matched
    return paths, reasons


def _expected_skip_reasons(source: Phase, target: Phase, supplied: Mapping[str, str], adc_reasons: Mapping[str, str]) -> dict[str, str]:
    expected = ({"specification"} if source is Phase.REQUIREMENTS and target is Phase.DESIGN else
                {"specification", "design"} if source is Phase.REQUIREMENTS and target is Phase.READY else
                {"design"} if source is Phase.SPECIFICATION and target is Phase.READY else set())
    if set(supplied) != expected:
        raise PhaseEvidenceError("--skip-phase reasons must exactly match the skipped phases")
    for phase, reason in supplied.items():
        adc_key = "specification" if phase == "specification" else "design"
        expected_reason = adc_reasons.get(adc_key)
        if expected_reason is None or reason.strip().casefold() != expected_reason.casefold():
            raise PhaseEvidenceError(f"{phase} skip reason does not match the approved ADC artifact impact")
    return dict(sorted(supplied.items()))


def _kind_from_issue(issue: dict[str, Any]) -> tuple[IssueKind, list[str]]:
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PhaseEvidenceError("Issue labels are malformed")
    labels = [row.get("name") for row in rows]
    kind_labels = [label for label in labels if isinstance(label, str) and label.startswith("kind:")]
    if len(kind_labels) != 1:
        raise PhaseEvidenceError("Issue must have exactly one kind:* label")
    try:
        kind = IssueKind(kind_labels[0].removeprefix("kind:"))
    except ValueError as exc:
        raise PhaseEvidenceError("Issue has an unknown kind:* label") from exc
    if kind not in {IssueKind.SINGLE, IssueKind.CHILD}:
        raise PhaseEvidenceError("phase evidence is only for single and child Issues")
    return kind, labels


def _verify_frozen_binding(github: GitHub, root: Path, issue_number: int, verified: VerifiedADC,
                           branch_ref: str, commit_sha: str) -> None:
    path = execution_binding_path(root.resolve(), issue_number)
    if not path.exists():
        if issue_number != 63 or not (
                (root / ".p_ases" / "state" / str(issue_number) / "execution-adoption.json").exists()
                or (root / ".p_ases" / "state" / str(issue_number) / "workspace-attachment.json").exists()):
            raise PhaseEvidenceError("a valid frozen Issue ExecutionBinding is required when no adopted epoch exists")
        try:
            from .execution_adoption import ExecutionAdoptionError, verify_adopted_execution
            adopted_readback = verify_adopted_execution(
                github, root, expected_adc_comment_id=verified.pointer.comment_id,
                expected_adc_sha256=verified.contract.sha256,
            )
            adopted = adopted_readback["epoch"]
            current_binding = adopted_readback["pr_binding"]
            if (issue_number != 63 or adopted.repository.casefold() != github.repo.casefold()
                    or adopted.issue_number != issue_number
                    or current_binding.adoption_id != adopted.adoption_id
                    or current_binding.adc_comment_id != verified.pointer.comment_id
                    or current_binding.adc_sha256 != verified.contract.sha256
                    or adopted.branch_ref != branch_ref
                    or current_binding.branch_ref != branch_ref
                    or current_binding.pr_head_sha40 != commit_sha
                    or not is_ancestor(root, adopted.selected_base_sha40, commit_sha)
                    or not is_ancestor(root, adopted.observed_start_head_sha40, commit_sha)):
                raise PhaseEvidenceError("verified adopted epoch/PRBinding does not match this Issue/ADC/branch/HEAD")
            return
        except (ExecutionAdoptionError, GitError) as exc:
            raise PhaseEvidenceError(f"a valid authenticated adopted execution epoch is required: {exc}") from exc
    try:
        binding = read_binding(path)
        if (binding.repository.casefold() != github.repo.casefold()
                or binding.issue_number != issue_number
                or binding.adc_comment_id != verified.pointer.comment_id
                or binding.adc_sha256 != verified.contract.sha256
                or binding.branch_ref != branch_ref
                or binding.base_ref == branch_ref
                or Path(binding.work_directory).resolve() != root.resolve()):
            raise PhaseEvidenceError("frozen ExecutionBinding does not match this Issue, approved ADC, branch, and worktree")
        if not is_ancestor(root, binding.base_sha, commit_sha):
            raise PhaseEvidenceError("current Issue branch does not descend from its frozen ExecutionBinding base")
    except (ExecutionError, GitError) as exc:
        raise PhaseEvidenceError(f"a valid frozen Issue ExecutionBinding is required: {exc}") from exc


def verify_ordinary_issue_context(github: GitHub, root: Path, issue_number: int,
                                 expected_kind: IssueKind | None = None, *, require_binding: bool = False
                                 ) -> VerifiedOrdinaryIssueContext:
    _check_activation(github, issue_number)
    try:
        issue = github.issue(issue_number)
        if issue.get("number") != issue_number or issue.get("state") != "open" or issue.get("pull_request") is not None:
            raise PhaseEvidenceError("ordinary phase transition requires the exact open GitHub Issue")
        repository_url = issue.get("repository_url")
        if (not isinstance(repository_url, str)
                or repository_url.casefold() != f"https://api.github.com/repos/{github.repo}".casefold()):
            raise PhaseEvidenceError("ordinary phase transition Issue belongs to a different repository")
        kind, _labels = _kind_from_issue(issue)
        if expected_kind is not None and kind is not expected_kind:
            raise PhaseEvidenceError("caller Issue kind differs from the actual kind:* label")
        verified = verify_adc(github, issue_number)
        if verified.pointer.state != "approved":
            raise PhaseEvidenceError("ordinary phase transitions require the current approved ADC")
        branch_ref = current_branch(root)
        local_sha = head_sha40(root)
        branch = github.branch(branch_ref)
        remote_sha = branch.get("commit", {}).get("sha") if isinstance(branch.get("commit"), dict) else None
        if branch.get("name") != branch_ref or remote_sha != local_sha:
            raise PhaseEvidenceError("local Git HEAD does not match the Issue branch commit on GitHub")
        if require_binding:
            _verify_frozen_binding(github, root, issue_number, verified, branch_ref, local_sha)
        return VerifiedOrdinaryIssueContext(
            issue, verified, kind, branch_ref, local_sha, require_binding,
        )
    except (ADCError, GitHubError, GitError) as exc:
        raise PhaseEvidenceError(str(exc)) from exc


def _reuse_verified_context(github: GitHub, root: Path, issue_number: int,
                            expected_kind: IssueKind | None,
                            context: VerifiedOrdinaryIssueContext) -> VerifiedOrdinaryIssueContext:
    """Validate an invocation-local proof before using it to avoid a duplicate full history read."""
    if (not isinstance(context, VerifiedOrdinaryIssueContext)
            or type(context.binding_verified) is not bool or not context.binding_verified):
        raise PhaseEvidenceError("phase receipt reuse requires a current binding-verified Issue context")
    issue = context.issue
    if not isinstance(issue, dict):
        raise PhaseEvidenceError("reused phase receipt context has a malformed Issue snapshot")
    repository_url = issue.get("repository_url")
    try:
        actual_kind, _labels = _kind_from_issue(issue)
    except PhaseEvidenceError:
        raise
    if (not isinstance(issue, dict) or issue.get("number") != issue_number
            or issue.get("state") != "open" or issue.get("pull_request") is not None
            or not isinstance(repository_url, str) or repository_url.casefold()
            != f"https://api.github.com/repos/{github.repo}".casefold()
            or not isinstance(context.verified_adc, VerifiedADC)
            or context.verified_adc.pointer.state != "approved"
            or context.kind not in {IssueKind.SINGLE, IssueKind.CHILD} or actual_kind is not context.kind
            or (expected_kind is not None and context.kind is not expected_kind)):
        raise PhaseEvidenceError("reused phase receipt context does not match the exact open Issue and approved ADC")
    try:
        if (current_branch(root) != context.branch_ref
                or head_sha40(root) != context.commit_sha40):
            raise PhaseEvidenceError("Issue worktree changed since its binding-verified context was read")
    except GitError as exc:
        raise PhaseEvidenceError(str(exc)) from exc
    return context


def _markdown_anchors(content: bytes) -> set[str]:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PhaseEvidenceError("traceability target must be valid UTF-8 Markdown") from exc
    visible_lines: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(```+|~~~+)", line)
        if marker:
            candidate = marker.group(1)[0]
            if not in_fence:
                in_fence, fence_marker = True, candidate
            elif candidate == fence_marker:
                in_fence, fence_marker = False, ""
            continue
        if not in_fence:
            visible_lines.append(line)
    visible = re.sub(r"<!--.*?-->", "", "\n".join(visible_lines), flags=re.DOTALL)
    anchors = {value.casefold() for value in re.findall(
        r"(?i)<a\b[^>]*\b(?:id|name)\s*=\s*['\"]([^'\"]+)['\"]", visible)}
    counts: dict[str, int] = {}
    for line in visible.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        title = re.sub(r"`([^`]*)`", r"\1", match.group(1))
        title = re.sub(r"!?(?:\[([^]]*)\])\([^)]*\)", r"\1", title)
        slug = re.sub(r"[^\w -]", "", title.casefold(), flags=re.UNICODE)
        slug = re.sub(r"\s+", "-", slug.strip())
        if not slug:
            continue
        duplicate = counts.get(slug, 0)
        counts[slug] = duplicate + 1
        anchors.add(slug if duplicate == 0 else f"{slug}-{duplicate}")
    return anchors


def _traceability_target(root: Path, github: GitHub, commit_sha: str, source_path: str,
                         destination: str, expected_root: str, label: str,
                         allowed_paths: tuple[str, ...], skipped: bool,
                         cache: dict[str, bytes]) -> tuple[str, bytes]:
    if (not isinstance(destination, str) or not destination or "\\" in destination
            or any(char in destination for char in "\x00\r\n?:%")):
        raise PhaseEvidenceError(f"traceability link for {label} has an unsafe target")
    parts = urlsplit(destination)
    if parts.scheme or parts.netloc or parts.query or parts.path.startswith("/"):
        raise PhaseEvidenceError(f"traceability link for {label} must be a repository-relative Markdown link")
    linked_path, marker, fragment = destination.partition("#")
    if not marker or not fragment or parts.fragment != fragment:
        raise PhaseEvidenceError(f"traceability link for {label} must name an existing anchor")
    target = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), linked_path))
    if (target.startswith("../") or target == ".." or not target.startswith(expected_root)
            or target not in allowed_paths and not skipped):
        raise PhaseEvidenceError(f"traceability link for {label} is outside its approved {expected_root} artifacts")
    if target not in cache:
        local = root / target
        if path_has_symlink(local, root=root) or not local.is_file():
            raise PhaseEvidenceError(f"traceability target is missing or unsafe: {target}")
        try:
            committed = github.regular_content_at_ref(target, commit_sha)
        except GitHubError as exc:
            raise PhaseEvidenceError(f"traceability target is absent from the branch commit: {target}: {exc}") from exc
        if local.read_bytes() != committed:
            raise PhaseEvidenceError(f"traceability target differs from the branch commit: {target}")
        cache[target] = committed
    if fragment.casefold() not in _markdown_anchors(cache[target]):
        raise PhaseEvidenceError(f"traceability anchor #{fragment} does not exist in {target}")
    if not (fragment.casefold() == label.casefold()
            or fragment.casefold().startswith(label.casefold() + "-")):
        raise PhaseEvidenceError(f"traceability anchor #{fragment} does not identify {label}")
    return target, cache[target]


def _validate_ready_traceability(root: Path, path: str, content: bytes, github: GitHub,
                                 commit_sha: str, requirements: tuple[str, ...],
                                 declared_paths: Mapping[str, tuple[str, ...]],
                                 skip_reasons: Mapping[str, str]) -> dict[str, tuple[str, bytes]]:
    if path != "docs/testing/traceability.md":
        return {}
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PhaseEvidenceError("test/Oracle traceability matrix must be valid UTF-8") from exc
    rows = [line.strip() for line in text.splitlines() if line.lstrip().startswith("|")]
    cache: dict[str, bytes] = {path: content}
    verified_targets: dict[str, tuple[str, bytes]] = {}
    identities = (
        ("specification", "docs/specs/", lambda label: label.startswith("REQ-")),
        ("design", "docs/design/", lambda label: re.fullmatch(r"DES-[A-Z0-9-]+", label) is not None),
        ("test-oracle", "docs/testing/", lambda label: re.fullmatch(r"(?:ORA|ORACLE|TST|TEST)-[A-Z0-9._-]+", label) is not None),
    )
    for requirement in requirements:
        matches = [row for row in rows if re.search(rf"\[{re.escape(requirement)}\]", row)]
        if not matches:
            raise PhaseEvidenceError(f"ready traceability matrix does not cover {requirement}")
        for row in matches:
            links = re.findall(r"\[([^]]+)\]\(([^)]+)\)", row)
            for role, expected_root, accepts in identities:
                selected = [(label, destination) for label, destination in links if accepts(label)]
                if role == "specification":
                    selected = [(label, destination) for label, destination in selected if label == requirement]
                elif role == "test-oracle":
                    oracles = [(label, destination) for label, destination in selected if label.startswith(("ORA-", "ORACLE-"))]
                    tests = [(label, destination) for label, destination in selected if label.startswith(("TST-", "TEST-"))]
                    if len(oracles) != 1 or len(tests) != 1:
                        raise PhaseEvidenceError(f"ready traceability row for {requirement} needs one linked Oracle and Test")
                    selected = [*oracles, *tests]
                if len(selected) != 1 and role != "test-oracle":
                    raise PhaseEvidenceError(f"ready traceability row for {requirement} needs one linked {role}")
                for label, destination in selected:
                    target, target_content = _traceability_target(
                        root, github, commit_sha, path, destination, expected_root, label,
                        declared_paths.get(role, ()), role in skip_reasons, cache,
                    )
                    verified_targets[target] = (role, target_content)
            source_links = [destination for _label, destination in links
                            if destination.startswith("../../tests/")]
            if not source_links:
                raise PhaseEvidenceError(f"ready traceability row for {requirement} needs an executable test source")
            for source_link in source_links:
                if any(char in source_link for char in "\\\x00\r\n?#:%"):
                    raise PhaseEvidenceError(f"ready traceability test source path for {requirement} is unsafe")
                normalized = posixpath.normpath(posixpath.join("docs/testing", source_link))
                if not normalized.startswith("tests/") or normalized.startswith("../"):
                    raise PhaseEvidenceError(f"ready traceability test source for {requirement} is outside tests/")
                local = root / normalized
                if path_has_symlink(local, root=root) or not local.is_file():
                    raise PhaseEvidenceError(f"ready traceability source is missing or unsafe: {normalized}")
                try:
                    committed = github.regular_content_at_ref(normalized, commit_sha)
                except GitHubError as exc:
                    raise PhaseEvidenceError(f"ready traceability source is absent from the branch commit: {normalized}") from exc
                if local.read_bytes() != committed:
                    raise PhaseEvidenceError(f"ready traceability source differs from the branch commit: {normalized}")
    return verified_targets


def _check_activation(github: GitHub, issue_number: int) -> None:
    if github.repo.casefold() == BOOTSTRAP_REPOSITORY.casefold() and issue_number in BOOTSTRAP_ISSUES:
        raise PhaseEvidenceError("fixed Bootstrap and parent Issues do not use ordinary phase evidence")
    try:
        issue = github.issue(issue_number)
        if (issue.get("number") != issue_number or issue.get("pull_request") is not None
                or not isinstance(issue.get("created_at"), str)):
            raise PhaseEvidenceError("P-ASES gate selection requires the exact GitHub Issue resource")
        gate_comment_id, pinned, _body = read_gate_selection(github, issue_number)
        activation_issue_number = pinned.activation_issue_number
        if activation_issue_number is None:
            raise PhaseEvidenceError("Gate Selection does not name its consumer Activation Issue")
        history = read_consumer_activation_history(
            github, github.repo, activation_issue_number,
            through_record_id=pinned.activation_comment_id,
        )
        activation_row = next((row for row in history if row[1] == pinned.activation_comment_id), None)
        if activation_row is None:
            raise PhaseEvidenceError("Gate Selection does not point to a valid historical consumer Activation")
        activation, activation_comment_id = activation_row
        expected = select_gate(
            github.repo, issue_number, selected_at=pinned.selected_at, activation=activation,
            activation_comment_id=activation_comment_id, activation_sha256=activation.sha256,
            issue_created_at=issue["created_at"], activation_issue_number=activation_issue_number,
        )
        if (expected is None or expected.payload() != pinned.payload()
                or gate_comment_id < 1):
            raise PhaseEvidenceError("Issue does not have the exact P-ASES Gate Selection bound to current Activation")
    except (GitHubError, GatePolicyError, ConsumerActivationError) as exc:
        raise PhaseEvidenceError(f"ordinary Issue phase evidence requires verified P-ASES Activation: {exc}") from exc


def _receipt_subject(payload: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(payload[key] for key in (
        "repository", "issue_number", "from_phase", "to_phase", "adc_comment_id", "adc_sha256",
    ))


def _find_receipt(github: GitHub, issue_number: int, *, source: Phase, target: Phase,
                  adc_comment_id: int, adc_sha256: str) -> tuple[int, PhaseDecision]:
    try:
        comments = github.issue_comments(issue_number)
    except GitHubError as exc:
        raise PhaseEvidenceError(f"prior phase receipt history is unavailable: {exc}") from exc
    matches: list[dict[str, Any]] = []
    for row in comments:
        body = row.get("body") if isinstance(row, dict) else None
        if isinstance(body, str) and body.startswith(SENTINEL + "\n"):
            candidate = PhaseDecision.from_body(body)
            if _receipt_subject(candidate.payload) == (
                    github.repo, issue_number, source.value, target.value, adc_comment_id, adc_sha256):
                matches.append(row)
    if len(matches) != 1:
        reason = "missing" if not matches else "duplicated"
        raise PhaseEvidenceError(f"required predecessor phase receipt is {reason} for this approved ADC generation")
    comment_id = matches[0].get("id")
    if type(comment_id) is not int or comment_id < 1:
        raise PhaseEvidenceError("predecessor phase receipt has an invalid comment ID")
    body = matches[0].get("body")
    parsed = _readback(github, issue_number, comment_id, body)
    return comment_id, parsed


def _predecessor_chain(source: Phase, target: Phase, adc_reasons: Mapping[str, str]
                       ) -> tuple[tuple[Phase, Phase], ...]:
    if source is Phase.SPECIFICATION and target is Phase.DESIGN:
        return ((Phase.REQUIREMENTS, Phase.SPECIFICATION),)
    if target is Phase.READY and source is Phase.SPECIFICATION:
        return ((Phase.REQUIREMENTS, Phase.SPECIFICATION),)
    if target is Phase.READY and source is Phase.DESIGN:
        if "specification" in adc_reasons:
            return ((Phase.REQUIREMENTS, Phase.DESIGN),)
        return (
            (Phase.REQUIREMENTS, Phase.SPECIFICATION),
            (Phase.SPECIFICATION, Phase.DESIGN),
        )
    return ()


def _verify_predecessor_receipt(github: GitHub, root: Path, issue_number: int,
                                edge: tuple[Phase, Phase], verified: VerifiedADC,
                                kind: IssueKind, branch_ref: str, current_sha: str,
                                declared_paths: Mapping[str, tuple[str, ...]],
                                adc_reasons: Mapping[str, str],
                                documents_by_path: Mapping[str, Mapping[str, str]],
                                previous_sha: str | None) -> tuple[PhaseDecision, str]:
    source, target = edge
    _comment_id, prior = _find_receipt(
        github, issue_number, source=source, target=target,
        adc_comment_id=verified.pointer.comment_id, adc_sha256=verified.contract.sha256,
    )
    payload = prior.payload
    if (payload["branch_ref"] != branch_ref or payload["issue_kind"] != kind.value
            or payload["repository"].casefold() != github.repo.casefold()
            or payload["adc_comment_id"] != verified.pointer.comment_id
            or payload["adc_sha256"] != verified.contract.sha256
            or not is_ancestor(root, payload["commit_sha40"], current_sha)
            or (previous_sha is not None and not is_ancestor(root, previous_sha, payload["commit_sha40"]))):
        raise PhaseEvidenceError("predecessor receipt chain does not belong to this Issue branch history")

    if target is Phase.SPECIFICATION:
        expected_roles = {"specification"}
    elif target is Phase.DESIGN and source is Phase.REQUIREMENTS:
        expected_roles = {"design"}
    elif target is Phase.DESIGN:
        expected_roles = {"specification", "design"}
    else:
        expected_roles = set()
    expected_paths = {
        path: role
        for role in expected_roles
        for path in declared_paths.get(role, ())
    }
    rows = {row["path"]: row for row in payload["documents"]}
    if set(rows) != set(expected_paths) or any(rows[path]["role"] != role for path, role in expected_paths.items()):
        raise PhaseEvidenceError("predecessor receipt artifact set does not match the approved ADC")

    expected_skips = ({"specification": adc_reasons["specification"]}
                      if source is Phase.REQUIREMENTS and target is Phase.DESIGN else {})
    if payload["skip_reasons"] != expected_skips:
        raise PhaseEvidenceError("predecessor receipt skip reason does not match the approved ADC")
    for path, role in expected_paths.items():
        current = documents_by_path.get(path)
        if (current is None or current["role"] != role
                or current["sha256"] != rows[path]["sha256"]):
            raise PhaseEvidenceError(
                "a previously completed specification/design artifact changed; "
                "return to requirements and reapprove the ADC",
            )
    return prior, payload["commit_sha40"]


def _collect_payload(github: GitHub, root: Path, issue_number: int, source: Phase, target: Phase,
                     skips: Mapping[str, str], *, check_source_phase: bool = True,
                     verified_context: VerifiedOrdinaryIssueContext | None = None,
                     ) -> tuple[PhaseDecision, dict[str, Any], VerifiedADC, str, str]:
    if type(issue_number) is not int or issue_number < 1:
        raise PhaseEvidenceError("Issue number must be a positive integer")
    context = (verify_ordinary_issue_context(github, root, issue_number, require_binding=True)
               if verified_context is None else
               _reuse_verified_context(github, root, issue_number, None, verified_context))
    issue, verified, kind, branch_ref, local_sha, _binding_verified = context
    labels = [row.get("name") for row in issue.get("labels", []) if isinstance(row, dict)]
    if check_source_phase and parse_phase_labels(labels) is not source:
        raise PhaseEvidenceError("Issue phase label differs from the requested evidence source phase")
    declared_paths, adc_reasons = _artifact_impacts(verified)
    skip_reasons = _expected_skip_reasons(source, target, skips, adc_reasons)
    if source is Phase.REQUIREMENTS and target is Phase.DESIGN and "specification" not in skip_reasons:
        raise PhaseEvidenceError("requirements to design requires an approved specification skip reason")
    if source is Phase.REQUIREMENTS and target is Phase.READY and set(skip_reasons) != {"specification", "design"}:
        raise PhaseEvidenceError("requirements to ready requires independent specification and design skip reasons")

    required_roles: set[str] = set()
    if target is Phase.SPECIFICATION:
        required_roles.add("specification")
    elif target is Phase.DESIGN:
        required_roles.add("design")
        if source is Phase.SPECIFICATION:
            required_roles.add("specification")
    elif target is Phase.READY:
        required_roles.add("test-oracle")
        if source is Phase.SPECIFICATION:
            required_roles.add("specification")
        elif source is Phase.DESIGN:
            required_roles.add("design")
            if declared_paths.get("specification"):
                required_roles.add("specification")
    roles = {role: declared_paths[role] for role in required_roles if declared_paths.get(role)}
    if "specification" in required_roles and not roles.get("specification"):
        raise PhaseEvidenceError("approved ADC has no specification artifact for this phase")
    if "design" in required_roles and not roles.get("design"):
        raise PhaseEvidenceError("approved ADC has no design artifact for this phase")
    if "test-oracle" in required_roles:
        if not roles.get("test-oracle"):
            raise PhaseEvidenceError("approved ADC has no committed test/Oracle artifact for ready")
        if "docs/testing/traceability.md" not in roles["test-oracle"]:
            raise PhaseEvidenceError("ready requires the committed canonical test/Oracle traceability matrix")

    documents_by_path: dict[str, dict[str, str]] = {}
    contents: dict[str, bytes] = {}
    for role, paths in roles.items():
        for path in paths:
            local_path = Path(root) / path
            if path_has_symlink(local_path, root=Path(root)) or not local_path.is_file():
                raise PhaseEvidenceError(f"phase artifact must be a regular file without symlinks: {path}")
            content = github.regular_content_at_ref(path, local_sha)
            if local_path.read_bytes() != content:
                raise PhaseEvidenceError(f"working-tree bytes differ from the committed phase artifact: {path}")
            contents[path] = content
            documents_by_path[path] = {"role": role, "path": path,
                                       "sha256": hashlib.sha256(content).hexdigest()}

    if target is Phase.READY:
        trace_targets = _validate_ready_traceability(
            Path(root), "docs/testing/traceability.md", contents["docs/testing/traceability.md"],
            github, local_sha, verified.contract.requirement_ids, declared_paths,
            {role: reason for role, reason in adc_reasons.items() if not declared_paths.get(role)},
        )
        for path, (role, content) in trace_targets.items():
            contents[path] = content
            documents_by_path[path] = {"role": role, "path": path,
                                       "sha256": hashlib.sha256(content).hexdigest()}

    previous_sha: str | None = None
    for edge in _predecessor_chain(source, target, adc_reasons):
        _prior, previous_sha = _verify_predecessor_receipt(
            github, Path(root), issue_number, edge, verified, kind, branch_ref, local_sha,
            declared_paths, adc_reasons, documents_by_path, previous_sha,
        )

    documents = sorted(documents_by_path.values(), key=lambda row: row["path"])
    payload = {
        "schema": SENTINEL,
        "repository": github.repo,
        "issue_number": issue_number,
        "issue_kind": kind.value,
        "from_phase": source.value,
        "to_phase": target.value,
        "adc_comment_id": verified.pointer.comment_id,
        "adc_sha256": verified.contract.sha256,
        "branch_ref": branch_ref,
        "commit_sha40": local_sha,
        "documents": documents,
        "skip_reasons": skip_reasons,
    }
    decision = PhaseDecision(_validate_payload(payload))
    return decision, issue, verified, branch_ref, local_sha


def _ready_source_and_skips(verified: VerifiedADC) -> tuple[Phase, dict[str, str]]:
    declared_paths, adc_reasons = _artifact_impacts(verified)
    if declared_paths.get("design"):
        return Phase.DESIGN, {}
    if declared_paths.get("specification"):
        return Phase.SPECIFICATION, {"design": adc_reasons.get("design", "")}
    return Phase.REQUIREMENTS, {
        key: adc_reasons.get(key, "") for key in ("specification", "design")
    }


def _ready_labels(issue: Mapping[str, Any], issue_kind: IssueKind) -> list[str]:
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PhaseEvidenceError("ready refresh requires a complete Issue label set")
    labels = [row.get("name") for row in rows]
    if (any(not isinstance(label, str) or not label for label in labels)
            or len(labels) != len(set(labels)) or parse_phase_labels(labels) is not Phase.READY
            or f"kind:{issue_kind.value}" not in labels):
        raise PhaseEvidenceError("ready refresh requires the exact open ready-phase Issue labels")
    return sorted(labels)


def _validate_ready_decision_continuation(root: Path, ready_decision: PhaseDecision,
                                         current_decision: PhaseDecision) -> None:
    immutable_fields = (
        "repository", "issue_number", "issue_kind", "from_phase", "to_phase",
        "adc_comment_id", "adc_sha256", "branch_ref", "documents", "skip_reasons",
    )
    if (any(ready_decision.payload[key] != current_decision.payload[key] for key in immutable_fields)
            or not is_ancestor(root, ready_decision.payload["commit_sha40"],
                               current_decision.payload["commit_sha40"])):
        raise PhaseEvidenceError(
            "ready preparation receipt changed a completed artifact, phase, or branch history"
        )


def _read_ready_refresh_history(github: GitHub, issue_number: int
                                ) -> tuple[tuple[int, ReadyPhaseRefresh, str], ...]:
    """Read complete Issue history and direct/list/direct verify every refresh marker."""
    try:
        first = github.issue_comments(issue_number)
        first_rows: list[dict[str, Any]] = []
        for row in first:
            body = row.get("body") if isinstance(row, dict) else None
            if isinstance(body, str) and body.startswith("<!-- PASES_PHASE_READY_REFRESH"):
                ReadyPhaseRefresh.from_body(body)
                first_rows.append(row)
        first_ids = [row.get("id") for row in first_rows]
        if (any(type(comment_id) is not int or comment_id < 1 for comment_id in first_ids)
                or first_ids != sorted(first_ids) or len(first_ids) != len(set(first_ids))):
            raise PhaseEvidenceError("ready refresh history is duplicated or not append-only")
        if not first_ids:
            return ()
        authenticated = github.authenticated_user()

        def direct_readback() -> dict[int, dict[str, Any]]:
            if not first_ids:
                return {}
            with ThreadPoolExecutor(max_workers=min(4, len(first_ids))) as executor:
                rows = list(executor.map(lambda comment_id: github.issue_comment(issue_number, comment_id), first_ids))
            return dict(zip(first_ids, rows, strict=True))

        direct_before = direct_readback()
        second = github.issue_comments(issue_number)
        second_rows = []
        for row in second:
            body = row.get("body") if isinstance(row, dict) else None
            if isinstance(body, str) and body.startswith("<!-- PASES_PHASE_READY_REFRESH"):
                ReadyPhaseRefresh.from_body(body)
                second_rows.append(row)
        second_ids = [row.get("id") if isinstance(row, dict) else None for row in second_rows]
        if second_ids != first_ids:
            raise PhaseEvidenceError("ready refresh history changed during direct/list/direct readback")
        direct_after = direct_readback()
    except GitHubError as exc:
        raise PhaseEvidenceError(f"ready refresh history readback failed: {exc}") from exc

    records: list[tuple[int, ReadyPhaseRefresh, str]] = []
    for listed, listed_again in zip(first_rows, second_rows, strict=True):
        comment_id = listed["id"]
        body = listed.get("body")
        if not isinstance(body, str):
            raise PhaseEvidenceError("ready refresh comment body is unavailable")
        fingerprints = tuple(
            _identity(row, repository=github.repo, issue_number=issue_number, authenticated=authenticated)
            for row in (direct_before[comment_id], listed_again, direct_after[comment_id])
        )
        if fingerprints[0] != fingerprints[1] or fingerprints[1] != fingerprints[2]:
            raise PhaseEvidenceError("ready refresh comment changed during direct/list/direct readback")
        record = ReadyPhaseRefresh.from_body(body)
        if (record.payload["repository"].casefold() != github.repo.casefold()
                or record.payload["issue_number"] != issue_number
                or record.payload["predecessor_comment_id"] >= comment_id):
            raise PhaseEvidenceError("ready refresh identity or predecessor order is invalid")
        records.append((comment_id, record, body))

    groups: dict[int, list[tuple[int, ReadyPhaseRefresh, str]]] = {}
    for row in records:
        groups.setdefault(row[1].payload["ready_decision_comment_id"], []).append(row)
    for decision_id, group in groups.items():
        first_record = group[0][1]
        prior_id = decision_id
        prior_digest = first_record.payload["ready_decision_sha256"]
        seen_heads: set[str] = set()
        for comment_id, record, _body in group:
            payload = record.payload
            if (payload["predecessor_comment_id"] != prior_id
                    or payload["predecessor_body_sha256"] != prior_digest
                    or payload["ready_decision_sha256"] != first_record.payload["ready_decision_sha256"]
                    or payload["commit_sha40"] in seen_heads
                    or comment_id <= prior_id):
                raise PhaseEvidenceError("ready refresh chain has a gap, duplicate, or wrong predecessor")
            invariant_keys = (
                "repository", "issue_number", "issue_kind", "phase", "adc_comment_id", "adc_sha256",
                "ready_decision_comment_id", "ready_decision_sha256", "branch_ref", "documents",
                "issue_body_sha256", "labels",
            )
            if any(payload[key] != first_record.payload[key] for key in invariant_keys):
                raise PhaseEvidenceError("ready refresh chain changed its ADC, branch, labels, or artifacts")
            seen_heads.add(payload["commit_sha40"])
            prior_id, prior_digest = comment_id, record.body_sha256
    return tuple(records)


def _ready_refresh_chain(root: Path, history: tuple[tuple[int, ReadyPhaseRefresh, str], ...],
                         *, ready_comment_id: int, ready_decision: PhaseDecision,
                         issue: Mapping[str, Any], current_decision: PhaseDecision,
                         current_labels: list[str]) -> tuple[int, ReadyPhaseRefresh, str] | None:
    selected = [row for row in history if row[1].payload["ready_decision_comment_id"] == ready_comment_id]
    if not selected:
        if ready_decision.payload["commit_sha40"] != current_decision.payload["commit_sha40"]:
            return None
        return None
    first = selected[0][1].payload
    issue_body = issue.get("body")
    if not isinstance(issue_body, str):
        raise PhaseEvidenceError("ready refresh requires the exact Issue body")
    expected_body_sha = hashlib.sha256(issue_body.encode("utf-8")).hexdigest()
    ready_body_sha = hashlib.sha256(ready_decision.body().encode("utf-8")).hexdigest()
    if (first["ready_decision_sha256"] != ready_body_sha
            or first["predecessor_comment_id"] != ready_comment_id
            or first["predecessor_body_sha256"] != ready_body_sha):
        raise PhaseEvidenceError("ready refresh chain does not start at the exact READY decision")
    prior_commit = ready_decision.payload["commit_sha40"]
    for comment_id, record, _body in selected:
        payload = record.payload
        if (payload["repository"].casefold() != current_decision.payload["repository"].casefold()
                or payload["issue_number"] != current_decision.payload["issue_number"]
                or payload["issue_kind"] != current_decision.payload["issue_kind"]
                or payload["phase"] != Phase.READY.value
                or payload["ready_decision_comment_id"] != ready_comment_id
                or payload["ready_decision_sha256"] != ready_body_sha
                or payload["issue_body_sha256"] != expected_body_sha or payload["labels"] != current_labels
                or payload["documents"] != current_decision.payload["documents"]
                or payload["adc_comment_id"] != current_decision.payload["adc_comment_id"]
                or payload["adc_sha256"] != current_decision.payload["adc_sha256"]
                or payload["branch_ref"] != current_decision.payload["branch_ref"]
                or not is_ancestor(root, prior_commit, payload["commit_sha40"])):
            raise PhaseEvidenceError("ready refresh is stale or changed a completed artifact, label, or Issue body")
        prior_commit = payload["commit_sha40"]
    latest = selected[-1]
    if not is_ancestor(root, prior_commit, current_decision.payload["commit_sha40"]):
        raise PhaseEvidenceError("current Issue HEAD no longer descends from its latest READY refresh")
    if latest[1].payload["commit_sha40"] != current_decision.payload["commit_sha40"]:
        return None
    if latest[1].payload["documents"] != current_decision.payload["documents"]:
        raise PhaseEvidenceError("current ready refresh document set differs from the exact READY decision")
    return latest


def _ready_refresh_payload(*, repository: str, issue_number: int, kind: IssueKind,
                           decision_comment_id: int, ready_decision: PhaseDecision,
                           current_decision: PhaseDecision,
                           issue_body: str, labels: list[str], predecessor_comment_id: int,
                           predecessor_body_sha256: str) -> ReadyPhaseRefresh:
    payload = {
        "schema": READY_REFRESH_SCHEMA,
        "repository": repository,
        "issue_number": issue_number,
        "issue_kind": kind.value,
        "phase": Phase.READY.value,
        "adc_comment_id": ready_decision.payload["adc_comment_id"],
        "adc_sha256": ready_decision.payload["adc_sha256"],
        "ready_decision_comment_id": decision_comment_id,
        "ready_decision_sha256": hashlib.sha256(ready_decision.body().encode("utf-8")).hexdigest(),
        "branch_ref": current_decision.payload["branch_ref"],
        "commit_sha40": current_decision.payload["commit_sha40"],
        "documents": current_decision.payload["documents"],
        "issue_body_sha256": hashlib.sha256(issue_body.encode("utf-8")).hexdigest(),
        "labels": labels,
        "predecessor_comment_id": predecessor_comment_id,
        "predecessor_body_sha256": predecessor_body_sha256,
    }
    return ReadyPhaseRefresh(_validate_ready_refresh_payload(payload))


def _ready_decision_for_context(github: GitHub, root: Path, issue_number: int,
                                context: VerifiedOrdinaryIssueContext) -> tuple[Phase, dict[str, str], PhaseDecision]:
    source, skips = _ready_source_and_skips(context.verified_adc)
    decision, _issue, _adc, _branch, _commit = _collect_payload(
        github, root, issue_number, source, Phase.READY, skips, check_source_phase=False,
        verified_context=context,
    )
    return source, skips, decision


def verify_ready_preparation(github: GitHub, root: Path, issue_number: int,
                             expected_kind: IssueKind, *,
                             verified_context: VerifiedOrdinaryIssueContext | None = None) -> PhaseDecision:
    """Rebuild exact READY evidence, including any current-HEAD refresh, before execution."""
    context = (verify_ordinary_issue_context(github, root, issue_number, expected_kind, require_binding=True)
               if verified_context is None else
               _reuse_verified_context(github, root, issue_number, expected_kind, verified_context))
    issue, verified, kind, _branch_ref, _local_sha, _binding_verified = context
    labels = _ready_labels(issue, kind)
    source, _skips, decision = _ready_decision_for_context(github, root, issue_number, context)
    decision_comment_id, stored = _find_receipt(
        github, issue_number, source=source, target=Phase.READY,
        adc_comment_id=verified.pointer.comment_id, adc_sha256=verified.contract.sha256,
    )
    _validate_ready_decision_continuation(root, stored, decision)
    history = _read_ready_refresh_history(github, issue_number)
    latest = _ready_refresh_chain(
        root, history, ready_comment_id=decision_comment_id, ready_decision=stored,
        issue=issue, current_decision=decision, current_labels=labels,
    )
    if latest is not None:
        return decision
    if stored.body() != decision.body():
        raise PhaseEvidenceError("ready preparation receipt is stale for the current Issue branch HEAD")
    return stored


def refresh_ready_phase_evidence(github: GitHub, root: Path, issue_number: int
                                ) -> tuple[int, ReadyPhaseRefresh | PhaseDecision, str]:
    """Append a current-HEAD READY attestation without changing Issue labels."""
    context = verify_ordinary_issue_context(github, root, issue_number, require_binding=True)
    issue, verified, kind, branch_ref, _commit_sha, _binding_verified = context
    labels = _ready_labels(issue, kind)
    if not isinstance(issue.get("body"), str):
        raise PhaseEvidenceError("ready refresh requires the exact Issue body")
    source, _skips, decision = _ready_decision_for_context(github, root, issue_number, context)
    decision_comment_id, ready_decision = _find_receipt(
        github, issue_number, source=source, target=Phase.READY,
        adc_comment_id=verified.pointer.comment_id, adc_sha256=verified.contract.sha256,
    )
    _validate_ready_decision_continuation(root, ready_decision, decision)
    history = _read_ready_refresh_history(github, issue_number)
    latest = _ready_refresh_chain(
        root, history, ready_comment_id=decision_comment_id, ready_decision=ready_decision,
        issue=issue, current_decision=decision, current_labels=labels,
    )
    selected_history = [row for row in history
                        if row[1].payload["ready_decision_comment_id"] == decision_comment_id]
    if latest is not None:
        return latest[0], latest[1], "NOOP"
    if ready_decision.body() == decision.body():
        return decision_comment_id, ready_decision, "CURRENT"

    previous_id = decision_comment_id if not selected_history else selected_history[-1][0]
    previous_body = ready_decision.body() if not selected_history else selected_history[-1][2]
    record = _ready_refresh_payload(
        repository=github.repo, issue_number=issue_number, kind=kind,
        decision_comment_id=decision_comment_id, ready_decision=ready_decision,
        current_decision=decision,
        issue_body=issue["body"], labels=labels, predecessor_comment_id=previous_id,
        predecessor_body_sha256=hashlib.sha256(previous_body.encode("utf-8")).hexdigest(),
    )
    # Refresh the live subject immediately before the one permitted append.
    latest_context = verify_ordinary_issue_context(github, root, issue_number, kind, require_binding=True)
    latest_issue, latest_verified, _latest_kind, latest_branch, _latest_sha, _binding_verified = latest_context
    if (latest_verified.pointer != verified.pointer or latest_verified.contract.sha256 != verified.contract.sha256
            or latest_branch != branch_ref or latest_issue.get("body") != issue.get("body")
            or _ready_labels(latest_issue, kind) != labels):
        raise PhaseEvidenceError("Issue, ADC, binding, or labels changed before ready refresh publication")
    _latest_source, _latest_skips, latest_decision = _ready_decision_for_context(
        github, root, issue_number, latest_context,
    )
    if latest_decision.body() != decision.body():
        raise PhaseEvidenceError("READY artifacts or HEAD changed before ready refresh publication")
    latest_history = _read_ready_refresh_history(github, issue_number)
    latest_chain = _ready_refresh_chain(
        root, latest_history, ready_comment_id=decision_comment_id, ready_decision=ready_decision,
        issue=latest_issue, current_decision=latest_decision, current_labels=labels,
    )
    if latest_chain is not None:
        return latest_chain[0], latest_chain[1], "NOOP"
    latest_selected_history = [row for row in latest_history
                               if row[1].payload["ready_decision_comment_id"] == decision_comment_id]
    if (latest_selected_history != selected_history
            or (latest_selected_history and latest_selected_history[-1][0] != previous_id)):
        raise PhaseEvidenceError("ready refresh history changed before publication")

    def verify_published_subject() -> None:
        after_context = verify_ordinary_issue_context(
            github, root, issue_number, kind, require_binding=True,
        )
        after_issue, after_adc, _after_kind, after_branch, _after_sha, _after_binding = after_context
        if (after_adc.pointer != verified.pointer or after_adc.contract.sha256 != verified.contract.sha256
                or after_branch != branch_ref or after_issue.get("body") != issue.get("body")
                or _ready_labels(after_issue, kind) != labels):
            raise PhaseEvidenceError("ready refresh subject changed before final readback")
        _after_source, _after_skips, after_decision = _ready_decision_for_context(
            github, root, issue_number, after_context,
        )
        if after_decision.body() != decision.body():
            raise PhaseEvidenceError("READY artifacts or HEAD changed during ready refresh publication")

    try:
        created = github.create_issue_comment(issue_number, record.body())
        comment_id = created.get("id") if isinstance(created, dict) else None
    except GitHubError as exc:
        recovered = _read_ready_refresh_history(github, issue_number)
        matches = [(comment_id, item) for comment_id, item, body in recovered if body == record.body()]
        if len(matches) != 1:
            raise PhaseEvidenceError(f"ready refresh append failed or is ambiguous: {exc}") from exc
        comment_id, record = matches[0]
        verify_published_subject()
        return comment_id, record, "RECOVERED"
    if type(comment_id) is not int or comment_id < 1:
        raise PhaseEvidenceError("ready refresh returned an invalid Issue comment ID")
    refreshed_history = _read_ready_refresh_history(github, issue_number)
    matches = [(row_id, item, body) for row_id, item, body in refreshed_history if body == record.body()]
    if len(matches) != 1 or matches[0][0] != comment_id:
        raise PhaseEvidenceError("ready refresh append is missing or duplicated after readback")
    verify_published_subject()
    return comment_id, matches[0][1], "REFRESHED"


def _identity(comment: Any, *, repository: str, issue_number: int,
              authenticated: dict[str, Any]) -> tuple[Any, ...]:
    if not isinstance(comment, dict):
        raise PhaseEvidenceError("phase evidence comment readback is malformed")
    user = comment.get("user")
    author_id = user.get("id") if isinstance(user, dict) else None
    login = user.get("login") if isinstance(user, dict) else None
    author_type = user.get("type") if isinstance(user, dict) else None
    auth_id, auth_login = authenticated.get("id"), authenticated.get("login")
    if (type(author_id) is not int or author_id < 1 or type(auth_id) is not int or auth_id < 1
            or author_id != auth_id or not isinstance(login, str) or not isinstance(auth_login, str)
            or login.casefold() != auth_login.casefold() or author_type != "User"
            or authenticated.get("type") != "User"):
        raise PhaseEvidenceError("phase evidence author is not the authenticated GitHub user")
    if type(comment.get("id")) is not int or comment["id"] < 1:
        raise PhaseEvidenceError("phase evidence comment ID is invalid")
    expected_urls = {
        "issue_url": f"https://api.github.com/repos/{repository}/issues/{issue_number}",
        "html_url": f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment['id']}",
        "url": f"https://api.github.com/repos/{repository}/issues/comments/{comment['id']}",
    }
    for key, expected in expected_urls.items():
        if comment.get(key) != expected:
            raise PhaseEvidenceError(f"phase evidence {key} does not identify this repository, Issue, and comment")
    created, updated = comment.get("created_at"), comment.get("updated_at")
    if not isinstance(created, str) or updated != created:
        raise PhaseEvidenceError("phase evidence comment was edited or has incomplete timestamps")
    for key in ("body", "issue_url", "html_url", "url"):
        if not isinstance(comment.get(key), str) or not comment[key]:
            raise PhaseEvidenceError("phase evidence comment identity fields are incomplete")
    return (comment["id"], comment["body"], created, updated, comment["issue_url"],
            comment["html_url"], comment["url"], author_id, login.casefold(), author_type)


def _readback(github: GitHub, issue_number: int, comment_id: int, expected_body: str) -> PhaseDecision:
    parsed = PhaseDecision.from_body(expected_body)
    if (parsed.payload["repository"].casefold() != github.repo.casefold()
            or parsed.payload["issue_number"] != issue_number):
        raise PhaseEvidenceError("phase evidence payload belongs to a different repository or Issue")
    try:
        authenticated = github.authenticated_user()
        snapshots: list[tuple[Any, ...]] = []
        for _ in range(2):
            first = github.issue_comment(issue_number, comment_id)
            comments = github.issue_comments(issue_number)
            if not isinstance(comments, list):
                raise PhaseEvidenceError("phase evidence Issue comment history is malformed")
            listed = [row for row in comments if isinstance(row, dict) and row.get("id") == comment_id]
            second = github.issue_comment(issue_number, comment_id)
            if len(listed) != 1:
                raise PhaseEvidenceError("phase evidence comment is missing or duplicated in Issue history")
            identities = [_identity(row, repository=github.repo, issue_number=issue_number,
                                    authenticated=authenticated)
                          for row in (first, listed[0], second)]
            if identities[0] != identities[1] or identities[1] != identities[2]:
                raise PhaseEvidenceError("phase evidence comment identity changed during readback")
            if identities[0][1] != expected_body:
                raise PhaseEvidenceError("phase evidence comment body does not match its verified payload")
            subjects: list[int] = []
            for row in comments:
                body = row.get("body") if isinstance(row, dict) else None
                if isinstance(body, str) and body.startswith(SENTINEL + "\n"):
                    candidate = PhaseDecision.from_body(body)
                    if _receipt_subject(candidate.payload) == _receipt_subject(parsed.payload):
                        subjects.append(row.get("id"))
            if subjects != [comment_id]:
                raise PhaseEvidenceError("phase evidence subject is duplicated or stale in Issue history")
            snapshots.append(identities[1])
    except GitHubError as exc:
        raise PhaseEvidenceError(f"phase evidence GitHub readback failed: {exc}") from exc
    if snapshots[0] != snapshots[1]:
        raise PhaseEvidenceError("phase evidence changed between complete readback snapshots")
    return parsed


def publish_phase_evidence(github: GitHub, root: Path, issue_number: int,
                           source: Phase, target: Phase,
                           skip_reasons: Mapping[str, str] | None = None) -> tuple[int, PhaseDecision]:
    skips = skip_reasons or {}
    decision, issue, verified, branch_ref, commit_sha = _collect_payload(
        github, root, issue_number, source, target, skips)
    body = decision.body()
    try:
        comments = github.issue_comments(issue_number)
    except GitHubError as exc:
        raise PhaseEvidenceError(f"phase evidence history read failed: {exc}") from exc
    matching: list[tuple[dict[str, Any], PhaseDecision]] = []
    for row in comments:
        text = row.get("body") if isinstance(row, dict) else None
        if isinstance(text, str) and text.startswith(SENTINEL + "\n"):
            existing = PhaseDecision.from_body(text)
            if _receipt_subject(existing.payload) == _receipt_subject(decision.payload):
                matching.append((row, existing))
    if len(matching) > 1:
        raise PhaseEvidenceError("phase evidence transition record is duplicated")
    if matching:
        row, existing = matching[0]
        if existing.body() != body:
            raise PhaseEvidenceError("existing phase evidence is stale or conflicts with the current decision")
        comment_id = row.get("id")
    else:
        try:
            latest_issue = github.issue(issue_number)
            latest_adc = verify_adc(github, issue_number)
            latest_branch = github.branch(branch_ref)
            latest_sha = latest_branch.get("commit", {}).get("sha") if isinstance(latest_branch.get("commit"), dict) else None
            if (latest_issue.get("state") != "open" or latest_issue.get("labels") != issue.get("labels")
                    or latest_adc.pointer.comment_id != verified.pointer.comment_id
                    or latest_adc.contract.sha256 != verified.contract.sha256 or latest_sha != commit_sha):
                raise PhaseEvidenceError("Issue, approved ADC, or branch changed before phase evidence publication")
            created = github.create_issue_comment(issue_number, body)
            comment_id = created.get("id") if isinstance(created, dict) else None
        except GitHubError as exc:
            # A lost POST response is recoverable only by finding this exact body once.
            try:
                matches = [row for row in github.issue_comments(issue_number)
                           if isinstance(row, dict) and row.get("body") == body]
            except GitHubError as read_exc:
                raise PhaseEvidenceError(f"phase evidence write failed and readback is unavailable: {read_exc}") from exc
            if len(matches) != 1:
                raise PhaseEvidenceError(f"phase evidence publication failed: {exc}") from exc
            comment_id = matches[0].get("id")
    if type(comment_id) is not int or comment_id < 1:
        raise PhaseEvidenceError("phase evidence publication returned an invalid Comment ID")
    return comment_id, _readback(github, issue_number, comment_id, body)


def verify_phase_evidence(github: GitHub, root: Path, issue_number: int, comment_id: int,
                          source: Phase, target: Phase,
                          skip_reasons: Mapping[str, str] | None = None) -> PhaseDecision:
    decision, _issue, _verified, _branch_ref, _commit_sha = _collect_payload(
        github, root, issue_number, source, target, skip_reasons or {})
    return _readback(github, issue_number, comment_id, decision.body())
