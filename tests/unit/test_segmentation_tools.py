"""
Tests for segmentation tools (fill/eraser) in image annotation.
"""

import pytest


class TestSegmentationToolsRegistration:
    """Verify fill and eraser tools are registered in image_annotation."""

    def test_fill_in_valid_tools(self):
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        assert "fill" in VALID_TOOLS

    def test_eraser_in_valid_tools(self):
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        assert "eraser" in VALID_TOOLS

    def test_original_tools_still_present(self):
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        for tool in ["bbox", "polygon", "freeform", "landmark"]:
            assert tool in VALID_TOOLS


class TestSegmentationToolButtons:
    """Verify tool buttons are generated correctly."""

    def test_fill_button_generated(self):
        from potato.server_utils.schemas.image_annotation import _generate_tool_buttons
        html = _generate_tool_buttons(["fill"])
        assert 'data-tool="fill"' in html
        assert "Fill" in html

    def test_eraser_button_generated(self):
        from potato.server_utils.schemas.image_annotation import _generate_tool_buttons
        html = _generate_tool_buttons(["eraser"])
        assert 'data-tool="eraser"' in html
        assert "Eraser" in html

    def test_all_tools_generate(self):
        from potato.server_utils.schemas.image_annotation import _generate_tool_buttons, VALID_TOOLS
        html = _generate_tool_buttons(VALID_TOOLS)
        for tool in VALID_TOOLS:
            assert f'data-tool="{tool}"' in html


class TestValidToolsHasOneSource:
    """
    ``config_module`` used to restate VALID_TOOLS as a literal, so adding a tool
    in one file and not the other either rejected a valid config or accepted a
    tool with no implementation behind it. It now imports the list.
    """

    def test_config_validation_uses_the_schema_list(self):
        import inspect
        from potato.server_utils import config_module

        source = inspect.getsource(config_module.validate_annotation_schemes) \
            if hasattr(config_module, "validate_annotation_schemes") \
            else inspect.getsource(config_module)
        # The literal list must not reappear.
        assert "'bbox', 'polygon', 'freeform', 'landmark'" not in source

    def test_a_tool_added_to_the_schema_validates(self):
        """A config using every VALID_TOOLS entry must pass validation."""
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        from potato.server_utils.config_module import validate_annotation_schemes

        config = {
            "annotation_schemes": [{
                "annotation_type": "image_annotation",
                "name": "seg",
                "description": "d",
                "tools": list(VALID_TOOLS),
                "labels": [{"name": "road"}],
            }]
        }
        validate_annotation_schemes(config)  # must not raise


class TestFillConfiguration:
    """fill_mode / fill_tolerance, which drive the colour-aware flood fill."""

    def _config(self, **extra):
        scheme = {
            "annotation_type": "image_annotation",
            "name": "seg",
            "description": "d",
            "tools": ["fill"],
            "labels": [{"name": "road"}],
        }
        scheme.update(extra)
        return {"annotation_schemes": [scheme]}

    def test_defaults_to_region_mode(self):
        from potato.server_utils.schemas.image_annotation import (
            generate_image_annotation_layout,
        )
        html, _ = generate_image_annotation_layout({
            "annotation_type": "image_annotation", "name": "seg",
            "description": "d", "tools": ["fill"], "labels": [{"name": "road"}],
        })
        # Colour-aware fill is what an annotator expects from a fill tool;
        # empty-area fill is the opt-in.
        assert '"fillMode": "region"' in html or "'fillMode': 'region'" in html

    @pytest.mark.parametrize("mode", ["region", "empty"])
    def test_valid_modes_accepted(self, mode):
        from potato.server_utils.config_module import validate_annotation_schemes
        validate_annotation_schemes(self._config(fill_mode=mode))

    def test_unknown_mode_rejected(self):
        from potato.server_utils.config_module import (
            validate_annotation_schemes, ConfigValidationError,
        )
        with pytest.raises(ConfigValidationError, match="fill_mode"):
            validate_annotation_schemes(self._config(fill_mode="magic"))

    @pytest.mark.parametrize("bad", [-1, 256, "32", 1.5, True])
    def test_out_of_range_tolerance_rejected(self, bad):
        from potato.server_utils.config_module import (
            validate_annotation_schemes, ConfigValidationError,
        )
        with pytest.raises(ConfigValidationError, match="fill_tolerance"):
            validate_annotation_schemes(self._config(fill_tolerance=bad))

    @pytest.mark.parametrize("ok", [0, 32, 255])
    def test_in_range_tolerance_accepted(self, ok):
        from potato.server_utils.config_module import validate_annotation_schemes
        validate_annotation_schemes(self._config(fill_tolerance=ok))


class TestKeybindingProfiles:
    """
    Tool shortcuts moved to V7/CVAT conventions so annotators arriving from
    either are productive immediately. `legacy` must keep working byte-for-byte
    for projects already collecting data, whose annotators have trained muscle
    memory that a rebind mid-study would break.
    """

    #: What Potato bound before the profiles existed.
    PRE_PROFILE_KEYS = {
        "bbox": "b", "polygon": "p", "freeform": "f", "landmark": "l",
        "brush": "m", "fill": "g", "eraser": "e",
    }

    def test_legacy_profile_never_moves_an_existing_key(self):
        """
        The promise `legacy` makes is that a running study's annotators keep the
        muscle memory they trained — i.e. no key they already use is reassigned.

        It is deliberately NOT "this dict never changes": a tool added later
        (polyline, ellipse) still needs a binding in `legacy`, or a project that
        opted out of the v7 rebind could never reach the new tools at all. So
        assert the pre-existing bindings survive, and let the profile grow.
        """
        from potato.server_utils.schemas.image_annotation import get_tool_keys

        legacy = get_tool_keys("legacy")
        for tool, key in self.PRE_PROFILE_KEYS.items():
            assert legacy[tool] == key, (
                f"legacy binding for {tool!r} moved from {key!r} to "
                f"{legacy[tool]!r}; that breaks a running study")

    def test_legacy_additions_do_not_collide(self):
        """A new tool must not be given a key an existing tool already owns."""
        from potato.server_utils.schemas.image_annotation import get_tool_keys

        legacy = get_tool_keys("legacy")
        assert len(set(legacy.values())) == len(legacy), legacy

    def test_v7_profile_matches_v7_conventions(self):
        from potato.server_utils.schemas.image_annotation import get_tool_keys
        keys = get_tool_keys("v7")
        # The bindings a V7/CVAT user arrives with.
        assert keys["brush"] == "b"
        assert keys["eraser"] == "e"
        assert keys["fill"] == "f"
        assert keys["bbox"] == "r"

    def test_default_is_v7(self):
        from potato.server_utils.schemas.image_annotation import (
            get_tool_keys, DEFAULT_KEYBINDING_PROFILE,
        )
        assert DEFAULT_KEYBINDING_PROFILE == "v7"
        assert get_tool_keys() == get_tool_keys("v7")

    def test_every_profile_covers_every_tool(self):
        """A tool with no key in some profile is unreachable there."""
        from potato.server_utils.schemas.image_annotation import (
            KEYBINDING_PROFILES, VALID_TOOLS,
        )
        for name, mapping in KEYBINDING_PROFILES.items():
            missing = set(VALID_TOOLS) - set(mapping)
            assert not missing, f"profile '{name}' has no key for {sorted(missing)}"

    def test_no_profile_binds_one_key_to_two_tools(self):
        from potato.server_utils.schemas.image_annotation import KEYBINDING_PROFILES
        for name, mapping in KEYBINDING_PROFILES.items():
            keys = list(mapping.values())
            assert len(keys) == len(set(keys)), (
                f"profile '{name}' double-binds a key: {sorted(keys)}")

    def test_no_profile_collides_with_the_common_keys(self):
        from potato.server_utils.schemas.image_annotation import (
            KEYBINDING_PROFILES, COMMON_KEYBINDINGS,
        )
        common = set(COMMON_KEYBINDINGS.values())
        for name, mapping in KEYBINDING_PROFILES.items():
            clash = common & set(mapping.values())
            assert not clash, f"profile '{name}' collides with common keys: {clash}"

    def test_profile_reaches_the_generated_client_config(self):
        from potato.server_utils.schemas.image_annotation import (
            generate_image_annotation_layout, get_tool_keys,
        )
        html, _ = generate_image_annotation_layout({
            "annotation_type": "image_annotation", "name": "seg",
            "description": "d", "tools": ["bbox", "brush"],
            "labels": [{"name": "road"}], "keybinding_profile": "legacy",
        })
        assert '"keybindingProfile": "legacy"' in html
        # The client reads config.toolKeys; a stale copy would silently
        # reintroduce the hardcoded switch this replaced.
        assert f'"bbox": "{get_tool_keys("legacy")["bbox"]}"' in html

    def test_tooltip_key_hint_follows_the_profile(self):
        from potato.server_utils.schemas.image_annotation import (
            _generate_tool_buttons, get_tool_keys,
        )
        v7 = _generate_tool_buttons(["bbox"], get_tool_keys("v7"))
        legacy = _generate_tool_buttons(["bbox"], get_tool_keys("legacy"))
        assert "Bounding Box (R)" in v7
        assert "Bounding Box (B)" in legacy

    @pytest.mark.parametrize("profile", ["v7", "legacy"])
    def test_profiles_validate(self, profile):
        from potato.server_utils.config_module import validate_annotation_schemes
        validate_annotation_schemes({"annotation_schemes": [{
            "annotation_type": "image_annotation", "name": "seg",
            "description": "d", "tools": ["bbox"], "labels": [{"name": "road"}],
            "keybinding_profile": profile,
        }]})

    def test_unknown_profile_rejected(self):
        from potato.server_utils.config_module import (
            validate_annotation_schemes, ConfigValidationError,
        )
        with pytest.raises(ConfigValidationError, match="keybinding_profile"):
            validate_annotation_schemes({"annotation_schemes": [{
                "annotation_type": "image_annotation", "name": "seg",
                "description": "d", "tools": ["bbox"], "labels": [{"name": "road"}],
                "keybinding_profile": "emacs",
            }]})

    def test_label_key_colliding_with_a_tool_key_warns_but_keeps_the_label(self, caplog):
        """
        Per project convention a keybinding conflict warns and continues.
        Dropping the label would leave an annotator with a label they cannot
        reach, which is worse than a double-fire they can be told about.
        """
        import logging
        from potato.server_utils.schemas.image_annotation import (
            _generate_keybindings, get_tool_keys,
        )
        clashing = get_tool_keys()["bbox"]
        with caplog.at_level(logging.WARNING):
            bindings = _generate_keybindings(
                [{"name": "box-ish", "key_value": clashing}], ["bbox"],
                schema_name="collide")

        assert any("Keybinding conflict" in r.message for r in caplog.records)
        assert any(k == clashing and "Select label" in d for k, d in bindings)


class TestKeybindingDocsMatchCode:
    """
    The docs table is how an admin decides whether to set `legacy`. A table that
    drifts from the code is worse than none: the old one documented `(M)/(G)/(E)`
    for brush/fill/eraser, which had no handler at all.
    """

    DOC = "docs/annotation-types/multimedia/image_annotation.md"

    def _doc_text(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        return (root / self.DOC).read_text(encoding="utf-8")

    def test_every_tool_key_appears_in_the_docs_table(self):
        from potato.server_utils.schemas.image_annotation import KEYBINDING_PROFILES
        text = self._doc_text()
        for profile, mapping in KEYBINDING_PROFILES.items():
            for tool, key in mapping.items():
                assert f"`{key}`" in text, (
                    f"{self.DOC} does not document key '{key}' "
                    f"({tool}, profile '{profile}')")

    def test_both_profile_names_are_documented(self):
        from potato.server_utils.schemas.image_annotation import KEYBINDING_PROFILES
        text = self._doc_text()
        for profile in KEYBINDING_PROFILES:
            assert f"`{profile}`" in text, f"{self.DOC} does not mention profile '{profile}'"

    def test_common_keys_are_documented(self):
        from potato.server_utils.schemas.image_annotation import COMMON_KEYBINDINGS
        text = self._doc_text()
        for action, key in COMMON_KEYBINDINGS.items():
            assert f"`{key}`" in text, f"{self.DOC} does not document '{key}' ({action})"


class TestSegmentationKeybindings:
    """Verify keybinding generation includes new tools."""

    def test_fill_keybinding(self):
        from potato.server_utils.schemas.image_annotation import (
            _generate_keybindings, get_tool_keys,
        )
        bindings = _generate_keybindings([], ["fill"])
        keys = [b[0] for b in bindings]
        assert get_tool_keys()["fill"] in keys

    def test_eraser_keybinding(self):
        from potato.server_utils.schemas.image_annotation import (
            _generate_keybindings, get_tool_keys,
        )
        bindings = _generate_keybindings([], ["eraser"])
        keys = [b[0] for b in bindings]
        assert get_tool_keys()["eraser"] in keys

    def test_brush_size_keys_only_when_a_sizing_tool_is_enabled(self):
        from potato.server_utils.schemas.image_annotation import _generate_keybindings
        with_brush = [b[0] for b in _generate_keybindings([], ["brush"])]
        without = [b[0] for b in _generate_keybindings([], ["bbox"])]
        assert "[/]" in with_brush
        assert "[/]" not in without


class TestSchemaGalleryDocsMatchCode:
    """
    `schemas_and_templates.md` is the gallery an admin copies from. Its image
    and video sections documented `annotation_mode:` and `frame_step:` — keys
    that do not exist in either schema — so a copied example silently ignored
    them and the annotator got default behaviour.
    """

    DOC = "docs/annotation-types/schemas_and_templates.md"

    def _text(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[2] / self.DOC).read_text(
            encoding="utf-8")

    def test_no_nonexistent_keys_are_documented(self):
        text = self._text()
        for phantom in ("annotation_mode:", "frame_step:", "allow_multiple:"):
            # Allowed only inside an explicit "there is no such key" note.
            bad = [ln for ln in text.splitlines()
                   if phantom in ln and "no " not in ln.lower()]
            assert not bad, f"{self.DOC} still documents a nonexistent key: {bad}"

    def test_image_section_documents_the_real_tools(self):
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        text = self._text()
        for tool in VALID_TOOLS:
            assert tool in text, f"{self.DOC} does not mention the '{tool}' tool"

    def test_video_section_documents_every_real_mode(self):
        from potato.server_utils.schemas.video_annotation import VALID_MODES
        text = self._text()
        for mode in VALID_MODES:
            assert mode in text, f"{self.DOC} does not mention video mode '{mode}'"
