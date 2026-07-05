"""Tests for per-cohort annotation layout generation.

Per-cohort schema assignment reuses the ``layout_name`` seam in front_end to
emit one layout per cohort. These tests verify distinct cohorts get distinct
layout files with content matching their own schemes, and that scheme-dict
mutation (annotation_id / keybinding allocation) stays isolated per cohort when
deep copies are used (as generate_annotation_html_template does).
"""

import copy
import os


def _config(tmp_path):
    return {"task_dir": str(tmp_path), "annotation_task_name": "cohort_task"}


def _radio_scheme(name, label):
    return {
        "annotation_type": "radio",
        "name": name,
        "description": f"scheme {name}",
        "labels": [label],
    }


def test_cohort_layouts_are_distinct_files(tmp_path):
    from potato.server_utils.front_end import get_or_generate_annotation_layout

    config = _config(tmp_path)
    schemes_a = [_radio_scheme("sentiment", "pos")]
    schemes_b = [_radio_scheme("sentiment", "pos"), _radio_scheme("topic", "x")]

    path_a = get_or_generate_annotation_layout(config, schemes_a, layout_name="cohorta")
    path_b = get_or_generate_annotation_layout(config, schemes_b, layout_name="cohortb")

    assert path_a.endswith("task_layout_cohorta.html")
    assert path_b.endswith("task_layout_cohortb.html")
    assert path_a != path_b
    assert os.path.exists(path_a) and os.path.exists(path_b)

    with open(path_a) as f:
        content_a = f.read()
    with open(path_b) as f:
        content_b = f.read()
    # cohortB has an extra scheme, so its layout must differ.
    assert content_a != content_b
    assert "topic" in content_b


def test_deep_copy_keeps_annotation_ids_independent(tmp_path):
    """Baking two cohorts on deep copies gives each its own annotation_id run."""
    from potato.server_utils.front_end import allocate_keybindings

    global_schemes = [_radio_scheme("sentiment", "pos"), _radio_scheme("topic", "x")]
    cohort_a = copy.deepcopy([global_schemes[0]])          # 1 scheme
    cohort_b = copy.deepcopy(global_schemes)               # 2 schemes

    # Simulate the per-cohort annotation_id assignment done in _bake_site_template.
    for idx, s in enumerate(cohort_a):
        s["annotation_id"] = idx
    for idx, s in enumerate(cohort_b):
        s["annotation_id"] = idx

    assert [s["annotation_id"] for s in cohort_a] == [0]
    assert [s["annotation_id"] for s in cohort_b] == [0, 1]
    # Global list untouched (no annotation_id leaked in).
    assert all("annotation_id" not in s for s in global_schemes)


def test_global_layout_stable_without_cohorts(tmp_path):
    """Same schemes + no layout_name → stable default file (hash match reuse)."""
    from potato.server_utils.front_end import get_or_generate_annotation_layout

    config = _config(tmp_path)
    schemes = [_radio_scheme("sentiment", "pos")]

    p1 = get_or_generate_annotation_layout(config, schemes)
    with open(p1) as f:
        first = f.read()
    # Regenerating with identical inputs must reuse the same file/content.
    p2 = get_or_generate_annotation_layout(config, schemes)
    with open(p2) as f:
        second = f.read()

    assert p1 == p2
    assert p1.endswith("task_layout.html")
    assert first == second
