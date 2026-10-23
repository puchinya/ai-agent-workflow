"""Owner-approved, append-only admission of one pre-Activation Issue."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adc import ADCError, verify_adc, verify_adc_generation
from .consumer_activation import ConsumerActivationError, read_consumer_activation_history
from .execution import ExecutionError, binding_digest, read_binding_history
from .gate_policy import (
    BOOTSTRAP_COHORT, BOOTSTRAP_REPOSITORY, LEGACY_ADOPTED_POLICY, GatePolicyError,
    LegacyGateSelection, _canonical, _decode_record_comment, _parse_time, _positive,
    _read_gate_selection_if_present, _sha,
)
from .github import GitHub, GitHubError
from .git import GitError, current_branch, head_sha40, is_ancestor, worktree_clean
from .issue_graph import IssueGraphError, validate_native_issue_graph
from .path_safety import path_has_symlink
from .phases import IssueKind, Phase, PhaseError, parse_attention_labels, parse_phase_labels
from .profile import ProfileError, load_profile
from .work import execution_binding_path


class LegacyAdoptionError(ValueError):
    pass


PLAN_SCHEMA_V1 = "PASES_LEGACY_ADOPTION_PLAN_V1"
PLAN_SCHEMA = "PASES_LEGACY_ADOPTION_PLAN_V2"
BOOTSTRAP_AUTH_SCHEMA = "PASES_LEGACY_BOOTSTRAP_AUTHORIZATION_V1"
ADOPTION_SCHEMA = "PASES_LEGACY_ISSUE_ADOPTION_V1"
LEGACY_GATE_SCHEMA = "PASES_GATE_SELECTION_LEGACY_V1"
OWNER_APPROVAL_SCHEMA = "PASES_LEGACY_OWNER_APPROVAL_V1"
RESET_PLAN_SCHEMA = "PASES_LEGACY_RESET_PLAN_V1"
RESET_INTENT_SCHEMA = "PASES_LEGACY_RESET_INTENT_V1"
RESET_APPLIED_SCHEMA = "PASES_LEGACY_RESET_APPLIED_V1"
ADOPTION_MARKER = f"<!-- {ADOPTION_SCHEMA}\n"
LEGACY_GATE_MARKER = f"<!-- {LEGACY_GATE_SCHEMA}\n"
OWNER_APPROVAL_MARKER = f"<!-- {OWNER_APPROVAL_SCHEMA}\n"
RESET_INTENT_MARKER = f"<!-- {RESET_INTENT_SCHEMA}\n"
RESET_APPLIED_MARKER = f"<!-- {RESET_APPLIED_SCHEMA}\n"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RISK_ACCEPTANCE_REPOSITORY = "puchinya/ai-agent-workflow"
RISK_ACCEPTANCE_REPOSITORY_ID = 1401910271
RISK_ACCEPTANCE_ISSUE = 46
RISK_ACCEPTANCE_OWNER_ID = 3744776
RISK_ACCEPTANCE_MODE = "owner_trusted_single_writer_v1"
ACCEPTED_RISK_IDS = (
    "CONCURRENT_ADOPTION_WRITES_NOT_ATOMIC",
    "PRIVILEGED_COMMENT_DELETION_OR_MARKER_REMOVAL_UNDETECTABLE",
)
PLAN_FIELDS_V1 = {
    "activation_issue_number", "activation_prefix", "adc_comment_id", "adc_sha256", "adc_state",
    "binding", "generated_at", "issue_created_at", "issue_id", "issue_kind", "issue_labels",
    "issue_number", "owner_id", "phase", "planned_gate_payload", "planned_gate_payload_sha256",
    "proposed_phase_action", "remote_head_ref", "remote_head_sha", "repository", "repository_id",
    "schema", "attention_labels", "plan_sha256",
}
PLAN_FIELDS = PLAN_FIELDS_V1 | {"accepted_risks", "writer_policy"}
RESET_PLAN_FIELDS = {
    "adoption_comment_id", "adoption_record_sha256", "generated_at", "issue_created_at", "issue_id",
    "issue_kind", "issue_labels", "issue_number", "owner_id", "phase", "repository", "repository_id",
    "schema", "target_labels", "plan_sha256",
}


def _positive_id(value: Any, label: str) -> int:
    try:
        return _positive(value, label)
    except GatePolicyError as exc:
        raise LegacyAdoptionError(str(exc)) from exc


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise LegacyAdoptionError(f"{label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LegacyAdoptionError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LegacyAdoptionError(f"{label} timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _record_payload(body: Any, sentinel: str) -> dict[str, Any]:
    try:
        return _decode_record_comment(body, sentinel)
    except GatePolicyError as exc:
        raise LegacyAdoptionError(str(exc)) from exc


def _body(sentinel: str, payload: dict[str, Any]) -> str:
    return f"<!-- {sentinel}\n{_canonical(payload).decode('utf-8')}\n-->"


def _identity(repository: str, issue_number: int, issue_id: int,
              repository_id: int, owner_id: int) -> tuple[str, int, int, int, int]:
    if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository):
        raise LegacyAdoptionError("repository identity is invalid")
    for value, label in ((issue_number, "Issue number"), (issue_id, "Issue stable ID"),
                         (repository_id, "repository ID"), (owner_id, "Owner user ID")):
        _positive_id(value, label)
    return repository.casefold(), issue_number, issue_id, repository_id, owner_id


def validate_bootstrap_changed_paths(paths: Any, scope: dict[str, Any]) -> tuple[str, ...]:
    """Reject any tracked Stage 1 path outside the exact Owner-approved budget."""
    scope_body = scope.get("scope") if isinstance(scope, dict) else None
    budget = scope_body.get("changed_file_budget") if isinstance(scope_body, dict) else None
    allowed = budget.get("paths") if isinstance(budget, dict) else None
    maximum = budget.get("max_tracked_files") if isinstance(budget, dict) else None
    if (not isinstance(allowed, list) or not allowed
            or any(not isinstance(item, str) or not item or item.startswith("/")
                   or "\\" in item or any(part in {"", ".", ".."} for part in item.split("/"))
                   for item in allowed)
            or allowed != sorted(set(allowed))
            or type(maximum) is not int or maximum < 1 or maximum > len(allowed)):
        raise LegacyAdoptionError("bootstrap changed-file budget is malformed")
    if (not isinstance(paths, (list, tuple, set, frozenset))
            or any(not isinstance(item, str) or not item or item.startswith("/")
                   or "\\" in item or any(part in {"", ".", ".."} for part in item.split("/"))
                   for item in paths)):
        raise LegacyAdoptionError("tracked bootstrap changed paths are malformed")
    actual = tuple(sorted(paths))
    if (len(actual) != len(set(actual)) or len(actual) > maximum
            or not set(actual).issubset(set(allowed))):
        raise LegacyAdoptionError("tracked bootstrap changes exceed the approved file budget")
    return actual


def validate_bootstrap_prework_subject(prework: Any, scope: dict[str, Any]) -> dict[str, Any]:
    """Check the exact clean worktree/base/branch snapshot bound by bootstrap approval."""
    scope_body = scope.get("scope") if isinstance(scope, dict) else None
    expected = scope_body.get("prework_subject") if isinstance(scope_body, dict) else None
    fields = {"base_ref", "base_sha", "branch_ref", "local_head_sha", "remote_head_sha", "worktree_clean"}
    if (not isinstance(expected, dict) or set(expected) != fields
            or not isinstance(prework, dict) or set(prework) != fields
            or prework != expected or expected.get("worktree_clean") is not True
            or not isinstance(expected.get("branch_ref"), str) or not expected["branch_ref"]
            or not isinstance(expected.get("base_ref"), str) or not expected["base_ref"]
            or not isinstance(expected.get("local_head_sha"), str)
            or not SHA40.fullmatch(expected["local_head_sha"])
            or expected.get("local_head_sha") != expected.get("remote_head_sha")
            or not isinstance(expected.get("base_sha"), str) or not SHA40.fullmatch(expected["base_sha"])):
        raise LegacyAdoptionError("bootstrap worktree does not match its exact clean pre-work subject")
    return prework


def _validate_plan_payload(value: Any, *, schema: str | None = None) -> dict[str, Any]:
    if schema is None:
        schema = value.get("schema") if isinstance(value, dict) else None
    if schema == PLAN_SCHEMA_V1:
        fields = PLAN_FIELDS_V1
    elif schema == PLAN_SCHEMA:
        fields = PLAN_FIELDS
    elif schema == RESET_PLAN_SCHEMA:
        fields = RESET_PLAN_FIELDS
    else:
        raise LegacyAdoptionError("legacy adoption or reset plan schema is unsupported")
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != schema:
        raise LegacyAdoptionError(f"{schema} has unknown or missing fields")
    digest = value.get("plan_sha256")
    without_digest = {key: item for key, item in value.items() if key != "plan_sha256"}
    if not isinstance(digest, str) or not SHA256.fullmatch(digest) or _digest(without_digest) != digest:
        raise LegacyAdoptionError(f"{schema} digest is invalid")
    _identity(value.get("repository"), value.get("issue_number"), value.get("issue_id"),
              value.get("repository_id"), value.get("owner_id"))
    for key, label in (("generated_at", "plan generated"), ("issue_created_at", "Issue creation")):
        if _timestamp(value.get(key), label) != value[key]:
            raise LegacyAdoptionError(f"{label} timestamp is not canonical UTC")
    if value.get("issue_kind") not in {kind.value for kind in (IssueKind.SINGLE, IssueKind.CHILD)}:
        raise LegacyAdoptionError("legacy adoption supports only single and child Issues")
    if schema in {PLAN_SCHEMA_V1, PLAN_SCHEMA}:
        if value.get("phase") not in {phase.value for phase in Phase if phase is not Phase.CLOSED}:
            raise LegacyAdoptionError("legacy adoption plan phase is invalid")
        labels = value.get("issue_labels")
        if (not isinstance(labels, list) or any(not isinstance(item, str) for item in labels)
                or labels != sorted(set(labels))):
            raise LegacyAdoptionError("legacy adoption plan labels are not canonical")
        attention = value.get("attention_labels")
        if (not isinstance(attention, list) or any(not isinstance(item, str) for item in attention)
                or attention != sorted(set(attention))):
            raise LegacyAdoptionError("legacy adoption attention labels are not canonical")
        if sum(label.startswith("kind:") for label in labels) != 1:
            raise LegacyAdoptionError("legacy adoption requires exactly one kind label")
        try:
            parsed_kind = IssueKind(next(label.removeprefix("kind:") for label in labels
                                         if label.startswith("kind:")))
            parsed_phase = parse_phase_labels(labels)
            parsed_attention = sorted(item.value for item in parse_attention_labels(labels))
        except (StopIteration, ValueError, PhaseError) as exc:
            raise LegacyAdoptionError("legacy adoption labels do not identify a valid Issue state") from exc
        if (parsed_kind.value != value["issue_kind"] or parsed_phase.value != value["phase"]
                or parsed_attention != attention or parsed_phase is Phase.CLOSED):
            raise LegacyAdoptionError("legacy adoption fields do not match its Issue labels")
        activation_number = _positive_id(value.get("activation_issue_number"), "Activation Issue number")
        prefix = value.get("activation_prefix")
        if (not isinstance(prefix, dict) or set(prefix) != {"activation_issue_number", "records", "schema", "sha256"}
                or prefix.get("schema") != "PASES_LEGACY_ACTIVATION_PREFIX_V1"
                or prefix.get("activation_issue_number") != activation_number
                or not isinstance(prefix.get("records"), list) or not prefix["records"]
                or not isinstance(prefix.get("sha256"), str) or not SHA256.fullmatch(prefix["sha256"])):
            raise LegacyAdoptionError("legacy adoption Activation prefix is invalid")
        previous_comment_id = 0
        for row in prefix["records"]:
            if (not isinstance(row, dict) or set(row) != {"comment_id", "record_sha256"}
                    or type(row.get("comment_id")) is not int or row["comment_id"] < 1
                    or row["comment_id"] <= previous_comment_id
                    or not isinstance(row.get("record_sha256"), str)
                    or not SHA256.fullmatch(row["record_sha256"])):
                raise LegacyAdoptionError("legacy adoption Activation prefix row is invalid")
            previous_comment_id = row["comment_id"]
        expected_prefix_sha = _digest({"activation_issue_number": activation_number,
                                       "records": prefix["records"],
                                       "schema": "PASES_LEGACY_ACTIVATION_PREFIX_V1"})
        if prefix["sha256"] != expected_prefix_sha:
            raise LegacyAdoptionError("legacy adoption Activation prefix digest is invalid")
        _positive_id(value.get("adc_comment_id"), "ADC comment ID")
        _sha(value.get("adc_sha256"), "ADC digest")
        if value.get("adc_state") != "approved":
            raise LegacyAdoptionError("legacy adoption requires an approved ADC")
        binding = value.get("binding")
        if binding is not None:
            expected_binding = {"base_ref", "base_sha", "branch_ref", "generations", "history_sha256", "latest_sha256"}
            if not isinstance(binding, dict) or set(binding) != expected_binding:
                raise LegacyAdoptionError("legacy adoption Binding snapshot is invalid")
            _sha(binding.get("base_sha"), "Binding base SHA", SHA40)
            _sha(binding.get("history_sha256"), "Binding history digest")
            _sha(binding.get("latest_sha256"), "Binding digest")
            if not all(isinstance(binding.get(key), str) and binding[key] for key in ("base_ref", "branch_ref")):
                raise LegacyAdoptionError("legacy adoption Binding refs are invalid")
            generations = binding.get("generations")
            if (not isinstance(generations, list) or not generations
                    or any(not isinstance(row, dict) or set(row) != {"adc_comment_id", "binding_sha256"}
                           or type(row.get("adc_comment_id")) is not int or row["adc_comment_id"] < 1
                           or not isinstance(row.get("binding_sha256"), str)
                           or not SHA256.fullmatch(row["binding_sha256"]) for row in generations)
                    or generations[-1]["binding_sha256"] != binding["latest_sha256"]):
                raise LegacyAdoptionError("legacy adoption Binding generations are invalid")
            if any(left["adc_comment_id"] >= right["adc_comment_id"]
                   for left, right in zip(generations, generations[1:])):
                raise LegacyAdoptionError("legacy adoption Binding generations are not append-only")
        if (not isinstance(value.get("remote_head_ref"), str) or not value["remote_head_ref"]
                or not isinstance(value.get("remote_head_sha"), str)
                or not SHA40.fullmatch(value["remote_head_sha"])):
            raise LegacyAdoptionError("legacy adoption remote HEAD is invalid")
        if binding is not None and value["remote_head_ref"] != binding["branch_ref"]:
            raise LegacyAdoptionError("legacy adoption remote branch differs from its frozen Binding")
        expected_action = ("KEEP_REQUIREMENTS" if value["phase"] == Phase.REQUIREMENTS.value
                           else "RESET_TO_REQUIREMENTS_REQUIRED")
        if value.get("proposed_phase_action") != expected_action:
            raise LegacyAdoptionError("legacy adoption proposed phase action is invalid")
        planned_gate = value.get("planned_gate_payload")
        if not isinstance(planned_gate, dict) or set(planned_gate) != {
                "issue_number", "policy_version", "repository", "schema", "selected_at"}:
            raise LegacyAdoptionError("planned legacy Gate payload is invalid")
        if (planned_gate.get("schema") != LEGACY_GATE_SCHEMA
                or planned_gate.get("policy_version") != LEGACY_ADOPTED_POLICY
                or not isinstance(planned_gate.get("repository"), str)
                or planned_gate["repository"].casefold() != value["repository"].casefold()
                or planned_gate.get("issue_number") != value["issue_number"]):
            raise LegacyAdoptionError("planned legacy Gate subject is invalid")
        if (_timestamp(planned_gate.get("selected_at"), "planned Gate selection")
                != planned_gate.get("selected_at")
                or planned_gate["selected_at"] != value["generated_at"]):
            raise LegacyAdoptionError("planned Gate selection time differs from plan generation time")
        if value.get("planned_gate_payload_sha256") != _digest(planned_gate):
            raise LegacyAdoptionError("planned legacy Gate digest is invalid")
        if schema == PLAN_SCHEMA:
            writer_policy = value.get("writer_policy")
            expected_writer_policy = {
                "max_active_writers": 1,
                "mode": RISK_ACCEPTANCE_MODE,
                "required_user_id": RISK_ACCEPTANCE_OWNER_ID,
            }
            if (value.get("repository", "").casefold() != RISK_ACCEPTANCE_REPOSITORY.casefold()
                    or value.get("repository_id") != RISK_ACCEPTANCE_REPOSITORY_ID
                    or value.get("owner_id") != RISK_ACCEPTANCE_OWNER_ID
                    or value.get("issue_number") != RISK_ACCEPTANCE_ISSUE):
                raise LegacyAdoptionError(
                    "risk-accepted Adoption plan is limited to the exact repository, Owner, and Issue #46"
                )
            if writer_policy != expected_writer_policy:
                raise LegacyAdoptionError("legacy Adoption writer policy is invalid")
            if value.get("accepted_risks") != list(ACCEPTED_RISK_IDS):
                raise LegacyAdoptionError("legacy Adoption risk acceptance does not name both exact risks")
    else:
        if value.get("phase") in {None, Phase.REQUIREMENTS.value, Phase.CLOSED.value}:
            raise LegacyAdoptionError("reset plan must name an open phase after requirements")
        labels = value.get("issue_labels")
        if (not isinstance(labels, list) or any(not isinstance(item, str) for item in labels)
                or labels != sorted(set(labels))):
            raise LegacyAdoptionError("reset source labels are not canonical")
        if sum(label.startswith("kind:") for label in labels) != 1:
            raise LegacyAdoptionError("reset source requires exactly one kind label")
        try:
            source_kind = IssueKind(next(label.removeprefix("kind:") for label in labels
                                         if label.startswith("kind:")))
            source_phase = parse_phase_labels(labels)
            source_attention = parse_attention_labels(labels)
        except (StopIteration, ValueError, PhaseError) as exc:
            raise LegacyAdoptionError("reset source labels do not identify a valid Issue state") from exc
        if (source_kind.value != value["issue_kind"] or source_phase.value != value["phase"]
                or source_attention):
            raise LegacyAdoptionError("reset source fields do not match the current Issue labels")
        if not isinstance(value.get("target_labels"), list):
            raise LegacyAdoptionError("reset target labels are invalid")
        if (any(not isinstance(item, str) for item in value["target_labels"])
                or value["target_labels"] != sorted(set(value["target_labels"]))):
            raise LegacyAdoptionError("reset target labels are not canonical")
        if sum(label.startswith("kind:") for label in value["target_labels"]) != 1:
            raise LegacyAdoptionError("reset target requires exactly one kind label")
        try:
            target_kind = IssueKind(next(label.removeprefix("kind:") for label in value["target_labels"]
                                         if label.startswith("kind:")))
            target_phase = parse_phase_labels(value["target_labels"])
            target_attention = parse_attention_labels(value["target_labels"])
        except (StopIteration, ValueError, PhaseError) as exc:
            raise LegacyAdoptionError("reset target labels do not identify a valid Issue state") from exc
        source_unmanaged = sorted(label for label in labels
                                  if not label.startswith(("phase:", "attention:")))
        target_unmanaged = sorted(label for label in value["target_labels"]
                                  if not label.startswith(("phase:", "attention:")))
        if (target_kind is not source_kind or target_phase is not Phase.REQUIREMENTS
                or target_attention or source_unmanaged != target_unmanaged):
            raise LegacyAdoptionError("reset target labels do not preserve the Issue identity and set requirements")
        _positive_id(value.get("adoption_comment_id"), "Adoption comment ID")
        _sha(value.get("adoption_record_sha256"), "Adoption record digest")
    return value


@dataclass(frozen=True)
class LegacyAdoptionPlan:
    value: dict[str, Any]

    def validate(self) -> "LegacyAdoptionPlan":
        _validate_plan_payload(self.value)
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        return self.value["plan_sha256"]

    @classmethod
    def from_payload(cls, value: Any) -> "LegacyAdoptionPlan":
        return cls(value).validate()


@dataclass(frozen=True)
class LegacyResetPlan:
    value: dict[str, Any]

    def validate(self) -> "LegacyResetPlan":
        _validate_plan_payload(self.value, schema=RESET_PLAN_SCHEMA)
        return self

    @property
    def sha256(self) -> str:
        self.validate()
        return self.value["plan_sha256"]

    @classmethod
    def from_payload(cls, value: Any) -> "LegacyResetPlan":
        return cls(value).validate()


def validate_bootstrap_authorization_record(value: Any, scope: dict[str, Any], *,
                                            changed_paths: Any = None) -> dict[str, Any]:
    """Validate the operator-reported, scope-bound local Stage 1 grant record."""
    fields = {
        "activation_prefix_sha256", "adc_comment_id", "adc_sha256", "approval_channel", "binding_sha256",
        "branch_ref", "changed_file_budget_sha256", "decision", "decision_observed_at", "issue_number",
        "issue_stable_id", "owner_user_id", "prework_head_sha", "repository_id", "schema", "scope_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != BOOTSTRAP_AUTH_SCHEMA:
        raise LegacyAdoptionError("bootstrap authorization record has unknown or missing fields")
    if (not isinstance(scope, dict) or not isinstance(scope.get("scope"), dict)
            or scope["scope"].get("operation") != "ISSUE_46_STAGE_1_LEGACY_ADMISSION_BOOTSTRAP"
            or scope["scope"].get("schema") != "PASES_LEGACY_BOOTSTRAP_SCOPE_V1"):
        raise LegacyAdoptionError("bootstrap authorization scope is invalid")
    scope_body = scope["scope"]
    if (set(scope) != {"scope", "scope_sha256"} or not isinstance(scope.get("scope_sha256"), str)
            or not SHA256.fullmatch(scope["scope_sha256"])
            or _digest(scope_body) != scope["scope_sha256"]):
        raise LegacyAdoptionError("bootstrap authorization scope digest is invalid")
    for key in ("repository", "issue", "approved_adc", "activation_prefix", "execution_binding",
                "prework_subject", "changed_file_budget", "authorization_record"):
        if not isinstance(scope_body.get(key), dict):
            raise LegacyAdoptionError(f"bootstrap authorization scope field {key} is malformed")
    generations = scope_body["execution_binding"].get("generations")
    if (not isinstance(generations, list) or not generations
            or any(not isinstance(row, dict) for row in generations)):
        raise LegacyAdoptionError("bootstrap authorization Binding generations are malformed")
    expected = {
        "scope_sha256": scope.get("scope_sha256"),
        "repository_id": scope_body.get("repository", {}).get("repository_id"),
        "owner_user_id": scope_body.get("repository", {}).get("owner_user_id"),
        "issue_number": scope_body.get("issue", {}).get("number"),
        "issue_stable_id": scope_body.get("issue", {}).get("stable_id"),
        "adc_comment_id": scope_body.get("approved_adc", {}).get("comment_id"),
        "adc_sha256": scope_body.get("approved_adc", {}).get("sha256"),
        "activation_prefix_sha256": scope_body.get("activation_prefix", {}).get("prefix_sha256"),
        "binding_sha256": generations[-1].get("binding_sha256"),
        "branch_ref": scope_body.get("prework_subject", {}).get("branch_ref"),
        "prework_head_sha": scope_body.get("prework_subject", {}).get("remote_head_sha"),
        "changed_file_budget_sha256": hashlib.sha256(json.dumps(
            scope_body.get("changed_file_budget", {}).get("paths"), separators=(",", ":")).encode()).hexdigest(),
        "decision": "APPROVED",
        "approval_channel": "same-conversation direct user-role response",
    }
    authorization = scope_body.get("authorization_record")
    if (not isinstance(authorization, dict)
            or authorization.get("schema") != BOOTSTRAP_AUTH_SCHEMA
            or authorization.get("record_path") != ".p_ases/state/46/legacy-bootstrap-authorization-v1.json"
            or not isinstance(authorization.get("record_fields"), list)
            or any(not isinstance(field, str) for field in authorization["record_fields"])
            or set(authorization["record_fields"]) != fields):
        raise LegacyAdoptionError("bootstrap authorization scope has an invalid record contract")
    validate_bootstrap_changed_paths([], scope)
    if any(value.get(key) != item for key, item in expected.items()):
        raise LegacyAdoptionError("bootstrap authorization record does not match the exact approved scope")
    if changed_paths is not None:
        validate_bootstrap_changed_paths(changed_paths, scope)
    _timestamp(value.get("decision_observed_at"), "bootstrap decision")
    return value


def read_bootstrap_authorization_record(record_path: Path, scope_path: Path, *,
                                       changed_paths: Any = None,
                                       prework_subject: Any = None) -> dict[str, Any]:
    """Read the canonical local bootstrap record and bind it to its approved scope."""
    record_location, scope_location = Path(record_path), Path(scope_path)
    if (record_location.is_symlink() or not record_location.is_file()
            or scope_location.is_symlink() or not scope_location.is_file()):
        raise LegacyAdoptionError("bootstrap authorization and scope must be regular non-symlink files")
    try:
        record_bytes = record_location.read_bytes()
        scope_bytes = scope_location.read_bytes()
        record = json.loads(record_bytes.decode("utf-8", errors="strict"))
        scope = json.loads(scope_bytes.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyAdoptionError("bootstrap authorization or scope file is unreadable JSON") from exc
    if _canonical(record) + b"\n" != record_bytes:
        raise LegacyAdoptionError("bootstrap authorization record is not canonical JSON with one trailing newline")
    validated = validate_bootstrap_authorization_record(record, scope, changed_paths=changed_paths)
    if prework_subject is not None:
        validate_bootstrap_prework_subject(prework_subject, scope)
    return validated


def _repository_identity(github: GitHub) -> tuple[int, int]:
    metadata = github.repository_metadata()
    owner = metadata.get("owner") if isinstance(metadata, dict) else None
    owner_login = github.repo.split("/", 1)[0]
    repository_id = metadata.get("id") if isinstance(metadata, dict) else None
    if (type(repository_id) is not int or repository_id < 1
            or not isinstance(owner, dict) or type(owner.get("id")) is not int or owner["id"] < 1
            or owner.get("type") != "User" or not isinstance(owner.get("login"), str)
            or owner["login"].casefold() != owner_login.casefold()):
        raise LegacyAdoptionError("repository/Owner stable identity is invalid")
    return repository_id, owner["id"]


def _exact_issue(github: GitHub, issue_number: int) -> dict[str, Any]:
    issue = github.issue(issue_number)
    if not isinstance(issue, dict):
        raise LegacyAdoptionError("GitHub did not return an Issue object")
    expected_url = f"https://api.github.com/repos/{github.repo}"
    if (issue.get("number") != issue_number or type(issue.get("id")) is not int or issue["id"] < 1
            or issue.get("state") != "open" or issue.get("pull_request") is not None
            or not isinstance(issue.get("repository_url"), str)
            or issue["repository_url"].casefold() != expected_url.casefold()
            or not isinstance(issue.get("created_at"), str)):
        raise LegacyAdoptionError("legacy admission requires the exact open same-repository Issue")
    return issue


def _issue_labels(issue: dict[str, Any]) -> tuple[list[str], IssueKind, Phase, list[str]]:
    if not isinstance(issue, dict):
        raise LegacyAdoptionError("GitHub Issue identity is malformed")
    rows = issue.get("labels")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise LegacyAdoptionError("Issue labels are unavailable or malformed")
    labels = [row.get("name") for row in rows]
    if any(not isinstance(label, str) or not label for label in labels) or len(labels) != len(set(labels)):
        raise LegacyAdoptionError("Issue labels contain invalid or duplicate values")
    kind_labels = [label.removeprefix("kind:") for label in labels if label.startswith("kind:")]
    if len(kind_labels) != 1:
        raise LegacyAdoptionError("legacy admission requires one verified kind:* label")
    try:
        kind = IssueKind(kind_labels[0])
        phase = parse_phase_labels(labels)
        attention = sorted(item.value for item in parse_attention_labels(labels))
    except (ValueError, PhaseError) as exc:
        raise LegacyAdoptionError(f"Issue kind/phase/attention labels are invalid: {exc}") from exc
    if kind not in {IssueKind.SINGLE, IssueKind.CHILD}:
        raise LegacyAdoptionError("legacy admission supports only single and child Issues")
    return sorted(labels), kind, phase, attention


def _activation_prefix(activation_issue_number: int, history: list[tuple[Any, int]]) -> dict[str, Any]:
    rows = [{"comment_id": comment_id, "record_sha256": record.sha256} for record, comment_id in history]
    payload = {
        "activation_issue_number": activation_issue_number,
        "records": rows,
        "schema": "PASES_LEGACY_ACTIVATION_PREFIX_V1",
    }
    return {**payload, "sha256": _digest(payload)}


def _snapshot_binding(root: Path, github: GitHub, issue_number: int, adc: Any) -> dict[str, Any] | None:
    path = execution_binding_path(root, issue_number)
    if path_has_symlink(path, root=root):
        raise LegacyAdoptionError("ExecutionBinding path traverses a symlink")
    if not path.exists():
        return None
    try:
        history = read_binding_history(path)
    except (ExecutionError, OSError) as exc:
        raise LegacyAdoptionError(f"ExecutionBinding history is invalid: {exc}") from exc
    if not history:
        raise LegacyAdoptionError("ExecutionBinding history is empty")
    latest = history[-1]
    if (latest.repository.casefold() != github.repo.casefold() or latest.issue_number != issue_number
            or latest.adc_comment_id != adc.pointer.comment_id or latest.adc_sha256 != adc.contract.sha256
            or Path(latest.work_directory).resolve() != root.resolve()):
        raise LegacyAdoptionError("latest ExecutionBinding does not match the current Issue, ADC, or worktree")
    raw = path.read_bytes()
    try:
        remote = github.branch(latest.branch_ref)
        if (not isinstance(remote, dict) or not isinstance(remote.get("commit"), dict)):
            raise LegacyAdoptionError("bound remote branch readback is malformed")
        if (current_branch(root) != latest.branch_ref or not worktree_clean(root)
                or head_sha40(root) != remote["commit"].get("sha")):
            raise LegacyAdoptionError("bound worktree must be clean and match its current remote branch HEAD")
    except (GitError, GitHubError) as exc:
        raise LegacyAdoptionError(f"bound worktree state is invalid: {exc}") from exc
    return {
        "base_ref": latest.base_ref,
        "base_sha": latest.base_sha,
        "branch_ref": latest.branch_ref,
        "generations": [{"adc_comment_id": row.adc_comment_id, "binding_sha256": binding_digest(row)}
                        for row in history],
        "history_sha256": hashlib.sha256(raw).hexdigest(),
        "latest_sha256": binding_digest(latest),
    }


def build_legacy_adoption_plan(github: GitHub, root: Path, issue_number: int, *,
                               generated_at: str | None = None) -> LegacyAdoptionPlan:
    """Read every exact input and produce a canonical per-Issue Owner plan."""
    if type(issue_number) is not int or issue_number < 1:
        raise LegacyAdoptionError("Issue number must be positive")
    if (github.repo.casefold() != RISK_ACCEPTANCE_REPOSITORY.casefold()
            or issue_number != RISK_ACCEPTANCE_ISSUE):
        raise LegacyAdoptionError("Owner-trusted single-writer risk mode is limited to Issue #46")
    root = Path(root).resolve()
    issue = _exact_issue(github, issue_number)
    repository_id, owner_id = _repository_identity(github)
    if (repository_id != RISK_ACCEPTANCE_REPOSITORY_ID
            or owner_id != RISK_ACCEPTANCE_OWNER_ID):
        raise LegacyAdoptionError("risk-accepted Adoption requires the exact configured repository Owner identity")
    labels, kind, phase, attention = _issue_labels(issue)
    if (github.repo.casefold() == BOOTSTRAP_REPOSITORY.casefold()
            and issue_number in BOOTSTRAP_COHORT):
        raise LegacyAdoptionError("fixed Bootstrap cohort cannot use legacy admission")
    try:
        verified_adc = verify_adc(github, issue_number)
    except ADCError as exc:
        raise LegacyAdoptionError(f"legacy admission requires a verified current ADC: {exc}") from exc
    if verified_adc.pointer.state != "approved":
        raise LegacyAdoptionError("legacy admission requires the current ADC pointer to be approved")
    try:
        profile = load_profile(root)
    except ProfileError as exc:
        raise LegacyAdoptionError(f"legacy admission requires the verified Activation locator: {exc}") from exc
    activation_issue_number = profile.activation_issue_number
    if activation_issue_number is None:
        raise LegacyAdoptionError("project profile does not identify the consumer Activation Issue")
    try:
        activation_history = read_consumer_activation_history(github, github.repo, activation_issue_number)
    except (ConsumerActivationError, GitHubError) as exc:
        raise LegacyAdoptionError(f"verified Activation history is unavailable: {exc}") from exc
    if not activation_history:
        raise LegacyAdoptionError("verified Activation history is empty")
    issue_created = _parse_time(issue["created_at"], "Issue creation")
    earliest_activation = min(_parse_time(record.activated_at, "Activation") for record, _cid in activation_history)
    if issue_created > earliest_activation:
        raise LegacyAdoptionError("Issue was created after the first verified Activation")
    prefix = _activation_prefix(activation_issue_number, activation_history)
    binding = _snapshot_binding(root, github, issue_number, verified_adc)
    repository_metadata = github.repository_metadata()
    remote_ref = (binding["branch_ref"] if binding is not None else
                  repository_metadata.get("default_branch") if isinstance(repository_metadata, dict) else None)
    if not isinstance(remote_ref, str) or not remote_ref:
        raise LegacyAdoptionError("remote branch reference is unavailable")
    try:
        branch = github.branch(remote_ref)
    except GitHubError as exc:
        raise LegacyAdoptionError(f"remote branch readback failed: {exc}") from exc
    remote_head = (branch.get("commit", {}).get("sha")
                   if isinstance(branch, dict) and isinstance(branch.get("commit"), dict) else None)
    if (not isinstance(branch, dict) or branch.get("name") != remote_ref
            or not isinstance(remote_head, str) or not SHA40.fullmatch(remote_head)):
        raise LegacyAdoptionError("remote branch identity or HEAD is invalid")
    try:
        existing_gate = _read_gate_selection_if_present(github, issue_number)
    except GatePolicyError as exc:
        raise LegacyAdoptionError(f"existing Gate history is invalid: {exc}") from exc
    if existing_gate is not None:
        raise LegacyAdoptionError("Issue already has an effective Gate; legacy admission cannot replace it")
    selected_at = _timestamp(generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "plan generated")
    planned_gate = {
        "issue_number": issue_number,
        "policy_version": LEGACY_ADOPTED_POLICY,
        "repository": github.repo,
        "schema": LEGACY_GATE_SCHEMA,
        "selected_at": selected_at,
    }
    payload = {
        "activation_issue_number": activation_issue_number,
        "activation_prefix": prefix,
        "adc_comment_id": verified_adc.pointer.comment_id,
        "adc_sha256": verified_adc.contract.sha256,
        "adc_state": verified_adc.pointer.state,
        "accepted_risks": list(ACCEPTED_RISK_IDS),
        "attention_labels": attention,
        "binding": binding,
        "generated_at": selected_at,
        "issue_created_at": _timestamp(issue["created_at"], "Issue creation"),
        "issue_id": issue["id"],
        "issue_kind": kind.value,
        "issue_labels": labels,
        "issue_number": issue_number,
        "owner_id": owner_id,
        "phase": phase.value,
        "planned_gate_payload": planned_gate,
        "planned_gate_payload_sha256": _digest(planned_gate),
        "proposed_phase_action": ("KEEP_REQUIREMENTS" if phase is Phase.REQUIREMENTS
                                  else "RESET_TO_REQUIREMENTS_REQUIRED"),
        "remote_head_ref": remote_ref,
        "remote_head_sha": remote_head,
        "repository": github.repo,
        "repository_id": repository_id,
        "schema": PLAN_SCHEMA,
        "writer_policy": {
            "max_active_writers": 1,
            "mode": RISK_ACCEPTANCE_MODE,
            "required_user_id": owner_id,
        },
    }
    plan = {**payload, "plan_sha256": _digest(payload)}
    return LegacyAdoptionPlan(plan).validate()


def read_legacy_adoption_plan(path: Path) -> LegacyAdoptionPlan:
    location = Path(path)
    if location.is_symlink() or not location.is_file():
        raise LegacyAdoptionError("plan path must be a regular non-symlink file")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyAdoptionError("plan file is not readable canonical JSON") from exc
    if _canonical(value) + b"\n" != raw:
        raise LegacyAdoptionError("plan file is not canonical JSON with one trailing newline")
    return LegacyAdoptionPlan.from_payload(value)


def write_legacy_adoption_plan(path: Path, plan: LegacyAdoptionPlan) -> None:
    plan.validate()
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise LegacyAdoptionError("plan output already exists; refusing to overwrite immutable approval input")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical(plan.value) + b"\n")


def owner_approval_comment(plan: LegacyAdoptionPlan | LegacyResetPlan, *, operation: str = "LEGACY_ADOPTION") -> str:
    plan.validate()
    if operation not in {"LEGACY_ADOPTION", "RESET_TO_REQUIREMENTS"}:
        raise LegacyAdoptionError("Owner approval operation is invalid")
    payload = {
        "approved": True,
        "issue_id": plan.value["issue_id"],
        "issue_number": plan.value["issue_number"],
        "operation": operation,
        "plan_sha256": plan.sha256,
        "repository": plan.value["repository"],
        "repository_id": plan.value["repository_id"],
        "schema": OWNER_APPROVAL_SCHEMA,
    }
    return _body(OWNER_APPROVAL_SCHEMA, payload)


def _comment_fingerprint(row: Any, issue_number: int, comment_id: int, repository: str) -> tuple[Any, ...]:
    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] != comment_id:
        raise LegacyAdoptionError("Issue comment identity is invalid")
    expected_issue_url = f"https://api.github.com/repos/{repository}/issues/{issue_number}"
    expected_html_url = f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}"
    expected_url = f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}"
    if (row.get("issue_url") != expected_issue_url or row.get("html_url") != expected_html_url
            or row.get("url") != expected_url):
        raise LegacyAdoptionError("Issue comment repository/Issue attribution metadata is invalid")
    created, updated = row.get("created_at"), row.get("updated_at")
    if not isinstance(created, str) or created != updated:
        raise LegacyAdoptionError("Issue comment is edited or has invalid timestamps")
    _timestamp(created, "Issue comment")
    actor = row.get("user")
    if (not isinstance(actor, dict) or type(actor.get("id")) is not int or actor["id"] < 1
            or not isinstance(actor.get("login"), str) or actor.get("type") not in {"User", "Bot"}):
        raise LegacyAdoptionError("Issue comment author identity is incomplete")
    return (comment_id, row.get("body"), created, updated, actor["id"], actor["login"], actor["type"],
            row.get("issue_url"), row.get("html_url"), row.get("url"))


def _read_comment_direct_list_direct(github: GitHub, issue_number: int, comment_id: int,
                                     *, expected_body: str | None = None) -> dict[str, Any]:
    try:
        direct_first = github.issue_comment(issue_number, comment_id)
        listed_rows = [row for row in github.issue_comments(issue_number)
                       if isinstance(row, dict) and row.get("id") == comment_id]
        direct_second = github.issue_comment(issue_number, comment_id)
    except GitHubError as exc:
        raise LegacyAdoptionError(f"Issue comment direct/list/direct readback failed: {exc}") from exc
    if len(listed_rows) != 1:
        raise LegacyAdoptionError("Issue comment is missing or duplicated in the complete list")
    first = _comment_fingerprint(direct_first, issue_number, comment_id, github.repo)
    listed = _comment_fingerprint(listed_rows[0], issue_number, comment_id, github.repo)
    second = _comment_fingerprint(direct_second, issue_number, comment_id, github.repo)
    if first != listed or first != second:
        raise LegacyAdoptionError("Issue comment changed across direct/list/direct readback")
    if expected_body is not None and direct_second.get("body") != expected_body:
        raise LegacyAdoptionError("Issue comment body differs from the expected immutable payload")
    return direct_second


def _owner_approval_payload(plan: LegacyAdoptionPlan | LegacyResetPlan, operation: str) -> dict[str, Any]:
    _body_value = owner_approval_comment(plan, operation=operation)
    return _record_payload(_body_value, OWNER_APPROVAL_SCHEMA)


def verify_owner_approval(github: GitHub, plan: LegacyAdoptionPlan | LegacyResetPlan, comment_id: int,
                          *, operation: str = "LEGACY_ADOPTION") -> dict[str, Any]:
    """Verify the unique Owner-authored UI comment for one exact plan."""
    plan.validate()
    _positive_id(comment_id, "Owner approval comment ID")
    if operation not in {"LEGACY_ADOPTION", "RESET_TO_REQUIREMENTS"}:
        raise LegacyAdoptionError("Owner approval operation is invalid")
    expected = _owner_approval_payload(plan, operation)
    repository_id, owner_id = _repository_identity(github)
    if (repository_id != plan.value["repository_id"] or owner_id != plan.value["owner_id"]
            or github.repo.casefold() != plan.value["repository"].casefold()):
        raise LegacyAdoptionError("Owner approval repository identity changed")
    try:
        comments = github.issue_comments(plan.value["issue_number"])
    except GitHubError as exc:
        raise LegacyAdoptionError(f"Owner approval history readback failed: {exc}") from exc
    candidates: list[dict[str, Any]] = []
    for row in comments:
        body_value = row.get("body") if isinstance(row, dict) else None
        if not isinstance(body_value, str) or not body_value.startswith(OWNER_APPROVAL_MARKER):
            continue
        payload = _record_payload(body_value, OWNER_APPROVAL_SCHEMA)
        if payload.get("issue_number") != plan.value["issue_number"]:
            raise LegacyAdoptionError("Owner approval comment is attached to a different Issue")
        if payload == expected:
            candidates.append(row)
    if len(candidates) != 1 or candidates[0].get("id") != comment_id:
        raise LegacyAdoptionError("exact Owner approval comment is missing, duplicated, or has the wrong ID")
    row = _read_comment_direct_list_direct(
        github, plan.value["issue_number"], comment_id, expected_body=_body(OWNER_APPROVAL_SCHEMA, expected),
    )
    actor = row.get("user")
    owner_login = plan.value["repository"].split("/", 1)[0]
    if (actor.get("id") != owner_id or actor.get("type") != "User"
            or actor.get("login", "").casefold() != owner_login.casefold()):
        raise LegacyAdoptionError("Owner approval was not authored by the repository Owner User ID")
    if _parse_time(row["created_at"], "Owner approval") < _parse_time(
            plan.value["generated_at"], "plan generated"):
        raise LegacyAdoptionError("Owner approval predates the approved plan")
    return row


def _require_owner_writer(github: GitHub, plan: LegacyAdoptionPlan) -> dict[str, Any]:
    """Require each bounded-risk writer to use the repository Owner's GitHub identity."""
    try:
        actor = github.authenticated_user()
    except GitHubError as exc:
        raise LegacyAdoptionError(f"authenticated Owner writer identity is unavailable: {exc}") from exc
    owner_login = plan.value["repository"].split("/", 1)[0]
    if (not isinstance(actor, dict) or actor.get("id") != plan.value["owner_id"]
            or actor.get("type") != "User"
            or not isinstance(actor.get("login"), str)
            or actor["login"].casefold() != owner_login.casefold()):
        raise LegacyAdoptionError("bounded-risk Adoption must run as the authenticated repository Owner")
    return actor


def _require_owner_record_author(row: dict[str, Any], plan: LegacyAdoptionPlan, label: str) -> None:
    actor = row.get("user")
    owner_login = plan.value["repository"].split("/", 1)[0]
    if (not isinstance(actor, dict) or actor.get("id") != plan.value["owner_id"]
            or actor.get("type") != "User"
            or not isinstance(actor.get("login"), str)
            or actor["login"].casefold() != owner_login.casefold()):
        raise LegacyAdoptionError(f"{label} was not written by the authenticated repository Owner")


def _read_adoption_state(github: GitHub, issue_number: int) -> dict[str, Any] | None:
    try:
        comments = github.issue_comments(issue_number)
    except GitHubError as exc:
        raise LegacyAdoptionError(f"legacy adoption history readback failed: {exc}") from exc
    adoption_rows = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                     and row["body"].startswith(ADOPTION_MARKER)]
    legacy_gate_rows = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                        and row["body"].startswith(LEGACY_GATE_MARKER)]
    ordinary_gate_rows = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
                          and row["body"].startswith("<!-- PASES_GATE_SELECTION_V1\n")]
    if len(adoption_rows) > 1 or len(legacy_gate_rows) > 1 or ordinary_gate_rows:
        raise LegacyAdoptionError("Issue has duplicate, conflicting, or ordinary Gate history")
    if not adoption_rows:
        if legacy_gate_rows:
            raise LegacyAdoptionError("legacy Gate exists without its linked Adoption record")
        return None
    adoption_row = adoption_rows[0]
    adoption_id = _positive_id(adoption_row.get("id"), "Adoption comment ID")
    adoption_payload = _record_payload(adoption_row.get("body"), ADOPTION_SCHEMA)
    expected_fields = {"approval_comment_id", "plan", "plan_sha256", "planned_gate_payload_sha256", "schema"}
    if set(adoption_payload) != expected_fields or adoption_payload.get("schema") != ADOPTION_SCHEMA:
        raise LegacyAdoptionError("Adoption record has unknown or missing fields")
    plan = LegacyAdoptionPlan.from_payload(adoption_payload["plan"])
    if (plan.value["issue_number"] != issue_number or adoption_payload.get("plan_sha256") != plan.sha256
            or adoption_payload.get("planned_gate_payload_sha256") != plan.value["planned_gate_payload_sha256"]):
        raise LegacyAdoptionError("Adoption record plan/digest does not match its Issue")
    approval_id = _positive_id(adoption_payload.get("approval_comment_id"), "Owner approval Comment ID")
    if adoption_id <= approval_id:
        raise LegacyAdoptionError("Adoption record does not follow its Owner approval in append-only order")
    approval_row = verify_owner_approval(github, plan, approval_id)
    adoption_row = _read_comment_direct_list_direct(
        github, issue_number, adoption_id, expected_body=_body(ADOPTION_SCHEMA, adoption_payload),
    )
    if plan.value["schema"] == PLAN_SCHEMA:
        _require_owner_record_author(adoption_row, plan, "Adoption record")
    if _parse_time(adoption_row["created_at"], "Adoption record") < _parse_time(
            approval_row["created_at"], "Owner approval"):
        raise LegacyAdoptionError("Adoption record predates its Owner approval")
    adoption_sha = _digest(adoption_payload)
    if not legacy_gate_rows:
        return {
            "adoption_comment_id": adoption_id, "adoption_payload": adoption_payload,
            "adoption_record_sha256": adoption_sha, "approval_comment_id": approval_id,
            "gate_comment_id": None, "gate_selection": None, "plan": plan,
        }
    gate_row = legacy_gate_rows[0]
    gate_id = _positive_id(gate_row.get("id"), "legacy Gate comment ID")
    gate_payload = _record_payload(gate_row.get("body"), LEGACY_GATE_SCHEMA)
    if gate_id <= adoption_id:
        raise LegacyAdoptionError("legacy Gate record does not follow the Adoption record")
    try:
        selection = LegacyGateSelection.from_payload(gate_payload)
    except GatePolicyError as exc:
        raise LegacyAdoptionError(str(exc)) from exc
    if (selection.issue_number != issue_number or selection.repository.casefold() != github.repo.casefold()
            or selection.adoption_comment_id != adoption_id or selection.adoption_record_sha256 != adoption_sha
            or selection.selection_sha256 != plan.value["planned_gate_payload_sha256"]
            or selection.selection_payload() != plan.value["planned_gate_payload"]):
        raise LegacyAdoptionError("legacy Gate does not link to the exact Adoption and planned selection")
    gate_readback = _read_comment_direct_list_direct(
        github, issue_number, gate_id, expected_body=_body(LEGACY_GATE_SCHEMA, gate_payload),
    )
    if plan.value["schema"] == PLAN_SCHEMA:
        _require_owner_record_author(gate_readback, plan, "legacy Gate record")
    if _parse_time(gate_readback["created_at"], "legacy Gate record") < _parse_time(
            adoption_row["created_at"], "Adoption record"):
        raise LegacyAdoptionError("legacy Gate record predates its Adoption record")
    return {
        "adoption_comment_id": adoption_id, "adoption_payload": adoption_payload,
        "adoption_record_sha256": adoption_sha, "approval_comment_id": approval_id,
        "gate_comment_id": gate_id, "gate_selection": selection, "plan": plan,
    }


def _append_record(github: GitHub, issue_number: int, sentinel: str,
                   payload: dict[str, Any]) -> tuple[int, str]:
    """Append one immutable record and recover only an exact prior body."""
    expected_body = _body(sentinel, payload)
    try:
        comments = github.issue_comments(issue_number)
    except GitHubError as exc:
        raise LegacyAdoptionError(f"{sentinel} pre-write history readback failed: {exc}") from exc
    rows = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
            and row["body"].startswith(f"<!-- {sentinel}\n")]
    if len(rows) > 1 or (rows and rows[0].get("body") != expected_body):
        raise LegacyAdoptionError(f"{sentinel} history is duplicated or conflicts with the exact plan")
    if rows:
        comment_id = _positive_id(rows[0].get("id"), f"{sentinel} comment ID")
    else:
        issue = _exact_issue(github, issue_number)
        if issue.get("state") != "open":
            raise LegacyAdoptionError(f"{sentinel} can only be appended to an open Issue")
        try:
            created = github.create_issue_comment(issue_number, expected_body)
        except GitHubError as exc:
            # The caller can resume read-only; this invocation never blindly retries.
            raise LegacyAdoptionError(f"{sentinel} append response is uncertain; read-only recovery is required") from exc
        comment_id = _positive_id(created.get("id"), f"created {sentinel} comment ID")
    readback = _read_comment_direct_list_direct(github, issue_number, comment_id, expected_body=expected_body)
    listed_matches = [row for row in github.issue_comments(issue_number)
                      if isinstance(row, dict) and row.get("body") == expected_body]
    if len(listed_matches) != 1 or listed_matches[0].get("id") != comment_id:
        raise LegacyAdoptionError(f"{sentinel} complete history readback is missing or duplicated")
    return comment_id, readback["body"]


def _fresh_plan(github: GitHub, root: Path, plan: LegacyAdoptionPlan) -> LegacyAdoptionPlan:
    current = build_legacy_adoption_plan(
        github, root, plan.value["issue_number"], generated_at=plan.value["generated_at"],
    )
    if current.value != plan.value:
        raise LegacyAdoptionError("legacy Adoption plan is stale; one or more bound inputs changed")
    return current


def apply_legacy_adoption(github: GitHub, root: Path, plan: LegacyAdoptionPlan,
                          approval_comment_id: int) -> dict[str, Any]:
    """Append Adoption then legacy Gate after current exact Owner-grant readback."""
    plan.validate()
    if plan.value["schema"] != PLAN_SCHEMA:
        raise LegacyAdoptionError("apply requires a new V2 risk-bound Owner plan")
    root = Path(root).resolve()
    _fresh_plan(github, root, plan)
    approval = verify_owner_approval(github, plan, approval_comment_id)
    _require_owner_writer(github, plan)
    state = _read_adoption_state(github, plan.value["issue_number"])
    if state is not None:
        if (state["plan"].value != plan.value or state["approval_comment_id"] != approval_comment_id):
            raise LegacyAdoptionError("existing partial/completed Adoption belongs to another plan or approval")
        if state["gate_selection"] is not None:
            return {"status": "NOOP", "risk_status": "KNOWN_RISK_ACCEPTED_BY_OWNER",
                    "accepted_risks": list(ACCEPTED_RISK_IDS),
                    "adoption_comment_id": state["adoption_comment_id"],
                    "gate_comment_id": state["gate_comment_id"], "plan_sha256": plan.sha256}
    else:
        adoption_payload = {
            "approval_comment_id": approval_comment_id,
            "plan": plan.value,
            "plan_sha256": plan.sha256,
            "planned_gate_payload_sha256": plan.value["planned_gate_payload_sha256"],
            "schema": ADOPTION_SCHEMA,
        }
        # Check current state and exact grant again immediately before the first append.
        _fresh_plan(github, root, plan)
        verify_owner_approval(github, plan, approval_comment_id)
        _require_owner_writer(github, plan)
        state = _read_adoption_state(github, plan.value["issue_number"])
        if state is not None:
            raise LegacyAdoptionError("concurrent or partial Adoption appeared before the first append")
        adoption_id, _adoption_body = _append_record(
            github, plan.value["issue_number"], ADOPTION_SCHEMA, adoption_payload,
        )
        state = _read_adoption_state(github, plan.value["issue_number"])
        if (state is None or state["adoption_comment_id"] != adoption_id
                or state["adoption_payload"] != adoption_payload or state["gate_selection"] is not None):
            raise LegacyAdoptionError("Adoption did not pass full readback; no Gate was appended")

    assert state is not None
    # A partial record can proceed only after rechecking the same immutable plan and grant.
    _fresh_plan(github, root, plan)
    verify_owner_approval(github, plan, approval_comment_id)
    _require_owner_writer(github, plan)
    final_state = _read_adoption_state(github, plan.value["issue_number"])
    if (final_state is None or final_state["plan"].value != plan.value
            or final_state["approval_comment_id"] != approval_comment_id
            or final_state["gate_selection"] is not None):
        raise LegacyAdoptionError("Adoption state changed before the Gate append")
    gate = LegacyGateSelection(
        repository=plan.value["repository"], issue_number=plan.value["issue_number"],
        policy_version=LEGACY_ADOPTED_POLICY,
        selected_at=plan.value["planned_gate_payload"]["selected_at"],
        adoption_comment_id=final_state["adoption_comment_id"],
        adoption_record_sha256=final_state["adoption_record_sha256"],
        selection_sha256=plan.value["planned_gate_payload_sha256"],
    ).validate()
    gate_id, _gate_body = _append_record(
        github, plan.value["issue_number"], LEGACY_GATE_SCHEMA, gate.payload(),
    )
    complete = _read_adoption_state(github, plan.value["issue_number"])
    if (complete is None or complete["gate_comment_id"] != gate_id
            or complete["plan"].value != plan.value or complete["gate_selection"] != gate):
        raise LegacyAdoptionError("Adoption/Gate pair failed complete readback")
    return {"status": "ADOPTED", "risk_status": "KNOWN_RISK_ACCEPTED_BY_OWNER",
            "accepted_risks": list(ACCEPTED_RISK_IDS),
            "adoption_comment_id": complete["adoption_comment_id"],
            "gate_comment_id": gate_id, "plan_sha256": plan.sha256}


def verify_legacy_gate_selection(github: GitHub, root: Path, issue_number: int,
                                 gate_comment_id: int, selection: LegacyGateSelection) -> None:
    """Verify historical Owner grant, ADC, Activation prefix, Binding, and Gate pair."""
    state = _read_adoption_state(github, issue_number)
    if (state is None or state["gate_comment_id"] != gate_comment_id
            or state["gate_selection"] != selection):
        raise LegacyAdoptionError("legacy Gate does not resolve to one exact Adoption record")
    plan = state["plan"]
    approval_id = state["approval_comment_id"]
    verify_owner_approval(github, plan, approval_id)
    repo_id, owner_id = _repository_identity(github)
    if repo_id != plan.value["repository_id"] or owner_id != plan.value["owner_id"]:
        raise LegacyAdoptionError("legacy Adoption repository Owner identity changed")
    issue = _exact_issue(github, issue_number)
    labels, kind, _phase, _attention = _issue_labels(issue)
    if (issue.get("id") != plan.value["issue_id"]
            or _timestamp(issue["created_at"], "Issue creation") != plan.value["issue_created_at"]
            or kind.value != plan.value["issue_kind"]):
        raise LegacyAdoptionError("legacy Adoption Issue identity or kind changed")
    try:
        verified = verify_adc_generation(
            github, issue_number, plan.value["adc_comment_id"], plan.value["adc_sha256"], state="approved",
        )
    except ADCError as exc:
        raise LegacyAdoptionError(f"legacy Adoption ADC generation is no longer verifiable: {exc}") from exc
    if verified.pointer.state != "approved":
        raise LegacyAdoptionError("legacy Adoption ADC generation was not approved")
    try:
        history = read_consumer_activation_history(
            github, github.repo, plan.value["activation_issue_number"],
        )
    except (ConsumerActivationError, GitHubError) as exc:
        raise LegacyAdoptionError(f"legacy Adoption Activation history is invalid: {exc}") from exc
    prefix_rows = plan.value["activation_prefix"]["records"]
    actual_rows = [{"comment_id": cid, "record_sha256": record.sha256}
                   for record, cid in history[:len(prefix_rows)]]
    actual_prefix = _activation_prefix(plan.value["activation_issue_number"], history[:len(prefix_rows)])
    if actual_rows != prefix_rows or actual_prefix != plan.value["activation_prefix"]:
        raise LegacyAdoptionError("legacy Adoption Activation prefix is stale or changed")
    if (_parse_time(issue["created_at"], "Issue creation")
            > min(_parse_time(record.activated_at, "Activation")
                  for record, _comment_id in history[:len(prefix_rows)])):
        raise LegacyAdoptionError("adopted Issue was not created before the first Activation in its prefix")
    if plan.value["binding"] is not None:
        path = execution_binding_path(Path(root).resolve(), issue_number)
        if path_has_symlink(path, root=Path(root).resolve()):
            raise LegacyAdoptionError("current ExecutionBinding path traverses a symlink")
        try:
            binding_history = read_binding_history(path)
        except (ExecutionError, OSError) as exc:
            raise LegacyAdoptionError(f"current ExecutionBinding history is invalid: {exc}") from exc
        expected_generations = plan.value["binding"]["generations"]
        actual_generations = [{"adc_comment_id": row.adc_comment_id, "binding_sha256": binding_digest(row)}
                              for row in binding_history]
        if (actual_generations[:len(expected_generations)] != expected_generations
                or len(actual_generations) < len(expected_generations)):
            raise LegacyAdoptionError("adopted frozen ExecutionBinding history prefix changed")
        if (len(actual_generations) == len(expected_generations)
                and hashlib.sha256(path.read_bytes()).hexdigest() != plan.value["binding"]["history_sha256"]):
            raise LegacyAdoptionError("single-generation ExecutionBinding file digest changed")
    try:
        remote_branch = github.branch(plan.value["remote_head_ref"])
    except GitHubError as exc:
        raise LegacyAdoptionError(f"adopted remote branch is unavailable: {exc}") from exc
    current_remote = (remote_branch.get("commit", {}).get("sha")
                      if isinstance(remote_branch, dict) and isinstance(remote_branch.get("commit"), dict)
                      else None)
    if (not isinstance(remote_branch, dict)
            or remote_branch.get("name") != plan.value["remote_head_ref"]
            or not isinstance(current_remote, str) or not SHA40.fullmatch(current_remote)):
        raise LegacyAdoptionError("adopted remote branch identity is invalid")
    try:
        if not is_ancestor(Path(root).resolve(), plan.value["remote_head_sha"], current_remote):
            raise LegacyAdoptionError("current remote branch no longer descends from the adopted HEAD")
    except GitError as exc:
        raise LegacyAdoptionError(f"cannot verify adopted HEAD ancestry: {exc}") from exc


def read_legacy_reset_plan(path: Path) -> LegacyResetPlan:
    location = Path(path)
    if location.is_symlink() or not location.is_file():
        raise LegacyAdoptionError("reset plan path must be a regular non-symlink file")
    try:
        raw = location.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyAdoptionError("reset plan file is not readable canonical JSON") from exc
    if _canonical(value) + b"\n" != raw:
        raise LegacyAdoptionError("reset plan file is not canonical JSON with one trailing newline")
    return LegacyResetPlan.from_payload(value)


def write_legacy_reset_plan(path: Path, plan: LegacyResetPlan) -> None:
    plan.validate()
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise LegacyAdoptionError("reset plan output already exists; refusing to overwrite an approval input")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical(plan.value) + b"\n")


def build_legacy_reset_plan(github: GitHub, root: Path, issue_number: int, *,
                            generated_at: str | None = None) -> LegacyResetPlan | None:
    """Plan a separately approved return to requirements; Requirements is a no-op."""
    issue = _exact_issue(github, issue_number)
    labels, kind, phase, attention = _issue_labels(issue)
    reset_state = _read_reset_state(github, issue_number)
    if phase is Phase.REQUIREMENTS:
        if reset_state["intent_comment_id"] is not None:
            if reset_state["applied_comment_id"] is None or reset_state["plan"].value["target_labels"] != labels:
                raise LegacyAdoptionError("requirements phase has unresolved or conflicting reset history")
        return None
    if reset_state["intent_comment_id"] is not None:
        raise LegacyAdoptionError("an earlier reset Intent remains unresolved")
    if attention:
        raise LegacyAdoptionError("conflicting attention/Owner-decision labels block reset to requirements")
    if phase is Phase.USER_REVIEW:
        raise LegacyAdoptionError("a User Review decision must not be reset to requirements")
    if kind is IssueKind.CHILD:
        try:
            validate_native_issue_graph(github, issue_number)
        except (IssueGraphError, GitHubError) as exc:
            raise LegacyAdoptionError(f"parent/dependency validation blocks reset: {exc}") from exc
    try:
        gate_id, selection, _gate_body = _read_gate_selection_if_present(github, issue_number)
    except GatePolicyError as exc:
        raise LegacyAdoptionError(f"Gate history is invalid: {exc}") from exc
    if not isinstance(selection, LegacyGateSelection):
        raise LegacyAdoptionError("separate reset requires a verified legacy Gate")
    state = _read_adoption_state(github, issue_number)
    if (state is None or state["gate_comment_id"] != gate_id
            or state["gate_selection"] != selection):
        raise LegacyAdoptionError("reset requires a complete authenticated Adoption/Gate pair")
    # Validate the exact earlier Owner grant and current Activation/ADC/Binding evidence.
    verify_legacy_gate_selection(github, root, issue_number, gate_id, selection)
    repository_id, owner_id = _repository_identity(github)
    target_labels = [label for label in labels if not label.startswith(("phase:", "attention:"))]
    target_labels.append(f"phase:{Phase.REQUIREMENTS.value}")
    target_labels = sorted(target_labels)
    stamp = _timestamp(generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "reset plan generated")
    payload = {
        "adoption_comment_id": state["adoption_comment_id"],
        "adoption_record_sha256": state["adoption_record_sha256"],
        "generated_at": stamp,
        "issue_created_at": _timestamp(issue["created_at"], "Issue creation"),
        "issue_id": issue["id"],
        "issue_kind": kind.value,
        "issue_labels": labels,
        "issue_number": issue_number,
        "owner_id": owner_id,
        "phase": phase.value,
        "repository": github.repo,
        "repository_id": repository_id,
        "schema": RESET_PLAN_SCHEMA,
        "target_labels": target_labels,
    }
    plan = {**payload, "plan_sha256": _digest(payload)}
    return LegacyResetPlan(plan).validate()


def _fresh_reset_plan(github: GitHub, root: Path, plan: LegacyResetPlan) -> LegacyResetPlan:
    current = build_legacy_reset_plan(
        github, root, plan.value["issue_number"], generated_at=plan.value["generated_at"],
    )
    if current is None or current.value != plan.value:
        raise LegacyAdoptionError("reset plan is stale; one or more bound inputs changed")
    return current


def _verify_reset_subject(github: GitHub, root: Path, plan: LegacyResetPlan, *,
                          expected_labels: list[str], expected_phase: Phase,
                          validate_dependencies: bool) -> dict[str, Any]:
    issue_number = plan.value["issue_number"]
    issue = _exact_issue(github, issue_number)
    labels, kind, phase, attention = _issue_labels(issue)
    repository_id, owner_id = _repository_identity(github)
    if (issue.get("id") != plan.value["issue_id"]
            or _timestamp(issue["created_at"], "Issue creation") != plan.value["issue_created_at"]
            or labels != expected_labels or kind.value != plan.value["issue_kind"]
            or phase is not expected_phase or attention
            or repository_id != plan.value["repository_id"] or owner_id != plan.value["owner_id"]):
        raise LegacyAdoptionError("Issue identity, labels, Owner, or phase changed during reset")
    try:
        gate_id, selection, _gate_body = _read_gate_selection_if_present(github, issue_number)
    except GatePolicyError as exc:
        raise LegacyAdoptionError(f"reset legacy Gate readback failed: {exc}") from exc
    if not isinstance(selection, LegacyGateSelection):
        raise LegacyAdoptionError("reset requires one verified legacy Gate")
    adoption = _read_adoption_state(github, issue_number)
    if (adoption is None or adoption["gate_comment_id"] != gate_id
            or adoption["adoption_comment_id"] != plan.value["adoption_comment_id"]
            or adoption["adoption_record_sha256"] != plan.value["adoption_record_sha256"]
            or adoption["gate_selection"] != selection):
        raise LegacyAdoptionError("reset plan no longer matches the authenticated Adoption/Gate history")
    try:
        verify_legacy_gate_selection(github, root, issue_number, gate_id, selection)
    except LegacyAdoptionError as exc:
        raise LegacyAdoptionError(f"reset predecessor Gate evidence is invalid: {exc}") from exc
    if validate_dependencies and kind is IssueKind.CHILD:
        try:
            validate_native_issue_graph(github, issue_number)
        except (IssueGraphError, GitHubError) as exc:
            raise LegacyAdoptionError(f"parent/dependency validation blocks reset: {exc}") from exc
    return issue


def _read_reset_state(github: GitHub, issue_number: int) -> dict[str, Any]:
    try:
        comments = github.issue_comments(issue_number)
    except GitHubError as exc:
        raise LegacyAdoptionError(f"reset history readback failed: {exc}") from exc
    intents = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
               and row["body"].startswith(RESET_INTENT_MARKER)]
    applied = [row for row in comments if isinstance(row, dict) and isinstance(row.get("body"), str)
               and row["body"].startswith(RESET_APPLIED_MARKER)]
    if len(intents) > 1 or len(applied) > 1 or (applied and not intents):
        raise LegacyAdoptionError("reset Intent/Applied history is duplicated or incomplete")
    if not intents:
        return {"intent_comment_id": None, "intent_payload": None, "plan": None,
                "applied_comment_id": None, "applied_payload": None}
    intent_row = intents[0]
    intent_id = _positive_id(intent_row.get("id"), "reset Intent comment ID")
    intent_payload = _record_payload(intent_row.get("body"), RESET_INTENT_SCHEMA)
    if (set(intent_payload) != {"approval_comment_id", "plan", "plan_sha256", "schema"}
            or intent_payload.get("schema") != RESET_INTENT_SCHEMA):
        raise LegacyAdoptionError("reset Intent has unknown or missing fields")
    plan = LegacyResetPlan.from_payload(intent_payload["plan"])
    if plan.value["issue_number"] != issue_number or intent_payload.get("plan_sha256") != plan.sha256:
        raise LegacyAdoptionError("reset Intent plan identity is invalid")
    approval_id = _positive_id(intent_payload.get("approval_comment_id"), "reset Owner approval Comment ID")
    if intent_id <= approval_id:
        raise LegacyAdoptionError("reset Intent does not follow its Owner approval in append-only order")
    _read_comment_direct_list_direct(
        github, issue_number, intent_id, expected_body=_body(RESET_INTENT_SCHEMA, intent_payload),
    )
    applied_id = None
    applied_payload = None
    if applied:
        applied_id = _positive_id(applied[0].get("id"), "reset Applied comment ID")
        applied_payload = _record_payload(applied[0].get("body"), RESET_APPLIED_SCHEMA)
        if (set(applied_payload) != {"approval_comment_id", "intent_comment_id", "plan_sha256", "schema"}
                or applied_payload.get("schema") != RESET_APPLIED_SCHEMA
                or applied_payload.get("intent_comment_id") != intent_id
                or applied_payload.get("plan_sha256") != plan.sha256
                or applied_payload.get("approval_comment_id") != intent_payload["approval_comment_id"]):
            raise LegacyAdoptionError("reset Applied record does not link to its exact Intent")
        if applied_id <= intent_id:
            raise LegacyAdoptionError("reset Applied record does not follow its Intent in append-only order")
        _read_comment_direct_list_direct(
            github, issue_number, applied_id, expected_body=_body(RESET_APPLIED_SCHEMA, applied_payload),
        )
    return {"intent_comment_id": intent_id, "intent_payload": intent_payload,
            "plan": plan, "applied_comment_id": applied_id, "applied_payload": applied_payload}


def apply_legacy_reset(github: GitHub, root: Path, plan: LegacyResetPlan,
                       approval_comment_id: int) -> dict[str, Any]:
    """Apply a separately authorized return to requirements with one label PUT."""
    plan.validate()
    root = Path(root).resolve()
    verify_owner_approval(github, plan, approval_comment_id, operation="RESET_TO_REQUIREMENTS")
    state = _read_reset_state(github, plan.value["issue_number"])
    issue = _exact_issue(github, plan.value["issue_number"])
    labels, _kind, current_phase, _attention = _issue_labels(issue)
    if state["applied_comment_id"] is not None:
        if state["plan"].value != plan.value or state["intent_payload"]["approval_comment_id"] != approval_comment_id:
            raise LegacyAdoptionError("existing reset Applied record belongs to another plan or approval")
        _verify_reset_subject(github, root, plan, expected_labels=plan.value["target_labels"],
                              expected_phase=Phase.REQUIREMENTS, validate_dependencies=False)
        return {"status": "NOOP", "intent_comment_id": state["intent_comment_id"],
                "applied_comment_id": state["applied_comment_id"], "plan_sha256": plan.sha256}
    if state["intent_comment_id"] is not None:
        if state["plan"].value != plan.value or state["intent_payload"]["approval_comment_id"] != approval_comment_id:
            raise LegacyAdoptionError("existing reset Intent belongs to another plan or approval")
        if labels == plan.value["target_labels"] and current_phase is Phase.REQUIREMENTS:
            _verify_reset_subject(github, root, plan, expected_labels=plan.value["target_labels"],
                                  expected_phase=Phase.REQUIREMENTS, validate_dependencies=False)
            verify_owner_approval(github, plan, approval_comment_id, operation="RESET_TO_REQUIREMENTS")
            current_state = _read_reset_state(github, plan.value["issue_number"])
            if (current_state["intent_comment_id"] != state["intent_comment_id"]
                    or current_state["intent_payload"] != state["intent_payload"]
                    or current_state["applied_comment_id"] is not None):
                raise LegacyAdoptionError("reset history changed during read-only recovery")
            latest = _exact_issue(github, plan.value["issue_number"])
            latest_labels, _kind, latest_phase, _attention = _issue_labels(latest)
            if latest_labels != plan.value["target_labels"] or latest_phase is not Phase.REQUIREMENTS:
                raise LegacyAdoptionError("reset Issue changed before Applied recovery")
            applied_payload = {"approval_comment_id": approval_comment_id,
                               "intent_comment_id": state["intent_comment_id"],
                               "plan_sha256": plan.sha256, "schema": RESET_APPLIED_SCHEMA}
            applied_id, _ = _append_record(
                github, plan.value["issue_number"], RESET_APPLIED_SCHEMA, applied_payload,
            )
            completed = _read_reset_state(github, plan.value["issue_number"])
            if (completed["applied_comment_id"] != applied_id
                    or completed["applied_payload"] != applied_payload):
                raise LegacyAdoptionError("reset Applied recovery failed full readback")
            return {"status": "APPLIED", "intent_comment_id": state["intent_comment_id"],
                    "applied_comment_id": applied_id, "plan_sha256": plan.sha256,
                    "label_write": "RECOVERED_BY_READBACK"}
        raise LegacyAdoptionError("reset Intent exists without a verified phase write; refusing a second PUT")
    _fresh_reset_plan(github, root, plan)
    verify_owner_approval(github, plan, approval_comment_id, operation="RESET_TO_REQUIREMENTS")
    state = _read_reset_state(github, plan.value["issue_number"])
    if state["intent_comment_id"] is not None:
        raise LegacyAdoptionError("concurrent reset Intent appeared before the phase write")
    issue = _verify_reset_subject(github, root, plan, expected_labels=plan.value["issue_labels"],
                                  expected_phase=Phase(plan.value["phase"]), validate_dependencies=True)
    labels, _kind, current_phase, _attention = _issue_labels(issue)
    if labels != plan.value["issue_labels"] or current_phase.value != plan.value["phase"]:
        raise LegacyAdoptionError("Issue phase/labels changed after reset plan approval")
    intent_payload = {"approval_comment_id": approval_comment_id, "plan": plan.value,
                      "plan_sha256": plan.sha256, "schema": RESET_INTENT_SCHEMA}
    intent_id, _intent_body = _append_record(
        github, plan.value["issue_number"], RESET_INTENT_SCHEMA, intent_payload,
    )
    _verify_reset_subject(github, root, plan, expected_labels=plan.value["issue_labels"],
                          expected_phase=Phase(plan.value["phase"]), validate_dependencies=True)
    verify_owner_approval(github, plan, approval_comment_id, operation="RESET_TO_REQUIREMENTS")
    current_reset_state = _read_reset_state(github, plan.value["issue_number"])
    if (current_reset_state["intent_comment_id"] != intent_id
            or current_reset_state["intent_payload"] != intent_payload
            or current_reset_state["applied_comment_id"] is not None):
        raise LegacyAdoptionError("reset history changed before the phase label write")
    latest = _exact_issue(github, plan.value["issue_number"])
    latest_labels, latest_kind, latest_phase, latest_attention = _issue_labels(latest)
    if (latest["id"] != plan.value["issue_id"] or latest_labels != plan.value["issue_labels"]
            or latest_kind.value != plan.value["issue_kind"] or latest_phase.value != plan.value["phase"]
            or latest_attention):
        raise LegacyAdoptionError("Issue changed after reset Intent; no phase label was written")
    if latest_kind is IssueKind.CHILD:
        try:
            validate_native_issue_graph(github, plan.value["issue_number"])
        except (IssueGraphError, GitHubError) as exc:
            raise LegacyAdoptionError(f"parent/dependency state changed before reset: {exc}") from exc
    try:
        github.replace_issue_labels(plan.value["issue_number"], plan.value["target_labels"])
    except GitHubError:
        # A write response can be lost. Read once and never issue a second PUT here.
        pass
    final_issue = _exact_issue(github, plan.value["issue_number"])
    final_labels, _final_kind, final_phase, _final_attention = _issue_labels(final_issue)
    if final_labels != plan.value["target_labels"] or final_phase is not Phase.REQUIREMENTS:
        raise LegacyAdoptionError("reset label write is unconfirmed; no automatic retry was attempted")
    _verify_reset_subject(github, root, plan, expected_labels=plan.value["target_labels"],
                          expected_phase=Phase.REQUIREMENTS, validate_dependencies=False)
    verify_owner_approval(github, plan, approval_comment_id, operation="RESET_TO_REQUIREMENTS")
    confirmed_intent = _read_reset_state(github, plan.value["issue_number"])
    if (confirmed_intent["intent_comment_id"] != intent_id
            or confirmed_intent["intent_payload"] != intent_payload
            or confirmed_intent["applied_comment_id"] is not None):
        raise LegacyAdoptionError("reset Intent changed before Applied append")
    applied_payload = {"approval_comment_id": approval_comment_id, "intent_comment_id": intent_id,
                       "plan_sha256": plan.sha256, "schema": RESET_APPLIED_SCHEMA}
    applied_id, _ = _append_record(
        github, plan.value["issue_number"], RESET_APPLIED_SCHEMA, applied_payload,
    )
    completed = _read_reset_state(github, plan.value["issue_number"])
    if (completed["intent_comment_id"] != intent_id or completed["applied_comment_id"] != applied_id
            or completed["applied_payload"] != applied_payload):
        raise LegacyAdoptionError("reset Intent/Applied pair failed complete readback")
    return {"status": "APPLIED", "intent_comment_id": intent_id,
            "applied_comment_id": applied_id, "plan_sha256": plan.sha256, "label_write": "VERIFIED"}
