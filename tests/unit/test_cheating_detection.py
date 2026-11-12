"""Robustness tests for LLM-cheating detection (E2).

Builds synthetic crowds with known ground truth about who cheated, and checks the
detector separates honest workers from covert-LLM users and random spammers.
"""

import random
import pytest

from potato.server_utils.cheating_detection import (
    correlated_agreement, llm_echo_signal, detect_llm_cheating, AnnotatorReport,
)


def _scenario(seed=0):
    """20 items, true labels in {A,B}. honest1/honest2 mostly correct; llm_bot
    always copies the LLM; spammer answers randomly. LLM is correct ~75%."""
    rng = random.Random(seed)
    truth = {f"i{n}": ("A" if n % 2 == 0 else "B") for n in range(20)}
    llm = {i: (t if rng.random() < 0.75 else _flip(t)) for i, t in truth.items()}
    obs = []
    for i, t in truth.items():
        # honest workers: independent signal, ~85% accurate (agree with truth, not LLM)
        for h in ("honest1", "honest2", "honest3"):
            obs.append((h, i, t if rng.random() < 0.85 else _flip(t)))
        obs.append(("llm_bot", i, llm[i]))          # pure LLM echo
        obs.append(("spammer", i, rng.choice(["A", "B"])))  # random
    return obs, llm, truth


def _flip(x):
    return "B" if x == "A" else "A"


class TestCorrelatedAgreement:
    def test_honest_above_random(self):
        obs, _llm, _t = _scenario()
        ca = correlated_agreement(obs)
        assert ca["honest1"] > ca["spammer"]
        assert ca["spammer"] < 0.1  # random worker has ~chance same-item agreement

    def test_empty(self):
        assert correlated_agreement([]) == {}


class TestLlmEchoSignal:
    def test_bot_high_alignment_low_residual(self):
        obs, llm, _t = _scenario()
        echo = llm_echo_signal(obs, llm)
        bot_align, bot_resid = echo["llm_bot"]
        h_align, h_resid = echo["honest1"]
        assert bot_align == 1.0                     # copies the LLM exactly
        # honest worker diverges from the LLM sometimes and still agrees with peers
        assert (h_resid or 0) >= (bot_resid or 0)
        assert h_align < bot_align                  # honest aligns with LLM less than the bot


class TestDetectLlmCheating:
    def test_bot_is_most_suspicious(self):
        obs, llm, _t = _scenario()
        reports = detect_llm_cheating(obs, llm)
        top = reports[0]
        assert top.annotator == "llm_bot"
        assert "llm_echo" in top.flags

    def test_honest_not_flagged_as_echo(self):
        obs, llm, _t = _scenario()
        by = {r.annotator: r for r in detect_llm_cheating(obs, llm)}
        assert "llm_echo" not in by["honest1"].flags
        assert by["llm_bot"].suspicion > by["honest1"].suspicion
        assert by["llm_bot"].suspicion > by["honest2"].suspicion

    def test_spammer_flagged_low_signal(self):
        obs, llm, _t = _scenario()
        by = {r.annotator: r for r in detect_llm_cheating(obs, llm)}
        assert "low_signal" in by["spammer"].flags

    def test_works_without_llm_labels(self):
        # CA-only mode still flags the random spammer as low-signal
        obs, _llm, _t = _scenario()
        by = {r.annotator: r for r in detect_llm_cheating(obs, llm_labels=None)}
        assert by["spammer"].llm_alignment is None
        assert "low_signal" in by["spammer"].flags
        assert "low_signal" not in by["honest1"].flags

    def test_sorted_by_suspicion(self):
        obs, llm, _t = _scenario()
        reports = detect_llm_cheating(obs, llm)
        susp = [r.suspicion for r in reports]
        assert susp == sorted(susp, reverse=True)

    def test_deterministic(self):
        obs, llm, _t = _scenario(seed=3)
        a = [r.to_dict() for r in detect_llm_cheating(obs, llm)]
        b = [r.to_dict() for r in detect_llm_cheating(obs, llm)]
        assert a == b

    def test_stable_across_seeds(self):
        # the bot should rank above both honest workers across several crowds
        for seed in range(5):
            obs, llm, _t = _scenario(seed=seed)
            by = {r.annotator: r for r in detect_llm_cheating(obs, llm)}
            assert by["llm_bot"].suspicion >= by["honest1"].suspicion
            assert by["llm_bot"].suspicion >= by["honest2"].suspicion
