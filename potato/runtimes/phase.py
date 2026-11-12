"""
Runtime phase pages: config checks, boot registration and rendering.

A phase whose ``type`` names a runtime (``jspsych``, ``osweb``, ...) is
rewritten by ``normalize_config_before_validation`` into a prestudy or
poststudy page with ``_kind: <runtime>``, so ordering, ``show_when``,
counterbalancing and ``--debug-phase`` treat it as an ordinary survey page.

Shared keys (every runtime)::

    extra_scripts: [tasks/my-plugin.js]  # author-supplied scripts, loaded before the study
    assets_dir: tasks/stimuli            # files the study may fetch
    expose_answers: [age, handedness]    # earlier survey answers passed to the study
    save: on_finish                      # on_finish | incremental
    allow_rerun: false
    max_data_mb: 10
    csp: {extra_sources: [https://fonts.example]}

The study file and scripts are author code, served as-is from the task
directory and never passed through Jinja. The page (``runtime_phase.html``)
runs under a Content-Security-Policy that allows scripts and connections only
to this server, plus the documented additions a runtime cannot work without.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Iterator, List, Optional, Tuple

from potato.runtimes.registry import get_adapter, runtime_kinds

logger = logging.getLogger(__name__)

TEMPLATE = "runtime_phase.html"

SHARED_KEYS = frozenset({
    "type", "slot", "extra_scripts", "assets_dir", "expose_answers", "save",
    "allow_rerun", "max_data_mb", "csp", "show_when", "logic", "exit_when", "_kind",
})

SAVE_MODES = ("on_finish", "incremental")

#: What the asset route serves from `assets_dir` for every runtime. Scripts
#: are declared in the study file key and `extra_scripts`, never picked up
#: from a folder, unless the adapter adds `.js` for a runtime whose export is
#: a directory of modules.
ASSET_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac",
    ".mp4", ".webm", ".ogv", ".mov",
    ".json", ".csv", ".tsv", ".txt",
    ".css", ".woff", ".woff2", ".ttf", ".otf",
})

DEFAULT_MAX_DATA_MB = 10

#: Where a page's run summary lives on the user state's flow record.
FLOW_KEY = "runtimes"


def is_runtime_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and get_adapter(entry.get("_kind")) is not None


def is_runtime_type(value: Any) -> bool:
    return str(value or "").lower() in runtime_kinds()


def runtime_entries(config: dict) -> Iterator[Tuple[str, Dict[str, Any]]]:
    from potato.server_utils.phase_flow import phases_dict
    for name, entry in phases_dict(config).items():
        if is_runtime_entry(entry) or (isinstance(entry, dict) and is_runtime_type(entry.get("type"))):
            yield name, entry


def has_runtime_pages(config: dict, kind: Optional[str] = None) -> bool:
    for _name, entry in runtime_entries(config):
        if kind is None or (entry.get("_kind") or str(entry.get("type", "")).lower()) == kind:
            return True
    return False


def runtime_pages(config: dict) -> Dict[str, Dict[str, Any]]:
    return config.get("_runtime_pages") or {}


def validate_runtime_entry(name: str, entry: Dict[str, Any]) -> None:
    """Shape checks for one normalized runtime entry."""
    from potato.server_utils.config_module import ConfigValidationError
    adapter = get_adapter(entry.get("_kind"))
    if adapter is None:
        raise ConfigValidationError(f"phases.{name}: unknown runtime {entry.get('_kind')!r}")
    where = f"phases.{name}"
    kind = adapter.kind
    unknown = set(entry) - SHARED_KEYS - adapter.extra_keys
    if unknown:
        raise ConfigValidationError(
            f"{where} (type: {kind}) has unknown key(s): {', '.join(sorted(unknown))}")
    main = entry.get(adapter.main_key) if adapter.main_key else None
    if adapter.main_key and (not isinstance(main, str) or not main.strip()):
        raise ConfigValidationError(
            f"{where}.{adapter.main_key} must name the {adapter.label} study file "
            f"({'a directory' if adapter.main_is_dir else ' or '.join(adapter.main_extensions)})")
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
    adapter.validate(where, entry)


def validate_runtime_config(config_data: Dict[str, Any]) -> None:
    for name, entry in runtime_entries(config_data):
        if is_runtime_entry(entry):
            validate_runtime_entry(name, entry)


def register_runtime_page(config: dict, name: str, entry: Dict[str, Any], resolve_path) -> None:
    """At boot: resolve and check every file the page names, then record it.

    ``resolve_path(path)`` turns a config path into an absolute one (the
    server's ``get_abs_or_rel_path``). Every path must stay inside the task
    directory.
    """
    from potato.server_utils.config_module import (
        ConfigValidationError, validate_path_security)
    validate_runtime_entry(name, entry)
    adapter = get_adapter(entry["_kind"])
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

    main = (_checked(entry[adapter.main_key], adapter.main_key, want_dir=adapter.main_is_dir)
            if adapter.main_key else None)
    if main and not adapter.main_is_dir and not main.lower().endswith(adapter.main_extensions):
        raise ConfigValidationError(
            f"phases.{name}.{adapter.main_key} must be a "
            f"{' or '.join(adapter.main_extensions)} file")
    extra = [_checked(p, "extra_scripts") for p in entry.get("extra_scripts") or []]
    for p in extra:
        if not p.endswith(".js"):
            raise ConfigValidationError(f"phases.{name}.extra_scripts must be .js files: {p}")
    assets_dir = (_checked(entry["assets_dir"], "assets_dir", want_dir=True)
                  if entry.get("assets_dir") else None)

    spec = {
        "kind": adapter.kind,
        "main": main,
        "extra_scripts": extra,
        "assets_dir": assets_dir,
        "expose_answers": list(entry.get("expose_answers") or []),
        "save": entry.get("save", "on_finish"),
        "allow_rerun": bool(entry.get("allow_rerun", False)),
        "max_bytes": int(float(entry.get("max_data_mb", DEFAULT_MAX_DATA_MB)) * 1024 * 1024),
        "extra_sources": list((entry.get("csp") or {}).get("extra_sources") or []),
        "page_name": name,
    }
    spec.update(adapter.spec_extras(entry))
    config.setdefault("_runtime_pages", {})[name] = spec


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def run_summary(user_state, page: str) -> Dict[str, Any]:
    from potato.server_utils.phase_flow import flow_record
    return flow_record(user_state).setdefault(FLOW_KEY, {}).setdefault(page, {})


def page_summary(user_state, page: str) -> Dict[str, Any]:
    """Read-only view of a page's run summary ({} when there is none)."""
    from potato.server_utils.phase_flow import flow_record
    return (flow_record(user_state).get(FLOW_KEY) or {}).get(page) or {}


def is_complete(user_state, page: str) -> bool:
    return page_summary(user_state, page).get("status") == "complete"


def content_security_policy(spec: Dict[str, Any], additions: Optional[Dict[str, tuple]] = None) -> str:
    """The page's CSP. ``connect-src`` never takes the author's extra sources:
    data leaves the page only for this server."""
    extra = " ".join(spec.get("extra_sources") or [])
    tail = f" {extra}" if extra else ""
    add = additions or {}

    def more(directive: str) -> str:
        sources = add.get(directive) or ()
        return (" " + " ".join(sources)) if sources else ""

    parts = [
        "default-src 'self'" + tail,
        "script-src 'self'" + tail + more("script-src"),
        "style-src 'self' 'unsafe-inline'" + tail + more("style-src"),
        "img-src 'self' data: blob:" + tail + more("img-src"),
        "media-src 'self' data: blob:" + tail + more("media-src"),
        "font-src 'self' data:" + tail + more("font-src"),
        "connect-src 'self'" + more("connect-src"),
    ]
    for directive in ("worker-src", "frame-src", "child-src"):
        if add.get(directive):
            parts.append(directive + more(directive))
    parts += ["frame-ancestors 'self'", "base-uri 'none'", "form-action 'self'"]
    return "; ".join(parts)


def _exposed_answers(config: dict, user_state, names: List[str]) -> Dict[str, Any]:
    if not names:
        return {}
    from potato.server_utils.phase_flow import collect_flow_answers
    answers = collect_flow_answers(config, user_state)
    return {n: answers.get(n) for n in names}


def asset_url(asset) -> str:
    from flask import url_for
    if asset.source == "static":
        return url_for("static", filename=asset.path)
    from potato import vendoring
    return vendoring.static_url(asset.source, asset.path)


def render_runtime_page(config: dict, username: str, user_state, phase, page: str) -> str:
    """The page that runs the study, or the "already done" page."""
    from flask import g, render_template, request, url_for
    from potato.runtimes import store
    from potato.server_utils.phase_flow import conditions_for
    from potato.user_state_management import get_user_state_manager

    spec = runtime_pages(config)[page]
    adapter = get_adapter(spec["kind"])
    usm = get_user_state_manager()
    task_name = config.get("annotation_task_name", "")

    if is_complete(user_state, page) and not spec["allow_rerun"]:
        return render_template("runtime_done.html", annotation_task_name=task_name,
                               page=page, continue_url=url_for("runtime_continue", page=page))

    # A runtime cannot resume mid-study, so a reload starts the task over.
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
    summary["kind"] = adapter.kind
    if reuse:
        attempt = int(summary.get("attempts", 1))
    else:
        attempt = int(summary.get("attempts", 0)) + 1
        run_id = uuid.uuid4().hex
        summary.update({"run_id": run_id, "attempts": attempt, "status": "started"})
        try:
            store.start_run(task_dir,
                            project=config.get("annotation_task_name") or "potato",
                            runtime=adapter.kind, user_id=username, phase=phase_name,
                            page=page, run_id=run_id, attempt=attempt, conditions=conditions)
        except Exception as e:
            logger.error("Could not record %s run start for %s: %s", adapter.label, username, e)
    usm.save_user_state(user_state)

    if not adapter.main_key:
        study_base, main_url = None, None
    elif adapter.main_is_dir:
        study_base = url_for("runtime_main", page=page) + "/"
        entry = adapter.entry_file(spec)
        main_url = (study_base + entry) if entry else study_base
    else:
        study_base = None
        main_url = url_for("runtime_main", page=page, run=run_id)
    client_config = {
        "kind": adapter.kind,
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
            "trial": url_for("runtime_trial"),
            "finish": url_for("runtime_finish"),
            "assets": url_for("runtime_asset_root", page=page),
            "main": main_url,
            "study_base": study_base,
        },
        "runtime": adapter.client_extras(spec),
    }
    link = getattr(adapter, "link", None)
    if callable(link):
        # A link-out page: the other system brings the participant back here.
        return_url = url_for("runtime_return", page=page, run=run_id, _external=True)
        client_config["runtime"]["link"] = link(spec, username, run_id, return_url, conditions)
    g.potato_csp = content_security_policy(spec, adapter.csp_for(spec))
    permissions = getattr(adapter, "permissions_policy", None)
    if callable(permissions):
        g.potato_permissions_policy = permissions(spec)
    styles, scripts = adapter.assets(spec)
    return render_template(
        TEMPLATE,
        annotation_task_name=task_name,
        client_config=client_config,
        style_urls=[asset_url(a) for a in styles],
        scripts=[{"src": asset_url(a), "module": a.module} for a in scripts],
        boot_script=adapter.boot_script,
        extra_script_urls=[url_for("runtime_extra_script", page=page, idx=i)
                           for i in range(len(spec["extra_scripts"]))],
        main_url=None if (not main_url or adapter.main_is_data
                          or (adapter.main_is_dir and not adapter.entry_file(spec))) else main_url,
        main_is_module=adapter.main_is_module,
    )


def validate_runtime_files(config_data: Dict[str, Any], config_file_dir: Optional[str] = None) -> None:
    """At validation time: every file a runtime page names exists inside the
    task directory, so `potato validate` reports a missing study file instead
    of the server failing at startup."""
    task_dir = config_data.get("task_dir") or config_file_dir or "."
    for name, entry in runtime_entries(config_data):
        if not is_runtime_entry(entry):
            continue

        def resolve(path, _dirs=(task_dir, config_file_dir)):
            if os.path.isabs(path):
                return path
            for base in _dirs:
                if base and os.path.exists(os.path.join(base, path)):
                    return os.path.join(base, path)
            raise FileNotFoundError(path)
        register_runtime_page({"task_dir": task_dir}, name, entry, resolve)
