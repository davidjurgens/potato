"""Participant-facing strings follow ``ui_language``.

With ``ui_language: de`` these stayed English: the ``select`` placeholder, the
``text`` character counter, and the whole completion page (done.html). The
schema layouts build HTML in Python and had no access to ``ui_lang``; they now
read their strings through ``i18n.ui_text``. done.html reads ``ui_lang``.

The English output must not change for a study without ``ui_language``.
"""

import re
from pathlib import Path

import pytest
from flask import Flask, render_template

from potato.server_utils import config_module
from potato.server_utils.i18n import (
    ANNOTATION_JS_KEYS, UI_LANG_DEFAULTS, resolve_ui_language, ui_text)
from potato.server_utils.schemas.select import generate_select_layout
from potato.server_utils.schemas.textbox import generate_textbox_layout

POTATO_DIR = Path(config_module.__file__).resolve().parent.parent


@pytest.fixture
def ui_language(monkeypatch):
    """Set ``ui_language`` in the loaded config for one test."""
    def _set(value):
        monkeypatch.setitem(config_module.config, "ui_language", value)
    monkeypatch.delitem(config_module.config, "ui_language", raising=False)
    return _set


SELECT = {"annotation_type": "select", "name": "frame", "description": "Frame?",
          "labels": ["a", "b"]}


def _text(min_chars=0, show=False):
    scheme = {"annotation_type": "text", "name": "why", "description": "Why?"}
    if min_chars:
        scheme["min_chars"] = min_chars
    if show:
        scheme["show_char_count"] = True
    return scheme


class TestUiText:
    def test_default_is_english(self, ui_language):
        assert ui_text("select_placeholder") == "-- select one --"

    def test_bundled_catalog(self, ui_language):
        ui_language("de")
        assert ui_text("select_placeholder") == "– Bitte auswählen –"

    def test_inline_override_wins(self, ui_language):
        ui_language({"_base": "de", "select_placeholder": "Wählen"})
        assert ui_text("select_placeholder") == "Wählen"

    def test_bad_placeholder_falls_back_to_english(self, ui_language):
        ui_language({"char_count": "{oops} Zeichen"})
        assert ui_text("char_count", count="7") == "7 characters"


class TestSelectPlaceholder:
    def test_english_unchanged(self, ui_language):
        html, _ = generate_select_layout(SELECT)
        assert ">-- select one --</option>" in html

    def test_german(self, ui_language):
        ui_language("de")
        html, _ = generate_select_layout(SELECT)
        assert ">– Bitte auswählen –</option>" in html
        assert "select one" not in html

    def test_predefined_list_is_translated_too(self, ui_language):
        ui_language("de")
        html, _ = generate_select_layout({**SELECT, "use_predefined_labels": "country"})
        assert "– Bitte auswählen –" in html
        assert "select one" not in html


class TestCharCounter:
    COUNT = '<span class="shadcn-textbox-char-count">0</span>'

    def test_english_min_chars_unchanged(self, ui_language):
        html, _ = generate_textbox_layout(_text(min_chars=40))
        assert f"{self.COUNT}/40 min characters" in html

    def test_english_plain_count_unchanged(self, ui_language):
        html, _ = generate_textbox_layout(_text(show=True))
        assert f"{self.COUNT} characters" in html

    def test_german_min_chars(self, ui_language):
        ui_language("de")
        html, _ = generate_textbox_layout(_text(min_chars=40))
        assert f"{self.COUNT} von mindestens 40 Zeichen" in html
        assert "characters" not in html

    def test_translation_is_escaped(self, ui_language):
        ui_language({"char_count": "{count} <b>Zeichen</b>"})
        html, _ = generate_textbox_layout(_text(show=True))
        assert "&lt;b&gt;Zeichen&lt;/b&gt;" in html


class TestAnnotationJsKeys:
    """annotation.js, ANNOTATION_JS_KEYS and the English defaults agree."""

    JS = (POTATO_DIR / "static" / "annotation.js").read_text(encoding="utf-8")

    def test_every_uitext_key_is_sent_to_the_page(self):
        used = set(re.findall(r"uiText\(\s*'(\w+)'", self.JS))
        used |= set(re.findall(r"'(required_question_\w+)'", self.JS))
        assert used, "no uiText() calls found"
        assert used <= set(ANNOTATION_JS_KEYS)

    def test_every_sent_key_has_an_english_default(self):
        assert set(ANNOTATION_JS_KEYS) <= set(UI_LANG_DEFAULTS)

    def test_js_fallback_matches_the_english_default(self):
        block = self.JS[self.JS.index("const UI_TEXT_FALLBACK = {"):]
        block = block[:block.index("};")]
        for key in ANNOTATION_JS_KEYS:
            assert f"{key}:" in block, key
        # One-line entries must be the English default word for word.
        for key, text in re.findall(r"^\s+(\w+): '([^'\n]*)',\s*$", block, re.M):
            assert text == UI_LANG_DEFAULTS[key], key


def _render_done(ui_language_value, **context):
    app = Flask(__name__, template_folder=str(POTATO_DIR / "templates"),
                static_folder=str(POTATO_DIR / "static"))
    ui_lang = resolve_ui_language(ui_language_value, UI_LANG_DEFAULTS)
    with app.test_request_context("/done"):
        return render_template("done.html", ui_lang=ui_lang, title="Studie",
                               ui_theme="auto", **context)


class TestDonePage:
    def test_english_unchanged(self):
        html = _render_done(None, completion_code="C0DE")
        assert '<html lang="en"' in html
        assert "Thank You!" in html
        assert "You have completed the annotation task and your responses are saved." in html
        assert "Click to copy your completion code" in html
        assert "Copy the code above and paste it in your crowdsourcing platform to receive credit." in html
        assert "Your responses are stored on this study&#39;s own server." in html

    def test_german(self):
        html = _render_done("de", completion_code="C0DE")
        assert '<html lang="de"' in html
        assert "Vielen Dank!" in html
        assert "Sie haben die Aufgabe abgeschlossen." in html
        assert "Klicken Sie, um Ihren Abschlusscode zu kopieren" in html
        for english in ("Thank You", "You have completed", "Click to copy",
                        "Copy the code above", "Your responses are stored",
                        "Copied!", "Please select and copy manually"):
            assert english not in html, english

    def test_german_platform_button(self):
        class Action:
            kind = "redirect"
            platform_label = "Prolific"
            redirect_url = "https://app.prolific.com/submissions/complete?cc=X"
            message = None
        html = _render_done("de", completion_code="X", action=Action())
        assert "Zurück zu Prolific" in html
        assert "Return to" not in html

    def test_german_without_code(self):
        html = _render_done("de")
        assert "Sie können dieses Fenster jetzt schließen." in html
