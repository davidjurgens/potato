"""
Open Images importer (CSV boxes, points, and segmentation index).

Open Images ships annotations as CSV, one row per box::

    ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,IsOccluded,...

Two properties account for most misreads of this format:

* **The column order is ``XMin, XMax, YMin, YMax``** — both X values first,
  then both Y values. Every other CSV-ish format in this package interleaves
  them (``x1 y1 x2 y2``), so the natural reading swaps a box's width for its
  vertical extent. On roughly square objects the result still looks like a box
  in about the right place, which is why this is worth naming rather than
  assuming.
* **Coordinates are already normalized to [0, 1]**, which happens to be the
  same space Potato stores. They still go through ``to_client_object`` — with
  the image treated as a 1x1 unit square — so there remains exactly one
  definition of the client shape, and the identity is deliberate rather than
  a copy that happens to work.

``LabelName`` is a Freebase MID such as ``/m/01g317``, meaningless on its own.
``class-descriptions-boxable.csv`` maps MIDs to display names; when it is found
beside the annotations (or passed via options) labels are resolved, and when it
is not, every class is imported as its MID and the import says so.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix, safe_instance_id
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: The header that identifies a boxable annotations CSV.
BOX_COLUMNS = {"ImageID", "LabelName", "XMin", "XMax", "YMin", "YMax"}

#: Point annotations (Open Images V7) use a different, simpler header.
POINT_COLUMNS = {"ImageID", "LabelName", "X", "Y"}

#: Filenames Open Images uses for the MID -> name mapping.
DESCRIPTION_FILES = ("class-descriptions-boxable.csv", "class-descriptions.csv",
                     "oidv7-class-descriptions.csv")

#: Boxes are normalized already, so the "image" is a unit square. Naming it
#: makes the identity intentional rather than an accident of both being [0, 1].
UNIT = 1.0

#: Per-box flags Open Images ships. Preserved so a filtered re-export can
#: reproduce the benchmark's own exclusions.
FLAG_COLUMNS = ("IsOccluded", "IsTruncated", "IsGroupOf", "IsDepiction",
                "IsInside")


class OpenImagesImporter(BaseAnnotationImporter):
    format_name = "openimages"
    description = "Open Images CSV (boxes or points)"
    file_extensions = [".csv"]

    def detect(self, data: Any) -> bool:
        if isinstance(data, dict) and "openimages_rows" in data:
            return True
        return False

    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        csv_files = sorted(base.glob("*.csv")) or sorted(base.rglob("*.csv"))
        annotations = None
        descriptions = None
        for path in csv_files:
            if path.name in DESCRIPTION_FILES:
                descriptions = path
                continue
            header = self._header(path)
            if header and (BOX_COLUMNS <= header or POINT_COLUMNS <= header):
                annotations = annotations or path
        if annotations is None:
            raise ValueError(
                f"No Open Images annotation CSV under {base}. Expected a file "
                f"whose header includes {', '.join(sorted(BOX_COLUMNS))}.")
        if descriptions is None:
            descriptions = next(
                (base / n for n in DESCRIPTION_FILES if (base / n).exists()),
                None)
        return self.parse_file(annotations, descriptions, options)

    def parse_file(self, annotations: Path, descriptions: Optional[Path],
                   options: Optional[dict] = None) -> ImportResult:
        with open(annotations, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        names = self._read_descriptions(descriptions)
        return self.parse({"openimages_rows": rows, "names": names,
                           "source": annotations.name}, options)

    @staticmethod
    def _header(path: Path):
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                first = next(csv.reader(fh), None)
        except (OSError, StopIteration, UnicodeDecodeError):
            return None
        return set(first or [])

    @staticmethod
    def _read_descriptions(path: Optional[Path]) -> Dict[str, str]:
        """MID -> display name. The file is headerless: ``/m/01g317,Person``."""
        if not path or not Path(path).exists():
            return {}
        names: Dict[str, str] = {}
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 2 and row[0].startswith("/"):
                        names[row[0]] = row[1]
        except (OSError, UnicodeDecodeError):
            return {}
        return names

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError(
                "Not an Open Images CSV. Point --input at the directory "
                "holding the annotations CSV, so the class-descriptions file "
                "beside it can be found too.")

        rows: List[dict] = list(data["openimages_rows"])
        names: Dict[str, str] = data.get("names") or {}

        result = ImportResult()
        labels: Dict[str, dict] = {}
        tools: set = set()
        by_image: Dict[str, List[dict]] = {}
        unresolved: set = set()
        skipped = 0

        for lineno, row in enumerate(rows, start=2):
            image_id = (row.get("ImageID") or "").strip()
            mid = (row.get("LabelName") or "").strip()
            if not image_id or not mid:
                continue

            label = names.get(mid, mid)
            if mid not in names and mid.startswith("/"):
                unresolved.add(mid)

            obj = self._object(row, label, lineno, result.warnings)
            if obj is None:
                skipped += 1
                continue
            by_image.setdefault(image_id, []).append(obj)
            labels.setdefault(label, {"name": label})
            tools.add(obj["type"])

        for image_id, objects in sorted(by_image.items()):
            file_name = f"{image_id}.jpg"
            result.images.append(ImportedImage(
                instance_id=safe_instance_id(image_id),
                file_name=file_name,
                # Coordinates are normalized, so no real pixel dimensions are
                # needed or recorded. 0 would break exporters that divide by
                # them, so the unit square is stated explicitly.
                width=1,
                height=1,
                objects=objects,
                extra={"image_url": apply_url_prefix(file_name, options)},
            ))

        if unresolved:
            result.warnings.append(
                f"{len(unresolved)} class id(s) could not be resolved to names "
                f"(e.g. {sorted(unresolved)[0]}) and were imported as their "
                f"Freebase MIDs. Put class-descriptions-boxable.csv beside the "
                f"annotations to get readable labels.")
        if skipped:
            result.warnings.append(
                f"{skipped} row(s) had unusable geometry and were skipped.")
        result.warnings.append(
            "Open Images stores coordinates already normalized to [0, 1], so "
            "each item records a 1x1 unit size rather than real pixels. "
            "Exports that need pixel dimensions (COCO area, YOLO) should be "
            "run after adding image_width/image_height to the data file.")

        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = sorted(tools)
        result.summarize()
        return result

    # ------------------------------------------------------------------

    def _object(self, row, label, lineno, warnings):
        def num(key):
            try:
                return float(row[key])
            except (KeyError, TypeError, ValueError):
                return None

        if "XMin" in row:
            # X's together, then Y's -- NOT x1 y1 x2 y2.
            x_min, x_max = num("XMin"), num("XMax")
            y_min, y_max = num("YMin"), num("YMax")
            if None in (x_min, x_max, y_min, y_max):
                return None
            w, h = x_max - x_min, y_max - y_min
            if w <= 0 or h <= 0:
                warnings.append(
                    f"row {lineno}: box has non-positive extent; skipped.")
                return None
            obj = to_client_object("bbox", label, img_w=UNIT, img_h=UNIT,
                                   bbox=[x_min, y_min, w, h])
        elif "X" in row and "Y" in row:
            x, y = num("X"), num("Y")
            if x is None or y is None:
                return None
            obj = to_client_object("landmark", label, img_w=UNIT, img_h=UNIT,
                                   points=[[x, y]])
        else:
            return None

        if obj is None:
            return None

        attributes = {}
        for flag in FLAG_COLUMNS:
            if row.get(flag) not in (None, ""):
                try:
                    attributes[flag] = bool(int(row[flag]))
                except (TypeError, ValueError):
                    pass
        # IsGroupOf is Open Images' crowd flag; map it so a COCO export keeps
        # the distinction instead of asserting one giant object.
        if attributes.get("IsGroupOf"):
            obj["iscrowd"] = 1
        if row.get("Confidence") not in (None, ""):
            try:
                attributes["confidence"] = float(row["Confidence"])
            except (TypeError, ValueError):
                pass
        if attributes:
            obj["attributes"] = attributes
        return obj
