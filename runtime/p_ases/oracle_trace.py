"""Independent Oracle definitions and requirement-to-test trace validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .verification_plan import (
    ORACLE_ID, REQ_ID, PlanEntry, PlanError, VerificationPlan, entry_key,
    validate_plan_coverage,
)


class OracleTraceError(ValueError):
    pass


INDEPENDENT_SOURCE_KINDS = {
    "frozen_specification", "external_standard", "recorded_reproducer", "manual_procedure",
}


@dataclass(frozen=True)
class OracleDefinition:
    oracle_id: str
    source_kind: str
    source_ref: str
    source_sha256: str
    expected_behavior: str
    req_ids: tuple[str, ...]
    derived_from_implementation: bool = False

    def validate(self) -> "OracleDefinition":
        if not isinstance(self.oracle_id, str) or not ORACLE_ID.fullmatch(self.oracle_id):
            raise OracleTraceError("Oracle ID must use the stable ORACLE-* form")
        if not isinstance(self.source_kind, str) or self.source_kind not in INDEPENDENT_SOURCE_KINDS:
            raise OracleTraceError("Oracle source must be an independent specification, standard, reproducer, or procedure")
        for value, label in (
            (self.source_ref, "Oracle source reference"),
            (self.expected_behavior, "Oracle expected behavior"),
        ):
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise OracleTraceError(f"{label} must be non-empty text")
        if not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64:
            raise OracleTraceError("Oracle source SHA-256 is invalid")
        if any(char not in "0123456789abcdef" for char in self.source_sha256):
            raise OracleTraceError("Oracle source SHA-256 must be lowercase hexadecimal")
        if type(self.derived_from_implementation) is not bool or self.derived_from_implementation:
            raise OracleTraceError("Oracle expected behavior must not be derived from the implementation under test")
        if type(self.req_ids) is not tuple or not self.req_ids:
            raise OracleTraceError("Oracle must declare at least one normative REQ-ID")
        if any(not isinstance(req, str) or not REQ_ID.fullmatch(req) for req in self.req_ids):
            raise OracleTraceError("Oracle requirement references must use stable REQ-N identifiers")
        if len(set(self.req_ids)) != len(self.req_ids):
            raise OracleTraceError("Oracle requirement references must be unique")
        return self


@dataclass(frozen=True)
class OracleTrace:
    status: str
    entries: tuple[PlanEntry, ...]
    oracle_digests: tuple[tuple[str, str], ...]


def trace_requirements(
    required_req_ids: Iterable[str],
    entries: Iterable[PlanEntry],
    oracles: Mapping[str, OracleDefinition],
) -> OracleTrace:
    """Validate complete REQ coverage against independently sourced Oracles.

    ``required_req_ids`` must come from the frozen ADC and normative documents;
    this function deliberately does not infer them from the implementation.
    """
    required = tuple(required_req_ids)
    if not required or any(not isinstance(req, str) or not REQ_ID.fullmatch(req) for req in required):
        raise OracleTraceError("normative requirement set must be non-empty and valid")
    if len(set(required)) != len(required):
        raise OracleTraceError("normative requirement set contains duplicates")
    rows = tuple(sorted(entries, key=entry_key))
    if not rows:
        raise OracleTraceError("Oracle trace cannot be empty")
    if not isinstance(oracles, Mapping) or not oracles:
        raise OracleTraceError("Oracle definitions are required")
    try:
        for entry in rows:
            entry.validate()
    except PlanError as exc:
        raise OracleTraceError(str(exc)) from exc
    keys = [entry_key(row) for row in rows]
    if len(keys) != len(set(keys)):
        raise OracleTraceError("Oracle trace contains duplicate REQ/Oracle/Test/target mappings")
    for key, oracle in oracles.items():
        if not isinstance(oracle, OracleDefinition) or key != oracle.oracle_id:
            raise OracleTraceError("Oracle map keys must match OracleDefinition IDs")
        oracle.validate()
    missing_oracles = sorted({entry.oracle_id for entry in rows} - set(oracles))
    if missing_oracles:
        raise OracleTraceError("undefined Oracle IDs: " + ", ".join(missing_oracles))
    for entry in rows:
        oracle = oracles[entry.oracle_id]
        if entry.req_id not in oracle.req_ids:
            raise OracleTraceError(f"Oracle {entry.oracle_id} does not define {entry.req_id}")
    try:
        # Reuse the Plan's exact-set coverage rule without inventing a Plan digest.
        unique = set(required)
        actual = {entry.req_id for entry in rows}
        if actual != unique:
            absent, extra = sorted(unique - actual), sorted(actual - unique)
            reasons = []
            if absent:
                reasons.append("missing " + ", ".join(absent))
            if extra:
                reasons.append("unexpected " + ", ".join(extra))
            raise OracleTraceError("Oracle trace requirement coverage mismatch: " + "; ".join(reasons))
    except PlanError as exc:
        raise OracleTraceError(str(exc)) from exc
    digests = tuple(sorted((oracle.oracle_id, oracle.source_sha256) for oracle in oracles.values()))
    return OracleTrace("PASS", rows, digests)


def validate_plan_oracles(plan: VerificationPlan, required_req_ids: Iterable[str],
                          oracles: Mapping[str, OracleDefinition]) -> OracleTrace:
    try:
        validate_plan_coverage(plan, required_req_ids)
    except PlanError as exc:
        raise OracleTraceError(str(exc)) from exc
    trace = trace_requirements(required_req_ids, plan.entries, oracles)
    frozen = {(kind, digest) for kind, _name, digest in plan.source_digests}
    for oracle_id, digest in trace.oracle_digests:
        if ("oracle", digest) not in frozen:
            raise OracleTraceError(f"Oracle {oracle_id} source digest is not frozen in the Plan")
    return trace
