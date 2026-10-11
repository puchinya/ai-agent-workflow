"""Versioned gate routing and independent migration Bootstrap evidence.

Bootstrap is deliberately separate from ordinary P-ASES Review Readiness.  This
module contains the policy and evidence schemas only; it never changes Issue
phases or the normal delivery gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from .adc import ADC, ADCPointer, ADCError, parse_adc, verify_adc
from .git import GitError, run_git
from .github import GitHub, GitHubError
from .process import ProcessError, run_process


class GatePolicyError(ValueError):
    pass


@dataclass(frozen=True)
class BootstrapADC:
    contract: ADC
    pointer: ADCPointer

    def validate(self) -> "BootstrapADC":
        if (self.pointer.comment_id < 1 or not SHA256.fullmatch(self.pointer.sha256)
                or self.pointer.byte_length < 1 or self.pointer.state not in {"approved", "draft", "unverified"}
                or self.contract.sha256 != self.pointer.sha256
                or self.contract.byte_length != self.pointer.byte_length):
            raise GatePolicyError("Bootstrap ADC readback does not match its exact pointer")
        return self


LEGACY_ADC_COMMENT = re.compile(r"(?m)^- child_adc_comment_id: `?([1-9][0-9]{0,19})`?[ \t]*$")
LEGACY_ADC_SHA = re.compile(r"(?m)^- child_adc_sha256: `?([0-9a-f]{64})`?[ \t]*$")
LEGACY_ADC_URL = re.compile(r"(?m)^- child_adc_comment_url: (https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*#issuecomment-[1-9][0-9]*)[ \t]*$")
LEGACY_CHILD_KEY = re.compile(r"(?m)^- child_key: `?([A-Za-z0-9][A-Za-z0-9._-]{0,63})`?[ \t]*$")
ADC_CHILD_KEY = re.compile(r"^Child key:[ \t]*`?([A-Za-z0-9][A-Za-z0-9._-]{0,63})`?[ \t]*$")


def _adc_declared_child_key(content: bytes) -> str | None:
    text = content.decode("utf-8", errors="strict")
    fence: tuple[str, int] | None = None
    matches: list[str] = []
    for line in text.splitlines():
        if fence is not None:
            marker, length = fence
            if re.match(rf"^ {{0,3}}{re.escape(marker)}{{{length},}}[ \t]*$", line):
                fence = None
            continue
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_match and (fence_match.group(1)[0] == "~" or "`" not in fence_match.group(2)):
            fence = (fence_match.group(1)[0], len(fence_match.group(1)))
            continue
        if re.match(r"^ {0,3}##[ \t]+", line):
            break
        match = ADC_CHILD_KEY.fullmatch(line)
        if match:
            matches.append(match.group(1))
    return matches[0] if len(matches) == 1 else None


REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BOOTSTRAP_PARENT = 26
BOOTSTRAP_ISSUES = frozenset(range(27, 33))
BOOTSTRAP_COHORT = frozenset({BOOTSTRAP_PARENT, *BOOTSTRAP_ISSUES})
BOOTSTRAP_REPOSITORY = "puchinya/ai-agent-workflow"
BOOTSTRAP_POLICY = "bootstrap-legacy-v1"
PASES_POLICY = "p-ases-v1"
RESULTS = {"BOOTSTRAP_REVIEW_READY", "BOOTSTRAP_BLOCKED", "PASES_GATE_REQUIRED", "UNDETERMINED"}
REQUIRED_LOCAL_CHECKS = ("compileall", "unittest", "dist-build-check", "dist-validation", "diff-check")
BOOTSTRAP_REQUIRED_JOBS = ("pull-request-metadata",)
BOOTSTRAP_POLICY_FILES = ("gate_policy.py", "cli.py", "github.py", "adc.py", "git.py", "process.py", "profile.py")
INDEPENDENCE_ASSURANCE = "reviewer-attested; the host/session identity is not cryptographically verified"
EXPECTED_BRANCH_PAIRS = {
    27: ("main", "pases/adc-core"),
    29: ("pases/adc-core", "pases/verification"),
    30: ("pases/verification", "pases/work-readiness"),
}
_CLOSES_LINE = re.compile(r"(?im)^\s*closes\s+#([1-9][0-9]*)\s*$")
_CLOSES_ANY = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#([1-9][0-9]*)\b")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def bootstrap_policy_digest() -> str:
    """Fingerprint the Bootstrap evaluator and the runtime adapters it trusts."""
    root = Path(__file__).resolve().parent
    rows = []
    for name in BOOTSTRAP_POLICY_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise GatePolicyError(f"Bootstrap policy source is missing or unsafe: {name}")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise GatePolicyError(f"could not read Bootstrap policy source {name}") from exc
        rows.append({"path": name, "sha256": hashlib.sha256(content).hexdigest()})
    return hashlib.sha256(_canonical({"files": rows, "schema": "PASES_BOOTSTRAP_POLICY_FINGERPRINT_V1"})).hexdigest()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise GatePolicyError(f"{label} must be non-empty text")
    return value.strip()


def _sha(value: Any, label: str, pattern: re.Pattern[str] = SHA256) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise GatePolicyError(f"{label} must be a full SHA-256" if pattern is SHA256 else f"{label} must be a full SHA-40")
    return value


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise GatePolicyError(f"{label} must be a positive integer")
    return value


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise GatePolicyError(f"{label} timestamp is missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GatePolicyError(f"{label} timestamp is invalid") from exc
    if result.tzinfo is None:
        raise GatePolicyError(f"{label} timestamp must include a timezone")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class BootstrapSubject:
    repository: str
    issue_number: int
    pr_number: int
    adc_comment_id: int
    adc_sha256: str
    base_ref: str
    base_sha40: str
    head_ref: str
    head_sha40: str

    def validate(self) -> "BootstrapSubject":
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository):
            raise GatePolicyError("Bootstrap repository must be owner/name")
        _positive(self.issue_number, "Bootstrap Issue number")
        _positive(self.pr_number, "Bootstrap PR number")
        _positive(self.adc_comment_id, "Bootstrap ADC Comment ID")
        _sha(self.adc_sha256, "Bootstrap ADC digest")
        _text(self.base_ref, "Bootstrap PR base ref")
        _sha(self.base_sha40, "Bootstrap PR base SHA", SHA40)
        _text(self.head_ref, "Bootstrap PR head ref")
        _sha(self.head_sha40, "Bootstrap PR HEAD", SHA40)
        if self.issue_number not in BOOTSTRAP_ISSUES:
            raise GatePolicyError("Issue is outside the fixed Bootstrap cohort")
        if self.repository.casefold() != BOOTSTRAP_REPOSITORY.casefold():
            raise GatePolicyError("Bootstrap subject repository is outside the fixed cohort repository")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"adc_comment_id": self.adc_comment_id, "adc_sha256": self.adc_sha256,
                "base_ref": self.base_ref, "base_sha40": self.base_sha40,
                "head_ref": self.head_ref, "head_sha40": self.head_sha40,
                "issue_number": self.issue_number, "pr_number": self.pr_number,
                "repository": self.repository}

    @classmethod
    def from_dict(cls, value: Any) -> "BootstrapSubject":
        expected = {"adc_comment_id", "adc_sha256", "base_ref", "base_sha40", "head_ref", "head_sha40",
                    "issue_number", "pr_number", "repository"}
        if not isinstance(value, dict) or set(value) != expected:
            raise GatePolicyError("Bootstrap subject has unknown or missing fields")
        return cls(**value).validate()


def read_bootstrap_adc(github: GitHub, issue_number: int) -> BootstrapADC:
    """Read an approved P-ASES ADC, or exact legacy bytes without inventing approval."""
    try:
        verified = verify_adc(github, issue_number)
    except ADCError as exc:
        if str(exc) != "Issue has no Agent Development Contract pointer":
            raise GatePolicyError(f"current ADC readback failed: {exc}") from exc
        return _read_legacy_bootstrap_adc(github, issue_number)
    return BootstrapADC(verified.contract, verified.pointer).validate()


def _read_legacy_bootstrap_adc(github: GitHub, issue_number: int) -> BootstrapADC:
    try:
        issue = github.issue(issue_number)
        if (issue.get("number") != issue_number or issue.get("state") != "open"
                or issue.get("pull_request") is not None or not isinstance(issue.get("body"), str)):
            raise GatePolicyError("legacy ADC source Issue identity/state is invalid")
        body = issue["body"]
        comment_ids = LEGACY_ADC_COMMENT.findall(body)
        digests = LEGACY_ADC_SHA.findall(body)
        urls = LEGACY_ADC_URL.findall(body)
        child_keys = LEGACY_CHILD_KEY.findall(body)
        if (len(comment_ids) != 1 or len(digests) != 1 or len(urls) != 1
                or len(child_keys) != 1):
            raise GatePolicyError("legacy child ADC pointer is missing, duplicated, or incomplete")
        comment_id, digest, comment_url = int(comment_ids[0]), digests[0], urls[0]
        expected_url = f"https://github.com/{github.repo}/issues/{issue_number}#issuecomment-{comment_id}"
        if comment_url.casefold() != expected_url.casefold():
            raise GatePolicyError("legacy child ADC URL does not match the selected Issue and Comment ID")
        named = _issue_comment_readback(github, issue_number, comment_id)
        if not isinstance(named.get("body"), str):
            raise GatePolicyError("legacy child ADC comment has no exact text body")
        content = named["body"].encode("utf-8", errors="strict")
        if hashlib.sha256(content).hexdigest() != digest:
            raise GatePolicyError("legacy child ADC SHA-256 does not match its named comment")
        contract = parse_adc(content, github.repo, issue_number)
        if _adc_declared_child_key(content) != child_keys[0]:
            raise GatePolicyError("legacy child ADC key differs from the Issue's child_key")
        final_issue = github.issue(issue_number)
        if final_issue.get("body") != body:
            raise GatePolicyError("legacy child ADC pointer changed during readback")
        # The legacy issue marker has no approval-state field. Keep that fact explicit.
        pointer = ADCPointer(comment_id, digest, len(content), "unverified")
        return BootstrapADC(contract, pointer).validate()
    except GitHubError as exc:
        raise GatePolicyError(f"legacy ADC GitHub readback failed: {exc}") from exc
    except ADCError as exc:
        raise GatePolicyError(f"legacy ADC validation failed: {exc}") from exc


@dataclass(frozen=True)
class GateSelection:
    repository: str
    issue_number: int
    policy_version: str
    selected_at: str
    activation_comment_id: int | None = None
    activation_sha256: str | None = None

    def validate(self) -> "GateSelection":
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository):
            raise GatePolicyError("Gate selection repository must be owner/name")
        _positive(self.issue_number, "Gate selection Issue number")
        _parse_time(self.selected_at, "Gate selection")
        if self.issue_number in BOOTSTRAP_COHORT:
            if self.repository.casefold() != BOOTSTRAP_REPOSITORY.casefold():
                raise GatePolicyError("fixed Bootstrap cohort is limited to its approved repository")
            if self.policy_version != BOOTSTRAP_POLICY or self.activation_comment_id is not None or self.activation_sha256 is not None:
                raise GatePolicyError("fixed Bootstrap cohort must remain pinned to bootstrap-legacy-v1")
        elif self.policy_version == PASES_POLICY:
            _positive(self.activation_comment_id, "Activation Comment ID")
            _sha(self.activation_sha256, "Activation digest")
        else:
            raise GatePolicyError("non-cohort Issues require a verified activation or remain UNDETERMINED")
        if self.policy_version not in {BOOTSTRAP_POLICY, PASES_POLICY}:
            raise GatePolicyError("Gate selection policy version is unknown")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"activation_comment_id": self.activation_comment_id, "activation_sha256": self.activation_sha256,
                "issue_number": self.issue_number, "policy_version": self.policy_version,
                "repository": self.repository, "schema": "PASES_GATE_SELECTION_V1", "selected_at": self.selected_at}

    @classmethod
    def from_payload(cls, value: Any) -> "GateSelection":
        expected = {"activation_comment_id", "activation_sha256", "issue_number", "policy_version",
                    "repository", "schema", "selected_at"}
        if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_GATE_SELECTION_V1":
            raise GatePolicyError("Gate selection record has unknown schema or fields")
        return cls(value["repository"], value["issue_number"], value["policy_version"],
                   value["selected_at"], value["activation_comment_id"], value["activation_sha256"]).validate()


def select_gate(repository: str, issue_number: int, *, selected_at: str,
                activation: "ActivationRecord | None" = None, activation_comment_id: int | None = None,
                activation_sha256: str | None = None,
                issue_created_at: str | None = None) -> GateSelection | None:
    """Return the pinned policy or None when the Issue's policy is undetermined."""
    if issue_number in BOOTSTRAP_COHORT:
        if not isinstance(repository, str) or repository.casefold() != BOOTSTRAP_REPOSITORY.casefold():
            raise GatePolicyError("fixed Bootstrap cohort is limited to its approved repository")
        return GateSelection(repository, issue_number, BOOTSTRAP_POLICY, selected_at).validate()
    if activation is None or activation_comment_id is None or activation_sha256 is None:
        return None
    activation.validate()
    if activation.repository.casefold() != repository.casefold():
        return None
    if issue_created_at is None:
        return None
    activation_time = _parse_time(activation.activated_at, "Activation")
    if (_parse_time(selected_at, "Gate selection") <= activation_time
            or _parse_time(issue_created_at, "Issue creation") <= activation_time):
        return None
    return GateSelection(repository, issue_number, PASES_POLICY, selected_at,
                         activation_comment_id, activation_sha256).validate()


@dataclass(frozen=True)
class ActivationRecord:
    repository: str
    child_issue_numbers: tuple[int, ...]
    child_prs: tuple[tuple[int, int, str], ...]
    closed_issue_numbers: tuple[int, ...]
    integration_evidence_sha256: str
    integration_evidence_comment_id: int
    gate_version: str
    activation_commit_sha40: str
    approval_comment_id: int
    activated_at: str

    def validate(self) -> "ActivationRecord":
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository):
            raise GatePolicyError("Activation repository must be owner/name")
        if self.child_issue_numbers != tuple(sorted(BOOTSTRAP_ISSUES)):
            raise GatePolicyError("Activation must cover exactly child Issues #27–#32")
        if self.closed_issue_numbers != tuple(sorted(BOOTSTRAP_ISSUES)):
            raise GatePolicyError("Activation requires all six child Issues to be closed")
        if (type(self.child_prs) is not tuple
                or any(not isinstance(row, tuple) or len(row) != 3 for row in self.child_prs)):
            raise GatePolicyError("Activation child PR mapping is malformed")
        if tuple(number for number, _pr, _sha_value in self.child_prs) != tuple(sorted(BOOTSTRAP_ISSUES)):
            raise GatePolicyError("Activation must bind one merge SHA for every fixed child Issue")
        for _issue, pr, _sha_value in self.child_prs:
            _positive(pr, "Activation child PR number")
        if len({pr for _issue, pr, _sha_value in self.child_prs}) != len(self.child_prs):
            raise GatePolicyError("Activation child PR numbers must be unique")
        for _issue, pr_number, sha_value in self.child_prs:
            _sha(sha_value, "Child merge SHA", SHA40)
        _sha(self.integration_evidence_sha256, "Integration evidence digest")
        _positive(self.integration_evidence_comment_id, "Integration evidence Comment ID")
        if self.gate_version != PASES_POLICY:
            raise GatePolicyError("Activation gate version must be p-ases-v1")
        _sha(self.activation_commit_sha40, "Activation commit", SHA40)
        _positive(self.approval_comment_id, "Activation approval Comment ID")
        _parse_time(self.activated_at, "Activation")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"activated_at": self.activated_at, "activation_commit_sha40": self.activation_commit_sha40,
                "approval_comment_id": self.approval_comment_id, "child_issue_numbers": list(self.child_issue_numbers),
                "child_prs": [{"issue_number": number, "pr_number": pr_number, "merge_sha40": sha_value}
                              for number, pr_number, sha_value in self.child_prs],
                "closed_issue_numbers": list(self.closed_issue_numbers),
                "gate_version": self.gate_version, "integration_evidence_comment_id": self.integration_evidence_comment_id,
                "integration_evidence_sha256": self.integration_evidence_sha256,
                "repository": self.repository, "schema": "PASES_ACTIVATION_V1"}

    @classmethod
    def from_payload(cls, value: Any) -> "ActivationRecord":
        expected = {"activated_at", "activation_commit_sha40", "approval_comment_id", "child_issue_numbers",
                    "child_prs", "closed_issue_numbers", "gate_version", "integration_evidence_comment_id",
                    "integration_evidence_sha256",
                    "repository", "schema"}
        if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_ACTIVATION_V1":
            raise GatePolicyError("Activation record has unknown schema or fields")
        if (not isinstance(value["child_issue_numbers"], list)
                or not isinstance(value["closed_issue_numbers"], list)):
            raise GatePolicyError("Activation child Issue sets are malformed")
        merges = value["child_prs"]
        if not isinstance(merges, list) or any(not isinstance(row, dict) or set(row) != {"issue_number", "pr_number", "merge_sha40"} for row in merges):
            raise GatePolicyError("Activation child merge mapping is malformed")
        record = cls(value["repository"], tuple(value["child_issue_numbers"]),
                     tuple((row["issue_number"], row["pr_number"], row["merge_sha40"]) for row in merges),
                     tuple(value["closed_issue_numbers"]), value["integration_evidence_sha256"],
                     value["integration_evidence_comment_id"],
                     value["gate_version"], value["activation_commit_sha40"], value["approval_comment_id"],
                     value["activated_at"])
        return record.validate()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    status: str
    evidence_refs: tuple[str, ...]

    def validate(self) -> "ReviewItem":
        _text(self.item_id, "Review item ID")
        if self.status not in {"PASS", "FAIL", "CONCERNS", "BLOCKED", "SKIPPED", "FLAKY"}:
            raise GatePolicyError("Review item status is unknown")
        if type(self.evidence_refs) is not tuple or not self.evidence_refs:
            raise GatePolicyError("Review item requires evidence references")
        for ref in self.evidence_refs:
            _text(ref, "Review evidence reference")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"evidence_refs": list(self.evidence_refs), "item_id": self.item_id, "status": self.status}


@dataclass(frozen=True)
class VerifiedReviewEvidence:
    item_id: str
    reference: str
    evidence_kind: str
    sha256: str
    head_sha40: str

    def validate(self, subject: BootstrapSubject) -> "VerifiedReviewEvidence":
        subject.validate()
        _text(self.item_id, "Review evidence item ID")
        _text(self.reference, "Review evidence reference")
        if self.evidence_kind not in {"git-blob", "workflow-run", "pull-request", "issue-comment"}:
            raise GatePolicyError("Review evidence artifact kind is unsupported")
        _sha(self.sha256, "Review evidence artifact digest")
        _sha(self.head_sha40, "Review evidence subject HEAD", SHA40)
        if self.head_sha40 != subject.head_sha40:
            raise GatePolicyError("Review evidence artifact is not bound to the current PR HEAD")
        return self

    def as_dict(self) -> dict[str, str]:
        return {"evidence_kind": self.evidence_kind, "head_sha40": self.head_sha40,
                "item_id": self.item_id, "reference": self.reference, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: Any, subject: BootstrapSubject) -> "VerifiedReviewEvidence":
        expected = {"evidence_kind", "head_sha40", "item_id", "reference", "sha256"}
        if not isinstance(value, dict) or set(value) != expected:
            raise GatePolicyError("Verified review evidence record is malformed")
        return cls(value["item_id"], value["reference"], value["evidence_kind"],
                   value["sha256"], value["head_sha40"]).validate(subject)


@dataclass(frozen=True)
class BootstrapSelfReview:
    subject: BootstrapSubject
    context_id: str
    items: tuple[ReviewItem, ...]
    comment_id: int
    verified_evidence: tuple[VerifiedReviewEvidence, ...] = ()

    def validate(self, required_ids: Iterable[str]) -> "BootstrapSelfReview":
        self.subject.validate()
        _text(self.context_id, "Self-review context ID")
        _positive(self.comment_id, "Self-review Comment ID")
        required = tuple(required_ids)
        if not required or len(set(required)) != len(required):
            raise GatePolicyError("Self-review requirement/checklist set is missing or duplicated")
        if type(self.items) is not tuple:
            raise GatePolicyError("Self-review items must be a tuple")
        for item in self.items:
            item.validate()
        ids = tuple(item.item_id for item in self.items)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)) or set(ids) != set(required):
            raise GatePolicyError("Self-review must cover every ADC requirement and checklist item exactly")
        if any(item.status != "PASS" for item in self.items):
            raise GatePolicyError("Self-review has a non-PASS requirement or checklist item")
        if type(self.verified_evidence) is not tuple:
            raise GatePolicyError("Self-review verified evidence must be a tuple")
        verified: set[tuple[str, str]] = set()
        for artifact in self.verified_evidence:
            artifact.validate(self.subject)
            pair = (artifact.item_id, artifact.reference)
            if pair in verified:
                raise GatePolicyError("Self-review has duplicate verified evidence references")
            verified.add(pair)
        required_evidence = {(item.item_id, ref) for item in self.items for ref in item.evidence_refs}
        if not required_evidence or not required_evidence.issubset(verified):
            raise GatePolicyError("Self-review references include artifacts that were not read back")
        return self

    def payload(self) -> dict[str, Any]:
        return {"context_id": self.context_id, "items": [item.as_dict() for item in self.items],
                "schema": "PASES_BOOTSTRAP_SELF_REVIEW_V1", "subject": self.subject.as_dict()}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def comment_body(self) -> str:
        value = {**self.payload(), "review_sha256": self.sha256}
        return f"<!-- PASES_BOOTSTRAP_SELF_REVIEW_V1\n{_canonical(value).decode('utf-8')}\n-->"


@dataclass(frozen=True)
class ReviewFinding:
    finding_id: str
    severity: str
    resolved: bool
    description: str
    evidence_ref: str

    def validate(self) -> "ReviewFinding":
        _text(self.finding_id, "Review finding ID")
        if self.severity not in {"A", "B", "C", "D"} or type(self.resolved) is not bool:
            raise GatePolicyError("Review finding severity or resolution is invalid")
        _text(self.description, "Review finding description")
        _text(self.evidence_ref, "Review finding evidence reference")
        return self


@dataclass(frozen=True)
class BootstrapIndependentReview:
    subject: BootstrapSubject
    reviewer_context_id: str
    implementation_context_id: str
    context_artifact_ref: str
    context_artifact_sha256: str
    separate_context_confirmed: bool
    findings: tuple[ReviewFinding, ...]
    verdict: str
    comment_id: int
    context_artifact_verified: bool = False
    context_artifact_comment_id: int | None = None
    verified_evidence: tuple[VerifiedReviewEvidence, ...] = ()

    def validate(self) -> "BootstrapIndependentReview":
        self.subject.validate()
        if _text(self.reviewer_context_id, "Reviewer context ID") == _text(self.implementation_context_id, "Implementation context ID"):
            raise GatePolicyError("Independent review must come from a separate context")
        _text(self.context_artifact_ref, "Independent review context artifact")
        _sha(self.context_artifact_sha256, "Independent review context artifact digest")
        if type(self.separate_context_confirmed) is not bool or not self.separate_context_confirmed:
            raise GatePolicyError("Independent review requires explicit separate-context execution confirmation")
        if self.context_artifact_verified is not True:
            raise GatePolicyError("Independent review context artifact has not been read back and verified")
        _positive(self.context_artifact_comment_id, "Independent context artifact Comment ID")
        _positive(self.comment_id, "Independent review Comment ID")
        if self.verdict not in {"PASS", "CONCERNS", "FAIL"}:
            raise GatePolicyError("Independent review verdict is invalid")
        if type(self.findings) is not tuple:
            raise GatePolicyError("Independent review findings must be a tuple")
        for finding in self.findings:
            finding.validate()
        if len({finding.finding_id for finding in self.findings}) != len(self.findings):
            raise GatePolicyError("Independent review has duplicate finding IDs")
        if type(self.verified_evidence) is not tuple:
            raise GatePolicyError("Independent-review verified evidence must be a tuple")
        for artifact in self.verified_evidence:
            artifact.validate(self.subject)
        required_evidence = {finding.evidence_ref for finding in self.findings}
        verified_refs = {artifact.reference for artifact in self.verified_evidence}
        if required_evidence and not required_evidence.issubset(verified_refs):
            raise GatePolicyError("Independent-review findings contain evidence refs that were not read back")
        unresolved_ab = [finding for finding in self.findings if finding.severity in {"A", "B"} and not finding.resolved]
        if unresolved_ab or self.verdict != "PASS":
            raise GatePolicyError("Independent review is not PASS or has unresolved A/B findings")
        return self

    def payload(self) -> dict[str, Any]:
        return {"context_artifact_ref": self.context_artifact_ref,
                "context_artifact_sha256": self.context_artifact_sha256,
                "findings": [{"description": item.description, "evidence_ref": item.evidence_ref,
                              "finding_id": item.finding_id, "resolved": item.resolved,
                              "severity": item.severity} for item in self.findings],
                "implementation_context_id": self.implementation_context_id,
                "reviewer_context_id": self.reviewer_context_id, "schema": "PASES_BOOTSTRAP_INDEPENDENT_REVIEW_V1",
                "separate_context_confirmed": self.separate_context_confirmed,
                "subject": self.subject.as_dict(), "verdict": self.verdict}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def comment_body(self) -> str:
        value = {**self.payload(), "review_sha256": self.sha256}
        return f"<!-- PASES_BOOTSTRAP_INDEPENDENT_REVIEW_V1\n{_canonical(value).decode('utf-8')}\n-->"


@dataclass(frozen=True)
class BootstrapReviewContextArtifact:
    subject: BootstrapSubject
    reviewer_context_id: str
    separate_context_confirmed: bool
    report: str
    comment_id: int

    def validate(self, *, expected_subject: BootstrapSubject,
                 expected_reviewer_context_id: str) -> "BootstrapReviewContextArtifact":
        self.subject.validate()
        if self.subject != expected_subject:
            raise GatePolicyError("Independent context artifact belongs to a different Bootstrap subject")
        if _text(self.reviewer_context_id, "Reviewer context ID") != expected_reviewer_context_id:
            raise GatePolicyError("Independent context artifact reviewer ID differs from its review record")
        if self.separate_context_confirmed is not True:
            raise GatePolicyError("Independent context artifact does not confirm a separate review execution")
        _text(self.report, "Independent context artifact report")
        _positive(self.comment_id, "Independent context artifact Comment ID")
        return self

    def payload(self) -> dict[str, Any]:
        return {"report": self.report, "reviewer_context_id": self.reviewer_context_id,
                "schema": "PASES_BOOTSTRAP_INDEPENDENT_CONTEXT_V1",
                "separate_context_confirmed": self.separate_context_confirmed,
                "subject": self.subject.as_dict()}

    def comment_body(self) -> str:
        return f"<!-- PASES_BOOTSTRAP_INDEPENDENT_CONTEXT_V1\n{_canonical(self.payload()).decode('utf-8')}\n-->"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.comment_body().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LocalCheck:
    name: str
    argv: tuple[str, ...]
    status: str
    exit_status: int | None
    output_sha256: str
    output_truncated: bool

    def validate(self) -> "LocalCheck":
        if self.name not in REQUIRED_LOCAL_CHECKS:
            raise GatePolicyError("Local Bootstrap check name is unknown")
        if type(self.argv) is not tuple or not self.argv or any(not isinstance(arg, str) or not arg for arg in self.argv):
            raise GatePolicyError("Local Bootstrap check must preserve argv")
        if self.status not in {"completed", "timed_out", "cancelled", "start_failed"}:
            raise GatePolicyError("Local Bootstrap process status is unknown")
        if self.status == "completed":
            if type(self.exit_status) is not int:
                raise GatePolicyError("Completed local check must have an exit status")
        elif self.exit_status is not None:
            raise GatePolicyError("Incomplete local check cannot claim an exit status")
        _sha(self.output_sha256, "Local check output digest")
        if type(self.output_truncated) is not bool:
            raise GatePolicyError("Local check truncation flag must be boolean")
        return self


@dataclass(frozen=True)
class BootstrapResult:
    status: str
    subject: BootstrapSubject
    reasons: tuple[str, ...]
    local_checks: tuple[LocalCheck, ...]
    required_jobs: tuple[tuple[str, int, str, str], ...]
    workflow_run_id: int | None
    workflow_status: str | None
    workflow_conclusion: str | None
    self_review_comment_id: int | None
    independent_review_comment_id: int | None
    unverified_hosts: tuple[str, ...]
    bootstrap_policy_sha256: str | None = None
    verified_review_evidence: tuple[VerifiedReviewEvidence, ...] = ()
    independent_context_artifact_comment_id: int | None = None
    independent_context_artifact_sha256: str | None = None
    separate_context_confirmed: bool = False

    def validate(self) -> "BootstrapResult":
        if self.status not in {"BOOTSTRAP_REVIEW_READY", "BOOTSTRAP_BLOCKED"}:
            raise GatePolicyError("Bootstrap result status is invalid")
        self.subject.validate()
        if type(self.reasons) is not tuple or any(not isinstance(reason, str) or not reason for reason in self.reasons):
            raise GatePolicyError("Bootstrap result reasons are invalid")
        for item in self.local_checks:
            item.validate()
        if type(self.required_jobs) is not tuple:
            raise GatePolicyError("Bootstrap required job results are invalid")
        for name, run_id, status, conclusion in self.required_jobs:
            _text(name, "Required CI job")
            _positive(run_id, "Required CI check-run ID")
            _text(status, "Required CI status")
            _text(conclusion, "Required CI conclusion")
        if self.workflow_run_id is not None:
            _positive(self.workflow_run_id, "CI workflow run ID")
        if self.workflow_status is not None and not isinstance(self.workflow_status, str):
            raise GatePolicyError("CI workflow status is invalid")
        if self.workflow_conclusion is not None and not isinstance(self.workflow_conclusion, str):
            raise GatePolicyError("CI workflow conclusion is invalid")
        if self.self_review_comment_id is not None:
            _positive(self.self_review_comment_id, "Self-review Comment ID")
        if self.independent_review_comment_id is not None:
            _positive(self.independent_review_comment_id, "Independent-review Comment ID")
        if self.bootstrap_policy_sha256 is not None:
            _sha(self.bootstrap_policy_sha256, "Bootstrap policy digest")
        if type(self.verified_review_evidence) is not tuple:
            raise GatePolicyError("Bootstrap verified review evidence is invalid")
        for artifact in self.verified_review_evidence:
            artifact.validate(self.subject)
        if self.independent_context_artifact_comment_id is not None:
            _positive(self.independent_context_artifact_comment_id, "Independent context artifact Comment ID")
        if self.independent_context_artifact_sha256 is not None:
            _sha(self.independent_context_artifact_sha256, "Independent context artifact digest")
        if type(self.separate_context_confirmed) is not bool:
            raise GatePolicyError("Independent context confirmation flag is invalid")
        if ((self.independent_context_artifact_comment_id is None)
                != (self.independent_context_artifact_sha256 is None)):
            raise GatePolicyError("Independent context artifact ID and digest must be paired")
        if (type(self.unverified_hosts) is not tuple or not self.unverified_hosts
                or any(not isinstance(host, str) or not host.strip() for host in self.unverified_hosts)):
            raise GatePolicyError("Unverified host disclosure is invalid")
        if self.status == "BOOTSTRAP_REVIEW_READY" and (
                tuple(check.name for check in self.local_checks) != REQUIRED_LOCAL_CHECKS
                or any(check.status != "completed" or check.exit_status != 0 or check.output_truncated
                       for check in self.local_checks)
                or not self.required_jobs
                or any(status != "completed" or conclusion != "success"
                       for _name, _run_id, status, conclusion in self.required_jobs)
                or self.workflow_run_id is None
                or self.workflow_status != "completed" or self.workflow_conclusion != "success"
                or self.self_review_comment_id is None or self.independent_review_comment_id is None
                or self.bootstrap_policy_sha256 is None or not self.verified_review_evidence
                or self.independent_context_artifact_comment_id is None
                or self.independent_context_artifact_sha256 is None or not self.separate_context_confirmed):
            raise GatePolicyError("Bootstrap REVIEW_READY record is missing successful evidence")
        if (self.status == "BOOTSTRAP_REVIEW_READY") != (not self.reasons):
            raise GatePolicyError("Bootstrap status and reasons disagree")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"independent_review_comment_id": self.independent_review_comment_id,
                "local_checks": [{"argv": list(check.argv), "exit_status": check.exit_status,
                                  "name": check.name, "output_sha256": check.output_sha256,
                                  "output_truncated": check.output_truncated, "status": check.status}
                                 for check in self.local_checks],
                "reasons": list(self.reasons), "required_jobs": [
                    {"check_run_id": run_id, "conclusion": conclusion, "name": name, "status": status}
                    for name, run_id, status, conclusion in self.required_jobs],
                "schema": "PASES_BOOTSTRAP_REVIEW_V1", "self_review_comment_id": self.self_review_comment_id,
                "can_request_final_user_review": self.status == "BOOTSTRAP_REVIEW_READY",
                "status": self.status, "subject": self.subject.as_dict(), "unverified_hosts": list(self.unverified_hosts),
                "ordinary_pases_readiness": "NOT_EVALUATED",
                "bootstrap_policy_sha256": self.bootstrap_policy_sha256,
                "verified_review_evidence": [row.as_dict() for row in self.verified_review_evidence],
                "independent_context_artifact_comment_id": self.independent_context_artifact_comment_id,
                "independent_context_artifact_sha256": self.independent_context_artifact_sha256,
                "separate_context_confirmed": self.separate_context_confirmed,
                "independence_assurance": INDEPENDENCE_ASSURANCE,
                "workflow_conclusion": self.workflow_conclusion, "workflow_run_id": self.workflow_run_id,
                "workflow_status": self.workflow_status}

    @classmethod
    def from_payload(cls, value: Any) -> "BootstrapResult":
        expected = {"can_request_final_user_review", "independent_review_comment_id", "local_checks",
                    "ordinary_pases_readiness", "reasons", "required_jobs", "schema",
                    "self_review_comment_id", "status", "subject", "unverified_hosts", "workflow_conclusion",
                    "workflow_run_id", "workflow_status"}
        expected_with_policy = expected | {"bootstrap_policy_sha256"}
        evidence_fields = {"verified_review_evidence", "independent_context_artifact_comment_id",
                           "independent_context_artifact_sha256", "separate_context_confirmed",
                           "independence_assurance"}
        accepted_shapes = {frozenset(expected), frozenset(expected_with_policy),
                           frozenset(expected | evidence_fields),
                           frozenset(expected_with_policy | evidence_fields)}
        if (not isinstance(value, dict) or frozenset(value) not in accepted_shapes
                or value.get("schema") != "PASES_BOOTSTRAP_REVIEW_V1"
                or value.get("ordinary_pases_readiness") != "NOT_EVALUATED"):
            raise GatePolicyError("Bootstrap result has unknown schema or fields")
        has_evidence_fields = evidence_fields.issubset(value)
        if has_evidence_fields and value.get("independence_assurance") != INDEPENDENCE_ASSURANCE:
            raise GatePolicyError("Bootstrap independence assurance is missing or changed")
        if (value.get("can_request_final_user_review") is not (value.get("status") == "BOOTSTRAP_REVIEW_READY")
                or not isinstance(value.get("reasons"), list)
                or not isinstance(value.get("local_checks"), list)
                or not isinstance(value.get("required_jobs"), list)
                or not isinstance(value.get("unverified_hosts"), list)):
            raise GatePolicyError("Bootstrap result fields are inconsistent")
        checks: list[LocalCheck] = []
        for item in value["local_checks"]:
            fields = {"argv", "exit_status", "name", "output_sha256", "output_truncated", "status"}
            if not isinstance(item, dict) or set(item) != fields or not isinstance(item["argv"], list):
                raise GatePolicyError("Bootstrap local check record is malformed")
            checks.append(LocalCheck(item["name"], tuple(item["argv"]), item["status"], item["exit_status"],
                                     item["output_sha256"], item["output_truncated"]))
        jobs: list[tuple[str, int, str, str]] = []
        for item in value["required_jobs"]:
            if not isinstance(item, dict) or set(item) != {"check_run_id", "conclusion", "name", "status"}:
                raise GatePolicyError("Bootstrap required job record is malformed")
            jobs.append((item["name"], item["check_run_id"], item["status"], item["conclusion"]))
        verified: list[VerifiedReviewEvidence] = []
        if has_evidence_fields:
            if (not isinstance(value["verified_review_evidence"], list)
                    or type(value["separate_context_confirmed"]) is not bool):
                raise GatePolicyError("Bootstrap review artifact evidence fields are malformed")
            verified = [VerifiedReviewEvidence.from_dict(row, BootstrapSubject.from_dict(value["subject"]))
                        for row in value["verified_review_evidence"]]
        result = cls(value["status"], BootstrapSubject.from_dict(value["subject"]), tuple(value["reasons"]),
                     tuple(checks), tuple(jobs), value["workflow_run_id"], value["workflow_status"],
                     value["workflow_conclusion"], value["self_review_comment_id"],
                     value["independent_review_comment_id"], tuple(value["unverified_hosts"]),
                     value.get("bootstrap_policy_sha256"), tuple(verified),
                     value.get("independent_context_artifact_comment_id"),
                     value.get("independent_context_artifact_sha256"),
                     value.get("separate_context_confirmed", False))
        return result.validate()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def comment_body(self) -> str:
        encoded = _canonical(self.payload()).decode("utf-8")
        return f"<!-- PASES_BOOTSTRAP_REVIEW_V1\n{encoded}\n-->"


def _pr_reasons(subject: BootstrapSubject, pr: dict[str, Any], response_repository: str) -> list[str]:
    reasons: list[str] = []
    if not isinstance(response_repository, str) or response_repository.casefold() != subject.repository.casefold():
        reasons.append("PR was not read from the subject repository")
    if not isinstance(pr, dict) or pr.get("number") != subject.pr_number:
        return reasons + ["current PR readback number is missing or mismatched"]
    if pr.get("state") != "open" or pr.get("draft") is not False:
        reasons.append("PR is not open and non-draft")
    base, head = pr.get("base"), pr.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        return reasons + ["PR base/head readback is incomplete"]
    base_repo = base.get("repo")
    head_repo = head.get("repo")
    for label, repo in (("base", base_repo), ("head", head_repo)):
        full_name = repo.get("full_name") if isinstance(repo, dict) else None
        if not isinstance(full_name, str) or full_name.casefold() != subject.repository.casefold():
            reasons.append(f"PR {label} repository does not match the same-repository Bootstrap subject")
    base_ref, head_ref = base.get("ref"), head.get("ref")
    expected_pair = EXPECTED_BRANCH_PAIRS.get(subject.issue_number)
    if expected_pair is None:
        reasons.append("approved Bootstrap base/head branch pair is not defined for this child Issue")
    elif (base_ref, head_ref) != expected_pair:
        reasons.append("PR base/head branch pair does not match the approved child branch contract")
    base_sha, head_sha = base.get("sha"), head.get("sha")
    if not isinstance(base_ref, str) or not base_ref or not isinstance(base_sha, str) or not SHA40.fullmatch(base_sha):
        reasons.append("PR base ref/SHA readback is incomplete")
    if (base_ref, base_sha, head_ref) != (subject.base_ref, subject.base_sha40, subject.head_ref):
        reasons.append("PR base/head identity differs from the Bootstrap subject")
    if not isinstance(head_ref, str) or not head_ref or not isinstance(head_sha, str) or not SHA40.fullmatch(head_sha):
        reasons.append("PR head ref/SHA readback is incomplete")
    elif head_sha != subject.head_sha40:
        reasons.append("PR current HEAD differs from the Bootstrap subject")
    body = pr.get("body")
    if not isinstance(body, str):
        reasons.append("PR body is missing; the Issue closing association cannot be verified")
    else:
        closing = [int(value) for value in _CLOSES_ANY.findall(body)]
        own_lines = [int(value) for value in _CLOSES_LINE.findall(body)]
        if closing != [subject.issue_number] or own_lines != [subject.issue_number]:
            reasons.append(f"PR body must contain exactly one standalone Closes #{subject.issue_number} association")
    return reasons


def _latest_check_results(check_runs: list[dict[str, Any]], required_names: Iterable[str], head_sha40: str) -> tuple[list[tuple[str, int, str, str]], list[str]]:
    reasons: list[str] = []
    results: list[tuple[str, int, str, str]] = []
    names = tuple(required_names)
    if not names or len(names) != len(set(names)):
        return [], ["Bootstrap required CI job set is empty or duplicated"]
    for name in names:
        matches = [run for run in check_runs if isinstance(run, dict) and run.get("name") == name]
        if not matches:
            reasons.append(f"required CI job is missing: {name}")
            continue
        for run in matches:
            if run.get("head_sha") != head_sha40:
                reasons.append(f"required CI job is not bound to current HEAD: {name}")
            app = run.get("app")
            if not isinstance(app, dict) or type(app.get("id")) is not int or app["id"] < 1:
                reasons.append(f"required CI job has incomplete GitHub Check Run provenance: {name}")
        latest = max(matches, key=lambda row: row.get("id", 0) if type(row.get("id")) is int else 0)
        run_id, status, conclusion = latest.get("id"), latest.get("status"), latest.get("conclusion")
        if type(run_id) is not int or run_id < 1:
            reasons.append(f"required CI job has no valid Check Run ID: {name}")
            continue
        results.append((name, run_id, status if isinstance(status, str) else "missing",
                        conclusion if isinstance(conclusion, str) else "missing"))
        if status != "completed" or conclusion != "success":
            reasons.append(f"required CI job is not completed/success: {name}")
    return results, reasons


def evaluate_bootstrap(subject: BootstrapSubject, *, pr: dict[str, Any], response_repository: str,
                       workflow_runs: list[dict[str, Any]], check_runs: list[dict[str, Any]],
                       required_check_names: Iterable[str], local_checks: tuple[LocalCheck, ...],
                       adc_requirement_ids: Iterable[str], adc_checklist_ids: Iterable[str],
                       self_review: BootstrapSelfReview | None,
                       independent_review: BootstrapIndependentReview | None,
                       unverified_hosts: tuple[str, ...] = (),
                       bootstrap_policy_sha256: str | None = None) -> BootstrapResult:
    """Evaluate Bootstrap inputs without changing the normal delivery gate."""
    subject.validate()
    reasons = _pr_reasons(subject, pr, response_repository)
    if bootstrap_policy_sha256 is None:
        reasons.append("Bootstrap evaluator/adapter source digest is unavailable")
    else:
        try:
            _sha(bootstrap_policy_sha256, "Bootstrap policy digest")
        except GatePolicyError as exc:
            reasons.append(str(exc))
    latest_runs = [run for run in workflow_runs if isinstance(run, dict)
                   and run.get("path") == ".github/workflows/ci.yml"
                   and run.get("head_sha") == subject.head_sha40
                   and run.get("event") == "pull_request"]
    workflow_run_id = None
    workflow_status = None
    workflow_conclusion = None
    if not latest_runs:
        reasons.append("current-head pull_request CI workflow run is missing")
    else:
        latest_workflow = max(latest_runs, key=lambda row: (
            row.get("run_number", 0) if type(row.get("run_number")) is int else 0,
            row.get("run_attempt", 0) if type(row.get("run_attempt")) is int else 0,
            row.get("id", 0) if type(row.get("id")) is int else 0))
        if type(latest_workflow.get("id")) is int and latest_workflow["id"] > 0:
            workflow_run_id = latest_workflow["id"]
        else:
            reasons.append("current-head CI workflow run ID is invalid")
        workflow_status = latest_workflow.get("status") if isinstance(latest_workflow.get("status"), str) else None
        workflow_conclusion = latest_workflow.get("conclusion") if isinstance(latest_workflow.get("conclusion"), str) else None
        if latest_workflow.get("status") != "completed" or latest_workflow.get("conclusion") != "success":
            reasons.append("latest current-head CI workflow run is not completed/success")
        if latest_workflow.get("head_branch") != subject.head_ref:
            reasons.append("CI workflow run head branch differs from the current PR")
        head_repository = latest_workflow.get("head_repository")
        if (not isinstance(head_repository, dict)
                or not isinstance(head_repository.get("full_name"), str)
                or head_repository["full_name"].casefold() != subject.repository.casefold()):
            reasons.append("CI workflow run repository differs from the current PR repository")
        pull_requests = latest_workflow.get("pull_requests")
        if not isinstance(pull_requests, list) or not any(
                isinstance(row, dict) and row.get("number") == subject.pr_number for row in pull_requests):
            reasons.append("CI workflow run is not associated with the current PR")
    configured_checks = tuple(required_check_names)
    if not configured_checks or len(configured_checks) != len(set(configured_checks)):
        reasons.append("Bootstrap trusted project Required Check name set is empty or duplicated")
    required = configured_checks + BOOTSTRAP_REQUIRED_JOBS
    job_results, job_reasons = _latest_check_results(check_runs, required, subject.head_sha40)
    reasons.extend(job_reasons)
    if type(local_checks) is not tuple or tuple(check.name for check in local_checks) != REQUIRED_LOCAL_CHECKS:
        reasons.append("local Bootstrap check set is incomplete or out of order")
    else:
        for check in local_checks:
            try:
                check.validate()
            except GatePolicyError as exc:
                reasons.append(str(exc))
            else:
                if check.status != "completed" or check.exit_status != 0 or check.output_truncated:
                    reasons.append(f"local check did not complete cleanly: {check.name}")
    required_ids = tuple(sorted(tuple(adc_requirement_ids) + tuple(adc_checklist_ids)))
    if self_review is None:
        reasons.append("ADC-wide self-review evidence is missing")
    else:
        try:
            self_review.validate(required_ids)
        except GatePolicyError as exc:
            reasons.append(f"self-review is invalid: {exc}")
        if self_review.subject != subject:
            reasons.append("self-review is bound to a different Bootstrap subject")
    if independent_review is None:
        reasons.append("separate-context independent review evidence is missing")
    else:
        try:
            independent_review.validate()
        except GatePolicyError as exc:
            reasons.append(f"independent review is invalid: {exc}")
        if independent_review.subject != subject:
            reasons.append("independent review is bound to a different Bootstrap subject")
    if (type(unverified_hosts) is not tuple or not unverified_hosts
            or any(not isinstance(host, str) or not host.strip() for host in unverified_hosts)):
        reasons.append("unverified-host disclosure is invalid")
    status = "BOOTSTRAP_REVIEW_READY" if not reasons else "BOOTSTRAP_BLOCKED"
    candidate_evidence = tuple(
        (self_review.verified_evidence if self_review is not None else ())
        + (independent_review.verified_evidence if independent_review is not None else ())
    )
    verified_evidence = tuple(
        artifact for artifact in candidate_evidence
        if isinstance(artifact, VerifiedReviewEvidence) and artifact.head_sha40 == subject.head_sha40
    )
    context_verified = (independent_review is not None and independent_review.context_artifact_verified is True
                        and independent_review.context_artifact_comment_id is not None
                        and independent_review.separate_context_confirmed is True)
    return BootstrapResult(status, subject, tuple(dict.fromkeys(reasons)), local_checks, tuple(job_results),
                           workflow_run_id, workflow_status, workflow_conclusion,
                           self_review.comment_id if self_review else None,
                           independent_review.comment_id if independent_review else None,
                           unverified_hosts, bootstrap_policy_sha256, verified_evidence,
                           (independent_review.context_artifact_comment_id if context_verified else None),
                           (independent_review.context_artifact_sha256 if context_verified else None),
                           context_verified).validate()


def _decode_record_comment(body: Any, sentinel: str) -> dict[str, Any]:
    if not isinstance(body, str) or not body.startswith(f"<!-- {sentinel}\n") or not body.endswith("\n-->"):
        raise GatePolicyError(f"comment is not a {sentinel} record")
    raw = body[len(f"<!-- {sentinel}\n"):-len("\n-->")]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GatePolicyError(f"{sentinel} record JSON is malformed") from exc
    if not isinstance(value, dict):
        raise GatePolicyError(f"{sentinel} record must be a JSON object")
    if _canonical(value).decode("utf-8") != raw:
        raise GatePolicyError(f"{sentinel} record is not canonical JSON")
    return value


def parse_self_review_comment(body: Any, comment_id: int) -> BootstrapSelfReview:
    value = _decode_record_comment(body, "PASES_BOOTSTRAP_SELF_REVIEW_V1")
    expected = {"context_id", "items", "review_sha256", "schema", "subject"}
    if set(value) != expected or value.get("schema") != "PASES_BOOTSTRAP_SELF_REVIEW_V1":
        raise GatePolicyError("Bootstrap self-review record has unknown fields")
    digest = value["review_sha256"]
    base = {key: item for key, item in value.items() if key != "review_sha256"}
    if not isinstance(digest, str) or hashlib.sha256(_canonical(base)).hexdigest() != digest:
        raise GatePolicyError("Bootstrap self-review digest is invalid")
    if not isinstance(value["items"], list):
        raise GatePolicyError("Bootstrap self-review items are malformed")
    items: list[ReviewItem] = []
    for item in value["items"]:
        if not isinstance(item, dict) or set(item) != {"evidence_refs", "item_id", "status"} or not isinstance(item["evidence_refs"], list):
            raise GatePolicyError("Bootstrap self-review item is malformed")
        items.append(ReviewItem(item["item_id"], item["status"], tuple(item["evidence_refs"])))
    return BootstrapSelfReview(BootstrapSubject.from_dict(value["subject"]), value["context_id"],
                               tuple(items), _positive(comment_id, "Self-review Comment ID"))


def parse_independent_review_comment(body: Any, comment_id: int) -> BootstrapIndependentReview:
    value = _decode_record_comment(body, "PASES_BOOTSTRAP_INDEPENDENT_REVIEW_V1")
    expected = {"context_artifact_ref", "context_artifact_sha256", "findings", "implementation_context_id",
                "review_sha256", "reviewer_context_id", "schema", "separate_context_confirmed", "subject", "verdict"}
    if set(value) != expected or value.get("schema") != "PASES_BOOTSTRAP_INDEPENDENT_REVIEW_V1":
        raise GatePolicyError("Bootstrap independent-review record has unknown fields")
    digest = value["review_sha256"]
    base = {key: item for key, item in value.items() if key != "review_sha256"}
    if not isinstance(digest, str) or hashlib.sha256(_canonical(base)).hexdigest() != digest:
        raise GatePolicyError("Bootstrap independent-review digest is invalid")
    if not isinstance(value["findings"], list):
        raise GatePolicyError("Bootstrap independent-review findings are malformed")
    findings: list[ReviewFinding] = []
    for item in value["findings"]:
        expected_finding = {"description", "evidence_ref", "finding_id", "resolved", "severity"}
        if not isinstance(item, dict) or set(item) != expected_finding:
            raise GatePolicyError("Bootstrap independent-review finding is malformed")
        findings.append(ReviewFinding(item["finding_id"], item["severity"], item["resolved"],
                                      item["description"], item["evidence_ref"]))
    return BootstrapIndependentReview(BootstrapSubject.from_dict(value["subject"]),
                                      value["reviewer_context_id"], value["implementation_context_id"],
                                      value["context_artifact_ref"], value["context_artifact_sha256"],
                                      value["separate_context_confirmed"], tuple(findings), value["verdict"],
                                      _positive(comment_id, "Independent-review Comment ID"))


def parse_independent_context_artifact(body: Any, comment_id: int) -> BootstrapReviewContextArtifact:
    value = _decode_record_comment(body, "PASES_BOOTSTRAP_INDEPENDENT_CONTEXT_V1")
    expected = {"report", "reviewer_context_id", "schema", "separate_context_confirmed", "subject"}
    if set(value) != expected or value.get("schema") != "PASES_BOOTSTRAP_INDEPENDENT_CONTEXT_V1":
        raise GatePolicyError("Independent context artifact has unknown fields")
    return BootstrapReviewContextArtifact(
        BootstrapSubject.from_dict(value["subject"]), value["reviewer_context_id"],
        value["separate_context_confirmed"], value["report"],
        _positive(comment_id, "Independent context artifact Comment ID"))


def read_review_comment(github: GitHub, issue_number: int, comment_id: int, sentinel: str) -> dict[str, Any]:
    try:
        comment = github.issue_comment(issue_number, comment_id)
    except GitHubError as exc:
        raise GatePolicyError(f"review comment readback failed: {exc}") from exc
    if comment.get("id") != comment_id:
        raise GatePolicyError("review comment readback ID does not match the requested ID")
    issue_url = comment.get("issue_url")
    expected_suffix = f"/repos/{github.repo}/issues/{issue_number}"
    if not isinstance(issue_url, str) or not issue_url.casefold().endswith(expected_suffix.casefold()):
        raise GatePolicyError("review evidence comment belongs to a different Issue")
    _decode_record_comment(comment.get("body"), sentinel)
    return comment


def _github_reference_parts(reference: str, subject: BootstrapSubject) -> tuple[list[str], str]:
    try:
        parsed = urlparse(reference)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise GatePolicyError("review evidence reference is not a valid GitHub URL") from exc
    if (parsed.scheme != "https" or parsed.netloc.casefold() != "github.com" or parsed.query
            or parsed.username is not None or parsed.password is not None or port is not None):
        raise GatePolicyError("review evidence must use a canonical HTTPS GitHub reference")
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if (len(parts) < 2 or f"{parts[0]}/{parts[1]}".casefold() != subject.repository.casefold()
            or any(part in {".", ".."} or "\x00" in part for part in parts)):
        raise GatePolicyError("review evidence reference repository/path is invalid")
    return parts[2:], parsed.fragment


def _issue_comment_artifact(github: GitHub, subject: BootstrapSubject, reference: str,
                            *, exclude_comment_id: int | None = None) -> tuple[int, str]:
    suffix, fragment = _github_reference_parts(reference, subject)
    match = re.fullmatch(r"issuecomment-([1-9][0-9]{0,19})", fragment)
    if (len(suffix) != 2 or suffix[0] != "issues" or suffix[1] != str(subject.issue_number)
            or match is None):
        raise GatePolicyError("review Issue evidence must reference a comment on the exact subject Issue")
    comment_id = int(match.group(1))
    if comment_id == exclude_comment_id:
        raise GatePolicyError("review evidence cannot cite its own review comment as its artifact")
    try:
        comment = github.issue_comment(subject.issue_number, comment_id)
    except GitHubError as exc:
        raise GatePolicyError("review Issue comment artifact could not be read back") from exc
    issue_url = comment.get("issue_url")
    expected_suffix = f"/repos/{subject.repository}/issues/{subject.issue_number}"
    if (comment.get("id") != comment_id or not isinstance(comment.get("body"), str)
            or not isinstance(issue_url, str) or not issue_url.casefold().endswith(expected_suffix.casefold())):
        raise GatePolicyError("review Issue comment artifact identity/readback is invalid")
    if subject.head_sha40 not in comment["body"]:
        raise GatePolicyError("review Issue comment artifact does not identify the current PR HEAD")
    return comment_id, hashlib.sha256(comment["body"].encode("utf-8")).hexdigest()


def verify_bootstrap_review_evidence(github: GitHub, subject: BootstrapSubject, *,
                                     self_review: BootstrapSelfReview | None,
                                     independent_review: BootstrapIndependentReview | None,
                                     pr: dict[str, Any], workflow_runs: list[dict[str, Any]]) -> tuple[VerifiedReviewEvidence, ...]:
    """Read every review citation and bind its digest to the exact Bootstrap HEAD."""
    subject.validate()
    rows: list[VerifiedReviewEvidence] = []
    sources: list[tuple[str, ReviewItem | ReviewFinding, int | None]] = []
    if self_review is not None:
        sources.extend((item.item_id, item, self_review.comment_id) for item in self_review.items)
    if independent_review is not None:
        sources.extend((finding.finding_id, finding, independent_review.comment_id)
                       for finding in independent_review.findings)
    for item_id, item, review_comment_id in sources:
        refs = item.evidence_refs if isinstance(item, ReviewItem) else (item.evidence_ref,)
        for reference in refs:
            suffix, fragment = _github_reference_parts(reference, subject)
            kind: str
            digest: str
            if len(suffix) >= 3 and suffix[0] == "blob":
                ref_sha = suffix[1]
                path = "/".join(suffix[2:])
                if ref_sha != subject.head_sha40:
                    raise GatePolicyError("review source citation is not pinned to the current PR HEAD")
                try:
                    content = github.content_at_ref(path, ref_sha)
                except GitHubError as exc:
                    raise GatePolicyError("review source artifact could not be read at the current PR HEAD") from exc
                digest, kind = hashlib.sha256(content).hexdigest(), "git-blob"
            elif len(suffix) == 3 and suffix[0] == "actions" and suffix[1] == "runs" and not fragment:
                if not re.fullmatch(r"[1-9][0-9]*", suffix[2]):
                    raise GatePolicyError("review Actions evidence run ID is invalid")
                run_id = int(suffix[2])
                matches = [run for run in workflow_runs if isinstance(run, dict) and run.get("id") == run_id]
                if len(matches) != 1:
                    raise GatePolicyError("review Actions evidence run is absent or ambiguous")
                run = matches[0]
                head_repo = run.get("head_repository")
                prs = run.get("pull_requests")
                if (run.get("head_sha") != subject.head_sha40 or run.get("status") != "completed"
                        or run.get("conclusion") != "success" or run.get("event") != "pull_request"
                        or run.get("path") != ".github/workflows/ci.yml"
                        or run.get("head_branch") != subject.head_ref
                        or not isinstance(head_repo, dict)
                        or str(head_repo.get("full_name", "")).casefold() != subject.repository.casefold()
                        or not isinstance(prs, list)
                        or not any(isinstance(row, dict) and row.get("number") == subject.pr_number for row in prs)):
                    raise GatePolicyError("review Actions evidence run is not successful for the exact subject")
                digest, kind = hashlib.sha256(_canonical(run)).hexdigest(), "workflow-run"
            elif len(suffix) in {2, 3} and suffix[0] == "pull" and not fragment:
                if suffix[1] != str(subject.pr_number) or (len(suffix) == 3 and suffix[2] != "files"):
                    raise GatePolicyError("review PR evidence does not identify the current PR")
                snapshot = {key: pr.get(key) for key in ("number", "state", "draft", "body", "base", "head")}
                base, head = snapshot.get("base"), snapshot.get("head")
                if (snapshot.get("number") != subject.pr_number or not isinstance(base, dict)
                        or not isinstance(head, dict) or head.get("sha") != subject.head_sha40
                        or (base.get("ref"), base.get("sha"), head.get("ref"))
                        != (subject.base_ref, subject.base_sha40, subject.head_ref)):
                    raise GatePolicyError("review PR evidence readback is mismatched")
                digest, kind = hashlib.sha256(_canonical(snapshot)).hexdigest(), "pull-request"
            elif len(suffix) == 2 and suffix[0] == "issues":
                _comment_id, digest = _issue_comment_artifact(
                    github, subject, reference, exclude_comment_id=review_comment_id)
                kind = "issue-comment"
            else:
                raise GatePolicyError("review evidence reference must identify a pinned source, current PR, CI run, or Issue comment")
            rows.append(VerifiedReviewEvidence(item_id, reference, kind, digest, subject.head_sha40).validate(subject))
    return tuple(rows)


def verify_independent_context_artifact(github: GitHub, subject: BootstrapSubject,
                                        review: BootstrapIndependentReview) -> BootstrapIndependentReview:
    """Read the separate review artifact; confirmation is an explicit reviewer attestation, not host proof."""
    if review.subject != subject:
        raise GatePolicyError("Independent context artifact is for a different Bootstrap subject")
    comment_id, actual_digest = _issue_comment_artifact(
        github, subject, review.context_artifact_ref, exclude_comment_id=review.comment_id)
    if actual_digest != review.context_artifact_sha256:
        raise GatePolicyError("Independent context artifact content digest does not match its review record")
    try:
        comment = github.issue_comment(subject.issue_number, comment_id)
    except GitHubError as exc:
        raise GatePolicyError("Independent context artifact readback failed") from exc
    artifact = parse_independent_context_artifact(comment.get("body"), comment_id)
    artifact.validate(expected_subject=subject, expected_reviewer_context_id=review.reviewer_context_id)
    if review.separate_context_confirmed is not True:
        raise GatePolicyError("Independent review must explicitly confirm separate-context execution")
    return replace(review, context_artifact_verified=True, context_artifact_comment_id=comment_id)


def read_bootstrap_evidence(github: GitHub, issue_number: int, comment_id: int) -> dict[str, Any]:
    """Read one immutable Bootstrap result by ID and validate the append-only chain."""
    try:
        comments = github.issue_comments(issue_number)
        rows = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                and row["body"].startswith("<!-- PASES_BOOTSTRAP_REVIEW_V1\n")]
        previous_id: int | None = None
        selected: dict[str, Any] | None = None
        last_id = 0
        for attempt, row in enumerate(rows, 1):
            record = _decode_record_comment(row["body"], "PASES_BOOTSTRAP_REVIEW_V1")
            if set(record) != {"attempt", "previous_comment_id", "result", "schema"} or record.get("schema") != "PASES_BOOTSTRAP_REVIEW_V1":
                raise GatePolicyError("Bootstrap evidence history has an invalid record shape")
            if record.get("attempt") != attempt or record.get("previous_comment_id") != previous_id:
                raise GatePolicyError("Bootstrap evidence history has a duplicate or broken predecessor chain")
            current_id = _positive(row.get("id"), "Bootstrap evidence Comment ID")
            if current_id <= last_id:
                raise GatePolicyError("Bootstrap evidence Comment IDs are not strictly increasing")
            previous_id, last_id = current_id, current_id
            result = record.get("result")
            if not isinstance(result, dict) or result.get("schema") != "PASES_BOOTSTRAP_REVIEW_V1":
                raise GatePolicyError("Bootstrap evidence payload schema is invalid")
            BootstrapResult.from_payload(result)
            if current_id == comment_id:
                selected = result
        if selected is None:
            raise GatePolicyError("Bootstrap evidence Comment ID is absent from the verified history")
        named = github.issue_comment(issue_number, comment_id)
        row = next(item for item in rows if item.get("id") == comment_id)
        expected_issue_url = f"/repos/{github.repo}/issues/{issue_number}"
        if (named.get("body") != row.get("body") or named.get("id") != comment_id
                or not isinstance(named.get("issue_url"), str)
                or not named["issue_url"].endswith(expected_issue_url)):
            raise GatePolicyError("Bootstrap evidence exact-body readback failed")
        if selected.get("subject", {}).get("issue_number") != issue_number:
            raise GatePolicyError("Bootstrap evidence belongs to a different Issue")
        return selected
    except GitHubError as exc:
        raise GatePolicyError(f"Bootstrap evidence readback failed: {exc}") from exc


def pin_gate_selection(github: GitHub, selection: GateSelection) -> tuple[int, str]:
    """Keep a gate choice immutable; retries reuse an exact record only."""
    payload = selection.payload()
    try:
        comments = github.issue_comments(selection.issue_number)
    except GitHubError as exc:
        raise GatePolicyError(f"gate selection readback failed: {exc}") from exc
    rows = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
            and row["body"].startswith("<!-- PASES_GATE_SELECTION_V1\n")]
    if len(rows) > 1:
        raise GatePolicyError("multiple gate selection records exist")
    if rows:
        existing = GateSelection.from_payload(_decode_record_comment(rows[0]["body"], "PASES_GATE_SELECTION_V1"))
        if (existing.repository.casefold() != selection.repository.casefold()
                or existing.issue_number != selection.issue_number
                or existing.policy_version != selection.policy_version
                or existing.activation_comment_id != selection.activation_comment_id
                or existing.activation_sha256 != selection.activation_sha256):
            raise GatePolicyError("existing gate selection conflicts; policy cannot be switched")
        comment_id = _positive(rows[0].get("id"), "Gate selection Comment ID")
        named = _issue_comment_readback(github, selection.issue_number, comment_id)
        if named.get("body") != rows[0]["body"]:
            raise GatePolicyError("gate selection exact-body readback failed")
        return comment_id, rows[0]["body"]
    return publish_immutable_record(github, selection.issue_number, "PASES_GATE_SELECTION_V1", payload)


def publish_immutable_record(github: GitHub, issue_number: int, sentinel: str, payload: dict[str, Any]) -> tuple[int, str]:
    """Create or exactly reuse one append-only record, then read it back by ID."""
    if not re.fullmatch(r"PASES_[A-Z0-9_]+_V1", sentinel):
        raise GatePolicyError("record sentinel is invalid")
    body = f"<!-- {sentinel}\n{_canonical(payload).decode('utf-8')}\n-->"
    try:
        comments = github.issue_comments(issue_number)
        existing = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                    and row["body"].startswith(f"<!-- {sentinel}\n")]
        if sentinel == "PASES_BOOTSTRAP_REVIEW_V1":
            previous_id: int | None = None
            last_payload: dict[str, Any] | None = None
            last_comment_id = 0
            for attempt, row in enumerate(existing, 1):
                record = _decode_record_comment(row["body"], sentinel)
                if set(record) != {"attempt", "previous_comment_id", "result", "schema"} or record.get("schema") != sentinel:
                    raise GatePolicyError("Bootstrap review history has an invalid record shape")
                if record.get("attempt") != attempt or record.get("previous_comment_id") != previous_id:
                    raise GatePolicyError("Bootstrap review history has a duplicate or broken predecessor chain")
                result_value = record.get("result")
                if (not isinstance(result_value, dict) or result_value.get("schema") != sentinel
                        or not isinstance(result_value.get("subject"), dict)
                        or result_value["subject"].get("issue_number") != issue_number):
                    raise GatePolicyError("Bootstrap review history subject is invalid")
                BootstrapResult.from_payload(result_value)
                previous_id = _positive(row.get("id"), "Bootstrap review Comment ID")
                if previous_id <= last_comment_id:
                    raise GatePolicyError("Bootstrap review Comment IDs are not strictly increasing")
                last_comment_id = previous_id
                last_payload = result_value
            if last_payload == payload:
                assert previous_id is not None
                latest = existing[-1]
                named = _issue_comment_readback(github, issue_number, previous_id)
                if named.get("body") != latest.get("body"):
                    raise GatePolicyError("Bootstrap review retry readback does not match the latest immutable record")
                return previous_id, latest["body"]
            attempt = len(existing) + 1
            envelope = {"attempt": attempt, "previous_comment_id": previous_id,
                        "result": payload, "schema": sentinel}
            body = f"<!-- {sentinel}\n{_canonical(envelope).decode('utf-8')}\n-->"
            named_issue = github.issue(issue_number)
            if named_issue.get("state") != "open":
                raise GatePolicyError("Bootstrap evidence can only be appended while its Issue is open")
            created = github.create_issue_comment(issue_number, body)
            comment_id = _positive(created.get("id") if isinstance(created, dict) else None,
                                   f"created {sentinel} Comment ID")
            named = _issue_comment_readback(github, issue_number, comment_id)
            if named.get("body") != body:
                raise GatePolicyError(f"{sentinel} exact-body readback failed")
            verify_rows = [row for row in github.issue_comments(issue_number)
                           if isinstance(row, dict) and isinstance(row.get("body"), str)
                           and row["body"].startswith(f"<!-- {sentinel}\n")]
            if len(verify_rows) != attempt or verify_rows[-1].get("id") != comment_id:
                raise GatePolicyError(f"{sentinel} append-only history changed during publication")
            return comment_id, body
        exact = [row for row in existing if row.get("body") == body]
        if len(existing) > 1:
            raise GatePolicyError(f"multiple {sentinel} records exist; refusing ambiguous evidence")
        if existing and not exact:
            raise GatePolicyError(f"a conflicting immutable {sentinel} record already exists")
        if exact:
            comment_id = _positive(exact[0].get("id"), f"{sentinel} Comment ID")
        else:
            issue = github.issue(issue_number)
            if issue.get("state") != "open":
                raise GatePolicyError(f"{sentinel} can only be published to an open Issue")
            created = github.create_issue_comment(issue_number, body)
            comment_id = _positive(created.get("id") if isinstance(created, dict) else None,
                                   f"created {sentinel} Comment ID")
        named = _issue_comment_readback(github, issue_number, comment_id)
        if named.get("body") != body:
            raise GatePolicyError(f"{sentinel} exact-body readback failed")
        readback = github.issue_comments(issue_number)
        matching = [row for row in readback if isinstance(row, dict) and row.get("body") == body]
        if len(matching) != 1:
            raise GatePolicyError(f"{sentinel} readback is missing or duplicated")
        return comment_id, body
    except GitHubError as exc:
        raise GatePolicyError(f"GitHub {sentinel} readback/publication failed: {exc}") from exc


def _validate_activation_candidate(github: GitHub, record: ActivationRecord) -> None:
    record.validate()
    integration = _issue_comment_readback(github, BOOTSTRAP_PARENT, record.integration_evidence_comment_id)
    integration_payload = _decode_record_comment(integration.get("body"), "PASES_INTEGRATION_EVIDENCE_V1")
    expected_integration_fields = {"documentation_pass", "distribution_pass", "evidence_refs", "integration_commit_sha40",
                                   "repository", "schema", "skills_count", "status", "tests_pass", "child_prs"}
    if set(integration_payload) != expected_integration_fields or integration_payload.get("schema") != "PASES_INTEGRATION_EVIDENCE_V1":
        raise GatePolicyError("parent integration evidence record has unknown or missing fields")
    digest = hashlib.sha256(_canonical(integration_payload)).hexdigest()
    expected_child_prs = [{"issue_number": issue, "pr_number": pr, "merge_sha40": sha}
                          for issue, pr, sha in record.child_prs]
    refs = integration_payload.get("evidence_refs")
    integration_repo = integration_payload.get("repository")
    if (digest != record.integration_evidence_sha256
            or not isinstance(integration_repo, str)
            or integration_repo.casefold() != record.repository.casefold()
            or integration_payload.get("status") != "PASS"
            or integration_payload.get("documentation_pass") is not True
            or integration_payload.get("tests_pass") is not True
            or integration_payload.get("distribution_pass") is not True
            or integration_payload.get("skills_count") != 16
            or integration_payload.get("integration_commit_sha40") != record.activation_commit_sha40
            or integration_payload.get("child_prs") != expected_child_prs
            or not isinstance(refs, list) or not refs
            or any(not isinstance(ref, str) or not ref.startswith("https://") for ref in refs)):
        raise GatePolicyError("parent integration evidence is incomplete or mismatched")

    approval = _issue_comment_readback(github, BOOTSTRAP_PARENT, record.approval_comment_id)
    approval_payload = _decode_record_comment(approval.get("body"), "PASES_ACTIVATION_APPROVAL_V1")
    expected_approval = {"approved": True, "activation_commit_sha40": record.activation_commit_sha40,
                         "child_issue_numbers": list(record.child_issue_numbers), "child_prs": expected_child_prs,
                         "integration_evidence_sha256": record.integration_evidence_sha256,
                         "repository": record.repository, "schema": "PASES_ACTIVATION_APPROVAL_V1"}
    if approval_payload != expected_approval:
        raise GatePolicyError("activation approval record is missing or mismatched")
    _require_repository_owner_actor(approval.get("user"), record.repository, "Activation approval")
    integration_created = _parse_time(integration.get("created_at"), "Integration evidence")
    approval_created = _parse_time(approval.get("created_at"), "Activation approval")
    if integration_created > approval_created:
        raise GatePolicyError("activation approval predates the integration evidence")
    activation_at = _parse_time(record.activated_at, "Activation")
    now = datetime.now(timezone.utc)
    if activation_at < approval_created or activation_at > now:
        raise GatePolicyError("activation timestamp is outside the explicit approval window")

    for issue_number, pr_number, merge_sha in record.child_prs:
        issue = github.issue(issue_number)
        pr = github.pull_request(pr_number)
        if issue.get("state") != "closed":
            raise GatePolicyError(f"child Issue #{issue_number} is not closed")
        if (pr.get("state") != "closed" or pr.get("merged") is not True
                or pr.get("merge_commit_sha") != merge_sha):
            raise GatePolicyError(f"child PR #{pr_number} is not merged at the activation SHA")
        _require_repository_owner_actor(pr.get("merged_by"), record.repository,
                                        f"child PR #{pr_number} merge")
        base = pr.get("base")
        head = pr.get("head")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        head_repo = head.get("repo") if isinstance(head, dict) else None
        base_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
        head_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
        if (not isinstance(base_name, str) or base_name.casefold() != record.repository.casefold()
                or not isinstance(head_name, str) or head_name.casefold() != record.repository.casefold()):
            raise GatePolicyError(f"child PR #{pr_number} did not use same-repository branches")
        expected_pair = EXPECTED_BRANCH_PAIRS.get(issue_number)
        if expected_pair is None or (base.get("ref"), head.get("ref")) != expected_pair:
            raise GatePolicyError(f"child PR #{pr_number} has no matching approved base/head branch contract")
        body = pr.get("body")
        if (not isinstance(body, str)
                or [int(value) for value in _CLOSES_ANY.findall(body)] != [issue_number]
                or [int(value) for value in _CLOSES_LINE.findall(body)] != [issue_number]):
            raise GatePolicyError(f"child PR #{pr_number} does not have its standalone Closes association")


def _issue_comment_readback(github: GitHub, issue_number: int, comment_id: int) -> dict[str, Any]:
    comment = github.issue_comment(issue_number, comment_id)
    expected_suffix = f"/repos/{github.repo}/issues/{issue_number}"
    if (comment.get("id") != comment_id or not isinstance(comment.get("issue_url"), str)
            or not comment["issue_url"].endswith(expected_suffix)):
        raise GatePolicyError("Issue comment identity readback failed")
    return comment


def _require_repository_owner_actor(actor: Any, repository: str, label: str) -> None:
    owner = repository.split("/", 1)[0]
    login = actor.get("login") if isinstance(actor, dict) else None
    if not isinstance(login, str) or login.casefold() != owner.casefold():
        raise GatePolicyError(f"{label} must be explicitly performed by repository owner {owner}")


def read_activation_record(github: GitHub, repository: str) -> tuple[ActivationRecord, int] | None:
    """Read and validate the unique activation, its evidence, child merges, and user approval."""
    try:
        comments = github.issue_comments(BOOTSTRAP_PARENT)
        rows = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                and row["body"].startswith("<!-- PASES_ACTIVATION_V1\n")]
        if not rows:
            return None
        if len(rows) != 1:
            raise GatePolicyError("multiple activation records exist")
        comment = rows[0]
        record = ActivationRecord.from_payload(_decode_record_comment(comment["body"], "PASES_ACTIVATION_V1"))
        if record.repository.casefold() != repository.casefold():
            raise GatePolicyError("activation record belongs to a different repository")
        _validate_activation_candidate(github, record)
        comment_id = _positive(comment.get("id"), "Activation Comment ID")
        named = _issue_comment_readback(github, BOOTSTRAP_PARENT, comment_id)
        expected_issue_url = f"/repos/{github.repo}/issues/{BOOTSTRAP_PARENT}"
        if (named.get("id") != comment_id or named.get("body") != comment.get("body")
                or not isinstance(named.get("issue_url"), str)
                or not named["issue_url"].endswith(expected_issue_url)):
            raise GatePolicyError("activation record exact-body readback failed")
        created_at = _parse_time(comment.get("created_at"), "Activation record")
        approved = _issue_comment_readback(github, BOOTSTRAP_PARENT, record.approval_comment_id)
        integration = _issue_comment_readback(github, BOOTSTRAP_PARENT, record.integration_evidence_comment_id)
        approved_at = _parse_time(approved.get("created_at"), "Activation approval")
        integration_at = _parse_time(integration.get("created_at"), "Integration evidence")
        activated_at = _parse_time(record.activated_at, "Activation")
        if (integration_at > approved_at or approved_at > created_at
                or activated_at < approved_at or activated_at > created_at.replace(microsecond=0)):
            raise GatePolicyError("activation record was not created after integration evidence and explicit approval")
        return record, comment_id
    except (GitHubError, KeyError, TypeError) as exc:
        raise GatePolicyError(f"activation GitHub readback failed: {exc}") from exc


def publish_activation_record(github: GitHub, record: ActivationRecord) -> tuple[int, str]:
    """Publish only after independent evidence and an explicit approval comment read back."""
    try:
        _validate_activation_candidate(github, record)
    except GitHubError as exc:
        raise GatePolicyError(f"activation prerequisites readback failed: {exc}") from exc
    comment_id, body = publish_immutable_record(github, BOOTSTRAP_PARENT, "PASES_ACTIVATION_V1", record.payload())
    readback = read_activation_record(github, record.repository)
    if readback is None or readback[1] != comment_id or readback[0] != record:
        raise GatePolicyError("activation record readback does not match the published record")
    return comment_id, body


def choose_gate_for_new_issue(github: GitHub, repository: str, issue_number: int,
                              selected_at: str) -> GateSelection | None:
    if issue_number in BOOTSTRAP_COHORT:
        return select_gate(repository, issue_number, selected_at=selected_at)
    activation_row = read_activation_record(github, repository)
    if activation_row is None:
        return None
    try:
        issue = github.issue(issue_number)
    except GitHubError as exc:
        raise GatePolicyError(f"new Issue creation-date readback failed: {exc}") from exc
    if issue.get("number") != issue_number or issue.get("pull_request") is not None:
        raise GatePolicyError("gate policy selection requires the exact Issue resource")
    activation, comment_id = activation_row
    return select_gate(repository, issue_number, selected_at=selected_at, activation=activation,
                       activation_comment_id=comment_id, activation_sha256=activation.sha256,
                       issue_created_at=issue.get("created_at"))


def run_local_bootstrap_checks(root: Path) -> tuple[LocalCheck, ...]:
    """Execute the fixed local test/static/distribution commands with bounded argv runs."""
    root = Path(root)
    commands = (
        ("compileall", (sys.executable, "-m", "compileall", "runtime", "tools", "tests")),
        ("unittest", (sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py")),
        ("dist-build-check", (sys.executable, "tools/build_dist.py", "--check")),
        ("dist-validation", (sys.executable, "tools/validate_dist.py")),
        ("diff-check", ("git", "diff", "--check")),
    )
    results: list[LocalCheck] = []
    for name, argv in commands:
        try:
            outcome = run_process(argv, cwd=root, timeout_seconds=600, max_output_bytes=4 * 1024 * 1024)
        except ProcessError as exc:
            raise GatePolicyError(f"could not execute local Bootstrap check {name}: {exc}") from exc
        output_hash = hashlib.sha256((outcome.stdout + "\x00" + outcome.stderr).encode("utf-8")).hexdigest()
        results.append(LocalCheck(name, tuple(argv), outcome.status, outcome.exit_status,
                                  output_hash, outcome.output_truncated).validate())
    return tuple(results)


def current_checkout_subject(root: Path, subject: BootstrapSubject) -> None:
    """Require tests to run from a clean checkout at the exact PR HEAD."""
    try:
        head = run_git(root, "rev-parse", "HEAD")
        branch = run_git(root, "symbolic-ref", "--short", "HEAD")
        status = run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    except GitError as exc:
        raise GatePolicyError(f"local Git readback failed: {exc}") from exc
    if head != subject.head_sha40:
        raise GatePolicyError("local checkout HEAD differs from current PR HEAD")
    if branch != subject.head_ref:
        raise GatePolicyError("local checkout branch differs from current PR head branch")
    if status:
        raise GatePolicyError("local checkout is not clean; Bootstrap checks would include uncommitted changes")


def run_local_bootstrap_checks_bound(root: Path, subject: BootstrapSubject) -> tuple[LocalCheck, ...]:
    """Run checks only while the exact target branch remains a clean checkout."""
    current_checkout_subject(root, subject)
    results = run_local_bootstrap_checks(root)
    current_checkout_subject(root, subject)
    return results
