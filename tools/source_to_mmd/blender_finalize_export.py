"""Export an editable MMD model, portable textures, and a validation report."""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path
import bpy
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pmx_bone_order import reorder_bones_parent_first


def configure_materials(meshes):
    for material in {m for o in meshes for m in o.data.materials if m}:
        settings = json.loads(material.get("source_to_mmd_settings", "{}"))
        if not settings:
            continue
        m = material.mmd_material
        m.diffuse_color = (1, 1, 1)
        m.ambient_color = (0.5, 0.5, 0.5)
        m.alpha = settings["alpha"]
        m.specular_color = (settings["specular"],)*3
        m.shininess = settings["shininess"]
        m.is_double_sided = settings["double_sided"]
        m.enabled_toon_edge = False
        m.sphere_texture_type = "0"


def configure_display(root, armature, metadata):
    frames = root.mmd_root.display_item_frames
    frames.clear()
    def frame(japanese, english, special=False):
        item = frames.add()
        item.name, item.name_e, item.is_special = japanese, english, special
        return item
    root_frame = frame("Root", "Root", True)
    face_frame = frame("表情", "Facial", True)
    body = frame("体", "Body")
    arms = frame("腕", "Arms")
    fingers = frame("指", "Fingers")
    legs = frame("足", "Legs and IK")
    extras = frame("その他", "Source bones")
    raw_flexes = frame("Source表情", "Source flexes")
    for bone in armature.data.bones:
        name = bone.name
        if name == "全ての親":
            target = root_frame
        elif name in ("センター", "グルーブ", "上半身", "上半身2", "下半身", "首", "頭", "両目", "左目", "右目"):
            target = body
        elif "指" in name:
            target = fingers
        elif any(s in name for s in ("肩", "腕", "ひじ", "手首", "手捩")):
            target = arms
        elif any(s in name for s in ("足", "ひざ", "つま先")):
            target = legs
        else:
            target = extras
        item = target.data.add()
        item.type, item.name = "BONE", name
    for morph in root.mmd_root.vertex_morphs:
        recipe = metadata.get(morph.name)
        if recipe:
            morph.category = recipe.get("category", "other").upper()
        target = face_frame if recipe or morph.name in ("まばたき", "あ", "い", "う", "え", "お") else raw_flexes
        item = target.data.add()
        item.type, item.name, item.morph_type = "MORPH", morph.name, "vertex_morphs"
    # Empty optional panels obscure the useful controls in PMX editors.
    for index in reversed(range(len(frames))):
        if not frames[index].is_special and not len(frames[index].data):
            frames.remove(index)


def validate_export(path):
    from mmd_tools_local.core import pmx
    with pmx.FileReadStream(str(path)) as stream:
        header = pmx.Header()
        header.load(stream)
        stream.setHeader(header)
        model = pmx.Model()
        model.load(stream)
    if not model.vertices or not model.faces or not model.bones:
        raise RuntimeError("Export produced an empty mesh or skeleton")
    errors, warnings = [], []
    textures = []
    for texture in model.textures:
        filename = Path(texture.path).resolve()
        portable = filename.is_relative_to(path.parent.resolve())
        textures.append(dict(path=str(filename.relative_to(path.parent.resolve())) if portable else str(filename), exists=filename.is_file(), portable=portable))
        if not filename.is_file() or not portable:
            errors.append(f"Texture is missing or outside output folder: {filename}")
    weighted = set()
    for index, vertex in enumerate(model.vertices):
        if not all(math.isfinite(n) for n in vertex.co):
            errors.append(f"Vertex {index} has non-finite coordinates")
            break
        weight = vertex.weight
        if weight.type == 0:
            values = [1.0]
        elif weight.type == 1:
            values = [weight.weights[0], 1-weight.weights[0]]
        elif weight.type in (2, 4):
            values = weight.weights
        else:
            values = [weight.weights.weight, 1-weight.weights.weight]
        if any(not math.isfinite(w) or w < -1e-5 or w > 1.00001 for w in values) or abs(sum(values)-1) > 1e-4:
            errors.append(f"Vertex {index} has invalid skin weights")
            break
        for bone, value in zip(weight.bones, values):
            if value > 0:
                if not 0 <= bone < len(model.bones):
                    errors.append(f"Vertex {index} references missing bone {bone}")
                else:
                    weighted.add(bone)
    for index, bone in enumerate(model.bones):
        current, seen = index, set()
        while current is not None and current >= 0:
            if current >= len(model.bones) or current in seen:
                errors.append(f"Invalid parent hierarchy at {bone.name}")
                break
            seen.add(current)
            current = model.bones[current].parent
        if "捩" in bone.name and index not in weighted:
            warnings.append(f"Twist bone {bone.name} has no direct mesh weights")
    ik = []
    for bone in model.bones:
        if bone.isIK:
            ik.append(dict(name=bone.name, parent=model.bones[bone.parent].name if bone.parent >= 0 else None,
                           target=model.bones[bone.target].name if 0 <= bone.target < len(model.bones) else None,
                           links=[model.bones[x.target].name for x in bone.ik_links if 0 <= x.target < len(model.bones)]))
    report = dict(pmx=str(path), status="failed" if errors else "passed", errors=errors, warnings=warnings,
                  counts={k: len(getattr(model, k)) for k in ("vertices", "faces", "bones", "materials", "textures", "morphs", "display", "rigids", "joints")},
                  textures=textures, ik=ik, morphs=[m.name for m in model.morphs],
                  limitation="Structural validation does not replace motion playback and visual checks in MMD.")
    return report


def run(blend_path, pmx_out, model_name, model_name_e=None, save_blend=None, report_json=None):
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(f"Expected one armature, found {len(armatures)}")
    armature = armatures[0]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    result = bpy.ops.mmd_tools_local.convert_to_mmd_model(scale=1.0, convert_material_nodes=True)
    if "FINISHED" not in result:
        raise RuntimeError("MMD model conversion failed")
    from mmd_tools_local.core.bone import FnBone
    FnBone.apply_additional_transformation(armature)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="OBJECT")
    root = armature.parent
    if root is None or not hasattr(root, "mmd_root"):
        raise RuntimeError("MMD conversion did not create a model root")
    root.name = root.mmd_root.name = model_name
    root.mmd_root.name_e = model_name_e or model_name
    note = bpy.data.texts.new("Source to MMD conversion notes")
    note.write("Experimental Source to MMD conversion. Source shader effects are approximated. Facial expressions may need character-specific refinement. No secondary physics has been generated.")
    root.mmd_root.comment_text = note.name
    configure_materials(meshes)
    metadata = json.loads(bpy.context.scene.get("source_to_mmd_morphs", "{}"))
    configure_display(root, armature, metadata)
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    pmx_out.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.mmd_tools_local.export_pmx(filepath=str(pmx_out), scale=12.5, copy_textures_mode="OVERWRITE", fix_bone_order=True, sort_materials=False)
    if "FINISHED" not in result or not pmx_out.is_file():
        raise RuntimeError("PMX export did not produce a file")
    from mmd_tools_local.core import pmx
    exported_model = pmx.load(str(pmx_out))
    ordering = reorder_bones_parent_first(exported_model)
    if ordering["moved_bones"]:
        pmx.save(str(pmx_out), exported_model)
    report = validate_export(pmx_out)
    report["bone_order"] = ordering
    # The exporter pins the basis shape while collecting vertices. Restore
    # normal shape blending so facial sliders work in the editable checkpoint.
    for mesh in meshes:
        mesh.show_only_shape_key = False
        mesh.active_shape_key_index = 0
    if save_blend:
        save_blend.parent.mkdir(parents=True, exist_ok=True)
        # Images use paths relative to this checkpoint so the whole output
        # directory can be moved to another machine for editing.
        for image in bpy.data.images:
            if image.source == "FILE" and image.filepath:
                absolute = Path(bpy.path.abspath(image.filepath)).resolve()
                if absolute.is_file() and absolute.is_relative_to(pmx_out.parent):
                    image.filepath = bpy.path.relpath(str(absolute), start=str(save_blend.parent))
        # Paths above are already relative to the destination. Blender's
        # default remap would interpret them against the *old* checkpoint.
        bpy.ops.wm.save_as_mainfile(filepath=str(save_blend), relative_remap=False)
        report["blend"] = str(save_blend)
    destination = report_json or pmx_out.with_suffix(".validation.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["errors"]:
        raise RuntimeError("PMX validation failed: " + "; ".join(report["errors"][:5]))
    print(f"Exported and structurally validated {pmx_out}. Report: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blend", type=Path, required=True)
    parser.add_argument("--pmx-out", type=Path, required=True)
    parser.add_argument("--model-name", default="Ported Model")
    parser.add_argument("--model-name-e")
    parser.add_argument("--save-blend", type=Path)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    run(args.blend.resolve(), args.pmx_out.resolve(), args.model_name, args.model_name_e,
        args.save_blend.resolve() if args.save_blend else None, args.report_json.resolve() if args.report_json else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
