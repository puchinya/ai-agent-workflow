"""Pure Verification and Required Check evaluators over immutable observations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from .evidence_store import EvidenceRecord, VerificationSubject
from .verification_plan import PlanEntry, VerificationPlan, entry_ref


class VerificationError(ValueError):
    pass


VERDICTS = {"PASS", "CONCERNS", "FAIL", "BLOCKED"}


@dataclass(frozen=True)
class GateResult:
    status: str
    reasons: tuple[str, ...]
    subject: VerificationSubject | None = None

    def validate(self) -> "GateResult":
        if not isinstance(self.status, str) or self.status not in VERDICTS:
            raise VerificationError("Gate result has an unknown status")
        if type(self.reasons) is not tuple or any(not isinstance(item, str) or not item for item in self.reasons):
            raise VerificationError("Gate result reasons must be non-empty strings")
        if (self.status == "PASS" and self.reasons) or (self.status != "PASS" and not self.reasons):
            raise VerificationError("Gate result status and explanation reasons are inconsistent")
        if self.subject is not None:
            self.subject.validate()
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        payload = {
            "reasons": list(self.reasons),
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


def _app_id(run: Any) -> int | None:
    if not isinstance(run, dict):
        return None
    app = run.get("app")
    value = app.get("id") if isinstance(app, dict) else None
    return value if type(value) is int and value > 0 else None


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
    runs = tuple(check_runs)
    if any(not isinstance(run, dict) for run in runs):
        reasons.append("Check Run response contains a malformed record")
    ids = [run.get("id") for run in runs if isinstance(run, dict)]
    valid_ids = [value for value in ids if type(value) is int and value > 0]
    if len(valid_ids) != len(ids):
        reasons.append("Check Run response contains a missing or invalid run ID")
    if len(valid_ids) != len(set(valid_ids)):
        reasons.append("Check Run response contains duplicate run IDs")
    if reasons:
        return GateResult("BLOCKED", tuple(reasons), subject).validate()

    for name, trusted_app_id in policy.checks:
        named_current = [
            run for run in runs
            if run.get("name") == name and run.get("head_sha") == head_sha40
        ]
        selected = [run for run in named_current if _app_id(run) == trusted_app_id]
        if not selected:
            reasons.append(f"required Check Run is missing or has untrusted App provenance: {name}")
            continue
        latest = max(selected, key=lambda run: run["id"])
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            reasons.append(
                f"latest required Check Run is not completed/success: {name} "
                f"(status={latest.get('status')!r}, conclusion={latest.get('conclusion')!r})"
            )
    return GateResult("PASS" if not reasons else "BLOCKED", tuple(reasons), subject).validate()


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
