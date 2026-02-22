"""
Filter Data by Prior Annotations

This module provides functionality to filter data items based on prior annotation
decisions. This is particularly useful for workflows like:

1. Triage -> Full Annotation: Filter items that were "accepted" in triage
2. Quality Control: Filter items that passed quality checks
3. Multi-phase Annotation: Chain annotation tasks together

Usage (CLI):
    python -m potato.filter_by_annotation \\
        --annotations annotation_output/ \\
        --data data/items.json \\
        --schema data_quality \\
        --value accept \\
        --output accepted_items.json

Usage (Python):
    from potato.filter_by_annotation import filter_items_by_annotation

    filtered = filter_items_by_annotation(
        annotation_dir="annotation_output/",
        data_file="data/items.json",
        schema_name="data_quality",
        filter_value="accept",
        id_key="id"
    )
"""

import argparse
import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Union

logger = logging.getLogger(__name__)


def load_annotations_from_dir(annotation_dir: str) -> Dict[str, Dict[str, Any]]:
    """
    Load all annotations from an annotation output directory.

    Args:
        annotation_dir: Path to annotation_output directory

    Returns:
        Dict mapping instance_id -> {schema_name -> value}
    """
    annotations = {}
    annotation_path = Path(annotation_dir)

    if not annotation_path.exists():
        logger.warning(f"Annotation directory does not exist: {annotation_dir}")
        return annotations

    # Look for user_state.json files in user subdirectories
    for user_dir in annotation_path.iterdir():
        if not user_dir.is_dir():
            continue

        state_file = user_dir / "user_state.json"
        if not state_file.exists():
            continue

        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                user_state = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load {state_file}: {e}")
            continue

        # Extract label annotations
        instance_labels = user_state.get("instance_id_to_label_to_value", {})

        for instance_id, label_list in instance_labels.items():
            if instance_id not in annotations:
                annotations[instance_id] = {}

            # label_list is a list of [label_dict, value] pairs
            for label_entry in label_list:
                if isinstance(label_entry, (list, tuple)) and len(label_entry) >= 2:
                    label_dict, value = label_entry[0], label_entry[1]
                    schema = label_dict.get("schema", "")
                    name = label_dict.get("name", "")

                    # For triage, the "name" is the decision (accept/reject/skip)
                    # Store both the name and raw value
                    if schema:
                        annotations[instance_id][schema] = {
                            "name": name,
                            "value": value
                        }

    return annotations


def load_data_file(data_file: str) -> List[Dict[str, Any]]:
    """
    Load data from a JSON or JSONL file.

    Args:
        data_file: Path to data file

    Returns:
        List of data items
    """
    data_path = Path(data_file)

    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_file}")

    with open(data_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()

    # Try JSON array first
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    # Try JSONL (newline-delimited JSON)
    items = []
    for line in content.split('\n'):
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return items


def filter_items_by_annotation(
    annotation_dir: str,
    data_file: str,
    schema_name: str,
    filter_value: Union[str, List[str]],
    id_key: str = "id",
    invert: bool = False
) -> List[Dict[str, Any]]:
    """
    Filter data items based on prior annotation decisions.

    Args:
        annotation_dir: Path to annotation_output directory
        data_file: Path to original data file
        schema_name: Name of the annotation schema to filter by
        filter_value: Value(s) to filter for (e.g., "accept" or ["accept", "maybe"])
        id_key: Key in data items containing the instance ID
        invert: If True, return items that DON'T match the filter

    Returns:
        List of filtered data items
    """
    # Normalize filter_value to a set
    if isinstance(filter_value, str):
        filter_values = {filter_value}
    else:
        filter_values = set(filter_value)

    # Load annotations
    annotations = load_annotations_from_dir(annotation_dir)
    logger.info(f"Loaded annotations for {len(annotations)} instances")

    # Load data
    data_items = load_data_file(data_file)
    logger.info(f"Loaded {len(data_items)} data items")

    # Filter items
    filtered = []
    for item in data_items:
        instance_id = str(item.get(id_key, ""))

        if not instance_id:
            logger.warning(f"Item missing id_key '{id_key}': {item}")
            continue

        # Check if this instance has the annotation we're looking for
        instance_annotations = annotations.get(instance_id, {})
        schema_annotation = instance_annotations.get(schema_name, {})

        # Get the annotation value (check both 'name' and 'value' fields)
        anno_value = schema_annotation.get("name") or schema_annotation.get("value")

        matches = anno_value in filter_values

        if invert:
            matches = not matches

        if matches:
            filtered.append(item)

    logger.info(f"Filtered to {len(filtered)} items (schema={schema_name}, value={filter_values})")
    return filtered


def get_annotation_summary(annotation_dir: str, schema_name: str) -> Dict[str, int]:
    """
    Get a summary of annotation value counts for a schema.

    Args:
        annotation_dir: Path to annotation_output directory
        schema_name: Name of the annotation schema

    Returns:
        Dict mapping value -> count
    """
    annotations = load_annotations_from_dir(annotation_dir)

    counts = {}
    for instance_id, schemas in annotations.items():
        if schema_name in schemas:
            value = schemas[schema_name].get("name") or schemas[schema_name].get("value")
            if value:
                counts[value] = counts.get(value, 0) + 1

    return counts


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Filter data items based on prior annotation decisions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Filter for accepted items from triage
  python -m potato.filter_by_annotation \\
      --annotations annotation_output/ \\
      --data data/items.json \\
      --schema data_quality \\
      --value accept \\
      --output accepted_items.json

  # Filter for multiple values
  python -m potato.filter_by_annotation \\
      --annotations annotation_output/ \\
      --data data/items.json \\
      --schema data_quality \\
      --value accept maybe \\
      --output filtered_items.json

  # Show annotation summary
  python -m potato.filter_by_annotation \\
      --annotations annotation_output/ \\
      --schema data_quality \\
      --summary
        """
    )

    parser.add_argument(
        "--annotations", "-a",
        required=True,
        help="Path to annotation_output directory"
    )
    parser.add_argument(
        "--data", "-d",
        help="Path to original data file (JSON or JSONL)"
    )
    parser.add_argument(
        "--schema", "-s",
        required=True,
        help="Name of the annotation schema to filter by"
    )
    parser.add_argument(
        "--value", "-v",
        nargs="+",
        help="Value(s) to filter for (e.g., 'accept' or 'accept maybe')"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path for filtered data"
    )
    parser.add_argument(
        "--id-key",
        default="id",
        help="Key in data items containing the instance ID (default: 'id')"
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Invert filter: return items that DON'T match"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show annotation value summary instead of filtering"
    )
    parser.add_argument(
        "--format",
        choices=["json", "jsonl"],
        default="json",
        help="Output format (default: json)"
    )
    parser.add_argument(
        "--verbose", "-V",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s"
    )

    # Summary mode
    if args.summary:
        counts = get_annotation_summary(args.annotations, args.schema)
        if counts:
            print(f"\nAnnotation summary for schema '{args.schema}':")
            print("-" * 40)
            total = sum(counts.values())
            for value, count in sorted(counts.items(), key=lambda x: -x[1]):
                pct = 100 * count / total
                print(f"  {value}: {count} ({pct:.1f}%)")
            print("-" * 40)
            print(f"  Total: {total}")
        else:
            print(f"No annotations found for schema '{args.schema}'")
        return

    # Filter mode
    if not args.data:
        parser.error("--data is required for filtering (use --summary for summary mode)")
    if not args.value:
        parser.error("--value is required for filtering")
    if not args.output:
        parser.error("--output is required for filtering")

    # Filter items
    filtered = filter_items_by_annotation(
        annotation_dir=args.annotations,
        data_file=args.data,
        schema_name=args.schema,
        filter_value=args.value,
        id_key=args.id_key,
        invert=args.invert
    )

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        if args.format == "jsonl":
            for item in filtered:
                f.write(json.dumps(item) + "\n")
        else:
            json.dump(filtered, f, indent=2)

    print(f"Wrote {len(filtered)} items to {args.output}")


if __name__ == "__main__":
    main()
