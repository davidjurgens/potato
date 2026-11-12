"""Boot-time checks of a listening test's items.

A trial built from a malformed item silently loses slots (no reference means
no hidden reference and no anchors in MUSHRA, and no slot A in BS.1116), and
a stimulus named like a condition Potato adds would be overwritten by it.
Both are refused when the items load, with the item ids.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from potato.listening.plan import ANCHOR_PREFIX, HIDDEN_REFERENCE, _reference, _stimuli

#: Methods whose trials are built against a reference.
NEEDS_REFERENCE = ("mushra", "bs1116", "dcr")
#: Stimuli each method needs.
MIN_STIMULI = {"mushra": 1, "bs1116": 1, "acr": 1, "dcr": 1, "p835": 1, "ccr": 2, "abx": 2}


def item_problems(scheme: Dict, items: Iterable) -> List[str]:
    method = scheme.get("method", "mushra")
    bad: Dict[str, List[str]] = {}
    for iid, data in items:
        if not isinstance(data, dict):
            continue
        stimuli = _stimuli(scheme, data)
        reasons = []
        reference = _reference(scheme, data)
        if method in NEEDS_REFERENCE and not reference:
            reasons.append(f"no reference (field '{scheme.get('reference_field', 'reference')}')")
        # Anchors are low-passed from the reference with the standard library's
        # wave module, which reads PCM WAV only: a FLAC or MP3 reference booted
        # and then answered 500 for every anchor slot.
        if (method == "mushra" and scheme.get("anchors") and isinstance(reference, str)
                and not reference.split("?", 1)[0].lower().endswith(".wav")):
            reasons.append("a reference that is not a .wav file, but anchors are made from "
                           "a PCM WAV reference (convert it, or remove anchors and add the "
                           "anchors as stimuli)")
        if len(stimuli) < MIN_STIMULI.get(method, 1):
            reasons.append(f"{len(stimuli)} stimuli, needs {MIN_STIMULI.get(method, 1)}")
        taken = [c for c in stimuli if c == HIDDEN_REFERENCE or c.startswith(ANCHOR_PREFIX)]
        if taken:
            reasons.append(f"stimulus named {', '.join(taken)} (names Potato uses for the "
                           "hidden reference and anchors)")
        for r in reasons:
            bad.setdefault(r, []).append(str(iid))
    out = []
    for reason, ids in bad.items():
        more = f" and {len(ids) - 5} more" if len(ids) > 5 else ""
        out.append(f"listening_test '{scheme.get('name')}' ({method}): {reason} in item(s) "
                   f"{', '.join(ids[:5])}{more}")
    return out


def check_items(config: Dict, ism) -> None:
    schemes = [s for s in config.get("annotation_schemes") or []
               if isinstance(s, dict) and s.get("annotation_type") == "listening_test"]
    if not schemes:
        return
    items = []
    for iid in ism.get_instance_ids():
        try:
            item = ism.get_item(iid)
            items.append((iid, item.get_data() if hasattr(item, "get_data") else dict(item)))
        except Exception:
            continue
    problems = [p for s in schemes for p in item_problems(s, items)]
    if problems:
        from potato.server_utils.config_module import ConfigValidationError
        raise ConfigValidationError("; ".join(problems))
