"""hf-conversation-tree: node answers and the selected path, fitted end to
end on a tiny model. Polite replies are rated 5 and rude ones 1, and the
annotators' path always follows the polite reply."""

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
from tests.helpers.test_utils import create_test_directory

HAVE_HF = all(__import__("importlib").util.find_spec(m) for m in
              ("torch", "transformers", "tokenizers"))
needs_hf = pytest.mark.skipif(not HAVE_HF, reason="torch/transformers absent")

GOOD = ["thanks so much glad to help", "happy to help thank you", "kind thanks glad"]
BAD = ["go away stupid", "whatever stupid idiot", "shut up go away"]
QUESTIONS = ["can you help me", "where is the station", "what time is it"]


@pytest.fixture
def work(request):
    return Path(create_test_directory("conv_tree_" + request.node.name))


@needs_hf
def test_conversation_tree_rates_turns_and_follows_the_better_reply(work):
    from tests.helpers.tiny_hf import tiny_encoder
    rng = random.Random(0)
    scheme = {"annotation_type": "tree_annotation", "name": "conv",
              "node_scheme": {"annotation_type": "likert", "name": "conv_node", "size": 5},
              "path_selection": {"enabled": True}}
    items, annotations = {}, []
    for n in range(40):
        good, bad = rng.choice(GOOD), rng.choice(BAD)
        children = [{"id": "g", "speaker": "B", "text": good, "children": []},
                    {"id": "b", "speaker": "B", "text": bad, "children": []}]
        rng.shuffle(children)
        tree = {"id": "root", "speaker": "A", "text": rng.choice(QUESTIONS),
                "children": children}
        iid = "c%02d" % n
        items[iid] = {"id": iid, "text": "", "tree": tree}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {"conv": {
            "selected_path": json.dumps(["root", "g"]),
            "node_annotations": json.dumps({"g": {"conv_node": "5"},
                                            "b": {"conv_node": "1"}})}}})
    config = {"task_dir": str(work), "item_properties": {"id_key": "id", "text_key": "text"},
              "instance_display": {"fields": [{"key": "tree", "type": "conversation_tree"}]},
              "annotation_schemes": [scheme]}
    context = types.SimpleNamespace(config=config, annotations=annotations, items=items,
                                    schemas=[scheme], output_dir=str(work),
                                    phase_responses={})
    bundle, _, _ = build_bundle(context, str(work / "bundle"), ["conv"], split_seed=1)
    words = " ".join(GOOD + BAD + QUESTIONS + ["A", "B"]).split()
    spec = TrainingSpec(
        run_id="r1", trainer="hf-conversation-tree",
        schemas=schema_specs_from_config(config, ["conv"], bundle.manifest["labels"]),
        bundle_dir=bundle.root, workdir=str(work / "artifacts"),
        params={"epochs": 25, "batch_size": 8, "learning_rate": 3e-3, "min_instances": 4,
                "patience": None, "model_name": tiny_encoder(str(work / "m"), words)},
        seed=3, limits=ResourceLimits(device="cpu"))
    report = CollectingReporter()
    assert worker.run(spec, report) == EXIT_OK, [e["msg"] for e in report.of_type("log")][-4:]
    metrics = report.of_type("result")[0]["metrics"]
    assert metrics["heldout_metric"] == "test node_macro_f1"
    assert metrics["heldout_score"] >= 0.9, metrics
    assert metrics["test_path_accuracy"] >= 0.9, metrics
    with open(os.path.join(spec.workdir, "predictions.jsonl")) as fh:
        payload = json.loads(fh.readline())["payload"]
    assert payload["path"] == ["root", "g"]
    assert payload["nodes"]["g"] == {"conv_node": "5"}
