"""Regressions for the findings in POTATO-BUGS-audit-23.

1  `gui_trajectory` with `coord_space: pixels` drew no marker at all. The
   pixel branch set left/top to null and the emit was guarded on
   `left !== null`, so the grounding marker -- the whole question the display
   exists to answer -- was never produced. The normalized default puts the
   same data at 42000%, off the picture, so a pixel-exported trace had no
   working setting.

Plus a guard the round earned rather than found: schema generators emit
JavaScript from Python f-strings, and a quote-escaping slip yields a page that
parses as nothing and fails silently. One was introduced while fixing the
above and only the live page caught it.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest


def _inline_scripts(html):
    """Script bodies the page defines itself, not the ones it links."""
    return re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)


def _node_check(body):
    """(ok, stderr) from `node --check` on a script body."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8")
    try:
        handle.write(body)
        handle.close()
        result = subprocess.run(["node", "--check", handle.name],
                                capture_output=True, text=True, timeout=60)
        return result.returncode == 0, result.stderr
    finally:
        os.unlink(handle.name)


# ---------------------------------------------------------------------------
# 1. The pixel-space marker.
# ---------------------------------------------------------------------------
class TestPixelCoordinateMarker:

    def _html(self, **extra):
        from potato.server_utils.schemas.gui_trajectory import (
            generate_gui_trajectory_layout)
        scheme = {"annotation_type": "gui_trajectory", "name": "traj",
                  "description": "Review each step"}
        scheme.update(extra)
        html, _ = generate_gui_trajectory_layout(scheme)
        return html

    def test_positioning_uses_the_intrinsic_size(self):
        """Percentage of naturalWidth, not of the rendered width: the
        screenshot scales inside a shrink-wrapping container, so the same
        percentage stays correct at any display size and survives a resize."""
        html = self._html(coord_space="pixels")
        assert "naturalWidth" in html and "naturalHeight" in html

    def test_a_pending_marker_is_hidden_until_placed(self):
        """Otherwise an unplaced marker sits at the container origin and reads
        as a real answer about where the click landed."""
        html = self._html(coord_space="pixels")
        assert re.search(r"\.gt-marker-pending\s*\{\s*display:\s*none",
                         html), "unplaced markers must not render"

    def test_both_modes_are_reachable_from_config(self):
        from potato.server_utils.schemas.registry import schema_registry
        entry = next(s for s in schema_registry.list_schemas()
                     if s["name"] == "gui_trajectory")
        assert "coord_space" in entry["optional_fields"]

    def test_a_screenshot_that_fails_to_load_says_so(self):
        """It rendered as a bare broken-image icon, so a wrong path and a
        wrong key looked identical."""
        html = self._html(coord_space="pixels")
        assert "screenshot did not load" in html
        assert "data-gt-src" in html
        assert "media_directory" in html

    def test_a_step_with_no_screenshot_names_the_key_it_wanted(self):
        html = self._html(coord_space="pixels", screenshot_key="shot")
        assert "no screenshot" in html
        assert "CONFIG.screenshot_key" in html


class TestPixelMarkerArithmetic:
    """The placement rule itself, executed rather than described."""

    @pytest.fixture(scope="class")
    def place(self):
        if not shutil.which("node"):
            pytest.skip("node is not installed")

        from potato.server_utils.schemas.gui_trajectory import (
            generate_gui_trajectory_layout)
        html, _ = generate_gui_trajectory_layout(
            {"annotation_type": "gui_trajectory", "name": "traj",
             "description": "d", "coord_space": "pixels"})
        body = _inline_scripts(html)[0]

        probe = r"""
        // Lift placePixelMarkers out of the emitted script and run it against
        // a stubbed screenshot, so the arithmetic is tested rather than the
        // spelling of the source.
        const src = require('fs').readFileSync(process.argv[2], 'utf8');
        const at = src.indexOf('function placePixelMarkers');
        let i = src.indexOf('{', at), depth = 0, end = -1;
        for (let j = i; j < src.length; j++) {
          if (src[j] === '{') depth++;
          else if (src[j] === '}') { depth--; if (!depth) { end = j + 1; break; } }
        }
        const place = eval('(' + src.slice(at, end) + ')');

        function marker(x, y, natW, natH) {
          const m = { style: {}, _cls: ['gt-marker', 'gt-marker-pending'],
                      getAttribute: (k) => (k === 'data-gt-x' ? String(x) : String(y)),
                      classList: { remove(c) { m._cls = m._cls.filter(v => v !== c); } } };
          const img = { naturalWidth: natW, naturalHeight: natH, complete: true,
                        addEventListener() {} };
          m.parentNode = { querySelector: () => img };
          return m;
        }
        // placePixelMarkers also walks img.gt-shot to attach error handlers,
        // so the stub root has to answer both selectors.
        const run = (m) => {
          place({ querySelectorAll: (sel) =>
            (sel.indexOf('gt-marker-pending') >= 0 ? [m] : []) });
          return m;
        };

        const out = {};
        let m;
        m = run(marker(420, 120, 800, 400));
        out.centre = [m.style.left, m.style.top, m._cls.includes('gt-marker-pending')];
        m = run(marker(0, 0, 800, 400));
        out.origin = [m.style.left, m.style.top];
        m = run(marker(799, 399, 800, 400));
        out.farCorner = [m.style.left, m.style.top];
        m = run(marker(420, 120, 0, 0));
        out.brokenImage = [m.style.left === undefined, m._cls.includes('gt-marker-pending')];
        m = run(marker(NaN, 5, 800, 400));
        out.badCoord = [m.style.left === undefined, m._cls.includes('gt-marker-pending')];
        console.log(JSON.stringify(out));
        """
        script = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8")
        payload = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                              encoding="utf-8")
        script.write(probe); script.close()
        payload.write(body); payload.close()
        try:
            result = subprocess.run(["node", script.name, payload.name],
                                    capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        finally:
            os.unlink(script.name)
            os.unlink(payload.name)

    def test_a_click_lands_where_the_data_says(self, place):
        """420 of 800 is 52.5%, 120 of 400 is 30%."""
        assert place["centre"][0] == "52.5%"
        assert place["centre"][1] == "30%"

    def test_the_marker_stops_being_pending_once_placed(self, place):
        assert place["centre"][2] is False

    def test_the_origin_is_not_special_cased_away(self, place):
        """0,0 is a real coordinate; a truthiness check would drop it."""
        assert place["origin"] == ["0%", "0%"]

    def test_the_far_corner_stays_inside_the_image(self, place):
        assert place["farCorner"] == ["99.875%", "99.75%"]

    def test_a_broken_screenshot_leaves_the_marker_hidden(self, place):
        """naturalWidth is 0 for an image that 404ed. Dividing by it would pin
        the marker to a corner, which reads as a real answer."""
        assert place["brokenImage"] == [True, True]

    def test_an_unparseable_coordinate_leaves_the_marker_hidden(self, place):
        assert place["badCoord"] == [True, True]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
class TestMarkerIsActuallyEmitted:
    """Asserting the source *contains* `gt-marker-pending` proves nothing --
    the CSS rule contains it too, so the check passes with the emitting branch
    disabled. Run the emitter."""

    def _marker(self, coord, coord_space):
        from potato.server_utils.schemas.gui_trajectory import (
            generate_gui_trajectory_layout)
        html, _ = generate_gui_trajectory_layout(
            {"annotation_type": "gui_trajectory", "name": "traj",
             "description": "d", "coord_space": coord_space})
        body = _inline_scripts(html)[0]
        probe = r"""
        const src = require('fs').readFileSync(process.argv[2], 'utf8');
        const at = src.indexOf('function markerHtml');
        let i = src.indexOf('{', at), depth = 0, end = -1;
        for (let j = i; j < src.length; j++) {
          if (src[j] === '{') depth++;
          else if (src[j] === '}') { depth--; if (!depth) { end = j + 1; break; } }
        }
        const CONFIG = { coord_space: process.argv[3] };
        const markerHtml = eval('(' + src.slice(at, end) + ')');
        console.log(JSON.stringify(markerHtml(JSON.parse(process.argv[4]))));
        """
        script = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8")
        payload = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                              encoding="utf-8")
        script.write(probe); script.close()
        payload.write(body); payload.close()
        try:
            result = subprocess.run(
                ["node", script.name, payload.name, coord_space,
                 json.dumps(coord)],
                capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        finally:
            os.unlink(script.name)
            os.unlink(payload.name)

    def test_pixel_mode_emits_a_marker(self):
        """It emitted the empty string: left was null and the emit was guarded
        on left !== null."""
        html = self._marker({"x": 420, "y": 120}, "pixels")
        assert html, "pixel mode must emit a marker"
        assert "gt-marker-pending" in html
        assert 'data-gt-x="420"' in html and 'data-gt-y="120"' in html

    def test_pixel_mode_does_not_position_inline(self):
        """Inline left/top in pixel space is what put the marker at 42000%."""
        html = self._marker({"x": 420, "y": 120}, "pixels")
        assert "style=" not in html

    def test_normalized_mode_positions_inline(self):
        html = self._marker({"x": 0.525, "y": 0.3}, "normalized")
        assert "left:52.5%" in html and "top:30%" in html
        assert "gt-marker-pending" not in html

    def test_no_coordinate_emits_no_marker(self):
        assert self._marker(None, "pixels") == ""
        assert self._marker(None, "normalized") == ""

    def test_the_origin_still_emits_a_marker(self, ):
        """0,0 is a real click position, not an absent one."""
        assert self._marker({"x": 0, "y": 0}, "pixels") != ""
        assert self._marker({"x": 0, "y": 0}, "normalized") != ""


# ---------------------------------------------------------------------------
# The guard this round earned.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
class TestEveryGeneratedScriptParses:
    """Schema generators build JavaScript by interpolating into Python
    f-strings, where a mis-escaped quote produces a page that parses as
    nothing and fails silently -- no error, no behaviour. One was introduced
    while fixing the marker above, and only opening the page caught it."""

    @staticmethod
    def _types():
        from potato.server_utils.schemas.registry import schema_registry
        return sorted(schema_registry.get_supported_types())

    @pytest.mark.parametrize("annotation_type", _types.__func__())
    def test_the_emitted_script_is_valid_javascript(self, annotation_type):
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {"annotation_type": annotation_type,
                  "name": f"s_{annotation_type}", "description": "d",
                  "labels": ["A", "B"], "options": ["A", "B"]}
        try:
            html, _ = schema_registry.generate(scheme)
        except Exception:
            pytest.skip(f"{annotation_type} needs more configuration")

        for index, body in enumerate(_inline_scripts(html)):
            ok, stderr = _node_check(body)
            assert ok, (f"{annotation_type} script {index} is not valid "
                        f"JavaScript:\n{stderr}")

    def test_the_guard_would_catch_an_unbalanced_quote(self):
        """A guard that cannot fail is not a guard."""
        ok, _ = _node_check("var a = 'unterminated;")
        assert not ok
