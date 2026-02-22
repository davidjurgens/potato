"""
Export CLI

Command-line interface for exporting Potato annotations to various formats.

Usage:
    python -m potato.export --config config.yaml --format coco --output ./out/
    python -m potato.export --config config.yaml --format conll_2003 --output ./out/
    python -m potato.export --list-formats
"""

import argparse
import json
import os
import sys
import logging
import glob

import yaml

from .base import ExportContext
from .registry import export_registry

logger = logging.getLogger(__name__)


def load_annotations_from_output_dir(output_dir: str, schemas: list) -> list:
    """
    Load user annotations from the Potato output directory.

    Reads user_state.json files from each user subdirectory
    and flattens annotations into a list of records.

    Args:
        output_dir: Path to the annotation output directory
        schemas: List of annotation scheme configs

    Returns:
        List of annotation dicts
    """
    annotations = []

    if not os.path.isdir(output_dir):
        logger.warning(f"Output directory not found: {output_dir}")
        return annotations

    for user_dir in sorted(os.listdir(output_dir)):
        user_path = os.path.join(output_dir, user_dir)
        if not os.path.isdir(user_path):
            continue

        state_file = os.path.join(user_path, "user_state.json")
        if not os.path.exists(state_file):
            continue

        with open(state_file, "r") as f:
            user_state = json.load(f)

        user_id = user_state.get("user_id", user_dir)

        # Extract label annotations
        label_data = user_state.get("instance_id_to_label_to_value", {})
        span_data = user_state.get("instance_id_to_span_to_value", {})

        # Collect all instance IDs
        all_instances = set(label_data.keys()) | set(span_data.keys())

        for instance_id in all_instances:
            record = {
                "instance_id": instance_id,
                "user_id": user_id,
                "labels": label_data.get(instance_id, {}),
                "spans": {},
                "links": {},
                "image_annotations": {},
            }

            # Process span data
            instance_spans = span_data.get(instance_id, {})
            for schema_name, span_list in instance_spans.items():
                if isinstance(span_list, list):
                    record["spans"][schema_name] = span_list
                elif isinstance(span_list, dict):
                    # Span data might be stored as a dict of span_id -> span_obj
                    record["spans"][schema_name] = list(span_list.values())

            # Extract image annotations from labels
            # Image annotations are stored as JSON strings in label values
            for schema_name, label_dict in record["labels"].items():
                schema_config = _find_schema(schemas, schema_name)
                if schema_config and schema_config.get("annotation_type") == "image_annotation":
                    # Image annotation data is stored in the label value
                    for label_key, value in label_dict.items():
                        if isinstance(value, str):
                            try:
                                parsed = json.loads(value)
                                if isinstance(parsed, list):
                                    record["image_annotations"][schema_name] = parsed
                            except (json.JSONDecodeError, TypeError):
                                pass
                        elif isinstance(value, list):
                            record["image_annotations"][schema_name] = value

            annotations.append(record)

    return annotations


def load_items_from_data_files(config: dict, config_dir: str) -> dict:
    """
    Load item data from the data files specified in config.

    Args:
        config: Full Potato configuration dict
        config_dir: Directory containing the config file

    Returns:
        Dict mapping instance_id -> item data
    """
    items = {}
    item_props = config.get("item_properties", {})
    id_key = item_props.get("id_key", "id")

    data_files = config.get("data_files", [])
    if isinstance(data_files, str):
        data_files = [data_files]

    task_dir = config.get("task_dir", ".")
    base_dir = os.path.normpath(os.path.join(config_dir, task_dir))

    for data_file_entry in data_files:
        if isinstance(data_file_entry, dict):
            path = data_file_entry.get("path", "")
        else:
            path = str(data_file_entry)

        if not os.path.isabs(path):
            path = os.path.join(base_dir, path)

        if not os.path.exists(path):
            logger.warning(f"Data file not found: {path}")
            continue

        with open(path, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    item_id = str(item.get(id_key, f"item_{line_num}"))
                    items[item_id] = item
                except json.JSONDecodeError:
                    # Try CSV/TSV
                    logger.debug(f"Line {line_num} in {path} is not JSON, skipping")

    return items


def _find_schema(schemas: list, name: str) -> dict:
    """Find a schema config by name."""
    for s in schemas:
        if s.get("name") == name:
            return s
    return {}


def build_export_context(config_path: str) -> ExportContext:
    """
    Build an ExportContext from a Potato config file.

    Args:
        config_path: Path to YAML config file

    Returns:
        ExportContext ready for export
    """
    config_path = os.path.abspath(config_path)
    config_dir = os.path.dirname(config_path)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    schemas = config.get("annotation_schemes", [])

    # Determine output directory
    task_dir = config.get("task_dir", ".")
    base_dir = os.path.normpath(os.path.join(config_dir, task_dir))
    output_annotation_dir = config.get(
        "output_annotation_dir",
        os.path.join(base_dir, "annotation_output")
    )
    if not os.path.isabs(output_annotation_dir):
        output_annotation_dir = os.path.join(base_dir, output_annotation_dir)

    items = load_items_from_data_files(config, config_dir)
    annotations = load_annotations_from_output_dir(output_annotation_dir, schemas)

    return ExportContext(
        config=config,
        annotations=annotations,
        items=items,
        schemas=schemas,
        output_dir=output_annotation_dir,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Export Potato annotations to standard formats"
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to Potato YAML config file",
    )
    parser.add_argument(
        "--format", "-f",
        help="Export format (e.g., coco, yolo, pascal_voc, conll_2003, conll_u)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output directory",
        default="./export_output",
    )
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="List available export formats and exit",
    )
    parser.add_argument(
        "--option",
        action="append",
        default=[],
        help="Format-specific option as key=value (can be repeated)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.list_formats:
        formats = export_registry.list_exporters()
        if not formats:
            print("No export formats registered.")
        else:
            print("Available export formats:\n")
            for fmt in formats:
                exts = ", ".join(fmt["file_extensions"])
                print(f"  {fmt['format_name']:15s} {fmt['description']}")
                print(f"  {'':15s} Extensions: {exts}")
                print()
        return

    if not args.config:
        parser.error("--config is required (unless using --list-formats)")
    if not args.format:
        parser.error("--format is required (unless using --list-formats)")

    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    # Parse options
    options = {}
    for opt in args.option:
        if "=" in opt:
            k, v = opt.split("=", 1)
            options[k.strip()] = v.strip()

    # Build context
    print(f"Loading config from: {args.config}")
    context = build_export_context(args.config)
    print(f"Loaded {len(context.items)} items, {len(context.annotations)} annotations")

    # Export
    print(f"Exporting to {args.format} format...")
    result = export_registry.export(args.format, context, args.output, options)

    if result.success:
        print(f"\nExport successful!")
        print(f"Files written:")
        for f in result.files_written:
            print(f"  {f}")
        if result.stats:
            print(f"\nStatistics:")
            for k, v in result.stats.items():
                print(f"  {k}: {v}")
    else:
        print(f"\nExport failed!", file=sys.stderr)
        for err in result.errors:
            print(f"  ERROR: {err}", file=sys.stderr)

    if result.warnings:
        print(f"\nWarnings:")
        for w in result.warnings:
            print(f"  WARNING: {w}")

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
