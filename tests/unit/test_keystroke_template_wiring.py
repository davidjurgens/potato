"""
Regression tests for the keystroke-tracker template wiring.

Potato renders annotation pages and phase pages (consent, instructions,
training, surveys) through **two different functions**. The keystroke tracker's
script tag is conditional, so a context variable added to only one of them means
the feature silently does nothing on the other half of the workflow — which is
exactly the bug these tests exist to prevent.

Free-text answers on phase pages matter: the training phase is how the
calibration example collects transcription exemplars, and prestudy/poststudy
surveys are full of open-ended questions.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FLASK_SERVER = REPO_ROOT / "potato" / "flask_server.py"
BASE_TEMPLATE = REPO_ROOT / "potato" / "templates" / "base_template_v2.html"

#: Every function that renders a page which can contain a free-text field.
RENDER_PATHS = ["render_page_with_annotations", "get_current_page_html"]


@pytest.fixture(scope="module")
def server_source():
    return FLASK_SERVER.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    """Slice out one top-level function definition."""
    match = re.search(rf"^def {re.escape(name)}\(", source, re.MULTILINE)
    assert match, f"{name}() not found in flask_server.py"
    start = match.start()
    nxt = re.search(r"^def \w+\(", source[start + 1:], re.MULTILINE)
    end = start + 1 + nxt.start() if nxt else len(source)
    return source[start:end]


class TestTemplateWiring:
    @pytest.mark.parametrize("func", RENDER_PATHS)
    def test_render_path_supplies_the_enable_flag(self, server_source, func):
        body = _function_body(server_source, func)
        assert "keystroke_logging_enabled" in body, (
            f"{func}() does not pass keystroke_logging_enabled, so the tracker "
            f"script will never load on the pages it renders."
        )

    @pytest.mark.parametrize("func", RENDER_PATHS)
    def test_render_path_supplies_the_client_config(self, server_source, func):
        body = _function_body(server_source, func)
        assert "keystroke_client_config" in body, (
            f"{func}() does not pass keystroke_client_config, so the tracker "
            f"would load with no configuration."
        )

    @pytest.mark.parametrize("func", RENDER_PATHS)
    def test_render_path_uses_the_shared_accessor(self, server_source, func):
        """Both paths must build the config the same way, or the two halves of
        the workflow can disagree about what is enabled."""
        body = _function_body(server_source, func)
        assert "get_keystroke_client_config" in body

    def test_template_guards_the_script_tag(self):
        html = BASE_TEMPLATE.read_text(encoding="utf-8")
        assert "keystroke_tracker.js" in html
        assert "keystroke_logging_enabled" in html, (
            "The tracker script must be behind the enable flag; loading it "
            "unconditionally would run keystroke capture on projects that never "
            "opted in."
        )

    def test_tracker_loads_after_interaction_tracker(self):
        """keystroke_tracker.js hooks interactionTracker.setInstanceId so both
        cut their sessions on the same navigation boundary. If it loaded first,
        the hook would silently not attach."""
        html = BASE_TEMPLATE.read_text(encoding="utf-8")
        assert html.index("interaction_tracker.js") < html.index("keystroke_tracker.js")

    def test_thresholds_are_not_in_the_template(self):
        """Detection thresholds are server-side only."""
        html = BASE_TEMPLATE.read_text(encoding="utf-8")
        assert "detection" not in html.split("keystroke_tracker.js")[0][-600:]
