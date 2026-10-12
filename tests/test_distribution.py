from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "runtime"), str(ROOT / "tools")]

import build_dist  # noqa: E402
import package_release  # noqa: E402
import validate_dist  # noqa: E402
from p_ases import __version__  # noqa: E402

SKILLS = (
    "request-intake", "adc-authoring", "adc-registry", "issue-decomposition",
    "product-specification", "technical-design", "test-specification", "work-execution",
    "verification-evidence", "acceptance-validation", "contract-audit", "independent-review",
    "user-review", "integration-validation", "delivery-control", "work-checkpoint",
)


class DistributionMigrationTests(unittest.TestCase):
    def test_canonical_and_all_three_host_skill_and_runtime_sets_are_exact(self):
        self.assertEqual(tuple(build_dist.EXPECTED_SKILLS), SKILLS)
        self.assertEqual({path.name for path in (ROOT / "workflow/skills").iterdir() if path.is_dir()}, set(SKILLS))
        expected = build_dist.expected_files()
        canonical_runtime = {path.name for path in (ROOT / "runtime/p_ases").glob("*.py")}
        for host in build_dist.HOSTS:
            with self.subTest(host=host):
                prefix = f"dist/{host}/"
                skills = {path.name for path in (ROOT / prefix / "skills").iterdir() if path.is_dir()}
                runtime = {path.removeprefix(prefix + "runtime/p_ases/")
                           for path in expected if path.startswith(prefix + "runtime/p_ases/")}
                self.assertEqual(skills, set(SKILLS))
                self.assertEqual(runtime, canonical_runtime)
                self.assertFalse(any(path.startswith(prefix + "runtime/agent_workflow/") for path in expected))
                self.assertIn(prefix + "runtime/p_ases/cli.py", expected)
        self.assertEqual(build_dist.check(expected), [])
        self.assertEqual(validate_dist.validate(), [])

    def test_generated_manifests_are_versioned_and_host_specific(self):
        files = build_dist.expected_files()
        self.assertEqual(__version__, "0.8.0")
        openai = json.loads(files["dist/openai/plugin.json"])
        claude = json.loads(files["dist/claude/.claude-plugin/plugin.json"])
        antigravity = json.loads(files["dist/antigravity/plugin.json"])
        self.assertEqual((openai["name"], claude["name"], antigravity["name"]), ("p-ases",) * 3)
        self.assertEqual((openai["version"], claude["version"]), (__version__, __version__))
        self.assertNotIn("version", antigravity)
        self.assertEqual(json.loads(files[".agents/plugins/marketplace.json"])["plugins"][0]["source"],
                         {"source": "local", "path": "./dist/openai"})
        self.assertEqual(json.loads(files[".claude-plugin/marketplace.json"])["plugins"][0]["source"],
                         "./dist/claude")
        self.assertEqual(openai, json.loads(files["dist/openai/plugin.json"]))
        self.assertNotEqual(openai, antigravity)
        self.assertEqual(json.loads(files["dist/antigravity/plugin.json"])["name"], "p-ases")

    def test_check_detects_edited_missing_and_extra_files_without_repair(self):
        target = ROOT / "dist/openai/README.md"
        original = target.read_bytes()
        extra = ROOT / "dist/openai/extra-unexpected.txt"
        try:
            edited = original + b"edited\n"
            target.write_bytes(edited)
            self.assertTrue(any("generated file drift" in item for item in build_dist.check(build_dist.expected_files())))
            self.assertEqual(target.read_bytes(), edited)
            target.write_bytes(original)

            target.unlink()
            self.assertTrue(any("missing generated file" in item for item in build_dist.check(build_dist.expected_files())))
            self.assertFalse(target.exists())
            target.write_bytes(original)

            extra.write_text("unexpected", encoding="utf-8")
            self.assertTrue(any("extra generated file" in item for item in build_dist.check(build_dist.expected_files())))
            self.assertTrue(extra.exists())
        finally:
            target.write_bytes(original)
            extra.unlink(missing_ok=True)

    def test_validator_rejects_retired_runtime_and_extra_skill_directory(self):
        extra_skill = ROOT / "dist/openai/skills/legacy-skill"
        old_runtime = ROOT / "dist/openai/runtime/agent_workflow"
        try:
            extra_skill.mkdir(parents=True)
            (extra_skill / "SKILL.md").write_text("legacy", encoding="utf-8")
            old_runtime.mkdir(parents=True)
            (old_runtime / "__init__.py").write_text("", encoding="utf-8")
            errors = validate_dist.validate()
            self.assertTrue(any("directory set must exactly match" in item for item in errors), errors)
            self.assertTrue(any("retired runtime package is forbidden" in item for item in errors), errors)
        finally:
            import shutil
            shutil.rmtree(extra_skill, ignore_errors=True)
            shutil.rmtree(old_runtime, ignore_errors=True)

    def test_marketplace_source_resolution_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            try:
                (root / "linked-package").symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")
            with patch.object(validate_dist, "ROOT", root):
                resolved, reason = validate_dist._repository_source_target("./linked-package")
            self.assertIsNone(resolved)
            self.assertIn("outside", reason)

    def test_package_markdown_validation_rejects_broken_links_and_symlinked_files(self):
        from p_ases.documents import validate_markdown_file
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "package"
            root.mkdir()
            document = root / "SKILL.md"
            document.write_text("# Skill\n\n[missing](missing.md)\n", encoding="utf-8")
            self.assertTrue(any("broken local link" in item for item in
                                validate_markdown_file(document, root)))
            outside = Path(tmp) / "outside.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            linked = root / "linked.md"
            try:
                linked.symlink_to(outside)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")
            self.assertTrue(any("symlinked Markdown path" in item for item in
                                validate_markdown_file(linked, root)))

    def test_release_names_zip_contents_checksums_and_bytes_are_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "first", Path(tmp) / "second"
            assets_a = package_release.package("v0.8.0", first)
            assets_b = package_release.package("v0.8.0", second)
            names = [path.name for path in assets_a]
            self.assertEqual(names, [
                "p-ases-openai-v0.8.0.zip", "p-ases-claude-v0.8.0.zip",
                "p-ases-antigravity-v0.8.0.zip", "SHA256SUMS",
            ])
            self.assertEqual([path.name for path in assets_b], names)
            for path_a, path_b in zip(assets_a, assets_b):
                self.assertEqual(path_a.read_bytes(), path_b.read_bytes())
            for path in assets_a[:3]:
                with ZipFile(path) as archive:
                    members = archive.namelist()
                    self.assertEqual(members, sorted(members))
                    self.assertIn("runtime/p_ases/cli.py", members)
                    self.assertFalse(any(name.startswith("runtime/agent_workflow/") for name in members))
                    self.assertEqual(len([name for name in members if name.startswith("skills/")
                                          and name.endswith("/SKILL.md")]), 16)
            expected_checksums = "".join(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                for path in sorted(assets_a[:3], key=lambda item: item.name)
            )
            self.assertEqual(assets_a[3].read_text(encoding="utf-8"), expected_checksums)

    def test_release_rejects_bad_tag_and_drift_without_creating_assets_or_repairing(self):
        for tag in ("0.8.0", "v00.8.0", "v0.8.0-rc.1", "v0.8.0\n", "v9.9.9"):
            with self.subTest(tag=tag), self.assertRaises(package_release.PackageError):
                package_release.validate_tag(tag)
        target = ROOT / "dist/openai/README.md"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b" ")
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "assets"
                with patch.object(build_dist, "build", side_effect=AssertionError("release must not repair")):
                    with self.assertRaises(package_release.PackageError):
                        package_release.package("v0.8.0", output)
                self.assertFalse(output.exists())
                self.assertEqual(target.read_bytes(), original + b" ")
        finally:
            target.write_bytes(original)

    def test_setuptools_package_discovery_excludes_the_retired_import_surface(self):
        from setuptools import find_packages
        packages = find_packages(where=str(ROOT / "runtime"), include=["p_ases*"])
        self.assertEqual(packages, ["p_ases"])
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('name = "p-ases"', pyproject)
        self.assertIn('version = {attr = "p_ases.__version__"}', pyproject)
        self.assertFalse((ROOT / "runtime/agent_workflow").exists())


if __name__ == "__main__":
    unittest.main()
