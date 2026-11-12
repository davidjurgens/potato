"""
Regression tests for the annotation-telemetry template wiring.

Potato renders annotation pages and phase pages (consent, instructions,
training, surveys) through **two different functions**. The telemetry script tag
is conditional, so a context variable added to only one of them means the
feature silently does nothing on the other half of the workflow.

That is not a hypothetical for this feature. The TRAINING phase renders real
annotation schemes through ``get_current_page_html`` — including image
annotation — and a new annotator's drawing behaviour during training is the
most worth measuring there is. Telemetry wired only into the annotation path
would collect nothing from exactly the sessions it exists for.

Mirrors tests/unit/test_keystroke_template_wiring.py; the two behavioural
subsystems have the same hazard and should fail the same way.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FLASK_SERVER = REPO_ROOT / "potato" / "flask_server.py"
BASE_TEMPLATE = REPO_ROOT / "potato" / "templates" / "base_template_v2.html"
ROUTES = REPO_ROOT / "potato" / "routes.py"

#: Every function that renders a page which can contain a drawing canvas.
RENDER_PATHS = ["render_page_with_annotations", "get_current_page_html"]

#: Match the actual <script> tag, not a mention of the filename in a comment.
TRACKER_TAG = "filename='annotation_telemetry.js'"


@pytest.fixture(scope="module")
def server_source():
    return FLASK_SERVER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def template():
    return BASE_TEMPLATE.read_text(encoding="utf-8")


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
        assert "annotation_telemetry_enabled" in body, (
            f"{func}() does not pass annotation_telemetry_enabled, so the "
            f"tracker script will never load on the pages it renders."
        )

    @pytest.mark.parametrize("func", RENDER_PATHS)
    def test_render_path_supplies_the_client_config(self, server_source, func):
        body = _function_body(server_source, func)
        assert "annotation_telemetry_client_config" in body, (
            f"{func}() does not pass annotation_telemetry_client_config, so the "
            f"tracker would load with no configuration."
        )

    @pytest.mark.parametrize("func", RENDER_PATHS)
    def test_render_path_uses_the_shared_accessor(self, server_source, func):
        """Both paths must build the config the same way, or the two halves of
        the workflow can disagree about what is enabled."""
        body = _function_body(server_source, func)
        assert "get_annotation_telemetry_client_config" in body

    def test_template_guards_the_script_tag(self, template):
        assert "annotation_telemetry.js" in template
        assert "annotation_telemetry_enabled" in template, (
            "The tracker script must be behind the enable flag; loading it "
            "unconditionally would run behavioural capture on projects that "
            "never opted in."
        )

    def test_tracker_loads_after_interaction_tracker(self, template):
        """annotation_telemetry.js hooks interactionTracker.setInstanceId so both
        cut their sessions on the same navigation boundary. If it loaded first,
        the hook would silently not attach."""
        assert template.index("filename='interaction_tracker.js'") < \
            template.index(TRACKER_TAG)


class TestDisclosure:
    def test_notice_is_rendered_server_side(self, template):
        """The notice must be Jinja, not JavaScript: an annotator who blocks
        scripts can still be measured by whatever does load, and a tracker that
        fails to load must not take the disclosure down with it."""
        assert "annotation-telemetry-disclosure" in template

    def test_notice_precedes_the_tracker_script(self, template):
        """It is markup in <body>, not something the tracker injects."""
        assert template.index("annotation-telemetry-disclosure") < \
            template.index(TRACKER_TAG)

    def test_notice_is_guarded(self, template):
        """Projects that never opted in must not see a recording notice."""
        block = template.split("annotation-telemetry-disclosure")[0]
        assert "annotation_telemetry_enabled" in block[-600:]


class TestThresholdsStaySeverSide:
    def test_client_config_carries_no_thresholds(self):
        """Shipping them would tell an annotator exactly how long to wait
        before clicking accept."""
        from potato.server_utils.config_module import (
            get_annotation_telemetry_client_config)

        client = get_annotation_telemetry_client_config({
            "annotation_telemetry": {
                "enabled": True,
                "detection": {"thresholds": {"ai_accept_latency_ms": 900}},
            }
        })
        assert "detection" not in client
        assert "thresholds" not in str(client)


class TestRouteRegistration:
    """A @app.route decorator alone 404s under `potato start`; the live app is
    built by create_app() and only sees what configure_routes() registers."""

    @pytest.fixture(scope="class")
    def routes_source(self):
        return ROUTES.read_text(encoding="utf-8")

    @pytest.mark.parametrize("rule", [
        "/api/track_annotation_telemetry",
        "/api/annotation_telemetry/<instance_id>",
        "/admin/api/annotation_process",
    ])
    def test_rule_is_added_in_configure_routes(self, routes_source, rule):
        assert f'add_url_rule("{rule}"' in routes_source, (
            f"{rule} has a decorator but no add_url_rule, so it will 404 "
            f"under `potato start`."
        )
