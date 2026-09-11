"""Validate exported PMX geometry, weights, textures and MMD controls."""
from __future__ import annotations
import argparse
import math
from pathlib import Path
import sys
import types
import zipfile
sys.path.insert(0,str(Path(__file__).parent))
from common import project_root,write_json

def load_pmx(path):
    archive=project_root()/'plugins_software'/'Cats-Blender-Plugin-Unofficial4.5.3.2.zip'
    with zipfile.ZipFile(archive) as z:
        member=next(n for n in z.namelist() if n.endswith('mmd_tools_local/core/pmx/__init__.py'))
        module=types.ModuleType('source_pmx_format')
        exec(compile(z.read(member),member,'exec'),module.__dict__)
    with module.FileReadStream(str(path)) as f:
        h=module.Header();h.load(f);f.setHeader(h)
        m=module.Model();m.load(f)
    return m

def validate(path):
    model=load_pmx(path)
    errors=[];warnings=[];counts={k:len(getattr(model,k)) for k in ('vertices','faces','materials','bones','morphs','rigids','joints')}
    if not model.vertices or not model.faces: errors.append('No character geometry.')
    weighted=set()
    for vertex in model.vertices:
        if not all(math.isfinite(x) for x in vertex.co): errors.append('Non-finite vertex position.');break
        w=vertex.weight
        if w.type==0: weights=[1.0]
        elif w.type==1: weights=[w.weights[0],1-w.weights[0]]
        elif w.type==2: weights=w.weights
        elif w.type==3: weights=[w.weights.weight,1-w.weights.weight]
        else: errors.append('Unsupported vertex weight type.');break
        if abs(sum(weights)-1)>0.001 or any(x< -0.0001 or x>1.0001 for x in weights):
            errors.append('Invalid or unnormalized skin weights.');break
        for bone,weight in zip(w.bones,weights):
            if weight>0:
                if not 0<=bone<len(model.bones): errors.append('Skin weight references missing bone.');break
                weighted.add(bone)
    for face in model.faces:
        if any(i<0 or i>=len(model.vertices) for i in face): errors.append('Face references missing vertex.');break
    for i,b in enumerate(model.bones):
        seen={i};parent=b.parent
        while parent>=0:
            if parent>=len(model.bones) or parent in seen:
                errors.append('Invalid or cyclic bone hierarchy.');break
            seen.add(parent);parent=model.bones[parent].parent
        if '捩' in b.name and i not in weighted:
            warnings.append(f'Twist bone {b.name} has no direct mesh weights.')
        if b.isIK and ('足ＩＫ' in b.name or '足IK' in b.name):
            if b.parent>=0 and model.bones[b.parent].name in ('下半身','センター','グルーブ'):
                errors.append(f'{b.name} inherits center/pelvis motion instead of independent foot control.')
    textures=[]
    for t in model.textures:
        p=Path(t.path)
        if not p.is_file(): errors.append(f'Missing exported texture: {p.name}')
        if not p.resolve().is_relative_to(path.parent.resolve()): errors.append(f'Texture is not portable: {p}')
        textures.append(str(p))
    for morph in model.morphs:
        if morph.type_index()==1:
            for item in morph.offsets:
                if not 0<=item.index<len(model.vertices) or not all(math.isfinite(x) for x in item.offset):
                    errors.append(f'Invalid vertex morph: {morph.name}');break
    names={m.name for m in model.morphs}
    if 'まばたき' not in names: warnings.append('No standard MMD blink morph was generated.')
    height=max(v.co[1] for v in model.vertices)-min(v.co[1] for v in model.vertices) if model.vertices else 0
    if not 5<height<50: warnings.append(f'Unusual MMD model height: {height:.3f} units; check scale.')
    return dict(ok=not errors,errors=list(dict.fromkeys(errors)),warnings=list(dict.fromkeys(warnings)),
                counts=counts,height_pmx_units=height,textures=textures,morph_names=sorted(names),
                motion_validation='Not performed by this structural check.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--pmx',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();result=validate(a.pmx.resolve());write_json(a.report,result)
    print('PMX validation:', 'passed' if result['ok'] else 'failed',result['counts'])
    if result['errors']: print('\n'.join(result['errors']))
    return 0 if result['ok'] else 1

if __name__=='__main__': raise SystemExit(main())
