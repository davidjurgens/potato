"""The idle-timeout check must accept the timestamps a session hands back.

Flask's cookie session returns a stored datetime timezone-aware (UTC); the
check subtracted it from a naive ``datetime.now()`` and raised TypeError, so
any signed-in request through a cookie session failed. Which tests saw it
depended on suite order.
"""

from datetime import datetime, timedelta, timezone

import flask
import pytest
from flask.json.tag import TaggedJSONSerializer

from potato import flask_server


def _valid_with(stamp):
    app = flask.Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context("/"):
        flask.session["created_at"] = stamp
        return flask_server.is_session_valid()


def test_a_stamp_read_back_from_a_cookie_session_is_accepted():
    s = TaggedJSONSerializer()
    stamp = s.loads(s.dumps({"d": datetime.now(timezone.utc)}))["d"]
    assert stamp.tzinfo is not None
    assert _valid_with(stamp) is True


def test_a_naive_stamp_from_an_older_server_is_accepted():
    assert _valid_with(datetime.now()) is True


def test_an_old_stamp_still_expires():
    old = datetime.now(timezone.utc) - flask_server.get_session_timeout() - timedelta(minutes=1)
    assert _valid_with(old) is False


class TestTheServedAppTimesSessionsOut:
    """The gate was decorated onto the import-time app, which create_app()
    discards, so `potato start` never timed a session out (potato-skill
    confirmed it live on 2.10.3: 75 s idle with a 1-minute timeout, still 200).
    Driven through the app create_app() returns."""

    @pytest.fixture(scope="class")
    def app(self):
        from potato.server_utils import config_module
        saved = dict(config_module.config)
        app = flask_server.create_app("examples/classification/single-choice/config.yaml")
        yield app
        from potato.item_state_management import clear_item_state_manager
        from potato.user_state_management import clear_user_state_manager
        clear_item_state_manager()
        clear_user_state_manager()
        config_module.config.clear()
        config_module.config.update(saved)

    @pytest.fixture(autouse=True)
    def debug_off(self, monkeypatch):
        from potato.server_utils import config_module
        monkeypatch.setitem(config_module.config, "debug", False)
        monkeypatch.setitem(config_module.config, "session_timeout_minutes", 1)

    def _get(self, app, idle):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "idle_user"
            sess["last_seen_at"] = datetime.now(timezone.utc) - idle
        response = client.get("/annotate")
        with client.session_transaction() as sess:
            return response, sess.get("username")

    def test_an_idle_session_is_cleared(self, app):
        response, user = self._get(app, timedelta(minutes=5))
        assert response.status_code == 302 and user is None

    def test_a_fresh_session_is_kept(self, app):
        _, user = self._get(app, timedelta(seconds=5))
        assert user == "idle_user"
