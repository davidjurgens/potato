"""
The client's fallback span palette must match the server's.

Codes minted at runtime are not in /api/colors, so the client colours them
itself. If the two palettes drift, a code's colour changes the moment it stops
being a runtime code — the same label would look one way while being minted and
another way after the next server render, which is worse than either colour on
its own.

This is the "no duplicated value lists" convention (CLAUDE.md #4/#9) applied to
a list that genuinely has to exist twice, because one copy runs in Python and
the other in the browser.
"""

import re
from pathlib import Path

from potato.server_utils.schemas.span import SPAN_COLOR_PALETTE

CLIENT = Path(__file__).resolve().parents[2] / "potato" / "static" / "span-core.js"


def _client_palette():
    """The FALLBACK_PALETTE literal out of span-core.js."""
    source = CLIENT.read_text()
    match = re.search(
        r"static FALLBACK_PALETTE\s*=\s*\[(.*?)\];", source, re.S)
    assert match, "SpanManager.FALLBACK_PALETTE not found in span-core.js"
    return re.findall(r"'(\([^']*\))'", match.group(1))


class TestPaletteParity:
    def test_the_client_palette_matches_the_server_palette(self):
        assert _client_palette() == SPAN_COLOR_PALETTE, (
            "span-core.js FALLBACK_PALETTE has drifted from "
            "potato/server_utils/schemas/span.py SPAN_COLOR_PALETTE"
        )

    def test_the_palette_is_not_empty(self):
        """A modulo against an empty list is a crash, not a fallback."""
        assert len(_client_palette()) > 1

    def test_every_entry_is_an_rgb_triple(self):
        """getSpanColor turns "(r, g, b)" into rgba(...) by string surgery."""
        for entry in _client_palette():
            assert re.fullmatch(r"\(\d{1,3}, \d{1,3}, \d{1,3}\)", entry), entry
