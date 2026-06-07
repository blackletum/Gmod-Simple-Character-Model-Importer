# MMD Character Importer

MMD Character Importer is a Windows desktop workflow tool for converting MMD
`.pmx` character models into Garry's Mod-ready Source model addons. The GUI
drives a Blender-based pipeline that imports the model, repairs the skeleton,
sorts bones/materials/bodygroups/flexes/collision, exports Source files,
generates icons and QC files, compiles with Garry's Mod StudioMDL, and packages
the final addon.

## Requirements

These requirements apply when running from source, building the executable, or
running a packaged release:

- Windows 10/11, 64-bit.
- Garry's Mod installed through Steam for the final QC compile/package step.
- PowerShell.

Python is only required when running from source or building:

- Python 3.12 is recommended.
- Python 3.10 or newer, 64-bit, is the minimum supported source-run version.

The app manages its own portable Blender 4.5 setup. On first use it downloads
the latest Blender 4.5 Windows x64 zip from Blender's official download index,
or falls back to the bundled `blender-4.5.10-windows-x64.zip` in this folder.
It extracts Blender and writes workspaces under:

```text
%LOCALAPPDATA%\MMDCharacterImporter
```

VTFCmd is bundled in `external_tools\vtfcmd`, so a separate VTFEdit/VTFCmd
install is not required for source runs or packaged EXE builds. The package also
includes the older Visual C++ runtime DLLs needed by bundled VTFCmd/PyOpenGL
components.

## Run The Program Without Building

### Option A: Run A Packaged Release

If `release\GmodSimpleMMDCharacterImporter.exe` already exists, no Python environment is
required. Launch it directly:

```powershell
.\release\GmodSimpleMMDCharacterImporter.exe
```

For the portable-folder build, keep `_internal` beside the executable and run:

```powershell
.\release\GmodSimpleMMDCharacterImporter_portable\GmodSimpleMMDCharacterImporter.exe
```

The first launch may take longer while the app prepares its local Blender setup
under `%LOCALAPPDATA%\MMDCharacterImporter`.

### Option B: Run From Source

Open a terminal in this folder. If your prompt looks like `C:\path>`, you are
using Command Prompt. If it starts with `PS`, you are using PowerShell.

```cmd
cd "C:\path\to\mmd_character_model_importer\MMD Character Importer"
```

Create the virtual environment first, then activate it as a separate command.
Do not append the activation script path to `python -m venv`.

Command Prompt:

```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
```

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks activation, run this once in that same PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

If your prompt shows both `(.venv)` and `(base)`, deactivate conda before
building to avoid conda/venv detection warnings:

```powershell
conda deactivate
.\.venv\Scripts\Activate.ps1
```

Install the Python packages used by the GUI and helper steps:

```powershell
python -m pip install PySide6 numpy Pillow requests PyOpenGL
```

Launch the GUI:

```powershell
python tools\mmd_character_importer_gui.py
```

Optional: run the Blender/add-on setup check before using the GUI:

```powershell
python tools\mmd_character_importer_core.py setup
```

The main screen can auto-detect Garry's Mod in common Steam locations. If it
does not, browse to the Garry's Mod install folder or directly to:

```text
...\GarrysMod\bin\studiomdl.exe
```

If you need to override the bundled VTFCmd, set `VTFCMD` to the full path of a
different `VTFCmd.exe`.

## Build Repo / GitHub Upload Folder

This project can generate a separate source/build folder named `Github Upload`
for upload as its own GitHub repository:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\sync_github_upload.ps1
```

The generated folder contains only the build source, small vendored tools,
required reference subsets, build instructions, and a download script for large
assets. It excludes generated `build`, `dist`, and `release` outputs and does
not commit `blender-4.5.10-windows-x64.zip`, because that file is larger than
GitHub's normal file-size limit. In the generated repo, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_build_assets.ps1
```

before running from source or building.

## Build The Program On Windows

The Windows build uses PyInstaller through:

```text
tools\build_mmd_character_importer_exe.ps1
```

Install runtime and build dependencies in the same virtual environment.

Command Prompt:

```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install PySide6 numpy Pillow requests PyOpenGL pyinstaller
```

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install PySide6 numpy Pillow requests PyOpenGL pyinstaller
```

If your prompt shows both `(.venv)` and `(base)`, run `conda deactivate`, then
activate `.venv` again before building.

Build the default one-file executable:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe
```

Build output:

```text
release\GmodSimpleMMDCharacterImporter.exe
release\GmodSimpleMMDCharacterImporter_dependency_manifest.json
release\GmodSimpleMMDCharacterImporter_RUN_ME.txt
```

The build also uses `build\` and `dist\` as PyInstaller intermediate folders.
These folders are generated outputs and can be deleted after a successful build.

### Portable Folder Build

Use `-OneDir` to make a portable folder instead of a single executable:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe -OneDir
```

Build output:

```text
release\GmodSimpleMMDCharacterImporter_portable\GmodSimpleMMDCharacterImporter.exe
release\GmodSimpleMMDCharacterImporter_portable\_internal
release\GmodSimpleMMDCharacterImporter_portable\dependency_manifest.json
release\GmodSimpleMMDCharacterImporter_portable\RUN_ME.txt
```

Do not move or delete the `_internal` folder from a portable build.

### Build Options

```powershell
# Change the application/executable name
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe -Name MyImporter

# Keep a console window for debugging logs
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe -Console

# Use UPX compression if UPX is installed and available
powershell -ExecutionPolicy Bypass -File .\tools\build_mmd_character_importer_exe.ps1 -Python .\.venv\Scripts\python.exe -UseUPX
```

The build script bundles the `tools`, `plugins_software`, `external_tools`,
selected `reference` assets, `steps.txt`, translation templates, this README,
the bundled Blender zip, and bundled VTFCmd. Required package data is validated
up front; the build fails instead of producing an incomplete release.

## Troubleshooting

### PySide6 Is Missing

Install the runtime packages again:

```powershell
python -m pip install PySide6 numpy Pillow requests PyOpenGL
```

### PyInstaller Is Missing

Install PyInstaller in the active environment:

```powershell
python -m pip install pyinstaller
```

### PowerShell Blocks The Build Script

Use the documented command with `-ExecutionPolicy Bypass`, or run PowerShell as
the same user that owns the project folder.

### Blender Setup Fails

Keep `blender-4.5.10-windows-x64.zip` in this folder for offline fallback
setup. The importer requires Blender 4.5.x because the bundled Blender add-ons
are verified against that version.

### Garry's Mod Compile Fails

Browse to the Garry's Mod folder or set `STUDIOMDL` to the full path of
`studiomdl.exe`. Step 14 also uses `gmad.exe` from the Garry's Mod install when
packaging a `.gma`.

### VTF Files Are Not Generated

Confirm `external_tools\vtfcmd\VTFCmd.exe` exists before building. Packaged
builds include that folder and Steps 13/14 use it after an explicit `VTFCMD`
override and before `PATH` or common VTFEdit install locations.
