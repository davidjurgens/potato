"""
Identity agreement between two annotators' tracks (iaa/identity.py): MOTA,
IDF1 and ID switches, checked against hand counts.

Most cases use objects that are plain positions on a line, with similarity 1
when two are within 1 unit and 0 otherwise, so every count can be done by
hand. The last ones go through the spatial report with real cuboids and
through the video report with real track values.
"""

import json

import pytest

from potato.server_utils.iaa import identity


def near(a, b):
    return 1.0 if abs(a - b) <= 1 else 0.0


def frames(**tracks):
    """frames(p=[0, 0, None, 0]) -> {frame: [(track, position), ...]}."""
    out = {}
    for track, positions in tracks.items():
        for frame, position in enumerate(positions):
            if position is not None:
                out.setdefault(frame, []).append((track, position))
    return out


# A tracks two objects, p at 0 and q at 10, on frames 0-3. B tracks the same
# two objects with the same boxes on every frame, but its ids swap at frame 2.
A = frames(p=[0, 0, 0, 0], q=[10, 10, 10, 10])
B_SWAPPED = frames(u=[0, 0, 10, 10], v=[10, 10, 0, 0])


class TestHandCounts:
    def test_a_swap_is_two_id_switches_and_nothing_else(self):
        counts = identity.clear_mot(A, B_SWAPPED, near, 0.5)
        assert counts == {"reference": 8, "misses": 0, "extra": 0, "id_switches": 2}

    def test_idf1_keeps_the_better_half_of_each_track(self):
        # p-u, p-v, q-u and q-v each match on 2 frames; the best one-to-one
        # assignment keeps 4 of the 8 object-frames on each side.
        assert identity.id_true_positives(A, B_SWAPPED, near, 0.5) == 4

    def test_the_report_pools_both_directions(self):
        report = identity.identity_report([identity.pair_counts(A, B_SWAPPED, near, 0.5)], 0.5)
        # MOTA = 1 - (2 + 2 switches) / (8 + 8); IDF1 = 2 * 4 / 16.
        assert report["mota"] == pytest.approx(0.75)
        assert report["idf1"] == pytest.approx(0.5)
        assert report["id_switches"] == 2.0
        assert (report["n_pairs"], report["n_object_frames"], report["match_iou"]) == (1, 16, 0.5)

    def test_a_missed_frame_is_a_miss_one_way_and_extra_the_other(self):
        b = frames(u=[0, 0, 0, 0], v=[10, 10, 10, None])
        pair = identity.pair_counts(A, b, near, 0.5)
        assert pair["a_as_reference"] == {"reference": 8, "misses": 1, "extra": 0, "id_switches": 0}
        assert pair["b_as_reference"] == {"reference": 7, "misses": 0, "extra": 1, "id_switches": 0}
        report = identity.identity_report([pair], 0.5)
        assert report["mota"] == pytest.approx(1 - 2 / 15)
        assert report["idf1"] == pytest.approx(2 * 7 / 15)
        assert report["id_switches"] == 0

    def test_a_match_that_still_holds_is_kept(self):
        # On frame 2 a second track v appears on top of u. Both fit p equally
        # well; CLEAR MOT keeps p with u, its partner on frame 1. v is listed
        # first so a fresh assignment would pick it and count a switch.
        a = frames(p=[0, 0, 0])
        b = {0: [("u", 0)], 1: [("u", 0)], 2: [("v", 0), ("u", 0)]}
        assert identity.clear_mot(a, b, near, 0.5) == {
            "reference": 3, "misses": 0, "extra": 1, "id_switches": 0}

    def test_no_tracks_has_no_numbers(self):
        report = identity.identity_report([], 0.25)
        assert "mota" not in report and report["n_pairs"] == 0 and report["note"]


def car(frame, track, x):
    return {"type": "cuboid_3d", "label": "car", "frame": frame, "track_id": track,
            "coordinates": {"center": [x, 0.0, 0.0], "size": [4.0, 2.0, 1.5],
                            "rotation": [0.0, 0.0, 0.0, 1.0]}}


class TestSpatialSequences:
    def test_crossing_cars_with_swapped_ids(self):
        """Two cars cross at frame 2. A follows each car through; B's ids swap.

        Frame by frame the boxes agree exactly, so mean_agreement is 1.0 and
        cannot show the swap. A: t1 0 -> 12, t2 12 -> 0 over frames 0-4. B: u
        and v meet at 6 on frame 2 and turn back, taking the other car's path.
        Frames 3 and 4 match t1 with v and t2 with u: 2 switches each way, so
        MOTA = 1 - 4/20. IDF1: every track pair shares 3 frames (0-2 or 2-4),
        the best assignment keeps 6 of 10 per side, 2 * 6 / 20.
        """
        from potato.server_utils.iaa.structured import spatial_report
        a = [car(0, "t1", 0.0), car(4, "t1", 12.0), car(0, "t2", 12.0), car(4, "t2", 0.0)]
        b = [car(0, "u", 0.0), car(2, "u", 6.0), car(4, "u", 0.0),
             car(0, "v", 12.0), car(2, "v", 6.0), car(4, "v", 12.0)]
        report = spatial_report({"s1": {"a": json.dumps(a), "b": json.dumps(b)}})
        assert report["mean_agreement"] == pytest.approx(1.0)
        ident = report["identity"]
        assert ident["mota"] == pytest.approx(0.8)
        assert ident["idf1"] == pytest.approx(0.6)
        assert ident["id_switches"] == 2.0
        assert ident["match_iou"] == 0.25

    def test_single_clouds_get_no_identity(self):
        from potato.server_utils.iaa.structured import spatial_report
        one = {"type": "cuboid_3d", "label": "car",
               "coordinates": {"center": [0, 0, 0], "size": [4, 2, 1.5], "rotation": [0, 0, 0, 1]}}
        report = spatial_report({"i": {"a": json.dumps([one]), "b": json.dumps([one])}})
        assert "identity" not in report


def video_value(*tracks):
    return json.dumps({"tracks": [
        {"id": tid, "label": "car",
         "keyframes": {str(f): {"frame": f, "bboxNorm": {"x": x, "y": 0.1, "width": 0.1, "height": 0.1}}
                       for f, x in keyframes}}
        for tid, keyframes in tracks]})


class TestVideoTracks:
    def test_the_same_tracks_agree_and_a_missing_annotator_misses(self):
        same = video_value(("track_1", [(0, 0.1), (4, 0.5)]))
        report = identity.video_identity({"clip": {"a": same, "b": same}})
        assert (report["mota"], report["idf1"], report["id_switches"]) == (1.0, 1.0, 0.0)
        report = identity.video_identity({"clip": {"a": same, "b": video_value()}})
        # b has nothing: a's 5 object-frames are misses one way, extras the other.
        assert report["mota"] == pytest.approx(1 - 10 / 5)
        assert report["idf1"] == 0.0

    def test_two_tracks_saved_under_one_id_are_still_two(self):
        # a saved both cars as "7"; b gave them their own ids. Keyed by id
        # alone, a's "7" changed partner on every frame: 10 switches each way.
        a = video_value(("7", [(0, 0.1), (9, 0.1)]), ("7", [(0, 0.6), (9, 0.6)]))
        b = video_value(("1", [(0, 0.1), (9, 0.1)]), ("2", [(0, 0.6), (9, 0.6)]))
        report = identity.video_identity({"clip": {"a": a, "b": b}})
        assert (report["mota"], report["idf1"], report["id_switches"]) == (1.0, 1.0, 0.0)

    def test_segment_mode_values_have_no_identity(self):
        segments = json.dumps({"segments": [{"start": 0, "end": 1, "label": "x"}]})
        assert identity.video_identity({"clip": {"a": segments, "b": segments}}) is None


class TestPresentation:
    def test_scales(self):
        from potato.server_utils.iaa.presentation import metric_scale
        assert metric_scale("identity.mota") == "raw"
        assert metric_scale("identity.idf1") == "raw"
        assert metric_scale("identity.id_switches") == "lower"
        assert metric_scale("identity.match_iou") == "count"
