"""
A hex color in the first column deleted the keyword.

Audit 27. `_parse_keyword_highlight_entries` drops any line starting with `#`
as a comment, and it does that on the raw text before the CSV is parsed, so it
cannot tell a comment from a data row whose first cell is `#ffcc00`:

    color,keyword,label
    #ffcc00,latch,Defect      -> 0 entries

    color,keyword,label
    red,latch,Defect          -> 1 entry

The header is recognized either way -- the reported shape is "delimited with a
header (color, keyword, label)" in both -- so this is not header detection, and
column order is not the problem. Every ordering that puts a keyword or label
first works; the two that put a hex color first do not.

That matters because hex is the natural way to write a color and `color` first
is an ordinary spreadsheet layout. The author gets "Loaded 0 keyword highlight
patterns", which is exactly the failure the multi-shape parsing was written to
prevent -- a file that reads as empty rather than as unreadable -- reappearing
one layer down.

Worse without a header, where the whole file disappears and the reported shape
is literally "empty", indistinguishable from a file with nothing in it.
"""

import pytest

from potato.flask_server import _parse_keyword_highlight_entries as parse


class TestHexColorInTheFirstColumn:

    def test_a_hex_color_first_does_not_delete_the_row(self):
        entries, fmt = parse(
            "color,keyword,label\n#ffcc00,latch,Defect\n", "kw.csv")
        assert len(entries) == 1, (entries, fmt)
        assert entries[0]["word"] == "latch"
        assert entries[0]["label"] == "Defect"
        assert entries[0]["color"] == "#ffcc00"

    def test_a_named_color_first_still_works(self):
        """The control. This one always worked, which is what made the
        failure look like a color problem rather than a comment problem."""
        entries, _ = parse(
            "color,keyword,label\nred,latch,Defect\n", "kw.csv")
        assert len(entries) == 1
        assert entries[0]["color"] == "red"

    def test_hex_and_named_rows_in_one_file_both_survive(self):
        """Only `ridge` came back before, so the file looked partly loaded --
        the shape of failure an author is least likely to notice."""
        entries, _ = parse(
            "color,keyword\n#ffcc00,latch\nred,ridge\n", "kw.csv")
        assert {e["word"] for e in entries} == {"latch", "ridge"}, entries

    def test_a_headerless_file_of_hex_rows_is_not_reported_as_empty(self, caplog):
        """`fmt == "empty"` is the one report an author cannot act on.

        It says the file had nothing in it, and the whole file had been eaten
        as comments. The rows survive now and are read positionally, which is
        the documented no-header contract: without a header there is nothing
        to say the first column is a color, and guessing would surprise anyone
        whose keywords genuinely start with `#`. The warning is what tells the
        author to add the header.
        """
        with caplog.at_level("WARNING"):
            entries, fmt = parse("#ffcc00,latch\n#00aaff,ridge\n", "kw.csv")
        assert fmt == "delimited, no header", (entries, fmt)
        assert len(entries) == 2, entries
        assert any("no recognised header" in record.message
                   for record in caplog.records), caplog.records

    def test_a_real_comment_is_still_a_comment(self):
        """The control in the other direction. Comments have to keep working,
        including one that starts with a word made of hex letters."""
        entries, _ = parse(
            "# my keywords\nkeyword,label\nlatch,Defect\n", "kw.csv")
        assert [e["word"] for e in entries] == ["latch"], entries

        entries, _ = parse(
            "# deadbeef notes here\nkeyword,label\nlatch,Defect\n", "kw.csv")
        assert [e["word"] for e in entries] == ["latch"], entries

    def test_a_hex_color_anywhere_else_was_never_affected(self):
        """Pinned so the fix cannot be mistaken for what already worked."""
        entries, _ = parse(
            "keyword,label,color\nlatch,Defect,#ffcc00\n", "kw.csv")
        assert entries[0]["color"] == "#ffcc00"


class TestARowThatDoesNotMatchItsHeader:

    def test_an_unquoted_rgb_value_is_reported_rather_than_mangled(self):
        """`rgb(255,0,0)` is three cells to a CSV reader.

        The row then has more cells than the header declares and the values
        slide, producing entries like `{'word': '0', 'label': '0)'}`. That is
        author error, but silent garbage is not a reasonable answer to it: the
        count mismatch is a precise, cheap signal.
        """
        # Color first is the ordering that produces the garbage: the extra
        # cells push the keyword out of its column entirely.
        entries, _ = parse(
            "color,keyword,label\nrgb(255,0,0),latch,Defect\n", "kw.csv")
        assert all(e["word"] not in ("0", "0)", "255") for e in entries), entries
