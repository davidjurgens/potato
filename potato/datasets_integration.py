"""
HuggingFace Datasets Integration

Convenience API for loading Potato annotations as HuggingFace Datasets
or pandas DataFrames — no Hub round-trip required.

Requires: pip install datasets>=2.14.0

Usage:
    from potato import load_as_dataset, load_annotations

    # Load as HuggingFace DatasetDict
    ds = load_as_dataset("path/to/config.yaml")
    print(ds["annotations"][0])

    # Load as pandas DataFrame
    df = load_annotations("path/to/config.yaml")
    print(df.head())
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def load_as_dataset(config_path: str,
                    include_spans: bool = True,
                    include_items: bool = True):
    """
    Load Potato annotations as a HuggingFace DatasetDict.

    Reads the config file, loads annotations from the output directory,
    and returns an in-memory DatasetDict with up to three splits:
    'annotations', 'spans', and 'items'.

    Args:
        config_path: Path to the Potato YAML config file
        include_spans: Include a 'spans' split (default True)
        include_items: Include an 'items' split (default True)

    Returns:
        datasets.DatasetDict with annotation data

    Raises:
        ImportError: If the 'datasets' package is not installed
        FileNotFoundError: If config_path does not exist
        ValueError: If no annotations are found
    """
    try:
        from datasets import DatasetDict  # noqa: F401
    except ImportError:
        raise ImportError(
            "The 'datasets' package is required for load_as_dataset(). "
            "Install with: pip install datasets>=2.14.0"
        )

    from potato.export.cli import build_export_context
    from potato.export.huggingface_exporter import HuggingFaceExporter

    context = build_export_context(config_path)
    exporter = HuggingFaceExporter()

    return exporter.build_dataset_dict(
        context,
        include_spans=include_spans,
        include_items=include_items,
    )


def load_annotations(config_path: str):
    """
    Load Potato annotations as a pandas DataFrame.

    Reads the config file, loads annotations from the output directory,
    and returns a flattened DataFrame with one row per (instance, user)
    annotation pair.

    Args:
        config_path: Path to the Potato YAML config file

    Returns:
        pandas.DataFrame with columns: instance_id, user_id, and one
        column per annotation schema

    Raises:
        FileNotFoundError: If config_path does not exist
        ValueError: If no annotations are found
    """
    import json
    import pandas as pd

    from potato.export.cli import build_export_context

    context = build_export_context(config_path)

    if not context.annotations:
        raise ValueError(
            f"No annotations found for config: {config_path}"
        )

    schema_map = {s["name"]: s for s in context.schemas}
    rows = []
    for ann in context.annotations:
        row = {
            "instance_id": ann.get("instance_id", ""),
            "user_id": ann.get("user_id", ""),
        }
        labels = ann.get("labels", {})
        for schema_name, value in labels.items():
            if isinstance(value, (dict, list)):
                row[schema_name] = json.dumps(value, ensure_ascii=False)
            else:
                row[schema_name] = value
        rows.append(row)

    return pd.DataFrame(rows)
