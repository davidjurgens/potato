"""The progress counter must not pass its own total.

Attention checks and gold items are injected by the platform, not drawn from
the item pool, so they never appear in the denominator. The numerator counted
every annotation including them, and a 12-item study with two checks and two
gold items walked "11/12 ... 12/12 ... 13/12 ... 15/12" before finishing.
Sixteen items were served, which was right; only the label was wrong.
"""

import json

import pytest

from potato.quality_control import (
    QualityControlManager,
    clear_quality_control_manager,
    count_dataset_items,
)
import potato.quality_control as qc_module


DATASET_IDS = [f"n{i:03d}" for i in range(1, 13)]
INJECTED_IDS = ["check01", "check02", "g1", "g2"]


@pytest.fixture
def qc_manager(tmp_path):
    (tmp_path / "attention.json").write_text(json.dumps([
        {"id": "check01", "text": "check one", "expected_answer": {"s": "a"}},
        {"id": "check02", "text": "check two", "expected_answer": {"s": "a"}},
    ]), encoding="utf-8")
    (tmp_path / "gold.json").write_text(json.dumps([
        {"id": "g1", "text": "gold one", "gold_label": {"s": "a"}},
        {"id": "g2", "text": "gold two", "gold_label": {"s": "b"}},
    ]), encoding="utf-8")

    config = {
        "attention_checks": {"enabled": True, "items_file": "attention.json", "frequency": 3},
        "gold_standards": {"enabled": True, "items_file": "gold.json", "frequency": 5},
    }
    manager = QualityControlManager(config, str(tmp_path))
    qc_module._QUALITY_CONTROL_MANAGER = manager
    yield manager
    clear_quality_control_manager()


def test_injected_items_are_not_counted_as_progress(qc_manager):
    """This is the numerator the annotation page now renders."""
    annotated = DATASET_IDS + INJECTED_IDS
    assert len(annotated) == 16
    assert count_dataset_items(annotated) == 12


def test_a_finished_study_reads_as_complete(qc_manager):
    """finished == total at the end, rather than 15/12."""
    finished = count_dataset_items(DATASET_IDS + INJECTED_IDS)
    remaining = 0  # nothing left in the pool
    assert finished == finished + remaining == 12


def test_dataset_items_still_count(qc_manager):
    assert count_dataset_items(DATASET_IDS[:5]) == 5


def test_without_quality_control_every_item_counts():
    """No manager means no injection, so the discount must not apply."""
    clear_quality_control_manager()
    assert count_dataset_items(DATASET_IDS + INJECTED_IDS) == 16


def test_the_rendered_counter_never_exceeds_its_total(qc_manager, monkeypatch):
    """Assert on the string the annotator reads, not on the helper behind it.

    The first attempt at this fix corrected the count that feeds `total_count`
    and left the template's `finished` bound to `get_annotation_count()`, so the
    page still rendered "10/12" after six dataset items and four injected ones.
    Only driving the real page in a browser showed it.
    """
    from pathlib import Path

    from flask import Flask

    import potato.flask_server as fs
    from potato.phase import UserPhase
    from potato.server_utils.html_sanitizer import register_jinja_filters

    template_folder = Path(__file__).resolve().parents[2] / "potato" / "templates"
    app = Flask(__name__, template_folder=str(template_folder))
    app.secret_key = "test-secret"
    register_jinja_filters(app)

    # Six dataset items and all four injected ones answered, six left in the pool.
    annotated = set(DATASET_IDS[:6]) | set(INJECTED_IDS)

    class StubItem:
        def get_id(self):
            return "n007"

        def get_data(self):
            return {"id": "n007", "text": "Review number 7."}

        def get_text(self):
            return "Review number 7."

        def get_displayed_text(self):
            return "Review number 7."

    class StubUserState:
        instance_id_ordering = DATASET_IDS + INJECTED_IDS

        def get_current_phase_and_page(self):
            return (UserPhase.ANNOTATION, "QC study")

        def get_current_instance(self):
            return StubItem()

        def get_current_instance_index(self):
            return 10

        def get_annotation_count(self):
            return len(annotated)

        def get_annotated_instance_ids(self):
            return set(annotated)

        def get_max_assignments(self):
            return 12

        def has_annotated(self, instance_id):
            return instance_id in annotated

        def generate_user_statistics(self):
            return {}

    class StubUSM:
        def get_user_state(self, username):
            return StubUserState()

        def get_phase_html_fname(self, phase, page):
            return "base_template_v2.html"

        def can_user_go_back(self, username):
            return True

    class StubISM:
        def get_total_assignable_items_for_user(self, user_state):
            return 6

    monkeypatch.setattr(fs, "app", app, raising=False)
    monkeypatch.setattr(fs, "config", {
        "annotation_task_name": "QC study",
        "annotation_schemes": [{
            "name": "sentiment",
            "annotation_type": "radio",
            "description": "Sentiment?",
            "labels": [{"name": "Positive"}, {"name": "Negative"}, {"name": "Neutral"}],
        }],
        "item_properties": {"text_key": "text", "kwargs": []},
        "site_file": "base_template_v2.html",
        "ui": {},
        "customjs": False,
        "debug": False,
        "alert_time_each_instance": 10000000,
    }, raising=False)
    monkeypatch.setattr(fs, "get_user_state_manager", lambda: StubUSM())
    monkeypatch.setattr(fs, "get_item_state_manager", lambda: StubISM())
    monkeypatch.setattr(fs, "get_quality_control_manager", lambda: qc_manager)
    monkeypatch.setattr(fs, "get_annotations_for_user_on", lambda username, instance_id: None)
    monkeypatch.setattr(fs, "get_span_annotations_for_user_on", lambda username, instance_id: [])
    monkeypatch.setattr(fs, "get_label_suggestions", lambda item, config, prefill: set())
    monkeypatch.setattr(fs, "_is_user_adjudicator", lambda username: False)

    with app.test_request_context("/annotate"):
        rendered = fs.render_page_with_annotations("user1")

    assert 'id="progress-counter">6/12<' in rendered, (
        "the counter must read 6/12 after six dataset items and four injected ones"
    )
