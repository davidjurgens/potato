"""
Exporting Potato annotations back into ConvoKit metadata.

The shapes exercised here were taken from a real annotation session rather than
invented: `instance_id_to_label_to_value` really is a list of
``[{schema, name}, value]`` pairs, a radio really does store the chosen label as
the *key*, and a turn-level scheme really does arrive as a JSON string under the
name ``_data``.

The round-trip test at the bottom is the one that matters — everything else is
detail on the way there.
"""

import json
import os

import pytest

from potato.convokit import read_corpus
from potato.convokit.items import ItemOptions, build_items
from potato.convokit.writer import info_filename, write_corpus, write_info_files
from potato.export.base import ExportContext
from potato.export.convokit_exporter import ConvoKitExporter
from potato.export.registry import export_registry

FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "convokit"
)
MODERN = os.path.join(FIXTURES, "mini-modern")


@pytest.fixture
def corpus():
    return read_corpus(MODERN)


@pytest.fixture
def items(corpus):
    return {item["id"]: item for item in build_items(corpus)}


def turn_level_value(turns):
    """The stored shape of a turn-level annotation: a JSON string under _data."""
    return json.dumps({
        "v": 1,
        "schema_type": "multiselect",
        "turns": {
            tid: {"speaker": spk, "values": vals} for tid, (spk, vals) in turns.items()
        },
    })


def context(items, annotations, schemas=None, config=None):
    return ExportContext(
        config=config or {"instance_display": {"fields": [
            {"key": "conversation", "type": "dialogue", "span_target": True},
        ]}},
        annotations=annotations,
        items=items,
        schemas=schemas or [
            {"name": "derailed", "annotation_type": "radio"},
            {"name": "turn_problems", "annotation_type": "multiselect", "turn_level": True},
            {"name": "hostility", "annotation_type": "span"},
        ],
        output_dir="",
    )


class TestRegistration:
    def test_registered_without_optional_dependencies(self):
        assert export_registry.get("convokit") is not None

    def test_listed_among_formats(self):
        assert "convokit" in export_registry.get_supported_formats()


class TestCanExport:
    def test_rejects_items_without_provenance(self):
        ok, reason = ConvoKitExporter().can_export(
            context({"a": {"id": "a", "text": "x"}}, [])
        )
        assert ok is False
        assert "potato convokit" in reason

    def test_rejects_empty_items(self):
        ok, reason = ConvoKitExporter().can_export(context({}, []))
        assert ok is False
        assert "item data" in reason

    def test_accepts_imported_items(self, items):
        ok, _ = ConvoKitExporter().can_export(context(items, []))
        assert ok is True


class TestInfoMode:
    def _export(self, items, annotations, tmp_path, **options):
        result = ConvoKitExporter().export(
            context(items, annotations), str(tmp_path), options
        )
        assert result.success, result.errors
        return result

    def _read(self, tmp_path, field):
        path = os.path.join(str(tmp_path), info_filename(field))
        with open(path) as f:
            return {json.loads(line)["id"]: json.loads(line)["value"] for line in f}

    def test_line_format_is_exactly_id_and_value(self, items, tmp_path):
        """convokit reads these with index_key='id', value_key='value'."""
        self._export(
            items,
            [{"instance_id": "convo:c0", "user_id": "u1",
              "labels": {"derailed": {"yes": "yes"}}, "spans": {}}],
            tmp_path,
        )
        path = os.path.join(str(tmp_path), info_filename("potato_derailed"))
        with open(path) as f:
            entry = json.loads(f.readline())
        assert set(entry) == {"id", "value"}

    def test_conversation_label_lands_on_the_conversation(self, items, tmp_path):
        self._export(
            items,
            [{"instance_id": "convo:c0", "user_id": "u1",
              "labels": {"derailed": {"yes": "yes"}}, "spans": {}}],
            tmp_path,
        )
        assert self._read(tmp_path, "potato_derailed") == {"c0": {"u1": "yes"}}

    def test_turn_level_annotation_keys_by_utterance_id(self, items, tmp_path):
        """The whole point: turn ids ARE ConvoKit utterance ids."""
        self._export(
            items,
            [{"instance_id": "convo:c0", "user_id": "u1",
              "labels": {"turn_problems": {"_data": turn_level_value(
                  {"c1": ("bob", ["attack"]), "c3": ("alice", ["snark"])})}},
              "spans": {}}],
            tmp_path,
        )
        stored = self._read(tmp_path, "potato_turn_problems")
        assert stored == {"c1": {"u1": ["attack"]}, "c3": {"u1": ["snark"]}}

    def test_manifest_records_the_object_type_per_field(self, items, tmp_path):
        self._export(
            items,
            [{"instance_id": "convo:c0", "user_id": "u1",
              "labels": {"derailed": {"yes": "yes"},
                         "turn_problems": {"_data": turn_level_value({"c1": ("bob", ["x"])})}},
              "spans": {}}],
            tmp_path,
        )
        with open(os.path.join(str(tmp_path), "potato_export_manifest.json")) as f:
            manifest = json.load(f)
        assert manifest["object_types"]["potato_derailed"] == "conversation"
        assert manifest["object_types"]["potato_turn_problems"] == "utterance"

    def test_filename_survives_convokits_own_slicing(self):
        """Upstream recovers the field by stripping 'info.' and '.jsonl'."""
        name = info_filename("potato_turn_problems")
        assert name[len("info."):-len(".jsonl")] == "potato_turn_problems"

    def test_dotted_field_names_are_refused(self, tmp_path):
        """A dot would be sliced out by the loader and attach to the wrong key."""
        written = write_info_files(str(tmp_path), {("utterance", "bad.name"): {"a": 1}})
        assert written == []

    def test_utterance_unit_labels_land_on_the_utterance(self, corpus, tmp_path):
        utt_items = {i["id"]: i for i in build_items(corpus, ItemOptions(unit="utterance"))}
        ConvoKitExporter().export(
            context(utt_items, [{"instance_id": "utt:c1", "user_id": "u1",
                                 "labels": {"derailed": {"yes": "yes"}}, "spans": {}}]),
            str(tmp_path), {},
        )
        assert self._read(tmp_path, "potato_derailed") == {"c1": {"u1": "yes"}}


class TestMultipleAnnotators:
    def _export(self, items, annotations, tmp_path, **options):
        ConvoKitExporter().export(context(items, annotations), str(tmp_path), options)
        path = os.path.join(str(tmp_path), info_filename("potato_derailed"))
        with open(path) as f:
            return {json.loads(l)["id"]: json.loads(l)["value"] for l in f}

    def _three_annotators(self):
        return [
            {"instance_id": "convo:c0", "user_id": u,
             "labels": {"derailed": {v: v}}, "spans": {}}
            for u, v in (("u1", "yes"), ("u2", "yes"), ("u3", "no"))
        ]

    def test_default_keeps_every_annotator(self, items, tmp_path):
        stored = self._export(items, self._three_annotators(), tmp_path)
        assert stored["c0"] == {"u1": "yes", "u2": "yes", "u3": "no"}

    def test_annotator_count_is_recorded(self, items, tmp_path):
        ConvoKitExporter().export(
            context(items, self._three_annotators()), str(tmp_path), {}
        )
        path = os.path.join(str(tmp_path), info_filename("potato_derailed_n_annotators"))
        with open(path) as f:
            assert json.loads(f.readline())["value"] == 3

    def test_majority_aggregates_but_keeps_the_raw_form(self, items, tmp_path):
        stored = self._export(
            items, self._three_annotators(), tmp_path, aggregate="majority"
        )
        assert stored["c0"] == "yes"
        raw_path = os.path.join(str(tmp_path), info_filename("potato_derailed_raw"))
        with open(raw_path) as f:
            assert json.loads(f.readline())["value"] == {
                "u1": "yes", "u2": "yes", "u3": "no"
            }

    def test_mean_over_non_numeric_falls_back_to_raw(self, items, tmp_path):
        """Better to keep the annotations than to drop what cannot be averaged."""
        stored = self._export(items, self._three_annotators(), tmp_path, aggregate="mean")
        assert stored["c0"] == {"u1": "yes", "u2": "yes", "u3": "no"}

    def test_mean_over_numbers(self, items, tmp_path):
        annotations = [
            {"instance_id": "convo:c0", "user_id": u,
             "labels": {"derailed": {"": v}}, "spans": {}}
            for u, v in (("u1", 1), ("u2", 2), ("u3", 3))
        ]
        stored = self._export(items, annotations, tmp_path, aggregate="mean")
        assert stored["c0"] == 2.0


class TestSpanSplitting:
    """Spans are field-scoped; they must come back as per-utterance offsets."""

    def _spans(self, items, span, tmp_path, show_turn_numbers=False):
        config = {"instance_display": {"fields": [{
            "key": "conversation", "type": "dialogue", "span_target": True,
            "display_options": {"show_turn_numbers": show_turn_numbers},
        }]}}
        ConvoKitExporter().export(
            context(
                items,
                [{"instance_id": "convo:c0", "user_id": "u1", "labels": {},
                  "spans": {"hostility": [span]}}],
                config=config,
            ),
            str(tmp_path), {},
        )
        path = os.path.join(str(tmp_path), info_filename("potato_hostility_spans"))
        with open(path) as f:
            return {json.loads(l)["id"]: json.loads(l)["value"] for l in f}

    def _layout(self, items):
        """The character layout the display renders and the server reconstructs."""
        turns = items["convo:c0"]["conversation"]
        text = "\n".join(
            f"{t['speaker']}: {t['text']}" if t.get("speaker") else t["text"]
            for t in turns
        )
        return turns, text

    def test_span_inside_one_turn(self, items, tmp_path):
        turns, layout = self._layout(items)
        phrase = "rename this article"
        start = layout.index(phrase)
        stored = self._spans(
            items,
            {"schema": "hostility", "name": "insult", "label": "insult",
             "start": start, "end": start + len(phrase),
             "target_field": "conversation", "id": "s1"},
            tmp_path,
        )
        assert list(stored) == ["c0"]
        piece = stored["c0"]["u1"][0]
        assert piece["text"] == phrase
        # Offsets are relative to the utterance's OWN text.
        assert turns[0]["text"][piece["start"]:piece["end"]] == phrase

    def test_span_crossing_a_turn_boundary_is_split(self, items, tmp_path):
        turns, layout = self._layout(items)
        # From inside turn 0 to inside the next rendered turn.
        first_text = turns[0]["text"]
        start = layout.index(first_text) + len(first_text) - 8
        end = start + 30
        stored = self._spans(
            items,
            {"schema": "hostility", "name": "insult", "label": "insult",
             "start": start, "end": end, "target_field": "conversation", "id": "s2"},
            tmp_path,
        )
        assert len(stored) == 2
        groups = {
            piece["span_group"]
            for value in stored.values() for piece in value["u1"]
        }
        assert groups == {"s2"}, "pieces of one span must share a span_group"

    def test_offsets_account_for_turn_numbers(self, items, tmp_path):
        turns, base = self._layout(items)
        numbered = "\n".join(
            f"[{i+1}] " + (f"{t['speaker']}: {t['text']}" if t.get("speaker") else t["text"])
            for i, t in enumerate(turns)
        )
        phrase = "rename this article"
        start = numbered.index(phrase)
        stored = self._spans(
            items,
            {"schema": "hostility", "name": "insult", "label": "insult",
             "start": start, "end": start + len(phrase),
             "target_field": "conversation", "id": "s3"},
            tmp_path,
            show_turn_numbers=True,
        )
        piece = stored["c0"]["u1"][0]
        assert piece["text"] == phrase

    def test_span_on_a_non_turn_field_is_warned_not_crashed(self, items, tmp_path):
        result = ConvoKitExporter().export(
            context(
                items,
                [{"instance_id": "convo:c0", "user_id": "u1", "labels": {},
                  "spans": {"hostility": [{"schema": "hostility", "name": "x",
                                           "start": 0, "end": 3,
                                           "target_field": "text"}]}}],
            ),
            str(tmp_path), {},
        )
        assert result.success
        assert any("cannot be mapped" in w for w in result.warnings)

    def test_spans_can_be_disabled(self, items, tmp_path):
        turns, layout = self._layout(items)
        result = ConvoKitExporter().export(
            context(
                items,
                [{"instance_id": "convo:c0", "user_id": "u1", "labels": {},
                  "spans": {"hostility": [{"schema": "hostility", "name": "x",
                                           "start": 0, "end": 5,
                                           "target_field": "conversation"}]}}],
            ),
            str(tmp_path), {"include_spans": False},
        )
        assert result.stats["spans_exported"] == 0


class TestPositionalTurnIdFallback:
    def test_t_index_ids_resolve_through_provenance(self, items, tmp_path):
        """Data not produced by our importer stores t0/t1 instead of real ids."""
        ConvoKitExporter().export(
            context(items, [{
                "instance_id": "convo:c0", "user_id": "u1",
                "labels": {"turn_problems": {"_data": json.dumps({
                    "v": 1, "schema_type": "multiselect",
                    "turns": {"t1": {"values": ["x"]}},
                })}},
                "spans": {},
            }]),
            str(tmp_path), {},
        )
        path = os.path.join(str(tmp_path), info_filename("potato_turn_problems"))
        with open(path) as f:
            stored = {json.loads(l)["id"]: json.loads(l)["value"] for l in f}
        expected = items["convo:c0"]["_convokit"]["utterance_ids"][1]
        assert stored == {expected: {"u1": ["x"]}}

    def test_out_of_range_index_is_counted_not_fatal(self, items, tmp_path):
        result = ConvoKitExporter().export(
            context(items, [{
                "instance_id": "convo:c0", "user_id": "u1",
                "labels": {"turn_problems": {"_data": json.dumps({
                    "v": 1, "schema_type": "multiselect",
                    "turns": {"t99": {"values": ["x"]}},
                })}},
                "spans": {},
            }]),
            str(tmp_path), {},
        )
        assert result.success
        assert result.stats["unresolved_turn_ids"] == 1


class TestCorpusMode:
    def test_writes_all_five_files(self, items, tmp_path):
        result = ConvoKitExporter().export(
            context(items, [{"instance_id": "convo:c0", "user_id": "u1",
                             "labels": {"derailed": {"yes": "yes"}}, "spans": {}}]),
            str(tmp_path), {"mode": "corpus"},
        )
        assert result.success, result.errors
        assert {os.path.basename(p) for p in result.files_written} == {
            "utterances.jsonl", "speakers.json", "conversations.json",
            "corpus.json", "index.json",
        }

    def test_index_types_are_one_element_lists(self, items, tmp_path):
        ConvoKitExporter().export(
            context(items, [{"instance_id": "convo:c0", "user_id": "u1",
                             "labels": {"derailed": {"yes": "yes"}}, "spans": {}}]),
            str(tmp_path), {"mode": "corpus"},
        )
        with open(os.path.join(str(tmp_path), "index.json")) as f:
            index = json.load(f)
        for entry in index["conversations-index"].values():
            assert isinstance(entry, list)
        assert isinstance(index["version"], int)

    def test_records_what_was_dropped_on_import(self, items, tmp_path):
        ConvoKitExporter().export(
            context(items, []), str(tmp_path), {"mode": "corpus"}
        )
        with open(os.path.join(str(tmp_path), "corpus.json")) as f:
            meta = json.load(f)
        assert "parsed" in meta["potato_dropped_meta"]

    def test_unknown_mode_is_an_error(self, items, tmp_path):
        result = ConvoKitExporter().export(
            context(items, []), str(tmp_path), {"mode": "banana"}
        )
        assert result.success is False
        assert "Unknown mode" in result.errors[0]

    def test_unknown_aggregate_is_an_error(self, items, tmp_path):
        result = ConvoKitExporter().export(
            context(items, []), str(tmp_path), {"aggregate": "median"}
        )
        assert result.success is False


class TestRoundTrip:
    """corpus -> items -> annotate -> export -> corpus, with nothing lost."""

    def test_full_round_trip(self, corpus, items, tmp_path):
        annotations = [
            {"instance_id": "convo:c0", "user_id": "u1",
             "labels": {
                 "derailed": {"yes": "yes"},
                 "turn_problems": {"_data": turn_level_value(
                     {"c1": ("bob", ["attack"]), "c3": ("alice", ["snark"])})},
             },
             "spans": {}},
            {"instance_id": "convo:d0", "user_id": "u2",
             "labels": {"derailed": {"no": "no"}}, "spans": {}},
        ]
        result = ConvoKitExporter().export(
            context(items, annotations), str(tmp_path), {"mode": "corpus"}
        )
        assert result.success, result.errors

        restored = read_corpus(str(tmp_path))

        # Every utterance survives.
        assert set(restored.utterances) == set(corpus.utterances)
        assert set(restored.conversations) == set(corpus.conversations)

        # Original metadata survives alongside the new.
        assert restored.utterances["c0"].meta["is_section_header"] is True
        assert restored.conversations["c0"].meta["page_title"] == "Talk:Example"

        # The annotations landed on the right objects, keyed by real ids.
        assert restored.utterances["c1"].meta["potato_turn_problems"] == {"u1": ["attack"]}
        assert restored.utterances["c3"].meta["potato_turn_problems"] == {"u1": ["snark"]}
        assert restored.conversations["c0"].meta["potato_derailed"] == {"u1": "yes"}
        assert restored.conversations["d0"].meta["potato_derailed"] == {"u2": "no"}

        # Structure survives.
        assert restored.utterances["c3"].reply_to == "c1"
        assert restored.utterances["c1"].speaker == "bob"
        assert restored.utterances["c1"].timestamp == 1200.0

    def test_unannotated_objects_carry_no_potato_fields(self, items, tmp_path):
        ConvoKitExporter().export(
            context(items, [{"instance_id": "convo:c0", "user_id": "u1",
                             "labels": {"derailed": {"yes": "yes"}}, "spans": {}}]),
            str(tmp_path), {"mode": "corpus"},
        )
        restored = read_corpus(str(tmp_path))
        assert not any(
            k.startswith("potato_") for k in restored.conversations["d0"].meta
        )

    def test_exported_corpus_is_readable_by_the_reader_contract(self, items, tmp_path):
        ConvoKitExporter().export(context(items, []), str(tmp_path), {"mode": "corpus"})
        restored = read_corpus(str(tmp_path))
        assert restored.legacy is False
        assert restored.index.present is True
