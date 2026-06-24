"""
Arena manager (singleton): runs prompts across the configured models and records
human preferences, producing a win-rate leaderboard.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Dict, List, Optional

from potato.arena.arena import run_arena
from potato.arena.config import ArenaConfig
from potato.server_utils.pairwise_rating import (
    EloRating, bradley_terry, pairs_from_ranking, pairs_from_winner,
)

logger = logging.getLogger("potato.arena")


class ArenaManager:
    def __init__(self, config: Dict[str, Any]):
        self.settings = ArenaConfig.from_config(config)
        self._lock = threading.RLock()
        self.history = deque(maxlen=200)         # recent {prompt, results}
        self.preferences = deque(maxlen=1000)    # {prompt, winner, ranking, chosen, rejected}
        self._wins: Dict[str, int] = {m.label: 0 for m in self.settings.models}
        self._compares: Dict[str, int] = {m.label: 0 for m in self.settings.models}
        # Pairwise outcomes drive opponent-strength-aware ratings (Elo + BT).
        self._pairs: List[tuple] = []            # [(winner_label, loser_label), ...]
        self._elo = EloRating()
        # Optional override (tests inject a stub endpoint builder).
        self.endpoint_builder = None
        logger.info("ArenaManager initialized with %d model(s)", len(self.settings.models))

    def model_labels(self) -> List[str]:
        return [m.label for m in self.settings.models]

    def run(self, prompt: str) -> List[Dict[str, Any]]:
        results = run_arena(prompt, self.settings.models, endpoint_builder=self.endpoint_builder)
        with self._lock:
            self.history.appendleft({"prompt": prompt, "results": results})
        return results

    def _latest_responses(self, prompt: str) -> Dict[str, str]:
        """Best-effort lookup of each model's response text for a prompt, from the
        most recent matching run — used to attach chosen/rejected text to a
        preference so it can be exported as DPO data."""
        for entry in self.history:  # newest first
            if entry.get("prompt") == prompt:
                out = {}
                for r in entry.get("results", []):
                    if r.get("label"):
                        out[r["label"]] = r.get("response") or r.get("output") or r.get("text") or ""
                return out
        return {}

    def record_preference(self, prompt: str, winner: str,
                          ranking: Optional[List[str]] = None) -> None:
        field = [m.label for m in self.settings.models]
        with self._lock:
            responses = self._latest_responses(prompt)
            # chosen = winner's response; rejected = the responses it beat (for DPO)
            losers = [l for l in (ranking or field) if l and l != winner]
            self.preferences.appendleft({
                "prompt": prompt, "winner": winner, "ranking": ranking,
                "chosen": responses.get(winner, ""),
                "rejected": {l: responses.get(l, "") for l in losers},
            })
            labels = ranking or field
            for lbl in labels:
                self._compares[lbl] = self._compares.get(lbl, 0) + 1
            if winner:
                self._wins[winner] = self._wins.get(winner, 0) + 1

            # Derive pairwise outcomes for Elo/BT: a full ranking gives all pairs;
            # a bare winner beats the rest of the field.
            if ranking and len(ranking) > 1:
                new_pairs = pairs_from_ranking(ranking)
            elif winner:
                new_pairs = pairs_from_winner(winner, field)
            else:
                new_pairs = []
            self._pairs.extend(new_pairs)
            self._elo.update_many(new_pairs)

    def leaderboard(self) -> List[Dict[str, Any]]:
        with self._lock:
            from potato.server_utils.eval_stats import wilson_ci
            bt = bradley_terry(self._pairs, labels=self.model_labels()) if self._pairs else {}
            rows = []
            for lbl in self.model_labels():
                wins, comps = self._wins.get(lbl, 0), self._compares.get(lbl, 0)
                ci = wilson_ci(wins, comps) if comps else {"lo": None, "hi": None}
                rows.append({
                    "label": lbl, "wins": wins, "comparisons": comps,
                    "win_rate": round(wins / comps, 3) if comps else None,
                    "win_rate_lo": ci["lo"], "win_rate_hi": ci["hi"],
                    "elo": round(self._elo.rating(lbl)) if self._pairs else None,
                    "bt_score": bt.get(lbl),
                })
            # Rank by Bradley-Terry when we have data (opponent-aware), else win-rate.
            if self._pairs:
                rows.sort(key=lambda r: (r["bt_score"] if r["bt_score"] is not None else -1), reverse=True)
            else:
                rows.sort(key=lambda r: (r["win_rate"] if r["win_rate"] is not None else -1), reverse=True)
            return rows

    def export_dpo(self) -> List[Dict[str, str]]:
        """Arena preferences as DPO triples: one (prompt, chosen, rejected) per
        winner-vs-loser pair where both response texts are available."""
        with self._lock:
            out: List[Dict[str, str]] = []
            for p in self.preferences:
                chosen = p.get("chosen") or ""
                if not chosen:
                    continue
                for loser_label, rejected in (p.get("rejected") or {}).items():
                    if rejected:
                        out.append({
                            "prompt": p.get("prompt", ""),
                            "chosen": chosen,
                            "rejected": rejected,
                            "winner": p.get("winner", ""),
                            "loser": loser_label,
                        })
            return out


# ----- singleton -----

_manager: Optional[ArenaManager] = None


def init_arena_manager(config: Dict[str, Any]) -> ArenaManager:
    global _manager
    _manager = ArenaManager(config)
    return _manager


def get_arena_manager() -> Optional[ArenaManager]:
    return _manager


def clear_arena_manager() -> None:
    global _manager
    _manager = None
