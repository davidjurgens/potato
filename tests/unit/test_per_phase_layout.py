"""
Tests for per-phase layout snippet files (Issue #119).

Verifies that each surveyflow phase gets its own layout file
(task_layout_{phase_name}.html) instead of all phases overwriting
the single task_layout.html.
"""

import os
import pytest
from unittest.mock import patch, MagicMock


def _make_config(tmp_path):
    """Create a minimal config dict pointing at tmp_path as task_dir."""
    return {
        "task_dir": str(tmp_path),
        "annotation_task_name": "test_task",
    }


def _make_schemes(labels):
    """Create simple annotation schemes that produce distinct HTML."""
    return [
        {
            "annotation_type": "radio",
            "name": f"scheme_{i}",
            "description": f"Scheme {label}",
            "labels": [label],
            "annotation_id": i,
        }
        for i, label in enumerate(labels)
    ]


class TestPerPhaseLayout:
    """Tests for per-phase layout file generation."""

    def test_main_annotation_uses_default_filename(self, tmp_path):
        """No layout_name → writes task_layout.html."""
        with patch("potato.server_utils.front_end.generate_schematic",
                    return_value=("<div>radio</div>", [])):
            from potato.server_utils.front_end import generate_annotation_layout_file

            config = _make_config(tmp_path)
            schemes = _make_schemes(["pos", "neg"])

            result = generate_annotation_layout_file(config, schemes)
            assert result.endswith("task_layout.html")
            assert os.path.exists(result)

    def test_phase_uses_named_filename(self, tmp_path):
        """layout_name='consent' → writes task_layout_consent.html."""
        with patch("potato.server_utils.front_end.generate_schematic",
                    return_value=("<div>consent</div>", [])):
            from potato.server_utils.front_end import generate_annotation_layout_file

            config = _make_config(tmp_path)
            schemes = _make_schemes(["agree"])

            result = generate_annotation_layout_file(config, schemes, layout_name="consent")
            assert result.endswith("task_layout_consent.html")
            assert os.path.exists(result)

    def test_multiple_phases_get_separate_files(self, tmp_path):
        """Three phases → three separate files with distinct content."""
        from potato.server_utils.front_end import generate_annotation_layout_file

        config = _make_config(tmp_path)
        phase_names = ["consent", "demographics", "exit_survey"]
        generated_files = []

        for phase in phase_names:
            with patch("potato.server_utils.front_end.generate_schematic",
                        return_value=(f"<div>{phase}</div>", [])):
                schemes = _make_schemes([phase])
                result = generate_annotation_layout_file(config, schemes, layout_name=phase)
                generated_files.append(result)

        # All files should exist and be distinct
        assert len(set(generated_files)) == 3
        for f in generated_files:
            assert os.path.exists(f)

        # Content should differ
        contents = []
        for f in generated_files:
            with open(f, "r") as fh:
                contents.append(fh.read())
        assert len(set(contents)) == 3

    def test_main_layout_not_overwritten_by_phase(self, tmp_path):
        """Generate main layout, then a phase layout → main is unchanged."""
        from potato.server_utils.front_end import generate_annotation_layout_file

        config = _make_config(tmp_path)

        # Generate main layout
        with patch("potato.server_utils.front_end.generate_schematic",
                    return_value=("<div>main</div>", [])):
            main_path = generate_annotation_layout_file(config, _make_schemes(["main"]))
        with open(main_path, "r") as f:
            main_content = f.read()

        # Generate phase layout
        with patch("potato.server_utils.front_end.generate_schematic",
                    return_value=("<div>consent</div>", [])):
            phase_path = generate_annotation_layout_file(
                config, _make_schemes(["consent"]), layout_name="consent"
            )

        # Main should be unchanged
        with open(main_path, "r") as f:
            assert f.read() == main_content

        # Files should be different paths
        assert main_path != phase_path

    def test_hash_caching_preserves_edits(self, tmp_path):
        """Same schemas + same name → file not regenerated (edits preserved)."""
        from potato.server_utils.front_end import get_or_generate_annotation_layout

        config = _make_config(tmp_path)
        schemes = _make_schemes(["pos"])

        with patch("potato.server_utils.front_end.generate_schematic",
                    return_value=("<div>radio</div>", [])):
            # First call generates the file
            path1 = get_or_generate_annotation_layout(config, schemes, layout_name="consent")
            assert os.path.exists(path1)

            # Simulate admin editing the file (append custom content after hash line)
            with open(path1, "r") as f:
                original = f.read()
            edited = original + "\n<!-- admin customization -->"
            with open(path1, "w") as f:
                f.write(edited)

            # Second call with same schemas should NOT regenerate (hash matches)
            path2 = get_or_generate_annotation_layout(config, schemes, layout_name="consent")
            assert path1 == path2
            with open(path2, "r") as f:
                content = f.read()
            assert "<!-- admin customization -->" in content

    def test_hash_invalidation_on_schema_change(self, tmp_path):
        """Different schemas → file regenerated (hash mismatch)."""
        from potato.server_utils.front_end import get_or_generate_annotation_layout

        config = _make_config(tmp_path)
        schemes = _make_schemes(["pos"])

        # First call with one schema output
        with patch("potato.server_utils.front_end.generate_schematic",
                    return_value=("<div>v1</div>", [])):
            path1 = get_or_generate_annotation_layout(config, schemes, layout_name="consent")
            with open(path1, "r") as f:
                content_v1 = f.read()
            assert "<div>v1</div>" in content_v1

        # Second call with different schema output (simulates code change)
        with patch("potato.server_utils.front_end.generate_schematic",
                    return_value=("<div>v2</div>", [])):
            path2 = get_or_generate_annotation_layout(config, schemes, layout_name="consent")
            with open(path2, "r") as f:
                content_v2 = f.read()
            assert "<div>v2</div>" in content_v2

        # Same path, but content changed
        assert path1 == path2
        assert content_v1 != content_v2

    def test_get_or_generate_default_still_works(self, tmp_path):
        """get_or_generate without layout_name still uses task_layout.html."""
        with patch("potato.server_utils.front_end.generate_schematic",
                    return_value=("<div>default</div>", [])):
            from potato.server_utils.front_end import get_or_generate_annotation_layout

            config = _make_config(tmp_path)
            schemes = _make_schemes(["default"])

            path = get_or_generate_annotation_layout(config, schemes)
            assert path.endswith("task_layout.html")
            assert "task_layout_" not in os.path.basename(path)
