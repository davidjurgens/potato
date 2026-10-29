"""Span label key_value shortcuts and abbreviations.

An explicit key_value on a span label was read only by the key allocator,
which runs only for schemes with sequential keys, and no span checkbox had
the data-key attribute the page's key handler matches on, so no span
shortcut did anything. `abbreviation` was read into a variable nothing used.
"""

import re

from potato.server_utils.schemas.span import generate_span_layout


def _attrs(html, label):
    match = re.search(r'<input[^>]*id="ner_%s"[^>]*>' % label, html, re.S)
    assert match, label
    return match.group(0)


def test_explicit_key_value_binds_and_reaches_the_page():
    html, keys = generate_span_layout({
        "annotation_type": "span", "name": "ner", "description": "d",
        "labels": [{"name": "Person", "key_value": "p"}, {"name": "Place", "key_value": "l"}]})
    assert ("p", "ner: Person") in keys and ("l", "ner: Place") in keys
    assert 'data-key="p"' in _attrs(html, "Person")
    assert 'data-key="l"' in _attrs(html, "Place")


def test_duplicate_key_value_keeps_the_label_without_a_key():
    html, keys = generate_span_layout({
        "annotation_type": "span", "name": "ner", "description": "d",
        "labels": [{"name": "Person", "key_value": "p"}, {"name": "Place", "key_value": "p"}]})
    assert [k for k, _ in keys] == ["p"]
    assert "data-key" not in _attrs(html, "Place")


def test_abbreviation_is_on_the_checkbox():
    html, _ = generate_span_layout({
        "annotation_type": "span", "name": "ner", "description": "d",
        "labels": [{"name": "Person", "abbreviation": "PER"}, "Place"]})
    assert 'data-abbreviation="PER"' in _attrs(html, "Person")
    assert "data-abbreviation" not in _attrs(html, "Place")
