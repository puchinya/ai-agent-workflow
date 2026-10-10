"""Namespace-based command-line interface for P-ASES."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .adc import ADCError, parse_adc, publish_adc, restore_adc, verify_adc
from .git import GitError, discover_repository
from .github import GitHub, GitHubError
from .issue_graph import (
    IssueGraphError,
    load_split_plan,
    split_issue,
    validate_native_issue_graph,
    validate_split,
)
from .phases import IssueKind, Phase, PhaseError, PhaseState, advance, parse_attention_labels, parse_phase_labels


class CLIError(RuntimeError):
    pass


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _repo_root(value: str | None) -> Path:
    start = Path(value or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise CLIError("could not find repository root (.git)")


def _gh(root: Path) -> GitHub:
    return GitHub(discover_repository(root))


def _positive_number(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("Issue number must be a positive integer")
    return int(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m p_ases")
    namespaces = parser.add_subparsers(dest="namespace", required=True)

    adc = namespaces.add_parser("adc", help="validate and manage Agent Development Contracts")
    adc_commands = adc.add_subparsers(dest="verb", required=True)
    validate = adc_commands.add_parser("validate")
    validate.add_argument("issue", type=_positive_number)
    validate.add_argument("source", type=Path)
    validate.add_argument("--repo", help="repository owner/name; defaults to origin")
    publish = adc_commands.add_parser("publish")
    publish.add_argument("issue", type=_positive_number)
    publish.add_argument("source", type=Path)
    publish.add_argument("--repo", help="repository owner/name; defaults to origin")
    publish.add_argument("--state", choices=("draft", "approved"), default="draft")
    publish.add_argument("--supersede", action="store_true")
    verify = adc_commands.add_parser("verify")
    verify.add_argument("issue", type=_positive_number)
    verify.add_argument("--repo", help="repository owner/name; defaults to origin")
    restore = adc_commands.add_parser("restore")
    restore.add_argument("issue", type=_positive_number)
    restore.add_argument("destination", type=Path)
    restore.add_argument("--repo", help="repository owner/name; defaults to origin")

    issue = namespaces.add_parser("issue", help="validate or decompose Issue graphs")
    issue_commands = issue.add_subparsers(dest="verb", required=True)
    validate_plan = issue_commands.add_parser("validate-split")
    validate_plan.add_argument("plan", type=Path)
    validate_plan.add_argument("--repo", help="repository owner/name; defaults to origin")
    split = issue_commands.add_parser("split")
    split.add_argument("plan", type=Path)
    split.add_argument("--repo", help="repository owner/name; defaults to origin")
    split.add_argument("--dry-run", action="store_true")
    advance_issue = issue_commands.add_parser("advance")
    advance_issue.add_argument("issue", type=_positive_number)
    advance_issue.add_argument("target", choices=tuple(phase.value for phase in Phase))
    advance_issue.add_argument("--repo", help="repository owner/name; defaults to origin")
    advance_issue.add_argument("--kind", choices=tuple(kind.value for kind in IssueKind), required=True)
    advance_issue.add_argument("--skip-phase", action="append", default=[], metavar="PHASE=REASON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _repo_root(getattr(args, "repo_root", None))
        repository = args.repo or discover_repository(root)
        if args.namespace == "adc":
            if args.verb == "validate":
                contract = parse_adc(args.source.read_bytes(), repository, args.issue)
                _json({"status": "VALID", "issue": args.issue, "repository": repository,
                       "adc_sha256": contract.sha256, "byte_length": contract.byte_length,
                       "requirement_ids": contract.requirement_ids, "child_key": contract.child_key})
                return 0
            github = GitHub(repository)
            if args.verb == "publish":
                pointer = publish_adc(github, args.issue, args.source.read_bytes(),
                                      state=args.state, explicitly_approved=(args.state == "approved"),
                                      supersede=args.supersede)
                _json({"status": "PUBLISHED", "issue": args.issue, "comment_id": pointer.comment_id,
                       "adc_sha256": pointer.sha256, "byte_length": pointer.byte_length,
                       "state": pointer.state})
                return 0
            if args.verb == "verify":
                verified = verify_adc(github, args.issue)
                _json({"status": "VERIFIED", "issue": args.issue,
                       "comment_id": verified.pointer.comment_id,
                       "adc_sha256": verified.pointer.sha256,
                       "byte_length": verified.pointer.byte_length,
                       "state": verified.pointer.state,
                       "requirement_ids": verified.contract.requirement_ids})
                return 0
            verified = restore_adc(github, args.issue, args.destination)
            _json({"status": "RESTORED", "issue": args.issue, "destination": str(args.destination),
                   "comment_id": verified.pointer.comment_id, "adc_sha256": verified.pointer.sha256,
                   "byte_length": verified.pointer.byte_length})
            return 0

        if args.verb == "advance":
            github = GitHub(repository)
            issue = github.issue(args.issue)
            if issue.get("state") != "open" or issue.get("pull_request") is not None:
                raise CLIError("Issue advance requires an open Issue, not a pull request")
            label_rows = issue.get("labels")
            if not isinstance(label_rows, list) or any(not isinstance(item, dict) for item in label_rows):
                raise CLIError("Issue label readback is invalid")
            labels = [item.get("name") for item in label_rows]
            if any(not isinstance(label, str) for label in labels):
                raise CLIError("Issue label readback contains an invalid name")
            phase = parse_phase_labels(labels)
            attention = parse_attention_labels(labels)
            skip_reasons: dict[str, str] = {}
            for raw in args.skip_phase:
                name, separator, reason = raw.partition("=")
                if not separator or name in skip_reasons or name not in {"specification", "design"}:
                    raise CLIError("--skip-phase must be a unique specification=reason or design=reason")
                skip_reasons[name] = reason
            kind = IssueKind(args.kind)
            target = Phase(args.target)
            graph_validated = False
            if kind is IssueKind.PARENT and phase is Phase.REQUIREMENTS and target is Phase.READY:
                validate_native_issue_graph(github, args.issue)
                graph_validated = True
            next_state = advance(PhaseState(args.issue, kind, phase, attention), target,
                                 skip_reasons=skip_reasons, issue_graph_validated=graph_validated)
            kept = [label for label in labels if not label.startswith(("phase:", "attention:"))]
            kept.append(f"phase:{next_state.phase.value}")
            kept.extend(f"attention:{item.value}" for item in sorted(next_state.attention, key=lambda x: x.value))
            github.replace_issue_labels(args.issue, kept)
            _json({"status": "ADVANCED", "issue": args.issue, "from": phase.value,
                   "to": next_state.phase.value, "attention": sorted(x.value for x in next_state.attention)})
            return 0

        parent_issue, parent_sha, requirement_ids, children = load_split_plan(args.plan, repository)
        order = validate_split(parent_issue, parent_sha, requirement_ids, children)
        if args.verb == "validate-split" or getattr(args, "dry_run", False):
            _json({"status": "VALID", "parent_issue": parent_issue, "parent_adc_sha256": parent_sha,
                   "requirement_ids": requirement_ids, "child_order": order,
                   "children": [{"key": child.key, "adc_sha256": child.adc_sha256,
                                 "assigned_requirement_ids": child.assigned_requirement_ids,
                                 "dependencies": child.dependencies} for child in children]})
            return 0
        created = split_issue(GitHub(repository), parent_issue, parent_sha, requirement_ids, children)
        _json({"status": "SPLIT", "parent_issue": parent_issue,
               "children": [{"key": child.key, "issue": child.number,
                             "issue_id": child.issue_id, "adc_sha256": child.adc_sha256}
                            for child in created]})
        return 0
    except (ADCError, GitError, GitHubError, IssueGraphError, PhaseError, CLIError, OSError, UnicodeError) as exc:
        print(f"p-ases: {exc}", file=sys.stderr)
        return 2
