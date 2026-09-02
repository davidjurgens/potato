"""
`qda_mode.memos.show_sidebar_by_default` has to reach the browser.

The key was parsed (qda_mode/config.py), defaulted to True, and reported by
/qda/status — and no client ever read it, so the notes sidebar started
collapsed in every QDA project regardless of the setting. Nothing failed,
because every test that touched the key asserted on the parser or on the
status endpoint, and both were working exactly as written.

So these tests assert on the response the sidebar itself reads. A key that is
parsed but not delivered is indistinguishable, from the annotator's seat, from
a key that does not exist.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)

_SCHEMES = [
    {
        "name": "sentiment",
        "annotation_type": "radio",
        "labels": ["Positive", "Negative"],
        "description": "Pick one.",
    }
]


def _login(server, email):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": email, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": email, "pass": "pw"})
    return s


def _serve(request, name, extra_config):
    """Boot a server with the given extra config; tear it down after the class."""
    test_dir = create_test_directory(name)
    data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hi"}])
    config_file = create_test_config(
        test_dir,
        _SCHEMES,
        data_files=[data_file],
        annotation_task_name=name,
        require_password=False,
        additional_config=extra_config,
    )
    server = FlaskTestServer(config_file=config_file, debug=False)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.cls.server = server
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


def _open_by_default(server, user):
    body = _login(server, user).get(
        f"{server.base_url}/api/memos", params={"instance_id": "1"}).json()
    return body.get("open_by_default")


class TestSidebarOpensWhenConfigured:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        yield from _serve(request, "memo_sidebar_on", {
            "qda_mode": {
                "enabled": True,
                "memos": {"enabled": True, "show_sidebar_by_default": True},
            }
        })

    def test_the_listing_tells_the_client_to_open(self):
        assert _open_by_default(self.server, "sidebar_alice") is True

    def test_the_memos_themselves_still_come_back(self):
        """The flag rides along with the listing; it must not displace it."""
        body = _login(self.server, "sidebar_alice2").get(
            f"{self.server.base_url}/api/memos", params={"instance_id": "1"}).json()
        assert body["memos"] == []


class TestSidebarStaysShutWhenTurnedOff:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        yield from _serve(request, "memo_sidebar_off", {
            "qda_mode": {
                "enabled": True,
                "memos": {"enabled": True, "show_sidebar_by_default": False},
            }
        })

    def test_an_explicit_false_is_honoured(self):
        assert _open_by_default(self.server, "sidebar_bob") is False


class TestNonQDAProjectsAreUnaffected:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        yield from _serve(request, "memo_sidebar_plain", {
            "annotation_ui": {"memos": True}
        })

    def test_memos_work_without_opening_the_sidebar(self):
        """The key belongs to QDA Mode; a plain project keeps today's behaviour."""
        s = _login(self.server, "sidebar_carol")
        body = s.get(f"{self.server.base_url}/api/memos",
                     params={"instance_id": "1"}).json()
        assert body["open_by_default"] is False
        assert body["memos"] == []
