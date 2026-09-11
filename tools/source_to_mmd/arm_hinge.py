"""Verified Source elbow half-angle response as portable PMX append rotation.

This module is separate from arm/twist layout. It retains the Source helper
weights and pivot, and attaches the helper to the final upper-arm twist.
"""
from __future__ import annotations

import bpy


def elbow_corrective_candidates(armature, qc_path):
    from source_helpers import plan_helper_transfers, vrd_from_qc
    vrd = vrd_from_qc(qc_path)
    if vrd is None:
        return []
    parents = {bone.name: bone.parent.name if bone.parent else None
               for bone in armature.data.bones}
    rules, _ = plan_helper_transfers(vrd.read_text(encoding="utf-8", errors="replace"), parents)
    return [rule.source for rule in rules
            if rule.source in ("ValveBiped.Bip01_L_Elbow", "ValveBiped.Bip01_R_Elbow")
            and len(rule.targets) == 2]


def configure_arm_hinges(armature, candidates):
    """After neutral rebinding and twist insertion, before final PMX export.

    Exclude candidates from earlier helper-weight redistribution. Reparenting
    preserves the helper's global rest pivot, so neither mesh rest appearance
    nor its source pivot offset changes. Its axes align with the elbow to avoid
    Euler-axis mixing in Blender's append-constraint representation. Its parent is the
    upper arm; the new parent is the upper-arm twist that now precedes elbow.
    """
    records = []
    for letter, side in (("L", "左"), ("R", "右")):
        name = f"ValveBiped.Bip01_{letter}_Elbow"
        if name not in candidates:
            continue
        helper = armature.data.bones.get(name)
        elbow = armature.data.bones.get(side + "ひじ")
        twist = armature.data.bones.get(side + "腕捩")
        upper = armature.data.bones.get(side + "腕")
        if not all((helper, elbow, twist, upper)):
            raise ValueError(f"{name}: missing arm/twist joints for verified elbow corrective")
        if helper.parent not in (upper, twist) or elbow.parent != twist:
            raise ValueError(f"{name}: arm hierarchy differs from the expected twist/elbow chain")
        records.append(dict(helper=name, source=elbow.name, parent=twist.name,
                            coefficient=.5, transform_order=3,
                            pivot_offset_m=list(helper.head_local - elbow.head_local),
                            method="Verified VRD half-angle elbow response as PMX append rotation"))
    if not records:
        return records
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        bones = armature.data.edit_bones
        for record in records:
            helper = bones[record["helper"]]
            head = helper.head.copy()
            length = helper.length
            helper.use_connect = False
            helper.parent = bones[record["parent"]]
            helper.head = head
            elbow = bones[record["source"]]
            helper.tail = head + elbow.vector.normalized() * length
            helper.roll = elbow.roll
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    for record in records:
        helper = armature.pose.bones[record["helper"]]
        metadata = helper.mmd_bone
        metadata.has_additional_rotation = True
        metadata.has_additional_location = False
        metadata.additional_transform_bone = record["source"]
        metadata.additional_transform_influence = .5
        metadata.transform_order = 3
        metadata.enabled_local_axes = True
        axes = helper.bone.matrix_local.to_3x3().transposed()
        metadata.local_axis_x = axes[0].xzy
        metadata.local_axis_z = axes[2].xzy
        helper.lock_location = (True,) * 3
        helper.lock_rotation = (True,) * 3
        helper.lock_scale = (True,) * 3
    if armature.data.collections.get("mmd_dummy"):
        from mmd_tools_local.core.bone import FnBone
        FnBone.apply_additional_transformation(armature)
    return records
