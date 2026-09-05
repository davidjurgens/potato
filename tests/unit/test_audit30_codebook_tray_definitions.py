"""
The annotation-page codebook tray shows each code's definition, not its name.

Audit 27 (e): after saving a definition for `delay`, the tray on the annotation
page still listed the bare word "delay". Reading what a code means meant
clicking "Open full codebook" and leaving the page -- at exactly the moment the
annotator was deciding whether it applied.

This file covers the payload side. The rendering and the cache-freshness
half live in tests/selenium/test_audit30_codebook_tray_definitions_ui.py,
because "the tray shows the definition" is only true in a browser.
"""

import tempfile

import pytest

from potato.codebook import blocks, content_service, create_code
from potato.codebook.api import _with_glosses

PROJECT = "tray_probe"


@pytest.fixture
def task_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _save(task_dir, code_id, block_type, body):
    scope = content_service.get_scope(task_dir, PROJECT, "code", code_id)
    content_service.save_scope(
        task_dir, project=PROJECT, scope_kind="code", scope_id=code_id,
        blocks_in=[{"block_type": block_type, "body_md": body}],
        base_version=scope["scope_version"], actor="tester")


def test_gloss_reads_a_saved_definition(task_dir):
    code = create_code(task_dir, project=PROJECT, name="delay",
                       created_by="tester")
    _save(task_dir, code["id"], "short_def", "The agent stalled.")

    assert (blocks.gloss_by_code(task_dir, PROJECT)[code["id"]]
            == "The agent stalled.")


def test_a_full_definition_is_used_when_there_is_no_short_one(task_dir):
    """A code whose only prose is a long `definition` still gets a gloss;
    otherwise the tray silently shows nothing for a documented code."""
    code = create_code(task_dir, project=PROJECT, name="workaround",
                       created_by="tester")
    _save(task_dir, code["id"], "definition", "Routed around a blocked tool.")

    assert (blocks.gloss_by_code(task_dir, PROJECT)[code["id"]]
            == "Routed around a blocked tool.")


def test_the_short_definition_wins_over_the_long_one(task_dir):
    code = create_code(task_dir, project=PROJECT, name="delay",
                       created_by="tester")
    scope = content_service.get_scope(task_dir, PROJECT, "code", code["id"])
    content_service.save_scope(
        task_dir, project=PROJECT, scope_kind="code", scope_id=code["id"],
        blocks_in=[
            {"block_type": "definition", "body_md": "Three paragraphs."},
            {"block_type": "short_def", "body_md": "One line."},
        ],
        base_version=scope["scope_version"], actor="tester")

    assert blocks.gloss_by_code(task_dir, PROJECT)[code["id"]] == "One line."


def test_an_archived_definition_is_not_shown(task_dir):
    """Blocks are soft-archived rather than deleted. A tray that read the
    archived rows would show wording the researcher replaced."""
    code = create_code(task_dir, project=PROJECT, name="delay",
                       created_by="tester")
    _save(task_dir, code["id"], "short_def", "Old wording.")
    _save(task_dir, code["id"], "short_def", "New wording.")

    assert blocks.gloss_by_code(task_dir, PROJECT)[code["id"]] == "New wording."


def test_document_level_prose_is_not_mistaken_for_a_codes_definition(task_dir):
    """Document sections live in the same table with `code_id = ''`."""
    content_service.save_scope(
        task_dir, project=PROJECT, scope_kind="section",
        scope_id="preamble",
        blocks_in=[{"block_type": "short_def", "body_md": "Project preamble."}],
        base_version=0, actor="tester")

    assert blocks.gloss_by_code(task_dir, PROJECT) == {}


def test_glosses_attach_to_nested_codes():
    tree = [{"id": "a", "name": "parent", "children": [
        {"id": "b", "name": "child", "children": []}]}]
    _with_glosses(tree, {"a": "Parent gloss.", "b": "Child gloss."})

    assert tree[0]["definition"] == "Parent gloss."
    assert tree[0]["children"][0]["definition"] == "Child gloss."


def test_a_code_with_no_prose_carries_no_definition_key():
    """The client tests `n.definition`; an empty string would render an
    empty grey line under the name."""
    tree = [{"id": "a", "name": "bare", "children": []}]
    _with_glosses(tree, {})

    assert "definition" not in tree[0]
