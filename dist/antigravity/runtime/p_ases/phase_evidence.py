"""ADC-bound phase decision receipts for the ordinary Issue lifecycle."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
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


SENTINEL = "PASES_PHASE_DECISION_V1"
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


def _artifact_impacts(verified: VerifiedADC) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    text = verified.contract.section("artifact_impact")
    lines: dict[str, str] = {}
    for match in IMPACT_LINE.finditer(text):
        role = {"Specification": "specification", "Design": "design", "Testing": "test-oracle"}[match.group(1)]
        if role in lines:
            raise PhaseEvidenceError(f"approved ADC duplicates its {match.group(1)} artifact impact")
        lines[role] = match.group(2).strip()
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
    try:
        binding = read_binding(execution_binding_path(root.resolve(), issue_number))
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
                                 ) -> tuple[dict[str, Any], VerifiedADC, IssueKind, str, str]:
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
        return issue, verified, kind, branch_ref, local_sha
    except (ADCError, GitHubError, GitError) as exc:
        raise PhaseEvidenceError(str(exc)) from exc


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
                     skips: Mapping[str, str], *, check_source_phase: bool = True
                     ) -> tuple[PhaseDecision, dict[str, Any], VerifiedADC, str, str]:
    if type(issue_number) is not int or issue_number < 1:
        raise PhaseEvidenceError("Issue number must be a positive integer")
    issue, verified, kind, branch_ref, local_sha = verify_ordinary_issue_context(
        github, root, issue_number, require_binding=True,
    )
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


def verify_ready_preparation(github: GitHub, root: Path, issue_number: int,
                             expected_kind: IssueKind) -> PhaseDecision:
    """Rebuild and reread the exact ready receipt before entering implementation."""
    issue, verified, kind, _branch_ref, _local_sha = verify_ordinary_issue_context(
        github, root, issue_number, expected_kind, require_binding=True,
    )
    labels = [row.get("name") for row in issue.get("labels", []) if isinstance(row, dict)]
    if parse_phase_labels(labels) is not Phase.READY:
        raise PhaseEvidenceError("execution requires the Issue to be in the ready phase")
    declared_paths, adc_reasons = _artifact_impacts(verified)
    if declared_paths.get("specification") and declared_paths.get("design"):
        source, skips = Phase.DESIGN, {}
    elif declared_paths.get("design"):
        source, skips = Phase.DESIGN, {}
    elif declared_paths.get("specification"):
        source, skips = Phase.SPECIFICATION, {"design": adc_reasons.get("design", "")}
    else:
        source = Phase.REQUIREMENTS
        skips = {key: adc_reasons.get(key, "") for key in ("specification", "design")}
    decision, _issue, _adc, _branch, _commit = _collect_payload(
        github, root, issue_number, source, Phase.READY, skips, check_source_phase=False,
    )
    _comment_id, stored = _find_receipt(
        github, issue_number, source=source, target=Phase.READY,
        adc_comment_id=verified.pointer.comment_id, adc_sha256=verified.contract.sha256,
    )
    if stored.body() != decision.body():
        raise PhaseEvidenceError("ready preparation receipt is stale for the current Issue branch HEAD")
    return stored


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
