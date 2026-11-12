"""hf-relation: relations, events and coreference, fitted end to end on a
tiny model.

The sentences are templated so that the link depends on context: "works at"
links a person to an organization and "visited" does not, so a pair head
that ignored the words between two spans could not score well.
"""

import json
import os
import random
import types
from pathlib import Path

import pytest

from potato.training import worker
from potato.training.base import ResourceLimits, TrainingSpec
from potato.training.dataset import build_bundle, schema_specs_from_config
from potato.training.events import EXIT_OK, CollectingReporter
from potato.training.trainers.hf_relation import (decode_structure, gold_structure,
                                                  vocabularies)
from tests.helpers.test_utils import create_test_directory

HAVE_HF = all(__import__("importlib").util.find_spec(m) for m in
              ("torch", "transformers", "tokenizers"))
needs_hf = pytest.mark.skipif(not HAVE_HF, reason="torch/transformers absent")

PEOPLE = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi"]
ORGS = ["acme", "globex", "initech", "umbrella", "hooli", "vandelay"]
TRAIN = {"epochs": 40, "batch_size": 8, "learning_rate": 3e-3,
         "min_instances": 4, "patience": None}


@pytest.fixture
def work(request):
    return Path(create_test_directory("relation_" + request.node.name))


def _span(schema, label, text, word, nth=0, sid=None):
    start = -1
    for _ in range(nth + 1):
        start = text.index(word, start + 1)
    return {"schema": schema, "name": label, "title": label, "start": start,
            "end": start + len(word), "id": sid or "%s_%d" % (word, start)}


def _fit(work, schemes, items, annotations, name, vocab_words):
    from tests.helpers.tiny_hf import tiny_encoder
    config = {"task_dir": str(work),
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": schemes}
    context = types.SimpleNamespace(config=config, annotations=annotations,
                                    items=items, schemas=schemes,
                                    output_dir=str(work), phase_responses={})
    bundle, _, _ = build_bundle(context, str(work / "bundle"), [name], split_seed=1)
    params = dict(TRAIN, model_name=tiny_encoder(str(work / "m"), vocab_words))
    spec = TrainingSpec(
        run_id="r1", trainer="hf-relation",
        schemas=schema_specs_from_config(config, [name], bundle.manifest["labels"]),
        bundle_dir=bundle.root, workdir=str(work / "artifacts"), params=params,
        seed=3, limits=ResourceLimits(device="cpu"))
    report = CollectingReporter()
    code = worker.run(spec, report)
    assert code == EXIT_OK, [e["msg"] for e in report.of_type("log")][-5:]
    result = report.of_type("result")[0]
    with open(os.path.join(spec.workdir, "predictions.jsonl")) as fh:
        predictions = [json.loads(line) for line in fh if line.strip()]
    return result, predictions


ENTS = {"annotation_type": "span", "name": "ents", "labels": ["PER", "ORG", "TRIG"]}


@needs_hf
def test_relations_depend_on_the_words_between_the_spans(work):
    scheme = {"annotation_type": "span_link", "name": "rels", "span_schema": "ents",
              "link_types": [{"name": "WORKS_AT", "directed": True}]}
    items, annotations = {}, []
    rng = random.Random(0)
    for n in range(80):
        person, org = rng.choice(PEOPLE), rng.choice(ORGS)
        linked = n % 2 == 0
        text = "%s %s %s ." % (person, "works at" if linked else "visited", org)
        iid = "d%02d" % n
        items[iid] = {"id": iid, "text": text}
        p, o = _span("ents", "PER", text, person), _span("ents", "ORG", text, org)
        links = [{"schema": "rels", "link_type": "WORKS_AT", "direction": "directed",
                  "span_ids": [p["id"], o["id"]]}] if linked else []
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "spans": {"ents": [p, o]}, "links": {"rels": links}})
    words = PEOPLE + ORGS + ["works", "at", "visited", "."]
    result, predictions = _fit(work, [ENTS, scheme], items, annotations, "rels", words)
    metrics = result["metrics"]
    assert metrics["heldout_metric"] == "test f1"
    assert metrics["heldout_score"] >= 0.8, metrics
    assert metrics["test_mention_f1"] >= 0.9
    linked = [p for p in predictions if "works at" in items[p["instance_id"]]["text"]]
    payload = linked[0]["payload"]
    assert payload["links"] and payload["links"][0]["directed"] is True
    first, second = payload["links"][0]["spans"]
    assert payload["spans"][first]["label"] == "PER"
    assert payload["spans"][second]["label"] == "ORG"


@needs_hf
def test_coreference_clusters_a_pronoun_with_its_name(work):
    scheme = {"annotation_type": "coreference", "name": "coref", "span_schema": "ments"}
    ments = {"annotation_type": "span", "name": "ments", "labels": ["M"]}
    items, annotations = {}, []
    rng = random.Random(1)
    for n in range(48):
        a, b = rng.sample(PEOPLE, 2)
        text = "%s met %s and she smiled ." % (a, b) if n % 2 else \
            "%s said she met %s ." % (a, b)
        iid = "c%02d" % n
        items[iid] = {"id": iid, "text": text}
        spans = [_span("ments", "M", text, a), _span("ments", "M", text, b),
                 _span("ments", "M", text, "she")]
        # "she" is the first person in both templates.
        chain = {"schema": "coref", "link_type": "PERSON", "direction": "undirected",
                 "span_ids": [spans[0]["id"], spans[2]["id"]]}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "spans": {"ments": spans}, "links": {"coref": [chain]}})
    words = PEOPLE + ["met", "and", "she", "smiled", "said", "."]
    result, predictions = _fit(work, [ments, scheme], items, annotations, "coref", words)
    metrics = result["metrics"]
    assert metrics["heldout_metric"] == "test conll_f1"
    assert metrics["heldout_score"] >= 0.8, metrics
    cluster = predictions[0]["payload"]["clusters"][0]
    assert cluster["type"] == "PERSON" and len(cluster["spans"]) == 2


@needs_hf
def test_events_find_triggers_and_argument_roles(work):
    scheme = {"annotation_type": "event_annotation", "name": "events",
              "span_schema": "ents"}
    items, annotations = {}, []
    rng = random.Random(2)
    for n in range(48):
        boss, worker_ = rng.sample(PEOPLE, 2)
        text = "%s hired %s ." % (boss, worker_)
        iid = "e%02d" % n
        items[iid] = {"id": iid, "text": text}
        spans = [_span("ents", "PER", text, boss), _span("ents", "TRIG", text, "hired"),
                 _span("ents", "PER", text, worker_)]
        event = {"schema": "events", "event_type": "HIRE",
                 "trigger_span_id": spans[1]["id"],
                 "arguments": [{"role": "employer", "span_id": spans[0]["id"]},
                               {"role": "employee", "span_id": spans[2]["id"]}]}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "spans": {"ents": spans}, "events": {"events": [event]}})
    words = PEOPLE + ["hired", "."]
    result, predictions = _fit(work, [ENTS, scheme], items, annotations, "events", words)
    metrics = result["metrics"]
    assert metrics["heldout_metric"] == "test argument_f1"
    assert metrics["test_trigger_f1"] >= 0.9, metrics
    assert metrics["heldout_score"] >= 0.8, metrics
    (event,) = predictions[0]["payload"]["events"]
    assert {a["role"] for a in event["arguments"]} == {"employer", "employee"}


def test_gold_structure_and_decoding_agree():
    target = {"spans": [{"start": 0, "end": 5, "label": "PER"},
                        {"start": 6, "end": 9, "label": "ORG"}],
              "links": [{"type": "R", "spans": [0, 1], "directed": False}]}
    vocab = vocabularies("relation", [{"targets": {"s": target}}], "s")
    assert vocab["pair_classes"] == ["none", "R"] and vocab["directed"] == []
    pairs, _ = gold_structure("relation", target, vocab)
    assert pairs == {(0, 1): 1, (1, 0): 1}       # undirected: both orders
    spans = [dict(s, confidence=0.9) for s in target["spans"]]
    payload, decisions = decode_structure(
        "relation", spans, {(0, 1): [0.2, 0.8], (1, 0): [0.4, 0.6]}, [], vocab)
    assert payload["links"] == [{"type": "R", "spans": [0, 1], "directed": False}]
    assert min(decisions) == pytest.approx(0.7)


@needs_hf
def test_dependency_trees_decode_one_tree_per_sentence(work):
    """A dependency scheme as Potato stores it: every word a span, a directed
    span_link per word from its head (head first). Every training answer is
    a tree, so the run decodes trees and reports UAS and LAS."""
    scheme = {"annotation_type": "span_link", "name": "deps", "span_schema": "words",
              "link_types": [{"name": t, "directed": True}
                             for t in ("det", "nsubj", "obj", "punct")]}
    tokens = {"annotation_type": "span", "name": "words", "labels": ["W"]}
    nouns = ["cat", "dog", "bird", "fox", "cow", "owl"]
    verbs = ["saw", "chased", "heard", "liked"]
    items, annotations = {}, []
    rng = random.Random(3)
    for n in range(60):
        noun, verb, other = rng.choice(nouns), rng.choice(verbs), rng.choice(nouns)
        if n % 2:
            words = ["the", noun, verb, other, "."]
            arcs = [(1, 0, "det"), (2, 1, "nsubj"), (2, 3, "obj"), (2, 4, "punct")]
        else:
            words = [noun, verb, "the", other, "."]
            arcs = [(1, 0, "nsubj"), (3, 2, "det"), (1, 3, "obj"), (1, 4, "punct")]
        text = " ".join(words)
        iid = "t%02d" % n
        items[iid] = {"id": iid, "text": text}
        spans, at = [], 0
        for k, word in enumerate(words):
            start = text.index(word, at)
            spans.append({"schema": "words", "name": "W", "title": "W", "start": start,
                          "end": start + len(word), "id": "w%d" % k})
            at = start + len(word)
        links = [{"schema": "deps", "link_type": label, "direction": "directed",
                  "span_ids": ["w%d" % h, "w%d" % d]} for h, d, label in arcs]
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "spans": {"words": spans}, "links": {"deps": links}})
    vocab_words = nouns + verbs + ["the", "."]
    result, predictions = _fit(work, [tokens, scheme], items, annotations, "deps",
                               vocab_words)
    metrics = result["metrics"]
    assert metrics["test_uas"] >= 0.9, metrics
    assert metrics["test_las"] >= 0.85, metrics
    for prediction in predictions:
        payload = prediction["payload"]
        heads = [l["spans"][1] for l in payload["links"]]
        # One tree: one link fewer than words, no word with two heads.
        assert len(heads) == len(set(heads)) == len(payload["spans"]) - 1
