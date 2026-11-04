"""QLoRA: ``lora.quantize`` loads the base model in 4 or 8 bits.

Quantization runs only on a CUDA GPU with bitsandbytes, so on this machine
the tests check what can be checked without one: the refusals, the
``from_pretrained`` arguments, and that a quantized model is never moved
with ``.to()``. The run itself is checked on a GPU host through a SLURM or
ssh backend (plans/training-group1-infrastructure.md, Phase 3).
"""

import types

import pytest

from potato.training.trainers import _hf_common as hf

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")


def _spec(device="auto"):
    return types.SimpleNamespace(limits=types.SimpleNamespace(device=device))


def _params(quantize):
    return {"lora": dict(hf.LORA_DEFAULTS, quantize=quantize)}


def test_no_quantize_no_problems():
    assert hf.quantize_problems({"lora": None}, _spec()) == []
    assert hf.quantize_problems(_params(None), _spec()) == []
    assert hf.quantization_kwargs(None) == {}
    assert hf.quantization_kwargs(dict(hf.LORA_DEFAULTS)) == {}


@pytest.mark.parametrize("quantize, device, needle", [
    ("2bit", "auto", "must be one of 4bit, 8bit"),
    ("4bit", "mps", "needs a CUDA GPU; this run's device is mps"),
    ("4bit", "cpu", "needs a CUDA GPU; this run's device is cpu"),
])
def test_refusals_name_the_reason(quantize, device, needle):
    problems = hf.quantize_problems(_params(quantize), _spec(device))
    assert any(needle in p for p in problems), problems


def test_without_bitsandbytes_the_install_hint_is_given(monkeypatch):
    monkeypatch.setattr(hf, "missing", lambda modules: list(modules))
    problems = hf.quantize_problems(_params("4bit"), _spec("cuda"))
    assert problems and "bitsandbytes" in problems[0] and "CUDA only" in problems[0]


@pytest.mark.skipif(torch.cuda.is_available(), reason="a CUDA machine")
def test_a_machine_with_no_gpu_is_refused_before_anything_loads(monkeypatch):
    monkeypatch.setattr(hf, "missing", lambda modules: [])
    problems = hf.quantize_problems(_params("4bit"), _spec("auto"))
    assert problems == ["lora.quantize needs a CUDA GPU, and this machine has "
                        "none: bitsandbytes quantizes on the GPU"]


def test_4bit_is_qloras_nf4_with_double_quantization():
    kwargs = hf.quantization_kwargs(dict(hf.LORA_DEFAULTS, quantize="4bit"))
    config = kwargs["quantization_config"]
    assert config.load_in_4bit and not config.load_in_8bit
    assert config.bnb_4bit_quant_type == "nf4"
    assert config.bnb_4bit_use_double_quant is True
    assert kwargs["device_map"] == {"": 0}


def test_8bit():
    config = hf.quantization_kwargs(
        dict(hf.LORA_DEFAULTS, quantize="8bit"))["quantization_config"]
    assert config.load_in_8bit and not config.load_in_4bit


class _Model:
    def __init__(self, quantized):
        self.is_loaded_in_4bit = quantized
        self.moved_to = None

    def to(self, device):
        if self.is_loaded_in_4bit:
            raise ValueError("`.to` is not supported for 4-bit models")
        self.moved_to = device
        return self


def test_a_quantized_model_is_not_moved():
    model = _Model(True)
    assert hf.place(model, "cuda:0") is model and model.moved_to is None
    wrapped = types.SimpleNamespace(base_model=types.SimpleNamespace(
        model=_Model(True)))
    assert hf.is_quantized(wrapped)
    plain = _Model(False)
    assert hf.place(plain, "cpu").moved_to == "cpu"


def test_a_trainer_that_does_not_load_quantized_says_so():
    with pytest.raises(hf.TrainerError, match="llm-sft, llm-dpo, "
                                              "hf-text-classification, vlm-sft and "
                                              "reward-model"):
        hf.apply_lora(_Model(False), dict(hf.LORA_DEFAULTS, quantize="4bit"),
                      "TOKEN_CLS", None)


def test_llm_sft_refuses_quantize_where_there_is_no_cuda(tmp_path):
    if torch.cuda.is_available():
        pytest.skip("a CUDA machine")
    from potato.training.dataset import build_bundle
    from potato.training.events import EXIT_BAD_SPEC
    from tests.unit.test_training_trainers import _context, _run, _spec as spec_of
    scheme = {"annotation_type": "text", "name": "answer", "description": "?"}
    items = {"i%d" % n: {"id": "i%d" % n, "text": "q %d" % n} for n in range(30)}
    annotations = [{"instance_id": i, "user_id": "u",
                    "labels": {"answer": {"text_box": "a %s" % i}}} for i in items]
    config, context = _context(tmp_path, [scheme], items, annotations)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["answer"])
    spec = spec_of(tmp_path, config, bundle, "llm-sft", "answer",
                   {"lora": {"quantize": "4bit"}, "min_instances": 2})
    code, _, report = _run(spec)
    assert code == EXIT_BAD_SPEC
    assert "lora.quantize needs" in report.of_type("error")[0]["message"]


def test_a_bitsandbytes_without_a_binary_for_this_cuda_is_named():
    """Burger, 2026-11-02: torch 2.11+cu130 with bitsandbytes 0.46.1, which
    ships no CUDA 13.0 binary. Import works; quantizing raises."""
    import sys
    fake_torch = types.SimpleNamespace(
        __version__="2.11.0+cu130", version=types.SimpleNamespace(cuda="13.0"),
        zeros=lambda *a, **k: None, float16="float16")

    def refuse(tensor):
        raise RuntimeError("Configured CUDA binary not found at "
                           "/x/libbitsandbytes_cuda130.so")
    functional = types.SimpleNamespace(quantize_4bit=refuse)
    package = types.SimpleNamespace(__version__="0.46.1", functional=functional)
    saved = {k: sys.modules.get(k) for k in ("bitsandbytes", "bitsandbytes.functional")}
    sys.modules["bitsandbytes"] = package
    sys.modules["bitsandbytes.functional"] = functional
    try:
        problems = hf._bitsandbytes_runs(fake_torch)
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    assert problems == [
        "bitsandbytes 0.46.1 cannot quantize with this torch (2.11.0+cu130, "
        "CUDA 13.0): Configured CUDA binary not found at "
        "/x/libbitsandbytes_cuda130.so. Install a bitsandbytes build for "
        "CUDA 13.0."]
