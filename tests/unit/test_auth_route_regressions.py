import pytest

import potato.authentication as auth_module
from potato.authentication import UserAuthenticator
from potato.server_utils.config_module import config
from potato.user_state_management import (
    clear_user_state_manager,
    get_user_state_manager,
    init_user_state_manager,
)


@pytest.fixture(autouse=True)
def reset_auth_state():
    auth_module.USER_AUTHENTICATOR_SINGLETON = None
    clear_user_state_manager()
    init_user_state_manager(config)
    yield
    auth_module.USER_AUTHENTICATOR_SINGLETON = None


def _init_authenticator(allow_all_users=True):
    authenticator = UserAuthenticator.init_from_config(config)
    authenticator.require_password = True
    authenticator.allow_all_users = allow_all_users
    return authenticator


def test_register_then_login_succeeds_for_existing_user(client):
    authenticator = _init_authenticator(allow_all_users=True)

    register_response = client.post(
        "/register",
        data={"email": "returning_user", "pass": "secret123"},
        follow_redirects=False,
    )

    assert register_response.status_code == 302
    assert authenticator.auth_backend.is_valid_username("returning_user")
    assert get_user_state_manager().has_user("returning_user")

    with client.session_transaction() as session:
        session.clear()

    login_response = client.post(
        "/auth",
        data={"email": "returning_user", "pass": "secret123"},
        follow_redirects=False,
    )

    assert login_response.status_code == 302
    assert "/annotate" in login_response.headers["Location"]

    with client.session_transaction() as session:
        assert session["username"] == "returning_user"


def test_duplicate_registration_does_not_create_session(client):
    _init_authenticator(allow_all_users=True)

    first_response = client.post(
        "/register",
        data={"email": "repeat_user", "pass": "secret123"},
        follow_redirects=False,
    )
    assert first_response.status_code == 302

    with client.session_transaction() as session:
        session.clear()

    duplicate_response = client.post(
        "/register",
        data={"email": "repeat_user", "pass": "secret123"},
        follow_redirects=True,
    )

    assert duplicate_response.status_code == 200
    assert b"already exists" in duplicate_response.data.lower()

    with client.session_transaction() as session:
        assert "username" not in session


def test_unauthorized_registration_does_not_create_auth_or_user_state(client):
    authenticator = _init_authenticator(allow_all_users=False)

    response = client.post(
        "/register",
        data={"email": "blocked_user", "pass": "secret123"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"not authorized" in response.data.lower()
    assert not authenticator.auth_backend.is_valid_username("blocked_user")
    assert not get_user_state_manager().has_user("blocked_user")

    with client.session_transaction() as session:
        assert "username" not in session
