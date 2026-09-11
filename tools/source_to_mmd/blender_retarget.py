"""Import selected Source reference meshes and build an MMD-compatible rig.

Run in Blender after blender_setup_addons.py. Source Tools' QC import retains
VTA flexes; explicit --keep-mesh arguments select visible bodygroup meshes and
exclude LOD/collision geometry. All geometric edits use a shared metric space.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "reference"))
from common import eprint
import bone_mapping as bm

SOURCE_UNITS_TO_METERS = 0.0254


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qc", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True)
    parser.add_argument("--keep-mesh", action="append", required=True,
                        help="Imported reference mesh name; repeat for selected bodygroup parts.")
    parser.add_argument("--report-json", type=Path)
    return parser.parse_args(argv)


def import_reference_qc(qc_path: Path, keep_mesh: list[str]) -> tuple[bpy.types.Object, list[bpy.types.Object], list[str]]:
    if not keep_mesh:
        raise ValueError("Select at least one reference mesh with --keep-mesh; importing all LODs is unsafe.")
    existing = set(bpy.data.objects)
    result = bpy.ops.import_scene.smd(filepath=str(qc_path), doAnim=False,
        createCollections=True, makeCamera=False, append="NEW_ARMATURE",
        upAxis="Z", rotMode="XYZ", boneMode="SPHERE")
    if "FINISHED" not in result:
        raise RuntimeError(f"Source Tools import failed: {result}")
    imported = set(bpy.data.objects) - existing
    all_meshes = [obj for obj in imported if obj.type == "MESH"]
    names = set(keep_mesh)
    missing = names - {obj.name for obj in all_meshes}
    if missing:
        raise RuntimeError(f"Selected reference mesh(es) not imported: {sorted(missing)}. "
                           f"Available mesh names: {sorted(obj.name for obj in all_meshes)}")
    meshes = sorted((obj for obj in all_meshes if obj.name in names), key=lambda obj: obj.name)
    armatures = {obj.find_armature() for obj in meshes}
    if None in armatures or len(armatures) != 1:
        raise RuntimeError("Selected meshes must share one Source armature; check QC bodygroup selection.")
    armature = armatures.pop()
    removed = sorted(obj.name for obj in all_meshes if obj not in meshes)
    for obj in all_meshes:
        if obj not in meshes:
            bpy.data.objects.remove(obj, do_unlink=True)
    # Source animations are disabled at import. Clear any importer-created
    # rest action so it cannot overwrite the edited bone names/pose later.
    armature.animation_data_clear()
    for pose in armature.pose.bones:
        pose.matrix_basis.identity()
    bpy.context.view_layer.update()
    return armature, meshes, removed


def normalize_geometry(armature, meshes) -> dict:
    """Bake mesh (including every shape key) and bones into the same space.

    Scaling only the armature leaves mesh vertex.co in Source inches while
    bone.head is in meters. That was the cause of empty twist vertex groups.
    Capture every world matrix before changing parents, then bake explicitly.
    """
    old_armature_matrix = armature.matrix_world.copy()
    old_mesh_matrices = {obj: obj.matrix_world.copy() for obj in meshes}
    left = armature.data.bones.get("ValveBiped.Bip01_L_Thigh")
    right = armature.data.bones.get("ValveBiped.Bip01_R_Thigh")
    if left is None or right is None:
        raise RuntimeError("Expected ValveBiped thigh bones are missing; this conversion requires a humanoid ValveBiped rig.")
    left_axis = old_armature_matrix.to_3x3() @ (left.head_local - right.head_local)
    left_axis.z = 0.0
    if left_axis.length < 1e-6:
        raise RuntimeError("Cannot determine facing: left and right hip joints overlap.")
    left_axis.normalize()
    up_axis = Vector((0, 0, 1))
    back_axis = up_axis.cross(left_axis).normalized()
    rotation = Matrix((left_axis, back_axis, up_axis)).to_4x4()
    transform = Matrix.Scale(SOURCE_UNITS_TO_METERS, 4) @ rotation
    armature.data.transform(transform @ old_armature_matrix)
    armature.parent = None
    armature.matrix_world = Matrix.Identity(4)
    for obj in meshes:
        obj.data.transform(transform @ old_mesh_matrices[obj], shape_keys=True)
        obj.parent = armature
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = Matrix.Identity(4)
        obj.data.update()
    bpy.context.view_layer.update()
    return {"source_units_to_meters": SOURCE_UNITS_TO_METERS,
            "coordinate_system": "X character left, Y backward, Z up",
            "source_to_metric_matrix": [list(row) for row in transform]}


def merge_vertex_group(mesh, source_name, target_name):
    source = mesh.vertex_groups.get(source_name)
    if source is None:
        return
    target = mesh.vertex_groups.get(target_name) or mesh.vertex_groups.new(name=target_name)
    source_index = source.index
    for vertex in mesh.data.vertices:
        weight = next((item.weight for item in vertex.groups if item.group == source_index), 0)
        if weight > 0:
            target.add([vertex.index], weight, "ADD")
    mesh.vertex_groups.remove(source)


def collapse_spine(armature, meshes):
    """Keep the established two upper-body controls; preserve all children."""
    bones = armature.data.edit_bones
    for source_name, target_name in (("ValveBiped.Bip01_Spine", "ValveBiped.Bip01_Spine1"),
                                     ("ValveBiped.Bip01_Spine4", "ValveBiped.Bip01_Spine2")):
        source, target = bones.get(source_name), bones.get(target_name)
        if source is None or target is None:
            continue
        if target.parent == source:
            target.parent = source.parent
        for child in list(source.children):
            child.parent = target
        for mesh in meshes:
            merge_vertex_group(mesh, source_name, target_name)
        bones.remove(source)


def synthesize_root_chain(armature):
    bones = armature.data.edit_bones
    pelvis = bones.get("ValveBiped.Bip01_Pelvis")
    if pelvis is None:
        raise RuntimeError("Missing ValveBiped.Bip01_Pelvis.")
    head = pelvis.head.copy()
    parent = None
    for index, spec in enumerate(bm.ROOT_CHAIN_SPEC["chain"]):
        bone = bones.new(spec["jp"])
        bone.head = Vector((head.x, head.y, 0)) if index == 0 else head
        bone.tail = bone.head + Vector((0, 0, 0.05))
        bone.parent = parent
        bone.use_deform = False
        parent = bone
    pelvis.parent = parent
    upper_body = bones.get("ValveBiped.Bip01_Spine1") or bones.get("ValveBiped.Bip01_Spine")
    if upper_body:
        upper_body.parent = parent


def rename_bones(armature, meshes):
    bones = armature.data.edit_bones
    unmapped = []
    for old_name in [bone.name for bone in bones]:
        resolved = bm.valvebiped_to_mmd(old_name)
        if resolved is None:
            if old_name.startswith("ValveBiped."):
                unmapped.append(old_name)
            continue
        new_name, _ = resolved
        if new_name in bones:
            # Duplicate Source aliases must not accidentally share weights.
            unmapped.append(old_name)
            continue
        bones[old_name].name = new_name
        for mesh in meshes:
            group = mesh.vertex_groups.get(old_name)
            if group:
                group.name = new_name
    # A custom jacket/hair bone follows its mapped parent even without a VMD
    # track. Preserve that articulation and the original skin weights.
    for bone in bones:
        if bone.parent is None and bone.name != "全ての親":
            bone.parent = bones["全ての親"]
    return unmapped


def align_anatomical_tails(armature):
    """Source Tools imports display stubs; IK must terminate at real joints."""
    bones = armature.data.edit_bones
    connections = [("上半身", "上半身2"), ("上半身2", "首"), ("首", "頭")]
    for side in ("左", "右"):
        connections += [(side + parent, side + child) for parent, child in
            (("肩", "腕"), ("腕", "ひじ"), ("ひじ", "手首"),
             ("足", "ひざ"), ("ひざ", "足首"), ("足首", "つま先"))]
        for finger in ("親指", "人指", "中指", "薬指", "小指"):
            digits = "０１２" if finger == "親指" else "１２３"
            connections += [(side + finger + a, side + finger + b) for a, b in zip(digits, digits[1:])]
    touched = []
    for name, child_name in connections:
        bone, child = bones.get(name), bones.get(child_name)
        if bone and child and (child.head - bone.head).length > 1e-5:
            bone.tail = child.head.copy()
            touched.append(name)
    # Give each knee a local X hinge parallel to the character's left axis.
    # Its local Y points knee→ankle; this roll gives a backward bend for +X.
    for side in bm.LEG_IK_SPEC["sides"]:
        knee = bones.get(side["knee_jp"])
        if knee:
            desired_x = Vector((1, 0, 0))
            knee.align_roll(desired_x.cross(knee.vector.normalized()))
    return touched


def insert_twist_bones(armature, meshes):
    bones = armature.data.edit_bones
    inserted = []
    for side in ("左", "右"):
        for parent_suffix, child_suffix, twist_suffix in (("腕", "ひじ", "腕捩"), ("ひじ", "手首", "手捩")):
            parent, child = bones.get(side + parent_suffix), bones.get(side + child_suffix)
            name = side + twist_suffix
            if not parent or not child or name in bones:
                continue
            segment = child.head - parent.head
            if segment.length_squared < 1e-10:
                continue
            twist = bones.new(name)
            twist.head = parent.head.lerp(child.head, 0.5)
            twist.tail = child.head.copy()
            twist.parent = parent
            child.parent = twist
            for mesh in meshes:
                group = mesh.vertex_groups.get(parent.name)
                if group is None:
                    continue
                twist_group = mesh.vertex_groups.new(name=name)
                index = group.index
                # Both positions now use armature meters. Matrix conversion
                # also keeps this safe if a caller later retains transforms.
                mesh_to_armature = armature.matrix_world.inverted() @ mesh.matrix_world
                for vertex in mesh.data.vertices:
                    weight = next((item.weight for item in vertex.groups if item.group == index), 0)
                    if weight <= 0:
                        continue
                    position = mesh_to_armature @ vertex.co
                    fraction = max(0.0, min(1.0, (position - parent.head).dot(segment) / segment.length_squared))
                    group.add([vertex.index], weight * (1 - fraction), "REPLACE")
                    if fraction > 0:
                        twist_group.add([vertex.index], weight * fraction, "REPLACE")
            inserted.append(name)
    return inserted


def add_leg_ik(armature):
    bones = armature.data.edit_bones
    completed = []
    for side in bm.LEG_IK_SPEC["sides"]:
        if any(side[key] not in bones for key in ("thigh_jp", "knee_jp", "ankle_jp", "toe_jp")):
            continue
        leg = bones.new(side["leg_ik_jp"])
        leg.head = bones[side["ankle_jp"]].head.copy()
        leg.tail = leg.head + Vector((0, -0.08, 0))
        leg.parent = bones["全ての親"]
        leg.use_deform = False
        toe = bones.new(side["toe_ik_jp"])
        toe.head = bones[side["toe_jp"]].head.copy()
        toe.tail = toe.head + Vector((0, -0.05, 0))
        toe.parent = leg
        toe.use_deform = False
        completed.append(side["side"])
    return completed


def configure_pose_bones(armature, twists, ik_sides):
    from mmd_tools_local.core.bone import FnBone

    glosses = {jp: en for jp, en, _ in bm.CATS_CANONICAL_TO_MMD_JP.values()}
    glosses.update({spec["jp"]: spec["en"] for spec in bm.ROOT_CHAIN_SPEC["chain"]})
    controls = {spec["jp"] for spec in bm.ROOT_CHAIN_SPEC["chain"]}
    for side in bm.LEG_IK_SPEC["sides"]:
        controls.update((side["leg_ik_jp"], side["toe_ik_jp"]))
        glosses[side["leg_ik_jp"]] = side["leg_ik_en"]
        glosses[side["toe_ik_jp"]] = side["toe_ik_en"]
    for bone in armature.pose.bones:
        bone.mmd_bone.name_j = bone.name
        bone.mmd_bone.name_e = glosses.get(bone.name, bone.name)
        bone.lock_location = (bone.name not in controls,) * 3
        bone.lock_scale = (True,) * 3
        bone.rotation_mode = "QUATERNION"
    armature.pose.bones["グルーブ"].lock_rotation = (True,) * 3
    # The bundled mmd_tools implementation uses geometric head/tail positions
    # to recalculate arms/fingers. Run after replacing Source display stubs.
    FnBone.apply_auto_bone_roll(armature)
    for name in twists:
        pose = armature.pose.bones[name]
        pose.mmd_bone.enabled_fixed_axis = True
        pose.mmd_bone.fixed_axis = (pose.bone.tail_local - pose.bone.head_local).normalized().xzy
    for side in bm.LEG_IK_SPEC["sides"]:
        if side["side"] not in ik_sides:
            continue
        knee, ankle = (armature.pose.bones[side[key]] for key in ("knee_jp", "ankle_jp"))
        leg = knee.constraints.new("IK")
        leg.name = "MMD leg IK"
        leg.target, leg.subtarget = armature, side["leg_ik_jp"]
        leg.use_tail, leg.chain_count, leg.iterations = True, 2, 48
        leg.use_stretch = False
        knee.mmd_bone.ik_rotation_constraint = 2.0
        knee.lock_ik_y = knee.lock_ik_z = True
        knee.use_ik_limit_x = True
        knee.ik_min_x, knee.ik_max_x = 0, math.radians(179.5)
        toe = ankle.constraints.new("IK")
        toe.name = "MMD toe IK"
        toe.target, toe.subtarget = armature, side["toe_ik_jp"]
        toe.use_tail, toe.chain_count, toe.iterations = True, 1, 6
        toe.use_stretch = False
        ankle.mmd_bone.ik_rotation_constraint = 4.0
        armature.pose.bones[side["leg_ik_jp"]].mmd_bone.transform_order = 1
        armature.pose.bones[side["toe_ik_jp"]].mmd_bone.transform_order = 2


def build_report(armature, meshes, twists, ik_sides, retained, removed, coordinates):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    weights = {name: {"weighted_vertices": 0, "total_weight": 0.0} for name in twists}
    report_meshes, warnings = [], []
    for obj in meshes:
        indices = {group.index: group.name for group in obj.vertex_groups}
        unweighted = invalid_sums = 0
        for vertex in obj.data.vertices:
            total = 0
            for item in vertex.groups:
                name = indices[item.group]
                if name not in armature.data.bones:
                    continue
                total += item.weight
                if name in weights and item.weight > 1e-7:
                    weights[name]["weighted_vertices"] += 1
                    weights[name]["total_weight"] += item.weight
            unweighted += total < 1e-7
            invalid_sums += abs(total - 1) > 1e-4
        evaluated = obj.evaluated_get(depsgraph)
        evaluated_mesh = evaluated.to_mesh()
        try:
            drift = max(((a.co - b.co).length for a, b in zip(obj.data.vertices, evaluated_mesh.vertices)), default=0)
        finally:
            evaluated.to_mesh_clear()
        entry = {"name": obj.name, "vertices": len(obj.data.vertices),
                 "triangles": sum(len(poly.vertices) - 2 for poly in obj.data.polygons),
                 "materials": len(obj.data.materials),
                 "shape_keys": len(obj.data.shape_keys.key_blocks) - 1 if obj.data.shape_keys else 0,
                 "unweighted_vertices": unweighted, "nonunit_weight_sums": invalid_sums,
                 "rest_pose_max_drift_m": drift}
        report_meshes.append(entry)
        if unweighted:
            warnings.append(f"{obj.name}: {unweighted} vertices have no deform-bone weights.")
        if drift > 0.002:
            warnings.append(f"{obj.name}: IK changes the rest mesh by up to {drift:.4f} m; inspect the saved checkpoint.")
    for name, stats in weights.items():
        if not stats["weighted_vertices"]:
            warnings.append(f"Twist bone {name} has no direct skin weights; this model may use custom helper weighting.")
    if len(ik_sides) != 2:
        warnings.append("One or both leg IK chains are missing required bones.")
    return {"stage": "retarget", "coordinates": coordinates, "meshes": report_meshes,
            "bone_count": len(armature.data.bones), "retained_auxiliary_bones": retained,
            "removed_meshes": removed, "twist_weights": weights,
            "leg_ik_sides": ik_sides, "leg_ik_parent": "全ての親", "warnings": warnings}


def run(qc_path: Path, save_path: Path, keep_mesh: list[str], report_path: Path | None = None):
    # This stage builds a new character checkpoint. A saved Blender startup
    # scene may contain a cube, camera or even an unrelated armature.
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    armature, meshes, removed = import_reference_qc(qc_path, keep_mesh)
    coordinates = normalize_geometry(armature, meshes)
    from source_helpers import redistribute_source_helpers
    from leg_tuning import knee_corrective_candidates, configure_knee_correctives
    from torso_pivots import capture_source_waist, calibrate_torso_pivots
    from arm_tuning import insert_twist_segments, configure_twist_segments
    from arm_hinge import elbow_corrective_candidates, configure_arm_hinges
    knee_helpers = knee_corrective_candidates(armature, qc_path)
    elbow_helpers = elbow_corrective_candidates(armature, qc_path)
    helpers = redistribute_source_helpers(armature, meshes, qc_path, preserve_helpers=knee_helpers + elbow_helpers)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    source_waist = capture_source_waist(armature)
    collapse_spine(armature, meshes)
    synthesize_root_chain(armature)
    retained = rename_bones(armature, meshes)
    torso = calibrate_torso_pivots(armature, source_waist)
    bpy.ops.object.mode_set(mode="OBJECT")
    from rest_pose import rebind_mmd_neutral_pose
    neutral = rebind_mmd_neutral_pose(armature, meshes)
    bpy.ops.object.mode_set(mode="EDIT")
    align_anatomical_tails(armature)
    twists = insert_twist_bones(armature, meshes)
    twist_segments = insert_twist_segments(armature, meshes, twists)
    ik_sides = add_leg_ik(armature)
    bpy.ops.object.mode_set(mode="OBJECT")
    configure_pose_bones(armature, twists, ik_sides)
    configure_twist_segments(armature, twist_segments)
    knees = configure_knee_correctives(armature, knee_helpers)
    elbows = configure_arm_hinges(armature, elbow_helpers)
    bpy.ops.object.mode_set(mode="OBJECT")
    report = build_report(armature, meshes, twists, ik_sides, retained, removed, coordinates)
    report["torso_pivots"] = torso
    report["knee_correctives"] = knees
    report["elbow_correctives"] = elbows
    report["twist_segments"] = twist_segments
    if torso.get("warning"):
        report["warnings"].append(torso["warning"])
    report["neutral_pose"] = neutral
    report["source_helper_skinning"] = helpers
    report["warnings"].extend(helpers["warnings"])
    if neutral.get("warning"):
        report["warnings"].append(neutral["warning"])
    report["source_qc"] = str(qc_path)
    if "VTA vertices" in removed:
        report["warnings"].append(
            "Source Tools reported unmatched VTA vertices. Facial shape keys were retained; see the import log for the count.")
    report_path = report_path or save_path.with_suffix(".rig.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for warning in report["warnings"]:
        eprint("warning: " + warning)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    print(f"Retargeted {len(meshes)} meshes, {len(armature.data.bones)} bones; report: {report_path}")
    print(f"Saved: {save_path}")


def main():
    args = parse_args()
    try:
        run(args.qc.resolve(), args.save.resolve(), args.keep_mesh,
            args.report_json.resolve() if args.report_json else None)
    except Exception as exc:
        import traceback
        eprint(f"error: {exc}")
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
