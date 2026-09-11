"""Guard motion-facing names and custom recipe validation without Blender."""
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "source_to_mmd" / "morph_recipes.py"
SPEC = importlib.util.spec_from_file_location("source_to_mmd_morph_recipes_tested", MODULE_PATH)
recipes_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recipes_module)
bilateral = recipes_module.bilateral
default_recipes = recipes_module.default_recipes
parse_overrides = recipes_module.parse_overrides


class SourceMorphRecipesTests(unittest.TestCase):
    def test_winks_keep_character_left_and_right_separate(self):
        source_names = {"upper_right", "upper_left", "AU42"}
        original = source_names.copy()
        recipes = default_recipes(source_names)
        self.assertEqual(recipes["ウィンク"]["weights"], {"upper_left": 1})
        self.assertEqual(recipes["ウィンク右"]["weights"], {"upper_right": 1})
        self.assertEqual(recipes["まばたき"]["weights"], {"upper_right": 1, "upper_left": 1})
        self.assertEqual(source_names, original, "Planning aliases must preserve source names")

    def test_half_closed_or_one_lid_does_not_become_bilateral_blink(self):
        self.assertNotIn("まばたき", default_recipes({"AU42", "upper_left"}))
        self.assertEqual(default_recipes({"Blink"})["まばたき"]["weights"], {"Blink": 1})

    def test_vowel_requires_all_components_on_both_sides(self):
        incomplete = {"AU26R", "AU26L", "AU25R"}
        self.assertNotIn("あ", default_recipes(incomplete))
        complete = default_recipes(incomplete | {"AU25L"})["あ"]
        self.assertEqual(set(complete["weights"]), {"AU26R", "AU26L", "AU25R", "AU25L"})
        self.assertEqual(complete["weights"]["AU26R"], complete["weights"]["AU26L"])
        self.assertEqual(complete["weights"]["AU25R"], complete["weights"]["AU25L"])
        self.assertEqual(complete["category"], "mouth")
        self.assertTrue(complete["approximation"])

    def test_combined_flex_is_not_double_counted_with_separate_flexes(self):
        names = {"AU26R+AU26L", "AU26R", "AU26L", "AU26R+AU26L.001"}
        self.assertEqual(bilateral(names, "AU26"), {"AU26R+AU26L": 1.0})
        self.assertIsNone(bilateral({"AU26R+AU26L.001"}, "AU26"))

    def test_override_changes_recipe_and_null_disables_default(self):
        source = {"upper_left", "upper_right", "AU26", "AU25"}
        recipes = default_recipes(source)
        overrides = parse_overrides({"morphs": {
            "あ": {"weights": {"AU26": .4}, "category": "mouth"},
            "まばたき": None,
            "custom": "upper_left",
        }})
        recipes.update(overrides)
        self.assertEqual(recipes["あ"]["weights"], {"AU26": .4})
        self.assertIsNone(recipes["まばたき"])
        self.assertEqual(recipes["custom"]["weights"], {"upper_left": 1.0})
        self.assertEqual(recipes["ウィンク右"]["weights"], {"upper_right": 1})

    def test_legacy_mapping_and_flat_weight_forms(self):
        result = parse_overrides({"_comment": "ignored", "mapping": {"custom": {"flex": -0.25}}})
        self.assertEqual(result["custom"]["weights"], {"flex": -0.25})
        self.assertEqual(result["custom"]["category"], "other")

    def test_invalid_custom_values_fail_before_geometry_changes(self):
        invalid = [None, [], {"morphs": []}, {"": "flex"}, {"bad": {}},
                   {"bad": {"weights": {"": 1}}},
                   {"bad": {"weights": {"flex": 1}, "category": "lip"}}]
        invalid.extend({"bad": {"weights": {"flex": value}}}
                       for value in (float("nan"), float("inf"), -4.01, 4.01, "1", True))
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_overrides(value)


if __name__ == "__main__":
    unittest.main()
