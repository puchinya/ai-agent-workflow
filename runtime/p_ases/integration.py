"""Parent integration gate: verify actual child Issue and merged PR snapshots.

This is deliberately read-only. Approval and activation are separate gates.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CLOSES = re.compile(r"(?im)^Closes #([1-9][0-9]*)\s*$")


class IntegrationError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class ParentGateEvidenceComment:
    """Canonical external evidence payload posted to the fixed parent Issue.

    The Issue comment is outside the main commit it names, avoiding a Git
    self-reference. It binds an exact Actions run ID/attempt; the runtime
    reconstructs its bytes from GitHub job, step, and Check Run responses.
    The comment itself remains mutable GitHub storage and is double-read.
    """

    kind: str
    repository: str
    parent_issue_number: int
    parent_adc_sha256: str
    main_sha40: str
    workflow_run_id: int
    workflow_run_attempt: int
    workflow_path: str
    result_bytes: bytes
    artifacts: tuple[tuple[str, bytes], ...]

    def validate(self) -> "ParentGateEvidenceComment":
        if not isinstance(self.kind, str) or self.kind not in {"verification", "acceptance"}:
            raise IntegrationError("parent evidence comment kind is invalid")
        if not isinstance(self.repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise IntegrationError("parent evidence comment repository is invalid")
        if type(self.parent_issue_number) is not int or self.parent_issue_number < 1:
            raise IntegrationError("parent evidence comment Issue number is invalid")
        if not isinstance(self.parent_adc_sha256, str) or not SHA256.fullmatch(self.parent_adc_sha256):
            raise IntegrationError("parent evidence comment ADC digest is invalid")
        if not isinstance(self.main_sha40, str) or not SHA40.fullmatch(self.main_sha40):
            raise IntegrationError("parent evidence comment main SHA is invalid")
        if type(self.workflow_run_id) is not int or self.workflow_run_id < 1:
            raise IntegrationError("parent evidence comment workflow run ID is invalid")
        if type(self.workflow_run_attempt) is not int or self.workflow_run_attempt < 1:
            raise IntegrationError("parent evidence comment workflow attempt is invalid")
        expected_workflow = (".github/workflows/ci.yml" if self.kind == "verification"
                             else ".github/workflows/parent-integration.yml")
        if self.workflow_path != expected_workflow:
            raise IntegrationError("parent evidence comment workflow path is not trusted for this evidence kind")
        if not isinstance(self.result_bytes, bytes) or not self.result_bytes:
            raise IntegrationError("parent evidence comment result bytes are missing")
        if type(self.artifacts) is not tuple or not self.artifacts:
            raise IntegrationError("parent evidence comment artifacts are missing")
        references: list[str] = []
        for row in self.artifacts:
            if (type(row) is not tuple or len(row) != 2 or not isinstance(row[0], str)
                    or not isinstance(row[1], bytes) or not row[1]):
                raise IntegrationError("parent evidence comment artifact row is malformed")
            reference = row[0]
            if (reference.startswith("/") or "\\" in reference
                    or any(part in {"", ".", ".."} for part in reference.split("/"))
                    or any(char in reference for char in "\x00\r\n?#:")):
                raise IntegrationError("parent evidence comment artifact reference is invalid")
            references.append(reference)
        if references != sorted(set(references)):
            raise IntegrationError("parent evidence comment artifacts must be sorted and unique")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "artifacts": [{"reference": reference,
                           "sha256": hashlib.sha256(content).hexdigest(),
                           "content_base64": base64.b64encode(content).decode("ascii")}
                          for reference, content in self.artifacts],
            "kind": self.kind,
            "main_sha40": self.main_sha40,
            "parent_adc_sha256": self.parent_adc_sha256,
            "parent_issue_number": self.parent_issue_number,
            "repository": self.repository,
            "result_base64": base64.b64encode(self.result_bytes).decode("ascii"),
            "result_sha256": hashlib.sha256(self.result_bytes).hexdigest(),
            "workflow_path": self.workflow_path,
            "workflow_run_attempt": self.workflow_run_attempt,
            "workflow_run_id": self.workflow_run_id,
            "schema": "PASES_PARENT_GATE_EVIDENCE_COMMENT_V2",
        }

    def to_body(self) -> str:
        payload = self.payload()
        payload["payload_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
        return "P-ASES-PARENT-EVIDENCE-V2\n" + _canonical(payload).decode("utf-8") + "\n"

    @classmethod
    def from_body(cls, body: Any) -> "ParentGateEvidenceComment":
        if not isinstance(body, str) or not body.startswith("P-ASES-PARENT-EVIDENCE-V2\n"):
            raise IntegrationError("Issue comment is not a parent evidence record")
        raw = body[len("P-ASES-PARENT-EVIDENCE-V2\n"):].encode("utf-8")
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrationError("parent evidence comment is not valid canonical JSON") from exc
        expected = {"artifacts", "kind", "main_sha40", "parent_adc_sha256", "parent_issue_number",
                    "repository", "result_base64", "result_sha256", "workflow_path",
                    "workflow_run_attempt", "workflow_run_id", "schema", "payload_sha256"}
        if not isinstance(value, dict) or set(value) != expected:
            raise IntegrationError("parent evidence comment has unknown or missing fields")
        if value["schema"] != "PASES_PARENT_GATE_EVIDENCE_COMMENT_V2":
            raise IntegrationError("parent evidence comment schema is unknown")
        digest_payload = {key: item for key, item in value.items() if key != "payload_sha256"}
        if (value["payload_sha256"] != hashlib.sha256(_canonical(digest_payload)).hexdigest()
                or raw != _canonical(value) + b"\n"):
            raise IntegrationError("parent evidence comment digest or canonical bytes do not match")
        try:
            result_bytes = base64.b64decode(value["result_base64"], validate=True)
        except (TypeError, ValueError) as exc:
            raise IntegrationError("parent evidence result bytes are malformed") from exc
        if hashlib.sha256(result_bytes).hexdigest() != value["result_sha256"]:
            raise IntegrationError("parent evidence result digest does not match its bytes")
        rows = value["artifacts"]
        if not isinstance(rows, list):
            raise IntegrationError("parent evidence artifact list is malformed")
        artifacts: list[tuple[str, bytes]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"reference", "sha256", "content_base64"}:
                raise IntegrationError("parent evidence artifact row has unknown or missing fields")
            try:
                content = base64.b64decode(row["content_base64"], validate=True)
            except (TypeError, ValueError) as exc:
                raise IntegrationError("parent evidence artifact bytes are malformed") from exc
            if hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise IntegrationError("parent evidence artifact digest does not match its bytes")
            artifacts.append((row["reference"], content))
        return cls(value["kind"], value["repository"], value["parent_issue_number"],
                   value["parent_adc_sha256"], value["main_sha40"],
                   value["workflow_run_id"], value["workflow_run_attempt"], value["workflow_path"],
                   result_bytes, tuple(artifacts)).validate()


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise IntegrationError("child PR merge timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrationError("child PR merge timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IntegrationError("child PR merge timestamp must include a timezone")
    return parsed


@dataclass(frozen=True)
class ChildMerge:
    issue_number: int
    issue_id: int
    pr_number: int
    pr_head_sha40: str
    merge_sha40: str
    merged_at: str
    dependencies: tuple[int, ...]
    merge_sha_in_main: bool

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
        _time(self.merged_at)
        if type(self.merge_sha_in_main) is not bool:
            raise IntegrationError("child merge ancestry must be a verified boolean")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"issue_number": self.issue_number, "issue_id": self.issue_id,
                "pr_number": self.pr_number, "pr_head_sha40": self.pr_head_sha40,
                "merge_sha40": self.merge_sha40, "merged_at": self.merged_at,
                "dependencies": list(self.dependencies),
                "merge_sha_in_main": self.merge_sha_in_main}


@dataclass(frozen=True)
class IntegrationGateEvidence:
    """Typed immutable evidence bound to the final parent/main integration subject."""

    kind: str
    repository: str
    parent_issue_number: int
    parent_adc_sha256: str
    main_sha40: str
    status: str
    result_sha256: str
    source_reference: str

    def validate(self) -> "IntegrationGateEvidence":
        if not isinstance(self.kind, str) or self.kind not in {"verification", "acceptance"}:
            raise IntegrationError("parent evidence kind must be verification or acceptance")
        if not isinstance(self.repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise IntegrationError("parent evidence repository is invalid")
        if type(self.parent_issue_number) is not int or self.parent_issue_number < 1:
            raise IntegrationError("parent evidence Issue number is invalid")
        if not isinstance(self.parent_adc_sha256, str) or not SHA256.fullmatch(self.parent_adc_sha256):
            raise IntegrationError("parent evidence ADC digest is invalid")
        if not isinstance(self.main_sha40, str) or not SHA40.fullmatch(self.main_sha40):
            raise IntegrationError("parent evidence main SHA is invalid")
        if self.status != "PASS" or not isinstance(self.result_sha256, str) or not SHA256.fullmatch(self.result_sha256):
            raise IntegrationError("parent evidence must be an exact PASS result with a digest")
        if (not isinstance(self.source_reference, str)
                or not re.fullmatch(r"issue-comment:[1-9][0-9]*", self.source_reference)):
            raise IntegrationError("parent evidence source must identify an exact Issue comment ID")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"kind": self.kind, "repository": self.repository,
                "parent_issue_number": self.parent_issue_number,
                "parent_adc_sha256": self.parent_adc_sha256, "main_sha40": self.main_sha40,
                "status": self.status, "result_sha256": self.result_sha256,
                "source_reference": self.source_reference}

    def to_bytes(self) -> bytes:
        value = {**self.as_dict(), "schema": "PASES_PARENT_INTEGRATION_EVIDENCE_V1",
                 "evidence_sha256": self.sha256}
        return _canonical(value) + b"\n"

    @classmethod
    def from_dict(cls, value: Any) -> "IntegrationGateEvidence":
        expected = {"kind", "repository", "parent_issue_number", "parent_adc_sha256", "main_sha40",
                    "status", "result_sha256", "source_reference", "schema", "evidence_sha256"}
        if not isinstance(value, dict) or set(value) != expected:
            raise IntegrationError("parent integration evidence has unknown or missing fields")
        if value["schema"] != "PASES_PARENT_INTEGRATION_EVIDENCE_V1":
            raise IntegrationError("parent integration evidence schema is unknown")
        evidence = cls(value["kind"], value["repository"], value["parent_issue_number"],
                       value["parent_adc_sha256"], value["main_sha40"], value["status"],
                       value["result_sha256"], value["source_reference"]).validate()
        if value["evidence_sha256"] != evidence.sha256 or evidence.to_bytes() != _canonical(value) + b"\n":
            raise IntegrationError("parent integration evidence digest or bytes do not match")
        return evidence

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()


@dataclass(frozen=True)
class ParentIntegrationSubject:
    repository: str
    parent_issue_number: int
    parent_adc_sha256: str
    main_sha40: str
    children: tuple[ChildMerge, ...]
    integration_verification_sha256: str | None = None
    integration_acceptance_sha256: str | None = None
    expected_child_issue_numbers: tuple[int, ...] = ()
    declared_dependency_graph: tuple[tuple[int, tuple[int, ...]], ...] = ()

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
        if any(not isinstance(row, ChildMerge) for row in self.children):
            raise IntegrationError("parent child merge record is malformed")
        for row in self.children:
            row.validate()
        nums = [row.issue_number for row in self.children]
        if nums != sorted(set(nums)):
            raise IntegrationError("parent child set must be canonical, unique and sorted")
        if (type(self.expected_child_issue_numbers) is not tuple
                or not self.expected_child_issue_numbers
                or any(type(number) is not int or number < 1 for number in self.expected_child_issue_numbers)
                or self.expected_child_issue_numbers != tuple(sorted(set(self.expected_child_issue_numbers)))
                or not set(nums).issubset(self.expected_child_issue_numbers)):
            raise IntegrationError("parent expected child set is invalid or incomplete")
        if (type(self.declared_dependency_graph) is not tuple
                or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not int
                       for row in self.declared_dependency_graph)
                or self.declared_dependency_graph != tuple(sorted(self.declared_dependency_graph))
                or tuple(number for number, _dependencies in self.declared_dependency_graph)
                != self.expected_child_issue_numbers):
            raise IntegrationError("parent dependency graph must cover the exact frozen child set")
        for number, dependencies in self.declared_dependency_graph:
            if (type(number) is not int or number not in self.expected_child_issue_numbers
                    or type(dependencies) is not tuple
                    or any(type(dependency) is not int or dependency < 1 or dependency == number
                           for dependency in dependencies)
                    or dependencies != tuple(sorted(set(dependencies)))):
                raise IntegrationError("parent dependency graph contains invalid edges")
        merges = [row.merge_sha40 for row in self.children]
        if len(merges) != len(set(merges)):
            raise IntegrationError("parent merge SHA set contains duplicate commits")
        for digest in (self.integration_verification_sha256, self.integration_acceptance_sha256):
            if digest is not None and (not isinstance(digest, str) or not SHA256.fullmatch(digest)):
                raise IntegrationError("integration evidence digest is invalid")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"repository": self.repository, "parent_issue_number": self.parent_issue_number,
                "parent_adc_sha256": self.parent_adc_sha256, "main_sha40": self.main_sha40,
                "children": [item.as_dict() for item in self.children],
                "expected_child_issue_numbers": list(self.expected_child_issue_numbers),
                "declared_dependency_graph": [
                    {"issue_number": number, "dependencies": list(dependencies)}
                    for number, dependencies in self.declared_dependency_graph
                ],
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
        if self.status == "PASS":
            actual = tuple(row.issue_number for row in self.subject.children)
            if (actual != self.subject.expected_child_issue_numbers
                    or any(not row.merge_sha_in_main for row in self.subject.children)
                    or self.subject.integration_verification_sha256 is None
                    or self.subject.integration_acceptance_sha256 is None
                    or any(dependency not in self.subject.expected_child_issue_numbers
                           for _number, dependencies in self.subject.declared_dependency_graph
                           for dependency in dependencies)):
                raise IntegrationError("parent Integration PASS lacks the exact child/main/evidence subject")
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
        edges = dependencies[number]
        if (type(edges) is not tuple or any(type(dep) is not int for dep in edges)
                or len(edges) != len(set(edges))):
            raise IntegrationError("child dependency graph contains malformed or duplicate edges")
        for dep in edges:
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
    merge_sha_ancestry: Mapping[str, bool],
    integration_verification: IntegrationGateEvidence | None = None,
    integration_acceptance: IntegrationGateEvidence | None = None,
) -> ParentIntegrationResult:
    """Pure validation. Snapshots *must* be read from GitHub and verified adapters.

    PASS additionally requires exact typed Integration Verification and
    Acceptance artifacts; caller-supplied pass booleans cannot substitute.
    """
    expected = tuple(sorted(expected_child_issue_numbers))
    if not expected or any(type(n) is not int or n < 1 for n in expected) or len(set(expected)) != len(expected):
        raise IntegrationError("frozen child set is invalid")
    reasons: list[str] = []
    try:
        _validate_dependency_graph(expected, declared_dependencies)
    except IntegrationError as exc:
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
        base = pr.get("base")
        head = pr.get("head")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        head_repo = head.get("repo") if isinstance(head, dict) else None
        if (pr.get("state") != "closed" or not isinstance(pr.get("merged_at"), str)
                or not isinstance(base, dict) or not isinstance(head, dict)
                or not isinstance(base_repo, dict) or not isinstance(head_repo, dict)
                or not isinstance(base_repo.get("full_name"), str)
                or base_repo["full_name"].casefold() != repository.casefold()
                or base.get("ref") != "main"
                or not isinstance(head_repo.get("full_name"), str)
                or head_repo["full_name"].casefold() != repository.casefold()):
            reasons.append(f"child PR for #{number} is unmerged, forked, or not in the repository")
            continue
        pr_number = pr.get("number")
        headsha = head.get("sha")
        mergesha = pr.get("merge_commit_sha")
        try:
            in_main = merge_sha_ancestry.get(mergesha) is True
            child = ChildMerge(number, ids[number], pr_number, headsha, mergesha, pr["merged_at"],
                               declared_dependencies.get(number, ()), in_main).validate()
            if not in_main:
                reasons.append(f"child PR merge commit for #{number} is not confirmed in final main")
            accepted.append(child)
        except (IntegrationError, KeyError, TypeError):
            reasons.append(f"child PR for #{number} has an invalid identity or merge SHA")
    accepted_by_issue = {child.issue_number: child for child in accepted}
    for child in accepted:
        for dependency in child.dependencies:
            parent_merge = accepted_by_issue.get(dependency)
            if parent_merge is not None and _time(parent_merge.merged_at) > _time(child.merged_at):
                reasons.append(f"child PR for #{child.issue_number} merged before dependency #{dependency}")
    evidence = ((integration_verification, "verification"), (integration_acceptance, "acceptance"))
    evidence_digests: dict[str, str | None] = {"verification": None, "acceptance": None}
    for row, kind in evidence:
        if not isinstance(row, IntegrationGateEvidence):
            reasons.append(f"parent Integration {kind.title()} typed PASS evidence is missing")
            continue
        try:
            row.validate()
        except IntegrationError as exc:
            reasons.append(f"parent Integration {kind.title()} evidence is invalid: {exc}")
            continue
        if (row.kind != kind or row.repository.casefold() != repository.casefold()
                or row.parent_issue_number != parent_issue_number
                or row.parent_adc_sha256 != parent_adc_sha256 or row.main_sha40 != main_sha40):
            reasons.append(f"parent Integration {kind.title()} evidence is stale or has a different exact subject")
        else:
            evidence_digests[kind] = row.sha256
    dependency_graph: list[tuple[int, tuple[int, ...]]] = []
    for number in expected:
        try:
            dependencies = tuple(sorted(declared_dependencies.get(number, ())))
        except (TypeError, ValueError):
            dependencies = ()
        dependency_graph.append((number, dependencies))
    subject = ParentIntegrationSubject(
        repository, parent_issue_number, parent_adc_sha256, main_sha40,
        tuple(sorted(accepted, key=lambda x: x.issue_number)), evidence_digests["verification"],
        evidence_digests["acceptance"], expected,
        tuple(dependency_graph),
    ).validate()
    return ParentIntegrationResult("BLOCKED" if reasons else "PASS", subject, tuple(dict.fromkeys(reasons))).validate()
