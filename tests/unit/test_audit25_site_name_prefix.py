"""
A task name is not a path.

Found while building probe studies for audit 25: a config with
``annotation_task_name: "Pairwise left/right + conjoint"`` crashed the server
at boot with

    FileNotFoundError: .../templates/generated/Pairwise-left/right-+-conjoint-...

Three call sites built a generated-template filename out of the task name and
all three only ever replaced spaces, so any separator in the name became a
directory boundary -- and a name containing ``..`` would have written the
template outside the generated directory.
"""

import os

from potato.server_utils.generated_templates import site_name_prefix


class TestSiteNamePrefix:

    def test_spaces_still_become_the_separator_the_caller_asked_for(self):
        """Two conventions already exist in the tree and both stay."""
        assert site_name_prefix("Survey Instruments Demo", "-") == \
            "Survey-Instruments-Demo"
        assert site_name_prefix("Survey Instruments Demo", "_") == \
            "Survey_Instruments_Demo"

    def test_a_separator_in_the_name_does_not_become_a_directory(self):
        result = site_name_prefix("Pairwise left/right", "-")
        assert os.sep not in result
        assert result == "Pairwise-left-right"

    def test_a_dot_dot_name_cannot_escape_the_generated_directory(self):
        for name in ("..", ".", "../..", "..."):
            result = site_name_prefix(name, "-")
            assert result == "task", result
            assert os.path.basename(
                os.path.join("/generated", result + "-x.html")
            ) == result + "-x.html"

    def test_an_empty_name_still_produces_a_filename(self):
        assert site_name_prefix("", "-") == "task"
        assert site_name_prefix(None, "-") == "task"

    def test_ordinary_punctuation_is_left_alone(self):
        """Parentheses and plus signs are legal in a filename.

        Existing baked templates carry them, and replacing every character
        that merely looks unusual would rename files nothing asked to rename.
        """
        assert site_name_prefix("Summary preference (default_width)", "_") == \
            "Summary_preference_(default_width)"
        assert site_name_prefix("A + B", "-") == "A-+-B"
