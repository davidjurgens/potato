"""
Drift guards for the display-type registry.

The display registry is the single source of truth for which `instance_display`
field types exist. Two things have historically drifted away from it:

1. **The documentation.** `docs/annotation-types/instance_display.md` carries the
   reference table users scan to find out what a display type is called. It once
   listed 14 of 23 registered types, which made `audio_dialogue` — the
   diarized-transcript-with-audio display — effectively undiscoverable: the table
   showed only `audio` (bare player) and `dialogue` (text-only), so a reader
   reasonably concluded the feature did not exist.

2. **The static fallback list** in `validate_instance_display_config`. Config
   validation normally sources valid types from the registry, but falls back to a
   hardcoded list if the import fails. A type missing from that list is rejected as
   invalid on the fallback path — a config that works normally fails in whatever
   environment triggers the fallback.

These tests fail loudly when a new display type is registered without updating
both, and when either lists a type the registry does not actually serve.
"""

import ast
import inspect
import re
from pathlib import Path

import pytest

from potato.server_utils.displays import display_registry


REPO_ROOT = Path(__file__).resolve().parents[2]
DISPLAY_DOC = REPO_ROOT / "docs" / "annotation-types" / "instance_display.md"


def _registered_types():
    return set(display_registry.get_supported_types())


def _documented_types():
    """Display types named in a table row of the display-type reference doc.

    Table rows look like ``| `audio_dialogue` | Description | Yes |``. Matching on
    the leading-pipe-then-backticked-name shape keeps prose mentions of a type
    from counting as documentation — a type is only documented once it has a row
    in the table.
    """
    text = DISPLAY_DOC.read_text(encoding="utf-8")
    # Only the display-type section. The same document also carries an options
    # table -- `resizable`, `max_height`, `min_height` -- whose rows have the
    # identical shape, and reading those as display types made this guard fail
    # on a correct doc. Scoping it here rather than loosening the pattern keeps
    # the check exact: a row in the type table, and nowhere else.
    section = re.search(
        r"^## Supported Display Types\s*$(.*?)^## ", text,
        flags=re.MULTILINE | re.DOTALL)
    scope = section.group(1) if section else text
    return set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", scope,
                          flags=re.MULTILINE))


def _fallback_types():
    """The hardcoded list used when the registry import fails.

    Read out of the source with `ast` rather than by importing, because the list
    only ever materializes inside an `except` branch that does not fire in a
    healthy install.
    """
    from potato.server_utils import config_module

    tree = ast.parse(inspect.getsource(config_module.validate_instance_display_config))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "valid_display_types" not in targets:
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            return {
                el.value
                for el in node.value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            }
    pytest.fail(
        "No literal `valid_display_types` list found in "
        "validate_instance_display_config. If the fallback list was removed "
        "entirely, delete the tests that guard it; if it was restructured, "
        "update this extractor."
    )


class TestDisplayDocsSync:
    """The reference table must name every registered display type, and no others."""

    def test_doc_file_exists(self):
        assert DISPLAY_DOC.is_file(), f"Display type reference doc missing: {DISPLAY_DOC}"

    def test_every_registered_type_is_documented(self):
        missing = _registered_types() - _documented_types()
        assert not missing, (
            "Display types registered but absent from the reference table in "
            f"docs/annotation-types/instance_display.md: {sorted(missing)}. "
            "Users find display types by scanning that table; a type missing "
            "from it is effectively undiscoverable. Add a row of the form "
            "`| `type_name` | Description | Span Target |`."
        )

    def test_no_documented_type_is_unregistered(self):
        phantom = _documented_types() - _registered_types()
        assert not phantom, (
            "The reference table documents display types the registry does not "
            f"serve: {sorted(phantom)}. Either register them or remove the rows — "
            "a documented type that fails config validation is worse than an "
            "undocumented one."
        )


class TestDisplayValidationFallbackSync:
    """The static fallback list must cover every registered display type."""

    def test_validation_prefers_the_registry(self):
        from potato.server_utils import config_module

        src = inspect.getsource(config_module.validate_instance_display_config)
        assert "display_registry.get_supported_types()" in src, (
            "validate_instance_display_config no longer sources valid display "
            "types from display_registry.get_supported_types(); the registry and "
            "the config validator can now drift out of sync."
        )

    def test_fallback_list_covers_every_registered_type(self):
        missing = _registered_types() - _fallback_types()
        assert not missing, (
            "Display types registered but absent from the static fallback list "
            f"in validate_instance_display_config: {sorted(missing)}. On the "
            "fallback path these types are rejected as invalid, so a working "
            "config fails wherever the registry import does."
        )

    def test_fallback_list_has_no_unregistered_types(self):
        phantom = _fallback_types() - _registered_types()
        assert not phantom, (
            "The static fallback list accepts display types the registry does "
            f"not serve: {sorted(phantom)}. These pass validation and then fail "
            "at render time."
        )
