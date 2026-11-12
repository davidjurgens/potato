"""
`annotation_ui.visibility` sets the memo composer's starting visibility.

The server already defaulted a POST with no `visibility` to the configured
value, but the page's select always sends one and was hard-coded Private
first, so the setting only ever reached API callers. These tests read the
annotation page the annotator gets. The browser half (the note is posted
with that value, and the composer returns to it after an edit) is in
tests/selenium/test_memos_ui.py.
"""

import pytest
import requests
from bs4 import BeautifulSoup

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)

_SCHEMES = [{
    "name": "sentiment", "annotation_type": "radio",
    "labels": ["Positive", "Negative"], "description": "Pick one.",
}]


def _serve(request, name, annotation_ui):
    test_dir = create_test_directory(name)
    data_file = create_test_data_file(test_dir, [{"id": "1", "text": "hi"}])
    config_file = create_test_config(
        test_dir, _SCHEMES, data_files=[data_file],
        annotation_task_name=name, require_password=False,
        additional_config={"annotation_ui": annotation_ui})
    server = FlaskTestServer(config_file=config_file, debug=False)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    request.cls.server = server
    yield server
    server.stop()
    cleanup_test_directory(test_dir)


def _composer_select(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": user, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    page = s.get(f"{server.base_url}/annotate")
    assert page.status_code == 200
    select = BeautifulSoup(page.text, "html.parser").find(
        "select", id="memo-new-visibility")
    assert select is not None, "the memo composer was not rendered"
    selected = [o["value"] for o in select.find_all("option")
                if o.has_attr("selected")]
    return select, selected


class TestSharedDefault:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        yield from _serve(request, "memo_vis_shared",
                          {"memos": True, "visibility": "shared"})

    def test_the_composer_starts_shared(self):
        select, selected = _composer_select(self.server, "vis_shared_user")
        assert selected == ["shared"]
        assert select["data-default-visibility"] == "shared"


class TestPrivateIsTheDefault:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        yield from _serve(request, "memo_vis_default", {"memos": True})

    def test_the_composer_starts_private(self):
        select, selected = _composer_select(self.server, "vis_default_user")
        assert selected == ["private"]
        assert select["data-default-visibility"] == "private"
