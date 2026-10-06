from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from agent_workflow.contracts import (ContractError, parse_comment, publish_contract,
                                      classify_reviewer_checklist_h2, restore_contract, save_contract, sha256,
                                      validate_payload, validate_reviewer_checklist_authoring,
                                      verify_contract)
from agent_workflow.context import ContextError, affected_components, build_context
from agent_workflow.cli import (_ensure_milestone, _init_project, _start_feature_branch,
                                _validate_docs, _validate_self_review, build_parser,
                                main as cli_main)
from agent_workflow.delivery import (DeliveryError, delivery_check, ensure_review_pr,
                                     finalize_merged_issue)
from agent_workflow.documents import resolve_document_impact, validate_markdown_file, validate_docs
from agent_workflow.git import (GitLifecycleError, _remove_cleanup_path, changed_document_paths,
                                feature_slug, push_review_branch, start_feature_branch)
from agent_workflow.github import GitHub, GitHubError
from agent_workflow.profile import ProfileError, build_hook_plan, validate_profile
from agent_workflow.process import ProcessError, run_command
from agent_workflow.review import (ReviewError, _extract_items, _with_pointer,
                                   contract_review_units, load_review, prepare_review,
                                   load_review_surface, publish_review, review_path,
                                   validate_public_review)
import build_dist
import validate_dist
import package_release
from agent_workflow import __version__
from agent_workflow.versioning import (VersionError, _split_command, resolve_milestone_version,
                                       resolve_version)


def profile_fixture():
    return {
        "schema_version": 2,
        "initialized": True,
        "project_name": "fixture",
        "components": [
            {"id": "one", "roots": ["."], "stacks": ["unknown-stack"],
             "application_types": ["cli"], "hooks": {"verify_quick": ["echo one"]},
             "targets": [{"id": "linux", "runnable_on": ["linux"],
                          "hooks": {"verify_quick": ["echo target"]}}]},
            {"id": "two", "roots": ["sub"], "stacks": [], "application_types": ["library"],
             "hooks": {"verify_quick": ["echo two"]}, "targets": []},
        ],
        "branch": {"required_checks": ["CI"]}, "milestones": {"mode": "auto", "version_source": "auto"},
        "hooks": {"verify_quick": ["echo global"]},
    }


def python_shell_command(script, *arguments):
    command = [sys.executable, "-c", script, *arguments]
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)
    return " ".join(__import__("shlex").quote(part) for part in command)


class FakeGitHub:
    def __init__(self, body=""):
        self.repo = "owner/repo"
        self.issue_data = {"number": 1, "title": "Issue title",
                           "repository_url": "https://api.github.com/repos/owner/repo",
                           "html_url": "https://github.com/owner/repo/issues/1", "state": "open",
                           "pull_request": None, "body": body, "labels": [{"name": "phase:review"}],
                           "milestone": None}
        self.comments = []
        self.next_id = 100
        self.pull_data = None
        self.pull_candidates = []
        self.created_prs = []
        self.updated_prs = []
        self.next_pr = 1
        self.push_data = {"head_sha": "d" * 40, "head_branch": "feature/1-review"}
        self.label_replacements = []
        self.fail_label_replacement = False
        self.pull_comments = {}
        self.removed = []
        self.runs = []
        self.commit_statuses = []
        self.milestone_data = []
        self.next_milestone = 10
        self.repository_data = {"default_branch": "main"}
        self.lifecycle_calls = []

    def issue(self, number):
        self.lifecycle_calls.append(("issue", number))
        return copy.deepcopy(self.issue_data)

    def repository(self):
        self.lifecycle_calls.append(("repository",))
        return copy.deepcopy(self.repository_data)

    def milestones(self):
        self.lifecycle_calls.append(("milestones",))
        return copy.deepcopy(self.milestone_data)

    def create_milestone(self, title):
        self.lifecycle_calls.append(("create_milestone", title))
        self.next_milestone += 1
        milestone = {"number": self.next_milestone, "title": title, "state": "open"}
        self.milestone_data.append(copy.deepcopy(milestone))
        return copy.deepcopy(milestone)

    def assign_issue_milestone(self, number, milestone):
        self.lifecycle_calls.append(("assign_milestone", number, milestone))
        found = next(item for item in self.milestone_data if item["number"] == milestone)
        self.issue_data["milestone"] = copy.deepcopy(found)
        return self.issue(number)

    def issue_comments(self, number):
        return copy.deepcopy(self.comments)

    def issue_comment(self, number, comment_id):
        for comment in self.comments:
            if comment["id"] == comment_id:
                return copy.deepcopy(comment)
        raise RuntimeError("unexpected comment id")

    def create_issue_comment(self, number, body):
        self.next_id += 1
        comment = {"id": self.next_id, "issue_url": f"https://api.github.com/repos/{self.repo}/issues/{number}", "body": body}
        self.comments.append(comment)
        return copy.deepcopy(comment)

    def update_issue(self, number, body):
        self.issue_data["body"] = body
        return self.issue(number)

    def pull(self, number):
        return copy.deepcopy(self.pull_data)

    def open_pull_requests(self, head_branch, base_branch):
        self.lifecycle_calls.append(("open_pull_requests", head_branch, base_branch))
        return copy.deepcopy([
            pull for pull in self.pull_candidates
            if pull.get("head", {}).get("ref") == head_branch
            and pull.get("base", {}).get("ref") == base_branch
        ])

    def create_pull_request(self, title, head, base, body):
        self.next_pr += 1
        pull = {"number": self.next_pr, "html_url": f"https://github.com/{self.repo}/pull/{self.next_pr}",
                "title": title, "state": "open", "draft": False, "merged": False,
                "base": {"ref": base, "repo": {"full_name": self.repo}},
                "head": {"ref": head, "sha": self.push_data["head_sha"],
                         "repo": {"full_name": self.repo}}, "body": body}
        self.created_prs.append(copy.deepcopy(pull))
        self.pull_data = copy.deepcopy(pull)
        self.pull_candidates.append(copy.deepcopy(pull))
        return copy.deepcopy(pull)

    def update_pull_request(self, number, title, body):
        self.updated_prs.append((number, title, body))
        self.pull_data["title"] = title
        self.pull_data["body"] = body
        for pull in self.pull_candidates:
            if pull.get("number") == number:
                pull["title"] = title
                pull["body"] = body
        return self.pull(number)

    def pull_comment(self, comment_id):
        return copy.deepcopy(self.pull_comments[comment_id])

    def create_pull_comment(self, number, body):
        self.next_id += 1
        comment = {"id": self.next_id, "issue_url": f"https://api.github.com/repos/{self.repo}/issues/{number}", "body": body}
        self.pull_comments[self.next_id] = comment
        return copy.deepcopy(comment)

    def update_pull(self, number, body):
        self.pull_data["body"] = body
        return self.pull(number)

    def check_runs(self, ref):
        return copy.deepcopy(self.runs)

    def statuses(self, ref):
        return copy.deepcopy(self.commit_statuses)

    def remove_issue_label(self, number, label):
        self.removed.append(label)
        self.issue_data["labels"] = [x for x in self.issue_data["labels"] if x["name"] != label]

    def replace_issue_labels(self, number, labels):
        self.label_replacements.append((number, list(labels)))
        if self.fail_label_replacement:
            raise GitHubError("label replacement failed")
        self.issue_data["labels"] = [{"name": label} for label in labels]
        return copy.deepcopy(self.issue_data["labels"])


def install_review_contract(repo: Path, gh: FakeGitHub, payload: bytes | None = None):
    if payload is None:
        newline = bytes((13, 10))
        fence = bytes((96, 96, 96))
        lines = [
            b"Contract preamble.", b"", b"## Architecture Decisions",
            b"Review the complete contract.", fence + b"md", b"## Fake Heading", fence, b"",
            b"## 9. Reviewer Checklist", b"<!-- AGENT_REVIEWER_CHECKLIST_V1 -->",
            b"- [ ] Contract checklist point", b"<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->", b"",
            b"## Document impact", b"Specification and Design links are required.", b"",
        ]
        payload = newline.join(lines)
    newline_text = chr(13) + chr(10)
    gh.issue_data["body"] = newline_text.join([
        "## Reviewer Checklist",
        "<!-- AGENT_REVIEWER_CHECKLIST_V1 -->",
        "- [ ] Issue checklist point",
        "<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->",
        "",
    ])
    source = repo / "approved-contract.md"
    source.write_bytes(payload)
    published = publish_contract(repo, 1, gh, source)
    surface = load_review_surface(1, gh.issue_data["body"], gh)
    return payload, published, surface


def complete_review_draft(draft: dict, *, result: str = "pass") -> dict:
    updated = copy.deepcopy(draft)
    for section in updated["contract_sections"]:
        section["result"] = result
        section["evidence"] = f"Reviewed {section['id']} against the final source and diff."
    for item in updated["items"]:
        item["result"] = result
        item["evidence"] = f"Checked {item['id']} against source and verification output."
    return updated


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_schema2_and_explicit_unknown_stack_are_valid(self):
        result = validate_profile(profile_fixture(), self.repo)
        self.assertEqual(result["components"][0]["stacks"], ["unknown-stack"])
        self.assertEqual(result["components"][0]["application_types"], ["cli"])

    def test_schema1_flat_hooks_remain_readable(self):
        value = {"schema_version": 1, "project_name": "legacy", "hooks": {"verify_quick": ["python -V"]}}
        parsed = validate_profile(value, self.repo)
        plan = build_hook_plan(parsed, "verify_quick")
        self.assertEqual(plan.steps[0].command, "python -V")

    def test_malformed_target_requirements_fail_before_planning(self):
        value = profile_fixture()
        value["components"][0]["targets"][0]["requirements"] = {"tools": []}
        with self.assertRaises(ProfileError):
            validate_profile(value, self.repo)

    def test_application_types_are_explicit_and_closed_set(self):
        value = profile_fixture()
        value["components"][0]["application_types"] = ["desktop"]
        with self.assertRaises(ProfileError):
            validate_profile(value, self.repo)

    def test_posix_and_windows_escape_roots_are_rejected(self):
        for path in ("../outside", "..\\outside", "C:\\outside", "\\\\server\\share"):
            value = profile_fixture()
            value["components"][0]["roots"] = [path]
            with self.subTest(path=path), self.assertRaises(ProfileError):
                validate_profile(value, self.repo)

    def test_hook_order_is_global_component_target_in_profile_order(self):
        profile = validate_profile(profile_fixture(), self.repo)
        plan = build_hook_plan(profile, "verify_quick", ["two", "one"], host="linux")
        self.assertEqual([step.command for step in plan.steps], ["echo global", "echo one", "echo two", "echo target"])
        self.assertEqual([c["id"] for c in plan.components], ["one", "two"])

    def test_quick_without_scope_uses_all_components_and_branch_switch_is_global(self):
        profile = validate_profile(profile_fixture(), self.repo)
        quick = build_hook_plan(profile, "verify_quick", host="linux")
        self.assertEqual([step.command for step in quick.steps], ["echo global", "echo one", "echo two", "echo target"])
        profile["hooks"]["branch_switch"] = ["cargo clean"]
        switched = build_hook_plan(profile, "branch_switch")
        self.assertEqual([step.command for step in switched.steps], ["cargo clean"])
        with self.assertRaises(ProfileError):
            build_hook_plan(profile, "branch_switch", ["one"])

    def test_unknown_component_never_broadens_scope(self):
        profile = validate_profile(profile_fixture(), self.repo)
        with self.assertRaises(ProfileError):
            build_hook_plan(profile, "verify_quick", ["all"])

    def test_host_mismatch_skips_target_without_planning_its_command(self):
        profile = validate_profile(profile_fixture(), self.repo)
        plan = build_hook_plan(profile, "verify_quick", ["one"], host="windows")
        self.assertEqual([step.command for step in plan.steps], ["echo global", "echo one"])
        self.assertEqual(plan.skipped[0].target, "linux")
        self.assertEqual(plan.skipped[0].reason, "host_mismatch")

    def test_target_tool_requirement_skips_only_that_target(self):
        value = profile_fixture()
        value["components"][0]["targets"][0]["requirements"] = {
            "architectures": [], "tools": ["definitely-no-agent-workflow-tool"], "capabilities": []}
        profile = validate_profile(value, self.repo)
        plan = build_hook_plan(profile, "verify_quick", ["one"], host="linux")
        self.assertEqual([step.command for step in plan.steps], ["echo global", "echo one"])
        self.assertEqual(plan.skipped[0].reason, "missing_tool")

    def test_target_architecture_aliases_are_normalized(self):
        value = profile_fixture()
        value["components"][0]["targets"][0]["requirements"] = {
            "architectures": ["aarch64"], "tools": [], "capabilities": []}
        profile = validate_profile(value, self.repo)
        plan = build_hook_plan(profile, "verify_quick", ["one"], host="linux", arch="arm64")
        self.assertEqual(plan.skipped, ())
        self.assertEqual(plan.steps[-1].command, "echo target")

    def test_target_without_hook_does_not_emit_irrelevant_skip(self):
        value = profile_fixture()
        value["components"][0]["targets"][0]["hooks"] = {"verify_final": ["echo final"]}
        plan = build_hook_plan(validate_profile(value, self.repo), "verify_quick", ["one"], host="windows")
        self.assertEqual(plan.skipped, ())

    def test_required_check_schema_is_validated_before_use(self):
        value = profile_fixture()
        value["branch"]["required_checks"] = [{"name": "CI", "app_id": "not-an-id"}]
        with self.assertRaises(ProfileError):
            validate_profile(value, self.repo)

    def test_schema2_lifecycle_defaults_and_legacy_milestone_mapping(self):
        value = profile_fixture()
        value["milestones"] = {"mode": "auto", "version_source": "auto"}
        result = validate_profile(value, self.repo)
        self.assertEqual(result["branch"], {"prefix": "feature", "max_slug_length": 48,
                                             "cleanup_on_switch": [], "required_checks": ["CI"]})
        self.assertEqual(result["milestones"]["mode"], "auto")
        for enabled, expected in ((False, "disabled"), (True, "required")):
            legacy = profile_fixture()
            legacy["milestones"] = {"enabled": enabled, "version_source": "auto"}
            self.assertEqual(validate_profile(legacy, self.repo)["milestones"]["mode"], expected)

    def test_profile_rejects_conflicting_milestone_fields_and_unsafe_branches(self):
        cases = []
        value = profile_fixture()
        value["milestones"] = {"enabled": False, "mode": "auto"}
        cases.append(value)
        for prefix in ("../feature", "feature/sub", "-unsafe", "trailing.", "branch.lock"):
            value = profile_fixture()
            value["branch"]["prefix"] = prefix
            cases.append(value)
        for limit in (0, -1, 129, True, "48"):
            value = profile_fixture()
            value["branch"]["max_slug_length"] = limit
            cases.append(value)
        for path in ("/tmp/out", ".", "..", "out/../other", "C:\\outside", "bad\x00path"):
            value = profile_fixture()
            value["branch"]["cleanup_on_switch"] = [path]
            cases.append(value)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ProfileError):
                validate_profile(value, self.repo)

    def test_cleanup_path_may_be_a_symlink_leaf_but_not_an_escaping_parent(self):
        outside = self.repo.parent / (self.repo.name + "-outside")
        outside.mkdir()
        (self.repo / "link").symlink_to(outside, target_is_directory=True)
        value = profile_fixture()
        value["branch"]["cleanup_on_switch"] = ["link"]
        self.assertEqual(validate_profile(value, self.repo)["branch"]["cleanup_on_switch"], ["link"])
        value["branch"]["cleanup_on_switch"] = ["link/child"]
        with self.assertRaises(ProfileError):
            validate_profile(value, self.repo)
        import shutil
        shutil.rmtree(outside)

    def test_single_and_multi_component_issue_routing_are_explicit(self):
        single = profile_fixture()
        single["components"] = single["components"][:1]
        self.assertEqual([x["id"] for x in affected_components("", validate_profile(single, self.repo))], ["one"])
        profile = validate_profile(profile_fixture(), self.repo)
        with self.assertRaises(ContextError):
            affected_components("", profile)
        self.assertEqual([x["id"] for x in affected_components("## Affected components\n- two\n", profile)], ["two"])
        with self.assertRaises(ContextError):
            affected_components("## Affected components\n- all\n", profile)

    def test_init_project_is_schema2_generic_by_default_and_cargo_clean_is_opt_in(self):
        temp = Path(tempfile.mkdtemp())
        try:
            (temp / ".git").mkdir()
            (temp / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
            result = _init_project(type("Args", (), {"repo": str(temp), "name": None,
                "application_type": None, "stack": None, "target": [], "cargo_clean": "off"})())
            profile = json.loads((temp / ".agent/project.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["schema_version"], 2)
            self.assertEqual(profile["components"][0]["application_types"], ["generic"])
            self.assertEqual(profile["components"][0]["stacks"], ["rust"])
            self.assertEqual(profile["components"][0]["hooks"]["verify_final"], [])
            self.assertEqual(profile["hooks"]["branch_switch"], [])
            self.assertEqual(profile["milestones"], {"mode": "auto", "version_source": "auto"})
            self.assertEqual(profile["branch"]["cleanup_on_switch"], [])
            self.assertIsNotNone(result["warning"])
        finally:
            import shutil
            shutil.rmtree(temp)

    def test_init_project_places_opted_in_cargo_clean_on_global_branch_switch(self):
        temp = Path(tempfile.mkdtemp())
        try:
            (temp / ".git").mkdir()
            (temp / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
            args = type("Args", (), {"repo": str(temp), "name": None, "application_type": None,
                "stack": None, "target": [], "cargo_clean": "on"})()
            _init_project(args)
            data = json.loads((temp / ".agent/project.json").read_text(encoding="utf-8"))
            self.assertEqual(data["hooks"]["branch_switch"], ["cargo clean"])
            self.assertEqual(data["components"][0]["hooks"]["verify_final"], [])
        finally:
            import shutil
            shutil.rmtree(temp)


class VersioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_auto_versionless_is_unresolved(self):
        self.assertIsNone(resolve_version(self.repo, "auto"))

    def test_auto_detects_package_cargo_and_pyproject_versions(self):
        cases = [
            ("package.json", '{"version":" 1.2.3 "}\n'),
            ("Cargo.toml", '[package]\nname = "demo"\nversion = "2.3.4"\n'),
            ("Cargo.toml", '[workspace.package]\nversion = "3.4.5"\n'),
            ("pyproject.toml", '[project]\nname = "demo"\nversion = "4.5.6"\n'),
        ]
        for name, content in cases:
            with self.subTest(name=name, content=content):
                for path in self.repo.iterdir():
                    if path.is_dir():
                        import shutil
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                self.write(name, content)
                expected = json.loads(content)["version"] if name == "package.json" else content.split('version = "')[1].split('"')[0]
                self.assertEqual(resolve_version(self.repo, "auto"), expected)

    def test_equal_sources_are_accepted_and_conflicts_fail_closed(self):
        self.write("package.json", '{"version":"1.2.3"}\n')
        self.write("Cargo.toml", '[package]\nversion = "1.2.3"\n')
        self.assertEqual(resolve_version(self.repo, "auto"), "1.2.3")
        self.write("pyproject.toml", '[project]\nversion = "9.9.9"\n')
        with self.assertRaisesRegex(VersionError, "VERSION_AMBIGUOUS"):
            resolve_version(self.repo, "auto")

    def test_explicit_json_toml_python_attribute_and_command_sources(self):
        self.write("versions.json", '{"release":{"version":" 1.2.3 "}}\n')
        self.assertEqual(resolve_version(self.repo, {"type": "json", "path": "versions.json",
                                                     "field": "release.version"}), " 1.2.3 ")
        self.write("release.toml", '[workspace.package]\nversion = "2.3.4" # inline comment\n')
        self.assertEqual(resolve_version(self.repo, {"type": "toml", "path": "release.toml",
                                                     "field": "workspace.package.version"}), "2.3.4")
        self.write("version.py", '__version__ = "3.4.5"\n')
        self.assertEqual(resolve_version(self.repo, {"type": "python-attr", "path": "version.py",
                                                     "field": "__version__"}), "3.4.5")
        command = f'{sys.executable} -c "print(\'4.5.6\')"'
        self.assertEqual(resolve_version(self.repo, {"type": "command", "command": command}), "4.5.6")

    def test_windows_command_splitting_preserves_backslashes_and_quotes(self):
        command = r'"C:\Program Files\Python\python.exe" -c "print(456)"'
        self.assertEqual(
            _split_command(command, windows=True),
            [r"C:\Program Files\Python\python.exe", "-c", "print(456)"],
        )

    def test_explicit_missing_source_is_unresolved_and_invalid_versions_fail(self):
        source = {"type": "json", "path": "missing.json", "field": "version"}
        self.assertIsNone(resolve_version(self.repo, source))
        self.write("package.json", '{"version":"1.0\\n2.0"}\n')
        with self.assertRaisesRegex(VersionError, "single-line"):
            resolve_version(self.repo, "auto")

    def test_milestone_target_resolution_preserves_exact_string_and_bypasses_fallback(self):
        source = {"type": "command", "command": "not-a-real-version-command"}
        with patch("agent_workflow.versioning.resolve_version", side_effect=AssertionError("fallback called")) as fallback:
            self.assertEqual(resolve_milestone_version(self.repo, source, "  next release  "),
                             ("  next release  ", "target"))
        fallback.assert_not_called()

    def test_milestone_target_uses_existing_version_validation(self):
        for value in (123, "", "  \t", "0.4.0\nnext", "0.4.0\rnext"):
            with self.subTest(value=repr(value)), self.assertRaisesRegex(VersionError, "non-empty single-line"):
                resolve_milestone_version(self.repo, "auto", value)

    def test_milestone_version_fallback_reports_profile_origin(self):
        self.write("package.json", '{"version":"0.3.0"}\n')
        self.assertEqual(resolve_milestone_version(self.repo, "auto", None), ("0.3.0", "profile"))


class MilestoneLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.fake = FakeGitHub()
        self.profile = profile_fixture()
        self.profile["components"] = self.profile["components"][:1]
        self.profile["milestones"] = {"mode": "auto", "version_source": "auto"}

    def run_ensure(self, target_version=None):
        args = type("Args", (), {"repo": str(self.repo), "issue": 1,
                                  "target_version": target_version})()
        with patch("agent_workflow.cli._repo_arg", return_value=self.repo), \
             patch("agent_workflow.cli.load_profile", return_value=self.profile), \
             patch("agent_workflow.cli._gh", return_value=self.fake):
            return _ensure_milestone(args)

    def test_auto_without_version_is_not_applicable_without_mutation(self):
        result = self.run_ensure()
        self.assertEqual(result["status"], "NOT_APPLICABLE")
        self.assertEqual((result["version"], result["version_origin"]), (None, "profile"))
        self.assertEqual(self.fake.milestone_data, [])
        self.assertEqual([call[0] for call in self.fake.lifecycle_calls], ["issue"])

    def test_required_without_version_fails_and_disabled_skips(self):
        self.profile["milestones"]["mode"] = "required"
        with self.assertRaisesRegex(VersionError, "required milestone mode"):
            self.run_ensure()
        self.profile["milestones"]["mode"] = "disabled"
        self.fake.lifecycle_calls.clear()
        self.assertEqual(self.run_ensure("0.4.0")["status"], "DISABLED")
        self.assertEqual([call[0] for call in self.fake.lifecycle_calls], ["issue"])

    def test_create_reuse_and_same_issue_assignment_are_idempotent(self):
        (self.repo / "package.json").write_text('{"version":"0.2.0"}\n', encoding="utf-8")
        result = self.run_ensure()
        self.assertEqual((result["created"], result["assigned"]), (True, True))
        self.assertEqual((result["version"], result["version_origin"]), ("0.2.0", "profile"))
        self.assertEqual(self.fake.milestone_data[0]["title"], "0.2.0")
        self.assertEqual(self.fake.issue_data["milestone"]["number"], result["milestone"])

        self.fake.issue_data["milestone"] = {"number": result["milestone"], "title": "0.2.0", "state": "open"}
        self.fake.lifecycle_calls.clear()
        repeated = self.run_ensure()
        self.assertEqual((repeated["created"], repeated["assigned"]), (False, False))
        self.assertNotIn("assign_milestone", [call[0] for call in self.fake.lifecycle_calls])

    def test_version_title_is_used_without_normalization(self):
        (self.repo / "package.json").write_text('{"version":" 0.2.0 "}\n', encoding="utf-8")
        result = self.run_ensure()
        self.assertTrue(result["created"])
        self.assertEqual(self.fake.milestone_data[0]["title"], " 0.2.0 ")

    def test_existing_exact_title_is_reused_and_different_assignment_fails(self):
        (self.repo / "package.json").write_text('{"version":"0.2.0"}\n', encoding="utf-8")
        self.fake.milestone_data = [{"number": 12, "title": "0.2.0", "state": "open"}]
        result = self.run_ensure()
        self.assertFalse(result["created"])
        self.assertEqual(self.fake.issue_data["milestone"]["number"], 12)

        self.fake.issue_data["milestone"] = {"number": 99, "title": "0.1.0", "state": "open"}
        with self.assertRaisesRegex(GitHubError, "different milestone.*0.1.0.*0.2.0"):
            self.run_ensure()

    def test_closed_duplicate_and_ambiguous_versions_fail_before_assignment(self):
        (self.repo / "package.json").write_text('{"version":"0.2.0"}\n', encoding="utf-8")
        self.fake.milestone_data = [{"number": 12, "title": "0.2.0", "state": "closed"}]
        with self.assertRaisesRegex(GitHubError, "closed"):
            self.run_ensure()
        self.fake.milestone_data = [{"number": 12, "title": "0.2.0", "state": "open"},
                                    {"number": 13, "title": "0.2.0", "state": "open"}]
        with self.assertRaisesRegex(GitHubError, "multiple exact-title"):
            self.run_ensure()
        self.assertIsNone(self.fake.issue_data["milestone"])

        (self.repo / "pyproject.toml").write_text('[project]\nversion = "8.0"\n', encoding="utf-8")
        with self.assertRaisesRegex(VersionError, "VERSION_AMBIGUOUS"):
            self.run_ensure()

    def test_explicit_target_overrides_current_unresolved_and_ambiguous_sources(self):
        (self.repo / "package.json").write_text('{"version":"0.3.0"}\n', encoding="utf-8")
        self.profile["milestones"]["version_source"] = {
            "type": "json", "path": "missing.json", "field": "version"
        }
        result = self.run_ensure("0.4.0")
        self.assertEqual((result["created"], result["assigned"]), (True, True))
        self.assertEqual((result["version"], result["version_origin"]), ("0.4.0", "target"))
        self.assertEqual(self.fake.milestone_data[0]["title"], "0.4.0")
        retry = self.run_ensure("0.4.0")
        self.assertEqual((retry["created"], retry["assigned"]), (False, False))

        self.fake = FakeGitHub()
        self.profile["milestones"]["version_source"] = "auto"
        (self.repo / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
        result = self.run_ensure("0.4.0")
        self.assertEqual((result["version"], result["version_origin"]), ("0.4.0", "target"))
        self.assertEqual(self.fake.milestone_data[0]["title"], "0.4.0")

    def test_invalid_explicit_target_fails_before_milestone_list_or_mutation(self):
        for target in ("", "0.4.0\nnext"):
            with self.subTest(target=repr(target)):
                self.fake.lifecycle_calls.clear()
                with self.assertRaisesRegex(VersionError, "non-empty single-line"):
                    self.run_ensure(target)
                self.assertEqual([call[0] for call in self.fake.lifecycle_calls], ["issue"])
                self.assertEqual(self.fake.milestone_data, [])
                self.assertIsNone(self.fake.issue_data["milestone"])

    def test_target_exact_title_reuse_and_retry_are_idempotent(self):
        self.fake.milestone_data = [{"number": 14, "title": "0.4.0", "state": "open"}]
        first = self.run_ensure("0.4.0")
        self.assertEqual((first["created"], first["assigned"], first["milestone"]), (False, True, 14))
        self.assertEqual((first["version"], first["version_origin"]), ("0.4.0", "target"))

        self.fake.lifecycle_calls.clear()
        second = self.run_ensure("0.4.0")
        self.assertEqual((second["created"], second["assigned"]), (False, False))
        self.assertEqual((second["version"], second["version_origin"]), ("0.4.0", "target"))
        self.assertNotIn("assign_milestone", [call[0] for call in self.fake.lifecycle_calls])

    def test_mismatched_existing_issue_milestone_fails_without_mutation(self):
        self.fake.issue_data["milestone"] = {"number": 22, "title": "0.3.0", "state": "open"}
        with self.assertRaisesRegex(GitHubError, "different milestone.*0.3.0.*0.4.0"):
            self.run_ensure("0.4.0")
        self.assertEqual([call[0] for call in self.fake.lifecycle_calls], ["issue"])
        self.assertEqual(self.fake.milestone_data, [])
        self.assertEqual(self.fake.issue_data["milestone"]["number"], 22)

    def test_mismatched_existing_milestone_title_is_resolved_from_list(self):
        self.fake.issue_data["milestone"] = {"number": 22}
        self.fake.milestone_data = [
            {"number": 22, "title": "0.3.0", "state": "open"},
            {"number": 23, "title": "0.4.0", "state": "open"},
        ]
        with self.assertRaisesRegex(GitHubError, "different milestone.*0.3.0.*0.4.0"):
            self.run_ensure("0.4.0")
        self.assertNotIn("assign_milestone", [call[0] for call in self.fake.lifecycle_calls])
        self.assertEqual(self.fake.issue_data["milestone"]["number"], 22)

    def test_closed_or_duplicate_explicit_target_milestones_fail(self):
        self.fake.milestone_data = [{"number": 12, "title": "0.4.0", "state": "closed"}]
        with self.assertRaisesRegex(GitHubError, "closed"):
            self.run_ensure("0.4.0")
        self.fake.milestone_data = [{"number": 12, "title": "0.4.0", "state": "open"},
                                    {"number": 13, "title": "0.4.0", "state": "open"}]
        with self.assertRaisesRegex(GitHubError, "multiple exact-title"):
            self.run_ensure("0.4.0")
        self.assertIsNone(self.fake.issue_data["milestone"])

    def test_foreign_closed_or_pull_request_issue_fails_before_milestone_calls(self):
        (self.repo / "package.json").write_text('{"version":"0.2.0"}\n', encoding="utf-8")
        self.fake.issue_data["state"] = "closed"
        with self.assertRaises(ContextError):
            self.run_ensure()
        self.fake.issue_data["state"] = "open"
        self.fake.issue_data["pull_request"] = {"url": "https://api.github.com/repos/owner/repo/pulls/1"}
        with self.assertRaises(ContextError):
            self.run_ensure()
        self.assertEqual(self.fake.milestone_data, [])


class GitLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo, self.remote = self.make_repository()
        self.github = FakeGitHub()

    def git(self, repo, *args):
        return subprocess.run(["git", *args], cwd=repo, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def make_repository(self):
        remote = self.root / "remote.git"
        repo = self.root / "repo"
        remote.mkdir()
        repo.mkdir()
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, stdout=subprocess.DEVNULL)
        self.git(repo, "config", "user.name", "Test")
        self.git(repo, "config", "user.email", "test@example.invalid")
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        self.git(repo, "add", "README.md")
        self.git(repo, "commit", "-m", "base")
        self.git(repo, "remote", "add", "origin", str(remote))
        self.git(repo, "push", "-u", "origin", "main")
        return repo, remote

    def profile(self, cleanup=(), hooks=()):
        value = profile_fixture()
        value["components"] = value["components"][:1]
        value["branch"].update({"prefix": "feature", "max_slug_length": 48,
                                "cleanup_on_switch": list(cleanup)})
        value["hooks"]["branch_switch"] = list(hooks)
        return validate_profile(value, self.repo)

    def test_slug_unicode_punctuation_empty_and_length_boundaries(self):
        self.assertEqual(feature_slug("Café / Ship 🚀 it", 48), "cafe-ship-it")
        self.assertEqual(feature_slug("long description", 5), "long")
        with self.assertRaises(GitLifecycleError):
            feature_slug("你好!!!", 48)

    def test_cli_parses_both_lifecycle_commands(self):
        milestone = build_parser().parse_args(["ensure-milestone", "7", "--target-version", "0.4.0",
                                                "--repo", str(self.repo)])
        self.assertEqual((milestone.command, milestone.issue, milestone.target_version),
                         ("ensure-milestone", 7, "0.4.0"))
        branch = build_parser().parse_args(["start-feature-branch", "7", "ship", "lifecycle",
                                            "--repo", str(self.repo)])
        self.assertEqual((branch.command, branch.issue, branch.description),
                         ("start-feature-branch", 7, ["ship", "lifecycle"]))
        stacked = build_parser().parse_args(["start-feature-branch", "7", "stacked", "feature",
                                             "--base-ref", "release/v2", "--expected-base-sha", "a" * 40])
        self.assertEqual((stacked.base_ref, stacked.expected_base_sha), ("release/v2", "a" * 40))
        ensure = build_parser().parse_args(["ensure-review-pr", "7", "--body-file", "pr.md",
                                            "--base-ref", "release/v2", "--title", "Review title"])
        self.assertEqual((ensure.command, ensure.issue, ensure.body_file, ensure.base_ref, ensure.title),
                         ("ensure-review-pr", 7, Path("pr.md"), "release/v2", "Review title"))

    def test_new_local_and_remote_branch_paths(self):
        created, status = start_feature_branch(self.repo, self.profile(), 7, "new branch", self.github)
        self.assertEqual(status, 0)
        self.assertEqual(created["branch"], "feature/7-new-branch")
        self.assertTrue(created["switched"])
        self.assertEqual(created["creation_source"], "new")
        self.assertEqual(created["base_ref"], "main")
        self.assertEqual(created["base_sha"], self.git(self.repo, "rev-parse", "origin/main"))
        self.assertFalse(created["stacked"])

        self.git(self.repo, "switch", "main")
        local_target = "feature/7-local-branch"
        self.git(self.repo, "branch", local_target)
        local_sha = self.git(self.repo, "rev-parse", local_target)
        local, status = start_feature_branch(self.repo, self.profile(), 7, "local branch", self.github)
        self.assertEqual(status, 0)
        self.assertEqual(local["branch"], local_target)
        self.assertEqual(local["creation_source"], "local")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), local_sha)

        self.git(self.repo, "switch", "main")
        remote_target = "feature/7-remote-branch"
        self.git(self.repo, "branch", remote_target)
        self.git(self.repo, "switch", remote_target)
        (self.repo / "remote-only.txt").write_text("remote\n", encoding="utf-8")
        self.git(self.repo, "add", "remote-only.txt")
        self.git(self.repo, "commit", "-m", "remote target")
        self.git(self.repo, "push", "origin", remote_target)
        remote_sha = self.git(self.repo, "rev-parse", remote_target)
        self.git(self.repo, "switch", "main")
        self.git(self.repo, "branch", "-D", remote_target)
        tracked, status = start_feature_branch(self.repo, self.profile(), 7, "remote branch", self.github)
        self.assertEqual(status, 0)
        self.assertEqual(tracked["branch"], remote_target)
        self.assertEqual(tracked["creation_source"], "remote")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), remote_sha)
        self.assertEqual(self.git(self.repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
                         f"origin/{remote_target}")

    def test_review_push_is_non_force_verified_and_idempotent(self):
        start_feature_branch(self.repo, self.profile(), 7, "review branch", self.github)
        (self.repo / "review.txt").write_text("review change\n", encoding="utf-8")
        self.git(self.repo, "add", "review.txt")
        self.git(self.repo, "commit", "-m", "review change")
        real_invoke = __import__("agent_workflow.git", fromlist=["_invoke"])._invoke
        push_calls = []

        def track_push(repo, args, **kwargs):
            if args[0] == "push":
                push_calls.append(list(args))
            return real_invoke(repo, args, **kwargs)

        with patch("agent_workflow.git._origin_repository", return_value="owner/repo"), \
             patch("agent_workflow.git._invoke", side_effect=track_push):
            first = push_review_branch(self.repo, self.profile(), 7, "owner/repo", "main", "main")
            second = push_review_branch(self.repo, self.profile(), 7, "owner/repo", "main", "main")
        expected_head = self.git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(len(push_calls), 1)
        self.assertNotIn("--force", push_calls[0])
        self.assertNotIn("--force-with-lease", push_calls[0])
        self.assertIn("--no-follow-tags", push_calls[0])
        self.assertTrue(first["pushed"])
        self.assertFalse(second["pushed"])
        self.assertTrue(first["remote_head_verified"])
        self.assertEqual(first["head_sha"], expected_head)
        self.assertEqual(first["remote_head"], expected_head)
        self.assertEqual(self._remote_sha("feature/7-review-branch"), expected_head)

    def test_review_push_origin_identity_requires_one_parseable_fetch_or_push_url(self):
        git_module = __import__("agent_workflow.git", fromlist=["_origin_repository"])
        for push, url in ((False, "https://github.com/owner/repo.git"),
                          (True, "git@github.com:owner/repo.git")):
            completed = subprocess.CompletedProcess(["git"], 0, url + "\n", "")
            with self.subTest(push=push), patch("agent_workflow.git._invoke", return_value=completed) as invoke:
                self.assertEqual(git_module._origin_repository(self.repo, push=push), "owner/repo")
                args = ["remote", "get-url"] + (["--push"] if push else []) + ["--all", "origin"]
                invoke.assert_called_once_with(self.repo, args, allow_failure=True)

        multiple = subprocess.CompletedProcess(["git"], 0,
                                               "https://github.com/owner/repo.git\n"
                                               "https://github.com/owner/other.git\n", "")
        with patch("agent_workflow.git._invoke", return_value=multiple):
            with self.assertRaisesRegex(GitLifecycleError, "exactly one fetch and push URL"):
                git_module._origin_repository(self.repo)

    def test_review_push_rejects_dirty_default_and_no_ahead_before_push(self):
        profile = self.profile()
        real_invoke = __import__("agent_workflow.git", fromlist=["_invoke"])._invoke
        push_calls = []

        def track_push(repo, args, **kwargs):
            if args[0] == "push":
                push_calls.append(list(args))
            return real_invoke(repo, args, **kwargs)

        start_feature_branch(self.repo, profile, 7, "dirty branch", self.github)
        (self.repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with patch("agent_workflow.git._origin_repository", return_value="owner/repo"), \
             patch("agent_workflow.git._invoke", side_effect=track_push):
            with self.assertRaisesRegex(GitLifecycleError, "worktree must be clean"):
                push_review_branch(self.repo, profile, 7, "owner/repo", "main", "main")
        (self.repo / "dirty.txt").unlink()

        self.git(self.repo, "switch", "main")
        with patch("agent_workflow.git._origin_repository", return_value="owner/repo"), \
             patch("agent_workflow.git._invoke", side_effect=track_push):
            with self.assertRaisesRegex(GitLifecycleError, "default branch"):
                push_review_branch(self.repo, profile, 7, "owner/repo", "main", "main")

        start_feature_branch(self.repo, profile, 7, "no ahead", self.github)
        with patch("agent_workflow.git._origin_repository", return_value="owner/repo"), \
             patch("agent_workflow.git._invoke", side_effect=track_push):
            with self.assertRaisesRegex(GitLifecycleError, "no commit ahead"):
                push_review_branch(self.repo, profile, 7, "owner/repo", "main", "main")
        self.assertEqual(push_calls, [])

    def test_review_push_rejects_alternate_push_repository_and_mirror_mode(self):
        profile = self.profile()
        start_feature_branch(self.repo, profile, 7, "unsafe push target", self.github)
        (self.repo / "review.txt").write_text("review\n", encoding="utf-8")
        self.git(self.repo, "add", "review.txt")
        self.git(self.repo, "commit", "-m", "review")
        with patch("agent_workflow.git._origin_repository", side_effect=lambda _repo, push=False:
                   "other/repo" if push else "owner/repo"):
            with self.assertRaisesRegex(GitLifecycleError, "origin repository does not match"):
                push_review_branch(self.repo, profile, 7, "owner/repo", "main", "main")

        real_invoke = __import__("agent_workflow.git", fromlist=["_invoke"])._invoke
        push_calls = []

        def mirror_config(repo, args, **kwargs):
            if args[0] == "push":
                push_calls.append(list(args))
            if args == ["config", "--bool", "--get", "remote.origin.mirror"]:
                return subprocess.CompletedProcess(["git", *args], 0, "true\n", "")
            return real_invoke(repo, args, **kwargs)

        with patch("agent_workflow.git._origin_repository", return_value="owner/repo"), \
             patch("agent_workflow.git._invoke", side_effect=mirror_config):
            with self.assertRaisesRegex(GitLifecycleError, "mirror-push configuration"):
                push_review_branch(self.repo, profile, 7, "owner/repo", "main", "main")
        self.assertEqual(push_calls, [])
        self.assertIsNone(self._remote_sha("feature/7-unsafe-push-target"))

    def test_review_push_failure_and_remote_head_mismatch_fail_closed(self):
        profile = self.profile()
        start_feature_branch(self.repo, profile, 7, "push failure", self.github)
        (self.repo / "review.txt").write_text("review\n", encoding="utf-8")
        self.git(self.repo, "add", "review.txt")
        self.git(self.repo, "commit", "-m", "review")
        real_invoke = __import__("agent_workflow.git", fromlist=["_invoke"])._invoke

        def fail_push(repo, args, **kwargs):
            if args[0] == "push":
                return subprocess.CompletedProcess(["git", *args], 1, "", "private remote diagnostic")
            return real_invoke(repo, args, **kwargs)

        with patch("agent_workflow.git._origin_repository", return_value="owner/repo"), \
             patch("agent_workflow.git._invoke", side_effect=fail_push):
            with self.assertRaisesRegex(GitLifecycleError, "Git push failed") as raised:
                push_review_branch(self.repo, profile, 7, "owner/repo", "main", "main")
        self.assertNotIn("private remote diagnostic", str(raised.exception))
        self.assertIsNone(self._remote_sha("feature/7-push-failure"))

        real_remote = __import__("agent_workflow.git", fromlist=["_remote_branch_sha"])._remote_branch_sha
        target_reads = 0

        def mismatch_after_push(repo, branch):
            nonlocal target_reads
            if branch == "feature/7-push-failure":
                target_reads += 1
                return None if target_reads == 1 else "0" * 40
            return real_remote(repo, branch)

        with patch("agent_workflow.git._origin_repository", return_value="owner/repo"), \
             patch("agent_workflow.git._remote_branch_sha", side_effect=mismatch_after_push):
            with self.assertRaisesRegex(GitLifecycleError, "remote branch HEAD does not match"):
                push_review_branch(self.repo, profile, 7, "owner/repo", "main", "main")

    def _remote_sha(self, branch):
        result = subprocess.run(["git", "--git-dir", str(self.remote), "rev-parse", "--verify",
                                 f"refs/heads/{branch}"], check=False, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.strip() if result.returncode == 0 else None

    def test_stacked_new_branch_starts_at_fetched_base(self):
        self.git(self.repo, "branch", "release/v2")
        self.git(self.repo, "switch", "release/v2")
        (self.repo / "release.txt").write_text("stacked base\n", encoding="utf-8")
        self.git(self.repo, "add", "release.txt")
        self.git(self.repo, "commit", "-m", "release base")
        self.git(self.repo, "push", "-u", "origin", "release/v2")
        base_sha = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "switch", "main")

        result, status = start_feature_branch(self.repo, self.profile(), 7, "stacked feature",
                                              self.github, "release/v2", base_sha)

        self.assertEqual(status, 0)
        self.assertEqual(result["base_ref"], "release/v2")
        self.assertEqual(result["base_sha"], base_sha)
        self.assertTrue(result["stacked"])
        self.assertEqual(result["creation_source"], "new")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), base_sha)

    def test_base_ref_rejects_arbitrary_sha_as_a_branch(self):
        sha = self.git(self.repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(GitLifecycleError, "same-repository remote branch"):
            start_feature_branch(self.repo, self.profile(), 7, "sha as base", self.github, sha)
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")

    def test_expected_base_mismatch_has_zero_switch_cleanup_and_hooks(self):
        self.git(self.repo, "branch", "release/v2")
        self.git(self.repo, "push", "origin", "release/v2")
        (self.repo / ".git/info/exclude").write_text("out/\n", encoding="utf-8")
        (self.repo / "out").mkdir()
        (self.repo / "out/keep.txt").write_text("keep\n", encoding="utf-8")
        profile = self.profile(cleanup=("out",), hooks=("echo should-not-run",))
        before_branch = self.git(self.repo, "branch", "--show-current")
        before_head = self.git(self.repo, "rev-parse", "HEAD")
        before_status = self.git(self.repo, "status", "--porcelain", "--untracked-files=all")
        real_invoke = __import__("agent_workflow.git", fromlist=["_invoke"])._invoke
        switches = []

        def track_switch(repo, args, **kwargs):
            if args[0] == "switch":
                switches.append(list(args))
            return real_invoke(repo, args, **kwargs)

        with patch("agent_workflow.git._invoke", side_effect=track_switch), \
             patch("agent_workflow.git._remove_cleanup_path") as cleanup, \
             patch("agent_workflow.git.run_command") as hook:
            with self.assertRaisesRegex(GitLifecycleError, "expected base SHA does not match"):
                start_feature_branch(self.repo, profile, 7, "stacked mismatch", self.github,
                                     "release/v2", "0" * 40)
        self.assertEqual(switches, [])
        cleanup.assert_not_called()
        hook.assert_not_called()
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), before_branch)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), before_head)
        self.assertEqual(self.git(self.repo, "status", "--porcelain", "--untracked-files=all"), before_status)
        self.assertTrue((self.repo / "out/keep.txt").is_file())

    def test_same_branch_skips_cleanup_and_hooks(self):
        (self.repo / ".git/info/exclude").write_text("out/\n", encoding="utf-8")
        (self.repo / "out").mkdir()
        (self.repo / "out/cache").write_text("old\n", encoding="utf-8")
        profile = self.profile(cleanup=("out",), hooks=("echo switched",))
        with patch("agent_workflow.git.run_command") as hook:
            first, status = start_feature_branch(self.repo, profile, 7, "retry me", self.github)
            self.assertEqual(status, 0)
            self.assertTrue(first["switched"])
            self.assertFalse((self.repo / "out").exists())
            (self.repo / "out").mkdir()
            (self.repo / "out/cache").write_text("retry marker\n", encoding="utf-8")
            second, status = start_feature_branch(self.repo, profile, 7, "retry me", self.github)
        self.assertEqual(status, 0)
        self.assertFalse(second["switched"])
        self.assertEqual(second["creation_source"], "current")
        self.assertTrue((self.repo / "out/cache").is_file())
        self.assertEqual(hook.call_count, 1)

    def test_dirty_worktree_fails_before_repository_metadata_or_switch(self):
        (self.repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(GitLifecycleError, "worktree must be clean"):
            start_feature_branch(self.repo, self.profile(), 7, "dirty", self.github)
        self.assertFalse(any(call[0] == "repository" for call in self.github.lifecycle_calls))
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")

    def test_switch_cleanup_hook_order_and_post_switch_failure_retry(self):
        events = []
        profile = self.profile(cleanup=("out",), hooks=("hook one", "hook two"))
        real_invoke = __import__("agent_workflow.git", fromlist=["_invoke"])._invoke

        def invoke(repo, args, **kwargs):
            result = real_invoke(repo, args, **kwargs)
            if args[0] == "switch":
                events.append("switch")
            return result

        real_cleanup = _remove_cleanup_path

        def cleanup(repo, path):
            events.append("cleanup")
            return real_cleanup(repo, path)

        with patch("agent_workflow.git._invoke", side_effect=invoke), \
             patch("agent_workflow.git._remove_cleanup_path", side_effect=cleanup), \
             patch("agent_workflow.git.run_command", side_effect=lambda command, cwd: events.append(command)):
            result, status = start_feature_branch(self.repo, profile, 7, "ordered", self.github)
        self.assertEqual(status, 0)
        self.assertEqual(events, ["switch", "cleanup", "hook one", "hook two"])

        fail_profile = self.profile(hooks=("fails",))
        target = "feature/7-no-rollback"
        with patch("agent_workflow.git.run_command", side_effect=ProcessError("hook command 'fails' exited with status 9", 9)) as hook:
            failed, status = start_feature_branch(self.repo, fail_profile, 7, "no rollback", self.github)
            self.assertEqual(status, 1)
            self.assertEqual(failed["failure"]["stage"], "branch_switch")
            self.assertEqual(failed["branch"], target)
            retry, retry_status = start_feature_branch(self.repo, fail_profile, 7, "no rollback", self.github)
        self.assertEqual(retry_status, 0)
        self.assertFalse(retry["switched"])
        self.assertEqual(hook.call_count, 1)

    def test_post_switch_cleanup_failure_keeps_branch_and_retry_skips_cleanup(self):
        profile = self.profile(cleanup=("out",), hooks=("must not run",))
        with patch("agent_workflow.git._remove_cleanup_path", side_effect=OSError("cleanup denied")) as cleanup, \
             patch("agent_workflow.git.run_command") as hook:
            failed, status = start_feature_branch(self.repo, profile, 7, "cleanup failure", self.github)
            self.assertEqual(status, 1)
            self.assertEqual(failed["failure"]["stage"], "cleanup")
            self.assertEqual(failed["branch"], "feature/7-cleanup-failure")
            retry, retry_status = start_feature_branch(self.repo, profile, 7, "cleanup failure", self.github)
        self.assertEqual(retry_status, 0)
        self.assertFalse(retry["switched"])
        self.assertEqual(cleanup.call_count, 1)
        hook.assert_not_called()

    def test_cleanup_unlinks_symlink_without_touching_external_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("safe\n", encoding="utf-8")
        (self.repo / "linked").symlink_to(outside, target_is_directory=True)
        _remove_cleanup_path(self.repo, "linked")
        self.assertFalse((self.repo / "linked").exists())
        self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "safe\n")

    def test_shell_metacharacters_in_description_are_inert(self):
        result, status = start_feature_branch(self.repo, self.profile(), 7,
                                             "$(touch pwn); echo harmless", self.github)
        self.assertEqual(status, 0)
        self.assertEqual(result["branch"], "feature/7-touch-pwn-echo-harmless")
        self.assertFalse((self.repo / "pwn").exists())

    def test_invalid_issue_fails_before_branch_lifecycle(self):
        args = type("Args", (), {"repo": str(self.repo), "issue": 1, "description": ["not allowed"]})()
        self.github.issue_data["state"] = "closed"
        with patch("agent_workflow.cli._repo_arg", return_value=self.repo), \
             patch("agent_workflow.cli.load_profile", return_value=self.profile()), \
             patch("agent_workflow.cli._gh", return_value=self.github), \
             patch("agent_workflow.cli.start_feature_branch") as start:
            with self.assertRaises(ContextError):
                _start_feature_branch(args)
        start.assert_not_called()
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")


class DocumentTests(unittest.TestCase):
    def test_repo_docs_validate_locally_without_network(self):
        self.assertEqual(validate_docs(ROOT), [])

    def test_marker_headings_and_local_links_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "docs/specs").mkdir(parents=True)
            doc = repo / "docs/specs/x.md"
            doc.write_text("""<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Sample
## Purpose
## Scope
## Normative requirements
## Observable behavior
## Error and boundary behavior
## Security and privacy
## Verification strategy
[good](../other.md) [bad](missing.md) [external](https://example.invalid)
```md
[ignored](not-real.md)
```
""", encoding="utf-8")
            (repo / "docs/other.md").write_text("# Other\n", encoding="utf-8")
            errors = validate_markdown_file(doc, repo)
            self.assertEqual(len(errors), 1)
            self.assertIn("missing.md", errors[0])

    def test_fragment_link_must_resolve(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "a.md").write_text("[x](b.md#missing)\n", encoding="utf-8")
            (repo / "b.md").write_text("# Exists\n", encoding="utf-8")
            errors = validate_markdown_file(repo / "a.md", repo)
            self.assertTrue(any("fragment" in error for error in errors))
            self.assertTrue(any("b.md" in error for error in errors))

    def test_reference_link_targets_and_missing_references_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "index.md").write_text("[good][target] [bad][missing]\n\n[target]: page.md\n", encoding="utf-8")
            (repo / "page.md").write_text("# Page\n", encoding="utf-8")
            errors = validate_markdown_file(repo / "index.md", repo)
            self.assertTrue(any("unresolved Markdown reference" in error for error in errors))

    def test_structured_document_impact_routes_decisions_and_legacy_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "docs/specs").mkdir(parents=True)
            (repo / "docs/specs/workflow.md").write_text("# Workflow\n", encoding="utf-8")
            (repo / "docs/specs/runtime.md").write_text("# Runtime\n", encoding="utf-8")
            body = """## Document impact
- Specification: [workflow](docs/specs/workflow.md), [runtime](https://github.com/owner/repo/blob/main/docs/specs/runtime.md)
- Design: unchanged — The architecture remains unchanged.
- Status: evidence-only — Verification evidence belongs on the Issue and PR.
"""
            owners, planned, impact, errors = resolve_document_impact(body, repo, "owner/repo")
            self.assertEqual(owners, ["docs/specs/workflow.md", "docs/specs/runtime.md"])
            self.assertEqual(planned, [])
            self.assertEqual(errors, [])
            self.assertEqual(impact["format"], "structured")
            self.assertEqual(impact["specification"]["decision"], "linked")
            self.assertEqual(impact["design"]["decision"], "unchanged")
            self.assertEqual(impact["status"]["decision"], "evidence-only")

            legacy = "## Document impact\n- [workflow](docs/specs/workflow.md)\n"
            legacy_owners, legacy_planned, legacy_impact, legacy_errors = resolve_document_impact(legacy, repo)
            self.assertEqual(legacy_owners, ["docs/specs/workflow.md"])
            self.assertEqual(legacy_planned, [])
            self.assertEqual(legacy_impact["format"], "legacy")
            self.assertEqual(legacy_errors, [])

    def test_document_impact_rejects_wrong_tree_malformed_and_missing_decisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "docs/design").mkdir(parents=True)
            (repo / "docs/design/design.md").write_text("# Design\n", encoding="utf-8")
            wrong_tree = """## Document impact
- Specification: [design](docs/design/design.md)
- Design: unchanged — Design is not changing.
- Status: unchanged — Evidence remains in the Issue.
"""
            owners, planned, impact, errors = resolve_document_impact(wrong_tree, repo)
            self.assertEqual(owners, [])
            self.assertEqual(planned, [])
            self.assertEqual(impact["specification"]["decision"], "invalid")
            self.assertTrue(any("must target docs/specs" in error for error in errors))

            malformed = """## Document impact
- Specification: unchanged —
- Design: unchanged — Design is not changing.
- Status: evidence-only — <reason>
"""
            _, _, _, malformed_errors = resolve_document_impact(malformed, repo)
            self.assertTrue(any("requires a concrete reason" in error for error in malformed_errors))

    def test_issue_scoped_docs_validate_only_declared_owners_and_missing_owner_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".git").mkdir()
            (repo / ".agent").mkdir()
            profile = profile_fixture()
            (repo / ".agent/project.json").write_text(json.dumps(profile), encoding="utf-8")
            (repo / "docs/specs").mkdir(parents=True)
            required = """<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Owner
## Purpose
## Scope
## Normative requirements
## Observable behavior
## Error and boundary behavior
## Security and privacy
## Verification strategy
"""
            (repo / "docs/specs/owned.md").write_text(required, encoding="utf-8")
            (repo / "docs/specs/unrelated.md").write_text("unrelated legacy defect\n", encoding="utf-8")
            gh = FakeGitHub("""## Document impact
- Specification: [owned](docs/specs/owned.md)
- Design: unchanged — No design changes are needed.
- Status: evidence-only — Evidence will be recorded on the Issue.
""")
            args = type("Args", (), {"repo": str(repo), "issue": 1, "changed": None})()
            with patch("agent_workflow.cli._repo_arg", return_value=repo), \
                 patch("agent_workflow.cli._gh", return_value=gh):
                result, status = _validate_docs(args)
            self.assertEqual(status, 0)
            self.assertTrue(result["valid"])
            self.assertEqual(result["files"], 1)
            gh.issue_data["body"] = "## Affected components\n- one\n\n" + gh.issue_data["body"]
            with patch("agent_workflow.context._pull_requests", return_value=[]), \
                 patch("agent_workflow.context._git", return_value="a" * 40):
                context = build_context(repo, 1, gh)
            self.assertEqual(context["document_owners"], ["docs/specs/owned.md"])
            self.assertEqual(context["document_impact"]["format"], "structured")
            self.assertEqual(context["document_impact"]["specification"]["decision"], "linked")

            gh.issue_data["body"] = """## Document impact
- Specification: [planned](docs/specs/planned.md)
- Design: unchanged — No design changes are needed.
- Status: unchanged — No status document is needed.
"""
            with patch("agent_workflow.cli._repo_arg", return_value=repo), \
                 patch("agent_workflow.cli._gh", return_value=gh), \
                 patch("agent_workflow.cli.run_command") as hook:
                result, status = _validate_docs(args)
            self.assertEqual(status, 1)
            self.assertFalse(result["valid"])
            self.assertTrue(any("planned document owner is missing" in error for error in result["errors"]))
            hook.assert_not_called()


class ChangedDocumentValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "-m", message)

    def test_changed_scope_checks_only_changed_docs_and_ignores_deletions(self):
        specs = self.repo / "docs/specs"
        specs.mkdir(parents=True)
        good = """<!-- agent-doc-type: specification -->
<!-- agent-doc-schema: 2 -->
# Good
## Purpose
## Scope
## Normative requirements
## Observable behavior
## Error and boundary behavior
## Security and privacy
## Verification strategy
"""
        (specs / "changed.md").write_text(good, encoding="utf-8")
        (specs / "unchanged.md").write_text("unrelated legacy defect\n", encoding="utf-8")
        (specs / "deleted.md").write_text("deleted legacy defect\n", encoding="utf-8")
        self.commit("baseline docs")
        base = self.git("rev-parse", "HEAD")
        (specs / "changed.md").write_text("# Broken changed document\n", encoding="utf-8")
        (specs / "deleted.md").unlink()
        self.commit("change one document and delete another")

        paths = changed_document_paths(self.repo, base)
        self.assertEqual(paths, [specs / "changed.md"])
        errors = validate_docs(self.repo, paths)
        self.assertTrue(errors)
        self.assertTrue(all("changed.md" in error for error in errors), errors)
        args = type("Args", (), {"repo": str(self.repo), "issue": None, "changed": base})()
        with patch("agent_workflow.cli._repo_arg", return_value=self.repo):
            result, status = _validate_docs(args)
        self.assertEqual(status, 1)
        self.assertEqual(result["scope"], "changed")
        self.assertEqual(result["files"], 1)
        self.assertTrue(all("changed.md" in error for error in result["errors"]))

    def test_unknown_changed_base_fails_without_hooks_or_broadening(self):
        args = type("Args", (), {"repo": str(self.repo), "issue": None, "changed": "not-a-ref"})()
        with patch("agent_workflow.cli._repo_arg", return_value=self.repo), \
             patch("agent_workflow.cli.run_command") as hook:
            with self.assertRaisesRegex(GitLifecycleError, "unknown --changed base ref"):
                _validate_docs(args)
        hook.assert_not_called()

    def test_validate_doc_selectors_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["validate-docs", "--issue", "1", "--changed", "main"])


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.gh = FakeGitHub()

    def tearDown(self):
        self.temp.cleanup()

    def source(self, content: bytes) -> Path:
        path = self.repo / "source.md"
        path.write_bytes(content)
        return path

    def test_pointer_error_shows_canonical_block_and_forbids_appended_prose(self):
        from agent_workflow.contracts import parse_pointer
        with self.assertRaises(ContractError) as raised:
            parse_pointer("## Implementation Contract\nComment ID: bad\nSHA-256: nope\nState: approved\nextra prose")
        message = str(raised.exception)
        self.assertIn("## Implementation Contract\nComment ID: <comment-id>\nSHA-256: <sha256>\nState: approved", message)
        self.assertIn("do not append prose", message)

    def test_pointer_remains_strict_about_extra_fields_and_prose(self):
        from agent_workflow.contracts import parse_pointer
        good = "## Implementation Contract\nComment ID: 123\nSHA-256: " + "a" * 64 + "\nState: approved\n"
        self.assertEqual(parse_pointer(good), (123, "a" * 64))
        with self.assertRaises(ContractError):
            parse_pointer(good + "Additional prose\n")

    def test_exact_utf8_bytes_and_line_endings_are_preserved(self):
        raw = "# Contract\r\n\r\nCafe\u0301\n".encode("utf-8")
        metadata = save_contract(self.repo, 1, self.source(raw))
        self.assertEqual((self.repo / ".agent-state/issues/1/implementation-contract.md").read_bytes(), raw)
        self.assertEqual(metadata["sha256"], hashlib.sha256(raw).hexdigest())

    def test_raw_size_nul_and_obvious_credentials_are_rejected(self):
        for raw in (b"x" * 65537, b"a\x00b", b"token=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"):
            with self.subTest(raw=raw[:12]), self.assertRaises(ContractError):
                validate_payload(raw, 1)

    def test_reviewer_checklist_h2_authoring_rule_is_enforced_before_github_mutation(self):
        intro = b"The implementer must self-review every item in this checklist.\n\n"
        block = (b"<!-- AGENT_REVIEWER_CHECKLIST_V1 -->\n- [ ] canonical item\n"
                 b"<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->\n")
        canonical = b"## Reviewer Checklist\n" + intro + block
        validate_reviewer_checklist_authoring(canonical)
        good = self.source(canonical)
        publish_contract(self.repo, 1, self.gh, good)

        bad = self.source(
            b"## Reviewer Checklist\n" + block + b"Unique runtime requirement outside checklist.\n"
        )
        gh = FakeGitHub()
        with self.assertRaisesRegex(ContractError, "must not contain prose"):
            publish_contract(self.repo / "bad", 1, gh, bad)
        self.assertEqual(gh.comments, [])
        self.assertEqual([call for call in gh.lifecycle_calls if call[0] == "issue"], [])

    def test_publish_readback_verify_and_same_sha_idempotence(self):
        raw = "# Contract\r\n\nnaïve\n".encode()
        source = self.source(raw)
        result = publish_contract(self.repo, 1, self.gh, source)
        self.assertFalse(result["idempotent"])
        payload, digest = parse_comment(self.gh.comments[0]["body"], 1)
        self.assertEqual(payload, raw)
        self.assertEqual(digest, result["sha256"])
        self.assertTrue(verify_contract(self.repo, 1, self.gh)["verified"])
        again = publish_contract(self.repo, 1, self.gh, source)
        self.assertTrue(again["idempotent"])
        self.assertEqual(len(self.gh.comments), 1)

    def test_changed_sha_requires_explicit_supersede(self):
        publish_contract(self.repo, 1, self.gh, self.source(b"first"))
        with self.assertRaises(ContractError):
            publish_contract(self.repo, 1, self.gh, self.source(b"second"))
        result = publish_contract(self.repo, 1, self.gh, self.source(b"second"), supersede=True)
        self.assertEqual(len(self.gh.comments), 2)
        self.assertNotEqual(result["sha256"], sha256(b"first"))

    def test_restore_refuses_stale_mirror_and_backs_it_up_explicitly(self):
        original = b"approved bytes"
        publish_contract(self.repo, 1, self.gh, self.source(original))
        stale = b"local stale bytes"
        save_contract(self.repo, 1, self.source(stale))
        with self.assertRaises(ContractError):
            restore_contract(self.repo, 1, self.gh)
        result = restore_contract(self.repo, 1, self.gh, replace_stale=True)
        self.assertEqual(Path(result["path"]).read_bytes(), original)
        backup = Path(result["path"]).with_name(f"implementation-contract.{sha256(stale)}.bak")
        self.assertEqual(backup.read_bytes(), stale)

    def test_wrong_issue_comment_header_fails_closed(self):
        with self.assertRaises(ContractError):
            parse_comment("<!-- agent-contract:v1 issue=2 sha256=" + "0" * 64 + " bytes=1 -->\n\nx", 1)

    def test_wrong_comment_association_fails_verification(self):
        publish_contract(self.repo, 1, self.gh, self.source(b"approved"))
        self.gh.comments[0]["issue_url"] = f"https://api.github.com/repos/{self.gh.repo}/issues/9"
        with self.assertRaises(ContractError):
            verify_contract(self.repo, 1, self.gh)

    def test_restore_and_verify_fetch_only_the_named_comment(self):
        publish_contract(self.repo, 1, self.gh, self.source(b"approved bytes"))
        with patch.object(self.gh, "issue_comments", side_effect=AssertionError("must not list comments")):
            restore_contract(self.repo, 1, self.gh)
            self.assertTrue(verify_contract(self.repo, 1, self.gh)["verified"])

    def test_concurrent_issue_body_change_does_not_update_pointer_or_local_state(self):
        class RacingGitHub(FakeGitHub):
            def __init__(self):
                super().__init__("")
                self.reads = 0
                self.updates = 0

            def issue(self, number):
                self.reads += 1
                if self.reads >= 2:
                    self.issue_data["body"] = "Concurrent unrelated change"
                return super().issue(number)

            def update_issue(self, number, body):
                self.updates += 1
                return super().update_issue(number, body)

        gh = RacingGitHub()
        with self.assertRaises(ContractError):
            publish_contract(self.repo, 1, gh, self.source(b"payload"))
        self.assertEqual(gh.updates, 0)
        self.assertFalse((self.repo / ".agent-state/issues/1/implementation-contract.md").exists())


class ReviewTests(unittest.TestCase):
    def _install_historical_contract(self, gh: FakeGitHub, contract: bytes) -> int:
        contract_id = 99
        digest = hashlib.sha256(contract).hexdigest()
        body = (
            f"<!-- agent-contract:v1 issue=1 sha256={digest} bytes={len(contract)} -->\n\n"
            + contract.decode("utf-8")
        )
        gh.comments.append({
            "id": contract_id,
            "issue_url": f"https://api.github.com/repos/{gh.repo}/issues/1",
            "body": body,
        })
        gh.issue_data["body"] = (
            "## Reviewer Checklist\n"
            "The implementer must self-review every item in this checklist.\n\n"
            "<!-- AGENT_REVIEWER_CHECKLIST_V1 -->\n"
            "- [ ] Issue checklist point\n"
            "<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->\n\n"
            "## Implementation Contract\n\n"
            f"Comment ID: {contract_id}\nSHA-256: {digest}\nState: approved\n"
        )
        return contract_id

    def _ready_to_publish(self, repo: Path, gh: FakeGitHub):
        _, _, surface = install_review_contract(repo, gh)
        head = "f" * 40
        original_body = _with_pointer(
            "Closes #1\n\n## Verification\nchecks passed\n\n## Untested\nproduct smoke test unavailable\n",
            77, "a" * 64, "e" * 40, "d" * 64, 88, "c" * 64,
        )
        gh.pull_data = {
            "number": 2, "state": "open", "draft": False,
            "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
            "body": original_body,
        }
        prepare_review(repo, 1, 2, gh)
        path = review_path(repo, 1, 2)
        draft = complete_review_draft(json.loads(path.read_text(encoding="utf-8")))
        path.write_text(json.dumps(draft), encoding="utf-8")
        return head, original_body, surface

    def test_canonical_block_wins_and_fallback_heading_is_narrow(self):
        text = """## 9. Reviewer Checklist（contract）
- [ ] fallback item
<!-- AGENT_REVIEWER_CHECKLIST_V1 -->
- [ ] canonical item
<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->
"""
        self.assertEqual(_extract_items(text), ["canonical item"])
        self.assertEqual(_extract_items("## Checklist\n- [ ] ignored"), [])
        self.assertEqual(_extract_items("## 1. Reviewer Checklist (Issue)\n- [ ] accepted"), ["accepted"])
        self.assertEqual(_extract_items("```md\n## Reviewer Checklist\n- [ ] ignored\n```"), [])

    def test_review_draft_requires_results_and_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "review.json"
            draft = {"schema_version": 2, "issue": 1, "pr": 2, "head": "a" * 40,
                     "contract_comment_id": 123, "contract_sha256": "c" * 64,
                     "checklist_sha256": "b" * 64,
                     "contract_sections": [{"id": "S001", "title": "Architecture",
                                            "section_sha256": "d" * 64,
                                            "result": "pending", "evidence": ""}],
                     "items": [{"id": "C001", "text": "check", "result": "pending", "evidence": ""}]}
            path.write_text(json.dumps(draft), encoding="utf-8")
            with self.assertRaisesRegex(ReviewError, "S001.*concrete evidence"):
                load_review(path)

    def test_contract_review_units_hash_exact_bytes_and_ignore_fenced_headings(self):
        newline = bytes((13, 10))
        fence = bytes((96, 96, 96))
        lines = [
            b"Contract preamble.", b"", b"## First", b"one", fence + b"md",
            b"## Fake Section", fence, b"", b"## Reviewer Checklist",
            b"- [ ] check", b"## Extra", b"two", b"",
        ]
        payload = newline.join(lines)
        units = contract_review_units(payload)
        first = newline.join(lines[2:8]) + newline
        extra = newline.join(lines[10:])
        self.assertEqual([unit["id"] for unit in units], ["P000", "S001", "S002", "S003"])
        self.assertEqual(
            [unit["title"] for unit in units],
            ["Contract Preamble", "First", "Reviewer Checklist", "Extra"],
        )
        self.assertEqual(units[0]["section_sha256"], hashlib.sha256(newline.join(lines[:2]) + newline).hexdigest())
        self.assertEqual(units[1]["section_sha256"], hashlib.sha256(first).hexdigest())
        legacy_checklist = newline.join(lines[8:10]) + newline
        self.assertEqual(units[2]["section_sha256"], hashlib.sha256(legacy_checklist).hexdigest())
        self.assertEqual(units[3]["section_sha256"], hashlib.sha256(extra).hexdigest())

    def test_strict_canonical_first_heading_does_not_leak_into_preamble(self):
        newline = bytes((13, 10))
        contract = newline.join([
            b"## Reviewer Checklist",
            b"<!-- AGENT_REVIEWER_CHECKLIST_V1 -->",
            b"- [ ] canonical item",
            b"<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->",
            b"",
            b"## Further Work",
            b"content",
            b"",
        ])

        self.assertEqual(classify_reviewer_checklist_h2(contract).state, "strict-canonical")
        units = contract_review_units(contract)
        self.assertEqual([unit["id"] for unit in units], ["S001"])
        self.assertEqual([unit["title"] for unit in units], ["Further Work"])
        further_work = contract.index(b"## Further Work" + newline)
        self.assertEqual(
            units[0]["section_sha256"], hashlib.sha256(contract[further_work:]).hexdigest()
        )
        self.assertEqual(_extract_items(contract.decode("utf-8")), ["canonical item"])

    def test_strict_checklist_preamble_ends_at_first_h2_preserving_crlf(self):
        newline = bytes((13, 10))
        preamble = b"Intro.\r\n\r\n"
        contract = preamble + newline.join([
            b"## Reviewer Checklist",
            b"<!-- AGENT_REVIEWER_CHECKLIST_V1 -->",
            b"- [ ] canonical item",
            b"<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->",
            b"",
            b"## Further Work",
            b"content",
            b"",
        ])

        units = contract_review_units(contract)
        self.assertEqual([unit["id"] for unit in units], ["P000", "S001"])
        self.assertEqual([unit["title"] for unit in units], ["Contract Preamble", "Further Work"])
        self.assertEqual(units[0]["section_sha256"], hashlib.sha256(preamble).hexdigest())
        further_work = contract.index(b"## Further Work" + newline)
        self.assertEqual(
            units[1]["section_sha256"], hashlib.sha256(contract[further_work:]).hexdigest()
        )

    def test_strict_checklist_only_has_no_contract_units(self):
        contract = (
            b"## Reviewer Checklist\r\n"
            b"<!-- AGENT_REVIEWER_CHECKLIST_V1 -->\r\n"
            b"- [ ] canonical item\r\n"
            b"<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->\r\n"
        )

        self.assertEqual(contract_review_units(contract), [])
        self.assertEqual(_extract_items(contract.decode("utf-8")), ["canonical item"])

    def test_strict_checklist_only_contract_prepares_and_validates_v2_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            contract = (
                b"## Reviewer Checklist\r\n"
                b"<!-- AGENT_REVIEWER_CHECKLIST_V1 -->\r\n"
                b"- [ ] canonical item\r\n"
                b"<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->\r\n"
            )
            install_review_contract(repo, gh, contract)
            gh.pull_data = {
                "number": 2,
                "base": {"repo": {"full_name": gh.repo}},
                "head": {"sha": "f" * 40},
                "body": "Closes #1",
            }

            prepared = prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            draft = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(prepared["contract_section_count"], 0)
            self.assertEqual(draft["contract_sections"], [])
            self.assertEqual([item["text"] for item in draft["items"]], [
                "canonical item", "Issue checklist point",
            ])
            path.write_text(
                json.dumps(complete_review_draft(draft)), encoding="utf-8"
            )
            args = type("Args", (), {"repo": None, "input": None, "issue": 1, "pr": 2})()
            with patch("agent_workflow.cli._repo_arg", return_value=repo), \
                 patch("agent_workflow.cli._gh", return_value=gh):
                validated = _validate_self_review(args)

            self.assertTrue(validated["valid"])
            self.assertEqual(validated["contract_section_count"], 0)
            self.assertEqual(validated["items"], 2)

    def test_legacy_checklist_first_is_s001_without_artificial_preamble(self):
        contract = (
            b"## Reviewer Checklist\r\n"
            b"- [ ] legacy item\r\n"
            b"\r\n"
            b"## Further Work\r\n"
            b"content\r\n"
        )
        gh = FakeGitHub()
        self._install_historical_contract(gh, contract)

        surface = load_review_surface(1, gh.issue_data["body"], gh)
        self.assertEqual([unit["id"] for unit in surface["contract_sections"]], ["S001", "S002"])
        self.assertEqual([unit["title"] for unit in surface["contract_sections"]], [
            "Reviewer Checklist", "Further Work",
        ])
        self.assertEqual([item["text"] for item in surface["items"]], [
            "legacy item", "Issue checklist point",
        ])
        self.assertEqual(
            surface["contract_sections"][0]["section_sha256"],
            hashlib.sha256(contract[:contract.index(b"## Further Work")]).hexdigest(),
        )

    def test_contract_without_h2_remains_exact_preamble_unit(self):
        contract = b"Exact no-heading payload.\r\n\r\nSecond line.\n"

        units = contract_review_units(contract)

        self.assertEqual([unit["id"] for unit in units], ["P000"])
        self.assertEqual(units[0]["title"], "Contract Preamble")
        self.assertEqual(units[0]["section_sha256"], hashlib.sha256(contract).hexdigest())

    def test_legacy_fallback_contract_is_readable_and_v2_reviewable(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            contract = (
                b"## Baseline\nold contract bytes\n\n"
                b"## Reviewer Checklist\n- [ ] legacy item\nHistorical architecture note.\n\n"
                b"## Additional Requirements\nlegacy-safe behavior\n"
            )
            contract_id = self._install_historical_contract(gh, contract)
            original_contract_comment = gh.comments[0]["body"]
            classification = classify_reviewer_checklist_h2(contract)
            self.assertEqual(classification.state, "legacy/non-canonical")
            surface = load_review_surface(1, gh.issue_data["body"], gh)
            self.assertEqual(surface["contract_comment_id"], contract_id)
            self.assertEqual(surface["items"][0]["text"], "legacy item")
            checklist_section = next(
                section for section in surface["contract_sections"]
                if section["title"] == "Reviewer Checklist"
            )
            start = contract.index(b"## Reviewer Checklist\n")
            end = contract.index(b"## Additional Requirements\n")
            self.assertEqual(
                checklist_section["section_sha256"], hashlib.sha256(contract[start:end]).hexdigest()
            )

            head = "f" * 40
            gh.pull_data = {
                "number": 2, "state": "open", "draft": False,
                "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
                "body": "Closes #1\n\n## Verification\npassed\n\n## Untested\nnot run\n",
            }
            prepared = prepare_review(repo, 1, 2, gh)
            self.assertEqual(prepared["contract_comment_id"], contract_id)
            path = review_path(repo, 1, 2)
            prepared_draft = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("Reviewer Checklist", [s["title"] for s in prepared_draft["contract_sections"]])
            path.write_text(
                json.dumps(complete_review_draft(json.loads(path.read_text(encoding="utf-8")))),
                encoding="utf-8",
            )
            published = publish_review(repo, 1, 2, gh)
            self.assertEqual(published["schema_version"], 2)
            self.assertEqual(published["contract_comment_id"], contract_id)
            self.assertEqual(len(gh.comments), 1)
            self.assertEqual(gh.comments[0]["body"], original_contract_comment)

    def test_legacy_canonical_block_with_extra_prose_is_covered_as_contract_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            contract = (
                b"## Reviewer Checklist\n"
                b"<!-- AGENT_REVIEWER_CHECKLIST_V1 -->\n- [ ] canonical item\n"
                b"<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->\n"
                b"Historical prose remains contract content.\n\n## Further Work\ncontent\n"
            )
            contract_id = self._install_historical_contract(gh, contract)
            with self.assertRaisesRegex(ContractError, "must not contain prose"):
                validate_reviewer_checklist_authoring(contract)
            surface = load_review_surface(1, gh.issue_data["body"], gh)
            self.assertEqual(surface["contract_comment_id"], contract_id)
            self.assertEqual(surface["items"][0]["text"], "canonical item")
            checklist_section = next(
                section for section in surface["contract_sections"]
                if section["title"] == "Reviewer Checklist"
            )
            start = contract.index(b"## Reviewer Checklist\n")
            end = contract.index(b"## Further Work\n")
            self.assertEqual(
                checklist_section["section_sha256"], hashlib.sha256(contract[start:end]).hexdigest()
            )

    def test_strict_canonical_checklist_h2_is_excluded_from_contract_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            contract, _, surface = install_review_contract(Path(temporary), FakeGitHub())
            self.assertEqual(classify_reviewer_checklist_h2(b"## No checklist\nbody\n").state, "absent")
            self.assertEqual(classify_reviewer_checklist_h2(contract).state, "strict-canonical")
            self.assertNotIn("Reviewer Checklist", [s["title"] for s in surface["contract_sections"]])

    def test_prepare_review_binds_contract_units_checklist_and_exact_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            payload, published_contract, surface = install_review_contract(repo, gh)
            head = "f" * 40
            gh.pull_data = {"number": 2, "base": {"repo": {"full_name": gh.repo}},
                            "head": {"sha": head}, "body": "Closes #1"}
            result = prepare_review(repo, 1, 2, gh)
            draft = json.loads(review_path(repo, 1, 2).read_text(encoding="utf-8"))
            self.assertEqual(draft["schema_version"], 2)
            self.assertEqual(draft["head"], head)
            self.assertEqual(draft["contract_comment_id"], published_contract["comment_id"])
            self.assertEqual(draft["contract_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(draft["contract_sha256"], published_contract["sha256"])
            self.assertEqual(draft["checklist_sha256"], surface["checklist_sha256"])
            self.assertEqual([s["title"] for s in draft["contract_sections"]],
                             ["Contract Preamble", "Architecture Decisions", "Document impact"])
            self.assertNotIn("Reviewer Checklist", [s["title"] for s in draft["contract_sections"]])
            self.assertEqual([item["id"] for item in draft["items"]], ["C001", "I001"])
            self.assertEqual(result["contract_section_count"], 3)
            self.assertTrue(prepare_review(repo, 1, 2, gh)["reused"])

    def test_validate_self_review_rejects_superseded_contract_with_same_checklist(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            payload_a, _, _ = install_review_contract(repo, gh)
            head = "f" * 40
            gh.pull_data = {
                "number": 2, "base": {"repo": {"full_name": gh.repo}},
                "head": {"sha": head}, "body": "Closes #1",
            }
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            path.write_text(json.dumps(complete_review_draft(json.loads(path.read_text()))), encoding="utf-8")
            args = type("Args", (), {"repo": None, "input": None, "issue": 1, "pr": 2})()
            with patch("agent_workflow.cli._repo_arg", return_value=repo), \
                 patch("agent_workflow.cli._gh", return_value=gh):
                result = _validate_self_review(args)
                self.assertEqual(result["contract_sha256"], hashlib.sha256(payload_a).hexdigest())
                self.assertEqual(result["schema_version"], 2)

                payload_b = payload_a.replace(b"Review the complete contract.", b"Review revised contract body.")
                source = repo / "contract-b.md"
                source.write_bytes(payload_b)
                publish_contract(repo, 1, gh, source, supersede=True)
                with self.assertRaisesRegex(ReviewError, "current approved Implementation Contract comment ID"):
                    _validate_self_review(args)

    def test_publish_v2_binds_contract_metadata_and_pointer_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            _, _, surface = install_review_contract(repo, gh)
            head = "f" * 40
            gh.pull_data = {
                "number": 2, "state": "open", "draft": False,
                "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
                "body": "Closes #1\n\n## Verification\nchecks passed\n\n## Untested\nproduct smoke test unavailable\n",
            }
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            draft = complete_review_draft(json.loads(path.read_text(encoding="utf-8")))
            path.write_text(json.dumps(draft), encoding="utf-8")
            result = publish_review(repo, 1, 2, gh)
            self.assertEqual(result["schema_version"], 2)
            self.assertEqual(result["contract_comment_id"], surface["contract_comment_id"])
            self.assertEqual(result["contract_sha256"], surface["contract_sha256"])
            self.assertIn(f"Contract Comment ID: {surface['contract_comment_id']}", gh.pull_data["body"])
            self.assertIn(f"Contract SHA-256: {surface['contract_sha256']}", gh.pull_data["body"])
            comment = gh.pull_comments[result["comment_id"]]
            self.assertIn(
                f"<!-- agent-self-review:v2 issue=1 pr=2 head={head} "
                f"contract_comment={surface['contract_comment_id']} contract={surface['contract_sha256']} "
                f"checklist={surface['checklist_sha256']} -->",
                comment["body"],
            )
            self.assertNotIn("Review the complete contract.", comment["body"])
            readback = validate_public_review(1, 2, gh)
            self.assertFalse(readback["stale"])
            self.assertTrue(readback["contract_conformance"])
            self.assertEqual(readback["contract_comment_id"], surface["contract_comment_id"])
            self.assertEqual(readback["current_contract_comment_id"], surface["contract_comment_id"])
            self.assertEqual(readback["contract_sha256"], surface["contract_sha256"])
            self.assertEqual(readback["checklist_sha256"], surface["checklist_sha256"])
            self.assertEqual(readback["head"], head)

    def test_named_comment_get_readback_precedes_pointer_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            self._ready_to_publish(repo, gh)
            events = []
            create = gh.create_pull_comment
            named_get = gh.pull_comment
            update = gh.update_pull

            def create_comment(number, body):
                events.append("POST")
                return create(number, body)

            def read_comment(comment_id):
                events.append("named GET")
                return named_get(comment_id)

            def update_pointer(number, body):
                events.append("pointer PATCH")
                return update(number, body)

            gh.create_pull_comment = create_comment
            gh.pull_comment = read_comment
            gh.update_pull = update_pointer
            publish_review(repo, 1, 2, gh)
            self.assertEqual(events, ["POST", "named GET", "pointer PATCH"])

    def test_named_comment_body_mismatch_leaves_orphan_and_old_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            _, original_body, _ = self._ready_to_publish(repo, gh)
            read_comment = gh.pull_comment
            updates = []
            gh.pull_comment = lambda comment_id: dict(read_comment(comment_id), body="truncated")
            update = gh.update_pull

            def track_update(number, body):
                updates.append(body)
                return update(number, body)

            gh.update_pull = track_update
            with self.assertRaisesRegex(ReviewError, "readback body differs"):
                publish_review(repo, 1, 2, gh)
            self.assertEqual(gh.pull_data["body"], original_body)
            self.assertEqual(updates, [])
            self.assertEqual(len(gh.pull_comments), 1)

    def test_named_comment_association_mismatch_leaves_orphan_and_old_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            _, original_body, _ = self._ready_to_publish(repo, gh)
            read_comment = gh.pull_comment
            updates = []
            gh.pull_comment = lambda comment_id: dict(
                read_comment(comment_id), issue_url=f"https://api.github.com/repos/{gh.repo}/issues/999"
            )
            update = gh.update_pull

            def track_update(number, body):
                updates.append(body)
                return update(number, body)

            gh.update_pull = track_update
            with self.assertRaisesRegex(ReviewError, "belongs to a different PR"):
                publish_review(repo, 1, 2, gh)
            self.assertEqual(gh.pull_data["body"], original_body)
            self.assertEqual(updates, [])
            self.assertEqual(len(gh.pull_comments), 1)

    def test_named_comment_read_failure_leaves_orphan_and_old_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            _, original_body, _ = self._ready_to_publish(repo, gh)
            updates = []
            update = gh.update_pull

            def track_update(number, body):
                updates.append(body)
                return update(number, body)

            gh.pull_comment = lambda _comment_id: (_ for _ in ()).throw(GitHubError("read failed"))
            gh.update_pull = track_update
            with self.assertRaisesRegex(ReviewError, "could not be read back by ID"):
                publish_review(repo, 1, 2, gh)
            self.assertEqual(gh.pull_data["body"], original_body)
            self.assertEqual(updates, [])
            self.assertEqual(len(gh.pull_comments), 1)

    def test_same_checklist_contract_supersession_invalidates_v2_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            payload_a, _, surface_a = install_review_contract(repo, gh)
            head = "f" * 40
            gh.pull_data = {
                "number": 2, "state": "open", "draft": False,
                "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
                "body": "Closes #1\n\n## Verification\nchecks passed\n\n## Untested\nexternal smoke test unavailable\n",
            }
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            path.write_text(json.dumps(complete_review_draft(json.loads(path.read_text()))), encoding="utf-8")
            published = publish_review(repo, 1, 2, gh)
            payload_b = payload_a.replace(b"Review the complete contract.", b"Review revised contract body.")
            source = repo / "superseded-contract.md"
            source.write_bytes(payload_b)
            superseded = publish_contract(repo, 1, gh, source, supersede=True)
            self.assertNotEqual(superseded["sha256"], surface_a["contract_sha256"])
            current = validate_public_review(1, 2, gh)
            self.assertTrue(current["stale"])
            self.assertTrue(current["contract_stale"])
            self.assertFalse(current["checklist_stale"])
            self.assertEqual(current["sha256"], published["sha256"])
            (repo / ".agent").mkdir()
            profile = {
                "schema_version": 2, "initialized": False, "project_name": "review-test",
                "components": [{
                    "id": "root", "roots": ["."], "stacks": [], "application_types": ["cli"],
                    "targets": [], "hooks": {},
                }],
                "branch": {"required_checks": ["CI"]},
                "milestones": {"mode": "disabled", "version_source": "auto"},
                "hooks": {},
            }
            (repo / ".agent/project.json").write_text(json.dumps(profile), encoding="utf-8")
            gh.pull_data["base"] = {"ref": "main", "repo": {"full_name": gh.repo}}
            gh.runs = [{
                "name": "CI", "head_sha": head, "status": "completed", "conclusion": "success",
            }]
            handoff = delivery_check(repo, 1, 2, gh)
            self.assertFalse(handoff["passed"])
            self.assertTrue(any("approved Implementation Contract" in error for error in handoff["errors"]))
            prior_comment_count = len(gh.pull_comments)
            with self.assertRaisesRegex(ReviewError, "comment ID changed"):
                publish_review(repo, 1, 2, gh)
            self.assertEqual(len(gh.pull_comments), prior_comment_count)
            gh.pull_data["head"]["sha"] = "a" * 40
            new_head = validate_public_review(1, 2, gh)
            self.assertTrue(new_head["head_stale"])

    def test_changed_contract_comment_id_with_same_sha_stales_review_and_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            _, approved, surface = install_review_contract(repo, gh)
            head = "f" * 40
            gh.pull_data = {
                "number": 2, "state": "open", "draft": False,
                "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
                "body": "Closes #1\n\n## Verification\nchecks passed\n\n## Untested\nnot applicable\n",
            }
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            path.write_text(json.dumps(complete_review_draft(json.loads(path.read_text()))), encoding="utf-8")
            publish_review(repo, 1, 2, gh)

            old_id = approved["comment_id"]
            old_comment = gh.issue_comment(1, old_id)
            replacement = gh.create_issue_comment(1, old_comment["body"])
            gh.issue_data["body"] = gh.issue_data["body"].replace(
                f"Comment ID: {old_id}\nSHA-256: {surface['contract_sha256']}",
                f"Comment ID: {replacement['id']}\nSHA-256: {surface['contract_sha256']}",
            )

            public = validate_public_review(1, 2, gh)
            self.assertTrue(public["stale"])
            self.assertTrue(public["contract_stale"])
            self.assertEqual(public["contract_comment_id"], old_id)
            self.assertEqual(public["current_contract_comment_id"], replacement["id"])
            self.assertEqual(public["current_contract_sha256"], public["contract_sha256"])
            with self.assertRaisesRegex(ReviewError, "comment ID"):
                publish_review(repo, 1, 2, gh)

            prepared = prepare_review(repo, 1, 2, gh)
            refreshed = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(prepared.get("reused", False))
            self.assertEqual(refreshed["contract_comment_id"], replacement["id"])
            self.assertTrue(all(section["result"] == "pending" for section in refreshed["contract_sections"]))
            backups = list(path.parent.glob(path.stem + ".*.stale.json"))
            self.assertEqual(len(backups), 1)

    def test_section_coverage_status_duplicates_and_order_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            _, _, _ = install_review_contract(repo, gh)
            gh.pull_data = {"number": 2, "base": {"repo": {"full_name": gh.repo}},
                            "head": {"sha": "f" * 40}, "body": "Closes #1"}
            prepare_review(repo, 1, 2, gh)
            original = json.loads(review_path(repo, 1, 2).read_text(encoding="utf-8"))

            def save_and_load(value):
                path = repo / "candidate.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                return load_review(path)

            pending = complete_review_draft(original)
            pending["contract_sections"][0]["result"] = "pending"
            with self.assertRaisesRegex(ReviewError, "result must be pass/fail/untested"):
                save_and_load(pending)

            empty = complete_review_draft(original)
            empty["contract_sections"][0]["evidence"] = " "
            with self.assertRaisesRegex(ReviewError, "concrete evidence"):
                save_and_load(empty)

            malformed_result = complete_review_draft(original)
            malformed_result["contract_sections"][0]["result"] = []
            with self.assertRaisesRegex(ReviewError, "result must be pass/fail/untested"):
                save_and_load(malformed_result)

            malformed_identity = complete_review_draft(original)
            malformed_identity["issue"] = True
            with self.assertRaisesRegex(ReviewError, "invalid ISSUE identity"):
                save_and_load(malformed_identity)

            missing = complete_review_draft(original)
            missing["contract_sections"].pop(1)
            with self.assertRaisesRegex(ReviewError, "missing or reordered"):
                save_and_load(missing)

            duplicate = complete_review_draft(original)
            duplicate["contract_sections"][1]["id"] = duplicate["contract_sections"][0]["id"]
            with self.assertRaisesRegex(ReviewError, "duplicate contract section"):
                save_and_load(duplicate)

            reordered = complete_review_draft(original)
            reordered["contract_sections"][1], reordered["contract_sections"][2] = (
                reordered["contract_sections"][2], reordered["contract_sections"][1]
            )
            with self.assertRaisesRegex(ReviewError, "missing or reordered"):
                save_and_load(reordered)

            wrong_hash = complete_review_draft(original)
            wrong_hash["contract_sections"][1]["section_sha256"] = "0" * 64
            save_and_load(wrong_hash)
            path = review_path(repo, 1, 2)
            path.write_text(json.dumps(wrong_hash), encoding="utf-8")
            args = type("Args", (), {"repo": None, "input": None, "issue": 1, "pr": 2})()
            with patch("agent_workflow.cli._repo_arg", return_value=repo), \
                 patch("agent_workflow.cli._gh", return_value=gh), \
                 self.assertRaisesRegex(ReviewError, "contract sections are stale"):
                _validate_self_review(args)

            wrong_title = complete_review_draft(original)
            wrong_title["contract_sections"][1]["title"] = "Invented title"
            path.write_text(json.dumps(wrong_title), encoding="utf-8")
            with patch("agent_workflow.cli._repo_arg", return_value=repo), \
                 patch("agent_workflow.cli._gh", return_value=gh), \
                 self.assertRaisesRegex(ReviewError, "contract sections are stale"):
                _validate_self_review(args)

    def test_legacy_v1_is_readable_and_reports_missing_contract_conformance(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            install_review_contract(repo, gh)
            surface = load_review_surface(1, gh.issue_data["body"], gh)
            head = "a" * 40
            review = {
                "schema_version": 1, "issue": 1, "pr": 2, "head": head,
                "checklist_sha256": surface["checklist_sha256"],
                "items": [
                    {**item, "result": "pass", "evidence": "validated prior checklist"}
                    for item in surface["items"]
                ],
            }
            payload = json.dumps(review, ensure_ascii=False, sort_keys=True, indent=2)
            sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            checklist = surface["checklist_sha256"]
            body = (
                f"<!-- agent-self-review:v1 issue=1 pr=2 head={head} checklist={checklist} -->\n\n"
                + payload
            )
            gh.pull_data = {
                "number": 2, "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
                "body": (
                    "Closes #1\n\n## Agent Self-Review\n\nComment ID: 105\n"
                    f"SHA-256: {sha}\nHEAD: {head}\nChecklist SHA-256: {checklist}\n"
                ),
            }
            gh.pull_comments[105] = {
                "id": 105, "issue_url": f"https://api.github.com/repos/{gh.repo}/issues/2",
                "body": body,
            }
            result = validate_public_review(1, 2, gh)
            self.assertFalse(result["stale"])
            self.assertEqual(result["schema_version"], 1)
            self.assertFalse(result["contract_conformance"])
            self.assertIsNone(result["contract_sha256"])

    def test_publication_detects_contract_supersession_before_pointer_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            payload_a, _, _ = install_review_contract(repo, gh)
            old_issue_body = gh.issue_data["body"]
            gh.pull_data = {
                "number": 2, "state": "open", "draft": False,
                "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": "f" * 40},
                "body": "Closes #1",
            }
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            path.write_text(json.dumps(complete_review_draft(json.loads(path.read_text()))), encoding="utf-8")
            payload_b = payload_a.replace(b"Review the complete contract.", b"Review superseded contract.")
            source = repo / "superseded-contract.md"
            source.write_bytes(payload_b)
            publish_contract(repo, 1, gh, source, supersede=True)
            new_issue_body = gh.issue_data["body"]
            real_issue = gh.issue
            reads = 0

            def racing_issue(number):
                nonlocal reads
                reads += 1
                value = real_issue(number)
                value["body"] = old_issue_body if reads == 1 else new_issue_body
                return value

            gh.issue = racing_issue
            with self.assertRaisesRegex(ReviewError, "changed while publishing"):
                publish_review(repo, 1, 2, gh)
            self.assertNotIn("## Agent Self-Review", gh.pull_data["body"])
            self.assertEqual(len(gh.pull_comments), 1)
            orphan = next(iter(gh.pull_comments.values()))
            self.assertIn("agent-self-review:v2", orphan["body"])

    def test_publication_head_change_after_comment_post_leaves_orphan_and_old_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            install_review_contract(repo, gh)
            old_head = "f" * 40
            gh.pull_data = {
                "number": 2, "state": "open", "draft": False,
                "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": old_head},
                "body": "Closes #1\n\n## Agent Self-Review\n\nComment ID: 77\nSHA-256: " + "a" * 64 + "\n",
            }
            original_body = gh.pull_data["body"]
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            path.write_text(json.dumps(complete_review_draft(json.loads(path.read_text()))), encoding="utf-8")
            real_create = gh.create_pull_comment

            def create_then_advance_head(number, body):
                comment = real_create(number, body)
                gh.pull_data["head"]["sha"] = "a" * 40
                return comment

            gh.create_pull_comment = create_then_advance_head
            with self.assertRaisesRegex(ReviewError, "HEAD changed while publishing"):
                publish_review(repo, 1, 2, gh)
            self.assertEqual(gh.pull_data["body"], original_body)
            self.assertEqual(len(gh.pull_comments), 1)
            self.assertIn("agent-self-review:v2", next(iter(gh.pull_comments.values()))["body"])

    def test_publication_contract_comment_id_change_after_post_leaves_orphan(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            _, approved, surface = install_review_contract(repo, gh)
            head = "f" * 40
            gh.pull_data = {
                "number": 2, "state": "open", "draft": False,
                "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
                "body": "Closes #1\n\n## Agent Self-Review\n\nComment ID: 77\nSHA-256: " + "a" * 64 + "\n",
            }
            original_body = gh.pull_data["body"]
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            path.write_text(json.dumps(complete_review_draft(json.loads(path.read_text()))), encoding="utf-8")
            real_create = gh.create_pull_comment

            def create_then_replace_contract_comment(number, body):
                review_comment = real_create(number, body)
                approved_comment = gh.issue_comment(1, approved["comment_id"])
                replacement = gh.create_issue_comment(1, approved_comment["body"])
                gh.issue_data["body"] = gh.issue_data["body"].replace(
                    f"Comment ID: {approved['comment_id']}\nSHA-256: {surface['contract_sha256']}",
                    f"Comment ID: {replacement['id']}\nSHA-256: {surface['contract_sha256']}",
                )
                return review_comment

            gh.create_pull_comment = create_then_replace_contract_comment
            with self.assertRaisesRegex(ReviewError, "comment/SHA.*changed while publishing"):
                publish_review(repo, 1, 2, gh)
            self.assertEqual(gh.pull_data["body"], original_body)
            self.assertEqual(len(gh.pull_comments), 1)
            self.assertIn("agent-self-review:v2", next(iter(gh.pull_comments.values()))["body"])

    def test_contract_evidence_secret_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            install_review_contract(repo, gh)
            gh.pull_data = {"number": 2, "base": {"repo": {"full_name": gh.repo}},
                            "head": {"sha": "f" * 40}, "body": "Closes #1"}
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            draft = complete_review_draft(json.loads(path.read_text()))
            draft["contract_sections"][0]["evidence"] = "credential ghp_abcdefghijklmnopqrstuvwxyz"
            path.write_text(json.dumps(draft), encoding="utf-8")
            with self.assertRaisesRegex(ReviewError, "credential material"):
                load_review(path)


    def test_public_review_size_limit_still_applies_without_contract_body_duplication(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            long_item = b"x" * 65100
            lines = [
                b"Contract preamble.", b"", b"## Reviewer Checklist",
                b"<!-- AGENT_REVIEWER_CHECKLIST_V1 -->", b"- [ ] " + long_item,
                b"<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->", b"",
            ]
            payload = b"\n".join(lines)
            install_review_contract(repo, gh, payload)
            head = "f" * 40
            gh.pull_data = {
                "number": 2, "state": "open", "draft": False,
                "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
                "body": "Closes #1",
            }
            prepare_review(repo, 1, 2, gh)
            path = review_path(repo, 1, 2)
            draft = complete_review_draft(json.loads(path.read_text()))
            path.write_text(json.dumps(draft), encoding="utf-8")
            with self.assertRaisesRegex(ReviewError, "comment exceeds 65536"):
                publish_review(repo, 1, 2, gh)
            self.assertEqual(gh.pull_comments, {})


class GitHubTransportTests(unittest.TestCase):
    def test_mutation_payload_uses_ascii_json_and_utf8_transport(self):
        gh = GitHub("owner/repo")
        fake = type("Result", (), {"returncode": 0, "stdout": "{\"ok\":true}", "stderr": ""})()
        with patch("agent_workflow.github.subprocess.run", return_value=fake) as run:
            self.assertEqual(gh.request("POST", "repos/owner/repo/issues/1", {"body": "契約\r\n"}), {"ok": True})
        kwargs = run.call_args.kwargs
        self.assertTrue(kwargs["input"].isascii())
        self.assertIn("\\u5951\\u7d04", kwargs["input"])
        self.assertEqual(kwargs["encoding"], "utf-8")

    def test_transport_error_does_not_echo_gh_stderr(self):
        gh = GitHub("owner/repo")
        fake = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "authorization: secret-value"})()
        with patch("agent_workflow.github.subprocess.run", return_value=fake):
            with self.assertRaises(GitHubError) as raised:
                gh.request("GET", "repos/owner/repo/issues/1")
        self.assertNotIn("secret-value", str(raised.exception))
        self.assertIn("exit status 1", str(raised.exception))

    def test_repository_metadata_and_milestone_mutations_use_github_boundary(self):
        gh = GitHub("owner/repo")
        with patch.object(gh, "request", side_effect=[{"default_branch": "main"},
                                                       {"number": 8, "title": "0.2.0", "state": "open"},
                                                       {"milestone": {"number": 8}}]) as request:
            self.assertEqual(gh.repository()["default_branch"], "main")
            self.assertEqual(gh.create_milestone("0.2.0")["number"], 8)
            self.assertEqual(gh.assign_issue_milestone(7, 8)["milestone"]["number"], 8)
        self.assertEqual(request.call_args_list[1].args[:2], ("POST", "repos/owner/repo/milestones"))
        self.assertEqual(request.call_args_list[1].args[2], {"title": "0.2.0"})
        self.assertEqual(request.call_args_list[2].args[:2], ("PATCH", "repos/owner/repo/issues/7"))
        self.assertEqual(request.call_args_list[2].args[2], {"milestone": 8})

    def test_milestones_paginate_with_state_all(self):
        gh = GitHub("owner/repo")
        first = [{"number": index, "title": f"m{index}", "state": "open"} for index in range(100)]
        with patch.object(gh, "request", side_effect=[first, [{"number": 100, "title": "m100", "state": "closed"}]]) as request:
            values = gh.milestones()
        self.assertEqual(len(values), 101)
        queries = [parse_qs(urlsplit(call.args[1]).query) for call in request.call_args_list]
        self.assertEqual([query["state"] for query in queries], [["all"], ["all"]])
        self.assertEqual([query["page"] for query in queries], [["1"], ["2"]])

    def test_open_pull_query_filters_exact_refs_and_retains_fork_candidates(self):
        gh = GitHub("owner/repo")
        pulls = [
            {"number": 1, "head": {"ref": "feature/1-work", "repo": {"full_name": "owner/repo"}},
             "base": {"ref": "main"}},
            {"number": 2, "head": {"ref": "feature/1-work", "repo": {"full_name": "fork/repo"}},
             "base": {"ref": "main"}},
            {"number": 3, "head": {"ref": "feature/2-other", "repo": {"full_name": "owner/repo"}},
             "base": {"ref": "main"}},
            {"number": 4, "head": {"ref": "feature/1-work", "repo": {"full_name": "owner/repo"}},
             "base": {"ref": "release/v2"}},
        ]
        with patch.object(gh, "_paginate", return_value=pulls) as paginate:
            result = gh.open_pull_requests("feature/1-work", "main")
        self.assertEqual([pull["number"] for pull in result], [1, 2])
        endpoint = paginate.call_args.args[0]
        self.assertIn("state=open", endpoint)
        self.assertIn("base=main", endpoint)

    def test_pull_create_update_and_issue_label_replacement_use_structured_payloads(self):
        gh = GitHub("owner/repo")
        created = {"number": 8, "state": "open", "draft": False}
        updated = {"number": 8, "title": "Review", "body": "payload"}
        labels = [{"name": "area:runtime"}, {"name": "phase:review"}]
        with patch.object(gh, "request", side_effect=[created, updated, labels]) as request:
            self.assertEqual(gh.create_pull_request("Review", "feature/1-work", "main", "payload"), created)
            self.assertEqual(gh.update_pull_request(8, "Review", "payload"), updated)
            self.assertEqual(gh.replace_issue_labels(1, ["area:runtime", "phase:review"]), labels)
        self.assertEqual(request.call_args_list[0].args[:2], ("POST", "repos/owner/repo/pulls"))
        self.assertEqual(request.call_args_list[0].args[2], {
            "title": "Review", "head": "feature/1-work", "base": "main", "body": "payload", "draft": False,
        })
        self.assertEqual(request.call_args_list[1].args[:2], ("PATCH", "repos/owner/repo/pulls/8"))
        self.assertEqual(request.call_args_list[1].args[2], {"title": "Review", "body": "payload"})
        self.assertEqual(request.call_args_list[2].args[:2], ("PUT", "repos/owner/repo/issues/1/labels"))
        self.assertEqual(request.call_args_list[2].args[2], {"labels": ["area:runtime", "phase:review"]})


class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / ".agent").mkdir()
        self.profile = profile_fixture()
        self.profile["components"] = self.profile["components"][:1]
        self.profile["branch"]["required_checks"] = [{"name": "CI", "app_id": 77}]
        self.write_profile()
        self.fake = FakeGitHub()
        self.gh = GitHub(self.fake.repo)
        self.head = "d" * 40
        self.fake.pull_data = {
            "number": 2, "state": "open", "draft": False, "merged": False,
            "base": {"ref": "main", "repo": {"full_name": self.gh.repo}}, "head": {"sha": self.head},
            "body": "Closes #1\n\n## Verification\ntests passed\n\n## Untested\nIDE not run\n",
        }
        self.paths = {
            "issue_comments": f"{self.gh.prefix}/issues/1/comments",
            "issue_events": f"{self.gh.prefix}/issues/1/events",
            "check_runs": f"{self.gh.prefix}/commits/{self.head}/check-runs",
            "statuses": f"{self.gh.prefix}/commits/{self.head}/statuses",
        }
        self.pages = {path: [[]] for path in self.paths.values()}
        self.pages[self.paths["check_runs"]] = [{"check_runs": []}]
        mocked = patch.object(self.gh, "request", side_effect=self.respond)
        self.request = mocked.start()
        self.addCleanup(mocked.stop)

    def write_profile(self):
        (self.repo / ".agent/project.json").write_text(json.dumps(self.profile), encoding="utf-8")

    def respond(self, method, endpoint, payload=None):
        parsed = urlsplit(endpoint)
        if endpoint == self.gh.prefix and method == "GET":
            return {"default_branch": "main"}
        if parsed.query:
            self.assertEqual(method, "GET")
            query = parse_qs(parsed.query)
            self.assertEqual(query["per_page"], ["100"])
            return copy.deepcopy(self.pages[parsed.path][int(query["page"][0]) - 1])
        if endpoint == f"{self.gh.prefix}/issues/1":
            if method == "GET":
                return self.fake.issue(1)
            if method == "PATCH":
                return self.fake.update_issue(1, payload["body"])
        if endpoint == f"{self.gh.prefix}/pulls/2" and method == "GET":
            return self.fake.pull(2)
        if endpoint.startswith(f"{self.gh.prefix}/issues/comments/") and method == "GET":
            return self.fake.issue_comment(1, int(endpoint.rsplit("/", 1)[1]))
        raise AssertionError(f"unexpected API operation: {method} {endpoint}")

    def run_handoff(self):
        published = {
            "stale": False, "schema_version": 2, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {
                "items": [{"id": "C001", "text": "works", "result": "pass"}],
                "contract_sections": [{"id": "S001", "title": "Scope", "result": "pass"}],
            },
        }
        with patch("agent_workflow.delivery.validate_public_review", return_value=published):
            return delivery_check(self.repo, 1, 2, self.gh)

    def test_pending_same_sha_contract_on_page_two_is_reused_without_post(self):
        raw = b"approved pending contract\r\n"
        digest = sha256(raw)
        comment = self.fake.create_issue_comment(
            1, f"<!-- agent-contract:v1 issue=1 sha256={digest} bytes={len(raw)} -->\n\n" + raw.decode())
        unrelated = [{"id": i, "issue_url": comment["issue_url"], "body": "unrelated"} for i in range(100)]
        self.pages[self.paths["issue_comments"]] = [unrelated, [comment]]
        source = self.repo / "contract.md"
        source.write_bytes(raw)
        first = publish_contract(self.repo, 1, self.gh, source)
        retry = publish_contract(self.repo, 1, self.gh, source)
        self.assertEqual(first["comment_id"], comment["id"])
        self.assertTrue(retry["idempotent"])
        self.assertEqual(len(self.fake.comments), 1)
        self.assertFalse(any(call.args[0] == "POST" for call in self.request.call_args_list))
        self.request.assert_any_call("GET", self.paths["issue_comments"] + "?page=2&per_page=100")

    def test_page_two_issue_event_reaches_agent_context(self):
        event = {"source": {"issue": {"number": 2, "pull_request": {}, "state": "open",
                                     "html_url": "https://github.com/owner/repo/pull/2"}}}
        self.pages[self.paths["issue_events"]] = [[{"event": "labeled"} for _ in range(100)], [event]]
        with patch("agent_workflow.context._git", return_value=self.head):
            context = build_context(self.repo, 1, self.gh)
        self.assertEqual([pr["number"] for pr in context["pull_requests"]], [2])
        self.request.assert_any_call("GET", self.paths["issue_events"] + "?page=2&per_page=100")

    def test_page_two_required_check_reaches_handoff(self):
        successful = {"name": "CI", "head_sha": self.head, "status": "completed",
                      "conclusion": "success", "app": {"id": 77}}
        self.pages[self.paths["check_runs"]] = [
            {"check_runs": [{"name": f"unrelated-{i}"} for i in range(100)]},
            {"check_runs": [successful]},
        ]
        result = self.run_handoff()
        self.assertTrue(result["passed"], result["errors"])
        self.request.assert_any_call("GET", self.paths["check_runs"] + "?page=2&per_page=100")

    def test_page_two_commit_status_reaches_unrestricted_handoff(self):
        self.profile["branch"]["required_checks"] = ["CI"]
        self.write_profile()
        status = {"context": "CI", "sha": self.head, "state": "success"}
        self.pages[self.paths["statuses"]] = [[{"context": f"unrelated-{i}"} for i in range(100)], [status]]
        result = self.run_handoff()
        self.assertTrue(result["passed"], result["errors"])
        self.request.assert_any_call("GET", self.paths["statuses"] + "?page=2&per_page=100")

    def test_all_collections_keep_order_and_fetch_after_full_last_page(self):
        for method, path in self.paths.items():
            with self.subTest(method=method):
                pages = [[{"id": i} for i in range(100)], [{"id": i} for i in range(100, 200)], []]
                self.pages[path] = [{"check_runs": page} for page in pages] if method == "check_runs" else pages
                argument = self.head if method in {"check_runs", "statuses"} else 1
                result = getattr(self.gh, method)(argument)
                self.assertEqual([item["id"] for item in result], list(range(200)))
                self.request.assert_any_call("GET", path + "?page=3&per_page=100")

    def test_malformed_first_or_later_page_fails_closed(self):
        invalid = {
            "issue_comments": [None, {}, ["not an object"]],
            "issue_events": [None, {}, ["not an object"]],
            "check_runs": [None, [], {}, {"check_runs": None}, {"check_runs": ["not an object"]}],
            "statuses": [None, {}, ["not an object"]],
        }
        for method, responses in invalid.items():
            full = [{"id": i} for i in range(100)]
            first = {"check_runs": full} if method == "check_runs" else full
            for response in responses:
                for later in (False, True):
                    with self.subTest(method=method, response=response, later=later):
                        argument = self.head if method in {"check_runs", "statuses"} else 1
                        with patch.object(self.gh, "request", side_effect=[first, response] if later else [response]):
                            with self.assertRaises(GitHubError):
                                getattr(self.gh, method)(argument)

    def test_later_page_api_failure_does_not_return_partial_success(self):
        with patch.object(self.gh, "request", side_effect=[[{} for _ in range(100)], GitHubError("API failed")]):
            with self.assertRaises(GitHubError):
                self.gh.issue_events(1)


class ProcessTests(unittest.TestCase):
    def test_python_alias_fallback_preserves_command_text(self):
        result = type("Result", (), {"returncode": 0})()
        with patch("agent_workflow.process.shutil.which", side_effect=lambda name: None if name == "python" else "/usr/bin/python3"), \
             patch("agent_workflow.process.subprocess.run", return_value=result) as run:
            completed = run_command("  python -m unittest --quiet", Path("."))
        self.assertEqual(completed.command, "  python3 -m unittest --quiet")
        self.assertTrue(run.call_args.args[0].startswith("  python3"))
        self.assertTrue(run.call_args.kwargs["shell"])

    def test_hook_failure_identifies_executable_without_echoing_arguments_or_output(self):
        result = type("Result", (), {"returncode": 37})()
        with patch("agent_workflow.process.subprocess.run", return_value=result) as run:
            with self.assertRaises(ProcessError) as raised:
                run_command("python -m check --token=do-not-print", Path("."))
        self.assertEqual(raised.exception.returncode, 37)
        self.assertIn("python", str(raised.exception))
        self.assertNotIn("do-not-print", str(raised.exception))
        self.assertIs(run.call_args.kwargs["stdout"], __import__("subprocess").DEVNULL)

    def test_hook_failure_skips_environment_assignment_values_in_label(self):
        result = type("Result", (), {"returncode": 1})()
        with patch("agent_workflow.process.subprocess.run", return_value=result):
            with self.assertRaises(ProcessError) as raised:
                run_command("API_TOKEN=do-not-print python -m check", Path("."))
        self.assertIn("python", str(raised.exception))
        self.assertNotIn("do-not-print", str(raised.exception))

    def test_diagnostic_failure_is_redacted_bounded_and_uses_deleted_temp_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            secret = "hook-secret-value"
            script = ("import sys; print('x'*20000); print(sys.argv[-1]); "
                      "print('Authorization: Bearer abcdefghijklmnopqrstuvwxyz'); "
                      "print('stderr detail', file=sys.stderr); sys.exit(37)")
            command = python_shell_command(script, f"--token={secret}")
            with patch("agent_workflow.process.tempfile.tempdir", temporary):
                with self.assertRaises(ProcessError) as raised:
                    run_command(command, Path(temporary), diagnostic=True)
            error = raised.exception
            self.assertEqual(error.returncode, 37)
            self.assertIn(Path(sys.executable).name, str(error))
            self.assertIn("[REDACTED]", error.diagnostic)
            self.assertNotIn(secret, error.diagnostic)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", error.diagnostic)
            self.assertLessEqual(len(error.diagnostic.encode("utf-8")), 16 * 1024)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_default_hook_failure_stays_silent_and_diagnostic_cli_flag_parses(self):
        script = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(9)"
        command = python_shell_command(script)
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            with self.assertRaises(ProcessError) as raised:
                run_command(command, Path("."))
        self.assertEqual(raised.exception.returncode, 9)
        self.assertEqual(raised.exception.diagnostic, "")
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "")
        args = build_parser().parse_args(["run-hook", "verify_final", "--diagnostic"])
        self.assertTrue(args.diagnostic)
        with tempfile.TemporaryDirectory() as temporary, \
             patch("agent_workflow.process.tempfile.tempdir", temporary), \
             redirect_stdout(output), redirect_stderr(errors):
            run_command(command.replace("sys.exit(9)", "sys.exit(0)"), Path(temporary), diagnostic=True)
            self.assertEqual(list(Path(temporary).iterdir()), [])
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "")

    def test_run_hook_diagnostic_cli_emits_only_redacted_failure_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".git").mkdir()
            (repo / ".agent").mkdir()
            secret = "cli-hook-secret"
            script = "import sys; print(sys.argv[-1]); sys.exit(23)"
            command = python_shell_command(script, f"--token={secret}")
            profile = profile_fixture()
            profile["hooks"] = {"verify_final": [command]}
            (repo / ".agent/project.json").write_text(json.dumps(profile), encoding="utf-8")
            output = io.StringIO()
            with patch("agent_workflow.process.tempfile.tempdir", temporary), redirect_stderr(output):
                status = cli_main(["run-hook", "verify_final", "--diagnostic", "--repo", str(repo)])
            self.assertEqual(status, 23)
            self.assertIn("hook command", output.getvalue())
            self.assertIn("[REDACTED]", output.getvalue())
            self.assertNotIn(secret, output.getvalue())
            self.assertLessEqual(len(output.getvalue().encode("utf-8")), 16 * 1024 + 256)
            self.assertEqual({p.name for p in repo.iterdir()}, {".git", ".agent"})


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        (self.repo / ".agent").mkdir()
        data = {"schema_version": 2, "initialized": True, "project_name": "x",
                "components": [{"id": "root", "roots": ["."], "stacks": [],
                                "application_types": ["cli"], "targets": [], "hooks": {}}],
                "branch": {"prefix": "feature", "max_slug_length": 48,
                           "required_checks": [{"name": "CI", "app_id": 77}]},
                "milestones": {"enabled": False}, "hooks": {}}
        (self.repo / ".agent/project.json").write_text(json.dumps(data), encoding="utf-8")
        self.gh = FakeGitHub("## Affected components\n- root\n")
        self.head = "d" * 40
        self.pr_body = """Closes #1

## Verification
python -m unittest: passed

## Untested
macOS IDE smoke test not run
"""
        self.gh.pull_data = {"number": 2, "state": "open", "draft": False, "merged": False,
                            "base": {"ref": "main", "repo": {"full_name": self.gh.repo}},
                            "head": {"sha": self.head, "repo": {"full_name": self.gh.repo}},
                            "body": self.pr_body}
        self.gh.runs = [{"name": "CI", "head_sha": self.head, "status": "completed",
                         "conclusion": "success", "app": {"id": 77}}]

    def tearDown(self):
        self.temp.cleanup()

    def run_gate(self, **changes):
        published = changes.pop("published_review", {
            "stale": False, "schema_version": 2, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_comment_id": 123,
            "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {
                "items": [{"id": "C001", "text": "works", "result": "pass"}],
                "contract_sections": [
                    {"id": "S001", "title": "Architecture", "result": "pass"},
                ],
            },
        })
        if "issue_labels" in changes:
            self.gh.issue_data["labels"] = changes.pop("issue_labels")
        if "issue_state" in changes:
            self.gh.issue_data["state"] = changes.pop("issue_state")
        if "profile_checks" in changes:
            path = self.repo / ".agent/project.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["branch"]["required_checks"] = changes.pop("profile_checks")
            path.write_text(json.dumps(data), encoding="utf-8")
        for key, value in changes.items():
            if key == "body":
                self.gh.pull_data["body"] = value
            else:
                self.gh.pull_data[key] = value
        with patch("agent_workflow.delivery.validate_public_review", return_value=published):
            return delivery_check(self.repo, 1, 2, self.gh)

    def run_ensure(self, body=None, title=None, base_ref=None, head_sha=None):
        head_sha = head_sha or self.head
        pushed = {"head_sha": head_sha, "head_branch": "feature/1-review", "base_branch": base_ref or "main",
                  "base_sha": "a" * 40, "ahead_by": 1, "pushed": True,
                  "remote_head": head_sha, "remote_head_verified": True}
        self.gh.push_data = copy.deepcopy(pushed)
        with patch("agent_workflow.delivery.push_review_branch", return_value=pushed) as push:
            result = ensure_review_pr(self.repo, 1, body or self.pr_body, self.gh, title, base_ref)
        return result, push

    def _candidate_pr(self, **changes):
        pull = {"number": 8, "html_url": f"https://github.com/{self.gh.repo}/pull/8",
                "title": "Existing title", "state": "open", "draft": False, "merged": False,
                "base": {"ref": "main", "repo": {"full_name": self.gh.repo}},
                "head": {"ref": "feature/1-review", "sha": self.head,
                         "repo": {"full_name": self.gh.repo}}, "body": "## Verification\nold\n\n## Untested\nold"}
        pull.update(changes)
        self.gh.pull_data = copy.deepcopy(pull)
        self.gh.pull_candidates = [copy.deepcopy(pull)]
        return pull

    def test_ensure_review_pr_creates_pushes_and_transitions_phase(self):
        self.gh.issue_data["labels"] = [{"name": "area:runtime"}, {"name": "phase:ready"},
                                         {"name": "phase:implementation"}]
        result, push = self.run_ensure()
        self.assertTrue(result["success"], result)
        self.assertTrue(result["created"])
        self.assertFalse(result["reused"])
        self.assertEqual(result["head_sha"], self.head)
        self.assertEqual(result["head_branch"], "feature/1-review")
        self.assertEqual(result["base_branch"], "main")
        self.assertEqual(self.gh.pull_data["title"], "Issue title")
        self.assertIn("Closes #1", self.gh.pull_data["body"])
        self.assertIn("## Verification", self.gh.pull_data["body"])
        self.assertIn("## Untested", self.gh.pull_data["body"])
        self.assertEqual(self.gh.issue_data["labels"], [{"name": "area:runtime"}, {"name": "phase:review"}])
        self.assertEqual(len(self.gh.created_prs), 1)
        self.assertEqual(len(self.gh.label_replacements), 1)
        push.assert_called_once()

    def test_ensure_review_pr_retry_reuses_pr_and_preserves_labels(self):
        self.gh.issue_data["labels"] = [{"name": "area:runtime"}, {"name": "phase:ready"},
                                         {"name": "phase:implementation"}]
        first, _ = self.run_ensure()
        second, push = self.run_ensure()
        self.assertTrue(first["success"])
        self.assertTrue(second["success"], second)
        self.assertEqual(first["pr"], second["pr"])
        self.assertFalse(second["created"])
        self.assertTrue(second["reused"])
        self.assertEqual(len(self.gh.created_prs), 1)
        self.assertEqual(self.gh.updated_prs, [])
        self.assertEqual(self.gh.issue_data["labels"], [{"name": "area:runtime"}, {"name": "phase:review"}])
        self.assertEqual(len(self.gh.label_replacements), 1)
        self.assertTrue(push.called)

    def test_ensure_review_pr_validates_body_before_push_or_github(self):
        cases = [
            ("## Verification\npassed\n\n## Untested\nnone", "Closes #1"),
            ("Closes #1\n\n## Verification\n\n## Untested\nnone", "Verification"),
            ("Closes #1\n\n## Verification\npassed\n\n## Untested\n", "Untested"),
            ("Closes #2\n\n## Verification\npassed\n\n## Untested\nnone", "Closes #1"),
        ]
        for body, expected in cases:
            with self.subTest(expected=expected):
                self.gh.lifecycle_calls.clear()
                with patch("agent_workflow.delivery.push_review_branch") as push:
                    with self.assertRaisesRegex(DeliveryError, expected):
                        ensure_review_pr(self.repo, 1, body, self.gh)
                push.assert_not_called()
                self.assertEqual(self.gh.lifecycle_calls, [])

    def test_requested_body_closing_conflicts_fail_before_push_or_github(self):
        for clause in (
            "Fixes #2",
            "Fixes other/repo#99",
            "Resolves other/repo#1",
            "Closes #1, #2",
            "Closes #1 and other/repo#2",
        ):
            with self.subTest(clause=clause):
                self.gh.lifecycle_calls.clear()
                body = self.pr_body + "\n" + clause + "\n"
                with patch("agent_workflow.delivery.push_review_branch") as push:
                    with self.assertRaisesRegex(DeliveryError, "closing reference"):
                        ensure_review_pr(self.repo, 1, body, self.gh)
                push.assert_not_called()
                self.assertEqual(self.gh.lifecycle_calls, [])
                self.assertEqual(self.gh.created_prs, [])
                self.assertEqual(self.gh.updated_prs, [])
                self.assertEqual(self.gh.label_replacements, [])

    def test_existing_cross_repository_closing_conflicts_are_never_rewritten(self):
        for closing_body in ("Fixes other/repo#1", "Closes #1, resolves other/repo#1"):
            with self.subTest(closing_body=closing_body):
                self.gh.created_prs = []
                self.gh.updated_prs = []
                self.gh.label_replacements = []
                self._candidate_pr(body=closing_body)
                with patch("agent_workflow.delivery.push_review_branch", return_value={
                    "head_sha": self.head, "head_branch": "feature/1-review", "base_branch": "main",
                    "base_sha": "a" * 40, "ahead_by": 1, "pushed": True,
                    "remote_head": self.head, "remote_head_verified": True,
                }):
                    with self.assertRaisesRegex(DeliveryError, "closes a different Issue or repository"):
                        ensure_review_pr(self.repo, 1, self.pr_body, self.gh)
                self.assertEqual(self.gh.created_prs, [])
                self.assertEqual(self.gh.updated_prs, [])
                self.assertEqual(self.gh.label_replacements, [])

    def test_repository_aware_closing_reference_parser(self):
        from agent_workflow.delivery import _closing_references

        cases = [
            ("CLOSES: #1", {("owner/repo", 1)}),
            ("fixed Other/Repo#2", {("other/repo", 2)}),
            ("Resolved #3", {("owner/repo", 3)}),
            ("Closes #1, #2", {("owner/repo", 1), ("owner/repo", 2)}),
            ("See #99", set()),
            ("close #4", {("owner/repo", 4)}),
            ("closed #5", {("owner/repo", 5)}),
            ("fix #6", {("owner/repo", 6)}),
            ("fixes #7", {("owner/repo", 7)}),
            ("resolve #8", {("owner/repo", 8)}),
            ("resolves #9", {("owner/repo", 9)}),
            ("Closes #1; See #2", {("owner/repo", 1)}),
            ("Closes #1 because discussion continues in #2", {("owner/repo", 1)}),
            ("Closes #1. Follow-up is #2", {("owner/repo", 1)}),
            ("Closes #1 — see #2", {("owner/repo", 1)}),
            ("Closes #1 and other/repo#2", {("owner/repo", 1), ("other/repo", 2)}),
            ("Closes #1 and #2", {("owner/repo", 1), ("owner/repo", 2)}),
            ("Closes #1, and #2", {("owner/repo", 1), ("owner/repo", 2)}),
            ("Closes #1; fixes #2", {("owner/repo", 1), ("owner/repo", 2)}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(_closing_references(body, "owner/repo"), expected)

    def test_requested_body_ordinary_followup_reference_does_not_block(self):
        body = (
            "Closes #1\n\nCloses #1; See #2\n\n"
            "## Verification\npassed\n\n## Untested\nnone\n"
        )
        result, push = self.run_ensure(body=body)
        self.assertTrue(result["success"], result)
        push.assert_called_once()

    def test_ensure_review_pr_push_failure_has_no_pr_or_label_mutation(self):
        self.gh.issue_data["labels"] = [{"name": "phase:implementation"}]
        with patch("agent_workflow.delivery.push_review_branch",
                   side_effect=GitLifecycleError("Git push failed (exit status 1)")):
            with self.assertRaisesRegex(DeliveryError, "Git push failed"):
                ensure_review_pr(self.repo, 1, self.pr_body, self.gh)
        self.assertEqual(self.gh.created_prs, [])
        self.assertEqual(self.gh.label_replacements, [])

    def test_ensure_review_pr_fails_closed_for_conflict_draft_and_fork(self):
        for changes, expected in [
            ({"body": "Closes #2"}, "closes a different Issue"),
            ({"draft": True}, "open and non-draft"),
            ({"head": {"ref": "feature/1-review", "sha": self.head,
                       "repo": {"full_name": "fork/repo"}}}, "fork or another repository"),
        ]:
            with self.subTest(expected=expected):
                self.gh.created_prs = []
                self.gh.updated_prs = []
                self.gh.label_replacements = []
                self._candidate_pr(**changes)
                with patch("agent_workflow.delivery.push_review_branch", return_value={
                    "head_sha": self.head, "head_branch": "feature/1-review", "base_branch": "main",
                    "base_sha": "a" * 40, "ahead_by": 1, "pushed": True,
                    "remote_head": self.head, "remote_head_verified": True,
                }):
                    with self.assertRaisesRegex(DeliveryError, expected):
                        ensure_review_pr(self.repo, 1, self.pr_body, self.gh)
                self.assertEqual(self.gh.created_prs, [])
                self.assertEqual(self.gh.updated_prs, [])
                self.assertEqual(self.gh.label_replacements, [])

    def test_ensure_review_pr_fails_closed_on_duplicate_matches(self):
        candidate = self._candidate_pr()
        self.gh.pull_candidates.append(copy.deepcopy(candidate))
        with patch("agent_workflow.delivery.push_review_branch", return_value={
            "head_sha": self.head, "head_branch": "feature/1-review", "base_branch": "main",
            "base_sha": "a" * 40, "ahead_by": 1, "pushed": True,
            "remote_head": self.head, "remote_head_verified": True,
        }):
            with self.assertRaisesRegex(DeliveryError, "multiple open PRs"):
                ensure_review_pr(self.repo, 1, self.pr_body, self.gh)
        self.assertEqual(self.gh.created_prs, [])
        self.assertEqual(self.gh.updated_prs, [])
        self.assertEqual(self.gh.label_replacements, [])

    def test_ensure_review_pr_updates_compatible_existing_pr_only_when_needed(self):
        existing = self._candidate_pr()
        self.gh.issue_data["labels"] = [{"name": "phase:implementation"}, {"name": "area:runtime"}]
        result, _ = self.run_ensure()
        self.assertTrue(result["success"], result)
        self.assertTrue(result["reused"])
        self.assertFalse(result["created"])
        self.assertEqual(result["pr"], existing["number"])
        self.assertEqual(len(self.gh.updated_prs), 1)
        self.assertEqual(self.gh.updated_prs[0], (8, "Issue title", self.pr_body))
        self.assertEqual(self.gh.created_prs, [])

    def test_existing_pr_ordinary_followup_reference_remains_compatible(self):
        body = (
            "Closes #1\n\nCloses #1; See #2\n\n"
            "## Verification\npassed\n\n## Untested\nnone\n"
        )
        self._candidate_pr(title="Issue title", body=body)
        result, _ = self.run_ensure(body=body)
        self.assertTrue(result["success"], result)
        self.assertTrue(result["reused"])
        self.assertEqual(result["pr"], 8)
        self.assertEqual(self.gh.updated_prs, [])
        self.assertEqual(self.gh.created_prs, [])

    def test_phase_failure_returns_pr_identity_and_retry_reuses_it(self):
        self.gh.issue_data["labels"] = [{"name": "area:runtime"}, {"name": "phase:implementation"}]
        self.gh.fail_label_replacement = True
        failed, _ = self.run_ensure()
        self.assertFalse(failed["success"])
        self.assertEqual(failed["pr_url"], f"https://github.com/{self.gh.repo}/pull/{failed['pr']}")
        self.assertFalse(failed["phase_transition"]["verified"])
        self.assertEqual(len(self.gh.created_prs), 1)
        self.gh.fail_label_replacement = False
        retry, _ = self.run_ensure()
        self.assertTrue(retry["success"], retry)
        self.assertTrue(retry["reused"])
        self.assertEqual(retry["pr"], failed["pr"])
        self.assertEqual(len(self.gh.created_prs), 1)

    def test_new_head_reuses_pr_and_pending_checks_still_block_delivery(self):
        first, _ = self.run_ensure()
        new_head = "f" * 40
        for candidate in self.gh.pull_candidates:
            candidate["head"]["sha"] = new_head
        self.gh.pull_data["head"]["sha"] = new_head
        second, _ = self.run_ensure(head_sha=new_head)
        self.assertTrue(second["success"], second)
        self.assertTrue(second["reused"])
        self.assertEqual(first["pr"], second["pr"])
        self.gh.runs = []
        self.head = new_head
        result = self.run_gate(published_review={
            "stale": True, "schema_version": 2, "head": "d" * 40, "head_stale": True,
            "contract_stale": False, "checklist_stale": False,
            "review": {"items": [], "contract_sections": []},
        })
        self.assertFalse(result["passed"])
        self.assertTrue(any("stale for the current PR HEAD" in error for error in result["errors"]))
        self.assertTrue(any("Required Check" in error for error in result["errors"]))

    def test_pending_required_checks_do_not_prevent_pr_establishment(self):
        self.gh.runs = []
        result, _ = self.run_ensure()
        self.assertTrue(result["success"], result)
        self.assertEqual(len(self.gh.created_prs), 1)
        gate = self.run_gate()
        self.assertFalse(gate["passed"])
        self.assertTrue(any("Required Check" in error for error in gate["errors"]))

    def test_handoff_passes_only_with_current_review_and_green_app_check(self):
        result = self.run_gate()
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["contract_comment_id"], 123)

    def test_current_review_fail_blocks_green_handoff_with_bounded_item_details(self):
        item = {"id": "C001", "text": "the runtime must reject failed review"}
        review = {
            "stale": False, "schema_version": 2, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {
                "items": [dict(item, result="fail")],
                "contract_sections": [{"id": "S001", "title": "Architecture", "result": "pass"}],
            },
        }
        result = self.run_gate(published_review=review)
        self.assertFalse(result["passed"])
        self.assertEqual(result["review_failures"], [{"id": "C001", "text": "the runtime must reject failed review"}])
        self.assertTrue(any("C001" in error and "reject failed review" in error for error in result["errors"]))

    def test_pass_and_untested_review_items_remain_nonblocking(self):
        items = [{"id": "C001", "text": "passed item"}, {"id": "C002", "text": "untested item"}]
        review = {
            "stale": False, "schema_version": 2, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {
                "items": [dict(items[0], result="pass"), dict(items[1], result="untested")],
                "contract_sections": [{"id": "S001", "title": "Architecture", "result": "pass"}],
            },
        }
        result = self.run_gate(published_review=review)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["review_failures"], [])
        self.assertEqual(result["review_failure_count"], 0)

    def test_contract_section_fail_blocks_delivery_and_reports_bounded_identity(self):
        review = {
            "stale": False, "schema_version": 2, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {
                "items": [{"id": "C001", "text": "checklist item", "result": "pass"}],
                "contract_sections": [
                    {"id": "S001", "title": "Architecture decisions", "result": "fail"},
                ],
            },
        }
        result = self.run_gate(published_review=review)
        self.assertFalse(result["passed"])
        self.assertEqual(result["contract_sha256"], "e" * 64)
        self.assertEqual(result["review_schema_version"], 2)
        self.assertEqual(result["contract_review_failure_count"], 1)
        self.assertEqual(result["contract_review_failures"], [
            {"id": "S001", "title": "Architecture decisions"},
        ])
        self.assertTrue(any("failed contract section" in error for error in result["errors"]))

    def test_contract_untested_blocks_delivery_and_reports_bounded_identity(self):
        review = {
            "stale": False, "schema_version": 2, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {
                "items": [{"id": "C001", "text": "checklist item", "result": "pass"}],
                "contract_sections": [
                    {"id": "S001", "title": "External verification", "result": "untested"},
                ],
            },
        }
        result = self.run_gate(published_review=review)
        self.assertFalse(result["passed"])
        self.assertEqual(result["contract_review_untested_count"], 1)
        self.assertEqual(result["contract_review_untested"], [
            {"id": "S001", "title": "External verification"},
        ])
        self.assertEqual(result["contract_review_failure_count"], 0)
        self.assertTrue(any("conformance is incomplete" in error for error in result["errors"]))

    def test_legacy_v1_review_is_rejected_with_regeneration_guidance(self):
        review = {
            "stale": False, "schema_version": 1, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {"items": [{"id": "C001", "text": "checklist item", "result": "pass"}]},
        }
        result = self.run_gate(published_review=review)
        self.assertFalse(result["passed"])
        self.assertEqual(result["review_schema_version"], 1)
        self.assertTrue(any(
            "schema v1 has no full Implementation Contract conformance" in error
            and "regenerate the self-review" in error
            for error in result["errors"]
        ))

    def test_contract_failure_details_are_bounded_to_ten_entries(self):
        sections = [
            {"id": f"S{n:03d}", "title": "T" * 200, "result": "fail"}
            for n in range(1, 13)
        ]
        review = {
            "stale": False, "schema_version": 2, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {
                "items": [{"id": "C001", "text": "checklist item", "result": "pass"}],
                "contract_sections": sections,
            },
        }
        result = self.run_gate(published_review=review)
        self.assertFalse(result["passed"])
        self.assertEqual(result["contract_review_failure_count"], 12)
        self.assertEqual(len(result["contract_review_failures"]), 10)
        self.assertTrue(all(len(item["title"]) <= 120 for item in result["contract_review_failures"]))

    def test_contract_untested_details_are_bounded_to_ten_entries(self):
        sections = [
            {"id": f"S{n:03d}", "title": "U" * 200, "result": "untested"}
            for n in range(1, 13)
        ]
        review = {
            "stale": False, "schema_version": 2, "head": self.head,
            "checklist_sha256": "c" * 64, "current_contract_sha256": "e" * 64,
            "head_stale": False, "contract_stale": False, "checklist_stale": False,
            "review": {
                "items": [{"id": "C001", "text": "checklist item", "result": "pass"}],
                "contract_sections": sections,
            },
        }
        result = self.run_gate(published_review=review)
        self.assertFalse(result["passed"])
        self.assertEqual(result["contract_review_untested_count"], 12)
        self.assertEqual(len(result["contract_review_untested"]), 10)
        self.assertTrue(all(len(item["title"]) <= 120 for item in result["contract_review_untested"]))

    def test_delivery_reports_stacked_state_without_blocking_it(self):
        result = self.run_gate(base={"ref": "feature/8-base", "repo": {"full_name": self.gh.repo}})
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["base_ref"], "feature/8-base")
        self.assertEqual(result["default_base_ref"], "main")
        self.assertTrue(result["stacked"])

    def test_each_required_handoff_precondition_is_checked(self):
        cases = [
            ({"draft": True}, "non-draft"),
            ({"issue_state": "closed"}, "open Issue"),
            ({"body": "## Verification\npassed\n\n## Untested\nnone"}, "Closes #1"),
            ({"issue_labels": []}, "phase:review"),
            ({"head": {"sha": "e" * 40, "repo": {"full_name": "owner/repo"}},
              "published_review": {"stale": True, "schema_version": 2, "head": "d" * 40,
                                   "head_stale": True, "contract_stale": False,
                                   "checklist_stale": False, "review": {"items": []}}}, "stale"),
            ({"published_review": {"stale": True, "schema_version": 2, "head": "d" * 40,
                                    "head_stale": False, "contract_stale": False,
                                    "checklist_stale": True, "review": {"items": []}}}, "checklist is stale"),
            ({"body": "Closes #1\n\n## Verification\n\n## Untested\nnone"}, "Verification"),
            ({"body": "Closes #1\n\n## Verification\npassed\n\n## Untested\n"}, "Untested"),
            ({"profile_checks": []}, "no Required Checks"),
        ]
        for changes, expected in cases:
            with self.subTest(expected=expected):
                # Reset the state between independent failure scenarios.
                self.tearDown()
                self.setUp()
                try:
                    result = self.run_gate(**changes)
                    self.assertFalse(result["passed"])
                    self.assertTrue(any(expected in error for error in result["errors"]), result["errors"])
                finally:
                    self.tearDown()

    def test_pending_required_check_fails(self):
        self.gh.runs[0]["status"] = "in_progress"
        result = self.run_gate()
        self.assertFalse(result["passed"])
        self.assertTrue(any("Required Check" in error for error in result["errors"]))

    def test_app_scoped_required_check_requires_the_exact_app(self):
        self.gh.runs[0]["app"]["id"] = 99
        result = self.run_gate()
        self.assertFalse(result["passed"])
        self.assertTrue(any("Required Check" in error for error in result["errors"]))

    def test_finalize_only_removes_review_phase_and_is_idempotent(self):
        self.gh.pull_data["merged"] = True
        self.gh.issue_data["state"] = "closed"
        first = finalize_merged_issue(1, 2, self.gh)
        second = finalize_merged_issue(1, 2, self.gh)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(self.gh.removed, ["phase:review"])

    def test_unexpected_phase_label_blocks_without_mutation(self):
        self.gh.pull_data["merged"] = True
        self.gh.issue_data["state"] = "closed"
        self.gh.issue_data["labels"].append({"name": "phase:ready"})
        with self.assertRaises(DeliveryError):
            finalize_merged_issue(1, 2, self.gh)
        self.assertEqual(self.gh.removed, [])


class DistributionTests(unittest.TestCase):
    def test_generated_packages_carry_handoff_authority_and_runtime_command(self):
        files = build_dist.expected_files()
        for host in build_dist.HOSTS:
            with self.subTest(host=host):
                implementation = files[f"dist/{host}/skills/implementation/SKILL.md"].decode("utf-8")
                requirements = files[f"dist/{host}/skills/requirements/SKILL.md"].decode("utf-8")
                delivery = files[f"dist/{host}/skills/delivery/SKILL.md"].decode("utf-8")
                self_review = files[f"dist/{host}/skills/self-review/SKILL.md"].decode("utf-8")
                all_skills = "\n".join(
                    files[f"dist/{host}/skills/{name}/SKILL.md"].decode("utf-8")
                    for name in build_dist.EXPECTED_SKILLS
                )
                runtime_delivery = files[f"dist/{host}/runtime/agent_workflow/delivery.py"].decode("utf-8")
                runtime_cli = files[f"dist/{host}/runtime/agent_workflow/cli.py"].decode("utf-8")
                self.assertIn("continue without another conversational prompt", implementation)
                self.assertIn("Do not report implementation complete until an open, non-draft review PR exists", implementation)
                self.assertIn("Do not request a later PR-specific conversational approval", requirements)
                self.assertIn("merge/release", requirements)
                self.assertIn("destructive Git operations", requirements)
                self.assertIn("material scope/architecture changes", requirements)
                for line in all_skills.splitlines():
                    requests_later_approval = re.search(
                        r"(?i)\b(?:ask|request|wait for)\b.*\b(?:separate|additional|another|later)\b"
                        r".*\b(?:PR|pull request)\b.*\b(?:approval|confirmation)\b", line)
                    if requests_later_approval:
                        self.assertRegex(line, r"(?i)\b(?:do not|must not|never)\b")
                self.assertIn("ensure-review-pr <issue> --body-file <path>", delivery)
                self.assertIn("without another user prompt", self_review)
                self.assertIn("def ensure_review_pr(", runtime_delivery)
                self.assertIn('commands.add_parser("ensure-review-pr")', runtime_cli)
        for path in ("dist/openai/plugin.json", "dist/claude/.claude-plugin/plugin.json"):
            self.assertEqual(json.loads(files[path])['version'], __version__)
        self.assertNotIn("version", json.loads(files["dist/antigravity/plugin.json"]))

    def test_openai_marketplace_uses_repository_contained_host_package(self):
        files = build_dist.expected_files()
        market = json.loads(files[".agents/plugins/marketplace.json"])
        manifest = json.loads(files["dist/openai/plugin.json"])
        self.assertEqual(len(market["plugins"]), 1)
        entry = market["plugins"][0]
        self.assertEqual(market["name"], "ai-agent-workflow")
        self.assertEqual(entry["name"], manifest["name"])
        self.assertEqual(entry["name"], "ai-agent-workflow")
        self.assertEqual(entry["source"], {"source": "local", "path": "./dist/openai"})
        self.assertEqual(entry["category"], "Productivity")
        self.assertEqual(entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        target = (ROOT / entry["source"]["path"][2:]).resolve()
        self.assertIn(ROOT.resolve(), target.parents)
        self.assertTrue(target.is_dir())
        self.assertTrue((target / "plugin.json").is_file())
        self.assertEqual(validate_dist.validate(), [])

    def test_openai_marketplace_rejects_invalid_or_missing_sources(self):
        market_path = validate_dist.ROOT / ".agents/plugins/marketplace.json"
        base = json.loads(build_dist.expected_files()[".agents/plugins/marketplace.json"])
        original_load = validate_dist._load
        invalid_paths = ("../outside", "/tmp/openai", "C:\\outside", "./dist/claude",
                         "./dist/openai-missing")
        for source_path in invalid_paths:
            def load(path, errors):
                if path == market_path:
                    market = copy.deepcopy(base)
                    market["plugins"][0]["source"]["path"] = source_path
                    return market
                return original_load(path, errors)
            with self.subTest(source_path=source_path), patch.object(validate_dist, "_load", side_effect=load):
                errors = validate_dist.validate()
                self.assertTrue(any(".agents/plugins/marketplace.json: marketplace-source error:" in error
                                    for error in errors), errors)

    def test_claude_marketplace_has_one_matching_repository_package(self):
        files = build_dist.expected_files()
        market = json.loads(files[".claude-plugin/marketplace.json"])
        manifest = json.loads(files["dist/claude/.claude-plugin/plugin.json"])
        self.assertEqual(market["name"], "ai-agent-workflow")
        self.assertEqual(len(market["plugins"]), 1)
        entry = market["plugins"][0]
        self.assertEqual(entry["name"], manifest["name"])
        self.assertEqual(entry["name"], "ai-agent-workflow")
        self.assertEqual(entry["source"], "./dist/claude")
        target = (ROOT / entry["source"][2:]).resolve()
        self.assertIn(ROOT.resolve(), target.parents)
        self.assertTrue(target.is_dir())
        self.assertTrue((target / ".claude-plugin/plugin.json").is_file())
        self.assertEqual(validate_dist.validate(), [])

    def test_marketplace_entry_and_manifest_name_mismatches_are_rejected(self):
        cases = (
            ("openai", validate_dist.ROOT / ".agents/plugins/marketplace.json",
             ".agents/plugins/marketplace.json"),
            ("claude", validate_dist.ROOT / ".claude-plugin/marketplace.json",
             ".claude-plugin/marketplace.json"),
        )
        for host, market_path, market_rel in cases:
            base = json.loads(build_dist.expected_files()[market_rel])
            original_load = validate_dist._load
            def load(path, errors):
                if path == market_path:
                    market = copy.deepcopy(base)
                    market["plugins"][0]["name"] = "different-plugin"
                    return market
                return original_load(path, errors)
            with self.subTest(host=host, kind="entry"), patch.object(validate_dist, "_load", side_effect=load):
                errors = validate_dist.validate()
                self.assertTrue(any("plugin entry name does not match" in error for error in errors), errors)

            manifest_rel = ("dist/openai/plugin.json" if host == "openai"
                            else "dist/claude/.claude-plugin/plugin.json")
            manifest_path = validate_dist.ROOT / manifest_rel
            original_load = validate_dist._load
            def load_manifest(path, errors):
                result = original_load(path, errors)
                if path == manifest_path and isinstance(result, dict):
                    result = copy.deepcopy(result)
                    result["name"] = "different-plugin"
                return result
            with self.subTest(host=host, kind="manifest"), patch.object(
                    validate_dist, "_load", side_effect=load_manifest):
                errors = validate_dist.validate()
                self.assertTrue(any("marketplace entry and manifest name must be ai-agent-workflow" in error
                                    for error in errors), errors)

    def test_marketplace_validation_is_offline_and_release_independent(self):
        with patch.object(
                package_release, "package",
                side_effect=AssertionError("marketplace validation must not package or fall back to Releases")), \
                patch("socket.socket",
                      side_effect=AssertionError("distribution validation must not use the network")):
            self.assertEqual(validate_dist.validate(), [])

    def test_serialized_json_survives_autocrlf_checkout_without_drift(self):
        files = build_dist.expected_files()
        paths = ("dist/openai/plugin.json", "dist/claude/.claude-plugin/plugin.json",
                 ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
            for rel in paths:
                target = repo / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(files[rel])
            for command in (["git", "init", "--quiet"],
                            ["git", "-c", "core.autocrlf=true", "add", "--all"]):
                subprocess.run(command, cwd=repo, check=True, capture_output=True)
            for rel in paths:
                (repo / rel).unlink()
            subprocess.run(["git", "-c", "core.autocrlf=true", "checkout-index", "--all"],
                           cwd=repo, check=True, capture_output=True)
            for rel in paths:
                with self.subTest(path=rel):
                    self.assertEqual((repo / rel).read_bytes(), files[rel])

    def test_release_tag_validation_distinguishes_invalid_and_mismatched_versions(self):
        for tag in ("0.1.0", "v01.1.0", "v0.01.0", "v0.1.00", "v0.1", "v0.1.0-rc.1",
                    "v0.1.0+build", "v0.1.0\n", "v١.1.0"):
            with self.subTest(tag=tag):
                with self.assertRaisesRegex(package_release.PackageError, "invalid release tag"):
                    package_release.validate_tag(tag)
        self.assertEqual(package_release.validate_tag(f"v{__version__}"), __version__)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "assets"
            stream = io.StringIO()
            with patch.object(build_dist, "expected_files", side_effect=AssertionError("must validate tag first")), \
                 redirect_stderr(stream):
                self.assertEqual(package_release.main(["--tag", "v9.8.7", "--output-dir", str(output)]), 1)
            self.assertIn("does not equal agent_workflow.__version__", stream.getvalue())
            self.assertFalse(output.exists())

    def test_release_packaging_rejects_drift_without_repair_or_artifacts(self):
        target = ROOT / "dist/openai/plugin.json"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b" ")  # Still valid JSON, but drifted.
            with tempfile.TemporaryDirectory() as tmp, \
                 patch.object(build_dist, "build", side_effect=AssertionError("must not regenerate")), \
                 patch.object(validate_dist, "validate", side_effect=AssertionError("drift gate must run first")):
                output = Path(tmp) / "assets"
                with self.assertRaisesRegex(package_release.PackageError, "generated file drift: dist/openai/plugin.json"):
                    package_release.package(f"v{__version__}", output)
                self.assertFalse(output.exists())
                self.assertEqual(target.read_bytes(), original + b" ")
        finally:
            target.write_bytes(original)

    def test_release_packaging_requires_host_validation_independently_of_drift(self):
        load = validate_dist._load
        def invalid_host(path, errors):
            manifest = load(path, errors)
            if path == ROOT / "dist/antigravity/plugin.json":
                manifest["version"] = __version__
            return manifest
        with tempfile.TemporaryDirectory() as tmp, patch.object(validate_dist, "_load", side_effect=invalid_host):
            output = Path(tmp) / "assets"
            with self.assertRaisesRegex(package_release.PackageError, "only schema-supported name and description"):
                package_release.package(f"v{__version__}", output)
            self.assertFalse(output.exists())

    def test_release_zip_layout_metadata_bytes_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = package_release.package(f"v{__version__}", Path(tmp) / "one")
            second = package_release.package(f"v{__version__}", Path(tmp) / "two")
            self.assertEqual({p.name: p.read_bytes() for p in first}, {p.name: p.read_bytes() for p in second})
            expected = build_dist.expected_files()
            self.assertEqual({p.name for p in first}, {"SHA256SUMS"} | {
                f"ai-agent-workflow-{host}-v{__version__}.zip" for host in build_dist.HOSTS})
            for host, path in zip(build_dist.HOSTS, first[:3]):
                with ZipFile(path) as archive:
                    members = archive.namelist()
                    prefix = f"dist/{host}/"
                    host_files = {p[len(prefix):]: data for p, data in expected.items() if p.startswith(prefix)}
                    self.assertEqual(members, sorted(host_files))
                    self.assertIn(".claude-plugin/plugin.json" if host == "claude" else "plugin.json", members)
                    self.assertFalse(any(p.startswith("dist/") or "\\" in p for p in members))
                    for info in archive.infolist():
                        self.assertEqual(archive.read(info), host_files[info.filename])
                        self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                        self.assertEqual(info.create_system, 3)
                        self.assertEqual(info.external_attr >> 16, 0o100644)
            sums = first[3].read_text(encoding="utf-8").splitlines()
            expected_sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
                             for p in sorted(first[:3], key=lambda p: p.name)]
            self.assertEqual(sums, expected_sums)

    def test_release_workflow_gates_matrix_permissions_and_publication(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        jobs = dict(re.findall(r"(?ms)^  (prepare|verify|publish):\n(.*?)(?=^  \w+:|\Z)", workflow))
        self.assertEqual(set(jobs), {"prepare", "verify", "publish"})
        self.assertIn('on:\n  push:\n    tags: ["v*"]', workflow)
        self.assertIn("group: release-${{ github.ref }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("fetch-depth: 0", jobs["prepare"])
        self.assertIn('validate_tag(os.environ["RELEASE_TAG"])', jobs["prepare"])
        self.assertIn("git fetch origin +refs/heads/main:refs/remotes/origin/main", jobs["prepare"])
        self.assertIn("git merge-base --is-ancestor HEAD origin/main", jobs["prepare"])
        self.assertLess(jobs["prepare"].index("validate_tag("), jobs["prepare"].index("git fetch"))
        self.assertIn("needs: prepare", jobs["verify"])
        self.assertIn("needs: verify", jobs["publish"])
        matrix = r'- os: (\S+)\n\s+python-version: "([^"]+)"'
        self.assertEqual(re.findall(matrix, jobs["verify"]), re.findall(matrix, ci))
        self.assertEqual(len(re.findall(matrix, jobs["verify"])), 4)
        commands = r"^        run: (.+)$"
        self.assertEqual(re.findall(commands, jobs["verify"], re.M), re.findall(commands, ci, re.M))
        self.assertEqual(workflow.count("contents: write"), 1)
        self.assertIn("permissions:\n      contents: write", jobs["publish"])
        self.assertNotIn("permissions:", jobs["prepare"] + jobs["verify"])
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn('python tools/package_release.py --tag "$RELEASE_TAG" --output-dir "${{ runner.temp }}/release-assets"', jobs["publish"])
        self.assertIn("GH_TOKEN: ${{ github.token }}", jobs["publish"])
        self.assertIn('gh release create "$RELEASE_TAG" --verify-tag', jobs["publish"])
        self.assertIn('gh release upload "$RELEASE_TAG"', jobs["publish"])
        self.assertIn("--clobber", jobs["publish"])
        self.assertEqual(re.findall(r'"\$ASSET_DIR/([^"\n]+)"', jobs["publish"]), [
            "ai-agent-workflow-openai-$RELEASE_TAG.zip", "ai-agent-workflow-claude-$RELEASE_TAG.zip",
            "ai-agent-workflow-antigravity-$RELEASE_TAG.zip", "SHA256SUMS"])
        self.assertNotRegex(workflow, r"git (?:push|tag)|gh api|secrets\.(?!GITHUB_TOKEN)")

    def test_canonical_version_is_injected_only_into_versioned_hosts(self):
        files = build_dist.expected_files()
        for host, rel in (("openai", "plugin.json"), ("claude", ".claude-plugin/plugin.json")):
            self.assertEqual(json.loads(files[f"dist/{host}/{rel}"])["version"], __version__)
            self.assertNotIn("version", json.loads((ROOT / "adapters" / host / "plugin.json").read_bytes()))
        self.assertNotIn("version", json.loads(files["dist/antigravity/plugin.json"]))
        with patch.object(build_dist, "__version__", "2.3.4"):
            changed = build_dist.expected_files()
        for path in ("dist/openai/plugin.json", "dist/claude/.claude-plugin/plugin.json"):
            self.assertEqual(json.loads(changed[path])["version"], "2.3.4")

    def test_adapter_owned_versions_fail_before_build_mutation(self):
        original_json = build_dist._json
        for host in ("openai", "claude"):
            def with_version(path):
                data = original_json(path)
                if path == ROOT / "adapters" / host / "plugin.json":
                    data["version"] = __version__
                return data
            output = io.StringIO()
            with self.subTest(host=host), patch.object(build_dist, "_json", side_effect=with_version), \
                 patch.object(build_dist, "build", side_effect=AssertionError("must not mutate")), \
                 redirect_stderr(output):
                self.assertEqual(build_dist.main([]), 1)
                self.assertIn(f"adapters/{host}/plugin.json: adapter-owned version", output.getvalue())

    def test_pyproject_uses_dynamic_attribute_version(self):
        # Python 3.10 has no tomllib; inspect the specific TOML sections.
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        sections = dict(re.findall(r"(?ms)^\[([^\]]+)\]\n(.*?)(?=^\[|\Z)", text))
        self.assertRegex(sections["project"], r'(?m)^dynamic = \["version"\]$')
        self.assertNotRegex(sections["project"], r"(?m)^\s*version\s*=")
        self.assertRegex(sections["tool.setuptools.dynamic"],
                         r'(?m)^version = \{attr = "agent_workflow\.__version__"\}$')

    def test_validator_rejects_missing_and_mismatched_generated_versions(self):
        original_load = validate_dist._load
        for host, rel in (("openai", "plugin.json"), ("claude", ".claude-plugin/plugin.json")):
            for value in (None, "9.8.7"):
                def wrong_version(path, errors):
                    data = original_load(path, errors)
                    if path == ROOT / "dist" / host / rel:
                        if value is None:
                            data.pop("version", None)
                        else:
                            data["version"] = value
                    return data
                with self.subTest(host=host, value=value), patch.object(validate_dist, "_load", side_effect=wrong_version):
                    self.assertIn(f"dist/{host}/{rel}: version must equal agent_workflow.__version__",
                                  validate_dist.validate())

    def test_check_rejects_existing_drift_without_regeneration(self):
        target = ROOT / "dist/openai/plugin.json"
        original = target.read_bytes()
        changed = original + b" deliberate drift"
        try:
            target.write_bytes(changed)
            output = io.StringIO()
            with patch.object(build_dist, "build", side_effect=AssertionError("must not regenerate")), \
                 redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(build_dist.main(["--check"]), 1)
            self.assertIn("generated file drift", output.getvalue())
            self.assertEqual(target.read_bytes(), changed)
        finally:
            target.write_bytes(original)

    def test_skill_commands_require_the_module_entrypoint(self):
        for command in validate_dist.RUNTIME_COMMANDS:
            for example in (f"Run `{command} 1 2`.", f"```sh\n{command} 1 2\n```",
                            f"Run `python -m agent_workflow agent-context 1 && {command} 1 2`."):
                with self.subTest(command=command, example=example):
                    self.assertTrue(validate_dist.validate_skill_commands(example, "SKILL.md"))
            for example in (f"Run `python -m agent_workflow {command} 1 2`.",
                            f"```sh\npython -m agent_workflow {command} 1 2\n```"):
                self.assertEqual(validate_dist.validate_skill_commands(example, "SKILL.md"), [])

    def test_distribution_validator_rejects_a_bare_skill_instruction(self):
        target = ROOT / "dist/openai/skills/implementation/SKILL.md"
        original = target.read_bytes()
        try:
            target.write_bytes(original.replace(b"python -m agent_workflow agent-context", b"agent-context"))
            self.assertTrue(any("execute agent-context with python -m agent_workflow" in error
                                for error in validate_dist.validate()))
        finally:
            target.write_bytes(original)

    def test_ci_checks_distribution_before_mutation_and_after_build(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        runs = re.findall(r"^        run: (.+)$", workflow, re.M)
        self.assertEqual(runs, [
            "python -m compileall runtime tools tests", "python tools/build_dist.py --check",
            'python -m unittest discover -s tests -p "test_*.py"', "python tools/build_dist.py",
            "python tools/build_dist.py --check", "python tools/validate_dist.py",
            "git diff --exit-code -- dist .agents/plugins/marketplace.json .claude-plugin/marketplace.json",
            "git diff --check",
        ])

    def test_build_is_deterministic_separated_and_check_detects_drift(self):
        first = build_dist.expected_files()
        second = build_dist.expected_files()
        self.assertEqual(first, second)
        build_dist.build(first)
        self.assertEqual(build_dist.check(first), [])
        self.assertEqual(validate_dist.validate(), [])
        target = ROOT / "dist/openai/plugin.json"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b" ")
            self.assertTrue(any("drift" in error for error in build_dist.check(first)))
        finally:
            target.write_bytes(original)
        self.assertEqual(build_dist.check(first), [])

    def test_repo_docs_and_all_host_skill_copies_are_valid(self):
        self.assertEqual(validate_docs(ROOT), [])
        for host in build_dist.HOSTS:
            for name in build_dist.EXPECTED_SKILLS:
                text = (ROOT / "dist" / host / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn(f"name: {name}", text)

    def test_host_manifests_reject_cross_host_and_invalid_schema_fields(self):
        paths = [ROOT / "dist/openai/plugin.json", ROOT / "dist/claude/.claude-plugin/plugin.json",
                 ROOT / "dist/antigravity/plugin.json"]
        originals = [path.read_bytes() for path in paths]
        try:
            paths[0].write_text(json.dumps({"name": "foreign", "description": "invalid portable plugin"}), encoding="utf-8")
            self.assertTrue(any("portable Agent Plugins" in error or "schema/name" in error
                                for error in validate_dist.validate()))
            paths[0].write_bytes(originals[0])
            paths[1].write_text(json.dumps({"name": "Not-Slug", "description": "x"}), encoding="utf-8")
            self.assertTrue(any("lowercase letters/digits/hyphens" in error for error in validate_dist.validate()))
            paths[1].write_bytes(originals[1])
            paths[2].write_text(json.dumps({"$schema": "wrong", "name": "bad name"}), encoding="utf-8")
            self.assertTrue(any("only schema-supported" in error or "violates" in error
                                for error in validate_dist.validate()))
        finally:
            for path, data in zip(paths, originals):
                path.write_bytes(data)


if __name__ == "__main__":
    unittest.main()
