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
import uuid
from typing import Any, Dict, List, Optional

from potato.codebook import create_code, store
from potato.codebook.codebook import Codebook
from potato.codebook.service import DuplicateCodeError
from potato.codebook.store import ROOT

logger = logging.getLogger(__name__)


def _label_name(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("name") or entry.get("label") or "").strip()
    return str(entry).strip()


def _label_color(entry: Any) -> str:
    """A label's configured colour, so the codebook's dot matches the
    chip the annotator sees on the form."""
    if isinstance(entry, dict):
        return str(entry.get("color") or "").strip() or None
    return None


def _label_gloss(entry: Any) -> str:
    """A label's prose, in the order an author is likely to have written
    it. `tooltip` is the documented per-label help text; `description` is
    what authors reach for anyway, and neither used to reach the
    codebook, so a code seeded from a fully-described config still read
    "No content yet"."""
    if not isinstance(entry, dict):
        return ""
    for key in ("description", "tooltip"):
        text = entry.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _seed_gloss(task_dir: str, project: str, code_id: str,
                gloss: str) -> None:
    """Write a config label's prose in as the code's short definition.
    Only ever called for a code this bootstrap just created, and only
    when its content scope is untouched (base_version 0), so it can
    never overwrite a researcher's own wording."""
    from potato.codebook import content_service
    try:
        content_service.save_scope(
            task_dir, project=project, scope_kind="code", scope_id=code_id,
            blocks_in=[{"block_type": "short_def", "body_md": gloss}],
            base_version=0, actor="config", actor_kind="config", minor=True)
    except Exception:
        # A codebook whose codes carry no definitions is still a working
        # codebook; never let seeding prose break server start.
        logger.exception(
            "codebook seed: could not write a definition for code %s",
            code_id)


def _project_of(config: Dict[str, Any]) -> str:
    return config.get("annotation_task_name") or "default"


def _label_details(entry: Any) -> Dict[str, Any]:
    """Structured codebook-prompting fields from a dict label entry."""
    from potato.codebook.store import RICH_FIELDS
    if not isinstance(entry, dict):
        return {}
    return {f: entry[f] for f in RICH_FIELDS if f in entry}


# Stable namespace so ids are reproducible across machines/runs.
_NS = uuid.UUID("6b9b1f6e-1c2d-5a4b-9e3f-c0deb00c0de5")


def deterministic_code_id(project: str, parent_id: str, name: str) -> str:
    """``uuid5`` over project | parent | name: the same config yields the
    same code ids on every machine, whether the server or
    ``potato codebook`` seeded them."""
    return uuid.uuid5(_NS, f"{project}\x1f{parent_id}\x1f{name}").hex


def seed_label(task_dir: str, project: str, entry: Any, *,
               created_by: str) -> Optional[Dict[str, Any]]:
    """Create the code for one YAML label: its deterministic id, colour
    and definition. The one seeding path for the server and the CLI --
    the CLI used to create bare names, and the server then skipped
    seeding because the codebook was no longer empty, so a project
    initialised from the CLI never got its configured colours or
    descriptions.

    Returns the new code, or None when the entry has no name or the code
    already exists (seeding is idempotent)."""
    name = _label_name(entry)
    if not name:
        return None
    code_id = deterministic_code_id(project, ROOT, name)
    # A code that was seeded and since renamed still holds this id; it is
    # the researcher's now, and inserting again would collide on it.
    if store.get_code(task_dir, code_id) is not None:
        return None
    try:
        code = create_code(
            task_dir, project=project, name=name, created_by=created_by,
            color=_label_color(entry), code_id=code_id,
            details=_label_details(entry))
    except DuplicateCodeError:
        return None
    gloss = _label_gloss(entry)
    if gloss:
        _seed_gloss(task_dir, project, code["id"], gloss)
    return code


def _seed_from_yaml(
    task_dir: str, project: str, yaml_labels: List[Any]
) -> None:
    for entry in yaml_labels or []:
        seed_label(task_dir, project, entry, created_by="config")


def apply_codebook_to_schemes(config: Dict[str, Any],
                              task_dir: str = None,
                              seed: bool = True) -> None:
    """Mutate ``config['annotation_schemes']`` in place: for every
    scheme with ``codebook: true``, point ``labels`` at the codebook
    (seeding it from every codebook-backed scheme's YAML labels on first
    run).

    ``task_dir`` overrides ``config['task_dir']``, which is relative to the
    config file rather than to the process's cwd -- an export run from
    anywhere else has to resolve it first. ``seed=False`` suppresses the
    first-run bootstrap for read-only callers, so opening an export never
    writes codes into a project.
    """
    schemes = config.get("annotation_schemes") or []
    if task_dir is None:
        task_dir = config.get("task_dir", ".")
    project = _project_of(config)

    codebook_schemes = [s for s in schemes
                        if isinstance(s, dict) and s.get("codebook")]
    if not codebook_schemes:
        return

    # Seed from EVERY codebook-backed scheme, not just whichever comes first.
    # They share one codebook, so once the first scheme seeded it the
    # `is_empty()` gate closed and every later scheme's own labels were
    # dropped on the floor -- a label declared only on a later scheme never
    # entered the codebook and so rendered nowhere at all. Still gated on
    # `is_empty()`: seeding is a first-run bootstrap, and re-seeding a
    # curated codebook would resurrect codes the researcher deleted.
    cb = Codebook.load(task_dir, project)
    if seed and cb.is_empty():
        for scheme in codebook_schemes:
            _seed_from_yaml(task_dir, project, scheme.get("labels"))
        cb = Codebook.load(task_dir, project)

    names = cb.labels()
    for scheme in codebook_schemes:
        if names:
            scheme["labels"] = names
            logger.info(
                "Codebook bridge: scheme %r now sources %d label(s) "
                "from the project codebook",
                scheme.get("name"), len(names))

        # Distill the living-document content into model guidance and
        # stash it on the scheme so the ICL/judge prompt builder can append
        # it without importing the codebook. Refreshed on every codebook
        # change because this function is the change listener.
        try:
            from potato.codebook.distiller import distill_for_config
            guidance = distill_for_config(config)
            scheme["codebook_guidance"] = guidance
        except Exception:  # never let distillation break label sync
            logger.exception("codebook distillation failed; skipping")

        # Pre-render the structured codebook block (definitions / include
        # / exclude / examples) onto the scheme so the ICL prompt builder
        # can inject it without touching the DB. "" when no code carries
        # structured fields. Refreshed on every codebook change via the
        # ICL-sync listener below.
        from potato.codebook.prompt import render_from_codebook
        scheme["codebook_prompt"] = render_from_codebook(cb)


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
