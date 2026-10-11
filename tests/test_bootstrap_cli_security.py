from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tests"))

import test_gate_policy as fixtures
from p_ases import cli
from p_ases.gate_policy import GateSelection


class BootstrapCLISecurityTests(unittest.TestCase):
    def test_cli_bootstrap_route_rejects_same_number_in_another_repository(self):
        github = Mock()
        github.pull_request.return_value = fixtures.pr_readback()
        adc = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=100, sha256=fixtures.ADC, state="approved"),
            contract=SimpleNamespace(requirement_ids=("REQ-08",), section=lambda _name: "- [ ] one"),
        )
        args = SimpleNamespace(issue=27, pr=33, self_review_comment=None,
                               independent_review_comment=None, unverified_host=("none",))
        output = {}
        with patch("p_ases.cli.read_bootstrap_adc", return_value=adc), \
                patch("p_ases.cli._json", side_effect=lambda value: output.update(value)), \
                patch("p_ases.cli.run_local_bootstrap_checks_bound") as run_checks:
            exit_code = cli._delivery_bootstrap_check(
                args, "another-owner/another-repo", Path("/fake/repo"), github)
        self.assertEqual(exit_code, 2)
        self.assertEqual(output.get("status"), "BOOTSTRAP_BLOCKED")
        self.assertTrue(any("fixed cohort repository" in reason for reason in output.get("reasons", [])))
        run_checks.assert_not_called()

    def test_checkout_change_after_github_reads_or_immediately_before_publish_blocks_ready(self):
        github = Mock()
        github.pull_request.return_value = fixtures.pr_readback()
        github.check_runs_for_ref.return_value = fixtures.check_runs()
        github.workflow_runs_for_ref.return_value = [fixtures.workflow_run()]
        adc = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=100, sha256=fixtures.ADC, state="approved"),
            contract=SimpleNamespace(requirement_ids=("REQ-08",), section=lambda _name: "- [ ] one"),
        )
        args = SimpleNamespace(issue=27, pr=33, self_review_comment=200,
                               independent_review_comment=201, unverified_host=("none",))
        for fail_on in (1, 3):
            with self.subTest(checkout_recheck=fail_on):
                local_state = {"checks": 0}
                published = []

                def checkout_stub(_root, _subject):
                    local_state["checks"] += 1
                    # Call 1 follows GitHub artifact/CI reads; call 3 is immediately
                    # before publication, after the final ADC/PR snapshot.
                    if local_state["checks"] == fail_on:
                        raise cli.GatePolicyError("local checkout is not clean; tracked file changed")

                def publish_stub(_github, _issue, _sentinel, payload):
                    published.append(payload)
                    return 900, "record"

                output = {}
                with patch("p_ases.cli.read_bootstrap_adc", return_value=adc), \
                        patch("p_ases.cli.choose_gate_for_new_issue",
                              return_value=GateSelection(fixtures.REPO, 27, "bootstrap-legacy-v1", "2026-10-11T00:00:00Z")), \
                        patch("p_ases.cli.pin_gate_selection", return_value=(900, "selection")), \
                        patch("p_ases.cli.run_local_bootstrap_checks_bound", return_value=fixtures.local_checks()), \
                        patch("p_ases.cli.current_checkout_subject", side_effect=checkout_stub), \
                        patch("p_ases.cli.read_review_comment", return_value={"body": "review"}), \
                        patch("p_ases.cli.parse_self_review_comment", return_value=fixtures.self_review()), \
                        patch("p_ases.cli.parse_independent_review_comment", return_value=fixtures.independent_review()), \
                        patch("p_ases.cli.verify_independent_context_artifact",
                              side_effect=lambda _gh, _subject, review: review), \
                        patch("p_ases.cli.verify_bootstrap_review_evidence",
                              return_value=fixtures.self_review().verified_evidence), \
                        patch("p_ases.cli.load_profile", return_value=SimpleNamespace(required_checks=(
                            ("test-a", 789), ("test-b", 789)))), \
                        patch("p_ases.cli.bootstrap_policy_digest", return_value="f" * 64), \
                        patch("p_ases.cli.evaluate_bootstrap", return_value=fixtures.evaluate()), \
                        patch("p_ases.cli.publish_immutable_record", side_effect=publish_stub), \
                        patch("p_ases.cli.read_bootstrap_evidence", side_effect=lambda *_args: published[-1]), \
                        patch("p_ases.cli._json", side_effect=lambda value: output.update(value)):
                    exit_code = cli._delivery_bootstrap_check(args, fixtures.REPO, Path("/fake/repo"), github)

                self.assertEqual(exit_code, 2)
                self.assertEqual(output.get("status"), "BOOTSTRAP_BLOCKED")
                self.assertTrue(any("tracked file changed" in reason for reason in output.get("reasons", [])))
                if fail_on == 3:
                    self.assertEqual(published, [])
                else:
                    self.assertEqual(len(published), 1)
                    self.assertEqual(published[0]["status"], "BOOTSTRAP_BLOCKED")


if __name__ == "__main__":
    unittest.main()
