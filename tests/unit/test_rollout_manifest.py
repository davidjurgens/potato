"""
Reading a rollout set, and the two things about it that are decided per user.

The panel order and the blinding are the parts most likely to break silently.
An order that is not stable across reloads makes an annotator's own second look
disagree with their first; blinding that leaks the generator name turns a
preference study into a popularity contest. Neither shows up as an error.
"""

from __future__ import annotations

import json

import pytest

from potato.rollouts.models import (
    RolloutError,
    RolloutSet,
    RolloutStream,
    stable_order,
)
from potato.rollouts.registry import from_item, from_manifest, read_rollout_set


SPEC = {
    "streams": [
        {"field": "real", "name": "Recording", "role": "real"},
        {"field": "gen_a", "name": "Model A"},
        {"field": "gen_b", "name": "Model B"},
    ],
    "fps": 25,
}

ITEM = {
    "id": "ball_drop",
    "prompt": "A ball is dropped.",
    "real": "rollouts/ball_drop/real.webm",
    "gen_a": "rollouts/ball_drop/gen_a.webm",
    "gen_b": "rollouts/ball_drop/gen_b.webm",
}


class TestReadingFromTheItem:
    def test_every_configured_stream_becomes_a_rollout(self):
        rollout = from_item(ITEM, SPEC)
        assert [s.stream_id for s in rollout.streams] == ["real", "gen_a", "gen_b"]
        assert rollout.stream("real").role == "real"
        assert rollout.stream("gen_a").role == "model"
        assert rollout.prompt == "A ball is dropped."

    def test_the_declared_frame_rate_reaches_every_stream(self):
        rollout = from_item(ITEM, SPEC)
        assert all(s.fps == 25 for s in rollout.streams)
        assert rollout.effective_fps == 25

    def test_a_stream_missing_from_this_item_is_skipped_and_named(self):
        # Benchmarks are ragged -- a model that failed to produce a rollout for
        # one prompt is normal. An empty panel saying "not found" reads as a
        # Potato bug rather than as missing data.
        ragged = dict(ITEM)
        ragged["gen_b"] = ""
        rollout = from_item(ragged, SPEC)
        assert [s.stream_id for s in rollout.streams] == ["real", "gen_a"]
        assert rollout.metadata["missing_streams"] == ["Model B"]

    def test_a_schema_with_no_streams_says_what_to_add(self):
        with pytest.raises(RolloutError) as excinfo:
            from_item(ITEM, {"streams": []})
        assert "streams" in str(excinfo.value)

    def test_a_stream_entry_with_no_field_names_the_problem(self):
        with pytest.raises(RolloutError) as excinfo:
            from_item(ITEM, {"streams": [{"name": "Model A"}]})
        assert "field" in str(excinfo.value)

    def test_a_bare_string_is_a_field_name(self):
        rollout = from_item(ITEM, {"streams": ["real", "gen_a"]})
        assert [s.stream_id for s in rollout.streams] == ["real", "gen_a"]

    def test_a_relative_path_is_served_from_the_media_route(self):
        # Found by Playwright, invisible everywhere else: without the prefix
        # the browser resolves the path against the page URL and every panel
        # 404s. There is no error to see -- a <video> with a missing source
        # never reports a length, so the timeline sits at zero looking like it
        # is still loading.
        rollout = from_item(ITEM, SPEC)
        assert rollout.stream("real").url == "/media/rollouts/ball_drop/real.webm"

    def test_an_absolute_url_is_left_alone(self):
        item = dict(ITEM, real="https://cdn.example/real.webm")
        assert (from_item(item, SPEC).stream("real").url
                == "https://cdn.example/real.webm")

    def test_an_already_rooted_path_is_not_prefixed_twice(self):
        item = dict(ITEM, real="/media/elsewhere/real.webm")
        assert (from_item(item, SPEC).stream("real").url
                == "/media/elsewhere/real.webm")

    def test_the_intervention_and_its_time_come_off_the_item(self):
        item = dict(ITEM, intervention="the wall moved", intervention_t=1.5)
        rollout = from_item(item, SPEC)
        assert rollout.intervention == "the wall moved"
        assert rollout.intervention_t == 1.5


class TestReadingFromAManifest:
    def _write(self, tmp_path, payload):
        path = tmp_path / "rollouts" / "set.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_streams_are_read_with_their_declared_lengths(self, tmp_path):
        path = self._write(tmp_path, {
            "fps": 24,
            "prompt": "A block slides.",
            "streams": [
                {"id": "real", "url": "real.webm", "role": "real",
                 "duration": 5.0},
                {"id": "gen_a", "url": "gen_a.webm", "duration": 5.0},
            ],
        })
        rollout = from_manifest(str(path), {"media_root": str(tmp_path)})
        assert rollout.effective_fps == 24
        assert rollout.duration == 5.0
        assert rollout.prompt == "A block slides."

    def test_relative_urls_are_rewritten_to_the_media_route(self, tmp_path):
        path = self._write(tmp_path, {
            "streams": [{"id": "real", "url": "real.webm"},
                        {"id": "gen_a", "url": "gen_a.webm"}]})
        rollout = from_manifest(str(path), {"media_root": str(tmp_path)})
        assert rollout.stream("real").url == "/media/rollouts/real.webm"

    def test_absolute_urls_are_left_alone(self, tmp_path):
        # A manifest full of absolute URLs is a legitimate shape; inventing a
        # prefix for it would break it.
        path = self._write(tmp_path, {
            "streams": [{"id": "real", "url": "https://cdn.example/real.webm"},
                        {"id": "gen_a", "url": "/media/elsewhere/a.webm"}]})
        rollout = from_manifest(str(path), {"media_root": str(tmp_path)})
        assert rollout.stream("real").url == "https://cdn.example/real.webm"
        assert rollout.stream("gen_a").url == "/media/elsewhere/a.webm"

    def test_a_missing_manifest_names_the_file(self, tmp_path):
        with pytest.raises(RolloutError) as excinfo:
            from_manifest(str(tmp_path / "nope.json"), {})
        assert "nope.json" in str(excinfo.value)

    def test_invalid_json_says_so_rather_than_raising_a_decoder_error(
            self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(RolloutError) as excinfo:
            from_manifest(str(path), {})
        assert "not valid JSON" in str(excinfo.value)

    def test_a_manifest_with_no_streams_says_which_key_is_missing(
            self, tmp_path):
        path = self._write(tmp_path, {"prompt": "hello"})
        with pytest.raises(RolloutError) as excinfo:
            from_manifest(str(path), {})
        assert "streams" in str(excinfo.value)

    def test_read_rollout_set_dispatches_on_manifest_field(self, tmp_path):
        path = self._write(tmp_path, {
            "streams": [{"id": "real", "url": "real.webm"},
                        {"id": "gen_a", "url": "a.webm"}]})
        rollout = read_rollout_set(
            {"manifest": "rollouts/set.json"},
            {"manifest_field": "manifest", "media_root": str(tmp_path)},
            resolve_manifest=lambda p: str(path))
        assert rollout.source_format == "manifest"

    def test_a_manifest_outside_the_media_directory_is_refused(self):
        with pytest.raises(RolloutError) as excinfo:
            read_rollout_set({"manifest": "../../etc/passwd"},
                             {"manifest_field": "manifest"},
                             resolve_manifest=lambda p: None)
        assert "outside" in str(excinfo.value)


class TestTheTimeline:
    def test_the_timeline_runs_to_the_LONGEST_stream(self):
        # Not the shortest. A rollout that keeps going after the real recording
        # ends is exactly where drift and appearance collapse show up.
        rollout = RolloutSet(set_id="s", streams=[
            RolloutStream("a", "a.webm", duration=5.0),
            RolloutStream("b", "b.webm", duration=7.5),
        ])
        assert rollout.duration == 7.5

    def test_streams_of_different_lengths_are_reported(self):
        rollout = RolloutSet(set_id="s", fps=25, streams=[
            RolloutStream("a", "a.webm", duration=5.0),
            RolloutStream("b", "b.webm", duration=3.0),
        ])
        warnings = " ".join(rollout.validate())
        assert "differ in length" in warnings

    def test_a_one_frame_difference_is_not_reported(self):
        # Encoders round the last frame's duration; flagging 40 ms would flag
        # every set always, and a warning that is always on is not read.
        rollout = RolloutSet(set_id="s", fps=25, streams=[
            RolloutStream("a", "a.webm", duration=5.0),
            RolloutStream("b", "b.webm", duration=5.02),
        ])
        assert not any("differ in length" in w for w in rollout.validate())

    def test_one_stream_is_not_a_comparison(self):
        rollout = RolloutSet(set_id="s", streams=[
            RolloutStream("a", "a.webm", duration=5.0)])
        assert any("at least two" in w for w in rollout.validate())

    def test_mismatched_frame_rates_are_reported_and_the_lowest_wins(self):
        # Stepping at the highest rate leaves slower streams on the same frame
        # for several presses, which reads as the control being broken.
        rollout = RolloutSet(set_id="s", streams=[
            RolloutStream("a", "a.webm", fps=30.0, duration=5.0),
            RolloutStream("b", "b.webm", fps=24.0, duration=5.0),
        ])
        assert rollout.effective_fps == 24.0
        assert any("frame rates" in w for w in rollout.validate())

    def test_frame_at_rounds_rather_than_truncating(self):
        # 0.999 of a frame means the next frame. Truncating would place every
        # quoted frame one early.
        rollout = RolloutSet(set_id="s", fps=25)
        assert rollout.frame_at(0.999 / 25) == 1
        assert rollout.frame_at(1.4 / 25) == 1
        assert rollout.frame_at(1.6 / 25) == 2


class TestOrderAndBlinding:
    IDS = ["real", "gen_a", "gen_b", "gen_c"]

    def test_the_order_is_the_same_every_time_for_one_annotator(self):
        # The property the whole scheme rests on. A client-side shuffle
        # reshuffles on reload, and then the annotator's second look disagrees
        # with their first and the answers cannot be pooled.
        first = stable_order(self.IDS, "alice\x00item1")
        for _ in range(20):
            assert stable_order(self.IDS, "alice\x00item1") == first

    def test_different_annotators_get_different_orders(self):
        orders = {tuple(stable_order(self.IDS, f"user{i}\x00item1"))
                  for i in range(12)}
        assert len(orders) > 1

    def test_the_same_annotator_gets_different_orders_on_different_items(self):
        assert (stable_order(self.IDS, "alice\x00item1")
                != stable_order(self.IDS, "alice\x00item2")
                or stable_order(self.IDS, "alice\x00item3")
                != stable_order(self.IDS, "alice\x00item1"))

    def test_the_order_is_a_permutation_and_loses_nothing(self):
        assert sorted(stable_order(self.IDS, "alice\x00i")) == sorted(self.IDS)

    def test_blinding_replaces_the_names_with_positional_letters(self):
        rollout = from_item(ITEM, SPEC)
        payload = rollout.to_json(blind=True)
        assert [s["name"] for s in payload["streams"]] == ["A", "B", "C"]

    def test_blinding_keeps_the_stream_ids(self):
        # They are what annotations reference and what agreement joins on.
        rollout = from_item(ITEM, SPEC)
        payload = rollout.to_json(blind=True)
        assert [s["stream_id"] for s in payload["streams"]] == [
            "real", "gen_a", "gen_b"]

    def test_blinding_hides_the_real_role_but_keeps_counterfactual(self):
        # "real" is the ground truth and every annotator knows it, so the role
        # leaks the identity. The counterfactual distinction survives because
        # the interface needs it to ask its own question.
        rollout = RolloutSet(set_id="s", streams=[
            RolloutStream("real", "r.webm", role="real"),
            RolloutStream("cf", "c.webm", role="counterfactual"),
        ])
        roles = [s["role"] for s in rollout.to_json(blind=True)["streams"]]
        assert roles == ["hidden", "counterfactual"]

    def test_an_unblinded_set_keeps_the_configured_names(self):
        rollout = from_item(ITEM, SPEC)
        payload = rollout.to_json(blind=False)
        assert [s["name"] for s in payload["streams"]] == [
            "Recording", "Model A", "Model B"]

    def test_the_order_is_applied_to_the_payload(self):
        rollout = from_item(ITEM, SPEC)
        payload = rollout.to_json(order=["gen_b", "real", "gen_a"])
        assert [s["stream_id"] for s in payload["streams"]] == [
            "gen_b", "real", "gen_a"]
        assert [s["position"] for s in payload["streams"]] == [0, 1, 2]

    def test_a_stale_order_does_not_drop_a_stream_it_never_saw(self):
        # Showing two panels when the item has three is unrecoverable from the
        # stored annotation: nothing records that the third was never on screen.
        rollout = from_item(ITEM, SPEC)
        payload = rollout.to_json(order=["gen_b", "real"])
        assert {s["stream_id"] for s in payload["streams"]} == {
            "real", "gen_a", "gen_b"}

    def test_blind_labels_stay_unique_past_twenty_six_panels(self):
        streams = [RolloutStream(f"s{i}", f"{i}.webm") for i in range(30)]
        names = [s["name"] for s
                 in RolloutSet(set_id="s", streams=streams).to_json(blind=True)
                 ["streams"]]
        assert len(set(names)) == 30
        assert names[25] == "Z"
        assert names[26] == "AA"
