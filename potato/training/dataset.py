"""Turning a project's annotations into a training bundle.

A bundle is a directory a trainer can read on its own: split files, a label
vocabulary, symlinked media, and a manifest describing all of it. Nothing in a
bundle refers back to Potato, which is what lets the same directory be handed
to a subprocess on this machine or downloaded by a training rig somewhere else.

Almost none of the work here is new. Loading annotations, normalizing the two
label encodings, splitting spans by schema and parsing geometry blobs is
``export.cli.load_annotations_from_output_dir``; resolving disagreement between
annotators is ``eval_datasets.annotation_aggregation``; assigning splits is
``publish.preprocessing._partition_splits``. This module is the wiring.

The one thing it does insist on is **stable splits**. Split membership is a
seeded hash of the instance id, so an item that was held out in round one is
held out in round two. Reshuffling between rounds moves validation items into
training and every metric after that is measuring memorization.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from potato.training import rasters, tiling
from potato.training.base import BundleRef, SchemaSpec, TrainerError

logger = logging.getLogger(__name__)

#: Scheme types whose ``source_field`` names a text field, not a media file.
#: Looked up as media, every gloss item counted as missing media.
TEXT_SOURCE_TYPES = frozenset({"interlinear_gloss", "error_span", "text_edit", "cloze"})

__all__ = [
    "DEFAULT_SPLITS",
    "BundleStats",
    "build_bundle",
    "schema_specs_from_config",
    "detect_modality",
    "guess_modality",
]

#: Default split fractions. Deliberately includes a test set even for small
#: projects: a val set used for both model selection and reporting stops being
#: held out the moment anyone tunes against it.
DEFAULT_SPLITS = {"train": 0.7, "val": 0.15, "test": 0.15}

#: Item fields that name a media file, in the order they are looked for.
_MEDIA_KEYS = ("image_url", "image", "image_path", "file_name", "audio_url",
               "audio", "audio_path", "video_url", "video", "video_path",
               "url", "path")

_MODALITY_BY_TYPE = {
    "image_annotation": "image",
    "region_caption": "image",
    "grounding_eval": "image",
    "microscopy": "image",
    "geo_annotation": "image",
    "gui_trajectory": "image",
    "audio_annotation": "audio",
    "video_annotation": "video",
    "tiered_annotation": "audio",
    "spatial_annotation": "point_cloud",
    "episode_annotation": "video",
}


class BundleStats:
    """Counts worth surfacing after a build."""

    def __init__(self):
        self.n_items = 0
        self.n_annotated = 0
        self.n_skipped_no_label = 0
        self.n_media_linked = 0
        self.n_media_missing = 0
        #: Of the missing, files outside the task and media directories.
        self.n_media_outside = 0
        self.splits: Dict[str, int] = {}
        #: Per reason, items put in train whatever their hash split said, and
        #: how many of those the hash had held out.
        self.forced_train: Dict[str, Dict[str, int]] = {}
        #: Images cut into tiles, and how many tiles they made.
        self.tiles: Dict[str, int] = {}
        self.warnings: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {"n_items": self.n_items, "n_annotated": self.n_annotated,
                "n_skipped_no_label": self.n_skipped_no_label,
                "n_media_linked": self.n_media_linked,
                "n_media_missing": self.n_media_missing,
                "n_media_outside": self.n_media_outside,
                "splits": dict(self.splits),
                "forced_train": {k: dict(v) for k, v in self.forced_train.items()},
                "tiles": dict(self.tiles),
                "warnings": list(self.warnings)}


_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".gif",
                   # Whole-slide formats (openslide), cut into tiles at bundle time.
                   ".svs", ".ndpi", ".mrxs", ".scn", ".vms", ".vmu", ".bif", ".svslide")


def detect_modality(schemes: Sequence[Dict[str, Any]],
                    rows: Optional[Sequence[Dict[str, Any]]] = None) -> str:
    """What kind of corpus this is, from the schemes being trained and, for a
    classification scheme, from what its items show.

    Text is the default because it is both the common case and the harmless
    one: a text trainer handed an image path fails loudly at fit time, whereas
    an image trainer handed text tries to open a sentence as a file. A radio
    or multiselect scheme over images is an image classifier, though: when
    most labelled rows name an image file, the corpus is images.
    """
    for scheme in schemes:
        modality = _MODALITY_BY_TYPE.get(scheme.get("annotation_type", ""))
        if modality:
            return modality
    if rows:
        def image_ref(row):
            ref = str(row.get("media") or row.get("media_missing") or "")
            if not ref.lower().split("?")[0].endswith(_IMAGE_SUFFIXES):
                return False
            if ref.startswith(("http://", "https://")):
                # A remote image counts only when the item shows nothing else:
                # a text item that carries an image_url is a text item, and
                # its images cannot be read from disk anyway.
                text = str(row.get("text") or "").strip()
                return not text or text == ref
            return True
        if sum(1 for r in rows if image_ref(r)) >= 0.8 * len(rows):
            return "image"
    return "text"


def guess_modality(config: Dict[str, Any], scheme: Dict[str, Any],
                   items: Sequence[Dict[str, Any]]) -> str:
    """What a bundle for *scheme* would be, from a sample of item data.

    The same rule :func:`build_bundle` applies, run before any bundle
    exists, so the start form can offer image trainers for an image project
    and text trainers for a text one.
    """
    text_key = (config.get("item_properties", {}) or {}).get("text_key", "text")
    rows = []
    for data in items:
        if not isinstance(data, dict):
            continue
        reference = _media_reference(data, scheme.get("source_field"))
        row = {"text": str(data.get(text_key, "") or "")}
        if reference:
            row["media"] = reference
        rows.append(row)
    return detect_modality([scheme], rows)


def schema_specs_from_config(config: Dict[str, Any],
                             schema_names: Sequence[str],
                             label_index: Optional[Dict[str, List[str]]] = None
                             ) -> Tuple[SchemaSpec, ...]:
    """Build ``SchemaSpec``s for the named schemes.

    Labels come from *label_index* (observed in the data) when given, and from
    the config's declared labels otherwise. Observed wins because a label
    declared but never used would become a class the model can never predict
    and every metric would be averaged over it.
    """
    from potato.training.registry import kind_of_schema

    by_name = {s["name"]: s for s in config.get("annotation_schemes", [])
               if s.get("name")}
    specs = []
    for name in schema_names:
        scheme = by_name.get(name)
        if scheme is None:
            raise TrainerError("No annotation scheme named %r in this config"
                               % name)
        labels = (label_index or {}).get(name)
        if labels is None:
            labels = [str(lab.get("name", lab) if isinstance(lab, dict) else lab)
                      for lab in (scheme.get("labels") or [])]
        specs.append(SchemaSpec(
            name=name,
            annotation_type=scheme.get("annotation_type", ""),
            kind=kind_of_schema(scheme),
            labels=tuple(labels),
            source_field=scheme.get("source_field"),
            description=str(scheme.get("description") or "")))
    return tuple(specs)


def _annotation_index(annotations: Sequence[Dict[str, Any]],
                      schemes: Sequence[Dict[str, Any]] = ()
                      ) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], List[str]]:
    """``{(user, instance): {scheme: value_map}}`` plus the annotator list.

    ``load_annotations_from_output_dir`` hands back a flat list of per-user,
    per-instance records; the aggregators want a lookup. Spans are folded in
    under their schema so a span scheme aggregates like any other.

    A structured scheme among *schemes* (links, chains, events, soft labels,
    glosses, conversation trees) is stored as ``{"_structured": answer}``,
    the annotator's answer in the canonical form of
    :mod:`potato.training.structured`, so that two annotators who gave the
    same answer agree in the vote.
    """
    from potato.training.registry import kind_of_schema
    from potato.training.structured import (LINK_KINDS, STRUCTURED_KINDS,
                                            canonical_answer, span_schema_of)
    structured = [(s, kind_of_schema(s)) for s in schemes or ()
                  if s.get("name")]
    structured = [(s, k) for s, k in structured if k in STRUCTURED_KINDS]

    index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    users: List[str] = []

    for record in annotations:
        user = str(record.get("user_id", ""))
        iid = str(record.get("instance_id", ""))
        if not user or not iid:
            continue
        if user not in index and user not in users:
            users.append(user)

        by_scheme: Dict[str, Any] = {}
        for scheme, value_map in (record.get("labels") or {}).items():
            by_scheme[scheme] = value_map
        for scheme, spans in (record.get("spans") or {}).items():
            by_scheme[scheme] = {"_spans": spans}
        for scheme, objects in (record.get("image_annotations") or {}).items():
            by_scheme[scheme] = {"_objects": objects}

        for scheme, kind in structured:
            name = scheme["name"]
            if kind in LINK_KINDS:
                answer = canonical_answer(
                    kind, scheme,
                    spans=(record.get("spans") or {}).get(span_schema_of(scheme)),
                    links=(record.get("links") or {}).get(name),
                    events=(record.get("events") or {}).get(name))
            else:
                answer = canonical_answer(kind, scheme, by_scheme.get(name))
            if answer is None:
                by_scheme.pop(name, None)
            else:
                by_scheme[name] = {"_structured": answer}

        if by_scheme:
            index[(user, iid)] = by_scheme

    return index, users


def _resolve_labels(annotations: Sequence[Dict[str, Any]],
                    instance_ids: Sequence[str],
                    aggregation: str = "consensus",
                    schemes: Sequence[Dict[str, Any]] = ()
                    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """One agreed answer per instance.

    Dawid-Skene by default rather than majority vote: it estimates each
    annotator's reliability and weights their votes by it, so one careless
    annotator does not get equal say. Both implementations already exist in
    ``eval_datasets.annotation_aggregation`` and are tested there.
    """
    index, users = _annotation_index(annotations, schemes)

    def get_user_annotations(user: str, iid: str) -> Dict[str, Any]:
        return index.get((str(user), str(iid)), {})

    ids = [str(i) for i in instance_ids]

    if aggregation == "consensus" and len(users) > 1:
        try:
            from potato.eval_datasets.annotation_aggregation import (
                consensus_reference_outputs)
            references, meta = consensus_reference_outputs(
                ids, users, get_user_annotations)
            return {str(k): v for k, v in references.items()}, meta
        except Exception:
            logger.warning("Dawid-Skene consensus failed; falling back to "
                           "majority vote", exc_info=True)

    from potato.eval_datasets.annotation_aggregation import (
        aggregate_instance_annotations)

    references: Dict[str, Dict[str, Any]] = {}
    votes: Dict[str, Any] = {}
    for iid in ids:
        resolved, meta = aggregate_instance_annotations(
            iid, users, get_user_annotations)
        if resolved:
            references[iid] = resolved
            votes[iid] = meta
    return references, {"aggregation": "majority", "per_instance": votes}


def _label_of(value_map: Any) -> Optional[str]:
    """The single label a classification value map represents.

    Potato stores ``{label_name: value}`` with the selected option's value
    truthy, which is one encoding; a bare scalar is another. Both appear in
    real output directories.
    """
    if isinstance(value_map, str):
        return value_map
    if not isinstance(value_map, dict):
        return None if value_map is None else str(value_map)

    chosen = [name for name, value in value_map.items()
              if value not in (None, "", False, 0, "false")]
    if len(chosen) == 1:
        return str(chosen[0])
    if not chosen:
        return None
    # Several set: multilabel, handled by the caller.
    return None


def _labels_of(value_map: Any) -> List[str]:
    """Every label set in a value map, for a multilabel scheme."""
    if isinstance(value_map, str):
        return [value_map]
    if not isinstance(value_map, dict):
        return []
    return [str(name) for name, value in value_map.items()
            if value not in (None, "", False, 0, "false")]


def _target_for(spec: SchemaSpec, value_map: Any,
                scheme: Optional[Dict[str, Any]] = None) -> Any:
    """The training target for one schema kind."""
    scheme = scheme or {"annotation_type": spec.annotation_type,
                        "name": spec.name}
    if spec.kind == "temporal":
        from potato.server_utils.annotation_values import temporal_segments
        return [s for s in temporal_segments(scheme, value_map)
                if s.get("label") not in (None, "")]
    from potato.training.structured import STRUCTURED_KINDS
    if spec.kind in STRUCTURED_KINDS:
        return value_map.get("_structured") if isinstance(value_map, dict) else None
    if spec.kind == "bws":
        # Tuple positions as letters; the row's candidates say what they are.
        if not isinstance(value_map, dict):
            return None
        best, worst = value_map.get("best"), value_map.get("worst")
        if best in (None, "") or worst in (None, "") or best == worst:
            return None
        return {"best": str(best), "worst": str(worst)}
    if spec.kind == "preference_scale":
        # Already in data order: negative prefers A, positive prefers B.
        values = value_map.values() if isinstance(value_map, dict) else [value_map]
        for value in values:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None
    # A type that stores its whole answer under one fixed key -- pairwise
    # {"selection": "A"}, ranking {"rank_order": ...} -- reads as that key
    # below, so every pairwise item trained as the label "selection".
    from potato.server_utils.iaa.dispatcher import packed_answer
    packed = packed_answer(scheme, value_map)
    if packed is not None:
        if spec.kind == "ranking":
            # The whole order, best first. One element is no ranking.
            return packed if len(packed) > 1 else None
        if spec.kind == "multilabel":
            return packed
        return packed[0] if len(packed) == 1 else None
    if spec.kind == "multilabel":
        return _labels_of(value_map)
    if spec.kind == "span":
        return (value_map or {}).get("_spans", []) if isinstance(value_map, dict) else []
    if spec.kind == "geometry" and spec.annotation_type == "microscopy":
        from potato.training.vision import microscopy_target
        return microscopy_target(value_map)
    if spec.kind == "geometry":
        return (value_map or {}).get("_objects", []) if isinstance(value_map, dict) else []
    if spec.kind == "text":
        # A text box stores {"text_box": "what they wrote"}. The label-name
        # reading below would return the key, "text_box", for every item.
        if isinstance(value_map, dict):
            texts = [str(v) for v in value_map.values()
                     if isinstance(v, str) and v.strip()]
            return texts[0] if texts else None
        return str(value_map) if value_map not in (None, "") else None
    if spec.kind in ("ordinal", "continuous"):
        if isinstance(value_map, dict) and len(value_map) == 1:
            only = list(value_map.values())[0]
            try:
                return float(only)
            except (TypeError, ValueError):
                return _label_of(value_map)
        try:
            return float(value_map)
        except (TypeError, ValueError):
            return _label_of(value_map)
    return _label_of(value_map)


#: Kinds whose inputs are an agent trace on the item, not its text field.
TRACE_KINDS = ("trajectory", "trace")

from potato.training.vision import VISION_KINDS  # noqa: E402


def _vision_target(kind: str, scheme: Dict[str, Any], value_map: Any,
                   item_data: Dict[str, Any]) -> Any:
    """The target for a scheme that stores its answer as one JSON blob."""
    from potato.training import vision
    if kind == "geo":
        return vision.geo_target(value_map)
    if kind == "caption":
        return vision.caption_target(value_map)
    if kind == "grounding":
        return vision.grounding_target(scheme, value_map, item_data)
    if kind == "gui_click":
        return vision.gui_target(value_map)
    return None


def _render_step(step: Any) -> str:
    """One trace step as text. A dict step keeps its keys, in order, so a
    model sees ``thought:`` and ``action:`` the way annotators did."""
    if isinstance(step, dict):
        lines = []
        for key, value in step.items():
            if value in (None, "", [], {}):
                continue
            if not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            lines.append("%s: %s" % (key, value))
        return "\n".join(lines)
    return "" if step is None else str(step)


def _render_steps(steps: Sequence[Any], final_answer: Any = None,
                  final_answer_key: str = "final_answer") -> str:
    parts = ["Step %d\n%s" % (n + 1, _render_step(step))
             for n, step in enumerate(steps or [])]
    if final_answer not in (None, ""):
        parts.append("%s: %s" % (final_answer_key, final_answer))
    return "\n\n".join(parts)


def _trace_inputs(scheme: Dict[str, Any], item_data: Dict[str, Any]
                  ) -> Dict[str, Any]:
    """The task and the rendered steps of the trace an item carries."""
    steps_key = scheme.get("steps_key", "steps")
    final_key = scheme.get("final_answer_key", "final_answer")
    steps = item_data.get(steps_key)
    steps = steps if isinstance(steps, list) else []
    task = _as_text(item_data.get("task_description", item_data.get(
        "task", item_data.get("text", ""))))
    return {"task": task, "steps": [_render_step(s) for s in steps],
            "rendered": _render_steps(steps, item_data.get(final_key), final_key)}


def _blob(value_map: Any) -> Optional[Dict[str, Any]]:
    """The JSON object a blob scheme saved, from ``{label: json}``."""
    values = value_map.values() if isinstance(value_map, dict) else [value_map]
    for value in values:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                parsed = json.loads(value)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


#: process_reward stores 1 (correct), 0 (neutral) and -1 (incorrect).
STEP_REWARDS = (-1, 0, 1)


def _agent_trace_target(kind: str, scheme: Dict[str, Any], value_map: Any,
                        item_data: Dict[str, Any]) -> Any:
    """The target for a ``trajectory_edit`` or ``process_reward`` answer.

    ``trajectory``: ``{"chosen": corrected steps, "rejected": original
    steps}``, rebuilt from the per-field edits the way the
    trajectory_correction exporter does; an unedited trace has no target.
    ``trace``: one reward per step of the item's trace, None where the step
    was not rated.
    """
    blob = _blob(value_map)
    if blob is None:
        return None
    if kind == "trajectory":
        from potato.export.trajectory_correction_exporter import (
            TrajectoryCorrectionExporter)
        record = TrajectoryCorrectionExporter()._build_record(
            "", "", scheme, item_data, blob)
        if not record or not record.get("n_edits"):
            return None
        final_key = scheme.get("final_answer_key", "final_answer")
        def render(trace):
            return _render_steps(trace.get("steps") or [], trace.get(final_key),
                                 final_key)
        chosen = render(record["corrected_trace"])
        rejected = render(record["original_trace"])
        return None if chosen == rejected else {"chosen": chosen,
                                                "rejected": rejected}

    steps = item_data.get(scheme.get("steps_key", "steps"))
    n_steps = len(steps) if isinstance(steps, list) else 0
    rewards: List[Optional[int]] = [None] * n_steps
    for n, step in enumerate(blob.get("steps") or []):
        if not isinstance(step, dict):
            continue
        try:
            index = int(step.get("index", n))
            reward = int(step.get("reward"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < n_steps and reward in STEP_REWARDS:
            rewards[index] = reward
    return rewards if any(r is not None for r in rewards) else None


def _as_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("text", "content", "response", "output", "answer"):
            if isinstance(value.get(key), str):
                return value[key]
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "" if value is None else str(value)


def _item_text(item_data: Dict[str, Any], text_key: str) -> str:
    """The item's text. A list (pairwise candidates, ``list_as_text``) is
    joined with blank lines; ``str()`` of it gave a Python list literal."""
    value = item_data.get(text_key, "")
    if isinstance(value, (list, tuple)):
        return "\n\n".join(_as_text(v) for v in value)
    return _as_text(value) if value else ""


def _candidates(scheme: Dict[str, Any], item_data: Dict[str, Any]) -> List[str]:
    """The responses a pairwise scheme compares, in data order (A, B)."""
    if (scheme.get("annotation_type") or "") != "pairwise":
        return []
    value = item_data.get(scheme.get("items_key") or "text")
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return []
    return [_as_text(v) for v in value]


#: Item fields that hold what a pair of responses answers, first found wins.
PROMPT_KEYS = ("prompt", "question", "instruction", "query", "input", "context")


def _is_tree_node(value: Any) -> bool:
    return isinstance(value, dict) and "id" in value and isinstance(
        value.get("children", []), list)


def _conversation_tree(config: Dict[str, Any], item_data: Dict[str, Any]
                       ) -> Optional[Dict[str, Any]]:
    """The conversation tree an item shows: the field of its
    ``conversation_tree`` display, or else the first field holding a tree
    (a node with an ``id`` and ``children``)."""
    fields = ((config.get("instance_display") or {}).get("fields") or [])
    for field in fields:
        if isinstance(field, dict) and field.get("type") == "conversation_tree":
            value = item_data.get(field.get("key"))
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = None
            if _is_tree_node(value):
                return value
    for value in item_data.values():
        if _is_tree_node(value):
            return value
    return None


def _bws_candidates(item_data: Dict[str, Any]) -> List[str]:
    """The items of a BWS tuple in position order, so ``A`` is the first.
    A tuple is a synthetic item the server builds; its answer is letters."""
    entries = [e for e in item_data.get("_bws_items") or [] if isinstance(e, dict)]
    entries.sort(key=lambda e: e.get("position", 0))
    return [_as_text(e.get("text")) for e in entries]


#: Kinds that get a soft target beside the voted one when two or more
#: annotators answered.
SOFT_KINDS = ("nominal", "ordinal", "multilabel", "distribution")


def _soft_target(kind: str, answers: Sequence[Any]) -> Optional[Dict[str, float]]:
    """The annotators' answers as a label distribution, or None.

    Only with two or more answers, except for a soft label, which is a
    distribution even from one annotator."""
    from potato.training.structured import soft_target
    if kind not in SOFT_KINDS:
        return None
    if kind == "distribution":
        shares = [a.get("_structured") for a in answers if isinstance(a, dict)]
        return soft_target(kind, [s for s in shares if s])
    if len(answers) < 2:
        return None
    labels_of = (_labels_of if kind == "multilabel"
                 else lambda a: [x for x in [_label_of(a)] if x is not None])
    return soft_target(kind, answers, labels_of)


def _pair_prompt(item_data: Dict[str, Any]) -> str:
    for key in PROMPT_KEYS:
        if isinstance(item_data.get(key), str) and item_data[key].strip():
            return item_data[key]
    return ""


def _media_reference(item_data: Dict[str, Any],
                     source_field: Optional[str]) -> Optional[str]:
    if source_field and item_data.get(source_field):
        return str(item_data[source_field])
    for key in _MEDIA_KEYS:
        if item_data.get(key):
            return str(item_data[key])
    return None


def _image_size(path: str) -> Optional[Tuple[int, int]]:
    """``(width, height)`` from an image header, or None."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _media_field(config: Dict[str, Any], scheme: Dict[str, Any]) -> Optional[str]:
    """The item field that names a scheme's image. A caption or grounding
    scheme draws on an image_annotation scheme's canvas, whose
    ``source_field`` is the image; a microscopy scheme names it
    ``image_key``."""
    if scheme.get("source_field"):
        return scheme["source_field"]
    if scheme.get("annotation_type") == "microscopy":
        return scheme.get("image_key") or "image"
    if scheme.get("annotation_type") in ("region_caption", "grounding_eval"):
        for other in config.get("annotation_schemes") or []:
            if isinstance(other, dict) and other.get("annotation_type") == "image_annotation":
                return other.get("source_field")
    return None


def _media_file(reference: str, task_dir: str, media_directory: str = "media") -> str:
    """A media reference as a filesystem path. ``/media/x.jpg`` is the URL the
    annotation page serves from ``<task_dir>/<media_directory>/``; read as a
    path it pointed at /media, so an image study's files were never found."""
    base = (media_directory if os.path.isabs(media_directory)
            else os.path.join(task_dir, media_directory))
    if reference.startswith("/media/"):
        return os.path.join(base, reference[len("/media/"):])
    if os.path.isabs(reference):
        return reference
    # A bare name is the deep-zoom viewer's convention ("a path inside
    # media_directory"): found only there, it was missing for every slide.
    beside = os.path.join(task_dir, reference)
    inside = os.path.join(base, reference)
    return inside if not os.path.exists(beside) and os.path.exists(inside) else beside


def _source_path(source: str, task_dir: str) -> str:
    """Where a media file lives: relative to the task directory (with ``/``)
    when it is inside it, else absolute. The bundle's own copy sits under a
    hashed folder, so it cannot stand in for the file's name in a URL."""
    source, root = os.path.abspath(source), os.path.abspath(task_dir)
    if source.startswith(root + os.sep):
        return os.path.relpath(source, root).replace(os.sep, "/")
    return source


def _link_media(reference: str, task_dir: str, media_dir: str,
                stats: BundleStats, media_directory: str = "media") -> Optional[str]:
    """Symlink one media file into the bundle, returning its bundle-relative path.

    Symlinks rather than copies: a run over a large image corpus would
    otherwise duplicate the whole corpus per run, and retention keeps five.
    Falls back to copying where symlinks are unavailable.
    """
    if reference.startswith(("http://", "https://")):
        # A remote asset is the trainer's problem to fetch; record it as-is.
        return reference
    if reference.startswith("data:"):
        return _write_data_uri(reference, media_dir, stats)

    source = _media_file(reference, task_dir, media_directory)
    # A directory is an OME-Zarr image, rendered to planes later.
    if not os.path.exists(source):
        stats.n_media_missing += 1
        return None
    # Only files inside the project, as the annotation page serves them. An
    # absolute path, a ../ path or a symlink out of media/ was linked in, and
    # a remote run's archive follows links: /etc/passwd went to the GPU host.
    real = os.path.realpath(source)
    base = (media_directory if os.path.isabs(media_directory)
            else os.path.join(task_dir, media_directory))
    roots = [os.path.realpath(task_dir), os.path.realpath(base)]
    if not any(real == root or real.startswith(root + os.sep) for root in roots):
        stats.n_media_missing += 1
        stats.n_media_outside += 1
        return None

    # A folder per source file. Two folders of 001.jpg shared a two-digit
    # folder one time in 256, and the second item trained on the first's image.
    digest = hashlib.sha1(real.encode()).hexdigest()[:16]
    dest_dir = os.path.join(media_dir, digest)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(source))

    if not os.path.lexists(dest):
        try:
            os.symlink(real, dest)
        except (OSError, NotImplementedError):
            shutil.copy2(real, dest)
    stats.n_media_linked += 1
    return os.path.join(digest, os.path.basename(source))


_DATA_URI_SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
                      "image/webp": ".webp", "image/gif": ".gif"}


def _write_data_uri(reference: str, media_dir: str,
                    stats: BundleStats) -> Optional[str]:
    """An inline ``data:image/...;base64,`` screenshot as a file in the
    bundle, named by its content so a repeated screenshot is written once."""
    import base64
    head, _, payload = reference.partition(",")
    mime = head[5:].split(";")[0].lower()
    if ";base64" not in head or mime not in _DATA_URI_SUFFIXES:
        stats.n_media_missing += 1
        return None
    try:
        raw = base64.b64decode(payload, validate=False)
    except (ValueError, TypeError):
        stats.n_media_missing += 1
        return None
    digest = hashlib.sha1(raw).hexdigest()
    name = "inline-%s%s" % (digest[:16], _DATA_URI_SUFFIXES[mime])
    dest_dir = os.path.join(media_dir, digest[:2])
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    if not os.path.exists(dest):
        with open(dest, "wb") as fh:
            fh.write(raw)
    stats.n_media_linked += 1
    return os.path.join(digest[:2], name)


def _prune_media(media_dir: str, rows: Sequence[Dict[str, Any]]) -> None:
    """Remove the links to sources no row reads any more. A tiled slide or a
    rendered microscopy stack is replaced by its tiles or planes, and the
    link left behind would be dereferenced into the archive a remote run
    downloads: the whole slide, which tiling exists to avoid."""
    used = set()
    for row in rows:
        if row.get("media"):
            used.add(os.path.normpath(str(row["media"])))
        for step in row.get("steps") or []:
            if isinstance(step, dict) and step.get("media"):
                used.add(os.path.normpath(str(step["media"])))
    if not os.path.isdir(media_dir):
        return
    for folder in os.listdir(media_dir):
        if folder in ("tiles", "planes"):
            continue
        path = os.path.join(media_dir, folder)
        if not os.path.isdir(path) or os.path.islink(path):
            continue
        for name in os.listdir(path):
            if os.path.normpath(os.path.join(folder, name)) not in used:
                target = os.path.join(path, name)
                if os.path.islink(target) or os.path.isfile(target):
                    os.remove(target)
                elif os.path.isdir(target):
                    shutil.rmtree(target)
        if not os.listdir(path):
            os.rmdir(path)


def _force_into_train(partitioned: Dict[str, List[Dict[str, Any]]],
                      rows: Sequence[Dict[str, Any]],
                      force_train: Dict[str, Iterable[str]],
                      stats: BundleStats) -> None:
    """Move forced rows into ``train``, counting what moved and why."""
    partitioned.setdefault("train", [])
    labelled = {r["instance_id"] for r in rows}
    reason_of: Dict[str, str] = {}
    for reason, ids in force_train.items():
        ids = {str(i) for i in ids or ()}
        # An item with two reasons (corrected and pinned) is counted under
        # the first, the one it moves under.
        mine = {i for i in ids & labelled if reason_of.setdefault(i, reason) == reason}
        stats.forced_train[reason] = {
            "n": len(mine), "moved": 0,
            "waiting_for_label": len(ids - labelled)}

    moved_total = 0
    for split_name, split_rows in partitioned.items():
        if split_name == "train":
            continue
        keep = []
        for row in split_rows:
            reason = reason_of.get(row["instance_id"])
            if reason is None:
                keep.append(row)
                continue
            partitioned["train"].append(row)
            stats.forced_train[reason]["moved"] += 1
            moved_total += 1
        partitioned[split_name] = keep

    if moved_total:
        stats.warnings.append(
            "%d held-out item(s) moved to train (%s). Held-out scores are "
            "computed without them, so they are not directly comparable with "
            "a run that had them."
            % (moved_total, ", ".join(
                "%s: %d" % (r, c["moved"])
                for r, c in sorted(stats.forced_train.items()) if c["moved"])))
    if reason_of and labelled and not any(
            partitioned.get(s) for s in partitioned if s not in ("train", "unlabeled")):
        stats.warnings.append(
            "Every labelled item is a correction or pinned, so all of them "
            "train and none is held out: this run has no held-out score. "
            "Label more items, or unpin some.")


def _digest_of(paths: Sequence[str]) -> str:
    """A content hash over the split files.

    Lets a re-run over unchanged data be recognized and skipped, which matters
    once auto-retrain is firing on a timer.
    """
    hasher = hashlib.sha256()
    for path in sorted(paths):
        if not os.path.isfile(path):
            continue
        hasher.update(os.path.basename(path).encode())
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def build_bundle(
    context,
    dest: str,
    schema_names: Sequence[str],
    *,
    split_spec: Optional[Dict[str, float]] = None,
    split_seed: int = 0,
    aggregation: str = "consensus",
    text_key: Optional[str] = None,
    include_media: bool = True,
    include_unlabeled: bool = False,
    force_train: Optional[Dict[str, Iterable[str]]] = None,
) -> Tuple[BundleRef, BundleStats, Dict[str, List[str]]]:
    """Write a training bundle from an ``ExportContext``.

    Args:
        context: from ``potato.export.cli.build_export_context``.
        dest: bundle root, created if absent.
        schema_names: which schemes to train on.
        split_spec: split name to fraction. Defaults to 70/15/15.
        split_seed: seeds split assignment. **Keep it fixed across runs** --
            changing it reshuffles held-out data into training and silently
            invalidates every earlier metric.
        aggregation: ``consensus`` (Dawid-Skene) or ``majority``.
        include_unlabeled: also write the items nobody has labelled yet as an
            ``unlabeled`` split, for the worker to predict on (write-back's
            ``include_unlabeled``). Never trained or evaluated on, and not in
            *split_ids*.
        force_train: reason to instance ids that go to ``train`` whatever
            their hash split, such as items a reviewer corrected. A
            correction is the most useful label there is and not a random
            sample of the corpus: in val or test it would make the model look
            worse at the items it was already worst at. Ids with no human
            label are counted as waiting and otherwise ignored.

    Returns:
        ``(bundle, stats, split_ids)`` where *split_ids* maps a split name to
        its instance ids, ready for the run ledger's leak guard.
    """
    config = context.config or {}
    task_dir = config.get("task_dir", ".")
    item_props = config.get("item_properties", {}) or {}
    text_key = text_key or item_props.get("text_key", "text")

    os.makedirs(dest, exist_ok=True)
    media_dir = os.path.join(dest, "media")
    stats = BundleStats()

    items = {str(k): v for k, v in (context.items or {}).items()} \
        if isinstance(context.items, dict) else {
            str(i.get("id", i.get("instance_id", n))): i
            for n, i in enumerate(context.items or [])}
    stats.n_items = len(items)

    instance_ids = sorted(items)
    trained_schemes = [s for s in config.get("annotation_schemes", [])
                       if s.get("name") in set(schema_names)]
    references, agg_meta = _resolve_labels(
        context.annotations or [], instance_ids, aggregation, trained_schemes)
    stats.n_annotated = len(references)
    # Every annotator's answer per item and scheme, before the vote keeps
    # one: what the soft targets are made of.
    answers_by_item: Dict[str, Dict[str, List[Any]]] = defaultdict(
        lambda: defaultdict(list))
    for (_user, iid), by_scheme in _annotation_index(
            context.annotations or [], trained_schemes)[0].items():
        for name, value_map in by_scheme.items():
            answers_by_item[iid][name].append(value_map)

    if not references:
        raise TrainerError(
            "No resolved annotations to train on. There are %d items and %d "
            "annotation records; check that the schemes named (%s) match the "
            "ones being annotated."
            % (len(items), len(context.annotations or []),
               ", ".join(schema_names)))

    # First pass: rows and the observed label vocabulary.
    from potato.training.registry import kind_of_schema
    by_name = {s["name"]: s for s in config.get("annotation_schemes", [])
               if s.get("name")}
    kinds = {name: kind_of_schema(by_name.get(name, {})) for name in schema_names}

    label_index: Dict[str, List[str]] = {name: [] for name in schema_names}
    seen_labels: Dict[str, set] = {name: set() for name in schema_names}
    rows: List[Dict[str, Any]] = []
    unlabeled_rows: List[Dict[str, Any]] = []
    media_directory = config.get("media_directory") or "media"

    def attach_media(row, item_data):
        if not include_media:
            return
        if by_name.get(schema_names[0], {}).get("annotation_type") in TEXT_SOURCE_TYPES:
            return
        source_field = _media_field(config, by_name.get(schema_names[0], {}))
        reference = _media_reference(item_data, source_field)
        if reference:
            linked = _link_media(reference, task_dir, media_dir, stats,
                                 media_directory)
            if linked:
                row["media"] = linked
                if not reference.startswith(("http://", "https://")):
                    row["media_source"] = _source_path(
                        _media_file(reference, task_dir, media_directory),
                        task_dir)
            else:
                row["media_missing"] = reference

    primary = by_name.get(schema_names[0], {}) if schema_names else {}
    trace_inputs = kinds.get(schema_names[0]) in TRACE_KINDS if schema_names else False

    def attach_trace(row, item_data):
        # Agent-trace schemes train on the trace, which is not the text field.
        # The SFT text is the task and the original steps; DPO's prompt is the
        # task alone and its two responses are steps.
        if not trace_inputs:
            return
        inputs = _trace_inputs(primary, item_data)
        row["trace"] = inputs
        row["prompt"] = inputs["task"]
        row["text"] = ("%s\n\n%s" % (inputs["task"], inputs["rendered"])).strip()

    def attach_candidates(row, item_data):
        # What a preference or reward model compares. An unlabelled row
        # needs them most: without them nothing could be predicted on the
        # items still waiting for an annotator.
        candidates = (_bws_candidates(item_data)
                      if kinds.get(schema_names[0]) == "bws"
                      else _candidates(primary, item_data))
        if candidates:
            row["candidates"] = candidates
            prompt = _pair_prompt(item_data)
            if prompt:
                row["prompt"] = prompt

    def attach_tree(row, item_data):
        # A conversation-tree scheme's input is the tree, node by node.
        if kinds.get(schema_names[0]) == "conversation_tree":
            tree = _conversation_tree(config, item_data)
            if tree is not None:
                row["tree"] = tree
        # A gloss scheme's input is the words the page shows, with any
        # segmentation or gloss the item pre-fills.
        if kinds.get(schema_names[0]) == "gloss":
            from potato.igt import initial_answer
            row["gloss_input"] = initial_answer(item_data, primary)

    def attach_steps(row, item_data):
        # A GUI trace's input is its steps, each with its own screenshot.
        if kinds.get(schema_names[0]) != "gui_click":
            return
        from potato.training.vision import gui_steps
        pixels = primary.get("coord_space", "normalized") == "pixels"
        steps = []
        for step in gui_steps(primary, item_data):
            shot = step.pop("screenshot")
            if shot and include_media:
                linked = _link_media(shot, task_dir, media_dir, stats,
                                     media_directory)
                if linked:
                    step["media"] = linked
                else:
                    step["media_missing"] = shot[:200]
            if pixels and step.get("point"):
                # Clicks travel normalized, as the page draws them; a pixel
                # click needs its screenshot's size, and without the file it
                # cannot be placed at all.
                size = _image_size(os.path.join(media_dir, step["media"])) \
                    if step.get("media") else None
                step["point"] = ({"x": step["point"]["x"] / size[0],
                                  "y": step["point"]["y"] / size[1]}
                                 if size else None)
            steps.append(step)
        row["steps"] = steps

    prediction_field = ((config.get("model_training") or {}).get("writeback") or {}
                        ).get("field") or "predictions"

    def attach_basemap(row, item_data):
        # A geo answer is drawn over the item's raster basemap.
        if kinds.get(schema_names[0]) == "geo":
            basemap = rasters.item_basemap(primary, item_data)
            if basemap:
                row["basemap"] = basemap

    def attach_expressions(row, item_data):
        # The phrases a grounding scheme asks about, so an item nobody has
        # answered yet can still be predicted on.
        if kinds.get(schema_names[0]) == "grounding" and (
                primary.get("expression_source") or "field") == "field":
            from potato.grounding.routes import normalize_expressions
            expressions = normalize_expressions(
                item_data.get(primary.get("expressions_field", "expressions")))
            if expressions:
                row["expressions"] = [{"id": e["id"], "text": e["text"]}
                                      for e in expressions]
                row["region_type"] = primary.get("region_type", "box")

    def attach_words(row, item_data):
        # A page's words with their boxes, what a layout model reads; Potato
        # runs no OCR, so they come from the item (a PDF text layer, a
        # PAGE-XML transcription).
        words = item_data.get("words")
        if kinds.get(schema_names[0]) == "geometry" and isinstance(words, list) and words:
            row["words"] = [w for w in words if isinstance(w, dict)]

    def attach_prior(row, item_data):
        # The shapes an earlier run already put on the item (a detector's
        # boxes), which a refining trainer such as sam-finetune starts from.
        if kinds.get(schema_names[0]) != "geometry":
            return
        prior = (item_data.get(prediction_field) or {}) if isinstance(
            item_data.get(prediction_field), dict) else {}
        objects = prior.get(schema_names[0])
        if isinstance(objects, str):
            try:
                objects = json.loads(objects)
            except ValueError:
                objects = None
        if isinstance(objects, list) and objects:
            row["prior"] = [o for o in objects if isinstance(o, dict)]

    def unlabeled(iid, item_data):
        if include_unlabeled:
            row = {"instance_id": iid,
                   "text": _item_text(item_data, text_key)}
            attach_media(row, item_data)
            attach_trace(row, item_data)
            attach_tree(row, item_data)
            attach_steps(row, item_data)
            attach_prior(row, item_data)
            attach_basemap(row, item_data)
            attach_words(row, item_data)
            attach_expressions(row, item_data)
            if not trace_inputs:
                attach_candidates(row, item_data)
            unlabeled_rows.append(row)

    for iid in instance_ids:
        resolved = references.get(iid)
        item_data = items.get(iid) or {}
        if not isinstance(item_data, dict):
            item_data = {"text": str(item_data)}
        if not resolved:
            unlabeled(iid, item_data)
            continue

        targets: Dict[str, Any] = {}
        soft_targets: Dict[str, Dict[str, float]] = {}
        for name in schema_names:
            if name not in resolved:
                continue
            spec_kind = kinds.get(name, "nominal")
            fake_spec = SchemaSpec(name=name,
                                   annotation_type=by_name.get(name, {}).get(
                                       "annotation_type", ""),
                                   kind=spec_kind)
            if spec_kind in TRACE_KINDS:
                target = _agent_trace_target(spec_kind, by_name.get(name, {}),
                                             resolved[name], item_data)
            elif spec_kind in VISION_KINDS:
                target = _vision_target(spec_kind, by_name.get(name, {}),
                                        resolved[name], item_data)
            else:
                target = _target_for(fake_spec, resolved[name], by_name.get(name))
            if target is None or target == [] or target == "":
                continue
            soft = _soft_target(spec_kind, answers_by_item[iid].get(name) or [])
            if spec_kind == "distribution" and soft:
                # The annotators' mean, not the one answer the vote kept:
                # a soft label is already a distribution, and averaging
                # them is what several people's soft labels mean.
                target = soft
            elif soft is not None:
                soft_targets[name] = soft
            targets[name] = target

            if spec_kind == "multilabel":
                seen_labels[name].update(str(t) for t in target)
            elif spec_kind in ("nominal", "ordinal", "preference"):
                seen_labels[name].add(str(target))
            elif spec_kind in ("geometry", "temporal"):
                seen_labels[name].update(
                    str(o.get("label")) for o in target
                    if isinstance(o, dict) and o.get("label") not in (None, ""))
            elif spec_kind == "span":
                # A tagger's output layer is this vocabulary; without it a
                # span bundle declared no labels at all.
                seen_labels[name].update(
                    str(s.get("name") or s.get("label"))
                    for s in target if isinstance(s, dict)
                    and (s.get("name") or s.get("label")))
            elif spec_kind == "ranking":
                # A tie "A=D" is two items, not a third.
                from potato.server_utils.iaa.dispatcher import rank_tiers
                seen_labels[name].update(
                    item for tier in rank_tiers(target) for item in tier)
            elif spec_kind == "distribution":
                seen_labels[name].update(str(t) for t in target)
            elif spec_kind == "geo":
                seen_labels[name].update(
                    str(f["properties"]["label"]) for f in target)
            elif spec_kind == "gui_click":
                seen_labels[name].update(str(s["verdict"]) for s in target)
            elif spec_kind in ("relation", "event", "coreference"):
                # The link, event or entity types: what the pair classifier
                # predicts. Mention labels are in each target's spans.
                group = {"relation": "links", "event": "events",
                         "coreference": "clusters"}[spec_kind]
                seen_labels[name].update(
                    str(g.get("type")) for g in target.get(group) or []
                    if g.get("type"))

        if not targets:
            stats.n_skipped_no_label += 1
            unlabeled(iid, item_data)
            continue

        row: Dict[str, Any] = {
            "instance_id": iid,
            "text": _item_text(item_data, text_key),
            "targets": targets,
        }
        if soft_targets:
            row["soft_targets"] = soft_targets

        attach_media(row, item_data)
        attach_trace(row, item_data)
        attach_tree(row, item_data)
        attach_steps(row, item_data)
        attach_prior(row, item_data)
        attach_basemap(row, item_data)
        attach_words(row, item_data)
        attach_expressions(row, item_data)
        trajectory = targets.get(schema_names[0]) \
            if kinds.get(schema_names[0]) == "trajectory" else None
        # The corrected steps first, so a preference model's "A" means it
        # prefers the correction.
        if isinstance(trajectory, dict):
            row["candidates"] = [trajectory["chosen"], trajectory["rejected"]]
            prompt = _pair_prompt(item_data)
            if prompt:
                row["prompt"] = prompt
        else:
            attach_candidates(row, item_data)

        rows.append(row)

    for name in schema_names:
        declared = [str(lab.get("name", lab) if isinstance(lab, dict) else lab)
                    for lab in (by_name.get(name, {}).get("labels") or [])]
        if kinds.get(name) == "ranking" and declared:
            # A ranking orders the scheme's labels, whichever were ranked.
            label_index[name] = sorted(declared)
        else:
            label_index[name] = sorted(seen_labels[name])

    # Splits, by a seeded hash of the instance id so they are stable across
    # runs. Reuses the publish pipeline's partitioner.
    from potato.publish.preprocessing import _partition_splits
    spec = split_spec or DEFAULT_SPLITS
    partitioned = _partition_splits(rows, spec, split_seed)
    if force_train:
        _force_into_train(partitioned, rows, force_train, stats)

    split_files: Dict[str, Dict[str, Any]] = {}
    split_ids: Dict[str, List[str]] = {
        name: [r["instance_id"] for r in split_rows]
        for name, split_rows in partitioned.items()}
    written_paths: List[str] = []

    # A geo answer becomes shapes on its raster, written as an image.
    if include_media and kinds.get(schema_names[0]) == "geo":
        problems = []
        for split_name in list(partitioned):
            partitioned[split_name] = rasters.geo_rasters(
                partitioned[split_name], media_dir, schema_names[0], task_dir,
                media_directory, problems)
        if unlabeled_rows:
            unlabeled_rows = rasters.geo_rasters(
                unlabeled_rows, media_dir, schema_names[0], task_dir,
                media_directory, problems)
        for problem in problems[:20]:
            stats.warnings.append("Left out %s." % problem)

    # Multichannel microscopy becomes one rendered image per annotated plane.
    if include_media and primary.get("annotation_type") in rasters.PLANE_TYPES:
        problems: List[str] = []
        for split_name in list(partitioned):
            partitioned[split_name] = rasters.render_planes(
                partitioned[split_name], split_name, media_dir, schema_names[0],
                primary, task_dir, media_directory, problems)
        if unlabeled_rows:
            unlabeled_rows = rasters.render_planes(
                unlabeled_rows, "unlabeled", media_dir, schema_names[0], primary,
                task_dir, media_directory, problems)
        for problem in problems:
            stats.warnings.append("Could not render %s; left out." % problem)

    # Large images become tiles, after the split so that one slide's tiles
    # stay in one split. The ids above stay the images' own: the run ledger
    # and write-back see images, not tiles.
    tiling_manifest = None
    if include_media and kinds.get(schema_names[0]) in tiling.TILED_KINDS:
        tiling_opts = tiling.settings(config)
        if tiling_opts["enabled"] is not False:
            parents: List[Dict[str, Any]] = []
            summary: Dict[str, Any] = {}
            for split_name in list(partitioned):
                partitioned[split_name], cut = tiling.tile_rows(
                    partitioned[split_name], split_name, dest, media_dir,
                    schema_names, tiling_opts, split_seed, summary)
                parents.extend(cut)
            if unlabeled_rows:
                unlabeled_rows, cut = tiling.tile_rows(
                    unlabeled_rows, "unlabeled", dest, media_dir, schema_names,
                    tiling_opts, split_seed, summary)
                parents.extend(cut)
            for problem in summary.get("unreadable", []):
                stats.warnings.append("Could not tile %s; trained on it whole." % problem)
            if summary.get("capped"):
                stats.warnings.append(
                    "%d image(s) had more than %d tissue tiles; predicted on the "
                    "%d with the most tissue. Raise model_training.tiling."
                    "max_predict_tiles or downsample to cover them."
                    % (len(summary["capped"]), tiling_opts["max_predict_tiles"],
                       tiling_opts["max_predict_tiles"]))
            if parents:
                path = os.path.join(dest, tiling.PARENTS_FILE)
                with open(path, "w") as fh:
                    for parent in parents:
                        fh.write(json.dumps(parent, ensure_ascii=False) + "\n")
                written_paths.append(path)
                stats.tiles = {"n_items": summary.get("n_items", 0),
                               "n_tiles": summary.get("n_tiles", 0)}
                tiling_manifest = dict(tiling_opts, parents=tiling.PARENTS_FILE)

    if include_media and (tiling_manifest or kinds.get(schema_names[0]) == "geo"
                          or primary.get("annotation_type") in rasters.PLANE_TYPES):
        _prune_media(media_dir, [r for rows_ in partitioned.values() for r in rows_]
                     + unlabeled_rows)

    for split_name, split_rows in partitioned.items():
        filename = "%s.jsonl" % split_name
        path = os.path.join(dest, filename)
        with open(path, "w") as fh:
            for row in split_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        split_files[split_name] = {"path": filename, "format": "jsonl",
                                   "n": len(split_rows)}
        stats.splits[split_name] = len(split_ids[split_name])
        written_paths.append(path)

    if unlabeled_rows:
        # Predicted on, never trained or scored on, and kept out of split_ids:
        # the run ledger's held-out records stay what they were.
        path = os.path.join(dest, "unlabeled.jsonl")
        with open(path, "w") as fh:
            for row in unlabeled_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        split_files["unlabeled"] = {"path": "unlabeled.jsonl", "format": "jsonl",
                                    "n": len(unlabeled_rows), "predict_only": True}
        written_paths.append(path)

    if stats.n_media_outside:
        stats.warnings.append(
            "%d media file(s) are outside the task directory and media_directory "
            "and were left out. Move them into media_directory to train on them."
            % stats.n_media_outside)

    if not stats.splits.get("train"):
        stats.warnings.append(
            "The train split is empty. With %d labelled items and these split "
            "fractions, everything landed elsewhere." % len(rows))

    schemes = [by_name[name] for name in schema_names if name in by_name]
    manifest = {
        "v": 1,
        "schemas": [s.to_dict() for s in
                    schema_specs_from_config(config, schema_names, label_index)],
        "splits": split_files,
        "labels": label_index,
        "media_dir": "media",
        "modality": detect_modality(schemes, rows),
        "text_key": text_key,
        "split_seed": split_seed,
        "aggregation": aggregation,
        "stats": stats.to_dict(),
        "digest": _digest_of(written_paths),
    }
    if tiling_manifest:
        manifest["tiling"] = tiling_manifest

    with open(os.path.join(dest, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    with open(os.path.join(dest, "labels.json"), "w") as fh:
        json.dump(label_index, fh, indent=2)

    logger.info("Built bundle at %s: %s", dest,
                ", ".join("%s=%d" % (k, v) for k, v in stats.splits.items()))

    return BundleRef(root=dest, manifest=manifest), stats, split_ids
