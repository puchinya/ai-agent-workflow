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

from p_ases.branch_policy import EffectiveBranchPolicy  # noqa: E402
from p_ases.github import GitHubError  # noqa: E402
from p_ases.ruleset_management import (  # noqa: E402
    APPLIED_MARKER, RULESET_NAME, RulesetManagementError, _canonical, _desired_payload, _managed_body,
    _body_digest, _publish_applied_record, _verify_exact_approval, apply_ruleset_plan,
    effective_policy_sha256, validate_plan, verify_applied_policy_record, write_plan,
)


REPOSITORY = "puchinya/ai-agent-workflow"
PLAN_SHA = "a" * 64
OWNER_ID = 3744776


def approval_row(comment_id: int, body: str, *, actor_id: int = OWNER_ID,
                 updated_at: str = "2026-10-17T00:00:00Z", issue_number: int = 57):
    return {
        "id": comment_id,
        "body": body,
        "created_at": "2026-10-17T00:00:00Z",
        "updated_at": updated_at,
        "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{issue_number}",
        "html_url": f"https://github.com/{REPOSITORY}/issues/{issue_number}#issuecomment-{comment_id}",
        "user": {"id": actor_id, "login": "puchinya", "type": "User"},
    }


class FakeApprovalGitHub:
    repo = REPOSITORY

    def __init__(self, row):
        self.row = copy.deepcopy(row)

    def issue(self, number):
        self.issue_number = number
        return {"number": number, "state": "open", "pull_request": None,
                "repository_url": f"https://api.github.com/repos/{REPOSITORY}"}

    def issue_comment(self, issue_number, comment_id):
        if issue_number != self.issue_number:
            raise AssertionError("approval check used an unexpected Issue")
        return copy.deepcopy(self.row)

    def issue_comments(self, issue_number):
        if issue_number != self.issue_number:
            raise AssertionError("approval list used an unexpected Issue")
        return [copy.deepcopy(self.row)]


def make_plan(**updates):
    checks = [{"context": "ci", "integration_id": 15368}]
    desired = _desired_payload(REPOSITORY, (("ci", 15368),))
    value = {
        "activation_issue_number": 57,
        "blockers": [],
        "default_branch": "main",
        "default_branch_sha40": "1" * 40,
        "diff": {"operation": "create", "before": None, "before_body_sha256": None,
                 "after": desired,
                 "changed_fields": ["bypass_actors", "conditions", "enforcement", "name", "rules", "target"]},
        "existing_ruleset_id": None,
        "existing_ruleset_sha256": None,
        "owner_id": OWNER_ID,
        "plan_schema": "PASES_RULESET_PLAN_V1",
        "policy_evidence": {
            "branch": {"name": "main", "protected": False, "commit": {"sha": "1" * 40}},
            "legacy_protection": None,
            "source_errors": {"legacy_protection": 404},
        },
        "policy_proof": {"status": "NOT_CONFIGURED"},
        "predecessor_comment_id": None,
        "profile_review_mode": "solo_owner",
        "profile_sha256": "b" * 64,
        "repository": REPOSITORY,
        "repository_id": 1401910271,
        "required_checks": checks,
        "desired_ruleset": desired,
        "existing_pr_impact": [],
    }
    value.update(updates)
    value["plan_sha256"] = hashlib.sha256(_canonical(value)).hexdigest()
    return value


class RulesetManagementTests(unittest.TestCase):
    def test_desired_ruleset_uses_exact_repository_policy(self):
        payload = _desired_payload(REPOSITORY, (("windows", 15368), ("ubuntu", 15368)))
        self.assertEqual(payload["name"], RULESET_NAME)
        self.assertEqual(payload["target"], "branch")
        self.assertEqual(payload["enforcement"], "active")
        self.assertEqual(payload["conditions"], {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}})
        self.assertEqual(payload["bypass_actors"], [])
        self.assertEqual([row["type"] for row in payload["rules"]], [
            "pull_request", "required_status_checks", "non_fast_forward",
        ])
        pr = payload["rules"][0]["parameters"]
        self.assertEqual(pr["required_approving_review_count"], 0)
        self.assertTrue(pr["required_review_thread_resolution"])
        self.assertEqual(pr["allowed_merge_methods"], ["merge", "squash", "rebase"])
        checks = payload["rules"][1]["parameters"]["required_status_checks"]
        self.assertEqual(checks, [
            {"context": "ubuntu", "integration_id": 15368},
            {"context": "windows", "integration_id": 15368},
        ])

    def test_managed_body_normalizes_only_nonsemantic_api_defaults(self):
        payload = _desired_payload(REPOSITORY, (("ci", 15368),))
        response = copy.deepcopy(payload)
        response["rules"][-1]["parameters"] = {}
        self.assertEqual(_managed_body(payload), _managed_body(response))
        response["rules"].append({"type": "creation", "parameters": {}})
        self.assertNotEqual(_managed_body(payload), _managed_body(response))

    def test_plan_digest_rejects_any_changed_bound_field(self):
        plan = make_plan()
        self.assertEqual(validate_plan(plan), plan)
        for field, value in (("owner_id", OWNER_ID + 1), ("repository_id", 42),
                             ("profile_sha256", "c" * 64), ("repository", "other/repo")):
            changed = copy.deepcopy(plan)
            changed[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(RulesetManagementError, "digest"):
                validate_plan(changed)

    def test_plan_rejects_approved_digest_with_mutated_ruleset_payload(self):
        plan = make_plan()
        changed = copy.deepcopy(plan)
        changed["desired_ruleset"]["bypass_actors"] = [{"actor_id": 9}]
        changed["diff"]["after"] = copy.deepcopy(changed["desired_ruleset"])
        changed["plan_sha256"] = hashlib.sha256(
            _canonical({key: item for key, item in changed.items() if key != "plan_sha256"})
        ).hexdigest()
        with self.assertRaisesRegex(RulesetManagementError, "desired Ruleset"):
            validate_plan(changed)

    def test_exact_owner_approval_requires_issue_repo_actor_and_immutable_body(self):
        plan = make_plan()
        expected = (f"PASES-RULESET-APPROVE: {plan['plan_sha256']}\n"
                    f"PASES-REPOSITORY: {REPOSITORY}")
        github = FakeApprovalGitHub(approval_row(900, expected))
        self.assertEqual(_verify_exact_approval(github, plan, 900)["id"], 900)
        wrong_actor = FakeApprovalGitHub(approval_row(900, expected, actor_id=1))
        with self.assertRaisesRegex(RulesetManagementError, "approval comment"):
            _verify_exact_approval(wrong_actor, plan, 900)
        edited = FakeApprovalGitHub(approval_row(900, expected, updated_at="2026-10-17T00:05:00Z"))
        with self.assertRaisesRegex(RulesetManagementError, "approval comment"):
            _verify_exact_approval(edited, plan, 900)
        wrong_plan = FakeApprovalGitHub(approval_row(900, "PASES-RULESET-APPROVE: " + "d" * 64
                                                     + f"\nPASES-REPOSITORY: {REPOSITORY}"))
        with self.assertRaisesRegex(RulesetManagementError, "approval comment"):
            _verify_exact_approval(wrong_plan, plan, 900)

    def test_exact_owner_approval_uses_the_plan_activation_issue_number(self):
        plan = make_plan(activation_issue_number=92)
        expected = (f"PASES-RULESET-APPROVE: {plan['plan_sha256']}\n"
                    f"PASES-REPOSITORY: {REPOSITORY}")
        github = FakeApprovalGitHub(approval_row(900, expected, issue_number=92))
        self.assertEqual(_verify_exact_approval(github, plan, 900)["id"], 900)
        self.assertEqual(github.issue_number, 92)

    def test_apply_rejects_non_owner_approval_before_any_ruleset_write(self):
        plan = make_plan()
        github = FakeApprovalGitHub(approval_row(
            900, f"PASES-RULESET-APPROVE: {plan['plan_sha256']}\nPASES-REPOSITORY: {REPOSITORY}",
            actor_id=1,
        ))
        github.write_calls = 0
        github.create_repository_ruleset = lambda _payload: setattr(github, "write_calls", github.write_calls + 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ruleset-plan.json"
            write_plan(path, plan)
            with self.assertRaisesRegex(RulesetManagementError, "approval comment"):
                apply_ruleset_plan(Path(tmp), github, path, 900)
        self.assertEqual(github.write_calls, 0)

    def test_policy_source_403_is_recorded_and_never_seen_as_absent(self):
        from p_ases.ruleset_management import _read_policy

        class PolicyReads:
            repo = REPOSITORY

            def branch(self, _branch):
                return {"name": "main", "protected": False, "commit": {"sha": "1" * 40}}

            def branch_protection(self, _branch):
                raise GitHubError("forbidden", status_code=403)

            def effective_branch_rules(self, _branch):
                return []

        policy, evidence = _read_policy(
            PolicyReads(), REPOSITORY, "main", "solo_owner", (("ci", 15368),), "main",
        )
        self.assertEqual(policy.status, "UNAVAILABLE")
        self.assertEqual(dict(policy.source_errors)["legacy_protection"], 403)
        self.assertEqual(evidence["source_errors"]["legacy_protection"], 403)

    def test_lost_ruleset_create_response_recovers_exactly_once(self):
        from p_ases.branch_policy import EffectiveBranchPolicy

        plan = make_plan()

        class LostCreateGitHub:
            repo = REPOSITORY

            def __init__(self):
                self.create_calls = 0
                self.detail = {
                    **copy.deepcopy(plan["desired_ruleset"]),
                    "id": 400,
                    "source": REPOSITORY,
                    "source_type": "Repository",
                }

            def create_repository_ruleset(self, payload):
                self.create_calls += 1
                self.asserted_payload = copy.deepcopy(payload)
                raise GitHubError("simulated lost POST response")

            def repository_rulesets(self):
                return [{"id": 400, "name": RULESET_NAME, "target": "branch", "enforcement": "active"}]

            def ruleset_details(self, ruleset_id, *, source_type):
                if ruleset_id != 400 or source_type != "Repository":
                    raise AssertionError("unexpected Ruleset detail read")
                return copy.deepcopy(self.detail)

        github = LostCreateGitHub()
        policy = EffectiveBranchPolicy(
            REPOSITORY, "main", ("branch", "effective-rules", "ruleset-details"), "solo_owner",
            "VERIFIED", (("ci", 15368),), True, 0, True, 0, (), (), (), "d" * 64,
        )
        evidence = {"branch": {"protected": True}}
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "ruleset-plan.json"
            write_plan(plan_path, plan)
            with patch("p_ases.ruleset_management._verify_exact_approval", return_value={"id": 900}), \
                    patch("p_ases.ruleset_management._require_current_admin",
                          return_value={"id": OWNER_ID, "login": "puchinya"}), \
                    patch("p_ases.ruleset_management.build_ruleset_plan", return_value=plan), \
                    patch("p_ases.ruleset_management._read_policy", return_value=(policy, evidence)), \
                    patch("p_ases.ruleset_management._publish_applied_record", return_value=901):
                result = apply_ruleset_plan(Path(tmp), github, plan_path, 900)
        self.assertEqual(github.create_calls, 1)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["ruleset_id"], 400)
        self.assertEqual(result["record_comment_id"], 901)

    def test_process_death_after_ruleset_create_recovers_from_durable_intent(self):
        plan = make_plan()
        post_write_plan = copy.deepcopy(plan)
        post_write_plan.update({
            "blockers": ["MANAGED_RULESET_HAS_NO_OWNERSHIP_EVIDENCE"],
            "diff": {**plan["diff"], "operation": "blocked"},
            "existing_ruleset_id": 400,
            "existing_ruleset_sha256": _body_digest(plan["desired_ruleset"]),
            "policy_evidence": {
                **plan["policy_evidence"],
                "branch": {"name": "main", "protected": True, "commit": {"sha": "1" * 40}},
            },
        })

        class ProcessDeathGitHub:
            repo = REPOSITORY

            def __init__(self):
                self.create_calls = 0
                self.created = False
                self.crash_after_create = True
                self.detail = None

            def create_repository_ruleset(self, payload):
                self.create_calls += 1
                self.created = True
                self.detail = {
                    **copy.deepcopy(payload), "id": 400,
                    "source": REPOSITORY, "source_type": "Repository",
                }
                return {"id": 400}

            def repository_rulesets(self):
                return ([{"id": 400, "name": RULESET_NAME, "target": "branch", "enforcement": "active"}]
                        if self.created else [])

            def ruleset_details(self, ruleset_id, *, source_type):
                if ruleset_id != 400 or source_type != "Repository":
                    raise AssertionError("unexpected Ruleset detail read")
                if self.crash_after_create:
                    self.crash_after_create = False
                    raise SystemExit("simulated process death after successful POST")
                return copy.deepcopy(self.detail)

        github = ProcessDeathGitHub()
        policy = EffectiveBranchPolicy(
            REPOSITORY, "main", ("branch", "effective-rules", "ruleset-details"), "solo_owner",
            "VERIFIED", (("ci", 15368),), True, 0, True, 0, (), (), (), "d" * 64,
        )
        evidence = {"branch": {"protected": True}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "ruleset-plan.json"
            write_plan(path, plan)
            shared_patches = (
                patch("p_ases.ruleset_management._verify_exact_approval", return_value={"id": 900}),
                patch("p_ases.ruleset_management._require_current_admin",
                      return_value={"id": OWNER_ID, "login": "puchinya"}),
                patch("p_ases.ruleset_management._read_policy", return_value=(policy, evidence)),
                patch("p_ases.ruleset_management._read_ownership_history", return_value=[]),
                patch("p_ases.ruleset_management._publish_applied_record", return_value=901),
            )
            with shared_patches[0], shared_patches[1], shared_patches[2], shared_patches[3], shared_patches[4], \
                    patch("p_ases.ruleset_management.build_ruleset_plan",
                          side_effect=[plan, plan, post_write_plan]):
                with self.assertRaisesRegex(SystemExit, "simulated process death"):
                    apply_ruleset_plan(root, github, path, 900)
                result = apply_ruleset_plan(root, github, path, 900)
        self.assertEqual(github.create_calls, 1)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["ruleset_id"], 400)
        self.assertEqual(result["record_comment_id"], 901)

    def test_unowned_same_name_ruleset_without_intent_cannot_be_adopted(self):
        plan = make_plan()
        blocked = copy.deepcopy(plan)
        blocked["blockers"] = ["MANAGED_RULESET_HAS_NO_OWNERSHIP_EVIDENCE"]
        blocked["diff"]["operation"] = "blocked"
        blocked["existing_ruleset_id"] = 400
        blocked["existing_ruleset_sha256"] = _body_digest(plan["desired_ruleset"])
        blocked["plan_sha256"] = hashlib.sha256(
            _canonical({key: item for key, item in blocked.items() if key != "plan_sha256"})
        ).hexdigest()

        class UnownedGitHub(FakeApprovalGitHub):
            def __init__(self, row):
                super().__init__(row)
                self.write_calls = 0

            def create_repository_ruleset(self, _payload):
                self.write_calls += 1

        expected = (f"PASES-RULESET-APPROVE: {plan['plan_sha256']}\n"
                    f"PASES-REPOSITORY: {REPOSITORY}")
        github = UnownedGitHub(approval_row(900, expected))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ruleset-plan.json"
            write_plan(path, plan)
            with patch("p_ases.ruleset_management._require_current_admin",
                       return_value={"id": OWNER_ID, "login": "puchinya"}), \
                    patch("p_ases.ruleset_management.build_ruleset_plan", return_value=blocked):
                with self.assertRaisesRegex(RulesetManagementError, "preconditions changed"):
                    apply_ruleset_plan(Path(tmp), github, path, 900)
        self.assertEqual(github.write_calls, 0)

    def test_lost_ruleset_update_response_recovers_exactly_once(self):
        from p_ases.branch_policy import EffectiveBranchPolicy

        plan = make_plan()
        before = copy.deepcopy(plan["desired_ruleset"])
        before["rules"][0]["parameters"]["required_review_thread_resolution"] = False
        plan["diff"] = {
            "operation": "update", "before": before, "before_body_sha256": _body_digest(before),
            "after": plan["desired_ruleset"], "changed_fields": ["rules"],
        }
        plan["existing_ruleset_id"] = 400
        plan["existing_ruleset_sha256"] = _body_digest(before)
        plan["plan_sha256"] = hashlib.sha256(
            _canonical({key: item for key, item in plan.items() if key != "plan_sha256"})
        ).hexdigest()

        class LostUpdateGitHub:
            repo = REPOSITORY

            def __init__(self):
                self.update_calls = 0
                self.detail = {
                    **copy.deepcopy(plan["desired_ruleset"]),
                    "id": 400,
                    "source": REPOSITORY,
                    "source_type": "Repository",
                }

            def update_repository_ruleset(self, ruleset_id, payload):
                self.update_calls += 1
                if ruleset_id != 400 or payload != plan["desired_ruleset"]:
                    raise AssertionError("unexpected Ruleset update")
                raise GitHubError("simulated lost PUT response")

            def repository_rulesets(self):
                return [{"id": 400, "name": RULESET_NAME, "target": "branch", "enforcement": "active"}]

            def ruleset_details(self, ruleset_id, *, source_type):
                if ruleset_id != 400 or source_type != "Repository":
                    raise AssertionError("unexpected Ruleset detail read")
                return copy.deepcopy(self.detail)

        github = LostUpdateGitHub()
        policy = EffectiveBranchPolicy(
            REPOSITORY, "main", ("branch", "effective-rules", "ruleset-details"), "solo_owner",
            "VERIFIED", (("ci", 15368),), True, 0, True, 0, (), (), (), "d" * 64,
        )
        evidence = {"branch": {"protected": True}}
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "ruleset-plan.json"
            write_plan(plan_path, plan)
            with patch("p_ases.ruleset_management._verify_exact_approval", return_value={"id": 900}), \
                    patch("p_ases.ruleset_management._require_current_admin",
                          return_value={"id": OWNER_ID, "login": "puchinya"}), \
                    patch("p_ases.ruleset_management.build_ruleset_plan", return_value=plan), \
                    patch("p_ases.ruleset_management._read_policy", return_value=(policy, evidence)), \
                    patch("p_ases.ruleset_management._publish_applied_record", return_value=901):
                result = apply_ruleset_plan(Path(tmp), github, plan_path, 900)
        self.assertEqual(github.update_calls, 1)
        self.assertEqual(result["operation"], "UPDATE")
        self.assertEqual(result["ruleset_id"], 400)

    def test_lost_applied_record_response_recovers_without_a_second_comment(self):
        plan = make_plan()
        actor = {"id": OWNER_ID, "login": "puchinya"}

        class LostCommentGitHub:
            repo = REPOSITORY

            def __init__(self):
                self.rows = []
                self.create_calls = 0

            def issue_comments(self, _number):
                return copy.deepcopy(self.rows)

            def issue_comment(self, _number, comment_id):
                rows = [row for row in self.rows if row["id"] == comment_id]
                if len(rows) != 1:
                    raise GitHubError("comment missing or duplicated")
                return copy.deepcopy(rows[0])

            def create_issue_comment(self, issue_number, body):
                self.create_calls += 1
                row = approval_row(950, body)
                row["issue_url"] = f"https://api.github.com/repos/{REPOSITORY}/issues/{issue_number}"
                row["user"] = {"id": OWNER_ID, "login": "puchinya", "type": "User"}
                self.rows.append(row)
                raise GitHubError("simulated lost comment response")

        github = LostCommentGitHub()
        def ownership_history(_github, _repository_id, _owner_id, _activation_issue_number):
            if not github.rows:
                return []
            body = github.rows[0]["body"]
            payload_start = body.index("\n") + 1
            payload_end = body.rindex("\n-->")
            return [(950, json.loads(body[payload_start:payload_end]))]

        with patch("p_ases.ruleset_management._read_ownership_history", side_effect=ownership_history):
            record_id = _publish_applied_record(
                github, plan, 900, 400, "c" * 64, "d" * 64, actor,
            )
        self.assertEqual(record_id, 950)
        self.assertEqual(github.create_calls, 1)
        self.assertEqual(len(github.rows), 1)

    def test_effective_policy_configuration_digest_ignores_default_branch_commit(self):
        policy = EffectiveBranchPolicy(
            REPOSITORY, "main", ("branch", "effective-rules", "ruleset-details"), "solo_owner",
            "VERIFIED", (("ci", 15368),), True, 0, True, 0, (), (), (), "d" * 64,
        )
        changed_evidence = EffectiveBranchPolicy(
            **{**policy.__dict__, "source_evidence_sha256": "e" * 64},
        )
        self.assertEqual(effective_policy_sha256(policy, 10, "f" * 64),
                         effective_policy_sha256(changed_evidence, 10, "f" * 64))
        self.assertNotEqual(effective_policy_sha256(policy, 10, "f" * 64),
                            effective_policy_sha256(policy, 11, "f" * 64))

    def test_historical_v2_evidence_uses_ownership_prefix_before_corrupt_successor(self):
        plan_sha = "a" * 64
        policy_sha = "d" * 64
        body_sha = "c" * 64
        approval_body = (f"PASES-RULESET-APPROVE: {plan_sha}\n"
                         f"PASES-REPOSITORY: {REPOSITORY}")
        payload = {
            "actor_id": OWNER_ID, "actor_login": "puchinya", "approval_comment_id": 10,
            "plan_sha256": plan_sha, "predecessor_comment_id": None,
            "effective_policy_sha256": policy_sha, "repository": REPOSITORY,
            "repository_id": 1401910271, "ruleset_body_sha256": body_sha,
            "ruleset_id": 17, "schema": "PASES_RULESET_APPLIED_V1",
        }
        record_body = APPLIED_MARKER + _canonical(payload).decode("utf-8") + "\n-->"

        def row(comment_id, body):
            return {
                "id": comment_id, "body": body,
                "created_at": "2026-10-17T00:00:00Z", "updated_at": "2026-10-17T00:00:00Z",
                "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/57",
                "html_url": f"https://github.com/{REPOSITORY}/issues/57#issuecomment-{comment_id}",
                "user": {"id": OWNER_ID, "login": "puchinya", "type": "User"},
            }

        comments = [row(10, approval_body), row(11, record_body), row(13, APPLIED_MARKER + "not-json\n-->")]

        class HistoricalGitHub:
            repo = REPOSITORY

            def repository_metadata(self):
                return {"id": 1401910271, "owner": {"id": OWNER_ID}}

            def issue_comments(self, issue_number):
                if issue_number != 57:
                    raise AssertionError("ownership history used the wrong Activation Issue")
                return copy.deepcopy(comments)

            def issue_comment(self, issue_number, comment_id):
                if issue_number != 57:
                    raise AssertionError("ownership history used the wrong Activation Issue")
                matches = [item for item in comments if item["id"] == comment_id]
                if len(matches) != 1:
                    raise GitHubError("comment missing or duplicated")
                return copy.deepcopy(matches[0])

        github = HistoricalGitHub()
        verified = verify_applied_policy_record(github, 57, 20, 11, 17, policy_sha)
        self.assertEqual(verified, payload)
        from p_ases.ruleset_management import _read_ownership_history
        with self.assertRaisesRegex(RulesetManagementError, "canonical|JSON"):
            _read_ownership_history(github, 1401910271, OWNER_ID, 57)

    def test_ownership_history_allows_a_to_b_to_a_and_rejects_duplicate_operations(self):
        from p_ases.ruleset_management import _read_ownership_history

        def read_history(operation_specs):
            comments = []
            for index, (body_digest, plan_sha, predecessor) in enumerate(operation_specs):
                approval_id = 10 + index * 2
                record_id = approval_id + 1
                approval_body = (f"PASES-RULESET-APPROVE: {plan_sha}\n"
                                 f"PASES-REPOSITORY: {REPOSITORY}")
                payload = {
                    "actor_id": OWNER_ID, "actor_login": "puchinya",
                    "approval_comment_id": approval_id, "plan_sha256": plan_sha,
                    "predecessor_comment_id": predecessor,
                    "effective_policy_sha256": "f" * 64,
                    "repository": REPOSITORY, "repository_id": 1401910271,
                    "ruleset_body_sha256": body_digest, "ruleset_id": 17,
                    "schema": "PASES_RULESET_APPLIED_V1",
                }
                record_body = APPLIED_MARKER + _canonical(payload).decode("utf-8") + "\n-->"
                for comment_id, body in ((approval_id, approval_body), (record_id, record_body)):
                    comments.append({
                        "id": comment_id, "body": body,
                        "created_at": "2026-10-17T00:00:00Z",
                        "updated_at": "2026-10-17T00:00:00Z",
                        "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/57",
                        "html_url": f"https://github.com/{REPOSITORY}/issues/57#issuecomment-{comment_id}",
                        "user": {"id": OWNER_ID, "login": "puchinya", "type": "User"},
                    })

            class OwnershipGitHub:
                repo = REPOSITORY

                def issue_comments(self, issue_number):
                    if issue_number != 57:
                        raise AssertionError("ownership history used the wrong Activation Issue")
                    return copy.deepcopy(comments)

                def issue_comment(self, issue_number, comment_id):
                    if issue_number != 57:
                        raise AssertionError("ownership history used the wrong Activation Issue")
                    matches = [item for item in comments if item["id"] == comment_id]
                    if len(matches) != 1:
                        raise GitHubError("comment missing or duplicated")
                    return copy.deepcopy(matches[0])

            return _read_ownership_history(OwnershipGitHub(), 1401910271, OWNER_ID, 57)

        body_a, body_b = "a" * 64, "b" * 64
        history = read_history([
            (body_a, "1" * 64, None),
            (body_b, "2" * 64, 11),
            (body_a, "3" * 64, 13),
        ])
        self.assertEqual([item[1]["ruleset_body_sha256"] for item in history],
                         [body_a, body_b, body_a])

        with self.assertRaisesRegex(RulesetManagementError, "evidence chain"):
            read_history([
                (body_a, "1" * 64, None),
                (body_b, "1" * 64, 11),
            ])
        with self.assertRaisesRegex(RulesetManagementError, "evidence chain"):
            read_history([
                (body_a, "1" * 64, None),
                (body_b, "2" * 64, 11),
                (body_a, "3" * 64, 11),
            ])


if __name__ == "__main__":
    unittest.main()
