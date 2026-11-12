"""
Label keys the way they are matched.

Shortcuts are matched without case and a YAML `key_value: 1` arrives as a
number, but several generators compared keys as given: two labels on `A` and
`a` both kept the key, `accept_key: 4` crashed triage, and spectrogram filled
in digits over a digit another label had set.
"""

import json
import re

import pytest
from bs4 import BeautifulSoup

from potato.server_utils.schemas.keybinding_allocator import allocate_keybindings
from potato.server_utils.schemas.registry import schema_registry


def data_keys(scheme):
    html, _ = schema_registry.generate(scheme)
    return [k.lower() for k in re.findall(r'data-key="([^"]+)"', html)]


@pytest.mark.parametrize("kind", ["radio", "multiselect", "span"])
def test_keys_that_differ_only_in_case_are_one_key(kind, caplog):
    scheme = {"annotation_type": kind, "name": "q", "description": "d",
              "labels": [{"name": "upper", "key_value": "A"},
                         {"name": "lower", "key_value": "a"}]}
    assert data_keys(scheme).count("a") == 1
    assert "already bound to 'upper'" in caplog.text


def test_triage_takes_a_numeric_key():
    keys = data_keys({"annotation_type": "triage", "name": "keep", "description": "d",
                      "accept_key": 4, "reject_key": 5, "skip_key": 6})
    assert keys == ["4", "5", "6"]


def test_spectrogram_fills_in_digits_no_label_sets():
    html, _ = schema_registry.generate({
        "annotation_type": "spectrogram_annotation", "name": "calls", "description": "d",
        "labels": ["whistle", {"name": "trill", "key_value": "1"}, "click"]})
    form = BeautifulSoup(html, "html.parser").find("form")
    cfg = json.loads(form["data-spectrogram-config"])
    assert [lab["key"] for lab in cfg["labels"]] == ["2", "1", "3"]


def test_a_rollout_takes_a_digit_per_stream():
    rollout = {"annotation_type": "rollout_evaluation", "name": "roll", "description": "d",
               "streams": [{"field": "a", "name": "A"}, {"field": "b", "name": "B"}]}
    radio = {"annotation_type": "radio", "name": "tone", "description": "d",
             "labels": ["x", "y", "z"], "sequential_key_binding": True}
    keys = [e["key"] for e in allocate_keybindings([rollout, radio])["tone"]]
    assert keys == ["3", "4", "5"]


def test_a_rollout_manifest_wins_over_its_streams():
    # The page reads the manifest whenever manifest_field is set, so its
    # panel count is unknown here and every digit stays reserved.
    rollout = {"annotation_type": "rollout_evaluation", "name": "roll", "description": "d",
               "manifest_field": "manifest",
               "streams": [{"field": "a", "name": "A"}, {"field": "b", "name": "B"}]}
    radio = {"annotation_type": "radio", "name": "tone", "description": "d",
             "labels": ["x", "y", "z"], "sequential_key_binding": True}
    keys = [e["key"] for e in allocate_keybindings([rollout, radio])["tone"]]
    assert not any(k.isdigit() and k != "0" for k in keys) and len(keys) == 3


def test_an_uppercase_label_key_on_an_image_tool_key_warns(caplog):
    # Keys match without case, so R is the bbox tool's r; the check compared
    # them as given and said nothing.
    scheme = {"annotation_type": "image_annotation", "name": "img", "description": "d",
              "tools": ["bbox"], "labels": [{"name": "car", "key_value": "R"}]}
    schema_registry.generate(scheme)
    assert "key 'r' is bound to bbox tool" in caplog.text


def test_an_uppercase_phase_key_on_an_episode_tool_key_warns(caplog):
    schema_registry.generate({
        "annotation_type": "episode_annotation", "name": "review", "description": "d",
        "layers": ["phases", "reward"],
        "phases": [{"name": "reach", "key_value": "R"}]})
    assert "uses key 'r', which is already a tool shortcut" in caplog.text
