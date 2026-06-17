"""Unit test for the judge_calibration generation thread (mocked endpoint)."""

import threading
from potato.judge_calibration.config import parse_judge_calibration_config
from potato.judge_calibration.generation import LLMGenerationThread, _SingleLabel
from potato.judge_calibration.storage import ResultStore


class ScriptedEndpoint:
    """Returns a deterministic cycle of labels so vote fractions are testable."""
    def __init__(self, sequence):
        self.sequence = sequence
        self.i = 0
        self._lock = threading.Lock()

    def parseStringToJson(self, s):
        return s

    def query(self, prompt, output_format):
        with self._lock:
            label = self.sequence[self.i % len(self.sequence)]
            self.i += 1
        return _SingleLabel(label=label)


SCHEMA = {
    "name": "sentiment",
    "annotation_type": "radio",
    "description": "Sentiment",
    "labels": ["positive", "negative"],
}


def _make_config():
    return parse_judge_calibration_config({
        "judge_calibration": {
            "enabled": True,
            "k_samples": 4,
            "models": [{"endpoint_type": "ollama", "model": "fake", "temperature": 0.7}],
        },
        "output_annotation_dir": "ao",
    })


def test_generation_end_to_end(monkeypatch):
    cfg = _make_config()
    # 3 of 4 draws are "positive" -> modal positive, confidence 0.75
    endpoint = ScriptedEndpoint(["positive", "positive", "positive", "negative"])
    monkeypatch.setattr(
        "potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint",
        lambda config: endpoint,
    )

    store = ResultStore(state_dir=None)
    work = [("i1", "great"), ("i2", "awful")]
    done = threading.Event()

    thread = LLMGenerationThread(
        config=cfg, work_items=work, schema_infos=[SCHEMA],
        result_store=store, on_complete=done.set,
    )
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert thread.error is None
    assert done.is_set()

    assert store.count() == 2
    r = store.get("fake", "i1", "sentiment")
    assert r is not None
    assert r.modal_label == "positive"
    assert r.confidence == 0.75
    assert r.k == 4
    assert len(r.samples) == 4


def test_generation_resume_skips_existing(monkeypatch):
    cfg = _make_config()
    endpoint = ScriptedEndpoint(["positive"])
    monkeypatch.setattr(
        "potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint",
        lambda config: endpoint,
    )
    store = ResultStore(state_dir=None)
    # Pre-seed i1 as already done.
    from potato.judge_calibration.aggregation import aggregate
    store.upsert(aggregate("fake", "i1", "sentiment", "radio", ["negative"] * 4, 4), save=False)

    thread = LLMGenerationThread(
        config=cfg, work_items=[("i1", "x"), ("i2", "y")],
        schema_infos=[SCHEMA], result_store=store,
    )
    thread.start()
    thread.join(timeout=10)

    # i1 untouched (still the pre-seeded negative), i2 newly generated.
    assert store.get("fake", "i1", "sentiment").modal_label == "negative"
    assert store.get("fake", "i2", "sentiment").modal_label == "positive"
