"""Stable parent-before-child ordering for an mmd_tools PMX model object.

Only bone ordering and references change. Transform layers, flags, axes,
weights and every geometric/morph/physics value are left intact. This helps
simple consumers without claiming that raw-index evaluation matches PMX.
"""
from __future__ import annotations

import heapq


def reorder_bones_parent_first(model) -> dict:
    bones = model.bones
    count = len(bones)

    def check(index, context):
        if index is None or index == -1:
            return
        if not isinstance(index, int) or not 0 <= index < count:
            raise ValueError(f"Invalid PMX bone reference {index!r} in {context}")

    children = [[] for _ in bones]
    indegree = [0] * count
    for index, bone in enumerate(bones):
        check(bone.parent, f"parent of {bone.name}")
        if bone.parent is not None and bone.parent >= 0:
            children[bone.parent].append(index)
            indegree[index] += 1
    ready = [index for index, degree in enumerate(indegree) if degree == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        index = heapq.heappop(ready)
        order.append(index)
        for child in children[index]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(order) != count:
        raise ValueError("PMX bone parent hierarchy contains a cycle")
    mapping = {old: new for new, old in enumerate(order)}

    def remap(index, context):
        check(index, context)
        return mapping[index] if index is not None and index >= 0 else index

    # Validate and compute every replacement before mutating the model, so a
    # malformed reference cannot leave the caller with a partly reordered file.
    vertex_refs = [[remap(index, "vertex weight") for index in vertex.weight.bones]
                   for vertex in model.vertices]
    bone_refs = []
    for bone in bones:
        tail = bone.displayConnection
        if isinstance(tail, int):
            tail = remap(tail, f"tail of {bone.name}")
        append = bone.additionalTransform
        if append is not None:
            append = (remap(append[0], f"append parent of {bone.name}"), append[1])
        target = remap(bone.target, f"IK target of {bone.name}")
        links = [remap(link.target, f"IK link of {bone.name}") for link in bone.ik_links]
        bone_refs.append((remap(bone.parent, f"parent of {bone.name}"), tail, append, target, links))
    morph_refs = [(offset, remap(offset.index, f"bone morph {morph.name}"))
                  for morph in model.morphs if morph.type_index() == 2 for offset in morph.offsets]
    display_refs = [[(kind, remap(index, f"display {frame.name}") if kind == 0 else index)
                     for kind, index in frame.data] for frame in model.display]
    rigid_refs = [remap(rigid.bone, "rigid body") for rigid in model.rigids]
    moved = [dict(name=bones[old].name, old_index=old, new_index=new)
             for new, old in enumerate(order) if old != new]
    if moved:
        for vertex, refs in zip(model.vertices, vertex_refs):
            vertex.weight.bones = refs
        for bone, (parent, tail, append, target, links) in zip(bones, bone_refs):
            bone.parent = parent
            bone.displayConnection = tail
            bone.additionalTransform = append
            bone.target = target
            for link, index in zip(bone.ik_links, links):
                link.target = index
        for offset, index in morph_refs:
            offset.index = index
        for frame, refs in zip(model.display, display_refs):
            frame.data = refs
        for rigid, index in zip(model.rigids, rigid_refs):
            rigid.bone = index
        model.bones = [bones[index] for index in order]
    return dict(method="Stable parent-before-child PMX bone order",
                moved_bones=len(moved), changes=moved)
