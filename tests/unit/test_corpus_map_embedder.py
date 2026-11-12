"""
What the corpus map plots, and whether it says what it plotted.

Two defects, both invisible from the outside:

* the map read `DiversityManager.embeddings`, which the boot prefill filled from
  `item_data.get(text_key, item.get_text())` — and `get_text()` returns an
  item's first string value when there is no text key. A vision corpus was
  therefore a UMAP of `img_01`, `img_02`, …, which looks like a corpus map.
* it refused to run at all without `diversity_ordering` enabled, for no reason
  beyond that being where the vectors lived.

The tests use a fake backend, so nothing here downloads CLIP.
"""

import types

import numpy
import pytest

from potato.embedders import EmbeddingBackend, register, unregister

#: Enough items for UMAP to have neighbours to work with — a three-point
#: corpus fails inside umap-learn for reasons that have nothing to do with
#: what is being tested.
SUBJECTS = ["cat", "dog", "bird", "horse", "otter", "fox", "owl", "bee",
            "crab", "moth", "newt", "hare", "lynx", "mole", "swan", "wolf"]
IMAGE_ITEMS = [
    {"id": f"img_{i:02d}", "image_url": f"media/{name}.jpg"}
    for i, name in enumerate(SUBJECTS, start=1)
]


class RecordingBackend(EmbeddingBackend):
    name = "recording"
    modality = "image"
    default_model = "recording-v1"
    seen = []

    def embed(self, references):
        RecordingBackend.seen.extend(references)
        return numpy.array([[float(i), float(len(r))]
                            for i, r in enumerate(references)])


class FakeItem:
    def __init__(self, data):
        self._data = data

    def get_id(self):
        return self._data["id"]

    def get_data(self):
        return self._data

    def get_text(self):
        # Exactly what the real Item does: first string value.
        for value in self._data.values():
            if isinstance(value, str):
                return value
        return ""


class FakeItemStateManager:
    def __init__(self, items):
        self._items = [FakeItem(d) for d in items]

    def items(self):
        return list(self._items)

    def get_item(self, instance_id):
        for item in self._items:
            if item.get_id() == instance_id:
                return item
        raise KeyError(instance_id)

    def get_annotators_for_item(self, instance_id):
        return []


@pytest.fixture
def backend():
    RecordingBackend.seen = []
    register(RecordingBackend)
    yield RecordingBackend
    unregister("recording")


@pytest.fixture
def viz(monkeypatch, backend):
    from potato import embedding_visualization as ev

    config = ev.EmbeddingVizConfig(enabled=True, sample_size=50)
    app_config = {
        "item_properties": {"text_key": "text"},
        "embeddings": {"backend": "recording", "source_field": "image_url"},
    }
    manager = ev.EmbeddingVisualizationManager(config, app_config)
    if not manager.enabled:
        pytest.skip("umap-learn/numpy not installed")

    ism = FakeItemStateManager(IMAGE_ITEMS)
    monkeypatch.setattr(manager, "_get_item_state_manager", lambda: ism)
    monkeypatch.setattr(manager, "_get_diversity_manager", lambda: None)
    monkeypatch.setattr(manager, "_get_user_state_manager", lambda: None)
    return manager


class TestItEmbedsTheMediaNotTheIds:
    def test_the_image_field_is_what_gets_encoded(self, viz, backend):
        vectors, spec = viz._embed_corpus()
        assert backend.seen[:3] == ["media/cat.jpg", "media/dog.jpg",
                                    "media/bird.jpg"]
        assert not any(r.startswith("img_") for r in backend.seen)  # the regression
        assert set(vectors) == {i["id"] for i in IMAGE_ITEMS}

    def test_the_spec_records_what_was_used(self, viz):
        _, spec = viz._embed_corpus()
        assert spec.backend == "recording"
        assert spec.source_field == "image_url"
        assert spec.modality == "image"

    def test_a_second_call_reuses_the_vectors(self, viz, backend):
        viz._embed_corpus()
        first = len(backend.seen)
        viz._embed_corpus()
        assert len(backend.seen) == first

    def test_force_refresh_recomputes(self, viz, backend):
        viz._embed_corpus()
        first = len(backend.seen)
        viz._embed_corpus(force_refresh=True)
        assert len(backend.seen) > first


class TestItWorksWithoutDiversityOrdering:
    def test_the_map_renders_with_no_diversity_manager(self, viz):
        data = viz.get_visualization_data()
        assert "error" not in data.stats, data.stats.get("error")
        assert len(data.points) == len(IMAGE_ITEMS)

    def test_the_points_carry_the_media_reference_not_the_id(self, viz):
        data = viz.get_visualization_data()
        previews = {p.instance_id: (p.preview, p.preview_type) for p in data.points}
        assert previews["img_01"] == ("media/cat.jpg", "image")

    def test_the_response_says_which_embedder_drew_it(self, viz):
        data = viz.get_visualization_data()
        embedder = data.stats["embedder"]
        assert embedder["backend"] == "recording"
        assert embedder["source_field"] == "image_url"
        assert embedder["available"] is True


class TestItRefusesRatherThanPlottingNonsense:
    def test_an_id_only_corpus_reports_why(self, monkeypatch, backend):
        from potato import embedding_visualization as ev

        manager = ev.EmbeddingVisualizationManager(
            ev.EmbeddingVizConfig(enabled=True), {"item_properties": {}})
        if not manager.enabled:
            pytest.skip("umap-learn/numpy not installed")
        ism = FakeItemStateManager([{"id": "img_01"}, {"id": "img_02"}])
        monkeypatch.setattr(manager, "_get_item_state_manager", lambda: ism)
        monkeypatch.setattr(manager, "_get_diversity_manager", lambda: None)

        data = manager.get_visualization_data()
        assert "error" in data.stats
        assert "nothing to embed" in data.stats["error"]
        assert data.points == []


class TestDiversityManagerAdoptsTheEmbedder:
    def test_use_embedder_swaps_the_encode_function(self, backend):
        from potato.diversity_manager import DiversityConfig, DiversityManager
        from potato.embedders import resolve

        manager = DiversityManager.__new__(DiversityManager)
        manager.logger = __import__("logging").getLogger("test")
        manager.embedder_spec = None
        embedder = resolve({"embeddings": {"backend": "recording",
                                           "source_field": "image_url"}},
                           samples=IMAGE_ITEMS)
        assert manager.use_embedder(embedder) is True
        manager._embed_function(["media/cat.jpg"])
        assert backend.seen == ["media/cat.jpg"]
        assert manager.embedder_spec.backend == "recording"

    def test_an_unavailable_embedder_is_not_adopted(self):
        from potato.diversity_manager import DiversityManager
        from potato.embedders import resolve

        manager = DiversityManager.__new__(DiversityManager)
        manager.logger = __import__("logging").getLogger("test")
        manager.embedder_spec = None
        embedder = resolve({"embeddings": {"backend": "nope"}}, samples=IMAGE_ITEMS)
        assert manager.use_embedder(embedder) is False

    def test_the_text_model_is_not_loaded_at_construction(self):
        """A vision project should not pay for a sentence-transformer it never calls."""
        import inspect
        from potato import diversity_manager

        source = inspect.getsource(diversity_manager.DiversityManager.__init__)
        assert "SentenceTransformer(" not in source
