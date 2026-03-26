from unittest.mock import MagicMock

from flask import Flask, session

import potato.routes as routes
from potato.user_state_management import UserStateManager
from potato.phase import UserPhase


def _make_usm_config():
    return {
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


def _build_routes_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.add_url_rule("/", "home", lambda: "home")
    return app


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


def test_get_prev_user_phase_page_returns_previous_page_within_same_phase():
    usm = UserStateManager(_make_usm_config())
    usm.phase_type_to_name_to_page = {
        UserPhase.CONSENT: {"consent_page": "consent.html"},
        UserPhase.INSTRUCTIONS: {
            "instructions_a": "instructions_a.html",
            "instructions_b": "instructions_b.html",
        },
        UserPhase.POSTSTUDY: {"poststudy_page": "poststudy.html"},
    }

    user_state = MagicMock()
    user_state.get_current_phase_and_page.return_value = (UserPhase.INSTRUCTIONS, "instructions_b")
    usm.user_to_annotation_state["user1"] = user_state

    assert usm.get_prev_user_phase_page("user1") == (UserPhase.INSTRUCTIONS, "instructions_a")


def test_get_prev_user_phase_page_returns_previous_phase_boundary():
    usm = UserStateManager(_make_usm_config())
    usm.phase_type_to_name_to_page = {
        UserPhase.CONSENT: {"consent_page": "consent.html"},
        UserPhase.INSTRUCTIONS: {
            "instructions_a": "instructions_a.html",
            "instructions_b": "instructions_b.html",
        },
        UserPhase.POSTSTUDY: {"poststudy_page": "poststudy.html"},
    }

    user_state = MagicMock()
    user_state.get_current_phase_and_page.return_value = (UserPhase.ANNOTATION, None)
    usm.user_to_annotation_state["user1"] = user_state

    assert usm.get_prev_user_phase_page("user1") == (UserPhase.INSTRUCTIONS, "instructions_b")


def test_annotate_prev_instance_on_non_annotation_phase_retreats(monkeypatch):
    app = _build_routes_app()
    retreat_calls = []

    usm = MagicMock()
    usm.has_user.return_value = True
    usm.get_user_ids.return_value = ["user1"]
    usm.retreat_phase.side_effect = lambda username: retreat_calls.append(username)

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
    app = _build_routes_app()
    retreat_calls = []

    user_state = _StubAnnotationUserState()
    usm = MagicMock()
    usm.has_user.return_value = True
    usm.get_user_ids.return_value = ["user1"]
    usm.retreat_phase.side_effect = lambda username: retreat_calls.append(username)

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
