"""Live per-session override for the codebook -> prompt distill options
(distill_options.py) — YAML defaults (DistillConfig) merged with a
runtime override written by the annotate-screen Options panel."""

from potato.solo_mode.config import DistillConfig
from potato.solo_mode.distill_options import (
    clear_override, effective_options, load_override, save_override,
)


class FakeSoloConfig:
    def __init__(self, state_dir, distill=None):
        self.state_dir = state_dir
        self.distill = distill or DistillConfig()


def test_effective_options_defaults_to_distill_config(tmp_path):
    cfg = FakeSoloConfig(str(tmp_path),
                          distill=DistillConfig(max_examples=3))
    opts = effective_options(cfg)
    assert opts == {
        "show_examples": True, "max_examples": 3,
        "include_rationale": True, "summarize_above_tokens": 400,
    }


def test_save_override_merges_and_persists(tmp_path):
    state_dir = str(tmp_path)
    save_override(state_dir, {"max_examples": 1})
    save_override(state_dir, {"show_examples": False})

    merged = load_override(state_dir)
    assert merged == {"max_examples": 1, "show_examples": False}


def test_effective_options_prefers_override_over_defaults(tmp_path):
    state_dir = str(tmp_path)
    cfg = FakeSoloConfig(state_dir, distill=DistillConfig(max_examples=5))
    save_override(state_dir, {"max_examples": 1})

    opts = effective_options(cfg)
    assert opts["max_examples"] == 1
    assert opts["show_examples"] is True  # untouched fields keep defaults


def test_clear_override_restores_defaults(tmp_path):
    state_dir = str(tmp_path)
    cfg = FakeSoloConfig(state_dir)
    save_override(state_dir, {"max_examples": 1})
    clear_override(state_dir)

    assert load_override(state_dir) is None
    assert effective_options(cfg)["max_examples"] == 5  # DistillConfig default


def test_effective_options_tolerates_missing_state_dir():
    cfg = FakeSoloConfig(None)
    assert effective_options(cfg)["max_examples"] == 5


def test_ignores_unknown_keys(tmp_path):
    state_dir = str(tmp_path)
    save_override(state_dir, {"max_examples": 2, "bogus_field": "x"})
    merged = load_override(state_dir)
    assert "bogus_field" not in merged
    assert merged["max_examples"] == 2
