"""
``type: jspsych``: a jsPsych 8 timeline.

.. code-block:: yaml

    phases:
      order: [consent, stroop, annotation, exit_survey]
      stroop:
        type: jspsych
        timeline: tasks/stroop.js           # defines window.potatoTimeline
        plugins: [html-keyboard-response, preload, fullscreen]
        extensions: [mouse-tracking]        # optional
        extra_scripts: [tasks/my-plugin.js] # optional, author-supplied plugins
        assets_dir: tasks/stimuli           # optional, served to the timeline
        expose_answers: [age, handedness]   # optional, earlier survey answers
        answers: [agree]                    # optional, values page rules can test
        save: on_finish                     # on_finish | incremental
        allow_rerun: false
        max_data_mb: 10

``answers`` names values the timeline records, so ``show_when`` and
``exit_when`` can test them as ``<page>_<name>``. When the run finishes, each
takes its value from the last trial that recorded it: a top-level data field
(``data: {agree: "no"}`` on a trial, or set in its ``on_finish``), or a survey
question of that ``name`` (inside the trial's ``response``). A name no trial
recorded stays unanswered. With it, a consent page written in jsPsych can
screen out a participant who declines::

    consent:
      type: jspsych
      timeline: tasks/consent.js
      plugins: [survey-multi-choice]
      answers: [agree]
      exit_when:
        show_when: [{schema: consent_agree, operator: equals, value: "No"}]
        message: "Thank you. You chose not to take part."
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from potato.jspsych.vendored import (
    EXTENSIONS, PLUGINS, core_static_path, extension_static_path, plugin_static_path)
from potato.runtimes.base import Asset, RuntimeAdapter

_ANSWER_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")


class JsPsychAdapter(RuntimeAdapter):
    kind = "jspsych"
    label = "jsPsych"
    main_key = "timeline"
    extra_keys = frozenset({"timeline", "plugins", "extensions", "answers"})
    boot_script = "runtime-boot-jspsych.js"

    def validate(self, where: str, entry: Dict[str, Any]) -> None:
        from potato.server_utils.config_module import ConfigValidationError
        for key, table, what in (("plugins", PLUGINS, "plugin"),
                                 ("extensions", EXTENSIONS, "extension")):
            names = entry.get(key, [])
            if not isinstance(names, list) or not all(isinstance(p, str) for p in names):
                raise ConfigValidationError(f"{where}.{key} must be a list of {what} names")
            missing = [p for p in names if p not in table]
            if missing:
                raise ConfigValidationError(
                    f"{where}.{key} names {', '.join(missing)}, which Potato does not ship. "
                    f"Shipped: {', '.join(sorted(table)) or 'none'}. Add other {what}s as "
                    "files under extra_scripts.")
        # An extension's companion plugins (WebGazer's camera and calibration
        # trials) have to be listed too, or the timeline fails at run time.
        for ext in entry.get("extensions", []) or []:
            needs = [p for p in EXTENSIONS[ext].get("plugins", ())
                     if p not in (entry.get("plugins") or [])]
            if needs:
                raise ConfigValidationError(
                    f"{where}.extensions: {ext} needs the plugin(s) {', '.join(needs)} "
                    f"in {where}.plugins")
        answers = entry.get("answers", [])
        if not isinstance(answers, list) or not all(
                isinstance(a, str) and _ANSWER_NAME.match(a) for a in answers):
            raise ConfigValidationError(
                f"{where}.answers must be a list of names (letters, digits and "
                "underscores) of values the timeline records")

    def spec_extras(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return {"plugins": list(entry.get("plugins") or []),
                "extensions": list(entry.get("extensions") or []),
                "answers": list(entry.get("answers") or [])}

    def answer_schemes(self, name: str, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [{"name": f"{name}_{a}", "annotation_type": "text",
                 "description": f"jsPsych: {a}"} for a in entry.get("answers") or []]

    def summarize(self, spec, trials):
        """``<page>_<name>`` for each of ``answers``, from the last trial that
        recorded it as a data field or as a survey question's response."""
        page = spec.get("page_name", "")
        out: Dict[str, Any] = {}
        for name in spec.get("answers") or []:
            for trial in reversed(trials):
                response = trial.get("response")
                if name in trial:
                    value = trial[name]
                elif isinstance(response, dict) and name in response:
                    value = response[name]
                else:
                    continue
                if value is not None and not isinstance(value, dict):
                    out[f"{page}_{name}"] = value
                break
        return out

    def assets(self, spec):
        styles = [Asset("static", core_static_path("jspsych.css"))]
        scripts: List[Asset] = [Asset("static", core_static_path("jspsych.js"))]
        for ext in spec.get("extensions", []):
            for dep in EXTENSIONS[ext].get("scripts", ()):
                scripts.append(Asset("static", dep))
            scripts.append(Asset("static", extension_static_path(ext)))
        scripts.extend(Asset("static", plugin_static_path(p)) for p in spec.get("plugins", []))
        return styles, scripts

    def client_extras(self, spec):
        return {"extensions": [{"name": ext, "global": EXTENSIONS[ext]["global"]}
                               for ext in spec.get("extensions", [])]}

    def csp_for(self, spec) -> Dict[str, tuple]:
        """WebGazer reads the camera and runs TensorFlow.js face mesh."""
        extra: Dict[str, tuple] = {}
        for ext in spec.get("extensions", []):
            for directive, sources in EXTENSIONS[ext].get("csp", {}).items():
                extra[directive] = tuple(dict.fromkeys(extra.get(directive, ()) + tuple(sources)))
        return extra


ADAPTER = JsPsychAdapter()
