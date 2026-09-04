"""Every registered type must emit `data-grid-columns`, or its `layout:` is dead.

`generate_layout_attributes` produces the attribute the grid reads. Fifteen
registered types never called it, so their per-scheme `layout:` block was
silently discarded and they rendered at one column: `validate --strict` passed,
the config looked honoured, and the only way to see it was to read the
attribute in the browser.

Every media and geometry type was on that list -- image, video, audio, spatial,
region_caption, tiered, episode -- which is the wrong half of the registry to
lose, because those are the schemes that most need the width. `slider` too,
where a single column is the case the width control exists for.

A drift guard rather than a behaviour test: the failure mode is a NEW schema
module forgetting the call, which nothing else catches.
"""

import logging

import pytest

from potato.server_utils.schemas.registry import schema_registry


@pytest.fixture(autouse=True)
def _quiet_generators():
    """Silence the generators' boot chatter for these renders only.

    A module-level `logging.disable` would stay in force for the rest of the
    session and silently break any later test that asserts on a warning.
    """
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)


# Minimum extra config to get each type past its own validation. Anything that
# renders an error placeholder is a fixture problem, not a finding, so these
# have to be right.
PROBE_EXTRAS = {
    "slider": {"min": 0, "max": 10},
    "range_slider": {"min": 0, "max": 10},
    "number": {"min": 0, "max": 10},
    "likert": {"size": 3},
    "multirate": {"options": ["x", "y"]},
    "card_sort": {"groups": ["g1", "g2"]},
    "conjoint": {"attributes": [{"name": "a", "levels": ["1", "2"]}]},
    "error_span": {"error_types": [{"name": "typo", "description": "d"}]},
    "hierarchical_multiselect": {"taxonomy": {"a": ["b"]}},
    "rubric_eval": {"criteria": [{"name": "c", "description": "d"}]},
    "semantic_differential": {"pairs": [["hot", "cold"]]},
    "video": {"video_path": "v.mp4"},
    "image_annotation": {"tools": ["bbox"]},
    "spatial_annotation": {"tools": ["cuboid_3d"], "pointcloud_key": "pc"},
    "video_annotation": {"video_key": "video", "tools": ["bbox"]},
    "audio_annotation": {"audio_key": "audio"},
    "region_caption": {"source_field": "image"},
    "tiered_annotation": {"tiers": [{"name": "t", "labels": ["a"]}]},
    "episode_annotation": {"steps_key": "steps"},
    "coreference": {"labels": ["ENT"]},
    "event_annotation": {"labels": ["EV"]},
    "span_link": {"labels": ["REL"]},
    "multi_document_event": {"labels": ["EV"]},
    "grounding_eval": {"expressions_field": "expressions"},
    "rollout_evaluation": {"streams": ["a", "b"]},
    "context_attribution": {"source_field": "ctx"},
    "cot_trace": {"steps_key": "steps"},
    "process_reward": {"steps_key": "steps"},
}


def _render(annotation_type, columns=2):
    scheme = {
        "annotation_type": annotation_type,
        "name": "probe",
        "description": "Probe?",
        "labels": ["alpha", "beta"],
        "annotation_id": "probe1",
        "layout": {"columns": columns},
    }
    scheme.update(PROBE_EXTRAS.get(annotation_type, {}))
    html, _ = schema_registry.generate(scheme)
    return html


@pytest.mark.parametrize("annotation_type",
                         sorted(schema_registry.get_supported_types()))
def test_the_layout_block_reaches_the_dom(annotation_type):
    html = _render(annotation_type)

    assert "annotation-error" not in html, (
        f"{annotation_type} could not render with the probe config; add what it "
        f"needs to PROBE_EXTRAS rather than letting the assertion below pass "
        f"vacuously"
    )
    assert 'data-grid-columns="2"' in html, (
        f"{annotation_type} does not emit data-grid-columns, so a `layout:` "
        f"block on it is silently discarded and it renders at one column. Call "
        f"generate_layout_attributes(annotation_scheme) and interpolate the "
        f"result into the outermost element."
    )


@pytest.mark.parametrize("annotation_type",
                         sorted(schema_registry.get_supported_types()))
def test_the_schema_is_addressable_by_name(annotation_type):
    """A page-wide scan by schema name missed slider and span."""
    html = _render(annotation_type)
    assert 'data-schema-name="probe"' in html, (
        f"{annotation_type} carries no data-schema-name, so a page-wide scan "
        f"by schema name cannot find it"
    )
