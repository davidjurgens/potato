"""
The call pipeline and the runner: every prediction cites logged calls, runs
resume without paying twice, budgets refuse before spending, redaction never
stores what it masked, and measured usage is marked as measured.
"""

import json
import threading

import pytest

from potato.ai.ai_endpoint import BaseAIEndpoint
from potato.labeling_engine.config import parse_engine_config
from potato.labeling_engine.items import ItemView
from potato.labeling_engine.runtime import Runner, RunContext
from potato.labeling_engine.schemes import SchemeSpec, normalize_label
from potato.labeling_engine.sources import build_source
from potato.labeling_engine.store import EngineStore
from potato.persistence import clear_db_cache

SCHEME = {"name": "sentiment", "annotation_type": "radio",
          "description": "Is the review positive or negative?",
          "labels": ["positive", "negative"]}


class FakeEndpoint(BaseAIEndpoint):
    """A real BaseAIEndpoint subclass, so query_with_usage is the real one."""

    def __init__(self, replies=None, usage=None, fail_on=None):
        self.replies = replies or (lambda prompt: {"label": "positive", "confidence": 90})
        self.usage = usage
        self.fail_on = fail_on or (lambda prompt: False)
        self.prompts = []
        self.model = "fake-model"
        self._lock = threading.Lock()

    def _initialize_client(self):
        pass

    def _get_default_model(self):
        return "fake-model"

    def query(self, prompt, output_format=None):
        with self._lock:
            self.prompts.append(prompt)
        if self.fail_on(prompt):
            raise RuntimeError("boom")
        if self.usage:
            self._note_usage(*self.usage)
        return self.replies(prompt)


@pytest.fixture
def store(tmp_path):
    clear_db_cache()
    yield EngineStore(str(tmp_path))
    clear_db_cache()


def _app(tmp_path, **extra):
    return {"task_dir": str(tmp_path), "annotation_task_name": f"t-{tmp_path.name}",
            "annotation_schemes": [SCHEME], **extra}


def _engine(app, sources, **block):
    return parse_engine_config({**app, "labeling_engine": {
        "enabled": True, "sources": sources, **block}})


def _items(n, prefix="i", text=None):
    return [ItemView(f"{prefix}{k}", text or f"review number {k}",
                     data={"gold": "positive" if k % 2 else "negative"})
            for k in range(n)]


def _llm(app, engine, endpoint, monkeypatch, source_id="gemma"):
    src = build_source(engine.source(source_id), app, engine)
    monkeypatch.setattr(src, "_endpoint", lambda temperature=None: endpoint)
    return src


SCHEMESPEC = SchemeSpec.from_scheme(SCHEME)
LLM_SRC = {"id": "gemma", "kind": "llm", "endpoint_type": "openai", "model": "fake-model"}


class TestLabels:

    @pytest.mark.parametrize("raw,want", [
        ("positive", "positive"), (" Positive ", "positive"), ('"NEGATIVE"', "negative"),
        ("positive.", "positive"), ("neutral", None), (None, None), (["positive"], None),
    ])
    def test_normalize(self, raw, want):
        assert normalize_label(raw, ["positive", "negative"]) == want


class TestFixtureRun:

    def test_predictions_cite_calls_that_exist(self, store, tmp_path):
        app = _app(tmp_path)
        eng = _engine(app, [{"id": "fx", "kind": "fixture", "error_rate": 0.2}])
        src = build_source(eng.source("fx"), app, eng)
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(50))
        assert s.status == "done" and s.n_predicted == 50
        call_ids = {c.id for c in store.calls(limit=1000)}
        preds = store.current_predictions("sentiment", s.source_version_id)
        assert len(preds) == 50
        for p in preds.values():
            assert p.call_ids and set(p.call_ids) <= call_ids
            assert p.run_id == s.run_id

    def test_error_rate_is_what_was_asked_for(self, store, tmp_path):
        app = _app(tmp_path)
        eng = _engine(app, [{"id": "fx", "kind": "fixture", "error_rate": 0.3}])
        src = build_source(eng.source("fx"), app, eng)
        items = _items(4000)
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, items)
        preds = store.current_predictions("sentiment", s.source_version_id)
        wrong = sum(preds[i.item_id].value != i.data["gold"] for i in items)
        assert 0.27 < wrong / len(items) < 0.33

    def test_rerun_skips_everything(self, store, tmp_path):
        app = _app(tmp_path)
        eng = _engine(app, [{"id": "fx", "kind": "fixture"}])
        src = build_source(eng.source("fx"), app, eng)
        runner = Runner(store, app, eng)
        runner.predict(src, SCHEMESPEC, _items(10))
        again = runner.predict(src, SCHEMESPEC, _items(10))
        assert again.n_skipped == 10 and again.n_predicted == 0
        assert store.prediction_count() == 10


class TestResumeAfterACrash:

    def test_resume_pays_only_once_per_item(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC], runtime={"batch_size": 5, "concurrency": 1})
        crash = {"on": True}
        ep = FakeEndpoint(fail_on=lambda p: False)
        src = _llm(app, eng, ep, monkeypatch)
        real = src._verbalized

        def flaky(item, scheme, ctx, sv):
            # Item 7 kills the process half-way through the second chunk,
            # after items 5 and 6 of that chunk have been called.
            if crash["on"] and item.item_id == "i7":
                raise KeyboardInterrupt
            return real(item, scheme, ctx, sv)
        monkeypatch.setattr(src, "_verbalized", flaky)

        runner = Runner(store, app, eng)
        with pytest.raises(KeyboardInterrupt):
            runner.predict(src, SCHEMESPEC, _items(12))
        assert store.prediction_count() == 5  # only the first chunk committed
        crash["on"] = False
        s = runner.predict(src, SCHEMESPEC, _items(12))
        assert s.status == "done" and store.prediction_count() == 12
        paid = [c for c in store.calls(limit=1000) if not c.cache_hit]
        assert sorted(c.input_hash for c in paid) == sorted({c.input_hash for c in paid})
        assert len(paid) == 12
        assert len(ep.prompts) == 12

    def test_cancel_stops_at_the_next_chunk(self, store, tmp_path):
        app = _app(tmp_path)
        eng = _engine(app, [{"id": "fx", "kind": "fixture"}], runtime={"batch_size": 5})
        src = build_source(eng.source("fx"), app, eng)
        runner = Runner(store, app, eng)
        real = src.predict_batch

        def cancel_after_first(items, scheme, ctx, sv):
            out = real(items, scheme, ctx, sv)
            runner.cancel(ctx.run_id)
            return out
        src.predict_batch = cancel_after_first
        s = runner.predict(src, SCHEMESPEC, _items(20))
        assert s.status == "cancelled" and s.n_predicted == 5
        assert store.get_run(s.run_id).status == "cancelled"


class TestBudgets:

    PRICES = {"fake-model": [1_000_000.0, 0.0]}  # $1 per input token

    def test_model_budget_refuses_before_sending(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path, ai_budget={"prices": self.PRICES})
        eng = _engine(app, [LLM_SRC], budgets={"model_usd": 100},
                      runtime={"batch_size": 50, "concurrency": 1})
        ep = FakeEndpoint(usage=(10, 1))
        src = _llm(app, eng, ep, monkeypatch)
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(30))
        assert s.status == "paused" and "budgets.model_usd" in s.message
        spent = store.get_budget("model_usd").spent
        assert spent <= 100 + 1e-9
        # Each call is refused when its *projected* cost (from the prompt
        # length, before the provider reports usage) would cross the budget,
        # so the run stops short of the last affordable measured call rather
        # than past it.
        ctx = RunContext(store, app, eng)
        projected = ctx._projected_cost(ep.prompts[0], "fake-model", "openai", 256)
        assert spent + projected > 100
        assert spent == pytest.approx(10 * len(ep.prompts))
        assert 0 < len(ep.prompts) < 30

    def test_project_cap_pauses_before_a_chunk(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path, ai_budget={"prices": self.PRICES, "cap_usd": 1.0})
        eng = _engine(app, [LLM_SRC])
        ep = FakeEndpoint()
        src = _llm(app, eng, ep, monkeypatch)
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3))
        assert s.status == "paused" and "cap" in s.message
        assert ep.prompts == []

    def test_spend_reaches_the_project_ledger(self, store, tmp_path, monkeypatch):
        from potato.ai import cost
        app = _app(tmp_path, ai_budget={"prices": {"fake-model": [1.0, 2.0]}})
        eng = _engine(app, [LLM_SRC])
        src = _llm(app, eng, FakeEndpoint(usage=(1000, 10)), monkeypatch)
        Runner(store, app, eng).predict(src, SCHEMESPEC, _items(4))
        total = cost.total_spend(app)
        assert total["cost_usd"] == pytest.approx(4 * (1000 * 1 + 10 * 2) / 1e6)
        assert all(r["estimated"] is False or r["estimated"] == 0 for r in total["runs"])


class TestUsageAndCache:

    def test_measured_usage_is_not_marked_estimated(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        src = _llm(app, eng, FakeEndpoint(usage=(42, 7)), monkeypatch)
        Runner(store, app, eng).predict(src, SCHEMESPEC, _items(1))
        [c] = store.calls()
        assert (c.input_tokens, c.output_tokens, c.estimated) == (42, 7, False)

    def test_unreported_usage_is_estimated(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        src = _llm(app, eng, FakeEndpoint(), monkeypatch)
        Runner(store, app, eng).predict(src, SCHEMESPEC, _items(1))
        assert store.calls()[0].estimated is True

    def test_cache_serves_a_new_run_of_the_same_version(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        ep = FakeEndpoint()
        src = _llm(app, eng, ep, monkeypatch)
        Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3))
        Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3), resume=False)
        assert len(ep.prompts) == 3
        assert sum(c.cache_hit for c in store.calls(limit=100)) == 3

    def test_changed_prompt_is_a_new_version_and_misses_the_cache(
            self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        ep = FakeEndpoint()
        a = _llm(app, _engine(app, [LLM_SRC]), ep, monkeypatch)
        b_cfg = dict(LLM_SRC, prompt="Sentiment of: {text}\nLabels: {labels}")
        b = _llm(app, _engine(app, [b_cfg]), ep, monkeypatch)
        assert a.version(SCHEMESPEC).version_id != b.version(SCHEMESPEC).version_id
        Runner(store, app).predict(a, SCHEMESPEC, _items(2))
        Runner(store, app).predict(b, SCHEMESPEC, _items(2))
        assert len(ep.prompts) == 4


class TestRedaction:

    TEXT = "Loved it! Write to jane.doe@example.com or call 555-123-4567."

    def test_remote_prompts_are_masked_and_the_mask_is_not_stored(
            self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC], features={"pii_redaction": True})
        ep = FakeEndpoint()
        src = _llm(app, eng, ep, monkeypatch)
        Runner(store, app, eng).predict(src, SCHEMESPEC, _items(1, text=self.TEXT))
        assert "jane.doe@example.com" not in ep.prompts[0]
        assert "[EMAIL]" in ep.prompts[0] and "[PHONE]" in ep.prompts[0]
        [c] = store.calls()
        assert c.redaction["categories"] == {"email": 1, "phone": 1}
        raw = open(tmp_path / "engine.sqlite", "rb").read()
        assert b"jane.doe" not in raw and b"555-123" not in raw

    def test_local_endpoints_are_not_masked(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        local = dict(LLM_SRC, endpoint_type="vllm", base_url="http://burger:8001/v1")
        eng = _engine(app, [local], features={"pii_redaction": True})
        ep = FakeEndpoint()
        src = _llm(app, eng, ep, monkeypatch)
        Runner(store, app, eng).predict(src, SCHEMESPEC, _items(1, text=self.TEXT))
        assert "jane.doe@example.com" in ep.prompts[0]
        assert store.calls()[0].redaction is None

    def test_redaction_off_by_default(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        ep = FakeEndpoint()
        Runner(store, app, eng).predict(_llm(app, eng, ep, monkeypatch), SCHEMESPEC,
                                        _items(1, text=self.TEXT))
        assert "jane.doe@example.com" in ep.prompts[0]

    def test_payload_capture_keeps_full_text_outside_the_db(
            self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC], features={"payload_capture": True})
        Runner(store, app, eng).predict(_llm(app, eng, FakeEndpoint(), monkeypatch),
                                        SCHEMESPEC, _items(1, text="hello payload"))
        [c] = store.calls()
        path, _, h = c.payload_ref.partition("#")
        lines = [json.loads(x) for x in open(tmp_path / path)]
        assert lines[0]["input_hash"] == h and "hello payload" in lines[0]["prompt"]


class TestLLMSource:

    def test_verbalized_label_confidence_and_abstain(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        replies = {"i0": {"label": "Negative", "confidence": 0.8},
                   "i1": {"label": "neutral", "confidence": 99},
                   "i2": '```json\n{"label": "positive", "confidence": 70}\n```'}

        def reply(prompt):
            for k, v in replies.items():
                if f"review number {k[1:]}" in prompt:
                    return v
        src = _llm(app, eng, FakeEndpoint(replies=reply), monkeypatch)
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3))
        p = store.current_predictions("sentiment", s.source_version_id)
        assert (p["i0"].value, p["i0"].raw_conf) == ("negative", 0.8)
        assert p["i1"].status == "abstain" and p["i1"].value is None
        assert (p["i2"].value, p["i2"].raw_conf) == ("positive", 0.7)

    def test_failed_call_is_an_error_prediction(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        src = _llm(app, eng, FakeEndpoint(fail_on=lambda p: True), monkeypatch)
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(2))
        assert s.n_error == 2
        assert all(c.error for c in store.calls())

    def test_k_sample_votes(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        cfg = dict(LLM_SRC, confidence={"method": "k_sample", "samples": 4})
        eng = _engine(app, [cfg])
        n = {"k": 0}
        lock = threading.Lock()

        def reply(prompt):
            with lock:
                n["k"] += 1
                k = n["k"]
            return {"label": "negative" if k % 4 == 0 else "positive", "confidence": 50}
        src = _llm(app, eng, FakeEndpoint(replies=reply), monkeypatch)
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(1))
        [p] = store.current_predictions("sentiment", s.source_version_id).values()
        assert p.value == "positive" and p.raw_conf == 0.75
        assert p.conf == {"positive": 0.75, "negative": 0.25} and len(p.call_ids) == 4

    def test_logprob_distribution(self, store, tmp_path, monkeypatch):
        import math
        app = _app(tmp_path)
        cfg = dict(LLM_SRC, endpoint_type="vllm", confidence={"method": "logprob"})
        eng = _engine(app, [cfg])
        src = _llm(app, eng, FakeEndpoint(), monkeypatch)
        monkeypatch.setattr(src, "_letter_logprobs", lambda p, n: (
            {"A": math.log(0.6), "B": math.log(0.2)}, {"input_tokens": 50,
                                                      "output_tokens": 1}))
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(1))
        [p] = store.current_predictions("sentiment", s.source_version_id).values()
        assert p.value == "positive" and p.raw_conf == pytest.approx(0.75)
        assert store.calls()[0].estimated is False

    def test_logprob_needs_a_logprob_endpoint(self, tmp_path):
        app = _app(tmp_path)
        cfg = dict(LLM_SRC, endpoint_type="anthropic", confidence={"method": "logprob"})
        eng = _engine(app, [cfg])
        src = build_source(eng.source("gemma"), app, eng)
        assert not src.supports(SCHEMESPEC)
        assert "logprob" in src.unsupported_reason(SCHEMESPEC)

    def test_bad_template_says_how_to_fix_it(self, tmp_path):
        from potato.labeling_engine.sources import SourceError
        app = _app(tmp_path)
        eng = _engine(app, [dict(LLM_SRC, prompt='Reply {"label": x} for {text}')])
        src = build_source(eng.source("gemma"), app, eng)
        with pytest.raises(SourceError, match="literal braces"):
            src.build_prompt(SCHEMESPEC, "x")

    def test_unsupported_scheme_is_refused(self, store, tmp_path):
        from potato.labeling_engine.sources import SourceError
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        src = build_source(eng.source("gemma"), app, eng)
        span = SchemeSpec.from_scheme({"name": "ner", "annotation_type": "span",
                                       "labels": ["PER", "ORG"]})
        with pytest.raises(SourceError):
            Runner(store, app, eng).predict(src, span, _items(1))


class TestDecisionSource:

    def test_probabilities_become_confidence(self, store, tmp_path, monkeypatch):
        from potato.ai.decision_endpoint import DecisionAnswer
        app = _app(tmp_path)
        eng = _engine(app, [{"id": "laya", "kind": "decision", "endpoint_type": "laya",
                             "model": "convaiinnovations/laya"}])
        src = build_source(eng.source("laya"), app, eng)

        class FakeDecision:
            is_decision_model = True

            def decide(self, text, questions):
                return [DecisionAnswer(id="sentiment", value="negative", confidence=0.85,
                                       probabilities={"negative": 0.85, "positive": 0.15})]
        monkeypatch.setattr(src, "_endpoint", lambda: FakeDecision())
        s = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(2))
        p = store.current_predictions("sentiment", s.source_version_id)["i0"]
        assert p.value == "negative" and p.raw_conf == 0.85
        assert p.conf == {"negative": 0.85, "positive": 0.15}
        assert store.calls()[0].output_tokens == 0

    def test_multiselect_is_not_a_decision_scheme(self, tmp_path):
        app = _app(tmp_path)
        eng = _engine(app, [{"id": "laya", "kind": "decision", "endpoint_type": "laya"}])
        src = build_source(eng.source("laya"), app, eng)
        ms = SchemeSpec.from_scheme({"name": "t", "annotation_type": "multiselect",
                                     "labels": ["a", "b"]})
        assert not src.supports(ms)


def test_parallel_keeps_input_order(store, tmp_path):
    ctx = RunContext(store, _app(tmp_path))
    import random
    import time as _t

    def slow(x):
        _t.sleep(random.random() / 200)
        return x * 2
    assert ctx.parallel(list(range(40)), slow, concurrency=8) == [x * 2 for x in range(40)]


class TestRetries:

    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        import potato.labeling_engine.runtime.calls as calls
        monkeypatch.setattr(calls.time, "sleep", lambda s: None)

    def test_transient_failure_is_retried_and_each_attempt_logged(
            self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        n = {"k": 0}

        class Flaky(FakeEndpoint):
            def query(self, prompt, output_format=None):
                n["k"] += 1
                if n["k"] < 3:
                    raise TimeoutError("Read timed out")
                return {"label": "positive", "confidence": 80}
        s = Runner(store, app, eng).predict(_llm(app, eng, Flaky(), monkeypatch),
                                            SCHEMESPEC, _items(1))
        assert s.n_ok == 1
        calls = store.calls()
        assert len(calls) == 3 and [bool(c.error) for c in reversed(calls)] == [
            True, True, False]

    def test_a_bad_request_is_not_retried(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC])
        ep = FakeEndpoint(fail_on=lambda p: True)  # RuntimeError("boom")
        Runner(store, app, eng).predict(_llm(app, eng, ep, monkeypatch), SCHEMESPEC,
                                        _items(1))
        assert len(store.calls()) == 1

    def test_an_item_that_keeps_failing_is_not_asked_forever(self, store, tmp_path,
                                                             monkeypatch):
        """Found by potato-skill (H4): a wrong key or a dead server was a paid
        call per item on every planner pass. (An off-list answer is an
        abstention, which is an answer and is not asked again.)"""
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC], runtime={"retries": 0})
        ep = FakeEndpoint(fail_on=lambda p: True)
        src = _llm(app, eng, ep, monkeypatch)
        for _ in range(5):
            Runner(store, app, eng).predict(src, SCHEMESPEC, _items(2))
        assert len(ep.prompts) == 2 * store.MAX_ERROR_ATTEMPTS

    def test_errored_items_are_retried_by_the_next_run(self, store, tmp_path, monkeypatch):
        app = _app(tmp_path)
        eng = _engine(app, [LLM_SRC], runtime={"retries": 0})
        down = {"on": True}
        ep = FakeEndpoint(fail_on=lambda p: down["on"])
        src = _llm(app, eng, ep, monkeypatch)
        first = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3))
        assert first.n_error == 3
        down["on"] = False
        second = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3))
        assert second.n_skipped == 0 and second.n_ok == 3
        third = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3))
        assert third.n_skipped == 3


def test_loopback_endpoint_without_a_price_costs_nothing(tmp_path):
    """A self-hosted model behind localhost (an OpenJev server through an SSH
    tunnel) is free per call; logging it as unpriced made the spend a lower
    bound for no reason. A remote host with no price stays unpriced."""
    from potato.labeling_engine.runtime.calls import RunContext
    from potato.labeling_engine.store import EngineStore
    from potato.persistence import clear_db_cache
    clear_db_cache()
    ctx = RunContext(EngineStore(str(tmp_path)), {"task_dir": str(tmp_path)}, None)
    local = ctx._actual_cost("hi", "wev-8b", "systemone", 0, None, False,
                             base_url="http://127.0.0.1:18009")
    remote = ctx._actual_cost("hi", "wev-8b", "systemone", 0, None, False,
                              base_url="https://api.example.com")
    assert local[0] == 0.0
    assert remote[0] is None
    clear_db_cache()


def test_the_judge_endpoint_is_built_once_and_shared_by_every_thread(monkeypatch):
    """Found by potato-skill (D3): with concurrency 4, five of six step
    verdicts were silent abstains, because the endpoint was marked built
    before it existed and the other threads got None."""
    import time as _t
    from concurrent.futures import ThreadPoolExecutor
    from potato.ai import ai_endpoint
    from potato.ai.judge import JudgeService
    built = []

    def slow_create(cfg):
        _t.sleep(0.05)
        built.append(1)
        return object()
    monkeypatch.setattr(ai_endpoint.AIEndpointFactory, "create_endpoint",
                        staticmethod(slow_create))
    svc = JudgeService({"judge_alignment": {"ai_support": {"enabled": True,
                                                           "endpoint_type": "openai"}}})
    with ThreadPoolExecutor(6) as ex:
        got = list(ex.map(lambda _: svc._get_endpoint(), range(6)))
    assert all(g is not None for g in got) and len(set(map(id, got))) == 1
    assert len(built) == 1


def test_a_one_run_budget_override_does_not_bind_later_runs(tmp_path):
    """Found by potato-skill (B10): --budget-usd stayed in the budget table."""
    from potato.labeling_engine.config import parse_engine_config
    from potato.labeling_engine.service import Engine
    clear_db_cache()
    app = _app(tmp_path)
    block = {"enabled": True, "sources": [{"id": "fx", "kind": "fixture"}]}
    cfg = parse_engine_config({**app, "labeling_engine": block})
    cfg.budgets["model_usd"] = 0.5                     # what --budget-usd does
    Engine({**app, "labeling_engine": block}, engine_cfg=cfg)
    later = Engine({**app, "labeling_engine": block})
    assert later.store.get_budget("model_usd").limit is None
    clear_db_cache()


def test_an_idle_pass_writes_no_run_rows(store, tmp_path):
    """Found by potato-skill (cosmetic): two empty run rows per idle tick."""
    app = _app(tmp_path)
    eng = _engine(app, [{"id": "fx", "kind": "fixture"}])
    src = build_source(eng.source("fx"), app, eng)
    Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3))
    n = store.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
    again = Runner(store, app, eng).predict(src, SCHEMESPEC, _items(3))
    assert again.status == "done" and again.n_skipped == 3
    assert store.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == n
