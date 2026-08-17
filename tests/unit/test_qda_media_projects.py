"""
QDA Mode on a corpus that is not text.

Memos already worked anywhere — they are attached to an instance, not to a
character offset. Two other parts did not:

* the codebook reconciles a project's label options with the codes an annotator
  mints at runtime, but only for span / radio / multiselect option markup.
  Image, spatial and episode schemas render `.label-btn` drawing palettes, so a
  code minted in an image project could never be drawn with.
* search indexed `data.get(text_key) or item.get_text()`, and `get_text()`
  returns an item's first string value. A media corpus was a full-text index of
  its own filenames and ids.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CODEBOOK_JS = (ROOT / "potato" / "static" / "codebook.js").read_text()
SPAN_CORE_JS = (ROOT / "potato" / "static" / "span-core.js").read_text()


class TestDrawingPalettesGainMintedCodes:
    def test_the_reconciler_handles_label_buttons(self):
        assert "reconcileLabelButtons" in CODEBOOK_JS

    def test_it_is_reached_from_the_dispatch(self):
        """A function nobody calls is the shape of half these findings."""
        dispatch = CODEBOOK_JS[CODEBOOK_JS.index("function reconcileForm("):]
        dispatch = dispatch[:600]
        assert ".label-btn" in dispatch
        assert "reconcileLabelButtons(form, labelBtn, labels)" in dispatch

    def test_a_cloned_button_carries_what_the_handler_reads(self):
        """The delegated click handler reads dataset.label and dataset.color."""
        body = CODEBOOK_JS[CODEBOOK_JS.index("function reconcileLabelButtons"):]
        body = body[:1600]
        assert "node.dataset.label" in body
        assert "node.dataset.color" in body
        assert 'aria-pressed", "false"' in body

    def test_the_swatch_is_kept(self):
        body = CODEBOOK_JS[CODEBOOK_JS.index("function reconcileLabelButtons"):]
        body = body[:1600]
        assert "label-color-dot" in body
        # textContent would wipe the swatch element out of the button.
        assert "node.textContent =" not in body


class TestOneColourFunctionForEveryone:
    def test_the_hash_lives_in_one_place(self):
        assert "window.potatoPaletteColor = paletteColorFor" in SPAN_CORE_JS
        # The class method must delegate rather than re-implement it.
        method = SPAN_CORE_JS[SPAN_CORE_JS.index("    paletteColorFor(label) {"):]
        method = method[:200]
        assert "return paletteColorFor(label);" in method

    def test_the_codebook_uses_it(self):
        assert "window.potatoPaletteColor" in CODEBOOK_JS

    def test_the_codebook_still_works_without_it(self):
        """An image-only page might not have a span manager instantiated."""
        body = CODEBOOK_JS[CODEBOOK_JS.index("function paletteTriple"):]
        body = body[:600]
        assert 'return ""' in body


class TestSearchDoesNotIndexIds:
    def rows(self, items, config=None):
        import potato.search.service as service

        class Item:
            def __init__(self, data):
                self._data = data

            def get_data(self):
                return self._data

            def get_text(self):
                for value in self._data.values():
                    if isinstance(value, str):
                        return value
                return ""

        class ISM:
            def get_instance_ids(self):
                return [d["id"] for d in items]

            def get_item(self, iid):
                return Item(next(d for d in items if d["id"] == iid))

        original = service.get_item_state_manager if hasattr(
            service, "get_item_state_manager") else None
        import potato.item_state_management as ism_module
        saved = ism_module.get_item_state_manager
        ism_module.get_item_state_manager = lambda: ISM()
        try:
            return list(service._rows_from_item_state(
                config or {"item_properties": {"text_key": "text"}}))
        finally:
            ism_module.get_item_state_manager = saved

    def test_media_only_items_are_skipped(self):
        rows = self.rows([{"id": "img_01", "image_url": "media/cat.jpg"},
                          {"id": "img_02", "image_url": "media/dog.png"}])
        assert rows == []

    def test_text_items_are_still_indexed(self):
        rows = self.rows([{"id": "t1", "text": "the clinic was closed"}])
        assert rows == [("t1", "the clinic was closed")]

    def test_a_caption_is_indexed_when_there_is_no_text_key(self):
        """Real text about a media item is worth finding."""
        rows = self.rows([{"id": "img_01", "image_url": "media/cat.jpg",
                           "caption": "a tabby asleep on a windowsill"}])
        assert rows == [("img_01", "a tabby asleep on a windowsill")]

    def test_a_configured_text_key_still_wins(self):
        rows = self.rows(
            [{"id": "x", "utterance": "hello there", "caption": "ignored"}],
            config={"item_properties": {"text_key": "utterance"}})
        assert rows == [("x", "hello there")]

    def test_a_mixed_corpus_indexes_only_what_has_text(self):
        rows = self.rows([{"id": "a", "text": "spoken words"},
                          {"id": "b", "image_url": "b.png"},
                          {"id": "c", "text": "more words"}])
        assert [r[0] for r in rows] == ["a", "c"]
