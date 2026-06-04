# MMD Character Importer Build Repo

This repository is the GitHub-uploadable source/build package for MMD Character
Importer. It contains the source files, small vendored tools/plugins, required
reference subsets, and scripts needed to run from source or build the Windows
executable.

Large generated outputs and the large Blender fallback zip are intentionally
excluded from git. Download the heavyweight build asset before running or
building.

## Requirements

- Windows 10/11, 64-bit.
- Python 3.12, 64-bit.
- PowerShell.
- Garry's Mod installed through Steam for final StudioMDL/gmad compile and
  package steps.

The app manages its own portable Blender 4.5 setup under:

```text
%LOCALAPPDATA%\MMDCharacterImporter
```

VTFCmd and the older VC runtime DLLs needed by VTFCmd/PyOpenGL are included in
`external_tools`.

## One-Time Source Setup

Open PowerShell in this repo folder, then create and activate a virtual
environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install runtime/build dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
```

Download and verify the excluded heavyweight asset:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_build_assets.ps1
```

This writes `blender-4.5.10-windows-x64.zip` at repo root. The file is ignored
by git because it is larger than GitHub's normal file-size limit.

To verify an already downloaded asset without downloading again:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_build_assets.ps1 -VerifyOnly
```

## Run Without Building

After the one-time source setup, launch the GUI directly from Python:

```powershell
python .\tools\mmd_character_importer_gui.py
```

Optional: verify Blender/add-on setup before launching the GUI:

```powershell
python .\tools\mmd_character_importer_core.py setup
```

The main screen can auto-detect Garry's Mod in common Steam locations. If it
does not, browse to the Garry's Mod install folder or to:

```text
...\GarrysMod\bin\studiomdl.exe
```

## Build The Program

Build the default one-file executable:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe
```

The output is written to `release\MMDCharacterImporter.exe`.

Build a portable folder instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe -OneDir
```

Portable output:

```text
release\MMDCharacterImporter_portable\MMDCharacterImporter.exe
release\MMDCharacterImporter_portable\_internal
release\MMDCharacterImporter_portable\dependency_manifest.json
release\MMDCharacterImporter_portable\RUN_ME.txt
```

Useful build options:

```powershell
# Change executable name
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe -Name MyImporter

# Keep console window for debugging
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe -Console

# Use UPX if installed
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe -UseUPX
```

## Run A Built Release

After building, launch:

```powershell
.\release\MMDCharacterImporter.exe
```

For a portable-folder build, keep `_internal` beside the executable and launch:

```powershell
.\release\MMDCharacterImporter_portable\MMDCharacterImporter.exe
```

## Repository Maintenance

- `blender-4.5.10-windows-x64.zip` is required by the build script but is excluded from git because it is larger than GitHub's normal file limit.
- `external_tools\vtfcmd` and the required VC runtime DLLs are included directly because they are needed for icon and VTF generation.
- Garry's Mod is still required on the machine that runs the importer because StudioMDL and gmad are distributed with Garry's Mod.
- The source project updates this folder by running `tools\sync_github_upload.ps1`; do not manually copy files when refreshing this repo.
- Generated `build`, `dist`, and `release` folders are ignored by git.

The original project README is copied to `docs\MMDCharacterImporter_README.md`.