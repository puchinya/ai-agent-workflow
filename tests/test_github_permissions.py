from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.github import GitHub, GitHubError, ReadOnlyGitHub  # noqa: E402


class GitHubActivationPermissionTests(unittest.TestCase):
    def test_read_only_verifier_has_a_separate_verified_get_only_route(self):
        reader = ReadOnlyGitHub("owner/repo")
        reader.verify_read_only_scope()
        identity = {"id": 42, "login": "reader", "type": "User"}
        with patch.object(GitHub, "request", return_value=identity) as request:
            self.assertEqual(reader.authenticated_user(), identity)
        request.assert_called_once_with("GET", "user")
        with self.assertRaisesRegex(GitHubError, "GET requests only"):
            reader.request("POST", "repos/owner/repo/issues/1/comments", {"body": "x"})
        with self.assertRaisesRegex(GitHubError, "GET requests only"):
            reader.replace_issue_labels(1, ["kind:single"])
        request.assert_called_once()
        with patch.object(GitHub, "_graphql", return_value={"read": True}) as graphql:
            self.assertEqual(reader._graphql("query { viewer { login } }", {}), {"read": True})
        graphql.assert_called_once_with("query { viewer { login } }", {})
        with self.assertRaisesRegex(GitHubError, "query operations only"):
            reader._graphql("mutation { createIssue(input: {}) { issue { id } } }", {})
        with self.assertRaisesRegex(GitHubError, "query operations only"):
            reader._graphql(
                "query { viewer { login } } mutation { createIssue(input: {}) { issue { id } } }", {},
            )

    def test_read_only_verifier_rejects_modified_scope_or_generic_client(self):
        reader = ReadOnlyGitHub("owner/repo")
        reader._allowed_methods = frozenset({"GET", "POST"})
        with self.assertRaisesRegex(GitHubError, "positively verified"):
            reader.verify_read_only_scope()
        reader = ReadOnlyGitHub("owner/repo")
        reader._graphql = lambda *_args: {}
        with self.assertRaisesRegex(GitHubError, "positively verified"):
            reader.verify_read_only_scope()

    def test_admin_permission_requires_matching_stable_human_identity(self):
        github = GitHub("owner/repo")
        expected = {"permission": "admin", "user": {"id": 42, "login": "repo-admin", "type": "User"}}
        with patch.object(github, "request", return_value=expected) as request:
            self.assertEqual(github.collaborator_permission("repo-admin"), expected)
        request.assert_called_once_with("GET", "repos/owner/repo/collaborators/repo-admin/permission")
        reader_permission = {"permission": "write", "user": expected["user"]}
        with patch.object(github, "request", return_value=reader_permission):
            self.assertEqual(github.collaborator_permission("repo-admin"), reader_permission)

        for response in (
            {"permission": "admin", "user": {"id": 43, "login": "other", "type": "User"}},
            {"permission": "admin", "user": {"id": 42, "login": "repo-admin", "type": "Bot"}},
            {"permission": "admin", "user": {"id": 0, "login": "repo-admin", "type": "User"}},
        ):
            with patch.object(github, "request", return_value=response):
                with self.assertRaises(GitHubError):
                    github.collaborator_permission("repo-admin")

        for login in ("", "has spaces", "octo/repo", "x\ny"):
            with self.assertRaises(GitHubError):
                github.collaborator_permission(login)

    def test_pull_request_files_uses_complete_paginated_api(self):
        github = GitHub("owner/repo")
        with patch.object(github, "_paginate", return_value=[{"filename": ".agent/project.json"}]) as paginate:
            self.assertEqual(github.pull_request_files(17), [{"filename": ".agent/project.json"}])
        paginate.assert_called_once_with("repos/owner/repo/pulls/17/files")


if __name__ == "__main__":
    unittest.main()
