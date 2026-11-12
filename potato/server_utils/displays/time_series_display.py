"""
Time series display (``type: time_series``).

Draws a multi-channel signal (EEG, PSG, ECG, accelerometer, a light curve)
with uPlot, one lane per channel or all channels on one axis. The browser
never receives the recording: it asks ``/api/signals/window`` for the
visible range at its own pixel width and gets min/max-decimated samples back
(:mod:`potato.science.signals`).

The item field holds a signal file (EDF/EDF+, BDF, WFDB ``.hea``, CSV,
Parquet, or a JSON file in the inline shape), resolved inside
``media_directory`` or the task directory, or the inline object itself::

    {"sampling_rate": 100, "start_time": "2024-01-01T22:00:00",
     "channels": [{"name": "Fz", "unit": "uV", "data": [...]}]}

The display is a viewer display (:mod:`.viewer_display`): the framework
loads uPlot when it mounts, and the ``interval_label`` scheme draws its
labels on it through ``window.PotatoTimeSeries.get(field)``.

Engine: uPlot 1.6.32, MIT, committed under ``potato/static/vendor/uplot-1.6.32/``.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List

from .viewer_display import ViewerAsset, ViewerDataError, ViewerDisplay, ViewerEngine

LAYOUTS = ("stacked", "overlay")
DRAW_STYLES = ("line", "points")
AMPLITUDE_MODES = ("recording", "window")
TIME_FORMATS = ("auto", "clock", "elapsed", "number")
CHANNEL_KEYS = {"name", "label", "range", "color"}


def _positive_number(v) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and v > 0


class TimeSeriesDisplay(ViewerDisplay):
    name = "time_series"
    description = "Multi-channel signal (EEG, ECG, sensors, light curves) with zoom, pan and labelled overlays"
    required_fields = ["key"]
    optional_fields = {
        **ViewerDisplay.COMMON_OPTIONS,
        "engine": "uplot",
        "height": None,
        "channels": None,
        "window": 30,
        "layout": "stacked",
        "draw": "line",
        "amplitude": "recording",
        "lane_height": 56,
        "time_format": "auto",
        "time_unit": "s",
        "invert_y": False,
        "time_column": None,
        "annotation_extension": "atr",
        "max_file_mb": 2048,
        "overview": True,
    }
    default_engine = "uplot"
    engines = {
        "uplot": ViewerEngine(
            name="uplot", label="uPlot", webgl=None, licence="MIT",
            assets=(ViewerAsset("style", "vendor/uplot-1.6.32/uPlot.min.css"),
                    ViewerAsset("script", "vendor/uplot-1.6.32/uPlot.iife.min.js"))),
    }

    # -- options ------------------------------------------------------------------

    def validate_options(self, options: Dict[str, Any], path: str) -> List[str]:
        errors = []
        if options.get("allow_remote"):
            errors.append(f"{path}.allow_remote: time_series reads its files on the server "
                          f"and never from a URL; remove allow_remote")
        chans = options.get("channels")
        if chans is not None:
            if not isinstance(chans, list) or not chans:
                errors.append(f"{path}.channels must be a non-empty list of channel names "
                              f"(or mappings with name, label, range, color)")
            else:
                seen = set()
                for n, c in enumerate(chans):
                    where = f"{path}.channels[{n}]"
                    name = c.get("name") if isinstance(c, dict) else c
                    if not isinstance(name, str) or not name:
                        errors.append(f"{where} must be a channel name or a mapping with name")
                        continue
                    if name in seen:
                        errors.append(f"{where}: channel '{name}' is listed twice")
                    seen.add(name)
                    if isinstance(c, dict):
                        extra = sorted(set(c) - CHANNEL_KEYS)
                        if extra:
                            errors.append(f"{where} has unknown key(s) {', '.join(extra)}; "
                                          f"accepted: {', '.join(sorted(CHANNEL_KEYS))}")
                        r = c.get("range")
                        if r is not None and not (isinstance(r, list) and len(r) == 2
                                                  and all(not isinstance(x, bool) and isinstance(x, (int, float)) for x in r)
                                                  and r[1] > r[0]):
                            errors.append(f"{where}.range must be [low, high] with high > low")
                        for key in ("label", "color"):
                            if key in c and not isinstance(c[key], str):
                                errors.append(f"{where}.{key} must be text")
        if not _positive_number(options.get("window")):
            errors.append(f"{path}.window must be a positive number of seconds (the visible span)")
        for key, allowed in (("layout", LAYOUTS), ("draw", DRAW_STYLES),
                             ("amplitude", AMPLITUDE_MODES), ("time_format", TIME_FORMATS)):
            if options.get(key) not in allowed:
                errors.append(f"{path}.{key} must be one of {', '.join(allowed)}")
        lh = options.get("lane_height")
        if isinstance(lh, bool) or not isinstance(lh, int) or not 20 <= lh <= 400:
            errors.append(f"{path}.lane_height must be a whole number of pixels from 20 to 400")
        h = options.get("height")
        if h is not None and (isinstance(h, bool) or not isinstance(h, int) or not 80 <= h <= 4000):
            errors.append(f"{path}.height must be a whole number of pixels from 80 to 4000")
        for key in ("invert_y", "overview"):
            if not isinstance(options.get(key), bool):
                errors.append(f"{path}.{key} must be true or false")
        if not isinstance(options.get("time_unit"), str) or not options.get("time_unit"):
            errors.append(f"{path}.time_unit must be text such as s or d")
        tc = options.get("time_column")
        if tc is not None and (not isinstance(tc, str) or not tc):
            errors.append(f"{path}.time_column must be a column name")
        ae = options.get("annotation_extension")
        if ae is not None and (not isinstance(ae, str) or not ae.isalnum()):
            errors.append(f"{path}.annotation_extension must be a WFDB annotator name such as "
                          f"atr, or null for none")
        mb = options.get("max_file_mb")
        if not _positive_number(mb):
            errors.append(f"{path}.max_file_mb must be a positive number of megabytes")
        return errors

    # -- rendering -------------------------------------------------------------------

    def client_config(self, field_config, data, options):
        from potato.science.signal_store import channel_indices, open_signal
        from potato.science.signals import SignalError
        from potato.science.converters import ConverterUnavailable
        try:
            from potato.server_utils.config_module import config as live_config
        except ImportError:   # pragma: no cover
            live_config = {}
        try:
            _key, rec = open_signal(live_config, data, options)
            wanted = options.get("channels") or None
            names = [c["name"] if isinstance(c, dict) else c for c in wanted] if wanted else None
            idx = channel_indices(rec, names)
        except (SignalError, ConverterUnavailable, OSError) as e:
            raise ViewerDataError(f"Cannot show this signal: {e}")
        overrides = {}
        for c in wanted or []:
            if isinstance(c, dict):
                overrides[c["name"]] = {k: c[k] for k in ("label", "range", "color") if k in c}
        channels = []
        for i in idx:
            ch = rec.channels[i]
            entry = {"name": ch.name, "unit": ch.unit, "rate": ch.sampling_rate}
            entry.update(overrides.get(ch.name, {}))
            channels.append(entry)
        lanes = len(channels) if options.get("layout") == "stacked" else 1
        height = (options.get("_plot_height") or options.get("height")
                  or max(160, min(1400, lanes * int(options.get("lane_height") or 56) + 48)))
        return {
            "channels": channels,
            "tStart": rec.t_start,
            "tEnd": rec.t_end,
            "startTime": rec.start_time,
            "format": rec.format,
            "warnings": rec.warnings,
            "window": float(options.get("window") or 30),
            "layout": options.get("layout"),
            "draw": options.get("draw"),
            "amplitude": options.get("amplitude"),
            "timeFormat": options.get("time_format"),
            "timeUnit": options.get("time_unit"),
            "invertY": bool(options.get("invert_y")),
            "overview": bool(options.get("overview")),
            "plotHeight": int(height),
            "api": "/api/signals/window",
        }

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        # ``height`` is the plot's height; the stage around it (toolbar, plot,
        # overview strip) sizes itself, so the base class must not fix it.
        height = self.get_display_options(field_config).get("height")
        field_config = dict(field_config)
        opts = dict(field_config.get("display_options") or {})
        opts["height"] = None
        opts["_plot_height"] = height
        field_config["display_options"] = opts
        field_config.pop("height", None)
        return super().render(field_config, data)

    def render_extras(self, field_config, data, options, cfg) -> str:
        warnings = cfg.get("warnings") or []
        if not warnings:
            return ""
        items = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
        return f'<ul class="ts-warnings" role="note">{items}</ul>'
