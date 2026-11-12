"""The text span offsets index on the default (``text_key``) display.

The browser measures a span by walking the text nodes of ``#text-content``,
so an offset counts characters of the *rendered* text: the displayed text
after ``sanitize_html``, with tags contributing nothing and each entity
contributing the one character it decodes to. Three server consumers used to
slice something else:

* ``/api/spans`` stripped tags with a regex that also ate ``< y and y >`` in
  ``x < y and y > z``, and left ``&amp;`` five characters wide.
* the exporter sliced the raw data-file string, so a doubled space or an
  entity before a span shifted the exported words.
* the page renderer inserted highlight markup into the HTML at text offsets,
  which landed inside ``<b>`` and printed a stray ``>``.

All three now go through :func:`instance_dom_text` and :func:`dom_to_markup_offsets`.
Offsets are code points, as everywhere else on the wire.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List, Tuple

_CONTROL = re.compile(r'[\x00-\x1F\x7F]')
_HSPACE = re.compile(r'[ \t]+')


def normalize_display_text(text: str, highlight_linebreaks: bool = False) -> str:
    """What the default display does to a string before it is rendered.

    Control characters other than newline are removed, runs of spaces and
    tabs become one space, and the ends are trimmed. ``flask_server``'s
    ``get_displayed_text`` calls this, so the two cannot drift apart.
    """
    text = _CONTROL.sub(lambda m: m.group() if m.group() == '\n' else '', text)
    text = _HSPACE.sub(' ', text)
    text = text.strip()
    if highlight_linebreaks:
        text = text.replace("\n", "<br/>")
    return text


class _TextCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def markup_text(markup: str) -> str:
    """The text content of an HTML fragment, as a browser's textContent reads it."""
    collector = _TextCollector()
    collector.feed(markup)
    collector.close()
    return "".join(collector.parts)


def instance_dom_text(displayed: str) -> str:
    """The text the browser holds for already-displayed instance text.

    ``displayed`` is the output of ``get_displayed_text``. It is sanitized
    exactly as the template does, then read back as text.
    """
    from potato.server_utils.html_sanitizer import sanitize_html
    return markup_text(str(sanitize_html(displayed or "")))


_TOKEN = re.compile(r'<[^>]*>|&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);')


def dom_to_markup_offsets(markup: str) -> Tuple[List[int], List[int]]:
    """Where each text offset falls in sanitized markup.

    Returns ``(starts, ends)``, each of length ``len(text) + 1`` where ``text``
    is :func:`markup_text` of the markup. ``starts[i]`` is the markup index at
    which text character ``i`` begins, after any tags in front of it, which is
    where a span starting at ``i`` opens. ``ends[i]`` is the markup index just
    after character ``i - 1``, before any tags that follow it, which is where a
    span ending at ``i`` closes. The markup must come from ``sanitize_html``:
    there every ``<`` that is not a tag has been escaped.
    """
    starts: List[int] = []
    ends: List[int] = [0]
    pos = 0
    length = len(markup)
    while pos < length:
        m = _TOKEN.match(markup, pos)
        if m and m.group(0).startswith('<'):
            pos = m.end()
            continue
        if m:  # an entity: one or more characters of text
            width = len(markup_text(m.group(0))) or 1
            for k in range(width):
                starts.append(pos)
                ends.append(m.end() if k == width - 1 else pos)
            pos = m.end()
            continue
        starts.append(pos)
        ends.append(pos + 1)
        pos += 1
    starts.append(length)
    return starts, ends
