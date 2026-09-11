"""Decompile a Source character and resolve its model parts and materials."""
from __future__ import annotations
import argparse
import hashlib
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PipelineError, ascii_staging_root, find_external_tool, run_tool, safe_name, write_json

TOKEN_RE = re.compile(r'"([^"\r\n]*)"|([^\s{}"]+)|([{}])')

def tokens(text):
    text = re.sub(r'//[^\r\n]*', '', text)
    return [next(x for x in m.groups() if x is not None) for m in TOKEN_RE.finditer(text)]

def inside(root: Path, raw: str, extension='') -> Path:
    raw = raw.replace('\\', '/')
    if extension and not raw.lower().endswith(extension):
        raw += extension
    p = (root / raw).resolve()
    if not p.is_relative_to(root.resolve()):
        raise PipelineError(f'Resource path escapes its folder: {raw}')
    return p

def qc_parts(text: str, qc_dir: Path) -> dict:
    """Only render-body directives count; never guess a largest SMD/LOD."""
    ts = tokens(text)
    mandatory, groups, all_names, sources = [], [], [], {}
    def mesh(raw):
        p = inside(qc_dir, raw, '.smd')
        if not p.is_file():
            raise PipelineError(f'Reference mesh is missing: {p}')
        name = p.stem
        if name in sources and sources[name] != str(p):
            raise PipelineError(f'Two reference meshes share the same name: {name}. Rename the parts before conversion.')
        sources[name] = str(p)
        if name not in all_names:
            all_names.append(name)
        return name
    i = 0
    while i < len(ts):
        t = ts[i].lower()
        if t in ('$model', '$body') and i + 2 < len(ts):
            mandatory.append(mesh(ts[i+2]))
            i += 3
        elif t == '$bodygroup' and i + 2 < len(ts):
            name = ts[i+1]
            i += 2
            if ts[i] != '{':
                raise PipelineError(f'Invalid bodygroup: {name}')
            i += 1
            choices = []
            while i < len(ts) and ts[i] != '}':
                if ts[i].lower() == 'studio' and i+1 < len(ts):
                    choices.append(mesh(ts[i+1])); i += 2
                elif ts[i].lower() == 'blank':
                    choices.append(None); i += 1
                else:
                    i += 1
            groups.append({'name':name,'meshes':[x for x in choices if x], 'allow_blank':None in choices,
                           'default':choices[0] if choices else None})
        else:
            i += 1
    mandatory = list(dict.fromkeys(mandatory))
    if not all_names:
        raise PipelineError('The model has no render meshes. Choose a character .mdl, not an animation library.')
    return dict(mesh_names=all_names, mesh_sources=sources, mandatory_meshes=mandatory, mesh_groups=groups,
                default_meshes=list(dict.fromkeys(mandatory+[g['default'] for g in groups if g['default']])))

def parse_smd_material_names(text):
    lines = text.splitlines()
    try: start = next(i for i,x in enumerate(lines) if x.strip()=='triangles')+1
    except StopIteration: return set()
    out = set()
    while start < len(lines) and lines[start].strip() != 'end':
        if not lines[start].strip(): start += 1; continue
        out.add(lines[start].strip()); start += 4
    return out

def vmt_values(text):
    ts = tokens(text)
    values = {}
    for i, key in enumerate(ts[:-1]):
        if (key.startswith('$') or key.lower()=='include') and ts[i+1] not in ('{','}'):
            values[key.lower()] = ts[i+1]
    return (ts[0].lower() if ts else ''), values

def read_vmt(path: Path, root: Path, seen=None):
    seen = set() if seen is None else seen
    if path in seen or len(seen) >= 12:
        raise PipelineError(f'Cyclic or excessive VMT includes: {path.name}')
    seen.add(path)
    shader, values = vmt_values(path.read_text(encoding='utf-8-sig', errors='replace'))
    if shader == 'patch':
        if 'include' not in values:
            raise PipelineError(f'Patch material has no include: {path.name}')
        inc = values.pop('include')
        if inc.lower().startswith('materials/'):
            inc = inc[10:]
        base_shader, base = read_vmt(inside(root, inc, '.vmt'), root, seen)
        base.update(values)
        return base_shader, base
    return shader, values

def convert_vtf(vtf: Path, texture_root: Path, material_root: Path):
    tool = find_external_tool('vtfcmd/VTFCmd.exe', env_var='VTFCMD')
    if tool is None:
        raise PipelineError('Bundled VTFCmd is missing.')
    key = vtf.relative_to(material_root).as_posix().lower()
    target = texture_root / (safe_name(vtf.stem) + '_' + hashlib.sha1(key.encode()).hexdigest()[:8] + '.png')
    if target.is_file():
        return target
    # Only staged copies go to ANSI-only VTFCmd; never write beside source VTFs.
    with tempfile.TemporaryDirectory(prefix='vtf_', dir=ascii_staging_root()) as tmp:
        scratch=Path(tmp); out=scratch/'out'; out.mkdir()
        shutil.copyfile(vtf, scratch/'texture.vtf')
        result=run_tool([tool,'-folder',str(scratch/'*.vtf'),'-output',out,'-exportformat','png'],description='Texture conversion')
        png=out/'texture.png'
        if not png.exists():
            raise PipelineError(f'No PNG produced for {vtf.name}: {result.stdout}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(png,target)
    return target

def material_roots(mdl: Path):
    roots=[]
    for parent in list(mdl.parents)[:6]:
        candidate=parent/'materials'
        if candidate.is_dir() and candidate not in roots:
            roots.append(candidate)
    return roots

def locate_vmt(root: Path, name: str, cdmaterials):
    for sub in list(cdmaterials)+['']:
        candidate=inside(root,(sub.rstrip('/')+'/' if sub else '')+name,'.vmt')
        if candidate.is_file(): return candidate
    return None

def parse_eyes(qc_text):
    eyes=[]
    for line in qc_text.splitlines():
        ts=tokens(line)
        if ts and ts[0].lower()=='eyeball' and len(ts)>=11:
            try:
                eyes.append(dict(name=ts[1],bone=ts[2],origin_source=[float(x) for x in ts[3:6]],
                    material=ts[6],diameter=float(ts[7]),angle=float(ts[8]),iris_scale=float(ts[10])))
            except ValueError: pass
    return eyes

def run(mdl: Path, materials_root: Path | None, out: Path):
    if sys.platform!='win32':
        raise PipelineError('Source to MMD currently requires Windows for the bundled Crowbar decompiler.')
    if not mdl.is_file() or mdl.suffix.lower()!='.mdl':
        raise PipelineError('Choose a compiled Source character .mdl file.')
    header=mdl.read_bytes()[:80]
    if len(header)<80 or header[:4]!=b'IDST':
        raise PipelineError('The selected file is not a supported Source MDL.')
    for companion in (mdl.with_suffix('.vvd'),mdl.with_suffix('.dx90.vtx')):
        if not companion.is_file():
            raise PipelineError(f'Missing companion {companion.name}. Extract the complete model set first.')
    crowbar=find_external_tool('crowbar/cli/CrowbarCommandLineDecomp.exe',env_var='MCI_CROWBAR')
    if not crowbar: raise PipelineError('Crowbar command-line decompiler is missing.')
    decompiled=out/'decompiled'; decompiled.mkdir(parents=True,exist_ok=True)
    # Stage the complete companion set into a unique ASCII directory.
    with tempfile.TemporaryDirectory(prefix='mdl_',dir=ascii_staging_root()) as tmp:
        scratch=Path(tmp); target=scratch/'out'; target.mkdir()
        for p in mdl.parent.glob(mdl.stem+'.*'):
            if p.is_file(): shutil.copyfile(p,scratch/p.name)
        result=run_tool([crowbar,'-p',scratch/mdl.name,'-o',target],description='Crowbar decompilation')
        print(result.stdout,flush=True)
        shutil.copytree(target,decompiled,dirs_exist_ok=True)
    candidates=list(decompiled.rglob('*.qc'))
    if len(candidates)!=1:
        raise PipelineError(f'Expected one decompiled QC; found {len(candidates)}.')
    qc=candidates[0]; text=qc.read_text(encoding='utf-8-sig',errors='replace')
    parts=qc_parts(text,qc.parent)
    ts=tokens(text)
    cd=[ts[i+1].replace('\\','/').strip('/') for i,x in enumerate(ts[:-1]) if x.lower()=='$cdmaterials']
    material_names=set()
    for name in parts['mesh_names']:
        material_names.update(parse_smd_material_names(Path(parts['mesh_sources'][name]).read_text(encoding='utf-8-sig',errors='replace')))
    roots=[materials_root] if materials_root else material_roots(mdl)
    if not roots:
        raise PipelineError('Could not find the materials folder. Select it explicitly.')
    if materials_root and materials_root.name.lower()!='materials' and (materials_root/'materials').is_dir():
        roots=[materials_root/'materials']
    chosen=max(roots,key=lambda root:sum(locate_vmt(root,n,cd) is not None for n in material_names))
    if not chosen.is_dir(): raise PipelineError(f'Materials folder does not exist: {chosen}')
    warnings=[]; materials=[]
    for name in sorted(material_names):
        row=dict(material_name=name,converted_png=None,iris_png=None,shader='',params={},warning=None)
        try:
            vmt=locate_vmt(chosen,name,cd)
            if vmt is None: raise PipelineError(f'Missing material {name}.vmt')
            shader,params=read_vmt(vmt,chosen)
            row.update(vmt_path=str(vmt),shader=shader,params=params)
            for key,field in [('$basetexture','converted_png'),('$iris','iris_png')]:
                if key not in params: continue
                vtf=inside(chosen,params[key],'.vtf')
                if not vtf.is_file(): raise PipelineError(f'Missing texture: {vtf}')
                row[field]=str(convert_vtf(vtf,out/'textures',chosen))
            if not row['converted_png']: raise PipelineError(f'Material {name} has no base texture')
        except (OSError,PipelineError) as exc:
            row['warning']=str(exc);warnings.append(str(exc))
        materials.append(row)
        print(f'Material: {name}'+(' (warning)' if row['warning'] else ' ready'),flush=True)
    inputs={mdl,*[p for p in mdl.parent.glob(mdl.stem+'.*') if p.is_file()]}
    for row in materials:
        if row.get('vmt_path'):
            inputs.add(Path(row['vmt_path']))
        for key in ('$basetexture','$iris'):
            if row.get('params',{}).get(key):
                p=inside(chosen,row['params'][key],'.vtf')
                if p.is_file(): inputs.add(p)
    fingerprints=[dict(path=str(p),size=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns) for p in sorted(inputs)]
    return dict(schema_version=1,mdl=str(mdl),source_sha256=hashlib.sha256(mdl.read_bytes()).hexdigest(),input_fingerprints=fingerprints,
        qc_path=str(qc),reference_smd=parts['mesh_sources'][parts['default_meshes'][0]] if parts['default_meshes'] else None,
        materials_root=str(chosen),materials=materials,cdmaterials=cd,eyes=parse_eyes(text),warnings=warnings,
        run_dir=str(out),**parts)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mdl',type=Path,required=True);p.add_argument('--materials-root',type=Path)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--manifest-json',type=Path)
    a=p.parse_args()
    result=run(a.mdl.resolve(),a.materials_root.resolve() if a.materials_root else None,a.out.resolve())
    manifest=a.manifest_json or a.out/'source_manifest.json'
    result['manifest_path']=str(manifest.resolve());write_json(manifest,result)
    print(f'Manifest: {manifest}',flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
