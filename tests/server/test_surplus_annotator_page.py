"""
What a fourth annotator sees when three items need one annotator each.

Before this, they saw the completion page: "Thank You! You have completed the
annotation task and your responses are saved." They had annotated nothing, no
``annotation_output/<user>/`` directory existed, and the log said nothing about
it. On a pilot that reads as "the study is broken"; in the field it pays people
for a page they could not work on.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

ITEM_IDS = [f"item_{i}" for i in range(3)]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("surplus_annotator")
    data = [{"id": iid, "text": f"sentence {i}"} for i, iid in enumerate(ITEM_IDS)]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "How does this read?",
            "labels": ["positive", "negative"],
        }],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="Surplus annotator",
        require_password=False,
        # One annotator per item, one item per annotator, three items: the
        # fourth user to arrive can be given nothing. The per-user quota is
        # what makes the first three take one item each rather than the first
        # taking all three -- the shape the audit reported.
        num_annotators_per_item=1,
        max_annotations_per_user=1,
    )
    srv = FlaskTestServer(port=find_free_port(preferred_port=9114),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    yield srv, test_dir
    srv.stop_server()
    cleanup_test_directory(test_dir)


def _join(base_url, user):
    session = requests.Session()
    session.post(f"{base_url}/register",
                 data={"email": user, "pass": "pw", "action": "signup"})
    session.post(f"{base_url}/auth", data={"email": user, "pass": "pw"})
    return session, session.get(f"{base_url}/annotate")


def _work(base_url, user):
    """Join, annotate whatever was assigned, and report what was seen."""
    from potato.user_state_management import get_user_state_manager

    session, response = _join(base_url, user)
    assigned = list(
        get_user_state_manager().get_user_state(user).get_assigned_instance_ids())
    for instance_id in assigned:
        session.post(f"{base_url}/updateinstance",
                     json={"instance_id": instance_id,
                           # `schema:::label`; the nested form names no label
                           # and stored nothing, so this loop was a no-op.
                           "annotations": {"sentiment:::positive": "true"}})
    return session, response, assigned


class TestSurplusAnnotator:
    """Ordered: the pool has to be exhausted before the surplus case exists."""

    def test_the_first_three_each_get_one_item(self, server):
        srv, _ = server
        for i in range(3):
            _, response, assigned = _work(srv.base_url, f"worker{i}")
            assert response.status_code == 200
            assert len(assigned) == 1, f"worker{i} got {assigned}"
            assert "There is no work left for you" not in response.text

    def test_the_fourth_is_not_told_they_finished(self, server):
        # The exact wrong sentence, named so a regression cannot slip past by
        # rewording the right one.
        srv, _ = server
        _, response, assigned = _work(srv.base_url, "worker_surplus")
        assert response.status_code == 200
        assert assigned == []
        assert "You have completed the annotation task" not in response.text
        assert "Thank You!" not in response.text

    def test_the_fourth_is_told_there_is_no_work(self, server):
        srv, _ = server
        _, response, _assigned = _work(srv.base_url, "worker_surplus_2")
        assert "There is no work left for you" in response.text
        assert "You have not annotated anything" in response.text

    def test_they_stay_in_the_annotation_phase_so_new_data_reaches_them(self, server):
        # Advancing the phase was what produced the completion page, and it is
        # a one-way door: a user moved to DONE never returns to /annotate even
        # if the study later gains items or raises its annotator count.
        from potato.phase import UserPhase
        from potato.user_state_management import get_user_state_manager

        srv, _ = server
        session, _, _assigned = _work(srv.base_url, "worker_surplus_3")
        state = get_user_state_manager().get_user_state("worker_surplus_3")
        assert state.get_phase() == UserPhase.ANNOTATION
        again = session.get(f"{srv.base_url}/annotate")
        assert "There is no work left for you" in again.text

    def test_nothing_is_recorded_against_them(self, server):
        # They annotated nothing, so nothing should exist under their name --
        # the completion page's "your responses are saved" was false as well
        # as misleading.
        from potato.user_state_management import get_user_state_manager

        srv, _ = server
        _work(srv.base_url, "worker_surplus_4")
        state = get_user_state_manager().get_user_state("worker_surplus_4")
        assert not state.get_annotated_instance_ids()
