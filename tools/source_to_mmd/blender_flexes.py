"""Preserve original Source flexes and add usable MMD facial controls.

--mapping-json accepts {"morphs": {"あ": {"weights": {"AU26R+AU26L": .8},
"category": "mouth"}}}. A null recipe disables that generated control.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_json
from morph_recipes import default_recipes, parse_overrides


def load_flex_name_hints():
    path = Path(__file__).resolve().parent / "reference" / "flex_name_dictionary.json"
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "flex_name_dictionary.json"
    if not path.exists():
        return {}
    hints = {}
    for target, source in read_json(path).get("mapping", {}).items():
        if isinstance(source, str):
            hints.setdefault(source, target)
    return hints


def coordinates(key):
    array = np.empty(len(key.data)*3, dtype=np.float32)
    key.data.foreach_get("co", array)
    return array


def run(blend_path, save_path, mapping_json=None, report_json=None):
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    overrides = parse_overrides(read_json(mapping_json)) if mapping_json else {}
    hints = load_flex_name_hints()
    report = {"meshes": [], "generated": [], "warnings": [], "original_flexes_preserved": True}
    metadata = {}
    used_overrides = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        blocks = obj.data.shape_keys.key_blocks
        original = {key.name: key for key in blocks if key != blocks[0]}
        recipes = default_recipes(original)
        for source, target in hints.items():
            if source in original and source != target:
                recipes.setdefault(target, dict(weights={source: 1.0}, category="other", approximation=True, evidence="Alias from the forward tool's flex dictionary."))
        recipes.update(overrides)
        base = coordinates(blocks[0])
        created = []
        for name, recipe in recipes.items():
            if recipe is None or name in original:
                continue
            missing = [key for key in recipe["weights"] if key not in original]
            if missing:
                continue
            delta = np.zeros_like(base)
            for source, weight in recipe["weights"].items():
                key = original[source]
                relative = key.relative_key or blocks[0]
                delta += (coordinates(key)-coordinates(relative))*weight
            if np.max(np.abs(delta), initial=0) < 1e-8:
                report["warnings"].append(f"{obj.name}: {name} has no displacement and was skipped.")
                continue
            target = obj.shape_key_add(name=name, from_mix=False)
            target.relative_key = blocks[0]
            target.data.foreach_set("co", base+delta)
            target.value = 0
            target.slider_min, target.slider_max = 0, 1
            metadata[name] = recipe
            if name in overrides:
                used_overrides.add(name)
            created.append(name)
            displacement = np.linalg.norm(delta.reshape((-1, 3)), axis=1)
            report["generated"].append(dict(mesh=obj.name, name=name, **recipe,
                moved_vertices=int(np.count_nonzero(displacement > 1e-7)),
                max_displacement=float(displacement.max(initial=0))))
        # Checkpoints and exports begin neutral, independent of previous preview sliders.
        for key in blocks:
            key.value = 0
        report["meshes"].append(dict(name=obj.name, source_flex_count=len(original), generated=created))
    for name, recipe in overrides.items():
        if recipe and name not in used_overrides:
            report["warnings"].append(f"Override {name} was not generated: required source flexes were absent or the target already exists.")
    report["warnings"].append("Vowels use Source open-mouth jaw targets and lip shapes. They remain approximations; inspect and refine them for each character.")
    bpy.context.scene["source_to_mmd_morphs"] = json.dumps(metadata, ensure_ascii=False)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    destination = report_json or save_path.with_suffix(".flexes.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Added {len(report['generated'])} MMD controls while preserving Source flexes. Report: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blend", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True)
    parser.add_argument("--mapping-json", type=Path)
    parser.add_argument("--report-json", type=Path)
    a = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    run(a.blend.resolve(), a.save.resolve(), a.mapping_json, a.report_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
