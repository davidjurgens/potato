"""Singleton manager for dataset publishing.

Publishing (especially a Hub push or a Zenodo deposition) can be slow, so the
manager runs it on a daemon thread and exposes a lock-guarded status dict the admin
UI polls — the same pattern as ``corpus_map``. Previewing (pipeline + card, no
upload) is synchronous and cheap.

The manager reads the project's config file path from ``config["__config_file__"]``
so it can rebuild the export context on demand.
"""

import logging
import os
import tempfile
import threading
import traceback
from typing import Any, Dict, Optional

from potato.publish.config import PublishConfig
from potato.publish.dataset_card import generate_dataset_card
from potato.publish.preprocessing import run_pipeline

logger = logging.getLogger(__name__)

_PUBLISH_MANAGER: Optional["PublishManager"] = None
_PUBLISH_LOCK = threading.Lock()


class PublishManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.publish_config = PublishConfig.from_config(self.config)
        self._lock = threading.RLock()
        self._status: Dict[str, Any] = {
            "state": "idle",      # idle | running | success | error
            "step": "",
            "target": "",
            "result": None,
            "warnings": [],
            "errors": [],
        }
        # Last archive produced, for the download endpoint.
        self._last_archive: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    # ---- config -----------------------------------------------------------

    def _config_path(self) -> str:
        path = self.config.get("__config_file__")
        if not path:
            # Fall back to the live server's global config, which always carries
            # the resolved config file path.
            try:
                from potato.flask_server import config as global_config
                path = global_config.get("__config_file__")
                if path and not self.config.get("__config_file__"):
                    self.config = global_config
                    self.publish_config = PublishConfig.from_config(global_config)
            except Exception:
                path = None
        if not path:
            raise RuntimeError("Config file path unavailable; cannot publish.")
        return path

    def defaults(self) -> Dict[str, Any]:
        """Config-derived defaults for the wizard form."""
        md = self.publish_config.metadata
        return {
            "default_target": self.publish_config.default_target,
            "options": self.publish_config.options,
            "metadata": {
                "pretty_name": md.pretty_name,
                "description": md.description,
                "license": md.license,
                "version": md.version,
                "keywords": md.keywords,
                "authors": [a.__dict__ for a in md.authors],
                "citation": md.citation,
            },
        }

    # ---- preview (synchronous) --------------------------------------------

    def preview(self, options: Optional[dict], metadata: Optional[dict],
                target: str = "archive") -> Dict[str, Any]:
        bundle = run_pipeline(self._config_path(), options=options,
                              metadata_overrides=metadata,
                              publish_config=self.publish_config)
        card = generate_dataset_card(bundle, target=target)
        return {
            "card_markdown": card,
            "splits": bundle.split_row_counts(),
            "warnings": bundle.warnings,
        }

    # ---- publish (background) ---------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def is_running(self) -> bool:
        with self._lock:
            return self._status["state"] == "running"

    def start_publish(self, options: Optional[dict], metadata: Optional[dict],
                      target: str, credentials: Optional[dict]) -> Dict[str, Any]:
        with self._lock:
            if self._status["state"] == "running":
                return {"started": False, "error": "A publish job is already running."}
            self._status = {"state": "running", "step": "starting",
                            "target": target, "result": None,
                            "warnings": [], "errors": []}
        self._thread = threading.Thread(
            target=self._run, args=(options, metadata, target, credentials or {}),
            daemon=True)
        self._thread.start()
        return {"started": True}

    def _set(self, **kw):
        with self._lock:
            self._status.update(kw)

    def _run(self, options, metadata, target, credentials):
        try:
            self._set(step="preprocessing")
            bundle = run_pipeline(self._config_path(), options=options,
                                  metadata_overrides=metadata,
                                  publish_config=self.publish_config)
            self._set(step="generating dataset card")
            bundle.card_markdown = generate_dataset_card(
                bundle, repo_id=credentials.get("repo_id", ""), target=target)

            self._set(step=f"publishing to {target}")
            result = self._dispatch(target, bundle, credentials, options)

            with self._lock:
                self._status.update(state="success", step="done", result=result,
                                    warnings=bundle.warnings)
        except Exception as e:                       # surface any failure to the UI
            logger.exception("Publish job failed")
            self._set(state="error", step="failed",
                      errors=[str(e)],
                      result={"traceback": traceback.format_exc()})

    def _dispatch(self, target, bundle, credentials, options) -> Dict[str, Any]:
        from potato.publish import targets as tgt
        data_format = str((options or {}).get("data_format", "jsonl"))
        if target == "huggingface":
            return tgt.push_to_huggingface(
                bundle, repo_id=credentials.get("repo_id", ""),
                token=credentials.get("token"),
                private=bool(credentials.get("private", False)))
        if target == "zenodo":
            return tgt.deposit_to_zenodo(
                bundle, token=credentials.get("token"),
                sandbox=bool(credentials.get("sandbox", True)),
                publish=bool(credentials.get("publish", False)))
        # default: local archive
        out_dir = os.path.join(
            self.config.get("output_annotation_dir", tempfile.gettempdir()),
            "publish")
        os.makedirs(out_dir, exist_ok=True)
        name = (bundle.metadata.pretty_name or "dataset").replace("/", "_") \
            .replace(" ", "_") or "dataset"
        archive = tgt.write_archive(
            bundle, os.path.join(out_dir, name),
            archive_format=str(credentials.get("archive_format", "zip")),
            data_format=data_format)
        with self._lock:
            self._last_archive = archive
        return {"archive_path": archive,
                "archive_name": os.path.basename(archive),
                "download_url": "/admin/publish/api/download"}

    def last_archive(self) -> Optional[str]:
        with self._lock:
            return self._last_archive


def init_publish_manager(config: Dict[str, Any]) -> "PublishManager":
    global _PUBLISH_MANAGER
    with _PUBLISH_LOCK:
        if _PUBLISH_MANAGER is None:
            _PUBLISH_MANAGER = PublishManager(config)
    return _PUBLISH_MANAGER


def get_publish_manager() -> Optional["PublishManager"]:
    return _PUBLISH_MANAGER


def clear_publish_manager() -> None:
    global _PUBLISH_MANAGER
    with _PUBLISH_LOCK:
        _PUBLISH_MANAGER = None
