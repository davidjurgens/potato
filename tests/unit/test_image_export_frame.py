"""A box lands where it was drawn, whatever the file is.

The annotator draws in the frame the BROWSER shows. The export measures the
frame PILLOW reads. Two things made those disagree, and in both the export
looked clean while every coordinate in it was wrong.

EXIF orientation. Chrome applies the orientation tag before painting, and
reports the corrected size: a JPEG stored 160x240 with orientation 6 is
`naturalWidth: 240, naturalHeight: 160` (measured, not assumed). PIL reports
the stored 160x240. Coordinates are stored normalized, so the two get
multiplied together and a box on the subject comes out on a 90-degree rotation
of the picture. Measured on the fixture below, a box on the marker at
[10, 10, 60, 40] exported as [6.67, 15.0, 40.0, 60.0].

SVG. Pillow cannot open one, so the size fell through to (0, 0) and every
normalized coordinate multiplied to zero: `[0, 0, 0, 0]` for every object, with
`"warnings": []` beside it. An SVG states its own size in its opening tag.

The third case -- a file that genuinely cannot be measured -- still exports
zeros, because there is nothing else to write. What changed is that it says so.

Expected values here are computed from the fixture geometry, never from the
exporter.
"""

import json
import logging
import os
import tempfile

import pytest

pytest.importorskip("PIL")

# The fixture, as a human sees it: 240x160 with a marker at (10, 10)-(70, 50).
SEEN_W, SEEN_H = 240, 160
MARKER = (10, 10, 60, 40)  # x, y, w, h in displayed pixels


@pytest.fixture
def media(tmp_path):
    """A media directory holding the same picture in three encodings."""
    from PIL import Image, ImageDraw

    folder = tmp_path / "media"
    folder.mkdir()

    displayed = Image.new("RGB", (SEEN_W, SEEN_H), (240, 240, 240))
    ImageDraw.Draw(displayed).rectangle(
        [MARKER[0], MARKER[1], MARKER[0] + MARKER[2], MARKER[1] + MARKER[3]],
        fill=(220, 30, 30))
    displayed.save(folder / "upright.jpg", quality=95)

    # Orientation 6 is "rotate 90 CW to display", so the stored pixels are the
    # displayed image rotated 90 CCW -- 160x240 on disk, 240x160 on screen.
    exif = Image.Exif()
    exif[0x0112] = 6
    displayed.rotate(90, expand=True).save(
        folder / "rotated.jpg", quality=95, exif=exif)

    (folder / "chart.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{SEEN_W}" height="{SEEN_H}">'
        f'<rect x="{MARKER[0]}" y="{MARKER[1]}" width="{MARKER[2]}" '
        f'height="{MARKER[3]}" fill="red"/></svg>')

    from potato.export import cv_utils

    cv_utils._DIMENSION_CACHE.clear()
    cv_utils._UNMEASURABLE_SEEN.clear()
    return tmp_path


def export_one(project, filename):
    """Export one bbox drawn on the marker, and return (image entry, bbox)."""
    from potato.export.base import ExportContext
    from potato.export.coco_exporter import COCOExporter

    objects = [{"type": "bbox", "label": "marker", "coordinates": {
        "x": MARKER[0] / SEEN_W, "y": MARKER[1] / SEEN_H,
        "width": MARKER[2] / SEEN_W, "height": MARKER[3] / SEEN_H}}]
    annotation = {"instance_id": "i1", "user": "u1",
                  "labels": {"boxes": {"_data": json.dumps(objects)}},
                  "spans": {}, "links": {},
                  "image_annotations": {"boxes": objects}}
    context = ExportContext(
        config={"task_dir": str(project), "media_directory": "media"},
        annotations=[annotation],
        items={"i1": {"id": "i1", "image_url": f"/media/{filename}"}},
        schemas=[{"annotation_type": "image_annotation", "name": "boxes",
                  "labels": ["marker"]}],
        output_dir="")
    with tempfile.TemporaryDirectory() as out:
        result = COCOExporter().export(context, out)
        with open(os.path.join(out, "annotations.json")) as fh:
            data = json.load(fh)
    box = [round(v, 2) for v in data["annotations"][0]["bbox"]]
    return data["images"][0], box, list(result.warnings or [])


class TestTheBoxLandsOnTheMarker:

    @pytest.mark.parametrize("filename", ["upright.jpg", "rotated.jpg",
                                          "chart.svg"])
    def test_every_encoding_gives_the_same_box(self, media, filename):
        image, box, _warnings = export_one(media, filename)
        assert (image["width"], image["height"]) == (SEEN_W, SEEN_H), (
            f"{filename} was measured in a frame the annotator never saw")
        assert box == [float(v) for v in MARKER], (
            f"{filename}: the box was drawn on the marker at {list(MARKER)} "
            f"and exported at {box}")

    def test_the_rotated_file_really_is_stored_transposed(self, media):
        """Without this, the EXIF case could pass by simply not being rotated."""
        from PIL import Image

        with Image.open(media / "media" / "rotated.jpg") as stored:
            assert (stored.width, stored.height) == (SEEN_H, SEEN_W)
            assert stored.getexif().get(0x0112) == 6


class TestAnUnmeasurableImageSaysSo:
    """Zero stays zero -- there is nothing else to write -- but not in silence."""

    def test_the_export_result_carries_a_warning(self, media):
        image, box, warnings = export_one(media, "absent.png")
        assert (image["width"], image["height"]) == (0, 0)
        assert box == [0.0, 0.0, 0.0, 0.0]
        assert any("absent.png" in w for w in warnings), (
            "zeros were written with an empty warning list, which reads as a "
            "clean run over annotations that all sit at the origin")

    def test_it_is_logged_as_well(self, media, caplog):
        from potato.export.cv_utils import get_image_dimensions

        with caplog.at_level(logging.WARNING):
            size = get_image_dimensions(
                {"id": "i1", "image_url": "/media/absent.png"},
                config={"task_dir": str(media), "media_directory": "media"})
        assert size == (0, 0)
        assert "absent.png" in " ".join(r.getMessage() for r in caplog.records)

    def test_a_measurable_image_says_nothing(self, media, caplog):
        from potato.export.cv_utils import get_image_dimensions

        with caplog.at_level(logging.WARNING):
            size = get_image_dimensions(
                {"id": "i1", "image_url": "/media/upright.jpg"},
                config={"task_dir": str(media), "media_directory": "media"})
        assert size == (SEEN_W, SEEN_H)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_item_metadata_still_wins_over_the_file(self, media, caplog):
        """An item that states its own size must not be warned about, and must
        not be overridden by whatever is on disk."""
        from potato.export.cv_utils import get_image_dimensions

        with caplog.at_level(logging.WARNING):
            size = get_image_dimensions(
                {"id": "i1", "image_url": "/media/absent.png",
                 "image_width": 640, "image_height": 480},
                config={"task_dir": str(media), "media_directory": "media"})
        assert size == (640, 480)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


class TestSvgDimensionParsing:
    """The opening tag is read with a bounded regex over the first 8 KB, not an
    XML parser -- the file is annotator-supplied."""

    def _size(self, tmp_path, body):
        from potato.export.cv_utils import _svg_dimensions

        path = tmp_path / "s.svg"
        path.write_text(body)
        return _svg_dimensions(str(path))

    @pytest.mark.parametrize("body", [
        '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="160"/>',
        '<svg width="240px" height="160px"/>',
        '<svg viewBox="0 0 240 160"/>',
        '<svg viewBox="0,0,240,160"/>',
        '<?xml version="1.0"?>\n<svg\n  width="240"\n  height="160">\n</svg>',
        "<svg width='240' height='160'/>",
    ])
    def test_it_reads_the_size(self, tmp_path, body):
        assert self._size(tmp_path, body) == (SEEN_W, SEEN_H)

    def test_a_percentage_falls_back_to_the_viewbox(self, tmp_path):
        """A responsive SVG states no pixel size; the viewBox is the real one."""
        assert self._size(
            tmp_path,
            '<svg width="100%" height="100%" viewBox="0 0 240 160"/>'
        ) == (SEEN_W, SEEN_H)

    @pytest.mark.parametrize("body", [
        "<svg/>",
        "<html><body>not an svg at all</body></html>",
        '<svg width="0" height="0"/>',
        '<svg width="abc" height="def"/>',
    ])
    def test_an_unreadable_svg_is_none_rather_than_a_guess(self, tmp_path, body):
        assert self._size(tmp_path, body) is None

    def test_a_huge_file_is_not_read_whole(self, tmp_path):
        """The tag is at the top by definition; a 50 MB SVG must not be slurped
        to learn two numbers."""
        body = ('<svg width="240" height="160">'
                + '<rect x="1" y="1" width="1" height="1"/>' * 200000
                + '</svg>')
        assert self._size(tmp_path, body) == (SEEN_W, SEEN_H)
