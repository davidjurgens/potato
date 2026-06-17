"""Unit tests for judge_calibration config parsing and validation."""

import os
import pytest

from potato.judge_calibration.config import parse_judge_calibration_config


def _base(jc):
    return {"judge_calibration": jc, "output_annotation_dir": "ao"}


class TestParse:
    def test_disabled_when_absent(self):
        cfg = parse_judge_calibration_config({})
        assert cfg.enabled is False

    def test_defaults(self):
        cfg = parse_judge_calibration_config(_base({"enabled": True}))
        assert cfg.enabled is True
        assert cfg.k_samples == 5
        assert cfg.sampling.strategy == "random"
        assert cfg.sampling.sample_size == 200
        assert cfg.human.num_raters == 1
        assert cfg.human.gold == "single"
        assert cfg.calibration.n_bins == 10
        assert cfg.output.labels_file == "llm_labels.jsonl"
        # state_dir derives from output_annotation_dir when not given
        assert cfg.state_dir == os.path.join("ao", ".judge_calibration")

    def test_models_parsed_with_env_key(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret123")
        cfg = parse_judge_calibration_config(_base({
            "enabled": True,
            "models": [
                {"endpoint_type": "openai", "model": "gpt-4o-mini", "api_key": "${MY_KEY}", "temperature": 0.7},
                {"endpoint_type": "ollama", "model": "llama3", "base_url": "http://x:11434"},
            ],
        }))
        assert len(cfg.models) == 2
        assert cfg.models[0].api_key == "secret123"
        assert cfg.models[1].base_url == "http://x:11434"

    def test_output_files_override(self):
        cfg = parse_judge_calibration_config(_base({
            "enabled": True,
            "output": {"dir": "d", "files": {"labels": "L.jsonl", "report_json": "R.json"}},
        }))
        assert cfg.output.dir == "d"
        assert cfg.output.labels_file == "L.jsonl"
        assert cfg.output.report_json == "R.json"


class TestValidate:
    def _ok_models(self):
        return [{"endpoint_type": "ollama", "model": "llama3", "temperature": 0.7}]

    def test_valid(self):
        cfg = parse_judge_calibration_config(_base({
            "enabled": True, "models": self._ok_models(),
        }))
        assert cfg.validate() == []

    def test_requires_models(self):
        cfg = parse_judge_calibration_config(_base({"enabled": True}))
        errs = cfg.validate()
        assert any("models" in e for e in errs)

    def test_bad_strategy(self):
        cfg = parse_judge_calibration_config(_base({
            "enabled": True, "models": self._ok_models(),
            "sampling": {"strategy": "nonsense"},
        }))
        assert any("strategy" in e for e in cfg.validate())

    def test_bad_fraction(self):
        cfg = parse_judge_calibration_config(_base({
            "enabled": True, "models": self._ok_models(), "fraction": 1.5,
        }))
        assert any("fraction" in e for e in cfg.validate())

    def test_bad_gold(self):
        cfg = parse_judge_calibration_config(_base({
            "enabled": True, "models": self._ok_models(),
            "human": {"gold": "consensus"},
        }))
        assert any("gold" in e for e in cfg.validate())

    def test_k_samples_min(self):
        cfg = parse_judge_calibration_config(_base({
            "enabled": True, "models": self._ok_models(), "k_samples": 0,
        }))
        assert any("k_samples" in e for e in cfg.validate())

    def test_temperature_zero_warns_not_errors(self, caplog):
        cfg = parse_judge_calibration_config(_base({
            "enabled": True, "k_samples": 5,
            "models": [{"endpoint_type": "ollama", "model": "llama3", "temperature": 0}],
        }))
        errs = cfg.validate()
        assert errs == []  # warning only, not an error
