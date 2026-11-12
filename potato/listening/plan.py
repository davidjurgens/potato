"""
The trial plan for one participant on one item.

A plan lists the slots the page shows (``s1``, ``s2``, ...; ``A`` / ``B`` /
``X`` for ABX) and, server-side only, which condition and file each slot is.
It is a pure function of the scheme, the item and the seed, so the audio
route, the plan route and the export all derive the same mapping without
storing it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from potato.server_utils.presentation_order import order_seed, permutation

METHODS = ("mushra", "bs1116", "acr", "dcr", "ccr", "abx", "p835")

#: Condition names Potato adds; a data file's own conditions may not use them.
HIDDEN_REFERENCE = "hidden_reference"
ANCHOR_PREFIX = "anchor_lp"

#: Category labels, highest first, as the recommendations word them.
SCALES: Dict[str, List[str]] = {
    "acr": ["Excellent", "Good", "Fair", "Poor", "Bad"],
    "dcr": ["Degradation is inaudible", "Degradation is audible but not annoying",
            "Degradation is slightly annoying", "Degradation is annoying",
            "Degradation is very annoying"],
    "ccr": ["Much better", "Better", "Slightly better", "About the same",
            "Slightly worse", "Worse", "Much worse"],
    "sig": ["Not distorted", "Slightly distorted", "Somewhat distorted",
            "Fairly distorted", "Very distorted"],
    "bak": ["Not noticeable", "Slightly noticeable", "Noticeable but not intrusive",
            "Somewhat intrusive", "Very intrusive"],
    "ovrl": ["Excellent", "Good", "Fair", "Poor", "Bad"],
    "bs1116": ["Imperceptible", "Perceptible, but not annoying", "Slightly annoying",
               "Annoying", "Very annoying"],
    "mushra": ["Excellent", "Good", "Fair", "Poor", "Bad"],
}


def _stimuli(scheme: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, str]:
    raw = item.get(scheme.get("stimuli_field", "stimuli"))
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v}
    if isinstance(raw, list):
        out = {}
        for i, entry in enumerate(raw):
            if isinstance(entry, dict):
                key = str(entry.get("id") or entry.get("condition") or f"c{i + 1}")
                url = entry.get("url") or entry.get("src") or entry.get("file")
            else:
                key, url = f"c{i + 1}", entry
            if url:
                out[key] = str(url)
        return out
    if isinstance(raw, str) and raw:
        # One clip per item (ACR, DCR, P.835): its condition is named by a
        # field, so ratings can be grouped by codec, system or noise level.
        condition = item.get(scheme.get("condition_field", "condition"))
        return {str(condition) if condition not in (None, "") else "stimulus": raw}
    return {}


def _reference(scheme: Dict[str, Any], item: Dict[str, Any]) -> Optional[str]:
    value = item.get(scheme.get("reference_field", "reference"))
    return str(value) if value else None


def anchor_cutoffs(scheme: Dict[str, Any]) -> List[int]:
    anchors = scheme.get("anchors")
    if anchors is None:
        return []
    return [int(a) for a in anchors]


def build_plan(scheme: Dict[str, Any], item: Dict[str, Any], user_id: str,
               instance_id: str) -> Dict[str, Any]:
    """{"method", "reference": src|None, "slots": [{"slot", "condition", "source"}], ...}

    ``source`` is a data-file reference (``/media/x.wav``, a URL) or, for a
    generated anchor, ``{"anchor_hz": n, "of": reference}``.
    """
    method = scheme.get("method", "mushra")
    stimuli = _stimuli(scheme, item)
    reference = _reference(scheme, item)
    seed = order_seed(user_id, str(instance_id), scheme.get("name", ""))
    plan: Dict[str, Any] = {"method": method, "reference": None, "slots": []}

    if method == "mushra":
        conditions = dict(stimuli)
        if reference and scheme.get("hidden_reference", True):
            conditions[HIDDEN_REFERENCE] = reference
        for hz in anchor_cutoffs(scheme):
            if reference:
                conditions[f"{ANCHOR_PREFIX}{hz}"] = {"anchor_hz": hz, "of": reference}
        names = sorted(conditions)
        order = permutation(len(names), seed)
        plan["reference"] = reference
        plan["slots"] = [{"slot": f"s{i + 1}", "condition": names[j], "source": conditions[names[j]]}
                         for i, j in enumerate(order)]
    elif method == "bs1116":
        # Reference, then A and B: one is the hidden reference, the other the
        # condition under test.
        name, src = next(iter(sorted(stimuli.items())), (None, None))
        pair = [(name, src), (HIDDEN_REFERENCE, reference)]
        if permutation(2, seed)[0] == 1:
            pair.reverse()
        plan["reference"] = reference
        plan["slots"] = [{"slot": s, "condition": c, "source": u}
                         for s, (c, u) in zip(("A", "B"), pair)]
    elif method in ("acr", "p835"):
        name, src = next(iter(sorted(stimuli.items())), (None, None))
        plan["slots"] = [{"slot": "s1", "condition": name, "source": src}]
    elif method == "dcr":
        name, src = next(iter(sorted(stimuli.items())), (None, None))
        plan["reference"] = reference
        plan["slots"] = [{"slot": "s1", "condition": name, "source": src}]
    elif method == "ccr":
        names = sorted(stimuli)[:2]
        order = permutation(len(names), seed)
        plan["slots"] = [{"slot": f"s{i + 1}", "condition": names[j], "source": stimuli[names[j]]}
                         for i, j in enumerate(order)]
    elif method == "abx":
        names = sorted(stimuli)[:2]
        x_is = "A" if permutation(2, seed)[0] == 0 else "B"
        slots = [{"slot": "A", "condition": names[0] if names else None,
                  "source": stimuli.get(names[0]) if names else None},
                 {"slot": "B", "condition": names[1] if len(names) > 1 else None,
                  "source": stimuli.get(names[1]) if len(names) > 1 else None}]
        x = dict(slots[0] if x_is == "A" else slots[1])
        x["slot"] = "X"
        plan["slots"] = slots + [x]
        plan["x_is"] = x_is
    return plan


def slot_source(plan: Dict[str, Any], slot: str):
    if slot == "ref":
        return plan.get("reference")
    for s in plan["slots"]:
        if s["slot"] == slot:
            return s["source"]
    return None


def client_view(plan: Dict[str, Any], scheme: Dict[str, Any], audio_url) -> Dict[str, Any]:
    """What the page may see: slot names and opaque audio URLs, no conditions."""
    method = plan["method"]
    view = {
        "method": method,
        "reference": audio_url("ref") if plan.get("reference") else None,
        "slots": [{"slot": s["slot"], "url": audio_url(s["slot"])} for s in plan["slots"]
                  if s.get("source")],
        "loop": bool(scheme.get("loop", method in ("mushra", "bs1116"))),
        "require_full_playback": bool(scheme.get(
            "require_full_playback", method in ("acr", "dcr", "ccr", "p835", "abx"))),
        "require_all_played": bool(scheme.get("require_all_played", True)),
        "require_one_at_100": bool(scheme.get("require_one_at_100", method == "mushra")),
        "allow_replay": bool(scheme.get("allow_replay", True)),
    }
    if method == "p835":
        view["scales"] = {k: SCALES[k] for k in ("sig", "bak", "ovrl")}
    elif method in SCALES:
        view["scale"] = scheme.get("scale_labels") or SCALES[method]
    return view
