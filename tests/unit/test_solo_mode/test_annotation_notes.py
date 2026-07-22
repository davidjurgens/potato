"""Rationale notes captured during validation/disagreement resolution
(previously silently dropped by manager.record_validation /
resolve_disagreement — see annotation_notes.py)."""

from potato.solo_mode import annotation_notes


def test_save_note_blank_is_noop(tmp_path):
    td = str(tmp_path)
    assert annotation_notes.save_note(
        td, project="p", instance_id="i1", schema_name="s",
        note="   ", source="validation") is None
    assert annotation_notes.notes_for_instance(td, "p", "i1") == []


def test_save_and_read_note(tmp_path):
    td = str(tmp_path)
    nid = annotation_notes.save_note(
        td, project="p", instance_id="i1", schema_name="sentiment",
        note="Ambiguous sarcasm.", source="validation",
        label="negative")
    assert nid is not None

    rows = annotation_notes.notes_for_instance(td, "p", "i1")
    assert len(rows) == 1
    assert rows[0]["note"] == "Ambiguous sarcasm."
    assert rows[0]["label"] == "negative"
    assert rows[0]["source"] == "validation"


def test_recent_notes_filters_by_since_and_project(tmp_path):
    td = str(tmp_path)
    annotation_notes.save_note(
        td, project="p1", instance_id="i1", schema_name="s",
        note="note one", source="validation")
    annotation_notes.save_note(
        td, project="p2", instance_id="i2", schema_name="s",
        note="note two", source="disagreement")

    p1_notes = annotation_notes.recent_notes(td, "p1")
    assert len(p1_notes) == 1
    assert p1_notes[0]["note"] == "note one"

    future_cutoff = annotation_notes.recent_notes(
        td, "p1", since=9999999999.0)
    assert future_cutoff == []
