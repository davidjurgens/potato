"""Active learning on an image-classification study (radio over images).

docs/ai-intelligence/vision_active_learning.md documented a vectorizer that
did not exist: `image` was not a name the manager could build, and a radio or
multiselect scheme handed the vectorizer its text, so such a study was ranked
by TF-IDF over file paths.
"""

import types

from potato.active_learning_manager import (
    ActiveLearningManager, feature_for_item, parse_active_learning_config,
    vectorizer_reads_images)
from potato.server_utils.config_module import validate_active_learning_config


def _cfg():
    return {"active_learning": {"enabled": True, "query_strategy": "uncertainty",
                                "vectorizer": {"name": "image", "hyperparameters":
                                               {"model_name": "clip-ViT-B-32"}}},
            "annotation_schemes": [{"name": "kind", "annotation_type": "radio",
                                    "labels": ["cat", "dog"]}]}


def test_the_documented_config_validates_and_builds_the_image_vectorizer():
    validate_active_learning_config(_cfg())
    al = parse_active_learning_config(_cfg())
    assert al.vectorizer_name == "image" and vectorizer_reads_images(al.vectorizer_name)
    manager = ActiveLearningManager.__new__(ActiveLearningManager)
    manager.config = al
    manager.logger = types.SimpleNamespace(error=print, info=print, warning=print)
    from potato.vision_features import ImageEmbeddingVectorizer
    vec = manager._create_vectorizer()
    assert isinstance(vec, ImageEmbeddingVectorizer)
    assert vec.model_name == "clip-ViT-B-32"


def test_a_radio_scheme_gets_the_image_when_the_vectorizer_reads_images():
    item = types.SimpleNamespace(data={"image_url": "/media/cat1.jpg"},
                                 get_text=lambda: "/media/cat1.jpg")
    assert feature_for_item(item, "radio", None, reads_images=True) == "/media/cat1.jpg"
    text_item = types.SimpleNamespace(data={"text": "a review", "url": "https://x"},
                                      get_text=lambda: "a review")
    # A text vectorizer on a radio scheme still reads the text.
    assert feature_for_item(text_item, "radio", None) == "a review"
