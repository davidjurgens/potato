"""Unit tests for BWS tuple generator."""

import pytest
from potato.bws_tuple_generator import BwsTupleGenerator


def make_pool(n=10, id_key="id", text_key="text"):
    """Create a simple pool of items."""
    return [
        {id_key: f"s{i:03d}", text_key: f"Item text {i}"}
        for i in range(1, n + 1)
    ]


class TestBwsTupleGenerator:
    """Tests for BwsTupleGenerator."""

    def test_basic_generation(self):
        """Generate correct number of tuples with correct structure."""
        pool = make_pool(10)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=4, num_tuples=5, seed=42)
        tuples = gen.generate()

        assert len(tuples) == 5
        for t in tuples:
            assert "id" in t
            assert "text" in t
            assert "_bws_items" in t
            assert "_bws_tuple_size" in t
            assert t["_bws_tuple_size"] == 4
            assert len(t["_bws_items"]) == 4

    def test_tuple_size_validation(self):
        """Reject tuple_size < 2."""
        pool = make_pool(10)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=1, num_tuples=5)
        with pytest.raises(ValueError, match="tuple_size must be >= 2"):
            gen.validate()

    def test_tuple_size_exceeds_pool(self):
        """Reject tuple_size > pool_size."""
        pool = make_pool(3)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=5, num_tuples=2)
        with pytest.raises(ValueError, match="exceeds pool size"):
            gen.validate()

    def test_reproducibility_with_seed(self):
        """Same seed produces same tuples."""
        pool = make_pool(10)
        gen1 = BwsTupleGenerator(pool, "id", "text", tuple_size=4, num_tuples=5, seed=42)
        gen2 = BwsTupleGenerator(pool, "id", "text", tuple_size=4, num_tuples=5, seed=42)

        tuples1 = gen1.generate()
        tuples2 = gen2.generate()

        for t1, t2 in zip(tuples1, tuples2):
            items1 = [item["source_id"] for item in t1["_bws_items"]]
            items2 = [item["source_id"] for item in t2["_bws_items"]]
            assert items1 == items2

    def test_different_seeds_different_tuples(self):
        """Different seeds produce different tuples."""
        pool = make_pool(20)
        gen1 = BwsTupleGenerator(pool, "id", "text", tuple_size=4, num_tuples=10, seed=42)
        gen2 = BwsTupleGenerator(pool, "id", "text", tuple_size=4, num_tuples=10, seed=99)

        tuples1 = gen1.generate()
        tuples2 = gen2.generate()

        # At least one tuple should be different
        any_different = False
        for t1, t2 in zip(tuples1, tuples2):
            items1 = set(item["source_id"] for item in t1["_bws_items"])
            items2 = set(item["source_id"] for item in t2["_bws_items"])
            if items1 != items2:
                any_different = True
                break
        assert any_different

    def test_all_items_appear(self):
        """Every pool item appears in at least one tuple."""
        pool = make_pool(10)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=4, num_tuples=20, seed=42)
        tuples = gen.generate()

        appeared = set()
        for t in tuples:
            for item in t["_bws_items"]:
                appeared.add(item["source_id"])

        pool_ids = {item["id"] for item in pool}
        assert pool_ids == appeared

    def test_min_item_appearances(self):
        """Average item appearances meets the min_appearances target."""
        pool = make_pool(10)
        gen = BwsTupleGenerator(
            pool, "id", "text", tuple_size=4, seed=42, min_item_appearances=5
        )
        tuples = gen.generate()

        counts = {}
        for t in tuples:
            for item in t["_bws_items"]:
                sid = item["source_id"]
                counts[sid] = counts.get(sid, 0) + 1

        # With random sampling, average appearances should meet target
        avg_appearances = sum(counts.values()) / len(counts)
        assert avg_appearances >= 5, (
            f"Average appearances {avg_appearances:.1f} below target 5"
        )
        # Every item should appear at least once
        for item in pool:
            assert counts.get(item["id"], 0) >= 1, (
                f"Item {item['id']} never appeared"
            )

    def test_auto_num_tuples(self):
        """Auto-calculation produces reasonable count."""
        pool = make_pool(20)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=4, seed=42)
        # Default min_item_appearances = 2 * tuple_size = 8
        # num_tuples = ceil(20 * 8 / 4) = 40
        tuples = gen.generate()
        assert len(tuples) == 40

    def test_tuple_metadata_structure(self):
        """Each tuple has _bws_items with source_id, text, position."""
        pool = make_pool(6)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=3, num_tuples=2, seed=42)
        tuples = gen.generate()

        for t in tuples:
            assert len(t["_bws_items"]) == 3
            positions_seen = set()
            for item in t["_bws_items"]:
                assert "source_id" in item
                assert "text" in item
                assert "position" in item
                assert item["position"] in ["A", "B", "C"]
                positions_seen.add(item["position"])
            # All positions used
            assert positions_seen == {"A", "B", "C"}

    def test_no_duplicates_within_tuple(self):
        """No item appears twice in the same tuple."""
        pool = make_pool(10)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=4, num_tuples=20, seed=42)
        tuples = gen.generate()

        for t in tuples:
            ids = [item["source_id"] for item in t["_bws_items"]]
            assert len(ids) == len(set(ids)), "Duplicate item in tuple"

    def test_tuple_ids_are_unique(self):
        """Each tuple gets a unique ID."""
        pool = make_pool(10)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=4, num_tuples=10, seed=42)
        tuples = gen.generate()

        ids = [t["id"] for t in tuples]
        assert len(ids) == len(set(ids))

    def test_text_key_is_empty_for_tuples(self):
        """Tuple's text_key value is empty (BWS JS handles display)."""
        pool = make_pool(6)
        gen = BwsTupleGenerator(pool, "id", "text", tuple_size=3, num_tuples=2, seed=42)
        tuples = gen.generate()

        for t in tuples:
            assert t["text"] == ""
