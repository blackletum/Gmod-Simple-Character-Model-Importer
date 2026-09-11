"""Utilities shared by the isolated Source-to-MMD subprocess stages."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

class PipelineError(RuntimeError):
    pass

def project_root() -> Path:
    return Path(os.environ.get('MCI_SOURCE_RESOURCE_ROOT') or Path(__file__).resolve().parents[2])

def hidden_subprocess_kwargs() -> dict:
    if os.name != 'nt':
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {'startupinfo': si, 'creationflags': subprocess.CREATE_NO_WINDOW}

def path_is_ascii(path) -> bool:
    return str(path).isascii()

def safe_name(value: str, fallback='model') -> str:
    return re.sub(r'[^A-Za-z0-9_-]+', '_', str(value)).strip('_')[:80] or fallback

def ascii_staging_root() -> Path:
    p = Path(os.environ.get('MCI_SOURCE_STAGING') or (Path(tempfile.gettempdir()) / 'MMDCharacterImporter' / 'source_staging'))
    if not str(p).isascii():
        p = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Temp' / 'MMDCharacterImporter' / 'source_staging'
    p.mkdir(parents=True, exist_ok=True)
    return p

def find_external_tool(*relative_candidates, env_var=None):
    override = os.environ.get(env_var, '') if env_var else ''
    if override and Path(override).is_file():
        return Path(override)
    for candidate in relative_candidates:
        p = project_root() / 'external_tools' / candidate
        if p.is_file():
            return p
    return None

def run_tool(command, *, cwd=None, description=''):
    env = None
    if Path(command[0]).name.lower().startswith('crowbar'):
        # .NET resolves SpecialFolder.ApplicationData from this child profile.
        # Keep Crowbar's mandatory startup preferences with our scratch data,
        # including when the host account's roaming profile is inaccessible.
        profile = ascii_staging_root() / 'crowbar_profile'
        roaming = profile / 'AppData' / 'Roaming'
        local = profile / 'AppData' / 'Local'
        roaming.mkdir(parents=True, exist_ok=True)
        local.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, USERPROFILE=str(profile), APPDATA=str(roaming), LOCALAPPDATA=str(local))
    # Child tools inherit this flag: an external crash should reach our log,
    # not block cancellation behind a native Windows fault dialog.
    previous_error_mode = None
    if os.name == 'nt':
        import ctypes
        previous_error_mode = ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    try:
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', **hidden_subprocess_kwargs())
    except OSError as exc:
        raise PipelineError(f'{description}: could not launch tool: {exc}') from exc
    finally:
        if previous_error_mode is not None:
            ctypes.windll.kernel32.SetErrorMode(previous_error_mode)
    if result.returncode:
        raise PipelineError(f'{description} failed ({result.returncode}):\n{result.stdout}')
    return result

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
