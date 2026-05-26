import os
import shutil
import tempfile
import pytest
from potato.user_state_management import InMemoryUserState, UserPhase
from potato.item_state_management import Item, Label, SpanAnnotation

@pytest.fixture(scope="function")
def temp_user_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)

def test_radio_annotation_save_and_load(temp_user_dir):
    user = InMemoryUserState("radio_user")
    iid = "item1"
    label = Label("sentiment", "positive")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    user.add_label_annotation(iid, label, "true")
    user.save(temp_user_dir)
    loaded = InMemoryUserState.load(temp_user_dir)
    assert loaded.get_label_annotations(iid)[label] == "true"

def test_likert_annotation_save_and_load(temp_user_dir):
    user = InMemoryUserState("likert_user")
    iid = "item2"
    label = Label("agreement", "3")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    user.add_label_annotation(iid, label, 3)
    user.save(temp_user_dir)
    loaded = InMemoryUserState.load(temp_user_dir)
    assert loaded.get_label_annotations(iid)[label] == 3

def test_slider_annotation_save_and_load(temp_user_dir):
    user = InMemoryUserState("slider_user")
    iid = "item3"
    label = Label("intensity", "75")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    user.add_label_annotation(iid, label, 75)
    user.save(temp_user_dir)
    loaded = InMemoryUserState.load(temp_user_dir)
    assert loaded.get_label_annotations(iid)[label] == 75

def test_text_annotation_save_and_load(temp_user_dir):
    user = InMemoryUserState("text_user")
    iid = "item4"
    label = Label("explanation", "freeform")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    user.add_label_annotation(iid, label, "This is a test explanation.")
    user.save(temp_user_dir)
    loaded = InMemoryUserState.load(temp_user_dir)
    assert loaded.get_label_annotations(iid)[label] == "This is a test explanation."

def test_multiselect_annotation_save_and_load(temp_user_dir):
    user = InMemoryUserState("multi_user")
    iid = "item5"
    label1 = Label("tags", "funny")
    label2 = Label("tags", "informative")
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    user.add_label_annotation(iid, label1, True)
    user.add_label_annotation(iid, label2, True)
    user.save(temp_user_dir)
    loaded = InMemoryUserState.load(temp_user_dir)
    anns = loaded.get_label_annotations(iid)
    assert anns[label1] is True
    assert anns[label2] is True

def test_span_annotation_save_and_load(temp_user_dir):
    user = InMemoryUserState("span_user")
    iid = "item6"
    span = SpanAnnotation("highlight", "span1", "title", 0, 5)
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    user.add_span_annotation(iid, span, "selected")
    user.save(temp_user_dir)
    loaded = InMemoryUserState.load(temp_user_dir)
    spans = loaded.get_span_annotations(iid)
    assert span in spans
    assert spans[span] == "selected"


def test_prune_removes_missing_items(monkeypatch):
    """prune_missing_assigned_instances should remove items not in the item manager."""
    user = InMemoryUserState("prune_user")
    user.instance_id_ordering = ["missing_qc", "valid_1", "missing_2", "valid_2"]
    user.assigned_instance_ids = set(user.instance_id_ordering)
    user.instance_id_to_order = user.generate_id_order_mapping(user.instance_id_ordering)
    user.current_instance_index = 2  # points at "missing_2"

    valid_ids = {"valid_1", "valid_2"}

    class StubItemManager:
        def has_item(self, item_id):
            return item_id in valid_ids

    monkeypatch.setattr(
        "potato.user_state_management.get_item_state_manager",
        lambda: StubItemManager(),
    )

    removed = user.prune_missing_assigned_instances()

    assert removed == 2
    assert user.instance_id_ordering == ["valid_1", "valid_2"]
    assert user.assigned_instance_ids == {"valid_1", "valid_2"}
    # "missing_qc" was before index 2, so index shifts down by 1 → new index 1
    assert user.current_instance_index == 1


def test_prune_adjusts_index_correctly(monkeypatch):
    """Index should account for removals before the current position."""
    user = InMemoryUserState("idx_user")
    user.instance_id_ordering = ["gone_a", "gone_b", "keep_c", "keep_d"]
    user.assigned_instance_ids = set(user.instance_id_ordering)
    user.instance_id_to_order = user.generate_id_order_mapping(user.instance_id_ordering)
    user.current_instance_index = 3  # points at "keep_d"

    class StubItemManager:
        def has_item(self, item_id):
            return item_id.startswith("keep")

    monkeypatch.setattr(
        "potato.user_state_management.get_item_state_manager",
        lambda: StubItemManager(),
    )

    user.prune_missing_assigned_instances()

    assert user.instance_id_ordering == ["keep_c", "keep_d"]
    # Two items removed before index 3 → 3-2 = 1
    assert user.current_instance_index == 1


def test_get_current_instance_returns_none_for_missing(monkeypatch):
    """get_current_instance should return None without mutating the index."""
    user = InMemoryUserState("nomutate_user")
    user.instance_id_ordering = ["missing_item", "also_missing"]
    user.current_instance_index = 0

    class StubItemManager:
        def has_item(self, item_id):
            return False

    monkeypatch.setattr(
        "potato.user_state_management.get_item_state_manager",
        lambda: StubItemManager(),
    )

    result = user.get_current_instance()
    assert result is None
    assert user.current_instance_index == 0  # unchanged


def test_load_prunes_missing_items(monkeypatch, temp_user_dir):
    """Loading persisted state should automatically prune stale items."""
    user = InMemoryUserState("load_prune_user")
    user.instance_id_ordering = ["missing_qc_item", "valid_item"]
    user.assigned_instance_ids = set(user.instance_id_ordering)
    user.current_instance_index = 0
    user.current_phase_and_page = (UserPhase.ANNOTATION, None)
    user.save(temp_user_dir)

    valid_item = Item("valid_item", {"text": "Valid item"})

    class StubItemManager:
        def has_item(self, item_id):
            return item_id == "valid_item"
        def get_item(self, item_id):
            return valid_item if item_id == "valid_item" else None

    monkeypatch.setattr(
        "potato.user_state_management.get_item_state_manager",
        lambda: StubItemManager(),
    )

    loaded = InMemoryUserState.load(temp_user_dir)

    assert loaded.instance_id_ordering == ["valid_item"]
    assert loaded.get_assigned_instance_ids() == {"valid_item"}
    assert loaded.get_current_instance().get_id() == "valid_item"