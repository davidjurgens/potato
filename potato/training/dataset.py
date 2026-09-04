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

from potato.training.base import BundleRef, SchemaSpec, TrainerError

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_SPLITS",
    "BundleStats",
    "build_bundle",
    "schema_specs_from_config",
    "detect_modality",
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
        self.splits: Dict[str, int] = {}
        self.warnings: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {"n_items": self.n_items, "n_annotated": self.n_annotated,
                "n_skipped_no_label": self.n_skipped_no_label,
                "n_media_linked": self.n_media_linked,
                "n_media_missing": self.n_media_missing,
                "splits": dict(self.splits), "warnings": list(self.warnings)}


def detect_modality(schemes: Sequence[Dict[str, Any]]) -> str:
    """What kind of corpus this is, from the schemes being trained.

    Text is the default because it is both the common case and the harmless
    one: a text trainer handed an image path fails loudly at fit time, whereas
    an image trainer handed text tries to open a sentence as a file.
    """
    for scheme in schemes:
        modality = _MODALITY_BY_TYPE.get(scheme.get("annotation_type", ""))
        if modality:
            return modality
    return "text"


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
            source_field=scheme.get("source_field")))
    return tuple(specs)


def _annotation_index(annotations: Sequence[Dict[str, Any]]
                      ) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], List[str]]:
    """``{(user, instance): {scheme: value_map}}`` plus the annotator list.

    ``load_annotations_from_output_dir`` hands back a flat list of per-user,
    per-instance records; the aggregators want a lookup. Spans are folded in
    under their schema so a span scheme aggregates like any other.
    """
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

        if by_scheme:
            index[(user, iid)] = by_scheme

    return index, users


def _resolve_labels(annotations: Sequence[Dict[str, Any]],
                    instance_ids: Sequence[str],
                    aggregation: str = "consensus"
                    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """One agreed answer per instance.

    Dawid-Skene by default rather than majority vote: it estimates each
    annotator's reliability and weights their votes by it, so one careless
    annotator does not get equal say. Both implementations already exist in
    ``eval_datasets.annotation_aggregation`` and are tested there.
    """
    index, users = _annotation_index(annotations)

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


def _target_for(spec: SchemaSpec, value_map: Any) -> Any:
    """The training target for one schema kind."""
    if spec.kind == "multilabel":
        return _labels_of(value_map)
    if spec.kind == "span":
        return (value_map or {}).get("_spans", []) if isinstance(value_map, dict) else []
    if spec.kind in ("geometry", "grounding"):
        return (value_map or {}).get("_objects", []) if isinstance(value_map, dict) else []
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


def _media_reference(item_data: Dict[str, Any],
                     source_field: Optional[str]) -> Optional[str]:
    if source_field and item_data.get(source_field):
        return str(item_data[source_field])
    for key in _MEDIA_KEYS:
        if item_data.get(key):
            return str(item_data[key])
    return None


def _link_media(reference: str, task_dir: str, media_dir: str,
                stats: BundleStats) -> Optional[str]:
    """Symlink one media file into the bundle, returning its bundle-relative path.

    Symlinks rather than copies: a run over a large image corpus would
    otherwise duplicate the whole corpus per run, and retention keeps five.
    Falls back to copying where symlinks are unavailable.
    """
    if reference.startswith(("http://", "https://")):
        # A remote asset is the trainer's problem to fetch; record it as-is.
        return reference

    source = reference if os.path.isabs(reference) else os.path.join(
        task_dir, reference)
    if not os.path.isfile(source):
        stats.n_media_missing += 1
        return None

    digest = hashlib.sha1(os.path.abspath(source).encode()).hexdigest()[:2]
    dest_dir = os.path.join(media_dir, digest)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(source))

    if not os.path.exists(dest):
        try:
            os.symlink(os.path.abspath(source), dest)
        except (OSError, NotImplementedError):
            shutil.copy2(source, dest)
    stats.n_media_linked += 1
    return os.path.join(digest, os.path.basename(source))


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
    references, agg_meta = _resolve_labels(
        context.annotations or [], instance_ids, aggregation)
    stats.n_annotated = len(references)

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

    for iid in instance_ids:
        resolved = references.get(iid)
        if not resolved:
            continue

        item_data = items.get(iid) or {}
        if not isinstance(item_data, dict):
            item_data = {"text": str(item_data)}

        targets: Dict[str, Any] = {}
        for name in schema_names:
            if name not in resolved:
                continue
            spec_kind = kinds.get(name, "nominal")
            fake_spec = SchemaSpec(name=name,
                                   annotation_type=by_name.get(name, {}).get(
                                       "annotation_type", ""),
                                   kind=spec_kind)
            target = _target_for(fake_spec, resolved[name])
            if target is None or target == [] or target == "":
                continue
            targets[name] = target

            if spec_kind == "multilabel":
                seen_labels[name].update(str(t) for t in target)
            elif spec_kind in ("nominal",):
                seen_labels[name].add(str(target))

        if not targets:
            stats.n_skipped_no_label += 1
            continue

        row: Dict[str, Any] = {
            "instance_id": iid,
            "text": str(item_data.get(text_key, "") or ""),
            "targets": targets,
        }

        if include_media:
            source_field = by_name.get(schema_names[0], {}).get("source_field")
            reference = _media_reference(item_data, source_field)
            if reference:
                linked = _link_media(reference, task_dir, media_dir, stats)
                if linked:
                    row["media"] = linked
                else:
                    row["media_missing"] = reference

        rows.append(row)

    for name in schema_names:
        label_index[name] = sorted(seen_labels[name])

    # Splits, by a seeded hash of the instance id so they are stable across
    # runs. Reuses the publish pipeline's partitioner.
    from potato.publish.preprocessing import _partition_splits
    spec = split_spec or DEFAULT_SPLITS
    partitioned = _partition_splits(rows, spec, split_seed)

    split_files: Dict[str, Dict[str, Any]] = {}
    split_ids: Dict[str, List[str]] = {}
    written_paths: List[str] = []

    for split_name, split_rows in partitioned.items():
        filename = "%s.jsonl" % split_name
        path = os.path.join(dest, filename)
        with open(path, "w") as fh:
            for row in split_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        split_files[split_name] = {"path": filename, "format": "jsonl",
                                   "n": len(split_rows)}
        split_ids[split_name] = [r["instance_id"] for r in split_rows]
        stats.splits[split_name] = len(split_rows)
        written_paths.append(path)

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
        "modality": detect_modality(schemes),
        "text_key": text_key,
        "split_seed": split_seed,
        "aggregation": aggregation,
        "stats": stats.to_dict(),
        "digest": _digest_of(written_paths),
    }

    with open(os.path.join(dest, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    with open(os.path.join(dest, "labels.json"), "w") as fh:
        json.dump(label_index, fh, indent=2)

    logger.info("Built bundle at %s: %s", dest,
                ", ".join("%s=%d" % (k, v) for k, v in stats.splits.items()))

    return BundleRef(root=dest, manifest=manifest), stats, split_ids
