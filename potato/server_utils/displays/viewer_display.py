"""
Third-party viewer displays: a shared base for scientific viewers.

A viewer display embeds a JavaScript library that draws the item (a protein
structure in 3Dmol.js or Mol*, a genome locus in igv.js) and lets the
annotator select parts of it. This module holds what every such display
shares, so a new viewer is a subclass and one adapter script rather than a
fresh copy of the loading, fallback and selection plumbing.

What the base provides
----------------------

* **A container** for one item field: ``<div class="potato-viewer"
  data-viewer-kind=... data-viewer-field=... data-viewer-config=...>`` with a
  stage the library draws into, a status line, and an error/fallback slot.
* **Lazy library loading.** The page loads only the small framework script
  (``static/viewers/viewer-framework.js``) and the adapters. The library
  itself, which is 0.5 to 5 MB, is fetched when a viewer is mounted: from
  ``potato/static/vendor/`` when it is committed, or from a bundle installed
  with ``potato vendor fetch`` (:mod:`potato.vendoring`) when it is too large
  to commit.
* **A WebGL check.** An engine that needs WebGL (or WebGL2) and does not get
  it shows a plain message instead of a blank canvas, and the display's
  non-graphical controls (the protein residue table) keep working.
* **A selection API** in the browser, one object per field::

      window.potatoViewers[field] = {
          getSelection(), setSelection(sel), onSelectionChange(cb), describe(sel)
      }

  The ``viewer_selection`` annotation scheme binds to it with
  ``viewer_field``, stores the selection as JSON and restores it.
* **A selection shape per viewer**, which :func:`validate_selection` checks
  in Python. The server does not call it: ``/updateinstance`` stores the
  scheme's JSON as the browser sent it, and no exporter re-checks it. It is
  there for scripts that audit stored answers, and for the tests.

Subclasses set ``name``, ``engines``, ``default_engine`` and implement
:meth:`ViewerDisplay.client_config` (what the adapter receives) and
:meth:`ViewerDisplay.validate_item` (one selected item).
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseDisplay, css_length

logger = logging.getLogger(__name__)

#: Where the framework's own scripts live (served from potato/static/).
FRAMEWORK_STATIC = "/static/viewers/"


class ViewerDataError(ValueError):
    """The item's value cannot be shown (missing file, remote URL refused...).

    Rendered as a message in the viewer's place; never raised to the page.
    """


@dataclass(frozen=True)
class ViewerAsset:
    """One file a viewer engine loads: a script or a stylesheet.

    ``bundle`` names a fetched bundle (:mod:`potato.vendoring`); without one
    ``path`` is under ``potato/static/``.
    """
    kind: str            # "script" | "style"
    path: str
    bundle: Optional[str] = None

    def url(self) -> str:
        if self.bundle:
            from potato import vendoring
            return vendoring.static_url(self.bundle, self.path)
        return "/static/" + self.path.lstrip("/")


@dataclass(frozen=True)
class ViewerEngine:
    """A library that can draw one viewer kind."""
    name: str
    label: str
    assets: Tuple[ViewerAsset, ...] = ()
    #: "webgl", "webgl2" or None (a canvas-2D or DOM library).
    webgl: Optional[str] = None
    licence: str = ""

    @property
    def bundles(self) -> List[str]:
        return list(dict.fromkeys(a.bundle for a in self.assets if a.bundle))


class ViewerDisplay(BaseDisplay):
    """Base class for third-party viewer displays.

    Options every viewer accepts (declare them in a subclass's
    ``optional_fields`` by merging :attr:`COMMON_OPTIONS`):

    ``engine``         which library draws the view (subclass-specific)
    ``height``         CSS height of the drawing area
    ``allow_remote``   let the browser fetch an http(s) URL named in the data
    """

    supports_span_target = False
    engines: Dict[str, ViewerEngine] = {}
    default_engine: str = ""

    COMMON_OPTIONS: Dict[str, Any] = {
        "engine": None,
        "height": 420,
        "allow_remote": False,
    }

    # -- what subclasses implement ------------------------------------------

    def client_config(self, field_config: Dict[str, Any], data: Any,
                      options: Dict[str, Any]) -> Dict[str, Any]:
        """The JSON the browser adapter receives. Raise ViewerDataError for an
        item that cannot be shown."""
        raise NotImplementedError

    def render_extras(self, field_config: Dict[str, Any], data: Any,
                      options: Dict[str, Any], cfg: Dict[str, Any]) -> str:
        """HTML rendered below the stage (tables, side panels)."""
        return ""

    def validate_item(self, item: Any, where: str) -> List[str]:
        """Problems with one selected item."""
        return []

    #: Keys a stored selection may carry besides ``items`` (e.g. ``locus``).
    selection_context: Tuple[str, ...] = ()

    def validate_context(self, selection: Dict[str, Any]) -> List[str]:
        return []

    def validate_options(self, options: Dict[str, Any], path: str) -> List[str]:
        """Problems with a field's options (beyond the engine and bundles)."""
        return []

    # -- shared behaviour -----------------------------------------------------

    def engine_for(self, field_config: Dict[str, Any]) -> ViewerEngine:
        options = self.get_display_options(field_config)
        name = options.get("engine") or self.default_engine
        engine = self.engines.get(name)
        if engine is None:
            raise ValueError(
                f"display type '{self.name}': engine '{name}' is not one of "
                f"{', '.join(sorted(self.engines))}")
        return engine

    def required_bundles(self, field_config: Dict[str, Any]) -> List[str]:
        try:
            return self.engine_for(field_config).bundles
        except ValueError:
            return []

    def field_id(self, field_config: Dict[str, Any]) -> str:
        key = str(field_config.get("key", self.name))
        return "viewer-" + "".join(c if c.isalnum() or c in "-_" else "-" for c in key)

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        options = self.get_display_options(field_config)
        field_key = str(field_config.get("key", ""))
        dom_id = self.field_id(field_config)
        try:
            engine = self.engine_for(field_config)
            cfg = self.client_config(field_config, data, options)
            problem = None
        except (ViewerDataError, ValueError) as e:
            engine, cfg, problem = None, {}, str(e)

        # No height: the library sizes itself (igv grows with its tracks).
        height = css_length(options.get("height"), "")
        stage_style = (f' style="height: {html.escape(height, quote=True)}"' if height
                       else "")
        if problem is not None:
            # Still a .potato-viewer, so the selection API exists and a bound
            # scheme can say why there is nothing to select.
            client = {"field": field_key, "kind": self.name, "error": problem}
            return (
                f'<div class="potato-viewer pv-failed" id="{dom_id}" '
                f'data-viewer-kind="{self.name}" '
                f'data-viewer-field="{html.escape(field_key, quote=True)}" '
                f"data-viewer-config='{html.escape(json.dumps(client), quote=True)}'>"
                f'<p class="pv-message pv-error" role="alert">{html.escape(problem)}</p>'
                f'</div>')

        client = dict(cfg)
        client.update({
            "field": field_key,
            "kind": self.name,
            "engine": engine.name,
            "engineLabel": engine.label,
            "webgl": engine.webgl,
            "assets": [{"type": a.kind, "src": a.url()} for a in engine.assets],
        })
        # Extras first: they may consume private keys ("_residues") that must
        # not reach the JSON attribute.
        extras = self.render_extras(field_config, data, options, client)
        side = self.render_side(field_config, data, options, client)
        client = {k: v for k, v in client.items() if not k.startswith("_")}
        label = html.escape(field_config.get("label") or self.description, quote=True)
        return (
            f'<div class="potato-viewer" id="{dom_id}" data-viewer-kind="{self.name}" '
            f'data-viewer-field="{html.escape(field_key, quote=True)}" '
            f'data-viewer-state="loading" '
            f"data-viewer-config='{html.escape(json.dumps(client), quote=True)}'>"
            f'<div class="pv-main">'
            f'<div class="pv-stage-wrap{"" if height else " pv-auto-height"}"{stage_style}>'
            f'<div class="pv-stage" role="img" aria-label="{label}"></div>'
            f'<p class="pv-message pv-loading" role="status">Loading {html.escape(engine.label)}…</p>'
            f'</div>'
            f'{side}'
            f'</div>'
            f'<p class="pv-status" aria-live="polite"></p>'
            f'{extras}'
            f'</div>')

    def render_side(self, field_config, data, options, cfg) -> str:
        """HTML beside the stage (e.g. a PAE image). Empty by default."""
        return ""

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        classes.append("viewer-display-container")
        return classes

    def validate_config(self, field_config: Dict[str, Any]) -> List[str]:
        errors = super().validate_config(field_config)
        errors.extend(validate_viewer_field(field_config, "instance_display.fields[]",
                                            display=self, check_bundles=False))
        return errors


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def viewer_display(kind: str) -> Optional[ViewerDisplay]:
    """The registered ViewerDisplay for a display type name, or None."""
    try:
        from .registry import display_registry
    except ImportError:
        return None
    entry = display_registry.get(kind)
    renderer = getattr(entry, "renderer", entry)
    return renderer if isinstance(renderer, ViewerDisplay) else None


def viewer_fields(config: Dict[str, Any]) -> List[Tuple[int, Dict[str, Any], ViewerDisplay]]:
    """``(index, field, display)`` for every viewer field in instance_display."""
    fields = ((config or {}).get("instance_display") or {}).get("fields") or []
    out = []
    if not isinstance(fields, list):
        return out
    for i, f in enumerate(fields):
        if isinstance(f, dict):
            display = viewer_display(str(f.get("type", "")))
            if display is not None:
                out.append((i, f, display))
    return out


def display_required_bundles(config: Dict[str, Any]) -> List[str]:
    """Fetchable bundles the config's viewer displays need."""
    names: List[str] = []
    for _i, f, display in viewer_fields(config):
        names.extend(display.required_bundles(f))
    return list(dict.fromkeys(names))


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def validate_viewer_field(field_config: Dict[str, Any], path: str,
                          display: Optional[ViewerDisplay] = None,
                          check_bundles: bool = True) -> List[str]:
    """Problems with one viewer field's options, and missing bundles."""
    display = display or viewer_display(str(field_config.get("type", "")))
    if display is None:
        return []
    errors: List[str] = []
    options = display.get_display_options(field_config)
    name = options.get("engine") or display.default_engine
    if name not in display.engines:
        errors.append(f"{path}.engine '{name}' is not an engine for {display.name}; "
                      f"use one of: {', '.join(sorted(display.engines))}")
        return errors
    if not isinstance(options.get("allow_remote", False), bool):
        errors.append(f"{path}.allow_remote must be true or false")
    errors.extend(display.validate_options(options, path))
    if check_bundles:
        from potato import vendoring
        missing = vendoring.missing(display.engines[name].bundles)
        if missing:
            errors.append(
                f"{path}: {display.name} with engine '{name}' needs the browser "
                f"library {', '.join(missing)}, which is not installed. Install it "
                f"with `{vendoring.fetch_hint(missing)}`.")
    return errors


def validate_viewer_config(config: Dict[str, Any]) -> List[str]:
    """Every viewer field and every ``viewer_selection`` scheme in a config."""
    errors: List[str] = []
    viewers = {}
    for i, f, display in viewer_fields(config):
        errors.extend(validate_viewer_field(f, f"instance_display.fields[{i}]", display))
        viewers[str(f.get("key", ""))] = display

    from potato.server_utils.schemas.viewer_selection import iter_viewer_selection_schemes
    for path, scheme in iter_viewer_selection_schemes(config):
        target = scheme.get("viewer_field")
        if not isinstance(target, str) or not target:
            continue        # the scheme's own validator reports this
        if target not in viewers:
            known = ", ".join(sorted(viewers)) or "none"
            errors.append(
                f"{path}.viewer_field '{target}' does not name a viewer display "
                f"field in instance_display (viewer fields: {known})")
    # peak_picking binds to a spectrum display the same way.
    from potato.server_utils.schemas.peak_picking import validate_binding
    errors.extend(validate_binding(config))
    # interval_label binds to a time_series display.
    from potato.server_utils.schemas.interval_label import validate_binding as _signal_binding
    errors.extend(_signal_binding(config))
    return errors


# ---------------------------------------------------------------------------
# Selections
# ---------------------------------------------------------------------------

def validate_selection(kind: str, value: Any, labels: Optional[List[str]] = None,
                       min_selections: Optional[int] = None,
                       max_selections: Optional[int] = None) -> List[str]:
    """Problems with a stored selection for viewer ``kind``.

    The stored shape is ``{"viewer": kind, "items": [...], <context keys>}``.
    An empty list means valid. ``value`` may be the JSON text or the object.
    """
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except ValueError:
            return ["selection is not valid JSON"]
    if not isinstance(value, dict):
        return ["selection must be an object with an 'items' list"]
    display = viewer_display(kind)
    if display is None:
        return [f"'{kind}' is not a viewer display type"]
    errors: List[str] = []
    if value.get("viewer") not in (None, kind):
        errors.append(f"selection was made in a '{value.get('viewer')}' viewer, not '{kind}'")
    allowed = {"viewer", "items"} | set(display.selection_context)
    extra = sorted(set(value) - allowed)
    if extra:
        errors.append(f"unexpected key(s) {', '.join(extra)}")
    items = value.get("items", [])
    if not isinstance(items, list):
        return errors + ["'items' must be a list"]
    seen = set()
    for n, item in enumerate(items):
        where = f"items[{n}]"
        if not isinstance(item, dict):
            errors.append(f"{where} must be an object")
            continue
        errors.extend(display.validate_item(item, where))
        if "label" in item:
            label = item["label"]
            if not isinstance(label, str):
                errors.append(f"{where}.label must be a string")
            elif labels and label not in labels:
                errors.append(f"{where}.label '{label}' is not one of: {', '.join(labels)}")
        key = json.dumps({k: v for k, v in item.items() if k != "label"}, sort_keys=True)
        if key in seen:
            errors.append(f"{where} repeats an earlier item")
        seen.add(key)
    errors.extend(display.validate_context(value))
    if min_selections is not None and len(items) < min_selections:
        errors.append(f"needs at least {min_selections} selection(s), has {len(items)}")
    if max_selections is not None and len(items) > max_selections:
        errors.append(f"allows at most {max_selections} selection(s), has {len(items)}")
    return errors


def resolve_source(value: Any, allow_remote: bool, what: str,
                   config: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[str]]:
    """``(url, local_path)`` for a file named in item data.

    A bare or ``media/`` path resolves inside ``media_directory`` and is
    served from ``/media/``. An http(s) URL is passed to the browser only
    when ``allow_remote`` is on; Potato itself never fetches it.
    """
    from potato.media.paths import media_href, resolve_media_url
    ref = str(value or "").strip()
    if not ref:
        raise ViewerDataError(f"This item has no {what}.")
    if ref.startswith(("http://", "https://", "//")):
        if not allow_remote:
            raise ViewerDataError(
                f"The {what} for this item is a remote URL, and remote files are "
                f"turned off. Download it into the media directory, or set "
                f"allow_remote: true on this display to let the browser fetch it.")
        return ref, None
    if config is None:
        try:
            from potato.server_utils.config_module import config as live_config
            config = live_config
        except ImportError:   # pragma: no cover - bare import path
            config = {}
    url = media_href(config, ref, context="viewer")
    path = resolve_media_url(config, url, context="viewer")
    if path is None:
        raise ViewerDataError(
            f"The {what} '{ref}' is not in the media directory, so the browser "
            f"cannot load it. Put the file under media_directory and name it "
            f"relative to that.")
    return url, path
