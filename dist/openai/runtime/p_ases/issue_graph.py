"""Parent/child Issue DAG validation, idempotent decomposition, and integration gates."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .adc import ADCError, parse_adc, parse_pointer, publish_adc, verify_adc
from .github import GitHub, GitHubError


class IssueGraphError(ValueError):
    pass


SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHILD_KEY = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
REQ_ID = re.compile(r"^REQ-[0-9]+$")
SECRET_TEXT = re.compile(
    r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{16,}|"
    r"(?:password|client[_-]?secret|authorization|api[_-]?key|access[_-]?token)"
    r"\s*[:=]\s*\S+)"
)


@dataclass(frozen=True)
class ChildPlan:
    key: str
    title: str
    body: str
    assigned_requirement_ids: tuple[str, ...]
    referenced_requirement_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    acceptance: tuple[str, ...]
    adc_bytes: bytes
    adc_sha256: str


@dataclass(frozen=True)
class ChildIssue:
    key: str
    number: int
    issue_id: int
    adc_sha256: str


@dataclass(frozen=True)
class IntegrationResult:
    passed: bool
    reasons: tuple[str, ...]
    child_set: tuple[int, ...]
    merge_sha_set: tuple[str, ...]


def _string(value: Any, label: str, *, multiline: bool = False) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise IssueGraphError(f"{label} must be non-empty text")
    if not multiline and any(c in value for c in "\r\n"):
        raise IssueGraphError(f"{label} must be a single line")
    return value.strip()


def _ids(values: Any, label: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        raise IssueGraphError(f"{label} must be a non-empty array")
    if any(not isinstance(value, str) or not pattern.fullmatch(value) for value in values):
        raise IssueGraphError(f"{label} contains an invalid identifier")
    if len(set(values)) != len(values):
        raise IssueGraphError(f"{label} contains duplicates")
    return tuple(values)


def _unique_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IssueGraphError(f"split plan contains duplicate JSON field: {key}")
        result[key] = value
    return result


def load_split_plan(path: Path, repository: str) -> tuple[int, str, tuple[str, ...], tuple[ChildPlan, ...]]:
    """Read and validate a JSON split plan; ADC paths are relative to the plan file."""
    plan_path = Path(path)
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IssueGraphError(f"could not read split plan: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {
        "parent_issue", "parent_adc_sha256", "requirement_ids", "children"
    }:
        raise IssueGraphError("split plan must contain exactly parent_issue, parent_adc_sha256, requirement_ids, and children")
    parent_issue = data["parent_issue"]
    if type(parent_issue) is not int or parent_issue < 1:
        raise IssueGraphError("split plan parent_issue must be a positive integer")
    parent_sha = data["parent_adc_sha256"]
    if not isinstance(parent_sha, str) or not SHA256.fullmatch(parent_sha):
        raise IssueGraphError("split plan parent_adc_sha256 must be lowercase SHA-256")
    requirement_ids = _ids(data["requirement_ids"], "requirement_ids", REQ_ID)
    raw_children = data["children"]
    if not isinstance(raw_children, list) or not raw_children:
        raise IssueGraphError("split plan children must be a non-empty array")
    children: list[ChildPlan] = []
    base = plan_path.parent
    expected_repo = repository.lower()
    for raw in raw_children:
        if not isinstance(raw, dict) or set(raw) != {
            "key", "title", "body", "assigned_requirement_ids", "referenced_requirement_ids",
            "dependencies", "acceptance", "adc_path",
        }:
            raise IssueGraphError("each child plan must contain exactly the documented child fields")
        key = _string(raw["key"], "child key")
        if not CHILD_KEY.fullmatch(key):
            raise IssueGraphError("child key must be lowercase kebab-case")
        title = _string(raw["title"], f"{key} title")
        body = raw["body"]
        if not isinstance(body, str):
            raise IssueGraphError(f"{key} body must be text")
        assigned = _ids(raw["assigned_requirement_ids"], f"{key} assigned_requirement_ids", REQ_ID)
        references = () if raw["referenced_requirement_ids"] == [] else _ids(
            raw["referenced_requirement_ids"], f"{key} referenced_requirement_ids", REQ_ID
        )
        dependencies = () if raw["dependencies"] == [] else _ids(
            raw["dependencies"], f"{key} dependencies", CHILD_KEY
        )
        acceptance = raw["acceptance"]
        if not isinstance(acceptance, list) or not acceptance or any(
            not isinstance(item, str) or not item.strip() for item in acceptance
        ):
            raise IssueGraphError(f"{key} acceptance must be a non-empty array of text")
        if SECRET_TEXT.search("\n".join((title, body, *acceptance))):
            raise IssueGraphError(f"{key} Issue content appears to contain a credential or secret")
        adc_path = _string(raw["adc_path"], f"{key} adc_path")
        candidate = (base / adc_path).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError as exc:
            raise IssueGraphError(f"{key} ADC path escapes the plan directory") from exc
        try:
            adc_bytes = candidate.read_bytes()
        except OSError as exc:
            raise IssueGraphError(f"could not read {key} ADC: {exc}") from exc
        try:
            adc = parse_adc(adc_bytes, expected_repo, parent_issue)
        except ADCError as exc:
            raise IssueGraphError(f"{key} ADC is invalid: {exc}") from exc
        if adc.child_key != key:
            raise IssueGraphError(f"{key} ADC Child key does not match the split plan")
        for requirement_id in assigned:
            if requirement_id not in adc.requirement_ids:
                raise IssueGraphError(f"{key} ADC does not define assigned {requirement_id}")
        for requirement_id in references:
            if requirement_id not in adc.requirement_ids:
                raise IssueGraphError(f"{key} ADC does not define referenced {requirement_id}")
        children.append(ChildPlan(
            key, title, body, assigned, references, dependencies, tuple(acceptance), adc_bytes, adc.sha256
        ))
    validate_split(parent_issue, parent_sha, requirement_ids, children)
    return parent_issue, parent_sha, requirement_ids, tuple(children)


def validate_split(parent_issue: int, parent_adc_sha256: str, requirement_ids: Iterable[str],
                   children: Iterable[ChildPlan]) -> tuple[str, ...]:
    if type(parent_issue) is not int or parent_issue < 1:
        raise IssueGraphError("parent Issue number must be positive")
    if not isinstance(parent_adc_sha256, str) or not SHA256.fullmatch(parent_adc_sha256):
        raise IssueGraphError("parent ADC SHA-256 is invalid")
    try:
        parent_requirements = tuple(requirement_ids)
    except TypeError as exc:
        raise IssueGraphError("parent REQ-ID set is invalid") from exc
    if not parent_requirements or any(not isinstance(x, str) or not REQ_ID.fullmatch(x) for x in parent_requirements):
        raise IssueGraphError("parent REQ-ID set is invalid")
    if len(set(parent_requirements)) != len(parent_requirements):
        raise IssueGraphError("parent REQ-ID set contains duplicates")
    rows = tuple(children)
    if not rows:
        raise IssueGraphError("a split requires at least one child")
    by_key: dict[str, ChildPlan] = {}
    ownership: dict[str, str] = {}
    for child in rows:
        if (not isinstance(child, ChildPlan) or not isinstance(child.key, str)
                or not CHILD_KEY.fullmatch(child.key)):
            raise IssueGraphError("child plan key is invalid")
        if child.key in by_key:
            raise IssueGraphError(f"duplicate child key: {child.key}")
        if (not isinstance(child.title, str) or not child.title.strip()
                or any(c in child.title for c in "\x00\r\n")
                or not isinstance(child.body, str) or "\x00" in child.body
                or not isinstance(child.adc_bytes, bytes)
                or not isinstance(child.assigned_requirement_ids, tuple)
                or not isinstance(child.referenced_requirement_ids, tuple)
                or not isinstance(child.dependencies, tuple)
                or not isinstance(child.acceptance, tuple)
                or any(not isinstance(item, str) or not item.strip() or any(c in item for c in "\x00\r\n")
                       for item in child.acceptance)):
            raise IssueGraphError(f"{child.key} child plan fields are invalid")
        if not child.assigned_requirement_ids:
            raise IssueGraphError(f"{child.key} must own at least one parent requirement")
        if (not isinstance(child.adc_sha256, str) or not SHA256.fullmatch(child.adc_sha256)
                or hashlib.sha256(child.adc_bytes).hexdigest() != child.adc_sha256):
            raise IssueGraphError(f"{child.key} child ADC hash does not match its exact bytes")
        if child.title.strip() == "" or not child.acceptance:
            raise IssueGraphError(f"{child.key} is missing a title or acceptance condition")
        if SECRET_TEXT.search("\n".join((child.title, child.body, *child.acceptance))):
            raise IssueGraphError(f"{child.key} Issue content appears to contain a credential or secret")
        for requirement_id in child.assigned_requirement_ids:
            if not isinstance(requirement_id, str) or not REQ_ID.fullmatch(requirement_id):
                raise IssueGraphError(f"{child.key} has an invalid assigned REQ-ID")
            if requirement_id not in parent_requirements:
                raise IssueGraphError(f"{child.key} assigns unknown parent requirement {requirement_id}")
            if requirement_id in ownership:
                raise IssueGraphError(
                    f"{requirement_id} has multiple primary owners: {ownership[requirement_id]} and {child.key}"
                )
            ownership[requirement_id] = child.key
        if any(not isinstance(item, str) or not REQ_ID.fullmatch(item)
               or item not in parent_requirements for item in child.referenced_requirement_ids):
            raise IssueGraphError(f"{child.key} references an unknown parent REQ-ID")
        if len(set(child.referenced_requirement_ids)) != len(child.referenced_requirement_ids):
            raise IssueGraphError(f"{child.key} contains duplicate referenced REQ-IDs")
        by_key[child.key] = child
    missing = sorted(set(parent_requirements) - ownership.keys())
    if missing:
        raise IssueGraphError("parent requirements have no primary child owner: " + ", ".join(missing))
    for child in rows:
        if any(not isinstance(item, str) or not CHILD_KEY.fullmatch(item) for item in child.dependencies):
            raise IssueGraphError(f"{child.key} contains an invalid dependency key")
        if len(set(child.dependencies)) != len(child.dependencies):
            raise IssueGraphError(f"{child.key} contains duplicate dependency keys")
        if child.key in child.dependencies:
            raise IssueGraphError(f"{child.key} cannot depend on itself")
        missing_dependencies = sorted(set(child.dependencies) - by_key.keys())
        if missing_dependencies:
            raise IssueGraphError(f"{child.key} has missing dependencies: " + ", ".join(missing_dependencies))
    return topological_order(rows)


def topological_order(children: Iterable[ChildPlan]) -> tuple[str, ...]:
    rows = {child.key: child for child in children}
    indegree = {key: len(set(child.dependencies)) for key, child in rows.items()}
    dependents: dict[str, set[str]] = {key: set() for key in rows}
    for key, child in rows.items():
        for dependency in set(child.dependencies):
            if dependency not in rows:
                raise IssueGraphError(f"{key} has missing dependency {dependency}")
            dependents[dependency].add(key)
    ready = sorted(key for key, count in indegree.items() if count == 0)
    order: list[str] = []
    while ready:
        key = ready.pop(0)
        order.append(key)
        for dependent in sorted(dependents[key]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort()
    if len(order) != len(rows):
        raise IssueGraphError("child dependency graph contains a cycle")
    return tuple(order)


def _child_marker(key: str, parent_issue: int, parent_sha: str, child_sha: str) -> str:
    return (f"<!-- PASES_CHILD_V1 child_key={key} parent_issue={parent_issue} "
            f"parent_adc_sha256={parent_sha} child_adc_sha256={child_sha} -->")


def _outside_fence_lines(text: str) -> tuple[str, ...]:
    """Return Markdown lines outside fenced code blocks."""
    result: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        if fence is not None:
            marker, length = fence
            if re.match(rf"^ {{0,3}}{re.escape(marker)}{{{length},}}[ \t]*$", line):
                fence = None
            continue
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match and (match.group(1)[0] == "~" or "`" not in match.group(2)):
            fence = (match.group(1)[0], len(match.group(1)))
            continue
        result.append(line)
    return tuple(result)


def _has_marker(body: str, marker: str) -> bool:
    return sum(line == marker for line in _outside_fence_lines(body)) == 1


def find_existing_child(issues: Iterable[dict[str, Any]], key: str, parent_issue: int,
                        parent_sha: str, child_sha: str) -> dict[str, Any] | None:
    exact = _child_marker(key, parent_issue, parent_sha, child_sha)
    prefix = (f"<!-- PASES_CHILD_V1 child_key={key} parent_issue={parent_issue} "
              f"parent_adc_sha256={parent_sha} child_adc_sha256=")
    matches: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("pull_request") is not None:
            continue
        body = issue.get("body")
        if not isinstance(body, str):
            continue
        markers = [line for line in _outside_fence_lines(body) if line.startswith(prefix) and line.endswith(" -->")]
        exact_count = markers.count(exact)
        if exact_count > 1:
            raise IssueGraphError(f"child key {key} has duplicate idempotency markers")
        if exact_count == 1:
            matches.append(issue)
        elif markers:
            raise IssueGraphError(f"child key {key} already exists with a different ADC under this parent contract")
    if len(matches) > 1:
        raise IssueGraphError(f"duplicate GitHub Issues exist for idempotency key {key}/{parent_sha}")
    return matches[0] if matches else None


def _child_issue_body(parent_issue: int, parent_sha: str, child: ChildPlan) -> str:
    marker = _child_marker(child.key, parent_issue, parent_sha, child.adc_sha256)
    requirements = ", ".join(child.assigned_requirement_ids)
    references = ", ".join(child.referenced_requirement_ids) if child.referenced_requirement_ids else "none"
    dependencies = ", ".join(child.dependencies) if child.dependencies else "none"
    acceptance = "\n".join(f"- {item}" for item in child.acceptance)
    summary = child.body.strip()
    if not summary:
        summary = f"Child of #{parent_issue}; implementation scope is defined by the immutable ADC comment."
    summary = "\n".join(f"> {line}" if line else ">" for line in summary.splitlines())
    return (
        f"{marker}\n\nChild of #{parent_issue}.\n\n"
        f"- child_key: `{child.key}`\n"
        f"- parent_issue: #{parent_issue}\n"
        f"- parent_adc_sha256: `{parent_sha}`\n"
        f"- assigned_requirement_ids: {requirements}\n"
        f"- referenced_requirement_ids: {references}\n"
        f"- dependencies: {dependencies}\n"
        f"- child_adc_sha256: `{child.adc_sha256}`\n\n"
        f"## Summary\n\n{summary}\n\n## Acceptance\n\n{acceptance}\n\n"
        f"## ADC Publication\n\nThe append-only ADC pointer record follows comment readback."
    )


def split_issue(github: GitHub, parent_issue: int, parent_adc_sha256: str,
                requirement_ids: Iterable[str], children: Iterable[ChildPlan]) -> tuple[ChildIssue, ...]:
    """Create/reuse child Issues and ADCs, then attach native Sub-issues and dependency edges."""
    rows = tuple(children)
    order = validate_split(parent_issue, parent_adc_sha256, requirement_ids, rows)
    by_key = {child.key: child for child in rows}
    for child in rows:
        try:
            contract = parse_adc(child.adc_bytes, github.repo, parent_issue)
        except ADCError as exc:
            raise IssueGraphError(f"{child.key} child ADC is invalid: {exc}") from exc
        if contract.child_key != child.key:
            raise IssueGraphError(f"{child.key} child ADC key does not match its plan")
        if not set(child.assigned_requirement_ids + child.referenced_requirement_ids).issubset(
            contract.requirement_ids
        ):
            raise IssueGraphError(f"{child.key} child ADC omits an assigned or referenced parent requirement")
    try:
        parent = github.issue(parent_issue)
        verified_parent = verify_adc(github, parent_issue)
        if verified_parent.contract.sha256 != parent_adc_sha256:
            raise IssueGraphError("parent ADC changed after the split plan was prepared")
        if verified_parent.pointer.state != "approved":
            raise IssueGraphError("parent ADC must be approved before creating executable child ADCs")
        if parent.get("state") != "open":
            raise IssueGraphError("parent Issue must remain open while its children are created")
        existing_issues = github.issues()
    except (ADCError, GitHubError) as exc:
        raise IssueGraphError(str(exc)) from exc

    resolved: dict[str, ChildIssue] = {}
    for key in order:
        child = by_key[key]
        existing = find_existing_child(existing_issues, key, parent_issue, parent_adc_sha256, child.adc_sha256)
        if existing is None:
            try:
                created = github.create_issue(
                    child.title, _child_issue_body(parent_issue, parent_adc_sha256, child), ["enhancement"]
                )
                number = created["number"]
                issue_record = github.issue(number)
            except GitHubError as exc:
                raise IssueGraphError(f"could not create child Issue {key}: {exc}") from exc
        else:
            issue_record = existing
            number = issue_record.get("number")
            if type(number) is not int or number < 1:
                raise IssueGraphError(f"existing child Issue {key} has an invalid number")
            if issue_record.get("state") != "open":
                raise IssueGraphError(f"existing child Issue {key} is not open")
        issue_id = issue_record.get("id")
        if type(issue_id) is not int or issue_id < 1 or issue_record.get("pull_request") is not None:
            raise IssueGraphError(f"child {key} readback is not a GitHub Issue")
        marker = _child_marker(key, parent_issue, parent_adc_sha256, child.adc_sha256)
        if not _has_marker(issue_record.get("body") or "", marker):
            raise IssueGraphError(f"child {key} Issue marker failed readback")
        pointer = parse_pointer(issue_record.get("body") or "")
        if pointer is None:
            try:
                publish_adc(github, number, child.adc_bytes, state="approved", explicitly_approved=True)
                issue_record = github.issue(number)
            except (ADCError, GitHubError) as exc:
                raise IssueGraphError(f"could not publish child ADC {key}: {exc}") from exc
        else:
            try:
                verified_child = verify_adc(github, number)
            except (ADCError, GitHubError) as exc:
                raise IssueGraphError(f"existing child ADC {key} failed verification: {exc}") from exc
            if (verified_child.contract.sha256 != child.adc_sha256
                    or verified_child.pointer.state != "approved"):
                raise IssueGraphError(f"existing child ADC {key} differs from the approved split plan")
        resolved[key] = ChildIssue(key, number, issue_id, child.adc_sha256)
        # Update the in-memory collection so a later retry within this invocation sees the new child.
        existing_issues = [item for item in existing_issues if item.get("number") != number] + [issue_record]

    try:
        for key in order:
            github.add_sub_issue(parent_issue, resolved[key].issue_id)
        for key in order:
            child = by_key[key]
            for dependency in child.dependencies:
                github.add_blocked_by(resolved[key].number, resolved[dependency].issue_id)
        subissues = github.sub_issues(parent_issue)
        expected_ids = {item.issue_id for item in resolved.values()}
        actual_ids = {item.get("id") for item in subissues}
        if actual_ids != expected_ids:
            raise IssueGraphError("native Sub-issue readback differs from the declared child set")
        for key, child in by_key.items():
            actual = {item.get("id") for item in github.blocked_by(resolved[key].number)}
            expected = {resolved[dependency].issue_id for dependency in child.dependencies}
            if actual != expected:
                raise IssueGraphError(f"native dependency readback differs from {key}'s declared dependencies")
    except GitHubError as exc:
        raise IssueGraphError(f"native Issue relation write/readback failed: {exc}") from exc
    return tuple(resolved[key] for key in order)


def _issue_bullet(body: str, name: str) -> str:
    outside_fence = "\n".join(_outside_fence_lines(body))
    matches = re.findall(rf"(?m)^- {re.escape(name)}:[ \t]*(.*?)[ \t]*$", outside_fence)
    if len(matches) != 1:
        raise IssueGraphError(f"child Issue must contain exactly one {name} metadata line")
    return matches[0].strip().strip("`")


def _id_list(value: str, label: str) -> tuple[str, ...]:
    if value == "none":
        return ()
    items = tuple(item.strip() for item in value.split(","))
    if not items or any(not item for item in items) or len(set(items)) != len(items):
        raise IssueGraphError(f"child Issue {label} metadata is invalid")
    return items


def validate_native_issue_graph(github: GitHub, parent_issue: int) -> tuple[str, ...]:
    """Read back the approved parent ADC, child contracts, and every native relation."""
    try:
        parent_record = github.issue(parent_issue)
        verified_parent = verify_adc(github, parent_issue)
        if parent_record.get("state") != "open" or verified_parent.pointer.state != "approved":
            raise IssueGraphError("parent Issue must be open with an approved ADC")
        subissues = github.sub_issues(parent_issue)
    except (ADCError, GitHubError) as exc:
        raise IssueGraphError(str(exc)) from exc
    if not subissues:
        raise IssueGraphError("parent Issue has no native Sub-issues")

    children: list[ChildPlan] = []
    records_by_id: dict[int, dict[str, Any]] = {}
    records_by_key: dict[str, dict[str, Any]] = {}
    number_by_key: dict[str, int] = {}
    for subissue in subissues:
        number, issue_id = subissue.get("number"), subissue.get("id")
        if type(number) is not int or number < 1 or type(issue_id) is not int or issue_id < 1:
            raise IssueGraphError("native Sub-issue readback has an invalid identity")
        if issue_id in records_by_id or number in {item.get("number") for item in records_by_id.values()}:
            raise IssueGraphError("native Sub-issue readback contains duplicates")
        try:
            issue_record = github.issue(number)
            if (issue_record.get("id") != issue_id or issue_record.get("number") != number
                    or issue_record.get("state") != "open" or issue_record.get("pull_request") is not None):
                raise IssueGraphError(f"child Issue #{number} must be open and not a pull request")
            body = issue_record.get("body")
            if not isinstance(body, str):
                raise IssueGraphError(f"child Issue #{number} has no body")
            key = _issue_bullet(body, "child_key")
            assigned = _id_list(_issue_bullet(body, "assigned_requirement_ids"), "assigned_requirement_ids")
            referenced = _id_list(_issue_bullet(body, "referenced_requirement_ids"), "referenced_requirement_ids")
            dependencies = _id_list(_issue_bullet(body, "dependencies"), "dependencies")
            parent_sha = _issue_bullet(body, "parent_adc_sha256")
            child_sha = _issue_bullet(body, "child_adc_sha256")
            if parent_sha != verified_parent.contract.sha256:
                raise IssueGraphError(f"child Issue #{number} belongs to a different parent ADC")
            child_adc = verify_adc(github, number)
            if child_adc.pointer.state != "approved" or child_adc.contract.sha256 != child_sha:
                raise IssueGraphError(f"child Issue #{number} ADC pointer does not match its issue metadata")
            marker = _child_marker(key, parent_issue, parent_sha, child_sha)
            if not _has_marker(body, marker) or child_adc.contract.child_key != key:
                raise IssueGraphError(f"child Issue #{number} identity marker does not match its ADC")
            outside_fence = "\n".join(_outside_fence_lines(body))
            acceptance_match = re.search(
                r"(?ms)^## Acceptance[ \t]*\n(.*?)(?=^##[ \t]+|\Z)", outside_fence
            )
            acceptance = tuple(
                line[2:].strip() for line in (acceptance_match.group(1).splitlines() if acceptance_match else [])
                if line.startswith("- ") and line[2:].strip()
            )
            if not acceptance:
                raise IssueGraphError(f"child Issue #{number} has no acceptance conditions")
            plan = ChildPlan(
                key, _string(issue_record.get("title"), f"{key} title"), "", assigned, referenced,
                dependencies, acceptance, child_adc.contract.content, child_adc.contract.sha256,
            )
        except (ADCError, GitHubError) as exc:
            raise IssueGraphError(f"child Issue #{number} readback failed: {exc}") from exc
        if key in records_by_key:
            raise IssueGraphError(f"duplicate child key in native Sub-issues: {key}")
        records_by_id[issue_id] = issue_record
        records_by_key[key] = issue_record
        number_by_key[key] = number
        children.append(plan)

    order = validate_split(
        parent_issue, verified_parent.contract.sha256, verified_parent.contract.requirement_ids, children
    )
    issue_id_by_key = {key: record["id"] for key, record in records_by_key.items()}
    try:
        for child in children:
            number = number_by_key[child.key]
            actual_blockers = {item.get("id") for item in github.blocked_by(number)}
            expected_blockers = {issue_id_by_key[key] for key in child.dependencies}
            if actual_blockers != expected_blockers:
                raise IssueGraphError(f"native dependency readback differs from {child.key}'s ADC plan")
    except GitHubError as exc:
        raise IssueGraphError(f"native dependency readback failed: {exc}") from exc
    return order


def validate_parent_integration(children: Iterable[dict[str, Any]], expected_issue_numbers: Iterable[int],
                                expected_merge_shas: Iterable[str], *, verification_passed: bool) -> IntegrationResult:
    try:
        supplied_issues = tuple(expected_issue_numbers)
        supplied_shas = tuple(expected_merge_shas)
        child_rows = tuple(children)
    except TypeError as exc:
        raise IssueGraphError("parent integration inputs must be iterable") from exc
    if any(type(number) is not int or number < 1 for number in supplied_issues):
        raise IssueGraphError("expected child Issue numbers must be positive integers")
    if any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in supplied_shas):
        raise IssueGraphError("expected child merge SHAs must be full lowercase commit IDs")
    expected_issues = tuple(sorted(supplied_issues))
    expected_shas = tuple(sorted(supplied_shas))
    reasons: list[str] = []
    status_rows = [item for item in child_rows if isinstance(item, dict)]
    if len(status_rows) != len(child_rows):
        reasons.append("child status contains a malformed record")
    records: dict[int, dict[str, Any]] = {}
    for item in status_rows:
        number = item.get("number")
        if type(number) is not int or number < 1:
            reasons.append("child status contains an invalid Issue number")
            continue
        if number in records:
            reasons.append("child status contains duplicate Issue numbers")
            continue
        records[number] = item
    if len(records) != len(status_rows):
        reasons.append("child status contains duplicate Issue numbers")
    if tuple(sorted(records)) != expected_issues:
        reasons.append("child issue set does not match the frozen parent child set")
    merge_shas: list[str] = []
    for issue_number in expected_issues:
        item = records.get(issue_number)
        if item is None or item.get("state") != "closed":
            reasons.append(f"child Issue #{issue_number} is not closed")
            continue
        if item.get("merged") is not True:
            reasons.append(f"child Issue #{issue_number} has no merged PR evidence")
            continue
        sha = item.get("merge_sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            reasons.append(f"child Issue #{issue_number} has no valid merge SHA")
        else:
            merge_shas.append(sha)
    if tuple(sorted(merge_shas)) != expected_shas:
        reasons.append("child merge SHA set does not match the frozen parent merge SHA set")
    if verification_passed is not True:
        reasons.append("parent integration Verification did not pass")
    return IntegrationResult(not reasons, tuple(reasons), expected_issues, tuple(sorted(merge_shas)))
