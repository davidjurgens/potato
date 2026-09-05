"""Regressions for the audit-17 findings."""

import pytest
from flask import Flask

from potato.mcp_server.routes import mcp_bp
from potato.server_utils.agent_tokens import issue_token


# --------------------------------------------------------------- finding 1 --
# MCP-written annotations never reached the item-side accounting, so agreement
# and progress reported nothing on a fully annotated study.

class TestMcpWritesReachItemState:
    @pytest.fixture
    def surface(self, tmp_path):
        """An MCP surface over a two-item study with three annotators."""
        from potato.item_state_management import (
            clear_item_state_manager, init_item_state_manager)
        from potato.phase import UserPhase
        from potato.user_state_management import (
            clear_user_state_manager, init_user_state_manager)

        config = {
            "annotation_task_name": "Test",
            "task_dir": str(tmp_path),
            "output_annotation_dir": str(tmp_path / "out"),
            "item_properties": {"id_key": "id", "text_key": "text"},
            "num_annotators_per_item": 3,
            "annotation_schemes": [
                {"name": "decision", "annotation_type": "radio",
                 "description": "d", "labels": ["Accept", "Reject"]},
            ],
            "mcp": {"enabled": True,
                    "tools": ["submit_annotation"],
                    "audit_log": str(tmp_path / "audit.jsonl")},
        }

        clear_item_state_manager()
        clear_user_state_manager()
        ism = init_item_state_manager(config)
        ism.add_item("P01", {"id": "P01", "text": "first"})
        ism.add_item("P02", {"id": "P02", "text": "second"})

        usm = init_user_state_manager(config)
        for name in ("r1@lab.org", "r2@lab.org", "r3@lab.org"):
            usm.add_user(name)
            state = usm.get_user_state(name)
            # submit_annotation refuses outside the annotation phase (audit 15
            # finding 5), which is correct and not what this test is about.
            state.current_phase_and_page = (UserPhase.ANNOTATION, None)
            ism.assign_instances_to_user(state)

        app = Flask(__name__)
        app.config["mcp_task_config"] = config
        app.register_blueprint(mcp_bp)
        token = issue_token("test-agent", role="admin", config=config)

        yield app.test_client(), token, ism, usm
        clear_item_state_manager()
        clear_user_state_manager()

    @staticmethod
    def _submit(client, token, username, instance_id, value="Accept"):
        return client.post(
            "/api/mcp/tools/submit_annotation",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"username": username, "instance_id": instance_id,
                  "annotations": {"decision": value}},
        )

    def test_a_submission_registers_its_annotator_on_the_item(self, surface):
        client, token, ism, _usm = surface
        assert ism.get_annotators_for_item("P01") == set()

        response = self._submit(client, token, "r1@lab.org", "P01")
        assert response.status_code == 200, response.get_json()

        assert "r1@lab.org" in ism.get_annotators_for_item("P01"), (
            "the item side never saw the write, so agreement and progress "
            "reported nothing on a fully annotated study")

    def test_three_annotators_reach_the_per_item_cap(self, surface):
        """/admin/iaa reported n_annotators 0 on exactly this shape."""
        client, token, ism, _usm = surface
        for name in ("r1@lab.org", "r2@lab.org", "r3@lab.org"):
            assert self._submit(client, token, name, "P01").status_code == 200

        assert ism.get_annotators_for_item("P01") == {
            "r1@lab.org", "r2@lab.org", "r3@lab.org"}
        # And the item counts as saturated, which is what the cap and the
        # "below cap" figure on /admin/iaa are derived from.
        assert ism._item_is_saturated("P01")

    def test_the_same_annotator_twice_is_still_one_annotator(self, surface):
        client, token, ism, _usm = surface
        self._submit(client, token, "r1@lab.org", "P01", "Accept")
        self._submit(client, token, "r1@lab.org", "P01", "Reject")
        assert ism.get_annotators_for_item("P01") == {"r1@lab.org"}

    def test_the_answer_is_still_stored(self, surface):
        """Registering the annotator must not have displaced the write."""
        from potato.item_state_management import Label

        client, token, _ism, usm = surface
        self._submit(client, token, "r1@lab.org", "P01", "Accept")
        stored = usm.get_user_state("r1@lab.org").get_label_annotations("P01")
        assert stored.get(Label("decision", "Accept")) == "Accept"


# --------------------------------------------------------------- finding 2 --
# show_turn_numbers was documented, implemented on both sides, and inert --
# because it only took effect nested under `display_options`.

class TestDisplayOptionsAcceptTheFlatForm:
    TURNS = [{"speaker": "Customer", "text": "I want a refund."},
             {"speaker": "Agent", "text": "Let me check."}]

    def _render(self, field_config):
        from potato.server_utils.displays.dialogue_display import DialogueDisplay
        return DialogueDisplay().render(field_config, self.TURNS)

    def test_an_option_written_at_the_field_level_takes_effect(self):
        """`describe_display_type` lists these as the type's optional fields.

        Writing one there did nothing, silently.
        """
        html = self._render({"key": "turns", "type": "dialogue",
                             "show_turn_numbers": True})
        assert html.count("turn-number") == 2

    def test_the_nested_form_still_works(self):
        html = self._render({"key": "turns", "type": "dialogue",
                             "display_options": {"show_turn_numbers": True}})
        assert html.count("turn-number") == 2

    def test_display_options_wins_when_both_are_given(self):
        html = self._render({"key": "turns", "type": "dialogue",
                             "show_turn_numbers": True,
                             "display_options": {"show_turn_numbers": False}})
        assert html.count("turn-number") == 0

    def test_the_default_is_unchanged(self):
        assert self._render({"key": "turns", "type": "dialogue"}).count(
            "turn-number") == 0

    def test_a_structural_key_is_never_read_as_an_option(self):
        """`key`, `type`, `span_target` belong to the field, not the display."""
        from potato.server_utils.displays.base import BaseDisplay
        for name in ("key", "type", "span_target", "display_options"):
            assert name in BaseDisplay.STRUCTURAL_FIELD_KEYS

    def test_an_undeclared_top_level_key_is_still_ignored(self):
        from potato.server_utils.displays.dialogue_display import DialogueDisplay
        options = DialogueDisplay().get_display_options(
            {"key": "turns", "type": "dialogue", "not_an_option": "x"})
        assert "not_an_option" not in options

    def test_the_server_anchor_grows_the_numbers_with_the_dom(self):
        """If numbers reach the DOM the anchor must grow them in step.

        Otherwise every dialogue span offset shifts by the width of the
        numbering, silently.
        """
        from potato.server_utils.displays.base import reconstruct_dialogue_dom_text

        plain = reconstruct_dialogue_dom_text(self.TURNS)
        numbered = reconstruct_dialogue_dom_text(self.TURNS, show_turn_numbers=True)
        assert plain.startswith("Customer: ")
        assert numbered.startswith("[1] Customer: ")
        assert len(numbered) > len(plain)
