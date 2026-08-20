"""
Annotation Importer CLI

Turns an existing annotation file into a runnable Potato project: a data file,
a config, and a README.

Usage:
    potato import --input instances_val2017.json --image-dir /data/val2017 \\
        --output-dir my-project/ --schema-name object_detection
    python -m potato.importers --list-formats

The generated project is runnable as-is:
    python potato/flask_server.py start my-project/config.yaml -p 8000
"""

import argparse
import json
import logging
import os
import sys
from typing import List, Optional

import yaml

from .registry import import_registry

logger = logging.getLogger(__name__)


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        prog="potato import",
        description=(
            "Import existing annotations into a runnable Potato project. "
            "COCO files are read as-is: polygons, uncompressed RLE, compressed "
            "RLE strings and crowd regions all work without preprocessing."
        ),
    )

    parser.add_argument("--input", "-i", help="Input annotation file (JSON)")
    parser.add_argument(
        "--input-format", "-f",
        help="Input format name. Auto-detected when omitted.")
    parser.add_argument(
        "--output-dir", "-o",
        help="Directory to write the generated project into")
    parser.add_argument(
        "--schema-name", default="image_annotation",
        help="Name of the generated annotation scheme (default: image_annotation)")
    parser.add_argument(
        "--image-dir",
        help=("Directory holding the images. Used to read width/height when "
              "the file's images[] entries lack them (needs Pillow)."))
    parser.add_argument(
        "--image-url-prefix", default="",
        help=("Prefix joined to each file_name to form the served image URL. "
              "For images served by Potato itself, put them in <task_dir>/media "
              "and pass /media -- otherwise use the absolute URL they are "
              "hosted at."))
    parser.add_argument(
        "--config-only", action="store_true",
        help="Write config.yaml only, leaving any existing data file alone")
    parser.add_argument(
        "--rle-as-polygon", action="store_true",
        help=("Trace RLE masks into polygons for editability. LOSSY: holes are "
              "dropped and the contour will not re-rasterize to the source mask."))
    parser.add_argument(
        "--keypoints", action="store_true",
        help="Import COCO keypoints as landmark annotations")
    parser.add_argument(
        "--no-merge-crowd", action="store_true",
        help=("Keep each iscrowd=1 region separate instead of merging them per "
              "label. COCO allows only one crowd annotation per category per "
              "image, so merging is normally correct."))
    parser.add_argument(
        "--via-label-key", metavar="ATTR",
        help=("Which VIA region attribute holds the class. Inferred from the "
              "project's own _via_attributes when omitted."))
    parser.add_argument(
        "--extract-media", metavar="DIR",
        help=("Write images out of a WebDataset shard into DIR. Without it the "
              "images stay inside the .tar, which no web server can read, and "
              "the canvas is blank."))
    parser.add_argument(
        "--hf-dataset", metavar="ID",
        help="HuggingFace Hub dataset id to import, e.g. cppe-5")
    parser.add_argument(
        "--hf-split", default="train",
        help="Split to read from a HuggingFace dataset (default: train)")
    parser.add_argument(
        "--seed-user", metavar="NAME",
        help=("Also write the imported annotations as NAME's saved work. This "
              "FABRICATES AN ANNOTATOR and exists so import->export can be "
              "verified without a human opening each item. Without it, imported "
              "annotations are pre-annotations: they show as a starting point "
              "and are only stored once a real annotator saves."))
    parser.add_argument(
        "--list-formats", action="store_true",
        help="List supported import formats and exit")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging")

    return parser.parse_args(args)


def _probe_dimensions(data: dict, image_dir: str) -> int:
    """Fill missing images[].width/height by reading the files. Returns count."""
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit(
            "--image-dir needs Pillow to read image sizes. Install it with "
            "`pip install Pillow`, or add width/height to the images[] entries."
        )

    filled = 0
    for img in data.get("images", []):
        if not isinstance(img, dict):
            continue
        if img.get("width") and img.get("height"):
            continue
        path = os.path.join(image_dir, str(img.get("file_name") or ""))
        if not os.path.isfile(path):
            continue
        try:
            with Image.open(path) as handle:
                img["width"], img["height"] = handle.size
            filled += 1
        except Exception as exc:
            logger.warning("Could not read size of %s: %s", path, exc)
    return filled


def _build_config(schema_name: str, result, data_file: str) -> dict:
    """Generate a runnable config for the imported project."""
    return {
        "port": 8000,
        "annotation_task_name": f"{schema_name} (imported)",
        "task_dir": ".",
        "output_annotation_dir": "annotation_output/",
        "data_files": [data_file],
        "item_properties": {
            "id_key": "id",
            "text_key": "image_url",
        },
        "user_config": {
            "allow_all_users": True,
            "users": [],
        },
        "site_dir": "default",
        # Imported annotations arrive as pre-annotations: every annotator sees
        # them as a starting point, and their corrections replace them on save.
        # They are deliberately NOT written into anyone's user_state, which
        # would make machine output indistinguishable from human work and
        # fabricate agreement between annotators who never touched the item.
        "pre_annotation": {
            "enabled": True,
            "field": "predictions",
            "allow_modification": True,
        },
        "annotation_schemes": [{
            "annotation_type": "image_annotation",
            "name": schema_name,
            "description": "Correct the imported annotations",
            "source_field": "image_url",
            "tools": list(result.tools),
            # Correcting an imported boundary means working at the pixel level,
            # so both are on by default.
            "zoom_enabled": True,
            "pan_enabled": True,
            "labels": [dict(label) for label in result.labels],
        }],
    }


def _write_readme(path: str, config_name: str, result, source: str) -> None:
    tools = ", ".join(result.tools)
    with open(path, "w") as f:
        f.write(f"""# Imported annotation project

Generated by `potato import` from `{os.path.basename(source)}`.

- **Images:** {result.stats.get('num_images', 0)}
- **Annotations:** {result.stats.get('num_annotations', 0)}
- **Categories:** {result.stats.get('num_categories', 0)}
- **Tools enabled:** {tools}

## Run it

```bash
python potato/flask_server.py start {config_name} -p 8000
```

The imported annotations appear pre-populated on each image. Edit them as
normal; your corrections replace the imported ones as soon as you save.

## Export back out

```bash
python -m potato.export -c {config_name} -f coco -o ./export/
```

Category IDs are preserved via `label_id` on each label, so the exported file
keeps the original (often sparse) COCO category numbering.

## Notes

- Imported annotations are *pre-annotations*. They are shown to every annotator
  as a starting point and are only stored once someone saves, so an untouched
  item exports as empty rather than as fabricated agreement.
- Brush strokes edit the label-level mask. Imported per-instance masks are kept
  separate (keyed `label#instance`) and are preserved, but cannot yet be
  painted into individually.
""")


def _detect_directory_format(root: str):
    """
    Guess a directory dataset's format from its signature files.

    Deliberately conservative: an ambiguous tree returns None so the user is
    asked, rather than being handed a silently wrong import.

    Order matters. The checks run from most specific marker to least: a KITTI
    tree also contains ``*.txt`` files that a naive YOLO check would claim, and
    a Cityscapes tree is full of ``*.json`` that LabelMe would happily accept
    and misread. Each format is therefore identified by something only it has.
    """
    import csv as _csv
    import json as _json
    import tarfile as _tarfile
    import xml.etree.ElementTree as _ET
    from pathlib import Path

    base = Path(root)

    # --- Marker files unique to one format -------------------------------
    # MOT: a sequence directory, or a folder of them.
    if ((base / "gt" / "gt.txt").exists() or (base / "seqinfo.ini").exists()
            or any((d / "seqinfo.ini").exists() or (d / "gt" / "gt.txt").exists()
                   for d in base.iterdir() if d.is_dir())):
        return "mot"

    # KITTI: label_2/ is the devkit's own name and nothing else uses it.
    if any((base / n).is_dir() for n in ("label_2", "training/label_2")):
        return "kitti"

    # DAVIS: indexed PNG masks under Annotations/.
    if (base / "Annotations").is_dir() and list(
            (base / "Annotations").rglob("*.png")):
        return "davis"

    # Cityscapes: the suffix is part of the format's own convention.
    if next(base.rglob("*_gtFine_polygons.json"), None) is not None:
        return "cityscapes"
    if next(base.rglob("*_gtCoarse_polygons.json"), None) is not None:
        return "cityscapes"

    # A HuggingFace save_to_disk directory.
    if (base / "dataset_info.json").exists() and (
            (base / "state.json").exists() or list(base.glob("*.arrow"))):
        return "huggingface"

    # WebDataset: tar shards.
    if any(_tarfile.is_tarfile(p) for p in list(base.glob("*.tar"))[:3]):
        return "webdataset"

    if any((base / n).exists() for n in ("data.yaml", "data.yml", "dataset.yaml")):
        return "yolo"
    if (base / "labels").is_dir() or list(base.glob("*/labels")):
        return "yolo"

    # Open Images: a CSV whose header carries the boxable columns.
    for path in list(base.glob("*.csv"))[:5]:
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                header = set(next(_csv.reader(fh), []) or [])
        except (OSError, StopIteration, UnicodeDecodeError):
            continue
        if {"ImageID", "LabelName", "XMin", "XMax"} <= header:
            return "openimages"

    # CVAT and Pascal VOC are BOTH XML, so the extension decides nothing --
    # peek at the root element instead. Guessing from the suffix sent every
    # CVAT export to the VOC importer, which rejected it with a confusing
    # "Not a Pascal VOC <annotation> document".
    xml_files = list(base.glob("*.xml"))
    if not xml_files and (base / "Annotations").is_dir():
        xml_files = list((base / "Annotations").glob("*.xml"))
    for path in xml_files[:5]:
        try:
            tag = _ET.parse(path).getroot().tag
        except _ET.ParseError:
            continue
        if tag == "annotations":
            return "cvat"
        if tag == "annotation":
            return "pascal_voc"
    if xml_files:
        return "pascal_voc"

    # Darwin, VIA and LabelMe are all JSON, and again the suffix decides
    # nothing: Darwin has `item` + `annotations`, VIA has `_via_img_metadata`,
    # LabelMe has `shapes` + image fields.
    json_files = sorted(base.rglob("*.json"))
    for path in json_files[:5]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = _json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        if isinstance(doc.get("annotations"), list) and isinstance(
                doc.get("item"), dict):
            return "darwin"
        if "_via_img_metadata" in doc or "_via_settings" in doc:
            return "via"
        if isinstance(doc.get("shapes"), list):
            return "labelme"
    if json_files:
        return "labelme"
    return None


def _load_document(path: str):
    """
    Read a single annotation file into the structure its importer expects.

    Not every format is a JSON object. Labelbox exports are newline-delimited
    JSON, where ``json.load`` fails on line 2 with a message about extra data
    that reads as file corruption rather than a different container — so a
    failed parse falls back to a line-by-line read before giving up.

    Returns ``(data, error_message)``; exactly one is set.
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        first_error = exc

    # NDJSON / JSONL: one complete record per line.
    records = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records = []
            break
    if records:
        logger.info("Read %s as newline-delimited JSON (%d records)",
                    os.path.basename(path), len(records))
        return records, None

    return None, (f"{path} is neither JSON nor newline-delimited JSON: "
                  f"{first_error}")


def _container_format(path: str, explicit: Optional[str]):
    """
    Formats whose single-file input is not a JSON document.

    A ``.tar`` shard and an Open Images ``.csv`` both arrive as ``--input``
    pointing at one file, but neither can be read by ``json.load``. They go
    through the importer's own directory entry point, which knows how to open
    them, rather than failing with "not valid JSON" on a perfectly good file.
    """
    import csv as _csv
    import tarfile as _tarfile

    if explicit in ("webdataset", "openimages"):
        return explicit

    try:
        if _tarfile.is_tarfile(path):
            return "webdataset"
    except (OSError, ValueError):
        pass

    if path.lower().endswith(".csv"):
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                header = set(next(_csv.reader(fh), []) or [])
        except (OSError, StopIteration, UnicodeDecodeError):
            return None
        if {"ImageID", "LabelName"} <= header:
            return "openimages"
    return None


def _run_hub_import(parsed, options) -> int:
    """Import straight from the HuggingFace Hub, which has no local path."""
    from .hf_importer import HuggingFaceImporter

    try:
        result = HuggingFaceImporter().load(
            parsed.hf_dataset, parsed.hf_split, options)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return _write_project(parsed, result, source=parsed.hf_dataset,
                          stem=parsed.hf_dataset.replace("/", "_"))


def main(args=None) -> int:
    parsed = parse_args(args)
    logging.basicConfig(
        level=logging.DEBUG if parsed.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if parsed.list_formats:
        print("Supported annotation import formats:\n")
        for info in import_registry.list_importers():
            exts = ", ".join(info["file_extensions"]) or "-"
            print(f"  {info['name']:<10} {info['description']}")
            print(f"  {'':<10} extensions: {exts}\n")
        return 0

    if not parsed.input and not parsed.hf_dataset:
        print("error: --input is required (or --hf-dataset, or --list-formats)",
              file=sys.stderr)
        return 2
    if not parsed.output_dir:
        print("error: --output-dir is required", file=sys.stderr)
        return 2

    options = {
        "rle_as_polygon": parsed.rle_as_polygon,
        "merge_crowd": not parsed.no_merge_crowd,
        "keypoints": parsed.keypoints,
        "image_url_prefix": parsed.image_url_prefix,
        "via_label_key": parsed.via_label_key,
        "extract_media": parsed.extract_media,
        "hf_split": parsed.hf_split,
        "image_dir": parsed.image_dir,
    }

    # A Hub dataset has no path at all, so it bypasses the file/directory
    # branching entirely.
    if parsed.hf_dataset:
        return _run_hub_import(parsed, options)

    # Most CV formats are DIRECTORY formats -- a dataset is a tree of per-image
    # files, not one document -- so the input may be either.
    is_directory = os.path.isdir(parsed.input)
    if not is_directory and not os.path.isfile(parsed.input):
        print(f"error: no such file or directory: {parsed.input}",
              file=sys.stderr)
        return 2

    data = None
    if is_directory:
        fmt = parsed.input_format or _detect_directory_format(parsed.input)
        if not fmt:
            print(f"error: could not tell what kind of dataset {parsed.input} "
                  f"is. Looked for data.yaml (yolo), label_2/ (kitti), "
                  f"seqinfo.ini (mot), Annotations/*.png (davis), "
                  f"*_gtFine_polygons.json (cityscapes), *.xml (cvat/voc), "
                  f"*.csv (openimages), *.tar (webdataset), *.json "
                  f"(darwin/via/labelme). Pass --input-format.",
                  file=sys.stderr)
            return 2
    else:
        # Container formats are read by the importer itself: a .tar is not text
        # and an Open Images .csv is not JSON, so neither survives a document
        # load. Route them through the directory entry point instead.
        container_fmt = _container_format(parsed.input, parsed.input_format)
        if container_fmt:
            fmt, is_directory = container_fmt, True
        else:
            data, error = _load_document(parsed.input)
            if error:
                print(f"error: {error}", file=sys.stderr)
                return 2

            fmt = parsed.input_format or import_registry.detect_format(data)
            if not fmt:
                supported = ", ".join(import_registry.get_supported_formats())
                print(f"error: could not detect the format of {parsed.input}. "
                      f"Pass --input-format (one of: {supported}).",
                      file=sys.stderr)
                return 2

    if parsed.image_dir and data is not None:
        filled = _probe_dimensions(data, parsed.image_dir)
        if filled:
            logger.info("Read dimensions for %d image(s) from %s",
                        filled, parsed.image_dir)

    try:
        if is_directory:
            importer = import_registry.get(fmt)
            if importer is None or not hasattr(importer, "parse_directory"):
                print(f"error: the {fmt} importer reads a single file, not a "
                      f"directory.", file=sys.stderr)
                return 2
            result = importer.parse_directory(parsed.input, options)
        else:
            result = import_registry.parse(fmt, data, options)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return _write_project(parsed, result, source=parsed.input)


def _write_project(parsed, result, source: str,
                   stem: Optional[str] = None) -> int:
    """
    Turn an ImportResult into a runnable project on disk.

    Split out of ``main`` so the Hub path (``--hf-dataset``), which has no local
    input file at all, produces a byte-identical project rather than a second
    copy of this logic that drifts.
    """
    os.makedirs(parsed.output_dir, exist_ok=True)
    data_dir = os.path.join(parsed.output_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    stem = stem or os.path.splitext(os.path.basename(source))[0]
    data_rel = os.path.join("data", f"{stem}.json")
    data_path = os.path.join(parsed.output_dir, data_rel)

    if not parsed.config_only:
        with open(data_path, "w") as f:
            for image in result.images:
                row = {
                    "id": image.instance_id,
                    # image_width/image_height are exactly the keys
                    # cv_utils.get_image_dimensions() looks for, so COCO exports
                    # carry real sizes and YOLO's can_export() stops failing.
                    "image_width": image.width,
                    "image_height": image.height,
                    "file_name": image.file_name,
                }
                row.update(image.extra)
                if image.objects:
                    row["predictions"] = {
                        parsed.schema_name: image.objects,
                    }
                f.write(json.dumps(row) + "\n")

    config_path = os.path.join(parsed.output_dir, "config.yaml")
    config = _build_config(parsed.schema_name, result, data_rel)
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)

    # Never clobber a README someone has written by hand -- re-running the
    # importer to refresh a data file should not destroy project notes.
    readme_path = os.path.join(parsed.output_dir, "README.md")
    if os.path.exists(readme_path):
        logger.info("README.md already exists; leaving it alone")
    else:
        _write_readme(readme_path, "config.yaml", result, source)

    if parsed.seed_user:
        _write_seed_user(parsed.output_dir, parsed.seed_user,
                         parsed.schema_name, result)

    for warning in result.warnings[:20]:
        logger.warning(warning)
    if len(result.warnings) > 20:
        logger.warning("... and %d more warnings",
                       len(result.warnings) - 20)

    stats = result.stats
    print(f"Imported {stats.get('num_images', 0)} image(s), "
          f"{stats.get('num_annotations', 0)} annotation(s), "
          f"{stats.get('num_categories', 0)} categor(ies) "
          f"into {parsed.output_dir}")
    print(f"\nRun it:\n  python potato/flask_server.py start {config_path} -p 8000")
    return 0


def _write_seed_user(output_dir: str, username: str, schema_name: str,
                     result) -> None:
    """
    Write the imported annotations as a user's saved work.

    This fabricates an annotator and exists only so import->export can be
    verified end to end without a human opening every item. It is off by
    default for exactly that reason.
    """
    user_dir = os.path.join(output_dir, "annotation_output", username)
    os.makedirs(user_dir, exist_ok=True)

    label_to_value = {}
    for image in result.images:
        if not image.objects:
            continue
        label_to_value[image.instance_id] = [
            [{"schema": schema_name, "name": "_data"},
             json.dumps(image.objects)]
        ]

    state = {
        "user_id": username,
        "instance_id_to_label_to_value": label_to_value,
    }
    with open(os.path.join(user_dir, "user_state.json"), "w") as f:
        json.dump(state, f, indent=2)

    logger.warning(
        "--seed-user wrote %d item(s) as '%s'. This is fabricated annotator "
        "work; do not include it in agreement or adjudication analysis.",
        len(label_to_value), username)
