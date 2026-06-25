"""Round-trip + render guard for the codebook living-document parser.

The load-bearing invariant: blocks -> markdown -> blocks is a fixed point
over the *persisted* fields (block_type, custom_label, body_md). This
mirrors tests/unit/test_span_serialization_roundtrip.py — a drift guard so
a new block field can't silently vanish across a markdown round-trip.
"""

import pytest

from potato.codebook import markdown as md
from potato.codebook.blocks import BLOCK_TYPES


def _persisted(blocks):
    return [
        (b.get("block_type"), b.get("custom_label"), b.get("body_md"))
        for b in blocks
    ]


def _rt(blocks):
    """blocks -> markdown -> blocks, returning persisted-field tuples."""
    text = md.blocks_to_markdown(blocks)
    return _persisted(md.markdown_to_blocks(text))


class TestRoundTrip:
    def test_every_known_type_round_trips(self):
        blocks = [
            {"block_type": t, "custom_label": None,
             "body_md": f"body for {t}"}
            for t in BLOCK_TYPES if t != "custom"
        ]
        assert _rt(blocks) == _persisted(blocks)

    def test_custom_heading_preserved(self):
        blocks = [{
            "block_type": "custom",
            "custom_label": "Coder disagreement protocol",
            "body_md": "When two coders disagree, escalate.",
        }]
        assert _rt(blocks) == _persisted(blocks)

    def test_custom_heading_with_punctuation(self):
        blocks = [{
            "block_type": "custom",
            "custom_label": "Edge cases (rare!): what to do",
            "body_md": "Handle with care.",
        }]
        assert _rt(blocks) == _persisted(blocks)

    def test_empty_body_survives(self):
        blocks = [
            {"block_type": "definition", "custom_label": None, "body_md": ""},
            {"block_type": "use_when", "custom_label": None,
             "body_md": "non-empty"},
        ]
        assert _rt(blocks) == _persisted(blocks)

    def test_multiline_and_lists_in_body(self):
        body = "- mentions cost\n- mentions affordability\n\nSecond paragraph."
        blocks = [{"block_type": "use_when", "custom_label": None,
                   "body_md": body}]
        assert _rt(blocks) == _persisted(blocks)

    def test_kitchen_sink_fixed_point(self):
        blocks = [
            {"block_type": "short_def", "custom_label": None,
             "body_md": "One-line gloss."},
            {"block_type": "definition", "custom_label": None,
             "body_md": "A **detailed** definition with *emphasis*."},
            {"block_type": "use_when", "custom_label": None,
             "body_md": "- A\n- B"},
            {"block_type": "avoid_when", "custom_label": None,
             "body_md": "Never when X."},
            {"block_type": "example", "custom_label": None,
             "body_md": "> a quote"},
            {"block_type": "custom", "custom_label": "Provenance",
             "body_md": "from interview 3"},
        ]
        once = md.markdown_to_blocks(md.blocks_to_markdown(blocks))
        twice = md.markdown_to_blocks(md.blocks_to_markdown(once))
        assert _persisted(once) == _persisted(blocks)
        assert _persisted(twice) == _persisted(once)


class TestClassification:
    def test_aliases_classify(self):
        text = "### Inclusion\nuse it here\n\n### Exclusion\nnot here\n"
        blocks = md.markdown_to_blocks(text)
        assert blocks[0]["block_type"] == "use_when"
        assert blocks[0]["classified"] is True
        assert blocks[1]["block_type"] == "avoid_when"

    def test_case_and_hyphen_insensitive(self):
        text = "### USE-WHEN:\nx\n"
        blocks = md.markdown_to_blocks(text)
        assert blocks[0]["block_type"] == "use_when"

    def test_unknown_heading_is_custom_and_unclassified(self):
        text = "### Whatever Heading\nsome text\n"
        blocks = md.markdown_to_blocks(text)
        assert blocks[0]["block_type"] == "custom"
        assert blocks[0]["custom_label"] == "Whatever Heading"
        assert blocks[0]["classified"] is False

    def test_freeform_no_heading_becomes_definition_flagged(self):
        blocks = md.markdown_to_blocks("Just some pasted prose, no heading.")
        assert len(blocks) == 1
        assert blocks[0]["block_type"] == "definition"
        assert blocks[0]["classified"] is False
        assert "pasted prose" in blocks[0]["body_md"]


class TestRender:
    def test_basic_markdown_renders(self):
        out = md.render_markdown("# Title\n\nA **bold** and *italic* line.")
        assert "<h1>" in out and "Title" in out
        assert "<strong>bold</strong>" in out
        assert "<em>italic</em>" in out

    def test_lists_render(self):
        out = md.render_markdown("- one\n- two")
        assert "<ul>" in out and "<li>one</li>" in out

    def test_script_is_neutralized(self):
        out = md.render_markdown("hello <script>alert('x')</script> world")
        assert "<script>" not in out
        assert "alert" not in out or "&lt;script&gt;" in out

    def test_event_handler_attr_stripped(self):
        out = md.render_markdown("<img src=x onerror=alert(1)>")
        assert "onerror" not in out

    def test_link_renders_safely(self):
        out = md.render_markdown("see [docs](https://example.com)")
        assert '<a href="https://example.com"' in out

    def test_javascript_link_neutralized(self):
        out = md.render_markdown("[x](javascript:alert(1))")
        assert "javascript:" not in out
