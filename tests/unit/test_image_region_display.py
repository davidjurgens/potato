"""image_region: the crop geometry the CSS encodes, and its fallbacks."""

import re

from potato.server_utils.displays import display_registry
from potato.server_utils.displays.image_region_display import ImageRegionDisplay

DATA = {"image": "/media/page.png", "width": 1000, "height": 700,
        "region": [120, 190, 760, 56],
        "polygon": [[120, 190], [880, 190], [880, 246], [120, 246]]}


def _style(html, cls):
    match = re.search(rf'class="{cls}"[^>]*style="([^"]+)"', html) or \
        re.search(rf'<img src="[^"]+" alt="" draggable="false" style="([^"]+)"', html)
    return match.group(1)


def test_registered():
    assert "image_region" in display_registry.get_supported_types()
    html = display_registry.render("image_region", {"key": "line_image"}, DATA)
    assert 'class="image-region"' in html


def test_crop_geometry_shows_the_padded_region():
    html = ImageRegionDisplay().render({"key": "line_image", "padding": 8}, DATA)
    # crop = (112, 182) .. (888, 254): 776 x 72
    crop = re.search(r'class="image-region-crop"[^>]*style="([^"]+)"', html).group(1)
    assert "aspect-ratio: 776 / 72" in crop
    img = re.search(r'draggable="false" style="([^"]+)"', html).group(1)
    width = float(re.search(r"width: ([0-9.]+)%", img).group(1))
    left = float(re.search(r"left: (-[0-9.]+)%", img).group(1))
    top = float(re.search(r"top: (-[0-9.]+)%", img).group(1))
    assert width == round(1000 / 776 * 100, 6)
    assert left == round(-112 / 776 * 100, 6)
    assert top == round(-182 / 72 * 100, 6)
    assert '<polygon points="120,190 880,190 880,246 120,246"/>' in html
    assert 'viewBox="112 182 776 72"' in html
    assert "Show the whole image" in html


def test_padding_is_clamped_to_the_image():
    data = dict(DATA, region=[0, 0, 100, 50])
    html = ImageRegionDisplay().render({"key": "k", "padding": 20}, data)
    assert 'viewBox="0 0 120 70"' in html


def test_region_from_polygon_alone_and_options_off():
    data = {k: v for k, v in DATA.items() if k != "region"}
    html = ImageRegionDisplay().render({"key": "k", "outline": False, "show_page": False,
                                        "padding": 0}, data)
    assert "aspect-ratio: 760 / 56" in html
    assert "<svg" not in html and "<details" not in html


def test_unknown_size_falls_back_to_whole_image_with_a_note():
    data = {"image": "/media/page.png", "region": [1, 2, 3, 4]}
    html = ImageRegionDisplay().render({"key": "k"}, data)
    assert "cannot be cropped" in html and 'src="/media/page.png"' in html


def test_escapes_and_refuses_script_urls():
    html = ImageRegionDisplay().render({"key": "k"}, dict(DATA, image='/m/a".png'))
    assert 'src="/m/a&quot;.png"' in html
    assert "Invalid image URL" in ImageRegionDisplay().render({"key": "k"},
                                                             dict(DATA, image="javascript:alert(1)"))
    assert "No image" in ImageRegionDisplay().render({"key": "k"}, None)
