"""Think-Aloud session state: chunk ingestion, detection, transcripts, export.

Each (annotator, instance) pair is a *session*. Audio arrives in complete,
independently-decodable chunks; every chunk is transcribed, appended to the
session, and the label-phrase parser runs over a rolling window of the last
two chunks (phrases can straddle a chunk boundary). Last detection wins, so
annotators can change their mind mid-stream.

Persistence: ``{output_annotation_dir}/thinkaloud/transcripts.jsonl`` —
append-only, one record per chunk, replayed on startup.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from potato.thinkaloud.config import ThinkAloudConfig, parse_thinkaloud_config
from potato.thinkaloud.parser import LabelPhraseParser, count_fillers
from potato.thinkaloud.stt import STTBackend, create_stt

logger = logging.getLogger(__name__)


class ThinkAloudManager:
    """Singleton owning STT, sessions, and transcript persistence."""

    def __init__(self, app_config: Dict[str, Any]) -> None:
        self.app_config = app_config
        self.ta_config: ThinkAloudConfig = parse_thinkaloud_config(app_config)

        output_dir = app_config.get("output_annotation_dir", "annotation_output")
        self.storage_dir = os.path.join(output_dir, "thinkaloud")
        self._lock = threading.Lock()
        self._stt: Optional[STTBackend] = None

        labels = self._scheme_labels()
        self.parser = LabelPhraseParser(labels, stems=self.ta_config.stems) \
            if labels else None

        # (username, instance_id) -> list of chunk records (ordered by seq)
        self._sessions: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._load()

    # -------------------------------------------------------------- helpers --
    def _scheme_labels(self) -> List[str]:
        for scheme in self.app_config.get("annotation_schemes", []) or []:
            if scheme.get("name") != self.ta_config.schema:
                continue
            labels = []
            for label in scheme.get("labels", []) or []:
                if isinstance(label, dict):
                    if label.get("name"):
                        labels.append(str(label["name"]))
                else:
                    labels.append(str(label))
            return labels
        return []

    def get_stt(self) -> STTBackend:
        """Lazy backend creation so servers without audio use never load models."""
        if self._stt is None:
            self._stt = create_stt(self.ta_config.stt, model=self.ta_config.model,
                                   language=self.ta_config.language)
            logger.info("Think-Aloud STT backend ready: %s", self._stt.name)
        return self._stt

    # ------------------------------------------------------------------ io --
    def _path(self) -> str:
        return os.path.join(self.storage_dir, "transcripts.jsonl")

    def _load(self) -> None:
        path = self._path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        key = (record["username"], str(record["instance_id"]))
                        self._sessions.setdefault(key, []).append(record)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        logger.warning("Skipping malformed line in %s", path)
        except OSError:
            logger.exception("Failed reading %s", path)

    def _append(self, record: Dict[str, Any]) -> None:
        os.makedirs(self.storage_dir, exist_ok=True)
        with open(self._path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --------------------------------------------------------------- chunks --
    def ingest_chunk(self, username: str, instance_id: str, seq: int,
                     audio_bytes: Optional[bytes] = None,
                     text: Optional[str] = None,
                     mock_text: Optional[str] = None) -> Dict[str, Any]:
        """Transcribe (or accept) one chunk; run detection on a rolling window.

        Returns {text, detection, transcript} where detection covers the
        rolling window ending at this chunk (None if no phrase found).
        """
        if text is None:
            transcript_text = self.get_stt().transcribe(audio_bytes or b"",
                                                        mock_text=mock_text)
        else:
            transcript_text = text.strip()

        record = {
            "username": username,
            "instance_id": str(instance_id),
            "seq": int(seq),
            "text": transcript_text,
            "timestamp": time.time(),
        }
        key = (username, str(instance_id))
        with self._lock:
            chunks = self._sessions.setdefault(key, [])
            chunks.append(record)
            chunks.sort(key=lambda c: c["seq"])
            self._append(record)
            window = " ".join(c["text"] for c in chunks[-2:] if c["text"])
            full = " ".join(c["text"] for c in chunks if c["text"])

        detection = None
        if self.parser and window:
            hit = self.parser.parse(window)
            if hit:
                detection = {
                    "label": hit.label,
                    "matched_text": hit.matched_text,
                    "stem_text": hit.stem_text,
                    "confidence": hit.confidence,
                }
        return {"text": transcript_text, "detection": detection, "transcript": full}

    # ---------------------------------------------------------------- state --
    def get_session(self, username: str, instance_id: str) -> Dict[str, Any]:
        """Aggregated view of one session (for UI restore and export)."""
        key = (username, str(instance_id))
        with self._lock:
            chunks = list(self._sessions.get(key, []))
        full = " ".join(c["text"] for c in chunks if c["text"])
        detection = None
        if self.parser and full:
            hit = self.parser.parse(full)
            if hit:
                detection = {
                    "label": hit.label,
                    "matched_text": hit.matched_text,
                    "stem_text": hit.stem_text,
                    "confidence": hit.confidence,
                }
        silent = sum(1 for c in chunks if not c["text"])
        rationale = full
        if detection:
            # Rationale = transcript minus the committed label phrase
            phrase = f"{detection['stem_text']} {detection['matched_text']}"
            from potato.thinkaloud.parser import normalize
            rationale = normalize(full).replace(normalize(phrase), " ").strip()
        return {
            "username": username,
            "instance_id": str(instance_id),
            "n_chunks": len(chunks),
            "silent_chunks": silent,
            "transcript": full,
            "detection": detection,
            "rationale": rationale,
            "filler_count": count_fillers(full, self.ta_config.fillers),
            "duration_seconds": (
                round(chunks[-1]["timestamp"] - chunks[0]["timestamp"]
                      + self.ta_config.chunk_seconds, 1) if chunks else 0
            ),
        }

    def export_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            keys = sorted(self._sessions.keys())
        return [self.get_session(username, instance_id)
                for username, instance_id in keys]


# ----------------------------------------------------------------- singleton --
_manager: Optional[ThinkAloudManager] = None


def init_thinkaloud_manager(app_config: Dict[str, Any]) -> Optional[ThinkAloudManager]:
    global _manager
    if not (app_config.get("thinkaloud") or {}).get("enabled", False):
        _manager = None
        return None
    _manager = ThinkAloudManager(app_config)
    logger.info("Think-Aloud enabled (schema=%s, stt=%s)",
                _manager.ta_config.schema, _manager.ta_config.stt)
    return _manager


def get_thinkaloud_manager() -> Optional[ThinkAloudManager]:
    return _manager


def clear_thinkaloud_manager() -> None:
    global _manager
    _manager = None
