"""
Unit tests for the IBWSManager class.

Tests the core IBWS algorithm: tuple generation, partitioning, round management,
and final ranking.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.ibws_manager import IBWSManager, clear_ibws_manager


def make_pool_items(n, id_key="id", text_key="text"):
    """Create n pool items with sequential IDs."""
    return [
        {id_key: f"item_{i:03d}", text_key: f"Text for item {i}"}
        for i in range(1, n + 1)
    ]


def make_config(tuple_size=4, max_rounds=None, seed=42,
                scoring_method="counting", tuples_per_item_per_round=2):
    """Create a minimal IBWS config."""
    return {
        "ibws_config": {
            "tuple_size": tuple_size,
            "max_rounds": max_rounds,
            "seed": seed,
            "scoring_method": scoring_method,
            "tuples_per_item_per_round": tuples_per_item_per_round,
        }
    }


class TestIBWSManagerInit:
    """Test IBWSManager initialization."""

    def test_init_basic(self):
        pool = make_pool_items(10)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        assert mgr.current_round == 0
        assert mgr.completed is False
        assert len(mgr.buckets) == 1
        assert len(mgr.buckets[0]) == 10
        assert len(mgr.terminal_buckets) == 0

    def test_init_stores_pool_map(self):
        pool = make_pool_items(5)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        assert "item_001" in mgr.pool_item_map
        assert mgr.pool_item_map["item_001"]["text"] == "Text for item 1"


class TestRoundGeneration:
    """Test tuple generation for rounds."""

    def test_generate_round_1(self):
        pool = make_pool_items(12)
        config = make_config(tuple_size=4)
        mgr = IBWSManager(config, pool, "id", "text")

        tuples = mgr.generate_round_tuples()

        assert mgr.current_round == 1
        assert len(tuples) > 0
        # All tuples should have round 1 marker
        for t in tuples:
            assert t["_ibws_round"] == 1
            assert t["id"].startswith("ibws_r1_b0_")
            assert "_bws_items" in t
            assert len(t["_bws_items"]) == 4

    def test_tuple_ids_are_unique(self):
        pool = make_pool_items(20)
        config = make_config(tuple_size=4)
        mgr = IBWSManager(config, pool, "id", "text")

        tuples = mgr.generate_round_tuples()
        ids = [t["id"] for t in tuples]
        assert len(ids) == len(set(ids))

    def test_seed_reproducibility(self):
        pool = make_pool_items(12)
        config = make_config(seed=99)

        mgr1 = IBWSManager(config, pool, "id", "text")
        tuples1 = mgr1.generate_round_tuples()

        mgr2 = IBWSManager(config, pool, "id", "text")
        tuples2 = mgr2.generate_round_tuples()

        ids1 = [t["id"] for t in tuples1]
        ids2 = [t["id"] for t in tuples2]
        assert ids1 == ids2

        # Check that the actual items in each tuple match
        for t1, t2 in zip(tuples1, tuples2):
            items1 = [i["source_id"] for i in t1["_bws_items"]]
            items2 = [i["source_id"] for i in t2["_bws_items"]]
            assert items1 == items2


class TestPartitioning:
    """Test bucket partitioning logic."""

    def test_partition_even_split(self):
        pool = make_pool_items(9)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        item_ids = [f"item_{i:03d}" for i in range(1, 10)]
        scores = {
            f"item_{i:03d}": {"score": float(i)}
            for i in range(1, 10)
        }

        upper, middle, lower = mgr._partition_bucket(item_ids, scores)

        assert len(upper) == 3
        assert len(middle) == 3
        assert len(lower) == 3
        # Upper should have highest scores
        for iid in upper:
            assert scores[iid]["score"] >= 7.0
        for iid in lower:
            assert scores[iid]["score"] <= 3.0

    def test_partition_uneven_split(self):
        pool = make_pool_items(7)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        item_ids = [f"item_{i:03d}" for i in range(1, 8)]
        scores = {
            f"item_{i:03d}": {"score": float(i)}
            for i in range(1, 8)
        }

        upper, middle, lower = mgr._partition_bucket(item_ids, scores)

        # 7 // 3 = 2, so upper=2, lower=2, middle=3
        assert len(upper) == 2
        assert len(lower) == 2
        assert len(middle) == 3
        total = len(upper) + len(middle) + len(lower)
        assert total == 7

    def test_partition_small_bucket(self):
        """Buckets with 2 items should still partition (giving middle 2, upper 0, lower 0)."""
        pool = make_pool_items(2)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        item_ids = ["item_001", "item_002"]
        scores = {"item_001": {"score": 1.0}, "item_002": {"score": 2.0}}

        upper, middle, lower = mgr._partition_bucket(item_ids, scores)

        # 2 // 3 = 0, so upper=0, lower=0, middle=all
        total = len(upper) + len(middle) + len(lower)
        assert total == 2


class TestTerminalBuckets:
    """Test terminal bucket detection."""

    def test_small_pool_all_terminal(self):
        """With 3 items and tuple_size=4, all go to terminal immediately."""
        pool = make_pool_items(3)
        config = make_config(tuple_size=4)
        mgr = IBWSManager(config, pool, "id", "text")

        tuples = mgr.generate_round_tuples()

        # Pool is smaller than tuple_size, so all items are terminal
        assert len(tuples) == 0
        assert mgr.completed is True
        assert len(mgr.terminal_buckets) == 1
        assert len(mgr.terminal_buckets[0]) == 3


class TestRoundCompletion:
    """Test round completion checking."""

    def test_check_round_complete_no_annotations(self):
        pool = make_pool_items(12)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")
        mgr.generate_round_tuples()

        # Mock ISM with empty instance_annotators (no annotations)
        ism = MagicMock()
        ism.instance_annotators = {}

        assert mgr.check_round_complete(ism, "test_schema") is False

    def test_check_round_complete_all_annotated(self):
        pool = make_pool_items(12)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")
        tuples = mgr.generate_round_tuples()

        # Mock ISM with all tuples having at least one annotator
        ism = MagicMock()
        ism.instance_annotators = {
            t["id"]: {"user1"} for t in tuples
        }

        assert mgr.check_round_complete(ism, "test_schema") is True

    def test_check_round_zero(self):
        """Before any rounds, check should return False."""
        pool = make_pool_items(12)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        ism = MagicMock()
        assert mgr.check_round_complete(ism, "test_schema") is False


class TestMaxRounds:
    """Test max_rounds enforcement."""

    def test_max_rounds_stops_advance(self):
        pool = make_pool_items(20)
        config = make_config(max_rounds=1)
        mgr = IBWSManager(config, pool, "id", "text")
        mgr.generate_round_tuples()

        ism = MagicMock()
        usm = MagicMock()
        usm.get_all_users.return_value = []

        new_tuples = mgr.advance_round(ism, usm, "test_schema")

        assert len(new_tuples) == 0
        assert mgr.completed is True


class TestFinalRanking:
    """Test final ranking generation."""

    def test_final_ranking_includes_all_items(self):
        pool = make_pool_items(8)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        ranking = mgr.get_final_ranking()

        assert len(ranking) == 8
        item_ids = {r["item_id"] for r in ranking}
        expected = {f"item_{i:03d}" for i in range(1, 9)}
        assert item_ids == expected

    def test_final_ranking_has_sequential_ranks(self):
        pool = make_pool_items(8)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        ranking = mgr.get_final_ranking()
        ranks = [r["rank"] for r in ranking]
        assert ranks == list(range(1, 9))


class TestRoundInfo:
    """Test get_round_info()."""

    def test_round_info_before_start(self):
        pool = make_pool_items(10)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")

        info = mgr.get_round_info()
        assert info["current_round"] == 0
        assert info["completed"] is False
        assert info["total_items"] == 10

    def test_round_info_after_round_1(self):
        pool = make_pool_items(12)
        config = make_config()
        mgr = IBWSManager(config, pool, "id", "text")
        mgr.generate_round_tuples()

        info = mgr.get_round_info()
        assert info["current_round"] == 1
        assert info["total_tuples_this_round"] > 0
        assert info["total_items"] == 12
