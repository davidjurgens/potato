"""Audit 95, V1: `potato validate` passed volume_annotation values that the
generator then turned into an error card on every page."""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError, validate_single_annotation_scheme)

BASE = {"annotation_type": "volume_annotation", "name": "seg", "description": "Segment",
        "labels": ["Lesion"]}


def _validate(**extra):
    scheme = dict(BASE)
    scheme.update(extra)
    validate_single_annotation_scheme(scheme, "annotation_schemes[0]")


def test_valid():
    _validate(tools=["brush", "box"], views=["axial"], brush_size=3,
              default_window="Lung", display_tags=["Modality"],
              window_presets=[{"name": "Liver", "center": 60, "width": 150}])
    _validate(default_window="Liver", window_presets=[{"name": "Liver", "center": 60, "width": 150}])


@pytest.mark.parametrize("extra,match", [
    ({"tools": ["lasso"]}, "tools"),
    ({"views": ["oblique"]}, "views"),
    ({"brush_size": "big"}, "brush_size"),
    ({"brush_size": -3}, "brush_size"),
    ({"default_window": "Abdomen"}, "default_window"),
    ({"window_presets": [{"name": "W", "center": 1}]}, "window_presets"),
    ({"window_presets": [{"name": "W", "center": 1, "width": 0}]}, "width must be positive"),
    ({"display_tags": "Modality"}, "display_tags"),
    ({"labels": []}, "at least one label"),
])
def test_refused(extra, match):
    with pytest.raises(ConfigValidationError, match=match):
        _validate(**extra)


def test_media_errors_hide_server_paths():
    """Audit 95, V2: a corrupt NIfTI's error showed the server's absolute path."""
    from potato.media.routes import _public_error
    msg = _public_error(ValueError("File /private/tmp/study/vol/ct.nii.gz is not a gzip file"))
    assert msg == "File ct.nii.gz is not a gzip file"
    assert _public_error(ValueError("index must be an integer")) == "index must be an integer"
