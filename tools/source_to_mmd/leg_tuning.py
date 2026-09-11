"""Conservative neutral feet and verified half-angle knee correctives."""
from __future__ import annotations
import math
from mathutils import Matrix, Vector
import bpy


def pose_forward_feet(armature):
    """Call while posing the neutral bind, before baking skin and shape keys.

    Correct yaw only. Keep ankle height, foot pitch, joint lengths and the
    character's actual feet. This is a neutral-motion compatibility choice.
    """
    result=[]
    for side in ("左", "右"):
        ankle=armature.pose.bones.get(side+"足首")
        toe=armature.pose.bones.get(side+"つま先")
        if ankle is None or toe is None:
            continue
        foot=toe.head-ankle.head
        if math.hypot(foot.x,foot.y)<.025 or foot.y>=0:
            result.append(dict(side=side,applied=False,reason="Foot direction is ambiguous"))
            continue
        yaw=math.atan2(foot.x,-foot.y)
        # A sideways/backward foot can represent an unusual/custom skeleton.
        if abs(yaw)>math.radians(35):
            result.append(dict(side=side,applied=False,reason="Foot yaw exceeds conservative correction range"))
            continue
        pivot=ankle.head.copy()
        rotation=Matrix.Rotation(-yaw,4,"Z")
        ankle.matrix=Matrix.Translation(pivot)@rotation@Matrix.Translation(-pivot)@ankle.matrix
        bpy.context.view_layer.update()
        result.append(dict(side=side,applied=True,yaw_correction_degrees=-math.degrees(yaw)))
    return result


def knee_corrective_candidates(armature,qc_path):
    """Use the existing strict VRD signature + measured half-bend recognizer."""
    from source_helpers import plan_helper_transfers, vrd_from_qc
    vrd=vrd_from_qc(qc_path)
    if vrd is None:return []
    parents={bone.name:bone.parent.name if bone.parent else None for bone in armature.data.bones}
    rules,_=plan_helper_transfers(vrd.read_text(encoding="utf-8",errors="replace"),parents)
    return [rule.source for rule in rules if rule.source in
            ("ValveBiped.Bip01_L_Knee","ValveBiped.Bip01_R_Knee") and len(rule.targets)==2]


def configure_knee_correctives(armature,candidates):
    """After rename/rebind/IK configuration, preserve Source knee weights.

    Candidate helpers must be excluded from the earlier LBS transfer. The
    half-angle rotation is PMX append rotation, evaluated after leg/toe IK.
    """
    result=[]
    for letter,side in (("L","左"),("R","右")):
        name=f"ValveBiped.Bip01_{letter}_Knee"
        if name not in candidates:continue
        helper=armature.pose.bones.get(name)
        knee=armature.pose.bones.get(side+"ひざ")
        thigh=armature.pose.bones.get(side+"足")
        if not helper or not knee or not thigh:continue
        if helper.parent!=thigh or (helper.head-knee.head).length>.002:
            raise ValueError(f"{name}: verified knee helper no longer matches its anatomical hinge")
        meta=helper.mmd_bone
        meta.has_additional_rotation=True
        meta.has_additional_location=False
        meta.additional_transform_bone=knee.name
        meta.additional_transform_influence=.5
        meta.transform_order=3
        helper.lock_location=(True,)*3
        helper.lock_rotation=(True,)*3
        helper.lock_scale=(True,)*3
        result.append(dict(helper=name,source=knee.name,coefficient=.5,
                           transform_order=3,method="Verified VRD half-angle knee response as PMX append rotation"))
    # Bare Source armatures do not yet have the add-on's dummy/shadow bone
    # collections. Export reads these metadata properties directly. Build the
    # editable Blender constraints after convert_to_mmd_model has run.
    if result and armature.data.collections.get("mmd_dummy"):
        from mmd_tools_local.core.bone import FnBone
        FnBone.apply_additional_transformation(armature)
    return result
