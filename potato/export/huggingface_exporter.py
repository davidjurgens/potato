"""
HuggingFace Hub Exporter

Pushes annotations as a HuggingFace Dataset to the Hub, making them
available for download via `datasets.load_dataset()`.

Requires: pip install huggingface_hub>=0.20.0 datasets>=2.14.0

Usage:
    python -m potato.export \\
        --config config.yaml \\
        --format huggingface \\
        --output your-org/my-annotations \\
        --option token=hf_xxx \\
        --option private=true
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


def _check_deps():
    """Try to import HF dependencies and return them, or raise ImportError."""
    from datasets import Dataset, DatasetDict
    from huggingface_hub import DatasetCard, DatasetCardData
    return Dataset, DatasetDict, DatasetCard, DatasetCardData


class HuggingFaceExporter(BaseExporter):
    """
    Exports annotations to HuggingFace Hub as a Dataset.

    The output_path parameter is used as the repo_id (e.g., "your-org/dataset-name").
    Produces a DatasetDict with an 'annotations' split, plus optional 'spans' and 'items'.
    """

    format_name = "huggingface"
    description = "Push annotations to HuggingFace Hub as a Dataset"
    file_extensions = []  # No local files — pushes to Hub

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        try:
            _check_deps()
        except ImportError:
            return False, (
                "huggingface_hub and datasets are required for HuggingFace export. "
                "Install with: pip install huggingface_hub>=0.20.0 datasets>=2.14.0"
            )

        if not context.annotations:
            return False, "No annotations to export"

        return True, ""

    def build_dataset_dict(self, context: ExportContext,
                           include_spans: bool = True,
                           include_items: bool = True) -> "DatasetDict":
        """
        Build a DatasetDict from an ExportContext without pushing to Hub.

        Args:
            context: ExportContext with annotations, items, schemas
            include_spans: Include a 'spans' split
            include_items: Include an 'items' split

        Returns:
            datasets.DatasetDict with annotations/spans/items splits

        Raises:
            ImportError: If datasets library is not installed
            ValueError: If no data to build
        """
        Dataset, DatasetDict, _, _ = _check_deps()

        schema_map = {s["name"]: s for s in context.schemas}
        splits = {}

        # 1. Annotations split
        ann_rows = self._build_annotation_rows(context.annotations, schema_map)
        if ann_rows:
            splits["annotations"] = Dataset.from_list(ann_rows)

        # 2. Spans split (optional)
        if include_spans:
            span_rows = self._build_span_rows(context.annotations)
            if span_rows:
                splits["spans"] = Dataset.from_list(span_rows)

        # 3. Items split (optional)
        if include_items and context.items:
            item_rows = self._build_item_rows(context.items)
            if item_rows:
                splits["items"] = Dataset.from_list(item_rows)

        if not splits:
            raise ValueError("No data to build — annotations list is empty")

        return DatasetDict(splits)

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings_list = []

        try:
            _, _, DatasetCard, DatasetCardData = _check_deps()
        except ImportError as e:
            return ExportResult(
                success=False,
                format_name=self.format_name,
                errors=[str(e)],
            )

        # Parse options
        repo_id = output_path  # e.g., "your-org/my-annotations"
        token = options.get("token") or os.environ.get("HF_TOKEN")
        private = options.get("private", False)
        commit_message = options.get("commit_message", "Upload annotations from Potato")
        include_items = options.get("include_items", True)
        include_spans = options.get("include_spans", True)

        # Normalize string booleans from CLI
        if isinstance(private, str):
            private = private.lower() not in ("false", "0", "no")
        if isinstance(include_items, str):
            include_items = include_items.lower() not in ("false", "0", "no")
        if isinstance(include_spans, str):
            include_spans = include_spans.lower() not in ("false", "0", "no")

        if not repo_id or "/" not in repo_id:
            return ExportResult(
                success=False,
                format_name=self.format_name,
                errors=[
                    f"output_path must be a HuggingFace repo ID "
                    f"(e.g., 'your-org/dataset-name'), got: '{repo_id}'"
                ],
            )

        try:
            dataset_dict = self.build_dataset_dict(
                context,
                include_spans=include_spans,
                include_items=include_items,
            )

            dataset_dict.push_to_hub(
                repo_id,
                token=token,
                private=private,
                commit_message=commit_message,
            )

            # Compute stats by rebuilding row counts (avoids depending on
            # DatasetDict internals for len/keys).
            schema_map = {s["name"]: s for s in context.schemas}
            ann_rows = self._build_annotation_rows(context.annotations, schema_map)
            span_rows = self._build_span_rows(context.annotations) if include_spans else []
            item_rows = self._build_item_rows(context.items) if include_items and context.items else []

            # Generate and push dataset card
            try:
                card_content = self._build_dataset_card(
                    context, repo_id, ann_rows, schema_map
                )
                card = DatasetCard(card_content)
                card.push_to_hub(repo_id, token=token)
            except Exception as e:
                warnings_list.append(f"Dataset card push failed: {e}")
                logger.warning("Failed to push dataset card: %s", e)

            # Build splits list based on what was actually included
            splits_list = []
            if ann_rows:
                splits_list.append("annotations")
            if span_rows:
                splits_list.append("spans")
            if item_rows:
                splits_list.append("items")

            return ExportResult(
                success=True,
                format_name=self.format_name,
                warnings=warnings_list,
                stats={
                    "repo_id": repo_id,
                    "annotation_rows": len(ann_rows),
                    "span_rows": len(span_rows),
                    "item_rows": len(item_rows),
                    "splits": splits_list,
                    "private": private,
                },
            )

        except ValueError as e:
            return ExportResult(
                success=False,
                format_name=self.format_name,
                errors=[str(e)],
            )
        except Exception as e:
            logger.error("HuggingFace Hub export failed: %s", e)
            return ExportResult(
                success=False,
                format_name=self.format_name,
                errors=[str(e)],
            )

    def _build_annotation_rows(self, annotations: List[dict],
                                schema_map: Dict[str, dict]) -> List[dict]:
        """Build flat row dicts for the annotations dataset."""
        rows = []
        for ann in annotations:
            row = {
                "instance_id": ann.get("instance_id", ""),
                "user_id": ann.get("user_id", ""),
            }

            labels = ann.get("labels", {})
            for schema_name, value in labels.items():
                # Serialize complex values as JSON strings for schema flexibility
                if isinstance(value, (dict, list)):
                    row[schema_name] = json.dumps(value, ensure_ascii=False)
                else:
                    row[schema_name] = value

            rows.append(row)
        return rows

    def _build_span_rows(self, annotations: List[dict]) -> List[dict]:
        """Build flat row dicts for the spans dataset."""
        rows = []
        for ann in annotations:
            instance_id = ann.get("instance_id", "")
            user_id = ann.get("user_id", "")
            spans = ann.get("spans", {})

            for schema_name, span_list in spans.items():
                if not isinstance(span_list, list):
                    continue
                for span in span_list:
                    if not isinstance(span, dict):
                        continue
                    rows.append({
                        "instance_id": instance_id,
                        "user_id": user_id,
                        "schema_name": schema_name,
                        "start": span.get("start"),
                        "end": span.get("end"),
                        "label": span.get("label", ""),
                        "text": span.get("text", ""),
                    })
        return rows

    def _build_item_rows(self, items: Dict[str, dict]) -> List[dict]:
        """Build flat row dicts for the items dataset."""
        rows = []
        for item_id, item_data in items.items():
            row = {"item_id": item_id}
            if isinstance(item_data, dict):
                for key, val in item_data.items():
                    if isinstance(val, (dict, list)):
                        row[key] = json.dumps(val, ensure_ascii=False)
                    else:
                        row[key] = val
            rows.append(row)
        return rows

    def _build_dataset_card(self, context: ExportContext, repo_id: str,
                             ann_rows: List[dict],
                             schema_map: Dict[str, dict]) -> str:
        """Build a DatasetCard markdown string with task metadata."""
        schema_descriptions = []
        for name, schema in schema_map.items():
            ann_type = schema.get("annotation_type", "unknown")
            desc = schema.get("description", "")
            labels = schema.get("labels", [])
            label_str = ", ".join(labels[:10]) if labels else "N/A"
            if len(labels) > 10:
                label_str += f" (+{len(labels) - 10} more)"
            schema_descriptions.append(
                f"- **{name}** ({ann_type}): {desc}\n  Labels: {label_str}"
            )

        schemas_section = "\n".join(schema_descriptions) if schema_descriptions else "N/A"

        card = f"""---
annotations_creators:
- crowdsourced
language_creators:
- expert-generated
source_datasets: []
task_categories:
- text-classification
tags:
- potato-annotation
---

# {repo_id.split('/')[-1]}

Annotations exported from [Potato](https://github.com/davidjurgens/potato) annotation tool.

## Dataset Structure

### Splits

- **annotations**: {len(ann_rows)} annotation records (one per instance-annotator pair)

### Annotation Schemas

{schemas_section}

## Usage

```python
from datasets import load_dataset

ds = load_dataset("{repo_id}")
print(ds["annotations"][0])
```

## Export Details

- Exported by: Potato annotation platform
- Format: HuggingFace Datasets
"""
        return card
