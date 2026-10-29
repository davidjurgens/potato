"""
A randomized pairwise page must not carry the item in data order.

The candidates were shuffled for the schema widget, but the page's
``[data-instance-json]`` record, and fields such as the model behind each
response, still came from the unshuffled item. Anyone could read the source
order, and the model names, off the page. ``item_properties.private_keys``
keeps chosen fields out of everything the browser receives.
"""

import json
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory)

SECRET = "secret-model-zz9"
RESPONSES = ["first response", "second response"]
USERS = [f"rater{i}" for i in range(8)]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("pairwise_page_blindness")
    data_file = create_test_data_file(test_dir, [
        {"id": "p1", "text": "Which reply is better?", "responses": RESPONSES,
         "models": [SECRET, "other-model"]},
    ])
    config_file = create_test_config(
        test_dir,
        [{"annotation_type": "pairwise", "name": "pref", "description": "Better?",
          "items_key": "responses", "randomize_order": True}],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text",
                         "private_keys": ["models"]},
    )
    srv = FlaskTestServer(port=9873, config_file=config_file)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def _session(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": user, "pass": "pw"})
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    return s


def _page_record(html):
    m = re.search(r"data-instance-json='([^']*)'", html)
    assert m, "no [data-instance-json] on the page"
    import html as _html
    return json.loads(_html.unescape(m.group(1)))


def test_page_and_apis_agree_on_the_shown_order(server):
    shown = set()
    for user in USERS:
        s = _session(server, user)
        page = s.get(f"{server.base_url}/annotate").text
        assert SECRET not in page, "a private field reached the page"

        record = _page_record(page)
        api = s.get(f"{server.base_url}/api/instance_data").json()
        current = s.get(f"{server.base_url}/api/current_instance").json()["data"]
        for data in (api, current):
            assert "models" not in data
            assert SECRET not in json.dumps(data)
        # One order for this annotator, wherever the page reads it from.
        assert record["responses"] == api["responses"] == current["responses"]
        assert sorted(record["responses"]) == sorted(RESPONSES)
        shown.add(tuple(record["responses"]))
    # Eight annotators all seeing data order would mean nothing is shuffled.
    assert shown == {tuple(RESPONSES), tuple(reversed(RESPONSES))}


@pytest.fixture(scope="module")
def multi_server():
    """Three pairwise schemes comparing the same candidates."""
    test_dir = create_test_directory("pairwise_shared_order")
    data_file = create_test_data_file(test_dir, [
        {"id": f"m{i}", "text": "Which reply is better?",
         "responses": [f"first {i}", f"second {i}"]} for i in range(4)])
    common = {"items_key": "responses", "randomize_order": True}
    config_file = create_test_config(
        test_dir,
        [dict(common, annotation_type="pairwise", name="pref", description="Better?",
              allow_tie=True),
         dict(common, annotation_type="pairwise", name="sc", description="How much?",
              mode="scale"),
         dict(common, annotation_type="pairwise", name="md", description="Per aspect",
              mode="multi_dimension",
              dimensions=[{"name": "accuracy", "description": "Accurate?"}])],
        data_files=[data_file],
    )
    srv = FlaskTestServer(port=9874, config_file=config_file)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def test_schemes_on_one_field_share_one_order(multi_server):
    """Each scheme permuted the list again, so the page showed the parity of
    three swaps while each scheme recorded only its own."""
    from potato.user_state_management import get_user_state_manager

    for user in USERS[:6]:
        s = _session(multi_server, user)
        for _ in range(4):
            record = _page_record(s.get(f"{multi_server.base_url}/annotate").text)
            iid = record["id"]
            orders = get_user_state_manager().get_user_state(user).get_presentation_order(iid)
            assert orders["pref"] == orders["sc"] == orders["md"], orders
            shown = [f"first {iid[1:]}", f"second {iid[1:]}"]
            assert record["responses"] == [shown[i] for i in orders["pref"]]
            s.post(f"{multi_server.base_url}/updateinstance",
                   json={"instance_id": iid, "annotations": {"pref:::selection": "A"},
                         "span_annotations": []})
            s.post(f"{multi_server.base_url}/annotate", json={"action": "next_instance"})
