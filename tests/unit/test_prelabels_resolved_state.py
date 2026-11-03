"""
Which items' span, link and event prelabels an annotator has taken over.

The prelabel routes offer a model's spans while the annotator has none stored,
so an annotator who deleted every predicted span got the prediction back.
The record of taking them over has to survive a restart, or the prediction
comes back then instead.
"""

import json
import os

from potato.user_state_management import InMemoryUserState
from tests.helpers.test_utils import create_test_directory


def _reload(us, name):
    user_dir = create_test_directory(name)
    with open(os.path.join(user_dir, "user_state.json"), "w") as f:
        json.dump(us.to_json(), f)
    return InMemoryUserState.load(user_dir)


def test_resolved_items_survive_a_reload():
    us = InMemoryUserState("taker", -1)
    assert not us.prelabels_resolved("d1")
    us.resolve_prelabels("d1")
    loaded = _reload(us, "prelabels_resolved_round_trip")
    assert loaded.prelabels_resolved("d1")
    assert not loaded.prelabels_resolved("d2")


def test_a_state_written_before_the_record_loads_with_none_resolved():
    us = InMemoryUserState("old", -1)
    d = us.to_json()
    d.pop("prelabels_resolved_ids")
    user_dir = create_test_directory("prelabels_resolved_old_state")
    with open(os.path.join(user_dir, "user_state.json"), "w") as f:
        json.dump(d, f)
    assert not InMemoryUserState.load(user_dir).prelabels_resolved("d1")


def test_clearing_an_item_offers_its_prelabels_again():
    us = InMemoryUserState("cleared", -1)
    us.resolve_prelabels("d1")
    us.clear_instance_annotations("d1")
    assert not us.prelabels_resolved("d1")
