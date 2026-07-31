"""
The dialogue span-offset contract.

Span offsets are produced in the browser against the rendered DOM and the
annotated substring is sliced back out on the server. That only works if both
sides agree on the *same string, character for character*.

These tests pin the two halves together:

* ``DialogueDisplay.render()`` — emits the markup the browser measures.
* ``reconstruct_dialogue_dom_text()`` — reproduces it on the server.

They simulate the browser by stripping tags from the rendered HTML with the same
skip rules ``shouldSkipForOffsets()`` applies in ``static/span-core.js``. That is
not a substitute for the Selenium coverage, but it catches the whole class of
drift in milliseconds — and this file exists because there was previously no test
here at all, while the two sides had silently diverged: the server collapsed all
whitespace to single spaces and the client deliberately did not normalize, so
every dialogue span was sliced a few characters further off with each turn.
"""

from html.parser import HTMLParser

import pytest

from potato.server_utils.displays.base import (
    TURN_SEPARATOR,
    reconstruct_dialogue_dom_text,
)
from potato.server_utils.displays.dialogue_display import DialogueDisplay

#: Container subtrees excluded from the offset basis. Mirrors
#: ``UnifiedPositioningStrategy.shouldSkipForOffsets`` in static/span-core.js.
SKIPPED_CLASSES = (
    "turn-anno-slot",
    "per-turn-rating",
    "per-turn-rating-group",
    "span-overlays-field",
    "span-link-simple-arcs",
    "span-link-arcs-layer",
)


class _TextContentExtractor(HTMLParser):
    """Collect ``textContent`` of the ``.text-content`` element, browser-style.

    A real parser rather than regexes because element nesting is what decides
    both which subtree is the span container and which subtrees are skipped —
    exactly the questions the browser answers by walking the DOM.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self._depth = 0          # nesting depth inside .text-content
        self._skip_depth = 0     # nesting depth inside a skipped subtree

    @staticmethod
    def _classes(attrs):
        for name, value in attrs:
            if name == "class":
                return (value or "").split()
        return []

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        if self._depth:
            self._depth += 1
            if self._skip_depth:
                self._skip_depth += 1
            elif any(c in SKIPPED_CLASSES for c in classes):
                self._skip_depth = 1
        elif "text-content" in classes:
            self._depth = 1

    def handle_endtag(self, tag):
        if not self._depth:
            return
        if self._skip_depth:
            self._skip_depth -= 1
        self._depth -= 1

    def handle_data(self, data):
        if self._depth and not self._skip_depth:
            self.chunks.append(data)

    @property
    def text(self):
        return "".join(self.chunks)


def browser_text_content(html_str):
    """The ``textContent`` a browser would report for the span container.

    Applies the same skip rules ``shouldSkipForOffsets()`` does, and performs no
    whitespace normalization — the client deliberately does none either.
    """
    parser = _TextContentExtractor()
    parser.feed(html_str)
    return parser.text


def render(data, **display_options):
    return DialogueDisplay().render(
        {
            "key": "conversation",
            "span_target": True,
            "display_options": display_options,
        },
        data,
    )


SIMPLE = [
    {"speaker": "alice", "text": "Should we rename this article?"},
    {"speaker": "bob", "text": "The current title is not common usage."},
]

THREADED = [
    {"id": "m1", "speaker": "ana", "text": "Should we deprecate v1?", "timestamp": 1000},
    {"id": "m2", "speaker": "ben", "text": "Yes, with a migration window.",
     "reply_to": "m1", "timestamp": 4600, "meta": {"score": 0.5}},
    {"id": "m3", "speaker": "cy", "text": "Three months is far too aggressive.",
     "reply_to": "m2", "timestamp": 8200, "meta": {"score": 0.9}},
    {"id": "m4", "speaker": "ben", "text": "They have had two years of warning.",
     "reply_to": "m3", "timestamp": 11800, "meta": {"score": 0.2}},
]

MULTILINE = [
    {"speaker": "alice", "text": "== Section header ==\n\nWith a blank line above."},
    {"speaker": "bob", "text": "Short reply."},
]


class TestServerMatchesBrowser:
    """The core invariant, across every display option combination."""

    @pytest.mark.parametrize(
        "data,options",
        [
            (SIMPLE, {}),
            (SIMPLE, {"show_turn_numbers": True}),
            (THREADED, {}),
            (THREADED, {"show_turn_numbers": True}),
            (THREADED, {"indent_replies": True}),
            (THREADED, {"indent_replies": True, "show_timestamps": True}),
            (THREADED, {"indent_replies": True, "show_timestamps": True,
                        "turn_meta_fields": ["score"], "show_turn_numbers": True}),
            (THREADED, {"show_timestamps": True, "timestamp_format": "absolute"}),
            (MULTILINE, {}),
            (MULTILINE, {"show_turn_numbers": True}),
        ],
    )
    def test_reconstruction_is_byte_identical(self, data, options):
        rendered = browser_text_content(render(data, **options))
        server = reconstruct_dialogue_dom_text(
            data, show_turn_numbers=options.get("show_turn_numbers", False)
        )
        assert rendered == server

    def test_multiline_turn_text_is_not_collapsed(self):
        """The old implementation flattened these newlines; the browser keeps them."""
        server = reconstruct_dialogue_dom_text(MULTILINE)
        assert "\n\n" in server
        assert server == browser_text_content(render(MULTILINE))

    def test_turns_are_separated_by_the_declared_separator(self):
        server = reconstruct_dialogue_dom_text(SIMPLE)
        assert TURN_SEPARATOR in server
        assert server.count(TURN_SEPARATOR) == len(SIMPLE) - 1


class TestOffsetsSliceTheRightText:
    """What actually matters: offsets from one side slice correctly on the other."""

    @pytest.mark.parametrize(
        "phrase",
        ["Should we deprecate v1?", "far too aggressive", "two years of warning", "ben:"],
    )
    def test_phrase_offsets_agree(self, phrase):
        options = {"indent_replies": True, "show_timestamps": True,
                   "turn_meta_fields": ["score"], "show_turn_numbers": True}
        browser = browser_text_content(render(THREADED, **options))
        server = reconstruct_dialogue_dom_text(THREADED, show_turn_numbers=True)

        start = browser.index(phrase)
        end = start + len(phrase)
        # The browser's offsets, applied to the server's string.
        assert server[start:end] == phrase

    def test_drift_does_not_accumulate_over_a_long_conversation(self):
        """The old bug was proportional to turn count — check the last turn."""
        data = [
            {"speaker": f"user{i}", "text": f"Message number {i} in the thread."}
            for i in range(40)
        ]
        browser = browser_text_content(render(data, show_turn_numbers=True))
        server = reconstruct_dialogue_dom_text(data, show_turn_numbers=True)
        assert browser == server

        phrase = "Message number 39 in the thread."
        start = browser.index(phrase)
        assert server[start:start + len(phrase)] == phrase


class TestSkippedSubtreesDoNotShiftOffsets:
    def test_turn_annotation_slots_are_excluded(self):
        schemes = [{
            "name": "turn_problems",
            "annotation_type": "multiselect",
            "labels": ["personal_attack", "condescension"],
            "description": "Problems in this comment",
            "turn_binding": {},
        }]
        with_slots = DialogueDisplay().render(
            {"key": "conversation", "span_target": True, "_turn_schemes": schemes,
             "display_options": {"show_turn_numbers": True}},
            THREADED,
        )
        without = render(THREADED, show_turn_numbers=True)

        # The widget text is in the markup...
        assert "condescension" in with_slots
        # ...but contributes nothing to the offset basis.
        assert browser_text_content(with_slots) == browser_text_content(without)
        assert browser_text_content(with_slots) == reconstruct_dialogue_dom_text(
            THREADED, show_turn_numbers=True
        )

    def test_legacy_per_turn_ratings_are_excluded(self):
        """Regression: .per-turn-rating used to shift every subsequent offset."""
        rated = DialogueDisplay().render(
            {"key": "conversation", "span_target": True,
             "display_options": {
                 "show_turn_numbers": True,
                 "per_turn_ratings": {
                     "speakers": ["ben"],
                     "scheme": {"min": 1, "max": 3},
                     "schema_name": "quality",
                 },
             }},
            THREADED,
        )
        assert "per-turn-rating" in rated
        assert browser_text_content(rated) == reconstruct_dialogue_dom_text(
            THREADED, show_turn_numbers=True
        )


class TestThreadingChromeIsInvisibleToOffsets:
    """Indentation, timestamps and metadata chips are pseudo-element content."""

    def test_chrome_values_never_appear_in_the_offset_basis(self):
        html_out = render(
            THREADED,
            indent_replies=True,
            show_timestamps=True,
            timestamp_format="absolute",
            turn_meta_fields=["score"],
        )
        text = browser_text_content(html_out)
        assert "score:" not in text
        assert "depth" not in text
        assert "1970-" not in text

    def test_chrome_is_present_as_attributes(self):
        html_out = render(
            THREADED, indent_replies=True, show_timestamps=True,
            turn_meta_fields=["score"],
        )
        assert 'data-depth="2"' in html_out
        assert "data-turn-timestamp=" in html_out
        assert "data-turn-meta-chips=" in html_out
