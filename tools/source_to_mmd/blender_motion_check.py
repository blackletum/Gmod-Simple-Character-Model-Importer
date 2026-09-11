"""Roundtrip a PMX through Blender and inspect sampled VMD deformation."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

def bounds(meshes):
    dg=bpy.context.evaluated_depsgraph_get()
    low=Vector((math.inf,math.inf,math.inf)); high=-low
    count=0
    for obj in meshes:
        evaluated=obj.evaluated_get(dg)
        mesh=evaluated.to_mesh()
        try:
            for v in mesh.vertices:
                point=evaluated.matrix_world @ v.co
                if not all(math.isfinite(x) for x in point):
                    raise RuntimeError('Motion produced a non-finite vertex.')
                for axis in range(3):
                    low[axis]=min(low[axis],point[axis]);high[axis]=max(high[axis],point[axis])
                count+=1
        finally:
            evaluated.to_mesh_clear()
    if not count: raise RuntimeError('PMX import produced no mesh vertices.')
    return dict(min=list(low),max=list(high),diagonal=(high-low).length,vertices=count)

def run(pmx,motion,report_path,save_blend):
    if motion.suffix.lower()!='.vmd' or not motion.is_file():
        raise ValueError('Motion check requires a readable VMD file.')
    for obj in list(bpy.data.objects): bpy.data.objects.remove(obj,do_unlink=True)
    outcome=bpy.ops.mmd_tools_local.import_model(filepath=str(pmx),scale=0.08,rename_bones=False)
    if 'FINISHED' not in outcome: raise RuntimeError('Could not reimport the exported PMX for motion checks.')
    roots=[o for o in bpy.data.objects if getattr(o,'mmd_type',None)=='ROOT']
    if len(roots)!=1: raise RuntimeError('Expected one imported MMD model.')
    meshes=[o for o in bpy.data.objects if o.type=='MESH']
    baseline=bounds(meshes)
    bpy.ops.object.select_all(action='DESELECT')
    root=roots[0];root.select_set(True);bpy.context.view_layer.objects.active=root
    outcome=bpy.ops.mmd_tools_local.import_vmd(filepath=str(motion),directory=str(motion.parent),
        files=[{'name':motion.name}],scale=0.08,bone_mapper='PMX',update_scene_settings=True)
    if 'FINISHED' not in outcome: raise RuntimeError('Could not import VMD for motion checks.')
    # A VMD can load successfully while none of its controls match this model.
    # Reject that case instead of passing checks on an unanimated character.
    bone_curves = 0
    morph_curves = 0
    for obj in bpy.data.objects:
        animation = obj.animation_data if obj.type == 'ARMATURE' else None
        if animation and animation.action:
            bone_curves += sum(len(c.keyframe_points) > 1 and c.data_path.startswith('pose.bones[')
                               for c in animation.action.fcurves)
        if obj.type == 'MESH' and obj.data.shape_keys:
            animation = obj.data.shape_keys.animation_data
            if animation and animation.action:
                morph_curves += sum(len(c.keyframe_points) > 1 for c in animation.action.fcurves)
    if not bone_curves and not morph_curves:
        raise RuntimeError('The VMD has no animated bone or facial controls matching this model.')
    scene=bpy.context.scene
    start,end=scene.frame_start,scene.frame_end
    if end<=start: raise RuntimeError('The motion contains no usable animation range.')
    frames=sorted({start+round((end-start)*i/31) for i in range(32)})
    samples=[];errors=[]
    for f in frames:
        scene.frame_set(f);bpy.context.view_layer.update()
        b=bounds(meshes)
        ratio=b['diagonal']/max(baseline['diagonal'],1e-8)
        if ratio>3.0 or ratio<0.1:
            errors.append(f'Frame {f}: unusually large/collapsed geometry ({ratio:.2f}x rest bounds).')
        samples.append(dict(frame=f,bounds=b,relative_diagonal=ratio))
    scene.frame_set(start)
    if save_blend:
        save_blend.parent.mkdir(parents=True,exist_ok=True)
        for image in bpy.data.images:
            if image.source == 'FILE' and image.filepath:
                absolute = Path(bpy.path.abspath(image.filepath)).resolve()
                if absolute.is_file() and absolute.is_relative_to(pmx.parent):
                    image.filepath = bpy.path.relpath(str(absolute), start=str(save_blend.parent))
        bpy.ops.wm.save_as_mainfile(filepath=str(save_blend), relative_remap=False)
    report=dict(ok=not errors,errors=errors,warnings=[],engine='Blender mmd_tools PMX reimport + VMD',
        motion=str(motion),frame_range=[start,end],samples=samples,animated_bone_curves=bone_curves,
        animated_morph_curves=morph_curves,blend_path=str(save_blend) if save_blend else None,
        limitation='Samples detect broken geometry; they do not establish animation fidelity in the native MMD player.')
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if errors: raise RuntimeError('; '.join(errors[:4]))
    print(f'Blender motion checks passed on {len(frames)} frames ({start}–{end}).')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pmx',type=Path,required=True);p.add_argument('--motion',type=Path,required=True)
    p.add_argument('--report-json',type=Path,required=True);p.add_argument('--save-blend',type=Path)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    run(a.pmx.resolve(),a.motion.resolve(),a.report_json.resolve(),a.save_blend.resolve() if a.save_blend else None)

if __name__=='__main__':main()
