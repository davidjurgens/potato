"""Drawings merged shape by shape (live collaborative sessions, Phase 4).

A drawing scheme stores its whole answer as one JSON value. These check the
element-level three-way merge on the shapes the real widgets write: image
(a list of shapes), audio (``{segments: [...]}``), video (lists and
mappings side by side), tiered (collections one level down), and answers
saved before shapes had ids.
"""

import json

from potato.collab.state import label_key, merge_blob, merge_payload, revert_blob


def box(i, **kw):
    return dict({"id": i, "type": "bbox", "label": "person", "coordinates": [0, 0, 1, 1]}, **kw)


def j(value):
    return json.dumps(value)


def parsed(result):
    value, _ = result
    return json.loads(value) if value else None


class TestImageShapes:
    def test_two_members_drawing_at_once_both_keep_their_shapes(self):
        base = [box("a")]
        out = parsed(merge_blob(j(base), j(base + [box("b")]), j(base + [box("c")])))
        assert [b["id"] for b in out] == ["a", "c", "b"]

    def test_moving_a_shape_keeps_a_teammates_new_one(self):
        moved = box("a", coordinates=[5, 5, 6, 6])
        out = parsed(merge_blob(j([box("a")]), j([moved]), j([box("a"), box("c")])))
        assert out == [moved, box("c")]

    def test_deleting_a_shape_a_teammate_did_not_touch_deletes_it(self):
        out = parsed(merge_blob(j([box("a"), box("b")]), j([box("b")]),
                                j([box("a"), box("b"), box("c")])))
        assert [b["id"] for b in out] == ["b", "c"]

    def test_both_changing_one_shape_is_a_conflict_and_the_later_wins(self):
        mine, theirs = box("a", label="car"), box("a", label="dog")
        value, conflicts = merge_blob(j([box("a")]), j([mine]), j([theirs]))
        assert json.loads(value) == [mine]
        assert [c["element"] for c in conflicts] == ["a/label"]

    def test_one_moving_and_the_other_relabelling_a_shape_keeps_both(self):
        moved = box("a", coordinates=[5, 5, 6, 6])
        relabelled = box("a", label="car")
        value, conflicts = merge_blob(j([box("a")]), j([moved]), j([relabelled]))
        assert json.loads(value) == [box("a", label="car", coordinates=[5, 5, 6, 6])]
        assert conflicts == []

    def test_first_shapes_on_an_empty_image_from_two_members(self):
        out = parsed(merge_blob(None, j([box("a")]), j([box("c")])))
        assert sorted(b["id"] for b in out) == ["a", "c"]

    def test_an_empty_canvas_page_does_not_clear_the_teammates_shapes(self):
        # The page loaded before the teammate drew; "[]" is what it showed.
        assert merge_blob(None, "[]", j([box("c")]))[0] == j([box("c")])

    def test_shapes_saved_before_ids_existed_merge_by_content(self):
        old = {"type": "bbox", "label": "x", "coordinates": [1, 1, 2, 2]}
        added = {"type": "bbox", "label": "y", "coordinates": [3, 3, 4, 4]}
        theirs = {"type": "bbox", "label": "z", "coordinates": [5, 5, 6, 6]}
        out = parsed(merge_blob(j([old]), j([old, added]), j([old, theirs])))
        assert out == [old, theirs, added]


class TestObjectAnswers:
    def test_audio_segments(self):
        seg = lambda i, s: {"id": i, "start_time": s, "end_time": s + 1, "label": "speech"}
        out = parsed(merge_blob(j({"segments": [seg("s1", 0)]}),
                                j({"segments": [seg("s1", 0), seg("s2", 5)]}),
                                j({"segments": [seg("s1", 0), seg("s3", 9)]})))
        assert [s["id"] for s in out["segments"]] == ["s1", "s3", "s2"]

    def test_video_lists_and_mappings_side_by_side(self):
        def video(segments, keyframes, frames):
            return j({"video_metadata": {"duration": 3}, "segments": segments,
                      "keyframes": keyframes, "frame_annotations": frames, "tracking": {}})
        out = parsed(merge_blob(video([], [], {}),
                                video([{"id": "s1"}], [], {"f1": {"id": "f1", "label": "a"}}),
                                video([], [{"id": "k1"}], {"f2": {"id": "f2", "label": "b"}})))
        assert out["segments"] == [{"id": "s1"}]
        assert out["keyframes"] == [{"id": "k1"}]
        assert set(out["frame_annotations"]) == {"f1", "f2"}
        assert out["video_metadata"] == {"duration": 3}

    def test_keyframes_inside_one_track_merge_by_frame(self):
        def track(frames):
            return j({"tracking": {"o1": {"id": "o1", "label": "car",
                                          "keyframes": {f: {"bbox": [int(f)]} for f in frames}}}})
        out = parsed(merge_blob(track(["1"]), track(["1", "5"]), track(["1", "9"])))
        assert set(out["tracking"]["o1"]["keyframes"]) == {"1", "5", "9"}

    def test_tiered_tiers_are_collections_one_level_down(self):
        def tiered(tiers):
            return j({"annotations": tiers, "time_slots": {}})
        out = parsed(merge_blob(tiered({"words": [{"id": "1"}]}),
                                tiered({"words": [{"id": "1"}, {"id": "2"}]}),
                                tiered({"words": [{"id": "1"}], "phones": [{"id": "3"}]})))
        assert [a["id"] for a in out["annotations"]["words"]] == ["1", "2"]
        assert [a["id"] for a in out["annotations"]["phones"]] == ["3"]


class TestNotADrawing:
    def test_plain_text_is_left_to_the_whole_value_rule(self):
        assert merge_blob("hello", "hello there", "hi") is None

    def test_a_list_of_numbers_is_not_a_list_of_shapes(self):
        assert merge_blob("[1, 2]", "[1, 2, 3]", "[1]") is None


class TestRevert:
    def test_undoing_my_shape_keeps_a_shape_drawn_after_it(self):
        before, after = j([box("a")]), j([box("a"), box("b")])
        current = j([box("a"), box("b"), box("c")])
        ok, value = revert_blob(before, after, current)
        assert ok and [b["id"] for b in json.loads(value)] == ["a", "c"]

    def test_text_is_not_a_drawing(self):
        assert revert_blob("x", "y", "z") == (False, None)


class TestThroughTheSave:
    """merge_payload hands a drawing scheme to the element merge."""

    def merge(self, mine, base, current):
        from potato.server_utils.annotation_keys import split_annotation_key
        return merge_payload(mine, base, current, split_key=split_annotation_key,
                             is_single_select=lambda s: False, is_multiselect=lambda s: False)

    def test_two_members_boxes_in_one_image_scheme(self):
        key = label_key("objects", "_data")
        base = {key: j([box("a")])}
        current = {key: j([box("a"), box("c")])}
        mine = {"annotations": {"objects:::_data": j([box("a"), box("b")])}}
        result = self.merge(mine, base, current)
        stored = json.loads(result.payload["annotations"]["objects:::_data"])
        assert [b["id"] for b in stored] == ["a", "c", "b"]
        assert result.conflicts == []


class TestKeepTheirs:
    """``conflict_policy: reject``: a conflict keeps the teammate's value, the
    member's other changes still go in, and the conflict is still reported."""

    def merge(self, mine, base, current, **kw):
        from potato.server_utils.annotation_keys import split_annotation_key
        return merge_payload(mine, base, current, split_key=split_annotation_key,
                             is_single_select=lambda s: s == "stance",
                             is_multiselect=lambda s: False, keep_theirs=True)

    def test_a_shape_both_moved_stays_where_the_teammate_put_it(self):
        mine_a, theirs_a = box("a", coordinates=[5, 5, 6, 6]), box("a", coordinates=[9, 9, 9, 9])
        value, conflicts = merge_blob(j([box("a")]), j([mine_a, box("b")]), j([theirs_a]),
                                      keep_theirs=True)
        assert json.loads(value) == [theirs_a, box("b")]
        assert [c["element"] for c in conflicts] == ["a/coordinates"]

    def test_a_shape_the_teammate_deleted_is_not_put_back_by_my_edit(self):
        value, conflicts = merge_blob(j([box("a"), box("k")]),
                                      j([box("a", label="car"), box("k")]), j([box("k")]),
                                      keep_theirs=True)
        assert json.loads(value) == [box("k")]
        assert len(conflicts) == 1

    def test_without_it_the_later_change_wins(self):
        mine_a, theirs_a = box("a", coordinates=[5, 5, 6, 6]), box("a", coordinates=[9, 9, 9, 9])
        value, _ = merge_blob(j([box("a")]), j([mine_a]), j([theirs_a]))
        assert json.loads(value) == [mine_a]

    def test_a_single_choice_conflict_keeps_theirs_and_my_text_goes_in(self):
        base = {}
        current = {label_key("stance", "pro"): "pro"}
        mine = {"annotations": {"stance:::con": "con", "note:::text_box": "hm"}}
        result = self.merge(mine, base, current)
        assert result.payload["annotations"] == {"note:::text_box": "hm"}
        assert [c["key"] for c in result.conflicts] == ["L:stance"]
        assert result.changed

    def test_a_text_conflict_keeps_theirs(self):
        key = label_key("note", "text_box")
        result = self.merge({"annotations": {"note:::text_box": "mine"}},
                            {key: "old"}, {key: "theirs"})
        assert result.payload["annotations"] == {}
        assert not result.changed
        assert [c["key"] for c in result.conflicts] == [key]

    def test_a_span_the_teammate_relabelled_keeps_their_label(self):
        from potato.collab.state import SPAN
        span = {"schema": "ner", "name": "PER", "start": 0, "end": 5, "title": "PER",
                "id": "s1"}
        base_entry = {"span": span, "value": "true"}
        theirs = {"span": dict(span, name="ORG", title="ORG"), "value": "true"}
        sid = "s1"
        result = self.merge(
            {"annotations": {}, "span_annotations": [dict(span, name="LOC", title="LOC",
                                                          value="true")]},
            {SPAN + sid: base_entry}, {SPAN + sid: theirs})
        assert result.payload["span_annotations"] == []
        assert [c["key"] for c in result.conflicts] == [SPAN + sid]

    def test_a_drawing_whose_only_change_was_refused_is_no_change(self):
        key = label_key("objects", "_data")
        mine_a, theirs_a = box("a", coordinates=[5, 5, 6, 6]), box("a", coordinates=[9, 9, 9, 9])
        result = self.merge({"annotations": {"objects:::_data": j([mine_a])}},
                            {key: j([box("a")])}, {key: j([theirs_a])})
        assert not result.changed
        assert len(result.conflicts) == 1


class TestElementsWithoutIds:
    """Records with no id: one per step or turn is matched by that field."""

    def test_two_members_rating_one_step_keep_both_fields(self):
        base = {"steps": [{"step_index": 0, "verdict": "ok"}, {"step_index": 1}]}
        mine = {"steps": [{"step_index": 0, "verdict": "ok"}, {"step_index": 1, "verdict": "bad"}]}
        theirs = {"steps": [{"step_index": 0, "verdict": "ok"},
                            {"step_index": 1, "comment": "tool call fails"}]}
        out = parsed(merge_blob(j(base), j(mine), j(theirs)))
        assert out["steps"] == [{"step_index": 0, "verdict": "ok"},
                                {"step_index": 1, "comment": "tool call fails", "verdict": "bad"}]

    def test_without_the_step_key_the_same_edits_would_keep_two_copies_of_the_step(self):
        # Keyed by content, both edits read as "removed step 1, added a new
        # step": the merge keeps both new records. The step key prevents it.
        base = {"steps": [{"n": 1}]}
        out = parsed(merge_blob(j(base), j({"steps": [{"n": 1, "v": "a"}]}),
                                j({"steps": [{"n": 1, "c": "b"}]})))
        assert len(out["steps"]) == 2

    def test_a_list_with_several_records_per_step_is_keyed_by_content(self):
        base = [{"step": 1, "tag": "x"}]
        mine = [{"step": 1, "tag": "x"}, {"step": 1, "tag": "y"}]
        theirs = [{"step": 1, "tag": "x"}, {"step": 2, "tag": "z"}]
        out = parsed(merge_blob(j(base), j(mine), j(theirs)))
        assert sorted((e["step"], e["tag"]) for e in out) == [(1, "x"), (1, "y"), (2, "z")]

    def test_two_identical_shapes_saved_before_ids_are_both_kept(self):
        legacy = {"type": "bbox", "label": "car", "coordinates": [0, 0, 1, 1]}
        base = [legacy, legacy]
        theirs = [legacy, legacy, {"type": "bbox", "label": "dog", "coordinates": [2, 2, 3, 3]}]
        out = parsed(merge_blob(j(base), j(base), j(theirs)))
        assert out == theirs

    def test_deleting_one_of_two_identical_shapes_deletes_one(self):
        legacy = {"type": "bbox", "label": "car", "coordinates": [0, 0, 1, 1]}
        out = parsed(merge_blob(j([legacy, legacy]), j([legacy]), j([legacy, legacy])))
        assert out == [legacy]

    def test_two_regions_on_one_time_point_are_two_regions(self):
        # Microscopy regions carry ``t`` (the time point). Matched on it, two
        # members' first regions on t=0 were one element, and one was lost.
        mine = {"rois": [{"t": 0, "points": [[0, 0], [1, 1]], "label": "cell"}]}
        theirs = {"rois": [{"t": 0, "points": [[5, 5], [6, 6]], "label": "cell"}]}
        out = parsed(merge_blob(j({"rois": []}), j(mine), j(theirs)))
        assert len(out["rois"]) == 2
