"""Machine consensus never reaches the gold pool, driven through a real server.

The unit tests cover ``record_item_annotation(origin=...)``. They cannot see
whether ``/updateinstance`` passes the participant's origin in, and without it
every caller reads as a person and the guard refuses nothing.

The positive case is here for the same reason: a study where promotion never
fires would pass the negative assertion by doing nothing at all.
"""

import json
import os

import pytest
import requests

from potato.quality_control import get_quality_control_manager
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

PORT = 9243

SCHEMES = [
    {
        "annotation_type": "radio",
        "name": "product",
        "description": "Product?",
        "labels": ["hypothetical", "kinase"],
    },
]

ITEMS = [{"id": f"item_{i}", "text": f"Locus {i}"} for i in range(1, 4)]

TOOLS = ["prokka", "bakta", "pgap"]
PEOPLE = ["alice", "bob", "carol"]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("machine_consensus_gold_api")
    try:
        create_test_data_file(test_dir, ITEMS)
        # Gold standards refuse to load without a configured pool, even when
        # auto-promotion is the only part under test.
        gold_file = os.path.join(os.path.abspath(test_dir), "gold.json")
        with open(gold_file, "w", encoding="utf-8") as fh:
            json.dump([{"id": "gold_1", "text": "Known locus",
                        "gold_label": {"product": "kinase"}}], fh)
        config_file = create_test_config(
            test_dir,
            SCHEMES,
            data_files=["test_data.jsonl"],
            annotation_task_name="Machine Consensus Gold",
            additional_config={
                "machine_annotators": {
                    "enabled": True,
                    "annotators": [{"id": t, "kind": "tool"} for t in TOOLS],
                },
                "gold_standards": {
                    "enabled": True,
                    "items_file": gold_file,
                    "auto_promote": {"enabled": True, "min_annotators": 3,
                                     "agreement_threshold": 1.0},
                },
            },
        )
        srv = FlaskTestServer(port=PORT, config_file=config_file)
        if not srv.start():
            pytest.fail("Failed to start server for machine consensus tests")
        yield srv
        srv.stop()
    finally:
        cleanup_test_directory(test_dir)


def _save_as(server, username, instance_id):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"action": "signup", "email": username, "pass": "pw12345"})
    s.post(f"{server.base_url}/auth",
           data={"action": "login", "email": username, "pass": "pw12345"})
    response = s.post(
        f"{server.base_url}/updateinstance",
        json={
            "instance_id": instance_id,
            "annotations": {"product:::hypothetical": "hypothetical"},
            "span_annotations": [],
        },
    )
    assert response.status_code == 200, response.text


def _promoted_ids():
    return [g["id"] for g in get_quality_control_manager().get_promoted_gold_standards()]


def test_three_agreeing_tools_do_not_write_the_answer_key(server):
    for tool in TOOLS:
        _save_as(server, tool, "item_1")
    assert "item_1" not in _promoted_ids()


def test_three_agreeing_people_still_do(server):
    for person in PEOPLE:
        _save_as(server, person, "item_2")
    assert "item_2" in _promoted_ids()
