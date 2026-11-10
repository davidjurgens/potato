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


# ---------------------------------------------------------------------------
# Keys on a rendered page. The allocator used to reserve a-d for BWS "worst"
# while bws.py bound q-r, never reserved triage's 1/2/3, allocated a likert
# nothing (so it bound 1..size over whatever else held them), and ignored
# explicit keys on schemas it was not allocating. Each case renders every
# scheme the way the server does and reads the data-key attributes back.
# ---------------------------------------------------------------------------

import re

from potato.server_utils.schemas.registry import schema_registry


def rendered_keys(schemes):
    """{scheme name: set of data-key values} after allocation and rendering."""
    alloc = allocate_keybindings(schemes)
    keys = {}
    for scheme in schemes:
        scheme = dict(scheme)
        if scheme["name"] in alloc:
            scheme["_allocated_keys"] = alloc[scheme["name"]]
        html, _ = schema_registry.generate(scheme)
        keys[scheme["name"]] = {k.lower() for k in re.findall(r'data-key="([^"]+)"', html)}
    return keys


def assert_disjoint(keys):
    names = list(keys)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert not keys[a] & keys[b], f"{a} and {b} share {keys[a] & keys[b]}"


def radio(name, n, **extra):
    return {"annotation_type": "radio", "name": name, "description": "d",
            "labels": [f"{name}{i}" for i in range(n)], "sequential_key_binding": True,
            **extra}


LIKERT = {"annotation_type": "likert", "name": "agree", "description": "d", "size": 5,
          "min_label": "lo", "max_label": "hi", "sequential_key_binding": True}


class TestKeysOnARenderedPage:
    def test_triage_keys_are_reserved(self):
        keys = rendered_keys([{"annotation_type": "triage", "name": "keep", "description": "d"},
                              radio("tone", 3)])
        assert keys["keep"] == {"1", "2", "3"} and len(keys["tone"]) == 3
        assert_disjoint(keys)

    def test_custom_triage_keys_are_reserved_too(self):
        keys = rendered_keys([{"annotation_type": "triage", "name": "keep", "description": "d",
                               "accept_key": "A", "reject_key": "q", "skip_key": "w"},
                              dict(radio("tone", 3, keybinding_strategy="mnemonic"),
                                   labels=["apple", "quiet", "wild"])])
        assert keys["keep"] == {"a", "q", "w"} and len(keys["tone"]) == 3
        assert_disjoint(keys)

    def test_bws_worst_keys_are_reserved(self):
        # Seven labels do not fit the six number keys BWS leaves, so the radio
        # goes to a letter row; it used to land on BWS's q w e r.
        keys = rendered_keys([{"annotation_type": "bws", "name": "bws", "description": "d"},
                              radio("tone", 7)])
        assert {"q", "w", "e", "r"} <= keys["bws"] and len(keys["tone"]) == 7
        assert_disjoint(keys)

    def test_every_bws_tile_has_its_own_key(self):
        keys = rendered_keys([{"annotation_type": "bws", "name": "bws", "description": "d",
                               "tuple_size": 5}])
        assert len(keys["bws"]) == 10          # position 5 used to repeat position 3's `e`

    def test_a_likert_after_a_radio_gets_free_keys(self):
        keys = rendered_keys([radio("tone", 3), LIKERT])
        assert len(keys["agree"]) == 5
        assert_disjoint(keys)

    def test_a_likert_on_its_own_keeps_the_number_row(self):
        assert rendered_keys([LIKERT])["agree"] == {"1", "2", "3", "4", "5"}

    def test_an_explicit_key_on_an_unallocated_schema_is_reserved(self):
        fixed = {"annotation_type": "radio", "name": "fixed", "description": "d",
                 "labels": [{"name": "yes", "key_value": 1}, {"name": "no", "key_value": 2}]}
        keys = rendered_keys([fixed, radio("tone", 3)])
        assert keys["fixed"] == {"1", "2"}
        assert_disjoint(keys)


class TestCrossSchemaWarning:
    def warnings(self, caplog, schemes):
        caplog.clear()
        with caplog.at_level("WARNING",
                             logger="potato.server_utils.schemas.keybinding_allocator"):
            allocate_keybindings(schemes)
        return [r.getMessage() for r in caplog.records]

    def test_two_hard_coded_schemas_on_one_key_warn(self, caplog):
        binary = {"annotation_type": "pairwise", "mode": "binary", "description": "d"}
        messages = self.warnings(caplog, [dict(binary, name="a"), dict(binary, name="b")])
        assert any("Key '1' is bound by more than one schema: 'a', 'b'" in m for m in messages)

    def test_an_explicit_key_on_a_triage_key_names_the_label(self, caplog):
        fixed = {"annotation_type": "radio", "name": "fixed", "description": "d",
                 "labels": [{"name": "yes", "key_value": "1"}]}
        messages = self.warnings(caplog, [fixed, {"annotation_type": "triage", "name": "keep"}])
        assert any("'fixed' (label 'yes'), 'keep'" in m for m in messages)

    def test_pairwise_without_keys_does_not_warn(self, caplog):
        scale = {"annotation_type": "pairwise", "mode": "scale", "name": "pref"}
        binary = {"annotation_type": "pairwise", "mode": "binary", "name": "help"}
        assert self.warnings(caplog, [scale, binary]) == []


# ---------------------------------------------------------------------------
# Viewer keys. Image, video, audio, point-cloud, rollout and interval viewers
# listen on the whole page, and their handler runs before the label shortcuts
# and calls preventDefault, so a radio label given one of their keys did
# nothing. The allocator did not know those keys: beside an image with the bbox
# tool, a second sequential radio got q w e r t, and its r picked the tool.
# The expected keys below are the ones each viewer's JS handles, written out.
# ---------------------------------------------------------------------------

IMAGE = {"annotation_type": "image_annotation", "name": "img", "description": "d",
         "tools": ["bbox"], "labels": ["car"]}
VIDEO = {"annotation_type": "video_annotation", "name": "clip", "description": "d",
         "mode": "segment", "labels": ["speech"]}
AUDIO = {"annotation_type": "audio_annotation", "name": "sound", "description": "d",
         "labels": ["music", "speech", "noise"]}
ROLLOUT = {"annotation_type": "rollout_evaluation", "name": "roll", "description": "d"}
INTERVAL = {"annotation_type": "interval_label", "name": "sleep", "description": "d",
            "signal_field": "signal", "labels": ["W", "N1", "N2"]}
POINTS = {"annotation_type": "spatial_annotation", "name": "scan", "description": "d",
          "tools": ["cuboid_3d"], "labels": ["car"]}


def keys_beside(viewer, *schemes):
    """Rendered keys of ``schemes`` when they share a page with ``viewer``."""
    alloc = allocate_keybindings([viewer, *schemes])
    keys = {}
    for scheme in schemes:
        scheme = dict(scheme, _allocated_keys=alloc[scheme["name"]])
        html, _ = schema_registry.generate(scheme)
        keys[scheme["name"]] = {k.lower() for k in re.findall(r'data-key="([^"]+)"', html)}
    return keys


def allocator_warnings(caplog, schemes):
    caplog.clear()
    with caplog.at_level("WARNING", logger="potato.server_utils.schemas.keybinding_allocator"):
        allocate_keybindings(schemes)
    return [r.getMessage() for r in caplog.records]


def mnemonic(name, labels):
    return dict(radio(name, 0, keybinding_strategy="mnemonic"), labels=labels)


class TestViewerKeysAreReserved:
    def test_a_radio_beside_an_image_skips_the_tool_keys(self):
        keys = keys_beside(IMAGE, radio("first", 10), radio("second", 5))
        assert len(keys["second"]) == 5 and "r" not in keys["second"]   # r is bbox
        keys = keys_beside(IMAGE, mnemonic("tone", ["vivid", "harsh", "rough"]))
        assert len(keys["tone"]) == 3 and not keys["tone"] & {"v", "h", "r"}

    def test_the_image_keys_follow_its_keybinding_profile(self):
        # legacy puts bbox on b, so r is free and b is not.
        keys = keys_beside(dict(IMAGE, keybinding_profile="legacy"),
                           mnemonic("tone", ["bold", "rough"]))
        assert "b" not in keys["tone"] and "r" in keys["tone"]

    def test_a_radio_beside_a_video_skips_the_player_keys(self):
        keys = keys_beside(VIDEO, mnemonic("tone", ["calm", "kind", "tense"]))
        assert len(keys["tone"]) == 3 and not keys["tone"] & {"c", "k"}
        assert "0" not in keys_beside(VIDEO, radio("many", 10))["many"]   # zoom to fit

    def test_tracking_mode_also_takes_t(self):
        keys = keys_beside(dict(VIDEO, mode="tracking"), mnemonic("tone", ["tense", "terse"]))
        assert len(keys["tone"]) == 2 and "t" not in keys["tone"]

    def test_a_radio_beside_audio_skips_the_digits_that_pick_its_labels(self):
        keys = keys_beside(AUDIO, radio("tone", 3))
        assert len(keys["tone"]) == 3 and not keys["tone"] & {"1", "2", "3"}

    def test_a_radio_beside_a_rollout_gets_no_digit(self):
        keys = keys_beside(ROLLOUT, radio("tone", 3))
        assert len(keys["tone"]) == 3 and not any(k.isdigit() for k in keys["tone"])

    def test_a_radio_beside_interval_labels_skips_their_filled_in_keys(self):
        keys = keys_beside(INTERVAL, radio("tone", 3))
        assert len(keys["tone"]) == 3 and not keys["tone"] & {"1", "2", "3"}

    def test_a_radio_beside_a_point_cloud_skips_its_keys(self):
        keys = keys_beside(POINTS, mnemonic("tone", ["cold", "quiet", "hot"]))
        assert len(keys["tone"]) == 3 and not keys["tone"] & {"c", "q", "h"}

    def test_the_paint_keys_count_only_with_the_paint_tool(self, caplog):
        minus = {"annotation_type": "radio", "name": "tone", "description": "d",
                 "labels": [{"name": "less", "key_value": "-"}]}
        painting = dict(POINTS, tools=["cuboid_3d", "segment_3d"])
        assert any("Key '-'" in m for m in allocator_warnings(caplog, [painting, minus]))
        assert allocator_warnings(caplog, [POINTS, minus]) == []

    def test_an_explicit_key_on_a_viewer_key_warns(self, caplog):
        fixed = {"annotation_type": "radio", "name": "tone", "description": "d",
                 "labels": [{"name": "vivid", "key_value": "v"}]}
        messages = allocator_warnings(caplog, [IMAGE, fixed])
        assert any("Key 'v' is bound by more than one schema: 'img' (viewer shortcut), "
                   "'tone' (label 'vivid')" in m for m in messages)

    def test_two_viewers_of_one_type_share_their_keys_without_a_warning(self, caplog):
        # One press of ] steps both interval plots; that is the design.
        free = dict(INTERVAL, name="arousals", labels=[{"name": "arousal", "key_value": "a"}])
        assert allocator_warnings(caplog, [INTERVAL, free]) == []

    def test_a_malformed_viewer_scheme_leaves_the_error_to_its_generator(self):
        broken = {"annotation_type": "interval_label", "name": "x", "labels": [{"color": "red"}]}
        assert allocate_keybindings([broken, radio("tone", 3)])["tone"]
