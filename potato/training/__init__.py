"""Model training and the retrain loop.

Importing this package must stay cheap. `store` talks to SQLite through
:mod:`potato.persistence`; `base` and `registry` are dataclasses, an ABC and
name strings. Nothing here imports sklearn, torch or transformers at module
level, and `tests/unit/test_boot_import_weight.py` enforces that.

The trainers themselves live in :mod:`potato.training.trainers` and are
resolved lazily by name, so a project that never trains never pays for the
import.
"""

from potato.training.store import (
    TrainingRun,
    delete_run,
    latest_run,
    list_runs,
    load_run,
    prune_runs,
    record_run,
    record_run_items,
    run_item_splits,
    training_split_ids,
)

__all__ = [
    "TrainingRun",
    "delete_run",
    "latest_run",
    "list_runs",
    "load_run",
    "prune_runs",
    "record_run",
    "record_run_items",
    "run_item_splits",
    "training_split_ids",
]
