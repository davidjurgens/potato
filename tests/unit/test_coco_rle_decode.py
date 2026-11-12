"""
COCO RLE decoding -- the inverse direction, needed for import.

``rle_to_coco_rle`` (Potato -> COCO) already existed and is covered by
tests/unit/test_cv_utils_rle.py. Import needs the other direction, including
COCO's compressed ASCII ``counts`` string, which is where a stock COCO file
puts RLE segmentation.

The delta boundary in the encoder is ``i > 2``, not ``i >= 2``. The decoder has
to mirror that exactly; getting it wrong corrupts every mask long enough to
reach a third run and does so silently, so it is pinned here directly.
"""

import random

import pytest

from potato.export.cv_utils import (
    _decode_coco_rle_string,
    _encode_coco_rle_string,
    coco_rle_to_rle,
    decode_rle,
    polygons_to_rle,
    rle_to_coco_rle,
)


class TestStringCodecIsSelfInverse:
    """No pycocotools needed -- encode then decode must be the identity."""

    @pytest.mark.parametrize("counts", [
        [0],
        [5],
        [0, 4, 0],
        [2, 3, 1],
        [1, 2, 2, 2, 5],
        [10, 1, 10, 1, 10, 1, 10],
        # Long enough to exercise the i>2 delta path repeatedly
        [3, 7, 2, 9, 4, 1, 8, 6, 5, 2, 11, 3],
        # Large values force multi-group encoding
        [100000, 5, 99999, 7],
        # A descending run makes the deltas negative, exercising sign extension
        [50, 40, 30, 20, 10, 5, 1],
    ])
    def test_roundtrip(self, counts):
        assert _decode_coco_rle_string(_encode_coco_rle_string(counts)) == counts

    def test_roundtrip_random(self):
        rng = random.Random(20260812)
        for _ in range(200):
            counts = [rng.randint(0, 5000) for _ in range(rng.randint(1, 40))]
            encoded = _encode_coco_rle_string(counts)
            assert _decode_coco_rle_string(encoded) == counts, counts

    def test_delta_boundary_is_strictly_greater_than_two(self):
        """The 4th element (index 3) is the first one delta-encoded.

        If the decoder used ``>= 2`` it would start applying the delta one
        element early and every subsequent count would be wrong.
        """
        counts = [7, 11, 13, 17, 19]
        encoded = _encode_coco_rle_string(counts)
        assert _decode_coco_rle_string(encoded) == counts

        # Reproduce the off-by-one and confirm it actually diverges, so this
        # test would fail if the boundary were ever "corrected" to >= 2.
        wrong = []
        p, n = 0, len(encoded)
        while p < n:
            x, k, more = 0, 0, True
            while more:
                c = ord(encoded[p]) - 48
                x |= (c & 0x1F) << (5 * k)
                more = bool(c & 0x20)
                p += 1
                k += 1
                if not more and (c & 0x10):
                    x |= -1 << (5 * k)
            if len(wrong) >= 2:          # the bug
                x += wrong[-2]
            wrong.append(x)
        assert wrong != counts


class TestPotatoCocoRoundTrip:

    @pytest.mark.parametrize("bitmap,h,w", [
        ([0, 0, 1, 1, 1, 0], 2, 3),
        ([1, 1, 1, 1], 2, 2),
        ([0, 0, 0, 0], 2, 2),
        ([1, 0, 0, 1], 2, 2),
    ])
    def test_potato_to_coco_and_back(self, bitmap, h, w):
        counts = []
        current, run = 0, 0
        for v in bitmap:
            if v == current:
                run += 1
            else:
                counts.append(run)
                current = 1 - current
                run = 1
        counts.append(run)
        potato = {"counts": counts, "size": [h, w]}

        coco = rle_to_coco_rle(potato, w, h)
        back = coco_rle_to_rle(coco)

        assert back["size"] == [h, w]
        assert decode_rle(back, w, h) == bitmap

    def test_roundtrip_random_bitmaps(self):
        rng = random.Random(11235)
        for _ in range(60):
            h, w = rng.randint(1, 12), rng.randint(1, 12)
            bitmap = [rng.randint(0, 1) for _ in range(h * w)]
            counts, current, run = [], 0, 0
            for v in bitmap:
                if v == current:
                    run += 1
                else:
                    counts.append(run)
                    current = 1 - current
                    run = 1
            counts.append(run)

            coco = rle_to_coco_rle({"counts": counts, "size": [h, w]}, w, h)
            back = coco_rle_to_rle(coco)
            assert decode_rle(back, w, h) == bitmap, (h, w, bitmap)

    def test_accepts_uncompressed_counts(self):
        """COCO also ships RLE with counts as a plain int list."""
        # Column-major over a 2x3 (h=2, w=3): 2 zeros then 4 ones
        coco = {"counts": [2, 4], "size": [2, 3]}
        potato = coco_rle_to_rle(coco)
        assert sum(potato["counts"]) == 6
        assert decode_rle(potato, 3, 2).count(1) == 4

    def test_missing_size_is_a_hard_error(self):
        with pytest.raises(ValueError, match="size"):
            coco_rle_to_rle({"counts": "abc"})


class TestAgainstPycocotools:
    """Validate against the reference implementation when it is installed."""

    def test_decode_matches_pycocotools(self):
        pytest.importorskip("pycocotools")
        import numpy as np
        from pycocotools import mask as mask_utils

        rng = random.Random(4242)
        for _ in range(15):
            h, w = rng.randint(2, 16), rng.randint(2, 16)
            arr = np.array(
                [[rng.randint(0, 1) for _ in range(w)] for _ in range(h)],
                dtype=np.uint8, order="F")
            encoded = mask_utils.encode(arr)

            potato = coco_rle_to_rle({
                "counts": encoded["counts"].decode("ascii"),
                "size": list(encoded["size"]),
            })
            decoded = decode_rle(potato, w, h)
            expected = [int(arr[y][x]) for y in range(h) for x in range(w)]
            assert decoded == expected, (h, w)

    def test_string_codec_matches_pycocotools_counts(self):
        pytest.importorskip("pycocotools")
        import numpy as np
        from pycocotools import mask as mask_utils

        arr = np.array([[1, 0, 1], [0, 1, 0]], dtype=np.uint8, order="F")
        encoded = mask_utils.encode(arr)
        raw = encoded["counts"].decode("ascii")

        # Our decoder must read their string, and our encoder must reproduce it.
        counts = _decode_coco_rle_string(raw)
        assert _encode_coco_rle_string(counts) == raw


class TestPolygonsToRLE:

    def test_fills_a_rectangle(self):
        rle = polygons_to_rle([[1, 1, 4, 1, 4, 3, 1, 3]], height=5, width=5)
        decoded = decode_rle(rle, 5, 5)
        filled = {(i % 5, i // 5) for i, v in enumerate(decoded) if v}
        assert filled == {(x, y) for x in range(1, 4) for y in range(1, 3)}

    def test_accepts_point_pair_rings(self):
        flat = polygons_to_rle([[1, 1, 4, 1, 4, 3, 1, 3]], height=5, width=5)
        pairs = polygons_to_rle([[[1, 1], [4, 1], [4, 3], [1, 3]]],
                                height=5, width=5)
        assert flat == pairs

    def test_inner_ring_is_a_hole(self):
        """COCO encodes holes as an additional ring; even-odd fill honours it."""
        outer = [0, 0, 6, 0, 6, 6, 0, 6]
        inner = [2, 2, 4, 2, 4, 4, 2, 4]
        solid = decode_rle(polygons_to_rle([outer], 6, 6), 6, 6)
        holed = decode_rle(polygons_to_rle([outer, inner], 6, 6), 6, 6)
        assert sum(holed) < sum(solid)

    def test_degenerate_ring_is_ignored(self):
        rle = polygons_to_rle([[0, 0, 1, 1]], height=4, width=4)
        assert sum(decode_rle(rle, 4, 4)) == 0
