"""
Filter Data by Prior Annotations

Filter data items based on prior annotation
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

    Filtered = filter_items_by_annotation(
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
from typing import List, Dict, Any, Mapping, Optional, Set, Union

logger = logging.getLogger(__name__)


def load_annotations_from_dir(annotation_dir: str, config: Optional[Mapping] = None
                              ) -> Dict[str, Dict[str, Dict[str, Set[str]]]]:
    """
    Load every annotator's answers from an annotation output directory.

    Returns:
        ``{instance_id: {schema_name: {user_id: {selected label names}}}}``

    Each annotator is kept. This used to return one ``{"name", "value"}`` per
    instance and schema, overwritten by each user directory in turn, so with
    several annotators the result was whoever ``iterdir`` listed last, and a
    multiselect kept only its last ticked box.
    """
    from potato.server_utils.answer_collapse import collapse_entries

    from potato.server_utils.stored_states import iter_stored_states, uses_mysql

    annotations: Dict[str, Dict[str, Dict[str, Set[str]]]] = {}

    if not uses_mysql(config) and not Path(annotation_dir).exists():
        logger.warning(f"Annotation directory does not exist: {annotation_dir}")
        return annotations

    for name, user_state in iter_stored_states(annotation_dir, config,
                                               skip_unreadable=True):
        user_id = str(user_state.get("user_id") or name)
        instance_labels = user_state.get("instance_id_to_label_to_value", {})

        for instance_id, label_list in instance_labels.items():
            # label_list is a list of [label_dict, value] pairs
            by_schema: Dict[str, list] = {}
            for label_entry in label_list:
                if isinstance(label_entry, (list, tuple)) and len(label_entry) >= 2:
                    label_dict, value = label_entry[0], label_entry[1]
                    if isinstance(label_dict, dict) and label_dict.get("schema"):
                        by_schema.setdefault(label_dict["schema"], []).append(
                            (label_dict.get("name", ""), value))
            for schema, entries in by_schema.items():
                answer, _w, _m = collapse_entries(entries, schema=schema)
                if answer is None or answer == "":
                    continue
                chosen = {str(a) for a in (answer if isinstance(answer, list) else [answer])}
                annotations.setdefault(str(instance_id), {}).setdefault(schema, {})[user_id] = chosen

    return annotations


#: How several annotators' answers decide whether an item matches.
RULES = ("majority", "any", "all")


def instance_matches(answers_by_user: Dict[str, Set[str]], filter_values: Set[str],
                     rule: str = "majority") -> bool:
    """Whether an item's annotators chose one of ``filter_values``.

    ``majority``: more than half of the annotators who answered did.
    ``any``: at least one did. ``all``: every one did. An item nobody
    answered matches nothing.
    """
    if rule not in RULES:
        raise ValueError(f"Unknown rule {rule!r}; use one of {', '.join(RULES)}")
    votes = [bool(labels & filter_values) for labels in (answers_by_user or {}).values()]
    if not votes:
        return False
    if rule == "any":
        return any(votes)
    if rule == "all":
        return all(votes)
    return sum(votes) * 2 > len(votes)


def filter_loaded_items(items: List[Dict[str, Any]], annotations: dict, schema_name: str,
                        filter_values: Set[str], id_key: str = "id",
                        invert: bool = False, rule: str = "majority") -> List[Dict[str, Any]]:
    """Filter ``items`` against annotations already loaded by
    :func:`load_annotations_from_dir`. Shared by the CLI and the server's
    ``filter_by_prior_annotation``."""
    filtered = []
    for item in items:
        instance_id = str(item.get(id_key, ""))
        if not instance_id:
            logger.warning(f"Item missing id_key '{id_key}': {item}")
            continue
        matches = instance_matches(
            annotations.get(instance_id, {}).get(schema_name, {}), filter_values, rule)
        if invert:
            matches = not matches
        if matches:
            filtered.append(item)
    return filtered


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
    invert: bool = False,
    rule: str = "majority",
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
        rule: How several annotators decide: "majority" (default), "any", "all"

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

    filtered = filter_loaded_items(data_items, annotations, schema_name,
                                   filter_values, id_key, invert, rule)

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

    # One count per annotator answer: an item three people labelled "accept"
    # counts three times. Counting one value per item, the last annotator's,
    # reported 2 annotations where there were 5.
    counts: Dict[str, int] = {}
    for schemas in annotations.values():
        for labels in schemas.get(schema_name, {}).values():
            for value in labels:
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
        "--rule",
        choices=list(RULES),
        default="majority",
        help="With several annotators, match when a majority (default), any, "
             "or all of them chose a value"
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
            print(f"  Total answers: {total}")
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
        invert=args.invert,
        rule=args.rule,
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
