"""
Unit tests for the overlap sampler.
"""

import pytest

from potato.item_state_management import ItemStateManager
from potato.server_utils.overlap_sampler import apply_overlap_sample


def _build(n_items=20, with_category=False, config_overrides=None):
    config = {
        "random_seed": 123,
        "num_annotators_per_item": {
            "default": 1,
            "overlap_sample": {"fraction": 0.2, "count": 3, "seed": 42},
        },
    }
    if with_category:
        config["item_properties"] = {"category_key": "category"}
        config["num_annotators_per_item"]["overlap_sample"]["stratify_by"] = "category"
    if config_overrides:
        config.update(config_overrides)
    ism = ItemStateManager(config)
    for i in range(n_items):
        cat = "A" if i < n_items // 2 else "B"
        ism.add_item(f"item_{i:02d}", {"text": f"t{i}", "category": cat})
    return ism, config


class TestOverlapSampler:
    def test_basic_fraction(self):
        ism, config = _build(n_items=20)
        sampled = apply_overlap_sample(ism, config)
        assert len(sampled) == 4  # 20% of 20
        assert all(v == 3 for v in sampled.values())

    def test_stratification_balanced(self):
        ism, config = _build(n_items=20, with_category=True)
        sampled = apply_overlap_sample(ism, config)
        a = sum(1 for iid in sampled if int(iid.split("_")[1]) < 10)
        b = sum(1 for iid in sampled if int(iid.split("_")[1]) >= 10)
        # Each stratum has 10 items, 20% each = 2 each.
        assert a == 2
        assert b == 2

    def test_determinism(self):
        ism1, config = _build(n_items=20, with_category=True)
        ism2, _ = _build(n_items=20, with_category=True)
        s1 = apply_overlap_sample(ism1, config)
        s2 = apply_overlap_sample(ism2, config)
        assert sorted(s1) == sorted(s2)

    def test_per_item_cap_visible(self):
        ism, config = _build(n_items=20)
        sampled = apply_overlap_sample(ism, config)
        for iid in sampled:
            assert ism._get_annotator_cap_for_item(iid) == 3
        unsampled = set(ism.instance_id_to_instance) - set(sampled)
        for iid in unsampled:
            assert ism._get_annotator_cap_for_item(iid) == 1

    def test_no_overlap_block_returns_empty(self):
        config = {"num_annotators_per_item": {"default": 1}, "random_seed": 1}
        ism = ItemStateManager(config)
        for i in range(10):
            ism.add_item(f"i{i}", {"text": "x"})
        assert apply_overlap_sample(ism, config) == {}

    def test_respects_existing_metadata(self):
        ism, config = _build(n_items=20)
        # Pre-stamp item_00 with a manual override
        ism.instance_id_to_instance["item_00"].add_metadata("required_annotations", 5)
        sampled = apply_overlap_sample(ism, config)
        assert "item_00" not in sampled  # respected
        assert ism._get_annotator_cap_for_item("item_00") == 5
