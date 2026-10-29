"""Keys inside dict labels are checked against what each type reads.

The scheme-level key check stopped at `labels`, so a label key nothing reads
(`description:` on an audio label, `key_value:` on a select label, the
`key_binding:` six examples used for `key_value`) loaded silently and
`validate --strict` passed it.
"""

import logging

import pytest

from potato.server_utils.config_module import ConfigValidationError, validate_scheme_keys
from potato.server_utils.schemas.registry import (
    LABEL_FIELDS, SELF_VALIDATED_LABEL_TYPES, STRING_LABEL_TYPES, schema_registry)


def _warnings(caplog, *schemes):
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="potato.server_utils.config_module"):
        validate_scheme_keys({"annotation_schemes": list(schemes)})
    return [r.getMessage() for r in caplog.records if "Unrecognized config key" in r.getMessage()]


def test_unread_label_key_warns_with_the_path(caplog):
    (msg,) = _warnings(caplog, {"annotation_type": "select", "name": "s", "description": "d",
                                "labels": [{"name": "A"}, {"name": "B", "key_value": "b"}]})
    assert "annotation_schemes[s].labels[1].key_value" in msg


def test_key_binding_is_pointed_at_key_value(caplog):
    (msg,) = _warnings(caplog, {"annotation_type": "radio", "name": "q", "description": "d",
                                "labels": [{"name": "A", "key_binding": "a"}]})
    assert "Did you mean: 'key_value'" in msg


@pytest.mark.parametrize("scheme", [
    {"annotation_type": "radio", "name": "q", "description": "d",
     "labels": [{"name": "A", "text": "Alpha", "tooltip": "t", "key_value": "a",
                 "color": "#f00", "description": "x", "tooltip_file": "f.txt"}]},
    {"annotation_type": "span", "name": "ner", "description": "d",
     "labels": [{"name": "PER", "abbreviation": "P", "key_value": "p", "color": "#0f0"}]},
    {"annotation_type": "image_annotation", "name": "img", "description": "d", "tools": ["bbox"],
     "labels": [{"name": "car", "key_value": "c", "label_id": 3, "supercategory": "vehicle"}]},
])
def test_keys_the_type_reads_pass(caplog, scheme):
    assert _warnings(caplog, scheme) == []


def test_string_labels_are_not_checked(caplog):
    assert _warnings(caplog, {"annotation_type": "radio", "name": "q", "description": "d",
                              "labels": ["A", "B"]}) == []


@pytest.mark.parametrize("kind", sorted(STRING_LABEL_TYPES))
def test_dict_labels_are_refused_where_they_render_as_a_repr(kind):
    with pytest.raises(ConfigValidationError, match="plain strings"):
        validate_scheme_keys({"annotation_schemes": [
            {"annotation_type": kind, "name": "x", "description": "d", "labels": [{"name": "A"}]}]})


def test_every_type_that_takes_labels_is_classified():
    """A new type with a `labels` field has to say what its labels read."""
    classified = set(LABEL_FIELDS) | STRING_LABEL_TYPES | SELF_VALIDATED_LABEL_TYPES
    takes_labels = {t for t in schema_registry.get_supported_types()
                    if "labels" in (schema_registry.get_accepted_fields(t) or set())}
    assert takes_labels - classified == set()
