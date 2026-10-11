from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases import cli
from p_ases.adc import ADCPointer
from p_ases.evidence_store import VerificationSubject


class FakePullRequestGitHub:
    def __init__(self):
        self.current_head = "b" * 40
        self.head_reads: list[str] = []
        self.head_sequence: list[str] = []
        self.comments_created = 0

    def pull_request(self, number):
        if self.head_sequence:
            self.current_head = self.head_sequence.pop(0)
        self.head_reads.append(self.current_head)
        return {
            "number": number, "state": "open", "draft": False,
            "body": "Implementation details.\n\nCloses #29\n",
            "base": {"ref": "pases/adc-core", "sha": "c" * 40,
                     "repo": {"full_name": "owner/repo"}},
            "head": {"ref": "pases/verification", "sha": self.current_head,
                     "repo": {"full_name": "owner/repo"}},
        }

    def check_runs_for_ref(self, _head):
        return []

    def create_issue_comment(self, _issue, _body):
        self.comments_created += 1
        return {"id": self.comments_created}

    def issue_comments(self, _issue):
        return []

    def issue_comment(self, _issue, _comment):
        raise AssertionError("no result should be published for a stale PR HEAD")


class VerificationCLITests(unittest.TestCase):
    def test_current_pr_readback_binds_head_repo_state_base_and_issue_closing_line(self):
        subject = VerificationSubject("owner/repo", 29, 83, 501, "a" * 64, "c" * 64, "b" * 40)
        good = FakePullRequestGitHub().pull_request(83)

        class ResponseGitHub:
            def __init__(self, response):
                self.response = response

            def pull_request(self, _number):
                return self.response

        self.assertEqual(cli._readback_current_pr(ResponseGitHub(good), subject)["head_sha"], "b" * 40)
        invalid_rows = []
        for key, value in (("state", "closed"), ("draft", True), ("number", 84),
                           ("body", "Closes #30\n"), ("body", "Closes #29\nCloses #30\n")):
            changed = dict(good)
            changed[key] = value
            invalid_rows.append(changed)
        for side, key, value in (
            ("head", "sha", "f" * 40),
            ("head", "ref", "pases/other"),
            ("head", "repo", {"full_name": "someone/fork"}),
            ("base", "ref", "main"),
            ("base", "sha", "not-a-sha"),
            ("base", "repo", {"full_name": "someone/other"}),
        ):
            changed = {**good, side: {**good[side], key: value}}
            invalid_rows.append(changed)
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaises(cli.CLIError):
                cli._readback_current_pr(ResponseGitHub(row), subject)

    def test_acceptance_keeps_upstream_issues_in_waiting_dependency_state(self):
        class FakeGitHub:
            def issue(self, number):
                return {"number": number, "state": "open"}

        contract = SimpleNamespace(issue_number=29, section=lambda _name: "")
        reasons = cli._unaccepted_dependencies(FakeGitHub(), contract)
        self.assertEqual(len(reasons), 2)
        self.assertIn("WAITING_DEPENDENCY #27", reasons[0])
        self.assertIn("WAITING_DEPENDENCY #28", reasons[1])

    def test_plan_collect_validate_uses_external_evidence_and_reports_missing_trust_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".agent").mkdir()
            (root / ".agent" / "project.json").write_text(
                json.dumps({"branch": {"required_checks": [{"name": "required-ci"}]}}), encoding="utf-8",
            )
            (root / "spec.md").write_text("REQ-01: Frozen expected behavior.\n", encoding="utf-8")
            (root / "tests.md").write_text("REQ-01: Independently specified test.\n", encoding="utf-8")
            (root / "oracle.md").write_text("The independent behavior is exact.\n", encoding="utf-8")
            plan_input = {
                "sources": [
                    {"kind": "specification", "name": "spec.md"},
                    {"kind": "test_specification", "name": "tests.md"},
                    {"kind": "oracle", "name": "oracle.md"},
                ],
                "entries": [{
                    "acceptance": "assert the frozen expected behavior",
                    "command": ["/usr/bin/python", "-m", "unittest"],
                    "environment": "ubuntu-py314", "evidence_required": ["result"],
                    "manual_procedure": "", "oracle_id": "ORACLE-01", "req_id": "REQ-01",
                    "risk": "high", "target": "linux", "test_id": "TEST-01",
                }],
                "oracles": [{
                    "derived_from_implementation": False,
                    "expected_behavior": "The independent behavior is exact.",
                    "oracle_id": "ORACLE-01", "req_ids": ["REQ-01"],
                    "source_kind": "frozen_specification", "source_ref": "oracle.md",
                    "source_sha256": "",
                }],
                "tests": [{
                    "derived_from_implementation": False, "req_id": "REQ-01", "source_ref": "tests.md",
                    "source_sha256": "", "target": "linux", "test_id": "TEST-01",
                }],
            }
            import hashlib
            plan_input["oracles"][0]["source_sha256"] = hashlib.sha256((root / "oracle.md").read_bytes()).hexdigest()
            plan_input["tests"][0]["source_sha256"] = hashlib.sha256((root / "tests.md").read_bytes()).hexdigest()
            input_path = root / "plan-input.json"
            input_path.write_text(json.dumps(plan_input), encoding="utf-8")
            pointer = ADCPointer(501, "a" * 64, 1234, "approved")
            verified = SimpleNamespace(pointer=pointer, contract=SimpleNamespace(requirement_ids=("REQ-01",)))
            fake_github = FakePullRequestGitHub()
            with patch.object(cli, "GitHub", return_value=fake_github), patch.object(cli, "verify_adc", return_value=verified):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = cli.main(["verification", "plan", "29", str(input_path),
                                     "--repo", "owner/repo", "--root", str(root)])
                self.assertEqual(code, 0)
                plan_output = json.loads(stdout.getvalue())
                plan_path = Path(plan_output["plan_path"])

                observation = {
                    "command": ["/usr/bin/python", "-m", "unittest"],
                    "entry_key": "REQ-01|ORACLE-01|TEST-01|linux",
                    "environment": "ubuntu-py314", "evidence_type": "result", "exit_status": 0,
                    "manual_procedure": "", "observed_at": "2026-10-11T00:00:00Z",
                    "outcome": "PASS", "output_sha256": "f" * 64, "runner_source": "local",
                }
                observation_path = root / "execution.json"
                observation_path.write_text(json.dumps(observation), encoding="utf-8")
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = cli.main(["verification", "collect", "29", "83", "b" * 40,
                                     str(plan_path), str(observation_path), "--repo", "owner/repo",
                                     "--root", str(root)])
                self.assertEqual(code, 0)
                collected = json.loads(stdout.getvalue())
                self.assertEqual(collected["status"], "EVIDENCE_RECORDED")
                self.assertTrue(Path(collected["evidence_refs"][0]).is_file())

                # A PR that advances after the initial A readback invalidates the whole calculation.
                changing_github = FakePullRequestGitHub()
                changing_github.head_sequence[:] = ["b" * 40, "f" * 40]
                with patch.object(cli, "GitHub", return_value=changing_github):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        code = cli.main(["verification", "validate", "29", "83", "b" * 40,
                                         str(plan_path), "--repo", "owner/repo", "--root", str(root)])
                    self.assertEqual(code, 2)
                    moved = json.loads(stdout.getvalue())
                    self.assertEqual(moved["status"], "BLOCKED")
                    self.assertIn("current GitHub PR HEAD", " ".join(moved["reasons"]))

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = cli.main(["verification", "validate", "29", "83", "b" * 40,
                                     str(plan_path), "--repo", "owner/repo", "--root", str(root)])
                self.assertEqual(code, 2)
                blocked = json.loads(stdout.getvalue())
                self.assertEqual(blocked["status"], "BLOCKED")
                self.assertIn("trusted_app_id", " ".join(blocked["reasons"]))

                # Every evidence-producing or publishing entry point must refuse saved A evidence
                # once GitHub reports that the same PR now points at B.
                frozen_subject = VerificationSubject(
                    "owner/repo", 29, 83, pointer.comment_id, pointer.sha256,
                    plan_output["plan_sha256"], "b" * 40,
                ).validate()
                fake_github.current_head = "f" * 40

                def invoke(command):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        return cli.main(command), json.loads(output.getvalue())

                observation_count_before = len(list((root / ".p_ases" / "evidence").rglob("*.json")))
                observation_path.write_text(json.dumps(observation), encoding="utf-8")
                stale_calls = [
                    ["verification", "collect", "29", "83", "b" * 40,
                     str(plan_path), str(observation_path), "--repo", "owner/repo", "--root", str(root)],
                    ["verification", "validate", "29", "83", "b" * 40,
                     str(plan_path), "--repo", "owner/repo", "--root", str(root)],
                    ["verification", "final", "29", "83", "b" * 40,
                     str(plan_path), "--repo", "owner/repo", "--root", str(root)],
                    ["acceptance", "prepare", "29", "83", "b" * 40,
                     str(plan_path), "documentation_only", str(root / "stale-template.json"),
                     "--repo", "owner/repo", "--root", str(root)],
                ]
                observations_path = root / "stale-observations.json"
                observations_path.write_text("{}\n", encoding="utf-8")
                stale_calls.append(["acceptance", "validate", "29", "83", "b" * 40,
                                    str(plan_path), "documentation_only", str(observations_path),
                                    str(root / "old-verification.json"),
                                    "--repo", "owner/repo", "--root", str(root)])
                for command in stale_calls:
                    code, stale = invoke(command)
                    self.assertEqual(code, 2, command[1])
                    self.assertEqual(stale["status"], "BLOCKED", command[1])
                    self.assertIn("current GitHub PR HEAD", " ".join(stale["reasons"]), command[1])
                self.assertFalse((root / "stale-template.json").exists())
                self.assertEqual(len(list((root / ".p_ases" / "evidence").rglob("*.json"))),
                                 observation_count_before)

                # Readback-only/publish operations also reject saved A results before comment I/O.
                verification_result_path = root / "old-verification.json"
                with patch.object(cli, "read_verification_result",
                                  return_value=SimpleNamespace(subject=frozen_subject)):
                    code, stale = invoke(["verification", "published", "29", str(verification_result_path),
                                          "--repo", "owner/repo", "--root", str(root)])
                self.assertEqual(code, 2)
                self.assertEqual(stale["status"], "BLOCKED")
                self.assertIn("current GitHub PR HEAD", " ".join(stale["reasons"]))

                acceptance_result = SimpleNamespace(subject=frozen_subject)
                for verb in ("publish", "verify"):
                    with patch.object(cli, "read_acceptance_result", return_value=acceptance_result):
                        code, stale = invoke(["acceptance", verb, "29", str(root / "old-acceptance.json"),
                                              "--repo", "owner/repo", "--root", str(root)])
                    self.assertEqual(code, 2, verb)
                    self.assertEqual(stale["status"], "BLOCKED", verb)
                    self.assertIn("current GitHub PR HEAD", " ".join(stale["reasons"]), verb)
                self.assertEqual(fake_github.comments_created, 0)

                trace_path = plan_path.with_suffix(".trace.json")
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                trace["oracles"][0]["expected_behavior"] = "tampered after Plan freeze"
                # Keep the deliberate file bytes identical across Windows' text newline translation.
                trace_path.write_bytes((json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = cli.main(["verification", "validate", "29", "83", "b" * 40,
                                     str(plan_path), "--repo", "owner/repo", "--root", str(root)])
                self.assertEqual(code, 2)
                stale_trace = json.loads(stdout.getvalue())
                self.assertEqual(stale_trace["status"], "BLOCKED")
                self.assertIn("changed after Plan creation", " ".join(stale_trace["reasons"]))


if __name__ == "__main__":
    unittest.main()
