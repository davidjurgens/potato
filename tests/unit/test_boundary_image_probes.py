"""
Boundary Lab on image items.

Before this, an image project got nothing: `_instance_text` fell back to
`get_text()`, whose answer for a media item is the instance id, and the rule
transforms find no handle on "img_01" — measured, zero probes for `img_01`,
`clip_7` and `media/cat.jpg`. The panel simply never appeared, on a feature the
project had explicitly enabled.

The visual probes ask the same two questions the text probes ask. Invariance:
does your label survive the picture in greyscale, mirrored, slightly cropped?
Flip: does it survive part of the evidence being taken away? Every transform is
applied by the browser to the original image, so nothing is rendered
server-side and remote media is never fetched.
"""

import pytest

from potato.boundary.image_probes import (
    KIND_FLIP,
    KIND_INVARIANCE,
    generate_image_probes,
    to_style,
    transform_id,
)
from potato.boundary.routes import _image_reference


class TestImageDetection:
    def test_a_named_image_field(self):
        assert _image_reference({"id": "1", "image_url": "media/cat.jpg"}) == \
            "media/cat.jpg"

    def test_an_extension_without_a_known_field_name(self):
        assert _image_reference({"id": "1", "stimulus": "shots/a.png"}) == \
            "shots/a.png"

    def test_a_query_string_does_not_hide_it(self):
        assert _image_reference({"id": "1", "src": "https://x/a.jpg?w=8"})

    def test_a_text_item_is_not_an_image(self):
        assert _image_reference({"id": "1", "text": "hello"}) is None

    def test_a_video_item_is_not_an_image(self):
        assert _image_reference({"id": "1", "video_url": "clip.mp4"}) is None

    def test_junk(self):
        assert _image_reference(None) is None
        assert _image_reference({}) is None


class TestProbeGeneration:
    def test_it_produces_the_requested_mix(self):
        probes = generate_image_probes("media/cat.jpg", 2, 1)
        kinds = [kind for _t, kind, _h in probes]
        assert kinds.count(KIND_FLIP) == 2
        assert kinds.count(KIND_INVARIANCE) == 1

    def test_flips_come_first(self):
        """Same ordering as the text probes: the invariance gotcha reads last."""
        kinds = [k for _t, k, _h in generate_image_probes("x.jpg", 2, 1)]
        assert kinds == [KIND_FLIP, KIND_FLIP, KIND_INVARIANCE]

    def test_every_probe_explains_itself(self):
        for _t, _k, hint in generate_image_probes("x.jpg", 3, 2):
            assert hint and hint == hint.strip()

    def test_it_is_deterministic(self):
        """Annotators must be answering about the same transformed images."""
        first = generate_image_probes("x.jpg", 2, 1)
        second = generate_image_probes("x.jpg", 2, 1)
        assert first == second

    def test_no_reference_no_probes(self):
        assert generate_image_probes("", 2, 1) == []

    def test_a_zero_budget(self):
        assert generate_image_probes("x.jpg", 0, 0) == []

    def test_it_never_exceeds_what_it_has(self):
        probes = generate_image_probes("x.jpg", 50, 50)
        assert len(probes) <= 12


class TestTransformIds:
    def test_the_id_follows_the_transform_not_the_wording(self):
        """Re-wording a hint must not orphan the verdicts already collected."""
        one = transform_id("x.jpg", {"filter": "grayscale(1)"})
        two = transform_id("x.jpg", {"filter": "grayscale(1)"})
        assert one == two

    def test_different_transforms_differ(self):
        assert transform_id("x.jpg", {"filter": "grayscale(1)"}) != \
            transform_id("x.jpg", {"mirror": True})

    def test_different_images_differ(self):
        assert transform_id("a.jpg", {"mirror": True}) != \
            transform_id("b.jpg", {"mirror": True})

    def test_key_order_does_not_change_the_id(self):
        a = transform_id("x.jpg", {"filter": "blur(3px)", "mirror": True})
        b = transform_id("x.jpg", {"mirror": True, "filter": "blur(3px)"})
        assert a == b


class TestStyleRecipes:
    def test_a_filter_passes_through(self):
        assert to_style({"filter": "grayscale(1)"}) == {"filter": "grayscale(1)"}

    def test_a_mirror(self):
        assert to_style({"mirror": True})["mirror"] is True

    def test_a_crop_becomes_an_inset(self):
        style = to_style({"crop": [0.1, 0.1, 0.1, 0.1]})
        assert style["inset"] == [0.1, 0.1, 0.1, 0.1]

    def test_an_occlusion_rectangle(self):
        style = to_style({"occlude": [0.3, 0.3, 0.4, 0.4]})
        assert style["occlude"] == [0.3, 0.3, 0.4, 0.4]

    def test_out_of_range_values_are_clamped(self):
        """A crop of 1.0 would clip the whole image away."""
        assert to_style({"crop": [2.0, -1.0, 0.5, 0.5]})["inset"][:2] == [0.9, 0.0]
        assert to_style({"occlude": [-1, 2, 0.5, 0.5]})["occlude"][:2] == [0.0, 1.0]

    def test_an_unknown_transform_yields_nothing_to_apply(self):
        assert to_style({"rotate": 90}) == {}


class TestTheClientRendersThem:
    def source(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        return (root / "potato" / "static" / "boundary-probe.js").read_text()

    def test_the_panel_has_an_image_path(self):
        assert "function probeImage" in self.source()

    def test_it_is_reached_from_the_dispatch(self):
        source = self.source()
        body = source[source.index("function probeText("):][:400]
        assert "probe.media" in body and "probeImage(probe)" in body

    def test_the_image_is_built_with_dom_calls(self):
        """The src is an item field; string-building it invites markup."""
        source = self.source()
        body = source[source.index("function probeImage"):][:2600]
        assert "createElement" in body
        assert "innerHTML" not in body

    def test_both_versions_are_shown(self):
        body = self.source()
        body = body[body.index("function probeImage"):][:2600]
        assert "'Original'" in body

    def test_the_transformed_image_has_an_accessible_name(self):
        body = self.source()
        body = body[body.index("function probeImage"):][:2600]
        assert "img.alt" in body and "edit_hint" in body
