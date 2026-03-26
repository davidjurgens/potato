from pathlib import Path

import potato.flask_server as fs
from flask import Flask

from potato.phase import UserPhase
from potato.server_utils.html_sanitizer import register_jinja_filters


def _build_template_app():
    template_folder = Path(__file__).resolve().parents[2] / "potato" / "templates"
    static_folder = Path(__file__).resolve().parents[2] / "potato" / "static"
    app = Flask(__name__, template_folder=str(template_folder), static_folder=str(static_folder))
    app.secret_key = "test-secret"
    register_jinja_filters(app)

    @app.context_processor
    def inject_template_context():
        return {
            "ui_debug": False,
            "server_debug": False,
            "debug_mode": False,
            "debug_phase": None,
            "annotation_task_name": "Header Codebook Test",
            "header_logo_url": None,
            "PROJECT_BASE_CSS": "",
            "ui_lang": {
                "next_button": "Next",
                "previous_button": "Previous",
                "labeled_badge": "Labeled",
                "not_labeled_badge": "Not labeled",
                "submit_button": "Submit",
                "progress_label": "Progress",
                "go_button": "Go",
                "logout": "Logout",
                "loading": "Loading annotation interface...",
                "error_heading": "Error",
                "retry_button": "Retry",
                "adjudicate": "Adjudicate",
                "codebook": "Codebook",
            },
        }

    return app


class _StubItem:
    def get_id(self):
        return "item-1"

    def get_data(self):
        return {
            "id": "item-1",
            "text": "Test instance text",
        }

    def get_text(self):
        return "Test instance text"

    def get_displayed_text(self):
        return "Test instance text"


class _StubUserState:
    instance_id_ordering = ["item-1"]

    def get_current_phase_and_page(self):
        return (UserPhase.ANNOTATION, "page")

    def get_current_instance(self):
        return _StubItem()

    def get_current_instance_index(self):
        return 0

    def get_annotation_count(self):
        return 0

    def has_annotated(self, instance_id):
        return False

    def generate_user_statistics(self):
        return {}


class _StubUSM:
    def get_user_state(self, username):
        return _StubUserState()

    def get_phase_html_fname(self, phase, page):
        return "base_template_v2.html"


class _StubISM:
    def get_total_assignable_items_for_user(self, user_state):
        return 1


def _configure_render_mocks(monkeypatch, app, annotation_codebook_url):
    monkeypatch.setattr(fs, "app", app, raising=False)
    monkeypatch.setattr(fs, "config", {
        "annotation_task_name": "Header Codebook Test",
        "annotation_codebook_url": annotation_codebook_url,
        "annotation_schemes": [{
            "name": "sentiment",
            "annotation_type": "radio",
            "description": "Select sentiment",
            "labels": [{"name": "positive"}, {"name": "negative"}],
        }],
        "item_properties": {"text_key": "text", "kwargs": []},
        "site_file": "base_template_v2.html",
        "ui": {},
        "customjs": False,
        "debug": False,
        "alert_time_each_instance": 10000000,
    }, raising=False)
    monkeypatch.setattr(fs, "get_user_state_manager", lambda: _StubUSM())
    monkeypatch.setattr(fs, "get_item_state_manager", lambda: _StubISM())
    monkeypatch.setattr(fs, "get_quality_control_manager", lambda: None)
    monkeypatch.setattr(fs, "get_annotations_for_user_on", lambda username, instance_id: None)
    monkeypatch.setattr(fs, "get_span_annotations_for_user_on", lambda username, instance_id: [])
    monkeypatch.setattr(fs, "get_label_suggestions", lambda item, config, prefill: set())
    monkeypatch.setattr(fs, "_is_user_adjudicator", lambda username: False)


def test_render_page_with_annotations_shows_codebook_link(monkeypatch):
    app = _build_template_app()
    _configure_render_mocks(monkeypatch, app, "data_files/codebook.pdf")

    with app.test_request_context("/annotate"):
        rendered = fs.render_page_with_annotations("user1")

    assert 'class="codebook-btn"' in rendered
    assert 'href="/media/codebook.pdf"' in rendered
    assert 'title="Open annotation codebook"' in rendered
    assert "> Codebook" in rendered


def test_render_page_with_annotations_hides_codebook_link_without_url(monkeypatch):
    app = _build_template_app()
    _configure_render_mocks(monkeypatch, app, "")

    with app.test_request_context("/annotate"):
        rendered = fs.render_page_with_annotations("user1")

    assert 'class="codebook-btn"' not in rendered
    assert 'title="Open annotation codebook"' not in rendered
    assert 'href="/media/' not in rendered


def test_codebook_url_javascript_blocked(monkeypatch):
    """javascript: URLs in annotation_codebook_url should be blocked."""
    app = _build_template_app()
    _configure_render_mocks(monkeypatch, app, "javascript:alert(1)")

    with app.test_request_context("/annotate"):
        rendered = fs.render_page_with_annotations("user1")

    assert 'javascript:' not in rendered
    assert 'class="codebook-btn"' not in rendered


def test_codebook_url_data_blocked(monkeypatch):
    """data: URLs in annotation_codebook_url should be blocked."""
    app = _build_template_app()
    _configure_render_mocks(monkeypatch, app, "data:text/html,<script>alert(1)</script>")

    with app.test_request_context("/annotate"):
        rendered = fs.render_page_with_annotations("user1")

    assert 'data:' not in rendered
    assert 'class="codebook-btn"' not in rendered


def test_codebook_i18n_label(monkeypatch):
    """Codebook button should use ui_lang.codebook for the label."""
    app = _build_template_app()
    _configure_render_mocks(monkeypatch, app, "https://example.com/codebook.pdf")

    with app.test_request_context("/annotate"):
        rendered = fs.render_page_with_annotations("user1")

    # Default label from ui_lang_defaults
    assert "> Codebook" in rendered
