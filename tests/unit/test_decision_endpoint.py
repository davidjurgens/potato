"""Decision-model endpoints: scheme mapping, wire format, Laya wiring."""

import json
import subprocess
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
import requests

from potato.ai.ai_endpoint import (
    AIEndpointConfigError, AIEndpointFactory, AIEndpointRequestError,
)
from potato.ai.decision_endpoint import (
    MAX_SLIDER_STEPS, DecisionQuestion, UnsupportedSchemeError,
    build_systemone_questions, normalize_distribution, parse_systemone_answers,
    questions_for_scheme,
)
from potato.ai.systemone_endpoint import SystemOneEndpoint


# ---------------------------------------------------------------------------
# Scheme mapping
# ---------------------------------------------------------------------------

class TestQuestionsForScheme:
    def test_radio_string_labels(self):
        qs = questions_for_scheme(
            {"annotation_type": "radio", "name": "sentiment", "description": "Pick one",
             "labels": ["positive", "negative", "neutral"]}, "Label the tweet.")
        assert len(qs) == 1
        q = qs[0]
        assert (q.id, q.kind, q.options) == ("sentiment", "choice", ["positive", "negative", "neutral"])
        assert q.text == "Label the tweet.\n\nPick one"

    def test_radio_dict_labels_keep_tooltips(self):
        qs = questions_for_scheme(
            {"annotation_type": "radio", "name": "s",
             "labels": [{"name": "pos", "tooltip": "good vibes"}, {"name": "neg"}]}, "")
        assert qs[0].options == ["pos", "neg"]
        assert qs[0].descriptions == {"pos": "good vibes"}
        assert qs[0].text == "s"

    def test_select_is_choice(self):
        q = questions_for_scheme({"annotation_type": "select", "name": "c",
                                  "labels": ["a", "b"]}, "x")[0]
        assert q.kind == "choice"

    def test_yes_no_radio_stays_choice(self):
        q = questions_for_scheme({"annotation_type": "radio", "name": "c",
                                  "labels": ["Yes", "No"]}, "x")[0]
        assert q.kind == "choice" and q.options == ["Yes", "No"]

    def test_radio_needs_two_labels(self):
        with pytest.raises(UnsupportedSchemeError):
            questions_for_scheme({"annotation_type": "radio", "name": "c", "labels": ["a"]}, "")

    def test_likert(self):
        q = questions_for_scheme({"annotation_type": "likert", "name": "agree", "size": 5,
                                  "min_label": "Disagree", "max_label": "Agree"}, "")[0]
        assert q.kind == "score"
        assert q.options == ["1", "2", "3", "4", "5"]
        assert q.descriptions == {"1": "1 (Disagree)", "5": "5 (Agree)"}

    def test_likert_bad_size(self):
        with pytest.raises(UnsupportedSchemeError):
            questions_for_scheme({"annotation_type": "likert", "name": "a"}, "")

    def test_slider_steps(self):
        q = questions_for_scheme({"annotation_type": "slider", "name": "s",
                                  "min_value": 0, "max_value": 10, "step": 2}, "")[0]
        assert q.kind == "score"
        assert q.options == ["0", "2", "4", "6", "8", "10"]

    def test_slider_at_limit_ok_and_over_limit_raises(self):
        q = questions_for_scheme({"annotation_type": "slider", "name": "s",
                                  "min_value": 0, "max_value": MAX_SLIDER_STEPS - 1}, "")[0]
        assert len(q.options) == MAX_SLIDER_STEPS
        with pytest.raises(UnsupportedSchemeError, match="steps"):
            questions_for_scheme({"annotation_type": "slider", "name": "s",
                                  "min_value": 0, "max_value": 100}, "")

    @pytest.mark.parametrize("atype", ["multiselect", "span", "text", "textbox", "number",
                                       "pairwise", "image_annotation"])
    def test_unsupported_types(self, atype):
        with pytest.raises(UnsupportedSchemeError) as exc:
            questions_for_scheme({"annotation_type": atype, "name": "x", "labels": ["a", "b"]}, "")
        assert atype in str(exc.value) and "one-of-N" in str(exc.value)
        assert isinstance(exc.value, ValueError)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_probabilities_renormalised(self):
        out = normalize_distribution({"a": 0.5, "b": 0.4999})
        assert out["a"] == pytest.approx(0.5 / 0.9999)
        assert sum(out.values()) == pytest.approx(1.0)

    def test_logits_softmaxed(self):
        out = normalize_distribution({"a": 2.0, "b": 0.0, "c": -1.0})
        assert sum(out.values()) == pytest.approx(1.0)
        assert out["a"] == pytest.approx(0.8437947, rel=1e-5)

    def test_unnormalised_scores_softmaxed(self):
        out = normalize_distribution({"a": 0.9, "b": 0.9})
        assert out == pytest.approx({"a": 0.5, "b": 0.5})

    def test_non_numeric_raises(self):
        with pytest.raises(AIEndpointRequestError):
            normalize_distribution({"a": "x"})


# ---------------------------------------------------------------------------
# Wire format: request body and response parsing
# ---------------------------------------------------------------------------

CHOICE = DecisionQuestion(id="team", kind="choice", text="Which team?",
                          options=["billing", "technical", "account"],
                          descriptions={"billing": "Payments, invoices, refunds"})
SCORE = DecisionQuestion(id="urgency", kind="score", text="How urgent?",
                         options=["Can wait", "Reply this week", "Reply today"])
NOUL = DecisionQuestion(id="refund_requested", kind="noul", text="Refund asked?")

# The response example from spice.ai/learn/typesafe-jev, verbatim.
JEV_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "team": {"type": "choice", "choice": "billing",
                 "probabilities": {"billing": 0.97, "technical": 0.02, "account": 0.01},
                 "confidence": 0.95},
        "urgency": {"type": "score", "score": 1.9,
                    "legend": {"0": "Can wait", "1": "Reply this week", "2": "Reply today"},
                    "probabilities": {"0": 0.0, "1": 0.1, "2": 0.9}, "confidence": 0.85},
        "refund_requested": {"type": "noul", "noul": 0.91},
    },
    "usage": {"input_tokens": 312, "output_tokens": 30},
}


def test_build_questions_shape():
    body = build_systemone_questions([CHOICE, SCORE, NOUL])
    assert body == {
        "team": {"type": "choice", "instructions": "Which team?",
                 "criteria": {"billing": "Payments, invoices, refunds",
                              "technical": None, "account": None}},
        "urgency": {"type": "score", "instructions": "How urgent?",
                    "criteria": ["Can wait", "Reply this week", "Reply today"]},
        "refund_requested": {"type": "noul", "instructions": "Refund asked?"},
    }


def test_parse_jev_response():
    team, urgency, refund = parse_systemone_answers(JEV_RESPONSE, [CHOICE, SCORE, NOUL])
    assert team.value == "billing"
    # confidence is P(value), not the backend's entropy confidence (0.95)
    assert team.confidence == pytest.approx(0.97)
    assert urgency.value == "Reply today"
    assert urgency.confidence == pytest.approx(0.9)
    assert urgency.probabilities == pytest.approx(
        {"Can wait": 0.0, "Reply this week": 0.1, "Reply today": 0.9})
    assert refund.value is True
    assert refund.confidence == pytest.approx(0.91)
    assert refund.probabilities == pytest.approx({"yes": 0.91, "no": 0.09})
    assert refund.raw == {"type": "noul", "noul": 0.91}


def test_parse_noul_false_and_logit():
    q = [NOUL]
    a = parse_systemone_answers({"answers": {"refund_requested": {"noul": 0.2}}}, q)[0]
    assert a.value is False and a.confidence == pytest.approx(0.8)
    a = parse_systemone_answers({"answers": {"refund_requested": {"noul": 3.0}}}, q)[0]
    assert a.value is True and 0.9 < a.probabilities["yes"] < 1.0


def test_parse_missing_answer_raises():
    with pytest.raises(AIEndpointRequestError, match="team"):
        parse_systemone_answers({"answers": {}}, [CHOICE])
    with pytest.raises(AIEndpointRequestError):
        parse_systemone_answers({"detail": "nope"}, [CHOICE])


def test_parse_unknown_option_raises():
    resp = {"answers": {"team": {"choice": "sales", "probabilities": {"sales": 1.0}}}}
    with pytest.raises(AIEndpointRequestError, match="sales"):
        parse_systemone_answers(resp, [CHOICE])


# ---------------------------------------------------------------------------
# SystemOneEndpoint
# ---------------------------------------------------------------------------

def _endpoint(**cfg):
    cfg.setdefault("base_url", "https://api.typesafe.ai/v1/")
    return SystemOneEndpoint({"ai_config": cfg})


def _ok(payload):
    resp = MagicMock(status_code=200, text=json.dumps(payload))
    resp.json.return_value = payload
    return resp


class TestSystemOneEndpoint:
    def test_requires_base_url(self):
        with pytest.raises(AIEndpointConfigError, match="base_url"):
            SystemOneEndpoint({"ai_config": {}})

    def test_request_body_and_headers(self):
        ep = _endpoint(api_key="sk-test")
        with patch("potato.ai.systemone_endpoint.requests.post",
                   return_value=_ok(JEV_RESPONSE)) as post:
            answers = ep.decide("I was charged twice", [CHOICE, SCORE, NOUL])
        assert [a.id for a in answers] == ["team", "urgency", "refund_requested"]
        assert post.call_count == 1  # every question in one request
        args, kwargs = post.call_args
        assert args[0] == "https://api.typesafe.ai/v1/systemone"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
        assert kwargs["timeout"] == 30
        body = kwargs["json"]
        assert body["model"] == "jev-latest"
        assert body["state"] == {"text": "I was charged twice"}
        assert body["questions"] == build_systemone_questions([CHOICE, SCORE, NOUL])

    def test_no_auth_header_without_key_and_bare_state(self):
        ep = _endpoint(state_key="", model="openjev", timeout=5)
        with patch("potato.ai.systemone_endpoint.requests.post",
                   return_value=_ok(JEV_RESPONSE)) as post:
            ep.decide("hi", [NOUL])
        kwargs = post.call_args.kwargs
        assert "Authorization" not in kwargs["headers"]
        assert kwargs["json"]["state"] == "hi"
        assert kwargs["json"]["model"] == "openjev"
        assert kwargs["timeout"] == 5

    def test_http_error_carries_body(self):
        ep = _endpoint()
        bad = MagicMock(status_code=401, text='{"detail":"invalid or missing bearer token"}')
        with patch("potato.ai.systemone_endpoint.requests.post", return_value=bad):
            with pytest.raises(AIEndpointRequestError, match="401.*invalid or missing bearer"):
                ep.decide("x", [NOUL])

    def test_timeout_and_connection_errors(self):
        ep = _endpoint()
        with patch("potato.ai.systemone_endpoint.requests.post",
                   side_effect=requests.exceptions.Timeout()):
            with pytest.raises(AIEndpointRequestError, match="timed out"):
                ep.decide("x", [NOUL])
        with patch("potato.ai.systemone_endpoint.requests.post",
                   side_effect=requests.exceptions.ConnectionError("refused")):
            with pytest.raises(AIEndpointRequestError, match="refused"):
                ep.decide("x", [NOUL])

    def test_non_json_response(self):
        ep = _endpoint()
        resp = MagicMock(status_code=200, text="<html>")
        resp.json.side_effect = ValueError("no json")
        with patch("potato.ai.systemone_endpoint.requests.post", return_value=resp):
            with pytest.raises(AIEndpointRequestError, match="not JSON"):
                ep.decide("x", [NOUL])

    def test_max_options(self):
        assert _endpoint().max_options == 255
        assert _endpoint(model="openjev").max_options == 52
        ep = _endpoint(max_options=3)
        too_many = DecisionQuestion(id="q", kind="choice", text="?", options=list("abcd"))
        with patch("potato.ai.systemone_endpoint.requests.post") as post:
            with pytest.raises(ValueError, match="at most 3"):
                ep.decide("x", [too_many])
        post.assert_not_called()

    def test_question_validation(self):
        ep = _endpoint()
        with pytest.raises(ValueError):
            ep.decide("x", [])
        with pytest.raises(ValueError, match="kind"):
            ep.decide("x", [DecisionQuestion(id="q", kind="multi", text="?")])
        with pytest.raises(ValueError, match="duplicate"):
            ep.decide("x", [NOUL, NOUL])

    @pytest.mark.parametrize("call", [
        lambda ep: ep.query("hello"),
        lambda ep: ep.chat_query([{"role": "user", "content": "hi"}]),
    ])
    def test_refuses_generation(self, call):
        with pytest.raises(AIEndpointRequestError, match="cannot generate text"):
            call(_endpoint())

    def test_is_decision_model(self):
        assert _endpoint().is_decision_model is True

    def test_health_check(self):
        ep = _endpoint()
        with patch("potato.ai.systemone_endpoint.requests.get",
                   return_value=MagicMock(status_code=200)):
            assert ep.health_check() is True
        with patch("potato.ai.systemone_endpoint.requests.get",
                   return_value=MagicMock(status_code=404)), \
             patch("potato.ai.systemone_endpoint.requests.post",
                   side_effect=requests.exceptions.ConnectionError("down")):
            assert ep.health_check() is False


# ---------------------------------------------------------------------------
# Factory registration
# ---------------------------------------------------------------------------

def test_factory_creates_systemone():
    ep = AIEndpointFactory.create_endpoint({"ai_support": {
        "enabled": True, "endpoint_type": "systemone",
        "ai_config": {"base_url": "http://localhost:8000"}}})
    assert isinstance(ep, SystemOneEndpoint)
    assert AIEndpointFactory.has_endpoint("laya")


# ---------------------------------------------------------------------------
# LayaEndpoint with a fake laya module
# ---------------------------------------------------------------------------

class _FakeAgent:
    def __init__(self, model, device):
        self.model, self.device = model, device
        self.calls = []

    def predict(self, state, questions, **kw):
        self.calls.append(("predict", state, questions, kw))
        return {"answers": {
            qid: ({"type": "noul", "noul": 0.7} if q["type"] == "noul" else
                  {"type": q["type"],
                   "choice": next(iter(q["criteria"])) if q["type"] == "choice" else None,
                   "probabilities": ({k: 1.0 / len(q["criteria"]) for k in q["criteria"]}
                                     if q["type"] == "choice" else
                                     {str(i): (1.0 if i == 0 else 0.0)
                                      for i in range(len(q["criteria"]))})})
            for qid, q in questions.items()}}

    def predict_batch(self, states, questions, batch_size=None, **kw):
        self.calls.append(("predict_batch", states, batch_size))
        return [self.predict(s, questions) for s in states]


@pytest.fixture
def fake_laya(monkeypatch):
    from potato.ai import laya_endpoint
    laya_endpoint.clear_predictors()
    mod = types.ModuleType("laya")
    mod.loads = []

    def load(model, device=None):
        mod.loads.append((model, device))
        return _FakeAgent(model, device)

    class Router:
        def __init__(self, device=None):
            self.agent = _FakeAgent("router", device)

        def predict(self, state, questions, **kw):
            return self.agent.predict(state, questions, **kw)

    mod.load = load
    mod.Router = Router
    monkeypatch.setitem(sys.modules, "laya", mod)
    # find_spec consults sys.modules first; a module without __spec__ raises there.
    mod.__spec__ = MagicMock()
    yield mod
    laya_endpoint.clear_predictors()


class TestLayaEndpoint:
    def test_defaults_and_decide(self, fake_laya):
        from potato.ai.laya_endpoint import LayaEndpoint
        ep = LayaEndpoint({"ai_config": {}})
        assert ep.model == "convaiinnovations/laya" and ep.device == "cpu"
        answers = ep.decide("great movie", [CHOICE, SCORE, NOUL])
        assert fake_laya.loads == [("convaiinnovations/laya", "cpu")]
        assert answers[0].value == "billing"
        assert answers[0].confidence == pytest.approx(1 / 3)
        assert answers[1].value == "Can wait"
        assert answers[2].value is True and answers[2].confidence == pytest.approx(0.7)

    def test_model_cached_per_model_and_device(self, fake_laya):
        from potato.ai.laya_endpoint import LayaEndpoint
        a = LayaEndpoint({"ai_config": {}})
        b = LayaEndpoint({"ai_config": {}})
        a.decide("x", [NOUL]); b.decide("y", [NOUL])
        assert len(fake_laya.loads) == 1
        LayaEndpoint({"ai_config": {"model": "multilingual"}}).decide("z", [NOUL])
        assert fake_laya.loads[-1] == ("multilingual", "cpu")
        assert len(fake_laya.loads) == 2

    def test_router_mode(self, fake_laya):
        from potato.ai.laya_endpoint import LayaEndpoint
        ep = LayaEndpoint({"ai_config": {"model": "router", "device": "cuda"}})
        assert ep.decide("x", [NOUL])[0].value is True
        assert fake_laya.loads == []

    def test_decide_batch_uses_predict_batch(self, fake_laya):
        from potato.ai.laya_endpoint import LayaEndpoint, get_predictor
        ep = LayaEndpoint({"ai_config": {"batch_size": 4}})
        out = ep.decide_batch(["a", "b", "c"], [NOUL])
        assert len(out) == 3
        agent = get_predictor("convaiinnovations/laya", "cpu")
        assert agent.calls[0] == ("predict_batch", ["a", "b", "c"], 4)

    def test_errors_wrapped(self, fake_laya):
        from potato.ai.laya_endpoint import LayaEndpoint
        ep = LayaEndpoint({"ai_config": {}})
        with patch.object(_FakeAgent, "predict", side_effect=RuntimeError("boom")):
            with pytest.raises(AIEndpointRequestError, match="boom"):
                ep.decide("x", [NOUL])

    def test_refuses_generation(self, fake_laya):
        from potato.ai.laya_endpoint import LayaEndpoint
        with pytest.raises(AIEndpointRequestError, match="decision model"):
            LayaEndpoint({"ai_config": {}}).query("write a hint")

    def test_missing_laya_names_extra(self, monkeypatch):
        from potato.ai import laya_endpoint
        monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
        with pytest.raises(AIEndpointConfigError, match=r"potato-annotation\[decision\]"):
            laya_endpoint.LayaEndpoint({"ai_config": {}})


def test_laya_endpoint_import_is_light():
    """Importing the module must not import laya or torch (fresh interpreter)."""
    code = (
        "import sys, json; import potato.ai.laya_endpoint, potato.ai.systemone_endpoint; "
        "print(json.dumps([m for m in ('laya', 'torch', 'transformers') if m in sys.modules]))"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []
