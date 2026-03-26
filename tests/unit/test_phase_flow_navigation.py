from unittest.mock import MagicMock

from flask import Flask, session

import potato.routes as routes
from potato.user_state_management import UserStateManager
from potato.phase import UserPhase


def _make_usm_config(**overrides):
    cfg = {
        "output_annotation_dir": ".",
        "annotation_task_name": "Phase Flow Test",
        "annotation_schemes": [],
        "phases": {
            "order": ["consent", "instructions", "annotation", "poststudy"],
            "consent": {"type": "consent"},
            "instructions": {"type": "instructions"},
            "poststudy": {"type": "poststudy"},
        },
    }
    cfg.update(overrides)
    return cfg


def _build_routes_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.add_url_rule("/", "home", lambda: "home")
    return app


def _make_usm_with_phases(**config_overrides):
    """Create a USM with standard phase page mappings."""
    usm = UserStateManager(_make_usm_config(**config_overrides))
    usm.phase_type_to_name_to_page = {
        UserPhase.CONSENT: {"consent_page": "consent.html"},
        UserPhase.INSTRUCTIONS: {
            "instructions_a": "instructions_a.html",
            "instructions_b": "instructions_b.html",
        },
        UserPhase.POSTSTUDY: {"poststudy_page": "poststudy.html"},
    }
    return usm


class _StubPhaseUserState:
    def __init__(self, phase):
        self._phase = phase

    def get_phase(self):
        return self._phase


class _StubAnnotationUserState:
    current_instance_index = 0

    def get_phase(self):
        return UserPhase.ANNOTATION

    def has_assignments(self):
        return True

    def has_remaining_assignments(self):
        return True

    def get_current_instance_index(self):
        return self.current_instance_index


# ---- get_prev_user_phase_page tests (pure query, no config gating) ----

def test_get_prev_user_phase_page_returns_previous_page_within_same_phase():
    usm = _make_usm_with_phases()
    user_state = MagicMock()
    user_state.get_current_phase_and_page.return_value = (UserPhase.INSTRUCTIONS, "instructions_b")
    usm.user_to_annotation_state["user1"] = user_state

    assert usm.get_prev_user_phase_page("user1") == (UserPhase.INSTRUCTIONS, "instructions_a")


def test_get_prev_user_phase_page_returns_previous_phase_boundary():
    usm = _make_usm_with_phases()
    user_state = MagicMock()
    user_state.get_current_phase_and_page.return_value = (UserPhase.ANNOTATION, None)
    usm.user_to_annotation_state["user1"] = user_state

    assert usm.get_prev_user_phase_page("user1") == (UserPhase.INSTRUCTIONS, "instructions_b")


# ---- retreat_phase tests (config-gated) ----

def test_retreat_phase_within_phase_always_allowed():
    """Within-phase backward navigation works regardless of config."""
    usm = _make_usm_with_phases()  # default: allow_phase_back_navigation not set
    user_state = MagicMock()
    user_state.get_current_phase_and_page.return_value = (UserPhase.INSTRUCTIONS, "instructions_b")
    usm.user_to_annotation_state["user1"] = user_state

    result = usm.retreat_phase("user1")

    assert result is True
    user_state.advance_to_phase.assert_called_once_with(UserPhase.INSTRUCTIONS, "instructions_a")


def test_retreat_phase_cross_phase_blocked_by_default():
    """Cross-phase backward navigation is blocked when config flag is not set."""
    usm = _make_usm_with_phases()
    user_state = MagicMock()
    user_state.get_current_phase_and_page.return_value = (UserPhase.ANNOTATION, None)
    usm.user_to_annotation_state["user1"] = user_state

    result = usm.retreat_phase("user1")

    assert result is False
    user_state.advance_to_phase.assert_not_called()


def test_retreat_phase_cross_phase_allowed_when_enabled():
    """Cross-phase backward navigation works when allow_phase_back_navigation is True."""
    usm = _make_usm_with_phases(allow_phase_back_navigation=True)
    user_state = MagicMock()
    user_state.get_current_phase_and_page.return_value = (UserPhase.ANNOTATION, None)
    usm.user_to_annotation_state["user1"] = user_state

    result = usm.retreat_phase("user1")

    assert result is True
    user_state.advance_to_phase.assert_called_once_with(UserPhase.INSTRUCTIONS, "instructions_b")


def test_retreat_phase_at_first_phase_first_page_returns_false():
    """Cannot retreat before the first configured phase."""
    usm = _make_usm_with_phases(allow_phase_back_navigation=True)
    user_state = MagicMock()
    user_state.get_current_phase_and_page.return_value = (UserPhase.CONSENT, "consent_page")
    usm.user_to_annotation_state["user1"] = user_state

    # get_prev_user_phase_page returns (CONSENT, "consent_page") — same place
    result = usm.retreat_phase("user1")

    assert result is False
    user_state.advance_to_phase.assert_not_called()


# ---- Route-level tests ----

def test_annotate_prev_instance_on_non_annotation_phase_retreats(monkeypatch):
    """Leaked prev_instance from non-annotation phase calls retreat_phase."""
    app = _build_routes_app()
    retreat_calls = []

    usm = MagicMock()
    usm.has_user.return_value = True
    usm.get_user_ids.return_value = ["user1"]
    usm.retreat_phase.side_effect = lambda username: retreat_calls.append(username) or True

    monkeypatch.setattr(routes, "app", app, raising=False)
    monkeypatch.setattr(routes, "config", {"debug": False}, raising=False)
    monkeypatch.setattr(routes, "get_user_state_manager", lambda: usm)
    monkeypatch.setattr(routes, "get_user_state", lambda username: _StubPhaseUserState(UserPhase.INSTRUCTIONS))

    with app.test_request_context("/annotate", method="POST", json={"action": "prev_instance"}):
        session["username"] = "user1"
        response = routes.annotate()

    assert response.status_code == 302
    assert response.location.endswith("/")
    assert retreat_calls == ["user1"]


def test_annotate_prev_instance_from_first_annotation_item_retreats(monkeypatch):
    """Back on first annotation item calls retreat_phase."""
    app = _build_routes_app()
    retreat_calls = []

    user_state = _StubAnnotationUserState()
    usm = MagicMock()
    usm.has_user.return_value = True
    usm.get_user_ids.return_value = ["user1"]
    usm.retreat_phase.side_effect = lambda username: retreat_calls.append(username) or True

    monkeypatch.setattr(routes, "app", app, raising=False)
    monkeypatch.setattr(routes, "config", {"debug": False}, raising=False)
    monkeypatch.setattr(routes, "get_user_state_manager", lambda: usm)
    monkeypatch.setattr(routes, "get_user_state", lambda username: user_state)
    monkeypatch.setattr(routes, "move_to_prev_instance", lambda username: False)
    monkeypatch.setattr(routes, "_inject_quality_control_item_if_needed", lambda username, state: None)
    monkeypatch.setattr(routes, "get_ai_cache_manager", lambda: None)

    with app.test_request_context("/annotate", method="POST", json={"action": "prev_instance"}):
        session["username"] = "user1"
        response = routes.annotate()

    assert response.status_code == 302
    assert response.location.endswith("/")
    assert retreat_calls == ["user1"]
