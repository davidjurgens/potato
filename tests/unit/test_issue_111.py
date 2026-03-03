"""
Tests for GitHub issue #111: All-Phases Navigation Loop + Schema Config Error

Bug 1: Navigation loop when multiple config entries map to the same UserPhase
        (e.g., general_instructions and specific_instructions both -> INSTRUCTIONS).
Bug 2: has_free_response: true (boolean) causes AttributeError because code
        calls .get() on a bool instead of a dict.
"""

import threading
from collections import OrderedDict, defaultdict

from potato.server_utils.schemas.radio import generate_radio_layout
from potato.server_utils.schemas.multiselect import generate_multiselect_layout
from potato.phase import UserPhase
from potato.user_state_management import UserStateManager, InMemoryUserState


def _make_user_state_manager(config):
    """Create a minimal UserStateManager without calling __init__ (avoids full server setup)."""
    mgr = UserStateManager.__new__(UserStateManager)
    mgr.config = config
    mgr.user_to_annotation_state = {}
    mgr.task_assignment = {}
    mgr.prolific_study = None
    mgr.max_annotations_per_user = -1
    mgr.use_database = False
    mgr.db_manager = None
    mgr._state_lock = threading.RLock()
    mgr.phase_type_to_name_to_page = defaultdict(OrderedDict)
    return mgr


class TestFreeResponseBoolean:
    """Bug 2: has_free_response as boolean should not crash."""

    def _radio_scheme(self, has_free_response):
        return {
            "annotation_type": "radio",
            "annotation_id": 0,
            "name": "sentiment",
            "description": "Rate sentiment",
            "labels": ["positive", "negative"],
            "has_free_response": has_free_response,
        }

    def _multiselect_scheme(self, has_free_response):
        return {
            "annotation_type": "multiselect",
            "annotation_id": 0,
            "name": "topics",
            "description": "Select topics",
            "labels": ["politics", "sports"],
            "has_free_response": has_free_response,
        }

    def test_radio_has_free_response_boolean_true(self):
        """has_free_response: true (boolean) should produce free response HTML without crashing."""
        scheme = self._radio_scheme(True)
        html, keybindings = generate_radio_layout(scheme)
        assert "free_response" in html
        assert "Other" in html  # Default instruction text

    def test_radio_has_free_response_dict(self):
        """has_free_response as dict should use the custom instruction text."""
        scheme = self._radio_scheme({"instruction": "Custom label"})
        html, keybindings = generate_radio_layout(scheme)
        assert "free_response" in html
        assert "Custom label" in html

    def test_multiselect_has_free_response_boolean_true(self):
        """has_free_response: true (boolean) should produce free response HTML without crashing."""
        scheme = self._multiselect_scheme(True)
        html, keybindings = generate_multiselect_layout(scheme)
        assert "free_response" in html
        assert "Other" in html

    def test_multiselect_has_free_response_dict(self):
        """has_free_response as dict should use the custom instruction text."""
        scheme = self._multiselect_scheme({"instruction": "Custom label"})
        html, keybindings = generate_multiselect_layout(scheme)
        assert "free_response" in html
        assert "Custom label" in html


class TestPhaseDeduplication:
    """Bug 1: Duplicate phase types in config_phases cause navigation loop."""

    def test_phase_transition_with_duplicate_phase_types(self):
        """When two config entries map to the same UserPhase (e.g., two INSTRUCTIONS pages),
        config_phases should deduplicate so that get_next_user_phase_page advances correctly."""
        config = {
            "output_annotation_dir": "/tmp/test_issue_111",
            "phases": {
                "order": [
                    "general_instructions",
                    "specific_instructions",
                    "training",
                    "annotation",
                ],
                "general_instructions": {
                    "type": "instructions",
                    "file": "general.html",
                },
                "specific_instructions": {
                    "type": "instructions",
                    "file": "specific.html",
                },
                "training": {
                    "type": "training",
                    "file": "training.html",
                },
            },
        }

        mgr = _make_user_state_manager(config)
        mgr.phase_type_to_name_to_page[UserPhase.INSTRUCTIONS]["general_instructions"] = "general.html"
        mgr.phase_type_to_name_to_page[UserPhase.INSTRUCTIONS]["specific_instructions"] = "specific.html"
        mgr.phase_type_to_name_to_page[UserPhase.TRAINING]["training"] = "training.html"

        # Create a user on the last INSTRUCTIONS page
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.INSTRUCTIONS, "specific_instructions")
        mgr.user_to_annotation_state = {"test_user": user}

        # Advance from last instructions page — should go to TRAINING, not loop back
        next_phase, next_page = mgr.get_next_user_phase_page("test_user")
        assert next_phase == UserPhase.TRAINING, (
            f"Expected TRAINING after last INSTRUCTIONS page, got {next_phase}"
        )
        assert next_page == "training"

        # Now advance from TRAINING — should go to ANNOTATION
        user.current_phase_and_page = (UserPhase.TRAINING, "training")
        next_phase, next_page = mgr.get_next_user_phase_page("test_user")
        assert next_phase == UserPhase.ANNOTATION, (
            f"Expected ANNOTATION after TRAINING, got {next_phase}"
        )

    def test_multi_page_instructions_advances_within_phase(self):
        """Within a multi-page phase, pages should advance one at a time before
        moving to the next phase type."""
        config = {
            "output_annotation_dir": "/tmp/test_issue_111",
            "phases": {
                "order": [
                    "general_instructions",
                    "specific_instructions",
                    "annotation",
                ],
                "general_instructions": {
                    "type": "instructions",
                    "file": "general.html",
                },
                "specific_instructions": {
                    "type": "instructions",
                    "file": "specific.html",
                },
            },
        }

        mgr = _make_user_state_manager(config)
        mgr.phase_type_to_name_to_page[UserPhase.INSTRUCTIONS]["general_instructions"] = "general.html"
        mgr.phase_type_to_name_to_page[UserPhase.INSTRUCTIONS]["specific_instructions"] = "specific.html"

        # Start on first instructions page
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.INSTRUCTIONS, "general_instructions")
        mgr.user_to_annotation_state = {"test_user": user}

        # Should advance to second instructions page (not skip to annotation)
        next_phase, next_page = mgr.get_next_user_phase_page("test_user")
        assert next_phase == UserPhase.INSTRUCTIONS
        assert next_page == "specific_instructions"
