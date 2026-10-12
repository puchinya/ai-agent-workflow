"""Pure Review Readiness aggregation. This module never starts User Review."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .acceptance import AcceptanceResult
from .audits import AuditError, IndependentReview, SelfAudit
from .checkpoint import CheckpointError, PRBinding
from .context import WorkContext, WorkContextError
from .evidence_store import VerificationSubject
from .path_safety import path_has_symlink
from .verification import VerificationResult, VERDICTS


class ReadinessError(ValueError):
    pass


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class PRReadback:
    repository: str
    issue_number: int
    pr_number: int
    state: str
    draft: bool
    base_ref: str
    base_sha40: str
    head_ref: str
    head_sha40: str
    head_repository: str
    closing_issue_number: int

    def validate(self) -> "PRReadback":
        if not isinstance(self.repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise ReadinessError("PR readback repository is invalid")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise ReadinessError("PR readback Issue number must be positive")
        if type(self.pr_number) is not int or self.pr_number < 1:
            raise ReadinessError("PR readback number must be positive")
        if not isinstance(self.state, str) or self.state not in {"open", "closed"}:
            raise ReadinessError("PR readback state is unknown")
        if type(self.draft) is not bool:
            raise ReadinessError("PR draft readback must be boolean")
        if not isinstance(self.base_ref, str) or not self.base_ref:
            raise ReadinessError("PR base ref readback is missing")
        if not isinstance(self.base_sha40, str) or not SHA40.fullmatch(self.base_sha40):
            raise ReadinessError("PR base SHA readback must be a full SHA-40")
        if not isinstance(self.head_ref, str) or not self.head_ref:
            raise ReadinessError("PR head ref readback is missing")
        if not isinstance(self.head_sha40, str) or not SHA40.fullmatch(self.head_sha40):
            raise ReadinessError("PR readback HEAD must be a full SHA-40")
        if not isinstance(self.head_repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.head_repository):
            raise ReadinessError("PR head repository readback is invalid")
        if type(self.closing_issue_number) is not int or self.closing_issue_number < 1:
            raise ReadinessError("PR closing Issue reference is missing")
        return self


@dataclass(frozen=True)
class ReadinessResult:
    status: str
    subject: VerificationSubject
    reasons: tuple[str, ...]
    evidence_sha256s: tuple[str, ...]
    required_check_policy_sha256: str | None = None

    def validate(self) -> "ReadinessResult":
        if not isinstance(self.status, str) or self.status not in VERDICTS:
            raise ReadinessError("Readiness result status is invalid")
        self.subject.validate()
        if type(self.reasons) is not tuple or any(not isinstance(reason, str) or not reason for reason in self.reasons):
            raise ReadinessError("Readiness result reasons are invalid")
        if (self.status == "PASS" and self.reasons) or (self.status != "PASS" and not self.reasons):
            raise ReadinessError("Readiness status and explanation reasons are inconsistent")
        if (type(self.evidence_sha256s) is not tuple
                or any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in self.evidence_sha256s)):
            raise ReadinessError("Readiness evidence digests are invalid")
        if self.evidence_sha256s != tuple(sorted(set(self.evidence_sha256s))):
            raise ReadinessError("Readiness evidence digests must be sorted and unique")
        if self.required_check_policy_sha256 is not None and not SHA256.fullmatch(self.required_check_policy_sha256):
            raise ReadinessError("Readiness Required Check policy digest is invalid")
        if self.status == "PASS" and self.required_check_policy_sha256 is None:
            raise ReadinessError("Readiness PASS requires an exact Required Check policy digest")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {
            "evidence_sha256s": list(self.evidence_sha256s),
            "policy_version": "PASES_REVIEW_READINESS_V1",
            "reasons": list(self.reasons),
            "required_check_policy_sha256": self.required_check_policy_sha256,
            "schema": "PASES_REVIEW_READINESS_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "evidence_sha256s": list(self.evidence_sha256s),
            "policy_version": "PASES_REVIEW_READINESS_V1",
            "reasons": list(self.reasons),
            "required_check_policy_sha256": self.required_check_policy_sha256,
            "schema": "PASES_REVIEW_READINESS_V1",
            "status": self.status,
            "subject": self.subject.as_dict(),
        }

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["readiness_sha256"] = self.sha256
        return _canonical(value) + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ReadinessResult":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReadinessError("Readiness result is not valid UTF-8 JSON") from exc
        expected = {
            "evidence_sha256s", "policy_version", "readiness_sha256", "reasons",
            "required_check_policy_sha256", "schema", "status", "subject",
        }
        if (not isinstance(value, dict) or set(value) != expected
                or value.get("schema") != "PASES_REVIEW_READINESS_V1"
                or value.get("policy_version") != "PASES_REVIEW_READINESS_V1"
                or not isinstance(value.get("evidence_sha256s"), list)
                or not isinstance(value.get("reasons"), list)):
            raise ReadinessError("Readiness result has unknown/missing fields or schema")
        result = cls(
            value["status"], VerificationSubject.from_dict(value["subject"]),
            tuple(value["reasons"]), tuple(value["evidence_sha256s"]),
            value["required_check_policy_sha256"],
        ).validate()
        if value["readiness_sha256"] != result.sha256 or result.to_bytes() != raw:
            raise ReadinessError("Readiness digest or canonical bytes do not match")
        return result

    @property
    def ready_for_user_review(self) -> bool:
        return self.status == "PASS"


def evaluate_readiness(
    *,
    subject: VerificationSubject,
    pr: PRReadback,
    pr_binding: PRBinding,
    work_context: WorkContext,
    verification: VerificationResult | None,
    acceptance: AcceptanceResult | None,
    self_audit: SelfAudit | None,
    required_item_ids: Iterable[str],
    independent_review: IndependentReview | None,
    required_checks_sha256: str | None,
    blocker_reasons: Iterable[str] = (),
) -> ReadinessResult:
    """Pass only when every exact-subject proof and the open PR read back agree."""
    if not isinstance(subject, VerificationSubject):
        raise ReadinessError("Readiness requires an exact Verification subject")
    subject.validate()
    reasons: list[str] = []
    digest_refs: set[str] = set()
    required_check_policy_sha256: str | None = None
    for reason in blocker_reasons:
        if not isinstance(reason, str) or not reason.strip():
            raise ReadinessError("Readiness blocker reasons must be non-empty text")
        reasons.append(reason.strip())

    pr_readback_valid = False
    if not isinstance(pr, PRReadback):
        reasons.append("GitHub PR readback is missing")
    else:
        try:
            pr.validate()
            pr_readback_valid = True
            if (pr.repository != subject.repository or pr.issue_number != subject.issue_number
                    or pr.pr_number != subject.pr_number or pr.state != "open" or pr.draft
                    or pr.head_sha40 != subject.pr_head_sha40 or pr.head_repository != subject.repository
                    or pr.closing_issue_number != subject.issue_number):
                reasons.append("GitHub PR readback is not the same open, non-draft, non-fork exact subject")
        except ReadinessError as exc:
            reasons.append(f"PR readback is invalid: {exc}")

    if not isinstance(pr_binding, PRBinding):
        reasons.append("PRBinding is missing")
    else:
        try:
            pr_binding.validate()
            if (pr_binding.repository != subject.repository or pr_binding.issue_number != subject.issue_number
                    or pr_binding.pr_number != subject.pr_number or pr_binding.adc_comment_id != subject.adc_comment_id
                    or pr_binding.adc_sha256 != subject.adc_sha256 or pr_binding.pr_head_sha40 != subject.pr_head_sha40
                    or (pr_readback_valid and (pr_binding.base_sha40 != pr.base_sha40
                                                or pr_binding.branch_ref != pr.head_ref))):
                reasons.append("PRBinding does not match the exact Verification subject")
            digest_refs.add(pr_binding.sha256)
        except CheckpointError as exc:
            reasons.append(f"PRBinding is invalid: {exc}")

    if not isinstance(work_context, WorkContext):
        reasons.append("work context is missing")
    else:
        try:
            work_context.validate()
            binding = work_context.execution_binding
            if (binding.repository != subject.repository or binding.issue_number != subject.issue_number
                    or binding.adc_comment_id != subject.adc_comment_id or binding.adc_sha256 != subject.adc_sha256
                    or work_context.current_head_sha40 != subject.pr_head_sha40
                    or not work_context.worktree_clean
                    or (pr_readback_valid and (binding.base_sha != pr.base_sha40
                                               or binding.base_ref != pr.base_ref
                                               or work_context.branch_ref != pr.head_ref))):
                reasons.append("work context is stale, dirty, or bound to a different exact subject")
            digest_refs.add(work_context.execution_binding_sha256)
        except WorkContextError as exc:
            reasons.append(f"work context is invalid: {exc}")

    if not isinstance(verification, VerificationResult):
        reasons.append("#29 Verification result is missing")
    else:
        try:
            verification.validate()
        except ValueError as exc:
            reasons.append(f"#29 Verification result is invalid: {exc}")
        else:
            if verification.subject != subject:
                reasons.append("#29 Verification result is stale or belongs to a different exact subject")
            if verification.status != "PASS":
                reasons.append(f"Verification status is {verification.status}")
            required_check_policy_sha256 = verification.required_check_policy_sha256
            if required_check_policy_sha256 is None or verification.check_result_sha256 is None:
                reasons.append("Verification has no trusted Required Check policy/result digest")
            digest_refs.add(verification.sha256)
            if verification.check_result_sha256 is not None:
                digest_refs.add(verification.check_result_sha256)
            if required_check_policy_sha256 is not None:
                digest_refs.add(required_check_policy_sha256)

    if not isinstance(required_checks_sha256, str) or not SHA256.fullmatch(required_checks_sha256):
        reasons.append("Required Checks result digest is missing or invalid")
    elif (verification is not None and verification.check_result_sha256 is not None
          and required_checks_sha256 != verification.check_result_sha256):
        reasons.append("Required Checks result differs from the #29 Verification readback")

    if not isinstance(acceptance, AcceptanceResult):
        reasons.append("Acceptance result is missing")
    else:
        try:
            acceptance.validate()
        except ValueError as exc:
            reasons.append(f"Acceptance result is invalid: {exc}")
        else:
            if acceptance.subject != subject:
                reasons.append("Acceptance result belongs to a different exact subject")
            if acceptance.status != "PASS":
                reasons.append(f"Acceptance status is {acceptance.status}")
            if (isinstance(verification, VerificationResult)
                    and acceptance.verification_result_sha256 != verification.sha256):
                reasons.append("Acceptance result was not evaluated from the current #29 Verification result")
            digest_refs.add(acceptance.sha256)

    if not isinstance(self_audit, SelfAudit):
        reasons.append("self-audit is missing")
    else:
        try:
            self_audit.validate(required_item_ids)
        except AuditError as exc:
            reasons.append(f"self-audit is incomplete or invalid: {exc}")
        else:
            if self_audit.subject != subject:
                reasons.append("self-audit belongs to a different exact subject")
            if self_audit.status != "PASS":
                reasons.append(f"self-audit status is {self_audit.status}")
            digest_refs.add(self_audit.sha256)

    if not isinstance(independent_review, IndependentReview):
        reasons.append("independent review artifact is missing")
    else:
        try:
            independent_review.validate()
        except AuditError as exc:
            reasons.append(f"independent review artifact is invalid: {exc}")
        else:
            if independent_review.subject != subject:
                reasons.append("independent review belongs to a different exact subject")
            if independent_review.verdict != "PASS":
                reasons.append(f"independent review verdict is {independent_review.verdict}")
            if independent_review.blocking_findings:
                reasons.append("independent review has unresolved A/B findings")
            digest_refs.add(independent_review.sha256)

    normalized_reasons = tuple(reasons)
    if any("status is FAIL" in reason or "verdict is FAIL" in reason for reason in reasons):
        status = "FAIL"
    elif any("CONCERNS" in reason for reason in reasons):
        status = "CONCERNS"
    elif reasons:
        status = "BLOCKED"
    else:
        status = "PASS"
    return ReadinessResult(status, subject, normalized_reasons, tuple(sorted(digest_refs)),
                           required_check_policy_sha256).validate()


def readiness_path(root: Path, result: ReadinessResult) -> Path:
    result.validate()
    return Path(root).absolute() / ".p_ases" / "readiness" / str(result.subject.issue_number) / result.subject.sha256 / f"{result.sha256}.json"


def read_readiness(path: Path) -> ReadinessResult:
    location = Path(path)
    if path_has_symlink(location):
        raise ReadinessError("Readiness path must not traverse a symbolic link")
    try:
        return ReadinessResult.from_bytes(location.read_bytes())
    except OSError as exc:
        raise ReadinessError("Readiness result is missing or unreadable") from exc


def write_readiness(path: Path, result: ReadinessResult) -> str:
    result.validate()
    destination = Path(path)
    if path_has_symlink(destination):
        raise ReadinessError("Readiness path must not traverse a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(destination):
        raise ReadinessError("Readiness path must not traverse a symbolic link")
    raw = result.to_bytes()
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if read_readiness(destination) != result:
                raise ReadinessError("Readiness identity exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise ReadinessError("could not atomically store Readiness result") from exc
    if read_readiness(destination) != result:
        raise ReadinessError("Readiness result readback changed")
    return result.sha256
