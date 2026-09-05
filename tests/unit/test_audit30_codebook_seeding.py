"""
A config label's colour and prose must reach the codebook, not just the form.

Audit 27 (b): a span scheme with `codebook: true` whose two labels each carried
a `description` and a `color` produced two codes with `color = None` and the
placeholder "No content yet — use Edit to add a definition". The colour reached
the annotation chips, so the researcher saw a coloured, described label list on
the form and an empty codebook behind it. Everything they had written about
each code was on the floor.

The seed runs once, on a codebook that is still empty, so none of this can
overwrite a codebook a researcher has since curated -- the last test here is
the one that says so.
"""

import tempfile

import pytest

from potato.codebook import blocks, content_service
from potato.codebook.codebook import Codebook
from potato.codebook.schema_bridge import apply_codebook_to_schemes

PROJECT = "seed_probe"


def _config(labels, task_dir):
    return {
        "annotation_task_name": PROJECT,
        "task_dir": task_dir,
        "annotation_schemes": [{
            "annotation_type": "radio",
            "name": "codes",
            "description": "Pick a code",
            "codebook": True,
            "labels": labels,
        }],
    }


@pytest.fixture
def task_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _codes(task_dir):
    return {n["name"]: n for n in Codebook.load(task_dir, PROJECT).as_tree()}


def test_label_color_reaches_the_codebook(task_dir):
    apply_codebook_to_schemes(_config([
        {"name": "delay", "color": "#4682b4"},
        {"name": "workaround", "color": "#b44682"},
    ], task_dir), task_dir=task_dir)

    codes = _codes(task_dir)
    assert codes["delay"]["color"] == "#4682b4"
    assert codes["workaround"]["color"] == "#b44682"


def test_label_description_becomes_the_codes_definition(task_dir):
    apply_codebook_to_schemes(_config([
        {"name": "delay", "description": "The agent stalled before acting."},
    ], task_dir), task_dir=task_dir)

    code_id = _codes(task_dir)["delay"]["id"]
    assert (blocks.gloss_by_code(task_dir, PROJECT)[code_id]
            == "The agent stalled before acting.")


def test_label_tooltip_is_used_when_there_is_no_description(task_dir):
    """`tooltip` is the documented per-label help key; an author who used
    the documented spelling must not get an empty codebook for it."""
    apply_codebook_to_schemes(_config([
        {"name": "workaround", "tooltip": "Routed around a blocked tool."},
    ], task_dir), task_dir=task_dir)

    code_id = _codes(task_dir)["workaround"]["id"]
    assert (blocks.gloss_by_code(task_dir, PROJECT)[code_id]
            == "Routed around a blocked tool.")


def test_a_bare_label_seeds_a_code_with_no_definition(task_dir):
    apply_codebook_to_schemes(
        _config([{"name": "bare"}, "plain_string"], task_dir),
        task_dir=task_dir)

    codes = _codes(task_dir)
    assert set(codes) == {"bare", "plain_string"}
    assert blocks.gloss_by_code(task_dir, PROJECT) == {}


def test_seeding_never_overwrites_a_curated_definition(task_dir):
    """The bridge runs on every server start. A researcher who rewrote a
    definition must still have their wording after a restart."""
    cfg = _config(
        [{"name": "delay", "description": "Seeded wording."}], task_dir)
    apply_codebook_to_schemes(cfg, task_dir=task_dir)
    code_id = _codes(task_dir)["delay"]["id"]

    scope = content_service.get_scope(task_dir, PROJECT, "code", code_id)
    content_service.save_scope(
        task_dir, project=PROJECT, scope_kind="code", scope_id=code_id,
        blocks_in=[{"block_type": "short_def",
                    "body_md": "Wording the researcher chose."}],
        base_version=scope["scope_version"], actor="researcher")

    apply_codebook_to_schemes(
        _config([{"name": "delay", "description": "Seeded wording."}],
                task_dir),
        task_dir=task_dir)

    assert (blocks.gloss_by_code(task_dir, PROJECT)[code_id]
            == "Wording the researcher chose.")
