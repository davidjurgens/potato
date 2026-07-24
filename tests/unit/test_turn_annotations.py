"""
Unit tests for the turn-level annotation framework.

Covers: binding filter matrix, stable turn ids, slot rendering (including the
no-real-inputs proxy contract), the form-area anchor layout, config
validation, export flattening, and display integration for dialogue and
agent_trace.
"""

import pytest

from potato.server_utils.turn_annotations import (
    TURN_LEVEL_SUPPORTED_TYPES,
    build_turn_index,
    extract_tool_name,
    flatten_turn_annotation,
    generate_turn_level_anchor_layout,
    get_turn_level_schemes,
    render_turn_slot,
    schemes_for_field,
    turn_id_for,
    turn_matches_binding,
)


def make_scheme(**overrides):
    scheme = {
        "annotation_type": "multiselect",
        "name": "turn_errors",
        "description": "Errors in this turn",
        "labels": ["hallucination", "wrong_tool"],
        "turn_level": True,
        "turn_binding": {"field": "conversation", "speakers": ["Assistant"]},
    }
    scheme.update(overrides)
    return scheme


TURNS = [
    {"speaker": "User", "text": "hi"},
    {"speaker": "Assistant", "text": "hello"},
    {"speaker": "Agent (Action)", "text": "search(q=1)", "turn_id": "s9"},
    {"speaker": "Planner", "text": "step here", "agent_id": "planner"},
]


class TestBindingFilters:
    def test_empty_binding_matches_all(self):
        for i, turn in enumerate(TURNS):
            assert turn_matches_binding(turn, i, {})

    def test_speaker_filter(self):
        binding = {"speakers": ["Assistant"]}
        assert not turn_matches_binding(TURNS[0], 0, binding)
        assert turn_matches_binding(TURNS[1], 1, binding)

    def test_agent_filter(self):
        binding = {"agents": ["planner"]}
        assert turn_matches_binding(TURNS[3], 3, binding)
        assert not turn_matches_binding(TURNS[0], 0, binding)

    def test_step_type_filter_inferred_from_speaker(self):
        binding = {"step_types": ["action"]}
        assert turn_matches_binding(TURNS[2], 2, binding)
        assert not turn_matches_binding(TURNS[3], 3, binding)

    def test_step_type_filter_explicit(self):
        turn = {"speaker": "X", "text": "y", "type": "thought"}
        assert turn_matches_binding(turn, 0, {"step_types": ["thought"]})
        assert not turn_matches_binding(turn, 0, {"step_types": ["action"]})

    def test_tool_filter_from_text(self):
        assert turn_matches_binding(TURNS[2], 2, {"tools": ["search"]})
        assert not turn_matches_binding(TURNS[2], 2, {"tools": ["browser"]})

    def test_tool_filter_from_explicit_key(self):
        turn = {"speaker": "Agent (Action)", "text": "...", "tool": "browser"}
        assert turn_matches_binding(turn, 0, {"tools": ["browser"]})

    def test_turn_range(self):
        binding = {"turn_range": [1, 2]}
        assert not turn_matches_binding(TURNS[0], 0, binding)
        assert turn_matches_binding(TURNS[1], 1, binding)
        assert turn_matches_binding(TURNS[2], 2, binding)
        assert not turn_matches_binding(TURNS[3], 3, binding)

    def test_filters_and_together(self):
        binding = {"speakers": ["Assistant"], "turn_range": [0, 0]}
        assert not turn_matches_binding(TURNS[1], 1, binding)


class TestTurnIds:
    def test_index_fallback(self):
        assert turn_id_for({"speaker": "a"}, 4) == "t4"

    def test_explicit_turn_id(self):
        assert turn_id_for({"turn_id": "s9"}, 2) == "s9"

    def test_explicit_step_id(self):
        assert turn_id_for({"step_id": 12}, 0) == "12"

    def test_turn_index_records(self):
        idx = build_turn_index(TURNS)
        assert [r["turn_id"] for r in idx] == ["t0", "t1", "s9", "t3"]
        assert idx[2]["tool"] == "search"
        assert idx[2]["step_type"] == "action"
        assert idx[3]["agent_id"] == "planner"


class TestToolExtraction:
    def test_from_text_action(self):
        assert extract_tool_name(
            {"speaker": "Agent (Action)", "text": "search(q=1)"}) == "search"

    def test_from_tool_calls_list(self):
        assert extract_tool_name({"tool_calls": [{"name": "browser"}]}) == "browser"

    def test_non_action_text_not_parsed(self):
        assert extract_tool_name({"speaker": "User", "text": "why(oh why)"}) == ""


class TestSlotRendering:
    def test_no_match_returns_empty(self):
        assert render_turn_slot([make_scheme()], TURNS[0], 0, "conversation") == ""

    def test_proxy_contract_no_real_inputs(self):
        """R3: slot widgets must never carry annotation-input class or
        schema/label_name attributes (the global persistence pipeline in
        annotation.js would pick them up as real annotations)."""
        schemes = [
            make_scheme(),
            make_scheme(annotation_type="radio", name="r"),
            make_scheme(annotation_type="likert", name="l", size=5),
            make_scheme(annotation_type="slider", name="s", min_value=0, max_value=10),
            make_scheme(annotation_type="select", name="sel"),
            make_scheme(annotation_type="textbox", name="tb"),
            make_scheme(annotation_type="number", name="n"),
        ]
        html = render_turn_slot(schemes, TURNS[1], 1, "conversation")
        assert "turn-anno-slot" in html
        assert "annotation-input" not in html
        assert "annotation-data-input" not in html
        assert "label_name" not in html
        # No *bare* schema attribute (annotation.js keys on the annotation-input
        # class + a bare schema attr); the namespaced data-ta-schema is safe.
        assert ' schema="' not in html

    def test_slot_carries_snapshot_attributes(self):
        html = render_turn_slot([make_scheme()], TURNS[1], 1, "conversation")
        assert 'data-turn-id="t1"' in html
        assert 'data-speaker="Assistant"' in html
        assert 'data-field-key="conversation"' in html

    def test_explicit_turn_id_used(self):
        scheme = make_scheme(turn_binding={"speakers": ["Agent (Action)"]})
        html = render_turn_slot([scheme], TURNS[2], 2, "conversation")
        assert 'data-turn-id="s9"' in html

    def test_drawer_placement(self):
        scheme = make_scheme(turn_binding={"placement": "drawer"})
        html = render_turn_slot([scheme], TURNS[1], 1, "conversation")
        assert "ta-drawer-toggle" in html
        assert 'class="ta-drawer"' in html

    def test_widget_families(self):
        cases = {
            "radio": "ta-chip",
            "multiselect": "ta-chip",
            "likert": "ta-likert",
            "slider": "ta-range",
            "select": "ta-select",
            "textbox": "ta-text",
            "number": "ta-number",
        }
        for ann_type, marker in cases.items():
            scheme = make_scheme(
                annotation_type=ann_type, name=f"x_{ann_type}",
                turn_binding={}, size=5, min_value=0, max_value=10)
            html = render_turn_slot([scheme], TURNS[1], 1, "conversation")
            assert marker in html, f"{ann_type} missing {marker}"

    def test_dict_labels_supported(self):
        scheme = make_scheme(labels=[{"name": "a", "tooltip": "t"}, "b"], turn_binding={})
        html = render_turn_slot([scheme], TURNS[0], 0, "conversation")
        assert 'data-value="a"' in html and 'data-value="b"' in html

    def test_html_escaping(self):
        scheme = make_scheme(labels=['<script>alert(1)</script>'], turn_binding={})
        html = render_turn_slot([scheme], {"speaker": '<b>x</b>', "text": "y"}, 0, "conversation")
        assert "<script>" not in html
        assert "<b>" not in html.replace('data-speaker="&lt;b&gt;x&lt;/b&gt;"', "")


class TestAnchorLayout:
    def test_anchor_has_hidden_data_input(self):
        html, keybindings = generate_turn_level_anchor_layout(make_scheme())
        assert keybindings == []
        assert 'class="annotation-data-input turn-anno-hidden"' in html
        assert 'name="turn_errors"' in html
        assert 'data-schema-name="turn_errors"' in html

    def test_generate_schematic_intercepts_turn_level(self):
        from potato.server_utils.front_end import generate_schematic
        html, keybindings = generate_schematic(make_scheme())
        assert "turn-level-anchor" in html
        assert keybindings == []

    def test_generate_schematic_normal_schemes_unaffected(self):
        from potato.server_utils.front_end import generate_schematic
        html, _ = generate_schematic({
            "annotation_type": "radio", "name": "plain",
            "description": "d", "labels": ["a", "b"],
        })
        assert "turn-level-anchor" not in html


class TestConfigDiscovery:
    def test_top_level_schemes(self):
        cfg = {"annotation_schemes": [make_scheme(), {"annotation_type": "radio",
                                                      "name": "x", "description": "d",
                                                      "labels": ["a"]}]}
        found = get_turn_level_schemes(cfg)
        assert len(found) == 1 and found[0]["name"] == "turn_errors"

    def test_phase_schemes(self):
        cfg = {"phases": {"main": {"annotation_schemes": [make_scheme()]}, "order": ["main"]}}
        assert len(get_turn_level_schemes(cfg)) == 1

    def test_schemes_for_field(self):
        bound = make_scheme()
        unbound = make_scheme(name="global_one", turn_binding={})
        no_binding = make_scheme(name="none_at_all")
        del no_binding["turn_binding"]
        schemes = [bound, unbound, no_binding]
        assert {s["name"] for s in schemes_for_field(schemes, "conversation")} == {
            "turn_errors", "global_one", "none_at_all"}
        assert {s["name"] for s in schemes_for_field(schemes, "other")} == {
            "global_one", "none_at_all"}


class TestConfigValidation:
    def test_valid_scheme_passes(self):
        from potato.server_utils.config_module import validate_single_annotation_scheme
        validate_single_annotation_scheme(make_scheme(), "t")

    def test_unsupported_type_rejected(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_single_annotation_scheme)
        scheme = make_scheme(annotation_type="span")
        with pytest.raises(ConfigValidationError, match="turn_level is not supported"):
            validate_single_annotation_scheme(scheme, "t")

    def test_unknown_binding_key_rejected(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_single_annotation_scheme)
        scheme = make_scheme(turn_binding={"speekers": ["x"]})
        with pytest.raises(ConfigValidationError, match="unknown keys"):
            validate_single_annotation_scheme(scheme, "t")

    def test_bad_turn_range_rejected(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_single_annotation_scheme)
        scheme = make_scheme(turn_binding={"turn_range": [5, 1]})
        with pytest.raises(ConfigValidationError, match="turn_range"):
            validate_single_annotation_scheme(scheme, "t")

    def test_bad_placement_rejected(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_single_annotation_scheme)
        scheme = make_scheme(turn_binding={"placement": "sidebar"})
        with pytest.raises(ConfigValidationError, match="placement"):
            validate_single_annotation_scheme(scheme, "t")

    def test_all_supported_types_are_registered(self):
        from potato.server_utils.schemas.registry import schema_registry
        registered = set(schema_registry.get_supported_types())
        assert TURN_LEVEL_SUPPORTED_TYPES <= registered

    def test_binding_field_cross_check(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, _validate_turn_level_bindings)
        cfg = {"instance_display": {"fields": [{"key": "conversation", "type": "dialogue"}]}}
        _validate_turn_level_bindings(cfg, [make_scheme()])  # ok
        bad = make_scheme(turn_binding={"field": "nonexistent"})
        with pytest.raises(ConfigValidationError, match="does not match any"):
            _validate_turn_level_bindings(cfg, [bad])


class TestExportFlattening:
    def test_flatten_round_trip(self):
        raw = ('{"v":1,"schema_type":"multiselect","turns":'
               '{"t1":{"values":["hallucination"],"speaker":"Assistant"},'
               '"s9":{"value":3,"step_type":"action"}}}')
        rows = flatten_turn_annotation("turn_errors", raw)
        by_tid = {r["turn_id"]: r for r in rows}
        assert by_tid["t1"]["values"] == ["hallucination"]
        assert by_tid["t1"]["speaker"] == "Assistant"
        assert by_tid["s9"]["value"] == 3
        assert all(r["schema"] == "turn_errors" for r in rows)

    def test_flatten_rejects_garbage(self):
        assert flatten_turn_annotation("x", "not json") == []
        assert flatten_turn_annotation("x", '{"no_turns": true}') == []
        assert flatten_turn_annotation("x", None) == []

    def test_flatten_dict_input(self):
        rows = flatten_turn_annotation("x", {"v": 1, "turns": {"t0": {"value": "a"}}})
        assert rows == [{"schema": "x", "turn_id": "t0", "value": "a"}]


class TestDisplayIntegration:
    def test_dialogue_renders_slots(self):
        from potato.server_utils.displays.dialogue_display import DialogueDisplay
        out = DialogueDisplay().render(
            {"key": "conversation", "_turn_schemes": [make_scheme()]}, TURNS)
        assert out.count("turn-anno-slot") == 1  # only the Assistant turn
        assert "ta-chip" in out
        assert "annotation-input" not in out.split("turn-anno-slot")[1].split("</div>")[0]

    def test_dialogue_without_schemes_unchanged(self):
        from potato.server_utils.displays.dialogue_display import DialogueDisplay
        out = DialogueDisplay().render({"key": "conversation"}, TURNS)
        assert "turn-anno-slot" not in out

    def test_agent_trace_renders_slots(self):
        from potato.server_utils.displays.agent_trace_display import AgentTraceDisplay
        scheme = make_scheme(turn_binding={"step_types": ["action"]})
        out = AgentTraceDisplay().render({"key": "steps", "_turn_schemes": [scheme]}, TURNS)
        assert out.count("turn-anno-slot") == 1  # only the action step

    def test_normalize_passthrough_identity_keys(self):
        from potato.server_utils.displays._trace_normalize import normalize_steps
        steps = normalize_steps([
            {"speaker": "A", "text": "x", "agent_id": "planner", "turn_id": "u1"},
            {"thought": "th", "action": {"tool": "search"}, "turn_id": "shared"},
        ])
        assert steps[0]["agent_id"] == "planner"
        assert steps[0]["turn_id"] == "u1"
        # Format-2 expansion must NOT share explicit ids across expanded steps
        assert "turn_id" not in steps[1]
        assert "turn_id" not in steps[2]

    def test_instance_display_injects_turn_schemes(self):
        from potato.server_utils.instance_display import InstanceDisplayRenderer
        config = {
            "instance_display": {
                "fields": [{"key": "conversation", "type": "dialogue"}],
            },
            "annotation_schemes": [make_scheme()],
        }
        renderer = InstanceDisplayRenderer(config)
        html = renderer.render({"conversation": TURNS})
        assert "turn-anno-slot" in html
