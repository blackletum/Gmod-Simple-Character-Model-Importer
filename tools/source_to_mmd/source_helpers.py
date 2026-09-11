"""Replace known ValveBiped procedural skinning with portable linear weights.

This is an explicitly reported approximation, not a general VRD interpreter.
Only helpers identified in the model's own VRD with the expected driver chain
are eligible. Unrecognized helpers, attachments and secondary bones survive.
Run before bone renaming, rest-pose rebinding and anatomical twist splitting.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re


@dataclass(frozen=True)
class HelperRule:
    source: str
    targets: tuple[tuple[str, float], ...]
    method: str


def _name(value: str) -> str:
    return value.removeprefix("ValveBiped.")


def read_vrd(text: str) -> dict[str, dict]:
    result, current = {}, None
    for original in text.splitlines():
        line = original.split("//", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if fields[0].lower() == "<helper>":
            current = None
            if len(fields) == 5:
                name, parent, reference, driver = map(_name, fields[1:])
                # Duplicate definitions are ambiguous: never simplify them.
                if name in result:
                    result[name]["ambiguous"] = True
                else:
                    current = dict(parent=parent, reference=reference,
                                   driver=driver, triggers=[], ambiguous=False)
                    result[name] = current
        elif fields[0].lower() == "<trigger>" and current is not None:
            try:
                trigger = tuple(map(float, fields[1:]))
                if len(trigger) != 10 or not all(map(math.isfinite, trigger)):
                    current["ambiguous"] = True
                else:
                    current["triggers"].append(trigger)
            except ValueError:
                current["ambiguous"] = True
        elif fields[0].lower() == "<aimconstraint>":
            current = None
    return result


def _half_bend(triggers: list[tuple]) -> bool:
    """Recognize the measured Source 0/90 -> 0/45 hinge response only."""
    if len(triggers) != 2:
        return False
    a, b = triggers
    driving = [b[i] - a[i] for i in range(1, 4)]
    response = [b[i] - a[i] for i in range(4, 7)]
    driver_axis = max(range(3), key=lambda i: abs(driving[i]))
    return (abs(abs(driving[driver_axis]) - 90) < .02
            and abs(response[driver_axis] / driving[driver_axis] - .5) < .001
            and all(abs(driving[i]) < .02 and abs(response[i]) < .02
                    for i in range(3) if i != driver_axis)
            and all(abs(a[i] - b[i]) < .02 for i in range(7, 10)))


def plan_helper_transfers(vrd_text: str, bone_parents: dict[str, str | None]):
    """Return qualified rules and explanations for every preserved VRD helper."""
    definitions = read_vrd(vrd_text)
    by_short = {}
    for actual in bone_parents:
        by_short.setdefault(_name(actual), []).append(actual)
    rules, preserved = [], []
    for short, definition in definitions.items():
        matches = by_short.get(short, [])
        match = re.fullmatch(r"Bip01_([LR])_(Shoulder|Bicep|Ulna|Wrist|Elbow|Knee|Shin|Ankle|Quadricep)", short)
        if not match or len(matches) != 1 or definition["ambiguous"]:
            preserved.append(dict(name=short, reason="Unknown, missing or ambiguous helper definition"))
            continue
        side, kind = match.groups()
        prefix = f"Bip01_{side}_"
        expected = {
            "Shoulder": ("UpperArm", "Clavicle", "UpperArm"),
            "Bicep": ("UpperArm", "Clavicle", "UpperArm"),
            "Ulna": ("Forearm", "Forearm", "Hand"),
            "Wrist": ("Forearm", "Forearm", "Hand"),
            "Elbow": ("UpperArm", "UpperArm", "Forearm"),
            "Knee": ("Thigh", "Thigh", "Calf"),
            "Shin": ("Calf", "Calf", "Foot"),
            "Ankle": ("Calf", "Calf", "Foot"),
            "Quadricep": ("Thigh", "Thigh", "Calf"),
        }[kind]
        actual = matches[0]
        signature = tuple(definition[key] for key in ("parent", "reference", "driver"))
        expected = tuple(prefix + suffix for suffix in expected)
        if (signature != expected or _name(bone_parents[actual] or "") != expected[0]
                or any(len(by_short.get(name, [])) != 1 for name in expected)
                or not definition["triggers"]):
            preserved.append(dict(name=actual, reason="Procedural driver chain does not match the known ValveBiped pattern"))
            continue
        if kind in ("Elbow", "Knee"):
            if not _half_bend(definition["triggers"]):
                preserved.append(dict(name=actual, reason="Hinge response is not the verified 90-degree to 45-degree pattern"))
                continue
            targets = ((by_short[expected[0]][0], .5), (by_short[expected[2]][0], .5))
            method = "Linear half-bend approximation of verified VRD hinge response"
        elif kind in ("Shin", "Ankle", "Quadricep"):
            if len(definition["triggers"]) != 1:
                preserved.append(dict(name=actual, reason="Helper has a variable corrective response"))
                continue
            targets = ((by_short[expected[0]][0], 1.),)
            method = "Constant local helper: equivalent parent skinning"
        else:
            targets = ((by_short[expected[0]][0], 1.),)
            method = "Anatomical weights participate in the subsequent spatial MMD twist gradient"
        rules.append(HelperRule(actual, targets, method))
    return rules, preserved


def transfer_vertex_weights(weights: dict[str, float], rules: list[HelperRule]) -> dict[str, float]:
    """Pure weight transformation, preserving existing destination influences."""
    result = dict(weights)
    for rule in rules:
        weight = result.pop(rule.source, 0.)
        if not weight:
            continue
        for target, fraction in rule.targets:
            result[target] = result.get(target, 0.) + weight * fraction
    return result


def vrd_from_qc(qc_path: Path) -> Path | None:
    text = qc_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'^\s*\$proceduralbones\s+(?:"([^"]+)"|(\S+))', text, re.I | re.M)
    if not match:
        return None
    candidate = (qc_path.parent / (match.group(1) or match.group(2))).resolve()
    if not candidate.is_relative_to(qc_path.parent.resolve()) or not candidate.is_file():
        return None
    return candidate


def redistribute_source_helpers(armature, meshes, qc_path: Path, preserve_helpers=()) -> dict:
    """Blender adapter; geometry and all shape-key coordinates are untouched."""
    vrd = vrd_from_qc(qc_path)
    report = dict(method="Verified ValveBiped helper weight approximation", vrd_path=str(vrd) if vrd else None,
                  transfers=[], preserved=[], mesh_weight_error_max=0., warnings=[])
    if vrd is None:
        report["warnings"].append("No readable QC-referenced VRD: procedural helper weights were preserved.")
        return report
    parents = {bone.name: bone.parent.name if bone.parent else None for bone in armature.data.bones}
    rules, report["preserved"] = plan_helper_transfers(vrd.read_text(encoding="utf-8", errors="replace"), parents)
    rules = [rule for rule in rules if rule.source not in preserve_helpers]
    report["append_rotation_helpers"] = list(preserve_helpers)
    for mesh in meshes:
        before_sums = [sum(group.weight for group in vertex.groups) for vertex in mesh.data.vertices]
        for rule in rules:
            source = mesh.vertex_groups.get(rule.source)
            if source is None:
                continue
            source_index = source.index
            vertices = [(vertex.index, next((group.weight for group in vertex.groups if group.group == source_index), 0.))
                        for vertex in mesh.data.vertices]
            vertices = [(index, weight) for index, weight in vertices if weight > 0]
            for target_name, fraction in rule.targets:
                target = mesh.vertex_groups.get(target_name) or mesh.vertex_groups.new(name=target_name)
                for index, weight in vertices:
                    target.add([index], weight * fraction, "ADD")
            mesh.vertex_groups.remove(source)
            report["transfers"].append(dict(mesh=mesh.name, source=rule.source,
                targets=dict(rule.targets), method=rule.method, weighted_vertices=len(vertices),
                total_weight=sum(weight for _, weight in vertices)))
        after_sums = [sum(group.weight for group in vertex.groups) for vertex in mesh.data.vertices]
        error = max((abs(a - b) for a, b in zip(before_sums, after_sums)), default=0.)
        report["mesh_weight_error_max"] = max(report["mesh_weight_error_max"], error)
        if error > 1e-5:
            raise RuntimeError(f"Helper weight conversion changed total weights on {mesh.name}: {error}")
    if report["transfers"]:
        report["warnings"].append("Known Source arm and joint helpers use portable linear skinning approximations; nonlinear VRD muscle corrections are not reproduced exactly.")
    if report["preserved"]:
        report["warnings"].append("Unrecognized or complex Source procedural helpers were preserved with their original weights; their procedural response curves remain unsupported.")
    return report
