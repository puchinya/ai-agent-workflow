"""Pure Verification and Required Check evaluators over immutable observations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from .evidence_store import EvidenceRecord, VerificationSubject
from .verification_plan import PlanEntry, VerificationPlan, entry_ref


class VerificationError(ValueError):
    pass


VERDICTS = {"PASS", "CONCERNS", "FAIL", "BLOCKED"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GateResult:
    status: str
    reasons: tuple[str, ...]
    subject: VerificationSubject | None = None
    provenance_sha256: str | None = None

    def validate(self) -> "GateResult":
        if not isinstance(self.status, str) or self.status not in VERDICTS:
            raise VerificationError("Gate result has an unknown status")
        if type(self.reasons) is not tuple or any(not isinstance(item, str) or not item for item in self.reasons):
            raise VerificationError("Gate result reasons must be non-empty strings")
        if (self.status == "PASS" and self.reasons) or (self.status != "PASS" and not self.reasons):
            raise VerificationError("Gate result status and explanation reasons are inconsistent")
        if self.subject is not None:
            self.subject.validate()
        if self.provenance_sha256 is not None and not SHA256.fullmatch(self.provenance_sha256):
            raise VerificationError("Gate result provenance digest is invalid")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {
            "reasons": list(self.reasons),
            "provenance_sha256": self.provenance_sha256,
            "schema": "PASES_VERIFICATION_RESULT_V1",
            "status": self.status,
            "subject": None if self.subject is None else self.subject.as_dict(),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class RequiredCheckPolicy:
    checks: tuple[tuple[str, int], ...]

    def validate(self) -> "RequiredCheckPolicy":
        if type(self.checks) is not tuple or not self.checks:
            raise VerificationError("Required Check policy must be a non-empty set")
        names: list[str] = []
        for item in self.checks:
            if type(item) is not tuple or len(item) != 2:
                raise VerificationError("Required Check entries must be (name, trusted_app_id)")
            name, app_id = item
            if not isinstance(name, str) or not name.strip() or name != name.strip() or "\x00" in name:
                raise VerificationError("Required Check name must be non-empty text")
            if type(app_id) is not int or app_id < 1:
                raise VerificationError("Required Check trusted App ID must be positive")
            names.append(name)
        if len(names) != len(set(names)):
            raise VerificationError("Required Check names must be unique")
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {"checks": [{"app_id": app_id, "name": name} for name, app_id in sorted(self.checks)],
                   "schema": "PASES_REQUIRED_CHECK_POLICY_V1"}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def from_project_config(cls, value: Any) -> "RequiredCheckPolicy":
        """Load explicit trusted App IDs; check names alone are not trust policy."""
        if not isinstance(value, dict):
            raise VerificationError("project configuration must be a JSON object")
        branch = value.get("branch")
        checks = branch.get("required_checks") if isinstance(branch, dict) else None
        if not isinstance(checks, list) or not checks:
            raise VerificationError("project configuration has no required Checks")
        parsed: list[tuple[str, int]] = []
        for index, item in enumerate(checks):
            if not isinstance(item, dict) or set(item) != {"name", "trusted_app_id"}:
                raise VerificationError(
                    f"required Check {index + 1} must configure exactly name and trusted_app_id"
                )
            parsed.append((item["name"], item["trusted_app_id"]))
        return cls(tuple(parsed)).validate()


def _app_id(run: Any) -> int | None:
    if not isinstance(run, dict):
        return None
    app = run.get("app")
    value = app.get("id") if isinstance(app, dict) else None
    return value if type(value) is int and value > 0 else None


def _repository_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    full_name = value.get("full_name")
    if isinstance(full_name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        return full_name.lower()
    url = value.get("url")
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if (parsed.scheme != "https" or parsed.hostname not in {"api.github.com", "github.com"}
            or len(parts) != 3 or parts[0] != "repos"
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1])
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[2])):
        return None
    return f"{parts[1]}/{parts[2]}".lower()


def _check_run_pr_fork(run: dict[str, Any], subject: VerificationSubject,
                       expected_repository: str) -> tuple[bool | None, str | None]:
    if not isinstance(expected_repository, str) or not expected_repository:
        return None, "expected repository is unavailable"
    pull_requests = run.get("pull_requests")
    if not isinstance(pull_requests, list):
        return None, "Check Run response has no PR association metadata"
    matches = [row for row in pull_requests if isinstance(row, dict) and row.get("number") == subject.pr_number]
    if len(matches) != 1:
        return None, "Check Run is not uniquely associated with the expected PR"
    pr = matches[0]
    base, head = pr.get("base"), pr.get("head")
    base_repo = _repository_name(base.get("repo") if isinstance(base, dict) else None)
    head_repo = _repository_name(head.get("repo") if isinstance(head, dict) else None)
    if base_repo is None or head_repo is None:
        return None, "Check Run PR association has unknown source repository provenance"
    if base_repo != expected_repository.lower():
        return None, "Check Run PR base repository does not match the expected repository"
    if not isinstance(head, dict) or head.get("sha") != subject.pr_head_sha40:
        return None, "Check Run PR association has a stale or different HEAD"
    return head_repo != expected_repository.lower(), None


def required_check_fork_status(
    policy: RequiredCheckPolicy,
    check_runs: Iterable[dict[str, Any]],
    *,
    subject: VerificationSubject,
    expected_repository: str,
) -> bool | None:
    """Derive fork status from the Check Run's GitHub PR association readback."""
    try:
        policy.validate()
        rows = tuple(check_runs)
        if any(not isinstance(row, dict) for row in rows):
            return None
        statuses: list[bool] = []
        for name, _app_id_value in policy.checks:
            named = [row for row in rows
                     if row.get("name") == name and row.get("head_sha") == subject.pr_head_sha40]
            if not named:
                return None
            latest = max(named, key=lambda row: row.get("id", 0))
            forked, error = _check_run_pr_fork(latest, subject, expected_repository)
            if error or forked is None:
                return None
            statuses.append(forked)
        if not statuses or len(set(statuses)) != 1:
            return None
        return statuses[0]
    except (VerificationError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class VerificationResult:
    """Versioned final result bound to Plan, exact subject, and Check policy."""

    status: str
    subject: VerificationSubject
    source_digests: tuple[tuple[str, str, str], ...]
    required_check_policy_sha256: str | None
    check_result_sha256: str | None
    evidence_sha256s: tuple[str, ...]
    reasons: tuple[str, ...]

    def validate(self) -> "VerificationResult":
        if not isinstance(self.status, str) or self.status not in VERDICTS:
            raise VerificationError("Verification result status is invalid")
        self.subject.validate()
        if type(self.source_digests) is not tuple:
            raise VerificationError("Verification result source digests must be a tuple")
        if any(type(item) is not tuple or len(item) != 3 for item in self.source_digests):
            raise VerificationError("Verification result source digest entry is invalid")
        if self.source_digests != tuple(sorted(set(self.source_digests))):
            raise VerificationError("Verification result source digests must be sorted and unique")
        for kind, name, digest in self.source_digests:
            if not isinstance(kind, str) or not kind or not isinstance(name, str) or not name:
                raise VerificationError("Verification result source kind and name must be non-empty")
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise VerificationError("Verification result source digest is invalid")
        if self.required_check_policy_sha256 is not None and not SHA256.fullmatch(self.required_check_policy_sha256):
            raise VerificationError("Verification result Required Check policy digest is invalid")
        if self.check_result_sha256 is not None and not SHA256.fullmatch(self.check_result_sha256):
            raise VerificationError("Verification result Check digest is invalid")
        if (type(self.evidence_sha256s) is not tuple
                or any(not isinstance(item, str) or not SHA256.fullmatch(item) for item in self.evidence_sha256s)
                or self.evidence_sha256s != tuple(sorted(set(self.evidence_sha256s)))):
            raise VerificationError("Verification result Evidence digests must be sorted unique SHA-256 values")
        if type(self.reasons) is not tuple or any(not isinstance(item, str) or not item for item in self.reasons):
            raise VerificationError("Verification result reasons are invalid")
        if (self.status == "PASS" and self.reasons) or (self.status != "PASS" and not self.reasons):
            raise VerificationError("Verification result status and reasons are inconsistent")
        if self.status == "PASS" and (
            self.required_check_policy_sha256 is None or self.check_result_sha256 is None
            or not self.evidence_sha256s
        ):
            raise VerificationError("Verification PASS requires Check policy, Check result, and Evidence digests")
        if self.subject.plan_sha256 == "0" * 64:
            raise VerificationError("Verification result cannot use a placeholder Plan digest")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "check_result_sha256": self.check_result_sha256,
            "evidence_sha256s": list(self.evidence_sha256s),
            "reasons": list(self.reasons),
            "required_check_policy_sha256": self.required_check_policy_sha256,
            "schema": "PASES_VERIFICATION_RESULT_V1",
            "source_digests": [
                {"kind": kind, "name": name, "sha256": digest}
                for kind, name, digest in self.source_digests
            ],
            "status": self.status,
            "subject": self.subject.as_dict(),
        }

    @property
    def sha256(self) -> str:
        canonical = json.dumps(self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def to_bytes(self) -> bytes:
        value = self.payload()
        value["result_sha256"] = self.sha256
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"

    @classmethod
    def from_bytes(cls, raw: bytes) -> "VerificationResult":
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VerificationError("Verification result is not valid UTF-8 JSON") from exc
        expected = {
            "check_result_sha256", "evidence_sha256s", "reasons", "required_check_policy_sha256",
            "result_sha256", "schema", "source_digests", "status", "subject",
        }
        if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_VERIFICATION_RESULT_V1":
            raise VerificationError("Verification result has unknown/missing fields or schema")
        if not isinstance(value["source_digests"], list) or not isinstance(value["evidence_sha256s"], list) or not isinstance(value["reasons"], list):
            raise VerificationError("Verification result arrays have an invalid shape")
        sources = []
        for item in value["source_digests"]:
            if not isinstance(item, dict) or set(item) != {"kind", "name", "sha256"}:
                raise VerificationError("Verification result source digest has unknown/missing fields")
            sources.append((item["kind"], item["name"], item["sha256"]))
        result = cls(
            status=value["status"], subject=VerificationSubject.from_dict(value["subject"]),
            source_digests=tuple(sources), required_check_policy_sha256=value["required_check_policy_sha256"],
            check_result_sha256=value["check_result_sha256"], evidence_sha256s=tuple(value["evidence_sha256s"]),
            reasons=tuple(value["reasons"]),
        ).validate()
        if value["result_sha256"] != result.sha256 or result.to_bytes() != raw:
            raise VerificationError("Verification result digest or canonical bytes do not match")
        return result

    def as_json(self) -> dict[str, Any]:
        value = self.payload()
        value["result_sha256"] = self.sha256
        value["subject_sha256"] = self.subject.sha256
        return value


def build_verification_result(
    plan: VerificationPlan,
    subject: VerificationSubject,
    records: Iterable[EvidenceRecord],
    check_result: GateResult,
    policy: RequiredCheckPolicy | None,
) -> VerificationResult:
    """Freeze the complete final gate, including the exact Check policy digest."""
    plan.validate()
    subject.validate()
    rows = tuple(records)
    if not isinstance(check_result, GateResult):
        check_result = GateResult("BLOCKED", ("Required Check result is missing or malformed",), subject).validate()
    check = verify_final(plan, subject, rows, check_result)
    policy_sha = None
    if policy is not None:
        try:
            policy_sha = policy.validate().sha256
        except VerificationError as exc:
            check = GateResult("BLOCKED", tuple(dict.fromkeys(check.reasons + (str(exc),))), subject).validate()
    result = VerificationResult(
        status=check.status, subject=subject, source_digests=tuple(sorted(plan.source_digests)),
        required_check_policy_sha256=policy_sha,
        check_result_sha256=check_result.sha256 if isinstance(check_result, GateResult) else None,
        evidence_sha256s=tuple(sorted({record.evidence_sha256 for record in rows
                                      if isinstance(record, EvidenceRecord)})),
        reasons=check.reasons,
    ).validate()
    return result


def verification_result_path(root: Path, result: VerificationResult) -> Path:
    result.validate()
    return Path(root) / str(result.subject.issue_number) / result.subject.sha256 / f"{result.sha256}.json"


def read_verification_result(path: Path) -> VerificationResult:
    location = Path(path)
    absolute = Path(os.path.abspath(location))
    if any(candidate.is_symlink() for candidate in (absolute, *absolute.parents)):
        raise VerificationError("Verification result path must not traverse a symbolic link")
    try:
        raw = location.read_bytes()
    except OSError as exc:
        raise VerificationError("Verification result is missing or unreadable") from exc
    return VerificationResult.from_bytes(raw)


def write_verification_result(path: Path, result: VerificationResult) -> str:
    """Create-only, atomic final-result persistence with digest readback."""
    result.validate()
    destination = Path(path)
    absolute = Path(os.path.abspath(destination))
    if any(candidate.is_symlink() for candidate in (absolute, *absolute.parents)):
        raise VerificationError("Verification result path must not traverse a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if any(candidate.is_symlink() for candidate in (absolute, *absolute.parents)):
        raise VerificationError("Verification result path must not traverse a symbolic link")
    parent = destination.parent
    while parent != parent.parent:
        if parent.is_symlink():
            raise VerificationError("Verification result directory path must not contain a symbolic link")
        parent = parent.parent
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
            if destination.is_symlink() or destination.read_bytes() != raw:
                raise VerificationError("Verification result identity exists with different bytes")
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise VerificationError("Could not atomically store Verification result") from exc
    if read_verification_result(destination) != result:
        raise VerificationError("Verification result readback changed")
    return result.sha256


def evaluate_required_checks(
    policy: RequiredCheckPolicy,
    check_runs: Iterable[dict[str, Any]],
    *,
    subject: VerificationSubject,
    expected_repository: str,
    response_repository: str,
    head_sha40: str,
    is_fork: bool,
) -> GateResult:
    """Select each configured job's newest matching Check Run, including failed reruns."""
    reasons: list[str] = []
    if not isinstance(subject, VerificationSubject):
        return GateResult("BLOCKED", ("exact Verification subject is required for Check evaluation",)).validate()
    try:
        subject.validate()
    except ValueError as exc:
        return GateResult("BLOCKED", (f"invalid Verification subject: {exc}",)).validate()
    try:
        policy.validate()
    except VerificationError as exc:
        return GateResult("BLOCKED", (str(exc),), subject).validate()
    if not isinstance(expected_repository, str) or not expected_repository:
        reasons.append("expected repository is unavailable")
    if response_repository != expected_repository:
        reasons.append("Check Run response repository does not match the expected repository")
    if subject.repository != expected_repository:
        reasons.append("Check policy repository differs from the exact Verification subject")
    if (not isinstance(head_sha40, str) or len(head_sha40) != 40
            or any(char not in "0123456789abcdef" for char in head_sha40)):
        reasons.append("current PR HEAD is not a full lowercase SHA-40")
    elif head_sha40 != subject.pr_head_sha40:
        reasons.append("Check Run HEAD differs from the exact Verification subject")
    if type(is_fork) is not bool:
        reasons.append("PR fork provenance is unavailable")
    elif is_fork:
        reasons.append("forked PR Check Runs are not trusted by the configured policy")
    try:
        runs = tuple(check_runs)
    except (TypeError, ValueError):
        return GateResult("BLOCKED", ("Check Run response is not an iterable collection",), subject).validate()
    if any(not isinstance(run, dict) for run in runs):
        reasons.append("Check Run response contains a malformed record")
    try:
        check_response_sha256 = hashlib.sha256(json.dumps(
            {
                "check_runs": list(runs),
                "expected_repository": expected_repository,
                "head_sha40": head_sha40,
                "policy_sha256": policy.sha256,
                "response_repository": response_repository,
                "schema": "PASES_CHECK_RUN_RESPONSE_V1",
                "subject": subject.as_dict(),
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        check_response_sha256 = None
        reasons.append("Check Run response cannot be canonically bound")
    ids = [run.get("id") for run in runs if isinstance(run, dict)]
    valid_ids = [value for value in ids if type(value) is int and value > 0]
    if len(valid_ids) != len(ids):
        reasons.append("Check Run response contains a missing or invalid run ID")
    if len(valid_ids) != len(set(valid_ids)):
        reasons.append("Check Run response contains duplicate run IDs")
    for run in runs:
        if not isinstance(run, dict):
            continue
        if not isinstance(run.get("name"), str) or not run["name"]:
            reasons.append("Check Run response contains a missing name")
        if run.get("head_sha") != head_sha40:
            reasons.append("Check Run response contains a different or missing HEAD SHA")
        if _app_id(run) is None:
            reasons.append("Check Run response contains missing or invalid GitHub App provenance")
        if run.get("status") not in {"queued", "in_progress", "completed"}:
            reasons.append("Check Run response contains an unknown status")
        if run.get("status") == "completed" and run.get("conclusion") not in {
            "success", "failure", "neutral", "cancelled", "skipped", "timed_out",
            "action_required", "stale", "startup_failure", "" , None,
        }:
            reasons.append("Check Run response contains an unknown conclusion")
    if reasons:
        return GateResult("BLOCKED", tuple(reasons), subject, check_response_sha256).validate()

    observed_fork: bool | None = None
    for name, trusted_app_id in policy.checks:
        named_current = [
            run for run in runs
            if run.get("name") == name and run.get("head_sha") == head_sha40
        ]
        if not named_current:
            reasons.append(f"required Check Run is missing for the current HEAD: {name}")
            continue
        # Select the newest same-name/current-HEAD run before trusting its App.
        # A later forged or rerun Check must not leave an older success eligible.
        latest = max(named_current, key=lambda run: run["id"])
        if _app_id(latest) != trusted_app_id:
            reasons.append(f"latest required Check Run has untrusted App provenance: {name}")
        forked, provenance_error = _check_run_pr_fork(latest, subject, expected_repository)
        if provenance_error:
            reasons.append(f"required Check Run provenance is incomplete for {name}: {provenance_error}")
        elif forked is not None:
            if observed_fork is not None and observed_fork != forked:
                reasons.append("required Check Runs disagree about fork provenance")
            observed_fork = forked
            if type(is_fork) is not bool or is_fork != forked:
                reasons.append("caller fork provenance does not match GitHub Check Run PR readback")
            if forked:
                reasons.append(f"required Check Run originates from an untrusted fork: {name}")
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            reasons.append(
                f"latest required Check Run is not completed/success: {name} "
                f"(status={latest.get('status')!r}, conclusion={latest.get('conclusion')!r})"
            )
    return GateResult("PASS" if not reasons else "BLOCKED", tuple(reasons), subject,
                      check_response_sha256).validate()


def evaluate_evidence(
    plan: VerificationPlan,
    subject: VerificationSubject,
    records: Iterable[EvidenceRecord],
) -> GateResult:
    """Require a current, passing record for every Plan entry's evidence type."""
    if not isinstance(plan, VerificationPlan) or not isinstance(subject, VerificationSubject):
        return GateResult("BLOCKED", ("Verification Plan or exact subject is missing",)).validate()
    try:
        plan.validate()
        subject.validate()
    except (ValueError, TypeError) as exc:
        return GateResult("BLOCKED", (f"invalid verification input: {exc}",), subject if isinstance(subject, VerificationSubject) else None).validate()
    if (subject.repository != plan.repository or subject.issue_number != plan.issue_number
            or subject.adc_comment_id != plan.adc_comment_id or subject.adc_sha256 != plan.adc_sha256
            or subject.plan_sha256 != plan.sha256):
        return GateResult("BLOCKED", ("Verification subject does not match the frozen Plan and ADC",), subject).validate()
    rows = tuple(records)
    if any(not isinstance(record, EvidenceRecord) for record in rows):
        return GateResult("BLOCKED", ("Evidence collection contains a malformed record",), subject).validate()
    reasons: list[str] = []
    planned: dict[str, PlanEntry] = {entry_ref(entry): entry for entry in plan.entries}
    observed: dict[tuple[str, str], list[EvidenceRecord]] = {}
    for record in rows:
        try:
            record.validate()
        except (ValueError, TypeError, AttributeError) as exc:
            reasons.append(f"invalid Evidence record: {exc}")
            continue
        if record.subject != subject:
            reasons.append("Evidence is stale or belongs to a different exact subject")
            continue
        if record.entry_key not in planned:
            reasons.append("Evidence references an entry outside the frozen Plan")
            continue
        entry = planned[record.entry_key]
        if record.environment != entry.environment or record.command != entry.command or record.manual_procedure != entry.manual_procedure:
            reasons.append(f"Evidence command/environment differs from Plan entry {record.entry_key}")
            continue
        observed.setdefault((record.entry_key, record.evidence_type), []).append(record)
    if reasons:
        return GateResult("BLOCKED", tuple(reasons), subject).validate()
    concerns: list[str] = []
    failures: list[str] = []
    for ref, entry in planned.items():
        for evidence_type in entry.evidence_required:
            matching = observed.get((ref, evidence_type), [])
            if not matching:
                reasons.append(f"required Evidence is missing: {ref} / {evidence_type}")
                continue
            # Preserve history but select the newest observation for this exact identity.
            latest_time = max(datetime.fromisoformat(record.observed_at.replace("Z", "+00:00")) for record in matching)
            latest_rows = [record for record in matching
                           if datetime.fromisoformat(record.observed_at.replace("Z", "+00:00")) == latest_time]
            if len({record.evidence_sha256 for record in latest_rows}) > 1:
                reasons.append(f"Evidence has conflicting observations at one timestamp: {ref} / {evidence_type}")
                continue
            latest = latest_rows[0]
            if latest.outcome == "FAIL":
                failures.append(f"mandatory Evidence failed: {ref} / {evidence_type}")
            elif latest.outcome == "FLAKY":
                concerns.append(f"mandatory Evidence is flaky: {ref} / {evidence_type}")
            elif latest.outcome != "PASS":
                reasons.append(f"mandatory Evidence is {latest.outcome}: {ref} / {evidence_type}")
    if failures:
        return GateResult("FAIL", tuple(failures + reasons + concerns), subject).validate()
    if reasons:
        return GateResult("BLOCKED", tuple(reasons + concerns), subject).validate()
    if concerns:
        return GateResult("CONCERNS", tuple(concerns), subject).validate()
    return GateResult("PASS", (), subject).validate()


def verify_final(
    plan: VerificationPlan,
    subject: VerificationSubject,
    records: Iterable[EvidenceRecord],
    check_result: GateResult,
) -> GateResult:
    evidence_result = evaluate_evidence(plan, subject, records)
    if not isinstance(check_result, GateResult):
        return GateResult("BLOCKED", ("Required Check result is missing or malformed",), subject).validate()
    check_result.validate()
    if check_result.subject != subject:
        return GateResult("BLOCKED", ("Required Check result belongs to a different exact subject",), subject).validate()
    combined = [evidence_result, check_result]
    reasons = tuple(reason for result in combined for reason in result.reasons)
    if any(result.status == "FAIL" for result in combined):
        return GateResult("FAIL", reasons, subject).validate()
    if any(result.status == "BLOCKED" for result in combined):
        return GateResult("BLOCKED", reasons or ("Required Verification evidence is incomplete",), subject).validate()
    if any(result.status == "CONCERNS" for result in combined):
        return GateResult("CONCERNS", reasons, subject).validate()
    return GateResult("PASS", (), subject).validate()
