"""
Integration tests for concurrent annotation constraints.

Verifies that max_annotations_per_item is enforced when multiple
annotators submit annotations for the same item.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestMaxAnnotationsPerItem:
    """Ensure the per-item annotation cap is respected."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("concurrent_ann_test")
        test_data = [
            {"id": "item_1", "text": "First test item."},
            {"id": "item_2", "text": "Second test item."},
            {"id": "item_3", "text": "Third test item."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Sentiment",
                }
            ],
            data_files=[data_file],
            max_annotations_per_item=2,
            assignment_strategy="random",
            random_seed=42,
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def _auth_session(self, flask_server, username):
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": username, "pass": "pass"},
            timeout=5,
        )
        session.post(
            f"{flask_server.base_url}/auth",
            data={"action": "login", "email": username, "pass": "pass"},
            timeout=5,
        )
        session.get(f"{flask_server.base_url}/annotate", timeout=5)
        return session

    def _annotate_and_next(self, session, base_url, instance_id, label="positive"):
        """Submit an annotation and move to the next item."""
        data = {
            "instance_id": instance_id,
            "schema": "sentiment",
            "type": "label",
            "state": [{"name": label, "value": label}],
        }
        session.post(f"{base_url}/updateinstance", json=data, timeout=5)
        session.get(f"{base_url}/next", timeout=5)

    def test_two_annotators_can_annotate_same_item(self, flask_server):
        """Two annotators should both be assigned the same item (cap=2)."""
        s1 = self._auth_session(flask_server, "conc_user_1")
        s2 = self._auth_session(flask_server, "conc_user_2")

        # Both users should be able to reach the annotation page
        r1 = s1.get(f"{flask_server.base_url}/annotate", timeout=5)
        r2 = s2.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_third_annotator_skips_saturated_item(self, flask_server):
        """A third annotator should not be assigned an item already at cap=2."""
        from potato.item_state_management import get_item_state_manager

        ism = get_item_state_manager()
        assert ism is not None
        assert ism.max_annotations_per_item == 2

        # After two annotators annotate all items, items should be complete
        s1 = self._auth_session(flask_server, "cap_user_a")
        s2 = self._auth_session(flask_server, "cap_user_b")

        # Annotate items from user a
        page_a = s1.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert page_a.status_code == 200

        # Get user a's current instance id from state
        from potato.user_state_management import get_user_state_manager
        usm = get_user_state_manager()
        ua = usm.get_user_state("cap_user_a")
        assigned_a = list(ua.get_assigned_instance_ids())

        # Annotate all assigned items as user a
        for iid in assigned_a:
            self._annotate_and_next(s1, flask_server.base_url, iid, "positive")

        # Annotate items from user b
        page_b = s2.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert page_b.status_code == 200

        ub = usm.get_user_state("cap_user_b")
        assigned_b = list(ub.get_assigned_instance_ids())

        for iid in assigned_b:
            self._annotate_and_next(s2, flask_server.base_url, iid, "negative")

        # Now a third user should get no items (or different items) if all
        # items have been annotated twice
        s3 = self._auth_session(flask_server, "cap_user_c")
        uc = usm.get_user_state("cap_user_c")
        assigned_c = list(uc.get_assigned_instance_ids())

        # Items that both user a and b annotated should NOT appear for user c
        doubly_annotated = set(assigned_a) & set(assigned_b)
        for iid in doubly_annotated:
            assert iid not in assigned_c, (
                f"Item {iid} already has 2 annotations but was assigned to a third user"
            )


class TestMaxAnnotationsUnlimited:
    """When max_annotations_per_item is -1, there should be no cap."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("unlimited_ann_test")
        test_data = [
            {"id": "u_item_1", "text": "Unlimited item."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "topic",
                    "annotation_type": "radio",
                    "labels": ["tech", "science"],
                    "description": "Topic",
                }
            ],
            data_files=[data_file],
            # No max_annotations_per_item means unlimited
        )
        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_many_annotators_all_get_item(self, flask_server):
        """With no cap, many annotators can all annotate the same item."""
        from potato.user_state_management import get_user_state_manager

        usm = get_user_state_manager()
        for i in range(5):
            username = f"unlim_user_{i}"
            session = requests.Session()
            session.post(
                f"{flask_server.base_url}/register",
                data={"action": "signup", "email": username, "pass": "pass"},
                timeout=5,
            )
            session.post(
                f"{flask_server.base_url}/auth",
                data={"action": "login", "email": username, "pass": "pass"},
                timeout=5,
            )
            session.get(f"{flask_server.base_url}/annotate", timeout=5)

            us = usm.get_user_state(username)
            assigned = list(us.get_assigned_instance_ids())
            assert "u_item_1" in assigned, f"User {username} was not assigned the item"
