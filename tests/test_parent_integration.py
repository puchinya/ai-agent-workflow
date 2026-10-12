from __future__ import annotations

from dataclasses import replace
import sys
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
import contextlib
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.integration import (
    IntegrationError, IntegrationGateEvidence, ParentGateEvidenceComment, evaluate_parent_integration,
)
from p_ases.github import GitHub, GitHubError
from p_ases.cli import (
    PARENT_ISSUE_CONTRACT_COMMIT, PARENT_ISSUE_CONTRACT_SOURCE,
    CLIError, _advance_parent_to_user_review, _delivery_parent, _delivery_parent_label_migration,
    _require_parent_user_review_phase, _load_parent_gate_evidence_from_github, _parent_adc_authority,
    _parent_contract_declaration, _parent_review_subject_from_integration, _publish_parent_gate_evidence,
)

EXPECTED = (27, 28, 29, 30, 31, 32)
DAG = {
    27: (),
    28: (27,),
    29: (27, 28),
    30: (27, 29),
    31: (29, 30),
    32: (27, 28, 29, 30, 31),
}
PR_NUMBER = {27: 33, 28: 36, 29: 34, 30: 35, 31: 37, 32: 38}
MAIN = "a" * 40


def integration_fixture():
    native = [{"id": 100 + number, "number": number} for number in EXPECTED]
    issues = [{"id": 100 + number, "number": number, "state": "closed"} for number in EXPECTED]
    blockers = {number: tuple(100 + dependency for dependency in DAG[number]) for number in EXPECTED}
    prs = []
    for number in EXPECTED:
        repository = {"full_name": "octo/repo"}
        prs.append({
            "number": PR_NUMBER[number], "state": "closed",
            "merged_at": f"2026-10-12T00:{number - 27:02d}:00Z",
            "merge_commit_sha": f"{number:040x}",
            "body": f"Implementation details\n\nCloses #{number}\n",
            "base": {"repo": repository, "ref": "main", "sha": MAIN},
            "head": {"repo": repository, "ref": f"pases/issue-{number}", "sha": f"{number + 100:040x}"},
        })
    return dict(
        repository="octo/repo", parent_issue_number=26,
        parent_adc_sha256="b" * 64, main_sha40=MAIN,
        expected_child_issue_numbers=EXPECTED,
        native_sub_issues=native, child_issue_rows=issues,
        actual_blockers_by_issue=blockers, declared_dependencies=DAG,
        merged_pr_rows=prs,
        merge_sha_ancestry={f"{number:040x}": True for number in EXPECTED},
        integration_verification=IntegrationGateEvidence(
            "verification", "octo/repo", 26, "b" * 64, MAIN, "PASS", "c" * 64, "issue-comment:801"),
        integration_acceptance=IntegrationGateEvidence(
            "acceptance", "octo/repo", 26, "b" * 64, MAIN, "PASS", "d" * 64, "issue-comment:802"),
    )


class ParentIntegrationTests(unittest.TestCase):
    def test_parent_review_subject_is_exact_integration_pass_and_phase_transition_is_guarded(self):
        passed = evaluate_parent_integration(**integration_fixture())
        subject = _parent_review_subject_from_integration(passed)
        self.assertEqual(subject.parent_issue_number, 26)
        self.assertEqual(subject.child_merge_set,
                         tuple((row.issue_number, row.merge_sha40) for row in passed.subject.children))
        self.assertEqual(subject.integration_evidence_digest, passed.sha256)

        blocked_inputs = integration_fixture()
        blocked_inputs["child_issue_rows"][-1]["state"] = "open"
        blocked = evaluate_parent_integration(**blocked_inputs)
        with self.assertRaisesRegex(CLIError, "only after complete parent Integration PASS"):
            _parent_review_subject_from_integration(blocked)

        class LabelGitHub:
            def __init__(self, labels):
                self.labels = labels
                self.replacements = []

            def issue(self, _number):
                return {"number": 26, "state": "open",
                        "labels": [{"name": label} for label in self.labels]}

            def replace_issue_labels(self, _number, labels):
                self.replacements.append(list(labels))
                self.labels = list(labels)

        github = LabelGitHub(["kind:parent", "phase:integration"])
        _advance_parent_to_user_review(github, 26)
        self.assertIn("phase:user-review", github.labels)
        self.assertEqual(len(github.replacements), 1)

        with self.assertRaisesRegex(CLIError, "no longer in unblocked User Review"):
            _require_parent_user_review_phase({"number": 26, "state": "open",
                                               "labels": [{"name": "kind:parent"},
                                                          {"name": "phase:integration"}]}, 26)
        _advance_parent_to_user_review(github, 26)
        self.assertEqual(len(github.replacements), 1)

        waiting = LabelGitHub(["kind:parent", "phase:integration", "attention:waiting-dependency"])
        with self.assertRaisesRegex(CLIError, "clear parent waiting/blocked attention"):
            _advance_parent_to_user_review(waiting, 26)
        self.assertEqual(waiting.replacements, [])

    def test_legacy_parent_label_migration_preflight_apply_retry_conflict_and_partial_failure(self):
        class LabelMigrationGitHub:
            def __init__(self, labels, *, fail_after_write=False):
                self.labels = list(labels)
                self.fail_after_write = fail_after_write
                self.fail_definition_name = None
                self.writes = 0
                self.definitions = {
                    "enhancement": {"name": "enhancement", "color": "a2eeef", "description": "New feature"}}

            def issue(self, _number):
                return {"number": 26, "state": "open", "pull_request": None,
                        "repository_url": "https://api.github.com/repos/octo/repo",
                        "labels": [{"name": label} for label in self.labels]}

            def repository_labels(self):
                return list(self.definitions.values())

            def create_repository_label(self, name, color, description):
                if self.fail_definition_name == name:
                    self.fail_definition_name = None
                    raise GitHubError("simulated response loss before label definition write")
                row = {"name": name, "color": color, "description": description}
                if name in self.definitions and self.definitions[name] != row:
                    raise GitHubError("conflicting label definition")
                self.definitions[name] = row
                return row

            def replace_issue_labels(self, _number, labels):
                self.writes += 1
                self.labels = list(labels)
                if self.fail_after_write:
                    self.fail_after_write = False
                    raise GitHubError("simulated response loss after GitHub write")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=False), "octo/repo", LabelMigrationGitHub(["enhancement"]))
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["labels_after"],
                         ["enhancement", "kind:parent", "phase:integration"])

        github = LabelMigrationGitHub(["enhancement"])
        for expected_status in ("MIGRATED", "ALREADY_MIGRATED"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = _delivery_parent_label_migration(
                    SimpleNamespace(issue=26, apply=True), "octo/repo", github)
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], expected_status)
        self.assertEqual(github.writes, 1)

        conflict = LabelMigrationGitHub(["enhancement", "phase:requirements"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", conflict)
        self.assertEqual(status, 2)
        self.assertIn("conflicts with an existing phase", json.loads(output.getvalue())["reasons"][0])
        self.assertEqual(conflict.writes, 0)

        partial = LabelMigrationGitHub(["enhancement"], fail_after_write=True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", partial)
        self.assertEqual(status, 2)
        self.assertEqual(partial.labels, ["enhancement", "kind:parent", "phase:integration"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", partial)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "ALREADY_MIGRATED")
        self.assertEqual(partial.writes, 1)

        definition_partial = LabelMigrationGitHub(["enhancement"])
        definition_partial.fail_definition_name = "phase:integration"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", definition_partial)
        self.assertEqual(status, 2)
        self.assertIn("response loss", json.loads(output.getvalue())["reasons"][0])
        self.assertIn("kind:parent", definition_partial.definitions)
        self.assertNotIn("phase:integration", definition_partial.definitions)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = _delivery_parent_label_migration(
                SimpleNamespace(issue=26, apply=True), "octo/repo", definition_partial)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "MIGRATED")
        self.assertEqual(definition_partial.labels,
                         ["enhancement", "kind:parent", "phase:integration"])

    def test_delivery_parent_requires_integration_and_approval_does_not_activate_or_merge(self):
        blocked_inputs = integration_fixture()
        blocked_inputs["child_issue_rows"][-1]["state"] = "open"
        blocked = evaluate_parent_integration(**blocked_inputs)
        args = SimpleNamespace(issue=26, verification_comment_id=None, acceptance_comment_id=None)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch("p_ases.cli._read_parent_integration", return_value=(blocked, Path(directory) / "blocked.json", None, None)), \
                patch("p_ases.cli._advance_parent_to_user_review") as advance_phase, \
                contextlib.redirect_stdout(output):
            status = _delivery_parent(args, "octo/repo", Path(directory), object())
            self.assertFalse((Path(directory) / ".p_ases" / "user-review" / "26").exists())
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())["parent_user_review"], "NOT_EVALUATED")
        advance_phase.assert_not_called()

        passed = evaluate_parent_integration(**integration_fixture())
        review_subject = _parent_review_subject_from_integration(passed)
        comment_row = {
            "id": 811, "created_at": "2026-10-13T00:00:00Z", "updated_at": "2026-10-13T00:00:00Z",
            "body": f"P-ASES-DECISION: APPROVED\nP-ASES-SUBJECT: {review_subject.sha256}",
            "user": {"id": 42, "login": "octocat", "type": "User"},
            "html_url": "https://github.com/octo/repo/issues/26#issuecomment-811",
        }
        parent_issue = {"number": 26, "state": "open", "pull_request": None,
                        "repository_url": "https://api.github.com/repos/octo/repo", "body": "parent",
                        "labels": [{"name": "kind:parent"}, {"name": "phase:user-review"}]}

        class ParentGitHub:
            def issue(self, _number):
                return parent_issue

            def issue_comments(self, _number):
                return [comment_row]

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with patch("p_ases.cli._read_parent_integration",
                       return_value=(passed, Path(directory) / "integration.json", None, None)), \
                    patch("p_ases.cli._parent_adc_authority", return_value=("b" * 64, object())), \
                    patch("p_ases.cli._advance_parent_to_user_review"), \
                    contextlib.redirect_stdout(output):
                status = _delivery_parent(args, "octo/repo", Path(directory), ParentGitHub())
            self.assertEqual(status, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "READY_FOR_EXPLICIT_ACTIVATION_APPROVAL")
            self.assertEqual(result["parent_user_review"], "APPROVED")
            self.assertFalse(result["merge_authorized"])
            self.assertFalse(result["activation_issued"])

    def test_legacy_parent_adc_reference_comes_from_current_approved_child_adc(self):
        content = (
            f"Parent contract: `{PARENT_ISSUE_CONTRACT_SOURCE}` at `{PARENT_ISSUE_CONTRACT_COMMIT}`\n"
            f"Parent ADC SHA-256: `{'f' * 64}`\n"
        ).encode()
        self.assertEqual(_parent_contract_declaration(content), (
            PARENT_ISSUE_CONTRACT_SOURCE, PARENT_ISSUE_CONTRACT_COMMIT, "f" * 64,
        ))

        pointer = SimpleNamespace(state="approved")
        approved_adc = SimpleNamespace(
            contract=SimpleNamespace(content=content),
            pointer=pointer,
        )

        class ContentGitHub:
            def __init__(self):
                self.calls = []

            def content_at_ref(self, path, ref):
                self.calls.append((path, ref))
                return b"pinned migration contract source\n"

        github = ContentGitHub()
        with patch("p_ases.cli.verify_adc", return_value=approved_adc) as verify:
            parent_digest, child_pointer = _parent_adc_authority(github)
        verify.assert_called_once_with(github, 31)
        self.assertEqual(parent_digest, "f" * 64)
        self.assertIs(child_pointer, pointer)
        self.assertEqual(github.calls, [(PARENT_ISSUE_CONTRACT_SOURCE, PARENT_ISSUE_CONTRACT_COMMIT)])

    def test_parent_contract_reference_must_be_unique_and_exactly_pinned(self):
        valid = (
            f"Parent contract: `{PARENT_ISSUE_CONTRACT_SOURCE}` at `{PARENT_ISSUE_CONTRACT_COMMIT}`\n"
            f"Parent ADC SHA-256: `{'f' * 64}`\n"
        ).encode()
        invalid = (
            valid + valid,
            valid.replace(PARENT_ISSUE_CONTRACT_COMMIT.encode(), b"0" * 40),
            valid.replace(b"f" * 64, b"not-a-digest"),
            b"\xff",
        )
        for content in invalid:
            with self.subTest(content=content[:50]), self.assertRaises(IntegrationError):
                _parent_contract_declaration(content)

    def test_parent_adc_authority_requires_approved_pointer_and_pinned_source(self):
        content = (
            f"Parent contract: `{PARENT_ISSUE_CONTRACT_SOURCE}` at `{PARENT_ISSUE_CONTRACT_COMMIT}`\n"
            f"Parent ADC SHA-256: `{'f' * 64}`\n"
        ).encode()
        for state, source in (("draft", b"present"), ("approved", b"")):
            with self.subTest(state=state, source=source):
                adc = SimpleNamespace(
                    contract=SimpleNamespace(content=content),
                    pointer=SimpleNamespace(state=state),
                )

                class ContentGitHub:
                    def content_at_ref(self, path, ref):
                        return source

                with patch("p_ases.cli.verify_adc", return_value=adc):
                    with self.assertRaises(IntegrationError):
                        _parent_adc_authority(ContentGitHub())

    def test_u07_six_closed_merged_children_and_exact_evidence_can_pass(self):
        result = evaluate_parent_integration(**integration_fixture())
        self.assertEqual(result.status, "PASS")
        self.assertEqual(tuple(row.issue_number for row in result.subject.children), EXPECTED)
        self.assertEqual(result.subject.expected_child_issue_numbers, EXPECTED)
        self.assertEqual(tuple(number for number, _dependencies in result.subject.declared_dependency_graph), EXPECTED)
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(len({child.merge_sha40 for child in result.subject.children}), 6)

    def test_u07_unmerged_or_open_child_blocks_without_guessing_provenance(self):
        for target in ("issue", "pr", "merge"):
            with self.subTest(target=target):
                kwargs = integration_fixture()
                if target == "issue":
                    kwargs["child_issue_rows"][-1]["state"] = "open"
                elif target == "pr":
                    kwargs["merged_pr_rows"][-1]["merged_at"] = None
                else:
                    kwargs["merged_pr_rows"][-1]["merge_commit_sha"] = "bad"
                self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_u07_unaccepted_or_missing_integration_evidence_blocks(self):
        for name, value in (
            ("integration_verification", None),
            ("integration_acceptance", None),
            ("integration_verification", IntegrationGateEvidence(
                "verification", "octo/repo", 26, "b" * 64, MAIN, "FAIL", "c" * 64, "issue-comment:803")),
            ("integration_acceptance", IntegrationGateEvidence(
                "acceptance", "octo/repo", 26, "b" * 64, "f" * 40, "PASS", "d" * 64, "issue-comment:804")),
        ):
            kwargs = integration_fixture()
            kwargs[name] = value
            self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_native_children_duplicates_and_missing_records_block(self):
        cases = (
            lambda a: a["native_sub_issues"].pop(),
            lambda a: a["native_sub_issues"].append(dict(a["native_sub_issues"][0])),
            lambda a: a["child_issue_rows"].pop(),
            lambda a: a["merged_pr_rows"].pop(),
            lambda a: a["merged_pr_rows"].append(dict(a["merged_pr_rows"][0])),
        )
        for mutate in cases:
            kwargs = integration_fixture()
            mutate(kwargs)
            self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_dependency_cycle_and_incomplete_graph_block(self):
        kwargs = integration_fixture()
        kwargs["declared_dependencies"] = {**DAG, 27: (32,)}
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")
        kwargs = integration_fixture()
        kwargs["actual_blockers_by_issue"][31] = (999,)
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_child_merge_timestamps_must_follow_the_declared_dependencies(self):
        kwargs = integration_fixture()
        kwargs["merged_pr_rows"][0]["merged_at"] = "2026-10-12T00:05:00Z"
        result = evaluate_parent_integration(**kwargs)
        self.assertEqual(result.status, "BLOCKED")
        self.assertTrue(any("merged before dependency" in reason for reason in result.reasons))

    def test_parent_closing_reference_is_rejected(self):
        kwargs = integration_fixture()
        kwargs["merged_pr_rows"][0]["body"] += "\nCloses #26\n"
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_merge_commit_must_be_confirmed_in_current_main(self):
        kwargs = integration_fixture()
        kwargs["merge_sha_ancestry"].pop(f"{27:040x}")
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")
        kwargs = integration_fixture()
        kwargs["merge_sha_ancestry"][f"{27:040x}"] = False
        self.assertEqual(evaluate_parent_integration(**kwargs).status, "BLOCKED")

    def test_parent_pass_record_cannot_claim_a_stale_child_merge(self):
        result = evaluate_parent_integration(**integration_fixture())
        children = (replace(result.subject.children[0], merge_sha_in_main=False), *result.subject.children[1:])
        invalid = replace(result, subject=replace(result.subject, children=children))
        with self.assertRaisesRegex(IntegrationError, "PASS lacks the exact child"):
            invalid.validate()

    def test_typed_parent_gate_evidence_round_trips_exact_subject(self):
        kwargs = integration_fixture()
        evidence = kwargs["integration_verification"]
        self.assertEqual(IntegrationGateEvidence.from_dict(__import__("json").loads(evidence.to_bytes())), evidence)
        stale = IntegrationGateEvidence.from_dict(__import__("json").loads(evidence.to_bytes()))
        self.assertNotEqual(stale.main_sha40, "f" * 40)

    def test_parent_gate_evidence_comment_uses_real_git_sha_and_double_reads_external_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "P-ASES test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "pases@example.invalid"], check=True)
            check_ids = ("compileall", "unit-tests", "docs-validation", "format-check", "required-ci")
            checks = []
            artifacts = []
            for check_id in check_ids:
                reference = f"evidence/{check_id}.txt"
                content = f"verified {check_id}\n".encode()
                path = repo / reference
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                artifacts.append((reference, content))
                checks.append({"check_id": check_id, "status": "PASS",
                               "evidence_sha256": hashlib.sha256(content).hexdigest(),
                               "evidence_reference": reference})
            subprocess.run(["git", "-C", str(repo), "add", "evidence"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add verification artifacts"], check=True)
            main_sha = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            source = {"schema": "PASES_PARENT_INTEGRATION_CHECKS_V1", "kind": "verification",
                      "status": "PASS", "repository": "octo/repo", "parent_issue_number": 26,
                      "parent_adc_sha256": "b" * 64, "main_sha40": main_sha, "checks": checks}
            source_bytes = json.dumps(source, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            artifacts.sort(key=lambda row: row[0])
            bundle = ParentGateEvidenceComment("verification", "octo/repo", 26, "b" * 64,
                                               main_sha, source_bytes, tuple(artifacts))
            comment_id = 9876
            comment = {
                "id": comment_id, "body": bundle.to_body(),
                "created_at": "2026-10-12T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
                "issue_url": "https://api.github.com/repos/octo/repo/issues/26",
                "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id}",
                "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id}",
                "user": {"id": 42, "login": "octocat", "type": "User"},
            }

            class CommentGitHub:
                def __init__(self):
                    self.row = comment
                    self.reads = 0
                    self.duplicate = False
                    self.extra = None
                def issue_comment(self, _issue, _comment):
                    self.reads += 1
                    if self.row is None:
                        raise GitHubError("comment deleted")
                    return dict(self.row)
                def issue_comments(self, _issue):
                    if self.row is None:
                        return []
                    if self.extra is not None:
                        return [dict(self.row), dict(self.extra)]
                    return [dict(self.row), dict(self.row)] if self.duplicate else [dict(self.row)]
                def authenticated_user(self):
                    return {"id": 42, "login": "octocat", "type": "User"}

            github = CommentGitHub()
            evidence = _load_parent_gate_evidence_from_github(
                github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            self.assertEqual(evidence.source_reference, f"issue-comment:{comment_id}")
            self.assertEqual(evidence.main_sha40, main_sha)
            self.assertEqual(github.reads, 4)

            with self.assertRaisesRegex(IntegrationError, "exact current main/ADC subject"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "f" * 64)
            github.row = {**comment, "issue_url": "https://api.github.com/repos/octo/repo/issues/27"}
            with self.assertRaisesRegex(IntegrationError, "repository or Issue identity"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.row = comment
            github.duplicate = True
            with self.assertRaisesRegex(IntegrationError, "missing or duplicated"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.duplicate = False
            github.extra = {**comment, "id": comment_id + 1,
                            "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id + 1}",
                            "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id + 1}"}
            with self.assertRaisesRegex(IntegrationError, "duplicate or mismatched comment IDs"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.extra = None

            with self.assertRaisesRegex(IntegrationError, "current main/ADC subject"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, "f" * 40, "verification", "octo/repo", "b" * 64)
            github.row = {**comment, "updated_at": "2026-10-12T00:01:00Z"}
            with self.assertRaisesRegex(IntegrationError, "edited"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.row = {**comment, "user": {"id": 99, "login": "other", "type": "User"}}
            with self.assertRaisesRegex(IntegrationError, "author is not the authenticated"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)
            github.row = None
            with self.assertRaisesRegex(GitHubError, "comment deleted"):
                _load_parent_gate_evidence_from_github(
                    github, comment_id, main_sha, "verification", "octo/repo", "b" * 64)

    def test_parent_evidence_publish_reuses_exact_comment_and_rejects_conflict(self):
        main_sha = "1" * 40
        pointer = object()

        class PublishGitHub:
            def __init__(self):
                self.comments = []
                self.posts = 0
                self.issue_body = "parent contract"

            def issue(self, _number):
                return {"number": 26, "state": "open", "pull_request": None,
                        "repository_url": "https://api.github.com/repos/octo/repo",
                        "body": self.issue_body}

            def issue_comments(self, _number):
                return [dict(row) for row in self.comments]

            def authenticated_user(self):
                return {"id": 42, "login": "octocat", "type": "User"}

            def create_issue_comment(self, _number, body):
                self.posts += 1
                comment_id = 9000 + self.posts
                row = {"id": comment_id, "body": body,
                       "created_at": "2026-10-12T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
                       "issue_url": "https://api.github.com/repos/octo/repo/issues/26",
                       "html_url": f"https://github.com/octo/repo/issues/26#issuecomment-{comment_id}",
                       "url": f"https://api.github.com/repos/octo/repo/issues/comments/{comment_id}",
                       "user": {"id": 42, "login": "octocat", "type": "User"}}
                self.comments.append(row)
                return row

            def issue_comment(self, _number, comment_id):
                return next(dict(row) for row in self.comments if row["id"] == comment_id)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_path = root / "evidence" / "unit-tests.txt"
            artifact_path.parent.mkdir()
            artifact_path.write_bytes(b"unit test result\n")
            source = {"schema": "PASES_PARENT_INTEGRATION_CHECKS_V1", "kind": "verification",
                      "status": "PASS", "repository": "octo/repo", "parent_issue_number": 26,
                      "parent_adc_sha256": "b" * 64, "main_sha40": main_sha,
                      "checks": [{"check_id": name, "status": "PASS", "evidence_sha256": "0" * 64,
                                  "evidence_reference": f"evidence/{name}.txt"}
                                 for name in ("compileall", "unit-tests", "docs-validation",
                                              "format-check", "required-ci")]}
            for check in source["checks"]:
                path = root / check["evidence_reference"]
                path.parent.mkdir(exist_ok=True)
                path.write_bytes((check["check_id"] + "\n").encode())
                check["evidence_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            result_path = root / "verification.json"
            result_path.write_bytes(json.dumps(source, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            github = PublishGitHub()
            args = SimpleNamespace(issue=26, kind="verification", result=result_path)
            patches = (patch("p_ases.cli._parent_adc_authority", return_value=("b" * 64, pointer)),
                       patch("p_ases.cli._parent_current_main_sha", return_value=main_sha))
            for active in patches:
                active.start()
            try:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = _publish_parent_gate_evidence(args, "octo/repo", root, github)
                self.assertEqual(status, 0)
                first = json.loads(output.getvalue())
                self.assertEqual(first["status"], "PUBLISHED")
                self.assertEqual(github.posts, 1)

                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = _publish_parent_gate_evidence(args, "octo/repo", root, github)
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(output.getvalue())["status"], "REUSED")
                self.assertEqual(github.posts, 1)

                source["checks"][0]["evidence_sha256"] = hashlib.sha256(b"changed bytes\n").hexdigest()
                (root / "evidence/compileall.txt").write_bytes(b"changed bytes\n")
                result_path.write_bytes(json.dumps(source, sort_keys=True, separators=(",", ":")).encode() + b"\n")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = _publish_parent_gate_evidence(args, "octo/repo", root, github)
                self.assertEqual(status, 2)
                self.assertIn("different parent evidence comment", json.loads(output.getvalue())["reasons"][0])
                self.assertEqual(github.posts, 1)
            finally:
                for active in patches:
                    active.stop()

    def test_github_parent_label_definition_adapter_is_readback_checked(self):
        github = GitHub("octo/repo")
        expected = {"name": "phase:integration", "color": "0e8a16",
                    "description": "Workflow phase: integration"}
        with patch.object(github, "request", return_value=expected) as request:
            self.assertEqual(github.create_repository_label(**expected), expected)
        self.assertEqual(request.call_args.args[:2], ("POST", "repos/octo/repo/labels"))
        self.assertEqual(request.call_args.args[2], expected)
        with patch.object(github, "request", return_value={**expected, "color": "ffffff"}):
            with self.assertRaisesRegex(GitHubError, "did not match"):
                github.create_repository_label(**expected)

    def test_frozen_child_set_cannot_be_empty_or_duplicate(self):
        kwargs = integration_fixture()
        kwargs["expected_child_issue_numbers"] = (27, 27)
        with self.assertRaises(IntegrationError):
            evaluate_parent_integration(**kwargs)


if __name__ == "__main__":
    unittest.main()
