"""Immutable, deterministic Verification Plan schemas for P-ASES.

This module defines the input contract only. It does not infer requirements or
expected results from the implementation being verified.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable


class PlanError(ValueError):
    pass


SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
REQ_ID = re.compile(r"^REQ-[0-9]+$")
ORACLE_ID = re.compile(r"^ORACLE-[A-Za-z0-9][A-Za-z0-9._-]*$")
TEST_ID = re.compile(r"^TEST-[A-Za-z0-9][A-Za-z0-9._-]*$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REQUIRED_SOURCE_KINDS = {"specification", "test_specification", "oracle"}


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PlanError(f"{label} must be non-empty text")
    return value.strip()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise PlanError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


DEFAULT_TRACE_SHA256 = hashlib.sha256(_canonical_bytes({
    "oracles": [], "schema": "PASES_VERIFICATION_TRACE_V1", "tests": [],
})).hexdigest()


def _absolute_executable(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


@dataclass(frozen=True)
class PlanEntry:
    req_id: str
    oracle_id: str
    test_id: str
    target: str
    environment: str
    command: tuple[str, ...] = ()
    manual_procedure: str = ""
    risk: str = ""
    acceptance: str = ""
    evidence_required: tuple[str, ...] = ()

    def validate(self) -> "PlanEntry":
        if not isinstance(self.req_id, str) or not REQ_ID.fullmatch(self.req_id):
            raise PlanError("Plan entry req_id must be a stable REQ-N identifier")
        if not isinstance(self.oracle_id, str) or not ORACLE_ID.fullmatch(self.oracle_id):
            raise PlanError("Plan entry oracle_id must be a stable ORACLE-* identifier")
        if not isinstance(self.test_id, str) or not TEST_ID.fullmatch(self.test_id):
            raise PlanError("Plan entry test_id must be a stable TEST-* identifier")
        for name in ("target", "environment", "risk", "acceptance"):
            _text(getattr(self, name), f"Plan entry {name}")
        if type(self.command) is not tuple or any(not isinstance(part, str) or not part for part in self.command):
            raise PlanError("Plan command must be a tuple of non-empty argv values")
        if bool(self.command) == bool(self.manual_procedure.strip() if isinstance(self.manual_procedure, str) else False):
            raise PlanError("Plan entry must define exactly one command or named manual procedure")
        if self.command and not _absolute_executable(self.command[0]):
            raise PlanError("Plan executable must be an absolute path")
        if self.manual_procedure:
            _text(self.manual_procedure, "Plan manual procedure")
        if type(self.evidence_required) is not tuple or not self.evidence_required:
            raise PlanError("Plan entry must require at least one evidence item")
        normalized = tuple(_text(item, "Plan evidence requirement") for item in self.evidence_required)
        if len(set(normalized)) != len(normalized):
            raise PlanError("Plan evidence requirements must be unique")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "acceptance": self.acceptance.strip(),
            "command": list(self.command),
            "environment": self.environment.strip(),
            "evidence_required": list(self.evidence_required),
            "manual_procedure": self.manual_procedure.strip(),
            "oracle_id": self.oracle_id,
            "req_id": self.req_id,
            "risk": self.risk.strip(),
            "target": self.target.strip(),
            "test_id": self.test_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "PlanEntry":
        expected = {
            "acceptance", "command", "environment", "evidence_required", "manual_procedure",
            "oracle_id", "req_id", "risk", "target", "test_id",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise PlanError("Plan entry has unknown or missing fields")
        if not isinstance(value["command"], list) or not isinstance(value["evidence_required"], list):
            raise PlanError("Plan command and evidence_required must be arrays")
        entry = cls(
            req_id=value["req_id"], oracle_id=value["oracle_id"], test_id=value["test_id"],
            target=value["target"], environment=value["environment"], command=tuple(value["command"]),
            manual_procedure=value["manual_procedure"], risk=value["risk"],
            acceptance=value["acceptance"], evidence_required=tuple(value["evidence_required"]),
        )
        return entry.validate()


@dataclass(frozen=True)
class VerificationPlan:
    repository: str
    issue_number: int
    adc_comment_id: int
    adc_sha256: str
    source_digests: tuple[tuple[str, str, str], ...]
    entries: tuple[PlanEntry, ...]
    oracle_test_trace_sha256: str = DEFAULT_TRACE_SHA256

    def validate(self) -> "VerificationPlan":
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository):
            raise PlanError("Plan repository must be owner/name")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise PlanError("Plan Issue number must be positive")
        if type(self.adc_comment_id) is not int or self.adc_comment_id < 1:
            raise PlanError("Plan ADC Comment ID must be positive")
        _sha(self.adc_sha256, "Plan ADC SHA-256")
        _sha(self.oracle_test_trace_sha256, "Plan Oracle/Test trace SHA-256")
        if type(self.source_digests) is not tuple or not self.source_digests:
            raise PlanError("Plan must freeze source document digests")
        names: list[str] = []
        kinds: set[str] = set()
        for item in self.source_digests:
            if type(item) is not tuple or len(item) != 3:
                raise PlanError("Plan source digest entries must be (kind, name, sha256) tuples")
            kind, name, digest = item
            if not isinstance(kind, str):
                raise PlanError("Plan source kind must be text")
            if kind not in REQUIRED_SOURCE_KINDS:
                raise PlanError(f"unsupported Plan source kind: {kind}")
            _text(name, "Plan source name")
            _sha(digest, f"Plan source digest for {name}")
            names.append(name)
            kinds.add(kind)
        if len(set(names)) != len(names):
            raise PlanError("Plan source names must be unique")
        if kinds != REQUIRED_SOURCE_KINDS:
            missing = sorted(REQUIRED_SOURCE_KINDS - kinds)
            raise PlanError("Plan is missing frozen source kinds: " + ", ".join(missing))
        if type(self.entries) is not tuple or not self.entries:
            raise PlanError("Verification Plan must not be empty")
        for entry in self.entries:
            if not isinstance(entry, PlanEntry):
                raise PlanError("Verification Plan entries must be PlanEntry values")
            entry.validate()
        keys = [entry_key(entry) for entry in self.entries]
        if len(set(keys)) != len(keys):
            raise PlanError("Verification Plan contains duplicate requirement/oracle/test/target mappings")
        if tuple(sorted(self.entries, key=entry_key)) != self.entries:
            raise PlanError("Verification Plan entries must be in canonical order")
        return self

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "adc_comment_id": self.adc_comment_id,
            "adc_sha256": self.adc_sha256,
            "entries": [entry.as_dict() for entry in self.entries],
            "issue_number": self.issue_number,
            "oracle_test_trace_sha256": self.oracle_test_trace_sha256,
            "repository": self.repository,
            "schema": "PASES_VERIFICATION_PLAN_V1",
            "source_digests": [
                {"kind": kind, "name": name, "sha256": digest}
                for kind, name, digest in sorted(self.source_digests)
            ],
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_bytes(self.payload())).hexdigest()

    def to_bytes(self) -> bytes:
        payload = self.payload()
        payload["plan_sha256"] = self.sha256
        return _canonical_bytes(payload) + b"\n"


def entry_key(entry: PlanEntry) -> tuple[str, str, str, str]:
    return (entry.req_id, entry.oracle_id, entry.test_id, entry.target)


def entry_ref(entry: PlanEntry) -> str:
    """Stable printable key used by immutable Evidence records."""
    return "|".join(entry_key(entry))


def create_plan(
    *, repository: str, issue_number: int, adc_comment_id: int, adc_sha256: str,
    source_digests: Iterable[tuple[str, str, str]], entries: Iterable[PlanEntry],
    required_req_ids: Iterable[str], oracle_test_trace_sha256: str = DEFAULT_TRACE_SHA256,
) -> VerificationPlan:
    rows = tuple(sorted(entries, key=entry_key))
    sources = tuple(sorted(source_digests))
    plan = VerificationPlan(repository, issue_number, adc_comment_id, adc_sha256, sources, rows,
                            oracle_test_trace_sha256).validate()
    validate_plan_coverage(plan, required_req_ids)
    return plan


def validate_plan_coverage(plan: VerificationPlan, required_req_ids: Iterable[str]) -> None:
    plan.validate()
    required = tuple(required_req_ids)
    if not required or any(not isinstance(item, str) or not REQ_ID.fullmatch(item) for item in required):
        raise PlanError("normative REQ-ID set must be non-empty and valid")
    if len(set(required)) != len(required):
        raise PlanError("normative REQ-ID set contains duplicates")
    expected, actual = set(required), {entry.req_id for entry in plan.entries}
    missing, unexpected = sorted(expected - actual), sorted(actual - expected)
    if missing or unexpected:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if unexpected:
            parts.append("unexpected: " + ", ".join(unexpected))
        raise PlanError("Plan requirement coverage mismatch (" + "; ".join(parts) + ")")


def read_plan(data: bytes) -> VerificationPlan:
    if not isinstance(data, bytes) or not data:
        raise PlanError("Plan file must be non-empty bytes")
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError("Plan file is not valid UTF-8 JSON") from exc
    expected = {
        "adc_comment_id", "adc_sha256", "entries", "issue_number", "oracle_test_trace_sha256",
        "plan_sha256", "repository",
        "schema", "source_digests",
    }
    if not isinstance(value, dict) or set(value) != expected or value.get("schema") != "PASES_VERIFICATION_PLAN_V1":
        raise PlanError("Plan file has unknown/missing fields or schema")
    if not isinstance(value["entries"], list) or not isinstance(value["source_digests"], list):
        raise PlanError("Plan entries and source_digests must be arrays")
    entries = tuple(PlanEntry.from_dict(item) for item in value["entries"])
    sources = []
    for item in value["source_digests"]:
        if not isinstance(item, dict) or set(item) != {"kind", "name", "sha256"}:
            raise PlanError("Plan source digest has unknown or missing fields")
        sources.append((item["kind"], item["name"], item["sha256"]))
    plan = VerificationPlan(
        repository=value["repository"], issue_number=value["issue_number"],
        adc_comment_id=value["adc_comment_id"], adc_sha256=value["adc_sha256"],
        source_digests=tuple(sources), entries=entries,
        oracle_test_trace_sha256=value["oracle_test_trace_sha256"],
    ).validate()
    if value["plan_sha256"] != plan.sha256:
        raise PlanError("Plan digest does not match its canonical content")
    if plan.to_bytes() != data:
        raise PlanError("Plan file is not in canonical byte form")
    return plan


def verify_plan_sources(repository_root: Path, plan: VerificationPlan) -> tuple[tuple[str, str, str], ...]:
    """Re-read every frozen source without following symlinks or leaving the checkout."""
    plan.validate()
    root = Path(repository_root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise PlanError("repository root must be an absolute, non-symlink directory")
    actual: list[tuple[str, str, str]] = []
    for kind, name, expected_sha in plan.source_digests:
        relative = PureWindowsPath(name)
        posix = Path(name)
        if (relative.is_absolute() or posix.is_absolute() or "\\" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))):
            raise PlanError(f"Plan source path is not a canonical repository-relative path: {name}")
        path = root
        for part in name.split("/"):
            path = path / part
            if path.is_symlink():
                raise PlanError(f"Plan source path must not traverse a symbolic link: {name}")
        if not path.is_file():
            raise PlanError(f"frozen Plan source is missing: {name}")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise PlanError(f"frozen Plan source is unreadable: {name}") from exc
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_sha:
            raise PlanError(f"frozen Plan source changed: {name}")
        actual.append((kind, name, digest))
    return tuple(sorted(actual))
