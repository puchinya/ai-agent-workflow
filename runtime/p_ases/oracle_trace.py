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
class TestDefinition:
    """A named test case sourced from a frozen test specification."""

    test_id: str
    req_id: str
    target: str
    source_ref: str
    source_sha256: str
    derived_from_implementation: bool = False

    def validate(self) -> "TestDefinition":
        from .verification_plan import TEST_ID

        if not isinstance(self.test_id, str) or not TEST_ID.fullmatch(self.test_id):
            raise OracleTraceError("Test ID must use the stable TEST-* form")
        if not isinstance(self.req_id, str) or not REQ_ID.fullmatch(self.req_id):
            raise OracleTraceError("Test requirement must use a stable REQ-N identifier")
        for value, label in ((self.target, "Test target"), (self.source_ref, "Test source reference")):
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise OracleTraceError(f"{label} must be non-empty text")
        if (not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64
                or any(char not in "0123456789abcdef" for char in self.source_sha256)):
            raise OracleTraceError("Test source SHA-256 is invalid")
        if type(self.derived_from_implementation) is not bool or self.derived_from_implementation:
            raise OracleTraceError("Test expectations must not be derived from the implementation under test")
        return self

    def as_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "derived_from_implementation": self.derived_from_implementation,
            "req_id": self.req_id,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "target": self.target,
            "test_id": self.test_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "TestDefinition":
        expected = {"derived_from_implementation", "req_id", "source_ref", "source_sha256", "target", "test_id"}
        if not isinstance(value, dict) or set(value) != expected:
            raise OracleTraceError("Test definition has unknown or missing fields")
        return cls(**value).validate()


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

    def as_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "derived_from_implementation": self.derived_from_implementation,
            "expected_behavior": self.expected_behavior,
            "oracle_id": self.oracle_id,
            "req_ids": list(self.req_ids),
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "OracleDefinition":
        expected = {
            "derived_from_implementation", "expected_behavior", "oracle_id", "req_ids",
            "source_kind", "source_ref", "source_sha256",
        }
        if not isinstance(value, dict) or set(value) != expected or not isinstance(value.get("req_ids"), list):
            raise OracleTraceError("Oracle definition has unknown or missing fields")
        return cls(
            oracle_id=value["oracle_id"], source_kind=value["source_kind"],
            source_ref=value["source_ref"], source_sha256=value["source_sha256"],
            expected_behavior=value["expected_behavior"], req_ids=tuple(value["req_ids"]),
            derived_from_implementation=value["derived_from_implementation"],
        ).validate()


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
    frozen = set(plan.source_digests)
    for oracle_id, digest in trace.oracle_digests:
        oracle = oracles[oracle_id]
        if ("oracle", oracle.source_ref, digest) not in frozen:
            raise OracleTraceError(f"Oracle {oracle_id} source digest is not frozen in the Plan")
    return trace


def validate_plan_tests(
    plan: VerificationPlan,
    tests: Iterable[TestDefinition],
    source_digests: Iterable[tuple[str, str, str]] | None = None,
) -> tuple[TestDefinition, ...]:
    """Require every Plan test mapping to exist in the frozen test specification."""
    plan.validate()
    rows = tuple(tests)
    if not rows:
        raise OracleTraceError("frozen Test definitions are required")
    for row in rows:
        if not isinstance(row, TestDefinition):
            raise OracleTraceError("Test mapping has an invalid type")
        row.validate()
    keys = [(row.req_id, row.test_id, row.target) for row in rows]
    if len(keys) != len(set(keys)):
        raise OracleTraceError("Test definitions contain duplicate REQ/Test/target mappings")
    plan_keys = {(entry.req_id, entry.test_id, entry.target) for entry in plan.entries}
    test_keys = set(keys)
    if plan_keys != test_keys:
        missing, extra = sorted(plan_keys - test_keys), sorted(test_keys - plan_keys)
        details = []
        if missing:
            details.append("missing tests " + ", ".join("/".join(item) for item in missing))
        if extra:
            details.append("unexpected tests " + ", ".join("/".join(item) for item in extra))
        raise OracleTraceError("Plan/Test specification mapping mismatch: " + "; ".join(details))
    frozen = set(source_digests if source_digests is not None else plan.source_digests)
    for row in rows:
        if ("test_specification", row.source_ref, row.source_sha256) not in frozen:
            raise OracleTraceError(f"Test {row.test_id} source is not frozen in the Plan")
    return tuple(sorted(rows, key=lambda row: (row.req_id, row.test_id, row.target)))
