"""
Solo mode and the AI pipeline, driven through the real SDK clients with HTTP
mocked at the transport (httpx.MockTransport), the real result handler, the
real /solo/annotate route and the real disk cache.

The earlier tests used MagicMock endpoints, which accept any arguments and any
reply, so they could not see that Anthropic's query() took one argument and
OpenAI's took two. They also set the agreement counters by hand rather than
going through the route that is meant to read them, and asserted the cache
key's shape instead of what a changed model or label set should do to it.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import shutil
import time

import httpx
import pytest

from potato.item_state_management import Label
from tests.helpers.test_utils import create_test_directory


# ---------------------------------------------------------------------------
# Mocked providers
# ---------------------------------------------------------------------------

class _Recorder:
    def __init__(self, content='{"label": "positive", "confidence": 90}', status=200):
        self.content = content
        self.status = status
        self.calls = []


def _openai(recorder):
    openai = pytest.importorskip("openai")
    from potato.ai.openai_endpoint import OpenAIEndpoint

    def handler(req):
        body = json.loads(req.content)
        recorder.calls.append(body)
        if recorder.status != 200:
            return httpx.Response(recorder.status, json={
                "error": {"message": "overloaded", "type": "server_error"}})
        return httpx.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": recorder.content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    ep = OpenAIEndpoint({"ai_config": {"model": "gpt-4o-mini", "api_key": "k"}})
    ep.client = openai.OpenAI(api_key="k", max_retries=0,
                              http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return ep


def _anthropic(recorder):
    anthropic = pytest.importorskip("anthropic")
    from potato.ai.anthropic_endpoint import AnthropicEndpoint

    def handler(req):
        recorder.calls.append(json.loads(req.content))
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-x",
            "content": [{"type": "text", "text": recorder.content}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}})

    ep = AnthropicEndpoint({"ai_config": {"model": "claude-x", "api_key": "k"}})
    ep.client = anthropic.Anthropic(api_key="k", max_retries=0,
                                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return ep


def _labeler(schemes):
    from potato.solo_mode.config import parse_solo_mode_config
    from potato.solo_mode.llm_labeler import LLMLabelingThread
    cfg = {"annotation_schemes": schemes, "solo_mode": {"enabled": True, "labeling_models": []}}
    thread = LLMLabelingThread(cfg, parse_solo_mode_config(cfg), lambda: "Label", lambda r: None)
    thread._get_uncertainty_estimator = lambda: None
    return thread


RADIO = [{"name": "s", "annotation_type": "radio", "labels": ["positive", "negative"]}]


# ---------------------------------------------------------------------------
# Every endpoint answers both call shapes
# ---------------------------------------------------------------------------

class TestEndpointCallShapes:
    def test_every_endpoint_takes_an_optional_output_format(self):
        """Callers pass (prompt) or (prompt, Model); each must work everywhere."""
        import importlib
        modules = ["anthropic_endpoint", "openai_endpoint", "huggingface_endpoint",
                   "gemini_endpoint", "ollama_endpoint", "openrouter_endpoint",
                   "vllm_endpoint", "anthropic_vision_endpoint", "openai_vision_endpoint",
                   "ollama_vision_endpoint", "yolo_endpoint", "sam_endpoint", "sam3_endpoint"]
        for name in modules:
            module = importlib.import_module(f"potato.ai.{name}")
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if cls.__module__ != module.__name__ or "query" not in cls.__dict__:
                    continue
                params = list(inspect.signature(cls.query).parameters.values())
                assert len(params) == 3, (cls, params)
                assert params[2].default is None, f"{cls.__name__}.query needs output_format=None"

    def test_anthropic_answers_an_ai_hint(self, monkeypatch):
        import potato.server_utils.config_module as cm
        from potato.ai.ai_endpoint import AnnotationInput
        from potato.ai.ai_prompt import ModelManager, init_ai_prompt
        monkeypatch.setitem(cm.config, "ai_support", {"enabled": True})
        init_ai_prompt({"ai_support": {"enabled": True}})
        rec = _Recorder('```json\n{"hint": "h", "suggestive_choice": "positive"}\n```')
        ep = _anthropic(rec)
        spec = json.load(open("potato/ai/prompt/radio.json"))["hint"]["output_format"]
        result = ep.get_ai(AnnotationInput(ai_assistant="hint", annotation_type="radio",
                                           text="Great!", description="Sentiment",
                                           labels=["positive", "negative"]),
                           ModelManager().get_model_class_by_name(spec))
        assert len(rec.calls) == 1
        assert isinstance(result, dict) and result.get("suggestive_choice") == "positive"

    def test_anthropic_runs_the_solo_labeler(self):
        rec = _Recorder('{"label": "positive", "confidence": 90, "reasoning": "r"}')
        result = _labeler(RADIO)._label_instance("i1", "Great!", "s", endpoint=_anthropic(rec))
        assert result.error is None and result.label == "positive"

    def test_openai_runs_a_one_argument_caller(self):
        from potato.solo_mode.config import parse_solo_mode_config
        from potato.solo_mode.labeling_functions import LabelingFunctionExtractor
        rec = _Recorder(json.dumps([{"pattern_text": "mentions refund", "condition": "refund",
                                     "label": "negative", "keywords": ["refund"]}]))
        cfg = {"annotation_schemes": RADIO, "solo_mode": {"enabled": True, "labeling_models": []}}
        extractor = LabelingFunctionExtractor(cfg, parse_solo_mode_config(cfg))
        extractor._endpoint = _openai(rec)
        preds = [{"instance_id": f"i{k}", "text": f"I want a refund {k}",
                  "predicted_label": "negative", "confidence": 0.99, "reasoning": "r"}
                 for k in range(10)]
        assert len(extractor.extract_from_predictions(preds)) == 1
        assert len(rec.calls) == 1


# ---------------------------------------------------------------------------
# Solo labeller replies
# ---------------------------------------------------------------------------

class TestSoloLabelerReplies:
    @pytest.mark.parametrize("raw,expected", [(0.92, 0.92), (92, 0.92), ("85", 0.85), (1, 1.0)])
    def test_confidence_on_either_scale(self, raw, expected):
        rec = _Recorder(json.dumps({"label": "positive", "confidence": raw}))
        result = _labeler(RADIO)._label_instance("i1", "Great!", "s", endpoint=_openai(rec))
        assert result.confidence == pytest.approx(expected)

    def test_json_after_a_think_block_is_read(self):
        rec = _Recorder('<think>hmm</think>\nSure: {"label": "negative", "confidence": 80}')
        result = _labeler(RADIO)._label_instance("i1", "Awful.", "s", endpoint=_openai(rec))
        assert result.label == "negative"

    def _spans(self, reply, text):
        schemes = [{"name": "ner", "annotation_type": "span", "labels": ["PER", "ORG", "LOC"]}]
        rec = _Recorder(json.dumps({"label": reply, "confidence": 90}))
        result = _labeler(schemes)._label_instance("i1", text, "ner", endpoint=_openai(rec))
        return json.loads(result.label)

    def test_a_span_label_outside_the_schema_is_not_stored(self):
        spans = self._spans([{"text": "Acme", "label": "COMPANY"},
                             {"text": "Paris", "label": "LOC"}], "Acme opened in Paris.")
        assert [(s["text"], s["label"]) for s in spans] == [("Paris", "LOC")]

    def test_a_repeated_name_lands_on_each_occurrence(self):
        text = "Kim met Lee, then Kim left."
        spans = self._spans([{"text": "Kim", "label": "PER"}, {"text": "Kim", "label": "PER"}], text)
        assert [s["start"] for s in spans] == [0, text.rindex("Kim")]


def test_icl_reads_a_fenced_reply():
    import threading
    from potato.ai.icl_labeler import HighConfidenceExample, ICLLabeler
    labeler = ICLLabeler.__new__(ICLLabeler)
    labeler._lock = threading.Lock()
    labeler.predictions, labeler.labeled_instance_ids = {}, set()
    labeler.verification_enabled = False
    labeler.verification_queue = []
    rec = _Recorder('```json\n{"label": "positive", "confidence": 85}\n```')
    endpoint = _openai(rec)
    labeler._get_ai_endpoint = lambda: endpoint
    labeler._get_annotation_schemes = lambda: [
        {"name": "s", "annotation_type": "radio", "labels": ["positive", "negative"]}]
    labeler.get_examples_for_schema = lambda name: [
        HighConfidenceExample(instance_id="e1", text="Lovely.", schema_name="s",
                              label="positive", agreement_score=1.0, annotator_count=3)]
    prediction = labeler.label_instance("i1", "s", "Great!")
    assert len(rec.calls) == 1
    assert prediction is not None and prediction.predicted_label == "positive"
    assert prediction.confidence_score == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# Solo agreement gate and bookkeeping
# ---------------------------------------------------------------------------

def _manager(state_dir=None, **thresholds):
    from potato.solo_mode.config import parse_solo_mode_config
    from potato.solo_mode.manager import SoloModeManager
    solo = {"enabled": True, "labeling_models": []}
    if thresholds:
        solo["thresholds"] = thresholds
    if state_dir:
        solo["state_dir"] = state_dir
    cfg = {"annotation_schemes": [{"name": "sentiment", "annotation_type": "radio",
                                   "labels": ["positive", "negative"]}],
           "solo_mode": solo, "item_properties": {"id_key": "id", "text_key": "text"}}
    manager = SoloModeManager(parse_solo_mode_config(cfg), cfg)
    if not state_dir:
        manager._save_state = lambda *a, **k: None
    return manager, cfg


class TestSoloGate:
    def test_the_gate_hands_over_while_the_human_still_has_items(self):
        from flask import Flask
        import potato.solo_mode.manager as M
        from potato.item_state_management import clear_item_state_manager, init_item_state_manager
        from potato.solo_mode.phase_controller import SoloPhase
        from potato.solo_mode.routes import solo_mode_bp

        clear_item_state_manager()
        M.clear_solo_mode_manager()
        cfg = {"annotation_schemes": [{"name": "sentiment", "annotation_type": "radio",
                                       "labels": ["positive", "negative"]}],
               "solo_mode": {"enabled": True,
                             "labeling_models": [{"provider": "openai", "model": "gpt-x",
                                                  "api_key": "k"}],
                             "thresholds": {"end_human_annotation_agreement": 0.9,
                                            "minimum_validation_sample": 5}},
               "item_properties": {"id_key": "id", "text_key": "text"}}
        ism = init_item_state_manager(cfg)
        ism.add_items({f"i{n}": {"id": f"i{n}", "text": f"text {n}"} for n in range(50)})
        manager = M.init_solo_mode_manager(cfg)
        manager.start_background_labeling = lambda *a, **k: False
        manager.create_prompt_version("p", "user")
        manager.phase_controller.transition_to(SoloPhase.PARALLEL_ANNOTATION, force=True)
        for n in range(50):
            manager.set_llm_prediction(f"i{n}", "sentiment", M.LLMPrediction(
                instance_id=f"i{n}", schema_name="sentiment", predicted_label="positive",
                confidence_score=0.95, uncertainty_score=0.05, prompt_version=1, model_name="m"))
        app = Flask(__name__, template_folder=os.path.abspath("potato/templates"))
        app.secret_key = "x"
        app.add_url_rule("/login", "login", lambda: "login")
        app.register_blueprint(solo_mode_bp)
        client = app.test_client()
        with client.session_transaction() as s:
            s["username"] = "u"
        try:
            for _ in range(6):
                iid = manager.get_next_instance_for_human("u")
                client.post("/solo/annotate", data={"instance_id": iid, "annotation": "positive"})
            assert manager.get_current_phase() == SoloPhase.AUTONOMOUS_LABELING
            assert client.get("/solo/annotate").status_code == 302
        finally:
            M.clear_solo_mode_manager()
            clear_item_state_manager()

    def test_a_reannotated_item_is_one_comparison(self):
        from potato.solo_mode.llm_labeler import LabelingResult
        manager, _ = _manager()
        manager.create_prompt_version("p1", "user")
        v1 = manager.current_prompt_version
        manager._handle_labeling_result(LabelingResult("i1", "sentiment", "positive", 0.3, 0.7, "", v1, "m"))
        manager.record_human_label("i1", "sentiment", "negative", "u")
        manager.create_prompt_version("p2", "llm")
        assert manager._trigger_reannotation(v1) == 1
        v2 = manager.current_prompt_version
        manager._handle_labeling_result(LabelingResult("i1", "sentiment", "negative", 0.9, 0.1, "", v2, "m"))
        manager.record_human_label("i1", "sentiment", "negative", "u")
        metrics = manager.agreement_metrics
        assert (metrics.total_compared, metrics.agreements, metrics.disagreements) == (1, 1, 0)
        assert "i1" not in manager.disagreement_ids

    def test_a_restart_in_autonomous_labelling_resumes_the_loop(self):
        from potato.solo_mode.phase_controller import SoloPhase
        state = create_test_directory("tg2_solo_restart")
        shutil.rmtree(state, ignore_errors=True)
        first, _ = _manager(state_dir=state)
        first.start_background_labeling = lambda: True
        first.create_prompt_version("p", "user")
        first.phase_controller.transition_to(SoloPhase.AUTONOMOUS_LABELING, force=True)
        first._save_state()
        started = []
        second, _ = _manager(state_dir=state)
        second.start_background_labeling = lambda: started.append(True) or True
        second.load_state()
        assert second.get_current_phase() == SoloPhase.AUTONOMOUS_LABELING
        assert started == [True]

    def test_a_labeling_function_label_is_compared_with_the_human(self):
        from types import SimpleNamespace
        manager, _ = _manager()
        manager.config.labeling_functions.enabled = True
        manager.human_labeled_ids.add("i1")
        manager._get_stored_human_label = lambda iid, schema: "negative"
        manager._get_instances_for_labeling = lambda n: [
            {"instance_id": "i1", "text": "t", "schema_name": "sentiment"}]
        manager.labeling_function_manager.apply_batch = lambda insts: (
            [SimpleNamespace(instance_id="i1", label="positive", vote_agreement=1.0,
                             votes=[1])], [])
        manager.config.confidence_routing.enabled = False
        manager._label_batch(1)
        assert manager.agreement_metrics.total_compared == 1
        assert "i1" in manager.disagreement_ids


# ---------------------------------------------------------------------------
# AI suggestion cache
# ---------------------------------------------------------------------------

SENT = {"name": "sentiment", "annotation_type": "radio", "description": "Sentiment?",
        "labels": ["positive", "negative"]}
TOPIC = {"name": "topic", "annotation_type": "radio", "description": "Topic?",
         "labels": ["food", "service"]}


@pytest.fixture
def cache_env():
    openai = pytest.importorskip("openai")
    import potato.ai.ai_cache as AC
    import potato.server_utils.config_module as cm
    from potato.ai.ai_prompt import init_ai_prompt
    from potato.item_state_management import clear_item_state_manager, init_item_state_manager

    task = create_test_directory("tg2_ai_cache")
    shutil.rmtree(task, ignore_errors=True)
    os.makedirs(task)
    saved = dict(cm.config)
    rec = _Recorder()
    rec.choice = "positive"

    def handler(req):
        body = json.loads(req.content)
        rec.calls.append(body["model"])
        if rec.status != 200:
            return httpx.Response(rec.status, json={"error": {"message": "x", "type": "server_error"}})
        content = json.dumps({"hint": "Upbeat.", "suggestive_choice": rec.choice})
        return httpx.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    def boot(model, schemes):
        cm.config.clear()
        cm.config.update({
            "task_dir": task, "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": schemes,
            "ai_support": {"enabled": True, "endpoint_type": "openai",
                           "ai_config": {"model": model, "api_key": "k"},
                           "cache_config": {"disk_cache": {"enabled": True,
                                                           "path": os.path.join(task, "c.json")},
                                            "prefetch": {}}}})
        init_ai_prompt(cm.config)
        clear_item_state_manager()
        init_item_state_manager(cm.config).add_items({"r1": {"id": "r1", "text": "Great food."}})
        AC.clear_ai_cache_manager()
        manager = AC.init_ai_cache_manager()
        manager.ai_endpoint.client = openai.OpenAI(
            api_key="k", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        return manager

    yield boot, rec
    AC.clear_ai_cache_manager()
    clear_item_state_manager()
    cm.config.clear()
    cm.config.update(saved)


class TestAiCache:
    def test_a_new_model_is_asked_again(self, cache_env):
        boot, rec = cache_env
        boot("gpt-4o-mini", [SENT]).get_ai_help("r1", 0, "hint")
        rec.calls.clear()
        boot("gpt-5", [SENT]).get_ai_help("r1", 0, "hint")
        assert rec.calls == ["gpt-5"]

    def test_changed_labels_are_asked_again(self, cache_env):
        boot, rec = cache_env
        boot("gpt-5", [SENT]).get_ai_help("r1", 0, "hint")
        rec.calls.clear()
        rec.choice = "4"
        result = boot("gpt-5", [{**SENT, "labels": ["1", "2", "3", "4", "5"]}]).get_ai_help("r1", 0, "hint")
        assert rec.calls == ["gpt-5"]
        assert result["suggestive_choice"] == "4"

    def test_a_scheme_inserted_ahead_does_not_inherit_a_suggestion(self, cache_env):
        boot, rec = cache_env
        boot("gpt-5", [SENT]).get_ai_help("r1", 0, "hint")
        rec.calls.clear()
        rec.choice = "food"
        result = boot("gpt-5", [TOPIC, SENT]).get_ai_help("r1", 0, "hint")
        assert result["suggestive_choice"] == "food"

    def test_a_prefetch_failure_is_not_cached(self, cache_env):
        boot, rec = cache_env
        manager = boot("gpt-5", [SENT])
        rec.status = 503
        manager.prefetch([("r1", 0, "hint")])
        deadline = time.time() + 10
        while manager.in_progress and time.time() < deadline:
            time.sleep(0.05)
        rec.status = 200
        result = manager.get_ai_help("r1", 0, "hint")
        assert isinstance(result, dict) and result.get("suggestive_choice") == "positive"


# ---------------------------------------------------------------------------
# MACE
# ---------------------------------------------------------------------------

def test_mace_reads_an_answer_of_zero():
    from potato.mace_manager import MACEManager
    from potato.phase import UserPhase
    from potato.user_state_management import clear_user_state_manager, init_user_state_manager
    out = create_test_directory("tg2_mace_zero")
    cfg = {"annotation_schemes": [{"name": "toxic", "annotation_type": "radio", "labels": ["0", "1"]}],
           "mace": {"enabled": True, "min_annotations_per_item": 3, "min_items": 5,
                    "cache_results": False},
           "output_annotation_dir": out, "user_config": {}}
    clear_user_state_manager()
    try:
        usm = init_user_state_manager(cfg)
        truth = ["0", "1"] * 5
        for user in "abc":
            state = usm.add_user(user)
            state.advance_to_phase(UserPhase.ANNOTATION, None)
            for i, value in enumerate(truth):
                state.add_label_annotation(f"i{i}", Label("toxic", value), value)
        manager = MACEManager(cfg)
        stored = usm.get_user_state("a").get_label_annotations("i0")
        assert manager._extract_annotation(stored, "toxic", "radio") == "0"
        result = manager._run_for_schema(usm, None, "toxic", "radio")
        assert result is not None and result.num_instances == 10
        assert result.predicted_labels["i0"] == "0"
    finally:
        clear_user_state_manager()
