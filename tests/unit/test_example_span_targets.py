"""An example with a span scheme and `instance_display` marks a field `span_target`.

With `instance_display` configured the page hides the legacy `#instance-text`
and shows the item through its display fields. Only a field marked
`span_target: true` takes a selection or draws span overlays, so without one a
span scheme has nowhere to work: no span can be made, and stored spans are
drawn nowhere. `examples/span/coreference` shipped that way -- its mentions
existed only as markup inside the hidden `#instance-text`, and the chain list
was the one place they showed.
"""

import glob
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]


def _span_examples_with_instance_display():
    found = []
    for path in sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "config.yaml"),
                                 recursive=True)):
        try:
            with open(path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError:
            continue
        if not isinstance(config, dict):
            continue
        schemes = config.get("annotation_schemes") or []
        if not any(isinstance(s, dict) and s.get("annotation_type") == "span"
                   for s in schemes):
            continue
        display = config.get("instance_display")
        if isinstance(display, dict) and display.get("fields"):
            found.append((path, display["fields"]))
    return found


def test_there_are_such_examples():
    """A sweep that finds nothing would pass vacuously."""
    paths = [p for p, _ in _span_examples_with_instance_display()]
    assert any(p.endswith("examples/span/coreference/config.yaml") for p in paths)


def test_each_marks_a_field_span_target():
    offenders = [
        str(Path(path).relative_to(REPO_ROOT))
        for path, fields in _span_examples_with_instance_display()
        if not any(isinstance(f, dict) and f.get("span_target") for f in fields)
    ]
    assert offenders == [], (
        "These examples have a span scheme and instance_display but no field "
        f"with span_target: true, so no span can be made or shown: {offenders}")


def _config(span_target):
    field = {"key": "text", "type": "text", "label": "Text"}
    if span_target:
        field["span_target"] = True
    return {
        "annotation_schemes": [{"annotation_type": "span", "name": "mentions",
                                "description": "Mark mentions.", "labels": ["PERSON"]}],
        "instance_display": {"fields": [field]},
    }


def test_a_config_without_one_is_warned(caplog):
    """Outside the examples, the same mistake has to be caught at load time."""
    from potato.server_utils.config_module import validate_instance_display_config
    with caplog.at_level("WARNING"):
        validate_instance_display_config(_config(span_target=False))
    assert any("mentions" in r.getMessage() and "span_target" in r.getMessage()
               for r in caplog.records)


def test_a_config_with_one_is_not(caplog):
    from potato.server_utils.config_module import validate_instance_display_config
    with caplog.at_level("WARNING"):
        validate_instance_display_config(_config(span_target=True))
    assert not any("span_target" in r.getMessage() for r in caplog.records)
