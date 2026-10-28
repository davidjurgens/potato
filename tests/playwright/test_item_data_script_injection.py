"""
Item data cannot run script on the annotation page.

Every str/int/float/bool/list field of an item is copied into
``<script id="instance_data" type="application/json">``. That JSON was
written with plain json.dumps, so a field containing a closing script tag
ended the element and the rest ran as markup for every annotator. The
displayed text goes through the HTML sanitizer; the JSON copy did not.
"""

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory)

pytestmark = pytest.mark.playwright

PAYLOADS = {
    "text": "Hello </script><script>window.__pwned='text'</script> world",
    "note": "</script><img src=x onerror=\"window.__pwned='img'\">",
    "upper": "</SCRIPT ><svg onload=\"window.__pwned='svg'\"></svg>",
    "comment": "<!--<script>window.__pwned='comment'</script>",
    "tags": ["</script><script>window.__pwned='list'</script>", "a & b"],
}

SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
            "description": "Sentiment", "labels": ["pos", "neg"]}]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("item_data_script_injection")
    data_file = create_test_data_file(test_dir, [
        dict(id="1", **PAYLOADS),
        {"id": "2", "text": "second"},
    ])
    config_file = create_test_config(test_dir, SCHEMES, data_files=[data_file])
    srv = FlaskTestServer(port=find_free_port(), config_file=config_file)
    if not srv.start():
        pytest.fail("Failed to start server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def test_item_fields_do_not_execute_and_round_trip(server, page):
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"email": "xss", "pass": "pw"})
    req.post(f"{server.base_url}/auth", form={"email": "xss", "pass": "pw"})
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_selector("#instance_data", state="attached")
    page.wait_for_timeout(500)          # let any injected onerror/onload fire

    assert page.evaluate("typeof window.__pwned") == "undefined"
    assert dialogs == []
    # Nothing from the payloads became an element.
    assert page.locator("img[src='x']").count() == 0
    assert page.locator("svg[onload]").count() == 0

    # The page still receives each field unchanged.
    data = page.evaluate(
        "JSON.parse(document.getElementById('instance_data').textContent)")
    for key, value in PAYLOADS.items():
        assert data[key] == value
    instance = page.evaluate(
        "JSON.parse(document.getElementById('instance').textContent)")
    assert "window.__pwned" in instance["text"]
