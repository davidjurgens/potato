"""
``type: headphone_check``: a screening page that checks the participant is
wearing headphones, before a listening test.

.. code-block:: yaml

    phases:
      order: [consent, headphones, annotation]
      headphones:
        type: headphone_check
        test: huggins          # huggins (default) | antiphase | both
        trials: 6              # per test
        pass_threshold: 5      # correct answers needed, per test
        on_fail: screen_out    # screen_out (default) | continue
        message: "This study needs headphones."

Two published procedures. The server makes the stimuli (no audio files are
shipped) and picks each trial's answer, so the page never holds it:

* **antiphase** (Woods, Siegel, Traer & McDermott, 2017): three 200 Hz tones;
  one is 6 dB quieter, one is in antiphase between the ears. Over
  loudspeakers the antiphase tone partly cancels and sounds quietest, so the
  listener without headphones picks it.
* **huggins** (Milne et al., 2021): three bursts of noise; in one, a narrow
  band around 600 Hz is phase-inverted in one ear. Over headphones that is
  heard as a faint tone ("Huggins pitch"); over loudspeakers it is not.

The page answers two pseudo-questions that page rules can test:
``<page>_passed`` (``yes`` / ``no``) and ``<page>_correct`` (a number, or
for ``test: both`` ``<page>_correct_huggins`` / ``_antiphase``). With
``on_fail: screen_out`` (the default) a failed check ends the study with
``message``, as an ``exit_when`` would.

Scoring (audit 96 R13). The answers are drawn on the server when the page
first asks for a sound, and kept in the run summary on the participant's
state, which the page cannot read. Each trial's three sounds are one WAV
(``/runtime/<page>/stimulus/<n>.wav``), so the request does not say which
interval is the target. At finish the server scores the response the page
sent for each trial against its own record. A target or ``correct`` value
in the posted trials is ignored, as is a second answer to the same trial or
an answer to a trial whose sound was never fetched. A participant who
posts made-up answers scores at chance. One who writes code to analyse the
WAV can still find the target, as with any headphone screen whose sounds
reach the browser.
"""

from __future__ import annotations

import io
import secrets
import threading
import wave
from typing import Any, Dict, List, Optional

from potato.runtimes.base import Asset, RuntimeAdapter

TESTS = ("huggins", "antiphase", "both")
DEFAULT_MESSAGE = ("This study needs headphones, and the check suggests you are not "
                   "wearing them. Thank you for your time.")

#: Sample rate of the served WAVs. The highest frequency in either test is
#: the 600 Hz Huggins band, well below the 8 kHz limit.
RATE = 16000
#: Each interval lasts INTERVAL_S; interval i starts at i * SPACING_S.
INTERVAL_S = 1.0
SPACING_S = 1.5
PLAN_KEY = "hc_plan"

_plan_lock = threading.Lock()


def _ramp(n: int):
    """100 ms raised-cosine onset and offset."""
    import numpy as np
    env = np.ones(n)
    r = int(0.1 * RATE)
    k = np.arange(r)
    env[:r] = 0.5 - 0.5 * np.cos(np.pi * k / r)
    env[n - r:] = env[:r][::-1]
    return env


def _tone(kind: str):
    """(left, right) for one antiphase-test interval: standard, quiet
    (-6 dB, the answer) or antiphase (right = -left)."""
    import numpy as np
    n = int(INTERVAL_S * RATE)
    gain = 0.25 if kind == "quiet" else 0.5
    left = gain * np.sin(2 * np.pi * 200 * np.arange(n) / RATE) * _ramp(n)
    return left, (-left if kind == "antiphase" else left)


def _noise(with_pitch: bool, rng):
    """(left, right) for one Huggins interval: diotic noise, or, for the
    answer, noise whose right channel has the band 600 Hz +/- 6% inverted."""
    import numpy as np
    n = int(INTERVAL_S * RATE)
    left = rng.uniform(-0.25, 0.25, n)
    if not with_pitch:
        return left * _ramp(n), left * _ramp(n)
    spectrum = np.fft.rfft(left)
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    spectrum[(freqs >= 600 * 0.94) & (freqs <= 600 * 1.06)] *= -1
    right = np.fft.irfft(spectrum, n)
    return left * _ramp(n), right * _ramp(n)


def _wav(intervals) -> bytes:
    """One stereo 16-bit WAV with interval i starting at i * SPACING_S."""
    import numpy as np
    total = int((SPACING_S * (len(intervals) - 1) + INTERVAL_S) * RATE)
    out = np.zeros((total, 2))
    for i, (left, right) in enumerate(intervals):
        start = int(i * SPACING_S * RATE)
        out[start:start + len(left), 0] = left
        out[start:start + len(right), 1] = right
    pcm = (np.clip(out, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _plan(spec: Dict[str, Any], user_state, create: bool) -> Optional[List[Dict[str, Any]]]:
    """This run's trials with their answers, drawn on first use."""
    from potato.runtimes.phase import run_summary
    summary = run_summary(user_state, spec.get("page_name", ""))
    run_id = summary.get("run_id")
    stored = summary.get(PLAN_KEY) or {}
    if stored.get("run_id") == run_id and run_id:
        return stored["trials"]
    if not create or not run_id:
        return None
    rand = secrets.SystemRandom()
    tests = ("huggins", "antiphase") if spec["test"] == "both" else (spec["test"],)
    trials = []
    for test in tests:
        for t in range(spec["trials"]):
            row = {"test": test, "trial": t + 1, "target": rand.randint(1, 3), "served": False}
            if test == "antiphase":
                row["others"] = rand.sample(["antiphase", "standard"], 2)
            trials.append(row)
    summary[PLAN_KEY] = {"run_id": run_id, "trials": trials}
    return trials


class HeadphoneCheckAdapter(RuntimeAdapter):
    kind = "headphone_check"
    label = "headphone check"
    main_key = None
    extra_keys = frozenset({"test", "trials", "pass_threshold", "on_fail", "message"})
    boot_script = "runtime-boot-headphone.js"

    def normalize(self, name: str, entry: Dict[str, Any]) -> None:
        if entry.get("on_fail", "screen_out") == "screen_out" and "exit_when" not in entry:
            entry["exit_when"] = {
                "show_when": [{"schema": f"{name}_passed", "operator": "equals", "value": "no"}],
                "message": entry.get("message") or DEFAULT_MESSAGE,
            }

    def validate(self, where: str, entry: Dict[str, Any]) -> None:
        from potato.server_utils.config_module import ConfigValidationError
        if entry.get("test", "huggins") not in TESTS:
            raise ConfigValidationError(f"{where}.test must be one of {', '.join(TESTS)}")
        trials = entry.get("trials", 6)
        if isinstance(trials, bool) or not isinstance(trials, int) or not 2 <= trials <= 20:
            raise ConfigValidationError(f"{where}.trials must be a whole number from 2 to 20")
        threshold = entry.get("pass_threshold", min(5, trials))
        if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= trials:
            raise ConfigValidationError(
                f"{where}.pass_threshold must be a whole number from 1 to trials ({trials})")
        if entry.get("on_fail", "screen_out") not in ("screen_out", "continue"):
            raise ConfigValidationError(f"{where}.on_fail must be screen_out or continue")
        if "message" in entry and not isinstance(entry["message"], str):
            raise ConfigValidationError(f"{where}.message must be text")

    def spec_extras(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        trials = int(entry.get("trials", 6))
        return {"test": entry.get("test", "huggins"), "trials": trials,
                "pass_threshold": int(entry.get("pass_threshold", min(5, trials)))}

    def assets(self, spec):
        return [Asset("static", "runtime-headphone.css")], []

    def client_extras(self, spec):
        from flask import url_for
        stimulus = url_for("runtime_stimulus", page=spec.get("page_name", ""), idx=0)
        return {"test": spec["test"], "trials": spec["trials"],
                "stimulus": stimulus[:-len("0.wav")], "spacing_s": SPACING_S,
                "interval_s": INTERVAL_S}

    def stimulus(self, spec, user_state, index):
        import numpy as np
        from potato.user_state_management import get_user_state_manager
        with _plan_lock:
            plan = _plan(spec, user_state, create=True)
            if plan is None or not 0 <= index < len(plan):
                return None
            row = plan[index]
            if not row["served"]:
                row["served"] = True
                get_user_state_manager().save_user_state(user_state)
        if row["test"] == "antiphase":
            others = list(row["others"])
            kinds = ["quiet" if i == row["target"] else others.pop(0) for i in (1, 2, 3)]
            return _wav([_tone(k) for k in kinds])
        rng = np.random.default_rng(secrets.randbits(64))
        return _wav([_noise(i == row["target"], rng) for i in (1, 2, 3)])

    def finalize_trials(self, spec, trials, user_state):
        """Score each posted response against the server's plan. What the
        page said the target was, or whether it was correct, is dropped."""
        plan = _plan(spec, user_state, create=False) or []
        seen = set()
        out = []
        for posted in trials:
            row = {k: v for k, v in posted.items()
                   if k not in ("target", "correct", "scored", "test", "trial")}
            index, response = posted.get("index"), posted.get("response")
            ok_index = (isinstance(index, int) and not isinstance(index, bool)
                        and 0 <= index < len(plan) and index not in seen
                        and plan[index]["served"])
            ok_response = (isinstance(response, int) and not isinstance(response, bool)
                           and 1 <= response <= 3)
            if ok_index:
                seen.add(index)
                entry = plan[index]
                row.update({"test": entry["test"], "trial": entry["trial"],
                            "target": entry["target"], "scored": ok_response,
                            "correct": ok_response and response == entry["target"]})
            else:
                row.update({"test": None, "trial": None, "target": None,
                            "scored": False, "correct": False})
            out.append(row)
        return out

    def answer_schemes(self, name: str, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        out = [{"name": f"{name}_passed", "annotation_type": "radio", "labels": ["yes", "no"],
                "description": "Headphone check passed"}]
        if entry.get("test", "huggins") == "both":
            out += [{"name": f"{name}_correct_{t}", "annotation_type": "number",
                     "description": f"Headphone check: {t} trials correct"}
                    for t in ("huggins", "antiphase")]
        else:
            out.append({"name": f"{name}_correct", "annotation_type": "number",
                        "description": "Headphone check: trials correct"})
        return out

    def summarize(self, spec: Dict[str, Any], trials: List[Dict[str, Any]]) -> Dict[str, Any]:
        page = spec.get("page_name", "")
        counts = {}
        # Trials come from finalize_trials, which stamps "scored" and
        # "correct" from the server's plan.
        for t in trials:
            test = t.get("test")
            if test in ("huggins", "antiphase"):
                right = t.get("scored") is True and t.get("correct") is True
                counts[test] = counts.get(test, 0) + int(right)
        needed = ("huggins", "antiphase") if spec["test"] == "both" else (spec["test"],)
        passed = all(counts.get(t, 0) >= spec["pass_threshold"] for t in needed)
        answers = {f"{page}_passed": "yes" if passed else "no"}
        if spec["test"] == "both":
            for t in needed:
                answers[f"{page}_correct_{t}"] = counts.get(t, 0)
        else:
            answers[f"{page}_correct"] = counts.get(spec["test"], 0)
        return answers


ADAPTER = HeadphoneCheckAdapter()
