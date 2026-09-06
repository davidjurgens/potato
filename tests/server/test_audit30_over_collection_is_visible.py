"""
An item with more annotations than its cap must be countable afterwards.

The assignment relaxation hands out an item that another annotator holds
but has not submitted, so on an over-subscribed pool two annotators can
both be assigned an item neither has answered yet -- and nothing
re-checks the cap at submission. The item ends up with two annotations
under a cap of one.

That is the relaxation working as designed, and the study is better for
it (the alternative is sending someone away empty-handed). What was
wrong is that it left no trace: no warning, no count, nothing in the
admin overview. An agreement number computed over an over-collected item
is quietly not the design that was configured, and there was no way to
know which items those were.

Driven through real submissions, because the count is only interesting
if it reflects annotations that were actually recorded.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory, create_test_data_file, create_test_config,
    cleanup_test_directory)

SCHEMES = [{"name": "verdict", "description": "Verdict?",
            "annotation_type": "radio", "labels": ["yes", "no"]}]

ADMIN_KEY = "over-collection-admin-key"


def _login(server, who):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"email": who, "pass": "p"})
    s.post(f"{server.base_url}/auth", data={"email": who, "pass": "p"})
    return s


class TestOverCollection:
    @pytest.fixture
    def server(self):
        test_dir = create_test_directory("over_collected")
        # Two annotators, four items, one annotator wanted per item: the
        # pool is over-subscribed only if both take everything before
        # either submits, which is exactly what the relaxation does.
        data_file = create_test_data_file(
            test_dir, [{"id": f"i{i}", "text": f"t{i}"} for i in range(1, 5)])
        config_file = create_test_config(
            test_dir, SCHEMES, data_files=[data_file], require_password=False,
            additional_config={"num_annotators_per_item": 1,
                               "admin_api_key": ADMIN_KEY})
        s = FlaskTestServer(port=find_free_port(), debug=False,
                            config_file=config_file)
        if not s.start_server():
            cleanup_test_directory(test_dir)
            pytest.fail("server did not start")
        s._wait_for_server_ready(timeout=10)
        yield s
        s.stop_server()
        cleanup_test_directory(test_dir)

    def test_a_clean_study_counts_zero(self, server):
        """The count must be zero when the study collected what it was
        configured to -- otherwise it is noise nobody will read."""
        from potato.item_state_management import get_item_state_manager

        alice = _login(server, "alice")
        alice.get(f"{server.base_url}/annotate")
        alice.post(f"{server.base_url}/updateinstance",
                   json={"instance_id": "i1",
                         "annotations": {"verdict:::yes": "true"}})

        assert get_item_state_manager().count_over_collected_items() == {}

    def test_an_over_collected_item_is_counted_and_named(self, server):
        from potato.item_state_management import get_item_state_manager

        # Both hold everything before either submits.
        alice = _login(server, "alice")
        bob = _login(server, "bob")
        alice.get(f"{server.base_url}/annotate")
        bob.get(f"{server.base_url}/annotate")

        for session in (alice, bob):
            session.post(f"{server.base_url}/updateinstance",
                         json={"instance_id": "i1",
                               "annotations": {"verdict:::yes": "true"}})

        over = get_item_state_manager().count_over_collected_items()
        assert over.get("i1") == 2, (
            "i1 carries two annotations under a cap of one and the count "
            f"does not name it: {over}")

    def test_an_unlimited_cap_is_never_over_collected(self, server):
        """A study with no cap has no design to exceed; counting there
        would report every popular item as a problem."""
        from potato.item_state_management import get_item_state_manager

        ism = get_item_state_manager()
        original = ism._get_annotator_cap_for_item
        ism._get_annotator_cap_for_item = lambda instance_id: -1
        try:
            for who in ("carol", "dave", "erin"):
                s = _login(server, who)
                s.get(f"{server.base_url}/annotate")
                s.post(f"{server.base_url}/updateinstance",
                       json={"instance_id": "i2",
                             "annotations": {"verdict:::no": "true"}})
            assert ism.count_over_collected_items() == {}
        finally:
            ism._get_annotator_cap_for_item = original

    def test_the_admin_overview_reports_it_over_http(self, server):
        """The manager call is the shadow; /admin/api/overview is what a
        researcher actually reads. Driven over HTTP so a payload change
        that drops the field fails here rather than passing on the
        manager alone."""
        alice = _login(server, "alice")
        bob = _login(server, "bob")
        alice.get(f"{server.base_url}/annotate")
        bob.get(f"{server.base_url}/annotate")
        for session in (alice, bob):
            session.post(f"{server.base_url}/updateinstance",
                         json={"instance_id": "i1",
                               "annotations": {"verdict:::yes": "true"}})

        admin = requests.Session()
        response = admin.get(f"{server.base_url}/admin/api/overview",
                             headers={"X-API-Key": ADMIN_KEY})
        assert response.status_code == 200, response.text[:200]
        overview = response.json()["overview"]
        assert overview["over_collected_items"] == 1, overview
        assert overview["over_collected_item_ids"] == ["i1"], overview
