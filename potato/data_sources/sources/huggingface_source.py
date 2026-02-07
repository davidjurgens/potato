"""
Hugging Face Datasets data source.

This module provides data loading from Hugging Face Hub datasets,
supporting both public and private datasets.
"""

import logging
from typing import Any, Dict, Iterator, List, Optional

from potato.data_sources.base import DataSource, SourceConfig

logger = logging.getLogger(__name__)


class HuggingFaceSource(DataSource):
    """
    Data source for Hugging Face Hub datasets.

    Loads data from Hugging Face's datasets library, supporting:
    - Public datasets from the Hub
    - Private datasets with authentication token
    - Specific splits (train, validation, test)
    - Dataset subsets/configurations

    Configuration:
        type: huggingface
        dataset: "squad"           # Required: dataset name
        split: "train"             # Optional: split name (default: train)
        subset: null               # Optional: dataset subset/config
        token: "${HF_TOKEN}"       # Optional: for private datasets

        # Field mapping
        id_field: "id"             # Field to use as item ID
        text_field: "context"      # Field to use as text

    Note: Requires the 'datasets' library: pip install datasets
    """

    # Check for optional dependencies
    _HAS_DATASETS = None

    @classmethod
    def _check_dependencies(cls) -> bool:
        """Check if datasets library is available."""
        if cls._HAS_DATASETS is None:
            try:
                import datasets
                cls._HAS_DATASETS = True
            except ImportError:
                cls._HAS_DATASETS = False
        return cls._HAS_DATASETS

    def __init__(self, config: SourceConfig):
        """Initialize the HuggingFace source."""
        super().__init__(config)

        self._dataset_name = config.config.get("dataset", "")
        self._split = config.config.get("split", "train")
        self._subset = config.config.get("subset")
        self._token = config.config.get("token")

        # Field mapping for converting HF dataset to Potato items
        self._id_field = config.config.get("id_field", "id")
        self._text_field = config.config.get("text_field", "text")
        self._include_fields = config.config.get("include_fields")  # List or None

        self._dataset = None
        self._cached_items: Optional[List[Dict]] = None

    def get_source_id(self) -> str:
        """Get unique identifier."""
        return self._source_id

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = []

        if not self._dataset_name:
            errors.append("'dataset' is required for HuggingFace source")

        return errors

    def is_available(self) -> bool:
        """Check if the source is available."""
        if not self._check_dependencies():
            logger.warning(
                "datasets library not installed. "
                "Install with: pip install datasets"
            )
            return False

        return True

    def _load_dataset(self):
        """Load the HuggingFace dataset."""
        if self._dataset is not None:
            return self._dataset

        from datasets import load_dataset

        load_kwargs = {
            'path': self._dataset_name,
            'split': self._split,
        }

        if self._subset:
            load_kwargs['name'] = self._subset

        if self._token:
            load_kwargs['token'] = self._token

        try:
            self._dataset = load_dataset(**load_kwargs)
            logger.info(
                f"Loaded HuggingFace dataset: {self._dataset_name} "
                f"(split={self._split}, {len(self._dataset)} examples)"
            )
            return self._dataset

        except Exception as e:
            raise RuntimeError(f"Failed to load dataset: {e}")

    def _convert_example(self, example: Dict, index: int) -> Dict[str, Any]:
        """Convert a HuggingFace example to a Potato item."""
        item = {}

        # Handle ID field
        if self._id_field in example:
            item['id'] = str(example[self._id_field])
        else:
            # Generate ID from index
            item['id'] = f"{self._dataset_name}_{self._split}_{index}"

        # Handle text field
        if self._text_field in example:
            item['text'] = example[self._text_field]

        # Include specified fields or all fields
        if self._include_fields:
            for field in self._include_fields:
                if field in example:
                    item[field] = example[field]
        else:
            # Include all fields from the example
            for key, value in example.items():
                if key not in item:
                    # Convert non-serializable types
                    item[key] = self._serialize_value(value)

        return item

    def _serialize_value(self, value: Any) -> Any:
        """Convert a value to a JSON-serializable format."""
        import numpy as np

        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        elif isinstance(value, (list, tuple)):
            return [self._serialize_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        elif isinstance(value, np.ndarray):
            return value.tolist()
        elif hasattr(value, 'item'):  # numpy scalar
            return value.item()
        else:
            return str(value)

    def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch and convert all data from the dataset."""
        dataset = self._load_dataset()

        items = []
        for index, example in enumerate(dataset):
            item = self._convert_example(example, index)
            items.append(item)

        return items

    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Read items from the HuggingFace dataset."""
        # Use cached items if available
        if self._cached_items is not None:
            items = self._cached_items[start:]
            if count is not None:
                items = items[:count]
            yield from items
            return

        # Load dataset
        dataset = self._load_dataset()

        # For partial reading, slice the dataset
        end_index = None
        if count is not None:
            end_index = start + count

        items_yielded = 0
        for index, example in enumerate(dataset):
            if index < start:
                continue
            if end_index is not None and index >= end_index:
                break

            item = self._convert_example(example, index)
            yield item
            items_yielded += 1

    def get_total_count(self) -> Optional[int]:
        """Get total number of items in the dataset."""
        try:
            dataset = self._load_dataset()
            return len(dataset)
        except Exception as e:
            logger.error(f"Error getting dataset count: {e}")
            return None

    def supports_partial_reading(self) -> bool:
        """HuggingFace datasets support efficient partial reading."""
        return True

    def refresh(self) -> bool:
        """Refresh by reloading the dataset."""
        self._dataset = None
        self._cached_items = None
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get source status."""
        status = super().get_status()
        status["dataset"] = self._dataset_name
        status["split"] = self._split
        status["subset"] = self._subset
        status["loaded"] = self._dataset is not None
        return status

    def close(self) -> None:
        """Close the source."""
        self._dataset = None
        self._cached_items = None
