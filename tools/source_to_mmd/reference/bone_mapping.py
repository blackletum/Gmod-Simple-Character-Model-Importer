"""ValveBiped <-> MMD semi-standard bone name mapping.

This is the ground truth for reversing the skeleton-retarget step of
blackletum/Gmod-Simple-Character-Model-Importer (MIT licensed). That project
never hand-rolled its MMD -> Source bone conversion; it drives the
Cats-Blender-Plugin operator `cats_manual.convert_to_valve`. This module
inverts the exact dict that operator uses, so the Source -> MMD direction
starts from verified data instead of a guessed mapping.

Provenance, so it's clear what's verified vs. what's convention:

VALVE_TO_CATS_CANONICAL
    Inverted directly from Cats-Blender-Plugin-Unofficial4.5.3.2.zip
    (plugins_software/ in the reference repo) ->
    Cats-Blender-Plugin-blender-45/tools/armature_manual.py ->
    class ConvertToValveButton (bl_idname 'cats_manual.convert_to_valve'),
    the `valve_translations` dict, ~line 1881. That dict is
    {cats_canonical_name: valvebiped_name}; this module stores the reverse.
    This is exact, not inferred -- it's the literal table the forward
    pipeline runs through blender_fix_mmd_model.py::convert_to_valve().

CATS_CANONICAL_TO_MMD_JP
    CATS' canonical vocabulary ('chest', 'left_leg', ...) and MMD's own
    semi-standard vocabulary aren't the same list. The core torso/limb
    entries here are cross-checked against
    Gmod-Simple-Character-Model-Importer/tools/mmd_character_importer_core.py
    REQUIRED_MMD_SKELETON_BONES (~line 210), which pairs each JP semi-standard
    name with an English gloss -- that table only covers the bones the
    forward tool treats as mandatory, so it doesn't include fingers, toes,
    clavicles, or the second spine segment. Those gaps are filled with
    standard MMD PMX rigging convention (documented across essentially every
    MMD modeling tutorial), not extracted from this specific repo. Flagged
    per-entry below.

What this module deliberately does NOT cover:
    - The MMD-only root chain (mother/center/groove) -- ValveBiped has
      nothing upstream of Pelvis, so there's no bone to rename. This has to
      be synthesized fresh; see ROOT_CHAIN_SPEC.
    - Spine segment count. Source's ValveBiped spine is 4 bones
      (Spine/Spine1/Spine2/Spine4); standard MMD is 2 (upper body / upper
      body 2). That's a collapse, not a rename; see SPINE_COLLAPSE_PLAN.
    - mmd_tools' actual property names for writing this onto a Blender
      armature (mmd_bone.name_j / name_e, or similar). That needs to be
      confirmed against extern_tools/mmd_tools_local/core/pmx/importer.py
      before use. The integration verifies these against the bundled add-on.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# VERIFIED: inverted from Cats-Blender-Plugin's own convert_to_valve dict.
# Key = ValveBiped bone name as it appears on a compiled/decompiled Source
# model. Value = CATS' internal canonical English bone name.
# ---------------------------------------------------------------------------
VALVE_TO_CATS_CANONICAL: dict[str, str] = {
    "ValveBiped.Bip01_Pelvis": "hips",
    "ValveBiped.Bip01_Spine": "spine",
    "ValveBiped.Bip01_Spine1": "chest",
    "ValveBiped.Bip01_Spine2": "upper_chest",
    "ValveBiped.Bip01_Neck1": "neck",
    "ValveBiped.Bip01_Head1": "head",
    # Robustness addition (full audit against mmd_tools_helper's own
    # ValveBiped dictionary): that dictionary lists the source names as
    # plain "Bip01_Neck"/"Bip01_Head", no trailing "1". Alyx's own
    # skeleton uses the "1" variant (confirmed -- she already renames
    # successfully without these two lines), so this isn't fixing
    # anything currently broken for her specifically, but ValveBiped
    # naming isn't perfectly uniform across every Source character, and
    # adding the no-suffix variant costs nothing for models that don't
    # have it while covering ones that use this convention instead.
    "ValveBiped.Bip01_Neck": "neck",
    "ValveBiped.Bip01_Head": "head",
    "ValveBiped.Bip01_L_Thigh": "left_leg",
    "ValveBiped.Bip01_L_Calf": "left_knee",
    "ValveBiped.Bip01_L_Foot": "left_ankle",
    "ValveBiped.Bip01_L_Toe0": "left_toe",
    "ValveBiped.Bip01_R_Thigh": "right_leg",
    "ValveBiped.Bip01_R_Calf": "right_knee",
    "ValveBiped.Bip01_R_Foot": "right_ankle",
    "ValveBiped.Bip01_R_Toe0": "right_toe",
    "ValveBiped.Bip01_L_Clavicle": "left_shoulder",
    "ValveBiped.Bip01_L_UpperArm": "left_arm",
    "ValveBiped.Bip01_L_Forearm": "left_elbow",
    "ValveBiped.Bip01_L_Hand": "left_wrist",
    "ValveBiped.Bip01_R_Clavicle": "right_shoulder",
    "ValveBiped.Bip01_R_UpperArm": "right_arm",
    "ValveBiped.Bip01_R_Forearm": "right_elbow",
    "ValveBiped.Bip01_R_Hand": "right_wrist",
    # Fingers, left. Source thumb joints map to MMD semi-standard 0/1/2.
    "ValveBiped.Bip01_L_Finger4": "pinkie_1_l",
    "ValveBiped.Bip01_L_Finger41": "pinkie_2_l",
    "ValveBiped.Bip01_L_Finger42": "pinkie_3_l",
    "ValveBiped.Bip01_L_Finger3": "ring_1_l",
    "ValveBiped.Bip01_L_Finger31": "ring_2_l",
    "ValveBiped.Bip01_L_Finger32": "ring_3_l",
    "ValveBiped.Bip01_L_Finger2": "middle_1_l",
    "ValveBiped.Bip01_L_Finger21": "middle_2_l",
    "ValveBiped.Bip01_L_Finger22": "middle_3_l",
    "ValveBiped.Bip01_L_Finger1": "index_1_l",
    "ValveBiped.Bip01_L_Finger11": "index_2_l",
    "ValveBiped.Bip01_L_Finger12": "index_3_l",
    "ValveBiped.Bip01_L_Finger0": "thumb_1_l",
    "ValveBiped.Bip01_L_Finger01": "thumb_2_l",
    "ValveBiped.Bip01_L_Finger02": "thumb_3_l",
    # Fingers, right.
    "ValveBiped.Bip01_R_Finger4": "pinkie_1_r",
    "ValveBiped.Bip01_R_Finger41": "pinkie_2_r",
    "ValveBiped.Bip01_R_Finger42": "pinkie_3_r",
    "ValveBiped.Bip01_R_Finger3": "ring_1_r",
    "ValveBiped.Bip01_R_Finger31": "ring_2_r",
    "ValveBiped.Bip01_R_Finger32": "ring_3_r",
    "ValveBiped.Bip01_R_Finger2": "middle_1_r",
    "ValveBiped.Bip01_R_Finger21": "middle_2_r",
    "ValveBiped.Bip01_R_Finger22": "middle_3_r",
    "ValveBiped.Bip01_R_Finger1": "index_1_r",
    "ValveBiped.Bip01_R_Finger11": "index_2_r",
    "ValveBiped.Bip01_R_Finger12": "index_3_r",
    "ValveBiped.Bip01_R_Finger0": "thumb_1_r",
    "ValveBiped.Bip01_R_Finger01": "thumb_2_r",
    "ValveBiped.Bip01_R_Finger02": "thumb_3_r",
}

# Preserve Source's three thumb joints as the semi-standard MMD thumb 0/1/2.
# No thumb weights or joints are collapsed.
THUMB_SEGMENT_COLLAPSE: dict[str, str] = {}

# ---------------------------------------------------------------------------
# CATS canonical name -> (MMD JP name, English gloss).
# "verified" entries are cross-checked against this repo's
# REQUIRED_MMD_SKELETON_BONES table. "convention" entries are standard MMD
# PMX rigging names not present in that table (it only lists mandatory
# bones, not the full humanoid set).
# ---------------------------------------------------------------------------
CATS_CANONICAL_TO_MMD_JP: dict[str, tuple[str, str, str]] = {
    # canonical:      (JP name,        EN gloss,      provenance)
    "hips":            ("\u4e0b\u534a\u8eab",   "lower body",  "verified"),
    "spine":            ("\u4e0a\u534a\u8eab",   "upper body",  "verified"),
    "chest":            ("\u4e0a\u534a\u8eab",   "upper body",  "verified (collapsed, see SPINE_COLLAPSE_PLAN)"),
    "upper_chest":      ("\u4e0a\u534a\u8eab2",  "upper body 2", "convention"),
    "neck":             ("\u9996",       "neck",        "verified"),
    "head":             ("\u982d",       "head",        "verified"),
    "left_leg":         ("\u5de6\u8db3",    "leg L",       "convention"),
    "left_knee":        ("\u5de6\u3072\u3056",   "knee L",      "verified"),
    "left_ankle":       ("\u5de6\u8db3\u9996",   "ankle L",     "verified"),
    "left_toe":         ("\u5de6\u3064\u307e\u5148",  "toe L",       "convention"),
    "right_leg":        ("\u53f3\u8db3",    "leg R",       "verified"),
    "right_knee":       ("\u53f3\u3072\u3056",   "knee R",      "verified"),
    "right_ankle":      ("\u53f3\u8db3\u9996",   "ankle R",     "verified"),
    "right_toe":        ("\u53f3\u3064\u307e\u5148",  "toe R",       "convention"),
    "left_shoulder":    ("\u5de6\u80a9",    "shoulder L",  "verified"),
    "left_arm":         ("\u5de6\u8155",    "arm L",       "verified"),
    "left_elbow":       ("\u5de6\u3072\u3058",   "elbow L",     "verified"),
    "left_wrist":       ("\u5de6\u624b\u9996",   "wrist L",     "verified"),
    "right_shoulder":   ("\u53f3\u80a9",    "shoulderR",   "verified"),
    "right_arm":        ("\u53f3\u8155",    "armR",        "verified"),
    "right_elbow":      ("\u53f3\u3072\u3058",   "elbowR",      "verified"),
    "right_wrist":      ("\u53f3\u624b\u9996",   "wristR",      "verified"),
    # Fingers -- all convention (\u4eb2\u6307=thumb, \u4eba\u6307=index, \u4e2d\u6307=middle, \u85ac\u6307=ring, \u5c0f\u6307=pinky).
    # The trailing segment digit is FULLWIDTH (\uff11\uff12\uff13), not ASCII (123) --
    # confirmed byte-for-byte against a real Miku V4X PMX and a real VPD pose
    # file (both use fullwidth for every finger bone). This file previously
    # used ASCII digits here, which meant no VMD/VPD could ever string-match
    # these bone names -- finger motion silently never applied, for any
    # motion, independent of anything else in the pipeline.
    "thumb_1_l":  ("\u5de6\u89aa\u6307\uff10",  "thumb L 0",  "semi-standard; preserves Source thumb base"),
    "thumb_2_l":  ("\u5de6\u89aa\u6307\uff11",  "thumb L 1",  "convention"),
    "thumb_3_l":  ("\u5de6\u89aa\u6307\uff12",  "thumb L 2",  "convention; Source distal joint preserved"),
    "index_1_l":  ("\u5de6\u4eba\u6307\uff11",  "index L 1",  "convention"),
    "index_2_l":  ("\u5de6\u4eba\u6307\uff12",  "index L 2",  "convention"),
    "index_3_l":  ("\u5de6\u4eba\u6307\uff13",  "index L 3",  "convention"),
    "middle_1_l": ("\u5de6\u4e2d\u6307\uff11",  "middle L 1", "convention"),
    "middle_2_l": ("\u5de6\u4e2d\u6307\uff12",  "middle L 2", "convention"),
    "middle_3_l": ("\u5de6\u4e2d\u6307\uff13",  "middle L 3", "convention"),
    "ring_1_l":   ("\u5de6\u85ac\u6307\uff11",  "ring L 1",   "convention"),
    "ring_2_l":   ("\u5de6\u85ac\u6307\uff12",  "ring L 2",   "convention"),
    "ring_3_l":   ("\u5de6\u85ac\u6307\uff13",  "ring L 3",   "convention"),
    "pinkie_1_l": ("\u5de6\u5c0f\u6307\uff11",  "pinky L 1",  "convention"),
    "pinkie_2_l": ("\u5de6\u5c0f\u6307\uff12",  "pinky L 2",  "convention"),
    "pinkie_3_l": ("\u5de6\u5c0f\u6307\uff13",  "pinky L 3",  "convention"),
    "thumb_1_r":  ("\u53f3\u89aa\u6307\uff10",  "thumb R 0",  "semi-standard; preserves Source thumb base"),
    "thumb_2_r":  ("\u53f3\u89aa\u6307\uff11",  "thumb R 1",  "convention"),
    "thumb_3_r":  ("\u53f3\u89aa\u6307\uff12",  "thumb R 2",  "convention; Source distal joint preserved"),
    "index_1_r":  ("\u53f3\u4eba\u6307\uff11",  "index R 1",  "convention"),
    "index_2_r":  ("\u53f3\u4eba\u6307\uff12",  "index R 2",  "convention"),
    "index_3_r":  ("\u53f3\u4eba\u6307\uff13",  "index R 3",  "convention"),
    "middle_1_r": ("\u53f3\u4e2d\u6307\uff11",  "middle R 1", "convention"),
    "middle_2_r": ("\u53f3\u4e2d\u6307\uff12",  "middle R 2", "convention"),
    "middle_3_r": ("\u53f3\u4e2d\u6307\uff13",  "middle R 3", "convention"),
    "ring_1_r":   ("\u53f3\u85ac\u6307\uff11",  "ring R 1",   "convention"),
    "ring_2_r":   ("\u53f3\u85ac\u6307\uff12",  "ring R 2",   "convention"),
    "ring_3_r":   ("\u53f3\u85ac\u6307\uff13",  "ring R 3",   "convention"),
    "pinkie_1_r": ("\u53f3\u5c0f\u6307\uff11",  "pinky R 1",  "convention"),
    "pinkie_2_r": ("\u53f3\u5c0f\u6307\uff12",  "pinky R 2",  "convention"),
    "pinkie_3_r": ("\u53f3\u5c0f\u6307\uff13",  "pinky R 3",  "convention"),
}

# ---------------------------------------------------------------------------
# Source's ValveBiped spine (4 segments) vs. standard MMD (2 segments).
# Default collapse plan -- not extracted from any file, this is a design
# decision. Revisit once tested against a real decompiled model.
# ---------------------------------------------------------------------------
SPINE_COLLAPSE_PLAN = {
    "description": (
        "ValveBiped.Bip01_Spine and Spine1 merge into MMD's upper body "
        "(joint position taken from Spine1); Spine2 and Spine4 merge into "
        "upper body 2 (joint position taken from Spine2). Vertex group "
        "weights combined (ADD) on merge, matching the merge_vertex_group "
        "pattern already used by blender_fix_mmd_model.py in the forward "
        "tool for its VRM spine merge."
    ),
    "upper_body_sources": ["ValveBiped.Bip01_Spine", "ValveBiped.Bip01_Spine1"],
    "upper_body2_sources": ["ValveBiped.Bip01_Spine2", "ValveBiped.Bip01_Spine4"],
}

# ---------------------------------------------------------------------------
# MMD's root control chain has no ValveBiped counterpart at all -- it must
# be synthesized, not renamed. Standard MMD PMX convention, not from this
# repo. All three are typically zero-weight (no mesh deformation), pure
# animation/IK helpers.
# ---------------------------------------------------------------------------
ROOT_CHAIN_SPEC = {
    "description": (
        "Three non-deforming helper bones sit above the retargeted pelvis, "
        "parented in this order: mother (ground level, i.e. directly below "
        "the pelvis with Z zeroed out) -> center (pelvis height, the bone "
        "most animators key) -> groove (same position as center, a "
        "separate translate-only layer for vertical adjustment). Lower "
        "body / upper body then parent from groove, replacing "
        "ValveBiped.Bip01_Pelvis as the top of the retargeted chain."
    ),
    "chain": [
        {"jp": "\u5168\u3066\u306e\u89aa", "en": "mother", "parent": None, "position": "ground level, below the pelvis"},
        {"jp": "\u30bb\u30f3\u30bf\u30fc", "en": "center", "parent": "mother", "position": "pelvis height"},
        {"jp": "\u30b0\u30eb\u30fc\u30d6", "en": "groove", "parent": "center", "position": "same as center"},
    ],
}


def valvebiped_to_mmd(bone_name: str) -> tuple[str, str] | None:
    """Look up the (MMD JP name, English gloss) for a ValveBiped bone name.

    Returns None for bones with no entry (extra/custom bones on a given
    model) -- callers should leave those bones under their original name
    rather than fail, since PMX tolerates non-semi-standard bones fine.
    """
    canonical = VALVE_TO_CATS_CANONICAL.get(bone_name)
    if canonical is None:
        return None
    entry = CATS_CANONICAL_TO_MMD_JP.get(canonical)
    if entry is None:
        return None
    jp, en, _provenance = entry
    return jp, en


# ---------------------------------------------------------------------------
# Leg/toe IK uses the bundled mmd_tools PMX exporter's native Blender IK
# support. Retarget aligns knee tails to ankle heads and ankle tails to toe
# heads, then sets use_tail=True with chain_count=2/1. Knee local X is aligned
# to the anatomical left-right axis; positive X bends backward in Blender.
# The PMX exporter converts these local limits to PMX coordinates. Leg IK is
# under the mother/root so center/pelvis motion does not drag planted feet.
LEG_IK_SPEC = {
    "description": (
        "Per side: a leg-IK bone (positioned at the ankle, parented to "
        "mother/root) driving the thigh+knee via an IK constraint placed "
        "on the knee bone; a toe-IK bone (positioned at the toe, "
        "parented to the leg-IK bone) driving the ankle-to-toe segment "
        "via an IK constraint placed on the ankle bone."
    ),
    "sides": [
        {
            "side": "L",
            "leg_ik_jp": "\u5de6\u8db3\uff29\uff2b",
            "leg_ik_en": "leg IK_L",
            "toe_ik_jp": "\u5de6\u3064\u307e\u5148\uff29\uff2b",
            "toe_ik_en": "toe IK_L",
            "thigh_jp": "\u5de6\u8db3",
            "knee_jp": "\u5de6\u3072\u3056",
            "ankle_jp": "\u5de6\u8db3\u9996",
            "toe_jp": "\u5de6\u3064\u307e\u5148",
            "lower_body_jp": "\u4e0b\u534a\u8eab",
        },
        {
            "side": "R",
            "leg_ik_jp": "\u53f3\u8db3\uff29\uff2b",
            "leg_ik_en": "leg IK_R",
            "toe_ik_jp": "\u53f3\u3064\u307e\u5148\uff29\uff2b",
            "toe_ik_en": "toe IK_R",
            "thigh_jp": "\u53f3\u8db3",
            "knee_jp": "\u53f3\u3072\u3056",
            "ankle_jp": "\u53f3\u8db3\u9996",
            "toe_jp": "\u53f3\u3064\u307e\u5148",
            "lower_body_jp": "\u4e0b\u534a\u8eab",
        },
    ],
}
