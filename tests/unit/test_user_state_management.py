import os
import shutil
import tempfile
import pytest
from potato.user_state_management import InMemoryUserState, UserPhase
from potato.item_state_management import Label, SpanAnnotation

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