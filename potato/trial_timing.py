"""
Timed trials on the annotation page (``trial_timing``).

Turns each annotation item into a trial: an optional fixation, the stimulus
for a set time, a response window with a deadline, and keys mapped to labels,
with the reaction time measured in the browser from the frame the stimulus
appeared.

.. code-block:: yaml

    trial_timing:
      enabled: true
      fixation_ms: 500
      stimulus_duration_ms: 200      # omit to keep the stimulus up until the response
      trial_duration_ms: 2000        # omit for no deadline
      iti_ms: 500
      response:
        schema: decision             # a radio scheme
        keys: {f: word, j: nonword}  # key -> label name
      item_overrides:                # per-item timing from item fields
        stimulus_duration_ms: soa_ms
      disable_back_navigation: true

Word-by-word presentation (self-paced reading, RSVP, the maze task) is a
``presentation`` block; the item's text is shown one region at a time and
each region's reading time is recorded:

.. code-block:: yaml

    trial_timing:
      enabled: true
      fixation_ms: 500
      presentation:
        mode: moving_window          # moving_window | centered | cumulative | maze
        field: sentence              # item field (default: item_properties.text_key)
        region_separator: "|"        # optional: regions instead of words
        advance_key: space
        question_field: question     # optional per-item comprehension question
        # maze only:
        distractor_field: distractors   # one distractor per region
        maze_keys: {left: e, right: i}
        on_error: stop               # stop | redo
      response:                      # the comprehension or judgment question
        schema: answer
        keys: {f: "yes", j: "no"}

With ``question_field``, an item without a question ends after the last
region (outcome ``completed``); without it, every item asks the response
scheme.

Precision: onset is known to the display frame (about 17 ms at 60 Hz); the
keyboard and display add latency the browser cannot see; browsers that coarsen
timers for privacy (``privacy.resistFingerprinting``) round to tens of
milliseconds. Every record carries the measured frame interval and timer
resolution, so analysts can see what each participant's browser could
deliver. For auditory or frame-critical paradigms use a ``type: jspsych``
phase instead.

The browser reports the record; the server checks it against what it knows.
A reaction time longer than the time the item was on the server's clock, a
timeout claimed before the deadline could have passed, a record for an item
the server never served, or a key and label that do not match the
configuration, is flagged. A timeout with a timing flag does not excuse the
required answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TIMING_KEYS = ("fixation_ms", "stimulus_duration_ms", "trial_duration_ms", "iti_ms")
CONFIG_KEYS = {"enabled", *TIMING_KEYS, "fixation_symbol", "response", "item_overrides",
               "disable_back_navigation", "show_response_options", "presentation"}
PRESENTATION_MODES = ("moving_window", "centered", "cumulative", "maze")
PRESENTATION_KEYS = {"mode", "field", "region_separator", "advance_key", "question_field",
                     "distractor_field", "maze_keys", "on_error", "mask_char"}
#: Most regions one item may have (a long passage word by word).
MAX_REGIONS = 400
#: The maze's first word has no real competitor (Boyce et al., 2020).
MAZE_FIRST_DISTRACTOR = "x-x-x"
RESPONSE_KEYS = {"schema", "keys", "allow_mouse"}
RESPONSE_TYPES = ("radio", "likert")

#: Allowed fields in a record from the browser, and their types.
_NUMBER_FIELDS = (
    "rt_ms", "onset_epoch_ms", "fixation_ms_actual", "stimulus_ms_actual",
    "iti_actual_ms", "frame_ms", "timer_resolution_ms", "early_keys",
    "attempt", "reloads",
)
_STRING_FIELDS = ("outcome", "key", "label")
_BOOL_FIELDS = ("tab_hidden", "fullscreen_at_onset")
OUTCOMES = ("response", "timeout", "completed")

#: Slack between the browser's and the server's clocks: the save request's
#: own latency, plus the render-to-onset gap the server cannot see.
SERVER_CLOCK_TOLERANCE_MS = 250


def trial_config(config: dict) -> Optional[Dict[str, Any]]:
    block = (config or {}).get("trial_timing")
    if not isinstance(block, dict) or not block.get("enabled"):
        return None
    return block


def _response_scheme(config: dict, name: str) -> Optional[dict]:
    for scheme in config.get("annotation_schemes") or []:
        if isinstance(scheme, dict) and scheme.get("name") == name:
            return scheme
    return None


def _label_names(scheme: dict) -> List[str]:
    from potato.server_utils.presentation_order import label_names
    if scheme.get("annotation_type") == "likert":
        size = int(scheme.get("size") or 0)
        return [str(i) for i in range(1, size + 1)]
    return [str(n) for n in label_names(scheme)]


def validate_trial_timing_config(config_data: Dict[str, Any]) -> None:
    from potato.server_utils.config_module import ConfigValidationError
    block = config_data.get("trial_timing")
    if block is None:
        return
    if not isinstance(block, dict):
        raise ConfigValidationError("trial_timing must be a mapping")
    unknown = set(block) - CONFIG_KEYS
    if unknown:
        raise ConfigValidationError(
            f"trial_timing has unknown key(s): {', '.join(sorted(unknown))}")
    for key in TIMING_KEYS:
        v = block.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0
                              or v > 600000):
            raise ConfigValidationError(
                f"trial_timing.{key} must be a whole number of milliseconds (0-600000)")
    sd, td = block.get("stimulus_duration_ms"), block.get("trial_duration_ms")
    if sd == 0:
        raise ConfigValidationError(
            "trial_timing.stimulus_duration_ms is 0; omit it to keep the stimulus up")
    if td == 0:
        raise ConfigValidationError(
            "trial_timing.trial_duration_ms is 0; omit it for no deadline")
    if not block.get("enabled"):
        return
    presentation = block.get("presentation")
    taken_keys = set()
    if presentation is not None:
        taken_keys = _validate_presentation(presentation)
        timed = [k for k in ("trial_duration_ms", "stimulus_duration_ms") if block.get(k)]
        if timed:
            # On the config logger, which `potato validate` collects into its report.
            logging.getLogger("potato.server_utils.config_module").warning(
                "trial_timing: %s %s to the question after the reading, not to "
                           "the reading itself, and an item with no question has no deadline",
                           " and ".join(timed), "applies" if len(timed) == 1 else "apply")
    response = block.get("response")
    if presentation is not None and response is None:
        # Reading only: nothing to answer, so nothing else may be on the page.
        others = [s.get("name") for s in config_data.get("annotation_schemes") or []
                  if isinstance(s, dict) and s.get("annotation_type") != "pure_display"]
        if others:
            raise ConfigValidationError(
                "trial_timing.presentation with no response: the timed page asks no "
                f"question, so {', '.join(map(str, others))} could never be answered. Add "
                "trial_timing.response (a comprehension question) or make them pure_display")
        return
    if not isinstance(response, dict) or not response.get("schema"):
        raise ConfigValidationError(
            "trial_timing.response.schema must name the scheme that records the answer")
    unknown = set(response) - RESPONSE_KEYS
    if unknown:
        raise ConfigValidationError(
            f"trial_timing.response has unknown key(s): {', '.join(sorted(unknown))}")
    scheme = _response_scheme(config_data, response["schema"])
    if scheme is None:
        raise ConfigValidationError(
            f"trial_timing.response.schema is '{response['schema']}', which is not in "
            "annotation_schemes")
    if scheme.get("annotation_type") not in RESPONSE_TYPES:
        raise ConfigValidationError(
            f"trial_timing.response.schema must be one of {', '.join(RESPONSE_TYPES)}; "
            f"'{scheme['name']}' is {scheme.get('annotation_type')}")
    keys = response.get("keys")
    allow_mouse = response.get("allow_mouse", False)
    if not isinstance(allow_mouse, bool):
        raise ConfigValidationError("trial_timing.response.allow_mouse must be true or false")
    if not keys and not allow_mouse:
        raise ConfigValidationError(
            "trial_timing.response needs keys (key -> label) or allow_mouse: true")
    if keys is not None:
        if not isinstance(keys, dict) or not keys:
            raise ConfigValidationError("trial_timing.response.keys must map keys to labels")
        labels = _label_names(scheme)
        for key, label in keys.items():
            single = isinstance(key, str) and (len(key) == 1 or key == "space")
            if not single:
                raise ConfigValidationError(
                    f"trial_timing.response.keys: '{key}' must be one character "
                    "(or 'space'). YAML reads bare y/n/yes/no as booleans; quote them.")
            if str(label) not in labels:
                raise ConfigValidationError(
                    f"trial_timing.response.keys maps '{key}' to '{label}', which is not a "
                    f"label of '{scheme['name']}' ({', '.join(labels)})")
        if len(set(map(str, keys.values()))) != len(keys):
            raise ConfigValidationError("trial_timing.response.keys maps two keys to one label")
        clash = {(" " if k == "space" else str(k).lower()) for k in keys} & taken_keys
        if clash:
            raise ConfigValidationError(
                f"trial_timing.response.keys uses {', '.join(sorted(clash))}, which "
                "trial_timing.presentation uses to advance or choose")
    # A timed page owns the keyboard and hides the forms, so a second
    # question on it can never be answered properly: keys meant for a text
    # box are taken as the response, or the form is hidden. Display-only
    # schemes are fine.
    others = [s.get("name") for s in config_data.get("annotation_schemes") or []
              if isinstance(s, dict) and s.get("name") != scheme["name"]
              and s.get("annotation_type") != "pure_display"]
    if others:
        raise ConfigValidationError(
            f"trial_timing: the timed page can hold only its response scheme "
            f"('{scheme['name']}'); remove or move {', '.join(map(str, others))} "
            "(a poststudy page can ask them afterwards)")
    overrides = block.get("item_overrides") or {}
    if not isinstance(overrides, dict) or set(overrides) - set(TIMING_KEYS):
        raise ConfigValidationError(
            f"trial_timing.item_overrides keys must be among {', '.join(TIMING_KEYS)}")
    for flag in ("disable_back_navigation", "show_response_options"):
        if flag in block and not isinstance(block[flag], bool):
            raise ConfigValidationError(f"trial_timing.{flag} must be true or false")
    pocket = config_data.get("pocket")
    if isinstance(pocket, dict) and pocket.get("enabled"):
        logger.warning("trial_timing is enabled with pocket mode: phones and tablets are "
                       "sent to /pocket, which does not run timed trials.")


def _single_key(value) -> Optional[str]:
    if value == "space" or value == " ":
        return " "
    if isinstance(value, str) and len(value) == 1:
        return value.lower()
    return None


def _validate_presentation(p: Any) -> set:
    """Check trial_timing.presentation; return the keys it takes."""
    from potato.server_utils.config_module import ConfigValidationError
    where = "trial_timing.presentation"
    if not isinstance(p, dict):
        raise ConfigValidationError(f"{where} must be a mapping")
    unknown = set(p) - PRESENTATION_KEYS
    if unknown:
        raise ConfigValidationError(f"{where} has unknown key(s): {', '.join(sorted(unknown))}")
    mode = p.get("mode", "moving_window")
    if mode not in PRESENTATION_MODES:
        raise ConfigValidationError(f"{where}.mode must be one of {', '.join(PRESENTATION_MODES)}")
    for key in ("field", "question_field", "distractor_field"):
        if key in p and not (isinstance(p[key], str) and p[key]):
            raise ConfigValidationError(f"{where}.{key} must be the name of an item field")
    sep = p.get("region_separator")
    if sep is not None and not (isinstance(sep, str) and 1 <= len(sep) <= 3 and sep.strip()):
        raise ConfigValidationError(f"{where}.region_separator must be 1-3 characters, such as |")
    mask = p.get("mask_char", "-")
    if not (isinstance(mask, str) and len(mask) == 1):
        raise ConfigValidationError(f"{where}.mask_char must be one character")
    if mode == "maze":
        if not p.get("distractor_field"):
            raise ConfigValidationError(
                f"{where}: mode maze needs distractor_field, the item field listing one "
                "distractor per region")
        maze_keys = p.get("maze_keys", {"left": "e", "right": "i"})
        if (not isinstance(maze_keys, dict) or set(maze_keys) != {"left", "right"}
                or not all(_single_key(v) for v in maze_keys.values())
                or _single_key(maze_keys["left"]) == _single_key(maze_keys["right"])):
            raise ConfigValidationError(
                f"{where}.maze_keys must be {{left: <key>, right: <key>}}, two different "
                "single keys")
        if p.get("on_error", "stop") not in ("stop", "redo"):
            raise ConfigValidationError(f"{where}.on_error must be stop or redo")
        return {_single_key(v) for v in maze_keys.values()}
    for key in ("distractor_field", "maze_keys", "on_error"):
        if key in p:
            raise ConfigValidationError(f"{where}.{key} applies to mode: maze only")
    advance = _single_key(p.get("advance_key", "space"))
    if advance is None:
        raise ConfigValidationError(f"{where}.advance_key must be one key, or space")
    return {advance}


def split_regions(text: Any, separator: Optional[str]) -> List[str]:
    if isinstance(text, list):
        parts = [str(t) for t in text]
    elif separator:
        parts = str(text or "").split(separator)
    else:
        parts = str(text or "").split()
    return [p.strip() for p in parts if p.strip()][:MAX_REGIONS]


def _presentation_client(block: dict, config: dict, item_data: Optional[dict]) -> Optional[dict]:
    p = block.get("presentation")
    if not isinstance(p, dict):
        return None
    item = item_data if isinstance(item_data, dict) else {}
    field = p.get("field") or ((config.get("item_properties") or {}).get("text_key") or "text")
    sep = p.get("region_separator")
    regions = split_regions(item.get(field), sep)
    mode = p.get("mode", "moving_window")
    out = {"mode": mode, "regions": regions, "mask_char": p.get("mask_char", "-"),
           "question": None, "ask": True}
    if p.get("question_field"):
        q = item.get(p["question_field"])
        out["question"] = str(q) if q not in (None, "") else None
        out["ask"] = out["question"] is not None
    if mode == "maze":
        raw = item.get(p["distractor_field"])
        distractors = split_regions(raw, sep)
        if len(distractors) == len(regions) - 1:
            distractors = [MAZE_FIRST_DISTRACTOR] + distractors
        if len(distractors) != len(regions):
            logger.warning("trial_timing maze: item %s has %d regions and %d distractors; "
                           "missing ones are shown as %s", item.get("id"), len(regions),
                           len(distractors), MAZE_FIRST_DISTRACTOR)
            distractors = (distractors + [MAZE_FIRST_DISTRACTOR] * len(regions))[:len(regions)]
        keys = p.get("maze_keys", {"left": "e", "right": "i"})
        out.update({"distractors": distractors, "on_error": p.get("on_error", "stop"),
                    "maze_keys": {"left": _single_key(keys["left"]),
                                  "right": _single_key(keys["right"])}})
    else:
        out["advance_key"] = _single_key(p.get("advance_key", "space"))
    return out


def _override(item_data: Optional[dict], field: Optional[str]):
    if not field or not isinstance(item_data, dict):
        return None
    value = item_data.get(field)
    if isinstance(value, bool):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def client_config(config: dict, item_data: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    """What the browser needs for this item's trial, or None when off."""
    block = trial_config(config)
    if block is None:
        return None
    timing = {k: block.get(k) for k in TIMING_KEYS}
    for key, field in (block.get("item_overrides") or {}).items():
        value = _override(item_data, field)
        if value is None:
            continue
        # 0 means "no limit" for the two durations, as omitting them does.
        if value == 0 and key in ("stimulus_duration_ms", "trial_duration_ms"):
            value = None
        timing[key] = value
    response = block.get("response") or {}
    keys = {(" " if k == "space" else str(k).lower()): str(v)
            for k, v in (response.get("keys") or {}).items()}
    scheme = _response_scheme(config, response.get("schema") or "")
    return {
        "labels": _label_names(scheme) if scheme else [],
        **timing,
        "fixation_symbol": block.get("fixation_symbol", "+"),
        "schema": response.get("schema"),
        "keys": keys,
        "allow_mouse": bool(response.get("allow_mouse", False)),
        "show_response_options": bool(block.get("show_response_options",
                                                bool(response.get("allow_mouse", False)))),
        "presentation": _presentation_client(block, config, item_data),
    }


def back_navigation_disabled(config: dict) -> bool:
    block = trial_config(config)
    return bool(block and block.get("disable_back_navigation", True))


def validate_record(record: Any, served_at: Optional[float], cfg: Dict[str, Any],
                    now: Optional[float] = None) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Clean one trial record from the browser and flag what does not add up."""
    if not isinstance(record, dict):
        return None, ["not_an_object"]
    clean: Dict[str, Any] = {}
    for f in _NUMBER_FIELDS:
        v = record.get(f)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            clean[f] = float(v) if isinstance(v, float) else v
    for f in _STRING_FIELDS:
        v = record.get(f)
        if isinstance(v, str) and len(v) <= 200:
            clean[f] = v
    for f in _BOOL_FIELDS:
        if isinstance(record.get(f), bool):
            clean[f] = record[f]
    intended = record.get("intended")
    if isinstance(intended, dict):
        clean["intended"] = {k: intended.get(k) for k in TIMING_KEYS
                             if isinstance(intended.get(k), (int, float, type(None)))}
    flags: List[str] = []
    outcome = clean.get("outcome")
    if outcome not in OUTCOMES:
        return None, ["bad_outcome"]
    regions = record.get("regions")
    if isinstance(regions, list):
        kept = []
        for r in regions[:MAX_REGIONS]:
            if not isinstance(r, dict):
                continue
            row = {}
            for f in ("index", "rt_ms", "errors"):
                v = r.get(f)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
                    row[f] = v
            for f in ("correct",):
                if isinstance(r.get(f), bool):
                    row[f] = r[f]
            for f in ("text", "side"):
                if isinstance(r.get(f), str) and len(r[f]) <= 200:
                    row[f] = r[f]
            if "rt_ms" in row and row["rt_ms"] < 0:
                flags.append("bad_region_rt")
            kept.append(row)
        clean["regions"] = kept
    pres = cfg.get("presentation") or {}
    if outcome == "completed" and not pres.get("regions"):
        flags.append("completed_without_presentation")
    elif outcome == "completed":
        # The page ends a trial as `completed` only when there is no question
        # to ask after reading (trial-timing.js endReading), and only after
        # the last region, or at a maze error with on_error: stop.
        if pres.get("ask", True) and cfg.get("schema"):
            flags.append("completed_with_question")
        kept = clean.get("regions") or []
        maze_stop = (pres.get("mode") == "maze" and pres.get("on_error", "stop") == "stop"
                     and kept and kept[-1].get("correct") is False)
        if maze_stop:
            flags.append("maze_error")
            if len(kept) > len(pres["regions"]):
                flags.append("regions_incomplete")
        elif len(kept) != len(pres["regions"]):
            flags.append("regions_incomplete")
    if pres.get("regions") and (clean.get("reloads") or 0) > 0:
        # The sentence restarts on a reload, so the regions are a second reading.
        flags.append("reloaded_mid_trial")
    if outcome == "response":
        if clean.get("label") is None:
            flags.append("response_without_label")
        if clean.get("rt_ms") is None or clean["rt_ms"] < 0:
            flags.append("bad_rt")
    # The key and label must be ones the study defined, and agree.
    key = clean.get("key")
    keys = cfg.get("keys") or {}
    if key is not None:
        normalized = " " if key == "space" else key
        if normalized not in keys:
            flags.append("key_not_mapped")
        elif clean.get("label") is not None and keys[normalized] != clean["label"]:
            flags.append("label_mismatch")
    labels = cfg.get("labels")
    if outcome == "response" and labels and clean.get("label") not in labels:
        flags.append("label_not_in_scheme")
    now = time.time() if now is None else now
    if not served_at:
        # The server never handed this item over in this process (or has
        # restarted since), so it cannot check the timing at all.
        flags.append("not_served")
    elapsed_ms = (now - served_at) * 1000.0 if served_at else None
    if elapsed_ms is not None:
        rt = clean.get("rt_ms")
        if rt is not None and rt > elapsed_ms + SERVER_CLOCK_TOLERANCE_MS:
            flags.append("rt_exceeds_server_elapsed")
        reading = sum(r.get("rt_ms", 0) for r in clean.get("regions") or [])
        if reading > elapsed_ms + SERVER_CLOCK_TOLERANCE_MS:
            flags.append("reading_exceeds_server_elapsed")
        deadline = cfg.get("trial_duration_ms")
        if outcome == "timeout":
            if not deadline:
                flags.append("timeout_without_deadline")
            elif elapsed_ms + SERVER_CLOCK_TOLERANCE_MS < deadline:
                flags.append("timeout_too_early")
    elif outcome == "timeout" and not cfg.get("trial_duration_ms"):
        flags.append("timeout_without_deadline")
    if clean.get("tab_hidden"):
        flags.append("tab_hidden")
    clean["flags"] = flags
    clean["received_at"] = now
    if elapsed_ms is not None:
        clean["server_elapsed_ms"] = round(elapsed_ms, 1)
    return clean, flags


def excuses_required_answer(record: Optional[Dict[str, Any]]) -> bool:
    """A real timeout lets the participant move on without an answer, and so
    does a read sentence that had no question to ask."""
    if not isinstance(record, dict):
        return False
    if record.get("outcome") == "completed":
        bad = {"completed_without_presentation", "completed_with_question",
               "regions_incomplete", "not_served"}
        return not (set(record.get("flags") or []) & bad)
    if record.get("outcome") != "timeout":
        return False
    bad = {"timeout_too_early", "timeout_without_deadline", "not_served"}
    return not (set(record.get("flags") or []) & bad)


def is_terminal(record: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("outcome") in ("timeout", "completed"):
        return excuses_required_answer(record)
    return record.get("outcome") == "response"


def record_served(user_state, instance_id: str) -> None:
    """Note when the server handed this item over (kept in memory only)."""
    served = getattr(user_state, "_trial_served_at", None)
    if not isinstance(served, dict):
        served = {}
        user_state._trial_served_at = served
    served[str(instance_id)] = time.time()


def served_at(user_state, instance_id: str) -> Optional[float]:
    return (getattr(user_state, "_trial_served_at", None) or {}).get(str(instance_id))


def store_record(user_state, instance_id: str, record: Dict[str, Any]) -> None:
    """Keep the latest record; earlier ones for the item go in previous_attempts."""
    trials = getattr(user_state, "instance_id_to_trial", None)
    if not isinstance(trials, dict):
        trials = {}
        user_state.instance_id_to_trial = trials
    old = trials.get(str(instance_id))
    # The page sends the finished record with every save after the trial
    # ends (autosave and the navigation save); that is one trial, not two.
    if isinstance(old, dict) and old.get("onset_epoch_ms") == record.get("onset_epoch_ms"):
        record["previous_attempts"] = old.get("previous_attempts", [])
        trials[str(instance_id)] = record
        return
    if isinstance(old, dict):
        history = list(old.pop("previous_attempts", []) or [])
        history.append(old)
        record["previous_attempts"] = history[-5:]
    trials[str(instance_id)] = record
