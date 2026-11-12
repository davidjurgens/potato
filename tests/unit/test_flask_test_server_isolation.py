"""
Two test servers alive at once corrupt each other, and the harness now says so.

`FlaskTestServer` runs Flask in a thread inside the pytest process, so all
instances share `get_item_state_manager()`, `get_user_state_manager()` and the
config module. Whichever started last owns all three, and from then on every
running server answers with that project's data — on its own port, with its own
base_url, looking entirely healthy.

Found by writing a dashboard test that stood up an "annotators agree" project
and an "annotators disagree" project and compared the rendered reports. The two
pages were byte-identical, both showing the disagreeing numbers, while the JSON
each server had returned at its own setup time was correct. Nothing failed;
the test simply measured the same thing twice.

These tests pin the detection, not the sharing — the sharing is a property of
running in-process, and the fix for a test that trips it is to sequence its
servers.
"""

from __future__ import annotations

import warnings

import pytest

from tests.helpers.flask_test_setup import FlaskTestServer


class _Fake(FlaskTestServer):
    """A stand-in that registers and deregisters without binding a port.

    `_wsgi_server` stands for "actually serving": the registry prunes entries
    without one, because a test that drops its server without calling
    stop_server() would otherwise haunt every later start.
    """

    def __init__(self, port, serving=True):
        self.port = port
        self.temp_config_file = f"/tmp/fake-{port}.yaml"
        self._wsgi_server = object() if serving else None


@pytest.fixture(autouse=True)
def clean_registry():
    saved = list(FlaskTestServer._live)
    FlaskTestServer._live.clear()
    yield
    FlaskTestServer._live.clear()
    FlaskTestServer._live.extend(saved)


class TestOverlapDetection:

    def test_a_lone_server_is_silent(self):
        first = _Fake(9001)
        with warnings.catch_warnings():
            warnings.simplefilter("error")     # any warning fails the test
            first._warn_if_another_server_is_live()

    def test_a_second_live_server_is_reported(self):
        first = _Fake(9001)
        FlaskTestServer._live.append(first)
        second = _Fake(9002)

        with pytest.warns(RuntimeWarning, match="still serving"):
            second._warn_if_another_server_is_live()

    def test_the_warning_names_the_other_port(self):
        """A warning that does not say which server is a warning nobody acts on."""
        FlaskTestServer._live.append(_Fake(9001))
        with pytest.warns(RuntimeWarning) as caught:
            _Fake(9002)._warn_if_another_server_is_live()
        assert "9001" in str(caught[0].message)

    def test_strict_mode_turns_it_into_a_failure(self, monkeypatch):
        monkeypatch.setenv("POTATO_STRICT_TEST_SERVERS", "1")
        FlaskTestServer._live.append(_Fake(9001))
        with pytest.raises(RuntimeError, match="still serving"):
            _Fake(9002)._warn_if_another_server_is_live()

    def test_a_stopped_server_no_longer_counts(self):
        """
        Otherwise the warning fires on every later start and gets tuned out,
        which is worse than not having it.
        """
        first = _Fake(9001)
        FlaskTestServer._live.append(first)
        FlaskTestServer._live.remove(first)      # what stop_server() does

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _Fake(9002)._warn_if_another_server_is_live()

    def test_a_registered_but_no_longer_serving_entry_is_pruned(self):
        """
        The naive version counted every server ever started. Run against the
        real suite it reported 1039 overlaps, nearly all of them tests that
        simply never called stop_server() — noise that would have buried the
        handful of genuine ones.
        """
        dropped = _Fake(9001, serving=False)
        FlaskTestServer._live.append(dropped)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _Fake(9002)._warn_if_another_server_is_live()

        assert dropped not in FlaskTestServer._live
