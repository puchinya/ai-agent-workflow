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


class VerificationCLITests(unittest.TestCase):
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
            with patch.object(cli, "GitHub", return_value=object()), patch.object(cli, "verify_adc", return_value=verified):
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

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = cli.main(["verification", "validate", "29", "83", "b" * 40,
                                     str(plan_path), "--repo", "owner/repo", "--root", str(root)])
                self.assertEqual(code, 2)
                blocked = json.loads(stdout.getvalue())
                self.assertEqual(blocked["status"], "BLOCKED")
                self.assertIn("trusted_app_id", " ".join(blocked["reasons"]))

                trace_path = plan_path.with_suffix(".trace.json")
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                trace["oracles"][0]["expected_behavior"] = "tampered after Plan freeze"
                trace_path.write_text(json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n",
                                      encoding="utf-8")
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
