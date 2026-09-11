"""Run inside Blender (background mode) to make sure the two add-ons this
pipeline needs are installed and enabled:

  - Blender Source Tools (SMD/QC importer)
  - mmd_tools (PMX exporter) -- extracted from inside the CATS plugin zip
    at extern_tools/mmd_tools_local/, same as the reference repo does. We
    don't need CATS' own features (its MMD->Valve conversion has no
    reverse direction to call), just the mmd_tools copy it carries.

Invoke as:
    blender --background --factory-startup --python tools/blender_setup_addons.py -- \\
        --cats-zip external_tools/blender_addons/Cats-Blender-Plugin-Unofficial4.5.3.2.zip \\
        --source-tools-zip external_tools/blender_addons/blender_source_tools_3.4.3.zip

Adapted from Gmod-Simple-Character-Model-Importer's tools/blender_setup_addons.py
(MIT) -- same install/enable calls (verified against Blender's actual addon
API by reading that file, not guessed), trimmed to only the two add-ons this
project needs instead of all six the forward tool installs.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import eprint  # noqa: E402


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cats-zip", type=Path, required=True)
    parser.add_argument("--source-tools-zip", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args(argv)


def _operator_exists(id_path: str) -> bool:
    """Whether a Blender operator is actually registered.

    bpy.ops attribute access is lazy: bpy.ops.import_scene.smd resolves
    to a callable wrapper regardless of whether Source Tools is
    installed, and the real "does this exist" check only happens inside
    __call__ -- confirmed the hard way, from a real pipeline run against
    a genuinely fresh Blender install: this file's previous version used
    hasattr(bpy.ops, "import_scene") and hasattr(bpy.ops.import_scene,
    "smd"), both of which reported True on an addon-free install, right
    before the actual import call failed with "operator ... could not
    be found". See DESIGN.md.

    poll() goes through the same registered-operator lookup a real call
    does, without executing anything, so it fails the same way __call__
    does for a genuinely unregistered operator -- and that's the
    failure this function watches for. If poll() runs and returns
    False for a normal context reason (e.g. "no active object"), that
    still means the operator DOES exist, just isn't valid to run right
    now -- only an AttributeError from the lookup itself means "not
    registered"."""
    category, _, name = id_path.partition(".")
    try:
        getattr(getattr(bpy.ops, category), name).poll()
        return True
    except AttributeError:
        return False
    except Exception:
        # poll() executed and raised for some other (context-related)
        # reason -- the operator lookup itself succeeded, so it exists.
        return True


def safe_extract_destination(target: Path, member: str, rel: str) -> Path:
    """Resolve an archive member's output path, rejecting zip-slip
    escapes. Same safety check the reference repo applies -- a zip
    entry with '../..' in its name should never be trusted to extract
    wherever it points."""
    rel_path = Path(rel.replace("\\", "/"))
    if rel_path.is_absolute() or rel_path.drive:
        raise RuntimeError(f"unsafe absolute archive member path: {member}")
    destination = (target / rel_path).resolve()
    if not destination.is_relative_to(target.resolve()):
        raise RuntimeError(f"archive member escapes the install directory: {member}")
    return destination


def install_mmd_tools_from_cats(zip_path: Path) -> None:
    print(f"Extracting mmd_tools_local from {zip_path.name}")
    addon_root = Path(bpy.utils.user_resource("SCRIPTS", path="addons", create=True))
    target = addon_root / "mmd_tools_local"
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(zip_path) as archive:
        prefix = ""
        for member in archive.namelist():
            if member.endswith("extern_tools/mmd_tools_local/__init__.py"):
                prefix = member[: -len("__init__.py")]
                break
        if not prefix:
            raise RuntimeError("mmd_tools_local package not found inside the CATS archive -- did the zip layout change?")
        for member in archive.namelist():
            if member.endswith("/") or not member.startswith(prefix):
                continue
            rel = member[len(prefix) :]
            if not rel:
                continue
            destination = safe_extract_destination(target, member, rel)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as handle:
                shutil.copyfileobj(source, handle)
    print(f"Extracted mmd_tools_local to {target}")


def enable_module(module_name: str) -> bool:
    import addon_utils

    try:
        addon_utils.enable(module_name, default_set=True, persistent=True)
        return True
    except Exception as exc:  # noqa: BLE001
        eprint(f"  {module_name}: {exc}")
        return False


def ensure_mmd_tools(cats_zip: Path, check_only: bool) -> None:
    if check_only:
        if not _operator_exists("mmd_tools_local.export_pmx"):
            raise RuntimeError("mmd_tools is not available.")
        print("mmd_tools already available.")
        return
    # Always (re-)install rather than gating on an "already there" check
    # -- install_mmd_tools_from_cats() already removes any existing copy
    # before extracting, so this is idempotent and cheap (a few hundred
    # KB), and it sidesteps needing a reliable pre-check at all.
    install_mmd_tools_from_cats(cats_zip)
    enable_module("mmd_tools_local")
    if not _operator_exists("mmd_tools_local.export_pmx"):
        raise RuntimeError("mmd_tools_local was installed but its export operator still isn't registered.")
    print("mmd_tools ready (module: mmd_tools_local).")


def ensure_source_tools(zip_path: Path, check_only: bool) -> None:
    if check_only:
        if not _operator_exists("import_scene.smd"):
            raise RuntimeError("Blender Source Tools is not available.")
        print("Blender Source Tools already available.")
        return
    try:
        bpy.ops.preferences.addon_install(filepath=str(zip_path), overwrite=True, enable_on_install=True)
    except Exception as exc:  # noqa: BLE001
        eprint(f"  addon_install raised: {exc}")
    if not _operator_exists("import_scene.smd"):
        # Some Blender versions want an explicit enable even with
        # enable_on_install=True if the module name doesn't match the
        # zip's top folder name exactly.
        for candidate in ("io_scene_valvesource", "blender_source_tools"):
            if enable_module(candidate):
                break
    if not _operator_exists("import_scene.smd"):
        raise RuntimeError("Blender Source Tools was installed but import_scene.smd still isn't registered.")
    print("Blender Source Tools ready.")


def main() -> int:
    args = parse_args()
    try:
        ensure_source_tools(args.source_tools_zip, args.check_only)
        ensure_mmd_tools(args.cats_zip, args.check_only)
    except Exception as exc:  # noqa: BLE001
        eprint(f"error: {exc}")
        return 1
    try:
        bpy.ops.wm.save_userpref()
    except Exception:  # noqa: BLE001
        pass  # not fatal -- addons are enabled for this session either way
    print("Add-on setup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
