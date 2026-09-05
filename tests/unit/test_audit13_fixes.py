"""
Regressions for the defects audit 13 found.

Named by the symptom, not by the function that produced it.
"""

import json
import os
import tempfile

import pytest


# --------------------------------------------------------------------------
# 1. A restart locked every annotator out, and handed their work to anyone
# --------------------------------------------------------------------------

class TestAccountsSurviveARestart:

    def test_in_memory_registration_is_written_to_disk(self, tmp_path):
        from potato.authentication import UserAuthenticator

        roster = tmp_path / "user_config.json"
        auth = UserAuthenticator(str(roster), auth_method="in_memory")
        auth.user_config_path_explicit = False  # the default, and the bug
        assert auth.add_user("rev1@x.com", "pw13") == "Success"
        auth.save_user_config()

        row = json.loads(roster.read_text().strip())
        assert row["username"] == "rev1@x.com"
        assert "$" in row["password"], "password must be stored salted+hashed"
        assert "pw13" not in roster.read_text()

    def test_the_roster_reads_back_and_the_password_still_matters(self, tmp_path):
        from potato.authentication import UserAuthenticator

        roster = tmp_path / "user_config.json"
        first = UserAuthenticator(str(roster), auth_method="in_memory")
        first.add_user("rev1@x.com", "pw13")
        first.save_user_config()

        # A second process, as after a restart.
        second = UserAuthenticator(str(roster), auth_method="in_memory")
        assert second.auth_backend.is_valid_username("rev1@x.com")
        assert second.auth_backend.authenticate("rev1@x.com", "pw13")
        assert not second.auth_backend.authenticate(
            "rev1@x.com", "a-completely-different-password")

    def test_a_known_username_cannot_be_re_registered(self, tmp_path):
        from potato.authentication import UserAuthenticator

        roster = tmp_path / "user_config.json"
        first = UserAuthenticator(str(roster), auth_method="in_memory")
        first.add_user("rev1@x.com", "pw13")
        first.save_user_config()

        second = UserAuthenticator(str(roster), auth_method="in_memory")
        assert second.add_user("rev1@x.com", "anything-else") == "Duplicate user"

    def test_a_username_owning_annotations_is_refused(self, tmp_path, monkeypatch):
        """Belt and braces for a roster that has gone missing."""
        from potato import routes

        output_dir = tmp_path / "annotation_output"
        (output_dir / "rev1@x.com").mkdir(parents=True)
        (output_dir / "rev1@x.com" / "user_state.json").write_text("{}")

        monkeypatch.setattr(routes, "config",
                            {"output_annotation_dir": str(output_dir)})

        assert routes._username_owns_annotations("rev1@x.com")
        assert not routes._username_owns_annotations("someone-else")


# --------------------------------------------------------------------------
# 2. Behind a reverse proxy, nobody could sign in
# --------------------------------------------------------------------------

class TestEveryAppLinkCarriesTheDeploymentPrefix:
    """Templates must not hardcode a root-relative app URL.

    `_url_prefix.js` patches fetch, sendBeacon and EventSource; it cannot patch
    an `href` or a form `action`, and the login page's two forms posted to the
    public root -- so a task mounted below a path could not admit anybody.
    """

    #: Not app routes: a protocol-relative URL, and anything already
    #: interpolated.
    ALLOWED = ("//",)

    def _templates(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2] / "potato" / "templates"
        return sorted(root.glob("*.html"))

    def test_no_template_hardcodes_a_root_relative_url(self):
        import re

        pattern = re.compile(r'(?:href|action|src)="(/(?!/)[^"]*)"')
        offenders = []
        for path in self._templates():
            for match in pattern.finditer(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.name}: {match.group(1)}")
        assert not offenders, (
            "These resolve against the public root and 404 behind a path "
            "prefix. Write them as \"{{ url_prefix }}/...\":\n  "
            + "\n  ".join(offenders))

    @pytest.mark.parametrize("template,needle", [
        ("home.html", '{{ url_prefix }}/auth'),
        ("home.html", '{{ url_prefix }}/register'),
        ("base_template_v2.html", '{{ url_prefix }}/logout'),
        ("base_template_v2.html", '{{ url_prefix }}/done'),
        ("base_template_v2.html", '{{ url_prefix }}/pocket'),
    ])
    def test_the_named_links_carry_the_prefix(self, template, needle):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2] / "potato" / "templates"
        assert needle in (root / template).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 3. An ingested trace reached annotators as a blank item
# --------------------------------------------------------------------------

class TestIngestedTracesKeepTheirFields:

    PAYLOAD = {
        "id": "ing03", "task": "Third", "repo": "docs", "status": "ok",
        "feedback": "down", "judge_score": 0.4, "reasoning": "1. a\n2. b",
        "patch": "x", "eval_steps": [{"speaker": "tool", "text": "t"}],
    }

    def test_every_supplied_field_survives_normalization(self):
        from potato.trace_ingestion.webhook_receiver import WebhookReceiver

        trace = WebhookReceiver(api_key="k").process_webhook(dict(self.PAYLOAD))

        for key in ("repo", "judge_score", "reasoning", "patch", "eval_steps"):
            assert key in trace, f"{key} was dropped between the POST and the item"
        assert trace["eval_steps"] == self.PAYLOAD["eval_steps"]

    def test_the_envelope_still_wins(self):
        from potato.trace_ingestion.webhook_receiver import WebhookReceiver

        trace = WebhookReceiver(api_key="k").process_webhook(dict(self.PAYLOAD))
        assert trace["id"] == "webhook_ing03"
        assert trace["task_description"] == "Third"

    def test_an_item_with_no_matching_field_says_so_on_the_page(self):
        from potato.server_utils.instance_display import InstanceDisplayRenderer

        renderer = InstanceDisplayRenderer({"instance_display": {"fields": [
            {"key": "task", "type": "text"},
            {"key": "patch", "type": "code"}]}})

        html = renderer.render({"id": "ing03", "text": "x", "steps": []})

        assert "nothing to show" in html
        assert "task" in html and "patch" in html


# --------------------------------------------------------------------------
# 4. submit_annotation over MCP always 500'd
# --------------------------------------------------------------------------

def test_save_user_state_accepts_a_username():
    """The MCP tool passed the name and got AttributeError from deep inside."""
    from potato.user_state_management import UserStateManager

    class FakeState:
        def get_user_id(self):
            return "rev1@x.com"

        def save(self, path):
            self.saved_to = path

    mgr = UserStateManager.__new__(UserStateManager)
    state = FakeState()
    mgr.config = {"output_annotation_dir": "/tmp/does-not-matter"}
    mgr._auto_export_formats = []
    mgr.get_user_state = lambda name: state if name == "rev1@x.com" else None

    mgr.save_user_state("rev1@x.com")
    assert state.saved_to.endswith("rev1@x.com")

    with pytest.raises(KeyError):
        mgr.save_user_state("nobody")


def test_mcp_submit_annotation_saves_the_state_object():
    import inspect

    from potato.mcp_server import routes

    src = inspect.getsource(routes.tool_submit_annotation)
    assert "usm.save_user_state(state)" in src


# --------------------------------------------------------------------------
# 5/6. Automation
# --------------------------------------------------------------------------

class TestAutomation:

    def test_the_manager_is_built_before_the_corpus_loads(self):
        import inspect

        from potato import flask_server

        src = inspect.getsource(flask_server)
        early = src.index("_init_automation_manager_early(config)")
        load = src.index("load_all_data(config)", early)
        assert early < load

    @pytest.mark.parametrize("rules,needle", [
        ([{"when": {"field": "repo", "equals": "docs"}, "actions": ["skip"]}],
         "must be a mapping"),
        ([{"when": {}, "sample": 0.5, "actions": []}], "sample_rate"),
        ([{"when": {}, "actions": [{"type": "teleport"}]}], "not an action"),
        ([{"when": {}, "sample_rate": 3.0, "actions": []}], "between 0 and 1"),
    ])
    def test_a_malformed_rule_is_a_config_error(self, rules, needle):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_automation_config)

        with pytest.raises(ConfigValidationError) as excinfo:
            validate_automation_config({"automation": {"enabled": True,
                                                       "rules": rules}})
        assert needle in str(excinfo.value)

    def test_a_correct_rule_validates(self):
        from potato.server_utils.config_module import validate_automation_config

        validate_automation_config({"automation": {"enabled": True, "rules": [
            {"name": "route-errors",
             "when": {"field": "status", "in": ["error", "failed"]},
             "sample_rate": 0.5,
             "actions": [{"type": "add_to_queue", "priority": 100},
                         {"type": "notify", "message": "New error trace"}]}]}})


# --------------------------------------------------------------------------
# 7. trace_ingestion.api_key as X-API-Key
# --------------------------------------------------------------------------

@pytest.mark.parametrize("headers", [
    {"Authorization": "Bearer trace-secret-13"},
    {"X-API-Key": "trace-secret-13"},
    {"X-Api-Key": "trace-secret-13"},   # what Werkzeug's title-casing produces
    {"x-api-key": "trace-secret-13"},
])
def test_the_webhook_accepts_both_documented_headers(headers):
    from potato.trace_ingestion.webhook_receiver import WebhookReceiver

    assert WebhookReceiver(api_key="trace-secret-13").validate_auth(headers)


def test_the_webhook_still_refuses_a_wrong_key():
    from potato.trace_ingestion.webhook_receiver import WebhookReceiver

    receiver = WebhookReceiver(api_key="trace-secret-13")
    assert not receiver.validate_auth({"X-API-Key": "wrong"})
    assert not receiver.validate_auth({})


# --------------------------------------------------------------------------
# 8. process_reward printed the raw step JSON; CoT steps were all observations
# --------------------------------------------------------------------------

class TestChainOfThoughtSteps:

    def test_the_widget_reads_a_step_written_under_text(self):
        from potato.server_utils.schemas.process_reward import (
            generate_process_reward_layout)

        html, _ = generate_process_reward_layout({
            "name": "step_rewards", "description": "d",
            "annotation_type": "process_reward", "steps_key": "cot_steps",
            "mode": "per_step"})
        # `text` must be in the fallback chain before JSON.stringify.
        chain = html[html.index("var stepText"):]
        assert chain.index("step.text") < chain.index("JSON.stringify(step)")

    def test_a_numbered_reasoning_step_is_a_thought(self):
        from potato.server_utils.displays._trace_normalize import (
            infer_type_from_text)

        assert infer_type_from_text(
            "1. First I need to reproduce the failure locally, so I will run "
            "the test in a loop.") == "thought"

    def test_segmented_chains_are_not_all_observations(self):
        from potato.server_utils.cot_segmentation import segment_cot

        steps = segment_cot(
            "1. First I need to reproduce the failure locally.\n"
            "2. run_tests(loop=20)\n"
            "3. The test failed 3 times out of 20, and the flake is real.\n",
            {"strategy": "numbered"})

        types = [s["type"] for s in steps]
        assert types.count("observation") < len(types), types
        assert "thought" in types

    def test_the_shipped_example_names_its_step_text_key(self):
        import pathlib

        import yaml

        root = pathlib.Path(__file__).resolve().parents[2]
        cfg = yaml.safe_load(
            (root / "examples/agent-traces/cot-process-reward/config.yaml")
            .read_text())
        scheme = next(s for s in cfg["annotation_schemes"]
                      if s["annotation_type"] == "process_reward")
        assert scheme["step_text_key"] == "text"


# --------------------------------------------------------------------------
# 9. Only depth_map resolved a path against media_directory
# --------------------------------------------------------------------------

class TestMediaReferencesResolve:

    @pytest.fixture
    def project(self, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        for name in ("shelf_a.png", "clip.mp4", "tone.wav", "incident.pdf"):
            (media / name).write_bytes(b"x")
        return str(tmp_path)

    @pytest.mark.parametrize("field_type,key", [
        ("image", "shelf_a.png"), ("gallery", "shelf_a.png"),
        ("video", "clip.mp4"), ("audio", "tone.wav"),
    ])
    def test_a_bare_filename_becomes_a_media_url(self, project, field_type, key):
        from potato.server_utils.instance_display import InstanceDisplayRenderer

        renderer = InstanceDisplayRenderer({
            "task_dir": project, "media_directory": "media",
            "instance_display": {"fields": [{"key": "f", "type": field_type}]}})

        html = renderer.render({"f": key})
        assert f"/media/{key}" in html

    def test_absolute_and_rooted_references_are_left_alone(self, project):
        from potato.media.paths import media_href

        config = {"task_dir": project, "media_directory": "media"}
        for reference in ("https://example.com/a.png", "data:image/png;base64,AA",
                          "/static/a.png", "/media/shelf_a.png"):
            assert media_href(config, reference) == reference

    def test_a_reference_to_no_file_is_left_alone(self, project):
        from potato.media.paths import media_href

        config = {"task_dir": project, "media_directory": "media"}
        assert media_href(config, "not-here.png") == "not-here.png"

    def test_traversal_is_still_refused(self, project):
        from potato.media.paths import media_href

        config = {"task_dir": project, "media_directory": "media"}
        assert media_href(config, "../../etc/passwd") == "../../etc/passwd"


# --------------------------------------------------------------------------
# 10. eval_trace showed the last tool call as the final answer
# --------------------------------------------------------------------------

def test_a_step_labelled_final_is_the_final_answer():
    import re

    from potato.server_utils.displays.eval_trace_display import EvalTraceDisplay

    html = EvalTraceDisplay().render({"key": "t", "type": "eval_trace"}, [
        {"speaker": "thought", "text": "I need to fix the whitespace handling."},
        {"speaker": "apply_patch", "text": "apply_patch(file='w.py')"},
        {"speaker": "final", "text": "[t10] FINAL: whitespace now behaves."},
    ])

    pane = re.search(
        r'<div class="eval-card eval-card-answer"><div class="eval-card-text">(.*?)</div>',
        html, re.S)
    assert pane and "FINAL: whitespace now behaves" in pane.group(1)


# --------------------------------------------------------------------------
# 11. The progress counter read N/N at num_annotators_per_item: 1
# --------------------------------------------------------------------------

def test_progress_denominator_at_one_annotator_per_item():
    from potato.item_state_management import ItemStateManager

    class FakeUserState:
        def get_assigned_instance_ids(self):
            return {"i0", "i1", "i2"}

        def has_annotated(self, iid):
            return False

    mgr = ItemStateManager.__new__(ItemStateManager)
    mgr.remaining_instance_ids = ["i0", "i1", "i2"]
    # With a cap of 1, the annotator's own hold saturates every item.
    mgr._item_is_saturated = lambda iid: True

    assert len(mgr.get_progress_pending_ids_for_user(FakeUserState())) == 3


# --------------------------------------------------------------------------
# 12/13. Small things
# --------------------------------------------------------------------------

def test_the_bare_datasets_prefix_is_routed():
    """`/datasets` was a 404: every page lived at a deeper path."""
    from flask import Flask

    from potato.eval_datasets.routes import datasets_bp

    app = Flask(__name__)
    app.register_blueprint(datasets_bp)
    rules = {r.rule for r in app.url_map.iter_rules()}

    assert "/datasets/" in rules or "/datasets" in rules
    assert "/datasets/admin" in rules


@pytest.mark.parametrize("data", [
    {"columns": ["Depot", "Temp"], "rows": [["A", "3.1"]]},
    {"columns": ["Depot", "Temp"], "rows": [{"Depot": "A", "Temp": "3.1"}]},
    {"headers": ["Depot"], "rows": [["A"]]},
    [{"Depot": "A"}],
])
def test_spreadsheet_renders_a_header_row(data):
    from potato.server_utils.displays.spreadsheet_display import SpreadsheetDisplay

    assert "<th" in SpreadsheetDisplay().render({"key": "t", "type": "spreadsheet"},
                                                data)


def test_pairwise_uses_the_labels_in_the_data():
    import re

    from potato.server_utils.displays.pairwise_display import PairwiseDisplay

    data = {"left": {"label": "Model A", "text": "one"},
            "right": {"label": "Model B", "text": "two"}}
    html = PairwiseDisplay().render({"key": "c", "type": "pairwise"}, data)

    assert re.findall(r'pairwise-label">([^<]*)<', html) == ["Model A", "Model B"]
    # display_options.labels still overrides them.
    html = PairwiseDisplay().render(
        {"key": "c", "type": "pairwise",
         "display_options": {"labels": ["Left", "Right"]}}, data)
    assert re.findall(r'pairwise-label">([^<]*)<', html) == ["Left", "Right"]


@pytest.mark.parametrize("textarea,expected", [
    ({"rows": 3}, True),
    ({"on": True}, True),
    ({"on": False, "rows": 3}, False),
])
def test_a_textarea_block_renders_a_textarea(textarea, expected):
    from potato.server_utils.schemas.textbox import generate_textbox_layout

    html, _ = generate_textbox_layout({
        "name": "t", "description": "d", "annotation_type": "textbox",
        "textarea": textarea})
    assert ("<textarea" in html) is expected


def test_a_list_valued_display_option_must_be_a_list():
    from potato.server_utils.config_module import (
        ConfigValidationError, _validate_display_options)

    with pytest.raises(ConfigValidationError) as excinfo:
        _validate_display_options("eval_trace", {"pane_labels": True}, "f[0]")
    assert "must be a list" in str(excinfo.value)

    _validate_display_options("eval_trace",
                              {"pane_labels": ["A", "B", "C"]}, "f[0]")


def test_the_mcp_refusal_names_the_command_that_creates_a_token():
    import inspect

    from potato.mcp_server import routes

    src = inspect.getsource(routes)
    assert src.count("potato mcp issue-token") >= 2
