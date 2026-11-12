"""Every option a display renderer reads has to be declared where authors look.

`potato/server_utils/schemas/registry.py` has had this rule for annotation
schemes since `test_schema_registry_field_coverage.py`: a key the generator
reads but the registry omits does not exist as far as editors, agents or the
published JSON Schema are concerned. The display registry had no equivalent
guard, and had drifted much further than the scheme registry ever did.

`DisplayDefinition` used to repeat each renderer's `optional_fields` by hand.
`BaseDisplay.get_display_options()` merges the *renderer's* copy, so the
definition's copy fed only `list_displays()`, the generated schema and the docs.
Fourteen of twenty-four displays hid forty-four working options between them --
`pdf` alone hid fifteen, `ocr` and `link_schema` among them -- and
`multi_agent_discussion` hid `speaker_key`, which is what a trace whose turns are
keyed `agent` rather than `speaker` needs to render agent names at all. There is
no error and nothing in the log; every turn just renders as an anonymous grey
avatar.

The definition now reads the renderer in `__post_init__`. These tests fail if
anyone reintroduces the copy, or registers a renderer the derivation cannot read.
"""

import ast
import inspect
from pathlib import Path

import pytest

from potato.server_utils.displays.base import BaseDisplay
from potato.server_utils.displays.registry import display_registry


REGISTRY_SOURCE = Path(inspect.getfile(display_registry.__class__))


@pytest.fixture(scope="module", autouse=True)
def _populated():
    """The registry is lazily populated; list_displays() forces it."""
    display_registry.list_displays()


def _base_display_definitions():
    return {
        name: d
        for name, d in display_registry._displays.items()
        if isinstance(d.renderer, BaseDisplay)
    }


class TestTheDefinitionReportsWhatTheRendererReads:
    def test_no_renderer_option_is_missing_from_its_definition(self):
        missing = {
            name: sorted(set(d.renderer.optional_fields or {}) - set(d.optional_fields or {}))
            for name, d in _base_display_definitions().items()
        }
        missing = {k: v for k, v in missing.items() if v}

        assert not missing, (
            "These display options work but are undiscoverable -- absent from "
            f"list_displays(), the generated JSON Schema and the docs: {missing}"
        )

    def test_no_published_default_contradicts_the_renderer(self):
        """A wrong default is worse than an absent one: it is documentation.

        `agent_trace.step_type_colors` and `eval_trace.pane_labels` were both
        published as None while the renderer supplied a real default.
        """
        wrong = [
            f"{name}.{key}: published {value!r}, renderer uses "
            f"{d.renderer.optional_fields[key]!r}"
            for name, d in _base_display_definitions().items()
            for key, value in (d.optional_fields or {}).items()
            if key in (d.renderer.optional_fields or {})
            and value != d.renderer.optional_fields[key]
        ]

        assert not wrong, wrong

    def test_required_fields_agree_too(self):
        disagree = {
            name: (sorted(d.renderer.required_fields or []), sorted(d.required_fields or []))
            for name, d in _base_display_definitions().items()
            if set(d.renderer.required_fields or []) != set(d.required_fields or [])
        }

        assert not disagree, disagree


class TestTheCopyStaysDeleted:
    """The derivation only holds while nobody hand-writes the dict again.

    A literal `optional_fields=` on a DisplayDefinition whose renderer is a
    BaseDisplay is now dead weight -- `__post_init__` overrides every key it
    shares with the renderer -- so someone editing it to change a default would
    watch their edit do nothing.
    """

    def test_no_display_definition_passes_optional_fields_literally(self):
        tree = ast.parse(REGISTRY_SOURCE.read_text(encoding="utf-8"))

        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "DisplayDefinition"):
                continue
            kwargs = {k.arg: k.value for k in node.keywords}
            renderer = kwargs.get("renderer")
            is_display_instance = (
                isinstance(renderer, ast.Call)
                and getattr(renderer.func, "id", "").endswith("Display")
            )
            if is_display_instance and "optional_fields" in kwargs:
                name = kwargs.get("name")
                offenders.append(getattr(name, "value", "?"))

        assert not offenders, (
            "Declare these on the renderer class instead -- the definition's "
            f"copy is overridden and cannot take effect: {offenders}"
        )


class TestTheOptionsAuthorsActuallyNeeded:
    """Spot checks on the options that were invisible, so a regression is named.

    Each of these was reachable in the product and absent from every place an
    author, an editor or an agent would look.
    """

    @pytest.mark.parametrize("display,option", [
        ("multi_agent_discussion", "speaker_key"),
        ("multi_agent_discussion", "text_key"),
        ("agent_trace", "show_run_tree"),
        ("cot_trace", "step_type_colors"),
        ("pdf", "ocr"),
        ("pdf", "link_schema"),
        ("pdf", "enable_text_anchors"),
        ("spreadsheet", "filterable"),
        ("gallery", "url_key"),
        ("video", "poster"),
        ("audio", "preload"),
        ("image", "object_fit"),
        ("html", "preserve_whitespace"),
        ("document", "annotation_mode"),
        ("interactive_chat", "per_turn_ratings"),
        ("audio_dialogue", "transcript_is_path"),
        ("eval_trace", "speaker_key"),
    ])
    def test_option_is_published(self, display, option):
        published = {d["name"]: d for d in display_registry.list_displays()}
        assert option in set(published[display]["optional_fields"] or [])
