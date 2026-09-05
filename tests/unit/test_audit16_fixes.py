"""Regressions for the audit-16 findings.

Each test names the finding it guards and fails on the behaviour that was
reported, not on an approximation of it.
"""

import io

import pytest


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------- finding 1 --
# Keyword highlighting only ever scanned item_properties.text_key.

class TestKeywordScanCoversEverySpanTarget:
    @pytest.fixture
    def dialogue_project(self):
        """Configure the dict `_keyword_scan_fields` actually reads.

        `routes.config` is bound at import, so a test earlier in the run that
        rebinds `config_module.config` (rather than mutating it) leaves the two
        pointing at different dicts. Reaching through `routes` is correct
        whichever object won.
        """
        import potato.routes as routes
        from potato.item_state_management import set_configured_text_key

        config = routes.config
        previous = dict(config)
        config.clear()
        config.update({
            "item_properties": {"id_key": "id", "text_key": "resolution"},
            "instance_display": {"fields": [
                {"key": "turns", "type": "dialogue", "span_target": True},
                {"key": "resolution", "type": "text", "span_target": True},
                {"key": "caption", "type": "text"},
            ]},
        })
        set_configured_text_key("resolution")
        yield
        set_configured_text_key(previous.get("item_properties", {}).get("text_key"))
        config.clear()
        config.update(previous)

    @staticmethod
    def _item():
        from potato.item_state_management import Item
        return Item("D01", {
            "id": "D01",
            "turns": [
                {"speaker": "Customer", "text": "My order arrived damaged."},
                {"speaker": "Agent", "text": "Escalated to the returns team."},
            ],
            "resolution": "Refund issued the same day.",
            "caption": "a refund conversation",
        })

    def test_every_span_target_field_is_scanned(self, dialogue_project):
        import potato.routes as routes
        scanned = dict(routes._keyword_scan_fields(self._item()))
        assert "resolution" in scanned
        assert "turns" in scanned, (
            "the conversation was never scanned, so keywords in it were "
            "silently unhighlighted")

    def test_the_text_key_field_comes_first(self, dialogue_project):
        import potato.routes as routes
        fields = routes._keyword_scan_fields(self._item())
        assert fields[0][0] == "resolution", (
            "text_key must stay the default target for anything with no field "
            "of its own")

    def test_a_field_that_is_not_a_span_target_is_left_alone(self, dialogue_project):
        import potato.routes as routes
        scanned = dict(routes._keyword_scan_fields(self._item()))
        assert "caption" not in scanned, (
            "a keyword overlay cannot be drawn on a field nobody can mark")

    def test_a_dialogue_field_is_scanned_as_its_rendered_text(self, dialogue_project):
        """Offsets must index what the browser measured, speaker labels included."""
        import potato.routes as routes
        from potato.server_utils.displays.base import reconstruct_dialogue_dom_text

        scanned = dict(routes._keyword_scan_fields(self._item()))
        expected = reconstruct_dialogue_dom_text(self._item().get_data()["turns"])
        assert scanned["turns"] == expected
        assert scanned["turns"].startswith("Customer: ")

    def test_the_response_names_every_field_it_looked_at(self):
        source = _read("potato/routes.py")
        assert '"fields_scanned"' in source
        # Both branches, so a caller need not know which answered it.
        assert source.count('"fields_scanned"') >= 2

    def test_each_match_carries_the_field_it_was_found_in(self):
        source = _read("potato/routes.py")
        assert '"target_field": field_name,' in source


# --------------------------------------------------------------- finding 2 --
# A span on a dialogue field exported with text=''.

class TestDialogueSpansExportTheirText:
    @staticmethod
    def _context():
        from potato.export.base import ExportContext
        turns = [
            {"speaker": "Customer", "text": "My order arrived damaged and I want a refund."},
            {"speaker": "Agent", "text": "I'm sorry. Let me check the order."},
            {"speaker": "Customer", "text": "I've already waited three weeks."},
        ]
        item = {"id": "D01", "turns": turns,
                "resolution": "Refund issued the same day."}
        return ExportContext(
            config={"item_properties": {"id_key": "id", "text_key": "resolution"},
                    "instance_display": {"fields": [
                        {"key": "turns", "type": "dialogue"},
                        {"key": "resolution", "type": "text"}]}},
            annotations=[], items={"D01": item}, schemas=[], output_dir="."), turns

    def test_a_dialogue_span_resolves_instead_of_exporting_empty(self):
        from potato.server_utils.displays.base import reconstruct_dialogue_dom_text
        ctx, turns = self._context()
        anchor = reconstruct_dialogue_dom_text(turns)
        start = anchor.index("already waited three weeks")
        end = start + len("already waited three weeks")
        got = ctx.covered_text("D01", {"start": start, "end": end,
                                       "target_field": "turns"})
        assert got == "already waited three weeks"
        assert got != "", "the whole conversational span family exported empty"

    def test_it_matches_the_anchor_the_browser_measured(self):
        """Every window, not one lucky slice."""
        from potato.server_utils.displays.base import reconstruct_dialogue_dom_text
        ctx, turns = self._context()
        anchor = reconstruct_dialogue_dom_text(turns)
        for start in range(0, len(anchor) - 12, 5):
            got = ctx.covered_text("D01", {"start": start, "end": start + 12,
                                           "target_field": "turns"})
            assert got == anchor[start:start + 12], f"window at {start}"

    def test_a_plain_text_field_is_unchanged(self):
        ctx, _ = self._context()
        assert ctx.covered_text(
            "D01", {"start": 0, "end": 6, "target_field": "resolution"}) == "Refund"

    def test_a_list_field_with_no_display_entry_still_resolves(self):
        from potato.export.base import ExportContext
        ctx = ExportContext(
            config={"item_properties": {"text_key": "notes"}},
            annotations=[],
            items={"X": {"notes": ["alpha", "beta"]}},
            schemas=[], output_dir=".")
        assert ctx.covered_text("X", {"start": 0, "end": 5,
                                      "target_field": "notes"}) == "alpha"


# --------------------------------------------------------------- finding 3 --
# _parse_action raised TypeError on a string action and killed the thread.

class TestAgentActionCoercion:
    def test_a_string_action_naming_a_real_type_is_honoured(self):
        from potato.agent_runner import _coerce_action
        assert _coerce_action("done") == {"type": "done"}
        assert _coerce_action("  WAIT ") == {"type": "wait"}

    def test_free_text_becomes_a_wait_and_keeps_what_the_model_said(self):
        from potato.agent_runner import _coerce_action
        action = _coerce_action("click the Username field")
        assert action["type"] == "wait"
        assert action["_thought"] == "click the Username field"

    def test_a_dict_without_a_type_still_gets_one(self):
        from potato.agent_runner import _coerce_action
        assert _coerce_action({"x": 1})["type"] == "wait"

    def test_the_original_dict_is_not_mutated(self):
        from potato.agent_runner import _coerce_action
        original = {"x": 1}
        _coerce_action(original)
        assert original == {"x": 1}

    @pytest.mark.parametrize("reply", [
        '{"thought": "I need the fields.", "action": "click the Username field"}',
        '{"thought": "", "action": ["click"]}',
        '{"thought": "t", "action": 5}',
        '"just some prose"',
        '[1, 2]',
        'the model rambled',
        '```json\n{"thought":"t","action":"wait"}\n```',
    ])
    def test_no_reply_shape_raises(self, reply):
        """The crash reached the annotator's panel as a Python error."""
        from potato.agent_runner import AgentRunner
        thought, action = AgentRunner._parse_action(None, reply)
        assert isinstance(action, dict)
        assert "type" in action
        assert "_thought" not in action, "the caller must strip the carrier key"

    def test_the_reported_reply_keeps_its_thought(self):
        from potato.agent_runner import AgentRunner
        thought, action = AgentRunner._parse_action(
            None, '{"thought": "I need to identify the fields.", '
                  '"action": "click the Username field", "done": false}')
        assert thought == "I need to identify the fields."
        assert action == {"type": "wait"}


# --------------------------------------------------------------- finding 4 --
class TestLiveAgentStartUrl:
    @staticmethod
    def _start_url(value):
        import re
        from potato.server_utils.displays.live_agent_display import LiveAgentDisplay
        html = LiveAgentDisplay().render({"key": "url", "type": "live_agent"}, value)
        match = re.search(r'placeholder="Starting URL[^"]*"\s*\n?\s*value="([^"]*)"',
                          html)
        return match.group(1) if match else None

    def test_a_field_holding_the_url_seeds_the_box(self):
        assert self._start_url("http://localhost:9101/") == "http://localhost:9101/"

    def test_the_object_forms_still_work(self):
        assert self._start_url({"url": "http://x.test/"}) == "http://x.test/"
        assert self._start_url(
            {"start_url": "http://y.test/", "task_description": "sign in"}
        ) == "http://y.test/"

    def test_a_non_url_string_is_not_seeded(self):
        """Seeding it would send the agent somewhere meaningless."""
        assert self._start_url("some prose") == ""


# --------------------------------------------------------------- finding 5 --
class TestExampleLookupJoin:
    def test_list_examples_returns_the_key_get_example_takes(self):
        from potato.mcp_server.tools_local import list_examples
        entry = list_examples(limit=1)["examples"][0]
        assert entry["name"] == entry["dir"]

    def test_get_example_accepts_either_parameter(self):
        from potato.mcp_server.tools_local import get_example, list_examples
        entry = list_examples(limit=1)["examples"][0]
        assert "error" not in get_example(name=entry["name"])
        assert "error" not in get_example(dir=entry["dir"])

    def test_a_bad_lookup_says_what_shape_to_pass(self):
        from potato.mcp_server.tools_local import get_example
        result = get_example("check-box")
        assert "error" in result
        assert "list_examples" in result["hint"]
        assert result["did_you_mean"], "near matches make the join obvious"

    def test_calling_it_with_nothing_explains_itself(self):
        from potato.mcp_server.tools_local import get_example
        assert "error" in get_example()


# ------------------------------------------------------- the example's docs --
class TestLiveAgentExampleNamesEveryEndpoint:
    def test_openai_vision_is_listed(self):
        """The comment named two of the three, which would stop a vLLM user."""
        text = _read("examples/agent-traces/live-agent-evaluation/config.yaml")
        header = [l for l in text.splitlines()
                  if "Supported endpoint_type values" in l][0]
        for endpoint in ("anthropic_vision", "ollama_vision", "openai_vision"):
            assert endpoint in header
