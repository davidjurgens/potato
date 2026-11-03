"""Bundle targets for answers that are structures: links, chains, events,
rankings, BWS, soft labels, glosses, conversation trees, scale preferences,
and the soft targets learning from disagreement trains on.

Each of these reached the bundle with no target before: links were never
exported, a ranking or BWS answer has more than one value, and a soft label
or gloss read as a label named after its key. The records here have the
shapes ``export.cli.load_annotations_from_output_dir`` produces from real
user states.
"""

import json
import types

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from tests.helpers.test_utils import create_test_directory


def _bundle(name, schemes, annotations, items):
    root = create_test_directory("structured_targets_" + name)
    config = {"task_dir": root, "item_properties": {"id_key": "id",
                                                    "text_key": "text"},
              "annotation_schemes": schemes}
    context = types.SimpleNamespace(config=config, annotations=annotations,
                                    items=items, schemas=schemes,
                                    output_dir=root, phase_responses={})
    names = [s["name"] for s in schemes if not s.get("_support")]
    bundle, stats, _ = build_bundle(context, root + "/bundle", names)
    rows = {}
    for split in ("train", "val", "test"):
        for row in bundle.read_split(split):
            rows[row["instance_id"]] = row
    return bundle, rows


def _span(schema, label, start, end, span_id):
    return {"schema": schema, "name": label, "title": label, "start": start,
            "end": end, "id": span_id}


SPANS = {"annotation_type": "span", "name": "ents", "labels": ["PER", "ORG"],
         "_support": True}
TEXT = "Alice joined Acme in May."


def _link_record(user, suffix, links):
    return {"instance_id": "d1", "user_id": user, "labels": {},
            "spans": {"ents": [_span("ents", "PER", 0, 5, "p" + suffix),
                               _span("ents", "ORG", 13, 17, "o" + suffix)]},
            "links": {"rels": links}}


def test_links_become_span_positions_and_two_annotators_agree():
    scheme = {"annotation_type": "span_link", "name": "rels",
              "span_schema": "ents", "link_types": [{"name": "WORKS_FOR"}]}
    # Same answer, different browser-made ids and colours.
    annotations = [
        _link_record("alice", "1", [{"id": "l1", "schema": "rels",
                                     "link_type": "WORKS_FOR",
                                     "span_ids": ["p1", "o1"],
                                     "direction": "directed",
                                     "properties": {"color": "#f00"}}]),
        # bob's link lost its ids; the offsets it kept still resolve.
        _link_record("bob", "2", [{"id": "zz", "schema": "rels",
                                   "link_type": "WORKS_FOR",
                                   "span_ids": ["gone-a", "gone-b"],
                                   "direction": "directed",
                                   "properties": {"span_positions": [
                                       {"start": 0, "end": 5},
                                       {"start": 13, "end": 17}]}}])]
    bundle, rows = _bundle("links", [SPANS, scheme], annotations,
                           {"d1": {"id": "d1", "text": TEXT}})
    target = rows["d1"]["targets"]["rels"]
    assert target == {
        "spans": [{"start": 0, "end": 5, "label": "PER"},
                  {"start": 13, "end": 17, "label": "ORG"}],
        "links": [{"type": "WORKS_FOR", "spans": [0, 1], "directed": True}]}
    assert bundle.labels("rels") == ["WORKS_FOR"]


def test_a_directed_link_keeps_its_order_and_an_undirected_one_is_sorted():
    from potato.training.structured import canonical_answer
    spans = [_span("ents", "PER", 0, 5, "a"), _span("ents", "ORG", 13, 17, "b")]
    scheme = {"name": "rels", "span_schema": "ents"}
    directed = canonical_answer("relation", scheme, spans=spans, links=[
        {"schema": "rels", "link_type": "R", "span_ids": ["b", "a"],
         "direction": "directed"}])
    undirected = canonical_answer("relation", scheme, spans=spans, links=[
        {"schema": "rels", "link_type": "R", "span_ids": ["b", "a"],
         "direction": "undirected"}])
    assert directed["links"][0]["spans"] == [1, 0]
    assert undirected["links"][0]["spans"] == [0, 1]


def test_coreference_chains_become_clusters():
    scheme = {"annotation_type": "coreference", "name": "coref",
              "span_schema": "ments"}
    record = {"instance_id": "d1", "user_id": "alice", "labels": {},
              "spans": {"ments": [_span("ments", "MENTION", 0, 5, "m1"),
                                  _span("ments", "MENTION", 18, 21, "m2"),
                                  _span("ments", "MENTION", 30, 34, "m3")]},
              "links": {"coref": [{"schema": "coref", "link_type": "PERSON",
                                   "span_ids": ["m2", "m1"],
                                   "direction": "undirected"}]}}
    _, rows = _bundle("coref", [{"annotation_type": "span", "name": "ments",
                                 "_support": True}, scheme], [record],
                      {"d1": {"id": "d1", "text": "Alice said that she and Bob left."}})
    target = rows["d1"]["targets"]["coref"]
    assert len(target["spans"]) == 3
    # m3 is in no chain: a singleton mention.
    assert target["clusters"] == [{"type": "PERSON", "spans": [0, 1]}]


def test_events_become_trigger_and_argument_positions():
    scheme = {"annotation_type": "event_annotation", "name": "events",
              "span_schema": "ents"}
    record = _link_record("alice", "1", [])
    record["spans"]["ents"].append(_span("ents", "TRIGGER", 6, 12, "t1"))
    record["events"] = {"events": [{"schema": "events", "event_type": "HIRE",
                                    "trigger_span_id": "t1",
                                    "arguments": [{"role": "org", "span_id": "o1"},
                                                  {"role": "employee", "span_id": "p1"}]}]}
    bundle, rows = _bundle("events", [SPANS, scheme], [record],
                           {"d1": {"id": "d1", "text": TEXT}})
    target = rows["d1"]["targets"]["events"]
    labels = [s["label"] for s in target["spans"]]
    assert labels == ["PER", "TRIGGER", "ORG"]
    assert target["events"] == [{"type": "HIRE", "trigger": 1, "arguments": [
        {"role": "employee", "span": 0}, {"role": "org", "span": 2}]}]
    assert bundle.labels("events") == ["HIRE"]


def test_link_kinds_are_not_offered_the_span_tagger():
    for atype in ("span_link", "coreference", "event_annotation",
                  "tree_annotation"):
        names = [t.name for t in registry.trainers_for_schema(
            {"annotation_type": atype, "name": "x", "span_schema": "ents"})]
        assert "hf-token-classification" not in names, atype


def test_a_ranking_target_is_the_whole_order():
    scheme = {"annotation_type": "ranking", "name": "rank",
              "labels": ["Cost", "Speed", "Quality"]}
    annotations = [{"instance_id": "q%d" % n, "user_id": "alice",
                    "labels": {"rank": {"rank_order": "Speed,Quality,Cost"}}}
                   for n in range(4)]
    bundle, rows = _bundle("ranking", [scheme], annotations,
                           {"q%d" % n: {"id": "q%d" % n, "text": "t"} for n in range(4)})
    assert {r["targets"]["rank"][0] for r in rows.values()} == {"Speed"}
    assert next(iter(rows.values()))["targets"]["rank"] == ["Speed", "Quality", "Cost"]
    assert bundle.labels("rank") == ["Cost", "Quality", "Speed"]


def test_a_bws_target_is_letters_and_the_row_carries_the_tuple():
    scheme = {"annotation_type": "bws", "name": "bws"}
    items = {"bws_tuple_0001": {"id": "bws_tuple_0001", "text": "",
                                "_bws_items": [
                                    {"source_id": "x", "text": "second", "position": 1},
                                    {"source_id": "y", "text": "first", "position": 0},
                                    {"source_id": "z", "text": "third", "position": 2}]}}
    annotations = [{"instance_id": "bws_tuple_0001", "user_id": "alice",
                    "labels": {"bws": {"best": "A", "worst": "C"}}}]
    _, rows = _bundle("bws", [scheme], annotations, items)
    row = rows["bws_tuple_0001"]
    assert row["targets"]["bws"] == {"best": "A", "worst": "C"}
    assert row["candidates"] == ["first", "second", "third"]


def test_soft_label_target_is_the_annotators_mean_distribution():
    scheme = {"annotation_type": "soft_label", "name": "soft",
              "labels": ["pos", "neg"], "total": 100}
    annotations = [
        {"instance_id": "i1", "user_id": "alice",
         "labels": {"soft": {"pos": "80", "neg": "20"}}},
        {"instance_id": "i1", "user_id": "bob",
         "labels": {"soft": {"pos": "40", "neg": "60"}}}]
    bundle, rows = _bundle("soft", [scheme], annotations,
                           {"i1": {"id": "i1", "text": "fine"}})
    assert rows["i1"]["targets"]["soft"] == {"neg": 0.4, "pos": 0.6}
    assert bundle.labels("soft") == ["neg", "pos"]


def test_soft_targets_keep_the_vote_split_the_label_hides():
    scheme = {"annotation_type": "radio", "name": "s", "labels": ["pos", "neg"]}
    annotations = [{"instance_id": "i1", "user_id": u, "labels": {"s": {lab: True}}}
                   for u, lab in (("a", "pos"), ("b", "pos"), ("c", "neg"))]
    annotations.append({"instance_id": "i2", "user_id": "a",
                        "labels": {"s": {"neg": True}}})
    _, rows = _bundle("soft_vote", [scheme], annotations,
                      {i: {"id": i, "text": i} for i in ("i1", "i2")})
    assert rows["i1"]["targets"]["s"] == "pos"
    assert rows["i1"]["soft_targets"]["s"] == pytest.approx(
        {"pos": 2 / 3, "neg": 1 / 3}, abs=1e-5)
    # One annotator: nothing to learn about disagreement.
    assert "soft_targets" not in rows["i2"]


def test_a_gloss_answer_is_decoded():
    scheme = {"annotation_type": "interlinear_gloss", "name": "igt"}
    answer = {"words": [{"word": "kitabım", "morphemes": "kitab-ım",
                         "gloss": "book-1SG.POSS"}], "translation": "my book"}
    annotations = [{"instance_id": "s1", "user_id": "alice",
                    "labels": {"igt": {"igt": json.dumps(answer)}}}]
    _, rows = _bundle("gloss", [scheme], annotations,
                      {"s1": {"id": "s1", "text": "kitabım"}})
    assert rows["s1"]["targets"]["igt"]["words"][0]["gloss"] == "book-1SG.POSS"


def test_a_conversation_tree_answer_is_its_path_and_node_labels():
    scheme = {"annotation_type": "tree_annotation", "name": "tree"}
    annotations = [{"instance_id": "c1", "user_id": "alice", "labels": {"tree": {
        "selected_path": json.dumps(["root", "r2"]),
        "node_annotations": json.dumps({"r1": {"tree_node": "4"}})}}}]
    tree = {"id": "root", "text": "Hi", "children": [
        {"id": "r1", "text": "Hello", "children": []},
        {"id": "r2", "text": "Hey", "children": []}]}
    _, rows = _bundle("tree", [scheme], annotations,
                      {"c1": {"id": "c1", "text": "", "conversation": tree}})
    assert rows["c1"]["targets"]["tree"] == {
        "path": ["root", "r2"], "nodes": {"r1": {"tree_node": "4"}}}
    # The tree itself travels with the row: it is the trainer's input.
    assert rows["c1"]["tree"] == tree


def test_a_scale_preference_is_a_number():
    scheme = {"annotation_type": "pairwise", "name": "pref", "mode": "scale"}
    assert registry.kind_of_schema(scheme) == "preference_scale"
    annotations = [{"instance_id": "p1", "user_id": "alice",
                    "labels": {"pref": {"scale_value": "-2"}}}]
    _, rows = _bundle("scale", [scheme], annotations,
                      {"p1": {"id": "p1", "text": ["one", "two"]}})
    assert rows["p1"]["targets"]["pref"] == -2.0
