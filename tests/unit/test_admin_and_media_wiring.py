"""Regressions for four wiring bugs found while re-capturing the talk screenshots.

Each of these was silent: no exception reached the annotator, nothing failed a test,
and every one of them showed up only as a screenshot of a feature that looked broken.

1. Peaks.js was gated on audio_annotation/video_annotation only, so the tiered
   annotation schema — whose overview and zoomed views *are* Peaks views — rendered
   "Loading overview..." forever.
2. /admin/api/embedding_viz/data called ItemStateManager.get_instance_by_id(), a method
   that does not exist, so every request 500'd.
3. ...and once that was fixed, jsonify() sorted a dict keyed by label, where None means
   "unannotated", and TypeError'd comparing None to str.
4. The admin annotators table read total_working_time / average_time_per_annotation from
   a payload that returns total_seconds / average_seconds_per_annotation, so both
   columns read "N/A" for every annotator no matter how much work they had done.
"""
import json
import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / "potato" / "templates"


class TestPeaksGating:
    """Bug 1: the waveform library must load for every schema that draws waveforms."""

    @pytest.fixture(scope="class")
    def base_template(self):
        return (TEMPLATES / "base_template_v2.html").read_text(encoding="utf-8")

    def test_peaks_gate_includes_tiered_annotation(self, base_template):
        gate = next(
            (line for line in base_template.splitlines()
             if "peaks.min.js" in line or
             ("frontend_assets.audio_annotation" in line and "{% if" in line)),
            None)
        # Find the {% if %} immediately preceding the peaks.min.js script tag.
        idx = base_template.index("peaks.min.js")
        preceding = base_template[:idx].rsplit("{% if", 1)[-1]
        assert "tiered_annotation" in preceding, (
            "peaks.min.js is not loaded for tiered_annotation; its waveform views "
            "will sit on 'Loading overview...' forever")

    def test_tiered_annotation_is_a_known_asset_key(self):
        from potato.flask_server import FRONTEND_ASSET_MARKERS
        assert "tiered_annotation" in FRONTEND_ASSET_MARKERS


class TestEmbeddingVizPayload:
    """Bugs 2 and 3: the admin embedding projection must serialise."""

    def test_item_state_manager_has_no_get_instance_by_id(self):
        """The name the caller used. If it ever appears, the guard can be dropped."""
        from potato.item_state_management import ItemStateManager
        assert not hasattr(ItemStateManager, "get_instance_by_id")
        assert hasattr(ItemStateManager, "get_item")

    def test_visualiser_uses_get_item(self):
        src = (Path(__file__).resolve().parents[2] / "potato"
               / "embedding_visualization.py").read_text(encoding="utf-8")
        # Match the call, not the name — the fix leaves the old name in a comment.
        assert not re.search(r"\.get_instance_by_id\s*\(", src), (
            "embedding_visualization.py calls a method ItemStateManager does not "
            "define; /admin/api/embedding_viz/data will 500")
        assert re.search(r"ism\.get_item\s*\(", src)

    def test_label_colors_none_key_is_json_safe(self):
        """A None key survives json.dumps only once it has been remapped.

        Flask's provider sorts keys, so this is the exact failure: a mixed
        {str: ..., None: ...} dict raises before anything reaches the client.
        """
        raw = {"Positive": "#1f77b4", None: "#cccccc"}
        with pytest.raises(TypeError):
            json.dumps(raw, sort_keys=True)

        remapped = {("null" if k is None else k): v for k, v in raw.items()}
        assert json.loads(json.dumps(remapped, sort_keys=True))["null"] == "#cccccc"

    def test_route_remaps_the_none_key(self):
        src = (Path(__file__).resolve().parents[2] / "potato"
               / "routes.py").read_text(encoding="utf-8")
        handler = src.split("def admin_api_embedding_viz_data", 1)[1].split("\ndef ", 1)[0]
        assert '"null" if k is None' in handler, (
            "label_colors is passed to jsonify with its None key intact; the response "
            "will 500 as soon as any instance is unlabelled")


class TestAdminAnnotatorTimings:
    """Bug 4: the table must read the keys the API actually sends."""

    @pytest.fixture(scope="class")
    def admin_template(self):
        return (TEMPLATES / "admin.html").read_text(encoding="utf-8")

    def test_api_payload_keys(self):
        src = (Path(__file__).resolve().parents[2] / "potato"
               / "admin.py").read_text(encoding="utf-8")
        block = src.split("annotators_data.append(", 1)[1][:1500]
        assert '"total_seconds"' in block
        assert '"average_seconds_per_annotation"' in block
        assert '"total_working_time"' not in block
        assert '"average_time_per_annotation"' not in block

    def test_table_reads_the_keys_the_api_sends(self, admin_template):
        row = admin_template.split("annotator.total_annotations", 1)[1][:1200]
        assert "annotator.total_seconds" in row
        assert "annotator.average_seconds_per_annotation" in row
        assert "annotator.total_working_time" not in row, (
            "the annotators table reads a key /admin/api/annotators never returns; "
            "Working Time will read N/A for everyone")

    def test_format_time_shares_scope_with_the_row_renderer(self, admin_template):
        """The row template calls formatTime(); both must be in the same <script>."""
        blocks = [m for m in re.finditer(r"<script[^>]*>.*?</script>",
                                         admin_template, re.S)]
        defn = admin_template.index("function formatTime")
        use = admin_template.index("annotator.total_seconds")
        owning = [i for i, m in enumerate(blocks)
                  if m.start() <= defn < m.end() and m.start() <= use < m.end()]
        assert owning, "formatTime() is not in scope where the annotator row uses it"
