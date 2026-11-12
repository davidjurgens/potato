"""A label's display text must reach the annotator, whichever key it is under.

Three spellings for "the words the annotator reads" accumulated, and only one
of them was ever read:

* ``displayed_label`` -- honored.
* ``text`` -- documented in ``docs/configuration/config_reference.md`` as
  "Display text shown to annotators", and ignored.
* ``label`` -- used by all 55 bundled survey instruments, and ignored.

So a config that followed the docs, and every bundled demographics battery,
showed annotators the raw identifier: "less_hs" rather than "Less than high
school".
"""

import re

import pytest

from potato.server_utils.schemas.identifier_utils import display_label_text


DISPLAY_KEYS = ["displayed_label", "text", "label"]


class TestDisplayLabelText:
    @pytest.mark.parametrize("key", DISPLAY_KEYS)
    def test_each_display_key_wins_over_the_name(self, key):
        label = {"name": "less_hs", key: "Less than high school"}
        assert display_label_text(label, {}) == "Less than high school"

    @pytest.mark.parametrize("key", DISPLAY_KEYS)
    def test_display_key_wins_even_when_humanizing_is_off(self, key):
        """Explicit display text is not a humanization decision."""
        label = {"name": "less_hs", key: "Less than high school"}
        scheme = {"humanize_labels": False}
        assert display_label_text(label, scheme) == "Less than high school"

    def test_displayed_label_outranks_the_others(self):
        label = {
            "name": "less_hs",
            "label": "from label",
            "text": "from text",
            "displayed_label": "from displayed_label",
        }
        assert display_label_text(label, {}) == "from displayed_label"

    def test_text_outranks_label(self):
        label = {"name": "less_hs", "label": "from label", "text": "from text"}
        assert display_label_text(label, {}) == "from text"

    def test_bare_name_still_humanizes_by_default(self):
        assert display_label_text({"name": "less_hs"}, {}) == "Less Hs"

    def test_bare_name_is_left_alone_when_humanizing_is_off(self):
        scheme = {"humanize_labels": False}
        assert display_label_text({"name": "less_hs"}, scheme) == "less_hs"

    def test_plain_string_label_still_humanizes(self):
        assert display_label_text("less_hs", {}) == "Less Hs"

    @pytest.mark.parametrize("key", DISPLAY_KEYS)
    def test_empty_display_text_falls_through_to_the_name(self, key):
        """An empty string is not display text; do not render a blank option."""
        assert display_label_text({"name": "less_hs", key: ""}, {}) == "Less Hs"


class TestDisplayTextReachesTheRenderedForm:
    """The helper is only useful if the generators actually surface it."""

    @pytest.mark.parametrize("key", DISPLAY_KEYS)
    @pytest.mark.parametrize("annotation_type", ["radio", "multiselect"])
    def test_option_renders_its_display_text(self, annotation_type, key):
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": annotation_type,
            "name": "q",
            "description": "Highest level of education?",
            "labels": [{"name": "less_hs", key: "Less than high school"}],
        }
        html, _ = schema_registry.generate(scheme)
        assert "Less than high school" in html

    @pytest.mark.parametrize("annotation_type", ["radio", "multiselect"])
    def test_stored_value_is_still_the_raw_name(self, annotation_type):
        """Display text must never leak into the stored annotation value.

        Existing annotation files key on the raw name, so changing what the
        option renders must not change what it saves.
        """
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": annotation_type,
            "name": "q",
            "description": "Highest level of education?",
            "labels": [{"name": "less_hs", "label": "Less than high school"}],
        }
        html, _ = schema_registry.generate(scheme)
        values = re.findall(r'value="([^"]*)"', html)
        assert "less_hs" in values
        assert "Less than high school" not in values
