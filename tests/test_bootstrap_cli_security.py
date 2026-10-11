from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tests"))

import test_gate_policy as fixtures
from p_ases import cli
from p_ases.gate_policy import GatePolicyError, GateSelection


class BootstrapCLISecurityTests(unittest.TestCase):
    def test_legacy_review_cli_options_are_documented_as_ignored(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            cli._parser().parse_args(["delivery", "bootstrap-check", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("accepted and ignored", output.getvalue())

    def _run_post_publish_scenario(self, *, mutate_pr=None, gate_reads=None, adc_reads=None,
                                   ambiguous_first_publish=False):
        github = Mock()
        current_pr = {"value": fixtures.pr_readback()}
        github.pull_request.side_effect = lambda _number: deepcopy(current_pr["value"])
        github.check_runs_for_ref.return_value = fixtures.check_runs()
        github.workflow_runs_for_ref.return_value = [fixtures.workflow_run()]
        adc = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=100, sha256=fixtures.ADC, state="approved"),
            contract=SimpleNamespace(requirement_ids=("REQ-08",), section=lambda _name: "- [ ] one"),
        )
        args = SimpleNamespace(issue=27, pr=33, self_review_comment=999999,
                               independent_review_comment=999998, unverified_host=("none",))
        selection = GateSelection(fixtures.REPO, 27, "bootstrap-legacy-v1", "2026-10-11T00:00:00Z")
        gate_reads = gate_reads or [(900, selection, "selection")] * 3
        observations = []
        comment_ids = []

        def publish_stub(_github, _issue, _sentinel, payload):
            observations.append(payload)
            comment_ids.append(900 + len(observations))
            if len(observations) == 1 and mutate_pr is not None:
                mutate_pr(current_pr["value"])
            if len(observations) == 1 and ambiguous_first_publish:
                raise GatePolicyError("simulated timeout after remote append")
            return comment_ids[-1], "record"

        output = {}
        with patch("p_ases.cli.read_bootstrap_adc",
                   side_effect=adc_reads if adc_reads is not None else None,
                   return_value=adc if adc_reads is None else None), \
                patch("p_ases.cli.choose_gate_for_new_issue", return_value=selection), \
                patch("p_ases.cli.pin_gate_selection", return_value=(900, "selection")), \
                patch("p_ases.cli.read_gate_selection", side_effect=gate_reads), \
                patch("p_ases.cli.run_local_bootstrap_checks_bound", return_value=fixtures.local_checks()), \
                patch("p_ases.cli.current_checkout_subject"), \
                patch("p_ases.gate_policy.read_review_comment") as read_review, \
                patch("p_ases.gate_policy.verify_bootstrap_review_evidence") as verify_review, \
                patch("p_ases.cli.load_profile", return_value=SimpleNamespace(required_checks=(
                    ("test-a", 789), ("test-b", 789)))), \
                patch("p_ases.cli.bootstrap_policy_digest", return_value="f" * 64), \
                patch("p_ases.cli.evaluate_bootstrap", return_value=fixtures.evaluate()), \
                patch("p_ases.cli.publish_immutable_record", side_effect=publish_stub), \
                patch("p_ases.cli.read_bootstrap_evidence",
                      side_effect=lambda _gh, _issue, comment_id: observations[comment_ids.index(comment_id)]), \
                patch("p_ases.cli.read_latest_bootstrap_evidence",
                      side_effect=lambda *_args: (comment_ids[-1], observations[-1])), \
                patch("p_ases.cli._json", side_effect=lambda value: output.update(value)):
            exit_code = cli._delivery_bootstrap_check(args, fixtures.REPO, Path("/fake/repo"), github)
        read_review.assert_not_called()
        verify_review.assert_not_called()
        return exit_code, output, observations, comment_ids

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
        selection = GateSelection(fixtures.REPO, 27, "bootstrap-legacy-v1", "2026-10-11T00:00:00Z")
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
                        patch("p_ases.cli.choose_gate_for_new_issue", return_value=selection), \
                        patch("p_ases.cli.pin_gate_selection", return_value=(900, "selection")), \
                        patch("p_ases.cli.read_gate_selection", return_value=(900, selection, "selection")), \
                        patch("p_ases.cli.run_local_bootstrap_checks_bound", return_value=fixtures.local_checks()), \
                        patch("p_ases.cli.current_checkout_subject", side_effect=checkout_stub), \
                        patch("p_ases.cli.load_profile", return_value=SimpleNamespace(required_checks=(
                            ("test-a", 789), ("test-b", 789)))), \
                        patch("p_ases.cli.bootstrap_policy_digest", return_value="f" * 64), \
                        patch("p_ases.cli.evaluate_bootstrap", return_value=fixtures.evaluate()), \
                        patch("p_ases.cli.publish_immutable_record", side_effect=publish_stub), \
                        patch("p_ases.cli.read_bootstrap_evidence", side_effect=lambda *_args: published[-1]), \
                        patch("p_ases.cli.read_latest_bootstrap_evidence",
                              side_effect=lambda *_args: (900 + len(published), published[-1])), \
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

    def test_post_publish_pr_identity_changes_append_a_latest_blocked_observation(self):
        mutations = {
            "body": lambda pr: pr.update(body="Closes #99\n"),
            "base-ref": lambda pr: pr["base"].update(ref="other-base"),
            "base-sha": lambda pr: pr["base"].update(sha="d" * 40),
            "base-repository": lambda pr: pr["base"]["repo"].update(full_name="another/repo"),
            "head-ref": lambda pr: pr["head"].update(ref="other-head"),
            "head-repository": lambda pr: pr["head"]["repo"].update(full_name="fork/branch"),
            "pr-number": lambda pr: pr.update(number=999),
            "draft": lambda pr: pr.update(draft=True),
            "closed": lambda pr: pr.update(state="closed"),
        }
        for label, mutate in mutations.items():
            with self.subTest(change=label):
                exit_code, output, observations, comment_ids = self._run_post_publish_scenario(
                    mutate_pr=mutate)
                self.assertEqual(exit_code, 2)
                self.assertEqual(output.get("status"), "BOOTSTRAP_BLOCKED")
                self.assertEqual([row["status"] for row in observations],
                                 ["BOOTSTRAP_TECHNICAL_READY", "BOOTSTRAP_BLOCKED"])
                self.assertEqual(output.get("evidence_comment_id"), comment_ids[-1])
                self.assertTrue(any("changed during evidence publication" in reason
                                    for reason in observations[-1]["reasons"]))

    def test_post_publish_gate_selection_change_appends_latest_blocked_observation(self):
        initial = GateSelection(fixtures.REPO, 27, "bootstrap-legacy-v1", "2026-10-11T00:00:00Z")
        changed = GateSelection(fixtures.REPO, 27,
                                "bootstrap-legacy-v1", "2026-10-11T00:01:00Z")
        gate_reads = [(900, initial, "selection"), (900, initial, "selection"),
                      (900, changed, "changed selection")]
        exit_code, output, observations, comment_ids = self._run_post_publish_scenario(
            gate_reads=gate_reads)
        self.assertEqual(exit_code, 2)
        self.assertEqual([row["status"] for row in observations],
                         ["BOOTSTRAP_TECHNICAL_READY", "BOOTSTRAP_BLOCKED"])
        self.assertEqual(output.get("evidence_comment_id"), comment_ids[-1])
        self.assertTrue(any("pinned gate selection identity changed" in reason
                            for reason in observations[-1]["reasons"]))

    def test_ambiguous_ready_publish_is_read_back_then_invalidated_on_subject_drift(self):
        exit_code, output, observations, comment_ids = self._run_post_publish_scenario(
            mutate_pr=lambda pr: pr.update(body="Closes #99\n"),
            ambiguous_first_publish=True)
        self.assertEqual(exit_code, 2)
        self.assertEqual([row["status"] for row in observations],
                         ["BOOTSTRAP_TECHNICAL_READY", "BOOTSTRAP_BLOCKED"])
        self.assertEqual(output.get("evidence_comment_id"), comment_ids[-1])

    def test_post_publish_adc_pointer_change_appends_latest_blocked_observation(self):
        original_adc = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=100, sha256=fixtures.ADC, state="approved"),
            contract=SimpleNamespace(requirement_ids=("REQ-08",), section=lambda _name: "- [ ] one"),
        )
        changed_adc = SimpleNamespace(
            pointer=SimpleNamespace(comment_id=101, sha256="d" * 64, state="approved"),
            contract=original_adc.contract,
        )
        exit_code, output, observations, comment_ids = self._run_post_publish_scenario(
            adc_reads=[original_adc, original_adc, changed_adc])
        self.assertEqual(exit_code, 2)
        self.assertEqual([row["status"] for row in observations],
                         ["BOOTSTRAP_TECHNICAL_READY", "BOOTSTRAP_BLOCKED"])
        self.assertEqual(output.get("evidence_comment_id"), comment_ids[-1])
        self.assertTrue(any("ADC pointer changed" in reason for reason in observations[-1]["reasons"]))

    def test_unchanged_post_publish_subject_keeps_ready_as_latest(self):
        exit_code, output, observations, _comment_ids = self._run_post_publish_scenario()
        self.assertEqual(exit_code, 0)
        self.assertEqual(output.get("status"), "BOOTSTRAP_TECHNICAL_READY")
        self.assertEqual([row["status"] for row in observations], ["BOOTSTRAP_TECHNICAL_READY"])


if __name__ == "__main__":
    unittest.main()
