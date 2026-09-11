"""Build portable Source material approximations before MMD conversion.

Source's runtime eye shader is baked to a neutral-gaze texture and projected
onto the eye mesh. Alpha masks are interpreted from VMT flags, since an opaque
Source texture can store a specular mask in its alpha channel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_json


def flag(value):
    return str(value).strip().lower() not in ("", "0", "0.0", "false", "none")


def number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_pixels(path):
    image = bpy.data.images.load(str(Path(path).resolve()), check_existing=True)
    width, height = image.size[:]
    if not width or not height:
        raise RuntimeError(f"Cannot read image: {path}")
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(height, width, 4)


def resize(pixels, width, height):
    """Bilinear resampling; coordinates follow Blender's bottom-up pixels."""
    y, x = np.meshgrid(np.linspace(0, pixels.shape[0]-1, height),
                       np.linspace(0, pixels.shape[1]-1, width), indexing="ij")
    x0, y0 = x.astype(int), y.astype(int)
    x1, y1 = np.minimum(x0+1, pixels.shape[1]-1), np.minimum(y0+1, pixels.shape[0]-1)
    fx, fy = (x-x0)[..., None], (y-y0)[..., None]
    return ((pixels[y0, x0]*(1-fx)+pixels[y0, x1]*fx)*(1-fy)
            +(pixels[y1, x0]*(1-fx)+pixels[y1, x1]*fx)*fy).astype(np.float32)


def save_pixels(pixels, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = pixels.shape[:2]
    image = bpy.data.images.new(path.stem, width=width, height=height, alpha=True)
    image.pixels.foreach_set(np.ascontiguousarray(pixels).ravel())
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    return image


def project_eye_uv(meshes, material, eye):
    """Separate eye materials only; front and back get different atlas halves."""
    surfaces = []
    points = []
    for obj in meshes:
        indices = {i for i, m in enumerate(obj.data.materials) if m == material}
        polys = [p for p in obj.data.polygons if p.material_index in indices]
        surfaces.append((obj, polys))
        points.extend(obj.matrix_world @ obj.data.vertices[i].co for p in polys for i in p.vertices)
    if not points:
        raise RuntimeError(f"Eye material {material.name} has no geometry")
    xmin, xmax = min(v.x for v in points), max(v.x for v in points)
    zmin, zmax = min(v.z for v in points), max(v.z for v in points)
    cx, cz = (xmin+xmax)/2, (zmin+zmax)/2
    origin = eye.get("origin_source")
    # The retarget stage normalizes mesh coordinates to meters with Source X/Z
    # retained. Reject an unrelated QC center instead of placing an invisible iris.
    if origin and len(origin) == 3:
        ex, ez = float(origin[0])*0.0254, float(origin[2])*0.0254
        if xmin-(xmax-xmin) <= ex <= xmax+(xmax-xmin) and zmin-(zmax-zmin) <= ez <= zmax+(zmax-zmin):
            cx, cz = ex, ez
    span = max(number(eye.get("diameter"), 0)*0.0254,
               2*max(abs(xmin-cx), abs(xmax-cx), abs(zmin-cz), abs(zmax-cz)), 1e-5)
    for obj, polys in surfaces:
        uv = obj.data.uv_layers.active or obj.data.uv_layers.new(name="UVMap")
        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        for polygon in polys:
            front = (normal_matrix @ polygon.normal).y <= 0
            for loop_id in polygon.loop_indices:
                p = obj.matrix_world @ obj.data.vertices[obj.data.loops[loop_id].vertex_index].co
                u = max(0.001, min(0.999, 0.5+(p.x-cx)/span))
                v = max(0.001, min(0.999, 0.5+(p.z-cz)/span))
                uv.data[loop_id].uv = (u*0.5 if front else 0.75, v if front else 0.5)
    return span


def build_texture(entry, material, meshes, eyes, directory):
    source = entry.get("converted_png")
    if not source or not Path(source).is_file():
        return None, {"warning": "Base texture missing; material kept with neutral color."}
    pixels = load_pixels(source).copy()
    params = {k.lower(): v for k, v in entry.get("params", {}).items()}
    alpha_test, translucent = flag(params.get("$alphatest", "0")), flag(params.get("$translucent", "0"))
    info = {"alpha_mode": "cutout" if alpha_test else "blend" if translucent else "opaque"}
    if alpha_test:
        pixels[:, :, 3] = (pixels[:, :, 3] >= number(params.get("$alphatestreference"), 0.5)).astype(float)
    elif not translucent:
        pixels[:, :, 3] = 1
    iris = entry.get("iris_png")
    if iris and Path(iris).is_file():
        eye = next((e for e in eyes if str(e.get("material", "")).casefold() == entry["material_name"].casefold()), {})
        span = project_eye_uv(meshes, material, eye)
        size = 512
        base = resize(pixels, size, size)
        # QC iris size is in Source units. Without it use a conservative pupil
        # disk and report the estimate, allowing later per-character refinement.
        iris_span = number(eye.get("iris_scale"), 0)*0.0254 or span*0.65
        disk_size = max(8, min(size, round(size*iris_span/span)))
        disk = resize(load_pixels(iris), disk_size, disk_size)
        start = (size-disk_size)//2
        target = base[start:start+disk_size, start:start+disk_size]
        alpha = np.clip(disk[:, :, 3:4], 0, 1)
        target[:, :, :3] = disk[:, :, :3]*alpha + target[:, :, :3]*(1-alpha)
        base[:, :, 3] = 1
        # The atlas right half is plain sclera for any back-facing eye polygons.
        back = np.empty_like(base)
        back[:, :, :] = np.mean(pixels, axis=(0, 1))
        back[:, :, 3] = 1
        pixels = np.concatenate((base, back), axis=1)
        info.update(eye_projection="neutral frontal X/Z projection", iris_source=str(iris),
                    iris_size_source="QC" if eye.get("iris_scale") else "estimated", projection_span_m=span,
                    warning="Eye shader baked at neutral gaze; Source reflections and refraction are approximated.")
    name = hashlib.sha256((entry["material_name"]+str(source)).encode()).hexdigest()[:10]
    image = save_pixels(pixels, directory / f"{Path(source).stem}_{name}.png")
    info["texture"] = str(Path(image.filepath_raw).resolve())
    return image, info


def wire_material(material, image, entry):
    params = {k.lower(): v for k, v in entry.get("params", {}).items()}
    alpha = max(0.0, min(1.0, number(params.get("$alpha"), 1.0)))
    double_sided = flag(params.get("$nocull", "0"))
    eye = bool(entry.get("iris_png")) or "eye" in str(entry.get("shader", "")).lower()
    specular = 0.05 if eye else 0.02
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    bsdf, output = nodes.new("ShaderNodeBsdfPrincipled"), nodes.new("ShaderNodeOutputMaterial")
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = (1, 1, 1, alpha)
    material.specular_color = (specular,)*3
    material.roughness = 0.6
    material.use_backface_culling = not double_sided
    bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1)
    bsdf.inputs["Roughness"].default_value = 0.6
    bsdf.inputs["Alpha"].default_value = alpha
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = specular
    if image:
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
        multiplier = nodes.new("ShaderNodeMath")
        multiplier.operation = "MULTIPLY"
        multiplier.inputs[1].default_value = alpha
        links.new(texture.outputs["Alpha"], multiplier.inputs[0])
        links.new(multiplier.outputs[0], bsdf.inputs["Alpha"])
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    elif hasattr(material, "blend_method"):
        material.blend_method = "HASHED"
    # Applied explicitly after convert_to_mmd_model, whose material conversion
    # reads legacy properties and cannot preserve every node setting.
    material["source_to_mmd_settings"] = json.dumps(dict(alpha=alpha, double_sided=double_sided, specular=specular, shininess=8.0))


def run(blend_path, manifest_path, save_path, report_json=None):
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    manifest = read_json(manifest_path)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    entries = {m["material_name"].casefold(): m for m in manifest.get("materials", [])}
    materials = {o.data.materials[i] for o in meshes
                 for i in {p.material_index for p in o.data.polygons}
                 if i < len(o.data.materials) and o.data.materials[i]}
    report = {"materials": [], "warnings": []}
    directory = save_path.parent.parent / "textures" / "mmd"
    for material in sorted(materials, key=lambda m: m.name):
        entry = entries.get(material.name.casefold())
        if entry is None:
            report["warnings"].append(f"No Source material metadata for {material.name}")
            continue
        image, info = build_texture(entry, material, meshes, manifest.get("eyes", []), directory)
        wire_material(material, image, entry)
        report["materials"].append(dict(name=material.name, **info))
        if info.get("warning"):
            report["warnings"].append(f"{material.name}: {info['warning']}")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    destination = report_json or save_path.with_suffix(".materials.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(report['materials'])} materials. Report: {destination}")


def main():
    args = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("blend", "manifest", "save"):
        parser.add_argument("--"+key, type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    a = parser.parse_args(args)
    run(a.blend.resolve(), a.manifest.resolve(), a.save.resolve(), a.report_json.resolve() if a.report_json else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
