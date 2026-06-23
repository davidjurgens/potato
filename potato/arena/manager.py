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

logger = logging.getLogger("potato.arena")


class ArenaManager:
    def __init__(self, config: Dict[str, Any]):
        self.settings = ArenaConfig.from_config(config)
        self._lock = threading.RLock()
        self.history = deque(maxlen=200)         # recent {prompt, results}
        self.preferences = deque(maxlen=1000)    # {prompt, winner, ranking}
        self._wins: Dict[str, int] = {m.label: 0 for m in self.settings.models}
        self._compares: Dict[str, int] = {m.label: 0 for m in self.settings.models}
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

    def record_preference(self, prompt: str, winner: str,
                          ranking: Optional[List[str]] = None) -> None:
        with self._lock:
            self.preferences.appendleft({"prompt": prompt, "winner": winner, "ranking": ranking})
            labels = ranking or [m.label for m in self.settings.models]
            for lbl in labels:
                self._compares[lbl] = self._compares.get(lbl, 0) + 1
            if winner:
                self._wins[winner] = self._wins.get(winner, 0) + 1

    def leaderboard(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = []
            for lbl in self.model_labels():
                wins, comps = self._wins.get(lbl, 0), self._compares.get(lbl, 0)
                rows.append({"label": lbl, "wins": wins, "comparisons": comps,
                             "win_rate": round(wins / comps, 3) if comps else None})
            rows.sort(key=lambda r: (r["win_rate"] if r["win_rate"] is not None else -1), reverse=True)
            return rows


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
