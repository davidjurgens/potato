"""Unit tests for judge_calibration calibration-sample selection."""

from potato.judge_calibration.config import SamplingConfig
from potato.judge_calibration.sampler import select_calibration_sample


class TestSampler:
    def test_all(self):
        ids = [f"i{n}" for n in range(20)]
        cfg = SamplingConfig(strategy="all")
        assert select_calibration_sample(ids, cfg) == sorted(ids)

    def test_random_size_and_determinism(self):
        ids = [f"i{n}" for n in range(100)]
        cfg = SamplingConfig(strategy="random", sample_size=10, seed=1)
        a = select_calibration_sample(ids, cfg)
        b = select_calibration_sample(ids, cfg)
        assert len(a) == 10
        assert a == b  # deterministic for a fixed seed

    def test_random_different_seed_differs(self):
        ids = [f"i{n}" for n in range(100)]
        a = select_calibration_sample(ids, SamplingConfig(strategy="random", sample_size=10, seed=1))
        b = select_calibration_sample(ids, SamplingConfig(strategy="random", sample_size=10, seed=2))
        assert a != b

    def test_sample_size_caps_at_population(self):
        ids = ["a", "b", "c"]
        cfg = SamplingConfig(strategy="random", sample_size=99)
        assert sorted(select_calibration_sample(ids, cfg)) == ["a", "b", "c"]

    def test_stratified_covers_strata(self):
        # 90 of label A, 10 of label B; stratified sample should include some B.
        ids = [f"a{n}" for n in range(90)] + [f"b{n}" for n in range(10)]
        strata = {i: ("A" if i.startswith("a") else "B") for i in ids}
        cfg = SamplingConfig(strategy="stratified", sample_size=20, seed=3)
        out = select_calibration_sample(ids, cfg, stratum_of=lambda i: strata[i])
        assert len(out) <= 20
        assert any(i.startswith("b") for i in out)  # minority stratum represented

    def test_stratified_without_mapping_falls_back(self):
        ids = [f"i{n}" for n in range(50)]
        cfg = SamplingConfig(strategy="stratified", sample_size=10, seed=5)
        out = select_calibration_sample(ids, cfg, stratum_of=None)
        assert len(out) == 10

    def test_empty(self):
        assert select_calibration_sample([], SamplingConfig()) == []
