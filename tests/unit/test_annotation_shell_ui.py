"""
Annotation-page shell: what the 2026-10 UI/UX audit found and fixed.

Each test renders the real ``base_template_v2.html`` (or calls the real phase
render path) and checks the resulting markup, not the template source.

- The text box under every item was one blank line too tall: the whitespace
  between ``{{ instance }}`` and the span-overlay layer sat inside a
  ``white-space: pre-wrap`` element and rendered as an extra line.
- "Text to Annotate:" headed every item, including ones whose text field is a
  ``<video>``, ``<audio>`` or ``<img>``.
- The jump-to-unlabeled buttons were bare backward/forward glyphs, which read
  as plain previous/next.
- Display stylesheets (spreadsheet, coding trace, turn annotations, multi-agent
  discussion, audio dialogue) loaded on every page whether or not the page
  rendered that display.
- Consent/instructions/survey pages showed jump and go-to controls for
  annotation instances they do not have.
"""

import os
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "potato" / "templates"


def _env():
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    env.globals["url_for"] = lambda endpoint, **kw: f"/static/{kw.get('filename', '')}"
    env.filters["sanitize_html"] = lambda x: x
    return env


def _render(**overrides):
    from potato.server_utils.i18n import UI_LANG_DEFAULTS

    context = {
        "username": "u",
        "annotation_task_name": "T",
        "instance": "Aliquam eius modi ut.",
        "instance_plain_text": "Aliquam eius modi ut.",
        "instance_id": "1",
        "instance_index": 0,
        "finished": 0,
        "total_count": 3,
        "is_annotation_page": True,
        "annotation_status": "unlabeled",
        "jumping_to_id_disabled": False,
        "ui_lang": dict(UI_LANG_DEFAULTS),
        "frontend_assets": {},
    }
    context.update(overrides)
    html = _env().get_template("base_template_v2.html").render(**context)
    return BeautifulSoup(html, "html.parser")


class TestInstanceTextBox:
    def test_no_whitespace_follows_the_instance_inside_the_pre_wrap_box(self):
        soup = _render()
        content = soup.find(id="text-content")
        # Every text node in the box is the instance itself; anything else is
        # rendered by pre-wrap as visible blank space.
        texts = [t for t in content.find_all(string=True, recursive=False)]
        assert "".join(texts) == "Aliquam eius modi ut."

    def test_the_overlay_layer_is_still_inside_the_box(self):
        soup = _render()
        assert soup.find(id="text-content").find(id="span-overlays") is not None

    def test_the_instance_area_is_marked_for_the_empty_collapse_rule(self):
        soup = _render()
        area = soup.find(id="text-content").find_parent(class_="instance-area")
        assert area is not None


class TestInstanceHeading:
    @pytest.mark.parametrize("instance, expected", [
        ("Plain words.", "Text to Annotate:"),
        ('<video src="a.mp4"></video>', "Video to Annotate:"),
        ('<AUDIO src="a.mp3"></AUDIO>', "Audio to Annotate:"),
        ('<img src="a.png">', "Image to Annotate:"),
    ])
    def test_the_heading_names_what_the_item_is(self, instance, expected):
        soup = _render(instance=instance)
        assert soup.find(class_="instance-text-heading").get_text(strip=True) == expected

    def test_an_explicit_heading_still_wins(self):
        soup = _render(instance='<video src="a.mp4"></video>',
                       instance_text_heading="Training Question")
        assert soup.find(class_="instance-text-heading").get_text(strip=True) == "Training Question"


class TestJumpControls:
    def test_the_pair_is_captioned_and_each_button_is_named(self):
        soup = _render()
        group = soup.find(class_="nav-controls")
        assert group.find(class_="nav-controls-label").get_text(strip=True) == "Unlabeled"
        prev_btn = soup.find(id="jump-unannotated-prev-btn")
        next_btn = soup.find(id="jump-unannotated-btn")
        assert prev_btn["aria-label"] == "Previous unannotated"
        assert next_btn["aria-label"] == "Next unannotated"

    def test_the_glyphs_are_step_icons_not_plain_back_forward(self):
        soup = _render()
        icons = [i["class"] for i in soup.find(class_="nav-controls").find_all("i")]
        assert ["fas", "fa-backward-step"] in icons
        assert ["fas", "fa-forward-step"] in icons

    def test_the_caption_is_localisable(self):
        from potato.server_utils.i18n import UI_LANG_DEFAULTS

        lang = dict(UI_LANG_DEFAULTS, jump_unannotated_label="Sin etiquetar")
        soup = _render(ui_lang=lang)
        assert soup.find(class_="nav-controls-label").get_text(strip=True) == "Sin etiquetar"


DISPLAY_STYLESHEETS = {
    "turn_annotations": "turn-annotations.css",
    "multi_agent_discussion": "multi-agent-discussion.css",
    "audio_dialogue": "audio-dialogue.css",
    "spreadsheet_display": "spreadsheet-display.css",
    "coding_trace": "coding-trace.css",
}


def _stylesheets(soup):
    return {link["href"].split("/")[-1].split("?")[0]
            for link in soup.find_all("link", rel="stylesheet")}


class TestDisplayStylesheetGating:
    def test_a_plain_page_loads_none_of_them(self):
        loaded = _stylesheets(_render())
        assert not (set(DISPLAY_STYLESHEETS.values()) & loaded)

    @pytest.mark.parametrize("key, filename", sorted(DISPLAY_STYLESHEETS.items()))
    def test_each_loads_when_its_display_is_on_the_page(self, key, filename):
        loaded = _stylesheets(_render(frontend_assets={key: True}))
        assert filename in loaded

    @pytest.mark.parametrize("markup, key", [
        ('<div class="spreadsheet-display border-rounded"><table></table></div>', "spreadsheet_display"),
        ('<div class="spreadsheet-error">Unsupported data format</div>', "spreadsheet_display"),
        ('<div class="coding-trace-display layout-x"></div>', "coding_trace"),
        ('<div class="lca-turns coding-trace-display"></div>', "coding_trace"),
        ('<div class="multi-agent-discussion" data-field-key="t"></div>', "multi_agent_discussion"),
    ])
    def test_the_marker_scan_finds_the_display(self, tmp_path, markup, key):
        from potato.flask_server import _detect_frontend_assets_for_page

        page = tmp_path / "page.html"
        page.write_text("<html><body></body></html>", encoding="utf-8")
        assert _detect_frontend_assets_for_page(str(page), display_html=markup)[key] is True


class TestPhasePagesHaveNoInstanceNavigation:
    def _render_phase(self, monkeypatch, tmp_path, phase):
        from flask import Flask

        import potato.flask_server as fs
        from potato.phase import UserPhase

        (tmp_path / "page.html").write_text(
            "{{ 'JUMP_DISABLED' if jumping_to_id_disabled else 'JUMP_ENABLED' }}",
            encoding="utf-8")
        app = Flask(__name__, template_folder=str(tmp_path))
        app.secret_key = "t"

        class StubUserState:
            phase_to_page_to_label_to_value = {}

            def get_current_phase_and_page(self):
                return (getattr(UserPhase, phase), "page")

            def get_assigned_instance_count(self):
                return 0

        class StubUSM:
            def get_phase_html_fname(self, phase, page):
                return "page.html"

            def can_user_go_back(self, user_id):
                return False

        monkeypatch.setattr(fs, "app", app, raising=False)
        monkeypatch.setattr(fs, "get_user_state", lambda username: StubUserState())
        monkeypatch.setattr(fs, "get_user_state_manager", lambda: StubUSM())
        with app.test_request_context("/"):
            return fs.get_current_page_html({"annotation_task_name": "T"}, "u")

    @pytest.mark.parametrize("phase", ["CONSENT", "INSTRUCTIONS", "PRESTUDY", "POSTSTUDY"])
    def test_jump_and_go_to_are_off_on_phase_pages(self, monkeypatch, tmp_path, phase):
        assert "JUMP_DISABLED" in self._render_phase(monkeypatch, tmp_path, phase)

    def test_the_annotation_phase_keeps_the_configured_setting(self, monkeypatch, tmp_path):
        # Only non-annotation pages lose the controls; an annotation page
        # rendered through this path still follows jumping_to_id_disabled.
        assert "JUMP_ENABLED" in self._render_phase(monkeypatch, tmp_path, "ANNOTATION")
