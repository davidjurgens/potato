"""
Saved annotations <-> codebook links.

An annotation on a ``codebook: true`` scheme is saved twice over: as the
label string in the coder's user state (what the form restores and the
export reads), and as an ``annotation_codes`` link to the code's id
(what merge / split / restamp read). This module keeps the two in step:

- on save, the coder's links on the instance are set from the names
  they saved (``sync_saved_annotation``);
- before a retroactive op, codings saved before links were written are
  linked (``backfill_links``);
- after a merge / split / rename, the saved names are rewritten to the
  code they now belong to (``relabel_saved``).

The last two run inside the codebook service, which has no request and
may be called on a task_dir the server is not serving (unit tests, the
CLI). They act only when the live config serves the same task_dir and
project; otherwise they do nothing.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from potato.codebook import store
from potato.codebook.codebook import Codebook

logger = logging.getLogger(__name__)

# Values that mean "not selected" rather than an answer. The legacy v1
# template posts unticked boxes as {name: false}.
_UNSELECTED = (None, False, "", "false")


def codebook_scheme_names(config: Dict[str, Any]) -> Set[str]:
    return {s.get("name") for s in (config.get("annotation_schemes") or [])
            if isinstance(s, dict) and s.get("codebook") and s.get("name")}


#: How codebook.js names a runtime option's element id; before the fix its
#: label_name was this too, so codings saved then carry it as their name.
RUNTIME_PREFIX = "__cb__"


def _slug(name: str) -> str:
    """codebook.js ``slug()``: every character outside [A-Za-z0-9_-] as _."""
    import re
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(name))


def normalize_runtime_names(user_state, instance_id: str, scheme_names: Set[str],
                            code_names: Iterable[str]) -> bool:
    """Rename codings saved under a runtime option's id
    (``<schema>__cb__<slug>``) to the code's own name; True when any was.

    A saved name that is itself a code is left alone, and so is one whose
    slug two codes share ("Gam ma" and "Gam_ma"): there is no telling which
    of them it meant."""
    code_names = set(code_names)
    by_slug: Dict[str, Set[str]] = {}
    for name in code_names:
        by_slug.setdefault(_slug(name), set()).add(name)
    changed = False
    labels = user_state.get_label_annotations(instance_id) or {}
    for label in list(labels):
        schema = label.get_schema() if getattr(label, "get_schema", None) else None
        if schema not in scheme_names:
            continue
        prefix = schema + RUNTIME_PREFIX
        name = label.get_name()
        if not name.startswith(prefix) or name in code_names:
            continue
        matches = by_slug.get(name[len(prefix):]) or set()
        if len(matches) > 1:
            logger.warning("Saved coding %r matches codes %s; left as saved",
                           name, sorted(matches))
            continue
        if matches and _rename_in_state(user_state, instance_id, {schema},
                                        name, next(iter(matches))):
            changed = True
    return changed


def _current_name(changes, name: str, username: str,
                  name_to_id: Dict[str, str], task_dir: str) -> Optional[str]:
    """The live code a retired name now belongs to, by the change log: a
    rename keeps the code, a merge moves to its target, and a split moves
    only the split annotator's codings. None when the log does not say."""
    def successor(match):
        hits = [c for c in changes if match(c) and (
            c["op"] in ("rename", "merge")
            or (c["op"] == "split"
                and str(c.get("new_value") or "").endswith(" [%s]" % username)))]
        if not hits:
            return None
        last = hits[-1]
        return last["code_id"] if last["op"] == "rename" else last["related_code_id"]

    code_id = successor(lambda c: c.get("old_value") == name)
    for _ in range(len(changes) + 1):
        if not code_id:
            return None
        code = store.get_code(task_dir, code_id)
        if code and name_to_id.get(code["name"]) == code_id:
            return code["name"]
        # Merged or split away since: follow the code, not its old name.
        code_id = successor(lambda c, cid=code_id: c.get("code_id") == cid
                            and c["op"] != "rename")
    return None


def map_retired_names(user_state, instance_id: str, scheme_names: Set[str],
                      name_to_id: Dict[str, str], username: str,
                      task_dir: str, project: str) -> bool:
    """Move codings saved under a code name that no longer exists to the
    code it was renamed, merged or split into. A page opened before the
    change still has the old name ticked, and its next save would write
    it back as a coding with no code. True when any was moved."""
    retired = saved_code_names(user_state, instance_id, scheme_names) - set(name_to_id)
    if not retired:
        return False
    from potato.codebook import changelog
    changes = changelog.all_changes(task_dir, project)
    changed = False
    for name in sorted(retired):
        current = _current_name(changes, name, username, name_to_id, task_dir)
        if current and _rename_in_state(user_state, instance_id, scheme_names,
                                        name, current):
            changed = True
    return changed


def saved_code_names(user_state, instance_id: str,
                     scheme_names: Set[str]) -> Set[str]:
    """Label and span names this coder saved on the instance under a
    codebook-backed scheme."""
    names: Set[str] = set()
    labels = user_state.get_label_annotations(instance_id) or {}
    for label, value in labels.items():
        if (getattr(label, "get_schema", None)
                and label.get_schema() in scheme_names
                and value not in _UNSELECTED):
            names.add(label.get_name())
    spans = user_state.get_span_annotations(instance_id) or {}
    for span in spans:
        if getattr(span, "get_schema", None) and span.get_schema() in scheme_names:
            names.add(span.get_name())
    return names


def sync_saved_annotation(config: Dict[str, Any], user_state,
                          instance_id: str, username: str) -> None:
    """Set the coder's live links on `instance_id` from what they saved."""
    schemes = codebook_scheme_names(config)
    if not schemes:
        return
    from potato.codebook.service import sync_annotation_links
    task_dir = config.get("task_dir", ".")
    project = config.get("annotation_task_name") or "default"
    name_to_id = Codebook.load(task_dir, project).label_to_id()
    renamed = normalize_runtime_names(user_state, instance_id, schemes, name_to_id)
    renamed = map_retired_names(user_state, instance_id, schemes, name_to_id,
                                username, task_dir, project) or renamed
    if renamed:
        # The save that called this may already have written the state.
        try:
            from potato.user_state_management import get_user_state_manager
            get_user_state_manager().save_user_state(user_state)
        except Exception:  # noqa: BLE001 - the next save writes it
            logger.debug("Could not save the renamed codings", exc_info=True)
    names = saved_code_names(user_state, instance_id, schemes)
    sync_annotation_links(
        task_dir, project=project, instance_id=instance_id,
        username=username,
        code_ids={name_to_id[n] for n in names if n in name_to_id})


def _live_context(task_dir: str, project: str) -> Optional[Tuple[set, Any]]:
    """(codebook scheme names, user state manager) when the running
    server serves this task_dir and project, else None."""
    try:
        from potato.server_utils.config_module import config
        from potato.user_state_management import get_user_state_manager
    except Exception:
        return None
    if not config:
        return None
    if (config.get("annotation_task_name") or "default") != project:
        return None
    if (os.path.realpath(config.get("task_dir", "."))
            != os.path.realpath(task_dir)):
        return None
    schemes = codebook_scheme_names(config)
    if not schemes:
        return None
    try:
        usm = get_user_state_manager()
    except ValueError:
        return None
    return schemes, usm


def backfill_links(task_dir: str, project: str, code_id: str) -> int:
    """Link every saved coding of `code_id` that has no live link yet.
    Returns the number of links written."""
    ctx = _live_context(task_dir, project)
    if ctx is None:
        return 0
    schemes, usm = ctx
    code = store.get_code(task_dir, code_id)
    if code is None:
        return 0
    name = code["name"]
    # Two codes can share a name under different parents; a saved name
    # belongs to the one the save path maps it to.
    if Codebook.load(task_dir, project).label_to_id().get(name) != code_id:
        return 0
    written = 0
    code_names = list(Codebook.load(task_dir, project).label_to_id())
    for user_state in usm.get_all_users():
        username = user_state.get_user_id()
        renamed = False
        for iid in list(user_state.get_annotated_instance_ids()):
            renamed = normalize_runtime_names(user_state, iid, schemes,
                                              code_names) or renamed
            if name not in saved_code_names(user_state, iid, schemes):
                continue
            key = store.annotation_key(iid, username)
            if code_id in store.live_code_ids(task_dir, key):
                continue
            store.set_link_live(
                task_dir, project=project, annotation_id=key,
                code_id=code_id, created_by=username)
            written += 1
        if renamed:
            usm.save_user_state(user_state)
    return written


def _rename_in_state(user_state, instance_id: str, schemes: Set[str],
                     old_name: str, new_name: str) -> bool:
    from potato.item_state_management import Label
    changed = False
    # Both accessors return the live containers, so editing them in place
    # edits the state that save_user_state writes.
    labels = user_state.get_label_annotations(instance_id) or {}
    for label in [k for k in labels
                  if getattr(k, "get_schema", None)
                  and k.get_schema() in schemes
                  and k.get_name() == old_name]:
        value = labels.pop(label)
        renamed = Label(label.get_schema(), new_name)
        # A coder who already had the target keeps it as it was.
        if renamed not in labels:
            labels[renamed] = new_name if value == old_name else value
        changed = True
    spans = user_state.get_span_annotations(instance_id) or {}
    for span in [s for s in spans
                 if getattr(s, "get_schema", None)
                 and s.get_schema() in schemes
                 and s.get_name() == old_name]:
        # The name is part of the span's hash: take it out, rename it,
        # put it back.
        value = spans.pop(span)
        span.name = new_name
        if span.title == old_name:
            span.title = new_name
        spans[span] = value
        changed = True
    return changed


def relabel_saved(task_dir: str, project: str,
                  annotation_ids: Iterable[str],
                  old_name: str, new_name: str) -> int:
    """Rewrite `old_name` to `new_name` in the saved state of each coder
    behind `annotation_ids`. Returns the number of codings rewritten."""
    ctx = _live_context(task_dir, project)
    if ctx is None:
        return 0
    schemes, usm = ctx
    rewritten = 0
    touched = {}
    for aid in annotation_ids:
        iid, username = store.split_annotation_key(aid)
        if username is None:
            continue  # a legacy key does not say whose state to edit
        user_state = usm.get_user_state(username)
        if user_state is None:
            continue
        if _rename_in_state(user_state, iid, schemes, old_name, new_name):
            rewritten += 1
            touched[username] = user_state
    for user_state in touched.values():
        usm.save_user_state(user_state)
    return rewritten
