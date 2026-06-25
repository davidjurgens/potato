"""Unit tests for Elo / Bradley-Terry pairwise rating and arena integration (D3)."""

import pytest

from potato.server_utils.pairwise_rating import (
    EloRating, bradley_terry, pairs_from_ranking, pairs_from_winner,
)


class TestElo:
    def test_winner_gains_loser_loses(self):
        elo = EloRating()
        elo.update("A", "B")
        assert elo.rating("A") > 1000 > elo.rating("B")

    def test_zero_sum(self):
        elo = EloRating()
        elo.update("A", "B")
        assert elo.rating("A") + elo.rating("B") == pytest.approx(2000.0)

    def test_consistent_winner_ranks_first(self):
        elo = EloRating()
        for _ in range(20):
            elo.update("Strong", "Weak")
        assert elo.rating("Strong") > elo.rating("Weak")


class TestBradleyTerry:
    def test_dominant_model_scores_highest(self):
        pairs = [("A", "B")] * 10 + [("A", "C")] * 10 + [("B", "C")] * 5
        bt = bradley_terry(pairs, labels=["A", "B", "C"])
        assert bt["A"] > bt["B"] > bt["C"]

    def test_opponent_strength_matters(self):
        # X beats only a weak model; Y beats a strong model. Y should rank higher
        # even with equal raw win counts — the whole point over win-rate.
        pairs = [("X", "Weak")] * 5 + [("Y", "Strong")] * 5 + [("Strong", "Weak")] * 10
        bt = bradley_terry(pairs, labels=["X", "Y", "Strong", "Weak"])
        assert bt["Y"] > bt["X"]

    def test_scores_on_0_100_scale(self):
        bt = bradley_terry([("A", "B")] * 3, labels=["A", "B"])
        for v in bt.values():
            assert 0.0 <= v <= 100.0

    def test_empty_pairs(self):
        assert bradley_terry([], labels=["A"]) == {"A": 50.0} or bradley_terry([]) == {}


class TestPairExpansion:
    def test_ranking_expands_to_all_pairs(self):
        pairs = pairs_from_ranking(["A", "B", "C"])
        assert ("A", "B") in pairs and ("A", "C") in pairs and ("B", "C") in pairs
        assert len(pairs) == 3

    def test_winner_beats_field(self):
        pairs = pairs_from_winner("A", ["A", "B", "C"])
        assert set(pairs) == {("A", "B"), ("A", "C")}


class TestArenaIntegration:
    def _mgr(self):
        from potato.arena.manager import ArenaManager
        return ArenaManager({"arena": {"enabled": True, "models": [
            {"label": "M1", "endpoint_type": "openai", "model": "x"},
            {"label": "M2", "endpoint_type": "openai", "model": "y"},
        ]}})

    def test_leaderboard_has_elo_and_bt_after_pref(self):
        mgr = self._mgr()
        # seed a run so responses can attach for DPO
        mgr.history.appendleft({"prompt": "p", "results": [
            {"label": "M1", "response": "good answer"},
            {"label": "M2", "response": "bad answer"}]})
        mgr.record_preference("p", "M1")
        lb = {r["label"]: r for r in mgr.leaderboard()}
        assert lb["M1"]["elo"] > lb["M2"]["elo"]
        assert lb["M1"]["bt_score"] >= lb["M2"]["bt_score"]
        assert mgr.leaderboard()[0]["label"] == "M1"  # leader ranked first

    def test_export_dpo_pairs(self):
        mgr = self._mgr()
        mgr.history.appendleft({"prompt": "p", "results": [
            {"label": "M1", "response": "chosen text"},
            {"label": "M2", "response": "rejected text"}]})
        mgr.record_preference("p", "M1")
        dpo = mgr.export_dpo()
        assert len(dpo) == 1
        assert dpo[0]["chosen"] == "chosen text"
        assert dpo[0]["rejected"] == "rejected text"
        assert dpo[0]["prompt"] == "p"

    def test_no_dpo_without_responses(self):
        mgr = self._mgr()
        mgr.record_preference("p", "M1")  # no history -> no response text
        assert mgr.export_dpo() == []
