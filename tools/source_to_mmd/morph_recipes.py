"""Source flex recipes; independent of Blender for validation.

AU identities are grounded in Valve's decompiled facial controller rules:
AU26 jaw_drop with lips together, AU27 mouth_drop, AU25 part,
AU20 stretcher, AU18 puckerer, AU22 funneler,
AU12 corner_puller, AU4 brow lowerer. Japanese vowel combinations are
editable approximations, not an exact reconstruction of a Source faceposer rig.
"""
from __future__ import annotations
import math


def bilateral(names, action):
    for candidate in (f"{action}R+{action}L", f"{action}L+{action}R", action):
        if candidate in names:
            return {candidate: 1.0}
    if action+"R" in names and action+"L" in names:
        return {action+"R": 1.0, action+"L": 1.0}
    return None


def open_jaw_actions(names, amount):
    """Resolve the Source open-mouth jaw targets over their authored 0–2 range.

    Valve's QC rules crossfade AU27 to AU27Z above jaw_drop=1: the Z
    target is a full shape relative to neutral, not an additive correction.
    AU26 moves the same jaw but keeps the lips together on HL2 faces, so
    it is only a fallback for models without the mouth-drop variant.
    Do not extrapolate a single target when its full-range partner is absent.
    """
    if not math.isfinite(amount) or amount < 0 or amount > 2:
        raise ValueError("Source jaw opening must be between 0 and 2")
    action = next((key for key in ("AU27", "AU26") if bilateral(names, key)), None)
    if action is None:
        return None
    over = max(amount-1, 0) if bilateral(names, action+"Z") else 0
    result = {action: min(amount, 1)-over}
    if over:
        result[action+"Z"] = over
    return {key: value for key, value in result.items() if value}


def source_phoneme_actions(names, *, jaw=0, mouth_drop=0, part=0, pucker=0, funnel=0, stretch=0):
    """Evaluate the neutral, symmetric phoneme subset of Valve's flex rules.

    Part, pucker and funnel suppress one another. Mouth drop controls the
    AU26/AU27 split; it is attenuated when the lips are already opening.
    Jaw and funnel targets crossfade to their authored Z shape above one.
    Smile, bite, presser and asymmetric controllers are neutral here. This
    is an explicit profile for Valve AU rigs, not a generic QC evaluator.
    """
    values = dict(jaw=jaw, mouth_drop=mouth_drop, part=part, pucker=pucker, funnel=funnel, stretch=stretch)
    for name, value in values.items():
        if not math.isfinite(value) or not 0 <= value <= (2 if name in ("jaw", "funnel") else 1):
            raise ValueError(f"Source phoneme controller out of range: {name}")
    au25 = part*(1-pucker*(.5-funnel/6)-funnel/4)
    au18 = pucker*(1-part*(.5-funnel/6)-funnel/4)
    au22 = funnel*(1-part*(.5-pucker/3)-pucker/2)
    denominator = .8*au18+.8*au22+stretch
    au20 = stretch*stretch/denominator*(1-jaw*.5) if denominator else 0
    opening = part+pucker+funnel
    denominator = .5*opening+mouth_drop
    drop = mouth_drop*mouth_drop/denominator if denominator else 0
    actions = {"AU25": au25, "AU18": au18, "AU20": au20}
    def target_range(action, value):
        if not bilateral(names, action):
            return {}
        over = max(value-1, 0) if bilateral(names, action+"Z") else 0
        result = {action: min(value, 1)-over}
        if over:
            result[action+"Z"] = over
        return result
    actions.update(target_range("AU22", au22))
    closed, opened = target_range("AU26", jaw), target_range("AU27", jaw)
    if not opened:
        drop = 0
    if not closed:
        drop = 1
    for targets, amount in ((closed, 1-drop), (opened, drop)):
        for action, value in targets.items():
            actions[action] = actions.get(action, 0)+value*amount
    return {name: value for name, value in actions.items() if value > 1e-9}


def default_recipes(names):
    names = set(names)
    recipes = {}
    def direct(name, weights, category, evidence, approximation=False):
        if all(k in names for k in weights):
            recipes[name] = dict(weights=weights, category=category, evidence=evidence, approximation=approximation)
    if {"upper_right", "upper_left"} <= names:
        direct("まばたき", {"upper_right": 1, "upper_left": 1}, "eye", "QC blink drives both upper eyelid lowerer frames.")
        direct("ウィンク", {"upper_left": 1}, "eye", "Left upper eyelid lowerer; raw lid shape retained.")
        direct("ウィンク右", {"upper_right": 1}, "eye", "Right upper eyelid lowerer; raw lid shape retained.")
    else:
        for alias in ("blink", "Blink", "eyes_closed", "EyesClosed"):
            if alias in names:
                direct("まばたき", {alias: 1}, "eye", "Explicitly named source blink flex.")
                break
    def compose(name, aus, category, evidence=None):
        weights = {}
        for action, scale in aus.items():
            resolved = bilateral(names, action)
            if resolved is None:
                return
            for key, value in resolved.items():
                weights[key] = weights.get(key, 0)+value*scale
        direct(name, weights, category, evidence or "Source AU controller components; editable MMD expression approximation.", True)
    def vowel(name, **controllers):
        compose(name, source_phoneme_actions(names, **controllers), "mouth", "Valve phoneme controller rules attenuate overlapping lip actions and split open/closed-lip jaw targets; controller endpoints approximate a Japanese vowel.")
        if name in recipes:
            recipes[name]["controllers"] = controllers
    vowel("あ", jaw=2, mouth_drop=1, part=.6)
    vowel("い", jaw=.55, mouth_drop=1, part=1, stretch=1)
    vowel("う", jaw=.65, mouth_drop=1, part=.7, pucker=.8)
    vowel("え", jaw=.95, mouth_drop=1, part=1, stretch=.9)
    vowel("お", jaw=1, mouth_drop=1, pucker=.75, funnel=1)
    compose("にこり", {"AU1": .20}, "eyebrow", "Standard MMD にこり animates eyebrows; a gentle inner-brow raise approximates it without changing the mouth.")
    compose("口の微笑み", {"AU12": .75}, "mouth", "Custom mouth smile preserves the Source corner-puller control independently of MMD eyebrow expressions.")
    compose("にやり", {"AU14": .65}, "mouth")
    compose("怒り", {"AU4": .8}, "eyebrow")
    compose("困る", {"AU1": .55, "AU4": .35}, "eyebrow")
    return recipes


def parse_overrides(data):
    if not isinstance(data, dict):
        raise ValueError("Morph mapping must be a JSON object")
    mapping = data.get("morphs", data.get("mapping", data))
    if not isinstance(mapping, dict):
        raise ValueError("Morph mapping must contain an object under 'morphs' or 'mapping'")
    recipes = {}
    for name, value in mapping.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Morph names must be non-empty strings")
        if name.startswith("_"):
            continue
        if value is None:
            recipes[name] = None
            continue
        if isinstance(value, str):
            value = {"weights": {value: 1.0}}
        if not isinstance(value, dict):
            raise ValueError(f"Invalid morph recipe for {name}")
        weights = value.get("weights", value)
        if not isinstance(weights, dict) or not weights:
            raise ValueError(f"Morph {name} requires source weights")
        validated = {}
        for source, weight in weights.items():
            if not isinstance(source, str) or not source.strip() or isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or abs(weight) > 4:
                raise ValueError(f"Morph {name}: weights must be finite numbers between -4 and 4")
            validated[source] = float(weight)
        category = value.get("category", "other")
        if category not in ("eye", "mouth", "eyebrow", "other"):
            raise ValueError(f"Unknown morph category: {category}")
        recipes[name] = dict(weights=validated, category=category, approximation=True, evidence="User mapping override")
    return recipes
