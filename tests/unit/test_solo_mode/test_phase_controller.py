"""
Unit tests for Solo Mode Phase Controller

Tests the phase state machine, transitions, and state persistence.
"""

import pytest
import tempfile
import os
from datetime import datetime

from potato.solo_mode.phase_controller import (
    SoloPhase,
    SoloPhaseController,
    PhaseTransition,
    PhaseState,
    PHASE_TRANSITIONS,
)


class TestSoloPhase:
    """Tests for SoloPhase enum."""

    def test_all_phases_defined(self):
        """Verify all expected phases exist."""
        expected_phases = [
            'SETUP', 'PROMPT_REVIEW', 'EDGE_CASE_SYNTHESIS',
            'EDGE_CASE_LABELING', 'PROMPT_VALIDATION', 'PARALLEL_ANNOTATION',
            'DISAGREEMENT_RESOLUTION', 'ACTIVE_ANNOTATION', 'PERIODIC_REVIEW',
            'AUTONOMOUS_LABELING', 'FINAL_VALIDATION', 'COMPLETED'
        ]
        for phase_name in expected_phases:
            assert hasattr(SoloPhase, phase_name)

    def test_from_str(self):
        """Test parsing phases from strings."""
        assert SoloPhase.from_str('setup') == SoloPhase.SETUP
        assert SoloPhase.from_str('SETUP') == SoloPhase.SETUP
        assert SoloPhase.from_str('prompt-review') == SoloPhase.PROMPT_REVIEW
        assert SoloPhase.from_str('PROMPT_REVIEW') == SoloPhase.PROMPT_REVIEW

    def test_from_str_invalid(self):
        """Test that invalid strings raise KeyError."""
        with pytest.raises(KeyError):
            SoloPhase.from_str('invalid_phase')

    def test_to_str(self):
        """Test converting phases to strings."""
        assert SoloPhase.SETUP.to_str() == 'setup'
        assert SoloPhase.PROMPT_REVIEW.to_str() == 'prompt-review'
        assert SoloPhase.EDGE_CASE_SYNTHESIS.to_str() == 'edge-case-synthesis'

    def test_roundtrip(self):
        """Test that from_str and to_str are inverses."""
        for phase in SoloPhase:
            assert SoloPhase.from_str(phase.to_str()) == phase


class TestPhaseTransitions:
    """Tests for phase transition rules."""

    def test_setup_transitions(self):
        """SETUP should only transition to PROMPT_REVIEW."""
        allowed = PHASE_TRANSITIONS[SoloPhase.SETUP]
        assert allowed == {SoloPhase.PROMPT_REVIEW}

    def test_prompt_review_transitions(self):
        """PROMPT_REVIEW can go to EDGE_CASE_SYNTHESIS or PARALLEL_ANNOTATION."""
        allowed = PHASE_TRANSITIONS[SoloPhase.PROMPT_REVIEW]
        assert SoloPhase.EDGE_CASE_SYNTHESIS in allowed
        assert SoloPhase.PARALLEL_ANNOTATION in allowed

    def test_completed_is_terminal(self):
        """COMPLETED should be a terminal state with no transitions."""
        allowed = PHASE_TRANSITIONS[SoloPhase.COMPLETED]
        assert allowed == set()

    def test_all_phases_have_transition_rules(self):
        """Every phase should have an entry in PHASE_TRANSITIONS."""
        for phase in SoloPhase:
            assert phase in PHASE_TRANSITIONS

    def test_bidirectional_annotation_disagreement(self):
        """PARALLEL_ANNOTATION and DISAGREEMENT_RESOLUTION should be bidirectional."""
        assert SoloPhase.DISAGREEMENT_RESOLUTION in PHASE_TRANSITIONS[SoloPhase.PARALLEL_ANNOTATION]
        assert SoloPhase.PARALLEL_ANNOTATION in PHASE_TRANSITIONS[SoloPhase.DISAGREEMENT_RESOLUTION]


class TestPhaseTransitionDataclass:
    """Tests for PhaseTransition dataclass."""

    def test_to_dict(self):
        """Test serialization."""
        transition = PhaseTransition(
            from_phase=SoloPhase.SETUP,
            to_phase=SoloPhase.PROMPT_REVIEW,
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            reason="User submitted task description",
        )
        d = transition.to_dict()
        assert d['from_phase'] == 'setup'
        assert d['to_phase'] == 'prompt-review'
        assert d['reason'] == "User submitted task description"
        assert '2024-01-01' in d['timestamp']

    def test_from_dict(self):
        """Test deserialization."""
        data = {
            'from_phase': 'setup',
            'to_phase': 'prompt-review',
            'timestamp': '2024-01-01T12:00:00',
            'reason': 'test',
            'metadata': {'key': 'value'},
        }
        transition = PhaseTransition.from_dict(data)
        assert transition.from_phase == SoloPhase.SETUP
        assert transition.to_phase == SoloPhase.PROMPT_REVIEW
        assert transition.reason == 'test'
        assert transition.metadata == {'key': 'value'}


class TestSoloPhaseController:
    """Tests for SoloPhaseController."""

    @pytest.fixture
    def controller(self):
        """Create a controller without state persistence."""
        return SoloPhaseController(state_dir=None)

    @pytest.fixture
    def controller_with_persistence(self, tmp_path):
        """Create a controller with state persistence."""
        return SoloPhaseController(state_dir=str(tmp_path))

    def test_initial_state(self, controller):
        """Controller should start in SETUP phase."""
        assert controller.get_current_phase() == SoloPhase.SETUP
        assert controller.is_phase(SoloPhase.SETUP)
        assert not controller.is_completed()

    def test_valid_transition(self, controller):
        """Valid transitions should succeed."""
        assert controller.can_transition_to(SoloPhase.PROMPT_REVIEW)
        result = controller.transition_to(SoloPhase.PROMPT_REVIEW, reason="test")
        assert result is True
        assert controller.get_current_phase() == SoloPhase.PROMPT_REVIEW

    def test_invalid_transition_raises(self, controller):
        """Invalid transitions should raise ValueError."""
        # SETUP cannot directly go to COMPLETED
        assert not controller.can_transition_to(SoloPhase.COMPLETED)
        with pytest.raises(ValueError) as exc_info:
            controller.transition_to(SoloPhase.COMPLETED)
        assert "Invalid phase transition" in str(exc_info.value)

    def test_force_transition(self, controller):
        """Force flag should allow invalid transitions."""
        result = controller.transition_to(SoloPhase.COMPLETED, force=True)
        assert result is True
        assert controller.get_current_phase() == SoloPhase.COMPLETED

    def test_transition_history(self, controller):
        """Transitions should be recorded in history."""
        controller.transition_to(SoloPhase.PROMPT_REVIEW, reason="first")
        controller.transition_to(SoloPhase.PARALLEL_ANNOTATION, reason="second")

        history = controller.get_transition_history()
        assert len(history) == 2
        assert history[0].from_phase == SoloPhase.SETUP
        assert history[0].to_phase == SoloPhase.PROMPT_REVIEW
        assert history[0].reason == "first"
        assert history[1].reason == "second"

    def test_advance_to_next_phase(self, controller):
        """advance_to_next_phase should select the primary transition."""
        result = controller.advance_to_next_phase(reason="auto-advance")
        assert result is True
        assert controller.get_current_phase() == SoloPhase.PROMPT_REVIEW

    def test_advance_from_terminal_fails(self, controller):
        """Cannot advance from terminal COMPLETED state."""
        controller.transition_to(SoloPhase.COMPLETED, force=True)
        result = controller.advance_to_next_phase()
        assert result is False
        assert controller.is_completed()

    def test_get_allowed_transitions(self, controller):
        """get_allowed_transitions should return valid next phases."""
        allowed = controller.get_allowed_transitions()
        assert SoloPhase.PROMPT_REVIEW in allowed
        assert SoloPhase.COMPLETED not in allowed

    def test_phase_data(self, controller):
        """Phase data should be storable and retrievable."""
        controller.set_phase_data('test_key', {'value': 123})
        assert controller.get_phase_data('test_key') == {'value': 123}
        assert controller.get_phase_data('missing_key') is None
        assert controller.get_phase_data('missing_key', 'default') == 'default'

    def test_get_status(self, controller):
        """get_status should return comprehensive status info."""
        status = controller.get_status()
        assert status['current_phase'] == 'setup'
        assert 'prompt-review' in status['allowed_transitions']
        assert status['is_completed'] is False
        assert status['transition_count'] == 0

    def test_reset(self, controller):
        """reset should return to SETUP state."""
        controller.transition_to(SoloPhase.PROMPT_REVIEW)
        controller.set_phase_data('key', 'value')
        controller.reset()

        assert controller.get_current_phase() == SoloPhase.SETUP
        assert len(controller.get_transition_history()) == 0
        assert controller.get_phase_data('key') is None

    def test_timestamps(self, controller):
        """Timestamps should be set on transitions."""
        controller.transition_to(SoloPhase.PROMPT_REVIEW)
        assert controller.state.started_at is not None

        controller.transition_to(SoloPhase.COMPLETED, force=True)
        assert controller.state.completed_at is not None

    def test_time_in_phase(self, controller):
        """get_time_in_phase should return elapsed time."""
        controller.transition_to(SoloPhase.PROMPT_REVIEW)
        import time
        time.sleep(0.01)  # Small delay

        time_in_phase = controller.get_time_in_phase()
        assert time_in_phase is not None
        assert time_in_phase >= 0.01

    def test_persistence_save_load(self, controller_with_persistence, tmp_path):
        """State should be persisted and loadable."""
        controller = controller_with_persistence

        # Make some changes
        controller.transition_to(SoloPhase.PROMPT_REVIEW, reason="test")
        controller.set_phase_data('key', 'value')

        # Create new controller and load state
        new_controller = SoloPhaseController(state_dir=str(tmp_path))
        loaded = new_controller.load_state()

        assert loaded is True
        assert new_controller.get_current_phase() == SoloPhase.PROMPT_REVIEW
        assert new_controller.get_phase_data('key') == 'value'
        assert len(new_controller.get_transition_history()) == 1

    def test_persistence_no_file(self, tmp_path):
        """load_state should return False when no state file exists."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        controller = SoloPhaseController(state_dir=str(empty_dir))
        loaded = controller.load_state()
        assert loaded is False


class TestPhaseState:
    """Tests for PhaseState dataclass."""

    def test_to_dict(self):
        """Test serialization."""
        state = PhaseState(
            current_phase=SoloPhase.PROMPT_REVIEW,
            started_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        d = state.to_dict()
        assert d['current_phase'] == 'prompt-review'
        assert d['started_at'] is not None

    def test_from_dict(self):
        """Test deserialization."""
        data = {
            'current_phase': 'prompt-review',
            'transition_history': [],
            'phase_data': {'key': 'value'},
            'started_at': '2024-01-01T12:00:00',
            'completed_at': None,
        }
        state = PhaseState.from_dict(data)
        assert state.current_phase == SoloPhase.PROMPT_REVIEW
        assert state.phase_data == {'key': 'value'}
        assert state.started_at is not None
        assert state.completed_at is None
