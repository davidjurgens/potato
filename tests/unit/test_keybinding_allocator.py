"""
Tests for the centralized keybinding allocator.

Verifies that allocate_keybindings() assigns non-overlapping keys across
multiple annotation schemas, honors explicit overrides, and handles edge cases.
"""

import pytest
from potato.server_utils.schemas.keybinding_allocator import (
    allocate_keybindings,
    KEY_POOLS,
    SELF_MANAGED_TYPES,
)


class TestSingleSchema:
    """A single schema with sequential_key_binding gets number keys."""

    def test_single_schema_gets_number_keys(self):
        schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "sequential_key_binding": True,
                "labels": ["positive", "negative", "neutral", "mixed"],
            }
        ]
        alloc = allocate_keybindings(schemes)
        assert "sentiment" in alloc
        keys = [e["key"] for e in alloc["sentiment"]]
        assert keys == ["1", "2", "3", "4"]

    def test_single_schema_labels_preserved(self):
        schemes = [
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "sequential_key_binding": True,
                "labels": ["quality", "price", "service"],
            }
        ]
        alloc = allocate_keybindings(schemes)
        labels = [e["label"] for e in alloc["topics"]]
        assert labels == ["quality", "price", "service"]


class TestTwoSchemas:
    """Two schemas: first gets numbers, second gets QWERTY top row."""

    def test_two_schemas_non_overlapping(self):
        schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "sequential_key_binding": True,
                "labels": ["positive", "negative", "neutral", "mixed"],
            },
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "sequential_key_binding": True,
                "labels": ["quality", "price", "service", "design", "durability"],
            },
        ]
        alloc = allocate_keybindings(schemes)
        sentiment_keys = {e["key"] for e in alloc["sentiment"]}
        topic_keys = {e["key"] for e in alloc["topics"]}

        # No overlap
        assert sentiment_keys & topic_keys == set()

        # First schema gets numbers
        assert sentiment_keys == {"1", "2", "3", "4"}

        # Second schema gets QWERTY top row
        assert topic_keys == {"q", "w", "e", "r", "t"}

    def test_two_schemas_order_matters(self):
        """First schema in config order gets number pool."""
        schemes = [
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "sequential_key_binding": True,
                "labels": ["a", "b", "c"],
            },
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "sequential_key_binding": True,
                "labels": ["x", "y"],
            },
        ]
        alloc = allocate_keybindings(schemes)
        topic_keys = [e["key"] for e in alloc["topics"]]
        sentiment_keys = [e["key"] for e in alloc["sentiment"]]

        assert topic_keys == ["1", "2", "3"]
        assert sentiment_keys == ["q", "w"]


class TestThreeSchemas:
    """Three schemas: numbers, top row, home row."""

    def test_three_schemas_all_different_pools(self):
        schemes = [
            {
                "annotation_type": "radio",
                "name": "s1",
                "sequential_key_binding": True,
                "labels": ["a", "b"],
            },
            {
                "annotation_type": "radio",
                "name": "s2",
                "sequential_key_binding": True,
                "labels": ["c", "d"],
            },
            {
                "annotation_type": "radio",
                "name": "s3",
                "sequential_key_binding": True,
                "labels": ["e", "f"],
            },
        ]
        alloc = allocate_keybindings(schemes)
        k1 = {e["key"] for e in alloc["s1"]}
        k2 = {e["key"] for e in alloc["s2"]}
        k3 = {e["key"] for e in alloc["s3"]}

        assert k1 == {"1", "2"}
        assert k2 == {"q", "w"}
        assert k3 == {"a", "s"}

        # Verify no overlap between any pair
        assert k1 & k2 == set()
        assert k1 & k3 == set()
        assert k2 & k3 == set()


class TestExplicitKeyValue:
    """Explicit key_value per-label is honored and removed from pool."""

    def test_explicit_key_honored(self):
        schemes = [
            {
                "annotation_type": "radio",
                "name": "s1",
                "sequential_key_binding": True,
                "labels": [
                    {"name": "positive", "key_value": "p"},
                    "negative",
                    "neutral",
                ],
            }
        ]
        alloc = allocate_keybindings(schemes)
        entries = alloc["s1"]
        assert entries[0] == {"label": "positive", "key": "p"}
        # Remaining get sequential from pool
        assert entries[1]["key"] == "1"
        assert entries[2]["key"] == "2"

    def test_explicit_key_excluded_from_second_schema(self):
        """Explicit keys from one schema don't appear in another's allocation."""
        schemes = [
            {
                "annotation_type": "radio",
                "name": "s1",
                "sequential_key_binding": True,
                "labels": [
                    {"name": "a", "key_value": "q"},
                ],
            },
            {
                "annotation_type": "radio",
                "name": "s2",
                "sequential_key_binding": True,
                "labels": ["b", "c"],
            },
        ]
        alloc = allocate_keybindings(schemes)
        # s1 got "q" explicitly, s2 should not include "q"
        s2_keys = {e["key"] for e in alloc["s2"]}
        assert "q" not in s2_keys


class TestMnemonicStrategy:
    """keybinding_strategy: mnemonic assigns first letters."""

    def test_mnemonic_first_letters(self):
        schemes = [
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "sequential_key_binding": True,
                "keybinding_strategy": "mnemonic",
                "labels": ["quality", "price", "service"],
            }
        ]
        alloc = allocate_keybindings(schemes)
        keys = [e["key"] for e in alloc["topics"]]
        assert keys == ["q", "p", "s"]

    def test_mnemonic_fallback_on_conflict(self):
        """When two labels start with the same letter, second gets fallback."""
        schemes = [
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "sequential_key_binding": True,
                "keybinding_strategy": "mnemonic",
                "labels": ["service", "support"],
            }
        ]
        alloc = allocate_keybindings(schemes)
        keys = [e["key"] for e in alloc["topics"]]
        # "service" gets 's', "support" tries 's' (taken), then 'u'
        assert keys[0] == "s"
        assert keys[1] == "u"

    def test_mnemonic_with_explicit_override(self):
        schemes = [
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "sequential_key_binding": True,
                "keybinding_strategy": "mnemonic",
                "labels": [
                    {"name": "quality", "key_value": "z"},
                    "price",
                ],
            }
        ]
        alloc = allocate_keybindings(schemes)
        assert alloc["topics"][0] == {"label": "quality", "key": "z"}
        assert alloc["topics"][1] == {"label": "price", "key": "p"}


class TestNoneStrategy:
    """keybinding_strategy: none disables keybindings."""

    def test_none_strategy_skipped(self):
        schemes = [
            {
                "annotation_type": "radio",
                "name": "s1",
                "keybinding_strategy": "none",
                "labels": ["a", "b"],
            }
        ]
        alloc = allocate_keybindings(schemes)
        assert "s1" not in alloc

    def test_no_sequential_no_allocation(self):
        """Schema without sequential_key_binding is not allocated."""
        schemes = [
            {
                "annotation_type": "radio",
                "name": "s1",
                "labels": ["a", "b"],
            }
        ]
        alloc = allocate_keybindings(schemes)
        assert "s1" not in alloc


class TestSelfManagedSchemas:
    """Pairwise and BWS pre-claim their hardcoded keys."""

    def test_pairwise_claims_keys(self):
        schemes = [
            {
                "annotation_type": "pairwise",
                "name": "compare",
                "sequential_key_binding": True,
                "labels": ["A", "B"],
            },
            {
                "annotation_type": "radio",
                "name": "s2",
                "sequential_key_binding": True,
                "labels": ["x", "y"],
            },
        ]
        alloc = allocate_keybindings(schemes)
        # pairwise is self-managed, not in allocation
        assert "compare" not in alloc
        # radio should not get keys 1, 2, 0 (claimed by pairwise)
        s2_keys = {e["key"] for e in alloc["s2"]}
        assert "1" not in s2_keys
        assert "2" not in s2_keys
        assert "0" not in s2_keys

    def test_bws_claims_keys(self):
        schemes = [
            {
                "annotation_type": "bws",
                "name": "bws_task",
                "sequential_key_binding": True,
                "tuple_size": 3,
            },
            {
                "annotation_type": "radio",
                "name": "quality",
                "sequential_key_binding": True,
                "labels": ["good", "bad"],
            },
        ]
        alloc = allocate_keybindings(schemes)
        assert "bws_task" not in alloc
        quality_keys = {e["key"] for e in alloc["quality"]}
        # BWS with tuple_size=3 claims 1,2,3 and a,b,c
        assert "1" not in quality_keys
        assert "2" not in quality_keys
        assert "3" not in quality_keys


class TestOverflow:
    """More labels than pool size."""

    def test_overflow_labels_get_none(self):
        """When a schema has more labels than any pool, excess get None."""
        # Create 12 labels — more than any single pool
        labels = [f"label_{i}" for i in range(12)]
        schemes = [
            {
                "annotation_type": "radio",
                "name": "big",
                "sequential_key_binding": True,
                "labels": labels,
            }
        ]
        alloc = allocate_keybindings(schemes)
        entries = alloc["big"]
        assert len(entries) == 12
        # First 10 get number keys
        assigned = [e["key"] for e in entries if e["key"] is not None]
        assert len(assigned) == 10
        # Last 2 get None
        assert entries[10]["key"] is None
        assert entries[11]["key"] is None


class TestEmptyInput:
    """Edge cases with empty inputs."""

    def test_empty_schemes_returns_empty(self):
        assert allocate_keybindings([]) == {}

    def test_no_sequential_schemas_returns_empty(self):
        schemes = [
            {
                "annotation_type": "text",
                "name": "notes",
                "labels": [],
            }
        ]
        assert allocate_keybindings(schemes) == {}


class TestDictLabels:
    """Labels can be dicts with 'name' key."""

    def test_dict_labels_extracted(self):
        schemes = [
            {
                "annotation_type": "radio",
                "name": "s1",
                "sequential_key_binding": True,
                "labels": [
                    {"name": "positive", "tooltip": "good"},
                    {"name": "negative", "tooltip": "bad"},
                ],
            }
        ]
        alloc = allocate_keybindings(schemes)
        labels = [e["label"] for e in alloc["s1"]]
        assert labels == ["positive", "negative"]
        keys = [e["key"] for e in alloc["s1"]]
        assert keys == ["1", "2"]
