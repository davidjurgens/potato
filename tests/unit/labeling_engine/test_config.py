"""
Parsing and validating the labeling_engine block, and its wiring into boot.
"""

import pytest

from potato.labeling_engine.config import EngineConfigError, parse_engine_config

SCHEMES = [{"name": "sentiment", "annotation_type": "radio",
            "labels": ["positive", "negative"]}]


def _cfg(**block):
    base = {
        "enabled": True,
        "sources": [
            {"id": "laya", "kind": "decision", "endpoint_type": "laya",
             "model": "convaiinnovations/laya"},
            {"id": "gemma", "kind": "llm", "endpoint_type": "vllm", "model": "g",
             "base_url": "http://x/v1", "api_key": "secret"},
        ],
        "cascade": ["laya", "gemma"],
        "contracts": [{"id": "acc", "kind": "selective_risk", "schema": "sentiment",
                       "error": 0.05, "confidence": 0.9, "per_class": True}],
    }
    base.update(block)
    return {"annotation_schemes": SCHEMES, "labeling_engine": base}


def _errors(**block):
    with pytest.raises(EngineConfigError) as e:
        parse_engine_config(_cfg(**block))
    return e.value.errors


class TestParse:

    def test_absent_block_is_disabled(self):
        assert parse_engine_config({}).enabled is False

    def test_full_block(self):
        cfg = parse_engine_config(_cfg())
        assert cfg.enabled and cfg.cascade == ["laya", "gemma"]
        [c] = cfg.contracts
        assert c.error == 0.05 and c.delta == pytest.approx(0.1) and c.per_class
        assert cfg.humans.pools == ["team"] and cfg.humans.verify_visibility == "shown"

    def test_cascade_defaults_to_first_source(self):
        assert parse_engine_config(_cfg(cascade=None)).cascade == ["laya"]

    def test_api_key_is_not_part_of_the_version_params(self):
        gemma = parse_engine_config(_cfg()).source("gemma")
        assert "api_key" not in gemma.public_params()
        assert gemma.public_params()["model"] == "g"

    def test_config_hash_changes_with_the_prompt(self):
        a = parse_engine_config(_cfg())
        srcs = _cfg()["labeling_engine"]["sources"]
        srcs[1]["prompt"] = "Classify the sentiment."
        b = parse_engine_config(_cfg(sources=srcs))
        assert a.config_hash() != b.config_hash()

    def test_zero_epsilon_is_kept(self):
        cfg = parse_engine_config(_cfg(contracts=[
            {"kind": "no_worse_than_human", "schema": "sentiment", "epsilon": 0}]))
        assert cfg.contracts[0].epsilon == 0.0


class TestErrors:

    def test_every_problem_is_reported_at_once(self):
        errs = _errors(
            sources=[{"id": "a", "kind": "nonsense"}, {"kind": "llm"}],
            cascade=["missing"],
            contracts=[{"kind": "selective_risk", "schema": "nope"}],
            humans={"pools": ["mturk"]},
        )
        text = "\n".join(errs)
        for needle in ("kind must be one of", "id is required",
                       "endpoint_type is required", "unknown source 'missing'",
                       "'nope' is not an annotation scheme", "error is required",
                       "pools must list"):
            assert needle in text, needle

    @pytest.mark.parametrize("error", [1.0, -0.1, "five"])
    def test_selective_risk_error_range(self, error):
        errs = _errors(contracts=[{"kind": "selective_risk", "schema": "sentiment",
                                   "error": error}])
        assert any("error" in e for e in errs)

    @pytest.mark.parametrize("conf", [0, 1, 1.5])
    def test_confidence_is_strictly_between_zero_and_one(self, conf):
        errs = _errors(contracts=[{"kind": "ppi", "schema": "sentiment",
                                   "confidence": conf}])
        assert any("confidence" in e for e in errs)

    def test_duplicate_ids(self):
        src = {"id": "a", "kind": "fixture"}
        errs = _errors(sources=[src, dict(src)], cascade=["a"])
        assert any("duplicate ids a" in e for e in errs)

    def test_unknown_source_key(self):
        errs = _errors(sources=[{"id": "a", "kind": "fixture", "tempreature": 0}],
                       cascade=["a"])
        assert any("unknown keys: tempreature" in e for e in errs)

    def test_live_crowd_spend_needs_a_human_budget(self):
        errs = _errors(humans={"pools": ["crowd"]},
                       features={"crowd_live_spend": True})
        assert any("never unbounded" in e for e in errs)

    def test_live_crowd_spend_with_budget_is_accepted(self):
        cfg = parse_engine_config(_cfg(humans={"pools": ["crowd"]},
                                       features={"crowd_live_spend": True},
                                       budgets={"human_usd": 40}))
        assert cfg.feature("crowd_live_spend") and cfg.budgets["human_usd"] == 40

    def test_enabled_without_sources(self):
        errs = _errors(sources=[], cascade=[], contracts=[])
        assert any("at least one source" in e for e in errs)

    def test_jury_members_must_exist(self):
        errs = _errors(sources=[{"id": "j", "kind": "jury", "members": ["a", "b"]}],
                       cascade=["j"])
        assert any("unknown source 'a'" in e for e in errs)

    def test_unknown_feature_and_budget(self):
        errs = _errors(features={"telepathy": True}, budgets={"gold_bars": 3})
        assert any("telepathy" in e for e in errs)
        assert any("gold_bars" in e for e in errs)


class TestBootWiring:

    def test_invalid_block_stops_config_validation(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_labeling_engine_config)
        bad = _cfg(cascade=["missing"])
        with pytest.raises(ConfigValidationError, match="unknown source"):
            validate_labeling_engine_config(bad)

    def test_disabled_block_is_still_checked(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_labeling_engine_config)
        bad = _cfg(enabled=False, cascade=["missing"])
        with pytest.raises(ConfigValidationError):
            validate_labeling_engine_config(bad)

    @pytest.mark.parametrize("block", [None, {"enabled": False}])
    def test_engine_strategy_needs_the_engine_on(self, block):
        """Otherwise annotators are told every item has enough annotators."""
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_labeling_engine_config)
        cfg = {"annotation_schemes": SCHEMES, "assignment_strategy": "engine"}
        if block is not None:
            cfg["labeling_engine"] = _cfg(**block)["labeling_engine"]
        with pytest.raises(ConfigValidationError, match="assignment_strategy: engine"):
            validate_labeling_engine_config(cfg)
        cfg["labeling_engine"] = _cfg()["labeling_engine"]
        validate_labeling_engine_config(cfg)

    @pytest.mark.parametrize("enabled", [False, True])
    def test_engine_mcp_tools_warn_when_the_engine_is_off(self, enabled, caplog):
        from potato.server_utils.config_module import validate_mcp_config
        cfg = _cfg(enabled=enabled)
        cfg["mcp"] = {"enabled": True, "tools": ["get_status", "engine_status"]}
        with caplog.at_level("WARNING"):
            validate_mcp_config(cfg)
        warned = [r for r in caplog.records if "engine_status" in r.getMessage()]
        assert bool(warned) is not enabled

    def test_keys_are_known_to_the_hygiene_check(self):
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS
        assert "labeling_engine" in KNOWN_CONFIG_KEYS
        assert "model_training" in KNOWN_CONFIG_KEYS

    def test_env_vars_are_substituted_in_sources(self, monkeypatch):
        from potato.server_utils.config_module import _substitute_llm_block_env_vars
        monkeypatch.setenv("ENGINE_TEST_URL", "http://burger:8001/v1")
        cfg = _cfg()
        cfg["labeling_engine"]["sources"][1]["base_url"] = "${ENGINE_TEST_URL}"
        out = _substitute_llm_block_env_vars(cfg)
        assert out["labeling_engine"]["sources"][1]["base_url"] == "http://burger:8001/v1"


class TestSourceKindChecks:
    """Found by potato-skill (H1/H2): each of these passed validation and
    then predicted nothing."""

    @pytest.mark.parametrize("source,word", [
        ({"id": "d", "kind": "decision", "endpoint_type": "vllm", "model": "m"},
         "not a decision model"),
        ({"id": "d", "kind": "decision", "endpoint_type": "systemone", "model": "m"},
         "base_url is required"),
        ({"id": "d", "kind": "llm", "endpoint_type": "laya", "model": "m"},
         "use kind: decision"),
    ])
    def test_decision_source_mistakes(self, source, word):
        errs = _errors(sources=[source], cascade=["d"])
        assert any(word in e for e in errs), errs

    def test_a_contract_on_a_scheme_no_source_supports(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_labeling_engine_config)
        cfg = _cfg(sources=[{"id": "laya", "kind": "decision", "endpoint_type": "laya",
                             "model": "convaiinnovations/laya"}], cascade=["laya"])
        cfg["annotation_schemes"] = [{"name": "sentiment", "annotation_type": "multiselect",
                                      "labels": ["a", "b"]}]
        with pytest.raises(ConfigValidationError, match="no cascade source can label"):
            validate_labeling_engine_config(cfg)


def test_a_contract_on_a_free_text_scheme_is_refused():
    """Found by potato-skill (D9)."""
    from potato.server_utils.config_module import (
        ConfigValidationError, validate_labeling_engine_config)
    cfg = _cfg(sources=[{"id": "f", "kind": "static", "field": "pred"}], cascade=["f"])
    cfg["annotation_schemes"] = [{"name": "sentiment", "annotation_type": "text"}]
    with pytest.raises(ConfigValidationError, match="cannot score"):
        validate_labeling_engine_config(cfg)


class TestSetupsThatCannotWork:
    """Found by potato-skill (B9): each validated and failed later."""

    def test_an_unknown_contract_key_is_refused(self):
        cfg = _cfg(contracts=[{"id": "acc", "kind": "selective_risk", "schema": "sentiment",
                               "eror": 0.05, "error": 0.05}])
        assert any("unknown keys: eror" in e for e in _errors(**cfg["labeling_engine"]))

    def test_native_confidence_on_an_llm(self):
        srcs = _cfg()["labeling_engine"]["sources"]
        srcs[1]["confidence"] = {"method": "native"}
        assert any("native" in e for e in _errors(sources=srcs))

    def test_logprob_with_more_than_twenty_labels(self):
        from potato.labeling_engine.config import EngineConfigError, parse_engine_config
        cfg = _cfg()
        cfg["labeling_engine"]["sources"][1]["confidence"] = {"method": "logprob"}
        cfg["annotation_schemes"] = [dict(SCHEMES[0], labels=[f"l{k}" for k in range(25)])]
        with pytest.raises(EngineConfigError, match="at most 20"):
            parse_engine_config(cfg)

    def test_the_alt_test_needs_three_people_per_item(self):
        errs = _errors(contracts=[{"id": "h", "kind": "no_worse_than_human",
                                   "schema": "sentiment"}],
                       humans={"overlap": 0.5, "overlap_k": 2})
        assert any("overlap_k must be at least 3" in e for e in errs)


def test_a_scheme_the_engine_leaves_to_people_is_warned_about(caplog):
    """Found by potato-skill (A6): `topic` was answered on 5 of 30 items."""
    from potato.server_utils.config_module import validate_labeling_engine_config
    cfg = _cfg(schemas=["sentiment"])
    cfg["annotation_schemes"] = SCHEMES + [{"name": "topic", "annotation_type": "radio",
                                            "labels": ["a", "b"]}]
    cfg["assignment_strategy"] = "engine"
    with caplog.at_level("WARNING"):
        validate_labeling_engine_config(cfg)
    assert any("topic" in r.getMessage() and "not on every item" in r.getMessage()
               for r in caplog.records)


def test_a_scheme_no_source_can_label_is_warned_about_without_a_schemas_key(caplog):
    """Found by potato-skill (A6, fork S): with no `schemas` key, the commonest
    shape, a free-text `why` got no request on any item and nothing said so."""
    from potato.server_utils.config_module import validate_labeling_engine_config
    cfg = _cfg()
    cfg["annotation_schemes"] = SCHEMES + [{"name": "why", "annotation_type": "text",
                                            "description": "Why?"}]
    cfg["assignment_strategy"] = "engine"
    with caplog.at_level("WARNING"):
        validate_labeling_engine_config(cfg)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("why" in m and "not on every item" in m for m in msgs)
    assert not any("sentiment" in m and "not on every item" in m for m in msgs)


class TestEveryBlockRefusesTypos:
    """Found by potato-skill (O3): `optimize {prompt_variants: 3, bogus: 1}`,
    `drift {zzz: 2}`, `distill {trainr: x}` and `redaction {categoris: [...]}`
    all passed `validate --strict`. optimize and drift had no setting any code
    read; they are on/off features only."""

    @pytest.mark.parametrize("block, bad", [
        ({"distill": {"trainr": "x"}}, "labeling_engine.distill has unknown keys: trainr"),
        ({"redaction": {"categoris": ["email"]}},
         "labeling_engine.redaction has unknown keys: categoris"),
        ({"humans": {"overlapk": 3}}, "labeling_engine.humans has unknown keys: overlapk"),
        ({"crowd": {"studyid": "x"}}, "labeling_engine.crowd has unknown keys: studyid"),
        ({"runtime": {"hold_minute": 5}}, "labeling_engine.runtime has unknown keys: hold_minute"),
        ({"sourcse": []}, "labeling_engine has unknown keys: sourcse"),
        ({"optimize": {"prompt_variants": 3}}, "features.optimize"),
        ({"drift": {"per_class": True}}, "features.drift"),
    ])
    def test_refused(self, block, bad):
        assert any(bad in e for e in _errors(**block))

    def test_the_documented_keys_pass(self):
        cfg = parse_engine_config(_cfg(
            distill={"trainer": "sklearn-text", "min_labels": 50, "every": 2,
                     "include_silver": False},
            redaction={"categories": ["email"]},
            runtime={"hold_minutes": 5, "cache": True}))
        assert cfg.distill["include_silver"] is False and cfg.runtime.hold_minutes == 5


def test_the_note_for_an_older_key_is_shown_once(capsys, monkeypatch):
    """Found by potato-skill (O1): logged at info before logging was set up,
    so `validate`, `start` and `start -v` never showed it."""
    from potato.server_utils import config_module
    monkeypatch.setattr(config_module, "_DEPRECATION_NOTES_SHOWN", set())
    cfg = {"annotation_schemes": SCHEMES,
           "icl_labeling": {"enabled": True}}
    config_module.validate_labeling_engine_config(cfg)
    config_module.validate_labeling_engine_config(cfg)
    err = capsys.readouterr().err
    assert err.count("NOTE: icl_labeling") == 1 and "migrate-config" in err


class TestNoContracts:
    """An enabled engine with `contracts: []` validates and accepts nothing.

    Reported by the potato-skill agent: the config passed `validate --strict`
    and the engine then never accepted a machine label.
    """

    def _warnings(self, caplog, cfg):
        import logging
        from potato.server_utils.config_module import validate_labeling_engine_config
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="potato.server_utils.config_module"):
            validate_labeling_engine_config(cfg)
        return [r.getMessage() for r in caplog.records if "no contracts" in r.getMessage()]

    def test_enabled_with_no_contracts_warns(self, caplog):
        [msg] = self._warnings(caplog, _cfg(contracts=[]))
        assert "accept no machine label" in msg

    def test_with_a_contract_it_does_not(self, caplog):
        assert self._warnings(caplog, _cfg()) == []

    def test_disabled_with_no_contracts_does_not(self, caplog):
        assert self._warnings(caplog, _cfg(enabled=False, contracts=[])) == []
