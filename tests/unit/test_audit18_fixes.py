"""Regressions for the audit-18 findings."""

import re
import html as html_module

import pytest


TURNS = [
    {"speaker": "Customer", "text": "My laptop arrived cracked."},
    {"speaker": "Agent", "text": "I am sorry to hear that."},
    {"speaker": "Customer", "text": "I would like a replacement."},
    {"speaker": "Agent", "text": "I can refund it today or send a new one."},
]


def _dom_text(field_config):
    """The textContent a browser would measure for a rendered dialogue field.

    Mirrors `shouldSkipForOffsets()` in static/span-core.js: the per-turn
    annotation slots and rating widgets are excluded from the offset basis.
    """
    from potato.server_utils.displays.dialogue_display import DialogueDisplay

    html = DialogueDisplay().render(field_config, TURNS)
    for css_class in ("turn-anno-slot", "per-turn-rating-group", "per-turn-rating"):
        html = re.sub(r'<div class="[^"]*%s[^"]*".*?</div>' % css_class, "",
                      html, flags=re.S)
    return html_module.unescape(re.sub(r"<[^>]+>", "", html)).strip()


def _server_anchor(field_config):
    from potato.server_utils.displays.base import (
        reconstruct_dialogue_dom_text, resolve_display_options)

    options = resolve_display_options(field_config)
    return reconstruct_dialogue_dom_text(
        TURNS,
        speaker_key=options.get("speaker_key", "speaker"),
        text_key=options.get("text_key", "text"),
        show_turn_numbers=options.get("show_turn_numbers", False),
    )


# --------------------------------------------------------------- finding 1 --
# The display honoured the flat option; the export, /api/spans and the keyword
# scan still read only display_options, so the two anchored to different
# strings and every dialogue span exported shifted by the numbering width.

class TestBothHalvesAnchorToOneString:
    FIELDS = {
        "flat": {"key": "turns", "type": "dialogue", "show_turn_numbers": True},
        "nested": {"key": "turns", "type": "dialogue",
                   "display_options": {"show_turn_numbers": True}},
        "off": {"key": "turns", "type": "dialogue"},
    }

    @pytest.mark.parametrize("shape", ["flat", "nested", "off"])
    def test_the_server_anchor_equals_the_rendered_dom_text(self, shape):
        field_config = self.FIELDS[shape]
        assert _server_anchor(field_config) == _dom_text(field_config)

    def test_numbering_actually_changes_the_anchor(self):
        """Otherwise the test above would pass on a no-op."""
        assert _server_anchor(self.FIELDS["flat"]).startswith("[1] Customer: ")
        assert _server_anchor(self.FIELDS["off"]).startswith("Customer: ")

    @pytest.mark.parametrize("shape", ["flat", "nested"])
    def test_the_export_slices_what_the_annotator_marked(self, shape):
        from potato.export.base import ExportContext

        field_config = self.FIELDS[shape]
        anchor = _server_anchor(field_config)
        start = anchor.index("can refun")
        context = ExportContext(
            config={"item_properties": {"text_key": "turns"},
                    "instance_display": {"fields": [field_config]}},
            annotations=[], items={"M01": {"id": "M01", "turns": TURNS}},
            schemas=[], output_dir=".")
        assert context.covered_text(
            "M01", {"start": start, "end": start + 9,
                    "target_field": "turns"}) == "can refun"

    def test_every_anchor_side_reader_resolves_options_the_same_way(self):
        """One resolver, or the halves drift again."""
        import io
        for path in ("potato/export/base.py",
                     "potato/routes.py",
                     "potato/export/convokit_exporter.py"):
            source = io.open(path, encoding="utf-8").read()
            assert "resolve_display_options" in source, (
                f"{path} resolves display options its own way")


class TestResolveDisplayOptions:
    @staticmethod
    def _resolve(field_config):
        from potato.server_utils.displays.base import resolve_display_options
        return resolve_display_options(field_config)

    def test_flat_and_nested_agree(self):
        flat = self._resolve({"key": "t", "type": "dialogue",
                              "show_turn_numbers": True})
        nested = self._resolve({"key": "t", "type": "dialogue",
                                "display_options": {"show_turn_numbers": True}})
        assert flat["show_turn_numbers"] is nested["show_turn_numbers"] is True

    def test_nested_wins(self):
        assert self._resolve({
            "key": "t", "type": "dialogue", "show_turn_numbers": True,
            "display_options": {"show_turn_numbers": False},
        })["show_turn_numbers"] is False

    def test_the_declared_default_is_applied(self):
        assert self._resolve(
            {"key": "t", "type": "dialogue"})["show_turn_numbers"] is False

    def test_an_unknown_display_type_still_resolves(self):
        """A plugin display or a stale config must not raise mid-slice."""
        assert self._resolve({"key": "t", "type": "not-a-display",
                              "show_turn_numbers": True})["show_turn_numbers"] is True


# --------------------------------------------------------------- finding 2 --
# mean_jaccard paired users positionally, so one missing answer misaligned
# every later item.

class TestMeanJaccardPairsByItem:
    ITEMS = [f"M{n:02d}" for n in range(1, 9)]
    ANSWERS = [{"a"}, {"b"}, {"c"}, {"d"}, {"e"}, {"f"}, {"g"}, {"h"}]

    def _by_item(self):
        full = {iid: frozenset(s) for iid, s in zip(self.ITEMS, self.ANSWERS)}
        short = {k: v for k, v in full.items() if k not in ("M01", "M02")}
        return {"r1": full, "r2": full, "r3": short}

    def test_identical_answers_score_one_despite_a_missing_answer(self):
        from potato.server_utils.iaa import multilabel
        assert multilabel.mean_jaccard(self._by_item()) == 1.0

    def test_the_positional_shape_was_the_bug(self):
        """Kept as the specimen: it compares two different items."""
        from potato.server_utils.iaa import multilabel
        positional = {u: list(d.values()) for u, d in self._by_item().items()}
        assert multilabel.mean_jaccard(positional) < 1.0

    def test_the_dispatcher_passes_the_item_keyed_shape(self):
        from potato.server_utils.iaa.dispatcher import _aggregate_multilabel

        rows = {}
        for iid, answer in zip(self.ITEMS, self.ANSWERS):
            per_user = {"r1": sorted(answer), "r2": sorted(answer),
                        "r3": sorted(answer)}
            if iid in ("M01", "M02"):
                del per_user["r3"]
            rows[iid] = per_user
        result = _aggregate_multilabel(rows)
        assert result["mean_jaccard"] == 1.0, (
            "every answer given was identical, so agreement is 1.0")
        assert result["n_annotators"] == 3

    def test_only_shared_items_are_compared(self):
        """A pairwise figure means "where both answered"."""
        from potato.server_utils.iaa import multilabel
        assert multilabel.mean_jaccard({
            "r1": {"M01": frozenset({"a"}), "M02": frozenset({"b"})},
            "r2": {"M01": frozenset({"a"})},
        }) == 1.0

    def test_disagreement_still_scores_zero(self):
        from potato.server_utils.iaa import multilabel
        assert multilabel.mean_jaccard({
            "r1": {"M01": frozenset({"a"})},
            "r2": {"M01": frozenset({"z"})},
        }) == 0.0

    def test_one_user_is_nan(self):
        from potato.server_utils.iaa import multilabel
        result = multilabel.mean_jaccard({"r1": {"M01": frozenset({"a"})}})
        assert result != result
