"""Signal readers, windows, pre-annotations, the interval_label scheme and its exports.

Fixtures in tests/data/signals/ were written by independent tools
(make_fixtures.py: pyedflib for EDF+/BDF+, wfdb for the WFDB record), so the
readers here are checked against files they did not write.
"""

import json
import math
import os

import numpy as np
import pytest

from potato.science.signals import (InMemoryRecording, SignalError, from_inline,
                                    normalize_annotations, window)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data", "signals")


@pytest.fixture
def tmp(tmp_path_factory):
    from tests.helpers.test_utils import create_test_directory
    return create_test_directory("signals_unit")


# ---------------------------------------------------------------------------
# EDF / BDF
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,tol", [("pyedflib_edfplus.edf", 0.02), ("pyedflib_bdfplus.bdf", 1e-3)])
def test_edf_and_bdf_written_by_pyedflib(name, tol):
    from potato.science.converters.edf import read_edf
    rec = read_edf(os.path.join(DATA, name))
    assert [c.name for c in rec.channels] == ["Fz", "Resp"]
    assert [c.sampling_rate for c in rec.channels] == [128.0, 8.0]
    assert [c.unit for c in rec.channels] == ["uV", "mV"]
    assert rec.duration == 20.0
    t = np.arange(2560) / 128
    assert np.max(np.abs(rec.read(0, 0, 2560) - 200 * np.sin(2 * np.pi * 3 * t))) < tol
    tr = np.arange(160) / 8
    assert np.max(np.abs(rec.read(1, 0, 160) - 1.5 * np.sin(2 * np.pi * 0.25 * tr))) < tol
    assert rec.annotations == {
        "intervals": [{"start": 2.0, "end": 7.0, "label": "Sleep stage W", "channel": None, "source": "file"}],
        "events": [{"time": 9.5, "label": "Arousal", "channel": None, "source": "file"}]}


def _edf(path, **kw):
    from potato.science.converters.edf import write_edf
    t = np.arange(0, 10, 0.01)
    write_edf(path, [{"label": "C3", "unit": "uV", "fs": 100, "data": 50 * np.sin(t),
                      "physical_min": -100, "physical_max": 100}], **kw)


def test_edf_plus_d_places_records_at_their_onsets(tmp):
    from potato.science.converters.edf import read_edf
    p = os.path.join(tmp, "d.edf")
    # 10 one-second records; records 5..9 start 20 s later than they would.
    _edf(p, record_onsets=[0, 1, 2, 3, 4, 25, 26, 27, 28, 29])
    rec = read_edf(p)
    assert rec.discontinuous and rec.t_end == 30.0
    assert rec.index_at(0, 4.995) == 500          # first sample after the first segment
    assert rec.index_at(0, 10.0) == 500           # inside the gap: the next segment
    assert rec.sample_times(0, 499, 502).tolist() == pytest.approx([4.99, 25.0, 25.01])
    assert rec.gaps(0, 0, 30) == [[5.0, 25.0]]
    w = window(rec, 0, 30, 100)["channels"][0]
    assert w["gaps"] == [[5.0, 25.0]]
    assert all(not (5.0 < t < 25.0) for t in w["t"])


def test_edf_header_errors_are_clear(tmp):
    from potato.science.converters.edf import read_edf
    p = os.path.join(tmp, "ok.edf")
    _edf(p)
    raw = open(p, "rb").read()

    def bad(data, needle):
        q = os.path.join(tmp, "bad.edf")
        open(q, "wb").write(data)
        with pytest.raises(SignalError, match=needle):
            read_edf(q)

    bad(b"9" + raw[1:], "not an EDF file")
    bad(raw[:252] + b"x   " + raw[256:], "number of signals")
    bad(raw[:184] + b"1024    " + raw[192:], "header size field")
    bad(raw[:100], "shorter than an EDF header")
    with pytest.raises(SignalError, match="over the"):
        read_edf(p, max_bytes=1000)
    # A truncated file is read up to its last complete record, with a warning.
    q = os.path.join(tmp, "short.edf")
    rec_bytes = read_edf(p).header["record_bytes"]
    open(q, "wb").write(raw[:-(rec_bytes + 10)])          # the last record and a bit of the one before
    rec = read_edf(q)
    assert rec.channels[0].n_samples == 800 and "holds 8" in rec.warnings[0]


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def _long(n=64 * 1024 * 8, fs=256.0):
    rng = np.random.default_rng(1)
    v = rng.standard_normal(n)
    rec = InMemoryRecording()
    rec.add_channel("x", v, sampling_rate=fs)
    return rec, v


def test_window_minmax_matches_brute_force():
    rec, v = _long()
    n, fs = v.size, 256.0
    px = 128                     # 4096 samples per bucket: 4 blocks of 1024, exactly
    w = window(rec, 0, n / fs, px)["channels"][0]
    assert len(w["t"]) == px and "lo" in w
    buckets = v.reshape(px, -1)
    assert np.allclose(w["lo"], buckets.min(axis=1), rtol=1e-5)
    assert np.allclose(w["hi"], buckets.max(axis=1), rtol=1e-5)


def test_short_window_returns_the_samples_themselves():
    rec, v = _long()
    w = window(rec, 10.0, 11.0, 800)["channels"][0]
    assert "v" in w and "lo" not in w
    # One sample beyond each edge, then every sample in between.
    assert w["t"][0] == pytest.approx(10.0 - 1 / 256) and len(w["t"]) == 256 + 2
    assert w["v"][1] == pytest.approx(float(f"{v[2560]:.6g}"))


def test_window_never_sends_more_than_two_values_per_pixel():
    rec, _v = _long()
    for start, end, px in ((0, 2048, 300), (100, 900, 1000), (0, 20, 50)):
        w = window(rec, start, end, px)["channels"][0]
        assert len(w["t"]) <= 2 * px + 2


def test_irregular_series_and_nan():
    rec = InMemoryRecording()
    rec.add_channel("mag", [18.2, float("nan"), 18.5, 18.1], times=[0.0, 1.5, 7.25, 30.0])
    w = window(rec, 0, 31, 100)["channels"][0]
    assert w["t"] == [0.0, 1.5, 7.25, 30.0] and w["v"][1] is None


# ---------------------------------------------------------------------------
# WFDB, BIDS, CSV, Parquet, inline
# ---------------------------------------------------------------------------

def test_wfdb_record_and_annotations():
    pytest.importorskip("wfdb")
    from potato.science.converters.wfdb_record import read_wfdb
    rec = read_wfdb(os.path.join(DATA, "rec1.hea"))
    assert [c.name for c in rec.channels] == ["MLII", "V5"]
    assert rec.channels[0].sampling_rate == 250.0 and rec.duration == 10.0
    assert rec.read(0, 100, 101)[0] == pytest.approx(1.2 + 0.05 * math.sin(2 * math.pi * 0.4), abs=1e-3)
    ev = rec.annotations["events"]
    assert [e["label"] for e in ev[:6]] == ["N", "N", "N", "N", "V", "N"] and ev[0]["time"] == 0.4
    assert [(i["start"], i["end"], i["label"]) for i in rec.annotations["intervals"]] == [
        (0.0, 5.0, "N"), (5.0, 10.0, "AFIB")]


def test_wfdb_header_naming_a_file_elsewhere_is_refused(tmp):
    pytest.importorskip("wfdb")
    from potato.science.converters.wfdb_record import read_wfdb
    hea = os.path.join(tmp, "evil.hea")
    with open(hea, "w") as f:
        f.write("evil 1 250 10\n../../secret.dat 16 200/mV 16 0 0 0 0 I\n")
    with pytest.raises(SignalError, match="outside the record's directory"):
        read_wfdb(hea)


def test_wfdb_missing_library_names_the_extra(monkeypatch):
    import builtins
    from potato.science.converters import ConverterUnavailable
    from potato.science.converters import wfdb_record
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "wfdb":
            raise ImportError("no wfdb")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(ConverterUnavailable, match=r"potato-annotation\[signals\]"):
        wfdb_record.read_wfdb(os.path.join(DATA, "rec1.hea"))


def test_bids_events_read_and_write_round_trip(tmp):
    from potato.science.converters.bids_events import parse_bids_events, read_bids_events, write_bids_events
    got = parse_bids_events("onset\tduration\ttrial_type\tvalue\tchannel\n"
                            "1.5\t2\tspindle\tn/a\tC3\n4\tn/a\tn/a\tblink\tn/a\n6\t0\tn/a\tn/a\tn/a\n")
    assert got["intervals"] == [{"start": 1.5, "end": 3.5, "label": "spindle", "channel": "C3", "source": "file"}]
    assert [(e["time"], e["label"], e["channel"]) for e in got["events"]] == [(4.0, "blink", None), (6.0, "event", None)]
    p = os.path.join(tmp, "x_events.tsv")
    write_bids_events(got, p)
    assert open(p).read().splitlines() == ["onset\tduration\ttrial_type\tchannel", "1.5\t2\tspindle\tC3",
                                           "4\t0\tblink\tn/a", "6\t0\tevent\tn/a"]
    assert read_bids_events(p)["intervals"][0]["end"] == 3.5
    with pytest.raises(SignalError, match="no 'duration' column"):
        parse_bids_events("onset\ttrial_type\n1\ta\n")
    with pytest.raises(SignalError, match="not a number"):
        parse_bids_events("onset\tduration\nsoon\t1\n")


def test_csv_regular_irregular_and_datetime(tmp):
    from potato.science.converters.tabular_signal import read_csv_signal
    p = os.path.join(tmp, "a.csv")
    with open(p, "w") as f:
        f.write("time,ax (g),ay [m/s^2]\n" + "".join(f"{i / 50:.2f},{i},{-i}\n" for i in range(100)))
    rec = read_csv_signal(p)
    assert [(c.name, c.unit, c.sampling_rate) for c in rec.channels] == [("ax", "g", pytest.approx(50.0)),
                                                                           ("ay", "m/s^2", pytest.approx(50.0))]
    assert rec.read(1, 10, 11)[0] == -10
    q = os.path.join(tmp, "lc.csv")
    open(q, "w").write("mjd,mag\n59000.1,18.2\n59000.4,18.4\n59003.0,18.1\n")
    rec = read_csv_signal(q)
    assert rec.channels[0].sampling_rate is None and rec.t_start == pytest.approx(59000.1)
    r = os.path.join(tmp, "dt.csv")
    open(r, "w").write("timestamp,hr\n2024-01-01T22:00:00,60\n2024-01-01T22:00:02,61\n2024-01-01T22:00:04,62\n")
    rec = read_csv_signal(r)
    assert rec.start_time == "2024-01-01T22:00:00" and rec.channels[0].sampling_rate == pytest.approx(0.5)
    s = os.path.join(tmp, "desc.csv")
    open(s, "w").write("t,x\n2,1\n1,2\n")
    with pytest.raises(SignalError, match="ascending"):
        read_csv_signal(s)


def test_parquet(tmp):
    pytest.importorskip("pyarrow")
    import pandas as pd
    from potato.science.converters.tabular_signal import read_parquet_signal
    p = os.path.join(tmp, "a.parquet")
    pd.DataFrame({"t": np.arange(10) / 10, "x": np.arange(10.0)}).to_parquet(p)
    rec = read_parquet_signal(p)
    assert rec.channels[0].sampling_rate == pytest.approx(10.0) and rec.read(0, 3, 4)[0] == 3.0


def test_inline_shape_and_its_errors():
    rec = from_inline({"sampling_rate": 4, "channels": [{"name": "a", "unit": "uV", "data": [1, 2, None, 4]}],
                       "annotations": [{"start": 0, "end": 0.5, "label": "x"}, {"time": 0.25, "label": "y"}]})
    assert rec.duration == 1.0 and rec.annotations["events"][0]["label"] == "y"
    with pytest.raises(SignalError, match="unknown key"):
        from_inline({"channels": [{"name": "a", "data": [1]}], "rate": 4})
    with pytest.raises(SignalError, match="sampling_rate"):
        from_inline({"channels": [{"name": "a", "data": [1]}]})
    with pytest.raises(SignalError, match="more than"):
        from_inline({"sampling_rate": 1, "channels": [{"name": "a", "data": [0] * 500_001}]})


def test_normalize_annotations_drops_or_refuses_bad_entries():
    bad = {"intervals": [{"start": 2, "end": 1, "label": "x"}], "events": [{"time": "soon", "label": "y"}]}
    with pytest.raises(SignalError):
        normalize_annotations(bad)
    assert normalize_annotations(bad, strict=False) == {"intervals": [], "events": []}


def test_converter_table():
    from potato.science.converters import converter_for
    from potato.science.converters.bids_events import read_bids_events
    from potato.science.converters.edf import read_edf
    assert converter_for("night.EDF") is read_edf and converter_for("x.bdf") is read_edf
    assert converter_for("sub-01_task-sleep_events.tsv") is read_bids_events


# ---------------------------------------------------------------------------
# Store: paths and pre-annotations
# ---------------------------------------------------------------------------

def _config(tmp):
    media = os.path.join(tmp, "media")
    os.makedirs(media, exist_ok=True)
    return {"task_dir": tmp, "media_directory": "media"}, media


def test_preannotations_keep_only_labels_the_scheme_declares(tmp):
    """A second scheme on the same recording (labels a, b) was handed the
    file's sleep stages, which it has no button for, and they reached the
    export. A label is kept only where the scheme declares it, as that kind."""
    from potato.science.signal_store import open_signal, preannotations
    cfg, media = _config(tmp)
    _edf(os.path.join(media, "a.edf"),
         annotations=[(0, 30, "Sleep stage 2"), (30, 30, "Sleep stage W"), (12, 0, "Arousal")])
    _key, rec = open_signal(cfg, "a.edf")
    other = {"labels": ["a", "b"]}
    assert preannotations(cfg, other, {}, rec) == {"intervals": [], "events": []}
    stages = {"labels": ["N2", "W", {"name": "arousal", "kind": "event"}],
              "preannotation_labels": {"Sleep stage 2": "N2", "Sleep stage W": "W",
                                       "Arousal": "arousal"}}
    got = preannotations(cfg, stages, {}, rec)
    assert [i["label"] for i in got["intervals"]] == ["N2", "W"]
    assert [e["label"] for e in got["events"]] == ["arousal"]
    # An event label does not admit an interval of the same name.
    as_interval = {"labels": [{"name": "N2", "kind": "event"}],
                   "preannotation_labels": {"Sleep stage 2": "N2"}}
    assert preannotations(cfg, as_interval, {}, rec)["intervals"] == []


def test_signal_paths_stay_inside_the_project(tmp):
    from potato.science.signal_store import open_signal, resolve_signal_path
    cfg, media = _config(tmp)
    _edf(os.path.join(media, "a.edf"))
    assert resolve_signal_path(cfg, "a.edf") == os.path.realpath(os.path.join(media, "a.edf"))
    assert open_signal(cfg, "media/a.edf")[1].channels[0].name == "C3"
    for ref, needle in (("../../etc/passwd", "outside"), ("/etc/passwd", "absolute"),
                        ("https://x.org/a.edf", "local"), ("missing.edf", "not found")):
        with pytest.raises(SignalError, match=needle):
            resolve_signal_path(cfg, ref)


def test_preannotations_rename_drop_and_bids_field(tmp):
    from potato.science.signal_store import open_signal, preannotations
    cfg, media = _config(tmp)
    _edf(os.path.join(media, "a.edf"), annotations=[(0, 5, "Sleep stage W"), (3, 0, "Arousal")])
    open(os.path.join(media, "a_events.tsv"), "w").write("onset\tduration\ttrial_type\n1\t2\tspindle\n")
    _key, rec = open_signal(cfg, "a.edf")
    scheme = {"labels": ["W", "spindle"],
              "preannotation_labels": {"Sleep stage W": "W", "Arousal": None},
              "preannotation_field": "events"}
    got = preannotations(cfg, scheme, {"events": "a_events.tsv"}, rec)
    assert [(i["start"], i["label"]) for i in got["intervals"]] == [(0.0, "W"), (1.0, "spindle")]
    assert got["events"] == []
    # The cached recording's own annotations were not rewritten.
    assert rec.annotations["intervals"][0]["label"] == "Sleep stage W"
    assert preannotations(cfg, {"pre_annotations": False}, {}, rec) == {"intervals": [], "events": []}


# ---------------------------------------------------------------------------
# Scheme, display, exports
# ---------------------------------------------------------------------------

def test_scheme_validation():
    from potato.server_utils.schemas.interval_label import labels_of, validate_scheme
    ok = {"name": "s", "description": "d", "signal_field": "sig", "labels": ["W", {"name": "N1", "key_value": "q"}]}
    assert validate_scheme(ok, "s") == []
    assert [(l["name"], l["key"]) for l in labels_of(ok)] == [("W", "1"), ("N1", "q")]
    errs = validate_scheme({"labels": [True, "a", "a", {"name": "b", "kind": "span", "key_value": "]"}],
                            "mode": "epochs", "epoch_length": 0, "channel_scope": "one",
                            "preannotation_labels": {"x": "nope"}}, "s")
    text = " ".join(errs)
    for needle in ("signal_field", "quote it", "appears twice", "kind must be", "mode must be",
                   "epoch_length", "channel_scope", "next/previous key", "not one of the labels"):
        assert needle in text, needle


def test_config_module_rejects_a_bad_scheme():
    from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
    with pytest.raises(ConfigValidationError, match="signal_field"):
        validate_single_annotation_scheme({"annotation_type": "interval_label", "name": "s",
                                           "description": "d", "labels": ["a"]}, "annotation_schemes[0]")


def test_generator_output():
    from potato.server_utils.schemas.registry import schema_registry
    html, keys = schema_registry.generate({"annotation_type": "interval_label", "name": "stage",
                                           "description": "Stage", "signal_field": "sig",
                                           "mode": "epoch", "labels": ["W", "N1"]})
    assert 'data-annotation-type="interval_label"' in html and 'class="annotation-input interval-label-input"' in html
    assert ("1", "stage: W") in keys and ("]", "stage: next window") in keys


def test_display_options_validation_and_inline_render():
    from potato.server_utils.displays.registry import display_registry
    d = display_registry.get("time_series").renderer
    errs = d.validate_options(d.get_display_options({"key": "s", "window": 0, "layout": "grid",
                                                     "channels": ["a", "a"], "lane_height": 5}), "f")
    text = " ".join(errs)
    for needle in ("window", "layout", "listed twice", "lane_height"):
        assert needle in text
    html = d.render({"key": "sig", "type": "time_series"},
                    {"sampling_rate": 10, "channels": [{"name": "a", "data": list(range(50))}]})
    assert 'data-viewer-kind="time_series"' in html and '&quot;tEnd&quot;: 5.0' in html
    broken = d.render({"key": "sig", "type": "time_series"}, "nowhere.edf")
    assert "pv-failed" in broken and "not found" in broken


def _ctx(answers):
    from potato.export.base import ExportContext
    schemes = [{"annotation_type": "interval_label", "name": "stage", "description": "d",
                "signal_field": "sig", "labels": [{"name": "W", "tooltip": "Wake"}, "N1"]}]
    anns = [{"user_id": u, "instance_id": i, "labels": {"stage": {"stage": json.dumps(a)}}}
            for (u, i), a in answers.items()]
    return ExportContext(config={}, annotations=anns, items={}, schemas=schemes, output_dir="")


def test_interval_and_bids_exports(tmp):
    from potato.export.signal_exporter import BIDSEventsExporter, IntervalLabelExporter
    ctx = _ctx({("ann1", "rec/01"): {"intervals": [{"start": 0, "end": 30, "label": "W", "channel": None}],
                                     "events": [{"time": 12.5, "label": "N1", "channel": "C3"}]}})
    res = IntervalLabelExporter().export(ctx, os.path.join(tmp, "iv"))
    assert res.success and res.stats["num_rows"] == 2
    lines = open(os.path.join(tmp, "iv", "intervals.csv")).read().splitlines()
    assert lines[1] == "ann1,rec/01,stage,interval,0.0,30.0,30.0,W,,annotator"
    assert lines[2] == "ann1,rec/01,stage,event,12.5,12.5,0,N1,C3,annotator"
    res = BIDSEventsExporter().export(ctx, os.path.join(tmp, "bids"))
    assert res.success
    tsv = open(os.path.join(tmp, "bids", "ann1", "rec_01_events.tsv")).read().splitlines()
    assert tsv == ["onset\tduration\ttrial_type\tchannel", "0\t30\tW\tn/a", "12.5\t0\tN1\tC3"]
    side = json.load(open(os.path.join(tmp, "bids", "events.json")))
    assert side["trial_type"]["Levels"] == {"W": "Wake", "N1": "N1"}
    empty = IntervalLabelExporter().export(_ctx({("a", "b"): {"intervals": [], "events": []}}), os.path.join(tmp, "e"))
    assert not empty.success


class TestSignalFieldBinding:
    """signal_field must name a time_series display field; checked at load."""

    def _config(self, field_type, signal_field="signal"):
        return {
            "instance_display": {"fields": [{"key": "signal", "type": field_type}]},
            "annotation_schemes": [{"annotation_type": "interval_label", "name": "stage",
                                    "signal_field": signal_field,
                                    "labels": ["Wake", "N1"]}],
        }

    def test_matching_field_passes(self):
        from potato.server_utils.displays.viewer_display import validate_viewer_config
        assert not [e for e in validate_viewer_config(self._config("time_series"))
                    if "signal_field" in e]

    def test_wrong_type_is_refused(self):
        from potato.server_utils.displays.viewer_display import validate_viewer_config
        errors = [e for e in validate_viewer_config(self._config("text")) if "signal_field" in e]
        assert errors == ["annotation_schemes[0].signal_field 'signal' does not name a "
                          "time_series display field in instance_display "
                          "(time_series fields: none)"]

    def test_missing_field_is_refused(self):
        from potato.server_utils.displays.viewer_display import validate_viewer_config
        errors = [e for e in validate_viewer_config(self._config("time_series", "eeg"))
                  if "signal_field" in e]
        assert len(errors) == 1 and "'eeg'" in errors[0] and "fields: signal" in errors[0]


def test_decode_answer_for_a_scheme_named_events():
    """{"events": "<json>"} is the stored shape of a scheme called events,
    not an answer with an "events" key holding a string."""
    import json as _json
    from potato.export.signal_exporter import decode_answer
    blob = _json.dumps({"intervals": [{"start": 1, "end": 12, "label": "apnea", "channel": None}],
                        "events": []})
    out = decode_answer({"events": {"events": blob}}, "events")
    assert out is not None and out["intervals"][0]["label"] == "apnea"
