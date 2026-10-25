from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from p_ases.profile import ProfileError, load_profile


class ProfileUnavailableHandlingTests(unittest.TestCase):
    def profile_copy(self, temporary: str, review: dict) -> Path:
        root = Path(temporary)
        shutil.copytree(ROOT / ".agent", root / ".agent")
        path = root / ".agent" / "project.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["independent_review"] = review
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        return root

    def test_omission_defaults_to_block_and_owner_exception_requires_explicit_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            default_root = self.profile_copy(temporary, {"minimum_assurance": "independent_attested"})
            profile = load_profile(default_root)
            self.assertEqual(profile.independent_review_unavailable_handling, "block")
            self.assertEqual(len(profile.profile_sha256), 64)
        with tempfile.TemporaryDirectory() as temporary:
            opted_root = self.profile_copy(
                temporary, {"minimum_assurance": "independent_attested", "unavailable_handling": "owner_exception"})
            profile = load_profile(opted_root)
            self.assertEqual(profile.independent_review_minimum_assurance, "independent_attested")
            self.assertEqual(profile.independent_review_unavailable_handling, "owner_exception")

    def test_unknown_policy_values_or_fields_are_rejected(self):
        for review in (
            {"minimum_assurance": "independent_attested", "unavailable_handling": "allow"},
            {"minimum_assurance": "independent_attested", "unavailable_handling": "owner_exception", "force": True},
        ):
            with self.subTest(review=review), tempfile.TemporaryDirectory() as temporary:
                root = self.profile_copy(temporary, review)
                with self.assertRaises(ProfileError):
                    load_profile(root)


if __name__ == "__main__":
    unittest.main()
