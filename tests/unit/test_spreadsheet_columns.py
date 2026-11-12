"""A spreadsheet shows every column its data has.

Columns came from row 0 alone and every row was projected onto them:

    headers = list(data[0].keys()) if data else []
    rows = [[row.get(h, "") for h in headers] for row in data]

A key that first appeared later was dropped, values and all, with no warning
and no log line. The shape this hits is a JSON-lines export that omits a field
when it is empty -- what most APIs and `to_json(orient="records")` produce.

Measured on a three-row table whose second row carried a key the first did not:

    {"country":"Peru","year":2024,"cases":8,
     "RETRACTION_NOTE":"FIGURES WITHDRAWN"}

The rendered table read country/year/cases over all three rows, well-formed,
and "FIGURES WITHDRAWN" was not inside the `<table>` at all -- on a scheme
asking whether the table was usable as published. Three rows is the worst case
for noticing: with row 0 sparse you lose a column from every later row and the
table still looks complete.

The second finding is the list-of-lists branch, which set `headers = []`
unconditionally, so `show_headers: true` had nothing to act on and a CSV's
header line was rendered as data row 1. There was no way to supply a header
alongside a list-of-lists at all.

That one is opt-in rather than inferred. `show_headers` defaults to True, so
promoting row 0 automatically would turn the first data row of every existing
list-of-lists study into a header -- a wrong guess that silently removes a real
row from the data.
"""

import re

import pytest

from potato.server_utils.displays.registry import display_registry


RAGGED = [
    {"country": "Kenya", "year": 2024, "cases": 13},
    {"country": "Peru", "year": 2024, "cases": 8,
     "RETRACTION_NOTE": "FIGURES WITHDRAWN"},
    {"country": "Chad", "year": 2024, "cases": 21},
]

CSVISH = [["country", "year", "cases"],
          ["Kenya", 2024, 13],
          ["Peru", 2024, 8]]


def render(data, **display_options):
    field_config = {"type": "spreadsheet", "key": "t"}
    if display_options:
        field_config["display_options"] = display_options
    return display_registry.render("spreadsheet", field_config, data)


def headers(html):
    return [h for h in re.findall(r"<th[^>]*>([^<]*)</th>", html) if h.strip()]


class TestNoColumnIsDropped:

    def test_a_late_column_is_rendered(self):
        html = render(RAGGED)
        assert "RETRACTION_NOTE" in headers(html), (
            "a column that first appears in row 2 was dropped from the table")

    def test_its_value_is_rendered(self):
        """A header with no cell under it would be its own bug."""
        assert "FIGURES WITHDRAWN" in render(RAGGED)

    def test_the_row_0_columns_keep_their_order(self):
        assert headers(render(RAGGED))[:3] == ["country", "year", "cases"]

    def test_a_late_column_is_appended_not_interleaved(self):
        assert headers(render(RAGGED))[-1] == "RETRACTION_NOTE"

    def test_a_sparse_first_row_loses_nothing(self):
        """The worst case: row 0 has the fewest keys."""
        data = [{"a": 1}, {"a": 2, "b": 3}, {"a": 4, "b": 5, "c": 6}]
        assert headers(render(data)) == ["a", "b", "c"]

    def test_rows_missing_a_column_render_empty_rather_than_shifting(self):
        html = render([{"a": "A1"}, {"a": "A2", "b": "B2"}])
        assert "A1" in html and "B2" in html

    def test_the_columns_rows_shape_is_covered_too(self):
        """`{columns, rows: [{col: value}]}` took its keys from row 0 as well."""
        data = {"rows": [{"a": 1}, {"a": 2, "b": 3}]}
        assert headers(render(data)) == ["a", "b"]

    def test_an_explicit_columns_list_still_wins(self):
        """A config that names its columns is choosing them, including
        choosing to leave one out."""
        data = {"columns": ["a"], "rows": [{"a": 1}, {"a": 2, "b": 3}]}
        assert headers(render(data)) == ["a"]


class TestAListOfListsCanHaveAHeader:

    def test_the_first_row_becomes_the_header_when_asked(self):
        html = render(CSVISH, header_row=True)
        assert headers(html) == ["country", "year", "cases"], (
            "there was no way to supply a header alongside a list-of-lists")

    def test_the_header_row_is_no_longer_a_data_row(self):
        html = render(CSVISH, header_row=True)
        body = html.split("</thead>")[-1]
        assert body.count("<tr") == 2, "the header line stayed in the body too"

    def test_the_data_rows_survive(self):
        html = render(CSVISH, header_row=True)
        assert "Kenya" in html and "Peru" in html

    def test_the_default_is_unchanged(self):
        """`show_headers` defaults to True; promoting row 0 automatically would
        turn every existing list-of-lists study's first data row into a
        header."""
        html = render(CSVISH)
        assert headers(html) == []
        assert "country" in html, "row 0 must still be rendered as data"

    def test_an_empty_list_does_not_raise(self):
        assert render([], header_row=True) is not None

    def test_a_single_row_becomes_a_header_with_no_body(self):
        html = render([["a", "b"]], header_row=True)
        assert headers(html) == ["a", "b"]


class TestTheOptionIsDeclared:
    """An option the renderer reads but does not declare is invisible to
    `get_display_options`, which merges the declared defaults."""

    def test_header_row_is_in_optional_fields(self):
        from potato.server_utils.displays.spreadsheet_display import (
            SpreadsheetDisplay)

        assert "header_row" in SpreadsheetDisplay.optional_fields

    def test_it_defaults_to_off(self):
        from potato.server_utils.displays.spreadsheet_display import (
            SpreadsheetDisplay)

        assert SpreadsheetDisplay.optional_fields["header_row"] is False
