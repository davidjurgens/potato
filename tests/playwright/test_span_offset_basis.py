"""
Playwright guards for the span character-offset BASIS in turn-based displays.

Span offsets are produced by ``UnifiedPositioningStrategy.getOffsetsFromSelection()``,
which sums RAW ``node.textContent.length`` over the span-target container while
skipping non-transcript chrome. Every consumer that slices text by those offsets
(``getCanonicalText()``, the span-link builder's snippet, the bounds check in
``createSpanWithAlgorithm()``) must index the SAME string, or it silently returns
text from the wrong place.

Two real bugs motivated these tests, both invisible in flat single-field tasks and
both only reproducible in a browser:

  1. Per-turn rating slots render INSIDE the span-target container, and
     ``turn-annotations.js`` writes dynamic text into them. That text counted
     toward offsets, so its length differed between save and reload and every
     span after an earlier turn's slot restored onto the wrong text.

  2. ``getCanonicalText()`` and the link builder whitespace-COLLAPSED the text
     before slicing it, while the offsets were measured against the RAW text.
     Bubble markup carries newlines/indentation between elements, so the
     collapsed string was shorter and every snippet was shifted by the
     whitespace preceding the span.

Run:  pytest tests/playwright/test_span_offset_basis.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
)
from tests.playwright.test_base import BasePlaywrightTest


# Long turns so a selection lands well past the first rating slot, which is where
# both bugs manifested. Turn 0 is intentionally boring: spans there were always
# correct (nothing precedes them) and so hid the bug.
TURNS = [
    {
        "turn_id": "t0",
        "speaker": "host",
        "start": 0.0,
        "end": 4.0,
        "text": (
            "Welcome to the show. Today we are talking about how coaching changes "
            "the way people approach their own work and their teams."
        ),
    },
    {
        "turn_id": "t1",
        "speaker": "guest",
        "start": 4.0,
        "end": 8.0,
        "text": (
            "Thanks for having me. I have been doing this for a decade now and it "
            "still surprises me how much a single conversation can shift things."
        ),
    },
    {
        "turn_id": "t2",
        "speaker": "host",
        "start": 8.0,
        "end": 12.0,
        "text": (
            "Do you believe that coaching has enhanced your life in ways you did "
            "not expect when you first started out on this particular path?"
        ),
    },
    {
        "turn_id": "t3",
        "speaker": "guest",
        "start": 12.0,
        "end": 16.0,
        "text": (
            "Absolutely, for sure. And I appreciate you asking that, because the "
            "honest answer is that it reshaped how I listen to other people."
        ),
    },
]


@pytest.fixture(scope="module")
def basis_server():
    test_dir = create_test_directory("pw_span_offset_basis")
    # Two instances: navigating away and back needs somewhere to go, and a
    # single-instance task redirects off /annotate once its only item is saved.
    data = [
        {"id": "ob_001", "title": "Episode one", "conversation": {"audio": "", "turns": TURNS}},
        {"id": "ob_002", "title": "Episode two", "conversation": {"audio": "", "turns": TURNS}},
    ]
    data_file = create_test_data_file(test_dir, data, filename="basis_data.jsonl")

    schemes = [
        # A turn_level scheme is REQUIRED to reproduce bug #1: it injects a
        # .turn-anno-slot into every turn, inside the span-target container.
        {
            "annotation_type": "radio",
            "name": "turn_category",
            "description": "Category of this turn",
            "labels": ["claim", "question", "answer", "aside"],
            "turn_level": True,
            "turn_binding": {"field": "conversation"},
        },
        {
            "annotation_type": "span",
            "name": "highlights",
            "description": "Highlight spans",
            "target_field": "conversation",
            "labels": ["question", "answer"],
        },
        {
            "annotation_type": "span_link",
            "name": "qa_links",
            "description": "Link an answer to its question",
            "span_schema": "highlights",
            "link_types": [
                {
                    "name": "answers",
                    "directed": True,
                    "allowed_source_labels": ["answer"],
                    "allowed_target_labels": ["question"],
                }
            ],
        },
    ]
    instance_display = {
        "layout": {"direction": "vertical", "gap": "12px"},
        "fields": [
            {"key": "title", "type": "text", "label": "Episode"},
            {
                "key": "conversation",
                "type": "audio_dialogue",
                "label": "Transcript",
                "span_target": True,
                "display_options": {
                    "scroll_height": "400px",
                    "speakers": [
                        {"id": "host", "name": "Host", "color": "#7c3aed", "side": "left"},
                        {"id": "guest", "name": "Guest", "color": "#059669", "side": "right"},
                    ],
                },
            },
        ],
    }
    config_file = create_test_config(
        test_dir,
        schemes,
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "title"},
        additional_config={"instance_display": instance_display},
    )
    srv = FlaskTestServer(port=find_free_port(), debug=False, config_file=config_file)
    if not srv.start():
        pytest.fail("Failed to start span-offset-basis Playwright server")
    yield srv
    srv.stop()


# Selects a phrase inside a given turn and fires the real mouseup handler, i.e.
# exactly what a user drag does. Returns the selected text so tests can assert
# against ground truth rather than against another derived value.
_MAKE_SPAN_JS = """
([turnIdx, labelId]) => {
    document.getElementById(labelId).click();
    const turn = [...document.querySelectorAll('.ad-turn')][turnIdx];
    const textEl = turn.querySelector('.ad-text');
    let tn = null;
    const rec = (n) => {
        if (tn) return;
        if (n.nodeType === 3 && n.textContent.trim().length > 40) { tn = n; return; }
        if (n.nodeType === 1) for (const c of n.childNodes) rec(c);
    };
    rec(textEl);
    if (!tn) return null;
    const raw = tn.textContent;
    const s = raw.indexOf(' ', 5) + 1;
    const e = raw.indexOf(' ', s + 20);
    if (s < 1 || e < 0) return null;
    const range = document.createRange();
    range.setStart(tn, s);
    range.setEnd(tn, e);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const r = range.getBoundingClientRect();
    textEl.dispatchEvent(new MouseEvent('mouseup', {
        bubbles: true, cancelable: true,
        clientX: r.right, clientY: r.top + r.height / 2,
    }));
    return raw.slice(s, e);
}
"""


@pytest.mark.playwright
class TestSpanOffsetBasis(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_selector(".audio-dialogue", timeout=15000)
        page.wait_for_function(
            "() => window.spanManager && window.spanManager.fieldStrategies "
            "&& window.spanManager.fieldStrategies['conversation']",
            timeout=15000,
        )

    def _make_span(self, page, turn_idx, label_id):
        truth = page.evaluate(_MAKE_SPAN_JS, [turn_idx, label_id])
        assert truth, f"could not build a selection in turn {turn_idx}"
        page.wait_for_timeout(700)
        return truth

    # ---- bug #1: chrome inside the container must not shift offsets ----

    def test_turn_slot_text_is_excluded_from_offsets(self, page, basis_server):
        """Rating-slot text lives inside the span target but must not count."""
        self._open(page, basis_server)
        excluded = page.evaluate(
            """() => {
                const host = document.getElementById('text-content-conversation');
                const walk = (skip) => {
                    let s = '';
                    const rec = (n) => {
                        if (n.nodeType === 3) { s += n.textContent; return; }
                        if (n.nodeType !== 1) return;
                        if (skip && UnifiedPositioningStrategy.shouldSkipForOffsets(n)) return;
                        for (const c of n.childNodes) rec(c);
                    };
                    rec(host);
                    return s;
                };
                return { raw: walk(false).length, skipped: walk(true).length,
                         slots: document.querySelectorAll('.turn-anno-slot').length };
            }"""
        )
        # The fixture has a turn_level scheme, so slots must exist -- otherwise
        # this test would vacuously pass and guard nothing.
        assert excluded["slots"] == len(TURNS)
        assert excluded["raw"] > excluded["skipped"], (
            "rating-slot text is being counted toward span offsets; it will shift "
            "every span that follows a slot when its text changes on restore"
        )

    # ---- bug #2: the canonical text must BE the offset basis ----

    def test_canonical_text_is_the_offset_basis(self, page, basis_server):
        """getCanonicalText() must return the exact string offsets index into."""
        self._open(page, basis_server)
        result = page.evaluate(
            """() => {
                const strat = window.spanManager.fieldStrategies['conversation'];
                let basis = '';
                const rec = (n) => {
                    if (n.nodeType === 3) { basis += n.textContent; return; }
                    if (n.nodeType !== 1) return;
                    if (UnifiedPositioningStrategy.shouldSkipForOffsets(n)) return;
                    for (const c of n.childNodes) rec(c);
                };
                rec(strat.container);
                const canon = strat.getCanonicalText();
                return { basisLen: basis.length, canonLen: canon.length, equal: basis === canon };
            }"""
        )
        assert result["equal"], (
            "getCanonicalText() != the raw offset basis "
            f"(basis={result['basisLen']} canonical={result['canonLen']}). "
            "Slicing it by span offsets returns shifted text, and the bounds "
            "check in createSpanWithAlgorithm() will reject spans near the end."
        )

    def test_link_builder_snippet_matches_selected_text(self, page, basis_server):
        """The snippet shown in the Link Builder must be the text the user picked."""
        self._open(page, basis_server)
        truth = self._make_span(page, 2, "highlights_question")

        shown = page.evaluate(
            """() => {
                const mgr = Object.values(window.spanLinkManagers || {})[0];
                const ov = document.querySelector('.span-overlay-pure');
                return mgr && ov ? mgr.getSpanText(ov) : null;
            }"""
        )
        assert shown == truth, f"link builder shows {shown!r}, user selected {truth!r}"

    # ---- the end-to-end behavior both bugs broke ----

    def test_span_and_link_survive_reload_on_the_same_text(self, page, basis_server):
        """A span past a rating slot must restore onto the text it was drawn on."""
        self._open(page, basis_server)
        q_truth = self._make_span(page, 2, "highlights_question")
        a_truth = self._make_span(page, 3, "highlights_answer")

        # Rate an EARLIER turn: this is the mutation that used to change the
        # offset basis between save and reload.
        page.evaluate(
            """() => {
                const slot = document.querySelectorAll('.turn-anno-slot')[0];
                slot.querySelector('.ta-chip[data-value="question"]').click();
            }"""
        )
        page.evaluate("() => window.saveAnnotations && window.saveAnnotations()")
        page.wait_for_timeout(1800)

        # Navigate away and back rather than refreshing (browsers cache form state).
        page.click("#next-btn")
        page.wait_for_selector(".audio-dialogue", timeout=10000)
        page.click("#prev-btn")
        page.wait_for_selector(".audio-dialogue", timeout=10000)
        page.wait_for_function(
            "() => document.querySelectorAll('.span-overlay-pure').length >= 2",
            timeout=15000,
        )

        restored = page.evaluate(
            """() => {
                const strat = window.spanManager.fieldStrategies['conversation'];
                const canon = strat.getCanonicalText();
                return [...document.querySelectorAll('.span-overlay-pure')].map(o => ({
                    id: o.dataset.annotationId,
                    textAtOffsets: canon.slice(+o.dataset.start, +o.dataset.end),
                }));
            }"""
        )
        by_label = {r["id"].split("_")[1]: r["textAtOffsets"] for r in restored}
        assert by_label.get("question") == q_truth, (
            f"question span restored onto {by_label.get('question')!r}, drawn on {q_truth!r}"
        )
        assert by_label.get("answer") == a_truth, (
            f"answer span restored onto {by_label.get('answer')!r}, drawn on {a_truth!r}"
        )
