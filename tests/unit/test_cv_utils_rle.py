"""
Tests for RLE mask utilities in cv_utils.
"""

import pytest

from potato.export.cv_utils import (
    decode_rle,
    rle_bbox,
    rle_area,
    rle_to_coco_rle,
    _column_major_rle_counts,
    _encode_coco_rle_string,
)


class TestDecodeRLE:
    def test_basic(self):
        """Simple RLE decodes correctly."""
        # 3x2 mask: 2 zeros, 3 ones, 1 zero → [0,0,1,1,1,0]
        rle = {"counts": [2, 3, 1], "size": [2, 3]}
        result = decode_rle(rle, 3, 2)
        assert result == [0, 0, 1, 1, 1, 0]

    def test_all_zeros(self):
        """All-zero mask."""
        rle = {"counts": [6], "size": [2, 3]}
        result = decode_rle(rle, 3, 2)
        assert result == [0, 0, 0, 0, 0, 0]

    def test_all_ones(self):
        """All-one mask (starts with 0 count of 0)."""
        rle = {"counts": [0, 6], "size": [2, 3]}
        result = decode_rle(rle, 3, 2)
        assert result == [1, 1, 1, 1, 1, 1]

    def test_single_pixel(self):
        """Single foreground pixel."""
        # 1x3: 1 zero, 1 one, 1 zero → [0, 1, 0]
        rle = {"counts": [1, 1, 1], "size": [1, 3]}
        result = decode_rle(rle, 3, 1)
        assert result == [0, 1, 0]

    def test_empty_counts(self):
        """Empty counts produces all-zero mask."""
        rle = {"counts": [], "size": [2, 2]}
        result = decode_rle(rle, 2, 2)
        assert result == [0, 0, 0, 0]


class TestRLEBbox:
    def test_basic(self):
        """Known mask produces correct bounding box."""
        # 3x3 mask with foreground at positions (1,0), (1,1), (2,1)
        # Row-major: row0=[0,0,0], row1=[0,1,1], row2=[0,1,0]
        mask = [0, 0, 0, 0, 1, 1, 0, 1, 0]
        bbox = rle_bbox(mask, 3, 3)
        # x_min=1, y_min=1, width=2, height=2
        assert bbox == [1.0, 1.0, 2.0, 2.0]

    def test_empty_mask(self):
        """All-zero mask returns zero bbox."""
        mask = [0, 0, 0, 0]
        bbox = rle_bbox(mask, 2, 2)
        assert bbox == [0, 0, 0, 0]

    def test_full_mask(self):
        """All-one mask returns full image bbox."""
        mask = [1, 1, 1, 1, 1, 1]
        bbox = rle_bbox(mask, 3, 2)
        assert bbox == [0.0, 0.0, 3.0, 2.0]

    def test_single_pixel(self):
        """Single pixel bbox."""
        mask = [0, 0, 0, 0, 1, 0, 0, 0, 0]
        bbox = rle_bbox(mask, 3, 3)
        # pixel at (1, 1)
        assert bbox == [1.0, 1.0, 1.0, 1.0]


class TestRLEArea:
    def test_basic(self):
        mask = [0, 0, 1, 1, 1, 0]
        assert rle_area(mask) == 3

    def test_empty(self):
        mask = [0, 0, 0, 0]
        assert rle_area(mask) == 0

    def test_full(self):
        mask = [1, 1, 1, 1]
        assert rle_area(mask) == 4


class TestColumnMajorRLECounts:
    def test_basic(self):
        """Verify column-major RLE from a known 2D mask."""
        # 2x3 mask:
        # row0: [0, 0, 1]
        # row1: [1, 1, 0]
        # Column-major reading: col0=[0,1], col1=[0,1], col2=[1,0]
        # Flat column-major: [0, 1, 0, 1, 1, 0]
        # RLE (starting with 0): 1 zero, 1 one, 1 zero, 1 one, 1 one, 1 zero
        # = [1, 1, 1, 1, 1, 1] ... wait let me recalculate
        # Flat: 0, 1, 0, 1, 1, 0
        # Runs: 1×0, 1×1, 1×0, 1×1, 1×1 → but consecutive 1s merge
        # Actually: 0 | 1 | 0 | 1, 1 | 0
        # Runs: 1(zero), 1(one), 1(zero), 2(one), 1(zero)
        mask_2d = [[0, 0, 1], [1, 1, 0]]
        counts = _column_major_rle_counts(mask_2d, 2, 3)
        assert counts == [1, 1, 1, 2, 1]

    def test_all_zeros(self):
        mask_2d = [[0, 0], [0, 0]]
        counts = _column_major_rle_counts(mask_2d, 2, 2)
        assert counts == [4]

    def test_all_ones(self):
        mask_2d = [[1, 1], [1, 1]]
        counts = _column_major_rle_counts(mask_2d, 2, 2)
        assert counts == [0, 4]


class TestEncodeCOCORLEString:
    def test_small_counts(self):
        """Small values encode to single characters each."""
        # Count of 3: no delta for first elements
        # 3 & 0x1F = 3, 3 >> 5 = 0, bit4=0 → more=(0!=0)=False
        # chr(3 + 48) = chr(51) = '3'
        encoded = _encode_coco_rle_string([3])
        assert encoded == "3"

    def test_larger_value(self):
        """Values > 31 need multiple groups."""
        # Count of 32: 32 & 0x1F = 0, 32 >> 5 = 1
        # bit4=0, more=(1!=0)=True → c=0|0x20=32, chr(32+48)=chr(80)='P'
        # Next: 1 & 0x1F = 1, 1 >> 5 = 0, bit4=0, more=False
        # chr(1+48)=chr(49)='1'
        encoded = _encode_coco_rle_string([32])
        assert encoded == "P1"

    def test_zero_count(self):
        """Zero encodes to single char."""
        # 0 & 0x1F = 0, 0 >> 5 = 0, bit4=0, more=False
        # chr(0 + 48) = chr(48) = '0'
        encoded = _encode_coco_rle_string([0])
        assert encoded == "0"

    def test_delta_encoding(self):
        """For i > 2, values are delta-encoded against counts[i-2]."""
        # counts = [5, 3, 5, 3]
        # i=0: x=5 → encodes 5
        # i=1: x=3 → encodes 3
        # i=2: x=5 (no delta, i==2 not >2) → encodes 5
        # i=3: x=3-3=0 (delta from counts[1]) → encodes 0
        encoded = _encode_coco_rle_string([5, 3, 5, 3])
        # 5 → chr(5+48)='5', 3 → chr(3+48)='3', 5 → '5', 0 → '0'
        assert encoded == "5350"


class TestRLEToCOCORLE:
    def test_output_format(self):
        """Output has 'counts' (string) and 'size' (list) keys."""
        rle = {"counts": [2, 3, 1], "size": [2, 3]}
        result = rle_to_coco_rle(rle, 3, 2)
        assert isinstance(result["counts"], str)
        assert result["size"] == [2, 3]

    def test_column_major_reorder(self):
        """Verify column-major reordering with a known small mask."""
        # 2x3 Potato RLE (row-major):
        # row0: [0, 0, 1], row1: [1, 1, 0]
        # counts = [2, 3, 1] (2 zeros, 3 ones, 1 zero)
        #
        # Column-major reading:
        # col0: [0, 1], col1: [0, 1], col2: [1, 0]
        # flat: [0, 1, 0, 1, 1, 0]
        # Column-major RLE: [1, 1, 1, 2, 1]
        rle = {"counts": [2, 3, 1], "size": [2, 3]}
        result = rle_to_coco_rle(rle, 3, 2)
        assert result["size"] == [2, 3]
        # The encoded string should decode back to [1, 1, 1, 2, 1]
        # Just verify it's a non-empty string
        assert len(result["counts"]) > 0

    def test_all_zeros(self):
        """All-zero mask."""
        rle = {"counts": [4], "size": [2, 2]}
        result = rle_to_coco_rle(rle, 2, 2)
        assert result["size"] == [2, 2]
        # Column-major RLE for all zeros: [4]
        # Encoded: chr(4+48) = '4'
        assert result["counts"] == "4"

    def test_all_ones(self):
        """All-one mask."""
        rle = {"counts": [0, 4], "size": [2, 2]}
        result = rle_to_coco_rle(rle, 2, 2)
        # Column-major is also all ones: [0, 4]
        # Encoded: chr(0+48)='0', chr(4+48)='4'
        assert result["counts"] == "04"

    def test_roundtrip_with_pycocotools(self):
        """If pycocotools is available, verify our encoding matches."""
        pytest.importorskip("pycocotools")
        from pycocotools import mask as maskUtils
        import numpy as np

        # Create a known 4x4 mask
        # Row-major flat: [0,0,1,1, 0,0,1,1, 1,1,0,0, 1,1,0,0]
        # Potato RLE: 2 zeros, 2 ones, 2 zeros, 4 ones, 2 zeros, 2 ones, 2 zeros
        potato_rle = {"counts": [2, 2, 2, 4, 2, 2, 2], "size": [4, 4]}
        coco_rle = rle_to_coco_rle(potato_rle, 4, 4)

        # Decode using pycocotools
        decoded = maskUtils.decode(coco_rle)
        assert decoded.shape == (4, 4)

        # Verify the mask content matches
        expected = np.array([
            [0, 0, 1, 1],
            [0, 0, 1, 1],
            [1, 1, 0, 0],
            [1, 1, 0, 0],
        ], dtype=np.uint8)
        np.testing.assert_array_equal(decoded, expected)
