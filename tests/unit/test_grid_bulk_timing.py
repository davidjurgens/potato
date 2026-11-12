"""
Grid saves carry each item's share of the page's active time.

The grid has no per-item events, so the page measures its own active time and
splits it among the items it saves. BehavioralData.bulk holds the share, and
both active_time_ms() and the Throughput report count it.
"""

from potato.interaction_tracking import BehavioralData, InteractionEvent
from potato.throughput import _active_ms, _finished_at


def test_the_share_is_stored_clamped_and_counted():
    bd = BehavioralData(instance_id="i1")
    bd.record_bulk_time({"page_items": 4, "page_active_ms": 20000, "active_ms": 5000}, now=1000.0)
    assert bd.bulk == {"view": "grid", "page_items": 4, "page_active_ms": 20000,
                       "active_ms": 5000, "saved_at": 1000.0}
    assert bd.active_time_ms() == 5000
    assert _active_ms(bd) == 5000 and _active_ms(bd.to_dict()) == 5000
    assert _finished_at(bd.to_dict()) == 1000.0


def test_nonsense_from_the_client_is_clamped():
    bd = BehavioralData(instance_id="i1")
    bd.record_bulk_time({"page_items": "x", "page_active_ms": -5, "active_ms": 10 ** 12})
    assert bd.bulk["page_items"] == 1 and bd.bulk["page_active_ms"] == 0
    assert bd.bulk["active_ms"] == BehavioralData.MAX_BULK_MS


def test_events_and_a_share_add_up():
    bd = BehavioralData(instance_id="i1")
    bd.interactions = [InteractionEvent(event_type="click", target="a", timestamp=t, instance_id="i1")
                       for t in (100.0, 102.0)]
    bd.record_bulk_time({"active_ms": 1500})
    assert bd.active_time_ms() == 3500


def test_round_trip():
    bd = BehavioralData(instance_id="i1")
    bd.record_bulk_time({"page_items": 2, "page_active_ms": 10, "active_ms": 5}, now=7.0)
    assert BehavioralData.from_dict(bd.to_dict()).bulk == bd.bulk
