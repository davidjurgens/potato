"""
Unit tests for potato.ai.critique — the pure half of the VLM critique pass.

Everything here runs without a model, a network, or an image, which is the
point of the split. The properties that matter are the ones that keep a judge
from manufacturing findings: unparseable answers must not flag, low confidence
must not flag, a label outside the schema must not flag, and an error must not
flag.
"""

import pytest

from potato.ai.critique import (
    CAVEAT,
    CRITIQUE_VERDICTS,
    CritiqueRegion,
    DEFAULT_MIN_CONFIDENCE,
    MissedObject,
    build_missed_prompt,
    build_region_prompt,
    coerce_payload,
    crop_window,
    parse_missed,
    parse_region_verdict,
    regions_from_objects,
    suppress_covered,
    summarize,
)

LABELS = ["cat", "dog", "car"]


def region(index=0, label="cat", bbox=(100, 100, 50, 50), **kw):
    return CritiqueRegion(index=index, label=label, type=kw.pop("type", "bbox"),
                          bbox=bbox, **kw)


def norm_bbox(x, y, w, h, iw=500.0, ih=500.0):
    return {"x": x / iw, "y": y / ih, "width": w / iw, "height": h / ih}


class TestRegions:
    def test_every_geometry_type_yields_a_croppable_region(self):
        """Regions come from normalize_annotation_object, so a type added to
        the coordinate contract is critiqueable with no change here."""
        objects = [
            {"type": "bbox", "label": "cat",
             "coordinates": norm_bbox(10, 10, 40, 40)},
            {"type": "polygon", "label": "dog",
             "coordinates": [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.1},
                             {"x": 0.2, "y": 0.3}]},
            {"type": "polyline", "label": "car",
             "coordinates": [{"x": 0.5, "y": 0.5}, {"x": 0.8, "y": 0.6}]},
        ]
        regions = regions_from_objects(objects, 500, 500)
        assert [r.type for r in regions] == ["bbox", "polygon", "polyline"]
        assert all(r.bbox[2] > 0 or r.bbox[3] > 0 for r in regions)

    def test_index_is_the_position_in_the_stored_list(self):
        """A verdict's index is its only identity, so it must survive a
        malformed neighbour rather than being renumbered."""
        objects = [
            {"type": "bbox", "label": "cat",
             "coordinates": norm_bbox(10, 10, 40, 40)},
            {"nonsense": True},
            {"type": "bbox", "label": "dog",
             "coordinates": norm_bbox(80, 80, 40, 40)},
        ]
        regions = regions_from_objects(objects, 500, 500)
        assert [r.index for r in regions] == [0, 2]
        assert [r.label for r in regions] == ["cat", "dog"]

    def test_malformed_objects_are_skipped_not_raised(self):
        assert regions_from_objects([None, 5, {}, "x"], 100, 100) == []

    def test_polygon_points_are_absolute_pixels(self):
        objects = [{"type": "polygon", "label": "cat",
                    "coordinates": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0},
                                    {"x": 0.5, "y": 0.5}]}]
        r = regions_from_objects(objects, 200, 400)[0]
        assert r.points == [[0.0, 0.0], [100.0, 0.0], [100.0, 200.0]]


class TestCropWindow:
    def test_context_is_included_around_the_region(self):
        """A crop tight to the bbox makes boundary quality unjudgeable — the
        object fills the frame by construction."""
        w = crop_window([100, 100, 50, 50], 500, 500)
        assert w.x0 < 100 and w.y0 < 100
        assert w.x1 > 150 and w.y1 > 150

    def test_padding_follows_the_longer_side(self):
        """A long thin bar padded per-side becomes a square of background."""
        w = crop_window([100, 100, 200, 20], 1000, 1000)
        assert w.width > w.height

    def test_a_corner_region_still_gets_the_minimum_size(self):
        """Growing symmetrically then clamping leaves the crop that most needed
        widening the smallest one."""
        w = crop_window([0, 0, 10, 10], 500, 500)
        assert w.width >= 96 and w.height >= 96
        w = crop_window([490, 490, 10, 10], 500, 500)
        assert w.width >= 96 and w.height >= 96
        assert w.x1 <= 500 and w.y1 <= 500

    def test_it_never_asks_for_more_than_the_image_has(self):
        w = crop_window([0, 0, 10, 10], 40, 40)
        assert (w.x0, w.y0, w.x1, w.y1) == (0, 0, 40, 40)

    def test_the_window_is_never_empty(self):
        """PIL raises on a zero-area crop, so the caller would see a traceback
        instead of a verdict."""
        for bbox in ([0, 0, 0, 0], [-50, -50, 10, 10], [900, 900, 10, 10]):
            w = crop_window(bbox, 100, 100)
            assert w.width > 0 and w.height > 0

    def test_shift_translates_into_crop_local_coordinates(self):
        w = crop_window([100, 100, 50, 50], 500, 500)
        assert w.shift([[100, 100]]) == [[100 - w.x0, 100 - w.y0]]
        assert w.shift_bbox([100, 100, 50, 50]) == [100 - w.x0, 100 - w.y0, 50, 50]


class TestPrompts:
    def test_the_region_prompt_names_the_label_under_review(self):
        prompt = build_region_prompt(region(label="cat"), LABELS, "Find pets.")
        assert '"cat"' in prompt
        assert "dog" in prompt and "car" in prompt
        assert "Find pets." in prompt

    def test_the_region_prompt_names_the_outline_colour_it_is_given(self):
        """The service draws the outline; if the two disagree the prompt points
        the model at a colour that is not in the image."""
        prompt = build_region_prompt(region(), LABELS, outline_colour="bright red")
        assert "bright red" in prompt

    def test_the_region_prompt_offers_uncertain_as_a_real_answer(self):
        prompt = build_region_prompt(region(), LABELS)
        assert "uncertain" in prompt
        assert "guessing is not" in prompt

    def test_the_missed_prompt_lists_what_is_already_annotated(self):
        prompt = build_missed_prompt([region(0, "cat"), region(1, "dog")],
                                     LABELS)
        assert "2 region" in prompt
        assert "cat" in prompt and "dog" in prompt

    def test_the_missed_prompt_says_empty_is_the_expected_answer(self):
        """Without it, models pad the list to look useful."""
        prompt = build_missed_prompt([], LABELS)
        assert "empty list" in prompt
        assert "none" in prompt


class TestCoercePayload:
    def test_plain_json(self):
        assert coerce_payload('{"verdict": "confirmed"}') == {"verdict": "confirmed"}

    def test_fenced_json(self):
        raw = '```json\n{"verdict": "confirmed"}\n```'
        assert coerce_payload(raw)["verdict"] == "confirmed"

    def test_json_with_commentary_containing_braces(self):
        """A 'find the last brace' scan fails on exactly this shape."""
        raw = 'Here you go:\n{"verdict": "confirmed"}\nNote: use {curly} carefully.'
        assert coerce_payload(raw) == {"verdict": "confirmed"}

    def test_braces_inside_strings_do_not_end_the_object(self):
        raw = '{"rationale": "it looks like a {thing}", "verdict": "confirmed"}'
        assert coerce_payload(raw)["verdict"] == "confirmed"

    def test_escaped_quotes_inside_strings(self):
        raw = '{"rationale": "a \\"cat\\" probably", "verdict": "confirmed"}'
        assert coerce_payload(raw)["verdict"] == "confirmed"

    def test_pydantic_models_are_dumped(self):
        class Fake:
            def model_dump(self):
                return {"verdict": "confirmed"}

        assert coerce_payload(Fake()) == {"verdict": "confirmed"}

    def test_unusable_input_becomes_an_empty_dict_not_an_exception(self):
        for raw in (None, "", "no json here", 42, [1, 2], '{"broken": '):
            assert coerce_payload(raw) == {}


class TestParseRegionVerdict:
    def test_a_clean_confirmation(self):
        v = parse_region_verdict(
            {"verdict": "confirmed", "boundary": "tight", "confidence": 0.9,
             "rationale": "It is a cat."}, region(), LABELS)
        assert v.verdict == "confirmed"
        assert v.flagged is False
        assert v.rationale == "It is a cat."

    def test_a_wrong_label_flags_and_resolves_the_suggestion(self):
        v = parse_region_verdict(
            {"verdict": "wrong_label", "suggested_label": "Dog",
             "boundary": "tight", "confidence": 0.9}, region(), LABELS)
        assert v.verdict == "wrong_label"
        assert v.suggested_label == "dog"  # matched to the schema's casing
        assert v.flagged is True

    def test_an_unreadable_response_does_not_flag(self):
        """The most important property here: no answer is not a finding."""
        v = parse_region_verdict("the model rambled", region(), LABELS)
        assert v.verdict == "uncertain"
        assert v.flagged is False

    def test_an_unrecognised_verdict_string_does_not_flag(self):
        v = parse_region_verdict({"verdict": "totally_bogus", "confidence": 0.99},
                                 region(), LABELS)
        assert v.verdict == "uncertain"
        assert v.flagged is False

    def test_low_confidence_disagreement_is_downgraded(self):
        v = parse_region_verdict(
            {"verdict": "wrong_label", "suggested_label": "dog",
             "confidence": DEFAULT_MIN_CONFIDENCE - 0.01}, region(), LABELS)
        assert v.verdict == "uncertain"
        assert v.flagged is False

    def test_confidence_at_the_threshold_still_flags(self):
        v = parse_region_verdict(
            {"verdict": "wrong_label", "suggested_label": "dog",
             "confidence": DEFAULT_MIN_CONFIDENCE}, region(), LABELS)
        assert v.flagged is True

    def test_a_suggestion_outside_the_schema_is_not_actionable(self):
        """The annotator cannot apply a label the task does not have, so
        reporting it as a finding wastes the one thing the queue spends."""
        v = parse_region_verdict(
            {"verdict": "wrong_label", "suggested_label": "aardvark",
             "confidence": 0.99}, region(), LABELS)
        assert v.verdict == "uncertain"
        assert v.flagged is False
        assert v.suggested_label == ""
        assert "aardvark" in v.rationale

    def test_confirmed_with_a_bad_boundary_becomes_a_boundary_finding(self):
        v = parse_region_verdict(
            {"verdict": "confirmed", "boundary": "loose", "confidence": 0.9},
            region(), LABELS)
        assert v.verdict == "loose_boundary"
        assert v.flagged is True

    def test_confirmed_with_a_clipped_boundary_also_flags(self):
        v = parse_region_verdict(
            {"verdict": "confirmed", "boundary": "clipped", "confidence": 0.9},
            region(), LABELS)
        assert v.verdict == "loose_boundary"

    def test_a_self_contradicting_verdict_trusts_the_label_it_named(self):
        """'wrong_label: cat' on a region already labelled cat is the model
        contradicting itself; flagging it would send the annotator to change
        a label to the one it already has."""
        v = parse_region_verdict(
            {"verdict": "wrong_label", "suggested_label": "cat",
             "boundary": "tight", "confidence": 0.95},
            region(label="cat"), LABELS)
        assert v.verdict == "confirmed"
        assert v.flagged is False

    def test_confidence_on_a_hundred_point_scale_is_rescaled(self):
        v = parse_region_verdict(
            {"verdict": "wrong_label", "suggested_label": "dog",
             "confidence": 85}, region(), LABELS)
        assert v.confidence == pytest.approx(0.85)
        assert v.flagged is True

    def test_nonsense_confidence_reads_as_zero(self):
        for bad in ("high", None, float("nan"), float("inf")):
            v = parse_region_verdict(
                {"verdict": "wrong_label", "suggested_label": "dog",
                 "confidence": bad}, region(), LABELS)
            assert v.confidence == 0.0
            assert v.flagged is False

    def test_an_unknown_boundary_word_does_not_invent_a_finding(self):
        v = parse_region_verdict(
            {"verdict": "confirmed", "boundary": "perfectish",
             "confidence": 0.9}, region(), LABELS)
        assert v.boundary == "unknown"
        assert v.verdict == "confirmed"
        assert v.flagged is False

    def test_every_verdict_it_can_produce_is_in_the_vocabulary(self):
        payloads = [
            {}, {"verdict": "confirmed"}, {"verdict": "wrong_label"},
            {"verdict": "not_an_object", "confidence": 0.9},
            {"verdict": "loose_boundary", "confidence": 0.9},
            {"verdict": "garbage"},
        ]
        for payload in payloads:
            v = parse_region_verdict(payload, region(), LABELS)
            assert v.verdict in CRITIQUE_VERDICTS


class TestParseMissed:
    def test_a_clean_missed_object(self):
        missed = parse_missed(
            {"missed": [{"label": "dog", "confidence": 0.9,
                         "bbox": {"x": 0.1, "y": 0.2, "width": 0.3,
                                  "height": 0.4},
                         "rationale": "A dog on the left."}]}, LABELS)
        assert len(missed) == 1
        assert missed[0].label == "dog"
        assert missed[0].bbox == (0.1, 0.2, 0.3, 0.4)

    def test_labels_outside_the_schema_are_dropped(self):
        missed = parse_missed(
            {"missed": [{"label": "aardvark", "confidence": 0.99}]}, LABELS)
        assert missed == []

    def test_low_confidence_entries_are_dropped(self):
        missed = parse_missed(
            {"missed": [{"label": "dog", "confidence": 0.1}]}, LABELS)
        assert missed == []

    def test_an_entry_with_no_box_is_kept(self):
        """'There is an unannotated dog somewhere' is still worth a look."""
        missed = parse_missed(
            {"missed": [{"label": "dog", "confidence": 0.9}]}, LABELS)
        assert len(missed) == 1 and missed[0].bbox is None

    def test_out_of_range_coordinates_are_clamped(self):
        missed = parse_missed(
            {"missed": [{"label": "dog", "confidence": 0.9,
                         "bbox": {"x": -3, "y": 0.2, "width": 8,
                                  "height": 0.4}}]}, LABELS)
        assert missed[0].bbox == (0.0, 0.2, 1.0, 0.4)

    def test_a_missing_or_malformed_list_is_empty_not_an_error(self):
        for raw in ({}, {"missed": "lots"}, "nonsense", None):
            assert parse_missed(raw, LABELS) == []


class TestSuppressCovered:
    def test_a_missed_object_over_an_existing_region_is_dropped(self):
        """Found live: an annotator who boxed a triangle but called it a circle
        was told twice — once as wrong_label, once as a missed triangle in the
        same place."""
        regions = [region(0, "cat", bbox=(100, 100, 100, 100))]
        missed = [MissedObject(label="dog", bbox=(0.2, 0.2, 0.2, 0.2),
                               confidence=0.9)]
        assert suppress_covered(missed, regions, 500, 500) == []

    def test_an_object_inside_a_much_larger_box_is_covered(self):
        """The second live finding, and the reason this uses containment rather
        than IoU. A box three times too large plainly contains the car, but its
        IoU with the car is ~0.12 — low precisely BECAUSE the box is loose — so
        an IoU test reported 'you missed this car' about an annotated car.
        """
        # A 240x180 box; the object inside it is 96x55.
        regions = [region(0, "car", bbox=(330, 180, 240, 180))]
        missed = [MissedObject(label="car", bbox=(380 / 640, 230 / 420,
                                                  96 / 640, 55 / 420),
                               confidence=0.9)]
        assert suppress_covered(missed, regions, 640, 420) == []

    def test_a_missed_object_much_larger_than_a_region_survives(self):
        """The asymmetry has to cut only one way: 'there is a whole bus here'
        when you annotated one wheel is a real finding, not a duplicate."""
        regions = [region(0, "car", bbox=(300, 300, 20, 20))]
        missed = [MissedObject(label="car", bbox=(0.4, 0.4, 0.4, 0.4),
                               confidence=0.9)]
        assert len(suppress_covered(missed, regions, 500, 500)) == 1

    def test_a_missed_object_elsewhere_survives(self):
        regions = [region(0, "cat", bbox=(0, 0, 50, 50))]
        missed = [MissedObject(label="dog", bbox=(0.7, 0.7, 0.2, 0.2),
                               confidence=0.9)]
        assert len(suppress_covered(missed, regions, 500, 500)) == 1

    def test_overlap_alone_decides_regardless_of_label(self):
        """A region already drawn is not missed, whatever either party calls it."""
        regions = [region(0, "car", bbox=(100, 100, 100, 100))]
        missed = [MissedObject(label="cat", bbox=(0.2, 0.2, 0.2, 0.2),
                               confidence=0.9)]
        assert suppress_covered(missed, regions, 500, 500) == []

    def test_an_unplaced_missed_object_is_kept(self):
        regions = [region(0, "cat", bbox=(100, 100, 100, 100))]
        missed = [MissedObject(label="dog", bbox=None, confidence=0.9)]
        assert len(suppress_covered(missed, regions, 500, 500)) == 1

    def test_nothing_annotated_means_nothing_to_suppress(self):
        missed = [MissedObject(label="dog", bbox=(0.1, 0.1, 0.2, 0.2))]
        assert suppress_covered(missed, [], 500, 500) == missed


class TestSummarize:
    def _verdicts(self):
        return [
            parse_region_verdict({"verdict": "confirmed", "confidence": 0.9},
                                 region(0), LABELS),
            parse_region_verdict({"verdict": "wrong_label",
                                  "suggested_label": "dog",
                                  "confidence": 0.9}, region(1), LABELS),
            parse_region_verdict({"verdict": "uncertain"}, region(2), LABELS),
        ]

    def test_counts_partition_the_verdicts(self):
        s = summarize(self._verdicts())
        assert s.reviewed == 3
        assert s.confirmed + s.flagged + s.uncertain + s.errors == 3

    def test_an_error_is_not_a_flag(self):
        """A model that timed out has said nothing about the annotation."""
        from potato.ai.critique import CritiqueVerdict

        broken = CritiqueVerdict(index=0, label="cat", error="timeout")
        s = summarize([broken])
        assert s.errors == 1
        assert s.flagged == 0

    def test_skipped_regions_are_reported_rather_than_silent(self):
        s = summarize([], skipped=7)
        assert s.skipped == 7

    def test_the_caveat_is_always_present(self):
        assert summarize([]).caveat == CAVEAT
        assert "not ground truth" in CAVEAT


class TestPurity:
    def test_the_module_does_no_io(self):
        """The split exists so the judgement rules are testable without a
        model; an import of requests or PIL here would undo it."""
        import pathlib

        source = pathlib.Path("potato/ai/critique.py").read_text()
        for forbidden in ("import requests", "from PIL", "import flask",
                          "from flask", "open("):
            assert forbidden not in source, f"critique.py should not {forbidden}"
