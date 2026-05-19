"""
Schema-loader codebook bridge.

When an annotation scheme opts in with ``codebook: true``, its label
list is sourced from the project's mutable codebook instead of (only)
the static YAML ``labels``. Applied once at server start, before
front-end generation, so every downstream generator
(radio/multiselect/span/hierarchical_multiselect) keeps reading
``scheme["labels"]`` unchanged.

Legacy preservation: a config's existing YAML ``labels`` seed the
codebook the first time (so old configs keep working and the codebook
starts populated); thereafter the database is the source of truth.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from potato.codebook import create_code
from potato.codebook.codebook import Codebook
from potato.codebook.service import DuplicateCodeError

logger = logging.getLogger(__name__)


def _label_name(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("name") or entry.get("label") or "").strip()
    return str(entry).strip()


def _project_of(config: Dict[str, Any]) -> str:
    return config.get("annotation_task_name") or "default"


def _seed_from_yaml(
    task_dir: str, project: str, yaml_labels: List[Any]
) -> None:
    for entry in yaml_labels or []:
        name = _label_name(entry)
        if not name:
            continue
        try:
            create_code(
                task_dir, project=project, name=name,
                created_by="config")
        except DuplicateCodeError:
            pass  # idempotent: re-seeding an existing code is fine


def apply_codebook_to_schemes(config: Dict[str, Any]) -> None:
    """Mutate ``config['annotation_schemes']`` in place: for every
    scheme with ``codebook: true``, point ``labels`` at the codebook
    (seeding it from the scheme's YAML labels on first run)."""
    schemes = config.get("annotation_schemes") or []
    task_dir = config.get("task_dir", ".")
    project = _project_of(config)

    for scheme in schemes:
        if not isinstance(scheme, dict) or not scheme.get("codebook"):
            continue

        cb = Codebook.load(task_dir, project)
        if cb.is_empty():
            _seed_from_yaml(task_dir, project, scheme.get("labels"))
            cb = Codebook.load(task_dir, project)

        names = cb.labels()
        if names:
            scheme["labels"] = names
            logger.info(
                "Codebook bridge: scheme %r now sources %d label(s) "
                "from the project codebook",
                scheme.get("name"), len(names))


def _icl_sync_listener(task_dir: str, project: str) -> None:
    """Codebook change listener: refresh the *live* server config's
    scheme labels so ICL prompts (built fresh from ``schema['labels']``
    each call) are restricted to the codebook's current set. Refreshing
    the source the prompt is built from *is* the prompt-cache
    invalidation — there is no separate persistent ICL prompt cache.
    """
    try:
        from potato.server_utils import config_module
        cfg = config_module.config
    except Exception:
        return
    if not cfg:
        return
    if (cfg.get("annotation_task_name") or "default") != project:
        return
    apply_codebook_to_schemes(cfg)


def install_codebook_icl_sync() -> None:
    """Register the ICL-sync listener (idempotent). Called at server
    init alongside the other mode initializers."""
    from potato.codebook.service import register_change_listener
    register_change_listener(_icl_sync_listener)
