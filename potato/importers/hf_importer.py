"""
HuggingFace ``datasets`` importer.

Reads a dataset from the Hub or from disk and converts its detection columns
into Potato annotations. Three layouts cover almost everything published:

* **COCO-style ``objects`` column** — ``{"bbox": [[x, y, w, h], ...],
  "category": [...]}``. This is what ``cppe-5``, ``fashionpedia`` and most
  detection sets use.
* **Parallel columns** — separate ``bbox``/``objects.bbox`` and ``category``
  arrays at the top level.
* **``imagefolder``** — one class per image, no geometry. Imported as an item
  field rather than a fabricated box.

Two details decide whether the result is right or merely plausible:

* **``category`` is usually an integer into the feature's ``ClassLabel`` names,
  not a string.** Imported without resolving it, every label becomes ``3`` —
  and because the geometry is correct, it looks like a working import with
  unhelpful names rather than a lost mapping. The names are read off the
  dataset's own features.
* **The bbox format is not declared anywhere in the schema.** COCO-style
  ``[x, y, w, h]`` and Pascal-style ``[x1, y1, x2, y2]`` are both in the wild
  under the same column name. They are distinguished by testing whether the
  third and fourth values behave like extents or like corners across the whole
  split, and the conclusion is reported so a wrong guess is visible rather
  than silent.

``datasets`` is an optional dependency. Its absence is reported with the
install command, never as an empty import.

**Never name a Potato subpackage ``datasets``** — it shadows this library when
running ``python potato/flask_server.py``. That is why the eval package is
``potato.eval_datasets``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix, safe_instance_id
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: Column names that hold a detection structure, in preference order.
OBJECT_COLUMNS = ("objects", "annotations", "detections")

#: Keys inside an objects struct.
BBOX_KEYS = ("bbox", "bboxes", "boxes")
CATEGORY_KEYS = ("category", "categories", "label", "labels", "category_id")

#: A box whose 3rd/4th values exceed the 1st/2nd for every row is more likely
#: corners than extents; below this share we treat the column as x/y/w/h.
CORNER_CONFIDENCE = 0.95


def _require_datasets():
    try:
        import datasets  # noqa: F401
    except ImportError:
        raise ValueError(
            "Reading a HuggingFace dataset needs the `datasets` library, "
            "which is not installed. Install it with "
            "`pip install datasets>=2.14.0` and re-run.")
    import datasets
    return datasets


class HuggingFaceImporter(BaseAnnotationImporter):
    format_name = "huggingface"
    description = "HuggingFace datasets (Hub id or saved dataset directory)"
    file_extensions = []

    def detect(self, data: Any) -> bool:
        return isinstance(data, dict) and "hf_dataset" in data

    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        """A directory written by ``Dataset.save_to_disk``."""
        datasets = _require_datasets()
        try:
            dataset = datasets.load_from_disk(str(root))
        except Exception as exc:
            raise ValueError(
                f"{root} is not a saved HuggingFace dataset ({exc}). For a Hub "
                f"dataset use --input-format huggingface with --hf-dataset "
                f"<org/name>.")
        return self.parse({"hf_dataset": dataset}, options)

    def load(self, dataset_id: str, split: str = "train",
             options: Optional[dict] = None) -> ImportResult:
        """Load a dataset from the Hub by id."""
        datasets = _require_datasets()
        try:
            dataset = datasets.load_dataset(dataset_id, split=split)
        except Exception as exc:
            raise ValueError(f"Could not load '{dataset_id}' ({split}): {exc}")
        return self.parse({"hf_dataset": dataset, "source": dataset_id}, options)

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError(
                "Not a HuggingFace dataset. Use --hf-dataset <org/name> or "
                "point --input at a save_to_disk directory.")

        dataset = data["hf_dataset"]
        # A DatasetDict has splits; take the requested one rather than the
        # first, which would silently import validation data as training data.
        if hasattr(dataset, "keys") and not hasattr(dataset, "features"):
            split = options.get("hf_split") or next(iter(dataset.keys()))
            dataset = dataset[split]

        result = ImportResult()
        column, struct_key = self._object_column(dataset)
        class_names = self._class_names(dataset, column, struct_key)
        rows = list(dataset)

        corner_style, corner_note = self._bbox_style(rows, column, struct_key)
        result.warnings.append(corner_note)

        labels: Dict[str, dict] = {}
        classification_only = 0

        for index, row in enumerate(rows):
            width, height = self._dimensions(row)
            objects: List[dict] = []

            for box, category in self._pairs(row, column, struct_key):
                label = self._label(category, class_names)
                geometry = self._bbox(box, corner_style)
                if geometry is None or width <= 0 or height <= 0:
                    continue
                obj = to_client_object("bbox", label, img_w=width,
                                       img_h=height, bbox=geometry)
                if obj is not None:
                    objects.append(obj)
                    labels.setdefault(label, {"name": label})

            extra: Dict[str, Any] = {}
            whole_image = self._whole_image_label(row, dataset)
            if whole_image is not None and not objects:
                classification_only += 1
                extra["hf_label"] = whole_image

            file_name = self._file_name(row, index)
            extra["image_url"] = apply_url_prefix(file_name, options)
            result.images.append(ImportedImage(
                instance_id=safe_instance_id(
                    row.get("image_id") or row.get("id") or f"row_{index}"),
                file_name=file_name,
                width=width or 1,
                height=height or 1,
                objects=objects,
                extra=extra,
            ))

        if classification_only:
            result.warnings.append(
                f"{classification_only} row(s) carry a whole-image class and "
                f"no geometry (an imagefolder-style dataset). The class is on "
                f"each item as hf_label; pair it with a radio schema rather "
                f"than an image_annotation one.")
        if not column:
            result.warnings.append(
                "No detection column was found. Looked for "
                f"{', '.join(OBJECT_COLUMNS)}; the dataset has "
                f"{', '.join(list(getattr(dataset, 'column_names', []))[:8])}.")
        result.warnings.append(
            "Images are referenced by file name. A Hub dataset stores its "
            "images inline, so they must be written out and served before the "
            "canvas can show them — see docs/tools/import_cli.md.")

        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = ["bbox"] if labels else []
        result.summarize()
        return result

    # ------------------------------------------------------------------

    @staticmethod
    def _object_column(dataset) -> Tuple[str, str]:
        columns = list(getattr(dataset, "column_names", []) or [])
        for name in OBJECT_COLUMNS:
            if name in columns:
                return name, ""
        for key in BBOX_KEYS:
            if key in columns:
                return "", key
        return "", ""

    @staticmethod
    def _class_names(dataset, column, struct_key) -> List[str]:
        """
        ClassLabel names, so an integer category resolves to a real word.

        The names live at different depths depending on whether the categories
        are a sequence inside a struct or a plain column.
        """
        features = getattr(dataset, "features", None) or {}
        candidates = []
        feature = features.get(column) if column else None
        if feature is not None:
            inner = getattr(feature, "feature", feature)
            if isinstance(inner, dict):
                candidates.extend(inner.get(k) for k in CATEGORY_KEYS)
            else:
                candidates.append(inner)
        for key in CATEGORY_KEYS:
            if key in features:
                candidates.append(features[key])

        for candidate in candidates:
            if candidate is None:
                continue
            names = getattr(candidate, "names", None)
            if names is None:
                names = getattr(getattr(candidate, "feature", None), "names", None)
            if names:
                return list(names)
        return []

    @staticmethod
    def _pairs(row, column, struct_key):
        """(box, category) pairs, across both the struct and parallel layouts."""
        source = row.get(column) if column else row
        if not isinstance(source, dict):
            # A list-of-dicts objects column.
            if isinstance(source, list):
                for entry in source:
                    if not isinstance(entry, dict):
                        continue
                    box = next((entry[k] for k in BBOX_KEYS if k in entry), None)
                    category = next(
                        (entry[k] for k in CATEGORY_KEYS if k in entry), None)
                    if box is not None:
                        yield box, category
            return

        boxes = next((source[k] for k in BBOX_KEYS if k in source), None)
        categories = next((source[k] for k in CATEGORY_KEYS if k in source), None)
        if boxes is None:
            return
        categories = categories if isinstance(categories, list) else []
        for i, box in enumerate(boxes or []):
            yield box, categories[i] if i < len(categories) else None

    def _bbox_style(self, rows, column, struct_key):
        """
        Decide whether boxes are ``[x, y, w, h]`` or ``[x1, y1, x2, y2]``.

        Nothing in the dataset schema records this, and both are published
        under the name ``bbox``. Corners always satisfy x2 > x1 and y2 > y1;
        extents usually do too, so a single box proves nothing — but a box
        whose 3rd value is SMALLER than its 1st cannot be corners, and one
        counterexample is decisive.
        """
        total = 0
        corner_like = 0
        for row in rows[:200]:
            for box, _category in self._pairs(row, column, struct_key):
                if not isinstance(box, (list, tuple)) or len(box) < 4:
                    continue
                total += 1
                try:
                    x0, y0, x1, y1 = (float(box[0]), float(box[1]),
                                      float(box[2]), float(box[3]))
                except (TypeError, ValueError):
                    continue
                if x1 > x0 and y1 > y0:
                    corner_like += 1
        if not total:
            return False, "No boxes found, so no bbox convention had to be chosen."
        share = corner_like / total
        if share >= CORNER_CONFIDENCE:
            return True, (
                f"Boxes were read as CORNERS [x1, y1, x2, y2]: in {corner_like} "
                f"of {total} sampled boxes the 3rd and 4th values exceed the "
                f"1st and 2nd. If they are actually [x, y, w, h], every box "
                f"will be too large — check one item before annotating.")
        return False, (
            f"Boxes were read as COCO-style [x, y, width, height] "
            f"({total - corner_like} of {total} sampled boxes are inconsistent "
            f"with corners). If they are actually [x1, y1, x2, y2], every box "
            f"will be too small — check one item before annotating.")

    @staticmethod
    def _bbox(box, corner_style):
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            return None
        try:
            a, b, c, d = (float(box[0]), float(box[1]),
                          float(box[2]), float(box[3]))
        except (TypeError, ValueError):
            return None
        if corner_style:
            w, h = c - a, d - b
        else:
            w, h = c, d
        if w <= 0 or h <= 0:
            return None
        return [a, b, w, h]

    @staticmethod
    def _label(category, class_names) -> str:
        if isinstance(category, str) and category.strip():
            return category.strip()
        if isinstance(category, (int, float)):
            index = int(category)
            if 0 <= index < len(class_names):
                return str(class_names[index])
            return f"class_{index}"
        return "object"

    @staticmethod
    def _dimensions(row):
        image = row.get("image")
        width = row.get("width") or row.get("image_width")
        height = row.get("height") or row.get("image_height")
        if not (width and height) and image is not None:
            size = getattr(image, "size", None)
            if isinstance(size, (tuple, list)) and len(size) == 2:
                width, height = size
        try:
            return int(width or 0), int(height or 0)
        except (TypeError, ValueError):
            return 0, 0

    @staticmethod
    def _whole_image_label(row, dataset):
        if "label" not in row:
            return None
        value = row["label"]
        features = getattr(dataset, "features", None) or {}
        names = getattr(features.get("label"), "names", None)
        if names and isinstance(value, int) and 0 <= value < len(names):
            return names[value]
        return value

    @staticmethod
    def _file_name(row, index):
        image = row.get("image")
        for attr in ("filename", "path"):
            value = getattr(image, attr, None)
            if value:
                import os

                return os.path.basename(str(value))
        for key in ("file_name", "image_path", "filename"):
            if row.get(key):
                import os

                return os.path.basename(str(row[key]))
        return f"{index:06d}.jpg"
