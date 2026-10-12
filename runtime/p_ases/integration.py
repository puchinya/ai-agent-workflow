"""Parent integration gate: verify actual child Issue and merged PR snapshots.

This is deliberately read-only. Approval and activation are separate gates.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CLOSES = re.compile(r"(?im)^Closes #([1-9][0-9]*)\s*$")


class IntegrationError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class ChildMerge:
    issue_number: int
    issue_id: int
    pr_number: int
    pr_head_sha40: str
    merge_sha40: str
    dependencies: tuple[int, ...]

    def validate(self) -> "ChildMerge":
        for value in (self.issue_number, self.issue_id, self.pr_number):
            if type(value) is not int or value < 1:
                raise IntegrationError("child/PR identity must use positive integers")
        for value in (self.pr_head_sha40, self.merge_sha40):
            if not isinstance(value, str) or not SHA40.fullmatch(value):
                raise IntegrationError("merged child SHA must be a lowercase full commit hash")
        if (type(self.dependencies) is not tuple
                or any(type(item) is not int or item < 1 for item in self.dependencies)
                or len(set(self.dependencies)) != len(self.dependencies)
                or self.issue_number in self.dependencies):
            raise IntegrationError("child dependency list is invalid")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"issue_number": self.issue_number, "issue_id": self.issue_id,
                "pr_number": self.pr_number, "pr_head_sha40": self.pr_head_sha40,
                "merge_sha40": self.merge_sha40, "dependencies": list(self.dependencies)}


@dataclass(frozen=True)
class ParentIntegrationSubject:
    repository: str
    parent_issue_number: int
    parent_adc_sha256: str
    main_sha40: str
    children: tuple[ChildMerge, ...]
    integration_verification_sha256: str | None = None
    integration_acceptance_sha256: str | None = None

    def validate(self) -> "ParentIntegrationSubject":
        if not isinstance(self.repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise IntegrationError("parent repository is invalid")
        if type(self.parent_issue_number) is not int or self.parent_issue_number < 1:
            raise IntegrationError("parent Issue number is invalid")
        if not isinstance(self.parent_adc_sha256, str) or not SHA256.fullmatch(self.parent_adc_sha256):
            raise IntegrationError("parent ADC digest is invalid")
        if not isinstance(self.main_sha40, str) or not SHA40.fullmatch(self.main_sha40):
            raise IntegrationError("parent integration main HEAD is invalid")
        if type(self.children) is not tuple:
            raise IntegrationError("parent children must be a canonical tuple")
        nums = [row.issue_number for row in self.children if isinstance(row, ChildMerge)]
        if len(nums) != len(self.children) or nums != sorted(set(nums)):
            raise IntegrationError("parent child set must be canonical, unique and sorted")
        for row in self.children:
            row.validate()
        for digest in (self.integration_verification_sha256, self.integration_acceptance_sha256):
            if digest is not None and (not isinstance(digest, str) or not SHA256.fullmatch(digest)):
                raise IntegrationError("integration evidence digest is invalid")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"repository": self.repository, "parent_issue_number": self.parent_issue_number,
                "parent_adc_sha256": self.parent_adc_sha256, "main_sha40": self.main_sha40,
                "children": [item.as_dict() for item in self.children],
                "integration_verification_sha256": self.integration_verification_sha256,
                "integration_acceptance_sha256": self.integration_acceptance_sha256}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()


@dataclass(frozen=True)
class ParentIntegrationResult:
    status: str
    subject: ParentIntegrationSubject
    reasons: tuple[str, ...]

    def validate(self) -> "ParentIntegrationResult":
        self.subject.validate()
        if self.status not in {"PASS", "BLOCKED"}:
            raise IntegrationError("parent integration verdict is invalid")
        if (self.status == "PASS" and self.reasons) or (self.status != "PASS" and not self.reasons):
            raise IntegrationError("parent integration verdict/reasons are inconsistent")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical({"status": self.status,
                                           "subject": self.subject.as_dict(),
                                           "reasons": self.reasons})).hexdigest()


def _validate_dependency_graph(expected: tuple[int, ...],
                               dependencies: Mapping[int, tuple[int, ...]]) -> tuple[int, ...]:
    if set(dependencies) != set(expected):
        raise IntegrationError("declared dependency graph does not cover the frozen child set")
    visited: set[int] = set()
    on_stack: set[int] = set()
    ordering: list[int] = []

    def visit(number: int) -> None:
        if number in on_stack:
            raise IntegrationError("native child dependency graph contains a cycle")
        if number in visited:
            return
        on_stack.add(number)
        for dep in dependencies[number]:
            if dep not in dependencies or dep == number:
                raise IntegrationError("child has an unexpected or self dependency")
            visit(dep)
        on_stack.remove(number)
        visited.add(number)
        ordering.append(number)

    for number in expected:
        visit(number)
    return tuple(ordering)


def evaluate_parent_integration(
    *,
    repository: str,
    parent_issue_number: int,
    parent_adc_sha256: str,
    main_sha40: str,
    expected_child_issue_numbers: Iterable[int],
    native_sub_issues: Iterable[dict[str, Any]],
    child_issue_rows: Iterable[dict[str, Any]],
    actual_blockers_by_issue: Mapping[int, Iterable[int]],
    declared_dependencies: Mapping[int, tuple[int, ...]],
    merged_pr_rows: Iterable[dict[str, Any]],
    integration_verification_sha256: str | None = None,
    integration_acceptance_sha256: str | None = None,
    integration_verification_pass: bool = False,
    integration_acceptance_pass: bool = False,
) -> ParentIntegrationResult:
    """Pure validation. Snapshots *must* be read from GitHub and verified adapters.

    PASS additionally requires external immutable Integration Verification and
    Acceptance PASS artifacts; booleans alone cannot substitute for digests.
    """
    expected = tuple(sorted(expected_child_issue_numbers))
    if not expected or any(type(n) is not int or n < 1 for n in expected) or len(set(expected)) != len(expected):
        raise IntegrationError("frozen child set is invalid")
    reasons: list[str] = []
    try:
        order = _validate_dependency_graph(expected, declared_dependencies)
    except IntegrationError as exc:
        order = ()
        reasons.append(str(exc))
    subs = list(native_sub_issues)
    issue_by_number: dict[int, dict[str, Any]] = {}
    ids: dict[int, int] = {}
    for row in subs:
        if not isinstance(row, dict) or type(row.get("number")) is not int or type(row.get("id")) is not int:
            reasons.append("native child identity is malformed")
            continue
        num, identifier = row["number"], row["id"]
        if num in ids or identifier in ids.values():
            reasons.append("native child set contains duplicate number or ID")
        ids[num] = identifier
    if set(ids) != set(expected):
        reasons.append("native Sub-issues differ from the frozen child set")
    for row in child_issue_rows:
        if not isinstance(row, dict) or type(row.get("number")) is not int:
            reasons.append("child Issue API row is malformed")
            continue
        if row["number"] in issue_by_number:
            reasons.append("child Issue snapshot duplicates a child")
        issue_by_number[row["number"]] = row
    if set(issue_by_number) != set(expected):
        reasons.append("child Issue snapshot does not cover the frozen child set")
    if set(actual_blockers_by_issue) != set(expected):
        reasons.append("native dependency readback is incomplete")
    else:
        for number in expected:
            row = tuple(actual_blockers_by_issue[number])
            if (any(type(item) is not int for item in row) or len(set(row)) != len(row)
                    or set(row) != {ids.get(dep) for dep in declared_dependencies.get(number, ())}):
                reasons.append(f"native blockers for child #{number} differ from the approved DAG")
    prs_by_issue: dict[int, list[dict[str, Any]]] = {n: [] for n in expected}
    for row in merged_pr_rows:
        if not isinstance(row, dict):
            reasons.append("merged PR snapshot contains malformed row")
            continue
        body = row.get("body")
        if not isinstance(body, str):
            reasons.append("merged PR body is missing")
            continue
        matched = [int(x) for x in CLOSES.findall(body)]
        if not matched:
            continue
        if len(matched) != 1:
            reasons.append("PR references multiple child closures")
            continue
        if matched[0] in prs_by_issue:
            prs_by_issue[matched[0]].append(row)
        elif matched[0] == parent_issue_number:
            reasons.append("child PR attempts to close the parent Issue")
    accepted: list[ChildMerge] = []
    for number in expected:
        issue = issue_by_number.get(number)
        if issue is None or issue.get("id") != ids.get(number) or issue.get("state") != "closed":
            reasons.append(f"child Issue #{number} is absent, mismatched, or not closed")
        prs = prs_by_issue[number]
        if len(prs) != 1:
            reasons.append(f"child Issue #{number} does not have exactly one merged matching PR")
            continue
        pr = prs[0]
        if (pr.get("state") != "closed" or pr.get("merged_at") is None
                or not isinstance(pr.get("base"), dict) or not isinstance(pr.get("head"), dict)
                or pr["base"].get("repo", {}).get("full_name", "").casefold() != repository.casefold()
                or pr["head"].get("repo", {}).get("full_name", "").casefold() != repository.casefold()):
            reasons.append(f"child PR for #{number} is unmerged, forked, or not in the repository")
            continue
        pr_number = pr.get("number")
        headsha = pr["head"].get("sha")
        mergesha = pr.get("merge_commit_sha")
        try:
            child = ChildMerge(number, ids[number], pr_number, headsha, mergesha,
                               declared_dependencies.get(number, ())).validate()
            accepted.append(child)
        except (IntegrationError, KeyError, TypeError):
            reasons.append(f"child PR for #{number} has an invalid identity or merge SHA")
    if order:
        # Verified native dependency graph, not guessed ordering.
        index = {num: pos for pos, num in enumerate(order)}
        for child in accepted:
            if any(index.get(dep, len(order)) >= index[child.issue_number] for dep in child.dependencies):
                reasons.append("child dependency ordering is inconsistent")
    if (not integration_verification_pass or not integration_verification_sha256
            or not SHA256.fullmatch(integration_verification_sha256)):
        reasons.append("parent Integration Verification PASS evidence is missing")
    if (not integration_acceptance_pass or not integration_acceptance_sha256
            or not SHA256.fullmatch(integration_acceptance_sha256)):
        reasons.append("parent Integration Acceptance PASS evidence is missing")
    subject = ParentIntegrationSubject(repository, parent_issue_number, parent_adc_sha256,
                                       main_sha40, tuple(sorted(accepted, key=lambda x: x.issue_number)),
                                       integration_verification_sha256, integration_acceptance_sha256).validate()
    return ParentIntegrationResult("BLOCKED" if reasons else "PASS", subject, tuple(dict.fromkeys(reasons))).validate()
