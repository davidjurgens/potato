"""
A response cache for Solo Mode's labeling calls.

The same prompt over the same text, to the same model at the same temperature,
gets the stored reply instead of a second call. Repeats are common: a prompt
reverted to an earlier version re-labels under that version, a gold-set
evaluation scores the same items every time it runs, and a study restarted from
a cleared state labels everything again.

The key covers everything that changes the reply: endpoint type, model,
base URL, temperature, the full prompt text (which carries the item, the labels
and any in-context examples) and the response schema. A provider that updates a
model behind an unchanged name is invisible to it; turn the cache off
(``solo_mode.cache.enabled: false``) to measure run-to-run variation.

Stored in SQLite under ``solo_mode.state_dir`` so it survives a restart, or in
memory when there is no state directory.
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_FILE = 'label_cache.sqlite'


def _schema_of(output_format) -> Any:
    if output_format is None:
        return None
    try:
        return output_format.model_json_schema()
    except Exception:
        return getattr(output_format, '__name__', str(output_format))


def cache_key(endpoint, prompt: str, output_format=None) -> str:
    """Hash of everything about a call that can change its reply."""
    ai_config = getattr(endpoint, 'ai_config', None)
    if not isinstance(ai_config, dict):
        ai_config = {}
    parts = {
        'endpoint': type(endpoint).__name__,
        'model': getattr(endpoint, 'model', '') or ai_config.get('model', ''),
        'base_url': ai_config.get('base_url') or ai_config.get('endpoint_url') or '',
        'temperature': getattr(endpoint, 'temperature', ai_config.get('temperature')),
        'prompt': prompt,
        'schema': _schema_of(output_format),
    }
    blob = json.dumps(parts, sort_keys=True, default=str).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


class LabelCache:
    """Thread-safe get/put of JSON-serialisable replies."""

    def __init__(self, state_dir: Optional[str] = None):
        self._lock = threading.Lock()
        self._memory: Dict[str, Any] = {}
        self._conn = None
        self.hits = 0
        self.misses = 0
        if state_dir:
            try:
                os.makedirs(state_dir, exist_ok=True)
                self._conn = sqlite3.connect(
                    os.path.join(state_dir, _FILE), check_same_thread=False)
                self._conn.execute(
                    'CREATE TABLE IF NOT EXISTS replies '
                    '(key TEXT PRIMARY KEY, reply TEXT NOT NULL)')
                self._conn.commit()
            except sqlite3.Error:
                logger.exception('Label cache unavailable on disk; using memory')
                self._conn = None

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._memory:
                self.hits += 1
                return self._memory[key]
            if self._conn is not None:
                row = self._conn.execute(
                    'SELECT reply FROM replies WHERE key = ?', (key,)).fetchone()
                if row is not None:
                    value = json.loads(row[0])
                    self._memory[key] = value
                    self.hits += 1
                    return value
            self.misses += 1
            return None

    def put(self, key: str, reply: Any) -> None:
        try:
            blob = json.dumps(reply)
        except (TypeError, ValueError):
            return  # not storable; the call simply is not cached
        with self._lock:
            self._memory[key] = json.loads(blob)
            if self._conn is not None:
                try:
                    self._conn.execute(
                        'INSERT OR REPLACE INTO replies (key, reply) VALUES (?, ?)',
                        (key, blob))
                    self._conn.commit()
                except sqlite3.Error:
                    logger.exception('Could not store a cached label reply')

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {'hits': self.hits, 'misses': self.misses,
                    'hit_rate': self.hits / total if total else None,
                    'persistent': self._conn is not None}


class CachingEndpoint:
    """Wraps an endpoint so ``query()`` is answered from the cache when it can.

    Everything else is passed through, so the wrapper can stand in for the
    endpoint anywhere the labeler hands one on.
    """

    def __init__(self, endpoint, cache: LabelCache):
        self._endpoint = endpoint
        self._cache = cache

    def __getattr__(self, name):
        return getattr(self._endpoint, name)

    def query(self, prompt: str, output_format=None):
        key = cache_key(self._endpoint, prompt, output_format)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        reply = self._endpoint.query(prompt, output_format)
        stored = reply.model_dump() if hasattr(reply, 'model_dump') else reply
        if isinstance(stored, str):
            try:
                stored = json.loads(stored)
            except ValueError:
                stored = None
        # Only a reply that parsed is kept. An error message, a truncated
        # object or a run of whitespace would otherwise come back forever,
        # where the next call might have succeeded.
        if isinstance(stored, dict) and stored:
            self._cache.put(key, stored)
        return reply
