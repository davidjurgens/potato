"""Notes -> codebook-edit proposals (notes_feedback.py): accumulated
human rationale notes are analyzed and staged as codebook-edit proposals
through the *existing* propose/human-confirm flow — nothing is applied
automatically."""

import pytest

from potato.codebook import changelog, create_code, clear_change_listeners
from potato.codebook.changelog import _CHANGE_MIGRATION
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.codebook.revision import _CODES_REV_MIGRATION, _REVISION_MIGRATION
from potato.persistence import clear_db_cache, clear_migrations, register_migration
from potato.solo_mode import annotation_notes
from potato.solo_mode.notes_feedback import suggest_from_notes


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    register_migration(_REVISION_MIGRATION)
    register_migration(_CODES_REV_MIGRATION)
    register_migration(_CHANGE_MIGRATION)
    clear_change_listeners()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


class FakeEndpoint:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def query(self, prompt):
        self.prompts.append(prompt)
        return self.response


def test_proposes_edit_when_notes_reveal_a_gap(td):
    code = create_code(td, project="p", name="wait times", created_by="u",
                        details={"definition": "delay in receiving care"})
    annotation_notes.save_note(
        td, project="p", instance_id="i1", schema_name="s",
        note="Marked wait times but it's really about not being able to "
             "reach a clinic at all.", source="validation",
        label="wait times")
    annotation_notes.save_note(
        td, project="p", instance_id="i2", schema_name="s",
        note="Same confusion — total unreachability vs. a slow "
             "appointment.", source="disagreement", label="wait times")

    endpoint = FakeEndpoint({
        "should_propose": True,
        "rationale": "Notes show confusion with access barriers.",
        "negative_clarification":
            "NOT being unable to reach the clinic at all.",
    })
    created = suggest_from_notes(td, "p", endpoint=endpoint)

    assert len(created) == 1
    assert created[0]["op"] == "update_fields"
    assert created[0]["payload"]["code_id"] == code["id"]
    assert created[0]["payload"]["negative_clarification"] == \
        "NOT being unable to reach the clinic at all."

    pending = changelog.list_proposals(td, "p", status="pending")
    assert len(pending) == 1
    assert pending[0]["actor_kind"] == "model"


def test_skips_labels_with_too_few_notes(td):
    create_code(td, project="p", name="cost concerns", created_by="u")
    annotation_notes.save_note(
        td, project="p", instance_id="i1", schema_name="s",
        note="single stray note", source="validation",
        label="cost concerns")

    endpoint = FakeEndpoint({"should_propose": True,
                             "definition": "should never be reached"})
    created = suggest_from_notes(td, "p", endpoint=endpoint)

    assert created == []
    assert endpoint.prompts == []  # never even asked the LLM


def test_llm_declining_to_propose_creates_nothing(td):
    create_code(td, project="p", name="provider trust", created_by="u")
    for i in range(2):
        annotation_notes.save_note(
            td, project="p", instance_id=f"i{i}", schema_name="s",
            note="just a note, nothing actionable", source="validation",
            label="provider trust")

    endpoint = FakeEndpoint({"should_propose": False})
    created = suggest_from_notes(td, "p", endpoint=endpoint)

    assert created == []
    assert changelog.list_proposals(td, "p", status="pending") == []


def test_notes_for_unknown_label_are_ignored(td):
    # No code named "mystery" exists in this project's codebook.
    for i in range(2):
        annotation_notes.save_note(
            td, project="p", instance_id=f"i{i}", schema_name="s",
            note="notes about a code that doesn't exist",
            source="validation", label="mystery")

    endpoint = FakeEndpoint({"should_propose": True, "definition": "x"})
    created = suggest_from_notes(td, "p", endpoint=endpoint)

    assert created == []
    assert endpoint.prompts == []
