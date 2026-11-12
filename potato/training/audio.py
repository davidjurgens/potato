"""Training targets for the audio answers group 4 trains on.

- ``transcript`` (``speech_transcript``): the turns an annotator corrected.
  The saved answer lists only the touched turns, by ``index`` into the
  item's transcript, with the corrected text; the timing and the ASR's own
  text are on the item. An untouched turn is not a label: nobody said it
  was right.
- ``segments`` (``tiered_annotation``): speaker turns, from the tier that
  holds them. Tiered answers are in milliseconds; targets are in seconds.
- ``acoustic`` (``spectrogram_annotation``): time-frequency boxes, read
  with ``acoustic_tables.decode_boxes``.

Standard library only: the bundle is built in the server process.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["transcript_turns", "transcript_target", "speaker_turns", "acoustic_target",
           "AUDIO_KINDS"]

#: Kinds whose target is built here rather than by ``dataset._target_for``.
AUDIO_KINDS = ("transcript", "segments", "acoustic")


def _blob(value_map: Any) -> Any:
    from potato.training.vision import blob
    return blob(value_map)


def transcript_turns(scheme: Dict[str, Any], item_data: Dict[str, Any],
                     base_dir: Optional[str] = None) -> Dict[str, Any]:
    """``{"audio", "turns": [{index, start, end, speaker, text}]}`` for the
    item, read the way the page reads it: through the transcript binding,
    with the scheme's ``turns_key``, ``speaker_key`` and ``text_key``, and a
    transcript file named by the item read from *base_dir* (the task
    directory). Indexes are the page's, so a correction's ``index`` names
    the turn the annotator saw."""
    field = scheme.get("segments_key", "segments")
    audio_key = scheme.get("audio_key", "audio")
    audio = item_data.get(audio_key)
    try:
        from potato.server_utils.transcripts.binding import build_index, collect_bindings
        bound = build_index(item_data, collect_bindings({"annotation_schemes": [scheme]}),
                            base_dir=base_dir).get(field)
    except Exception:  # noqa: BLE001 - unreadable transcript: the raw rows, as the page does
        bound = None
    if bound and bound.get("turns"):
        audio = audio or bound.get("audio")
        source = bound["turns"]
    else:
        raw = item_data.get(field)
        source = raw if isinstance(raw, list) else []
    turns: List[Dict[str, Any]] = []
    for index, turn in enumerate(source):
        turn = turn if isinstance(turn, dict) else {"text": str(turn)}
        try:
            start = float(turn.get("start") or 0)
            end = float(turn.get("end") or turn.get("start") or 0)
        except (TypeError, ValueError):
            start = end = 0.0
        turns.append({"index": index, "start": start, "end": end,
                      "speaker": str(turn.get("speaker") or turn.get("role") or ""),
                      "text": str(turn.get("text") or turn.get("content") or "")})
    raw = item_data.get(field)
    from potato.server_utils.transcripts.loader import is_transcript_path
    if is_transcript_path(raw) and len(turns) == 1 and turns[0]["text"] == raw.strip():
        # A transcript file that could not be read (missing, or outside the
        # task directory) comes back as one turn holding its path; the page
        # shows it, but it is no turn of speech. A one-line transcript
        # written inline is a turn.
        turns[0]["unread"] = True
    return {"audio": audio, "turns": turns}


def transcript_target(scheme: Dict[str, Any], value_map: Any,
                      item_data: Dict[str, Any],
                      base_dir: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """``[{index, start, end, text, asr_text}]`` for each corrected turn."""
    answer = _blob(value_map)
    if not isinstance(answer, list):
        return None
    turns = {t["index"]: t for t in transcript_turns(scheme, item_data, base_dir)["turns"]}
    out = []
    for entry in answer:
        if not isinstance(entry, dict):
            continue
        correction = str(entry.get("correction") or "").strip()
        try:
            index = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        turn = turns.get(index)
        if not correction or turn is None or turn["end"] <= turn["start"]:
            continue
        out.append({"index": index, "start": turn["start"], "end": turn["end"],
                    "text": correction, "asr_text": turn["text"]})
    return sorted(out, key=lambda t: t["index"]) or None


def _speaker_tier(tiers: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """``(tier, why not)``: the tier that holds speaker turns, or None and
    the reason. A tier named ``speaker`` or ``speakers``; else the one tier
    whose name says speaker (not ``non-speaker``); else the only tier with
    labels. Never a guess between two."""
    names = [str(n) for n in tiers]
    exact = [n for n in names if n.strip().lower() in ("speaker", "speakers")]
    if len(exact) == 1:
        return exact[0], ""
    named = [n for n in names if re.search(r"speaker", n, re.I)
             and not re.match(r"\s*non[-_ ]?speaker", n, re.I)]
    if len(named) == 1:
        return named[0], ""
    if len(named) > 1 or len(exact) > 1:
        return None, ("tiers %s all look like speaker tiers; name one 'speaker'"
                      % ", ".join(repr(n) for n in (exact or named)))
    labelled = [n for n in names if any(isinstance(e, dict) and e.get("label") not in (None, "")
                                        for e in tiers.get(n) or [])]
    if len(labelled) == 1:
        return labelled[0], ""
    if labelled:
        return None, ("no tier is named for speakers among %s; name the speaker tier "
                      "'speaker'" % ", ".join(repr(n) for n in labelled))
    return None, "no tier has a labelled turn"


def speaker_turns(value_map: Any, tier: Optional[str] = None,
                  problems: Optional[List[str]] = None) -> Optional[List[Dict[str, Any]]]:
    """``[{start, end, speaker, tier}]`` in seconds from a tiered answer: the
    annotations on *tier*, or on the tier :func:`_speaker_tier` picks. The
    label is the speaker. Why no tier could be picked goes to *problems*."""
    answer = _blob(value_map)
    if not isinstance(answer, dict):
        return None
    tiers = answer.get("annotations") or {}
    if not isinstance(tiers, dict):
        return None
    if tier is None:
        tier, why = _speaker_tier(tiers)
        if tier is None:
            if why and problems is not None:
                problems.append(why)
            return None
    out = []
    for entry in tiers.get(tier) or []:
        if not isinstance(entry, dict) or entry.get("label") in (None, ""):
            continue
        try:
            start = float(entry["start_time"]) / 1000.0
            end = float(entry["end_time"]) / 1000.0
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            out.append({"start": start, "end": end, "speaker": str(entry["label"]),
                        "tier": tier})
    if not out and problems is not None:
        problems.append("the %r tier has no labelled turn" % tier)
    return sorted(out, key=lambda t: (t["start"], t["end"])) or None


def acoustic_target(value_map: Any) -> Optional[List[Dict[str, Any]]]:
    """The labelled time-frequency boxes of a spectrogram answer, in seconds
    and hertz; a time-only box has ``low_hz`` and ``high_hz`` of None."""
    from potato.server_utils.acoustic_tables import decode_boxes
    values = value_map.values() if isinstance(value_map, dict) else [value_map]
    for value in values:
        try:
            boxes = decode_boxes(value)
        except Exception:  # noqa: BLE001
            continue
        boxes = [{k: b.get(k) for k in ("start_s", "end_s", "low_hz", "high_hz", "label")}
                 for b in boxes or [] if isinstance(b, dict) and b.get("label") not in (None, "")]
        if boxes:
            return boxes
    return None
