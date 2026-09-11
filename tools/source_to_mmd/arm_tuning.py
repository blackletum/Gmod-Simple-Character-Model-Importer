"""Distribute arm twists over short angular intervals using PMX append bones."""
from __future__ import annotations
import math


def insert_twist_segments(armature, meshes, twists):
    """In EDIT mode, refine the existing linear twist-weight gradient.

    A two-bone blend collapses the middle of a limb at a large twist. Three
    append-rotation helpers keep each blend within a quarter of that angle.
    The original control, rest geometry and total influence are unchanged.
    """
    bones = armature.data.edit_bones
    result = []
    for name in twists:
        twist = bones[name]
        parent = twist.parent
        names = [parent.name]
        for index in (1, 2, 3):
            helper = bones.new(name + str(index))
            helper.head = twist.head.copy()
            helper.tail = twist.tail.copy()
            helper.roll = twist.roll
            helper.parent = parent
            names.append(helper.name)
            result.append(dict(helper=helper.name, source=name, coefficient=index / 4))
        names.append(name)
        for mesh in meshes:
            source = mesh.vertex_groups.get(parent.name)
            target = mesh.vertex_groups.get(name)
            if source is None or target is None:
                continue
            indices = {source.index: 0, target.index: 1}
            assignments = []
            for vertex in mesh.data.vertices:
                weights = [0., 0.]
                for group in vertex.groups:
                    if group.group in indices:
                        weights[indices[group.group]] = group.weight
                total = sum(weights)
                if total > 1e-8:
                    fraction = min(1., max(0., weights[1] / total))
                    lower = min(3, int(math.floor(fraction * 4)))
                    alpha = fraction * 4 - lower
                    assignments.append((vertex.index, total, lower, alpha))
            groups = [mesh.vertex_groups.get(n) or mesh.vertex_groups.new(name=n) for n in names]
            touched = [row[0] for row in assignments]
            if touched:
                source.remove(touched)
                target.remove(touched)
            for index, total, lower, alpha in assignments:
                if alpha < 1:
                    groups[lower].add([index], total * (1-alpha), 'REPLACE')
                if alpha > 0:
                    groups[lower+1].add([index], total * alpha, 'REPLACE')
    return result


def configure_twist_segments(armature, segments):
    for row in segments:
        pose = armature.pose.bones[row['helper']]
        meta = pose.mmd_bone
        meta.name_j = pose.name
        meta.name_e = pose.name
        meta.has_additional_rotation = True
        meta.has_additional_location = False
        meta.additional_transform_bone = row['source']
        meta.additional_transform_influence = row['coefficient']
        meta.transform_order = 1
        meta.is_controllable = False
        pose.lock_location = pose.lock_rotation = pose.lock_scale = (True,) * 3
