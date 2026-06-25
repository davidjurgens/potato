"""Unit tests for judge_calibration calibration math (known-value fixtures)."""

import pytest
from potato.judge_calibration.calibration import (
    expected_calibration_error,
    reliability_bins,
    brier_score,
    _bin_index,
)


class TestBinIndex:
    def test_endpoints(self):
        assert _bin_index(0.0, 10) == 0
        assert _bin_index(1.0, 10) == 9  # 1.0 lands in last bin, not out of range
        assert _bin_index(0.05, 10) == 0
        assert _bin_index(0.15, 10) == 1
        assert _bin_index(0.95, 10) == 9


class TestECE:
    def test_perfectly_calibrated_is_zero(self):
        # In each used bin accuracy == mean confidence -> ECE 0.
        # bin [0.0,0.5): conf 0.0, all wrong (acc 0). bin [1.0]: conf 1.0 all right.
        conf = [0.0, 0.0, 1.0, 1.0]
        corr = [0, 0, 1, 1]
        assert expected_calibration_error(conf, corr, n_bins=2) == 0.0

    def test_fully_confident_half_wrong(self):
        # All confidence 1.0 but only half correct -> ECE = |0.5 - 1.0| = 0.5
        conf = [1.0, 1.0, 1.0, 1.0]
        corr = [1, 1, 0, 0]
        assert expected_calibration_error(conf, corr, n_bins=10) == 0.5

    def test_known_mixed_value(self):
        # Two bins, equal counts.
        # bin A (conf 0.2): acc 0.0 -> gap 0.2, weight 0.5
        # bin B (conf 0.8): acc 1.0 -> gap 0.2, weight 0.5
        # ECE = 0.5*0.2 + 0.5*0.2 = 0.2
        conf = [0.2, 0.2, 0.8, 0.8]
        corr = [0, 0, 1, 1]
        assert expected_calibration_error(conf, corr, n_bins=10) == 0.2

    def test_empty(self):
        assert expected_calibration_error([], [], 10) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            reliability_bins([0.1], [1, 0], 10)


class TestReliabilityBins:
    def test_counts_and_stats(self):
        # conf 0.1 -> bin index int(0.1*10)=1 ; conf 0.9 -> bin 9
        conf = [0.1, 0.1, 0.9]
        corr = [0, 1, 1]
        bins = reliability_bins(conf, corr, n_bins=10)
        assert len(bins) == 10
        assert bins[1]["count"] == 2
        assert bins[1]["mean_confidence"] == 0.1
        assert bins[1]["accuracy"] == 0.5
        assert bins[9]["count"] == 1
        assert bins[9]["accuracy"] == 1.0
        # empty bins present
        assert bins[0]["count"] == 0
        assert bins[5]["count"] == 0


class TestBrier:
    def test_perfect(self):
        assert brier_score([1.0, 0.0], [1, 0]) == 0.0

    def test_worst(self):
        assert brier_score([0.0, 1.0], [1, 0]) == 1.0

    def test_known(self):
        # (0.5-1)^2 + (0.5-0)^2 = 0.25+0.25 = 0.5 ; mean = 0.25
        assert brier_score([0.5, 0.5], [1, 0]) == 0.25
