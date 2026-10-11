"""Issue workflow phases and separate waiting/blocked attention states."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping


class PhaseError(ValueError):
    pass


class Phase(str, Enum):
    REQUIREMENTS = "requirements"
    SPECIFICATION = "specification"
    DESIGN = "design"
    READY = "ready"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    INTEGRATION = "integration"
    USER_REVIEW = "user-review"
    CLOSED = "closed"


class IssueKind(str, Enum):
    SINGLE = "single"
    CHILD = "child"
    PARENT = "parent"


class Attention(str, Enum):
    WAITING_USER = "waiting-user"
    BLOCKED = "blocked"
    WAITING_DEPENDENCY = "waiting-dependency"


@dataclass(frozen=True)
class PhaseState:
    issue_number: int
    kind: IssueKind
    phase: Phase
    attention: frozenset[Attention] = frozenset()


def parse_phase_labels(labels: list[str] | tuple[str, ...]) -> Phase:
    if not isinstance(labels, (list, tuple)) or any(not isinstance(x, str) for x in labels):
        raise PhaseError("Issue labels must be a list of strings")
    phases = [label.removeprefix("phase:") for label in labels if label.startswith("phase:")]
    if len(phases) != 1:
        raise PhaseError("an open Issue must have exactly one phase:* label")
    try:
        return Phase(phases[0])
    except ValueError as exc:
        raise PhaseError("Issue has an unknown phase label") from exc


def parse_attention_labels(labels: list[str] | tuple[str, ...]) -> frozenset[Attention]:
    if not isinstance(labels, (list, tuple)) or any(not isinstance(x, str) for x in labels):
        raise PhaseError("Issue labels must be a list of strings")
    result: set[Attention] = set()
    for label in labels:
        if label.startswith("attention:"):
            try:
                result.add(Attention(label.removeprefix("attention:")))
            except ValueError as exc:
                raise PhaseError("Issue has an unknown attention:* label") from exc
    if len(result) > 1:
        raise PhaseError("Issue may have at most one attention:* label")
    return frozenset(result)


def set_attention(state: PhaseState, attention: Attention | None) -> PhaseState:
    if not isinstance(state, PhaseState):
        raise PhaseError("workflow state is invalid")
    if (not isinstance(state.kind, IssueKind) or not isinstance(state.phase, Phase)
            or any(not isinstance(item, Attention) for item in state.attention)):
        raise PhaseError("workflow state contains an invalid phase or attention value")
    if attention is not None and not isinstance(attention, Attention):
        raise PhaseError("attention state is invalid")
    return replace(state, attention=frozenset(() if attention is None else (attention,)))


def advance(
    state: PhaseState,
    target: Phase,
    *,
    skip_reasons: Mapping[str, str] | None = None,
    readiness_passed: bool = False,
    integration_passed: bool = False,
    issue_graph_validated: bool = False,
    changes_requested: bool = False,
    user_approved: bool = False,
    merged: bool = False,
    all_children_merged: bool = False,
) -> PhaseState:
    if (not isinstance(state, PhaseState) or not isinstance(target, Phase)
            or not isinstance(state.kind, IssueKind) or not isinstance(state.phase, Phase)):
        raise PhaseError("workflow state and target phase must be valid")
    if type(state.issue_number) is not int or state.issue_number < 1:
        raise PhaseError("Issue number must be a positive integer")
    if (not isinstance(state.attention, frozenset)
            or any(not isinstance(item, Attention) for item in state.attention)
            or len(state.attention) > 1):
        raise PhaseError("Issue must have at most one valid attention state")
    if state.attention:
        raise PhaseError("clear the waiting or blocked attention state before advancing the phase")
    if state.phase is Phase.CLOSED:
        raise PhaseError("closed Issue phase is terminal")
    skips = skip_reasons or {}
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in skips.items()):
        raise PhaseError("phase skip reasons must map phase names to text")
    if set(skips) - {"specification", "design"}:
        raise PhaseError("only optional specification and design phases may be skipped")
    if any(not value.strip() for value in skips.values()):
        raise PhaseError("a skipped optional phase requires a non-empty reason")

    if state.kind is IssueKind.PARENT and state.phase is Phase.REQUIREMENTS and target is Phase.READY:
        if issue_graph_validated is not True:
            raise PhaseError("parent issue graph must be validated before the parent enters ready")
        return replace(state, phase=target)

    if state.kind in {IssueKind.SINGLE, IssueKind.CHILD} and target is Phase.READY and state.phase is Phase.REQUIREMENTS:
        if not all(skips.get(name, "").strip() for name in ("specification", "design")):
            raise PhaseError("skipping specification and design requires a reason for each phase")
        return replace(state, phase=target)
    if state.kind in {IssueKind.SINGLE, IssueKind.CHILD} and target is Phase.DESIGN and state.phase is Phase.REQUIREMENTS:
        if not skips.get("specification", "").strip():
            raise PhaseError("design cannot be finalized before specification without a reason that specification is unchanged")
        return replace(state, phase=target)
    if state.kind in {IssueKind.SINGLE, IssueKind.CHILD} and target is Phase.READY and state.phase is Phase.SPECIFICATION:
        if not skips.get("design", "").strip():
            raise PhaseError("skipping design requires an explicit reason")
        return replace(state, phase=target)

    allowed = {(Phase.READY, Phase.EXECUTION)}
    if state.kind in {IssueKind.SINGLE, IssueKind.CHILD}:
        allowed.update({
            (Phase.REQUIREMENTS, Phase.SPECIFICATION),
            (Phase.SPECIFICATION, Phase.DESIGN),
            (Phase.DESIGN, Phase.READY),
            (Phase.EXECUTION, Phase.VERIFICATION),
            (Phase.VERIFICATION, Phase.USER_REVIEW),
            (Phase.USER_REVIEW, Phase.EXECUTION),
            (Phase.USER_REVIEW, Phase.CLOSED),
        })
    if state.kind is IssueKind.PARENT:
        allowed.update({
            (Phase.READY, Phase.EXECUTION),
            (Phase.EXECUTION, Phase.INTEGRATION),
            (Phase.INTEGRATION, Phase.USER_REVIEW),
            (Phase.USER_REVIEW, Phase.CLOSED),
        })
    pair = (state.phase, target)
    if pair not in allowed:
        raise PhaseError(f"invalid {state.kind.value} transition {state.phase.value} -> {target.value}")

    if pair == (Phase.VERIFICATION, Phase.USER_REVIEW) and readiness_passed is not True:
        raise PhaseError("Review Readiness must pass before User Review")
    if pair == (Phase.INTEGRATION, Phase.USER_REVIEW) and integration_passed is not True:
        raise PhaseError("parent Integration must pass before User Review")
    if pair == (Phase.USER_REVIEW, Phase.EXECUTION) and changes_requested is not True:
        raise PhaseError("returning to execution requires an in-scope changes_requested decision")
    if pair == (Phase.USER_REVIEW, Phase.CLOSED):
        if user_approved is not True:
            raise PhaseError("closing an Issue requires explicit user approval")
        if state.kind is IssueKind.PARENT:
            if all_children_merged is not True:
                raise PhaseError("parent Issue cannot close until every child is merged and closed")
        elif merged is not True:
            raise PhaseError("child Issue cannot close until its PR is merged")
    return replace(state, phase=target)
