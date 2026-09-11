"""Cancellable Source-to-MMD workflow used by the GUI and command line."""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
import mmd_character_importer_core as forward

ROOT = Path(os.environ.get('MCI_SOURCE_RESOURCE_ROOT') or forward.ROOT)
STAGES = Path(os.environ.get('MCI_SOURCE_STAGE_DIR') or ROOT / 'tools' / 'source_to_mmd')

def _write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def _check(cancel_check):
    if cancel_check and cancel_check():
        raise RuntimeError('Conversion cancelled.')

def _env(run_dir):
    return dict(os.environ, MCI_SOURCE_RESOURCE_ROOT=str(ROOT), MCI_SOURCE_STAGING=str(run_dir/'tool_scratch'),
                PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')

def _run(command, run_dir, log_name, progress, cancel_check, env=None):
    _check(cancel_check)
    log=run_dir/'logs'/log_name
    forward.run_process_streamed([str(x) for x in command],progress=progress,log_path=log,cancel_check=cancel_check,env=env or _env(run_dir))
    _check(cancel_check)

def analyze_source(mdl: Path, materials_root: Path | None=None, output_root: Path | None=None,
                   progress=None, cancel_check=None) -> dict:
    mdl=Path(mdl).resolve()
    if not mdl.is_file() or mdl.suffix.lower()!='.mdl':
        raise ValueError('Select a Source character .mdl file.')
    _check(cancel_check)
    out=Path(output_root or forward.app_local_dir()/'source_to_mmd'/'exports').resolve()
    slug=re.sub(r'[^A-Za-z0-9_-]+','_',mdl.stem).strip('_') or 'model'
    run_dir=out/(slug+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    run_dir.mkdir(parents=True)
    manifest=run_dir/'source_manifest.json'
    command=[sys.executable,STAGES/'decompile_and_extract.py','--mdl',mdl,'--out',run_dir,'--manifest-json',manifest]
    if materials_root:
        command+=['--materials-root',Path(materials_root).resolve()]
    try:
        _run(command,run_dir,'01_source.log',progress,cancel_check)
        result=_read(manifest)
        result['log_path']=str(run_dir/'logs'/'01_source.log')
        _write(manifest,result)
        return result
    except Exception as exc:
        _write(run_dir/'failure.json',{'stage':'source analysis','error':str(exc),'log_path':str(run_dir/'logs'/'01_source.log')})
        raise RuntimeError(f'{exc}\nAnalysis files: {run_dir}') from exc

def validate_selection(manifest, selected):
    available=set(manifest['mesh_names'])
    selected=list(dict.fromkeys(selected))
    if not selected:
        raise ValueError('Select at least one character mesh.')
    if not set(selected)<=available:
        raise ValueError('Selected meshes do not belong to this analysis. Analyze the model again.')
    if not set(manifest.get('mandatory_meshes',[]))<=set(selected):
        raise ValueError('Required character meshes cannot be omitted.')
    for group in manifest.get('mesh_groups',[]):
        n=len(set(group['meshes'])&set(selected))
        if n>1 or (n==0 and not group.get('allow_blank',False)):
            raise ValueError(f"Choose one variant for bodygroup {group['name']}.")
    return selected

def _blender(options, run_dir, progress, cancel_check):
    explicit=options.get('blender_exe') or os.environ.get('MCI_SOURCE_BLENDER')
    if explicit:
        exe=Path(explicit).resolve()
        if not exe.is_file(): raise ValueError(f'Blender executable does not exist: {exe}')
    else:
        exe=forward.reusable_managed_blender_from_state(forward.read_setup_state(),progress)
        if exe is None:
            exe=forward.find_managed_blender(progress,cancel_check=cancel_check)
    profile=Path(options.get('blender_profile') or os.environ.get('MCI_SOURCE_PROFILE') or forward.app_local_dir()/'source_to_mmd'/'blender_profile').resolve()
    env=_env(run_dir)
    for key,name in [('BLENDER_USER_SCRIPTS','scripts'),('BLENDER_USER_CONFIG','config'),('BLENDER_USER_DATAFILES','datafiles')]:
        folder=profile/name;folder.mkdir(parents=True,exist_ok=True);env[key]=str(folder)
    cats=ROOT/'plugins_software'/'Cats-Blender-Plugin-Unofficial4.5.3.2.zip'
    source=ROOT/'plugins_software'/'blender_source_tools_3.4.3.zip'
    setup=STAGES/'blender_setup_addons.py'
    fingerprint=hashlib.sha256(setup.read_bytes()+str(exe).encode()+str(exe.stat().st_mtime_ns).encode()
        +hashlib.sha256(cats.read_bytes()).digest()+hashlib.sha256(source.read_bytes()).digest()).hexdigest()
    marker=profile/'setup.json'
    if not marker.is_file() or _read(marker).get('fingerprint')!=fingerprint:
        _run([exe,'--background','--factory-startup','--python-exit-code','1','--python',setup,'--',
              '--cats-zip',cats,'--source-tools-zip',source],run_dir,'02_setup.log',progress,cancel_check,env)
        _write(marker,{'fingerprint':fingerprint})
    return exe,env

def convert_source(mdl: Path, materials_root: Path | None, output_root: Path, options: dict | None=None,
                   progress=None, stage_callback=None, cancel_check=None) -> dict:
    options=dict(options or {})
    def stage(pct,label):
        _check(cancel_check)
        if stage_callback: stage_callback(pct,label)
        if progress: progress(label)
    stage(0,'Analyze Source character')
    source=Path(mdl).resolve()
    cached=options.get('analysis_manifest')
    if cached:
        manifest=_read(cached)
        if Path(manifest['mdl']).resolve()!=source or manifest['source_sha256']!=hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError('The source model changed. Analyze it again before exporting.')
        for item in manifest.get('input_fingerprints',[]):
            p=Path(item['path'])
            if not p.is_file() or p.stat().st_size!=item['size'] or p.stat().st_mtime_ns!=item['mtime_ns']:
                raise ValueError(f'Source asset changed: {p.name}. Analyze the model again.')
        original_run=Path(manifest['run_dir']).resolve()
        if not Path(cached).resolve().is_relative_to(original_run):
            raise ValueError('Analysis manifest is outside its workspace.')
        # Never reuse an old successful PMX as evidence that this run succeeded.
        # A second export from the same analysis gets fresh stage/output paths.
        run_dir=original_run/('export_'+datetime.now().strftime('%H%M%S')+'_'+uuid.uuid4().hex[:6])
        run_dir.mkdir(parents=True)
    else:
        manifest=analyze_source(source,materials_root,output_root,progress,cancel_check)
        run_dir=Path(manifest['run_dir'])
    selected=validate_selection(manifest,options.get('selected_meshes') or manifest['default_meshes'])
    if options.get('physics'):
        raise ValueError('Automatic secondary physics is not supported yet.')
    manifest_path=Path(manifest['manifest_path'])
    result={'output_dir':str(run_dir),'warnings':list(manifest.get('warnings',[])), 'stages':{},
            'source_manifest':str(manifest_path),'selected_meshes':selected,'log_path':str(run_dir/'conversion.log')}
    stage_name='Blender setup'
    try:
        stage(15,stage_name)
        exe,env=_blender(options,run_dir,progress,cancel_check)
        checkpoints=run_dir/'blend_stages';checkpoints.mkdir(exist_ok=True)
        def blender_step(pct,label,script,args,expected):
            nonlocal stage_name
            stage_name=label;stage(pct,label)
            log_name=f'{pct:02d}_{Path(script).stem}.log'
            _run([exe,'--background','--python-exit-code','1','--python',STAGES/script,'--',*args],
                 run_dir,log_name,progress,cancel_check,env)
            for p in expected:
                if not p.is_file(): raise RuntimeError(f'{label} did not produce {p.name}.')
            result['stages'][label]=[str(p) for p in expected]
        rig=checkpoints/'01_rig.blend';rig_report=run_dir/'rig_report.json'
        rig_args=['--qc',manifest['qc_path'],'--save',rig,'--report-json',rig_report]
        for name in selected: rig_args+=['--keep-mesh',name]
        blender_step(25,'Prepare MMD skeleton','blender_retarget.py',rig_args,[rig,rig_report])
        material=checkpoints/'02_materials.blend';material_report=run_dir/'material_report.json'
        blender_step(45,'Convert materials and eyes','blender_materials.py',
            ['--blend',rig,'--manifest',manifest_path,'--save',material,'--report-json',material_report],[material,material_report])
        flex=checkpoints/'03_expressions.blend';flex_report=run_dir/'expression_report.json'
        flex_args=['--blend',material,'--save',flex,'--report-json',flex_report]
        if options.get('mapping_path'): flex_args+=['--mapping-json',options['mapping_path']]
        blender_step(60,'Build MMD expressions','blender_flexes.py',flex_args,[flex,flex_report])
        pmx=run_dir/(re.sub(r'[^A-Za-z0-9_-]+','_',source.stem)+'.pmx')
        final_blend=run_dir/'mmd_model.blend';export_report=run_dir/'export_report.json'
        blender_step(75,'Export PMX character','blender_finalize_export.py',
            ['--blend',flex,'--pmx-out',pmx,'--model-name',source.stem,'--save-blend',final_blend,'--report-json',export_report],
            [pmx,final_blend,export_report])
        stage_name='Validate exported character'
        stage(90,stage_name)
        validation_report=run_dir/'validation.json'
        _run([sys.executable,STAGES/'validate_pmx.py','--pmx',pmx,'--report',validation_report],
             run_dir,'90_validation.log',progress,cancel_check)
        validation=_read(validation_report)
        if validation.get('errors'):
            raise RuntimeError('PMX validation failed: '+'; '.join(validation['errors']))
        if options.get('motion_path'):
            motion_report=run_dir/'motion_check.json';motion_blend=run_dir/'motion_preview.blend'
            blender_step(95,'Check motion on exported PMX','blender_motion_check.py',
                ['--pmx',pmx,'--motion',Path(options['motion_path']).resolve(),'--report-json',motion_report,'--save-blend',motion_blend],
                [motion_report,motion_blend])
            validation['motion_validation']=_read(motion_report)
            result['motion_blend_path']=str(motion_blend)
            _write(validation_report,validation)
        for report_path in [rig_report,material_report,flex_report,export_report,validation_report]:
            data=_read(report_path)
            result['warnings'].extend(data.get('warnings',[]))
        result.update(pmx_path=str(pmx),blend_path=str(final_blend),report_path=str(run_dir/'conversion_report.json'),
            validation=validation)
        result['warnings']=list(dict.fromkeys(str(x) for x in result['warnings']))
        _write(result['report_path'],result)
        stage(100,'PMX export complete')
        return result
    except Exception as exc:
        _write(run_dir/'failure.json',dict(stage=stage_name,error=str(exc),**result))
        raise RuntimeError(f'{exc}\nConversion files: {run_dir}') from exc
    finally:
        logs=sorted((run_dir/'logs').glob('*.log'))
        (run_dir/'conversion.log').write_text('\n'.join(f'[{p.name}]\n'+p.read_text(encoding='utf-8',errors='replace') for p in logs),encoding='utf-8')

def main():
    import argparse
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mdl',required=True,type=Path);p.add_argument('--materials-root',type=Path)
    p.add_argument('--out',required=True,type=Path);p.add_argument('--blender-exe',type=Path)
    p.add_argument('--blender-profile',type=Path);p.add_argument('--analyze-only',action='store_true')
    p.add_argument('--motion',type=Path,help='Optional VMD to check on the exported PMX in Blender')
    a=p.parse_args()
    if a.analyze_only: result=analyze_source(a.mdl,a.materials_root,a.out,progress=print)
    else: result=convert_source(a.mdl,a.materials_root,a.out,options={'blender_exe':a.blender_exe,'blender_profile':a.blender_profile,'motion_path':a.motion},progress=print)
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__': main()
