"""Dataset publishing: package a Potato project for HuggingFace, Zenodo, or a
self-contained local archive, with a rich auto-generated dataset card.

    from potato.publish import run_pipeline, generate_dataset_card

    bundle = run_pipeline("config.yaml", options={"aggregation": "majority"})
    bundle.card_markdown = generate_dataset_card(bundle, target="archive")

The card's data description reuses Paper Mode (``potato.paper``) so a published
README and a paper's methods section report the same numbers.
"""

from potato.publish.bundle import PublishBundle
from potato.publish.config import DatasetMetadata, PublishConfig
from potato.publish.dataset_card import generate_dataset_card
from potato.publish.preprocessing import run_pipeline
from potato.publish.targets import (deposit_to_zenodo, push_to_huggingface,
                                     write_archive)

__all__ = ["PublishBundle", "PublishConfig", "DatasetMetadata",
           "run_pipeline", "generate_dataset_card",
           "write_archive", "push_to_huggingface", "deposit_to_zenodo"]
