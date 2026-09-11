"""Use the character's own Source waist landmark for MMD torso controls."""
from mathutils import Vector


def capture_source_waist(armature):
    """Capture in EDIT mode before Source Spine is collapsed or renamed."""
    bone = armature.data.edit_bones.get('ValveBiped.Bip01_Spine')
    return bone.head.copy() if bone else None


def calibrate_torso_pivots(armature, source_waist):
    """Call in EDIT mode after the root chain and mapped torso bones exist.

    MMD upper/lower-body tracks can carry a common whole-torso rotation.
    They need a shared hinge, while Source separates pelvis and spine joints.
    Only these two bone heads change; mesh, weights, center and descendant
    joint positions retain the source character's original rest geometry.
    """
    bones = armature.data.edit_bones
    names = ('上半身', '下半身')
    if source_waist is None or any(name not in bones for name in names):
        return dict(applied=False, warning='Source waist landmark or mapped torso bones are missing; torso pivots were preserved.')
    point = Vector(source_waist)
    before = {b.name: (b.head.copy(), b.tail.copy()) for b in bones}
    for name in names:
        bone = bones[name]
        bone.use_connect = False
        bone.head = point
    # Changing a head must not drag an unrelated joint through a connected
    # hierarchy. Source Tools normally imports these bones disconnected.
    for bone in bones:
        old_head, old_tail = before[bone.name]
        if bone.name not in names and (bone.head-old_head).length > 1e-6:
            raise RuntimeError(f'Torso calibration moved descendant joint {bone.name}')
        if (bone.tail-old_tail).length > 1e-6:
            raise RuntimeError(f'Torso calibration moved the tail of {bone.name}')
    return dict(applied=True, source_landmark='ValveBiped.Bip01_Spine',
                common_waist_m=list(point),
                previous_heads_m={name:list(before[name][0]) for name in names})
