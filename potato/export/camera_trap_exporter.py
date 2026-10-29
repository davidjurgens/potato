"""
Camera-trap exports: MegaDetector JSON, Camtrap DP and Darwin Core occurrences.

All three read the questions the ``megadetector`` / ``coco_camera_traps``
importers create, found by type: the first ``image_annotation`` scheme (boxes),
a ``radio`` scheme whose labels include ``empty`` (triage), and a
``multiselect`` named ``species``. Options ``box_scheme``, ``triage_scheme``
and ``species_scheme`` name them explicitly.

``megadetector``
    The reviewed boxes in MegaDetector batch-output format (1.4), one entry
    per reviewed image: ``detections`` with ``category`` (1 animal, 2 person,
    3 vehicle), ``conf`` and a normalized ``[x, y, w, h]`` bbox; a species
    label becomes category 1 plus ``classifications``. A box the reviewer drew
    or changed gets ``conf`` 1.0; a model box they kept keeps the detector's
    score as ``conf`` and the classifier's score in ``classifications``.
    Items reviewed as a sequence or a video clip (no boxes in Potato) carry
    the imported detections through, emptied when the reviewer chose
    ``empty``.

All three write one reviewer per item: the first by user id, or the one named
by ``annotator=``, with a warning when an item had several. In Camtrap DP and
Darwin Core a second reviewer's answer would be a second observation of the
same animal, and GBIF counts it twice. Reconcile reviewers (adjudication)
before publishing, or name the one whose answers to export.

An image triaged ``empty`` that still has boxes is a contradiction the
reviewer left. Every camera-trap export (and the Darwin JSON export) keeps the
boxes, since deleting a box is the reviewer's call and not the exporter's, and
lists the image in the export warnings. Camtrap DP marks those observations
in ``observationComments``.

``camtrap_dp``
    A Camtrap DP 1.0 data package: ``datapackage.json``, ``deployments.csv``,
    ``media.csv`` and ``observations.csv`` with the 1.0 column names.
    Observations are media-level (one per box, or one per species / triage
    answer when there are no boxes) or event-level for sequence items. Potato
    does not know deployment coordinates, camera setup or the sampling design;
    item fields ``latitude`` / ``longitude`` / ``deployment_id`` are used when
    present, and export options fill the package metadata (``title``,
    ``contributor``, ``license``, ``sampling_design``, ``capture_method``,
    ``timezone``). Anything the profile requires that is still missing is
    listed in the export warnings.

``darwin_core``
    ``occurrence.csv``: one Darwin Core occurrence per animal observation that
    has a scientific name. ``basisOfRecord`` is ``MachineObservation`` when the
    identification is a model's that the reviewer left unchanged and
    ``HumanObservation`` otherwise (``basis_of_record=`` forces either).
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import mimetypes
import os
import re
from collections import OrderedDict, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import normalize_annotation_object

GENERIC = {"animal": "animal", "person": "person", "human": "person", "vehicle": "vehicle",
           "empty": "empty", "blank": "empty"}
MD_CATEGORIES = OrderedDict([("1", "animal"), ("2", "person"), ("3", "vehicle")])
MD_CATEGORY_ID = {v: k for k, v in MD_CATEGORIES.items()}
#: Camtrap DP observationType for each triage class.
CAMTRAP_TYPE = {"animal": "animal", "person": "human", "vehicle": "vehicle", "empty": "blank"}

CAMTRAP_VERSION = "1.0"
CAMTRAP_BASE = f"https://raw.githubusercontent.com/tdwg/camtrap-dp/{CAMTRAP_VERSION}"
DEPLOYMENT_COLUMNS = [
    "deploymentID", "locationID", "locationName", "latitude", "longitude",
    "coordinateUncertainty", "deploymentStart", "deploymentEnd", "setupBy", "cameraID",
    "cameraModel", "cameraDelay", "cameraHeight", "cameraDepth", "cameraTilt", "cameraHeading",
    "detectionDistance", "timestampIssues", "baitUse", "featureType", "habitat",
    "deploymentGroups", "deploymentTags", "deploymentComments"]
MEDIA_COLUMNS = [
    "mediaID", "deploymentID", "captureMethod", "timestamp", "filePath", "filePublic",
    "fileName", "fileMediatype", "exifData", "favorite", "mediaComments"]
OBSERVATION_COLUMNS = [
    "observationID", "deploymentID", "mediaID", "eventID", "eventStart", "eventEnd",
    "observationLevel", "observationType", "cameraSetupType", "scientificName", "count",
    "lifeStage", "sex", "behavior", "individualID", "individualPositionRadius",
    "individualPositionAngle", "individualSpeed", "bboxX", "bboxY", "bboxWidth", "bboxHeight",
    "classificationMethod", "classifiedBy", "classificationTimestamp",
    "classificationProbability", "observationTags", "observationComments"]
DWC_COLUMNS = [
    "occurrenceID", "basisOfRecord", "eventID", "eventDate", "scientificName",
    "individualCount", "occurrenceStatus", "decimalLatitude", "decimalLongitude",
    "geodeticDatum", "locationID", "associatedMedia", "identifiedBy", "identificationRemarks"]


def triage_class(name: str) -> str:
    return GENERIC.get(str(name).strip().lower(), "animal")


def is_generic(name: str) -> bool:
    return str(name).strip().lower() in GENERIC


# ---------------------------------------------------------------------------
# Reading the review out of the annotation records
# ---------------------------------------------------------------------------

def _chosen(labels: Any) -> List[str]:
    """Option names a radio / multiselect answer holds."""
    if not isinstance(labels, dict):
        return []
    out = []
    for name, value in labels.items():
        if value in (None, "", False) or str(value).lower() in ("false", "0"):
            continue
        out.append(str(name))
    return out


class CameraTrapReview:
    """The questions of a camera-trap project and one annotator's answers."""

    def __init__(self, context: ExportContext, options: Optional[dict] = None):
        options = options or {}
        schemes = context.schemas or []

        def pick(kind, named, test=lambda s: True):
            if named:
                return named
            for s in schemes:
                if s.get("annotation_type") == kind and test(s):
                    return s.get("name")
            return None

        def labels_of(s):
            return {(l.get("name") if isinstance(l, dict) else str(l)).lower()
                    for l in s.get("labels") or []}

        self.box_scheme = pick("image_annotation", options.get("box_scheme"))
        self.triage_scheme = pick("radio", options.get("triage_scheme"),
                                  lambda s: "empty" in labels_of(s))
        self.species_scheme = pick("multiselect", options.get("species_scheme"),
                                   lambda s: s.get("name") == "species")

    def usable(self) -> bool:
        return bool(self.box_scheme or self.triage_scheme)

    def boxes(self, record: dict) -> Optional[List[dict]]:
        """Canonical boxes (normalized bbox) or None when the scheme was not answered."""
        if not self.box_scheme:
            return None
        raw = (record.get("image_annotations") or {}).get(self.box_scheme)
        if raw is None:
            stored = (record.get("labels") or {}).get(self.box_scheme)
            if isinstance(stored, dict):
                stored = stored.get("_data", next(iter(stored.values()), None) if stored else None)
            if isinstance(stored, str):
                try:
                    raw = json.loads(stored)
                except ValueError:
                    raw = None
            elif isinstance(stored, list):
                raw = stored
        if not isinstance(raw, list):
            return None
        out = []
        for obj in raw:
            if not isinstance(obj, dict) or obj.get("type") != "bbox":
                continue
            canon = normalize_annotation_object(obj, 1.0, 1.0)
            if canon and canon.get("bbox"):
                if isinstance(obj.get("attributes"), dict):
                    canon["attributes"] = dict(obj["attributes"])
                out.append(canon)
        return out

    def triage(self, record: dict) -> Optional[str]:
        chosen = _chosen((record.get("labels") or {}).get(self.triage_scheme)) if self.triage_scheme else []
        return triage_class(chosen[0]) if chosen else None

    def species(self, record: dict) -> List[str]:
        if not self.species_scheme:
            return []
        return _chosen((record.get("labels") or {}).get(self.species_scheme))

    def answered(self, record: dict) -> bool:
        return (self.boxes(record) is not None or self.triage(record) is not None
                or bool(self.species(record)))


def is_machine(box: dict) -> bool:
    """A model's box the reviewer left as it was."""
    return box.get("source") == "ai" and not box.get("edited")


def classification_score(box: dict) -> Optional[float]:
    """The species classifier's score for an unchanged model box, or None.
    Not the detection score: a box can be a sure animal and an unsure puma."""
    if not is_machine(box):
        return None
    value = (box.get("attributes") or {}).get("classification_confidence")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


CONFLICT_NOTE = "triaged empty, but the reviewer left this box"


def triage_conflicts(context: ExportContext, review: CameraTrapReview,
                     annotator: Optional[str] = None) -> List[str]:
    """``item (user)`` for every answer triaged ``empty`` that still has boxes."""
    out = []
    for iid, recs in records_by_item(context, review, annotator).items():
        for record in recs:
            if review.triage(record) == "empty" and review.boxes(record):
                out.append(f"{iid} ({record.get('user_id')})")
    return out


def conflict_warning(conflicts: List[str], export: str) -> Optional[str]:
    if not conflicts:
        return None
    shown = ", ".join(conflicts[:10]) + (f" and {len(conflicts) - 10} more" if len(conflicts) > 10 else "")
    return (f"{len(conflicts)} answer(s) are triaged empty but still have boxes: {shown}. "
            f"{export} keeps the boxes; check these items and delete the boxes or change "
            f"the triage.")


def records_by_item(context: ExportContext, review: CameraTrapReview,
                    annotator: Optional[str] = None) -> "OrderedDict[str, List[dict]]":
    grouped: "OrderedDict[str, List[dict]]" = OrderedDict()
    for record in sorted(context.annotations, key=lambda r: (str(r.get("instance_id")),
                                                            str(r.get("user_id")))):
        if annotator and str(record.get("user_id")) != annotator:
            continue
        if review.answered(record):
            grouped.setdefault(str(record.get("instance_id")), []).append(record)
    return grouped


def _answer_key(review: "CameraTrapReview", record: dict) -> tuple:
    """What a reviewer said about an item, for telling disagreement apart."""
    boxes = review.boxes(record) or []
    return (review.triage(record), tuple(sorted(review.species(record))),
            tuple(sorted(str(b.get("label", "")) for b in boxes)))


def several_annotators_warning(grouped: "OrderedDict[str, List[dict]]",
                               annotator: Optional[str],
                               review: Optional["CameraTrapReview"] = None) -> Optional[str]:
    if annotator:
        return None if grouped else (
            f"No answers from annotator '{annotator}', so nothing was written; "
            f"check the user id")
    several = [iid for iid, recs in grouped.items() if len(recs) > 1]
    if not several:
        return None
    message = (f"{len(several)} item(s) have several annotators; each is written from "
               "the first by user id (pass --option annotator=<user> to choose)")
    if review is not None:
        differ = [iid for iid in several
                  if len({_answer_key(review, r) for r in grouped[iid]}) > 1]
        if differ:
            shown = ", ".join(differ[:10]) + (f" and {len(differ) - 10} more" if len(differ) > 10 else "")
            message += (f". On {len(differ)} of them the annotators disagree (triage, "
                        f"species or box labels): {shown}. Adjudicate those before publishing")
    return message


def _round(v: float, n: int = 4) -> float:
    return round(float(v), n)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_EXIF_DATE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})[ T]")


def iso_timestamp(raw: Any, timezone: Optional[str] = None) -> Tuple[str, bool]:
    """``(ISO 8601 text, has_offset)`` for a camera's date-time, or ``("", False)``.

    Accepts ``2024-05-14 05:42:10``, the EXIF form ``2024:05:14 05:42:10`` and
    ISO text. A missing UTC offset is taken from ``timezone`` (``+02:00``,
    ``Z``) when given; it is never guessed.
    """
    if raw in (None, ""):
        return "", False
    text = str(raw).strip()
    text = _EXIF_DATE.sub(lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}T", text)
    text = text.replace(" ", "T", 1)
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text, False
    if parsed.tzinfo is None and timezone:
        tz = timezone.strip()
        return parsed.isoformat() + ("Z" if tz.upper() in ("Z", "UTC") else tz), True
    if parsed.tzinfo is None:
        return parsed.isoformat(), False
    out = parsed.isoformat()
    return (out[:-6] + "Z" if out.endswith("+00:00") else out), True


# ---------------------------------------------------------------------------
# MegaDetector
# ---------------------------------------------------------------------------

class MegaDetectorExporter(BaseExporter):
    format_name = "megadetector"
    description = "MegaDetector batch-output JSON (1.4) of the reviewed camera-trap boxes"
    file_extensions = [".json"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not CameraTrapReview(context).usable():
            return False, "No camera-trap questions (an image_annotation or an empty/animal triage radio)"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        review = CameraTrapReview(context, options)
        grouped = records_by_item(context, review, options.get("annotator"))
        warnings: List[str] = []
        several = several_annotators_warning(grouped, options.get("annotator"), review)
        if several:
            warnings.append(several)

        species: "OrderedDict[str, None]" = OrderedDict()
        images: List[dict] = []
        detectors = set()
        for iid, recs in grouped.items():
            record, item = recs[0], context.items.get(iid) or {}
            boxes = review.boxes(record)
            triage = review.triage(record)
            if boxes is not None:
                dets = []
                for box in boxes:
                    dets.append(self._detection(box, species))
                    if box.get("ai_model"):
                        detectors.add(str(box["ai_model"]))
                entry = {"file": item.get("file") or iid, "detections": dets}
                if item.get("frame_rate"):
                    entry["frame_rate"] = item["frame_rate"]
                images.append(entry)
                continue
            # Reviewed as a sequence or a clip: the imported detections, or none.
            carried = item.get("md_detections") or item.get("frame_boxes")
            if not isinstance(carried, dict):
                warnings.append(f"{iid}: no boxes and no imported detections to carry; skipped")
                continue
            for file, dets in carried.items():
                out = []
                if triage != "empty":
                    for det in dets or []:
                        if isinstance(det, dict) and det.get("type") == "bbox":
                            canon = normalize_annotation_object(det, 1.0, 1.0)
                            if canon:
                                out.append(self._detection(canon, species))
                        elif isinstance(det, dict):
                            out.append(det)
                entry = {"file": file, "detections": out}
                if item.get("frame_rate"):
                    entry["frame_rate"] = item["frame_rate"]
                images.append(entry)

        conflict = conflict_warning(triage_conflicts(context, review, options.get("annotator")),
                                    "The MegaDetector export")
        if conflict:
            warnings.append(conflict)
        classes = OrderedDict((str(i), name) for i, name in enumerate(sorted(species), start=1))
        class_id = {name: cid for cid, name in classes.items()}
        for entry in images:
            for det in entry["detections"]:
                if "_species" in det:
                    score = det.pop("_class_conf", None)
                    det["classifications"] = [[class_id[det.pop("_species")],
                                               det["conf"] if score is None else score]]
        payload: Dict[str, Any] = {
            "info": {"format_version": "1.4",
                     "detector": ", ".join(sorted(detectors)) or "unknown",
                     "potato_review": {
                         "exported": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "annotators": sorted({str(r.get("user_id")) for recs in grouped.values()
                                               for r in recs[:1]}),
                         "conf": "1.0 marks a box a reviewer drew or changed"}},
            "detection_categories": dict(MD_CATEGORIES),
            "images": images,
        }
        if classes:
            payload["classification_categories"] = dict(classes)
        os.makedirs(output_path, exist_ok=True)
        path = os.path.join(output_path, options.get("filename", "megadetector_reviewed.json"))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
        return ExportResult(success=True, format_name=self.format_name, files_written=[path],
                            warnings=warnings,
                            stats={"num_images": len(images),
                                   "num_detections": sum(len(e["detections"]) for e in images)})

    @staticmethod
    def _detection(box: dict, species: "OrderedDict[str, None]") -> dict:
        label = str(box.get("label", ""))
        kind = triage_class(label)
        x, y, w, h = box["bbox"]
        conf = float(box["confidence"]) if is_machine(box) and box.get("confidence") is not None else 1.0
        det: Dict[str, Any] = {"category": MD_CATEGORY_ID.get(kind, "1"), "conf": _round(conf, 3),
                               "bbox": [_round(x), _round(y), _round(w), _round(h)]}
        if not is_generic(label):
            species.setdefault(label, None)
            det["_species"] = label
            score = classification_score(box)
            if score is not None:
                det["_class_conf"] = _round(score, 3)
        return det


# ---------------------------------------------------------------------------
# Observations shared by Camtrap DP and Darwin Core
# ---------------------------------------------------------------------------

def observations(context: ExportContext, review: CameraTrapReview,
                 timezone: Optional[str] = None,
                 annotator: Optional[str] = None) -> Iterable[Dict[str, Any]]:
    """One dict per observation, in Camtrap DP terms, plus ``_machine`` / ``_item``.

    From one reviewer per item, as the MegaDetector export does: every
    reviewer's boxes would be separate observations of the same animal.
    """
    grouped = records_by_item(context, review, annotator)
    for iid, recs in grouped.items():
        item = context.items.get(iid) or {}
        event_level = bool(item.get("frames")) or "files" in item
        start, _ = iso_timestamp(item.get("datetime"), timezone)
        end, _ = iso_timestamp(item.get("datetime_end") or item.get("datetime"), timezone)
        for record in recs[:1]:
            user = str(record.get("user_id", ""))
            base = {"_item": item, "_iid": iid, "deploymentID": deployment_of(item),
                    "mediaID": "" if event_level else iid,
                    "eventID": str(item.get("seq_id") or ""),
                    "eventStart": start, "eventEnd": end,
                    "observationLevel": "event" if event_level else "media"}
            n = 0

            def emit(**kw):
                nonlocal n
                n += 1
                row = dict(base, observationID=f"{iid}:{user}:{n}", **kw)
                row.setdefault("classificationMethod", "human")
                row.setdefault("classifiedBy", user)
                row.setdefault("_machine", False)
                return row

            boxes = review.boxes(record) or []
            triage = review.triage(record)
            species = review.species(record)
            if triage == "empty" and not boxes:
                yield emit(observationType="blank")
                continue
            conflict = triage == "empty"
            covered = set()
            for box in boxes:
                label = str(box.get("label", ""))
                x, y, w, h = box["bbox"]
                machine = is_machine(box)
                row = emit(observationType=CAMTRAP_TYPE.get(triage_class(label), "animal"),
                           scientificName="" if is_generic(label) else label, count=1,
                           bboxX=_round(x), bboxY=_round(y), bboxWidth=_round(w), bboxHeight=_round(h),
                           _machine=machine)
                if conflict:
                    row["observationComments"] = CONFLICT_NOTE
                if machine:
                    row["classificationMethod"] = "machine"
                    row["classifiedBy"] = str(box.get("ai_model") or "")
                    # A species name is the classifier's call; a generic
                    # label is the detector's.
                    score = classification_score(box) if not is_generic(label) else None
                    if score is None:
                        score = box.get("confidence")
                    if score is not None:
                        row["classificationProbability"] = _round(score, 3)
                covered.add(label)
                yield row
            if conflict:
                continue
            for name in species:
                if name not in covered:
                    yield emit(observationType="animal", scientificName=name)
            if not boxes and not species and triage:
                yield emit(observationType=CAMTRAP_TYPE.get(triage, "unclassified"))


def deployment_of(item: dict) -> str:
    for key in ("deployment_id", "deploymentID", "location", "location_id"):
        if item.get(key) not in (None, ""):
            return str(item[key])
    return "unknown"


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coords(item: dict) -> Tuple[Optional[float], Optional[float]]:
    lat = _number(item.get("latitude", item.get("lat")))
    lon = _number(item.get("longitude", item.get("lon", item.get("lng"))))
    return lat, lon


def _write_csv(path: str, columns: List[str], rows: Iterable[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})


# ---------------------------------------------------------------------------
# Camtrap DP
# ---------------------------------------------------------------------------

class CamtrapDPExporter(BaseExporter):
    format_name = "camtrap_dp"
    description = "Camtrap DP 1.0 data package (deployments, media, observations, datapackage.json)"
    file_extensions = [".csv", ".json"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not CameraTrapReview(context).usable():
            return False, "No camera-trap questions (an image_annotation or an empty/animal triage radio)"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        tz = options.get("timezone")
        review = CameraTrapReview(context, options)
        warnings: List[str] = []
        os.makedirs(output_path, exist_ok=True)

        media_rows, deployments = [], OrderedDict()
        missing_tz = 0
        for iid, item in context.items.items():
            if not isinstance(item, dict):
                continue
            dep = deployment_of(item)
            files = item.get("files") if isinstance(item.get("files"), list) else None
            stamps = []
            frame_times = item.get("frame_datetimes") if isinstance(item.get("frame_datetimes"), list) else []
            for index, file in enumerate(files or [item.get("file") or iid]):
                raw = (frame_times[index] if index < len(frame_times) else None) if files \
                    else item.get("datetime")
                stamp, has_tz = iso_timestamp(raw, tz)
                if stamp and not has_tz:
                    missing_tz += 1
                stamps.append(stamp)
                media_rows.append({
                    "mediaID": iid if not files else f"{iid}:{index + 1}",
                    "deploymentID": dep,
                    "captureMethod": options.get("capture_method", ""),
                    "timestamp": stamp,
                    "filePath": str(file),
                    "filePublic": "false",
                    "fileName": os.path.basename(str(file)),
                    "fileMediatype": mimetypes.guess_type(str(file))[0] or "",
                })
            d = deployments.setdefault(dep, {"deploymentID": dep, "locationID": str(item.get("location") or ""),
                                             "locationName": str(item.get("location") or ""),
                                             "_stamps": [], "_coords": set()})
            d["_stamps"].extend(s for s in stamps if s)
            lat, lon = _coords(item)
            if lat is not None and lon is not None:
                d["_coords"].add((lat, lon))
        if missing_tz:
            warnings.append(f"{missing_tz} timestamp(s) have no UTC offset, which Camtrap DP requires; "
                            "pass --option timezone=+HH:MM")

        no_coords, lats, lons, all_stamps = [], [], [], []
        for dep, d in deployments.items():
            stamps = sorted(d.pop("_stamps"))
            coords = d.pop("_coords")
            all_stamps.extend(stamps)
            d["deploymentStart"] = stamps[0] if stamps else ""
            d["deploymentEnd"] = stamps[-1] if stamps else ""
            if coords:
                lat, lon = sorted(coords)[0]
                d["latitude"], d["longitude"] = lat, lon
                lats.append(lat); lons.append(lon)
                if len(coords) > 1:
                    warnings.append(f"deployment {dep}: items give {len(coords)} different coordinates; "
                                    "the first is used")
            else:
                no_coords.append(dep)
        if no_coords:
            warnings.append(f"deployment(s) {', '.join(no_coords)} have no latitude/longitude "
                            "(required by Camtrap DP); add them to deployments.csv")
        if any(not d["deploymentStart"] for d in deployments.values()):
            warnings.append("some deployments have no timestamps, so deploymentStart/End are empty "
                            "(required by Camtrap DP)")

        annotator = options.get("annotator")
        several = several_annotators_warning(records_by_item(context, review, annotator), annotator, review)
        if several:
            warnings.append(several)
        obs = list(observations(context, review, tz, annotator))
        conflict = conflict_warning(triage_conflicts(context, review, annotator), "The Camtrap DP export")
        if conflict:
            warnings.append(conflict)
        taxa = sorted({o["scientificName"] for o in obs if o.get("scientificName")})
        levels = sorted({o["observationLevel"] for o in obs}) or ["media"]

        files = []
        for name, columns, rows in (("deployments.csv", DEPLOYMENT_COLUMNS, deployments.values()),
                                    ("media.csv", MEDIA_COLUMNS, media_rows),
                                    ("observations.csv", OBSERVATION_COLUMNS, obs)):
            path = os.path.join(output_path, name)
            _write_csv(path, columns, rows)
            files.append(path)

        title = options.get("title") or context.config.get("annotation_task_name") or "Camera-trap review"
        package: Dict[str, Any] = {
            "profile": f"{CAMTRAP_BASE}/camtrap-dp-profile.json",
            "name": re.sub(r"[^a-z0-9._-]+", "-", str(title).lower()).strip("-") or "camera-trap-review",
            "created": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "title": str(title),
            "contributors": ([{"title": options["contributor"], "role": "contact"}]
                             if options.get("contributor") else []),
            "project": {
                "title": str(title),
                "samplingDesign": options.get("sampling_design", ""),
                "captureMethod": ([options["capture_method"]] if options.get("capture_method") else []),
                "individualAnimals": False,
                "observationLevel": levels,
            },
            "spatial": ({"type": "Polygon", "bbox": [min(lons), min(lats), max(lons), max(lats)],
                         "coordinates": [[[min(lons), min(lats)], [max(lons), min(lats)],
                                          [max(lons), max(lats)], [min(lons), max(lats)],
                                          [min(lons), min(lats)]]]}
                        if lats else None),
            "temporal": {"start": min(all_stamps)[:10] if all_stamps else "",
                         "end": max(all_stamps)[:10] if all_stamps else ""},
            "taxonomic": [{"scientificName": t} for t in taxa],
            "resources": [{"name": n, "path": f"{n}.csv", "profile": "tabular-data-resource",
                           "format": "csv", "mediatype": "text/csv", "encoding": "utf-8",
                           "schema": f"{CAMTRAP_BASE}/{n}-table-schema.json"}
                          for n in ("deployments", "media", "observations")],
        }
        if options.get("license"):
            package["licenses"] = [{"name": options["license"], "scope": "data"}]
        for key, missing in (("contributor", not options.get("contributor")),
                             ("sampling_design", not options.get("sampling_design")),
                             ("capture_method", not options.get("capture_method"))):
            if missing:
                warnings.append(f"datapackage.json: pass --option {key}=... (the profile requires it)")
        if package["spatial"] is None:
            warnings.append("datapackage.json: spatial is empty because no item has coordinates")
        path = os.path.join(output_path, "datapackage.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(package, handle, indent=2)
        files.append(path)
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings,
                            stats={"num_deployments": len(deployments), "num_media": len(media_rows),
                                   "num_observations": len(obs)})


# ---------------------------------------------------------------------------
# Darwin Core
# ---------------------------------------------------------------------------

class DarwinCoreExporter(BaseExporter):
    format_name = "darwin_core"
    description = "Darwin Core occurrence CSV of the identified animals in a camera-trap review"
    file_extensions = [".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not CameraTrapReview(context).usable():
            return False, "No camera-trap questions (an image_annotation or an empty/animal triage radio)"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        forced = options.get("basis_of_record")
        if forced and forced not in ("MachineObservation", "HumanObservation"):
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["basis_of_record must be MachineObservation or HumanObservation"])
        review = CameraTrapReview(context, options)
        annotator = options.get("annotator")
        rows, unnamed = [], 0
        for o in observations(context, review, options.get("timezone"), annotator):
            if o["observationType"] != "animal":
                continue
            if not o.get("scientificName"):
                unnamed += 1
                continue
            item = o["_item"]
            lat, lon = _coords(item)
            media = item.get("image_url") or item.get("video_url") or item.get("file") or ""
            if isinstance(item.get("frames"), list):
                media = " | ".join(str(f.get("url", "")) for f in item["frames"] if isinstance(f, dict))
            rows.append({
                "occurrenceID": o["observationID"],
                "basisOfRecord": forced or ("MachineObservation" if o["_machine"] else "HumanObservation"),
                "eventID": o.get("eventID") or o["_iid"],
                "eventDate": o.get("eventStart", ""),
                "scientificName": o["scientificName"],
                "individualCount": o.get("count", ""),
                "occurrenceStatus": "present",
                "decimalLatitude": lat if lat is not None else "",
                "decimalLongitude": lon if lon is not None else "",
                "geodeticDatum": "EPSG:4326" if lat is not None and lon is not None else "",
                "locationID": item.get("location", ""),
                "associatedMedia": media,
                "identifiedBy": o.get("classifiedBy", ""),
                "identificationRemarks": "; ".join(filter(None, (
                    "model identification, not changed by the reviewer" if o["_machine"] else "",
                    o.get("observationComments", "") if o.get("observationComments") == CONFLICT_NOTE
                    else ""))),
            })
        os.makedirs(output_path, exist_ok=True)
        path = os.path.join(output_path, "occurrence.csv")
        _write_csv(path, DWC_COLUMNS, rows)
        warnings = []
        several = several_annotators_warning(records_by_item(context, review, annotator), annotator, review)
        if several:
            warnings.append(several)
        if unnamed:
            warnings.append(f"{unnamed} animal observation(s) without a species name were left out "
                            "(Darwin Core needs scientificName)")
        conflict = conflict_warning(triage_conflicts(context, review, annotator), "The Darwin Core export")
        if conflict:
            warnings.append(conflict)
        return ExportResult(success=True, format_name=self.format_name, files_written=[path],
                            warnings=warnings, stats={"num_occurrences": len(rows)})
