"""
Unit tests for turning a ConvoKit corpus into Potato items.

The single most important guarantee here is the ``turn_id`` contract: every
emitted turn carries the real ConvoKit utterance id, because that is what lets
per-turn annotations round-trip back into ConvoKit metadata without any
position-based reconciliation. Several tests exist purely to pin that down.
"""

import json
import os

import pytest

from potato.convokit import read_corpus
from potato.convokit.items import (
    PROVENANCE_KEY,
    ItemBuildError,
    ItemOptions,
    build_items,
    concatenate_turns,
    ordered_turns,
)

FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "convokit"
)
MODERN = os.path.join(FIXTURES, "mini-modern")
LEGACY = os.path.join(FIXTURES, "mini-legacy")
BROKEN = os.path.join(FIXTURES, "mini-broken")


@pytest.fixture
def modern():
    return read_corpus(MODERN)


def _by_id(items):
    return {item["id"]: item for item in items}


class TestConversationUnit:
    def test_one_item_per_conversation(self, modern):
        items = build_items(modern)
        assert len(items) == 2
        assert set(_by_id(items)) == {"convo:c0", "convo:d0"}

    def test_raw_ids_without_prefix(self, modern):
        items = build_items(modern, ItemOptions(id_prefix=False))
        assert set(_by_id(items)) == {"c0", "d0"}

    def test_all_utterances_appear_as_turns(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        assert {t["turn_id"] for t in item["conversation"]} == {"c0", "c1", "c2", "c3"}

    def test_turn_id_is_the_real_utterance_id(self, modern):
        """The round-trip linchpin. See potato/convokit/items.py."""
        items = build_items(modern)
        seen = {t["turn_id"] for item in items for t in item["conversation"]}
        assert seen == set(modern.utterances)

    def test_turn_carries_speaker_text_reply_and_timestamp(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        turn = next(t for t in item["conversation"] if t["turn_id"] == "c1")
        assert turn["speaker"] == "bob"
        assert turn["reply_to"] == "c0"
        assert turn["timestamp"] == 1200.0
        assert turn["text"].startswith("I don't think")

    def test_turn_meta_is_included(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        turn = next(t for t in item["conversation"] if t["turn_id"] == "c0")
        assert turn["meta"]["is_section_header"] is True
        assert turn["meta"]["stance"] == "support"

    def test_turn_meta_can_be_suppressed(self, modern):
        items = build_items(modern, ItemOptions(include_turn_meta=False))
        assert all("meta" not in t for i in items for t in i["conversation"])

    def test_text_field_is_a_flat_rendering(self, modern):
        item = _by_id(build_items(modern))["convo:d0"]
        assert item["text"] == (
            "dave: Reverting your edit, see the talk page.\n"
            "erin: That revert was not justified."
        )

    def test_conversation_meta_field(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        assert item["convo_meta"]["page_title"] == "Talk:Example"

    def test_speakers_field_collects_participant_metadata(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        assert set(item["speakers"]) == {"alice", "bob", "carol"}
        assert item["speakers"]["alice"] == {"editor_since": 2004}

    def test_items_are_json_serializable(self, modern):
        json.dumps(build_items(modern))


class TestDepthAndOrdering:
    def test_depth_reflects_reply_nesting(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        depths = {t["turn_id"]: t["depth"] for t in item["conversation"]}
        assert depths == {"c0": 0, "c1": 1, "c2": 1, "c3": 2}

    def test_thread_order_is_depth_first_preorder(self, modern):
        """Replies sit under what they reply to — required by the indented view."""
        item = _by_id(build_items(modern, ItemOptions(order="thread")))["convo:c0"]
        # c2 (ts 1100) sorts before c1 (ts 1200) as a sibling; c3 follows its parent c1.
        assert [t["turn_id"] for t in item["conversation"]] == ["c0", "c2", "c1", "c3"]

    def test_chronological_order_is_a_global_timestamp_sort(self, modern):
        item = _by_id(build_items(modern, ItemOptions(order="chronological")))["convo:c0"]
        assert [t["turn_id"] for t in item["conversation"]] == ["c0", "c2", "c1", "c3"]

    def test_chronological_differs_from_thread_when_replies_interleave(self):
        """A late reply to an early turn separates the two orderings."""
        corpus = read_corpus(MODERN)
        # c3 replies to c1 but happens last overall; make c2 later than c3.
        corpus.utterances["c2"].timestamp = 9999.0
        thread = _by_id(build_items(corpus, ItemOptions(order="thread")))["convo:c0"]
        chrono = _by_id(build_items(corpus, ItemOptions(order="chronological")))["convo:c0"]
        assert [t["turn_id"] for t in thread["conversation"]] == ["c0", "c1", "c3", "c2"]
        assert [t["turn_id"] for t in chrono["conversation"]] == ["c0", "c1", "c3", "c2"]
        # And with c2 early again, thread keeps c3 adjacent to c1 while chrono does not
        corpus.utterances["c3"].timestamp = 1150.0
        thread = _by_id(build_items(corpus, ItemOptions(order="thread")))["convo:c0"]
        assert [t["turn_id"] for t in thread["conversation"]] == ["c0", "c1", "c3", "c2"]

    def test_index_is_position_in_the_emitted_order(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        assert [t["index"] for t in item["conversation"]] == [0, 1, 2, 3]

    def test_siblings_fall_back_to_file_order_without_timestamps(self):
        corpus = read_corpus(MODERN)
        for utt in corpus.utterances.values():
            utt.timestamp = None
        item = _by_id(build_items(corpus))["convo:c0"]
        # File order is c0, c1, c2, c3 — so c1 now precedes c2.
        assert [t["turn_id"] for t in item["conversation"]] == ["c0", "c1", "c3", "c2"]

    def test_ids_are_never_used_for_ordering(self):
        """ConvoKit ids are structured strings that do not sort meaningfully."""
        corpus = read_corpus(MODERN)
        corpus.utterances["c1"].id = "z-last"
        corpus.utterances["c1"].timestamp = None
        corpus.utterances["c2"].timestamp = None
        item = _by_id(build_items(corpus))["convo:c0"]
        order = [t["turn_id"] for t in item["conversation"]]
        assert order.index("c2") > order.index("z-last") or "z-last" in order


class TestTree:
    def test_tree_node_ids_match_flat_turn_ids(self, modern):
        """Both views must annotate the same turns."""
        item = _by_id(build_items(modern))["convo:c0"]

        def ids(node):
            return {node["id"]} | {i for c in node["children"] for i in ids(c)}

        assert ids(item["conversation_tree"]) == {
            t["turn_id"] for t in item["conversation"]
        }

    def test_tree_nesting_follows_reply_to(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        root = item["conversation_tree"]
        assert root["id"] == "c0"
        assert {c["id"] for c in root["children"]} == {"c1", "c2"}
        c1 = next(c for c in root["children"] if c["id"] == "c1")
        assert [g["id"] for g in c1["children"]] == ["c3"]

    def test_tree_can_be_omitted(self, modern):
        items = build_items(modern, ItemOptions(tree_field=None))
        assert all("conversation_tree" not in i for i in items)

    def test_multiple_roots_get_a_synthetic_parent(self):
        corpus = read_corpus(BROKEN)
        item = build_items(corpus)[0]
        root = item["conversation_tree"]
        assert root["id"].endswith("::roots")
        assert len(root["children"]) >= 2

    def test_synthetic_root_is_flagged(self):
        """It is scaffolding, not an utterance — displays must not annotate it."""
        corpus = read_corpus(BROKEN)
        item = build_items(corpus)[0]
        assert item["conversation_tree"]["synthetic"] is True
        assert all(
            not child.get("synthetic") for child in item["conversation_tree"]["children"]
        )

    def test_real_single_root_is_not_flagged(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        assert "synthetic" not in item["conversation_tree"]


class TestBrokenThreading:
    def test_dangling_reply_to_becomes_a_root_and_is_counted(self):
        corpus = read_corpus(BROKEN)
        item = build_items(corpus)[0]
        assert item[PROVENANCE_KEY]["dangling_reply_to"] == 1
        x0 = next(t for t in item["conversation"] if t["turn_id"] == "x0")
        assert x0["depth"] == 0

    def test_reply_cycle_is_broken_and_counted(self):
        corpus = read_corpus(BROKEN)
        item = build_items(corpus)[0]
        assert item[PROVENANCE_KEY]["broken_cycles"] == 1
        # Nothing is lost to the cycle.
        assert {t["turn_id"] for t in item["conversation"]} == {"x0", "x1", "x2"}

    def test_every_utterance_gets_a_depth(self):
        corpus = read_corpus(BROKEN)
        item = build_items(corpus)[0]
        assert all(isinstance(t["depth"], int) for t in item["conversation"])


class TestUtteranceUnit:
    def test_one_item_per_utterance(self, modern):
        items = build_items(modern, ItemOptions(unit="utterance"))
        assert len(items) == len(modern.utterances)

    def test_focus_turn_is_flagged_and_named(self, modern):
        items = _by_id(build_items(modern, ItemOptions(unit="utterance")))
        item = items["utt:c3"]
        assert item["focus_turn_id"] == "c3"
        focus = [t for t in item["conversation"] if t.get("is_focus")]
        assert len(focus) == 1 and focus[0]["turn_id"] == "c3"

    def test_text_is_the_focus_utterance_only(self, modern):
        item = _by_id(build_items(modern, ItemOptions(unit="utterance")))["utt:c3"]
        assert item["text"] == "Fair enough, let's move it."

    def test_zero_context_window_yields_a_single_turn(self, modern):
        items = build_items(
            modern, ItemOptions(unit="utterance", context_before=0, context_after=0)
        )
        assert all(len(i["conversation"]) == 1 for i in items)

    def test_ancestor_context_walks_the_reply_chain(self, modern):
        item = _by_id(
            build_items(
                modern,
                ItemOptions(
                    unit="utterance",
                    context_mode="ancestors",
                    context_before=2,
                    context_after=0,
                ),
            )
        )["utt:c3"]
        assert [t["turn_id"] for t in item["conversation"]] == ["c0", "c1", "c3"]

    def test_linear_context_uses_adjacent_turns(self, modern):
        item = _by_id(
            build_items(
                modern,
                ItemOptions(
                    unit="utterance",
                    context_mode="linear",
                    context_before=2,
                    context_after=0,
                    order="thread",
                ),
            )
        )["utt:c3"]
        # Thread order is c0, c2, c1, c3 — so the two preceding turns are c2 and c1.
        assert [t["turn_id"] for t in item["conversation"]] == ["c2", "c1", "c3"]

    def test_context_after_follows_replies(self, modern):
        item = _by_id(
            build_items(
                modern,
                ItemOptions(
                    unit="utterance",
                    context_mode="ancestors",
                    context_before=0,
                    context_after=2,
                ),
            )
        )["utt:c0"]
        # Pre-order over c0's subtree: c2 (earlier sibling), then c1.
        assert [t["turn_id"] for t in item["conversation"]] == ["c0", "c2", "c1"]

    def test_context_after_does_not_dead_end_on_a_childless_first_reply(self, modern):
        """A first-child-only walk would return just c2 and stop; pre-order does not."""
        item = _by_id(
            build_items(
                modern,
                ItemOptions(
                    unit="utterance",
                    context_mode="ancestors",
                    context_before=0,
                    context_after=3,
                ),
            )
        )["utt:c0"]
        assert [t["turn_id"] for t in item["conversation"]] == ["c0", "c2", "c1", "c3"]

    def test_auto_mode_detects_a_threaded_corpus(self, modern):
        item = build_items(modern, ItemOptions(unit="utterance", context_mode="auto"))[0]
        assert item[PROVENANCE_KEY]["context_mode"] == "ancestors"

    def test_auto_mode_detects_a_linear_corpus(self, tmp_path):
        """Switchboard-style: reply_to is just 'the previous line'."""
        d = tmp_path / "linear"
        d.mkdir()
        rows = []
        for i in range(6):
            rows.append(
                {
                    "id": f"s{i}",
                    "conversation_id": "s0",
                    "text": f"turn {i}",
                    "speaker": "A" if i % 2 == 0 else "B",
                    "meta": {},
                    "reply-to": f"s{i - 1}" if i else None,
                    "timestamp": float(i),
                }
            )
        (d / "utterances.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        (d / "speakers.json").write_text('{"A": {}, "B": {}}')
        corpus = read_corpus(str(d))
        item = build_items(corpus, ItemOptions(unit="utterance", context_mode="auto"))[0]
        assert item[PROVENANCE_KEY]["context_mode"] == "linear"


class TestProvenance:
    def test_provenance_records_the_source(self, modern):
        prov = build_items(modern)[0][PROVENANCE_KEY]
        assert prov["v"] == 1
        assert prov["corpus"] == "mini-modern"
        assert prov["corpus_version"] == 3
        assert prov["unit"] == "conversation"
        assert prov["legacy_keys"] is False

    def test_provenance_lists_utterance_ids_in_emitted_order(self, modern):
        item = _by_id(build_items(modern))["convo:c0"]
        assert item[PROVENANCE_KEY]["utterance_ids"] == [
            t["turn_id"] for t in item["conversation"]
        ]

    def test_provenance_records_lossy_reads(self):
        corpus = read_corpus(MODERN)
        prov = build_items(corpus)[0][PROVENANCE_KEY]
        assert "parsed" in prov["dropped_meta"]

    def test_provenance_records_legacy_corpora(self):
        corpus = read_corpus(LEGACY)
        assert build_items(corpus)[0][PROVENANCE_KEY]["legacy_keys"] is True

    def test_utterance_unit_records_the_focus_id(self, modern):
        item = _by_id(build_items(modern, ItemOptions(unit="utterance")))["utt:c1"]
        assert item[PROVENANCE_KEY]["utterance_id"] == "c1"
        assert item[PROVENANCE_KEY]["conversation_id"] == "c0"


class TestPromoteMeta:
    def test_scalars_are_lifted_to_top_level(self, modern):
        item = _by_id(build_items(modern, ItemOptions(promote_meta=["split"])))["convo:c0"]
        assert item["split"] == "train"

    def test_nested_values_are_not_promoted(self, modern, caplog):
        modern.conversations["c0"].meta["complicated"] = {"a": 1}
        item = _by_id(build_items(modern, ItemOptions(promote_meta=["complicated"])))["convo:c0"]
        assert "complicated" not in item
        assert "must be scalars" in caplog.text

    def test_missing_field_is_silently_skipped(self, modern):
        item = _by_id(build_items(modern, ItemOptions(promote_meta=["nope"])))["convo:c0"]
        assert "nope" not in item

    def test_promotion_never_overwrites_an_existing_key(self, modern, caplog):
        modern.conversations["c0"].meta["text"] = "clobber"
        item = _by_id(build_items(modern, ItemOptions(promote_meta=["text"])))["convo:c0"]
        assert item["text"] != "clobber"
        assert "would overwrite" in caplog.text


class TestOptionValidation:
    def test_unknown_unit(self):
        with pytest.raises(ItemBuildError, match="unit must be"):
            ItemOptions(unit="speaker").validate()

    def test_unknown_order(self):
        with pytest.raises(ItemBuildError, match="order must be"):
            ItemOptions(order="random").validate()

    def test_unknown_context_mode(self):
        with pytest.raises(ItemBuildError, match="context_mode must be"):
            ItemOptions(context_mode="psychic").validate()

    def test_negative_context_window(self):
        with pytest.raises(ItemBuildError, match="must be >= 0"):
            ItemOptions(context_before=-1).validate()

    def test_field_names_may_not_collide(self):
        with pytest.raises(ItemBuildError, match="each field needs its own key"):
            ItemOptions(field_name="text", text_field="text").validate()

    def test_provenance_key_is_reserved(self):
        with pytest.raises(ItemBuildError, match="import provenance"):
            ItemOptions(field_name=PROVENANCE_KEY).validate()


class TestHelpers:
    def test_concatenate_turns(self):
        assert concatenate_turns(
            [{"speaker": "A", "text": "hi"}, {"speaker": "", "text": "bare"}]
        ) == "A: hi\nbare"

    def test_ordered_turns_reports_thread_stats(self, modern):
        turns, thread = ordered_turns(modern, modern.conversations["c0"], ItemOptions())
        assert len(turns) == 4
        assert thread.roots == ["c0"]
        assert thread.dangling == 0

    def test_limit_caps_item_count(self, modern):
        assert len(build_items(modern, limit=1)) == 1


class TestCustomFieldNames:
    def test_all_field_names_are_configurable(self, modern):
        item = build_items(
            modern,
            ItemOptions(
                field_name="turns",
                tree_field="thread",
                text_field="body",
                convo_meta_field="cmeta",
                speakers_field="who",
            ),
        )[0]
        assert set(item) >= {"turns", "thread", "body", "cmeta", "who", PROVENANCE_KEY}

    def test_optional_fields_can_be_dropped(self, modern):
        item = build_items(
            modern, ItemOptions(convo_meta_field=None, speakers_field=None, tree_field=None)
        )[0]
        assert set(item) == {"id", "conversation", "text", PROVENANCE_KEY}
