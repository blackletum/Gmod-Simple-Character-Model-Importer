"""Pure regression checks for qualified Source procedural-weight conversion."""
import importlib.util
from pathlib import Path
import sys
import unittest

path = Path(__file__).resolve().parents[1] / "tools/source_to_mmd/source_helpers.py"
spec = importlib.util.spec_from_file_location("source_helper_under_test", path)
helpers = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helpers
spec.loader.exec_module(helpers)


class HelperWeightTests(unittest.TestCase):
    def parents(self, kind="Elbow"):
        return {"ValveBiped.Bip01_L_UpperArm": None,
                "ValveBiped.Bip01_L_Forearm": "ValveBiped.Bip01_L_UpperArm",
                "ValveBiped.Bip01_L_Hand": "ValveBiped.Bip01_L_Forearm",
                "ValveBiped.Bip01_L_" + kind: "ValveBiped.Bip01_L_UpperArm" if kind == "Elbow" else "ValveBiped.Bip01_L_Forearm"}

    def hinge(self, response=45):
        return f"""<helper> Bip01_L_Elbow Bip01_L_UpperArm Bip01_L_UpperArm Bip01_L_Forearm
<trigger> 90 0 0 0 0 0 0 11 0 0
<trigger> 90 0 0 -90 0 0 -{response} 11 0 0
"""

    def test_real_half_hinge_preserves_total_and_existing_influences(self):
        rules, preserved = helpers.plan_helper_transfers(self.hinge(), self.parents())
        self.assertFalse(preserved)
        vertex = {"ValveBiped.Bip01_L_Elbow": .6, "ValveBiped.Bip01_L_UpperArm": .1,
                  "ValveBiped.Bip01_L_Forearm": .2, "Jacket_custom": .1}
        result = helpers.transfer_vertex_weights(vertex, rules)
        self.assertAlmostEqual(sum(result.values()), 1)
        self.assertAlmostEqual(result["ValveBiped.Bip01_L_UpperArm"], .4)
        self.assertAlmostEqual(result["ValveBiped.Bip01_L_Forearm"], .5)
        self.assertAlmostEqual(result["Jacket_custom"], .1)
        self.assertNotIn("ValveBiped.Bip01_L_Elbow", result)

    def test_custom_hinge_curve_is_preserved(self):
        rules, preserved = helpers.plan_helper_transfers(self.hinge(70), self.parents())
        self.assertFalse(rules)
        self.assertEqual(len(preserved), 1)

    def test_name_alone_cannot_trigger_transfer(self):
        parents = self.parents()
        parents["ValveBiped.Bip01_L_Elbow"] = "ValveBiped.Bip01_L_Hand"
        rules, _ = helpers.plan_helper_transfers(self.hinge(), parents)
        self.assertFalse(rules)
        wrong_driver = self.hinge().replace("<helper> Bip01_L_Elbow Bip01_L_UpperArm Bip01_L_UpperArm Bip01_L_Forearm",
            "<helper> Bip01_L_Elbow Bip01_L_UpperArm Bip01_L_UpperArm Bip01_L_Hand")
        rules, _ = helpers.plan_helper_transfers(wrong_driver, self.parents())
        self.assertFalse(rules)

    def test_unknown_custom_and_duplicate_helpers_are_preserved(self):
        unknown = self.hinge().replace("Bip01_L_Elbow", "Bip01_L_CustomMuscle")
        parents = self.parents()
        parents["ValveBiped.Bip01_L_CustomMuscle"] = "ValveBiped.Bip01_L_UpperArm"
        rules, _ = helpers.plan_helper_transfers(unknown, parents)
        self.assertFalse(rules)
        rules, _ = helpers.plan_helper_transfers(self.hinge() + self.hinge(), self.parents())
        self.assertFalse(rules)

    def test_wrist_weights_reach_forearm_for_geometric_twist_split(self):
        text = """<helper> Bip01_L_Wrist Bip01_L_Forearm Bip01_L_Forearm Bip01_L_Hand
<trigger> 90 90 0 0 0 0 0 11 0 0
<trigger> 90 0 0 0 -90 0 0 11 0 0
"""
        rules, _ = helpers.plan_helper_transfers(text, self.parents("Wrist"))
        result = helpers.transfer_vertex_weights({"ValveBiped.Bip01_L_Wrist": .7,
            "ValveBiped.Bip01_L_Forearm": .3}, rules)
        self.assertEqual(result, {"ValveBiped.Bip01_L_Forearm": 1.})

    def test_invalid_numeric_curve_is_preserved(self):
        for text in (self.hinge().replace("-45", "nan"), self.hinge().replace("-45", "broken")):
            rules, _ = helpers.plan_helper_transfers(text, self.parents())
            self.assertFalse(rules)


if __name__ == "__main__":
    unittest.main()
