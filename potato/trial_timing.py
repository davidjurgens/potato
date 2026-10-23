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
               "disable_back_navigation", "show_response_options"}
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
OUTCOMES = ("response", "timeout")

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
    response = block.get("response")
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
    """A real timeout lets the participant move on without an answer."""
    if not isinstance(record, dict) or record.get("outcome") != "timeout":
        return False
    bad = {"timeout_too_early", "timeout_without_deadline", "not_served"}
    return not (set(record.get("flags") or []) & bad)


def is_terminal(record: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("outcome") == "timeout":
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
