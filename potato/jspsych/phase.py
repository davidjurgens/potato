"""
A `type: jspsych` phase page: config checks, boot registration and rendering.

.. code-block:: yaml

    phases:
      order: [consent, stroop, annotation, exit_survey]
      stroop:
        type: jspsych
        timeline: tasks/stroop.js           # defines window.potatoTimeline
        plugins: [html-keyboard-response, preload, fullscreen]
        extra_scripts: [tasks/my-plugin.js] # optional, author-supplied plugins
        assets_dir: tasks/stimuli           # optional, served to the timeline
        expose_answers: [age, handedness]   # optional, earlier survey answers
        save: on_finish                     # on_finish | incremental
        allow_rerun: false
        max_data_mb: 10

The timeline is author code, served as-is from the task directory and never
passed through Jinja. It runs in a dedicated page (``jspsych_phase.html``)
under a Content-Security-Policy that only allows scripts and connections to
this server, so a stimulus that echoes participant text cannot pull in or
send to anything else.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from potato.jspsych.vendored import PLUGINS, core_static_path, plugin_static_path

logger = logging.getLogger(__name__)

TEMPLATE = "jspsych_phase.html"

PHASE_KEYS = {
    "type", "slot", "timeline", "plugins", "extra_scripts", "assets_dir",
    "expose_answers", "save", "allow_rerun", "max_data_mb", "csp",
    "show_when", "logic", "exit_when", "_kind",
}

SAVE_MODES = ("on_finish", "incremental")

#: What the asset route will serve from `assets_dir`. Scripts and pages are
#: declared in `timeline` / `extra_scripts`, never picked up from a folder.
ASSET_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac",
    ".mp4", ".webm", ".ogv", ".mov",
    ".json", ".csv", ".tsv", ".txt",
    ".css", ".woff", ".woff2", ".ttf", ".otf",
})

DEFAULT_MAX_DATA_MB = 10


def is_jspsych_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("_kind") == "jspsych"


def jspsych_pages(config: dict) -> Dict[str, Dict[str, Any]]:
    return config.get("_jspsych_pages") or {}


def validate_jspsych_entry(name: str, entry: Dict[str, Any]) -> None:
    """Shape checks for one normalized `type: jspsych` entry."""
    from potato.server_utils.config_module import ConfigValidationError
    where = f"phases.{name}"
    unknown = set(entry) - PHASE_KEYS
    if unknown:
        raise ConfigValidationError(
            f"{where} (type: jspsych) has unknown key(s): {', '.join(sorted(unknown))}")
    timeline = entry.get("timeline")
    if not isinstance(timeline, str) or not timeline.strip():
        raise ConfigValidationError(
            f"{where}.timeline must name the JavaScript file that defines "
            "window.potatoTimeline")
    plugins = entry.get("plugins", [])
    if not isinstance(plugins, list) or not all(isinstance(p, str) for p in plugins):
        raise ConfigValidationError(f"{where}.plugins must be a list of plugin names")
    missing = [p for p in plugins if p not in PLUGINS]
    if missing:
        raise ConfigValidationError(
            f"{where}.plugins names {', '.join(missing)}, which Potato does not ship. "
            f"Shipped: {', '.join(sorted(PLUGINS))}. Add other plugins as files "
            "under extra_scripts.")
    extra = entry.get("extra_scripts", [])
    if not isinstance(extra, list) or not all(isinstance(p, str) and p for p in extra):
        raise ConfigValidationError(f"{where}.extra_scripts must be a list of file paths")
    if "assets_dir" in entry and not (isinstance(entry["assets_dir"], str) and entry["assets_dir"]):
        raise ConfigValidationError(f"{where}.assets_dir must be a directory path")
    expose = entry.get("expose_answers", [])
    if not isinstance(expose, list) or not all(isinstance(p, str) for p in expose):
        raise ConfigValidationError(f"{where}.expose_answers must be a list of question names")
    if entry.get("save", "on_finish") not in SAVE_MODES:
        raise ConfigValidationError(f"{where}.save must be one of {', '.join(SAVE_MODES)}")
    if not isinstance(entry.get("allow_rerun", False), bool):
        raise ConfigValidationError(f"{where}.allow_rerun must be true or false")
    mb = entry.get("max_data_mb", DEFAULT_MAX_DATA_MB)
    if isinstance(mb, bool) or not isinstance(mb, (int, float)) or not (0 < mb <= 200):
        raise ConfigValidationError(f"{where}.max_data_mb must be a number between 0 and 200")
    csp = entry.get("csp", {})
    if not isinstance(csp, dict) or set(csp) - {"extra_sources"}:
        raise ConfigValidationError(f"{where}.csp may only contain extra_sources")
    for src in csp.get("extra_sources", []) or []:
        if not (isinstance(src, str) and src.startswith("https://") and
                not any(c in src for c in " ;,*'\"") and len(src) > len("https://")):
            raise ConfigValidationError(
                f"{where}.csp.extra_sources entries must each be one https:// origin "
                f"with no wildcard, got {src!r}")


def validate_jspsych_config(config_data: Dict[str, Any]) -> None:
    from potato.server_utils.phase_flow import phases_dict
    for name, entry in phases_dict(config_data).items():
        if is_jspsych_entry(entry):
            validate_jspsych_entry(name, entry)


def register_jspsych_page(config: dict, name: str, entry: Dict[str, Any], resolve_path) -> None:
    """At boot: resolve and check every file the page names, then record it.

    ``resolve_path(path)`` turns a config path into an absolute one (the
    server's ``get_abs_or_rel_path``). Every path must stay inside the task
    directory.
    """
    from potato.server_utils.config_module import (
        ConfigValidationError, validate_path_security)
    validate_jspsych_entry(name, entry)
    task_dir = config.get("task_dir") or "."

    def _checked(path: str, kind: str, want_dir: bool = False) -> str:
        try:
            resolved = os.path.abspath(resolve_path(path))
        except (FileNotFoundError, OSError):
            kind_word = "directory" if want_dir else "file"
            # `from None`: the resolver's own error names a guessed path that
            # is not where the file was looked for, and only misleads.
            raise ConfigValidationError(
                f"phases.{name}.{kind}: {kind_word} not found: {path} (looked in the "
                f"task directory {task_dir} and beside the config)") from None
        validate_path_security(resolved, task_dir)
        if want_dir:
            if not os.path.isdir(resolved):
                raise ConfigValidationError(
                    f"phases.{name}.{kind}: directory not found: {path}")
        elif not os.path.isfile(resolved):
            raise ConfigValidationError(f"phases.{name}.{kind}: file not found: {path}")
        return resolved

    timeline = _checked(entry["timeline"], "timeline")
    if not timeline.endswith(".js"):
        raise ConfigValidationError(f"phases.{name}.timeline must be a .js file")
    extra = [_checked(p, "extra_scripts") for p in entry.get("extra_scripts") or []]
    for p in extra:
        if not p.endswith(".js"):
            raise ConfigValidationError(f"phases.{name}.extra_scripts must be .js files: {p}")
    assets_dir = (_checked(entry["assets_dir"], "assets_dir", want_dir=True)
                  if entry.get("assets_dir") else None)

    config.setdefault("_jspsych_pages", {})[name] = {
        "timeline": timeline,
        "extra_scripts": extra,
        "assets_dir": assets_dir,
        "plugins": list(entry.get("plugins") or []),
        "expose_answers": list(entry.get("expose_answers") or []),
        "save": entry.get("save", "on_finish"),
        "allow_rerun": bool(entry.get("allow_rerun", False)),
        "max_bytes": int(float(entry.get("max_data_mb", DEFAULT_MAX_DATA_MB)) * 1024 * 1024),
        "extra_sources": list((entry.get("csp") or {}).get("extra_sources") or []),
    }


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def run_summary(user_state, page: str) -> Dict[str, Any]:
    from potato.server_utils.phase_flow import flow_record
    return flow_record(user_state).setdefault("jspsych", {}).setdefault(page, {})


def is_complete(user_state, page: str) -> bool:
    from potato.server_utils.phase_flow import flow_record
    return (flow_record(user_state).get("jspsych") or {}).get(page, {}).get("status") == "complete"


def content_security_policy(spec: Dict[str, Any]) -> str:
    extra = " ".join(spec.get("extra_sources") or [])
    tail = f" {extra}" if extra else ""
    return ("default-src 'self'" + tail + "; "
            "script-src 'self'" + tail + "; "
            "style-src 'self' 'unsafe-inline'" + tail + "; "
            "img-src 'self' data: blob:" + tail + "; "
            "media-src 'self' data: blob:" + tail + "; "
            "font-src 'self' data:" + tail + "; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; base-uri 'none'; form-action 'self'")


def _exposed_answers(config: dict, user_state, names: List[str]) -> Dict[str, Any]:
    if not names:
        return {}
    from potato.server_utils.phase_flow import collect_flow_answers
    answers = collect_flow_answers(config, user_state)
    return {n: answers.get(n) for n in names}


def render_jspsych_page(config: dict, username: str, user_state, phase, page: str) -> str:
    """The page that runs the timeline, or the "already done" page."""
    from flask import g, render_template, url_for
    from potato.jspsych import store
    from potato.server_utils.phase_flow import conditions_for
    from potato.user_state_management import get_user_state_manager

    spec = jspsych_pages(config)[page]
    usm = get_user_state_manager()
    task_name = config.get("annotation_task_name", "")

    if is_complete(user_state, page) and not spec["allow_rerun"]:
        return render_template("jspsych_done.html", annotation_task_name=task_name,
                               page=page, continue_url=url_for("jspsych_continue", page=page))

    # jsPsych cannot resume mid-timeline, so a reload starts the task over.
    # A run that has sent no data yet is reused: the page is often rendered
    # twice on arrival (the previous page's POST, then the reload), and that
    # is not a second attempt. Once a run has data, a reload starts a new
    # attempt and the earlier one stays on record as partial.
    task_dir = config.get("task_dir") or "."
    summary = run_summary(user_state, page)
    phase_name = phase.name.lower() if hasattr(phase, "name") else str(phase)
    conditions = conditions_for(user_state)
    run_id = summary.get("run_id")
    reuse = False
    from flask import request
    if run_id and summary.get("status") == "started" and request.method != "GET":
        # Not a page load: a refused form post re-renders this page as its
        # response. Starting a new run there orphaned the tab still running
        # the task, whose finish then failed as "replaced by a newer one".
        reuse = True
    elif run_id and summary.get("status") == "started":
        try:
            existing = store.get_run(task_dir, run_id)
            reuse = existing is not None and not existing.get("n_trials")
        except Exception:
            reuse = False
    summary["page_loads"] = int(summary.get("page_loads", 0)) + 1
    if reuse:
        attempt = int(summary.get("attempts", 1))
    else:
        attempt = int(summary.get("attempts", 0)) + 1
        run_id = uuid.uuid4().hex
        summary.update({"run_id": run_id, "attempts": attempt, "status": "started"})
        try:
            store.start_run(task_dir,
                            project=config.get("annotation_task_name") or "potato",
                            user_id=username, phase=phase_name, page=page,
                            run_id=run_id, attempt=attempt, conditions=conditions)
        except Exception as e:
            logger.error("Could not record jsPsych run start for %s: %s", username, e)
    usm.save_user_state(user_state)

    client_config = {
        "page": page,
        "phase": phase_name,
        "participant": username,
        "conditions": conditions,
        "answers": _exposed_answers(config, user_state, spec["expose_answers"]),
        "run_id": run_id,
        "attempt": attempt,
        "save": spec["save"],
        "max_bytes": spec["max_bytes"],
        "endpoints": {
            "trial": url_for("jspsych_trial"),
            "finish": url_for("jspsych_finish"),
            "assets": url_for("jspsych_asset_root", page=page),
        },
    }
    g.potato_csp = content_security_policy(spec)
    return render_template(
        TEMPLATE,
        annotation_task_name=task_name,
        client_config=client_config,
        core_js=core_static_path("jspsych.js"),
        core_css=core_static_path("jspsych.css"),
        plugin_paths=[plugin_static_path(p) for p in spec["plugins"]],
        extra_script_urls=[url_for("jspsych_extra_script", page=page, idx=i)
                           for i in range(len(spec["extra_scripts"]))],
        timeline_url=url_for("jspsych_timeline", page=page, run=run_id),
    )


def validate_jspsych_files(config_data: Dict[str, Any], config_file_dir: Optional[str] = None) -> None:
    """At validation time: every file a jsPsych page names exists inside the
    task directory, so `potato validate` reports a missing timeline instead of
    the server failing at startup."""
    from potato.server_utils.config_module import ConfigValidationError
    from potato.server_utils.phase_flow import phases_dict
    task_dir = config_data.get("task_dir") or config_file_dir or "."
    for name, entry in phases_dict(config_data).items():
        if not is_jspsych_entry(entry):
            continue

        def resolve(path, _dirs=(task_dir, config_file_dir)):
            if os.path.isabs(path):
                return path
            for base in _dirs:
                if base and os.path.exists(os.path.join(base, path)):
                    return os.path.join(base, path)
            raise FileNotFoundError(path)
        try:
            register_jspsych_page({"task_dir": task_dir}, name, entry, resolve)
        except ConfigValidationError:
            raise
