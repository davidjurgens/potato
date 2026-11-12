"""`min_response_time` is measured by the server, not reported by the annotator.

The check existed to catch someone clicking through without reading, and it
was checked against `response_time_seconds` out of the request body -- a number
supplied by the annotator's own client, which is to say by the only party with
a motive to change it.

Measured before the fix. Two annotators, same study, `min_response_time: 5`,
both answering in a scripted loop milliseconds apart, both giving the same
answers. Only the reported number differed:

    honest  reports 0.4     failed on time, then blocked
    liar    reports 600.0   failed only on the wrong answer, passed the rest

And the log named only the one that told the truth, so a researcher reading it
saw a study where one annotator rushed and everyone else was careful. That
inference is produced by the bug, and no post-hoc analysis recovers it: the
real timing is gone, and the annotator who inflated it is indistinguishable in
the record from one who did not.

It also failed open. A client that sent nothing left the value None, and the
check requires non-None, so it silently did not run.

The server serves the item and receives the save, so it has both ends and never
has to ask.
"""

import time

import pytest


@pytest.fixture
def manager(tmp_path):
    from potato.quality_control import QualityControlManager

    return QualityControlManager({}, str(tmp_path))


class TestTheServerMeasuresIt:

    def test_an_unserved_item_cannot_be_measured(self, manager):
        assert manager.measured_response_time("u1", "i1") is None, (
            "a time it never observed must not be reported as one it did")

    def test_a_served_item_measures_from_the_serve(self, manager):
        manager.record_item_served("u1", "i1")
        elapsed = manager.measured_response_time("u1", "i1")
        assert elapsed is not None and elapsed < 1.0

    def test_time_actually_passing_is_reflected(self, manager):
        manager.record_item_served("u1", "i1")
        time.sleep(0.25)
        assert manager.measured_response_time("u1", "i1") >= 0.2

    def test_it_is_per_user(self, manager):
        manager.record_item_served("u1", "i1")
        assert manager.measured_response_time("u2", "i1") is None, (
            "one annotator's serve would vouch for another's speed")

    def test_it_is_per_item(self, manager):
        manager.record_item_served("u1", "i1")
        assert manager.measured_response_time("u1", "i2") is None

    def test_reading_does_not_consume_the_stamp(self, manager):
        """The annotation page saves twice for one click -- on selection and
        again on Next -- and both saves have to resolve against the same
        serve."""
        manager.record_item_served("u1", "i1")
        assert manager.measured_response_time("u1", "i1") is not None
        assert manager.measured_response_time("u1", "i1") is not None

    def test_reserving_restarts_the_clock(self, manager):
        """Navigating back to an item is a new reading of it."""
        manager.record_item_served("u1", "i1")
        time.sleep(0.2)
        manager.record_item_served("u1", "i1")
        assert manager.measured_response_time("u1", "i1") < 0.15

    def test_the_store_is_bounded(self, manager):
        """A long-running server must not accumulate one stamp per item ever
        served."""
        limit = manager._SERVED_AT_LIMIT
        for n in range(limit + 50):
            manager.record_item_served("u1", f"i{n}")
        assert len(manager._served_at) <= limit
        assert manager.measured_response_time("u1", f"i{limit + 49}") is not None

    def test_the_oldest_stamps_are_the_ones_dropped(self, manager):
        limit = manager._SERVED_AT_LIMIT
        for n in range(limit + 10):
            manager.record_item_served("u1", f"i{n}")
        assert manager.measured_response_time("u1", "i0") is None


class TestTheCheckUsesTheMeasurement:
    """`validate_attention_response` takes the seconds as an argument, so this
    asserts on what the check does with a measured value versus a claimed one.
    """

    def _manager(self, tmp_path, minimum=5):
        from potato.quality_control import QualityControlManager

        config = {"attention_checks": {"enabled": True,
                                       "min_response_time": minimum}}
        mgr = QualityControlManager(config, str(tmp_path))
        # The shape the route passes: `all_annotations`, keyed
        # `schema:::label`. The nested `{schema: {label: value}}` form is what
        # adjudication stores and is NOT what arrives here.
        mgr.attention_expected["ac1"] = {"verdict": "yes"}
        return mgr

    def test_a_fast_answer_fails_on_time_even_when_correct(self, tmp_path):
        mgr = self._manager(tmp_path)
        result = mgr.validate_attention_response(
            "u1", "ac1", {"verdict:::yes": "on"}, 0.4)
        assert result is not None and result.get("passed") is not True

    def test_a_slow_correct_answer_passes(self, tmp_path):
        mgr = self._manager(tmp_path)
        result = mgr.validate_attention_response(
            "u1", "ac1", {"verdict:::yes": "on"}, 30.0)
        assert result is not None and result.get("passed") is True

    def test_an_unmeasurable_answer_does_not_fail_on_time(self, tmp_path):
        """None means the server could not measure, not that the annotator was
        fast. The caller logs it; the check must not invent a verdict."""
        mgr = self._manager(tmp_path)
        result = mgr.validate_attention_response(
            "u1", "ac1", {"verdict:::yes": "on"}, None)
        assert result is not None and result.get("passed") is True


class TestTheRouteNoLongerTrustsTheClient:
    """Driven through the module, not by reading the handler: the client value
    must not be what reaches the check."""

    def test_the_request_body_value_is_not_the_one_checked(self):
        import inspect

        from potato import routes

        source = inspect.getsource(routes)
        block = source.split("qc_manager.validate_attention_response", 1)[0]
        tail = block[-2500:]
        assert "measured_response_time" in tail, (
            "the response time handed to the check no longer comes from the "
            "server measurement")

    def test_the_manager_exposes_what_the_route_needs(self):
        from potato.quality_control import QualityControlManager

        for name in ("record_item_served", "measured_response_time"):
            assert callable(getattr(QualityControlManager, name, None))
