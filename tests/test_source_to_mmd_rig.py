"""Optional real-Blender regression tests for Source → MMD rig conversion.

Run with bundled add-ons enabled and SOURCE_MMD_TEST_QC pointing to a fixture
QC, SOURCE_MMD_TEST_MESHES containing semicolon-separated reference stems:
    blender --background --python-exit-code 1 --python tests/test_source_to_mmd_rig.py
Normal Python test discovery skips these tests without Blender/the fixture.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

try:
    import bpy
    from mathutils import Quaternion, Vector
except ImportError:
    bpy = None


@unittest.skipUnless(bpy is not None and os.environ.get("SOURCE_MMD_TEST_QC"),
                     "Requires Blender, enabled Source Tools/mmd_tools and SOURCE_MMD_TEST_QC")
class SourceRigIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qc = Path(os.environ["SOURCE_MMD_TEST_QC"]).resolve()
        cls.mesh_names = os.environ.get("SOURCE_MMD_TEST_MESHES", cls.qc.stem + "_reference").split(";")
        source = Path(__file__).resolve().parents[1] / "tools/source_to_mmd/blender_retarget.py"
        spec = importlib.util.spec_from_file_location("reverse_rig_under_test", source)
        cls.rig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.rig)
        cls.temp = tempfile.TemporaryDirectory(prefix="source_mmd_rig_test_")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name)
        cls.checkpoint = cls.output / "retarget.blend"
        cls.rig.run(cls.qc, cls.checkpoint, cls.mesh_names)
        cls.report = json.loads(cls.checkpoint.with_suffix(".rig.json").read_text(encoding="utf-8"))

    def setUp(self):
        bpy.ops.wm.open_mainfile(filepath=str(self.checkpoint))
        self.armature = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE")

    def positions(self):
        bpy.context.view_layer.update()
        armature = self.armature.evaluated_get(bpy.context.evaluated_depsgraph_get())
        return {bone.name: bone.head.copy() for bone in armature.pose.bones}

    def test_mesh_and_bone_coordinates_share_metric_space(self):
        self.assertEqual({obj.name for obj in bpy.data.objects if obj.type == "MESH"}, set(self.mesh_names),
                         "Only the selected character meshes belong in the checkpoint")
        for obj in [self.armature] + [obj for obj in bpy.data.objects if obj.type == "MESH"]:
            self.assertLess((obj.matrix_world.translation).length, 1e-6)
            self.assertTrue(all(abs(component - 1) < 1e-6 for component in obj.matrix_world.to_scale()))
        for mesh in self.report["meshes"]:
            self.assertEqual(mesh["unweighted_vertices"], 0)
            self.assertEqual(mesh["nonunit_weight_sums"], 0)
            self.assertLess(mesh["rest_pose_max_drift_m"], 0.002)
        self.assertEqual(len(self.report["twist_weights"]), 4)
        for stats in self.report["twist_weights"].values():
            self.assertGreater(stats["weighted_vertices"], 0)

    def test_center_descent_keeps_ankles_planted(self):
        before = self.positions()
        center = self.armature.pose.bones["センター"]
        center.location = center.bone.matrix_local.to_3x3().inverted() @ Vector((0, 0, -0.12))
        after = self.positions()
        for side in ("左", "右"):
            self.assertEqual(self.armature.data.bones[side + "足ＩＫ"].parent.name, "全ての親")
            self.assertLess((after[side + "足首"] - before[side + "足首"]).length, 0.001)
            self.assertLess(after[side + "ひざ"].y, before[side + "ひざ"].y)

    def test_neutral_arms_do_not_retain_source_downward_pose(self):
        for side, sign in (("左", 1), ("右", -1)):
            joints = self.positions()
            for parent, child, degrees in (("腕", "ひじ", 42), ("ひじ", "手首", 40)):
                segment = (joints[side+child]-joints[side+parent]).normalized()
                self.assertGreater(segment.x*sign, .6)
                self.assertAlmostEqual(segment.y, 0, places=4)
                self.assertAlmostEqual(math.degrees(math.atan2(-segment.z, abs(segment.x))), degrees, places=3)

    def test_fingers_start_extended_for_shared_mmd_poses(self):
        joints = self.positions()
        for side in ("左", "右"):
            for finger in ("人指", "中指", "薬指", "小指"):
                names = [side+finger+digit for digit in "１２３"]
                if not all(name in joints for name in names):
                    continue
                first, second = (joints[names[1]]-joints[names[0]]), (joints[names[2]]-joints[names[1]])
                self.assertLess(math.degrees(first.angle(second)), .1,
                                "Pre-curled Source fingers cause shared MMD poses to overbend")

    def test_torso_controls_share_original_source_waist(self):
        self.assertTrue(self.report['torso_pivots']['applied'])
        joints = self.positions()
        waist = Vector(self.report['torso_pivots']['common_waist_m'])
        self.assertLess((joints['上半身'] - waist).length, 1e-6)
        self.assertLess((joints['下半身'] - waist).length, 1e-6)
        self.assertGreater((joints['センター'] - waist).length, .01)

    def test_neutral_feet_face_forward_without_sideways_yaw(self):
        joints = self.positions()
        for side in ('左', '右'):
            foot = joints[side+'つま先'] - joints[side+'足首']
            self.assertLess(foot.y, -.025)
            self.assertLess(abs(math.degrees(math.atan2(foot.x, -foot.y))), .1)

    def test_twist_segments_keep_total_skin_weights(self):
        self.assertEqual(len(self.report['twist_segments']), 12)
        for row in self.report['twist_segments']:
            meta = self.armature.pose.bones[row['helper']].mmd_bone
            self.assertTrue(meta.has_additional_rotation)
            self.assertEqual(meta.additional_transform_bone, row['source'])
            self.assertIn(meta.additional_transform_influence, (.25, .5, .75))
        for mesh in self.report['meshes']:
            self.assertEqual(mesh['nonunit_weight_sums'], 0)

    def test_neutral_pose_bake_matches_evaluated_skin(self):
        self.assertTrue(self.report["neutral_pose"]["applied"])
        for result in self.report["neutral_pose"]["meshes"]:
            self.assertLess(result["max_skin_bake_error_m"], .00001)
            mesh = bpy.data.objects[result["name"]]
            if mesh.data.shape_keys:
                self.assertEqual(len(mesh.data.shape_keys.key_blocks)-1, result["shape_keys"])
                self.assertFalse(mesh.show_only_shape_key)
                self.assertTrue(all(key.value == 0 for key in mesh.data.shape_keys.key_blocks))

    def test_positive_knee_hinge_bends_backward_and_up(self):
        for bone in self.armature.pose.bones:
            for constraint in bone.constraints:
                if constraint.type == "IK":
                    constraint.mute = True
        for side in ("左", "右"):
            before = self.positions()[side + "足首"]
            knee = self.armature.pose.bones[side + "ひざ"]
            knee.rotation_quaternion = Quaternion((1, 0, 0), math.radians(45))
            after = self.positions()[side + "足首"]
            self.assertGreater(after.y, before.y + 0.05)
            self.assertGreater(after.z, before.z + 0.05)

    def test_pmx_roundtrip_preserves_ik_targets_limits_and_twist_weights(self):
        from mmd_tools_local.core import pmx
        bpy.context.view_layer.objects.active = self.armature
        bpy.ops.mmd_tools_local.convert_to_mmd_model(scale=1.0, convert_material_nodes=True)
        pmx_path = self.output / "rig.pmx"
        bpy.ops.mmd_tools_local.export_pmx(filepath=str(pmx_path))
        model = pmx.load(str(pmx_path))
        bones = {bone.name: bone for bone in model.bones}
        for row in self.report['twist_segments'] + self.report['knee_correctives'] + self.report['elbow_correctives']:
            helper = bones[row['helper']]
            self.assertTrue(helper.hasAdditionalRotate)
            self.assertEqual(model.bones[helper.additionalTransform[0]].name, row['source'])
            self.assertAlmostEqual(helper.additionalTransform[1], row['coefficient'])
        for side in ("左", "右"):
            leg = bones[side + "足ＩＫ"]
            self.assertEqual(model.bones[leg.parent].name, "全ての親")
            self.assertEqual(model.bones[leg.target].name, side + "足首")
            self.assertEqual([model.bones[link.target].name for link in leg.ik_links],
                             [side + "ひざ", side + "足"])
            self.assertAlmostEqual(leg.ik_links[0].minimumAngle[0], math.radians(-179.5), places=4)
            self.assertEqual(tuple(leg.ik_links[0].maximumAngle), (0.0, 0.0, 0.0))
            self.assertEqual(leg.loopCount, 48)
            toe = bones[side + "つま先ＩＫ"]
            self.assertEqual(model.bones[toe.target].name, side + "つま先")
            self.assertEqual(model.bones[toe.ik_links[0].target].name, side + "足首")
            self.assertIsNone(toe.ik_links[0].minimumAngle)
            for thumb in ("０", "１", "２"):
                self.assertIn(side + "親指" + thumb, bones)
        # PMX must retain the inserted twist groups too, rather than merely
        # preserving Blender's otherwise-unused bones.
        weighted_indices = set()
        for vertex in model.vertices:
            weighted_indices.update(vertex.weight.bones)
        for name in self.report["twist_weights"]:
            self.assertIn(model.bones.index(bones[name]), weighted_indices)

    def test_multiple_selected_meshes_survive(self):
        reference = self.qc.parent / (self.mesh_names[0] + ".smd")
        if not reference.is_file():
            self.skipTest("Fixture uses a subdirectory or non-SMD reference")
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        fixture = self.output / "multiple"
        fixture.mkdir(exist_ok=True)
        for name in ("body", "part"):
            shutil.copyfile(reference, fixture / (name + ".smd"))
        qc = fixture / "multiple.qc"
        qc.write_text('$modelname "multiple.mdl"\n$body body "body.smd"\n$body part "part.smd"\n', encoding="utf-8")
        result = fixture / "multiple.blend"
        self.rig.run(qc, result, ["body", "part"])
        report = json.loads(result.with_suffix(".rig.json").read_text(encoding="utf-8"))
        self.assertEqual({mesh["name"] for mesh in report["meshes"]}, {"body", "part"})

    def test_missing_selected_mesh_fails(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        with self.assertRaisesRegex(RuntimeError, "Selected reference mesh.*not imported"):
            self.rig.import_reference_qc(self.qc, ["definitely_absent_mesh"])


if __name__ == "__main__":
    result = unittest.main(argv=[__file__], exit=False)
    if not result.result.wasSuccessful():
        raise RuntimeError("Source rig integration tests failed")
