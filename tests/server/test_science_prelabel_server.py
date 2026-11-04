"""A trained model's peaks and intervals reach the page on the terms every
prelabel does: shown to an annotator who may see machine answers, and to
nobody held out from them (``ai_support.holdout``)."""

import json
import math

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (cleanup_test_directory, create_test_config,
                                      create_test_data_file, create_test_directory)

SCHEMES = [
    {"annotation_type": "peak_picking", "name": "picks", "description": "Pick the peaks",
     "viewer_field": "spectrum"},
    {"annotation_type": "interval_label", "name": "segs", "description": "Mark artefacts",
     "signal_field": "signal", "mode": "free",
     "labels": [{"name": "artefact"}, {"name": "spindle"}]},
]


def _items():
    xs = [i / 100.0 for i in range(1000)]
    spectrum = {"x": xs, "y": [math.exp(-0.5 * ((x - 4.0) / 0.05) ** 2) + 0.01 for x in xs],
                "x_units": "PPM"}
    signal = {"sampling_rate": 10, "channels": [
        {"name": "Fz", "data": [math.sin(k / 3.0) for k in range(300)]}]}
    predictions = {
        "picks": {"peaks": [{"x": 4.0, "confidence": 0.9}], "source": "model"},
        "segs": {"intervals": [{"start": 3.0, "end": 6.0, "label": "artefact",
                                "channel": None, "source": "model"}], "events": []}}
    return [{"id": "item_%d" % n, "text": "item %d" % n, "spectrum": spectrum,
             "signal": signal, "predictions": predictions} for n in range(1, 3)]


def _server(name, fraction):
    test_dir = create_test_directory(name)
    data_file = create_test_data_file(test_dir, _items())
    port = find_free_port(preferred_port=9897)
    extra = {"pre_annotation": {"enabled": True, "field": "predictions"},
             "instance_display": {"fields": [
                 {"key": "spectrum", "type": "spectrum", "display_options": {"prepick": True}},
                 {"key": "signal", "type": "time_series"}]}}
    if fraction is not None:
        extra["ai_support"] = {"enabled": False,
                               "holdout": {"fraction": fraction, "salt": "test"}}
    config_file = create_test_config(test_dir, SCHEMES, data_files=[data_file], port=port,
                                     additional_config=extra)
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start server")
    return server, test_dir


def _login(server, name):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": name, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": name, "pass": "pw"})
    return s


def _suggestions(page):
    """The spectrum display's suggestions, from its client config on the page."""
    marker = '"suggestions": '
    start = page.index(marker) + len(marker)
    depth, end = 0, start
    for end, ch in enumerate(page[start:], start):
        depth += ch == "["
        depth -= ch == "]"
        if depth == 0:
            break
    return json.loads(page[start:end + 1].replace("&#34;", '"'))


def _intervals(session, server):
    r = session.get(f"{server.base_url}/api/signals/preannotations",
                    params={"instance_id": "item_1", "field": "signal", "schema": "segs"})
    assert r.status_code == 200, r.text
    return r.json()["intervals"]


@pytest.fixture
def open_server():
    server, test_dir = _server("science_prelabel_open", None)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture
def held_out_server():
    server, test_dir = _server("science_prelabel_held_out", 1.0)
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


def test_the_model_s_peaks_and_intervals_reach_the_page(open_server):
    s = _login(open_server, "sees_models")
    page = s.get(f"{open_server.base_url}/annotate").text
    assert '"suggestionMethod": "model"' in page.replace("&#34;", '"')
    assert [(p["x"], p["source"]) for p in _suggestions(page)] == [(4.0, "model")]
    assert _intervals(s, open_server) == [
        {"start": 3.0, "end": 6.0, "label": "artefact", "channel": None, "source": "model"}]


def test_a_held_out_annotator_sees_neither(held_out_server):
    s = _login(held_out_server, "held_out")
    page = s.get(f"{held_out_server.base_url}/annotate").text.replace("&#34;", '"')
    # The detector's suggestions, not the model's.
    assert '"suggestionMethod": "detect"' in page
    assert all(p.get("source") != "model" for p in _suggestions(page))
    assert _intervals(s, held_out_server) == []
