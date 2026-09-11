"""Rebind a Source character to a neutral pose usable by ordinary MMD motion.

Joint lengths and skin weights remain the character's own. Rounded neutral
directions were checked against the supplied MMD reference; no reference mesh
or character-specific joint positions are copied into a converted model.
"""
from __future__ import annotations
import math
import bpy
import numpy as np
from mathutils import Matrix, Vector


def direction(side, degrees):
    angle=math.radians(degrees)
    return Vector((side*math.cos(angle),0,-math.sin(angle)))


def _aim(armature, name, target, child=None, axis=None):
    pose=armature.pose.bones.get(name)
    if pose is None:
        return None
    if child:
        endpoint=armature.pose.bones.get(child)
        if endpoint is None:return None
        current=endpoint.head-pose.head
    else:
        current=(pose.matrix@pose.bone.matrix_local.inverted()).to_3x3()@axis
    if current.length<1e-7:return None
    rotation=current.normalized().rotation_difference(target.normalized())
    head=pose.head.copy()
    pose.matrix=Matrix.Translation(head)@rotation.to_matrix().to_4x4()@Matrix.Translation(-head)@pose.matrix
    bpy.context.view_layer.update()
    return math.degrees(rotation.angle)


def _palm_frame(long_axis, across):
    along=long_axis.normalized()
    width=(across-along*across.dot(along)).normalized()
    if width.length<1e-5:raise ValueError('Cannot determine palm orientation')
    return Matrix((along,width,along.cross(width))).transposed()


def _distal_axis(meshes, bone):
    """Find the distal phalanx direction from its weighted surface, not a stub."""
    points=[]
    for mesh in meshes:
        group=mesh.vertex_groups.get(bone.name)
        if group:
            points.extend(tuple(v.co) for v in mesh.data.vertices
                          if any(g.group==group.index and g.weight>=.5 for g in v.groups))
    if len(points)<6:return None
    xyz=np.array(points,dtype=float)
    eigenvalues,eigenvectors=np.linalg.eigh(np.cov(xyz.T))
    if eigenvalues[-1]<eigenvalues[-2]*1.25:return None
    axis=Vector(eigenvectors[:,-1])
    outward=bone.head_local-bone.parent.head_local
    if axis.dot(outward)<0:axis.negate()
    return axis


def rebind_mmd_neutral_pose(armature, meshes):
    """Call in OBJECT mode, before adding IK/twist controls or pose drivers."""
    poses=armature.pose.bones
    names={b.name for b in poses}
    if any(s+n not in names for s in ('左','右') for n in ('腕','ひじ','手首')):
        return {'applied':False,'warning':'Missing arm joints; neutral arm pose was not calibrated.'}
    for pose in poses:
        pose.matrix_basis.identity()
    bpy.context.view_layer.update()
    distal={}
    for side in ('左','右'):
        for finger in ('人指','中指','薬指','小指'):
            bone=armature.data.bones.get(side+finger+'３')
            if bone and bone.parent:
                axis=_distal_axis(meshes,bone)
                if axis is not None:distal[bone.name]=axis
    corrections={}
    for side,sign in [('左',1),('右',-1)]:
        corrections[side+'腕']=_aim(armature,side+'腕',direction(sign,42),side+'ひじ')
        corrections[side+'ひじ']=_aim(armature,side+'ひじ',direction(sign,40),side+'手首')
        palm_names=[side+n for n in ('手首','中指１','人指１','小指１')]
        if all(n in poses for n in palm_names):
            wrist,middle,index,little=[poses[n] for n in palm_names]
            old=_palm_frame(middle.head-wrist.head,little.head-index.head)
            target=_palm_frame(direction(sign,40),Vector((0,1,0)))
            rotation=(target@old.transposed()).to_4x4()
            head=wrist.head.copy()
            wrist.matrix=Matrix.Translation(head)@rotation@Matrix.Translation(-head)@wrist.matrix
            bpy.context.view_layer.update()
            corrections[side+'手首']=math.degrees(rotation.to_quaternion().angle)
        for finger in ('人指','中指','薬指','小指'):
            for a,b in [('１','２'),('２','３')]:
                name=side+finger+a
                corrections[name]=_aim(armature,name,direction(sign,40),side+finger+b)
            name=side+finger+'３'
            if name in distal:
                corrections[name]=_aim(armature,name,direction(sign,40),axis=distal[name])
        # Thumb remains abducted instead of being made parallel to the fingers.
        # Preserve all three Source joints as the semi-standard thumb 0/1/2.
        corrections[side+'親指０']=_aim(armature,side+'親指０',Vector((sign*.65,-.47,-.60)),side+'親指１')
        corrections[side+'親指１']=_aim(armature,side+'親指１',Vector((sign*.16,-.52,-.84)),side+'親指２')
    from leg_tuning import pose_forward_feet
    feet = pose_forward_feet(armature)
    skin={pose.name:np.array(pose.matrix@pose.bone.matrix_local.inverted(),dtype=np.float64) for pose in poses}
    baked=[]
    dg=bpy.context.evaluated_depsgraph_get()
    for mesh in meshes:
        if any(mod.type=='ARMATURE' and mod.use_deform_preserve_volume for mod in mesh.modifiers):
            raise ValueError('Neutral-pose rebinding currently requires linear skinning')
        n=len(mesh.data.vertices)
        transforms=np.zeros((n,4,4),dtype=np.float64)
        groups={g.index:skin[g.name] for g in mesh.vertex_groups if g.name in skin}
        for vertex in mesh.data.vertices:
            total=0.0
            for assignment in vertex.groups:
                matrix=groups.get(assignment.group)
                if matrix is not None:
                    transforms[vertex.index]+=matrix*assignment.weight;total+=assignment.weight
            if total>1e-8:transforms[vertex.index]/=total
            else:transforms[vertex.index]=np.identity(4)
        keys=mesh.data.shape_keys.key_blocks if mesh.data.shape_keys else []
        data=[key.data for key in keys] if keys else [mesh.data.vertices]
        coordinates=[]
        for block in data:
            xyz=np.empty(n*3,dtype=np.float32);block.foreach_get('co',xyz);xyz=xyz.reshape(n,3)
            coordinates.append(np.einsum('nij,nj->ni',transforms[:,:3,:3],xyz)+transforms[:,:3,3])
        evaluated=mesh.evaluated_get(dg);evaluated_mesh=evaluated.to_mesh()
        try:
            check=np.array([v.co[:] for v in evaluated_mesh.vertices])
        finally:evaluated.to_mesh_clear()
        drift=float(np.max(np.linalg.norm(check-coordinates[0],axis=1),initial=0))
        if drift>.0001:raise ValueError(f'{mesh.name}: rebinding differs from evaluated skin by {drift:.6f}m')
        normals=None
        if mesh.data.has_custom_normals:
            source=np.array([normal.vector[:] for normal in mesh.data.corner_normals])
            indices=np.array([loop.vertex_index for loop in mesh.data.loops])
            normal_matrices=np.linalg.inv(transforms[:,:3,:3]).transpose(0,2,1)
            normals=np.einsum('nij,nj->ni',normal_matrices[indices],source)
            normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-12)
        baked.append((mesh,data,coordinates,normals,drift))
    bpy.context.view_layer.objects.active=armature
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    for mesh,data,coordinates,normals,drift in baked:
        for block,xyz in zip(data,coordinates):block.foreach_set('co',xyz.astype(np.float32).ravel())
        mesh.data.vertices.foreach_set('co',coordinates[0].astype(np.float32).ravel())
        if normals is not None:mesh.data.normals_split_custom_set(normals.tolist())
        mesh.data.update();mesh.show_only_shape_key=False
    bpy.context.view_layer.update()
    return dict(applied=True,feet=feet,arm_degrees_below_horizontal=42,forearm_and_fingers_degrees=40,
        corrections_degrees=corrections,meshes=[dict(name=m.name,shape_keys=len(d)-1 if m.data.shape_keys else 0,
            max_skin_bake_error_m=drift) for m,d,c,n,drift in baked])
