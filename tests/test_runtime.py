from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from agent_workflow.contracts import (ContractError, parse_comment, publish_contract,
                                      restore_contract, save_contract, sha256,
                                      validate_payload, verify_contract)
from agent_workflow.context import ContextError, affected_components
from agent_workflow.cli import _init_project
from agent_workflow.delivery import DeliveryError, delivery_check, finalize_merged_issue
from agent_workflow.documents import validate_markdown_file, validate_docs
from agent_workflow.github import GitHub, GitHubError
from agent_workflow.profile import ProfileError, build_hook_plan, validate_profile
from agent_workflow.process import ProcessError, run_command
from agent_workflow.review import (ReviewError, _extract_items, _with_pointer,
                                   load_review, publish_review, review_path,
                                   validate_public_review)
import build_dist
import validate_dist


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
        "branch": {"required_checks": ["CI"]}, "milestones": {"enabled": False},
        "hooks": {"verify_quick": ["echo global"]},
    }


class FakeGitHub:
    def __init__(self, body=""):
        self.repo = "owner/repo"
        self.issue_data = {"number": 1, "repository_url": "https://api.github.com/repos/owner/repo",
                           "html_url": "https://github.com/owner/repo/issues/1", "state": "open",
                           "pull_request": None, "body": body, "labels": [{"name": "phase:review"}]}
        self.comments = []
        self.next_id = 100
        self.pull_data = None
        self.pull_comments = {}
        self.removed = []
        self.runs = []
        self.commit_statuses = []

    def issue(self, number):
        return copy.deepcopy(self.issue_data)

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

    def test_exact_utf8_bytes_and_line_endings_are_preserved(self):
        raw = "# Contract\r\n\r\nCafe\u0301\n".encode("utf-8")
        metadata = save_contract(self.repo, 1, self.source(raw))
        self.assertEqual((self.repo / ".agent-state/issues/1/implementation-contract.md").read_bytes(), raw)
        self.assertEqual(metadata["sha256"], hashlib.sha256(raw).hexdigest())

    def test_raw_size_nul_and_obvious_credentials_are_rejected(self):
        for raw in (b"x" * 65537, b"a\x00b", b"token=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"):
            with self.subTest(raw=raw[:12]), self.assertRaises(ContractError):
                validate_payload(raw, 1)

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
            draft = {"schema_version": 1, "issue": 1, "pr": 2, "head": "a" * 40,
                     "checklist_sha256": "b" * 64,
                     "items": [{"id": "C001", "text": "check", "result": "pending", "evidence": ""}]}
            path.write_text(json.dumps(draft), encoding="utf-8")
            with self.assertRaises(ReviewError):
                load_review(path)

    def test_public_review_marks_new_commit_as_stale(self):
        gh = FakeGitHub()
        issue, pr = 1, 4
        old_head, current_head = "a" * 40, "b" * 40
        checklist = "c" * 64
        review = {"schema_version": 1, "issue": issue, "pr": pr, "head": old_head,
                  "checklist_sha256": checklist,
                  "items": [{"id": "C001", "text": "thing", "result": "pass", "evidence": "tests/test.py passed"}]}
        payload = json.dumps(review, ensure_ascii=False, sort_keys=True, indent=2)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        body = f"<!-- agent-self-review:v1 issue={issue} pr={pr} head={old_head} checklist={checklist} -->\n\n{payload}"
        gh.pull_data = {"number": pr, "head": {"sha": current_head},
                        "body": _with_pointer("Closes #1", 105, digest, old_head, checklist)}
        gh.pull_comments[105] = {"id": 105, "issue_url": f"https://api.github.com/repos/{gh.repo}/issues/{pr}", "body": body}
        result = validate_public_review(issue, pr, gh)
        self.assertTrue(result["stale"])
        self.assertEqual(result["head"], old_head)

    def test_publish_review_binds_exact_head_and_preserves_pr_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gh = FakeGitHub()
            head, checklist = "f" * 40, "e" * 64
            gh.pull_data = {"number": 2, "state": "open", "draft": False,
                            "base": {"repo": {"full_name": gh.repo}}, "head": {"sha": head},
                            "body": "Closes #1\n\n## Verification\ntests passed\n\n## Untested\nIDE smoke test not run\n"}
            draft = {"schema_version": 1, "issue": 1, "pr": 2, "head": head,
                     "checklist_sha256": checklist,
                     "items": [{"id": "C001", "text": "check", "result": "pass", "evidence": "test output"}]}
            path = review_path(repo, 1, 2)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(draft), encoding="utf-8")
            with patch("agent_workflow.review.effective_checklist", return_value=([{"id": "C001", "text": "check"}], checklist)):
                result = publish_review(repo, 1, 2, gh)
            self.assertEqual(result["head"], head)
            self.assertIn("Closes #1", gh.pull_data["body"])
            self.assertIn("## Verification", gh.pull_data["body"])
            self.assertIn("## Untested", gh.pull_data["body"])
            self.assertIn("## Agent Self-Review", gh.pull_data["body"])
            valid = validate_public_review(1, 2, gh)
            self.assertFalse(valid["stale"])


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


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        (self.repo / ".agent").mkdir()
        data = {"schema_version": 2, "initialized": False, "project_name": "x",
                "components": [{"id": "root", "roots": ["."], "stacks": [],
                                "application_types": ["cli"], "targets": [], "hooks": {}}],
                "branch": {"required_checks": [{"name": "CI", "app_id": 77}]},
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
                            "base": {"repo": {"full_name": self.gh.repo}},
                            "head": {"sha": self.head, "repo": {"full_name": self.gh.repo}},
                            "body": self.pr_body}
        self.gh.runs = [{"name": "CI", "head_sha": self.head, "status": "completed",
                         "conclusion": "success", "app": {"id": 77}}]

    def tearDown(self):
        self.temp.cleanup()

    def run_gate(self, **changes):
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
        published = changes.pop("published_review", {"stale": False, "head": self.head, "checklist_sha256": "c" * 64,
                     "review": {"items": [{"id": "C001", "text": "works"}]}}
                     )
        with patch("agent_workflow.delivery.validate_public_review", return_value=published), \
             patch("agent_workflow.delivery.effective_checklist", return_value=([{"id": "C001", "text": "works"}], "c" * 64)):
            return delivery_check(self.repo, 1, 2, self.gh)

    def test_handoff_passes_only_with_current_review_and_green_app_check(self):
        result = self.run_gate()
        self.assertTrue(result["passed"], result["errors"])

    def test_each_required_handoff_precondition_is_checked(self):
        cases = [
            ({"draft": True}, "non-draft"),
            ({"issue_state": "closed"}, "open Issue"),
            ({"body": "## Verification\npassed\n\n## Untested\nnone"}, "Closes #1"),
            ({"issue_labels": []}, "phase:review"),
            ({"head": {"sha": "e" * 40, "repo": {"full_name": "owner/repo"}}}, "stale"),
            ({"published_review": {"stale": False, "head": "d" * 40, "checklist_sha256": "c" * 64,
                                    "review": {"items": []}}}, "items do not match"),
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
