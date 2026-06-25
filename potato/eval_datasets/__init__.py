"""
Datasets: versioned collections of evaluation examples.

The backbone of continuous evaluation -- curated example sets (with reference
outputs, splits, and metadata) that experiments run against. Every mutation
produces an immutable version; versions can be tagged (e.g. ``prod``). Storage
is pluggable (``file`` default, or ``sqlite``).
"""

from potato.eval_datasets.config import DatasetsConfig
from potato.eval_datasets.models import Dataset, DatasetVersion, Example
from potato.eval_datasets.storage import DatasetStore, create_store, filter_examples
from potato.eval_datasets.manager import (
    DatasetsManager,
    init_datasets_manager,
    get_datasets_manager,
    clear_datasets_manager,
)

__all__ = [
    "DatasetsConfig",
    "Dataset",
    "DatasetVersion",
    "Example",
    "DatasetStore",
    "create_store",
    "filter_examples",
    "DatasetsManager",
    "init_datasets_manager",
    "get_datasets_manager",
    "clear_datasets_manager",
]
