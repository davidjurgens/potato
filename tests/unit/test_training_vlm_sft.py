"""vlm-sft: a vision-language model fitted on text answers about images,
region captions, grounding and GUI clicks.

The model is a two-layer LLaVA built from a config (tests/helpers/tiny_hf.py),
so nothing downloads. It learns "red" against "blue" from the image; the
grounding, caption and click runs check the examples, the parsing and what
comes back, which a model this small cannot get right.
"""

import base64
import io
import json
import os

import pytest

from potato.training import registry
from potato.training.base import SchemaSpec
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from potato.training.trainers.vlm_sft import (VLMSFTTrainer, answer_region,
                                              click_verdict, parse_answer)
from tests.unit.test_training_detection_audio_dpo import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec
needs_torch = pytest.mark.skipif(not (HAVE("torch") and HAVE("transformers")),
                                 reason="torch/transformers absent")
WORDS = ["red", "blue", "what", "colour", "is", "this", "describe", "the", "box", "square",
         "where", "find", "click", "save", "task", "step", "should", "it", "answer", "with",
         "json", "on", "a", "grid", "or", "if", "not", "in", "image", "one", "sentence"]


def _png(tmp, name, colour, size=(40, 30)):
    from PIL import Image
    Image.new("RGB", size, colour).save(os.path.join(str(tmp), name))
    return name


def test_answers_parse_with_or_without_json():
    assert parse_answer('Sure: {"bbox": [10, 20, 300, 400]}') == {"bbox": [10, 20, 300, 400]}
    assert parse_answer('{"absent": true}') == {"absent": True}
    assert parse_answer("[12, 40, 300, 410]") == {"bbox": [12.0, 40.0, 300.0, 410.0]}
    assert parse_answer("at 500, 250") == {"point": [500.0, 250.0]}
    assert parse_answer("no idea") == {}
    box = answer_region({"bbox": [300, 400, 100, 200]}, "r")
    assert box["coordinates"] == pytest.approx({"x": 0.1, "y": 0.2, "width": 0.2, "height": 0.2})
    assert answer_region({"bbox": [5, 5, 5, 9]}, "r") is None
    assert answer_region({"point": [500, 250]}, "r")["coordinates"] == {"x": 0.5, "y": 0.25}


def test_click_verdicts():
    agent = {"x": 0.5, "y": 0.5}
    verdict, confidence = click_verdict({"x": 0.5, "y": 0.5}, agent, 0.05)
    assert verdict == "correct" and confidence == 1.0
    verdict, confidence = click_verdict({"x": 0.6, "y": 0.5}, agent, 0.05)
    assert verdict == "wrong_element" and confidence == 1.0
    assert click_verdict({"x": 0.54, "y": 0.5}, agent, 0.05)[0] == "correct"


def test_offered_for_image_answers_only():
    names = lambda scheme, modality: [t.name for t in registry.trainers_for_schema(
        scheme, modality)]
    assert "vlm-sft" in names({"annotation_type": "text"}, "image")
    assert "vlm-sft" not in names({"annotation_type": "text"}, "text")
    for kind in ("region_caption", "grounding_eval", "gui_trajectory"):
        assert "vlm-sft" in names({"annotation_type": kind}, "image")


def colour_project(tmp, n=16):
    items, annotations = {}, []
    for i in range(n):
        colour = "red" if i % 2 else "blue"
        iid = "c%02d" % i
        items[iid] = {"id": iid, "image": _png(tmp, iid + ".png",
                                               (220, 20, 20) if i % 2 else (20, 20, 220))}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"colour": {"text_box": colour}}})
    scheme = {"annotation_type": "text", "name": "colour",
              "description": "What colour is this?"}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    return config, context


def grounding_project(tmp, n=8):
    canvas = {"annotation_type": "image_annotation", "name": "canvas", "description": "",
              "labels": ["referent"], "tools": ["bbox"]}
    scheme = {"annotation_type": "grounding_eval", "name": "g", "description": ""}
    box = {"type": "bbox", "label": "referent",
           "coordinates": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}}
    items, annotations = {}, []
    for i in range(n):
        iid = "g%02d" % i
        items[iid] = {"id": iid, "image": _png(tmp, iid + ".png", (200, 200, 200)),
                      "expressions": ["the square", "the unicorn"]}
        if i < n - 1:
            annotations.append({"instance_id": iid, "user_id": "a", "labels": {"g": {
                "_data": json.dumps({"regions": {"0": [box]}, "absent": ["1"]})}}})
    config, context = _context(tmp, [canvas, scheme], items, annotations)
    return config, context


def test_examples_for_each_kind(tmp_path):
    trainer = VLMSFTTrainer()
    params = trainer.default_params()
    config, context = grounding_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["g"],
                                split_spec={"train": 1.0}, include_unlabeled=True)
    spec = SchemaSpec(name="g", annotation_type="grounding_eval", kind="grounding")
    row = next(bundle.read_split("train"))
    found, absent = trainer._examples(spec, row, bundle, params, for_training=True)
    assert json.loads(found["answer"]) == {"bbox": [250, 250, 750, 750]}
    assert json.loads(absent["answer"]) == {"absent": True}
    assert '"the square"' in found["prompt"]
    # The item nobody answered is asked both expressions, from the item.
    (unlabeled,) = list(bundle.read_split("unlabeled"))
    asked = trainer._examples(spec, unlabeled, bundle, params, for_training=False)
    assert [e["key"] for e in asked] == ["0", "1"] and all(e["answer"] is None for e in asked)


@needs_torch
def test_learns_the_colour_from_the_image(tmp_path):
    from tests.helpers.tiny_hf import tiny_vlm
    model_dir = tiny_vlm(str(tmp_path / "vlm"), WORDS)
    config, context = colour_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["colour"], split_seed=3)
    assert bundle.manifest["modality"] == "image"
    spec = _spec(tmp_path, config, bundle, "vlm-sft", "colour",
                 {"model_name": model_dir, "epochs": 25, "batch_size": 4,
                  "learning_rate": 3e-3, "lora": False, "min_instances": 4,
                  "max_new_tokens": 3, "patience": None})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_metric"].endswith("token_f1")
    assert result["metrics"]["heldout_score"] > 0.5
    records = _predictions(spec)
    assert {r["payload"] for r in records} <= {"red", "blue"}


@needs_torch
def test_grounding_and_captions_run_and_come_back_in_the_schemes_shape(tmp_path):
    from tests.helpers.tiny_hf import tiny_vlm
    model_dir = tiny_vlm(str(tmp_path / "vlm"), WORDS)
    config, context = grounding_project(tmp_path, n=10)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["g"], split_seed=1,
                                include_unlabeled=True)
    spec = _spec(tmp_path, config, bundle, "vlm-sft", "g",
                 {"model_name": model_dir, "epochs": 2, "min_instances": 4,
                  "max_new_tokens": 12, "lora": True})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_metric"].endswith("accuracy")
    for record in _predictions(spec):
        assert set(record["payload"]) == {"regions", "absent"}
        assert not record.get("heldout_only")


@needs_torch
def test_gui_clicks_train_on_approved_steps_only(tmp_path):
    from PIL import Image
    from tests.helpers.tiny_hf import tiny_vlm
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (240, 240, 240)).save(buffer, format="PNG")
    shot = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    items, annotations = {}, []
    for i in range(8):
        iid = "t%d" % i
        items[iid] = {"id": iid, "steps": [
            {"screenshot": shot, "action": "click save", "x": 0.5, "y": 0.5},
            {"screenshot": shot, "action": "click the box", "x": 0.1, "y": 0.9}]}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {"gui": {
            "gui": json.dumps([{"index": 0, "verdict": "correct"},
                               {"index": 1, "verdict": "wrong_element"}])}}})
    scheme = {"annotation_type": "gui_trajectory", "name": "gui", "description": ""}
    config, context = _context(tmp_path, [scheme], items, annotations)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["gui"], split_seed=2)
    trainer = VLMSFTTrainer()
    spec_schema = SchemaSpec(name="gui", annotation_type="gui_trajectory", kind="gui_click")
    examples = trainer._examples(spec_schema, next(bundle.read_split("train")), bundle,
                                 trainer.default_params(), for_training=True)
    assert [e["key"] for e in examples] == [0]
    assert json.loads(examples[0]["answer"]) == {"point": [500, 500]}

    model_dir = tiny_vlm(str(tmp_path / "vlm"), WORDS)
    spec = _spec(tmp_path, config, bundle, "vlm-sft", "gui",
                 {"model_name": model_dir, "epochs": 2, "min_instances": 3,
                  "max_new_tokens": 10, "lora": False})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert result["metrics"]["heldout_metric"].endswith("verdict_macro_f1")
    for record in _predictions(spec):
        for step in record["payload"]:
            assert step["verdict"] in ("correct", "wrong_element")
            assert 0 <= step["point"]["x"] <= 1


@needs_torch
def test_the_answer_is_trained_when_the_tokenizer_appends_a_special_token(tmp_path):
    """A BERT-style tokenizer ends every encoding with [SEP]. Measured on its
    own, the prompt was one token longer than it is inside the full example,
    and the answer's first token was masked out of the loss."""
    from tokenizers import processors
    from transformers import AutoProcessor
    from tests.helpers.tiny_hf import tiny_vlm
    processor = AutoProcessor.from_pretrained(tiny_vlm(str(tmp_path / "vlm"), WORDS))
    tok = processor.tokenizer
    tok.backend_tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", pair="[CLS] $A [SEP] $B [SEP]",
        special_tokens=[("[CLS]", tok.cls_token_id), ("[SEP]", tok.sep_token_id)])
    image = _png(tmp_path, "x.png", (200, 0, 0))
    encoded, _ = VLMSFTTrainer()._batch(
        processor, [{"path": os.path.join(str(tmp_path), image), "prompt": "what colour",
                     "answer": "red"}], VLMSFTTrainer.default_params(), "cpu", train=True)
    trained = [tok.convert_ids_to_tokens(int(i)) for i, label in
               zip(encoded["input_ids"][0], encoded["labels"][0]) if label != -100]
    assert trained[0] == "red"


def test_a_gpu_that_cannot_compile_kernels_is_refused_before_loading():
    """On a host whose NVRTC does not match torch's CUDA, Qwen2.5-VL failed
    after loading 3.8B parameters, in torch.prod, with a page of kernel
    source. The run now stops at validation and says what to install."""
    import types
    from unittest.mock import patch
    from potato.training.trainers import _hf_common as hf
    torch = pytest.importorskip("torch")
    spec = types.SimpleNamespace(limits=types.SimpleNamespace(device="auto"))

    def broken(*args, **kwargs):
        raise RuntimeError("extern C kernel source...\nnvrtc: error: failed to open "
                           "libnvrtc-builtins.so.13.0.\n  Make sure it is installed.")

    with patch.object(torch.cuda, "is_available", return_value=True), \
            patch.object(torch.version, "cuda", "13.0"), \
            patch.object(hf, "nvrtc_builtins_dir", return_value=None), \
            patch.object(torch, "ones", side_effect=broken):
        (problem,) = hf.jit_kernel_problems(spec)
    assert "libnvrtc-builtins.so.13.0" in problem and "nvidia-cuda-nvrtc" in problem
    with patch.object(torch.cuda, "is_available", return_value=False):
        assert hf.jit_kernel_problems(spec) == []
    cpu = types.SimpleNamespace(limits=types.SimpleNamespace(device="cpu"))
    assert hf.jit_kernel_problems(cpu) == []


def test_an_installed_but_unfound_nvrtc_is_named(tmp_path):
    """burger had libnvrtc-builtins.so.13.0 in site-packages/nvidia/cu13/lib,
    off the loader's path; "install nvidia-cuda-nvrtc" sent a person to
    install what was there."""
    import site
    import types
    from unittest.mock import patch
    from potato.training.trainers import _hf_common as hf
    torch = pytest.importorskip("torch")
    lib = tmp_path / "nvidia" / "cu13" / "lib"
    lib.mkdir(parents=True)
    (lib / "libnvrtc-builtins.so.13.0").write_bytes(b"")
    spec = types.SimpleNamespace(limits=types.SimpleNamespace(device="auto"))

    def broken(*args, **kwargs):
        raise RuntimeError("nvrtc: error: failed to open libnvrtc-builtins.so.13.0.")

    with patch.object(site, "getsitepackages", return_value=[str(tmp_path)]), \
            patch.object(torch.version, "cuda", "13.0"), \
            patch.object(torch.cuda, "is_available", return_value=True), \
            patch.object(torch, "ones", side_effect=broken):
        (problem,) = hf.jit_kernel_problems(spec)
        assert hf.nvrtc_builtins_dir("12.9") is None
    assert str(lib) in problem and "LD_LIBRARY_PATH" in problem
    assert "nvidia-cuda-nvrtc" not in problem
