"""spectrogram_annotation: generator output, config validation, pre-annotation."""

import json

import pytest
from bs4 import BeautifulSoup

from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
from potato.server_utils.schemas.registry import schema_registry

SCHEME = {"annotation_type": "spectrogram_annotation", "name": "calls", "description": "Box the calls",
          "labels": ["whistle", {"name": "trill", "color": "#d97706", "key_value": "t"}],
          "max_freq": 8000, "fft_size": 512}


def test_renders_hidden_data_input_and_config():
    html, keys = schema_registry.generate(dict(SCHEME))
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    assert form["data-annotation-type"] == "spectrogram_annotation"
    cfg = json.loads(form["data-spectrogram-config"])
    assert cfg["labels"] == [{"name": "whistle", "color": "#2563eb", "key": "1"},
                             {"name": "trill", "color": "#d97706", "key": "t"}]
    assert (cfg["maxFreq"], cfg["minFreq"], cfg["fftSize"], cfg["sourceField"]) == (8000.0, 0.0, 512, "audio_url")
    hidden = soup.find("input", {"name": "calls", "class": "annotation-data-input"})
    assert hidden is not None and hidden["type"] == "hidden"
    assert keys == []


def test_label_names_are_escaped():
    html, _ = schema_registry.generate(dict(SCHEME, labels=["<b>x</b>"]))
    assert "<b>x</b>" not in html


@pytest.mark.parametrize("change,message", [
    ({"labels": []}, "non-empty"),
    ({"labels": [True, False]}, "needs a name"),
    ({"labels": ["a", "a"]}, "duplicate"),
    ({"fft_size": 1000}, "fft_size"),
    ({"colormap": "jet"}, "colormap"),
    ({"min_freq": 9000}, "above min_freq"),
    ({"max_boxes": 1, "min_boxes": 2}, "at least min_boxes"),
])
def test_config_validation_rejects(change, message):
    with pytest.raises(ConfigValidationError, match=message):
        validate_single_annotation_scheme(dict(SCHEME, **change), "annotation_schemes[0]")


def test_config_validation_accepts_example():
    validate_single_annotation_scheme(dict(SCHEME), "annotation_schemes[0]")


def test_page_assets_are_gated_on_the_scheme():
    from potato.flask_server import FRONTEND_ASSET_MARKERS
    html, _ = schema_registry.generate(dict(SCHEME))
    markers = FRONTEND_ASSET_MARKERS["spectrogram_annotation"]
    assert any(m in html for m in markers)
    with open("potato/templates/base_template_v2.html") as f:
        template = f.read()
    assert "frontend_assets.spectrogram_annotation" in template
    assert "spectrogram-annotation.js" in template and "spectrogram-annotation.css" in template
