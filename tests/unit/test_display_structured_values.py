"""A dict on the page is JSON, not a Python repr, on every path that shows one.

`str()` on a dict or a list produces `{'headline': 'NESTED_HEADLINE'}` --
braces, single quotes and all -- and that reached annotators through seventeen
of the twenty-four displays. It arrived four separate ways before this: dialogue
turn text, multi_agent_discussion, spreadsheet cells, and an API's typed content
blocks in the trace displays.

The sharpest version was that the two text paths disagreed, and the DECLARED
path was the worse one:

    no instance_display   { "headline": "NESTED_HEADLINE", "sub": "NESTED_SUB" }
    type: text            {'headline': 'NESTED_HEADLINE', 'sub': 'NESTED_SUB'}

`flask_server.get_displayed_text` had always emitted indented JSON for a dict.
`text_display` did its own `str()`. Since Potato's docs push authors toward
`instance_display` -- it is the path that preserves whitespace and labels the
field -- the recommended route produced Python syntax.

Lists keep their own `list_as_text` formatter where a display has one, because
how a list-valued field reads is a deliberate config surface.
"""

import pytest

from potato.server_utils.displays.base import display_text
from potato.server_utils.displays.registry import display_registry


NESTED = {"headline": "NESTED_HEADLINE", "sub": "NESTED_SUB"}


class TestTheHelper:

    def test_a_dict_becomes_json(self):
        out = display_text(NESTED)
        assert '"headline"' in out and "'headline'" not in out

    def test_a_list_becomes_json(self):
        assert display_text(["a", "b"]) == '[\n  "a",\n  "b"\n]'

    def test_a_string_is_returned_unchanged(self):
        assert display_text("already text") == "already text"

    def test_none_is_empty_not_the_word_none(self):
        assert display_text(None) == ""

    @pytest.mark.parametrize("value,expected", [
        (3, "3"), (3.5, "3.5"), (True, "True"), (False, "False"),
    ])
    def test_scalars_render_as_themselves(self, value, expected):
        assert display_text(value) == expected

    def test_a_bool_is_not_rendered_as_a_number(self):
        """bool is an int subclass; the wrong branch order gives "1"."""
        assert display_text(True) == "True"

    def test_an_unserializable_value_does_not_raise(self):
        assert display_text({"when": object()})


class TestTheTwoTextPathsAgree:

    def test_the_declared_path_emits_json(self):
        html = display_registry.render("text", {"type": "text", "key": "t"},
                                       NESTED)
        assert "&#x27;headline&#x27;" not in html and "'headline'" not in html, (
            "instance_display -- the path the docs recommend -- rendered the "
            "dict as Python syntax")
        assert "headline" in html and "NESTED_HEADLINE" in html

    def test_the_default_path_still_emits_json(self):
        from potato.flask_server import get_displayed_text

        out = get_displayed_text(NESTED)
        assert '"headline"' in out and "'headline'" not in out

    def test_both_paths_carry_the_same_values(self):
        from potato.flask_server import get_displayed_text

        default = get_displayed_text(NESTED)
        declared = display_registry.render(
            "text", {"type": "text", "key": "t"}, NESTED)
        for value in ("headline", "NESTED_HEADLINE", "sub", "NESTED_SUB"):
            assert value in default and value in declared


class TestNoDisplayLeaksARepr:
    """The displays where a dict or a list is plausible real data, as opposed
    to a field that is meant to hold a URL."""

    PROBES = {
        "text": ({"type": "text", "key": "t"}, NESTED),
        "dialogue": ({"type": "dialogue", "key": "t"},
                     [{"speaker": "A", "text": {"blocks": ["x"]}}]),
        "multi_agent_discussion": (
            {"type": "multi_agent_discussion", "key": "t"},
            [{"speaker": "A", "text": {"blocks": ["x"]}, "agent_id": "a1"}]),
        "spreadsheet": ({"type": "spreadsheet", "key": "t"},
                        [{"col": {"nested": "dict"}}]),
        "gallery": ({"type": "gallery", "key": "t"},
                    [{"url": "/media/a.png", "caption": {"n": 1}}]),
    }

    @pytest.mark.parametrize("name", sorted(PROBES))
    def test_no_python_quoting_reaches_the_page(self, name):
        field_config, data = self.PROBES[name]
        html = display_registry.render(name, field_config, data)
        assert "&#x27;blocks&#x27;" not in html
        assert "&#x27;nested&#x27;" not in html
        assert "{&#x27;" not in html and "{'" not in html, (
            f"{name} put a Python repr in front of the annotator")

    @pytest.mark.parametrize("name", sorted(PROBES))
    def test_the_value_is_still_there(self, name):
        """Not a repr is not the same as not rendered."""
        field_config, data = self.PROBES[name]
        html = display_registry.render(name, field_config, data)
        assert html.strip()


class TestSearchSaysWhyItSkipped:
    """`search: N instance(s) had no indexable text (media-only items); name a
    caption field with item_properties.text_key` named the right items and the
    wrong reason for a populated-but-non-text field. The advice was already
    satisfied, so following it changed nothing and the message repeated.
    """

    def test_a_structured_value_is_indexed_rather_than_skipped(self):
        from potato.search.service import _structured_text

        text = _structured_text(NESTED)
        assert text and "NESTED_HEADLINE" in text, (
            "the page shows this dict, so a search for what is on screen has "
            "to find the item")

    def test_an_awkward_structure_does_not_raise(self):
        """Indexing runs over the whole corpus at boot; one odd value must not
        take the index down. `default=str` means it always produces something,
        so the assertion is that it survives, not that it refuses."""
        from potato.search.service import _structured_text

        assert _structured_text({"when": {object()}})

    def test_an_empty_structure_is_not_indexed(self):
        from potato.search.service import _structured_text

        assert _structured_text({}) in (None, "{}")
